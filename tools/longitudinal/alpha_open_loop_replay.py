#!/usr/bin/env python3
"""Open-loop alpha-long planner replay on a stock-ACC route (STATUS 74c method, rebuilt).

What it does
------------
Feeds a stock-ACC route's logged carState, radarState, modelV2, starpilotPlan, selfdriveState,
carControl, liveParameters and starpilotCarState into `LongitudinalPlanner` at every modelV2 tick,
exactly as plannerd would, and compares the planner's `output_a_target` against what the car's own
ACC did: `carState.aEgo` and the stock radar's `ACC_CONTROL.ACCEL_COMMAND` decoded with the car's DBC.

It reports every episode where either side goes below a threshold (default -1.5 m/s^2) while stock
ACC is engaged, with the lead geometry at each side's onset and at alpha's minimum.

Two planners run on the same input in the same pass:
  * `alpha`   -- the tree as it is (the STATUS 74e/74g off-axis aLeadK bound active on Bosch-A Hondas)
  * `nobound` -- the same planner with that bound switched off (74f's `TAG=before`)
so the bound's effect on each episode is visible without a second run.

What it is NOT (read before quoting a number)
---------------------------------------------
* **Open loop.** Ego follows stock ACC. Once alpha and stock diverge, the later alpha values are what
  alpha would command *from stock's state*, not what alpha would have done on its own trajectory.
* Command replay only. It says what the planner would ask for, not what the car's brake would deliver
  (STATUS 71/72: the Honda Bosch brake ECU over-delivers fast brake onsets).
* The logged CarParams are stock long. The replay flips `openpilotLongitudinalControl` on and
  `pcmCruise` off (the alpha-long configuration) and synthesises `controlsState.longControlState`:
  `pid` while the car's cruise is engaged and the brake pedal is up, `off` otherwise. Under stock ACC
  the logged state is always `off`, which would reset the planner every frame.
* BLoTv3 was removed on 2026-09-30. The route's own initData BlotV3 is still printed, because a route driven
  with it ON cannot be reproduced by this replay (STATUS 52 found that the largest replay-vs-car gap).
* radarState is the logged one, produced on-device by the build that drove. It is not re-run through the
  current radard or Bosch-A parser. Name that build next to any result.

Route data is never committed (AGENTS.md section 7): the route directory is a required argument with
no default. Layout is tools/konik_fetch.py's: <route_dir>/<segment>/rlog.zst.

Usage
-----
    python tools/longitudinal/alpha_open_loop_replay.py ROUTE_DIR [--threshold -1.5] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DEBUG", "0")


from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib import longitudinal_planner as LP
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import STOP_DISTANCE
from openpilot.tools.lib.logreader import LogReader
from opendbc.can.parser import CANParser

for _level in ("info", "warning", "error", "exception", "event", "debug"):
  if hasattr(cloudlog, _level):
    setattr(cloudlog, _level, lambda *a, **k: None)


ACC_CONTROL_ADDR = 0x1DF
PLANNER_SERVICES = ("carState", "radarState", "starpilotPlan", "selfdriveState", "carControl",
                    "liveParameters", "starpilotCarState", "controlsState")
# Flagged frames closer than this are one episode; the 3 s pre-roll below must not straddle two episodes.
EPISODE_MERGE_GAP_S = 3.0
ONSET_SOFT = -0.5
# Stock ACC holds ACCEL_COMMAND at -4.0 at standstill; that is a hold, not a brake event.
MOVING_MIN_V = 1.0
CROSS_LEVELS = (-1.0, -1.5, -2.5)


def default_toggles() -> SimpleNamespace:
  # Same defaults as tools/longitudinal/score_route_longitudinal.py; the stock-long builds in this
  # corpus log an empty starpilotToggles string.
  return SimpleNamespace(taco_tune=False, classic_model=False, tinygrad_model=True, model_version="v11",
                         stop_distance=float(STOP_DISTANCE), vEgoStopping=0.5)


def parse_toggles(serialized: str, previous: SimpleNamespace) -> SimpleNamespace:
  if not serialized:
    return previous
  payload = vars(default_toggles())
  try:
    payload.update(json.loads(serialized))
  except Exception:
    return previous
  return SimpleNamespace(**payload)


class _ControlsStateView:
  """controlsState with longControlState replaced by the synthesised alpha-long state."""
  def __init__(self, cs, long_state):
    self._cs = cs
    self.longControlState = long_state

  def __getattr__(self, name):
    return getattr(self._cs, name)


class _ReplaySM(dict):
  """Dict of the latest logged messages plus the one SubMaster method the planner's update() calls.

  all_checks() answers from each message's logged `valid` flag; alive/frequency are not reconstructable
  from a log and are taken as good.
  """
  def __init__(self, msgs, valid):
    super().__init__(msgs)
    self._valid = valid

  def all_checks(self, service_list=None):
    return all(self._valid.get(s, True) for s in (service_list or self.keys()))


def alpha_car_params(cp):
  b = cp.as_builder()
  b.openpilotLongitudinalControl = True
  b.pcmCruise = False
  return b.as_reader()


def segment_files(route_dir: Path) -> list[Path]:
  segs = []
  for d in route_dir.iterdir():
    if d.is_dir() and d.name.isdigit():
      for name in ("rlog.zst", "rlog.bz2", "rlog"):
        if (d / name).exists():
          segs.append((int(d.name), d / name))
          break
  return [p for _, p in sorted(segs)]


def fmt_t(t: float) -> str:
  t = round(t, 1)
  return f"{int(t // 60)}:{t - 60 * int(t // 60):04.1f}"


@dataclass
class Frame:
  t: float
  engaged: bool
  a_alpha: float
  a_nobound: float
  a_ego: float
  accel_cmd: float
  v_ego: float
  v_cruise: float
  steer_deg: float
  src_alpha: str
  src_nobound: str
  lead: dict = field(default_factory=dict)


def lead_snapshot(radar_state, model) -> dict:
  lead = radar_state.leadOne
  if not lead.status:
    return {"status": False}
  d = float(lead.dRel)
  y = float(lead.yRel)
  vis_a = vis_p = float("nan")
  if len(model.leadsV3) > 0:
    vis_p = float(model.leadsV3[0].prob)
    if len(model.leadsV3[0].a) > 0:
      vis_a = float(model.leadsV3[0].a[0])
  return {
    "status": True, "radar": bool(lead.radar), "d": d, "y": y, "vRel": float(lead.vRel),
    "vLead": float(lead.vLead), "aLeadK": float(lead.aLeadK), "prob": float(lead.modelProb),
    "bearing": abs(y) / max(d, 1.0), "track": int(lead.radarTrackId), "visA": vis_a, "visP": vis_p,
    "offAxisBound": LP.off_axis_lead_a_lead(lead, model) is not None,
  }


def replay(route_dir: Path) -> tuple[list[Frame], dict]:
  files = segment_files(route_dir)
  if not files:
    raise SystemExit(f"no rlog segments under {route_dir}")

  state: dict = {}
  valid: dict = {}
  toggles = default_toggles()
  alpha = nobound = None
  can_parser = None
  acc_bus = None
  accel_cmd = float("nan")
  t0 = None
  meta: dict = {"route_dir": str(route_dir), "segments": [int(p.parent.name) for p in files]}
  frames: list[Frame] = []

  for path in files:
    for msg in LogReader(str(path), sort_by_time=True):
      which = msg.which()
      if t0 is None and which == "initData":
        # Every segment's initData carries the route-start logMonoTime, so route time is exact even when the
        # fetch starts mid-route (STATUS 74c's 25b clock: seg 11 events read 11:0x).
        t0 = msg.logMonoTime
      if t0 is None:
        continue
      if which == "initData" and "blotv3" not in meta:
        params = {e.key: bytes(e.value) for e in msg.initData.params.entries}
        meta["blotv3"] = params.get("BlotV3", b"0") in (b"1", b"True", b"true")
        meta["git_commit"] = msg.initData.gitCommit[:9]
        continue
      if which == "carParams" and alpha is None:
        cp = msg.carParams
        meta["fingerprint"] = str(cp.carFingerprint)
        meta["logged_op_long"] = bool(cp.openpilotLongitudinalControl)
        acp = alpha_car_params(cp)
        alpha, nobound = LP.LongitudinalPlanner(acp), LP.LongitudinalPlanner(acp)
        nobound.bound_off_axis_radar_leads = False
        meta["bound_active"] = bool(alpha.bound_off_axis_radar_leads)
        from opendbc.car.honda.values import DBC
        dbc = DBC[cp.carFingerprint]
        meta["dbc"] = dbc["pt"] if isinstance(dbc, dict) and "pt" in dbc else str(list(dbc.values())[0])
        continue
      if which == "can":
        # CAN arrives before carParams, so the parser is built on the first ACC_CONTROL frame after the DBC
        # is known. The bus is read from the log, not assumed: on this car the stock radar's ACC_CONTROL is
        # on bus 1 (dongle 11c8fa231c0499ed, all builds in STATUS 103).
        if can_parser is None and "dbc" in meta:
          for c in msg.can:
            if c.address == ACC_CONTROL_ADDR and c.src < 128:
              acc_bus = int(c.src)
              meta["acc_control_bus"] = acc_bus
              can_parser = CANParser(meta["dbc"], [("ACC_CONTROL", 50)], acc_bus)
              break
        if can_parser is not None:
          frames_in = [(c.address, bytes(c.dat), c.src) for c in msg.can if c.address == ACC_CONTROL_ADDR]
          if frames_in and ACC_CONTROL_ADDR in can_parser.update([(msg.logMonoTime, frames_in)]):
            accel_cmd = float(can_parser.vl["ACC_CONTROL"]["ACCEL_COMMAND"])
        continue
      if which in PLANNER_SERVICES:
        state[which] = getattr(msg, which)
        valid[which] = bool(msg.valid)
        if which == "starpilotPlan":
          toggles = parse_toggles(state["starpilotPlan"].starpilotToggles, toggles)
        continue
      if which != "modelV2" or alpha is None or not all(k in state for k in PLANNER_SERVICES):
        continue

      state["modelV2"] = msg.modelV2
      cs = state["carState"]
      engaged = bool(cs.cruiseState.enabled) and not bool(cs.brakePressed)
      valid["modelV2"] = bool(msg.valid)
      sm = _ReplaySM(state, valid)
      sm["controlsState"] = _ControlsStateView(state["controlsState"], LongCtrlState.pid if engaged else LongCtrlState.off)
      alpha.update(sm, toggles)
      nobound.update(sm, toggles)
      frames.append(Frame(
        t=(msg.logMonoTime - t0) / 1e9, engaged=engaged,
        a_alpha=float(alpha.output_a_target), a_nobound=float(nobound.output_a_target),
        a_ego=float(cs.aEgo), accel_cmd=accel_cmd, v_ego=float(cs.vEgo),
        v_cruise=float(state["starpilotPlan"].vCruise), steer_deg=float(cs.steeringAngleDeg),
        src_alpha=str(alpha.mpc.source), src_nobound=str(nobound.mpc.source),
        lead=lead_snapshot(state["radarState"], msg.modelV2),
      ))
  return frames, meta


def _onset(frames: list[Frame], idx: list[int], key: str, thr: float, imin):
  """First frame in the episode below thr, and the start of the ramp (walk back while < ONSET_SOFT).

  A side that never crosses thr still gets a ramp start when its minimum is below ONSET_SOFT, so the
  alpha-vs-stock lag is measurable when only one side brakes hard.
  """
  hit = next((i for i in idx if getattr(frames[i], key) < thr), None)
  if hit is None:
    if imin is None or not getattr(frames[imin], key) < ONSET_SOFT:
      return None, None
    j = imin
    while j > 0 and getattr(frames[j - 1], key) < ONSET_SOFT and frames[imin].t - frames[j - 1].t < 5.0:
      j -= 1
    return None, frames[j].t
  j = hit
  while j > 0 and getattr(frames[j - 1], key) < ONSET_SOFT and frames[hit].t - frames[j - 1].t < 5.0:
    j -= 1
  return frames[hit].t, frames[j].t


def episodes(frames: list[Frame], thr: float) -> list[dict]:
  flagged = [i for i, f in enumerate(frames) if f.engaged and f.v_ego > MOVING_MIN_V and
             min(f.a_alpha, f.a_nobound, f.a_ego, f.accel_cmd if math.isfinite(f.accel_cmd) else 0.0) < thr]
  groups: list[list[int]] = []
  for i in flagged:
    if groups and frames[i].t - frames[groups[-1][-1]].t <= EPISODE_MERGE_GAP_S:
      groups[-1].append(i)
    else:
      groups.append([i])

  out = []
  for g in groups:
    lo = g[0]
    while lo > 0 and frames[g[0]].t - frames[lo - 1].t < 3.0:
      lo -= 1
    hi = g[-1]
    while hi + 1 < len(frames) and frames[hi + 1].t - frames[g[-1]].t < 1.0:
      hi += 1
    idx = [i for i in range(lo, hi + 1) if frames[i].engaged and frames[i].v_ego > MOVING_MIN_V]
    ep = {"start": frames[g[0]].t, "end": frames[g[-1]].t}
    for key in ("a_alpha", "a_nobound", "a_ego", "accel_cmd"):
      vals = [(getattr(frames[i], key), i) for i in idx if math.isfinite(getattr(frames[i], key))]
      vmin, imin = min(vals) if vals else (float("nan"), None)
      on, ramp = _onset(frames, idx, key, thr, imin)
      ep[key] = {"min": vmin, "t_min": frames[imin].t if imin is not None else None, "onset": on, "ramp": ramp}
      if key == "a_alpha" and imin is not None:
        ep["lead_at_alpha_min"] = frames[imin].lead
        ep["src_at_alpha_min"] = frames[imin].src_alpha
    stock_on = [x for x in (ep["a_ego"]["onset"], ep["accel_cmd"]["onset"]) if x is not None]
    ref_t = ep["a_alpha"]["onset"] or (min(stock_on) if stock_on else frames[g[0]].t)
    ref = min(idx, key=lambda i: abs(frames[i].t - ref_t))
    ep["lead_at_onset"] = frames[ref].lead
    leads = [frames[i].lead for i in idx if frames[i].lead.get("status")]
    ep["v_ego"] = frames[ref].v_ego
    ep["v_cruise"] = frames[ref].v_cruise
    ep["steer_deg_max"] = max(abs(frames[i].steer_deg) for i in idx)
    ep["max_bearing"] = max((ld["bearing"] for ld in leads if ld["radar"]), default=float("nan"))
    ep["min_aLeadK"] = min((ld["aLeadK"] for ld in leads), default=float("nan"))
    ep["min_visA"] = min((ld["visA"] for ld in leads if math.isfinite(ld["visA"])), default=float("nan"))
    ep["min_d"] = min((ld["d"] for ld in leads), default=float("nan"))
    ep["bound_frames"] = sum(1 for ld in leads if ld.get("offAxisBound"))
    ep["setspeed_below_vego"] = frames[ref].v_cruise < frames[ref].v_ego - 0.5
    # Same-threshold crossing times, command against command. Less sensitive than the ramp start to a long
    # gentle stretch below ONSET_SOFT, which can move a ramp start by several seconds.
    ep["cross"] = {}
    for thr_c in CROSS_LEVELS:
      for key in ("a_alpha", "a_nobound", "accel_cmd", "a_ego"):
        ep["cross"][f"{key}@{thr_c}"] = next((frames[i].t for i in idx if getattr(frames[i], key) < thr_c), None)
    ep["lead_trace"] = [[round(frames[i].t, 2), frames[i].lead] for i in idx[::10]]
    # Lag = alpha crossing minus stock crossing at the same threshold (STATUS 103). Positive: alpha trails.
    ep["lag"] = {}
    for thr_c in CROSS_LEVELS:
      t_alpha = ep["cross"][f"a_alpha@{thr_c}"]
      for key, name in (("accel_cmd", "cmd"), ("a_ego", "aego")):
        t_stock = ep["cross"][f"{key}@{thr_c}"]
        ep["lag"][f"{name}@{thr_c}"] = t_alpha - t_stock if t_alpha is not None and t_stock is not None else None
    # Ramp-start lags are kept for reference only; they move by seconds on gentle pre-brake stretches.
    ar = ep["a_alpha"]["ramp"]
    ep["ramp_lag_cmd"] = ar - ep["accel_cmd"]["ramp"] if ar is not None and ep["accel_cmd"]["ramp"] is not None else None
    ep["ramp_lag_aego"] = ar - ep["a_ego"]["ramp"] if ar is not None and ep["a_ego"]["ramp"] is not None else None
    out.append(ep)
  return out


def fnum(x, nd=2):
  return "-" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{nd}f}"


def print_report(meta: dict, frames: list[Frame], eps: list[dict], thr: float) -> None:
  engaged = [f for f in frames if f.engaged]
  print("  ".join([f"route {meta['route_dir']}", f"build {meta.get('git_commit')}", str(meta.get("fingerprint")),
                   f"segs {len(meta['segments'])}", f"BLoTv3 logged {meta.get('blotv3')} (removed; not replayed)", f"bound {meta.get('bound_active')}",
                   f"ACC_CONTROL bus {meta.get('acc_control_bus')}"]))
  print(f"frames {len(frames)}, engaged {len(engaged)} ({len(engaged) * 0.05:.0f} s); episodes below {thr}: {len(eps)}")
  # ramp = start of the run below -0.5 that leads into the minimum (context only, not used for lag).
  # lag = alpha crossing minus stock crossing at the same threshold (positive: alpha trails); "-" when either
  # side never crosses. lag cmd compares command with command; lag aEgo is against the car's response.
  hdr = ("start", "alpha min@t", "alpha ramp", "nobound min", "cmd min@t", "cmd ramp", "aEgo min@t", "aEgo ramp",
         "lag cmd@-1.5", "lag aEgo@-1.5", "lag cmd@-2.5", "lag aEgo@-2.5",
         "d", "vRel", "aLeadK", "brg", "brg max", "visA", "steer", "vEgo", "set<v", "src", "bound")
  print(" | ".join(hdr))
  for ep in eps:
    a, nb, ae, ac = ep["a_alpha"], ep["a_nobound"], ep["a_ego"], ep["accel_cmd"]
    ld = ep["lead_at_onset"]

    def at(side):
      return f"{fnum(side['min'])}@{fmt_t(side['t_min']) if side['t_min'] is not None else '-'}"

    def ts(x):
      return fmt_t(x) if x is not None else "-"
    print(" | ".join([
      fmt_t(ep["start"]), at(a), ts(a["ramp"]), fnum(nb["min"]), at(ac), ts(ac["ramp"]), at(ae), ts(ae["ramp"]),
      fnum(ep["lag"]["cmd@-1.5"], 1), fnum(ep["lag"]["aego@-1.5"], 1),
      fnum(ep["lag"]["cmd@-2.5"], 1), fnum(ep["lag"]["aego@-2.5"], 1),
      fnum(ld.get("d"), 1), fnum(ld.get("vRel"), 1), fnum(ld.get("aLeadK"), 1), fnum(ld.get("bearing"), 3),
      fnum(ep["max_bearing"], 3), fnum(ld.get("visA"), 2), fnum(ep["steer_deg_max"], 0), fnum(ep["v_ego"], 1),
      "y" if ep["setspeed_below_vego"] else "", ep.get("src_at_alpha_min", "-"), str(ep["bound_frames"]),
    ]))


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("route_dir", type=Path, help="<out>/<ROUTE> directory written by tools/konik_fetch.py")
  ap.add_argument("--threshold", type=float, default=-1.5)
  ap.add_argument("--json", type=Path, help="write episodes + metadata here (keep it outside the repo)")
  args = ap.parse_args()

  frames, meta = replay(args.route_dir)
  eps = episodes(frames, args.threshold)
  print_report(meta, frames, eps, args.threshold)
  if args.json:
    args.json.write_text(json.dumps({"meta": meta, "episodes": eps}, indent=1, default=str))
  return 0


if __name__ == "__main__":
  sys.exit(main())
