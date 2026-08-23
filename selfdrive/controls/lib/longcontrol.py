from cereal import car
import math
from types import SimpleNamespace
import numpy as np
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.controls.lib.longcontrol_vehicle_tunes import LongControlVehicleTuning
from openpilot.selfdrive.controls.lib.nrdr_long_tune import LongTune
from opendbc.car.honda.values import CAR as HONDA_CAR

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
clip = np.clip
interp = np.interp
STOPPING_RELEASE_HYSTERESIS = 0.35
STOPPING_RELEASE_MIN_ACCEL = 0.15
STOPPING_RELEASE_STRONG_ACCEL = 0.45
LEAD_GAP_SETTLE_MAX_START_ACCEL = 0.25
MOVING_STOP_FOLLOW_MIN_GAP = 0.25
NEGATIVE_TARGET_CREEP_GUARD_SPEED = 0.35
NEGATIVE_TARGET_CREEP_GUARD_DECEL = 0.40
MODE_TRANSITION_MAX_DECEL = 4.0
TESLA_PEDAL_RELEASE_GUARD_TIME = 0.15
TESLA_PEDAL_RELEASE_GUARD_MAX_DECEL = 0.35

LongCtrlState = car.CarControl.Actuators.LongControlState

_ACCEL_DUE_TO_GRAVITY = 9.81  # m/s^2
STOPPING_HARD_HOLD_FLOOR = -1.0  # m/s^2; hardcoded safety cap, never a tune field
_DREL_ROLLING_FRAMES = 10
_DREL_FILTER_ALPHA = 0.3


def compute_stopping_accel(last_output_accel, stop_accel, stopping_decel_rate,
                            v_ego, v_ego_stopping, hold_accel, phase_switch_v,
                            proximity_scale_m, pitch_margin, drel_filtered, pitch):
  """Two-phase stopping-ramp shape (Bundle D / L2 port from nrdr-nightly).

  INERT above v_ego_stopping — reproduces the stock monotonic ramp so highway
  behavior is unchanged. drel_filtered=inf disables proximity scaling (scale=1.0).
  pitch=nan disables grade compensation.
  """
  if not math.isfinite(last_output_accel):
    last_output_accel = 0.0

  # INERT above v_ego_stopping
  if not (math.isfinite(v_ego) and v_ego <= v_ego_stopping):
    out = last_output_accel
    if out > stop_accel:
      out = min(out, 0.0)
      out -= stopping_decel_rate * DT_CTRL
    return out

  v_clamped = max(0.0, v_ego)
  speed_scale = float(np.interp(v_clamped, [0.0, 0.3, max(0.3 + 1e-6, v_ego_stopping)],
                                [0.3, 0.7, 1.0]))

  prox_scale = 1.0
  if math.isfinite(drel_filtered) and proximity_scale_m > 0.0:
    prox_scale = min(1.0, max(0.0, drel_filtered) / proximity_scale_m)

  rate_eff = stopping_decel_rate * speed_scale * prox_scale

  at_standstill = v_ego <= phase_switch_v

  if not at_standstill:
    target = hold_accel
  else:
    pitch_term = 0.0
    if math.isfinite(pitch):
      pitch_term = -_ACCEL_DUE_TO_GRAVITY * math.sin(pitch) * pitch_margin
    pitch_aware_floor = hold_accel + pitch_term
    target = min(pitch_aware_floor, STOPPING_HARD_HOLD_FLOOR)
    target = max(target, stop_accel)

  out = last_output_accel
  if out > target:
    out = min(out, 0.0)
    out = max(target, out - rate_eff * DT_CTRL)
  return out

def apply_deadzone(error, deadzone):
  if error > deadzone:
    error -= deadzone
  elif error < -deadzone:
    error += deadzone
  else:
    error = 0.0
  return error


def long_control_state_trans(CP, active, long_control_state, v_ego,
                             should_stop, brake_pressed, cruise_standstill, starpilot_toggles,
                             allow_stopping_release=True):
  # Ignore cruise standstill if car has a gas interceptor
  cruise_standstill = cruise_standstill and not CP.enableGasInterceptorDEPRECATED
  stopping_condition = should_stop
  release_condition = not should_stop and not brake_pressed
  starting_condition = release_condition and not cruise_standstill
  # Some stock ACC platforms keep standstill latched until they see positive drive torque.
  # Once the planner has sustained a release request, allow LongControl to leave stopping
  # even if the standstill bit has not dropped yet.
  stopping_release_condition = release_condition and allow_stopping_release
  started_condition = v_ego > starpilot_toggles.vEgoStarting

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      if not starting_condition:
        long_control_state = LongCtrlState.stopping
      else:
        if starting_condition and CP.startingState:
          long_control_state = LongCtrlState.starting
        else:
          long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.stopping:
      if stopping_release_condition and CP.startingState:
        long_control_state = LongCtrlState.starting
      elif stopping_release_condition:
        long_control_state = LongCtrlState.pid

    elif long_control_state in [LongCtrlState.starting, LongCtrlState.pid]:
      if stopping_condition:
        long_control_state = LongCtrlState.stopping
      elif started_condition:
        long_control_state = LongCtrlState.pid
  return long_control_state

def long_control_state_trans_old_long(CP, active, long_control_state, v_ego, v_target,
                                      v_target_1sec, brake_pressed, cruise_standstill, starpilot_toggles):
  accelerating = v_target_1sec > v_target
  planned_stop = (v_target < starpilot_toggles.vEgoStopping and
                  v_target_1sec < starpilot_toggles.vEgoStopping and
                  not accelerating)
  stay_stopped = (v_ego < starpilot_toggles.vEgoStopping and
                  (brake_pressed or cruise_standstill))
  stopping_condition = planned_stop or stay_stopped

  starting_condition = (v_target_1sec > starpilot_toggles.vEgoStarting and
                        accelerating and
                        not cruise_standstill and
                        not brake_pressed)
  started_condition = v_ego > starpilot_toggles.vEgoStarting

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state in (LongCtrlState.off, LongCtrlState.pid):
      long_control_state = LongCtrlState.pid
      if stopping_condition:
        long_control_state = LongCtrlState.stopping

    elif long_control_state == LongCtrlState.stopping:
      if starting_condition and CP.startingState:
        long_control_state = LongCtrlState.starting
      elif starting_condition:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.starting:
      if stopping_condition:
        long_control_state = LongCtrlState.stopping
      elif started_condition:
        long_control_state = LongCtrlState.pid

  return long_control_state

class LongControl:
  def __init__(self, CP):
    self.CP = CP
    self.params = Params()
    self.long_control_state = LongCtrlState.off
    self.experimental_mode = False
    self.pid = PIDController((CP.longitudinalTuning.kpBP, CP.longitudinalTuning.kpV),
                             (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    # Preserve legacy behaviour when no feedforward gain is provided (default of 0.0)
    kf = getattr(CP.longitudinalTuning, 'kfDEPRECATED', 0.0)
    self.feedforward_gain = kf if kf != 0.0 else 1.0
    self.v_pid = 0.0
    self._mode_setup()
    self.last_output_accel = 0.0
    self.stop_release_counter = 0
    self.pedal_override_active = False
    self.pedal_override_release_frames = 0
    self.vehicle_tuning = LongControlVehicleTuning(CP)
    self.frame = 0
    self._drel_window: list[float] = []
    self._drel_filtered = float("inf")
    self.is_honda = CP.brand == "honda"
    self.is_civic_bosch = self.is_honda and CP.carFingerprint == HONDA_CAR.HONDA_CIVIC_BOSCH
    self.honda_long_pid_tune_scale = 1.0
    self.honda_scale_excludes_kf = True
    # Civic Bosch's CarParams stopping values are the deployed tune. Preserve the legacy
    # branch-wide fallbacks for other Hondas until they are independently reviewed.
    self.honda_stop_accel = float(CP.stopAccel) if self.is_civic_bosch else -2.0
    self.honda_stopping_decel_rate = float(CP.stoppingDecelRate) if self.is_civic_bosch else 0.3
    self.honda_v_ego_starting = float(CP.vEgoStarting) if self.is_civic_bosch else 0.5
    self.honda_v_ego_stopping = float(CP.vEgoStopping) if self.is_civic_bosch else 0.5
    self._long_tune = LongTune()

  def update_mpc_mode(self, experimental_mode):
    new_mode = 'blended' if experimental_mode else 'acc'

    if self.transitioning and self.prev_mode == 'blended' and self.current_mode == 'acc':
      self.mode_transition_timer = 0.0

    if new_mode != self.current_mode:
      self.prev_mode = self.current_mode
      self.transitioning = True
      self.mode_transition_timer = 0.0
      self.mode_transition_filter.x = self.last_output_accel

      self.current_mode = new_mode

    if self.transitioning:
      self.mode_transition_timer += DT_CTRL
      if self.mode_transition_timer >= self.mode_transition_duration:
        self.transitioning = False

  def _mode_setup(self):
    self.prev_mode = 'acc'
    self.current_mode = 'acc'
    self.mode_transition_filter = FirstOrderFilter(0.0, 0.5, DT_CTRL)
    self.mode_transition_timer = 0.0
    self.mode_transition_duration = 1.0
    self.transitioning = False

  def reset(self, preserve_stop_release=False):
    self.pid.reset()
    self.vehicle_tuning.reset()
    if not preserve_stop_release:
      self.stop_release_counter = 0

  def _read_honda_long_params(self):
    if not self.is_honda:
      return

    self.honda_long_pid_tune_scale = float(np.clip(self.params.get_int("LongPidTuneScale", default=100), 0, 500)) / 100.0
    self.honda_scale_excludes_kf = self.params.get_bool("StaticFeedforwardLong", default=True)
    default_stop_accel = self.CP.stopAccel if self.is_civic_bosch else -2.0
    default_stopping_decel_rate = self.CP.stoppingDecelRate if self.is_civic_bosch else 0.3
    default_v_ego_starting = self.CP.vEgoStarting if self.is_civic_bosch else 0.5
    default_v_ego_stopping = self.CP.vEgoStopping if self.is_civic_bosch else 0.5
    self.honda_stop_accel = float(np.clip(self.params.get_float("HondaStopAccel", default=default_stop_accel), -10.0, 0.0))
    self.honda_stopping_decel_rate = float(np.clip(
      self.params.get_float("HondaStoppingDecelRateLong", default=default_stopping_decel_rate), 0.0, 5.0,
    ))
    self.honda_v_ego_starting = float(np.clip(
      self.params.get_float("HondaVEgoStarting", default=default_v_ego_starting), 0.0, 5.0,
    ))
    self.honda_v_ego_stopping = float(np.clip(
      self.params.get_float("HondaVEgoStopping", default=default_v_ego_stopping), 0.0, 5.0,
    ))

  def _get_runtime_long_tuning(self, starpilot_toggles):
    long_tuning = SimpleNamespace(
      startAccel=starpilot_toggles.startAccel,
      stopAccel=starpilot_toggles.stopAccel,
      stoppingDecelRate=starpilot_toggles.stoppingDecelRate,
      vEgoStarting=starpilot_toggles.vEgoStarting,
      vEgoStopping=starpilot_toggles.vEgoStopping,
    )

    if self.is_honda:
      long_tuning.stopAccel = self.honda_stop_accel
      long_tuning.stoppingDecelRate = self.honda_stopping_decel_rate
      long_tuning.vEgoStarting = self.honda_v_ego_starting
      long_tuning.vEgoStopping = self.honda_v_ego_stopping

    return long_tuning

  def _stop_release_ready(self, CS, a_target, should_stop, has_lead, v_ego_starting):
    if self.long_control_state != LongCtrlState.stopping:
      self.stop_release_counter = 0
      return True

    if should_stop or CS.brakePressed:
      self.stop_release_counter = 0
      return False

    if CS.vEgo > v_ego_starting:
      self.stop_release_counter = int(round(STOPPING_RELEASE_HYSTERESIS / DT_CTRL))
      return True

    if has_lead and a_target > STOPPING_RELEASE_MIN_ACCEL:
      self.stop_release_counter = int(round(STOPPING_RELEASE_HYSTERESIS / DT_CTRL))
      return True

    if a_target >= STOPPING_RELEASE_STRONG_ACCEL and not CS.cruiseState.standstill:
      self.stop_release_counter = int(round(STOPPING_RELEASE_HYSTERESIS / DT_CTRL))
      return True

    if a_target > STOPPING_RELEASE_MIN_ACCEL:
      max_frames = int(round(STOPPING_RELEASE_HYSTERESIS / DT_CTRL))
      self.stop_release_counter = min(self.stop_release_counter + 1, max_frames)
    else:
      self.stop_release_counter = 0

    return self.stop_release_counter >= int(round(STOPPING_RELEASE_HYSTERESIS / DT_CTRL))

  @staticmethod
  def _apply_moving_stop_target_follow(output_accel, a_target, should_stop, CS, v_ego_stopping):
    follow_min_speed = max(1.5, v_ego_stopping + 1.0)
    if not should_stop or CS.brakePressed or CS.vEgo <= follow_min_speed:
      return output_accel
    if a_target >= output_accel - MOVING_STOP_FOLLOW_MIN_GAP:
      return output_accel

    follow_step = interp(CS.vEgo, [follow_min_speed, 3.0, 6.0, 10.0], [0.02, 0.03, 0.05, 0.07])
    return max(float(a_target), output_accel - float(follow_step))

  def _update_drel_filter(self, drel):
    if drel is None or not math.isfinite(drel):
      self._drel_window = []
      self._drel_filtered = float("inf")
      return float("inf")
    self._drel_window.append(float(drel))
    if len(self._drel_window) > _DREL_ROLLING_FRAMES:
      self._drel_window.pop(0)
    rolling_min = min(self._drel_window)
    if not math.isfinite(self._drel_filtered):
      self._drel_filtered = rolling_min
    else:
      self._drel_filtered = _DREL_FILTER_ALPHA * rolling_min + (1.0 - _DREL_FILTER_ALPHA) * self._drel_filtered
    return self._drel_filtered

  def _trim_positive_overshoot_integrator(self, a_target, error, CS):
    if self.pid.i <= 0.0:
      return
    if a_target >= -0.05 or error >= -0.25:
      return
    if CS.vEgo <= NEGATIVE_TARGET_CREEP_GUARD_SPEED and a_target > -NEGATIVE_TARGET_CREEP_GUARD_DECEL:
      return

    # If the planner has already crossed into decel but the car is still
    # accelerating, bleed stale positive I aggressively so the command can
    # cross back through zero instead of carrying throttle for several seconds.
    bleed = interp(abs(error), [0.25, 0.75, 1.5], [0.55, 0.25, 0.0])
    self.pid.i *= bleed

  @staticmethod
  def _cap_positive_output_on_negative_target(output_accel, a_target, error, CS):
    if output_accel <= 0.0:
      return output_accel
    if a_target >= -0.10 or error >= -0.35:
      return output_accel
    if CS.vEgo <= NEGATIVE_TARGET_CREEP_GUARD_SPEED and a_target > -NEGATIVE_TARGET_CREEP_GUARD_DECEL:
      return output_accel

    # Once the planner is asking for real decel, don't keep feeding positive
    # drive torque while we're still accelerating away from the target.
    positive_cap = interp(a_target, [-1.5, -0.6, -0.1], [0.0, 0.0, 0.05])
    return min(output_accel, float(positive_cap))

  def update(self, active, CS, a_target, should_stop, accel_limits, starpilot_toggles, has_lead=False,
             traffic_mode_enabled=False, profile_max_accel=0.0, pitch=None, drel=None,
             pedal_override=False, leads=None):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    if self.frame % 300 == 0:
      self._read_honda_long_params()
    self.frame += 1

    long_tuning = self._get_runtime_long_tuning(starpilot_toggles)
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]
    drel_filtered = self._update_drel_filter(drel)

    if pedal_override:
      self.pedal_override_active = True
      self.pedal_override_release_frames = 0
      return 0.0

    if self.pedal_override_active:
      self.pedal_override_active = False
      self.pedal_override_release_frames = max(
        1, int(round(TESLA_PEDAL_RELEASE_GUARD_TIME / DT_CTRL)),
      )

    previous_long_control_state = self.long_control_state
    # Takes the Honda-overridden vEgoStarting from _get_runtime_long_tuning, not the raw
    # StarPilot toggle -- passing starpilot_toggles here would bypass HondaVEgoStarting.
    allow_stopping_release = self._stop_release_ready(CS, a_target, should_stop, has_lead, long_tuning.vEgoStarting)
    self.long_control_state = long_control_state_trans(self.CP, active, self.long_control_state, CS.vEgo,
                                                       should_stop, CS.brakePressed,
                                                       CS.cruiseState.standstill, long_tuning,
                                                       allow_stopping_release=allow_stopping_release)
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      self._long_tune.refresh()
      st = self._long_tune.stopping
      if st.get("l2_enable", 1.0) >= 0.5:
        output_accel = compute_stopping_accel(
          last_output_accel=self.last_output_accel,
          stop_accel=long_tuning.stopAccel,
          stopping_decel_rate=long_tuning.stoppingDecelRate,
          v_ego=CS.vEgo,
          v_ego_stopping=long_tuning.vEgoStopping,
          hold_accel=st.get("hold_accel", -0.6),
          phase_switch_v=st.get("phase_switch_v", 0.15),
          proximity_scale_m=st.get("proximity_scale_m", 8.0),
          pitch_margin=st.get("pitch_margin", 1.0),
          drel_filtered=drel_filtered,
          pitch=pitch if pitch is not None else float("nan"),
        )
      else:
        output_accel = self.last_output_accel
        if output_accel > long_tuning.stopAccel:
          output_accel = min(output_accel, 0.0)
          output_accel -= long_tuning.stoppingDecelRate * DT_CTRL
      output_accel = self.vehicle_tuning.shape_stopping_accel(
        output_accel, a_target, should_stop, CS.vEgo, has_lead, long_tuning.stopAccel,
      )
      output_accel = self._apply_moving_stop_target_follow(output_accel, a_target, should_stop, CS, long_tuning.vEgoStopping)
      self.reset(preserve_stop_release=True)

    elif self.long_control_state == LongCtrlState.starting:
      if traffic_mode_enabled:
        # Traffic Mode has its own soft launch curve (a_target); bypass the raw
        # StartAccel kick used elsewhere so launches stay within the traffic cap.
        output_accel = clip(a_target, 0.0, long_tuning.startAccel)
      elif getattr(starpilot_toggles, "custom_accel_profile", False):
        output_accel = clip(a_target, 0.0, long_tuning.startAccel)
      elif has_lead and a_target <= LEAD_GAP_SETTLE_MAX_START_ACCEL:
        output_accel = clip(a_target, 0.0, long_tuning.startAccel)
      elif profile_max_accel > 0.0:
        # Keep the StartAccel friction-overcoming shove, but cap it at the selected
        # acceleration profile's launch ceiling so Eco launches soft and Sport hard.
        output_accel = min(long_tuning.startAccel, profile_max_accel)
      else:
        output_accel = long_tuning.startAccel
      self.reset()

    else:  # LongCtrlState.pid
      a_target = self.vehicle_tuning.shape_gm_truck_accel_target(a_target, CS.vEgo, should_stop)
      a_target = self.vehicle_tuning.shape_toyota_corolla_accel_target(
        a_target, CS.vEgo, should_stop, self.last_output_accel,
      )
      a_target = self.vehicle_tuning.shape_toyota_sienna_accel_target(
        a_target, CS.vEgo, should_stop, leads=leads,
      )
      a_target = self.vehicle_tuning.cap_toyota_sienna_lead_departure_accel(
        a_target, CS.vEgo, leads=leads,
      )
      a_target = self.vehicle_tuning.shape_hyundai_elantra_lead_target(
        a_target, CS.vEgo, should_stop, leads,
      )
      error = a_target - CS.aEgo
      self.update_mpc_mode(self.experimental_mode)
      self.vehicle_tuning.shape_volt_test_tune_integrator(self.pid, error, CS.vEgo)
      self.vehicle_tuning.trim_volt_cruise_integrator(
        self.pid, a_target, error, CS.vEgo, should_stop, has_lead,
      )
      self._trim_positive_overshoot_integrator(a_target, error, CS)
      self.vehicle_tuning.trim_gm_truck_positive_hold_integrator(
        self.pid, self.last_output_accel, a_target, error, CS,
      )
      self.vehicle_tuning.trim_gm_truck_negative_hold_integrator(
        self.pid, self.last_output_accel, a_target, error, CS,
      )
      feedforward = self.vehicle_tuning.get_longitudinal_feedforward(
        self.feedforward_gain, self.last_output_accel, a_target, CS.vEgo,
      )
      freeze_integrator = self.vehicle_tuning.get_integrator_freeze(
        self.last_output_accel, a_target, error, CS.vEgo, accel_limits,
      )
      raw_output_accel = self.pid.update(error, speed=CS.vEgo, feedforward=feedforward,
                                         freeze_integrator=freeze_integrator)
      if self.is_honda:
        if self.honda_scale_excludes_kf:
          raw_output_accel = (raw_output_accel - self.pid.f) * self.honda_long_pid_tune_scale + self.pid.f
        else:
          raw_output_accel *= self.honda_long_pid_tune_scale
      raw_output_accel = self._cap_positive_output_on_negative_target(raw_output_accel, a_target, error, CS)
      raw_output_accel = self.vehicle_tuning.apply_pedal_long_brake_bias(raw_output_accel, a_target, CS)
      raw_output_accel = self.vehicle_tuning.apply_bolt_start_handoff_floor(
        raw_output_accel,
        self.last_output_accel,
        a_target,
        CS.vEgo,
        previous_long_control_state == LongCtrlState.starting,
        should_stop,
        has_lead,
      )
      raw_output_accel = self.vehicle_tuning.cap_hyundai_elantra_lead_output(
        raw_output_accel, CS.vEgo, should_stop, leads,
      )

      if self.transitioning and self.prev_mode == 'acc' and self.current_mode == 'blended':
        if raw_output_accel < 0 and raw_output_accel < self.last_output_accel:
          progress = min(1.0, self.mode_transition_timer / self.mode_transition_duration)
          # Soften transition at low urgency, but keep sharp for high decel
          # 20% smoother for chill decel (lower exponent)
          urgency = abs(raw_output_accel / -MODE_TRANSITION_MAX_DECEL)
          urgency_smooth = min(1.0, urgency ** 0.4)  # 20% smoother for chill decel
          blend_factor = 1.0 - (1.0 - progress) * (1.0 - urgency_smooth)
          output_accel = self.last_output_accel + (raw_output_accel - self.last_output_accel) * blend_factor
        else:
          output_accel = raw_output_accel
      else:
        output_accel = raw_output_accel

      output_accel = self.vehicle_tuning.cap_subaru_stop_release_accel(
        output_accel,
        previous_long_control_state == LongCtrlState.stopping and CS.vEgo < self.CP.vEgoStarting and not should_stop,
        should_stop,
      )

    if self.pedal_override_release_frames > 0:
      self.pedal_override_release_frames -= 1
      if not should_stop and -TESLA_PEDAL_RELEASE_GUARD_MAX_DECEL < output_accel < 0.0:
        output_accel = 0.0

    self.last_output_accel = clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel

  def reset_old_long(self, v_pid):
    """Reset PID controller and change setpoint"""
    self.pid.reset()
    self.v_pid = v_pid
    self.vehicle_tuning.reset()

  def update_old_long(self, active, CS, long_plan, accel_limits, t_since_plan, starpilot_toggles):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    if self.frame % 300 == 0:
      self._read_honda_long_params()
    self.frame += 1

    long_tuning = self._get_runtime_long_tuning(starpilot_toggles)
    # Interp control trajectory
    speeds = long_plan.speeds
    if len(speeds) == CONTROL_N:
      v_target_now = interp(t_since_plan, CONTROL_N_T_IDX, speeds)
      a_target_now = interp(t_since_plan, CONTROL_N_T_IDX, long_plan.accels)

      v_target = interp(starpilot_toggles.longitudinalActuatorDelay + t_since_plan, CONTROL_N_T_IDX, speeds)
      a_target = 2 * (v_target - v_target_now) / starpilot_toggles.longitudinalActuatorDelay - a_target_now

      v_target_1sec = interp(starpilot_toggles.longitudinalActuatorDelay + t_since_plan + 1.0, CONTROL_N_T_IDX, speeds)
    else:
      v_target = 0.0
      v_target_now = 0.0
      v_target_1sec = 0.0
      a_target = 0.0

    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    output_accel = self.last_output_accel
    self.long_control_state = long_control_state_trans_old_long(self.CP, active, self.long_control_state, CS.vEgo,
                                                                v_target, v_target_1sec, CS.brakePressed,
                                                                CS.cruiseState.standstill, long_tuning)

    if self.long_control_state == LongCtrlState.off:
      self.reset_old_long(CS.vEgo)
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      if output_accel > long_tuning.stopAccel:
        output_accel = min(output_accel, 0.0)
        output_accel -= long_tuning.stoppingDecelRate * DT_CTRL
      self.reset_old_long(CS.vEgo)

    elif self.long_control_state == LongCtrlState.starting:
      if getattr(starpilot_toggles, "custom_accel_profile", False):
        output_accel = clip(a_target, 0.0, long_tuning.startAccel)
      else:
        output_accel = long_tuning.startAccel
      self.reset_old_long(CS.vEgo)

    elif self.long_control_state == LongCtrlState.pid:
      self.v_pid = v_target_now

      # Toyota starts braking more when it thinks you want to stop
      # Freeze the integrator so we don't accelerate to compensate, and don't allow positive acceleration
      # TODO too complex, needs to be simplified and tested on toyotas
      prevent_overshoot = not self.CP.stoppingControl and CS.vEgo < 1.5 and v_target_1sec < 0.7 and v_target_1sec < self.v_pid
      deadzone = interp(CS.vEgo, self.CP.longitudinalTuning.deadzoneBP, self.CP.longitudinalTuning.deadzoneV)
      error = self.v_pid - CS.vEgo
      error_deadzone = apply_deadzone(error, deadzone)
      freeze_integrator = prevent_overshoot or self.vehicle_tuning.get_integrator_freeze(
        self.last_output_accel, a_target, error_deadzone, CS.vEgo, accel_limits,
      )
      feedforward = self.vehicle_tuning.get_longitudinal_feedforward(
        self.feedforward_gain, self.last_output_accel, a_target, CS.vEgo,
      )
      output_accel = self.pid.update(error_deadzone, speed=CS.vEgo,
                                     feedforward=feedforward,
                                     freeze_integrator=freeze_integrator)
      if self.is_honda:
        if self.honda_scale_excludes_kf:
          output_accel = (output_accel - self.pid.f) * self.honda_long_pid_tune_scale + self.pid.f
        else:
          output_accel *= self.honda_long_pid_tune_scale

    self.last_output_accel = clip(output_accel, accel_limits[0], accel_limits[1])

    return self.last_output_accel
