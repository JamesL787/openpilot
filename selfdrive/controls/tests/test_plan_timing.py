"""tools/lateral/plan_timing.py's distance alignment: the same steering laid on the same road is found at the same
shift whatever speed the car drove it at, and the shift and the speed mismatch come out in seconds."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'tools', 'lateral'))
import plan_timing as P

V_PLAN = 10.0


def road(s):
  """The road's curvature by distance along it, 1/m: smooth, and not periodic over the plan's 15 m."""
  return 0.010 * np.sin(2 * np.pi * s / 40.0) + 0.006 * np.sin(2 * np.pi * s / 17.0 + 0.5)


def drive(v_car, late_m):
  """A car at v_car m/s whose steering is late_m metres behind the plan, and the plans made along the way (at V_PLAN)."""
  frames = np.arange(5.0, 40.0, 0.05)
  yt = np.arange(0.0, 60.0, 0.01)
  dy = v_car * yt
  k = road(dy - late_m)
  start = v_car * frames
  plan = road(start[:, None] + V_PLAN * P.T_IDX[None, :])
  vplan = np.full_like(plan, V_PLAN)
  return frames, plan, vplan, yt, k, dy


def test_the_distance_shift_is_the_lateness_in_metres_at_the_frames_speed():
  tf, plan, vplan, yt, k, dy = drive(v_car=8.0, late_m=2.4)
  shift, shift_gain, gain = P.fit_shift(tf, plan, yt, k, vplan, np.full(len(tf), 8.0), dy)
  assert shift == pytest.approx(2.4 / 8.0, abs=0.011)
  assert shift_gain == pytest.approx(2.4 / 8.0, abs=0.011) and gain == pytest.approx(1.0, abs=0.02)


def test_a_slow_car_that_steers_on_time_is_on_distance_but_late_in_time():
  tf, plan, vplan, yt, k, dy = drive(v_car=8.0, late_m=0.0)
  assert P.fit_shift(tf, plan, yt, k, vplan, np.full(len(tf), 8.0), dy)[0] == pytest.approx(0.0, abs=0.011)
  assert P.fit_shift(tf, plan, yt, k)[0] > 0.1  # the time alignment reads the speed as lateness of the steering


def test_a_car_at_the_plans_speed_gives_the_same_answer_both_ways():
  tf, plan, vplan, yt, k, dy = drive(v_car=V_PLAN, late_m=1.5)
  time_shift = P.fit_shift(tf, plan, yt, k)[0]
  assert time_shift == pytest.approx(0.15, abs=0.011)
  assert P.fit_shift(tf, plan, yt, k, vplan, np.full(len(tf), V_PLAN), dy)[0] == pytest.approx(time_shift, abs=0.011)


def test_the_speed_term_is_the_extra_time_the_car_takes_over_the_plans_distance():
  tf, _, vplan, yt, _, dy = drive(v_car=8.0, late_m=0.0)
  lo, hi = P.T_SPEED
  # the plan covers (hi - lo) * 10 m; at 8 m/s that takes (hi - lo) * 10 / 8 s
  assert np.median(P.speed_term(tf, vplan, yt, dy)) == pytest.approx((hi - lo) * (V_PLAN / 8.0 - 1.0), abs=0.005)
  tf, _, vplan, yt, _, dy = drive(v_car=V_PLAN, late_m=0.0)
  assert np.median(P.speed_term(tf, vplan, yt, dy)) == pytest.approx(0.0, abs=0.005)


def test_the_odometer_integrates_speed():
  t = np.arange(0.0, 10.0, 0.01)
  assert P.odometer(t, np.full(len(t), 7.0))[-1] == pytest.approx(7.0 * (t[-1] - t[0]))
  d = P.plan_distance(np.full((1, 33), 12.0))[0]
  assert d[0] == 0.0 and d[-1] == pytest.approx(12.0 * P.T_IDX[-1])
