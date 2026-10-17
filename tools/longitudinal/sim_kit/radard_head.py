#!/usr/bin/env python3
"""Re-run this tree's radar parser + radard on a route's logged CAN and save one radarState per modelV2 frame (replay only).
  PARAMS_ROOT=<writable dir> PYTHONPATH=.:opendbc_repo:tools python tools/longitudinal/sim_kit/radard_head.py ROUTE_DIR OUT.pkl [--last-seg N]
Runs from segment 0 (radard keeps track/arm history) to --last-seg. OUT.pkl = {mdMonoTime: radarState bytes}; the closed-loop
harnesses take it with RADAR_PKL=OUT.pkl and swap it in for the logged radarState with the same mdMonoTime, so the planner sees
it at the same frame the logged one arrived. Same loop as radard_from_can.py, minus its U11-scale variants."""
import argparse, pickle, sys
from pathlib import Path

ap = argparse.ArgumentParser(); ap.add_argument('route'); ap.add_argument('out'); ap.add_argument('--last-seg', type=int, default=None)
a = ap.parse_args(); sys.argv = [sys.argv[0]]

import tools.longitudinal.alpha_closed_loop_replay as A  # noqa: E402
from tools.lib.logreader import LogReader  # noqa: E402
from opendbc.car.can_definitions import CanData  # noqa: E402

RDM = A.RDM
segs = sorted((p for p in Path(a.route).iterdir() if p.is_dir() and p.name.isdigit() and (p / 'rlog.zst').exists()), key=lambda p: int(p.name))
segs = [p for p in segs if a.last_seg is None or int(p.name) <= a.last_seg]
ri = rd = None; rsm = A._RadardSM(); rr_latest = None; out = {}
for sp in segs:
  for msg in LogReader(str(sp / 'rlog.zst'), sort_by_time=True):
    w = msg.which()
    if w == 'carParams' and ri is None:
      cp = msg.carParams
      ri, _ = A.build_radar_interface(str(cp.carFingerprint))
      rd = RDM.RadarD(radar_ts=RDM.DT_MDL, delay=float(cp.radarDelay), honda_bosch_a_radar=True)
      continue
    if w == 'can' and ri is not None:
      b = [CanData(c.address, bytes(c.dat), c.src) for c in msg.can if c.address in A.BOSCH_A_IDS]
      if b:
        rr = ri.update([(msg.logMonoTime, b)])
        if rr is not None:
          rr_latest = rr
          rsm.recv_frame['liveTracks'] += 1; rsm.logMonoTime['liveTracks'] = msg.logMonoTime
          rsm.valid['liveTracks'] = not any(rr.errors.to_dict().values())
      continue
    if w in A.RADARD_SERVICES:
      rsm.msgs[w] = getattr(msg, w); rsm.valid[w] = bool(msg.valid); rsm.logMonoTime[w] = msg.logMonoTime
      if w == 'carState':
        rsm.recv_frame['carState'] += 1
      continue
    if w != 'modelV2' or ri is None or rr_latest is None or 'carState' not in rsm.msgs or 'starpilotPlan' not in rsm.msgs:
      continue
    rsm.msgs['modelV2'] = msg.modelV2; rsm.valid['modelV2'] = True; rsm.seen['modelV2'] = True; rsm.logMonoTime['modelV2'] = msg.logMonoTime
    rd.update(rsm, rr_latest)
    out[msg.logMonoTime] = rd.radar_state.to_bytes()
  print(sp.name, len(out), flush=True)
pickle.dump(out, open(a.out, 'wb'))
print('frames', len(out))
