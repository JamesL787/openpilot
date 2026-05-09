import math

from cereal import log
from opendbc.car.honda.carcontroller import get_eps_modified_steering_pressed
from opendbc.car.honda.values import CAR as HONDA
from opendbc.sunnypilot.car.honda.values_ext import HondaFlagsSP
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.common.pid import PIDController


def _clarity_pid_output_scale(desired_angle_deg: float, desired_angle_delta_deg: float, v_ego: float) -> float:
  abs_angle = abs(desired_angle_deg)
  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  center_speed_weight = 0.65 + (0.35 * speed_weight)
  center_weight = min(max((16.0 - abs_angle) / 16.0, 0.0), 1.0)
  mid_turn_weight = min(max((abs_angle - 10.0) / 10.0, 0.0), 1.0)
  angle_weight = min(max((abs_angle - 16.0) / 12.0, 0.0), 1.0)
  phase = desired_angle_deg * desired_angle_delta_deg
  is_left = desired_angle_deg > 0.0
  center_taper = 0.1809
  mid_turn_scale = 0.0707 if is_left else 0.0238
  mid_turn_turn_in_scale = -0.3000 if is_left else -0.0728
  mid_turn_unwind_scale = 0.0008 if is_left else -0.0680
  base_scale = -0.0282 if is_left else 0.0739
  turn_in_scale = -0.0500 if is_left else 0.1143
  unwind_scale = 0.1003 if is_left else 0.2119

  scale = 1.0 - (center_speed_weight * center_weight * center_taper)
  scale += speed_weight * mid_turn_weight * mid_turn_scale
  scale += speed_weight * angle_weight * base_scale
  if phase > 0.2:
    scale += speed_weight * mid_turn_weight * mid_turn_turn_in_scale
    scale += speed_weight * angle_weight * turn_in_scale
  elif phase < -0.2:
    scale += speed_weight * mid_turn_weight * mid_turn_unwind_scale
    scale -= speed_weight * angle_weight * unwind_scale

  return max(scale, 0.5759)


class LatControlPID(LatControl):
  def __init__(self, CP, CP_SP, CI, dt):
    super().__init__(CP, CP_SP, CI, dt)
    self.pid = PIDController((CP.lateralTuning.pid.kpBP, CP.lateralTuning.pid.kpV),
                             (CP.lateralTuning.pid.kiBP, CP.lateralTuning.pid.kiV),
                             pos_limit=self.steer_max, neg_limit=-self.steer_max)
    self.ff_factor = CP.lateralTuning.pid.kf
    self.CI = CI
    self.get_steer_feedforward = CI.get_steer_feedforward_function()
    self.is_clarity_eps_modified = (
      CP.carFingerprint == HONDA.HONDA_CLARITY and
      bool(getattr(CP_SP, "flags", 0) & HondaFlagsSP.EPS_MODIFIED.value)
    )
    if self.is_clarity_eps_modified:
      # All EPS Modified gain values live here, gated on the hardware flag.
      # kP=0.03, kI=0.01: proven clean-data baseline (routes 48/49: 10.8% integrator
      #   wind-up, 86% clean frames, zero driver override needed through turns).
      #   kI=0.05 (prior value in interface.py) caused 28.9% wind-up and constant
      #   turn overshoot on city routes.
      # kf=1.2004e-5: Phase 3 DE optimisation (-12.8% from 1.377e-5 Phase 2 value),
      #   fit on routes 48+49+0c (256K frames, city+highway mixed).
      self.pid = PIDController(
        ([0.], [0.03]),
        ([0.], [0.01]),
        pos_limit=self.steer_max, neg_limit=-self.steer_max,
      )
      self.ff_factor = 1.2004e-5
    self.eps_modified_steering_pressed_filter_s = 0.0
    self.eps_modified_steering_pressed_prev = False
    self.prev_output_torque = 0.0
    self.prev_angle_steers_des_no_offset = 0.0
    self._dt = dt
    # Rate-limit the model-desired angle so 10Hz path model updates don't cause
    # instantaneous 10-20° jumps → P spikes → torque jerks at intersections.
    self._des_angle_rate_lim = 0.0
    # LPF on output scale to prevent phase-boundary flicker (alpha=0.3 → ~0.03/frame max,
    # ~6 frames / 60 ms to fully transition across a phase boundary).
    self._output_scale_lpf = 1.0

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, calibrated_pose, curvature_limited, lat_delay):
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)

    angle_steers_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))

    if self.is_clarity_eps_modified:
      # Smooth sudden path-model (10Hz) desired-angle jumps. Without this, a 15° curvature
      # update in one 10ms frame spikes P to ±0.75 and creates the felt torque jerk at
      # intersections. 200°/s lets the car execute a full 90° turn in 0.45s, which is faster
      # than any physical intersection geometry demands.
      max_delta = 200.0 * self._dt
      angle_steers_des_no_offset = max(
        min(angle_steers_des_no_offset, self._des_angle_rate_lim + max_delta),
        self._des_angle_rate_lim - max_delta
      )

    angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    error = angle_steers_des - CS.steeringAngleDeg

    pid_log.steeringAngleDesiredDeg = angle_steers_des
    pid_log.angleError = error
    if not active:
      output_torque = 0.0
      pid_log.active = False
      self.eps_modified_steering_pressed_filter_s = 0.0
      self.eps_modified_steering_pressed_prev = False
      self.prev_output_torque = 0.0
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self._des_angle_rate_lim = angle_steers_des_no_offset
      self._output_scale_lpf = 1.0

    else:
      # offset does not contribute to resistive torque
      ff = self.ff_factor * self.get_steer_feedforward(angle_steers_des_no_offset, CS.vEgo)

      steering_pressed = CS.steeringPressed
      if self.is_clarity_eps_modified:
        self.eps_modified_steering_pressed_filter_s, steering_pressed = get_eps_modified_steering_pressed(
          bool(CS.steeringPressed),
          float(getattr(CS, "steeringTorque", 0.0)),
          float(self.prev_output_torque),
          self.eps_modified_steering_pressed_filter_s,
          self.eps_modified_steering_pressed_prev,
        )
        self.eps_modified_steering_pressed_prev = steering_pressed

      freeze_integrator = steer_limited_by_safety or steering_pressed or CS.vEgo < 5

      output_torque = self.pid.update(error,
                                feedforward=ff,
                                speed=CS.vEgo,
                                freeze_integrator=freeze_integrator)

      if self.is_clarity_eps_modified:
        desired_angle_delta = angle_steers_des_no_offset - self.prev_angle_steers_des_no_offset
        # Ramp output to zero below 3 m/s: path model desired angles are unreliable at
        # near-zero speed and produce absurd commands (observed ±159° desired angle)
        low_speed_scale = max(min((CS.vEgo - 1.5) / 3.5, 1.0), 0.0)
        output_torque *= low_speed_scale
        raw_scale = _clarity_pid_output_scale(angle_steers_des_no_offset, desired_angle_delta, CS.vEgo)
        self._output_scale_lpf += 0.3 * (raw_scale - self._output_scale_lpf)
        output_torque *= self._output_scale_lpf
        output_torque = float(max(min(output_torque, self.steer_max), -self.steer_max))

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(output_torque)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))
      self.prev_output_torque = float(output_torque)
      self.prev_angle_steers_des_no_offset = angle_steers_des_no_offset
      self._des_angle_rate_lim = angle_steers_des_no_offset

    return output_torque, angle_steers_des, pid_log
