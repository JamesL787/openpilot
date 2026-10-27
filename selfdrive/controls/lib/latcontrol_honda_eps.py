"""ns-bosch-radar-testing Honda EPS core, adapted to res's CP_SP/update API and existing PID log schema.

Selected like the source branch's modified-EPS controller: the modified (comma) rev-b firmware string on a Civic Bosch,
with the linear 3840 map and a PID tune. The H020 vehicle coefficients are the TGG donor's and provisional.
No StarPilot schema, new Params keys or global PID API are required.
"""
import math
from collections import deque

import numpy as np
from cereal import log
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.honda_eps_firmware_ff import HondaEpsFirmwareFeedforward, HondaEpsLateralCore
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import H020
from openpilot.selfdrive.controls.lib.honda_eps_h020_geometry import H020_VGR_INVERSE
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
from opendbc.sunnypilot.car.honda.h020_ptm import H020Settings, is_h020
from openpilot.selfdrive.controls.lib.honda_eps_h020_override import get_eps_modified_steering_pressed

RIDE_THROUGH_S = 0.1


class CommandDelay:
  """The value issued `delay` seconds ago, linearly interpolated between frames. Fed every frame, engaged or not, so the
  history is already there at engagement; before it has enough history it returns the oldest value."""

  def __init__(self, dt, max_delay):
    self.dt = dt
    self.buf = deque(maxlen=int(math.ceil(max_delay / dt)) + 2)

  def update(self, value, delay):
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


def use_honda_eps_controller(CP):
  return (str(CP.carFingerprint) == "HONDA_CIVIC_BOSCH" and is_h020(CP.carFw) and CP.lateralTuning.which() == "pid"
          and list(CP.lateralParams.torqueBP) == [0, 3840] and list(CP.lateralParams.torqueV) == [0, 3840])


def warn_if_h020_tune_replaced(CP, cloudlog):
  """setup_interfaces (EnforceTorqueControl / NNLC) runs after the tune is set and can replace it with the torque tune."""
  if str(CP.carFingerprint) == "HONDA_CIVIC_BOSCH" and is_h020(CP.carFw) and not use_honda_eps_controller(CP):
    cloudlog.error("H020 rev-b EPS present but the H020 controller is not selected (the tune was replaced); using the generic controller")


class ScaledFeedforward(HondaEpsFirmwareFeedforward):
  """The firmware-inversion feedforward times a live scale; its own smoothing state is left unscaled."""
  def __init__(self, dt, cal, scale):
    super().__init__(dt, cal)
    self.scale = scale

  def update(self, *args):
    return super().update(*args) * self.scale()


class LatControlHondaEps(LatControl):
  def __init__(self, CP, CP_SP, CI):
    super().__init__(CP, CP_SP, CI)
    if not use_honda_eps_controller(CP):
      raise ValueError("H020 controller needs the exact rev-b EPS, a Civic Bosch, a PID tune and a linear 3840 map")
    self.dt = DT_CTRL
    self.calibration = H020
    pid = CP.lateralTuning.pid
    self.cmd_delay = CommandDelay(DT_CTRL, 0.5)  # 0.5 s is the largest setting
    self.settings = H020Settings()  # tuning scales from settings files (h020_ptm), re-read about once a second
    self.core = HondaEpsLateralCore(list(pid.kpBP), list(pid.kpV), list(pid.kiBP), list(pid.kiV), DT_CTRL,
                                  ScaledFeedforward(DT_CTRL, self.calibration, lambda: self.settings.feedforward_scale))
    # res does not have the source branch's override fade; do not assume it does.
    self.core.override_fade_up_s = 0.0
    # Match the source wrapper default, rather than the numerical core's different defaults.
    self.core.output_lpf_tau = (0.1, 0.1, 0.1)
    self.rack = HondaEpsRackMap(CP.wheelbase, H020_VGR_INVERSE, self.calibration.rack)
    self.previous_desired = None
    self.inactive_frames = math.inf
    self.ride_through_frames = int(round(RIDE_THROUGH_S / DT_CTRL))
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_prev = False

  def reset(self):
    # controlsd calls reset before update on every inactive frame, as in the source wrapper.
    if self.inactive_frames > self.ride_through_frames:
      self._hard_reset()

  def _hard_reset(self):
    super().reset()
    self.core.reset()
    self.previous_desired = None
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_prev = False

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, calibrated_pose, curvature_limited):
    self.settings.tick()
    s = self.settings.pid_scale
    self.core.p_scale = tuple(x * s for x in self.calibration.p_scale)
    self.core.i_scale = tuple(x * s for x in self.calibration.i_scale)
    pid_log = log.ControlsState.LateralPIDState.new_message()
    inputs = (CS.steeringAngleDeg, CS.steeringRateDeg, CS.vEgo, params.roll, params.angleOffsetDeg, desired_curvature, CS.steeringTorque)
    if not all(math.isfinite(float(x)) for x in inputs):
      self._hard_reset()
      self.inactive_frames = math.inf
      pid_log.active = False
      return 0.0, 0.0, pid_log
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)
    desired_curvature = self.cmd_delay.update(desired_curvature, self.settings.command_delay(CS.vEgo))
    desired = self.rack.angle_from_curvature(desired_curvature, CS.vEgo, params.roll)
    if active:
      # Deliberate adaptation: initialize the source's slew limiter at the actual wheel on engagement.
      previous = self.previous_desired if self.previous_desired is not None else CS.steeringAngleDeg - params.angleOffsetDeg
      desired = float(np.clip(desired, previous - 300.0 * DT_CTRL, previous + 300.0 * DT_CTRL))
      self.previous_desired = desired
    angle = desired + params.angleOffsetDeg
    pid_log.steeringAngleDesiredDeg = float(angle)
    pid_log.angleError = float(angle - CS.steeringAngleDeg)
    if not active:
      self.inactive_frames += 1
      if self.inactive_frames > self.ride_through_frames:
        self._hard_reset()
      else:
        # Brief dropout: update the model, freeze integration and send ZERO actuation.
        self.core.update(desired, params.angleOffsetDeg, CS.steeringAngleDeg, CS.vEgo, params.roll, False, True)
      output = 0.0
      pid_log.active = False
    else:
      self.inactive_frames = 0
      self.steering_pressed_filter_s, pressed = get_eps_modified_steering_pressed(
        bool(CS.steeringPressed), float(CS.steeringTorque), float(self.core.output),
        self.steering_pressed_filter_s, self.steering_pressed_prev)
      self.steering_pressed_prev = pressed
      # The filtered signal controls the FF/integrator only. res/panda still gate actual steering.
      output = float(self.core.update(desired, params.angleOffsetDeg, CS.steeringAngleDeg,
                                      CS.vEgo, params.roll, pressed, steer_limited_by_safety))
      if not math.isfinite(output):
        self._hard_reset()
        self.inactive_frames = math.inf
        output = 0.0
      output = float(np.clip(output, -self.steer_max, self.steer_max))
      pid_log.active = True
      pid_log.p = float(self.core.pid.p)
      pid_log.i = float(self.core.pid.i)
      pid_log.f = float(self.core.pid.f)
      pid_log.output = output
      pid_log.saturated = bool(self._check_saturation(abs(output) >= self.steer_max - 1e-3,
                                                     CS, steer_limited_by_safety, curvature_limited))
    return output, float(angle), pid_log
