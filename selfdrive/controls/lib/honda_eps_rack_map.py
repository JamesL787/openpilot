"""Wheel angle <-> curvature through a rack ratio identified against the car's yaw sensor. Only numpy here, so offline
tools can use it. Each vehicle that has been identified carries a RackMapTable on its EPS firmware calibration.
"""
import math
from dataclasses import dataclass

import numpy as np

# Clarity (TRW A020): wheel angle <-> curvature, identified against the car's own yaw sensor (0x94, GPS-verified) on routes 341-36b.
# VehicleModel's form is kept, lin = R * L * [k (1 - sf v^2) - g sf roll], with lin the firmware-VGR linear
# angle of the physical wheel angle. But its single ratio (paramsd's, one value for every wheel angle)
# and its slip factor (-0.00061 from the tyre stiffness defaults) are replaced by what the car does:
# - The effective ratio R still falls with angle after the firmware table, 17.3 near centre to 16.0 at 400 deg.
#   The rack is quicker off centre than the A table says.
# - The slip factor is -0.0005: fitted from how R changes with speed within one wheel-angle band, so R's angle
#   shape can't leak into it. Left turns alone give -0.00052, right turns -0.00045.
# Each value is the mean of the left and right medians, so an angle offset cancels. Fitted on the corrected yaw
# decode (opendbc honda/yaw_rate.py). The first fit used 0.25 deg/s per count and no clockwise correction, which
# made right turns read 19.6 near centre against 16.5 for lefts and put the centre 4-5% high. Fitted on routes
# 341-35d alone the table is within 0.04 of this one, and on held-out routes 363-36b it predicts the car's
# curvature within ~1% below 16 m/s (the first fit was 1-5% short at 9-16 m/s) and 1-5% above.
# The paramsd ratio with VM's slip factor over-predicted the angle needed by 3-6% in the city, the over-steer
# through tight turns.
GRAVITY = 9.81


@dataclass(frozen=True)
class RackMapTable:
  """Effective rack ratio after the firmware angle table, by physical wheel angle, and the slip factor."""
  ratio_bp: tuple      # physical wheel angle, deg
  ratio_v: tuple
  slip_factor: float   # 1 / (m/s)^2


CLARITY_TRW_A020_RACK = RackMapTable(
  ratio_bp=(6.5, 15.0, 32.0, 57.0, 85.0, 125.0, 175.0, 230.0, 305.0, 400.0),
  ratio_v=(17.34, 17.08, 16.94, 16.78, 16.78, 16.65, 16.48, 16.37, 16.29, 16.02),
  slip_factor=-0.0005,
)

# Civic Bosch (TBA-C020): the same method (tools/lateral/fit_rack_map.py) on the C020's own VSA yaw (0x94 bus 1,
# 0.244 deg/s per count, GPS-checked) over Peter's routes 294 / 289 / 2b7 / 2c6 / 2d4 / 1b8 / 251 (34 min of turning
# at >= 3 deg). Held out one route at a time, it predicts the car's curvature within ~1% at 70 deg and up (0.99-1.01)
# and within 0.97-1.03 below; the gyro-era road curve it replaces asks for ~3.5% too much wheel past 70 deg on every
# route (measured / predicted 1.03-1.04). Slip factor fitted from the speed dependence within each band.
CIVIC_TBA_C020_RACK = RackMapTable(
  ratio_bp=(5.0, 12.5, 27.1, 53.5, 85.6, 123.4, 174.5, 226.6, 283.0),
  ratio_v=(14.93, 14.81, 14.79, 14.78, 14.70, 14.62, 14.49, 14.38, 14.27),
  slip_factor=-0.00065,
)

# Insight (TXM-A040): the same method on its VSA yaw (0x94 bus 1, 0.2428 deg/s per count + 0.157 clockwise, from
# 70k straight-to-straight GPS pairs, tools/lateral/fit_yaw_scale.py) over the owner's konik route 0000001e, split
# in halves (7 min of turning). Held out half against half it lands within ~2% (one fast small-angle cell 0.92); the
# unmeasured two-point profile it replaces is 6-10% off everywhere (0.90-0.97). Thin past 50 deg: 10-24 s per band.
INSIGHT_TXM_A040_RACK = RackMapTable(
  ratio_bp=(4.6, 13.8, 35.8, 55.1, 83.3, 122.0, 174.0, 220.7),
  ratio_v=(17.86, 17.86, 17.86, 17.40, 17.28, 17.28, 17.21, 17.17),
  slip_factor=-0.00066,
)


class HondaEpsRackMap:
  """Physical wheel angle (deg, left-positive) <-> curvature (1/m, openpilot's right-positive) for one RackMapTable."""
  def __init__(self, wheelbase: float, vgr_inverse, table: RackMapTable):
    linear_bp, angle_bp = (np.asarray(x, dtype=float) for x in vgr_inverse)
    self.wheelbase = float(wheelbase)
    self.slip_factor = table.slip_factor
    self.angle_grid = np.unique(np.r_[angle_bp, np.linspace(0.0, angle_bp[-1], 1001)])
    linear = np.radians(np.interp(self.angle_grid, angle_bp, linear_bp))
    self.path_grid = linear / np.interp(self.angle_grid, table.ratio_bp, table.ratio_v)  # = L * k at zero roll/slip
    assert np.all(np.diff(self.path_grid) > 0), "rack map must be monotonic to invert"

  def angle_from_curvature(self, curvature: float, v_ego: float, roll: float) -> float:
    k = -curvature
    path = self.wheelbase * (k * (1.0 - self.slip_factor * v_ego ** 2) - GRAVITY * self.slip_factor * roll)
    return math.copysign(float(np.interp(abs(path), self.path_grid, self.angle_grid)), path)

  def curvature_from_angle(self, angle_deg: float, v_ego: float, roll: float) -> float:
    path = math.copysign(float(np.interp(abs(angle_deg), self.angle_grid, self.path_grid)), angle_deg)
    k = (path / self.wheelbase + GRAVITY * self.slip_factor * roll) / (1.0 - self.slip_factor * v_ego ** 2)
    return -k
