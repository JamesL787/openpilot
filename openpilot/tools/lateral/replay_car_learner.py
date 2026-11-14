#!/usr/bin/env python3
"""Replay the HondaEps car learner (selfdrive/controls/lib/honda_eps_car_learner.py) over an owner's drives, in time
order, through the shadow daemon's own chunk builder, and compare what it freezes with the shipped calibration.

  python openpilot/tools/lateral/replay_car_learner.py <route dir> [<route dir> ...]

A route dir is a konik/comma download (<route>--<seg>/rlog.zst, or flat rlog_<seg>.zst); several routes in one folder
are split by route name, never interleaved. Routes are replayed in the order given. Per part it prints when it froze
(minutes of log) or why it did not, the frozen or candidate values next to the shipped ones, and a frozen load scored
by regime on the drives AFTER it froze.
The logs must match the EPS image the calibration models: a route on an earlier PTM build is fitted through the
CURRENT law. The calibration comes from the fingerprint and EPS version, never from the log's HondaFlags.
--cache DIR keeps each route's chunks, so later runs skip the rlog decode. --json writes the learner's result.
"""
import argparse
import glob
import json
import os
import pickle
import re
import sys
from multiprocessing import Pool

import numpy as np
import zstandard as zstd

from opendbc.car.honda.steer_ratio import HONDA_VGR_INVERSE_BY_PROFILE, HONDA_VGR_PROFILE_BY_FW, normalize_honda_eps_fw
from opendbc.car.honda.yaw_rate import YAW_RATE_CALIBRATION
from openpilot.cereal import log
from openpilot.selfdrive.controls.honda_eps_learnerd import FrameBuilder
from openpilot.selfdrive.controls.lib import honda_eps_car_learner as L
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import REQUIRED_PTM_RWD, select_eps_firmware_calibration

STREAMS = ('carState', 'can', 'sendcan', 'carControl', 'vehicleParameters', 'liveParameters', 'starpilotLateralState', 'modelV2',
           'gpsLocation', 'gpsLocationExternal')


def segment_number(p):
  m = re.search(r'rlog_(\d+)\.zst$', p) or re.search(r'--(\d+)/rlog', p)
  return int(m.group(1)) if m else 0


def routes_in(paths):
  out = {}
  for d in paths:
    for f in glob.glob(os.path.join(d, '*--*--*', 'rlog*')) + glob.glob(os.path.join(d, 'rlog*')):
      m = re.search(r'([0-9a-f]{8}--[0-9a-f]{10})--\d+/', f)
      out.setdefault(m.group(1) if m else os.path.basename(os.path.normpath(d)), []).append(f)
  return {k: sorted(v, key=segment_number) for k, v in out.items()}


def events(path):
  raw = zstd.ZstdDecompressor().stream_reader(open(path, 'rb').read()).read()
  try:
    for e in log.Event.read_multiple_bytes(raw):
      try:
        yield e.which(), e
      except Exception:  # a union member this schema does not know
        continue
  except Exception as ex:  # a truncated last segment
    print(f'  (partial read {path}: {ex})', file=sys.stderr)


def car_info(files):
  for f in files[:2]:
    for which, e in events(f):
      if which == 'carParams':
        cp = e.carParams
        eps = [normalize_honda_eps_fw(fw.fwVersion) for fw in cp.carFw if str(fw.ecu) == 'eps']
        return {'fingerprint': str(cp.carFingerprint), 'wheelbase': float(cp.wheelbase), 'eps_fw': eps[0] if eps else None}
  return None


def read_route(job):
  name, files, cache = job
  path = os.path.join(cache, name + '.pkl') if cache else None
  if path and os.path.exists(path):
    with open(path, 'rb') as f:
      return pickle.load(f)
  info = car_info(files)
  chunks = []
  if info is not None:
    builder = FrameBuilder(YAW_RATE_CALIBRATION.get(info['fingerprint']), raw_yaw=True)
    for f in files:
      for which, e in events(f):
        if which in STREAMS:
          c = builder.handle(which, getattr(e, which), e.logMonoTime * 1e-9)
          if c is not None:
            chunks.append(c)
    c = builder.flush()
    if c is not None:
      chunks.append(c)
  out = (name, chunks, info)
  if path:
    with open(path, 'wb') as f:
      pickle.dump(out, f)
  return out


def fmt_load(d):
  return ' '.join(f'{k} {d[k]:+.4g}' for k in ('k0', 'k1', 'c', 'friction', 'bias', 'kroll'))


def print_regimes(table, label):
  print(f'  regime error, model minus firmware along the output as a share of |firmware| ({label}): shipped / learned')
  for reg in L.REGIMES:
    cells = [f'{sp} {100 * table[k][1]:+.0f}% / {100 * table[k][2]:+.0f}% ({table[k][0]:.0f} s)' for sp in L.REGIME_SPEEDS
             if (k := f'{reg} {sp}') in table]
    if cells:
      print(f'    {reg:8s} ' + '   '.join(cells))


def report(learner, frozen_at, scorer, cal):
  res = learner.result()
  print(f"\nreplayed {res['minutes']:.0f} min of log in {res['chunks']} chunks")
  for part, p in res['parts'].items():
    when = frozen_at.get(part)
    print(f"  {part:9s} {p['state']:9s} " + (f'at {when[0]:.0f} min ({when[1]}): ' if when else f"{p['progress']:.2f}: ") + p['why'])

  p = res['parts']['load']
  v = p.get('value') or p.get('candidate')
  print('\ncolumn load (firmware output counts; target rebuilt from the sent 0xE4)')
  print('  shipped  ', fmt_load(res['shipped_load']))
  if v is not None:
    print(f"  {'frozen' if 'value' in p else 'candidate':9s}", fmt_load(v), f"| kd {v['kd']:+.3f} j {v['j']:+.3f} lag {v['shift_s'] * 1000:.0f} ms " +
          f"knee {v['friction_width_v']} | R^2 {v['r2']:.3f} (shipped {v['r2_shipped']:.3f}) | prior-held {v['prior_held']}")
    cov = v['coverage']
    print(f"  coverage: {cov['accepted_s'] / 60:.1f} min accepted, {cov['turn_s']:.0f} s past 20 deg, {cov['rate_s']:.0f} s past 20 deg/s, " +
          f"{cov['speed_bands']} speed bands, hands-off windows {cov['windows']} at {L.OL_BANDS}")
    print_regimes({k: tuple(x) for k, x in v['regimes'].items()}, 'each half scored on the other')
    ld = learner.load
    s, ki = int(round(v['shift_s'] / L.DT)), L.LOAD_KNEES.index(tuple(v['friction_width_v']))
    gains = v['open_loop_gain'] or ld.open_loop(ld.solve(s=s, ki=ki), s, ki)
    ship = ld.open_loop(ld.shipped(0.0, s), s, 0)
    print('  open-loop 0.6-2.5 Hz wheel gain, simulated / measured: ' +
          ', '.join(f'{lo:.0f}-{hi:.0f} m/s {g:.2f} (shipped {sg:.2f})' for (lo, hi), g, sg in zip(L.OL_BANDS, gains, ship, strict=True)))
    if scorer is not None and scorer.n.sum() > 3000:
      coef = np.array(v['coef'])
      print(f"  on the {scorer.n[:, 0].sum() * L.DT / 60:.0f} min after the freeze: R^2 {scorer.r2(coef, (0, 1), s, ki):.3f} " +
            f"(shipped {scorer.r2(scorer.shipped(coef[L.I_KD], s), (0, 1), s, ki):.3f})")
      print_regimes(scorer.regimes(s, ki, given=coef), 'the frozen load on the drives after the freeze')

  p = res['parts']['yaw']
  v = p.get('value') or p.get('candidate')
  if v is not None:
    print(f"\nyaw decode ({'frozen' if 'value' in p else 'candidate'}): {v['scale']:.4f} deg/s per count + {v['right']:.3f} clockwise, zero error " +
          f"{v['zero_error_counts']:+.2f} counts (heading rms {v['heading_rms_deg']} deg, {v['pairs']} pairs on {v['drives']} drives); " +
          f"shipped {v['shipped'][0]} + {v['shipped'][1]}")
  p = res['parts']['rack']
  v = p.get('value') or p.get('candidate')
  if v is not None:
    print(f"\nrack map ({'frozen' if 'value' in p else 'candidate'}, {v['seconds']} s of turning, yaw decode {v['yaw_decode']}): " +
          f"slip factor {v['slip_factor']}")
    print('  |angle|  ' + ' '.join(f'{x:6.1f}' for x in v['ratio_bp']))
    print('  ratio    ' + ' '.join(f'{x:6.2f}' for x in v['ratio_v']))
    if cal.rack is not None:
      print('  shipped  ' + ' '.join(f'{np.interp(x, cal.rack.ratio_bp, cal.rack.ratio_v):6.2f}' for x in v['ratio_bp']) +
            f'   slip factor {cal.rack.slip_factor}')
    if 'value' not in p and learner.yaw.frozen is None and learner.yaw.candidate() is not None:
      c = learner.rack.candidate((learner.yaw.candidate()['scale'], learner.yaw.candidate()['right']))
      if c is not None:
        print('  on the candidate yaw decode: ' + ' '.join(f'{x:6.2f}' for x in c['ratio_v']) + f"   slip factor {c['slip_factor']}")
  if res['near_centre_gain']:
    def centre(gains):
      return ', '.join(f"{k} m/s {g:.2f} ({n} s; {'-' if ref is None else f'{ref:.2f}'} off centre, {nr} s)" for k, (g, n, ref, nr) in gains.items())
    print(f'\nnear-centre gain (car curvature / shipped rack map inside +-{L.CENTRE_ANGLES[0][1]:g} deg, within {L.CENTRE_WINDOW_S:g} s windows; ' +
          f'reference at {L.CENTRE_ANGLES[1][0]:g}-{L.CENTRE_ANGLES[1][1]:g} deg; reported only):\n  ' + centre(res['near_centre_gain']))
    if learner.yaw.frozen is None and learner.yaw.candidate() is not None:
      c = learner.yaw.candidate()
      print('  on the candidate yaw decode: ' + centre(learner.centre.gains((c['scale'], c['right']))))
  v = res['parts']['cmd_delay'].get('value') or res['parts']['cmd_delay'].get('candidate')
  if v is not None:
    print(f"\ncommand delay (measured only): the car vs the model's plan at {v['cmd_delay_s']} s, negative = early: " +
          ', '.join(f"{k} {x:+.2f} s ({n} frames)" for (k, x), n in zip(v['shift_s'].items(), v['frames'], strict=True)) +
          (f"; restarted {v['restarts']}x on a changed delay" if v['restarts'] else ''))
  v = res['parts']['timing'].get('value') or res['parts']['timing'].get('candidate')
  print('model delay, town bands (measured only): ' + ', '.join(f'{bp:g} m/s {x} s ({n} s)' for bp, x, n in zip(v['bp'], v['v'], v['seconds'], strict=True)) +
        f'; shipped {cal.lat_delay_schedule}')
  if res['torque_sensor']:
    t = res['torque_sensor']
    print(f"\ntorque sensor with nobody on the wheel ({t['minutes']} min): {t['offset']:+.0f} counts offset, {t['firmware_output']:+.3f} per count of " +
          f"firmware output, {t['thdd']:+.3f} per deg/s^2; rms {t['rms_counts']} -> {t['rms_after']} counts once those are taken out (R^2 {t['r2']})")
  return res


def main():
  ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
  ap.add_argument('paths', nargs='+', help='route directories (konik/comma downloads)')
  ap.add_argument('--cache', help='directory for per-route chunk caches')
  ap.add_argument('--json', help="write the learner's result (the HondaEpsLearnerResult value) here")
  ap.add_argument('--no-freeze', action='store_true', help='never freeze: what the fits give on all of the drives')
  a = ap.parse_args()
  if a.cache:
    os.makedirs(a.cache, exist_ok=True)
  jobs = [(k, v, a.cache) for k, v in routes_in(a.paths).items()]
  if not jobs:
    sys.exit('no rlogs found')
  with Pool(min(8, len(jobs))) as pool:
    routes = pool.map(read_route, jobs)

  learner, frozen_at, scorer, cal = None, {}, None, None
  for name, chunks, info in routes:
    if not chunks or info is None or info['eps_fw'] is None:
      print(f'{name}: nothing usable')
      continue
    cal = select_eps_firmware_calibration(info['fingerprint'], info['eps_fw'])
    if cal is None:
      sys.exit(f"{name}: no EPS calibration for {info['fingerprint']} {info['eps_fw']}")
    if learner is None:
      vgr = HONDA_VGR_INVERSE_BY_PROFILE.get(HONDA_VGR_PROFILE_BY_FW.get(info['eps_fw'], ''))
      learner = L.HondaEpsCarLearner(cal, info['wheelbase'], vgr, YAW_RATE_CALIBRATION.get(info['fingerprint']),
                                     identity=f"{info['eps_fw']}|{REQUIRED_PTM_RWD.get(cal.name, '')}")
      learner.freezing = not a.no_freeze
      print(f"{info['fingerprint']} {cal.name} ({learner.identity})")
    for c in chunks:
      learner.add_chunk(c)
      if scorer is not None:
        scorer.add_chunk(c, learner.last_target, learner.chunks)
      for part, (state, _, _) in learner.status().items():
        if state == 'frozen' and part not in frozen_at:
          frozen_at[part] = (learner.seconds / 60, name)
          if part == 'load':
            scorer = L.ColumnLoadLearner(cal, learner.load.fade_frames * L.DT - L.LOAD_FADE_MARGIN_S)
    yaw = learner.yaw.candidate() if learner.yaw is not None else None
    print(f"  {name}: {len(chunks)} chunks -> " + ', '.join(f'{k} {s} {p:.2f}' for k, (s, p, _) in learner.status().items()) +
          (f"; yaw {yaw['scale']:.4f} + {yaw['right']:.3f} ({yaw['pairs']} pairs)" if yaw else ''), flush=True)
  if learner is None:
    sys.exit('no usable route')
  learner.check()
  res = report(learner, frozen_at, scorer, cal)
  if a.json:
    with open(a.json, 'w') as f:
      json.dump(res, f, indent=1)


if __name__ == '__main__':
  main()
