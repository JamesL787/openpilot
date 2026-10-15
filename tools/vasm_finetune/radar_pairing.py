"""Radar-paired blind-spot timing: can the adjacent-lane radar track tell us when a car is in the side camera's crop?

  python tools/vasm_finetune/radar_pairing.py --crops /work/crops --dm /work/dm --out /work/radar_pairing.json
  python tools/vasm_finetune/radar_pairing.py ... --model /work/ft/run11/s9/ep0.pt --device mps   # + model latency

The radar (leadLeft/leadRight, ex_<route>_<seg>.json rows from tools/vasm_replay/rlog_extract.py) only sees ahead. Two
hand-offs bracket the blind spot:
  exit   we pass a car: its track closes (vRel < 0) and is lost at short range; extrapolate d = d_last + v_last * (t - t_last)
  entry  a car passes us: its track first appears at short range pulling away; extrapolate back from the first sample
Each hand-off is paired with the owner's labelled car run (labels.json entries without "by", sides >= LABELLED_MIN
labelled) on the same car side, and the extrapolated distance at the labelled onset and offset is recorded. If those
distances are tight, they are the crop's zone in radar coordinates, and the leave-one-out timing error says how well
radar alone would time a car's entry/exit. Radar silence never means "clear" (a car behind us is never tracked), so this
can only ever supply positives and onset times, never negatives.

With --model, the model's frame-level p_car on each paired event's crops (no daemon sampling) gives latency from the
radar-predicted zone entry: torch on --device (mps = Apple GPU), batched. --model takes a train.py state dict (ep<N>.pt,
needs --base for the architecture) or a whole saved model (best.pt, vasm_converted.pt).
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from benchmark import LABELLED_MIN, MERGE_GAP, runs  # noqa: E402

NEAR_M = 15.0  # a hand-off must happen this close (radar d) to bracket the blind spot
MIN_V = 0.5  # m/s relative speed: slower is a car pacing us, whose extrapolation is meaningless
V_WINDOW_S = 0.5  # vRel used for extrapolation = median over the last/first this many seconds of the track
EXIT_PAIR = (-3.0, 8.0)  # labelled onset within [t_last + a, t_last + b] pairs with an exit
ENTRY_PAIR = (-8.0, 3.0)  # labelled offset within [t_first + a, t_first + b] pairs with an entry
EDGE_S = 1.0  # tracks starting/ending this close to the segment edge are cut by the file, not the radar


def tracks(radar, k):
  """{tid: (t, d, v)} for car side k (0 left, 1 right), status rows only."""
  out = {}
  for row in radar:
    st, d, _y, v, tid = row[1 + 5 * k : 6 + 5 * k]
    if st:
      out.setdefault(int(tid), []).append((row[0], d, v))
  return {tid: tuple(np.array(c) for c in zip(*s)) for tid, s in out.items()}


def handoffs(trk, t0, t1):
  ev = []
  for tid, (t, d, v) in trk.items():
    if t[-1] < t1 - EDGE_S and d[-1] <= NEAR_M:
      vv = float(np.median(v[t >= t[-1] - V_WINDOW_S]))
      if vv < -MIN_V:
        ev.append({"kind": "exit", "tid": tid, "t": float(t[-1]), "d": float(d[-1]), "v": vv})
    if t[0] > t0 + EDGE_S and d[0] <= NEAR_M:
      vv = float(np.median(v[t <= t[0] + V_WINDOW_S]))
      if vv > MIN_V:
        ev.append({"kind": "entry", "tid": tid, "t": float(t[0]), "d": float(d[0]), "v": vv})
  return ev


def load_model(path, base, device):
  import torch
  obj = torch.load(path, weights_only=False, map_location="cpu")
  if isinstance(obj, dict):
    model = torch.load(base, weights_only=False, map_location="cpu")
    model.load_state_dict(obj)
  else:
    model = obj
  return model.to(device).eval()


def p_car(model, crops, files, device, batch=64):
  import cv2
  import torch
  out = []
  with torch.no_grad():
    for i in range(0, len(files), batch):
      x = np.stack([cv2.cvtColor(cv2.imread(os.path.join(crops, f)), cv2.COLOR_BGR2RGB).transpose(2, 0, 1) for f in files[i : i + batch]])
      out.append(model(torch.from_numpy(x).float().div(255.0).to(device))[:, 1].cpu().numpy())
  return np.concatenate(out) if out else np.zeros(0)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--dm", default="/work/dm", help="directory holding ex_<route>_<seg>.json")
  ap.add_argument("--out", default=None)
  ap.add_argument("--model", default=None)
  ap.add_argument("--base", default="/work/ft/vasm_converted.pt")
  ap.add_argument("--on", type=float, default=0.8)
  ap.add_argument("--device", default="mps")
  args = ap.parse_args()

  with open(os.path.join(args.crops, "labels.json")) as f:
    labels = json.load(f)
  sides = {}
  with open(os.path.join(args.crops, "manifest.csv")) as f:
    for r in csv.DictReader(f):
      sides.setdefault((r["route"], r["seg"], r["car_side"]), []).append(r)

  pairs, n_sides, n_runs, n_handoffs = [], 0, 0, 0
  for (route, seg, car_side), rows in sorted(sides.items()):
    ex_path = os.path.join(args.dm, f"ex_{route}_{seg}.json")
    lab = [labels.get(r["file"], {}) for r in rows]
    own = [e.get("label") if "by" not in e else None for e in lab]
    if not os.path.exists(ex_path) or np.mean([y in (0, 1, 2) for y in own]) < LABELLED_MIN:
      continue
    with open(ex_path) as f:
      radar = json.load(f)["radar"]
    if not radar:
      continue
    n_sides += 1
    order = np.argsort([float(r["t"]) for r in rows])
    rows, own = [rows[i] for i in order], [own[i] for i in order]
    t = np.array([float(r["t"]) for r in rows])
    car_runs = [(a, b) for a, b in runs(t, np.array([y == 1 for y in own]), MERGE_GAP)]
    n_runs += len(car_runs)
    ev = handoffs(tracks(radar, 0 if car_side == "left" else 1), t[0], t[-1])
    n_handoffs += len(ev)
    for e in ev:
      if e["kind"] == "exit":
        cand = [(a, b) for a, b in car_runs if e["t"] + EXIT_PAIR[0] <= a <= e["t"] + EXIT_PAIR[1]]
        cand.sort(key=lambda ab: abs(ab[0] - e["t"]))
      else:
        cand = [(a, b) for a, b in car_runs if e["t"] + ENTRY_PAIR[0] <= b <= e["t"] + ENTRY_PAIR[1]]
        cand.sort(key=lambda ab: abs(ab[1] - e["t"]))
      if not cand:
        pairs.append({**e, "route": route, "seg": seg, "car_side": car_side, "paired": False})
        continue
      a, b = cand[0]
      pairs.append({**e, "route": route, "seg": seg, "car_side": car_side, "paired": True, "onset": a, "offset": b,
                    "d_onset": e["d"] + e["v"] * (a - e["t"]), "d_offset": e["d"] + e["v"] * (b - e["t"]),
                    "files": [r["file"] for r, tt in zip(rows, t) if a - 3.0 <= tt <= b + 1.0],
                    "file_t": [float(tt) for tt in t if a - 3.0 <= tt <= b + 1.0]})

  print(f"{n_sides} dense owner-labelled segment sides with radar, {n_runs} labelled car runs, {n_handoffs} near hand-offs")
  res = {"sides": n_sides, "car_runs": n_runs, "handoffs": n_handoffs, "kinds": {}}
  for kind in ("exit", "entry"):
    p = [x for x in pairs if x["kind"] == kind and x["paired"]]
    tot = sum(x["kind"] == kind for x in pairs)
    print(f"\n{kind}: {len(p)}/{tot} hand-offs paired with a labelled car run")
    if len(p) < 3:
      res["kinds"][kind] = {"paired": len(p), "total": tot}
      continue
    # zone edge the car crosses first: exit -> crop entry is the onset; entry (car overtaking) -> also the onset
    d_on, d_off = np.array([x["d_onset"] for x in p]), np.array([x["d_offset"] for x in p])
    q = lambda a: [round(float(v), 2) for v in np.percentile(a, [10, 25, 50, 75, 90])]  # noqa: E731
    print(f"  extrapolated d at labelled onset  p10/25/50/75/90 {q(d_on)} m")
    print(f"  extrapolated d at labelled offset p10/25/50/75/90 {q(d_off)} m")
    # leave-one-out: predict the onset time from the other events' median onset distance
    err = []
    for i, x in enumerate(p):
      edge = float(np.median(np.delete(d_on, i)))
      err.append((x["t"] + (edge - x["d"]) / x["v"]) - x["onset"])
    err = np.array(err)
    print(f"  leave-one-out onset timing error: median {np.median(err):+.2f} s, |err| p50 {np.median(np.abs(err)):.2f} s, "
          f"p90 {np.percentile(np.abs(err), 90):.2f} s")
    # the edge next to the hand-off is extrapolated over the shortest time: the offset for an entry (car pulling ahead)
    err_off = np.array([(x["t"] + (float(np.median(np.delete(d_off, i))) - x["d"]) / x["v"]) - x["offset"] for i, x in enumerate(p)])
    print(f"  leave-one-out offset timing error: median {np.median(err_off):+.2f} s, |err| p50 {np.median(np.abs(err_off)):.2f} s, "
          f"p90 {np.percentile(np.abs(err_off), 90):.2f} s")
    gap = np.array([abs(x["onset"] - x["t"]) if kind == "exit" else abs(x["offset"] - x["t"]) for x in p])
    print(f"  hand-off to nearest labelled edge: p50 {np.median(gap):.2f} s, p90 {np.percentile(gap, 90):.2f} s")
    res["kinds"][kind] = {"paired": len(p), "total": tot, "d_onset_pct": q(d_on), "d_offset_pct": q(d_off),
                          "loo_abs_err_p50": round(float(np.median(np.abs(err))), 3),
                          "loo_abs_err_p90": round(float(np.percentile(np.abs(err), 90)), 3), "loo_err_median": round(float(np.median(err)), 3)}

  if args.model:
    model = load_model(args.model, args.base, args.device)
    for kind in ("exit", "entry"):
      p = [x for x in pairs if x["kind"] == kind and x["paired"]]
      if len(p) < 3:
        continue
      d_on = np.array([x["d_onset"] for x in p])
      lat_radar, lat_label = [], []
      for i, x in enumerate(p):
        pred = x["t"] + (float(np.median(np.delete(d_on, i))) - x["d"]) / x["v"]
        pc = p_car(model, args.crops, x["files"], args.device)
        hit = [tt for tt, pp in zip(x["file_t"], pc) if pp >= args.on and tt >= min(pred, x["onset"]) - 0.5]
        lat_radar.append(hit[0] - pred if hit else np.nan)
        lat_label.append(hit[0] - x["onset"] if hit else np.nan)
      lr, ll = np.array(lat_radar), np.array(lat_label)
      print(f"\n{kind} model frame latency @ {args.on}: from radar-predicted onset median {np.nanmedian(lr):+.2f} s, "
            f"from labelled onset {np.nanmedian(ll):+.2f} s, never fired {int(np.isnan(lr).sum())}/{len(lr)}")
      res["kinds"][kind].update({"model_lat_radar_p50": round(float(np.nanmedian(lr)), 3), "model_lat_label_p50": round(float(np.nanmedian(ll)), 3),
                                 "model_never": int(np.isnan(lr).sum())})
  if args.out:
    res["pairs"] = [{k: v for k, v in x.items() if k not in ("files", "file_t")} for x in pairs]
    with open(args.out, "w") as f:
      json.dump(res, f, indent=1)


if __name__ == "__main__":
  main()
