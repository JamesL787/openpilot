#!/usr/bin/env python3
"""Closed-loop replay of LatControlHondaEps's core against a car's own firmware law and fitted column.

The route's logged target (pidState.steeringAngleDesiredDeg: after the command delay and rate limit, as the core saw
it) drives HondaEpsLateralCore, the code the car runs; its output goes out as 0xE4 after --cmd-lag, through the
calibration's command map to R5, into the firmware law F = scale*(Kp(R5)*(R5 - ref) + KFF*R5)/2^18 with ref the R6
rate feedback through tracker-1, and into the column j*thdd = F - load(th, thd) (the calibration's ColumnLoadModel,
Coulomb tanh at 2 deg/s as fitted). The angle comes back --sensor-delay late. Hands-off engaged windows only: there is
no driver in the plant.

  open loop    the plant driven by the logged 0xE4 from the measured state, 20 s windows: does it move the wheel the
               way the car did at 0.6-2.5 Hz?
  closed loop  1-2 Hz wheel/target gain and tracking RMS, measured against simulated, with the calibration as it is
               and with --trimless (its P scale and friction knee removed), by speed band.

  eps_closed_loop.py --calibration rdx_tjb_a220 '<route dir>' [...]

Read by timestamp across segments: a segment splits each service at a slightly different moment, so a per-segment
forward fill holds stale controlsState values for up to ~0.2 s at each boundary.
"""
import argparse
import dataclasses
import glob
import math
import os
import re
from collections import deque

import numpy as np
import zstandard as zstd

from openpilot.cereal import log
from openpilot.selfdrive.controls.lib import honda_eps_calibrations as C
from openpilot.selfdrive.controls.lib import honda_eps_firmware_ff as F

MPH = 0.44704
# interface.py, every modified-EPS Honda
KP = ([0., 25 * MPH - 1e-3, 25 * MPH, 50 * MPH], [0.018, 0.024, 0.048, 0.060])
KI = ([0., 25 * MPH - 1e-3, 25 * MPH, 50 * MPH], [0.006, 0.008, 0.016, 0.020])
DT, SUB = 0.01, 20  # 100 Hz controller, 2 kHz plant
TRACKER_TAU = 0.0195  # s, tracker-1 at its Route-A / P-minus-5 setting (KB TRACKER1_TIMING.md)


def seg(p):
  m = re.search(r'(?:rlog_|--)(\d+)(?:\.zst|/rlog)', p)
  return int(m.group(1)) if m else 0


def read_route(pattern):
  s16 = lambda b: int.from_bytes(b, 'big', signed=True)  # noqa: E731
  S = {k: [] for k in ('cs', 'e4', 'cc', 'ctl', 'lp')}
  files = sorted({f for g in pattern.split(',') for f in glob.glob(os.path.join(g, 'rlog*') if os.path.isdir(g) else g)}, key=seg)
  for p in files:
    raw = zstd.ZstdDecompressor().stream_reader(open(p, 'rb').read()).read()
    try:
      for e in log.Event.read_multiple_bytes(raw):
        w, t = e.which(), e.logMonoTime * 1e-9
        if w == 'carState':
          c = e.carState
          S['cs'].append((t, c.vEgo, c.steeringAngleDeg, c.steeringRateDeg, c.steeringTorque, float(c.steeringPressed)))
        elif w == 'sendcan':
          for m in e.sendcan:
            if m.address == 0xE4:
              S['e4'].append((t, s16(m.dat[0:2])))
        elif w == 'carControl':
          S['cc'].append((t, float(e.carControl.latActive)))
        elif w == 'controlsState':
          S['ctl'].append((t, e.controlsState.lateralControlState.pidState.steeringAngleDesiredDeg))
        elif w == 'liveParameters':
          S['lp'].append((t, e.liveParameters.angleOffsetDeg, e.liveParameters.roll))
    except Exception:
      pass
  A = {k: np.array(sorted(v), float) for k, v in S.items()}
  t = A['cs'][:, 0]

  def at(arr, col):
    i = np.searchsorted(arr[:, 0], t, side='right') - 1
    out = arr[np.clip(i, 0, None), col].copy()
    out[i < 0] = np.nan
    return out
  d = dict(t=t, v=A['cs'][:, 1], ang=A['cs'][:, 2], rate=A['cs'][:, 3], tq=A['cs'][:, 4], pr=A['cs'][:, 5],
           lat=np.nan_to_num(at(A['cc'], 1)), des=at(A['ctl'], 1), e4=np.nan_to_num(at(A['e4'], 1)),
           off=np.nan_to_num(at(A['lp'], 1)), roll=np.nan_to_num(at(A['lp'], 2)))
  return d


class Plant:
  def __init__(self, cal, j, sensor_delay):
    self.cal, self.L, self.j = cal, cal.load, j
    self.trk = (DT / SUB) / (TRACKER_TAU + DT / SUB)
    self.nd = int(round(sensor_delay / DT))
    self.reset(0.0, 0.0)

  def reset(self, th, thd):
    self.th, self.thd = th, thd
    self.ref = F.firmware_r6(thd, th, self.cal)
    self.hist = deque([th] * self.nd)

  def frame(self, e4, v, roll):
    cal, L, h = self.cal, self.L, DT / SUB
    r5 = F.r5_from_output(-e4 / cal.e4_per_output, v, cal)
    kp = F.firmware_kp(r5, cal)
    g = 1.0 if cal.r6_angle_bp is None else float(np.interp(abs(self.th), cal.r6_angle_bp, cal.r6_angle_gain))
    k_ang, bias = L.k0 + L.k1 * v * v, L.bias + L.kroll * roll * v * v
    for _ in range(SUB):
      self.ref += self.trk * (max(min(cal.r6_per_deg_s * g * self.thd, F.R6_CLAMP), -F.R6_CLAMP) - self.ref)
      fw = cal.scale_q8 * (kp * (r5 - self.ref) + cal.kff * r5) / 1024.0 / 256.0
      self.thd += h * (fw - k_ang * self.th - L.c * self.thd - bias - L.friction * math.tanh(self.thd / 2.0)) / self.j
      self.th += h * self.thd
    self.hist.append(self.th)
    return self.hist.popleft()


def windows(d, min_len):
  ok = (d['lat'] > .5) & (d['pr'] < .5) & (d['v'] > 3.0) & np.isfinite(d['des']) & (np.abs(d['tq']) < 600)
  out, s = [], None
  for k, f in enumerate(np.r_[ok, False]):
    if f and s is None:
      s = k
    elif not f and s is not None:
      if k - s >= min_len:
        out.append((s, k))
      s = None
  return out


def band(x, lo, hi):
  X = np.fft.rfft(x - x.mean())
  f = np.fft.rfftfreq(len(x), DT)
  X[(f < lo) | (f > hi)] = 0
  return np.fft.irfft(X, len(x))


def closed_loop(d, wins, cal, plant, cmd_lag):
  th_s = np.full(len(d['t']), np.nan)
  for s, e in wins:
    core = F.HondaEpsLateralCore(*KP, *KI, DT, ff=F.HondaEpsFirmwareFeedforward(DT, cal))
    core.output_lpf_enabled = False
    plant.reset(float(d['ang'][s]), float(d['rate'][s]))
    meas, q = float(d['ang'][s]), deque([0.0] * cmd_lag)
    for k in range(s, e):
      v, ro, off = float(d['v'][k]), float(d['roll'][k]), float(d['off'][k])
      q.append(core.update(float(d['des'][k]) - off, off, meas, v, ro, False, False))
      meas = plant.frame(-q.popleft() * cal.e4_per_output, v, ro)
      th_s[k] = meas
  return th_s


def loop_gain(d, ang, wins, vlo, vhi, lo=1.0, hi=2.0, warm=200):
  num = den = 0.0
  err = []
  for s, e in wins:
    a = s + warm
    if e - a < 400 or not (vlo <= d['v'][a:e].mean() < vhi):
      continue
    x, y = band(d['des'][a:e] - d['off'][a:e], lo, hi), band(ang[a:e] - d['off'][a:e], lo, hi)
    num, den = num + np.sum(y ** 2), den + np.sum(x ** 2)
    err.append(ang[a:e] - d['des'][a:e])
  if not den:
    return float('nan'), float('nan')
  return math.sqrt(num / den), float(np.sqrt(np.mean(np.concatenate(err) ** 2)))


def open_loop(d, plant, cmd_lag, vlo, vhi, n=2000):
  gains, corrs = [], []
  for s, e in windows(d, n):
    for a in range(s, e - n, n):
      if not (vlo <= d['v'][a:a + n].mean() < vhi):
        continue
      plant.reset(float(d['ang'][a]), float(d['rate'][a]))
      y = np.array([plant.frame(d['e4'][k - cmd_lag], d['v'][k], d['roll'][k]) for k in range(a, a + n)])
      yb, mb = band(y, 0.6, 2.5), band(d['ang'][a:a + n], 0.6, 2.5)
      gains.append(np.std(yb) / max(np.std(mb), 1e-6))
      corrs.append(np.corrcoef(yb, mb)[0, 1])
  return len(gains), (float(np.median(gains)) if gains else float('nan')), (float(np.median(corrs)) if corrs else float('nan'))


def main():
  ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
  ap.add_argument('--calibration', required=True, help='EpsFirmwareCalibration name, e.g. rdx_tjb_a220')
  ap.add_argument('--j', type=float, default=-0.9, help="column inertia term from fit_column_load.py (its 'j')")
  ap.add_argument('--sensor-delay', type=float, default=0.04, help='s, published angle behind the wheel')
  ap.add_argument('--cmd-lag', type=int, default=2, help='frames from the controller to the firmware')
  ap.add_argument('routes', nargs='+', help='route directory or rlog glob per route (quote globs)')
  a = ap.parse_args()
  cal = next(c for _, c in C.EPS_FIRMWARE_CALIBRATIONS.values() if c.name == a.calibration)
  trimless = dataclasses.replace(cal, p_scale=(1.0, 1.0, 1.0), friction_width_v=None)
  plant = Plant(cal, a.j, a.sensor_delay)
  bands = ((9.0, 20.0), (20.0, 40.0))
  for r in a.routes:
    d = read_route(r)
    wins = windows(d, 800)
    print(f"{r}: {len(wins)} hands-off engaged windows >= 8 s")
    for vlo, vhi in bands:
      n, g, c = open_loop(d, plant, a.cmd_lag, vlo, vhi)
      print(f"  open loop {vlo:.0f}-{vhi:.0f} m/s: {n} x 20 s, 0.6-2.5 Hz wheel sim/measured {g:.2f}, correlation {c:.2f}")
    rows = [('measured', d['ang'])]
    rows.append(('sim, trimless', closed_loop(d, wins, trimless, plant, a.cmd_lag)))
    rows.append((f'sim, {cal.name}', closed_loop(d, wins, cal, plant, a.cmd_lag)))
    for name, ang in rows:
      cells = []
      for vlo, vhi in bands:
        g, rms = loop_gain(d, ang, wins, vlo, vhi)
        cells.append(f"{vlo:.0f}-{vhi:.0f} m/s: 1-2 Hz {g:.2f}, RMS {rms:.2f} deg")
      print(f"  {name:22s} " + ' | '.join(cells))


if __name__ == '__main__':
  main()
