#!/usr/bin/env python3
"""Does the car run the model's plan on time? On distance? Per drive, by turn phase.

The model publishes a plan for each camera frame: the car's yaw rate and speed at 33 future times. Their ratio is the
curvature the model expects the car to have at frame + T. The car's real curvature comes from its own yaw sensor
(VSA 0x94; carState.yawRate is not populated on these builds). For each turning frame the plan curve (T = 0.1-1.5 s)
is matched against the car's curvature shifted by s; s* is the shift with the least error:
  s* < 0  the car gets there EARLY (turns in before the model meant to: hugs the inside, unwinds early)
  s* > 0  the car gets there LATE
Two alignments are reported side by side, each also with a gain fitted at every shift (the car may deliver more or
less curvature than planned; "gain" is that factor at the best shift):
  time      the plan at frame + T against the car at frame + T + s.
  distance  the plan at the distance it planned to have covered by T against the car at the same distance travelled
            from the frame (odometry from vEgo) plus s * v, so s is still in seconds, at the frame's speed. This takes
            speed out of the comparison: a driver who is slower than the plan (cruise off, always-on lateral) reaches
            every point of the plan late, which the time alignment reads as lateness of the steering.
"speed" is that mismatch on its own: how much later the car reaches the plan's 1.5 s point from its 0.1 s point
(the plan's own distance between them), in seconds. The time shift is roughly the distance shift plus this term.
Phases: entry = planned curvature growing over the next 0.5 s, exit = shrinking, all = every turning frame at 5-12 m/s.
Frames within ~1 s of a takeover (steeringPressed) are left out, and so are frames whose window runs over a hole in the
log. A steady curve has a flat plan, so time is barely observable there: trust entry / exit / all, not the steady phase.
Each line also gives the frame counts with cruise on and off (carState.cruiseState.enabled).

  python tools/lateral/plan_timing.py <route dir or rlog glob> [...]
  python tools/lateral/plan_timing.py --schema-root ~/nrdr/ns7-personal5-w <rlogs of a 7.x build>

A 7.x build (StarPilot 7.0, Night Star) has its cereal under <root>/openpilot/cereal, so --schema-root reads its logs
with that tree's schema and opendbc. It logs the lateral source as a `modelLateralSource` log message, which this reads.

Konik/comma "files" lists are sorted as text (0, 1, 10, 11, 2, ...): name downloaded rlogs by the segment number in
their URL, not by list position, or the timeline is scrambled.
"""
import argparse
import glob
import os
import re
import sys

import numpy as np
import zstandard as zstd

# set by load_schema(): the cereal log module and the yaw decode of the build the logs came from
log = YAW_RATE_CALIBRATION = yaw_rate_deg_s = None


def load_schema(root=None):
  """Bind `log` and the yaw decode. Default: this checkout's. root: a build whose cereal is <root>/openpilot/cereal
  (7.x), put first on the path before anything of cereal / opendbc is loaded."""
  global log, YAW_RATE_CALIBRATION, yaw_rate_deg_s
  if root:
    root = os.path.abspath(os.path.expanduser(root))
    for name in [m for m in sys.modules if m.split('.')[0] in ('cereal', 'openpilot', 'opendbc')]:
      del sys.modules[name]
    sys.path[:0] = [root, os.path.join(root, 'opendbc_repo')]
    from openpilot.cereal import log as _log
  else:
    try:
      from cereal import log as _log
    except ImportError:
      from openpilot.cereal import log as _log
  from opendbc.car.honda.yaw_rate import YAW_RATE_CALIBRATION as _cal, yaw_rate_deg_s as _yaw
  log, YAW_RATE_CALIBRATION, yaw_rate_deg_s = _log, _cal, _yaw


def ensure_schema():
  if log is None:
    load_schema()


T_IDX = 10.0 * (np.arange(33) / 32) ** 2
T_FIT = (T_IDX >= 0.1) & (T_IDX <= 1.5)
SHIFTS = np.arange(-0.4, 0.41, 0.01)
T_SPEED = (0.1, 1.5)  # s: the span of the plan the speed mismatch is measured over
SOURCE_CODES = {'unknown': 0, 'plan': 1, 'actionHead': 2, 'curvatureHead': 3}
# s. 0x94 is 1-5 ms behind the comma gyro on all seven cars (docs/research/lateral-timing-map-2026-10-26.md). The 0.017 this
# used to be came from the rear wheel-speed yaw, which lags the gyro by 17-32 ms.
VSA_LATENCY = 0.002


def seg_number(path):
  m = re.search(r'(?:rlog_|--|/)(\d+)(?:\.zst|\.bz2|/rlog)', path)
  return int(m.group(1)) if m else 0


def rlog_paths(args):
  out = []
  for a in args:
    if os.path.isdir(a):
      out += glob.glob(os.path.join(a, '*rlog*')) + glob.glob(os.path.join(a, '*', 'rlog*'))
    else:
      out += glob.glob(a)
  return sorted({p for p in out if not p.endswith('.lock')}, key=seg_number)


def read(paths):
  ensure_schema()
  M, CS, LAT, Y, SRC, CD = [], [], [], {}, [], []
  fingerprint = None
  for p in paths:
    raw = open(p, 'rb').read()
    if p.endswith('.zst'):
      raw = zstd.ZstdDecompressor().stream_reader(raw).read()
    try:
      for e in log.Event.read_multiple_bytes(raw):
        try:
          w = e.which()
        except Exception:  # an event this schema cannot name
          continue
        t = e.logMonoTime * 1e-9
        if w == 'modelV2':
          m = e.modelV2
          vx = np.maximum(np.array(m.velocity.x), 1.0)
          M.append(np.r_[t, m.timestampEof * 1e-9, np.array(m.orientationRate.z) / vx, vx])
        elif w == 'carState':
          CS.append((t, e.carState.vEgo, e.carState.steeringPressed, e.carState.cruiseState.enabled))
        elif w == 'carControl':
          LAT.append((t, e.carControl.latActive))
        elif w == 'starpilotModelV2':
          try:
            SRC.append((t, int(e.starpilotModelV2.lateralSource.raw)))
          except AttributeError:  # a build without the field
            pass
        elif w == 'logMessage':
          # 7.x: modeld logs the source when it changes, rather than publishing it
          if 'modelLateralSource' in e.logMessage:
            m = re.search(r'"source":\s*"(\w+)"', e.logMessage)
            if m and m.group(1) in SOURCE_CODES:
              SRC.append((t, SOURCE_CODES[m.group(1)]))
        elif w == 'starpilotLateralState':
          st = e.starpilotLateralState
          # a build from before these fields reads 0 for both: no calibration name means not logged, not "no delay"
          CD.append((t, st.epsCommandDelay if st.epsCalibration else np.nan))
        elif w == 'carParams' and fingerprint is None:
          fingerprint = str(e.carParams.carFingerprint)
        elif w == 'can':
          for c in e.can:
            if c.address == 0x94:
              Y.setdefault(c.src, []).append((t, (c.dat[0] << 2) | (c.dat[1] >> 6)))
    except Exception as ex:  # a truncated last segment
      print(f'  (partial read {p}: {ex})', file=sys.stderr)
  return [np.array(x, float) for x in (M, CS, LAT, SRC, CD)], {k: np.array(v, float) for k, v in Y.items()}, fingerprint


def car_curvature(Y, CS, fingerprint):
  ensure_schema()
  # scale and clockwise correction from opendbc's per-car calibration (GPS-checked); 0x94 is read on whichever bus
  # carries it (Clarity 0, Bosch 1). An uncalibrated car falls back to the nominal 0.25 deg/s per count.
  scale, cal_zero, right = YAW_RATE_CALIBRATION.get(fingerprint, (0.25, 512.0, 0.0))
  bus = max(Y, key=lambda b: len(Y[b]))
  y = Y[bus]
  v = np.interp(y[:, 0], CS[:, 0], CS[:, 1])
  stopped = v < 0.01
  zero = y[stopped, 1].mean() if stopped.sum() > 100 else cal_zero  # the zero drifts by unit and temperature
  yaw = np.radians([yaw_rate_deg_s(c, scale, right) for c in y[:, 1] - zero])
  k = np.convolve(yaw / np.maximum(v, 0.5), np.ones(5) / 5, 'same')
  return y[:, 0] - VSA_LATENCY, k, bus, zero


SOURCE_NAMES = {0: 'unknown', 1: 'plan', 2: 'actionHead', 3: 'curvatureHead'}  # custom.capnp LateralSource


def step(arr, t, default):
  # the latest logged value at each time (a zero-order hold); default before the first one or when nothing is logged
  if not len(arr):
    return np.full(len(t), default, float)
  i = np.searchsorted(arr[:, 0], t, side='right') - 1
  return np.where(i >= 0, arr[np.clip(i, 0, None), 1], default)


def odometer(t, v):
  """Distance travelled at each sample time, m (trapezoid over vEgo). Only differences over a window mean anything:
  a hole in the log is integrated across, so windows over holes are masked out by the caller."""
  return np.r_[0.0, np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(t))]


def plan_distance(vplan):
  """Distance each plan frame plans to have covered by every T_IDX, m. vplan: (frames, 33) planned speed."""
  return np.c_[np.zeros(len(vplan)), np.cumsum(0.5 * (vplan[:, 1:] + vplan[:, :-1]) * np.diff(T_IDX), axis=1)]


def fit_shift(tf, plan, yt, k, vplan=None, vframe=None, dy=None):
  """Best shift of the car's curvature against each frame's plan, in seconds, with and without a fitted gain.
  Time alignment (vplan None): the plan at tf + T against the car at tf + T + s.
  Distance alignment: the plan at the distance it expects to have covered by T against the car at the same distance
  travelled since tf (dy: the car's odometer at the times yt), moved by s * vframe, so that s stays in seconds.
  Returns (shift, shift with gain, gain). The gain is the factor on the plan that best explains the car (car = g * plan)."""
  pf = plan[:, T_FIT]
  pp = float(np.sum(pf * pf))
  if vplan is not None:
    s0 = np.interp(tf, yt, dy)
    splan = plan_distance(vplan)[:, T_FIT]
  e0, eg, gains = [], [], []
  for s in SHIFTS:
    if vplan is None:
      car = np.interp(tf[:, None] + T_IDX[T_FIT][None, :] + s, yt, k)
    else:
      car = np.interp(np.interp(s0[:, None] + splan + s * vframe[:, None], dy, yt), yt, k)
    cp, cc = float(np.sum(car * pf)), float(np.sum(car * car))
    e0.append(cc - 2.0 * cp + pp)
    eg.append(cc - cp * cp / pp)
    gains.append(cp / pp)
  ig = int(np.argmin(eg))
  return float(SHIFTS[int(np.argmin(e0))]), float(SHIFTS[ig]), float(gains[ig])


def best_shift(tf, plan, yt, k):
  return fit_shift(tf, plan, yt, k)[0]


def speed_term(tf, vplan, yt, dy):
  """Per frame, how much later (s) the car reaches the plan's T_SPEED[1] point from its T_SPEED[0] point, by speed alone:
  the car's time to cover the distance the plan covers between them, less the plan's time. > 0: slower than planned."""
  lo, hi = T_SPEED
  sp = plan_distance(vplan)
  span = np.array([np.interp(hi, T_IDX, r) - np.interp(lo, T_IDX, r) for r in sp])
  start = np.interp(tf + lo, yt, dy)
  return np.interp(start + span, dy, yt) - (tf + lo) - (hi - lo)


def main():
  ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
  ap.add_argument('paths', nargs='+', help='route directory or rlog glob (quote globs)')
  ap.add_argument('--schema-root', help='a 7.x build whose cereal is <root>/openpilot/cereal (reads its logs with its schema)')
  args = ap.parse_args()
  load_schema(args.schema_root)
  paths = rlog_paths(args.paths)
  if not paths:
    sys.exit('no rlogs found')
  (M, CS, LAT, SRC, CD), Y, fingerprint = read(paths)
  if len(M) < 100 or not Y:
    sys.exit('need modelV2 and the 0x94 yaw sensor in the logs')
  yt, k, bus, zero = car_curvature(Y, CS, fingerprint)
  tm, tf, plan, vplan = M[:, 0], M[:, 1], M[:, 2:35], M[:, 35:68]
  plan = plan * np.sign(np.corrcoef(np.interp(tf + 0.5, yt, k), plan[:, 10])[0, 1])
  v = np.interp(tm, CS[:, 0], CS[:, 1])
  dcs = odometer(CS[:, 0], CS[:, 1])
  dy = np.interp(yt, CS[:, 0], dcs) + 1e-6 * np.arange(len(yt))  # strictly increasing: it is inverted below
  engaged = np.interp(tm, LAT[:, 0], LAT[:, 1]) > 0.5
  near_takeover = np.interp(tm, CS[:, 0], (np.convolve(CS[:, 2], np.ones(200), 'same') > 0).astype(float)) > 0.5
  cruise = np.interp(tm, CS[:, 0], CS[:, 3]) > 0.5
  # a frame's window (frame to frame + 1.5 s, and the shifts either side) must not run over a hole in the log
  holes = CS[:-1, 0][np.diff(CS[:, 0]) > 0.2]
  covered = (np.searchsorted(holes, tf + 2.0) - np.searchsorted(holes, tf - 0.3) == 0) & (tf - 0.3 > yt[0]) & (tf + 2.0 < yt[-1])
  k_now = np.abs(plan[:, 0])
  k_ahead = np.abs(np.array([np.interp(0.5, T_IDX, row) for row in plan]))
  turning = engaged & ~near_takeover & covered & (np.maximum(k_now, k_ahead) > 0.006)
  town = (v > 3) & (v < 12)
  phases = {
    'entry': turning & town & (k_ahead > 1.25 * k_now),
    'exit': turning & town & (k_ahead < 0.8 * k_now),
    'all turns 5-12 m/s': turning & (v > 5) & (v < 12),
  }
  minutes = (CS[-1, 0] - CS[0, 0]) / 60
  eng_min = np.mean(np.interp(CS[:, 0], LAT[:, 0], LAT[:, 1]) > 0.5) * minutes
  takeovers = int(np.sum(np.diff((CS[:, 2] > 0.5).astype(int)) == 1))
  where = os.path.dirname(paths[0]) or '.'
  print(f'{where}: {fingerprint}, {len(paths)} segments, {eng_min:.0f} engaged min, yaw bus {bus} (zero {zero:.1f}), '
        + f'model frame -> publish {np.median(tm - tf) * 1000:.0f} ms, cruise on {np.mean(cruise[engaged]) * 100:.0f}% of engaged frames')
  # The shift depends on how the controller ran the model: a plan model runs with no command delay, an action head
  # with its calibration's. Report each lateral source on its own, with the command delay it actually ran.
  src = step(SRC, tm, -1)
  cmd = step(CD, tm, np.nan)
  for code in np.unique(src):
    sel = src == code
    if not any((m & sel).any() for m in phases.values()):
      continue  # e.g. the few frames before the first lateral-source message
    name = SOURCE_NAMES.get(int(code), 'not logged')
    c = cmd[sel & (v > 5) & (v < 12) & np.isfinite(cmd)]
    applied = f'{np.median(c):.2f} s' if len(c) else 'not logged'
    print(f"car vs the model's plan, s (negative = early): lateral source {name}, town command delay {applied}")
    for phase, m in phases.items():
      m = m & sel
      on, off = int((m & cruise).sum()), int((m & ~cruise).sum())
      if m.sum() < 150:
        print(f'  {phase:20s}       -   (only {m.sum()} frames: cruise on {on} / off {off})')
        continue
      ts, tg, tgain = fit_shift(tf[m], plan[m], yt, k)
      ds, dg, dgain = fit_shift(tf[m], plan[m], yt, k, vplan[m], v[m], dy)
      sp = np.median(speed_term(tf[m], vplan[m], yt, dy))
      v_plan = np.median([np.interp(1.0, T_IDX, r) for r in vplan[m]])
      v_car = np.median(np.interp(tf[m] + 1.0, CS[:, 0], CS[:, 1]))
      print(f'  {phase:20s} time {ts:+.2f} (gain {tg:+.2f} @ {tgain:.2f})   distance {ds:+.2f} (gain {dg:+.2f} @ {dgain:.2f})   '
            + f'speed {sp:+.2f} (at +1 s plan {v_plan:.1f} / car {v_car:.1f} m/s)   ({m.sum()} frames: cruise on {on} / off {off})')
  print(f'takeovers: {takeovers} ({takeovers / max(eng_min, 0.1):.2f} per engaged minute)')


if __name__ == '__main__':
  main()
