#!/usr/bin/env python3
"""Render the car layout on the comma without a car: snapshots, frame rate and encode time.

  cd /data/openpilot && PYTHONPATH=/data/openpilot python3 tools/starpilot_auto/car_view_probe.py --seconds 20
  ... car_view_probe.py --rgba --sync-readback   # the pipeline before GPU NV12 and asynchronous readback

Starts the same offscreen car-UI renderer starpilot_autod uses, at a typical car
mode (1280x720 with a 240-row margin, i.e. a 1280x480 visible area), saves the
first and last frames as PNGs, and reports delivered frames per second and
hardware (or software) encode time. Changes no settings; the comma screen keeps
running normally. Do not run while Starpilot Auto is projecting.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from openpilot.starpilot.system.starpilot_auto.frame_source import FLAG_ASYNC_READBACK, FLAG_NV12, FORMAT_NV12, FrameRequest
from openpilot.starpilot.system.starpilot_auto.hw_encoder import create_encoder
from openpilot.starpilot.system.starpilot_auto.view import ViewSource


def save_png(frame, path: Path) -> None:
  import cv2
  import numpy as np
  if frame.pixel_format == FORMAT_NV12:
    image = np.frombuffer(frame.data, np.uint8).reshape(frame.height * 3 // 2, frame.width)
    cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_YUV2BGR_NV12))
  else:
    image = np.frombuffer(frame.data, np.uint8).reshape(frame.height, frame.width, 4)
    cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGBA2BGR))


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--seconds", type=float, default=20.0)
  parser.add_argument("--width", type=int, default=1280)
  parser.add_argument("--height", type=int, default=720)
  parser.add_argument("--margin-height", type=int, default=240)
  parser.add_argument("--output", type=Path, default=Path("/data/starpilot_auto/logs/car_view_probe"))
  parser.add_argument("--rgba", action="store_true", help="read RGBA back instead of converting to NV12 on the GPU")
  parser.add_argument("--sync-readback", action="store_true", help="stall on the GPU for every readback")
  parser.add_argument("--rate-control", choices=("cbr", "vbr"), default="cbr")
  args = parser.parse_args()
  args.output.mkdir(parents=True, exist_ok=True)
  events = []

  def log(name, **values):
    events.append({"event": name, **values})
    print(json.dumps({"event": name, **values}), flush=True)

  encoder, fps = create_encoder(args.width, args.height, preference="auto", bitrate_kbps=6000, margin_height=args.margin_height,
                                software_fps=15, log=log, rate_control=args.rate_control)
  flags = (0 if args.rgba or not getattr(encoder, "supports_nv12", False) else FLAG_NV12) | \
          (0 if args.sync_readback else FLAG_ASYNC_READBACK)
  request = FrameRequest(args.width, args.height, 0, args.margin_height, int(1e6 / fps), flags)
  view = ViewSource("car", request, log, renderer_log=args.output / "car_ui.log")
  first = last = None
  frames, encode_ms = 0, []
  started = time.monotonic()
  first_at = None
  try:
    while time.monotonic() - started < args.seconds:
      view.demand(1.0)
      view.check()
      if view.view != "car":
        print(json.dumps({"result": "fail", "reason": view.label, "log": str(args.output / "car_ui.log")}))
        return 1
      frame = view.latest()
      if frame is None:
        time.sleep(0.002)
        continue
      frames += 1
      first_at = first_at or time.monotonic()
      first = first or frame
      last = frame
      encode = encoder.encode_nv12 if frame.pixel_format == FORMAT_NV12 else encoder.encode_rgba
      _, _ = encode(frame.data, keyframe=frames == 1)
      encode_ms.append(encoder.last_encode_ms)
  finally:
    view.close()
    encoder.close()
  if first is None:
    print(json.dumps({"result": "fail", "reason": "no frames", "log": str(args.output / "car_ui.log")}))
    return 1
  save_png(first, args.output / "first.png")
  save_png(last, args.output / "last.png")
  elapsed = time.monotonic() - first_at if first_at else 0
  encode_ms.sort()
  print(json.dumps({"result": "pass", "frames": frames, "fps": round((frames - 1) / elapsed, 1) if elapsed else 0,
                    "startup_s": round(first_at - started, 1), "encoder": getattr(encoder, "backend", "?"),
                    "format": "nv12" if last.pixel_format == FORMAT_NV12 else "rgba", "async_readback": not args.sync_readback,
                    "encode_ms_median": round(encode_ms[len(encode_ms) // 2], 1), "snapshots": str(args.output)}))
  return 0


if __name__ == "__main__":
  sys.exit(main())
