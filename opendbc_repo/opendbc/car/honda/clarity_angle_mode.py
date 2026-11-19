"""Clarity angle mode: openpilot sends a steering-wheel angle target in 0xE4 to the angle-mode EPS build (rwd-xray
lab/clarity/CLARITY_ANGLE_MODE_20261117, build 0x04; format: ANGLE_MODE_E4_FORMAT_PROPOSAL_20261117.md, option A).

Chosen at startup by the setting ANGLE_MODE_PARAM (Night Star / Galaxy row "Angle Mode", default on): card's startup
hook (openpilot starpilot/car/honda/clarity_angle_mode.py) calls apply_angle_mode, which on a Clarity with modified EPS
firmware sets HondaFlags.CLARITY_ANGLE_MODE and steerControlType = angle. Off, or any other car: nothing changes (torque
mode, CleanPTM request). On a Clarity whose EPS is not the angle build, the 0x6A4 interlock never reports ready, so
openpilot faults "no_angle_loop" and sends no steering: turn the setting off on any other EPS firmware.

0xE4 in angle mode (every frame, 100 Hz):
  byte 3   = 0x07: mode 3 (bits 3:1) + control type angle (bit 0), always, so the EPS switches to mode 3 at LKAS idle
  bytes 0-1, byte 2 bit 7 (request), byte 2 bit 5 (angle payload): the target, only while the EPS reports in 0x6A4 that
           it runs mode 3 on a build with the angle loop (eps_cal_status.EpsCalStatus.angle_ready) and lateral is
           active. Otherwise all zero: an EPS that is not in mode 3 would read bytes 0-1 as a torque (stock, MM 0x02),
           and panda blocks non-zero bytes 0-1 while lateral is not allowed.
Units: bytes 0-1 = the EPS's own 0x14A STEER_ANGLE raw value (0.1 deg/bit, raw = -10 * CS.steeringAngleDeg).

Limits (all inside the EPS's own, so its jump-reject fault and its clamps never act in normal driving):
  - per-frame step <= 0.6 x the EPS jump threshold (4 deg/10 ms below 5 m/s, 1 deg/10 ms from 15 m/s; the EPS
    allows 0.8 x at the worst frame spacing) and <= 0.9 x the EPS reference slew (5 m/s^3 lateral jerk, 170 deg/s cap)
  - the target moves as a rate- and acceleration-limited trajectory (v2, 11-18 first drive): rate <= TARGET_RATE(v),
    acceleration <= TARGET_ACCEL(v) (~1.5 x the wheel acceleration openpilot produced hands-off in torque mode, p99),
    braking ahead of the target (sqrt(2*A*error)) so it never overshoots. The angle loop follows its target closely and
    is silent, so without this every model wobble and every re-engage reached the wheel at up to 160 deg/s in 10 ms
    (v1: 0.5 s at 10 deg/s, then the full step limit -> the "snap" after an override, route 000000e7).
  - the Steering Angle Rate Limit setting (HondaEpsAngleRateLimit, deg/s, 0 = off; CarController passes it) lowers the
    rate cap further; the angle lateral controller itself only converts curvature to angle (rack map / VGR)
  - engage (request rises, e.g. after a driver override): the trajectory starts at the measured angle AND the measured
    wheel rate, and its rate/acceleration limits ramp from ENGAGE_FLOOR to full over the engage time, so control fades
    in. The engage time is the Override Fade Up setting (HondaOverrideFadeUpSecs, Night Star; CarController passes it),
    ENGAGE_S without settings; 0 = full limits at once (still starting from the wheel, still acceleration-limited)
  - |desired| <= 0.95 x the EPS's 4 m/s^2 lateral-acceleration clamp (angle_ref.AMAX), applied before the limits
  - not active: the target is the measured angle (the Tesla pattern), so the first target the EPS sees equals its own
    angle. lat_active is CarController's modified-EPS lkas_active, which drops while the driver overrides (same press
    detector and yield as torque mode), so a press ends the request and the next engage restarts from the wheel.
"""
import numpy as np

from opendbc.car import DT_CTRL
from opendbc.car import structs
from opendbc.car.honda.values import CAR, HondaFlags

ANGLE_MODE_PARAM = "HondaClarityAngleMode"   # BOOL, default "1" (params_keys.h); read once at startup
EPS_MODE_ANGLE = 3            # byte 3 bits 3:1
BYTE3_ANGLE = (EPS_MODE_ANGLE << 1) | 1
EPS_MODE_ANGLE_CAP3 = 4       # build 0x05: mode 4 = the same angle loop with a 3.0 m/s^2 clamp (byte 3 = 0x09)
CAP3_BUILDS = {0x05, 0x06}    # builds that have mode 4
AUTH_BUILDS = {0x06}          # build 0x06: angle-loop authority gain, byte 3 bits 7:4 = CUT (0 = full .. 15 = none)
AMAX_CAP3_SCALE = 3.0 / 4.0   # angle_ref AMAX4_SCALE: mode 4's clamp table = mode 3's x 0.75 (clamp angle is linear in a_lat)
ANGLE_PAYLOAD = 0x20          # byte 2 bit 5 (DBC SET_ME_X00 holds byte 2 bits 6:0)
RAW_PER_DEG = -10.0           # 0x14A STEER_ANGLE factor is -0.1

# EPS limits (angle_ref.py v3: JUMP, SLEW, AMAX), speed m/s
_V = [0., 5., 8., 10., 12., 15., 20., 25., 30.]
EPS_JUMP_DEG = [4.0, 4.0, 3.1, 2.5, 1.9, 1.0, 1.0, 1.0, 1.0]                     # per 10 ms
EPS_SLEW_DEG_S = [170.0, 170.0, 170.0, 143.9, 103.1, 69.7, 43.8, 31.8, 25.3]
ANGLE_STEP_DEG = [min(0.6 * j, 0.9 * s * DT_CTRL) for j, s in zip(EPS_JUMP_DEG, EPS_SLEW_DEG_S, strict=True)]
AMAX_V = [5., 8., 10., 12., 16., 20., 25., 30.]
EPS_AMAX_DEG = [379., 160., 109., 80.3, 50.0, 35.3, 25.7, 20.4]
ANGLE_MAX_FRAC = 0.95
# target trajectory (v2): rate and acceleration limits by speed, engage fade
_VT = [0., 5., 10., 15., 20., 30.]
TARGET_RATE_DEG_S = [150., 150., 100., 60., 40., 25.]
TARGET_ACCEL_DEG_S2 = [450., 600., 450., 300., 225., 180.]    # 1.5 x torque-mode hands-off p99 (11-15 route)
ENGAGE_S, ENGAGE_FLOOR = 1.5, 0.15    # limits ramp 15% -> 100% after the request rises; ENGAGE_S = default engage time
RAW_MAX = 32767
# authority ramp (build 0x06, sunnypilot HKG CAN-FD angle torque_reduction_gain): while the driver overrides, the request
# and the plan target stay up and the loop's authority falls to AUTH_MIN over AUTH_DOWN_FRAMES (adaptive, at least
# AUTH_DOWN_MIN_STEP per frame); after the release it climbs back over Override Fade Up (AUTH_UP_DEFAULT per frame if 0)
AUTH_MIN, AUTH_DOWN_FRAMES, AUTH_DOWN_MIN_STEP, AUTH_UP_DEFAULT = 0.1, 17.0, 0.004, 0.008
# Off by default (emulator 11-19, hands-on model): holding the request through an override keeps the stock EPS's own
# rate damping on, which drags the driver's wheel even at near-zero loop authority (seg 36: wheel 15-18 deg behind,
# hands-off tracking 1.75 -> 3.39 deg). With it off, build 0x06 still ramps the loop in over ~1 s after every engage
# and override in firmware (re-engage wheel acceleration 724 -> 435 median), with no drag. True = the HKG experiment.
# 11-19 (build 0x07 investigation): holding is blocked by the STOCK EPS, not by damping. FUN_28D5A flags a driver override
# when |T_comp| >= 1536 (cal 0x1375C) for 50 ticks; FUN_2A994 then latches LKAS off (0xFFF879C9 3 -> 1) if the LKAS command
# stays > 44 for 100 more ticks, and only clears after <= 44 for 1000 ticks (2 s). The stock override fade (FUN_29CAE) also
# zeroes LKAS above 1536 anyway. So a held request gives no assist during the press and risks a 2 s lockout. Keep it off.
HOLD_THROUGH_OVERRIDE = False


def apply_angle_mode(CP, requested: bool):
  """Startup choice. Only a Clarity on modified EPS firmware can run the angle build; every other car is untouched."""
  if requested and CP.carFingerprint == CAR.HONDA_CLARITY and CP.flags & HondaFlags.EPS_MODIFIED:
    CP.flags |= HondaFlags.CLARITY_ANGLE_MODE.value
    CP.steerControlType = structs.CarParams.SteerControlType.angle
  return CP


def angle_mode(CP) -> bool:
  return bool(CP.flags & HondaFlags.CLARITY_ANGLE_MODE)


def angle_limit(v_ego: float, amax_scale: float = 1.0) -> float:
  return ANGLE_MAX_FRAC * amax_scale * float(np.interp(v_ego, AMAX_V, EPS_AMAX_DEG))


def angle_to_raw(angle_deg: float) -> int:
  return int(max(-RAW_MAX, min(RAW_MAX, round(angle_deg * RAW_PER_DEG))))


class AngleModeSender:
  """Turns actuators.steeringAngleDeg into the 0xE4 angle payload. update() returns (raw, request, payload_bit)."""
  def __init__(self):
    self.apply_angle = 0.0
    self.apply_rate = 0.0
    self.active_frames = 0
    self.sent_active = False
    self.out_angle = 0.0      # the angle actually sent (= apply_angle once the effort fade is done)

  def update(self, lat_active: bool, desired_deg: float, measured_deg: float, v_ego: float,
             angle_ready: bool, measured_rate_deg_s: float = 0.0, engage_s: float = ENGAGE_S,
             amax_scale: float = 1.0, rate_limit_deg_s: float = 0.0, effort_fade: bool = True) -> tuple[int, bool, int]:
    active = bool(lat_active and angle_ready)
    if not active:
      self.apply_angle, self.apply_rate = float(measured_deg), float(measured_rate_deg_s)
      self.out_angle = float(measured_deg)
      self.active_frames, self.sent_active = 0, False
      return 0, False, 0
    lim = angle_limit(v_ego, amax_scale)    # amax_scale = AMAX_CAP3_SCALE while the EPS runs mode 4
    # clamp the target, not the output, so the output still moves along the limited trajectory (from a measured angle
    # above the clamp it walks down to it instead of jumping, which the EPS would reject)
    target = float(np.clip(float(desired_deg), -lim, lim))
    fade = 1.0 if engage_s <= 0.0 else min(1.0, ENGAGE_FLOOR + (1.0 - ENGAGE_FLOOR) * self.active_frames * DT_CTRL / engage_s)
    rate_cap = min(float(np.interp(v_ego, _VT, TARGET_RATE_DEG_S)), float(np.interp(v_ego, _V, ANGLE_STEP_DEG)) / DT_CTRL)
    if rate_limit_deg_s > 0.0:                # Steering Angle Rate Limit (Night Star / Galaxy), 0 = off
      rate_cap = min(rate_cap, rate_limit_deg_s)
    rate_max = fade * rate_cap
    accel_max = fade * float(np.interp(v_ego, _VT, TARGET_ACCEL_DEG_S2))
    err = target - self.apply_angle
    # exact discrete braking curve: the fastest rate from which the trajectory can still stop at the target with
    # accel_max per frame (the continuous sqrt(2*A*e) overshoots by a frame)
    ad = accel_max * DT_CTRL
    brake = ad * (((0.25 + 2.0 * abs(err) / (ad * DT_CTRL)) ** 0.5) - 0.5) if ad > 0 else 0.0
    rate_des = float(np.sign(err)) * min(rate_max, brake, abs(err) / DT_CTRL)
    self.apply_rate += float(np.clip(rate_des - self.apply_rate, -accel_max * DT_CTRL, accel_max * DT_CTRL))
    # rate_max shapes rate_des only, so a wheel already turning faster at engage eases down at accel_max instead of being
    # stopped in one frame; the EPS's own per-frame jump limit stays a hard bound
    step_rate = float(np.interp(v_ego, _V, ANGLE_STEP_DEG)) / DT_CTRL
    self.apply_rate = float(np.clip(self.apply_rate, -step_rate, step_rate))
    self.apply_angle += self.apply_rate * DT_CTRL
    # effort fade: the EPS loop pushes in proportion to (target - wheel), so sending wheel + w * (trajectory - wheel)
    # scales its effort by w. w eases 0 -> 1 (smoothstep) over engage_s after the request rises, so the loop takes the
    # wheel over gently instead of pulling it onto the trajectory at full stiffness. The sent angle still moves at most
    # the EPS's per-frame jump limit.
    out = self.apply_angle
    if effort_fade and engage_s > 0.0:
      x = min(1.0, (self.active_frames + 1) * DT_CTRL / engage_s)
      w = x * x * (3.0 - 2.0 * x)
      out = float(measured_deg) + w * (self.apply_angle - float(measured_deg))
    step = float(np.interp(v_ego, _V, ANGLE_STEP_DEG))
    self.out_angle += float(np.clip(out - self.out_angle, -step, step))
    self.active_frames += 1
    self.sent_active = True
    return angle_to_raw(self.out_angle), True, ANGLE_PAYLOAD


class AuthorityRamp:
  """Build 0x06: the angle loop's authority g (0..1) -> CUT = round(15 (1 - g)) for byte 3 bits 7:4. The EPS slews its
  own gain to 256 - 17*CUT (Q8, up at most 1/256 and down 6/256 per 4 ms) and zeroes it whenever the loop
  (re)activates (angle_ref v4), so with CUT 0 every engage still ramps in over ~1 s."""
  def __init__(self):
    self.g = 0.0

  def update(self, active: bool, yielding: bool, fade_up_s: float) -> int:
    if not active:
      self.g = 0.0
    elif yielding:
      if self.g > AUTH_MIN:
        self.g = max(self.g - max((self.g - AUTH_MIN) / AUTH_DOWN_FRAMES, AUTH_DOWN_MIN_STEP), AUTH_MIN)
    else:
      self.g = min(1.0, self.g + (DT_CTRL / fade_up_s if fade_up_s > 0.0 else AUTH_UP_DEFAULT))
    return int(round(15.0 * (1.0 - self.g)))
