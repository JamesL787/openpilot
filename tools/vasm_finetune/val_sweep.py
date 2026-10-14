"""Pick a candidate's daemon on/off threshold on VALIDATION crops, never on the test set (owner, 2026-10-13).

  python tools/vasm_finetune/val_sweep.py --model /work/ft/run3/vasm_ft.onnx

Validation = the owner-labelled train-split crops in train.py's validation groups (same hash, --val-frac). The shipped
model at the daemon's 0.8 / 0.65 is the reference. Rule, fixed before looking: the chosen on is the LOWEST on in the
sweep whose validation false-occupied s/h and missed events are both no worse than the reference (frame fp when the
event scorer has no usable segment sides). off keeps the shipped gap, on - 0.15. Then benchmark.py --on/--off judges it
on test, once.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from benchmark import default_model, event_scores, frame_scores, infer  # noqa: E402
from train import is_val  # noqa: E402

GAP = 0.15


def val_rows(crops, frac):
  with open(os.path.join(crops, "manifest.csv")) as f:
    manifest = [r for r in csv.DictReader(f) if r["split"] == "train"]
  with open(os.path.join(crops, "labels.json")) as f:
    labels = json.load(f)
  rows = []
  for r in manifest:
    e = labels.get(r["file"], {})
    if "by" not in e and e.get("label") in (0, 1, 2) and is_val(f"{r['route']}/{r['seg']}", frac):
      rows.append({**r, "y": e["label"]})
  return rows


def score(rows, p_car, on):
  y_car = np.array([r["y"] == 1 for r in rows])
  return {"on": on, "off": round(on - GAP, 3), "frame": frame_scores(y_car, p_car, on), "events": event_scores(rows, p_car, on, on - GAP)}


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--model", required=True)
  ap.add_argument("--base", default=None, help="reference model (default: the shipped one)")
  ap.add_argument("--val-frac", type=float, default=0.1)
  ap.add_argument("--out", default=None)
  args = ap.parse_args()

  rows = val_rows(args.crops, args.val_frac)
  print(len(rows), "validation crops,", sum(r["y"] == 1 for r in rows), "car", flush=True)
  ref = score(rows, infer(args.base or default_model(), args.crops, rows)[:, 1], 0.8)
  p = infer(args.model, args.crops, rows)[:, 1]
  sweep = [score(rows, p, on) for on in np.round(np.arange(0.70, 0.991, 0.01), 2)]
  use_events = ref["events"]["segment_sides_used"] > 0

  def ok(s):
    if use_events:
      return (s["events"]["false_occupied_s_per_h"] <= ref["events"]["false_occupied_s_per_h"]
              and s["events"]["missed"] <= ref["events"]["missed"])
    return s["frame"]["fp"] <= ref["frame"]["fp"]

  def line(name, s):
    f, e = s["frame"], s["events"]
    print(f"{name:10s} on {s['on']:.2f} off {s['off']:.2f}  fp {f['fp']:4d} fn {f['fn']:4d} f0.5 {f['f0_5']:.3f}  "
          f"events {e['events']} missed {e['missed']} false-occ {e['false_occupied_s_per_h']:.1f} s/h")

  line("reference", ref)
  for s in sweep:
    line("candidate" + (" ok" if ok(s) else ""), s)
  pick = next((s for s in sweep if ok(s)), None)
  print("scored by", "events" if use_events else "frame fp (no segment side >= 95% labelled)")
  print("PICK", f"on {pick['on']:.2f} off {pick['off']:.2f}" if pick else "none: no threshold matches the reference")
  if args.out:
    json.dump({"reference": ref, "sweep": sweep, "pick": pick, "scored_by_events": use_events}, open(args.out, "w"), indent=1)


if __name__ == "__main__":
  main()
