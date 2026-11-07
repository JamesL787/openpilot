"""D-074: U11 is 1/72 m/s per count, built in. radard's U11-scale-derived values are the 1/72 ones and match the scale
radar_interface decodes with."""
import pytest

from opendbc.car.honda import radar_interface
from openpilot.selfdrive.controls import radard


def test_module_values_are_the_1_72_ones():
  assert radard.BOSCH_A_U11_SCALE_MPS == 1.0 / 72.0
  assert radard.BOSCH_A_U11_LOW_RAIL_MPS == pytest.approx(-12.0, abs=1e-12)
  assert radard.ONPATH_ADOPT_RAIL_VREL_MPS == pytest.approx(-11.0, abs=1e-12)
  assert radard.BOSCH_A_U11_SCALE_MPS / 2 == 1.0 / 144.0


def test_radard_scale_matches_the_decode():
  assert radard.BOSCH_A_U11_SCALE_MPS == radar_interface.BOSCH_A_DIRECT_VREL_SCALE_MPS
  assert radar_interface.BOSCH_A_DIRECT_VREL_COUNTS_PER_MPS == 72


def test_rail_reads_on_rail_with_the_half_count():
  half = radard.BOSCH_A_U11_SCALE_MPS / 2
  assert -12.0 <= radard.BOSCH_A_U11_LOW_RAIL_MPS + half
  assert -12.0 + 2 * half > radard.BOSCH_A_U11_LOW_RAIL_MPS + half  # one count inside the rail is off it


def test_no_scale_param_or_1_64_path_remains():
  assert not hasattr(radard, "set_bosch_a_u11_scale72")
  assert not hasattr(radar_interface, "bosch_a_u11_scale72_enabled")
  assert not hasattr(radar_interface, "BOSCH_A_DIRECT_VREL_COUNTS_PER_MPS_1_64")
