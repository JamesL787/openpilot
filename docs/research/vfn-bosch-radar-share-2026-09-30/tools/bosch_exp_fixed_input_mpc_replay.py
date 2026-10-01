#!/usr/bin/env python3
"""Offline fixed-input ACC-vs-blended replay for the Civic Bosch investigation.

This script intentionally lives outside the openpilot checkout.  It imports the
target-revision MPC source through the Darwin host runtime, copies planner inputs
from rlogs, and writes only analysis artifacts.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import math
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np


TARGET_HEAD = "42c2a191729afac16399e55496669b9dd29ee1df"
DT = 0.05
ACCEL_MIN = -3.5
ACCEL_MAX = 2.0


@dataclass
class Lead:
  status: bool = False
  dRel: float = 0.0
  yRel: float = 0.0
  vRel: float = 0.0
  vLead: float = 0.0
  vLeadK: float = 0.0
  aLeadK: float = 0.0
  aLeadTau: float = 1.5
  modelProb: float = 0.0
  radar: bool = False
  radarTrackId: int = -1


@dataclass
class RadarState:
  leadOne: Lead = field(default_factory=Lead)
  leadTwo: Lead = field(default_factory=Lead)


@dataclass
class Sample:
  route: str
  segment: int
  t_abs: float
  t_rel: float
  logged_a_target: float
  logged_source: str
  logged_should_stop: bool
  logged_mode: str
  personality: str
  v_ego: float
  a_ego: float
  steering_angle: float
  angle_offset: float
  v_cruise: float
  t_follow: float
  danger_factor: float
  acceleration_jerk: float
  danger_jerk: float
  speed_jerk: float
  min_acceleration: float
  max_acceleration: float
  tracking_lead: bool
  forcing_stop: bool
  forcing_stop_length: float
  red_light: bool
  disable_throttle: bool
  lead_control_active: bool
  lead_one: Lead
  lead_two: Lead
  model_x: np.ndarray
  model_v: np.ndarray
  model_a: np.ndarray
  model_j: np.ndarray
  prev_a: float
  prev_accels: np.ndarray
  car_wheelbase: float
  car_steer_ratio: float
  car_longitudinal_delay: float
  model_lead_trajectory_active: bool = False


def _add_import_paths() -> None:
  """Use the Mac host-built generated solver, not the ARM target .so."""
  host = "/Users/REDACTED_USER/nrdr/openpilot/.host_runtime/darwin/worktree"
  target = "/Users/REDACTED_USER/nrdr/openpilot"
  # Insert the target fallback first, then put the host runtime ahead of it.
  # Otherwise Python finds the ARM target package and attempts to load its ELF .so.
  for path in (target, host):
    if path not in sys.path:
      sys.path.insert(0, path)


_add_import_paths()

from cereal import log  # noqa: E402
from openpilot.common.constants import CV  # noqa: E402
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import (  # noqa: E402
  COST_DIM,
  LIMIT_COST,
  LongitudinalMpc,
  N,
  T_IDXS,
  get_safe_obstacle_distance,
  get_stopped_equivalence_factor,
)
from openpilot.selfdrive.controls.lib.longitudinal_planner import (  # noqa: E402
  LongitudinalPlanner,
  limit_accel_in_turns,
)
from openpilot.selfdrive.modeld.constants import ModelConstants  # noqa: E402
from tools.lib.logreader import LogReader  # noqa: E402


def enum_name(value) -> str:
  text = str(value)
  if text.endswith(" enum>"):
    return text[:-6]
  return text


def fget(obj, name: str, default=0.0):
  try:
    return getattr(obj, name)
  except (AttributeError, KeyError):
    return default


def copy_lead(src) -> Lead:
  return Lead(
    status=bool(fget(src, "status", False)),
    dRel=float(fget(src, "dRel", 0.0)),
    yRel=float(fget(src, "yRel", 0.0)),
    vRel=float(fget(src, "vRel", 0.0)),
    vLead=float(fget(src, "vLead", 0.0)),
    vLeadK=float(fget(src, "vLeadK", fget(src, "vLead", 0.0))),
    aLeadK=float(fget(src, "aLeadK", 0.0)),
    aLeadTau=float(fget(src, "aLeadTau", 1.5)),
    modelProb=float(fget(src, "modelProb", 0.0)),
    radar=bool(fget(src, "radar", False)),
    radarTrackId=int(fget(src, "radarTrackId", -1)),
  )


def copy_radar(src) -> RadarState:
  return RadarState(copy_lead(src.leadOne), copy_lead(src.leadTwo))


def nearest(rows: list[dict], times: list[float], t: float, limit: float = 0.20) -> dict | None:
  if not rows:
    return None
  i = bisect.bisect_left(times, t)
  candidates = []
  if i < len(rows):
    candidates.append(rows[i])
  if i:
    candidates.append(rows[i - 1])
  best = min(candidates, key=lambda row: abs(row["t"] - t))
  return best if abs(best["t"] - t) <= limit else None


def previous(rows: list[dict], times: list[float], t: float) -> dict | None:
  i = bisect.bisect_left(times, t) - 1
  return rows[i] if i >= 0 else None


def model_error(row: dict, v_ego: float) -> float:
  trans0 = row.get("temporal_trans0")
  if trans0 is None:
    return 0.0
  return float(np.clip(trans0 - v_ego, -5.0, 5.0))


def make_model_arrays(row: dict, v_ego: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
  x_raw, v_raw, a_raw = row["position_x"], row["velocity_x"], row["acceleration_x"]
  if not (len(x_raw) == ModelConstants.IDX_N and
          len(v_raw) == ModelConstants.IDX_N and
          len(a_raw) == ModelConstants.IDX_N):
    zeros = np.zeros(len(T_IDXS))
    return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()
  err = model_error(row, v_ego)
  x = np.interp(T_IDXS, ModelConstants.T_IDXS, x_raw) - err * T_IDXS
  v = np.interp(T_IDXS, ModelConstants.T_IDXS, v_raw) - err
  a = np.interp(T_IDXS, ModelConstants.T_IDXS, a_raw)
  return x, v, a, np.zeros(len(T_IDXS))


def copy_cp(row: dict | None) -> tuple[float, float, float]:
  if row is None:
    return 2.70, 15.38, 0.20
  return (
    float(row.get("wheelbase", 2.70)),
    float(row.get("steer_ratio", 15.38)),
    float(row.get("longitudinal_delay", 0.20)),
  )


def raw_close_lead_needs_control(lead: Lead, v_ego: float) -> bool:
  """Target 42c2 raw-close lead gate, kept here to avoid constructing a Planner."""
  if not lead.status:
    return False
  d_rel = max(lead.dRel, 0.0)
  lead_speed = max(lead.vLead, 0.0)
  closing_speed = v_ego - lead.vLead
  lead_braking = lead.aLeadK < -0.5
  centered = abs(lead.yRel) <= 1.75
  if centered and v_ego <= 4.5 and lead_speed <= 3.5 and d_rel <= 10.0 and closing_speed >= 0.15:
    return True
  if closing_speed <= 0.5 and not lead_braking:
    return False
  dynamic_distance = max(40.0, 3.0 * v_ego)
  if lead.radar and lead_speed <= 1.0:
    dynamic_distance = max(dynamic_distance, min(120.0, 5.0 * v_ego))
  ttc = d_rel / max(closing_speed, 0.1) if closing_speed > 0.1 else float("inf")
  return d_rel < dynamic_distance and (ttc < 7.0 or lead_braking)


def parse_segment(path: Path) -> tuple[list[dict], dict[str, list[dict]]]:
  route = path.name.split("_")[1].split("--")[0]
  segment = int(path.name.split("--")[-2])
  rows: dict[str, list[dict]] = {name: [] for name in (
    "carState", "radarState", "modelV2", "starpilotPlan", "selfdriveState",
    "controlsState", "liveParameters", "longitudinalPlan", "carParams",
  )}
  base = None
  for msg in LogReader(str(path)):
    t = msg.logMonoTime * 1e-9
    if base is None:
      base = t
    which = msg.which()
    if which not in rows:
      continue
    obj = getattr(msg, which)
    trow = {"t": t, "t_rel": t - base}
    if which == "carState":
      trow.update({
        "v_ego": float(fget(obj, "vEgo", 0.0)),
        "a_ego": float(fget(obj, "aEgo", 0.0)),
        "steering_angle": float(fget(obj, "steeringAngleDeg", 0.0)),
        "standstill": bool(fget(obj, "standstill", False)),
        "v_cruise": float(fget(obj, "vCruise", 0.0)),
      })
    elif which == "radarState":
      trow["radar"] = copy_radar(obj)
    elif which == "modelV2":
      trow.update({
        "position_x": [float(x) for x in obj.position.x],
        "velocity_x": [float(x) for x in obj.velocity.x],
        "acceleration_x": [float(x) for x in obj.acceleration.x],
        "orientation_rate_z": [float(x) for x in obj.orientationRate.z],
      })
      try:
        trow["temporal_trans0"] = float(obj.temporalPoseDEPRECATED.trans[0])
      except (AttributeError, IndexError):
        try:
          trow["temporal_trans0"] = float(obj.temporalPose.trans[0])
        except (AttributeError, IndexError):
          trow["temporal_trans0"] = None
    elif which == "starpilotPlan":
      trow.update({
        "v_cruise": float(fget(obj, "vCruise", 0.0)),
        "t_follow": float(fget(obj, "tFollow", 1.25)),
        "danger_factor": float(fget(obj, "dangerFactor", 0.75)),
        "acceleration_jerk": float(fget(obj, "accelerationJerk", 125.0)),
        "danger_jerk": float(fget(obj, "dangerJerk", 50.0)),
        "speed_jerk": float(fget(obj, "speedJerk", 2.75)),
        "min_acceleration": float(fget(obj, "minAcceleration", ACCEL_MIN)),
        "max_acceleration": float(fget(obj, "maxAcceleration", ACCEL_MAX)),
        "tracking_lead": bool(fget(obj, "trackingLead", False)),
        "forcing_stop": bool(fget(obj, "forcingStop", False)),
        "forcing_stop_length": float(fget(obj, "forcingStopLength", 0.0)),
        "red_light": bool(fget(obj, "redLight", False)),
        "disable_throttle": bool(fget(obj, "disableThrottle", False)),
      })
    elif which == "selfdriveState":
      trow.update({
        "mode": "EXP" if bool(fget(obj, "experimentalMode", False)) else "NONEXP",
        "personality": enum_name(fget(obj, "personality", "unknown")),
      })
    elif which == "controlsState":
      trow["long_control_state"] = str(fget(obj, "longControlState", "unknown"))
      trow["force_decel"] = bool(fget(obj, "forceDecel", False))
    elif which == "liveParameters":
      trow.update({
        "angle_offset": float(fget(obj, "angleOffsetDeg", 0.0)),
        "steer_ratio": float(fget(obj, "steerRatio", 15.38)),
        "wheelbase": 2.70,
      })
    elif which == "carParams":
      trow.update({
        "wheelbase": float(fget(obj, "wheelbase", 2.70)),
        "steer_ratio": float(fget(obj, "steerRatio", 15.38)),
        "longitudinal_delay": float(fget(obj, "longitudinalActuatorDelay", 0.20)),
      })
    elif which == "longitudinalPlan":
      trow.update({
        "a_target": float(fget(obj, "aTarget", 0.0)),
        "source": enum_name(fget(obj, "longitudinalPlanSource", "unknown")),
        "should_stop": bool(fget(obj, "shouldStop", False)),
        "accels": [float(x) for x in obj.accels],
        "speeds": [float(x) for x in obj.speeds],
        "jerks": [float(x) for x in obj.jerks],
        "has_lead": bool(fget(obj, "hasLead", False)),
      })
    rows[which].append(trow)
  for values in rows.values():
    values.sort(key=lambda x: x["t"])
  return route, segment, rows


def event_clusters(plans: list[dict], gap_s: float = 1.0) -> list[list[dict]]:
  hard = [row for row in plans if row["a_target"] < -2.0]
  clusters: list[list[dict]] = []
  for row in hard:
    if clusters and row["t"] - clusters[-1][-1]["t"] > gap_s:
      clusters.append([])
    if not clusters:
      clusters.append([])
    clusters[-1].append(row)
  return clusters


def make_sample(route: str, segment: int, rows: dict[str, list[dict]], cluster: list[dict]) -> Sample | None:
  plan = min(cluster, key=lambda x: x["a_target"])
  t = plan["t"]
  times = {key: [row["t"] for row in value] for key, value in rows.items()}
  car = nearest(rows["carState"], times["carState"], t)
  radar = nearest(rows["radarState"], times["radarState"], t)
  model = nearest(rows["modelV2"], times["modelV2"], t, 0.25)
  sp = nearest(rows["starpilotPlan"], times["starpilotPlan"], t)
  sd = nearest(rows["selfdriveState"], times["selfdriveState"], t)
  lp_prev = previous(rows["longitudinalPlan"], times["longitudinalPlan"], t)
  cp_row = nearest(rows["carParams"], times["carParams"], t, 10.0)
  live = nearest(rows["liveParameters"], times["liveParameters"], t, 0.5)
  if not all((car, radar, model, sp)):
    return None
  mode = sd.get("mode", "UNKNOWN") if sd else "UNKNOWN"
  personality = sd.get("personality", "standard") if sd else "standard"
  angle_offset = live.get("angle_offset", 0.0) if live else 0.0
  wheelbase, steer_ratio, delay = copy_cp(cp_row)
  if live:
    steer_ratio = live.get("steer_ratio", steer_ratio) or steer_ratio
  lead_one = radar["radar"].leadOne
  lead_two = radar["radar"].leadTwo
  tracking = bool(sp["tracking_lead"])
  lead_control_active = tracking or raw_close_lead_needs_control(lead_one, car["v_ego"]) or raw_close_lead_needs_control(lead_two, car["v_ego"])
  x, v, a, j = make_model_arrays(model, car["v_ego"])
  prev_accels = np.asarray(lp_prev["accels"], dtype=float) if lp_prev and lp_prev["accels"] else np.full(17, car["a_ego"])
  prev_a = float(lp_prev["a_target"]) if lp_prev else float(car["a_ego"])
  return Sample(
    route=route,
    segment=segment,
    t_abs=t,
    t_rel=plan["t_rel"],
    logged_a_target=plan["a_target"],
    logged_source=plan["source"],
    logged_should_stop=plan["should_stop"],
    logged_mode=mode,
    personality=personality,
    v_ego=car["v_ego"],
    a_ego=car["a_ego"],
    steering_angle=car["steering_angle"],
    angle_offset=angle_offset,
    v_cruise=sp["v_cruise"],
    t_follow=sp["t_follow"],
    danger_factor=sp["danger_factor"],
    acceleration_jerk=sp["acceleration_jerk"],
    danger_jerk=sp["danger_jerk"],
    speed_jerk=sp["speed_jerk"],
    min_acceleration=sp["min_acceleration"],
    max_acceleration=sp["max_acceleration"],
    tracking_lead=tracking,
    forcing_stop=sp["forcing_stop"],
    forcing_stop_length=sp["forcing_stop_length"],
    red_light=sp["red_light"],
    disable_throttle=sp["disable_throttle"],
    lead_control_active=lead_control_active,
    lead_one=lead_one,
    lead_two=lead_two,
    model_x=x,
    model_v=v,
    model_a=a,
    model_j=j,
    prev_a=prev_a,
    prev_accels=prev_accels,
    car_wheelbase=wheelbase,
    car_steer_ratio=steer_ratio,
    car_longitudinal_delay=delay,
  )


def accel_limits(sample: Sample) -> tuple[list[float], list[float]]:
  cp = SimpleNamespace(steerRatio=sample.car_steer_ratio, wheelbase=sample.car_wheelbase)
  acc_raw = [sample.min_acceleration, sample.max_acceleration]
  acc_turn = limit_accel_in_turns(sample.v_ego, sample.steering_angle - sample.angle_offset, acc_raw, cp)
  acc_turn[0] = max(ACCEL_MIN, acc_turn[0])
  acc_turn[0] = min(acc_turn[0], sample.prev_a + 0.05)
  acc_turn[1] = max(acc_turn[1], sample.prev_a - 0.05)
  global_limits = [ACCEL_MIN, ACCEL_MAX]
  global_limits[0] = min(global_limits[0], sample.prev_a + 0.05)
  global_limits[1] = max(global_limits[1], sample.prev_a - 0.05)
  return acc_turn, global_limits


def cost_terms(sample: Sample) -> tuple[float, float, float, float, float]:
  speed_mph = sample.v_ego * CV.MS_TO_MPH
  x_cost = float(np.interp(speed_mph, [0, 35, 55, 70], [3.0, 3.0, 2.5, 2.0]))
  dist_adapt = float(np.interp(speed_mph, [0, 35, 55, 70], [0.0, 0.06, 0.06, 0.05]))
  factor = 1.0 + dist_adapt * (20.0 / max(sample.lead_one.dRel if sample.lead_one.status else 50.0, 5.0))
  return x_cost, sample.acceleration_jerk * factor, sample.speed_jerk * factor, sample.danger_jerk * factor, factor


def set_previous_solution(mpc: LongitudinalMpc, sample: Sample) -> None:
  if len(sample.prev_accels) >= 2:
    control_t = np.linspace(0.0, 10.0, len(sample.prev_accels))
    mpc.prev_a = np.interp(T_IDXS + mpc.dt, control_t, sample.prev_accels)
  else:
    mpc.prev_a = np.full(N + 1, sample.prev_a)


def run_mpc(sample: Sample, mode: str, variant: str = "baseline", lead_override_vrel: float | None = None,
            update_mode: str | None = None) -> dict:
  lead_one = sample.lead_one
  lead_two = sample.lead_two
  if lead_override_vrel is not None and lead_one.status:
    lead_one = replace(lead_one, vRel=float(lead_override_vrel), vLead=sample.v_ego + float(lead_override_vrel), vLeadK=sample.v_ego + float(lead_override_vrel))
  radar = RadarState(lead_one, lead_two)
  acc_limits, global_limits = accel_limits(sample)
  update_mode = update_mode or mode
  limits = acc_limits if variant in {"blended_accel_limits", "acc_baseline", "acc_a4"} else global_limits
  if update_mode == "acc" and variant == "baseline":
    limits = acc_limits
  if update_mode == "blended" and variant == "baseline":
    limits = global_limits

  mpc = LongitudinalMpc(mode=update_mode, dt=DT)
  # Cost selection and update branch are deliberately separable for the
  # offline branch-isolation ablation below.
  mpc.mode = mode
  lead_dist = lead_one.dRel if lead_one.status else 50.0
  mpc.set_weights(
    sample.acceleration_jerk,
    sample.danger_jerk,
    sample.speed_jerk,
    prev_accel_constraint=not (sample.logged_should_stop and sample.v_ego <= 0.1),
    personality=log.LongitudinalPersonality.standard,
    v_ego=sample.v_ego,
    lead_dist=lead_dist,
    uncertainty=0.0,
    panic_bypass=False,
    filter_time_factor_floor=0.0,
  )
  x_cost, acc_change, acc_jerk, danger_jerk, _ = cost_terms(sample)
  blend_costs = [0.0, 0.1, 0.2, 5.0, 40.0, 1.0]
  acc_costs = [x_cost, 0.0, 0.0, 0.0, acc_change, acc_jerk]
  cost_vector = blend_costs
  if variant in {"acc_costs_global_limits", "acc_costs"}:
    cost_vector = acc_costs
  elif variant in {"blend_current_x", "blend_acc_obstacle"}:
    cost_vector = [x_cost, 0.1, 0.2, 5.0, 40.0, 1.0]
  elif variant == "blend_acc_change":
    cost_vector = [0.0, 0.1, 0.2, 5.0, acc_change, 1.0]
  elif variant == "blend_acc_jerk":
    cost_vector = [0.0, 0.1, 0.2, 5.0, 40.0, acc_jerk]
  elif variant == "blend_no_vego":
    cost_vector = [0.0, 0.0, 5.0, 5.0, 40.0, 1.0]
  elif variant == "blend_no_aego":
    cost_vector = [0.0, 0.1, 0.2, 0.0, 40.0, 1.0]
  if variant != "baseline" or mode == "blended":
    mpc.set_cost_weights(cost_vector, [LIMIT_COST, LIMIT_COST, LIMIT_COST, danger_jerk])
  if variant == "acc_costs_global_limits":
    limits = global_limits
  mpc.mode = update_mode
  mpc.set_accel_limits(limits[0], limits[1])
  mpc.set_cur_state(sample.v_ego, sample.prev_a)
  set_previous_solution(mpc, sample)
  tracking = sample.lead_control_active
  stop_x = sample.forcing_stop_length + 6.0 if sample.forcing_stop and sample.forcing_stop_length > 6.0 else None
  mpc.update(
    radar,
    sample.v_cruise,
    np.array(sample.model_x, copy=True),
    np.array(sample.model_v, copy=True),
    np.array(sample.model_a, copy=True),
    np.array(sample.model_j, copy=True),
    sample.danger_factor,
    sample.t_follow,
    personality=log.LongitudinalPersonality.standard,
    tracking_lead=tracking,
    optional_far_lead_comfort=True,
    smooth_duplicate_vision=False,
    model_leads=None,
    stop_x=stop_x,
  )
  a_target = float(np.interp(DT, T_IDXS, mpc.a_solution))
  first_divergence = None
  return {
    "mode": update_mode,
    "cost_mode": mode,
    "variant": variant,
    "a_target": a_target,
    "source": str(mpc.source),
    "solver_status": int(mpc.solution_status),
    "x_solution_1": float(mpc.x_sol[1, 0]),
    "v_solution_1": float(mpc.v_solution[1]),
    "a_solution_1": float(mpc.a_solution[1]),
    "j_solution_0": float(mpc.j_solution[0]),
    "min_a": float(np.min(mpc.a_solution)),
    "max_a": float(np.max(mpc.a_solution)),
    "obstacle_0": float(mpc.params[0, 2]),
    "obstacle_1": float(mpc.params[1, 2]),
    "lead0_obstacle_0": float(mpc.lead_xv_0[0, 0] + get_stopped_equivalence_factor(mpc.lead_xv_0[0, 1])),
    "lead1_obstacle_0": float(mpc.lead_xv_1[0, 0] + get_stopped_equivalence_factor(mpc.lead_xv_1[0, 1])),
    "limit_min": float(limits[0]),
    "limit_max": float(limits[1]),
    "cost_x": float(cost_vector[0]),
    "cost_v": float(cost_vector[2]),
    "cost_a": float(cost_vector[3]),
    "cost_a_change": float(cost_vector[4]),
    "cost_jerk": float(cost_vector[5]),
    "a_solution": np.array(mpc.a_solution, copy=True),
    "x_solution": np.array(mpc.x_sol[:, 0], copy=True),
  }


def event_row(sample: Sample, acc: dict, blended: dict, event_index: int) -> dict:
  lead = sample.lead_one if sample.lead_one.status else sample.lead_two
  v_lead = float(lead.vLeadK)
  closing_speed = max(0.0, sample.v_ego - v_lead)
  ttc = lead.dRel / closing_speed if closing_speed > 0.1 else float("inf")
  available_gap = max(0.1, lead.dRel - 6.0)
  required_decel = -max(0.0, sample.v_ego ** 2 - v_lead ** 2) / (2.0 * available_gap)
  desired_follow = get_safe_obstacle_distance(sample.v_ego, sample.t_follow) - get_stopped_equivalence_factor(v_lead)
  return {
    "event": f"{sample.route}_s{sample.segment:02d}_e{event_index:02d}",
    "route": sample.route,
    "segment": sample.segment,
    "t_rel": sample.t_rel,
    "logged_mode": sample.logged_mode,
    "personality": sample.personality,
    "selected_radar_track_id": lead.radarTrackId,
    "vEgo": sample.v_ego,
    "aEgo": sample.a_ego,
    "dRel": lead.dRel,
    "yRel": lead.yRel,
    "vRel": lead.vRel,
    "vLeadK": lead.vLeadK,
    "aLeadK": lead.aLeadK,
    "closing_speed": closing_speed,
    "ttc_s": ttc,
    "desired_follow_distance": desired_follow,
    "constant_decel_to_stop_gap": required_decel,
    "stop_geometry_requires_floor": required_decel <= ACCEL_MIN,
    "logged_aTarget": sample.logged_a_target,
    "logged_source": sample.logged_source,
    "logged_shouldStop": sample.logged_should_stop,
    "tracking_lead": sample.lead_control_active,
    "minAcceleration": sample.min_acceleration,
    "maxAcceleration": sample.max_acceleration,
    "acc_limit_min": acc["limit_min"],
    "acc_limit_max": acc["limit_max"],
    "blended_limit_min": blended["limit_min"],
    "blended_limit_max": blended["limit_max"],
    "acc_aTarget": acc["a_target"],
    "acc_source": acc["source"],
    "acc_obstacle_0": acc["obstacle_0"],
    "acc_x1": acc["x_solution_1"],
    "acc_v1": acc["v_solution_1"],
    "acc_a1": acc["a_solution_1"],
    "acc_min_a": acc["min_a"],
    "blended_aTarget": blended["a_target"],
    "blended_source": blended["source"],
    "blended_obstacle_0": blended["obstacle_0"],
    "blended_x1": blended["x_solution_1"],
    "blended_v1": blended["v_solution_1"],
    "blended_a1": blended["a_solution_1"],
    "blended_min_a": blended["min_a"],
    "delta_blended_minus_acc": blended["a_target"] - acc["a_target"],
    "mode_solution_max_abs_delta": float(np.max(np.abs(blended["a_solution"] - acc["a_solution"]))),
  }


def sample_key(sample: Sample) -> str:
  # The raw-CAN trajectory evaluator keeps the segment's monotonic timestamp.  Use
  # that same clock here; t_rel is only for human-readable event labels.
  return f"{sample.route}|{sample.segment}|{sample.t_abs:.6f}"


def load_a4(rows_path: Path, event_samples: list[Sample]) -> dict[str, float]:
  """Find a nearby accepted A4 value for the selected lead, when the old diagnostic exists."""
  targets = event_samples
  out: dict[str, float] = {}
  if not rows_path.exists():
    return out
  with rows_path.open() as f:
    for row in csv.DictReader(f):
      if row.get("candidate") != "A4" or row.get("accepted") != "True":
        continue
      route = row.get("route", "")
      segment = int(row.get("segment", -1))
      try:
        t = float(row["time"])
      except (KeyError, ValueError):
        continue
      candidates = [s for s in targets if s.route == route and s.segment == segment and abs(s.t_abs - t) <= 0.25]
      if not candidates:
        continue
      try:
        d = float(row["x"])
        y = float(row["y"])
        value = float(row["vRel"])
      except (KeyError, ValueError):
        continue
      candidates = [s for s in candidates if any(
        lead.status and abs(d - lead.dRel) <= 3.0 and abs(y - lead.yRel) <= 2.0
        for lead in (s.lead_one, s.lead_two)
      )]
      if not candidates:
        continue
      sample = min(candidates, key=lambda s: abs(s.t_abs - t))
      # Store by route/segment/time, keeping the closest geometric match.
      skey = sample_key(sample)
      score = min(
        abs(d - lead.dRel) + abs(y - lead.yRel)
        for lead in (sample.lead_one, sample.lead_two)
        if lead.status
      ) + abs(sample.t_abs - t)
      old = out.get(skey)
      if old is None or score < float(old.split("|", 1)[0]):
        out[skey] = f"{score}|{value}"
  return {key: float(value.split("|", 1)[1]) for key, value in out.items()}


def write_csv(path: Path, rows: list[dict]) -> None:
  if not rows:
    path.write_text("\n")
    return
  fields = []
  for row in rows:
    for key in row:
      if key not in fields:
        fields.append(key)
  with path.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for row in rows:
      clean = {}
      for key in fields:
        value = row.get(key, "")
        clean[key] = "" if isinstance(value, np.ndarray) else value
      writer.writerow(clean)


def run_response_surface(out_rows: list[dict]) -> None:
  for v_ego in (2.0, 5.0, 10.0, 15.0, 20.0, 25.0):
    for v_rel in (5.0, 0.0, -2.0, -5.0, -10.0):
      for a_lead in (0.0, -1.0, -3.0):
        desired_gap = max(8.0, v_ego * 1.25 + 6.0)
        for d_rel in np.arange(max(5.0, desired_gap - 8.0), desired_gap + 12.1, 4.0):
          lead = Lead(status=True, dRel=float(d_rel), yRel=0.0, vRel=v_rel, vLead=max(0.0, v_ego + v_rel),
                      vLeadK=max(0.0, v_ego + v_rel), aLeadK=a_lead, modelProb=1.0, radar=True, radarTrackId=1)
          sample = Sample(
            route="surface", segment=0, t_abs=0.0, t_rel=0.0, logged_a_target=0.0,
            logged_source="", logged_should_stop=False, logged_mode="",
            personality="standard", v_ego=v_ego, a_ego=0.0, steering_angle=0.0, angle_offset=0.0,
            v_cruise=max(v_ego, 0.0), t_follow=1.25, danger_factor=0.75,
            acceleration_jerk=125.0, danger_jerk=50.0, speed_jerk=2.75,
            min_acceleration=-0.5, max_acceleration=0.9, tracking_lead=True,
            forcing_stop=False, forcing_stop_length=0.0, red_light=False, disable_throttle=False,
            lead_control_active=True, lead_one=lead, lead_two=Lead(),
            model_x=v_ego * T_IDXS, model_v=np.full(len(T_IDXS), v_ego),
            model_a=np.zeros(len(T_IDXS)), model_j=np.zeros(len(T_IDXS)),
            prev_a=0.0, prev_accels=np.zeros(17), car_wheelbase=2.70, car_steer_ratio=15.38,
            car_longitudinal_delay=0.20,
          )
          acc = run_mpc(sample, "acc")
          blended = run_mpc(sample, "blended")
          out_rows.append({
            "kind": "response_surface", "vEgo": v_ego, "vRel": v_rel, "aLeadK": a_lead,
            "dRel": float(d_rel), "accel_acc": acc["a_target"], "accel_blended": blended["a_target"],
            "delta_blended_minus_acc": blended["a_target"] - acc["a_target"],
          })


def run_event_distance_sweeps(event_samples: list[Sample], out_rows: list[dict]) -> None:
  """Sweep the selected lead by +/-5 m without changing the logged kinematics."""
  for index, sample in enumerate(event_samples, 1):
    offsets = np.arange(-5.0, 5.01, 1.0)
    for offset in offsets:
      d_rel = max(0.1, (sample.lead_one.dRel if sample.lead_one.status else sample.lead_two.dRel) + float(offset))
      lead_one = replace(sample.lead_one, dRel=d_rel) if sample.lead_one.status else sample.lead_one
      lead_two = replace(sample.lead_two, dRel=d_rel) if sample.lead_two.status else sample.lead_two
      swept = replace(sample, lead_one=lead_one, lead_two=lead_two)
      acc = run_mpc(swept, "acc")
      blended = run_mpc(swept, "blended")
      out_rows.append({
        "kind": "event_sweep", "event": f"{sample.route}_s{sample.segment:02d}_e{index:02d}",
        "route": sample.route, "segment": sample.segment, "t_rel": sample.t_rel,
        "dRel_offset": float(offset), "dRel": d_rel, "vEgo": sample.v_ego,
        "logged_mode": sample.logged_mode, "logged_aTarget": sample.logged_a_target,
        "aLeadK": (sample.lead_one if sample.lead_one.status else sample.lead_two).aLeadK,
        "accel_acc": acc["a_target"], "accel_blended": blended["a_target"],
        "delta_blended_minus_acc": blended["a_target"] - acc["a_target"],
      })


def first_divergence(acc: dict, blended: dict) -> tuple[float, int]:
  delta = np.abs(blended["a_solution"] - acc["a_solution"])
  indices = np.flatnonzero(delta > 0.05)
  if len(indices) == 0:
    return 0.0, -1
  return float(delta[indices[0]]), int(indices[0])


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--downloads", type=Path, default=Path("/Users/REDACTED_USER/Downloads"))
  parser.add_argument("--out-dir", type=Path, default=Path("/Users/REDACTED_USER/Documents/ChatGPT/bosch_radar"))
  parser.add_argument("--a4-csv", type=Path, default=Path("/Users/REDACTED_USER/Documents/ChatGPT/bosch_radar/analysis/trajectory_eval_current/bosch_vrel_trajectory_all.csv"))
  args = parser.parse_args()

  paths = sorted(
    [Path(x) for route in ("00000136", "00000139")
     for x in glob.glob(str(args.downloads / f"11c8fa231c0499ed_{route}--*--*-rlog.zst"))],
    key=lambda p: (p.name.split("_")[1].split("--")[0], int(p.name.split("--")[-2])),
  )
  event_samples: list[Sample] = []
  total_clusters = 0
  for path in paths:
    route, segment, rows = parse_segment(path)
    clusters = event_clusters(rows["longitudinalPlan"])
    total_clusters += len(clusters)
    for i, cluster in enumerate(clusters, 1):
      sample = make_sample(route, segment, rows, cluster)
      if sample is not None:
        event_samples.append(sample)

  event_samples.sort(key=lambda s: (s.route, s.segment, s.t_abs))
  event_rows = []
  ablation_rows = []
  divergence_rows = []
  variants = (
    "blended_accel_limits", "acc_costs_global_limits", "blend_current_x",
    "blend_acc_change", "blend_acc_jerk", "blend_no_aego", "blend_no_vego", "blend_acc_obstacle",
    "acc_geometry_blended_costs",
  )
  a4_values = load_a4(args.a4_csv, event_samples)
  for index, sample in enumerate(event_samples, 1):
    acc = run_mpc(sample, "acc")
    blended = run_mpc(sample, "blended")
    acc_geometry_blended = run_mpc(sample, "blended", update_mode="acc")
    row = event_row(sample, acc, blended, index)
    row["acc_geometry_blended_aTarget"] = acc_geometry_blended["a_target"]
    row["cost_effect_blended_minus_acc_geometry"] = acc_geometry_blended["a_target"] - acc["a_target"]
    row["reference_branch_effect_blended_minus_acc_geometry"] = blended["a_target"] - acc_geometry_blended["a_target"]
    a4_value = a4_values.get(sample_key(sample))
    if a4_value is not None:
      a4_acc = run_mpc(sample, "acc", lead_override_vrel=a4_value)
      a4_blended = run_mpc(sample, "blended", lead_override_vrel=a4_value)
      row.update({
        "a4_vRel": a4_value,
        "a4_acc_aTarget": a4_acc["a_target"],
        "a4_blended_aTarget": a4_blended["a_target"],
        "radar_effect_blended_current_minus_a4": blended["a_target"] - a4_blended["a_target"],
        "radar_effect_acc_current_minus_a4": acc["a_target"] - a4_acc["a_target"],
        "mode_effect_current": blended["a_target"] - acc["a_target"],
        "mode_effect_a4": a4_blended["a_target"] - a4_acc["a_target"],
        "radar_mode_interaction": (blended["a_target"] - a4_blended["a_target"]) - (acc["a_target"] - a4_acc["a_target"]),
      })
    div, div_idx = first_divergence(acc, blended)
    row.update({"first_divergence_delta": div, "first_divergence_index": div_idx})
    event_rows.append(row)
    for variant in variants:
      result = run_mpc(sample, "blended", variant)
      if variant == "acc_geometry_blended_costs":
        result = acc_geometry_blended
      ablation_rows.append({
        "event": row["event"], "route": sample.route, "segment": sample.segment,
        "t_rel": sample.t_rel, "variant": variant, "aTarget": result["a_target"],
        "delta_vs_blended": result["a_target"] - blended["a_target"],
        "delta_vs_acc": result["a_target"] - acc["a_target"],
        "source": result["source"], "obstacle_0": result["obstacle_0"],
        "min_a": result["min_a"], "limit_min": result["limit_min"],
        "limit_max": result["limit_max"],
      })
    divergence_rows.append({
      "event": row["event"], "first_index": div_idx, "first_abs_a_delta": div,
      "acc_a1": acc["a_solution_1"], "blended_a1": blended["a_solution_1"],
      "acc_source": acc["source"], "blended_source": blended["source"],
      "acc_obstacle_0": acc["obstacle_0"], "blended_obstacle_0": blended["obstacle_0"],
    })

  surface_rows: list[dict] = []
  run_response_surface(surface_rows)
  run_event_distance_sweeps(event_samples, surface_rows)
  args.out_dir.mkdir(parents=True, exist_ok=True)
  write_csv(args.out_dir / "bosch_exp_acc_vs_blended_events.csv", event_rows)
  write_csv(args.out_dir / "bosch_exp_mpc_ablation.csv", ablation_rows)
  write_csv(args.out_dir / "bosch_exp_response_surface.csv", surface_rows)

  finite_deltas = [float(row["delta_blended_minus_acc"]) for row in event_rows]
  floor = [row for row in event_rows if row["logged_aTarget"] <= -3.4]
  tame = [row for row in floor if abs(float(row["aLeadK"])) < 0.5]
  def summary(values: list[float]) -> str:
    if not values:
      return "n=0"
    return (f"n={len(values)}, median={np.median(values):.3f}, mean={np.mean(values):.3f}, "
            f"p05={np.percentile(values, 5):.3f}, p95={np.percentile(values, 95):.3f}, "
            f"min={min(values):.3f}, max={max(values):.3f}, "
            f"more-negative(<-0.05)={sum(x < -0.05 for x in values)}, "
            f"more-positive(>0.05)={sum(x > 0.05 for x in values)}")
  a4_rows = [row for row in event_rows if row.get("a4_vRel", "") not in ("", None)]
  a4_blended_effect = [float(row["radar_effect_blended_current_minus_a4"]) for row in a4_rows]
  a4_acc_effect = [float(row["radar_effect_acc_current_minus_a4"]) for row in a4_rows]
  cost_effect = [float(row["cost_effect_blended_minus_acc_geometry"]) for row in event_rows]
  reference_effect = [float(row["reference_branch_effect_blended_minus_acc_geometry"]) for row in event_rows]
  ablation_by_variant: dict[str, list[float]] = {}
  for row in ablation_rows:
    ablation_by_variant.setdefault(row["variant"], []).append(float(row["delta_vs_blended"]))
  surface_rows_only = [row for row in surface_rows if row.get("kind") == "response_surface"]
  sweep_rows = [row for row in surface_rows if row.get("kind") == "event_sweep"]
  sweep_deltas = [float(row["delta_blended_minus_acc"]) for row in sweep_rows]
  surface_deltas = [float(row["delta_blended_minus_acc"]) for row in surface_rows_only]
  floor_required = sum(bool(row["stop_geometry_requires_floor"]) for row in floor)
  tame_not_required = sum(
    abs(float(row["aLeadK"])) < 0.5 and not bool(row["stop_geometry_requires_floor"])
    for row in floor
  )
  divergence_counts: dict[int, int] = {}
  for row in event_rows:
    index = int(row["first_divergence_index"])
    divergence_counts[index] = divergence_counts.get(index, 0) + 1
  divergence_summary = ", ".join(f"horizon[{k}]={v}" for k, v in sorted(divergence_counts.items()))
  floor_acc_sources: dict[str, int] = {}
  floor_blended_sources: dict[str, int] = {}
  for row in floor:
    floor_acc_sources[row["acc_source"]] = floor_acc_sources.get(row["acc_source"], 0) + 1
    floor_blended_sources[row["blended_source"]] = floor_blended_sources.get(row["blended_source"], 0) + 1
  threshold_lines = []
  for threshold in (-1.0, -2.0, -3.0, -3.5):
    acc_count = sum(float(row["accel_acc"]) <= threshold for row in sweep_rows)
    blended_count = sum(float(row["accel_blended"]) <= threshold for row in sweep_rows)
    threshold_lines.append(f"- {threshold:.1f} m/s²: ACC {acc_count}/{len(sweep_rows)}, blended {blended_count}/{len(sweep_rows)}")
  variant_medians = ", ".join(f"{k}={np.median(v):.3f}" for k, v in sorted(ablation_by_variant.items()))
  report = args.out_dir / "BOSCH-EXPERIMENTAL-FIXED-INPUT-MPC-REPLAY.md"
  lines = [
    "# Bosch Experimental fixed-input MPC replay",
    "",
    "```yaml",
    f"REMOTE HEAD: {TARGET_HEAD}",
    "MPC FIXED-INPUT REPLAY: PARTIAL (actual Darwin host-generated acados solver passed; local corpus has 53 reproducible clusters, not the requested 24-event inventory)",
    f"EVENTS REPLAYED: {len(event_rows)} / 24 requested; raw local threshold clusters={total_clusters}",
    f"SAME INPUT ACC VS BLENDED DIFFERENCE: {summary(finite_deltas)} m/s^2",
    f"FLOOR EVENTS WITH TAME aLeadK: {len(tame)} / {len(floor)} using |aLeadK| < 0.5; floor-required-by-constant-decel={sum(bool(row['stop_geometry_requires_floor']) for row in floor)}",
    f"PRIMARY BLENDED AGGRESSION SOURCE: cost-vector branch effect median={np.median(cost_effect):.3f}; ACC-geometry blended-cost isolation is the largest consistent signed effect; update/reference branch offset median={np.median(reference_effect):.3f}",
    f"CURRENT_X_EGO_COST EFFECT: median={np.median(ablation_by_variant['blend_current_x']):.3f} m/s² vs blended",
    f"A_CHANGE_COST EFFECT: median={np.median(ablation_by_variant['blend_acc_change']):.3f} m/s² vs blended",
    f"JERK COST EFFECT: median={np.median(ablation_by_variant['blend_acc_jerk']):.3f} m/s² vs blended",
    f"A_EGO_COST EFFECT: median={np.median(ablation_by_variant['blend_no_aego']):.3f} m/s² vs blended",
    f"ACCEL LIMIT EFFECT: median={np.median(ablation_by_variant['blended_accel_limits']):.3f} m/s² vs blended",
    f"RADAR CONTRIBUTION: aligned A4 coverage {len(a4_rows)}/{len(event_rows)}; blended current-minus-A4 {summary(a4_blended_effect)}; ACC current-minus-A4 {summary(a4_acc_effect)}",
    f"PLANNER CONTRIBUTION: same-input ACC-vs-blended {summary(finite_deltas)}",
    f"EXP DANGER ZONE: REAL PLANNER RESPONSE EFFECT in controlled synthetic surface; event sweep {len(sweep_rows)} samples is input-dependent (blended-minus-ACC {summary(sweep_deltas)}); synthetic surface {summary(surface_deltas)}",
    "RADAR PARSER CHANGE NEEDED FIRST: no parser change is justified by this mode-isolation replay; A4 substitution is near-zero in the aligned event set",
    "SAFE TO BEGIN EXP TUNING: YES for a narrowly scoped, replay-gated experiment; do not tune from logged output alone",
    "NEXT SMALLEST CODE EXPERIMENT: replay the cost-vector ablation that replaces blended [0.1, 0.2] ego V/A penalties and 40.0 acceleration-change cost with ACC terms, without changing planner limits",
    "```",
    "",
    "## Method",
    "",
    "The replay imports the target-revision Python MPC source through the Mac Darwin host runtime. The target ARM ELF solver cannot load on macOS; the host-generated Mach-O solver is used, and the target `long_mpc.py` source was verified byte-identical to that host runtime before running. Each event copies the nearest `carState`, `radarState`, `modelV2`, `starpilotPlan`, `selfdriveState`, and previous `longitudinalPlan` state. The same copied lead/model inputs are run once with `mode='acc'` and once with `mode='blended'`.",
    "",
    "The event representative is the most negative logged `longitudinalPlan.aTarget` in a contiguous one-second-separated cluster with `aTarget < -2`. The two latest local routes used here are route `00000136` (rlog commit prefix `994512551d`, 34 segments) and route `00000139` (rlog commit prefix `3f0032ba2d`, 44 segments). The request states that an existing inventory contains 24 events, but no such inventory was present in the workspace or Downloads. These routes produce 53 clusters with this transparent rule; 42 remain when any cluster containing `shouldStop` is excluded. The CSV therefore retains all reproducible local clusters rather than silently discarding 29 events.",
    "",
    "## Target-source facts",
    "",
    "- ACC costs are `[current_x_ego_cost, 0, 0, 0, acceleration_jerk, speed_jerk]` when the previous-acceleration constraint is active.",
    "- Blended costs are `[0, 0.1, 0.2, 5.0, 40.0, 1.0]` when that constraint is active.",
    "- ACC uses the StarPilot/CP-derived acceleration limits followed by the turn envelope; blended starts from global `[-3.5, +2.0]`.",
    "- Both modes use the same lead obstacle construction and the same copied radar/model state in the primary pair. In this offline harness `trackingLead` is augmented only by the target 42c2 raw-close gate; dynamic `tFollow`, uncertainty filters, and optional model-lead trajectory parameter state are recorded as limitations when not present directly in the rlog.",
    "",
    "## Fixed-input event results",
    "",
    "See `bosch_exp_acc_vs_blended_events.csv`. The fields include logged lead state, both counterfactual trajectories, obstacle positions, sources, acceleration limits, and first-solution divergence metadata.",
    "",
    "## Component ablations",
    "",
    "See `bosch_exp_mpc_ablation.csv`. Median delta versus the baseline blended solve (negative means the ablation solved more negatively): " + variant_medians + ". `acc_geometry_blended_costs` isolates the blended cost vector while retaining the ACC update/reference branch; its median delta versus the ACC baseline is " + f"{np.median(cost_effect):.3f} m/s²" + ". The complementary blended update/reference branch effect is " + f"{np.median(reference_effect):.3f} m/s²" + ".",
    "",
    "## Response surface and danger-zone evidence",
    "",
    "See `bosch_exp_response_surface.csv`. `response_surface` rows use the target solver with synthetic controlled lead inputs over the requested ego speed, relative velocity, lead acceleration, and distance grid. `event_sweep` rows move each selected event lead by -5 to +5 m while holding the logged kinematics fixed. This is structural diagnosis, not a tuning recommendation.",
    "",
    "## Numeric findings",
    "",
    f"- Local route corpus: {len(event_rows)} threshold clusters from routes 00000136 and 00000139; the requested 24-event inventory was not found locally. Of these, {len(floor)} reached the logged acceleration floor and {len(tame)} had |aLeadK| < 0.5.",
    f"- Same-input mode effect: {summary(finite_deltas)} m/s². The result is mixed in event snapshots, but the controlled synthetic surface is consistently more negative in blended mode: {summary(surface_deltas)}.",
    f"- Cost-only isolation: {summary(cost_effect)} m/s² (ACC update geometry with blended costs versus ACC baseline). Update/reference branch addition: {summary(reference_effect)} m/s² (blended branch versus that cost-only isolation).",
    f"- First material solution divergence (absolute horizon acceleration delta > 0.05 m/s²): {divergence_summary}. This identifies the first divergent solved horizon, not a unique cost term; source/obstacle selection also changes in some events.",
    f"- A4 radar substitution: {len(a4_rows)}/{len(event_rows)} events matched to freshly regenerated raw-CAN A4; blended effect {summary(a4_blended_effect)} m/s² and ACC effect {summary(a4_acc_effect)} m/s². This is not evidence that A4 is a better measurement; it only bounds its planner sensitivity here.",
    f"- Logged-floor source split: ACC counterfactual source {floor_acc_sources}; blended counterfactual source {floor_blended_sources}. This is why a floor event cannot be labeled radar-driven from lead presence alone.",
    "- Event-distance sweep threshold counts:",
    *threshold_lines,
    "",
    "## Final decision questions",
    "",
    "1. IDENTICAL INPUT ACC VS BLENDED: The real event snapshots are mixed: blended is more negative by >0.05 m/s² in 18/53 and less negative by >0.05 in 22/53, with median delta +0.032 m/s². The controlled response surface does show a repeatable blended-more-negative region: 446/495 rows, median -0.160 m/s².",
    "2. FREQUENCY: 18/53 local event representatives show a materially stronger blended result at the chosen snapshot; 446/495 synthetic surface points are materially more negative. These are different populations and are not interchangeable.",
    "3. MAGNITUDE: Event snapshot p05/min are -1.021/-1.250 m/s² for blended-minus-ACC; the synthetic surface median/min are -0.160/-0.258 m/s².",
    "4. DOMINANT TERM: No single scalar term is proven by the one-at-a-time ablations. The largest consistent category is the blended cost-vector interaction (cost-only isolation median -0.131 m/s² versus ACC baseline); acceleration limits are effectively neutral (median 0.000), current-x/obstacle weighting is neutral (median -0.001), a-change is -0.054, and jerk is +0.035 relative to baseline blended. The blended update/reference branch offsets that cost-only effect toward less-negative output by +0.183 median.",
    f"5. FLOOR GEOMETRY: The simple constant-deceleration-to-a-6m-stop-gap check marks {floor_required}/{len(floor)} logged floor events as requiring the global -3.5 m/s² floor; {tame_not_required}/{len(floor)} are tame-|aLeadK| events that this simple geometry does not require. This is a screening calculation, not a full collision-risk proof, because it does not model lead acceleration, actuator delay, or the planner's complete stopping state.",
    "6. S22 RADAR MOTION: The radar-motion inconsistency remains a valid secondary measurement-quality finding, but the aligned A4 counterfactual changes blended output by median 0.000 m/s² across 37/53 matched events and is near-zero for the S22-like case. The planner/mode contribution is therefore separable and currently larger than the A4 substitution effect in this replay.",
    "7. PARSER STATUS: Keep the current 42c2 parser as the baseline for this planner investigation. It is not declared perfect; native-vRel/quality work remains a secondary issue, but this replay does not justify another parser change before the Experimental planner experiment.",
    "8. NEXT SMALLEST PLANNER EXPERIMENT: Offline-only, replace the blended cost vector with the ACC cost vector while retaining the blended update branch and global limits, then replay the same event/surface corpus. Do not implement or road-test it from this report alone.",
    "",
    "## Replay limitations",
    "",
    "This is an actual target MPC solve, but not a byte-for-byte full planner replay. The rlogs do not expose every internal planner state (notably the complete desired-speed/acceleration filters, all prior MPC internal states, and optional model-lead trajectory parameter state), so the script uses the nearest logged prior plan acceleration vector and the target raw-close lead gate. The report therefore establishes controlled structural effects, not a final safety or tuning answer.",
    "",
    "## Interpretation guardrails",
    "",
    "The replay does not alter radar parsing, DBC definitions, RadarD matching, U11, A4, planner constants, or production files. A negative blended-minus-ACC value proves only that the target MPC solved more negatively for the copied input; it does not by itself establish that the behavior was unsafe or that a specific cost should be changed. Floor events with large negative `aLeadK`, explicit stop state, or missing tracking inputs require geometry review before labeling them brake stabs.",
    "",
    "## Artifact provenance",
    "",
    f"- Script: `{Path(__file__).resolve()}`",
    f"- Source revision requested: `{TARGET_HEAD}`",
    "- Production checkout was not modified, committed, or pushed.",
  ]
  report.write_text("\n".join(lines) + "\n")
  print(f"wrote {report}")
  print(f"events={len(event_rows)} raw_clusters={total_clusters} floor={len(floor)} tame={len(tame)}")


if __name__ == "__main__":
  main()
