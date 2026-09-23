#!/usr/bin/env python3
"""Build the camera-warp companion for Comma upstream-precompiled models."""
import argparse
import pickle
from typing import NamedTuple

import numpy as np
from tinygrad import Context, Device, Tensor
from tinygrad.engine.jit import TinyJit


class NV12Frame(NamedTuple):
  width: int
  height: int
  stride: int
  y_height: int
  uv_height: int
  size: int


def parse_frame(value):
  return NV12Frame(*map(int, value.split(",")))


def parse_size(value):
  return tuple(map(int, value.lower().split("x")))


def warp_perspective_tinygrad(src_flat, matrix_inverse, dst_shape, src_shape, stride_pad, border_fill_val=None):
  dst_w, dst_h = dst_shape
  src_h, src_width = src_shape

  x = Tensor.arange(dst_w).reshape(1, dst_w).expand(dst_h, dst_w).reshape(-1)
  y = Tensor.arange(dst_h).reshape(dst_h, 1).expand(dst_h, dst_w).reshape(-1)
  src_x = matrix_inverse[0, 0] * x + matrix_inverse[0, 1] * y + matrix_inverse[0, 2]
  src_y = matrix_inverse[1, 0] * x + matrix_inverse[1, 1] * y + matrix_inverse[1, 2]
  projective_w = matrix_inverse[2, 0] * x + matrix_inverse[2, 1] * y + matrix_inverse[2, 2]

  x_round = Tensor.round(src_x / projective_w)
  y_round = Tensor.round(src_y / projective_w)
  x_clipped = x_round.clip(0, src_width - 1).cast("int")
  y_clipped = y_round.clip(0, src_h - 1).cast("int")
  sampled = src_flat[y_clipped * (src_width + stride_pad) + x_clipped]
  if border_fill_val is None:
    return sampled

  in_bounds = ((x_round >= 0) & (x_round <= src_width - 1) & (y_round >= 0) & (y_round <= src_h - 1)).cast(sampled.dtype)
  return sampled * in_bounds + Tensor(border_fill_val, dtype=sampled.dtype) * (1 - in_bounds)


def frames_to_tensor(frames):
  height = (frames.shape[0] * 2) // 3
  width = frames.shape[1]
  return Tensor.cat(
    frames[0:height:2, 0::2],
    frames[1:height:2, 0::2],
    frames[0:height:2, 1::2],
    frames[1:height:2, 1::2],
    frames[height:height + height // 4].reshape((height // 2, width // 2)),
    frames[height + height // 4:height + height // 2].reshape((height // 2, width // 2)),
    dim=0,
  ).reshape((6, height // 2, width // 2))


def make_frame_prepare(frame: NV12Frame, model_w: int, model_h: int):
  cam_w, cam_h, stride, y_height, uv_height, _ = frame
  uv_offset = stride * y_height
  stride_pad = stride - cam_w

  def frame_prepare(input_frame, matrix_inverse):
    matrix_inverse = matrix_inverse.to(Device.DEFAULT).realize()
    matrix_inverse_uv = matrix_inverse * Tensor(
      [[1.0, 1.0, 0.5], [1.0, 1.0, 0.5], [2.0, 2.0, 1.0]], device=Device.DEFAULT,
    )
    uv = input_frame[uv_offset:uv_offset + uv_height * stride].reshape(uv_height, stride)
    with Context(SPLIT_REDUCEOP=0):
      y = warp_perspective_tinygrad(
        input_frame[:cam_h * stride], matrix_inverse, (model_w, model_h), (cam_h, cam_w), stride_pad,
      ).realize()
      u = warp_perspective_tinygrad(
        uv[:cam_h // 2, :cam_w:2].flatten(), matrix_inverse_uv,
        (model_w // 2, model_h // 2), (cam_h // 2, cam_w // 2), 0,
      ).realize()
      v = warp_perspective_tinygrad(
        uv[:cam_h // 2, 1:cam_w:2].flatten(), matrix_inverse_uv,
        (model_w // 2, model_h // 2), (cam_h // 2, cam_w // 2), 0,
      ).realize()
    return frames_to_tensor(y.cat(u).cat(v).reshape((model_h * 3 // 2, model_w)))

  return frame_prepare


def make_luma_warp(frame: NV12Frame, width: int, height: int, border_fill=None):
  def warp(input_frame, matrix_inverse):
    matrix_inverse = matrix_inverse.to(Device.DEFAULT).realize()
    return warp_perspective_tinygrad(
      input_frame[:frame.height * frame.stride], matrix_inverse,
      (width, height), (frame.height, frame.width), frame.stride - frame.width,
      border_fill_val=border_fill,
    ).reshape(-1, height * width)

  return warp


def compile_warp(frame: NV12Frame, output_size, *, layout="luma", border_fill=None, frames=1,
                 transform_device=None, benchmark_runs=20):
  if frames < 1 or benchmark_runs < 1:
    raise ValueError("frames and benchmark_runs must be positive")
  if layout == "luma":
    function = make_luma_warp(frame, *output_size, border_fill)
  elif layout == "yuv420":
    function = make_frame_prepare(frame, *output_size)
  else:
    raise ValueError(f"Unknown warp layout: {layout}")

  prefix = () if frames == 1 else (frames,)
  transform_device = transform_device or Device.DEFAULT
  input_specs = {
    "input_frame": (prefix + (frame.size,), np.dtype(np.uint8).str, Device.DEFAULT),
    "M_inv": (prefix + (3, 3), np.dtype(np.float32).str, transform_device),
  }

  def run(input_frame, M_inv):
    if frames == 1:
      return function(input_frame, M_inv)
    return Tensor.stack(*(function(input_frame[index], M_inv[index]) for index in range(frames)))

  jit = TinyJit(run, prune=True)
  output = None
  for _ in range(max(3, benchmark_runs)):
    input_frame = Tensor.randint(input_specs["input_frame"][0], low=0, high=256, dtype="uint8", device=Device.DEFAULT)
    matrix_inverse = Tensor.randn(input_specs["M_inv"][0], device=transform_device).mul(8)
    Device.default.synchronize()
    output = jit(input_frame, matrix_inverse)
    Tensor.realize(output)
    Device.default.synchronize()

  expected_shape = None
  if layout == "yuv420":
    expected_shape = (6, output_size[1] // 2, output_size[0] // 2)
    if frames > 1:
      expected_shape = (frames, *expected_shape)
  if expected_shape is not None and output.shape != expected_shape:
    raise ValueError(f"Compiled warp returned {output.shape}; expected {expected_shape}")
  return {"metadata": {}, "run": jit, "input_specs": input_specs}


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--frame", type=parse_frame, required=True,
                      help="width,height,stride,y_height,uv_height,buffer_size")
  parser.add_argument("--warp-to", type=parse_size, required=True)
  parser.add_argument("--layout", choices=("luma", "yuv420"), default="luma")
  parser.add_argument("--border-fill", type=int)
  parser.add_argument("--frames", type=int, default=1)
  parser.add_argument("--transform-device")
  parser.add_argument("--output", required=True)
  parser.add_argument("--benchmark-runs", type=int, default=20)
  args = parser.parse_args()

  artifact = compile_warp(
    args.frame, args.warp_to, layout=args.layout, border_fill=args.border_fill,
    frames=args.frames, transform_device=args.transform_device, benchmark_runs=args.benchmark_runs,
  )
  with open(args.output, "wb") as artifact_file:
    pickle.dump(artifact, artifact_file)
  print(f"saved {args.output}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
