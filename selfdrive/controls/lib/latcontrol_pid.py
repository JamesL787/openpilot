import json
import math
import numpy as np

from cereal import custom, log
from opendbc.car.honda.carcontroller import get_eps_modified_steering_pressed
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, vgr_linear_to_physical
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.pid import PIDController
from openpilot.common.swaglog import cloudlog
from openpilot.starpilot.common.testing_grounds import testing_ground
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.nrdr_eps_firmware_ff import CIVIC_BOSCH_C020, CIVIC_PID_LOAD, CIVIC_PID_LOAD_MIN_V, \
  CLARITY_A020, HondaEpsFirmwareFeedforward
from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import (
  RAV4_TSS2_CARS,
  SUBARU_IMPREZA_CARS,
  get_honda_crv_5g_pid_output,
  get_rav4_tss2_pid_output,
  get_subaru_impreza_pid_output_scale,
)


# nrdr: the Clarity's Nidec rack is variable-ratio, but paramsd learns ONE steerRatio.
#
# RESTORED 2026-08-19 from bbff849969^, the last state before the firmware VGR map work.
# This is the shape the car demonstrably drove best on. Everything that replaced it --
# the firmware position map (bbff8499/fbf4c5fa), the 393b2c11e2 road fit (18.340 centre),
# the 0698635629 retaper (17.248) and the 536a9f6304 refit (17.890) -- was justified on
# fit residual, and none of them drove better. From 90 degrees out this is bit-identical
# to the 393b2c11e2 curve; the whole difference is a 7-10%% higher ratio inside 90 degrees.
#
# Values from nrdr a954d153e7 (2026-07-31), "Blend learned Clarity steer ratio into
# proven tail", carried over from nrdr-clarity-backport. Replaces the old two-point
# [0, 250] -> [17.00, 12.74] taper that this branch still had.
#
# The <= 70 degree section is the sample-weighted, non-increasing fit of the measured
# 5 degree bins. The noisy 5-10 degree rise is capped at the 0-5 degree median, and every
# later upward violation is pooled with its neighbour(s) instead of being allowed to create
# an unphysical ratio increase. A smoothstep-sampled 70-90 degree handoff rejoins the
# previous road-proven curve at exactly its existing 90 degree value; 90 degrees onward is
# unchanged except for the corrected Honda end-to-end specification of 12.72 at 450 degrees.
NRDR_CLARITY_SR_CURVE_BP = [0., 2.5, 7.5, 12.5, 17.5, 22.5, 27.5, 32.5, 37.5, 42.5, 47.5, 52.5, 57.5,
                            62.5, 67.5, 70., 75., 80., 85., 90., 100., 140., 200., 300., 450.]  # |wheel angle|, deg
NRDR_CLARITY_SR_CURVE_V = [19.680, 19.680, 19.680, 19.680, 19.344, 19.344, 19.307, 19.151, 18.406, 18.406,
                           18.406, 18.087, 17.999, 17.999, 17.710, 17.604, 17.222, 16.706, 16.308, 16.093333333333334,
                           15.940, 15.400, 14.300, 13.400, 12.720]

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


def build_steer_ratio_inverse(curve_bp, curve_v) -> list[float]:
  """Unit-ratio angle breakpoints for a measured effective-ratio curve.

  VehicleModel.get_steer_from_curvature is exactly linear in sR -- curvature_factor and
  roll_compensation depend only on the vehicle's mass, geometry and speed -- so the desired
  wheel angle satisfies

      theta_des = A * sR(|theta_des|)

  where A is the angle the same command would need at sR = 1. Evaluating x / sR(x) at each
  knot gives the A that lands exactly on that knot, and since sR is non-increasing while x
  increases those values are strictly increasing -- so these bracket the solution for any A,
  in one step and without ever referring to the measured angle. solve_angle_from_ratio_curve
  then closes the segment exactly; see there for why interpolating this table is not enough.
  """
  assert all(low < high for low, high in zip(curve_bp, curve_bp[1:], strict=False)), \
    "ratio curve angle breakpoints must be strictly increasing"
  inverse_bp = [angle / ratio for angle, ratio in zip(curve_bp, curve_v, strict=True)]
  assert all(low < high for low, high in zip(inverse_bp, inverse_bp[1:], strict=False)), \
    "ratio curve is not invertible: x / sR(x) must be strictly increasing"
  return inverse_bp


def solve_angle_from_ratio_curve(unit_ratio_angle_deg: float, curve_bp, curve_v, inverse_bp) -> float:
  magnitude = abs(unit_ratio_angle_deg)
  if magnitude >= inverse_bp[-1]:
    # Past the table, np.interp would clamp the ANGLE. The curve clamps the RATIO, so keep
    # extrapolating at the final ratio -- exactly what selecting sR by interpolation did.
    solved = magnitude * curve_v[-1]
  else:
    # inverse_bp is exact AT the knots but interpolating it is not: that would make the
    # solution linear in A, and the inverse of a piecewise-linear sR is not. The drift shows
    # up mid-segment where the knots are widest -- 0.3 deg at 120 deg, 1.7 deg at 350 deg on
    # the Clarity curve, which is the same order as the measured-angle error being removed.
    #
    # Inside the bracketing segment sR is linear, sR(x) = m*x + c, so x = A * sR(x) closes in
    # one step: x = A*c / (1 - A*m). m <= 0 because the ratio is non-increasing and A >= 0, so
    # the denominator is never below 1 and this cannot blow up.
    index = int(np.searchsorted(inverse_bp, magnitude, side="right")) - 1
    index = min(max(index, 0), len(curve_bp) - 2)
    slope = (curve_v[index + 1] - curve_v[index]) / (curve_bp[index + 1] - curve_bp[index])
    intercept = curve_v[index] - slope * curve_bp[index]
    solved = magnitude * intercept / (1.0 - magnitude * slope)
  return math.copysign(solved, unit_ratio_angle_deg)


NRDR_SR_CURVE_INVERSE_BY_FP = {
  fingerprint: build_steer_ratio_inverse(*curve) for fingerprint, curve in NRDR_SR_CURVE_BY_FP.items()
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
  "HONDA_CRV_5G",
  "HONDA_INSIGHT",
})


def get_nrdr_modified_eps_kf(v_ego: float) -> float:
  return float(np.interp(v_ego, NRDR_MODIFIED_EPS_KF_SPEED_BP, NRDR_MODIFIED_EPS_KF_V))


# nrdr: ceiling on how fast the DESIRED wheel angle is allowed to move, deg/s.
#
# clip_curvature() enforces the ISO jerk limit in CURVATURE space -- the allowance is
# MAX_LATERAL_JERK / v_ego**2 -- but this controller works in ANGLE space, and the
# curvature-to-angle gain (sR * wheelbase) is very nearly speed-independent. The allowance
# falls off as 1/v**2 while the gain does not, so the angle-rate ceiling that actually
# reaches the PID is roughly:
#
#     1 mph  15500 deg/s      15 mph   345 deg/s      45 mph    38 deg/s
#     5 mph   3100 deg/s      25 mph   124 deg/s      65 mph    18 deg/s
#
# Sane at road speed, absent below ~20 mph -- exactly where the model's curvature jitter
# reaches the rack as multi-degree per-frame steps in the target, saturating the P term and
# flipping the turn-in/unwind branches of the output scale on alternate frames. A flat deg/s
# ceiling is the constraint that is physical for an angle-space controller, and since
# clip_curvature is already tighter than this above ~16 mph, it can only bind at low speed:
# highway behaviour is unchanged by construction.
#
# This is a slew clip, NOT a filter. Sustained target motion passes through untouched, so it
# costs no phase lag on a real maneuver -- only the per-frame excursions are removed.
NRDR_ANGLE_RATE_LIMIT_DEG_S = 300.0  # 0 disables

# nrdr: time constant for smoothing the desired angle, seconds. Speed-banded through the same
# HondaLpfTau{LowSpeed,Standard,Highway} params the carcontroller LPF used, so an existing
# road tune carries over verbatim.
NRDR_TARGET_SMOOTH_TAU = 0.1

# nrdr: desired-rate feedforward, torque fraction per 100 deg/s of (shaped) target slew. The rack
# damps angle rate, so P alone only moves the wheel once an error has built up: replay and sim
# put the angle 0.15-0.25 s behind the target on every logged route (STATUS 132). This term pays
# for the slew as it is asked for. Default 0 = off (STATUS 133 has the sim sweep).
NRDR_RATE_FF_DEFAULT = 0.0

# nrdr: NrdrLatPidFirmwareFF (STATUS 175) crossfades the kf and rate feedforward into the EPS firmware-inversion
# feedforward (the STATUS 165 path) in turns only. Join gate as upstream fd815ef3: the weight ramps in over
# 0.5 s once the error is under 10 deg, a press or v < 2 m/s drops it, full weight from 4 m/s. On top of that
# the weight scales with |desired angle|, 0 below 10 deg and full from 30 deg: ungated, the feedforward makes
# the wheel follow the model's near-centre wiggle (STATUS 170, route 286, 4-6x PID wobble below 12 m/s).
# Closed-loop sim on 280/284/285/286 kept all of the ungated turn gain with wobble at PID level (STATUS 175).
# Own constants so James's controller (nrdr_eps_firmware_ff.FF_SPEED_BP) can change without moving this.
NRDR_PID_EPS_FF_JOIN_ERROR_DEG = 10.0
NRDR_PID_EPS_FF_FADE_IN_S = 0.5
NRDR_PID_EPS_FF_SPEED_BP = (2.0, 4.0)
NRDR_PID_EPS_FF_ANGLE_BP = (10.0, 30.0)
# nrdr: trailing rejoin. The join above waits for |error| < 10 deg, so after a release in a turn, with the wheel
# short of the path, the feedforward stayed out and the plain PID trailed (road, 28a/28b/28f: 23-33 % of turn time
# latched out, mostly within 1 s of the release). It now also joins when the wheel is short of the turn
# (error * desired > 0) once there has been no press for this long. Replay on 10 PID routes (277-28f, no driver):
# 12-25 mph turn error 14.81 -> 13.51 deg, 93 % of it on turns left hands-off for 2 s or more, overshoot past the
# path +0.28 (27a right 1.46 -> 2.79, 28b left 1.75 -> 2.43); 0 s gained more but fires while the hand comes back
# (road: 64 % of joins meet a press within 0.5 s, 43 % at 0.5 s), 1.0 s kept half as much. A re-grab usually pushes
# against the turn (50 of 60), which replay cannot score: John's sim re-grab row is pending. inf turns it off.
# Only after a real release: since_press_s is inf from engagement until the first press, and 1a0dc489e let that
# through, so it also joined at a mid-turn engagement 20-70 deg short (James, static). An inf since_press_s never joins.
NRDR_PID_EPS_FF_REJOIN_HOLD_S = 0.5


def nrdr_pid_eps_ff_weight(ramp, error_deg, desired_angle_deg, v_ego, steering_pressed, dt, since_press_s=0.0):
  """Returns (ramp, weight). The ramp is the join state; the weight is what multiplies the feedforward.
  since_press_s: time since the last press, for the trailing rejoin (the default 0 leaves it out; inf, no press yet
  this engagement, leaves it out too)."""
  if steering_pressed or v_ego < NRDR_PID_EPS_FF_SPEED_BP[0]:
    ramp = 0.0
  elif ramp > 0.0 or abs(error_deg) < NRDR_PID_EPS_FF_JOIN_ERROR_DEG:
    ramp = min(1.0, ramp + dt / NRDR_PID_EPS_FF_FADE_IN_S)
  elif error_deg * desired_angle_deg > 0.0 and NRDR_PID_EPS_FF_REJOIN_HOLD_S <= since_press_s < math.inf:
    ramp = min(1.0, ramp + dt / NRDR_PID_EPS_FF_FADE_IN_S)
  speed_w = float(np.interp(v_ego, NRDR_PID_EPS_FF_SPEED_BP, (0.0, 1.0)))
  angle_w = float(np.interp(abs(desired_angle_deg), NRDR_PID_EPS_FF_ANGLE_BP, (0.0, 1.0)))
  return ramp, ramp * speed_w * angle_w

# nrdr: the Lat*Scale bands switch hard at 25 and 50 mph, and PIDController integrates at the
# unscaled gain, so a band with an I trim of 0 hid a live integrator. Route 277 (STATUS 136):
# at 50 mph, straight, target flat, vEgo 50.00 -> 49.98 mph stepped the I trim 0 -> 0.75 while
# the hidden i was 0.514, and the output went -0.00 -> +0.39 in one frame, the wheel +160 deg/s left.
# The applied trims now slew, and while the applied I trim is 0 the integrator is frozen and bled out.
NRDR_TRIM_SLEW_PER_S = 0.5
NRDR_HIDDEN_I_BLEED_TAU = 2.0
# nrdr: the base kpBP in interface.py doubles kp at 25 mph (0.024 -> 0.048), so P stepped by the whole
# error x 0.024 there (route 277 replay: -0.11 in one frame at 3.7 deg of error, STATUS 139). The
# applied kp now slews at up to 100 %/s of the larger gain; every steady-speed gain is unchanged.
NRDR_KP_SLEW_REL_PER_S = 1.0
# nrdr: after a press the carcontroller fades torque back in over HondaOverrideFadeUpSecs, and
# every faded frame trips steer_limited_by_safety, which froze the integrator at its pre-press
# value. Route 27a 12:34 (STATUS 143, 143d): two override trips held I at 0.19 into the turn
# through the unwind, where it cancelled 35-45 % of P and the car ran wide toward the curb.
# Below 25 mph 60-70 % of the non-pressed limited frames on 277/278/27a were in that window. The
# held I now bleeds toward 0 during the fade instead. 0.5 s leaves 37 % of it after a 0.5 s fade.
NRDR_OVERRIDE_FADE_I_BLEED_TAU = 0.5
NRDR_OVERRIDE_FADE_UP_S_DEFAULT = 1.5   # carcontroller's HondaOverrideFadeUpSecs default

def rate_limit_desired_angle(angle_deg: float, prev_angle_deg: float, max_rate_deg_s: float, dt: float) -> float:
  if max_rate_deg_s <= 0.0 or not math.isfinite(angle_deg):
    return angle_deg
  max_delta = max_rate_deg_s * dt
  return float(min(max(angle_deg, prev_angle_deg - max_delta), prev_angle_deg + max_delta))


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
_MPH_TO_MS = 0.44704
_LAT_SCALE_LOW_MAX = 25.0 * _MPH_TO_MS
_LAT_SCALE_STD_MAX = 50.0 * _MPH_TO_MS

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


# LatGainSchedule: an optional continuous speed schedule for the modified-EPS P/I/F trims,
# replacing the three Lat*Scale bands per term. JSON, percent values like the band params:
#   {"v_mph": [15, 35, 60], "p": [110, 115, 105], "i": [50, 75, 0], "f": [50, 100, 100]}
# Any of p/i/f may be omitted; an omitted term keeps its band. The whole schedule is rejected
# (every term falls back to the bands) on any malformed field -- an out-of-range knot is never
# clamped into something the owner did not write. Written by tools/lateral/lat_autotune.py for
# review; nothing on the car writes it. Linear between knots, held flat past the end knots.
LAT_GAIN_SCHEDULE_MAX_KNOTS = 8
LAT_GAIN_SCHEDULE_MAX_MPH = 100.0
LAT_GAIN_SCHEDULE_LIMITS = {"p": (25.0, 300.0), "i": (0.0, 300.0), "f": (0.0, 200.0)}


def parse_lat_gain_schedule(raw):
  """Return {"v": [m/s], term: [scale]} or None when absent/invalid."""
  if raw is None:
    return None
  try:
    if isinstance(raw, bytes):
      raw = raw.decode("utf-8")
    if isinstance(raw, str):
      if not raw.strip():
        return None
      raw = json.loads(raw)
    if not isinstance(raw, dict):
      return None
    v_mph = [float(x) for x in raw["v_mph"]]
  except (KeyError, TypeError, ValueError, UnicodeDecodeError):
    return None
  n = len(v_mph)
  if not 2 <= n <= LAT_GAIN_SCHEDULE_MAX_KNOTS:
    return None
  if not all(math.isfinite(x) and 0.0 <= x <= LAT_GAIN_SCHEDULE_MAX_MPH for x in v_mph):
    return None
  if any(b <= a for a, b in zip(v_mph[:-1], v_mph[1:], strict=True)):
    return None
  sched = {"v": [x * _MPH_TO_MS for x in v_mph]}
  for term, (lo, hi) in LAT_GAIN_SCHEDULE_LIMITS.items():
    if term not in raw:
      continue
    try:
      vals = [float(x) for x in raw[term]]
    except (TypeError, ValueError):
      return None
    if len(vals) != n or not all(math.isfinite(x) and lo <= x <= hi for x in vals):
      return None
    sched[term] = [x / 100.0 for x in vals]
  if len(sched) == 1:
    return None
  return sched


def lat_gain_schedule_scale(sched, term: str, v_ego: float, banded: float) -> float:
  if sched is None or term not in sched:
    return banded
  vs = sched["v"]
  ys = sched[term]
  if v_ego <= vs[0]:
    return ys[0]
  for i in range(1, len(vs)):
    if v_ego <= vs[i]:
      t = (v_ego - vs[i - 1]) / (vs[i] - vs[i - 1])
      return ys[i - 1] + t * (ys[i] - ys[i - 1])
  return ys[-1]


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


def _clarity_eps_pid_output_scale(desired_angle_deg: float, v_ego: float) -> float:
  # Adds a little torque as the turn gets deeper, the same for left and right. The turn-in, unwind
  # and centre-boost terms came from starpilot's first Honda PID; they are gone (owner, 2026-09-27;
  # the version James runs on clarity-eps-testing). lat_score gate over 10 routes: pass, 4 improve,
  # none regress (STATUS 186, sim only).
  abs_angle = abs(desired_angle_deg)
  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  mid_turn_weight = min(max((abs_angle - 10.0) / 10.0, 0.0), 1.0)
  angle_weight = min(max((abs_angle - 16.0) / 12.0, 0.0), 1.0)
  return 1.0 + speed_weight * (mid_turn_weight * 0.0675 + angle_weight * 0.0847)


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
    self.is_honda_crv_5g = CP.carFingerprint == HONDA.HONDA_CRV_5G
    self.is_subaru_impreza = CP.carFingerprint in SUBARU_IMPREZA_CARS
    # NRDR: every modified-EPS Honda (Civic 39990-TBA, CR-V 5G 39990-TLA, Insight 39990-TXM,
    # Clarity 39990-TRW) runs the live tune.
    self.is_eps_modified = self.is_honda_pid_lateral and bool(CP.flags & HondaFlags.EPS_MODIFIED)
    # A car with a road-measured curve uses it. The firmware position map is a partial
    # correction (rack-to-steering-wheel only) and is the fallback for a mapped rack that
    # has no measured curve yet -- currently just the Civic Bosch.
    self.sr_curve = NRDR_SR_CURVE_BY_FP.get(str(CP.carFingerprint))
    self.sr_curve_inverse = NRDR_SR_CURVE_INVERSE_BY_FP.get(str(CP.carFingerprint))
    # Selected at runtime by NrdrLatUseFirmwareVgr so the two maps can be A/B'd on the road.
    # They are NOT the same measurement: the road curve is the absolute effective ratio across
    # the whole chain and ignores what paramsd learned, while the firmware map is only a
    # relative warp applied on top of paramsd's scalar. Switching therefore moves the centre
    # gain as well as the taper -- see the comment at the selection in update().
    self.use_firmware_vgr = False
    # VGR is selected by exact EPS firmware. There is intentionally no vehicle-family
    # fallback: another rack's table is not interchangeable, so this stays None for a car
    # whose image was never traced and the toggle below is then inert.
    self.vgr_inverse = get_honda_vgr_inverse(CP.flags)
    self.is_rav4_tss2 = CP.carFingerprint in RAV4_TSS2_CARS
    self.prev_angle_steers_des_no_offset = 0.0
    # nrdr: firmware-inversion feedforward (upstream JamesL787 52618f42). Computed every frame and logged on
    # starpilotLateralState (controlsd publishes it whenever this attribute exists). Only NrdrLatPidFirmwareFF
    # puts it in the command, in turns, gated by nrdr_pid_eps_ff_weight. See nrdr_eps_firmware_ff.py, STATUS 175.
    self.eps_shadow_ff = None
    self.eps_ff_enabled = False
    self.eps_ff_ok = False
    self.eps_ff_ramp = 0.0
    self.eps_ff_weight = 0.0
    eps_shadow_cal = {HONDA.HONDA_CLARITY: CLARITY_A020, HONDA.HONDA_CIVIC_BOSCH: CIVIC_BOSCH_C020}.get(CP.carFingerprint)
    if self.is_eps_modified and eps_shadow_cal is not None:
      eps_shadow_load = CIVIC_PID_LOAD if eps_shadow_cal is CIVIC_BOSCH_C020 else None
      self.eps_shadow_ff = HondaEpsFirmwareFeedforward(dt, cal=eps_shadow_cal, load=eps_shadow_load,
                                                         load_min_v=CIVIC_PID_LOAD_MIN_V)
      self.eps_shadow_failed = False
      self.starpilot_lateral_state = custom.StarPilotLateralState.new_message()
    self.eps_modified_steering_pressed_filter_s = 0.0
    self.eps_modified_steering_pressed_prev = False
    self.prev_output_torque = 0.0
    self.dt = dt
    self.params = Params()
    self.frame = -1
    self.lat_p_scale_low = 1.0
    self.lat_p_scale_standard = 1.0
    self.lat_p_scale_highway = 1.0
    self.lat_i_scale_low = 0.2
    self.lat_i_scale_standard = 1.0
    self.lat_i_scale_highway = 0.0
    self.lat_f_scale_low = 1.0
    self.lat_f_scale_standard = 1.0
    self.lat_f_scale_highway = 1.0
    self.lat_gain_schedule = None
    self.phase_direction = 0.0
    self.angle_rate_limit_deg_s = NRDR_ANGLE_RATE_LIMIT_DEG_S
    # The rate limiter needs its own reference: chaining it off the SMOOTHED target would make
    # each frame's allowance alpha * max_delta instead of max_delta, throttling real steering.
    self.prev_rate_limited_angle = 0.0
    self.target_smooth_filter = FirstOrderFilter(0.0, NRDR_TARGET_SMOOTH_TAU, dt, initialized=False)
    self.target_smoothing_enabled = True
    self.lpf_tau_low = NRDR_TARGET_SMOOTH_TAU
    self.lpf_tau_standard = NRDR_TARGET_SMOOTH_TAU
    self.lpf_tau_highway = NRDR_TARGET_SMOOTH_TAU
    self.rate_ff = NRDR_RATE_FF_DEFAULT
    self.applied_scales = None   # (p, i, f) trims as applied, slewed toward the banded/scheduled ones
    self.applied_kp = None       # base kp as applied, slewed toward kpBP/kpV at this speed
    self.override_fade_up_s = NRDR_OVERRIDE_FADE_UP_S_DEFAULT
    self.since_press_s = math.inf  # time since the modified-EPS press detector last fired
    # The target before slew clip and smoothing, for offline tools scoring the shaping lag.
    self.raw_angle_steers_des = 0.0

  def reset(self):
    super().reset()
    self.pid.reset()
    self.since_press_s = math.inf

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

    # Which rack map converts curvature into a wheel angle. Only the A (position) table is
    # ever a candidate: the firmware's B table divides the RATE input on a separate path and
    # is not a position curve, which is why it is traced but not tabulated in steer_ratio.py.
    #
    # These two are not interchangeable calibrations of the same thing:
    #   road curve  absolute effective ratio, 19.680 at centre tapering 1.55x to 12.720. Fitted
    #               end to end, so it spans the VGR pinion, rack, linkage, Ackermann, compliance
    #               and tyres. It sets VM.sR itself and ignores what paramsd learned.
    #   firmware A  a relative warp only, about 1.13x across the same span, applied on top of
    #               paramsd's learned scalar (17.67 on route 00000278). It describes the VGR
    #               pinion alone, which is why it under-tapers.
    # So flipping the toggle moves the centre gain by roughly -10% AND flattens the taper; it
    # is not a pure taper swap, and the two effects partly cancel near centre.
    use_firmware_vgr = self.use_firmware_vgr and self.vgr_inverse is not None
    if self.sr_curve is not None and not use_firmware_vgr:
      # Road-measured effective ratio, solved at the DESIRED angle. Fitted from steering wheel
      # angle to achieved yaw rate, so it spans the whole chain: VGR pinion, rack, linkage,
      # Ackermann, compliance and tyres. The firmware position map covers only the first of
      # those -- 1.157x of the Clarity's measured 1.440x taper -- which is why using it alone
      # leaves the ratio too high at angle and over-commands.
      #
      # This used to select sR at the MEASURED angle, which is the hazard the vgr_inverse branch
      # below spells out and avoids: it only agrees when theta_meas == theta_des, and it closes a
      # d(theta_des)/d(theta_meas) path through the setpoint, so a measurement wobble moves the
      # target it is being compared against. Near centre the curve is flat and it cost nothing,
      # but 70-90 deg is where it is steepest -- a 1 deg wobble at 80 deg moved the target ~0.4
      # deg -- so that is where it fed the limit cycle.
      #
      # get_steer_from_curvature is linear in sR, so asking for the angle at sR = 1 and solving
      # the curve for its own fixed point costs one interpolation and removes the loop entirely.
      # controlsd refreshes VM from paramsd every frame before this runs, so no override compounds.
      sr_bp, sr_v = self.sr_curve
      VM.sR = 1.0
      unit_ratio_angle = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
      angle_steers_des_no_offset = solve_angle_from_ratio_curve(unit_ratio_angle, sr_bp, sr_v, self.sr_curve_inverse)
      # Leave the model holding the ratio at the angle actually being asked for.
      VM.sR = float(np.interp(abs(angle_steers_des_no_offset), sr_bp, sr_v))
    elif self.vgr_inverse is not None:
      # Firmware VGR path. VehicleModel keeps the scalar sR paramsd learned (controlsd sets it
      # every frame), so it returns the angle a constant-ratio rack would need; the measured rack
      # curve is then inverted to get the angle this rack actually needs. Solving at the DESIRED
      # angle is what the old path could not do: selecting sR at the MEASURED angle only agrees
      # when theta_meas == theta_des, and it lets a measurement wobble move the target
      # (a spurious d(theta_des)/d(theta_meas) term inside the loop).
      linear_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
      angle_steers_des_no_offset = vgr_linear_to_physical(linear_des_no_offset, self.vgr_inverse)
    else:
      angle_steers_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))

    # Shape the target before it becomes error, feedforward or phase, so a model curvature
    # spike cannot slam the P term or flip the turn-in/unwind branches downstream. Slew clip
    # first, then smooth: clipping removes the excursion outright, where smoothing alone would
    # still pass alpha of it (~9% of a 155 deg spike) straight into the command.
    #
    # The smoothing is the Honda torque LPF, moved off the carcontroller's OUTPUT and onto the
    # controller's INPUT. Same filter, same tau, same resulting command to the rack -- but on
    # this side of actuators.torque it is no longer invisible to controlsd, which compares
    # CC.actuators.torque against carOutput.actuatorsOutput.torque to decide steer_limited_by_
    # safety. A first-order lag holds a steady-state gap of tau * slew, so with tau = 0.1 s that
    # comparison tripped its 1e-2 threshold at any command slew above 0.1 authority/s -- under
    # 6 deg/s of angle-error change at low-speed kp, i.e. essentially the entire time the car
    # was steering -- and froze the integrator through every curve. Freezing on a lag is wrong
    # regardless: a lag converges to the command with nothing to wind up against, and the real
    # clipping cases are already handled by the anti-windup clamp inside PIDController.
    #
    # Filtering the target rather than the output is also strictly the better placement: P, the
    # feedforward, desired_angle_delta and therefore phase all see the smoothed value, so the
    # nonlinear output scales stop flapping between turn-in and unwind on alternate frames.
    # An output-side filter is applied after those scales and can only smear that chatter.
    #
    # Only while active: while disengaged both states track the raw target below, so
    # re-engagement snaps to the current command instead of slewing in from a stale value.
    self.raw_angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    if active and self.is_eps_modified:
      angle_steers_des_no_offset = rate_limit_desired_angle(
        angle_steers_des_no_offset, self.prev_rate_limited_angle, self.angle_rate_limit_deg_s, self.dt,
      )
      self.prev_rate_limited_angle = angle_steers_des_no_offset
      if self.target_smoothing_enabled:
        self.target_smooth_filter.update_alpha(
          _lat_pid_scale_banded(CS.vEgo, self.lpf_tau_low, self.lpf_tau_standard, self.lpf_tau_highway)
        )
        angle_steers_des_no_offset = float(self.target_smooth_filter.update(angle_steers_des_no_offset))
    angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    error = angle_steers_des - CS.steeringAngleDeg

    pid_log.steeringAngleDesiredDeg = angle_steers_des
    pid_log.angleError = error
    if self.eps_shadow_ff is not None:
      self._update_eps_shadow(active, angle_steers_des_no_offset, CS.vEgo, params.roll)
    self.eps_ff_weight = 0.0
    if not active:
      output_torque = 0.0
      pid_log.active = False
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self.prev_rate_limited_angle = angle_steers_des_no_offset
      self.target_smooth_filter.x = angle_steers_des_no_offset
      self.target_smooth_filter.initialized = True
      self.eps_modified_steering_pressed_filter_s = 0.0
      self.eps_modified_steering_pressed_prev = False
      self.prev_output_torque = 0.0
      self.applied_scales = None
      self.applied_kp = None
      # nrdr: PR JamesL787/openpilot#8. controlsd only resets LatControl.sat_time on disengage, so
      # the integrator carried across it (routes 277/278/27a: up to 0.32 into a fresh engagement).
      self.pid.reset()
      self.since_press_s = math.inf
      self.eps_ff_ramp = 0.0

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
        self.since_press_s = 0.0 if steering_pressed else self.since_press_s + self.dt

      freeze_threshold = 2.0 if self.is_eps_modified else 5.0
      freeze_integrator = steer_limited_by_safety or steering_pressed or CS.vEgo < freeze_threshold
      hidden_i = self.is_eps_modified and self.applied_scales is not None and self.applied_scales[1] <= 0.0
      freeze_integrator = freeze_integrator or hidden_i

      output_torque = self.pid.update(error,
                                feedforward=ff,
                                speed=CS.vEgo,
                                freeze_integrator=freeze_integrator)
      if (self.is_eps_modified and steer_limited_by_safety and not steering_pressed and
          self.since_press_s <= self.override_fade_up_s + self.dt):
        self.pid.i *= math.exp(-self.dt / NRDR_OVERRIDE_FADE_I_BLEED_TAU)

      # The Civic Bosch testing ground applies its own hardcoded center taper below; let it own the
      # output scale so the two tapers can never compound.
      civic_bosch_testing_ground = self.is_civic_bosch_modified and civic_bosch_modified_lateral_testing_ground_active()

      if self.is_eps_modified:
        if self.frame % 300 == 0:
          # Lat*Scale are user fine-trim shared by every modified-EPS Honda; the base speed
          # banding remains in kpBP/kpV in interface.py. There is no Clarity-only gate, so a
          # persisted value always has the same scope across the modified-EPS group.
          self.lat_p_scale_low = _get_param_float(self.params, "LatPScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_p_scale_standard = _get_param_float(self.params, "LatPScaleStandard", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_p_scale_highway = _get_param_float(self.params, "LatPScaleHighway", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_low = _get_param_float(self.params, "LatIScaleLowSpeed", 0.2, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_standard = _get_param_float(self.params, "LatIScaleStandard", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_i_scale_highway = _get_param_float(self.params, "LatIScaleHighway", 0.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_low = _get_param_float(self.params, "LatFScaleLowSpeed", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_standard = _get_param_float(self.params, "LatFScaleStandard", 1.0, 0.0, 5.0, scale=100.0)
          self.lat_f_scale_highway = _get_param_float(self.params, "LatFScaleHighway", 1.0, 0.0, 5.0, scale=100.0)
          try:
            self.lat_gain_schedule = parse_lat_gain_schedule(self.params.get("LatGainSchedule"))
          except Exception:
            self.lat_gain_schedule = None
          self.angle_rate_limit_deg_s = _get_param_float(self.params, "NrdrLatAngleRateLimit",
                                                         NRDR_ANGLE_RATE_LIMIT_DEG_S, 0.0, 2000.0)
          self.target_smoothing_enabled = _get_param_bool(self.params, "HondaTorqueLowPassFilter", True)
          self.lpf_tau_low = _get_param_float(self.params, "HondaLpfTauLowSpeed", NRDR_TARGET_SMOOTH_TAU, 0.0, 5.0)
          self.lpf_tau_standard = _get_param_float(self.params, "HondaLpfTauStandard", NRDR_TARGET_SMOOTH_TAU, 0.0, 5.0)
          self.lpf_tau_highway = _get_param_float(self.params, "HondaLpfTauHighway", NRDR_TARGET_SMOOTH_TAU, 0.0, 5.0)
          self.use_firmware_vgr = _get_param_bool(self.params, "NrdrLatUseFirmwareVgr")
          self.rate_ff = _get_param_float(self.params, "NrdrLatRateFF", NRDR_RATE_FF_DEFAULT, 0.0, 2.0)
          self.eps_ff_enabled = self.eps_shadow_ff is not None and _get_param_bool(self.params, "NrdrLatPidFirmwareFF")
          self.override_fade_up_s = _get_param_float(self.params, "HondaOverrideFadeUpSecs",
                                                     NRDR_OVERRIDE_FADE_UP_S_DEFAULT, 0.0, 10.0)

        p_scale = _lat_pid_scale_banded(CS.vEgo, self.lat_p_scale_low, self.lat_p_scale_standard, self.lat_p_scale_highway)
        i_scale = _lat_pid_scale_banded(CS.vEgo, self.lat_i_scale_low, self.lat_i_scale_standard, self.lat_i_scale_highway)
        f_scale = _lat_pid_scale_banded(CS.vEgo, self.lat_f_scale_low, self.lat_f_scale_standard, self.lat_f_scale_highway)
        p_scale = lat_gain_schedule_scale(self.lat_gain_schedule, "p", CS.vEgo, p_scale)
        i_scale = lat_gain_schedule_scale(self.lat_gain_schedule, "i", CS.vEgo, i_scale)
        f_scale = lat_gain_schedule_scale(self.lat_gain_schedule, "f", CS.vEgo, f_scale)
        if self.applied_scales is None:
          self.applied_scales = (p_scale, i_scale, f_scale)
        else:
          step = NRDR_TRIM_SLEW_PER_S * self.dt
          self.applied_scales = tuple(float(np.clip(want, have - step, have + step))
                                      for want, have in zip((p_scale, i_scale, f_scale), self.applied_scales, strict=True))
        p_scale, i_scale, f_scale = self.applied_scales
        if hidden_i:
          self.pid.i *= math.exp(-self.dt / NRDR_HIDDEN_I_BLEED_TAU)
        kp_target = float(self.pid.k_p)
        if self.applied_kp is None:
          self.applied_kp = kp_target
        else:
          step = NRDR_KP_SLEW_REL_PER_S * max(kp_target, self.applied_kp) * self.dt
          self.applied_kp = float(np.clip(kp_target, self.applied_kp - step, self.applied_kp + step))
        if kp_target > 0.0:
          self.pid.p *= self.applied_kp / kp_target
        if self.eps_ff_enabled and self.eps_ff_ok:
          self.eps_ff_ramp, self.eps_ff_weight = nrdr_pid_eps_ff_weight(self.eps_ff_ramp, error, angle_steers_des_no_offset,
                                                                        CS.vEgo, steering_pressed, self.dt,
                                                                        self.since_press_s)
        else:
          self.eps_ff_ramp = 0.0
        w = self.eps_ff_weight
        output_torque = self.pid.p * p_scale + self.pid.i * i_scale + self.pid.d + (1.0 - w) * self.pid.f * f_scale
        if w > 0.0:
          # as upstream: the firmware feedforward is not trimmed by LatFScale*, it replaces what they scaled
          output_torque += w * float(self.eps_shadow_ff.output)
        if self.rate_ff > 0.0:
          output_torque += (1.0 - w) * self.rate_ff * desired_angle_delta / (100.0 * self.dt)

        if not civic_bosch_testing_ground:
          output_torque *= _clarity_eps_pid_output_scale(angle_steers_des_no_offset, CS.vEgo)

      if self.is_subaru_impreza:
        raw_output_torque = self.pid.p + self.pid.i + self.pid.d + self.pid.f
        output_torque = raw_output_torque * get_subaru_impreza_pid_output_scale(error)

      output_torque = float(max(min(output_torque, self.steer_max), -self.steer_max))

      if self.is_honda_crv_5g:
        output_torque = get_honda_crv_5g_pid_output(
          output_torque, self.prev_output_torque, angle_steers_des_no_offset, CS.vEgo,
        )
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

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(output_torque)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self.prev_output_torque = float(output_torque)

    if self.eps_shadow_ff is not None:
      self.starpilot_lateral_state.epsFfWeight = float(self.eps_ff_weight)

    return output_torque, angle_steers_des, pid_log

  def _update_eps_shadow(self, active, desired_angle_no_offset, v_ego, roll):
    state = self.starpilot_lateral_state
    try:
      if not active:
        self.eps_shadow_ff.reset()
      else:
        self.eps_shadow_ff.update(float(desired_angle_no_offset), float(v_ego), float(roll))
      state.epsFfActive = bool(active)
      state.epsFfFeedforward = float(self.eps_shadow_ff.output)
      state.epsFfR5 = float(self.eps_shadow_ff.r5)
      state.epsFfLoad = float(self.eps_shadow_ff.load)
      state.epsFfDesiredRate = float(self.eps_shadow_ff.rate)
      self.eps_ff_ok = bool(active) and math.isfinite(self.eps_shadow_ff.output)
    except Exception:
      # A failure never reaches the command: the weight drops to 0 and the kf feedforward carries on.
      self.eps_ff_ok = False
      if not self.eps_shadow_failed:
        cloudlog.exception("nrdr: EPS shadow feedforward failed")
        self.eps_shadow_failed = True
      self.eps_shadow_ff.reset()
      state.epsFfActive = False
