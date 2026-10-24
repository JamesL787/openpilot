"""The modified-EPS Honda lateral controller, built on the EPS firmware's own control law.

Every PTM (Proper Torque Mod) EPS image -- Clarity, Civic, Insight, CR-V -- runs the same law with its own tables, so
one controller serves them all through EpsFirmwareCalibration below. It was developed on the Clarity, so the evidence
below is the Clarity's.

The LKAS path is not a torque command. The firmware turns our 0xE4 value into a target R5, compares it with
R6 -- a filtered steering RATE, taken before its angle table (see computed_r6) -- and runs P + D + KFF on the
difference in its fast control loop (1-2 kHz). So every command first has to cancel the firmware's own rate damping
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
profile after any reflash. Every image's calibration, and what it measured and only carries over, is in
honda_eps_calibrations.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from opendbc.car.honda.steer_ratio import HONDA_VGR_CENTRE_DIVISOR_BY_PROFILE, HONDA_VGR_INVERSE_BY_PROFILE
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import RackMapTable
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


# Command delay, per vehicle: the curvature controlsd hands over is executed this much later, cmd_delay_s in town and
# cmd_delay_highway_s above CMD_DELAY_SPEED_BP. Measured end to end with tools/lateral/plan_timing.py (car curvature from the VSA yaw
# sensor against the model's own plan, hands-off turns at 5-12 m/s): every car measured ran its model's plan early
# without it (early turn-in, loose exits), on this controller and on LatControlPID, because the controller reaches a
# command faster than the model assumes. On an action-head model (Cinque v3) the delay the model is told cannot fix
# that alone: it moves its aim by only ~half of a change in action_t (aim ~ 0.30 + 0.53 * action_t). A plan model is
# read at the told action time exactly (this fork has no MIN_STABLE_DELAY floor; upstream and other forks floor it at 0.3 s),
# so the told delay lands it on time and LatControlHondaEps runs it with no command delay (CMD_DELAY_SCALE_BY_SOURCE,
# from starpilotModelV2.lateralSource). These values are the action-head ones, measured on action-head drives. Each
# delay is sized at or below what was measured, so it cannot make a car late.
# - Clarity (Cinque v3): 0.12-0.14 s early (route 37e); 0.12 s took entries from -0.25 to -0.11 s (route 380).
# - Civic Bosch C020 (tsfdo): routes 290 / 293 / 289 -0.09 / -0.15 / -0.22 s, median -0.15. Checked with it on
#   (routes 2b7 / 2c6 / 2d4): -0.14 / -0.11 / +0.03 s, -0.045 weighted, against -0.15 without it on 289 / 290 / 294.
# - Insight: 0.15, inferred from a LatControlPID drive (see INSIGHT_TXM_A040).
# Unmeasured cars take the default, the smaller of the two, until plan_timing.py measures them.
# Above 15 m/s, where it used to fade out, the cars run early too (2026-10-18, per speed band): the TEG 0.13-0.17 s at
# 12-40 m/s on the TEG routes 12e-13d, the C020 0.16 s at 20-40 m/s on route 380 (no command delay), and the Clarity
# 0.12 / 0.14 / 0.10 s at 17 / 16 / 25 m/s on routes 3f1 / 3f5 (a Mountain-Dew-style action head; 0.10 s is the
# 1667-frame highway band). So the Civics hold theirs flat and the Clarity takes 0.10 s (cmd_delay_highway_s). The
# Insight's Cinque route needed ~0.05 s at 12-20 m/s, under the default, so it still fades to none.
CMD_DELAY_DEFAULT_S = 0.12
CMD_DELAY_SPEED_BP = (10.0, 15.0)  # m/s: cmd_delay_s below, cmd_delay_highway_s above


def command_delay(cal: "EpsFirmwareCalibration", v_ego: float) -> float:
  return float(np.interp(v_ego, CMD_DELAY_SPEED_BP, (cal.cmd_delay_s, cal.cmd_delay_highway_s)))


# Model-delay schedule, per vehicle: the lateral delay the model is told (liveDelay.lateralDelay's role in
# lat_action_t), scheduled on speed, in place of the single SteerDelay / lagd value. Measured on the Clarity, where
# this controller's real execution delay is not one number; the TEG and the C020 have their own (honda_eps_calibrations),
# and every other car takes the Clarity's schedule until a measurement on it gives a reason to change it. Each value
# is the measured lag of car curvature behind the logged model action minus the fixed pipeline offset (0.038 s), so
# the car reaches the requested curvature when the model intends it to.
# - Car curvature comes from the yaw sensor (0x94). The comma gyro runs ~50 ms behind the car and put the
#   first version of this table that much too long.
# - On Cinque v3 the lag hardly depends on the delay the model was told (5-9 m/s: 0.15 / 0.15 / 0.17 s at 0.22 /
#   0.30 / 0.48), so routes are pooled. That is model-specific: on a plan model the action IS the plan read at
#   action_t, exactly (no MIN_STABLE_DELAY floor in this fork), so there the told delay sets the timing 1:1.
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
  r6_per_deg_s: float          # R6 counts per published deg/s (d(0x14A angle)/dt) at centre; see computed_r6
  load: ColumnLoadModel
  p_scale: tuple               # residual PID P/I trims per band (<25 mph, 25-50, >50), fixed per car
  i_scale: tuple
  kff: float = 45.0            # project-added feedforward, KFF45 on every PTM image
  scale_q8: float = 256.0      # helper A * B / 256 while the request is held (median on the Clarity and the C020)
  r5_per_key: float | None = None  # set when the row is linear in the key (the Clarity's row 0): Kp per key, exactly
  r6_angle_bp: tuple | None = None    # |published angle| axis of r6_angle_gain, for images whose A table compresses it
  r6_angle_gain: tuple | None = None  # R6 per published deg/s relative to r6_per_deg_s, see firmware_r6()
  cmd_delay_s: float = CMD_DELAY_DEFAULT_S  # command delay in town, see CMD_DELAY_SPEED_BP
  cmd_delay_highway_s: float = 0.0  # command delay above CMD_DELAY_SPEED_BP
  lat_delay_schedule: tuple = LAT_DELAY_SCHEDULE_DEFAULT  # (speed bp, s): the delay told to the model, see above
  rack: RackMapTable | None = None  # rack ratio after the firmware angle table, yaw-fitted on the car or predicted
                                    # from its specs (honda_eps_spec_plant); when set it is the geometry, ahead of the
                                    # road curve and HondaEpsFirmwareVgr
  friction_width_v: tuple | None = None  # the friction knee at FRICTION_WIDTH_SPEED_BP, deg/s; None: FRICTION_WIDTH_V
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

  def output_ceiling(self) -> float:
    """The largest |output| the firmware still answers: past the end of the command row or the input clamp, more 0xE4
    gives the same R5. A 4096-per-unit car whose row ends at key 1663 (CR-V A040 rows 0-1, A220 rows 0-3) tops out at
    3840/4096 = 0.9375; a car sent its own clamp (the Clarity, the Civics) at 1.0. The speed envelope is left out: it
    lowers the ceiling only at highway speed, on every car, and the validated cars were tuned with 1.0 there."""
    key = min(self.key_clamp, self.r5_key_bp[-1])
    return min(1.0, math.ceil(key * 4.0 * 32768.0 / 56756.0) / self.e4_per_output)


# R6, the firmware's rate feedback, is computed from the image, not measured. The estimator (FUN_343FC) takes the
# per-sample advance of the motor-side, PRE-table angle; NORM scales it into the tracker-1 target (1650, read from
# every corrected image: Clarity, C020, C120, TGG-A120, A030, TEG-A010, TXM-A040, TLA-A040, TLA-A220; stock is 3429)
# and tracker-1 filters it (its coefficient, 3200 / 4000 / 4250 by image, sets a 4-5 ms time constant, not a
# gain); 0x1380C clamps it at +/-32765 in every image. The motor-to-angle constant K = 3121 is the same in every image,
# so per published deg/s (the derivative of 0x14A, which comes out of the A table: published = raw * 2**14 / A):
#   R6(angle) = -122 * (A[0] / 16384) * slope(angle) / slope(0),   then clamped to +/-32765
# where slope is d(linear)/d(published) as a +/-10 deg chord of the image's A table and -122 is R6 per raw deg/s at
# NORM 1650. Checked 2026-10-18 against the telemetry R6 word on every car that has it, on unrailed frames
# (10-150 deg/s): mean |error| over the angle bands 0.7% on the Clarity (routes 363/365/369), 1.9% on the C020
# (287/289/294), 0.8% on the TEG-A010 (133/134/137/13d). The rail is real: R6 sits at 32765 for 92% of frames at
# 200-260 deg/s on the Civics (from ~185 deg/s; ~260 on the Clarity). The ×5 branch of the estimator (|d1| >= 2000)
# lies past the rail, so it never shows. The TEG's and C020's earlier "measured" shapes were fitted with railed frames
# in, which read them 4-7% low past 150 deg.
# steeringRateDeg (0x14A STEER_ANGLE_RATE) is NOT the derivative of the published angle: the firmware publishes it
# through its second, B (rate) table. It reads 1.1% fast at centre on the Clarity and 2-5% slow at 45-100 deg, so
# don't feed it here without converting (see steer_ratio.py).
R6_PER_RAW_DEG_S = -122.0  # NORM 1650
R6_CLAMP = 32765.0         # 0x1380C (Clarity), the same word in every image
R6_GAIN_BP = (0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 180, 210, 240, 270, 300, 360, 420, 480)  # |angle|, deg


def computed_r6(profile: str, norm: float = 1650.0) -> tuple[float, tuple, tuple]:
  """(R6 per published deg/s at centre, |angle| axis, gain by angle) from an image's A table; see above."""
  linear_bp, angle_bp = (np.asarray(x, dtype=float) for x in HONDA_VGR_INVERSE_BY_PROFILE[profile])

  def linear(a: float) -> float:  # past the last knot the table holds its last divisor: linear = a * Y_end / Y0
    return float(np.interp(a, angle_bp, linear_bp)) if a <= angle_bp[-1] else float(a * linear_bp[-1] / angle_bp[-1])

  def slope(a: float) -> float:
    lo = max(a - 10.0, 0.0)
    return (linear(a + 10.0) - linear(lo)) / (a + 10.0 - lo)

  centre = R6_PER_RAW_DEG_S * norm / 1650.0 * HONDA_VGR_CENTRE_DIVISOR_BY_PROFILE[profile] / 16384.0
  return round(centre, 2), R6_GAIN_BP, tuple(round(slope(a) / slope(0.0), 4) for a in R6_GAIN_BP)




# The fits put the Coulomb knee at 2-5 deg/s, but the feedforward keys it on the DESIRED rate, so a knee that
# sharp turns every small wiggle in the model's path into a friction square wave: in the closed-loop sim the wheel
# answers a +/-2 deg, 1 Hz wiggle at 10 m/s with gain 1.40 (Clarity) / 1.63 (C020); a 20 deg/s knee brings that to
# 0.96 / 1.22, and turn-ins (30-200 deg/s) keep the full fitted friction. The price is lag on slow, small motions
# (the friction is then under-compensated), which only pays off at city speed: replaying hands-off chunks of routes
# 35e/360/361, a 20 deg/s knee cut the 0.6-2 Hz wheel/target transfer 0.93 -> 0.73 at 10-16 m/s for +25 ms, but
# above 16 m/s bought nothing (1.02 -> 0.97) for +45 ms of lag and RMS error 0.27 -> 0.37 deg. So it is scheduled:
# 20 deg/s up to 8 m/s, back to 5 by 15 m/s (10-16 m/s: 0.76 at +10 ms; above: unchanged). A calibration can carry
# its own (friction_width_v): on a car whose loop is delay-limited at speed the sharp knee is a rate gain the loop
# cannot afford (the RDX, see ACURA_RDX_TJB_A220).
FRICTION_WIDTH_DEG_S = 5.0
FRICTION_WIDTH_SPEED_BP = [8.0, 15.0]  # m/s
FRICTION_WIDTH_V = [20.0, FRICTION_WIDTH_DEG_S]  # deg/s


def friction_width(v_ego: float, cal: "EpsFirmwareCalibration | None" = None) -> float:
  widths = cal.friction_width_v if cal is not None and cal.friction_width_v is not None else FRICTION_WIDTH_V
  return float(np.interp(v_ego, FRICTION_WIDTH_SPEED_BP, widths))

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
OVERRIDE_FADE_UP_S_DEFAULT = 0.5  # s, the carcontroller's HondaOverrideFadeUpSecs default

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
  """The firmware's rate feedback for a published steering rate at a published angle, clamped where the firmware
  clamps it (+/-32765: from ~185 deg/s on the Civics, ~260 on the Clarity)."""
  gain = 1.0 if cal.r6_angle_bp is None else float(np.interp(abs(angle_deg), cal.r6_angle_bp, cal.r6_angle_gain))
  return max(min(cal.r6_per_deg_s * gain * steering_rate_deg_s, R6_CLAMP), -R6_CLAMP)


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
    width = self.friction_width if self.friction_width is not None else friction_width(v_ego, self.cal)
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

    # Clamp at what the firmware still answers, so the integrator cannot wind into 0xE4 the map ignores
    limit = self.ff.cal.output_ceiling()
    self.pid.set_limits(limit, -limit)
    i_scale = speed_band(v_ego, self.i_scale)
    self.pid.update(error, speed=v_ego, feedforward=ff,
                    freeze_integrator=steer_limited or steering_pressed or v_ego < INTEGRATOR_MIN_SPEED,
                    integrator_gain_scale=i_scale,
                    reset_integrator=i_scale <= 0.0 or v_ego < INTEGRATOR_MIN_SPEED)
    output = max(min(self.pid.p * speed_band(v_ego, self.p_scale) + self.pid.i + self.pid.d + ff, limit), -limit)

    if self.output_lpf_enabled:
      self.output_lpf.update_alpha(speed_band(v_ego, self.output_lpf_tau))
      output = float(self.output_lpf.update(output))
    else:
      self.output_lpf.x = output
      self.output_lpf.initialized = True
    self.output = max(min(output, limit), -limit)
    return self.output
