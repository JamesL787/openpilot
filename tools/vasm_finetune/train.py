"""Step 5: fine-tune the converted V-ASM model (convert.py) on the labelled TRAIN crops, then export ONNX for benchmark.py.

  python tools/vasm_finetune/train.py --out /work/ft/run1          (writes best.pt, vasm_ft.onnx, train_log.json)
  python tools/vasm_finetune/benchmark.py --model /work/ft/run1/vasm_ft.onnx --out cand.json

Data: manifest rows with split "train" and a 0/1/2 label in labels.json (x is left out). Test crops are never read, so
the benchmark stays held out. A truck part is a crop tagged "truck": true in labels.json (labeler key t, agent char t)
or listed in <crops>/truck_tags.json ({file: true}, agent tags on crops whose label is the owner's). The shipped
model handles trailers, containers and the rest of a cab badly (owner, 2026-10-13), so each truck crop is drawn
--truck-weight times as often as a crop of the same class. Classes are balanced first (each class drawn equally often
per epoch), because most crops are 0.

Validation: whole (route, segment) groups, --val-frac of them, chosen by a hash so the split is stable across runs and
neighbouring 4 Hz frames never straddle it. The best epoch by validation class-1 F0.5 at --on is kept.

The model ends in softmax, so the loss is NLL on log(probabilities). Augmentation is photometric only (brightness,
contrast) plus a few pixels of shift: no flips or crops, because where the lane line sits in the crop is the label.
"""

import argparse
import csv
import hashlib
import json
import os
import random

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler


def load_rows(crops):
  with open(os.path.join(crops, "manifest.csv")) as f:
    manifest = [r for r in csv.DictReader(f) if r["split"] == "train"]
  with open(os.path.join(crops, "labels.json")) as f:
    labels = json.load(f)
  side = os.path.join(crops, "truck_tags.json")
  tags = json.load(open(side)) if os.path.exists(side) else {}
  rows = []
  for r in manifest:
    e = labels.get(r["file"], {})
    if e.get("label") in (0, 1, 2):
      truck = bool(e.get("truck") or tags.get(r["file"])) and e["label"] != 0
      rows.append({"file": r["file"], "y": e["label"], "truck": truck, "group": f"{r['route']}/{r['seg']}"})
  return rows


def is_val(group, frac):
  return int(hashlib.sha1(group.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < frac


def sample_weights(rows, truck_weight):
  count = np.bincount([r["y"] for r in rows], minlength=3).astype(float)
  return [(1.0 / count[r["y"]]) * (truck_weight if r["truck"] else 1.0) for r in rows]


class Crops(Dataset):
  def __init__(self, crops, rows, augment):
    self.crops, self.rows, self.augment = crops, rows, augment

  def __len__(self):
    return len(self.rows)

  def __getitem__(self, k):
    r = self.rows[k]
    rgb = cv2.cvtColor(cv2.imread(os.path.join(self.crops, r["file"])), cv2.COLOR_BGR2RGB).astype(np.float32)
    if self.augment:
      rgb = rgb * random.uniform(0.75, 1.25) + random.uniform(-20, 20)
      rgb = (rgb - rgb.mean()) * random.uniform(0.8, 1.2) + rgb.mean()
      dx, dy = random.randint(-8, 8), random.randint(-8, 8)
      rgb = cv2.warpAffine(rgb, np.float32([[1, 0, dx], [0, 1, dy]]), (352, 352), borderMode=cv2.BORDER_REPLICATE)
      rgb = np.clip(rgb, 0, 255)
    return torch.from_numpy(rgb.transpose(2, 0, 1) / 255.0), r["y"]


def evaluate(model, loader, on):
  model.eval()
  ps, ys = [], []
  with torch.no_grad():
    for x, y in loader:
      ps.append(model(x.float()))
      ys.append(y)
  p, y = torch.cat(ps), torch.cat(ys)
  nll = torch.nn.functional.nll_loss(torch.log(p.clamp_min(1e-7)), y).item()
  pred, truth = p[:, 1] >= on, y == 1
  tp, fp, fn = int((pred & truth).sum()), int((pred & ~truth).sum()), int((~pred & truth).sum())
  prec, rec = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
  f05 = 1.25 * prec * rec / max(0.25 * prec + rec, 1e-9)
  return {"nll": nll, "precision": prec, "recall": rec, "f05": f05, "tp": tp, "fp": fp, "fn": fn}


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--base", default="/work/ft/vasm_converted.pt")
  ap.add_argument("--out", required=True)
  ap.add_argument("--epochs", type=int, default=8)
  ap.add_argument("--batch", type=int, default=32)
  ap.add_argument("--lr", type=float, default=1e-4)
  ap.add_argument("--truck-weight", type=float, default=4.0)
  ap.add_argument("--val-frac", type=float, default=0.1)
  ap.add_argument("--on", type=float, default=0.8)
  ap.add_argument("--seed", type=int, default=0)
  ap.add_argument("--limit", type=int, default=0, help="smoke test: use only this many train and val crops")
  args = ap.parse_args()
  random.seed(args.seed)
  torch.manual_seed(args.seed)
  os.makedirs(args.out, exist_ok=True)

  rows = load_rows(args.crops)
  tr = [r for r in rows if not is_val(r["group"], args.val_frac)]
  va = [r for r in rows if is_val(r["group"], args.val_frac)]
  if args.limit:
    tr, va = random.sample(tr, min(args.limit, len(tr))), random.sample(va, min(args.limit, len(va)))
  summary = {
    "train": len(tr), "val": len(va),
    "train_classes": np.bincount([r["y"] for r in tr], minlength=3).tolist(),
    "train_truck": sum(r["truck"] for r in tr),
  }
  print(summary, flush=True)
  if not tr or not va:
    raise SystemExit("not enough labelled train crops")

  sampler = WeightedRandomSampler(sample_weights(tr, args.truck_weight), num_samples=len(tr), replacement=True)
  train_loader = DataLoader(Crops(args.crops, tr, True), batch_size=args.batch, sampler=sampler, num_workers=4)
  val_loader = DataLoader(Crops(args.crops, va, False), batch_size=64, num_workers=4)

  model = torch.load(args.base, weights_only=False)
  opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
  sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
  log = {"args": vars(args), "data": summary, "base": evaluate(model, val_loader, args.on), "epochs": []}
  print("base", log["base"], flush=True)
  best = -1.0
  for ep in range(args.epochs):
    model.train()
    total = 0.0
    for x, y in train_loader:
      loss = torch.nn.functional.nll_loss(torch.log(model(x.float()).clamp_min(1e-7)), y)
      opt.zero_grad()
      loss.backward()
      opt.step()
      total += loss.item() * len(y)
    sched.step()
    v = evaluate(model, val_loader, args.on)
    log["epochs"].append({"epoch": ep, "train_nll": total / len(tr), "val": v})
    print(ep, round(total / len(tr), 4), v, flush=True)
    if v["f05"] > best:
      best = v["f05"]
      torch.save(model, os.path.join(args.out, "best.pt"))
    json.dump(log, open(os.path.join(args.out, "train_log.json"), "w"), indent=1)

  model = torch.load(os.path.join(args.out, "best.pt"), weights_only=False).eval()
  onnx_path = os.path.join(args.out, "vasm_ft.onnx")
  torch.onnx.export(model, torch.zeros(1, 3, 352, 352), onnx_path, input_names=["images"], output_names=["output0"], opset_version=17, dynamo=False)
  print("best val f05", best, "->", onnx_path)


if __name__ == "__main__":
  main()
