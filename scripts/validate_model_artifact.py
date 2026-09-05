#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from tinygrad.tensor import Tensor

from openpilot.common.params import Params
from openpilot.selfdrive.modeld.modeld import ModelState, _validate_external_gpu_outputs


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--model", required=True)
  parser.add_argument("--version", required=True)
  parser.add_argument("--artifact", type=Path, help="Validate this candidate PKL without installing or selecting it.")
  parser.add_argument("--external-gpu", action="store_true", help="Load the candidate on the external AMD GPU.")
  parser.add_argument("--camera-resolution", default="1928x1208")
  args = parser.parse_args()
  cam_w, cam_h = (int(value) for value in args.camera_resolution.split("x", 1))

  if args.artifact is None:
    params = Params()
    params.put("Model", args.model)
    params.put("DrivingModel", args.model)
    params.put("ModelVersion", args.version)
    params.put("DrivingModelVersion", args.version)

  model = ModelState(
    cam_w,
    cam_h,
    external_gpu_active=args.external_gpu,
    model_id_override=args.model,
    write_model_version=args.artifact is None,
    artifact_path_override=args.artifact,
  )
  model.npy["tfm"][:] = np.eye(3, dtype=np.float32)
  model.npy["big_tfm"][:] = np.eye(3, dtype=np.float32)
  for key, value in model.npy.items():
    if key not in ("tfm", "big_tfm"):
      value[:] = 0
  if "traffic_convention" in model.npy:
    model.npy["traffic_convention"][:] = [1, 0]
  if "action_t" in model.npy:
    model.npy["action_t"][:] = [0.15, 0.25]

  if model.fused:
    rng = np.random.default_rng(42)
    for frame in model.frame_views.values():
      frame[:] = rng.integers(0, 256, size=frame.shape, dtype=np.uint8)
    outputs = model.run_model(**{key: model.input_queues[key] for key in model.model_input_keys})
  else:
    frames = [
      Tensor.randint(model.frame_buf_size, low=0, high=256, dtype="uint8", device=model.WARP_DEV).realize()
      for _ in range(2)
    ]
    warped = model.warp_enqueue(
      **{key: model.input_queues[key] for key in model.warp_input_keys},
      frame=frames[0],
      big_frame=frames[1],
    )
    policy_inputs = {key: model.input_queues[key] for key in model.policy_input_keys}
    if model.image_history_pipeline == "policy":
      outputs = model.run_policy(**policy_inputs, warped=warped)
    else:
      outputs = model.run_policy(**policy_inputs, img=warped[0], big_img=warped[1])
  arrays = [output.numpy().flatten() for output in outputs]
  if model.uses_external_gpu:
    _validate_external_gpu_outputs(arrays)
  if model.model_type == "supercombo":
    parsed = model.parser.parse_outputs(model.slice_outputs(arrays[0], model.output_slices))
  else:
    parsed = model._parse_split_outputs(arrays)

  required = ("plan", "lane_lines", "lane_lines_prob", "road_edges", "lead", "lead_prob", "pose")
  missing = [key for key in required if key not in parsed]
  non_finite = [key for key, value in parsed.items() if isinstance(value, np.ndarray) and not np.isfinite(value).all()]
  has_control_output = "action" in parsed or "desired_curvature" in parsed or "plan" in parsed
  result = {
    "id": args.model,
    "version": args.version,
    "model_type": model.model_type,
    "policy_order": model.policy_order,
    "parsed_inputs": sorted(model.numpy_inputs),
    "output_sizes": [value.size for value in arrays],
    "output_shapes": {
      key: list(parsed[key].shape)
      for key in required
      if key in parsed
    },
    "missing": missing,
    "non_finite": non_finite,
    "has_control_output": has_control_output,
  }
  print(json.dumps(result))
  if missing or non_finite or not has_control_output:
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
