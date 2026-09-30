#!/usr/bin/env python3
"""Offline target-42c2 RadarD/KF counterfactual for selected Bosch tracks.

This is intentionally a standalone replay harness. It mirrors the target commit's
KalmanParams, Track.update, vision-match, Civic Bosch low-speed maturity gate, and
lead selection. It never imports or edits production files.
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
from collections import defaultdict
from pathlib import Path

from openpilot.tools.lib.logreader import LogReader

DT_MDL = 0.05
RADAR_TS = 1.0 / 15.0
RADAR_TO_CAMERA = 1.52
LEAD_PROB_THRESHOLD = 0.35
LOW_SPEED_MIN_COUNT = 3
LOW_SPEED_MAX_VEGO = 4.0


def val(obj, name: str, index: int = 0, default: float = 0.0) -> float:
  try:
    seq = getattr(obj, name)
    if len(seq) <= index:
      return default
    return float(seq[index])
  except (AttributeError, TypeError, IndexError):
    return default


def lead_dict(q) -> dict:
  return {"prob": float(getattr(q, "prob", 0.0)),
          "x": val(q, "x"), "y": val(q, "y"), "v": val(q, "v"), "a": val(q, "a"),
          "xstd": val(q, "xStd", default=5.0), "ystd": val(q, "yStd", default=1.0),
          "vstd": val(q, "vStd", default=5.0)}


def parse_logs(paths: list[Path], routes: set[str], segments: set[tuple[str, int]]):
  models = defaultdict(list)
  car_states = defaultdict(list)
  live_tracks = defaultdict(list)
  radar_states = defaultdict(list)
  for path in paths:
    route = path.name.split("_")[1].split("--")[0]
    segment = int(path.name.split("--")[-2])
    if route not in routes or (route, segment) not in segments:
      continue
    key = (route, segment)
    for msg in LogReader(str(path)):
      t = msg.logMonoTime * 1e-9
      which = msg.which()
      if which == "modelV2":
        leads = []
        for i in range(min(2, len(msg.modelV2.leadsV3))):
          leads.append(lead_dict(msg.modelV2.leadsV3[i]))
        while len(leads) < 2:
          leads.append({"prob": 0.0, "x": 0.0, "y": 0.0, "v": 0.0, "a": 0.0,
                        "xstd": 5.0, "ystd": 1.0, "vstd": 5.0})
        models[key].append({"time": t, "leads": leads,
                            "model_vego": float(msg.modelV2.velocity.x[0]) if len(msg.modelV2.velocity.x) else 0.0,
                            "vego": car_states[key][-1]["vego"] if car_states[key] else 0.0})
      elif which == "carState":
        car_states[key].append({"time": t, "vego": float(msg.carState.vEgo),
                                "aego": float(msg.carState.aEgo)})
      elif which == "liveTracks":
        points = []
        for i in range(len(msg.liveTracks.points)):
          p = msg.liveTracks.points[i]
          points.append({"id": int(p.trackId), "d": float(p.dRel), "y": float(p.yRel),
                         "v": float(p.vRel), "measured": bool(p.measured)})
        live_tracks[key].append({"time": t, "points": points})
      elif which == "radarState":
        vals = []
        for name in ("leadOne", "leadTwo"):
          p = getattr(msg.radarState, name)
          vals.append({"status": bool(p.status), "id": int(p.radarTrackId),
                       "d": float(p.dRel), "y": float(p.yRel), "v": float(p.vRel),
                       "vlead": float(p.vLead), "vleadk": float(p.vLeadK),
                       "aleadk": float(p.aLeadK)})
        radar_states[key].append({"time": t, "leads": vals})
  for d in (models, car_states, live_tracks, radar_states):
    for rows in d.values():
      rows.sort(key=lambda x: x["time"])
  # modelV2 is read before carState in some logs; attach nearest ego below instead.
  for key, rows in models.items():
    cs = car_states[key]
    for row in rows:
      row["vego"] = nearest(cs, row["time"], 0.15).get("vego", 0.0) if nearest(cs, row["time"], 0.15) else 0.0
  return models, car_states, live_tracks, radar_states


def nearest(rows: list[dict], t: float, limit: float = 0.15) -> dict | None:
  best = None
  best_dt = limit
  for row in rows:
    dt = abs(row["time"] - t)
    if dt < best_dt:
      best, best_dt = row, dt
  return best


def previous_event(rows: list[dict], t: float, limit: float = 0.20) -> dict | None:
  best = None
  for row in rows:
    if row["time"] > t:
      break
    if t - row["time"] <= limit:
      best = row
  return best


def laplace(x: float, mu: float, scale: float) -> float:
  return math.exp(-abs(x - mu) / max(scale, 1e-4))


def matches(track, lead: dict, v_ego: float, dist_scale=0.25, dist_floor=5.0,
            vel_limit=10.0, y_scale=1.0, y_floor=1.0) -> bool:
  offset = lead["x"] - RADAR_TO_CAMERA
  dist_ok = abs(track.d - offset) < max(abs(offset) * dist_scale, dist_floor)
  vel_ok = abs(track.v + v_ego - lead["v"]) < vel_limit or v_ego + track.v > 3
  lat_ok = abs(track.y + lead["y"]) < max(y_floor, y_scale * max(lead["ystd"], 0.2))
  return dist_ok and vel_ok and lat_ok


class KfTrack:
  def __init__(self, identifier: int, v_lead: float):
    self.identifier = identifier
    self.cnt = 0
    self.d = self.y = self.v = self.vlead = 0.0
    self.vleadk = v_lead
    self.aleadk = 0.0
    self.x0, self.x1 = v_lead, 0.0
    self.moving_frames = self.rest_frames = 0
    self.seen_moving = False

    dts = [i * 0.01 for i in range(1, 21)]
    k0 = [0.12287673, 0.14556536, 0.16522756, 0.18281627, 0.1988689, 0.21372394,
          0.22761098, 0.24069424, 0.253096, 0.26491023, 0.27621103, 0.28705801,
          0.29750003, 0.30757767, 0.31732515, 0.32677158, 0.33594201, 0.34485814,
          0.35353899, 0.36200124]
    k1 = [0.29666309, 0.29330885, 0.29042818, 0.28787125, 0.28555364, 0.28342219,
          0.28144091, 0.27958406, 0.27783249, 0.27617149, 0.27458948, 0.27307714,
          0.27162685, 0.27023228, 0.26888809, 0.26758976, 0.26633338, 0.26511557,
          0.26393339, 0.26278425]
    # Keep exact target values for dt=1/15; the target uses np.interp.
    self.k0 = interp(RADAR_TS, dts, k0)
    self.k1 = interp(RADAR_TS, dts, k1)
    self.dt = RADAR_TS

  def update(self, point: dict, v_ego: float, fresh: bool):
    self.d, self.y, self.v = point["d"], point["y"], point["v"]
    self.vlead = self.v + v_ego
    if fresh and self.cnt > 0:
      old0, old1 = self.x0, self.x1
      self.x0 = (1.0 - self.k0) * old0 + self.dt * old1 + self.k0 * self.vlead
      self.x1 = -self.k1 * old0 + old1 + self.k1 * self.vlead
    self.vleadk, self.aleadk = self.x0, self.x1
    if fresh:
      self.cnt += 1


def interp(x: float, xs: list[float], ys: list[float]) -> float:
  if x <= xs[0]:
    return ys[0]
  if x >= xs[-1]:
    return ys[-1]
  for i in range(1, len(xs)):
    if x <= xs[i]:
      a = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
      return ys[i - 1] + a * (ys[i] - ys[i - 1])
  return ys[-1]


def choose_lead(tracks: dict[int, KfTrack], lead: dict, v_ego: float, model_vego: float,
                filtered_prob: float, preferred_id: int, low_speed: bool = True) -> dict:
  lead_out = {"status": False, "id": -1, "d": 0.0, "y": 0.0, "v": 0.0,
              "vlead": 0.0, "vleadk": 0.0, "aleadk": 0.0, "radar": False}
  selected = None
  if tracks and filtered_prob > LEAD_PROB_THRESHOLD:
    def score(t: KfTrack) -> float:
      return (laplace(t.d, lead["x"] - RADAR_TO_CAMERA, lead["xstd"]) *
              laplace(t.y, -lead["y"], lead["ystd"]) *
              laplace(t.v + v_ego, lead["v"], lead["vstd"]))
    selected = max(tracks.values(), key=score)
    if not matches(selected, lead, v_ego):
      preferred = tracks.get(preferred_id)
      selected = (preferred if preferred is not None and preferred.cnt >= 3 and
                  matches(preferred, lead, v_ego, 0.40, 8.0, 13.0, 2.0, 1.5) else None)
    if selected is not None and matches(selected, lead, v_ego):
      lead_out = state(selected)
      lead_out["modelProb"] = filtered_prob

  if low_speed:
    model_available = filtered_prob > LEAD_PROB_THRESHOLD
    candidates = [t for t in tracks.values() if t.cnt >= LOW_SPEED_MIN_COUNT and
                  abs(t.y) < 1.0 and v_ego < LOW_SPEED_MAX_VEGO and 0.75 < t.d < 25.0]
    preferred = tracks.get(preferred_id)
    if preferred is not None and preferred.cnt >= LOW_SPEED_MIN_COUNT:
      preferred_model_ok = (not model_available or matches(preferred, lead, v_ego))
      preferred_current = (not lead_out["status"] or lead_out["id"] == preferred_id or
                           (lead_out["status"] and not lead_out["radar"]))
      if preferred_model_ok and preferred_current:
        lead_out = state(preferred)
        lead_out["modelProb"] = filtered_prob

    established = []
    for candidate in candidates:
      if not lead_out["status"] or lead_out["id"] == candidate.identifier:
        established.append(candidate)
      elif model_available and matches(candidate, lead, v_ego):
        established.append(candidate)
    if established:
      closest = min(established, key=lambda t: t.d)
      if not lead_out["status"] or closest.d < lead_out["d"]:
        lead_out = state(closest)
    
  return lead_out


def state(track: KfTrack) -> dict:
  return {"status": True, "id": track.identifier, "d": track.d, "y": track.y,
          "v": track.v, "vlead": track.vlead, "vleadk": track.vleadk,
          "aleadk": track.aleadk, "radar": True}


def read_candidate_rows(csv_path: Path, selected: set[tuple[str, int]], candidates: set[str]):
  rows = defaultdict(list)
  with csv_path.open() as f:
    for row in csv.DictReader(f):
      key = (row["route"], int(row["segment"]))
      if key not in selected or row["candidate"] not in candidates:
        continue
      row["time"] = float(row["time"]); row["track_id"] = int(row["track_id"])
      row["x"] = float(row["x"]); row["y"] = float(row["y"])
      row["accepted"] = row["accepted"] == "True"
      row["vRel"] = None if row["vRel"] == "" else float(row["vRel"])
      rows[key].append(row)
  for key in rows:
    rows[key].sort(key=lambda r: r["time"])
  return rows


def candidate_points(rows: list[dict], times: list[float], candidate: str):
  by_id = defaultdict(list)
  for row in rows:
    by_id[row["track_id"]].append(row)
  state_by_id = {}
  cursors = {tid: 0 for tid in by_id}
  result = []
  for t in times:
    latest_source = None
    for tid, rs in by_id.items():
      while cursors[tid] < len(rs) and rs[cursors[tid]]["time"] <= t:
        r = rs[cursors[tid]]; cursors[tid] += 1
        if r["vRel"] is not None and r["accepted"]:
          state_by_id[tid] = {"d": r["x"], "y": r["y"], "v": r["vRel"],
                              "measured": True, "source": r["time"]}
          latest_source = r["time"] if latest_source is None else max(latest_source, r["time"])
        elif tid in state_by_id and t - state_by_id[tid]["source"] > 0.20:
          state_by_id.pop(tid, None)
      if tid in state_by_id and t - state_by_id[tid]["source"] > 0.20:
        state_by_id.pop(tid, None)
    result.append((t, dict(state_by_id), latest_source))
  return result


def live_points(rows: list[dict], times: list[float]):
  result = []
  index = 0
  current = []
  source = None
  for t in times:
    while index < len(rows) and rows[index]["time"] <= t:
      current = {p["id"]: p for p in rows[index]["points"]}
      source = index
      index += 1
    if source is None or (rows[source]["time"] < t - 0.20):
      current = {}
    result.append((t, dict(current), source))
  return result


def run_sim(model_rows, source_rows, source_kind: str):
  tracks = {}
  prev_ids = [-1, -1]
  prob_filters = [0.0, 0.0]
  alpha = DT_MDL / (0.2 + DT_MDL)
  out = []
  for model, source in zip(model_rows, source_rows):
    _, points, source_seq = source
    fresh = source_seq is not None and (not out or source_seq != out[-1]["source_seq"])
    for tid in list(tracks):
      if tid not in points:
        tracks.pop(tid, None)
    for tid, p in points.items():
      if tid not in tracks:
        tracks[tid] = KfTrack(tid, p["v"] + model["vego"])
      measurement = bool(p.get("measured", True) and fresh)
      tracks[tid].update(p, model["vego"], measurement)

    leads = []
    for i in range(2):
      raw = model["leads"][i]["prob"]
      if raw > prob_filters[i]:
        prob_filters[i] = raw
      else:
        prob_filters[i] = (1.0 - alpha) * prob_filters[i] + alpha * raw
      leads.append(choose_lead(tracks, model["leads"][i], model["vego"], model["model_vego"],
                               prob_filters[i], prev_ids[i], low_speed=(i == 0)))
    for i, lead in enumerate(leads):
      if lead["status"] and lead["radar"]:
        prev_ids[i] = lead["id"]
      elif not lead["status"] or prev_ids[i] not in tracks:
        prev_ids[i] = -1
    row = {"time": model["time"], "source_seq": source_seq}
    for i, lead in enumerate(leads, 1):
      for k in ("status", "id", "d", "y", "v", "vlead", "vleadk", "aleadk", "radar"):
        row[f"lead{i}_{k}"] = lead[k]
    out.append(row)
  return out


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--candidate-csv", type=Path, required=True)
  ap.add_argument("--log-glob", nargs="+", type=Path, required=True)
  ap.add_argument("--out", type=Path, required=True)
  args = ap.parse_args()
  selected = {("0000010c", 11), ("00000125", 4), ("00000125", 6), ("00000125", 11)}
  candidates = {"A3", "A4B3", "A4", "A5", "B4", "B5"}
  paths = sorted({Path(p) for pattern in args.log_glob for p in glob.glob(str(pattern))})
  routes = {r for r, _ in selected}
  models, cars, live, radar = parse_logs(paths, routes, selected)
  candidate_rows = read_candidate_rows(args.candidate_csv, selected, candidates)
  all_results = []
  event_results = []
  event_track_rows = []
  for key in sorted(selected):
    if key not in models:
      continue
    model_rows = models[key]
    times = [m["time"] for m in model_rows]
    current = run_sim(model_rows, live_points(live.get(key, []), times), "CURRENT_42C2")
    actual = radar.get(key, [])
    actual_by_time = [nearest(actual, t, 0.10) for t in times]
    source_by_candidate = {c: candidate_points(candidate_rows.get(key, []), times, c) for c in candidates}
    sims = {c: run_sim(model_rows, source_by_candidate[c], c) for c in candidates}
    for i, t in enumerate(times):
      row = {"route": key[0], "segment": key[1], "time": t, "vEgo": model_rows[i]["vego"]}
      act = actual_by_time[i]
      if act:
        for j, lead in enumerate(act["leads"], 1):
          for k, v in lead.items():
            row[f"CURRENT_42C2_lead{j}_{k}"] = v
      for c, sim in sims.items():
        for k, v in sim[i].items():
          if k != "time" and k != "source_seq":
            row[f"{c}_{k}"] = v
      for k, v in current[i].items():
        if k not in ("time", "source_seq"):
          row[f"CURRENT_SIM_{k}"] = v
      all_results.append(row)
      if key in (("0000010c", 11), ("00000125", 4), ("00000125", 6), ("00000125", 11)):
        event_results.append(row)
    # Preserve every physical observation for the requested native IDs, not only model-matched
    # rows or observations that happened to be leadOne at a model cycle.
    event_ids = {("0000010c", 11): 23, ("00000125", 4): 50,
                 ("00000125", 6): 22, ("00000125", 11): 35}
    if key in event_ids:
      tid = event_ids[key]
      rows_by_time = {}
      for r in candidate_rows.get(key, []):
        if r["track_id"] == tid and r["candidate"] in ("A3", "A4B3", "A4", "A5"):
          rows_by_time.setdefault(r["time"], {})[r["candidate"]] = r
      for t, vals in sorted(rows_by_time.items()):
        a3 = vals.get("A3", {}); a4b3 = vals.get("A4B3", {})
        a4 = vals.get("A4", {}); a5 = vals.get("A5", {})
        current_lt = previous_event(live.get(key, []), t)
        current_point = None
        if current_lt is not None:
          current_point = next((p for p in current_lt["points"] if p["id"] == tid), None)
        actual = nearest(radar.get(key, []), t, 0.15)
        model_row = nearest(all_results_for_key := [r for r in all_results
                                                     if r["route"] == key[0] and r["segment"] == key[1]], t, 0.15)
        out = {"route": key[0], "segment": key[1], "time": t, "track_id": tid,
               "dRel": a4.get("x", ""), "yRel": a4.get("y", ""),
               "lifecycle": a4.get("lifecycle", ""), "frame_idx": a4.get("frame_idx", ""),
               "current_liveTracks_vRel": current_point["v"] if current_point else "",
               "current_liveTracks_measured": current_point["measured"] if current_point else "",
               "A3_vRel": a3.get("vRel", ""), "A4B3_vRel": a4b3.get("vRel", ""),
               "A4_vRel": a4.get("vRel", ""), "A5_vRel": a5.get("vRel", ""),
               "U11": a4.get("U11", ""), "U10": a4.get("U10", ""), "00CA": a4.get("00CA", ""),
               "current_radarState_leadOne_id": actual["leads"][0]["id"] if actual else "",
               "current_aLeadK": actual["leads"][0]["aleadk"] if actual else ""}
        for c in ("A3", "A4B3", "A4", "A5"):
          lead = None
          if model_row:
            for j in (1, 2):
              if model_row.get(f"{c}_lead{j}_id") == tid:
                lead = j
                break
          out[f"{c}_lead_number"] = lead or ""
          out[f"{c}_aLeadK"] = model_row.get(f"{c}_lead{lead}_aleadk", "") if lead else ""
          out[f"{c}_lead_id"] = model_row.get(f"{c}_lead{lead}_id", "") if lead else ""
        event_track_rows.append(out)
  args.out.parent.mkdir(parents=True, exist_ok=True)
  with args.out.open("w", newline="") as f:
    fields = sorted({k for r in all_results for k in r})
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(all_results)
  event_path = args.out.with_name("bosch_radard_event_comparison.csv")
  with event_path.open("w", newline="") as f:
    fields = sorted({k for r in event_results for k in r})
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(event_results)
  tracks_path = args.out.with_name("bosch_radard_event_tracks.csv")
  with tracks_path.open("w", newline="") as f:
    fields = sorted({k for r in event_track_rows for k in r})
    w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(event_track_rows)
  print(f"events={len(event_results)} rows={len(all_results)} output={args.out}")


if __name__ == "__main__":
  main()
