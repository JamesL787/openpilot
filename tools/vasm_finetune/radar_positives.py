"""Radar-timed car proposals on unlabelled segments, for the owner to confirm in the labeller (never auto-labels).

  python tools/vasm_finetune/radar_positives.py --crops /work/crops --dm /work/dm --out /work/cropsradar

Exit hand-offs (we pass a car: its adjacent-lane track closes and is lost at <= MAX_D m with no other hand-off on that
side within ISOLATE_S s) and entry hand-offs (a car passes us: its track first appears at <= ENTRY_MAX_D m pulling away,
and is traced back to the crop edge). radar_pairing.py on the owner's dense labels, 2026-10-14: those 18 exits
predict the labelled onset with leave-one-out |err| p50 0.14 s, p90 0.42 s, max 0.77 s; entries were all first seen at
> 10 m and unusable, and the outliers were far hand-offs and traffic clusters. The crop's zone edge is ZONE_D m (median
extrapolated radar d at the labelled onset over those exits). Crops in [t_edge + LEAD_S, t_edge + LEAD_S + WINDOW_S]
on that car side are proposed as car (1); LEAD_S is above the p90 timing error.

Agreement check against existing labels (--include-labelled, diag/exit_fail.py, 2026-10-14) put unfiltered exits at
46 car / 53 no-car windows. Lane offset and loss distance did not separate them; the extrapolation horizon
(ZONE_D - d) / v and ego speed did: horizon > 4 s 4 / 16, ego median 30 m/s on car windows vs 16 on no-car. With
horizon <= MAX_H and v_ego >= MIN_VEGO: 19 / 6 on all labels, 8 / 0 on the owner's (small n).

Entries: crops in [t_edge - ENTRY_WIN_S, t_edge], t_edge = t_first - (d_first - ENTRY_D) / v (ENTRY_D the median
extrapolated d at the labelled offset, radar_pairing.py). On owner labels, day: 142 car / 35 no-car, in-sample.
Night entries (crop mean_luma < NIGHT_LUMA) are kept unfiltered because there are only a handful and low light is the
point; day entries take the same MAX_H / MIN_VEGO filters as exits.

Writes <out>/: symlinks to the crops' route dirs, manifest.csv (proposed rows only), queue.json (one window per
hand-off, for labeler.py ?split=queue) and proposals.json. It never writes labels: <out>/labels.json is the owner's.
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from radar_pairing import handoffs, tracks  # noqa: E402

MAX_D = 10.0
ISOLATE_S = 3.0
ZONE_D = -0.7
LEAD_S = 0.45
WINDOW_S = 0.5
MAX_H = 2.5  # s of extrapolation from the radar hand-off to the crop edge
MIN_VEGO = 20.0  # m/s
ENTRY_MAX_D = 15.0
ENTRY_D = 1.94
ENTRY_WIN_S = 2.0
NIGHT_LUMA = 40.0


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default="/work/crops")
  ap.add_argument("--dm", default="/work/dm")
  ap.add_argument("--out", default="/work/cropsradar")
  ap.add_argument("--include-labelled", action="store_true", help="also propose on segment sides the owner labelled (to measure agreement)")
  args = ap.parse_args()
  with open(os.path.join(args.crops, "labels.json")) as f:
    labels = json.load(f)
  with open(os.path.join(args.crops, "manifest.csv")) as f:
    manifest = list(csv.DictReader(f))
  fields = list(manifest[0])
  sides = {}
  for r in manifest:
    sides.setdefault((r["route"], r["seg"], r["car_side"]), []).append(r)

  props, rows_out, queue = [], [], []
  for (route, seg, car_side), rows in sorted(sides.items()):
    if rows[0]["split"] == "test":
      continue
    ex_path = os.path.join(args.dm, f"ex_{route}_{seg}.json")
    owner = np.mean([labels.get(r["file"], {}).get("label") in (0, 1, 2) and "by" not in labels.get(r["file"], {}) for r in rows])
    if not os.path.exists(ex_path) or (owner > 0 and not args.include_labelled):
      continue
    with open(ex_path) as f:
      radar = json.load(f)["radar"]
    if not radar:
      continue
    t = np.array([float(r["t"]) for r in rows])
    ev = handoffs(tracks(radar, 0 if car_side == "left" else 1), t.min(), t.max())
    vego = np.array([float(r["v_ego"]) for r in rows])
    luma = np.array([float(r["mean_luma"]) for r in rows])
    for e in ev:
      if e["kind"] == "exit":  # isolation as measured: exits only, against any hand-off
        if e["d"] > MAX_D or any(o is not e and abs(o["t"] - e["t"]) < ISOLATE_S for o in ev):
          continue
        t_edge = e["t"] + (ZONE_D - e["d"]) / e["v"]
        a, b = t_edge + LEAD_S, t_edge + LEAD_S + WINDOW_S
      else:
        if e["d"] > ENTRY_MAX_D:
          continue
        t_edge = e["t"] - (e["d"] - ENTRY_D) / e["v"]
        a, b = t_edge - ENTRY_WIN_S, t_edge
      h = abs(e["t"] - t_edge)
      m = (t >= a) & (t <= b)
      if not m.any():
        continue
      night = bool(np.median(luma[m]) < NIGHT_LUMA)
      if not night and (h > MAX_H or np.median(vego[m]) < MIN_VEGO):
        continue
      sel = [r for r, k in zip(rows, m) if k]
      props.append({"route": route, "seg": seg, "car_side": car_side, "image_side": sel[0]["image_side"], "t_edge": round(t_edge, 3),
                    "horizon": round(h, 2), "night": night, "handoff": e, "files": [r["file"] for r in sel],
                    "existing_labels": [labels.get(r["file"], {}).get("label") for r in sel]})
      rows_out += sel
      queue.append({"route": route[-6:], "seg": int(seg), "side": sel[0]["image_side"], "t0": round(a, 3), "t1": round(b, 3),
                    "why": f"{'night ' if night else ''}radar {e['kind']} d {e['d']:.1f} v {e['v']:+.1f} trace {h:.1f}s"})

  queue.sort(key=lambda q: not q["why"].startswith("night"))
  os.makedirs(args.out, exist_ok=True)
  for route in sorted({p["route"] for p in props}):
    link = os.path.join(args.out, route)
    if not os.path.lexists(link):
      os.symlink(os.path.realpath(os.path.join(args.crops, route)), link)
  with open(os.path.join(args.out, "manifest.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows_out)
  with open(os.path.join(args.out, "queue.json"), "w") as f:
    json.dump({"created": "2026-10-14", "note": "radar-timed car proposals (exits + entries, night first); label what you see", "sides": queue}, f, indent=0)
  with open(os.path.join(args.out, "proposals.json"), "w") as f:
    json.dump(props, f, indent=0)
  lab = [y for p in props for y in p["existing_labels"] if y in (0, 1, 2)]
  kinds = {(p["handoff"]["kind"], p["night"]) for p in props}
  print({f"{k}{' night' if n else ''}": sum(p["handoff"]["kind"] == k and p["night"] == n for p in props) for k, n in sorted(kinds)})
  print(f"{len(props)} radar windows, {len(rows_out)} proposed car crops on {len({(p['route'], p['seg']) for p in props})} segments"
        + (f"; existing labels on them (owner + agent): car {lab.count(1)}, distant {lab.count(2)}, nocar {lab.count(0)}" if lab else ""))


if __name__ == "__main__":
  main()
