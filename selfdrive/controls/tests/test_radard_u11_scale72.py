"""D-074 BoschAU11Scale72 (default ON): radard's U11-scale-derived values are the 1/72 ones by default, OFF is exactly
the 1/64 set, and the param is read once, in main()."""
import inspect

import pytest

from openpilot.selfdrive.controls import radard


@pytest.fixture(autouse=True)
def restore_default():
  yield
  radard.set_bosch_a_u11_scale72(True)


def test_module_defaults_are_the_1_72_values():
  assert radard.BOSCH_A_U11_SCALE_MPS == 1.0 / 72.0
  assert radard.BOSCH_A_U11_LOW_RAIL_MPS == pytest.approx(-12.0, abs=1e-12)
  assert radard.ONPATH_ADOPT_RAIL_VREL_MPS == pytest.approx(-11.0, abs=1e-12)
  assert radard.BOSCH_A_U11_SCALE_MPS / 2 == 1.0 / 144.0


def test_off_is_the_1_64_set_exactly():
  radard.set_bosch_a_u11_scale72(False)
  assert radard.BOSCH_A_U11_SCALE_MPS == 1.0 / 64.0
  assert radard.BOSCH_A_U11_LOW_RAIL_MPS == -13.5
  assert radard.ONPATH_ADOPT_RAIL_VREL_MPS == -12.5
  assert radard.BOSCH_A_U11_SCALE_MPS / 2 == 1.0 / 128.0


def test_on_after_off_restores_the_defaults():
  defaults = (radard.BOSCH_A_U11_SCALE_MPS, radard.BOSCH_A_U11_LOW_RAIL_MPS, radard.ONPATH_ADOPT_RAIL_VREL_MPS)
  radard.set_bosch_a_u11_scale72(False)
  radard.set_bosch_a_u11_scale72(True)
  assert (radard.BOSCH_A_U11_SCALE_MPS, radard.BOSCH_A_U11_LOW_RAIL_MPS, radard.ONPATH_ADOPT_RAIL_VREL_MPS) == defaults


@pytest.mark.parametrize("enabled, rail", [(True, -12.0), (False, -13.5)])
def test_rail_reads_on_rail_with_the_half_count_of_its_own_scale(enabled, rail):
  radard.set_bosch_a_u11_scale72(enabled)
  half = radard.BOSCH_A_U11_SCALE_MPS / 2
  assert rail <= radard.BOSCH_A_U11_LOW_RAIL_MPS + half
  assert rail + 2 * half > radard.BOSCH_A_U11_LOW_RAIL_MPS + half  # one count inside the rail is off it


def test_param_is_read_once_in_main():
  source = inspect.getsource(radard)
  assert source.count("bosch_a_u11_scale72_enabled()") == 1
  assert "bosch_a_u11_scale72_enabled()" in inspect.getsource(radard.main)
