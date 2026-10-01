import math
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import car, log
from opendbc.car.honda.values import CAR as HONDA
import openpilot.selfdrive.controls.lib.clarity_yaw_trim as yaw_trim
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.tests.test_nrdr_eps_firmware_ff import _controller


class Car:
  """Steady-state car: turns `ratio` x the commanded curvature plus `bias`, one delivery lag later, through a
  first-order lag. Returns carState.yawRate (left-positive)."""

  def __init__(self, ratio=1.0, bias=0.0, lag_s=0.13, tau_s=0.15):
    self.ratio, self.bias = ratio, bias
    self.queue = [0.0] * int(round(lag_s / DT_CTRL))
    self.alpha = DT_CTRL / (tau_s + DT_CTRL)
    self.curvature = 0.0

  def step(self, commanded, v):
    self.queue.append(commanded)
    self.curvature += self.alpha * (self.ratio * self.queue.pop(0) + self.bias - self.curvature)
    return -self.curvature * v


def _turns(seconds, v, curvature, hold_s=4.0, ramp_s=1.0):
  """Alternating left and right steady turns with ramps between them, like city corners."""
  k = np.arange(int(seconds / DT_CTRL)) * DT_CTRL
  period = 2 * (hold_s + ramp_s)
  phase = k % period
  shape = np.interp(phase, [0, ramp_s, ramp_s + hold_s, 2 * ramp_s + hold_s, period],
                    [0, 1, 1, 0, 0]) * np.where((k // period) % 2 == 0, 1.0, -1.0)
  return curvature * shape


def _drive(trim, plant, requested, v, pressed=None, a_ego=0.0):
  gains = []
  for k, req in enumerate(requested):
    g = trim.update(req, plant.step(req * trim.gain(v), v), v, a_ego, bool(pressed[k]) if pressed is not None else False)
    gains.append(g)
  return np.array(gains)


@pytest.mark.parametrize("ratio", [0.95, 1.0, 1.04])
@pytest.mark.parametrize("v", [5.0, 12.0])
def test_learns_a_steady_ratio(ratio, v):
  trim = yaw_trim.YawCurvatureTrim(DT_CTRL)
  gains = _drive(trim, Car(ratio), _turns(240, v, 1.5 / v ** 2), v)
  assert gains[-1] == pytest.approx(1.0 / ratio, abs=0.006)
  assert np.all(np.abs(np.diff(gains)) < 0.001)  # slow: never a step


def test_a_bias_is_not_learned_as_a_ratio():
  # the car pulls left by 2e-4 1/m: in ~10 deg turns at 9-30 m/s that is left turns ~5% hot and rights ~5% cold,
  # as on routes 363-369
  v = 12.0
  trim = yaw_trim.YawCurvatureTrim(DT_CTRL)
  gains = _drive(trim, Car(1.0, bias=-2e-4), _turns(240, v, 0.6 / v ** 2), v)
  assert trim.ratios[yaw_trim.LEFT].max() > 1.03 and trim.ratios[yaw_trim.RIGHT].min() < 0.97
  assert gains[-1] == pytest.approx(1.0, abs=0.01)


def test_correction_is_bounded():
  v = 7.0
  trim = yaw_trim.YawCurvatureTrim(DT_CTRL)
  gains = _drive(trim, Car(0.8), _turns(600, v, 1.5 / v ** 2), v)
  assert gains.max() <= 1.0 + yaw_trim.GAIN_LIMIT + 1e-9


def test_turn_ins_and_exits_are_not_learned():
  # a car that lags a lot but delivers exactly: continuous weaving, never steady, so nothing may be learned
  v = 8.0
  trim = yaw_trim.YawCurvatureTrim(DT_CTRL)
  t = np.arange(int(120 / DT_CTRL)) * DT_CTRL
  gains = _drive(trim, Car(1.0, lag_s=0.25, tau_s=0.4), 0.03 * np.sin(2 * math.pi * 0.3 * t), v)
  assert np.all(gains == 1.0)


def test_nothing_is_learned_near_straight_or_slow_or_pressed():
  cases = [
    (12.0, _turns(120, 12.0, 0.0008), None),                     # below the curvature floor
    (3.0, _turns(120, 3.0, 0.05), None),                         # below walking-ish speed
    (7.0, _turns(120, 7.0, 0.03), np.ones(12000, bool)),         # driver steering throughout
  ]
  for v, requested, pressed in cases:
    trim = yaw_trim.YawCurvatureTrim(DT_CTRL)
    _drive(trim, Car(0.9), requested, v, pressed)
    assert np.all(trim.ratios == 1.0)


def test_a_dead_yaw_sensor_is_ignored():
  v = 7.0
  trim = yaw_trim.YawCurvatureTrim(DT_CTRL)
  for req in _turns(120, v, 0.03):
    trim.update(req, 0.0, v, 0.0, False)
  assert np.all(trim.ratios == 1.0)


def test_reset_keeps_what_was_learned():
  v = 7.0
  trim = yaw_trim.YawCurvatureTrim(DT_CTRL)
  _drive(trim, Car(0.95), _turns(120, v, 0.03), v)
  learned = trim.gain(v)
  trim.reset()
  assert learned > 1.02 and trim.gain(v) == learned and not trim.requested


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH])
def test_controller_scales_its_target_by_the_trim(monkeypatch, candidate):
  lac, VM, _ = _controller(monkeypatch, candidate, {"NrdrLatUseFirmwareVgr": "1"})
  CS = car.CarState.new_message()
  CS.vEgo = 10.0
  params = log.LiveParametersData.new_message()
  params.steerRatio, params.stiffnessFactor = 16.0, 1.0

  def target():
    # small enough that neither target reaches the one-frame angle-rate limit
    return lac.update(True, CS, VM, params, False, 0.0005, False, 0.2, None, None, SimpleNamespace())[1]

  base = target()
  lac.yaw_trim.ratios[:] = 1.0 / 1.05
  lac.prev_rate_limited_angle = 0.0
  assert target() == pytest.approx(1.05 * base, rel=0.01)


def test_the_trim_only_learns_while_engaged(monkeypatch):
  lac, VM, _ = _controller(monkeypatch, HONDA.HONDA_CIVIC_BOSCH)
  CS = car.CarState.new_message()
  CS.vEgo, CS.yawRate = 8.0, -0.9 * 0.02 * 8.0  # the car turns 10% less than asked
  params = log.LiveParametersData.new_message()
  params.steerRatio, params.stiffnessFactor = 16.0, 1.0
  for _ in range(3000):
    lac.update(False, CS, VM, params, False, 0.02, False, 0.2, None, None, SimpleNamespace())
  assert np.all(lac.yaw_trim.ratios == 1.0)
