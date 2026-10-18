"""The command delay follows where the model's steering comes from (starpilotModelV2.lateralSource)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from cereal import car, custom, log
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _controller
from openpilot.selfdrive.modeld import lateral_source as ls

GENERATIONS = {  # (mlsim, is_v9, is_v14, is_v15, is_v16)
  "v11": (True, False, False, False, False), "v12": (True, False, False, False, False),
  "v9": (True, True, False, False, False),
  "v14": (True, False, True, False, False), "v15": (True, False, False, True, False), "v16": (True, False, False, False, True),
  "v7": (False, False, False, False, False),
}


@pytest.mark.parametrize("gen,outputs,expected", [
  ("v11", {"plan": 1}, "plan"), ("v12", {"plan": 1, "desired_curvature": 1}, "plan"),  # tinygrad: the plan, always
  ("v14", {"action": 1}, "actionHead"), ("v15", {"action": 1}, "actionHead"), ("v16", {"action": 1}, "actionHead"),
  ("v9", {"plan": 1, "desired_curvature": 1}, "curvatureHead"),
  ("v7", {"plan": 1, "desired_curvature": 1}, "curvatureHead"), ("v7", {"plan": 1}, "plan"),
])
def test_lateral_source_mirrors_get_action_from_model(gen, outputs, expected):
  assert ls.lateral_source(outputs, *GENERATIONS[gen]) == expected


def _model(inputs=(), off_policy=(), requires_action_t=False):
  return SimpleNamespace(numpy_inputs=dict.fromkeys(inputs), off_policy_enabled=bool(off_policy),
                         off_policy_numpy_inputs=dict.fromkeys(off_policy), requires_action_t=requires_action_t)


def test_delay_input_names_the_input_that_carries_the_told_delay():
  assert ls.delay_input(_model(["action_t", "desire"])) == "actionT"
  assert ls.delay_input(_model(["desire"], off_policy=["action_t"])) == "actionT"
  assert ls.delay_input(_model(requires_action_t=True)) == "actionT"  # Jetlink's remote model
  assert ls.delay_input(_model(["lateral_control_params", "prev_desired_curv"])) == "lateralControlParams"
  assert ls.delay_input(_model(["desire_pulse", "traffic_convention", "features_buffer"])) == "none"


def test_the_published_names_are_the_schema_enums():
  sources = set(custom.StarPilotModelDataV2.LateralSource.schema.enumerants)
  delays = set(custom.StarPilotModelDataV2.DelayInput.schema.enumerants)
  assert {ls.PLAN, ls.ACTION_HEAD, ls.CURVATURE_HEAD, "unknown"} == sources
  assert {"actionT", "lateralControlParams", "none", "unknown"} == delays
  assert custom.StarPilotModelDataV2.new_message().lateralSource == "unknown"  # logs from before these existed


def test_modeld_publishes_both_and_feeds_action_t_by_the_same_rule():
  source = (Path(__file__).parents[2] / "modeld" / "modeld.py").read_text()
  assert "starpilotModelV2.lateralSource = lateral_source(" in source
  assert "starpilotModelV2.delayInput = delay_input(model)" in source
  assert "if takes_action_t(model):" in source


def _delays(lac, VM, sources, v_ego=8.0):
  CS = car.CarState.new_message(vEgo=v_ego)
  params = log.LiveParametersData.new_message(steerRatio=16.0, stiffnessFactor=1.0)
  out = []
  for source in sources:
    if source is not None:
      lac.update_lateral_source(source)
    lac.update(True, CS, VM, params, False, 0.01, False, 0.2, None, None, SimpleNamespace())
    out.append(lac.starpilot_lateral_state.epsCommandDelay)
  return out


def test_an_action_head_and_an_unknown_source_take_the_calibrations_command_delay(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  assert _delays(lac, VM, [None] * 5)[-1] == pytest.approx(0.12)  # no message yet
  assert _delays(lac, VM, ["actionHead"] * 5)[-1] == pytest.approx(0.12)
  assert _delays(lac, VM, ["curvatureHead"] * 5)[-1] == pytest.approx(0.12)


def test_a_plan_model_runs_with_no_command_delay_reached_by_a_ramp(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  frames = int(honda_eps.CMD_DELAY_RAMP_S / lac.dt)
  delays = _delays(lac, VM, ["plan"] * (frames + 5))
  assert delays[-1] == pytest.approx(0.0, abs=1e-9)
  steps = [a - b for a, b in zip(delays, delays[1:], strict=False)]
  assert max(steps) <= 0.12 * lac.dt / honda_eps.CMD_DELAY_RAMP_S + 1e-6  # no step: 0.12 s over 1 s (logged as float32)
  assert delays[frames // 2] == pytest.approx(0.06, abs=0.002)


def test_a_model_swap_ramps_back(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  frames = int(honda_eps.CMD_DELAY_RAMP_S / lac.dt)
  _delays(lac, VM, ["plan"] * (frames + 5))
  back = _delays(lac, VM, ["actionHead"] * (frames + 5))
  assert back[0] < 0.01 and back[-1] == pytest.approx(0.12)


def test_the_command_delay_takes_its_highway_value_with_speed(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  assert _delays(lac, VM, ["actionHead"] * 3, v_ego=20.0)[-1] == pytest.approx(0.10)
