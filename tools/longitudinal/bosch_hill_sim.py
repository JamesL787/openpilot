#!/usr/bin/env python3
"""Closed-loop hill / wind simulator for the Honda Civic Bosch gas path.

Controller: the real opendbc carcontroller pieces (LongGasLearner, bosch_gas_lookup_accel,
get_honda_bosch_wind_brake_mps2, update_honda_bosch_braking, CarControllerParams) imported from
the repo
the ~15-line Bosch gas block of CarController.update() is mirrored in `GasPath.step`.
Variants never touch the repo file: learner_min is applied here by passing the extra lookup
args and feeding the learner pitch - 0.013 (pitch is used only by the learner's pitch gate).

Plant (fitted by plantfit.py on routes 280 + 286, see plant_fit.npy):
  a = drive(u(t - lag(v)), first-order 0.1 s) + r0 + r2*v^2 - k*g*sin(theta)   (k = --plant-hill up/down, default 1) - CD*((v+w)|v+w| - v^2)
  drive(u) = 0 for u <= 0.02, else step + s1*min(u, 0.7) + s2*max(u - 0.7, 0),  u = GAS_COMMAND/375
  lag(v) 0.68 s below 3 m/s -> 0.48 s above 7 m/s. Gas saturates at 750 (u = 2).
  CD = -r2 (all speed-squared road load treated as aero, so wind w (+ = headwind) scales it).
  Brake mode (gas_force below BOSCH_BRAKE_FORCE_ON): the Bosch ECU is assumed to achieve
  min(coast, ACCEL_COMMAND) through a 0.3 s first-order lag. Not fitted
  descents only.
Sensors: aEgo = a through 0.15 s lowpass + N(0, 0.03)
pitch = theta + 0.013 + lowpassed noise
  (sd 0.003 rad, 1 s). vEgo exact.
Planner: cruise to set speed, a_target = clip(KV*(v_set - v), A_CRUISE_MIN, A_CRUISE_MAX(v)),
  jerk limited +1.0/-2.0 m/s^3, at 20 Hz. longcontrol kp = ki = 0, so actuators.accel = a_target.
  Or --atarget log: the recorded aTarget of the route replayed open loop by time.
"""
import argparse
import html
import json
import math
import os
import sys
from collections import deque

import numpy as np

REPO = os.environ.get('OP_REPO', '/home/ubuntu/openpilot')
sys.path[:0] = [REPO, os.path.join(REPO, 'opendbc_repo')]
from opendbc.car.honda import carcontroller as ccmod
from opendbc.car.honda.values import CarControllerParams

G = 9.81
MPH = 0.44704
DT = 0.01            # plant / controller frame (100 Hz)
PITCH_BIAS = 0.013   # rad, CC pitch minus GPS grade on this mount
# bosch_hill_plant_fit.py on routes 00000280 + 00000286 (2026-09-29): aEgo rms 0.132 / 0.118 open loop.
TAU1, EXTRA = 0.1, 0.0   # first-order after the delay, lag offset (a 0.1 s shorter lag fits 0.002 better)
STEP, S1, S2, R0, R2 = 0.163014, 0.818455, 0.591186, -0.195082, -0.000361787
# grade coefficient of the plant: 1 in this fit; the 26-route offline gas fit found ~0.84 (0.81 up, 1.01 down)
HILL_K = [1.0, 1.0]   # [uphill, downhill], set from --plant-hill


def grade_accel(th):
  return G * math.sin(th) * (HILL_K[0] if th > 0 else HILL_K[1])
CD = -R2
UK = 0.7
A_CRUISE_MAX_BP = [0.0, 5., 10., 15., 20., 25., 40.]
A_CRUISE_MAX_VALS = [1.125, 1.125, 1.125, 1.125, 1.25, 1.25, 1.5]
A_CRUISE_MIN = -1.0
MIN_GAS = CarControllerParams.BOSCH_GAS_LOOKUP_BP[0]
LOOK_BP = CarControllerParams.BOSCH_GAS_LOOKUP_BP
LOOK_V = [0, 750]  # honda/interface.py sets this for HONDA_CIVIC_BOSCH (values.py default is [0, 1600])
ACCEL_MAX, ACCEL_MIN = CarControllerParams.BOSCH_ACCEL_MAX, CarControllerParams.BOSCH_ACCEL_MIN
GAS_MAX = 750.0


def lag_s(v):
  return float(np.interp(v, [3.0, 7.0], [0.68, 0.48])) + EXTRA


def drive(u):
  if u <= 0.02:
    return 0.0
  return STEP + S1 * min(u, UK) + S2 * max(u - UK, 0.0)


# ---------------------------------------------------------------- controller variants
class GasPath:
  """Bosch gas block of CarController.update() at the 2-frame cadence. variant: head | prefix | learner_min | mvl"""

  def __init__(self, variant, gf0, wf0, hill_gain=1.2):
    self.variant = variant
    self.hill_gain = hill_gain
    self.learner = ccmod.LongGasLearner(gf0, wf0, "HONDA_CIVIC_BOSCH")
    # mvl 6f044aeb0 state
    self.gf, self.wf, self.gasalpha = gf0, wf0, 0.0
    self.gf_before_max, self.wf_before_max, self.wf_before_brake = gf0, wf0, wf0
    self.last_gas = 0.0
    self.braking = False
    self.gas = 0.0
    self.accel = 0.0
    self.gas_force = 0.0
    self.learning = False

  @property
  def factors(self):
    if self.variant == 'mvl':
      return self.gf, self.wf, self.gasalpha
    return self.learner.gasfactor, self.learner.windfactor, 0.0

  def step(self, accel, a_ego, v_ego, pitch):
    hill = math.sin(pitch) * G
    wind = ccmod.get_honda_bosch_wind_brake_mps2(v_ego)
    self.accel = float(np.clip(accel, ACCEL_MIN, ACCEL_MAX))
    if self.variant == 'mvl':
      gpf = accel + wind * self.wf + hill + self.gasalpha
      err = accel - a_ego  # no lag alignment in mvl
      ls = 150
      if err != 0.0 and gpf > 0:
        self.gf = float(np.clip(self.gf + err / ls * gpf, 0.01, 3.0))
      if (-0.5 < gpf - self.gasalpha < 0.1) and v_ego > 1.0:
        self.gasalpha = float(np.clip(self.gasalpha + err / ls / 10.0, 0.0, 0.4))
      if err != 0.0 and v_ego > 0.0:
        adj = 1 + wind / 1000
        self.wf = float(np.clip(self.wf * (adj if err > 0 else 1.0 / adj), 0.1, 3.0))
      if gpf <= 0.0:
        self.wf = max(self.wf, self.wf_before_brake)
      else:
        self.wf_before_brake = self.wf
      if gpf >= ACCEL_MAX:
        self.gf = min(self.gf, self.gf_before_max)
        self.wf = min(self.wf, self.wf_before_max)
      else:
        self.gf_before_max, self.wf_before_max = self.gf, self.wf
      look = gpf * self.gf
      self.learning = True
    else:
      L = self.learner
      gpf = accel + wind * L.windfactor + hill
      L.update(accel_cmd=accel, a_ego=a_ego, gas_pedal_force=gpf, wind_brake_ms2=wind, long_active=True,
               long_pid=True, gas_pressed=False, brake_pressed=False, v_ego=v_ego, at_standstill=v_ego <= 0.0,
               pitch=pitch - (PITCH_BIAS if self.variant == 'learner_min' else 0.0), brake_addon=0.0,
               at_accel_max=gpf >= ACCEL_MAX)
      self.learning = L.learning
      gf = L.gasfactor
      if self.variant == 'prefix':
        look = (gpf - MIN_GAS) * gf + MIN_GAS
      elif self.variant == 'learner_min':
        look = ccmod.bosch_gas_lookup_accel(gpf, hill, gf, MIN_GAS) + (self.hill_gain - 1.0) * (hill - math.sin(PITCH_BIAS) * G)
      else:
        look = ccmod.bosch_gas_lookup_accel(gpf, hill, gf, MIN_GAS)
    gas = float(np.interp(look, LOOK_BP, LOOK_V))
    gas = min(gas, max(60.0, self.last_gas + 60.0))
    self.last_gas = gas
    self.braking = ccmod.update_honda_bosch_braking(self.braking, gpf, False, True)
    self.gas_force = gpf
    # hondacan: GAS_COMMAND only when gas_force > min_gas and not braking, else -30000 (no gas)
    self.gas = min(gas, GAS_MAX) if (gpf > MIN_GAS and not self.braking) else 0.0
    return self.gas


# ---------------------------------------------------------------- scenarios
def smoothstep(x):
  x = np.clip(x, 0.0, 1.0)
  return x * x * (3 - 2 * x)


class Scenario:
  """grade(s) in rad by distance, wind(t) m/s (+ head), vset(t) m/s, duration s."""

  def __init__(self, name, duration, vset, grade=None, wind=None, atarget=None, group=''):
    self.name, self.duration, self.group = name, duration, group
    self.vset = vset if callable(vset) else (lambda t, v=vset: v)
    self.grade = grade or (lambda s: 0.0)
    self.wind = wind or (lambda t: 0.0)
    self.atarget = atarget


def hill_profile(deg, start, length=500.0, ramp=100.0):
  th = math.radians(deg)
  def f(s):
    up = smoothstep((s - start) / ramp)
    down = smoothstep((s - start - length) / ramp)
    return th * (up - down)
  return f


def route280_grade(npz, src='pitch'):
  d = np.load(npz)
  t, v = d['t'], d['v']
  m = (t >= 29 * 60) & (t < 33 * 60)
  s = np.cumsum(np.where(m, v, 0.0)) * 0.05
  s = s[m] - s[m][0]
  if src == 'gps':
    alt = d['alt'][m]
    k = int(2.5 / 0.05)  # GPS altitude lags 2-3 s: shift it forward
    alt = np.concatenate([alt[k:], np.full(k, alt[-1])])
    # grade = d(alt)/ds over a 50 m window
    ss = np.arange(0, s[-1], 5.0)
    a = np.interp(ss, s, alt)
    w = 10
    gr = np.zeros_like(ss)
    gr[w:-w] = (a[2 * w:] - a[:-2 * w]) / (ss[2 * w:] - ss[:-2 * w])
    return lambda x: float(np.interp(x, ss, np.arctan(gr)))
  th = np.radians(d['ccp'][m]) - PITCH_BIAS
  th = np.convolve(th, np.ones(20) / 20, mode='same')  # 1 s smoothing of the CC pitch
  return lambda x: float(np.interp(x, s, th))


def route280_atarget(npz):
  d = np.load(npz)
  m = (d['t'] >= 29 * 60) & (d['t'] < 33 * 60)
  t, aT = d['t'][m] - d['t'][m][0], d['aT'][m]
  return lambda x: float(np.interp(x, t, aT))


def scenarios(which, grade_src='pitch', atarget=None, npz=None):
  out = []
  if 'a' in which and npz is None:
    print('scenario a skipped: pass --route-npz (route 280 20 Hz npz)', file=sys.stderr)
  elif 'a' in which:
    out.append(Scenario(f'a_280_29-32_{grade_src}', 240.0, 50 * MPH, grade=route280_grade(npz, grade_src),
                        atarget=route280_atarget(npz) if atarget == 'log' else None, group='a'))
  if 'b' in which:
    for mph in (30, 45, 65):
      for deg in (2, 4, 6):
        for sgn in (1, -1):
          v = mph * MPH
          start = 20 * v
          out.append(Scenario(f'b_{"up" if sgn > 0 else "dn"}{deg}_{mph}', 20 + (1300 / v) + 25, v,
                              grade=hill_profile(sgn * deg, start), group='b'))
  if 'c' in which:
    for w in (5, 10, -5, -10):
      out.append(Scenario(f'c_{"head" if w > 0 else "tail"}{abs(w)}_65', 90.0, 65 * MPH,
                          wind=lambda t, w=w: w * smoothstep((t - 20) / 2.0) * (1 - smoothstep((t - 60) / 2.0)), group='c'))
  if 'd' in which:
    out.append(mixed_drive())
  if 'e' in which:
    for mph in (30, 45, 65):
      out.append(Scenario(f'e_flat_{mph}', 120.0, mph * MPH, group='e'))
  return out


def mixed_drive(minutes=24, seed=7):
  """(d) b- and c-type events back to back at 45/65 mph for ~24 min; learner state carries through."""
  rng = np.random.default_rng(seed)
  t, s = 0.0, 0.0
  hills, winds, vsets = [], [], [(0.0, 65 * MPH)]
  v = 65 * MPH
  while t < minutes * 60:
    if rng.random() < 0.15:
      v = float(rng.choice([45, 65])) * MPH
      vsets.append((t, v))
    t += 30
    s += 30 * v
    kind = rng.choice(['hill', 'hill', 'wind'])
    if kind == 'hill':
      deg = float(rng.choice([2, 4, 6])) * float(rng.choice([1, -1]))
      L = float(rng.choice([300, 500, 800]))
      hills.append((deg, s, L))
      dur = (L + 200) / v
      t += dur
      s += dur * v
    else:
      w = float(rng.choice([5, 10, -5, -10]))
      dur = float(rng.choice([30, 60, 120]))
      winds.append((t, t + dur, w))
      t += dur
      s += dur * v
  profs = [hill_profile(d, s0, L) for d, s0, L in hills]

  def vset(tt):
    cur = vsets[0][1]
    for t0, vv in vsets:
      if tt >= t0:
        cur = vv
    return cur

  def wind(tt):
    return sum(w * smoothstep((tt - a) / 2.0) * (1 - smoothstep((tt - b) / 2.0)) for a, b, w in winds)
  sc = Scenario(f'd_mix_{minutes}min', t, vset, grade=lambda x: sum(p(x) for p in profs), wind=wind, group='d')
  sc.events = {'hills': hills, 'winds': winds, 'vsets': vsets}
  return sc


# ---------------------------------------------------------------- closed loop
class Noise:
  def __init__(self, seed):
    self.rng = np.random.default_rng(seed)
    self.p = 0.0

  def pitch(self):
    a = DT / (1.0 + DT)
    self.p += a * (self.rng.normal(0, 0.003 * math.sqrt(2 / a)) - self.p)
    return self.p


def run(sc, variant, gf0=1.25, wf0=1.0, seed=1, hill_gain=1.2, kv=0.4, trace_hz=5):
  gp = GasPath(variant, gf0, wf0, hill_gain)
  nz = Noise(seed)
  v = sc.vset(0.0)
  x = 0.0
  n = int(sc.duration / DT)
  # prime drivetrain delay line and filters at a steady state for the initial speed and grade
  hist = deque(maxlen=int(1.2 / DT))
  a_true = 0.0
  a_filt = 0.0
  a_brake = 0.0
  u_f = 0.0
  a_target = 0.0
  accel_cmd = 0.0
  for _ in range(hist.maxlen):
    hist.append(0.0)
  rec = {k: [] for k in ('t', 'v', 'vset', 'a', 'aT', 'gas', 'gf', 'wf', 'ga', 'grade', 'wind', 'brk', 'learn')}
  jerk_a, prev_af = [], None
  every = int(1 / (trace_hz * DT))
  sat = over = 0
  climb_until = -1.0
  # warm start: hold the steady-state gas for vset on the initial grade so t=0 isn't a launch
  th0 = sc.grade(0.0)
  need = -(R0 + R2 * v * v) + grade_accel(th0)
  u0 = 0.0
  if need > STEP:
    u0 = (need - STEP) / S1 if need - STEP <= S1 * UK else UK + (need - STEP - S1 * UK) / S2
  for i in range(hist.maxlen):
    hist[i] = u0
  u_f = u0
  gp.last_gas = u0 * 375
  gp.gas = u0 * 375
  for i in range(n):
    t = i * DT
    th = sc.grade(x)
    w = sc.wind(t)
    vs = sc.vset(t)
    # sensors
    pitch = th + PITCH_BIAS + nz.pitch()
    if i % 5 == 0:  # planner at 20 Hz
      if sc.atarget is not None:
        a_des = sc.atarget(t)
      else:
        a_des = float(np.clip(kv * (vs - v), A_CRUISE_MIN, np.interp(v, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)))
      a_target = float(np.clip(a_des, a_target - 2.0 * 0.05, a_target + 1.0 * 0.05))
      accel_cmd = a_target  # longcontrol kp = ki = 0 -> feed-forward only
    if i % 2 == 0:
      a_ego_meas = a_filt + nz.rng.normal(0, 0.03)
      gp.step(accel_cmd, a_ego_meas, v, pitch)
    u = gp.gas / 375.0
    hist.append(u)
    k = min(int(round(lag_s(v) / DT)), hist.maxlen - 1)
    u_d = hist[-1 - k]
    u_f += DT / (TAU1 + DT) * (u_d - u_f)
    coast = R0 + R2 * v * v - grade_accel(th) - CD * ((v + w) * abs(v + w) - v * v)
    a_gas = drive(u_f) + coast
    if gp.braking:
      a_brake += DT / (0.3 + DT) * (min(0.0, gp.accel - coast) - a_brake)
    else:
      a_brake += DT / (0.3 + DT) * (0.0 - a_brake)
    a_true = a_gas + min(a_brake, 0.0)
    a_filt += DT / (0.15 + DT) * (a_true - a_filt)
    v = max(0.0, v + a_true * DT)
    x += v * DT
    if i % 2 == 0:
      sat += gp.gas >= GAS_MAX - 1
      over += (v - vs) > 1 * MPH
      af = a_filt
      if prev_af is not None:
        jerk_a.append((af - prev_af) / (2 * DT))
      prev_af = af
    if i % every == 0:
      gf, wf, ga = gp.factors
      for kk, val in (('t', t), ('v', v), ('vset', vs), ('a', a_true), ('aT', accel_cmd), ('gas', gp.gas), ('gf', gf),
                      ('wf', wf), ('ga', ga), ('grade', math.degrees(th)), ('wind', w), ('brk', float(gp.braking)),
                      ('learn', float(gp.learning))):
        rec[kk].append(round(float(val), 4))
    # metric accumulators at full rate
    if i == 0:
      acc = {'e2': 0.0, 'n': 0, 'peak_over': -99.0, 'min_under': 99.0}
    e = a_true - accel_cmd
    acc['e2'] += e * e
    acc['n'] += 1
    dv = (v - vs) / MPH
    acc['peak_over'] = max(acc['peak_over'], dv)
    if th > math.radians(1.0):
      climb_until = t + 10.0  # count the 10 s after the crest too: the car is still recovering
    if t < climb_until:
      acc['min_under'] = min(acc['min_under'], dv)
  gf, wf, ga = gp.factors
  j = np.array(jerk_a)
  metrics = {
    'peak_over_mph': acc['peak_over'],
    't_over_1mph_s': over * 2 * DT,
    'climb_under_mph': acc['min_under'] if acc['min_under'] < 99 else float('nan'),
    'rms_a_err': math.sqrt(acc['e2'] / acc['n']),
    'jerk_rms': float(np.sqrt(np.mean(j ** 2))) if len(j) else 0.0,
    'gf_end': gf, 'gf_min': min(rec['gf']), 'gf_max': max(rec['gf']),
    'wf_end': wf, 'wf_min': min(rec['wf']), 'wf_max': max(rec['wf']),
    'ga_end': ga,
    't_gas_sat_s': sat * 2 * DT,
  }
  return metrics, rec


VARIANTS = ('head', 'prefix', 'learner_min', 'mvl')


def fmt_table(rows):
  cols = ['peak_over_mph', 't_over_1mph_s', 'climb_under_mph', 'rms_a_err', 'jerk_rms', 'gf_end', 'gf_min', 'gf_max',
          'wf_end', 't_gas_sat_s']
  hdr = ['scenario', 'variant', 'pk_over', 't>+1mph', 'climb_und', 'rms(a-aT)', 'jerk_rms', 'gf_end', 'gf_min',
         'gf_max', 'wf_end', 't_gas_sat']
  lines = ['  '.join(f'{h:>10s}' if i > 1 else f'{h:<16s}' if i == 0 else f'{h:<11s}' for i, h in enumerate(hdr))]
  last = None
  for sc, var, m in rows:
    if last is not None and sc != last:
      lines.append('')
    last = sc
    cells = [f'{sc:<16s}', f'{var:<11s}'] + [f'{m[c]:>10.3f}' if not math.isnan(m[c]) else f'{"-":>10s}' for c in cols]
    lines.append('  '.join(cells))
  return '\n'.join(lines)


# ---------------------------------------------------------------- html report
COLORS = {'head': '#1f77b4', 'prefix': '#d62728', 'learner_min': '#2ca02c', 'mvl': '#9467bd'}
PANELS = [('v - vset (mph)', lambda r, i: (r['v'][i] - r['vset'][i]) / 0.44704),
          ('a (solid) / aT (dotted) m/s²', lambda r, i: r['a'][i]),
          ('gas (0-750)', lambda r, i: r['gas'][i]),
          ('gasfactor', lambda r, i: r['gf'][i]),
          ('windfactor', lambda r, i: r['wf'][i]),
          ('grade ° / wind m/s', lambda r, i: r['grade'][i])]
W, H, PADL = 900, 110, 60


def svg_panel(title, traces, fn, extra=None, tmax=None):
  pts = {}
  lo, hi = math.inf, -math.inf
  for var, r in traces.items():
    ys = [fn(r, i) for i in range(len(r['t']))]
    pts[var] = list(zip(r['t'], ys, strict=False))
    lo, hi = min(lo, *ys), max(hi, *ys)
  for ex in (extra or []):
    lo, hi = min(lo, *[y for _, y in ex[1]]), max(hi, *[y for _, y in ex[1]])
  if hi - lo < 1e-3:
    hi, lo = hi + 0.5, lo - 0.5
  pad = 0.05 * (hi - lo)
  lo -= pad
  hi += pad
  tmax = tmax or max(p[-1][0] for p in pts.values())
  def X(t):
    return PADL + (W - PADL - 10) * t / tmax
  def Y(y):
    return 5 + (H - 20) * (hi - y) / (hi - lo)
  out = [f'<svg width="{W}" height="{H}" style="background:#fff;border:1px solid #ddd">']
  if lo < 0 < hi:
    out.append(f'<line x1="{PADL}" x2="{W - 10}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#bbb" stroke-dasharray="3,3"/>')
  for y in (lo + pad, hi - pad):
    out.append(f'<text x="{PADL - 4}" y="{Y(y) + 4:.1f}" font-size="10" text-anchor="end">{y:.2f}</text>')
  out.append(f'<text x="{PADL + 4}" y="14" font-size="11" fill="#444">{html.escape(title)}</text>')
  for var, p in pts.items():
    d = ' '.join(f'{X(t):.1f},{Y(y):.1f}' for t, y in p)
    out.append(f'<polyline fill="none" stroke="{COLORS.get(var, "#000")}" stroke-width="1.2" points="{d}"/>')
  for style, p, color in (extra or []):
    d = ' '.join(f'{X(t):.1f},{Y(y):.1f}' for t, y in p)
    out.append(f'<polyline fill="none" stroke="{color}" stroke-width="1" stroke-dasharray="{style}" points="{d}"/>')
  for tt in range(0, int(tmax) + 1, max(10, int(tmax / 10) // 10 * 10 or 10)):
    out.append(f'<text x="{X(tt):.1f}" y="{H - 3}" font-size="9" text-anchor="middle" fill="#888">{tt}</text>')
  out.append('</svg>')
  return '\n'.join(out)


def write_html(path):
  D = json.load(open(path))
  out_dir = os.path.dirname(path)
  table = open(os.path.join(out_dir, 'table.txt')).read()
  body = ['<h1>hillsim: Civic Bosch gas path, closed loop</h1>',
          ('<p>Simulated plant fitted on routes 280/286 (open-loop aEgo RMS 0.13/0.12). Real LongGasLearner and ' +
          'bosch_gas_lookup_accel in the loop, cruise-to-set planner, feed-forward longcontrol. Simulation evidence only; ' +
          'see the plant and sensor assumptions in bosch_hill_sim.py.</p>'),
          '<p>' + ' '.join(f'<span style="color:{c};font-weight:bold">■ {v}</span>' for v, c in COLORS.items()) + '</p>',
          f'<pre style="font-size:11px">{html.escape(table)}</pre>']
  for sc, traces in D['traces'].items():
    body.append(f'<h3 id="{sc}">{sc}</h3>')
    first = next(iter(traces.values()))
    for title, fn in PANELS:
      extra = None
      if title.startswith('a '):
        extra = [('2,2', list(zip(r['t'], r['aT'], strict=False)), COLORS.get(v, '#000')) for v, r in traces.items()]
      if title.startswith('grade'):
        tr = {'grade': first}
        extra = [('4,2', list(zip(first['t'], first['wind'], strict=False)), '#ff7f0e')]
        body.append(svg_panel(title + ' (grade solid, wind dashed)', tr, fn, extra))
        continue
      body.append(svg_panel(title, traces, fn, extra))
  page = ('<!doctype html><html><head><meta charset="utf-8"><title>hillsim</title>' +
          '<style>body{font-family:sans-serif;margin:16px} svg{display:block;margin:2px 0}</style></head><body>'
          + '\n'.join(body) + '</body></html>')
  dst = os.path.join(out_dir, 'hillsim.html')
  open(dst, 'w').write(page)
  return dst



def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument('--variants', default=','.join(VARIANTS))
  ap.add_argument('--scenarios', default='abcde', help='letters from abcde')
  ap.add_argument('--gf0', type=float, default=1.25)
  ap.add_argument('--wf0', type=float, default=1.0)
  ap.add_argument('--hill-gain', type=float, default=1.2, help='learner_min hill gain')
  ap.add_argument('--kv', type=float, default=0.4, help='cruise planner speed gain, 1/s')
  ap.add_argument('--plant-hill', type=float, nargs='+', default=[1.0], metavar='K',
                  help='plant grade coefficient: one value, or uphill downhill (e.g. 0.81 1.01)')
  ap.add_argument('--grade-src', default='pitch', choices=['pitch', 'gps'])
  ap.add_argument('--atarget', default=None, choices=[None, 'log'], help="scenario a: replay the logged aTarget")
  ap.add_argument('--seed', type=int, default=1)
  ap.add_argument('--route-npz', default=None, help='route 280 npz for scenario a (fields t v ccp alt aT, 20 Hz)')
  ap.add_argument('--out', default='/tmp/bosch_hill_sim')
  args = ap.parse_args()
  HILL_K[:] = (args.plant_hill * 2)[:2]
  os.makedirs(args.out, exist_ok=True)
  rows, traces = [], {}
  for sc in scenarios(args.scenarios, args.grade_src, args.atarget, args.route_npz):
    for var in args.variants.split(','):
      m, rec = run(sc, var, args.gf0, args.wf0, args.seed, args.hill_gain, args.kv)
      rows.append((sc.name, var, m))
      traces.setdefault(sc.name, {})[var] = rec
      print(f'{sc.name} {var} done', file=sys.stderr)
  table = fmt_table(rows)
  hdr = (f'# hillsim  gf0 {args.gf0} wf0 {args.wf0} hill_gain {args.hill_gain} kv {args.kv} grade {args.grade_src} ' +
         f'atarget {args.atarget} seed {args.seed}\n' +
         f'# plant: step {STEP:.3f} s1 {S1:.3f} s2 {S2:.3f} r0 {R0:+.3f} r2 {R2:+.6f} tau1 {TAU1} lag 0.68->0.48 s hill_k up/down {HILL_K[0]}/{HILL_K[1]}\n' +
         '# pk_over: peak v - vset (mph); t>+1mph: s above set + 1 mph; climb_und: lowest v - vset on grade > 1 deg (mph)\n' +
         '# rms(a-aT): true accel - accel cmd; jerk_rms: of 0.15 s-filtered a (m/s^3); t_gas_sat: s at GAS 750\n')
  open(os.path.join(args.out, 'table.txt'), 'w').write(hdr + table + '\n')
  json.dump({'args': vars(args), 'rows': rows, 'traces': traces}, open(os.path.join(args.out, 'runs.json'), 'w'))
  print(hdr + table)
  print(write_html(os.path.join(args.out, 'runs.json')), file=sys.stderr)


if __name__ == '__main__':
  main()
