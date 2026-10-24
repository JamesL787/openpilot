"""Subaru stock ACC retains independent lateral intent after full engagement."""
from opendbc.car import structs
from opendbc.car.subaru.stock_aol import qualified, temporary_restriction
from openpilot.starpilot.aol.intent import AolCardIntent
from openpilot.starpilot.aol.policy import AolVehiclePolicy


class SubaruStockCardIntent(AolCardIntent):
  observe_stock_engagement = True

  def __init__(self, settings):
    super().__init__(settings, explicit_latch=True, lkas_button_supported=False)

  def update(self, CS, **kwargs):
    super().update(CS, **kwargs)
    if not CS.cruiseState.available:
      self._record_latch_clear('subaru_main_off')
      self.allowed_latch = False
      self._withdraw_full_engagement()


def policy_for(cp):
  admitted = qualified(cp)
  return AolVehiclePolicy(intent_supported=admitted, settings_supported=admitted, runtime_supported=admitted,
                          normal_runtime_supported=admitted, full_axis_runtime_required=qualified(cp, marked_only=True),
                          ordinary_axis_ack_required=qualified(cp, marked_only=True), explicit_latch=admitted,
                          fixed_cruise_buttons=admitted, lkas_button_supported=False,
                          alternative_experience_addition=32 if admitted else 0)


def native_profile_supported(model, param):
  return model == int(structs.CarParams.SafetyModel.subaru) and param in (0, 1, 8, 16, 17, 145, 177, 209, 401, 465, 512, 520, 1169, 1425, 2225)


def native_accepts_cp(cp, model, param):
  return qualified(cp, marked_only=True) and native_profile_supported(model, param)


def native_latch_rejected(cp, native):
  return qualified(cp, marked_only=True) and native.requestedLateral and not native.lateralAllowed


def retain_on_native_denial(cp, native, state):
  return temporary_restriction(cp, state)


def ordinary_axis_request_allowed(cp, state):
  return (qualified(cp, marked_only=True) and state.canValid and not state.canTimeout and
          not state.steerFaultPermanent and not state.accFaulted)


def create_intent(cp, settings):
  return SubaruStockCardIntent(settings)


def sng_standstill_lateral_inhibit(cp, state):
  # Native still requires movement. Withdraw the request before its expected denial,
  # preserving ordinary stock ACC without granting either active axis.
  return bool(qualified(cp, marked_only=True) and cp.safetyConfigs[0].safetyParam in (8, 520) and state.standstill)
