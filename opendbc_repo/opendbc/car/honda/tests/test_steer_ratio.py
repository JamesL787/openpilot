from types import SimpleNamespace

import pytest

from opendbc.car.honda.steer_ratio import (
  _CRV_TLA_A040_POSITION_X,
  _CRV_TLA_A040_POSITION_Y,
  HONDA_VGR_CRV_TLA_A040,
  HONDA_VGR_INVERSE_BY_PROFILE,
  NRDR_CRV_TLA_A040_VGR_ANGLE_BP,
  NRDR_CRV_TLA_A040_VGR_LINEAR_BP,
  get_honda_vgr_profile,
  vgr_linear_to_physical,
  vgr_physical_to_linear,
)


def _eps(version: bytes):
  return [SimpleNamespace(ecu="eps", fwVersion=version)]


@pytest.mark.parametrize("version", [b"39990-TLA-A040\0\0", b"39990-TLA,A040\0\0"])
def test_crv_5g_a040_selects_exact_firmware_profile(version):
  assert get_honda_vgr_profile(_eps(version)) == HONDA_VGR_CRV_TLA_A040


@pytest.mark.parametrize("version", [b"39990-TLA-A030\0\0", b"39990-TLA-A110\0\0", b"39990-TLA-A220\0\0"])
def test_other_crv_firmware_does_not_reuse_a040_table(version):
  assert get_honda_vgr_profile(_eps(version)) is None


def test_crv_5g_a040_table_uses_all_exact_firmware_knots():
  assert _CRV_TLA_A040_POSITION_X == [
    0, 42, 84, 125, 167, 209, 251, 292, 335, 419, 636, 864, 1102, 1227, 1276,
    1326, 1376, 1426, 1476, 1526, 1578, 1628, 1680, 1729, 2108, 2488, 2869, 3248, 3626, 5130,
  ]
  assert _CRV_TLA_A040_POSITION_Y == [
    16783, 16783, 16790, 16795, 16979, 16979, 17100, 17086, 17100, 17110,
    17300, 17597, 17964, 18170, 18247, 18322, 18378, 18460, 18521, 18566,
    18651, 18697, 18761, 18803, 19129, 19345, 19527, 19657, 19756, 19989,
  ]
  inverse = HONDA_VGR_INVERSE_BY_PROFILE[HONDA_VGR_CRV_TLA_A040]
  assert inverse == (NRDR_CRV_TLA_A040_VGR_LINEAR_BP, NRDR_CRV_TLA_A040_VGR_ANGLE_BP)
  assert len(inverse[0]) == len(inverse[1]) > 30  # firmware intervals are subdivided, not reduced to a six-point fit
  assert inverse[0][0] == inverse[1][0] == 0.0
  assert inverse[1][-1] == pytest.approx(513.0 * 16384.0 / 19989.0)


@pytest.mark.parametrize("linear", [-400.0, -150.0, -20.0, 0.0, 20.0, 150.0, 400.0])
def test_crv_5g_a040_position_map_round_trips(linear):
  inverse = HONDA_VGR_INVERSE_BY_PROFILE[HONDA_VGR_CRV_TLA_A040]
  physical = vgr_linear_to_physical(linear, inverse)
  assert vgr_physical_to_linear(physical, inverse) == pytest.approx(linear)
