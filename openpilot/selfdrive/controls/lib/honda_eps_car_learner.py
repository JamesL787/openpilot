"""Converge-and-freeze learner for the CAR half of a HondaEps (LatControlHondaEps) calibration, run in shadow.

The firmware half of an EpsFirmwareCalibration is read from the PTM image. The car half (column load, rack map, yaw
decode, delays) has been fitted offline from owner rlogs with tools/lateral/*. This does the same fits on the device from
60 s chunks and FREEZES each part once enough well-conditioned data agrees with itself. Nothing here reaches the
controller: the result is published for review (honda_eps_learnerd).
Design, freeze criteria and replay results: tools/lateral/CAR_LEARNER_DESIGN.md and CAR_LEARNER_REPLAY.md.

Only numpy and the controller's own modules here (no messaging, no params), so the replay tool drives exactly this code:
  learner = HondaEpsCarLearner(cal, wheelbase, vgr_inverse, yaw_calibration)
  learner.add_chunk(chunk)   # per-frame arrays, see CHUNK_FIELDS; one call per <= 60 s of frames
  learner.result()           # per part: state, progress, reason, frozen value or current candidate
  blob = learner.to_bytes(); HondaEpsCarLearner.from_bytes(blob, ...)
"""
import dataclasses
import io
import json

import numpy as np

from opendbc.car.honda.yaw_rate import RIGHT_LOSS_BP
from openpilot.selfdrive.controls.lib import honda_eps_firmware_ff as eps_ff
from openpilot.selfdrive.controls.lib.honda_eps_column_plant import OPEN_LOOP_FRAMES, Plant, open_loop_window
from openpilot.selfdrive.controls.lib.honda_eps_driver_yield import TORQUE_SENSOR_DEFAULT, DriverYield
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import GRAVITY, HondaEpsRackMap

LEARNER_VERSION = 4
CHUNK_S = 60.0
DT = 0.01

# Per carState frame (100 Hz). A chunk also carries 'model' (rows of t, timestampEof, action desired curvature and the
# 33 plan orientationRate.z / velocity.x values, one per modelV2) and 'gps' (rows of t, bearing deg, speed, bearing
# accuracy deg, one per fix).
CHUNK_FIELDS = (
  't', 'v', 'a', 'ang', 'rate', 'tq', 'pressed', 'blinker', 'lat', 'e4', 'off', 'roll', 'eps_ok',
  'yawc',       # VSA yaw, 0x94 counts from the standstill zero, clockwise-positive; NaN without the sensor
  'act',        # model action desired curvature
  'cmd_delay',  # the command delay the controller ran (starpilotLateralState.epsCommandDelay)
)


def smooth(x, n):
  return np.convolve(x, np.ones(n) / n, 'same')


def half_of(chunk_index):
  return chunk_index % 2


def pressed_recently(pressed, frames):
  """True where the driver-override detector fired within the last `frames` frames (this one included)."""
  return np.convolve(pressed > 0.5, np.ones(frames + 1))[:len(pressed)] > 0


def firmware_target(e4, v, rate, angle, cal):
  """The firmware output for the 0xE4 it was sent at the rate and angle the wheel had: the load fit's target."""
  return np.array([eps_ff.firmware_output(eps_ff.r5_from_output(-x / cal.e4_per_output, s, cal), r, cal, a)
                   for x, s, r, a in zip(e4, v, rate, angle, strict=True)])


def yaw_deg_s(counts, scale, right):
  """opendbc yaw_rate.yaw_rate_deg_s for arrays (clockwise-positive)."""
  lo, hi = RIGHT_LOSS_BP
  return counts * scale + right * np.clip((counts - lo) / (hi - lo), 0.0, 1.0)


def yaw_counts(yaw_rate, scale, right):
  """carState.yawRate (rad/s, left-positive) back to 0x94 counts from the zero, clockwise-positive."""
  lo, hi = RIGHT_LOSS_BP
  y = -np.degrees(np.asarray(yaw_rate, float))
  mid = (y + right * lo / (hi - lo)) / (scale + right / (hi - lo))
  return np.where(y <= lo * scale, y / scale, np.where(y >= hi * scale + right, (y - right) / scale, mid))


def jsonable(x):
  if isinstance(x, dict):
    return {str(k): jsonable(v) for k, v in x.items()}
  if isinstance(x, (list, tuple, np.ndarray)):
    return [jsonable(v) for v in x]
  if isinstance(x, (np.floating, float)):
    return float(x) if np.isfinite(x) else None
  if isinstance(x, (np.integer, np.bool_)):
    return x.item()
  return x


class Part:
  ARRAYS: tuple = ()
  META: tuple = ()
  frozen: dict | None = None

  def dump(self):
    return {k: getattr(self, k) for k in self.ARRAYS}, jsonable({k: getattr(self, k) for k in self.META + ('frozen',)})

  def restore(self, arrays, meta):
    for k in self.ARRAYS:
      if getattr(self, k).shape != arrays[k].shape:
        raise ValueError(k)
      setattr(self, k, arrays[k])
    for k in self.META + ('frozen',):
      setattr(self, k, meta[k])


# ---------------------------------------------------------------------------------------------------------------
# column load

LOAD_NAMES = ('k0', 'k1', 'c', 'friction', 'j', 'bias', 'kroll', 'kd')
I_J, I_BIAS, I_KD = 4, 5, 7
LOAD_SHIFTS = 5                      # motion shifted 0-40 ms, the recipe's lag search
LOAD_SPEED_EDGES = (1.0, 5.0, 9.0, 15.0, 25.0, 1e9)
LOAD_ANGLE_EDGES = (0.0, 5.0, 20.0, 60.0, 1e9)
# The recipe screened on |steeringTorque| < 300, which throws away most town driving of an owner who rests a hand on
# the wheel (both CR-Vs: 10-25% of unpressed frames at 5-9 m/s carry 600-1,900 counts; the press threshold is 2000).
# The driver's torque is a regressor instead (kd * steeringTorque, 0.54 / 0.58 firmware counts per count on the A220 /
# A040), with a cap that keeps a real override out. Frames in the fade-up after a press are left out as well.
LOAD_MAX_TORQUE = 1200.0
LOAD_MAX_RATE = 400.0
LOAD_FADE_MARGIN_S = 0.3
# The Coulomb knee at eps_ff.FRICTION_WIDTH_SPEED_BP. The recipe's 2 deg/s everywhere fits best, but on the A220 it
# makes the simulated column too stiff for small highway motions (open-loop wheel gain 0.81 at 20-40 m/s); the knee the
# feedforward itself runs above 15 m/s (5 deg/s) fits 0.02 R^2 worse and moves the wheel as the car did. The first
# candidate that passes the open-loop gate is taken.
LOAD_KNEES = ((2.0, 2.0), (2.0, 3.5), (2.0, 5.0))
# Sanity bounds over every column fitted so far (Clarity, C020, TEG, Insight, CR-V A040 / A220), widened ~2x. The
# target is rebuilt from 0xE4 through the calibration's R6, so an R6 error lands in c and may leave it mildly positive.
LOAD_BOUNDS = {'k0': (-25.0, -1.5), 'k1': (-0.45, -0.03), 'c': (-16.0, 6.0), 'friction': (-800.0, -80.0),
               'bias': (-160.0, 160.0), 'kroll': (-15.0, 5.0), 'kd': (-0.5, 2.0)}
LOAD_MIN_S = 15 * 60                 # accepted frames
LOAD_MIN_TURN_S = 45                 # of those with |angle| > 20 deg
LOAD_MIN_RATE_S = 30                 # ... with |rate| > 20 deg/s
LOAD_MIN_SPEED_BANDS = 3             # speed bands with >= 60 s each
# Each deployed term must be carried by the data: the prior's share of the information about it under a LOAD_PRIOR_S
# ridge below 25%. The inertia, roll and driver terms may stay prior-held (reported).
LOAD_IDENTIFIED_RATIO = 0.25
LOAD_MUST_IDENTIFY = ('k0', 'k1', 'c', 'friction', 'bias')
LOAD_SPLIT_TOL = 0.10                # split-half load surfaces agree within this fraction of the full fit's RMS
LOAD_CROSS_R2_TOL = 0.05             # each half's fit scores the other half within this R^2 of the other's own fit
LOAD_RIDGE_S = 5.0                   # ridge toward the shipped load, enough to hold a direction the drives never excite
LOAD_PRIOR_S = 120.0
LOAD_BUCKET_CAP_S = 1200.0           # no speed x angle cell weighs more than this (straight highway would swamp)
CHUNK_INCOHERENT_X = 4.0             # chunk rejected if its own best fit leaves > 4x the median chunk's residual
# Judged by regime, not by a pooled R^2 (which once hid a 10-27% under-ask at town turn-ins on the Clarity): the mean
# of (model - firmware) along the firmware output, as a share of |firmware|, in every turn-in / hold / unwind x speed
# cell with REGIME_MIN_S of frames. Each half's fit is scored on the other half; it may not be further from zero than
# the shipped load by more than REGIME_TOL in any cell.
REGIMES = ('turn-in', 'hold', 'unwind')
REGIME_SPEEDS = ('<8', '8-15', '15+')
REGIME_SPEED_EDGES = (8.0, 15.0)
REGIME_HOLD_RATE = 5.0
REGIME_MIN_S = 20.0
REGIME_TOL = 0.05
# Open loop: the column plant with the candidate load, driven by the logged 0xE4 over hands-off 20 s windows, must move
# the wheel as the car did at 0.6-2.5 Hz in both speed bands (tools/lateral/eps_closed_loop.py's check and defaults).
OL_BANDS = ((9.0, 20.0), (20.0, 40.0))
OL_WINDOWS = 16                      # kept per band, a uniform sample of those seen
OL_MIN_WINDOWS = 6
OL_GAIN = (0.85, 1.15)
OL_MAX_TORQUE = 600.0
OL_CMD_LAG = 2
OL_J = -0.9
OL_SENSOR_DELAY = 0.04
OL_RECHECK_CHUNKS = 15
# After the freeze: per usable chunk, the gain of the measured target on the frozen load's prediction. The first
# LOAD_MONITOR_CHUNKS set the baseline; the median of the last ones moving more than LOAD_STALE_GAIN from it marks the
# load stale (a reflash to another map, a changed column).
LOAD_MONITOR_CHUNKS = 15
LOAD_STALE_GAIN = 0.15
LOAD_MONITOR_MIN_STD = 60.0          # counts of predicted load


def scaled_solve(A, b):
  d = 1.0 / np.sqrt(np.abs(np.diag(A)))
  return d * np.linalg.solve(A * np.outer(d, d), b * d)


def ridge(XtX, n, prior_s):
  d = np.diag(XtX) / n
  return prior_s / DT * np.where(d > 1e-9, d, 1.0)


def load_regressors(th, thd, thdd, v, roll, tq=None, knee=None):
  """The fit_column_load recipe's regressors (that tool builds its own from this), plus the driver's torque."""
  width = 2.0 if knee is None else np.interp(v, eps_ff.FRICTION_WIDTH_SPEED_BP, knee)
  cols = [th, th * v ** 2, thd, np.tanh(thd / width), thdd, np.ones_like(th), roll * v ** 2]
  return np.column_stack(cols if tq is None else cols + [tq])


_G = np.array(np.meshgrid([-90.0, -30.0, -8.0, 0.0, 8.0, 30.0, 90.0], [-60.0, -15.0, -3.0, 0.0, 3.0, 15.0, 60.0],
                          [6.0, 12.0, 22.0], [-0.02, 0.0, 0.02])).reshape(4, -1).T


def load_surface(coef, knee):
  """The load over a fixed grid of motions: what split halves are compared on (c and friction trade against each other)."""
  th, thd, v, roll = _G.T
  return load_regressors(th, thd, np.zeros_like(th), v, roll, np.zeros_like(th), knee) @ coef


def regime_cells(th, thd, v):
  reg = np.where(np.abs(thd) < REGIME_HOLD_RATE, 1, np.where(th * thd > 0, 0, 2))
  return np.where(np.abs(th) > 0.5, reg * len(REGIME_SPEEDS) + np.searchsorted(REGIME_SPEED_EDGES, v, side='right'), -1)


class ColumnLoadLearner(Part):
  P = len(LOAD_NAMES)
  NB = (len(LOAD_SPEED_EDGES) - 1) * (len(LOAD_ANGLE_EDGES) - 1)
  NR = len(REGIMES) * len(REGIME_SPEEDS)
  ARRAYS = ('XtX', 'Xty', 'yty', 'ysum', 'n', 'rX', 'rabs', 'rn', 'ol_e4', 'ol_v', 'ol_roll', 'ol_ang', 'ol_rate0', 'ol_seen')
  META = ('turn_s', 'rate_s', 'chunk_rms', 'accepted', 'rejected', 'monitor_gain', 'monitor_base', 'ol_at', 'ol_gain')

  def __init__(self, cal, fade_up_s=eps_ff.OVERRIDE_FADE_UP_S_DEFAULT, seed=0):
    self.cal = cal
    self.fade_frames = int(round((fade_up_s + LOAD_FADE_MARGIN_S) / DT))
    load = cal.load
    self.prior = np.array([load.k0, load.k1, load.c, load.friction, 0.0, load.bias, load.kroll, 0.0])
    shape = (2, LOAD_SHIFTS, self.NB)
    K = len(LOAD_KNEES)
    self.XtX = np.zeros((K,) + shape + (self.P, self.P))
    self.Xty = np.zeros((K,) + shape + (self.P,))
    self.yty, self.ysum, self.n = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    self.rX = np.zeros((K, 2, LOAD_SHIFTS, self.NR, self.P))
    self.rabs, self.rn = np.zeros((2, LOAD_SHIFTS, self.NR)), np.zeros((2, LOAD_SHIFTS, self.NR))
    ol = (len(OL_BANDS), OL_WINDOWS, OPEN_LOOP_FRAMES)
    self.ol_e4, self.ol_ang = np.zeros(ol, np.int16), np.zeros(ol, np.int16)  # 0xE4 counts, angle in 0.01 deg
    self.ol_v, self.ol_roll = np.zeros(ol, np.float16), np.zeros(ol, np.float16)
    self.ol_rate0 = np.zeros(ol[:2], np.float32)
    self.ol_seen = np.zeros(len(OL_BANDS), np.int64)
    self.ol_at: dict[str, int] = {}          # knee index -> accepted chunks when the open-loop gate last ran
    self.ol_gain: dict[str, list] = {}       # ... and the gain it found per band
    self.rng = np.random.default_rng(seed)
    self.turn_s = self.rate_s = 0.0
    self.chunk_rms = []
    self.accepted = self.rejected = 0
    self.frozen = None
    self.passed: tuple[int, int] | None = None
    self.monitor_gain = []
    self.monitor_base = None

  # ---- per chunk
  def add_chunk(self, c, y, index):
    t, th = c['t'], c['ang'] - c['off']
    rate = smooth(c['rate'], 5)
    acc = smooth(np.gradient(rate, t), 5)
    clean = (c['lat'] > 0.5) & (c['eps_ok'] > 0.5) & ~pressed_recently(c['pressed'], self.fade_frames) & np.isfinite(y)
    gate = clean & (c['v'] > 1.0) & (np.abs(c['tq']) < LOAD_MAX_TORQUE) & (np.abs(c['rate']) < LOAD_MAX_RATE)
    idx = np.flatnonzero(gate)
    idx = idx[(idx > 5) & (idx + LOAD_SHIFTS < len(t) - 2)]
    if len(idx) < 500:
      return 'thin'
    if self.frozen is not None:
      return self._monitor(y, idx, th, rate, acc, c)
    self._keep_windows(c, clean)
    yy, tq = y[idx], c['tq'][idx]
    # coherence: the chunk's own least-squares residual, which no parameter value can make look better or worse
    X0 = load_regressors(th[idx], rate[idx], acc[idx], c['v'][idx], c['roll'][idx], tq)
    rms = float(np.sqrt(np.mean((yy - X0 @ np.linalg.lstsq(X0, yy, rcond=None)[0]) ** 2)))
    if len(self.chunk_rms) >= 5 and rms > CHUNK_INCOHERENT_X * float(np.median(self.chunk_rms)):
      self.rejected += 1
      return 'incoherent'
    self.chunk_rms = (self.chunk_rms + [rms])[-200:]
    self.accepted += 1
    h = half_of(index)
    vb = np.clip(np.searchsorted(LOAD_SPEED_EDGES, c['v'][idx], side='right') - 1, 0, len(LOAD_SPEED_EDGES) - 2)
    ab = np.clip(np.searchsorted(LOAD_ANGLE_EDGES, np.abs(th[idx]), side='right') - 1, 0, len(LOAD_ANGLE_EDGES) - 2)
    cell = vb * (len(LOAD_ANGLE_EDGES) - 1) + ab
    sign = np.sign(yy)
    for s in range(LOAD_SHIFTS):
      j = idx + s
      reg = regime_cells(th[j], rate[j], c['v'][j])
      for b in np.unique(cell):
        m = cell == b
        self.yty[h, s, b] += yy[m] @ yy[m]
        self.ysum[h, s, b] += yy[m].sum()
        self.n[h, s, b] += m.sum()
      for r in np.unique(reg[reg >= 0]):
        self.rabs[h, s, r] += np.abs(yy[reg == r]).sum()
        self.rn[h, s, r] += (reg == r).sum()
      for ki, knee in enumerate(LOAD_KNEES):
        X = load_regressors(th[j], rate[j], acc[j], c['v'][j], c['roll'][j], tq, knee)
        for b in np.unique(cell):
          m = cell == b
          self.XtX[ki, h, s, b] += X[m].T @ X[m]
          self.Xty[ki, h, s, b] += X[m].T @ yy[m]
        for r in np.unique(reg[reg >= 0]):
          self.rX[ki, h, s, r] += sign[reg == r] @ X[reg == r]
    self.turn_s += np.sum(np.abs(th[idx]) > 20) * DT
    self.rate_s += np.sum(np.abs(c['rate'][idx]) > 20) * DT
    return 'accepted'

  def _keep_windows(self, c, clean):
    ok = np.r_[clean & (c['v'] > 3.0) & (np.abs(c['tq']) < OL_MAX_TORQUE), False]
    edges = np.flatnonzero(np.diff(np.r_[False, ok].astype(int)))
    for s, e in zip(edges[::2], edges[1::2], strict=True):
      for a in range(s + OL_CMD_LAG, e - OPEN_LOOP_FRAMES + 1, OPEN_LOOP_FRAMES):
        w = slice(a, a + OPEN_LOOP_FRAMES)
        v = float(c['v'][w].mean())
        for bi, (lo, hi) in enumerate(OL_BANDS):
          if lo <= v < hi:
            seen = int(self.ol_seen[bi])
            self.ol_seen[bi] += 1
            slot = seen if seen < OL_WINDOWS else int(self.rng.integers(0, seen + 1))
            if slot < OL_WINDOWS:
              self.ol_e4[bi, slot] = c['e4'][a - OL_CMD_LAG:a + OPEN_LOOP_FRAMES - OL_CMD_LAG]
              self.ol_v[bi, slot], self.ol_roll[bi, slot] = c['v'][w], c['roll'][w]
              self.ol_ang[bi, slot] = np.clip(np.round(c['ang'][w] * 100.0), -32767, 32767)
              self.ol_rate0[bi, slot] = c['rate'][a]

  # ---- solving
  def _stats(self, ki, halves, s, capped=True):
    h = list(halves)
    n = self.n[h, s].sum(0)
    w = np.minimum(1.0, LOAD_BUCKET_CAP_S / DT / np.maximum(n, 1.0)) if capped else np.ones_like(n)
    return (np.tensordot(w, self.XtX[ki, h, s].sum(0), axes=(0, 0)), np.tensordot(w, self.Xty[ki, h, s].sum(0), axes=(0, 0)),
            float(w @ self.yty[h, s].sum(0)), float(w @ self.ysum[h, s].sum(0)), float(w @ n))

  def solve(self, halves=(0, 1), s=None, ki=0, capped=True, prior_s=LOAD_RIDGE_S):
    s = self.best_shift(halves) if s is None else s
    XtX, Xty, _, _, n = self._stats(ki, halves, s, capped)
    if n < 1:
      return self.prior.copy()
    lam = ridge(XtX, n, prior_s) + (np.diag(XtX) <= 0)  # a term the drives never moved (no roll estimate) stays the prior's
    return scaled_solve(XtX + np.diag(lam), Xty + lam * self.prior)

  def r2(self, coef, halves, s, ki=0):
    XtX, Xty, yty, ysum, n = self._stats(ki, halves, s, capped=False)
    return 1.0 - (yty - 2 * coef @ Xty + coef @ XtX @ coef) / max(yty - ysum ** 2 / max(n, 1), 1e-9)

  def best_shift(self, halves=(0, 1)):
    scores = [self.r2(self.solve(halves, s, capped=False, prior_s=0.0), halves, s) if self.n[list(halves), s].sum() > 0 else -1
              for s in range(LOAD_SHIFTS)]
    return int(np.argmax(scores))

  def tq_mean(self, s):
    XtX, _, _, _, n = self._stats(0, (0, 1), s, capped=False)
    return float(XtX[I_BIAS, I_KD] / max(n, 1.0))

  def model(self, coef, s):
    """The deployable load. The fitted bias is the one at zero driver torque; the torque sensor has an offset and a
    resting hand a mean, so the load takes the bias at the mean torque, as the recipe's own bias is."""
    k0, k1, c, friction, _, bias, kroll, kd = (float(x) for x in coef)
    return eps_ff.ColumnLoadModel(k0=k0, k1=k1, c=c, friction=friction, bias=bias + kd * self.tq_mean(s), kroll=kroll)

  def identified(self, s, ki=0):
    """Posterior / prior variance per term under the ridge (smaller = more of it from data)."""
    XtX, _, _, _, n = self._stats(ki, (0, 1), s)
    lam = ridge(XtX, max(n, 1.0), LOAD_PRIOR_S)
    A = XtX + np.diag(lam)
    d = 1.0 / np.sqrt(np.diag(A))
    return dict(zip(LOAD_NAMES, np.diag(np.linalg.inv(A * np.outer(d, d))) * d * d * lam, strict=True))

  def shipped(self, kd, s):
    """The shipped load as coefficients, given the driver term of the fit it is compared with."""
    ship = self.prior.copy()
    ship[I_KD], ship[I_BIAS] = kd, self.prior[I_BIAS] - kd * self.tq_mean(s)
    return ship

  def regimes(self, s, ki, given=None):
    """{regime speed: (s, shipped error, fitted error)}. The fit is each half's, scored on the other half, or `given`
    coefficients scored on everything here (a load frozen earlier, on later drives)."""
    ship = self.shipped(float((self.solve(s=s, ki=ki) if given is None else given)[I_KD]), s)
    fit_num, ship_num = np.zeros(self.NR), np.zeros(self.NR)
    for h in (0, 1):
      coef = np.array(self.solve((1 - h,), s, ki) if given is None else given, float)
      coef[I_J] = 0.0  # not deployed
      fit_num += self.rX[ki, h, s] @ coef - self.rabs[h, s]
      ship_num += self.rX[ki, h, s] @ ship - self.rabs[h, s]
    den, n = self.rabs[:, s].sum(0), self.rn[:, s].sum(0) * DT
    return {f'{REGIMES[i // 3]} {REGIME_SPEEDS[i % 3]}': (float(n[i]), float(ship_num[i] / den[i]), float(fit_num[i] / den[i]))
            for i in range(self.NR) if n[i] >= REGIME_MIN_S and den[i] > 0}

  def open_loop(self, coef, s, ki):
    """Median 0.6-2.5 Hz wheel gain, simulated / measured, per OL_BANDS."""
    plant = Plant(dataclasses.replace(self.cal, load=self.model(coef, s)), OL_J, OL_SENSOR_DELAY, LOAD_KNEES[ki])
    out = []
    for bi in range(len(OL_BANDS)):
      n = int(min(self.ol_seen[bi], OL_WINDOWS))
      gains = [open_loop_window(plant, self.ol_e4[bi, i], self.ol_v[bi, i], self.ol_roll[bi, i], self.ol_ang[bi, i] * 0.01, self.ol_rate0[bi, i])[0]
               for i in range(n)]
      out.append(float(np.median(gains)) if gains else float('nan'))
    return out

  # ---- convergence
  def coverage(self):
    n = self.n[:, 0].sum(0).reshape(len(LOAD_SPEED_EDGES) - 1, len(LOAD_ANGLE_EDGES) - 1) * DT
    return {'accepted_s': float(n.sum()), 'turn_s': float(self.turn_s), 'rate_s': float(self.rate_s),
            'speed_bands': int(np.sum(n.sum(1) >= 60)), 'windows': [int(min(x, OL_WINDOWS)) for x in self.ol_seen]}

  def check(self):
    cov = self.coverage()
    needs = {f"{cov['accepted_s'] / 60:.0f}/{LOAD_MIN_S / 60:.0f} min": cov['accepted_s'] / LOAD_MIN_S,
             f"{cov['turn_s']:.0f}/{LOAD_MIN_TURN_S} s past 20 deg": cov['turn_s'] / LOAD_MIN_TURN_S,
             f"{cov['rate_s']:.0f}/{LOAD_MIN_RATE_S} s past 20 deg/s": cov['rate_s'] / LOAD_MIN_RATE_S,
             f"{cov['speed_bands']}/{LOAD_MIN_SPEED_BANDS} speed bands": cov['speed_bands'] / LOAD_MIN_SPEED_BANDS}
    for (lo, hi), n in zip(OL_BANDS, cov['windows'], strict=True):
      needs[f'{n}/{OL_MIN_WINDOWS} hands-off 20 s windows at {lo:.0f}-{hi:.0f} m/s'] = n / OL_MIN_WINDOWS
    progress = min(1.0, *needs.values())
    if progress < 1.0:
      return False, progress, 'coverage: ' + ', '.join(k for k, x in needs.items() if x < 1.0)
    s = self.best_shift()
    why = ''
    for ki in range(len(LOAD_KNEES)):
      ok, why, widen = self._check_knee(s, ki)
      if ok:
        self.passed = (s, ki)
        return True, 1.0, why
      if not widen:
        break
    return False, 0.99, why

  def _check_knee(self, s, ki):
    """(ok, reason, whether a wider friction knee could help)."""
    full, a, b = self.solve(s=s, ki=ki), self.solve((0,), s, ki), self.solve((1,), s, ki)
    model = self.model(full, s)
    for k, (lo, hi) in LOAD_BOUNDS.items():
      v = getattr(model, k) if k != 'kd' else full[I_KD]
      if not lo <= v <= hi:
        return False, f'{k} {v:.4g} outside [{lo}, {hi}]', False
    held = [k for k, r in self.identified(s, ki).items() if r > LOAD_IDENTIFIED_RATIO]
    if any(k in LOAD_MUST_IDENTIFY for k in held):
      return False, f'prior-held: {", ".join(k for k in held if k in LOAD_MUST_IDENTIFY)}', False
    gf, ga, gb = (load_surface(x, LOAD_KNEES[ki]) for x in (full, a, b))
    split = float(np.sqrt(np.mean((ga - gb) ** 2)) / np.sqrt(np.mean(gf ** 2)))
    if split > LOAD_SPLIT_TOL:
      return False, f'halves disagree {split:.2f}', False
    cross = min(self.r2(a, (1,), s, ki) - self.r2(b, (1,), s, ki), self.r2(b, (0,), s, ki) - self.r2(a, (0,), s, ki))
    if cross < -LOAD_CROSS_R2_TOL:
      return False, f'cross R^2 {cross:+.3f}', False
    worse = [f'{k} {100 * fit:+.0f}% (shipped {100 * ship:+.0f}%)' for k, (_, ship, fit) in self.regimes(s, ki).items()
             if abs(fit) > abs(ship) + REGIME_TOL]
    if worse:
      return False, 'worse than the shipped load at ' + ', '.join(worse), False
    if str(ki) not in self.ol_at or self.accepted - self.ol_at[str(ki)] >= OL_RECHECK_CHUNKS:
      self.ol_at[str(ki)], self.ol_gain[str(ki)] = self.accepted, self.open_loop(full, s, ki)
    for (lo, hi), g in zip(OL_BANDS, self.ol_gain[str(ki)], strict=True):
      if not OL_GAIN[0] <= g <= OL_GAIN[1]:
        return False, f'open-loop wheel gain {g:.2f} at {lo:.0f}-{hi:.0f} m/s (knee {LOAD_KNEES[ki][1]:g} deg/s)', g < OL_GAIN[0]
    return True, f'split {split:.3f}, cross {cross:+.3f}, lag {s * 10} ms, knee {LOAD_KNEES[ki][1]:g} deg/s', False

  def candidate(self, s=None, ki=None):
    """The current fit, frozen or not, with how it scores."""
    if self.n.sum() < 1:
      return None
    s = self.best_shift() if s is None else s
    ki = 0 if ki is None else ki
    coef = self.solve(s=s, ki=ki)
    model = self.model(coef, s)
    out = {k: getattr(model, k) for k in ('k0', 'k1', 'c', 'friction', 'bias', 'kroll')}
    out.update(j=coef[I_J], kd=coef[I_KD], bias_at_zero_torque=coef[I_BIAS], shift_s=s * DT, friction_width_v=list(LOAD_KNEES[ki]),
               r2=self.r2(coef, (0, 1), s, ki), r2_shipped=self.r2(self.shipped(coef[I_KD], s), (0, 1), s, ki),
               prior_held=[k for k, r in self.identified(s, ki).items() if r > LOAD_IDENTIFIED_RATIO],
               regimes={k: [round(n), round(ship, 3), round(fit, 3)] for k, (n, ship, fit) in self.regimes(s, ki).items()},
               open_loop_gain=self.ol_gain.get(str(ki)), coverage=self.coverage())
    return jsonable(out)

  def freeze(self):
    assert self.passed is not None
    s, ki = self.passed
    frozen = self.candidate(s, ki)
    assert frozen is not None
    frozen.update(coef=jsonable(self.solve(s=s, ki=ki)), knee=ki)
    self.frozen = frozen
    return frozen

  def _monitor(self, y, idx, th, rate, acc, c):
    frozen = self.frozen
    assert frozen is not None
    j = idx + int(round(frozen['shift_s'] / DT))
    pred = load_regressors(th[j], rate[j], acc[j], c['v'][j], c['roll'][j], c['tq'][idx], LOAD_KNEES[frozen['knee']]) @ np.array(frozen['coef'])
    pred, yy = pred - pred.mean(), y[idx] - y[idx].mean()
    if np.std(pred) < LOAD_MONITOR_MIN_STD:
      return 'monitor: too little motion'
    self.monitor_gain = (self.monitor_gain + [float(pred @ yy / (pred @ pred))])[-LOAD_MONITOR_CHUNKS:]
    if self.monitor_base is None and len(self.monitor_gain) == LOAD_MONITOR_CHUNKS:
      self.monitor_base = float(np.median(self.monitor_gain))
    return 'monitored'

  def stale(self):
    return (self.monitor_base is not None and len(self.monitor_gain) >= LOAD_MONITOR_CHUNKS
            and abs(float(np.median(self.monitor_gain)) / self.monitor_base - 1.0) > LOAD_STALE_GAIN)


# ---------------------------------------------------------------------------------------------------------------
# yaw decode (the fit_yaw_scale recipe, streaming: that tool pairs fixes with this class)

GPS_LAG = 0.4                        # s, GPS bearing behind the car
YAW_STRAIGHT_COUNTS = 1.0            # |mean count| over +-1 s for a fix to count as on a straight
YAW_PAIR_S = (10.0, 40.0)
YAW_MIN_TURN_DEG = 30.0
YAW_MIN_PAIRS = 300
YAW_MIN_SIDE = 0.2                   # share of pairs turning each way
YAW_MIN_CHUNKS = 12                  # chunks that gave pairs, per half
YAW_MIN_DRIVES = 3                   # drives that gave pairs: each has its own zero error
YAW_DRIVE_GAP_S = 60.0
YAW_SPLIT_SCALE = 0.01               # relative
YAW_SPLIT_RIGHT = 0.08               # deg/s
YAW_BOUNDS = ((0.23, 0.26), (-0.4, 0.6), (-1.0, 1.0))  # scale, clockwise correction, zero error in counts
YAW_TAIL = 300


def straight_pairs(fixes, fix, unwrap_scale):
  """Rows (heading change, integral of counts, integral of the clockwise ramp, seconds) between a new straight fix and
  every earlier one YAW_PAIR_S before it."""
  rows = []
  for f in fixes:
    T = fix[0] - f[0]
    if not YAW_PAIR_S[0] <= T <= YAW_PAIR_S[1]:
      continue
    dk, dr, dh = fix[2] - f[2], fix[3] - f[3], fix[1] - f[1]
    dh += 360 * np.round((unwrap_scale * dk - dh) / 360)
    if abs(dh) >= YAW_MIN_TURN_DEG:
      rows.append((dh, dk, dr, T))
  return rows


class YawScaleLearner(Part):
  """Scale (deg/s per 0x94 count) and clockwise correction from GPS heading between pairs of fixes that both sit on a
  straight, where the bearing's lag and the car's sideslip cancel. A zero error is fitted with them (a heading drift
  per second of pair): without it 0.2 counts of zero, the spread between one drive's standstills and the next's, moves
  the A040's answer from 0.2421 + 0.44 to 0.2487 + 0.14; with it the answer stays at 0.246 + 0.25."""
  ARRAYS = ('A', 'b', 'hh', 'n', 'side', 'chunks')
  META = ('drives',)

  def __init__(self, scale, right):
    self.shipped = (float(scale), float(right))
    self.A, self.b = np.zeros((2, 3, 3)), np.zeros((2, 3))
    self.hh, self.n, self.side, self.chunks = np.zeros(2), np.zeros(2), np.zeros((2, 2)), np.zeros(2)
    self.drives = 0
    self.frozen = None
    self.t_end = None
    self._reset_carry()

  def _reset_carry(self):
    if self.t_end is None or self.gap > YAW_DRIVE_GAP_S or self.gap < 0:
      self.counted = False  # a new drive
    self.t_end = None
    self.ck = self.cr = 0.0
    self.tail = np.zeros((0, 4))     # t, counts, integral of counts, integral of the ramp
    self.pending = np.zeros((0, 4))  # fixes whose +1 s is not here yet
    self.fixes = []

  def add_chunk(self, c, index):
    if self.frozen is not None:
      return 'frozen'
    t, k, gps = c['t'], c['yawc'], c.get('gps')
    self.gap = np.inf if self.t_end is None else t[0] - self.t_end
    bad = np.flatnonzero(~np.isfinite(k))
    if len(bad):  # no zero yet at the start of a drive: only what follows counts
      self._reset_carry()
      t, k = t[bad[-1] + 1:], k[bad[-1] + 1:]
      if len(t) < 500:
        return 'thin'
    elif not 0 <= self.gap <= 0.5:
      self._reset_carry()
    dt = np.diff(t, prepend=t[0] if self.t_end is None else self.t_end)
    lo, hi = RIGHT_LOSS_BP
    ck, cr = self.ck + np.cumsum(k * dt), self.cr + np.cumsum(np.clip((k - lo) / (hi - lo), 0.0, 1.0) * dt)
    self.ck, self.cr, self.t_end = float(ck[-1]), float(cr[-1]), float(t[-1])
    T = np.vstack([self.tail, np.c_[t, k, ck, cr]])
    gps = np.vstack([self.pending, gps[gps[:, 0] >= t[0]]]) if gps is not None and len(gps) else self.pending
    usable = gps[:, 0] - GPS_LAG + 1.0 <= T[-1, 0]
    self.pending = gps[~usable]
    h, pairs = half_of(index), 0
    for tg, bearing, speed, accuracy in gps[usable]:
      te = tg - GPS_LAG
      i0, i1 = np.searchsorted(T[:, 0], [te - 1.0, te + 1.0])
      if te - 1.0 < T[0, 0] or speed <= 5.0 or accuracy >= 3.0 or i1 - i0 < 100 or abs(T[i0:i1, 1].mean()) > YAW_STRAIGHT_COUNTS:
        continue
      fix = (te, bearing, float(np.interp(te, T[:, 0], T[:, 2])), float(np.interp(te, T[:, 0], T[:, 3])))
      self.fixes = [f for f in self.fixes if te - f[0] <= YAW_PAIR_S[1]]
      for dh, *x in straight_pairs(self.fixes, fix, self.shipped[0]):
        x = np.array(x)
        self.A[h] += np.outer(x, x)
        self.b[h] += x * dh
        self.hh[h] += dh * dh
        self.n[h] += 1
        self.side[h, 0 if dh > 0 else 1] += 1
        pairs += 1
      self.fixes.append(fix)
    self.tail = T[-YAW_TAIL:]
    self.chunks[h] += pairs > 0
    if pairs and not self.counted:
      self.counted = True
      self.drives += 1
    return 'accepted' if pairs else 'no pairs'

  def solve(self, halves=(0, 1)):
    """(scale, clockwise correction, zero error in counts, heading rms in deg), NaN where the pairs cannot tell."""
    A, b, hh, n = (x[list(halves)].sum(0) for x in (self.A, self.b, self.hh, self.n))
    if n < 4 or np.linalg.matrix_rank(A * np.outer(*[1.0 / np.sqrt(np.maximum(np.diag(A), 1e-12))] * 2)) < 3:
      return (float('nan'),) * 4
    c = scaled_solve(A, b)
    return float(c[0]), float(c[1]), float(c[2] / c[0]), float(np.sqrt(max(hh - 2 * c @ b + c @ A @ c, 0.0) / n))

  def check(self):
    n, side = self.n.sum(), self.side.sum(0)
    progress = min(1.0, n / YAW_MIN_PAIRS, side.min() / max(n, 1.0) / YAW_MIN_SIDE, self.chunks.min() / YAW_MIN_CHUNKS, self.drives / YAW_MIN_DRIVES)
    if progress < 1.0:
      return False, progress, (f'coverage: {n:.0f}/{YAW_MIN_PAIRS} straight-to-straight pairs ({side[0]:.0f} right, {side[1]:.0f} left), ' +
                               f'from {self.chunks[0]:.0f} + {self.chunks[1]:.0f} chunks (need {YAW_MIN_CHUNKS} each) on {self.drives}/{YAW_MIN_DRIVES} drives')
    (s, r, z, _), (sa, ra, _, _), (sb, rb, _, _) = self.solve(), self.solve((0,)), self.solve((1,))
    if not np.isfinite([s, sa, sb]).all():
      return False, progress, 'pairs cannot separate the scale from the clockwise correction'
    if abs(sa - sb) > YAW_SPLIT_SCALE * s or abs(ra - rb) > YAW_SPLIT_RIGHT:
      return False, 0.99, f'halves disagree: {sa:.4f} + {ra:.3f} / {sb:.4f} + {rb:.3f}'
    if not all(lo <= x <= hi for x, (lo, hi) in zip((s, r, z), YAW_BOUNDS, strict=True)):
      return False, 0.99, f'{s:.4f} + {r:.3f}, zero {z:+.2f} counts: out of bounds'
    return True, 1.0, f'halves {sa:.4f} + {ra:.3f} / {sb:.4f} + {rb:.3f}'

  def candidate(self):
    s, r, z, rms = self.solve()
    if not np.isfinite(s):
      return None
    return jsonable({'scale': round(s, 5), 'right': round(r, 4), 'zero_error_counts': round(z, 3), 'heading_rms_deg': round(rms, 2),
                     'pairs': int(self.n.sum()), 'drives': int(self.drives), 'shipped': list(self.shipped)})

  def freeze(self):
    self.frozen = self.candidate()
    return self.frozen


# ---------------------------------------------------------------------------------------------------------------
# rack map (the fit_rack_map recipe on a bounded per-cell sample; that tool fits with RackMapFit)

WHEEL_TO_YAW_LAG = ([3.75, 7.0, 12.0, 20.0, 30.0], [0.08, 0.06, 0.06, 0.08, 0.10])  # s, measured on the Clarity
RACK_EDGES = (3, 10, 20, 45, 70, 100, 150, 200, 260, 350, 450)
RACK_VB = (2.5, 5, 7, 9, 12, 15, 20, 25, 40)
RACK_CELL_CAP = 1200                 # samples (20 Hz) per angle band x speed band x side
RACK_MIN_S = 300.0                   # the offline tool's own floor
RACK_MIN_BAND_SIDE_S = 15.0          # per side, in each band up to 150 deg
RACK_SPLIT_TOL = 0.015
RACK_SF_TOL = 0.00015
RACK_SF_GRID = np.arange(-0.0012, 0.0002, 0.00005)


def pava_decreasing(values, weights):
  blocks = []  # [mean, weight, count]
  for x, w in zip(values, weights, strict=True):
    blocks.append([float(x), float(w), 1])
    while len(blocks) > 1 and blocks[-1][0] > blocks[-2][0]:
      m2, w2, c2 = blocks.pop()
      m1, w1, c1 = blocks.pop()
      blocks.append([(m1 * w1 + m2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
  return [m for m, _, c in blocks for _ in range(c)]


class RackMapFit:
  """D rows: v, lagged wheel angle (deg, left-positive), curvature from the yaw sensor (1/m, left-positive), roll."""
  def __init__(self, vgr_inverse, wheelbase):
    self.lin_bp, self.phy_bp = (np.asarray(x, float) for x in vgr_inverse)
    self.L = wheelbase

  def to_lin(self, phys):
    return np.sign(phys) * np.interp(np.abs(phys), self.phy_bp, self.lin_bp)

  def y(self, D, sf):
    v, th, k, ro = D.T
    return np.radians(self.to_lin(th)) / (self.L * (k * (1 - sf * v ** 2) - GRAVITY * sf * ro))

  def cells(self, D, sf):
    v, th = D[:, 0], D[:, 1]
    y = self.y(D, sf)
    A, out = np.abs(th), {}
    for bi, (a0, a1) in enumerate(zip(RACK_EDGES[:-1], RACK_EDGES[1:], strict=True)):
      for vi, (v0, v1) in enumerate(zip(RACK_VB[:-1], RACK_VB[1:], strict=True)):
        m = (A >= a0) & (A < a1) & (v >= v0) & (v < v1) & (y > 5) & (y < 40)
        lft, rgt = m & (th > 0), m & (th < 0)
        if lft.sum() >= 40 and rgt.sum() >= 40:
          out[(bi, vi)] = (0.5 * (np.median(y[lft]) + np.median(y[rgt])), min(lft.sum(), rgt.sum()))
    return out

  def spread(self, D, sf):
    c = self.cells(D, sf)
    err = w = 0.0
    for b in range(len(RACK_EDGES) - 1):
      cs = [(val, n) for (bi, _), (val, n) in c.items() if bi == b]
      if len(cs) < 2:
        continue
      vals, ns = np.array([x[0] for x in cs]), np.sqrt([x[1] for x in cs])
      mu = np.average(vals, weights=ns)
      err += np.sum(ns * (vals / mu - 1) ** 2)
      w += ns.sum()
    return err / w if w else float('nan')

  def fit_sf(self, D):
    sp = [self.spread(D, s) for s in RACK_SF_GRID]
    if not np.isfinite(sp).any():
      return float('nan')
    i = int(np.nanargmin(sp))
    if 0 < i < len(RACK_SF_GRID) - 1 and np.isfinite(sp[i - 1:i + 2]).all():
      a, b, _ = np.polyfit(RACK_SF_GRID[i - 1:i + 2], sp[i - 1:i + 2], 2)
      return round(float(-b / (2 * a)), 5)
    return round(float(RACK_SF_GRID[i]), 5)

  def table(self, D, sf):
    th, y = D[:, 1], self.y(D, sf)
    bp, val, n = [], [], []
    for a0, a1 in zip(RACK_EDGES[:-1], RACK_EDGES[1:], strict=True):
      m = (np.abs(th) >= a0) & (np.abs(th) < a1) & (y > 5) & (y < 40)
      lft, rgt = m & (th > 0), m & (th < 0)
      if lft.sum() > 60 and rgt.sum() > 60:
        bp.append(float(np.median(np.abs(th[m]))))
        val.append(0.5 * (np.median(y[lft]) + np.median(y[rgt])))
        n.append(int(m.sum()))
    # a rack's effective ratio cannot rise off centre: a decreasing isotonic fit, sample-weighted
    return bp, pava_decreasing(val, n), n

  def predict_map(self, D, sf, bp, val):
    v, th, k, ro = D.T
    R = np.interp(np.abs(th), bp, val)
    return (np.radians(self.to_lin(th)) / (R * self.L) + GRAVITY * sf * ro) / (1 - sf * v ** 2)


def rack_samples(t, v, a, rate, angle, yaw_left, roll):
  """fit_rack_map's frame selection: (row indices at 20 Hz, lagged angle, curvature)."""
  k = smooth(yaw_left, 10) / np.maximum(v, 0.1)
  lagged = np.interp(t - np.interp(v, *WHEEL_TO_YAW_LAG), t, angle)
  m = np.isfinite(k) & (v > 2.5) & (np.abs(a) < 2) & (np.abs(rate) < 120) & (np.abs(lagged) >= 3) & (np.sign(k) == np.sign(lagged))
  return np.flatnonzero(m)[::5], lagged, k


class RackMapLearner(Part):
  """Samples (v, lagged angle, smoothed yaw counts, roll) at 20 Hz into per-cell reservoirs, so the store is bounded
  and every cell keeps a uniform sample of what it saw. Counts, not curvature: the fit runs on whatever yaw decode is
  current, and only freezes on a frozen one."""
  NCELL = (len(RACK_EDGES) - 1) * (len(RACK_VB) - 1) * 2
  ARRAYS = ('buf', 'seen')
  META = ()

  def __init__(self, vgr_inverse, wheelbase, seed=0):
    self.fit = RackMapFit(vgr_inverse, wheelbase)
    self.buf = np.full((self.NCELL, RACK_CELL_CAP, 5), np.nan, np.float32)  # v, th, counts, roll, half
    self.seen = np.zeros(self.NCELL, np.int64)
    self.rng = np.random.default_rng(seed)
    self.frozen = None

  def add_chunk(self, c, index):
    if self.frozen is not None:
      return 'frozen'
    t, v = c['t'], c['v']
    if not np.isfinite(c['yawc']).any() or len(t) < 200:
      return 'thin'
    counts = smooth(np.nan_to_num(c['yawc'], nan=0.0), 10)
    idx, lagged, _ = rack_samples(t, v, c['a'], c['rate'], c['ang'] - c['off'], np.where(np.isfinite(c['yawc']), -counts, np.nan), c['roll'])
    idx = idx[(c['eps_ok'][idx] > 0.5) & (t[idx] - t[0] > 0.2)]
    if len(idx) == 0:
      return 'thin'
    bi = np.searchsorted(RACK_EDGES, np.abs(lagged[idx]), side='right') - 1
    vi = np.searchsorted(RACK_VB, v[idx], side='right') - 1
    keep = (bi >= 0) & (bi < len(RACK_EDGES) - 1) & (vi >= 0) & (vi < len(RACK_VB) - 1)
    cell = ((bi * (len(RACK_VB) - 1) + vi) * 2 + (lagged[idx] < 0))[keep]
    rows = np.c_[v[idx], lagged[idx], counts[idx], c['roll'][idx], np.full(len(idx), half_of(index))][keep]
    for ci, row in zip(cell, rows, strict=True):
      n = self.seen[ci]
      if n < RACK_CELL_CAP:
        self.buf[ci, n] = row
      else:
        j = self.rng.integers(0, n + 1)
        if j < RACK_CELL_CAP:
          self.buf[ci, j] = row
      self.seen[ci] += 1
    return 'accepted'

  def samples(self, decode, halves=(0, 1)):
    D = self.buf.reshape(-1, 5)
    D = D[np.isfinite(D[:, 0]) & np.isin(D[:, 4], halves)].astype(float)
    k = -np.radians(yaw_deg_s(D[:, 2], *decode)) / np.maximum(D[:, 0], 0.1)
    return np.c_[D[:, 0], D[:, 1], k, D[:, 3]]

  def seconds(self):
    seen = self.seen.reshape(len(RACK_EDGES) - 1, len(RACK_VB) - 1, 2).sum(1) / 20.0  # band x side
    return float(seen.sum()), seen

  def solve(self, decode, halves=(0, 1)):
    D = self.samples(decode, halves)
    sf = self.fit.fit_sf(D)
    bp, val, _ = self.fit.table(D, sf) if np.isfinite(sf) else ([], [], [])
    return sf, bp, val

  def check(self, decode):
    total, band_side = self.seconds()
    need = [i for i, a0 in enumerate(RACK_EDGES[:-1]) if a0 < 150]
    short = [f'{RACK_EDGES[i]}-{RACK_EDGES[i + 1]} deg {min(band_side[i]):.0f}/{RACK_MIN_BAND_SIDE_S:.0f} s' for i in need
             if min(band_side[i]) < RACK_MIN_BAND_SIDE_S]
    progress = min(total / RACK_MIN_S, *(min(band_side[i]) / RACK_MIN_BAND_SIDE_S for i in need), 1.0)
    if progress < 1.0:
      return False, progress, 'coverage: ' + ', '.join(short or [f'{total:.0f}/{RACK_MIN_S:.0f} s of turning'])
    sf, bp, val = self.solve(decode)
    (sfa, bpa, va), (sfb, bpb, vb) = self.solve(decode, (0,)), self.solve(decode, (1,))
    if not (np.isfinite(sf) and np.isfinite(sfa) and np.isfinite(sfb)) or min(len(bp), len(bpa), len(bpb)) < 4:
      return False, progress, 'no slip factor'
    if abs(sfa - sfb) > RACK_SF_TOL:
      return False, 0.99, f'halves disagree on the slip factor ({sfa} / {sfb})'
    up_to = min(bpa[-1], bpb[-1], 150.0)
    worst = max(abs(np.interp(x, bpa, va) / np.interp(x, bpb, vb) - 1) for x in bp if x <= up_to)
    if worst > RACK_SPLIT_TOL:
      return False, 0.99, f'halves disagree by {worst:.3f}'
    if np.any(np.diff(val) > 1e-9) or not 8.0 < val[0] < 25.0:
      return False, 0.99, 'table not a rack'
    return True, 1.0, f'sf {sf}, worst split {worst:.3f}'

  def candidate(self, decode):
    sf, bp, val = self.solve(decode)
    if not np.isfinite(sf) or not bp:
      return None
    return jsonable({'ratio_bp': [round(x, 1) for x in bp], 'ratio_v': [round(x, 3) for x in val], 'slip_factor': sf,
                     'yaw_decode': list(decode), 'seconds': round(self.seconds()[0])})

  def freeze(self, decode):
    self.frozen = self.candidate(decode)
    return self.frozen


# Near centre the car turns less than the rack map says. Measured as the slope of the yaw sensor's curvature on the
# shipped map's inside short windows, each with its own mean taken out, so the yaw zero, the angle offset and the road's
# crown drop out (paramsd's offset is itself fitted to the yaw, so a pooled fit with it reads ~1.0 whatever the car
# does). The same slope a little off centre is the reference: on the A220 0.60-0.70 inside +-3 deg against 0.96 at
# 4-12 deg, on the A040 0.80-0.95 against 0.97. Reported per speed band, never applied.
CENTRE_ANGLES = ((0.0, 3.0), (4.0, 12.0))  # deg: centre, reference
CENTRE_BANDS = ((5.0, 9.0), (9.0, 15.0), (15.0, 30.0), (30.0, 45.0))
CENTRE_MAX_RATE = 40.0
CENTRE_WINDOW_S = 10.0
CENTRE_MIN_S = 40.0


class NearCentreGain(Part):
  """Sums are kept over counts, so the yaw decode can be chosen afterwards."""
  ARRAYS = ('S',)
  META = ()

  def __init__(self, rack_map):
    self.rack_map = rack_map
    self.S = np.zeros((len(CENTRE_ANGLES), len(CENTRE_BANDS), 4))  # n, and centered x*x, x*u1, x*u2

  def add_chunk(self, c):
    t, v = c['t'], c['v']
    if not np.isfinite(c['yawc']).all() or len(t) < 200:
      return 'thin'
    counts = smooth(c['yawc'], 10)
    lagged = np.interp(t - np.interp(v, *WHEEL_TO_YAW_LAG), t, c['ang'] - np.median(c['off']))
    ok = (np.abs(c['a']) < 2) & (np.abs(c['rate']) < CENTRE_MAX_RATE) & (t - t[0] > 0.2) & (t[-1] - t > 0.1)
    window = ((t - t[0]) // CENTRE_WINDOW_S).astype(int)
    lo, hi = RIGHT_LOSS_BP
    for ai, (a0, a1) in enumerate(CENTRE_ANGLES):
      for bi, (v0, v1) in enumerate(CENTRE_BANDS):
        idx = np.flatnonzero(ok & (np.abs(lagged) >= a0) & (np.abs(lagged) < a1) & (v >= v0) & (v < v1))[::5]
        if len(idx) < 20:
          continue
        x = np.array([-self.rack_map.curvature_from_angle(float(a), float(s), float(r)) for a, s, r in zip(lagged[idx], v[idx], c['roll'][idx], strict=True)])
        u1 = -np.radians(counts[idx]) / v[idx]
        u2 = -np.radians(np.clip((counts[idx] - lo) / (hi - lo), 0.0, 1.0)) / v[idx]
        group = window[idx] if ai == 0 else 2 * window[idx] + (lagged[idx] > 0)  # off centre, each side has its own offset
        for w in np.unique(group):
          m = group == w
          if m.sum() >= 20:
            xc = x[m] - x[m].mean()
            self.S[ai, bi] += [m.sum(), xc @ xc, xc @ u1[m], xc @ u2[m]]
    return 'accepted'

  def gains(self, decode):
    """{speed band: [gain inside +-3 deg, s of it, reference gain off centre, s of it]}"""
    out = {}
    for bi, (v0, v1) in enumerate(CENTRE_BANDS):
      row = []
      for n, xx, xu1, xu2 in self.S[:, bi]:
        seen = n / 20.0 >= CENTRE_MIN_S and xx > 0
        row += [round(float((decode[0] * xu1 + decode[1] * xu2) / xx), 3) if seen else None, round(n / 20.0)]
      if row[0] is not None:
        out[f'{v0:.0f}-{v1:.0f}'] = row
    return out


# ---------------------------------------------------------------------------------------------------------------
# model-delay schedule (eps_report timing: lag of the car's yaw curvature behind the model action). Measured only.

PIPELINE_OFFSET = 0.038
# Town bands only: above 15 m/s lane centering pulls 6-10% of a curve back out through its 0.4 s smoothing and reads as lag.
TIMING_BANDS = ((2.5, 5), (5, 9), (9, 15))
TIMING_LAGS = np.arange(0.0, 0.8, 0.01)
TIMING_MIN_S = (90, 120, 120)             # per band, s of hands-off turning frames
TIMING_SPLIT_TOL = 0.03                   # s
TIMING_BOUNDS = (0.0, 0.5)


class TimingLearner(Part):
  """Each speed band freezes on its own."""
  ARRAYS = ('spp', 'spy', 'syy', 'n')
  META = ('band_frozen',)

  def __init__(self):
    shape = (2, len(TIMING_BANDS), len(TIMING_LAGS))
    self.spp, self.spy = np.zeros(shape), np.zeros(shape)
    self.syy, self.n = np.zeros(shape[:2]), np.zeros(shape[:2])
    self.band_frozen = [None] * len(TIMING_BANDS)
    self.frozen = None

  def add_chunk(self, c, yaw, index):
    if self.frozen is not None:
      return 'frozen'
    t, v = c['t'], c['v']
    if not (np.isfinite(yaw).any() and np.isfinite(c['act']).any()) or len(t) < 200:
      return 'thin'
    k = smooth(np.where(np.isfinite(yaw), yaw, 0.0), 10) / np.maximum(v, 0.1)
    ok = (c['lat'] > 0.5) & (c['pressed'] < 0.5) & (np.abs(c['tq']) < 400) & (np.abs(c['a']) < 2) & np.isfinite(yaw) \
      & np.isfinite(c['act']) & (c['eps_ok'] > 0.5)
    ok &= np.convolve(~ok, np.ones(100), 'same') == 0
    ok &= (t - t[0]) > TIMING_LAGS[-1] + 0.05
    act = np.where(np.isfinite(c['act']), c['act'], 0.0)
    h = half_of(index)
    for bi, (lo, hi) in enumerate(TIMING_BANDS):
      if self.band_frozen[bi] is not None:
        continue
      idx = np.flatnonzero(ok & (c['blinker'] < 0.5) & (v >= lo) & (v < hi) & (np.abs(k) > 0.004))
      if len(idx) == 0:
        continue
      y = k[idx]
      P = np.interp(t[idx][None, :] - TIMING_LAGS[:, None], t, act)
      self.spp[h, bi] += np.sum(P * P, 1)
      self.spy[h, bi] += P @ y
      self.syy[h, bi] += y @ y
      self.n[h, bi] += len(idx)
    return 'accepted'

  def solve(self, halves=(0, 1)):
    spp, spy, syy = (x[list(halves)].sum(0) for x in (self.spp, self.spy, self.syy))
    err = syy[:, None] - spy ** 2 / np.maximum(spp, 1e-12)
    lag = TIMING_LAGS[np.argmin(err, 1)] - PIPELINE_OFFSET
    return np.where(self.n[list(halves)].sum(0) > 0, lag, np.nan)

  def check(self):
    s = self.n.sum(0) * DT
    full, a, b = self.solve(), self.solve((0,)), self.solve((1,))
    why = []
    for i, need in enumerate(TIMING_MIN_S):
      name = f'{TIMING_BANDS[i][0]}-{TIMING_BANDS[i][1]} m/s'
      if self.band_frozen[i] is not None:
        continue
      if s[i] < need:
        why.append(f'{name} {s[i]:.0f}/{need} s')
      elif abs(a[i] - b[i]) > TIMING_SPLIT_TOL:
        why.append(f'{name} halves {a[i]:.2f}/{b[i]:.2f}')
      elif not TIMING_BOUNDS[0] <= full[i] <= TIMING_BOUNDS[1]:
        why.append(f'{name} {full[i]:.2f} s out of bounds')
      else:
        self.band_frozen[i] = round(float(full[i]), 3)
    done = sum(x is not None for x in self.band_frozen)
    if done == len(TIMING_BANDS):
      return True, 1.0, 'every band'
    return False, min(0.99, float(np.mean(np.minimum(s / np.array(TIMING_MIN_S), 1.0)))), '; '.join(why)

  def candidate(self):
    lag = self.solve()
    return jsonable({'bp': [(lo + hi) / 2 for lo, hi in TIMING_BANDS], 'v': [None if np.isnan(x) else round(float(x), 3) for x in lag],
                     'frozen': self.band_frozen, 'seconds': [round(x) for x in self.n.sum(0) * DT]})

  def freeze(self):
    self.frozen = self.candidate()
    return self.frozen


# ---------------------------------------------------------------------------------------------------------------
# command delay (plan_timing: does the car run the model's plan on time). Measured for the delay that ran, never
# requested or applied: lateral timing changes go shadow first, then review.

PLAN_T = 10.0 * (np.arange(33) / 32) ** 2
PLAN_T_FIT = (PLAN_T >= 0.1) & (PLAN_T <= 1.5)
PLAN_SHIFTS = np.arange(-0.4, 0.41, 0.01)
PLAN_PHASES = ('entry', 'exit', 'all')
VSA_LATENCY = 0.017
PLAN_MIN_FRAMES = 3000               # model frames (20 Hz): 150 s of turning in the phase
PLAN_SPLIT_TOL = 0.03                # s
PLAN_DELAY_TOL = 0.005               # s: chunks run at another command delay start the measurement over


class PlanTimingLearner(Part):
  """How early (s* < 0) or late the car runs the model's plan at the command delay it was driven with."""
  ARRAYS = ('sse', 'n')
  META = ('delay_s', 'restarts')

  def __init__(self):
    self.delay_s = None
    self.restarts = 0
    self.frozen = None
    self._reset()

  def _reset(self):
    self.sse = np.zeros((2, len(PLAN_PHASES), len(PLAN_SHIFTS)))
    self.n = np.zeros((2, len(PLAN_PHASES)))

  def add_chunk(self, c, yaw, index):
    if self.frozen is not None:
      return 'frozen'
    M = c.get('model')
    if M is None or len(M) < 50 or not np.isfinite(yaw).any():
      return 'thin'
    t, v = c['t'], c['v']
    tm, tf, plan = M[:, 0], M[:, 1], M[:, 3:]   # orientationRate.z / vx: the sign of a clockwise-positive yaw
    engaged = np.interp(tm, t, c['lat']) > 0.5
    # the delay is scheduled on speed: the town value is the one the phases below are driven with
    ran = c['cmd_delay'][(c['lat'] > 0.5) & (v < eps_ff.CMD_DELAY_SPEED_BP[0]) & np.isfinite(c['cmd_delay'])]
    ran = float(np.median(ran)) if len(ran) >= 100 else None
    if ran is not None and (self.delay_s is None or abs(ran - self.delay_s) > PLAN_DELAY_TOL):
      self.restarts += self.delay_s is not None and self.n.sum() > 0
      self.delay_s = round(ran, 3)
      self._reset()
    yt = t - VSA_LATENCY
    k = smooth(np.where(np.isfinite(yaw), yaw, 0.0) / np.maximum(v, 0.5), 5)
    vm = np.interp(tm, t, v)
    near_takeover = np.interp(tm, t, (np.convolve(c['pressed'], np.ones(200), 'same') > 0).astype(float)) > 0.5
    k_now = np.abs(plan[:, 0])
    k_ahead = np.abs(np.array([np.interp(0.5, PLAN_T, row) for row in plan]))
    room = (tf + PLAN_T[PLAN_T_FIT][-1] + PLAN_SHIFTS[-1] < yt[-1]) & (tf + PLAN_T[PLAN_T_FIT][0] + PLAN_SHIFTS[0] > yt[0])
    turning = engaged & ~near_takeover & (np.maximum(k_now, k_ahead) > 0.006) & room
    town = (vm > 3) & (vm < 12)
    masks = (turning & town & (k_ahead > 1.25 * k_now), turning & town & (k_ahead < 0.8 * k_now), turning & (vm > 5) & (vm < 12))
    h = half_of(index)
    for pi, m in enumerate(masks):
      if not m.any():
        continue
      T = tf[m][:, None] + PLAN_T[PLAN_T_FIT][None, :]
      P = plan[m][:, PLAN_T_FIT]
      for si, sh in enumerate(PLAN_SHIFTS):
        self.sse[h, pi, si] += np.sum((np.interp(T + sh, yt, k) - P) ** 2)
      self.n[h, pi] += m.sum()
    return 'accepted'

  def solve(self, halves=(0, 1)):
    sse = self.sse[list(halves)].sum(0)
    return {ph: float(PLAN_SHIFTS[int(np.argmin(sse[i]))]) for i, ph in enumerate(PLAN_PHASES)}

  def check(self):
    n = self.n.sum(0)
    progress = min(1.0, min(n[0], n[2]) / PLAN_MIN_FRAMES)
    if progress < 1.0:
      return False, progress, f'coverage: {n[0]:.0f} entry / {n[2]:.0f} all of {PLAN_MIN_FRAMES} turning model frames'
    a, b = self.solve((0,)), self.solve((1,))
    for ph in ('entry', 'all'):
      if abs(a[ph] - b[ph]) > PLAN_SPLIT_TOL:
        return False, 0.99, f'{ph}: halves {a[ph]:+.2f}/{b[ph]:+.2f}'
    full = self.solve()
    return True, 1.0, f"entry {full['entry']:+.2f} s, all {full['all']:+.2f} s at {self.delay_s} s (negative = early)"

  def candidate(self):
    if self.n.sum() == 0:
      return None
    return jsonable({'cmd_delay_s': self.delay_s, 'shift_s': {k: round(v, 2) for k, v in self.solve().items()},
                     'frames': [int(x) for x in self.n.sum(0)], 'restarts': int(self.restarts)})

  def freeze(self):
    self.frozen = self.candidate()
    return self.frozen


# ---------------------------------------------------------------------------------------------------------------
# torque sensor (reported only): what steeringTorque reads with nobody on the wheel

TORQUE_NAMES = ('inertia', 'friction', 'imbalance', 'offset')
TORQUE_QUIET = 350.0                 # counts: no reading above this from TORQUE_NEAR_S to TORQUE_FAR_S on both sides
TORQUE_NEAR_S, TORQUE_FAR_S = 0.5, 3.0   # the reading itself is not selected on between, so one the EPS makes is kept
TORQUE_EXPLAINED = 300.0             # counts the default sensor may leave of a frame: more than that is a hand


class TorqueSensorModel(Part):
  """The torsion bar carries what it takes to move the wheel and the column above it. Over frames with quiet hands the
  reading is regressed on the terms the shadow driver yield takes out of it (honda_eps_driver_yield.TorqueSensor),
  computed by that module's own filter; what is left of a reading after that is the driver."""
  ARRAYS = ('XtX', 'Xty', 'misc')
  META = ()

  def __init__(self):
    p = len(TORQUE_NAMES)
    self.XtX, self.Xty, self.misc = np.zeros((p, p)), np.zeros(p), np.zeros(3)  # misc: sum of tq^2, tq, n

  def add_chunk(self, c):
    n = len(c['t'])
    near, far = int(round(TORQUE_NEAR_S / DT)), int(round(TORQUE_FAR_S / DT))
    if n < 2 * far + 100:
      return 'thin'
    est = DriverYield(DT)
    T = np.array([est.terms(*x) for x in zip(c['tq'].tolist(), (c['ang'] - c['off']).tolist(), c['rate'].tolist(), strict=True)])
    ok = (c['lat'] > 0.5) & (c['eps_ok'] > 0.5) & (c['v'] > 1.0)
    loud = np.r_[0, np.cumsum((np.abs(c['tq']) > TORQUE_QUIET) | (c['pressed'] > 0.5) | ~ok)]
    i = np.arange(n)
    before = loud[np.maximum(i - near, 0)] - loud[np.maximum(i - far, 0)]
    after = loud[np.minimum(i + far, n)] - loud[np.minimum(i + near, n)]
    idx = np.flatnonzero(ok & (i >= far) & (i + far <= n) & (before == 0) & (after == 0))
    if len(idx) == 0:
      return 'thin'
    d = TORQUE_SENSOR_DEFAULT
    left = T[idx, 0] - (d.inertia * T[idx, 1] + d.friction * T[idx, 2] + d.imbalance * T[idx, 3])
    idx = idx[np.abs(left - np.median(left)) < TORQUE_EXPLAINED]
    X = np.column_stack([T[idx, 1], T[idx, 2], T[idx, 3], np.ones(len(idx))])
    tq = T[idx, 0]
    self.XtX += X.T @ X
    self.Xty += X.T @ tq
    self.misc += [tq @ tq, tq.sum(), len(idx)]
    return 'accepted'

  def result(self):
    tt, ts, n = self.misc
    if n < 6000:
      return None
    coef = scaled_solve(self.XtX + 1e-9 * np.eye(len(TORQUE_NAMES)), self.Xty)
    sse, sst = tt - 2 * coef @ self.Xty + coef @ self.XtX @ coef, tt - ts ** 2 / n
    out = {k: float(f'{x:.4g}') for k, x in zip(TORQUE_NAMES, coef, strict=True)}
    out.update(minutes=round(n * DT / 60, 1), rms_counts=round(float(np.sqrt(sst / n)), 1), rms_after=round(float(np.sqrt(max(sse, 0.0) / n)), 1),
               r2=round(float(1 - sse / max(sst, 1e-9)), 3))
    return out


# ---------------------------------------------------------------------------------------------------------------

CHECK_EVERY = 5  # chunks
# A part freezes on its second passing check in a row: five more minutes of driving must not break the agreement.
# (The A040's yaw halves agreed at 89 min of log and no longer did on all 153.)
FREEZE_PASSES = 2


class HondaEpsCarLearner:
  PARTS = ('load', 'yaw', 'rack', 'cmd_delay', 'timing')

  def __init__(self, cal, wheelbase, vgr_inverse, yaw_calibration=None, fade_up_s=eps_ff.OVERRIDE_FADE_UP_S_DEFAULT, identity=''):
    """yaw_calibration: opendbc's (scale, zero, clockwise correction) for the car, None without a decoded 0x94.
    identity: anything that must match for saved state to be kept (the EPS version, the PTM image)."""
    self.cal, self.identity = cal, identity
    self.load = ColumnLoadLearner(cal, fade_up_s)
    self.yaw = YawScaleLearner(yaw_calibration[0], yaw_calibration[2]) if yaw_calibration is not None else None
    self.rack = RackMapLearner(vgr_inverse, wheelbase) if vgr_inverse is not None and self.yaw is not None else None
    has_map = cal.rack is not None and vgr_inverse is not None and self.yaw is not None
    self.centre = NearCentreGain(HondaEpsRackMap(wheelbase, vgr_inverse, cal.rack)) if has_map else None
    self.timing = TimingLearner()
    self.cmd_delay = PlanTimingLearner()
    self.torque = TorqueSensorModel()
    self.chunks = 0
    self.seconds = 0.0
    self.reasons = {}
    self.passes = {}
    self.freezing = True  # a replay turns it off to see what all of the data gives

  def decode(self):
    """The yaw decode in use: the learned one once frozen, opendbc's until then."""
    if self.yaw is None:
      return None
    return (self.yaw.frozen['scale'], self.yaw.frozen['right']) if self.yaw.frozen is not None else self.yaw.shipped

  def add_chunk(self, c):
    i = self.chunks
    self.chunks += 1
    self.seconds += float(c['t'][-1] - c['t'][0])
    y = self.last_target = firmware_target(c['e4'], c['v'], c['rate'], c['ang'] - c['off'], self.cal)
    out = {'load': self.load.add_chunk(c, y, i), 'torque': self.torque.add_chunk(c)}
    yaw = np.full(len(c['t']), np.nan)
    if self.yaw is not None:
      out['yaw'] = self.yaw.add_chunk(c, i)
      yaw = np.radians(yaw_deg_s(c['yawc'], *self.decode()))
    if self.rack is not None:
      out['rack'] = self.rack.add_chunk(c, i)
    if self.centre is not None:
      self.centre.add_chunk(c)
    out['cmd_delay'] = self.cmd_delay.add_chunk(c, yaw, i)
    out['timing'] = self.timing.add_chunk(c, yaw, i)
    if self.chunks % CHECK_EVERY == 0:
      self.check()
    return out

  def check(self):
    for name in self.PARTS:
      part = getattr(self, name)
      if part is None or part.frozen is not None:
        continue
      if name == 'rack':
        ok, progress, why = part.check(self.decode())
        if self.yaw.frozen is None:  # whatever it says on the shipped decode
          ok, why = False, 'waiting for the yaw decode to freeze' + (f'; {why}' if progress < 1.0 else '')
      else:
        ok, progress, why = part.check()
      self.passes[name] = self.passes.get(name, 0) + 1 if ok else 0
      if ok and self.freezing and self.passes[name] >= FREEZE_PASSES:
        part.freeze(*([self.decode()] if name == 'rack' else []))
      elif ok:
        progress, why = 0.99, f'passed, confirming on the next check: {why}'
      self.reasons[name] = [float(progress), why]

  def status(self):
    out = {}
    for name in self.PARTS:
      part = getattr(self, name)
      progress, why = self.reasons.get(name, (0.0, 'not checked yet'))
      if part is None:
        out[name] = ('waiting', 0.0, 'no decoded VSA yaw (0x94) or no firmware angle table for this car')
      elif name == 'load' and part.stale():
        gain = np.median(part.monitor_gain) / part.monitor_base
        out[name] = ('stale', 1.0, f'the car now needs {gain:.2f}x the frozen load: reflashed or changed? reset recommended')
      elif part.frozen is not None:
        out[name] = ('frozen', 1.0, why)
      else:
        out[name] = ('learning', progress, why)
    return out

  def result(self):
    """Everything worth reviewing, small enough for a Params value: per part its state and the frozen value, or the
    current candidate while it is still learning. Shadow only: nothing reads this back."""
    parts = {}
    for name, (state, progress, why) in self.status().items():
      part = getattr(self, name)
      entry = {'state': state, 'progress': round(progress, 2), 'why': why}
      if part is not None:
        if part.frozen is not None:
          entry['value'] = part.frozen
        else:
          entry['candidate'] = part.candidate(self.decode()) if name == 'rack' else part.candidate()
      parts[name] = entry
    load = self.cal.load
    return jsonable({'version': LEARNER_VERSION, 'shadow': True, 'calibration': self.cal.name, 'identity': self.identity, 'chunks': self.chunks,
                     'minutes': round(self.seconds / 60, 1), 'parts': parts,
                     'shipped_load': {k: getattr(load, k) for k in ('k0', 'k1', 'c', 'friction', 'bias', 'kroll')},
                     'near_centre_gain': self.centre.gains(self.decode()) if self.centre is not None else None,
                     'torque_sensor': self.torque.result()})

  # ---- persistence: one npz blob (a file, ~0.5 MB); the result above is the small part
  def _parts(self):
    return {k: getattr(self, k) for k in self.PARTS + ('centre', 'torque') if getattr(self, k) is not None}

  def to_bytes(self):
    arrays, parts = {}, {}
    for name, part in self._parts().items():
      a, parts[name] = part.dump()
      arrays.update({f'{name}_{k}': v for k, v in a.items()})
    meta = {'version': LEARNER_VERSION, 'calibration': self.cal.name, 'identity': self.identity, 'chunks': self.chunks,
            'seconds': self.seconds, 'reasons': self.reasons, 'passes': self.passes, 'parts': parts}
    f = io.BytesIO()
    np.savez_compressed(f, meta=np.array(json.dumps(meta)), **arrays)
    return f.getvalue()

  @classmethod
  def from_bytes(cls, blob, cal, wheelbase, vgr_inverse, yaw_calibration=None, fade_up_s=eps_ff.OVERRIDE_FADE_UP_S_DEFAULT, identity=''):
    """None when the blob is unreadable or from another learner version, calibration or identity (the caller starts over)."""
    self = cls(cal, wheelbase, vgr_inverse, yaw_calibration, fade_up_s, identity)
    try:
      z = np.load(io.BytesIO(blob))
      meta = json.loads(str(z['meta']))
      if (meta['version'], meta['calibration'], meta['identity']) != (LEARNER_VERSION, cal.name, identity):
        return None
      if set(meta['parts']) != set(self._parts()):
        return None
      for name, part in self._parts().items():
        part.restore({k: z[f'{name}_{k}'] for k in part.ARRAYS}, meta['parts'][name])
      self.chunks, self.seconds, self.reasons, self.passes = meta['chunks'], meta['seconds'], meta['reasons'], meta['passes']
    except Exception:
      return None
    return self
