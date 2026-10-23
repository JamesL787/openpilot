from opendbc.car import structs
from opendbc.car.volkswagen.stock_aol import qualified as stock_qualified, safety_config as aol_safety_config, AOL_WORD, MANUAL_WORD, AOL_WORDS
from opendbc.car.volkswagen.long_aol import qualified as long_qualified, WORDS as LONG_WORDS
from openpilot.starpilot.aol.intent import AolCardIntent, AOL_TOGGLE, ButtonType
from openpilot.starpilot.aol.policy import AolVehiclePolicy


def qualified(cp, *, marked_only=False):
  return stock_qualified(cp, marked_only=marked_only) or long_qualified(cp, marked_only=marked_only)


def temporary_restriction(cp, state):
  gears = structs.CarState.GearShifter
  return bool(state is not None and qualified(cp, marked_only=True) and state.canValid and not state.canTimeout and
              not state.steerFaultPermanent and (state.steerFaultTemporary or state.standstill or
              state.gearShifter not in (gears.drive, gears.sport, gears.eco, gears.manumatic)))


def policy_for(cp):
  if not qualified(cp):
    return AolVehiclePolicy()
  word = AOL_WORD | (MANUAL_WORD if cp.transmissionType == structs.CarParams.TransmissionType.manual else 0)
  return AolVehiclePolicy(intent_supported=True, settings_supported=True, runtime_supported=True,
                         normal_runtime_supported=True, ordinary_axis_ack_required=qualified(cp, marked_only=True),
                         explicit_latch=True, lkas_button_supported=False, safety_param_addition=word,
                         alternative_experience_addition=32)


def native_profile_supported(model, param):
  return model == int(structs.CarParams.SafetyModel.volkswagen) and param in AOL_WORDS | LONG_WORDS


def native_accepts_cp(cp, model, param):
  return qualified(cp, marked_only=True) and native_profile_supported(model, param) and param == aol_safety_config(cp).safetyParam


def native_latch_rejected(cp, native):
  return qualified(cp, marked_only=True) and native.requestedLateral and not native.lateralAllowed


def ordinary_axis_request_allowed(cp, state):
  return qualified(cp, marked_only=True) and state.canValid and not state.canTimeout and not state.steerFaultPermanent


def retain_on_native_denial(cp, native, state):
  return temporary_restriction(cp, state)


class VolkswagenStockCardIntent(AolCardIntent):
  observe_stock_engagement = True

  def __init__(self, cp, settings):
    self.main_seen = False
    self.main_startup_pending = True
    self.main_available = False
    self.main_neutral = False
    self.main_pulse = False
    super().__init__(settings, explicit_latch=True, lkas_button_supported=False)

  def update(self, CS, **kwargs):
    state = structs.CarState(**CS.to_dict())
    events = []
    for event in CS.buttonEvents:
      if event.type == ButtonType.mainCruise and self.settings.main_action != AOL_TOGGLE:
        if event.pressed:
          self._perform(self.settings.main_action)
      else:
        events.append(structs.CarState.ButtonEvent(**event.to_dict()))
    available = bool(state.cruiseState.available)
    if (not self.settings.enabled or self.settings.main_action == AOL_TOGGLE or self.settings.lkas_action == AOL_TOGGLE or
        (state.canValid and not state.canTimeout and (state.steerFaultPermanent or state.accFaulted)) or
        any(event.type == ButtonType.cancel and event.pressed for event in CS.buttonEvents)):
      self.main_startup_pending = False
    default_main_edge = (available and (self.main_startup_pending or (self.main_neutral and not self.main_available)) and
                         self.settings.main_action != AOL_TOGGLE and self.settings.lkas_action != AOL_TOGGLE)
    if state.canValid and not state.canTimeout:
      if self.main_pulse:
        events.append(structs.CarState.ButtonEvent(type=ButtonType.mainCruise, pressed=False))
        self.main_pulse = False
      if not available:
        self.main_neutral = True
      elif self.main_seen and self.main_neutral and not self.main_available and self.settings.main_action == AOL_TOGGLE:
        events.append(structs.CarState.ButtonEvent(type=ButtonType.mainCruise, pressed=True))
        self.main_pulse = True
        self.main_neutral = False
      self.main_seen = True
      self.main_available = available
    else:
      self.main_neutral = False
      self.main_pulse = False
    state.buttonEvents = events
    super().update(state.as_reader(), **kwargs)
    if (default_main_edge and state.canValid and not state.canTimeout and self.settings.enabled and
        not state.steerFaultPermanent and not state.accFaulted and not self._fault_inhibit):
      self.allowed_latch = True
      self.main_startup_pending = False
      self.main_neutral = False
    if not available:
      if state.canValid and not state.canTimeout:
        self.main_startup_pending = False
      self.allowed_latch = False


def create_intent(cp, settings):
  return VolkswagenStockCardIntent(cp, settings)
