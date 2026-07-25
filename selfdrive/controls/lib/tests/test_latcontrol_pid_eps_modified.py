"""NRDR: the modified-EPS live tune must reach every modified-EPS Honda, not just the Clarity.

Before this, latcontrol_pid gated the whole NRDR live-tune block on `is_clarity_eps_modified`, so a
Civic / CR-V 5G / Insight running a linear-max RWD image got none of the NRDR sliders. The gate is
now `is_eps_modified`. The variable-rack taper is scoped separately, by fingerprint alone
(NRDR_SR_CURVE_BY_FP), since a rack's geometry does not change with its EPS firmware.
"""
from types import SimpleNamespace

import pytest

from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from opendbc.car import structs
from selfdrive.controls.lib.latcontrol_pid import NRDR_SR_CURVE_BY_FP, LatControlPID

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


@pytest.mark.parametrize("candidate", [CAR.HONDA_CLARITY, CAR.HONDA_CRV_5G, CAR.HONDA_CIVIC, CAR.HONDA_CIVIC_BOSCH])
@pytest.mark.parametrize("fw_version", [MODIFIED_FW, STOCK_FW])
def test_mapped_racks_get_their_own_sr_curve(candidate, fw_version):
  # The rack's geometry does not change with the EPS firmware, so the curve is fingerprint-scoped
  # only. Each mapped car must get its own measured curve, never another car's.
  lat = _controller(candidate, fw_version)
  assert lat.sr_curve is NRDR_SR_CURVE_BY_FP[str(candidate)]


def test_unmapped_racks_keep_the_learned_steer_ratio():
  # An unmapped rack has no measured curve; applying another car's would corrupt the
  # curvature->angle conversion, so VehicleModel is left alone.
  for candidate in (CAR.HONDA_INSIGHT, CAR.HONDA_CIVIC_BOSCH_DIESEL):
    assert _controller(candidate, MODIFIED_FW).sr_curve is None


def test_clarity_pi_banding_does_not_leak_onto_other_racks():
  # 1.35/2.0 is Clarity tuning; nrdr-nightly runs a neutral 1.0 on every band for every car.
  clarity = _controller(CAR.HONDA_CLARITY, MODIFIED_FW)
  assert (clarity.lat_p_scale_standard, clarity.lat_p_scale_highway) == (1.35, 2.0)
  assert (clarity.lat_i_scale_standard, clarity.lat_i_scale_highway) == (1.35, 2.0)

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
