import pytest

from openpilot.selfdrive.controls.lib.accel_boost import (
  ACCEL_BOOST_MAX, ACCEL_BOOST_MIN_SPEED, ACCEL_BOOST_PER_OVERRIDE, AccelBoost,
)

DT = 0.05
V = 17.0


def run(b, seconds, **kw):
  for _ in range(round(seconds / DT)):
    b.update(**kw)


def test_one_press_adds_per_override_and_stops():
  b = AccelBoost(DT)
  run(b, 5.0, enabled=True, gas_pressed=True, v_ego=V, model_limited=True)
  assert b.value == pytest.approx(ACCEL_BOOST_PER_OVERRIDE)


def test_presses_accumulate_to_max_and_value_holds_after_release():
  b = AccelBoost(DT)
  for _ in range(6):
    run(b, 5.0, enabled=True, gas_pressed=True, v_ego=V, model_limited=True)
    run(b, 0.5, enabled=True, gas_pressed=False, v_ego=V, model_limited=True)
  assert b.value == pytest.approx(ACCEL_BOOST_MAX)


def test_no_boost_unless_model_limited_or_gas():
  b = AccelBoost(DT)
  run(b, 2.0, enabled=True, gas_pressed=True, v_ego=V, model_limited=False)
  run(b, 2.0, enabled=True, gas_pressed=False, v_ego=V, model_limited=True)
  assert b.value == 0.0


def test_decays_below_min_speed_and_clears_when_disabled():
  b = AccelBoost(DT)
  run(b, 5.0, enabled=True, gas_pressed=True, v_ego=V, model_limited=True)
  run(b, 0.2, enabled=True, gas_pressed=False, v_ego=ACCEL_BOOST_MIN_SPEED - 0.1, model_limited=False)
  assert 0.0 < b.value < ACCEL_BOOST_PER_OVERRIDE
  run(b, 0.1, enabled=False, gas_pressed=False, v_ego=V, model_limited=False)
  assert b.value == 0.0


def test_apply_shape():
  b = AccelBoost(DT)
  b.value = 0.2
  assert b.apply(-1.5) == -1.5  # at or below -1.0: no boost
  assert b.apply(-1.0) == pytest.approx(-1.0)
  assert b.apply(-0.5) == pytest.approx(-0.3)  # full boost from -0.5 up
  assert b.apply(0.5) == pytest.approx(0.7)
  assert b.apply(-0.75) == pytest.approx(-0.75 + 0.1)  # linear between -1.0 and -0.5
  assert b.apply(6.0) == 6.0  # beyond the table: no boost
