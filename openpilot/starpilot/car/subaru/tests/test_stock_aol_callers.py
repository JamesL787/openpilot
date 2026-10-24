"""Actual automatic Subaru factory/parser/Card/SD/Controls/native/CPP negotiation."""

import json
import time
from unittest.mock import patch
import pytest
from opendbc.can import CANParser
from opendbc.car import Bus, gen_empty_fingerprint, structs
from opendbc.car.subaru.values import CAR, DBC
from opendbc.car.subaru.fingerprints import FW_VERSIONS
from opendbc.safety.tests.libsafety import libsafety_py
from openpilot.cereal import messaging
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD
from openpilot.selfdrive.controls.controlsd import Controls
from openpilot.selfdrive.pandad import can_capnp_to_list
from openpilot.starpilot.aol.wire import decode_intent
from openpilot.starpilot.car.subaru.tests.caller_helpers import actual_factory, firmware_records, CompleteCan, feed_perception_only
from openpilot.starpilot.car.subaru.tests.selfdrive_step import selfdrive_step
from openpilot.starpilot.car.subaru.tests.pandad_order import PandadOrder

from openpilot.starpilot.car.subaru.tests.native_fixture import subaru_native_pair as subaru_native_pair


@pytest.mark.parametrize('candidate', [CAR.SUBARU_ASCENT_2023, CAR.SUBARU_LEGACY_2025, CAR.SUBARU_CROSSTREK_2025, CAR.SUBARU_FORESTER, CAR.SUBARU_OUTBACK])
def test_actual_full_engage_brake_reverse_temporary_recovery_mainoff(candidate, subaru_native_pair, tmp_path, aol=True, manual=False):
  fw = firmware_records(candidate, FW_VERSIONS, 'subaru')
  rows = []
  with actual_factory(candidate, gen_empty_fingerprint(), fw, '0' * 17, manual=manual, aol=aol) as (card, params, matches):
    cp = card.CP
    ci = card.CI
    safety = libsafety_py.libsafety
    assert cp.pcmCruise and not cp.openpilotLongitudinalControl and not cp.alphaLongitudinalAvailable
    assert cp.alternativeExperience == (32 if aol else 0) and not cp.dashcamOnly
    sd, controls = SelfdriveD(CP=cp), Controls()
    stream = CompleteCan(ci)
    safety.init_tests()
    safety.set_alternative_experience(cp.alternativeExperience)
    assert safety.set_safety_hooks(cp.safetyConfigs[0].safetyModel.raw, cp.safetyConfigs[0].safetyParam) == 0
    safety.set_aol_test_heartbeat(False)
    library, bridge = subaru_native_pair
    pandad = PandadOrder(safety, library, bridge)
    previous_controls = {}
    latest_controls = {}
    driven = {}
    driven_new = {}
    receipt = None
    steering_name = 'ES_LKAS_ANGLE' if cp.steerControlType == structs.CarParams.SteerControlType.angle else 'ES_LKAS'
    steering_address = ci.CC.packer.dbc.name_to_msg[steering_name].address
    steering_bus = 0 if candidate in (CAR.SUBARU_ASCENT_2023, CAR.SUBARU_FORESTER, CAR.SUBARU_OUTBACK, CAR.SUBARU_FORESTER_2022, CAR.SUBARU_OUTBACK_2023) else 1
    decoder = CANParser(DBC[candidate][Bus.pt], [(steering_name, 0)], steering_bus)
    dash_decoder = CANParser(DBC[candidate][Bus.pt], [('ES_LKAS_State', 0)], 0)
    dash_emissions = 0
    active_emissions = []
    base = time.monotonic_ns() + 100_000_000
    try:
      for tick in range(460):
        now = base + tick * 10_000_000
        cruise = 30 <= tick < 110 or tick >= 410
        brake = 90 <= tick < 110
        reverse = 150 <= tick < 185
        temporary = 225 <= tick < 260
        main = not 310 <= tick < 350
        values = {
          'Steering_Torque': {'Steer_Warning': int(temporary)},
          'Steering_2': {'Steering_Angle': 0},
          'Wheel_Speeds': dict.fromkeys(('FL', 'FR', 'RL', 'RR'), 54),
          'Brake_Status': {'Brake': int(brake)},
          'CruiseControl': {'Cruise_On': int(main), 'Cruise_Activated': int(cruise)},
          'ES_Status': {'Cruise_Activated': int(cruise)},
          'ES_DashStatus': {'Cruise_On': int(main), 'Cruise_Set_Speed': 100},
          'Transmission': {'Gear': 3 if reverse else 121},
        }
        incoming = stream.frames(values, tick=tick)
        safety.set_timer((now // 1000) & 0xFFFFFFFF)
        for addr, data, bus in incoming:
          safety.safety_rx_hook(libsafety_py.make_CANPacket(addr, bus, data))
        safety.safety_tick()
        panda = messaging.new_message('pandaStates', 1, valid=True, logMonoTime=now)
        panda.pandaStates[0].safetyModel = cp.safetyConfigs[0].safetyModel
        panda.pandaStates[0].safetyParam = cp.safetyConfigs[0].safetyParam
        panda.pandaStates[0].alternativeExperience = cp.alternativeExperience
        panda.pandaStates[0].ignitionLine = True
        panda.pandaStates[0].controlsAllowed = bool(safety.get_controls_allowed())
        panda.pandaStates[0].safetyRxChecksInvalid = not bool(safety.safety_config_valid())
        device = messaging.new_message('deviceState', valid=True, logMonoTime=now)
        device.deviceState.started = True
        device.deviceState.startedMonoTime = 500_000_000
        peers = [device.as_reader()]
        if tick % 10 == 0:
          peers.append(panda.as_reader())
        if 'carControl' in latest_controls:
          peers.append(latest_controls['carControl'])
        peers.extend(driven_new[s] for s in ('onroadEvents', 'selfdriveState', 'aolAxisState') if s in driven_new and s in card.sm.data)
        if receipt is not None and tick % 10 == 1:
          peers.append(receipt.as_reader())
        card.sm.update_msgs((now + 1000) / 1e9, peers)
        published = {}
        real_new = messaging.new_message

        def stamped(service=None, size=None, *, _real_new=real_new, _now=now, **kwargs):
          return _real_new(service, size, **({'logMonoTime': _now} | kwargs))

        def capture(service, msg, _published=published):
          wire = msg if isinstance(msg, bytes) else msg.to_bytes()
          _published[service] = messaging.log_from_bytes(wire)

        with (
          patch.object(card.sm, 'update'),
          patch('openpilot.selfdrive.car.card.messaging.drain_sock_raw', return_value=[b'can']),
          patch('openpilot.selfdrive.car.card.can_capnp_to_list', return_value=[(now, incoming)]),
          patch('openpilot.selfdrive.car.card.REPLAY', False),
          patch('openpilot.selfdrive.car.card.time.monotonic_ns', return_value=now + 2000),
          patch('openpilot.selfdrive.car.card.time.monotonic', return_value=(now + 2000) / 1e9),
          patch('openpilot.selfdrive.car.card.time.clock_gettime_ns', return_value=now + 2000),
          patch('openpilot.selfdrive.car.card.messaging.new_message', side_effect=stamped),
          patch.object(card.pm, 'send', side_effect=capture),
        ):
          card.step()
        if tick % 10 == 0:
          published['pandaStates'] = panda.as_reader()
        cs = published['carState'].carState
        assert cs.brakePressed == brake and cs.gearShifter == (structs.CarState.GearShifter.reverse if reverse else structs.CarState.GearShifter.drive)
        if tick >= 10:
          assert cs.canValid and safety.safety_config_valid()
        # Deliver each genuine10Hz native receipt once; do not refresh receive time/frequency from a cached snapshot.
        new_native = receipt if receipt is not None and tick % 10 == 1 else None
        driven_new = selfdrive_step(sd, published, new_native, previous_controls, cp, safety, now, calibration='calibrated')
        driven.update(driven_new)
        order = None
        if aol and tick % 10 == 0:
          receipt, order = pandad.step(driven, published, now)
        feed_perception_only(controls, now, tick, enabled=sd.enabled, active=sd.active)
        plan = messaging.new_message('longitudinalPlan', valid=True, logMonoTime=now)
        plan.longitudinalPlan.aTarget = 0.5
        control_peers = [published['carState'], published['carOutput'], plan.as_reader()]
        control_peers.extend(driven_new[s] for s in ('selfdriveState', 'onroadEvents', 'aolAxisState') if s in driven_new and s in controls.sm.data)
        if receipt is not None and tick % 10 == 0:
          control_peers.append(receipt.as_reader())
        controls.sm.update_msgs((now + 1000) / 1e9, control_peers)
        previous_controls = {}

        def capture_control(service, msg, _controls=previous_controls):
          wire = msg if isinstance(msg, bytes) else msg.to_bytes()
          _controls[service] = messaging.log_from_bytes(wire)

        with (
          patch('openpilot.selfdrive.controls.controlsd.time.monotonic_ns', return_value=now + 2000),
          patch('openpilot.cereal.messaging.time.monotonic', return_value=(now + 2000) / 1e9),
          patch.object(controls.pm, 'send', side_effect=capture_control),
        ):
          command, lateral_log = controls.state_control()
          controls.publish(command, lateral_log)
        latest_controls.update(previous_controls)
        command = previous_controls['carControl'].carControl
        outgoing = can_capnp_to_list([published['sendcan'].as_builder().to_bytes()], msgtype='sendcan')[0][1] if 'sendcan' in published else []
        tx = [(a, d.hex(), b, bool(safety.safety_tx_hook(libsafety_py.make_CANPacket(a, b, d)))) for a, d, b in outgoing]
        decoder.update([(now, outgoing)])
        dash_decoder.update([(now, outgoing)])
        if any(address == 0x322 for address, _, _ in outgoing):
          dash = dash_decoder.vl['ES_LKAS_State']
          expected = ci.CC.angle_was_active if steering_name == 'ES_LKAS_ANGLE' else card.sm['carControl'].latActive
          assert bool(dash['LKAS_ACTIVE']) == expected, (candidate, tick, expected, dash)
          assert dash['LKAS_Dash_State'] == (2 if expected else 0), (candidate, tick, expected, dash)
          assert all(accepted for address, _, _, accepted in tx if address == 0x322)
          dash_emissions += 1
        decoded_steering = []
        for address, _data, _bus, accepted in tx:
          if address == steering_address:
            request = bool(decoder.vl[steering_name]['LKAS_Request'])
            output = decoder.vl[steering_name]['LKAS_Output']
            decoded_steering.append({'request': request, 'output': output, 'nativeAccepted': accepted})
            if 65 <= tick < 90 or aol and (125 <= tick < 145 or 205 <= tick < 220 or 280 <= tick < 300):
              assert request and accepted, (tick, decoded_steering)
              if output != 0:
                active_emissions.append(tick)
            if 165 <= tick < 180 or 240 <= tick < 255 or not aol and (125 <= tick < 145 or 205 <= tick < 220 or 280 <= tick < 300):
              assert not request and output == 0, (tick, decoded_steering)
        intent = decode_intent(published['aolIntentWire'].aolIntentWire) if aol else None
        row = {
          'tick': tick,
          'intent': bool(intent and intent.allowedLatch),
          'armed': bool(intent and intent.lateralArmed),
          'cardLatch': bool(card.aol_card_intent and card.aol_card_intent.allowed_latch),
          'lat': command.latActive,
          'long': command.longActive,
          'enabled': sd.enabled,
          'active': sd.active,
          'permission': int(safety.aol_get_permission_mask()),
          'controls': bool(safety.get_controls_allowed()),
          'nativeNewToSD': new_native is not None,
          'pandaNew': tick % 10 == 0,
          'nativeSource': None if receipt is None else int(receipt.logMonoTime),
          'order': order,
          'tx': tx,
          'steering': decoded_steering,
          'fault': str(driven['aolAxisState'].aolAxisState.faultReason) if aol else 'unsupported',
          'events': [str(e.name) for e in driven['onroadEvents'].onroadEvents],
        }
        rows.append(row)
        assert not command.longActive, row
        if 10 <= tick < 30:
          assert not command.latActive and not bool(intent and intent.allowedLatch) and row['permission'] == 0, row
        if 65 <= tick < 90:
          assert command.latActive and bool(intent and intent.allowedLatch) == aol and row['permission'] == int(aol), row
        if 125 <= tick < 145 or 205 <= tick < 220 or 280 <= tick < 300:
          assert command.latActive == aol and bool(intent and intent.allowedLatch) == aol and row['permission'] == int(aol) and not row['controls'], row
        if 165 <= tick < 180:
          assert (not command.latActive and not bool(intent and intent.allowedLatch) and
                bool(intent and intent.lateralArmed) == aol and row['cardLatch'] == aol and row['permission'] == 0), row
        if 240 <= tick < 255:
          assert not command.latActive and bool(intent and intent.lateralArmed) == aol and row['cardLatch'] == aol and row['permission'] == 0, row
        if 330 <= tick < 400:
          assert not command.latActive and not bool(intent and intent.allowedLatch), row
        if tick >= 440:
          assert command.latActive and bool(intent and intent.allowedLatch) == aol and row['permission'] == int(aol), row
      assert len(active_emissions) >= 4, rows[65:90]
      assert dash_emissions >= 40
    finally:
      pandad.close()
      (tmp_path / (str(candidate) + '-' + str(aol) + '-actual.json')).write_text(json.dumps(rows, indent=2) + '\n')
