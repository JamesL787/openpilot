"""Tests for the NRDR lateral stiction output stage."""
import math
import random

import pytest

from openpilot.selfdrive.controls.lib.nrdr_lat_stiction import LatStiction

DT = 0.01
STEER_MAX = 1.0
V = 25.0


def make():
  return LatStiction(DT, STEER_MAX)


def settle_into_hold(stiction, torque=0.30, n=120):
  out = 0.0
  for _ in range(n):
    out = stiction.update(True, V, 0.0, 0.0, 0.0, torque, False, False, False)
  return out


class TestLatStiction:
  def test_enters_hold_and_kills_dither(self):
    stiction = make()
    settle_into_hold(stiction)
    assert stiction.holding
    rng = random.Random(0)
    outs = []
    for _ in range(500):
      live = 0.30 + rng.gauss(0.0, 0.05)
      error = rng.gauss(0.0, 0.05)
      outs.append(stiction.update(True, V, error, 0.0, 0.0, live, False, False, False))
    assert stiction.holding
    assert max(outs) - min(outs) < 0.01

  def test_breakaway_on_error(self):
    stiction = make()
    settle_into_hold(stiction)
    for i in range(200):
      error = min(i * 0.02, 2.0)
      stiction.update(True, V, error, 0.0, 0.0, 0.5, False, False, False)
      if not stiction.holding:
        break
    assert not stiction.holding
    assert error < 3.0 * stiction.E_HI_V[-1]

  def test_never_holds_while_plan_turns(self):
    stiction = make()
    for _ in range(300):
      stiction.update(True, V, 0.0, 5.0, 2.0, 0.4, False, False, False)
    assert not stiction.holding

  def test_drift_budget_escapes_slow_creep(self):
    stiction = make()
    settle_into_hold(stiction)
    elapsed = 0.0
    for _ in range(1000):
      stiction.update(True, V, 0.25, 0.0, 0.0, 0.4, False, False, False)
      elapsed += DT
      if not stiction.holding:
        break
    assert not stiction.holding
    assert elapsed < 2.5

  def test_micro_integrator_winds_toward_error(self):
    stiction = make()
    settle_into_hold(stiction, torque=0.30)
    initial = stiction.hold_torque
    for _ in range(50):
      stiction.update(True, V, 0.2, 0.0, 0.0, 0.30, False, False, False)
    assert stiction.hold_torque > initial
    assert stiction.hold_torque - initial == pytest.approx(stiction.KI_HOLD * 0.2 * 0.5, abs=0.002)

  def test_transitions_are_bumpless(self):
    stiction = make()
    outs = []
    rng = random.Random(1)
    for i in range(3000):
      cycle = i % 600
      triangle = cycle / 300.0 if cycle < 300 else (600 - cycle) / 300.0
      error = 1.5 * triangle
      live = 0.30 + 0.25 * triangle + rng.gauss(0.0, 0.01)
      outs.append(stiction.update(True, V, error, 0.0, 0.0, live, False, False, False))
    max_step = max(abs(b - a) for a, b in zip(outs, outs[1:], strict=False))
    assert max_step < 0.30 / (stiction.XFADE_S / DT) + 0.05

  def test_no_chatter_on_borderline_error(self):
    stiction = make()
    settle_into_hold(stiction)
    transitions = 0
    previous = stiction.holding
    for i in range(2000):
      error = 0.4 + 0.05 * math.sin(i * DT * 8.0)
      stiction.update(True, V, error, 0.0, 0.0, 0.4, False, False, False)
      if stiction.holding != previous:
        transitions += 1
        previous = stiction.holding
    assert transitions < 12

  def test_bypasses_are_exact_passthrough(self):
    for kwargs in (dict(pressed=True), dict(lane=True), dict(sat=True), dict(v=2.0), dict(act=False)):
      stiction = make()
      settle_into_hold(stiction)
      outs = []
      for i in range(60):
        live = 0.5 + 0.1 * math.sin(i * 0.3)
        outs.append(stiction.update(kwargs.get("act", True), kwargs.get("v", V), 0.0, 0.0, 0.0,
                                    live, kwargs.get("pressed", False), kwargs.get("lane", False), kwargs.get("sat", False)))
      assert outs[-1] == pytest.approx(0.5 + 0.1 * math.sin(59 * 0.3), abs=1e-9)
      assert not stiction.holding

  def test_hold_torque_clamped(self):
    stiction = make()
    settle_into_hold(stiction, torque=0.95)
    for _ in range(5000):
      stiction.update(True, V, 0.3, 0.0, 0.0, 0.95, False, False, False)
      if not stiction.holding:
        settle_into_hold(stiction, torque=0.95)
    assert abs(stiction.hold_torque) <= STEER_MAX + 1e-9
