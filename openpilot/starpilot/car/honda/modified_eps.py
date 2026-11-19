"""Saved settings for opendbc's modified-EPS Honda steering (opendbc/car/honda/modified_eps.py), refreshed once a second."""
import math
import time

from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS, ModifiedEpsSettings

REFRESH_NS = 1_000_000_000


def _number(params, key, fallback, lo, hi):
  try:
    value = float(params.get(key, return_default=True))
  except (TypeError, ValueError, OverflowError, RuntimeError):
    return fallback
  return min(max(value, lo), hi) if math.isfinite(value) else fallback


def _flag(params, key, fallback):
  try:
    value = params.get(key, return_default=True)
  except (TypeError, ValueError, RuntimeError):
    return fallback
  return fallback if value is None else bool(value)


def read_settings(params) -> ModifiedEpsSettings:
  d = DEFAULT_SETTINGS
  return ModifiedEpsSettings(
    override_threshold=int(_number(params, "HondaDriverOverrideThreshold", d.override_threshold, 0, 10000)),
    min_steer_speed_mph=int(_number(params, "HondaMinSteerSpeed", d.min_steer_speed_mph, 0, 45)),
    fade_down_s=_number(params, "HondaOverrideFadeDownSecs", d.fade_down_s, 0.0, 10.0),
    fade_up_s=_number(params, "HondaOverrideFadeUpSecs", d.fade_up_s, 0.0, 10.0),
    torque_scale=_number(params, "HondaOverrideTorqueScale", d.torque_scale * 100.0, 0.0, 100.0) / 100.0,
    assist_during_override=_flag(params, "HondaDriverAssistDuringOverride", d.assist_during_override),
    delta_limiter=_flag(params, "HondaSteerDeltaLimiter", d.delta_limiter),
    delta_up=_number(params, "HondaSteerDeltaUp", d.delta_up, 0.0, 100.0),
    delta_down=_number(params, "HondaSteerDeltaDown", d.delta_down, 0.0, 100.0),
    angle_cap3=_flag(params, "HondaClarityAngleCap3", d.angle_cap3),
    angle_rate_limit_deg_s=_number(params, "HondaEpsAngleRateLimit", d.angle_rate_limit_deg_s, 0.0, 2000.0),
  )


class ModifiedEpsPreferences:
  def __init__(self, params, clock=time.monotonic_ns):
    self.params = params
    self.clock = clock
    self.value = read_settings(params)
    self.read_ns = clock()

  def current(self) -> ModifiedEpsSettings:
    now = self.clock()
    if now - self.read_ns >= REFRESH_NS:
      self.value = read_settings(self.params)
      self.read_ns = now
    return self.value
