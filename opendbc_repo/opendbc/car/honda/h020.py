"""Driver-override defaults for the modified TEA-H020 EPS (reports 39990-TEA,H020 on a Civic Bosch).

manager fills every unset param with its params_keys.h default at boot (and migrations seed the Honda override
fades), so "unset" never reaches carstate. Instead the H020 values are written once, the first time the car is
seen, and a flag file keeps them from being written again: after that the user's own changes stick.
"""
from pathlib import Path

from opendbc.car.honda.steer_ratio import normalize_honda_eps_fw

H020_EPS = "39990-TEA-H020"
H020_OVERRIDE_THRESHOLD = 1800  # STEER_TORQUE_SENSOR units; the stock Civic Bosch value is 1200
H020_OVERRIDE_FADE_DOWN_S = 0.0
H020_OVERRIDE_FADE_UP_S = 0.5
H020_OVERRIDE_HOLD_S = 0.5  # an override stays latched this long after the driver torque drops below the threshold

H020_DEFAULTS_FLAG = Path("/data/h020_override_defaults_v1")


def is_h020_eps(car_fw) -> bool:
  return any(fw.ecu == "eps" and b"," in bytes(fw.fwVersion) and normalize_honda_eps_fw(fw.fwVersion) == H020_EPS for fw in car_fw)


def seed_h020_override_defaults(params, flag: Path = H020_DEFAULTS_FLAG) -> bool:
  """Write the H020 override values once; True if they were written now."""
  if flag.exists():
    return False
  try:
    params.put("NrdrDriverOverrideThreshold", H020_OVERRIDE_THRESHOLD)
    params.put("HondaOverrideFadeDownSecs", H020_OVERRIDE_FADE_DOWN_S)
    params.put("HondaOverrideFadeUpSecs", H020_OVERRIDE_FADE_UP_S)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("1\n")
    return True
  except Exception:
    return False
