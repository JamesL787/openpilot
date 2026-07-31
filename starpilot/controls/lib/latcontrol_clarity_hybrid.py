"""Clarity-only PID/NNFF hybrid lateral controller.

Ported from nrdr's sunnypilot/selfdrive/controls/lib/latcontrol_clarity_hybrid.py
(upstream/nrdr-development, 2026-07-29). The blend behaviour is reproduced exactly:
PID owns low speed and every lane change, NNFF owns high speed, with a narrow
speed blend and an asymmetric ramp that retreats to PID faster than it hands over.

Two deliberate differences from nrdr's version, both to fit this fork:

1. nrdr flips the shared CarParams lateralTuning union to torque in setup_interfaces(),
   then rebuilds the PID from get_non_essential_params() + their sunnypilot SP pass.
   We have no SP pass, and get_non_essential_params() alone returns the *stock* Honda
   tune (kpV [0.8]) rather than our EPS_MODIFIED banded tune (kpV [0.036, 0.048, 0.06]) --
   a 13x kp error. So we never mutate the shared CarParams: PID gets the real CP as-is,
   and only a private copy is flipped to torque for the NNFF half.

2. The NNLC half is this fork's LatControlNNFF. NNFF and NNLC are the same
   twilsonco-derived model and math; nrdr's stock 18-feature NNLC path and our NNFF
   compute the same setpoint/measurement error, the same high-lat-accel error blend
   and the same feedforward input vector, from the same 18-input model format.
"""
import copy

import numpy as np

from opendbc.car import structs
from opendbc.car.interfaces import CarInterfaceBase
from cereal import log
from openpilot.common.params import Params
from openpilot.common.constants import CV
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.starpilot.controls.lib.neural_network_feedforward import LatControlNNFF
from openpilot.starpilot.controls.lib.clarity_hybrid_blend import (
  NNLC_DEFAULT_ACTIVATION_SPEED_MPH,
  SETTINGS_REFRESH_FRAMES,
  clarity_nnlc_blend_target,
  step_blend,
)



class LatControlClarityHybrid(LatControl):
  """Run Clarity PID and NNFF every frame, then blend their outputs by speed."""

  def __init__(self, CP, CI, dt):
    super().__init__(CP, CI, dt)

    # PID receives the untouched CarParams, so it keeps the EPS_MODIFIED banded tune,
    # the kf speed band and the rack taper exactly as it has them today.
    self.pid_controller = LatControlPID(CP, CI, dt)

    # Only this private copy becomes a torque car, purely so NNFF has torque params.
    with structs.CarParams.from_bytes(CP.to_bytes()) as reader:
      CP_torque = reader.as_builder()
    CarInterfaceBase.configure_torque_tune(CP_torque.carFingerprint, CP_torque.lateralTuning)
    self.nnff_controller = LatControlNNFF(CP_torque, CI, dt)
    # nrdr's model sets friction_override, and their NNLC answers it with real
    # torque-space friction. Our legacy override line evaluates to exactly 0.0 for
    # Honda's linear mapping, so opt this instance into the nrdr behaviour.
    self.nnff_controller.torque_space_friction_override = True

    self.params = Params()
    self.nnlc_blend = 0.0
    self.enabled = True
    self.activation_speed_mps = NNLC_DEFAULT_ACTIVATION_SPEED_MPH * CV.MPH_TO_MS
    self._settings_frame = 0
    self._refresh_settings()

  def reset(self):
    super().reset()
    self.pid_controller.reset()
    self.nnff_controller.reset()

  def update_live_torque_params(self, latAccelFactor, latAccelOffset, friction):
    self.nnff_controller.update_live_torque_params(latAccelFactor, latAccelOffset, friction)

  # --- live settings -------------------------------------------------------
  def _read_int(self, key: str, default: float) -> float:
    try:
      value = self.params.get(key)
    except Exception:
      return default
    try:
      return float(default if value is None else value)
    except (TypeError, ValueError):
      return default

  def _refresh_settings(self) -> None:
    was_enabled = self.enabled
    try:
      self.enabled = self.params.get_bool("NrdrNnlcEnabled", default=True)
    except Exception:
      self.enabled = True
    if was_enabled and not self.enabled:
      # Never leave a hidden integral charge waiting for a later live re-enable.
      self.nnff_controller.pid.reset()

    activation_mph = float(np.clip(self._read_int("NrdrNnlcActivationSpeed", NNLC_DEFAULT_ACTIVATION_SPEED_MPH), 0.0, 100.0))
    self.activation_speed_mps = activation_mph * CV.MPH_TO_MS

    kp = float(np.clip(self._read_int("NrdrNnlcKpGain", 100.0) / 100.0, 0.0, 3.0))
    kf = float(np.clip(self._read_int("NrdrNnlcKfGain", 50.0) / 100.0, 0.0, 3.0))
    ki = float(np.clip(self._read_int("NrdrNnlcKiGain", 10.0) / 100.0, 0.0, 3.0))
    self.nnff_controller.pid._k_p = [[0.0], [kp]]
    self.nnff_controller.pid._k_i = [[0.0], [ki]]
    self.nnff_controller.pid.k_f = kf

  @staticmethod
  def _lane_change_state(model_data):
    if model_data is None:
      return log.LaneChangeState.off
    try:
      return model_data.meta.laneChangeState
    except AttributeError:
      return log.LaneChangeState.off

  def _update_blend(self, active: bool, target: float, lane_change_state) -> float:
    # preLaneChange is emitted before laneChangeStarting. Select the already-warm
    # PID immediately so the first lane-change curvature cannot receive NNFF torque.
    if lane_change_state != log.LaneChangeState.off:
      self.nnlc_blend = 0.0
      return self.nnlc_blend

    if not active:
      self.nnlc_blend = target
      return self.nnlc_blend

    self.nnlc_blend = step_blend(self.nnlc_blend, target, self.dt)
    return self.nnlc_blend

  # --- control -------------------------------------------------------------
  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature,
             curvature_limited, lat_delay, calibrated_pose, model_data, starpilot_toggles):
    if self._settings_frame % SETTINGS_REFRESH_FRAMES == 0:
      self._refresh_settings()
    self._settings_frame += 1

    # PID intentionally runs first: its fingerprint-scoped SR(|angle|) update is
    # applied to the shared VehicleModel before NNFF measures actual curvature.
    pid_output, pid_angle, pid_log = self.pid_controller.update(
      active, CS, VM, params, steer_limited_by_safety, desired_curvature,
      curvature_limited, lat_delay, calibrated_pose, model_data, starpilot_toggles,
    )

    # LatControlNNFF only engages its neural path when the nnff toggle is set; the
    # hybrid opts in on its own behalf without touching the user's global toggle.
    nnff_toggles = copy.copy(starpilot_toggles)
    nnff_toggles.nnff = True
    nnff_output, _, nnff_log = self.nnff_controller.update(
      active, CS, VM, params, steer_limited_by_safety, desired_curvature,
      curvature_limited, lat_delay, calibrated_pose, model_data, nnff_toggles,
    )

    lane_change_state = self._lane_change_state(model_data)
    target = clarity_nnlc_blend_target(CS.vEgo, lane_change_state, self.activation_speed_mps)
    if not self.enabled:
      target = 0.0
    blend = self._update_blend(active, target, lane_change_state)

    output = float((1.0 - blend) * float(pid_output) + blend * float(nnff_output))

    # Always publish the PID-shaped log. controlsd picks the controlsState union from
    # CP.lateralTuning.which(), and this design deliberately leaves that as 'pid';
    # handing back NNFF's LateralTorqueState makes that assignment raise
    # ("expected structValue.getSchema() == structType"), killing controlsd on the
    # first frame above the activation speed. p/i/d/f therefore describe the PID half,
    # which runs every frame regardless of blend, while output carries the blended
    # command actually sent to the car.
    out_log = pid_log
    out_log.output = output
    out_log.active = active
    out_log.saturated = bool(nnff_log.saturated if blend >= 0.5 else pid_log.saturated)

    # Do not carry a hidden integrator charge across a controller handoff. P and
    # feedforward still run every frame, while the inactive controller's I stays neutral.
    if blend <= 1e-3:
      self.nnff_controller.pid.i = 0.0
    elif blend >= 1.0 - 1e-3:
      self.pid_controller.pid.i = 0.0

    return output, float(pid_angle), out_log
