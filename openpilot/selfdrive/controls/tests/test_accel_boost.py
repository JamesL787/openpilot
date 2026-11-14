from types import SimpleNamespace

import pytest

from openpilot.cereal import log
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.accel_boost import (
  ACCEL_BOOST_INITIAL, ACCEL_BOOST_MAX, ACCEL_BOOST_MIN_SPEED, ACCEL_BOOST_PER_OVERRIDE, AccelBoost,
)

V = 17.0


Personality = log.LongitudinalPersonality


def make_sm(enabled=True, gas=False, v_ego=V, exp=True, personality=Personality.standard):
  return {'selfdriveState': SimpleNamespace(enabled=enabled, experimentalMode=exp, personality=personality),
          'carState': SimpleNamespace(gasPressed=gas, vEgo=v_ego)}


def run(b, seconds, e2e=0.0, mpc=1.0, a_cruise=1.0, **kw):
  out = None
  for _ in range(round(seconds / DT_MDL)):
    out = b.update(make_sm(**kw), e2e, mpc, a_cruise)
  return out


def test_one_press_adds_per_override_and_stops():
  b = AccelBoost()
  run(b, 1.0, gas=False)
  run(b, 5.0, gas=True)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_PER_OVERRIDE)


def test_presses_accumulate_to_max_and_value_holds_after_release():
  b = AccelBoost()
  for _ in range(6):
    run(b, 0.5, gas=False)
    run(b, 5.0, gas=True)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_MAX)
  run(b, 2.0, gas=False)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_MAX)


def test_eligibility_is_latched_before_the_press():
  b = AccelBoost()
  run(b, 1.0, gas=False, mpc=0.0, a_cruise=0.0)  # not model limited
  run(b, 2.0, gas=True)  # limited during the press, but not at press start
  assert b.total_boost == 0.0
  run(b, 1.0, gas=False)
  run(b, 5.0, gas=True, mpc=0.0)  # press-time lead plan changes cannot revoke it
  assert b.total_boost == pytest.approx(ACCEL_BOOST_PER_OVERRIDE)


def test_needs_margin():
  b = AccelBoost()
  run(b, 1.0, e2e=0.95, mpc=1.0)  # within the 0.1 margin
  run(b, 2.0, e2e=0.95, mpc=1.0, gas=True)
  assert b.total_boost == 0.0


def test_press_counts_outside_experimental_mode():
  # commaai/openpilot#39097 dropped the Experimental Mode check; the planners only use the e2e target in Experimental Mode
  b = AccelBoost()
  run(b, 1.0, exp=False)
  run(b, 2.0, exp=False, gas=True)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_PER_OVERRIDE)


def test_aggressive_starts_at_initial_boost_and_keeps_it():
  # commaai/openpilot#39229
  b = AccelBoost()
  run(b, 0.1, personality=Personality.aggressive)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_INITIAL)
  run(b, 0.1, enabled=False, personality=Personality.aggressive)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_INITIAL)
  run(b, 1.0, personality=Personality.aggressive)
  run(b, 5.0, gas=True, personality=Personality.aggressive)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_INITIAL + ACCEL_BOOST_PER_OVERRIDE)
  run(b, 0.1, personality=Personality.standard)
  assert b.total_boost == pytest.approx(ACCEL_BOOST_INITIAL + ACCEL_BOOST_PER_OVERRIDE)
  run(b, 0.1, enabled=False, personality=Personality.standard)
  assert b.total_boost == 0.0


def test_speed_ramp_scales_buildup_and_output():
  b = AccelBoost()
  run(b, 1.0, v_ego=ACCEL_BOOST_MIN_SPEED)
  run(b, 2.0, v_ego=ACCEL_BOOST_MIN_SPEED, gas=True)
  assert b.total_boost == 0.0  # no buildup at the minimum speed
  b.total_boost = 0.2
  assert b.update(make_sm(v_ego=ACCEL_BOOST_MIN_SPEED), 0.0, 1.0, 1.0) == 0.0
  assert b.update(make_sm(v_ego=1.5 * ACCEL_BOOST_MIN_SPEED), 0.0, 1.0, 1.0) == pytest.approx(0.1)
  assert b.update(make_sm(v_ego=2 * ACCEL_BOOST_MIN_SPEED), 0.0, 1.0, 1.0) == pytest.approx(0.2)


def test_clears_when_disabled():
  b = AccelBoost()
  run(b, 1.0)
  run(b, 5.0, gas=True)
  assert b.total_boost > 0.0
  run(b, 0.1, enabled=False)
  assert b.total_boost == 0.0 and not b.boost_eligible


def test_output_shape():
  b = AccelBoost()
  b.total_boost = 0.2
  def f(e2e):
    return b.update(make_sm(), e2e, 9.0, 9.0)

  assert f(-1.5) == -1.5  # at or below -1.0: no boost
  assert f(-1.0) == pytest.approx(-1.0)
  assert f(-0.5) == pytest.approx(-0.3)
  assert f(0.5) == pytest.approx(0.7)
  assert f(-0.75) == pytest.approx(-0.75 + 0.1)
  assert f(6.0) == 6.0
