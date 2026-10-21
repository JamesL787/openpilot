"""Actual registered mode39 bounds; no forced controlsAllowed or native callback bypass."""
import pytest
from opendbc.car.tesla.tests.preap_stream import PreAPStream
from opendbc.car.tesla.preap.pedal_contract import PedalCalibration, PedalCodec
from opendbc.safety.tests.libsafety import libsafety_py
from openpilot.starpilot.car.tesla.tests.pedal_fixture import configure_native, feedback_frame


def warm(bus, word):
  safety = libsafety_py.libsafety
  calibration = PedalCalibration(1., 0., bus)
  configure_native(safety, calibration, word, b'actual-registered-profile-test')
  stream = PreAPStream()
  priming = PedalCodec(calibration)
  now = 0
  for tick in range(1, 91):
    now = 1_000_000 + tick * 10000
    safety.set_timer(now)
    safety.set_aol_test_heartbeat(tick >= 65)
    frames = stream.frames(tick, lever=2 if tick in (65, 75) else 0, cruise=1)
    if tick % 2 == 0:
      frames.append(feedback_frame(calibration, tick // 2))
    for address, data, source in frames:
      assert safety.safety_rx_hook(libsafety_py.make_CANPacket(address, source, data))
    safety.safety_tick()
    safety.aol_set_host_request(3 if tick >= 65 else 0)
    if tick % 2 == 0:
      assert transmit(safety, priming.command(enabled=False))
    if 65 <= tick < 75:
      assert not (safety.aol_get_permission_mask() & 2), 'one physical pull is lateral only'
  assert safety.safety_config_valid() and safety.get_controls_allowed()
  assert safety.aol_get_permission_mask() == 3
  return safety, calibration, now


def transmit(safety, frame):
  address, data, bus = frame
  return bool(safety.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data)))


@pytest.mark.parametrize('bus', [0, 2])
@pytest.mark.parametrize('word', [1, 3, 7])
def test_actual_registered_priming_rate_absolute_bus_and_counter_bounds(bus, word):
  safety, calibration, now = warm(bus, word)
  codec = PedalCodec(calibration)
  assert transmit(safety, codec.command(enabled=False))
  for di in range(0, 73, 4):
    assert transmit(safety, codec.command(float(di), enabled=True))
  valid = codec.command(74., enabled=True)
  # At80kph original speed-profile max is75.78DI; this77DI request is
  # within+5 rate from72 but outside absolute native demand.
  too_high = PedalCodec(calibration)
  too_high.counter = valid[1][4] & 15
  assert not transmit(safety, too_high.command(77., enabled=True))
  assert transmit(safety, valid), 'rejected TX must not corrupt accepted counter/rate state'
  replay = valid
  assert not transmit(safety, replay)
  address, data, source = codec.command(74., enabled=True)
  assert not transmit(safety, (address, data, 2 - source))
  broken = bytearray(data)
  broken[5] ^= 1
  assert not transmit(safety, (address, bytes(broken), source))
  assert transmit(safety, (address, data, source))
  safety.set_timer(now + 500001)
  assert not transmit(safety, codec.command(74., enabled=True))
  assert transmit(safety, codec.command(enabled=False)), 'zero/disabled must remain available to withdraw/resynchronize'


@pytest.mark.parametrize('fault', ['state', 'channels', 'counter', 'short'])
def test_actual_feedback_fault_withdraws_then_needs_fresh_physical_rearm(fault):
  safety, calibration, now = warm(2, 1)
  codec = PedalCodec(calibration)
  assert transmit(safety, codec.command(enabled=False))
  assert transmit(safety, codec.command(0., enabled=True))
  counter = 45 if fault == 'counter' else 46
  frame = feedback_frame(calibration, counter, state=1 if fault == 'state' else 0,
                         bad_channel=fault == 'channels')
  if fault == 'short':
    frame = frame[0], frame[1][:-1], frame[2]
  safety.set_timer(now + 1000)
  address, data, bus = frame
  safety.safety_rx_hook(libsafety_py.make_CANPacket(address, bus, data))
  assert not safety.get_controls_allowed()
  assert not (safety.aol_get_permission_mask() & 2)
  assert not transmit(safety, codec.command(0., enabled=True))
  assert transmit(safety, codec.command(enabled=False))
