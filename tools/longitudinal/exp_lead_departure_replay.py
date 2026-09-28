#!/usr/bin/env python3
"""Open-loop replay of the experimental-mode lead-departure assist (STATUS 136b-136g) on logged drives.

Runs the planner's own get_exp_lead_departure_weight / apply_exp_lead_departure and the same weight
filter on each longitudinalPlan frame while engaged in Experimental Mode, using the logged lead
(radarState.leadOne), e2e target (modelV2.action.desiredAcceleration, rlogs only), MPC estimate
(get_accel_from_plan on longitudinalPlan.speeds/accels at 0.5 s) and starpilotPlan.tFollow. The logged
arbitration before the assist is min(e2e, MPC); the planner's later caps are not replayed. Open loop: the car does not respond to
the lifted target, so this shows where and how much the assist would act, not what the car would do.

Usage: exp_lead_departure_replay.py ROUTE_DIR [ROUTE_DIR ...] [--presses FILE]
  --presses: census rows (gas_override_census.py output) to check coverage of e2e-limited presses.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

import numpy as np

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan
from openpilot.selfdrive.controls.lib.longitudinal_planner import EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE, LongitudinalPlanner
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.tools.lib.logreader import _LogFileReader

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
ACTION_T = 0.5
ACT = 0.05  # m/s^2 lift that counts as acting


def rlog_segments(route_dir):
  segs = [s for s in os.listdir(route_dir) if s.isdigit() and os.path.exists(os.path.join(route_dir, s, "rlog.zst"))]
  return [(int(s), os.path.join(route_dir, s, "rlog.zst")) for s in sorted(segs, key=int)]


def route_t0(route_dir):
  """First logMonoTime of segment 0 (rlog or qlog), the clock gas_override_census.py prints."""
  for name in ("rlog.zst", "qlog.zst"):
    path = os.path.join(route_dir, "0", name)
    if os.path.exists(path):
      for m in _LogFileReader(path):
        return m.logMonoTime
  return None


def replay_route(route_dir):
  frames = []  # (route_t, seg, lift, e2e, mpc, vRel, aLeadK)
  t0 = route_t0(route_dir)
  for seg, path in rlog_segments(route_dir):
    st = dict(enabled=False, exp=False, e2e=None, stop=False, hold=False, tf=1.45, v=0.0, lead=None)
    planner = SimpleNamespace(lead_one=None, dt=DT_MDL, exp_lead_departure_weight=0.0, exp_lead_departure_lift=0.0)
    try:
      for m in _LogFileReader(path):
        k = m.which()
        if t0 is None:
          t0 = m.logMonoTime - int(seg * 60e9)
        if k == "selfdriveState":
          st["enabled"], st["exp"] = m.selfdriveState.enabled, m.selfdriveState.experimentalMode
        elif k == "modelV2":
          st["e2e"], st["stop"] = m.modelV2.action.desiredAcceleration, m.modelV2.action.shouldStop
        elif k == "starpilotPlan":
          sp = m.starpilotPlan
          st["tf"] = sp.tFollow
          st["hold"] = bool(getattr(sp, "forcingStop", False) or getattr(sp, "redLight", False))
        elif k == "carState":
          st["v"] = m.carState.vEgo
        elif k == "radarState":
          st["lead"] = m.radarState.leadOne
        elif k == "longitudinalPlan":
          lp = m.longitudinalPlan
          if not (st["enabled"] and st["exp"]) or st["e2e"] is None or st["lead"] is None or len(lp.speeds) != CONTROL_N:
            planner.exp_lead_departure_weight = planner.exp_lead_departure_lift = 0.0
            continue
          mpc = get_accel_from_plan(list(lp.speeds), list(lp.accels), CONTROL_N_T_IDX, action_t=ACTION_T)[0]
          base = min(mpc, st["e2e"])  # the planner's e2e/MPC arbitration, before its later caps
          planner.lead_one = st["lead"]
          lift = LongitudinalPlanner.update_exp_lead_departure(planner, base, st["e2e"], mpc, st["v"], st["tf"],
                                                               bool(st["stop"] or st["hold"])) - base
          frames.append(((m.logMonoTime - t0) / 1e9, seg, lift, st["e2e"], mpc,
                         st["lead"].vRel if st["lead"].status else np.nan, st["lead"].aLeadK))
    except Exception as e:  # truncated segment
      print(f"  warn {path}: {e}", file=sys.stderr)
  return frames


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("routes", nargs="+")
  ap.add_argument("--presses")
  args = ap.parse_args()
  presses = defaultdict(list)
  if args.presses:
    for line in open(args.presses):
      f = line.split()
      if len(f) > 11 and f[3] == "e2e_slow_accel" and "+" in f[10]:
        mm, ss = f[2].split(":")
        presses[f[0]].append(int(mm) * 60 + float(ss))
  allf, covered, total_p = [], 0, 0
  print(f"{'route':22} exp_min act% episodes lift_p50 lift_p95 lift_max max_rise bad_brake bad_lead")
  for r in args.routes:
    rid = os.path.basename(os.path.normpath(r))
    fr = replay_route(r)
    if not fr:
      continue
    allf += fr
    lift = np.array([f[2] for f in fr])
    act = lift > ACT
    episodes = int(np.sum(act[1:] & ~act[:-1]) + act[0])
    t_all = np.array([f[0] for f in fr])
    consecutive = np.diff(t_all) < 1.5 * DT_MDL
    dl = np.diff(lift)[consecutive]
    step = float(np.max(dl)) if dl.size else 0.0  # largest one-frame rise (drops toward braking are intended)
    bad_brake = sum(1 for f in fr if f[2] > 1e-6 and f[3] < EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE)
    bad_lead = sum(1 for f in fr if f[2] > ACT and (f[5] < -0.5 or f[6] < -1.0))
    a = lift[act] if act.any() else np.array([0.0])
    print(f"{rid:22} {len(fr) * DT_MDL / 60:7.1f} {100 * act.mean():4.1f} {episodes:8d} {np.median(a):8.2f} "
          f"{np.percentile(a, 95):8.2f} {a.max():8.2f} {step:8.3f} {bad_brake:9d} {bad_lead:8d}")
    t = np.array([f[0] for f in fr])
    for pt in presses.get(rid, []):
      total_p += 1
      sel = (t >= pt - 1.5) & (t < pt)
      covered += bool(sel.any() and lift[sel].max() > ACT)
  lift = np.array([f[2] for f in allf])
  print(f"\nall: {len(allf) * DT_MDL / 60:.1f} exp-mode engaged min, acting {100 * np.mean(lift > ACT):.1f}% of it")
  if args.presses:
    print(f"e2e-limited presses with a lead pulling away, assist acting in the 1.5 s before: {covered}/{total_p}")


if __name__ == "__main__":
  main()
