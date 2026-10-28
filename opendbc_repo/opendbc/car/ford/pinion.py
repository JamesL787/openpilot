"""Init-only pinion measurement selection adapted from BluePilot PR #145.

See CREDITS.md and THIRD_PARTY_NOTICES.md for upstream attribution and license.
The geometry is carried in the existing exact Panda safety word, not live Params.
"""
from opendbc.car.ford.values import CAR

KEY = "FordPrefSteerAngleCurvature"
ENABLE = 0x200
SHIFT = 10
MASK = 0x3E00
GEOMETRY = {
  CAR.FORD_BRONCO_SPORT_MK1: 1, CAR.FORD_ESCAPE_MK4: 2, CAR.FORD_ESCAPE_MK4_5: 3,
  CAR.FORD_EXPEDITION_MK4: 4, CAR.FORD_EXPLORER_MK6: 5, CAR.FORD_FOCUS_MK4: 6,
  CAR.FORD_F_150_LIGHTNING_MK1: 7, CAR.FORD_F_150_MK14: 8, CAR.FORD_MAVERICK_MK1: 9,
  CAR.FORD_MONDEO_MK5: 10, CAR.FORD_MUSTANG_MACH_E_MK1: 11, CAR.FORD_RANGER_MK2: 12,
}
CLASSIC = frozenset((32, 33, 128, 129, 160, 161))
GENERIC = frozenset((66, 67, 130, 131, 194, 195))
MACH_E = frozenset((18, 19, 130, 131, 146, 147))
PROFILES = {i: CLASSIC if i in (1, 2, 5, 6, 9) else MACH_E if i == 11 else frozenset((10, 11)) if i == 10 else GENERIC
            for i in range(1, 13)}


def decode(word):
  """Return (original profile, geometry), or None for malformed metadata."""
  if not word & MASK:
    return word, 0
  index = (word >> SHIFT) & 15
  base = word & ~MASK
  if not word & ENABLE or index not in PROFILES or (base & ~256) not in PROFILES[index]:
    return None
  return base, index


def base_word(word):
  result = decode(int(word))
  return result[0] if result is not None else -1


def configured(cp):
  if cp.brand != "ford" or not cp.safetyConfigs:
    return False
  result = decode(int(cp.safetyConfigs[-1].safetyParam))
  return bool(result is not None and result[1] and result[1] == GEOMETRY.get(cp.carFingerprint))


def select(cp, enabled):
  if not enabled or cp.brand != "ford" or cp.passive or cp.dashcamOnly or cp.notCar:
    return False
  from opendbc.car.ford.aol import qualified
  if not qualified(cp):
    return False
  index = GEOMETRY.get(cp.carFingerprint)
  if index is None:
    return False
  cp.safetyConfigs[-1].safetyParam |= ENABLE | index << SHIFT
  return True


class Measurement:
  """Same init-time family as native; live model correction never changes the source."""
  def __init__(self, cp):
    self.enabled = configured(cp)
    self.offset = self.roll = 0.0
    self.model = None
    if self.enabled:
      from opendbc.car.vehicle_model import VehicleModel
      self.model = VehicleModel(cp)

  def update_parameters(self, parameters):
    import math
    if self.model is None or parameters is None:
      return
    values = (parameters.angleOffsetDeg, parameters.roll, parameters.stiffnessFactor, parameters.steerRatio)
    if parameters.valid and all(math.isfinite(v) for v in values):
      self.offset, self.roll = values[:2]
      self.model.update_params(max(values[2], 0.1), max(values[3], 0.1))

  def curvature(self, state):
    if not self.enabled:
      return -state.yawRate / max(state.vEgoRaw, 0.1)
    import math
    return -self.model.calc_curvature(math.radians(state.steeringAngleDeg - self.offset), state.vEgoRaw, self.roll)
