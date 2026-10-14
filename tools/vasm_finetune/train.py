"""Step 5: fine-tune the converted V-ASM model (convert.py) on the labelled TRAIN crops, then export ONNX for benchmark.py.

  python tools/vasm_finetune/train.py --out /work/ft/run1          (writes best.pt, vasm_ft.onnx, train_log.json)
  python tools/vasm_finetune/benchmark.py --model /work/ft/run1/vasm_ft.onnx --out cand.json

Data: manifest rows with split "train" and a 0/1/2 label in labels.json (x is left out). Test crops are never read, so
the benchmark stays held out. A truck part is a crop tagged "truck": true in labels.json (labeler key t, agent char t)
or listed in <crops>/truck_tags.json ({file: true}, agent tags on crops whose label is the owner's). The shipped
model handles trailers, containers and the rest of a cab badly (owner, 2026-10-13), so each truck crop is drawn
--truck-weight times as often as a crop of the same class. Classes are balanced first (each class drawn equally often
per epoch), because most crops are 0.

--hardneg adds agent-0 crops the model scored as car, each checked by eye (concrete barriers, night window
reflections: run3's new false-occupied time on test), to train only; validation stays owner-labelled.

--owner-only drops agent labels (entries with a `by`). The agents put the adjacent lane one dashed line too far out:
on the owner-relabelled test set, 107 of 201 crops the owner calls 2 were agent 1, and run1 (trained mostly on
agent labels) failed the benchmark gate by calling distant traffic adjacent.

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
import time

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler


def load_rows(crops, owner_only=False, hardneg=()):
  with open(os.path.join(crops, "manifest.csv")) as f:
    manifest = [r for r in csv.DictReader(f) if r["split"] == "train"]
  with open(os.path.join(crops, "labels.json")) as f:
    labels = json.load(f)
  side = os.path.join(crops, "truck_tags.json")
  tags = json.load(open(side)) if os.path.exists(side) else {}
  rows = []
  for r in manifest:
    e = labels.get(r["file"], {})
    if r["file"] in hardneg and e.get("label") == 0:
      rows.append({**_where(r), "file": r["file"], "y": 0, "truck": False, "group": f"{r['route']}/{r['seg']}", "hardneg": True})
    elif e.get("label") in (0, 1, 2) and not (owner_only and "by" in e):
      truck = bool(e.get("truck") or tags.get(r["file"])) and e["label"] != 0
      rows.append({**_where(r), "file": r["file"], "y": e["label"], "truck": truck, "group": f"{r['route']}/{r['seg']}"})
  return rows


def _where(r):
  return {"route": r["route"], "seg": r["seg"], "side": r["image_side"], "t": float(r["t"])}


def queue_segments(path):
  # (route suffix, seg) of every queue.json side: the owner's dense validation segments, kept out of training
  return {(s["route"], str(s["seg"])) for s in json.load(open(path))["sides"]}


def in_segments(r, segs):
  return any(r["route"].endswith(q) and r["seg"] == s for q, s in segs)


def drop_hardneg_near_cars(rows, crops, gap):
  """Hard negatives within `gap` s of a crop labelled 1 (anyone's label) on the same side are likely a car's first or
  last sliver, which the owner labels 1 (partial vehicles count); 124 of the 678 accepted ones were within 1 s."""
  with open(os.path.join(crops, "labels.json")) as f:
    labels = json.load(f)
  with open(os.path.join(crops, "manifest.csv")) as f:
    cars = {}
    for r in csv.DictReader(f):
      if labels.get(r["file"], {}).get("label") == 1:
        cars.setdefault((r["route"], r["seg"], r["image_side"]), []).append(float(r["t"]))
  def near(r):
    return any(abs(r["t"] - t) <= gap for t in cars.get((r["route"], r["seg"], r["side"]), ()))
  return [r for r in rows if not (r.get("hardneg") and near(r))]


def mark_onsets(rows, onset_s, frame_gap=0.6):
  """Flag class-1 rows in the first `onset_s` of their run (consecutive 1s on one side, gaps under frame_gap s)."""
  by_side = {}
  for r in rows:
    by_side.setdefault((r["route"], r["seg"], r["side"]), []).append(r)
  for side_rows in by_side.values():
    start, prev = None, None
    for r in sorted(side_rows, key=lambda r: r["t"]):
      if r["y"] != 1:
        start = None
      elif start is None or r["t"] - prev > frame_gap:
        start = r["t"]
      if r["y"] == 1:
        r["onset"] = r["t"] - start <= onset_s
        prev = r["t"]


def is_val(group, frac):
  return int(hashlib.sha1(group.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < frac


def sample_weights(rows, truck_weight, balance=1.0, onset_weight=1.0):
  # balance 1 = each class drawn equally often; 0 = natural frequency. Full balancing makes the model call "car" too
  # readily at the daemon's fixed --on threshold (run2: false-occupied 29 -> 45 s/h on the owner test labels).
  count = np.bincount([r["y"] for r in rows], minlength=3).astype(float)
  return [count[r["y"]] ** -balance * (truck_weight if r["truck"] else 1.0) * (onset_weight if r.get("onset") else 1.0)
          for r in rows]


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


def evaluate(model, loader, on, dev):
  model.eval()
  ps, ys = [], []
  with torch.no_grad():
    for x, y in loader:
      ps.append(model(x.float().to(dev)).cpu())
      ys.append(y)
  p, y = torch.cat(ps), torch.cat(ys)
  nll = torch.nn.functional.nll_loss(torch.log(p.clamp_min(1e-7)), y).item()
  pred, truth = p[:, 1] >= on, y == 1
  tp, fp, fn = int((pred & truth).sum()), int((pred & ~truth).sum()), int((~pred & truth).sum())
  prec, rec = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
  f05 = 1.25 * prec * rec / max(0.25 * prec + rec, 1e-9)
  fp2 = int((pred & (y == 2)).sum())  # distant traffic called adjacent: the run1 failure
  return {"nll": nll, "precision": prec, "recall": rec, "f05": f05, "tp": tp, "fp": fp, "fn": fn, "fp_from2": fp2}


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--base", default="/work/ft/vasm_converted.pt")
  ap.add_argument("--out", required=True)
  ap.add_argument("--epochs", type=int, default=8)
  ap.add_argument("--batch", type=int, default=32)
  ap.add_argument("--lr", type=float, default=1e-4)
  ap.add_argument("--truck-weight", type=float, default=4.0)
  ap.add_argument("--balance", type=float, default=1.0, help="class balancing exponent: 1 = equal draws per class, 0 = natural")
  ap.add_argument("--val-frac", type=float, default=0.1)
  ap.add_argument("--on", type=float, default=0.8)
  ap.add_argument("--owner-only", action="store_true", help="train and validate on the owner's labels only (no `by`)")
  ap.add_argument("--hardneg", default=None, help="json list of agent-0 crops checked by eye; added as 0 to TRAIN only")
  ap.add_argument("--exclude-queue", default=None, help="queue.json: its segments are never trained on (dense validation)")
  ap.add_argument("--hardneg-gap", type=float, default=0.0, help="drop hard negatives within this many s of a labelled car")
  ap.add_argument("--onset-weight", type=float, default=1.0, help="sampling weight on the first --onset-s of each car run")
  ap.add_argument("--onset-s", type=float, default=1.0)
  ap.add_argument("--save-epochs", action="store_true", help="also export ep<N>.onnx every epoch, for queue-based selection")
  ap.add_argument("--seed", type=int, default=0)
  ap.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu", help="mps = Apple GPU (native macOS), else cpu")
  ap.add_argument("--limit", type=int, default=0, help="smoke test: use only this many train and val crops")
  args = ap.parse_args()
  random.seed(args.seed)
  torch.manual_seed(args.seed)
  os.makedirs(args.out, exist_ok=True)

  rows = load_rows(args.crops, args.owner_only, set(json.load(open(args.hardneg))) if args.hardneg else ())
  segs = queue_segments(args.exclude_queue) if args.exclude_queue else set()
  if args.hardneg_gap > 0:
    rows = drop_hardneg_near_cars(rows, args.crops, args.hardneg_gap)
  mark_onsets(rows, args.onset_s)
  # queue segments stay out of training only; validation groups queued for dense labelling (tier A) remain validation
  tr = [r for r in rows if not is_val(r["group"], args.val_frac) and not in_segments(r, segs)]
  va = [r for r in rows if is_val(r["group"], args.val_frac) and not r.get("hardneg")]
  if args.limit:
    tr, va = random.sample(tr, min(args.limit, len(tr))), random.sample(va, min(args.limit, len(va)))
  summary = {
    "train": len(tr), "val": len(va),
    "train_classes": np.bincount([r["y"] for r in tr], minlength=3).tolist(),
    "train_truck": sum(r["truck"] for r in tr),
    "train_hardneg": sum(bool(r.get("hardneg")) for r in tr),
    "train_onset": sum(bool(r.get("onset")) for r in tr),
  }
  print(summary, flush=True)
  if not tr or not va:
    raise SystemExit("not enough labelled train crops")

  weights = sample_weights(tr, args.truck_weight, args.balance, args.onset_weight)
  sampler = WeightedRandomSampler(weights, num_samples=len(tr), replacement=True)
  train_loader = DataLoader(Crops(args.crops, tr, True), batch_size=args.batch, sampler=sampler, num_workers=4)
  val_loader = DataLoader(Crops(args.crops, va, False), batch_size=64, num_workers=4)

  dev = torch.device(args.device)
  model = torch.load(args.base, weights_only=False).to(dev)
  opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
  sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
  log = {"args": vars(args), "data": summary, "base": evaluate(model, val_loader, args.on, dev), "epochs": []}
  print("base", log["base"], flush=True)
  best = -1.0
  for ep in range(args.epochs):
    model.train()
    total, t0 = 0.0, time.time()
    for x, y in train_loader:
      x, y = x.float().to(dev), y.to(dev)
      loss = torch.nn.functional.nll_loss(torch.log(model(x).clamp_min(1e-7)), y)
      opt.zero_grad()
      loss.backward()
      opt.step()
      total += loss.item() * len(y)
    sched.step()
    secs = time.time() - t0
    v = evaluate(model, val_loader, args.on, dev)
    log["epochs"].append({"epoch": ep, "train_nll": total / len(tr), "train_s": round(secs, 1), "val": v})
    print(ep, round(total / len(tr), 4), f"{secs:.0f}s", v, flush=True)
    if v["f05"] > best:
      best = v["f05"]
      torch.save(model, os.path.join(args.out, "best.pt"))
    if args.save_epochs:
      export(model, os.path.join(args.out, f"ep{ep}.onnx"), dev)
    json.dump(log, open(os.path.join(args.out, "train_log.json"), "w"), indent=1)

  model = torch.load(os.path.join(args.out, "best.pt"), weights_only=False, map_location="cpu").eval()
  onnx_path = os.path.join(args.out, "vasm_ft.onnx")
  export(model, onnx_path, None)
  print("best val f05", best, "->", onnx_path)


def export(model, path, dev):
  m = model.to("cpu").eval()
  torch.onnx.export(m, torch.zeros(1, 3, 352, 352), path, input_names=["images"], output_names=["output0"], opset_version=17, dynamo=False)
  if dev is not None:
    model.to(dev)


if __name__ == "__main__":
  main()
