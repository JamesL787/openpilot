"""Synthetic transport, real Mazda parser/Card/SD/Controls/encoder/native callers.

Native masks originate from actual libsafety RX, never a requested expected value.
Root must run this in its matching native runtime; no standalone artifact fallback.
"""
import pytest
from opendbc.can import CANPacker
from opendbc.car import Bus, structs
from opendbc.car.mazda.values import CAR, DBC
from opendbc.car.mazda.tests.test_stock_startup import complete_frames, exercise_startup


@pytest.mark.parametrize('identity', (CAR.MAZDA_CX5_2022, CAR.MAZDA_CX9_2021))
def test_ordinary_engagement_brake_actual_family_callers(identity, monkeypatch):
  _exercise_actual_family_callers(identity, monkeypatch)


@pytest.mark.parametrize('identity', (CAR.MAZDA_CX5_2022, CAR.MAZDA_CX9_2021))
def test_unassigned_cancel_retains_lateral_main_off_revokes_actual_callers(identity, monkeypatch):
  _exercise_actual_family_callers(identity, monkeypatch, scenario='cancel', cancel_action=0)


def _exercise_actual_family_callers(identity, monkeypatch, *, scenario='brake', cancel_action=3):
  from openpilot.cereal import messaging
  from openpilot.selfdrive.car import card as card_module
  from openpilot.starpilot.aol.wire import SafetyState, encode_safety
  from openpilot.starpilot.aol.tests.test_ioniq_availability import IoniqAvailabilityTests
  from opendbc.safety.tests.common import make_msg
  from opendbc.safety.tests.libsafety import libsafety_py

  def probe(card, ci, startup_controls, saved):
    patch_scope = monkeypatch.context()
    local_patch = patch_scope.__enter__()
    local_patch.setenv('SIMULATION', '0')
    case = IoniqAvailabilityTests(methodName='runTest')
    safety = libsafety_py.libsafety
    now, tick, queued = [10_000_000_000], 0, []
    received, previous_sd = {}, {}
    first_engagement_ns = None
    try:
      sd, controls, drive = case._authority_callers(False, cp=card.CP.as_reader().as_builder(), genuine_events=True)
      if scenario == 'cancel':
        from openpilot.starpilot.aol.intent import read_settings
        sd.aol_settings = read_settings(saved)
        assert sd.aol_settings.cancel_actions == (0, 0, 0)
        assert card.aol_card_intent.settings == sd.aol_settings
      assert sd.CP.to_dict() == card.CP.to_dict() == ci.CP.to_dict() == controls.CP.to_dict()
      safety.init_tests()
      safety.set_alternative_experience(32)
      safety.set_safety_hooks(structs.CarParams.SafetyModel.mazda, 0)
      safety.set_aol_test_heartbeat(False)
      local_patch.setattr(card_module.time, 'monotonic_ns', lambda: now[0])
      local_patch.setattr(card_module.time, 'clock_gettime_ns', lambda clock: now[0])
      local_patch.setattr(card_module.messaging, 'drain_sock_raw', lambda *args, **kwargs: list(queued))
      local_patch.setattr(card.sm, 'update', lambda *args: None)
      create = messaging.new_message

      def new_message(service=None, size=None, **kwargs):
        kwargs.setdefault('logMonoTime', now[0])
        return create(service, size, **kwargs)
      local_patch.setattr(messaging, 'new_message', new_message)
      send = card.pm.send

      def capture(service, event):
        raw = event if isinstance(event, bytes) else event.to_bytes()
        received[service] = messaging.log_from_bytes(raw).as_builder()
        return send(service, raw)
      local_patch.setattr(card.pm, 'send', capture)
      packer = CANPacker(DBC[identity][Bus.pt])

      def step(*, engaged=False, brake=False, cancel=False, main=True):
        nonlocal tick, first_engagement_ns
        tick += 1
        now[0] = 10_000_000_000 + tick * 10_000_000
        frames = complete_frames(packer, card.CP, tick, main=main, engaged=engaged, brake=brake, cancel=cancel)
        frames.append(packer.make_can_msg('STEER', 0, {'STEER_ANGLE': 1.0}))
        safety.set_timer(now[0] // 1000)
        prior_state = previous_sd.get('selfdriveState')
        prior_axis = previous_sd.get('aolAxisState')
        heartbeat = bool(prior_state is not None and prior_state.selfdriveState.enabled)
        if prior_axis is not None:
          heartbeat |= bool(prior_axis.aolAxisState.desiredLateral or prior_axis.aolAxisState.desiredLongitudinal)
        # Transport requests follow the preceding actual Selfdrive axis desire.
        # Before its first publication the host has requested neither axis.
        request_lat = bool(prior_axis is not None and prior_axis.aolAxisState.desiredLateral)
        request_long = bool(prior_axis is not None and prior_axis.aolAxisState.desiredLongitudinal)
        request_mask = int(request_lat) | (int(request_long) << 1)
        safety.set_aol_test_heartbeat(heartbeat)
        for address, data, bus in frames:
          safety.safety_rx_hook(make_msg(bus, address, dat=data))
        safety.safety_tick()
        # Permission remains the actual native response to the actual axis request.
        safety.aol_set_host_request(request_mask)
        # Match main_comms.h status: report native-filtered request, then permission.
        reported_request_mask = safety.aol_get_request_mask()
        mask = safety.aol_get_permission_mask()
        reported_request_lat = bool(reported_request_mask & 1)
        reported_request_long = bool(reported_request_mask & 2)
        if first_engagement_ns is None:
          assert request_mask == reported_request_mask == mask == 0, 'No axis request before actual SD desire'
          if engaged:
            assert not heartbeat and safety.get_controls_allowed(), 'Cold physical engagement must precede host acknowledgment'
            first_engagement_ns = now[0]
        if mask & 1:
          assert heartbeat and request_lat and reported_request_lat, 'Native lateral permission needs actual request and heartbeat'
          assert first_engagement_ns is not None and now[0] > first_engagement_ns, 'Native acknowledgment must follow physical grant'
        source = messaging.log_from_bytes(card_module.can_list_to_can_capnp(frames)).as_builder()
        source.logMonoTime = now[0]
        queued[:] = [source.to_bytes()]
        events = []
        for name, size in (('deviceState', None), ('pandaStates', 1)):
          events.append(messaging.new_message(name, size, valid=True, logMonoTime=now[0]))
        events[0].deviceState.started = True
        events[0].deviceState.startedMonoTime = 9_000_000_000
        panda = events[-1].pandaStates[0]
        panda.safetyModel = card.CP.safetyConfigs[0].safetyModel
        panda.safetyParam = 0
        panda.alternativeExperience = 32
        panda.controlsAllowed = safety.get_controls_allowed()
        if 'onroadEvents' not in previous_sd:
          events.append(messaging.new_message('onroadEvents', 0, valid=True, logMonoTime=now[0]))
        for name in ('selfdriveState', 'aolAxisState', 'onroadEvents'):
          if name in previous_sd:
            events.append(previous_sd[name].as_builder())
        wire = messaging.new_message('aolSafetyWire', 0, valid=True, logMonoTime=now[0])
        wire.aolSafetyWire = encode_safety(SafetyState(1, True, now[0], now[0] + 30_000_000,
          int(card.CP.safetyConfigs[0].safetyModel.raw), 0, bool(mask & 1), bool(mask & 2),
          reported_request_lat, reported_request_long, 'native-mazda-test', card.aol_axis_session()))
        events.append(wire)
        card.sm.update_msgs(now[0] / 1e9, [event.as_reader() for event in events])
        state, _ = card.state_update()
        card.state_publish(state, None)
        axis, host_state, command = drive(tick, observed_state=state,
          intent_message=received['aolIntentWire'], allowed=bool(mask & 1), long_allowed=bool(mask & 2),
          native_request_lat=reported_request_lat, native_request_long=reported_request_long, panda_controls_allowed=safety.get_controls_allowed())
        previous_sd.update(sd.pm.messages)
        # Feed exact serialized Controls output through Card's control/publication
        # path; direct CI.apply would bypass its startup and source gates.
        published_control = controls.pm.messages['carControl']
        can_source_ns = now[0]
        # This is a later receive/decision instant, not a rewritten source stamp.
        # Only the actual Controls publication enters carControl once per cycle.
        now[0] += 1
        card.sm.update_msgs(now[0] / 1e9, [published_control])
        card.can_log_mono_time = can_source_ns
        received.pop('sendcan', None)
        card.controls_update(state, card.sm['carControl'])
        if state.canValid:
          assert 'sendcan' in received, 'Card did not publish the actual Controls command'
          outgoing = received['sendcan']
          assert outgoing.valid
          assert any(frame.address == 0x243 for frame in outgoing.sendcan)
          for frame in outgoing.sendcan:
            assert safety.safety_tx_hook(make_msg(frame.src, frame.address, dat=frame.dat))
        return state, axis, host_state, command

      for _ in range(120):
        step()
      assert not card.aol_card_intent.allowed_latch
      for _ in range(30):
        state, axis, host_state, command = step(engaged=True)
      assert state.canValid and host_state.enabled and command.latActive
      assert card.aol_card_intent.allowed_latch
      if scenario == 'cancel':
        for _ in range(5):
          state, axis, host_state, command = step(cancel=True)
          assert state.cruiseState.available and not state.cruiseState.enabled
          assert card.aol_card_intent.allowed_latch
          assert axis.lateralActive and command.latActive, 'Unassigned stock Cancel withdrew Mazda lateral'
          assert not axis.longitudinalActive and not command.longActive
          assert safety.aol_get_permission_mask() == 1
        for _ in range(30):
          state, axis, host_state, command = step()
          assert card.aol_card_intent.allowed_latch and axis.lateralActive and command.latActive
        for _ in range(5):
          state, axis, host_state, command = step(main=False)
          assert not card.aol_card_intent.allowed_latch
          assert not axis.lateralActive and not command.latActive and not command.longActive
          assert safety.aol_get_permission_mask() == 0
        return
      nonzero = False
      for _ in range(30):
        state, axis, host_state, command = step(brake=True)
        nonzero |= abs(command.actuators.torque) > 0
        assert not safety.get_controls_allowed()
        assert safety.aol_get_permission_mask() == 1
        assert card.aol_card_intent.allowed_latch
        assert axis.lateralActive and command.latActive
        assert not axis.longitudinalActive and not command.longActive
      assert nonzero, 'Actual Controls never requested a nonzero correction for measured steering error'
      invalid = controls.pm.messages['carControl'].as_builder()
      invalid.valid = False
      now[0] += 1  # Ordered receipt of an unchanged-source invalid packet.
      card.sm.update_msgs(now[0] / 1e9, [invalid.as_reader()])
      received.pop('sendcan', None)
      card.controls_update(state, card.sm['carControl'])
      assert 'sendcan' not in received, 'Invalid carControl reached Card sendcan publication'
    finally:
      safety.init_tests()
      safety.set_alternative_experience(0)
      safety.set_safety_hooks(structs.CarParams.SafetyModel.noOutput, 0)
      # Restore nested patches before the harness closes its own clock mocks.
      patch_scope.__exit__(None, None, None)
      case.doCleanups()

  exercise_startup(identity, False, False, True, monkeypatch, probe=probe, cancel_action=cancel_action)
