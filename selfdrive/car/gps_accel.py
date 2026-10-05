"""Road grade and longitudinal acceleration from the 10 Hz u-blox fix (gpsLocationExternal), log-only.

card.py copies these into starpilotCarState next to aEgoVsa, so one 100 Hz message carries three independent
acceleration estimates: the wheel-speed KF (carState.aEgo), the VSA accelerometer (aEgoVsa, grade included), and
GPS (aEgoGps, no grade, no wheel slip). gpsGrade turns the accelerometer into delivered acceleration:
aEgoVsaGradeCorrected = aEgoVsa - g*sin(gpsGrade). Nothing reads any of this for control.

grade = atan2(-vD, |vNE|) per fix (vD is positive downward), then low-passed: a single fix's vertical velocity is
noisy at low speed. aEgoGps is the derivative of |vNE| between fixes, low-passed. Both are invalid until enough
good fixes have arrived, after a gap, and below GPS_MIN_SPEED. Constants and evidence: STATUS 216.
"""
import math

G = 9.81
GPS_MIN_SPEED = 3.0          # m/s; below this the vNED direction (and so the grade) is mostly noise
GPS_MAX_SPEED_ACCURACY = 1.0  # m/s, u-blox speedAccuracy
GPS_MAX_GAP = 0.3            # s between fixes before the filters restart (fixes come every 0.1 s)
GPS_GRADE_TAU = 1.0          # s
GPS_ACCEL_TAU = 0.3          # s
GPS_WARMUP_FIXES = 5         # good consecutive fixes before the outputs count
GPS_STALE = 0.3              # s since the last fix message before the outputs go invalid


class GpsAccelEstimator:
  def __init__(self):
    self.reset()

  def reset(self):
    self.grade = 0.0
    self.accel = 0.0
    self.prev_t = None
    self.prev_speed = None
    self.good_fixes = 0

  def update(self, t: float, gps) -> None:
    """t: fix time in seconds (logMonoTime). gps: a gpsLocationExternal reader (or anything with its fields)."""
    if self.prev_t is not None and t <= self.prev_t:
      return
    vn, ve, vd = (list(gps.vNED) + [0.0, 0.0, 0.0])[:3]
    speed = math.hypot(vn, ve)
    good = bool(gps.hasFix) and 0.0 <= gps.speedAccuracy < GPS_MAX_SPEED_ACCURACY and speed >= GPS_MIN_SPEED and \
      all(math.isfinite(x) for x in (vn, ve, vd))
    if not good or (self.prev_t is not None and t - self.prev_t > GPS_MAX_GAP):
      self.reset()
      if not good:
        return
    grade = math.atan2(-vd, speed)
    if self.prev_t is None:
      self.grade = grade
    else:
      dt = t - self.prev_t
      a_raw = (speed - self.prev_speed) / dt
      self.grade += (grade - self.grade) * min(1.0, dt / GPS_GRADE_TAU)
      self.accel = a_raw if self.good_fixes == 1 else self.accel + (a_raw - self.accel) * min(1.0, dt / GPS_ACCEL_TAU)
    self.prev_t, self.prev_speed = t, speed
    self.good_fixes += 1

  def valid(self, age: float) -> bool:
    """age: seconds since the last gpsLocationExternal message arrived (the caller's clock)."""
    return self.good_fixes >= GPS_WARMUP_FIXES and 0.0 <= age < GPS_STALE
