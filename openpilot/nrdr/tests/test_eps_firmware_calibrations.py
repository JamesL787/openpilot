"""Per-image firmware calibrations: well-formed tables, exact inversion, and what each car carries."""
import math

import numpy as np
import pytest

from openpilot.nrdr.features.lateral import vfn_eps_core as core
from openpilot.nrdr.features.lateral.vfn_eps_core import FIRMWARE_CAR_TUNES

NAMES = sorted(FIRMWARE_CAR_TUNES)


@pytest.mark.parametrize("name", NAMES)
def test_tables_are_well_formed(name):
  tune = FIRMWARE_CAR_TUNES[name]
  cal = tune.calibration
  assert len(cal.r5_key_bp) == len(cal.r5_v) == 9
  assert len(cal.kp_key_bp) == len(cal.kp_v) == 9
  assert len(cal.envelope_bp) == len(cal.envelope_v)
  for axis in (cal.r5_key_bp, cal.r5_v, cal.envelope_bp):
    assert all(b > a for a, b in zip(axis, axis[1:], strict=False))
  assert all(b > a for a, b in zip(cal.kp_key_bp, cal.kp_key_bp[1:], strict=False))
  assert cal.r5_v[0] == 0 and cal.r5_key_bp[0] == 0
  assert cal.key_clamp <= cal.envelope_v[0]
  assert cal.e4_per_output in (3840.0, 4096.0)
  assert cal.r6_per_deg_s < 0 and cal.scale_q8 == 256.0 and cal.kff == 45.0
  assert len(tune.load) == 6 and len(tune.p_scale) == len(tune.i_scale) == 3
  # the P rows are the P-minus-5 build's on every image
  assert tuple(cal.kp_v) == tuple(core.KP_V)
  # Kp pieces are continuous, so the quadratic inverse has a root on every piece boundary
  for (_, hi, *_), (lo2, *_) in zip(cal.kp_pieces, cal.kp_pieces[1:], strict=False):
    assert lo2 == pytest.approx(hi)
  assert all(kp > 0 for _, _, kp, _ in cal.kp_pieces)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("output", np.linspace(-.85, .85, 17))
def test_command_map_round_trips(name, output):
  cal = FIRMWARE_CAR_TUNES[name].calibration
  r5 = core.r5_from_output(output, 20., cal)
  assert core.output_from_r5(r5, cal) == pytest.approx(output, abs=.002)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("load,rate", [(500., 0.), (-1500., 0.), (800., 40.), (-800., -40.), (300., -60.), (-4000., 120.), (0., 0.)])
@pytest.mark.parametrize("guess", [0., 15000., -15000.])
def test_inversion_satisfies_the_images_firmware_law(name, load, rate, guess):
  cal = FIRMWARE_CAR_TUNES[name].calibration
  target = core.r5_for_motion(load, rate, guess, 0., cal)
  assert core.firmware_output(target, rate, 0., cal) == pytest.approx(load, abs=1e-6)


@pytest.mark.parametrize("name", NAMES)
def test_kp_pieces_reproduce_the_interpolation_over_the_command_key(name):
  cal = FIRMWARE_CAR_TUNES[name].calibration
  if cal.r5_per_key is not None:
    return
  for target in np.linspace(0., 35000., 350):
    key = np.interp(target, cal.r5_v, cal.r5_key_bp)
    assert core.firmware_kp(target, cal) == pytest.approx(np.interp(key, cal.kp_key_bp, cal.kp_v))


@pytest.mark.parametrize("name", NAMES)
def test_full_output_never_exceeds_the_rail_or_the_images_key_clamp(name):
  cal = FIRMWARE_CAR_TUNES[name].calibration
  for v in (0., 10., 30., 50.):
    assert core.key_ceiling(v, cal) <= cal.key_clamp
    assert math.isfinite(core.r5_from_output(1., v, cal))
    assert abs(core.r5_from_output(1., v, cal)) <= cal.r5_v[-1]


def test_clarity_is_unchanged_by_the_per_image_fields():
  cal = core.CLARITY_TRW_A020
  assert (cal.kp_key_bp, cal.kp_v, cal.key_clamp, cal.scale_q8, cal.kff) == (
    tuple(core.KP_KEY_BP), tuple(core.KP_V), core.KEY_CLAMP, core.SCALE_Q8, core.KFF)
  assert FIRMWARE_CAR_TUNES["clarity_trw_a020"].load == core.CLARITY_EPS_LOAD
  assert FIRMWARE_CAR_TUNES["clarity_trw_a020"].p_scale == core.P_SCALE


def test_teg_carries_its_own_measurements_and_the_nidec_transport():
  cal = core.CIVIC_TEG_A010
  assert cal.e4_per_output == 3840.0 and core.CIVIC_BOSCH_C020.e4_per_output == 4096.0
  # R6 from its own A table (C120 / A030 / TEG); the owner's -161 against 0x14A sits inside that curve
  assert cal.r6_per_deg_s == core.C120_R6_CENTRE and cal.r6_angle_gain == core.C120_R6_GAIN
  assert core.firmware_r6(1., 0., cal) > -161. > core.firmware_r6(1., 180., cal)
  assert FIRMWARE_CAR_TUNES["civic_teg_a010"].load == core.TEG_EPS_LOAD == (-9.205, -0.3252, -9.039, -550.7, -83.6, -3.185)
  # it shares the C020's command axes, P axis and envelope; the load and R6 are what differ
  assert cal.r5_key_bp == core.CIVIC_BOSCH_C020.r5_key_bp and cal.kp_key_bp == tuple(core.C020_P_KEYS)
  assert cal.envelope_v == core.CIVIC_BOSCH_C020.envelope_v
  # the column needs ~1.6x the C020's output for the same motion (measured against the route-294 C020 load)
  route_294_c020 = (-5.574, -.1831, -4.540, -326.5, -83.6, -3.185)
  assert core.column_load(30., 20., 8., 0., coefficients=core.TEG_EPS_LOAD) == pytest.approx(
    1.6 * core.column_load(30., 20., 8., 0., coefficients=route_294_c020), rel=.25)


def test_crv_carries_its_own_clamp_axes_r6_and_load():
  cal = core.CRV_TLA_A040
  assert cal.key_clamp == 1774 and cal.e4_per_output == 4096.0
  assert cal.r5_key_bp == (0, 219, 443, 662, 887, 1108, 1330, 1552, 1663)
  assert cal.r6_per_deg_s == core.CRV_R6_CENTRE and cal.r6_angle_gain == core.CRV_R6_GAIN
  # the owner's single V5 fit (-138.4 against 0x14A) sits inside the curve the A table gives
  assert core.firmware_r6(1., 0., cal) > -138.4 > core.firmware_r6(1., 180., cal)
  assert FIRMWARE_CAR_TUNES["crv_tla_a040"].load == core.CRV_EPS_LOAD
  assert FIRMWARE_CAR_TUNES["crv_tla_a040"].p_scale == core.P_SCALE  # the Clarity's trims, not the Civic's
  # its clamp, not the Clarity's 1663, is what bounds the key
  assert core.key_ceiling(5., cal) == 1774. and core.key_ceiling(5., core.CLARITY_TRW_A020) == 1663.


@pytest.mark.parametrize("name", ["civic_bosch_c120", "civic_tgg_a120"])
def test_provisional_images_read_their_own_tables_but_carry_the_c020_load(name):
  tune = FIRMWARE_CAR_TUNES[name]
  r6 = core.C120_R6_CENTRE if name == "civic_bosch_c120" else core.C020_R6_CENTRE  # own A table / shared with C020
  assert tune.calibration.r6_per_deg_s == r6 and tune.calibration.r6_angle_gain is not None
  assert tune.load == core.CIVIC_EPS_LOAD and tune.p_scale == core.CIVIC_P_SCALE
  assert tune.calibration.envelope_v == tuple(core.FLAT_ENVELOPE_V)


def test_each_images_command_axis_is_its_own():
  axes = {name: FIRMWARE_CAR_TUNES[name].calibration.r5_key_bp for name in NAMES}
  assert axes["civic_bosch_c120"] != axes["civic_tgg_a120"] != axes["civic_bosch_c020"]
  assert axes["civic_bosch_c120"][5] == 861 and axes["civic_tgg_a120"][5] == 862
  assert FIRMWARE_CAR_TUNES["civic_bosch_c120"].calibration.kp_key_bp == tuple(core.C120_P_KEYS)
  assert FIRMWARE_CAR_TUNES["insight_txm_a040"].calibration.key_clamp == 1663


def test_each_calibrations_transport_is_what_opendbc_sends_for_its_car():
  # E4 = -e4_per_output * u must equal the car's extended torque limit, or the inversion mis-scales every command.
  import ast
  from pathlib import Path

  from openpilot.nrdr.features.lateral.controller_selection import _PROFILES
  path = Path(__file__).resolve().parents[3] / "opendbc_repo/opendbc/sunnypilot/car/honda/interface_ext.py"
  assignment, = [node for node in ast.parse(path.read_text()).body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "_EXTENDED_TORQUE_LIMITS" for target in node.targets)]
  limits = {key.attr: value.value for key, value in zip(assignment.value.keys, assignment.value.values, strict=True)}
  for (fingerprint, _), profile in _PROFILES.items():
    assert FIRMWARE_CAR_TUNES[profile.calibration].calibration.e4_per_output == limits[fingerprint], (fingerprint, profile.name)


@pytest.mark.parametrize("name", NAMES)
def test_key_clamp_is_the_e4_the_firmware_stops_listening_at(name):
  # Read from the images: the command clamp word is 1663 (E4 3841 is the first to reach it) on every image but the
  # CR-V's, 1774 (E4 4097). Transport above that saturates in the firmware, which the key clamp models.
  cal = FIRMWARE_CAR_TUNES[name].calibration
  first_e4 = next(e4 for e4 in range(5000) if core.command_key(e4) >= cal.key_clamp)
  assert (cal.key_clamp, first_e4) in ((1663, 3841), (1774, 4097))
  assert (cal.key_clamp == 1774) == (name == "crv_tla_a040")


def test_insight_carries_its_own_measured_load_and_r6_from_its_a_table():
  tune = FIRMWARE_CAR_TUNES["insight_txm_a040"]
  assert tune.load == core.INSIGHT_EPS_LOAD != core.CIVIC_EPS_LOAD
  assert tune.calibration.r6_per_deg_s == core.INSIGHT_R6_CENTRE and tune.calibration.r6_angle_gain == core.INSIGHT_R6_GAIN
  assert tune.calibration.r5_key_bp == (0, 111, 222, 333, 443, 665, 887, 1108, 1663)  # row 0 on every Insight image
  # lighter than the C020's column at speed, which the carried-over load over-asked
  assert abs(core.column_load(10., 0., 25., 0., coefficients=core.INSIGHT_EPS_LOAD)) < \
    abs(core.column_load(10., 0., 25., 0., coefficients=core.CIVIC_EPS_LOAD))


@pytest.mark.parametrize("name", NAMES)
def test_every_image_has_angle_dependent_r6(name):
  # R6 is the pre-table column rate; per published deg/s it grows with the A table's slope on every image
  cal = FIRMWARE_CAR_TUNES[name].calibration
  assert cal.r6_angle_bp is not None and cal.r6_angle_gain[0] == 1.0
  assert core.firmware_r6(1., 180., cal) < core.firmware_r6(1., 0., cal) < 0.
  assert core.firmware_r6(1., -180., cal) == core.firmware_r6(1., 180., cal)


@pytest.mark.parametrize("band, measured", [(7.5, -153.2), (22.5, -152.2), (45., -155.), (80., -162.2), (125., -167.4),
                                            (175., -168.9), (250., -168.9)])
def test_c020_r6_is_its_measured_curve(band, measured):
  # 0.1 s derivative of the published angle against 0x6A2 R6, routes 64/154/287/289/294
  assert core.firmware_r6(1., band, core.CIVIC_BOSCH_C020) == pytest.approx(measured, rel=.01)


def test_a_table_r6_centres_scale_from_the_clarity_by_the_centre_divisor():
  # -122 x divisor / 16384; the C020's measured centre (-153.2) lands within 0.4% of its -153.7
  assert core.R6_PER_CENTRE_DEG_S * 20647 / 16384 == pytest.approx(core.C020_R6_CENTRE, rel=.005)
  for centre, divisor in ((core.C120_R6_CENTRE, 20972), (core.INSIGHT_R6_CENTRE, 17613), (core.CRV_R6_CENTRE, 16783)):
    assert centre == pytest.approx(core.R6_PER_CENTRE_DEG_S * divisor / 16384, abs=.01)
