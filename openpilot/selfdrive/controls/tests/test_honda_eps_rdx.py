"""The Acura RDX 3G (39990-TJB-A220 Route-A PTM): a THR-family image steered through the Clarity's law, in its units."""
import numpy as np
import pytest

import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.honda_eps_firmware_ff as eps_ff
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from opendbc.car.honda import steer_ratio as sr
from opendbc.car.honda.values import CAR, CarControllerParams, HondaFlags
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _params

RDX_PTM_FW = b'39990-TJB,A220\x00\x00'
CAL = eps_cal.ACURA_RDX_TJB_A220
# Read from the build the owner runs (KB TJB_A220_PTM_ROUTE_A_20261014/BUILD_Trk1641, rows 0 and 3 identical)
TJB_TARGET_A = (0, 128, 256, 384, 512, 640, 768, 896, 1024)
TJB_TARGET_S = (0, 3968, 7936, 11904, 15872, 19840, 23808, 27776, 30000)
TJB_KP_A = (0, 58, 109, 243, 320, 448, 640, 896, 1024)
TJB_KP = (7, 8, 9, 11, 13, 15, 16, 17, 17)  # >> 6


def test_the_ptm_rdx_gets_its_road_measured_vgr_and_its_calibration():
  CP = _params(RDX_PTM_FW, CAR.ACURA_RDX_3G)
  assert CP.flags & HondaFlags.EPS_MODIFIED and CP.flags & HondaFlags.VGR_RDX_TJB_A220
  assert honda_eps.eps_firmware_calibration(CP) is CAL   # Night Star port: every calibrated image, no setting
  assert honda_eps.get_rack_map(CP, CAL) is not None
  # the 2022+ (MMR) runs the same PTM image on the same rack, sent the same 4096 per unit
  assert eps_cal.select_eps_firmware_calibration("ACURA_RDX_3G_MMR", "39990-TJB-A220") is CAL
  assert eps_cal.select_eps_firmware_calibration("HONDA_CRV_5G", "39990-TJB-A220") is None


def test_the_ptm_mmr_gets_the_same_calibration():
  CP = _params(RDX_PTM_FW, CAR.ACURA_RDX_3G_MMR)
  # 7.0 keeps the command map in CarControllerParams, not CP.lateralParams
  assert list(CarControllerParams(CP).STEER_LOOKUP_V) == [-4096, 0, 4096]
  assert honda_eps.eps_firmware_calibration(CP) is CAL


def test_the_stock_rdx_is_untouched():
  CP = _params(b'39990-TJB-A220\x00\x00', CAR.ACURA_RDX_3G)
  assert not CP.flags & HondaFlags.EPS_MODIFIED
  assert honda_eps.eps_firmware_calibration(CP) is None


@pytest.mark.parametrize("a", list(range(0, 1025, 16)))
def test_the_clarity_unit_target_is_the_tjb_target_at_every_command(a):
  # TJB keys on a = E4 / 4; the calibration keys on the Clarity's q = trunc(E4 * 56756/32768 / 4) through its a-axis x 1.732
  e4 = 4 * a
  tjb = float(np.interp(a, TJB_TARGET_A, TJB_TARGET_S))
  ours = abs(eps_ff.r5_from_output(-e4 / CAL.e4_per_output, 10.0, CAL))
  assert ours == pytest.approx(tjb, abs=40)   # integer rounding of the key, <= one key step of the 31/a slope


@pytest.mark.parametrize("a", [16, 58, 109, 200, 243, 320, 448, 640, 896, 1024])
def test_the_clarity_unit_p_gain_is_the_tjbs(a):
  # TJB: P = Kp(a) * err >> 6; the Clarity law: P = Kp(R5) * err / 1024, so the stored gains are x 16
  r5 = float(np.interp(a, TJB_TARGET_A, TJB_TARGET_S))
  assert eps_ff.firmware_kp(r5, CAL) / 1024 == pytest.approx(float(np.interp(a, TJB_KP_A, TJB_KP)) / 64, rel=0.02)


def test_full_output_reaches_the_clarity_top():
  assert CAL.e4_per_output == 4096 and CAL.key_clamp == 1774
  # TJB reads a = 1024 -> 30000; the Clarity key truncates to 1773 there, 10 counts short. The Clarity: 29982 at 3840
  assert abs(eps_ff.r5_from_output(-1.0, 10.0, CAL)) == pytest.approx(30000, abs=15)


def test_its_linear_map_quickens_as_the_rack_does():
  linear, physical = sr.HONDA_VGR_INVERSE_BY_PROFILE[sr.HONDA_VGR_RDX_TJB_A220]
  slope = lambda a: (np.interp(a + 5, physical, linear) - np.interp(max(a - 5, 0), physical, linear)) / (a + 5 - max(a - 5, 0))  # noqa: E731
  assert slope(2.5) == pytest.approx(1.0, abs=0.03)
  assert slope(200) == pytest.approx(9.58 / 7.8, rel=0.01)   # the 0x18F rate word, centre to plateau
  assert CAL.r6_angle_gain[0] == 1.0 and max(CAL.r6_angle_gain) == pytest.approx(9.58 / 7.8, rel=0.02)


@pytest.mark.parametrize("v", [3.0, 15.0, 30.0])
def test_its_rack_map_round_trips_to_lock(v):
  CP = _params(RDX_PTM_FW, CAR.ACURA_RDX_3G)
  rack_map = honda_eps.get_rack_map(CP, CAL)
  for angle in (-480.0, -200.0, -10.0, 4.0, 90.0, 400.0):
    assert rack_map.angle_from_curvature(rack_map.curvature_from_angle(angle, v, 0.01), v, 0.01) == pytest.approx(angle, abs=1e-3)


def test_its_feedback_is_the_word_derived_value():
  # ref = 32 x the 0x18F rate word in the image (0x1C668 / 0x1D300), x 15768/32768 in the build; the word is -7.8 per
  # published deg/s at centre
  assert CAL.r6_per_deg_s == pytest.approx(15768 / 32768 * 32 * -7.8, abs=0.1)
  assert eps_cal.provenance(CAL)["r6"].startswith("firmware")


def test_its_trims_come_from_the_closed_loop_replay():
  # P x0.7 above 50 mph and a 15 deg/s friction knee at speed (see RDX_TJB_A220_P_SCALE); I and town untouched
  assert CAL.p_scale == (1.0, 1.0, 0.7) and CAL.i_scale == (1.0, 1.0, 1.0)
  assert CAL.friction_width_v == (20.0, 15.0)
  assert eps_cal.provenance(CAL)["trims"].startswith("measured: closed-loop replay")
