"""Gentle clear-road Experimental acceleration, below all existing plan ceilings."""

import math

SOURCES = ('carState', 'carControl', 'controlsState', 'selfdriveState', 'radarState', 'modelV2')
MAX_SOURCE_AGE_NS = 250_000_000
MAX_BOOST = .3
BOOST_RATE = .05
SETTLE_SECONDS = 2.


class Encouragement:
  def __init__(self):
    self.clear_seconds = 0.
    self.boost = 0.
    self.drive_id = None
    self.last_model_ns = 0

  def update(self, sm, cp, *, now_ns, drive_id, dt, target_speed, model_accel, mpc_accel, cruise_accel,
             lateral_accel, blocked):
    eligible = False
    model_ns = 0
    try:
      car = sm['carState']
      model_ns = sm.logMonoTime['modelV2']
      fresh = all(sm.valid[name] and sm.alive[name] and
                  getattr(sm, 'freq_ok', {}).get(name, True) and
                  0 < sm.logMonoTime[name] <= now_ns and now_ns - sm.logMonoTime[name] <= MAX_SOURCE_AGE_NS
                  for name in SOURCES)
      eligible = (not blocked and fresh and cp.openpilotLongitudinalControl and
                  not cp.passive and not cp.dashcamOnly and not cp.notCar and
                  sm['selfdriveState'].experimentalMode and sm['selfdriveState'].enabled and
                  sm['carControl'].longActive and car.canValid and not car.canTimeout and
                  not car.gasPressed and not car.brakePressed and not car.standstill and
                  not sm['controlsState'].forceDecel and not sm['modelV2'].action.shouldStop and
                  not sm['radarState'].leadOne.present and not sm['radarState'].leadTwo.present and
                  not any(sm['radarState'].radarErrors.to_dict().values()) and
                  all(math.isfinite(x) for x in (dt, target_speed, model_accel, mpc_accel, cruise_accel, lateral_accel, car.vEgo)) and
                  0 < dt <= .1 and car.vEgo >= 4.5 and target_speed - car.vEgo > .2 and
                  model_accel >= 0 and abs(lateral_accel) < .5 and min(mpc_accel, cruise_accel) > model_accel)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
      eligible = False
    if type(model_ns) is not int or model_ns <= 0:
      model_ns = 0
      eligible = False
    if drive_id != self.drive_id or model_ns <= self.last_model_ns:
      eligible = False
    self.drive_id = drive_id
    self.last_model_ns = model_ns
    if not eligible:
      self.clear_seconds = self.boost = 0.
      return model_accel
    self.clear_seconds += dt
    if self.clear_seconds > SETTLE_SECONDS:
      self.boost = min(MAX_BOOST, self.boost + BOOST_RATE * dt)
    gap_scale = min(1., max(0., (target_speed - car.vEgo - .2) / 1.8))
    return min(model_accel + self.boost * gap_scale, mpc_accel, cruise_accel)
