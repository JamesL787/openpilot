"""nrdr: modified-EPS lateral controller built on the EPS firmware law (Clarity, Civic Bosch C020, CR-V A040 FF45).

Ported from JamesL787/openpilot vfn-controller-shadow (shadow 52618f42, controller 8c3a3fd8, output LPF fd815ef3).
The feedforward and HondaEpsLateralCore below are upstream's, line for line, with the firmware constants moved
into a calibration and the fixed P/I trims into arguments, so each traced firmware image can use its own. The
feedforward is logged in shadow by LatControlPID; NrdrLatEpsFirmwareFF hands the car to LatControlHondaEps,
which runs HondaEpsLateralCore exactly as upstream does on the Clarity (STATUS 164-166).

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

The default firmware constants are for ONE build: Clarity_Pminus5_P117to265_D737_KFF45_NoR6L2_Tracker3200_Norm1650
(rwd-xray-2026chatgpt/CLARITY_PMINUS5_TRACKER3200_NORM1650_20260728). The version string does not
identify the build, so re-check these after any reflash. CIVIC_BOSCH_C020 below is the owner's image, see
its own comment and STATUS 163. The CR-V A040 FF45 calibration and route fit are documented in STATUS 224/D-091.
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
CLARITY_LOAD = (LOAD_K0, LOAD_K1, LOAD_C, LOAD_FRICTION, LOAD_BIAS, LOAD_KROLL)
# The fit's friction width is 2 deg/s; 5 deg/s keeps the Coulomb term from flipping on desired-rate
# noise near straight driving (command roughness 0.0029 -> 0.0020 in replay, tracking nearly unchanged).
# Keyed on the DESIRED rate, even 5 deg/s turns the model's small path wiggles into a friction square wave in the
# city: closed-loop sim, a +/-2 deg 1 Hz wiggle at 10 m/s comes out at the wheel with gain 1.63 on the C020 (1.40
# Clarity); with 20 deg/s 1.22 (0.96), and turn-ins (30-200 deg/s) keep the full friction. The price is lag on slow,
# small motions, which only pays off at city speed (upstream vfn b45f7a23, Clarity routes 35e/360/361: 0.6-2 Hz
# wheel/target 0.93 -> 0.76 at 10-16 m/s for +10 ms; a global 20 deg/s cost +45 ms above 16 m/s for nothing).
# So 20 deg/s up to 8 m/s, back to 5 by 15 m/s.
FRICTION_WIDTH_DEG_S = 5.0
FRICTION_WIDTH_SPEED_BP = [8.0, 15.0]  # m/s
FRICTION_WIDTH_V = [20.0, FRICTION_WIDTH_DEG_S]  # deg/s


def friction_width(v_ego: float) -> float:
  return float(np.interp(v_ego, FRICTION_WIDTH_SPEED_BP, FRICTION_WIDTH_V))


# Smoothing, picked in the closed-loop replay of route 352 over three plants (nominal, the 353 fit, +15 ms
# motor lag): unsmoothed, the command carried 3.8x vfn's 5-8 Hz content (the Clarity column's stutter band);
# with these it is 1.14x, for RMS error below 25 mph 2.3 deg vs vfn's 4.7, turn-in lag 10-20 ms vs 250 and
# exits 50 ms vs 130. A longer lead bought back turn-in but started 25-50 mph exits early, so it stays 0.07.
DESIRED_RATE_TAU = 0.10  # s, EMA on the frame-to-frame desired-angle rate
LEAD_S = 0.07            # s, covers the output LPF plus CAN/firmware transport (~20 ms)
FF_OUTPUT_TAU = 0.15     # s, first-order smoothing of the feedforward itself
R5_CAP = 27000.0         # stay clear of the 30000 rail, where the classic stutter lived (route 154)
R5_CAP_ENVELOPE_FRAC = 0.9

# HondaEpsLateralCore. The feedback path is vfn 35ddc44b's modified-EPS angle PID with the P/I trims the car
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
FF_SPEED_BP = [2.0, 4.0]    # m/s, faded in with speed; the desired angle is ill-conditioned near standstill
# At a crawl the feedforward passes the model's small desired-angle wiggle to the wheel almost 1:1, and column
# stiction makes that grow with amplitude: the Civic's first drive (286) wobbled ~1 Hz, +-3.5 deg, pulling away
# from a stop (STATUS 170/173), and so did the Clarity hands off (route 361 t 823-829, target -> wheel 1.02 below
# 4 m/s against 0.41 for the PID alone). So below FF_CRAWL_SPEED_BP the feedforward joins with |desired angle|
# (none under 5 deg, all from 20 deg: every real crawl turn), fading out of effect by 8 m/s. It replaces the
# 10-30 deg gate that applied at every speed, which also held the feedforward off on the highway (weight 0.07 at
# 12-20 m/s, 0 above). Replay of hands-off chunks of routes 287/289/294 through firmware + the C020 column plant,
# against that gate: RMS error 1.25 -> 0.92 deg at 8-12 m/s and 0.58 -> 0.41 at 12-16, turn (|des| > 20) error
# 2.97 -> 1.93, and 0.6-2 Hz wheel/target ~1.0 either way; the gate reaching up to 12 or 15 m/s bought nothing.
FF_CRAWL_ANGLE_BP = [5.0, 20.0]  # deg
FF_CRAWL_SPEED_BP = [5.0, 8.0]   # m/s
# At speed the feedforward also applies near straight (weight 1 from 8 m/s). An opt-in 10-30 deg gate above the
# crawl band (NrdrLatEpsFfAngleGate) was tried against the PR 10 sim verdict's highway wiggle (sha1 15223963: F2
# wig ratio, unitless 0.6-2 Hz wheel/desired, 0.84 -> 1.26 hands off at 45 mph and 0.91-1.21 -> 1.63-2.03 on the
# route-296 replays) and removed 2026-09-30 (owner's call). In the P' sim rounds (R2-R4) it was no smoother than
# without it, and its step fails against the pre-PR 10 controller were not shown to come from the gate. On the
# road (limited road evidence, steeringRateDeg, hands off, |dcurv| < 0.0005, 22.4-25 m/s only; 16-25 m/s reads
# 1.31 vs 1.00) route 298 without it read 1.10 deg/s against 0.63 on 297 (pre-PR 10), but 299 with it read 1.33
# with the feedforward at weight 0 on every straight frame, so that gap was road spread. The key stays in
# params_keys.h and is not read.
# Open question (sim only, 5-8 m/s): with the old 10-30 gate at every speed, the closed-loop sim took the 5-8 /
# 8-12 m/s wobble on route 286 from 1.03 / 0.67 to 0.27 / 0.23 (29698ea5a). Here the feedforward keeps some
# weight near straight in that band (0.62 in the P' R4 sim), and that sim read rough 0.032 vs 0.015 against the
# pre-PR 10 controller (5.0-5.7 m/s only, content not matched). Not yet checked on the road.


class EpsFirmwareCalibration:
  """Per-image constants for the shared firmware-inversion control law."""

  def __init__(self, e4_per_output, r5_key_bp, r5_v, envelope_bp, envelope_v, r6_per_deg_s, r5_per_key=None,
               kp_key_bp=KP_KEY_BP, kp_v=KP_V, key_clamp=KEY_CLAMP, scale_q8=SCALE_Q8, kff=KFF):
    self.e4_per_output = e4_per_output
    self.r5_key_bp = r5_key_bp
    self.r5_v = r5_v
    self.envelope_bp = envelope_bp
    self.envelope_v = envelope_v
    self.r6_per_deg_s = r6_per_deg_s
    self.key_clamp = key_clamp
    self.scale_q8 = scale_q8
    self.kff = kff
    if r5_per_key is not None:
      # upstream's form: the Clarity map is linear (18.02-18.06 R5 per key), so the P row scales straight over
      self.kp_pieces = KP_PIECES
    else:
      # a non-linear map: Kp(key(|R5|)) is still piecewise linear in |R5|, on the union of both tables' knots
      knots = sorted(set(r5_v) | {float(np.interp(k, r5_key_bp, r5_v)) for k in kp_key_bp if k <= r5_key_bp[-1]})
      kps = [float(np.interp(np.interp(r, r5_v, r5_key_bp), kp_key_bp, kp_v)) for r in knots]
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

# CR-V 5G 39990-TLA-A040 FF45 image. Exact tables/constants from
# 39990-TLA-A040_tq30000_a9000_t9_ff45_8cf8e537_DO_NOT_FLASH_full.bin
# (SHA-256 d5dc04a839af2c473e103f4f9d448bf600e26ea0531521a58da61e2267dc351e).
# The feedback DC scale was measured as -105.704 counts/(deg/s) on route 00000006--82bb552a2c
# with norm 1450, then scaled by the firmware-exact 1650/1450 ratio. Tracker alpha affects phase,
# not DC gain. The command map and P row are identical across all seven rows in this image.
CRV_5G_A040_FF45 = EpsFirmwareCalibration(
  e4_per_output=4096.0,
  r5_key_bp=[0, 219, 443, 662, 887, 1108, 1330, 1552, 1663],
  r5_v=[0, 1926, 4938, 8455, 12036, 15926, 20138, 26955, 30000],
  envelope_bp=[0, 400],
  envelope_v=[1774, 1774],
  r6_per_deg_s=-105.70439496 * 1650.0 / 1450.0,
  kp_key_bp=[0, 104, 279, 510, 807, 1108, 1330, 1552, 1663],
  kp_v=[117, 148, 184, 220, 245, 257, 263, 265, 265],
  key_clamp=1774,
  scale_q8=256.0,
  kff=45.0,
)

# Vehicle-load fit from 9,784 hands-off, active samples on route 00000006--82bb552a2c,
# OpenPilot 49e6610d08373bb8512ccce38d2f75c61656325e. Target is the EPS output reconstructed
# exactly from firmware telemetry. Alternating 60 s block holdouts: R^2 0.80 / 0.84.
# No roll signal was retained in the compact replay, so its coefficient is deliberately zero.
CRV_5G_EPS_LOAD = (-9.09927, -0.0225716, -5.24359, -259.312, -55.7274, 0.0)
CRV_5G_P_SCALE = (1.0, 1.0, 1.0)
CRV_5G_I_SCALE = (1.0, 1.0, 1.0)

# Civic column load for the PID's firmware feedforward only (NrdrLatPidFirmwareFF). latcontrol_honda_eps uses
# CIVIC_EPS_LOAD below. Same model and sign as LOAD_*, fitted on the owner's C020 PID drives 284, 285,
# 286, 287, 289, 28a, 28b (engaged, no press or lane change for 1 s, |command| < 0.9). Target: the firmware
# output the car's own command implies, firmware_output(r5_from_output(command), rate). Held out one route at
# a time, R^2 beats the Clarity fit on 7 of 8 routes (e.g. 28f 0.75 vs 0.66, 284 0.49 vs 0.20). On 28f's sharp
# corners at 25-50 mph (|angle| >= 25 deg) the Clarity fit asks about 1.5x the load the car used; this set ~1.2x.
# Against the Clarity fit: similar angle terms, far less rate damping (C) and roll (KROLL, cf. STATUS 168),
# and a negative bias. Refit after any reflash.
# Closed loop (lat_pid_sim gate, 11 routes) at all speeds it slowed low-speed turns on 27a (turn_err <12 mph
# 35.4 -> 36.1), so it applies from 25 mph only: gate neutral, 28f sharp-corner overshoot +3.3 -> +3.0 deg (sim).
CIVIC_PID_LOAD = (-6.2586, -0.16199, -1.6872, -303.29443, -78.01171, -0.57818)
CIVIC_PID_LOAD_MIN_V = 11.18  # m/s, 25 mph
LOAD_BLEND_V = 1.8  # m/s: blend from the Clarity fit to the car's own over 25-29 mph (a hard switch stepped up to 0.026)

# Civic column load for LatControlHondaEps on the C020, at every speed. Fitted on the firmware's OWN output rather
# than the command: P + KFF rebuilt from the bus 1 0x6A1 error telemetry (R5 = err + R6, Kp from the P row), hands
# off (not pressed, |steeringTorque| < 400), engaged above 2 m/s, jointly on routes 287 + 289 + 294, friction width
# 5 deg/s. Held out one route at a time, R^2 0.64 / 0.74 / 0.79 against 0.61 / 0.70 / 0.76 for the Clarity fit, which
# over-asks this column (actual / Clarity model 0.77-0.98 at 4-22 m/s, 0.5-0.8 at 2-4 m/s). The fit is in pre-scale
# counts (the firmware multiplies by A * B / 256 after it, 256 hands off on both cars), so it is carried to this
# module's SCALE_Q8 here. Replaying route 294's grass-island loop (t 114-134) through firmware + the C020 plant:
# RMS error 4.28 -> 3.61 deg against the Clarity fit, wheel inside the target +0.93 -> +0.64 deg. Refit after any
# reflash.
CIVIC_EPS_LOAD_PRESCALE = (-5.574, -0.1831, -4.540, -326.5, -83.6, -3.185)
CIVIC_EPS_LOAD = tuple(c * SCALE_Q8 / 256.0 for c in CIVIC_EPS_LOAD_PRESCALE)


def command_key(e4: float) -> int:
  return int(math.trunc(math.trunc(e4 * 56756 / 32768) / 4))


def key_ceiling(v_ego: float, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  return min(float(np.interp(v_ego * 3.6 * 2.0, cal.envelope_bp, cal.envelope_v)), cal.key_clamp)


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
  return cal.scale_q8 * (firmware_kp(r5, cal) * (r5 - r6) + cal.kff * r5) / 1024.0 / 256.0


def column_load(angle_deg: float, rate_deg_s: float, v_ego: float, roll: float,
                friction_width: float = FRICTION_WIDTH_DEG_S, load=None) -> float:
  k0, k1, c, fr, bias, kroll = CLARITY_LOAD if load is None else load
  return (k0 * angle_deg + k1 * angle_deg * v_ego ** 2 + c * rate_deg_s
          + fr * math.tanh(rate_deg_s / friction_width) + bias + kroll * roll * v_ego ** 2)


def r5_for_motion(load: float, rate_deg_s: float, r5_guess: float = 0.0, cal: EpsFirmwareCalibration = CLARITY_A020) -> float:
  """Solve the firmware law for the target that yields `load` while the wheel moves at `rate_deg_s`.

  load = scale * (Kp*(R5 - R6) + KFF*R5) / 1024 / 256, with Kp piecewise linear in |R5|. On each piece
  that is a quadratic in R5, so solve every piece exactly and keep the root nearest `r5_guess` (more than
  one root only exists when a fast unwind outruns a small target). A fixed-point iteration is not enough
  here: it is 1-4% off after three passes from rest and need not contract during a fast unwind.
  """
  x = 1024.0 * load * 256.0 / cal.scale_q8
  r6 = cal.r6_per_deg_s * rate_deg_s
  roots = []
  for lo, hi, kp_lo, slope in cal.kp_pieces:
    for side in (1.0, -1.0):
      # on this piece Kp = a + b*R5, and R5*(Kp + KFF) - Kp*R6 = x
      a, b = kp_lo - slope * lo, slope * side
      qa, qb, qc = b, a + cal.kff - b * r6, -(a * r6 + x)
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


class HondaEpsFirmwareFeedforward:
  def __init__(self, dt: float, rate_tau: float = DESIRED_RATE_TAU, lead_s: float = LEAD_S,
               output_tau: float = FF_OUTPUT_TAU, friction_width: float | None = None,
               cal: EpsFirmwareCalibration = CLARITY_A020, load=None, load_min_v: float = 0.0):
    self.dt = dt
    self.load_coef = load  # None: the Clarity fit (LOAD_*); see CIVIC_PID_LOAD
    self.load_min_v = load_min_v  # below this speed the Clarity fit is used; LOAD_BLEND_V above it
    self.alpha = dt / (rate_tau + dt)
    self.output_alpha = dt / (output_tau + dt)
    self.lead_s = lead_s
    self.friction_width = friction_width  # None: the speed schedule, friction_width()
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
    width = self.friction_width if self.friction_width is not None else friction_width(v_ego)
    self.load = column_load(angle, self.rate, v_ego, roll, width)
    if self.load_coef is not None and v_ego > self.load_min_v:
      own = min((v_ego - self.load_min_v) / LOAD_BLEND_V, 1.0) if self.load_min_v > 0.0 else 1.0
      self.load += own * (column_load(angle, self.rate, v_ego, roll, width, self.load_coef) - self.load)
    cap = min(R5_CAP, R5_CAP_ENVELOPE_FRAC * float(np.interp(key_ceiling(v_ego, self.cal), self.cal.r5_key_bp, self.cal.r5_v)))
    self.r5 = max(min(r5_for_motion(self.load, self.rate, self.r5, self.cal), cap), -cap)
    target = output_from_r5(self.r5, self.cal)
    self.output = target if first else self.output + self.output_alpha * (target - self.output)
    return self.output


def speed_band(v_ego: float, values):
  return values[0] if v_ego < BAND_LOW_MAX else values[1] if v_ego < BAND_STD_MAX else values[2]


class HondaEpsLateralCore:
  """Angle PID on the residual + firmware-inversion feedforward, faded in once the wheel is on the path.

  Pure (no messaging, no params), so the closed-loop replay can drive exactly the code the car runs.
  """

  def __init__(self, kp_bp, kp_v, ki_bp, ki_v, dt: float, ff: HondaEpsFirmwareFeedforward | None = None,
               p_scale=P_SCALE, i_scale=I_SCALE):
    self.dt = dt
    self.p_scale = p_scale
    self.i_scale = i_scale
    self.pid = PIDController((kp_bp, kp_v), (ki_bp, ki_v), pos_limit=1.0, neg_limit=-1.0, rate=1.0 / dt)
    self.ff = ff if ff is not None else HondaEpsFirmwareFeedforward(dt)
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
    crawl = float(np.interp(v_ego, FF_CRAWL_SPEED_BP, [1.0, 0.0]))
    crawl_gate = 1.0 - crawl * (1.0 - float(np.interp(abs(desired_angle_no_offset), FF_CRAWL_ANGLE_BP, [0.0, 1.0])))
    self.ff_weight = self.ff_ramp * float(np.interp(v_ego, FF_SPEED_BP, [0.0, 1.0])) * crawl_gate
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
