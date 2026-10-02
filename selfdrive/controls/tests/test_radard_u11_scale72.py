"""D-074 BoschAU11Scale72: radard's U11-scale-derived values follow the toggle, and OFF is exactly the 1/64 set."""
import pytest

from openpilot.selfdrive.controls import radard


@pytest.fixture(autouse=True)
def restore_off():
  yield
  radard.set_bosch_a_u11_scale72(False)


def test_module_defaults_are_the_1_64_values():
  assert radard.BOSCH_A_U11_SCALE_MPS == 1.0 / 64.0
  assert radard.BOSCH_A_U11_LOW_RAIL_MPS == -13.5
  assert radard.ONPATH_ADOPT_RAIL_VREL_MPS == -12.5


def test_on_moves_rail_and_onpath_threshold():
  radard.set_bosch_a_u11_scale72(True)
  assert radard.BOSCH_A_U11_SCALE_MPS == 1.0 / 72.0
  assert radard.BOSCH_A_U11_LOW_RAIL_MPS == pytest.approx(-12.0)
  assert radard.ONPATH_ADOPT_RAIL_VREL_MPS == pytest.approx(-11.0)
  # a 1/72 rail reads as on-rail with radard's half-count tolerance
  assert -12.0 <= radard.BOSCH_A_U11_LOW_RAIL_MPS + radard.BOSCH_A_U11_SCALE_MPS / 2


def test_off_restores_exactly():
  radard.set_bosch_a_u11_scale72(True)
  radard.set_bosch_a_u11_scale72(False)
  assert radard.BOSCH_A_U11_SCALE_MPS == 1.0 / 64.0
  assert radard.BOSCH_A_U11_LOW_RAIL_MPS == -13.5
  assert radard.ONPATH_ADOPT_RAIL_VREL_MPS == -12.5
