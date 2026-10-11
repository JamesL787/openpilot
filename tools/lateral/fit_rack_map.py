#!/usr/bin/env python3
"""Fit a car's rack map (honda_eps_rack_map.RackMapTable) against its VSA yaw sensor, the Clarity method.

Every moving frame, wheel angle shifted by the wheel->yaw lag, gives y = lin_rad / (L * k_eff) = R(theta), where lin
is the firmware VGR (A table) linear angle of the physical wheel angle and k_eff = k (1 - sf v^2) - g sf roll with
k = yaw / v from 0x94. sf comes from the speed dependence of y inside each wheel-angle band (it is the value that
makes R the same at every speed); R per band is the mean of the left and right medians, so an angle offset cancels.
Then held-out by route: how well the fitted map, and the car's current road curve, predict the measured curvature.

  fit_rack_map.py --car HONDA_CIVIC_BOSCH --vgr civic_tba_c020 --bus 1 --scale 0.244 '<route>/rlog*' ...
"""
import argparse
import bz2
import ast
import os
import glob
import re

import numpy as np
import zstandard as zstd

from cereal import log
from opendbc.car.honda.steer_ratio import HONDA_VGR_INVERSE_BY_PROFILE
from opendbc.car.honda.values import CAR
from opendbc.car.honda.yaw_rate import RIGHT_LOSS_BP

G = 9.81
LATCONTROL_PID = os.path.join(os.path.dirname(__file__), '..', '..', 'selfdrive', 'controls', 'lib', 'latcontrol_pid.py')


def road_curves():
  """The road steer-ratio curves (latcontrol_pid.HONDA_SR_CURVE_BY_FP), read from the source: importing
  latcontrol_pid pulls in compiled device modules."""
  env = {}
  for node in ast.parse(open(LATCONTROL_PID).read()).body:
    if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
      try:
        exec(compile(ast.Module([node], []), LATCONTROL_PID, 'exec'), {}, env)
      except Exception:
        pass
  return env.get('HONDA_SR_CURVE_BY_FP', {})


WHEEL_TO_YAW_LAG = ([3.75, 7.0, 12.0, 20.0, 30.0], [0.08, 0.06, 0.06, 0.08, 0.10])  # s, measured on the Clarity
EDGES = [3, 10, 20, 45, 70, 100, 150, 200, 260, 350, 450]   # |wheel angle| bands, deg
VB = [2.5, 5, 7, 9, 12, 15, 20, 25, 40]                     # speed bands, m/s


def seg(p):
  m = re.search(r'(?:rlog_|--)(\d+)(?:\.zst|\.bz2|/rlog)', p)
  return int(m.group(1)) if m else 0


def read_route(pattern, bus):
  st = dict(y=np.nan, off=0.0, roll=0.0)
  rows = []
  for p in sorted({f for g in pattern.split(',') for f in glob.glob(g)}, key=seg):
    raw = bz2.decompress(open(p, 'rb').read()) if p.endswith('.bz2') else zstd.ZstdDecompressor().stream_reader(open(p, 'rb').read()).read()
    try:
      for e in log.Event.read_multiple_bytes(raw):
        w = e.which()
        if w == 'can':
          for m in e.can:
            if m.src == bus and m.address == 0x94:
              st['y'] = (m.dat[0] << 2) | (m.dat[1] >> 6)
        elif w == 'liveParameters':
          st['off'], st['roll'] = e.liveParameters.angleOffsetDeg, e.liveParameters.roll
        elif w == 'carState':
          c = e.carState
          rows.append((e.logMonoTime * 1e-9, c.vEgo, c.aEgo, c.steeringAngleDeg, c.steeringRateDeg, st['y'], st['off'], st['roll']))
    except Exception:
      pass
  return dict(zip(['t', 'v', 'a', 'ang', 'rate', 'y', 'off', 'roll'], np.array(rows, float).T, strict=True))


def samples(d, scale, right):
  t, v = d['t'], d['v']
  still = np.convolve((v < 0.01).astype(float), np.ones(100) / 100, 'same') > 0.999
  ok = np.isfinite(d['y'])
  zero = float(np.mean(d['y'][still & ok])) if (still & ok).sum() > 300 else 512.0
  counts = d['y'] - zero
  ramp = np.clip((counts - RIGHT_LOSS_BP[0]) / (RIGHT_LOSS_BP[1] - RIGHT_LOSS_BP[0]), 0.0, 1.0)
  yaw = -np.radians(counts * scale + right * ramp)            # clockwise-positive decode -> left-positive like the wheel
  k = np.convolve(yaw, np.ones(10) / 10, 'same') / np.maximum(v, 0.1)
  ang = np.interp(t - np.interp(v, *WHEEL_TO_YAW_LAG), t, d['ang'] - d['off'])
  m = ok & (v > 2.5) & (np.abs(d['a']) < 2) & (np.abs(d['rate']) < 120) & (np.abs(ang) >= 3) & (np.sign(k) == np.sign(ang))
  idx = np.flatnonzero(m)[::5]
  return zero, np.c_[v[idx], ang[idx], k[idx], d['roll'][idx]]


class Fit:
  def __init__(self, vgr_inverse, wheelbase):
    self.lin_bp, self.phy_bp = (np.asarray(x, float) for x in vgr_inverse)
    self.L = wheelbase

  def to_lin(self, phys):
    return np.sign(phys) * np.interp(np.abs(phys), self.phy_bp, self.lin_bp)

  def y(self, D, sf):
    v, th, k, ro = D.T
    return np.radians(self.to_lin(th)) / (self.L * (k * (1 - sf * v ** 2) - G * sf * ro))

  def cells(self, D, sf):
    v, th = D[:, 0], D[:, 1]
    y = self.y(D, sf)
    A, out = np.abs(th), {}
    for bi, (a0, a1) in enumerate(zip(EDGES[:-1], EDGES[1:], strict=True)):
      for vi, (v0, v1) in enumerate(zip(VB[:-1], VB[1:], strict=True)):
        m = (A >= a0) & (A < a1) & (v >= v0) & (v < v1) & (y > 5) & (y < 40)
        lft, rgt = m & (th > 0), m & (th < 0)
        if lft.sum() >= 40 and rgt.sum() >= 40:
          out[(bi, vi)] = (0.5 * (np.median(y[lft]) + np.median(y[rgt])), min(lft.sum(), rgt.sum()))
    return out

  def spread(self, D, sf):
    c = self.cells(D, sf)
    err = w = 0.0
    for b in range(len(EDGES) - 1):
      cs = [(val, n) for (bi, _), (val, n) in c.items() if bi == b]
      if len(cs) < 2:
        continue
      vals, ns = np.array([x[0] for x in cs]), np.sqrt([x[1] for x in cs])
      mu = np.average(vals, weights=ns)
      err += np.sum(ns * (vals / mu - 1) ** 2)
      w += ns.sum()
    return err / w if w else float('nan')

  def fit_sf(self, D):
    sfs = np.arange(-0.0012, 0.0002, 0.00005)
    sp = [self.spread(D, s) for s in sfs]
    i = int(np.argmin(sp))
    if 0 < i < len(sfs) - 1:
      a, b, _ = np.polyfit(sfs[i - 1:i + 2], sp[i - 1:i + 2], 2)
      return round(float(-b / (2 * a)), 5)
    return round(float(sfs[i]), 5)

  def table(self, D, sf):
    th, y = D[:, 1], self.y(D, sf)
    bp, val, n = [], [], []
    for a0, a1 in zip(EDGES[:-1], EDGES[1:], strict=True):
      m = (np.abs(th) >= a0) & (np.abs(th) < a1) & (y > 5) & (y < 40)
      lft, rgt = m & (th > 0), m & (th < 0)
      if lft.sum() > 60 and rgt.sum() > 60:
        bp.append(float(np.median(np.abs(th[m]))))
        val.append(0.5 * (np.median(y[lft]) + np.median(y[rgt])))
        n.append(int(m.sum()))
    # a rack's effective ratio cannot rise off centre: pool upward violations (as the road curves were built)
    val = list(val)
    for i in range(1, len(val)):
      if val[i] > val[i - 1]:
        val[i] = val[i - 1] = (val[i] * n[i] + val[i - 1] * n[i - 1]) / (n[i] + n[i - 1])
        for j in range(i - 1, 0, -1):
          if val[j] > val[j - 1]:
            val[j] = val[j - 1] = (val[j] + val[j - 1]) / 2
    return bp, val, n

  def predict_map(self, D, sf, bp, val):
    v, th, k, ro = D.T
    R = np.interp(np.abs(th), bp, val)
    return (np.radians(self.to_lin(th)) / (R * self.L) + G * sf * ro) / (1 - sf * v ** 2)

  def predict_curve(self, D, curve, sf_vm=-0.00061):
    v, th, k, ro = D.T
    sr = np.interp(np.abs(th), *curve)
    return (np.radians(th) / (sr * self.L) + G * sf_vm * ro) / (1 - sf_vm * v ** 2)


def score(D, pred, label):
  v, th, k = D[:, 0], D[:, 1], D[:, 2]
  row = []
  for a0, a1 in ((3, 20), (20, 70), (70, 150), (150, 450)):
    for v0, v1 in ((2.5, 9), (9, 40)):
      m = (np.abs(th) >= a0) & (np.abs(th) < a1) & (v >= v0) & (v < v1)
      row.append(f'{np.median(k[m] / pred[m]):.3f}' if m.sum() > 100 else '  -  ')
  print(f'  {label:22s} ' + ' '.join(f'{x:>6s}' for x in row))


def main():
  ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
  ap.add_argument('--car', required=True, help='fingerprint, for its current road curve and wheelbase')
  ap.add_argument('--vgr', required=True, help='VGR profile (steer_ratio.HONDA_VGR_INVERSE_BY_PROFILE key)')
  ap.add_argument('--bus', type=int, required=True)
  ap.add_argument('--scale', type=float, required=True, help='deg/s per 0x94 count (GPS-checked)')
  ap.add_argument('--right', type=float, default=0.0, help='clockwise correction, deg/s')
  ap.add_argument('--wheelbase', type=float, default=None)
  ap.add_argument('routes', nargs='+', help='rlog glob per route, comma-separated globs allowed (quote it)')
  a = ap.parse_args()
  wheelbase = a.wheelbase or CAR(a.car).config.specs.wheelbase
  fit = Fit(HONDA_VGR_INVERSE_BY_PROFILE[a.vgr], wheelbase)
  per = []
  for r in a.routes:
    zero, D = samples(read_route(r, a.bus), a.scale, a.right)
    print(f'{r}: zero {zero:.1f}, {len(D) / 20:.0f} s moving at >= 3 deg', flush=True)
    per.append(D)
  D = np.vstack(per)
  if len(D) / 20 < 300:
    raise SystemExit(f'only {len(D) / 20:.0f} s of turning at >= 3 deg: not enough to fit a rack map (the Insight fit had 440 s)')
  sf = fit.fit_sf(D)
  bp, val, n = fit.table(D, sf)
  print(f'\n{a.car} / {a.vgr}: wheelbase {wheelbase}, slip factor {sf} (from the speed dependence within each band)')
  print('RackMapTable(')
  print(f'  ratio_bp=({", ".join(f"{x:.1f}" for x in bp)}),')
  print(f'  ratio_v=({", ".join(f"{x:.2f}" for x in val)}),')
  print(f'  slip_factor={sf},')
  print(')')
  print('  samples per band (s):', [int(x / 20) for x in n])
  print('\nmeasured / predicted curvature, held out by route (1.000 = exact)')
  print('  ' + ' ' * 22 + ' '.join(f'{h:>6s}' for h in ('3-20s', '3-20f', '20-70s', '20-70f', '70-150s', '70-150f', '150+s', '150+f')))
  curve = road_curves().get(a.car)
  for i in range(len(per)) if len(per) > 1 else []:
    tr = np.vstack([p for j, p in enumerate(per) if j != i])
    sfi = fit.fit_sf(tr)
    bpi, vali, _ = fit.table(tr, sfi)
    score(per[i], fit.predict_map(per[i], sfi, bpi, vali), f'route {i}: rack map')
    if curve is not None:
      score(per[i], fit.predict_curve(per[i], curve), f'route {i}: road curve')
  print('  (s = 2.5-9 m/s, f = 9-40 m/s)')


if __name__ == '__main__':
  main()
