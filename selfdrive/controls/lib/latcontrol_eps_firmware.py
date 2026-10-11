"""Lateral controller for the modified-EPS Hondas that run a PTM (Proper Torque Mod) EPS image. controlsd selects it
instead of LatControlPID.

The control law is eps_firmware_ff.EpsFirmwareLateralCore: vfn's angle PID on the residual plus a feedforward
that inverts the EPS firmware's own P + D + KFF law, so the command is the one the firmware needs to move the
wheel along the desired path rather than one it has to be dragged into by error. The firmware tables come from
the car's own image (eps_firmware_ff.EpsFirmwareProfile), picked by the EPS part number in carFw.

Which cars get it: a profile with default_on (the Clarity, where it was developed and validated) always; the other
PTM cars (Civic A030/TEG/C020/C120/TGG-A120, Insight, CR-V) only with HondaEpsFirmwareController on, because parts of
their calibration are carried over from a related car until a drive measures them. A car with no profile, or whose
torque map is not the linear [0, E4 cap] the profile expects, keeps LatControlPID. The setting is read once, when
controlsd starts.
Per vehicle, from its profile: the command delay (cmd_delay_s, every car), the model-delay schedule
(lat_delay_schedule) and the yaw-identified rack map (rack), the last two only where they were measured.

This shell does what LatControlPID does around its PID for a modified-EPS Honda, reusing the same helpers so
each setting behaves identically: curvature -> wheel angle through the firmware VGR table (with the ratio and
slip factor identified against the yaw sensor where the profile has one, rack_map.RackMap) or the road-measured ratio
curve (NrdrLatUseFirmwareVgr), the angle-rate ceiling (NrdrLatAngleRateLimit), the shared
driver-override detector, and the speed-banded output low-pass (HondaTorqueOutputLowPassFilter /
HondaTorqueOutputLpfTau*). Settings read elsewhere (carcontroller, carstate, controlsd) apply unchanged.

Not read here, on purpose: LatPScale*, LatIScale*, HondaLateralPidKp/KiScale (the PID is fixed per car to the
tune the feedforward was validated with) and LatFScale* (they scaled the kf * angle * v^2 feedforward this
replaces).
"""
import math
from collections import deque

import numpy as np

from cereal import custom, log
from opendbc.car.honda.carcontroller import get_eps_modified_steering_pressed
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, normalize_honda_eps_fw, vgr_linear_to_physical
from opendbc.car.honda.values import HondaFlags
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.eps_firmware_ff import (
  EpsFirmwareFeedforward,
  EpsFirmwareLateralCore,
  EpsFirmwareProfile,
  command_delay,
  select_eps_firmware_profile,
)
from openpilot.selfdrive.controls.lib.rack_map import RackMap
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

SETTINGS_REFRESH_FRAMES = 300




class CommandDelay:
  """The value issued delay seconds ago, linearly interpolated between frames. Fed every frame, engaged or not,
  so the history is already there at engagement; before it has enough history it returns the oldest value."""

  def __init__(self, dt: float, max_delay: float):
    self.dt = dt
    self.buf: deque[float] = deque(maxlen=int(math.ceil(max_delay / dt)) + 2)

  def update(self, value: float, delay: float) -> float:
    self.buf.append(float(value))
    if delay <= 0.0:
      return float(value)
    steps = delay / self.dt
    i = int(steps)
    frac = steps - i
    n = len(self.buf)
    newer = self.buf[max(n - 1 - i, 0)]
    older = self.buf[max(n - 2 - i, 0)]
    return newer + frac * (older - newer)


def eps_firmware_profile(CP, params=None) -> EpsFirmwareProfile | None:
  """The EPS image profile this car should steer with, or None to keep LatControlPID."""
  if not (bool(CP.flags & HondaFlags.EPS_MODIFIED) and CP.lateralTuning.which() == "pid"):
    return None
  eps_fw = next((normalize_honda_eps_fw(fw.fwVersion) for fw in CP.carFw if fw.ecu == "eps"), None)
  if eps_fw is None:
    return None
  params = params if params is not None else Params()
  profile = select_eps_firmware_profile(str(CP.carFingerprint), eps_fw)
  if profile is None:
    return None
  # The inversion assumes 0xE4 = -output * e4_per_output, i.e. the car's linear modified-EPS torque map
  cap = profile.e4_per_output
  if [float(x) for x in CP.lateralParams.torqueBP] != [0.0, cap] or [float(x) for x in CP.lateralParams.torqueV] != [0.0, cap]:
    return None
  if not profile.default_on and not _get_param_bool(params, "HondaEpsFirmwareController", False):
    return None
  return profile


def use_eps_firmware_controller(CP, params=None) -> bool:
  return eps_firmware_profile(CP, params) is not None


def lateral_delay_schedule(CP, params=None) -> tuple | None:
  """controlsd, modeld: the delay to tell the model in place of liveDelay, when this controller steers the car and
  its profile carries a measured schedule."""
  profile = eps_firmware_profile(CP, params)
  return profile.lat_delay_schedule if profile is not None else None


def scheduled_lateral_delay(schedule: tuple, v_ego: float) -> float:
  return float(np.interp(v_ego, *schedule))


def get_rack_map(CP, profile: EpsFirmwareProfile | None) -> RackMap | None:
  """The yaw-identified rack map, for a profile that has one and the firmware VGR table it was identified through."""
  vgr_inverse = get_honda_vgr_inverse(CP.flags)
  if profile is None or profile.rack is None or vgr_inverse is None:
    return None
  return RackMap(CP.wheelbase, vgr_inverse, profile.rack)


class LatControlEpsFirmware(LatControl):
  def __init__(self, CP, CI, dt, profile: EpsFirmwareProfile | None = None):
    super().__init__(CP, CI, dt)
    self.params = Params()
    self.profile = profile if profile is not None else eps_firmware_profile(CP, self.params)
    assert self.profile is not None, f"no EPS firmware profile for {CP.carFingerprint}"
    cloudlog.info(f"LatControlEpsFirmware: {CP.carFingerprint} steering with EPS profile {self.profile.name}")
    pid = CP.lateralTuning.pid
    self.core = EpsFirmwareLateralCore([float(x) for x in pid.kpBP], [float(x) for x in pid.kpV],
                                       [float(x) for x in pid.kiBP], [float(x) for x in pid.kiV], dt,
                                       ff=EpsFirmwareFeedforward(dt, cal=self.profile))
    self.sr_curve = NRDR_SR_CURVE_BY_FP.get(str(CP.carFingerprint))
    self.sr_curve_inverse = NRDR_SR_CURVE_INVERSE_BY_FP.get(str(CP.carFingerprint))
    self.vgr_inverse = get_honda_vgr_inverse(CP.flags)
    self.rack_map = get_rack_map(CP, self.profile)
    self.cmd_delay = CommandDelay(dt, self.profile.cmd_delay_s)
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

    desired_curvature = self.cmd_delay.update(desired_curvature, command_delay(self.profile, CS.vEgo))
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
