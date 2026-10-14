"""Pick a candidate's epoch and daemon threshold on the owner's dense queue sides (queue.json), never on the test set.

  python tools/vasm_finetune/select_queue.py --models /work/ft/run6/ep*.onnx --out /work/ft/run6_select.json

Validation = owner-labelled crops of every queue.json side; train.py --exclude-queue keeps those segments out of training.
The shipped model at the daemon's 0.8 / 0.65 is the reference, all scored with the D-122 night gate. Rule, fixed before
looking: a (model, on) qualifies if its missed events and false-occupied s/h are no worse than the reference and its
median latency is within the benchmark's slack of it; among those, the lowest on (the test-set failure was slow onset, and
the queue's 8 long events cannot rank latency: every candidate scored p50 0.26 s), then lowest false-occupied, then latency. off keeps the shipped gap, on - 0.15. Then benchmark.py --on/--off judges the pick on test, once.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from benchmark import LATENCY_SLACK, default_model, event_scores, infer, night_gate  # noqa: E402

GAP = 0.15
ONS = np.round(np.arange(0.70, 0.991, 0.01), 2)


def queue_rows(crops):
  sides = json.load(open(os.path.join(crops, "queue.json")))["sides"]
  with open(os.path.join(crops, "labels.json")) as f:
    labels = json.load(f)
  with open(os.path.join(crops, "manifest.csv")) as f:
    manifest = list(csv.DictReader(f))
  rows = []
  for r in manifest:
    e = labels.get(r["file"], {})
    if "by" in e or e.get("label") not in (0, 1, 2):
      continue
    if any(r["route"].endswith(s["route"]) and r["seg"] == str(s["seg"]) and r["image_side"] == s["side"] for s in sides):
      rows.append({**r, "y": e["label"]})
  return rows


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--models", nargs="+", required=True)
  ap.add_argument("--out", default=None)
  args = ap.parse_args()

  rows = queue_rows(args.crops)
  print(len(rows), "queue crops,", sum(r["y"] == 1 for r in rows), "car", flush=True)
  ref = event_scores(rows, night_gate(rows, infer(default_model(), args.crops, rows)[:, 1]), 0.8, 0.65)
  print(f"reference  0.80  events {ref['events']} missed {ref['missed']} false-occ {ref['false_occupied_s_per_h']:.1f} "
        f"p50 {ref['latency_p50']:.2f}  sides {ref['segment_sides_used']} (skipped {ref['segment_sides_skipped']})")

  def ok(e):
    return (e["missed"] <= ref["missed"] and e["false_occupied_s_per_h"] <= ref["false_occupied_s_per_h"]
            and e["latency_p50"] <= ref["latency_p50"] + LATENCY_SLACK)

  results = []
  for model in args.models:
    p = night_gate(rows, infer(model, args.crops, rows)[:, 1])
    for on in ONS:
      e = event_scores(rows, p, float(on), float(on) - GAP)
      results.append({"model": model, "on": float(on), "off": round(float(on) - GAP, 3), "events": e, "ok": ok(e)})
      if on in (0.70, 0.80, 0.90) or ok(e):
        print(f"{os.path.basename(model):12s} on {on:.2f}  missed {e['missed']} false-occ {e['false_occupied_s_per_h']:5.1f} "
              f"p50 {e['latency_p50']:.2f}{'  ok' if ok(e) else ''}", flush=True)
  good = [r for r in results if r["ok"]]
  pick = min(good, key=lambda r: (r["on"], r["events"]["false_occupied_s_per_h"], r["events"]["latency_p50"])) if good else None
  print("PICK", f"{pick['model']} on {pick['on']:.2f} off {pick['off']:.2f}" if pick else "none: nothing matches the reference")
  if args.out:
    json.dump({"reference": ref, "results": results, "pick": pick}, open(args.out, "w"), indent=1)


if __name__ == "__main__":
  main()
