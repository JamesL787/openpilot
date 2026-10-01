#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import defaultdict

from openpilot.tools.lib.logreader import LogReader, ReadMode


ROUTE = "11c8fa231c0499ed/000001d1--43392afe10"
EVENTS = {
  "crazy_0346": (3, 226.0),
  "far_brake_0456": (4, 296.0),
  "red_alert_1000": (10, 600.0),
  "similar_1021": (10, 621.0),
  "red_alert_1400": (14, 840.0),
  "brake_stab_1720": (17, 1040.0),
}


def enum_name(value) -> str:
  text = str(value)
  return text.rsplit(".", 1)[-1]


def lead_dict(lead) -> dict:
  return {
    "status": bool(lead.status),
    "radar": bool(lead.radar),
    "id": int(lead.radarTrackId),
    "dRel": float(lead.dRel),
    "yRel": float(lead.yRel),
    "vRel": float(lead.vRel),
    "vLead": float(lead.vLead),
    "vLeadK": float(lead.vLeadK),
    "aLeadK": float(lead.aLeadK),
    "aLeadTau": float(lead.aLeadTau),
    "modelProb": float(lead.modelProb),
    "fcw_field": bool(lead.fcw),
  }


def model_lead_dict(lead) -> dict:
  def first(values, default=math.nan):
    return float(values[0]) if len(values) else default
  return {
    "prob": float(lead.prob),
    "x": first(lead.x),
    "y": first(lead.y),
    "v": first(lead.v),
    "a": first(lead.a),
    "xStd": first(lead.xStd),
    "yStd": first(lead.yStd),
    "vStd": first(lead.vStd),
  }


def main_ids(slot: int) -> tuple[int, int, int, int]:
  base = 0x280 + 4 * slot if slot < 4 else 0x2D0 + 4 * (slot - 4)
  return tuple(base + i for i in range(4))


def aux_id(slot: int) -> int:
  return 0x2C8 + slot if slot < 8 else 0x290 + slot - 8


ADDR = {}
for slot in range(16):
  for kind, address in zip(("F0", "F1", "F2", "F3"), main_ids(slot), strict=True):
    ADDR[address] = (slot, kind)
  ADDR[aux_id(slot)] = (slot, "AUX")


def frame_idx(kind: str, b: bytes) -> int:
  return {"F0": b[3] & 0xF, "F1": (b[3] >> 1) & 0xF,
          "F2": b[1] & 0xF, "F3": (b[1] >> 1) & 0xF,
          "AUX": (b[1] >> 1) & 0xF}[kind]


def nearest(rows: list[dict], t: float, limit: float = 0.2) -> dict | None:
  if not rows:
    return None
  times = [r["t"] for r in rows]
  pos = bisect.bisect_left(times, t)
  candidates = rows[max(0, pos - 2):pos + 2]
  best = min(candidates, key=lambda r: abs(r["t"] - t), default=None)
  return best if best is not None and abs(best["t"] - t) <= limit else None


def load_segment(segment: int) -> dict[str, list[dict]]:
  identifier = f"{ROUTE}/{segment}/r"
  messages = list(LogReader(identifier, default_mode=ReadMode.RLOG, sort_by_time=True))
  car_times = [m.logMonoTime * 1e-9 for m in messages if m.which() == "carState"]
  route_base = min(car_times) - segment * 60.0
  rows: dict[str, list[dict]] = defaultdict(list)
  slot_frames: list[dict[str, tuple[float, bytes]]] = [dict() for _ in range(16)]
  last_raw_key = [None] * 16

  for msg in messages:
    which = msg.which()
    t = msg.logMonoTime * 1e-9 - route_base
    if which == "carState":
      cs = msg.carState
      rows[which].append({"t": t, "vEgo": float(cs.vEgo), "aEgo": float(cs.aEgo),
                          "gas": bool(cs.gasPressed), "brake": bool(cs.brakePressed),
                          "stockFcw": bool(cs.stockFcw), "stockAeb": bool(cs.stockAeb)})
    elif which == "radarState":
      rs = msg.radarState
      rows[which].append({"t": t, "leadOne": lead_dict(rs.leadOne), "leadTwo": lead_dict(rs.leadTwo)})
    elif which == "modelV2":
      model = msg.modelV2
      leads = list(model.leadsV3)
      rows[which].append({"t": t,
                          "lead0": model_lead_dict(leads[0]) if len(leads) > 0 else None,
                          "lead1": model_lead_dict(leads[1]) if len(leads) > 1 else None,
                          "hardBrakePredicted": bool(model.meta.hardBrakePredicted),
                          "modelVego": float(model.velocity.x[0]) if len(model.velocity.x) else math.nan})
    elif which == "longitudinalPlan":
      lp = msg.longitudinalPlan
      rows[which].append({"t": t, "aTarget": float(lp.aTarget), "shouldStop": bool(lp.shouldStop),
                          "source": enum_name(lp.longitudinalPlanSource), "fcw": bool(lp.fcw),
                          "hasLead": bool(lp.hasLead),
                          "speeds": [float(x) for x in list(lp.speeds)[:6]],
                          "accels": [float(x) for x in list(lp.accels)[:6]]})
    elif which == "selfdriveState":
      ss = msg.selfdriveState
      rows[which].append({"t": t, "enabled": bool(ss.enabled), "active": bool(ss.active),
                          "alertText1": str(ss.alertText1), "alertText2": str(ss.alertText2),
                          "alertType": str(ss.alertType), "alertStatus": enum_name(ss.alertStatus)})
    elif which == "controlsState":
      cs = msg.controlsState
      rows[which].append({"t": t, "longControlState": enum_name(cs.longControlState)})
    elif which == "carControl":
      cc = msg.carControl
      rows[which].append({"t": t, "accel": float(cc.actuators.accel),
                          "longActive": bool(cc.longActive),
                          "visualAlert": enum_name(cc.hudControl.visualAlert)})
    elif which in ("onroadEvents", "alertDebug", "userBookmark", "bookmarkButton"):
      try:
        payload = getattr(msg, which).to_dict()
      except Exception:
        payload = str(getattr(msg, which))
      rows[which].append({"t": t, "payload": payload})
    elif which == "can":
      for c in msg.can:
        if int(c.src) != 2:
          continue
        address = int(c.address)
        dat = bytes(c.dat)
        if address in ADDR:
          slot, kind = ADDR[address]
          slot_frames[slot][kind] = (t, dat)
          f = slot_frames[slot]
          if not all(k in f for k in ("F0", "F1", "F2", "F3")):
            continue
          idxs = [frame_idx(k, f[k][1]) for k in ("F0", "F1", "F2", "F3")]
          if len(set(idxs)) != 1:
            continue
          f3 = f["F3"][1]
          track_id = int(f3[6])
          key = (idxs[0], track_id, f["F2"][1][0], f["F2"][1][1])
          aux = f.get("AUX")
          if aux is None or frame_idx("AUX", aux[1]) != idxs[0]:
            continue
          if key == last_raw_key[slot]:
            continue
          last_raw_key[slot] = key
          raw_range = (f["F0"][1][2] << 4) | (f["F0"][1][3] >> 4)
          raw_angle = (f["F0"][1][4] << 3) | (f["F0"][1][5] >> 5)
          range_sigma = (f["F0"][1][0] >> 1) & 0x7F
          status = (f["F0"][1][1] >> 4) & 0xF
          existence = f["F1"][1][5] & 0x7F
          lifecycle = (f["F2"][1][0] << 4) | (f["F2"][1][1] >> 4)
          u11 = (aux[1][0] << 3) | (aux[1][1] >> 5)
          u10 = (aux[1][2] << 2) | (aux[1][3] >> 6)
          rows["rawRadar"].append({"t": max(v[0] for v in f.values()), "slot": slot, "id": track_id,
                                   "dRel": raw_range * 0.05712 - 3.0,
                                   "frameIdx": idxs[0], "lifecycle": lifecycle,
                                   "status": status, "rangeSigma": range_sigma, "existence": existence,
                                   "angleRaw": raw_angle, "U11": u11, "U10": u10,
                                   "u11Vrel": (u11 - 864) / 64.0,
                                   "rail": u11 in (0, 1728), "qualifiedCurrent": u10 <= 255})

        # Honda Bosch ACC_CONTROL (0x1DF) raw command fields, retained for actuator proof.
        if address == 0x1DF and len(dat) >= 8:
          rows["accControlCan"].append({"t": t, "address": address, "dat": dat.hex()})

  for service_rows in rows.values():
    service_rows.sort(key=lambda r: r["t"])
  return rows


def summarize_event(name: str, segment: int, target: float, rows: dict[str, list[dict]], radius: float) -> dict:
  lo, hi = target - radius, target + radius
  planner = [r for r in rows["longitudinalPlan"] if lo <= r["t"] <= hi]
  selfdrive = [r for r in rows["selfdriveState"] if lo <= r["t"] <= hi]
  if not planner:
    return {"name": name, "target": target, "error": "no planner rows"}
  min_plan = min(planner, key=lambda r: r["aTarget"])
  alert_rows = [r for r in selfdrive if r["alertText1"] or r["alertText2"] or "fcw" in r["alertType"].lower()]
  hard_models = [r for r in rows["modelV2"] if lo <= r["t"] <= hi and r["hardBrakePredicted"]]
  fcw_plans = [r for r in planner if r["fcw"]]

  # First material target drop; avoids assuming the bookmark itself is the onset.
  onset = None
  for prev, cur in zip(planner, planner[1:], strict=False):
    if cur["aTarget"] - prev["aTarget"] <= -0.35 and cur["t"] - prev["t"] <= 0.15:
      onset = {"previous": prev, "current": cur}
      break
  focus_t = onset["current"]["t"] if onset else min_plan["t"]
  radar = nearest(rows["radarState"], focus_t)
  model = nearest(rows["modelV2"], focus_t)
  car = nearest(rows["carState"], focus_t)
  control = nearest(rows["carControl"], focus_t)
  state = nearest(rows["selfdriveState"], focus_t)
  selected_id = radar["leadOne"]["id"] if radar and radar["leadOne"]["status"] else -1
  raw = [r for r in rows["rawRadar"] if r["id"] == selected_id and lo <= r["t"] <= hi]
  raw_near = nearest(raw, focus_t, 0.25)

  critical_times = [target, min_plan["t"]]
  if fcw_plans:
    critical_times.append(fcw_plans[0]["t"])
  if alert_rows:
    critical_times.append(alert_rows[0]["t"])
  snapshots = []
  for critical_t in sorted(set(critical_times)):
    critical_radar = nearest(rows["radarState"], critical_t)
    critical_id = critical_radar["leadOne"]["id"] if critical_radar and critical_radar["leadOne"]["status"] else -1
    critical_raw = nearest([r for r in rows["rawRadar"] if r["id"] == critical_id], critical_t, 0.25)
    snapshots.append({
      "t": critical_t,
      "planner": nearest(rows["longitudinalPlan"], critical_t),
      "radar": critical_radar,
      "raw": critical_raw,
      "model": nearest(rows["modelV2"], critical_t),
      "car": nearest(rows["carState"], critical_t),
      "carControl": nearest(rows["carControl"], critical_t),
      "selfdrive": nearest(rows["selfdriveState"], critical_t),
    })

  return {
    "name": name, "segment": segment, "target": target, "window": [lo, hi],
    "plannerMin": min_plan,
    "onset": onset,
    "focusTime": focus_t,
    "radar": radar,
    "rawSelected": raw_near,
    "rawSelectedSequence": raw,
    "model": model,
    "car": car,
    "carControl": control,
    "selfdrive": state,
    "alertRows": alert_rows,
    "plannerFcwRows": fcw_plans,
    "modelHardBrakeRows": hard_models,
    "onroadEvents": [r for r in rows["onroadEvents"] if lo <= r["t"] <= hi],
    "bookmarks": [r for k in ("userBookmark", "bookmarkButton") for r in rows[k] if lo <= r["t"] <= hi],
    "snapshots": snapshots,
  }


def run(radius: float) -> dict:
  by_segment = {}
  output = {}
  for name, (segment, target) in EVENTS.items():
    needed_segments = sorted({segment, max(0, int((target - radius) // 60)), int((target + radius) // 60)})
    for needed in needed_segments:
      if needed not in by_segment:
        by_segment[needed] = load_segment(needed)
    merged: dict[str, list[dict]] = defaultdict(list)
    for needed in needed_segments:
      for service, service_rows in by_segment[needed].items():
        merged[service].extend(service_rows)
    for service_rows in merged.values():
      service_rows.sort(key=lambda r: r["t"])
    output[name] = summarize_event(name, segment, target, merged, radius)
  return output


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--radius", type=float, default=12.0)
  parser.add_argument("--output")
  args = parser.parse_args()
  result = run(args.radius)
  text = json.dumps(result, indent=2, allow_nan=True)
  if args.output:
    with open(args.output, "w") as f:
      f.write(text + "\n")
  else:
    print(text)
