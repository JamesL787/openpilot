import math
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import car, log

from openpilot.selfdrive.controls.controlsd import CURVATURE_HOLD_PLAN_CAP, TURN_SHAPING_ALPHA, Controls

LateralControlMode = car.CarControl.Actuators.LateralControlMode


def _plan_right_turn(radius=10.0, arc_deg=60.0, tail_m=20.0):
  # positive y is a right turn in this curvature convention (see update_turn_hold)
  xs, ys = [], []
  n_arc = 60
  for k in range(n_arc + 1):
    a = math.radians(arc_deg) * k / n_arc
    xs.append(radius * math.sin(a))
    ys.append(radius * (1.0 - math.cos(a)))
  a = math.radians(arc_deg)
  for k in range(1, 21):
    xs.append(xs[n_arc] + tail_m * k / 20 * math.cos(a))
    ys.append(ys[n_arc] + tail_m * k / 20 * math.sin(a))
  return SimpleNamespace(position=SimpleNamespace(x=xs, y=ys), meta=SimpleNamespace(laneChangeState=log.LaneChangeState.off))


STRAIGHT = SimpleNamespace(position=SimpleNamespace(x=[i * 0.5 for i in range(80)], y=[0.0] * 80),
                           meta=SimpleNamespace(laneChangeState=log.LaneChangeState.off))
CC_ACTIVE = SimpleNamespace(latActive=True)


def _controls(shaping):
  c = Controls.__new__(Controls)
  c.CP = SimpleNamespace(brand="honda")
  c.sm = {"carOutput": SimpleNamespace(actuatorsOutput=SimpleNamespace(lateralControlMode=LateralControlMode.torque))}
  c.curvature = 0.0
  c.turn_hold_curvature = 0.0
  c.turn_hold_standstill_t = 0.0
  c.turn_hold_swept = 0.0
  c.turn_hold_handoff_t = 0.0
  c.turn_hold_done = False
  c.turn_blinker_swept = 0.0
  c.turn_floor = 0.0
  c.turn_release = 0.0
  c.turn_override_out = 0.0
  c.turn_hold_opposed_at_stop = False
  c.twitch_guard_remaining = 0.0
  c.turn_shaping = shaping
  return c


def _cs(v, right=True, pressed=False, torque=0.0):
  return SimpleNamespace(vEgo=v, aEgo=0.0, rightBlinker=right, leftBlinker=False, steeringPressed=pressed,
                         steeringTorque=torque, standstill=v < 0.1)


def _reversals(out):
  d = np.diff(out)
  d = d[np.abs(d) > 1e-6]
  return int(np.sum(np.sign(d[1:]) != np.sign(d[:-1])))


def test_standstill_prewind_against_an_opposing_model_does_not_flip_flop():
  # stopped, right blinker, plan shows the right turn, but the blind action reads a small LEFT
  # command past the opposite-release deadband: route 00000355 flipped hold/model every frame here
  plan = _plan_right_turn()
  outs = {}
  for shaping in (False, True):
    c = _controls(shaping)
    outs[shaping] = np.array([c.update_turn_hold(_cs(0.0), CC_ACTIVE, plan, -0.012) for _ in range(200)])
  assert _reversals(outs[False]) > 50
  assert _reversals(outs[True]) <= 1
  assert outs[True][-1] == pytest.approx(-0.012, abs=1e-4)


def test_standstill_still_resets_a_handoff_from_before_the_stop():
  # the turn4 case the every-frame reset exists for: a done latched while rolling must not block the pre-wind
  c = _controls(True)
  c.turn_hold_done = True
  plan = _plan_right_turn()
  for _ in range(200):
    out = c.update_turn_hold(_cs(0.0), CC_ACTIVE, plan, 0.0)
  assert out > 0.5 * CURVATURE_HOLD_PLAN_CAP


def _primed(shaping, hold):
  # a steady hold with the model at zero, shaping settled
  c = _controls(shaping)
  c.turn_hold_curvature = hold
  c.turn_hold_done = True  # no ratchet: isolate the release
  c.turn_floor = c.turn_override_out = hold
  return c


def test_opposite_release_glides_onto_the_model():
  model = [0.0] + [-0.05] * 300
  for shaping in (False, True):
    c = _primed(shaping, 0.1)
    out = np.array([c.update_turn_hold(_cs(3.0), CC_ACTIVE, STRAIGHT, m) for m in model])
    steps = np.abs(np.diff(out))
    if shaping:
      assert steps.max() <= 0.15 * TURN_SHAPING_ALPHA + 1e-9
      assert np.all(np.diff(out) <= 1e-12)
      assert out[-1] == pytest.approx(-0.05, abs=1e-4)
    else:
      assert steps.max() == pytest.approx(0.15, abs=1e-3)  # the hold decays 0.0005 in the first frame at 3 m/s


def test_model_rising_into_the_hold_does_not_overshoot_it():
  # handoff path: the model climbs through the hold; the shaped addition must not ride on top of it
  model = [0.0] + list(np.linspace(0.0, 0.15, 30)) + [0.15] * 100
  c = _primed(True, 0.1)
  out = np.array([c.update_turn_hold(_cs(3.0), CC_ACTIVE, STRAIGHT, m) for m in model])
  assert np.all(out <= np.maximum(0.1, np.array(model)) + 1e-9)
  assert out[-1] == pytest.approx(0.15)


def test_driver_confirmed_capture_still_snaps():
  # the wheel is already where the driver wound it; ramping the floor up would pull it back
  c = _controls(True)
  c.curvature = 0.08
  out = c.update_turn_hold(_cs(1.0, pressed=True, torque=-200.0), CC_ACTIVE, STRAIGHT, 0.0)
  assert out == pytest.approx(0.08)


def test_turn_lead_fades_in():
  plan = _plan_right_turn(radius=15.0, arc_deg=40.0)
  first = {}
  for shaping in (False, True):
    c = _controls(shaping)
    first[shaping] = c.update_turn_hold(_cs(5.0), CC_ACTIVE, plan, 0.0)
  assert first[False] > 0.02
  assert first[True] == pytest.approx(first[False] * TURN_SHAPING_ALPHA, rel=1e-6)


def test_shaping_off_is_a_pass_through_without_blinker():
  c = _controls(False)
  cs = SimpleNamespace(vEgo=5.0, aEgo=0.0, rightBlinker=False, leftBlinker=False, steeringPressed=False,
                       steeringTorque=0.0, standstill=False)
  assert c.update_turn_hold(cs, CC_ACTIVE, STRAIGHT, 0.013) == 0.013
