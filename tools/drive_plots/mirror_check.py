#!/usr/bin/env python3
"""Check that Plots mirrors the rlogs: its samples, its lateral figures and what the car published.

  python tools/drive_plots/mirror_check.py <route dir | rlog ...> [--out DIR]

Four checks, each on the same logs:

  columns    every drive_plots.build_row column against the rlog field it names, read here on its own at each
             longitudinalPlan (the moment the car takes a row). A mismatch is a column reading the wrong field.
  frames     Plots' wheel angle, desired angle, hands-on flag, pidState.active and lane-change state against
             tools/lateral/lat_pid_sim.extract_logs (the frames lat_score scores), frame by frame.
  lat_score  tools/lateral/lat_score.score_arrays (the lateral agents' scorecard) beside Plots' turn table
             ("scorecard" figures, the same mask) and wobble.
  car        the drivePlots messages the car put in the rlog beside the moments and takeovers found offline.

Differences between 20 Hz Plots rows and 100 Hz lat_score frames are expected to be small, not zero; the
tolerances are printed with each line. Route data stays out of the repo.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "lateral"))
sys.path.insert(1, ROOT)

from openpilot.starpilot.system.the_galaxy import drive_plots as dp  # noqa: E402
from openpilot.starpilot.system.the_galaxy import drive_plots_agents as agents  # noqa: E402
from openpilot.tools.drive_plots.rlog_report import ReplaySM, segments  # noqa: E402

NAN = float("nan")
# Plots' turn scorecard vs lat_score: mean |error| in degrees; wobble: rms in degrees. Absolute or relative.
TURN_TOL = (1.5, 0.10)
WOBBLE_TOL = (0.03, 0.15)
MOMENT_MATCH_S = 1.5


def _f(x):
  try:
    x = float(x)
  except (TypeError, ValueError):
    return NAN
  return x if math.isfinite(x) else NAN


def _lead(rs, attr):
  return getattr(rs, attr) if rs is not None and getattr(rs, attr).status else None


# Each column read straight from the rlog. `m` is the latest message of each service (absent: not received yet).
# Written from the cereal field names, not from build_row, so a slip in either shows up as a mismatch.
def expected(m, plan_mono):
  cs, cc, car, plan = m["controlsState"], m.get("carControl"), m["carState"], m["longitudinalPlan"]
  rs, md, co = m.get("radarState"), m.get("modelV2"), m.get("carOutput")
  sd, sp, ls = m.get("selfdriveState"), m.get("starpilotPlan"), m.get("starpilotLateralState")
  v = max(0.0, car.vEgo)
  lcs = cs.lateralControlState
  which = lcs.which()
  st = getattr(lcs, which)
  pid = lcs.pidState if which == "pidState" else None
  l1, l2 = _lead(rs, "leadOne"), _lead(rs, "leadTwo")
  e = {
    "t": plan_mono / 1e9, "v": v, "a_ego": car.aEgo,
    "enabled": int(cc is not None and cc.enabled), "lat_active": int(cc is not None and cc.latActive),
    "long_active": int(cc is not None and cc.longActive),
    "steer_pressed": int(car.steeringPressed), "gas_pressed": int(car.gasPressed), "brake_pressed": int(car.brakePressed),
    "lat_des": cs.desiredCurvature * v * v, "lat_act": cs.curvature * v * v,
    "long_des": plan.aTarget, "long_act": car.aEgo,
    "lat_p": st.p if which in ("pidState", "torqueState") else 0.0,
    "lat_i": st.i if which in ("pidState", "torqueState") else 0.0,
    "lat_d": st.d if which == "torqueState" else 0.0,
    "lat_f": st.f if which in ("pidState", "torqueState") else 0.0,
    "long_up": cs.upAccelCmd, "long_ui": cs.uiAccelCmd, "long_uf": cs.ufAccelCmd,
    "lat_sat": int(getattr(st, "saturated", False)),
    "ang_des": st.steeringAngleDesiredDeg if which in ("pidState", "angleState") else 0.0,
    "ang_act": car.steeringAngleDeg, "ang_ok": int(which in ("pidState", "angleState")),
    "lead_d": l1.dRel if l1 else 0.0, "lead_v": l1.vLead if l1 else 0.0, "lead_src": (1 if l1.radar else 2) if l1 else 0,
    "steer_tq": car.steeringTorque, "steer_tq_eps": car.steeringTorqueEps, "steer_rate": car.steeringRateDeg,
    "blinker": int(car.leftBlinker or car.rightBlinker),
    "tq_req": cc.actuators.torque if cc is not None else NAN,
    "tq_out": co.actuatorsOutput.torque if co is not None else NAN,
    "lat_out": pid.output if pid is not None else NAN, "ang_err": pid.angleError if pid is not None else NAN,
    "pid_active": int(pid.active) if pid is not None else NAN,
    "ff_active": int(ls.epsFfActive) if ls is not None else NAN, "ff_w": ls.epsFfWeight if ls is not None else NAN,
    "ff": ls.epsFfFeedforward if ls is not None else NAN,
    "lane_off": NAN, "lane_w": NAN, "lane_prob": NAN, "lane_change": NAN,
    "cs_age_ms": max(0.0, (plan_mono - m["_mono"]["controlsState"]) / 1e6),
    "a_cmd": cc.actuators.accel if cc is not None else NAN,
    "should_stop": int(plan.shouldStop), "fcw": int(plan.fcw), "has_lead": int(plan.hasLead),
    "exp_mode": int(sd.experimentalMode) if sd is not None else NAN,
    "t_follow": sp.tFollow if sp is not None else NAN, "tracking_lead": int(sp.trackingLead) if sp is not None else NAN,
    "standstill": int(car.standstill),
    "lead_id": l1.radarTrackId if l1 else NAN, "lead_y": l1.yRel if l1 else NAN, "lead_vrel": l1.vRel if l1 else NAN,
    "lead_a": l1.aLeadK if l1 else NAN, "lead_prob": l1.modelProb if l1 else NAN,
    "lead_meas": int(l1.measuredRadar) if l1 else NAN, "lead_vrr": l1.vRelRangeDerived if l1 else NAN,
    "lead2_on": int(l2 is not None) if rs is not None else NAN,
    "lead2_d": l2.dRel if l2 else NAN, "lead2_v": l2.vLead if l2 else NAN, "lead2_id": l2.radarTrackId if l2 else NAN,
    "mlead_p": NAN, "mlead_x": NAN, "mlead_y": NAN, "mlead_v": NAN, "mlead_a": NAN,
  }
  e["long_state"] = dp.LONG_STATES.get(str(cs.longControlState), 0)
  if md is not None:
    left, right, probs = md.laneLines[1].y, md.laneLines[2].y, md.laneLineProbs
    if len(md.laneLines) >= 3 and len(left) and len(right) and len(probs) >= 3:
      e["lane_off"] = (left[0] + right[0]) / 2.0   # y is + = right: the lane centre's y is the car left of it
      e["lane_w"] = right[0] - left[0]
      e["lane_prob"] = min(probs[1], probs[2])
    e["lane_change"] = int(md.meta.laneChangeState.raw)
    if len(md.leadsV3):
      ld = md.leadsV3[0]
      e["mlead_p"] = ld.prob
      for k, arr in (("mlead_x", ld.x), ("mlead_y", ld.y), ("mlead_v", ld.v), ("mlead_a", ld.a)):
        e[k] = arr[0] if len(arr) else NAN
  return [_f(e[c]) for c in dp.COLUMNS]


def read(seg_paths):
  """One pass: Plots rows (build_row on a ReplaySM, as rlog_report does), the same rows read here, and for each row
  the lat_pid_sim frame it follows. lat_pid_sim adds a frame at each controlsState with pidState once carState and
  liveParameters have arrived; counting the same way in log order lines the two up exactly (logMonoTime is not
  strictly ordered in an rlog, so matching by time can land a frame off)."""
  from openpilot.tools.lib.logreader import LogReader
  services = list(dp.DrivePlots.SERVICES)
  sm = ReplaySM(services)
  latest = {"_mono": {}}
  rows, exp, messages, frame_of_row = [], [], [], []
  n_frames, have_lp = 0, False
  for path in seg_paths:
    for msg in LogReader(path):
      w = msg.which()
      if w == "liveParameters":
        have_lp = True
      elif w == "controlsState" and have_lp and "carState" in latest and msg.controlsState.lateralControlState.which() == "pidState":
        n_frames += 1
      if w == dp.RLOG_SERVICE:
        try:
          j = json.loads(bytes(msg.customReservedRawData0))
          if isinstance(j, dict) and j.get("schema") == dp.RLOG_SCHEMA:
            messages.append(j)
        except Exception:
          pass
      if w not in sm.data:
        continue
      sm.feed(msg)
      latest[w] = getattr(msg, w)
      latest["_mono"][w] = msg.logMonoTime
      if w == "longitudinalPlan" and "controlsState" in latest and "carState" in latest:
        rows.append(dp.build_row(sm))
        exp.append(expected(latest, msg.logMonoTime))
        frame_of_row.append(n_frames - 1)
  n = len(dp.COLUMNS)
  return (np.asarray(rows, dtype=float).reshape(-1, n), np.asarray(exp, dtype=float).reshape(-1, n),
          messages, np.asarray(frame_of_row, dtype=int))


def check_columns(rows, exp):
  out = {}
  for i, name in enumerate(dp.COLUMNS):
    a, b = rows[:, i], exp[:, i]
    both_nan = np.isnan(a) & np.isnan(b)
    one_nan = np.isnan(a) ^ np.isnan(b)
    tol = 0.006 + 1e-4 * np.abs(np.nan_to_num(b))   # build_row rounds to 2-4 places
    bad = one_nan | (~both_nan & ~one_nan & (np.abs(np.nan_to_num(a) - np.nan_to_num(b)) > tol))
    diff = np.abs(a - b)[~np.isnan(a) & ~np.isnan(b)]
    out[name] = {"rows": len(a), "mismatches": int(np.count_nonzero(bad)),
                 "max_diff": round(float(diff.max()), 4) if len(diff) else None,
                 "first_bad_row": int(np.argmax(bad)) if bad.any() else None}
  return out


def check_frames(rows, d, frame_of_row):
  """Plots rows against the lat_pid_sim frame of the controlsState each row was built from."""
  c = dp._as_arrays(rows)
  k = frame_of_row
  ok = (k >= 0) & (k < len(d["t"])) & (c["ang_ok"] > 0.5)
  k = k[ok]
  # lat_pid_sim pairs each controlsState with the carState before it; a row can hold a newer carState, so the
  # wheel angle is allowed one carState frame (10 ms) of motion.
  slack = 0.5 + 0.02 * np.abs(d["rate"][k])
  pairs = {"ang_act": ("angle", slack), "ang_des": ("des_angle", 0.5), "steer_pressed": ("pressed", 0.5),
           "pid_active": ("active", 0.5), "lane_change": ("lane_change", 0.5)}
  out = {"rows_compared": int(len(k))}
  for col, (field, tol) in pairs.items():
    a = c[col][ok]
    fin = np.isfinite(a)
    tol = tol[fin] if isinstance(tol, np.ndarray) else tol
    agree = np.abs(a[fin] - d[field][k][fin]) <= tol
    out[col] = {"lat_pid_sim": field, "rows": int(fin.sum()),
                "agree_frac": round(float(agree.mean()), 4) if fin.any() else None}
  return out


def _close(a, b, tol):
  if a is None or b is None:
    return a is None and b is None
  return abs(a - b) <= max(tol[0], tol[1] * abs(b))


def check_lat_score(rows, d, controller=None):
  from openpilot.tools.lateral import lat_score as LS
  ls = LS.score_arrays(d, d["angle"], d["des_angle"], out=d["out"])
  turns = (dp.analyze(rows, controller=controller, detail=False).get("lateral") or {}).get("turns") or {}
  lines = []
  bins = {(b["lo_ms"], b["hi_ms"]): b for b in turns.get("bins") or []}
  for name, lo, hi in LS.TURN_BINS:
    b = next((x for (blo, bhi), x in bins.items() if abs(bhi - hi) < 0.05), None)
    sc = (b or {}).get("scorecard") or {}
    for part in ("err", "past", "trail"):
      a, p = ls.get(f"turn_{part}{name}"), sc.get(part)
      lines.append({"metric": f"turn_{part} {name}", "lat_score": _round(a), "plots": p, "tol": TURN_TOL,
                    "match": _close(p, a, TURN_TOL)})
    if b is not None and b.get("err") is not None:
      lines.append({"metric": f"turn_err {name}, Plots without the second after a grab", "lat_score": None,
                    "plots": b["err"], "tol": None, "match": None})
  wob = {(b["lo_ms"], b["hi_ms"]): b["rms_deg"] for b in turns.get("wobble") or []}
  for lo, hi in LS.WOBBLE_BINS:
    if f"{lo}-{hi}" not in LS.WOBBLE_GATED:
      continue
    a, p = ls.get(f"wobble{lo}-{hi}"), wob.get((lo, hi))
    lines.append({"metric": f"wobble {lo}-{hi} m/s", "lat_score": _round(a, 3), "plots": p, "tol": WOBBLE_TOL,
                  "match": _close(p, a, WOBBLE_TOL)})
  return lines


def _round(x, n=1):
  return None if x is None else round(float(x), n)


def check_car(rows, messages):
  """The car's drivePlots moments and takeovers beside the same detectors run on the whole drive offline. The car
  runs them on a rolling window, so a moment right at a window edge can land on one side only."""
  kinds = {}
  car = [(m.get("kind") if m.get("type") == "moment" else "takeover", m.get("mono_s")) for m in messages
         if m.get("type") in ("moment", "takeover") and m.get("mono_s") is not None]
  off = []
  if len(rows) > 1:
    c = dp._as_arrays(rows)
    off = [(e["kind"], e["mono_s"]) for e in agents.long_moments(c, t0=c["t"][0])]
    off += [("takeover", e["mono_s"]) for e in agents.takeovers(c, t0=c["t"][0])["episodes"]]
  for kind in sorted({k for k, _ in car} | {k for k, _ in off}):
    a = sorted(t for k, t in car if k == kind)
    b = sorted(t for k, t in off if k == kind)
    matched = sum(1 for x in a if any(abs(x - y) <= MOMENT_MATCH_S for y in b))
    kinds[kind] = {"car": len(a), "offline": len(b), "matched": matched}
  return {"car_messages": len(messages), "kinds": kinds}


def run(seg_paths, name="route", controller=None):
  from openpilot.tools.lateral import lat_pid_sim as S
  rows, exp, messages, frame_of_row = read(seg_paths)
  res = {"schema": "drivePlotsMirror/1", "rows": len(rows), "columns": check_columns(rows, exp),
         "car": check_car(rows, messages)}
  try:
    d = S.extract_logs(seg_paths, name)
  except RuntimeError as e:
    res["frames"] = res["lat_score"] = {"skipped": str(e)}
    return res
  if len(d["t"]) and len(rows) > 1:
    res["frames"] = check_frames(rows, d, frame_of_row)
    res["lat_score"] = check_lat_score(rows, d, controller)
  return res


def print_report(res):
  bad = {k: v for k, v in res["columns"].items() if v["mismatches"]}
  print(f"columns: {len(res['columns'])} checked on {res['rows']} rows; "
        + ("all match the rlog fields" if not bad else f"{len(bad)} differ"))
  for k, v in bad.items():
    print(f"  {k:14s} {v['mismatches']} rows differ, max diff {v['max_diff']}, first at row {v['first_bad_row']}")
  fr = res.get("frames") or {}
  if "skipped" in fr:
    print(f"frames: skipped ({fr['skipped']})")
  elif fr:
    print(f"frames: {fr['rows_compared']} Plots rows beside lat_pid_sim's frames")
    for k, v in fr.items():
      if isinstance(v, dict):
        print(f"  {k:14s} vs {v['lat_pid_sim']:12s} agree {v['agree_frac']}")
  ls = res.get("lat_score")
  if isinstance(ls, list):
    print("lat_score vs Plots:")
    for x in ls:
      flag = "" if x["match"] is None else ("  ok" if x["match"] else "  DIFFERS")
      print(f"  {x['metric']:52s} lat_score {str(x['lat_score']):>6s}  plots {str(x['plots']):>6s}{flag}")
  car = res["car"]
  print(f"car: {car['car_messages']} drivePlots messages in the rlog")
  for k, v in car["kinds"].items():
    print(f"  {k:22s} car {v['car']:3d}  offline {v['offline']:3d}  matched {v['matched']}")


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("routes", nargs="+", help="route cache dir(s) or rlog file(s); several are one route, in order")
  ap.add_argument("--out", help="also write mirror.json here (route data: do not commit)")
  a = ap.parse_args(argv)
  seg_paths = [p for spec in a.routes for p in segments(spec)]
  if not seg_paths:
    ap.error("no rlogs found")
  res = run(seg_paths, os.path.basename(os.path.normpath(a.routes[0])))
  print_report(res)
  if a.out:
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "mirror.json"), "w") as f:
      json.dump(dp._json_safe(res), f, indent=1)
  bad = any(v["mismatches"] for v in res["columns"].values())
  return 1 if bad else 0


if __name__ == "__main__":
  sys.exit(main())
