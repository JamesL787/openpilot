"""Current Card/SD location retention with explicit synthetic wire transport."""

import pytest

from opendbc.car import gen_empty_fingerprint
from opendbc.car.chrysler.interface import CarInterface
from opendbc.car.chrysler.radar_interface import RadarInterface
from opendbc.car.chrysler.values import CAR
from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.starpilot.aol.tests import test_stock_location_family_intent as shared_cases
from openpilot.starpilot.aol.tests.stock_lateral_test_helpers import car_state, hkg_family_case


def chrysler_callers(cleanup, candidate):
  cleanup.enter_context(OpenpilotPrefix())
  saved = Params()
  saved.put_bool('AlwaysOnLateral', True, block=True)
  for key in ('LKASButtonControl', 'MainCruiseButtonControl', 'CancelButtonControl',
              'LongCancelButtonControl', 'VeryLongCancelButtonControl'):
    saved.put(key, 0, block=True)
  case = hkg_family_case('hkg_canfd', False)
  cleanup.callback(case.doCleanups)
  cp = CarInterface.get_params(candidate, gen_empty_fingerprint(), [], False, False, False)
  case.family_cp = cp.as_reader()
  case.interface_type, case.radar_type = CarInterface, RadarInterface
  sd, _, drive, card, receive = case.family_callers(False)
  state = car_state()
  state.vEgo = state.vEgoRaw = 20.0
  return sd, drive, card, receive, state


@pytest.mark.parametrize('candidate', (CAR.CHRYSLER_PACIFICA_2018, CAR.RAM_1500_5TH_GEN))
@pytest.mark.parametrize('event_first', (False, True))
def test_location_loss_retains_existing_stock_lateral_intent(monkeypatch, candidate, event_first):
  monkeypatch.setattr(shared_cases, 'stock_family_callers', chrysler_callers)
  shared_cases.test_existing_stock_hkg_location_and_nominal_pcm_off_keep_established_intent(candidate, event_first)


@pytest.mark.parametrize('candidate', (CAR.CHRYSLER_PACIFICA_2018, CAR.RAM_1500_5TH_GEN))
@pytest.mark.parametrize('fault', ('native_denial', 'native_invalid', 'panda_rx', 'relay', 'permanent_eps',
  'invalid_can', 'can_timeout', 'door', 'seatbelt', 'brake', 'regen', 'gas', 'physical_cancel', 'reverse', 'unknown_gear',
  'extra_user', 'hard_event', 'epoch', 'session', 'expired', 'future_source', 'no_baseline'))
def test_location_retention_rejects_independent_faults(monkeypatch, candidate, fault):
  monkeypatch.setattr(shared_cases, 'stock_family_callers', chrysler_callers)
  shared_cases.test_stock_location_never_retains_intent_through_independent_fault(candidate, fault)
