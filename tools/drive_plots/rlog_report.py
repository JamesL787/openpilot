#!/usr/bin/env python3
"""Plots, rebuilt from a route's rlogs, for the lateral and longitudinal agents.

  rlog_report.py ROUTE_DIR_OR_RLOG [...] --out DIR [--rate plan|carstate]

ROUTE_DIR is a route cache (ROUTE_DIR/<seg>/rlog.zst, the konik_fetch layout) or one rlog. Writes to DIR (never commit
it: it is route data):

  report.json   one flat JSON: tune snapshot, controller, the Galaxy Plots analysis (lateral / longitudinal / tight
                turns / lateral_detail / driver_takeovers / moments) and the drivePlots messages the car logged.
  samples.csv   every row the analysis used, with seg and route_s.
  moment_windows.csv  +-2 s of rows around every moment in the report (moment index, kind, seconds from it).

Times. Every time an agent sees is route_s: seconds from the route's first logMonoTime (the first message of the
first segment given), plus seg and mm:ss inside that segment. mono_s is the raw logMonoTime in seconds, the join key
against anything else read from the same logs.

Rows are the same columns the car's Galaxy Plots records (starpilot/system/the_galaxy/drive_plots.py COLUMNS, built
by the same build_row), sampled on longitudinalPlan (20 Hz, what the car records) or, with --rate carstate, on
carState (100 Hz; the analysis thresholds were written for 20 Hz, so compare like with like).

Tune snapshot (initData of the first segment): gitCommit / gitBranch, every Nrdr* and HondaOverride* key in
common/params_keys.h ("missing" when the log has no entry), the lane-centring and delay keys, BlotV3,
openpilotLongitudinalControl (carParams), the sha1 of selfdrive/controls/lib/latcontrol_clarity_eps.py at the logged
commit (from this repo's git; "working tree" when the commit is not here), liveDelay.lateralDelay (median and last)
and the last liveTorqueParameters. The controller is tools/lateral/lat_score.py's detect rule (route_verdict).

The drivePlots messages are the JSON the car publishes on customReservedRawData0 while it records (schema
drivePlots/1): a start snapshot, moments and takeovers as they finish, and a summary every few minutes. They are a
cross-check; everything in the analysis is rebuilt here from the raw signals.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "lateral"))
sys.path.insert(1, ROOT)

from openpilot.starpilot.system.the_galaxy import drive_plots as dp  # noqa: E402

CLARITY_FILE = "selfdrive/controls/lib/latcontrol_clarity_eps.py"
EXTRA_KEYS = ("LaneCentering", "LaneCenteringE2EAuthority", "LaneCenterOffset", "SteerDelay", "BlotV3", "BoschARadar",
              "ExperimentalMode", "ConditionalExperimental", "ConditionalChill", "LongitudinalPersonality")
RLOG_SERVICE = dp.RLOG_SERVICE
MOMENT_WINDOW_S = 2.0          # moment_windows.csv: rows this far either side of each moment


def segments(spec):
  if os.path.isfile(spec):
    return [spec]
  segs = []
  for name in sorted(os.listdir(spec), key=lambda x: int(x) if x.isdigit() else -1):
    for fn in ("rlog.zst", "rlog.bz2", "rlog"):
      if name.isdigit() and os.path.isfile(os.path.join(spec, name, fn)):
        segs.append(os.path.join(spec, name, fn))
        break
  return segs


def agent_param_keys():
  try:
    with open(os.path.join(ROOT, "common", "params_keys.h")) as f:
      text = f.read()
  except OSError:
    return []
  return sorted(set(re.findall(r'\{"((?:Nrdr|HondaOverride)\w*)"', text)))


def clarity_sha1(commit):
  if commit:
    try:
      blob = subprocess.run(["git", "-C", ROOT, "show", f"{commit}:{CLARITY_FILE}"], capture_output=True, timeout=20)
      if blob.returncode == 0:
        return {"sha1": hashlib.sha1(blob.stdout).hexdigest(), "from": f"git {commit[:12]}"}
      missing = subprocess.run(["git", "-C", ROOT, "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True, timeout=20)
      if missing.returncode == 0:
        return {"sha1": None, "from": f"git {commit[:12]} (file not in that commit)"}
    except Exception:
      pass
  try:
    with open(os.path.join(ROOT, CLARITY_FILE), "rb") as f:
      return {"sha1": hashlib.sha1(f.read()).hexdigest(), "from": "working tree (the logged commit is not in this repo)"}
  except OSError:
    return {"sha1": None, "from": "not found"}


class ReplaySM:
  """The part of cereal's SubMaster build_row reads, fed from log messages."""

  def __init__(self, services):
    from cereal import log
    self.services = services
    self.recv_frame = dict.fromkeys(services, 0)
    self.logMonoTime = dict.fromkeys(services, 0)
    self.updated = dict.fromkeys(services, False)
    ev = log.Event.new_message()
    self.data = {}
    for s in services:
      try:
        ev.init(s)
        self.data[s] = getattr(ev, s).as_reader()
      except Exception:
        self.data[s] = None

  def feed(self, msg):
    s = msg.which()
    self.data[s] = getattr(msg, s)
    self.recv_frame[s] += 1
    self.logMonoTime[s] = msg.logMonoTime

  def __getitem__(self, s):
    return self.data[s]


def _mmss(s):
  return f"{int(s // 60):02d}:{s % 60:04.1f}"


def replay(seg_paths, rate="plan"):
  from openpilot.tools.lib.logreader import LogReader
  services = list(dp.DrivePlots.SERVICES)
  trigger = "longitudinalPlan" if rate == "plan" else "carState"
  sm = ReplaySM(services)
  rows, seg_of_row, seg_starts = [], [], []
  init, car_params, delays, torque, messages = None, None, [], None, []
  route_t0 = None
  for si, path in enumerate(seg_paths):
    seg_starts.append(None)
    for msg in LogReader(path):
      w = msg.which()
      if si == 0:
        route_t0 = msg.logMonoTime if route_t0 is None else min(route_t0, msg.logMonoTime)
      # Every segment repeats the route's initData (and carParams) with their original logMonoTime, so a segment
      # starts at its first carState, not its first message.
      if seg_starts[-1] is None and w == "carState":
        seg_starts[-1] = msg.logMonoTime
      if w == "initData" and init is None:
        init = msg.initData
        init = {"gitCommit": init.gitCommit, "gitBranch": init.gitBranch,
                "params": {e.key: e.value for e in init.params.entries}}
      elif w == "carParams" and car_params is None:
        car_params = {"carFingerprint": str(msg.carParams.carFingerprint),
                      "openpilotLongitudinalControl": bool(msg.carParams.openpilotLongitudinalControl)}
      elif w == "liveDelay":
        delays.append(float(msg.liveDelay.lateralDelay))
      elif w == "liveTorqueParameters":
        lt = msg.liveTorqueParameters
        torque = {"liveValid": bool(lt.liveValid), "latAccelFactorFiltered": round(float(lt.latAccelFactorFiltered), 4),
                  "frictionCoefficientFiltered": round(float(lt.frictionCoefficientFiltered), 4),
                  "offsetFiltered": round(float(lt.latAccelOffsetFiltered), 4)}
      elif w == RLOG_SERVICE:
        try:
          m = json.loads(bytes(msg.customReservedRawData0))
          if isinstance(m, dict) and m.get("schema") == dp.RLOG_SCHEMA:
            m["logged_route_s"] = round((msg.logMonoTime - route_t0) / 1e9, 2)
            messages.append(m)
        except Exception:
          pass
      if w in sm.data:
        sm.feed(msg)
        if w == trigger and sm.recv_frame["longitudinalPlan"] and sm.recv_frame["controlsState"]:
          row = dp.build_row(sm)
          if rate != "plan":
            row[0] = msg.logMonoTime / 1e9
          rows.append(row)
          seg_of_row.append(si)
  if seg_starts and seg_starts[0] is not None:
    seg_starts[0] = min(seg_starts[0], route_t0)
  return {"rows": np.asarray(rows, dtype=float).reshape(-1, len(dp.COLUMNS)), "seg": np.asarray(seg_of_row, dtype=int),
          "seg_starts": seg_starts, "route_t0": route_t0, "init": init, "car_params": car_params, "delays": delays,
          "torque": torque, "messages": messages}


def tune_snapshot(r):
  init = r["init"] or {"gitCommit": None, "gitBranch": None, "params": {}}
  p = init["params"]

  def val(k):
    if k not in p:
      return "missing"
    v = p[k]
    return v.decode(errors="replace") if isinstance(v, bytes) else v

  keys = agent_param_keys()
  snap = {"gitCommit": init["gitCommit"], "gitBranch": init["gitBranch"]}
  snap.update({k: val(k) for k in [*keys, *EXTRA_KEYS]})
  snap["openpilotLongitudinalControl"] = (r["car_params"] or {}).get("openpilotLongitudinalControl")
  snap["car"] = (r["car_params"] or {}).get("carFingerprint")
  sha = clarity_sha1(init["gitCommit"])
  snap["latcontrol_clarity_eps_sha1"], snap["latcontrol_clarity_eps_sha1_from"] = sha["sha1"], sha["from"]
  d = r["delays"]
  snap["lateralDelay_median"] = round(float(np.median(d)), 3) if d else None
  snap["lateralDelay_last"] = round(d[-1], 3) if d else None
  snap["liveTorqueParameters"] = r["torque"]
  return snap


def controller(seg_paths):
  try:
    import lat_score
    segs = [lat_score.detect_segment(p) for p in seg_paths]
    ctrl, why = lat_score.route_verdict(segs)
    return {"controller": ctrl, "reasons": why, "segments": segs}
  except Exception as e:
    return {"controller": None, "reasons": [f"detect failed: {e}"], "segments": []}


def _place(mono_s, r):
  """route_s, seg and mm:ss for a monotonic time in seconds."""
  ns = mono_s * 1e9
  starts = r["seg_starts"]
  seg = max([i for i, s in enumerate(starts) if s is not None and s <= ns] or [0])
  return {"route_s": round((ns - r["route_t0"]) / 1e9, 2), "seg": seg, "seg_mmss": _mmss((ns - starts[seg]) / 1e9)}


def _label_times(obj, r):
  """Add route_s / seg / seg_mmss beside every mono_s, and drop the drive-relative t that could be misread."""
  if isinstance(obj, dict):
    out = {k: _label_times(v, r) for k, v in obj.items()}
    if isinstance(obj.get("mono_s"), (int, float)):
      out.update(_place(obj["mono_s"], r))
      out.pop("t", None)
      out.pop("peak_t", None)
      out.pop("release_t", None)
    return out
  if isinstance(obj, list):
    return [_label_times(v, r) for v in obj]
  return obj


def report(seg_paths, rate="plan", detect=True):
  r = replay(seg_paths, rate)
  rows = r["rows"]
  snap = tune_snapshot(r)
  ctrl = controller(seg_paths) if detect else {"controller": None, "reasons": ["not run (--no-detect)"], "segments": []}
  dp_ctrl = {"clarity_eps": dp.CONTROLLER_CLARITY_EPS, "pid": dp.CONTROLLER_NRDR_PID}.get(ctrl["controller"])
  delay = snap["lateralDelay_median"]
  a = dp.analyze(rows, controller=dp_ctrl, lateral_delay=delay, git_commit=snap["gitCommit"]) if len(rows) > 1 else {"status": "no samples"}
  a.pop("overview", None)
  a = _label_times(dp._json_safe(a), r)
  gaps = None
  if len(rows) > 1:
    c = dp._as_arrays(rows)
    age = c["cs_age_ms"][np.isfinite(c["cs_age_ms"])]
    gaps = {"max_controlsState_age_ms": round(float(np.max(age)), 1) if len(age) else None,
            "frames_over_100ms": int(np.count_nonzero(age > dp.agents.STALL_MS)) if len(age) else None,
            "note": "age of the last controlsState at each sampled frame; > 100 ms is a dropped / stalled frame"}
  return {
    "schema": "drivePlotsReport/1",
    "segments": [os.path.relpath(p) for p in seg_paths],
    "rate": "longitudinalPlan 20 Hz" if rate == "plan" else "carState 100 Hz",
    "time_base": "route_s = seconds from the route's first logMonoTime; seg + seg_mmss inside the segment",
    "tune": snap,
    "controller": {k: ctrl[k] for k in ("controller", "reasons")},
    "controller_segments": ctrl["segments"],
    "controls_gaps": gaps,
    "analysis": a,
    "car_messages": _label_times(r["messages"], r),
  }, r


def write(out_dir, rep, r):
  os.makedirs(out_dir, exist_ok=True)
  with open(os.path.join(out_dir, "report.json"), "w") as f:
    json.dump(dp._json_safe(rep), f, indent=1, allow_nan=False)
  rows = r["rows"]
  with open(os.path.join(out_dir, "samples.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["seg", "route_s", *dp.COLUMNS])
    for seg, row in zip(r["seg"], rows, strict=True):
      w.writerow([int(seg), round(row[0] - r["route_t0"] / 1e9, 3), *("" if x != x else dp._fmt(x) for x in row)])
  write_moment_windows(os.path.join(out_dir, "moment_windows.csv"), rep, r)


def write_moment_windows(path, rep, r, half_s=MOMENT_WINDOW_S):
  """Every moment in the report with +-half_s of rows around it (Bob, James): moment index, kind, seconds from the
  moment, then the samples.csv columns. Offline only; the car keeps just the moment and the UI zooms to it."""
  rows = r["rows"]
  events = [e for e in ((rep.get("analysis") or {}).get("events") or []) if e.get("mono_s") is not None]
  t = np.array([row[0] for row in rows])
  with open(path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["moment", "kind", "rel_s", "route_s", *dp.COLUMNS])
    for k, e in enumerate(events):
      a, b = np.searchsorted(t, e["mono_s"] - half_s), np.searchsorted(t, e["mono_s"] + half_s, side="right")
      for row in rows[a:b]:
        w.writerow([k, e["kind"], round(row[0] - e["mono_s"], 3), round(row[0] - r["route_t0"] / 1e9, 3),
                    *("" if x != x else dp._fmt(x) for x in row)])


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("routes", nargs="+", help="route cache dir(s) or rlog file(s); several are one route, in order")
  ap.add_argument("--out", required=True, help="output dir (route data: do not commit)")
  ap.add_argument("--rate", choices=("plan", "carstate"), default="plan")
  ap.add_argument("--no-detect", action="store_true", help="skip the controller detection (a second pass over the logs)")
  a = ap.parse_args(argv)
  seg_paths = [p for spec in a.routes for p in segments(spec)]
  if not seg_paths:
    ap.error("no rlogs found")
  rep, r = report(seg_paths, a.rate, detect=not a.no_detect)
  write(a.out, rep, r)
  an = rep["analysis"]
  print(f"{len(r['rows'])} rows from {len(seg_paths)} segment(s); controller {rep['controller']['controller']}; "
        f"{len(an.get('events') or [])} moments, {((an.get('driver_takeovers') or {}).get('summary') or {}).get('count')} "
        f"takeovers, {len(rep['car_messages'])} drivePlots messages from the car -> {a.out}")


if __name__ == "__main__":
  main()
