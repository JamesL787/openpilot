"""Clarity angle mode (opendbc car/honda/clarity_angle_mode.py): the desired curvature becomes a desired wheel angle
through the same measured rack map LatControlHondaEps steers with (yaw-fitted ratio on the firmware's VGR position
table), so the target is in the coordinate the EPS publishes and compares against (CS.steeringAngleDeg = 0x14A).
Without a rack map it falls back to VehicleModel + the firmware VGR table (as LatControlHondaModifiedPID does).
The EPS runs the angle loop; CarController rate-limits and clamps the target inside the EPS's own limits."""
import math

from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, vgr_linear_to_physical
from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.latcontrol_angle import STEER_ANGLE_SATURATION_THRESHOLD, LatControlAngle
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import eps_firmware_calibration, get_rack_map


class LatControlHondaAngle(LatControlAngle):
  def __init__(self, CP, CI, dt):
    super().__init__(CP, CI, dt)
    self.rack_map = get_rack_map(CP, eps_firmware_calibration(CP))
    self.vgr_inverse = get_honda_vgr_inverse(CP.flags)

  def desired_angle_no_offset(self, desired_curvature: float, v_ego: float, roll: float, VM) -> float:
    if self.rack_map is not None:
      return self.rack_map.angle_from_curvature(desired_curvature, v_ego, roll)
    return vgr_linear_to_physical(math.degrees(VM.get_steer_from_curvature(-desired_curvature, v_ego, roll)), self.vgr_inverse)

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, curvature_limited, lat_delay, *args, **kwargs):
    angle_log = log.ControlsState.LateralAngleState.new_message()
    angle_log.active = bool(active)
    if active:
      angle_des = self.desired_angle_no_offset(desired_curvature, CS.vEgo, params.roll, VM) + params.angleOffsetDeg
    else:
      angle_des = float(CS.steeringAngleDeg)
    saturated = abs(angle_des - CS.steeringAngleDeg) > STEER_ANGLE_SATURATION_THRESHOLD
    angle_log.saturated = bool(self._check_saturation(saturated, CS, False, curvature_limited))
    angle_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    angle_log.steeringAngleDesiredDeg = float(angle_des)
    return 0, float(angle_des), angle_log
