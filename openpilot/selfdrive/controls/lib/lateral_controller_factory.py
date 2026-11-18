"""The production lateral-controller selection, shared with independent replay."""

from opendbc.car import structs
from opendbc.car.honda.clarity_angle_mode import angle_mode as clarity_angle_mode
from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle
from openpilot.selfdrive.controls.lib.latcontrol_curvature import LatControlCurvature
from openpilot.selfdrive.controls.lib.latcontrol_honda_angle import LatControlHondaAngle
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import LatControlHondaEps, eps_firmware_calibration
from openpilot.selfdrive.controls.lib.latcontrol_honda_modified_pid import LatControlHondaModifiedPID, use_honda_modified_pid
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque


def create_lateral_controller(cp, ci, dt, *, mode, turn_assist=False):
  if cp.steerControlType == structs.CarParams.SteerControlType.angle:
    if cp.brand == "honda" and clarity_angle_mode(cp):
      return LatControlHondaAngle(cp, ci, dt)
    return LatControlAngle(cp, ci, dt)
  if cp.steerControlType == structs.CarParams.SteerControlType.curvature:
    return LatControlCurvature(cp, ci, dt)
  # a modified-EPS Honda with a matching EPS firmware calibration steers through its firmware inversion
  if (eps_calibration := eps_firmware_calibration(cp)) is not None:
    return LatControlHondaEps(cp, ci, dt, eps_calibration)
  # any other modified-EPS Honda runs the modified-EPS angle-space PID; every other PID car keeps 7.0's stock one
  if use_honda_modified_pid(cp):
    return LatControlHondaModifiedPID(cp, ci, dt)
  if cp.lateralTuning.which() == 'pid':
    return LatControlPID(cp, ci, dt)
  if cp.lateralTuning.which() == 'torque':
    return LatControlTorque(cp, ci, dt, controller_mode=mode, turn_assist=turn_assist)
  raise ValueError('No lateral controller for CarParams')
