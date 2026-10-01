"""nrdr: lateral controller for the Honda Clarity and Civic Bosch with a modified EPS. controlsd selects it instead of
LatControlPID when NrdrLatEpsFirmwareFF is on (read once, when controlsd starts). Named LatControlClarityEps /
latcontrol_clarity_eps.py until it ran on more than the Clarity.

Upstream JamesL787/openpilot vfn-controller-shadow 8c3a3fd8 / fd815ef3, which selects it for the Clarity
unconditionally. Here it is behind the toggle, and the Civic Bosch C020 runs it with its own firmware calibration
(nrdr_eps_firmware_ff.CIVIC_BOSCH_C020), its own column load (CIVIC_EPS_LOAD) and its own fixed P/I trims
(CIVIC_P_SCALE / CIVIC_I_SCALE); everything else is upstream's. Upstream's HondaTorqueOutputLowPassFilter / HondaTorqueOutputLpfTau* keys do not exist on this
branch, so the output LPF runs on upstream's values (OUTPUT_LPF_TAU) and HondaLpfTau* (this branch's target
filter) is not used here.

The control law is nrdr_eps_firmware_ff.HondaEpsLateralCore: vfn's angle PID on the residual plus a
feedforward that inverts the EPS firmware's own P + D + KFF law, so the command is the one the firmware needs
to move the wheel along the desired path rather than one it has to be dragged into by error.

This shell does what LatControlPID does around its PID for a modified-EPS Honda, reusing the same helpers so
each setting behaves identically: curvature -> wheel angle through the firmware VGR table or the
road-measured ratio curve (NrdrLatUseFirmwareVgr), the angle-rate ceiling (NrdrLatAngleRateLimit), the shared
driver-override detector, and the speed-banded output low-pass. Settings read elsewhere (carcontroller, carstate, controlsd) apply unchanged.

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
  _get_param_bool,
  _get_param_float,
  rate_limit_desired_angle,
  solve_angle_from_ratio_curve,
)
from openpilot.selfdrive.controls.lib.nrdr_eps_firmware_ff import (
  CIVIC_BOSCH_C020,
  CIVIC_EPS_LOAD,
  CIVIC_I_SCALE,
  CIVIC_P_SCALE,
  HondaEpsFirmwareFeedforward,
  HondaEpsLateralCore,
)

SETTINGS_REFRESH_FRAMES = 300


def use_honda_eps_controller(CP, params=None) -> bool:
  if not (CP.carFingerprint in (HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH) and bool(CP.flags & HondaFlags.EPS_MODIFIED)
          and CP.lateralTuning.which() == "pid"):
    return False
  return _get_param_bool(params if params is not None else Params(), "NrdrLatEpsFirmwareFF")


# Lateral delay the model is told (liveDelay.lateralDelay's role in lat_action_t), scheduled on speed, per car.
# This controller's real execution delay depends on speed, so one SteerDelay / lagd value is early in the city and
# late on the highway. Each schedule is measured on its own car as the lag from the requested curvature to the
# curvature the car turns (VSA yaw, 0x94). A car with no entry keeps liveDelay.
# Clarity (vfn 8e839993): routes 354-36b; 3.5 m/s is the 2-5 m/s band. In vfn's closed-loop sim it cut the 5-9 m/s
# lateral error from 0.082 to 0.049 m/s^2 and the city turn-in from 80-120 ms early to within ~40 ms.
# Civic Bosch: not measured yet (needs drives on this controller), so it keeps liveDelay.
EPS_LAT_DELAY_SCHEDULE = {
  HONDA.HONDA_CLARITY: ([3.5, 7.0, 12.0, 20.0, 30.0], [0.12, 0.12, 0.15, 0.20, 0.30]),  # m/s, s
}


def eps_lateral_delay_schedule(CP, params=None):
  """The speed schedule to tell the model instead of liveDelay, or None to keep liveDelay."""
  if CP.carFingerprint not in EPS_LAT_DELAY_SCHEDULE or not use_honda_eps_controller(CP, params):
    return None
  return EPS_LAT_DELAY_SCHEDULE[CP.carFingerprint]


def eps_lateral_delay(schedule, v_ego: float, live_delay: float) -> float:
  if schedule is None:
    return live_delay
  return float(np.interp(v_ego, *schedule))


class LatControlHondaEps(LatControl):
  def __init__(self, CP, CI, dt):
    super().__init__(CP, CI, dt)
    pid = CP.lateralTuning.pid
    gains = ([float(x) for x in pid.kpBP], [float(x) for x in pid.kpV], [float(x) for x in pid.kiBP], [float(x) for x in pid.kiV])
    if CP.carFingerprint == HONDA.HONDA_CIVIC_BOSCH:
      self.core = HondaEpsLateralCore(*gains, dt, ff=HondaEpsFirmwareFeedforward(dt, cal=CIVIC_BOSCH_C020, load=CIVIC_EPS_LOAD),
                                        p_scale=CIVIC_P_SCALE, i_scale=CIVIC_I_SCALE)
    else:
      self.core = HondaEpsLateralCore(*gains, dt)
    self.sr_curve = NRDR_SR_CURVE_BY_FP.get(str(CP.carFingerprint))
    self.sr_curve_inverse = NRDR_SR_CURVE_INVERSE_BY_FP.get(str(CP.carFingerprint))
    self.vgr_inverse = get_honda_vgr_inverse(CP.flags)
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
    # upstream also reads HondaTorqueOutputLowPassFilter / HondaTorqueOutputLpfTau* here; not keys on this branch

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
