import math

from cereal import log
from opendbc.car.honda.carcontroller import get_eps_modified_steering_pressed
from opendbc.car.honda.values import CAR as HONDA
from opendbc.sunnypilot.car.honda.values_ext import HondaFlagsSP
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.pid import PIDController

# Phase scale for tanh transition: units are deg × (deg/frame).
# At angle=15°, filtered_delta=0.3°/frame → tanh(15×0.3/4.0)=tanh(1.125)=0.81 (strong turn-in signal).
# At noise level, filtered_delta≈0.02°/frame → tanh(15×0.02/4.0)=tanh(0.075)=0.07 (near-zero — no chatter).
CLARITY_PID_PHASE_SCALE = 4.0


def _clarity_pid_output_scale(desired_angle_deg: float, filtered_angle_delta_deg: float, v_ego: float) -> float:
  abs_angle = abs(desired_angle_deg)
  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  center_speed_weight = 0.65 + (0.35 * speed_weight)
  center_weight = min(max((16.0 - abs_angle) / 16.0, 0.0), 1.0)
  mid_turn_weight = min(max((abs_angle - 10.0) / 10.0, 0.0), 1.0)
  angle_weight = min(max((abs_angle - 16.0) / 12.0, 0.0), 1.0)
  # Continuous tanh phase weights replace the hard ±0.2 threshold.
  # Hard thresholds caused ~43 phase crossings/second in logged data (scale→output
  # correlation 0.435), producing the felt mid-turn oscillation/roughness.
  # tanh gives near-zero weight for noise-level deltas and near-unity for genuine
  # turn-in/unwind, with no discrete switching boundary to chatter across.
  phase_val = math.tanh(desired_angle_deg * filtered_angle_delta_deg / CLARITY_PID_PHASE_SCALE)
  turn_in_weight = max(phase_val, 0.0)
  unwind_weight = max(-phase_val, 0.0)

  is_left = desired_angle_deg > 0.0
  center_taper = 0.1764
  mid_turn_scale = 0.1200 if is_left else 0.0150
  mid_turn_turn_in_scale = -0.5500 if is_left else -0.0524
  mid_turn_unwind_scale = -0.0743 if is_left else -0.0842
  base_scale = 0.0722 if is_left else 0.0972
  turn_in_scale = -0.0799 if is_left else 0.0888
  unwind_scale = 0.1600 if is_left else 0.2000

  scale = 1.0 - (center_speed_weight * center_weight * center_taper)
  scale += speed_weight * mid_turn_weight * mid_turn_scale
  scale += speed_weight * angle_weight * base_scale
  scale += speed_weight * mid_turn_weight * mid_turn_turn_in_scale * turn_in_weight
  scale += speed_weight * angle_weight * turn_in_scale * turn_in_weight
  scale += speed_weight * mid_turn_weight * mid_turn_unwind_scale * unwind_weight
  scale -= speed_weight * angle_weight * unwind_scale * unwind_weight

  return max(scale, 0.6863)


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
      # kf=1.3768e-5: Phase 2 empirical calibration (-8.2% from 1.5e-5 baseline),
      #   measured on routes 48/49 using pure-feedforward frames.
      self.pid = PIDController(
        ([0.], [0.03]),
        ([0.], [0.01]),
        pos_limit=self.steer_max, neg_limit=-self.steer_max,
      )
      self.ff_factor = 1.3768e-5
    self.eps_modified_steering_pressed_filter_s = 0.0
    self.eps_modified_steering_pressed_prev = False
    self.prev_output_torque = 0.0
    self.prev_angle_steers_des_no_offset = 0.0
    self._dt = dt
    # Rate-limit the model-desired angle so 10Hz path model updates don't cause
    # instantaneous 10-20° jumps → P spikes → torque jerks at intersections.
    self._des_angle_rate_lim = 0.0
    # LPF on desired-angle delta before phase computation.
    # Raw one-frame delta was chattering across the ±0.2 phase threshold ~43×/s
    # (measured from PKL logs), driving scale oscillation and felt mid-turn roughness.
    # 2Hz cutoff: genuine turn-in evolves over ~10+ frames (well below 2Hz);
    # frame-to-frame noise is ~50Hz — fully rejected.
    # Mirrors jerk_filter in latcontrol_torque_starpilot (1.2Hz), adapted for angle space.
    self._des_angle_delta_filter = FirstOrderFilter(0.0, 1.0 / (2.0 * math.pi * 2.0), dt)

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
      self._des_angle_delta_filter.x = 0.0

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

      if self.is_clarity_eps_modified:
        # Lower threshold from 5 → 3 m/s: low_speed_scale already ramps output to zero
        # below 3 m/s (protecting against ±159° path-model instability at near-zero speed),
        # so the integrator can safely accumulate at 3–5 m/s — exactly the residential
        # intersection apex range where P alone cannot hold a steady-state turn angle.
        # Data (analyze_low_speed_turns.py): MAE at <5 m/s = 19.2° (frozen) vs 5.6° at
        # 5–8 m/s (integrator active) — 3× improvement just from allowing integration.
        freeze_integrator = steer_limited_by_safety or steering_pressed or CS.vEgo < 3
      else:
        freeze_integrator = steer_limited_by_safety or steering_pressed or CS.vEgo < 5

      output_torque = self.pid.update(error,
                                feedforward=ff,
                                speed=CS.vEgo,
                                freeze_integrator=freeze_integrator)

      if self.is_clarity_eps_modified:
        raw_delta = angle_steers_des_no_offset - self.prev_angle_steers_des_no_offset
        # Pre-filter delta before phase computation: eliminates the ~43 threshold
        # crossings/second that caused scale chatter and mid-turn roughness.
        # With a smooth filtered_delta, the tanh phase weights change gradually —
        # no separate output LPF needed.
        filtered_delta = self._des_angle_delta_filter.update(raw_delta)
        # Ramp output to zero below 3 m/s: path model desired angles are unreliable at
        # near-zero speed and produce absurd commands (observed ±159° desired angle)
        low_speed_scale = max(min((CS.vEgo - 1.5) / 3.5, 1.0), 0.0)
        output_torque *= low_speed_scale
        output_torque *= _clarity_pid_output_scale(angle_steers_des_no_offset, filtered_delta, CS.vEgo)
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
