"""The Honda EPS command delay follows where the model's steering comes from (ns-bosch 023b532e26, ported to 7.0).

On 7.0 modeld writes it to the ModelLateralSource param when it changes (selfdrive/modeld/lateral_source.py), derived
from 7.0's runners; controlsd reads it once a second.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.car.structs import car
from openpilot.cereal import log
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _controller
from openpilot.selfdrive.modeld import lateral_source as ls
from openpilot.starpilot.models.runner import CatalogModelState


def _catalog(version):
  model = CatalogModelState.__new__(CatalogModelState)
  model.behavior_version = version
  return model


@pytest.mark.parametrize("version,expected", [
  ("v11", "plan"), ("v12", "plan"), ("v14", "actionHead"), ("v15", "actionHead"), ("v16", "actionHead"),
  ("v9", "curvatureHead"),
])
def test_catalog_models_by_version(version, expected):
  assert ls.lateral_source(_catalog(version), {"plan": 1}) == expected


def test_the_big_model_runners_follow_their_output():
  # the bundled Chestnut runner and Jetlink's JetlinkModelState (always the big-model role; a joining Jetlink model
  # drives as the small model itself) go through get_action_from_model: an action head, or a plan read through the
  # 0.3 s floor
  big = SimpleNamespace(chestnut=True)
  assert ls.lateral_source(big, {"action": 1}) == "actionHead"
  assert ls.lateral_source(big, {"plan": 1}) == "unknown"
  assert ls.lateral_source(SimpleNamespace(), {"plan": 1}) == "unknown"


def test_every_source_the_controller_knows():
  assert set(ls.SOURCES) == {"unknown", "plan", "actionHead", "curvatureHead"}
  assert set(honda_eps.CMD_DELAY_SCALE_BY_SOURCE) <= set(ls.SOURCES)


def test_modeld_writes_the_source_on_change_and_tells_the_model_the_schedule():
  source = (Path(__file__).parents[2] / "modeld" / "modeld.py").read_text()
  assert "source = lateral_source(model, model_output)" in source
  assert "if source != last_lateral_source:" in source
  assert 'params.put("ModelLateralSource", source)' in source
  assert 'cloudlog.event("modelLateralSource"' in source
  controls = (Path(__file__).parents[1] / "controlsd.py").read_text()
  assert 'self.LaC.update_lateral_source(self.params.get("ModelLateralSource") or "unknown")' in controls
  assert "scheduled_lateral_delay(lat_delay_schedule, v_ego)" in source


def _delays(lac, VM, sources, v_ego=8.0):
  CS = car.CarState.new_message(vEgo=v_ego)
  params = log.VehicleParameters.new_message(steerRatio=16.0, stiffnessFactor=1.0)
  out = []
  for source in sources:
    if source is not None:
      lac.update_lateral_source(source)
    lac.update(True, CS, VM, params, False, 0.01, False, 0.2, None, None, SimpleNamespace())
    out.append(lac.starpilot_lateral_state.epsCommandDelay)
  return out


def test_an_action_head_and_an_unknown_source_take_the_calibrations_command_delay(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  assert _delays(lac, VM, [None] * 5)[-1] == pytest.approx(0.20)  # no message yet
  assert _delays(lac, VM, ["actionHead"] * 5)[-1] == pytest.approx(0.20)
  assert _delays(lac, VM, ["curvatureHead"] * 5)[-1] == pytest.approx(0.20)


def test_a_plan_model_runs_with_no_command_delay_reached_by_a_ramp(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  frames = int(honda_eps.CMD_DELAY_RAMP_S / lac.dt)
  delays = _delays(lac, VM, ["plan"] * (frames + 5))
  assert delays[-1] == pytest.approx(0.0, abs=1e-9)
  steps = [a - b for a, b in zip(delays, delays[1:], strict=False)]
  assert max(steps) <= 0.20 * lac.dt / honda_eps.CMD_DELAY_RAMP_S + 1e-6  # no step: 0.20 s over 1 s (logged as float32)
  assert delays[frames // 2] == pytest.approx(0.10, abs=0.003)  # one ramp step is 0.002 s


def test_a_model_swap_ramps_back(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  frames = int(honda_eps.CMD_DELAY_RAMP_S / lac.dt)
  _delays(lac, VM, ["plan"] * (frames + 5))
  back = _delays(lac, VM, ["actionHead"] * (frames + 5))
  assert back[0] < 0.01 and back[-1] == pytest.approx(0.20)


def test_the_command_delay_takes_its_highway_value_with_speed(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  assert _delays(lac, VM, ["actionHead"] * 3, v_ego=20.0)[-1] == pytest.approx(0.10)
