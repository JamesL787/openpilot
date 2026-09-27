"""nrdr: the modified-EPS lateral controller built on the EPS firmware's own control law (Clarity and Civic Bosch C020).

Ported from JamesL787/openpilot vfn-controller-shadow (shadow 52618f42, controller 8c3a3fd8, output LPF fd815ef3).
The feedforward and ClarityEpsLateralCore below are upstream's, line for line, with the firmware constants moved
into a calibration and the fixed P/I trims into arguments, so the Civic Bosch C020 image can use its own. The
feedforward is logged in shadow by LatControlPID; NrdrLatEpsFirmwareFF hands the car to LatControlClarityEps,
which runs ClarityEpsLateralCore exactly as upstream does on the Clarity (STATUS 164-166).

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
    feedforward it replaces explains 5% or less on either measure.

Firmware constants are for ONE build: Clarity_Pminus5_P117to265_D737_KFF45_NoR6L2_Tracker3200_Norm1650
(rwd-xray-2026chatgpt/CLARITY_PMINUS5_TRACKER3200_NORM1650_20260728). The version string does not
identify the build, so re-check these after any reflash. CIVIC_BOSCH_C020 below is the owner's image, see
its own comment and STATUS 163.
"""
import math

import numpy as np

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.pid import PIDController

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

# Smoothing, picked in the closed-loop replay of route 352 over three plants (nominal, the 353 fit, +15 ms
# motor lag): unsmoothed, the command carried 3.8x vfn's 5-8 Hz content (the Clarity column's stutter band);
# with these it is 1.14x, for RMS error below 25 mph 2.3 deg vs vfn's 4.7, turn-in lag 10-20 ms vs 250 and
# exits 50 ms vs 130. A longer lead bought back turn-in but started 25-50 mph exits early, so it stays 0.07.
DESIRED_RATE_TAU = 0.10  # s, EMA on the frame-to-frame desired-angle rate
LEAD_S = 0.07            # s, covers the output LPF plus CAN/firmware transport (~20 ms)
FF_OUTPUT_TAU = 0.15     # s, first-order smoothing of the feedforward itself
R5_CAP = 27000.0         # stay clear of the 30000 rail, where the classic stutter lived (route 154)
R5_CAP_ENVELOPE_FRAC = 0.9

# ClarityEpsLateralCore. The feedback path is vfn 35ddc44b's modified-EPS angle PID with the P/I trims the car
# ran on it (2026-09-26, LatPScale 125/100/125, LatIScale 70/95/35), fixed here because the replay validated
# the feedforward against exactly that PID. The output LPF is the NRDR setting (these are the car's values).
MPH_TO_MS = 0.44704
BAND_LOW_MAX = 25.0 * MPH_TO_MS
BAND_STD_MAX = 50.0 * MPH_TO_MS
P_SCALE = (1.25, 1.00, 1.25)
I_SCALE = (0.70, 0.95, 0.35)
OUTPUT_LPF_TAU = (0.07, 0.05, 0.01)
INTEGRATOR_MIN_SPEED = 2.0  # m/s, below this the integrator is held at zero (as vfn)

# The Civic Bosch C020 the same way: fixed to the P/I trims the owner's car ran on route 00000284 (initData:
# LatPScale 115/125/115, LatIScale 75/95/100), the drive the C020 calibration was checked against. The output
# LPF keeps upstream's values: this branch filters the target instead (HondaLpfTau*), so it has no car value
# for an output filter, and upstream has no HondaTorqueOutputLpfTau* keys here to read.
CIVIC_P_SCALE = (1.15, 1.25, 1.15)
CIVIC_I_SCALE = (0.75, 0.95, 1.00)

# The feedforward asks for the torque that moves the wheel ALONG the desired path, so it is only right
# once the wheel is on it. Engaging mid-turn at low speed routinely starts 20-70 deg off (45 engagements on
# routes 352/353/34f), where it would have pushed against the PID at up to 0.9. So it joins only once the
# angle error is small, then fades in; a driver press or dropping below walking speed takes it out again.
FF_JOIN_ERROR_DEG = 10.0
FF_FADE_IN_S = 0.5
# m/s, faded in with speed; the desired angle is ill-conditioned near standstill. nrdr: upstream is [2, 4].
# Moved to [4, 8] (STATUS 170): on the Civic's first drive (286) the wheel wobbled ~1 Hz, +-3.5 deg, pulling
# away from a stop, 0.4-3 Hz wheel rms 1.44 deg at 2-5 m/s against 0.22-0.44 on six PID drives. The
# feedforward makes the EPS follow the model's low-speed desired-angle wiggle almost 1:1. Closed-loop sim
# (C020 plant, 5 routes): 2-5 m/s wobble 0.87 -> 0.59 (PID 0.55), <25 mph turn entry 0.82 -> 0.75 (PID 0.61).
# Sim and one drive on the Civic only; not driven on this value, and never on a Clarity.
FF_SPEED_BP = [4.0, 8.0]


class EpsFirmwareCalibration:
  """The per-image constants of the chain above. The law, KFF, SCALE_Q8 and the load model are shared."""

  def __init__(self, e4_per_output, r5_key_bp, r5_v, envelope_bp, envelope_v, r6_per_deg_s, r5_per_key=None):
    self.e4_per_output = e4_per_output
    self.r5_key_bp = r5_key_bp
    self.r5_v = r5_v
    self.envelope_bp = envelope_bp
    self.envelope_v = envelope_v
    self.r6_per_deg_s = r6_per_deg_s
    if r5_per_key is not None:
      # upstream's form: the Clarity map is linear (18.02-18.06 R5 per key), so the P row scales straight over
      self.kp_pieces = KP_PIECES
    else:
      # a non-linear map: Kp(key(|R5|)) is still piecewise linear in |R5|, on the union of both tables' knots
      knots = sorted(set(r5_v) | {float(np.interp(k, r5_key_bp, r5_v)) for k in KP_KEY_BP if k <= r5_key_bp[-1]})
      kps = [float(np.interp(np.interp(r, r5_v, r5_key_bp), KP_KEY_BP, KP_V)) for r in knots]
      self.kp_pieces = [(lo, hi, kp_lo, (kp_hi - kp_lo) / (hi - lo))
                        for lo, hi, kp_lo, kp_hi in zip(knots[:-1], knots[1:], kps[:-1], kps[1:], strict=True)]
      self.kp_pieces.append((knots[-1], math.inf, kps[-1], 0.0))
    self.kp_r5_bp = [p[0] for p in self.kp_pieces]
    self.kp_r5_v = [p[2] for p in self.kp_pieces]


CLARITY_A020 = EpsFirmwareCalibration(E4_PER_OUTPUT, R5_KEY_BP, R5_V, ENVELOPE_BP, ENVELOPE_V, R6_PER_DEG_S,
                                      r5_per_key=R5_PER_KEY)

# Civic Bosch 39990-TBA C020, the owner's image
# 39990-TBA,C020-20260805-ClarityPminus5-P117to265-D737-KFF45-Norm1650-Trk4500-TargetMapD-Telem-SpeedClamp0-Pclamp7373
# (eps_tools/rwd/). Tables read from that image; the rest checked against its telemetry (bus 1 0x6A1/0x6A2,
# R5 = err + X + R6) on route 00000284, STATUS 163:
#   - E4 = -4096 * u (torqueBP/V = [0, 4096] identity). Key decode and the 1663 clamp (0x137F2) as the Clarity:
#     the largest R5 on 284 is 28497, row 1 at key 1663.
#   - Command map row 1 (axis 0x13806, R5 0x13872). All seven rows share the R5 row and differ in the key axis;
#     row 1 matches the telemetry R5 10 ms after the E4 to 94 counts RMS at 11-20 m/s and 31 above 20 m/s
#     (row 0: 200 / 179, rows 2-6: 119-1987). What selects the row is not decoded.
#   - P row (0x13BAE axis / 0x13BC0) is the Clarity's, D 737, KFF45, Norm 1650.
#   - R6 = -173 counts per deg/s of carState.steeringRateDeg (-169.9 on segments 27-28 alone). The tracker word
#     (4500) is the R6 low-pass alpha, unity DC gain, so it does not enter here (STATUS 161).
#   - Speed envelope (axis 0x13644, values 0x136C2): 1552 from 120 km/h, 1108 from 160. NOT checked, 284 never
#     passed 89 km/h, and what SpeedClamp0 disables is not decoded.
# The column load model is still the Clarity's: refitting it on 284 alone did not beat it on held-out segments.
CIVIC_BOSCH_C020 = EpsFirmwareCalibration(
  e4_per_output=4096.0,
  r5_key_bp=[0, 115, 254, 449, 654, 862, 1111, 1549, 1774],
  r5_v=[0, 1926, 4938, 8455, 12036, 15926, 20138, 26955, 30000],
  envelope_bp=[0, 50, 100, 150, 200, 240, 300, 321, 400],
  envelope_v=[1774, 1774, 1774, 1774, 1774, 1552, 1219, 1108, 1108],
  r6_per_deg_s=-173.0,
)


def command_key(e4: float) -> int:
  return int(math.trunc(math.trunc(e4 * 56756 / 32768) / 4))


def key_ceiling(v_ego: float, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  return min(float(np.interp(v_ego * 3.6 * 2.0, cal.envelope_bp, cal.envelope_v)), KEY_CLAMP)


def r5_from_output(output: float, v_ego: float, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  """What the firmware makes of a lateral output: forward model of 0xE4 -> key -> R5."""
  key = command_key(-output * cal.e4_per_output)
  mag = float(np.interp(min(abs(key), key_ceiling(v_ego, cal)), cal.r5_key_bp, cal.r5_v))
  return math.copysign(mag, key) if key else 0.0


def output_from_r5(r5: float, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  """Inverse of r5_from_output (up to integer truncation)."""
  key = float(np.interp(min(abs(r5), cal.r5_v[-1]), cal.r5_v, cal.r5_key_bp))
  e4 = key * 4.0 * 32768.0 / 56756.0
  return -math.copysign(e4, r5) / cal.e4_per_output


def firmware_kp(r5: float, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  return float(np.interp(abs(r5), cal.kp_r5_bp, cal.kp_r5_v))


def firmware_output(r5: float, steering_rate_deg_s: float, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  """Steady-state firmware output for a target and a rate (D term omitted): scale*(Kp*(R5-R6) + KFF*R5)/1024/256."""
  r6 = cal.r6_per_deg_s * steering_rate_deg_s
  return SCALE_Q8 * (firmware_kp(r5, cal) * (r5 - r6) + KFF * r5) / 1024.0 / 256.0


def column_load(angle_deg: float, rate_deg_s: float, v_ego: float, roll: float,
                friction_width: float = FRICTION_WIDTH_DEG_S) -> float:
  return (LOAD_K0 * angle_deg + LOAD_K1 * angle_deg * v_ego ** 2 + LOAD_C * rate_deg_s
          + LOAD_FRICTION * math.tanh(rate_deg_s / friction_width) + LOAD_BIAS + LOAD_KROLL * roll * v_ego ** 2)


def r5_for_motion(load: float, rate_deg_s: float, r5_guess: float = 0.0, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  """Solve the firmware law for the target that yields `load` while the wheel moves at `rate_deg_s`.

  load = scale * (Kp*(R5 - R6) + KFF*R5) / 1024 / 256, with Kp piecewise linear in |R5|. On each piece
  that is a quadratic in R5, so solve every piece exactly and keep the root nearest `r5_guess` (more than
  one root only exists when a fast unwind outruns a small target). A fixed-point iteration is not enough
  here: it is 1-4% off after three passes from rest and need not contract during a fast unwind.
  """
  x = 1024.0 * load * 256.0 / SCALE_Q8
  r6 = cal.r6_per_deg_s * rate_deg_s
  roots = []
  for lo, hi, kp_lo, slope in cal.kp_pieces:
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
  def __init__(self, dt: float, rate_tau: float = DESIRED_RATE_TAU, lead_s: float = LEAD_S,
               output_tau: float = FF_OUTPUT_TAU, friction_width: float = FRICTION_WIDTH_DEG_S,
               cal: EpsFirmwareCalibration = CLARITY_A020):
    self.dt = dt
    self.alpha = dt / (rate_tau + dt)
    self.output_alpha = dt / (output_tau + dt)
    self.lead_s = lead_s
    self.friction_width = friction_width
    self.cal = cal
    self.reset()

  def reset(self):
    self.prev_angle = None
    self.rate = 0.0
    self.r5 = 0.0
    self.load = 0.0
    self.output = 0.0

  def update(self, desired_angle_no_offset: float, v_ego: float, roll: float) -> float:
    first = self.prev_angle is None
    if not first:
      raw_rate = (desired_angle_no_offset - self.prev_angle) / self.dt
      self.rate += self.alpha * (max(min(raw_rate, 400.0), -400.0) - self.rate)
    self.prev_angle = desired_angle_no_offset

    angle = desired_angle_no_offset + self.lead_s * self.rate
    self.load = column_load(angle, self.rate, v_ego, roll, self.friction_width)
    cap = min(R5_CAP, R5_CAP_ENVELOPE_FRAC * float(np.interp(key_ceiling(v_ego, self.cal), self.cal.r5_key_bp, self.cal.r5_v)))
    self.r5 = max(min(r5_for_motion(self.load, self.rate, self.r5, self.cal), cap), -cap)
    target = output_from_r5(self.r5, self.cal)
    self.output = target if first else self.output + self.output_alpha * (target - self.output)
    return self.output


def speed_band(v_ego: float, values):
  return values[0] if v_ego < BAND_LOW_MAX else values[1] if v_ego < BAND_STD_MAX else values[2]


class ClarityEpsLateralCore:
  """Angle PID on the residual + firmware-inversion feedforward, faded in once the wheel is on the path.

  Pure (no messaging, no params), so the closed-loop replay can drive exactly the code the car runs.
  """

  def __init__(self, kp_bp, kp_v, ki_bp, ki_v, dt: float, ff: ClarityEpsFirmwareFeedforward | None = None,
               p_scale=P_SCALE, i_scale=I_SCALE):
    self.dt = dt
    self.p_scale = p_scale
    self.i_scale = i_scale
    self.pid = PIDController((kp_bp, kp_v), (ki_bp, ki_v), pos_limit=1.0, neg_limit=-1.0, rate=1.0 / dt)
    self.ff = ff if ff is not None else ClarityEpsFirmwareFeedforward(dt)
    # The NRDR torque-output LPF, run exactly as LatControlPID runs it (the car controller deliberately does
    # not filter, so this is the only one): same filter class, same per-band update_alpha, reset to 0.
    self.output_lpf = FirstOrderFilter(0.0, OUTPUT_LPF_TAU[0], dt)
    self.reset()

  def reset(self):
    self.pid.reset()
    self.ff.reset()
    self.ff_ramp = 0.0
    self.ff_weight = 0.0
    self.output_lpf.x = 0.0
    self.output_lpf.initialized = True
    self.output = 0.0

  output_lpf_enabled = True
  output_lpf_tau = OUTPUT_LPF_TAU

  def update(self, desired_angle_no_offset: float, angle_offset: float, angle: float, v_ego: float, roll: float,
             steering_pressed: bool, steer_limited: bool) -> float:
    error = desired_angle_no_offset + angle_offset - angle
    ff_full = self.ff.update(desired_angle_no_offset, v_ego, roll)

    if steering_pressed or v_ego < FF_SPEED_BP[0]:
      self.ff_ramp = 0.0
    elif self.ff_ramp > 0.0 or abs(error) < FF_JOIN_ERROR_DEG:
      self.ff_ramp = min(1.0, self.ff_ramp + self.dt / FF_FADE_IN_S)
    self.ff_weight = self.ff_ramp * float(np.interp(v_ego, FF_SPEED_BP, [0.0, 1.0]))
    ff = self.ff_weight * ff_full

    i_scale = speed_band(v_ego, self.i_scale)
    self.pid.update(error, speed=v_ego, feedforward=ff,
                    freeze_integrator=steer_limited or steering_pressed or v_ego < INTEGRATOR_MIN_SPEED,
                    integrator_gain_scale=i_scale,
                    reset_integrator=i_scale <= 0.0 or v_ego < INTEGRATOR_MIN_SPEED)
    output = max(min(self.pid.p * speed_band(v_ego, self.p_scale) + self.pid.i + self.pid.d + ff, 1.0), -1.0)

    if self.output_lpf_enabled:
      self.output_lpf.update_alpha(speed_band(v_ego, self.output_lpf_tau))
      output = float(self.output_lpf.update(output))
    else:
      self.output_lpf.x = output
      self.output_lpf.initialized = True
    self.output = max(min(output, 1.0), -1.0)
    return self.output
