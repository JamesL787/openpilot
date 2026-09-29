#!/usr/bin/env python3
"""Every logged range-assist arm across a set of routes, log side only, as CSV plus one HTML page.

For Fix A v3 (Radar Work (Bob), 2026-09-29): does the trailing radar - camera rate over the arm's own range slope
split a range that walks onto the camera (00000297 10:55, ratio ~2.6) from a car that really closes with the radar
long (53:40, ratio ~0.0) beyond those two events? Each arm row carries that ratio, the correction peak, the logged
brake, and the assist class the replay viewer gives the frames of that episode.

Every number comes from long_replay_viewer's own functions on the logged radarState / liveTracks / modelV2, so a row
matches the viewer's "range-assist arm (log)" line for the same route and time (viewer t = route t here; the viewer
takes its window in the frames JSON's time, which for 00000297 is route t). Route data is read in place and never
written anywhere but --out.

  tools/longitudinal/range_arm_scan.py ~/routes/00000297--f971b5896f ... --out /tmp/arms
  tools/longitudinal/range_arm_scan.py --all ~/routes --out /tmp/arms -j 4
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from openpilot.tools.longitudinal.alpha_open_loop_replay import segment_files
from openpilot.tools.longitudinal.long_replay_viewer import (ASSIST_CLASSES, DD_PRE_S, VIS_PROB, XRATE_STEP_M,
                                                             XRATE_STEP_MIN_SIDE, XRATE_STEP_SSE_FRAC, _col, arr,
                                                             assist_masks, cutin_series, range_assist_arms, read_rlog)

U11_PRE_S = 3.0      # max liveTracks vRel (U11) of the armed track over [arm - 3 s, arm]  (Bob: range swings OUT first)
YAW_PRE_S = 5.0      # max |livePose yaw rate| over [arm - 5 s, arm]  (bend)
MIN_PEAK_MPS = 0.5    # arms whose correction never reaches this are listed only as a count (one-tick 0.04 blips)
PAIR_MIN_PTS = 10     # a same-car camera pair in [arm - DD_PRE_S, arm]: at least this many gated points
# Overshoot after the arm (Bob, 2026-09-29, separator for Fix A: does the assist push vLead BELOW the camera's speed?).
# ov = published vLead (vEgo + radarState vRel) - camera lead v, on same-car camera points with modelProb >= OV_PROB.
# ov_min over [arm, arm + OV_WIN_S], NaN under OV_MIN_PTS points. Bob's step rule (the camera-distance check's) runs on
# those points' camera x; on a step only the points before it are kept, the car the camera had at the arm (ov_step 1).
# ov_at_arm, raw_minus_cam (vEgo + U11 of the armed track, i.e. no assist, - camera v) and cam_v_minus_ego use the
# gated camera point nearest the arm, within OV_ARM_DT_S, else NaN.
OV_PROB = 0.9
OV_WIN_S = 2.0
OV_MIN_PTS = 5
OV_ARM_DT_S = 0.25

COLS = ["route", "t", "seg", "track", "d", "v_ego", "corr_at_arm", "corr_peak", "t_peak", "t_end",
        "dd_arm", "dd_rate_pre", "range_slope_pre", "dd_over_range_pre", "dd_n_pre", "dd_same_n_pre", "pair",
        "dd_2s", "dd_rate", "range_slope", "cam_slope", "cutting_in", "off", "rate",
        "min_cmd", "min_a_ego", "u11_max_pre", "yaw_abs_max_pre",
        "ov_min", "ov_n", "ov_step", "ov_at_arm", "raw_minus_cam", "cam_v_minus_ego", "cls", "n_phantom", "n_helped", "n_neutral", "n_unjudged"]


def _r(x, nd=2):
  return round(float(x), nd) if x is not None and np.isfinite(x) else None


def step_index(x) -> int | None:
  """Bob's step rule, as in xrate_verdict: index of the first point after a camera-x step, else None."""
  n = len(x)
  if n < 2 * XRATE_STEP_MIN_SIDE:
    return None
  sse_l = float(np.sum((x - np.polyval(np.polyfit(np.arange(n), x, 1), np.arange(n))) ** 2))
  k = np.arange(XRATE_STEP_MIN_SIDE, n - XRATE_STEP_MIN_SIDE + 1)
  c1, c2 = np.concatenate([[0], np.cumsum(x)]), np.concatenate([[0], np.cumsum(x * x)])
  sse_s = (c2[k] - c1[k] ** 2 / k) + (c2[n] - c2[k] - (c1[n] - c1[k]) ** 2 / (n - k))
  j = int(np.argmin(sse_s))
  step_m = abs(float(c1[k[j]] / k[j] - (c1[n] - c1[k[j]]) / (n - k[j])))
  frac = float(sse_s[j] / sse_l) if sse_l > 0 else 1.0
  return int(k[j]) if frac < XRATE_STEP_SSE_FRAC and step_m > XRATE_STEP_M else None


def scan_route(rdir: str) -> dict:
  t_start = time.monotonic()
  rdir_p = Path(rdir)
  files = segment_files(rdir_p)
  if not files:
    return {"route": rdir_p.name, "error": "no rlogs"}
  try:
    snaps, info = read_rlog(files)
  except Exception as e:  # a truncated segment should not end a corpus run
    return {"route": rdir_p.name, "error": f"read: {e}"}
  if not snaps or info["first_init"] is None:
    return {"route": rdir_p.name, "error": "no modelV2/initData"}
  t0 = info["first_init"]
  # rounded to 1 ms like the viewer's D["t"]: at 20 Hz a tick lands on the [arm - 1.5 s, arm] edge, and unrounded
  # nanoseconds dropped it here but not there (00000297 10:55: 19 vs 20 points, ratio 2.21 vs 2.57)
  t = np.round(np.array([(s["mono"] - t0) / 1e9 for s in snaps]), 3)
  L1l = []
  for s in snaps:
    L = s["rs"][0] if s["rs"] else None
    if L is not None and L[5]:
      pt = next((p for p in s["rs_tracks"] if p[0] == L[4]), None)
      L = L + [pt[3] if pt else None]
    elif L is not None:
      L = L + [None]
    L1l.append(L)
  vpl, vnl = _col(L1l, 2), _col(L1l, 7)
  corr = vnl - vpl
  base = {"route": rdir_p.name, "segments": len(files), "minutes": round(float(t[-1] - t[0]) / 60, 1)}
  if not np.isfinite(corr).any():
    return {**base, "arms": [], "blips": 0, "note": "no range-assist field", "secs": round(time.monotonic() - t_start, 1)}
  v = arr([s["cs"][0] if s["cs"] else None for s in snaps])
  a = arr([s["cs"][1] if s["cs"] else None for s in snaps])
  cmd = arr([s.get("cc_a") for s in snaps])
  vis = [s["leads"][0] if s["leads"] else None for s in snaps]
  tracks = [s["rs_tracks"] for s in snaps]
  paths = [s["path"] for s in snaps]
  yaw = np.abs(arr([s.get("yaw") for s in snaps]))

  ser = cutin_series(t, L1l, 4, tracks, paths)
  arms = range_assist_arms(t, corr, ser, L1l, tracks, vis, v, a, cmd)

  # same inputs as the viewer's log-side assist_classes
  dl, rl = _col(L1l, 0), _col(L1l, 5)
  vis_d, vis_p, vis_v = _col(vis, 0), _col(vis, 3), _col(vis, 2)
  same = (rl == 1) & (vis_p > VIS_PROB) & (np.abs(dl - vis_d) < np.maximum(10.0, 0.2 * dl))
  masks, _ = assist_masks(t, corr, v + vpl, v + vnl, vis_v, same, dl, vis_d, vpl)
  ov_ok = same & (vis_p >= OV_PROB) & np.isfinite(vis_v) & np.isfinite(vpl) & np.isfinite(v)
  ov = v + vpl - vis_v

  rows, blips = [], 0
  for r in arms:
    if r["corr_peak"] is None or r["corr_peak"] < MIN_PEAK_MPS:
      blips += 1
      continue
    ep = (t >= r["t"]) & (t <= r["t_end"])
    lo, hi = np.searchsorted(t, r["t"] - U11_PRE_S), np.searchsorted(t, r["t"], side="right")
    u11 = [p[3] for i in range(lo, hi) for p in tracks[i] if p[0] == r["track"] and p[3] is not None]
    lo_y = np.searchsorted(t, r["t"] - YAW_PRE_S)
    yw = yaw[lo_y:hi][np.isfinite(yaw[lo_y:hi])]
    n = {k: int((masks[k] & ep).sum()) for k in ASSIST_CLASSES}
    w = np.where(ov_ok & (t >= r["t"]) & (t <= r["t"] + OV_WIN_S))[0]
    brk = step_index(vis_d[w]) if w.size else None
    if brk is not None:
      w = w[:brk]
    near = np.where(ov_ok & (np.abs(t - r["t"]) <= OV_ARM_DT_S))[0]
    i0 = near[np.argmin(np.abs(t[near] - r["t"]))] if near.size else None
    u0 = None
    if i0 is not None:
      u0 = next((q[3] for q in tracks[i0] if q[0] == r["track"] and q[3] is not None), None)
    cls = max(ASSIST_CLASSES, key=lambda k: (n[k], -ASSIST_CLASSES.index(k))) if any(n.values()) else "none"
    rows.append({"route": rdir_p.name, "seg": int(r["t"] // 60), **{k: r.get(k) for k in COLS if k in r},
                 "t": round(r["t"], 2), "t_end": round(r["t_end"], 2), "t_peak": round(r["t_peak"], 2),
                 "u11_max_pre": round(max(u11), 2) if u11 else None,
                 "yaw_abs_max_pre": round(float(yw.max()), 4) if yw.size else None,
                 "pair": int((r["dd_same_n_pre"] or 0) >= PAIR_MIN_PTS), "cls": cls,
                 "ov_min": _r(ov[w].min()) if w.size >= OV_MIN_PTS else None, "ov_n": int(w.size),
                 "ov_step": int(brk is not None), "ov_at_arm": _r(ov[i0]) if i0 is not None else None,
                 "raw_minus_cam": _r(v[i0] + u0 - vis_v[i0]) if u0 is not None else None,
                 "cam_v_minus_ego": _r(vis_v[i0] - v[i0]) if i0 is not None else None,
                 **{f"n_{k}": n[k] for k in ASSIST_CLASSES}})
  return {**base, "arms": rows, "blips": blips, "secs": round(time.monotonic() - t_start, 1)}


def _f(x, nd=2):
  return "" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


OV_SWEEP = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
OV_CUT_M = (80.0, 120.0)   # Bob's far-arm cut on d at the arm


def ov_summary(rows: list[dict]) -> str:
  """Does ov_min < -X split phantom from helped? Counts per class, all arms and the 80-120 m cut; plain text."""
  out = []
  for name, sub in (("all arms", rows), (f"d {OV_CUT_M[0]:g}-{OV_CUT_M[1]:g} m",
                                          [r for r in rows if r["d"] is not None and OV_CUT_M[0] <= r["d"] <= OV_CUT_M[1]])):
    out.append(f"{name}: {len(sub)} arms")
    for c in ASSIST_CLASSES + ("none",):
      cr = [r for r in sub if r["cls"] == c]
      if not cr:
        continue
      got = sorted(r["ov_min"] for r in cr if r["ov_min"] is not None)
      any_pt = sum(1 for r in cr if r["ov_n"] > 0)
      med = f"{got[len(got) // 2]:.2f}" if got else "-"
      sweep = "  ".join(f"<-{x:g}:{sum(1 for g in got if g < -x)}" for x in OV_SWEEP)
      out.append(f"  {c:9s} n {len(cr):3d}  any camera pt in 2 s {any_pt:3d}  ov_min (>= {OV_MIN_PTS} pts) {len(got):3d}"
                 + f"  median {med:>6s}  {sweep}")
  return "\n".join(out)


def write_html(out: Path, rows: list[dict], routes: list[dict]) -> None:
  pair = [r for r in rows if r["pair"] and r["dd_over_range_pre"] is not None]
  CLS_COL = {"phantom": "#ff4d6d", "helped": "#52b788", "neutral": "#ffd60a", "unjudged": "#8d99ae", "none": "#4a4e69"}
  # scatter: x = range slope pre, y = radar - camera rate pre; the y = x line is "range walks onto the camera"
  W, H, P, LIM = 520, 520, 40, 12.0
  sx = lambda x: P + (np.clip(x, -LIM, LIM) + LIM) / (2 * LIM) * (W - 2 * P)  # noqa: E731
  sy = lambda y: H - P - (np.clip(y, -LIM, LIM) + LIM) / (2 * LIM) * (H - 2 * P)  # noqa: E731
  svg = [f'<svg width="{W}" height="{H}" style="background:#0b0d12">',
         f'<line x1="{sx(-LIM)}" y1="{sy(-LIM)}" x2="{sx(LIM)}" y2="{sy(LIM)}" stroke="#555" stroke-dasharray="4 3"/>',
         f'<line x1="{sx(-LIM)}" y1="{sy(0)}" x2="{sx(LIM)}" y2="{sy(0)}" stroke="#333"/>',
         f'<line x1="{sx(0)}" y1="{sy(-LIM)}" x2="{sx(0)}" y2="{sy(LIM)}" stroke="#333"/>',
         f'<text x="{P}" y="{P - 12}" fill="#aaa" font-size="11">y: radar − camera rate over [arm − {DD_PRE_S:g} s, arm] m/s'
         + '  ·  x: range slope same window  ·  dashed: y = x (range walks, camera holds)</text>']
  for r in pair:
    tip = html.escape(f"{r['route']} t {r['t']} track {r['track']} ratio {r['dd_over_range_pre']} peak {r['corr_peak']} {r['cls']}")
    svg.append(f'<circle cx="{sx(r["range_slope_pre"]):.1f}" cy="{sy(r["dd_rate_pre"]):.1f}" r="{3 + min(r["corr_peak"], 8) / 2:.1f}" '
               + f'fill="{CLS_COL[r["cls"]]}" fill-opacity="0.75"><title>{tip}</title></circle>')
  svg.append("</svg>")

  def hist(key_rows):
    edges = [-np.inf, -0.5, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, np.inf]
    lab = ["< −0.5", "−0.5–0", "0–0.25", "0.25–0.5", "0.5–0.75", "0.75–1", "1–1.5", "1.5–2", "≥ 2"]
    head = "<tr><th>ratio</th>" + "".join(f"<th>{c}</th>" for c in (*ASSIST_CLASSES, "none")) + "</tr>"
    body = []
    for lo, hi, lb in zip(edges[:-1], edges[1:], lab, strict=True):
      sel = [r for r in key_rows if lo <= r["dd_over_range_pre"] < hi]
      body.append(f"<tr><td>{lb}</td>" + "".join(f"<td>{sum(r['cls'] == c for r in sel) or ''}</td>" for c in (*ASSIST_CLASSES, "none")) + "</tr>")
    return f"<table>{head}{''.join(body)}</table>"

  trs = []
  for r in sorted(rows, key=lambda r: (-r["pair"], ASSIST_CLASSES.index(r["cls"]) if r["cls"] in ASSIST_CLASSES else 9, -r["corr_peak"])):
    trs.append(f'<tr style="color:{CLS_COL[r["cls"]]}">' + "".join(f"<td>{html.escape(_f(r.get(c)))}</td>" for c in COLS) + "</tr>")
  rt = "".join(f"<tr><td>{html.escape(x['route'])}</td><td>{x.get('segments', '')}</td><td>{x.get('minutes', '')}</td>"
               + f"<td>{len(x.get('arms', []))}</td><td>{x.get('blips', '')}</td><td>{html.escape(x.get('error') or x.get('note') or '')}</td></tr>"
               for x in routes)
  out.write_text(f"""<!doctype html><meta charset="utf-8"><title>range-assist arms</title>
<style>body{{background:#0b0d12;color:#ddd;font:12px monospace;margin:16px}} table{{border-collapse:collapse;margin:8px 0}}
td,th{{border:1px solid #222;padding:2px 6px;text-align:right}} th{{color:#aaa}} h2{{color:#eee;font-size:14px}}</style>
<h2>Range-assist arms, log side, replay of logged data only (no road validation)</h2>
<p>{len(rows)} arms with correction peak ≥ {MIN_PEAK_MPS} m/s across {len(routes)} routes; {len(pair)} have a same-car camera pair
(≥ {PAIR_MIN_PTS} gated points in the trailing {DD_PRE_S:g} s) and a range slope past 0.5 m/s, so a ratio.
Class = the viewer's assist class held by the most frames of the episode (extra closing ≥ 2 m/s); "none" = the
correction never reached 2 m/s. 00000297 10:55 ≈ 2.6, 53:40 ≈ 0.0.</p>
<h2>ratio = dd_rate_pre / range_slope_pre, by class (pair arms)</h2>{hist(pair)}
<h2>scatter (pair arms; dot size = correction peak; hover for route/time)</h2>{''.join(svg)}
<h2>overshoot after the arm: ov_min = min over [arm, arm + {OV_WIN_S:g} s] of published vLead - camera v
(same car, p ≥ {OV_PROB:g}, ≥ {OV_MIN_PTS} pts); "&lt;-X:n" = arms of that class with ov_min below -X</h2>
<pre>{html.escape(ov_summary(rows))}</pre>
<h2>every arm (pair arms first)</h2><table><tr>{''.join(f'<th>{c}</th>' for c in COLS)}</tr>{''.join(trs)}</table>
<h2>routes</h2><table><tr><th>route</th><th>segments</th><th>minutes</th><th>arms</th><th>blips &lt; {MIN_PEAK_MPS}</th><th>note</th></tr>{rt}</table>
""")


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("routes", nargs="+", help="route dirs (segment subdirs with rlogs), or with --all a parent of route dirs")
  ap.add_argument("--all", action="store_true", help="scan every route dir under the given parent(s)")
  ap.add_argument("--out", type=Path, required=True)
  ap.add_argument("-j", type=int, default=4, help="routes read in parallel (each holds one route in memory)")
  args = ap.parse_args()
  dirs = [str(d) for p in args.routes for d in (sorted(Path(p).iterdir()) if args.all else [Path(p)]) if Path(d).is_dir()]
  # biggest first so the long routes do not finish last on one core
  dirs.sort(key=lambda d: -len(segment_files(Path(d))))
  args.out.mkdir(parents=True, exist_ok=True)
  routes = []
  with Pool(args.j) as pool:
    for k, res in enumerate(pool.imap_unordered(scan_route, dirs), 1):
      routes.append(res)
      print(f"[{k}/{len(dirs)}] {res['route']}: {len(res.get('arms', []))} arms {res.get('error') or res.get('note') or ''}"
            + f" {res.get('secs', '')} s", file=sys.stderr, flush=True)
  routes.sort(key=lambda x: x["route"])
  rows = [r for x in routes for r in x.get("arms", [])]
  with open(args.out / "arms.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS)
    w.writeheader()
    for r in rows:
      w.writerow({c: r.get(c) for c in COLS})
  (args.out / "routes.json").write_text(json.dumps([{k: v for k, v in x.items() if k != "arms"} for x in routes], indent=1))
  write_html(args.out / "arms.html", rows, routes)
  (args.out / "ov_summary.txt").write_text(ov_summary(rows) + "\n")
  print(ov_summary(rows), file=sys.stderr)
  print(f"wrote {args.out / 'arms.csv'} ({len(rows)} arms) and {args.out / 'arms.html'}", file=sys.stderr)
  return 0


if __name__ == "__main__":
  sys.exit(main())
