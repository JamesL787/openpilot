"""Offline real-RadarInterface replay; unchanged production Track/KF at model cadence.

Recorded ego motion remains fixed: this is not a vehicle closed-loop simulation.
The replay only changes vRel; no matching, planner or controller is simulated.
"""
import ast
from collections import deque
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.simple_kalman import KF1D
from openpilot.tools.lib.logreader import LogReader, ReadMode
from opendbc.car.can_definitions import CanData
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR


HERE = Path(__file__).resolve().parent
REPO = Path('/Users/REDACTED_USER/nrdr/openpilot')


def load(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module
  spec.loader.exec_module(module)
  return module


def exact_track():
  # Execute the current, unmodified Track and gain definitions without importing
  # the unrelated messaging extension (the checkout has a Linux native binary).
  source = ast.parse((REPO / 'selfdrive/controls/radard.py').read_text())
  selected = []
  for item in source.body:
    if isinstance(item, ast.Assign):
      names = [n.id for target in item.targets for n in ast.walk(target) if isinstance(n, ast.Name)]
      if any(n.startswith('ADJACENT_STOP_') or n in ('_LEAD_ACCEL_TAU', 'SPEED', 'ACCEL') for n in names):
        selected.append(item)
    elif isinstance(item, ast.ClassDef) and item.name in ('KalmanParams', 'Track'):
      selected.append(item)
  scope = {'np': np, 'KF1D': KF1D, 'FirstOrderFilter': FirstOrderFilter, 'DT_MDL': 0.05}
  future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
  tree = ast.fix_missing_locations(ast.Module(body=[future] + selected, type_ignores=[]))
  exec(compile(tree, '<unchanged Track and KalmanParams>', 'exec'), scope)
  return scope['Track'], scope['KalmanParams']


def run_event(route, segment, tid, start, end):
  base_mod = load('ri_baseline', HERE / 'radar_interface_baseline.py')
  test_mod = load('ri_candidate', HERE / 'radar_interface.py')
  cp = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC_BOSCH)
  cp.radarUnavailable = False
  modes = {'baseline': base_mod.RadarInterface(cp), 'current': test_mod.RadarInterface(cp)}
  robust = test_mod.RadarInterface(cp)
  robust.bosch_a_rate_estimator = 'robust'
  modes['robust_gate'] = robust
  hysteresis = test_mod.RadarInterface(cp)
  hysteresis.bosch_a_rate_gate = 'hysteresis'
  modes['hysteresis_gate'] = hysteresis
  for tau in (0.3, 0.6, 0.9):
    ri = test_mod.RadarInterface(cp)
    ri.bosch_a_velocity_observer_params = {'tau': tau}
    modes[f'observer_tau_{tau}'] = ri
  Track, Gains = exact_track()
  gains = Gains(1.0 / base_mod.BOSCH_A_FREQ_HZ)
  tracks = dict.fromkeys(modes)
  for name in tracks:
    tracks[name] = {}
  latest = {name: [] for name in modes}
  fresh = {name: False for name in modes}
  ego_hist = deque([0.0], maxlen=round(float(cp.radarDelay) / 0.05) + 1)
  ego = 0.0
  car_frame = 0
  last_car_frame = -1
  base_time = None
  rows = []
  disabled_equal = True
  geometry_equal = True
  route_cp = None
  selected = (-1, -1)
  segments = list(range(max(0, int((start - 6) // 60)), segment + 1))
  paths = [f'11c8fa231c0499ed/{route}/{s}/r' for s in segments]
  lr = LogReader(paths, default_mode=ReadMode.RLOG, sort_by_time=True)
  for msg in lr:
    which = msg.which()
    t = msg.logMonoTime * 1e-9
    if which == 'carParams':
      route_cp = {'carFingerprint': str(msg.carParams.carFingerprint), 'radarDelay': float(msg.carParams.radarDelay)}
      ego_hist = deque(ego_hist, maxlen=round(float(msg.carParams.radarDelay) / 0.05) + 1)
    elif which == 'carState':
      ego = float(msg.carState.vEgo)
      car_frame += 1
    elif which == 'radarState':
      selected = (int(msg.radarState.leadOne.radarTrackId), int(msg.radarState.leadTwo.radarTrackId))
    elif which == 'can':
      if base_time is None:
        base_time = t - 60.0 * segments[0]
      if t - base_time > end + 2:
        break
      packet = [(msg.logMonoTime, [CanData(c.address, bytes(c.dat), c.src) for c in msg.can])]
      outputs = {}
      for name, ri in modes.items():
        rr = ri.update(packet)
        if rr is not None:
          latest[name] = [(p.trackId, p.dRel, p.yRel, p.vRel, p.measured) for p in rr.points]
          fresh[name] = True
          outputs[name] = latest[name]
      if 'baseline' in outputs:
        disabled_equal &= outputs['baseline'] == outputs.get('current')
        bg = [(p[0], p[1], p[2], p[4]) for p in outputs['baseline']]
        for name in modes:
          geometry_equal &= bg == [(p[0], p[1], p[2], p[4]) for p in outputs[name]]
    elif which == 'modelV2' and base_time is not None:
      # Same fixed-length ego history and new-payload measurement rule as RadarD.update.
      if car_frame != last_car_frame:
        ego_hist.append(ego)
        last_car_frame = car_frame
      for name in modes:
        live = {p[0]: p for p in latest[name]}
        for key in list(tracks[name]):
          if key not in live:
            del tracks[name][key]
        for key, point in live.items():
          _, d, y, v, measured = point
          vl = v + ego_hist[0]
          if key not in tracks[name]:
            tracks[name][key] = Track(key, vl, gains)
          measurement = bool(measured and fresh[name])
          tracks[name][key].update(d, y, v, vl, measurement, measurement)
        fresh[name] = False
        track = tracks[name].get(tid)
        if start - 3 <= t - base_time <= end and track is not None:
          state = modes[name]._tracks.get(tid)
          observer = getattr(state, 'velocity_observer', None)
          rows.append({'t': t - base_time, 'mode': name, 'id': tid,
                       'dRel': track.dRel, 'yRel': track.yRel, 'vRel': track.vRel,
                       'vLead': track.vLead, 'vLeadK': track.vLeadK, 'aLeadK': track.aLeadK,
                       'measured': track.measured, 'vEgo': ego, 'selected_logged': selected,
                       'observer_rejected': 0 if observer is None else observer.rejected})
  summary = {'route': route, 'segment': segment, 'preroll_segments': segments, 'track': tid, 'window': [start, end],
             'clock': 'first CAN in segment + segment*60; prior event label convention',
             'route_cp': route_cp, 'disabled_identical': bool(disabled_equal),
             'geometry_and_measured_identical': bool(geometry_equal), 'modes': {}}
  for name in modes:
    r = [r for r in rows if r['mode'] == name and start <= r['t'] <= end]
    if not r:
      summary['modes'][name] = {'count': 0}
      continue
    pre = [r for r in rows if r['mode'] == name and r['t'] < start]
    v = np.array([r['vRel'] for r in r])
    a = np.array([r['aLeadK'] for r in r])
    summary['modes'][name] = {'count': len(r), 'min_vRel': float(v.min()), 'min_aLeadK': float(a.min()),
                            'max_aLeadK': float(a.max()),
                            'max_v_step': float(np.max(np.abs(np.diff(v)))) if len(v) > 1 else 0,
                            'first_a_below_minus2': next((x['t'] for x in r if x['aLeadK'] < -2), None),
                            'pre_a_sd': float(np.std([x['aLeadK'] for x in pre])) if pre else None,
                            'range_rejects': max(x['observer_rejected'] for x in r)}
  return summary, rows


def main():
  events = [
    ('000001fb--5f48412a46', 35, 38, 2098.8, 2106.5),
    ('000001fe--a99da71ccb', 35, 10, 2131.5, 2136.0),
    ('00000141--d3a05962de', 5, 42, 322.4, 328.4),
  ]
  all_rows, summaries = [], []
  for event in events:
    began = time.monotonic()
    print('START', event, flush=True)
    summary, rows = run_event(*event)
    summaries.append(summary)
    all_rows.extend(rows)
    print(json.dumps(summary), 'seconds', round(time.monotonic() - began, 1), flush=True)
    (HERE / 'replay_results.json').write_text(json.dumps({'summary': summaries, 'rows': all_rows}, indent=2))


if __name__ == '__main__':
  main()
