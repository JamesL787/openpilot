from types import SimpleNamespace

import pytest

from openpilot.selfdrive.controls.lib.longitudinal_planner import (
  EXP_LEAD_DEPARTURE_MAX_LIFT,
  EXP_LEAD_DEPARTURE_MAX_LIFT_FALL,
  EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE,
  LongitudinalPlanner,
  apply_exp_lead_departure,
  get_exp_lead_departure_weight,
)

V_EGO = 17.0
T_FOLLOW = 1.45


def lead(d_rel=70.0, v_rel=2.0, a_lead=0.1, radar=False, prob=0.9, status=True):
  return SimpleNamespace(status=status, dRel=d_rel, vRel=v_rel, aLeadK=a_lead, radar=radar, modelProb=prob)


def test_weight_full_for_lead_pulling_away_beyond_follow_distance():
  assert get_exp_lead_departure_weight(lead(), V_EGO, T_FOLLOW) == pytest.approx(1.0)


def test_weight_ramps_with_pull_away_speed():
  assert get_exp_lead_departure_weight(lead(v_rel=0.3), V_EGO, T_FOLLOW) == 0.0
  assert 0.0 < get_exp_lead_departure_weight(lead(v_rel=0.65), V_EGO, T_FOLLOW) < 1.0


@pytest.mark.parametrize("kwargs, v_ego", [
  (dict(status=False), V_EGO),
  (dict(v_rel=-1.0), V_EGO),  # closing
  (dict(a_lead=-0.5), V_EGO),  # lead braking
  (dict(d_rel=20.0), V_EGO),  # inside the follow distance (1.45 s * 17 m/s = 24.7 m)
  (dict(prob=0.3), V_EGO),  # weak vision lead
  ({}, 3.0),  # below 10 mph
])
def test_weight_zero_when_not_a_clear_departure(kwargs, v_ego):
  assert get_exp_lead_departure_weight(lead(**kwargs), v_ego, T_FOLLOW) == 0.0


def test_radar_lead_skips_model_prob_gate():
  assert get_exp_lead_departure_weight(lead(radar=True, prob=0.0), V_EGO, T_FOLLOW) == pytest.approx(1.0)


def test_lift_closes_part_of_gap_and_is_capped():
  # 0000006d--4715a1d4cc 4:22.5: e2e 0.23, MPC 0.75 -> 0.23 + 0.6 * 0.52
  assert apply_exp_lead_departure(0.23, 0.23, 0.75, 1.0) == pytest.approx(0.23 + 0.6 * 0.52)
  assert apply_exp_lead_departure(0.0, 0.0, 2.0, 1.0) == pytest.approx(EXP_LEAD_DEPARTURE_MAX_LIFT)
  assert apply_exp_lead_departure(0.2, 0.2, 2.0, 1.0) == pytest.approx(0.2 + EXP_LEAD_DEPARTURE_MAX_LIFT)
  assert apply_exp_lead_departure(0.23, 0.23, 0.75, 0.5) == pytest.approx(0.23 + 0.5 * 0.6 * 0.52)


def test_never_touches_e2e_braking_or_exceeds_mpc_or_lowers_target():
  e2e_brake = EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE - 0.01
  assert apply_exp_lead_departure(e2e_brake, e2e_brake, 1.0, 1.0) == e2e_brake
  assert apply_exp_lead_departure(0.5, 0.8, 0.5, 1.0) == 0.5  # MPC is the limit already
  assert apply_exp_lead_departure(0.7, 0.2, 0.75, 1.0) == 0.7  # something already higher (speed handoff)
  for mpc in (0.1, 0.3, 0.9, 3.0):
    assert apply_exp_lead_departure(0.05, 0.05, mpc, 1.0) <= mpc
  assert apply_exp_lead_departure(0.2, 0.2, 0.9, 0.0) == 0.2


def _planner(lead_one):
  return SimpleNamespace(lead_one=lead_one, dt=0.05, exp_lead_departure_weight=0.0, exp_lead_departure_lift=0.0)


def _step(p, toggle=True, hold=False, e2e=0.2, mpc=0.9):
  return LongitudinalPlanner.update_exp_lead_departure(
    p, e2e, e2e, mpc, V_EGO, T_FOLLOW, SimpleNamespace(exp_lead_departure_assist=toggle), hold)


def test_toggle_off_changes_nothing():
  p = _planner(lead())
  for _ in range(100):
    assert _step(p, toggle=False) == 0.2
  assert p.exp_lead_departure_weight == 0.0


def test_weight_fades_in_and_drops_quickly():
  p = _planner(lead())
  first = _step(p)
  assert 0.2 < first < 0.25  # ~0.5 s rise, no step
  for _ in range(60):
    out = _step(p)
  assert out == pytest.approx(0.2 + 0.6 * 0.7, abs=5e-3)
  p.lead_one = lead(a_lead=-1.0)  # lead brakes
  for _ in range(20):  # 1 s at a 0.15 s fall time constant
    out = _step(p)
  assert out < 0.205


def test_planned_stop_disarms():
  p = _planner(lead())
  for _ in range(60):
    _step(p)
  for _ in range(20):
    out = _step(p, hold=True)
  assert out < 0.205


def _held(p, **kw):
  for _ in range(60):
    out = _step(p, **kw)
  assert out - 0.2 > 0.4  # lift of 0.42 held
  return out


@pytest.mark.parametrize("gentle", [lead(v_rel=-0.2), lead(a_lead=-0.5), lead(status=False)])
def test_gentle_disarm_releases_at_the_fall_rate(gentle):
  p = _planner(lead())
  prev = _held(p)
  p.lead_one = gentle
  for _ in range(20):
    out = _step(p)
    assert prev - out <= EXP_LEAD_DEPARTURE_MAX_LIFT_FALL * p.dt + 1e-9  # 0.15 per 50 ms frame, not a step
    prev = out
  assert out < 0.205  # closing/braking: 0.42 gone in 3 frames; lost lead: the 0.15 s weight fade


def test_closing_lead_release_takes_three_frames():
  p = _planner(lead())
  _held(p)
  p.lead_one = lead(v_rel=-0.2)
  outs = [_step(p) for _ in range(3)]
  assert outs[0] > outs[1] > 0.2 and outs[2] == 0.2


@pytest.mark.parametrize("urgent", [lead(v_rel=-0.6), lead(a_lead=-1.2)])
def test_urgent_lead_drops_at_once(urgent):
  p = _planner(lead())
  _held(p)
  p.lead_one = urgent
  assert _step(p) == 0.2


@pytest.mark.parametrize("kw", [dict(hold=True), dict(toggle=False), dict(e2e=EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE - 0.05)])
def test_stop_toggle_off_or_e2e_braking_drop_at_once(kw):
  p = _planner(lead())
  _held(p)
  e2e = kw.get("e2e", 0.2)
  assert _step(p, **kw) == e2e


def test_release_never_exceeds_mpc():
  p = _planner(lead())
  _held(p)
  p.lead_one = lead(v_rel=-0.2)
  assert _step(p, mpc=0.3) <= 0.3 + 1e-9


def test_brake_threshold_fades_instead_of_stepping():
  just_above = apply_exp_lead_departure(-0.14, -0.14, 0.8, 1.0) - (-0.14)
  assert 0.0 < just_above < 0.05


def test_lift_rise_is_rate_limited():
  p = _planner(lead())
  p.exp_lead_departure_weight = 1.0  # weight already up; a sudden MPC jump must not step the output
  prev = _step(p, mpc=0.3)
  for _ in range(5):
    out = _step(p, mpc=2.0)
    assert out - prev <= 0.05 + 1e-9
    prev = out
