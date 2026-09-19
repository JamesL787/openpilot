#!/usr/bin/env python3
"""One-time direct narrow<->wide camera-pair alignment for VFN C3X->C4 reprojection.

Ported from AmyJeanes/openpilot-upstream:tizi-to-mici at the pinned checkpoint, with
VFN-specific service/schema names:
  * liveCalibration, not extrinsicsCalibration
  * log.LiveCalibrationData.Status
  * VISION_STREAM_ROAD, not upstream's VISION_STREAM_NARROW_ROAD

The fit is persistent. It runs until converged, builds the fitted reprojection tables at
low priority, writes rotation.json, and then mostly sleeps. A normal Settings -> Reset
Calibration intentionally asks it to fit again.
"""
import os
import time

import numpy as np

from cereal import log
import cereal.messaging as messaging
from msgq.visionipc import VisionIpcClient, VisionStreamType
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.locationd.calibrationd import MIN_SPEED_FILTER, MAX_YAW_RATE_FILTER
from openpilot.selfdrive.modeld import reproject_c4 as RC

MIN_N, MAX_N = 12, 40
SE_STOP = 0.02       # degrees, pitch/yaw standard error of trimmed mean
MIN_MATCHES = 15
MAX_RMS_DEG = 0.25
PROGRESS_FILE = "/data/reproject_c4/fit.json"
C4_CAM = (1344, 760)
CACHE_DIR = os.environ.get("XDG_CACHE_HOME", "/data/tgcache")
Status = log.LiveCalibrationData.Status


def luma(buf) -> np.ndarray:
  return np.array(buf.data[:buf.uv_offset], dtype=np.uint8).reshape(-1, buf.stride)[:buf.height, :buf.width]


def progress_pct(n: int, se: float) -> int:
  need = max(MIN_N, n * (se / SE_STOP) ** 2 if n and np.isfinite(se) and se > SE_STOP else 0)
  return int(min(99, 100 * max(n / need, n / MAX_N)))


_pct = [0]


def write_progress(**kw) -> None:
  try:
    import json
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    _pct[0] = 100 if kw.get("fitted") else max(
      0 if kw.get("n", 0) == 0 else _pct[0],
      progress_pct(kw.get("n", 0), kw.get("se_deg", np.inf)),
    )
    kw.setdefault("pct", _pct[0])
    tmp = PROGRESS_FILE + ".tmp"
    json.dump(kw, open(tmp, "w"))
    os.replace(tmp, PROGRESS_FILE)
  except OSError:
    pass


def main():
  # Never inherit modeld's realtime behavior. The phase/Kabsch work and LUT build are
  # intentionally ordinary low-priority CPU work.
  os.nice(10)

  sm = messaging.SubMaster(["carState", "liveCalibration", "cameraOdometry"])
  clients = {
    "narrow": VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_ROAD, True),
    "wide": VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD, True),
  }

  applied = tuple(RC.read_applied().get("rotvec") or RC.load_rotation())
  calib = RC.calib_from_rotvec(applied)
  state = RC.read_rotation_file()
  fits: list[tuple] = []
  mean = applied
  prev_cal = None

  if state.get("fitted") and Params().get("CalibrationParams") is None:
    cloudlog.warning("reprojectd: calibration was reset: refitting the camera-pair rotation")
    state = {}

  cloudlog.warning(
    "reprojectd: applied rotation %s deg, %s",
    np.degrees(applied).round(3),
    "fitted" if state.get("fitted") else "not fitted yet",
  )
  write_progress(n=0, of=MAX_N, fitted=bool(state.get("fitted")))
  why = None

  def waiting(reason: str | None) -> None:
    nonlocal why
    if reason != why and not fits and not state.get("fitted"):
      why = reason
      write_progress(n=0, of=MAX_N, fitted=False, why=reason)

  while True:
    sm.update(100)

    # VFN can run small/model-lab paths with no C3X->C4 stage. A stale fitted file must
    # never make reprojectd interfere with ordinary calibration in those modes.
    applied_state = RC.read_applied()
    if not applied_state.get("stage", False):
      waiting("stage")
      time.sleep(0.5)
      continue

    if not all(c.is_connected() for c in clients.values()):
      for c in clients.values():
        c.connect(False)
      waiting("cameras")
      continue

    if not (sm.alive["liveCalibration"] and sm.valid["liveCalibration"]):
      waiting("model")
      continue

    cal = sm["liveCalibration"].calStatus
    if prev_cal is None:
      prev_cal = cal

    if state.get("fitted"):
      # Only a completed calibration that later reset means a new physical fit. The
      # reset caused by our own geometry handoff must not create a fit/swap/reset loop.
      if prev_cal == Status.calibrated and cal in (Status.uncalibrated, Status.recalibrating):
        cloudlog.warning("reprojectd: completed calibration reset: refitting camera-pair rotation")
        state = {}
        fits = []
        mean = applied
        write_progress(n=0, of=MAX_N, fitted=False)
      else:
        prev_cal = cal
        time.sleep(0.5)
        continue
    prev_cal = cal

    if not all(sm.alive[k] and sm.valid[k] for k in ("carState", "cameraOdometry")):
      waiting("model")
      continue
    if sm["carState"].vEgo <= MIN_SPEED_FILTER:
      waiting("speed")
      continue
    if abs(sm["cameraOdometry"].rot[2]) >= MAX_YAW_RATE_FILTER:
      waiting("straight")
      continue
    waiting(None)

    bn = clients["narrow"].recv(50)
    bw = clients["wide"].recv(50)
    if bn is None or bw is None or clients["narrow"].frame_id != clients["wide"].frame_id:
      continue

    narrow_y, wide_y = luma(bn), luma(bw)
    t0 = time.monotonic()

    # First accepted frame gets the coarse search; subsequent frames refine from the
    # running mean and are much cheaper.
    r = (
      RC.fit_rotation(narrow_y, wide_y, calib)
      if not fits
      else RC.fit_rotation(narrow_y, wide_y, RC.calib_from_rotvec(mean), iters=1, coarse=False)
    )

    if r is None or r[1] < MIN_MATCHES or r[2] > MAX_RMS_DEG:
      cloudlog.warning(
        "reprojectd: frame %d rejected (%s), %.1f s",
        clients["narrow"].frame_id,
        "no fit" if r is None else f"{r[1]} matches, rms {r[2]:.3f} deg",
        time.monotonic() - t0,
      )
      write_progress(
        n=len(fits),
        of=MAX_N,
        fitted=False,
        why="features",
        mean_deg=[round(float(x), 3) for x in np.degrees(mean)] if fits else None,
      )
      continue

    fits.append(r)
    mean, keep, spread, se = RC.combine_fits([f[0] for f in fits])
    cloudlog.warning(
      "reprojectd: fit %d: %s deg, %d matches, rms %.3f deg, %.1f s; mean %s spread %.3f se %.3f deg",
      len(fits),
      np.degrees(r[0]).round(3),
      r[1],
      r[2],
      time.monotonic() - t0,
      np.degrees(mean).round(3),
      spread,
      se,
    )
    write_progress(
      n=len(fits),
      of=MAX_N,
      fitted=False,
      last_deg=[round(float(x), 3) for x in np.degrees(r[0])],
      rms=round(r[2], 3),
      mean_deg=[round(float(x), 3) for x in np.degrees(mean)],
      se_deg=round(se, 3),
    )

    if not (len(fits) >= MIN_N and se < SE_STOP) and len(fits) < MAX_N:
      continue

    final = np.array(mean)

    # reprojectd owns the expensive table build. modeld's handoff should be one file
    # read + GPU upload, not numpy geometry construction in the realtime process.
    t0 = time.monotonic()
    write_progress(
      n=len(fits),
      of=MAX_N,
      fitted=False,
      building=True,
      deg=[round(float(x), 3) for x in np.degrees(final)],
      se_deg=round(se, 3),
    )
    RC.load_tables((bn.width, bn.height), C4_CAM, CACHE_DIR, RC.calib_from_rotvec(final))
    cloudlog.warning("reprojectd: fitted tables built in %.1f s", time.monotonic() - t0)

    RC.save_rotation(
      final,
      fitted=True,
      n=int(len(keep)),
      spread_deg=round(spread, 3),
      se_deg=round(se, 3),
      applied=[float(v) for v in applied],
    )
    cloudlog.warning(
      "reprojectd: rotation fitted %s deg (was %s, spread %.3f deg)",
      np.degrees(final).round(3),
      np.degrees(applied).round(3),
      spread,
    )

    state = RC.read_rotation_file()
    fits = []
    applied = tuple(float(v) for v in final)
    mean = applied
    calib = RC.calib_from_rotvec(applied)
    write_progress(
      n=len(keep),
      of=len(keep),
      fitted=True,
      deg=[round(float(x), 3) for x in np.degrees(final)],
      spread_deg=round(spread, 3),
      se_deg=round(se, 3),
    )


if __name__ == "__main__":
  main()
