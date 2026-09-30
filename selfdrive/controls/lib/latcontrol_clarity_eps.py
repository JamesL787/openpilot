"""nrdr: lateral controller for the Honda Clarity with a modified EPS. controlsd selects it instead of LatControlPID.

The control law is nrdr_eps_firmware_ff.ClarityEpsLateralCore: vfn's angle PID on the residual plus a
feedforward that inverts the EPS firmware's own P + D + KFF law, so the command is the one the firmware needs
to move the wheel along the desired path rather than one it has to be dragged into by error.

This shell does what LatControlPID does around its PID for a modified-EPS Honda, reusing the same helpers so
each setting behaves identically: curvature -> wheel angle through the firmware VGR table (here with the
ratio and slip factor identified against the car's yaw sensor, ClarityRackMap) or the road-measured ratio curve
(NrdrLatUseFirmwareVgr), the angle-rate ceiling (NrdrLatAngleRateLimit), the shared
driver-override detector, and the speed-banded output low-pass (HondaTorqueOutputLowPassFilter /
HondaTorqueOutputLpfTau*). Settings read elsewhere (carcontroller, carstate, controlsd) apply unchanged.

Not read here, on purpose: LatPScale*, LatIScale*, HondaLateralPidKp/KiScale (the PID is fixed to the tune the
feedforward was validated with) and LatFScale* (they scaled the kf * angle * v^2 feedforward this replaces).
"""
import math

import numpy as np

from cereal import custom, log
from opendbc.car.honda.carcontroller import get_eps_modified_steering_pressed
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, vgr_linear_to_physical
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from openpilot.common.params import Params
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.latcontrol_pid import (
  NRDR_ANGLE_RATE_LIMIT_DEG_S,
  NRDR_SR_CURVE_BY_FP,
  NRDR_SR_CURVE_INVERSE_BY_FP,
  NRDR_TORQUE_OUTPUT_LPF_TAU,
  _get_param_bool,
  _get_param_float,
  rate_limit_desired_angle,
  solve_angle_from_ratio_curve,
)
from openpilot.selfdrive.controls.lib.nrdr_eps_firmware_ff import ClarityEpsLateralCore

SETTINGS_REFRESH_FRAMES = 300

# Lateral delay the model is told (liveDelay.lateralDelay's role in lat_action_t), scheduled on speed. It
# replaces the single SteerDelay / lagd value for this controller, whose real execution delay is not one
# number. Each value is the measured lag of car curvature behind the logged model action minus the fixed
# pipeline offset (0.038 s), so the car reaches the requested curvature when the model intends it to.
# - Car curvature comes from the yaw sensor (0x94). The comma gyro runs ~50 ms behind the car and put the
#   first version of this table that much too long.
# - The lag hardly depends on the delay the model was told (5-9 m/s: 0.15 / 0.15 / 0.17 s at 0.22 / 0.30 /
#   0.48), so routes 354-36b are pooled.
# - Above 15 m/s lane centering pulls 6-10% of a curve back out through its 0.4 s smoothing and reads as extra
#   lag. That is not delay and the model cannot aim around it, so those values sum the stage lags without it.
# lagd only learns above 15 m/s, so it cannot find the low-speed end.
CLARITY_LAT_DELAY_BP = [3.5, 7.0, 12.0, 20.0, 30.0]  # m/s, centres of the measured bands
CLARITY_LAT_DELAY_V = [0.12, 0.12, 0.15, 0.20, 0.30]  # s

# Wheel angle <-> curvature, identified against the car's own yaw sensor (0x94, GPS-verified) on routes 341-36b.
# VehicleModel's form is kept, lin = R * L * [k (1 - sf v^2) - g sf roll], with lin the firmware-VGR linear
# angle of the physical wheel angle. But its single ratio (paramsd, learned from a comma gyro that reads 3% low)
# and its slip factor (-0.00061 from the tyre stiffness defaults) are replaced by what the car does:
# - The effective ratio R still falls with angle after the firmware table, 18.2 near centre to 15.8 at 400 deg.
#   The rack is quicker off centre than the A table says.
# - The slip factor is -0.0005.
# Each value is the median of left and right turns, so an angle offset cancels. Against the yaw sensor this map
# predicts car curvature from wheel angle within 0.7% at 20-500 deg below 15 m/s and within 3.7% everywhere.
# The paramsd ratio with VM's slip factor over-predicted the angle needed by 3-6% in the city, the over-steer
# through tight turns.
CLARITY_RATIO_BP = [6.5, 15.0, 32.0, 57.0, 85.0, 125.0, 175.0, 230.0, 305.0, 400.0]  # physical wheel angle, deg
CLARITY_RATIO_V = [18.21, 17.63, 17.12, 16.77, 16.69, 16.52, 16.31, 16.19, 16.10, 15.83]
CLARITY_SLIP_FACTOR = -0.0005  # 1 / (m/s)^2
GRAVITY = 9.81


def use_clarity_eps_controller(CP) -> bool:
  return (CP.carFingerprint == HONDA.HONDA_CLARITY and bool(CP.flags & HondaFlags.EPS_MODIFIED)
          and CP.lateralTuning.which() == "pid")


def clarity_lateral_delay(v_ego: float) -> float:
  return float(np.interp(v_ego, CLARITY_LAT_DELAY_BP, CLARITY_LAT_DELAY_V))


class ClarityRackMap:
  """Physical wheel angle (deg, left-positive) <-> curvature (1/m, openpilot's right-positive), see CLARITY_RATIO_*."""
  def __init__(self, wheelbase: float, vgr_inverse):
    linear_bp, angle_bp = (np.asarray(x, dtype=float) for x in vgr_inverse)
    self.wheelbase = float(wheelbase)
    self.angle_grid = np.unique(np.r_[angle_bp, np.linspace(0.0, angle_bp[-1], 1001)])
    linear = np.radians(np.interp(self.angle_grid, angle_bp, linear_bp))
    self.path_grid = linear / np.interp(self.angle_grid, CLARITY_RATIO_BP, CLARITY_RATIO_V)  # = L * k at zero roll/slip
    assert np.all(np.diff(self.path_grid) > 0), "rack map must be monotonic to invert"

  def angle_from_curvature(self, curvature: float, v_ego: float, roll: float) -> float:
    k = -curvature
    path = self.wheelbase * (k * (1.0 - CLARITY_SLIP_FACTOR * v_ego ** 2) - GRAVITY * CLARITY_SLIP_FACTOR * roll)
    return math.copysign(float(np.interp(abs(path), self.path_grid, self.angle_grid)), path)

  def curvature_from_angle(self, angle_deg: float, v_ego: float, roll: float) -> float:
    path = math.copysign(float(np.interp(abs(angle_deg), self.angle_grid, self.path_grid)), angle_deg)
    k = (path / self.wheelbase + GRAVITY * CLARITY_SLIP_FACTOR * roll) / (1.0 - CLARITY_SLIP_FACTOR * v_ego ** 2)
    return -k


def get_clarity_rack_map(CP) -> ClarityRackMap | None:
  # identified on the TRW A020 firmware's A table only
  if not (use_clarity_eps_controller(CP) and CP.flags & HondaFlags.VGR_CLARITY_TRW_A020):
    return None
  return ClarityRackMap(CP.wheelbase, get_honda_vgr_inverse(HondaFlags.VGR_CLARITY_TRW_A020))


class LatControlClarityEps(LatControl):
  def __init__(self, CP, CI, dt):
    super().__init__(CP, CI, dt)
    pid = CP.lateralTuning.pid
    self.core = ClarityEpsLateralCore([float(x) for x in pid.kpBP], [float(x) for x in pid.kpV],
                                      [float(x) for x in pid.kiBP], [float(x) for x in pid.kiV], dt)
    self.sr_curve = NRDR_SR_CURVE_BY_FP.get(str(CP.carFingerprint))
    self.sr_curve_inverse = NRDR_SR_CURVE_INVERSE_BY_FP.get(str(CP.carFingerprint))
    self.vgr_inverse = get_honda_vgr_inverse(CP.flags)
    self.rack_map = get_clarity_rack_map(CP)
    self.params = Params()
    self.frame = -1
    self.prev_rate_limited_angle = 0.0
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_prev = False
    self.starpilot_lateral_state = custom.StarPilotLateralState.new_message()
    self._read_settings()

  def _read_settings(self):
    self.use_firmware_vgr = _get_param_bool(self.params, "NrdrLatUseFirmwareVgr")
    self.angle_rate_limit_deg_s = _get_param_float(self.params, "NrdrLatAngleRateLimit", NRDR_ANGLE_RATE_LIMIT_DEG_S, 0.0, 2000.0)
    self.core.output_lpf_enabled = _get_param_bool(self.params, "HondaTorqueOutputLowPassFilter", True)
    self.core.output_lpf_tau = tuple(
      _get_param_float(self.params, key, NRDR_TORQUE_OUTPUT_LPF_TAU, 0.0, 5.0)
      for key in ("HondaTorqueOutputLpfTauLowSpeed", "HondaTorqueOutputLpfTauStandard", "HondaTorqueOutputLpfTauHighway")
    )

  def reset(self):
    super().reset()
    self.core.reset()
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_prev = False

  def _desired_angle_no_offset(self, VM, v_ego, roll, desired_curvature):
    # Same rack map selection as LatControlPID; see the comments there for why the two maps differ.
    if self.sr_curve is not None and not (self.use_firmware_vgr and self.vgr_inverse is not None):
      sr_bp, sr_v = self.sr_curve
      VM.sR = 1.0
      unit_ratio_angle = math.degrees(VM.get_steer_from_curvature(-desired_curvature, v_ego, roll))
      angle = solve_angle_from_ratio_curve(unit_ratio_angle, sr_bp, sr_v, self.sr_curve_inverse)
      VM.sR = float(np.interp(abs(angle), sr_bp, sr_v))
      return angle
    if self.rack_map is not None:
      return self.rack_map.angle_from_curvature(desired_curvature, v_ego, roll)
    linear = math.degrees(VM.get_steer_from_curvature(-desired_curvature, v_ego, roll))
    return vgr_linear_to_physical(linear, self.vgr_inverse)

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, curvature_limited,
             lat_delay, calibrated_pose, model_data, starpilot_toggles):
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)

    angle_des_no_offset = self._desired_angle_no_offset(VM, CS.vEgo, params.roll, desired_curvature)
    if active:
      angle_des_no_offset = rate_limit_desired_angle(angle_des_no_offset, self.prev_rate_limited_angle,
                                                     self.angle_rate_limit_deg_s, self.dt)
    self.prev_rate_limited_angle = angle_des_no_offset

    angle_des = angle_des_no_offset + params.angleOffsetDeg
    pid_log.steeringAngleDesiredDeg = angle_des
    pid_log.angleError = angle_des - CS.steeringAngleDeg

    if not active:
      self.reset()
      output = 0.0
      pid_log.active = False
    else:
      self.frame += 1
      if self.frame % SETTINGS_REFRESH_FRAMES == 0:
        self._read_settings()
      self.steering_pressed_filter_s, steering_pressed = get_eps_modified_steering_pressed(
        bool(CS.steeringPressed), float(getattr(CS, "steeringTorque", 0.0)), float(self.core.output),
        self.steering_pressed_filter_s, self.steering_pressed_prev,
      )
      self.steering_pressed_prev = steering_pressed
      output = self.core.update(angle_des_no_offset, params.angleOffsetDeg, CS.steeringAngleDeg, CS.vEgo, params.roll,
                                steering_pressed, steer_limited_by_safety)
      output = float(max(min(output, self.steer_max), -self.steer_max))

      pid_log.active = True
      pid_log.p = float(self.core.pid.p)
      pid_log.i = float(self.core.pid.i)
      pid_log.f = float(self.core.pid.f)
      pid_log.output = output
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output) < 1e-3, CS, steer_limited_by_safety,
                                                      curvature_limited))

    ff = self.core.ff
    state = self.starpilot_lateral_state
    state.epsFfActive = bool(active)
    state.epsFfWeight = float(self.core.ff_weight)
    state.epsFfFeedforward = float(ff.output)
    state.epsFfR5 = float(ff.r5)
    state.epsFfLoad = float(ff.load)
    state.epsFfDesiredRate = float(ff.rate)
    return output, angle_des, pid_log
