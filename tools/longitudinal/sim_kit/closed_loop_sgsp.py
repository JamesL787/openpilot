#!/usr/bin/env python3
"""SGSP (starpilot/SecretGoodStarPilot) longitudinal planner, closed loop on our logs (scratch, replay only).
  closed_loop_sgsp.py EVENTS.json OUT.pkl
Same events and output rows as closed_loop.py, so score.py reads both. Inputs: the logged radarState (our radar
parser, as the car ran it) and modelV2. Each candidate drives the same plant (plant/plant.py) and Honda stopping
model as closed_loop.py. 'OLBASE' is SGSP fed the logged ego state (open-loop shadow).

SGSP runs out of the box: every update() kwarg left at its default (no profile, curve, SLC, conditional, force-stop or
traffic hosts), personality and Experimental Mode from the logged selfdriveState. Shims onto our schema: lead.present =
status, sm['vehicleParameters'].angleOffsetDeg from liveParameters, sm.logMonoTime/valid/alive from the log.
Needs sgsp/ (closure.py extract), sgsp/opendbc_extra and the x86 SGSP MPC build; one process per planner family.
"""
import json, os, pickle, sys, types
from pathlib import Path
import numpy as np
os.environ.setdefault("DEBUG", "0")
_KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _KIT)
import sgsp_loader
sgsp_loader.install()

sys.path.insert(0, os.path.join(_KIT, "plant"))
from plant import Plant
from openpilot.tools.lib.logreader import LogReader
import openpilot.selfdrive.controls.lib.longitudinal_planner as LP
assert "/sgsp/" in LP.__file__, LP.__file__
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
print("CHECK planner", LP.__file__, flush=True)

CANDS = os.environ.get("CANDS", "BASE,OLBASE").split(",")
STOP_SNAP = os.environ.get("STOP_SNAP", "1") == "1"
V_STOPPING = 0.5; STOP_RATE = 0.1; HOLD_A = -0.6
SERVICES = ("carState", "selfdriveState", "carControl", "liveParameters", "controlsState", "radarState", "deviceState")
NEED = ("carState", "selfdriveState", "carControl", "liveParameters", "controlsState", "radarState")


class _Clock:
  now_ns = 0


def segment_files(route_dir):
  segs = []
  for d in Path(route_dir).iterdir():
    if d.is_dir() and d.name.isdigit():
      for name in ("rlog.zst", "rlog.bz2", "rlog"):
        if (d / name).exists():
          segs.append((int(d.name), d / name)); break
  return [p for _, p in sorted(segs)]


class _O:
  def __init__(self, base, **over): self._b, self._o = base, over
  def __getattr__(self, k): return self._o[k] if k in self._o else getattr(self._b, k)


def _lead(ld, **over):
  return _O(ld, present=bool(ld.status), **over)


class _SM:
  def __init__(self, msgs, valid, mono):
    self._m, self.valid, self.logMonoTime = dict(msgs), dict(valid), dict(mono)
    self.alive = {k: True for k in self._m}; self.updated = {k: True for k in self._m}
    self.recv_frame = {k: 1 for k in self._m}; self.freq_ok = self.alive
  def __getitem__(self, k): return self._m[k]
  def __setitem__(self, k, v): self._m[k] = v
  def __contains__(self, k): return k in self._m
  def all_checks(self, service_list=None): return all(self.valid.get(s, True) for s in (service_list or self._m))
  def all_alive(self, service_list=None): return True
  def all_valid(self, service_list=None): return self.all_checks(service_list)


class Sim:
  def __init__(self, v, a):
    self.v, self.a, self.u, self.shift, self.stopping, self.pitch = v, a, a, 0.0, False, 0.0
    self.P = Plant(v, a)

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
    self.a = self.P.step(self.u, self.v, dt, None if os.environ.get("PLANT_NOGRADE") else self.pitch)
    v_new = max(self.v + self.a * dt, 0.0)
    if STOP_SNAP and self.v < 0.05 and self.a == 0.0:  # plant holds below 0.05 m/s: snap to 0, else a sim parked at 0.048 m/s drifts into the lead
      v_new = 0.0
    self.shift += (v_log - (self.v + v_new) / 2.0) * dt
    self.v = v_new


def car_params(cp):
  b = cp.as_builder(); b.openpilotLongitudinalControl = True; b.pcmCruise = False
  return b.as_reader()


def run_event(ev):
  files = segment_files(Path(ev["route"]).expanduser())
  T0, T1 = ev["T0"], ev["T1"]
  files = [f for f in files if int(f.parent.name) in set(ev["segs"])]
  state, valid, mono, planners, rows, sims = {}, {}, {}, {}, [], {}
  t_prev = None; done = False
  for path in files:
    for msg in LogReader(str(path), sort_by_time=True):
      _Clock.now_ns = msg.logMonoTime
      w = msg.which()
      if w == "carParams" and not planners:
        cp = car_params(msg.carParams)
        for c in CANDS:
          planners[c] = LP.LongitudinalPlanner(cp, 0.0, 0.0, clock_ns=lambda: _Clock.now_ns)
        continue
      if w in SERVICES:
        state[w] = getattr(msg, w); valid[w] = bool(msg.valid); mono[w] = msg.logMonoTime
        continue
      if w != "modelV2" or not planners or not all(k in state for k in NEED):
        continue
      t = msg.logMonoTime / 1e9
      if t > T1:
        done = True; break
      if t < T0 - 8.0:
        continue  # planner warm-up: 8 s open loop before T0
      md = msg.modelV2; valid["modelV2"] = bool(msg.valid); mono["modelV2"] = msg.logMonoTime
      cs, rs = state["carState"], state["radarState"]
      v_log = float(cs.vEgo)
      dt = min(t - t_prev, 0.2) if t_prev is not None else 0.05
      t_prev = t
      if t >= T0:
        for c in CANDS:
          if c.startswith("OL"):
            continue
          if c not in sims:
            sims[c] = Sim(v_log, float(cs.aEgo))
          else:
            o = state["carControl"].orientationNED
            sims[c].pitch = float(o[1]) if len(o) == 3 else 0.0
            sims[c].step(dt, v_log)
      vp = types.SimpleNamespace(angleOffsetDeg=float(state["liveParameters"].angleOffsetDeg))
      out = {}
      for c in CANDS:
        S = sims.get(c)
        msgs = dict(state); msgs["modelV2"] = md; msgs["vehicleParameters"] = vp
        if S:
          ve, sh = S.v, S.shift
          sl = lambda ld: _lead(ld) if not ld.status else _lead(ld, dRel=float(ld.dRel) + sh, vRel=float(ld.vLead) - ve)
          msgs["radarState"] = _O(rs, leadOne=sl(rs.leadOne), leadTwo=sl(rs.leadTwo))
          msgs["carState"] = _O(cs, vEgo=ve, vEgoCluster=ve, aEgo=S.a, standstill=ve < 0.05)
          msgs["modelV2"] = _O(md, leadsV3=[_O(ld, x=[float(x) + sh for x in ld.x]) for ld in md.leadsV3])
          msgs["controlsState"] = _O(state["controlsState"],
                                     longControlState=(LongCtrlState.stopping if S.stopping else LongCtrlState.pid))
        else:
          msgs["radarState"] = _O(rs, leadOne=_lead(rs.leadOne), leadTwo=_lead(rs.leadTwo))
        sm = _SM(msgs, valid, mono)
        P = planners[c]
        P.update(sm, now_ns=_Clock.now_ns)
        u = float(P.output_a_target); ss = bool(P.output_should_stop)
        if S:
          S.cmd(u, ss, dt)
        out[c] = (u, ss, float(P.mpc.a_solution[0]), float(P.mpc.a_solution[3]), None,
                  str(getattr(P.mpc, "source", "")) + "|" + str(getattr(P.mpc, "mode", "")),
                  (S.v, S.a, S.u, S.shift) if S else None)
      L = rs.leadOne
      rows.append(dict(t=t, v=v_log, a=float(cs.aEgo), cmd=float(state["carControl"].actuators.accel),
                       eng=bool(state["carControl"].longActive), exp=bool(state["selfdriveState"].experimentalMode),
                       lcs=int(state["controlsState"].longControlState.raw),
                       L=(bool(L.status), bool(L.radar), float(L.dRel), float(L.vRel), float(L.vLead), float(L.aLeadK)),
                       out=out))
    if done:
      break
  return rows


def main():
  evs = json.load(open(sys.argv[1])); outp = sys.argv[2]
  only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
  res = pickle.load(open(outp, "rb")) if os.path.exists(outp) else {}
  for ev in evs:
    if ev["id"] in res or (only and ev["id"] not in only):
      continue
    res[ev["id"]] = dict(ev=ev, rows=run_event(ev))
    pickle.dump(res, open(outp, "wb"))
    print(ev["id"], len(res[ev["id"]]["rows"]), flush=True)


if __name__ == "__main__":
  main()
