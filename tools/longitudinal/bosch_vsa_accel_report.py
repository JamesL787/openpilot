#!/usr/bin/env python3
"""Ego acceleration as the Bosch-A radar sees it, against what openpilot commands. Offline, logging only.

The 2026-10-03 cross-check (docs/xcheck_openpilot_2026-10-03.md) found that input b of the radar's ACC
min-select 0xd0c58 is KINEMATICS 0x094 LONG_ACCEL, the VSA's measured longitudinal acceleration, and input a
is a wheel-speed derivative. So the radar firmware bounds its own law with min(wheel accel, VSA accel). openpilot
judges braking only against carState.aEgo (wheel-speed KF). This tool reads rlogs and reports:

  1. 0x094 coverage and the two decodings of LONG_ACCEL (opendbc 9-bit signed x -0.049; firmware 10-bit
     offset-binary x 49/1024 - 24.5, negated). They should agree; a disagreement means the decode is wrong.
  2. aVsa - aEgo bias, raw and with g*sin(pitch) removed (an accelerometer reads grade, a wheel derivative does not).
  3. Command vs delivered accel in the STATUS item 71 bins (-0.5 ... -3.0 by 0.5, then -3.0...-3.6), delivered
     measured at t + lag (default 0.35 s, the item 71 value) against both aEgo and aVsa (docs §11.1, §12.3 P0).
     If aVsa sits on the command where aEgo over-delivers, part of the item 71 over-brake is measurement.
  4. A firmware-style ego accel aFw = min(a, b), a = wheel-mean speed, 5-tap mean, 41/2048 s difference, one
     first-order low-pass (--fw-lpf; the firmware's IIR constants are unresolved, correction h), b = 5-tap mean
     of aVsa. Reported against the command for the same bins.
  5. The stock-equivalent command: the sent command slewed at -5 m/s^3 on onset (the firmware ACC law's limiter).
     How often and by how much it differs. Item 72 found the over-brake does not grow with onset rate, so this
     is a log column, not a proposal to limit the command.
  6. The U11 vRel - d(dRel)/dt residual of radarState.leadOne regressed on aEgo and aVsa (docs §11 item 4,
     D-044, D-074). A slope well away from 0 means ego acceleration leaks into the radar's speed channel.

Input: one or more rlog files or segment directories (rlog.zst / rlog.bz2 / rlog). Nothing is written. Route data
stays out of the repo; cite it by route ID.

  tools/longitudinal/bosch_vsa_accel_report.py ~/routes/0000023e--abcdef1234/3 ~/routes/0000023e--abcdef1234/4

Evidence level: the functions below are unit-tested on synthetic data only (tools/longitudinal/tests/
test_bosch_vsa_accel_report.py). First real route: 000002e2 (Civic Bosch, 2026-10-05, STATUS 215). Since
STATUS 215 the live value is also logged as starpilotCarState.aEgoVsa / aEgoVsaValid.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

KINEMATICS_ADDR = 0x094
G = 9.81
FW_DIFF_DT = 41 / 2048  # firmware differentiator step, s (≈ 20 ms)
STOCK_ONSET_JERK = -5.0  # m/s^3, firmware ACC law onset limiter
ITEM71_LAG = 0.35
BINS = ((-1.0, -0.5), (-1.5, -1.0), (-2.0, -1.5), (-2.5, -2.0), (-3.0, -2.5), (-3.6, -3.0))
GRID_DT = 0.01


# ---------- decoding ----------

def long_accel_dbc(dat: bytes) -> float:
  """opendbc KINEMATICS LONG_ACCEL 24|9@0- (-0.049): forward-positive m/s^2."""
  raw = ((dat[3] & 0x01) << 8) | dat[4]
  if raw & 0x100:
    raw -= 0x200
  return raw * -0.049


def long_accel_fw(dat: bytes) -> float:
  """Firmware read of COM 0x276: 10 bits, LSB 32 (MSB 25), raw*49/1024 - 24.5, then negated."""
  raw = ((dat[3] & 0x03) << 8) | dat[4]
  return -(raw * 49 / 1024 - 24.5)


# ---------- filters ----------

def moving_mean(x: np.ndarray, n: int = 5) -> np.ndarray:
  """Causal n-tap mean; the first n-1 samples average what exists."""
  c = np.cumsum(np.insert(np.asarray(x, dtype=float), 0, 0.0))
  i = np.arange(1, len(x) + 1)
  lo = np.maximum(i - n, 0)
  return (c[i] - c[lo]) / (i - lo)


def first_order_lpf(x: np.ndarray, tau: float, dt: float) -> np.ndarray:
  if tau <= 0:
    return np.asarray(x, dtype=float).copy()
  y = np.empty(len(x))
  al = dt / (tau + dt)
  acc = float(x[0]) if len(x) else 0.0
  for k, v in enumerate(x):
    acc += al * (v - acc)
    y[k] = acc
  return y


def wheel_accel_fw(t: np.ndarray, v: np.ndarray, lpf_tau: float) -> np.ndarray:
  """Input a: 5-tap mean of the wheel-mean speed, difference over FW_DIFF_DT, first-order low-pass.

  t must be a uniform grid; the difference uses the nearest whole number of samples to FW_DIFF_DT (>= 1).
  """
  dt = float(np.median(np.diff(t)))
  k = max(1, int(round(FW_DIFF_DT / dt)))
  vm = moving_mean(v, 5)
  d = np.zeros_like(vm)
  d[k:] = (vm[k:] - vm[:-k]) / (k * dt)
  return first_order_lpf(d, lpf_tau, dt)


def fw_min_accel(a_wheel: np.ndarray, a_vsa: np.ndarray) -> np.ndarray:
  """0xd0c58 as re-read by the cross-check: signed min of the two measured ego accels (b 5-tap averaged)."""
  return np.minimum(a_wheel, moving_mean(a_vsa, 5))


def stock_slew(cmd: np.ndarray, dt: float, onset_jerk: float = STOCK_ONSET_JERK) -> np.ndarray:
  """Command with its decreasing direction rate-limited to onset_jerk (m/s^3); increases pass unchanged."""
  out = np.empty(len(cmd))
  prev = float(cmd[0]) if len(cmd) else 0.0
  step = onset_jerk * dt
  for k, c in enumerate(cmd):
    prev = c if c >= prev else max(c, prev + step)
    out[k] = prev
  return out


# ---------- statistics ----------

def bin_delivery(t: np.ndarray, cmd: np.ndarray, delivered: np.ndarray, active: np.ndarray, lag: float = ITEM71_LAG):
  """Per BINS: (lo, hi, n, median(delivered(t+lag) - cmd), p10, p90). n counts grid samples."""
  shifted = np.interp(t + lag, t, delivered, right=np.nan)
  out = []
  for lo, hi in BINS:
    m = active & (cmd >= lo) & (cmd < hi) & np.isfinite(shifted)
    e = shifted[m] - cmd[m]
    if len(e):
      out.append((lo, hi, int(m.sum()), float(np.median(e)), float(np.percentile(e, 10)), float(np.percentile(e, 90))))
    else:
      out.append((lo, hi, 0, math.nan, math.nan, math.nan))
  return out


def ols(y: np.ndarray, *xs: np.ndarray):
  """y = c0 + sum(ci * xi). Returns (coefs, r2, n) over finite rows."""
  X = np.column_stack([np.ones(len(y)), *xs])
  m = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
  if m.sum() < X.shape[1] + 2:
    return np.full(X.shape[1], np.nan), math.nan, int(m.sum())
  coef, *_ = np.linalg.lstsq(X[m], y[m], rcond=None)
  res = y[m] - X[m] @ coef
  ss = float(np.sum((y[m] - y[m].mean()) ** 2))
  return coef, (1 - float(res @ res) / ss) if ss > 0 else math.nan, int(m.sum())


def range_rate(t: np.ndarray, d: np.ndarray, track: np.ndarray, half_window: float = 0.25) -> np.ndarray:
  """Central-difference d(dRel)/dt over +-half_window, NaN where the track id changes inside the window."""
  out = np.full(len(t), np.nan)
  lo = np.searchsorted(t, t - half_window)
  hi = np.searchsorted(t, t + half_window, side='right') - 1
  for k in range(len(t)):
    a, b = lo[k], hi[k]
    if b > a and track[a] == track[k] == track[b] and track[k] >= 0 and t[b] > t[a]:
      out[k] = (d[b] - d[a]) / (t[b] - t[a])
  return out


# ---------- log reading ----------

def rlog_files(paths: list[str]) -> list[Path]:
  def seg_rlog(d: Path) -> Path | None:
    return next((d / n for n in ('rlog.zst', 'rlog.bz2', 'rlog') if (d / n).exists()), None)

  out = []
  for p in (Path(s).expanduser() for s in paths):
    if p.is_dir():
      f = seg_rlog(p)
      if f is None:
        # a route directory as tools/konik_fetch.py writes it: <route>/<segment>/rlog.zst, in segment order
        segs = sorted((d for d in p.iterdir() if d.is_dir() and d.name.isdigit()), key=lambda d: int(d.name))
        found = [r for r in (seg_rlog(d) for d in segs) if r is not None]
        if not found:
          raise SystemExit(f'{p}: no rlog')
        out.extend(found)
        continue
      out.append(f)
    else:
      out.append(p)
  return out


def read_logs(files: list[Path]) -> dict:
  from openpilot.tools.lib.logreader import LogReader
  kin: dict[int, list] = {}
  cs, cc, rs = [], [], []
  for f in files:
    for m in LogReader(str(f), sort_by_time=True):
      w = m.which()
      t = m.logMonoTime * 1e-9
      if w == 'can':
        for c in m.can:
          if c.address == KINEMATICS_ADDR and len(c.dat) >= 5:
            kin.setdefault(c.src, []).append((t, long_accel_dbc(c.dat), long_accel_fw(c.dat)))
      elif w == 'carState':
        s = m.carState
        ws = s.wheelSpeeds
        cs.append((t, s.vEgo, s.aEgo, (ws.fl + ws.fr + ws.rl + ws.rr) / 4))
      elif w == 'carControl':
        c = m.carControl
        o = list(c.orientationNED)
        cc.append((t, float(c.longActive), c.actuators.accel, o[1] if len(o) == 3 else math.nan))
      elif w == 'radarState':
        ld = m.radarState.leadOne
        rs.append((t, ld.dRel if ld.status else math.nan, ld.vRel if ld.status else math.nan,
                   getattr(ld, 'radarTrackId', -1) if ld.status and ld.radar else -1))
  bus = max(kin, key=lambda b: len(kin[b])) if kin else None
  return {'kin': np.array(kin[bus], dtype=float).reshape(-1, 3) if bus is not None else np.zeros((0, 3)),
          'kin_bus': bus, 'cs': np.array(cs, dtype=float).reshape(-1, 4), 'cc': np.array(cc, dtype=float).reshape(-1, 4),
          'rs': np.array(rs, dtype=float).reshape(-1, 4)}


def to_grid(raw: dict) -> dict | None:
  if len(raw['cs']) < 10 or len(raw['kin']) < 10 or len(raw['cc']) < 10:
    return None
  t0 = max(raw['cs'][0, 0], raw['kin'][0, 0], raw['cc'][0, 0])
  t1 = min(raw['cs'][-1, 0], raw['kin'][-1, 0], raw['cc'][-1, 0])
  t = np.arange(t0, t1, GRID_DT)

  def at(a, c):
    return np.interp(t, a[:, 0], a[:, c])

  def hold(a, c):  # zero-order hold for ids and flags
    i = np.clip(np.searchsorted(a[:, 0], t, side='right') - 1, 0, len(a) - 1)
    return a[i, c]
  g = {'t': t, 'v': at(raw['cs'], 1), 'aEgo': at(raw['cs'], 2), 'vWheel': at(raw['cs'], 3),
       'aVsa': at(raw['kin'], 1), 'aVsaFw': at(raw['kin'], 2), 'active': hold(raw['cc'], 1) > 0.5,
       'cmd': at(raw['cc'], 2), 'pitch': at(raw['cc'], 3)}
  if len(raw['rs']) > 10:
    g['dRel'], g['vRel'], g['trk'] = hold(raw['rs'], 1), hold(raw['rs'], 2), hold(raw['rs'], 3)
  return g


# ---------- report ----------

def fmt_bins(name: str, rows) -> str:
  s = [f'  {name}']
  for lo, hi, n, med, p10, p90 in rows:
    s.append(f'    [{lo:+.1f},{hi:+.1f})  n={n:6d}  median={med:+.2f}  p10={p10:+.2f}  p90={p90:+.2f}')
  return '\n'.join(s)


def report(raw: dict, lag: float, fw_lpf: float) -> str:
  out = []
  kin = raw['kin']
  if len(kin) > 1:
    rate = (len(kin) - 1) / (kin[-1, 0] - kin[0, 0])
    dd = np.abs(kin[:, 1] - kin[:, 2])
    out.append(f'0x094 KINEMATICS: bus {raw["kin_bus"]}, {len(kin)} frames, {rate:.1f} Hz; ' +
               f'|dbc - fw decode| median {np.median(dd):.3f}, p99 {np.percentile(dd, 99):.3f} m/s^2')
  else:
    return 'no 0x094 KINEMATICS frames in these logs (wrong bus logged, or not a Honda Bosch car)'
  g = to_grid(raw)
  if g is None:
    return '\n'.join(out + ['not enough carState/carControl/0x094 overlap to analyse'])
  t, cmd, act = g['t'], g['cmd'], g['active']
  grade = G * np.sin(np.nan_to_num(g['pitch']))
  steady = np.abs(np.gradient(moving_mean(g['aEgo'], 25), t)) < 0.5
  b = g['aVsa'] - g['aEgo']
  bc = g['aVsa'] - grade - g['aEgo']
  out.append(f'aVsa - aEgo (|jerk|<0.5): median {np.median(b[steady]):+.3f}; with g*sin(pitch) removed {np.median(bc[steady]):+.3f}' +
             '  (pitch from carControl.orientationNED; NaN pitch treated as 0)')
  a_fw = fw_min_accel(wheel_accel_fw(t, g['vWheel'], fw_lpf), g['aVsa'])
  out.append(f'\ncommand vs delivered at t+{lag:.2f} s, longActive only (delivered - cmd, m/s^2):')
  out.append(fmt_bins('aEgo (wheel KF, what openpilot judges against)', bin_delivery(t, cmd, g['aEgo'], act, lag)))
  out.append(fmt_bins('aVsa (0x094 accelerometer, raw)', bin_delivery(t, cmd, g['aVsa'], act, lag)))
  out.append(fmt_bins('aVsa - g*sin(pitch)', bin_delivery(t, cmd, g['aVsa'] - grade, act, lag)))
  out.append(fmt_bins(f'aFw = min(wheel 5-tap/diff/lpf {fw_lpf:.2f}s, 5-tap aVsa)', bin_delivery(t, cmd, a_fw, act, lag)))
  st = stock_slew(cmd, GRID_DT)
  diff = (cmd - st)[act]
  if len(diff):
    out.append(f'\nstock-equivalent -5 m/s^3 onset slew: command differs by > 0.1 on {100 * np.mean(diff < -0.1):.1f} % of ' +
               f'active time; largest {diff.min():+.2f} m/s^2 (logging only; item 72)')
  if 'dRel' in g:
    rr = range_rate(t, g['dRel'], g['trk'])
    res = g['vRel'] - rr
    for name, x in (('aEgo', g['aEgo']), ('aVsa', g['aVsa'])):
      coef, r2, n = ols(res, x)
      out.append(f'U11 - d(dRel)/dt vs {name}: intercept {coef[0]:+.3f} m/s, slope {coef[1]:+.3f} s, r2 {r2:.3f}, n {n}')
  return '\n'.join(out)


def main(argv: list[str] | None = None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument('paths', nargs='+', help='rlog files or segment directories')
  ap.add_argument('--lag', type=float, default=ITEM71_LAG, help='delivered-accel lag, s (default %(default)s, item 71)')
  ap.add_argument('--fw-lpf', type=float, default=0.1, help='low-pass tau for the wheel-derived input a, s; ' +
                  'NOT from firmware (IIR constants unresolved), default %(default)s')
  args = ap.parse_args(argv)
  print(report(read_logs(rlog_files(args.paths)), args.lag, args.fw_lpf))
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
