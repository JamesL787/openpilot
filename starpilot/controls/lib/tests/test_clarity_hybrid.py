"""Tests for the Clarity PID/NNFF hybrid port.

These deliberately avoid importing LatControl: on hosts without the device-built
native extensions (macOS) that import chain cannot load, which is why the pure
blend policy lives in clarity_hybrid_blend.py. Controller-level behaviour is
exercised on-device.
"""
import json
import os

import numpy as np
import pytest

from cereal import log
from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.interfaces import CarInterfaceBase
from openpilot.common.constants import CV
from openpilot.starpilot.controls.lib.clarity_hybrid_blend import (
  BLEND_TO_NNLC_SECONDS,
  BLEND_TO_PID_SECONDS,
  clarity_nnlc_blend_target,
  step_blend,
)

MPH = CV.MPH_TO_MS
ACTIVATION = 30.0 * MPH
# Resolve from this file, not BASEDIR: under pytest BASEDIR can point at the
# stale .host_runtime mirror rather than the tree under test.
CLARITY_MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
  os.path.dirname(os.path.abspath(__file__))))), "assets", "nnff_models", "HONDA_CLARITY.json")


def _clarity_cp():
  fw = [structs.CarParams.CarFw(ecu="eps", fwVersion=b'39990-TRW,A020\x00\x00', address=0x18DA30F1, subAddress=0)]
  from types import SimpleNamespace
  toggles = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)
  return CarInterface.get_params("HONDA_CLARITY", gen_empty_fingerprint(), fw, False, False, False, toggles)


class TestClarityHybridBlend:
  def test_pid_owns_low_speed_and_nnff_owns_high_speed(self):
    # nrdr's road-tested 27-33 mph handoff at the 30 mph default
    assert clarity_nnlc_blend_target(0.0, log.LaneChangeState.off, ACTIVATION) == 0.0
    assert clarity_nnlc_blend_target(27.0 * MPH, log.LaneChangeState.off, ACTIVATION) == 0.0
    assert clarity_nnlc_blend_target(30.0 * MPH, log.LaneChangeState.off, ACTIVATION) == pytest.approx(0.5)
    assert clarity_nnlc_blend_target(33.0 * MPH, log.LaneChangeState.off, ACTIVATION) == 1.0
    assert clarity_nnlc_blend_target(70.0 * MPH, log.LaneChangeState.off, ACTIVATION) == 1.0

  def test_blend_is_monotonic_across_the_handoff(self):
    speeds = np.arange(0.0, 60.0, 0.5) * MPH
    vals = [clarity_nnlc_blend_target(v, log.LaneChangeState.off, ACTIVATION) for v in speeds]
    assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:], strict=False))

  @pytest.mark.parametrize("state", [log.LaneChangeState.preLaneChange,
                                     log.LaneChangeState.laneChangeStarting,
                                     log.LaneChangeState.laneChangeFinishing])
  def test_any_lane_change_forces_pid_even_at_speed(self, state):
    # preLaneChange precedes laneChangeStarting, so the first lane-change
    # curvature must never receive NNFF torque.
    assert clarity_nnlc_blend_target(70.0 * MPH, state, ACTIVATION) == 0.0

  def test_activation_speed_is_honoured(self):
    act = 45.0 * MPH
    assert clarity_nnlc_blend_target(41.0 * MPH, log.LaneChangeState.off, act) == 0.0
    assert clarity_nnlc_blend_target(48.0 * MPH, log.LaneChangeState.off, act) == 1.0

  def test_retreat_to_pid_is_faster_than_handoff_to_nnff(self):
    dt = 0.01

    def ramp(start, target):
      b, n = start, 0
      while abs(b - target) > 1e-9 and n < 10000:
        b = step_blend(b, target, dt)
        n += 1
      return n * dt

    assert ramp(0.0, 1.0) == pytest.approx(BLEND_TO_NNLC_SECONDS, abs=dt)
    assert ramp(1.0, 0.0) == pytest.approx(BLEND_TO_PID_SECONDS, abs=dt)
    assert BLEND_TO_PID_SECONDS < BLEND_TO_NNLC_SECONDS


class TestClarityHybridCarParams:
  def test_gate_off_leaves_clarity_on_pid(self):
    """The whole point of the gate: with it off the Clarity is a PID car."""
    CP = _clarity_cp()
    assert CP.lateralTuning.which() == "pid"
    assert len(CP.lateralTuning.pid.kpV) > 0
    assert CP.lateralTuning.pid.kf > 0.0

  def test_torque_copy_does_not_mutate_shared_carparams(self):
    """The hybrid flips only a private copy; the shared CP keeps the PID tune.

    nrdr flips the shared union instead and rebuilds PID from
    get_non_essential_params(), which on this fork returns the stock Honda tune.
    """
    CP = _clarity_cp()
    kpV_before = list(CP.lateralTuning.pid.kpV)
    kf_before = CP.lateralTuning.pid.kf
    with structs.CarParams.from_bytes(CP.to_bytes()) as reader:
      CP_torque = reader.as_builder()
    CarInterfaceBase.configure_torque_tune(CP_torque.carFingerprint, CP_torque.lateralTuning)

    assert CP_torque.lateralTuning.which() == "torque"
    assert CP_torque.lateralTuning.torque.latAccelFactor > 0.0
    # shared CarParams untouched -- compare against the snapshot, so this holds
    # whatever tune the environment supplies
    assert CP.lateralTuning.which() == "pid"
    assert list(CP.lateralTuning.pid.kpV) == pytest.approx(kpV_before)
    assert CP.lateralTuning.pid.kf == pytest.approx(kf_before)

  def test_reconstructing_params_would_lose_our_tune(self):
    """Guards the trap: get_non_essential_params() has no car_fw, so EPS_MODIFIED
    is unset and the stock tune comes back. Documents why we copy instead."""
    stock = CarInterface.get_non_essential_params("HONDA_CLARITY")
    real = _clarity_cp()
    assert stock.lateralTuning.which() == "pid"
    # no car_fw -> EPS_MODIFIED unset -> a different (stock) tune comes back
    assert not (stock.flags & 2)
    assert list(stock.lateralTuning.pid.kpV) != list(real.lateralTuning.pid.kpV) \
        or stock.lateralTuning.pid.kf != real.lateralTuning.pid.kf


class TestClarityNNFFModel:
  def test_nrdr_model_is_present_and_well_formed(self):
    assert os.path.exists(CLARITY_MODEL)
    with open(CLARITY_MODEL) as f:
      m = json.load(f)
    assert m["input_size"] == 18 and m["output_size"] == 1
    assert len(m["layers"]) == 4
    # every activation must be one FluxModel implements
    for layer in m["layers"]:
      assert layer["activation"].replace("σ", "sigmoid") in ("sigmoid", "identity")

  def test_model_is_nrdrs_trained_one_not_the_stale_community_model(self):
    with open(CLARITY_MODEL) as f:
      m = json.load(f)
    assert m["model_test_loss"] < 5e-4, "expected nrdr's 2026-07-28 model (loss 3.9e-4)"
    assert "training_metadata" in m


class TestClarityHybridLogType:
  """controlsd assigns cs.lateralControlState.<union> from CP.lateralTuning.which().

  This design keeps that at 'pid', so the hybrid must always hand back a
  LateralPIDState. Returning NNFF's LateralTorqueState makes the assignment raise
  and takes controlsd down on the first frame above the activation speed.
  """

  def test_torque_state_cannot_be_published_as_pid_state(self):
    from cereal import log
    cs = log.ControlsState.new_message()
    torque_log = log.ControlsState.LateralTorqueState.new_message()
    with pytest.raises(Exception):
      cs.lateralControlState.pidState = torque_log

  def test_pid_state_publishes_cleanly(self):
    from cereal import log
    cs = log.ControlsState.new_message()
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.output = 0.42
    cs.lateralControlState.pidState = pid_log
    assert cs.lateralControlState.which() == "pidState"

  def test_hybrid_returns_pid_shaped_log_at_every_blend(self):
    """Guards the actual bug: the controller must not hand back nnff_log.

    Read as text rather than imported -- the LatControl chain needs the
    device-built native extensions.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "latcontrol_clarity_hybrid.py")
    with open(path) as f:
      src = f.read()
    assert "out_log = pid_log" in src
    assert "out_log = nnff_log" not in src
