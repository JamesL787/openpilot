"""Honda VSA yaw rate (0x94 KINEMATICS YAW_RATE) with each car's zero learned at standstill.

The DBC decodes against the nominal zero, 512 counts, but every unit sits a few counts off it (2018 Clarity 508,
2019 Civic Bosch 513) and holds that offset exactly at every stop. With the wheels stopped the true yaw rate is
zero, so the average reading there is the zero. The scale is not learnable that way and is measured per model
against GPS heading.
"""
from opendbc.car.honda.values import CAR

DBC_SCALE = 0.25   # deg/s per count, as the DBC decodes it
DBC_ZERO = 512.0   # counts

# (deg/s per count, standstill zero in counts) until this drive's own standstill replaces the zero
YAW_RATE_CALIBRATION = {
  CAR.HONDA_CLARITY: (0.25, 508.0),        # GPS 0.2494-0.2522 over 11 routes; 508.00 at every stop on 19 routes
  CAR.HONDA_CIVIC_BOSCH: (0.244, 513.0),   # GPS 0.2446 / 0.2412 on two routes; 513 at every stop
}

SETTLE_FRAMES = 50    # 0.5 s after the wheels stop before readings count
LEARN_FRAMES = 200    # 2 s of standstill readings before the zero is replaced
MAX_ZERO_OFFSET = 8.0  # counts (2 deg/s) from nominal; anything further is a fault, not a zero


class YawRateCalibration:
  def __init__(self, scale: float, zero: float):
    self.scale = scale
    self.zero = zero
    self.stopped_frames = 0
    self.total = 0.0
    self.samples = 0

  def update(self, dbc_yaw_rate_deg_s: float, standstill: bool) -> float:
    """Returns the yaw rate in deg/s, clockwise-positive like the DBC signal."""
    counts = DBC_ZERO + dbc_yaw_rate_deg_s / DBC_SCALE
    if standstill:
      self.stopped_frames += 1
      if self.stopped_frames > SETTLE_FRAMES:
        self.total += counts
        self.samples += 1
        zero = self.total / self.samples
        if self.samples >= LEARN_FRAMES and abs(zero - DBC_ZERO) <= MAX_ZERO_OFFSET:
          self.zero = zero
    else:
      self.stopped_frames, self.total, self.samples = 0, 0.0, 0
    return (counts - self.zero) * self.scale


def get_yaw_rate_calibration(car_fingerprint) -> YawRateCalibration | None:
  calibration = YAW_RATE_CALIBRATION.get(car_fingerprint)
  return YawRateCalibration(*calibration) if calibration is not None else None
