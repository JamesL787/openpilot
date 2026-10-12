import json
import math
import time

import numpy as np

from cereal import log
from openpilot.common.constants import CV
from openpilot.common.params import Params, UnknownKeyName
from openpilot.common.realtime import DT_MDL
from openpilot.starpilot.common.vision_bsm import get_fresh_vasm_state
from openpilot.starpilot.controls.lib.lateral_edge_guard import LateralEdgeGuard
from openpilot.starpilot.controls.lib.nav_lane_prompt import nav_lane_move_prompt

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.
LANE_CHANGE_NUDGE_TORQUE_THRESHOLD = 1200
NAV_EXIT_COMMIT_DISTANCE = 500.0
# D-107: lowest speed at which NavExitAutoKeep applies the exit keep without a wheel nudge
NAV_EXIT_AUTO_KEEP_MIN_SPEED = 8.0
# D-108: the driver steering against a started lane change for this long cancels it (LaneChangeCounterTorqueCancel)
LANE_CHANGE_CANCEL_TORQUE_FRAMES = round(0.25 / DT_MDL)
NAV_TURN_DISTANCE_SPEED_BREAKPOINTS = [0.0, 5.0, 10.0]
NAV_TURN_DISTANCE_BREAKPOINTS = [20.0, 25.0, 30.0]
NAV_KEEP_DISTANCE_SPEED_BREAKPOINTS = [0.0, 15.0, 30.0]
NAV_KEEP_DISTANCE_BREAKPOINTS = [25.0, 90.0, 160.0]
NAV_KEEP_AMBIGUOUS_SPLIT_DISTANCE_SCALE = 0.6
NAV_KEEP_SMALL_SPLIT_MAX_OTHER_LANES = 2

TURN_DESIRE_PULSE_CYCLE_FRAMES = round(5.0 / DT_MDL)
TURN_DESIRE_PULSE_HOLD_FRAMES = TURN_DESIRE_PULSE_CYCLE_FRAMES - 1
TURN_RECOIL_HEADING_RAD = math.radians(55.0)
TURN_DESIRE_MAX_SECONDS = 25.0
TURN_DESIRE_MOVING_SPEED = 0.5

DESIRES = {
  LaneChangeDirection.none: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.none,
    LaneChangeState.laneChangeFinishing: log.Desire.none,
  },
  LaneChangeDirection.left: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeLeft,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeLeft,
  },
  LaneChangeDirection.right: {
    LaneChangeState.off: log.Desire.none,
    LaneChangeState.preLaneChange: log.Desire.none,
    LaneChangeState.laneChangeStarting: log.Desire.laneChangeRight,
    LaneChangeState.laneChangeFinishing: log.Desire.laneChangeRight,
  },
}

TurnDirection = log.Desire

TURN_DESIRES = {
  TurnDirection.none: log.Desire.none,
  TurnDirection.turnLeft: log.Desire.turnLeft,
  TurnDirection.turnRight: log.Desire.turnRight,
}


class DesireHelper:
  def __init__(self):
    self.params_memory = Params(memory=True)
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.lane_change_ll_prob = 1.0
    self.keep_pulse_timer = 0.0
    self.prev_one_blinker = False
    self.prev_nav_exit_active = False
    self.nav_exit_rearmed = False
    self.desire = log.Desire.none
    self.nav_desire = log.Desire.none

    self.lane_change_completed = False

    self.lane_change_wait_timer = 0.0
    self.counter_torque_frames = 0
    self.edge_guard = LateralEdgeGuard()
    self.nav_desires_allowed = False
    self.nav_lane_positioning_allowed = False
    self.nav_exit_lane_change = False
    self.turn_desire_frames = 0
    self.turn_desire_cycle_input = log.Desire.none
    self.turn_heading_rad = 0.0
    self.turn_desire_seconds = 0.0
    self.turn_recoiled = False
    self._nav_instruction_state_raw: object = None
    self._nav_instruction_state: dict[str, object] = {}
    self._prompt_last = None
    self._prompt_publish_disabled = False
    self._prompt_last_t = 0.0

  def _update_nav_params(self):
    raw = self.params_memory.get("NavInstructionState") or {}
    if raw == self._nav_instruction_state_raw:
      return

    self._nav_instruction_state_raw = raw
    if not raw:
      self._nav_instruction_state = {}
      return

    if isinstance(raw, dict):
      self._nav_instruction_state = raw
      return

    if isinstance(raw, str):
      try:
        parsed = json.loads(raw)
        self._nav_instruction_state = parsed if isinstance(parsed, dict) else {}
        return
      except Exception:
        pass

    self._nav_instruction_state = {}

  def _get_combined_blindspot(self, carstate, lane_change_direction, v_asm_enabled=False):
    vasm_left, vasm_right = (False, False)
    if v_asm_enabled:
      vasm_left, vasm_right = get_fresh_vasm_state(self.params_memory)
    if lane_change_direction == LaneChangeDirection.left:
      return bool(getattr(carstate, "leftBlindspot", False) or vasm_left)
    elif lane_change_direction == LaneChangeDirection.right:
      return bool(getattr(carstate, "rightBlindspot", False) or vasm_right)
    return False

  def _publish_lane_move_prompt(self, carstate, starpilotPlan, starpilot_toggles, lateral_active):
    if self._prompt_publish_disabled:
      return
    self._update_nav_params()
    now = time.monotonic()
    state = self._nav_instruction_state if (lateral_active and getattr(starpilot_toggles, "nav_desires_allowed", False)) else {}
    widths = {"left": getattr(starpilotPlan, "laneWidthLeft", None), "right": getattr(starpilotPlan, "laneWidthRight", None)}
    prompt = nav_lane_move_prompt(state, carstate.vEgo, starpilot_toggles.minimum_lane_change_speed, widths,
                                  starpilot_toggles.lane_detection_width, now)
    v_asm_enabled = bool(getattr(starpilot_toggles, "v_asm_enabled", False))
    side_dir = {"left": LaneChangeDirection.left, "right": LaneChangeDirection.right}.get(prompt["side"], LaneChangeDirection.none)
    prompt["blocked"] = bool(prompt["armed"] and self._get_combined_blindspot(carstate, side_dir, v_asm_enabled))
    key = (prompt["armed"], prompt["side"], prompt["kind"], prompt["blocked"])
    # rewrite every 1 s while armed so the UI can drop a stale prompt by timestamp
    if key == self._prompt_last and not (prompt["armed"] and now - self._prompt_last_t >= 1.0):
      return
    self._prompt_last, self._prompt_last_t = key, now
    try:
      self.params_memory.put_nonblocking("NavLaneMovePrompt", prompt)
    except UnknownKeyName:
      # binary built before the key existed: drop the prompt rather than take down controlsd
      self._prompt_publish_disabled = True

  @staticmethod
  def _nav_keep_direction_is_clear(carstate, lane_change_direction, params_memory=None, v_asm_enabled=False):
    vasm_left, vasm_right = (False, False)
    if v_asm_enabled and params_memory is not None:
      vasm_left, vasm_right = get_fresh_vasm_state(params_memory)
    if lane_change_direction == LaneChangeDirection.left:
      return not (getattr(carstate, "leftBlindspot", False) or vasm_left)
    if lane_change_direction == LaneChangeDirection.right:
      return not (getattr(carstate, "rightBlindspot", False) or vasm_right)
    return True

  @staticmethod
  def _nav_torque_applied(carstate, lane_change_direction):
    return carstate.steeringPressed and (
      (lane_change_direction == LaneChangeDirection.left and carstate.steeringTorque > 0) or
      (lane_change_direction == LaneChangeDirection.right and carstate.steeringTorque < 0)
    )

  @staticmethod
  def _nav_exit_auto_keep(carstate, starpilot_toggles, maneuver_type):
    # D-107: an off-ramp whose lane guidance already marks the exit-side lane is kept without a nudge. Off ramps only,
    # never forks. Any steering input from the driver withdraws it (the nudge path below still works).
    return (
      bool(getattr(starpilot_toggles, "nav_exit_auto_keep", False)) and
      maneuver_type == "off ramp" and
      carstate.vEgo >= NAV_EXIT_AUTO_KEEP_MIN_SPEED and
      not carstate.steeringPressed
    )

  @staticmethod
  def _nav_turn_is_imminent(carstate, maneuver_distance):
    try:
      distance = float(maneuver_distance)
    except (TypeError, ValueError):
      return False

    return distance <= float(np.interp(carstate.vEgo, NAV_TURN_DISTANCE_SPEED_BREAKPOINTS, NAV_TURN_DISTANCE_BREAKPOINTS))

  @staticmethod
  def _nudgeless_enabled(starpilot_toggles, controls_enabled):
    nudgeless = bool(getattr(starpilot_toggles, "nudgeless", False))
    if getattr(starpilot_toggles, "nudgeless_lane_change_only_when_engaged", False):
      nudgeless &= bool(controls_enabled)
    return nudgeless

  @staticmethod
  def _nav_should_delay_ambiguous_split(maneuver_type="", same_side_lane_count=0, lane_count=0):
    if maneuver_type not in ("off ramp", "fork") or int(same_side_lane_count or 0) <= 1:
      return False

    total_lanes = int(lane_count or 0)
    if total_lanes <= 0:
      return True

    other_lanes = max(total_lanes - int(same_side_lane_count or 0), 0)
    return other_lanes <= NAV_KEEP_SMALL_SPLIT_MAX_OTHER_LANES

  @staticmethod
  def _nav_keep_is_imminent(carstate, maneuver_distance, maneuver_type="", same_side_lane_count=0, lane_count=0):
    try:
      distance = float(maneuver_distance)
    except (TypeError, ValueError):
      return False

    threshold = float(np.interp(carstate.vEgo, NAV_KEEP_DISTANCE_SPEED_BREAKPOINTS, NAV_KEEP_DISTANCE_BREAKPOINTS))
    if DesireHelper._nav_should_delay_ambiguous_split(maneuver_type, same_side_lane_count, lane_count):
      threshold *= NAV_KEEP_AMBIGUOUS_SPLIT_DISTANCE_SCALE
    return distance <= threshold

  @staticmethod
  def _nav_should_suppress_edge_lane_keep(nav_instruction_state):
    maneuver_type = str(nav_instruction_state.get("maneuverType", ""))
    if maneuver_type not in ("off ramp", "fork"):
      return False

    active_lane_direction = str(nav_instruction_state.get("activeLaneDirection", ""))
    if active_lane_direction not in ("slightLeft", "left", "sharpLeft", "slightRight", "right", "sharpRight"):
      return False

    same_side_lane_count = int(nav_instruction_state.get("sameSideLaneCount", 0) or 0)
    lane_count = int(nav_instruction_state.get("laneCount", 0) or 0)

    return (
      DesireHelper._nav_should_delay_ambiguous_split(maneuver_type, same_side_lane_count, lane_count) and
      bool(nav_instruction_state.get("activeLaneAtRoadEdge", False)) and
      bool(nav_instruction_state.get("hasSharedSameSideLane", False))
    )

  @staticmethod
  def _nav_effective_modifier(nav_instruction_state, carstate, maneuver_distance):
    modifier = str(nav_instruction_state.get("maneuverModifier", ""))
    maneuver_type = str(nav_instruction_state.get("maneuverType", ""))
    active_lane_direction = str(nav_instruction_state.get("activeLaneDirection", ""))
    same_side_lane_count = int(nav_instruction_state.get("sameSideLaneCount", 0) or 0)
    lane_count = int(nav_instruction_state.get("laneCount", 0) or 0)

    if maneuver_type in ("off ramp", "fork") and modifier in ("slightLeft", "left", "sharpLeft", "slightRight", "right", "sharpRight"):
      if not DesireHelper._nav_keep_is_imminent(carstate, maneuver_distance, maneuver_type, same_side_lane_count, lane_count):
        return ""

      if DesireHelper._nav_should_suppress_edge_lane_keep(nav_instruction_state):
        return ""

      if active_lane_direction in ("slightLeft", "left"):
        return "slightLeft"
      if active_lane_direction in ("slightRight", "right"):
        return "slightRight"

      # If lane guidance says the active lane stays straight, don't reinterpret the
      # broader fork/off-ramp maneuver as a late turn into another branch.
      return ""

    return modifier

  def _navigation_desire(self, carstate, lateral_active, starpilotPlan, starpilot_toggles):
    self._update_nav_params()
    self.nav_desires_allowed = bool(getattr(starpilot_toggles, "nav_desires_allowed", self.nav_desires_allowed))
    self.nav_lane_positioning_allowed = bool(
      getattr(starpilot_toggles, "nav_lane_positioning_allowed", self.nav_lane_positioning_allowed)
    )
    if not self.nav_desires_allowed or not lateral_active or not bool(self._nav_instruction_state.get("valid", False)):
      return log.Desire.none

    maneuver_distance = self._nav_instruction_state.get("maneuverDistance", 0.0)
    modifier = self._nav_effective_modifier(self._nav_instruction_state, carstate, maneuver_distance)
    if modifier == "":
      return log.Desire.none

    v_asm_enabled = bool(getattr(starpilot_toggles, "v_asm_enabled", False))
    maneuver_type = str(self._nav_instruction_state.get("maneuverType", ""))
    auto_keep = self._nav_exit_auto_keep(carstate, starpilot_toggles, maneuver_type)
    if modifier == "slightLeft":
      if not (self.nav_lane_positioning_allowed or auto_keep):
        return log.Desire.none
      lane_change_direction = LaneChangeDirection.left
      desired_lane_width = starpilotPlan.laneWidthLeft
      if not carstate.rightBlinker and self._nav_keep_direction_is_clear(carstate, lane_change_direction, self.params_memory, v_asm_enabled):
        if desired_lane_width >= starpilot_toggles.lane_detection_width and (auto_keep or self._nav_torque_applied(carstate, lane_change_direction)):
          return log.Desire.keepLeft
    elif modifier == "slightRight":
      if not (self.nav_lane_positioning_allowed or auto_keep):
        return log.Desire.none
      lane_change_direction = LaneChangeDirection.right
      desired_lane_width = starpilotPlan.laneWidthRight
      if not carstate.leftBlinker and self._nav_keep_direction_is_clear(carstate, lane_change_direction, self.params_memory, v_asm_enabled):
        if desired_lane_width >= starpilot_toggles.lane_detection_width and (auto_keep or self._nav_torque_applied(carstate, lane_change_direction)):
          return log.Desire.keepRight
    elif modifier in ("left", "sharpLeft"):
      left_blocked = self._get_combined_blindspot(carstate, LaneChangeDirection.left, v_asm_enabled)
      turn_allowed = carstate.leftBlinker and not carstate.rightBlinker and not left_blocked
      turn_allowed &= carstate.vEgo < starpilot_toggles.minimum_lane_change_speed and not carstate.standstill
      if turn_allowed and self._nav_turn_is_imminent(carstate, maneuver_distance):
        return log.Desire.turnLeft
    elif modifier in ("right", "sharpRight"):
      right_blocked = self._get_combined_blindspot(carstate, LaneChangeDirection.right, v_asm_enabled)
      turn_allowed = carstate.rightBlinker and not carstate.leftBlinker and not right_blocked
      turn_allowed &= carstate.vEgo < starpilot_toggles.minimum_lane_change_speed and not carstate.standstill
      if turn_allowed and self._nav_turn_is_imminent(carstate, maneuver_distance):
        return log.Desire.turnRight

    return log.Desire.none

  def _get_nav_exit_lane_change_direction(self, starpilot_toggles):
    self._update_nav_params()
    nav_exit_allowed = getattr(starpilot_toggles, "nav_exit_lane_change", False) or \
                       (getattr(starpilot_toggles, "nav_desires_allowed", self.nav_desires_allowed) and \
                        getattr(starpilot_toggles, "nav_lane_positioning_allowed", self.nav_lane_positioning_allowed))
    if not bool(nav_exit_allowed):
      return LaneChangeDirection.none

    if not bool(self._nav_instruction_state.get("valid", False)):
      return LaneChangeDirection.none

    # As IQ.Pilot NavExitLaneChangeController: only a highway exit (Mapbox "off ramp") within
    # NAV_EXIT_COMMIT_DISTANCE, in the maneuver's own direction
    maneuver_type = str(self._nav_instruction_state.get("maneuverType", "")).lower()
    if maneuver_type != "off ramp":
      return LaneChangeDirection.none

    # StarPilot-only: when navigationd has lane guidance for this exit, the existing keepLeft/keepRight
    # lane positioning handles it, and a lane change state would block those desires
    active_lane_dir = str(self._nav_instruction_state.get("activeLaneDirection", ""))
    if active_lane_dir in ("slightLeft", "left", "sharpLeft", "slightRight", "right", "sharpRight"):
      return LaneChangeDirection.none

    try:
      distance = float(self._nav_instruction_state.get("maneuverDistance", 0.0))
    except (TypeError, ValueError):
      return LaneChangeDirection.none
    if not 0.0 < distance <= NAV_EXIT_COMMIT_DISTANCE:
      return LaneChangeDirection.none

    # route_engine falls back to the raw Mapbox step modifier ("slight right") when there is no banner
    modifier = str(self._nav_instruction_state.get("maneuverModifier", "")).replace(" ", "").lower()
    if modifier in ("left", "sharpleft", "slightleft"):
      return LaneChangeDirection.left
    elif modifier in ("right", "sharpright", "slightright"):
      return LaneChangeDirection.right
    return LaneChangeDirection.none

  def _measured_yaw_rate(self, carstate) -> float:
    # carState.yawRate is left unpopulated by many ports, so the model pose is the primary source
    rate = getattr(getattr(getattr(self, "_last_modeldata", None), "orientationRate", None), "z", None)
    try:
      if rate is not None and len(rate) and math.isfinite(rate[0]):
        return float(rate[0])
    except (TypeError, IndexError):
      pass
    try:
      return float(getattr(carstate, "yawRate", 0.0) or 0.0)
    except (TypeError, ValueError):
      return 0.0

  def _turn_recoiled(self, desired_output: log.Desire, carstate) -> bool:
    if desired_output != self.turn_desire_cycle_input:
      self.turn_heading_rad = 0.0
      self.turn_desire_seconds = 0.0
      self.turn_recoiled = False
    self.turn_heading_rad += abs(self._measured_yaw_rate(carstate)) * DT_MDL
    if float(getattr(carstate, "vEgo", 0.0) or 0.0) > TURN_DESIRE_MOVING_SPEED:
      self.turn_desire_seconds += DT_MDL
    if self.turn_heading_rad >= TURN_RECOIL_HEADING_RAD or self.turn_desire_seconds >= TURN_DESIRE_MAX_SECONDS:
      self.turn_recoiled = True
    return self.turn_recoiled

  def _pulse_turn_desire(self, desired_output: log.Desire, carstate) -> log.Desire:
    if desired_output not in (log.Desire.turnLeft, log.Desire.turnRight):
      self.turn_desire_frames = 0
      self.turn_desire_cycle_input = log.Desire.none
      self.turn_heading_rad = 0.0
      self.turn_desire_seconds = 0.0
      self.turn_recoiled = False
      return desired_output

    recoiled = self._turn_recoiled(desired_output, carstate)

    if desired_output != self.turn_desire_cycle_input:
      self.turn_desire_frames = 0
      self.turn_desire_cycle_input = desired_output

    cycle_frame = self.turn_desire_frames % TURN_DESIRE_PULSE_CYCLE_FRAMES
    self.turn_desire_frames += 1
    if recoiled or cycle_frame >= TURN_DESIRE_PULSE_HOLD_FRAMES:
      return log.Desire.none
    return desired_output

  @staticmethod
  def get_lane_change_direction(CS):
    return LaneChangeDirection.left if CS.leftBlinker else LaneChangeDirection.right

  def update(self, carstate, lateral_active, lane_change_prob, starpilotPlan, starpilot_toggles, controls_enabled=None, modeldata=None):
    self._last_modeldata = modeldata
    self._publish_lane_move_prompt(carstate, starpilotPlan, starpilot_toggles, lateral_active)
    v_ego = carstate.vEgo
    one_blinker = carstate.leftBlinker != carstate.rightBlinker
    below_lane_change_speed = v_ego < starpilot_toggles.minimum_lane_change_speed

    cruise_state = getattr(carstate, "cruiseState", None)
    controls_enabled = bool(getattr(cruise_state, "enabled", False)) if controls_enabled is None else bool(controls_enabled)
    nudgeless_enabled = self._nudgeless_enabled(starpilot_toggles, controls_enabled)
    lane_changes_allowed = starpilot_toggles.lane_changes
    lane_changes_allowed &= not getattr(starpilot_toggles, "lane_changes_require_cruise", False) or bool(getattr(cruise_state, "enabled", False))

    lane_change_time_max = getattr(starpilot_toggles, 'lane_change_time_max', LANE_CHANGE_TIME_MAX)
    nav_exit_direction = self._get_nav_exit_lane_change_direction(starpilot_toggles)
    nav_exit_active = nav_exit_direction != LaneChangeDirection.none
    # D-110: runs every frame so its block/clear debounce is current when a lane change is requested
    self.edge_guard.update(modeldata, v_ego, DT_MDL, enabled=bool(getattr(starpilot_toggles, "lane_change_edge_guard", False)))

    if not lateral_active or self.lane_change_timer > lane_change_time_max or not lane_changes_allowed:
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.nav_exit_lane_change = False
    else:
      # LaneChangeState.off
      if self.lane_change_state == LaneChangeState.off:
        if one_blinker and not self.prev_one_blinker and not below_lane_change_speed:
          self.lane_change_state = LaneChangeState.preLaneChange
          self.lane_change_ll_prob = 1.0
          self.nav_exit_lane_change = False
          # Initialize lane change direction to prevent UI alert flicker
          self.lane_change_direction = self.get_lane_change_direction(carstate)
        elif not one_blinker and nav_exit_active and not self.prev_nav_exit_active and not below_lane_change_speed:
          # Navigation requested exit lane change -> enter preLaneChange
          self.lane_change_state = LaneChangeState.preLaneChange
          self.lane_change_ll_prob = 1.0
          self.nav_exit_lane_change = True
          self.nav_exit_rearmed = False
          self.lane_change_direction = nav_exit_direction

      # LaneChangeState.preLaneChange
      elif self.lane_change_state == LaneChangeState.preLaneChange:
        if one_blinker:
          blinker_direction = self.get_lane_change_direction(carstate)
          # a blinker toward the exit confirms the nav lane change; any other blinker takes over as a normal one
          if blinker_direction != nav_exit_direction:
            self.nav_exit_lane_change = False
          self.lane_change_direction = blinker_direction
        elif self.nav_exit_lane_change:
          if nav_exit_direction == LaneChangeDirection.none or below_lane_change_speed:
            self.lane_change_state = LaneChangeState.off
            self.lane_change_direction = LaneChangeDirection.none
            self.nav_exit_lane_change = False
          else:
            self.lane_change_direction = nav_exit_direction

        # Keep lane-change nudge sensitivity aligned with the old raw torque threshold,
        # even if steeringPressed is raised elsewhere for driver override filtering.
        torque_nudged = carstate.steeringPressed or abs(carstate.steeringTorque) > LANE_CHANGE_NUDGE_TORQUE_THRESHOLD
        torque_applied = torque_nudged and \
                         ((carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                          (carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

        v_asm_enabled = bool(getattr(starpilot_toggles, "v_asm_enabled", False))
        blindspot_detected = self._get_combined_blindspot(carstate, self.lane_change_direction, v_asm_enabled=v_asm_enabled)
        # D-110: a road edge where the target lane should be holds the launch the same way a blind-spot car does
        blindspot_detected |= self.edge_guard.block_for_direction(self.lane_change_direction)

        if self.nav_exit_lane_change:
          # Driver confirms with the blinker toward the exit (no native BSM; vision ASM can only block).
          # Every further lane of the same exit also needs a wheel nudge toward it.
          launch_allowed = one_blinker and (torque_applied or not self.nav_exit_rearmed) and not blindspot_detected
        else:
          if torque_applied:
            self.lane_change_wait_timer = starpilot_toggles.lane_change_delay
          else:
            torque_applied |= nudgeless_enabled
            torque_applied &= self.lane_change_wait_timer >= starpilot_toggles.lane_change_delay

            desired_lane_width = starpilotPlan.laneWidthLeft if self.lane_change_direction == LaneChangeDirection.left else starpilotPlan.laneWidthRight
            torque_applied &= desired_lane_width >= starpilot_toggles.lane_detection_width
          launch_allowed = torque_applied and not blindspot_detected

        if (not one_blinker and not self.nav_exit_lane_change) or below_lane_change_speed or self.lane_change_completed:
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
          self.nav_exit_lane_change = False
        elif launch_allowed:
          self.lane_change_state = LaneChangeState.laneChangeStarting
          self.lane_change_completed = True if self.nav_exit_lane_change else starpilot_toggles.one_lane_change
          self.lane_change_wait_timer = 0.0

        self.lane_change_wait_timer += DT_MDL

      # LaneChangeState.laneChangeStarting
      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        # fade out over .5s
        self.lane_change_ll_prob = max(self.lane_change_ll_prob - 2 * DT_MDL, 0.0)

        # D-108: steering against the move cancels it. Going to off (not preLaneChange) means a held blinker
        # needs a fresh press and a nav exit move needs a fresh exit request before anything relaunches.
        counter_torque = (carstate.steeringPressed or abs(carstate.steeringTorque) > LANE_CHANGE_NUDGE_TORQUE_THRESHOLD) and \
                         ((carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.left) or
                          (carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.right))
        if counter_torque and getattr(starpilot_toggles, "lane_change_counter_torque_cancel", False):
          self.counter_torque_frames += 1
        else:
          self.counter_torque_frames = 0

        if self.counter_torque_frames >= LANE_CHANGE_CANCEL_TORQUE_FRAMES:
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
          self.nav_exit_lane_change = False
        # 98% certainty
        elif lane_change_prob < 0.02 and self.lane_change_ll_prob < 0.01:
          self.lane_change_state = LaneChangeState.laneChangeFinishing

      # LaneChangeState.laneChangeFinishing
      elif self.lane_change_state == LaneChangeState.laneChangeFinishing:
        # fade in laneline over 1s
        self.lane_change_ll_prob = min(self.lane_change_ll_prob + DT_MDL, 1.0)

        if self.lane_change_ll_prob > 0.99:
          self.lane_change_direction = LaneChangeDirection.none
          if self.nav_exit_lane_change and nav_exit_active:
            # an exit can need more than one lane; every further move needs the blinker and a nudge toward the exit
            self.lane_change_state = LaneChangeState.preLaneChange
            self.lane_change_direction = nav_exit_direction
            self.lane_change_completed = False
            self.nav_exit_rearmed = True
          elif one_blinker:
            self.lane_change_state = LaneChangeState.preLaneChange
          else:
            self.lane_change_state = LaneChangeState.off
            self.nav_exit_lane_change = False

    if self.lane_change_state != LaneChangeState.laneChangeStarting:
      self.counter_torque_frames = 0

    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.preLaneChange):
      self.lane_change_timer = 0.0
    else:
      self.lane_change_timer += DT_MDL

    self.prev_one_blinker = one_blinker
    self.prev_nav_exit_active = nav_exit_active

    if lateral_active and one_blinker and below_lane_change_speed and not carstate.standstill and starpilot_toggles.use_turn_desires:
      self.turn_direction = TurnDirection.turnLeft if carstate.leftBlinker else TurnDirection.turnRight
      self.desire = TURN_DESIRES[self.turn_direction]
    else:
      self.turn_direction = TurnDirection.none
      self.desire = DESIRES[self.lane_change_direction][self.lane_change_state]

    # Send keep pulse once per second during LaneChangeStart.preLaneChange
    if self.lane_change_state in (LaneChangeState.off, LaneChangeState.laneChangeStarting):
      self.keep_pulse_timer = 0.0
    elif self.lane_change_state == LaneChangeState.preLaneChange:
      self.keep_pulse_timer += DT_MDL
      if self.keep_pulse_timer > 1.0:
        self.keep_pulse_timer = 0.0
      elif self.desire in (log.Desire.keepLeft, log.Desire.keepRight):
        self.desire = log.Desire.none

    if not one_blinker and not self.nav_exit_lane_change:
      self.lane_change_completed = False
      self.lane_change_wait_timer = 0.0

    nav_desire = self._navigation_desire(carstate, lateral_active, starpilotPlan, starpilot_toggles)
    self.nav_desire = nav_desire
    if nav_desire != log.Desire.none and self.lane_change_state == LaneChangeState.off:
      self.desire = nav_desire

    # Runs every frame, as in IQ.Pilot: a non-turn desire is what clears the pulse/recoil state
    self.desire = self._pulse_turn_desire(self.desire, carstate)
