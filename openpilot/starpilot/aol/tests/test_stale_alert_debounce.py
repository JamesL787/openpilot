"""The red commIssue alert waits for 100 ms of stale carState; commands still go at 30 ms.

Route 0000003c--8a8cfed3f7 segment 9: one 28 ms pandad gap aged carState past the
30 ms intent bound and sounded commIssue/softDisable for a single frame.
"""
from contextlib import ExitStack
from unittest import mock

import pytest

from openpilot.cereal import log
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.selfdrived import selfdrived
from openpilot.starpilot.aol.tests import test_ioniq_availability as fixture
from openpilot.starpilot.aol.tests.test_input_deadline_continuity import BASE
from openpilot.starpilot.aol.tests.test_ordinary_source_availability import settings

COMM_ISSUE = log.OnroadEvent.EventName.commIssue
STATE = log.SelfdriveState.OpenpilotState


def expire(mode, offset_ns):
  case = fixture.IoniqAvailabilityTests(methodName='runTest')
  cleanup = ExitStack()
  cleanup.callback(case.doCleanups)
  cleanup.enter_context(OpenpilotPrefix())
  cleanup.enter_context(mock.patch.object(selfdrived, 'AOL_STALE_ALERT_NS', 100_000_000))
  sd, controls, drive, _, _ = case._ioniq_availability_callers(full_op=True)
  drive(2, state_stamp=BASE, offset_ns=4_497_535, **settings(mode, BASE, 3))
  axis, state, command = drive(5, timeout=True, state_stamp=BASE, offset_ns=offset_ns, **settings(mode, BASE, 3))
  return cleanup, sd, drive, axis, state, command


@pytest.mark.parametrize('mode', ['long_only', 'combined', 'combined_unarmed'])
def test_short_stale_gap_withdraws_commands_without_alert(mode):
  cleanup, sd, drive, axis, state, command = expire(mode, 5_399_000)  # carState 35 ms old
  with cleanup:
    assert not axis.lateralActive and not axis.longitudinalActive
    assert not command.latActive and not command.longActive
    assert COMM_ISSUE not in sd.events.names
    assert state.enabled and state.state == STATE.enabled and state.alertType == ''
    assert sd.aol_stale_alert_deferred and sd.aol_fault_reason == 'availabilityPause'
    fresh = BASE + 40_000_000
    recovered, recovered_state, recovered_command = drive(6, state_stamp=fresh, **settings(mode, fresh, 4))
    assert recovered.longitudinalActive and recovered_command.longActive
    assert recovered_state.enabled and recovered_state.state == STATE.enabled
    assert not sd.aol_stale_alert_deferred


@pytest.mark.parametrize('mode', ['long_only', 'combined', 'combined_unarmed'])
def test_stale_gap_past_100ms_still_sounds_soft_disable(mode):
  cleanup, sd, _, axis, state, command = expire(mode, 75_399_000)  # carState 105 ms old
  with cleanup:
    assert not axis.longitudinalActive and not command.longActive
    assert COMM_ISSUE in sd.events.names
    assert state.state == STATE.softDisabling and state.alertType == 'commIssue/softDisable'
    assert not sd.aol_stale_alert_deferred


@pytest.mark.parametrize('age_ns, due', [(0, True), (29_000_000, False), (99_999_999, False), (100_000_000, True), (150_000_000, True)])
def test_alert_due_boundary(age_ns, due):
  sd = selfdrived.SelfdriveD.__new__(selfdrived.SelfdriveD)
  now = BASE + 200_000_000
  intent = mock.Mock(carStateLogMonoTime=now - age_ns if age_ns else 0)
  with mock.patch.object(selfdrived, 'AOL_STALE_ALERT_NS', 100_000_000):
    assert sd.aol_stale_alert_due(intent, now) == due
    assert sd.aol_stale_alert_due(None, now)


# Route 0000008e--55bbb6ccb6 segment 13 (13.9 min): one carState 29 ms after the
# last, gas pressed. Ordinary retention declines under gas, so expiry fell to the
# armed-LAT availability branch, which raised commIssue/softDisable with
# faultReason availabilityPause and disengaged. The age at the check is the gap
# plus publication latency, so ages of 35 ms and 65 ms are tested.
GAS_STALE_MODES = ['combined', 'lateral_only']
AGE_35_MS, AGE_65_MS, AGE_105_MS = 5_399_000, 35_399_000, 75_399_000  # offsets at tick 5


def expire_declined(mode, offset_ns, *, gas, retention):
  case = fixture.IoniqAvailabilityTests(methodName='runTest')
  cleanup = ExitStack()
  cleanup.callback(case.doCleanups)
  cleanup.enter_context(OpenpilotPrefix())
  cleanup.enter_context(mock.patch.object(selfdrived, 'AOL_STALE_ALERT_NS', 100_000_000))
  sd, controls, drive, _, _ = case._ioniq_availability_callers(full_op=True)
  drive(2, state_stamp=BASE, offset_ns=4_497_535, gas=gas, **settings(mode, BASE, 3))
  if not retention:
    cleanup.enter_context(mock.patch.object(sd, 'retain_ordinary_source_state', return_value=False))
  axis, state, command = drive(5, timeout=True, gas=gas, state_stamp=BASE, offset_ns=offset_ns, **settings(mode, BASE, 3))
  return cleanup, sd, drive, axis, state, command


@pytest.mark.parametrize('gas, retention', [(True, True), (False, False)], ids=['gas_held', 'retention_declined'])
@pytest.mark.parametrize('offset_ns', [AGE_35_MS, AGE_65_MS], ids=['35ms', '65ms'])
@pytest.mark.parametrize('mode', GAS_STALE_MODES)
def test_single_late_frame_on_availability_path_holds_without_alert(mode, offset_ns, gas, retention):
  cleanup, sd, drive, axis, state, command = expire_declined(mode, offset_ns, gas=gas, retention=retention)
  with cleanup:
    assert axis.sourceCarStateMonoTime == 0  # the source really expired
    assert not axis.lateralActive and not axis.longitudinalActive
    assert not command.latActive and not command.longActive
    assert COMM_ISSUE not in sd.events.names
    assert not sd.events.contains(selfdrived.ET.SOFT_DISABLE) and not sd.events.contains(selfdrived.ET.IMMEDIATE_DISABLE)
    assert state.enabled and state.state in (STATE.enabled, STATE.overriding)
    assert 'commIssue' not in state.alertType and 'controlsMismatch' not in state.alertType
    assert sd.aol_stale_alert_deferred and sd.aol_fault_reason == 'availabilityPause'
    assert not getattr(sd, 'aol_availability_long_inhibit', False) and not sd.aol_authority_lost
    fresh = BASE + 40_000_000
    recovered, recovered_state, recovered_command = drive(6, gas=gas, state_stamp=fresh, **settings(mode, fresh, 4))
    assert recovered.lateralActive and recovered_command.latActive
    assert recovered_state.enabled and COMM_ISSUE not in sd.events.names
    assert not sd.aol_stale_alert_deferred and sd.aol_fault_reason == 'none'


@pytest.mark.parametrize('gas, retention', [(True, True), (False, False)], ids=['gas_held', 'retention_declined'])
@pytest.mark.parametrize('mode', GAS_STALE_MODES)
def test_stale_past_100ms_on_availability_path_still_alerts(mode, gas, retention):
  cleanup, sd, _, axis, state, command = expire_declined(mode, AGE_105_MS, gas=gas, retention=retention)
  with cleanup:
    assert not axis.lateralActive and not axis.longitudinalActive
    assert not command.latActive and not command.longActive
    assert COMM_ISSUE in sd.events.names
    assert not state.enabled and state.alertType == 'commIssue/softDisable'
    assert not sd.aol_stale_alert_deferred and sd.aol_fault_reason == 'availabilityPause'


@pytest.mark.parametrize('mode', GAS_STALE_MODES)
def test_stall_growing_past_100ms_alerts_once_due(mode):
  cleanup, sd, drive, _, state, _ = expire_declined(mode, AGE_35_MS, gas=True, retention=True)
  with cleanup:
    assert COMM_ISSUE not in sd.events.names and state.enabled
    _, state, _ = drive(6, timeout=True, gas=True, state_stamp=BASE, offset_ns=AGE_65_MS - 10_000_000,
                        **settings(mode, BASE, 3))  # 65 ms old
    assert COMM_ISSUE not in sd.events.names and state.enabled and 'commIssue' not in state.alertType
    axis, state, command = drive(7, timeout=True, gas=True, state_stamp=BASE, offset_ns=AGE_105_MS - 20_000_000,
                                 **settings(mode, BASE, 3))  # 105 ms old
    assert not axis.lateralActive and not command.latActive
    assert COMM_ISSUE in sd.events.names and state.alertType == 'commIssue/softDisable'
    assert not state.enabled and not sd.aol_stale_alert_deferred


def test_source_alert_due_matches_intent_alert_due():
  now = BASE + 200_000_000
  with mock.patch.object(selfdrived, 'AOL_STALE_ALERT_NS', 100_000_000):
    for age_ns in (29_000_000, 99_999_999, 100_000_000):
      assert (selfdrived.SelfdriveD.aol_stale_source_alert_due(now - age_ns, now) ==
              selfdrived.SelfdriveD.__new__(selfdrived.SelfdriveD).aol_stale_alert_due(
                mock.Mock(carStateLogMonoTime=now - age_ns), now))
    assert selfdrived.SelfdriveD.aol_stale_source_alert_due(0, now)
    assert selfdrived.SelfdriveD.aol_stale_source_alert_due(now + 1, now)


# long_only and combined_unarmed with the gas held: ordinary retention declines
# under gas and there is no armed-LAT availability, so the late frame reached
# step()'s lost_companion -> aol_authority_lost -> controlsMismatch/immediateDisable.
GAS_LONG_MODES = ['long_only', 'combined_unarmed']
CONTROLS_MISMATCH = log.OnroadEvent.EventName.controlsMismatch


def tick_offset(tick, age_ns):
  """Offset giving carState age_ns at drive(tick); tick 5 + 5_399_000 is 35 ms, each tick adds 10 ms."""
  return age_ns - 29_601_000 - (tick - 5) * 10_000_000


@pytest.mark.parametrize('offset_ns', [AGE_35_MS, AGE_65_MS], ids=['35ms', '65ms'])
@pytest.mark.parametrize('mode', GAS_LONG_MODES)
def test_gas_held_single_late_frame_long_modes_no_controls_mismatch(mode, offset_ns):
  cleanup, sd, drive, axis, state, command = expire_declined(mode, offset_ns, gas=True, retention=True)
  with cleanup:
    assert axis.sourceCarStateMonoTime == 0  # the source really expired
    assert not axis.lateralActive and not axis.longitudinalActive
    assert not command.latActive and not command.longActive
    assert CONTROLS_MISMATCH not in sd.events.names and COMM_ISSUE not in sd.events.names
    assert not sd.events.contains(selfdrived.ET.SOFT_DISABLE) and not sd.events.contains(selfdrived.ET.IMMEDIATE_DISABLE)
    assert not sd.aol_authority_lost
    assert state.enabled and state.state in (STATE.enabled, STATE.overriding)
    assert 'controlsMismatch' not in state.alertType and 'commIssue' not in state.alertType
    assert sd.aol_stale_alert_deferred and sd.aol_fault_reason == 'availabilityPause'
    fresh = BASE + 40_000_000
    recovered, recovered_state, recovered_command = drive(6, gas=True, state_stamp=fresh, **settings(mode, fresh, 4))
    assert recovered.longitudinalActive and recovered_command.longActive
    assert recovered_state.enabled and CONTROLS_MISMATCH not in sd.events.names
    assert not sd.aol_stale_alert_deferred and sd.aol_fault_reason == 'none'
    assert not sd.aol_stale_grace_lost_companion


@pytest.mark.parametrize('age_ns', [120_000_000, 250_000_000], ids=['120ms', '250ms'])
@pytest.mark.parametrize('mode', GAS_LONG_MODES)
def test_gas_held_stall_past_100ms_long_modes_still_controls_mismatch(mode, age_ns):
  cleanup, sd, _, axis, state, command = expire_declined(mode, tick_offset(5, age_ns), gas=True, retention=True)
  with cleanup:
    assert not axis.lateralActive and not axis.longitudinalActive
    assert not command.latActive and not command.longActive
    assert CONTROLS_MISMATCH in sd.events.names and sd.aol_authority_lost
    assert not state.enabled and state.alertType == 'controlsMismatch/immediateDisable'
    assert sd.aol_fault_reason == 'critical'


@pytest.mark.parametrize('age_ns', [120_000_000, 250_000_000], ids=['120ms', '250ms'])
@pytest.mark.parametrize('mode', GAS_LONG_MODES)
def test_gas_held_stall_growing_past_100ms_long_modes_alerts_once_due(mode, age_ns):
  cleanup, sd, drive, _, state, command = expire_declined(mode, AGE_35_MS, gas=True, retention=True)
  with cleanup:
    for tick, held_age in ((5, None), (6, 65_000_000), (7, 95_000_000)):
      if held_age is not None:
        _, state, command = drive(tick, timeout=True, gas=True, state_stamp=BASE, offset_ns=tick_offset(tick, held_age),
                                  **settings(mode, BASE, 3))
      assert CONTROLS_MISMATCH not in sd.events.names and not sd.aol_authority_lost
      assert state.enabled and 'controlsMismatch' not in state.alertType
      assert not command.latActive and not command.longActive
    axis, state, command = drive(8, timeout=True, gas=True, state_stamp=BASE, offset_ns=tick_offset(8, age_ns),
                                 **settings(mode, BASE, 3))
    assert not axis.lateralActive and not axis.longitudinalActive
    assert not command.latActive and not command.longActive
    assert CONTROLS_MISMATCH in sd.events.names and sd.aol_authority_lost
    assert not state.enabled and state.alertType == 'controlsMismatch/immediateDisable'
