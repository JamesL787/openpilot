#!/usr/bin/env python3
from __future__ import annotations

import json
import math

from r1d1_event_analyzer import load_segment, nearest


SEGMENTS = (3, 9, 10, 13, 14)


def intervals(rows: list[dict], predicate) -> list[tuple[float, float]]:
  result = []
  start = None
  last = None
  for row in rows:
    active = predicate(row)
    if active and start is None:
      start = row["t"]
    if not active and start is not None:
      result.append((start, last if last is not None else start))
      start = None
    last = row["t"]
  if start is not None:
    result.append((start, last if last is not None else start))
  return result


def snapshot(rows: dict[str, list[dict]], t: float) -> dict:
  radar = nearest(rows["radarState"], t, 0.25)
  lead_id = radar["leadOne"]["id"] if radar and radar["leadOne"]["status"] else -1
  raw = nearest([r for r in rows["rawRadar"] if r["id"] == lead_id], t, 0.25)
  car = nearest(rows["carState"], t, 0.25)
  model = nearest(rows["modelV2"], t, 0.25)
  plan = nearest(rows["longitudinalPlan"], t, 0.25)
  closing = math.nan
  ttc = math.nan
  if car and radar and radar["leadOne"]["status"]:
    lead = radar["leadOne"]
    closing = car["vEgo"] - lead["vLead"]
    if closing > 0.01:
      ttc = lead["dRel"] / closing
  return {"t": t, "radar": radar, "raw": raw, "car": car, "model": model,
          "plan": plan, "closing": closing, "ttc": ttc,
          "selfdrive": nearest(rows["selfdriveState"], t, 0.25)}


def main() -> None:
  output = {}
  for segment in SEGMENTS:
    rows = load_segment(segment)
    plan_fcw = intervals(rows["longitudinalPlan"], lambda r: r["fcw"])
    ui_fcw = intervals(rows["selfdriveState"], lambda r: "fcw" in r["alertType"].lower())
    hard_model = intervals(rows["modelV2"], lambda r: r["hardBrakePredicted"])
    times = sorted({round(t, 6) for pair in plan_fcw + ui_fcw + hard_model for t in pair})
    output[str(segment)] = {
      "planFcw": plan_fcw,
      "uiFcw": ui_fcw,
      "modelHardBrake": hard_model,
      "snapshots": [snapshot(rows, t) for t in times],
    }
  print(json.dumps(output, indent=2, allow_nan=True))


if __name__ == "__main__":
  main()
