"""Firmware Controller: per-image EPS calibrations (Clarity TRW-A020 and the Civic, Insight and CR-V images).

Uses the source controller's fixed gains, firmware-inversion feedforward, command
delay and output filter. Geometry is supplied by the shared steer-ratio selection,
just as for PIF; choosing this controller must not replace the user's ratio choice.
Optimized lane changes remain an explicit owner-requested adaptation. The command
delay ends (NrdrYawCommandDelayLow/High) remain Clarity-specific. Every other image
uses its own source delay plus the existing SunnyPilot port compensation. Images
marked provisional in controller_selection have not steered with this controller;
no physical equivalence or road validation is implied.
"""
import numpy as np

from openpilot.cereal import log
from openpilot.common.swaglog import cloudlog
from openpilot.nrdr.params import NrdrParamKey, read_float
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.nrdr.features.lateral.controller_selection import firmware_controller_profile
from openpilot.nrdr.features.lateral.vfn_eps_core import (FIRMWARE_CAR_TUNES, OVERRIDE_FADE_UP_S_DEFAULT,
                                                          HondaEpsFirmwareFeedforward, HondaEpsLateralCore)
from openpilot.nrdr.features.lateral.yaw_control_timing import CommandDelay, command_delay, prediction_delay_schedule
from openpilot.nrdr.features.lateral.latcontrol_pid import _eps_modified_steering_pressed
from openpilot.nrdr.features.lateral.lane_change_tuning import optimized_lane_change_active

VFN_SOURCE_COMMIT = "f837ca86a639b1c20a0ce23bb8acf0ebbc6a05d4"
GAIN_BP = [0.0, 11.175, 11.176, 22.352]
KP = [0.018, 0.024, 0.048, 0.060]
KI = [0.006, 0.008, 0.016, 0.020]
ANGLE_RATE_LIMIT = 300.0


class LatControlFirmware(LatControl):
  owns_output_filter = True
  def __init__(self, CP, CP_SP, CI, dt):
    self.firmware_profile = firmware_controller_profile(CP, CP_SP)
    if self.firmware_profile is None:
      raise ValueError("Firmware control requires a supported modified EPS family with PID CarParams")
    super().__init__(CP, CP_SP, CI, dt)
    self.delay_schedule = prediction_delay_schedule(self.firmware_profile)
    # Each calibration brings its own tables, column load and fixed P/I trims; the base gains are the source's.
    # Never retune CP or increase CAN/safety limits.
    tune = FIRMWARE_CAR_TUNES[self.firmware_profile.calibration]
    self.core = HondaEpsLateralCore(GAIN_BP, KP, GAIN_BP, KI, dt,
      ff=HondaEpsFirmwareFeedforward(dt, cal=tune.calibration, load=tune.load),
      p_scale=tune.p_scale, i_scale=tune.i_scale)
    cloudlog.info("Firmware Controller profile=%s calibration=%s provisional=%s prediction_schedule=%s",
                  self.firmware_profile.name, self.firmware_profile.calibration,
                  self.firmware_profile.provisional, self.delay_schedule)
    self.cmd_delay = CommandDelay(dt)
    self.model_v2 = None
    self.prev_angle = 0.0
    self.pressed_duration = 0.0
    self.pressed_prev = False

  def update_model_v2(self, model_v2):
    self.model_v2 = model_v2

  def reset(self):
    super().reset()
    self.core.reset()
    self.pressed_duration = 0.0
    self.pressed_prev = False

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature,
             calibrated_pose, curvature_limited, lat_delay):
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)
    delay = command_delay(self.live_tuning_snapshot, CS.vEgo, calibration=self.firmware_profile.calibration)
    desired_curvature = self.cmd_delay.update(desired_curvature, delay)
    desired = self.steer_ratio_selection.desired_angle_no_offset(
      VM, CS.steeringAngleDeg, CS.vEgo, params.roll, desired_curvature)
    if active:
      step = ANGLE_RATE_LIMIT * self.dt
      desired = float(np.clip(desired, self.prev_angle - step, self.prev_angle + step))
    self.prev_angle = desired
    angle = desired + params.angleOffsetDeg
    pid_log.steeringAngleDesiredDeg = angle
    pid_log.angleError = angle - CS.steeringAngleDeg
    if not active:
      self.reset()
      output = 0.0
    else:
      self.pressed_duration, pressed = _eps_modified_steering_pressed(
        bool(CS.steeringPressed), float(CS.steeringTorque), self.core.output,
        self.pressed_duration, self.pressed_prev)
      self.pressed_prev = pressed
      state = 0 if self.model_v2 is None else self.model_v2.meta.laneChangeState.raw
      optimized = optimized_lane_change_active(self.live_tuning_snapshot, state)
      if self.live_tuning_snapshot is not None:
        self.core.override_fade_up_s = read_float(self.live_tuning_snapshot, NrdrParamKey.HONDA_OVERRIDE_FADE_UP_SECS,
                                                  OVERRIDE_FADE_UP_S_DEFAULT, 0.0, 10.0)
      output = self.core.update(desired, params.angleOffsetDeg, CS.steeringAngleDeg, CS.vEgo, params.roll,
                                pressed, steer_limited_by_safety, optimized_lane_change=optimized)
      output = float(np.clip(output, -self.steer_max, self.steer_max))
      pid_log.p = float(self.core.pid.p)
      pid_log.i = float(self.core.pid.i)
      pid_log.f = float(self.core.pid.f)
      pid_log.saturated = bool(self._check_saturation(
        self.steer_max - abs(output) < 1e-3, CS, steer_limited_by_safety, curvature_limited))
    ff = self.core.ff
    pid_log.epsFfActive = bool(active)
    pid_log.epsFfWeight = float(self.core.ff_weight)
    pid_log.epsFfFeedforward = float(ff.output)
    pid_log.epsFfR5 = float(ff.r5)
    pid_log.epsFfLoad = float(ff.load)
    pid_log.epsFfDesiredRate = float(ff.rate)
    pid_log.commandDelay = float(delay)
    pid_log.active = bool(active)
    pid_log.output = output
    return output, angle, pid_log
