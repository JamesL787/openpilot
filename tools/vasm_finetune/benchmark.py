"""Step 4: the frozen V-ASM benchmark. Scores a model on the hand-labelled test crops (labeler.py, split "test").

  python tools/vasm_finetune/benchmark.py --model <file.onnx> --out base.json        (default model: the shipped one)
  python tools/vasm_finetune/benchmark.py --compare base.json cand.json

The model runs on the saved PNGs (bit-identical to the daemon's input blob) through cv2.dnn, the daemon's runtime.
"car" means class 1, the only class the daemon publishes; classes 0 and 2 are both "not car". Unsure labels (x) are
left out.

Frame level, at the on threshold: precision, recall, F0.5 (the upstream author's precision-weighted score), false
positives, and the 3-class confusion. The same is reported for the subsets night (mean_luma < 40), pass_hold, radar
within 8 m, and each route. A sweep over on-thresholds shows what a threshold change alone would buy.

Event level, the daemon's sampling: one side per 1 s, alternating; 0.3 s for 1 s after any occupied; on/off
hysteresis. Each segment is simulated with both sides on the 4 Hz crop clock (the daemon's sample time snaps to the
nearest crop, at most 0.125 s off). Truth events are runs of "car" labels (gaps up to 0.5 s merged) lasting at least 0.5 s. Missed = never
published from its start to 1 s after its end; latency = first published - start; false-occupied = published while
the label is not car and no car label is within 1 s, per hour per side. Only segment sides labelled >= 95 % count.

The output JSON records the manifest and labels hashes; --compare refuses two runs on different test sets.
Runs at different --on/--off compare fine: that is how a threshold-only change is judged. The gate
(candidate no worse) is: missed <=, false-occupied/h <=, median latency <= baseline + 0.125 s (one crop period).
"""

import argparse
import csv
import hashlib
import json
import os
import sys

import cv2
import numpy as np

NIGHT_LUMA = 40.0
RADAR_NEAR_M = 8.0
LABELLED_MIN = 0.95
MERGE_GAP = 0.5
SWEEP = (0.3, 0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
LATENCY_SLACK = 0.125
MIN_EVENT_S = 0.5  # shorter car runs are counted apart: 1 s per-side sampling cannot be expected to see them


def sha(path):
  with open(path, "rb") as f:
    return hashlib.sha256(f.read()).hexdigest()


def frame_scores(y_car, p_car, on):
  pred = p_car >= on
  tp, fp, fn = int(np.sum(pred & y_car)), int(np.sum(pred & ~y_car)), int(np.sum(~pred & y_car))
  p = tp / (tp + fp) if tp + fp else float("nan")
  r = tp / (tp + fn) if tp + fn else float("nan")
  f05 = 1.25 * p * r / (0.25 * p + r) if tp else 0.0
  return {"n": int(len(y_car)), "cars": int(y_car.sum()), "precision": p, "recall": r, "f0_5": f05, "fp": fp, "fn": fn}


def runs(t, mask, gap):
  out, start, last = [], None, None
  for ti, m in zip(t, mask, strict=True):
    if m:
      if start is not None and ti - last > gap + 1e-6:
        out.append((start, last))
        start = None
      start = ti if start is None else start
      last = ti
  if start is not None:
    out.append((start, last))
  return out


def simulate(t, p, on, off):
  """Daemon sampling over one segment. t: crop times; p: {image_side: p_car per crop}. Returns {image_side: published}."""
  pub = {s: np.zeros(len(t), bool) for s in p}
  act = dict.fromkeys(p, False)
  side, last, follow = "left", -1e9, -1e9
  for i, ti in enumerate(t):
    interval = 0.3 if ti < follow else 1.0
    if ti - last >= interval - 0.13:  # a crop every 0.25 s: take the first one at or past the due time
      if side in p:
        c = p[side][i]
        act[side] = c >= (off if act[side] else on)
        if any(act.values()):
          follow = ti + 1.0
      last = ti
      side = "right" if side == "left" else "left"
    for s in p:
      pub[s][i] = act[s]
  return pub


def event_scores(rows, p_car, on, off):
  by_seg = {}
  for k, r in enumerate(rows):
    by_seg.setdefault((r["route"], r["seg"]), []).append(k)
  missed, total, short, lat, false_s, side_s, used, skipped = 0, 0, 0, [], 0.0, 0.0, 0, 0
  for idx in by_seg.values():
    times = sorted({float(rows[k]["t"]) for k in idx})
    pos = {t: n for n, t in enumerate(times)}
    t = np.array(times)
    p = {}
    lab = {}
    for side in ("left", "right"):
      ks = [k for k in idx if rows[k]["image_side"] == side]
      if not ks:
        continue
      p[side] = np.zeros(len(t))
      lab[side] = np.full(len(t), -1)
      for k in ks:
        p[side][pos[float(rows[k]["t"])]] = p_car[k]
        lab[side][pos[float(rows[k]["t"])]] = rows[k]["y"]
    pub = simulate(t, p, on, off)
    dt = np.median(np.diff(t)) if len(t) > 1 else 0.25
    for side in p:
      if np.mean(lab[side] >= 0) < LABELLED_MIN:
        skipped += 1
        continue
      used += 1
      car = lab[side] == 1
      side_s += len(t) * dt
      for a, b in runs(t, car, MERGE_GAP):
        if b - a < MIN_EVENT_S:
          short += 1
          continue
        total += 1
        hit = t[(t >= a) & (t <= b + 1.0) & pub[side]]
        if len(hit):
          lat.append(float(hit[0] - a))
        else:
          missed += 1
      near_car = np.array([np.any(car & (np.abs(t - ti) <= 1.0)) for ti in t])
      false_s += float(np.sum(pub[side] & (lab[side] >= 0) & ~car & ~near_car)) * dt
  return {
    "events": total,
    "missed": missed,
    "short_events": short,
    "latency_p50": float(np.median(lat)) if lat else float("nan"),
    "latency_p90": float(np.percentile(lat, 90)) if lat else float("nan"),
    "false_occupied_s_per_h": false_s / side_s * 3600.0 if side_s else float("nan"),
    "side_hours": side_s / 3600.0,
    "segment_sides_used": used,
    "segment_sides_skipped": skipped,
  }


# starpilot/system/adj_spot_monitor_vision.py DARK_LUMA_ENTER / DARK_LUMA_EXIT (D-122); mean_luma is the same measure
DARK_LUMA_ENTER, DARK_LUMA_EXIT = 30.0, 40.0


def night_gate(rows, p_car):
  """The daemon's D-122 night gate: on a dark side the camera verdict is dropped (p_car 0), hysteresis per side."""
  p = np.array(p_car, dtype=np.float64)
  by_side = {}
  for k, r in enumerate(rows):
    by_side.setdefault((r["route"], r["seg"], r["image_side"]), []).append(k)
  for ks in by_side.values():
    dark = False
    for k in sorted(ks, key=lambda k: float(rows[k]["t"])):
      luma = float(rows[k]["mean_luma"])
      dark = luma <= DARK_LUMA_EXIT if dark else luma < DARK_LUMA_ENTER
      if dark:
        p[k] = 0.0
  return p


def infer(model_path, crops, rows):
  net = cv2.dnn.readNetFromONNX(model_path)
  out = np.zeros((len(rows), 3), np.float32)
  for k, r in enumerate(rows):
    bgr = cv2.imread(os.path.join(crops, r["file"]))
    if bgr is None:
      sys.exit(f"cannot read crop {os.path.join(crops, r['file'])}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    net.setInput(np.expand_dims(rgb.astype(np.float32).transpose(2, 0, 1) / 255.0, 0))
    out[k] = np.squeeze(net.forward())
  return out


def run(args):
  manifest, labels_path = os.path.join(args.crops, "manifest.csv"), os.path.join(args.crops, "labels.json")
  with open(manifest) as f:
    allrows = [r for r in csv.DictReader(f) if r["split"] == "test"]
  with open(labels_path) as f:
    labels = json.load(f)
  rows = []
  for r in allrows:
    lab = labels.get(r["file"], {}).get("label")
    if lab in (0, 1, 2):
      rows.append(dict(r, y=lab))
  print(f"test crops {len(allrows)}, labelled {len(rows)} (+{sum(labels.get(r['file'], {}).get('label') == 'x' for r in allrows)} unsure)")
  if not rows:
    sys.exit("no labelled test crops yet")

  probs = infer(args.model, args.crops, rows)
  if os.path.realpath(args.model) == os.path.realpath(default_model()):
    shipped = np.array([[float(r["p_nocar"]), float(r["p_car"]), float(r["p_distant"])] for r in rows])
    diff = float(np.max(np.abs(probs - shipped)))
    assert diff < 1e-3, f"shipped model on PNGs differs from the manifest by {diff}"
    print(f"shipped model reproduces the manifest probabilities (max diff {diff:.1e})")

  y = np.array([r["y"] for r in rows])
  y_car, p_car = y == 1, probs[:, 1]
  if args.night_gate:
    p_car = night_gate(rows, p_car)
  luma = np.array([float(r["mean_luma"]) for r in rows])
  subsets = {
    "all": np.ones(len(rows), bool),
    "night": luma < NIGHT_LUMA,
    "pass_hold": np.array([r["pass_hold"] == "1" for r in rows]),
    "radar_near": np.array([r["radar_status"] == "1" and 0.0 <= float(r["radar_drel"]) <= RADAR_NEAR_M for r in rows]),
  }
  for route in sorted({r["route"] for r in rows}):
    subsets[route] = np.array([r["route"] == route for r in rows])
  res = {
    "model": os.path.basename(args.model),
    "model_sha256": sha(args.model),
    "manifest_sha256": sha(manifest),
    "labels_sha256": sha(labels_path),
    "labelled": len(rows),
    "on": args.on,
    "off": args.off,
    "night_gate": args.night_gate,
    "frame": {name: frame_scores(y_car[m], p_car[m], args.on) for name, m in subsets.items() if m.any()},
    "confusion": [[int(np.sum((y == a) & (probs.argmax(1) == b))) for b in range(3)] for a in range(3)],
    "sweep": {f"{on:.2f}": frame_scores(y_car, p_car, on) for on in SWEEP},
    "events": event_scores(rows, p_car, args.on, args.off),
  }
  report(res)
  if args.out:
    with open(args.out, "w") as f:
      json.dump(res, f, indent=1)
  return res


def report(res):
  print(f"\n{res['model']}  on {res['on']} / off {res['off']}   frame level (car = class 1)")
  print(f"{'subset':26s} {'n':>5s} {'cars':>5s} {'prec':>6s} {'recall':>6s} {'F0.5':>6s} {'FP':>4s} {'FN':>4s}")
  for name, s in res["frame"].items():
    print(f"{name:26s} {s['n']:5d} {s['cars']:5d} {s['precision']:6.3f} {s['recall']:6.3f} {s['f0_5']:6.3f} {s['fp']:4d} {s['fn']:4d}")
  print("confusion (rows = label nocar/car/distant, cols = model argmax):", res["confusion"])
  print("threshold sweep (on):  " + "  ".join(f"{k}: P{v['precision']:.2f} R{v['recall']:.2f}" for k, v in res["sweep"].items()))
  e = res["events"]
  print(f"events (daemon sampling): {e['events']} car events (+{e['short_events']} under {MIN_EVENT_S} s, not scored), missed {e['missed']}")
  print(f"  latency p50 {e['latency_p50']:.2f} s, p90 {e['latency_p90']:.2f} s; false-occupied {e['false_occupied_s_per_h']:.0f} s/h")
  print(f"  {e['side_hours']:.2f} side-hours, {e['segment_sides_used']} segment sides used, {e['segment_sides_skipped']} skipped < {LABELLED_MIN:.0%} labelled")


def compare(a_path, b_path):
  with open(a_path) as f:
    a = json.load(f)
  with open(b_path) as f:
    b = json.load(f)
  if (a["manifest_sha256"], a["labels_sha256"]) != (b["manifest_sha256"], b["labels_sha256"]):
    sys.exit("different test sets (manifest or labels changed): re-run both")
  if a.get("night_gate", False) != b.get("night_gate", False):
    sys.exit("one run has the D-122 night gate and the other does not: re-run both the same way")
  ea, eb = a["events"], b["events"]
  checks = [
    ("missed events", ea["missed"], eb["missed"], eb["missed"] <= ea["missed"]),
    ("false-occupied s/h", ea["false_occupied_s_per_h"], eb["false_occupied_s_per_h"], eb["false_occupied_s_per_h"] <= ea["false_occupied_s_per_h"]),
    ("latency p50 s", ea["latency_p50"], eb["latency_p50"], eb["latency_p50"] <= ea["latency_p50"] + LATENCY_SLACK),
  ]
  fa, fb = a["frame"]["all"], b["frame"]["all"]
  print(f"{'':22s} {a['model']:>22s} {b['model']:>22s}")
  print(f"{'on / off':22s} {a['on']:>15} / {a['off']:<4} {b['on']:>15} / {b['off']:<4}")
  for k in ("precision", "recall", "f0_5", "fp", "fn"):
    print(f"frame {k:16s} {fa[k]:22.3f} {fb[k]:22.3f}")
  for name, va, vb, ok in checks:
    print(f"{name:22s} {va:22.2f} {vb:22.2f}  {'ok' if ok else 'WORSE'}")
  verdict = all(ok for *_, ok in checks)
  print("GATE:", "candidate no worse" if verdict else "candidate FAILS the gate")
  return verdict


def default_model():
  from openpilot.starpilot.system.adj_spot_monitor_vision_inference import V_ASM_MODEL_PATH

  return V_ASM_MODEL_PATH


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--model", default=None)
  ap.add_argument("--on", type=float, default=0.8)
  ap.add_argument("--off", type=float, default=0.65)
  ap.add_argument("--out")
  ap.add_argument("--no-night-gate", dest="night_gate", action="store_false", help="score without the daemon's D-122 gate")
  ap.add_argument("--compare", nargs=2, metavar=("BASE", "CANDIDATE"))
  args = ap.parse_args()
  if args.compare:
    sys.exit(0 if compare(*args.compare) else 1)
  args.model = args.model or default_model()
  run(args)


if __name__ == "__main__":
  main()
