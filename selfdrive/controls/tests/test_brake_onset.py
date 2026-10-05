from types import SimpleNamespace

import pytest

from openpilot.selfdrive.controls.lib import longitudinal_planner as lp


def _lead(d, v_rel, a=0.0, status=True):
  return SimpleNamespace(status=status, dRel=d, vRel=v_rel, aLeadK=a)


def test_switch_is_off_by_default():
  assert lp.BRAKE_ONSET_LIMIT is False


def test_far_slow_closing_gets_the_gentlest_jerk():
  # 80 m, closing 5 m/s -> TTC 16 s
  assert lp.brake_onset_jerk((_lead(80.0, -5.0), None), 25.0) == pytest.approx(lp.BRAKE_ONSET_JERK_V[-1])


def test_jerk_allowance_grows_as_ttc_shrinks():
  far = lp.brake_onset_jerk((_lead(60.0, -10.0),), 20.0)  # 6 s
  mid = lp.brake_onset_jerk((_lead(45.0, -10.0),), 20.0)  # 4.5 s
  assert far < mid < lp.BRAKE_ONSET_JERK_V[0]


@pytest.mark.parametrize("leads,v_ego", [
  ((_lead(30.0, -10.0),), 20.0),               # TTC 3 s: urgent
  ((_lead(25.0, -1.0),), 20.0),                # inside 1.5 s of gap
  ((_lead(8.0, 0.0),), 3.0),                   # inside the 10 m floor
  ((_lead(80.0, -2.0, a=-1.2),), 25.0),        # lead braking
  ((None, _lead(5.0, 0.0, status=False)), 25.0),  # no active lead
  ((_lead(90.0, -2.0), _lead(30.0, -12.0)), 25.0),  # the worst lead decides
])
def test_limit_is_off_when_anything_is_urgent_or_unknown(leads, v_ego):
  assert lp.brake_onset_jerk(leads, v_ego) is None


def test_limited_target_slows_only_a_falling_target():
  dt = 0.05
  assert lp.brake_onset_limited_target(-0.2, -1.5, dt, 1.5) == pytest.approx(-0.2 - 1.5 * dt)
  assert lp.brake_onset_limited_target(-1.0, -0.5, dt, 1.5) == pytest.approx(-0.5)  # release untouched
  assert lp.brake_onset_limited_target(-0.2, -1.5, dt, None) == pytest.approx(-1.5)
  assert lp.brake_onset_limited_target(1.0, 0.03, dt, 1.5) == pytest.approx(0.03)   # throttle cut untouched
  assert lp.brake_onset_limited_target(0.8, -1.0, dt, 1.5) == pytest.approx(-1.5 * dt)  # ramps from 0, not from +0.8


def test_ramp_reaches_the_target_within_abs_a_over_j():
  a, dt, j = 0.0, 0.05, 1.5
  for _ in range(int(1.5 / (j * dt)) + 1):
    a = lp.brake_onset_limited_target(a, -1.5, dt, j)
  assert a == pytest.approx(-1.5)


def test_toggle_sits_under_advanced_longitudinal_tuning_in_galaxy_and_device_ui():
  import json
  from pathlib import Path
  root = Path(__file__).resolve().parents[3]
  layout = json.loads((root / "starpilot/common/assets/device_settings_layout.json").read_text())
  found = []

  def walk(node):
    if isinstance(node, dict):
      if node.get("key") == "BrakeOnsetLimit":
        found.append(node)
      for v in node.values():
        walk(v)
    elif isinstance(node, list):
      for v in node:
        walk(v)
  walk(layout)
  assert len(found) == 1
  assert found[0]["parent_key"] == "AdvancedLongitudinalTune" and found[0]["ui_type"] == "toggle"
  ui = (root / "selfdrive/ui/layouts/settings/starpilot/longitudinal.py").read_text()
  assert 'SettingRow("BrakeOnsetLimit", "toggle"' in ui
  assert '{"BrakeOnsetLimit", {PERSISTENT, BOOL, "0", "0", 3}}' in (root / "common/params_keys.h").read_text()
  assert 'toggle.brake_onset_limit = False' in (root / "starpilot/common/starpilot_variables.py").read_text()


# D-080: newborn radar lead aLeadK bound, part of the same toggle.
def _rlead(tid, d, a, v_rel=-2.0, radar=True):
  return SimpleNamespace(status=True, radar=radar, radarTrackId=tid, dRel=d, vRel=v_rel, aLeadK=a)


def _sm(lead_one, lead_two=None, a_ego=0.0):
  lead_two = lead_two or SimpleNamespace(status=False, radar=False)
  return {'radarState': SimpleNamespace(leadOne=lead_one, leadTwo=lead_two), 'carState': SimpleNamespace(aEgo=a_ego)}


def _run(hold, frames):
  """frames: list of (lead_one, lead_two, a_ego); returns the planner-side leadOne aLeadK per frame."""
  out = []
  for one, two, a_ego in frames:
    out.append(float(lp.bound_newborn_leads(_sm(one, two, a_ego), hold)['radarState'].leadOne.aLeadK))
  return out


def test_newborn_lead_hard_brake_is_bounded_then_released_after_two_seconds():
  hold = lp.NewbornLeadHold()
  # constant closing speed: range history shows no lead decel
  a = _run(hold, [(_rlead(7, 60.0 - 0.1 * i, -3.0), None, 0.0) for i in range(lp.NEWBORN_LEAD_FRAMES + 5)])
  assert all(x == pytest.approx(-lp.NEWBORN_LEAD_MIN_BRAKE) for x in a[:lp.NEWBORN_LEAD_FRAMES])
  assert all(x == -3.0 for x in a[lp.NEWBORN_LEAD_FRAMES:])


def test_bound_only_touches_aleadk_and_never_drops_the_lead():
  hold = lp.NewbornLeadHold()
  lead = _rlead(3, 40.0, -5.0, v_rel=-4.0)
  out = lp.bound_newborn_leads(_sm(lead), hold)['radarState'].leadOne
  assert out.aLeadK == pytest.approx(-1.0)
  assert (out.dRel, out.vRel, out.status, out.radarTrackId) == (40.0, -4.0, True, 3)


@pytest.mark.parametrize("lead", [_rlead(1, 50.0, -0.5), _rlead(1, 50.0, -3.0, radar=False),
                                  SimpleNamespace(status=False, radar=True, radarTrackId=1, dRel=50.0, aLeadK=-3.0)])
def test_mild_vision_only_or_inactive_leads_pass_through(lead):
  hold = lp.NewbornLeadHold()
  sm = _sm(lead)
  assert lp.bound_newborn_leads(sm, hold) is sm


def test_range_history_that_shows_lead_braking_lowers_the_floor():
  hold = lp.NewbornLeadHold()
  # ego steady, lead decelerating at -3 m/s^2 from a 2 m/s closing: d = 60 - 2t - 1.5 t^2
  frames = []
  for i in range(30):
    t = i * lp.DT_MDL
    frames.append((_rlead(9, 60.0 - 2.0 * t - 1.5 * t * t, -3.0), None, 0.0))
  a = _run(hold, frames)
  assert a[lp.NEWBORN_LEAD_FIT_FRAMES - 2] == pytest.approx(-1.0)
  assert a[-1] == pytest.approx(-3.0, abs=0.05)


def test_dropout_or_range_jump_makes_a_track_newborn_again():
  hold = lp.NewbornLeadHold()
  _run(hold, [(_rlead(5, 50.0, 0.0, v_rel=0.0), None, 0.0) for _ in range(lp.NEWBORN_LEAD_FRAMES + 2)])
  assert _run(hold, [(_rlead(5, 50.0, -4.0, v_rel=0.0), None, 0.0)]) == [-4.0]  # mature: untouched
  assert _run(hold, [(_rlead(5, 50.0 - lp.NEWBORN_LEAD_JUMP_M - 1.0, -4.0, v_rel=0.0), None, 0.0)]) == [-1.0]
  hold2 = lp.NewbornLeadHold()
  _run(hold2, [(_rlead(6, 50.0, 0.0, v_rel=0.0), None, 0.0) for _ in range(lp.NEWBORN_LEAD_FRAMES + 2)])
  absent = SimpleNamespace(status=False, radar=False, aLeadK=0.0)
  _run(hold2, [(absent, None, 0.0) for _ in range(lp.NEWBORN_LEAD_GAP_FRAMES + 1)])
  assert _run(hold2, [(_rlead(6, 50.0, -4.0, v_rel=0.0), None, 0.0)]) == [-1.0]


def test_same_track_as_lead_one_and_two_is_recorded_once_per_frame():
  hold = lp.NewbornLeadHold()
  lead = _rlead(4, 30.0, -3.0)
  lp.bound_newborn_leads(_sm(lead, lead), hold)
  assert len(hold.hist[4]) == 1


def test_bound_is_applied_only_when_the_onset_toggle_is_on():
  import inspect
  src = inspect.getsource(lp.LongitudinalPlanner._update)
  gate = 'if BRAKE_ONSET_LIMIT or bool(getattr(starpilot_toggles, "brake_onset_limit", False)):\n'
  assert gate + '      sm = bound_newborn_leads(sm, self.newborn_lead_hold)' in src


# D-081: under a panic bypass the onset limit still applies, but only above BRAKE_ONSET_PANIC_TTC_S.
def test_panic_bypass_keeps_the_limit_only_when_ttc_is_long():
  # 2df 24:45 shape: 55 m, closing 12 m/s -> TTC 4.6 s
  assert lp.brake_onset_jerk((_lead(55.0, -12.0),), 20.0, lp.BRAKE_ONSET_PANIC_TTC_S) is not None
  # TTC 3.5 s: limited on the normal path, off under a panic bypass
  assert lp.brake_onset_jerk((_lead(42.0, -12.0),), 20.0) is not None
  assert lp.brake_onset_jerk((_lead(42.0, -12.0),), 20.0, lp.BRAKE_ONSET_PANIC_TTC_S) is None


def test_panic_bypass_no_longer_switches_the_onset_limit_off_outright():
  import inspect
  src = inspect.getsource(lp.LongitudinalPlanner._update)
  assert 'self._onset_panic_soft = prev_output_a_target > BRAKE_ONSET_PANIC_MAX_PRIOR_BRAKE' in src
  assert "onset_ttc_off = BRAKE_ONSET_PANIC_TTC_S if self._onset_panic_soft else float('inf')" in src
  assert 'output_should_stop or vision_low_speed_stop_active or panic_bypass or' not in src


# D-083: stock-like onset ramp (part of the BrakeOnsetLimit toggle).
def test_stock_ramp_is_on_inside_the_toggle_and_caps_jerk_at_stock_rates():
  assert lp.BRAKE_ONSET_STOCK_RAMP is True
  assert max(lp.BRAKE_ONSET_STOCK_JERK_V) <= 3.0
  # 299 20:34 / 2d5 11:58 shape: 50 m, closing 12 m/s (TTC 4.2 s) gets a stock-rate ramp
  j, over = lp.stock_onset_jerk((_lead(50.0, -12.0),), 22.0, -0.3, False, False)
  assert j is not None and j <= 3.0 and not over


def test_stock_ramp_continues_below_the_old_3s_switch_off_while_the_need_is_modest():
  # 20 m closing 7 m/s at 12 m/s, already at -1.5: TTC 2.9 s, the old limit was off here; need ~2.8 m/s^2
  leads = (_lead(20.0, -7.0),)
  assert lp.brake_onset_jerk(leads, 12.0) is None
  j, _ = lp.stock_onset_jerk(leads, 12.0, -1.5, False, False)
  assert j == pytest.approx(lp.BRAKE_ONSET_STOCK_JERK_V[0])


@pytest.mark.parametrize("leads,v_ego", [
  ((_lead(30.0, -16.0),), 25.0),          # TTC 1.9 s: at the floor
  ((_lead(30.0, -2.0),), 25.0),           # gap gate (1.5 s of v_ego)
  ((_lead(80.0, -5.0, a=-1.5),), 25.0),   # lead braking
])
def test_stock_ramp_keeps_the_floor_and_the_old_gates(leads, v_ego):
  assert lp.stock_onset_jerk(leads, v_ego, -0.5, False, False)[0] is None


def test_hard_panic_bypass_still_switches_the_ramp_off():
  assert lp.stock_onset_jerk((_lead(60.0, -8.0),), 20.0, -1.0, True, False)[0] is None
  assert lp.stock_onset_jerk((_lead(60.0, -8.0),), 20.0, -1.0, False, False)[0] is not None


def test_need_counts_the_ramp_lag_and_the_lead_decel():
  flat = 12.0 ** 2 / (2 * (50.0 - lp.BRAKE_ONSET_MIN_GAP_M))
  assert lp.brake_onset_need((_lead(50.0, -12.0),), -flat, 3.0) == pytest.approx(flat)   # already there: no lag
  assert lp.brake_onset_need((_lead(50.0, -12.0),), 0.0, 3.0) > flat                     # ramp from 0 costs room
  assert lp.brake_onset_need((_lead(50.0, -12.0, a=-0.8),), -flat, 3.0) == pytest.approx(flat + 0.8)
  assert lp.brake_onset_need((_lead(12.0, -12.0),), 0.0, 3.0) == float('inf')


def test_a_lone_spike_cannot_end_the_ramp_but_a_sustained_need_does():
  calm, spike = (_lead(47.0, -12.0),), (_lead(47.0, -20.0),)   # 2d5 11:58: one frame read -20
  j, over = lp.stock_onset_jerk(calm, 22.0, -1.1, False, False)
  assert j is not None and not over
  j, over = lp.stock_onset_jerk(spike, 22.0, -1.2, False, over)
  assert j is not None and over        # first frame over the need: still ramping
  j, over = lp.stock_onset_jerk(calm, 22.0, -1.3, False, over)
  assert j is not None and not over    # spike gone: ramp continues
  j, over = lp.stock_onset_jerk(spike, 22.0, -1.4, False, False)
  j, over = lp.stock_onset_jerk(spike, 22.0, -1.5, False, over)
  assert j is None                     # two frames over: limit stands down, full target passes


def test_ramp_never_reduces_the_peak_only_its_arrival():
  a, dt = 0.0, 0.05
  for _ in range(200):
    a = lp.brake_onset_limited_target(a, -3.5, dt, lp.BRAKE_ONSET_STOCK_JERK_V[0])
  assert a == pytest.approx(-3.5)


def test_planner_uses_the_stock_ramp_behind_its_switch():
  import inspect
  src = inspect.getsource(lp.LongitudinalPlanner._update)
  assert 'if BRAKE_ONSET_STOCK_RAMP:' in src
  assert 'stock_onset_jerk(' in src and 'panic_bypass and not self._onset_panic_soft' in src
  assert 'and not BRAKE_ONSET_STOCK_PANIC_RAMP' in src


def test_panic_bypass_keeps_the_stock_ramp_down_to_the_ttc_floor():
  # D-084 / 2e5 7:58: merge-in at 61 m, vRel -9.5 (TTC 6.4), bypass began at -0.53 (just past the D-081 latch)
  assert lp.BRAKE_ONSET_STOCK_PANIC_RAMP and lp.BRAKE_ONSET_STOCK_TTC_FLOOR_S == 2.0
  assert lp.stock_onset_jerk((_lead(61.0, -9.5),), 27.0, -0.53, False, False)[0] is not None
  assert lp.stock_onset_jerk((_lead(30.0, -14.0),), 18.0, -0.53, False, False)[0] is not None   # TTC 2.1 s
  assert lp.stock_onset_jerk((_lead(30.0, -16.0),), 18.0, -0.53, False, False)[0] is None       # TTC 1.9 s


# D-086: StockBrakeFeel toggle, slow far ramp and -2.0 depth hold.
def test_stock_feel_toggle_is_wired_and_off_by_default():
  import json
  from pathlib import Path
  root = Path(__file__).resolve().parents[3]
  layout = json.loads((root / "starpilot/common/assets/device_settings_layout.json").read_text())
  found = []

  def walk(node):
    if isinstance(node, dict):
      if node.get("key") == "StockBrakeFeel":
        found.append(node)
      for v in node.values():
        walk(v)
    elif isinstance(node, list):
      for v in node:
        walk(v)
  walk(layout)
  assert len(found) == 1
  assert found[0]["parent_key"] == "AdvancedLongitudinalTune" and found[0]["ui_type"] == "toggle"
  assert 'SettingRow("StockBrakeFeel", "toggle"' in (root / "selfdrive/ui/layouts/settings/starpilot/longitudinal.py").read_text()
  assert '{"StockBrakeFeel", {PERSISTENT, BOOL, "0", "0", 3}}' in (root / "common/params_keys.h").read_text()
  assert 'toggle.stock_brake_feel = False' in (root / "starpilot/common/starpilot_variables.py").read_text()
  src = Path(lp.__file__).read_text()
  assert 'getattr(starpilot_toggles, "stock_brake_feel", False)' in src


def test_stock_feel_ramp_is_slower_far_and_unchanged_near():
  far = (_lead(100.0, -8.0),)   # TTC 12.5 s
  mid = (_lead(48.0, -8.0),)    # TTC 6 s
  near = (_lead(24.0, -8.0),)   # TTC 3 s, 24 m > 1.5 s * 15
  args = (lp.STOCK_FEEL_JERK_V, lp.STOCK_FEEL_TTC_BP)
  assert lp.stock_onset_jerk(far, 15.0, -0.5, False, False, *args)[0] == pytest.approx(0.5)
  assert lp.stock_onset_jerk(mid, 15.0, -0.5, False, False, *args)[0] == pytest.approx(1.0)
  assert lp.stock_onset_jerk(near, 15.0, -0.5, False, False, *args)[0] == pytest.approx(3.0)
  assert lp.stock_onset_jerk(far, 15.0, -0.5, False, False)[0] == pytest.approx(lp.BRAKE_ONSET_STOCK_JERK_V[-1])


def test_stock_feel_holds_at_stock_depth_while_far_and_need_is_small():
  far = (_lead(100.0, -8.0),)   # need 64 / 180 plus ramp lag, well under 1.6
  t, rel = lp.stock_feel_depth_target(far, -1.5, -3.0, 0.5, False)
  assert t == lp.STOCK_FEEL_DEPTH and not rel
  t, rel = lp.stock_feel_depth_target(far, -1.0, -1.8, 0.5, False)   # shallower than the hold: untouched
  assert t == -1.8 and not rel


@pytest.mark.parametrize("leads,jerk", [
  ((_lead(100.0, -8.0),), None),          # onset ramp off (any D-083 gate)
  ((_lead(30.0, -11.0),), 3.0),           # TTC 2.7 s
  ((_lead(60.0, -14.0),), 1.0),           # need over 1.6
])
def test_stock_feel_releases_to_full_depth(leads, jerk):
  t, rel = lp.stock_feel_depth_target(leads, -2.0, -3.4, jerk, False)
  assert t == -3.4 and rel


def test_stock_feel_release_latches_until_the_brake_ends():
  far = (_lead(100.0, -8.0),)
  t, rel = lp.stock_feel_depth_target(far, -2.5, -3.0, 0.5, True)   # need small again: stays released, no pulse
  assert t == -3.0 and rel
  t, rel = lp.stock_feel_depth_target(far, -0.2, -0.1, 0.5, True)   # brake over: rearmed
  assert not rel
  assert lp.stock_feel_depth_target(far, -0.2, -3.0, 0.5, rel)[0] == lp.STOCK_FEEL_DEPTH
