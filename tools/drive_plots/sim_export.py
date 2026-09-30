#!/usr/bin/env python3
"""Real drives in the shape Metadrive Sim (John)'s scorer reads: one lat_pid_sim.npz per segment, at the controls rate.

  sim_export.py ROUTE_DIR_OR_RLOG [...] --out DIR [--all]

The 20 Hz Plots rows are too slow for the sim's 5-8 Hz torque roughness and per-frame torque steps, so this is
rebuilt from the rlog: one row per controlsState that carries pidState (~100 Hz; LatControlClarityEps publishes
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

export.json also carries, for John's P' rows:
  params      every Nrdr* toggle as initData stored it (a toggle never written is absent; the CLI warns for each
              of REQUIRED_PARAMS that is missing)
  windows     engaged runs with no press (active, not pressed), each one speed band (BANDS, m/s) and one shape
              (straight: |des_angle| < 5 deg; curve: 10-30 deg; other), at least WINDOW_MIN_S long:
              {seg, t0, t1, s, band, shape}; t as in the npz
  window_totals_s   {band: {shape: seconds}} over every engaged no-press frame, whatever its run length
  presses     each raw steeringPressed run: {seg, t_press, t_release, held_s, v, band, active_before, blinker, episode};
              blinker: a blinker or a lane change from BLINKER_BEFORE_S before the press to its release.
              episode numbers the drive's press episodes: a press starting within EPISODE_JOIN_S of the previous
              release in the same segment joins its episode.
  press_summary     Kevin's drive-to-drive press counts, per band of the press (episode: of its first press), only
              presses made while openpilot was steering: {band: {presses, presses_long, episodes, episodes_blinker}},
              where presses_long counts presses held >= PRESS_LONG_S and episodes_blinker the episodes with a
              blinker press (a lane change or turn the driver signalled, not a correction). An episode is counted
              once, in the band at its first press's onset, and only if openpilot was steering then. Its blinker
              window is from BLINKER_BEFORE_S before its first press to its last release (the presses' own windows
              join into that, since presses in one episode are at most EPISODE_JOIN_S apart). presses and
              presses_long count each press in its own band. Compare drives on episodes and presses_long,
              not raw presses (most raw onsets on 299 were <= 0.1 s blips near the threshold).
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
BANDS = ((5.0, 8.0, "5-8"), (8.0, 12.0, "8-12"), (12.0, 16.0, "12-16"), (16.0, 25.0, "16-25"), (25.0, np.inf, "25+"))
STRAIGHT_DEG = 5.0
CURVE_DEG = (10.0, 30.0)
WINDOW_MIN_S = 2.0
EPISODE_JOIN_S = 2.0
PRESS_LONG_S = 0.3
BLINKER_BEFORE_S = 2.0
# Toggles a scored drive must have stored (D-053: a toggle never written is not in initData, and its drive can't be
# attributed). John scores PR 10 drives against NrdrLatEpsFfAngleGate.
REQUIRED_PARAMS = ("NrdrLatEpsFfAngleGate",)
NAN = float("nan")


def read_segment(path):
  """Rows (dict of arrays over KEYS), the segment's liveDelay.lateralDelay values and its initData Nrdr* params."""
  from openpilot.tools.lib.logreader import LogReader
  rows, delays, params = [], [], {}
  cs = lp = cc = co = pose = None
  lane_change = NAN
  t0 = None
  try:
    for m in LogReader(path):
      w = m.which()
      if w == "initData":
        for p in m.initData.params.entries:
          if p.key.startswith("Nrdr"):
            params[p.key] = bytes(p.value).decode(errors="replace")
      elif w == "carState":
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
  return {k: arr[:, i] for i, k in enumerate(KEYS)}, delays, params


def band_of(v):
  for lo, hi, name in BANDS:
    if lo <= v < hi:
      return name
  return None


def shape_of(des):
  a = abs(des)
  if a < STRAIGHT_DEG:
    return "straight"
  if CURVE_DEG[0] <= a <= CURVE_DEG[1]:
    return "curve"
  return "other"


def _runs(keys):
  """(start, end exclusive, key) runs of equal non-None keys."""
  out, a = [], 0
  for i in range(1, len(keys) + 1):
    if i == len(keys) or keys[i] != keys[a]:
      if keys[a] is not None:
        out.append((a, i, keys[a]))
      a = i
  return out


def find_windows(d, seg):
  """John's P' labels on one segment's rows: engaged no-press windows, per-frame totals, and press runs."""
  t, n = d["t"], len(d["t"])
  if n < 2:
    return [], {}, []
  dt = np.clip(np.diff(t, append=t[-1]), 0.0, 0.1)
  engaged = (np.nan_to_num(d["active"]) > 0.5) & (np.nan_to_num(d["pressed"]) < 0.5)
  keys = [(band_of(d["v"][i]), shape_of(d["des_angle"][i])) if engaged[i] and np.isfinite(d["des_angle"][i])
          and band_of(d["v"][i]) else None for i in range(n)]
  totals = {}
  for i, k in enumerate(keys):
    if k is not None:
      totals.setdefault(k[0], {}).setdefault(k[1], 0.0)
      totals[k[0]][k[1]] += float(dt[i])
  windows = []
  for a, b, (band, shape) in _runs(keys):
    dur = float(t[b - 1] - t[a] + dt[b - 1])
    if dur >= WINDOW_MIN_S:
      windows.append({"seg": seg, "t0": round(float(t[a]), 3), "t1": round(float(t[b - 1] + dt[b - 1]), 3),
                      "s": round(dur, 2), "band": band, "shape": shape})
  pressed = np.nan_to_num(d["pressed"]) > 0.5
  signal = (np.nan_to_num(d["lblink"]) > 0.5) | (np.nan_to_num(d["rblink"]) > 0.5) | (np.nan_to_num(d["lane_change"]) > 0.5)
  presses = []
  for a, b, _ in _runs([True if p else None for p in pressed]):
    presses.append({"seg": seg, "t_press": round(float(t[a]), 3), "t_release": round(float(t[b - 1]), 3),
                    "held_s": round(float(t[b - 1] - t[a] + dt[b - 1]), 3),
                    "v": round(float(d["v"][a]), 2), "band": band_of(d["v"][a]),
                    "active_before": bool(np.nan_to_num(d["active"][max(0, a - 1)]) > 0.5),
                    "blinker": bool(signal[np.searchsorted(t, t[a] - BLINKER_BEFORE_S):b].any())})
  return windows, totals, presses


def press_summary(presses):
  """Numbers each press's episode in place and counts engaged presses, long presses and episodes per band.
  An episode counts when its first press was made while openpilot was steering, in that press's band."""
  out, ep, prev, head = {}, -1, None, None
  for p in presses:
    if prev is None or p["seg"] != prev["seg"] or p["t_press"] - prev["t_release"] > EPISODE_JOIN_S:
      ep += 1
      head = None
      if p["active_before"] and p["band"] is not None:
        head = out.setdefault(p["band"], {"presses": 0, "presses_long": 0, "episodes": 0, "episodes_blinker": 0})
        head["episodes"] += 1
      blinker = False
    p["episode"] = ep
    prev = p
    if head is not None and p.get("blinker") and not blinker:
      blinker = True
      head["episodes_blinker"] += 1
    if p["active_before"] and p["band"] is not None:
      c = out.setdefault(p["band"], {"presses": 0, "presses_long": 0, "episodes": 0, "episodes_blinker": 0})
      c["presses"] += 1
      c["presses_long"] += p["held_s"] >= PRESS_LONG_S
  return out


def _seg_name(path, i):
  d = os.path.basename(os.path.dirname(path))
  return d if d.isdigit() else str(i)


def export(seg_paths, out_dir, route=None, all_segments=False):
  os.makedirs(out_dir, exist_ok=True)
  info = {"schema": "drivePlotsSimExport/1", "route": route, "keys": list(KEYS), "segments": [], "params": {},
          "bands_ms": [b[2] for b in BANDS], "straight_deg": STRAIGHT_DEG, "curve_deg": list(CURVE_DEG),
          "window_min_s": WINDOW_MIN_S, "episode_join_s": EPISODE_JOIN_S, "press_long_s": PRESS_LONG_S,
          "windows": [], "window_totals_s": {}, "presses": []}
  delays = []
  for i, path in enumerate(seg_paths):
    d, dl, params = read_segment(path)
    delays += dl
    info["params"].update(params)
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
    windows, totals, presses = find_windows(d, seg["seg"])
    info["windows"] += windows
    info["presses"] += presses
    for band, shapes in totals.items():
      for shape, sec in shapes.items():
        tot = info["window_totals_s"].setdefault(band, {})
        tot[shape] = round(tot.get(shape, 0.0) + sec, 2)
  info["press_summary"] = press_summary(info["presses"])
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
  print(f"{len(written)} of {len(info['segments'])} segment(s) written to {a.out}; " +
        f"lateralDelay median {info['lateral_delay_median_s']}")
  print(f"params: {info['params'] or 'no Nrdr* toggle in initData'}")
  for k in REQUIRED_PARAMS:
    print(f"  {k} = {info['params'][k]}" if k in info["params"] else f"  WARNING: {k} is not in initData (never stored)")
  for band in info["bands_ms"]:
    sh = info["window_totals_s"].get(band, {})
    print(f"  {band:>6} m/s engaged, no press: straight {sh.get('straight', 0):7.1f} s  curve {sh.get('curve', 0):7.1f} s  " +
          f"other {sh.get('other', 0):7.1f} s")
  print(f"  {len(info['windows'])} window(s) >= {WINDOW_MIN_S:g} s, {len(info['presses'])} press(es)")
  for band in info["bands_ms"]:
    c = info["press_summary"].get(band, {})
    print(f"  {band:>6} m/s while steering: {c.get('episodes', 0):4d} episode(s) " +
          f"({c.get('episodes_blinker', 0)} with a blinker), " +
          f"{c.get('presses_long', 0):4d} press(es) >= {PRESS_LONG_S:g} s, {c.get('presses', 0):4d} raw")


if __name__ == "__main__":
  main()
