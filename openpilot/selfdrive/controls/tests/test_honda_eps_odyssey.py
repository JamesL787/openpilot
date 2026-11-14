"""The Honda Odyssey (39990-THR-A020 PTM, 2026-11-10): the RDX car build ported to THR, on a spec vehicle side."""
import numpy as np
import pytest

import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.honda_eps_firmware_ff as eps_ff
import openpilot.selfdrive.controls.lib.honda_eps_spec_plant as spec
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from opendbc.car.honda import steer_ratio as sr
from opendbc.car.honda.values import CAR, CarControllerParams, HondaFlags
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _params

PTM_FW = b'39990-THR,A020\x00\x00'
CAL = eps_cal.ODYSSEY_THR_A020
RDX = eps_cal.ACURA_RDX_TJB_A220
A = 56756 / 32768
# Read from 39990-THR,A020-20261110-PTM.rwd decoded (RWD sha256 b89d20f0), rows 0-2 (0x57B00 + 0x300 * row, identical):
# target map X/Y 0x57BAE/0x57BC0 and Kp X/Y 0x57C70/0x57C82, in THR's a = E4 / 4 units
MAP_X = (0, 128, 256, 384, 512, 640, 768, 896, 1024)
MAP_Y = (0, 3968, 7936, 11904, 15872, 19840, 23808, 27776, 30000)
KP_X = (0, 55, 166, 319, 532, 776, 887, 942, 998)
KP_Y = (7, 8, 10, 13, 15, 16, 17, 17, 17)


def test_the_ptm_gets_its_calibration_and_linear_geometry():
  CP = _params(PTM_FW, CAR.HONDA_ODYSSEY)
  assert CP.flags & HondaFlags.EPS_MODIFIED and CP.flags & HondaFlags.VGR_ODYSSEY_THR_A020
  assert not CP.dashcamOnly
  assert list(CarControllerParams(CP).STEER_LOOKUP_V) == [-4096, 0, 4096]
  assert CP.lateralTuning.which() == "pid" and list(CP.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
  assert honda_eps.eps_firmware_calibration(CP) is CAL
  assert honda_eps.get_rack_map(CP, CAL) is not None
  assert eps_cal.select_eps_firmware_calibration("HONDA_ODYSSEY_TWN", "39990-THR-A020") is None


def test_the_stock_odyssey_is_untouched():
  CP = _params(b'39990-THR-A020\x00\x00', CAR.HONDA_ODYSSEY)
  assert not CP.flags & HondaFlags.EPS_MODIFIED
  assert list(CP.lateralTuning.pid.kpV) == pytest.approx([0.28])
  assert honda_eps.eps_firmware_calibration(CP) is None


def test_the_tables_are_the_images():
  assert CAL.r5_key_bp == tuple(round(a * A) for a in MAP_X) and CAL.r5_v == MAP_Y
  assert CAL.key_clamp == round(1024 * A)
  assert CAL.kp_key_bp == tuple(round(a * A) for a in KP_X) and CAL.kp_v == tuple(16 * k for k in KP_Y)
  assert set(CAL.envelope_v) == {CAL.key_clamp}


def test_everything_but_kp_is_the_rdx_cars():
  for field in ("e4_per_output", "r5_key_bp", "r5_v", "key_clamp", "kff", "scale_q8", "r6_per_deg_s", "p_scale", "i_scale",
                "friction_width_v"):
    assert getattr(CAL, field) == getattr(RDX, field), field
  assert CAL.kp_v != RDX.kp_v


def _clarity_kp(a):  # the Clarity's P at the same E4, in THR's Kp units (>> 6 against / 1024)
  return np.interp(a * A, eps_cal.CLARITY_TRW_A020_P_KEYS, eps_cal.P_ROW_PMINUS5) / 16


def test_kp_is_the_clarity_rule_on_thrs_own_knots():
  clarity = _clarity_kp
  assert KP_Y == tuple(round(float(clarity(a))) for a in KP_X)
  a = np.arange(0, 1025)
  assert np.abs(np.interp(a, KP_X, KP_Y) - clarity(a)).max() < 0.65


def test_its_geometry_is_the_spec_constant_ratio_rack():
  linear, physical = sr.HONDA_VGR_INVERSE_BY_PROFILE[sr.HONDA_VGR_ODYSSEY_THR_A020]
  assert list(linear) == list(physical)
  assert CAL.r6_angle_gain is not None and set(CAL.r6_angle_gain) == {1.0}
  r0 = spec.spec_r0(spec.ODYSSEY_2018_SPEC, (linear, physical))
  assert r0 == pytest.approx(1.149 * 14.35, rel=1e-6)
  assert CAL.rack is not None
  assert CAL.rack.ratio_v[0] == pytest.approx(r0, abs=0.01) and CAL.rack.slip_factor < 0.0
  CP = _params(PTM_FW, CAR.HONDA_ODYSSEY)
  rack_map = honda_eps.get_rack_map(CP, CAL)
  assert rack_map is not None
  for v in (3.0, 15.0, 30.0):
    for angle in (-530.0, -200.0, -10.0, 4.0, 90.0, 500.0):
      assert rack_map.angle_from_curvature(rack_map.curvature_from_angle(angle, v, 0.01), v, 0.01) == pytest.approx(angle, abs=1e-3)


@pytest.mark.parametrize("output", [-1.0, -0.4, -0.05, 0.0, 0.02, 0.3, 0.9, 1.0])
def test_the_target_is_the_rdxs_at_every_output(output):
  r5 = eps_ff.r5_from_output(output, 15.0, CAL)
  assert eps_ff.r5_from_output(output, 15.0, RDX) == pytest.approx(r5)


def test_it_names_the_build_it_requires():
  assert eps_cal.REQUIRED_PTM_RWD["odyssey_thr_a020"] == "b89d20f0"
  assert eps_cal.provenance_summary(CAL)
