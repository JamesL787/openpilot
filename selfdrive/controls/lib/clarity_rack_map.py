"""Honda Clarity (TRW A020 EPS) wheel angle <-> curvature map. Only numpy here, so offline tools can use it."""
import math

import numpy as np

# Wheel angle <-> curvature, identified against the car's own yaw sensor (0x94, GPS-verified) on routes 341-36b.
# VehicleModel's form is kept, lin = R * L * [k (1 - sf v^2) - g sf roll], with lin the firmware-VGR linear
# angle of the physical wheel angle. But its single ratio (paramsd, learned from a comma gyro that reads 3% low)
# and its slip factor (-0.00061 from the tyre stiffness defaults) are replaced by what the car does:
# - The effective ratio R still falls with angle after the firmware table, 18.2 near centre to 15.8 at 400 deg.
#   The rack is quicker off centre than the A table says.
# - The slip factor is -0.0005.
# Each value is the median of left and right turns, so an angle offset cancels. Against the yaw sensor this map
# predicts car curvature from wheel angle within 0.7% at 20-500 deg below 15 m/s and within 3.7% everywhere.
# The paramsd ratio with VM's slip factor over-predicted the angle needed by 3-6% in the city, the over-steer
# through tight turns.
CLARITY_RATIO_BP = [6.5, 15.0, 32.0, 57.0, 85.0, 125.0, 175.0, 230.0, 305.0, 400.0]  # physical wheel angle, deg
CLARITY_RATIO_V = [18.21, 17.63, 17.12, 16.77, 16.69, 16.52, 16.31, 16.19, 16.10, 15.83]
CLARITY_SLIP_FACTOR = -0.0005  # 1 / (m/s)^2
GRAVITY = 9.81


class ClarityRackMap:
  """Physical wheel angle (deg, left-positive) <-> curvature (1/m, openpilot's right-positive), see CLARITY_RATIO_*."""
  def __init__(self, wheelbase: float, vgr_inverse):
    linear_bp, angle_bp = (np.asarray(x, dtype=float) for x in vgr_inverse)
    self.wheelbase = float(wheelbase)
    self.angle_grid = np.unique(np.r_[angle_bp, np.linspace(0.0, angle_bp[-1], 1001)])
    linear = np.radians(np.interp(self.angle_grid, angle_bp, linear_bp))
    self.path_grid = linear / np.interp(self.angle_grid, CLARITY_RATIO_BP, CLARITY_RATIO_V)  # = L * k at zero roll/slip
    assert np.all(np.diff(self.path_grid) > 0), "rack map must be monotonic to invert"

  def angle_from_curvature(self, curvature: float, v_ego: float, roll: float) -> float:
    k = -curvature
    path = self.wheelbase * (k * (1.0 - CLARITY_SLIP_FACTOR * v_ego ** 2) - GRAVITY * CLARITY_SLIP_FACTOR * roll)
    return math.copysign(float(np.interp(abs(path), self.path_grid, self.angle_grid)), path)

  def curvature_from_angle(self, angle_deg: float, v_ego: float, roll: float) -> float:
    path = math.copysign(float(np.interp(abs(angle_deg), self.angle_grid, self.path_grid)), angle_deg)
    k = (path / self.wheelbase + GRAVITY * CLARITY_SLIP_FACTOR * roll) / (1.0 - CLARITY_SLIP_FACTOR * v_ego ** 2)
    return -k
