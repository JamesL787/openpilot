import math
import numpy as np

from cereal import log
from opendbc.car.honda.carcontroller import get_civic_bosch_modified_steering_pressed, get_eps_modified_steering_pressed
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.pid import PIDController
from openpilot.starpilot.common.testing_grounds import testing_ground
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.selfdrive.controls.lib.nrdr_tune_learner import TuneLearner
from openpilot.selfdrive.modeld.constants import ModelConstants


# nrdr: the Clarity's Nidec rack is variable-ratio, but paramsd learns ONE steerRatio.
# Log-derived test curve: higher effective ratio near center, tapering down as the rack
# quickens at larger steering angles, then holding the high-angle plateau.
NRDR_STEER_RATIO_ANGLE_BP = [0.0, 75.0, 150.0, 250.0]  # |steering-wheel angle|, deg
NRDR_STEER_RATIO_V = [18.5, 17.4, 16.0, 15.6]          # effective steer ratio at each break


CENTER_TAPER_FADE_TAU = 0.25
UNWIND_LOOKAHEAD_MIN_IDX = 5
UNWIND_LOOKAHEAD_SECONDS = 1.0
UNWIND_LOOKAHEAD_MIN_LAT_ACCEL = 0.3
UNWIND_BOOST_FADE_S = 0.3
UNWIND_FREEZE_PHASE_THRESHOLD = -0.2
UNWIND_FREEZE_ANGLE_NEAR_CENTER = 8.0
_MPH_TO_MS = 0.44704
_LAT_SCALE_LOW_MAX = 25.0 * _MPH_TO_MS
_LAT_SCALE_STD_MAX = 50.0 * _MPH_TO_MS
CENTER_BOOST_SPEED_FADE_MS = 5.0 * _MPH_TO_MS

HONDA_PID_GAIN_SCALE_MIN = 0.1
HONDA_PID_GAIN_SCALE_MAX = 4.0


def civic_bosch_modified_lateral_testing_ground_active() -> bool:
  return testing_ground.use("8", "B")


def get_honda_lateral_pid_gain_scale(value) -> float:
  try:
    scale = float(value)
  except (TypeError, ValueError):
    return 1.0
  if not math.isfinite(scale):
    return 1.0
  return min(max(scale, HONDA_PID_GAIN_SCALE_MIN), HONDA_PID_GAIN_SCALE_MAX)


def scale_lateral_pid_gain_values(values, scale: float) -> list[float]:
  return [float(value) * scale for value in values]


def get_civic_bosch_modified_pid_output_scale(desired_angle_deg: float, desired_angle_delta_deg: float, v_ego: float) -> float:
  abs_angle = abs(desired_angle_deg)
  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  center_speed_weight = 0.70 + (0.30 * speed_weight)
  center_weight = min(max((18.0 - abs_angle) / 18.0, 0.0), 1.0)
  mid_turn_weight = min(max((abs_angle - 10.0) / 10.0, 0.0), 1.0)
  angle_weight = min(max((abs_angle - 18.0) / 10.0, 0.0), 1.0)
  phase = desired_angle_deg * desired_angle_delta_deg

  is_left = desired_angle_deg > 0.0
  center_taper = 0.32
  mid_turn_scale = 0.12 if is_left else -0.10
  mid_turn_turn_in_scale = 0.08 if is_left else -0.08
  mid_turn_unwind_scale = -0.05 if is_left else -0.08
  base_scale = 0.12 if is_left else 0.10
  turn_in_scale = 0.12 if is_left else 0.12
  unwind_scale = 0.14 if is_left else 0.18

  scale = 1.0 - (center_speed_weight * center_weight * center_taper)
  scale += speed_weight * mid_turn_weight * mid_turn_scale
  scale += speed_weight * angle_weight * base_scale
  if phase > 0.2:
    scale += speed_weight * mid_turn_weight * mid_turn_turn_in_scale
    scale += speed_weight * angle_weight * turn_in_scale
  elif phase < -0.2:
    scale += speed_weight * mid_turn_weight * mid_turn_unwind_scale
    scale -= speed_weight * angle_weight * unwind_scale

  return max(scale, 0.70)


def get_civic_bosch_modified_pid_output_alpha(desired_angle_deg: float, desired_angle_delta_deg: float,
                                              v_ego: float, output_torque: float, prev_output_torque: float) -> float:
  abs_angle = abs(desired_angle_deg)
  if abs_angle < 0.75 or abs_angle > 22.0:
    return 1.0

  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  onset = min(max((abs_angle - 0.75) / 5.25, 0.0), 1.0)
  cutoff = min(max((22.0 - abs_angle) / 8.0, 0.0), 1.0)
  band_weight = onset * cutoff
  small_curve_weight = min(max((12.0 - abs_angle) / 6.0, 0.0), 1.0)
  large_turn_weight = min(max((abs_angle - 16.0) / 6.0, 0.0), 1.0)
  transition_weight = min(abs(desired_angle_delta_deg) / 0.35, 1.0)
  sign_change_weight = 1.0 if (output_torque * prev_output_torque) < 0.0 else 0.0

  smoothing = band_weight * (0.36 + (0.22 * speed_weight) + (0.12 * transition_weight) + (0.12 * sign_change_weight))
  smoothing *= 1.0 + (0.35 * small_curve_weight)
  smoothing *= 1.0 - (0.50 * large_turn_weight)
  return min(max(1.0 - smoothing, 0.14), 1.0)


def _lat_pid_scale_banded(v_ego: float, low: float, standard: float, highway: float) -> float:
  if v_ego < _LAT_SCALE_LOW_MAX:
    return low
  if v_ego < _LAT_SCALE_STD_MAX:
    return standard
  return highway


def _sign(x: float) -> float:
  return 1.0 if x > 0.0 else (-1.0 if x < 0.0 else 0.0)


def _lookahead_release(future_vals, current_val) -> float:
  if not future_vals:
    return current_val
  same_sign = [v for v in future_vals if _sign(v) == _sign(current_val)]
  if len(same_sign) < len(future_vals):
    return 0.0
  return min(same_sign + [current_val], key=lambda x: abs(x))


def _get_param_float(params, key, default, min_value=None, max_value=None, scale=1.0):
  try:
    value = params.get(key)
  except Exception:
    value = None
  if value is None:
    ret = default
  else:
    try:
      if isinstance(value, bytes):
        value = value.decode("utf-8")
      ret = float(value) / scale
    except (AttributeError, TypeError, ValueError):
      ret = default

  if min_value is not None:
    ret = max(min_value, ret)
  if max_value is not None:
    ret = min(max_value, ret)
  return ret


def _get_param_bool(params, key, default=False):
  try:
    return bool(params.get_bool(key))
  except Exception:
    return default


def _clarity_eps_pid_output_scale(
  desired_angle_deg: float,
  desired_angle_delta_deg: float,
  steering_rate_deg: float,
  v_ego: float,
  center_taper_scale: float,
  center_taper_high: float,
  center_boost_threshold_deg: float,
  center_boost_min_speed_ms: float,
) -> float:
  abs_angle = abs(desired_angle_deg)
  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  mid_turn_weight = min(max((abs_angle - 10.0) / 10.0, 0.0), 1.0)
  angle_weight = min(max((abs_angle - 16.0) / 12.0, 0.0), 1.0)
  phase = desired_angle_deg * desired_angle_delta_deg
  is_left = desired_angle_deg > 0.0

  low_speed_unwind_weight = min(max(1.0 - (v_ego / (15.0 * _MPH_TO_MS)), 0.0), 1.0)
  steering_rate_unwind = desired_angle_deg * steering_rate_deg < -1.0
  low_speed_unwind = low_speed_unwind_weight > 0.0 and steering_rate_unwind

  center_fade_deg = 1.0
  center_weight = min(max((center_boost_threshold_deg + center_fade_deg - abs_angle) / center_fade_deg, 0.0), 1.0)
  if center_boost_min_speed_ms > 0.0:
    center_speed_weight = min(max((v_ego - center_boost_min_speed_ms) / CENTER_BOOST_SPEED_FADE_MS, 0.0), 1.0)
  else:
    center_speed_weight = 1.0
  center_taper = center_taper_high * center_taper_scale * center_speed_weight

  mid_turn_scale = 0.1200 if is_left else 0.0150
  mid_turn_turn_in_scale = -0.5500 if is_left else -0.0524
  mid_turn_unwind_scale = -0.0743 if is_left else -0.0842
  base_scale = 0.0722 if is_left else 0.0972
  turn_in_scale = -0.0799 if is_left else 0.0888
  unwind_scale = 0.1600 if is_left else 0.2000

  scale = 1.0 + (center_weight * center_taper)
  scale += speed_weight * mid_turn_weight * mid_turn_scale
  scale += speed_weight * angle_weight * base_scale

  turn_in_weight = min(max(phase / 0.5, 0.0), 1.0)
  unwind_weight = min(max(-phase / 0.5, 0.0), 1.0)
  if low_speed_unwind and speed_weight < 0.1:
    scale += low_speed_unwind_weight * mid_turn_weight * 0.18
  else:
    scale += speed_weight * mid_turn_weight * (turn_in_weight * mid_turn_turn_in_scale + unwind_weight * mid_turn_unwind_scale)
    scale += speed_weight * angle_weight * (turn_in_weight * turn_in_scale - unwind_weight * unwind_scale)

  return max(scale, 0.6863)


class LatControlPID(LatControl):
  def __init__(self, CP, CI, dt):
    super().__init__(CP, CI, dt)
    self.base_kp_bp = [float(value) for value in CP.lateralTuning.pid.kpBP]
    self.base_kp_v = [float(value) for value in CP.lateralTuning.pid.kpV]
    self.base_ki_bp = [float(value) for value in CP.lateralTuning.pid.kiBP]
    self.base_ki_v = [float(value) for value in CP.lateralTuning.pid.kiV]
    self.pid = PIDController((self.base_kp_bp, self.base_kp_v),
                             (self.base_ki_bp, self.base_ki_v),
                             pos_limit=self.steer_max, neg_limit=-self.steer_max)
    self.ff_factor = CP.lateralTuning.pid.kf
    self.get_steer_feedforward = CI.get_steer_feedforward_function()
    self.is_honda_pid_lateral = CP.brand == "honda"
    self.honda_lateral_pid_kp_scale = 1.0
    self.honda_lateral_pid_ki_scale = 1.0
    self.is_civic_bosch_modified = CP.carFingerprint == HONDA.HONDA_CIVIC_BOSCH and bool(CP.flags & HondaFlags.EPS_MODIFIED)
    self.is_clarity_eps_modified = CP.carFingerprint == HONDA.HONDA_CLARITY and bool(CP.flags & HondaFlags.EPS_MODIFIED)
    self.prev_angle_steers_des_no_offset = 0.0
    self.modified_civic_steering_pressed_filter_s = 0.0
    self.modified_civic_steering_pressed_prev = False
    self.eps_modified_steering_pressed_filter_s = 0.0
    self.eps_modified_steering_pressed_prev = False
    self.prev_output_torque = 0.0
    self.center_taper_scale = FirstOrderFilter(1.0, CENTER_TAPER_FADE_TAU, dt)
    self.dt = dt
    self.params = Params()
    self.frame = -1
    self.tune_learner = TuneLearner(dt, self.steer_max)
    self.lat_p_scale_low = 1.0
    self.lat_p_scale_standard = 1.35
    self.lat_p_scale_highway = 2.0
    self.lat_i_scale_low = 1.0
    self.lat_i_scale_standard = 1.35
    self.lat_i_scale_highway = 2.0
    self.lat_f_scale_low = 1.0
    self.lat_f_scale_standard = 1.0
    self.lat_f_scale_highway = 1.0
    self.center_taper_high = 0.5
    self.center_boost_threshold = 3.0
    self.center_boost_min_speed = 50.0
    self.unwind_freeze_enabled = False
    self.unwind_lookahead_enabled = False
    self.unwind_ff_multiplier = 2.0
    self.unwind_boost_cap_s = 1.0
    self.unwind_boost_elapsed = 0.0

  def update_honda_lateral_pid_gain_scale(self, starpilot_toggles):
    if not self.is_honda_pid_lateral:
      return

    kp_scale = get_honda_lateral_pid_gain_scale(getattr(starpilot_toggles, "honda_lateral_pid_kp_scale", 1.0))
    ki_scale = get_honda_lateral_pid_gain_scale(getattr(starpilot_toggles, "honda_lateral_pid_ki_scale", 1.0))
    if math.isclose(kp_scale, self.honda_lateral_pid_kp_scale) and math.isclose(ki_scale, self.honda_lateral_pid_ki_scale):
      return

    self.honda_lateral_pid_kp_scale = kp_scale
    self.honda_lateral_pid_ki_scale = ki_scale
    self.pid._k_p = [self.base_kp_bp, scale_lateral_pid_gain_values(self.base_kp_v, kp_scale)]
    self.pid._k_i = [self.base_ki_bp, scale_lateral_pid_gain_values(self.base_ki_v, ki_scale)]

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, curvature_limited,
             lat_delay, calibrated_pose, model_data, starpilot_toggles):
    self.update_honda_lateral_pid_gain_scale(starpilot_toggles)

    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)

    if self.is_clarity_eps_modified:
      # NRDR: apply the variable-rack taper before curvature->angle conversion. controlsd
      # refreshes VM every frame, so this per-frame override cannot compound.
      VM.sR = float(np.interp(abs(CS.steeringAngleDeg), NRDR_STEER_RATIO_ANGLE_BP, NRDR_STEER_RATIO_V))

    angle_steers_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
    angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    error = angle_steers_des - CS.steeringAngleDeg

    pid_log.steeringAngleDesiredDeg = angle_steers_des
    pid_log.angleError = error
    if not active:
      output_torque = 0.0
      pid_log.active = False
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self.modified_civic_steering_pressed_filter_s = 0.0
      self.modified_civic_steering_pressed_prev = False
      self.eps_modified_steering_pressed_filter_s = 0.0
      self.eps_modified_steering_pressed_prev = False
      self.center_taper_scale.x = 1.0
      self.unwind_boost_elapsed = 0.0
      self.prev_output_torque = 0.0

    else:
      self.frame += 1
      desired_angle_delta = angle_steers_des_no_offset - self.prev_angle_steers_des_no_offset
      phase = angle_steers_des_no_offset * desired_angle_delta

      # offset does not contribute to resistive torque
      ff = self.ff_factor * self.get_steer_feedforward(angle_steers_des_no_offset, CS.vEgo)
      abs_angle_des = abs(angle_steers_des_no_offset)
      unwind_predicted = False
      if self.is_clarity_eps_modified:
        unwind_ff_boost = float(np.interp(CS.vEgo, [0.0, 10.0], [self.unwind_ff_multiplier, 1.0]))
        steering_rate_unwind_ff = angle_steers_des_no_offset * float(CS.steeringRateDeg) < -1.0
        ff_unwind_weight = min(max(-phase / 0.5, 0.0), 1.0)
        if steering_rate_unwind_ff and abs_angle_des > 5.0:
          ff_unwind_weight = max(ff_unwind_weight, 0.5)

        predicted_unwind_weight = 0.0
        if self.unwind_lookahead_enabled and model_data is not None and len(model_data.acceleration.y) >= CONTROL_N:
          lat_accels = list(model_data.acceleration.y)
          if len(lat_accels) > UNWIND_LOOKAHEAD_MIN_IDX:
            current_la = float(lat_accels[0])
            upper_idx = next((i for i, t in enumerate(ModelConstants.T_IDXS) if t > UNWIND_LOOKAHEAD_SECONDS), len(lat_accels))
            future = [float(v) for v in lat_accels[UNWIND_LOOKAHEAD_MIN_IDX:upper_idx]]
            lookahead_la = _lookahead_release(future, current_la)
            if abs(current_la) > UNWIND_LOOKAHEAD_MIN_LAT_ACCEL:
              predicted_unwind_weight = min(max(1.0 - abs(lookahead_la) / abs(current_la), 0.0), 1.0)
              unwind_predicted = lookahead_la == 0.0 or predicted_unwind_weight > 0.5

        ff_unwind_weight = max(ff_unwind_weight, predicted_unwind_weight)

        if ff_unwind_weight > 0.0:
          self.unwind_boost_elapsed += self.dt
        else:
          self.unwind_boost_elapsed = 0.0
        if self.unwind_boost_cap_s > 0.0:
          fade = min(UNWIND_BOOST_FADE_S, self.unwind_boost_cap_s)
          time_gate = min(max((self.unwind_boost_cap_s - self.unwind_boost_elapsed) / fade, 0.0), 1.0)
        else:
          time_gate = 0.0
        ff_unwind_weight *= time_gate
        ff *= 1.0 + ff_unwind_weight * max(unwind_ff_boost - 1.0, 0.0)

      steering_pressed = CS.steeringPressed
      if self.is_civic_bosch_modified:
        self.modified_civic_steering_pressed_filter_s, steering_pressed = get_civic_bosch_modified_steering_pressed(
          bool(CS.steeringPressed),
          float(getattr(CS, "steeringTorque", 0.0)),
          float(self.prev_output_torque),
          self.modified_civic_steering_pressed_filter_s,
          self.modified_civic_steering_pressed_prev,
        )
        self.modified_civic_steering_pressed_prev = steering_pressed
      elif self.is_clarity_eps_modified:
        self.eps_modified_steering_pressed_filter_s, steering_pressed = get_eps_modified_steering_pressed(
          bool(CS.steeringPressed),
          float(getattr(CS, "steeringTorque", 0.0)),
          float(self.prev_output_torque),
          self.eps_modified_steering_pressed_filter_s,
          self.eps_modified_steering_pressed_prev,
        )
        self.eps_modified_steering_pressed_prev = steering_pressed

      freeze_threshold = 2.0 if self.is_clarity_eps_modified else 5.0
      freeze_integrator = steer_limited_by_safety or steering_pressed or CS.vEgo < freeze_threshold
      unwind_detected = phase < UNWIND_FREEZE_PHASE_THRESHOLD and abs_angle_des < UNWIND_FREEZE_ANGLE_NEAR_CENTER
      if self.is_clarity_eps_modified and self.unwind_freeze_enabled and (unwind_detected or unwind_predicted):
        freeze_integrator = True

      output_torque = self.pid.update(error,
                                feedforward=ff,
                                speed=CS.vEgo,
                                freeze_integrator=freeze_integrator)

      if self.is_clarity_eps_modified:
        if self.frame % 300 == 0:
          self.lat_p_scale_low = _get_param_float(self.params, "LatPScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_p_scale_standard = _get_param_float(self.params, "LatPScaleStandard", 1.35, 0.0, 5.0, scale=100.0)
          self.lat_p_scale_highway = _get_param_float(self.params, "LatPScaleHighway", 2.0, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_low = _get_param_float(self.params, "LatIScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_standard = _get_param_float(self.params, "LatIScaleStandard", 1.35, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_highway = _get_param_float(self.params, "LatIScaleHighway", 2.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_low = _get_param_float(self.params, "LatFScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_standard = _get_param_float(self.params, "LatFScaleStandard", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_highway = _get_param_float(self.params, "LatFScaleHighway", 1.0, 0.0, 5.0, scale=100.0)
          self.center_taper_high = _get_param_float(self.params, "HondaCenterScale", 0.5, 0.0, 5.0)
          self.center_boost_threshold = _get_param_float(self.params, "HondaCenterBoostThreshold", 3.0, 0.0, 10.0)
          self.center_boost_min_speed = _get_param_float(self.params, "HondaCenterBoostMinSpeed", 50.0, 0.0, 90.0)
          self.unwind_freeze_enabled = _get_param_bool(self.params, "HondaUnwindFreeze")
          self.unwind_lookahead_enabled = _get_param_bool(self.params, "HondaUnwindLookahead")
          self.unwind_ff_multiplier = _get_param_float(self.params, "HondaUnwindFfMultiplier", 2.0, 1.0, 4.0)
          self.unwind_boost_cap_s = _get_param_float(self.params, "HondaUnwindBoostSeconds", 1.0, 0.0, 3.0)

        p_scale = _lat_pid_scale_banded(CS.vEgo, self.lat_p_scale_low, self.lat_p_scale_standard, self.lat_p_scale_highway)
        i_scale = _lat_pid_scale_banded(CS.vEgo, self.lat_i_scale_low, self.lat_i_scale_standard, self.lat_i_scale_highway)
        f_scale = _lat_pid_scale_banded(CS.vEgo, self.lat_f_scale_low, self.lat_f_scale_standard, self.lat_f_scale_highway)
        output_torque = self.pid.p * p_scale + self.pid.i * i_scale + self.pid.d + self.pid.f * f_scale

        lane_change = bool(getattr(CS, "leftBlinker", False) or getattr(CS, "rightBlinker", False))
        if lane_change:
          self.center_taper_scale.x = 0.0
          center_taper_scale = 0.0
        else:
          center_taper_scale = float(self.center_taper_scale.update(1.0))
        output_torque *= _clarity_eps_pid_output_scale(
          angle_steers_des_no_offset,
          desired_angle_delta,
          float(CS.steeringRateDeg),
          CS.vEgo,
          center_taper_scale,
          self.center_taper_high,
          self.center_boost_threshold,
          self.center_boost_min_speed * _MPH_TO_MS,
        )
        output_torque = float(max(min(output_torque, self.steer_max), -self.steer_max))

      if self.is_civic_bosch_modified and civic_bosch_modified_lateral_testing_ground_active():
        output_torque *= get_civic_bosch_modified_pid_output_scale(angle_steers_des_no_offset, desired_angle_delta, CS.vEgo)
        output_alpha = get_civic_bosch_modified_pid_output_alpha(angle_steers_des_no_offset, desired_angle_delta, CS.vEgo,
                                                                 output_torque, self.prev_output_torque)
        output_torque = self.prev_output_torque + (output_alpha * (output_torque - self.prev_output_torque))
        output_torque = float(max(min(output_torque, self.steer_max), -self.steer_max))

      output_torque += self.tune_learner.apply(CS.vEgo, angle_steers_des)
      output_torque = float(max(min(output_torque, self.steer_max), -self.steer_max))

      paramsd_ok = bool(
        getattr(params, "valid", True) and
        getattr(params, "angleOffsetValid", True) and
        getattr(params, "steerRatioValid", True) and
        getattr(params, "stiffnessFactorValid", True)
      )
      self.tune_learner.learn(CS.vEgo, angle_steers_des, error, float(CS.steeringRateDeg), steering_pressed, paramsd_ok, self.frame)

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(output_torque)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self.prev_output_torque = float(output_torque)

    return output_torque, angle_steers_des, pid_log
