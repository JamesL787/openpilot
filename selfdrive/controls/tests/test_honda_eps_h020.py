"""The modified Civic Bosch 39990-TEA,H020 PTM: calibration selection and its driver-override defaults."""
from types import SimpleNamespace

import pytest

import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from opendbc.car.honda import steer_ratio as sr
from opendbc.car.honda.carcontroller import CarController
from opendbc.car.honda.h020 import H020_OVERRIDE_FADE_DOWN_S, H020_OVERRIDE_FADE_UP_S, H020_OVERRIDE_HOLD_S, H020_OVERRIDE_THRESHOLD, \
  is_h020_eps, seed_h020_override_defaults
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
  assert CAL.cmd_delay_s == CAL.cmd_delay_highway_s == 0.27
  assert CAL.lat_delay_schedule == eps_cal.CIVIC_TBA_C020_LAT_DELAY_SCHEDULE
  prov = eps_cal.provenance(CAL)
  assert prov["cmd_delay"].startswith("measured (provisional)") and prov["model_delay"].startswith("inferred")


class _WritableParams(_Params):
  def put(self, key, value):
    self.values[key] = value


def test_override_defaults_are_seeded_once_over_manager_defaults(tmp_path):
  # manager has already filled the params_keys.h defaults (2400, 1.5 s) before the car is seen
  params = _WritableParams({"NrdrDriverOverrideThreshold": 2400, "HondaOverrideFadeDownSecs": 0.1, "HondaOverrideFadeUpSecs": 1.5})
  flag = tmp_path / "h020_override_defaults_v1"
  assert seed_h020_override_defaults(params, flag)
  assert params.values == {"NrdrDriverOverrideThreshold": H020_OVERRIDE_THRESHOLD,
                           "HondaOverrideFadeDownSecs": H020_OVERRIDE_FADE_DOWN_S, "HondaOverrideFadeUpSecs": H020_OVERRIDE_FADE_UP_S}
  assert flag.exists()

  # a later user change sticks
  params.put("NrdrDriverOverrideThreshold", 2000)
  assert not seed_h020_override_defaults(params, flag)
  assert params.values["NrdrDriverOverrideThreshold"] == 2000


def test_failed_seed_is_retried(tmp_path):
  class _Broken(_WritableParams):
    def put(self, key, value):
      raise OSError("read-only")
  flag = tmp_path / "h020_override_defaults_v1"
  assert not seed_h020_override_defaults(_Broken(), flag)
  assert not flag.exists()


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
