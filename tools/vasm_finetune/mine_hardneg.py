"""Hard-negative candidates for train.py --hardneg: agent-labelled 0 TRAIN crops (outside the validation groups) that a
model scores as car, written as 4x4 contact sheets for an eye check. Crops that turn out to show an adjacent car are
dropped from the list by hand before training; the agents' 0 agreed with the owner on 96% of test crops, not 100%.

  python tools/vasm_finetune/mine_hardneg.py --model /work/ft/run3/vasm_ft.onnx --out /work/hardneg
    -> <out>/cand.json (file, p_car, highest first), <out>/sheet_NNNN.jpg, <out>/index.json
"""

import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from benchmark import infer  # noqa: E402
from train import is_val  # noqa: E402


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--model", required=True)
  ap.add_argument("--out", required=True)
  ap.add_argument("--min-p", type=float, default=0.5)
  ap.add_argument("--val-frac", type=float, default=0.1)
  args = ap.parse_args()
  os.makedirs(args.out, exist_ok=True)

  with open(os.path.join(args.crops, "labels.json")) as f:
    labels = json.load(f)
  with open(os.path.join(args.crops, "manifest.csv")) as f:
    rows = [r for r in csv.DictReader(f) if r["split"] == "train" and labels.get(r["file"], {}).get("label") == 0
            and "by" in labels[r["file"]] and not is_val(f"{r['route']}/{r['seg']}", args.val_frac)]
  print(len(rows), "agent-0 train crops", flush=True)
  p = infer(args.model, args.crops, rows)[:, 1]
  cand = sorted(((r["file"], float(q)) for r, q in zip(rows, p) if q >= args.min_p), key=lambda c: -c[1])
  json.dump(cand, open(os.path.join(args.out, "cand.json"), "w"), indent=0)
  idx = {}
  for s in range(0, len(cand), 16):
    sheet = np.zeros((4 * 352, 4 * 352, 3), np.uint8)
    for k, (f, q) in enumerate(cand[s:s + 16]):
      y, x = (k // 4) * 352, (k % 4) * 352
      sheet[y:y + 352, x:x + 352] = cv2.imread(os.path.join(args.crops, f))
      cv2.putText(sheet, f"{k} {q:.2f}", (x + 6, y + 34), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 2)
    name = f"sheet_{s // 16:04d}.jpg"
    cv2.imwrite(os.path.join(args.out, name), cv2.resize(sheet, (1056, 1056)), [cv2.IMWRITE_JPEG_QUALITY, 85])
    idx[name] = [f for f, _ in cand[s:s + 16]]
  json.dump(idx, open(os.path.join(args.out, "index.json"), "w"))
  print(len(cand), "candidates at p_car >=", args.min_p, "->", len(idx), "sheets")


if __name__ == "__main__":
  main()
