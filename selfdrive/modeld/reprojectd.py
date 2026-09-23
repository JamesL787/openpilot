#!/usr/bin/env python3
"""Serve the physical C3X road/wide cameras as a virtual comma 4 camera pair.

This is the only runtime reprojection implementation. There is no project
feature switch and no legacy in-modeld reprojection fallback. The stage builds
and warms at normal priority, then enters the 20 Hz loop as FIFO 53 on core 6.
"""

import os
os.environ["QCOM_PRIORITY"] = "1"
os.environ["DEV"] = "QCOM"

import threading
import time

import numpy as np
from tinygrad import Device, Tensor

from cereal import custom
import cereal.messaging as messaging
from msgq.visionipc import VisionIpcClient, VisionIpcServer, VisionStreamType
from openpilot.common.realtime import config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.modeld import reproject_c4 as RC
from openpilot.selfdrive.modeld.reproject_c4.kernel import Reprojector
from openpilot.selfdrive.modeld.reproject_c4.vision import allocate_virtual_camera_frames
from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

C4_CAM = RC.C4_CAM
NARROW = VisionStreamType.VISION_STREAM_ROAD
WIDE = VisionStreamType.VISION_STREAM_WIDE_ROAD


class Stage:
  def __init__(self, src_wh: tuple[int, int]):
    self.src_wh = src_wh
    self.cache_dir = RC.table_cache_dir()
    self.src_size = get_nv12_info(*src_wh)[3]
    self.rotation = RC.load_rotation()
    self.fitted = bool(RC.read_rotation())
    cloudlog.warning(
      "reprojectd: rotation %s deg, %s",
      np.degrees(self.rotation).round(3),
      "fitted" if self.fitted else "board/reference seed",
    )
    self.calib = RC.calib_from_rotvec(self.rotation)
    tables = RC.load_tables(src_wh, C4_CAM, self.cache_dir, self.calib)
    self.rp = Reprojector(tables, C4_CAM, "QCOM")
    self.meter = RC.SeamMeter(tables["meter"])
    self.pending = None
    self.loader: threading.Thread | None = None
    self._src_tensors: dict[int, Tensor] = {}
    # Allocate the full Venus buffer expected by QCOM VisionIPC consumers.
    # The kernel writes only the active NV12 body; the zeroed tail remains
    # untouched and is copied with the frame for safe full-allocation mapping.
    self.out, self.body_size, self.stride, self.uv_offset = allocate_virtual_camera_frames(C4_CAM)
    if self.body_size != self.rp.body:
      raise ValueError(f"Virtual camera body mismatch: allocation={self.body_size}, kernel={self.rp.body}")
    self.rp.bind(self.out[1, :self.body_size], self.out[0, :self.body_size])
    self.time = 0.0

  def src_tensor(self, buf) -> Tensor:
    ptr = np.frombuffer(buf.data, dtype=np.uint8).ctypes.data
    if ptr not in self._src_tensors:
      self._src_tensors[ptr] = Tensor.from_blob(ptr, (self.src_size,), dtype="uint8", device="QCOM")
    return self._src_tensors[ptr]

  def run(self, wide, narrow, match: np.ndarray) -> None:
    t0 = time.perf_counter()
    self.rp(self.src_tensor(wide), self.src_tensor(narrow), match)
    Device["QCOM"].synchronize()
    self.time = time.perf_counter() - t0

  def follow_fit(self, fit) -> None:
    """Load the fitted tables off-loop, then swap one set of QCOM table inputs."""
    if self.pending is not None:
      tables, calib, meter, rot = self.pending
      self.pending = None
      self.loader = None
      t0 = time.perf_counter()
      self.rp.reload(tables)
      self.calib, self.meter, self.rotation, self.fitted = calib, meter, rot, True
      cloudlog.warning(
        "reprojectd: fitted rotation %s deg swapped in (%.0f ms)",
        np.degrees(rot).round(3),
        (time.perf_counter() - t0) * 1e3,
      )
      return

    if self.loader is not None or fit is None or fit.status != custom.ReprojectFit.Status.fitted or len(fit.mean) != 3:
      return
    rot = tuple(float(v) for v in fit.mean)
    if np.allclose(rot, self.rotation, atol=1e-6):
      # A fitted rotation may equal the seed closely enough to skip a table
      # reload; the lifecycle still needs to become fitted.
      self.fitted = True
      return
    calib = RC.calib_from_rotvec(rot)
    if not os.path.exists(RC.table_path(self.src_wh, C4_CAM, self.cache_dir, calib)):
      cloudlog.warning("reprojectd: fitted rotation has no table cache yet")
      return

    def load():
      # Threads inherit the realtime scheduler after the main loop starts.
      try:
        os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))
        tables = RC.load_tables(self.src_wh, C4_CAM, self.cache_dir, calib)
        meter = RC.SeamMeter(tables["meter"])
        self.pending = (tables, calib, meter, rot)
      except Exception:
        cloudlog.exception("reprojectd: failed to prepare fitted tables")
        self.loader = None

    self.loader = threading.Thread(target=load, daemon=True)
    self.loader.start()


def main():
  sm = messaging.SubMaster(["roadCameraState", "wideRoadCameraState", "reprojectFit"])
  pm = messaging.PubMaster(["reprojectState"])
  narrow = VisionIpcClient("camerad", NARROW, True)
  wide = VisionIpcClient("camerad", WIDE, False)
  while not narrow.connect(False):
    time.sleep(0.1)
  while not wide.connect(False):
    time.sleep(0.1)

  src_wh = (narrow.width, narrow.height)
  cloudlog.warning("reprojectd: cameras %dx%d -> comma 4 %dx%d", *src_wh, *C4_CAM)
  t0 = time.monotonic()
  stage = Stage(src_wh)

  # Capture the JIT before becoming realtime. Holding FIFO while loading tables
  # or capturing tinygrad can trip TICI's panic-on-RT-throttling kernel config.
  blank = [Tensor.zeros(stage.src_size, dtype="uint8", device="QCOM").contiguous().realize() for _ in range(2)]
  for _ in range(3):
    stage.rp(blank[0], blank[1])
    Device["QCOM"].synchronize()

  server = VisionIpcServer("reproject")
  for stream in (NARROW, WIDE):
    server.create_buffers_with_sizes(
      stream, 4, C4_CAM[0], C4_CAM[1], stage.out.shape[1], stage.stride, stage.uv_offset,
    )
  server.start_listener()
  cloudlog.warning("reprojectd: serving after %.1f s", time.monotonic() - t0)
  config_realtime_process(6, 53)

  n = 0
  while True:
    pair = RC.recv_pair(narrow, wide)
    if pair is None:
      continue
    buf_n, buf_w = pair
    sm.update(0)

    ncs, wcs = sm["roadCameraState"], sm["wideRoadCameraState"]
    exposure = RC.exposure_gain(
      ncs.gain * ncs.integLines,
      wcs.gain * wcs.integLines,
    ) if sm.seen["roadCameraState"] and sm.seen["wideRoadCameraState"] else 1.0
    match = stage.meter.update(
      np.frombuffer(buf_w.data, dtype=np.uint8),
      np.frombuffer(buf_n.data, dtype=np.uint8),
      exposure,
    )
    stage.run(buf_w, buf_n, match)

    server.send(NARROW, stage.out[0], narrow.frame_id, narrow.timestamp_sof, narrow.timestamp_eof)
    server.send(WIDE, stage.out[1], wide.frame_id, wide.timestamp_sof, wide.timestamp_eof)

    msg = messaging.new_message("reprojectState", valid=True)
    state = msg.reprojectState
    state.frameId = narrow.frame_id
    state.stageMs = stage.time * 1e3
    state.rotation = [float(v) for v in stage.rotation]
    state.fitted = stage.fitted
    pm.send("reprojectState", msg)

    n += 1
    if n % 20 == 0:
      stage.follow_fit(sm["reprojectFit"] if sm.seen["reprojectFit"] else None)


if __name__ == "__main__":
  main()
