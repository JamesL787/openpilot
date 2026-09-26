"""nrdr: Clarity modified-EPS feedforward built on the EPS firmware's own control law. SHADOW ONLY for now.

The Clarity's LKAS path is not a torque command. The firmware turns our 0xE4 value into a target R5,
compares it with R6 -- a filtered steering RATE (R6 = -138.6 counts per deg/s, corr 0.98 against
steeringRateDeg) -- and runs P + D + KFF on the difference at 1 kHz. So every command first has to cancel
the firmware's own rate damping (Kp * 138.6 / 1024 = 16..36 counts per deg/s, 2-5x the rack's physical
damping), which is why vfn's angle PID trails a turn-in by ~250 ms x steering rate below 25 mph. On a turn
exit that same damping is the braking that holds the line -- which is why the symmetric rate feedforward
of 709dbba828 cut exits and was reverted.

This inverts the chain instead. A column load model (stiffness, speed stiffness, viscous, Coulomb friction,
road roll) says what motor output a motion needs; the firmware law is solved for the R5 that produces it,
rate damping included; the command map is inverted back to a lateral output. On a turn-in the load and
damping terms add, on an exit they cancel, so no hand-tuned asymmetry is needed.

Evidence, routes 00000352 / 00000353 (vfn 35ddc44b, P-minus-5 firmware):
  - E4 = -3840 * u; R5 = 7.7 * E4 ~20 ms later (corr 0.998); firmware output reproduced to 1-2 counts
    (corr 0.999) by the law in firmware_output() below.
  - Load model fitted on 352. On the held-out 353, the target this computes from the desired angle alone
    matches the R5 the car actually ran with R^2 0.79 on turning frames (|angle| > 2 deg; 0.75 below
    25 mph, 0.86 above) and explains 46% of vfn's command over all engaged frames. The kf * angle * v^2
    feedforward it would replace explains 5% or less on either measure.
  - Closed-loop replay (firmware 1 kHz + fitted plant, validated against the logged car) over plants
    deliberately unlike this model: RMS error below 25 mph 1.0-1.6 deg vs 4.2-5.2 deg; turn-in lag
    -41..+38 ms vs 204-289 ms; exits 1-10 ms vs 126-139 ms. The command is ~2x rougher.
Unknowns this shadow run is meant to measure: the 5-8 Hz stutter band of the command it would send
(the replay plant has no column resonance), load-model drift across roads, and highway behaviour.

Firmware constants are for ONE build: Clarity_Pminus5_P117to265_D737_KFF45_NoR6L2_Tracker3200_Norm1650
(rwd-xray-2026chatgpt/CLARITY_PMINUS5_TRACKER3200_NORM1650_20260728). The version string does not
identify the build, so re-check these after any reflash.
"""
import math

import numpy as np

# 0xE4 value per unit of lateral output: torqueBP/V = [0, 3840] identity, apply_torque = -u * 3840
E4_PER_OUTPUT = 3840.0

# command map, row 0 (0x13810 / 0x1388E); key = trunc(trunc(E4 * 56756 / 32768) / 4) with the no-SHLL2 decode
R5_KEY_BP = [0, 111, 222, 333, 443, 665, 887, 1108, 1663]
R5_V = [0, 2000, 4000, 6000, 8000, 12000, 16000, 20000, 30000]
KEY_CLAMP = 1663

# FUN_29C14 speed envelope: a CEILING on |key| (0x13660 / 0x136DE), speed axis in 0.5 km/h counts.
# 1774 up to 100 km/h, so the 1663 key clamp binds first until ~107 km/h; 1330 from 130 km/h.
ENVELOPE_BP = [0, 50, 100, 150, 200, 260, 300, 350, 400]
ENVELOPE_V = [1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330, 1330]

# P row 0 (0x13B5E / 0x13BDC), indexed by the command key; project-added feedforward KFF45
KP_KEY_BP = [0, 222, 443, 665, 887, 1108, 1330, 1552, 1774]
KP_V = [117, 148, 184, 220, 245, 257, 263, 265, 265]
KFF = 45.0
R5_PER_KEY = 18.04
# the same P row as pieces over |R5|: (lo, hi, Kp at lo, dKp/d|R5|), flat past the last breakpoint
KP_PIECES = [(lo * R5_PER_KEY, hi * R5_PER_KEY, kp_lo, (kp_hi - kp_lo) / ((hi - lo) * R5_PER_KEY))
             for lo, hi, kp_lo, kp_hi in zip(KP_KEY_BP[:-1], KP_KEY_BP[1:], KP_V[:-1], KP_V[1:], strict=True)]
KP_PIECES.append((KP_KEY_BP[-1] * R5_PER_KEY, math.inf, KP_V[-1], 0.0))

R6_PER_DEG_S = -138.6  # measured: NORM 1650 / tracker-1 3200
SCALE_Q8 = 252.0       # helper A * B / 256 while the request is held (measured median)

# Column load model, firmware output counts (A030 sign convention), fitted on route 00000352:
#   load = k0*th + k1*th*v^2 + c*thd + fr*tanh(thd/w) + bias + kroll*roll*v^2
# th/thd: steering-wheel deg, deg/s; v: m/s; roll: rad. R^2 0.82 in-route, 0.72 on the held-out route.
LOAD_K0 = -7.00387
LOAD_K1 = -0.21857
LOAD_C = -6.8317
LOAD_FRICTION = -314.07279
LOAD_BIAS = 20.46793
LOAD_KROLL = -7.20003
# The fit's friction width is 2 deg/s; 5 deg/s keeps the Coulomb term from flipping on desired-rate
# noise near straight driving (command roughness 0.0029 -> 0.0020 in replay, tracking nearly unchanged).
FRICTION_WIDTH_DEG_S = 5.0

DESIRED_RATE_TAU = 0.06  # s, EMA on the frame-to-frame desired-angle rate
LEAD_S = 0.07            # s, covers the output LPF plus CAN/firmware transport (~20 ms)
R5_CAP = 27000.0         # stay clear of the 30000 rail, where the classic stutter lived (route 154)
R5_CAP_ENVELOPE_FRAC = 0.9


def command_key(e4: float) -> int:
  return int(math.trunc(math.trunc(e4 * 56756 / 32768) / 4))


def key_ceiling(v_ego: float) -> float:
  return min(float(np.interp(v_ego * 3.6 * 2.0, ENVELOPE_BP, ENVELOPE_V)), KEY_CLAMP)


def r5_from_output(output: float, v_ego: float) -> float:
  """What the firmware makes of a lateral output: forward model of 0xE4 -> key -> R5."""
  key = command_key(-output * E4_PER_OUTPUT)
  mag = float(np.interp(min(abs(key), key_ceiling(v_ego)), R5_KEY_BP, R5_V))
  return math.copysign(mag, key) if key else 0.0


def output_from_r5(r5: float) -> float:
  """Inverse of r5_from_output (up to integer truncation)."""
  key = float(np.interp(min(abs(r5), R5_V[-1]), R5_V, R5_KEY_BP))
  e4 = key * 4.0 * 32768.0 / 56756.0
  return -math.copysign(e4, r5) / E4_PER_OUTPUT


def firmware_kp(r5: float) -> float:
  return float(np.interp(abs(r5) / R5_PER_KEY, KP_KEY_BP, KP_V))


def firmware_output(r5: float, steering_rate_deg_s: float) -> float:
  """Steady-state firmware output for a target and a rate (D term omitted): scale*(Kp*(R5-R6) + KFF*R5)/1024/256."""
  r6 = R6_PER_DEG_S * steering_rate_deg_s
  return SCALE_Q8 * (firmware_kp(r5) * (r5 - r6) + KFF * r5) / 1024.0 / 256.0


def column_load(angle_deg: float, rate_deg_s: float, v_ego: float, roll: float) -> float:
  return (LOAD_K0 * angle_deg + LOAD_K1 * angle_deg * v_ego ** 2 + LOAD_C * rate_deg_s
          + LOAD_FRICTION * math.tanh(rate_deg_s / FRICTION_WIDTH_DEG_S) + LOAD_BIAS + LOAD_KROLL * roll * v_ego ** 2)


def r5_for_motion(load: float, rate_deg_s: float, r5_guess: float = 0.0) -> float:
  """Solve the firmware law for the target that yields `load` while the wheel moves at `rate_deg_s`.

  load = scale * (Kp*(R5 - R6) + KFF*R5) / 1024 / 256, with Kp piecewise linear in |R5|. On each piece
  that is a quadratic in R5, so solve every piece exactly and keep the root nearest `r5_guess` (more than
  one root only exists when a fast unwind outruns a small target). A fixed-point iteration is not enough
  here: it is 1-4% off after three passes from rest and need not contract during a fast unwind.
  """
  x = 1024.0 * load * 256.0 / SCALE_Q8
  r6 = R6_PER_DEG_S * rate_deg_s
  roots = []
  for lo, hi, kp_lo, slope in KP_PIECES:
    for side in (1.0, -1.0):
      # on this piece Kp = a + b*R5, and R5*(Kp + KFF) - Kp*R6 = x
      a, b = kp_lo - slope * lo, slope * side
      qa, qb, qc = b, a + KFF - b * r6, -(a * r6 + x)
      if abs(qa) < 1e-12:
        candidates = [-qc / qb]
      else:
        disc = qb * qb - 4.0 * qa * qc
        if disc < 0.0:
          continue
        candidates = [(-qb + sq) / (2.0 * qa) for sq in (math.sqrt(disc), -math.sqrt(disc))]
      roots += [r for r in candidates if lo <= side * r <= hi]
  # g(R5) = R5*(Kp + KFF) - Kp*R6 - x runs from -inf to +inf, so a root always exists
  return min(roots, key=lambda r: abs(r - r5_guess))


class ClarityEpsFirmwareFeedforward:
  def __init__(self, dt: float):
    self.dt = dt
    self.alpha = dt / (DESIRED_RATE_TAU + dt)
    self.reset()

  def reset(self):
    self.prev_angle = None
    self.rate = 0.0
    self.r5 = 0.0
    self.load = 0.0
    self.output = 0.0

  def update(self, desired_angle_no_offset: float, v_ego: float, roll: float) -> float:
    if self.prev_angle is not None:
      raw_rate = (desired_angle_no_offset - self.prev_angle) / self.dt
      self.rate += self.alpha * (max(min(raw_rate, 400.0), -400.0) - self.rate)
    self.prev_angle = desired_angle_no_offset

    angle = desired_angle_no_offset + LEAD_S * self.rate
    self.load = column_load(angle, self.rate, v_ego, roll)
    cap = min(R5_CAP, R5_CAP_ENVELOPE_FRAC * float(np.interp(key_ceiling(v_ego), R5_KEY_BP, R5_V)))
    self.r5 = max(min(r5_for_motion(self.load, self.rate, self.r5), cap), -cap)
    self.output = output_from_r5(self.r5)
    return self.output
