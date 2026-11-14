#!/usr/bin/env python3
"""What the HondaEps car learner has found on a car, read from a route's qlog (or rlog).

The shadow daemon (selfdrive/controls/honda_eps_learnerd.py) keeps its result in the HondaEpsLearnerResult param, and
every route copies its params into initData, so one segment's qlog from Konik/comma connect is enough: no rlogs needed.
The value is the one at the START of that route; take the newest route for the latest.

  python openpilot/tools/lateral/learner_result.py <qlog.zst> [...]
  python openpilot/tools/lateral/learner_result.py --json <file written by replay_car_learner.py --json>
"""
import argparse
import json
import sys

import zstandard as zstd

from openpilot.cereal import log

KEY = 'HondaEpsLearnerResult'
LOAD = ('k0', 'k1', 'c', 'friction', 'bias', 'kroll')


def result_in(path):
  """(the result or None, whether the learner was switched on) from the first initData in a log."""
  raw = open(path, 'rb').read()
  if path.endswith('.zst'):
    raw = zstd.ZstdDecompressor().stream_reader(raw).read()
  for e in log.Event.read_multiple_bytes(raw):
    if e.which() == 'initData':
      params = {entry.key: bytes(entry.value) for entry in e.initData.params.entries}
      value = params.get(KEY)
      return (json.loads(value) if value else None), params.get('HondaEpsLearner') == b'1'
  return None, False


def fmt_load(d):
  return ' '.join(f'{k} {d[k]:+.4g}' for k in LOAD)


def summarize(res):
  print(f"{res['calibration']} ({res['identity']}): {res['minutes']:.0f} min in {res['chunks']} chunks, learner v{res['version']}, shadow only")
  for name, p in res['parts'].items():
    print(f"  {name:9s} {p['state']:9s} {p['progress']:.2f}  {p['why']}")
  for name, p in res['parts'].items():
    v = p.get('value') or p.get('candidate')
    if v is None:
      continue
    kind = 'frozen' if 'value' in p else 'candidate'
    if name == 'load':
      print(f"\nload, shipped:   {fmt_load(res['shipped_load'])}")
      print(f"load, {kind + ':':10s} {fmt_load(v)} | kd {v['kd']:+.3f} lag {v['shift_s'] * 1000:.0f} ms knee {v['friction_width_v']} " +
            f"R^2 {v['r2']:.3f} (shipped {v['r2_shipped']:.3f})")
      print('  regime error, shipped / learned: ' + ', '.join(f'{k} {100 * s:+.0f}% / {100 * f:+.0f}% ({n} s)' for k, (n, s, f) in v['regimes'].items()))
      print(f"  open-loop wheel gain {v['open_loop_gain']}, coverage {v['coverage']}")
    elif name == 'yaw':
      print(f"yaw decode, {kind}: {v['scale']} deg/s per count + {v['right']} clockwise, zero error {v['zero_error_counts']} counts " +
            f"({v['pairs']} pairs, {v['drives']} drives); shipped {v['shipped']}")
    elif name == 'rack':
      print(f"rack map, {kind}: bp {v['ratio_bp']}\n                    v {v['ratio_v']}, slip factor {v['slip_factor']} (yaw decode {v['yaw_decode']})")
    elif name == 'cmd_delay':
      print(f"command delay, {kind}: car vs plan at {v['cmd_delay_s']} s: {v['shift_s']} s (negative = early), frames {v['frames']}")
    elif name == 'timing':
      print(f"model delay, {kind}: {dict(zip(v['bp'], v['v'], strict=True))} s by m/s, seconds {v['seconds']}")
  if res.get('near_centre_gain'):
    print('near-centre gain [inside +-3 deg, s, off-centre reference, s] by m/s: ' + json.dumps(res['near_centre_gain']))
  if res.get('torque_sensor'):
    print('torque sensor with nobody on the wheel: ' + json.dumps(res['torque_sensor']))


def main():
  ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
  ap.add_argument('paths', nargs='*', help='qlog or rlog files')
  ap.add_argument('--json', help='a result file instead of a log')
  a = ap.parse_args()
  if a.json:
    with open(a.json) as f:
      summarize(json.load(f))
  if not a.paths and not a.json:
    sys.exit('give a qlog/rlog or --json')
  for p in a.paths:
    res, enabled = result_in(p)
    print(f'{p}: HondaEpsLearner {"on" if enabled else "off"}')
    if res is None:
      print('  no HondaEpsLearnerResult in this log: the learner has not run on this car (or the build predates it)')
    else:
      summarize(res)


if __name__ == '__main__':
  main()
