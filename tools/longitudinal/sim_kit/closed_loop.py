#!/usr/bin/env python3
"""End-of-stop crawl candidates (scratch, Radar Work, replay only). Current tree planner (selfdrive.controls.lib).
  r5.py EVENTS.json OUT.pkl
EVENTS.json: list of {id, route, segs:[..], T0, T1, tref:'abs'|'init'}; T in seconds (abs = logMonoTime/1e9, init =
  since initData). From T0 each candidate drives its own plant (r3 Sim: tau PLANT_TAU, gain PLANT_GAIN) plus a
  Honda stopping-state model (should_stop and v < 0.5: output held, ramps toward -0.6 at 0.1 m/s^3).
  Candidate 'OL' is the current planner fed the logged ego state throughout (open-loop shadow).
"""
import json, os, pickle, sys, types
from pathlib import Path
import numpy as np
os.environ.setdefault("DEBUG", "0")
# (2) the car's planner (pr10-smooth 07b66420) in place of the working-tree module, before anything imports it
import importlib.util
_KIT = os.path.dirname(os.path.abspath(__file__))
_CAR_LP = os.environ.get("CAR_LP", os.path.join(_KIT, "car", "longitudinal_planner.py"))
if _CAR_LP:
  import openpilot.selfdrive.controls.lib  # parent package
  for _n in filter(None, os.environ.get("CAR_LIBS", "longitudinal_lead,blotv3,accel_boost").split(",")):  # removed from the tree with BLoTv3; the 2a6 build (87505f426) imports them
    _bs = importlib.util.spec_from_file_location(f"openpilot.selfdrive.controls.lib.{_n}", os.path.join(_KIT, "car", f"{_n}.py"))
    _bm = importlib.util.module_from_spec(_bs); sys.modules[_bs.name] = _bm; _bs.loader.exec_module(_bm)
  _spec = importlib.util.spec_from_file_location("openpilot.selfdrive.controls.lib.longitudinal_planner", _CAR_LP)
  _mod = importlib.util.module_from_spec(_spec)
  sys.modules["openpilot.selfdrive.controls.lib.longitudinal_planner"] = _mod
  _spec.loader.exec_module(_mod)
sys.path.insert(0, os.path.join(_KIT, "plant"))
if os.environ.get("PLANT_MODULE", "plant") == "plant_bp":  # Steve's brake-overshoot plant (bpos/bpos2 params)
  from plant_bp import Plant
else:
  from plant import Plant
from openpilot.tools.lib.logreader import LogReader
from openpilot.tools.longitudinal import alpha_closed_loop_replay as T
from openpilot.tools.longitudinal.alpha_open_loop_replay import _ReplaySM, alpha_car_params, default_toggles, parse_toggles, segment_files
import openpilot.selfdrive.controls.lib.longitudinal_planner as LP
if os.environ.get("MPC_QP_CAP_RESOLVE") is not None:  # D-126 re-solve; 0 for builds before fd7dd7701
  import openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc as _LM
  _LM.MPC_QP_CAP_RESOLVE = os.environ["MPC_QP_CAP_RESOLVE"] == "1"
LP.time = T.LOG_CLOCK
print("CHECK planner", LP.__file__, "BRAKE_RELEASE_DWELL" in dir(LP), "PARAMS_ROOT", os.environ.get("PARAMS_ROOT"),
      "PLANT", os.environ.get("PLANT", "new"), flush=True)
PLANT = os.environ.get("PLANT", "new")

TAU = float(os.environ.get("PLANT_TAU", "0.3")); GAIN = float(os.environ.get("PLANT_GAIN", "1.1"))
CANDS = os.environ.get("CANDS", "OLON,OLOFF,ON,OFF").split(",")
STOP_SNAP = os.environ.get("STOP_SNAP", "1") == "1"
V_STOPPING = 0.5; STOP_RATE = 0.1; HOLD_A = -0.6
# Engaged starpilotPlan follow values (logged 297 longActive: 1.45/250/100/5.5) forced on stock-ACC events. Index [decel?].
SP_TF = 1.25; SP_AJ = {False: 125.0, True: 125.0}; SP_DJ = 50.0; SP_SJ = {False: 2.75, True: 2.75}  # car now: LongitudinalPersonality 0, CustomPersonalities 0; logged on 298 active

# Headway fade near a stopped lead: t_follow -> interp(v_ego, [v0, v1], [tmin, T]) weighted by
# w = clip((vl_hi - vLead)/(vl_hi - vl_lo), 0, 1) of lead_one (radar or vision). Only lowers T.
CFG = {
  "C5": {}, "OL": {},
  "H1": dict(v0=2.0, v1=8.0, tmin=0.6, vl_lo=0.5, vl_hi=2.0),
  "H2": dict(v0=3.0, v1=12.0, tmin=0.4, vl_lo=0.5, vl_hi=2.0),
  "H3": dict(v0=2.0, v1=8.0, tmin=0.9, vl_lo=0.5, vl_hi=2.0),
  # wider lead gate: fades while the lead itself is still rolling down through 6..2 m/s
  "H4": dict(v0=2.0, v1=10.0, tmin=0.5, vl_lo=2.0, vl_hi=6.0),
  "H5": dict(v0=2.0, v1=10.0, tmin=0.8, vl_lo=2.0, vl_hi=6.0),
  # K: constant-decel stop commit. Stopped radar lead (vLead < 0.5, aLeadK <= 0.5), v_ego <= vmax:
  # output = min(output, max(-v^2 / (2 (dRel - dstop)), amin)). Only ever brakes harder, never closer.
  "K1": dict(kind="K", dstop=5.0, vmax=6.0, amin=-2.0),
  "K2": dict(kind="K", dstop=5.5, vmax=6.0, amin=-2.0),
}
for k, v in json.loads(os.environ.get("XCFG", "{}")).items():
  CFG[k] = v


def fade_t(cf, T_in, lead, v_ego):
  if not cf or lead is None or not bool(lead.status):
    return T_in, 0.0
  vl = float(lead.vLead)
  if float(getattr(lead, "aLeadK", 0.0)) > cf.get("amax", 0.5):
    return T_in, 0.0
  w = float(np.clip((cf["vl_hi"] - vl) / (cf["vl_hi"] - cf["vl_lo"]), 0.0, 1.0))
  if w <= 0.0:
    return T_in, 0.0
  t_low = float(np.interp(v_ego, [cf["v0"], cf["v1"]], [min(cf["tmin"], T_in), T_in]))
  return T_in - w * (T_in - t_low), w


def install(P, c):
  flag = c.endswith("ON")
  P._short_action_t_active = (lambda f=flag: f)


class _O:
  def __init__(self, base, **over): self._b, self._o = base, over
  def __getattr__(self, k): return self._o[k] if k in self._o else getattr(self._b, k)


class Sim:
  def __init__(self, v, a, new=True):
    self.v, self.a, self.u, self.shift, self.stopping = v, a, a, 0.0, False
    self.P = Plant(v, a) if (new and PLANT == "new") else None
    self.pitch = 0.0

  def cmd(self, u_plan, should_stop, dt):
    if should_stop and self.v < V_STOPPING:
      self.stopping = True
    elif not should_stop:
      self.stopping = False
    if self.stopping:
      out = min(self.u, 0.0)
      if out > HOLD_A:
        out = max(HOLD_A, out - STOP_RATE * dt)
      self.u = out
    else:
      self.u = u_plan

  def step(self, dt, v_log):
    if self.P is not None:
      self.a = self.P.step(self.u, self.v, dt, None if os.environ.get("PLANT_NOGRADE") else self.pitch)
      v_new = max(self.v + self.a * dt, 0.0)
      if STOP_SNAP and self.v < 0.05 and self.a == 0.0:  # plant holds below 0.05 m/s: snap to 0, else a sim parked at 0.048 m/s drifts into the lead
        v_new = 0.0
    elif self.v < 0.05 and self.u <= 0.3:
      self.a, v_new = 0.0, 0.0
    else:
      self.a += (GAIN * self.u - self.a) * min(dt / TAU, 1.0)
      v_new = max(self.v + self.a * dt, 0.0)
    self.shift += (v_log - (self.v + v_new) / 2.0) * dt
    self.v = v_new


_LIM = {}
def _var(c):
  return c[2:] if c.startswith("OL") else c
def xform(c, rs, v_ego, t):
  v = _var(c)
  if v in ("BASE", "ACC"):
    return rs
  leads = []
  for i, ld in enumerate((rs.leadOne, rs.leadTwo)):
    key = (c, i)
    if not ld.status:
      _LIM.pop(key, None); leads.append(ld); continue
    if v == "VK":
      nv = float(ld.vLeadK)
    else:  # RLx: bound the published lead speed's rate of change to x m/s^2 (a bound, not a deletion)
      amax = float(v[2:]); vr = float(ld.vLead); d = float(ld.dRel)
      p = _LIM.get(key)
      if p is None or abs(d - p[2]) > 3.0 or t - p[0] > 0.3:
        nv = vr
      else:
        dt = t - p[0]; nv = float(np.clip(vr, p[1] - amax * dt, p[1] + amax * dt))
      _LIM[key] = (t, nv, d)
    leads.append(_O(ld, vLead=nv, vRel=nv - v_ego))
  return LP._BoundedRadarState(rs, leads[0], leads[1])

# RADAR_PKL=<radard_head.py output>: replace each logged radarState with the one this tree's parser + radard make from the
# same CAN (matched on mdMonoTime, so it reaches the planner at the same frame). Unset = the logged radarState.
_RADAR = pickle.load(open(os.environ["RADAR_PKL"], "rb")) if os.environ.get("RADAR_PKL") else None
RADAR_MISS = [0, 0]


def _radar(rs):
  if _RADAR is None:
    return rs
  from cereal import log as _log
  b = _RADAR.get(rs.mdMonoTime)
  RADAR_MISS[0] += 1; RADAR_MISS[1] += b is None
  if b is None:
    return rs
  with _log.RadarState.from_bytes(b) as r:
    return r.as_builder().as_reader()


def run_event(ev):
  route = (Path(os.environ["ROUTES"]) / Path(ev["route"]).name) if os.environ.get("ROUTES") else Path(ev["route"]).expanduser()
  files = segment_files(route)
  t_init = None
  if ev.get("tref", "abs") == "init":
    for m in LogReader(str(files[0])):
      if m.which() == "initData":
        t_init = m.logMonoTime / 1e9; break
  off = t_init if t_init is not None else 0.0
  T0, T1 = ev["T0"] + off, ev["T1"] + off
  segs = set(ev["segs"])
  files = [f for f in files if int(f.parent.name) in segs]
  _LIM.clear()
  state, valid, toggles, planners, rows, sims = {}, {}, default_toggles(), {}, [], {}
  t_prev = None
  for path in files:
    done = False
    for msg in LogReader(str(path), sort_by_time=True):
      T.LOG_CLOCK.now = msg.logMonoTime / 1e9
      w = msg.which()
      if w == "carParams" and not planners:
        acp = alpha_car_params(msg.carParams)
        for c in CANDS:
          p = LP.LongitudinalPlanner(acp); p._blotv3_active = (lambda: False)
          install(p, c)
          planners[c] = p
        continue
      if w == "radarState" or w in T.PLANNER_SERVICES:
        state[w] = _radar(msg.radarState) if w == "radarState" else getattr(msg, w); valid[w] = bool(msg.valid)
        if w == "starpilotPlan":
          toggles = parse_toggles(state["starpilotPlan"].starpilotToggles, toggles)
        continue
      if w != "modelV2" or not planners or not all(k in state for k in T.PLANNER_SERVICES) or "radarState" not in state:
        continue
      t = msg.logMonoTime / 1e9
      if t > T1:
        done = True; break
      if t < T0 - 8.0:
        continue  # planner warm-up: 8 s open loop before T0
      md = msg.modelV2; state["modelV2"] = md; valid["modelV2"] = bool(msg.valid)
      cs, rs = state["carState"], state["radarState"]
      v_log = float(cs.vEgo)
      dt = min(t - t_prev, 0.2) if t_prev is not None else 0.05
      t_prev = t
      if t >= T0:
        for c in CANDS:
          if c.startswith("OL"):
            continue
          if c not in sims:
            sims[c] = Sim(v_log, float(cs.aEgo), new=not c.endswith("_old"))  # '<cand>_old' = r3 tau/gain plant
          else:
            o = state["carControl"].orientationNED
            sims[c].pitch = float(o[1]) if len(o) == 3 else 0.0
            sims[c].step(dt, v_log)
      out = {}
      for c in CANDS:
        sm = _ReplaySM(state, valid)
        S = sims.get(c)
        rs = xform(c, state["radarState"], v_log, t)
        if _var(c) == "ACC":
          sm["selfdriveState"] = _O(state["selfdriveState"], experimentalMode=False)
        sm["radarState"] = LP._BoundedRadarState(rs, rs.leadOne, rs.leadTwo)
        if S:
          ve, sh = S.v, S.shift
          sl = lambda ld: ld if not ld.status else _O(ld, dRel=float(ld.dRel) + sh, vRel=float(ld.vLead) - ve)
          lo, l2 = sl(rs.leadOne), sl(rs.leadTwo)
          sm["carState"] = _O(cs, vEgo=ve, vEgoCluster=ve, aEgo=S.a, standstill=ve < 0.05)
          sm["modelV2"] = _O(md, leadsV3=[_O(ld, x=[float(x) + sh for x in ld.x]) for ld in md.leadsV3])
          sm["radarState"] = LP._BoundedRadarState(rs, lo, l2)
        sp = state["starpilotPlan"]
        if ev.get("mode") == "stock" or float(sp.tFollow) < 0.1:  # stock ACC: StarPilotFollowing zeroes tFollow/jerks while long is not active
          dec = (S.a if S else float(cs.aEgo)) < 0.0
          sm["starpilotPlan"] = _O(sp, tFollow=SP_TF, accelerationJerk=SP_AJ[dec], dangerJerk=SP_DJ, speedJerk=SP_SJ[dec])
        if S:
          cst = state["controlsState"]
          sm["controlsState"] = _O(cst, longControlState=(LP.LongCtrlState.stopping if S.stopping else LP.LongCtrlState.pid))
        P = planners[c]
        P.update(sm, toggles)
        u = float(P.output_a_target); ss = bool(P.output_should_stop)
        if S:
          S.cmd(u, ss, dt)
        out[c] = (u, ss, float(P.mpc.a_solution[0]), float(P.mpc.a_solution[3]), None, str(getattr(P.mpc, "source", "")) + "|" + str(P.mpc.mode),
                  (S.v, S.a, S.u, S.shift) if S else None)
      L = state["radarState"].leadOne
      rows.append(dict(t=t, v=v_log, a=float(cs.aEgo), cmd=float(state["carControl"].actuators.accel),
                       eng=bool(state["carControl"].longActive), exp=bool(state["selfdriveState"].experimentalMode), lcs=int(state["controlsState"].longControlState.raw),
                       L=(bool(L.status), bool(L.radar), float(L.dRel), float(L.vRel), float(L.vLead), float(L.aLeadK)),
                       out=out))
    if done:
      break
  return rows


def main():
  evs = json.load(open(sys.argv[1])); outp = sys.argv[2]
  res = {}
  if os.path.exists(outp):
    res = pickle.load(open(outp, "rb"))
  for ev in evs:
    if ev["id"] in res:
      continue
    try:
      res[ev["id"]] = dict(ev=ev, rows=run_event(ev))
    except Exception as e:
      print("ERR", ev["id"], repr(e), flush=True); continue
    pickle.dump(res, open(outp, "wb"))
    print(ev["id"], len(res[ev["id"]]["rows"]), "radar frames/missed", RADAR_MISS, flush=True)


if __name__ == "__main__":
  main()
