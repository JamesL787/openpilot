"""The shadow driver yield (lib/honda_eps_driver_yield.py): what it reads as the driver, when it would give way, and that
the controller only logs it."""
from types import SimpleNamespace

import numpy as np
import pytest

import openpilot.selfdrive.controls.lib.honda_eps_driver_yield as Y
from opendbc.car.honda.values import CAR
from opendbc.car.structs import car
from openpilot.cereal import log
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _controller

DT = 0.01
A040 = Y.TORQUE_SENSOR_BY_CALIBRATION["crv_tla_a040"]


def hold(shadow, torque, error, seconds, rate=0.0, firmware_output=0.0):
  """Authority after each frame of a steady reading."""
  out = []
  for _ in range(int(round(seconds / DT))):
    shadow.measure(torque, firmware_output, rate)
    out.append(shadow.update(error, rate))
  return np.array(out)


def test_the_driver_estimate_takes_out_the_sensors_own_reading():
  shadow = Y.DriverYield(DT, A040)
  # nobody on the wheel: the offset, plus the EPS's share at a full command
  assert shadow.measure(A040.offset, 0.0, 0.0) == pytest.approx(0.0)
  assert shadow.measure(A040.offset + A040.eps_share * 3000.0, 3000.0, 0.0) == pytest.approx(0.0)
  # and a free wheel's inertia as the EPS spins it up at 500 deg/s^2
  for k in range(1, 40):
    driver = shadow.measure(A040.offset + A040.inertia * 500.0, 0.0, 500.0 * k * DT)
  assert driver == pytest.approx(0.0, abs=5.0)
  assert Y.torque_sensor("crv_tla_a220").offset == 90.0 and Y.torque_sensor("clarity_trw_a020") is Y.TORQUE_SENSOR_DEFAULT


def test_hands_off_and_a_resting_hand_keep_full_authority():
  shadow = Y.DriverYield(DT)
  rng = np.random.default_rng(0)
  for _ in range(3000):
    shadow.measure(float(rng.normal(0, 60)), 0.0, 0.0)
    assert shadow.update(3.0, 0.0) == 1.0
  # a hand resting against a wheel that is being turned: under the deadband plus the drag allowance
  assert hold(shadow, -(Y.DEADBAND + Y.DRAG * 60.0), 5.0, 3.0, rate=60.0).min() == 1.0
  assert shadow.evidence == 0.0


def test_a_hold_against_the_controller_gives_way_in_proportion():
  shadow = Y.DriverYield(DT)
  # the controller wants the wheel 2.5 deg to the left (+); the driver holds 1800 counts to the right
  a = hold(shadow, -1800.0, 2.5, 3.0)
  assert a[0] == 1.0 and np.all(np.diff(a) <= 0.0)
  assert np.argmax(a < 0.5) * DT == pytest.approx(0.25, abs=0.06)
  assert a[-1] == 0.0
  # a lighter hold settles part way and stays there: no cut, no cycle
  light = hold(Y.DriverYield(DT), -900.0, 2.5, 6.0)
  assert 0.25 < light[-1] < 0.75 and np.ptp(light[-200:]) < 0.01
  # authority comes back at RETURN_PER_S once the evidence has leaked away
  back = hold(shadow, 0.0, 2.5, 3.0)
  assert back[-1] == 1.0 and np.diff(back).max() == pytest.approx(Y.RETURN_PER_S * DT)
  assert 1.0 < np.argmax(back == 1.0) * DT < 2.5


def test_torque_with_the_controller_or_on_target_is_not_an_override():
  shadow = Y.DriverYield(DT)
  assert hold(shadow, 1800.0, 2.5, 3.0).min() == 1.0      # helping it turn
  assert hold(shadow, -1800.0, 0.3, 3.0).min() == 1.0     # on the target: nothing to oppose
  assert hold(shadow, 1800.0, -0.3, 3.0).min() == 1.0


def test_a_yank_yields_at_once_either_way():
  for torque, error in ((-(Y.YANK + 100.0), 2.5), (Y.YANK + 100.0, 2.5), (Y.YANK + 100.0, 0.0)):
    assert hold(Y.DriverYield(DT), torque, error, 0.02)[0] == 0.0
  # a fast wheel earns its drag allowance before it counts as a yank
  assert hold(Y.DriverYield(DT), Y.YANK + 100.0, 0.0, 0.02, rate=100.0)[0] == 1.0


def test_the_eps_pushing_a_free_wheel_does_not_look_like_the_driver():
  # a full command with nobody on the wheel reads ~390 counts against the push on the A040, on top of its 124 offset
  shadow = Y.DriverYield(DT, A040)
  reading = A040.offset + A040.eps_share * 3000.0
  assert hold(shadow, reading, -5.0, 5.0, firmware_output=3000.0).min() == 1.0
  # uncompensated, the same reading is a quarter of today's threshold and half way through this deadband
  raw = Y.DriverYield(DT, Y.TorqueSensor(0.0, 0.0, 0.0))
  raw.measure(reading, 3000.0, 0.0)
  assert raw.driver_torque == pytest.approx(514.0)


def _run(lac, VM, frames, torque, sent=None):
  CS = car.CarState.new_message(vEgo=19.0, steeringAngleDeg=-2.5, steeringTorque=torque)
  params = log.VehicleParameters.new_message(steerRatio=16.0, stiffnessFactor=1.0)
  outputs = []
  for _ in range(frames):
    if sent is not None:
      lac.update_sent_output(sent)
    outputs.append(lac.update(True, CS, VM, params, False, 0.0, False, 0.2, None, None, SimpleNamespace())[0])
  return outputs


def test_the_controller_logs_the_shadow_and_does_not_apply_it(monkeypatch):
  fw = b'39990-TLA,A040\x00\x00'
  lac, VM, _ = _controller(monkeypatch, fw=fw, candidate=CAR.HONDA_CRV_5G)
  quiet, VM2, _ = _controller(monkeypatch, fw=fw, candidate=CAR.HONDA_CRV_5G)
  assert lac.driver_yield.sensor is A040
  # the driver holds the wheel 2.5 deg right of a straight target with 1700 counts, under today's 2000 threshold
  held = _run(lac, VM, 300, -1700.0)
  state = lac.starpilot_lateral_state
  assert state.epsYieldAuthority == 0.0 and state.epsYieldEvidence > Y.YIELD_FULL
  assert state.epsDriverTorque == pytest.approx(lac.driver_yield.driver_torque) and state.epsDriverTorque < -1200.0
  msg = log.Event.new_message(starpilotLateralState=state)   # what controlsd publishes
  assert msg.starpilotLateralState.epsYieldAuthority == 0.0
  # the command is the one a controller with nobody on the wheel gives: the shadow changes nothing
  assert held == _run(quiet, VM2, 300, A040.offset)
  assert quiet.starpilot_lateral_state.epsYieldAuthority == 1.0
  # controlsd tells it what the car controller really sent; a cut command has no EPS share to take out
  cut, VM3, _ = _controller(monkeypatch, fw=fw, candidate=CAR.HONDA_CRV_5G)
  _run(cut, VM3, 50, A040.offset, sent=0.0)
  assert cut.starpilot_lateral_state.epsDriverTorque == pytest.approx(0.0, abs=1.0)
  # disengaged: the estimate keeps running, the yield starts over
  CS = car.CarState.new_message(vEgo=19.0, steeringTorque=-1700.0)
  lac.reset()
  lac.update(False, CS, VM, log.VehicleParameters.new_message(), False, 0.0, False, 0.2, None, None, SimpleNamespace())
  state = lac.starpilot_lateral_state
  assert state.epsYieldAuthority == 1.0 and state.epsYieldEvidence == 0.0 and state.epsDriverTorque == pytest.approx(-1700.0 - A040.offset)
