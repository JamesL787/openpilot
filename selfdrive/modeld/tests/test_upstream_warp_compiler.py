import pickle

import numpy as np
from tinygrad import Context, Tensor

from openpilot.selfdrive.modeld.compile_upstream_warp import NV12Frame, compile_warp


def test_upstream_warp_compiles_and_round_trips_yuv420_artifact():
  frame = NV12Frame(width=16, height=16, stride=16, y_height=16, uv_height=8, size=384)
  with Context(DEV="CPU"):
    artifact = compile_warp(
      frame,
      (8, 8),
      layout="yuv420",
      frames=2,
      transform_device="CPU",
      benchmark_runs=1,
    )

  assert artifact["input_specs"] == {
    "input_frame": ((2, 384), "|u1", "CPU"),
    "M_inv": ((2, 3, 3), "<f4", "CPU"),
  }
  restored = pickle.loads(pickle.dumps(artifact))
  with Context(DEV="CPU"):
    frames = Tensor.randint((2, 384), low=0, high=256, dtype="uint8", device="CPU").realize()
    transforms = Tensor(np.repeat(np.eye(3, dtype=np.float32)[None], 2, axis=0)).realize()
    output = restored["run"](frames, transforms)
    assert output.shape == (2, 6, 4, 4)
    output.realize()
