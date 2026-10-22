"""H020's own position table. Firmware evidence: Y 0x1306C, X 0x130A8 (unchanged by PTM)."""
import math
import numpy as np

PROFILE = "civic_tea_h020"
A_X = (0, 52, 103, 153, 203, 254, 305, 357, 407, 511, 771, 1046, 1334, 1482, 1542, 1602, 1661, 1722, 1782, 1844, 1904, 1965, 2025, 2086, 2540, 2997, 3451, 3907, 4363, 5731)
A_Y = (20647, 20647, 20597, 20720, 20637, 20769, 20786, 20795, 20784, 20850, 21053, 21413, 21856, 22060, 22150, 22243, 22306, 22380, 22450, 22546, 22605, 22672, 22724, 22780, 23110, 23379, 23550, 23708, 23827, 24070)


def position_inverse():
  linear, angle = [], []
  for x0, x1, y0, y1 in zip(A_X, A_X[1:], A_Y, A_Y[1:]):
    steps = max(1, math.ceil((x1 - x0) / 20))
    for step in range(steps):
      f = step / steps
      raw = x0 + (x1 - x0) * f
      divisor = y0 + (y1 - y0) * f
      linear.append(raw * 16384 / A_Y[0] / 10)
      angle.append(raw * 16384 / divisor / 10)
  linear.append(A_X[-1] * 16384 / A_Y[0] / 10)
  angle.append(A_X[-1] * 16384 / A_Y[-1] / 10)
  return tuple(linear), tuple(angle)


H020_VGR_INVERSE = position_inverse()
HONDA_VGR_INVERSE_BY_PROFILE = {PROFILE: H020_VGR_INVERSE}
HONDA_VGR_CENTRE_DIVISOR_BY_PROFILE = {PROFILE: A_Y[0]}
