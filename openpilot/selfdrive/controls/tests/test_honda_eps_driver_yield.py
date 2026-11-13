"""The shadow driver yield (lib/honda_eps_driver_yield.py): what it reads as the driver, when it would give way, and that
the controller only logs it."""
import math
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
BARE = Y.TorqueSensor(0.0, 0.0, 0.0, 0.0)   # the reading taken as the driver, for the tests of the yield itself


def hold(shadow, torque, error, seconds, rate=0.0):
  """Authority after each frame of a steady reading."""
  out = []
  for _ in range(int(round(seconds / DT))):
    shadow.measure(torque, 0.0, rate)
    out.append(shadow.update(error, rate))
  return np.array(out)


def free_wheel(sensor, rates):
  """What the bar reads, frame by frame, as something below it takes a wheel nobody holds through these rates."""
  angle, stop, prev = 0.0, 0.0, rates[0]
  out = []
  for rate in rates:
    stop = min(max(stop + rate * DT / Y.FRICTION_WIDTH, -1.0), 1.0)
    angle += rate * DT
    out.append((sensor.offset + sensor.inertia * (rate - prev) / DT + sensor.friction * stop + sensor.imbalance * math.sin(math.radians(angle)), angle, rate))
    prev = rate
  return out


def test_the_driver_estimate_takes_out_what_moving_the_wheel_puts_on_the_bar():
  # nobody on the wheel, wheel still and straight: the offset
  shadow = Y.DriverYield(DT, A040)
  for _ in range(50):
    driver = shadow.measure(A040.offset, 0.0, 0.0)
  assert driver == pytest.approx(0.0)
  # the wheel was last turned left (+) and is held at 40 deg: the column's friction and the wheel's imbalance stay on the bar
  for reading, angle, rate in free_wheel(A040, [20.0] * 200 + [0.0] * 100):
    driver = shadow.measure(reading, angle, rate)
  assert reading == pytest.approx(A040.offset + A040.friction + A040.imbalance * math.sin(math.radians(40.0)))
  assert abs(reading - A040.offset) > 190 and driver == pytest.approx(0.0, abs=1.0)
  assert Y.torque_sensor("clarity_trw_a020").offset == -54.0 and Y.torque_sensor("rdx_tjb_a220") is Y.TORQUE_SENSOR_DEFAULT


def test_the_eps_jerking_a_free_wheel_does_not_look_like_the_driver():
  # the EPS takes a free wheel to 200 deg/s in 0.1 s and stops it as fast: 2000 deg/s^2 either way
  rates = [0.0] * 30 + list(np.linspace(0.0, 200.0, 11)) + [200.0] * 20 + list(np.linspace(200.0, 0.0, 11)) + [0.0] * 60
  frames = free_wheel(A040, rates)
  shadow, bare = Y.DriverYield(DT, A040), Y.DriverYield(DT, Y.TorqueSensor(A040.offset, 0.0, 0.0, 0.0))
  driver, raw, authority = [], [], []
  for reading, angle, rate in frames:
    driver.append(shadow.measure(reading, angle, rate))
    raw.append(bare.measure(reading, angle, rate))
    authority.append(shadow.update(-8.0, rate))   # the controller is turning it right at the time: the spin-up reads against it
  # the bar reads over 500 counts with nobody there; the estimate leaves under a third of that, for under 0.1 s
  assert max(np.abs(raw)) > 500.0
  assert max(np.abs(driver)) < 0.33 * max(np.abs(raw)) and np.sum(np.abs(driver) > 100.0) < 10
  assert min(authority) == 1.0


def test_hands_off_and_a_resting_hand_keep_full_authority():
  shadow = Y.DriverYield(DT, BARE)
  rng = np.random.default_rng(0)
  for _ in range(3000):
    shadow.measure(float(rng.normal(0, 60)), 0.0, 0.0)
    assert shadow.update(3.0, 0.0) == 1.0
  # a hand carried along by a wheel that is being turned: under the deadband plus the drag allowance
  assert hold(shadow, -(Y.DEADBAND + Y.DRAG * 60.0), 5.0, 3.0, rate=60.0).min() == 1.0
  assert shadow.evidence == 0.0


def test_a_hold_against_the_controller_gives_way_in_proportion():
  shadow = Y.DriverYield(DT, BARE)
  hold(shadow, 0.0, 2.5, 0.5)
  # the controller wants the wheel 2.5 deg to the left (+); the driver holds 1800 counts to the right
  a = hold(shadow, -1800.0, 2.5, 3.0)
  assert a[0] == 1.0 and np.all(np.diff(a) <= 0.0)
  assert np.argmax(a < 0.5) * DT == pytest.approx(0.30, abs=0.06)
  assert a[-1] == 0.0
  # a lighter hold settles part way and stays there: no cut, no cycle
  light = hold(Y.DriverYield(DT, BARE), -900.0, 2.5, 6.0)
  assert 0.25 < light[-1] < 0.75 and np.ptp(light[-200:]) < 0.01
  # authority comes back at RETURN_PER_S once the evidence has leaked away
  back = hold(shadow, 0.0, 2.5, 3.0)
  assert back[-1] == 1.0 and np.diff(back).max() == pytest.approx(Y.RETURN_PER_S * DT)
  assert 1.0 < np.argmax(back == 1.0) * DT < 2.5


def test_torque_with_the_controller_or_on_target_is_not_an_override():
  shadow = Y.DriverYield(DT, BARE)
  assert hold(shadow, 1800.0, 2.5, 3.0).min() == 1.0      # helping it turn
  assert hold(shadow, -1800.0, 0.3, 3.0).min() == 1.0     # on the target: nothing to oppose
  assert hold(shadow, 1800.0, -0.3, 3.0).min() == 1.0


def test_a_yank_yields_within_a_tenth_of_a_second_either_way():
  for torque, error in ((-(Y.YANK + 600.0), 2.5), (Y.YANK + 600.0, 2.5), (Y.YANK + 600.0, 0.0)):
    shadow = Y.DriverYield(DT, BARE)
    hold(shadow, 0.0, error, 0.5)
    a = hold(shadow, torque, error, 0.2)
    assert a[0] == 1.0 and np.argmax(a == 0.0) * DT <= 0.08   # the reading's filter and its one frame
  # a fast wheel earns its drag allowance before it counts as a yank
  assert hold(Y.DriverYield(DT, BARE), Y.YANK + 100.0, 0.0, 0.2, rate=100.0).min() == 1.0


def test_a_reset_starts_the_yield_over_and_leaves_the_wheel_alone():
  shadow = Y.DriverYield(DT, A040)
  for reading, angle, rate in free_wheel(A040, [20.0] * 50 + [0.0] * 50):
    shadow.measure(reading - 1500.0, angle, rate)
    shadow.update(2.5, rate)
  assert shadow.authority == 0.0 and shadow.memory == pytest.approx(1.0, abs=0.01)
  shadow.reset()
  assert (shadow.authority, shadow.evidence) == (1.0, 0.0) and shadow.memory == pytest.approx(1.0, abs=0.01)


def _run(lac, VM, frames, torque):
  CS = car.CarState.new_message(vEgo=19.0, steeringAngleDeg=-2.5, steeringTorque=torque)
  params = log.VehicleParameters.new_message(steerRatio=16.0, stiffnessFactor=1.0)
  return [lac.update(True, CS, VM, params, False, 0.0, False, 0.2, None, None, SimpleNamespace())[0] for _ in range(frames)]


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
  assert quiet.starpilot_lateral_state.epsDriverTorque == pytest.approx(0.0, abs=15.0)   # the wheel's imbalance at 2.5 deg
  # disengaged: the estimate keeps running, the yield starts over
  CS = car.CarState.new_message(vEgo=19.0, steeringAngleDeg=-2.5, steeringTorque=-1700.0)
  lac.reset()
  lac.update(False, CS, VM, log.VehicleParameters.new_message(), False, 0.0, False, 0.2, None, None, SimpleNamespace())
  state = lac.starpilot_lateral_state
  assert state.epsYieldAuthority == 1.0 and state.epsYieldEvidence == 0.0
  assert state.epsDriverTorque == pytest.approx(-1700.0 - A040.offset, abs=15.0)
