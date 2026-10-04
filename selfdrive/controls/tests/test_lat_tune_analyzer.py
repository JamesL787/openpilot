import json

import pytest

from openpilot.selfdrive.controls.lib import lat_tune_analyzer as lat

MPH = lat.MPH_TO_MS


class FakeParams:
  def __init__(self, **values):
    self.values = {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in values.items()}
    self.puts = []

  def get(self, key, *args, **kwargs):
    return self.values.get(key)

  def put(self, key, value):
    self.puts.append(key)
    self.values[key] = value

  put_nonblocking = put


def drive(minutes, v_mph, *, straight_err=0.5, flip_every=150, curve_des=None, curve_ratio=1.0, press_every=None, carry=None):
  """Synthetic engaged drive at one speed. The straight-frame error alternates sign every
  `flip_every` straight frames; with curve_des, one second in four is a curve, so straight runs
  are 300 frames and a flip that lands on a run boundary is not counted (the learner resets there).
  The default, one counted flip per run, is 0.33 /s: under SIGN_RATE_UP_MAX."""
  st = lat.DriveStats(carry)
  n = int(minutes * 6000)
  j = 0
  for k in range(n):
    in_curve = curve_des is not None and (k // 100) % 4 == 3
    if in_curve:
      des, ang = curve_des, curve_des * curve_ratio
    else:
      sgn = 1.0 if (j // flip_every) % 2 == 0 else -1.0
      j += 1
      des, ang = 0.0, -sgn * straight_err
    pressed = press_every is not None and k % press_every == 0
    st.observe(v_mph * MPH, des, ang, pressed, False, False)
  return st


def fp(params):
  return lat.tuning_fingerprint({k: params.get(k) for k in lat.TUNING_KEYS})


def saved(params, stats):
  """Stats as the previous drive would have saved them under `params`' current tuning."""
  stats.tuning = fp(params)
  params.values["LatAdaptiveStats"] = stats.to_json()
  return params


def band_of(v_mph):
  return lat.band_index(v_mph * MPH)


class TestBands:
  def test_bands_match_latcontrol_pid_edges(self):
    from openpilot.selfdrive.controls.lib.latcontrol_pid import _lat_pid_scale_banded
    for v_mph in (0.0, 10.0, 24.9, 25.0, 25.1, 37.0, 49.9, 50.0, 50.1, 80.0):
      v = v_mph * MPH
      assert lat.band_index(v) == _lat_pid_scale_banded(v, 0, 1, 2)
    assert lat.BAND_NAMES == ("LowSpeed", "Standard", "Highway")
    assert lat.P_KEYS == ("LatPScaleLowSpeed", "LatPScaleStandard", "LatPScaleHighway")

  def test_band_weights_are_hard(self):
    assert lat.band_weights(20 * MPH) == ((0, 1.0),)
    assert lat.band_weights(30 * MPH) == ((1, 1.0),)
    assert lat.band_weights(70 * MPH) == ((2, 1.0),)


class TestMetrics:
  def test_sign_rate_straight_rms_and_curve_ratio(self):
    st = drive(4, 30, straight_err=0.5, flip_every=100, curve_des=10.0, curve_ratio=0.9)  # 2 flips per 300-frame run
    m = lat.band_metrics(st.acc[band_of(30)])
    assert m["min"] == pytest.approx(4.0, rel=1e-3)
    assert m["straight_rms"] == pytest.approx(0.5)
    assert m["sign_rate"] == pytest.approx(2 / 3, rel=0.01)
    assert m["curve_ratio"] == pytest.approx(0.9)

  @pytest.mark.parametrize("amp,counted", [(0.1, 0), (0.14, 0), (0.15, 1), (0.3, 1)])
  def test_sign_change_needs_the_full_deadband_swing(self, amp, counted):
    st = lat.DriveStats()
    for k in range(2000):
      st.observe(30 * MPH, 0.0, -amp if (k // 10) % 2 == 0 else amp, False, False, False)   # flips every 0.1 s
    assert st.acc[band_of(30)]["sc"] == pytest.approx(199 * counted)

  def test_error_returning_inside_the_deadband_is_not_a_sign_change(self):
    st = lat.DriveStats()
    for err in [0.5] * 50 + [-0.1] * 50 + [0.5] * 50 + [0.0] * 50 + [-0.5] * 50:
      st.observe(30 * MPH, 0.0, -err, False, False, False)
    assert st.acc[band_of(30)]["sc"] == pytest.approx(1.0)   # only the final +0.5 -> -0.5

  def test_curve_split_into_entry_steady_and_exit(self):
    # 2 s wind-up to 20 deg at 10 deg/s, 40 s hold, 2 s unwind; the angle trails the desired by 0.2 s.
    des = [0.0] * 100 + [k * 0.1 for k in range(200)] + [20.0] * 4000 + [20.0 - k * 0.1 for k in range(200)] + [0.0] * 100
    st = lat.DriveStats()
    for _ in range(4):   # entry and exit above CURVE_DEG: 1.5 s each per curve
      for k, d in enumerate(des):
        st.observe(30 * MPH, d, 0.98 * des[max(k - 20, 0)], False, False, False)
    m = lat.band_metrics(st.acc[band_of(30)])
    assert m["curve_ratio_ss"] == pytest.approx(0.98, abs=0.005)
    assert m["curve_ratio_en"] < 0.9 < 1.05 < m["curve_ratio_ex"]
    assert m["curve_ratio_en"] < m["curve_ratio"] < m["curve_ratio_ss"]

  def test_curve_split_needs_enough_transient_time(self):
    a = drive(4, 30, curve_des=10, curve_ratio=0.9).acc[band_of(30)]   # 60 step curves, no unwinding inside a curve
    assert a["n_en"] == pytest.approx(60 * lat.CURVE_RATE_FRAMES)   # the step is a wind-up until it leaves the rate window
    m = lat.band_metrics(a)
    assert m["curve_ratio_ss"] == pytest.approx(0.9) and m["curve_ratio_en"] == pytest.approx(0.9)
    assert m["curve_ratio_ex"] is None
    assert lat.band_metrics(drive(2, 30, curve_des=10, curve_ratio=0.9).acc[band_of(30)])["curve_ratio_en"] is None   # 3 s < MIN_TRANSIENT_S

  def test_excluded_frames_do_not_count(self):
    st = lat.DriveStats()
    for _ in range(1000):
      st.observe(30 * MPH, 0.0, 1.0, True, False, False)
      st.observe(30 * MPH, 0.0, 1.0, False, True, False)
      st.observe(30 * MPH, 0.0, 1.0, False, False, True)
      st.observe(2.0, 0.0, 1.0, False, False, False)
    assert all(a["n"] == 0 for a in st.acc)

  def test_json_round_trip_and_rejects_garbage(self):
    st = drive(1, 40)
    back = lat.DriveStats.from_json(st.to_json())
    assert back.acc[band_of(40)]["n"] == pytest.approx(st.acc[band_of(40)]["n"])
    for bad in ("", "x", "[]", json.dumps({"version": 99}), json.dumps({"version": 1, "knots_mph": [1, 2], "acc": []})):
      assert lat.DriveStats.from_json(bad) is None


class TestStepSize:
  @pytest.mark.parametrize("ratio,step", [(0.944, 0.05), (0.97, 0.05), (0.90, 0.10), (0.87, 0.15), (0.50, 0.15), (1.10, 0.10), (1.04, 0.05)])
  def test_curve_step_is_on_grid_and_capped_at_15_percent(self, ratio, step):
    assert lat.curve_step(ratio) == pytest.approx(step)


class TestRules:
  def test_short_drive_holds_and_carries(self):
    s1 = lat.update_state(lat.default_state(), drive(2, 40, curve_des=10, curve_ratio=0.9), lat.APPLY_MODE)
    assert s1["factor"] == [1.0] * len(lat.BANDS)
    assert s1["carry"][band_of(40)] is not None
    s2 = lat.update_state(s1, drive(2, 40, curve_des=10, curve_ratio=0.9, carry=s1["carry"]), lat.APPLY_MODE)
    assert s2["factor"][band_of(40)] == pytest.approx(1.10)   # curve ratio 0.9 needs +0.11 -> 0.10 step
    assert s2["carry"][band_of(40)] is None

  def test_curve_shortfall_steps_up_one_step_per_drive_and_is_bounded(self):
    s = lat.default_state()
    for _ in range(10):
      s = lat.update_state(s, drive(4, 30, curve_des=10, curve_ratio=0.9), 0)
    assert s["factor"][band_of(30)] == pytest.approx(1.0 + lat.MAX_NEIGHBOUR_GAP)  # neighbours had no data
    for _ in range(10):
      st = lat.DriveStats()
      for v in (15.0, 35.0, 60.0):
        st.acc[band_of(v)] = drive(4, v, curve_des=10, curve_ratio=0.9).acc[band_of(v)]
      s = lat.update_state(s, st, 0)
    assert s["factor"] == pytest.approx([lat.FACTOR_MAX] * len(lat.BANDS))

  def test_one_step_per_drive(self):
    s = lat.update_state(lat.default_state(), drive(20, 30, curve_des=10, curve_ratio=0.5), 0)
    assert s["factor"][band_of(30)] == pytest.approx(1.0 + lat.MAX_STEP)   # capped at 15 % however short the curve

  def test_oscillation_steps_down_to_bound(self):
    s = lat.default_state()
    for _ in range(10):
      s = lat.update_state(s, drive(4, 40, flip_every=50), 0)  # 2 sign changes /s
    assert s["factor"][band_of(40)] == pytest.approx(1.0 - lat.MAX_NEIGHBOUR_GAP)

  def test_overshoot_steps_down(self):
    s = lat.update_state(lat.default_state(), drive(4, 40, curve_des=10, curve_ratio=1.1), 0)
    assert s["factor"][band_of(40)] == pytest.approx(0.90)   # 1/1.1 - 1 = -0.09 -> 0.10 step

  def test_no_step_up_when_override_onsets_high(self):
    s = lat.update_state(lat.default_state(), drive(4, 20, curve_des=10, curve_ratio=0.85, press_every=2000), lat.APPLY_MODE)
    assert s["factor"][band_of(20)] == pytest.approx(1.0)  # 3 onsets/min > PRESS_RATE_UP_MAX

  def test_press_chatter_within_one_fight_counts_once(self):
    # 0000026b 32:43.7-45.2: seven 2-4 frame presses 10-40 frames apart while the driver held the wheel
    st = lat.DriveStats()
    v = 20 * lat.MPH_TO_MS
    pattern = ([True] * 4 + [False] * 12) * 7 + [False] * 400 + [True] * 25 + [False] * 400
    for p in pattern:
      st.observe(v, 0.0, 0.0, p, False, False)
    assert st.acc[band_of(20)]["press"] == pytest.approx(2.0)   # the chatter burst, then a separate press 4 s later

  def test_no_step_up_when_already_near_oscillation_limit(self, monkeypatch):
    monkeypatch.setattr(lat, "SIGN_RATE_UP_MAX", 0.3)  # 0.33 /s: above the step-up limit, below SIGN_RATE_MAX
    s = lat.update_state(lat.default_state(), drive(4, 30, flip_every=150, curve_des=10, curve_ratio=0.85), lat.APPLY_MODE)
    assert s["factor"][band_of(30)] == pytest.approx(1.0)

  def test_revert_after_increase_that_raised_oscillation_only_in_apply(self):
    s = lat.update_state(lat.default_state(), drive(4, 30, flip_every=150, curve_des=10, curve_ratio=0.9), lat.APPLY_MODE)
    assert s["factor"][band_of(30)] == pytest.approx(1.10)
    worse = drive(4, 30, flip_every=100, curve_des=10, curve_ratio=0.9)  # 0.33 -> 0.67 /s
    assert lat.update_state(s, worse, lat.APPLY_MODE)["factor"][band_of(30)] == pytest.approx(1.0)   # undo the +0.10
    assert lat.update_state(s, worse, 0)["factor"][band_of(30)] == pytest.approx(1.05)   # no revert: one step down, 0.67 > SIGN_RATE_MAX

  @pytest.mark.parametrize("prev_rate,reverted", [(0.25, True), (0.286, False)])
  def test_revert_needs_an_absolute_rise_too(self, prev_rate, reverted):
    s = lat.update_state(lat.default_state(), drive(4, 30, curve_des=10, curve_ratio=0.9), lat.APPLY_MODE)
    s["prev"][band_of(30)]["sign_rate"] = prev_rate   # -> 0.333 /s: +33 % / +0.083, or +16 % but only +0.047
    f = lat.update_state(s, drive(4, 30, curve_des=10, curve_ratio=0.9), lat.APPLY_MODE)["factor"][band_of(30)]
    assert (f == pytest.approx(1.0)) == reverted

  def test_revert_after_increase_that_raised_override_onsets(self):
    s = lat.update_state(lat.default_state(), drive(4, 30, curve_des=10, curve_ratio=0.9), lat.APPLY_MODE)
    worse = drive(4, 30, curve_des=10, curve_ratio=0.9, press_every=6000)  # 1 onset/min, from 0
    assert lat.update_state(s, worse, lat.APPLY_MODE)["factor"][band_of(30)] == pytest.approx(1.0)

  def test_neighbour_gap_is_bounded(self):
    s = lat.default_state()
    s["factor"] = [0.85, 1.15, 1.0]
    s = lat.update_state(s, lat.DriveStats(), 0)
    f = s["factor"]
    assert all(abs(a - b) <= lat.MAX_NEIGHBOUR_GAP + 1e-9 for a, b in zip(f[:-1], f[1:], strict=True))
    assert all(lat.FACTOR_MIN <= x <= lat.FACTOR_MAX for x in f)

  @pytest.mark.parametrize("raw", ["", "junk", "[]", json.dumps({"version": 2, "bands": list(lat.BAND_NAMES), "factor": [2, 1, 1]}),
                                   json.dumps({"version": 1, "knots_mph": [20, 30, 40, 50], "factor": [1, 1, 1, 1]}),
                                   json.dumps({"version": 2, "bands": ["a", "b"], "factor": [1, 1]})])
  def test_bad_state_resets(self, raw):
    assert lat.parse_state(raw)["factor"] == [1.0] * len(lat.BANDS)


class TestTrialAndBandParams:
  GAINS = [{"p": 100, "i": 100, "f": 50}, {"p": 100, "i": 75, "f": 100}, {"p": 105, "i": 100, "f": 100}]
  BASELINE = {"fingerprint": "deadbeef", "gains": GAINS, "raw": {}}

  def test_build_trial_reports_bands_readiness_factors_and_reasons(self):
    stats = drive(4, 30, curve_des=8.0, curve_ratio=0.9)   # 4 min in the 25-50 mph band, curve shortfall -> up
    trial = lat.build_trial(stats, self.BASELINE, ["r1"], [{"route": "r1", "minutes": [0, 4, 0]}], [])
    assert trial["schemaVersion"] == 2
    assert [(b["name"], b["lowMph"], b["highMph"]) for b in trial["bands"]] == [
      ("LowSpeed", 0.0, 25.0), ("Standard", 25.0, 50.0), ("Highway", 50.0, None)]
    std = trial["bands"][1]
    assert std["ready"] is True and std["minutes"] >= 3.9
    assert std["decision"] == "up" and std["factor"] == 1.10 and std["reason"].startswith("Standard: up")
    assert std["current"] == {"p": 100, "i": 75, "f": 100}
    assert std["proposed"] == {"p": 110, "i": 75, "f": 100}     # only P moves
    low = trial["bands"][0]
    assert low["ready"] is False and low["factor"] == 1.0 and low["proposed"] == low["current"]
    assert trial["baseline"]["fingerprint"] == "deadbeef" and trial["baseline"]["scheduleTerms"] == []
    assert trial["routeNames"] == ["r1"] and trial["perRoute"][0]["route"] == "r1"
    assert trial["applied"] is None

  def test_build_band_params_writes_only_p(self):
    trial = lat.build_trial(drive(4, 30, curve_des=8.0, curve_ratio=0.9), self.BASELINE, ["r1"], [], [])
    assert lat.build_band_params(trial) == {"LatPScaleStandard": 110}       # held bands are not written
    # forced apply after a manual change: the step lands on the device's P, the logged 100 is not restored
    device = [{"p": 90, "i": 20, "f": 100}, {"p": 120, "i": 75, "f": 100}, {"p": 130, "i": 0, "f": 100}]
    assert lat.build_band_params(trial, device) == {"LatPScaleStandard": 130}

  def test_build_band_params_writes_i_only_for_a_sim_step(self):
    trial = lat.build_trial(drive(4, 30, curve_des=8.0, curve_ratio=0.9), self.BASELINE, ["r1"], [], [])
    trial["bands"][0].update(iDelta=25)       # the sim moved LowSpeed I only
    trial["bands"][2].update(iDelta=-25)      # Highway I 100 -> 75; I is clamped at 0 on a device already at 0
    assert lat.build_band_params(trial) == {"LatPScaleStandard": 110, "LatIScaleLowSpeed": 125, "LatIScaleHighway": 75}
    device = [{"p": 90, "i": 20, "f": 100}, {"p": 120, "i": 75, "f": 100}, {"p": 130, "i": 0, "f": 100}]
    assert lat.build_band_params(trial, device) == {"LatPScaleStandard": 130, "LatIScaleLowSpeed": 45, "LatIScaleHighway": 0}

  @pytest.mark.parametrize("cur,factor,want", [(100, 1.0, 100), (100, 1.05, 105), (100, 0.95, 95), (135, 1.05, 140),
                                               (200, 0.95, 190), (20, 1.05, 25), (20, 0.95, 15), (3, 0.95, 0),
                                               (498, 1.05, 500), (100, 1.10, 110)])
  def test_propose_p_rounds_to_galaxy_step_and_never_cancels_the_step(self, cur, factor, want):
    assert lat.propose_p(cur, factor) == want

  def test_band_gains_reads_params_and_uses_the_real_defaults(self):
    raw = {"LatPScaleLowSpeed": "80", "LatPScaleStandard": b"135", "LatIScaleStandard": "75", "LatFScaleLowSpeed": "junk"}
    g = lat.band_gains(raw)
    assert g[0] == {"p": 80, "i": 20, "f": 100}
    assert g[1] == {"p": 135, "i": 75, "f": 100}
    assert g[2] == {"p": 100, "i": 0, "f": 100}

  def test_band_defaults_match_params_keys_and_the_controller(self):
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    header = (root / "common" / "params_keys.h").read_text()
    ctrl = (root / "selfdrive" / "controls" / "lib" / "latcontrol_pid.py").read_text()
    for term, keys in (("p", lat.P_KEYS), ("i", lat.I_KEYS), ("f", lat.F_KEYS)):
      for n, key in enumerate(keys):
        want = lat.BAND_DEFAULTS[term][n]
        h = re.search(fr'\{{"{key}", \{{PERSISTENT, INT, "(\d+)"', header)
        c = re.search(fr'"{key}", ([\d.]+), ', ctrl)
        assert h and int(h.group(1)) == want, key
        assert c and round(float(c.group(1)) * 100) == want, key

  def test_schedule_terms_and_strip_p(self):
    both = '{"v_mph": [20, 50], "p": [100, 200], "i": [50, 60]}'
    assert lat.schedule_terms(both) == ["i", "p"]
    assert lat.schedule_terms("") == [] and lat.schedule_terms(None) == []
    assert json.loads(lat.strip_schedule_p(both)) == {"v_mph": [20, 50], "i": [50, 60]}
    assert lat.strip_schedule_p('{"v_mph": [20, 50], "p": [100, 200]}') == ""
    assert lat.strip_schedule_p("") == ""
    only_i = '{"v_mph": [20, 50], "i": [50, 60]}'
    assert lat.strip_schedule_p(only_i) == only_i
    # the controller rejects this whole schedule (p over 300), so its i is not live; stripping p would switch it on
    rejected = '{"v_mph": [20, 50], "p": [500, 500], "i": [40, 90]}'
    assert lat.schedule_terms(rejected) == [] and lat.strip_schedule_p(rejected) == rejected


class _Which:
  """Tiny capnp-like message stand-in: .which() plus one attribute holding the payload."""
  def __init__(self, which, **payload):
    self._which = which
    for k, v in payload.items():
      setattr(self, k, v)
  def which(self):
    return self._which


class _Obj:
  def __init__(self, **kw):
    self.__dict__.update(kw)


def _init_msg(entries):
  params = _Obj(entries=[_Obj(key=k, value=v.encode()) for k, v in entries.items()])
  return _Which("initData", initData=_Obj(params=params))


def _cs(v, angle, pressed=False):
  return _Which("carState", carState=_Obj(vEgo=v, steeringAngleDeg=angle, steeringPressed=pressed))


def _pid(desired, active=True):
  lcs = _Which("pidState", pidState=_Obj(active=active, steeringAngleDesiredDeg=desired))
  return _Which("controlsState", controlsState=_Obj(lateralControlState=lcs))


def _fake_log(msgs):
  return lambda path, **kw: iter(msgs)


class TestFrames:
  def test_frames_follow_pid_state_and_carry_init_tuning(self):
    msgs = [_init_msg({"LatPScaleStandard": "120", "LatGainSchedule": ""}), _cs(13.4, 1.0), _pid(0.5), _cs(13.4, -1.0, pressed=True),
            _pid(0.3), _Which("controlsState", controlsState=_Obj(lateralControlState=_Which("torqueState")))]
    src = lat.FrameSource("x/rlog.zst", log_reader=_fake_log(msgs))
    frames = list(src.frames())
    assert frames == [(13.4, 0.5, 1.0, False, False, False), (13.4, 0.3, -1.0, True, False, False)]
    assert src.tuning["LatPScaleStandard"] == "120"

  def test_inactive_pid_frames_are_skipped(self):
    src = lat.FrameSource("x", log_reader=_fake_log([_cs(13.4, 0.0), _pid(0.5, active=False)]))
    assert list(src.frames()) == []

  def test_analyze_sources_builds_trial_with_baseline_from_latest_route(self):
    n = 6000 * 4
    a = [_init_msg({"LatPScaleStandard": "100"}), _cs(13.4, 0.5)] + [_pid(0.4 if i % 100 < 50 else -0.4) for i in range(n)]
    b = [_init_msg({"LatPScaleStandard": "120"}), _cs(13.4, 0.5)] + [_pid(0.4) for _ in range(600)]
    sources = [lat.RouteLog("r-old", "1", "a", _fake_log(a)), lat.RouteLog("r-new", "1", "b", _fake_log(b))]
    trial = lat.analyze_sources(sources, mixed_tuning=True)
    assert trial["routeNames"] == ["r-old", "r-new"]
    assert trial["baseline"]["gains"][1]["p"] == 120             # latest route's initData wins
    assert trial["bands"][1]["current"]["p"] == 120
    assert any("fingerprint" in w for w in trial["warnings"])     # routes disagree
    assert trial["perRoute"][0]["route"] == "r-old" and trial["perRoute"][0]["minutes"][1] >= 3.9
    assert all(r["used"] for r in trial["perRoute"])
    assert trial["bands"][1]["ready"] is True

  def test_analyze_sources_leaves_out_routes_on_other_tuning(self):
    n = 6000 * 4
    a = [_init_msg({"LatPScaleStandard": "100"}), _cs(13.4, 0.5)] + [_pid(0.4) for _ in range(n)]
    b = [_init_msg({"LatPScaleStandard": "120"}), _cs(13.4, 0.5)] + [_pid(0.4) for _ in range(600)]
    sources = [lat.RouteLog("r-old", "1", "a", _fake_log(a)), lat.RouteLog("r-new", "1", "b", _fake_log(b))]
    trial = lat.analyze_sources(sources)
    assert [(r["route"], r["used"]) for r in trial["perRoute"]] == [("r-old", False), ("r-new", True)]
    assert trial["perRoute"][0]["minutes"][1] >= 3.9                # still reported, just not pooled
    assert trial["bands"][1]["minutes"] < 1.0 and trial["bands"][1]["ready"] is False
    assert any(w.startswith("r-old: left out") and "LatPScaleStandard" in w for w in trial["warnings"])
    assert not any("pooled anyway" in w for w in trial["warnings"])

  def test_analyze_sources_pools_routes_on_the_same_tuning(self):
    n = 6000 * 2
    msgs = [_init_msg({"LatPScaleStandard": "105"}), _cs(13.4, 0.5)] + [_pid(0.4) for _ in range(n)]
    sources = [lat.RouteLog("r1", "0", "a", _fake_log(msgs)), lat.RouteLog("r2", "0", "b", _fake_log(msgs))]
    trial = lat.analyze_sources(sources)
    assert all(r["used"] for r in trial["perRoute"])
    assert trial["bands"][1]["minutes"] >= 3.9 and trial["bands"][1]["ready"] is True
    assert not any("left out" in w for w in trial["warnings"])

  def test_analyze_sources_leaves_out_a_route_without_logged_tuning(self):
    tuned = [_init_msg({"LatPScaleStandard": "105"}), _cs(13.4, 0.5)] + [_pid(0.4) for _ in range(600)]
    bare = [_cs(13.4, 0.5)] + [_pid(0.4) for _ in range(600)]
    trial = lat.analyze_sources([lat.RouteLog("r-bare", "0", "a", _fake_log(bare)),
                                 lat.RouteLog("r-new", "0", "b", _fake_log(tuned))])
    assert [r["used"] for r in trial["perRoute"]] == [False, True]
    assert any(w.startswith("r-bare: left out") and "no logged tuning" in w for w in trial["warnings"])

  def test_analyze_sources_baseline_override_changes_start_value_not_metrics(self):
    n = 6000 * 4
    msgs = [_init_msg({"LatPScaleStandard": "100"}), _cs(13.4, 0.5)] + [_pid(0.4) for _ in range(n)]
    plain = lat.analyze_sources([lat.RouteLog("r", "1", "a", _fake_log(msgs))])
    what_if = lat.analyze_sources([lat.RouteLog("r", "1", "a", _fake_log(msgs))], baseline_overrides={"LatPScaleStandard": "115"})
    assert plain["bands"][1]["current"]["p"] == 100 and what_if["bands"][1]["current"]["p"] == 115
    assert what_if["bands"][1]["minutes"] == plain["bands"][1]["minutes"]
    assert what_if["bands"][1]["factor"] == plain["bands"][1]["factor"]
    assert any("baseline override: LatPScaleStandard = 115" in w and "driven with 100" in w for w in what_if["warnings"])
    assert what_if["baseline"]["fingerprint"] != plain["baseline"]["fingerprint"]   # matches a device set to 115

  def test_analyze_sources_warns_when_schedule_overrides_p(self):
    msgs = [_init_msg({"LatGainSchedule": '{"v_mph": [20, 50], "p": [100, 120]}'}), _cs(13.4, 0.5), _pid(0.4)]
    trial = lat.analyze_sources([lat.RouteLog("r", "1", "a", _fake_log(msgs))])
    assert trial["baseline"]["scheduleTerms"] == ["p"]
    assert any("LatGainSchedule overrides P" in w for w in trial["warnings"])


def test_fingerprint_matches_between_initdata_bytes_and_typed_device_params():
  # initData stores the raw bytes; Params.get() on the device returns typed values. Both must hash alike,
  # or every trial needs force once a BOOL tuning key is set.
  raw = {"HondaTorqueLowPassFilter": b"0", "NrdrLatUseFirmwareVgr": "1", "HondaCenterScale": "0.5", "LatPScaleStandard": "105"}
  typed = {"HondaTorqueLowPassFilter": False, "NrdrLatUseFirmwareVgr": True, "HondaCenterScale": 0.5, "LatPScaleStandard": 105}
  assert lat.tuning_fingerprint(raw) == lat.tuning_fingerprint(typed)
  assert lat.tuning_fingerprint({"HondaCenterScale": "0.5"}) != lat.tuning_fingerprint({"HondaCenterScale": 0.55})
  assert lat.tuning_fingerprint({"LatPScaleStandard": 105}) != lat.tuning_fingerprint({"LatPScaleStandard": 110})
  sched = '{"v_mph":[20,50],"p":[100,110]}'
  assert lat.tuning_fingerprint({"LatGainSchedule": sched}) == lat.tuning_fingerprint({"LatGainSchedule": sched.encode()})


def test_added_tuning_key_leaves_earlier_fingerprints_alone_until_it_is_used():
  # A route logged before NrdrLatRateFF existed and one logged after with it at its off value pool together.
  before = {"LatPScaleStandard": "105"}
  assert lat.tuning_fingerprint({**before, "NrdrLatRateFF": "0.0"}) == lat.tuning_fingerprint(before)
  assert lat.tuning_fingerprint({**before, "NrdrLatRateFF": 0}) == lat.tuning_fingerprint(before)
  assert lat.tuning_fingerprint({**before, "NrdrLatRateFF": "0.5"}) != lat.tuning_fingerprint(before)
