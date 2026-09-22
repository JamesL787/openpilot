#!/usr/bin/env python3
"""One-time direct alignment of the physical C3X narrow/wide camera pair.

The persisted ReprojectRotation is physical board geometry and is the single
truth. It is fitted once, then left alone until an explicit Reset Calibration
clears both CalibrationParams and ReprojectRotation. No runtime feature switch,
no model-output geometry learner and no refit loop.
"""

import os
import time

import numpy as np

import cereal.messaging as messaging
from msgq.visionipc import VisionIpcClient, VisionStreamType
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.locationd.calibrationd import MAX_YAW_RATE_FILTER, MIN_SPEED_FILTER
from openpilot.selfdrive.modeld import reproject_c4 as RC

N_FRAMES = 12
MAX_RMS_DEG = 0.25
C4_CAM = RC.C4_CAM
NARROW = VisionStreamType.VISION_STREAM_ROAD
WIDE = VisionStreamType.VISION_STREAM_WIDE_ROAD


def luma(buf) -> np.ndarray:
  return np.array(buf.data[:buf.uv_offset], dtype=np.uint8).reshape(-1, buf.stride)[:buf.height, :buf.width]



class Fit:
  def __init__(self, applied):
    self.applied = tuple(float(v) for v in applied)
    self.calib = RC.calib_from_rotvec(self.applied)
    self.fits: list[tuple] = []
    self.mean = self.applied
    self.last_id = 0
    self.last_ok = False

  @property
  def n(self) -> int:
    return len(self.fits)

  @property
  def complete(self) -> bool:
    return self.n >= N_FRAMES

  @property
  def spread(self) -> float:
    return float(np.degrees(np.abs(np.array(self.fits) - self.mean).max())) if self.fits else 0.0

  def frame(self, narrow_y, wide_y, frame_id: int):
    r = (
      RC.fit_rotation(narrow_y, wide_y, self.calib)
      if not self.fits
      else RC.fit_rotation(narrow_y, wide_y, RC.calib_from_rotvec(self.mean), iters=1, coarse=False)
    )
    self.last_id = frame_id
    self.last_ok = r is not None and r[2] <= MAX_RMS_DEG
    if not self.last_ok:
      return None
    self.fits.append(r[0])
    self.mean = tuple(float(v) for v in np.median(self.fits, axis=0))
    return r


class FitState:
  def __init__(self):
    self.pm = messaging.PubMaster(["reprojectFit"])
    self.last = None
    self.t = 0.0

  def publish(self, status: str, fit: Fit, why: str | None = None) -> None:
    pct = 100 if status in ("building", "fitted") else min(99, 100 * fit.n // N_FRAMES)
    mean = [float(v) for v in fit.mean]
    key = (status, why, pct, tuple(mean), fit.last_id, fit.last_ok)
    if key == self.last and time.monotonic() - self.t < 0.5:
      return
    self.last, self.t = key, time.monotonic()
    msg = messaging.new_message("reprojectFit", valid=True)
    f = msg.reprojectFit
    f.status = status
    f.why = why or "none"
    f.pct = pct
    f.mean = mean
    f.lastFrameId = fit.last_id
    f.lastAccepted = fit.last_ok
    self.pm.send("reprojectFit", msg)


def save_completed_rotation(rotvec, fit: Fit) -> None:
  """Persist only the final estimate, explicitly marked safe for reboot use."""
  RC.save_rotation(
    rotvec,
    fitted=True,
    n=fit.n,
    spread_deg=round(fit.spread, 3),
    applied=[float(v) for v in fit.applied],
  )


def main():
  os.nice(10)
  sm = messaging.SubMaster(["carState", "liveCalibration", "cameraOdometry"])
  narrow = VisionIpcClient("camerad", NARROW, True)
  wide = VisionIpcClient("camerad", WIDE, False)
  params = Params()
  state = FitState()
  fit = Fit(RC.load_rotation())
  fitted = bool(RC.read_rotation())
  cloudlog.warning(
    "reprojectcalibd: applied rotation %s deg, %s",
    np.degrees(fit.applied).round(3),
    "fitted" if fitted else "not fitted yet",
  )

  def done(final) -> None:
    final_fit = Fit(final)
    final_fit.mean = tuple(float(v) for v in final)
    while True:
      state.publish("fitted", final_fit)
      time.sleep(0.5)

  if fitted:
    done(fit.applied)

  state.publish("waiting", fit)
  why = None
  why_t = log_t = time.monotonic()

  def waiting(reason: str | None) -> None:
    nonlocal why, why_t, log_t
    now = time.monotonic()
    if reason != why:
      if why is not None and now - why_t > 5.0:
        cloudlog.warning("reprojectcalibd: waited %.0f s for %s at %d fits", now - why_t, why, fit.n)
      why, why_t, log_t = reason, now, now
    elif reason is not None and now - log_t > 30.0:
      cloudlog.warning("reprojectcalibd: still waiting for %s after %.0f s at %d fits", reason, now - why_t, fit.n)
      log_t = now
    state.publish("fitting" if fit.fits else "waiting", fit, why=reason)

  while True:
    sm.update(100)
    if not (narrow.is_connected() and wide.is_connected()):
      narrow.connect(False)
      wide.connect(False)
      waiting("cameras")
      continue
    if not (sm.alive["liveCalibration"] and sm.valid["liveCalibration"]):
      waiting("model")
      continue
    if not all(sm.alive[k] and sm.valid[k] for k in ("carState", "cameraOdometry")):
      waiting("model")
      continue
    if sm["carState"].vEgo <= MIN_SPEED_FILTER:
      waiting("speed")
      continue
    if abs(sm["cameraOdometry"].rot[2]) >= MAX_YAW_RATE_FILTER:
      waiting("straight")
      continue

    pair = RC.recv_pair(narrow, wide)
    if pair is None:
      waiting("pair")
      continue
    waiting(None)
    bn, bw = pair
    narrow_y, wide_y = luma(bn), luma(bw)
    t0 = time.monotonic()
    r = fit.frame(narrow_y, wide_y, narrow.frame_id)
    if r is None:
      cloudlog.warning("reprojectcalibd: frame %d rejected, %.1f s", narrow.frame_id, time.monotonic() - t0)
      state.publish("fitting" if fit.fits else "waiting", fit, why="features")
      continue

    cloudlog.warning(
      "reprojectcalibd: fit %d/%d: %s deg, %d matches, rms %.3f deg, %.1f s; median %s spread %.3f deg",
      fit.n,
      N_FRAMES,
      np.degrees(r[0]).round(3),
      r[1],
      r[2],
      time.monotonic() - t0,
      np.degrees(fit.mean).round(3),
      fit.spread,
    )
    state.publish("fitting", fit)
    if not fit.complete:
      continue

    final = tuple(float(v) for v in fit.mean)
    t0 = time.monotonic()
    state.publish("building", fit)
    RC.load_tables((bn.width, bn.height), C4_CAM, RC.table_cache_dir(), RC.calib_from_rotvec(final))
    cloudlog.warning("reprojectcalibd: tables built in %.1f s", time.monotonic() - t0)
    save_completed_rotation(final, fit)
    # The road calibration was accumulated against the old camera-pair geometry.
    # Delete the persisted copy before declaring the new geometry fitted so a
    # reboot cannot resurrect stale CalibrationParams in the handoff window.
    params.remove("CalibrationParams")
    cloudlog.warning(
      "reprojectcalibd: rotation fitted %s deg (was %s, spread %.3f deg)",
      np.degrees(final).round(3),
      np.degrees(fit.applied).round(3),
      fit.spread,
    )
    done(final)


if __name__ == "__main__":
  main()
