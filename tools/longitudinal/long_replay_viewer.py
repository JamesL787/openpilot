#!/usr/bin/env python3
"""Scrubbable replay of one longitudinal event: the logged drive and alpha_closed_loop_replay's variants in one view.

Input is a frames JSON written by `alpha_closed_loop_replay.py --frames-json` (or Bob's mvlsim.py harness around
it), plus the route's rlogs, which are read again for everything the frames do not carry: the model path and lane
lines, the model leads, the logged liveTracks and the logged radarState. Output:

  --html OUT.html  one self-contained page: a bird's-eye view of radar tracks, leadOne/leadTwo, the model path and
                   the model lead; synced strips (speed, accel, dRel, vRel, lead source, model prob); a scrubber;
                   per-event metrics. Open it in any browser; it needs no network.
  --mp4 OUT.mp4    the same bird's-eye view plus four strips, rendered with PIL and ffmpeg, for sharing.

With the route's qcamera.ts files (--qcamera-dir, default the route dir), the page also shows the road camera with
every radar track drawn on it: a 1.8 m x 1.4 m box at the track's range and lateral offset, labelled id and vRel,
plus leadOne/leadTwo and the model path. The projection is the onroad UI's (liveCalibration rpyCalib and height,
the device's road-camera intrinsics scaled to the qcamera size), so a box that sits on the car it names is a
cross-check on the radar, and the path should lie on the road; if it does not, the boxes are misplaced too.

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
import base64
import io
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from openpilot.common.transformations.camera import DEVICE_CAMERAS, view_frame_from_device_frame
from openpilot.common.transformations.orientation import rot_from_euler
from openpilot.tools.lib.logreader import LogReader
from openpilot.tools.longitudinal.alpha_open_loop_replay import segment_files

DRIFT_M = 10.0            # |gap_shift| past which the logged world no longer matches the sim car (Bob, 2026-09-29)
ONPATH_HALF_M = 1.8       # a track is on-path when within this of the model path at its range
ONPATH_MAX_D = 150.0
VIS_PROB = 0.5            # model lead counts as present above this
RADAR_TO_CAMERA = 1.52    # radard.py: leadsV3 x is from the camera, radar dRel from the radar
SEGMENT_S = 60.0          # rlog segment length; window_segments() maps route seconds to segment numbers with it
CAM_JPEG_Q = 70           # qcamera frames embedded in the page; ~15 kB each at 526x330
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
  snaps, first_init, cam = [], None, None
  tracks, rs, lp_a, cs, cal, rs_tracks, cc_a, yaw = [], None, None, None, None, [], None, None
  qframe: dict[int, tuple[int, int]] = {}  # road frameId -> (segment, frame index in that segment's qcamera.ts)
  for path in files:
    for msg in LogReader(str(path), sort_by_time=True):
      w = msg.which()
      if w == "initData":
        if first_init is None:
          first_init = msg.logMonoTime
        cam = [str(msg.initData.deviceType), cam[1] if cam else "unknown"]
      elif w == "roadCameraState":
        if cam is not None and cam[1] == "unknown":
          cam[1] = str(msg.roadCameraState.sensor)
      elif w == "qRoadEncodeIdx":
        e = msg.qRoadEncodeIdx
        qframe[int(e.frameId)] = (int(e.segmentNum), int(e.segmentId))
      elif w == "liveCalibration":
        lc = msg.liveCalibration
        if len(lc.rpyCalib) == 3:
          cal = [float(x) for x in lc.rpyCalib] + [float(lc.height[0]) if len(lc.height) else 1.22]
      elif w == "liveTracks":
        tracks = [[int(p.trackId), fnum(p.dRel), fnum(p.yRel), fnum(p.vRel), int(bool(p.measured))] for p in msg.liveTracks.points]
      elif w == "radarState":
        rs = (_lead_rec(msg.radarState.leadOne), _lead_rec(msg.radarState.leadTwo))
        rs_tracks = tracks  # radard built this radarState from the liveTracks before it, not the next one
      elif w == "longitudinalPlan":
        lp_a = fnum(msg.longitudinalPlan.aTarget)
      elif w == "carControl":
        cc_a = float(msg.carControl.actuators.accel) if msg.carControl.longActive else None
      elif w == "livePose":  # carState.yawRate is 0 on the Clarity
        yaw = float(msg.livePose.angularVelocityDevice.z)
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
                      "tracks": tracks, "rs_tracks": rs_tracks, "rs": rs, "lp_a": lp_a, "cs": cs, "cc_a": cc_a, "yaw": yaw,
                      "cal": cal, "frame_id": int(md.frameId)})
  for sn in snaps:
    sn["q"] = qframe.get(sn["frame_id"])
  return snaps, {"first_init": first_init, "cam": cam}


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


def window_segments(files: list[Path], window: tuple[float, float]) -> list[Path]:
  """The rlogs that cover a window in route seconds, plus the segment before it so the latest tracks,
  radarState and calibration are already known at the window start. Segment k holds route t of about
  60k + 2.7 .. 60k + 62.7 (00000297: segments 1, 30, 53); reading only these takes a 22 s window from
  about 100 s to a few seconds. build() falls back to every segment if the snapshots miss the window."""
  lo, hi = int(window[0] // SEGMENT_S) - 1, int(window[1] // SEGMENT_S)
  return [p for p in files if p.parent.name.isdigit() and lo <= int(p.parent.name) <= hi]


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
  if window is None:
    sw = meta.get("sim_window")
    if sw:
      window = (sw[0] - PAD_BEFORE_S, sw[1] + PAD_AFTER_S)
    else:
      window = (frames[0]["t"], frames[-1]["t"])
  snaps = None
  if "t0_mono" in meta:
    t0 = int(meta["t0_mono"])
    sub = window_segments(files, window)
    if sub:
      print(f"reading {len(sub)} of {len(files)} rlog segment(s) under {rdir} ...", file=sys.stderr)
      snaps, info = read_rlog(sub)
      m = [s["mono"] for s in snaps]
      if not m or m[0] > t0 + window[0] * 1e9 or m[-1] < t0 + window[1] * 1e9:
        snaps = None
  if snaps is None:
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
             "path": [], "lanes": [], "lprob": [], "tr": [], "trlog": [], "rs_tracks": [], "cal": [], "q": []}
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
    D["cal"].append(s["cal"])
    D["rs_tracks"].append(s["rs_tracks"])
    D["q"].append(s["q"])

  # native vRel of the lead: replay has it in viz; log takes the raw point with the same id from the liveTracks
  # radard built that radarState from (the one before it). Pairing with the same-time liveTracks is one cycle
  # late and reads as extra closing whenever closing speed changes (Radar Work (Bob), 2026-09-29: 293 412-428
  # device correction 2.50 -> 0.00, 294 559-567 1.28 -> 0.00, 25e 725 2.05 -> 0.23)
  for i, L in enumerate(D["L1log"]):
    if L is not None and L[5]:
      pt = next((p for p in D["rs_tracks"][i] if p[0] == L[4]), None)
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
               "onpath_half_m": ONPATH_HALF_M, "vis_prob": VIS_PROB, "event_t": event_t,
               "cutin": {"rate_mps": CUTIN_RATE_MPS, "doff_m": CUTIN_DOFF_M, "win_s": CUTIN_RATE_WIN_S}}
  D["metrics"], D["events"] = metrics(D)
  D["cam_info"] = info["cam"]
  return D


# ---------------------------------------------------------------------------------------------- camera

def _qcamera_path(qdir: Path, seg: int) -> Path | None:
  for p in (qdir / str(seg) / "qcamera.ts", *sorted(qdir.glob(f"*--{seg}/qcamera.ts"))):
    if p.exists():
      return p
  return None


def add_camera(D: dict, qdir: Path) -> None:
  """Embed the qcamera frame behind each row, and the calibrated-frame -> qcamera-pixel matrix to draw on it."""
  from PIL import Image
  need: dict[int, set[int]] = {}
  for q in D["q"]:
    if q is not None:
      need.setdefault(q[0], set()).add(q[1])
  imgs: list[str] = []
  where: dict[tuple[int, int], int] = {}
  size = None
  for seg, ids in sorted(need.items()):
    path = _qcamera_path(qdir, seg)
    if path is None:
      print(f"no qcamera.ts for segment {seg} under {qdir}", file=sys.stderr)
      continue
    wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.split()[0].split(",")
    w, h = int(wh[0]), int(wh[1])
    size = (w, h)
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            stdout=subprocess.PIPE)
    k, last = 0, max(ids)
    while k <= last:
      buf = proc.stdout.read(w * h * 3)
      if len(buf) < w * h * 3:
        break
      if k in ids:
        out = io.BytesIO()
        Image.frombytes("RGB", (w, h), buf).save(out, "JPEG", quality=CAM_JPEG_Q)
        where[(seg, k)] = len(imgs)
        imgs.append(base64.b64encode(out.getvalue()).decode())
      k += 1
    proc.kill()
    proc.wait()
  if not imgs or size is None:
    return
  dev, sensor = D.get("cam_info") or ("tici", "unknown")
  fcam = DEVICE_CAMERAS.get((dev, sensor), DEVICE_CAMERAS[("tici", "unknown")]).fcam
  K = fcam.intrinsics.copy()
  K[0] *= size[0] / fcam.width   # qcamera is the full road frame scaled, per axis
  K[1] *= size[1] / fcam.height
  mats = []
  for c in D["cal"]:
    if c is None:
      mats.append(None)
      continue
    m = K @ view_frame_from_device_frame @ rot_from_euler(c[:3])
    mats.append([round(float(x), 5) for x in m.ravel()] + [round(c[3], 3)])
  D["cam"] = {"w": size[0], "h": size[1], "imgs": imgs, "device": [dev, sensor], "radar_to_camera": RADAR_TO_CAMERA,
              "idx": [where.get(tuple(q)) if q is not None else None for q in D["q"]], "P": mats}
  print(f"camera: {len(imgs)} qcamera frames {size[0]}x{size[1]} ({dev}/{sensor})", file=sys.stderr)


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


def sustained_run(t, x) -> tuple[float | None, float | None]:
  """Largest value x stayed at or above for SUSTAIN_S (a gap in x ends the run), and when that run began."""
  best, best_t = None, None
  for i in range(len(t)):
    if not np.isfinite(x[i]):
      continue
    lo, j = x[i], i
    while j + 1 < len(t) and np.isfinite(x[j + 1]) and t[j + 1] - t[i] <= SUSTAIN_S:
      j += 1
      lo = min(lo, x[j])
    if t[j] - t[i] >= SUSTAIN_S - 0.06 and (best is None or lo > best):
      best, best_t = lo, t[i]
  return (fnum(best), best_t) if best is not None else (None, None)


def sustained_max(t, x) -> float | None:
  return sustained_run(t, x)[0]


# Range-assist classes (Radar Work (Bob), 2026-09-29). Extra closing (native - published vRel) of
# PHANTOM_EXTRA_MPS or more is a phantom only when it moved the published lead speed AWAY from the
# camera's; 00000297 39:01.8 (Bob clock) hit the 8.0 cap and pulled a lagging vLead TOWARD the camera,
# so the raw sustained figure alone flags a rescue. No same-car camera at VIS_PROB -> unjudged.
PHANTOM_EXTRA_MPS = 2.0
PHANTOM_AWAY_MARGIN_MPS = 1.0
# The camera's speed under-reads closing on far cars (STATUS 162 / 280 15:03). 00000297 53:40: camera v steady
# while its own x fell 119 -> 49 m in 8 s. So a "phantom" frame gets a second look at the camera's distance. Rule
# from Radar Work (Bob), 2026-09-29, provisional pending Fix A v2 and kept identical to it:
# - trailing window [t - XRATE_WIN_S, t], same-car points only: radard only sees the past, so judge t as it would.
#   Fewer than XRATE_MIN_PTS -> unjudged.
# - camera x is +-5 m noisy and steps on lead switches. At 00000297 10:55 it sat at 72-77 m, dropped 13 m in 0.3 s,
#   then stayed flat at 58-63 m, and a line fit across that read as 7-10 m/s of closing. So fit a step first (two
#   flat levels, >= XRATE_STEP_MIN_SIDE points a side). If it leaves less than XRATE_STEP_SSE_FRAC of the line's
#   squared error and the step is over XRATE_STEP_M, keep only the points after the break; fewer than
#   XRATE_POST_MIN_PTS or under XRATE_POST_MIN_S of them -> unjudged.
# - on the clean points refit a line. Camera x noise grows with range (53:40: resid sd 3.1-3.5 m at 100-120 m), so the
#   limits scale with mean camera x: resid sd over max(XRATE_RESID_SD_M, XRATE_RESID_SD_FRAC * x) -> unjudged; slope
#   within max(XRATE_AGREE_MPS, XRATE_AGREE_FRAC * x) of the radar range slope -> neutral; otherwise phantom.
#   Resid sd uses n-2 degrees of freedom; the radar slope is fitted on the same (post-break) samples.
#   XRATE_AGREE_FRAC is 0 (Bob, 2026-09-29): at 95-107 m on 00000297 42:18 0.03 * x widened agreement to ~3 m/s and let
#   the radar walk pass as agree. Kept as a named term so Fix A v2 and the viewer stay the same.
XRATE_WIN_S = 3.0
XRATE_MIN_PTS = 20
XRATE_STEP_MIN_SIDE = 5
XRATE_STEP_SSE_FRAC = 0.5
XRATE_STEP_M = 6.0
XRATE_POST_MIN_PTS = 10
XRATE_POST_MIN_S = 1.0
XRATE_RESID_SD_M = 3.0
XRATE_RESID_SD_FRAC = 0.04
XRATE_AGREE_MPS = 2.0
XRATE_AGREE_FRAC = 0.0
# Published vRel minus the radar range slope over the same window is reported, never used in the class: the trailing
# 3 s camera slope lags a change in closing by ~1.5 s while published vRel does not, so camera vs published would call
# phantom at the onset of every real closing (00000297 drop: 3227.5). Radar vs radar range lags equally on both sides.
# A frame the camera calls neutral with |published - range slope| over XRATE_OVERSHOOT_MPS is tagged "assist
# overshoot": the ranges agree, so the radar is on the camera's car, but the assist's short fit overshot its own range
# (00000297 40:24 2430.2: published -6.44, range slope -2.87, camera -1.68). Radar-only; Bob, 2026-09-29.
XRATE_OVERSHOOT_MPS = 2.0
ASSIST_CLASSES = ("phantom", "helped", "neutral", "unjudged")


def xrate_verdict(t, x, d, v_rel_pub=None) -> dict:
  """Camera-distance check on one trailing window of same-car points: verdict 'phantom', 'neutral' or 'unjudged'."""
  r = {"n": len(t)}
  if len(t) < XRATE_MIN_PTS:
    return {**r, "verdict": "unjudged", "why": "few points"}
  o = np.argsort(t)
  t, x, d = t[o], x[o], d[o]
  sse_l = float(np.sum((x - np.polyval(np.polyfit(t, x, 1), t)) ** 2))
  n, k = len(x), np.arange(XRATE_STEP_MIN_SIDE, len(x) - XRATE_STEP_MIN_SIDE + 1)
  c1, c2 = np.concatenate([[0], np.cumsum(x)]), np.concatenate([[0], np.cumsum(x * x)])
  sse_s = (c2[k] - c1[k] ** 2 / k) + (c2[n] - c2[k] - (c1[n] - c1[k]) ** 2 / (n - k))
  j = int(np.argmin(sse_s))
  r["step_m"] = abs(float(c1[k[j]] / k[j] - (c1[n] - c1[k[j]]) / (n - k[j])))
  r["step_sse_frac"] = float(sse_s[j] / sse_l) if sse_l > 0 else 1.0
  if r["step_sse_frac"] < XRATE_STEP_SSE_FRAC and r["step_m"] > XRATE_STEP_M:
    r["break_t"] = float(t[k[j]])
    t, x, d = t[k[j]:], x[k[j]:], d[k[j]:]
    if len(t) < XRATE_POST_MIN_PTS or t[-1] - t[0] < XRATE_POST_MIN_S:
      return {**r, "verdict": "unjudged", "why": "step, short after"}
  pc, pd = np.polyfit(t, x, 1), np.polyfit(t, d, 1)
  xm = float(np.mean(x))
  r.update(cam_mps=float(pc[0]), radar_mps=float(pd[0]), cam_x_m=xm,
           resid_sd_m=float(np.sqrt(np.sum((x - np.polyval(pc, t)) ** 2) / (len(t) - 2))))
  if r["resid_sd_m"] > max(XRATE_RESID_SD_M, XRATE_RESID_SD_FRAC * xm):
    return {**r, "verdict": "unjudged", "why": "noisy"}
  tol = max(XRATE_AGREE_MPS, XRATE_AGREE_FRAC * xm)
  if v_rel_pub is not None and np.isfinite(v_rel_pub):
    r.update(pub_mps=float(v_rel_pub), pub_minus_range_mps=float(v_rel_pub) - r["radar_mps"])
  if abs(r["cam_mps"] - r["radar_mps"]) < tol:
    over = abs(r.get("pub_minus_range_mps", 0.0)) > XRATE_OVERSHOOT_MPS
    return {**r, "verdict": "neutral", "why": "agree, assist overshoot" if over else "agree"}
  return {**r, "verdict": "phantom", "why": "disagree"}


def assist_classes(t, extra, v_pub, v_nat, vis_v, same, d_radar=None, x_cam=None, v_rel_pub=None) -> dict:
  """Per class: largest extra closing held >= SUSTAIN_S inside that class, and when it began."""
  t = np.asarray(t, dtype=float)
  masks, flips = assist_masks(t, extra, v_pub, v_nat, vis_v, same, d_radar, x_cam, v_rel_pub)
  out = {}
  for k in ASSIST_CLASSES:
    v, ts = sustained_run(t, np.where(masks[k], extra, np.nan))
    out[k] = {"extra_sustained": v, "t": ts}
  out["xrate_flips"] = flips
  return out


def assist_masks(t, extra, v_pub, v_nat, vis_v, same, d_radar=None, x_cam=None, v_rel_pub=None) -> tuple[dict, list]:
  """Per-frame class masks (extra closing >= PHANTOM_EXTRA_MPS only) and the camera-distance check's flips."""
  t = np.asarray(t, dtype=float)
  e_pub, e_nat = np.abs(v_pub - vis_v), np.abs(v_nat - vis_v)
  big = np.isfinite(extra) & (extra >= PHANTOM_EXTRA_MPS)
  judged = same & np.isfinite(e_pub) & np.isfinite(e_nat)
  masks = {
    "phantom": big & judged & (e_pub > e_nat + PHANTOM_AWAY_MARGIN_MPS),
    "helped": big & judged & (e_pub < e_nat),
    "unjudged": big & ~judged,
  }
  flips = []
  if d_radar is not None and x_cam is not None:
    ok = same & np.isfinite(x_cam) & np.isfinite(d_radar)
    to = {}
    for i in np.where(masks["phantom"])[0]:
      w = ok & (t <= t[i]) & (t >= t[i] - XRATE_WIN_S)
      r = xrate_verdict(t[w], x_cam[w], d_radar[w], v_rel_pub[i] if v_rel_pub is not None else None)
      if r["verdict"] != "phantom":
        to[i] = r
    for i, r in to.items():
      masks["phantom"][i] = False
      if r["verdict"] == "unjudged":
        masks["unjudged"][i] = True
    # contiguous runs of frames the camera-distance check moved out of phantom, for the log and Bob's table
    for i in sorted(to):
      r = to[i]
      if flips and flips[-1]["to"] == r["verdict"] and flips[-1]["why"] == r["why"] and flips[-1]["_i"] == i - 1:
        flips[-1].update(t1=float(t[i]), n=flips[-1]["n"] + 1, _i=i)
      else:
        flips.append({"to": r["verdict"], "why": r["why"], "t0": float(t[i]), "t1": float(t[i]), "n": 1, "_i": i,
                      **{k: round(v, 2) for k, v in r.items() if isinstance(v, float)}})
    for f in flips:
      f.pop("_i")
  masks["neutral"] = big & judged & ~masks["phantom"] & ~masks["helped"] & ~masks["unjudged"]
  return masks, flips


# Cut-in at range-assist arm, for Fix A v3 (range assist blocked while a track is still cutting in). Radar Work (Bob),
# 2026-09-29. PLACEHOLDER numbers: the Fix A agent settles the real ones and Bob sends them so the two stay identical.
# - path offset of a track = its yRel minus the model path's lateral at its dRel (both +left; past the end of the path
#   hold its last lateral, as onpath_ids does). Kept per track id from every liveTracks point, so the history exists
#   before the track becomes leadOne.
# - lateral rate = slope of a line fit to that track's offset over the trailing CUTIN_RATE_WIN_S (>= CUTIN_MIN_PTS
#   points spanning >= CUTIN_MIN_SPAN_S, else none). Offset change = offset now minus the oldest offset in the same
#   window.
# - an arm is the tick the correction (native - published vRel of the radar leadOne) first goes above 0; its episode
#   runs until the correction is back to <= 0 or leadOne changes track. Cutting in at arm: |lateral rate| >
#   CUTIN_RATE_MPS or |offset change| > CUTIN_DOFF_M. 00000297 10:55 (track 41, yRel 5.2 -> 0.5 while range walked
#   75 -> 60) is the case it must show.
CUTIN_RATE_WIN_S = 1.0
CUTIN_MIN_PTS = 8
CUTIN_MIN_SPAN_S = 0.5
CUTIN_RATE_MPS = 1.0
CUTIN_DOFF_M = 1.5
# After an arm, did the gap really close? Line fit over [arm, arm + CONFIRM_WIN_S] of the same track's radar range,
# and of the camera lead's x while it is the same car; a slope below -CONFIRM_CLOSING_MPS confirms real closing.
CONFIRM_WIN_S = 2.0
CONFIRM_CLOSING_MPS = 1.0
BRAKE_WIN_S = 4.0         # logged brake after an arm: min command and aEgo over [arm, arm + BRAKE_WIN_S]
DD_PRE_S = 1.5            # trailing window for dd_rate_pre / range_slope_pre: [arm - DD_PRE_S, arm], what radard saw at the arm


def _slope(t, x, min_pts, min_span):
  ok = np.isfinite(x)
  if ok.sum() < min_pts or t[ok][-1] - t[ok][0] < min_span:
    return np.nan
  return float(np.polyfit(t[ok], x[ok], 1)[0])


def cutin_series(t, lead_recs, id_k, tracks, paths) -> dict:
  """Per frame, for the radar leadOne's track: path offset, trailing lateral rate and offset change."""
  hist: dict[int, list[tuple[float, float]]] = {}
  n = len(t)
  out = {k: np.full(n, np.nan) for k in ("off", "rate", "doff")}
  out["id"] = [None] * n
  for i in range(n):
    path = paths[i]
    if path and path[0]:
      for tid, d, y, _vr, _meas in tracks[i]:
        if d is not None and y is not None:
          hist.setdefault(tid, []).append((t[i], y - float(np.interp(d, path[0], path[1]))))
    L = lead_recs[i]
    if L is None or not L[id_k + 1]:
      continue
    tid = L[id_k]
    h = hist[tid] = [p for p in hist.get(tid, []) if t[i] - CUTIN_RATE_WIN_S <= p[0] <= t[i]]
    if not h or h[-1][0] != t[i]:
      continue
    ht, ho = np.array([p[0] for p in h]), np.array([p[1] for p in h])
    out["id"][i] = tid
    out["off"][i] = ho[-1]
    out["rate"][i] = _slope(ht, ho, CUTIN_MIN_PTS, CUTIN_MIN_SPAN_S)
    if ht[-1] - ht[0] >= CUTIN_MIN_SPAN_S:
      out["doff"][i] = ho[-1] - ho[0]
  return out


def range_assist_arms(t, corr, ser, lead_recs, tracks, vis, v_ego, a_ego, cmd) -> list[dict]:
  """Every range-assist arm: cut-in state at the arm tick, correction peak, whether the gap really closed, the brake."""
  t = np.asarray(t, dtype=float)
  vis_d, vis_p = _col(vis, 0), _col(vis, 3)
  arms, i, n = [], 0, len(t)

  def track_d(mask, tid):
    # range of track tid on the ticks in mask; loops only over those ticks so hour-long routes stay cheap
    out = np.full(n, np.nan)
    for k in np.flatnonzero(mask):
      out[k] = next((p[1] for p in tracks[k] if p[0] == tid), np.nan)
    return out
  while i < n:
    tid = ser["id"][i]
    if not (np.isfinite(corr[i]) and corr[i] > 0 and tid is not None) or (i > 0 and np.isfinite(corr[i - 1]) and corr[i - 1] > 0
                                                                          and ser["id"][i - 1] == tid):
      i += 1
      continue
    j = i
    while j + 1 < n and np.isfinite(corr[j + 1]) and corr[j + 1] > 0 and ser["id"][j + 1] == tid:
      j += 1
    rate, doff = ser["rate"][i], ser["doff"][i]
    cut = bool((np.isfinite(rate) and abs(rate) > CUTIN_RATE_MPS) or (np.isfinite(doff) and abs(doff) > CUTIN_DOFF_M))
    w = (t >= t[i]) & (t <= t[i] + CONFIRM_WIN_S)
    d_tr = track_d(w, tid)
    rng = _slope(t[w], d_tr[w], 10, 1.0)
    same = w & (vis_p > VIS_PROB) & np.isfinite(d_tr) & (np.abs(vis_d - d_tr) < np.maximum(10.0, 0.2 * d_tr))
    cam = _slope(t[same], vis_d[same], 10, 1.0)
    b = (t >= t[i]) & (t <= t[i] + BRAKE_WIN_S)
    L = lead_recs[i]
    # radar lead range minus camera x on the armed track, ungated: a range that starts long and walks down
    # onto the camera shrinks the gap at about the range slope while the camera holds; a car that really
    # closes keeps the gap and moves both (Radar Work (Bob), 2026-09-29, 10:55 vs 53:40)
    dd = np.full(n, np.nan)
    for k in np.flatnonzero((t >= t[i] - DD_PRE_S) & (t <= t[i] + BRAKE_WIN_S + 0.25)):
      L_ = lead_recs[k]
      if L_ is not None and L_[0] is not None and ser["id"][k] == tid and vis_p[k] > VIS_PROB:
        dd[k] = L_[0] - vis_d[k]
    ddw = w & np.isfinite(dd)
    # trailing twins of dd_rate and range_slope over [arm - DD_PRE_S, arm]: what radard could see when it armed
    # (10:55's correction peaks 0.6 s after the arm, inside the forward window; Bob, 2026-09-29)
    pw = (t >= t[i] - DD_PRE_S) & (t <= t[i])
    ddp = pw & np.isfinite(dd)
    d_pre = track_d(pw, tid)
    d_lead = np.full(n, np.nan)
    for k in np.flatnonzero(ddp):
      d_lead[k] = lead_recs[k][0]
    same_pre = ddp & (np.abs(dd) < np.maximum(10.0, 0.2 * d_lead))
    rng_pre = _slope(t[pw], d_pre[pw], 10, 1.0)
    dd_rate_pre = _slope(t[ddp], dd[ddp], 10, 1.0)

    def dd_at(tk, dd=dd):
      m = np.isfinite(dd) & (np.abs(t - tk) <= 0.25)
      return fnum(np.median(dd[m])) if m.any() else None
    arms.append({
      "t": float(t[i]), "t_end": float(t[j]), "track": int(tid), "d": L[0], "y": L[1], "v_pub": L[2],
      "off": fnum(ser["off"][i]), "rate": fnum(rate), "doff": fnum(doff), "cutting_in": cut,
      "corr_at_arm": fnum(corr[i]), "corr_peak": fnum(np.nanmax(corr[i:j + 1])),
      "t_peak": float(t[i + int(np.nanargmax(corr[i:j + 1]))]),
      "range_slope": fnum(rng), "cam_slope": fnum(cam),
      "dd_arm": dd_at(t[i]), "dd_2s": dd_at(t[i] + CONFIRM_WIN_S), "dd_4s": dd_at(t[i] + BRAKE_WIN_S),
      "dd_rate": fnum(_slope(t[ddw], dd[ddw], 10, 1.0)),
      "dd_rate_pre": fnum(dd_rate_pre), "dd_n_pre": int(ddp.sum()), "dd_same_n_pre": int(same_pre.sum()), "range_slope_pre": fnum(rng_pre),
      "dd_over_range_pre": fnum(dd_rate_pre / rng_pre) if np.isfinite(dd_rate_pre) and np.isfinite(rng_pre)
      and abs(rng_pre) > 0.5 else None,
      "range_confirms": bool(np.isfinite(rng) and rng < -CONFIRM_CLOSING_MPS),
      "cam_confirms": None if not np.isfinite(cam) else bool(cam < -CONFIRM_CLOSING_MPS),
      "min_cmd": fnum(np.nanmin(cmd[b])) if np.isfinite(cmd[b]).any() else None,
      "min_a_ego": fnum(np.nanmin(a_ego[b])) if np.isfinite(a_ego[b]).any() else None,
      "v_ego": fnum(v_ego[i]),
    })
    i = j + 1
  return arms


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
  common["assist_log"] = assist_classes(t, vnl - vpl, v_log + vpl, v_log + vnl, vis_v, same, dl, vis_d, vpl)
  cmd = arr(D["acmd"])
  ser = cutin_series(t, L1l, 4, D["rs_tracks"], D["path"])
  D["cutin_log"] = {k: [fnum(x) for x in ser[k]] for k in ("off", "rate", "doff")}
  common["arms_log"] = range_assist_arms(t, vnl - vpl, ser, L1l, D["rs_tracks"], D["vis"], v_log, a_log, cmd)
  if D["meta"]["has_viz"]:
    ser = cutin_series(t, L1, 5, D["tr"], D["path"])
    D["cutin_rep"] = {k: [fnum(x) for x in ser[k]] for k in ("off", "rate", "doff")}
    common["arms"] = range_assist_arms(t, vn1 - vr1, ser, L1, D["tr"], D["vis"], v_log, a_log, cmd)
    same1 = (radar1 == 1) & (vis_p > VIS_PROB) & (np.abs(d1 - vis_d) < np.maximum(10.0, 0.2 * d1))
    common["assist"] = assist_classes(t, vn1 - vr1, v_log + vr1, v_log + vn1, vis_v, same1, d1, vis_d, vr1)

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
  for side, key in (("replay", "assist"), ("log", "assist_log")):
    if key in c:
      print(f"  range assist ({side}, extra >= {PHANTOM_EXTRA_MPS:g} held {SUSTAIN_S:g} s): " + "  ".join(
        f"{k} {c[key][k]['extra_sustained']}" + (f" @{c[key][k]['t']:.2f}" if c[key][k]["t"] is not None else "")
        for k in ASSIST_CLASSES))
      for fl in c[key].get("xrate_flips", []):
        print(f"    camera-distance check {side}: phantom -> {fl['to']} ({fl['why']}) {fl['t0']:.2f}-{fl['t1']:.2f}",
              f"({fl['n']} frames)", " ".join(f"{k} {fl[k]}" for k in ("cam_mps", "radar_mps", "cam_x_m", "resid_sd_m",
                                                                       "pub_mps", "pub_minus_range_mps", "step_m", "step_sse_frac", "break_t") if k in fl))
  for side, key in (("replay", "arms"), ("log", "arms_log")):
    for r in c.get(key, []):
      print(f"  range-assist arm ({side}) {r['t']:.2f}-{r['t_end']:.2f} track {r['track']} d {r['d']}:",
            f"cutting-in at arm {'YES' if r['cutting_in'] else 'no'} (offset {r['off']} m, lat rate {r['rate']} m/s,",
            f"offset change {r['doff']} m in {CUTIN_RATE_WIN_S:g} s); correction peak {r['corr_peak']} @{r['t_peak']:.2f};",
            f"range slope {r['range_slope']} cam slope {r['cam_slope']};",
            f"radar - camera {r['dd_arm']} m at arm, {r['dd_2s']} +2 s, {r['dd_4s']} +4 s, rate {r['dd_rate']} m/s;",
            f"trailing {DD_PRE_S:g} s: radar - camera rate {r['dd_rate_pre']} m/s ({r['dd_n_pre']} pts), range slope",
            f"{r['range_slope_pre']}, ratio {r['dd_over_range_pre']};",
            f"min cmd {r['min_cmd']} min aEgo {r['min_a_ego']}")
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
  ap.add_argument("--qcamera-dir", type=Path, help="dir with <seg>/qcamera.ts or <route>--<seg>/qcamera.ts "
                  + "(default: the route dir); the page shows the road camera with the radar tracks drawn on it")
  ap.add_argument("--no-camera", action="store_true")
  args = ap.parse_args()
  window = tuple(float(x) for x in args.window.split(",")) if args.window else None
  D = build(args.frames_json, args.route_dir, window, args.event_t)
  print_metrics(D)
  if args.metrics_json:
    args.metrics_json.write_text(json.dumps({"meta": D["meta"], **D["metrics"], "events": D["events"]}, indent=1))
  if args.html:
    if not args.no_camera:
      add_camera(D, args.qcamera_dir or Path(D["meta"]["route_dir"]))
    write_html(D, args.html)
    print(f"wrote {args.html}", file=sys.stderr)
  if args.mp4:
    write_mp4(D, args.mp4, args.fps, args.range, args.variants.split(",") if args.variants else None)
    print(f"wrote {args.mp4}", file=sys.stderr)
  return 0


if __name__ == "__main__":
  sys.exit(main())
