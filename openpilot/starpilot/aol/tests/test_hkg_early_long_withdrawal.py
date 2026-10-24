"""EV6 brake receipt ordering retains only native-granted lateral permission."""
from contextlib import ExitStack
from dataclasses import replace

import pytest

from openpilot.cereal import log, messaging
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.starpilot.aol.runtime import current_native
from openpilot.starpilot.aol.transport_pause import TransportPauseFeedback
from openpilot.starpilot.aol.wire import encode_safety
from openpilot.starpilot.aol.tests import test_ioniq_availability as fixture
from openpilot.starpilot.aol.tests.test_ev6_physical_authorization import ev6_params

BASE = 10_000_000_000


def wire(sd, now, *, health_controls=True, lateral=True):
  prior = current_native(sd.sm, sd.CP, now_ns=now - 10_000_000, axis_session_id=sd.aol_session_id)
  assert prior is not None
  state = replace(prior, observedMonoTime=now, validUntilMonoTime=now + 200_000_000,
                  lateralAllowed=lateral, longitudinalAllowed=False, sourcePandaStatesMonoTime=now,
                  pandaInventory=tuple(replace(slot, controlsAllowed=health_controls) for slot in prior.pandaInventory))
  message = messaging.new_message('aolSafetyWire', 0, valid=True, logMonoTime=now)
  message.aolSafetyWire = encode_safety(state)
  return message


def callers(case):
  return case._authority_callers(True, cp=ev6_params(), genuine_events=True)


def test_ev6_early_brake_mask_is_not_an_immediate_fault():
  case = fixture.IoniqAvailabilityTests(methodName='runTest')
  with ExitStack() as cleanup:
    cleanup.callback(case.doCleanups)
    cleanup.enter_context(OpenpilotPrefix())
    sd, _, drive = callers(case)
    for tick in range(10):
      axis, state, command = drive(tick)
      assert state.enabled and axis.lateralActive and axis.longitudinalActive
      assert command.latActive and command.longActive
    now = BASE + 100_000_000
    # Native health is read before its mask; latest PandaStates may already
    # report the brake, while parsed carState reaches selfdrive one tick later.
    native = wire(sd, now)
    axis, state, command = drive(10, native_request_lat=True, native_request_long=True,
      long_allowed=False, panda_controls_allowed=False, safety_message=native)
    assert log.OnroadEvent.EventName.controlsMismatch not in sd.events.names, 'EV6_EARLY_NATIVE_LONG_WITHDRAWAL_MISCLASSIFIED'
    assert state.enabled and axis.lateralActive and command.latActive
    assert not axis.longitudinalActive and not command.longActive
    assert sd.mismatch_counter > 0
    axis, state, command = drive(11, brake=True, native_request_lat=True, native_request_long=True,
      long_allowed=False, panda_controls_allowed=False)
    assert not state.enabled and not state.active
    assert axis.lateralActive and command.latActive
    assert not axis.longitudinalActive and not command.longActive
    assert log.OnroadEvent.EventName.controlsMismatch not in sd.events.names


def test_card_feedback_accepts_only_existing_lateral_grant_during_early_long_drop():
  case = fixture.IoniqAvailabilityTests(methodName='runTest')
  with ExitStack() as cleanup:
    cleanup.callback(case.doCleanups)
    cleanup.enter_context(OpenpilotPrefix())
    sd, _, drive = callers(case)
    feedback = TransportPauseFeedback(sd.CP)
    sm = messaging.SubMaster(['aolAxisState', 'onroadEvents', 'aolSafetyWire', 'pandaStates'])
    for tick in range(10):
      drive(tick)
      now = BASE + tick * 10_000_000
      frames = [sd.pm.messages['aolAxisState'], sd.pm.messages['onroadEvents']]
      for name in ('aolSafetyWire', 'pandaStates'):
        event = messaging.new_message(name, len(sd.sm[name]), valid=sd.sm.valid[name], logMonoTime=sd.sm.logMonoTime[name])
        setattr(event, name, sd.sm[name])
        frames.append(event.as_reader())
      sm.update_msgs(now / 1e9, frames)
      assert not feedback.observe(sm, sd.CP, sd.CS_prev, now, latched=True, intent_producer_session='authority-card')
    now = BASE + 100_000_000
    sm.update_msgs(now / 1e9, [wire(sd, now).as_reader()])
    assert not feedback.observe(sm, sd.CP, sd.CS_prev, now, latched=True,
      intent_producer_session='authority-card'), 'EV6_CARD_EARLY_LONG_WITHDRAWAL_CLEARED_INTENT'
    assert not feedback.failed


@pytest.mark.parametrize('fault', ('lateral_denied', 'invalid', 'rx', 'heartbeat', 'inventory', 'session', 'expired'))
def test_early_long_classification_never_retains_denied_or_invalid_lateral(fault):
  case = fixture.IoniqAvailabilityTests(methodName='runTest')
  with ExitStack() as cleanup:
    cleanup.callback(case.doCleanups)
    cleanup.enter_context(OpenpilotPrefix())
    sd, _, drive = callers(case)
    for tick in range(2):
      axis, _, command = drive(tick)
      assert axis.lateralActive and command.latActive and command.longActive
    now = BASE + 20_000_000
    event = wire(sd, now, lateral=fault != 'lateral_denied')
    from openpilot.starpilot.aol.wire import decode_safety
    native = decode_safety(event.aolSafetyWire)
    assert native is not None
    if fault == 'invalid':
      event.valid = False
    elif fault in ('rx', 'heartbeat', 'inventory'):
      field, value = {'rx': ('safetyRxChecksInvalid', True), 'heartbeat': ('heartbeatLost', True),
                      'inventory': ('safetyParam', 0)}[fault]
      native = replace(native, pandaInventory=(replace(native.pandaInventory[0], **{field: value}),))
    elif fault == 'session':
      native = replace(native, axisSessionId='foreign')
    elif fault == 'expired':
      native = replace(native, observedMonoTime=now - 200_000_001, validUntilMonoTime=now - 1)
      event.logMonoTime = native.observedMonoTime
    event.aolSafetyWire = encode_safety(native)
    axis, state, command = drive(2, native_request_lat=True, native_request_long=True,
      long_allowed=False, panda_controls_allowed=False, safety_message=event)
    assert not axis.lateralActive and not command.latActive
    assert not axis.longitudinalActive and not command.longActive
    assert not state.enabled
    assert log.OnroadEvent.EventName.controlsMismatch in sd.events.names


def test_ev6_persistent_controls_denial_keeps_original_mismatch_counter():
  case = fixture.IoniqAvailabilityTests(methodName='runTest')
  with ExitStack() as cleanup:
    cleanup.callback(case.doCleanups)
    cleanup.enter_context(OpenpilotPrefix())
    sd, _, drive = callers(case)
    for tick in range(10):
      drive(tick)
    for tick in range(10, 214):
      axis, state, command = drive(tick, native_request_lat=True, native_request_long=True,
        long_allowed=False, panda_controls_allowed=False)
      assert not axis.longitudinalActive and not command.longActive
      if log.OnroadEvent.EventName.controlsMismatch in sd.events.names:
        break
      assert axis.lateralActive and command.latActive and state.enabled
    assert sd.mismatch_counter >= 200
    assert not state.enabled and not axis.lateralActive and not command.latActive


@pytest.mark.parametrize('change', ('none', 'unmarked', 'wrong_word', 'stock', 'passive', 'wrong_identity'))
def test_exact_torque_long_profile_boundary(change):
  from openpilot.starpilot.car.hyundai.aol import early_native_long_withdrawal_supported
  cp = ev6_params()
  cp.safetyConfigs[0].safetyParam = 0x815
  cp.alternativeExperience = 32
  if change == 'unmarked':
    cp.alternativeExperience = 0
  elif change == 'wrong_word':
    cp.safetyConfigs[0].safetyParam = 0x8815
  elif change == 'stock':
    cp.openpilotLongitudinalControl, cp.pcmCruise = False, True
  elif change == 'passive':
    cp.passive = True
  elif change == 'wrong_identity':
    cp.carFingerprint = 'KIA_EV9'
  assert early_native_long_withdrawal_supported(cp) == (change == 'none')
