"""Clarity interceptor PCM-ACC test mode: hold the PCM in ACC while engaged, cancel it on disengage, stock-like HUD."""
import pytest

from opendbc.can import CANPacker, CANParser
from opendbc.car import Bus, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.honda import pcm_acc
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.tests.test_nidec_interceptor import factory, source_frames
from opendbc.car.honda.values import CAR, DBC

T0 = 1_000_000_000
DT = 10_000_000


class PcmAccPacker:
  """the interceptor tests' packer with POWERTRAIN_DATA ACC_STATUS set to the PCM state under test"""
  def __init__(self, identity, acc_status):
    self.packer = CANPacker(DBC[identity][Bus.pt])
    self.acc_status = acc_status

  def make_can_msg(self, name, bus, values):
    if name == "POWERTRAIN_DATA":
      values = {**values, "ACC_STATUS": self.acc_status}
    return self.packer.make_can_msg(name, bus, values)


def _drive(keep, acc_status, ticks=50):
  cp = factory(CAR.HONDA_CLARITY)
  ci = CarInterface(cp)
  ci.CC.keep_pcm_acc = ci.CS.keep_pcm_acc = keep
  packer = PcmAccPacker(CAR.HONDA_CLARITY, acc_status)
  for tick in range(ticks):
    cs = ci.update([(T0 + tick * DT, source_frames(cp, packer, tick))])
  return cp, ci, cs


def _apply(ci, enabled, long_active, accel, cancel=False, ticks=20):
  command = structs.CarControl(enabled=enabled, longActive=long_active)
  command.actuators.accel = accel
  command.actuators.longControlState = "pid"
  command.cruiseControl.cancel = cancel
  brake, hud = [], []
  for tick in range(ticks):
    _, frames = ci.apply(command.as_reader(), T0 + (60 + tick) * DT)
    brake += [f for f in frames if f[0] == 0x1FA]
    hud += [f for f in frames if f[0] == 0x30C]
  return brake, hud


def _hud_values(frame):
  parser = CANParser(DBC[CAR.HONDA_CLARITY][Bus.pt], [("ACC_HUD", 10)], 0)
  parser.update([(T0, [frame])])
  return parser.vl["ACC_HUD"]


def _cancel(frame):
  return bool((frame[1][2] >> 1) & 1)


def test_only_the_clarity_with_an_interceptor_qualifies():
  assert pcm_acc.qualified(factory(CAR.HONDA_CLARITY))
  assert not pcm_acc.qualified(factory(CAR.HONDA_CLARITY, sensor=False))
  assert not pcm_acc.qualified(factory(CAR.HONDA_CIVIC))


def test_hud_gas_follows_stock_braking_values():
  assert pcm_acc.hud_gas(0.0) == 38
  assert pcm_acc.hud_gas(1.5 * CV.MPH_TO_MS) == 38
  assert pcm_acc.hud_gas(6.5 * CV.MPH_TO_MS) == 62
  assert pcm_acc.hud_gas(60 * CV.MPH_TO_MS) == 98
  values = [pcm_acc.hud_gas(v * CV.MPH_TO_MS) for v in range(0, 70)]
  assert values == sorted(values) and max(values) <= 198


@pytest.mark.parametrize("keep", [False, True])
def test_pcm_acc_is_hidden_from_openpilot_only_in_the_mode(keep):
  _, ci, cs = _drive(keep, acc_status=1)
  assert ci.CS.pcm_acc_active
  assert cs.cruiseState.enabled == (not keep)


def test_mode_keeps_pcm_acc_while_engaged_with_stock_braking_hud():
  _, ci, cs = _drive(True, acc_status=1)
  brake, hud = _apply(ci, enabled=True, long_active=True, accel=-1.0)
  assert brake and not any(_cancel(f) for f in brake)
  values = _hud_values(hud[-1])
  assert values["PCM_SPEED"] == 0
  assert values["PCM_GAS"] == pcm_acc.hud_gas(cs.vEgo)
  assert values["PCM_GAS"] > 0


def test_mode_cancels_pcm_acc_once_openpilot_disengages():
  _, ci, _ = _drive(True, acc_status=1)
  brake, hud = _apply(ci, enabled=False, long_active=False, accel=0.0)
  assert brake and all(_cancel(f) for f in brake)
  assert _hud_values(hud[-1])["PCM_GAS"] == 0


def test_mode_sends_no_cancel_when_the_pcm_is_not_in_acc():
  _, ci, _ = _drive(True, acc_status=0)
  brake, _ = _apply(ci, enabled=False, long_active=False, accel=0.0)
  assert brake and not any(_cancel(f) for f in brake)


def test_driver_gas_override_keeps_pcm_acc_and_zeroes_hud_gas():
  _, ci, _ = _drive(True, acc_status=1)
  brake, hud = _apply(ci, enabled=True, long_active=False, accel=0.0)
  assert brake and not any(_cancel(f) for f in brake)
  assert _hud_values(hud[-1])["PCM_GAS"] == 0


def test_without_the_mode_nothing_changes():
  _, ci, cs = _drive(False, acc_status=1)
  brake, hud = _apply(ci, enabled=True, long_active=True, accel=-1.0, cancel=cs.cruiseState.enabled)
  assert brake and all(_cancel(f) for f in brake)
  values = _hud_values(hud[-1])
  assert values["PCM_GAS"] == 0 and values["PCM_SPEED"] == 0
