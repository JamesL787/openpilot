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


STOPPED = {"ENGINE_DATA": {"XMISSION_SPEED": 0},
           "WHEEL_SPEEDS": {"WHEEL_SPEED_FL": 0, "WHEEL_SPEED_FR": 0, "WHEEL_SPEED_RL": 0, "WHEEL_SPEED_RR": 0}}


class PcmAccPacker:
  """the interceptor tests' packer with POWERTRAIN_DATA ACC_STATUS set to the PCM state under test"""
  def __init__(self, identity, acc_status, overrides=None):
    self.packer = CANPacker(DBC[identity][Bus.pt])
    self.overrides = {**(overrides or {}), "POWERTRAIN_DATA": {"ACC_STATUS": acc_status}}

  def make_can_msg(self, name, bus, values):
    return self.packer.make_can_msg(name, bus, {**values, **self.overrides.get(name, {})})


def _drive(keep, acc_status, ticks=50, overrides=None):
  cp = factory(CAR.HONDA_CLARITY)
  ci = CarInterface(cp)
  ci.CC.keep_pcm_acc = ci.CS.keep_pcm_acc = keep
  packer = PcmAccPacker(CAR.HONDA_CLARITY, acc_status, overrides)
  for tick in range(ticks):
    cs = ci.update([(T0 + tick * DT, source_frames(cp, packer, tick))])
  return cp, ci, cs


def _apply(ci, enabled, long_active, accel, cancel=False, ticks=20, state="pid"):
  command = structs.CarControl(enabled=enabled, longActive=long_active)
  command.actuators.accel = accel
  command.actuators.longControlState = state
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


def _brake(frame):
  # COMPUTER_BRAKE, or COMPUTER_BRAKE_HYBRID on a car fingerprinted as a hybrid
  return max((frame[1][0] << 2) | (frame[1][1] >> 6), (frame[1][6] << 2) | (frame[1][7] >> 6))


@pytest.mark.parametrize("keep", [False, True])
def test_standstill_hold_floor_only_in_the_mode(keep):
  _, ci, cs = _drive(keep, acc_status=1, overrides=STOPPED)
  assert cs.standstill
  brake, _ = _apply(ci, enabled=True, long_active=True, accel=-0.15, state="stopping", ticks=100)
  floor = int((pcm_acc.STANDSTILL_HOLD_BRAKE - 0.02) * 256)  # less the 0.01 brake hysteresis gap and wind term
  if keep:
    assert _brake(brake[-1]) >= floor
  else:
    assert _brake(brake[-1]) < floor


def test_standstill_hold_latches_through_standstill_flicker():
  hold, floor = pcm_acc.StandstillHold(), pcm_acc.STANDSTILL_HOLD_BRAKE
  assert hold.update(0.1, False, True) == 0.1          # still rolling while stopping: no hold yet
  assert hold.update(0.1, True, True) == floor         # stopped
  for standstill in (False, True, False, False, True):  # carState.standstill flickers at ~2 Hz while stopped
    assert hold.update(0.1, standstill, True) == floor
  assert hold.update(0.6, False, True) == 0.6          # a larger request still wins
  assert hold.update(0.1, False, False) == 0.1         # leaving the stopping state releases it
  assert hold.update(0.1, False, True) == 0.1          # and it waits for the next stop


def test_hold_survives_a_standstill_flicker_on_the_real_interface():
  cp, ci, _ = _drive(True, acc_status=1, overrides=STOPPED)
  _apply(ci, enabled=True, long_active=True, accel=-0.1, state="stopping", ticks=100)
  rolling = PcmAccPacker(CAR.HONDA_CLARITY, 1, {**STOPPED, "ENGINE_DATA": {"XMISSION_SPEED": 0.1}})
  cs = ci.update([(T0 + 200 * DT, source_frames(cp, rolling, 200))])
  assert not cs.standstill
  brake, _ = _apply(ci, enabled=True, long_active=True, accel=-0.1, state="stopping", ticks=10)
  assert min(_brake(f) for f in brake) >= int((pcm_acc.STANDSTILL_HOLD_BRAKE - 0.02) * 256)


def test_gas_override_clears_the_hold():
  _, ci, _ = _drive(True, acc_status=1, overrides=STOPPED)
  _apply(ci, enabled=True, long_active=True, accel=-0.1, state="stopping", ticks=100)
  assert ci.CC.standstill_hold.latched
  _apply(ci, enabled=True, long_active=False, accel=0.0, ticks=2)
  assert not ci.CC.standstill_hold.latched


def test_launch_releases_the_hold():
  _, ci, _ = _drive(True, acc_status=1, overrides=STOPPED)
  _apply(ci, enabled=True, long_active=True, accel=-0.15, state="stopping", ticks=100)
  brake, _ = _apply(ci, enabled=True, long_active=True, accel=1.0, state="starting", ticks=4)
  assert _brake(brake[-1]) == 0


@pytest.mark.parametrize("identity, sensor, expected", [(CAR.HONDA_CLARITY, True, True), (CAR.HONDA_CLARITY, False, False),
                                                        (CAR.HONDA_CIVIC, True, False)])
def test_on_by_default_only_for_a_clarity_with_an_interceptor(identity, sensor, expected):
  ci = CarInterface(factory(identity, sensor=sensor))
  assert ci.CC.keep_pcm_acc == expected and ci.CS.keep_pcm_acc == expected


def test_passive_reports_the_pcm_cruise_state():
  cp, ci, cs = _drive(True, acc_status=1)
  assert not cs.cruiseState.enabled
  cp.passive = True
  packer = PcmAccPacker(CAR.HONDA_CLARITY, 1)
  cs = ci.update([(T0 + 50 * DT, source_frames(cp, packer, 50))])
  assert cs.cruiseState.enabled
