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


def test_crv_carries_its_own_clamp_axes_r6_and_load():
  cal = core.CRV_TLA_A040
  assert cal.key_clamp == 1774 and cal.e4_per_output == 4096.0
  assert cal.r5_key_bp == (0, 219, 443, 662, 887, 1108, 1330, 1552, 1663)
  assert cal.r6_per_deg_s == pytest.approx(-121.6051 * 1650 / 1450)
  assert FIRMWARE_CAR_TUNES["crv_tla_a040"].load == core.CRV_EPS_LOAD
  assert FIRMWARE_CAR_TUNES["crv_tla_a040"].p_scale == core.P_SCALE  # the Clarity's trims, not the Civic's
  # its clamp, not the Clarity's 1663, is what bounds the key
  assert core.key_ceiling(5., cal) == 1774. and core.key_ceiling(5., core.CLARITY_TRW_A020) == 1663.


@pytest.mark.parametrize("name", ["civic_bosch_c120", "civic_tgg_a120"])
def test_provisional_images_read_their_own_tables_but_carry_the_c020_r6_and_load(name):
  tune = FIRMWARE_CAR_TUNES[name]
  assert tune.calibration.r6_per_deg_s == core.CIVIC_BOSCH_C020.r6_per_deg_s
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

  from openpilot.nrdr.features.lateral.controller_selection import _PROFILES, TEG_PLACEHOLDER_PROFILE
  path = Path(__file__).resolve().parents[3] / "opendbc_repo/opendbc/sunnypilot/car/honda/interface_ext.py"
  assignment, = [node for node in ast.parse(path.read_text()).body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "_EXTENDED_TORQUE_LIMITS" for target in node.targets)]
  limits = {key.attr: value.value for key, value in zip(assignment.value.keys, assignment.value.values, strict=True)}
  for (fingerprint, _), profile in _PROFILES.items():
    if profile is TEG_PLACEHOLDER_PROFILE:
      continue  # the C020 placeholder predates this check (4096 map on the 3840 Nidec transport)
    assert FIRMWARE_CAR_TUNES[profile.calibration].calibration.e4_per_output == limits[fingerprint], (fingerprint, profile.name)


@pytest.mark.parametrize("name", NAMES)
def test_key_clamp_is_the_e4_the_firmware_stops_listening_at(name):
  # Read from the images: the command clamp word is 1663 (E4 3841 is the first to reach it) on every image but the
  # CR-V's, 1774 (E4 4097). Transport above that saturates in the firmware, which the key clamp models.
  cal = FIRMWARE_CAR_TUNES[name].calibration
  first_e4 = next(e4 for e4 in range(5000) if core.command_key(e4) >= cal.key_clamp)
  assert (cal.key_clamp, first_e4) in ((1663, 3841), (1774, 4097))
  assert (cal.key_clamp == 1774) == (name == "crv_tla_a040")


def test_insight_carries_its_own_measured_load_and_the_c020_r6():
  tune = FIRMWARE_CAR_TUNES["insight_txm_a040"]
  assert tune.load == core.INSIGHT_EPS_LOAD != core.CIVIC_EPS_LOAD
  assert tune.calibration.r6_per_deg_s == core.CIVIC_BOSCH_C020.r6_per_deg_s
  assert tune.calibration.r5_key_bp == (0, 111, 222, 333, 443, 665, 887, 1108, 1663)  # row 0 on every Insight image
  # lighter than the C020's column at speed, which the carried-over load over-asked
  assert abs(core.column_load(10., 0., 25., 0., coefficients=core.INSIGHT_EPS_LOAD)) < \
    abs(core.column_load(10., 0., 25., 0., coefficients=core.CIVIC_EPS_LOAD))
