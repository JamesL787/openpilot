import math
from types import SimpleNamespace

import pytest

from cereal import messaging
from opendbc.car import Bus
from opendbc.car.honda.carstate import CarState, VSA_STALE_FRAMES
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.selfdrive.car.card import set_vsa_accel_fields


def _fpcs():
  return messaging.new_message('starpilotCarState').starpilotCarState


def test_card_copies_fields():
  fpcs = _fpcs()
  set_vsa_accel_fields(fpcs, SimpleNamespace(vsa_long_accel=-1.47, vsa_long_accel_valid=True))
  assert abs(fpcs.aEgoVsa + 1.47) < 1e-6
  assert fpcs.aEgoVsaValid


def test_card_defaults_without_sensor():
  for cs in (None, SimpleNamespace(), SimpleNamespace(vsa_long_accel=float('nan'), vsa_long_accel_valid=True)):
    fpcs = _fpcs()
    set_vsa_accel_fields(fpcs, cs)
    assert fpcs.aEgoVsa == 0.0
    assert not fpcs.aEgoVsaValid


class _FakeVl(dict):
  def __getitem__(self, key):
    raise AssertionError("must not lazily subscribe")


def _cs_stub():
  cs = SimpleNamespace(vsa_long_accel=float('nan'), vsa_long_accel_valid=False, vsa_frames_since_seen=VSA_STALE_FRAMES)
  cs.update = lambda cp: CarState.update_vsa_long_accel(cs, cp)
  return cs


def test_carstate_fresh_hold_and_stale():
  cs = _cs_stub()
  vl = {"KINEMATICS": {"LONG_ACCEL": -2.205}}
  cp = SimpleNamespace(vl=vl, vl_all={"KINEMATICS": {"LONG_ACCEL": [-2.205]}})
  cs.update(cp)
  assert cs.vsa_long_accel == pytest.approx(-2.205) and cs.vsa_long_accel_valid
  cp.vl_all["KINEMATICS"]["LONG_ACCEL"] = []
  for _ in range(VSA_STALE_FRAMES - 1):
    cs.update(cp)
  assert cs.vsa_long_accel_valid  # 0.09 s since the last frame: still valid, value held
  cs.update(cp)
  assert not cs.vsa_long_accel_valid and cs.vsa_long_accel == pytest.approx(-2.205)


def test_carstate_never_subscribes_missing_message():
  cs = _cs_stub()
  cs.update(SimpleNamespace(vl=_FakeVl(), vl_all={}))
  assert math.isnan(cs.vsa_long_accel) and not cs.vsa_long_accel_valid


def _parsers(car):
  CP = CarInterface.get_non_essential_params(car)
  return CarState.get_can_parsers(None, CP)


def test_kinematics_optional_on_non_yaw_car():
  pt = _parsers(CAR.HONDA_ACCORD)[Bus.pt]
  st = pt.message_states[0x94]
  assert st.ignore_alive  # never part of canValid


def test_yaw_rate_car_kinematics_unchanged():
  # Civic Bosch reads KINEMATICS through the lazy, alive-checked yaw path; we must not pre-register it as optional
  pt = _parsers(CAR.HONDA_CIVIC_BOSCH)[Bus.pt]
  assert 0x94 not in pt.message_states
