#!/usr/bin/env python3
"""Exact road-geometry numbers from modelV2, for whoever is evaluating lateral performance and wants
ground-truth values instead of eyeballing a rendered frame.

This does not judge anything. It samples an rlog and prints, per timestamp: lane-line and road-edge
lateral (y, +left/-right, car space) position at fixed forward distances, lane width, the planned
path's own lateral position and its offset from the lane center, a curvature estimate fit to the path,
and the car/engagement state at that instant (vEgo, steeringAngleDeg, steeringPressed, enabled).

Distances are fixed at 5/15/30/50 m forward (x, car space) -- change FORWARD_X below if you need a
different set. laneLineProbs is included unmodified so the caller can decide its own confidence cutoff;
this tool does not drop or flag low-confidence samples.

Usage:
  python tools/lateral/model_geometry.py SEG_DIR [T0 T1 STEP] [--csv]

  SEG_DIR   a segment directory containing rlog.zst (not qlog -- modelV2 is not in qlog)
  T0 T1     seconds into this segment's own log (default: the whole segment)
  STEP      sample interval in seconds (default 1.0)
  --csv     machine-readable CSV instead of the human-readable table (one row per sample)

Log-decode only; no replay, no simulation.
"""
from __future__ import annotations

import argparse
import csv as csv_mod
import os
import sys

import numpy as np

from openpilot.tools.lib.logreader import LogReader

FORWARD_X = (5.0, 15.0, 30.0, 50.0)
LANE_NAMES = ("outer_left", "left", "right", "outer_right")


def _interp_y(line: np.ndarray, x: float) -> float | None:
  if line.shape[0] == 0 or x < line[0, 0] or x > line[-1, 0]:
    return None
  return float(np.interp(x, line[:, 0], line[:, 1]))


def _path_curvature(path: np.ndarray) -> float | None:
  """Fit y = a*x^2 + b*x + c over the near-field (0-30 m) path points; curvature at x=0 is 2*a.
  Matches the sign convention elsewhere in this tree (+y = left => positive curvature = curving left)."""
  mask = (path[:, 0] >= 0) & (path[:, 0] <= 30)
  if mask.sum() < 5:
    return None
  a, _b, _c = np.polyfit(path[mask, 0], path[mask, 1], 2)
  return float(2 * a)


def sample(seg_dir: str, t0: float | None, t1: float | None, step: float):
  msgs = list(LogReader(os.path.join(seg_dir, "rlog.zst")))
  t_start = msgs[0].logMonoTime
  t1 = t1 if t1 is not None else (msgs[-1].logMonoTime - t_start) / 1e9
  t0 = t0 if t0 is not None else 0.0

  state: dict = {}
  next_sample = t0
  rows = []
  for m in msgs:
    t = (m.logMonoTime - t_start) / 1e9
    w = m.which()
    if w == "modelV2":
      mv2 = m.modelV2
      lines = [np.array([ln.x, ln.y, ln.z], dtype=np.float32).T for ln in mv2.laneLines]
      probs = list(mv2.laneLineProbs)
      edges = [np.array([e.x, e.y, e.z], dtype=np.float32).T for e in mv2.roadEdges]
      path = np.array([mv2.position.x, mv2.position.y, mv2.position.z], dtype=np.float32).T
      state["model"] = (lines, probs, edges, path)
    elif w == "carState":
      cs = m.carState
      state["vEgo"] = cs.vEgo
      state["steeringAngleDeg"] = cs.steeringAngleDeg
      state["steeringPressed"] = cs.steeringPressed
    elif w == "selfdriveState":
      state["enabled"] = m.selfdriveState.enabled

    if t > t1:
      break
    if t >= next_sample and t0 <= t <= t1 and "model" in state:
      lines, probs, edges, path = state["model"]
      row = {"t": round(t, 2), "vEgo": round(state.get("vEgo", float("nan")), 2),
             "steeringAngleDeg": round(state.get("steeringAngleDeg", float("nan")), 2),
             "steeringPressed": state.get("steeringPressed"), "enabled": state.get("enabled")}
      for name, line, prob in zip(LANE_NAMES, lines, probs):
        row[f"{name}_prob"] = round(prob, 3)
        for x in FORWARD_X:
          y = _interp_y(line, x)
          row[f"{name}_y@{x:g}"] = None if y is None else round(y, 3)
      for name, edge in zip(("edge_left", "edge_right"), edges):
        for x in FORWARD_X:
          y = _interp_y(edge, x)
          row[f"{name}_y@{x:g}"] = None if y is None else round(y, 3)
      left_line, right_line = lines[1], lines[2]
      for x in FORWARD_X:
        py = _interp_y(path, x)
        ly = _interp_y(left_line, x)
        ry = _interp_y(right_line, x)
        row[f"path_y@{x:g}"] = None if py is None else round(py, 3)
        row[f"lane_width@{x:g}"] = None if (ly is None or ry is None) else round(ly - ry, 3)
        if py is not None and ly is not None and ry is not None:
          row[f"path_offset_from_center@{x:g}"] = round(py - (ly + ry) / 2, 3)
        else:
          row[f"path_offset_from_center@{x:g}"] = None
      curv = _path_curvature(path)
      row["path_curvature"] = None if curv is None else round(curv, 5)
      rows.append(row)
      next_sample += step

  return rows


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("seg_dir")
  ap.add_argument("t0", nargs="?", type=float, default=None)
  ap.add_argument("t1", nargs="?", type=float, default=None)
  ap.add_argument("step", nargs="?", type=float, default=1.0)
  ap.add_argument("--csv", action="store_true")
  args = ap.parse_args()

  rows = sample(args.seg_dir, args.t0, args.t1, args.step)
  if not rows:
    print("no modelV2 samples in range", file=sys.stderr)
    sys.exit(1)

  if args.csv:
    w = csv_mod.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return

  for row in rows:
    hdr = (f"t={row['t']:6.2f}  vEgo={row['vEgo']:5.1f}  steerAngle={row['steeringAngleDeg']:7.2f}  "
           f"pressed={str(row['steeringPressed']):5s}  enabled={str(row['enabled']):5s}")
    print(hdr)
    for x in FORWARD_X:
      print(f"    x={x:4.0f}m  path_y={row[f'path_y@{x:g}']!s:>8}  offset_from_center={row[f'path_offset_from_center@{x:g}']!s:>8}  "
            f"lane_width={row[f'lane_width@{x:g}']!s:>8}  left_y={row[f'left_y@{x:g}']!s:>8}(p={row['left_prob']})  "
            f"right_y={row[f'right_y@{x:g}']!s:>8}(p={row['right_prob']})  "
            f"edgeL_y={row[f'edge_left_y@{x:g}']!s:>8}  edgeR_y={row[f'edge_right_y@{x:g}']!s:>8}")
    print(f"    path_curvature (1/m, +left)={row['path_curvature']}")


if __name__ == "__main__":
  main()
