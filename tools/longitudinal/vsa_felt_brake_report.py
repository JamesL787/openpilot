#!/usr/bin/env python3
"""Felt braking per episode from the Bosch VSA accelerometer (0x094, grade removed with carControl pitch) and the
~10 Hz GPS speed derivative, for stock ACC vs openpilot long (STATUS 219). One JSON per run; VSA-GPS agreement included.
usage: vsa_felt_brake_report.py OUT.json ROUTE_DIR [ROUTE_DIR ...]   (ROUTE_DIR holds <seg>/rlog*)"""
import glob
import json
import math
import sys

import numpy as np

from openpilot.tools.longitudinal.bosch_vsa_accel_report import long_accel_dbc, KINEMATICS_ADDR
from openpilot.tools.lib.logreader import LogReader

G, DT = 9.81, 0.05


def read(route):
  kin, cs, cc, rs, gps = {}, [], [], [], []
  files = sorted(glob.glob(route + '/*/rlog*'), key=lambda f: int(f.split('/')[-2]))
  for f in files:
    try:
      for m in LogReader(f, sort_by_time=True):
        w = m.which()
        t = m.logMonoTime * 1e-9
        if w == 'can':
          for c in m.can:
            if c.address == KINEMATICS_ADDR and len(c.dat) >= 5:
              kin.setdefault(c.src, []).append((t, long_accel_dbc(c.dat)))
        elif w == 'carState':
          s = m.carState
          cs.append((t, s.vEgo, s.aEgo, float(s.cruiseState.enabled), float(s.brakePressed or s.gasPressed)))
        elif w == 'carControl':
          c = m.carControl
          o = list(c.orientationNED)
          cc.append((t, float(c.longActive), c.actuators.accel, o[1] if len(o) == 3 else math.nan))
        elif w == 'radarState':
          ld = m.radarState.leadOne
          rs.append((t, ld.dRel if ld.status else math.nan, ld.vRel if ld.status else math.nan,
                     ld.aLeadK if ld.status else math.nan))
        elif w == 'gpsLocationExternal':
          g = m.gpsLocationExternal
          if g.hasFix and g.speedAccuracy < 1.0:
            gps.append((g.unixTimestampMillis * 1e-3, t, g.speed))
    except Exception as e:
      print(route, f, e, file=sys.stderr)
  bus = max(kin, key=lambda b: len(kin[b]))
  return {k: np.array(v, dtype=float) for k, v in
          dict(kin=kin[bus], cs=cs, cc=cc, rs=rs, gps=gps).items()}


def lpf(x, tau):
  y = np.empty_like(x)
  a = DT / (tau + DT)
  y[0] = x[0]
  for i in range(1, len(x)):
    y[i] = y[i - 1] + a * (x[i] - y[i - 1])
  return y


def grid(r):
  t = np.arange(max(r['cs'][0, 0], r['kin'][0, 0], r['cc'][0, 0]), min(r['cs'][-1, 0], r['kin'][-1, 0], r['cc'][-1, 0]), DT)

  def at(a, c):
    return np.interp(t, a[:, 0], a[:, c])

  def hold(a, c):
    i = np.clip(np.searchsorted(a[:, 0], t, side='right') - 1, 0, len(a) - 1)
    return a[i, c]

  g = dict(t=t, v=at(r['cs'], 1), aEgo=at(r['cs'], 2), cruise=hold(r['cs'], 3) > 0.5, pedal=hold(r['cs'], 4) > 0.5,
           long=hold(r['cc'], 1) > 0.5, cmd=at(r['cc'], 2), pitch=np.nan_to_num(at(r['cc'], 3)),
           d=hold(r['rs'], 1), vrel=hold(r['rs'], 2), alead=hold(r['rs'], 3))
  g['vsa'] = at(r['kin'], 1) - G * np.sin(g['pitch'])           # grade removed: felt, not wheel
  g['vsa_s'] = lpf(g['vsa'], 0.15)
  if len(r['gps']) > 50:                                          # GPS speed derivative, ~10 Hz
    gt, gv = r['gps'][:, 1], r['gps'][:, 2]
    k = np.flatnonzero(np.diff(gt) > 0.05)
    gt, gv = gt[k], gv[k]
    ag = np.gradient(gv, gt)
    x = lpf(np.interp(t, gt, ag), 0.15)
    x[(t < gt[0]) | (t > gt[-1])] = np.nan
    gap = np.interp(t, gt[1:], np.diff(gt)) > 0.5
    x[gap] = np.nan
    g['gps_a'] = x
  else:
    g['gps_a'] = np.full_like(t, np.nan)
  return g


def runs(m):
  d = np.diff(np.r_[0, m.astype(int), 0])
  return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1), strict=True))


def episodes(g, alpha):
  eng = (g['long'] if alpha else (g['cruise'] & ~g['long'])) & ~g['pedal'] & (g['v'] > 4.0)
  out = []
  a = g['vsa_s']
  for s, e in runs(eng & (a < -0.8)):
    if e - s < int(0.5 / DT):
      continue
    # walk back to onset at -0.3, forward to release above -0.3 (still engaged)
    s0 = s
    while s0 > 0 and a[s0 - 1] < -0.3 and eng[s0 - 1]:
      s0 -= 1
    e0 = e
    while e0 < len(a) - 1 and a[e0] < -0.3 and eng[e0]:
      e0 += 1
    if out and s0 <= out[-1]['_e']:
      continue
    seg = slice(s0, e0)
    jerk = np.gradient(a[seg], DT)
    pk = s0 + int(np.argmin(a[seg]))
    j_on = jerk[:pk - s0 + 1]
    j_off = jerk[pk - s0:]
    # pulses: deepen >=0.4 after a release >=0.4
    pulses, lo, hi = 0, a[s0], a[s0]
    state = 'down'
    for x in a[seg]:
      if state == 'down':
        lo = min(lo, x)
        if x > lo + 0.4:
          state, hi = 'up', x
      else:
        hi = max(hi, x)
        if x < hi - 0.4:
          pulses += 1
          state, lo = 'down', x
    d0, vr0 = g['d'][s0], g['vrel'][s0]
    ttc0 = d0 / -vr0 if np.isfinite(d0) and vr0 < -0.1 else math.inf
    ga = g['gps_a'][seg]
    out.append(dict(t=float(g['t'][s0]), _e=int(e0), v0=float(g['v'][s0]), d0=float(d0), vrel0=float(vr0), ttc0=float(ttc0),
                    peak=float(a[pk]), gps_peak=float(np.nanmin(ga)) if np.isfinite(ga).any() else None,
                    cmd_peak=float(g['cmd'][seg].min()) if alpha else None,
                    t_to_peak=float((pk - s0) * DT), below1=float(np.sum(a[seg] < -1.0) * DT), dur=float((e0 - s0) * DT),
                    jerk_on=float(np.percentile(j_on, 5)) if len(j_on) > 1 else 0.0,
                    jerk_on_max=float(j_on.min()) if len(j_on) else 0.0,
                    jerk_off=float(np.percentile(j_off, 95)) if len(j_off) > 1 else 0.0,
                    pulses=pulses, d_min=float(np.nanmin(g['d'][seg])) if np.isfinite(g['d'][seg]).any() else None,
                    stop=bool(g['v'][e0 - 1] < 1.0)))
  return out


def main():
  res = {}
  for route in sys.argv[2:]:
    r = read(route)
    g = grid(r)
    alpha = bool(g['long'].mean() > 0.01)
    eps = episodes(g, alpha)
    for e in eps:
      e.pop('_e')
    # VSA vs GPS agreement while moving
    m = np.isfinite(g['gps_a']) & (g['v'] > 4)
    agree = dict(n=int(m.sum()), med=float(np.median(g['vsa_s'][m] - g['gps_a'][m])) if m.any() else None,
                 mad=float(np.median(np.abs(g['vsa_s'][m] - g['gps_a'][m]))) if m.any() else None)
    res[route.rstrip('/').split('/')[-1]] = dict(alpha=alpha, eng_min=float(((g['long'] if alpha else g['cruise']) & (g['v'] > 4)).sum() * DT / 60),
                                                 agree=agree, eps=eps)
    print(route, 'alpha' if alpha else 'stock', len(eps), agree, flush=True)
  json.dump(res, open(sys.argv[1], 'w'))


if __name__ == '__main__':
  main()
