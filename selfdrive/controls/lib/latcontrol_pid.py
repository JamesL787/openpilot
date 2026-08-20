import math
import numpy as np

from cereal import log
from opendbc.car.honda.carcontroller import get_eps_modified_steering_pressed
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, vgr_linear_to_physical
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.pid import PIDController
from openpilot.starpilot.common.testing_grounds import testing_ground
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import (
  RAV4_TSS2_CARS,
  SUBARU_IMPREZA_CARS,
  get_rav4_tss2_pid_output,
  get_subaru_impreza_pid_output_scale,
)
from openpilot.selfdrive.controls.lib.nrdr_lat_stiction import LatStiction
from openpilot.selfdrive.controls.lib.nrdr_tune_learner import TuneLearner


# Clarity effective-ratio schedule: EPS position-table shape, scaled to road measurement.
#
# Derived 2026-08-15 and it replaces the 4f3271d6af road fit, which tapered 1.440x. Two
# independent sources say that was roughly twice the real taper:
#
#   * The EPS position table (Y 16384 -> 18952) tapers 1.157x centre to lock.
#   * Corrected road data over 3392 samples tapers 1.161x over the same span.
#
# The old fit inverted KINEMATIC steering (atan(L*curv)), which assumes no tyre slip and so
# overstates the ratio by 1/(L*curvature_factor(u)) -- about 1.02x at 10 mph but 1.37x at
# 55 mph. Because speed correlates with angle (highway is small-angle, parking is large),
# that inflated the near-centre bins far more than the outer ones and manufactured taper the
# rack does not have. Solving VehicleModel's own equation instead, theta = (curv - roll_comp)
# * sR / curvature_factor(u), removes it.
#
# Shape comes from the firmware table because it is dense and noise-free; the absolute level
# is a weighted least-squares fit to the measured bins (n/IQR^2 weighting, reliable bins from
# 32 to 330 deg only). Residual is within 2.5% at every measured point. Below ~30 deg the
# yaw-rate estimate is unusable -- IQR reaches 15-23% and the medians go non-physical -- so
# the curve is held flat there rather than fitted.
#
# The old 12.74 tail came from a claimed Honda end-to-end spec of 12.72 at lock. Neither the
# firmware table nor the road data supports it: both put lock near 14.8-14.9.
NRDR_CLARITY_SR_CURVE_BP = [0., 25., 40., 55., 80., 110., 150., 205., 295., 380.,
                            450.]  # |wheel angle|, deg
NRDR_CLARITY_SR_CURVE_V = [17.890, 17.873, 17.507, 17.458, 16.846, 16.202, 15.637, 15.174,
                           14.759, 14.441, 14.345]

# Civic Bosch (EPS 39990-TBA-C020) road-measured curve, from Peter's 152-segment extract
# (6824 accepted samples) processed with the same slip/roll-corrected estimator. Reliable
# bins only: the 5-15 and 15-25 deg bins are dropped because they RISE off centre, which a
# variable-ratio rack cannot do -- that is the near-centre yaw-rate SNR floor, not geometry.
# Beyond 220 deg, where Peter has no data, the tail follows the C020 position table's shape.
#
# This replaces the firmware VGR map for this car. The map's taper (1.166x) is close to the
# measurement (1.140x over 32-220 deg), but the map only supplies a shape to warp paramsd's
# scalar with, while this is the absolute ratio measured end to end, same as the Clarity.
#
# It also settles the 15.25-vs-17.24 disagreement: against Peter's data the 15.25-centre
# curve is within 2.5% while the 17.24 two-point profile is 6.4% off and tapers 1.459x,
# failing with the same +10% centre / -15% outer signature an uncorrected kinematic fit
# always produces.
NRDR_CIVIC_BOSCH_SR_CURVE_BP = [0., 32., 50., 75., 110., 155., 220., 300., 400.]  # |wheel angle|, deg
NRDR_CIVIC_BOSCH_SR_CURVE_V = [14.960, 14.960, 14.910, 14.740, 14.210, 13.630, 13.120, 12.904, 12.774]

# CR-V 5G road-measured curve, carried over unchanged from 4f3271d6af.  This rack is not
# in HONDA_VGR_PROFILE_BY_FW, so it had been running a flat paramsd scalar with no taper
# at all since the firmware-map work landed.
NRDR_CRV_5G_SR_CURVE_BP = [0., 50., 100., 150., 175., 200.]  # |wheel angle|, deg
NRDR_CRV_5G_SR_CURVE_V = [18.10, 17.80, 16.30, 15.30, 14.90, 14.60]

# Insight two-point road-tested profile from nrdr upstream (36e203995a).  No multi-knot
# Insight measurement has ever existed on this branch, so this is the only road data for
# the car.  The outer breakpoint is derived the same way upstream derives it -- the
# Clarity's 250 deg sample point scaled by this rack's lock angle -- rather than
# transcribed, so it stays identical to the source by construction.
NRDR_CLARITY_LOCK_ANGLE = 2.41 * 180.0
NRDR_INSIGHT_LOCK_ANGLE = 2.54 * 180.0
NRDR_TWO_POINT_OUTER_FRACTION = 250.0 / NRDR_CLARITY_LOCK_ANGLE
NRDR_INSIGHT_SR_CURVE_BP = [0.0, NRDR_INSIGHT_LOCK_ANGLE * NRDR_TWO_POINT_OUTER_FRACTION]  # |wheel angle|, deg
NRDR_INSIGHT_SR_CURVE_V = [16.82, 12.58]

# Road-measured effective-ratio curves, by fingerprint.  A car listed here uses its
# measured curve and does NOT use the firmware VGR map: the EPS position table only
# describes rack-to-steering-wheel (the VGR pinion), and misses the rack-to-roadwheel
# linkage, so on its own it under-tapers and over-commands at angle.  A car absent from
# this dict falls through to the firmware map if it has one, then to a flat CP.steerRatio.
NRDR_SR_CURVE_BY_FP = {
  "HONDA_CLARITY": (NRDR_CLARITY_SR_CURVE_BP, NRDR_CLARITY_SR_CURVE_V),
  "HONDA_CIVIC_BOSCH": (NRDR_CIVIC_BOSCH_SR_CURVE_BP, NRDR_CIVIC_BOSCH_SR_CURVE_V),
  "HONDA_CRV_5G": (NRDR_CRV_5G_SR_CURVE_BP, NRDR_CRV_5G_SR_CURVE_V),
  "HONDA_INSIGHT": (NRDR_INSIGHT_SR_CURVE_BP, NRDR_INSIGHT_SR_CURVE_V),
}

# NRDR modified-EPS speed-banded feedforward shared by Clarity and Civic Bosch. The
# duplicate-near-25 breakpoint preserves the road-tested hard handoff.
NRDR_MODIFIED_EPS_KF_SPEED_BP = [0.0, 25.0 * 0.44704 - 1e-3, 25.0 * 0.44704, 50.0 * 0.44704]  # m/s
NRDR_MODIFIED_EPS_KF_V = [2.4e-6, 1.8e-6, 3.6e-6, 6.0e-6]

# Cars carrying the shared modified-EPS tune (the four-point kp/ki in interface.py). They all
# take the banded feedforward above; every other car keeps the scalar kf from CarParams.
# Kept as a set so adding a car is one entry rather than another term in an or-chain.
NRDR_MODIFIED_EPS_KF_CARS = frozenset({
  "HONDA_CLARITY",
  "HONDA_CIVIC",
  "HONDA_CIVIC_BOSCH",
  "HONDA_INSIGHT",
})


def get_nrdr_modified_eps_kf(v_ego: float) -> float:
  return float(np.interp(v_ego, NRDR_MODIFIED_EPS_KF_SPEED_BP, NRDR_MODIFIED_EPS_KF_V))


CENTER_TAPER_FADE_TAU = 0.25
UNWIND_BOOST_FADE_S = 0.3

# Below this speed the phase SIGN is held rather than recomputed. phase is
# angle * d(angle), and d(angle) is a frame-to-frame difference of the desired angle, so
# at a crawl it is dominated by model jitter and the sign chatters -- which would flip
# every consumer below between turn-in and unwind scaling. Magnitude still comes from the
# current frame; only the direction latches. Adopted from nrdr-development-new a9afab2866.
PHASE_SWITCH_MIN_SPEED = 0.5 * 0.44704  # m/s; _MPH_TO_MS is defined below this point


def phase_with_latch(angle_deg: float, angle_delta_deg: float, v_ego: float,
                     direction: float) -> tuple[float, float]:
  phase = angle_deg * angle_delta_deg
  if phase != 0.0 and (v_ego > PHASE_SWITCH_MIN_SPEED or direction == 0.0):
    direction = 1.0 if phase > 0.0 else -1.0
  return abs(phase) * direction, direction
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


def get_civic_bosch_modified_pid_output_scale(desired_angle_deg: float, phase: float, v_ego: float) -> float:
  abs_angle = abs(desired_angle_deg)
  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  center_speed_weight = 0.70 + (0.30 * speed_weight)
  center_weight = min(max((18.0 - abs_angle) / 18.0, 0.0), 1.0)
  mid_turn_weight = min(max((abs_angle - 10.0) / 10.0, 0.0), 1.0)
  angle_weight = min(max((abs_angle - 18.0) / 10.0, 0.0), 1.0)

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
  phase: float,
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
    self.is_modified_eps_kf_car = (str(CP.carFingerprint) in NRDR_MODIFIED_EPS_KF_CARS
                                   and bool(CP.flags & HondaFlags.EPS_MODIFIED))
    self.is_civic_bosch_modified = CP.carFingerprint == HONDA.HONDA_CIVIC_BOSCH and bool(CP.flags & HondaFlags.EPS_MODIFIED)
    self.is_subaru_impreza = CP.carFingerprint in SUBARU_IMPREZA_CARS
    # NRDR: every modified-EPS Honda (Civic 39990-TBA, CR-V 5G 39990-TLA, Insight 39990-TXM,
    # Clarity 39990-TRW) runs the live tune.
    self.is_eps_modified = self.is_honda_pid_lateral and bool(CP.flags & HondaFlags.EPS_MODIFIED)
    # A car with a road-measured curve uses it. The firmware position map is a partial
    # correction (rack-to-steering-wheel only) and is the fallback for a mapped rack that
    # has no measured curve yet -- currently just the Civic Bosch.
    self.sr_curve = NRDR_SR_CURVE_BY_FP.get(str(CP.carFingerprint))
    # VGR is selected by exact EPS firmware, and only for a car with no measured curve.
    # There is intentionally no vehicle-family fallback: another rack's table is not
    # interchangeable.
    self.vgr_inverse = None if self.sr_curve is not None else get_honda_vgr_inverse(CP.flags)
    self.is_rav4_tss2 = CP.carFingerprint in RAV4_TSS2_CARS
    self.prev_angle_steers_des_no_offset = 0.0
    self.eps_modified_steering_pressed_filter_s = 0.0
    self.eps_modified_steering_pressed_prev = False
    self.prev_output_torque = 0.0
    self.center_taper_scale = FirstOrderFilter(1.0, CENTER_TAPER_FADE_TAU, dt)
    self.dt = dt
    self.params = Params()
    self.frame = -1
    self.tune_learner = TuneLearner(dt, self.steer_max)
    self.lat_p_scale_low = 1.0
    self.lat_p_scale_standard = 1.0
    self.lat_p_scale_highway = 1.0
    self.lat_i_scale_low = 1.0
    self.lat_i_scale_standard = 1.0
    self.lat_i_scale_highway = 1.0
    self.lat_f_scale_low = 1.0
    self.lat_f_scale_standard = 1.0
    self.lat_f_scale_highway = 1.0
    self.center_taper_high = 0.5
    self.center_boost_threshold = 3.0
    self.center_boost_min_speed = 50.0
    self.phase_direction = 0.0
    self.unwind_freeze_enabled = False
    self.unwind_ff_multiplier = 2.0
    self.unwind_boost_cap_s = 1.0
    self.unwind_boost_elapsed = 0.0
    self.lat_stiction = LatStiction(dt, self.steer_max)
    self.lat_stiction_enabled = False
    self.prev_saturated = False

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

    if self.sr_curve is not None:
      # Road-measured effective ratio, selected at the MEASURED angle. Fitted from steering
      # wheel angle to achieved yaw rate, so it spans the whole chain: VGR pinion, rack,
      # linkage, Ackermann, compliance and tyres. The firmware position map covers only the
      # first of those -- 1.157x of the Clarity's measured 1.440x taper -- which is why using
      # it alone leaves the ratio too high at angle and over-commands. controlsd refreshes VM
      # every frame, so this override cannot compound.
      sr_bp, sr_v = self.sr_curve
      VM.sR = float(np.interp(abs(CS.steeringAngleDeg), sr_bp, sr_v))
      angle_steers_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
      angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    elif self.vgr_inverse is not None:
      # Firmware VGR path. VehicleModel keeps the scalar sR paramsd learned (controlsd sets it
      # every frame), so it returns the angle a constant-ratio rack would need; the measured rack
      # curve is then inverted to get the angle this rack actually needs. Solving at the DESIRED
      # angle is what the old path could not do: selecting sR at the MEASURED angle only agrees
      # when theta_meas == theta_des, and it lets a measurement wobble move the target
      # (a spurious d(theta_des)/d(theta_meas) term inside the loop).
      linear_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
      angle_steers_des_no_offset = vgr_linear_to_physical(linear_des_no_offset, self.vgr_inverse)
      angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    else:
      angle_steers_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
      angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    error = angle_steers_des - CS.steeringAngleDeg

    pid_log.steeringAngleDesiredDeg = angle_steers_des
    pid_log.angleError = error
    if not active:
      output_torque = 0.0
      pid_log.active = False
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self.eps_modified_steering_pressed_filter_s = 0.0
      self.eps_modified_steering_pressed_prev = False
      self.center_taper_scale.x = 1.0
      self.unwind_boost_elapsed = 0.0
      self.prev_output_torque = 0.0
      self.prev_saturated = False
      self.lat_stiction.reset()

    else:
      self.frame += 1
      desired_angle_delta = angle_steers_des_no_offset - self.prev_angle_steers_des_no_offset
      phase, self.phase_direction = phase_with_latch(angle_steers_des_no_offset, desired_angle_delta,
                                                      CS.vEgo, self.phase_direction)

      # offset does not contribute to resistive torque
      if self.is_modified_eps_kf_car:
        ff_factor = get_nrdr_modified_eps_kf(CS.vEgo)
      else:
        ff_factor = self.ff_factor
      ff = ff_factor * self.get_steer_feedforward(angle_steers_des_no_offset, CS.vEgo)
      abs_angle_des = abs(angle_steers_des_no_offset)
      if self.is_eps_modified:
        unwind_ff_boost = float(np.interp(CS.vEgo, [0.0, 10.0], [self.unwind_ff_multiplier, 1.0]))
        steering_rate_unwind_ff = angle_steers_des_no_offset * float(CS.steeringRateDeg) < -1.0
        ff_unwind_weight = min(max(-phase / 0.5, 0.0), 1.0)
        if steering_rate_unwind_ff and abs_angle_des > 5.0:
          ff_unwind_weight = max(ff_unwind_weight, 0.5)


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
      # Civic Bosch used to take a graded detector of its own here. It now shares the generic
      # modified-EPS one with the Clarity, so override feel is identical across the cars.
      if self.is_eps_modified:
        self.eps_modified_steering_pressed_filter_s, steering_pressed = get_eps_modified_steering_pressed(
          bool(CS.steeringPressed),
          float(getattr(CS, "steeringTorque", 0.0)),
          float(self.prev_output_torque),
          self.eps_modified_steering_pressed_filter_s,
          self.eps_modified_steering_pressed_prev,
        )
        self.eps_modified_steering_pressed_prev = steering_pressed

      freeze_threshold = 2.0 if self.is_eps_modified else 5.0
      freeze_integrator = steer_limited_by_safety or steering_pressed or CS.vEgo < freeze_threshold
      unwind_detected = phase < UNWIND_FREEZE_PHASE_THRESHOLD and abs_angle_des < UNWIND_FREEZE_ANGLE_NEAR_CENTER
      if self.is_eps_modified and self.unwind_freeze_enabled and unwind_detected:
        freeze_integrator = True

      output_torque = self.pid.update(error,
                                feedforward=ff,
                                speed=CS.vEgo,
                                freeze_integrator=freeze_integrator)

      # The Civic Bosch testing ground applies its own hardcoded center taper below; let it own the
      # output scale so the two tapers can never compound.
      civic_bosch_testing_ground = self.is_civic_bosch_modified and civic_bosch_modified_lateral_testing_ground_active()

      if self.is_eps_modified:
        if self.frame % 300 == 0:
          # Lat*Scale are pure user fine-trim now: every modified-EPS car gets its banding from
          # kpBP/kpV in interface.py, and these params default to a neutral 100. The old
          # Clarity-only gate here existed because they defaulted 135/200 and would otherwise
          # leak the Clarity curve onto Civic/CR-V/Insight; that premise is gone.
          self.lat_p_scale_low = _get_param_float(self.params, "LatPScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_p_scale_standard = _get_param_float(self.params, "LatPScaleStandard", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_p_scale_highway = _get_param_float(self.params, "LatPScaleHighway", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_low = _get_param_float(self.params, "LatIScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_standard = _get_param_float(self.params, "LatIScaleStandard", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_highway = _get_param_float(self.params, "LatIScaleHighway", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_low = _get_param_float(self.params, "LatFScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_standard = _get_param_float(self.params, "LatFScaleStandard", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_highway = _get_param_float(self.params, "LatFScaleHighway", 1.0, 0.0, 5.0, scale=100.0)
          self.center_taper_high = _get_param_float(self.params, "HondaCenterScale", 0.5, 0.0, 5.0)
          self.center_boost_threshold = _get_param_float(self.params, "HondaCenterBoostThreshold", 3.0, 0.0, 10.0)
          self.center_boost_min_speed = _get_param_float(self.params, "HondaCenterBoostMinSpeed", 50.0, 0.0, 90.0)
          self.unwind_freeze_enabled = _get_param_bool(self.params, "HondaUnwindFreeze")
          self.unwind_ff_multiplier = _get_param_float(self.params, "HondaUnwindFfMultiplier", 2.0, 1.0, 4.0)
          self.unwind_boost_cap_s = _get_param_float(self.params, "HondaUnwindBoostSeconds", 1.0, 0.0, 3.0)
          self.lat_stiction_enabled = _get_param_bool(self.params, "NrdrLatStiction")

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
        if not civic_bosch_testing_ground:
          output_torque *= _clarity_eps_pid_output_scale(
            angle_steers_des_no_offset,
            phase,
            float(CS.steeringRateDeg),
            CS.vEgo,
            center_taper_scale,
            self.center_taper_high,
            self.center_boost_threshold,
            self.center_boost_min_speed * _MPH_TO_MS,
          )

      if self.is_subaru_impreza:
        raw_output_torque = self.pid.p + self.pid.i + self.pid.d + self.pid.f
        output_torque = raw_output_torque * get_subaru_impreza_pid_output_scale(error)

      output_torque = float(max(min(output_torque, self.steer_max), -self.steer_max))

      if self.is_rav4_tss2:
        output_torque = get_rav4_tss2_pid_output(output_torque, self.prev_output_torque,
                                                angle_steers_des_no_offset, CS.vEgo)
        output_torque = float(max(min(output_torque, self.steer_max), -self.steer_max))

      if civic_bosch_testing_ground:
        output_torque *= get_civic_bosch_modified_pid_output_scale(angle_steers_des_no_offset, phase, CS.vEgo)
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

      # nrdr stiction output stage:
      if self.lat_stiction_enabled:
        des_rate_degs = desired_angle_delta / self.dt
        lane_change_stiction = bool(getattr(CS, "leftBlinker", False) or getattr(CS, "rightBlinker", False))
        output_torque = float(self.lat_stiction.update(
          active, CS.vEgo, error, des_rate_degs, float(CS.steeringRateDeg), output_torque,
          steering_pressed, lane_change_stiction, self.prev_saturated))
      else:
        self.lat_stiction.reset()

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(output_torque)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self.prev_output_torque = float(output_torque)
      self.prev_saturated = bool(pid_log.saturated)

    return output_torque, angle_steers_des, pid_log
