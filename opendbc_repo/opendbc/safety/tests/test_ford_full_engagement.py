"""Physical ordinary cruise activation must arm Ford's retained native token."""

import pytest

from opendbc.car import structs
from opendbc.safety.tests.ford_release_contract import assert_release_denial
from opendbc.safety.tests.test_ford_aol import TestFordAolDriverIntent as _FordNative

WORDS = (8, 9, 10, 11, 12, 13, 18, 19, 32, 33, 66, 67)


@pytest.fixture
def ford_native():
  native = _FordNative(methodName='runTest')
  native.setUp()
  try:
    yield native
  finally:
    native.tearDown()


def select(native, word, *, ae=32):
  safety = native.safety
  debug = safety.set_safety_hooks(structs.CarParams.SafetyModel.allOutput, 0) == 0
  safety.init_tests()
  safety.set_alternative_experience(ae)
  result = safety.set_safety_hooks(structs.CarParams.SafetyModel.ford, word)
  assert result == 0
  if not debug and word in (11, 19, 67):
    assert_release_denial(native, word)
    pytest.skip('RELEASE configuration/physical RX/AOL and TX denial proved; positive vector requires DEBUG')
  native.word, native.tick = word & ~1, 0
  safety.set_aol_test_heartbeat(True)


@pytest.mark.parametrize('word', WORDS)
def test_cold_main_already_on_full_engagement_brake_reverse_temporary_and_explicit_cancel(ford_native, word):
  n = ford_native
  select(n, word)
  n.pump(40, main=3)
  assert not n.safety.get_controls_allowed()
  n.safety.aol_set_host_request(1)
  assert n.safety.aol_get_permission_mask() == 0  # Steady MAIN is not an activation.
  n.pump(10, main=4, mask=1)
  assert n.safety.get_controls_allowed()
  assert n.safety.aol_get_permission_mask() == 1
  n.rx('EngBrakeData', {'BpedDrvAppl_D_Actl': 2, 'CcStat_D_Actl': 3})
  assert not n.safety.get_controls_allowed()
  assert n.safety.aol_get_permission_mask() == 1  # Fails before the native token fix.
  n.pump(20, main=3, mask=1)
  assert not n.safety.get_controls_allowed()
  assert n.safety.aol_get_permission_mask() == 1
  n.pump(20, gear=1, mask=1)
  assert n.safety.aol_get_permission_mask() == 0
  n.pump(20, gear=3, mask=1)
  assert n.safety.aol_get_permission_mask() == 1
  n.pump(20, eps=1, mask=1)
  assert n.safety.aol_get_permission_mask() == 0
  n.pump(20, eps=0, mask=1)
  assert n.safety.aol_get_permission_mask() == 1
  n.rx('Steering_Data_FD1', {'CcAslButtnCnclPress': 1})
  assert n.safety.aol_get_permission_mask() == 0
  n.pump(20, main=3, mask=1)
  assert n.safety.aol_get_permission_mask() == 0
  n.pump(10, main=4, mask=1)  # A new successful driver engagement may arm again.
  n.rx('EngBrakeData', {'BpedDrvAppl_D_Actl': 2, 'CcStat_D_Actl': 3})
  assert not n.safety.get_controls_allowed()
  assert n.safety.aol_get_permission_mask() == 1
  assert n.safety.aol_get_permission_mask() & 2 == 0


@pytest.mark.parametrize('word', WORDS)
@pytest.mark.parametrize('veto', ('brake', 'gas', 'eps', 'reverse', 'expired-unclaimed', 'missing-health', 'ae-off'))
def test_full_engagement_never_bypasses_native_qualification(ford_native, word, veto):
  n = ford_native
  select(n, word, ae=0 if veto == 'ae-off' else 32)
  n.pump(40, main=3)
  if veto == 'missing-health':
    n.safety.set_timer(3_000_000)
  if veto == 'gas':
    n.rx('EngVehicleSpThrottle', {'ApedPos_Pc_ActlArb': 25})
  if veto == 'eps':
    n.rx('EPAS_INFO', {'EPAS_Failure': 2})
  if veto == 'reverse':
    name, signal = (
      ('TransGearData', 'GearLvrPos_D_Actl')
      if n.word == 8
      else (('Gear_Shift_by_Wire_FD1', 'TrnRng_D_RqGsm') if n.word == 10 else ('PowertrainData_10', 'TrnRng_D_Rq'))
    )
    n.rx(name, {signal: 1})
  n.rx('EngBrakeData', {'BpedDrvAppl_D_Actl': 2 if veto == 'brake' else 1, 'CcStat_D_Actl': 4})
  if veto == 'expired-unclaimed':
    n.pump(40, main=4, mask=0)
  # A physical brake drops ordinary permission. No veto can leave a retained token.
  n.rx('EngBrakeData', {'BpedDrvAppl_D_Actl': 2, 'CcStat_D_Actl': 3})
  n.safety.aol_set_host_request(1)
  assert not n.safety.get_controls_allowed()
  assert n.safety.aol_get_permission_mask() == 0


def test_full_engagement_token_dies_on_source_health_heartbeat_or_permanent_eps(ford_native):
  n = ford_native
  for fault in ('health', 'heartbeat', 'eps'):
    select(n, 32)
    n.pump(40, main=3)
    n.pump(10, main=4, mask=1)
    n.rx('EngBrakeData', {'BpedDrvAppl_D_Actl': 2, 'CcStat_D_Actl': 3})
    assert n.safety.aol_get_permission_mask() == 1
    if fault == 'health':
      n.safety.set_timer(3_000_000)
    elif fault == 'heartbeat':
      n.safety.set_aol_test_heartbeat(False)
    else:
      n.rx('EPAS_INFO', {'EPAS_Failure': 2})
    assert n.safety.aol_get_permission_mask() == 0
    n.pump(30, main=3, mask=1)
    assert n.safety.aol_get_permission_mask() == 0
