"""Live lateral timing estimator for the Honda EPS controller (timing standard §8d, shadow mode).

The standard is docs/research/lateral-timing-standard-draft-2026-10-26.md on ns-bosch-radar-testing. In short:
  - a turning window is engaged, hands-off (no steeringPressed within 1 s), 5-12 m/s, with the plan's curvature now or
    0.5 s ahead above 0.006 1/m, from each such model frame to 1.5 s after it (D9);
  - each window is fitted on its own for the lag of every stage (published action -> controlsd target curvature, the
    controller's angle target -> wheel angle, wheel -> yaw curvature, ...): least squares over -0.5..+0.5 s with the
    gain fitted and the minimum refined between samples, kept when the fit is >= 0.6 and not at the search edge;
  - the slow composite S = ramp + target->wheel + wheel->yaw, with target->wheel corrected for the size of the turn
    (-20 ms per e-fold of the target's angle rate, against 30 deg/s), is learned per speed band (5-9, 9-15 m/s);
  - S converges, freezes and is monitored: frozen at >= 50 turns over >= 3 drives with the two halves (alternate turns)
    within 15 ms; after the freeze nothing moves, and the band is flagged stale (and re-learned) when the median of
    the last 50 turns is more than 30 ms from the frozen value;
  - each model's aim T* (the plan horizon its unsmoothed action matches, on steep frames) is learned as the offset
    T* - 0.55 * told delay, frozen per model after 2000 frames with halves within 15 ms.

This module is numpy only, so it runs on the device and in replay alike. The turn search is the offline one
(scratchpad turns.py / robust.py of the standard's evidence) run on buffered streams, so the device and the offline
replay produce the same turns.
"""
import json
import math
import os
import tempfile

import numpy as np

VERSION = 1
DT = 0.01
T_IDXS = np.array([10.0 * (i / 32) ** 2 for i in range(33)])   # ModelConstants.T_IDXS

# turning windows (D9)
V_MIN, V_MAX = 5.0, 12.0
K_TURN = 0.006
WINDOW_AFTER_FRAME = 1.5
PRESSED_PAD = 100               # carState samples either side of a steeringPressed sample (~1 s at 100 Hz)
HOLE_GAP = 0.5                  # a carState gap longer than this is a hole
MIN_WINDOW = 200                # samples
WINDOW_PAD = 50
MAX_LAG = 0.5
MIN_FIT = 0.6
SMOOTH = 10                     # samples, box filter before fitting

# learning
BANDS = ((5.0, 9.0), (9.0, 15.0))
SIZE_COEF = 0.020               # s per e-fold of target angle rate
SIZE_REF = 30.0                 # deg/s
FREEZE_TURNS = 50
FREEZE_DRIVES = 3
FREEZE_SPLIT = 0.015
MONITOR_TURNS = 50
STALE = 0.030
MAX_LEARNING_TURNS = 400
AIM_SLOPE = 0.55
AIM_FREEZE_FRAMES = 2000
AIM_SPLIT = 0.015
MAX_AIM_FRAMES = 4000
YAW_SENSOR = 0.002
TOLD_EXTRA = 0.075              # lat_action_t = epsModelDelay (schedule + smoothing) + 0.050 + 0.025


def band_name(v: float) -> str | None:
  for lo, hi in BANDS:
    if lo <= v < hi:
      return f"{lo:g}-{hi:g}"
  return None


def ema_delay(lss: float) -> float:
  """T2: the group delay of modeld's per-frame EMA with time constant lss at 20 Hz."""
  if lss <= 0:
    return 0.0
  a = 1 - math.exp(-0.05 / lss)
  return (1 - a) / a * 0.05


def size_correction(target_rate_rms: float) -> float:
  return SIZE_COEF * math.log(max(target_rate_rms, 1e-3) / SIZE_REF)


# ---------------------------------------------------------------------------------------------------------------
# per-window lag fit (robust.py)

def windows(mask: np.ndarray, min_len: int = MIN_WINDOW, pad: int = WINDOW_PAD) -> list[tuple[int, int]]:
  idx = np.flatnonzero(mask)
  if not len(idx):
    return []
  out = []
  for seg in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
    if len(seg) >= min_len:
      out.append((max(seg[0] - pad, 0), seg[-1] + pad))
  return out


def lag_one(x: np.ndarray, y: np.ndarray, lags: np.ndarray) -> tuple[float, float, bool]:
  e = []
  for L in lags:
    a, b = (x[:len(x) - L], y[L:]) if L >= 0 else (x[-L:], y[:len(y) + L])
    a = a - a.mean()
    b = b - b.mean()
    g = np.dot(a, b) / max(np.dot(a, a), 1e-12)
    e.append(np.mean((b - g * a) ** 2) / max(np.mean(b ** 2), 1e-12))
  e = np.array(e)
  i = int(np.argmin(e))
  d = 0.0
  if 0 < i < len(e) - 1:
    den = e[i - 1] - 2 * e[i] + e[i + 1]
    d = (e[i - 1] - e[i + 1]) / (2 * den) if den > 0 else 0.0
  return (lags[i] + d) * DT, 1 - e[i], i in (0, len(e) - 1)


def fit_window(x: np.ndarray, y: np.ndarray, a: int, b: int) -> tuple[int, int, float, float] | None:
  """The lag of y behind x over window [a, b] (indices into x and y), or None when the fit is rejected."""
  L = int(MAX_LAG / DT)
  a0, b0 = max(a, L), min(b, len(x) - L - 1)
  if b0 - a0 < 150:
    return None
  lag, fit, edge = lag_one(x[a0 - L:b0 + L], y[a0 - L:b0 + L], np.arange(-L, L + 1))
  if fit >= MIN_FIT and not edge and np.isfinite(lag):
    return a0, b0, float(lag), float(fit)
  return None


def smooth(z: np.ndarray) -> np.ndarray:
  return np.convolve(np.nan_to_num(z), np.ones(SMOOTH) / SMOOTH, 'same')


# ---------------------------------------------------------------------------------------------------------------
# streams

class Rows:
  """A growable float array of fixed-width rows, first column the time (s), trimmed from the front."""
  def __init__(self, width: int, capacity: int = 4096):
    self.a = np.empty((capacity, width))
    self.n = 0

  def append(self, row) -> None:
    if self.n == len(self.a):
      self.a = np.concatenate([self.a, np.empty_like(self.a)])
    self.a[self.n] = row
    self.n += 1

  def __len__(self) -> int:
    return self.n

  @property
  def view(self) -> np.ndarray:
    return self.a[:self.n]

  def trim(self, t_min: float) -> None:
    i = int(np.searchsorted(self.a[:self.n, 0], t_min))
    if i:
      self.a[:self.n - i] = self.a[i:self.n]
      self.n -= i


class Streams:
  """Raw timestamped samples (s, logMonoTime), one row per message."""
  def __init__(self):
    self.cs = Rows(6)      # carState: t, vEgo, steeringAngleDeg, steeringPressed, yawRate (rad/s),
                           #   receipt time of the CAN packet it was decoded from
    self.cc = Rows(2)      # carControl: t, latActive
    self.ctl = Rows(3)     # controlsState: t, desiredCurvature, angle target (deg)
    self.lp = Rows(3)      # vehicleParameters: t, angleOffsetDeg, roll
    self.md = Rows(3)      # starpilotLateralState: t, epsModelDelay, epsCommandDelay
    self.model = Rows(102, 1024)   # modelV2: tp, tf, action, orientation.z[33], orientationRate.z[33], velocity.x[33]

  def trim(self, t_min: float) -> None:
    for rows in (self.cs, self.cc, self.ctl, self.lp, self.md, self.model):
      rows.trim(t_min)


def _model_arrays(m: np.ndarray):
  return m[:, 0], m[:, 1], m[:, 2], m[:, 3:36], m[:, 36:69], m[:, 69:102]


def frame_aims(tp, act, yaws, rates, vx, vf, ok, lss):
  """T* per model frame (nan where the frame is not steep or no crossing): the first T at which the curvature the plan
  implies over [0, T], 2 psi(T) / (v T) - psidot(0) / v, equals the unsmoothed action (D5)."""
  a = 1 - math.exp(-0.05 / lss) if lss > 0 else 1.0
  raw = np.r_[act[:1], (act[1:] - (1 - a) * act[:-1]) / a]
  Tg = np.linspace(0.05, 2.0, 79)
  vv = np.clip(vf, 1.0, None)[:, None]
  psi = np.array([np.interp(Tg, T_IDXS, r) for r in yaws]) if len(yaws) else np.zeros((0, len(Tg)))
  K = 2 * psi / (vv * Tg[None, :]) - rates[:, :1] / vv
  dK = np.median(np.abs(np.gradient(K, Tg, axis=1))[:, 4:40], axis=1) if len(K) else np.zeros(0)
  steep = (dK * np.clip(vf, 1, None) ** 2 > 0.3) & ok & (vf > 3)
  aim = np.full(len(tp), np.nan)
  for i in np.flatnonzero(steep):
    k, r = K[i], raw[i]
    j = np.flatnonzero(np.diff(np.sign(k - r)) != 0)
    if len(j):
      j = j[0]
      f = (r - k[j]) / (k[j + 1] - k[j]) if k[j + 1] != k[j] else 0.0
      aim[i] = Tg[j] + f * (Tg[j + 1] - Tg[j])
  return aim


def find_turns(s: Streams, conv, lss: float, closed_before: float, open_after: float = -math.inf,
               aim_from: float = -math.inf):
  """Every turning window of the buffered streams that is complete (its last sample, with the fit's padding, before
  closed_before) and starts after open_after, with its per-stage lags. conv(angle_deg[], v[], offset[], roll[]) ->
  curvature[] is the car's rack map. Also returns the per-frame aims of the model frames in the buffer (computed only
  from aim_from on; earlier frames are nan, which the caller has already used)."""
  if len(s.cs) < 400 or len(s.model) < 40 or len(s.ctl) < 100 or len(s.cc) < 10:
    return [], None
  CS, CC, CTL, LP, MD = s.cs.view, s.cc.view, s.ctl.view, s.lp.view, s.md.view
  tp, tf, act, yaws, rates, vx = _model_arrays(s.model.view)

  # the grid is locked to carState's phase, the ticks controlsd runs on (so the held 20 Hz action steps where controlsd
  # sees it step), and stays put as the buffer is trimmed
  phase = float(np.median(np.mod(CS[:, 0], DT)))
  g = np.arange(math.ceil((CS[0, 0] + 2 - phase) / DT) * DT + phase, CS[-1, 0] - 2, DT)
  if len(g) < 400:
    return [], None
  hole = np.zeros(len(g), bool)
  for i in np.flatnonzero(np.diff(CS[:, 0]) > HOLE_GAP):
    hole |= (g > CS[i, 0] - 0.5) & (g < CS[i + 1, 0] + 2.0)
  v = np.interp(g, CS[:, 0], CS[:, 1])
  ang = np.interp(g, CS[:, 0], CS[:, 2])
  lat = np.interp(g, CC[:, 0], CC[:, 1])
  if len(LP):
    off, roll = np.interp(g, LP[:, 0], LP[:, 1]), np.interp(g, LP[:, 0], LP[:, 2])
  else:
    off, roll = np.zeros(len(g)), np.zeros(len(g))
  # car curvature from the VSA yaw rate, timestamped at the CAN receipt minus the sensor's 2 ms (D7)
  Y = np.interp(g, CS[:, 5] - YAW_SENSOR, CS[:, 4]) / np.maximum(v, 0.5)
  A = act[np.clip(np.searchsorted(tp, g, side='right') - 1, 0, None)]
  C = np.interp(g, CTL[:, 0], CTL[:, 1])
  tgt = np.interp(g, CTL[:, 0], CTL[:, 2])
  has_tgt = np.isfinite(CTL[:, 2]).mean() > 0.9
  W, T = conv(ang - off, v, roll), conv(np.nan_to_num(tgt) - off, v, roll)

  vf = np.interp(tp, CS[:, 0], CS[:, 1])
  eng = np.interp(tp, CC[:, 0], CC[:, 1]) > 0.5
  pressed = np.convolve(CS[:, 3], np.ones(2 * PRESSED_PAD), 'same') > 0
  pr = np.interp(tp, CS[:, 0], pressed.astype(float)) > 0.5
  kplan = rates / np.maximum(vx, 1.0)
  k_now = np.abs(kplan[:, 0])
  j = int(np.searchsorted(T_IDXS, 0.5))
  w = (0.5 - T_IDXS[j - 1]) / (T_IDXS[j] - T_IDXS[j - 1])
  k_ahead = np.abs(kplan[:, j - 1] * (1 - w) + kplan[:, j] * w)   # np.interp(0.5, T_IDXS, row) for every row
  sel = eng & ~pr & (np.maximum(k_now, k_ahead) > K_TURN) & (vf > V_MIN) & (vf < V_MAX)
  # every selected frame covers [tf, tf + 1.5 s] (inclusive): mark starts and ends, then count coverage
  cover = np.zeros(len(g) + 1, int)
  np.add.at(cover, np.searchsorted(g, tf[sel], side='left'), 1)
  np.add.at(cover, np.searchsorted(g, tf[sel] + WINDOW_AFTER_FRAME, side='right'), -1)
  mask = np.cumsum(cover[:-1]) > 0
  mask &= ~hole & (lat > 0.5)

  told = np.interp(tp, MD[:, 0], MD[:, 1]) + TOLD_EXTRA if len(MD) else np.full(len(tp), np.nan)
  aim = np.full(len(tp), np.nan)
  i0 = max(int(np.searchsorted(tp, aim_from)), 1)   # the first frame has no previous one to un-smooth against
  if i0 < len(tp):
    aim[i0:] = frame_aims(tp[i0 - 1:], act[i0 - 1:], yaws[i0 - 1:], rates[i0 - 1:], vx[i0 - 1:], vf[i0 - 1:],
                          (eng & ~pr)[i0 - 1:], lss)[1:]
  cmd = np.interp(g, MD[:, 0], MD[:, 2]) if len(MD) else np.full(len(g), np.nan)

  stages = {'ramp': (A, C), 'cmd': (C, T), 'tw': (T, W), 'wy': (W, Y), 'ay': (A, Y)}
  sm = {k: (smooth(x), smooth(y)) for k, (x, y) in stages.items() if has_tgt or k not in ('cmd', 'tw')}
  pub = float(np.median(tp - tf))
  L = int(MAX_LAG / DT)
  turns = []
  for a, b in windows(mask):
    # complete: the fit reads up to b + L; open: the window starts after what was already searched
    if b + L >= len(g) or g[min(b + L, len(g) - 1)] >= closed_before or g[a] <= open_after or a - L < 0:
      continue
    fits = {}
    for k, (x, y) in sm.items():
      r = fit_window(x, y, a, b)
      if r is not None:
        fits[k] = r
    if 'ay' not in fits:   # still reported, so the caller does not search it again
      turns.append(dict(win_start=float(g[a]), rejected=True))
      continue
    a0, b0 = fits['ay'][0], fits['ay'][1]
    t0, t1 = g[a0], g[b0]
    fm = (tf >= t0 - 0.5) & (tf <= t1)
    ta = tgt[a0:b0]
    rate = float(np.sqrt(np.mean((np.gradient(ta) / DT) ** 2))) if has_tgt else float('nan')
    rec = dict(win_start=float(g[a]), rejected=False, t0=float(t0), t1=float(t1), v=float(np.median(v[a0:b0])), pub=pub, lss=lss,
               cmd_applied=float(np.nanmedian(cmd[a0:b0])) if np.isfinite(cmd[a0:b0]).any() else None,
               told=float(np.nanmedian(told[fm])) if np.isfinite(told[fm]).any() else None,
               aim=float(np.nanmedian(aim[fm])) if np.isfinite(aim[fm]).any() else None,
               n_aim=int(np.isfinite(aim[fm]).sum()), tgt_rate=rate)
    for k in ('ramp', 'cmd', 'tw', 'wy', 'ay'):
      r = fits.get(k)
      ok = r is not None and r[0] == a0 and r[1] == b0
      rec[k] = r[2] if ok else None
      rec[k + '_fit'] = r[3] if ok else None
    turns.append(rec)
  frames = dict(tp=tp, tf=tf, told=told, aim=aim)
  return turns, frames


def slow_composite(rec: dict) -> float | None:
  """S for one turn: ramp + size-corrected target -> wheel + wheel -> yaw; None unless all three fitted."""
  if rec.get('ramp') is None or rec.get('tw') is None or rec.get('wy') is None or not np.isfinite(rec.get('tgt_rate', np.nan)):
    return None
  return rec['ramp'] + rec['tw'] + size_correction(rec['tgt_rate']) + rec['wy']


# ---------------------------------------------------------------------------------------------------------------
# learning: converge, freeze, monitor

def _split_ok(xs: list, tol: float) -> bool:
  a, b = xs[0::2], xs[1::2]
  return len(a) > 0 and len(b) > 0 and abs(float(np.median(a)) - float(np.median(b))) <= tol


def _se(xs) -> float:
  x = np.asarray(xs, float)
  if len(x) < 2:
    return float('nan')
  q1, q3 = np.percentile(x, [25, 75])
  return float(1.25 * (q3 - q1) / 1.35 / math.sqrt(len(x)))


class BandLearner:
  """S for one speed band."""
  def __init__(self, d: dict | None = None):
    d = d or {}
    self.turns: list = d.get('turns', [])          # [S, drive] while learning
    self.frozen: dict | None = d.get('frozen')     # {value, n, drives, se}
    self.monitor: list = d.get('monitor', [])      # S of the turns since the freeze (last MONITOR_TURNS)
    self.stale_count: int = d.get('stale_count', 0)

  def to_dict(self) -> dict:
    return dict(turns=self.turns, frozen=self.frozen, monitor=self.monitor, stale_count=self.stale_count)

  @property
  def state(self) -> str:
    return 'frozen' if self.frozen is not None else 'learning'

  def add(self, S: float, drive: str) -> str | None:
    """Add one turn; returns an event name ('frozen', 'stale') when the band changes state."""
    if self.frozen is None:
      self.turns.append([float(S), drive])
      del self.turns[:-MAX_LEARNING_TURNS]
      xs = [x for x, _ in self.turns]
      drives = {d for _, d in self.turns}
      if len(xs) >= FREEZE_TURNS and len(drives) >= FREEZE_DRIVES and _split_ok(xs, FREEZE_SPLIT):
        self.frozen = dict(value=float(np.median(xs)), n=len(xs), drives=len(drives), se=_se(xs))
        self.monitor = []
        return 'frozen'
      return None
    self.monitor.append(float(S))
    del self.monitor[:-MONITOR_TURNS]
    if len(self.monitor) >= MONITOR_TURNS and abs(float(np.median(self.monitor)) - self.frozen['value']) > STALE:
      self.stale_count += 1
      self.turns, self.frozen, self.monitor = [], None, []
      return 'stale'
    return None

  def estimate(self) -> dict:
    xs = [x for x, _ in self.turns]
    out = dict(state=self.state, n=len(xs), drives=len({d for _, d in self.turns}), stale_count=self.stale_count,
               running=float(np.median(xs)) if xs else None, running_se=_se(xs) if xs else None)
    if self.frozen is not None:
      out.update(value=self.frozen['value'], se=self.frozen['se'], frozen_n=self.frozen['n'],
                 frozen_drives=self.frozen['drives'], monitor_n=len(self.monitor),
                 monitor=float(np.median(self.monitor)) if self.monitor else None)
    return out


class AimLearner:
  """One model's aim offset T* - AIM_SLOPE * told."""
  def __init__(self, d: dict | None = None):
    d = d or {}
    self.offsets: list = d.get('offsets', [])
    self.frozen: float | None = d.get('frozen')

  def to_dict(self) -> dict:
    return dict(offsets=self.offsets, frozen=self.frozen)

  def add(self, offsets) -> bool:
    if self.frozen is not None:
      return False
    self.offsets += [round(float(o), 4) for o in offsets]
    del self.offsets[:-MAX_AIM_FRAMES]
    if len(self.offsets) >= AIM_FREEZE_FRAMES and _split_ok(self.offsets, AIM_SPLIT):
      self.frozen = float(np.median(self.offsets))
      return True
    return False

  def estimate(self) -> dict:
    return dict(state='frozen' if self.frozen is not None else 'learning', n=len(self.offsets),
                offset=self.frozen if self.frozen is not None else (float(np.median(self.offsets)) if self.offsets else None))


class TimingLearner:
  """Everything the estimator keeps across drives. `keys` identify what S depends on (fingerprint, EPS firmware,
  calibration, controller settings, controller code, device); any change resets the bands. Models do not reset S."""
  def __init__(self, keys: dict, d: dict | None = None):
    d = d if d is not None and d.get('version') == VERSION else {}
    self.reset_reason = None
    if d and d.get('keys') != keys:
      changed = sorted(k for k in set(keys) | set(d.get('keys', {})) if keys.get(k) != d.get('keys', {}).get(k))
      self.reset_reason = 'changed: ' + ', '.join(changed)
      d = {'aims': d.get('aims', {})}   # a model's aim is the model's own: no car-side change touches it
    self.keys = keys
    self.bands = {band_name(lo): BandLearner(d.get('bands', {}).get(band_name(lo))) for lo, _ in BANDS}
    self.aims = {k: AimLearner(v) for k, v in d.get('aims', {}).items()}
    self.drives = int(d.get('drives', 0))

  def to_dict(self) -> dict:
    return dict(version=VERSION, keys=self.keys, drives=self.drives,
                bands={k: b.to_dict() for k, b in self.bands.items()}, aims={k: a.to_dict() for k, a in self.aims.items()})

  def add_turn(self, rec: dict, drive: str) -> str | None:
    S = slow_composite(rec)
    name = band_name(rec['v'])
    if S is None or name is None:
      return None
    return self.bands[name].add(S, drive)

  def add_aims(self, model: str, offsets) -> bool:
    if model not in self.aims:
      self.aims[model] = AimLearner()
    return self.aims[model].add(offsets)

  def estimate(self, model: str | None, source: str, t1: float, lss: float, told_now: dict) -> dict:
    """What the estimator would set now. told_now: band name -> the told delay running in that band (s)."""
    out = {'bands': {}, 'model': model, 'source': source, 't1': t1, 't2': ema_delay(lss)}
    aim = self.aims.get(model).estimate() if model in self.aims else None
    out['aim'] = aim
    for name, b in self.bands.items():
      e = b.estimate()
      told = told_now.get(name)
      # frozen values are what the estimator would set; running ones are shown while it learns (shadow mode)
      for S, suffix in ((e.get('value'), ''), (e.get('running'), '_running')):
        if S is None or not np.isfinite(t1):
          continue
        delivery = t1 + ema_delay(lss) + S + YAW_SENSOR
        e['delivery' + suffix] = delivery
        e['plan_told' + suffix] = delivery
        if aim is not None and aim['offset'] is not None and told is not None:
          e['head_cmd_delay' + suffix] = aim['offset'] + AIM_SLOPE * told - delivery
      out['bands'][name] = e
    return out


def load_state(path: str) -> dict | None:
  try:
    with open(path) as f:
      return json.load(f)
  except (OSError, ValueError):
    return None


def save_state(path: str, d: dict) -> None:
  os.makedirs(os.path.dirname(path), exist_ok=True)
  fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.state')
  with os.fdopen(fd, 'w') as f:
    json.dump(d, f, separators=(',', ':'))
  os.replace(tmp, path)
