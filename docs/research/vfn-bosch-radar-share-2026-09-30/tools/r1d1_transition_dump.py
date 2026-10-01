#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
from pathlib import Path

from r1d1_event_analyzer import load_segment, nearest


RADAR_TO_CAMERA = 1.52
WINDOWS = {
  "fcw_0349": (3, 227.0, 231.0),
  "floor_1019": (10, 616.0, 621.5),
}


def match_metrics(lead: dict | None, model: dict | None, v_ego: float) -> dict:
  if lead is None or model is None:
    return {}
  expected_d = model["x"] - RADAR_TO_CAMERA
  d_error = abs(lead["dRel"] - expected_d)
  d_allow = max(abs(expected_d) * 0.25, 5.0)
  y_error = abs(lead["yRel"] + model["y"])
  y_allow = max(1.0, max(model["yStd"], 0.2))
  v_abs = lead["vRel"] + v_ego
  v_error = abs(v_abs - model["v"])
  v_pass = v_error < 10.0 or v_abs > 3.0
  return {
    "d_error": d_error, "d_allow": d_allow, "d_pass": d_error < d_allow,
    "y_error": y_error, "y_allow": y_allow, "y_pass": y_error < y_allow,
    "v_error": v_error, "v_pass": v_pass,
  }


def main() -> None:
  out_dir = Path("/tmp/r1d1_transition_dump")
  out_dir.mkdir(exist_ok=True)
  for name, (segment, lo, hi) in WINDOWS.items():
    rows = load_segment(segment)
    out = []
    for radar in rows["radarState"]:
      t = radar["t"]
      if not lo <= t <= hi:
        continue
      car = nearest(rows["carState"], t, 0.15)
      model = nearest(rows["modelV2"], t, 0.15)
      plan = nearest(rows["longitudinalPlan"], t, 0.15)
      selfdrive = nearest(rows["selfdriveState"], t, 0.15)
      row = {
        "t": t,
        "vEgo": car["vEgo"] if car else math.nan,
        "aEgo": car["aEgo"] if car else math.nan,
        "aTarget": plan["aTarget"] if plan else math.nan,
        "source": plan["source"] if plan else "",
        "plannerFcw": plan["fcw"] if plan else False,
        "alertType": selfdrive["alertType"] if selfdrive else "",
      }
      for i, lead_name in enumerate(("leadOne", "leadTwo")):
        prefix = f"L{i}"
        lead = radar[lead_name]
        model_lead = model[f"lead{i}"] if model else None
        raw = nearest([r for r in rows["rawRadar"] if r["id"] == lead["id"]], t, 0.2) if lead["id"] >= 0 else None
        row |= {
          f"{prefix}_status": lead["status"], f"{prefix}_radar": lead["radar"], f"{prefix}_id": lead["id"],
          f"{prefix}_dRel": lead["dRel"], f"{prefix}_yRel": lead["yRel"], f"{prefix}_vRel": lead["vRel"],
          f"{prefix}_vLead": lead["vLead"], f"{prefix}_aLeadK": lead["aLeadK"], f"{prefix}_prob": lead["modelProb"],
          f"M{i}_x": model_lead["x"] if model_lead else math.nan,
          f"M{i}_y": model_lead["y"] if model_lead else math.nan,
          f"M{i}_v": model_lead["v"] if model_lead else math.nan,
          f"M{i}_a": model_lead["a"] if model_lead else math.nan,
          f"M{i}_prob": model_lead["prob"] if model_lead else math.nan,
          f"{prefix}_rawSlot": raw["slot"] if raw else "", f"{prefix}_life": raw["lifecycle"] if raw else "",
          f"{prefix}_U11": raw["U11"] if raw else "", f"{prefix}_U10": raw["U10"] if raw else "",
        }
        row |= {f"{prefix}_{key}": value for key, value in match_metrics(lead, model_lead, row["vEgo"]).items()}
      out.append(row)
    path = out_dir / f"{name}.csv"
    with path.open("w", newline="") as f:
      writer = csv.DictWriter(f, fieldnames=list(out[0]))
      writer.writeheader()
      writer.writerows(out)
    print(path)


if __name__ == "__main__":
  main()
