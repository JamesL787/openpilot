"""ns-bosch-radar-testing Honda EPS core, adapted to res's CP_SP/update API and existing PID log schema.

The H020 vehicle coefficients are provisional. Activation needs an explicit config file and an exact PTM part.
No StarPilot schema, HondaFlags.EPS_MODIFIED, new Params keys, or global PID API are required.
"""
import math
import numpy as np
from cereal import log
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.honda_eps_firmware_ff import HondaEpsFirmwareFeedforward, HondaEpsLateralCore
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import H020
from openpilot.selfdrive.controls.lib.honda_eps_h020_geometry import H020_VGR_INVERSE
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
from opendbc.sunnypilot.car.honda.h020_ptm import read_config, is_h020_ptm


def use_honda_eps_controller(CP, config=None):
  cfg = read_config() if config is None else config
  if not cfg.get("enabled") or str(CP.carFingerprint) != "HONDA_CIVIC_BOSCH" or not is_h020_ptm(CP.carFw):
    return False
  return (CP.lateralTuning.which() == "pid" and
          list(CP.lateralParams.torqueBP) == [0, 3840] and list(CP.lateralParams.torqueV) == [0, 3840])


class LatControlHondaEps(LatControl):
  def __init__(self, CP, CP_SP, CI):
    super().__init__(CP, CP_SP, CI)
    if not use_honda_eps_controller(CP):
      raise ValueError("H020 controller needs an explicit config, exact PTM firmware and a linear 3840 map")
    self.dt = DT_CTRL
    self.calibration = H020
    pid = CP.lateralTuning.pid
    self.core = HondaEpsLateralCore(list(pid.kpBP), list(pid.kpV), list(pid.kiBP), list(pid.kiV), DT_CTRL,
                                  HondaEpsFirmwareFeedforward(DT_CTRL, H020))
    # res does not have the source branch's override fade; do not assume it does.
    self.core.override_fade_up_s = 0.0
    self.rack = HondaEpsRackMap(CP.wheelbase, H020_VGR_INVERSE, H020.rack)
    self.previous_desired = None

  def reset(self):
    super().reset()
    self.core.reset()
    self.previous_desired = None

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, calibrated_pose, curvature_limited):
    pid_log = log.ControlsState.LateralPIDState.new_message()
    inputs = (CS.steeringAngleDeg, CS.steeringRateDeg, CS.vEgo, params.roll, params.angleOffsetDeg, desired_curvature)
    if not all(math.isfinite(float(x)) for x in inputs):
      self.reset()
      pid_log.active = False
      return 0.0, 0.0, pid_log
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)
    desired = self.rack.angle_from_curvature(desired_curvature, CS.vEgo, params.roll)
    if active:
      # The source wrapper's desired-angle slew, initialized at the actual wheel on engagement.
      previous = self.previous_desired if self.previous_desired is not None else CS.steeringAngleDeg - params.angleOffsetDeg
      desired = float(np.clip(desired, previous - 300.0 * DT_CTRL, previous + 300.0 * DT_CTRL))
      self.previous_desired = desired
    angle = desired + params.angleOffsetDeg
    pid_log.steeringAngleDesiredDeg = float(angle)
    pid_log.angleError = float(angle - CS.steeringAngleDeg)
    if not active:
      self.reset()
      output = 0.0
      pid_log.active = False
    else:
      # Preserve res's driver override decision and all existing carcontroller/safety limits.
      output = float(self.core.update(desired, params.angleOffsetDeg, CS.steeringAngleDeg,
                                      CS.vEgo, params.roll, bool(CS.steeringPressed), steer_limited_by_safety))
      if not math.isfinite(output):
        self.reset()
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
