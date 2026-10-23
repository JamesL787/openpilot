"""Shared actual Ford factory/Card/SD/Controls/native regression fixture.

Transport, clocks and initialized onroad service sources are synthetic. This is
not startup/USB/road qualification. No desired/allowed axis value is invented.
"""

from types import SimpleNamespace

from opendbc.can import CANParser
from opendbc.car import Bus
from unittest.mock import patch

import pytest
from openpilot.starpilot.aol.wire import decode_intent

"""Test transport subset of pandad's current, producer-bound retained-arm heartbeat."""


def retained_arm(intent_event, axis_event, now_ns):
  if intent_event is None or axis_event is None or not intent_event.valid or not axis_event.valid:
    return False
  intent = decode_intent(bytes(intent_event.aolIntentWire))
  axis = axis_event.aolAxisState
  if intent is None:
    return False
  stamp = int(intent_event.logMonoTime)
  # The coupled probe has exact same-source Card/SD publications. This stricter
  # subset needs none of pandad's optional newer-source/expired-axis joins.
  return bool(
    axis.qualified
    and axis.sessionId
    and axis.intentProducerSessionId
    and int(axis_event.logMonoTime) == axis.observedMonoTime == axis.sourceCarStateMonoTime == stamp
    and 0 < stamp <= now_ns <= axis.validUntilMonoTime
    and now_ns - stamp <= 30_000_000
    and intent.producerSessionId == str(axis.intentProducerSessionId)
    and intent.sequence > 0
    and intent.carStateLogMonoTime == intent.observedMonoTime == stamp
    and intent.settingsQualified
    and intent.lateralArmed
    and now_ns <= intent.validUntilMonoTime
  )


from opendbc.car.ford.values import CAR, FordFlags, DBC
from openpilot.cereal import messaging
from openpilot.selfdrive.car import card as card_module
from openpilot.starpilot.aol.wire import PandaSlot, SafetyState, encode_safety


FORD_FACTORIES = (
  (CAR.FORD_BRONCO_SPORT_MK1, 32),
  (CAR.FORD_EDGE_MK2, 8),
  (CAR.FORD_ESCAPE_MK4, 32),
  (CAR.FORD_ESCAPE_MK4_5, 66),
  (CAR.FORD_EXPLORER_MK6, 32),
  (CAR.FORD_EXPEDITION_MK4, 66),
  (CAR.FORD_F_150_MK14, 66),
  (CAR.FORD_F_150_LIGHTNING_MK1, 66),
  (CAR.FORD_FOCUS_MK4, 32),
  (CAR.FORD_MONDEO_MK5, 10),
  (CAR.FORD_MAVERICK_MK1, 32),
  (CAR.FORD_MUSTANG_MACH_E_MK1, 18),
  (CAR.FORD_RANGER_MK2, 66),
  (CAR.FORD_TRANSIT_MK5, 12),
)


@pytest.fixture
def ford_joined(identity, alpha, hands_free, monkeypatch, record_property):
  from opendbc.car import car_helpers, gen_empty_fingerprint, structs
  from opendbc.safety.tests import test_ford_aol as ford_native_module
  from openpilot.common.params import Params
  from openpilot.common.prefix import OpenpilotPrefix

  monkeypatch.setenv('SIMULATION', '1')
  monkeypatch.setenv('REPLAY', '1')
  monkeypatch.setenv('AOL_REPLAY_RUNTIME', '0')
  native = ford_native_module.TestFordAolDriverIntent(methodName='runTest')
  native.setUp()
  release = native.safety.set_safety_hooks(structs.CarParams.SafetyModel.allOutput, 0) != 0
  host = None
  with OpenpilotPrefix():
    saved = Params()
    for key, value in (
      ('OpenpilotEnabledToggle', True),
      ('AlwaysOnLateral', True),
      ('SafeMode', False),
      ('AlphaLongitudinalEnabled', alpha),
      ('IsReleaseBranch', release),
      ('FordHumanTurnDetection', False),
    ):
      saved.put_bool(key, value, block=True)
    from pathlib import Path

    for key, value in (('FordLateralMode', b'1'), ('PauseAOLOnBrake', b'0.0'), ('CancelButtonControl', b'0'), ('MainCruiseButtonControl', b'0')):
      Path(saved.get_param_path(key)).write_bytes(value)
    from pathlib import Path

    Path(saved.get_param_path("FordHandsFreeCluster")).write_bytes(b"1" if hands_free else b"0")
    fp = gen_empty_fingerprint()
    fp[0][0x5A] = 8
    fp[0].update({0x3A6: 8, 0x3A7: 8})
    fp[2].update({0x3D6: 8, 0x186: 8})
    name, base = identity
    observed = (name, fp, '0' * 17, [], structs.CarParams.FingerprintSource.can, True)
    try:
      with monkeypatch.context() as discovery:
        discovery.setattr(car_helpers, 'fingerprint', lambda *args: observed)
        discovery.setattr(card_module, 'can_comm_callbacks', lambda *args: (lambda *args: [], lambda frames: None))
        discovery.setattr(card_module.messaging, 'recv_one_retry', lambda socket: messaging.new_message('can', 1))
        host = card_module.Car()
      assert host.CP.alternativeExperience == 32 and host.aol_card_intent is not None
      assert str(host.CP.carFingerprint) == str(name)
      expected_long = bool(alpha and not release)
      assert host.CP.openpilotLongitudinalControl == expected_long
      assert host.CP.safetyConfigs[0].safetyParam == base | int(expected_long)
      record_property('ford_factory_identity', str(name))
      record_property('ford_saved_alpha', alpha)
      record_property('ford_release', release)
      record_property('ford_longitudinal', expected_long)
      record_property('ford_safety_word', int(host.CP.safetyConfigs[0].safetyParam))
      native.reset(host.CP.safetyConfigs[0].safetyParam)
      native.word &= ~1
      # Real empty update registers lazily accessed parser messages before RX.
      # Card.controls_update owns CI initialization; no flag is assigned here.
      host.CI.update([])
      for _warm_tick in range(120):
        preframes = []

        def pre_rx(message, fields, preframes=preframes):
          frame = native.packer.make_can_msg(message, 0, fields)
          from opendbc.safety.tests.libsafety import libsafety_py

          assert native.safety.safety_rx_hook(libsafety_py.make_CANPacket(frame[0], frame[2], frame[1]))
          preframes.append(frame)

        with patch.object(native, 'rx', side_effect=pre_rx):
          native.pump(1, main=3, mask=0, heartbeat=False, speed=15.0)
        extras: list[tuple[str, int, dict[str, float]]] = [
          ('SteeringPinion_Data', 0, {'StePinCompAnEst_D_Qf': 3}),
          ('Cluster_Info1_FD1', 0, {'AccEnbl_B_RqDrv': 1}),
          ('BodyInfo_3_FD1', 0, {}),
          ('RCMStatusMessage2_FD1', 0, {'FirstRowBuckleDriver': 1}),
          ('INSTRUMENT_PANEL', 0, {}),
          ('IPMA_Data', 2, {}),
          ('ACCDATA', 2, {}),
          ('ACCDATA_2', 2, {}),
          ('ACCDATA_3', 2, {}),
        ]
        if host.CP.flags & FordFlags.ALT_STEER_ANGLE:
          extras += [('SteeringPinion_Data_Alt', 0, {'StePinRelInit_An_Sns': 0}), ('ParkAid_Data', 0, {'ExtSteeringAngleReq2': 0})]
        if host.CP.flags & FordFlags.LKA_STEERING:
          extras += [('LateralMotionControl', 2, {})]
        extras += [('Side_Detect_L_Stat', 2, {}), ('Side_Detect_R_Stat', 2, {})]
        preframes += [native.packer.make_can_msg(message, bus, fields) for message, bus, fields in extras]
        state = host.CI.update([(10_000_000_000 + native.tick * 10_000_000, preframes)])
        assert not native.safety.get_controls_allowed() and native.safety.aol_get_permission_mask() == 0
      assert state.canValid and not state.canTimeout
      yield SimpleNamespace(host=host, native=native, safety=native.safety, initial_cp=host.CP.to_dict(), expected_long=expected_long, hands_free=hands_free)
    finally:
      native.tearDown()
      if host is not None:
        host.vehicle_startup.close()


def run_actual_producer(ford_joined, monkeypatch, *, scenario='reverse', reengage=False):
  # Reuse the factory/parser/native configuration; no old synthetic SD peer runs.
  from openpilot.starpilot.aol.tests import test_ioniq_availability as availability

  joined = ford_joined
  host, native, safety = joined.host, joined.native, joined.safety
  case = availability.IoniqAvailabilityTests(methodName='runTest')
  now = [10_000_000_000]
  queued, published, previous_sd = [], {}, {}
  steps = start_tick = native.tick
  warmup_waits = qualified_samples = 0
  active_lat_frames = active_long_frames = 0
  long_parser = CANParser(DBC[host.CP.carFingerprint][Bus.pt], [('ACCDATA', 50)], 0)

  class ClockMappedSafety:
    """Translate only the native fixture's clock epoch to the existing SD harness."""

    def set_timer(self, timestamp):
      safety.set_timer(timestamp + 9_000_000)

    def __getattr__(self, name):
      return getattr(safety, name)

  try:
    with monkeypatch.context() as local:
      local.setenv('SIMULATION', '0')
      sd, controls, drive = case._authority_callers(False, cp=host.CP.as_reader().as_builder(), genuine_events=True)
      assert sd.CP.to_dict() == controls.CP.to_dict() == host.CP.to_dict()
      local.setattr(card_module, 'REPLAY', False)
      local.setattr(card_module.time, 'monotonic_ns', lambda: now[0])
      local.setattr(card_module.time, 'clock_gettime_ns', lambda clock: now[0])
      local.setattr(card_module.time, 'monotonic', lambda: now[0] / 1e9)
      local.setattr(card_module.messaging, 'drain_sock_raw', lambda *args, **kwargs: list(queued))
      local.setattr(host.sm, 'update', lambda *args: None)
      create = messaging.new_message

      def clocked_message(service=None, size=None, **kwargs):
        kwargs.setdefault('logMonoTime', now[0])
        return create(service, size, **kwargs)

      local.setattr(messaging, 'new_message', clocked_message)
      send = host.pm.send

      def capture(service, event):
        raw = event if isinstance(event, bytes) else event.to_bytes()
        published[service] = messaging.log_from_bytes(raw).as_builder()
        return send(service, raw)

      local.setattr(host.pm, 'send', capture)
      native.safety = ClockMappedSafety()

      location_unavailable = [False]
      original_update = sd.sm.update_msgs

      def location_update(timestamp, messages):
        selected = []
        for message in messages:
          if message.which() == 'deviceMotion':
            message = message.as_builder()
            message.deviceMotion.inputsOK = not location_unavailable[0]
            message = message.as_reader()
          selected.append(message)
        return original_update(timestamp, selected)

      local.setattr(sd.sm, 'update_msgs', location_update)

      def step(*, engaged=False, brake=False, reverse=False, warmup=False, fault=None, main_off=False, availability_transition=False):
        nonlocal steps, warmup_waits, qualified_samples, active_lat_frames, active_long_frames
        steps += 1
        now[0] = 10_000_000_000 + steps * 10_000_000
        prior_axis = previous_sd.get('aolAxisState')
        joined.last_input_axis = prior_axis
        prior_state = previous_sd.get('selfdriveState')
        request = 0 if prior_axis is None else (int(prior_axis.aolAxisState.desiredLateral) | (int(prior_axis.aolAxisState.desiredLongitudinal) << 1))
        arm_heartbeat = retained_arm(published.get('aolIntentWire'), prior_axis, now[0])
        heartbeat = bool(request or prior_state is not None and prior_state.selfdriveState.enabled or arm_heartbeat)
        frames = []

        def receive(name, values):
          fields = dict(values)
          if name == 'EngBrakeData' and brake:
            fields['BpedDrvAppl_D_Actl'] = 2
          if name == 'EngVehicleSpThrottle' and fault == 'gas':
            fields['ApedPos_Pc_ActlArb'] = 25
          if name == 'BrakeSysFeatures' and fault == 'rx-quality':
            fields['VehVActlBrk_D_Qf'] = 0
          frame = native.packer.make_can_msg(name, 0, fields)
          if not (fault == 'source-loss' and name == 'Yaw_Data_FD1'):
            accepted = safety.safety_rx_hook(joined_packet(frame))
            assert bool(accepted) == (not (fault == 'rx-quality' and name == 'BrakeSysFeatures'))
          frames.append(frame)

        with patch.object(native, 'rx', side_effect=receive):
          native.pump(
            1,
            main=0 if main_off else 5 if engaged else 3,
            gear=1 if reverse else 3,
            mask=request,
            heartbeat=heartbeat and fault != 'heartbeat',
            speed=15.0,
            eps=1 if fault == 'temporary-eps' else 0,
          )
        assert native.tick == steps
        safety.safety_tick()
        native_request = safety.aol_get_request_mask()
        permission = safety.aol_get_permission_mask()
        joined.last_permission = permission
        joined.last_native_request = native_request
        if prior_axis is None:
          assert request == native_request == permission == 0
        assert permission & 1 == 0 or heartbeat and request & 1 and native_request & 1
        extras = [
          ('SteeringPinion_Data', 0, {'StePinCompAnEst_D_Qf': 3}),
          ('Cluster_Info1_FD1', 0, {'AccEnbl_B_RqDrv': 1}),
          ('BodyInfo_3_FD1', 0, {}),
          ('RCMStatusMessage2_FD1', 0, {'FirstRowBuckleDriver': 1}),
          ('INSTRUMENT_PANEL', 0, {}),
          ('IPMA_Data', 2, {}),
          ('ACCDATA', 2, {}),
          ('ACCDATA_2', 2, {}),
          ('ACCDATA_3', 2, {}),
        ]
        if host.CP.flags & FordFlags.ALT_STEER_ANGLE:
          extras.append(('SteeringPinion_Data_Alt', 0, {'StePinRelInit_An_Sns': 0}))
          if steps % 2 == 0:
            extras.append(('ParkAid_Data', 0, {'ExtSteeringAngleReq2': 0}))
        if host.CP.flags & FordFlags.LKA_STEERING and steps % 5 == 0:
          extras.append(('LateralMotionControl', 2, {}))
        extras += [('Side_Detect_L_Stat', 2, {}), ('Side_Detect_R_Stat', 2, {})]
        frames += [native.packer.make_can_msg(name, bus, fields) for name, bus, fields in extras]
        batch = messaging.log_from_bytes(card_module.can_list_to_can_capnp(frames)).as_builder()
        batch.logMonoTime = now[0]
        queued[:] = [batch.to_bytes()]
        config = host.CP.safetyConfigs[0]
        slot = PandaSlot(
          0, 'authority-panda', config.safetyModel.raw, config.safetyParam, 32, bool(safety.get_controls_allowed()), not bool(safety.safety_config_valid())
        )
        native_state = SafetyState(
          1,
          True,
          now[0],
          now[0] + 200_000_000,
          config.safetyModel.raw,
          config.safetyParam,
          bool(permission & 1),
          bool(permission & 2),
          bool(native_request & 1),
          bool(native_request & 2),
          'authority-panda',
          str(prior_axis.aolAxisState.sessionId) if prior_axis is not None else host.aol_axis_session(),
          sourcePandaStatesMonoTime=now[0],
          pandaInventory=(slot,),
        )
        wire = messaging.new_message('aolSafetyWire', 0, valid=True, logMonoTime=now[0])
        wire.aolSafetyWire = encode_safety(native_state)
        panda = messaging.new_message('pandaStates', 1, valid=True, logMonoTime=now[0])
        panda.pandaStates[0].safetyModel = config.safetyModel
        panda.pandaStates[0].safetyParam = config.safetyParam
        panda.pandaStates[0].alternativeExperience = 32
        panda.pandaStates[0].controlsAllowed = slot.controlsAllowed
        panda.pandaStates[0].safetyRxChecksInvalid = slot.safetyRxChecksInvalid
        device = messaging.new_message('deviceState', valid=True, logMonoTime=now[0])
        device.deviceState.started, device.deviceState.startedMonoTime = True, 9_000_000_000
        events = [wire.as_reader(), panda.as_reader(), device.as_reader()]
        for name in ('selfdriveState', 'aolAxisState', 'onroadEvents'):
          if name in previous_sd:
            events.append(previous_sd[name])  # Original publication/source stamps.
        if 'onroadEvents' not in previous_sd:
          events.append(messaging.new_message('onroadEvents', 0, valid=True, logMonoTime=now[0]).as_reader())
        host.sm.update_msgs(now[0] / 1e9, events)
        state, _ = host.state_update()
        host.state_publish(state, None)
        assert 'aolIntentWire' in published
        parser_ready = bool(
          state.canValid and not state.canTimeout and state.cruiseState.available and str(state.gearShifter) == 'drive' and safety.safety_config_valid()
        )
        if warmup and not parser_ready:
          assert steps <= start_tick + 120 and not engaged and not brake and not reverse
          assert request == native_request == permission == 0
          assert not safety.get_controls_allowed() and not host.aol_card_intent.allowed_latch
          warmup_waits += 1
          return state, None, None, None
        if fault is None:
          assert state.canValid and not state.canTimeout
        qualified_samples += 1
        parsed_before_producer = state.to_dict()
        assert (main_off or state.cruiseState.available or availability_transition and not state.cruiseState.enabled) and not state.steeringPressed
        assert bool(state.gasPressed) == (fault == 'gas')
        axis, sd_state, command = drive(
          steps,
          car_state_message=published['carState'],
          gas=bool(state.gasPressed),
          steering=bool(state.steeringPressed),
          intent_message=published['aolIntentWire'],
          allowed=bool(permission & 1),
          long_allowed=bool(permission & 2),
          native_request_lat=bool(native_request & 1),
          native_request_long=bool(native_request & 2),
          panda_controls_allowed=bool(safety.get_controls_allowed()),
          panda_fault=slot.safetyRxChecksInvalid,
        )
        assert state.to_dict() == parsed_before_producer, 'Authority harness changed actual parsed CarState'
        previous_sd.update(sd.pm.messages)
        control = controls.pm.messages['carControl']
        source_ns = now[0]
        now[0] += 1
        host.sm.update_msgs(now[0] / 1e9, [control])
        host.can_log_mono_time = source_ns
        published.pop('sendcan', None)
        host.controls_update(state, host.sm['carControl'])
        if state.canValid:
          assert 'sendcan' in published
          assert published['sendcan'].valid
          for frame in published['sendcan'].sendcan:
            from opendbc.safety.tests.libsafety import libsafety_py

            assert safety.safety_tx_hook(libsafety_py.make_CANPacket(frame.address, frame.src, frame.dat))
            data, address = frame.dat, frame.address
            if address in (0x3CA, 0x3D3, 0x3D6):
              active = ((data[4] >> 2) & 7) != 0 if address == 0x3D3 else ((data[0] >> 4) & 7) != 0 if address == 0x3D6 else (data[0] >> 5) in (2, 4)
              if active:
                assert command.latActive and permission & 1
                active_lat_frames += 1
            elif address == 0x186:
              long_parser.update([(source_ns, [(address, bytes(data), frame.src)])])
              active = bool(long_parser.vl['ACCDATA']['Cmbb_B_Enbl'])
              assert active == bool(command.longActive)
              active_long_frames += int(active)
        if scenario in ('display', 'route24', 'route24-mixed-eps', 'route2a', 'route2a-main', 'route2a-main-fault'):
          ui = [f for f in published['sendcan'].sendcan if f.address in (0x3D8, 0x18A)]
          owns = all(safety.safety_fwd_hook(2, address) == -1 for address in (0x3D8, 0x18A))
          assert host.CP.carFingerprint != CAR.FORD_MUSTANG_MACH_E_MK1 or not ui or owns, (
            'Host injected cluster UI while native still forwarded stock UI',
            steps,
            bool(command.latActive),
            int(permission),
            int(safety.aol_get_permission_mask()),
            [(hex(f.address), bytes(f.dat).hex()) for f in published['sendcan'].sendcan],
            dict(vars(host.CI.CC)).get('aol_mache_ui'),
          )
          for frame in ui:
            if frame.address == 0x18A and command.latActive:
              display_parser = CANParser('ford_lincoln_base_pt', [('ACCDATA_3', 5)], 0)
              display_parser.update([(now[0], [(frame.address, bytes(frame.dat), frame.src)])])
              assert display_parser.vl['ACCDATA_3']['Tja_D_Stat'] == (7 if joined.hands_free else 2)
          if not command.latActive and host.CP.carFingerprint == CAR.FORD_MUSTANG_MACH_E_MK1:
            assert not ui
            assert all(safety.safety_fwd_hook(2, address) == 0 for address in (0x3D8, 0x18A))
        assert bool(axis.longitudinalActive) == bool(command.longActive)
        if not joined.expected_long:
          assert not axis.longitudinalActive and not command.longActive
        elif command.longActive:
          assert permission & 2 and safety.get_controls_allowed()
        return state, axis, sd_state, command

      def joined_packet(frame):
        from opendbc.safety.tests.libsafety import libsafety_py

        return libsafety_py.make_CANPacket(frame[0], frame[2], frame[1])

      for _ in range(120):
        step(warmup=True)
      assert 0 <= warmup_waits < 120 and qualified_samples >= 100
      assert host.ci_initialized  # Read-only witness: real controls_update completed init.
      assert not host.aol_card_intent.allowed_latch
      assert scenario in ('route24', 'route24-mixed-eps', 'route2a', 'route2a-main', 'route2a-main-fault')
      if scenario in ('route24', 'route24-mixed-eps', 'route2a', 'route2a-main', 'route2a-main-fault'):
        mixed_eps = scenario in ('route24-mixed-eps', 'route2a', 'route2a-main', 'route2a-main-fault')
        assert host.CP.flags == 3 and not host.CP.openpilotLongitudinalControl
        for _ in range(30):
          step(fault='gas')
        for _ in range(40):
          state, axis, sd_state, command = step(engaged=True, fault='gas')
        assert state.cruiseState.enabled and state.gasPressed and host.aol_card_intent.allowed_latch
        for _ in range(40):
          state, axis, sd_state, command = step()
          assert host.aol_card_intent.allowed_latch, 'Route24 normal stock disengage after gas engagement erased AOL'
        assert axis.lateralActive and command.latActive and not command.longActive and not sd_state.enabled
        for _ in range(40):
          step(engaged=True)
        for _ in range(30):
          state, axis, sd_state, command = step(brake=True)
        assert host.aol_card_intent.allowed_latch and command.latActive and not command.longActive
        for _ in range(20):
          state, axis, sd_state, command = step(brake=mixed_eps)
        assert state.brakePressed == mixed_eps and command.latActive and host.aol_card_intent.allowed_latch
        for _ in range(60):
          state, axis, sd_state, command = step(brake=mixed_eps, fault='temporary-eps')
          assert host.aol_card_intent.allowed_latch
          if state.steerFaultTemporary:
            assert not command.latActive and not command.longActive
        for _ in range(40):
          state, axis, sd_state, command = step(brake=mixed_eps)
        assert state.brakePressed == mixed_eps and command.latActive and host.aol_card_intent.allowed_latch and not command.longActive
        for _ in range(20):
          state, axis, sd_state, command = step()
        assert not state.brakePressed and command.latActive and host.aol_card_intent.allowed_latch
        for _ in range(30):
          state, axis, sd_state, command = step(reverse=True)
        assert host.aol_card_intent.allowed_latch and not command.latActive and not command.longActive
        for _ in range(40):
          state, axis, sd_state, command = step()
        assert command.latActive and not command.longActive and host.aol_card_intent.allowed_latch
        if scenario == 'route2a':
          # The previous native session has been withdrawn with MAIN still on,
          # matching the route's new engagement after its earlier host failure.
          for _ in range(30):
            state, axis, sd_state, command = step(fault='heartbeat')
          assert not host.aol_card_intent.allowed_latch and not command.latActive and not command.longActive
          for _ in range(30):
            step()
          for _ in range(40):
            state, axis, sd_state, command = step(engaged=True, fault='gas')
          assert state.cruiseState.enabled and command.latActive and host.aol_card_intent.allowed_latch
          for _ in range(40):
            state, axis, sd_state, command = step()
            assert host.aol_card_intent.allowed_latch, 'Route2a new ordinary engagement lost retained native token'
          assert command.latActive and axis.lateralActive and not command.longActive and not sd_state.enabled
        for _ in range(30):
          state, axis, sd_state, command = step(main_off=True)
        assert not state.cruiseState.available
        assert not host.aol_card_intent.allowed_latch and not command.latActive and not command.longActive
        if scenario in ('route2a-main', 'route2a-main-fault'):
          failed_edge = scenario == 'route2a-main-fault'
          for transition_tick in range(30):
            state, axis, sd_state, command = step(fault='rx-quality' if failed_edge else None, availability_transition=transition_tick < 10)
          if failed_edge:
            for _ in range(40):
              state, axis, sd_state, command = step()
          assert state.cruiseState.available and not state.cruiseState.enabled
          assert host.aol_card_intent.allowed_latch == (not failed_edge)
          assert command.latActive == (not failed_edge) and not command.longActive
          for _ in range(30):
            state, axis, sd_state, command = step(main_off=True)
          assert not host.aol_card_intent.allowed_latch and not command.latActive and not command.longActive
        return
  finally:
    native.safety = safety
    case.doCleanups()
