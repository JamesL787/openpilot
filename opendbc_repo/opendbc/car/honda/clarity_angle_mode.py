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
CAP3_BUILDS = {0x05}          # builds that have mode 4
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

  def update(self, lat_active: bool, desired_deg: float, measured_deg: float, v_ego: float,
             angle_ready: bool, measured_rate_deg_s: float = 0.0, engage_s: float = ENGAGE_S,
             amax_scale: float = 1.0, rate_limit_deg_s: float = 0.0) -> tuple[int, bool, int]:
    active = bool(lat_active and angle_ready)
    if not active:
      self.apply_angle, self.apply_rate = float(measured_deg), float(measured_rate_deg_s)
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
    self.active_frames += 1
    self.sent_active = True
    return angle_to_raw(self.apply_angle), True, ANGLE_PAYLOAD
