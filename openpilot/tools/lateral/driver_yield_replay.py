#!/usr/bin/env python3
"""Replay the shadow driver yield (selfdrive/controls/lib/honda_eps_driver_yield.py) over a car's rlogs, next to what
today's press / cut / fade did on the same drives.

  python openpilot/tools/lateral/driver_yield_replay.py <route dir> [...]

Open loop: the logged driver torque already contains today's cuts, so the counts say what the detector sees, not how
the car would have driven with it. Where the log carries the controller's own shadow value (epsYieldAuthority), the
replay is checked against it.
"""
import argparse
import struct
import sys

import numpy as np

from openpilot.selfdrive.controls.lib import honda_eps_driver_yield as Y
from openpilot.selfdrive.controls.lib import honda_eps_firmware_ff as eps_ff
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import select_eps_firmware_calibration
from openpilot.tools.lateral.replay_car_learner import car_info, events, routes_in

DT = 0.01
REPRESS_FRAMES = 150   # a press this soon after the last one is chatter
HOLD_COUNTS = 1200.0   # a sustained hold against the controller: this much ...
HOLD_FRAMES = 50       # ... for this long
QUIET_COUNTS = 400.0   # hands off: no reading above this within +-1.5 s


def runs(mask):
  d = np.diff(np.r_[0, mask.astype(int), 0])
  return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1), strict=True))


def read_route(files, cal, sensor):
  """Per carState frame: what today's logic did, and the shadow yield replayed with the controller's own class."""
  st = {'lat': False, 'e4': 0.0, 'des': np.nan, 'off': 0.0, 'online': np.nan}
  shadow = Y.DriverYield(DT, sensor)
  rows = []
  for f in files:
    for which, e in events(f):
      if which == 'sendcan':
        for m in e.sendcan:
          if m.address == 0xE4:
            st['e4'] = struct.unpack('>h', m.dat[0:2])[0]
      elif which == 'carControl':
        st['lat'] = bool(e.carControl.latActive)
      elif which in ('vehicleParameters', 'liveParameters'):
        st['off'] = getattr(e, which).angleOffsetDeg
      elif which == 'controlsState':
        lcs = e.controlsState.lateralControlState
        st['des'] = lcs.pidState.steeringAngleDesiredDeg if lcs.which() == 'pidState' else np.nan
      elif which == 'starpilotLateralState':
        try:
          st['online'] = e.starpilotLateralState.epsYieldAuthority
        except Exception:  # a log from before the field
          pass
      elif which == 'carState':
        c = e.carState
        active = st['lat'] and np.isfinite(st['des'])
        output = 0.0
        if active:
          sent = -st['e4'] / cal.e4_per_output
          output = eps_ff.firmware_output(eps_ff.r5_from_output(sent, c.vEgo, cal), c.steeringRateDeg, cal, c.steeringAngleDeg - st['off'])
        driver = shadow.measure(c.steeringTorque, output, c.steeringRateDeg)
        error = st['des'] - c.steeringAngleDeg if active else 0.0
        if active:
          shadow.update(error, c.steeringRateDeg)
        else:
          shadow.reset()
        rows.append((float(active), c.steeringTorque, float(c.steeringPressed), driver, error, shadow.authority, st['online']))
  return np.array(rows, float).reshape(-1, 7)


def score(R):
  active, tq, pressed, driver, error = R[:, 0] > 0.5, R[:, 1], R[:, 2] > 0.5, R[:, 3], R[:, 4]
  authority, online = R[:, 5], R[:, 6]
  against = np.where(np.abs(error) > Y.ERROR_MIN, -driver * np.sign(error), 0.0)
  presses, yields = runs(pressed & active), runs((authority < 0.5) & active)
  out = {'minutes': active.sum() * DT / 60, 'presses': len(presses), 'yields': len(yields),
         'represses': sum(a - presses[i][1] < REPRESS_FRAMES for i, (a, _) in enumerate(presses[1:])),
         'reyields': sum(a - yields[i][1] < REPRESS_FRAMES for i, (a, _) in enumerate(yields[1:])),
         'cut': (pressed & active).sum(), 'yielded': ((authority < 0.5) & active).sum(), 'latency': [], 'missed': 0}
  for a, b in runs((against > HOLD_COUNTS) & active):
    if b - a >= HOLD_FRAMES:
      hit = np.flatnonzero(authority[a:b] < 0.5)
      if len(hit):
        out['latency'].append(hit[0] * DT)
      else:
        out['missed'] += 1
  quiet = (np.convolve((np.abs(tq) > QUIET_COUNTS).astype(float), np.ones(301), 'same') == 0) & active
  out['quiet_minutes'], out['quiet_yielding'] = quiet.sum() * DT / 60, int(((authority < 1.0) & quiet).sum())
  both = np.isfinite(online) & active & (online > 0)  # an unset field reads 0
  out['online_frames'] = int(both.sum())
  out['online_diff'] = float(np.abs(online[both] - authority[both]).max()) if both.any() else float('nan')
  return out


def show(name, s):
  m = max(s['minutes'], 1e-9)
  lat = np.array(s['latency'])
  print(f"{name}: {s['minutes']:.1f} engaged min")
  print(f"  today (press, cut, fade): {s['presses'] / m:.1f} presses/min, {s['represses'] / m:.2f}/min of them within 1.5 s of the last, " +
        f"cut {100 * s['cut'] * DT / 60 / m:.1f}% of the time")
  print(f"  shadow yield:             {s['yields'] / m:.1f} yields/min, {s['reyields'] / m:.2f}/min within 1.5 s of the last, " +
        f"authority under 50% {100 * s['yielded'] * DT / 60 / m:.1f}% of the time")
  if len(lat) or s['missed']:
    print(f"  holds against the controller (> {HOLD_COUNTS:.0f} counts for {HOLD_FRAMES * DT:.1f} s): {len(lat) + s['missed']}, authority under 50% after " +
          (f"{np.median(lat):.2f} s median, {np.percentile(lat, 90):.2f} s p90" if len(lat) else '-') + f", never in {s['missed']}")
  print(f"  hands off ({s['quiet_minutes']:.1f} min): authority below 1 on {s['quiet_yielding']} frames")
  if s['online_frames']:
    print(f"  the controller's own shadow value is in this log: {s['online_frames']} frames, largest difference from this replay {s['online_diff']:.3f}")


def main():
  ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
  ap.add_argument('paths', nargs='+', help='route directories (konik/comma downloads)')
  routes = routes_in(ap.parse_args().paths)
  if not routes:
    sys.exit('no rlogs found')
  total = None
  for name, files in routes.items():
    info = car_info(files)
    cal = select_eps_firmware_calibration(info['fingerprint'], info['eps_fw']) if info and info['eps_fw'] else None
    if cal is None:
      print(f'{name}: no EPS calibration for this car')
      continue
    sensor = Y.torque_sensor(cal.name)
    s = score(read_route(files, cal, sensor))
    show(f'{name} ({cal.name}, sensor offset {sensor.offset:g})', s)
    if total is None:
      total = s
    else:
      total = {k: (total[k] + v if k != 'online_diff' else np.nanmax([total[k], v])) for k, v in s.items()}
  if total is not None and len(routes) > 1:
    show('all routes', total)


if __name__ == '__main__':
  main()
