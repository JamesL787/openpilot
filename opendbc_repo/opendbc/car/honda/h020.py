"""Driver-override defaults for the modified TEA-H020 EPS (reports 39990-TEA,H020 on a Civic Bosch).

They apply only while the user has not set the matching param, so a wiped params directory still gets them.
"""
from opendbc.car.honda.steer_ratio import normalize_honda_eps_fw

H020_EPS = "39990-TEA-H020"
H020_OVERRIDE_THRESHOLD = 1800  # STEER_TORQUE_SENSOR units; the stock Civic Bosch value is 1200
H020_OVERRIDE_FADE_DOWN_S = 0.0
H020_OVERRIDE_FADE_UP_S = 0.5
H020_OVERRIDE_HOLD_S = 0.5  # an override stays latched this long after the driver torque drops below the threshold


def is_h020_eps(car_fw) -> bool:
  return any(fw.ecu == "eps" and b"," in bytes(fw.fwVersion) and normalize_honda_eps_fw(fw.fwVersion) == H020_EPS for fw in car_fw)


def param_or_default(params, key, default):
  """The param's float value, or `default` while it is unset or unreadable."""
  try:
    value = params.get(key)
    if value is None:
      return default
    return float(value.decode("utf-8") if isinstance(value, bytes) else value)
  except Exception:
    return default
