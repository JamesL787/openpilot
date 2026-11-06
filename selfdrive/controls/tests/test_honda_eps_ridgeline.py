"""The Honda Ridgeline (39990-T6Z-A110 PTM rev b5): a V850 image steered through the Clarity's law, in its units."""
import math

import numpy as np
import pytest

import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.honda_eps_firmware_ff as eps_ff
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from opendbc.car.honda import steer_ratio as sr
from opendbc.car.honda.values import CAR, CarControllerParams, HondaFlags
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _Params, _params

REVB5_FW = b'39990-T6Z,A110\x00\x00'
CAL = eps_cal.RIDGELINE_T6Z_A110
# Read from 39990-T6Z,A110-REVB5.rwd decoded (RWD sha256 e7e2d909, image 5c578995), calset 0x1E5D2 (all five identical):
# the target map (+0x426, s16) and Kp (+0xA26, u8), indexed by j
TM = (
  0, 167, 333, 499, 664, 829, 992, 1155, 1318, 1480, 1641, 1802, 1962, 2122,
  2281, 2440, 2598, 2755, 2912, 3069, 3225, 3381, 3536, 3691, 3845, 3999, 4153, 4306,
  4458, 4611, 4763, 4914, 5065, 5216, 5366, 5516, 5665, 5813, 5960, 6107, 6254, 6401,
  6547, 6693, 6839, 6984, 7129, 7273, 7418, 7562, 7705, 7849, 7992, 8136, 8280, 8424,
  8567, 8710, 8853, 8996, 9138, 9281, 9422, 9564, 9706, 9847, 9988, 10129, 10269, 10410,
  10549, 10688, 10826, 10964, 11102, 11240, 11378, 11516, 11653, 11790, 11927, 12064, 12201, 12337,
  12473, 12610, 12746, 12882, 13017, 13153, 13288, 13423, 13559, 13694, 13828, 13963, 14098, 14232,
  14366, 14501, 14635, 14769, 14902, 15036, 15170, 15307, 15444, 15581, 15718, 15855, 15991, 16128,
  16264, 16401, 16537, 16673, 16809, 16945, 17081, 17217, 17352, 17488, 17623, 17759, 17894, 18029,
  18164, 18299, 18434, 18569, 18704, 18839, 18973, 19108, 19242, 19377, 19511, 19645, 19780, 19915,
  20055, 20194, 20333, 20472, 20612, 20751, 20890, 21029, 21168, 21307, 21446, 21584, 21723, 21862,
  22000, 22139, 22278, 22416, 22555, 22693, 22832, 22970, 23108, 23246, 23385, 23523, 23661, 23799,
  23937, 24075, 24213, 24351, 24489, 24626, 24766, 24905, 25045, 25184, 25324, 25463, 25603, 25742,
  25882, 26021, 26160, 26300, 26439, 26578, 26717, 26857, 26996, 27135, 27274, 27413, 27553, 27692,
  27831, 27970, 28109, 28248, 28387, 28526, 28665, 28803, 28942, 29081, 29220, 29359, 29498, 29638,
  29779, 29920, 30060, 30201, 30342, 30482, 30623, 30763, 30904, 31044, 31185, 31326, 31466, 31607,
  31747, 31888, 32028, 32169, 32309, 32450, 32590, 32731, 32767, 32767, 32767, 32767, 32767, 32767,
  32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767,
  32767, 32767, 32767, 32767,
)
KP = (
  12, 12, 12, 12, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 15, 15, 15, 15, 15, 15,
  15, 15, 15, 15, 16, 16, 16, 16, 16, 16, 16, 16, 16, 17, 17, 17, 17, 17, 17, 17, 17, 17, 17, 18, 18, 18, 18, 18, 18, 18, 18, 18,
  19, 19, 19, 19, 19, 19, 19, 19, 19, 20, 20, 20, 20, 20, 20, 20, 20, 20, 21, 21, 21, 21, 21, 21, 21, 21, 21, 21, 22, 22, 22, 22,
  22, 22, 22, 22, 22, 23, 23, 23, 23, 23, 23, 23, 23, 23, 23, 23, 23, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 25, 25,
  25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 25, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26, 26,
  26, 26, 26, 26, 26, 26, 26, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27,
  27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27,
  27, 27, 27, 27, 27, 27, 27, 27, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
)
P_CLAMP, KD, C7A, OUT_MUL = 942, 77, 2410, 0x28F


def _rnd(x, n):  # FUN_00033722: round half away from zero after >> n
  u = ((abs(int(x)) >> (n - 1)) + 1) >> 1
  return -u if x < 0 else u


def _j(e4):
  """The image's index for a command, hands off: FUN_00037568 (C7E 100), FUN_0003607a (x41, flat ceiling 256) and the
  target-stage fades (255 x 255 >> 8 = 254)."""
  fe25a = min(_rnd(abs(e4) * 100, 8), 0x7FF)
  return min(_rnd(254 * min(_rnd(fe25a * 41, 8), 256), 8), 255)


def _firmware(e4, fb):
  """The image's static LKAS output for a sent 0xE4 and a feedback fe232 (D left out, hands off)."""
  j = _j(e4)
  e = math.copysign(TM[j], e4) - fb
  p = max(min(_rnd(KP[j] * e, 10), P_CLAMP), -P_CLAMP)
  o = _rnd(p * 255 * 255, 16)
  return max(min(_rnd(o * OUT_MUL, 8), C7A), -C7A)


def test_revb5_gets_its_calibration_and_linear_geometry():
  CP = _params(REVB5_FW, CAR.HONDA_RIDGELINE)
  assert CP.flags & HondaFlags.EPS_MODIFIED and CP.flags & HondaFlags.VGR_RIDGELINE_T6Z_A110
  assert not CP.dashcamOnly
  assert list(CarControllerParams(CP).STEER_LOOKUP_V) == [-4096, 0, 4096]
  assert CP.lateralTuning.which() == "pid" and list(CP.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
  on = _Params({"HondaEpsController": "1"})
  assert honda_eps.eps_firmware_calibration(CP, on) is CAL
  assert honda_eps.eps_firmware_calibration(CP, _Params()) is None   # opt-in, like every car but the Clarity
  assert honda_eps.get_rack_map(CP, CAL) is not None
  assert eps_cal.select_eps_firmware_calibration("HONDA_PILOT", "39990-T6Z-A110") is None


def test_the_stock_ridgeline_is_untouched():
  CP = _params(b'39990-T6Z-A110\x00\x00', CAR.HONDA_RIDGELINE)
  assert not CP.flags & HondaFlags.EPS_MODIFIED
  assert list(CP.lateralTuning.pid.kpV) == pytest.approx([0.38])
  assert honda_eps.eps_firmware_calibration(CP, _Params({"HondaEpsController": "1"})) is None


def test_the_earlier_t6z_builds_keep_the_stock_tune():
  # rev b1-b4 and the PTM2045 build report 39990,T6Z,A110: none of them runs this law
  CP = _params(b'39990,T6Z,A110\x00\x00', CAR.HONDA_RIDGELINE)
  assert list(CP.lateralTuning.pid.kpV) == pytest.approx([0.38])
  assert honda_eps.eps_firmware_calibration(CP, _Params({"HondaEpsController": "1"})) is None


def test_the_tables_are_the_images():
  assert len(TM) == len(KP) == 256 and TM.index(32767) == 232
  # every 16th entry and the first saturated one, at the Clarity key of the smallest E4 that reaches it
  for j, k, r5 in zip([*range(0, 232, 16), 232], CAL.r5_key_bp, CAL.r5_v, strict=True):
    assert r5 == TM[j]
    assert k == eps_ff.command_key(next(e for e in range(4097) if _j(e) >= j))


@pytest.mark.parametrize("e4", list(range(0, 4097, 17)) + [3731, 3732, 4096])
def test_the_clarity_unit_target_is_the_images_at_every_command(e4):
  ours = abs(eps_ff.r5_from_output(-e4 / CAL.e4_per_output, 10.0, CAL))
  assert ours == pytest.approx(TM[_j(e4)], abs=260)   # one table step (~140 counts) plus the key's own rounding


@pytest.mark.parametrize("e4", list(range(0, 4097, 64)))
def test_the_clarity_unit_p_gain_is_the_images(e4):
  r5 = eps_ff.r5_from_output(-e4 / CAL.e4_per_output, 10.0, CAL)
  assert eps_ff.firmware_kp(r5, CAL) == pytest.approx(KP[_j(e4)], abs=1.0)


def test_the_law_reproduces_the_image_including_its_p_clamp():
  rng = np.random.default_rng(0)
  clamped = 0
  for _ in range(4000):
    e4 = int(rng.integers(-4096, 4097))
    rate = float(rng.uniform(-250, 250))
    fw = _firmware(e4, -128 * rate)
    # the controller's view: lateral output u = -E4 / 4096, R6 per published deg/s
    ours = eps_ff.firmware_output(eps_ff.r5_from_output(-e4 / CAL.e4_per_output, 10.0, CAL), rate, CAL)
    clamped += abs(fw) >= 2390
    tol = 0.035 * abs(fw) + 0.02 * C7A   # the interpolated target and Kp; integer rounding
    assert ours == pytest.approx(fw, abs=tol), (e4, rate)
  assert clamped > 100   # the P clamp was exercised


def test_a_load_past_the_p_clamp_asks_for_the_target_that_reaches_it():
  out_max = CAL.scale_q8 * P_CLAMP / 256
  assert out_max == pytest.approx(2391, abs=1) and out_max < C7A
  r5 = eps_ff.r5_for_motion(5000.0, 20.0, CAL)
  assert eps_ff.firmware_output(r5, 20.0, CAL) == pytest.approx(out_max, rel=1e-6)
  assert eps_ff.r5_for_motion(5000.0, 20.0, CAL) == pytest.approx(eps_ff.r5_for_motion(out_max, 20.0, CAL))
  # inside the clamp it is the plain inverse
  r5 = eps_ff.r5_for_motion(800.0, -15.0, CAL)
  assert eps_ff.firmware_output(r5, -15.0, CAL) == pytest.approx(800.0, rel=1e-6)


def test_the_integrator_stops_where_the_target_saturates():
  assert CAL.key_clamp == eps_ff.command_key(4096)
  assert CAL.output_ceiling() == pytest.approx(3732 / 4096, abs=0.002)


def test_its_feedback_is_the_x42_motor_speed():
  # fe232 = 32 x the 0x18F rate word; the word reads -4.00 per published deg/s from 10 deg to lock
  assert CAL.r6_per_deg_s == -128.0 and CAL.r6_angle_bp is None
  assert CAL.kff == 0.0 and CAL.p_clamp == P_CLAMP
  assert CAL.scale_q8 == pytest.approx(OUT_MUL * 255 * 255 / 65536)
  assert eps_cal.provenance(CAL)["r6"].startswith("firmware")


def test_its_geometry_is_linear_and_round_trips_to_lock():
  linear, physical = sr.HONDA_VGR_INVERSE_BY_PROFILE[sr.HONDA_VGR_RIDGELINE_T6Z_A110]
  assert list(linear) == list(physical)
  CP = _params(REVB5_FW, CAR.HONDA_RIDGELINE)
  rack_map = honda_eps.get_rack_map(CP, CAL)
  for v in (3.0, 15.0, 30.0):
    for angle in (-540.0, -200.0, -10.0, 4.0, 90.0, 500.0):
      assert rack_map.angle_from_curvature(rack_map.curvature_from_angle(angle, v, 0.01), v, 0.01) == pytest.approx(angle, abs=1e-3)


def test_it_names_the_build_it_requires():
  assert eps_cal.REQUIRED_PTM_RWD["ridgeline_t6z_a110"] == "e7e2d909"
