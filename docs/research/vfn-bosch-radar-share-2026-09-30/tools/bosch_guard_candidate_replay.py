#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cereal import log
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import (
  T_IDXS,
  build_model_lead_trajectory,
)
from openpilot.selfdrive.controls.lib.longitudinal_planner import CONTROL_N_T_IDX, LongitudinalPlanner
from openpilot.tools.lib.logreader import LogReader, ReadMode
from openpilot.tools.longitudinal.score_route_longitudinal import REQUIRED_SERVICES, default_toggles, parse_toggles


RADAR_TO_CAMERA = 1.52


@dataclass(frozen=True)
class Event:
  name: str
  route: str
  target: float
  before: float = 12.0
  after: float = 12.0

  @property
  def segment(self) -> int:
    return int(self.target // 60)


EVENTS = (
  Event("r1c7_012346", "11c8fa231c0499ed/000001c7--e2038c162d", 5026.0),
  Event("r1c7_014250", "11c8fa231c0499ed/000001c7--e2038c162d", 6170.0),
  Event("r1c7_015219", "11c8fa231c0499ed/000001c7--e2038c162d", 6739.0),
  Event("r1c7_020300", "11c8fa231c0499ed/000001c7--e2038c162d", 7380.0),
  Event("r1c9_021946", "11c8fa231c0499ed/000001c9--ec79f83531", 8386.0),
  Event("r1c9_024930", "11c8fa231c0499ed/000001c9--ec79f83531", 10170.0),
  Event("r1c9_025018", "11c8fa231c0499ed/000001c9--ec79f83531", 10218.0),
  Event("r1c9_025253", "11c8fa231c0499ed/000001c9--ec79f83531", 10373.0),
  Event("r1c9_025645", "11c8fa231c0499ed/000001c9--ec79f83531", 10605.0),
  Event("r1cb_0928", "11c8fa231c0499ed/000001cb--49bc3c73ac", 568.0),
  Event("r1d1_fcw_0349", "11c8fa231c0499ed/000001d1--43392afe10", 229.0),
  Event("r1d1_floor_1019", "11c8fa231c0499ed/000001d1--43392afe10", 619.0),
)


def strict_match(lead, model_lead, v_ego: float) -> bool:
  if not bool(lead.status) or not bool(lead.radar) or float(model_lead.prob) <= 0.0:
    return False
  expected_d = float(model_lead.x[0]) - RADAR_TO_CAMERA
  d_ok = abs(float(lead.dRel) - expected_d) < max(abs(expected_d) * 0.25, 5.0)
  absolute_v = float(lead.vRel) + v_ego
  v_ok = abs(absolute_v - float(model_lead.v[0])) < 10.0 or absolute_v > 3.0
  y_ok = abs(float(lead.yRel) + float(model_lead.y[0])) < max(1.0, max(float(model_lead.yStd[0]), 0.2))
  return bool(d_ok and v_ok and y_ok)


def radar_with_counterfactual_fcw(radar_state, model_v2, v_ego: float):
  out = log.RadarState.new_message()
  out.leadOne = radar_state.leadOne.to_dict()
  out.leadTwo = radar_state.leadTwo.to_dict()
  out.carStateMonoTime = radar_state.carStateMonoTime
  out.mdMonoTime = radar_state.mdMonoTime
  leads = model_v2.leadsV3
  for index, name in enumerate(("leadOne", "leadTwo")):
    lead = getattr(out, name)
    if bool(lead.radar) and index < len(leads) and not strict_match(lead, leads[index], v_ego):
      lead.fcw = False
  return out


def planner_row(event: Event, t: float, planner: LongitudinalPlanner, state: dict, logged_plan) -> dict:
  car = state["carState"]
  radar = state["radarState"]
  lead = radar.leadOne
  model_lead = state["modelV2"].leadsV3[0]
  v_ego = float(car.vEgo)
  closing = max(0.0, v_ego - float(lead.vLead)) if lead.status else 0.0
  ttc = float(lead.dRel) / closing if closing > 0.1 else math.inf
  usable_gap = max(float(lead.dRel) - 6.0, 1e-3) if lead.status else math.inf
  required_decel = closing ** 2 / (2.0 * usable_gap) if lead.status else 0.0
  model_path = build_model_lead_trajectory(
    model_lead,
    lead,
    v_ego,
    raw_geometry_guard=bool(planner.mpc.raw_geometry_model_guard and lead.radar),
  )
  action_t = float(planner.longitudinal_actuator_delay + 0.05)
  direct_accel = float(np.interp(action_t, CONTROL_N_T_IDX, planner.a_desired_trajectory))
  return {
    "event": event.name,
    "t": t,
    "logged_aTarget": float(logged_plan.aTarget) if logged_plan is not None else math.nan,
    "replay_aTarget": float(planner.output_a_target),
    "source": str(planner.mpc.source),
    "fcw": bool(planner.fcw),
    "crashCnt": int(planner.mpc.crash_cnt),
    "directAccel": direct_accel,
    "vEgo": v_ego,
    "leadRadar": bool(lead.radar),
    "leadId": int(lead.radarTrackId),
    "leadFcwEligible": bool(lead.fcw),
    "strictMatch": strict_match(lead, model_lead, v_ego),
    "dRel": float(lead.dRel),
    "yRel": float(lead.yRel),
    "vRel": float(lead.vRel),
    "vLead": float(lead.vLead),
    "aLeadK": float(lead.aLeadK),
    "modelX": float(model_lead.x[0]),
    "modelY": float(model_lead.y[0]),
    "modelV": float(model_lead.v[0]),
    "modelA": float(model_lead.a[0]),
    "ttc": ttc,
    "requiredDecel": required_decel,
    "modelTrajectoryUsed": model_path is not None,
  }


def run_event(event: Event, simulate_radard_fcw: bool) -> list[dict]:
  messages = list(LogReader(f"{event.route}/{event.segment}/r", default_mode=ReadMode.RLOG, sort_by_time=True))
  car_times = [m.logMonoTime * 1e-9 for m in messages if m.which() == "carState"]
  route_base = min(car_times) - event.segment * 60.0
  state: dict[str, object] = {}
  planner = None
  toggles = default_toggles()
  logged_plan = None
  rows = []

  for msg in messages:
    which = msg.which()
    if which == "carParams" and planner is None:
      planner = LongitudinalPlanner(msg.carParams)
      continue
    if which == "longitudinalPlan":
      logged_plan = msg.longitudinalPlan
      continue
    if which not in REQUIRED_SERVICES and which != "modelV2":
      continue
    state[which] = getattr(msg, which)
    if which == "starpilotPlan":
      toggles = parse_toggles(state["starpilotPlan"].starpilotToggles, toggles)
    if which != "modelV2" or planner is None or not REQUIRED_SERVICES.issubset(state):
      continue

    if simulate_radard_fcw:
      state["radarState"] = radar_with_counterfactual_fcw(state["radarState"], state["modelV2"], float(state["carState"].vEgo))
    planner.update(state, toggles)
    t = msg.logMonoTime * 1e-9 - route_base
    if event.target - event.before <= t <= event.target + event.after:
      rows.append(planner_row(event, t, planner, state, logged_plan))
  return rows


def write_csv(path: Path, rows: list[dict]) -> None:
  with path.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--output", type=Path, required=True)
  parser.add_argument("--simulate-radard-fcw", action="store_true")
  args = parser.parse_args()
  rows = []
  for event in EVENTS:
    rows.extend(run_event(event, args.simulate_radard_fcw))
  write_csv(args.output, rows)

  summary = {}
  for event in EVENTS:
    event_rows = [row for row in rows if row["event"] == event.name]
    worst = min(event_rows, key=lambda row: row["replay_aTarget"])
    summary[event.name] = {
      "minReplay": worst["replay_aTarget"],
      "minLogged": min(row["logged_aTarget"] for row in event_rows),
      "minTime": worst["t"],
      "floorCycles": sum(row["replay_aTarget"] <= -3.4 for row in event_rows),
      "fcwCycles": sum(row["fcw"] for row in event_rows),
      "maxCrashCnt": max(row["crashCnt"] for row in event_rows),
      "modelTrajectoryFraction": sum(row["modelTrajectoryUsed"] for row in event_rows) / len(event_rows),
      "worst": worst,
    }
  args.output.with_suffix(".json").write_text(json.dumps(summary, indent=2, allow_nan=True) + "\n")
  print(args.output)


if __name__ == "__main__":
  main()
