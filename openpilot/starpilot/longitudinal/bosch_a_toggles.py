"""Owner toggles for the Bosch-A longitudinal features, read once when plannerd starts (either planner).

- BoschAStockBrakeFeel: the Stock Brake Feel law in honda_bosch_a_long (D-086 and its follow-ups).
- BoschAHumanFollowing: HumanFollowing (human_following.py) and HumanAcceleration (human_acceleration.py).

Like UseStarPilotLongitudinalPlanner, the values are latched for the life of the plannerd process, so a change
applies on the next drive. Only an exact saved "1" turns a feature on; a missing, unreadable or malformed value is
Off. A toggle only arms its feature: each one still applies its own car gate (honda_bosch_a_long.active_for,
human_following.enabled_for), so a car that is not a verified Bosch-A Honda with openpilot longitudinal is unaffected.
"""
from dataclasses import dataclass

from openpilot.starpilot.saved_source import read_saved

STOCK_BRAKE_FEEL_KEY = 'BoschAStockBrakeFeel'
HUMAN_FOLLOWING_KEY = 'BoschAHumanFollowing'
KEYS = (STOCK_BRAKE_FEEL_KEY, HUMAN_FOLLOWING_KEY)


@dataclass(frozen=True)
class BoschAToggles:
  stock_brake_feel: bool = False
  human_following: bool = False


OFF = BoschAToggles()


def _on(params, key: str) -> bool:
  try:
    raw, readable = read_saved(params, key, 8)
  except Exception:
    return False
  return bool(readable and raw == b'1')


def read_toggles(params) -> BoschAToggles:
  """The saved toggles; Off for anything but an exact b'1'."""
  return BoschAToggles(stock_brake_feel=_on(params, STOCK_BRAKE_FEEL_KEY), human_following=_on(params, HUMAN_FOLLOWING_KEY))


def vehicle_supported(CP) -> bool:
  """Settings-row gate: a Honda with a verified Bosch-A radar and openpilot longitudinal. The planners still apply their
  own gates; this only decides whether the rows can be turned on."""
  if CP is None:
    return False
  try:
    from opendbc.car.honda.bosch_a_radar import VERIFIED_BOSCH_A_CARS
    return bool(CP.brand == "honda" and CP.carFingerprint in VERIFIED_BOSCH_A_CARS and CP.openpilotLongitudinalControl)
  except Exception:
    return False
