"""Startup choice for the Clarity angle-mode EPS build (opendbc car/honda/clarity_angle_mode.py).

HondaClarityAngleMode (Night Star / Galaxy row "Angle Mode", default on) is read once, in card's pre-create hook, before
the car interface, its controller and the first CarParams exist: steerControlType cannot change while driving, so a
change takes effect at the next car start. Unreadable setting -> the default (on).
"""
from opendbc.car.honda.clarity_angle_mode import ANGLE_MODE_PARAM, apply_angle_mode

DEFAULT = True


def requested(params) -> bool:
  try:
    value = params.get(ANGLE_MODE_PARAM, return_default=True)
  except Exception:   # unknown key (params library not rebuilt), unreadable file
    return DEFAULT
  return DEFAULT if value is None else bool(value)


def prepare(cp, params):
  return apply_angle_mode(cp, requested(params))
