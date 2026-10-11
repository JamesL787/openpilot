"""The modified-EPS Honda lateral controller, built on the EPS firmware's own control law.

Every PTM (Proper Torque Mod) EPS image -- Clarity, Civic, Insight, CR-V -- runs the same law with its own tables, so
one controller serves them all through EpsFirmwareCalibration below. It was developed on the Clarity, so the evidence
below is the Clarity's.

The LKAS path is not a torque command. The firmware turns our 0xE4 value into a target R5, compares it with
R6 -- a filtered steering RATE, taken before its angle table (see CLARITY_TRW_A020_R6_CENTRE and R6_GAIN_BP) -- and runs
P + D + KFF on the difference at 1 kHz. So every command first has to cancel the firmware's own rate damping
(Kp * 122 / 1024 = 14..32 counts per deg/s at centre, 2-5x the rack's physical damping), which is why vfn's angle PID
trails a turn-in by ~250 ms x steering rate below 25 mph. On a turn exit that same damping is the braking that
holds the line -- which is why the symmetric rate feedforward of 709dbba828 cut exits and was reverted.

This inverts the chain instead. A column load model (stiffness, speed stiffness, viscous, Coulomb friction,
road roll) says what motor output a motion needs; the firmware law is solved for the R5 that produces it,
rate damping included; the command map is inverted back to a lateral output. On a turn-in the load and
damping terms add, on an exit they cancel, so no hand-tuned asymmetry is needed. vfn's angle PID stays on
the residual (HondaEpsLateralCore), with the gains and output filter the car ran on vfn 35ddc44b.

Evidence, routes 00000352 / 00000353 (Clarity, vfn 35ddc44b, P-minus-5 firmware):
  - E4 = -3840 * u; R5 = 7.7 * E4 ~20 ms later (corr 0.998); firmware output reproduced to 1-2 counts
    (corr 0.999) by the law in firmware_output() below.
  - Load model fitted on 352. On the held-out 353, the target this computes from the desired angle alone
    matches the R5 the car actually ran with R^2 0.79 on turning frames (|angle| > 2 deg; 0.75 below
    25 mph, 0.86 above) and explains 46% of vfn's command over all engaged frames. The kf * angle * v^2
    feedforward it replaces explains 5% or less on either measure.

Firmware constants are per IMAGE, and the version string does not identify the build, so re-check the
profile after any reflash. What each profile measured and what it only carries over is spelled out on it.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from opendbc.car.honda.steer_ratio import CLARITY_TRW_A020_VGR_ANGLE_BP, CLARITY_TRW_A020_VGR_LINEAR_BP
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import CIVIC_TBA_C020_RACK, CLARITY_TRW_A020_RACK, INSIGHT_TXM_A040_RACK, \
  RackMapTable
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.pid import PIDController


def command_key(e4: float) -> int:
  """0xE4 value -> command-map key, with the no-SHLL2 decode (every PTM image)."""
  return int(math.trunc(math.trunc(e4 * 56756 / 32768) / 4))


@dataclass(frozen=True)
class ColumnLoadModel:
  """Firmware output counts (A030 sign convention) a motion needs:
    load = k0*th + k1*th*v^2 + c*thd + friction*tanh(thd/w) + bias + kroll*roll*v^2
  th/thd: steering-wheel deg, deg/s; v: m/s; roll: rad."""
  k0: float
  k1: float
  c: float
  friction: float
  bias: float
  kroll: float


# Command delay, per vehicle: the curvature controlsd hands over is executed this much later in town, faded out
# between CMD_DELAY_SPEED_BP. Measured end to end with tools/lateral/plan_timing.py (car curvature from the VSA yaw
# sensor against the model's own plan, hands-off turns at 5-12 m/s): every car measured ran its model's plan early
# without it (early turn-in, loose exits), on this controller and on LatControlPID, and the models do not follow
# the delay they are told (Cinque v3: the same aim told 0.09 or 0.30 s; tsfdo: told 0.30 or 0.48 s), so
# SteerDelay / lagd cannot fix it. Each delay is sized at or below what was measured, so it cannot make a car late.
# - Clarity (Cinque v3): 0.12-0.14 s early (route 37e); 0.12 s took entries from -0.25 to -0.11 s (route 380).
# - Civic Bosch C020 (tsfdo): routes 290 / 293 / 289 -0.09 / -0.15 / -0.22 s, median -0.15. Checked with it on
#   (routes 2b7 / 2c6 / 2d4): -0.14 / -0.11 / +0.03 s, -0.045 weighted, against -0.15 without it on 289 / 290 / 294.
# - Insight: 0.15, inferred from a LatControlPID drive (see INSIGHT_TXM_A040).
# Unmeasured cars take the default, the smaller of the two, until plan_timing.py measures them.
CMD_DELAY_DEFAULT_S = 0.12
CMD_DELAY_SPEED_BP = (10.0, 15.0)  # m/s: the full delay below, none above (nothing was measured early on the highway)


def command_delay(cal: "EpsFirmwareCalibration", v_ego: float) -> float:
  return float(np.interp(v_ego, CMD_DELAY_SPEED_BP, (cal.cmd_delay_s, 0.0)))


# Model-delay schedule, per vehicle: the lateral delay the model is told (liveDelay.lateralDelay's role in
# lat_action_t), scheduled on speed, in place of the single SteerDelay / lagd value. Measured on the Clarity, where
# this controller's real execution delay is not one number; every other car takes the Clarity's schedule until a
# measurement on it gives a reason to change it. Each value is the measured lag of car curvature behind the logged
# model action minus the fixed pipeline offset (0.038 s), so the car reaches the requested curvature when the model
# intends it to.
# - Car curvature comes from the yaw sensor (0x94). The comma gyro runs ~50 ms behind the car and put the
#   first version of this table that much too long.
# - The lag hardly depends on the delay the model was told (5-9 m/s: 0.15 / 0.15 / 0.17 s at 0.22 / 0.30 /
#   0.48), so routes are pooled.
# - The lag is fitted with a gain per route (tools/lateral/eps_report.py timing). The first table (0.12 / 0.12 /
#   0.15 at 3.5 / 7 / 12 m/s, routes 354-36b) compared raw curves, and the car delivering only 0.85-0.96 of the
#   request there read as extra lag: on 36c-377 the car turned 40-70 ms early in the city. Refit 2026-10-01 on
#   36c/36d/373/377 and, separately, 362-36b (same answer): 2.5-5 m/s 0.18 / 0.14, 5-9 m/s 0.08 / 0.08,
#   9-15 m/s 0.10 / 0.10 s. Crawl is slower than town because the wheel gets ~0.8 of small targets there.
# - Above 15 m/s lane centering pulls 6-10% of a curve back out through its 0.4 s smoothing and reads as extra
#   lag. That is not delay and the model cannot aim around it, so those values sum the stage lags without it.
# lagd only learns above 15 m/s, so it cannot find the low-speed end.
CLARITY_TRW_A020_LAT_DELAY_SCHEDULE = ((3.5, 7.0, 12.0, 20.0, 30.0), (0.15, 0.08, 0.10, 0.20, 0.30))  # m/s band centres, s
LAT_DELAY_SCHEDULE_DEFAULT = CLARITY_TRW_A020_LAT_DELAY_SCHEDULE


@dataclass(frozen=True)
class EpsFirmwareCalibration:
  """The per-image constants of the chain above, plus the car's residual-PID trims."""
  name: str
  e4_per_output: float         # 0xE4 value per unit of lateral output (the car's linear torqueBP/V cap)
  r5_key_bp: tuple             # live command-map row: key axis ...
  r5_v: tuple                  # ... and R5 values
  key_clamp: float             # command-input clamp, the word before tracker-1 in the table header
  envelope_bp: tuple           # FUN_29C14 speed envelope, a CEILING on |key|; speed axis in 0.5 km/h counts
  envelope_v: tuple
  kp_key_bp: tuple             # P row 0, indexed by the command key
  kp_v: tuple
  r6_per_deg_s: float          # R6 counts per deg/s of carState.steeringRateDeg (at centre when r6_angle_* is set)
  load: ColumnLoadModel
  p_scale: tuple               # residual PID P/I trims per band (<25 mph, 25-50, >50), fixed per car
  i_scale: tuple
  kff: float = 45.0            # project-added feedforward, KFF45 on every PTM image
  scale_q8: float = 256.0      # helper A * B / 256 while the request is held (median on the Clarity and the C020)
  r5_per_key: float | None = None  # set when the row is linear in the key (the Clarity's row 0): Kp per key, exactly
  r6_angle_bp: tuple | None = None    # |published angle| axis of r6_angle_gain, for images whose A table compresses it
  r6_angle_gain: tuple | None = None  # R6 per published deg/s relative to r6_per_deg_s, see firmware_r6()
  cmd_delay_s: float = CMD_DELAY_DEFAULT_S  # command delay in town, see CMD_DELAY_SPEED_BP
  default_on: bool = False     # steer with this controller without HondaEpsController (validated on this car)
  lat_delay_schedule: tuple = LAT_DELAY_SCHEDULE_DEFAULT  # (speed bp, s): the delay told to the model, see above
  rack: RackMapTable | None = None  # yaw-identified rack ratio after the firmware angle table; when set it is the
                                    # geometry, ahead of the road curve and HondaEpsFirmwareVgr
  kp_pieces: tuple = field(init=False, repr=False, compare=False)

  def __post_init__(self):
    if self.r5_per_key is not None:
      # the P row as pieces over |R5| through a constant R5-per-key, flat past the last breakpoint
      pieces = [(lo * self.r5_per_key, hi * self.r5_per_key, kp_lo, (kp_hi - kp_lo) / ((hi - lo) * self.r5_per_key))
                for lo, hi, kp_lo, kp_hi in zip(self.kp_key_bp[:-1], self.kp_key_bp[1:], self.kp_v[:-1], self.kp_v[1:],
                                                strict=True)]
      pieces.append((self.kp_key_bp[-1] * self.r5_per_key, math.inf, self.kp_v[-1], 0.0))
    else:
      # a non-linear row: Kp(key(|R5|)) is still piecewise linear in |R5|, on the union of both tables' knots
      knots = sorted(set(self.r5_v) | {float(np.interp(k, self.r5_key_bp, self.r5_v)) for k in self.kp_key_bp
                                       if k <= self.r5_key_bp[-1]})
      kps = [self._kp_at_r5(r) for r in knots]
      pieces = [(lo, hi, kp_lo, (kp_hi - kp_lo) / (hi - lo))
                for lo, hi, kp_lo, kp_hi in zip(knots[:-1], knots[1:], kps[:-1], kps[1:], strict=True)]
      pieces.append((knots[-1], math.inf, kps[-1], 0.0))
    object.__setattr__(self, "kp_pieces", tuple(pieces))

  def _kp_at_r5(self, r5_abs: float) -> float:
    if self.r5_per_key is not None:
      return float(np.interp(r5_abs / self.r5_per_key, self.kp_key_bp, self.kp_v))
    return float(np.interp(np.interp(r5_abs, self.r5_v, self.r5_key_bp), self.kp_key_bp, self.kp_v))

  def key_ceiling(self, v_ego: float) -> float:
    return min(float(np.interp(v_ego * 3.6 * 2.0, self.envelope_bp, self.envelope_v)), self.key_clamp)

  def r5_ceiling(self, v_ego: float) -> float:
    return float(np.interp(self.key_ceiling(v_ego), self.r5_key_bp, self.r5_v))


# --- the images ------------------------------------------------------------------------------------------------
# Every table below was read from the image the car's owners actually run (the latest builds on the dev machine;
# the shared "Proper Torque Mod" Drive copies are stale for the A030 and C020). The work notes, extractor and the
# per-image table live in rwd-xray-2026chatgpt/EPS_FW_CONTROLLER_MULTICAR_20260927 (notes/firmware_profiles.md).
#
# Which command-map row is live is set per VEHICLE VARIANT, in the image itself: a ROM record table (Clarity
# 0x4B9DC, 89-byte records) keys 5-character variant codes (TRWF3, TBCA9, TGGA5, ...) to row indices, and byte
# 0x0F of the car's record (0 whenever its enable byte 0x0E is 0) is what fn_2AD2E writes to the row selector
# 0xFFF87B7C that the command map, P and D tables read. Checked against both measured cars: every Clarity record
# says 0 (row 0 live), and on the C020 only TBCA9/TBHC8 say 1 (row 1 live on the owner's car). Per image below.

# Clarity column load, fitted on route 00000352 (gain/plant.py: target the firmware's A030 output, every engaged,
# unpressed frame with the scale word >= 240, which keeps resting-hand turns; regressors k0, k1, c, friction with a
# 2 deg/s knee, inertia j (not deployed), bias, roll; motion shifted by the best lag). R^2 0.82 in-route, 0.72 on the
# held-out route. The same recipe per route on 35c-38c (14 routes) gives friction -272..-344 (median -311), k0 median
# -6.2, so this is representative.
CLARITY_TRW_A020_LOAD = ColumnLoadModel(k0=-7.00387, k1=-0.21857, c=-6.8317, friction=-314.07279, bias=20.46793, kroll=-7.20003)

# 10th-gen Civic column, fitted jointly on the C020 owner's routes 00000287 + 00000289 + 00000294 (hands off, from the
# firmware's own P + KFF output rebuilt out of its 0x6A1 error telemetry, so in pre-scale counts: scale_q8 256).
# Held out one route at a time, R^2 0.64 / 0.74 / 0.79 against 0.61 / 0.70 / 0.76 for the Clarity model, which
# over-asks this column (actual / model 0.77-0.98 at 4-22 m/s, 0.5-0.8 at 2-4 m/s). Bias and roll are the Civic's
# own now that three drives identify them.
CIVIC_TBA_C020_LOAD = ColumnLoadModel(k0=-5.574, k1=-0.1831, c=-4.540, friction=-326.5, bias=-83.6, kroll=-3.185)

# Nidec Civic column (HONDA_CIVIC), fitted on the TEG-A010 owner's 08-12 telemetry drive (route 00000001, 18 min of
# city driving up to 15 m/s, hands off), from the same P + KFF rebuild as CIVIC_TBA_C020_LOAD. It needs ~1.6x the C020's output
# for the same motion, even at |driver torque| < 60 (so it is the column, not resting hands); NORM is 1650 on both.
# Held out a minute at a time, R^2 0.74 against 0.61 for CIVIC_TBA_C020_LOAD and 0.68 for the Clarity's. Bias and roll could
# not be told apart on this drive (fitting them gains 0.005 R^2), so they stay the C020's. k1 is fitted below 15 m/s
# only; the highway is an extrapolation.
CIVIC_TEG_A010_LOAD = ColumnLoadModel(k0=-9.205, k1=-0.3252, c=-9.039, friction=-550.7, bias=-83.6, kroll=-3.185)
# CR-V 5G column (HONDA_CRV_5G, 39990-TLA-A040), fitted on the owner's route 00000006--82bb552a2c (native V5 telemetry,
# 40,193 hands-off active groups; RiskyBiscuit-arc/openpilot STATUS 225 / D-092, tools/lateral/fit_crv_eps_load.py) in
# this model's own units: m/s, angle with the liveParameters offset removed, liveParameters roll. R^2 0.843, alternating
# 60 s holdouts 0.857 / 0.820. Close to the Clarity's in every term but the speed term (-0.143 vs -0.219).
CRV_TLA_A040_LOAD = ColumnLoadModel(k0=-7.29446, k1=-0.143159, c=-4.60337, friction=-297.83, bias=-19.899, kroll=-3.58048)
# Insight column (HONDA_INSIGHT, 39990-TXM,A040), measured the way CLARITY_TRW_A020_LOAD was (gain/plant.py) on the owner's
# konik route f133facb1b9b7420|0000001e--2987344626 (2026-10-08, 15.8 mi, 26.9 min engaged and unpressed). That
# build has no telemetry, so the target is the firmware law rebuilt from the sent E4 through row 0 and the car's
# [0, 3840] map with R6 from the Insight's A table (on the Clarity that rebuild matches the A030 output at corr 0.987
# hands off), and the scale-word gate is a |driver torque| < 300 cut (on the Clarity the scale word stays >= 240 up to
# ~500 counts; the fit hardly moves between cuts of 200, 300 and 500). Regressors k0, k1, c, friction (2 deg/s knee),
# inertia j (-0.34, not deployed), bias, roll; best motion lag 40 ms; R^2 0.76.
INSIGHT_TXM_A040_LOAD = ColumnLoadModel(k0=-4.876, k1=-0.1376, c=-4.452, friction=-397.2, bias=65.41, kroll=-4.29)

# R6 comes from the column rate BEFORE the firmware's angle tables, the domain 0x18F STEER_ANGLE_RATE reports
# (R6 = -31.6 per 0x18F count, flat to 2% at every angle on route 369). The feedforward's rate is the derivative
# of the published (0x14A) angle, which the A (position) table compresses, so per deg/s of it the damping grows
# with angle by the A table's local slope (the chain rule): engaged, routes 363/365/366/369, -119 near centre
# and -141..-146 past 60 deg, where a single -133 was 11% too strong near centre and 10% too weak in big turns.
# Scaled by the slope it is flat at -120..-123 on each route (-122 pooled).
# steeringRateDeg (0x14A STEER_ANGLE_RATE) is NOT that derivative: the firmware publishes it through its second,
# B (rate) table, indexed by angle. It reads 1.1% fast at centre (B[0] 16204 vs 16384) and 2-5% slow at 45-100
# deg, so don't feed it here without converting (see steer_ratio.py).
# The other images get the same treatment from their own A tables (R6_GAIN_BP below).
CLARITY_TRW_A020_R6_CENTRE = -122.0  # NORM 1650 / tracker-1 3200
# d(pre-table angle) / d(published angle) along the A020 angle table, 1.0 at centre, ~1.19 from 150 deg
_VGR_SLOPE = np.gradient(CLARITY_TRW_A020_VGR_LINEAR_BP, CLARITY_TRW_A020_VGR_ANGLE_BP)
CLARITY_TRW_A020_R6_BP = tuple(float(x) for x in CLARITY_TRW_A020_VGR_ANGLE_BP)
CLARITY_TRW_A020_R6_GAIN = tuple(float(x) for x in _VGR_SLOPE / _VGR_SLOPE[0])

# Default residual-PID trims: vfn 35ddc44b's modified-EPS angle PID with the P/I trims the Clarity ran on it
# (2026-09-26, LatPScale 125/100/125, LatIScale 70/95/35), fixed because the replay validated the feedforward
# against exactly that PID.
CLARITY_TRW_A020_P_SCALE = (1.25, 1.00, 1.25)
CLARITY_TRW_A020_I_SCALE = (0.70, 0.95, 0.35)
# The C020 owner's trims on route 00000284 (LatPScale 115/125/115, LatIScale 75/95/100), the drive their port of
# this controller was checked against. Every Civic-platform car starts here.
CIVIC_TBA_C020_P_SCALE = (1.15, 1.25, 1.15)
CIVIC_TBA_C020_I_SCALE = (0.75, 0.95, 1.00)
# The CR-V owner drives this controller untrimmed (RiskyBiscuit-arc ns-bosch-updated CRV_5G_P/I_SCALE), on the
# CarParams base gains.
CRV_TLA_A040_P_SCALE = (1.0, 1.0, 1.0)
CRV_TLA_A040_I_SCALE = (1.0, 1.0, 1.0)

# The TargetMap-D R5 row every Civic-family image carries in all seven rows, and the Clarity's own row 0.
TARGET_MAP_D_R5 = (0, 1926, 4938, 8455, 12036, 15926, 20138, 26955, 30000)
CLARITY_TRW_A020_R5 = (0, 2000, 4000, 6000, 8000, 12000, 16000, 20000, 30000)
P_ROW_PMINUS5 = (117, 148, 184, 220, 245, 257, 263, 265, 265)
FLAT_ENVELOPE = ((0, 50, 100, 150, 200, 250, 300, 350, 400), (1774,) * 9)
# C020 / TEG / A030 speed envelope (axis 0x13644, values 0x136C2 on the C020): 1552 from 120 km/h, 1108 from 160
CIVIC_TBA_C020_ENVELOPE = ((0, 50, 100, 150, 200, 240, 300, 321, 400), (1774, 1774, 1774, 1774, 1774, 1552, 1219, 1108, 1108))
# C020 row 1 (axis 0x13806); the TEG-A010 and the 09-12 A030 images carry the C020's axes in every row
CIVIC_TBA_C020_ROW1_KEYS = (0, 115, 254, 449, 654, 862, 1111, 1549, 1774)
CIVIC_TBA_C020_P_KEYS = (0, 223, 441, 665, 883, 1108, 1330, 1552, 1774)
CIVIC_TBA_C120_P_KEYS = (3, 173, 441, 665, 887, 1104, 1317, 1610, 1774)
# R6 per published deg/s is angle-dependent on every image, not just the Clarity: R6 is the firmware's PRE-table
# column rate (flat against the 0x18F rate: 30.8 -> 28.6 counts per 0x18F count on the C020, 31.0 -> 30.6 on the
# Clarity), scaled by NORM (1650 on every build) and the motor-to-angle constant (3121 in every image), while the
# published angle the feedforward differentiates comes out of each image's A table. So per published deg/s,
#   R6(angle) = -122 * (A-table centre divisor / 16384) * (A-table slope at angle / slope at centre),
# -122 being the Clarity's centre value. Checked against telemetry on both cars that have it (0.1 s derivative of the
# published angle, so the noise does not shrink the slope): Clarity within 0.6% at centre and 2.7% at every angle;
# C020 within 0.4% at centre but 5-10% high past 60 deg (R6 per 0x18F count falls ~7% there on that car), so the C020
# and the TGG-A120, which shares its A table, take the C020's measured curve. The single constants used before
# (-172 C020, -161 TEG, -138.4 CR-V) were angle averages fitted against 0x14A: ~12% too strong at centre, 8-18% too
# weak in big turns. The slopes are +/-10 deg chords of each image's A table (honda_vgr in nrdr-development).
R6_GAIN_BP = (0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 180, 210, 240, 270, 300, 360, 420, 480)  # |angle|, deg
# C020 measured (routes 64/154/287/289/294, hands on or off: R6 is kinematic), per published deg/s
CIVIC_TBA_C020_R6_CENTRE = -153.2
CIVIC_TBA_C020_R6_BP = (0.0, 22.5, 45.0, 80.0, 125.0, 175.0, 250.0)
CIVIC_TBA_C020_R6_GAIN = (1.0, 0.99347, 1.01175, 1.05875, 1.09269, 1.10248, 1.10248)
# C120 / A030 / TEG-A010 A table (centre divisor 20972), computed
CIVIC_TBA_C120_R6_CENTRE = -156.16
CIVIC_TBA_C120_R6_GAIN = (1.0, 0.9838, 0.9927, 1.0254, 1.0699, 1.097, 1.1244, 1.1465, 1.1099, 1.1222, 1.1905, 1.257, 1.1758,
                1.1618, 1.1702, 1.1787, 1.196, 1.2137, 1.2317)
# Insight TXM-A040 A table (centre divisor 17613), computed
INSIGHT_TXM_A040_R6_CENTRE = -131.15
INSIGHT_TXM_A040_R6_GAIN = (1.0, 1.0247, 1.0326, 1.052, 1.0852, 1.1305, 1.1692, 1.207, 1.2242, 1.2239, 1.2156, 1.2234, 1.2254,
                   1.2249, 1.2273, 1.2253, 1.2279, 1.2436, 1.1917)
# CR-V TLA-A040 / A220 A table (centre divisor 16783, byte-identical in both images), computed. The owner's V5 fit
# (-121.6 at norm 1450 -> -138.4) is the angle average against 0x14A; the centre this gives is -125.
CRV_TLA_A040_R6_CENTRE = -124.97
CRV_TLA_A040_R6_GAIN = (1.0, 1.0233, 1.0273, 1.0431, 1.075, 1.1134, 1.1566, 1.199, 1.2195, 1.2305, 1.2252, 1.2367, 1.2354,
               1.2381, 1.2328, 1.2243, 1.2257, 1.2162, 1.191)

# Clarity 39990-TRW-A020, the P-minus-5 build (07-28, bin sha256 92cde599; P117..265 D737 KFF45 NoR6L2 Tracker3200
# Norm1650), the Clarity standard: what routes 352/353 and the whole replay validation ran on, and the parent of the
# A280-flat build owners move to (which edits only the A280 cells, so every table here holds). The older ClarityMax
# 07-22 P123..279 build differed only in the P row (123, 156, 194, 232, 258, 270, 277, 279, 279) and is not supported.
CLARITY_TRW_A020 = EpsFirmwareCalibration(
  name="clarity_trw_a020",
  e4_per_output=3840.0,
  # command map row 0 (0x13810 / 0x1388E); key = trunc(trunc(E4 * 56756 / 32768) / 4)
  r5_key_bp=(0, 111, 222, 333, 443, 665, 887, 1108, 1663), r5_v=CLARITY_TRW_A020_R5, key_clamp=1663,
  # 1774 up to 100 km/h, so the 1663 key clamp binds first until ~107 km/h; 1330 from 130 km/h (0x13660 / 0x136DE)
  envelope_bp=(0, 50, 100, 150, 200, 260, 300, 350, 400), envelope_v=(1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330, 1330),
  # P row 0 (0x13B5E / 0x13BDC)
  kp_key_bp=(0, 222, 443, 665, 887, 1108, 1330, 1552, 1774), kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CLARITY_TRW_A020_R6_CENTRE, r6_angle_bp=CLARITY_TRW_A020_R6_BP, r6_angle_gain=CLARITY_TRW_A020_R6_GAIN,
  load=CLARITY_TRW_A020_LOAD, p_scale=CLARITY_TRW_A020_P_SCALE, i_scale=CLARITY_TRW_A020_I_SCALE,
  r5_per_key=18.04,
  cmd_delay_s=0.12,  # measured
  default_on=True,
  lat_delay_schedule=CLARITY_TRW_A020_LAT_DELAY_SCHEDULE,  # measured
  rack=CLARITY_TRW_A020_RACK,
)

# Civic Bosch 39990-TBA-C020, 08-05 ClarityPminus5 P117..265 D737 KFF45 Norm1650 Trk4500 TargetMapD Telem (bin
# sha256 6ecd587c). Measured on the owner's telemetry (routes 284/287/289): E4 = -4096 * u, key clamp 1663 (0x137F2),
# row 1 is live (94 counts RMS vs 200 for row 0 at 11-20 m/s; the largest R5 on 284 is 28497 = row 1 at 1663), R6,
# the column load. Not checked: the envelope above 89 km/h.
CIVIC_TBA_C020 = EpsFirmwareCalibration(
  name="civic_tba_c020", e4_per_output=4096.0,
  r5_key_bp=CIVIC_TBA_C020_ROW1_KEYS, r5_v=TARGET_MAP_D_R5, key_clamp=1663,
  envelope_bp=CIVIC_TBA_C020_ENVELOPE[0], envelope_v=CIVIC_TBA_C020_ENVELOPE[1],
  kp_key_bp=CIVIC_TBA_C020_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TBA_C020_R6_CENTRE, r6_angle_bp=CIVIC_TBA_C020_R6_BP, r6_angle_gain=CIVIC_TBA_C020_R6_GAIN,
  load=CIVIC_TBA_C020_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  cmd_delay_s=0.15,  # measured
  rack=CIVIC_TBA_C020_RACK,
)
# Civic 39990-TBA-A030 (Nidec), 09-12 TEGLatestCalMatch Trk3200 (bin sha256 1de38bcb) and TEG-A010, 08-26
# Tracker1-3200 (bin sha256 60f42ecc): both carry the C020's command axes, P axis and envelope byte for byte, so
# they take the C020's row 1. E4 = -3840 * u (HONDA_CIVIC torque map). R6 and load are the TEG owner's, measured on
# the 08-12 telemetry build (E4 -> R5 -> P + KFF law exact there; Kp keyed on |command key|); the A030 shares the
# fingerprint and the TEG calibration, so it takes them too (not measured on an A030).
# The live row is VARIANT-DEPENDENT here, and it matters: rows 0 and 1 agree within 8%, but A030 TBCA1 / TEG TEGA1
# select row 2 (R5 1.28-1.30x row 1 at mid command) and A030 TBCA2 / TEG TEGA2 row 3 (0.48-0.70x at low command).
# Every other variant (A030 TBAA0-3, TBAC0, TBCA0; TEG TEGA0, TBCA3) is row 0 or 1. The car's variant cannot be
# read from openpilot, and the TEG telemetry drive cannot tell either: its build has the same command, P, D, A280 and
# helper-A values in rows 0-5 (row 6 is ruled out). Settling it needs a telemetry build that reports the row selector.
CIVIC_TBA_A030 = EpsFirmwareCalibration(**{**{k: getattr(CIVIC_TBA_C020, k) for k in CIVIC_TBA_C020.__dataclass_fields__
                                      if k != "kp_pieces"}, "name": "civic_tba_a030", "e4_per_output": 3840.0,
                                   "r6_per_deg_s": CIVIC_TBA_C120_R6_CENTRE, "r6_angle_bp": R6_GAIN_BP,
                                   "r6_angle_gain": CIVIC_TBA_C120_R6_GAIN, "load": CIVIC_TEG_A010_LOAD,
                                   "cmd_delay_s": CMD_DELAY_DEFAULT_S,  # Nidec Civic: not measured
                                   "rack": None})  # its own A table, not identified
CIVIC_TEG_A010 = EpsFirmwareCalibration(**{**{k: getattr(CIVIC_TBA_A030, k) for k in CIVIC_TBA_A030.__dataclass_fields__
                                          if k != "kp_pieces"}, "name": "civic_teg_a010"})
# Civic Bosch 39990-TBA-C120, 08-11 C020Profile Trk4250 (bin sha256 3d88d5ea). Its variants select rows 0-4, all
# within 5% of each other in R5, so the row does not matter; row 1 (= row 2) is taken, as the C020's. Flat envelope.
# E4 = -3840 * u: opendbc gives the C120 image its own [0, 3840] map, unlike the C020's 4096. Not measured: R6, load.
CIVIC_TBA_C120 = EpsFirmwareCalibration(
  name="civic_tba_c120", e4_per_output=3840.0,
  r5_key_bp=(0, 103, 263, 459, 660, 861, 1111, 1549, 1774), r5_v=TARGET_MAP_D_R5, key_clamp=1663,
  envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=CIVIC_TBA_C120_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TBA_C120_R6_CENTRE, r6_angle_bp=R6_GAIN_BP, r6_angle_gain=CIVIC_TBA_C120_R6_GAIN,
  load=CIVIC_TBA_C020_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  cmd_delay_s=0.15,  # the C020's (same Civic Bosch chassis)
)
# Civic hatch 39990-TGG-A120, 08-07 C020Pminus5 Trk4250 KFF45 (bin sha256 7c60b3fa). Only row 0 carries car-specific
# axes (rows 1-5 are the generic [0,222,333,...] row, 2x the key at low command). Row 0 is live: both of the image's
# variant records (TGGA5, TGGA6, at 0x4B500) select row 0. Flat envelope. Not measured: R6, load.
CIVIC_TGG_A120 = EpsFirmwareCalibration(
  name="civic_tgg_a120", e4_per_output=4096.0,
  r5_key_bp=(0, 103, 263, 459, 660, 862, 1111, 1549, 1774), r5_v=TARGET_MAP_D_R5, key_clamp=1663,
  envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=CIVIC_TBA_C120_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TBA_C020_R6_CENTRE, r6_angle_bp=CIVIC_TBA_C020_R6_BP, r6_angle_gain=CIVIC_TBA_C020_R6_GAIN,
  load=CIVIC_TBA_C020_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  cmd_delay_s=0.15,  # the C020's (same Civic Bosch chassis)
)
# Insight 39990-TXM-A040, 08-08 C020Surface Trk1-4000 Trk2-3869 (bin sha256 1f1cfe6b). Rows 0-1 keep the Clarity-
# style axis ending at the 1663 clamp and rows 2-5 are 2x it at low command. Row 0 is live: all three variant records
# (TXMA0/1/2, at 0xECF7, laid out among the part-number strings) select row 0, and rows 0 and 1 are identical anyway.
# Every Insight image we have (08-01 through 08-08) carries the same row-0 axis and variant records (TXMA0/1 enabled
# -> row 0, TXMA2 disabled -> row 0), so the row holds whichever build the car runs. The envelope was not located;
# flat is assumed (the 1663 clamp binds). Load measured (INSIGHT_TXM_A040_LOAD); R6 computed from its A table. Not measured:
# envelope.
INSIGHT_TXM_A040 = EpsFirmwareCalibration(
  name="insight_txm_a040", e4_per_output=3840.0,
  r5_key_bp=(0, 111, 222, 333, 443, 665, 887, 1108, 1663), r5_v=TARGET_MAP_D_R5, key_clamp=1663,
  envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=(0, 222, 333, 665, 887, 1104, 1317, 1441, 1663), kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=INSIGHT_TXM_A040_R6_CENTRE, r6_angle_bp=R6_GAIN_BP, r6_angle_gain=INSIGHT_TXM_A040_R6_GAIN,
  load=INSIGHT_TXM_A040_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  # Inferred: on LatControlPID its route 0000001e ran the plan 0.06 s early (exit 0.12), and this controller runs
  # ~0.13 s (Clarity) to ~0.18 s (C020) ahead of the PID, so ~0.19-0.24 s early here; 0.15 stays below that. Re-check
  # with plan_timing.py after a drive on this controller.
  cmd_delay_s=0.15,
  rack=INSIGHT_TXM_A040_RACK,
)
# CR-V 5G 39990-TLA-A040, the owner's 08-24 Clarity_FF_tune_telemety_8cf8e537 (decoded full image sha256 d5dc04a8):
# TargetMap-D, P117..265, D737, KFF45, Norm1650, Trk3200, clamps 7373/1774/9000 on the CR-V's stock axes. Key clamp
# 1774 (the others' 1663). Rows 0-1 and 2-5 differ by under 5%, so the row choice barely matters; row 0 is taken, and
# every variant record selects row 0 except TLBA2 (row 1, identical to row 0).
# R6 measured: least squares of the image's own V5 feedback_R6 on steeringRateDeg, hands off, route 82bb (-121.6 at a
# 15 ms lag, R^2 0.977) on the t9-67523237 build, whose norm reads 1450; x 1650/1450 for this image = -138.4. The firmware
# predicts the same from the shared motor-to-angle constant (3121) and the A-table centre divisor (16783/16384 x the
# Clarity's). Column load measured on the same drive (CRV_TLA_A040_LOAD). P/I trims: the owner's
# (CRV_TLA_A040_P_SCALE / CRV_TLA_A040_I_SCALE, untrimmed).
CRV_TLA_A040 = EpsFirmwareCalibration(
  name="crv_tla_a040", e4_per_output=4096.0,
  r5_key_bp=(0, 219, 443, 662, 887, 1108, 1330, 1552, 1663), r5_v=TARGET_MAP_D_R5, key_clamp=1774,
  envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=(0, 104, 279, 510, 807, 1108, 1330, 1552, 1663), kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CRV_TLA_A040_R6_CENTRE, r6_angle_bp=R6_GAIN_BP, r6_angle_gain=CRV_TLA_A040_R6_GAIN,
  load=CRV_TLA_A040_LOAD, p_scale=CRV_TLA_A040_P_SCALE, i_scale=CRV_TLA_A040_I_SCALE,
)
# CR-V 5G 39990-TLA-A220 (2020+), the 10-06 A280Flat PTM build (full image sha256 5f706dd6, RWD 8f175250) on stock
# df85f988: TargetMap-D, P117..265, D737, KFF45, Norm1650, Trk3200, clamps 7373/1774/9000, speed clamp 0. The
# controller block is the A040's shifted -0x448 (only RAM literals differ), every calibration literal resolves to the
# SAME table address, and the PTM edits left the command axes, P axis, envelope and VGR tables stock. Read from THIS
# image: the command-map key axis (rows 0-3 at 0x11AE0 + 18*row), the P axis (0x11E2E), the speed envelope (values
# 0x119AE + 18*row, axis 0x11930), the key clamp (header word 0x11ADE, 1774), the A/B VGR tables, E4 scale (opendbc
# gives every modified HONDA_CRV_5G [0, 4096]).
# What differs from the A040 is the COMMAND AXIS: rows 0-3 are [0,161,222,322,409,534,696,998|1050,1663], so the same
# key asks ~2.5x the R5 (key 443: 13094 vs 4938; key 887: 24449 vs 12036) and the map saturates at 30000 by key 1663.
# Kp is still keyed on the same P axis, so its P pieces sit at different R5.
# Live row is VARIANT-DEPENDENT but barely: the ROM record table at 0xECF7 (91-byte records, enable byte 0x0E, row byte
# 0x0F, same layout as the A040's, where it reproduces TLBA2 -> 1) selects row 0 for TLAA3/TLAY2/TLAY8/TLBL1 and, with
# the enable byte 0, TLAY6/TLAY7/TLBK6/TLDY6; row 1 for TLAA4 (identical to row 0); row 2 for TLBA4; row 3 for TLBA5.
# Rows 2-3 differ from row 0 only at the 7th knot (1050, not 998: up to 1001 counts of R5 at key 998); the PTM's target
# map, P and D rows are identical in all of rows 0-3. Row 0 is taken. The car's variant cannot be read from openpilot.
# Envelope: unlike the A040's flat table, row 0 caps |key| at 1330 from 150 km/h (1774 up to 125 km/h); rows 1 and 2-3
# differ only above 150 km/h (row 1: 1108 from 175 km/h), so the row choice does not matter below 150 km/h.
# Carried over, NOT read from this image: load = CRV_TLA_A040_LOAD and the P/I trims (the CR-V's, see CRV_TLA_A040). R6 is PREDICTED,
# not measured -- there is no A220 drive: the motor-to-angle constant (3121, 0x19C00), the A-table centre divisor
# (16783, 0x11338, byte-identical to the A040's) and NORM (1650, PTM halfword 0x42558) all equal the A040's, so it takes
# the A040's measured R6 (route 82bb at norm 1450, scaled to 1650).
CRV_TLA_A220 = EpsFirmwareCalibration(
  name="crv_tla_a220", e4_per_output=4096.0,
  r5_key_bp=(0, 161, 222, 322, 409, 534, 696, 998, 1663), r5_v=TARGET_MAP_D_R5, key_clamp=1774,
  envelope_bp=(0, 50, 100, 150, 200, 250, 300, 350, 400), envelope_v=(1774, 1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330),
  kp_key_bp=CRV_TLA_A040.kp_key_bp, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CRV_TLA_A040.r6_per_deg_s, r6_angle_bp=CRV_TLA_A040.r6_angle_bp, r6_angle_gain=CRV_TLA_A040.r6_angle_gain,
  load=CRV_TLA_A040_LOAD, p_scale=CRV_TLA_A040_P_SCALE, i_scale=CRV_TLA_A040_I_SCALE,
)

# normalize_honda_eps_fw(EPS fwVersion) -> (fingerprint, profile). TGG-A020 is a separate application from the A120 (its RWD updates only A010/A020)
# and has no PTM build, so it is absent on purpose.
EPS_FIRMWARE_CALIBRATIONS = {
  "39990-TRW-A020": ("HONDA_CLARITY", CLARITY_TRW_A020),
  "39990-TBA-C020": ("HONDA_CIVIC_BOSCH", CIVIC_TBA_C020),
  "39990-TBA-C120": ("HONDA_CIVIC_BOSCH", CIVIC_TBA_C120),
  "39990-TGG-A120": ("HONDA_CIVIC_BOSCH", CIVIC_TGG_A120),
  "39990-TBA-A030": ("HONDA_CIVIC", CIVIC_TBA_A030),
  "39990-TEG-A010": ("HONDA_CIVIC", CIVIC_TEG_A010),
  "39990-TXM-A040": ("HONDA_INSIGHT", INSIGHT_TXM_A040),
  "39990-TLA-A040": ("HONDA_CRV_5G", CRV_TLA_A040),
  "39990-TLA-A220": ("HONDA_CRV_5G", CRV_TLA_A220),
}


# --- where each calibration value came from --------------------------------------------------------------------
# One line per quantity per image, so what is measured and what is carried over is auditable in one place (and is
# logged when LatControlHondaEps starts). Each value starts with its kind:
#   firmware  read or computed from the image the owners run
#   measured  fitted on that car's own drives (the routes say which)
#   inferred  carried over from a related car or derived indirectly; re-measure when its logs exist
#   default   the controller-wide default, nothing car-specific yet
#   none      not applicable (no rack map: the road curve or the firmware table is the geometry)
PROVENANCE_KINDS = ('firmware', 'measured', 'inferred', 'default', 'none')
PROVENANCE_FIELDS = ('row', 'kp_axis', 'key_clamp', 'envelope', 'r6', 'load', 'trims', 'cmd_delay', 'model_delay', 'rack')
CALIBRATION_PROVENANCE = {
  "clarity_trw_a020": {
    "row": "measured: telemetry R5 = row 0 exactly; every TRW variant record selects row 0",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "measured: telemetry, routes 363/365/366/369 (-122 x the A-table slope)",
    "load": "measured: route 352, against the firmware output (14 routes agree)",
    "trims": "measured: the tune the car drove on vfn 35ddc44b",
    "cmd_delay": "measured: plan_timing, routes 37e / 380",
    "model_delay": "measured: routes 36c/36d/373/377 and 362-36b",
    "rack": "measured: VSA yaw, routes 341-36b",
  },
  "civic_tba_c020": {
    "row": "measured: telemetry R5 = row 1 (route 294, live_row_fit); TBCA9/TBHC8 select row 1",
    "kp_axis": "firmware", "key_clamp": "firmware",
    "envelope": "firmware (not road-checked above 89 km/h)",
    "r6": "measured: telemetry, routes 64/154/287/289/294",
    "load": "measured: owner telemetry 287/289/294; a 14-route refit agrees",
    "trims": "measured: the owner's tune, route 284",
    "cmd_delay": "measured: plan_timing 290/293/289; confirmed with it on, 2b7/2c6/2d4",
    "model_delay": "default: the Clarity's schedule",
    "rack": "measured: VSA yaw, routes 294/289/2b7/2c6/2d4/1b8/251",
  },
  "civic_tba_a030": {
    "row": "inferred: the C020's row 1; the live row is variant-dependent (TBCA1 row 2, TBCA2 row 3)",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table (the C120's)",
    "load": "inferred: the TEG-A010 owner's",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "default", "model_delay": "default: the Clarity's schedule", "rack": "none",
  },
  "civic_teg_a010": {
    "row": "inferred: the C020's row 1; a steering TEG is TEGA1 (row 2) or TEGA2 (row 3), not yet read",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table; telemetry fit -161 at its 08-12 build",
    "load": "measured: the owner's 08-18 telemetry drive (P+KFF rebuild, hands off, below 15 m/s)",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "default", "model_delay": "default: the Clarity's schedule", "rack": "none",
  },
  "civic_tba_c120": {
    "row": "firmware: its variants' rows 0-4 agree within 5%",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table",
    "load": "inferred: the C020's",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "inferred: the C020's (same chassis)", "model_delay": "default: the Clarity's schedule", "rack": "none",
  },
  "civic_tgg_a120": {
    "row": "firmware: both variant records (TGGA5, TGGA6) select row 0",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "inferred: the C020's measured curve (same A table)",
    "load": "inferred: the C020's",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "inferred: the C020's (same chassis)", "model_delay": "default: the Clarity's schedule", "rack": "none",
  },
  "insight_txm_a040": {
    "row": "firmware: row 0 in every build and variant",
    "kp_axis": "firmware", "key_clamp": "firmware",
    "envelope": "default: not located in the image; flat assumed (the 1663 clamp binds first)",
    "r6": "firmware: computed from its A table",
    "load": "measured: the owner's konik route 0000001e",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "inferred: its LatControlPID drive (0.06 s early) plus this controller's lead over the PID",
    "model_delay": "default: the Clarity's schedule",
    "rack": "measured: VSA yaw (GPS-checked scale), route 0000001e",
  },
  "crv_tla_a040": {
    "row": "firmware: every variant record selects row 0 (TLBA2 row 1, identical)",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table; matches the owner's telemetry fit (route 82bb)",
    "load": "measured: the owner's telemetry route 82bb",
    "trims": "measured: the owner drives it untrimmed",
    "cmd_delay": "default (the owner's LatControlPID drive ran 0.08 s late: re-check on this controller)",
    "model_delay": "default: the Clarity's schedule", "rack": "none",
  },
  "crv_tla_a220": {
    "row": "firmware", "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "inferred: the A040's (its A table not checked)",
    "load": "inferred: the A040 owner's",
    "trims": "inferred: the A040 owner's",
    "cmd_delay": "default", "model_delay": "default: the Clarity's schedule", "rack": "none",
  },
}


def provenance(cal: EpsFirmwareCalibration) -> dict:
  return CALIBRATION_PROVENANCE[cal.name]


def provenance_summary(cal: EpsFirmwareCalibration) -> str:
  """'measured: r6, load, ... | inferred: ... | default: ...', for the startup log."""
  groups = {}
  for key in PROVENANCE_FIELDS:
    groups.setdefault(provenance(cal)[key].split(':')[0].split(' ')[0], []).append(key)
  return ' | '.join(f"{kind}: {', '.join(keys)}" for kind, keys in groups.items())


def select_eps_firmware_calibration(fingerprint: str, eps_fw: str) -> EpsFirmwareCalibration | None:
  """The profile for this car's EPS image, or None when there is no PTM build for it (or it is on another car)."""
  entry = EPS_FIRMWARE_CALIBRATIONS.get(eps_fw)
  if entry is None or entry[0] != fingerprint:
    return None
  return entry[1]


# The fits put the Coulomb knee at 2-5 deg/s, but the feedforward keys it on the DESIRED rate, so a knee that
# sharp turns every small wiggle in the model's path into a friction square wave: in the closed-loop sim the wheel
# answers a +/-2 deg, 1 Hz wiggle at 10 m/s with gain 1.40 (Clarity) / 1.63 (C020); a 20 deg/s knee brings that to
# 0.96 / 1.22, and turn-ins (30-200 deg/s) keep the full fitted friction. The price is lag on slow, small motions
# (the friction is then under-compensated), which only pays off at city speed: replaying hands-off chunks of routes
# 35e/360/361, a 20 deg/s knee cut the 0.6-2 Hz wheel/target transfer 0.93 -> 0.73 at 10-16 m/s for +25 ms, but
# above 16 m/s bought nothing (1.02 -> 0.97) for +45 ms of lag and RMS error 0.27 -> 0.37 deg. So it is scheduled:
# 20 deg/s up to 8 m/s, back to 5 by 15 m/s (10-16 m/s: 0.76 at +10 ms; above: unchanged).
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

# The output LPF default is the Honda torque-output LPF setting (these are the Clarity's values).
MPH_TO_MS = 0.44704
BAND_LOW_MAX = 25.0 * MPH_TO_MS
BAND_STD_MAX = 50.0 * MPH_TO_MS
OUTPUT_LPF_TAU = (0.07, 0.05, 0.01)
INTEGRATOR_MIN_SPEED = 2.0  # m/s, below this the integrator is held at zero (as vfn)
# After a press the carcontroller fades torque back in over HondaOverrideFadeUpSecs, and every faded frame trips
# steer_limited_by_safety, which froze the integrator at its pre-press value. On the C020 (route 0000027a, 12:34,
# LatControlPID) two override trips held I at 0.19 into the turn through the unwind, where it cancelled 35-45 % of P
# and the car ran wide toward the curb; below 25 mph 60-70 % of the non-pressed limited frames on routes 277/278/27a
# were in that window. So the held I bleeds toward 0 during the fade instead, as LatControlPID does (PR #14, Peter
# Nguyen). Pressed frames, and a limit with no recent press, still freeze.
OVERRIDE_FADE_I_BLEED_TAU = 0.5   # s: 37 % of the held I is left after a 0.5 s fade
OVERRIDE_FADE_UP_S_DEFAULT = 1.5  # s, the carcontroller's HondaOverrideFadeUpSecs default

# The feedforward asks for the torque that moves the wheel ALONG the desired path, so it is only right
# once the wheel is on it. Engaging mid-turn at low speed routinely starts 20-70 deg off (45 engagements on
# routes 352/353/34f), where it would have pushed against the PID at up to 0.9. So it joins only once the
# angle error is small, then fades in; a driver press or dropping below walking speed takes it out again.
FF_JOIN_ERROR_DEG = 10.0
FF_FADE_IN_S = 0.5
FF_SPEED_BP = [2.0, 4.0]    # m/s, faded in with speed; the desired angle is ill-conditioned near standstill

# At a crawl the feedforward also passes the model's small path wiggles to the wheel 1:1 (target -> wheel gain
# 1.02 measured below 4 m/s on route 361, 0.41 for the PID alone), and column stiction makes that gain grow with
# amplitude, so a near-straight crawl can build a ~0.9 Hz wobble through the camera and the model (route 361
# t 823-829, hands off). Below FF_CRAWL_SPEED_BP the feedforward therefore joins with |desired angle| (none under
# 5 deg, all from 20 deg: every real crawl turn), fading out of effect by 8 m/s so nothing changes at speed.
# Sim, 3 m/s 0.9 Hz: gain 0.88 -> 0.29 (PID alone 0.29) with turn RMS 4.4 deg (PID alone 9.8).
FF_CRAWL_ANGLE_BP = [5.0, 20.0]  # deg
FF_CRAWL_SPEED_BP = [5.0, 8.0]   # m/s


def key_ceiling(v_ego: float, cal: EpsFirmwareCalibration) -> float:
  return cal.key_ceiling(v_ego)


def r5_from_output(output: float, v_ego: float, cal: EpsFirmwareCalibration) -> float:
  """What the firmware makes of a lateral output: forward model of 0xE4 -> key -> R5."""
  key = command_key(-output * cal.e4_per_output)
  mag = float(np.interp(min(abs(key), cal.key_ceiling(v_ego)), cal.r5_key_bp, cal.r5_v))
  return math.copysign(mag, key) if key else 0.0


def output_from_r5(r5: float, cal: EpsFirmwareCalibration) -> float:
  """Inverse of r5_from_output (up to integer truncation)."""
  key = float(np.interp(min(abs(r5), cal.r5_v[-1]), cal.r5_v, cal.r5_key_bp))
  e4 = key * 4.0 * 32768.0 / 56756.0
  return -math.copysign(e4, r5) / cal.e4_per_output


def firmware_kp(r5: float, cal: EpsFirmwareCalibration) -> float:
  return cal._kp_at_r5(abs(r5))


def firmware_r6(steering_rate_deg_s: float, angle_deg: float, cal: EpsFirmwareCalibration) -> float:
  """The firmware's rate feedback for a published steering rate at a published angle."""
  gain = 1.0 if cal.r6_angle_bp is None else float(np.interp(abs(angle_deg), cal.r6_angle_bp, cal.r6_angle_gain))
  return cal.r6_per_deg_s * gain * steering_rate_deg_s


def firmware_output(r5: float, steering_rate_deg_s: float, cal: EpsFirmwareCalibration, angle_deg: float = 0.0) -> float:
  """Steady-state firmware output for a target and a rate (D term omitted): scale*(Kp*(R5-R6) + KFF*R5)/1024/256."""
  r6 = firmware_r6(steering_rate_deg_s, angle_deg, cal)
  return cal.scale_q8 * (firmware_kp(r5, cal) * (r5 - r6) + cal.kff * r5) / 1024.0 / 256.0


def column_load(angle_deg: float, rate_deg_s: float, v_ego: float, roll: float,
                load: ColumnLoadModel, friction_width: float = FRICTION_WIDTH_DEG_S) -> float:
  return (load.k0 * angle_deg + load.k1 * angle_deg * v_ego ** 2 + load.c * rate_deg_s
          + load.friction * math.tanh(rate_deg_s / friction_width) + load.bias + load.kroll * roll * v_ego ** 2)


def r5_for_motion(load: float, rate_deg_s: float, cal: EpsFirmwareCalibration, r5_guess: float = 0.0, angle_deg: float = 0.0) -> float:
  """Solve the firmware law for the target that yields `load` while the wheel moves at `rate_deg_s` through `angle_deg`.

  load = scale * (Kp*(R5 - R6) + KFF*R5) / 1024 / 256, with Kp piecewise linear in |R5|. On each piece
  that is a quadratic in R5, so solve every piece exactly and keep the root nearest `r5_guess` (more than
  one root only exists when a fast unwind outruns a small target). A fixed-point iteration is not enough
  here: it is 1-4% off after three passes from rest and need not contract during a fast unwind.
  """
  x = 1024.0 * load * 256.0 / cal.scale_q8
  r6 = firmware_r6(rate_deg_s, angle_deg, cal)
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
  def __init__(self, dt: float, cal: EpsFirmwareCalibration, rate_tau: float = DESIRED_RATE_TAU, lead_s: float = LEAD_S,
               output_tau: float = FF_OUTPUT_TAU, friction_width: float | None = None):
    self.dt = dt
    self.alpha = dt / (rate_tau + dt)
    self.output_alpha = dt / (output_tau + dt)
    self.lead_s = lead_s
    self.friction_width = friction_width  # None: the speed schedule above
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
    self.load = column_load(angle, self.rate, v_ego, roll, self.cal.load, width)
    cap = min(R5_CAP, R5_CAP_ENVELOPE_FRAC * self.cal.r5_ceiling(v_ego))
    self.r5 = max(min(r5_for_motion(self.load, self.rate, self.cal, self.r5, angle), cap), -cap)
    target = output_from_r5(self.r5, self.cal)
    self.output = target if first else self.output + self.output_alpha * (target - self.output)
    return self.output


def speed_band(v_ego: float, values):
  return values[0] if v_ego < BAND_LOW_MAX else values[1] if v_ego < BAND_STD_MAX else values[2]


class HondaEpsLateralCore:
  """Angle PID on the residual + firmware-inversion feedforward, faded in once the wheel is on the path.

  Pure (no messaging, no params), so the closed-loop replay can drive exactly the code the car runs.
  """

  def __init__(self, kp_bp, kp_v, ki_bp, ki_v, dt: float, ff: HondaEpsFirmwareFeedforward, p_scale=None, i_scale=None):
    self.dt = dt
    self.pid = PIDController((kp_bp, kp_v), (ki_bp, ki_v), pos_limit=1.0, neg_limit=-1.0, rate=1.0 / dt)
    self.ff = ff
    self.p_scale = p_scale if p_scale is not None else self.ff.cal.p_scale
    self.i_scale = i_scale if i_scale is not None else self.ff.cal.i_scale
    # The Honda torque-output LPF, run exactly as LatControlPID runs it (the car controller deliberately does
    # not filter, so this is the only one): same filter class, same per-band update_alpha, reset to 0.
    self.output_lpf = FirstOrderFilter(0.0, OUTPUT_LPF_TAU[0], dt)
    self.override_fade_up_s = OVERRIDE_FADE_UP_S_DEFAULT
    self.reset()

  def reset(self):
    self.pid.reset()
    self.ff.reset()
    self.since_press_s = math.inf  # time since the driver-override detector last fired
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

    self.since_press_s = 0.0 if steering_pressed else self.since_press_s + self.dt
    if steer_limited and not steering_pressed and self.since_press_s <= self.override_fade_up_s + self.dt:
      self.pid.i *= math.exp(-self.dt / OVERRIDE_FADE_I_BLEED_TAU)  # see OVERRIDE_FADE_I_BLEED_TAU

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
