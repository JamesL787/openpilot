#!/usr/bin/env python3
"""Offline Bosch-A longitudinal-coordinate experiment.

This script reads only raw source-2 CAN plus modelV2 position/velocity for
evaluation. It never imports or modifies the production RadarInterface.
The model is used only for position/lateral matching; candidate velocity is
not used to choose the match.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
from collections import defaultdict, deque
from pathlib import Path

from openpilot.tools.lib.logreader import LogReader

RADAR_TO_CAMERA = 1.52
RANGE_SCALE = 0.05712
RANGE_OFFSET = -3.0
STALE = 0.20


def main_ids(slot: int) -> tuple[int, int, int, int]:
  base = 0x280 + 4 * slot if slot < 4 else 0x2D0 + 4 * (slot - 4)
  return tuple(base + i for i in range(4))


def aux_id(slot: int) -> int:
  return 0x2C8 + slot if slot < 8 else 0x290 + slot - 8


ADDR = {}
for _slot in range(16):
  for _kind, _addr in zip(("F0", "F1", "F2", "F3"), main_ids(_slot), strict=True):
    ADDR[_addr] = (_slot, _kind)
  ADDR[aux_id(_slot)] = (_slot, "AUX")


def frame_idx(kind: str, b: bytes) -> int:
  return {"F0": b[3] & 0xF, "F1": (b[3] >> 1) & 0xF,
          "F2": b[1] & 0xF, "F3": (b[1] >> 1) & 0xF,
          "AUX": (b[1] >> 1) & 0xF}[kind]


def decode(slot: int, frames: dict[str, tuple[float, bytes]]) -> dict:
  f0, f1, f2, f3 = (frames[k][1] for k in ("F0", "F1", "F2", "F3"))
  aux = frames.get("AUX")
  raw_range = (f0[2] << 4) | (f0[3] >> 4)
  raw_angle = (f0[4] << 3) | (f0[5] >> 5)
  theta = (raw_angle - 1024) / 2048.0
  return {
    "time": max(v[0] for v in frames.values()), "slot": slot,
    "track_id": f3[6], "life": (f2[0] << 4) | (f2[1] >> 4),
    "frame_idx": frame_idx("F0", f0), "range_raw": raw_range,
    "angle_raw": raw_angle,
    "range_m": RANGE_SCALE * raw_range + RANGE_OFFSET,
    "theta": theta, "range_sigma": (f0[0] >> 1) & 0x7F,
    "existence": f1[5] & 0x7F, "status": f0[1] >> 4,
    "aux_time": aux[0] if aux is not None else None,
    "u11": ((aux[1][0] << 3) | (aux[1][1] >> 5)) if aux is not None else None,
    "u10": ((aux[1][2] << 2) | (aux[1][3] >> 6)) if aux is not None else None,
    "ratio_raw": ((aux[1][6] << 2) | (aux[1][7] >> 6)) if aux is not None else None,
    "aux_frame_idx": frame_idx("AUX", aux[1]) if aux is not None else None,
  }


def median_slope(history: deque[tuple[float, float]], n: int) -> float | None:
  if len(history) < n:
    return None
  rows = list(history)[-n:]
  slopes = [(rows[j][1] - rows[i][1]) / (rows[j][0] - rows[i][0])
            for i in range(n) for j in range(i + 1, n)
            if rows[j][0] > rows[i][0]]
  return statistics.median(slopes) if slopes else None


def model_match(model_index: dict[str, tuple[list[float], list[dict]]], route: str,
                t: float, x: float, y: float) -> dict | None:
  # Position-only nearest model match. The candidate velocity is deliberately
  # absent from this score, preventing evaluation leakage.
  best = None
  best_score = float("inf")
  if route not in model_index:
    return None
  times, route_models = model_index[route]
  lo = bisect.bisect_left(times, t - 0.15)
  hi = bisect.bisect_right(times, t + 0.15)
  for m in route_models[lo:hi]:
    dt = abs(m["time"] - t)
    if dt > 0.15 or m["prob"] < 0.7:
      continue
    sx = max(float(m["xstd"]), 2.0)
    sy = max(float(m["ystd"]), 1.0)
    score = ((x - (m["x"] - RADAR_TO_CAMERA)) / sx) ** 2 + ((y + m["y"]) / sy) ** 2
    if score < best_score:
      best_score, best = score, m
  return best if best_score < 9.0 else None


def nearest_service(service_index: dict[str, tuple[list[float], list[dict]]], route: str,
                    t: float, limit: float = 0.15) -> dict | None:
  best = None
  best_dt = limit
  if route not in service_index:
    return None
  times, rows = service_index[route]
  lo = bisect.bisect_left(times, t - limit)
  hi = bisect.bisect_right(times, t + limit)
  for row in rows[lo:hi]:
    dt = abs(row["time"] - t)
    if dt < best_dt:
      best_dt, best = dt, row
  return best


def percentile(values: list[float], p: float) -> float:
  if not values:
    return float("nan")
  values = sorted(values)
  return values[min(len(values) - 1, int((len(values) - 1) * p))]


def valid_geometry(row: dict) -> bool:
  return (row["status"] != 0xF and row["range_raw"] != 0xFFF and
          row["range_raw"] >= 0 and row["range_raw"] <= 0xFFE and
          row["angle_raw"] != 0x7FF and row["angle_raw"] >= 0 and
          row["angle_raw"] <= 0x7FE and row["life"] != 0xFFF and
          1 <= row["track_id"] <= 0x3F)


def run(paths: list[Path], out: Path) -> None:
  models = []
  car_states = []
  raw_obs = []
  for path in paths:
    segment = int(path.name.split("--")[-2])
    route_id = path.name.split("_")[1].split("--")[0]
    slot_frames: list[dict[str, tuple[float, bytes]]] = [dict() for _ in range(16)]
    seen: dict[tuple[int, int, int, int, int], int] = {}
    for msg in LogReader(str(path)):
      t = msg.logMonoTime * 1e-9
      which = msg.which()
      if which == "modelV2":
        q = msg.modelV2.leadsV3[0]
        if len(q.x) and len(q.v):
          models.append({"time": t, "route": route_id, "segment": segment, "prob": float(q.prob),
                         "x": float(q.x[0]), "y": float(q.y[0]), "v": float(q.v[0]),
                         "vego": float(msg.modelV2.velocity.x[0]),
                         "xstd": float(q.xStd[0]), "ystd": float(q.yStd[0])})
      elif which == "carState":
        car_states.append({"time": t, "route": route_id, "segment": segment,
                           "vego": float(msg.carState.vEgo),
                           "aego": float(msg.carState.aEgo)})
      elif which == "can":
        for c in msg.can:
          if int(c.src) != 2 or int(c.address) not in ADDR:
            continue
          slot, kind = ADDR[int(c.address)]
          slot_frames[slot][kind] = (t, bytes(c.dat))
          f = slot_frames[slot]
          if not all(k in f for k in ("F0", "F1", "F2", "F3")):
            continue
          idxs = [frame_idx(k, f[k][1]) for k in ("F0", "F1", "F2", "F3")]
          if len(set(idxs)) != 1 or max(f[k][0] for k in ("F0", "F1", "F2", "F3")) - min(f[k][0] for k in ("F0", "F1", "F2", "F3")) > 0.15:
            continue
          if "AUX" in f and frame_idx("AUX", f["AUX"][1]) != idxs[0]:
            f = {k: v for k, v in f.items() if k != "AUX"}
          row = decode(slot, f)
          key = (segment, slot, row["frame_idx"], row["track_id"], row["life"])
          if key not in seen:
            row["route"] = route_id
            row["segment"] = segment
            seen[key] = len(raw_obs)
            raw_obs.append(row)
          elif row["u11"] is not None:
            # The companion can arrive after the four main frames. Upgrade the already-seen
            # geometry row instead of counting the same physical observation twice.
            raw_obs[seen[key]].update({k: row[k] for k in ("u11", "u10", "ratio_raw", "aux_frame_idx", "aux_time")})
  models.sort(key=lambda x: (x["route"], x["time"]))
  car_states.sort(key=lambda x: (x["route"], x["time"]))
  raw_obs.sort(key=lambda x: (x["route"], x["time"]))
  model_index = {}
  for route in {m["route"] for m in models}:
    rs = [m for m in models if m["route"] == route]
    model_index[route] = ([m["time"] for m in rs], rs)
  car_index = {}
  for route in {c["route"] for c in car_states}:
    rs = [c for c in car_states if c["route"] == route]
    car_index[route] = ([c["time"] for c in rs], rs)
  coherent_main = len(raw_obs)
  coherent_with_aux = sum(row["u11"] is not None for row in raw_obs)

  # Accepted history is per persistent identity and resets on lifecycle break.
  histories: dict[tuple[str, int], dict[str, deque[tuple[float, float]]]] = defaultdict(
    lambda: {"A": deque(maxlen=5), "B": deque(maxlen=5)})
  previous: dict[tuple[str, int], tuple[float, int, int, float, float]] = {}
  detailed = []
  all_candidates = []
  for row in raw_obs:
    tid = row["track_id"]
    identity = (row["route"], tid)
    if not valid_geometry(row):
      continue
    t, life, idx = row["time"], row["life"], row["frame_idx"]
    old = previous.get(identity)
    same = old is not None and ((idx - old[1]) & 0xF) > 0 and ((life - old[2]) & 0xFFF) == 2 * ((idx - old[1]) & 0xF)
    if not same:
      histories[identity]["A"].clear(); histories[identity]["B"].clear()
    theta, r = row["theta"], row["range_m"]
    xa, ya = r, -r * math.tan(theta)
    xb, yb = r * math.cos(theta), -r * math.sin(theta)
    accepted = True
    if old is not None and same and t > old[0]:
      dt = t - old[0]
      ratio = (0.5 + row["ratio_raw"] / 1000.0
               if row["ratio_raw"] is not None and row["ratio_raw"] < 0x3FF else None)
      residuals = [] if ratio is None else [abs(old[3] - r * ratio)]
      if residuals:
        accepted = min(residuals) <= 5.0 and not (row["range_sigma"] >= 4 and min(residuals) > 2.0)
      elif abs(r - old[3]) / dt > 50.0:
        accepted = False
    if accepted:
      histories[identity]["A"].append((t, xa)); histories[identity]["B"].append((t, xb))
      previous[identity] = (t, idx, life, r, xa)
    for coord, x, y in (("A", xa, ya), ("B", xb, yb)):
      history = histories[identity][coord]
      specs = [(f"{coord}3", 3, 3), (f"{coord}4B3", 4, 3),
               (f"{coord}4", 4, 4), (f"{coord}5", 5, 5)]
      for candidate, window, minimum in specs:
        estimate_window = 3 if candidate.endswith("4B3") and len(history) == 3 else window
        estimate = median_slope(history, estimate_window) if accepted and len(history) >= minimum else None
        oldest_age = (t - history[-estimate_window][0]) if estimate is not None else None
        all_candidates.append({
          "route": row["route"], "segment": row["segment"], "time": t,
          "track_id": tid, "slot": row["slot"], "lifecycle": row["life"],
          "frame_idx": row["frame_idx"], "candidate": candidate,
          "x": x, "y": y, "vRel": estimate,
          "history_count": len(history), "oldest_sample_age": oldest_age,
          "range_sigma": row["range_sigma"], "existence": row["existence"],
          "U11": row["u11"], "U10": row["u10"], "00CA": row["ratio_raw"],
          "accepted": accepted,
        })
        model = model_match(model_index, row["route"], t, x, y) if estimate is not None else None
        if estimate is not None and model is not None:
          car = nearest_service(car_index, row["route"], t)
          model_truth = model["v"] - model["vego"]
          car_truth = model["v"] - car["vego"] if car is not None else None
          detailed.append({"route": row["route"], "segment": row["segment"], "time": t,
                           "track_id": tid, "coordinate": coord, "window": estimate_window,
                           "candidate": candidate,
                           "x": x, "y": y, "estimate": estimate,
                           "model_vrel": model_truth, "carstate_vrel": car_truth,
                           "abs_error_model": abs(estimate - model_truth),
                           "abs_error_carstate": abs(estimate - car_truth) if car_truth is not None else None,
                           "oldest_sample_age": oldest_age, "accepted": accepted})

  out.mkdir(parents=True, exist_ok=True)
  detail_path = out / "bosch_vrel_trajectory_samples.csv"
  with detail_path.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(detailed[0]) if detailed else ["coordinate"])
    writer.writeheader(); writer.writerows(detailed)
  all_path = out / "bosch_vrel_trajectory_all.csv"
  with all_path.open("w", newline="") as f:
    fields = list(all_candidates[0]) if all_candidates else ["candidate"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader(); writer.writerows(all_candidates)
  summary = []
  for reference, error_key in (("model_vrel", "abs_error_model"), ("carstate_vrel", "abs_error_carstate")):
    for coord in ("A", "B"):
      for candidate in (f"{coord}3", f"{coord}4B3", f"{coord}4", f"{coord}5"):
        vals = [r for r in detailed if r["candidate"] == candidate and r[error_key] is not None]
        errors = [r["estimate"] - r[reference] for r in vals]
        ages = [r["oldest_sample_age"] for r in vals if r["oldest_sample_age"] is not None]
        summary.append({"reference": reference, "candidate": candidate, "n": len(vals),
                        "bias": sum(errors) / len(errors) if errors else float("nan"),
                        "mae": sum(abs(x) for x in errors) / len(errors) if errors else float("nan"),
                        "rmse": math.sqrt(sum(x*x for x in errors) / len(errors)) if errors else float("nan"),
                        "p95_abs": percentile([abs(x) for x in errors], .95),
                        "p99_abs": percentile([abs(x) for x in errors], .99),
                        "max_abs": max((abs(x) for x in errors), default=float("nan")),
                        "age_median": statistics.median(ages) if ages else float("nan"),
                        "age_p95": percentile(ages, .95),
                        "age_max": max(ages, default=float("nan"))})
  with (out / "bosch_vrel_trajectory_comparison.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(summary[0])); writer.writeheader(); writer.writerows(summary)
  print(f"coherent_f0_f3={coherent_main} coherent_with_matching_aux={coherent_with_aux} observations={len(raw_obs)} model_rows={len(models)} all_candidate_rows={len(all_candidates)} matched_samples={len(detailed)}")
  for r in summary:
    print(r)


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("paths", nargs="+", type=Path)
  ap.add_argument("--out", type=Path, default=Path("analysis/trajectory_eval"))
  args = ap.parse_args()
  run(sorted(args.paths), args.out)
