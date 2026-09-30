"""Honda Clarity curvature delivery trim, learned from the car's own yaw sensor (0x94). Only numpy here, so
offline tools can replay exactly this code.

The rack map (clarity_rack_map) and the controller put the car on the requested curvature to within a few
percent, but what is left (tyres, load, temperature, rack wear, a map fitted on one car) is a steady ratio
between the curvature commanded and the curvature the car turns. The VSA yaw rate measures that directly:
car curvature = yaw rate / speed, ~17 ms behind the wheels and GPS-verified. This estimates that ratio per
speed and scales the requested curvature by its inverse.

Left and right are estimated separately and the correction uses their mean. From 9 m/s up the car turns
5-12% more than the map says in left turns and 2-6% less in right turns (routes 363/365/366/369): an additive
bias of ~2e-4 1/m (~0.5 deg of wheel angle), not a ratio. A single gain chases whichever way the last turn
went (+/-7% within one drive at 12 m/s); in the mean of the two sides a bias cancels and a ratio does not.
The ratio is estimated against what was commanded (requested x the applied gain), so it is a plant estimate
that the correction does not feed back into.

It is deliberately slow and only learns from steady turning:
- The requested curvature must have held within 10% for the delivery lag plus 0.25 s, and the car's within
  15% for 0.25 s. A turn-in or exit is lag, not a ratio, and must not be learned as one.
- The curvature must be at least 0.0015 1/m, so an angle offset is not mistaken for a ratio, and at least
  0.5 m/s^2 of lateral acceleration, so the 0.25 deg/s yaw count is not the error.
- Nothing is learned while the driver steers, for a second after, on hard acceleration or braking, below
  4 m/s, or from a reading more than 30% off (a sensor fault or a skid, not a ratio).
- Each estimate closes an error over TAU_S of learning time, and the correction is held within +/-8%.
Near straight the requested curvature is ~0, so the trim does nothing there and cannot steer a straight road.
"""
from collections import deque

import numpy as np

SPEED_BP = [4.0, 7.0, 12.0, 20.0, 30.0]  # m/s, learning nodes
# Lag from the curvature controlsd asks for to the curvature the car turns (tracking + wheel -> yaw), per route
# 369's delivery section; only used to line the steady windows up, so it need not be exact.
DELIVERY_LAG_V = [0.12, 0.12, 0.13, 0.14, 0.25]  # s
TAU_S = 2.0              # s of steady-turn time for an estimate to close an error
GAIN_LIMIT = 0.08        # the correction stays within 1 +/- this
MIN_SPEED = 4.0          # m/s
MIN_CURVATURE = 0.0015   # 1/m
MIN_LAT_ACCEL = 0.5      # m/s^2
MAX_ACCEL = 1.5          # m/s^2, |aEgo|
REF_STEADY = 0.10        # requested curvature spread allowed over the window, fraction of its mean
CAR_STEADY = 0.15        # car curvature spread allowed over CAR_WINDOW_S, fraction of its mean
CAR_WINDOW_S = 0.25
MAX_RATIO_ERROR = 0.30   # readings further than this from 1 are not a ratio
PRESS_HOLDOFF_S = 1.0
YAW_TAU_S = 0.10         # s, smoothing on the car curvature (0.25 deg/s counts)
RIGHT, LEFT = 0, 1       # openpilot curvature is right-positive


class YawCurvatureTrim:
  def __init__(self, dt: float):
    self.dt = dt
    self.ratios = np.ones((2, len(SPEED_BP)))  # car / commanded curvature, [right, left] x speed node
    self.yaw_alpha = dt / (YAW_TAU_S + dt)
    self.requested = deque(maxlen=int(round((max(DELIVERY_LAG_V) + CAR_WINDOW_S) / dt)) + 2)
    self.commanded = deque(maxlen=self.requested.maxlen)
    self.car = deque(maxlen=int(round(CAR_WINDOW_S / dt)))
    self.car_curvature = 0.0
    self.holdoff = PRESS_HOLDOFF_S
    self.learning = False

  def reset(self):
    """Engagement lost: forget the windows, keep what was learned."""
    self.requested.clear()
    self.commanded.clear()
    self.car.clear()
    self.holdoff = PRESS_HOLDOFF_S
    self.learning = False

  def gain(self, v_ego: float) -> float:
    ratio = float(np.interp(v_ego, SPEED_BP, self.ratios.mean(axis=0)))
    return float(np.clip(1.0 / ratio, 1.0 - GAIN_LIMIT, 1.0 + GAIN_LIMIT))

  def update(self, desired_curvature: float, yaw_rate: float, v_ego: float, a_ego: float, steering_pressed: bool) -> float:
    """desired_curvature: openpilot's (1/m, right-positive), untrimmed. yaw_rate: carState.yawRate (rad/s, left-positive).
    Returns the gain to apply to desired_curvature."""
    gain = self.gain(v_ego)
    self.car_curvature += self.yaw_alpha * (-yaw_rate / max(v_ego, 0.1) - self.car_curvature)
    self.requested.append(desired_curvature)
    self.commanded.append(desired_curvature * gain)
    self.car.append(self.car_curvature)
    self.holdoff = PRESS_HOLDOFF_S if steering_pressed else max(self.holdoff - self.dt, 0.0)

    self.learning = False
    lag_frames = int(round(float(np.interp(v_ego, SPEED_BP, DELIVERY_LAG_V)) / self.dt))
    if self._steady(v_ego, a_ego, lag_frames):
      ratio = self.car_curvature / self.commanded[-1 - lag_frames]
      if abs(ratio - 1.0) <= MAX_RATIO_ERROR:
        side = RIGHT if self.commanded[-1 - lag_frames] > 0.0 else LEFT
        self.ratios[side] += self._weights(v_ego) * (ratio - self.ratios[side]) * self.dt / TAU_S
        self.learning = True
    return gain

  @staticmethod
  def _weights(v_ego: float) -> np.ndarray:
    # linear-interpolation weights of v_ego over the nodes, so a node learns in proportion to how much it applies
    return np.array([float(np.interp(v_ego, SPEED_BP, row)) for row in np.eye(len(SPEED_BP))])

  def _steady(self, v_ego: float, a_ego: float, lag_frames: int) -> bool:
    if v_ego < MIN_SPEED or abs(a_ego) > MAX_ACCEL or self.holdoff > 0.0:
      return False
    window = lag_frames + self.car.maxlen
    if len(self.requested) < window or len(self.car) < self.car.maxlen:
      return False
    ref = np.array(self.requested)[-window:]
    mean = float(np.mean(ref))
    if abs(mean) < max(MIN_CURVATURE, MIN_LAT_ACCEL / v_ego ** 2) or np.ptp(ref) > REF_STEADY * abs(mean):
      return False
    car = np.array(self.car)
    car_mean = float(np.mean(car))
    return car_mean * mean > 0.0 and np.ptp(car) <= CAR_STEADY * abs(car_mean)
