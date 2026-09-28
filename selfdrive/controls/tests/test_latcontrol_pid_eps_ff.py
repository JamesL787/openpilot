"""NrdrLatPidFirmwareFF (STATUS 175): the EPS firmware-inversion feedforward in the NRDR PID, in turns only."""
from types import SimpleNamespace

import pytest

from cereal import car, custom, log
import openpilot.selfdrive.controls.lib.latcontrol_pid as latcontrol_pid
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID, nrdr_pid_eps_ff_weight


class _Params:
  def __init__(self, values):
    self.values = values

  def get(self, key, *args, **kwargs):
    return self.values.get(key)

  def get_bool(self, key, *args, **kwargs):
    return str(self.values[key]) in ("1", "True", "true")   # KeyError -> the controller's default


def _run(monkeypatch, values, peak_curv, v_ego=8.0, frames=1000):
  """Straight to frame 320, a turn-in over 1 s, then held. The wheel follows the shaped target one frame late."""
  monkeypatch.setattr(latcontrol_pid, "civic_bosch_modified_lateral_testing_ground_active", lambda *a, **kw: False)
  monkeypatch.setattr(latcontrol_pid, "Params", lambda: _Params(values))
  CarInterface = interfaces[HONDA.HONDA_CIVIC_BOSCH]
  CP = CarInterface.get_non_essential_params(HONDA.HONDA_CIVIC_BOSCH)
  CP.flags |= int(HondaFlags.EPS_MODIFIED)
  CP.dashcamOnly = True
  CI = CarInterface(CP, custom.StarPilotCarParams.new_message())
  lac = LatControlPID(CP.as_reader(), CI, DT_CTRL)
  lac.params = _Params(values)
  VM = VehicleModel(CP)
  params = log.LiveParametersData.new_message()
  params.steerRatio = CP.steerRatio
  params.stiffnessFactor = 1.0
  params.angleOffsetDeg = 0.0
  CS = car.CarState.new_message()
  CS.vEgo = v_ego
  CS.steeringAngleDeg = 0.0
  outs, weights, shaped = [], [], []
  for k in range(frames):
    curv = peak_curv * min(max(k - 320, 0) / 100.0, 1.0)
    out, des, _ = lac.update(True, CS, VM, params, False, curv, False, 0.0, None, None, SimpleNamespace())
    CS.steeringAngleDeg = des
    outs.append(out)
    weights.append(lac.starpilot_lateral_state.epsFfWeight)
    shaped.append(des)
  return lac, outs, weights, shaped


def _ramp_to_full(error, des, v, pressed=False, frames=60):
  ramp = w = 0.0
  for _ in range(frames):
    ramp, w = nrdr_pid_eps_ff_weight(ramp, error, des, v, pressed, DT_CTRL)
  return ramp, w


def test_weight_is_zero_near_centre_and_full_in_turns():
  assert _ramp_to_full(0.0, 5.0, 10.0)[1] == 0.0
  assert _ramp_to_full(0.0, -9.9, 10.0)[1] == 0.0
  assert _ramp_to_full(0.0, 20.0, 10.0)[1] == pytest.approx(0.5)
  assert _ramp_to_full(0.0, -45.0, 10.0)[1] == pytest.approx(1.0)
  assert _ramp_to_full(0.0, 45.0, 3.0)[1] == pytest.approx(0.5)   # half weight halfway up the 2-4 m/s fade


def test_weight_joins_on_small_error_and_drops_on_press_or_low_speed():
  assert _ramp_to_full(15.0, 60.0, 10.0) == (0.0, 0.0)   # never joins while the error is large
  ramp, _ = _ramp_to_full(0.0, 60.0, 10.0, frames=25)
  assert 0.0 < ramp < 1.0   # fades in over 0.5 s
  ramp, w = nrdr_pid_eps_ff_weight(ramp, 15.0, 60.0, 10.0, False, DT_CTRL)
  assert w > 0.0   # once joined, a large error keeps it
  assert nrdr_pid_eps_ff_weight(1.0, 0.0, 60.0, 10.0, True, DT_CTRL) == (0.0, 0.0)
  assert nrdr_pid_eps_ff_weight(1.0, 0.0, 60.0, 1.5, False, DT_CTRL) == (0.0, 0.0)


def test_default_off_leaves_the_command_unchanged(monkeypatch):
  _, base, w_base, _ = _run(monkeypatch, {}, 0.03)
  _, off, w_off, _ = _run(monkeypatch, {"NrdrLatPidFirmwareFF": "0"}, 0.03)
  assert off == pytest.approx(base)
  assert max(w_base) == 0.0 and max(w_off) == 0.0


def test_on_adds_turn_torque_only_in_turns(monkeypatch):
  lac, off, _, shaped = _run(monkeypatch, {}, 0.03)
  _, on, w, _ = _run(monkeypatch, {"NrdrLatPidFirmwareFF": "1"}, 0.03)
  assert abs(shaped[-1]) > 40.0
  assert on[:300] == pytest.approx(off[:300])   # params not read yet: frame 300 is the first refresh
  assert w[-1] == pytest.approx(1.0)
  assert on[-1] * shaped[-1] > 0 and abs(on[-1]) > abs(off[-1]) + 0.05   # the firmware FF pushes into the turn

  _, off_c, _, shaped_c = _run(monkeypatch, {}, 0.002)
  _, on_c, w_c, _ = _run(monkeypatch, {"NrdrLatPidFirmwareFF": "1"}, 0.002)
  assert abs(shaped_c[-1]) < 10.0
  assert max(w_c) == 0.0   # near centre the gate keeps it out entirely
  assert on_c == pytest.approx(off_c)


# --- isolation from James's controller (owner: a fix for one must not move the other) -----------------------

def test_james_controller_constants_do_not_move_the_pid_gate(monkeypatch):
  from openpilot.selfdrive.controls.lib import nrdr_eps_firmware_ff as eps_ff
  before = [_ramp_to_full(0.0, des, v) for des in (5.0, 20.0, 60.0) for v in (1.5, 3.0, 6.0)]
  monkeypatch.setattr(eps_ff, "FF_SPEED_BP", [9.0, 18.0], raising=False)
  monkeypatch.setattr(eps_ff, "FF_JOIN_ERROR_DEG", 0.1, raising=False)
  monkeypatch.setattr(eps_ff, "FF_FADE_IN_S", 9.0, raising=False)
  after = [_ramp_to_full(0.0, des, v) for des in (5.0, 20.0, 60.0) for v in (1.5, 3.0, 6.0)]
  assert after == before


def test_the_pid_toggle_does_not_select_or_change_james_controller(monkeypatch):
  import math
  from openpilot.selfdrive.controls.lib import latcontrol_clarity_eps as clarity_eps

  class _V(_Params):
    def get_bool(self, key, *args, **kwargs):
      return self.values.get(key) == "1"

  CP = interfaces[HONDA.HONDA_CIVIC_BOSCH].get_non_essential_params(HONDA.HONDA_CIVIC_BOSCH)
  CP.flags |= int(HondaFlags.EPS_MODIFIED)
  assert not clarity_eps.use_clarity_eps_controller(CP, _V({"NrdrLatPidFirmwareFF": "1"}))
  assert clarity_eps.use_clarity_eps_controller(CP, _V({"NrdrLatEpsFirmwareFF": "1", "NrdrLatPidFirmwareFF": "1"}))

  def drive(values):
    monkeypatch.setattr(clarity_eps, "Params", lambda: _V(values))
    lac = clarity_eps.LatControlClarityEps(CP.as_reader(), None, DT_CTRL)
    VM = VehicleModel(CP)
    params = log.LiveParametersData.new_message()
    params.steerRatio, params.stiffnessFactor = 16.0, 1.0
    CS = car.CarState.new_message()
    CS.vEgo = 9.0
    outs = []
    for k in range(700):
      CS.steeringAngleDeg = 60.0 * math.sin(k * 0.01 - 0.05)
      out, _, _ = lac.update(k >= 20, CS, VM, params, False, 0.04 * math.sin(k * 0.01), False, 0.0,
                             None, None, SimpleNamespace())
      outs.append(out)
    return outs

  base = drive({"NrdrLatEpsFirmwareFF": "1"})
  assert max(abs(x) for x in base) > 0.05
  assert drive({"NrdrLatEpsFirmwareFF": "1", "NrdrLatPidFirmwareFF": "1"}) == base
