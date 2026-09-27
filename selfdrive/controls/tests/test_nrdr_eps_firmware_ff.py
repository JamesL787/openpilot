import math
from types import SimpleNamespace

import pytest

from cereal import car, custom, log
import openpilot.selfdrive.controls.lib.latcontrol_pid as latcontrol_pid
import openpilot.selfdrive.controls.lib.nrdr_eps_firmware_ff as eps_ff
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID

# Ported from JamesL787/openpilot vfn-controller-shadow: the firmware-model tests are upstream's (fd815ef3), the
# shadow tests are 52618f42's with the final field names; the C020 tests are this branch's (STATUS 163).
C020 = eps_ff.CIVIC_BOSCH_C020


# --- firmware model and feedforward (upstream, Clarity calibration) ------------------------------

@pytest.mark.parametrize("output", [-1.0, -0.4, -0.05, 0.0, 0.02, 0.3, 0.9])
def test_command_map_round_trips(output):
  r5 = eps_ff.r5_from_output(output, 20.0)
  assert eps_ff.output_from_r5(r5) == pytest.approx(output, abs=2e-3)


def test_command_map_matches_the_measured_gain():
  # route 00000352: R5 = 7.7 * E4 and E4 = -3840 * output
  assert eps_ff.r5_from_output(0.1, 20.0) == pytest.approx(-0.1 * 3840 * 7.7, rel=0.03)


@pytest.mark.parametrize("load,rate", [(500, 0), (-1500, 0), (800, 40), (-800, -40), (300, -60), (-4000, 120),
                                       (100, -216), (-6000, 0), (0, 0)])
@pytest.mark.parametrize("guess", [0.0, 15000.0, -15000.0])
def test_inversion_reproduces_the_requested_load(load, rate, guess):
  r5 = eps_ff.r5_for_motion(load, rate, guess)
  assert eps_ff.firmware_output(r5, rate) == pytest.approx(load, abs=1e-6)


def test_turn_in_asks_more_than_a_hold_and_an_exit_less():
  # left turn (positive angle and output) at 60 deg, 8 m/s
  def out(rate):
    return eps_ff.output_from_r5(eps_ff.r5_for_motion(eps_ff.column_load(60.0, rate, 8.0, 0.0), rate))
  turn_in, hold, unwind = out(40.0), out(0.0), out(-40.0)
  assert turn_in > hold > unwind
  assert hold > 0.0


@pytest.mark.parametrize("v_kph,cap", [(40.0, eps_ff.R5_CAP), (130.0, 0.9 * 24000)])
def test_target_stays_clear_of_the_rail_and_the_speed_ceiling(v_kph, cap):
  ff = eps_ff.ClarityEpsFirmwareFeedforward(DT_CTRL)
  for k in range(200):
    ff.update(400.0 + k, v_kph / 3.6, 0.0)
  assert abs(ff.r5) <= cap + 1e-6


def test_desired_rate_tracks_a_ramp_and_resets():
  ff = eps_ff.ClarityEpsFirmwareFeedforward(DT_CTRL)
  for k in range(150):
    ff.update(50.0 * k * DT_CTRL, 10.0, 0.0)
  assert ff.rate == pytest.approx(50.0, abs=1.0)
  ff.reset()
  assert ff.rate == 0.0 and ff.output == 0.0 and ff.prev_angle is None


def test_feedforward_output_is_smoothed():
  raw = eps_ff.ClarityEpsFirmwareFeedforward(DT_CTRL, output_tau=0.0)
  smooth = eps_ff.ClarityEpsFirmwareFeedforward(DT_CTRL)
  for ff in (raw, smooth):
    ff.update(0.0, 10.0, 0.0)
    ff.update(30.0, 10.0, 0.0)   # a step in the target
  assert abs(smooth.output) < 0.2 * abs(raw.output)


# --- Civic Bosch C020 calibration ----------------------------------------------------------------

# E4 4096 is key 1773, past the 1663 clamp: on the Civic |output| above 0.938 all lands on the same R5
@pytest.mark.parametrize("output", [-0.93, -0.4, -0.05, 0.0, 0.02, 0.3, 0.93])
def test_c020_command_map_round_trips(output):
  r5 = eps_ff.r5_from_output(output, 20.0, C020)
  assert eps_ff.output_from_r5(r5, C020) == pytest.approx(output, abs=2e-3)


def test_c020_command_map_matches_the_telemetry():
  # route 00000284 telemetry: E4 = -4096 * output, the 1663 key clamp gives the largest R5 seen (28497)
  assert eps_ff.r5_from_output(-1.0, 20.0, C020) == pytest.approx(28497, abs=15)
  assert eps_ff.r5_from_output(-0.94, 20.0, C020) == eps_ff.r5_from_output(-1.0, 20.0, C020)
  # row 1: key 115 -> 1926, E4 = 115 * 4 * 32768 / 56756 = 265.6 -> key 115
  assert eps_ff.r5_from_output(-266 / 4096, 20.0, C020) == pytest.approx(1926, abs=20)


@pytest.mark.parametrize("r5", [0.0, 500.0, 1926.0, 3000.0, 8455.0, 15000.0, 22000.0, 28497.0, 31000.0])
def test_c020_kp_follows_the_p_row_through_the_command_map(r5):
  key = float(eps_ff.np.interp(min(r5, 30000.0), C020.r5_v, C020.r5_key_bp))
  assert eps_ff.firmware_kp(r5, C020) == pytest.approx(float(eps_ff.np.interp(key, eps_ff.KP_KEY_BP, eps_ff.KP_V)), abs=1e-9)
  assert eps_ff.firmware_kp(-r5, C020) == eps_ff.firmware_kp(r5, C020)


def test_clarity_kp_is_upstreams():
  for r5 in (0.0, 1000.0, 7000.0, 19000.0, 29000.0, 40000.0):
    assert eps_ff.firmware_kp(r5) == pytest.approx(float(eps_ff.np.interp(r5 / eps_ff.R5_PER_KEY, eps_ff.KP_KEY_BP, eps_ff.KP_V)))


@pytest.mark.parametrize("load,rate", [(500, 0), (-1500, 0), (800, 40), (-800, -40), (300, -60), (-4000, 120),
                                       (100, -216), (-6000, 0), (0, 0)])
@pytest.mark.parametrize("guess", [0.0, 15000.0, -15000.0])
def test_c020_inversion_reproduces_the_requested_load(load, rate, guess):
  r5 = eps_ff.r5_for_motion(load, rate, guess, C020)
  assert eps_ff.firmware_output(r5, rate, C020) == pytest.approx(load, abs=1e-6)


def test_c020_rate_damping_is_the_c020s():
  # same R5, same rate: the C020's larger R6 scale means more damping to cancel on a turn-in
  assert eps_ff.firmware_output(5000.0, 0.0, C020) < eps_ff.firmware_output(5000.0, 30.0, C020)
  d_c020 = eps_ff.firmware_output(5000.0, 30.0, C020) - eps_ff.firmware_output(5000.0, 0.0, C020)
  d_clarity = eps_ff.firmware_output(5000.0, 30.0) - eps_ff.firmware_output(5000.0, 0.0)
  assert d_c020 / d_clarity == pytest.approx(173.0 / 138.6, rel=0.05)


def test_c020_target_stays_clear_of_the_rail():
  ff = eps_ff.ClarityEpsFirmwareFeedforward(DT_CTRL, cal=C020)
  for k in range(200):
    ff.update(400.0 + k, 40.0 / 3.6, 0.0)
  assert abs(ff.r5) <= eps_ff.R5_CAP + 1e-6
  assert abs(ff.output) <= 1.0


# --- shadow in LatControlPID (upstream 52618f42) ------------------------------------------------

class _Params:
  def __init__(self, applied=False):
    self.applied = applied

  def get(self, key, *args, **kwargs):
    return None

  def get_bool(self, key, *args, **kwargs):
    if key == "NrdrLatEpsFirmwareFF" and self.applied:
      return True
    raise KeyError(key)   # -> the controller's own default


def _car(monkeypatch, candidate=HONDA.HONDA_CLARITY, modified=True, applied=False):
  monkeypatch.setattr(latcontrol_pid, "Params", lambda: _Params(applied))
  CarInterface = interfaces[candidate]
  CP = CarInterface.get_non_essential_params(candidate)
  if modified:
    CP.flags |= int(HondaFlags.EPS_MODIFIED)
  CP.dashcamOnly = True
  CI = CarInterface(CP, custom.StarPilotCarParams.new_message())
  lac = LatControlPID(CP.as_reader(), CI, DT_CTRL)
  params = log.LiveParametersData.new_message()
  params.steerRatio = CP.steerRatio
  params.stiffnessFactor = 1.0
  params.angleOffsetDeg = 0.0
  return lac, VehicleModel(CP), params


def _drive(lac, VM, params, frames=400, pressed=(), weights=None):
  CS = car.CarState.new_message()
  CS.vEgo = 9.0
  outputs = []
  for k in range(frames):
    active = k >= 20
    CS.steeringPressed = k in pressed
    curvature = 0.02 * math.sin(k * 0.02)
    CS.steeringAngleDeg = 10.0 * math.sin(k * 0.02 - 0.3)
    out, _, _ = lac.update(active, CS, VM, params, False, curvature, False, 0.2, None, None, SimpleNamespace())
    outputs.append(out)
    if weights is not None:
      weights.append(lac.eps_ff_weight)
  return outputs


SHADOW_CARS = [(HONDA.HONDA_CLARITY, eps_ff.CLARITY_A020), (HONDA.HONDA_CIVIC_BOSCH, C020)]


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_shadow_is_logged(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate)
  assert lac.eps_shadow_ff is not None and lac.eps_shadow_ff.cal is cal
  _drive(lac, VM, params)
  state = lac.starpilot_lateral_state
  assert state.epsFfActive and state.epsFfWeight == 0.0
  assert state.epsFfR5 != 0.0 and math.isfinite(state.epsFfFeedforward)
  msg = log.Event.new_message(starpilotLateralState=state)   # what controlsd publishes
  assert msg.starpilotLateralState.epsFfR5 == pytest.approx(state.epsFfR5)


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH])
def test_no_shadow_on_a_stock_eps(monkeypatch, candidate):
  lac, _, _ = _car(monkeypatch, candidate, modified=False)
  assert lac.eps_shadow_ff is None and not hasattr(lac, "starpilot_lateral_state")


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_shadow_never_changes_the_steering_command(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate)
  twin, _, _ = _car(monkeypatch, candidate)
  twin.eps_shadow_ff = None
  assert _drive(lac, VM, params) == _drive(twin, VM, params)


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_a_shadow_failure_cannot_reach_the_command(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate)
  twin, _, _ = _car(monkeypatch, candidate)
  twin.eps_shadow_ff = None

  def boom(*args, **kwargs):
    raise ValueError("shadow failure")
  monkeypatch.setattr(lac.eps_shadow_ff, "update", boom)
  assert _drive(lac, VM, params) == _drive(twin, VM, params)
  assert not lac.starpilot_lateral_state.epsFfActive


# --- applied behind NrdrLatEpsFirmwareFF (this branch, STATUS 165; gate is upstream's ClarityEpsLateralCore) ----

def test_join_gate_fades_in_and_drops_on_a_press():
  ramp, w = eps_ff.eps_ff_weight(0.0, 12.0, 9.0, False, DT_CTRL)
  assert ramp == w == 0.0                       # does not join outside 10 deg of error
  for _ in range(25):
    ramp, w = eps_ff.eps_ff_weight(ramp, 3.0, 9.0, False, DT_CTRL)
  assert w == pytest.approx(0.5)                # 0.5 s fade
  ramp, w = eps_ff.eps_ff_weight(ramp, 12.0, 9.0, False, DT_CTRL)
  assert w > 0.5                                # once joined, a large error does not drop it
  assert eps_ff.eps_ff_weight(ramp, 3.0, 9.0, True, DT_CTRL) == (0.0, 0.0)
  assert eps_ff.eps_ff_weight(ramp, 3.0, 1.9, False, DT_CTRL) == (0.0, 0.0)
  assert eps_ff.eps_ff_weight(1.0, 3.0, 3.0, False, DT_CTRL)[1] == pytest.approx(0.5)   # 2-4 m/s speed fade


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_applied_feedforward_replaces_the_kf_feedforward(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate, applied=True)
  off, _, _ = _car(monkeypatch, candidate)
  weights = []
  on_out = _drive(lac, VM, params, weights=weights)
  off_out = _drive(off, VM, params)
  assert lac.eps_ff_enabled and not off.eps_ff_enabled
  assert on_out[:20] == off_out[:20]            # inactive: nothing applied
  assert weights[-1] == 1.0 and lac.starpilot_lateral_state.epsFfWeight == 1.0
  assert on_out != off_out
  assert all(math.isfinite(o) and abs(o) <= lac.steer_max for o in on_out)


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_a_press_hands_back_to_the_kf_feedforward(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate, applied=True)
  weights = []
  _drive(lac, VM, params, pressed=range(200, 260), weights=weights)
  assert weights[199] > 0.0
  assert weights[259] == 0.0                    # once the override detector counts the press
  assert weights[-1] == 1.0                     # rejoins and fades back in after the press


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_an_applied_failure_falls_back_to_the_toggle_off_command(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate, applied=True)
  off, _, _ = _car(monkeypatch, candidate)

  def boom(*args, **kwargs):
    raise ValueError("feedforward failure")
  monkeypatch.setattr(lac.eps_shadow_ff, "update", boom)
  assert _drive(lac, VM, params) == _drive(off, VM, params)
  assert lac.eps_ff_weight == 0.0
