"""Firmware-derived Honda variable-gear-ratio profiles.

The EPS firmware contains distinct position and rate VGR paths.  A traced
primary position table can be reproduced directly.  A secondary local-gain
table must instead be integrated before it can be used as a position map.
VehicleModel's ``sR`` remains the learned center ratio in either case.

Only exact EPS firmware profiles belong here.  A Honda with an unknown EPS
image deliberately has no VGR profile and keeps its normal fixed steer ratio.
"""

from dataclasses import dataclass, field
import math

from opendbc.car.honda.values import HondaFlags


HONDA_VGR_CLARITY_TRW_A020 = "clarity_trw_a020"
HONDA_VGR_CIVIC_TBA_C020 = "civic_tba_c020"
HONDA_VGR_INSIGHT_TXM_A040 = "insight_txm_a040"


# Firmware queries return the modified image with a comma in place of the
# stock image's hyphen.  Normalize that representation, but do not match a
# family prefix: the table is only safe for the exact traced image.
HONDA_VGR_PROFILE_BY_FW = {
  "39990-TRW-A020": HONDA_VGR_CLARITY_TRW_A020,
  "39990-TBA-C020": HONDA_VGR_CIVIC_TBA_C020,
  "39990-TXM-A040": HONDA_VGR_INSIGHT_TXM_A040,
}

HONDA_VGR_PROFILE_FLAGS = {
  HONDA_VGR_CLARITY_TRW_A020: HondaFlags.VGR_CLARITY_TRW_A020,
  HONDA_VGR_CIVIC_TBA_C020: HondaFlags.VGR_CIVIC_TBA_C020,
  HONDA_VGR_INSIGHT_TXM_A040: HondaFlags.VGR_INSIGHT_TXM_A040,
}


def normalize_honda_eps_fw(version) -> str:
  if isinstance(version, bytes):
    version = version.split(b"\0", 1)[0].decode("ascii", errors="ignore")
  return str(version).split("\0", 1)[0].replace(",", "-")


def get_honda_vgr_profile(car_fw):
  for fw in car_fw:
    if fw.ecu == "eps":
      profile = HONDA_VGR_PROFILE_BY_FW.get(normalize_honda_eps_fw(fw.fwVersion))
      if profile is not None:
        return profile
  return None


def _integrate_inverse_local_gain(angle_bp, local_gain):
  """Return the constant-ratio-equivalent axis for a local VGR table."""
  linear_bp = [0.0]
  for angle0, angle1, gain0, gain1 in zip(angle_bp, angle_bp[1:], local_gain, local_gain[1:], strict=False):
    delta_angle = angle1 - angle0
    if abs(gain1 - gain0) < 1e-12:
      delta_linear = delta_angle / gain0
    else:
      # Exact integral for a linearly interpolated gain.  The logarithmic form
      # avoids the bias from treating each firmware knot as a point sample.
      delta_linear = delta_angle * math.log(gain1 / gain0) / (gain1 - gain0)
    linear_bp.append(linear_bp[-1] + delta_linear)
  return linear_bp


def _build_vgr_inverse(raw_x, raw_y):
  # The traced Honda B tables use 0.05 degree raw-angle units: 9000 is 450°.
  angle_bp = [value / 20.0 for value in raw_x]
  local_gain = [raw_y[0] / value for value in raw_y]
  linear_bp = _integrate_inverse_local_gain(angle_bp, local_gain)
  return linear_bp, angle_bp, local_gain


def _build_vgr_position_inverse(raw_x, raw_y, raw_units_per_degree=10.0, max_raw_step=20):
  """Reproduce the firmware's primary angle conversion as an inverse map.

  The primary path linearly interpolates a Q14 divisor from ``abs(raw)`` and
  publishes ``raw * 2**14 / divisor``.  VehicleModel's learned center steer
  ratio already includes the divisor at zero, so ``linear_bp`` expresses the
  same raw angle using that center divisor while ``angle_bp`` is the angle the
  EPS actually publishes.

  Subdividing the firmware intervals preserves its interpolate-then-divide
  behavior; connecting only the transformed firmware knots would introduce a
  chord approximation through the curved transition.
  """
  linear_bp = []
  angle_bp = []
  relative_ratio = []
  center_divisor = raw_y[0]

  for raw0, raw1, divisor0, divisor1 in zip(raw_x, raw_x[1:], raw_y, raw_y[1:], strict=False):
    steps = max(1, math.ceil((raw1 - raw0) / max_raw_step))
    for step in range(steps):
      fraction = step / steps
      raw = raw0 + (raw1 - raw0) * fraction
      divisor = divisor0 + (divisor1 - divisor0) * fraction
      linear_bp.append(raw * (1 << 14) / center_divisor / raw_units_per_degree)
      angle_bp.append(raw * (1 << 14) / divisor / raw_units_per_degree)
      relative_ratio.append(center_divisor / divisor)

  raw = raw_x[-1]
  divisor = raw_y[-1]
  linear_bp.append(raw * (1 << 14) / center_divisor / raw_units_per_degree)
  angle_bp.append(raw * (1 << 14) / divisor / raw_units_per_degree)
  relative_ratio.append(center_divisor / divisor)
  return linear_bp, angle_bp, relative_ratio


# Clarity 39990-TRW-A020 primary angle table, X at 0x130A8 / Y at 0x1306C.
# Same layout as the C020: a four-pointer block (here at 0x1FFB0) feeding two lookups,
# A first then B.  The PC-relative loads at 0x1FE88/0x1FE8A resolve to 0x1306C/0x130A8
# (A) and those at 0x1FE98/0x1FE9A to 0x130E4/0x13120 (B), matching the C020 order where
# A divides the position and B divides the rate input.  Y[0] is exactly 16384 = 2**14,
# i.e. unity at centre, which the B table's 16204 is not.
_CLARITY_POSITION_X = [0, 40, 80, 119, 158, 198, 237, 277, 317, 398,
                       604, 820, 1047, 1164, 1210, 1257, 1305, 1352, 1398, 1447,
                       1493, 1540, 1588, 1634, 1989, 2344, 2700, 3056, 3413, 5020]
_CLARITY_POSITION_Y = [16384, 16174, 16173, 16247, 16179, 16220, 16180, 16209, 16231, 16303,
                       16506, 16812, 17177, 17352, 17411, 17473, 17538, 17600, 17644, 17705,
                       17749, 17792, 17843, 17885, 18130, 18303, 18439, 18547, 18645, 18952]

# Civic Bosch Sport 39990-TBA-C020 primary angle table, X at 0x130A8 / Y at 0x1306C.
# FUN_0001f212 loads four table pointers from 0x1F2D4: this A pair, then the B pair at
# 0x13120/0x130E4.  Only A divides the position -- `(iVar12 << 0xe) / sVar5`, where
# iVar12 is the angle from FUN_0001f444 and sVar5 is the A lookup.  B divides a
# separate input on the rate path, so it is not the position curve.
_CIVIC_C020_POSITION_X = [0, 52, 103, 153, 203, 254, 305, 357, 407, 511,
                          771, 1046, 1334, 1482, 1542, 1602, 1661, 1722, 1782, 1844,
                          1904, 1965, 2025, 2086, 2540, 2997, 3451, 3907, 4363, 5731]
_CIVIC_C020_POSITION_Y = [20647, 20647, 20597, 20720, 20637, 20769, 20786, 20795, 20784, 20850,
                          21053, 21413, 21856, 22060, 22150, 22243, 22306, 22380, 22450, 22546,
                          22605, 22672, 22724, 22780, 23110, 23379, 23550, 23708, 23827, 24070]

# Honda Insight 39990-TXM-A040 primary angle table.  The stock SH-2A image
# loads Y from 0x11338 and X from 0x11374 at 0x1e1fc/0x1e1fe, interpolates at
# 0x1e202, then divides the raw angle by that Q14 result at 0x1e216-0x1e21a.
# The adjacent 0x113B0/0x113EC pair is independently interpolated at 0x1e210
# and divides the rate input at 0x1e270-0x1e276; it is not the position curve.
_INSIGHT_TXM_A040_POSITION_X = [0, 43, 88, 130, 175, 219, 263, 306, 351, 441,
                                671, 914, 1166, 1297, 1348, 1401, 1454, 1507, 1559, 1613,
                                1664, 1718, 1771, 1823, 2217, 2610, 3005, 3402, 3798, 5515]
_INSIGHT_TXM_A040_POSITION_Y = [17613, 17613, 18022, 17886, 17971, 17981, 17988, 17964, 18022, 18084,
                                18269, 18631, 19026, 19226, 19313, 19387, 19442, 19523, 19583, 19636,
                                19692, 19745, 19798, 19839, 20113, 20317, 20474, 20593, 20702, 20989]


NRDR_CLARITY_VGR_LINEAR_BP, NRDR_CLARITY_VGR_ANGLE_BP, NRDR_CLARITY_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _CLARITY_POSITION_X, _CLARITY_POSITION_Y)
NRDR_CIVIC_C020_VGR_LINEAR_BP, NRDR_CIVIC_C020_VGR_ANGLE_BP, NRDR_CIVIC_C020_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _CIVIC_C020_POSITION_X, _CIVIC_C020_POSITION_Y)
NRDR_INSIGHT_TXM_A040_VGR_LINEAR_BP, NRDR_INSIGHT_TXM_A040_VGR_ANGLE_BP, NRDR_INSIGHT_TXM_A040_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _INSIGHT_TXM_A040_POSITION_X, _INSIGHT_TXM_A040_POSITION_Y)


HONDA_VGR_INVERSE_BY_PROFILE = {
  HONDA_VGR_CLARITY_TRW_A020: (NRDR_CLARITY_VGR_LINEAR_BP, NRDR_CLARITY_VGR_ANGLE_BP),
  HONDA_VGR_CIVIC_TBA_C020: (NRDR_CIVIC_C020_VGR_LINEAR_BP, NRDR_CIVIC_C020_VGR_ANGLE_BP),
  HONDA_VGR_INSIGHT_TXM_A040: (NRDR_INSIGHT_TXM_A040_VGR_LINEAR_BP, NRDR_INSIGHT_TXM_A040_VGR_ANGLE_BP),
}

HONDA_VGR_INVERSE_BY_FLAG = {
  int(flag): HONDA_VGR_INVERSE_BY_PROFILE[profile]
  for profile, flag in HONDA_VGR_PROFILE_FLAGS.items()
}


def get_honda_vgr_inverse(flags):
  for flag, inverse in HONDA_VGR_INVERSE_BY_FLAG.items():
    if int(flags) & flag:
      return inverse
  return None


# Profiles whose centre-equivalent coordinate has been checked against road data, and so
# are allowed to change what paramsd learns.  The Clarity's slip-corrected effective ratio
# was measured across 7 routes / 23k samples and tracks this map from 5 to 200 degrees
# (predicted 18.0/17.7/16.8 against measured 18.7/17.6/16.3 at 5-10/40-80/80-200), with a
# centre near 17.8.  The C020 and Insight maps are traced but have no such validation, so
# they keep the previous behaviour until someone drives them.
HONDA_VGR_LEARNING_FLAGS = (HondaFlags.VGR_CLARITY_TRW_A020,)


def get_honda_vgr_learning_inverse(flags):
  """VGR map to use when converting a published angle into the coordinate paramsd learns in.

  Deliberately narrower than get_honda_vgr_inverse(): returning None here only means the
  learner keeps observing the published angle, which is what every car did before.
  """
  for flag in HONDA_VGR_LEARNING_FLAGS:
    if int(flags) & int(flag):
      return HONDA_VGR_INVERSE_BY_FLAG[int(flag)]
  return None


# Two coordinates, and it matters which one a value is in:
#
#   linear    centre-equivalent steering angle.  What VehicleModel produces from a
#             curvature using a single steer ratio, and the coordinate a steer ratio
#             and an angle offset are only meaningful in.
#   physical  the angle the EPS publishes as 0x14A STEER_ANGLE, i.e. what
#             CS.steeringAngleDeg carries.  The A table maps linear -> physical.
#
# Vehicle dynamics and parameter learning belong in linear; actuator feedback and
# angle-indexed actuator maps belong in physical.

def vgr_linear_to_physical(linear_deg: float, inverse) -> float:
  """Centre-equivalent angle -> the angle the EPS will publish."""
  if inverse is None:
    return linear_deg
  linear_bp, angle_bp = inverse
  return math.copysign(float(_interp(abs(linear_deg), linear_bp, angle_bp)), linear_deg)


def vgr_physical_to_linear(physical_deg: float, inverse) -> float:
  """Published EPS angle -> centre-equivalent angle.  Inverse of the above.

  Both breakpoint arrays are monotonically increasing, so the same interpolation
  run with the axes swapped is an exact inverse at the knots.
  """
  if inverse is None:
    return physical_deg
  linear_bp, angle_bp = inverse
  return math.copysign(float(_interp(abs(physical_deg), angle_bp, linear_bp)), physical_deg)


def _interp(x, xp, fp):
  # Local so this module stays importable without numpy on the car-port side.
  if x <= xp[0]:
    return fp[0]
  if x >= xp[-1]:
    return fp[-1]
  lo, hi = 0, len(xp) - 1
  while hi - lo > 1:
    mid = (lo + hi) // 2
    if xp[mid] <= x:
      lo = mid
    else:
      hi = mid
  span = xp[hi] - xp[lo]
  if span <= 0:
    return fp[lo]
  return fp[lo] + (fp[hi] - fp[lo]) * (x - xp[lo]) / span


# The latest NRDR Clarity tune uses the exact firmware VGR map in the inner range,
# then joins it smoothly to the legacy two-breakpoint road curve.  Keeping this next
# to the VGR map avoids a second, subtly different representation of the firmware table.
FIRMWARE_LEGACY_BLEND_START_DEG = 70.0
FIRMWARE_LEGACY_BLEND_END_DEG = 90.0


def dual_bp_ratio(angle_deg: float, center_ratio: float, outer_ratio: float, outer_angle: float) -> float:
  angle_weight = min(abs(angle_deg) / outer_angle, 1.0)
  return center_ratio + (outer_ratio - center_ratio) * angle_weight


def dual_bp_desired_angle(linear_angle_deg: float, center_ratio: float,
                          outer_ratio: float, outer_angle: float) -> float:
  """Solve y = (linear / center) * dual_bp_ratio(y)."""
  magnitude = abs(linear_angle_deg)
  road_angle_factor = magnitude / center_ratio
  outer_candidate = road_angle_factor * outer_ratio
  if outer_candidate >= outer_angle:
    desired = outer_candidate
  else:
    denominator = 1.0 - road_angle_factor * (outer_ratio - center_ratio) / outer_angle
    desired = magnitude / denominator
  return math.copysign(desired, linear_angle_deg)


def _dual_bp_desired_slope(linear_angle_deg: float, center_ratio: float,
                           outer_ratio: float, outer_angle: float) -> float:
  road_angle_factor = abs(linear_angle_deg) / center_ratio
  if road_angle_factor * outer_ratio >= outer_angle:
    return outer_ratio / center_ratio
  denominator = 1.0 - road_angle_factor * (outer_ratio - center_ratio) / outer_angle
  return 1.0 / denominator ** 2


def _hermite_value(x: float, x0: float, x1: float, y0: float, y1: float,
                   slope0: float, slope1: float) -> float:
  interval = x1 - x0
  t = (x - x0) / interval
  t2 = t * t
  t3 = t2 * t
  return ((2.0 * t3 - 3.0 * t2 + 1.0) * y0
          + (t3 - 2.0 * t2 + t) * interval * slope0
          + (-2.0 * t3 + 3.0 * t2) * y1
          + (t3 - t2) * interval * slope1)


def _hermite_minimum_slope(x0: float, x1: float, y0: float, y1: float,
                           slope0: float, slope1: float) -> float:
  interval = x1 - x0
  cubic = 2.0 * y0 - 2.0 * y1 + interval * (slope0 + slope1)
  quadratic = -3.0 * y0 + 3.0 * y1 - interval * (2.0 * slope0 + slope1)
  linear = interval * slope0
  candidates = [linear, 3.0 * cubic + 2.0 * quadratic + linear]
  if abs(cubic) > 1e-12:
    vertex = -quadratic / (3.0 * cubic)
    if 0.0 < vertex < 1.0:
      candidates.append(3.0 * cubic * vertex ** 2 + 2.0 * quadratic * vertex + linear)
  return min(candidates) / interval


def _vgr_linear_to_physical_slope(linear_deg: float, inverse) -> float:
  linear_bp, angle_bp = inverse
  magnitude = abs(linear_deg)
  if magnitude <= linear_bp[0]:
    index = 0
  elif magnitude >= linear_bp[-1]:
    index = len(linear_bp) - 2
  else:
    index = next(i for i in range(len(linear_bp) - 1) if magnitude < linear_bp[i + 1])
  span = linear_bp[index + 1] - linear_bp[index]
  return (angle_bp[index + 1] - angle_bp[index]) / span if span > 0.0 else 0.0


@dataclass(frozen=True)
class FirmwareLegacySteerRatioCurve:
  """Smoothly join exact firmware VGR to the legacy dual-breakpoint curve."""
  inverse: tuple
  center_ratio: float
  outer_ratio: float
  outer_angle: float
  transition_start_linear: float = field(init=False, default=0.0)
  transition_end_linear: float = field(init=False, default=0.0)
  firmware_slope: float = field(init=False, default=0.0)
  legacy_slope: float = field(init=False, default=0.0)
  valid: bool = field(init=False, default=False)

  def __post_init__(self) -> None:
    values = (self.center_ratio, self.outer_ratio, self.outer_angle)
    if not all(math.isfinite(value) and value > 0.0 for value in values):
      return
    if self.outer_angle <= FIRMWARE_LEGACY_BLEND_END_DEG:
      return

    start_linear = abs(vgr_physical_to_linear(FIRMWARE_LEGACY_BLEND_START_DEG, self.inverse))
    end_ratio = dual_bp_ratio(FIRMWARE_LEGACY_BLEND_END_DEG, self.center_ratio,
                              self.outer_ratio, self.outer_angle)
    end_linear = self.center_ratio * FIRMWARE_LEGACY_BLEND_END_DEG / end_ratio
    firmware_slope = _vgr_linear_to_physical_slope(start_linear, self.inverse)
    legacy_slope = _dual_bp_desired_slope(end_linear, self.center_ratio,
                                          self.outer_ratio, self.outer_angle)
    derived = (start_linear, end_linear, firmware_slope, legacy_slope)
    if not all(math.isfinite(value) and value > 0.0 for value in derived) or end_linear <= start_linear:
      return

    minimum_slope = _hermite_minimum_slope(
      start_linear, end_linear,
      FIRMWARE_LEGACY_BLEND_START_DEG, FIRMWARE_LEGACY_BLEND_END_DEG,
      firmware_slope, legacy_slope,
    )
    if not math.isfinite(minimum_slope) or minimum_slope <= 0.0:
      return

    object.__setattr__(self, "transition_start_linear", start_linear)
    object.__setattr__(self, "transition_end_linear", end_linear)
    object.__setattr__(self, "firmware_slope", firmware_slope)
    object.__setattr__(self, "legacy_slope", legacy_slope)
    object.__setattr__(self, "valid", True)

  def desired_angle(self, linear_angle_deg: float) -> float:
    if not self.valid:
      return vgr_linear_to_physical(linear_angle_deg, self.inverse)

    magnitude = abs(linear_angle_deg)
    if magnitude <= self.transition_start_linear:
      return vgr_linear_to_physical(linear_angle_deg, self.inverse)
    if magnitude >= self.transition_end_linear:
      return dual_bp_desired_angle(linear_angle_deg, self.center_ratio,
                                   self.outer_ratio, self.outer_angle)

    desired = _hermite_value(
      magnitude, self.transition_start_linear, self.transition_end_linear,
      FIRMWARE_LEGACY_BLEND_START_DEG, FIRMWARE_LEGACY_BLEND_END_DEG,
      self.firmware_slope, self.legacy_slope,
    )
    return math.copysign(desired, linear_angle_deg)
