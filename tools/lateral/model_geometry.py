#!/usr/bin/env python3
"""Exact road-geometry numbers from modelV2, for whoever is evaluating lateral performance and wants
ground-truth values instead of eyeballing a rendered frame.

This does not judge anything. Log-decode only; no replay, no simulation.

SIGN CONVENTION (checked empirically 2026-09-28 by projecting modelV2.laneLines[1] ("left") and [2]
("right") through the real camera transform on route 294 seg4 t=276.9: the "left" line landed at
negative y and the smaller screen-x pixel, the "right" line at positive y and the larger screen-x
pixel): modelV2 x/y/z (the calib frame) is +y = RIGHT, -y = LEFT. This matches desiredCurvature
(also +right) and `model.y == -yRel` in model_renderer.py's lead_in_adjacent_lane docstring (yRel is
+left). A first pass at this tool had the labels backwards; James (VFN Shadow controller) caught it.
steeringAngleDeg keeps the OTHER convention already established in this repo: + = left.

  sample    per-timestamp table (default mode)
  episodes  press/release/+1/+2/+3s snapshots for driver-takeover episodes, joined against
            tools/drive_plots/rlog_report.py's report.json so episode boundaries match Live Plots
            Enhancement's lane_press_m / lane_release_m exactly (same press/release definition,
            same mono_s join key) instead of a second, possibly-different re-detection.

Usage:
  python tools/lateral/model_geometry.py sample SEG_DIR [T0 T1 STEP] [--csv] [--summary]
  python tools/lateral/model_geometry.py episodes SEG_DIR --episodes-file report.json [--csv]

  SEG_DIR         a segment directory containing rlog.zst (not qlog -- modelV2 is not in qlog)
  T0 T1           seconds into this segment's own log (default: the whole segment)
  STEP            sample interval in seconds (default 1.0)
  --csv           machine-readable CSV instead of the human-readable table (one row per sample)
  --summary       (sample mode) median/p90 of inside_offset for car and path, binned by |ay| =
                   v^2*|path_curvature| (0.15-0.5 / 0.5-1 / 1-1.5 / 1.5-2.5 m/s^2), split by
                   both-lane-probs > 0.6 vs outside-prob < 0.35, instead of per-frame rows
  --episodes-file path to a report.json written by tools/drive_plots/rlog_report.py on the same
                   route/segments (analysis.driver_takeovers.episodes; mono_s is the join key)
"""
from __future__ import annotations

import argparse
import csv as csv_mod
import json
import os
import sys

import numpy as np

from openpilot.tools.lib.logreader import LogReader

FORWARD_X = (5.0, 15.0, 30.0, 50.0)
LANE_NAMES = ("outer_left", "left", "right", "outer_right")
AY_BINS = ((0.15, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.5))


def _interp_y(line: np.ndarray, x: float, *, strict: bool = True) -> float | None:
  if line.shape[0] == 0:
    return None
  if strict and (x < line[0, 0] or x > line[-1, 0]):
    return None
  return float(np.interp(x, line[:, 0], line[:, 1]))


def _path_curvature(path: np.ndarray) -> float | None:
  """Fit y = a*x^2 + b*x + c over the near-field (0-30 m) path points; curvature at x=0 is 2*a.
  +y = right (see module docstring), so positive curvature = curving right, matching desiredCurvature."""
  mask = (path[:, 0] >= 0) & (path[:, 0] <= 30)
  if mask.sum() < 5:
    return None
  a, _b, _c = np.polyfit(path[mask, 0], path[mask, 1], 2)
  return float(2 * a)


def _sign(v: float) -> float:
  return 1.0 if v >= 0 else -1.0


def _replay(seg_dir: str):
  """Yields (t, state) after every message, state holding the latest of everything we track."""
  msgs = list(LogReader(os.path.join(seg_dir, "rlog.zst")))
  t_start = msgs[0].logMonoTime
  state: dict = {}
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
      state["steeringTorque"] = cs.steeringTorque
      state["leftBlinker"] = cs.leftBlinker
      state["rightBlinker"] = cs.rightBlinker
    elif w == "selfdriveState":
      state["enabled"] = m.selfdriveState.enabled
    elif w == "controlsState":
      state["desiredCurvature"] = m.controlsState.desiredCurvature
    elif w == "carControl":
      state["latActive"] = m.carControl.latActive
    elif w == "lateralPlan":
      state["laneChangeState"] = str(m.lateralPlan.laneChangeState)
    yield t, t_start, state


def geometry_at(state: dict) -> dict | None:
  """One snapshot's worth of geometry, or None if modelV2 hasn't arrived yet."""
  if "model" not in state:
    return None
  lines, probs, edges, path = state["model"]
  left_line, right_line = lines[1], lines[2]
  left_edge, right_edge = (edges[0], edges[1]) if len(edges) >= 2 else (np.zeros((0, 3)), np.zeros((0, 3)))

  row: dict = {
    "vEgo": state.get("vEgo"), "steeringAngleDeg": state.get("steeringAngleDeg"),
    "steeringPressed": state.get("steeringPressed"), "steeringTorque": state.get("steeringTorque"),
    "leftBlinker": state.get("leftBlinker"), "rightBlinker": state.get("rightBlinker"),
    "enabled": state.get("enabled"), "desiredCurvature": state.get("desiredCurvature"),
    "latActive": state.get("latActive"), "laneChangeState": state.get("laneChangeState"),
  }
  for name, line, prob in zip(LANE_NAMES, lines, probs):
    row[f"{name}_prob"] = round(prob, 3)
    for x in FORWARD_X:
      y = _interp_y(line, x)
      row[f"{name}_y@{x:g}"] = None if y is None else round(y, 3)
  for name, edge in zip(("edge_left", "edge_right"), edges):
    for x in FORWARD_X:
      y = _interp_y(edge, x)
      row[f"{name}_y@{x:g}"] = None if y is None else round(y, 3)

  for x in FORWARD_X:
    py = _interp_y(path, x)
    ly = _interp_y(left_line, x)
    ry = _interp_y(right_line, x)
    row[f"path_y@{x:g}"] = None if py is None else round(py, 3)
    row[f"lane_width@{x:g}"] = None if (ly is None or ry is None) else round(ry - ly, 3)  # +y=right: right - left
    row[f"path_offset_from_center@{x:g}"] = None if (py is None or ly is None or ry is None) else round(py - (ly + ry) / 2, 3)

  angle = row["steeringAngleDeg"]
  off30 = row.get("path_offset_from_center@30")
  if angle is not None and off30 is not None:
    row["inside_offset"] = round(-_sign(angle) * off30, 3)  # +left angle; + = toward the curve's inside
  else:
    row["inside_offset"] = None

  # lookahead distance per James (VFN Shadow controller): clip(vEgo, 8, 35) m, ~1s of travel with an
  # 8m floor and 35m cap. Shared definition so his/John's/this tool's lookahead numbers line up.
  x_la = None if row["vEgo"] is None else float(np.clip(row["vEgo"], 8.0, 35.0))
  py_la = None if x_la is None else _interp_y(path, x_la, strict=False)
  ly_la = None if x_la is None else _interp_y(left_line, x_la, strict=False)
  ry_la = None if x_la is None else _interp_y(right_line, x_la, strict=False)
  row["lookahead_x"] = None if x_la is None else round(x_la, 2)
  if angle is not None and py_la is not None and ly_la is not None and ry_la is not None:
    row["path_inside_at_lookahead"] = round(-_sign(angle) * (py_la - (ly_la + ry_la) / 2), 3)
  else:
    row["path_inside_at_lookahead"] = None

  ly0 = _interp_y(left_line, 0.0, strict=False)
  ry0 = _interp_y(right_line, 0.0, strict=False)
  row["ego_offset_at_x0"] = None if (ly0 is None or ry0 is None) else round(-(ly0 + ry0) / 2, 3)  # ego is y=0 by definition
  row["lane_width_at_x0"] = None if (ly0 is None or ry0 is None) else round(ry0 - ly0, 3)
  ely0 = _interp_y(left_edge, 0.0, strict=False)
  ery0 = _interp_y(right_edge, 0.0, strict=False)
  row["edge_left_y@0"] = None if ely0 is None else round(ely0, 3)
  row["edge_right_y@0"] = None if ery0 is None else round(ery0, 3)

  curv = _path_curvature(path)
  row["path_curvature"] = None if curv is None else round(curv, 5)
  dc = row["desiredCurvature"]
  if dc is not None and row["vEgo"] is not None:
    row["ay"] = round(row["vEgo"] ** 2 * abs(dc), 3)  # binned on desiredCurvature per James, not the fitted path
  else:
    row["ay"] = None

  # "outside" line = the outer laneLine on the side away from the turn (+left angle -> outside is
  # the right side); used for the outside-confidence split, matches James's fov.py.
  if angle is not None:
    row["outside_prob"] = row["outer_right_prob"] if angle > 0 else row["outer_left_prob"]
  else:
    row["outside_prob"] = None

  if row[f"left_y@30"] is not None and row[f"right_y@30"] is not None and row["left_prob"] > 0.5 and row["right_prob"] > 0.5:
    if row["lane_width@30"] < 0:
      print(f"WARNING sign-check failed: lane_width@30={row['lane_width@30']} < 0 with both probs > 0.5 "
            f"(left_prob={row['left_prob']} right_prob={row['right_prob']})", file=sys.stderr)

  # steeringAngleDeg is +left; desiredCurvature is +right (see module docstring) -- they should be
  # opposite-signed across any real turn (corr ~ -0.99 per James on routes 290-294). Gated on
  # |desiredCurvature| > 1e-3 and compared against the CURRENT curvature (not the 0-30m path fit,
  # which lags the wheel through S-bend transitions and is noisy near zero).
  if angle is not None and dc is not None and abs(angle) > 5 and abs(dc) > 1e-3 and row["vEgo"] is not None and row["vEgo"] > 1.0:
    if _sign(dc) == _sign(angle):
      print(f"WARNING sign-check failed: desiredCurvature={dc} and steeringAngleDeg={angle} have the "
            f"SAME sign (expected opposite: +right curvature during a +left steer or vice versa)", file=sys.stderr)

  return row


def sample(seg_dir: str, t0: float | None, t1: float | None, step: float):
  gen = _replay(seg_dir)
  t_end = None
  rows = []
  next_sample = t0 if t0 is not None else 0.0
  for t, _t_start, state in gen:
    if t1 is not None and t > t1:
      break
    if t0 is not None and t < t0:
      continue
    if t >= next_sample:
      row = geometry_at(state)
      if row is not None:
        row = {"t": round(t, 2), **row}
        rows.append(row)
      next_sample += step
  return rows


def _bin_ay(ay: float) -> str | None:
  for lo, hi in AY_BINS:
    if lo <= ay < hi:
      return f"{lo:g}-{hi:g}"
  return None


# Frame filters matching James's fov.py, applied in --summary so takeovers/intersections/lane
# changes don't leak into the lateral-performance numbers. Each entry: (name, predicate-is-OK).
_FILTERS = (
  ("lat_active", lambda r: r.get("latActive") is True),
  ("not_pressed", lambda r: r.get("steeringPressed") is False),
  ("no_blinker", lambda r: not r.get("leftBlinker") and not r.get("rightBlinker")),
  ("lane_change_off", lambda r: r.get("laneChangeState") in ("off", None)),
  ("speed_11_22.4", lambda r: r.get("vEgo") is not None and 11.0 <= r["vEgo"] < 22.4),
  ("angle_gt_1deg", lambda r: r.get("steeringAngleDeg") is not None and abs(r["steeringAngleDeg"]) > 1.0),
  ("lane_width_2.6_4.8", lambda r: r.get("lane_width_at_x0") is not None and 2.6 <= r["lane_width_at_x0"] <= 4.8),
)


def _passes_filters(row: dict) -> bool:
  return all(pred(row) for _name, pred in _FILTERS)


def summarize(rows: list[dict]) -> list[dict]:
  drop_counts = {name: sum(1 for r in rows if not pred(r)) for name, pred in _FILTERS}
  print(f"summary: {len(rows)} frames sampled; dropped by filter (not mutually exclusive): {drop_counts}", file=sys.stderr)
  filtered = [r for r in rows if _passes_filters(r)]
  print(f"summary: {len(filtered)} frames pass all filters", file=sys.stderr)

  out = []
  for lo, hi in AY_BINS:
    label = f"{lo:g}-{hi:g}"
    for conf_label, pred in (
      ("both_seen(>0.6)", lambda r: r["left_prob"] > 0.6 and r["right_prob"] > 0.6),
      ("outside_weak(<0.35)", lambda r: r["outside_prob"] is not None and r["outside_prob"] < 0.35),
      ("all_filtered", lambda r: True),
    ):
      sel = [r for r in filtered if r["ay"] is not None and lo <= r["ay"] < hi and r["inside_offset"] is not None and pred(r)]
      if not sel:
        out.append({"ay_bin": label, "confidence": conf_label, "n": 0})
        continue
      path_vals = np.array([r["inside_offset"] for r in sel])
      car_vals = np.array([-_sign(r["steeringAngleDeg"]) * r["ego_offset_at_x0"] for r in sel
                            if r["steeringAngleDeg"] is not None and r["ego_offset_at_x0"] is not None])
      row = {"ay_bin": label, "confidence": conf_label, "n": len(sel),
             "path_inside_offset_median": round(float(np.median(path_vals)), 3),
             "path_inside_offset_p90": round(float(np.percentile(path_vals, 90)), 3)}
      if car_vals.size:
        row["car_inside_offset_median"] = round(float(np.median(car_vals)), 3)
        row["car_inside_offset_p90"] = round(float(np.percentile(car_vals, 90)), 3)
      out.append(row)
  return out


def _episode_list(episodes_file: str) -> list[dict]:
  with open(episodes_file) as f:
    report = json.load(f)
  return report["analysis"]["driver_takeovers"]["episodes"]


def episodes_report(seg_dir: str, episodes_file: str) -> list[dict]:
  eps = _episode_list(episodes_file)
  msgs = list(LogReader(os.path.join(seg_dir, "rlog.zst")))
  t_start = msgs[0].logMonoTime
  seg_end = (msgs[-1].logMonoTime - t_start) / 1e9

  # pre-index states over the whole segment once, so per-episode snapshots don't re-replay the log
  timeline = []
  state: dict = {}
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
      state["steeringTorque"] = cs.steeringTorque
      state["leftBlinker"] = cs.leftBlinker
      state["rightBlinker"] = cs.rightBlinker
    elif w == "selfdriveState":
      state["enabled"] = m.selfdriveState.enabled
    elif w == "controlsState":
      state["desiredCurvature"] = m.controlsState.desiredCurvature
    if w in ("modelV2", "carState", "selfdriveState", "controlsState"):
      timeline.append((t, dict(state)))

  def state_near(target_t: float) -> dict | None:
    best = None
    for t, s in timeline:
      if t > target_t:
        break
      best = s
    return best

  out = []
  for ep in eps:
    press_raw_mono = ep["mono_s"] * 1e9
    press_t = (press_raw_mono - t_start) / 1e9
    hold_s = ep["hold_s"]
    release_t = press_t + hold_s
    if press_t < -1 or press_t > seg_end + 1:
      continue  # this episode belongs to a different segment

    press_state = state_near(press_t)
    release_state = state_near(release_t)
    if press_state is None or release_state is None:
      continue

    # push is +1=left/-1=right, in that priority: Live Plots' own "push" field when present
    # (it's the source of truth per Driver override's cross-check on 294), else torque sign at
    # press, else the angle delta press->release.
    push_field = ep.get("push")
    if push_field in ("left", "right"):
      push_sign = 1.0 if push_field == "left" else -1.0
    else:
      push_sign = _sign(press_state.get("steeringTorque") or 0.0)
      if press_state.get("steeringTorque") in (None, 0.0):
        da = (release_state.get("steeringAngleDeg") or 0) - (press_state.get("steeringAngleDeg") or 0)
        push_sign = _sign(da) if da else 1.0

    snap = {"tag": ep.get("tag"), "hold_s": hold_s, "push_sign": push_sign,
            "route_s_press": ep.get("route_s"), "route_s_release": ep.get("route_s") + hold_s}
    times = {"press": press_t, "release": release_t, "release+1s": release_t + 1.0,
             "release+2s": release_t + 2.0, "release+3s": release_t + 3.0}
    path_off_30 = {}
    for label, t in times.items():
      s = state_near(t)
      if s is None:
        snap[label] = None
        continue
      g = geometry_at(s)
      if g is None:
        snap[label] = None
        continue
      # Below prob 0.3 the lane geometry itself is untrustworthy (e.g. route 294: 45/47 episodes
      # low_confidence, offsets blowing up to +-15-35m) -- print None for offset/path_move columns
      # rather than a number that looks like a measurement. low_confidence (< 0.5) stays as a
      # softer flag alongside the raw probs.
      lanes_trustworthy = g["left_prob"] >= 0.3 and g["right_prob"] >= 0.3
      path_off_30[label] = g.get("path_offset_from_center@30") if lanes_trustworthy else None
      snap[label] = {
        "ego_offset_toward_push": None if (g["ego_offset_at_x0"] is None or not lanes_trustworthy) else round(push_sign * g["ego_offset_at_x0"], 3),
        "path_offset_toward_push@15": None if (g["path_offset_from_center@15"] is None or not lanes_trustworthy) else round(push_sign * g["path_offset_from_center@15"], 3),
        "path_offset_toward_push@30": None if (g["path_offset_from_center@30"] is None or not lanes_trustworthy) else round(push_sign * g["path_offset_from_center@30"], 3),
        "road_edge_margin_push_side@0": round(push_sign * (g["edge_right_y@0"] if push_sign > 0 else g["edge_left_y@0"]), 3)
          if (push_sign > 0 and g["edge_right_y@0"] is not None) or (push_sign < 0 and g["edge_left_y@0"] is not None) else None,
        "left_prob": g["left_prob"], "right_prob": g["right_prob"],
        "low_confidence": bool(g["left_prob"] < 0.5 or g["right_prob"] < 0.5),
        "leftBlinker": g["leftBlinker"], "rightBlinker": g["rightBlinker"],
        "lane_change_suspected": bool(g["leftBlinker"] or g["rightBlinker"]),
      }
    if path_off_30.get("release") is not None and path_off_30.get("release+1s") is not None:
      d = path_off_30["release+1s"] - path_off_30["release"]
      snap["path_move_release_to_1s_m"] = round(d, 3)
      snap["path_move_release_to_1s_mps"] = round(d, 3)  # window is exactly 1s
    else:
      snap["path_move_release_to_1s_m"] = None
      snap["path_move_release_to_1s_mps"] = None
    out.append(snap)
  return out


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("mode", choices=["sample", "episodes"])
  ap.add_argument("seg_dir")
  ap.add_argument("t0", nargs="?", type=float, default=None)
  ap.add_argument("t1", nargs="?", type=float, default=None)
  ap.add_argument("step", nargs="?", type=float, default=1.0)
  ap.add_argument("--csv", action="store_true")
  ap.add_argument("--summary", action="store_true")
  ap.add_argument("--episodes-file")
  args = ap.parse_args()

  if args.mode == "episodes":
    if not args.episodes_file:
      print("episodes mode needs --episodes-file report.json (from tools/drive_plots/rlog_report.py)", file=sys.stderr)
      sys.exit(1)
    out = episodes_report(args.seg_dir, args.episodes_file)
    if args.csv:
      flat = []
      for ep in out:
        base = {k: v for k, v in ep.items() if not isinstance(v, dict)}
        for label in ("press", "release", "release+1s", "release+2s", "release+3s"):
          sub = ep.get(label) or {}
          for k, v in sub.items():
            base[f"{label}_{k}"] = v
        flat.append(base)
      w = csv_mod.DictWriter(sys.stdout, fieldnames=list(flat[0].keys()) if flat else [])
      if flat:
        w.writeheader()
        w.writerows(flat)
    else:
      print(json.dumps(out, indent=2))
    return

  rows = sample(args.seg_dir, args.t0, args.t1, args.step)
  if not rows:
    print("no modelV2 samples in range", file=sys.stderr)
    sys.exit(1)

  if args.summary:
    summ = summarize(rows)
    if args.csv:
      w = csv_mod.DictWriter(sys.stdout, fieldnames=list(summ[0].keys()))
      w.writeheader()
      w.writerows(summ)
    else:
      for r in summ:
        print(r)
    return

  if args.csv:
    w = csv_mod.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return

  for row in rows:
    hdr = (f"t={row['t']:6.2f}  vEgo={row['vEgo']:5.1f}  steerAngle={row['steeringAngleDeg']:7.2f}  "
           f"pressed={str(row['steeringPressed']):5s}  enabled={str(row['enabled']):5s}  "
           f"desiredCurvature={row['desiredCurvature']}")
    print(hdr)
    for x in FORWARD_X:
      print(f"    x={x:4.0f}m  path_y={row[f'path_y@{x:g}']!s:>8}  offset_from_center={row[f'path_offset_from_center@{x:g}']!s:>8}  "
            f"lane_width={row[f'lane_width@{x:g}']!s:>8}  left_y={row[f'left_y@{x:g}']!s:>8}(p={row['left_prob']})  "
            f"right_y={row[f'right_y@{x:g}']!s:>8}(p={row['right_prob']})  "
            f"edgeL_y={row[f'edge_left_y@{x:g}']!s:>8}  edgeR_y={row[f'edge_right_y@{x:g}']!s:>8}")
    print(f"    path_curvature (1/m, +right)={row['path_curvature']}  ay={row['ay']}  "
          f"inside_offset={row['inside_offset']}  ego_offset_at_x0={row['ego_offset_at_x0']}")
    print(f"    lookahead_x={row['lookahead_x']}  path_inside_at_lookahead={row['path_inside_at_lookahead']}")


if __name__ == "__main__":
  main()
