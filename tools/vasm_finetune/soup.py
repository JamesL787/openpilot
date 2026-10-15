"""Uniform weight average ("model soup") of the same epoch across seeds, exported like train.py's models.

  python tools/vasm_finetune/soup.py --base /work/ft/vasm_converted.pt --out /work/ft/run11/soup_ep0.onnx \
      /work/ft/run11/s9/ep0.pt /work/ft/run11/s10/ep0.pt /work/ft/run11/s11/ep0.pt

All runs start from the same base at a small learning rate, so they stay in one basin and averaging their weights is
meaningful; it damps the seed-to-seed swing a single run shows (run9 seed 9 vs 10: 37 vs 27 test-323 frame FPs).
Float tensors (weights and BatchNorm running stats) are averaged; integer buffers (num_batches_tracked) come from the
first run. One model, so inference cost on the device is unchanged.
"""

import argparse
import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train import export  # noqa: E402


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--base", required=True, help="the converted base model train.py started from (architecture)")
  ap.add_argument("--out", required=True)
  ap.add_argument("states", nargs="+", help="ep<N>.pt state dicts from train.py --save-epochs")
  args = ap.parse_args()
  states = [torch.load(p, map_location="cpu") for p in args.states]
  avg = {}
  for k, v in states[0].items():
    avg[k] = torch.stack([s[k].float() for s in states]).mean(0).to(v.dtype) if v.is_floating_point() else v.clone()
  model = torch.load(args.base, weights_only=False, map_location="cpu")
  model.load_state_dict(avg)
  export(model, args.out, None)
  print(len(states), "runs ->", args.out)


if __name__ == "__main__":
  main()
