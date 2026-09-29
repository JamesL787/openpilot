#!/usr/bin/env python3
"""Fit and open-loop check of the Civic Bosch gas plant used by bosch_hill_sim.py.

  a = drive(u(t - lag(v))) + r0 + r2*v^2 - g*sin(theta),  u = gas/375, theta = CC pitch - 0.013 rad
  drive(u) = 0 (u <= 0), step + s1*min(u, 0.7) + s2*max(u - 0.7, 0) (u > 0)

Input: route directories (~/routes/<route>, the same the replay tools take; read whole unless --window) or
20 Hz npz files with fields t v gas ccp aE la gp bp acmd, as bosch_hill_sim.read_route returns. Route data stays
out of the repo: --cache-dir keeps one npz per route read.

  bosch_hill_plant_fit.py fit   ~/routes/00000280--d02d9c2f8e ~/routes/00000286--...   # least squares over
                                                  # tau1 x lag offset, per-route / per-band rms
  bosch_hill_plant_fit.py check A.npz B.npz       # the sim's own plant constants: aEgo rms and 30 s v drift

2026-09-29, routes 00000280 + 00000286: aEgo rms 0.132 / 0.118, 30 s v drift rms ~1.0 / 0.7 m/s.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from openpilot.tools.longitudinal import bosch_hill_sim as sim

g = 9.81
DT = 0.05
BIAS = 0.013
UK = 0.7


def load(p: Path, window: tuple[float, float] | None = None, cache_dir: Path | None = None) -> dict:
  cache = None
  if cache_dir is not None and p.is_dir():
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f'{p.name}_{window[0]:g}-{window[1]:g}.npz' if window else cache_dir / f'{p.name}.npz'
  d = dict(sim.load_route(p, window, cache))
  d['u'] = d['gas'] / 375.0
  d['th'] = np.radians(d['ccp']) - BIAS
  return d


def delayed(x, v, extra=0.0):
  n = np.round((np.interp(v, [3.0, 7.0], [0.68, 0.48]) + extra) / DT).astype(int)
  return x[np.maximum(np.arange(len(x)) - n, 0)]


def feats(d, extra=0.0, tau1=0.0):
  u = delayed(d['u'], d['v'], extra)
  if tau1 > 0:  # first-order smoothing after the delay
    y = np.empty_like(u)
    y[0] = u[0]
    al = DT / (tau1 + DT)
    for i in range(1, len(u)):
      y[i] = y[i - 1] + al * (u[i] - y[i - 1])
    u = y
  on = (u > 0.02).astype(float)
  return np.vstack([on, on * np.minimum(u, UK), on * np.maximum(u - UK, 0), np.ones_like(u), d['v'] ** 2]).T


def mask(d):
  # long active, no pedals, moving, not braking (the brake is not in the fit); the lag window must qualify too
  ok = (d['la'] > 0.5) & (d['gp'] < 0.5) & (d['bp'] < 0.5) & (d['v'] > 3)
  ok &= (d['u'] > 0.02) | (d['acmd'] > -0.4)
  for s in (10, 20):
    ok &= np.roll(ok, s)
  return ok


def fit(D, names):
  best = None
  for tau1 in (0.0, 0.1, 0.2, 0.3):
    for extra in (-0.1, 0.0, 0.1):
      X = np.vstack([feats(d, extra, tau1)[mask(d)] for d in D])
      y = np.concatenate([(d['aE'] + g * np.sin(d['th']))[mask(d)] for d in D])
      c = np.linalg.lstsq(X, y, rcond=None)[0]
      r = np.sqrt(np.mean((X @ c - y) ** 2))
      print(f'tau1 {tau1:.1f} extra {extra:+.1f}: rms {r:.3f}  step {c[0]:+.3f} s1 {c[1]:.3f} s2 {c[2]:.3f} r0 {c[3]:+.3f} r2 {c[4]:+.6f}')
      if best is None or r < best[0]:
        best = (r, tau1, extra, c)
  r, tau1, extra, c = best
  print(f'best: tau1 {tau1} extra {extra} rms {r:.3f} -> STEP, S1, S2, R0, R2 = {", ".join(f"{x:.6g}" for x in c)}')
  for name, d in zip(names, D, strict=True):
    m = mask(d)
    p = feats(d, extra, tau1) @ c - g * np.sin(d['th'])
    e = (p - d['aE'])[m]
    line = f'{name}: n {m.sum()} rms {np.sqrt(np.mean(e ** 2)):.3f} mean {e.mean():+.3f} '
    for lo, hi in ((3, 10), (10, 20), (20, 25), (25, 40)):
      b = m & (d['v'] >= lo) & (d['v'] < hi)
      if b.sum() > 100:
        line += f' {lo}-{hi}:{np.sqrt(np.mean((p - d["aE"])[b] ** 2)):.3f}'
    up = m & (d['th'] > 0.035)
    dn = m & (d['th'] < -0.035)
    line += f' | up>2deg {np.mean((p - d["aE"])[up]):+.3f} n{up.sum()} dn<-2deg {np.mean((p - d["aE"])[dn]):+.3f} n{dn.sum()}'
    print(line)


def check(D, names):
  for name, d in zip(names, D, strict=True):
    n = len(d['t'])
    u, v, th = d['u'], d['v'], d['th']
    pred = np.zeros(n)
    uf = u[0]
    for i in range(n):
      ud = u[max(i - int(round(sim.lag_s(v[i]) / DT)), 0)]
      uf += DT / (sim.TAU1 + DT) * (ud - uf)
      pred[i] = sim.drive(uf) + sim.R0 + sim.R2 * v[i] ** 2 - sim.grade_accel(th[i])
    m = mask(d)
    e = (pred - d['aE'])[m]
    drift = []
    W = int(30 / DT)
    for s0 in range(0, n - W, W):
      if m[s0:s0 + W].mean() < 0.98:
        continue
      vv = v[s0] + np.sum(pred[s0:s0 + W]) * DT
      drift.append(vv - v[s0 + W - 1])
    drift = np.array(drift)
    print(f'{name}: aEgo rms {np.sqrt(np.mean(e ** 2)):.3f} bias {e.mean():+.3f} (n {m.sum()} @20Hz, gas mode, long active, >3 m/s) | ' +
          f'30 s windows {len(drift)}: v drift rms {np.sqrt(np.mean(drift ** 2)):.2f} m/s, p90 |drift| {np.percentile(abs(drift), 90):.2f}')


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument('mode', choices=['fit', 'check'])
  ap.add_argument('routes', nargs='+', type=Path, help='route directories or 20 Hz npz files')
  ap.add_argument('--window', type=sim.parse_window, metavar='T0,T1', help='route seconds to read (default all)')
  ap.add_argument('--cache-dir', type=Path, help='npz cache of route reads (keep it outside the repo)')
  args = ap.parse_args()
  D = [load(p.expanduser(), args.window, args.cache_dir) for p in args.routes]
  (fit if args.mode == 'fit' else check)(D, [p.name for p in args.routes])
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
