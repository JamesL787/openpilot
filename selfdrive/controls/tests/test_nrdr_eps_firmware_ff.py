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
  for k in range(100):
    ff.update(50.0 * k * DT_CTRL, 10.0, 0.0)
  assert ff.rate == pytest.approx(50.0, abs=1.0)
  ff.reset()
  assert ff.rate == 0.0 and ff.output == 0.0 and ff.prev_angle is None


class _Params:
  def get(self, key, *args, **kwargs):
    return None

  def get_bool(self, key, *args, **kwargs):
    raise KeyError(key)   # -> the controller's own default


def _clarity(monkeypatch):
  monkeypatch.setattr(latcontrol_pid, "Params", lambda: _Params())
  CarInterface = interfaces[HONDA.HONDA_CLARITY]
  CP = CarInterface.get_non_essential_params(HONDA.HONDA_CLARITY)
  CP.flags |= int(HondaFlags.EPS_MODIFIED)
  CP.dashcamOnly = True
  CI = CarInterface(CP, custom.StarPilotCarParams.new_message())
  lac = LatControlPID(CP.as_reader(), CI, DT_CTRL)
  params = log.LiveParametersData.new_message()
  params.steerRatio = CP.steerRatio
  params.stiffnessFactor = 1.0
  params.angleOffsetDeg = 0.0
  return lac, VehicleModel(CP), params


def _drive(lac, VM, params, frames=400):
  CS = car.CarState.new_message()
  CS.vEgo = 9.0
  outputs = []
  for k in range(frames):
    active = k >= 20
    curvature = 0.02 * math.sin(k * 0.02)
    CS.steeringAngleDeg = 10.0 * math.sin(k * 0.02 - 0.3)
    out, _, _ = lac.update(active, CS, VM, params, False, curvature, False, 0.2, None, None, SimpleNamespace())
    outputs.append(out)
  return outputs


def test_shadow_is_logged_for_the_clarity(monkeypatch):
  lac, VM, params = _clarity(monkeypatch)
  assert lac.eps_shadow_ff is not None
  _drive(lac, VM, params)
  state = lac.starpilot_lateral_state
  assert state.epsShadowActive
  assert state.epsShadowR5 != 0.0 and math.isfinite(state.epsShadowFeedforward)
  msg = log.Event.new_message(starpilotLateralState=state)   # what controlsd publishes
  assert msg.starpilotLateralState.epsShadowR5 == pytest.approx(state.epsShadowR5)


def test_shadow_never_changes_the_steering_command(monkeypatch):
  lac, VM, params = _clarity(monkeypatch)
  twin, _, _ = _clarity(monkeypatch)
  twin.eps_shadow_ff = None
  assert _drive(lac, VM, params) == _drive(twin, VM, params)


def test_a_shadow_failure_cannot_reach_the_command(monkeypatch):
  lac, VM, params = _clarity(monkeypatch)
  twin, _, _ = _clarity(monkeypatch)
  twin.eps_shadow_ff = None

  def boom(*args, **kwargs):
    raise ValueError("shadow failure")
  monkeypatch.setattr(lac.eps_shadow_ff, "update", boom)
  assert _drive(lac, VM, params) == _drive(twin, VM, params)
  assert not lac.starpilot_lateral_state.epsShadowActive
