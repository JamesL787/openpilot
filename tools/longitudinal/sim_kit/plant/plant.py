"""Civic Bosch alpha-long plant: commanded accel -> achieved aEgo (replay/log fit, scratch, not driven).

Drop-in for the r3 first-order Sim plant `a += (GAIN*u - a) * dt/TAU`:

    from plant import Plant
    P = Plant(v0, a0)                  # once, at the closed-loop start
    a = P.step(u, v, dt)              # each frame: u = commanded accel, v = current sim speed (pitch ignored: default params are GRADE false)
    # then integrate v yourself as before (v += a*dt, clamp >= 0)

Model (fit.py): a_drive = TABLE(v, u(t - LAG)) through a first-order lag TAU_BRAKE (u < 0) / TAU_GAS (u >= 0);
a = a_drive - g*sin(pitch - PITCH_BIAS). TABLE is the steady-state achieved accel on flat road, piecewise linear in
u at U_KNOTS within each speed band V_KNOTS (linear between band centres). Standstill: v < 0.05 and a_drive <= 0 holds.
Pass pitch=None to skip the grade term (replay without carControl.orientationNED); then the fit's flat-road map is used.
"""
import json
import os
from collections import deque

import numpy as np

G = 9.81
PITCH_BIAS = 0.013  # rad, CC pitch minus GPS grade on this mount (bosch_hill_sim.PITCH_BIAS)
_P = os.environ.get('PLANT_PARAMS') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plant_params.json')


def load_params(path=None):
  path = path or _P
  with open(path) as f:
    return json.load(f)


class Plant:
  def __init__(self, v, a, params=None):
    p = params or load_params()
    self.vk = np.array(p['V_KNOTS']); self.uk = np.array(p['U_KNOTS']); self.T = np.array(p['TABLE'])
    self.grade = bool(p.get('GRADE', True)); self.lag = float(p['LAG']); self.tb = float(p['TAU_BRAKE']); self.tg = float(p['TAU_GAS'])
    self.a = float(a); self.v = float(v)
    self.hist = deque()  # (t, u)
    self.t = 0.0
    self.ad = float(a)  # drive accel state (grade removed); re-based on the first step's pitch
    self._first = True

  def table(self, v, u):
    rows = np.array([np.interp(u, self.uk, r) for r in self.T])
    return float(np.interp(v, self.vk, rows))

  def step(self, u, v, dt, pitch=None):
    self.t += dt
    if not self.hist:
      self.hist.append((self.t - self.lag - dt, float(u)))  # pre-history: hold the first command
    self.hist.append((self.t, float(u)))
    while len(self.hist) > 1 and self.hist[1][0] <= self.t - self.lag:
      self.hist.popleft()
    ud = self.hist[0][1]
    grade = 0.0 if (pitch is None or not self.grade) else G * np.sin(pitch - PITCH_BIAS)
    if self._first:
      self.ad += grade; self._first = False
    target = self.table(v, ud)
    tau = self.tb if ud < 0 else self.tg
    self.ad += (target - self.ad) * min(dt / tau, 1.0) if tau > 0 else (target - self.ad)
    a = self.ad - grade
    if v < 0.05 and a <= 0.0:
      a = 0.0
      self.ad = min(self.ad, grade)  # held by the brake; no wind-up below what holds the car
    self.a = a
    return a


def old_step(a, u, dt, tau=0.3, gain=1.1):
  return a + (gain * u - a) * min(dt / tau, 1.0)
