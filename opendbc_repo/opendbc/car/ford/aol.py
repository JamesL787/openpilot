from opendbc.car import structs
from opendbc.car.ford.values import CAR, FordFlags, FordSafetyFlags

AOL_EXPERIENCE = 32
CLASSIC = frozenset((CAR.FORD_BRONCO_SPORT_MK1, CAR.FORD_ESCAPE_MK4, CAR.FORD_FOCUS_MK4,
                     CAR.FORD_MAVERICK_MK1, CAR.FORD_EXPLORER_MK6))
GENERIC_CANFD = frozenset((CAR.FORD_ESCAPE_MK4_5, CAR.FORD_EXPEDITION_MK4, CAR.FORD_F_150_MK14,
                         CAR.FORD_F_150_LIGHTNING_MK1, CAR.FORD_RANGER_MK2))
MANUAL = int(FordSafetyFlags.MANUAL)
BASE_WORDS = frozenset((8, 9, 10, 11, 12, 13, 18, 19, 32, 33, 66, 67))
ANGLE = 128
ANGLE_BASE_WORDS = frozenset((18, 19, 32, 33, 66, 67))
AOL_WORDS = (BASE_WORDS | frozenset(word | ANGLE for word in ANGLE_BASE_WORDS))
AOL_WORDS |= frozenset(word | MANUAL for word in AOL_WORDS)
from opendbc.car.ford.pinion import ENABLE, SHIFT, PROFILES, base_word, configured
AOL_WORDS |= frozenset(word | ENABLE | index << SHIFT for index, words in PROFILES.items()
                      for word in tuple(AOL_WORDS) if (word & ~MANUAL) in words)


def aol_safety_config(cp):
  if len(cp.safetyConfigs) not in (1, 2):
    return None
  if len(cp.safetyConfigs) == 2:
    passive = cp.safetyConfigs[0]
    if passive.safetyModel != structs.CarParams.SafetyModel.noOutput or passive.safetyParam != 0:
      return None
  owner = cp.safetyConfigs[-1]
  return owner if owner.safetyModel == structs.CarParams.SafetyModel.ford else None


def base_safety_param(cp):
  owner = aol_safety_config(cp)
  if owner is None:
    return -1
  manual = cp.transmissionType == structs.CarParams.TransmissionType.manual
  if cp.transmissionType not in (structs.CarParams.TransmissionType.automatic, structs.CarParams.TransmissionType.manual):
    return -1
  word = int(owner.safetyParam)
  normalized = base_word(word)
  if normalized != word and not configured(cp):
    return -1
  word = normalized
  if (word & MANUAL and not manual) or (manual and cp.alternativeExperience == AOL_EXPERIENCE and not word & MANUAL):
    return -1
  if word & ANGLE:
    if cp.alternativeExperience == 0:
      from opendbc.bluepilot_lateral.hosts.starpilot import qualified as angle_qualified
      if not angle_qualified(cp):
        return -1
      base = 18 if cp.carFingerprint == CAR.FORD_MUSTANG_MACH_E_MK1 else (66 if cp.carFingerprint in GENERIC_CANFD else 32)
      return base | int(cp.openpilotLongitudinalControl)
    if word not in AOL_WORDS:
      return -1
    word &= ~ANGLE
  return word & ~MANUAL


def qualified(cp, *, marked_only=False):
  if (cp.brand != 'ford' or cp.carFingerprint not in tuple(CAR) or cp.passive or cp.notCar or cp.dashcamOnly or
      cp.steerControlType != structs.CarParams.SteerControlType.angle or
      cp.alternativeExperience not in ((32,) if marked_only else (0, 32))):
    return False
  flags = int(cp.flags) & ~int(FordFlags.HAS_BSM)
  if cp.carFingerprint in CLASSIC and flags == 0:
    base = 32
  elif cp.carFingerprint == CAR.FORD_MUSTANG_MACH_E_MK1 and flags == int(FordFlags.CANFD):
    base = 18
  elif cp.carFingerprint in GENERIC_CANFD and flags == int(FordFlags.CANFD):
    base = 66
  elif cp.carFingerprint == CAR.FORD_EDGE_MK2 and flags == int(FordFlags.NEW_PORT | FordFlags.ALT_STEER_ANGLE):
    base = 8
  elif cp.carFingerprint == CAR.FORD_MONDEO_MK5 and flags == int(FordFlags.NEW_PORT | FordFlags.CANFD):
    base = 10
  elif cp.carFingerprint == CAR.FORD_TRANSIT_MK5 and flags == int(FordFlags.NEW_PORT | FordFlags.LKA_STEERING):
    base = 12
  else:
    return False
  safety = aol_safety_config(cp)
  return bool(cp.pcmCruise and safety is not None and
              base_safety_param(cp) == (base | int(cp.openpilotLongitudinalControl)))


def temporary_restriction(cp, state):
  gears = structs.CarState.GearShifter
  return bool(state is not None and qualified(cp, marked_only=True) and state.canValid and not state.canTimeout
              and not state.steerFaultPermanent and
              (state.gearShifter not in (gears.drive, gears.sport, gears.low) or state.steerFaultTemporary or state.vehicleSensorsInvalid))


def native_observation(native, *, latched, panda_ready, restricted, now_ns, pending_since_ns):
  lost = not panda_ready or native is None
  if not latched or lost or restricted:
    return 0, lost, False
  if native.requestedLateral and native.lateralAllowed:
    return 0, False, False
  pending_since_ns = pending_since_ns or now_ns
  return pending_since_ns, False, now_ns - pending_since_ns >= 200_000_000
