"""Nidec hybrids (Clarity) brake on COMPUTER_BRAKE_HYBRID and may report brake hold on BRAKE_HOLD_HYBRID_ALT."""
import pytest

from opendbc.can import CANPacker
from opendbc.car import Bus, gen_empty_fingerprint
from opendbc.car.honda import hondacan
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR, DBC, HondaFlags


def _brake_fields(dat):
  standard = (dat[0] << 2) | (dat[1] >> 6)
  hybrid = (dat[6] << 2) | (dat[7] >> 6)
  return standard, hybrid


@pytest.mark.parametrize("hybrid", [False, True])
def test_brake_command_uses_the_hybrid_field_on_a_hybrid(hybrid):
  CP = CarInterface.get_non_essential_params(CAR.HONDA_CLARITY)
  packer = CANPacker(DBC[CAR.HONDA_CLARITY][Bus.pt])
  stock_brake = {"CHIME": 0}
  _, dat, _ = hondacan.create_brake_command(packer, CanBus(CP), 200, True, True, False, False, stock_brake, hybrid=hybrid)
  assert _brake_fields(dat) == ((0, 200) if hybrid else (200, 0))


def _clarity_params(extra_addrs):
  fingerprint = gen_empty_fingerprint()
  initial = CarInterface.get_params(CAR.HONDA_CLARITY, fingerprint, [], False, False, False)
  for addr in (0x184, *extra_addrs):   # 0x184 marks a hybrid
    fingerprint[CanBus(initial).pt][addr] = 8
  return CarInterface.get_params(CAR.HONDA_CLARITY, fingerprint, [], False, False, False)


def test_alt_brake_hold_message_sets_its_flag():
  assert _clarity_params([0x223]).flags & HondaFlags.HYBRID_ALT_BRAKEHOLD
  assert not _clarity_params([]).flags & HondaFlags.HYBRID_ALT_BRAKEHOLD


def test_hybrid_brake_map_is_unchanged_below_half_and_reaches_the_stock_ceiling():
  from opendbc.car.honda.carcontroller import HYBRID_BRAKE_MAX, hybrid_brake_command
  for fraction in (0.0, 0.05, 0.2, 0.4, 0.49):
    assert hybrid_brake_command(fraction) == int(fraction * 256)
  assert hybrid_brake_command(0.5) == 128
  assert hybrid_brake_command(0.70) == HYBRID_BRAKE_MAX == 320
  assert hybrid_brake_command(4.0 / 4.8 - 0.13) >= 315   # -4.0 at 65 mph, after wind_brake
  assert hybrid_brake_command(1.0) == 320
  values = [hybrid_brake_command(f / 100) for f in range(101)]
  assert values == sorted(values)


def test_a_full_brake_request_reaches_320_on_a_hybrid_only():
  from opendbc.can import CANPacker
  from opendbc.car import structs
  from opendbc.car.honda.tests.test_nidec_interceptor import source_frames
  for hybrid in (True, False):
    fp = gen_empty_fingerprint()
    fp[0][0x201] = 6
    if hybrid:
      fp[0][0x184] = 8
    cp = CarInterface.get_params(CAR.HONDA_CLARITY, fp, [], False, False, False)
    assert bool(cp.flags & HondaFlags.HYBRID) == hybrid
    ci = CarInterface(cp)
    packer = CANPacker(DBC[CAR.HONDA_CLARITY][Bus.pt])
    for tick in range(50):
      ci.update([(1_000_000_000 + tick * 10_000_000, source_frames(cp, packer, tick))])
    command = structs.CarControl(enabled=True, longActive=True)
    command.actuators.accel = -4.0
    command.actuators.longControlState = "pid"
    brake = 0
    for tick in range(50, 250):
      _, frames = ci.apply(command.as_reader(), 1_000_000_000 + tick * 10_000_000)
      for f in frames:
        if f[0] == 0x1FA:
          brake = _brake_fields(f[1])[1 if hybrid else 0]
    assert (310 <= brake <= 320) if hybrid else (brake <= 255), (hybrid, brake)
