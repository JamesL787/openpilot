#!/usr/bin/env python3
"""Check the car renderer's GPU NV12 conversion and readback paths on the comma.

  cd /data/openpilot && PYTHONPATH=/data/openpilot python3 tools/starpilot_auto/nv12_check.py

Draws random colours into an offscreen frame, reads it back as RGBA and as NV12
(converted on the GPU, read back both synchronously and asynchronously), and
requires the NV12 to match the CPU reference byte for byte. Then times each
readback path. Needs no car and changes no settings.
"""

import argparse
import json
import sys
import time

import numpy as np

from openpilot.starpilot.system.starpilot_auto.gpu_nv12 import Nv12Converter, reference_nv12
from openpilot.starpilot.system.starpilot_auto.headless_egl import FrameReadback, HeadlessContext

RGBA8 = 7  # PIXELFORMAT_UNCOMPRESSED_R8G8B8A8


def read(readback: FrameReadback, regions) -> bytes:
  readback.start(regions)
  try:
    return bytes(readback.finish())
  finally:
    readback.release()


def timed(readback: FrameReadback, regions, convert, iterations: int) -> dict:
  waits, starts, finishes = [], [], []
  for _ in range(iterations):
    readback.gpu_finish()
    began = time.monotonic()
    regions = convert() or regions
    readback.start(regions)
    started = time.monotonic()
    readback.finish()
    readback.release()
    finished = time.monotonic()
    waits.append(finished - began)
    starts.append(started - began)
    finishes.append(finished - started)
  def median(values):
    return round(sorted(values)[len(values) // 2] * 1000, 2)
  return {"total_ms": median(waits), "start_ms": median(starts), "finish_ms": median(finishes)}


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--width", type=int, default=1280)
  parser.add_argument("--height", type=int, default=720)
  parser.add_argument("--iterations", type=int, default=60)
  args = parser.parse_args()
  width, height = args.width, args.height
  context = HeadlessContext(width, height)
  import pyray as rl
  pixels = np.random.default_rng(1).integers(0, 256, (height, width, 4), dtype=np.uint8)
  pixels[..., 3] = 255
  buffer = rl.ffi.from_buffer(pixels)
  texture_id = rl.rl_load_texture(rl.ffi.cast("void *", buffer), width, height, RGBA8, 1)
  source = rl.Texture(texture_id, width, height, 1, RGBA8)
  frame = rl.load_render_texture(width, height)
  rl.begin_texture_mode(frame)
  rl.clear_background(rl.BLACK)
  rl.draw_texture_pro(source, rl.Rectangle(0, 0, width, height), rl.Rectangle(0, 0, width, height), rl.Vector2(0, 0), 0.0, rl.WHITE)
  rl.end_texture_mode()
  converter = Nv12Converter(width, height)
  rgba_regions = [(frame.id, width, height, 0)]
  nv12_size = width * height * 3 // 2
  results: dict = {}
  try:
    rgba = read(FrameReadback(width * height * 4), rgba_regions)
    expected = np.frombuffer(reference_nv12(rgba, width, height), np.uint8)
    nv12_regions = converter.convert(frame.texture)
    for mode, asynchronous in (("sync", False), ("async", True)):
      got = np.frombuffer(read(FrameReadback(nv12_size, asynchronous), nv12_regions), np.uint8)
      difference = np.abs(got.astype(np.int16) - expected.astype(np.int16))
      results[f"nv12_{mode}"] = {"mismatched_bytes": int(np.count_nonzero(difference)), "max_difference": int(difference.max())}
    results["timing_rgba_sync"] = timed(FrameReadback(width * height * 4), rgba_regions, lambda: None, args.iterations)
    results["timing_rgba_async"] = timed(FrameReadback(width * height * 4, True), rgba_regions, lambda: None, args.iterations)
    def convert():
      return converter.convert(frame.texture)
    results["timing_nv12_sync"] = timed(FrameReadback(nv12_size), nv12_regions, convert, args.iterations)
    results["timing_nv12_async"] = timed(FrameReadback(nv12_size, True), nv12_regions, convert, args.iterations)
  finally:
    converter.close()
    rl.unload_render_texture(frame)
    rl.rl_unload_texture(texture_id)
    context.close()
  passed = all(results[f"nv12_{mode}"]["mismatched_bytes"] == 0 for mode in ("sync", "async"))
  print(json.dumps({"result": "pass" if passed else "fail", **results}, indent=2))
  return 0 if passed else 1


if __name__ == "__main__":
  sys.exit(main())
