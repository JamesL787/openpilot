#!/usr/bin/env python3
"""One lateral scorecard for both controllers (LatControlPID and LatControlClarityEps), from replay and from MetaDrive.

The MetaDrive gain search (branch sim-lat-training) proposes tunes; this tool accepts or rejects them against the
owner's drives, with the metrics STATUS 173/175 used, so a candidate reaches the car only if it does not regress
on real desired-angle traces.

  score FILE_OR_ROUTE_DIR [...]      score a lat_pid_sim-format log as recorded (a real route cache, or a MetaDrive
                                     tools/sim/lat_episode.sh OUTDIR). Nothing is simulated.
  replay [ROUTE ...] --kind K --set KEY=VALUE [...] [--clarity-const NAME=a,b] [--base-kind K --base-set ...]
                                     closed-loop lat_pid_sim runs of a baseline and a candidate on the C020 plant,
                                     per-route metrics and deltas, and a verdict.
  gate  (same arguments as replay)   the same, and exits 0 only on a "pass" verdict.

Metrics (per route; 100 Hz lat_pid_sim frames):
  wobble      rms of the 0.4-3 Hz band of the steering angle (MA 15 - MA 125 frames) on near-straight driving:
              engaged, no press, no lane change, |des| and |angle| < 12 deg for a whole centred 1.51 s window.
              Speed bins 2-5 / 5-8 / 8-12 / 12-20 m/s; NaN under 300 frames. The mask always comes from the
              LOG's desired and measured angle, so baseline and candidate score the same frames.
  turn_err    mean |des - angle| with |des| > 45 deg, engaged, hands off, v > 4 m/s; bins < 12 mph and 12-25 mph
              (4-5.36 and 5.36-11.2 m/s); NaN under 50 frames. turn_sat is the fraction of those frames with
              |output| > 0.99 (authority-limited, not a tracking failure) and turn_ffw the mean feedforward weight
              there (LatControlClarityEps core.ff_weight or LatControlPID eps_ff_weight; replay only).
  dither      reversals per second of the controller output on |des| < 5 deg, hands off, by the wobble bins; a
              reversal needs |out| > 0.01 on both sides (hysteresis), so resting near 0 does not count.
  unwind_lag  mean best time shift (s) of angle onto desired over the unwind half of low-speed turns with a peak
              |des| >= 45 deg (lat_route_check.unwind_episodes).
  err_rms / curve_ratio / lag_s   lat_pid_sim.metrics, by its < 25 / 25-50 / > 50 mph bands (>= 30 s each).
  pullaway    (score only) wobble-band rms of the angle in the 10 s after each start from a stop, engaged, no
              press, |des| < 12 deg. The replay re-syncs the plant to the log below 4 m/s, so this only means
              something on a closed-loop recording (MetaDrive).

Gate (per route, candidate minus baseline, agreed with the NRDR PID session 2026-09-27):
  wobble 5-8 / 8-12 / 12-20 m/s   regress if > max(+0.05 deg, +15 %)       (2-5 is re-synced to the log; reported only)
  turn_err, both bins             regress if > +0.5 deg
  dither, each bin                regress if > +0.1 /s
  err_rms, each band              regress if > +3 %
  an improvement is the same margin the other way. A route regresses if any gated figure does; the verdict is
  "pass" (no route regresses, one or more improve), "neutral" (nothing moves), "mixed" (some routes improve, some
  regress) or "fail". Figures a route's trust tag marks untrusted are reported and not gated.

Toggles: the baseline and the candidate each run with NrdrLatEpsFirmwareFF / NrdrLatPidFirmwareFF forced to match
their kind (pid: EpsFF 0, PidFF as logged unless --set; clarity_eps: EpsFF 1, PidFF 0), so a route logged with one
controller cannot leak it into the other's run. The resolved toggles are printed.

--clarity-const NAME=a,b sets a list constant of selfdrive/controls/lib/nrdr_eps_firmware_ff.py (FF_SPEED_BP, or
FF_ANGLE_GATE_DEG where the branch has it) for the candidate only, in the worker process. Sim only; the car cannot
set these.

Limits: the lat_pid_sim limits apply (desired curvature is exogenous, no model in the loop, one fitted plant;
re-synced to the log below 4 m/s). Every number from this tool is replay/sim evidence only, not driven.
Needs PARAMS_ROOT pointing at a writable directory (the controllers construct Params()). STATUS 176.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # the repo, for openpilot.*
import lat_pid_sim as S
from lat_route_check import unwind_episodes

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PLANT = os.path.join(REPO, "tools/lateral/plants/civic_bosch_c020.json")
# 280/284/285/286: the STATUS 173/175 comparison set; 27a/277/278: 25-50 mph coverage (C020 drives).
DEFAULT_ROUTES = ("00000280--d02d9c2f8e", "00000284--1109db7c4c", "00000285--1cd7a85309", "00000286--ba543e3a3e",
                  "0000027a--4eae257c95", "00000277--2f5fd64a58", "00000278--8f101d683e")
# Where a route's lat_pid_sim cache is looked for (never in the repo).
CACHE_DIRS = ("~/routes/{r}/lat_pid_sim.npz", "/tmp/simr/{r}/lat_pid_sim.npz", "/tmp/epsff/{r}.npz")
# STATUS 172 (NRDR PID session): how far the plant matches each route. Keys are the route counter.
TRUST = {
  "00000280": ("trusted", ()),
  "00000284": ("low band untrusted: the plant trails less than the car", ("turn_err<12mph", "wobble2-5")),
  "00000285": ("sim reads error ~20 % low", ()),
}

WOBBLE_BINS = ((2, 5), (5, 8), (8, 12), (12, 20))
TURN_BINS = (("<12mph", 4.0, 5.36), ("12-25mph", 5.36, 11.2))
WOBBLE_GATED = ("5-8", "8-12", "12-20")
DITHER_DES_DEG = 5.0
DITHER_DEADBAND = 0.01  # command units; below this a sign change is resting noise (280: |out| ~7e-4 at flips)
PULLAWAY_S = 10.0


def band_pass(x):
  f = lambda n: np.convolve(x, np.ones(n) / n, "same")  # noqa: E731
  return f(15) - f(125)


def straight_mask(d):
  ok = ((d["active"] > 0) & (d["pressed"] == 0) & (d["lane_change"] == 0) & (np.abs(d["des_angle"]) < 12) &
        (np.abs(d["angle"]) < 12))
  return np.convolve(ok.astype(float), np.ones(151) / 151, "same") > 0.999


def _nan(x):
  return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def score_arrays(d, ang, des, out=None, ffw=None, pullaway=False):
  """Scorecard of one run: d the route (the log), ang/des the angle and desired angle to score (the log's own, or
  a simulation's), out the controller output, ffw the per-frame feedforward weight."""
  v = d["v"]
  res = {}
  m = straight_mask(d)
  bp = band_pass(ang)
  for lo, hi in WOBBLE_BINS:
    mm = m & (v >= lo) & (v < hi)
    res[f"wobble{lo}-{hi}"] = float(np.sqrt(np.mean(bp[mm] ** 2))) if mm.sum() > 300 else None

  hands = (d["active"] > 0.5) & (d["pressed"] < 0.5) & (v > 4)
  for name, lo, hi in TURN_BINS:
    t = hands & (v >= lo) & (v < hi) & (np.abs(des) > 45)
    ok = t.sum() > 50
    res[f"turn_err{name}"] = float(np.mean(np.abs(des - ang)[t])) if ok else None
    res[f"turn_sat{name}"] = float(np.mean(np.abs(out[t]) > 0.99)) if ok and out is not None else None
    res[f"turn_ffw{name}"] = float(np.mean(ffw[t])) if ok and ffw is not None else None

  if out is not None:
    st = hands & (np.abs(des) < DITHER_DES_DEG)
    flip = reversals(out) & st & np.r_[False, st[:-1]]
    for lo, hi in WOBBLE_BINS[1:]:
      b = (v >= lo) & (v < hi)
      n = (st & b).sum()
      res[f"dither{lo}-{hi}"] = float(flip[b].sum() / (n / 100)) if n > 300 else None

  eps = unwind_episodes(dict(d, angle=ang, des_angle=des))
  res["unwind_lag"] = float(np.mean([e["lag_out"] for e in eps])) if eps else None
  res["unwind_n"] = len(eps)

  for band, r in S.metrics(d, ang, des).items():
    key = band.split()[0]
    res[f"err_rms_{key}"] = r["err_rms"] if r else None
    res[f"curve_ratio_{key}"] = r["curve_ratio"] if r else None
    res[f"lag_s_{key}"] = r["lag_s"] if r else None

  if pullaway:
    res.update(pullaway_wobble(d, ang, des))
  return res


def reversals(out, db=DITHER_DEADBAND):
  """True on the frame the command's sign reverses, with hysteresis: the sign only changes once |out| passes db,
  so a command resting near 0 (|out| ~ 1e-3 on a straight) does not count."""
  s = np.zeros(len(out), dtype=np.int8)
  cur = 0
  for k, x in enumerate(out):
    if x > db:
      cur_new = 1
    elif x < -db:
      cur_new = -1
    else:
      cur_new = cur
    s[k] = cur_new
    cur = cur_new
  return np.r_[False, (s[1:] != s[:-1]) & (s[:-1] != 0)]


def pullaway_wobble(d, ang, des):
  """Wobble-band rms in the PULLAWAY_S after each start from a stop (v < 0.3 m/s, then > 0.5 m/s)."""
  v, n = d["v"], len(d["v"])
  bp = band_pass(ang)
  ok = (d["active"] > 0.5) & (d["pressed"] < 0.5) & (np.abs(des) < 12)
  sel = np.zeros(n, dtype=bool)
  starts, stopped = 0, False
  for k in range(n):
    if v[k] < 0.3:
      stopped = True
    elif stopped and v[k] > 0.5:
      stopped = False
      starts += 1
      sel[k:k + int(PULLAWAY_S * 100)] = True
  sel &= ok
  return {"pullaway_wobble": float(np.sqrt(np.mean(bp[sel] ** 2))) if sel.sum() > 100 else None, "pullaway_n": starts}


# ----------------------------------------------------------------------------------------------
# score: recorded logs

def load_route(spec):
  """A route id (looked up in CACHE_DIRS), a route dir holding lat_pid_sim.npz, or an .npz path."""
  if spec.endswith(".npz"):
    path = spec
  elif os.path.isdir(spec):
    path = os.path.join(spec, "lat_pid_sim.npz")
  else:
    path = next((os.path.expanduser(c.format(r=spec)) for c in CACHE_DIRS if os.path.exists(os.path.expanduser(c.format(r=spec)))),
                None)
    if path is None:
      raise FileNotFoundError(f"no lat_pid_sim cache for {spec} in {CACHE_DIRS}")
  name = os.path.basename(os.path.dirname(path)) if os.path.basename(path) == "lat_pid_sim.npz" else \
    os.path.splitext(os.path.basename(path))[0]
  return S.extract_logs([], name, path), path


def cmd_score(specs):
  rows = {}
  for spec in specs:
    d, path = load_route(spec)
    res = score_arrays(d, d["angle"], d["des_angle"], out=d["out"], pullaway=True)
    ep = os.path.join(os.path.dirname(path), "episode.json")
    if os.path.exists(ep):
      with open(ep) as f:
        j = json.load(f)
      res["offroad"] = j.get("offroad")
      res["engaged_s"] = j.get("engaged_s")
    rows[d["route"]] = res
  return rows


# ----------------------------------------------------------------------------------------------
# replay: closed-loop sim of a baseline and a candidate

class _RecordingController(S.Controller):
  """lat_pid_sim.Controller that also keeps the feedforward weight of each frame."""
  def __init__(self, *a, **k):
    super().__init__(*a, **k)
    self.ffw = []

  def step(self, *a, **k):
    r = super().step(*a, **k)
    lac = getattr(self, "lac", None)
    core = getattr(lac, "core", None)
    self.ffw.append(float(core.ff_weight) if core is not None else float(getattr(lac, "eps_ff_weight", 0.0)))
    _RecordingController.last = self
    return r


def resolve_params(logged, kind, sets):
  p = dict(logged)
  if kind == "pid":
    p["NrdrLatEpsFirmwareFF"] = "0"
    p.setdefault("NrdrLatPidFirmwareFF", "0")
  else:
    p["NrdrLatEpsFirmwareFF"] = "1"
    p["NrdrLatPidFirmwareFF"] = "0"
  p.update(sets)
  return p


def _toggles(p):
  return {k: p.get(k) for k in ("NrdrLatEpsFirmwareFF", "NrdrLatPidFirmwareFF")}


def _run(job):
  route, plant_path, kind, sets, consts = job
  from openpilot.selfdrive.controls.lib import nrdr_eps_firmware_ff as F
  saved = {}
  for name, vals in consts.items():
    if not hasattr(F, name):
      raise AttributeError(f"nrdr_eps_firmware_ff has no {name} on this branch")
    saved[name] = list(getattr(F, name))
    getattr(F, name)[:] = vals
  d, _ = load_route(route)
  params = resolve_params(d["params"], kind, sets)
  S.Controller, orig = _RecordingController, S.Controller
  try:
    ang, des, out, _ = S.simulate(d, S.load_plant(plant_path), overrides=params, kind=kind)
    ffw = np.asarray(_RecordingController.last.ffw)
  finally:
    S.Controller = orig
    for name, vals in saved.items():
      getattr(F, name)[:] = vals
  res = score_arrays(d, ang, des, out=out, ffw=ffw)
  res["toggles"] = _toggles(params)
  return d["route"], res


def _parse_sets(pairs):
  return {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in pairs or [])}


def _parse_consts(pairs):
  return {k.strip(): [float(x) for x in v.split(",")] for k, _, v in (p.partition("=") for p in pairs or [])}


def compare(base, cand, route):
  """Per-figure verdicts for one route: {figure: 'regress'|'improve'|'same'|'untrusted'|'n/a'}."""
  untrusted = TRUST.get(route[:8], ("unrated", ()))[1]
  out = {}

  def judge(key, worse_by, better_by):
    b, c = base.get(key), cand.get(key)
    if b is None or c is None:
      out[key] = "n/a"
    elif key in untrusted:
      out[key] = "untrusted"
    elif c - b > worse_by(b):
      out[key] = "regress"
    elif b - c > better_by(b):
      out[key] = "improve"
    else:
      out[key] = "same"

  for k in WOBBLE_GATED:
    tol = lambda b: max(0.05, 0.15 * b)  # noqa: E731
    judge(f"wobble{k}", tol, tol)
  for name, _, _ in TURN_BINS:
    judge(f"turn_err{name}", lambda b: 0.5, lambda b: 0.5)
  for lo, hi in WOBBLE_BINS[1:]:
    judge(f"dither{lo}-{hi}", lambda b: 0.1, lambda b: 0.1)
  for band in ("low", "standard", "highway"):
    judge(f"err_rms_{band}", lambda b: 0.03 * b, lambda b: 0.03 * b)
  return out


def verdict(per_route):
  states = []
  for figs in per_route.values():
    v = figs.values()
    states.append("regress" if "regress" in v else "improve" if "improve" in v else "same")
  if "regress" in states:
    return "mixed" if "improve" in states else "fail"
  return "pass" if "improve" in states else "neutral"


def cmd_replay(a):
  routes = a.routes or list(DEFAULT_ROUTES)
  sets, base_sets = _parse_sets(a.set), _parse_sets(a.base_set)
  consts, base_consts = _parse_consts(a.clarity_const), _parse_consts(a.base_clarity_const)
  base_kind = a.base_kind or a.kind
  jobs = [(r, a.plant, base_kind, base_sets, base_consts) for r in routes] + \
         [(r, a.plant, a.kind, sets, consts) for r in routes]
  with Pool(a.jobs) as p:
    res = p.map(_run, jobs)
  base = dict(res[:len(routes)])
  cand = dict(res[len(routes):])
  per_route = {r: compare(base[r], cand[r], r) for r in base}
  return {"baseline": {"kind": base_kind, "set": base_sets, "clarity_const": base_consts, "routes": base},
          "candidate": {"kind": a.kind, "set": sets, "clarity_const": consts, "routes": cand},
          "trust": {r: TRUST.get(r[:8], ("unrated", ()))[0] for r in base},
          "figures": per_route, "verdict": verdict(per_route), "plant": a.plant}


# ----------------------------------------------------------------------------------------------
# printing

SHOW = ([f"wobble{lo}-{hi}" for lo, hi in WOBBLE_BINS] + [f"turn_err{n}" for n, _, _ in TURN_BINS] +
        [f"turn_sat{n}" for n, _, _ in TURN_BINS] + [f"turn_ffw{n}" for n, _, _ in TURN_BINS] +
        [f"dither{lo}-{hi}" for lo, hi in WOBBLE_BINS[1:]] + ["unwind_lag"] +
        [f"err_rms_{b}" for b in ("low", "standard", "highway")] + [f"curve_ratio_{b}" for b in ("low", "standard", "highway")])


def _f(x):
  return "   -  " if _nan(x) is None else f"{x:6.2f}"


def print_score(rows):
  keys = SHOW + ["pullaway_wobble", "pullaway_n", "offroad"]
  for route, r in rows.items():
    print(f"== {route}")
    for k in keys:
      if k in r:
        print(f"  {k:22} {r[k] if isinstance(r[k], (bool, int)) or r[k] is None else _f(r[k])}")


def print_replay(rep):
  b, c = rep["baseline"], rep["candidate"]
  print(f"baseline  {b['kind']} set={b['set']} const={b['clarity_const']}")
  print(f"candidate {c['kind']} set={c['set']} const={c['clarity_const']}")
  for r in b["routes"]:
    rb, rc, figs = b["routes"][r], c["routes"][r], rep["figures"][r]
    print(f"== {r}  trust: {rep['trust'][r]}  toggles base {rb['toggles']} cand {rc['toggles']}")
    for k in SHOW:
      if _nan(rb.get(k)) is None and _nan(rc.get(k)) is None:
        continue
      tag = figs.get(k, "")
      print(f"  {k:22} {_f(rb.get(k))} -> {_f(rc.get(k))}  {tag if tag not in ('same', 'n/a') else ''}")
  print(f"verdict: {rep['verdict']}  (replay/sim evidence only, not driven)")


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="cmd", required=True)
  sp = sub.add_parser("score")
  sp.add_argument("routes", nargs="+")
  sp.add_argument("--json")
  for name in ("replay", "gate"):
    rp = sub.add_parser(name)
    rp.add_argument("routes", nargs="*")
    rp.add_argument("--kind", choices=("pid", "clarity_eps"), default="pid")
    rp.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    rp.add_argument("--clarity-const", action="append", default=[], metavar="NAME=a,b")
    rp.add_argument("--base-kind", choices=("pid", "clarity_eps"))
    rp.add_argument("--base-set", action="append", default=[], metavar="KEY=VALUE")
    rp.add_argument("--base-clarity-const", action="append", default=[], metavar="NAME=a,b")
    rp.add_argument("--plant", default=DEFAULT_PLANT)
    rp.add_argument("-j", "--jobs", type=int, default=min(4, os.cpu_count() or 1))
    rp.add_argument("--json")
  a = ap.parse_args(argv)

  if a.cmd == "score":
    out = cmd_score(a.routes)
    print_score(out)
  else:
    out = cmd_replay(a)
    print_replay(out)
  if a.json:
    with open(a.json, "w") as f:
      json.dump(out, f, indent=1, default=float)
  if a.cmd == "gate":
    return 0 if out["verdict"] == "pass" else 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
