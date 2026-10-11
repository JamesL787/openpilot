"""Firmware-derived Honda variable-gear-ratio profiles.

The EPS firmware contains distinct position and rate VGR paths.  A traced
primary position table can be reproduced directly.  A secondary local-gain
table must instead be integrated before it can be used as a position map.
VehicleModel's ``sR`` remains the learned center ratio in either case.

Only exact EPS firmware profiles belong here.  A Honda with an unknown EPS
image deliberately has no VGR profile and keeps its normal fixed steer ratio.
"""

import math

from opendbc.car.honda.values import HondaFlags


HONDA_VGR_CLARITY_TRW_A020 = "clarity_trw_a020"
HONDA_VGR_CIVIC_TBA_C020 = "civic_tba_c020"
HONDA_VGR_INSIGHT_TXM_A040 = "insight_txm_a040"
HONDA_VGR_CRV_TLA_A040 = "crv_tla_a040"
HONDA_VGR_CIVIC_TBA_C120 = "civic_tba_c120"


# Firmware queries return the modified image with a comma in place of the
# stock image's hyphen.  Normalize that representation, but do not match a
# family prefix: the table is only safe for the exact traced image.
HONDA_VGR_PROFILE_BY_FW = {
  "39990-TRW-A020": HONDA_VGR_CLARITY_TRW_A020,
  "39990-TBA-C020": HONDA_VGR_CIVIC_TBA_C020,
  "39990-TXM-A040": HONDA_VGR_INSIGHT_TXM_A040,
  "39990-TLA-A040": HONDA_VGR_CRV_TLA_A040,
  # Same A table as the image above them, read from each image (see the tables below).
  "39990-TGG-A120": HONDA_VGR_CIVIC_TBA_C020,
  "39990-TBA-C120": HONDA_VGR_CIVIC_TBA_C120,
  "39990-TBA-A030": HONDA_VGR_CIVIC_TBA_C120,
  "39990-TEG-A010": HONDA_VGR_CIVIC_TBA_C120,
}

HONDA_VGR_PROFILE_FLAGS = {
  HONDA_VGR_CLARITY_TRW_A020: HondaFlags.VGR_CLARITY_TRW_A020,
  HONDA_VGR_CIVIC_TBA_C020: HondaFlags.VGR_CIVIC_TBA_C020,
  HONDA_VGR_INSIGHT_TXM_A040: HondaFlags.VGR_INSIGHT_TXM_A040,
  HONDA_VGR_CRV_TLA_A040: HondaFlags.VGR_CRV_TLA_A040,
  HONDA_VGR_CIVIC_TBA_C120: HondaFlags.VGR_CIVIC_TBA_C120,
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
# Checked on routes 366/369: 0x14A STEER_ANGLE_RATE = 0x18F raw rate * 2**14 / B(|raw angle|),
# with B's X in the same 0.1 deg raw units as A's (within 0.8% at every angle; not indexed by
# rate).  B Y = [16204 x4, 16205, 16229, 16284, 16368, 16481, 16783, 17825, 18866, 19421, 19445...]
# at X = [0, 40, ..., 320, 400, 600, 800, 1000, 1100...].  So the published rate is not the
# derivative of the published angle: 1.1% fast at centre, 2-5% slow at 45-100 deg.
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

# Honda CR-V 5G 39990-TLA-A040 primary angle table. The four-pointer literal block
# at 0x1E14C is [Y_A=0x11338, X_A=0x11374, Y_B=0x113B0, X_B=0x113EC]. The A pair
# feeds the position divisor; B feeds the separate rate path. These exact words
# are identical in the checksum-valid stock image and the owner's 44256c0b tune.
# See docs/honda_crv_5g_vgr_firmware.md for the content hashes and trace evidence.
_CRV_TLA_A040_POSITION_X = [0, 42, 84, 125, 167, 209, 251, 292, 335, 419,
                            636, 864, 1102, 1227, 1276, 1326, 1376, 1426, 1476, 1526,
                            1578, 1628, 1680, 1729, 2108, 2488, 2869, 3248, 3626, 5130]
_CRV_TLA_A040_POSITION_Y = [16783, 16783, 16790, 16795, 16979, 16979, 17100, 17086, 17100, 17110,
                            17300, 17597, 17964, 18170, 18247, 18322, 18378, 18460, 18521, 18566,
                            18651, 18697, 18761, 18803, 19129, 19345, 19527, 19657, 19756, 19989]


# Civic 39990-TBA-C120 primary angle table, shared byte for byte by the Civic 39990-TBA-A030 and 39990-TEG-A010
# (stock TEG and every modified build checked): Y_A at 0x1306C, X_A at 0x130A8, the same addresses as the C020's A
# pair. The TGG-A120 image carries the C020 table at those addresses instead. Decoded by vote_for_nobody (nrdr
# honda_vgr), re-read from the C120 08-11, A030 09-12, TEG stock and TEG 10-03 images.
_CIVIC_C120_POSITION_X = [0, 40, 80, 120, 160, 200, 240, 280, 320, 400,
                          600, 800, 1000, 1100, 1140, 1180, 1220, 1260, 1300, 1340,
                          1380, 1420, 1460, 1500, 1800, 2100, 2400, 2700, 3000, 9000]
_CIVIC_C120_POSITION_Y = [20972, 20972, 20480, 20644, 20644, 20808, 20644, 20644, 20644, 20644,
                          20808, 21135, 21463, 21627, 21627, 21791, 21791, 21955, 21955, 21955,
                          22118, 22118, 22282, 22282, 22446, 22610, 23101, 23429, 23593, 24740]


CLARITY_TRW_A020_VGR_LINEAR_BP, CLARITY_TRW_A020_VGR_ANGLE_BP, CLARITY_TRW_A020_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _CLARITY_POSITION_X, _CLARITY_POSITION_Y)
CIVIC_TBA_C020_VGR_LINEAR_BP, CIVIC_TBA_C020_VGR_ANGLE_BP, CIVIC_TBA_C020_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _CIVIC_C020_POSITION_X, _CIVIC_C020_POSITION_Y)
INSIGHT_TXM_A040_VGR_LINEAR_BP, INSIGHT_TXM_A040_VGR_ANGLE_BP, INSIGHT_TXM_A040_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _INSIGHT_TXM_A040_POSITION_X, _INSIGHT_TXM_A040_POSITION_Y)
CRV_TLA_A040_VGR_LINEAR_BP, CRV_TLA_A040_VGR_ANGLE_BP, CRV_TLA_A040_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _CRV_TLA_A040_POSITION_X, _CRV_TLA_A040_POSITION_Y)
CIVIC_TBA_C120_VGR_LINEAR_BP, CIVIC_TBA_C120_VGR_ANGLE_BP, CIVIC_TBA_C120_VGR_REL_LOCAL = _build_vgr_position_inverse(
  _CIVIC_C120_POSITION_X, _CIVIC_C120_POSITION_Y)


HONDA_VGR_INVERSE_BY_PROFILE = {
  HONDA_VGR_CLARITY_TRW_A020: (CLARITY_TRW_A020_VGR_LINEAR_BP, CLARITY_TRW_A020_VGR_ANGLE_BP),
  HONDA_VGR_CIVIC_TBA_C020: (CIVIC_TBA_C020_VGR_LINEAR_BP, CIVIC_TBA_C020_VGR_ANGLE_BP),
  HONDA_VGR_INSIGHT_TXM_A040: (INSIGHT_TXM_A040_VGR_LINEAR_BP, INSIGHT_TXM_A040_VGR_ANGLE_BP),
  HONDA_VGR_CRV_TLA_A040: (CRV_TLA_A040_VGR_LINEAR_BP, CRV_TLA_A040_VGR_ANGLE_BP),
  HONDA_VGR_CIVIC_TBA_C120: (CIVIC_TBA_C120_VGR_LINEAR_BP, CIVIC_TBA_C120_VGR_ANGLE_BP),
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
