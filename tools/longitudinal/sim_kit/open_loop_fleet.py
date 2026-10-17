#!/usr/bin/env python3
"""Open-loop fleet A/B of planner variants on logged inputs (scratch). rfleet.py ROUTE_DIR OUT.npz
Variants are planner module files given in env VARIANTS=name=path,... ; each runs open loop on the same logged state."""
import os, sys, importlib.util
import numpy as np
from pathlib import Path
os.environ.setdefault("DEBUG", "0")
import openpilot.selfdrive.controls.lib  # noqa
for _n in ("longitudinal_lead", "blotv3", "accel_boost"):
  _bs = importlib.util.spec_from_file_location(f"openpilot.selfdrive.controls.lib.{_n}", os.path.join(os.path.dirname(os.path.abspath(__file__)), "car", f"{_n}.py"))
  _bm = importlib.util.module_from_spec(_bs); sys.modules[_bs.name] = _bm; _bs.loader.exec_module(_bm)
VARS = [v.split("=") for v in os.environ["VARIANTS"].split(",")]
MODS = {}
for name, path in VARS:
  sp = importlib.util.spec_from_file_location(f"lpvar_{name}", path); m = importlib.util.module_from_spec(sp)
  sys.modules[sp.name] = m; sp.loader.exec_module(m); MODS[name] = m
from openpilot.tools.lib.logreader import LogReader
from openpilot.tools.longitudinal import alpha_closed_loop_replay as T
from openpilot.tools.longitudinal.alpha_open_loop_replay import _ReplaySM, alpha_car_params, default_toggles, parse_toggles, segment_files
for m in MODS.values():
  m.time = T.LOG_CLOCK

def main():
  route = Path(sys.argv[1]); out = sys.argv[2]
  files = segment_files(route)
  state, valid, toggles, P = {}, {}, default_toggles(), {}
  rows = []; t0 = None
  for path in files:
    try:
      for msg in LogReader(str(path), sort_by_time=True):
        if t0 is None: t0 = msg.logMonoTime / 1e9
        T.LOG_CLOCK.now = msg.logMonoTime / 1e9
        w = msg.which()
        if w == "carParams" and not P:
          acp = alpha_car_params(msg.carParams)
          for n, m in MODS.items():
            P[n] = m.LongitudinalPlanner(acp)
            if hasattr(P[n], "_blotv3_active"): P[n]._blotv3_active = (lambda: False)
            P[n]._short_action_t_active = (lambda: False)
          continue
        if w == "radarState" or w in T.PLANNER_SERVICES:
          state[w] = getattr(msg, w); valid[w] = bool(msg.valid)
          if w == "starpilotPlan":
            toggles = parse_toggles(state["starpilotPlan"].starpilotToggles, toggles)
          continue
        if w != "modelV2" or not P or not all(k in state for k in T.PLANNER_SERVICES) or "radarState" not in state:
          continue
        state["modelV2"] = msg.modelV2; valid["modelV2"] = bool(msg.valid)
        outs = []
        for n in MODS:
          P[n].update(_ReplaySM(state, valid), toggles); outs.append(float(P[n].output_a_target))
        cs = state["carState"]; L = state["radarState"].leadOne; cc = state["carControl"]
        if not cc.longActive:
          continue
        rows.append([msg.logMonoTime / 1e9 - t0, float(state["selfdriveState"].experimentalMode), float(cs.vEgo), float(cs.aEgo),
                     float(cc.actuators.accel), float(L.status), float(L.dRel), float(L.vRel), float(L.aLeadK), float(L.radar),
                     float(L.modelProb)] + outs)
    except Exception as e:
      print("SEGERR", path, repr(e)[:200], flush=True)
  np.savez_compressed(out, rows=np.array(rows, dtype=np.float32), names=np.array([n for n, _ in VARS]))
  print("DONE", route.name, len(rows), flush=True)

if __name__ == "__main__":
  main()
