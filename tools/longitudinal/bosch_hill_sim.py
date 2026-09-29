#!/usr/bin/env python3
"""Closed-loop hill / wind simulator for the Honda Civic Bosch gas path. Simulation, not driven.

Where it sits in the longitudinal replay family (tools/longitudinal, Radar Work (Bob), 2026-09-29):
  alpha_open_loop_replay.py    planner variants against the logged scene, open loop
  alpha_closed_loop_replay.py  planner variants, each driving its own sim car (--sim-window, --frames-json)
  plan_variant_compare.py      pages from those frames: planner command, sim a / v, gap to the lead per variant
  long_replay_viewer.py        radar / camera / lead frames of one window
  range_arm_scan.py            logged range-assist arms across routes
  bosch_hill_sim.py            this: the car side below the planner command, on hills and in wind
  bosch_hill_plant_fit.py      fits and checks this file's plant on logged routes
The replay tools stop at the planner command and move their sim car with a first-order accel lag. This one starts at
the command and runs the Civic's gas path (LongGasLearner, gas lookup, gas ramp, brake hysteresis) into a fitted
drivetrain, so a planner variant's command from alpha_closed_loop_replay can be driven through it
(--frames-json F --frames-variant K). Route input is the same route directory the replay tools take
(~/routes/<route>/<seg>/rlog.zst) and route time t is theirs: seconds from the first initData of segment 0.
Output follows plan_variant_compare: --out DIR gets index.html, summary.json (+ table.txt, traces.json).

  bosch_hill_sim.py --out /tmp/hill                                   # synthetic hills, wind, mixed drive, flat
  bosch_hill_sim.py --route ~/routes/00000280--d02d9c2f8e --window 1740,1980 --scenarios a --out /tmp/hill280
  bosch_hill_sim.py --route ~/routes/00000280--d02d9c2f8e --window 1740,1980 --scenarios a \\
      --frames-json /tmp/rv/plan/f.json --frames-variant b0.075 --out /tmp/hill280_b   # a replayed planner command

Controller: the real opendbc carcontroller pieces (LongGasLearner, bosch_gas_lookup_accel,
get_honda_bosch_wind_brake_mps2, update_honda_bosch_braking, CarControllerParams) imported from
the repo; the ~15-line Bosch gas block of CarController.update() is mirrored in `GasPath.step`.
Variants never touch the repo file: learner_min is applied here by passing the extra lookup
args and feeding the learner pitch - 0.013 (pitch is used only by the learner's pitch gate).

Plant (fitted by bosch_hill_plant_fit.py on routes 280 + 286):
  a = drive(u(t - lag(v)), first-order 0.1 s) + r0 + r2*v^2 - k*g*sin(theta) - CD*((v+w)|v+w| - v^2)
  k = --plant-hill (up / down, default 1); CD = -r2 (all speed-squared road load treated as aero, so wind w,
  + = headwind, scales it)
  drive(u) = 0 for u <= 0.02, else step + s1*min(u, 0.7) + s2*max(u - 0.7, 0),  u = GAS_COMMAND/375
  lag(v) 0.68 s below 3 m/s -> 0.48 s above 7 m/s. Gas saturates at 750 (u = 2).
  Brake mode (gas_force below BOSCH_BRAKE_FORCE_ON): the Bosch ECU is assumed to achieve min(coast, ACCEL_COMMAND)
  through a 0.3 s first-order lag. Not fitted; it matters on descents only.
Sensors: aEgo = a through 0.15 s lowpass + N(0, 0.03); pitch = theta + 0.013 + lowpassed noise (sd 0.003 rad, 1 s);
  vEgo exact.
Planner: cruise to set speed, a_target = clip(KV*(v_set - v), A_CRUISE_MIN, A_CRUISE_MAX(v)),
  jerk limited +1.0/-2.0 m/s^3, at 20 Hz. longcontrol kp = ki = 0, so actuators.accel = a_target.
  Or, route scenario (a) only: --atarget log replays the logged aTarget, and --frames-json replays a variant's
  planner command from alpha_closed_loop_replay, both open loop by time. A replayed command starts at the logged
  speed and is scored as sim v - logged v (the plant alone drifts ~1 m/s rms over 30 s open loop, so read that
  column against the `logged` variant's, not against zero).
Set speed for (a): --vset, else the logged carState.vCruise while long is active.
--route-npz takes a 20 Hz npz (fields as read_route returns) in its own clock: /tmp/rv/hill/g280full.npz runs
  1.6 s behind route t.
Run from the repo with PYTHONPATH=$(dirname $PWD):$PWD, as the other tools/longitudinal scripts.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

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

  def __init__(self, name, duration, vset, grade=None, wind=None, atarget=None, group='', v0=None, vlog=None):
    self.name, self.duration, self.group = name, duration, group
    self.v0 = v0  # start speed (default vset(0)); a replayed command starts at the logged speed
    self.vlog = vlog  # logged speed(t), scored against the sim speed when the command is replayed
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


# ---------------------------------------------------------------- route input
RDT = 0.05  # route arrays are resampled to 20 Hz


def segment_files(route_dir: Path) -> list[Path]:
  # same rule as alpha_open_loop_replay.segment_files; importing that module loads the planner and Params
  segs = []
  for d in route_dir.iterdir():
    if d.is_dir() and d.name.isdigit():
      for name in ('rlog.zst', 'rlog.bz2', 'rlog'):
        if (d / name).exists():
          segs.append((int(d.name), d / name))
          break
  return [p for _, p in sorted(segs)]


def read_route(route_dir: Path, window: tuple[float, float] | None = None) -> dict:
  """20 Hz arrays of one route, t in route seconds (the replay tools' clock: first initData of segment 0).

  Fields: t v aE gp bp vcruise la acmd ccp (carControl.orientationNED pitch, deg) alt aT gas. Only the segments
  covering `window` are read (segment 0 too, for its first initData when it is not one of them).
  """
  from openpilot.tools.lib.logreader import LogReader
  route_dir = Path(route_dir).expanduser()
  files = segment_files(route_dir)
  if not files:
    raise SystemExit(f'{route_dir}: no <seg>/rlog.zst')
  if window is not None:
    files = [f for f in files if window[0] - 60 < int(f.parent.name) * 60 < window[1] + 1]
  t0 = None
  for f in segment_files(route_dir)[:1]:
    if f.parent.name == '0':
      t0 = next((m.logMonoTime for m in LogReader(str(f)) if m.which() == 'initData'), None)
  raw: dict[str, list] = {k: [] for k in ('cs', 'cc', 'co', 'lp', 'gps')}
  for f in files:
    for m in LogReader(str(f), sort_by_time=True):
      w = m.which()
      if t0 is None:  # no segment 0: fall back to seg * 60 s from this segment's first message
        t0 = m.logMonoTime - int(int(f.parent.name) * 60e9)
      t = (m.logMonoTime - t0) / 1e9
      if w == 'carState':
        c = m.carState
        # set speed: openpilot's vCruise (km/h, 255 = unset); this car logs cruiseState.speed as 0
        vc = c.vCruise / 3.6 if 0 < c.vCruise < 250 else c.cruiseState.speed
        raw['cs'].append((t, c.vEgo, c.aEgo, c.gasPressed, c.brakePressed, vc))
      elif w == 'carControl':
        c = m.carControl
        o = list(c.orientationNED)
        raw['cc'].append((t, c.longActive, c.actuators.accel, o[1] if len(o) == 3 else np.nan))
      elif w == 'carOutput':
        raw['co'].append((t, m.carOutput.actuatorsOutput.gas))
      elif w == 'longitudinalPlan':
        raw['lp'].append((t, m.longitudinalPlan.aTarget))
      elif w == 'gpsLocationExternal':
        raw['gps'].append((t, m.gpsLocationExternal.altitude))
  a = {k: np.array(sorted(v), dtype=float).reshape(-1, 2 if k in ('co', 'lp', 'gps') else (6 if k == 'cs' else 4))
       for k, v in raw.items()}
  if len(a['cs']) < 2:
    raise SystemExit(f'{route_dir}: no carState in the segments read')
  t = np.arange(a['cs'][0, 0] + 1, a['cs'][-1, 0] - 1, RDT)

  def at(k, c):
    return np.interp(t, a[k][:, 0], a[k][:, c]) if len(a[k]) else np.full_like(t, np.nan)
  return {'t': t, 'v': at('cs', 1), 'aE': at('cs', 2), 'gp': at('cs', 3), 'bp': at('cs', 4), 'vcruise': at('cs', 5),
          'la': at('cc', 1), 'acmd': at('cc', 2), 'ccp': np.degrees(at('cc', 3)), 'gas': at('co', 1), 'aT': at('lp', 1),
          'alt': at('gps', 1)}


def load_route(src: str | Path, window: tuple[float, float] | None = None, cache: Path | None = None) -> dict:
  """A route directory (read with read_route), or an npz of the same 20 Hz fields (bosch_hill_plant_fit input).

  cache: npz written after a route read and reused on the next run with the same route and window. Keep it outside
  the repo; route data is never committed.
  """
  src = Path(src).expanduser()
  if src.suffix == '.npz':
    z = np.load(src)
    return {k: z[k] for k in z.files}
  if cache is not None:
    cache = cache.with_suffix('.npz')  # np.savez would add it anyway
  if cache is not None and cache.exists():
    z = np.load(cache)
    if str(z['src']) == f'{src.resolve()}|{window}':
      return {k: z[k] for k in z.files if k != 'src'}
  R = read_route(src, window)
  if cache is not None:
    np.savez(cache, src=f'{src.resolve()}|{window}', **R)
  return R


def route_grade(R, window, src='pitch'):
  t, v = R['t'], R['v']
  m = (t >= window[0]) & (t < window[1])
  s = np.cumsum(np.where(m, v, 0.0)) * RDT
  s = s[m] - s[m][0]
  if src == 'gps':
    alt = R['alt'][m]
    k = int(2.5 / RDT)  # GPS altitude lags 2-3 s: shift it forward
    alt = np.concatenate([alt[k:], np.full(k, alt[-1])])
    # grade = d(alt)/ds over a 50 m window
    ss = np.arange(0, s[-1], 5.0)
    a = np.interp(ss, s, alt)
    w = 10
    gr = np.zeros_like(ss)
    gr[w:-w] = (a[2 * w:] - a[:-2 * w]) / (ss[2 * w:] - ss[:-2 * w])
    return lambda x: float(np.interp(x, ss, np.arctan(gr)))
  th = np.radians(R['ccp'][m]) - PITCH_BIAS
  th = np.convolve(th, np.ones(20) / 20, mode='same')  # 1 s smoothing of the CC pitch
  return lambda x: float(np.interp(x, s, th))


def route_series(R, window, key):
  m = (R['t'] >= window[0]) & (R['t'] < window[1])
  t, y = R['t'][m] - R['t'][m][0], R[key][m]
  return lambda x: float(np.interp(x, t, y))


FRAMES_ALIGN_S = 3.0  # frames JSON clock checked against the route's vEgo within +-this (the npz clock can differ by ~1 s)


def frames_atarget(path: Path, variant: str, R, window):
  """A planner variant's command (frame `out`) from alpha_closed_loop_replay --frames-json, on the route window.

  The frames' own v_ego is matched to the route's vEgo to confirm (or find) the clock offset; returns (fn, offset_s).
  """
  F = json.loads(Path(path).read_text())['frames']
  fr = [f for f in F if f.get('out', {}).get(variant) is not None]
  if not fr:
    keys = sorted({k for f in F for k in f.get('out', {})})
    raise SystemExit(f'{path}: no frames with out[{variant!r}]; variants there: {", ".join(keys)}')
  ft = np.array([f['t'] for f in fr])
  fa = np.array([f['out'][variant] for f in fr], dtype=float)
  fv = np.array([f['v_ego'] for f in fr], dtype=float)
  m = (R['t'] >= window[0]) & (R['t'] < window[1])
  rt, rv = R['t'][m], R['v'][m]
  cover = (rt >= ft[0]) & (rt <= ft[-1])
  if cover.mean() < 0.9:
    raise SystemExit(f'{path}: frames cover {ft[0]:.1f}-{ft[-1]:.1f} s, only {cover.mean():.0%} of the window {window}')
  offs = np.arange(-FRAMES_ALIGN_S, FRAMES_ALIGN_S + 1e-9, RDT)
  err = [np.nanmean((np.interp(rt[cover] + o, ft, fv) - rv[cover]) ** 2) for o in offs]
  off = float(offs[int(np.argmin(err))])
  t0 = rt[0]
  return (lambda x: float(np.interp(t0 + x + off, ft, fa))), off


def scenarios(which, grade_src='pitch', atarget=None, route=None):
  """route: {'R': load_route(...), 'window': (t0, t1), 'name': str, 'vset': m/s or None, 'frames': (path, variant)}"""
  out = []
  if 'a' in which and route is None:
    print('scenario a skipped: pass --route DIR --window T0,T1 (or --route-npz)', file=sys.stderr)
  elif 'a' in which:
    R, win = route['R'], route['window']
    vset = route.get('vset')
    if vset is None and 'vcruise' in R:
      m = (R['t'] >= win[0]) & (R['t'] < win[1]) & (R['la'] > 0.5) & (R['vcruise'] > 1)
      vset = float(np.median(R['vcruise'][m])) if m.any() else None
    if vset is None:
      vset = 50 * MPH
    at, tag = None, ''
    if route.get('frames'):
      at, off = frames_atarget(*route['frames'], R, win)
      tag = f'_{route["frames"][1]}'
      print(f'scenario a: {route["frames"][0]} out[{route["frames"][1]}], frames clock {off:+.2f} s against the route', file=sys.stderr)
    elif atarget == 'log':
      at, tag = route_series(R, win, 'aT'), '_logaT'
    vlog = route_series(R, win, 'v') if at is not None else None
    out.append(Scenario(f'a_{route["name"]}_{win[0]:g}-{win[1]:g}_{grade_src}{tag}', float(win[1] - win[0]), vset,
                        grade=route_grade(R, win, grade_src), atarget=at, group='a',
                        v0=vlog(0.0) if vlog else None, vlog=vlog))
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
  v = sc.v0 if sc.v0 is not None else sc.vset(0.0)
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
      acc = {'e2': 0.0, 'n': 0, 'peak_over': -99.0, 'min_under': 99.0, 'l2': 0.0, 'lmax': 0.0}
    e = a_true - accel_cmd
    acc['e2'] += e * e
    acc['n'] += 1
    dv = (v - vs) / MPH
    if sc.vlog is not None:
      dl = (v - sc.vlog(t)) / MPH
      acc['l2'] += dl * dl
      acc['lmax'] = max(acc['lmax'], abs(dl))
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
    'v_vs_log_rms_mph': math.sqrt(acc['l2'] / acc['n']) if sc.vlog is not None else float('nan'),
    'v_vs_log_max_mph': acc['lmax'] if sc.vlog is not None else float('nan'),
  }
  return metrics, rec


VARIANTS = ('head', 'prefix', 'learner_min', 'mvl')


def fmt_table(rows):
  cols = ['peak_over_mph', 't_over_1mph_s', 'climb_under_mph', 'rms_a_err', 'jerk_rms', 'gf_end', 'gf_min', 'gf_max',
          'wf_end', 't_gas_sat_s']
  hdr = ['scenario', 'variant', 'pk_over', 't>+1mph', 'climb_und', 'rms(a-aT)', 'jerk_rms', 'gf_end', 'gf_min',
         'gf_max', 'wf_end', 't_gas_sat']
  if any(not math.isnan(m.get('v_vs_log_rms_mph', float('nan'))) for _, _, m in rows):
    cols.append('v_vs_log_rms_mph')
    hdr.append('v-vlog_rms')
  lines = ['  '.join(f'{h:>10s}' if i > 1 else f'{h:<16s}' if i == 0 else f'{h:<11s}' for i, h in enumerate(hdr))]
  last = None
  for sc, var, m in rows:
    if last is not None and sc != last:
      lines.append('')
    last = sc
    cells = [f'{sc:<16s}', f'{var:<11s}'] + [f'{m[c]:>10.3f}' if not math.isnan(m[c]) else f'{"-":>10s}' for c in cols]
    lines.append('  '.join(cells))
  return '\n'.join(lines)


# ---------------------------------------------------------------- report
# family colours (plan_variant_compare): the repo code is blue, mvl green
COLORS = {'head': '#1f5fbf', 'prefix': '#bcbd22', 'learner_min': '#e377c2', 'mvl': '#2ca02c'}
LABELS = {'head': 'head', 'prefix': 'prefix', 'learner_min': 'learner_min', 'mvl': 'mvl'}
WIND_COLOR = '#ff7f0e'
PANELS = [('v - vset (mph)', lambda r, i: (r['v'][i] - r['vset'][i]) / MPH),
          ('a (solid) / command (dotted) m/s²', lambda r, i: r['a'][i]),
          ('gas (0-750)', lambda r, i: r['gas'][i]),
          ('gasfactor', lambda r, i: r['gf'][i]),
          ('windfactor', lambda r, i: r['wf'][i]),
          ('grade ° / wind m/s', lambda r, i: r['grade'][i])]
W, H, PADL = 900, 110, 60
COLS = [('peak_over_mph', 'peak over set mph', 2), ('t_over_1mph_s', 's over set +1 mph', 1),
        ('climb_under_mph', 'lowest on climbs mph', 2), ('rms_a_err', 'rms(a - cmd) m/s²', 3), ('jerk_rms', 'jerk rms m/s³', 2),
        ('gf_end', 'gf end', 3), ('gf_max', 'gf max', 3), ('wf_end', 'wf end', 3), ('t_gas_sat_s', 's at gas 750', 1),
        ('v_vs_log_rms_mph', 'sim v - logged v rms mph', 2)]


def label(v: str) -> str:
  return LABELS.get(v, v)


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


def index_html(meta: dict, rows: list[dict], traces: dict) -> str:
  scs = list(dict.fromkeys(r['scenario'] for r in rows))
  head = ''.join(f'<th>{html.escape(t)}</th>' for _, t, _ in COLS)
  trs = []
  for sc in scs:
    rs = [r for r in rows if r['scenario'] == sc]
    for j, r in enumerate(rs):
      name = f'<td rowspan="{len(rs)}"><a href="#{html.escape(sc)}">{html.escape(sc)}</a></td>' if j == 0 else ''
      cells = ''.join('<td>-</td>' if r[k] is None or (isinstance(r[k], float) and math.isnan(r[k])) else f'<td>{r[k]:.{nd}f}</td>'
                      for k, _, nd in COLS)
      trs.append(f'<tr>{name}<td style="color:{COLORS.get(r["variant"], "#000")};font-weight:bold">'
                 + f'{html.escape(label(r["variant"]))}</td>{cells}</tr>')
  plots = []
  for sc, tr in traces.items():
    plots.append(f'<h3 id="{html.escape(sc)}">{html.escape(sc)}</h3>')
    first = next(iter(tr.values()))
    for title, fn in PANELS:
      extra = None
      if title.startswith('a '):
        extra = [('2,2', list(zip(r['t'], r['aT'], strict=False)), COLORS.get(v, '#000')) for v, r in tr.items()]
      if title.startswith('grade'):
        extra = [('4,2', list(zip(first['t'], first['wind'], strict=False)), WIND_COLOR)]
        plots.append(svg_panel(title + ' (grade solid, wind dashed)', {'grade': first}, fn, extra))
        continue
      plots.append(svg_panel(title, tr, fn, extra))
  legend = ' '.join(f'<span style="color:{COLORS.get(v, "#000")};font-weight:bold">■ {html.escape(label(v))}</span>'
                    for v in meta['variants'])
  src = meta.get('route') or 'synthetic scenarios only'
  cmd = meta.get('command_source') or 'cruise-to-set planner'
  return f"""<!doctype html><html><head><meta charset="utf-8"><title>Civic gas path on hills — simulation</title><style>
body{{font:13px system-ui,sans-serif;margin:14px;max-width:1500px}} table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:3px 8px;text-align:right}} td:first-child{{text-align:left}} svg{{display:block;margin:2px 0}}
.warn{{background:#fff4d6;border:1px solid #e0b000;padding:6px 10px;margin:6px 0}}</style></head><body>
<h2>Civic Bosch gas path on hills and in wind — simulation, not driven</h2>
<div class="warn">Closed-loop simulation. The controller is the repo's LongGasLearner and gas lookup; the car is a drivetrain
fitted on routes 00000280 / 00000286 (open-loop aEgo rms 0.13 / 0.12 m/s², bosch_hill_plant_fit.py), plant hill term
up/down {meta['plant_hill'][0]:g} / {meta['plant_hill'][1]:g}. Wind and grade are what the scenario says, not measured.
Command: {html.escape(cmd)}. Route: {html.escape(str(src))}.
learner_min is applied in this file only (hill gain {meta['hill_gain']:g}); it is not in the car.</div>
<p>{legend} &nbsp; gf0 {meta['gf0']:g}, wf0 {meta['wf0']:g}, kv {meta['kv']:g} 1/s, grade from {meta['grade_src']}, seed {meta['seed']},
build {html.escape(str(meta.get('git_commit')))}. "lowest on climbs" is the lowest v - vset on grade &gt; 1° and the 10 s after.</p>
<table><tr><th>scenario</th><th>variant</th>{head}</tr>{''.join(trs)}</table>
{''.join(plots)}
</body></html>"""


def git_commit() -> str | None:
  import subprocess
  try:
    return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=Path(__file__).parent, capture_output=True, text=True,
                          check=True).stdout.strip()
  except (OSError, subprocess.CalledProcessError):
    return None


def parse_window(s: str) -> tuple[float, float]:
  a, b = (float(x) for x in s.split(','))
  return a, b


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument('--out', type=Path, required=True, help='directory for index.html, summary.json, table.txt, traces.json')
  ap.add_argument('--variants', default=','.join(VARIANTS))
  ap.add_argument('--scenarios', default='bcde', help='letters from abcde (a needs --route or --route-npz)')
  ap.add_argument('--gf0', type=float, default=1.25)
  ap.add_argument('--wf0', type=float, default=1.0)
  ap.add_argument('--hill-gain', type=float, default=1.2, help='learner_min hill gain')
  ap.add_argument('--kv', type=float, default=0.4, help='cruise planner speed gain, 1/s')
  ap.add_argument('--plant-hill', type=float, nargs='+', default=[1.0], metavar='K',
                  help='plant grade coefficient: one value, or uphill downhill (e.g. 0.81 1.01)')
  ap.add_argument('--grade-src', default='pitch', choices=['pitch', 'gps'])
  ap.add_argument('--seed', type=int, default=1)
  ap.add_argument('--route', type=Path, help='route directory (<seg>/rlog.zst), as the replay tools take it')
  ap.add_argument('--window', type=parse_window, metavar='T0,T1', help='route seconds for scenario a')
  ap.add_argument('--vset', type=float, metavar='MPH', help='scenario a set speed (default: logged cruise set speed, median)')
  ap.add_argument('--cache', type=Path, help='npz cache of the route read (keep it outside the repo)')
  ap.add_argument('--route-npz', type=Path, help='20 Hz route npz instead of --route (default window 1740,1980, 50 mph)')
  ap.add_argument('--atarget', default=None, choices=[None, 'log'], help='scenario a: replay the logged aTarget')
  ap.add_argument('--frames-json', type=Path, help='scenario a: replay a planner command from alpha_closed_loop_replay')
  ap.add_argument('--frames-variant', default='b0.075', help='frame `out` key for --frames-json (default the repo planner)')
  ap.add_argument('--label', action='append', default=[], metavar='KEY=NAME', help='display name for a variant key')
  args = ap.parse_args()
  for kv in args.label:
    k, v = kv.split('=', 1)
    LABELS[k] = v
  HILL_K[:] = (args.plant_hill * 2)[:2]
  route = None
  if args.route is not None or args.route_npz is not None:
    if args.route is not None and args.window is None:
      ap.error('--route needs --window T0,T1')
    window = args.window or (29 * 60.0, 33 * 60.0)
    src = args.route if args.route is not None else args.route_npz
    R = load_route(src, window, args.cache)
    name = src.name.split('--')[0] if args.route is not None else src.stem
    vset = args.vset * MPH if args.vset else (None if args.route is not None else 50 * MPH)
    route = {'R': R, 'window': window, 'name': name, 'vset': vset,
             'frames': (args.frames_json, args.frames_variant) if args.frames_json else None}
  elif args.frames_json or args.atarget:
    ap.error('--frames-json / --atarget replay a command on a route: pass --route DIR --window T0,T1')
  args.out.mkdir(parents=True, exist_ok=True)
  variants = args.variants.split(',')
  rows, traces = [], {}
  for sc in scenarios(args.scenarios, args.grade_src, args.atarget, route):
    for var in variants:
      m, rec = run(sc, var, args.gf0, args.wf0, args.seed, args.hill_gain, args.kv)
      rows.append((sc.name, var, m))
      traces.setdefault(sc.name, {})[var] = rec
      print(f'{sc.name} {var} done', file=sys.stderr)
  if not rows:
    print('no scenarios ran', file=sys.stderr)
    return 1
  meta = {'variants': variants, 'scenarios': args.scenarios, 'gf0': args.gf0, 'wf0': args.wf0, 'hill_gain': args.hill_gain,
          'kv': args.kv, 'plant_hill': list(HILL_K), 'grade_src': args.grade_src, 'seed': args.seed,
          'route': str(args.route or args.route_npz or '') or None, 'window': route['window'] if route else None,
          'command_source': (f'{args.frames_json} out[{args.frames_variant}]' if args.frames_json else
                             'logged aTarget' if args.atarget == 'log' else None),
          'plant': {'step': STEP, 's1': S1, 's2': S2, 'r0': R0, 'r2': R2, 'tau1': TAU1, 'lag_s': [0.68, 0.48]},
          'git_commit': git_commit()}
  table = fmt_table(rows)
  hdr = (f'# hillsim  gf0 {args.gf0} wf0 {args.wf0} hill_gain {args.hill_gain} kv {args.kv} grade {args.grade_src} ' +
         f'atarget {meta["command_source"]} seed {args.seed}\n' +
         f'# plant: step {STEP:.3f} s1 {S1:.3f} s2 {S2:.3f} r0 {R0:+.3f} r2 {R2:+.6f} tau1 {TAU1} lag 0.68->0.48 s hill_k up/down {HILL_K[0]}/{HILL_K[1]}\n' +
         '# pk_over: peak v - vset (mph); t>+1mph: s above set + 1 mph; climb_und: lowest v - vset on grade > 1 deg (mph)\n' +
         '# rms(a-aT): true accel - accel cmd; jerk_rms: of 0.15 s-filtered a (m/s^3); t_gas_sat: s at GAS 750\n')
  (args.out / 'table.txt').write_text(hdr + table + '\n')
  S = [{'scenario': s, 'variant': v, **{k: (None if isinstance(x, float) and math.isnan(x) else x) for k, x in m.items()}}
       for s, v, m in rows]
  (args.out / 'summary.json').write_text(json.dumps({'meta': meta, 'rows': S}, indent=1, default=str))
  (args.out / 'traces.json').write_text(json.dumps(traces))
  (args.out / 'index.html').write_text(index_html(meta, S, traces))
  print(hdr + table)
  print(f'wrote index.html, summary.json, table.txt, traces.json to {args.out}', file=sys.stderr)
  return 0


if __name__ == '__main__':
  sys.exit(main())
