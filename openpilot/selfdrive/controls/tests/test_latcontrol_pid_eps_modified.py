"""Honda modified-EPS tuning, controller selection and exact-firmware VGR profile selection.

Ported from vfn (selfdrive/controls/lib/tests/). On StarPilot 7.0 a modified EPS is an exact image on
MODIFIED_EPS_FW rather than any comma-marked one, the modified-EPS PID path lives in LatControlHondaModifiedPID, and
stock-EPS cars keep 7.0's own LatControlPID.
"""
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.steer_ratio import HONDA_VGR_INVERSE_BY_PROFILE
from opendbc.car.honda.values import CAR, CarControllerParams, HondaFlags
from openpilot.common.pid import PIDController
from openpilot.selfdrive.controls.lib.lateral_controller_factory import create_lateral_controller
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_honda_modified_pid import (
  MODIFIED_EPS_KF_SPEED_BP,
  MODIFIED_EPS_KF_V,
  LatControlHondaModifiedPID,
  _clarity_eps_pid_output_scale,
  get_modified_eps_kf,
  use_honda_modified_pid,
)

CarParams = structs.CarParams

# The fleet's modified images (MODIFIED_EPS_FW); a comma alone no longer marks a modified EPS on 7.0.
MODIFIED_FW = {
  CAR.HONDA_CLARITY: b'39990-TRW,A020\x00\x00',
  CAR.HONDA_CRV_5G: b'39990-TLA,A040\x00\x00',
  CAR.HONDA_INSIGHT: b'39990-TXM,A040\x00\x00',
  CAR.HONDA_CIVIC: b'39990-TBA,A030\x00\x00',
  CAR.HONDA_CIVIC_BOSCH: b'39990-TBA,C020\x00\x00',
  CAR.ACURA_RDX_3G: b'39990-TJB,A220\x00\x00',
  CAR.ACURA_RDX_3G_MMR: b'39990-TJB,A220\x00\x00',
}
STOCK_FW = b'39990-TBA-A010\x00\x00'

# The controllers only reach into CI for the feedforward function
STUB_CI = SimpleNamespace(get_steer_feedforward_function=lambda: (lambda angle, v_ego: angle))

MODIFIED_EPS_CARS = list(MODIFIED_FW)


def _params(candidate, fw_version):
  car_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=fw_version, address=0x18DA30F1, subAddress=0)]
  return CarInterface.get_params(candidate, {0: {}, 1: {}, 2: {}}, car_fw, False, False, False)


def _controller(candidate, fw_version=None):
  return LatControlHondaModifiedPID(_params(candidate, fw_version or MODIFIED_FW[candidate]), STUB_CI, 0.01)


@pytest.mark.parametrize("candidate", MODIFIED_EPS_CARS)
def test_modified_eps_hondas_select_the_modified_eps_pid_path(candidate):
  cp = _params(candidate, MODIFIED_FW[candidate])
  assert cp.flags & HondaFlags.EPS_MODIFIED and not cp.dashcamOnly
  assert cp.lateralTuning.which() == "pid"
  assert use_honda_modified_pid(cp)


def _with_eps_fw(cp, fw):
  # get_params reads the firmware but does not keep it; the calibration lookup reads CP.carFw
  cp.carFw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=fw, address=0x18DA30F1, subAddress=0)]
  return cp


def test_factory_gives_an_uncalibrated_modified_eps_honda_the_modified_eps_pid():
  # the Accord's TVA-A150 PTM has no calibration, so the modified-EPS PID
  fw = b'39990-TVA,A150\x00\x00'
  lac = create_lateral_controller(_with_eps_fw(_params(CAR.HONDA_ACCORD, fw), fw), STUB_CI, 0.01, mode=None)
  assert type(lac) is LatControlHondaModifiedPID


@pytest.mark.parametrize("candidate", [CAR.ACURA_RDX_3G, CAR.ACURA_RDX_3G_MMR])
def test_factory_gives_both_rdx_3g_platforms_the_honda_eps_controller(candidate):
  # the TJB-A220 PTM runs on every 3G RDX (2019-2026): one image, one rack, one calibration
  from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import LatControlHondaEps
  fw = MODIFIED_FW[candidate]
  lac = create_lateral_controller(_with_eps_fw(_params(candidate, fw), fw), STUB_CI, 0.01, mode=None)
  assert type(lac) is LatControlHondaEps


@pytest.mark.parametrize("candidate", MODIFIED_EPS_CARS)
def test_modified_eps_hondas_get_the_live_tune(candidate):
  assert _controller(candidate).is_eps_modified


@pytest.mark.parametrize("candidate", [CAR.HONDA_CLARITY, CAR.HONDA_CRV_5G, CAR.HONDA_INSIGHT, CAR.HONDA_CIVIC,
                                       CAR.HONDA_CIVIC_BOSCH])
def test_stock_eps_hondas_keep_7_0s_stock_pid(candidate):
  # Night Star port decision: a stock-EPS car runs 7.0's own LatControlPID, so it no longer picks up the
  # road-measured steer-ratio curve it got on vfn.
  cp = _params(candidate, STOCK_FW)
  assert not cp.flags & HondaFlags.EPS_MODIFIED
  assert not use_honda_modified_pid(cp)
  assert type(create_lateral_controller(cp, STUB_CI, 0.01, mode=None)) is LatControlPID


@pytest.mark.parametrize("candidate, fw_version, profile", [
  (CAR.HONDA_CLARITY, b'39990-TRW,A020\x00\x00', "clarity_trw_a020"),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C020\x00\x00', "civic_tba_c020"),
  (CAR.HONDA_INSIGHT, b'39990-TXM,A040\x00\x00', "insight_txm_a040"),
  (CAR.HONDA_CRV_5G, b'39990-TLA,A220\x00\x00', "crv_tla_a040"),   # the A220 carries the A040's table
])
def test_the_modified_eps_pid_steers_on_the_exact_firmware_vgr_table(candidate, fw_version, profile):
  # Night Star port: the firmware VGR table is this controller's geometry; the road-fit curves are not ported
  lat = _controller(candidate, fw_version)
  assert lat.vgr_inverse is HONDA_VGR_INVERSE_BY_PROFILE[profile]
  assert not hasattr(lat, "sr_curve")


@pytest.mark.parametrize("candidate", [CAR.ACURA_RDX_3G, CAR.ACURA_RDX_3G_MMR])
def test_both_rdx_3g_platforms_get_the_road_measured_tjb_map(candidate):
  # the TJB-A220 PTM runs on every 3G RDX (2019-2026, the 2022+ MMR included): one rack, one road-measured map
  assert _controller(candidate).vgr_inverse is not None


def test_modified_eps_runtime_scales_match_defaults():
  # P/F defaults are neutral, while the requested I defaults reduce low-speed correction
  # to 20% and disable highway integration.
  expected_scales = (1.0, 1.0, 1.0, 0.2, 1.0, 0.0, 1.0, 1.0, 1.0)
  for candidate in MODIFIED_EPS_CARS:
    lat = _controller(candidate)
    scales = (lat.lat_p_scale_low, lat.lat_p_scale_standard, lat.lat_p_scale_highway,
              lat.lat_i_scale_low, lat.lat_i_scale_standard, lat.lat_i_scale_highway,
              lat.lat_f_scale_low, lat.lat_f_scale_standard, lat.lat_f_scale_highway)
    assert scales == expected_scales, f"{candidate} should use the configured band scales, got {scales}"


def test_non_honda_never_takes_the_eps_modified_path():
  CP = _params(CAR.HONDA_CLARITY, MODIFIED_FW[CAR.HONDA_CLARITY])
  CP.brand = "toyota"
  assert not use_honda_modified_pid(CP)


def test_clarity_and_c020_share_the_current_feedforward_curve():
  low_max = 25.0 * 0.44704
  assert MODIFIED_EPS_KF_SPEED_BP == pytest.approx([0.0, low_max - 1e-3, low_max, 50.0 * 0.44704])
  assert MODIFIED_EPS_KF_V == pytest.approx([2.4e-6, 1.8e-6, 3.6e-6, 6.0e-6])
  assert get_modified_eps_kf(0.0) == pytest.approx(2.4e-6)
  assert get_modified_eps_kf(low_max - 1e-3) == pytest.approx(1.8e-6)
  assert get_modified_eps_kf(low_max) == pytest.approx(3.6e-6)
  assert get_modified_eps_kf(50.0 * 0.44704) == pytest.approx(6.0e-6)

  clarity = _controller(CAR.HONDA_CLARITY)
  c020 = _controller(CAR.HONDA_CIVIC_BOSCH)
  assert clarity.is_modified_eps_kf_car and c020.is_modified_eps_kf_car
  assert clarity.ff_factor == pytest.approx(3.6e-6)
  assert c020.ff_factor == pytest.approx(3.6e-6)


@pytest.mark.parametrize(("desired_angle", "expected"), [
  (-24.0, 1.07438),
  (24.0, 1.07438),
])
def test_modified_eps_output_scale_is_direction_neutral(desired_angle, expected):
  # The shared modified-EPS scale is direction-neutral. Directional authority belongs
  # in the PID, not in a multiplier on its complete P/I/F output.
  assert _clarity_eps_pid_output_scale(desired_angle, 10.0) == pytest.approx(expected)


def test_modified_eps_i_scale_controls_accumulation_and_clears_zero_band_state():
  pid = PIDController(k_p=0.0, k_i=1.0, rate=100)

  pid.update(1.0, integrator_gain_scale=0.2)
  assert pid.i == pytest.approx(0.002)

  pid.update(1.0, integrator_gain_scale=0.0, reset_integrator=True)
  assert pid.i == pytest.approx(0.0)

  # Returning to a non-zero band starts clean; no hidden highway I can reappear.
  pid.update(0.0, integrator_gain_scale=1.0)
  assert pid.i == pytest.approx(0.0)

  pid.update(1.0, integrator_gain_scale=1.0)
  assert pid.i == pytest.approx(0.01)

  # The modified-EPS low-speed freeze clears I as well, so pull-away cannot revive
  # an old parking-speed correction.
  pid.update(0.0, freeze_integrator=True, reset_integrator=True)
  assert pid.i == pytest.approx(0.0)


def test_crv_5g_shares_the_clarity_modified_eps_tune():
  crv_5g = _controller(CAR.HONDA_CRV_5G)
  assert crv_5g.is_modified_eps_kf_car
  assert crv_5g.ff_factor == pytest.approx(3.6e-6)

  low_max = 25.0 * 0.44704
  expected_bp = [0.0, low_max - 1e-3, low_max, 50.0 * 0.44704]
  cp = _params(CAR.HONDA_CRV_5G, MODIFIED_FW[CAR.HONDA_CRV_5G])
  assert list(cp.lateralTuning.pid.kpBP) == pytest.approx(expected_bp)
  assert list(cp.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
  assert list(cp.lateralTuning.pid.kiBP) == pytest.approx(expected_bp)
  assert list(cp.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])


@pytest.mark.parametrize("candidate", [CAR.ACURA_RDX_3G, CAR.ACURA_RDX_3G_MMR])
def test_rdx_3g_ptm_shares_the_clarity_modified_eps_tune_on_pid(candidate):
  # Both RDX 3G platforms flash to the same 39990-TJB,A220 PTM image.
  cp = _params(candidate, MODIFIED_FW[candidate])
  clarity = _params(CAR.HONDA_CLARITY, MODIFIED_FW[CAR.HONDA_CLARITY])
  assert cp.flags & HondaFlags.EPS_MODIFIED
  assert cp.lateralTuning.which() == "pid"
  # The PTM target map X axis ends at E4 4096, where Route A matches the Clarity's 3840 top.
  lookup = CarControllerParams(cp)
  assert lookup.STEER_LOOKUP == lookup.STEER_LOOKUP_V == [-4096, 0, 4096]
  for field in ("kpBP", "kpV", "kiBP", "kiV"):
    assert list(getattr(cp.lateralTuning.pid, field)) == pytest.approx(list(getattr(clarity.lateralTuning.pid, field)))
  assert cp.lateralTuning.pid.kf == pytest.approx(clarity.lateralTuning.pid.kf)
  assert cp.steerAtStandstill

  rdx = LatControlHondaModifiedPID(cp, STUB_CI, 0.01)
  assert rdx.is_eps_modified and rdx.is_modified_eps_kf_car

  from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import eps_firmware_calibration
  assert eps_firmware_calibration(cp) is None


def test_stock_rdx_3g_keeps_7_0s_tune():
  # Night Star port decision: vfn moved the stock RDX 3G to the torque controller; 7.0's PID tune is kept
  cp = _params(CAR.ACURA_RDX_3G, b'39990-TJB-A030\x00\x00')
  assert not cp.flags & HondaFlags.EPS_MODIFIED
  assert cp.lateralTuning.which() == "pid"
  assert list(cp.lateralTuning.pid.kpV) == pytest.approx([0.2])
