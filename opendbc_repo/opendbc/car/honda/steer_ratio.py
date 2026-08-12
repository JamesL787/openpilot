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


# Clarity 39990-TRW-A020, B table at 0x13120/0x130E4.
_CLARITY_B_X = [0, 40, 80, 120, 160, 200, 240, 280, 320, 400, 600, 800, 1000, 1100,
                1140, 1180, 1220, 1260, 1300, 1340, 1380, 1420, 1460, 1500, 1800,
                2100, 2400, 2700, 3000, 9000]
_CLARITY_B_Y = [16204, 16204, 16204, 16204, 16205, 16229, 16284, 16368, 16481, 16783,
                17825, 18866, 19421, 19445, 19445, 19445, 19445, 19445, 19445, 19445,
                19445, 19445, 19445, 19445, 19445, 19445, 19445, 19445, 19445, 19445]

# Civic Bosch Sport 39990-TBA-C020, B table at 0x13120/0x130E4.
_CIVIC_C020_B_X = [0, 40, 80, 120, 160, 200, 240, 280, 320, 400, 600, 800, 1000, 1100,
                   1140, 1180, 1220, 1260, 1300, 1340, 1380, 1420, 1460, 1500, 1800,
                   2100, 2400, 2700, 3000, 9000]
_CIVIC_C020_B_Y = [20677, 20677, 20677, 20677, 20677, 20677, 20840, 20840, 20840, 21004,
                   21660, 22643, 23462, 23953, 24117, 24281, 24281, 24445, 24609, 24609,
                   24773, 24773, 24773, 24936, 24936, 24936, 24936, 24936, 24936, 24936]

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


# Keep the reviewed/resampled Clarity inverse map unchanged.  It is derived
# from the same B table, with extra knots through the transition to avoid the
# coarse firmware chords; this change only moves its selection from vehicle
# fingerprint to exact EPS firmware.
NRDR_CLARITY_VGR_ANGLE_BP = [0.000, 4.052, 8.104, 12.102, 16.201, 20.205,
                             24.299, 28.299, 32.296, 40.194, 50.000, 59.571,
                             68.000, 78.095, 87.000, 95.805, 104.440, 140.000,
                             200.000, 300.000, 450.000]
NRDR_CLARITY_VGR_LINEAR_BP = [0.000, 4.052, 8.104, 12.102, 16.201, 20.208,
                              24.316, 28.346, 32.397, 40.504, 50.818, 61.193,
                              70.587, 82.162, 92.605, 103.083, 113.438, 156.111,
                              228.111, 348.113, 528.115]
NRDR_CLARITY_VGR_REL_LOCAL = [1.000, 1.000, 1.000, 1.000, 1.000, 0.998,
                              0.995, 0.990, 0.983, 0.966, 0.936, 0.909,
                              0.886, 0.859, 0.847, 0.834, 0.833, 0.833,
                              0.833, 0.833, 0.833]
NRDR_CIVIC_C020_VGR_LINEAR_BP, NRDR_CIVIC_C020_VGR_ANGLE_BP, NRDR_CIVIC_C020_VGR_REL_LOCAL = _build_vgr_inverse(
  _CIVIC_C020_B_X, _CIVIC_C020_B_Y)
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
