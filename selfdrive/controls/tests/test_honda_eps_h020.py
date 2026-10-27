"""The modified Civic Bosch 39990-TEA,H020 PTM: calibration selection and its driver-override defaults."""
from types import SimpleNamespace

import pytest

import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from opendbc.car.honda import steer_ratio as sr
from opendbc.car.honda.carcontroller import CarController
from opendbc.car.honda.h020 import H020_OVERRIDE_HOLD_S, is_h020_eps, param_or_default
from opendbc.car.honda.values import CAR, HondaFlags
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _Params, _params

H020_FW = b'39990-TEA,H020\x00\x00'
CAL = eps_cal.CIVIC_TEA_H020


def _fw(version):
  return [SimpleNamespace(ecu="eps", fwVersion=version)]


def test_calibration_is_selected_for_the_modified_h020_on_a_civic_bosch():
  CP = _params(H020_FW, CAR.HONDA_CIVIC_BOSCH)
  assert CP.flags & HondaFlags.EPS_MODIFIED and CP.flags & HondaFlags.VGR_CIVIC_TBA_C020
  assert honda_eps.eps_firmware_calibration(CP, _Params()) is CAL  # default_on: params may be wiped on boot
  assert eps_cal.select_eps_firmware_calibration("HONDA_CIVIC_BOSCH", "39990-TEA-H020") is CAL
  assert eps_cal.select_eps_firmware_calibration("HONDA_CIVIC", "39990-TEA-H020") is None
  assert sr.get_honda_vgr_profile(_fw(H020_FW)) == sr.HONDA_VGR_CIVIC_TBA_C020


def test_stock_h020_is_not_a_ptm():
  CP = _params(b'39990-TEA-H020\x00\x00', CAR.HONDA_CIVIC_BOSCH)
  assert not CP.flags & HondaFlags.EPS_MODIFIED
  assert not is_h020_eps(_fw(b'39990-TEA-H020\x00\x00'))
  assert is_h020_eps(_fw(H020_FW))
  assert not is_h020_eps(_fw(b'39990-TBA,C020\x00\x00'))


def test_calibration_values():
  assert CAL.key_clamp == 1663 and CAL.e4_per_output == 3840.0
  assert (CAL.load.k0, CAL.load.friction) == (-7.8, -285.0)
  assert CAL.cmd_delay_s == CAL.cmd_delay_highway_s == 0.15
  assert CAL.lat_delay_schedule == eps_cal.CIVIC_TBA_C020_LAT_DELAY_SCHEDULE
  prov = eps_cal.provenance(CAL)
  assert prov["cmd_delay"].startswith("inferred") and prov["model_delay"].startswith("inferred")


def test_param_or_default():
  assert param_or_default(_Params(), "X", 0.5) == 0.5
  assert param_or_default(_Params({"X": "1.5"}), "X", 0.5) == 1.5
  assert param_or_default(_Params({"X": b"2.0"}), "X", 0.5) == 2.0
  assert param_or_default(_Params({"X": "junk"}), "X", 0.5) == 0.5


def _controller(h020):
  cc = SimpleNamespace(is_h020=h020, steering_pressed_filter_s=0.0, steering_pressed_robust_prev=False, steering_pressed_hold_s=0.0)
  return cc


def _step(cc, raw_pressed, torque=3000., cmd=0.5):
  CS = SimpleNamespace(out=SimpleNamespace(steeringPressed=raw_pressed, steeringTorque=torque))
  return CarController._filtered_steering_pressed(cc, CS, cmd)


def test_h020_holds_an_override_after_the_torque_drops():
  cc = _controller(True)
  assert _step(cc, True, torque=-3000.)  # opposing torque latches at once
  held = 0
  while _step(cc, False):
    held += 1
    assert held < 1000
  assert held * DT_CTRL == pytest.approx(H020_OVERRIDE_HOLD_S, abs=2 * DT_CTRL)


def test_other_cars_release_at_once():
  cc = _controller(False)
  assert _step(cc, True, torque=-3000.)
  assert not _step(cc, False)
