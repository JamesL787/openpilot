#!/usr/bin/env python3
"""Closed-loop radar replay into the alpha-long planner, with the off-axis bearing threshold as the variable.

What "closed loop" means here (STATUS 36's sense, not a vehicle simulation)
--------------------------------------------------------------------------
The radar chain is re-run from the route's CAN, with the code in this tree:

    logged CAN -> Bosch-A RadarInterface (current parser) -> RadarD (current radard) -> radarState

The replayed radarState feeds several `LongitudinalPlanner` instances cycle for cycle, one per
`OFF_AXIS_LEAD_MIN_BEARING` value. There is also a `nobound` planner and a `logged` planner that reads the
on-device radarState at the shipped threshold, which is `alpha_open_loop_replay.py`'s view of the same route.
radard is shared by every variant, because the off-axis bound acts at planner input only. radarState and
radard do not depend on the threshold (D-041/D-042).

What stays open
---------------
Ego motion is the logged motion: stock ACC on a stock-ACC route, live alpha on an alpha route. A variant that
brakes differently does not change the gap it later sees. The tool compares the planner's command, not
delivered braking.

Validity check
--------------
Validity is printed first, for cycles where the log and the replay both have a leadOne. It covers agreement
on `radar`, `|dRel| < 1 m` and the same track id. When the logged build's parser differed from this tree, a
lower agreement is expected. Quote it next to any result.

Which episodes count as genuine brakes
--------------------------------------
The label has to be independent of the planners under test. On an alpha-long route the logged command is
alpha's own output (STATUS 104: 23e 4:54.6 was labelled genuine only because the pre-74e build braked on a
curve artifact), so the reference there is the vision lead alone. An episode is genuine when, on at least
VISION_REF_MIN_FRAMES frames with leadsV3[0].prob >= VISION_REF_MIN_PROB, either vision a <= VISION_REF_MAX_A
or the vision-kinematic required decel reaches VISION_REF_MIN_REQ:

    req = max(0, -a_vis) + max(0, v_ego - v_vis)^2 / (2 * max(x_vis - VISION_REF_STANDOFF, 0.5))

On a stock-ACC route the stock command below STOCK_REF_CMD also counts, since stock ACC is independent of
alpha. A driver brake press is reported but not used: it can be an override of a false brake.

The toggles are the shipped defaults. The Bosch-A rail interval (D-063), coast range bound and D-053 range assist
are built in since f9802ed9 and run as on the car.

Route data is never committed (AGENTS.md section 7).

Usage
-----
    python tools/longitudinal/alpha_closed_loop_replay.py ROUTE_DIR [--bearings 0.10,0.075] [--threshold -1.5] [--json OUT]
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("DEBUG", "0")

from openpilot.selfdrive.controls import radard as RDM
from openpilot.selfdrive.controls.lib import longitudinal_planner as LP
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib import long_mpc as LM
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.tools.lib.logreader import LogReader
from openpilot.tools.longitudinal.alpha_open_loop_replay import (
  ACC_CONTROL_ADDR, CROSS_LEVELS, EPISODE_MERGE_GAP_S, MOVING_MIN_V, _ControlsStateView, _ReplaySM,
  alpha_car_params, default_toggles, fmt_t, fnum, parse_toggles, segment_files,
)
from opendbc.can.parser import CANParser
from opendbc.car.can_definitions import CanData
from opendbc.car.honda import radar_interface as HRI

PLANNER_SERVICES = ("carState", "starpilotPlan", "selfdriveState", "carControl", "liveParameters",
                    "starpilotCarState", "controlsState")
RADARD_SERVICES = ("carState", "starpilotPlan")
BOSCH_A_IDS = frozenset(HRI.BOSCH_A_ALL_IDS)
# A variant "changes" an episode when its minimum moves by more than this, or its -1.5 crossing moves by more
# than CHANGE_DT. Smaller moves are planner-state noise after a divergence.
CHANGE_DA = 0.3
CHANGE_DT = 0.2
# Genuine-brake reference (see the module docstring). Independent of radar and of every planner under test.
VISION_REF_MIN_PROB = 0.5
VISION_REF_MAX_A = -1.0
VISION_REF_MIN_REQ = 2.0
VISION_REF_STANDOFF = 4.0
VISION_REF_MIN_FRAMES = 3
STOCK_REF_CMD = -2.0
# Baseline first: the pre-STATUS-104 threshold, then the shipped one.
DEFAULT_BEARINGS = "0.1,0.075"

# Candidate follow-ups to the bearing bound (STATUS 106/107), replay-only, behind --fixes. Both keep the shipped
# rule and add one more way to reach the same bound (aLeadK >= -max(1.5, vision brake)); nothing is shipped.
#   hold:   the bearing test also passes for FIX_HOLD_S after the same radar track last sat at or above the
#           shipped threshold. 267 15:13.3: the lead swung to the centre on a curve exit, bearing fell 0.084 ->
#           0.070 while aLeadK was still -9.
#   visdis: the bearing test also passes when a confident vision lead is the same object (x within
#           max(FIX_VIS_X_ABS, FIX_VIS_X_REL * dRel)) and its speed disagrees with the radar vLead by >= FIX_VIS_DV.
FIX_HOLD_S = 1.0
FIX_VIS_MIN_PROB = 0.9
FIX_VIS_X_ABS = 5.0
FIX_VIS_X_REL = 0.15
FIX_VIS_DV = 5.0
FIX_VARIANTS = ("hold", "visdis")
# --human-ab: HumanFollowing/HumanAcceleration both off, FrogPilot's HumanFollowing path
# (FrogPilot-Testing 728f65472 long_mpc.py process_lead), and that path with StarPilot's former
# 3 s closing-TTC fallback kept ('frog_guard', STATUS 63). Trips of the fallback are counted per frame.
HUMAN_VARIANTS = ("human_off", "frog", "frog_guard")
# STATUS 119 late-start fixes (shipped on): 'late_off' = both off (the pre-119 planner),
# 'late_A' = only the comfort-floor pass, 'late_B' = only the merge-floor release.
LATE_VARIANTS = {"late_off": (False, None), "late_A": (True, None), "late_B": (False, -1.5)}
LATE_DEFAULTS = (LP.MPC_LEAD_BRAKE_PASSES_COMFORT_FLOOR, LP.LC_MERGE_RELEASE_MPC_DEMAND)
# --hf-gate: FrogPilot e7debabe5 (2026-09-20) gates the HumanFollowing model path on the radar lead's own
# modelProb as well as the model lead's prob, so a lead the model never matched (low-speed override,
# modelProb 0) keeps its aLeadK extrapolation. 'hf_gate' = the shipped builder plus that gate.
HF_GATE_VARIANT = "hf_gate"
# --brake-ab (28f 11:33 / 14:19 firm brakes): 'cap_off' = the built-in far-lead coast cap disabled;
# 'alead_floor' = every radar lead's aLeadK floored at -ALEAD_FLOOR at planner input (diagnostic only,
# not a proposal: it would also blunt a real hard stop ahead). The vision-corroborated bound for every
# lead is the existing bearing variant b0. 'cap_radar' = the cap as it was through a8441f64, reading aLeadK
# only; the shipped cap also stands down while vision sees its lead braking (far_lead_vision_braking).
BRAKE_VARIANTS = ("cap_off", "cap_radar", "alead_floor")
ALEAD_FLOOR = 2.0
GUARD_TTC = 3.0
GUARD_MIN_CLOSING = 0.75


# --blot-ab: 'noblot' = the same planner with the BLoTv3 supervisor off (it is on in the car, BlotV3=1).
# Each frame also records what the supervisor did in the first variant (jerk scale, t_follow, triggers).
BLOT_OFF_VARIANT = "noblot"

# --sim-window T0,T1 (route seconds): inside the window every replayed variant drives its own simulated car
# instead of the logged one, so a variant that brakes earlier also arrives slower. The lead stays as logged in
# the world: its dRel is shifted by how far the simulated car is behind the logged car, its vRel re-based on
# the simulated speed, and the camera lead's x shifted the same way. The car's acceleration follows the
# planner's output through SIM_DELAY and a first-order SIM_TAU lag (fit on 28f 11:20-11:45: accel command ->
# aEgo, rmse 0.22 m/s^2), plus the logged residual (aEgo minus the same model driven by the logged command),
# so grade and drag carry over and a variant commanding exactly what the car did reproduces the log.
# Not modelled: the driver, starpilotPlan (tFollow, vCruise stay as logged), and the rest of modelV2.
SIM_DELAY = 0.1
SIM_TAU = 0.3


class _Over:
  """Read-through proxy that overrides a few attributes of a capnp reader."""
  def __init__(self, base, **over):
    self._base = base
    self._over = over

  def __getattr__(self, k):
    over = self.__dict__["_over"]
    return over[k] if k in over else getattr(self.__dict__["_base"], k)


class _FirstOrderDelay:
  def __init__(self, a0: float):
    self.a = a0
    self.buf: list = []

  def step(self, u: float, dt: float) -> float:
    self.buf.append(u)
    ud = self.buf.pop(0) if len(self.buf) > round(SIM_DELAY / 0.05) else self.buf[0]
    self.a += (ud - self.a) * min(dt / SIM_TAU, 1.0)
    return self.a


class SimCar:
  """One variant's simulated ego inside --sim-window (see SIM_DELAY)."""
  def __init__(self, v: float, a: float):
    self.v = v
    self.a = a
    self.gap_shift = 0.0
    self.model = _FirstOrderDelay(a)
    self.u = a

  def step(self, dt: float, residual: float, v_log: float):
    self.a = self.model.step(self.u, dt) + residual
    v_new = max(self.v + self.a * dt, 0.0)
    self.gap_shift += (v_log - (self.v + v_new) / 2.0) * dt
    self.v = v_new

  def views(self, cs, rs, model):
    shift, v = self.gap_shift, self.v

    def lead(ld):
      if not ld.status:
        return ld
      return _Over(ld, dRel=float(ld.dRel) + shift, vRel=float(ld.vLead) - v)

    cs_v = _Over(cs, vEgo=v, vEgoCluster=v, aEgo=self.a, standstill=v < 0.05)
    rs_v = _Over(rs, leadOne=lead(rs.leadOne), leadTwo=lead(rs.leadTwo))
    leads = [_Over(ld, x=[float(x) + shift for x in ld.x]) for ld in model.leadsV3]
    return cs_v, rs_v, _Over(model, leadsV3=leads)


def frogpilot_model_lead_trajectory(lead_detection_probability, guard=False, trips=None):
  """FrogPilot's HumanFollowing lead path: radar anchor + model deltas; `guard` adds the 3 s TTC fallback."""
  def build(model_lead, radar_lead, v_ego, *_):
    if model_lead is None or radar_lead is None or not bool(getattr(radar_lead, "status", False)):
      return None
    if not float(model_lead.prob) > lead_detection_probability:
      return None
    if guard:
      closing = max(0.0, float(v_ego) - float(radar_lead.vLead))
      if closing > GUARD_MIN_CLOSING and float(radar_lead.dRel) / closing < GUARD_TTC:
        if trips is not None:
          trips.append(1)
        return None
    model_x = np.asarray(model_lead.x, dtype=np.float64)
    model_v = np.asarray(model_lead.v, dtype=np.float64)
    x_lead_traj = float(radar_lead.dRel) + (model_x - model_x[0])
    v_lead_traj = float(radar_lead.vLead) + (model_v - model_v[0])
    v_ego = float(v_ego)
    v_lead_0 = v_lead_traj[0]
    min_x_lead = 0.5 * (v_ego + v_lead_0) * (v_ego - v_lead_0) / (-LM.ACCEL_MIN * 2)
    x_lead_traj[0] = max(x_lead_traj[0], min_x_lead)
    v_lead_traj = np.clip(v_lead_traj, 0.0, 1e8)
    x_lead_mpc = np.maximum.accumulate(np.interp(LM.T_IDXS, LM.LEAD_T_IDXS_MODEL, x_lead_traj))
    v_lead_mpc = np.interp(LM.T_IDXS, LM.LEAD_T_IDXS_MODEL, v_lead_traj)
    x_lead_max = x_lead_mpc[0] + np.cumsum(LM.T_DIFFS[1:] * (v_lead_mpc[:-1] + v_lead_mpc[1:]) / 2)
    x_lead_mpc[1:] = np.minimum(x_lead_mpc[1:], x_lead_max)
    return np.column_stack((x_lead_mpc, v_lead_mpc))
  return build


class FixBound:
  """Per-planner replacement for LP.off_axis_lead_a_lead: the shipped rule, with an extra way past the bearing test."""
  def __init__(self, kind: str):
    self.kind = kind
    self.last_off_axis: dict[int, float] = {}
    self.t = 0.0
    self.v_ego = 0.0
    self.fired = False

  def observe(self, radar_state, t: float, v_ego: float) -> None:
    self.t, self.v_ego, self.fired = t, v_ego, False
    for lead in (radar_state.leadOne, radar_state.leadTwo):
      if lead.status and lead.radar and float(lead.dRel) > 1.0 and \
         abs(float(lead.yRel)) / float(lead.dRel) >= LP.OFF_AXIS_LEAD_MIN_BEARING:
        self.last_off_axis[int(lead.radarTrackId)] = t

  def _extra(self, lead, model_msg) -> bool:
    if self.kind == "hold":
      last = self.last_off_axis.get(int(lead.radarTrackId))
      return last is not None and self.t - last <= FIX_HOLD_S
    leads = getattr(model_msg, "leadsV3", None) if model_msg is not None else None
    if leads is None or not len(leads) or float(leads[0].prob) < FIX_VIS_MIN_PROB or not len(leads[0].x) or not len(leads[0].v):
      return False
    d = float(lead.dRel)
    if abs(float(leads[0].x[0]) - d) > max(FIX_VIS_X_ABS, FIX_VIS_X_REL * d):
      return False
    return abs((self.v_ego + float(lead.vRel)) - float(leads[0].v[0])) >= FIX_VIS_DV

  def __call__(self, lead, model_msg, held=False):
    if lead is None or not bool(getattr(lead, "status", False)) or not bool(getattr(lead, "radar", False)):
      return None
    d_rel = float(lead.dRel)
    a_lead = float(lead.aLeadK)
    if d_rel <= 1.0 or a_lead >= -LP.OFF_AXIS_LEAD_MAX_BRAKE:
      return None
    if abs(float(lead.yRel)) / d_rel < LP.OFF_AXIS_LEAD_MIN_BEARING and not held and not self._extra(lead, model_msg):
      return None
    vision_brake = 0.0
    leads = getattr(model_msg, "leadsV3", None) if model_msg is not None else None
    if leads is not None and len(leads) and float(leads[0].prob) >= LP.OFF_AXIS_LEAD_VISION_MIN_PROB and len(leads[0].a):
      vision_brake = max(0.0, -float(leads[0].a[0]))
    bounded = max(a_lead, -max(LP.OFF_AXIS_LEAD_MAX_BRAKE, vision_brake))
    if bounded > a_lead:
      self.fired = True
      return bounded
    return None


class _RadardSM:
  """The SubMaster surface RadarD.update() reads: [], seen, logMonoTime, recv_frame, all_checks()."""
  def __init__(self):
    self.msgs: dict = {}
    self.valid: dict = {}
    self.seen = {"modelV2": False}
    self.logMonoTime = {"modelV2": 0, "carState": 0, "liveTracks": 0, "starpilotPlan": 0}
    self.recv_frame = {"carState": 0, "liveTracks": 0}

  def __getitem__(self, k):
    return self.msgs[k]

  def all_checks(self, service_list=None):
    return all(self.valid.get(s, True) for s in (service_list or self.valid.keys()))


def build_radar_interface(fingerprint: str):
  from opendbc.car.honda.interface import CarInterface
  from opendbc.car.honda.values import CAR, HONDA_BOSCH_A
  car = getattr(CAR, fingerprint)
  if car not in HONDA_BOSCH_A:
    raise SystemExit(f"{fingerprint} is not a Bosch-A Honda; the closed-loop replay needs the Bosch-A parser")
  cp = CarInterface.get_non_essential_params(car)
  cp.radarUnavailable = False  # BoschARadar on, as on the drives; not read from this host's Params
  ri = CarInterface.RadarInterface(cp)
  if not ri.bosch_a_radar:
    raise SystemExit("RadarInterface did not select the Bosch-A parser")
  ri.rail_interval = HRI.BOSCH_A_RAIL_INTERVAL  # built in since f9802ed9 (was BoschARailInterval)
  ri.coast_range_bound = HRI.BOSCH_A_COAST_RANGE_BOUND  # built in since f9802ed9 (was RangeDerivedVrel)
  return ri, cp


def lead_view(lead, model, bearings) -> dict:
  if not lead.status:
    return {"status": False}
  d, y = float(lead.dRel), float(lead.yRel)
  vis_a = vis_p = float("nan")
  if len(model.leadsV3) > 0:
    vis_p = float(model.leadsV3[0].prob)
    if len(model.leadsV3[0].a) > 0:
      vis_a = float(model.leadsV3[0].a[0])
  out = {"status": True, "radar": bool(lead.radar), "d": d, "y": y, "vRel": float(lead.vRel), "aLeadK": float(lead.aLeadK),
         "bearing": abs(y) / max(d, 1.0), "track": int(lead.radarTrackId), "visA": vis_a, "visP": vis_p}
  saved = LP.OFF_AXIS_LEAD_MIN_BEARING
  try:
    for b in bearings:
      LP.OFF_AXIS_LEAD_MIN_BEARING = b
      out[f"bound@{b:g}"] = LP.off_axis_lead_a_lead(lead, model) is not None
  finally:
    LP.OFF_AXIS_LEAD_MIN_BEARING = saved
  return out


def vision_view(model, v_ego: float) -> dict | None:
  """leadsV3[0] now, with the kinematic decel it demands; None when the model has no lead output."""
  if len(model.leadsV3) == 0:
    return None
  ld = model.leadsV3[0]
  if len(ld.x) == 0 or len(ld.v) == 0 or len(ld.a) == 0:
    return None
  x, v, a = float(ld.x[0]), float(ld.v[0]), float(ld.a[0])
  closing = max(0.0, v_ego - v)
  req = max(0.0, -a) + closing * closing / (2.0 * max(x - VISION_REF_STANDOFF, 0.5))
  return {"p": float(ld.prob), "x": x, "v": v, "a": a, "req": req}


def hf_gated_model_lead_trajectory(builder, lead_detection_probability, fired):
  """The shipped HumanFollowing builder, refused when the radar lead is not vision-matched (FrogPilot e7debabe5)."""
  def build(model_lead, radar_lead, v_ego, *args, **kwargs):
    xv = builder(model_lead, radar_lead, v_ego, *args, **kwargs)
    if xv is not None and not float(getattr(radar_lead, "modelProb", 0.0)) > lead_detection_probability:
      fired.append(True)
      return None
    return xv
  return build


def floored_a_lead(bound):
  """The shipped off-axis bound, then aLeadK floored at -ALEAD_FLOOR for any radar lead (--brake-ab)."""
  def a_lead(lead, model_msg, held=False):
    shipped = bound(lead, model_msg, held)
    if lead is None or not bool(getattr(lead, "status", False)) or not bool(getattr(lead, "radar", False)):
      return shipped
    raw = float(lead.aLeadK)
    floored = max(raw if shipped is None else shipped, -ALEAD_FLOOR)
    return floored if floored > raw else shipped
  return a_lead


def replay(route_dir: Path, bearings: list[float], fixes: bool = False, coast_bound: bool = False,
           human_ab: bool = False, vision_only: bool = False, late_ab: bool = False, hf_gate: bool = False,
           brake_ab: bool = False, blot_ab: bool = False, sim_window: tuple | None = None):
  files = segment_files(route_dir)
  if not files:
    raise SystemExit(f"no rlog segments under {route_dir}")

  variants = ([f"b{b:g}" for b in bearings] + (list(FIX_VARIANTS) if fixes else []) +
              (list(HUMAN_VARIANTS) if human_ab else []) + (list(LATE_VARIANTS) if late_ab else []) +
              ([HF_GATE_VARIANT] if hf_gate else []) + (list(BRAKE_VARIANTS) if brake_ab else []) +
              ([BLOT_OFF_VARIANT] if blot_ab else []) +
              ["nobound", "logged"])
  original_builder = LM.build_model_lead_trajectory
  fix_bounds = {k: FixBound(k) for k in FIX_VARIANTS} if fixes else {}
  original_bound = LP.off_axis_lead_a_lead
  cap_default = LP.FAR_LEAD_COAST_MAX_DECEL
  original_vision_braking = LP.far_lead_vision_braking
  state: dict = {}
  valid: dict = {}
  toggles = default_toggles()
  planners: dict = {}
  ri = rd = None
  rsm = _RadardSM()
  rr_latest = None
  can_parser = None
  accel_cmd = float("nan")
  t0 = None
  meta: dict = {"route_dir": str(route_dir), "segments": [int(p.parent.name) for p in files], "bearings": bearings,
                "human_ab": human_ab, "vision_only": vision_only,
                "shipped_bearing": LP.OFF_AXIS_LEAD_MIN_BEARING}
  agree = {"both": 0, "radar": 0, "d1m": 0, "track": 0, "status_eq": 0, "ticks": 0}
  frames: list[dict] = []
  sims: dict = {}
  sim_resid_model = None
  t_prev = None
  meta["sim_window"] = sim_window

  for path in files:
    for msg in LogReader(str(path), sort_by_time=True):
      which = msg.which()
      if t0 is None and which == "initData":
        t0 = msg.logMonoTime
      if t0 is None:
        continue
      if which == "initData" and "blotv3" not in meta:
        params = {e.key: bytes(e.value) for e in msg.initData.params.entries}
        meta["blotv3"] = params.get("BlotV3", b"0") in (b"1", b"True", b"true")
        meta["git_commit"] = msg.initData.gitCommit[:9]
        continue
      if which == "carParams" and not planners:
        cp = msg.carParams
        meta["fingerprint"] = str(cp.carFingerprint)
        meta["logged_op_long"] = bool(cp.openpilotLongitudinalControl)
        acp = alpha_car_params(cp)
        blot = bool(meta.get("blotv3", False))
        for v in variants:
          p = LP.LongitudinalPlanner(acp)
          p._blotv3_active = (lambda b=blot and v != BLOT_OFF_VARIANT: b)
          if v == "nobound":
            p.bound_off_axis_radar_leads = False
          planners[v] = p
        meta["bound_active"] = bool(planners[variants[0]].bound_off_axis_radar_leads)
        ri, ocp = build_radar_interface(str(cp.carFingerprint))
        ri.coast_range_bound = coast_bound or HRI.BOSCH_A_COAST_RANGE_BOUND
        meta["coast_bound"] = ri.coast_range_bound
        # D-053 range assist is built in (RANGE_VREL_ASSIST); radard reads it, as on the car
        rd = RDM.RadarD(radar_ts=RDM.DT_MDL, delay=float(cp.radarDelay), honda_bosch_a_radar=True)
        from opendbc.car.honda.values import DBC
        dbc = DBC[cp.carFingerprint]
        meta["dbc"] = dbc["pt"] if isinstance(dbc, dict) and "pt" in dbc else str(list(dbc.values())[0])
        continue
      if which == "can":
        if ri is not None:
          bosch = [CanData(c.address, bytes(c.dat), c.src) for c in msg.can if c.address in BOSCH_A_IDS]
          if bosch:
            rr = ri.update([(msg.logMonoTime, bosch)])
            if rr is not None:
              if vision_only:
                rr.init("points", 0)
              rr_latest = rr
              rsm.recv_frame["liveTracks"] += 1
              rsm.logMonoTime["liveTracks"] = msg.logMonoTime
              rsm.valid["liveTracks"] = not any(rr.errors.to_dict().values())
        if can_parser is None and "dbc" in meta:
          for c in msg.can:
            if c.address == ACC_CONTROL_ADDR and c.src < 128:
              meta["acc_control_bus"] = int(c.src)
              can_parser = CANParser(meta["dbc"], [("ACC_CONTROL", 50)], int(c.src))
              break
        if can_parser is not None:
          frames_in = [(c.address, bytes(c.dat), c.src) for c in msg.can if c.address == ACC_CONTROL_ADDR]
          if frames_in and ACC_CONTROL_ADDR in can_parser.update([(msg.logMonoTime, frames_in)]):
            accel_cmd = float(can_parser.vl["ACC_CONTROL"]["ACCEL_COMMAND"])
        continue
      if which == "radarState":
        state["radarState_logged"] = msg.radarState
        valid["radarState_logged"] = bool(msg.valid)
        continue
      if which in PLANNER_SERVICES:
        state[which] = getattr(msg, which)
        valid[which] = bool(msg.valid)
        if which in RADARD_SERVICES:
          rsm.msgs[which] = state[which]
          rsm.valid[which] = bool(msg.valid)
          rsm.logMonoTime[which] = msg.logMonoTime
          if which == "carState":
            rsm.recv_frame["carState"] += 1
        if which == "starpilotPlan":
          toggles = parse_toggles(state["starpilotPlan"].starpilotToggles, toggles)
        continue
      if which != "modelV2" or not planners or rr_latest is None:
        continue
      if not all(k in state for k in PLANNER_SERVICES) or "radarState_logged" not in state:
        continue

      model = msg.modelV2
      state["modelV2"] = model
      valid["modelV2"] = bool(msg.valid)
      rsm.msgs["modelV2"] = model
      rsm.valid["modelV2"] = bool(msg.valid)
      rsm.seen["modelV2"] = True
      rsm.logMonoTime["modelV2"] = msg.logMonoTime
      rd.update(rsm, rr_latest)
      rs = rd.radar_state.as_reader()

      cs = state["carState"]
      if meta["logged_op_long"]:
        long_state = state["controlsState"].longControlState
        engaged = long_state != LongCtrlState.off
        cstate = state["controlsState"]
      else:
        engaged = bool(cs.cruiseState.enabled) and not bool(cs.brakePressed)
        cstate = _ControlsStateView(state["controlsState"], LongCtrlState.pid if engaged else LongCtrlState.off)

      out = {}
      src = {}
      guard_trip = False
      hf_gate_fired = []
      fix_fired = {}
      blot_rec = None
      saved = LP.OFF_AXIS_LEAD_MIN_BEARING
      t_now = (msg.logMonoTime - t0) / 1e9
      in_sim = sim_window is not None and sim_window[0] <= t_now <= sim_window[1]
      dt = min(t_now - t_prev, 0.2) if t_prev is not None else 0.05
      t_prev = t_now
      logged_cmd = accel_cmd if not meta["logged_op_long"] else float(state["carControl"].actuators.accel)
      if sim_resid_model is None:
        sim_resid_model = _FirstOrderDelay(float(cs.aEgo))
      sim_resid = float(cs.aEgo) - sim_resid_model.step(logged_cmd if np.isfinite(logged_cmd) else float(cs.aEgo), dt)
      if not in_sim:
        sims.clear()
      else:
        for v in planners:
          if v == "logged":
            continue
          if v not in sims:
            sims[v] = SimCar(float(cs.vEgo), float(cs.aEgo))
          else:
            sims[v].step(dt, sim_resid, float(cs.vEgo))
      try:
        for v, p in planners.items():
          sm = _ReplaySM(state, valid)
          sm["controlsState"] = cstate
          if v in sims:
            sm["carState"], rs_sim, sm["modelV2"] = sims[v].views(cs, rs, model)
          if v == "logged":
            sm["radarState"] = state["radarState_logged"]
            sm._valid = {**valid, "radarState": valid["radarState_logged"]}
            LP.OFF_AXIS_LEAD_MIN_BEARING = saved
          else:
            sm["radarState"] = rs_sim if v in sims else rs
            sm._valid = {**valid, "radarState": bool(rd.radar_state_valid)}
            LP.OFF_AXIS_LEAD_MIN_BEARING = float(v[1:]) if v.startswith("b") else saved
          LP.MPC_LEAD_BRAKE_PASSES_COMFORT_FLOOR, LP.LC_MERGE_RELEASE_MPC_DEMAND = LATE_VARIANTS.get(v, LATE_DEFAULTS)
          if v in fix_bounds:
            fix_bounds[v].observe(rs, t_now, float(cs.vEgo))
            LP.off_axis_lead_a_lead = fix_bounds[v]
          if v == "alead_floor":
            LP.off_axis_lead_a_lead = floored_a_lead(original_bound)
          LP.FAR_LEAD_COAST_MAX_DECEL = 1e3 if v == "cap_off" else cap_default
          if v == "cap_radar":
            LP.far_lead_vision_braking = lambda model_msg: False
          if v in HUMAN_VARIANTS:
            vt = copy.copy(toggles)
            vt.human_following = v != "human_off"
            vt.human_acceleration = v != "human_off"
            if v == "human_off":
              LM.build_model_lead_trajectory = lambda *a, **k: None
            else:
              trips = []
              LM.build_model_lead_trajectory = frogpilot_model_lead_trajectory(
                float(getattr(toggles, "lead_detection_probability", 0.35)), v == "frog_guard", trips)
            p.update(sm, vt)
            LM.build_model_lead_trajectory = original_builder
          elif v == HF_GATE_VARIANT:
            LM.build_model_lead_trajectory = hf_gated_model_lead_trajectory(
              original_builder, float(getattr(toggles, "lead_detection_probability", 0.35)), hf_gate_fired)
            p.update(sm, toggles)
            LM.build_model_lead_trajectory = original_builder
          else:
            p.update(sm, toggles)
          LP.off_axis_lead_a_lead = original_bound
          LP.far_lead_vision_braking = original_vision_braking
          if v in fix_bounds:
            fix_fired[v] = fix_bounds[v].fired
          out[v] = float(p.output_a_target)
          if v == variants[0] and p._blotv3_policy is not None:
            bp = p._blotv3_policy
            blot_rec = [round(float(bp.jerk_scale), 3), round(float(bp.t_follow), 3), round(float(bp.required_decel), 2),
                    int(bp.emergency), int(bp.recovery_active), int(bp.model_active), int(bp.launch_active)]
          if v in sims:
            sims[v].u = out[v]
          if v == "frog_guard":
            guard_trip = bool(trips)
          src[v] = str(p.mpc.source)
      finally:
        LP.OFF_AXIS_LEAD_MIN_BEARING = saved
        LP.off_axis_lead_a_lead = original_bound
        LM.build_model_lead_trajectory = original_builder
        LP.MPC_LEAD_BRAKE_PASSES_COMFORT_FLOOR, LP.LC_MERGE_RELEASE_MPC_DEMAND = LATE_DEFAULTS
        LP.FAR_LEAD_COAST_MAX_DECEL = cap_default
        LP.far_lead_vision_braking = original_vision_braking

      lg = state["radarState_logged"].leadOne
      lr = rs.leadOne
      agree["ticks"] += 1
      agree["status_eq"] += int(bool(lg.status) == bool(lr.status))
      if lg.status and lr.status:
        agree["both"] += 1
        agree["radar"] += int(bool(lg.radar) == bool(lr.radar))
        agree["d1m"] += int(abs(float(lg.dRel) - float(lr.dRel)) < 1.0)
        agree["track"] += int(bool(lg.radar) and bool(lr.radar) and int(lg.radarTrackId) == int(lr.radarTrackId))

      frames.append({
        "t": (msg.logMonoTime - t0) / 1e9, "engaged": engaged, "v_ego": float(cs.vEgo), "a_ego": float(cs.aEgo),
        "accel_cmd": accel_cmd if not meta["logged_op_long"] else float(state["carControl"].actuators.accel),
        "steer": float(cs.steeringAngleDeg), "out": out, "src": src, "brake": bool(cs.brakePressed), "fix": fix_fired, "guard_trip": guard_trip,
        "hf_gate": bool(hf_gate_fired), "blot": blot_rec,
        "sim": {v: [round(c.v, 3), round(c.a, 3), round(c.gap_shift, 2)] for v, c in sims.items()},
        "vis": vision_view(model, float(cs.vEgo)),
        "lead": lead_view(lr, model, bearings), "lead_logged_bearing":
          abs(float(lg.yRel)) / max(float(lg.dRel), 1.0) if lg.status and lg.radar else None,
      })
  meta["agreement"] = agree
  meta["variants"] = variants
  return frames, meta


def _cross(frames, idx, fn, thr):
  return next((frames[i]["t"] for i in idx if fn(frames[i]) < thr), None)


def episodes(frames: list[dict], meta: dict, thr: float) -> list[dict]:
  variants = meta["variants"]

  def ok(f):
    return f["engaged"] and f["v_ego"] > MOVING_MIN_V

  def stock_min(f):
    c = f["accel_cmd"]
    return min(f["a_ego"], c if math.isfinite(c) else 0.0)

  flagged = [i for i, f in enumerate(frames) if ok(f) and min(min(f["out"].values()), stock_min(f)) < thr]
  groups: list[list[int]] = []
  for i in flagged:
    if groups and frames[i]["t"] - frames[groups[-1][-1]]["t"] <= EPISODE_MERGE_GAP_S:
      groups[-1].append(i)
    else:
      groups.append([i])

  base = variants[0]
  eps = []
  for g in groups:
    lo = g[0]
    while lo > 0 and frames[g[0]]["t"] - frames[lo - 1]["t"] < 3.0:
      lo -= 1
    hi = g[-1]
    while hi + 1 < len(frames) and frames[hi + 1]["t"] - frames[g[-1]]["t"] < 1.0:
      hi += 1
    idx = [i for i in range(lo, hi + 1) if ok(frames[i])]
    ep: dict = {"start": frames[g[0]]["t"], "end": frames[g[-1]]["t"], "min": {}, "cross": {}}
    for v in variants:
      ep["min"][v] = min(frames[i]["out"][v] for i in idx)
      for c in CROSS_LEVELS:
        ep["cross"][f"{v}@{c}"] = _cross(frames, idx, lambda f, v=v: f["out"][v], c)
    finite_cmd = [frames[i]["accel_cmd"] for i in idx if math.isfinite(frames[i]["accel_cmd"])]
    ep["min"]["cmd"] = min(finite_cmd) if finite_cmd else float("nan")
    ep["min"]["aEgo"] = min(frames[i]["a_ego"] for i in idx)
    for c in CROSS_LEVELS:
      ep["cross"][f"cmd@{c}"] = _cross(frames, idx, lambda f: f["accel_cmd"] if math.isfinite(f["accel_cmd"]) else 0.0, c)
      ep["cross"][f"aEgo@{c}"] = _cross(frames, idx, lambda f: f["a_ego"], c)
    leads = [frames[i]["lead"] for i in idx if frames[i]["lead"].get("status")]
    ep["max_bearing"] = max((ld["bearing"] for ld in leads if ld["radar"]), default=float("nan"))
    ep["min_visA"] = min((ld["visA"] for ld in leads if math.isfinite(ld["visA"])), default=float("nan"))
    ep["bound_frames"] = {f"{b:g}": sum(1 for ld in leads if ld.get(f"bound@{b:g}")) for b in meta["bearings"]}
    ep["steer_max"] = max(abs(frames[i]["steer"]) for i in idx)
    ep["fix_frames"] = {k: sum(1 for i in idx if frames[i].get("fix", {}).get(k)) for k in FIX_VARIANTS if k in variants}
    vis = [frames[i]["vis"] for i in idx if frames[i]["vis"] is not None and frames[i]["vis"]["p"] >= VISION_REF_MIN_PROB]
    n_req = sum(1 for x in vis if x["req"] >= VISION_REF_MIN_REQ)
    n_a = sum(1 for x in vis if x["a"] <= VISION_REF_MAX_A)
    vision_ref = n_req >= VISION_REF_MIN_FRAMES or n_a >= VISION_REF_MIN_FRAMES
    stock_ref = not meta["logged_op_long"] and math.isfinite(ep["min"]["cmd"]) and ep["min"]["cmd"] < STOCK_REF_CMD
    ep["ref"] = {"vision": vision_ref, "stock": stock_ref, "genuine": vision_ref or stock_ref,
                 "req_frames": n_req, "visA_frames": n_a, "max_req": max((x["req"] for x in vis), default=0.0),
                 "driver_brake": any(frames[i]["brake"] for i in range(lo, hi + 1)),
                 "legacy": (math.isfinite(ep["min"]["cmd"]) and ep["min"]["cmd"] < STOCK_REF_CMD) or
                           (math.isfinite(ep["min_visA"]) and ep["min_visA"] <= VISION_REF_MAX_A)}
    imin = min(idx, key=lambda i: frames[i]["out"][base])
    ep["src_at_min"] = frames[imin]["src"][base]
    ep["lead_at_min"] = frames[imin]["lead"]
    ep["changed"] = {}
    for v in variants[1:]:
      if v in ("nobound", "logged"):
        continue
      da = ep["min"][v] - ep["min"][base]
      c0, c1 = ep["cross"][f"{base}@-1.5"], ep["cross"][f"{v}@-1.5"]
      dt = None if c0 is None or c1 is None else c1 - c0
      moved = abs(da) > CHANGE_DA or (dt is not None and abs(dt) > CHANGE_DT) or ((c0 is None) != (c1 is None))
      ep["changed"][v] = {"da": da, "dt": dt, "moved": moved}
    ep["lead_trace"] = [[round(frames[i]["t"], 2), frames[i]["lead"], {k: round(x, 2) for k, x in frames[i]["out"].items()}]
                        for i in idx[::5]]
    eps.append(ep)
  return eps


def frame_diffs(frames: list[dict], meta: dict) -> dict:
  """Engaged, moving frames where each bearing variant differs from the first by more than CHANGE_DA."""
  base = meta["variants"][0]
  out = {}
  for v in meta["variants"][1:]:
    if v in ("nobound", "logged"):
      continue
    hits = [f["t"] for f in frames if f["engaged"] and f["v_ego"] > MOVING_MIN_V and abs(f["out"][v] - f["out"][base]) > CHANGE_DA]
    clusters: list[list[float]] = []
    for t in hits:
      if clusters and t - clusters[-1][-1] <= 2.0:
        clusters[-1].append(t)
      else:
        clusters.append([t])
    out[v] = {"frames": len(hits), "clusters": [[round(c[0], 2), round(c[-1], 2), len(c)] for c in clusters]}
  return out


def _ref_label(ref: dict) -> str:
  tags = [t for t, on in (("vision", ref["vision"]), ("stock", ref["stock"]), ("driver-brake", ref["driver_brake"])) if on]
  return ("GENUINE " if ref["genuine"] else "") + ("+".join(tags) or "-") + f" req {ref['max_req']:.1f}"


def print_report(meta, frames, eps, diffs, thr):
  a = meta["agreement"]
  engaged = sum(1 for f in frames if f["engaged"])

  def pct(n, d):
    return f"{100.0 * n / d:.2f}%" if d else "-"
  print("  ".join([f"route {meta['route_dir']}", f"build {meta.get('git_commit')}", str(meta.get("fingerprint")),
                   f"segs {len(meta['segments'])}", f"opLong {meta.get('logged_op_long')}", f"BLoTv3 {meta.get('blotv3')}",
                   f"bound {meta.get('bound_active')}", f"bearings {meta['bearings']}"]))
  print(f"frames {len(frames)}, engaged {engaged} ({engaged * 0.05:.0f} s); episodes below {thr}: {len(eps)}")
  print(f"validity (replayed vs logged leadOne): status {pct(a['status_eq'], a['ticks'])}; both-lead {a['both']} ticks: " +
        f"radar {pct(a['radar'], a['both'])}, |dRel|<1m {pct(a['d1m'], a['both'])}, same track {pct(a['track'], a['both'])}")
  for v, d in diffs.items():
    print(f"frame diffs {v} vs {meta['variants'][0]} (|d| > {CHANGE_DA}): {d['frames']} frames in {len(d['clusters'])} clusters "
          + ", ".join(f"{fmt_t(c[0])}({c[2]})" for c in d["clusters"][:20]))
  variants = meta["variants"]
  print(" | ".join(["start"] + [f"{v} min" for v in variants] + ["cmd", "aEgo", "brg max", "visA min", "bound frames", "ref", "changed"]))
  for ep in eps:
    ch = ",".join(f"{v}:{fnum(c['da'])}/{fnum(c['dt'], 1)}" for v, c in ep["changed"].items() if c["moved"])
    print(" | ".join([fmt_t(ep["start"])] + [fnum(ep["min"][v]) for v in variants] +
                     [fnum(ep["min"]["cmd"]), fnum(ep["min"]["aEgo"]), fnum(ep["max_bearing"], 3), fnum(ep["min_visA"]),
                      "/".join(str(x) for x in list(ep["bound_frames"].values()) + list(ep.get("fix_frames", {}).values())), _ref_label(ep["ref"]), ch or "-"]))


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("route_dir", type=Path, help="<out>/<ROUTE> directory written by tools/konik_fetch.py")
  ap.add_argument("--bearings", default=DEFAULT_BEARINGS,
                  help="comma list; the first is the baseline the others are diffed against")
  ap.add_argument("--threshold", type=float, default=-1.5)
  ap.add_argument("--fixes", action="store_true", help="add the replay-only 'hold' and 'visdis' bound variants (STATUS 107)")
  ap.add_argument("--coast-bound", action="store_true",
                  help="bound Bosch-A coasts by their fresh range fit, as RangeDerivedVrel does on the car (STATUS 111)")
  ap.add_argument("--human-ab", action="store_true",
                  help="add HumanFollowing/HumanAcceleration variants: 'human_off' (both off) and 'frog' (FrogPilot path)")
  ap.add_argument("--vision-only", action="store_true", help="drop every radar point, so radard publishes vision leads only")
  ap.add_argument("--late-ab", action="store_true",
                  help="add STATUS 119 variants: 'late_off' (both fixes off), 'late_A' / 'late_B' (one fix only)")
  ap.add_argument("--hf-gate", action="store_true",
                  help="add 'hf_gate': HumanFollowing also needs the radar lead's modelProb (FrogPilot e7debabe5)")
  ap.add_argument("--brake-ab", action="store_true",
                  help="add 'cap_off' (cap disabled), 'cap_radar' (cap ignores vision, as before), 'alead_floor'")
  ap.add_argument("--blot-ab", action="store_true", help="add 'noblot': the BLoTv3 supervisor off")
  ap.add_argument("--sim-window", help="T0,T1 route seconds: each variant drives its own simulated car there (SIM_DELAY)")
  ap.add_argument("--frames-json", type=Path, help="write every replayed frame here, for charts (keep it outside the repo)")
  ap.add_argument("--json", type=Path, help="write episodes + metadata here (keep it outside the repo)")
  args = ap.parse_args()

  bearings = [float(x) for x in args.bearings.split(",")]
  frames, meta = replay(args.route_dir, bearings, args.fixes, args.coast_bound, args.human_ab, args.vision_only,
                        args.late_ab, args.hf_gate, args.brake_ab, args.blot_ab,
                        tuple(float(x) for x in args.sim_window.split(",")) if args.sim_window else None)
  eps = episodes(frames, meta, args.threshold)
  diffs = frame_diffs(frames, meta)
  print_report(meta, frames, eps, diffs, args.threshold)
  if args.json:
    args.json.write_text(json.dumps({"meta": meta, "episodes": eps, "diffs": diffs}, indent=1, default=str))
  if args.frames_json:
    args.frames_json.write_text(json.dumps({"meta": meta, "frames": frames}, default=str))
  return 0


if __name__ == "__main__":
  sys.exit(main())
