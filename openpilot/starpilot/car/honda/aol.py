from opendbc.car.structs import car
from opendbc.car.honda.stock_aol import qualified as qualified_stock, BOSCH_WORDS, NIDEC_WORDS, temporary_restriction
from openpilot.starpilot.car.honda.stock_intent import HondaStockCardIntent
from opendbc.car.honda.nidec_interceptor import qualified as interceptor_qualified
from opendbc.car.honda.values import CAR, HondaFlags, HondaSafetyFlags
from openpilot.starpilot.aol.policy import AolVehiclePolicy


CLASSIC_BOSCH_AOL_CARS = frozenset((
  CAR.HONDA_NBOX_2G, CAR.HONDA_ACCORD, CAR.HONDA_CIVIC_BOSCH, CAR.HONDA_CIVIC_BOSCH_DIESEL,
  CAR.HONDA_CRV_5G, CAR.HONDA_CRV_HYBRID, CAR.ACURA_RDX_3G, CAR.HONDA_INSIGHT,
  CAR.HONDA_E, CAR.HONDA_E_ADVANCE,
))
_CLASSIC_BOSCH_AOL_IDS = frozenset(str(candidate) for candidate in CLASSIC_BOSCH_AOL_CARS)
_NON_CLASSIC_BOSCH_FLAGS = HondaFlags.BOSCH_RADARLESS | HondaFlags.BOSCH_CANFD | HondaFlags.BOSCH_ALT_RADAR
_AOL_SAFETY_PARAMS = frozenset((
  int(HondaSafetyFlags.BOSCH_LONG),
  int(HondaSafetyFlags.BOSCH_LONG | HondaSafetyFlags.ALT_BRAKE),
  int(HondaSafetyFlags.BOSCH_LONG | HondaSafetyFlags.AOL_BOSCH_LONG),
  int(HondaSafetyFlags.BOSCH_LONG | HondaSafetyFlags.ALT_BRAKE | HondaSafetyFlags.AOL_BOSCH_LONG),
))


# Nidec with a gas interceptor (openpilot longitudinal, no PCM cruise). Only the Clarity has driven it; the panda accepts
# exactly GAS_INTERCEPTOR | AOL_NIDEC_INTERCEPTOR on a SCM_FEEDBACK (not NIDEC_ALT) Nidec.
NIDEC_INTERCEPTOR_AOL_CARS = frozenset((CAR.HONDA_CLARITY,))
_NIDEC_INTERCEPTOR_WORD = int(HondaSafetyFlags.GAS_INTERCEPTOR)
_NIDEC_INTERCEPTOR_AOL_WORD = _NIDEC_INTERCEPTOR_WORD | int(HondaSafetyFlags.AOL_NIDEC_INTERCEPTOR)


def qualified_nidec_interceptor(CP) -> bool:
  return (CP.carFingerprint in NIDEC_INTERCEPTOR_AOL_CARS and bool(interceptor_qualified(CP)) and
          not bool(CP.flags & HondaFlags.NIDEC_ALT_SCM_MESSAGES) and len(CP.safetyConfigs) == 1 and
          int(CP.safetyConfigs[0].safetyParam) in (_NIDEC_INTERCEPTOR_WORD, _NIDEC_INTERCEPTOR_AOL_WORD))


def qualified_honda(CP) -> bool:
  rdx = CP.carFingerprint == CAR.ACURA_RDX_3G
  word = int(CP.safetyConfigs[0].safetyParam) if len(CP.safetyConfigs) == 1 else -1
  return (word in ((131, 163) if rdx else _AOL_SAFETY_PARAMS) and
          str(CP.carFingerprint) in _CLASSIC_BOSCH_AOL_IDS and
          CP.brand == 'honda' and bool(CP.flags & HondaFlags.BOSCH) and
          not bool(CP.flags & _NON_CLASSIC_BOSCH_FLAGS) and
          bool(CP.openpilotLongitudinalControl) and not bool(CP.pcmCruise) and
          not bool(CP.notCar) and not bool(CP.passive) and not bool(CP.dashcamOnly) and
          len(CP.safetyConfigs) == 1 and
          CP.safetyConfigs[0].safetyModel == car.CarParams.SafetyModel.hondaBosch and
          int(CP.safetyConfigs[0].safetyParam) in (_AOL_SAFETY_PARAMS | {131, 163}))


def policy_for(CP) -> AolVehiclePolicy:
  if qualified_stock(CP):
    return AolVehiclePolicy(intent_supported=True, settings_supported=True, runtime_supported=True,
                            normal_runtime_supported=True, ordinary_axis_ack_required=qualified_stock(CP, marked_only=True), explicit_latch=True,
                            alternative_experience_addition=32,
                            safety_param_addition=256 if CP.carFingerprint == CAR.HONDA_ODYSSEY_TWN else 0)
  if qualified_nidec_interceptor(CP):
    # runs normally (not only in replay): the panda grants lateral on main + host request, long only after SET/RES
    return AolVehiclePolicy(intent_supported=True, settings_supported=True,
                            runtime_supported=int(CP.safetyConfigs[0].safetyParam) == _NIDEC_INTERCEPTOR_AOL_WORD,
                            normal_runtime_supported=True,
                            safety_param_addition=int(HondaSafetyFlags.AOL_NIDEC_INTERCEPTOR))
  qualified = qualified_honda(CP)
  return AolVehiclePolicy(
    intent_supported=qualified, settings_supported=qualified,
    runtime_supported=qualified and bool(int(CP.safetyConfigs[0].safetyParam) & 0x20),
    distance_personality=qualified,
    safety_param_addition=0x20 if qualified else 0,
  )


def native_profile_supported(model: int, param: int) -> bool:
  return ((model == int(car.CarParams.SafetyModel.hondaBosch) and param in BOSCH_WORDS | {34, 35, 163}) or
          (model == int(car.CarParams.SafetyModel.hondaNidec) and param in NIDEC_WORDS | {_NIDEC_INTERCEPTOR_AOL_WORD}))


def native_accepts_cp(CP, model: int, param: int) -> bool:
  # Honda's native receipt checks the safety profile, then the shared exact CP match.
  if qualified_stock(CP, marked_only=True):
    return native_profile_supported(model, param) and param == CP.safetyConfigs[0].safetyParam
  if qualified_nidec_interceptor(CP):
    return param == CP.safetyConfigs[0].safetyParam == _NIDEC_INTERCEPTOR_AOL_WORD
  return qualified_honda(CP) and param == CP.safetyConfigs[0].safetyParam and param in (34, 35, 163)


def native_latch_rejected(CP, native):
  return qualified_stock(CP, marked_only=True) and native.requestedLateral and not native.lateralAllowed


def ordinary_axis_request_allowed(CP, CS):
  return qualified_stock(CP, marked_only=True) and CS.canValid and not CS.canTimeout and not CS.steerFaultPermanent


def retain_on_native_denial(CP, native, state):
  return temporary_restriction(CP, state)


def create_intent(CP, settings):
  if qualified_stock(CP):
    return HondaStockCardIntent(CP, settings)
  from openpilot.starpilot.aol.intent import AolCardIntent
  return AolCardIntent(settings)
