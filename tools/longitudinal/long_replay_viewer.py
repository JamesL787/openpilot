#!/usr/bin/env python3
"""Scrubbable replay of one longitudinal event: the logged drive and alpha_closed_loop_replay's variants in one view.

Input is a frames JSON written by `alpha_closed_loop_replay.py --frames-json` (or Bob's mvlsim.py harness around
it), plus the route's rlogs, which are read again for everything the frames do not carry: the model path and lane
lines, the model leads, the logged liveTracks and the logged radarState. Output:

  --html OUT.html  one self-contained page: a bird's-eye view of radar tracks, leadOne/leadTwo, the model path and
                   the model lead; synced strips (speed, accel, dRel, vRel, lead source, model prob); a scrubber;
                   per-event metrics. Open it in any browser; it needs no network.
  --mp4 OUT.mp4    the same bird's-eye view plus four strips, rendered with PIL and ffmpeg, for sharing.

What the colours mean is printed in the page legend. Two worlds are shown and they are not the same:

  * "log" is what ran on the car: the rlog's liveTracks and radarState.
  * "replay" is this tree's RadarInterface + radard re-run on the logged CAN (the frames' `viz` field). Frames
    written before `viz` existed fall back to the logged tracks, and the page says so.

Sim variants (the frames' `sim` field, inside --sim-window only) drive their own car. gap_shift is how far that car
has fallen behind the logged one, so its gap to the lead is replay dRel + gap_shift. The camera and radar world is the
logged car's, so once |gap_shift| exceeds DRIFT_M the variant no longer sees what its own car would have seen. From
that tick the variant is drawn grey and its metrics stop there ("cut at drift").

Every number here is replay, never road evidence. See STATUS.md for what the sim model leaves out (SIM_DELAY,
first-order actuator, residual from the logged car).

  tools/longitudinal/long_replay_viewer.py /tmp/rv/sim/vis_294_559.json --html /tmp/lrv/294_559.html --mp4 /tmp/lrv/294_559.mp4
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from openpilot.tools.lib.logreader import LogReader
from openpilot.tools.longitudinal.alpha_open_loop_replay import segment_files

DRIFT_M = 10.0            # |gap_shift| past which the logged world no longer matches the sim car (Bob, 2026-09-29)
ONPATH_HALF_M = 1.8       # a track is on-path when within this of the model path at its range
ONPATH_MAX_D = 150.0
VIS_PROB = 0.5            # model lead counts as present above this
RADAR_TO_CAMERA = 1.52    # radard.py: leadsV3 x is from the camera, radar dRel from the radar
BRAKE_ONSET = -1.0        # m/s^2: "brake onset" for a_target and aEgo
JERK_WINDOW_S = 0.2       # felt jerk = d(aEgo) over this window
PAD_BEFORE_S, PAD_AFTER_S = 8.0, 6.0

DRIVE = "drive"           # the logged car itself: carState v/a and the logged ACC command


def fnum(x, nd=2):
  if x is None:
    return None
  x = float(x)
  return round(x, nd) if math.isfinite(x) else None


def arr(xs) -> np.ndarray:
  return np.array([np.nan if x is None else float(x) for x in xs], dtype=float)


# ---------------------------------------------------------------------------------------------- rlog

def _lead_rec(ld):
  if not ld.status:
    return None
  return [fnum(ld.dRel), fnum(ld.yRel), fnum(ld.vRel), fnum(getattr(ld, "vRelRangeDerived", float("nan"))),
          int(ld.radarTrackId), int(bool(ld.radar)), fnum(ld.modelProb, 3)]


def _xy(line, max_x=200.0, step=2):
  xs, ys = list(line.x), list(line.y)
  out_x, out_l = [], []
  for k in range(0, len(xs), step):
    if xs[k] > max_x:
      break
    out_x.append(round(float(xs[k]), 1))
    out_l.append(round(-float(ys[k]), 2))  # model y is +right; the view uses radar yRel, +left
  return [out_x, out_l]


def read_rlog(files: list[Path]) -> tuple[list[dict], dict]:
  """One snapshot per modelV2, keyed by logMonoTime, with the latest of every other service."""
  snaps, first_init = [], None
  tracks, rs, lp_a, cs = [], None, None, None
  for path in files:
    for msg in LogReader(str(path), sort_by_time=True):
      w = msg.which()
      if w == "initData":
        if first_init is None:
          first_init = msg.logMonoTime
      elif w == "liveTracks":
        tracks = [[int(p.trackId), fnum(p.dRel), fnum(p.yRel), fnum(p.vRel), int(bool(p.measured))] for p in msg.liveTracks.points]
      elif w == "radarState":
        rs = (_lead_rec(msg.radarState.leadOne), _lead_rec(msg.radarState.leadTwo))
      elif w == "longitudinalPlan":
        lp_a = fnum(msg.longitudinalPlan.aTarget)
      elif w == "carState":
        cs = (float(msg.carState.vEgo), float(msg.carState.aEgo))
      elif w == "modelV2":
        md = msg.modelV2
        leads = []
        for ld in list(md.leadsV3)[:2]:
          if len(ld.x) and len(ld.v):
            leads.append([fnum(ld.x[0] - RADAR_TO_CAMERA), fnum(-ld.y[0]), fnum(ld.v[0]), fnum(ld.prob, 3)])
          else:
            leads.append(None)
        lanes = [_xy(md.laneLines[k]) for k in (1, 2)] if len(md.laneLines) >= 3 else [None, None]
        snaps.append({"mono": msg.logMonoTime, "path": _xy(md.position, step=1), "lanes": lanes,
                      "lprob": [fnum(p, 2) for p in list(md.laneLineProbs)[1:3]], "leads": leads,
                      "tracks": tracks, "rs": rs, "lp_a": lp_a, "cs": cs})
  return snaps, {"first_init": first_init}


def route_zero_init(route_dir: Path, segments: list[int]) -> int | None:
  """initData of segment 0 of the real route, for frames whose t is route-relative (mvlsim.py shifts t0)."""
  if not segments:
    return None
  real = (route_dir / str(segments[0])).resolve().parent
  seg0 = segment_files(real)[:1]
  if not seg0 or not seg0[0].parent.name == "0":
    return None
  for msg in LogReader(str(seg0[0])):
    if msg.which() == "initData":
      return msg.logMonoTime
  return None


def pick_t0(frames: list[dict], snaps: list[dict], candidates: list[int]) -> int:
  """The candidate t0 whose carState vEgo best matches the frames' v_ego."""
  monos = np.array([s["mono"] for s in snaps], dtype=np.int64)
  vs = np.array([s["cs"][0] if s["cs"] else np.nan for s in snaps])
  sample = frames[:: max(1, len(frames) // 80)]
  best, best_err = candidates[0], float("inf")
  for c in candidates:
    errs = []
    for f in sample:
      k = int(np.searchsorted(monos, c + int(f["t"] * 1e9)))
      if 0 <= k < len(monos) and abs(int(monos[k]) - (c + f["t"] * 1e9)) < 0.1e9:
        errs.append(abs(vs[k] - f["v_ego"]))
    err = float(np.nanmean(errs)) if len(errs) > len(sample) // 2 else float("inf")
    if err < best_err:
      best, best_err = c, err
  if not math.isfinite(best_err) or best_err > 0.3:
    raise SystemExit(f"cannot align frames to the rlog (best vEgo error {best_err:.2f} m/s); pass --route-dir")
  return best


# ---------------------------------------------------------------------------------------------- build

def build(frames_path: Path, route_dir: Path | None, window: tuple[float, float] | None, event_t: float | None = None) -> dict:
  blob = json.loads(frames_path.read_text())
  meta, frames = blob["meta"], blob["frames"]
  rdir = route_dir or Path(meta["route_dir"])
  files = segment_files(rdir)
  if not files:
    raise SystemExit(f"no rlogs under {rdir}")
  print(f"reading {len(files)} rlog segment(s) under {rdir} ...", file=sys.stderr)
  snaps, info = read_rlog(files)
  if "t0_mono" in meta:
    t0 = int(meta["t0_mono"])
  else:
    cands = [info["first_init"]]
    z = route_zero_init(rdir, meta.get("segments", []))
    if z is not None:
      cands.append(z)
    t0 = pick_t0(frames, snaps, cands)

  if window is None:
    sw = meta.get("sim_window")
    if sw:
      window = (sw[0] - PAD_BEFORE_S, sw[1] + PAD_AFTER_S)
    else:
      window = (frames[0]["t"], frames[-1]["t"])
  sel = [f for f in frames if window[0] <= f["t"] <= window[1]]
  if len(sel) < 10:
    raise SystemExit(f"window {window} holds {len(sel)} frames; frames span {frames[0]['t']:.1f}..{frames[-1]['t']:.1f}")

  monos = np.array([s["mono"] for s in snaps], dtype=np.int64)
  variants = [v for v in meta["variants"] if v in sel[0]["out"]] + \
             [v for v in sel[0]["out"] if v not in meta["variants"]]
  sim_variants = [v for v in variants if any(v in f["sim"] for f in sel)]
  has_viz = "viz" in sel[0]

  D: dict = {"t": [], "eng": [], "brk": [], "v": [], "a": [], "acmd": [], "lp_a": [],
             "out": {v: [] for v in variants}, "src": {v: [] for v in variants},
             "simv": {v: [] for v in sim_variants}, "sima": {v: [] for v in sim_variants},
             "gs": {v: [] for v in sim_variants},
             "L1log": [], "L2log": [], "L1rep": [], "L2rep": [], "vis": [], "vis2": [],
             "path": [], "lanes": [], "lprob": [], "tr": [], "trlog": []}
  for f in sel:
    k = int(np.searchsorted(monos, t0 + int(f["t"] * 1e9)))
    k = min(max(k, 0), len(snaps) - 1)
    if k > 0 and abs(monos[k - 1] - (t0 + f["t"] * 1e9)) < abs(monos[k] - (t0 + f["t"] * 1e9)):
      k -= 1
    s = snaps[k]
    D["t"].append(round(f["t"], 3))
    D["eng"].append(int(bool(f["engaged"])))
    D["brk"].append(int(bool(f["brake"])))
    D["v"].append(fnum(f["v_ego"], 3))
    D["a"].append(fnum(f["a_ego"], 3))
    D["acmd"].append(fnum(f["accel_cmd"], 3))
    D["lp_a"].append(s["lp_a"])
    for v in variants:
      D["out"][v].append(fnum(f["out"].get(v), 3))
      D["src"][v].append(f["src"].get(v))
    for v in sim_variants:
      sv = f["sim"].get(v)
      D["simv"][v].append(sv[0] if sv else None)
      D["sima"][v].append(sv[1] if sv else None)
      D["gs"][v].append(sv[2] if sv else None)
    rs = s["rs"] or (None, None)
    D["L1log"].append(rs[0])
    D["L2log"].append(rs[1])
    if has_viz:
      D["L1rep"].append(f["viz"]["l1"])
      D["L2rep"].append(f["viz"]["l2"])
      D["tr"].append([[t[0], t[1], t[2], t[3], t[5]] for t in f["viz"]["tr"]])
      D["trlog"].append(s["tracks"])
    else:
      ld = f["lead"]
      D["L1rep"].append([fnum(ld["d"]), fnum(ld["y"]), fnum(ld["vRel"]), None, None, ld["track"], int(ld["radar"]), None]
                        if ld.get("status") else None)
      D["L2rep"].append(None)
      D["tr"].append(s["tracks"])
    D["vis"].append(s["leads"][0] if s["leads"] else None)
    D["vis2"].append(s["leads"][1] if len(s["leads"]) > 1 else None)
    D["path"].append(s["path"])
    D["lanes"].append(s["lanes"])
    D["lprob"].append(s["lprob"])

  # native vRel of the lead: replay has it in viz; log takes the raw liveTracks point with the same id
  for i, L in enumerate(D["L1log"]):
    if L is not None and L[5]:
      pt = next((p for p in (D["trlog"][i] if has_viz else D["tr"][i]) if p[0] == L[4]), None)
      D["L1log"][i] = L + [pt[3] if pt else None]
    elif L is not None:
      D["L1log"][i] = L + [None]
  D["onpath"] = [onpath_ids(D["tr"][i], D["path"][i]) for i in range(len(D["t"]))]
  if has_viz:
    D["onpath_log"] = [onpath_ids(D["trlog"][i], D["path"][i]) for i in range(len(D["t"]))]

  drift = {}
  for v in sim_variants:
    for t, g in zip(D["t"], D["gs"][v], strict=True):
      if g is not None and abs(g) > DRIFT_M:
        drift[v] = t
        break
  D["meta"] = {"frames": str(frames_path), "route_dir": str(rdir), "window": [round(window[0], 2), round(window[1], 2)],
               "sim_window": meta.get("sim_window"), "variants": variants, "sim_variants": sim_variants,
               "drift": drift, "drift_m": DRIFT_M, "has_viz": has_viz, "git_commit": meta.get("git_commit"),
               "fingerprint": meta.get("fingerprint"), "blotv3": meta.get("blotv3"),
               "logged_op_long": meta.get("logged_op_long"), "agreement": meta.get("agreement"),
               "onpath_half_m": ONPATH_HALF_M, "vis_prob": VIS_PROB, "event_t": event_t}
  D["metrics"], D["events"] = metrics(D)
  return D


def onpath_ids(tracks, path) -> list[int]:
  if not path or not path[0]:
    return []
  px, pl = path
  out = []
  for tid, d, y, _vr, meas in tracks:
    # past the end of the model path, hold its last lateral offset: while braking the path is short
    # (00000297 31:06: stopped car at 31 m, path ended at 30 m, so it dropped off-path 0.3 s before adoption)
    if d is None or y is None or not meas or d > ONPATH_MAX_D:
      continue
    if abs(y - float(np.interp(d, px, pl))) < ONPATH_HALF_M:
      out.append(tid)
  return out


# ---------------------------------------------------------------------------------------------- metrics

def _col(recs, k):
  return arr([r[k] if r is not None and len(r) > k else None for r in recs])


ONPATH_GAP_S = 0.5  # an on-path run survives off-path flickers this short (path jitter, one missed measurement)


def adoption_lags(t, lead_recs, onpath, track_idx=5):
  """For each radar track that becomes leadOne: how long it sat on-path (measured) first."""
  out, seen = [], set()
  for i, L in enumerate(lead_recs):
    if L is None or not L[6 if track_idx == 5 else 5]:
      continue
    tid = L[track_idx]
    if tid in seen:
      continue
    seen.add(tid)
    j = k = i
    while k > 0 and (tid in onpath[k - 1] or t[j] - t[k - 1] <= ONPATH_GAP_S):
      k -= 1
      if tid in onpath[k]:
        j = k
    out.append({"track": int(tid), "onpath_t": t[j], "adopt_t": t[i], "lag_s": round(t[i] - t[j], 2),
                "d_at_onpath": None, "since_window_start": j == 0})
  return out


SUSTAIN_S = 0.3


def sustained_max(t, x) -> float | None:
  """Largest value x stayed at or above for SUSTAIN_S (a gap in x ends the run)."""
  best = None
  for i in range(len(t)):
    if not np.isfinite(x[i]):
      continue
    lo, j = x[i], i
    while j + 1 < len(t) and np.isfinite(x[j + 1]) and t[j + 1] - t[i] <= SUSTAIN_S:
      j += 1
      lo = min(lo, x[j])
    if t[j] - t[i] >= SUSTAIN_S - 0.06 and (best is None or lo > best):
      best = lo
  return fnum(best) if best is not None else None


def longest_run(t, mask) -> tuple[float, float | None]:
  best, best_t, start = 0.0, None, None
  for i, m in enumerate(mask):
    if m and start is None:
      start = i
    if (not m or i == len(mask) - 1) and start is not None:
      end = i if m else i - 1
      dur = t[end] - t[start]
      if dur > best:
        best, best_t = dur, t[start]
      start = None
  return round(best, 2), best_t


def first_below(t, x, thr, t_from, t_to=None):
  for ti, xi in zip(t, x, strict=True):
    if ti >= t_from and (t_to is None or ti <= t_to) and np.isfinite(xi) and xi < thr:
      return ti
  return None


def felt_jerk(t, a):
  t = np.asarray(t)
  ok = np.isfinite(a)
  if ok.sum() < 5:
    return None, None
  a_shift = np.interp(t + JERK_WINDOW_S, t[ok], a[ok], right=np.nan)
  j = (a_shift - a) / JERK_WINDOW_S
  j = j[np.isfinite(j) & (t + JERK_WINDOW_S <= t[ok][-1])]
  if not len(j):
    return None, None
  return fnum(np.sqrt(np.mean(j ** 2))), fnum(np.max(np.abs(j)))


def metrics(D) -> tuple[dict, list[dict]]:
  t = np.array(D["t"])
  v_log, a_log = arr(D["v"]), arr(D["a"])
  L1 = D["L1rep"]
  d1, vr1, vn1, vrr1 = _col(L1, 0), _col(L1, 2), _col(L1, 3), _col(L1, 4)
  radar1 = _col(L1, 6)
  v_lead = v_log + vr1
  vis_d, vis_p = _col(D["vis"], 0), _col(D["vis"], 3)
  events = []

  lags = adoption_lags(D["t"], L1, D["onpath"])
  for g in lags:
    i = D["t"].index(g["onpath_t"])
    tr = next((p for p in D["tr"][i] if p[0] == g["track"]), None)
    g["d_at_onpath"] = tr[1] if tr else None
    if not D["meta"]["has_viz"]:
      # no replay tracks in this JSON: logged liveTracks carry the device's ids, so an on-path run
      # cannot be matched to the replay lead's id. Report the adoption, not a lag.
      g["lag_s"], g["d_at_onpath"] = None, L1[D["t"].index(g["adopt_t"])][0]
    events.append({"t": g["onpath_t"], "kind": "onpath", "label": f"track {g['track']} on-path"})
    events.append({"t": g["adopt_t"], "kind": "adopt", "label": f"track {g['track']} adopted" + (f" (lag {g['lag_s']} s)" if g["lag_s"] is not None else "")})
  t_ev = D["meta"].get("event_t")
  if t_ev is None:
    t_ev = min((g["onpath_t"] for g in lags if not g["since_window_start"]), default=float(t[0]))
  sw = D["meta"]["sim_window"]
  in_scope = (t >= sw[0]) & (t <= sw[1]) if sw else np.ones_like(t, dtype=bool)

  common = {
    "lead_event_t": t_ev,
    "adoption": lags,
    "max_adoption_lag_s": max((g["lag_s"] for g in lags if g["lag_s"] is not None), default=None),
    "max_extra_closing_vrel": fnum(np.nanmax(vn1 - vr1)) if np.isfinite(vn1 - vr1).any() else None,
    "max_native_minus_rangederived_vrel": fnum(np.nanmax(np.abs(vn1 - vrr1))) if np.isfinite(vn1 - vrr1).any() else None,
    "lead_dropout_s": longest_run(D["t"], [bool(p > VIS_PROB) and not (r == 1) for p, r in zip(vis_p, radar1, strict=True)])[0],
    "radar_vs_vision_d_err_median": None, "radar_vs_vision_d_err_max": None,
  }
  both = (radar1 == 1) & (vis_p > VIS_PROB) & np.isfinite(d1) & np.isfinite(vis_d)
  if both.any():
    err = np.abs(d1[both] - vis_d[both])
    common["radar_vs_vision_d_err_median"] = fnum(np.median(err))
    common["radar_vs_vision_d_err_max"] = fnum(np.max(err))
  if "onpath_log" in D:
    common["adoption_log"] = adoption_lags(D["t"], D["L1log"], D["onpath_log"], track_idx=4)
    for g in common["adoption_log"]:
      i = D["t"].index(g["onpath_t"])
      tr = next((p for p in D["trlog"][i] if p[0] == g["track"]), None)
      g["d_at_onpath"] = tr[1] if tr else None
  L1l = D["L1log"]
  vpl, vnl = _col(L1l, 2), _col(L1l, 7)
  common["max_extra_closing_vrel_log"] = fnum(np.nanmax(vnl - vpl)) if np.isfinite(vnl - vpl).any() else None
  # the raw max catches one-tick spikes (00000297 17:50: 3.6 m/s for one 50 ms frame at low speed);
  # the sustained figure is the largest extra closing that held for SUSTAIN_S
  common["max_extra_closing_vrel_sustained"] = sustained_max(t, vn1 - vr1)
  common["max_extra_closing_vrel_log_sustained"] = sustained_max(t, vnl - vpl)
  # logged radar lead speed (published, and native Doppler) vs the camera's, when both see the same car
  dl, rl, vis_v = _col(L1l, 0), _col(L1l, 5), _col(D["vis"], 2)
  same = (rl == 1) & (vis_p > VIS_PROB) & (np.abs(dl - vis_d) < np.maximum(10.0, 0.2 * dl))
  for k, vr in (("radar_vs_vision_vlead_err_max_log", vpl), ("native_vs_vision_vlead_err_max_log", vnl)):
    e = np.where(same, v_log + vr - vis_v, np.nan)
    common[k] = fnum(e[np.nanargmax(np.abs(e))]) if np.isfinite(e).any() else None

  per: dict = {}
  cars = [(DRIVE, v_log, a_log, arr(D["acmd"]), np.zeros_like(t), None)]
  for v in D["meta"]["sim_variants"]:
    cars.append((v, arr(D["simv"][v]), arr(D["sima"][v]), arr(D["out"][v]), arr(D["gs"][v]), D["meta"]["drift"].get(v)))
  for name, vv, aa, cmd, gs, t_drift in cars:
    live = in_scope & (np.isfinite(vv) if name != DRIVE else True)
    if t_drift is not None:
      live &= t < t_drift
    if not live.any():
      continue
    gap = d1 + gs
    closing = vv - v_lead
    ttc = np.where(live & (closing > 0.3) & np.isfinite(gap), gap / np.maximum(closing, 0.3), np.nan)
    tl = t[live]
    rms, jmax = felt_jerk(tl, aa[live])
    cj = np.diff(cmd[live]) / np.maximum(np.diff(tl), 1e-3) if live.sum() > 2 else np.array([])
    cj = cj[np.isfinite(cj)]
    onset_cmd = first_below(tl, cmd[live], BRAKE_ONSET, tl[0])
    onset_a = first_below(tl, aa[live], BRAKE_ONSET, tl[0])
    per[name] = {
      "t_from": fnum(tl[0]), "t_to": fnum(tl[-1]), "cut_at_drift": t_drift,
      "min_gap_m": fnum(np.nanmin(np.where(live, gap, np.nan))) if np.isfinite(gap[live]).any() else None,
      "min_ttc_s": fnum(np.nanmin(ttc)) if np.isfinite(ttc).any() else None,
      "max_decel": fnum(np.nanmin(aa[live])),
      "felt_jerk_rms": rms, "felt_jerk_max": jmax,
      "max_cmd_jerk": fnum(np.max(np.abs(cj))) if len(cj) else None,
      "cmd_brake_onset_t": onset_cmd, "a_brake_onset_t": onset_a,
      "cmd_onset_lag_s": fnum(onset_cmd - t_ev) if onset_cmd is not None else None,
      "a_onset_lag_s": fnum(onset_a - t_ev) if onset_a is not None else None,
      "cmd_to_a_lag_s": fnum(onset_a - onset_cmd) if onset_a is not None and onset_cmd is not None else None,
    }
    if onset_cmd is not None:
      events.append({"t": onset_cmd, "kind": "onset", "label": f"{name} command < {BRAKE_ONSET:g}"})
  for v in D["meta"]["variants"]:
    if v in per:
      continue
    cmd = arr(D["out"][v])
    onset = first_below(t[in_scope], cmd[in_scope], BRAKE_ONSET, -1e9)
    cj = np.diff(cmd) / np.maximum(np.diff(t), 1e-3)
    cj = cj[np.isfinite(cj)]
    per[v] = {"open_loop": True, "min_cmd": fnum(np.nanmin(cmd)), "max_cmd_jerk": fnum(np.max(np.abs(cj))) if len(cj) else None,
              "cmd_brake_onset_t": onset, "cmd_onset_lag_s": fnum(onset - t_ev) if onset is not None else None}
  for v, td in D["meta"]["drift"].items():
    events.append({"t": td, "kind": "drift", "label": f"{v} drift > {DRIFT_M:g} m"})
  events.sort(key=lambda e: e["t"])
  return {"common": common, "per": per}, events


# ---------------------------------------------------------------------------------------------- html

def write_html(D: dict, out: Path) -> None:
  tpl = (Path(__file__).parent / "long_replay_viewer.html").read_text()
  out.write_text(tpl.replace("/*__DATA__*/null", json.dumps(D, separators=(",", ":"), allow_nan=False)))


# ---------------------------------------------------------------------------------------------- mp4

COLORS = {DRIVE: (235, 235, 235), "b0.075": (61, 220, 132), "mvl": (255, 159, 28), "mvlvis": (199, 125, 255),
          "mvl50": (255, 214, 10), "nobound": (76, 201, 240), "logged": (141, 153, 174)}
EXTRA = [(239, 71, 111), (6, 214, 160), (17, 138, 178), (255, 209, 102)]


def vcolor(v, k=0):
  return COLORS.get(v, EXTRA[k % len(EXTRA)])


def write_mp4(D: dict, out: Path, fps: float, bev_range: float, show: list[str] | None) -> None:
  from PIL import Image, ImageDraw, ImageFont
  try:
    font = ImageFont.load_default(size=14)
    small = ImageFont.load_default(size=11)
  except TypeError:
    font = small = ImageFont.load_default()
  W, H, BW = 1280, 720, 420
  t = np.array(D["t"])
  t_play = np.arange(t[0], t[-1], 1.0 / fps)
  idx = np.clip(np.searchsorted(t, t_play), 0, len(t) - 1)
  sims = [v for v in D["meta"]["sim_variants"] if (v in show if show else v not in ("nobound", "logged"))]
  D["meta"]["mp4_sims"] = sims
  drift = D["meta"]["drift"]

  def series_accel():
    s = [("acmd", arr(D["acmd"]), vcolor(DRIVE), None), ("aEgo", arr(D["a"]), (150, 150, 150), None)]
    for k, v in enumerate(sims or D["meta"]["variants"][:1]):
      s.append((f"{v} cmd", arr(D["out"][v]), vcolor(v, k), drift.get(v)))
      if v in D["sima"]:
        s.append((f"{v} a", arr(D["sima"][v]), tuple(c // 2 for c in vcolor(v, k)), drift.get(v)))
    return s

  d1 = _col(D["L1rep"], 0)
  strips = [
    ("speed m/s", [("drive", arr(D["v"]), vcolor(DRIVE), None)] +
     [(v, arr(D["simv"][v]), vcolor(v, k), drift.get(v)) for k, v in enumerate(sims)]),
    ("accel m/s^2", series_accel()),
    ("dRel / gap m", [("vision", _col(D["vis"], 0), (72, 149, 239), None), ("L1 log", _col(D["L1log"], 0), (120, 60, 60), None),
                      ("L1 replay", d1, (230, 57, 70), None)] +
     [(f"{v} gap", d1 + arr(D["gs"][v]), vcolor(v, k), drift.get(v)) for k, v in enumerate(sims)]),
    ("vRel m/s", [("vision", _col(D["vis"], 2) - arr(D["v"]), (72, 149, 239), None),
                  ("range-derived", _col(D["L1rep"], 4), (76, 201, 240), None),
                  ("native", _col(D["L1rep"], 3), (255, 159, 28), None), ("published", _col(D["L1rep"], 2), (230, 57, 70), None)]),
  ]
  SX0, SW = BW + 60, W - BW - 80
  SH = (H - 40) // len(strips)

  def sx(ti):
    return SX0 + (ti - t[0]) / (t[-1] - t[0]) * SW

  base = Image.new("RGB", (W, H), (18, 18, 22))
  g = ImageDraw.Draw(base)
  for si, (title, series) in enumerate(strips):
    y0 = 20 + si * SH
    y1 = y0 + SH - 18
    vals = np.concatenate([s[1][np.isfinite(s[1])] for s in series] + [np.array([0.0])])
    lo, hi = np.percentile(vals, 1), np.percentile(vals, 99)
    if hi - lo < 1:
      lo, hi = lo - 0.5, hi + 0.5
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad

    def sy(x, y0=y0, y1=y1, lo=lo, hi=hi):
      return y1 - (x - lo) / (hi - lo) * (y1 - y0)
    g.rectangle([SX0, y0, SX0 + SW, y1], outline=(60, 60, 70))
    g.text((SX0 - 55, y0), title.split()[0], fill=(200, 200, 200), font=small)
    for tick in (lo + pad, (lo + hi) / 2, hi - pad):
      g.text((SX0 - 40, sy(tick) - 6), f"{tick:.1f}", fill=(130, 130, 130), font=small)
    if lo < 0 < hi:
      g.line([SX0, sy(0), SX0 + SW, sy(0)], fill=(70, 70, 80))
    for i in range(len(t) - 1):
      if not D["eng"][i]:
        g.rectangle([sx(t[i]), y0 + 1, sx(t[i + 1]), y0 + 4], fill=(120, 40, 40))
    lx = SX0 + 4
    for name, x, colr, td in series:
      pts = []
      for ti, xi in zip(t, x, strict=True):
        if not np.isfinite(xi):
          if len(pts) > 1:
            g.line(pts, fill=colr, width=2)
          pts = []
          continue
        c = colr if td is None or ti < td else (90, 90, 90)
        pts.append((sx(ti), sy(xi)))
        if td is not None and ti >= td and len(pts) > 1:
          g.line(pts[-2:], fill=c, width=1)
          pts = pts[-1:]
      if len(pts) > 1:
        g.line(pts, fill=colr, width=2)
      g.text((lx, y1 + 2), name, fill=colr, font=small)
      lx += 8 + g.textlength(name, font=small)
    for td in drift.values():
      g.line([sx(td), y0, sx(td), y1], fill=(110, 110, 110), width=1)
  for e in D["events"]:
    if e["kind"] in ("adopt", "onpath"):
      g.line([sx(e["t"]), 20, sx(e["t"]), H - 20], fill=(90, 70, 20) if e["kind"] == "onpath" else (140, 110, 20))

  proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out)],
                          stdin=subprocess.PIPE)
  for tp, i in zip(t_play, idx, strict=True):
    img = base.copy()
    g = ImageDraw.Draw(img)
    g.line([sx(tp), 20, sx(tp), H - 20], fill=(255, 255, 255), width=1)
    draw_bev(g, D, int(i), BW, H, bev_range, font, small)
    proc.stdin.write(img.tobytes())
  proc.stdin.close()
  proc.wait()


def draw_bev(g, D, i, BW, H, rng, font, small) -> None:
  ox, oy, lat = BW / 2, H - 50, 16.0
  fs = (H - 90) / rng

  def P(d, l):
    return ox - l * lat, oy - d * fs
  g.rectangle([0, 0, BW, H], fill=(10, 12, 16))
  step = 10 if rng <= 80 else 20
  for d in range(0, int(rng) + 1, step):
    g.line([P(d, 12), P(d, -12)], fill=(35, 38, 45))
    g.text((4, P(d, 0)[1] - 6), f"{d}", fill=(90, 90, 100), font=small)
  path = D["path"][i]
  if path and path[0]:
    left = [P(x, l + ONPATH_HALF_M) for x, l in zip(*path, strict=True) if x <= rng]
    right = [P(x, l - ONPATH_HALF_M) for x, l in zip(*path, strict=True) if x <= rng]
    if len(left) > 1:
      g.polygon(left + right[::-1], fill=(20, 45, 30))
      g.line([P(x, l) for x, l in zip(*path, strict=True) if x <= rng], fill=(60, 140, 80), width=2)
  for ln in D["lanes"][i] or []:
    if ln and len(ln[0]) > 1:
      g.line([P(x, l) for x, l in zip(*ln, strict=True) if x <= rng], fill=(170, 150, 60), width=1)
  onp = set(D["onpath"][i])
  for tid, d, y, vr, meas in D["tr"][i]:
    if d is None or d > rng:
      continue
    x, yy = P(d, y)
    c = (255, 214, 10) if tid in onp else (140, 140, 150)
    r = 4
    if meas:
      g.ellipse([x - r, yy - r, x + r, yy + r], fill=c)
    else:
      g.ellipse([x - r, yy - r, x + r, yy + r], outline=c)
    g.text((x + 6, yy - 6), f"{tid} {vr:+.1f}" if vr is not None else f"{tid}", fill=c, font=small)
  vis = D["vis"][i]
  if vis and vis[0] is not None and vis[3] is not None and vis[3] > 0.2 and vis[0] <= rng:
    x, yy = P(vis[0], vis[1])
    c = (72, 149, 239)
    g.polygon([(x, yy - 8), (x + 8, yy), (x, yy + 8), (x - 8, yy)], outline=c, width=2)
    g.text((x - 70, yy - 6), f"vis p{vis[3]:.2f}", fill=c, font=small)
  for L, c, name in ((D["L1log"][i], (120, 60, 60), "log"), (D["L2rep"][i], (255, 140, 0), "L2"), (D["L1rep"][i], (230, 57, 70), "L1")):
    if L is None or L[0] is None or L[0] > rng:
      continue
    x, yy = P(L[0], L[1])
    w = 0.9 * lat
    g.rectangle([x - w, yy - 10, x + w, yy + 2], outline=c, width=2)
    tid = L[4] if name == "log" else L[5]
    radar = L[5] if name == "log" else L[6]
    label = f"{name} #{tid}" if radar else f"{name} vision"
    g.text((x + w + 3, yy - 20 if name == "log" else yy + 2), label, fill=c, font=small)
  # ego and sim ghosts
  g.rectangle([ox - 0.9 * lat, oy, ox + 0.9 * lat, oy + 4.5 * fs + 6], fill=(235, 235, 235))
  k = 0
  for v in D["meta"].get("mp4_sims", D["meta"]["sim_variants"]):
    gs = D["gs"][v][i]
    if gs is None:
      continue
    drifted = abs(gs) > DRIFT_M
    c = (100, 100, 100) if drifted else vcolor(v, k)
    k += 1
    yy = oy + gs * fs
    if yy > H - 16:
      g.text((ox + 20 + 90 * (k - 1) - 80, H - 16), f"{v} {-gs:+.0f} m v", fill=c, font=small)
    else:
      g.rectangle([ox - 0.9 * lat - 2 * k, yy, ox + 0.9 * lat + 2 * k, yy + 4.5 * fs + 6], outline=c, width=2)
      g.text((ox + 0.9 * lat + 2 * k + 3, yy + 2 + 12 * (k - 1)), f"{v} {-gs:+.1f} m", fill=c, font=small)
  t = D["t"][i]
  head = f"t {t:7.2f}s  v {D['v'][i]:.1f}  aEgo {D['a'][i]:+.2f}  {'ENGAGED' if D['eng'][i] else 'not engaged'}"
  g.text((6, 4), head, fill=(230, 230, 230), font=font)
  shown = D["meta"].get("mp4_sims", D["meta"]["sim_variants"])
  row = 0
  for n, v in enumerate(D["meta"]["variants"]):
    if v in D["meta"]["sim_variants"] and v not in shown:
      continue
    o = D["out"][v][i]
    s = f"{v:>8}: cmd {o:+.2f} src {D['src'][v][i]}" if o is not None else f"{v:>8}: -"
    g.text((6, 26 + 15 * row), s, fill=vcolor(v, n), font=small)
    row += 1
  drifted = [v for v in shown if D["gs"][v][i] is not None and abs(D["gs"][v][i]) > DRIFT_M]
  if drifted:
    g.text((6, H - 32), f"DRIFT > {DRIFT_M:g} m: {', '.join(drifted)} (grey; world != sim car)", fill=(200, 200, 200), font=small)


# ---------------------------------------------------------------------------------------------- main

def print_metrics(D: dict) -> None:
  m = D["metrics"]
  c = m["common"]
  print(f"window {D['meta']['window']}  sim {D['meta']['sim_window']}  viz={'replay' if D['meta']['has_viz'] else 'log only'}  (replay)")
  for side, key in (("replay", "adoption"), ("log", "adoption_log")):
    for g in c.get(key, []):
      pre = ">=" if g["since_window_start"] else ""
      lag = f"lag {pre}{g['lag_s']} s" if g["lag_s"] is not None else "lag n/a (JSON has no replay tracks)"
      print(f"  {side:>6} track {g['track']:>3}: on-path {g['onpath_t']:.2f} at {g['d_at_onpath']} m -> leadOne {g['adopt_t']:.2f}  {lag}")
  for k in ("max_extra_closing_vrel", "max_extra_closing_vrel_log", "max_extra_closing_vrel_sustained",
            "max_extra_closing_vrel_log_sustained", "max_native_minus_rangederived_vrel",
            "lead_dropout_s", "radar_vs_vision_d_err_median", "radar_vs_vision_d_err_max",
            "radar_vs_vision_vlead_err_max_log", "native_vs_vision_vlead_err_max_log"):
    print(f"  {k}: {c.get(k)}")
  keys = ["min_gap_m", "min_ttc_s", "max_decel", "felt_jerk_rms", "felt_jerk_max", "max_cmd_jerk", "cmd_onset_lag_s",
          "a_onset_lag_s", "cmd_to_a_lag_s", "cut_at_drift"]
  print(f"  {'':>8} " + " ".join(f"{k[:13]:>13}" for k in keys))
  for v, r in m["per"].items():
    if r.get("open_loop"):
      continue
    print(f"  {v:>8} " + " ".join(f"{str(r.get(k)):>13}" for k in keys))


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("frames_json", type=Path)
  ap.add_argument("--route-dir", type=Path, help="override meta.route_dir")
  ap.add_argument("--window", help="T0,T1 in the frames' seconds (default: sim window -8/+6 s, else all)")
  ap.add_argument("--event-t", type=float, help="lead event time for the onset lags "
                  + "(default: first on-path track that later becomes leadOne, else window start)")
  ap.add_argument("--html", type=Path)
  ap.add_argument("--mp4", type=Path)
  ap.add_argument("--fps", type=float, default=10.0)
  ap.add_argument("--range", type=float, default=100.0, help="bird's-eye forward range for the mp4, m")
  ap.add_argument("--variants", help="comma list of sim variants drawn in the mp4 (default: all but nobound/logged)")
  ap.add_argument("--metrics-json", type=Path)
  args = ap.parse_args()
  window = tuple(float(x) for x in args.window.split(",")) if args.window else None
  D = build(args.frames_json, args.route_dir, window, args.event_t)
  print_metrics(D)
  if args.metrics_json:
    args.metrics_json.write_text(json.dumps({"meta": D["meta"], **D["metrics"], "events": D["events"]}, indent=1))
  if args.html:
    write_html(D, args.html)
    print(f"wrote {args.html}", file=sys.stderr)
  if args.mp4:
    write_mp4(D, args.mp4, args.fps, args.range, args.variants.split(",") if args.variants else None)
    print(f"wrote {args.mp4}", file=sys.stderr)
  return 0


if __name__ == "__main__":
  sys.exit(main())
