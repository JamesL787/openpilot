#!/usr/bin/env python3
"""Real drives in the shape Metadrive Sim (John)'s scorer reads: one lat_pid_sim.npz per segment, at the controls rate.

  sim_export.py ROUTE_DIR_OR_RLOG [...] --out DIR [--all]

The 20 Hz Plots rows are too slow for the sim's 5-8 Hz torque roughness and per-frame torque steps, so this is
rebuilt from the rlog: one row per controlsState that carries pidState (~100 Hz; LatControlHondaEps publishes
pidState too). Writes DIR/<seg>/lat_pid_sim.npz for every segment with openpilot steering (every segment with --all)
and DIR/export.json. DIR is route data: never commit it.

Keys (float64 arrays, one per row):
  t           seconds from the segment's first carState (starts at 0 in every file), strictly increasing
  angle       carState.steeringAngleDeg (+ = left)
  des_angle   pidState.steeringAngleDesiredDeg
  cc_torque   carControl.actuators.torque (requested)
  co_torque   carOutput.actuatorsOutput.torque (delivered)
  v           carState.vEgo
  eps_torque  carState.steeringTorque (the driver's torque, despite the name)
  active      carControl.latActive
  pressed     carState.steeringPressed (raw)
  pid_active  pidState.active; out = pidState.output; log_p / log_i / log_f = pidState.p / i / f
  rate        carState.steeringRateDeg; lblink / rblink the blinkers; lane_change modelV2 laneChangeState (0 off)
  sr, stiff, offset, roll   liveParameters steerRatio / stiffnessFactor / angleOffsetDeg / roll (rad)
  des_curv    controlsState.desiredCurvature (1/m, + = right on this branch, as in drive_plots)
  yaw_curv    livePose.angularVelocityDevice.z / vEgo (1/m; NaN under 1 m/s): the curvature achieved. + = right like
              des_curv (the device z axis points down; route 297: corr with des_curv +0.80, with angle -0.98)
Before the first message of a service a key is NaN. No lane offset: real drives have no ground truth, and a model
estimate must not be scored as one. No GPS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(1, ROOT)

from openpilot.tools.drive_plots.rlog_report import segments

KEYS = ("t", "angle", "des_angle", "cc_torque", "co_torque", "v", "eps_torque", "active", "pressed", "pid_active", "out",
        "log_p", "log_i", "log_f", "rate", "lblink", "rblink", "lane_change", "sr", "stiff", "offset", "roll", "des_curv",
        "yaw_curv")
YAW_MIN_V = 1.0
NAN = float("nan")


def read_segment(path):
  """Rows (dict of arrays over KEYS) and the segment's liveDelay.lateralDelay values."""
  from openpilot.tools.lib.logreader import LogReader
  rows, delays = [], []
  cs = lp = cc = co = pose = None
  lane_change = NAN
  t0 = None
  try:
    for m in LogReader(path):
      w = m.which()
      if w == "carState":
        if t0 is None:   # not the first message: every segment repeats initData stamped at the route's start
          t0 = m.logMonoTime
        cs = m.carState
      elif w == "liveParameters":
        lp = m.liveParameters
      elif w == "carControl":
        cc = m.carControl
      elif w == "carOutput":
        co = m.carOutput
      elif w == "livePose":
        pose = m.livePose
      elif w == "liveDelay":
        delays.append(m.liveDelay.lateralDelay)
      elif w == "modelV2":
        lane_change = float(m.modelV2.meta.laneChangeState.raw)
      elif w == "controlsState" and cs is not None:
        c = m.controlsState
        if c.lateralControlState.which() != "pidState":
          continue
        p = c.lateralControlState.pidState
        v = cs.vEgo
        yaw = pose.angularVelocityDevice.z / v if pose is not None and v >= YAW_MIN_V else NAN
        rows.append((
          (m.logMonoTime - t0) * 1e-9, cs.steeringAngleDeg, p.steeringAngleDesiredDeg,
          cc.actuators.torque if cc is not None else NAN, co.actuatorsOutput.torque if co is not None else NAN,
          v, cs.steeringTorque, float(cc.latActive) if cc is not None else NAN, float(cs.steeringPressed),
          float(p.active), p.output, p.p, p.i, p.f, cs.steeringRateDeg, float(cs.leftBlinker), float(cs.rightBlinker),
          lane_change,
          *((lp.steerRatio, lp.stiffnessFactor, lp.angleOffsetDeg, lp.roll) if lp is not None else (NAN,) * 4),
          c.desiredCurvature, yaw,
        ))
  except Exception as e:  # a truncated final segment is common; keep what was read
    print(f"warning: {path}: {e}", file=sys.stderr)
  arr = np.array(rows, dtype=np.float64).reshape(-1, len(KEYS))
  if len(arr):
    keep = np.concatenate([[True], np.diff(arr[:, 0]) > 0])   # t strictly increasing
    arr = arr[keep]
  return {k: arr[:, i] for i, k in enumerate(KEYS)}, delays


def _seg_name(path, i):
  d = os.path.basename(os.path.dirname(path))
  return d if d.isdigit() else str(i)


def export(seg_paths, out_dir, route=None, all_segments=False):
  os.makedirs(out_dir, exist_ok=True)
  info = {"schema": "drivePlotsSimExport/1", "route": route, "keys": list(KEYS), "segments": []}
  delays = []
  for i, path in enumerate(seg_paths):
    d, dl = read_segment(path)
    delays += dl
    n = len(d["t"])
    steer_s = float(np.sum(np.clip(np.diff(d["t"]), 0, 0.1)[d["active"][1:] > 0.5])) if n > 1 else 0.0
    seg = {"seg": _seg_name(path, i), "rows": n, "steering_s": round(steer_s, 1),
           "rate_hz": round((n - 1) / (d["t"][-1] - d["t"][0]), 1) if n > 1 and d["t"][-1] > d["t"][0] else None}
    if n > 1 and (all_segments or steer_s > 0):
      rel = os.path.join(seg["seg"], "lat_pid_sim.npz")
      os.makedirs(os.path.join(out_dir, seg["seg"]), exist_ok=True)
      np.savez_compressed(os.path.join(out_dir, rel), **d)
      seg["file"] = rel
    info["segments"].append(seg)
  info["lateral_delay_median_s"] = round(float(np.median(delays)), 3) if delays else None
  with open(os.path.join(out_dir, "export.json"), "w") as f:
    json.dump(info, f, indent=1)
  return info


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("routes", nargs="+", help="route cache dir(s) or rlog file(s)")
  ap.add_argument("--out", required=True, help="output dir (route data: do not commit)")
  ap.add_argument("--all", action="store_true", help="also write segments where openpilot never steered")
  a = ap.parse_args(argv)
  seg_paths = [p for spec in a.routes for p in segments(spec)]
  if not seg_paths:
    ap.error("no rlogs found")
  route = os.path.basename(os.path.normpath(a.routes[0])) if len(a.routes) == 1 and os.path.isdir(a.routes[0]) else None
  info = export(seg_paths, a.out, route, a.all)
  written = [s for s in info["segments"] if "file" in s]
  print(f"{len(written)} of {len(info['segments'])} segment(s) written to {a.out}; "
        f"lateralDelay median {info['lateral_delay_median_s']}")


if __name__ == "__main__":
  main()
