#!/usr/bin/env python3
"""Is a Bosch-A track that is BORN on the U11 rail really closing that fast?

Why this exists
---------------
docs/research/bosch-a-bank-is-the-camera-2026-10-04.pdf (owner report) identifies the 16-slot
"Bosch-A" object bank (0x280-0x2FF, aux 0x2C8-0x2CF / 0x290-0x297) as the output of Honda's
windshield-camera tracker. U11 is that tracker's velocity state: low-pass (tau ~0.6 s), decoded
at 1/72 m/s, saturating at +-12.0 m/s. A freshly initialised tracker state can sit on the rail
while it spins up. Motivating case: 000002d5--1393dccb3d ~718 s, cut-in track 23 promoted at
54.8 m with U11 on the -12 rail, radard published the -20 RAIL_FAST bound and the car braked at
-3.5; the lead then settled ~35 m ahead at ~17 m/s with ego starting at 22 m/s, i.e. ~5 m/s of
true closing at birth.

This tool measures, over whole routes, how often a born-railed track's rail is genuine. It
reads the RAW bank from CAN (not liveTracks, whose vRel is the parser's processed value) and
builds a truth estimate that uses neither openpilot vision nor U11:

  (a) settle anchor: the first >= SETTLE_WINDOW_S window at age SETTLE_AGE_MIN_S..MAX_S whose
      linear-fit range rate is within +-SETTLE_RATE_MAX_MPS. Constancy is robust to a range
      SCALE error (the report measures the bank closing only 71-90% of odometry), so the lead
      speed ~= mean carState.vEgo there (wheel odometry), plus the small fitted rate. Truth
      closing at the reference time = vEgo(ref) - v_lead. ASSUMES the lead's speed did not
      change between the reference time and the window; ego accel over that gap is reported
      so a reader can judge it (a lead that braked or accelerated breaks the anchor).
  (b) stationary anchor: U11 (median over a 1 s window at age 1-6 s) within 10% of -vEgo with
      vEgo >= 5 m/s: the target is stopped, truth closing = vEgo(ref). Only possible below the
      12 m/s rail.
  (c) camera range-rate over age 0.5-1.5 s scaled by 1/CAM_RANGE_SCALE. SECONDARY and NOT
      independent of the camera -- labelled "cam" and never used as truth.

The reference time is the track's birth for born-railed tracks, and the first railed sweep for
the contrast group (tracks not born railed that reach the rail later).

Status: replay/offline statistics only. Track identity is the bank TRACK_ID; a new incarnation
starts after a gap > INCARNATION_GAP_S. Nothing here is road-validated.

Usage
-----
    python tools/bosch_a_birth_rail_report.py <route_dir> [<route_dir> ...] [--jobs 4]

Each route_dir holds numbered segment subdirectories with an rlog (rlog.zst / rlog.bz2 / rlog).
Route time is logMonoTime minus initData's logMonoTime (logger start), as in the sweep trace.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import opendbc.car.honda.radar_interface as RI
from opendbc.can.dbc import DBC
from opendbc.can.parser import get_raw_value
from openpilot.tools.lib.logreader import _LogFileReader

U11_CPS = RI.BOSCH_A_DIRECT_VREL_COUNTS_PER_MPS          # 72 (D-074)
U11_CENTER = RI.BOSCH_A_DIRECT_VREL_CENTER_RAW            # 864
U11_RAIL = (RI.BOSCH_A_DIRECT_VREL_MAX_RAW - U11_CENTER) / U11_CPS   # 12.0
RAIL_TOL_MPS = 0.5          # "on the rail" = within this of +-12.0
BIRTH_WINDOW_S = 0.5        # born railed = railed on any sweep in the first 0.5 s of life
MIN_LIFE_S = 3.0            # anchors are only attempted on tracks that live this long
INCARNATION_GAP_S = 0.3     # TRACK_ID absent longer than this -> a new track
ROUTE_START_GUARD_S = 1.0   # tracks present in the first second of a log were not born there
SETTLE_AGE_MIN_S, SETTLE_AGE_MAX_S = 1.0, 6.0
SETTLE_WINDOW_S = 1.0
SETTLE_RATE_MAX_MPS = 0.5
SETTLE_MIN_SWEEPS = 8
STATIONARY_TOL = 0.10
STATIONARY_MIN_VEGO = 5.0
CAM_RANGE_SCALE = 0.8       # bank range closes 71-90% of odometry (owner report); midpoint
OVERSTATED_TRUTH_MAX = 8.0  # truth < 8 => rail overstated by > 4 m/s
GENUINE_TRUTH_MIN = 11.0
RADARD_RAIL_FAST_BOUND = -19.5   # radard publishes -20 on RAIL_FAST; anything at/below this counts
LEAD_WINDOW_S = 3.0         # leadOne tenure looked at: promotion age and min published vRel in the first 3 s
TIMECOURSE_AGES = (0.0, 0.25, 0.5, 1.0, 1.5)
SWEEP_END_ADDR = RI.BOSCH_A_SWEEP_END_MSG   # 0x297, last frame of a sweep

_SIGS = {  # (frame index within the slot, signal names); aux is index 4
  0: ("FRAME_IDX", "STATUS", "RANGE_RAW", "AZIMUTH_RAW"),
  1: ("FRAME_IDX",),
  2: ("FRAME_IDX", "LIFECYCLE_RAW"),
  3: ("FRAME_IDX", "TRACK_ID"),
  4: ("FRAME_IDX", "REL_VELOCITY_RAW", "REL_VELOCITY_UNCERTAINTY_RAW"),
}


def _decoder():
  dbc = DBC(RI.BOSCH_A_DBC_NAME)
  table = {}
  for slot in range(RI.BOSCH_A_NUM_SLOTS):
    for k, addr in enumerate(RI.BOSCH_A_MAIN_IDS[slot] + [RI.BOSCH_A_AUX_IDS[slot]]):
      msg = dbc.addr_to_msg[addr]
      table[addr] = (slot, k, [(n, msg.sigs[n]) for n in _SIGS[k]])
  return table


def _route_files(route_dir: str) -> list[tuple[int, str]]:
  out = []
  for d in os.listdir(route_dir):
    if d.isdigit():
      g = sorted(glob.glob(os.path.join(route_dir, d, "rlog*")))
      if g:
        out.append((int(d), g[0]))
  return sorted(out)


def read_segment(path: str) -> dict:
  """Raw bank sweeps plus the ego / radarState / liveTracks series, in absolute logMonoTime seconds."""
  table = _decoder()
  init_t = None
  bus = None
  bus_votes: Counter = Counter()
  frames: dict[tuple[int, int], dict] = {}   # (slot, k) -> decoded signals for the current sweep
  sweeps: list[tuple[float, list[tuple]]] = []
  car: list[tuple[float, float, float]] = []
  lead1: list[tuple[float, int, float, float]] = []
  lt: list[tuple[float, int, float]] = []

  def flush(t: float):
    objs = []
    for slot in range(RI.BOSCH_A_NUM_SLOTS):
      fs = [frames.get((slot, k)) for k in range(4)]
      if any(f is None for f in fs) or len({f["FRAME_IDX"] for f in fs}) != 1:
        continue
      f0, f2, f3 = fs[0], fs[2], fs[3]
      rr, ar, tid = f0["RANGE_RAW"], f0["AZIMUTH_RAW"], f3["TRACK_ID"]
      if (f0["STATUS"] == RI.BOSCH_A_STATUS_INVALID or rr == RI.BOSCH_A_RANGE_RAW_INVALID or
          ar == RI.BOSCH_A_ANGLE_RAW_INVALID or f2["LIFECYCLE_RAW"] == RI.BOSCH_A_LIFE_INVALID or
          not RI.BOSCH_A_TRACK_ID_MIN <= tid <= RI.BOSCH_A_TRACK_ID_MAX):
        continue
      d = RI.BOSCH_A_RANGE_SCALE_M * rr + RI.BOSCH_A_RANGE_OFFSET_M
      y = d * math.tan(RI.BOSCH_A_AZIMUTH_SCALE_RAD * (ar - RI.BOSCH_A_AZIMUTH_CENTER))
      aux = frames.get((slot, 4))
      u11 = None
      if aux is not None and aux["FRAME_IDX"] == f0["FRAME_IDX"] and aux["REL_VELOCITY_RAW"] != RI.BOSCH_A_DIRECT_VREL_INVALID:
        u11 = (aux["REL_VELOCITY_RAW"] - U11_CENTER) / U11_CPS
      objs.append((tid, d, y, u11))
    sweeps.append((t, objs))
    frames.clear()

  for msg in _LogFileReader(path):
    which = msg.which()
    if which == "initData":
      init_t = msg.logMonoTime * 1e-9
      continue
    if which == "sentinel":
      continue
    t = msg.logMonoTime * 1e-9
    if which == "can":
      for fr in msg.can:
        ent = table.get(fr.address)
        if ent is None:
          continue
        if bus is None:
          bus_votes[fr.src] += 1
          if sum(bus_votes.values()) >= 200:
            bus = bus_votes.most_common(1)[0][0]
          continue
        if fr.src != bus:
          continue
        slot, k, sigs = ent
        dat = bytes(fr.dat)
        if (slot, k) in frames and k == 0 and slot == 0:
          flush(t)   # a new sweep started without its 0x297 (dropped aux)
        frames[(slot, k)] = {n: get_raw_value(dat, s) for n, s in sigs}
        if fr.address == SWEEP_END_ADDR:
          flush(t)
    elif which == "carState":
      car.append((t, float(msg.carState.vEgo), float(msg.carState.aEgo)))
    elif which == "radarState":
      ld = msg.radarState.leadOne
      if ld.status:
        lead1.append((t, int(ld.radarTrackId), float(ld.vRel), float(ld.dRel)))
    elif which == "liveTracks":
      for p in msg.liveTracks.points:
        lt.append((t, int(p.trackId), float(p.vRel)))
  return {"path": path, "init_t": init_t, "sweeps": sweeps, "car": car, "lead1": lead1, "lt": lt}


# --- pure helpers (no capnp) ------------------------------------------------------------------------

def linfit_slope(ts: list[float], xs: list[float]) -> float | None:
  n = len(ts)
  if n < 2:
    return None
  mt, mx = sum(ts) / n, sum(xs) / n
  den = sum((t - mt) ** 2 for t in ts)
  if den <= 0:
    return None
  return sum((t - mt) * (x - mx) for t, x in zip(ts, xs, strict=True)) / den


def interp(series: list[tuple], t: float, idx: int = 1) -> float | None:
  """Nearest-sample lookup in a time-sorted series (bisect)."""
  if not series:
    return None
  lo, hi = 0, len(series) - 1
  while lo < hi:
    mid = (lo + hi) // 2
    if series[mid][0] < t:
      lo = mid + 1
    else:
      hi = mid
  best = min((i for i in (lo - 1, lo) if 0 <= i < len(series)), key=lambda i: abs(series[i][0] - t))
  if abs(series[best][0] - t) > 0.5:
    return None
  return series[best][idx]


def mean_in(series: list[tuple], a: float, b: float, idx: int = 1) -> float | None:
  vals = [s[idx] for s in series if a <= s[0] <= b]
  return sum(vals) / len(vals) if vals else None


def build_tracks(sweeps: list[tuple[float, list[tuple]]], log_start: float) -> list[dict]:
  """Split TRACK_ID sightings into incarnations. Each track: samples [(t, d, y, u11)]."""
  open_tracks: dict[int, dict] = {}
  done: list[dict] = []
  for t, objs in sweeps:
    for tid, d, y, u11 in objs:
      tr = open_tracks.get(tid)
      if tr is not None and t - tr["samples"][-1][0] > INCARNATION_GAP_S:
        done.append(tr)
        tr = None
      if tr is None:
        tr = open_tracks[tid] = {"tid": tid, "samples": [], "censored": t - log_start < ROUTE_START_GUARD_S}
      if tr["samples"] and tr["samples"][-1][0] == t:
        continue   # duplicate identity in two slots this sweep: keep the first
      tr["samples"].append((t, d, y, u11))
  done.extend(open_tracks.values())
  return done


def settle_anchor(samples: list[tuple], t_ref: float, car: list[tuple]) -> dict | None:
  for i, s in enumerate(samples):
    age = s[0] - t_ref
    if age < SETTLE_AGE_MIN_S:
      continue
    if age > SETTLE_AGE_MAX_S - SETTLE_WINDOW_S:
      break
    win = [x for x in samples[i:] if x[0] <= s[0] + SETTLE_WINDOW_S]
    if len(win) < SETTLE_MIN_SWEEPS or win[-1][0] - win[0][0] < SETTLE_WINDOW_S * 0.9:
      continue
    if any(b[0] - a[0] > 0.3 for a, b in zip(win, win[1:], strict=False)):
      continue
    slope = linfit_slope([x[0] for x in win], [x[1] for x in win])
    if slope is None or abs(slope) > SETTLE_RATE_MAX_MPS:
      continue
    v_ego_win = mean_in(car, win[0][0], win[-1][0])
    if v_ego_win is None:
      continue
    return {"v_lead": v_ego_win + slope, "t0": win[0][0], "t1": win[-1][0], "slope": slope, "v_ego_win": v_ego_win}
  return None


def stationary_anchor(samples: list[tuple], t_ref: float, car: list[tuple]) -> bool:
  for i, s in enumerate(samples):
    age = s[0] - t_ref
    if age < SETTLE_AGE_MIN_S:
      continue
    if age > SETTLE_AGE_MAX_S - SETTLE_WINDOW_S:
      break
    win = [x for x in samples[i:] if x[0] <= s[0] + SETTLE_WINDOW_S and x[3] is not None]
    if len(win) < SETTLE_MIN_SWEEPS:
      continue
    v = mean_in(car, win[0][0], win[-1][0])
    if v is None or v < STATIONARY_MIN_VEGO:
      continue
    u = statistics.median(x[3] for x in win)
    if abs(u + v) <= STATIONARY_TOL * v:
      return True
  return False


def cam_rate(samples: list[tuple], t_ref: float) -> float | None:
  win = [x for x in samples if 0.5 <= x[0] - t_ref <= 1.5]
  if len(win) < 5:
    return None
  slope = linfit_slope([x[0] for x in win], [x[1] for x in win])
  return None if slope is None else -slope / CAM_RANGE_SCALE


def truth_at(samples: list[tuple], t_ref: float, car: list[tuple]) -> dict:
  v_ref = interp(car, t_ref)
  out = {"v_ego": v_ref, "truth": None, "anchor": "none", "cam": cam_rate(samples, t_ref), "ego_dv": None}
  if v_ref is None:
    return out
  sa = settle_anchor(samples, t_ref, car)
  if sa is not None:
    out.update(truth=v_ref - sa["v_lead"], anchor=f"settle@{sa['t0'] - t_ref:.1f}s",
               ego_dv=sa["v_ego_win"] - v_ref)
  elif stationary_anchor(samples, t_ref, car):
    out.update(truth=v_ref, anchor="stationary")
  return out


def analyse_route(route_dir: str, segs: list[dict]) -> list[dict]:
  segs = sorted(segs, key=lambda s: s["sweeps"][0][0] if s["sweeps"] else 0.0)
  init_t = next((s["init_t"] for s in segs if s["init_t"] is not None), None)
  sweeps = sorted((sw for s in segs for sw in s["sweeps"]), key=lambda x: x[0])
  car = sorted(c for s in segs for c in s["car"])
  lead1 = sorted(x for s in segs for x in s["lead1"])
  lt_by_tid: dict[int, list[tuple]] = defaultdict(list)
  for s in segs:
    for t, tid, v in s["lt"]:
      lt_by_tid[tid].append((t, v))
  if init_t is None:
    init_t = sweeps[0][0] if sweeps else 0.0
  # Segment starts (after a gap) are not births either: guard every log start.
  starts = sorted({s["sweeps"][0][0] for s in segs if s["sweeps"]})
  tracks = []
  for tr in build_tracks(sweeps, sweeps[0][0] if sweeps else 0.0):
    t_b = tr["samples"][0][0]
    if tr["censored"] or any(0 <= t_b - st < ROUTE_START_GUARD_S and not _continuous(sweeps, st) for st in starts):
      continue
    smp = tr["samples"]
    life = smp[-1][0] - t_b
    birth_u = [x[3] for x in smp if x[0] - t_b <= BIRTH_WINDOW_S and x[3] is not None]
    born_low = any(u <= -U11_RAIL + RAIL_TOL_MPS for u in birth_u)
    born_high = any(u >= U11_RAIL - RAIL_TOL_MPS for u in birth_u)
    later_low = next((x[0] for x in smp if x[0] - t_b > BIRTH_WINDOW_S and x[3] is not None
                      and x[3] <= -U11_RAIL + RAIL_TOL_MPS), None)
    lead_ts = [x for x in lead1 if t_b <= x[0] <= t_b + LEAD_WINDOW_S and x[1] == tr["tid"]]
    lt_v = [v for t, v in lt_by_tid.get(tr["tid"], []) if t_b <= t <= t_b + BIRTH_WINDOW_S]
    rec = {
      "route": os.path.basename(os.path.normpath(route_dir)), "t": t_b - init_t, "tid": tr["tid"],
      "d": smp[0][1], "y": smp[0][2], "life": life, "born_low": born_low, "born_high": born_high,
      "u11_min05": min(birth_u) if birth_u else None, "later_low_t": later_low,
      "lead1_1s": any(x[0] - t_b <= 1.0 for x in lead_ts),
      "lead1_age": lead_ts[0][0] - t_b if lead_ts else None,
      "lead1_vmin": min((x[2] for x in lead_ts), default=None),
      "lt_vmin05": min(lt_v, default=None),
      "u_at": {a: _u_at(smp, t_b + a) for a in TIMECOURSE_AGES},
    }
    rec["pub_rail_fast"] = rec["lead1_vmin"] is not None and rec["lead1_vmin"] <= RADARD_RAIL_FAST_BOUND
    if life >= MIN_LIFE_S and (born_low or born_high or rec["pub_rail_fast"]):
      rec.update(truth_at(smp, t_b, car))
    elif life >= MIN_LIFE_S and later_low is not None:
      rec.update(truth_at([x for x in smp if x[0] >= later_low], later_low, car))
      rec["t_rail"] = later_low - init_t
    else:
      rec["v_ego"] = interp(car, t_b)
    tracks.append(rec)
  return tracks


def _continuous(sweeps: list[tuple], t: float) -> bool:
  """True when a sweep exists within 0.3 s before t (the log did not just start)."""
  lo, hi = 0, len(sweeps)
  while lo < hi:
    mid = (lo + hi) // 2
    if sweeps[mid][0] < t:
      lo = mid + 1
    else:
      hi = mid
  return lo > 0 and t - sweeps[lo - 1][0] <= 0.3


def _u_at(smp: list[tuple], t: float) -> float | None:
  best = min(smp, key=lambda x: abs(x[0] - t))
  return best[3] if abs(best[0] - t) <= 0.1 else None


# --- report -----------------------------------------------------------------------------------------

def _f(x, n=1):
  return "  -  " if x is None else f"{x:.{n}f}"


def _dist(vals: list[float]) -> str:
  if not vals:
    return "n=0"
  q = statistics.quantiles(vals, n=20, method="inclusive") if len(vals) > 1 else [vals[0]] * 19
  return (f"n={len(vals)}  p5 {q[0]:.1f}  p25 {q[4]:.1f}  p50 {statistics.median(vals):.1f}  " +
          f"p75 {q[14]:.1f}  p95 {q[18]:.1f}  min {min(vals):.1f}  max {max(vals):.1f}")


def _group_stats(out: list[str], title: str, rows: list[dict]) -> None:
  anch = [r for r in rows if r.get("truth") is not None]
  out.append(f"\n{title}: {len(rows)} tracks living >= {MIN_LIFE_S:.0f} s, {len(anch)} with an independent anchor " +
             f"({sum(r['anchor'].startswith('settle') for r in anch)} settle, " +
             f"{sum(r['anchor'] == 'stationary' for r in anch)} stationary)")
  if not anch:
    return
  truths = [r["truth"] for r in anch]
  out.append(f"  truth closing (m/s):            {_dist(truths)}")
  out.append(f"  rail magnitude - truth (m/s):   {_dist([U11_RAIL - x for x in truths])}")
  over = sum(x < OVERSTATED_TRUTH_MAX for x in truths)
  gen = sum(x >= GENUINE_TRUTH_MIN for x in truths)
  out.append(f"  truth < {OVERSTATED_TRUTH_MAX:.0f} (rail overstated > 4 m/s): {over}/{len(anch)} = {100 * over / len(anch):.0f}%")
  out.append(f"  truth >= {GENUINE_TRUTH_MIN:.0f} (rail genuine):              {gen}/{len(anch)} = {100 * gen / len(anch):.0f}%")
  dv = [r["ego_dv"] for r in anch if r.get("ego_dv") is not None]
  if dv:
    out.append(f"  ego dv birth->settle window (m/s, anchor-validity check): {_dist(dv)}")
  cam = [r["cam"] - r["truth"] for r in anch if r.get("cam") is not None]
  if cam:
    out.append(f"  cam range-rate(0.5-1.5 s)/{CAM_RANGE_SCALE} minus truth (secondary, camera): {_dist(cam)}")


def render(tracks: list[dict]) -> str:
  out = []
  all_n = len(tracks)
  low = [r for r in tracks if r["born_low"]]
  high = [r for r in tracks if r["born_high"]]
  out.append(f"Bosch-A birth-rail report  (raw bank decode, U11 at 1/{U11_CPS}, rail +-{U11_RAIL:.1f}, " +
             f"railed = within {RAIL_TOL_MPS} m/s, birth window {BIRTH_WINDOW_S} s)")
  out.append(f"tracks born (excl. log-start censored): {all_n}")
  out.append(f"  born on LOW rail (-12):  {len(low)}  ({sum(r['life'] >= MIN_LIFE_S for r in low)} live >= {MIN_LIFE_S:.0f} s)")
  out.append(f"  born on HIGH rail (+12): {len(high)}  ({sum(r['life'] >= MIN_LIFE_S for r in high)} live >= {MIN_LIFE_S:.0f} s)")
  pubrf = [r for r in tracks if r["pub_rail_fast"]]
  out.append(f"  leadOne in first {LEAD_WINDOW_S:.0f} s of life with published vRel <= {RADARD_RAIL_FAST_BOUND}: {len(pubrf)} " +
             f"({sum(r['born_low'] for r in pubrf)} of them born on the low rail)")
  out.append(f"  born-low-railed tracks that became leadOne within 1 s of birth: {sum(r['lead1_1s'] for r in low)}/{len(low)}" +
             f"  (living >= 3 s: {sum(r['lead1_1s'] for r in low if r['life'] >= MIN_LIFE_S)}); within " +
             f"{LEAD_WINDOW_S:.0f} s: {sum(r['lead1_age'] is not None for r in low)}")

  hdr = (f"{'route':22s} {'t(s)':>8s} {'tid':>3s} {'d':>5s} {'y':>5s} {'vEgo':>5s} {'U11min':>6s} {'L1':>2s} " +
         f"{'L1age':>5s} {'L1vmin':>6s} {'life':>5s} {'truth':>5s} {'cam':>5s} {'egodv':>5s} anchor")

  def row(r, t_key="t"):
    return (f"{r['route']:22s} {r[t_key]:8.2f} {r['tid']:3d} {r['d']:5.1f} {r['y']:5.2f} {_f(r.get('v_ego'))} " +
            f"{_f(r['u11_min05']):>6s} {'Y' if r['lead1_1s'] else '.':>2s} {_f(r['lead1_age']):>5s} {_f(r['lead1_vmin']):>6s} {r['life']:5.1f} " +
            f"{_f(r.get('truth')):>5s} {_f(r.get('cam')):>5s} {_f(r.get('ego_dv')):>5s} {r.get('anchor', '')}")

  born_long = [r for r in low if r["life"] >= MIN_LIFE_S]
  _group_stats(out, "BORN ON LOW RAIL", born_long)
  _group_stats(out, "  ...and leadOne within 1 s", [r for r in born_long if r["lead1_1s"]])
  _group_stats(out, f"  ...and leadOne within {LEAD_WINDOW_S:.0f} s", [r for r in born_long if r["lead1_age"] is not None])
  _group_stats(out, f"PUBLISHED RAIL_FAST (leadOne vRel <= {RADARD_RAIL_FAST_BOUND} within {LEAD_WINDOW_S:.0f} s of birth)",
               [r for r in tracks if r["pub_rail_fast"] and r["life"] >= MIN_LIFE_S])
  _group_stats(out, "  ...and |y| < 2 m at birth (in or near ego lane)", [r for r in born_long if abs(r["y"]) < 2.0])
  moving = [r for r in born_long if (r.get("v_ego") or 0.0) >= STATIONARY_MIN_VEGO]
  _group_stats(out, f"  ...and ego >= {STATIONARY_MIN_VEGO:.0f} m/s at birth", moving)
  _group_stats(out, f"  ...and ego >= {STATIONARY_MIN_VEGO:.0f} m/s and |y| < 2 m at birth", [r for r in moving if abs(r["y"]) < 2.0])
  _group_stats(out, "BORN ON HIGH RAIL (truth sign: closing; expect negative)", [r for r in high if r["life"] >= MIN_LIFE_S])
  later = [r for r in tracks if not r["born_low"] and not r["born_high"] and r.get("later_low_t") is not None
           and r["life"] >= MIN_LIFE_S]
  _group_stats(out, "CONTRAST: not born railed, reach the low rail later (truth at first railed sweep)", later)

  spin = [r for r in moving if r.get("truth") is not None and r["truth"] < OVERSTATED_TRUTH_MAX]
  out.append(f"\nTime-course of U11 for born-low-railed tracks, ego >= {STATIONARY_MIN_VEGO:.0f} m/s, truth < {OVERSTATED_TRUTH_MAX:.0f} (n={len(spin)}):")
  for a in TIMECOURSE_AGES:
    us = [r["u_at"][a] for r in spin if r["u_at"][a] is not None]
    ex = [u - (-r["truth"]) for r in spin if (u := r["u_at"][a]) is not None]
    if us:
      out.append(f"  age {a:4.2f} s: median U11 {statistics.median(us):6.2f}  (n={len(us)}, " +
                 f"railed {sum(u <= -U11_RAIL + RAIL_TOL_MPS for u in us)}/{len(us)}, " +
                 f"median excess U11+truth {statistics.median(ex):5.2f})")
  gen = [r for r in moving if r.get("truth") is not None and r["truth"] >= GENUINE_TRUTH_MIN]
  out.append(f"Time-course for born-low-railed tracks, ego >= {STATIONARY_MIN_VEGO:.0f} m/s, truth >= {GENUINE_TRUTH_MIN:.0f} (n={len(gen)}):")
  for a in TIMECOURSE_AGES:
    us = [r["u_at"][a] for r in gen if r["u_at"][a] is not None]
    if us:
      out.append(f"  age {a:4.2f} s: median U11 {statistics.median(us):6.2f}  (n={len(us)})")

  out.append("\nPER-TRACK: born on the low rail or published RAIL_FAST, living >= 3 s")
  out.append(hdr)
  for r in sorted((r for r in tracks if (r["born_low"] or r["pub_rail_fast"]) and r["life"] >= MIN_LIFE_S),
                  key=lambda r: (r["route"], r["t"])):
    out.append(row(r))
  out.append("\nPER-TRACK: born on the high rail, living >= 3 s")
  out.append(hdr)
  for r in sorted((r for r in high if r["life"] >= MIN_LIFE_S), key=lambda r: (r["route"], r["t"])):
    out.append(row(r))
  out.append("\nPER-TRACK CONTRAST: reach the low rail later (t = first railed sweep; d,y at birth)")
  out.append(hdr)
  for r in sorted(later, key=lambda r: (r["route"], r["t_rail"])):
    out.append(row(r, "t_rail"))
  out.append("\nColumns: t route time at birth; U11min = min U11 over first 0.5 s; L1 = leadOne within 1 s; " +
             "L1age = age at first leadOne (within 3 s); L1vmin = min published leadOne vRel in the first 3 s; " +
             "truth = independent closing at t (positive = closing); " +
             "cam = bank range-rate/0.8 at age 0.5-1.5 s (camera, secondary); egodv = ego speed change birth->settle window.")
  return "\n".join(out)


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("routes", nargs="+", help="route directories (numbered segment subdirs holding rlogs)")
  ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
  args = ap.parse_args()

  jobs = []
  for rd in args.routes:
    files = _route_files(rd)
    if not files:
      print(f"  !! no rlogs under {rd}", file=sys.stderr)
    jobs += [(rd, p) for _n, p in files]
  if not jobs:
    raise SystemExit("No segments found")

  by_route: dict[str, list[dict]] = defaultdict(list)
  with Pool(args.jobs) as pool:
    for rd, res in zip([j[0] for j in jobs], pool.imap(_safe_read, [j[1] for j in jobs]), strict=True):
      if res is not None:
        by_route[rd].append(res)

  tracks = []
  for rd in args.routes:
    if by_route.get(rd):
      tracks += analyse_route(rd, by_route[rd])
  print(render(tracks))
  return 0


def _safe_read(path: str) -> dict | None:
  try:
    return read_segment(path)
  except Exception as e:  # one unreadable segment must not lose the route
    print(f"  !! {path}: {type(e).__name__}: {e}", file=sys.stderr)
    return None


if __name__ == "__main__":
  raise SystemExit(main())
