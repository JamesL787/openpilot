import numpy as np

from openpilot.tools.longitudinal import stock_acc_reference as sar


def _route(name, op_long, n=2000, seed=0, brake_gain=1.0):
  # synthetic drive: a lead at 30 m, closing speed sweeps; "stock" commands brake_gain * vrel below -1 m/s
  rng = np.random.default_rng(seed)
  t = np.arange(n) / sar.HZ
  vrel = -3.0 * np.sin(t / 7.0) ** 2 + rng.normal(0, 0.05, n)
  cmd = np.where(vrel < -1.0, brake_gain * (vrel + 1.0), 0.2)
  z = np.zeros(n)
  R = {"t": t, "v": z + 20.0, "a": cmd.copy(), "d": z + 30.0, "vrel": vrel, "alead": z, "aleadk": z, "yrel": z,
       "radar": z + 1, "mprob": z + 1, "mx": z + 30, "mv": 20 + vrel, "cmd": cmd, "stock": z + (not op_long),
       "alert": z.copy(),
       "alpha": z + op_long, "icbm": z, "setv": z + 30.0}
  R["meta"] = {"route": name, "op_long": op_long, "fingerprint": "X", "acc_bus": 1}
  return R


def test_reversals_counts_changes_of_mind_only():
  assert sar.reversals(np.array([0, -1, -2, -3, -3, -2.9])) == 0
  assert sar.reversals(np.array([0, -2, -1, -2.5, -1, -3])) == 4
  assert sar.reversals(np.array([0, -2, -1.85, -2.1])) == 0  # swings under REVERSAL_MIN are noise


def test_leave_one_out_recovers_stock_law():
  C = sar.Corpus([_route(f"s{i}", False, seed=i) for i in range(3)])
  sel = C.I == 0
  r = C.query(C.X[sel], exclude=0)
  err = np.abs(r["med"][:, 0] - C.Y[sel, 0])
  assert np.nanmean(err) < 0.1
  assert np.nanmax(r["dist"]) < sar.NO_PRECEDENT


def test_alpha_routes_are_not_in_the_corpus_and_far_queries_say_no_precedent():
  C = sar.Corpus([_route("s0", False), _route("a0", True)])
  assert C.names == ["s0"]
  far = _route("a1", True)
  far["v"] = far["v"] * 0 + 35.0  # 15 m/s faster than anything stock drove
  res = sar.compare_route(far, C)
  assert all(e["no_precedent"] for e in res["episodes"])
  assert all(sar.verdict(e) == "no stock precedent" for e in res["episodes"])


def test_compare_flags_harder_and_twitchier_than_stock():
  C = sar.Corpus([_route(f"s{i}", False, seed=i) for i in range(3)])
  A = _route("a0", True, seed=9, brake_gain=2.0)
  k = np.flatnonzero(A["cmd"] < -1.0)
  A["cmd"][k[::10]] += 1.0  # change its mind every half second while braking
  res = sar.compare_route(A, C)
  assert res["episodes"]
  v = [sar.verdict(e) for e in res["episodes"] if e["stock_peak"] < -1.5]
  assert v and all("ours harder" in x and "ours twitchier" in x for x in v)


def test_radar_closing_faster_than_model_is_tagged():
  C = sar.Corpus([_route(f"s{i}", False, seed=i) for i in range(3)])
  A = _route("a0", True, seed=9, brake_gain=2.0)
  assert not any("radar closing > model" in sar.verdict(e) for e in sar.compare_route(A, C)["episodes"])
  A["mv"] = A["mv"] + sar.RADAR_MODEL_GAP + 1.0  # the model thinks the lead is 4 m/s faster than radar does
  eps = sar.compare_route(A, C)["episodes"]
  assert eps and all("radar closing > model" in sar.verdict(e) for e in eps)


def test_lead_brake_onset_needs_a_calm_lead_first():
  R = _route("s0", False, n=400)
  R["vrel"][:] = 0.0
  R["alead"][200:260] = -2.0
  ev = sar.lead_brake_events(R, R["stock"])
  assert [e["t"] for e in ev] == [10.0]
  R["alead"][150:200] = -1.0  # already braking the second before: not an onset
  assert sar.lead_brake_events(R, R["stock"]) == []


def test_stop_profile_samples_the_approach_and_skips_creeps():
  R = _route("s0", False, n=1000)
  n = len(R["t"])
  v = np.clip(8.0 - 1.0 * R["t"], 0.0, None)  # 8 m/s to a stop at t = 8 s, standing after
  v[500:520] = 0.5  # creeps forward at t = 25 s and stops again: not a fresh approach
  R["v"], R["a"], R["cmd"] = v, np.where(v > 0, -1.0, 0.0), np.where(v > 0, -1.0, 0.0)
  R["d"] = np.full(n, 5.0)
  ev = sar.stop_events(R, R["stock"])
  assert len(ev) == 1 and abs(ev[0]["t"] - 7.85) < 0.1  # below STOP_V from 7.85 s
  assert abs(ev[0]["approach_s"] - 3.85) < 0.1 and ev[0]["cmd_at_2"] == -1.0 and ev[0]["reversals"] == 0


def test_release_measures_how_long_the_brake_lingers_after_its_peak():
  t = np.arange(200) / sar.HZ
  sharp = np.where((t >= 2) & (t < 3), -3.0, 0.0)  # full brake for 1 s, then off
  slow = sharp.copy()
  slow[(t >= 3) & (t < 6)] = -2.0  # peaks the same, then holds -2 for 3 s more
  assert abs(sar.release(t, sharp, 0, 199) - 1.0) < 0.06
  assert abs(sar.release(t, slow, 0, 199) - 4.0) < 0.06
  assert np.isnan(sar.release(t, np.full(200, -0.5), 0, 199))  # never braked
  e = {"no_precedent": False, "ours_peak": -3.0, "stock_peak": -3.0, "stock_peak_p25": -3.2, "ours_onset": 2.0,
       "stock_onset": 2.0, "ours_release": 4.0, "stock_release": 1.0, "ours_reversals": 0, "stock_reversals": 0.0,
       "at_ours_peak": {"alead": -3.0, "aleadk": -3.0}}
  assert sar.verdict(e) == "ours lingers"


def test_stock_brake_warning_is_carried_to_the_neighbours_and_unknown_on_old_caches():
  S = [_route(f"s{i}", False, seed=i) for i in range(3)]
  for R in S:
    R["alert"] = (R["vrel"] < -2.5).astype(float)  # stock's dash BRAKE shows on its hardest closing
  A = _route("a0", True, seed=9, brake_gain=2.0)
  eps = sar.compare_route(A, sar.Corpus(S))["episodes"]
  hard = [e for e in eps if e["stock_peak"] < -1.5]
  assert hard and all(e["stock_alert_share"] >= sar.ALERT_SHARE and "stock would warn" in sar.verdict(e) for e in hard)
  assert all(e["dash_alert"] is False for e in eps)  # our own route: dash never warned
  for R in S:
    R["alert"] = R["alert"] * np.nan  # cache from before the column
  eps = sar.compare_route(A, sar.Corpus(S))["episodes"]
  assert eps and all(e["stock_alert_share"] is None and "warn" not in sar.verdict(e) for e in eps)
