"""Honda modified-EPS tuning and exact-firmware VGR profile selection."""
from types import SimpleNamespace

import pytest

from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.steer_ratio import (
  HONDA_VGR_INVERSE_BY_PROFILE,
)
from opendbc.car.honda.values import CAR
from opendbc.car import structs
from openpilot.selfdrive.controls.lib.latcontrol_pid import (
  NRDR_CLARITY_LEGACY_CENTER_RATIO,
  NRDR_CLARITY_LEGACY_OUTER_ANGLE,
  NRDR_CLARITY_LEGACY_OUTER_RATIO,
  NRDR_MODIFIED_EPS_KF_SPEED_BP,
  NRDR_MODIFIED_EPS_KF_V,
  NRDR_CLARITY_SR_CURVE_BP,
  NRDR_CLARITY_SR_CURVE_V,
  NRDR_SR_CURVE_BY_FP,
  LatControlPID,
  get_nrdr_modified_eps_kf,
)

CarParams = structs.CarParams

TOGGLES = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)

# a comma in the eps fw version is what marks a modified EPS
MODIFIED_FW = b'39990-TBA,A030\x00\x00'
STOCK_FW = b'39990-TBA-A030\x00\x00'

# LatControlPID only reaches into CI for the feedforward function
STUB_CI = SimpleNamespace(get_steer_feedforward_function=lambda: (lambda angle, v_ego: angle))

# Every Honda that can carry a linear-max RWD image. Civic Bosch is included: NRDR keeps modified-EPS
# cars on the angle-space PID controller, as nrdr-nightly does.
MODIFIED_EPS_CARS = [CAR.HONDA_CLARITY, CAR.HONDA_CRV_5G, CAR.HONDA_INSIGHT, CAR.HONDA_CIVIC, CAR.HONDA_CIVIC_BOSCH]


def _params(candidate, fw_version):
  car_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=fw_version, address=0x18DA30F1, subAddress=0)]
  return CarInterface.get_params(candidate, {0: {}, 1: {}, 2: {}}, car_fw, False, False, False, TOGGLES)


def _controller(candidate, fw_version):
  return LatControlPID(_params(candidate, fw_version), STUB_CI, 0.01)


# All of these must land on LatControlPID, including Civic Bosch.

@pytest.mark.parametrize("candidate", MODIFIED_EPS_CARS)
def test_modified_eps_hondas_select_the_pid_controller(candidate):
  # controlsd dispatches on lateralTuning.which(); anything but "pid" never reaches LatControlPID.
  assert _params(candidate, MODIFIED_FW).lateralTuning.which() == "pid"


@pytest.mark.parametrize("candidate", MODIFIED_EPS_CARS)
def test_modified_eps_hondas_get_the_nrdr_live_tune(candidate):
  lat = _controller(candidate, MODIFIED_FW)
  assert lat.is_eps_modified, f"{candidate} should run the NRDR live tune on a modified EPS"


@pytest.mark.parametrize("candidate", MODIFIED_EPS_CARS)
def test_stock_eps_hondas_do_not_get_the_nrdr_live_tune(candidate):
  lat = _controller(candidate, STOCK_FW)
  assert not lat.is_eps_modified, f"{candidate} must keep stock behaviour on an unmodified EPS"


@pytest.mark.parametrize("candidate, fw_version, profile", [
  (CAR.HONDA_CLARITY, b'39990-TRW,A020\x00\x00', "clarity_trw_a020"),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C020\x00\x00', "civic_tba_c020"),
  (CAR.HONDA_INSIGHT, b'39990-TXM,A040\x00\x00', "insight_txm_a040"),
])
def test_exact_eps_firmware_selects_only_its_vgr_profile(candidate, fw_version, profile):
  car_params = _params(candidate, fw_version)
  lat = LatControlPID(car_params, STUB_CI, 0.01)
  assert lat.vgr_inverse is HONDA_VGR_INVERSE_BY_PROFILE[profile]
  assert lat.sr_curve is None


def test_exact_clarity_firmware_uses_the_latest_firmware_legacy_handoff():
  lat = _controller(CAR.HONDA_CLARITY, b'39990-TRW,A020\x00\x00')
  assert lat.firmware_legacy_sr_curve is not None
  assert lat.firmware_legacy_sr_curve.valid


def test_clarity_uses_nrdr_two_point_ratio_and_modified_eps_base_pid():
  assert NRDR_CLARITY_SR_CURVE_BP == [0.0, NRDR_CLARITY_LEGACY_OUTER_ANGLE]
  assert NRDR_CLARITY_SR_CURVE_V == [NRDR_CLARITY_LEGACY_CENTER_RATIO, NRDR_CLARITY_LEGACY_OUTER_RATIO]

  CP = _params(CAR.HONDA_CLARITY, MODIFIED_FW)
  assert list(CP.lateralParams.torqueBP) == [0.0, 3840.0]
  assert list(CP.lateralTuning.pid.kpBP) == pytest.approx([0.0, 25.0 * 0.44704 - 1e-3, 25.0 * 0.44704, 50.0 * 0.44704])
  assert list(CP.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
  assert list(CP.lateralTuning.pid.kiBP) == pytest.approx([0.0, 25.0 * 0.44704 - 1e-3, 25.0 * 0.44704, 50.0 * 0.44704])
  assert list(CP.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
  assert CP.lateralTuning.pid.kf == pytest.approx(3.6e-6)


def test_clarity_lane_change_uses_outer_ratio_endpoint():
  class StubVehicleModel:
    sR = 18.5

    def get_steer_from_curvature(self, curvature, _v_ego, _roll):
      return curvature * self.sR

  lat = _controller(CAR.HONDA_CLARITY, b'39990-TRW,A020\x00\x00')
  cs = SimpleNamespace(
    steeringAngleDeg=0.0,
    steeringRateDeg=0.0,
    vEgo=20.0,
    steeringPressed=False,
    steeringTorque=0.0,
    leftBlinker=True,
    rightBlinker=False,
  )
  params = SimpleNamespace(angleOffsetDeg=0.0, roll=0.0)
  vm = StubVehicleModel()
  _, desired_angle, _ = lat.update(False, cs, vm, params, False, -0.01, False, 0.0, None, None, TOGGLES)
  assert desired_angle == pytest.approx(12.72 * 0.01 * 180.0 / 3.141592653589793)
  assert vm.sR == pytest.approx(18.5)


@pytest.mark.parametrize("candidate", [CAR.HONDA_CLARITY, CAR.HONDA_CIVIC_BOSCH, CAR.HONDA_INSIGHT,
                                       CAR.HONDA_CRV_5G, CAR.HONDA_CIVIC_BOSCH_DIESEL])
def test_unknown_eps_firmware_keeps_fixed_vehicle_model_ratio(candidate):
  lat = _controller(candidate, STOCK_FW)
  assert lat.vgr_inverse is None
  assert lat.sr_curve == NRDR_SR_CURVE_BY_FP.get(str(candidate))


def test_modified_eps_runtime_scales_remain_neutral():
  # P/I/F speed banding is baked into the base tune; runtime scales must not apply it again.
  clarity = _controller(CAR.HONDA_CLARITY, MODIFIED_FW)
  clarity_scales = (clarity.lat_p_scale_low, clarity.lat_p_scale_standard, clarity.lat_p_scale_highway,
                    clarity.lat_i_scale_low, clarity.lat_i_scale_standard, clarity.lat_i_scale_highway,
                    clarity.lat_f_scale_low, clarity.lat_f_scale_standard, clarity.lat_f_scale_highway)
  assert clarity_scales == (1.0,) * 9

  for candidate in (CAR.HONDA_CRV_5G, CAR.HONDA_INSIGHT, CAR.HONDA_CIVIC, CAR.HONDA_CIVIC_BOSCH):
    lat = _controller(candidate, MODIFIED_FW)
    scales = (lat.lat_p_scale_low, lat.lat_p_scale_standard, lat.lat_p_scale_highway,
              lat.lat_i_scale_low, lat.lat_i_scale_standard, lat.lat_i_scale_highway,
              lat.lat_f_scale_low, lat.lat_f_scale_standard, lat.lat_f_scale_highway)
    assert scales == (1.0,) * 9, f"{candidate} should run neutral band scales, got {scales}"


def test_non_honda_never_takes_the_eps_modified_path():
  CP = _params(CAR.HONDA_CLARITY, MODIFIED_FW)
  CP.brand = "toyota"
  assert not LatControlPID(CP, STUB_CI, 0.01).is_eps_modified


def test_clarity_and_c020_share_the_current_feedforward_curve():
  low_max = 25.0 * 0.44704
  assert NRDR_MODIFIED_EPS_KF_SPEED_BP == pytest.approx([0.0, low_max - 1e-3, low_max, 50.0 * 0.44704])
  assert NRDR_MODIFIED_EPS_KF_V == pytest.approx([2.4e-6, 1.8e-6, 3.6e-6, 6.0e-6])
  assert get_nrdr_modified_eps_kf(0.0) == pytest.approx(2.4e-6)
  assert get_nrdr_modified_eps_kf(low_max - 1e-3) == pytest.approx(1.8e-6)
  assert get_nrdr_modified_eps_kf(low_max) == pytest.approx(3.6e-6)
  assert get_nrdr_modified_eps_kf(50.0 * 0.44704) == pytest.approx(6.0e-6)

  clarity = _controller(CAR.HONDA_CLARITY, MODIFIED_FW)
  c020 = _controller(CAR.HONDA_CIVIC_BOSCH, MODIFIED_FW)
  assert clarity.is_modified_eps_kf_car
  assert c020.is_modified_eps_kf_car
  assert c020.is_civic_bosch_modified
  assert clarity.ff_factor == pytest.approx(3.6e-6)
  assert c020.ff_factor == pytest.approx(3.6e-6)
