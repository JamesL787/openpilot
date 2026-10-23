"""Fresh stock MQB MAIN-on startup; Dom default follows MAIN without synthetic edge/SET."""
import pytest
from opendbc.car import structs, gen_empty_fingerprint
from opendbc.car.volkswagen.interface import CarInterface
from opendbc.car.volkswagen.values import CAR
from openpilot.starpilot.aol.intent import AolSettings
from openpilot.starpilot.car.volkswagen.aol import VolkswagenStockCardIntent
from opendbc.safety.tests import test_volkswagen_stock_aol as stock_tests


@pytest.mark.parametrize('enabled', (False, True))
@pytest.mark.parametrize('main_action', (0, 9))
def test_current_valid_boot_main_default_intent_requires_no_set_or_main_cycle(enabled, main_action):
  fp = gen_empty_fingerprint()
  fp[0][0xAD] = 8
  cp = CarInterface.get_params(CAR.VOLKSWAGEN_GOLF_MK7, fp, [], False, False, False)
  owner = VolkswagenStockCardIntent(cp, AolSettings(enabled, 5., 0, main_action, (0, 0, 0), (0, 0, 0)))
  state = structs.CarState(canValid=True, vEgo=20., gearShifter=structs.CarState.GearShifter.drive)
  state.cruiseState.available = True
  for tick in range(15):
    owner.update(state, now_ns=1_000_000_000 + tick * 10_000_000)
  assert owner.allowed_latch == (enabled and main_action == 0)
  assert not state.cruiseState.enabled


@pytest.mark.parametrize('word', (8, 24))
def test_current_fresh_native_main_boot_retains_only_lateral_and_fault_does_not_rearm(word):
  owner = stock_tests.TestVolkswagenStockAol()
  try:
    owner.configure(word)
    for _ in range(12):
      owner.feed()
    owner.safety.aol_set_host_request(3)
    assert not owner.safety.get_controls_allowed()
    assert owner.safety.aol_get_permission_mask() == 1
    owner.feed(permanent=True)
    assert owner.safety.aol_get_permission_mask() == 0
    for _ in range(12):
      owner.feed()
    assert owner.safety.aol_get_permission_mask() == 0
  finally:
    owner.tearDown()


@pytest.mark.parametrize('main_action', (0, 9))
def test_startup_transport_wait_is_consumed_once_and_permanent_fault_never_rearms_held_main(main_action):
  fp = gen_empty_fingerprint()
  fp[0][0xAD] = 8
  cp = CarInterface.get_params(CAR.VOLKSWAGEN_GOLF_MK7, fp, [], False, False, False)
  owner = VolkswagenStockCardIntent(cp, AolSettings(True, 5., 0, main_action, (0, 0, 0), (0, 0, 0)))
  state = structs.CarState(canValid=True, vEgo=20., gearShifter=structs.CarState.GearShifter.drive)
  state.cruiseState.available = True
  owner.update(state, now_ns=1_000_000_000, fault_active=True)
  assert not owner.allowed_latch
  owner.update(state, now_ns=1_010_000_000, fault_active=False)
  assert owner.allowed_latch == (main_action == 0)
  assert not owner.main_startup_pending
  state.steerFaultPermanent = True
  owner.update(state, now_ns=1_020_000_000, fault_active=True)
  assert not owner.allowed_latch
  state.steerFaultPermanent = False
  owner.update(state, now_ns=1_030_000_000, fault_active=False)
  assert not owner.allowed_latch  # A held MAIN cannot undo a later disarming fault.


@pytest.mark.parametrize('word', (9, 25))
def test_debug_op_long_cold_main_grants_no_longitudinal_axis_before_native_set(word):
  from opendbc.safety.tests import test_volkswagen_long_aol as long_tests
  owner, debug = long_tests.configure(word)
  try:
    for _ in range(12):
      owner.feed()
    owner.safety.aol_set_host_request(3)
    assert not owner.safety.get_controls_allowed()
    assert owner.safety.aol_get_permission_mask() == (1 if debug else 0)
    assert not owner.safety.safety_tx_hook(owner.packet('ACC_06', {'ACC_Sollbeschleunigung_02': 0.5}))
  finally:
    owner.tearDown()


@pytest.mark.parametrize('main_action', (0, 9))
def test_missing_initial_can_fields_cannot_consume_main_boot_request(main_action):
  fp = gen_empty_fingerprint()
  fp[0][0xAD] = 8
  cp = CarInterface.get_params(CAR.VOLKSWAGEN_GOLF_MK7, fp, [], False, False, False)
  owner = VolkswagenStockCardIntent(cp, AolSettings(True, 5., 0, main_action, (0, 0, 0), (0, 0, 0)))
  # Parser defaults before cruise/EPS arrive are not qualified physical OFF/fault observations.
  state = structs.CarState(canValid=False, steerFaultPermanent=True, accFaulted=True)
  owner.update(state, now_ns=1_000_000_000, fault_active=True)
  assert not owner.allowed_latch
  assert owner.main_startup_pending == (main_action == 0)
  state.canValid = True
  state.steerFaultPermanent = False
  state.accFaulted = False
  state.vEgo = 20.
  state.gearShifter = structs.CarState.GearShifter.drive
  state.cruiseState.available = True
  owner.update(state, now_ns=1_010_000_000, fault_active=False)
  assert owner.allowed_latch == (main_action == 0)
  assert not owner.main_startup_pending
