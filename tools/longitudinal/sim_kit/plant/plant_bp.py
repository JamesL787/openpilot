"""Bob's table plant plus a brake transient-excess term (replay/log fit, scratch, not driven).

The real Civic Bosch-A brakes go past a held brake command for the first ~1-2 s, then settle back toward it
(median ~0.5 m/s^2 deeper at the peak on 28 held onsets, 9 routes; d(vEgo)/dt agrees, so it is real decel, not an aEgo
artifact). A first-order lag cannot do that. Here the braking part of the table target, beyond a deadzone, passes through
a band-pass (fast low-pass minus slow low-pass) that is added to the target:

  x  = TABLE(v, u(t - LAG));  xb = min(x + EXCESS_DEADZONE, 0)
  f1 -> xb with EXCESS_TAU_FAST, f2 -> xb with EXCESS_TAU_SLOW
  a_drive -> x + EXCESS_K * (f1 - f2) with TAU_BRAKE / TAU_GAS, as in Plant

Steady state is the table (f1 = f2). Commands above -DEADZONE (most stop-end and cruise braking) get no excess.
With EXCESS_K 0 it is Bob's Plant exactly. Same API: P = PlantBP(v0, a0); a = P.step(u, v, dt, pitch=None).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plant import Plant as _Base, load_params  # noqa: E402


class Plant(_Base):
  def __init__(self, v, a, params=None):
    p = params or load_params()
    super().__init__(v, a, p)
    self.k = float(p.get('EXCESS_K', 0.0)); self.tf = float(p.get('EXCESS_TAU_FAST', 0.4))
    self.ts = float(p.get('EXCESS_TAU_SLOW', 1.0)); self.dz = float(p.get('EXCESS_DEADZONE', 1.0))
    self.os = bool(p.get('EXCESS_ONESIDED', False))
    self.f1 = self.f2 = None

  def table(self, v, u):
    x = super().table(v, u)
    if self.k == 0.0 or self._dt is None:
      return x
    xb = min(x + self.dz, 0.0)
    if self.f1 is None:
      self.f1 = self.f2 = xb
    self.f1 += (xb - self.f1) * min(self._dt / self.tf, 1.0)
    self.f2 += (xb - self.f2) * min(self._dt / self.ts, 1.0)
    ex = self.f1 - self.f2
    if self.os: ex = min(ex, 0.0)   # brake onsets only; no lighter-than-table release
    return x + self.k * ex

  _dt = None

  def step(self, u, v, dt, pitch=None):
    self._dt = dt
    return super().step(u, v, dt, pitch)
