#!/usr/bin/env python3
import json
import math
import time

import cereal.messaging as messaging
import numpy as np

from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.gps import get_gps_location_service
from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX, V_CRUISE_UNSET
from openpilot.selfdrive.controls.lib.lead_behavior import (
  is_radarless_matched_follow_window,
  should_hold_tracked_vision_lead,
  should_track_lead,
)
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import A_CHANGE_COST, DANGER_ZONE_COST, J_EGO_COST, STOP_DISTANCE
from openpilot.selfdrive.controls.lib.longitudinal_vehicle_tunes import get_lead_follow_jerk_scale

from openpilot.starpilot.common.vision_bsm import get_fresh_vasm_state, vasm_is_live
from openpilot.starpilot.common.starpilot_utilities import calculate_lane_width, calculate_road_curvature, extract_curve_profile
from openpilot.starpilot.common.starpilot_variables import CRUISING_SPEED, MINIMUM_LATERAL_ACCELERATION, PLANNER_TIME, THRESHOLD
from openpilot.starpilot.controls.lib.conditional_chill_mode import ConditionalChillMode
from openpilot.starpilot.controls.lib.conditional_experimental_mode import ConditionalExperimentalMode
from openpilot.starpilot.controls.lib.nav_passing import Lead, NavPassingAdvisor, PassingInputs, edge_gap
from openpilot.starpilot.controls.lib.speed_limit_controller import SOURCE_NONE
from openpilot.starpilot.controls.lib.starpilot_acceleration import StarPilotAcceleration
from openpilot.starpilot.controls.lib.starpilot_events import StarPilotEvents
from openpilot.starpilot.controls.lib.starpilot_following import StarPilotFollowing
from openpilot.starpilot.controls.lib.starpilot_vcruise import StarPilotVCruise
from openpilot.starpilot.controls.lib.weather_checker import WeatherChecker

RADARLESS_TRACK_HOLD_TIME = 0.45
PASSING_MIN_LANE_WIDTH = 2.5  # m, D-114
GPS_MEMORY_REFRESH_SECONDS = 0.25
GPS_NEW_FIX_REFRESH_SECONDS = 0.1  # a new fix is published at once; its timestamp starts the map's dead reckoning
FORCE_STOP_JERK_SCALE = 0.20  # accel-change cost multiplier for the whole stop approach,
                              # envelope included (125 -> 25). Lower = reaches the braking
                              # target sooner; it does not make the target deeper. Response
                              # is super-linear here, so raise it if onset feels like a step.
FORCE_STOP_JERK_SCALE_OVERRIDES = {
  # The Elantra's current force-stop ramp is smooth, but it waits too long
  # before building decel and then arrives at the initial brake too abruptly.
  # Increase the accel-change cost to spread the same stop over more time;
  # this does not alter the force-stop distance.
  "HYUNDAI_ELANTRA_2021": 0.80,
}


def get_force_stop_jerk_scale(car_params):
  fingerprint = str(getattr(car_params, "carFingerprint", ""))
  return FORCE_STOP_JERK_SCALE_OVERRIDES.get(fingerprint, FORCE_STOP_JERK_SCALE)


def _sanitize_json_value(value):
  if isinstance(value, float):
    return value if math.isfinite(value) else None
  if isinstance(value, dict):
    return {k: _sanitize_json_value(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [_sanitize_json_value(v) for v in value]
  return value


def serialize_starpilot_toggles(starpilot_toggles):
  return json.dumps(_sanitize_json_value(vars(starpilot_toggles)), allow_nan=False)


class StarPilotPlanner:
  def __init__(self, error_log, ThemeManager):
    self.params = Params(return_defaults=True)
    self.params_memory = Params(memory=True)

    self.starpilot_acceleration = StarPilotAcceleration(self)
    self.starpilot_cem = ConditionalExperimentalMode(self)
    self.starpilot_ccm = ConditionalChillMode(self, self.starpilot_cem)
    self.starpilot_events = StarPilotEvents(self, error_log, ThemeManager)
    self.starpilot_following = StarPilotFollowing(self)
    self.starpilot_vcruise = StarPilotVCruise(self)
    self.starpilot_weather = WeatherChecker(self)

    self.nav_passing = NavPassingAdvisor()
    self._passing_last = None
    self._passing_last_t = 0.0
    self._passing_publish_disabled = False
    self._passing_chimed = set()
    self.nav_passing_chime = ""

    self.driving_in_curve = False
    self.gps_valid = False
    self.lateral_check = False
    self.model_stopped = False
    self.raw_model_stopped = False
    self.road_curvature_detected = False
    self.tracking_lead = False
    self._last_gps_memory_state = ""
    self._last_gps_memory_write = 0.0
    self._last_gps_fix: tuple[float, float, float] | None = None
    self._prev_gps_bearing = 0

    # Blinker-based lateral resume delay state
    self.blinker_min_speed = float('inf')
    self.blinker_delay_active = False
    self.blinker_delay_frame = 0
    self.CS_prev_left_blinker = False
    self.CS_prev_right_blinker = False

    self.lane_width_left = 0
    self.lane_width_right = 0
    self.edge_gap_left = 99.0
    self.edge_gap_right = 99.0
    self._lane_width_counter = 0
    self.lateral_acceleration = 0
    self.model_length = 0
    self.lead_path_y = 0
    self.road_curvature = 0
    self.time_to_curve = 0
    self.v_cruise = 0

    self.gps_position = None

    self.gps_location_service = get_gps_location_service(self.params)

    self.tracking_lead_filter = FirstOrderFilter(0, 0.5, DT_MDL)
    self.radarless_follow_hold_until = 0.0

  def shutdown(self):
    self.starpilot_vcruise.csc.flush_data()
    self.starpilot_vcruise.slc.shutdown()
    self.starpilot_weather.executor.shutdown(wait=False, cancel_futures=True)

  def update(self, now, time_validated, sm, starpilot_toggles):
    self.lead_one = sm["radarState"].leadOne

    controls_enabled = sm["selfdriveState"].enabled

    v_cruise_kph = min(sm["carState"].vCruise, V_CRUISE_MAX)
    if 0 < v_cruise_kph < V_CRUISE_UNSET and starpilot_toggles.set_speed_offset > 0:
      v_cruise_kph += starpilot_toggles.set_speed_offset
    v_cruise = v_cruise_kph * CV.KPH_TO_MS
    v_ego = max(sm["carState"].vEgo, 0)

    gps_location = sm[self.gps_location_service]
    self.gps_position = {
      "latitude": gps_location.latitude,
      "longitude": gps_location.longitude,
      "bearing": gps_location.bearingDeg,
      "speed": v_ego,
      "hasFix": bool(getattr(gps_location, "hasFix", False)),
      "updatedAtMonotonic": time.monotonic(),
      "updatedAtSec": time.time(),
    }
    self.gps_valid = self.gps_position["hasFix"] and (self.gps_position["latitude"] != 0 or self.gps_position["longitude"] != 0)
    bearing = self.gps_position["bearing"]
    if self.gps_valid:
      gps_memory_state = json.dumps(_sanitize_json_value(self.gps_position), allow_nan=False)
      now_mono = self.gps_position["updatedAtMonotonic"]
      fix = (self.gps_position["latitude"], self.gps_position["longitude"], bearing)
      interval = GPS_NEW_FIX_REFRESH_SECONDS if fix != self._last_gps_fix else GPS_MEMORY_REFRESH_SECONDS
      should_refresh_memory = gps_memory_state != self._last_gps_memory_state and (now_mono - self._last_gps_memory_write) >= interval
      if should_refresh_memory:
        self.params_memory.put_nonblocking("LastGPSPosition", gps_memory_state)
        self._last_gps_memory_state = gps_memory_state
        self._last_gps_memory_write = now_mono
        self._last_gps_fix = fix

    if getattr(starpilot_toggles, "compass", False) and abs(bearing - self._prev_gps_bearing) > 0.5:
      self._prev_gps_bearing = bearing

    if v_ego >= starpilot_toggles.minimum_lane_change_speed:
      self._lane_width_counter += 1
      if self._lane_width_counter % 4 == 0:
        self.lane_width_left = calculate_lane_width(sm["modelV2"].laneLines[0], sm["modelV2"].laneLines[1], sm["modelV2"].roadEdges[0])
        self.lane_width_right = calculate_lane_width(sm["modelV2"].laneLines[3], sm["modelV2"].laneLines[2], sm["modelV2"].roadEdges[1])
        lines, edges = sm["modelV2"].laneLines, sm["modelV2"].roadEdges
        if len(lines) == 4 and len(edges) == 2:
          self.edge_gap_left = edge_gap(lines[0].x, lines[0].y, edges[0].x, edges[0].y)
          self.edge_gap_right = edge_gap(lines[3].x, lines[3].y, edges[1].x, edges[1].y)
    else:
      self._lane_width_counter = 0
      self.lane_width_left = 0
      self.lane_width_right = 0

    self.lateral_acceleration = v_ego**2 * sm["controlsState"].curvature
    self.driving_in_curve = abs(self.lateral_acceleration) >= MINIMUM_LATERAL_ACCELERATION

    CS = sm["carState"]
    blinker_on = CS.leftBlinker or CS.rightBlinker
    signal_pause = blinker_on and starpilot_toggles.pause_lateral_below_signal

    self.lateral_check = v_ego >= starpilot_toggles.pause_lateral_below_speed
    self.lateral_check |= not blinker_on and starpilot_toggles.pause_lateral_below_signal
    self.lateral_check |= CS.standstill and not signal_pause
    self.lateral_check &= not sm["starpilotCarState"].pauseLateral

    # Blinker-based lateral resume delay: after blinker turns off, delay lateral
    # resumption if the vehicle went below half the pause speed during the blinker.
    # This lets the driver manually straighten the wheel after a turn without
    # openpilot fighting them.
    prev_blinker_on = self.CS_prev_left_blinker or self.CS_prev_right_blinker

    if blinker_on:
      # Track minimum speed while blinker is active
      if not prev_blinker_on:
        self.blinker_min_speed = CS.vEgo
      else:
        self.blinker_min_speed = min(self.blinker_min_speed, CS.vEgo)
      self.blinker_delay_active = False
    elif prev_blinker_on and starpilot_toggles.pause_lateral_below_signal and starpilot_toggles.pause_lateral_signal_delay > 0:
      # Blinker just turned off — start the delay timer
      self.blinker_delay_active = True
      self.blinker_delay_frame = sm.frame

    if self.blinker_delay_active:
      time_since_blinker = (sm.frame - self.blinker_delay_frame) * DT_MDL
      if time_since_blinker < starpilot_toggles.pause_lateral_signal_delay and \
         self.blinker_min_speed < starpilot_toggles.pause_lateral_below_speed / 2:
        self.lateral_check = False
      else:
        self.blinker_delay_active = False

    self.CS_prev_left_blinker = CS.leftBlinker
    self.CS_prev_right_blinker = CS.rightBlinker

    self.model_length = sm["modelV2"].position.x[-1]
    model_position = sm["modelV2"].position
    model_path_y = getattr(model_position, "y", [])
    if len(model_path_y) == len(model_position.x):
      self.lead_path_y = float(np.interp(self.lead_one.dRel, model_position.x, model_path_y))
    else:
      self.lead_path_y = 0.0

    self.raw_model_stopped = self.model_length < CRUISING_SPEED * PLANNER_TIME
    self.model_stopped = self.raw_model_stopped or self.starpilot_vcruise.forcing_stop

    self.road_curvature, self.time_to_curve = calculate_road_curvature(sm["modelV2"], v_ego)
    self.curve_profile = extract_curve_profile(sm["modelV2"])

    self.road_curvature_detected = (1 / abs(self.road_curvature))**0.5 < v_ego > CRUISING_SPEED and not (sm["carState"].leftBlinker or sm["carState"].rightBlinker)

    if not sm["carState"].standstill:
      self.tracking_lead = self.update_lead_status(v_ego)

    self.starpilot_following.update(controls_enabled, v_ego, sm, starpilot_toggles)

    conditional_tracking_active = controls_enabled or sm["starpilotCarState"].alwaysOnLateralEnabled
    if conditional_tracking_active and bool(getattr(starpilot_toggles, "conditional_experimental_mode", False)):
      # Keep CEM's filters warm in AOL so engagement can inherit the current scene.
      self.starpilot_cem.update(v_ego, sm, starpilot_toggles, v_cruise)
      self.starpilot_ccm.deactivate()
    elif conditional_tracking_active and bool(getattr(starpilot_toggles, "conditional_chill_mode", False)):
      self.starpilot_ccm.update(v_ego, v_cruise, sm, starpilot_toggles)
      self.starpilot_cem.deactivate()
    else:
      self.starpilot_ccm.deactivate()
      self.starpilot_cem.deactivate()
      self.starpilot_cem.curve_detected = False
      self.starpilot_cem.stop_sign_and_light(v_ego, sm, PLANNER_TIME - 2)

    self.v_cruise = self.starpilot_vcruise.update(controls_enabled, now, time_validated, v_cruise, v_ego, sm, starpilot_toggles)

    if controls_enabled:
      self.starpilot_acceleration.update(v_ego, sm, starpilot_toggles)
      if self.starpilot_acceleration.pulse_glide_target is not None:
        self.v_cruise = self.starpilot_acceleration.pulse_glide_target
    else:
      self.starpilot_acceleration.max_accel = 0
      self.starpilot_acceleration.min_accel = 0
      self.starpilot_acceleration.gas_override_coast = False

    self.update_nav_passing(sm, starpilot_toggles, v_ego)

    self.starpilot_events.update(controls_enabled, v_cruise, sm, starpilot_toggles)

    if self.gps_valid and time_validated and starpilot_toggles.weather_presets:
      self.starpilot_weather.update_weather(now, starpilot_toggles)
    else:
      self.starpilot_weather.weather_id = 0

  def _passing_speed_limit(self):
    # a real posted limit only: SLC's set-speed fallback has no source and is not a limit
    slc = self.starpilot_vcruise.slc
    return float(slc.target or 0.0) if getattr(slc, "source", SOURCE_NONE) != SOURCE_NONE else 0.0

  def _passing_speed_offset(self, limit):
    # the owner's SLC offset for this limit: openpilot may drive up to limit + offset
    return 0.0 if limit <= 0.0 else float(self.starpilot_vcruise.slc.get_offset(limit) or 0.0)

  def _passing_inputs(self, sm, starpilot_toggles, v_ego, now):
    CS = sm["carState"]
    radar = sm["starpilotRadarState"]
    vasm_on = bool(getattr(starpilot_toggles, "v_asm_enabled", False))
    vasm_live = vasm_on and vasm_is_live(self.params_memory, now)
    vasm_left, vasm_right = get_fresh_vasm_state(self.params_memory, now) if vasm_live else (False, False)

    def lead(l):
      return Lead(bool(l.status), float(l.dRel), float(l.vLead))

    speed_limit = self._passing_speed_limit()
    return PassingInputs(
      enabled=True,
      nav_state=self.starpilot_vcruise._nav_instruction_state,
      v_ego=v_ego,
      speed_limit=speed_limit,
      speed_offset=self._passing_speed_offset(speed_limit),
      min_lane_change_speed=float(starpilot_toggles.minimum_lane_change_speed),
      lead=lead(self.lead_one), lead_left=lead(radar.leadLeft), lead_right=lead(radar.leadRight),
      lane_width_left=float(self.lane_width_left), lane_width_right=float(self.lane_width_right),
      edge_gap_left=float(self.edge_gap_left), edge_gap_right=float(self.edge_gap_right),
      # floor: with Lane Changes off the toggle reads 0, which would make any gap count as a lane
      lane_detection_width=max(float(starpilot_toggles.lane_detection_width), PASSING_MIN_LANE_WIDTH),
      vasm_live=vasm_live,
      blocked_left=bool(CS.leftBlindspot or vasm_left), blocked_right=bool(CS.rightBlindspot or vasm_right),
      left_blinker=bool(CS.leftBlinker), right_blinker=bool(CS.rightBlinker),
    )

  def update_nav_passing(self, sm, starpilot_toggles, v_ego):
    """D-114: publish the pass / move-back suggestion. Prompt only; the driver's blinker does the lane change."""
    self.nav_passing_chime = ""
    if self._passing_publish_disabled:
      return
    now = time.monotonic()
    passing = bool(getattr(starpilot_toggles, "nav_passing_suggest", False))
    exit_warn = bool(getattr(starpilot_toggles, "nav_exit_only_warn", False))
    keep_right = bool(getattr(starpilot_toggles, "nav_keep_right", False))
    if passing or exit_warn or keep_right:
      inputs = self._passing_inputs(sm, starpilot_toggles, v_ego, now)
      inputs.enabled, inputs.exit_warn, inputs.keep_right = passing, exit_warn, keep_right
    else:
      inputs = PassingInputs(False, {}, v_ego, 0.0, 0.0, Lead(), Lead(), Lead(), 0.0, 0.0, 0.0, False, False, False, False, False)
    prompt = self.nav_passing.update(inputs, now)
    # one chime per phase per episode, so a flickering right-side block does not re-chime the return prompt
    phase = prompt["phase"] if prompt["armed"] else ""
    self.nav_passing_chime = phase if phase and phase not in self._passing_chimed else ""
    if phase:
      self._passing_chimed.add(phase)
    elif self.nav_passing.state == "idle":
      self._passing_chimed -= {"pass", "return", "keepright"}
    # D-116: with no suggestion up, say why the jam slowdown is easing off. No chime; the banner only.
    jam = getattr(self.starpilot_vcruise, "nav_jam_notice", None)
    if not prompt["armed"] and jam is not None:
      prompt = {"armed": True, "side": "", "phase": "jam", "ts": now,
                "distance": float(round(jam[0] / 10.0) * 10.0), "speed": round(float(jam[1]), 1)}
    # one exit-only chime per junction: re-arm only once navigationd reports no exit-only lane ahead
    if phase != "exit" and float(inputs.nav_state.get("exitOnlyDistance", -1.0) or -1.0) <= 0.0:
      self._passing_chimed.discard("exit")
    key = (prompt["armed"], prompt["side"], prompt["phase"])
    # rewrite every 1 s while armed so the UI can drop a stale prompt by timestamp
    if key == self._passing_last and not (prompt["armed"] and now - self._passing_last_t >= 1.0):
      return
    self._passing_last, self._passing_last_t = key, now
    try:
      self.params_memory.put_nonblocking("NavPassingPrompt", prompt)
    except UnknownKeyName:
      self._passing_publish_disabled = True

  def update_lead_status(self, v_ego):
    following_lead = should_track_lead(
      self.lead_one.status,
      self.lead_one.dRel,
      self.model_length,
      STOP_DISTANCE,
      v_ego,
      v_lead=self.lead_one.vLead,
      radar=bool(getattr(self.lead_one, "radar", False)),
    )
    continuity_candidate = self.tracking_lead or self.tracking_lead_filter.x >= THRESHOLD * 0.6
    if not following_lead and continuity_candidate:
      following_lead = should_hold_tracked_vision_lead(
        self.lead_one.status,
        self.lead_one.dRel,
        self.model_length,
        STOP_DISTANCE,
        v_ego,
        model_prob=float(getattr(self.lead_one, "modelProb", 0.0)),
        y_rel=float(getattr(self.lead_one, "yRel", 0.0)),
        path_y=self.lead_path_y,
        radar=bool(getattr(self.lead_one, "radar", False)),
      )
    now_t = time.monotonic()
    lead_radar = bool(getattr(self.lead_one, "radar", False))
    t_follow = max(float(getattr(self.starpilot_following, "t_follow", 0.0)), 1.45)
    matched_follow_window = self.lead_one.status and is_radarless_matched_follow_window(
      v_ego,
      self.lead_one.dRel,
      self.lead_one.vLead,
      t_follow,
      radar=lead_radar,
      lead_brake=max(0.0, -float(getattr(self.lead_one, "aLeadK", 0.0))),
      lead_prob=float(getattr(self.lead_one, "modelProb", 0.0)),
    )
    if matched_follow_window and (following_lead or self.tracking_lead or self.tracking_lead_filter.x >= THRESHOLD * 0.6):
      self.radarless_follow_hold_until = now_t + RADARLESS_TRACK_HOLD_TIME
    elif lead_radar or not self.lead_one.status:
      self.radarless_follow_hold_until = 0.0

    if not following_lead and matched_follow_window and now_t < self.radarless_follow_hold_until:
      following_lead = True

    self.tracking_lead_filter.update(following_lead)
    return self.tracking_lead_filter.x >= THRESHOLD

  def publish(self, theme_updated, sm, pm, starpilot_toggles, serialized_toggles=""):
    starpilot_plan_send = messaging.new_message("starpilotPlan")
    starpilot_plan_send.valid = sm.all_checks(service_list=["carState", "controlsState", "selfdriveState", "radarState"])
    starpilotPlan = starpilot_plan_send.starpilotPlan

    # While committed to a Force Stop, cut the MPC's accel-change penalty so terminal
    # braking can ramp faster. 0.32 lands near 40, what long_mpc uses in blended mode.
    try:
      car_params = sm["carParams"]
    except (KeyError, IndexError, TypeError, AttributeError):
      car_params = None

    # Also while the far-approach envelope is running: at onset the ramp reaches only
    # ~-0.5 m/s^2 after a second, so the first seconds of a detected red are mostly lost.
    if self.starpilot_vcruise.forcing_stop or self.starpilot_vcruise.approach_stop_length > 0.0:
      jerk_scale = get_force_stop_jerk_scale(car_params)
    elif self.tracking_lead:
      jerk_scale = get_lead_follow_jerk_scale(car_params)
    else:
      jerk_scale = 1.0
    starpilotPlan.accelerationJerk = float(A_CHANGE_COST * self.starpilot_following.acceleration_jerk * jerk_scale)
    starpilotPlan.dangerFactor = float(self.starpilot_following.danger_factor)
    starpilotPlan.dangerJerk = float(DANGER_ZONE_COST * self.starpilot_following.danger_jerk)
    starpilotPlan.speedJerk = float(J_EGO_COST * self.starpilot_following.speed_jerk)
    starpilotPlan.tFollow = float(self.starpilot_following.t_follow)

    starpilotPlan.cscControllingSpeed = self.starpilot_vcruise.csc_controlling_speed
    starpilotPlan.cscSpeed = float(self.starpilot_vcruise.csc_target)
    starpilotPlan.cscTraining = self.starpilot_vcruise.csc.enable_training
    # The static controller (CurveSpeedManualScaling on) answers the same interface: its slider
    # value as the lat accel, no binding distance, and csc_override stays False.
    starpilotPlan.cscOverridden = self.starpilot_vcruise.csc_override
    starpilotPlan.cscLearnedLatAccel = float(self.starpilot_vcruise.csc.learned_lat_accel(self.road_curvature))
    starpilotPlan.cscBindingDistance = float(self.starpilot_vcruise.csc.binding_distance)

    starpilotPlan.desiredFollowDistance = int(self.starpilot_following.desired_follow_distance)
    starpilotPlan.disableThrottle = (
      self.starpilot_following.disable_throttle or
      self.starpilot_acceleration.pulse_glide_coasting
    )
    starpilotPlan.pulseGlideCoasting = self.starpilot_acceleration.pulse_glide_coasting
    starpilotPlan.trackingLead = self.tracking_lead

    conditional_experimental_mode = False
    if starpilot_toggles.conditional_experimental_mode:
      conditional_experimental_mode = self.starpilot_cem.experimental_mode
    elif starpilot_toggles.conditional_chill_mode:
      conditional_experimental_mode = self.starpilot_ccm.experimental_mode

    starpilotPlan.experimentalMode = conditional_experimental_mode or self.starpilot_vcruise.slc.experimental_mode

    starpilotPlan.forcingStop = self.starpilot_vcruise.forcing_stop
    starpilotPlan.forcingStopLength = self.starpilot_vcruise.tracked_model_length
    starpilotPlan.approachStopLength = float(self.starpilot_vcruise.approach_stop_length)
    starpilotPlan.stopSignConfirmed = self.starpilot_vcruise.stop_sign_confirmed

    starpilotPlan.starpilotEvents = self.starpilot_events.events.to_msg()

    starpilotPlan.starpilotToggles = serialized_toggles

    if sm["starpilotCarState"].trafficModeEnabled:
      starpilotPlan.increasedStoppedDistance = 0
    else:
      starpilotPlan.increasedStoppedDistance = starpilot_toggles.increase_stopped_distance
      if self.starpilot_weather.weather_id != 0:
        starpilotPlan.increasedStoppedDistance += self.starpilot_weather.increase_stopped_distance

    starpilotPlan.laneWidthLeft = self.lane_width_left
    starpilotPlan.laneWidthRight = self.lane_width_right

    starpilotPlan.lateralCheck = self.lateral_check

    starpilotPlan.maxAcceleration = float(self.starpilot_acceleration.max_accel)
    starpilotPlan.minAcceleration = float(self.starpilot_acceleration.min_accel)

    starpilotPlan.redLight = self.starpilot_cem.stop_light_detected

    starpilotPlan.roadCurvature = self.road_curvature

    starpilotPlan.slcMapSpeedLimit = self.starpilot_vcruise.slc.map_speed_limit
    starpilotPlan.slcMapboxSpeedLimit = self.starpilot_vcruise.slc.mapbox_limit
    starpilotPlan.slcNextSpeedLimit = self.starpilot_vcruise.slc.next_speed_limit
    starpilotPlan.slcOverriddenSpeed = self.starpilot_vcruise.slc.overridden_speed
    starpilotPlan.slcSpeedLimit = self.starpilot_vcruise.slc_target
    starpilotPlan.slcSpeedLimitOffset = self.starpilot_vcruise.slc_offset
    starpilotPlan.slcSpeedLimitSource = self.starpilot_vcruise.slc.source
    starpilotPlan.slcPresentedSpeedLimitSource = self.starpilot_vcruise.slc.presented_source
    starpilotPlan.slcIsLimitingMaxSet = self.starpilot_vcruise.slc_is_limiting_max_set
    starpilotPlan.speedLimitChanged = self.starpilot_vcruise.slc.confirmation_pending
    starpilotPlan.unconfirmedSlcSpeedLimit = self.starpilot_vcruise.slc.unconfirmed_speed_limit

    starpilotPlan.themeUpdated = theme_updated

    starpilotPlan.vCruise = float(self.v_cruise)

    starpilotPlan.weatherDaytime = self.starpilot_weather.is_daytime
    starpilotPlan.weatherId = self.starpilot_weather.weather_id

    pm.send("starpilotPlan", starpilot_plan_send)
