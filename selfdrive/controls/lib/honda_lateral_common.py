"""Honda lateral pieces shared by LatControlPID and LatControlHondaEps: the road-measured steer-ratio curves and
their solver, the desired-angle slew limit, the torque-output LPF default and the param readers."""
import math

import numpy as np


# the Clarity's Nidec rack is variable-ratio, but paramsd learns ONE steerRatio.
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
CLARITY_SR_CURVE_BP = [0., 2.5, 7.5, 12.5, 17.5, 22.5, 27.5, 32.5, 37.5, 42.5, 47.5, 52.5, 57.5,
                            62.5, 67.5, 70., 75., 80., 85., 90., 100., 140., 200., 300., 450.]  # |wheel angle|, deg
CLARITY_SR_CURVE_V = [19.680, 19.680, 19.680, 19.680, 19.344, 19.344, 19.307, 19.151, 18.406, 18.406,
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
CIVIC_BOSCH_SR_CURVE_BP = [0., 32., 50., 75., 110., 155., 220., 300., 400.]  # |wheel angle|, deg
CIVIC_BOSCH_SR_CURVE_V = [14.960, 14.960, 14.910, 14.740, 14.210, 13.630, 13.120, 12.904, 12.774]

# CR-V 5G road-measured curve, carried over unchanged from 4f3271d6af. The A040 image also has an exact
# firmware position map (steer_ratio.py, the owner's static decode, not road-checked), but this measured
# effective-ratio curve stays the default: HondaEpsFirmwareVgr must be turned on to select the firmware map.
CRV_5G_SR_CURVE_BP = [0., 50., 100., 150., 175., 200.]  # |wheel angle|, deg
CRV_5G_SR_CURVE_V = [18.10, 17.80, 16.30, 15.30, 14.90, 14.60]

# Insight two-point road-tested profile from nrdr upstream (36e203995a).  No multi-knot
# Insight measurement has ever existed on this branch, so this is the only road data for
# the car.  The outer breakpoint is derived the same way upstream derives it -- the
# Clarity's 250 deg sample point scaled by this rack's lock angle -- rather than
# transcribed, so it stays identical to the source by construction.
CLARITY_LOCK_ANGLE = 2.41 * 180.0
INSIGHT_LOCK_ANGLE = 2.54 * 180.0
TWO_POINT_OUTER_FRACTION = 250.0 / CLARITY_LOCK_ANGLE
INSIGHT_SR_CURVE_BP = [0.0, INSIGHT_LOCK_ANGLE * TWO_POINT_OUTER_FRACTION]  # |wheel angle|, deg
INSIGHT_SR_CURVE_V = [16.82, 12.58]

# Road-measured effective-ratio curves, by fingerprint.  A car listed here uses its
# measured curve and does NOT use the firmware VGR map: the EPS position table only
# describes rack-to-steering-wheel (the VGR pinion), and misses the rack-to-roadwheel
# linkage, so on its own it under-tapers and over-commands at angle.  A car absent from
# this dict falls through to the firmware map if it has one, then to a flat CP.steerRatio.
HONDA_SR_CURVE_BY_FP = {
  "HONDA_CLARITY": (CLARITY_SR_CURVE_BP, CLARITY_SR_CURVE_V),
  "HONDA_CIVIC_BOSCH": (CIVIC_BOSCH_SR_CURVE_BP, CIVIC_BOSCH_SR_CURVE_V),
  "HONDA_CRV_5G": (CRV_5G_SR_CURVE_BP, CRV_5G_SR_CURVE_V),
  "HONDA_INSIGHT": (INSIGHT_SR_CURVE_BP, INSIGHT_SR_CURVE_V),
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


HONDA_SR_CURVE_INVERSE_BY_FP = {
  fingerprint: build_steer_ratio_inverse(*curve) for fingerprint, curve in HONDA_SR_CURVE_BY_FP.items()
}


# ceiling on how fast the DESIRED wheel angle is allowed to move, deg/s.
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
HONDA_ANGLE_RATE_LIMIT_DEG_S = 300.0  # 0 disables

# time constant for smoothing the final modified-EPS torque command, seconds.
# Speed-banded so the former carcontroller tune carries over without filtering the target.
HONDA_TORQUE_OUTPUT_LPF_TAU = 0.1

def rate_limit_desired_angle(angle_deg: float, prev_angle_deg: float, max_rate_deg_s: float, dt: float) -> float:
  if max_rate_deg_s <= 0.0 or not math.isfinite(angle_deg):
    return angle_deg
  max_delta = max_rate_deg_s * dt
  return float(min(max(angle_deg, prev_angle_deg - max_delta), prev_angle_deg + max_delta))



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
