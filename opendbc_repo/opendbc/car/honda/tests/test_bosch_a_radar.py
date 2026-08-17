import math
import random

import pytest

from opendbc.can.dbc import DBC as DbcFile
from opendbc.can.parser import get_raw_value
from opendbc.car.can_definitions import CanData
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.radar_interface import (
  BOSCH_A_AUX_IDS,
  BOSCH_A_DBC_NAME,
  BOSCH_A_MAIN_IDS,
  BOSCH_A_NUM_SLOTS,
  _bosch_a_aux_id,
  _bosch_a_main_base,
  _bosch_a_ols_vrel,
)
from opendbc.car.honda.values import CAR
from openpilot.common.params import Params

# Tester toggle: CP is computed once at import time below (many helpers in this module close over
# it), which runs before any pytest fixture could -- so this has to be plain top-level code, not a
# fixture. teardown_module() restores it once every test in this file has run (mirrors
# gm/tests/test_gm.py's put_bool/finally pattern for params-gated _get_params behavior).
Params().put_bool("NrdrBoschARadar", True)


def teardown_module(module):
  Params().remove("NrdrBoschARadar")


CP = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC_BOSCH)
BUS = CanBus(CP).radar


# --- synthetic frame builders (inverse of the spec's raw-byte formulas) -----------------------------

def make_f0(frame_idx=0, status=0x7, range_raw=0, angle_raw=0):
  # inverse of raw_angle = (B4 << 3) | (B5 >> 5): B4 carries the top 8 bits, B5's top 3 bits carry the
  # bottom 3 bits of the 11-bit angle (the decoder ignores B5's low 5 bits entirely).
  B3 = (frame_idx & 0xF) | ((range_raw & 0xF) << 4)
  B2 = (range_raw >> 4) & 0xFF
  B1 = (status & 0xF) << 4
  B5 = (angle_raw & 0x7) << 5
  B4 = (angle_raw >> 3) & 0xFF
  return bytes([0, B1, B2, B3, B4, B5, 0, 0])


def make_f1(frame_idx=0):
  return bytes([0, 0, 0, (frame_idx & 0xF) << 1, 0, 0, 0, 0])


def make_f2(frame_idx=0, life=0):
  B1 = (frame_idx & 0xF) | ((life & 0xF) << 4)
  B0 = (life >> 4) & 0xFF
  return bytes([B0, B1, 0, 0, 0, 0, 0, 0])


def make_f3(frame_idx=0):
  return bytes([0, (frame_idx & 0xF) << 1, 0, 0, 0, 0, 0, 0])


def make_aux(frame_idx=0, rawc9=0, rawca=0):
  B1 = (frame_idx & 0xF) << 1
  B5 = (rawc9 & 0x3) << 6
  B4 = (rawc9 >> 2) & 0xFF
  B7 = (rawca & 0x3) << 6
  B6 = (rawca >> 2) & 0xFF
  return bytes([0, B1, 0, 0, B4, B5, B6, B7])


def make_radar_interface():
  return CarInterface.RadarInterface(CP)


def sweep(slot, frame_idx, status, range_raw, angle_raw, life, t_nanos, with_aux=False, aux_frame_idx=None,
          rawc9=0, rawca=0, extra_slots=()):
  """Build one update() input: a full main-frame set for `slot` (+ optional aux), plus the trigger
  frame (slot 15's f3) so update() always processes the cycle unless the caller is testing slot 15
  itself or an incomplete-frame scenario via extra_slots."""
  f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[slot]
  aux = BOSCH_A_AUX_IDS[slot]
  frames = [
    CanData(f0, make_f0(frame_idx, status, range_raw, angle_raw), BUS),
    CanData(f1, make_f1(frame_idx), BUS),
    CanData(f2, make_f2(frame_idx, life), BUS),
    CanData(f3, make_f3(frame_idx), BUS),
  ]
  if with_aux:
    frames.append(CanData(aux, make_aux(aux_frame_idx if aux_frame_idx is not None else frame_idx, rawc9, rawca), BUS))
  if slot != BOSCH_A_NUM_SLOTS - 1:
    _, _, _, trig_f3 = BOSCH_A_MAIN_IDS[BOSCH_A_NUM_SLOTS - 1]
    frames.append(CanData(trig_f3, make_f3(frame_idx), BUS))
  for extra in extra_slots:
    frames.append(extra)
  return [(t_nanos, frames)]


# --- 1. all 16 slot/frame ID mappings ---------------------------------------------------------------

def test_all_16_slot_main_ids():
  for slot in range(16):
    base = 0x280 + 4 * slot if slot < 4 else 0x2D0 + 4 * (slot - 4)
    assert _bosch_a_main_base(slot) == base
    assert BOSCH_A_MAIN_IDS[slot] == [base, base + 1, base + 2, base + 3]


def test_all_16_slot_aux_ids():
  expected = {
    0: 0x2C8, 1: 0x2C9, 2: 0x2CA, 3: 0x2CB, 4: 0x2CC, 5: 0x2CD, 6: 0x2CE, 7: 0x2CF,
    8: 0x290, 9: 0x291, 10: 0x292, 11: 0x293, 12: 0x294, 13: 0x295, 14: 0x296, 15: 0x297,
  }
  for slot, addr in expected.items():
    assert _bosch_a_aux_id(slot) == addr
    assert BOSCH_A_AUX_IDS[slot] == addr


def test_no_duplicate_can_ids_across_80_messages():
  all_ids = [addr for ids in BOSCH_A_MAIN_IDS for addr in ids] + BOSCH_A_AUX_IDS
  assert len(all_ids) == 80
  assert len(set(all_ids)) == 80


# --- 2. DBC bit geometry matches the spec's raw-byte formulas exactly (section 16) -------------------

class TestDbcBitGeometry:
  dbc = DbcFile(BOSCH_A_DBC_NAME)

  def test_f0_fields(self):
    msg = self.dbc.msgs[0x280]
    rng = random.Random(0)
    for _ in range(500):
      b = [rng.randint(0, 255) for _ in range(8)]
      dat = bytes(b)
      assert get_raw_value(dat, msg.sigs['STATUS']) == (b[1] >> 4) & 0x0F
      assert get_raw_value(dat, msg.sigs['FRAME_IDX']) == b[3] & 0x0F
      assert get_raw_value(dat, msg.sigs['RANGE_RAW']) == (b[2] << 4) | (b[3] >> 4)
      assert get_raw_value(dat, msg.sigs['AZIMUTH_RAW']) == (b[4] << 3) | (b[5] >> 5)

  def test_f1_frame_idx(self):
    msg = self.dbc.msgs[0x281]
    rng = random.Random(1)
    for _ in range(500):
      b = [rng.randint(0, 255) for _ in range(8)]
      assert get_raw_value(bytes(b), msg.sigs['FRAME_IDX']) == (b[3] >> 1) & 0x0F

  def test_f2_fields(self):
    msg = self.dbc.msgs[0x282]
    rng = random.Random(2)
    for _ in range(500):
      b = [rng.randint(0, 255) for _ in range(8)]
      dat = bytes(b)
      assert get_raw_value(dat, msg.sigs['FRAME_IDX']) == b[1] & 0x0F
      assert get_raw_value(dat, msg.sigs['LIFECYCLE_RAW']) == (b[0] << 4) | (b[1] >> 4)

  def test_f3_frame_idx(self):
    msg = self.dbc.msgs[0x283]
    rng = random.Random(3)
    for _ in range(500):
      b = [rng.randint(0, 255) for _ in range(8)]
      assert get_raw_value(bytes(b), msg.sigs['FRAME_IDX']) == (b[1] >> 1) & 0x0F

  def test_aux_fields(self):
    msg = self.dbc.msgs[0x2C8]
    rng = random.Random(4)
    for _ in range(500):
      b = [rng.randint(0, 255) for _ in range(8)]
      dat = bytes(b)
      assert get_raw_value(dat, msg.sigs['FRAME_IDX']) == (b[1] >> 1) & 0x0F
      assert get_raw_value(dat, msg.sigs['RAWC9_RAW']) == (b[4] << 2) | (b[5] >> 6)
      assert get_raw_value(dat, msg.sigs['RAWCA_RAW']) == (b[6] << 2) | (b[7] >> 6)


# --- 3. range / azimuth extraction + invalid sentinels ------------------------------------------------

class TestRangeAzimuth:
  def test_range_scale_and_offset(self):
    ri = make_radar_interface()
    raw_range = 1000
    rr = ri.update(sweep(0, 0, 0x7, raw_range, 1024, 1, 0))
    assert rr.points[0].dRel == pytest.approx(0.05712 * raw_range - 3.0)

  def test_range_invalid_sentinel_0xfff(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 0xFFF, 1024, 1, 0))
    assert len(rr.points) == 0

  def test_azimuth_invalid_sentinel_0x7ff(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 0x7FF, 1, 0))
    assert len(rr.points) == 0

  def test_yrel_sign_right_of_center_is_negative(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024 + 100, 1, 0))  # raw_angle > center -> right of center
    d = 0.05712 * 1000 - 3.0
    az_deg = 0.032 * 100
    expected_y = -d * math.sin(math.radians(az_deg))
    assert rr.points[0].yRel == pytest.approx(expected_y)
    assert rr.points[0].yRel < 0

  def test_yrel_sign_left_of_center_is_positive(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024 - 100, 1, 0))
    assert rr.points[0].yRel > 0

  def test_yrel_zero_on_boresight(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    assert rr.points[0].yRel == pytest.approx(0.0, abs=1e-9)


# --- 4. status / life invalid sentinels -> conservative object_valid ---------------------------------

class TestObjectValid:
  def test_status_invalid_0xf(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0xF, 1000, 1024, 1, 0))
    assert len(rr.points) == 0

  def test_life_invalid_0xfff(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 0xFFF, 0))
    assert len(rr.points) == 0

  def test_all_valid_emits_point(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    assert len(rr.points) == 1
    assert rr.points[0].measured is True
    assert math.isnan(rr.points[0].aRel)
    assert math.isnan(rr.points[0].yvRel)


# --- 5. lifecycle continuity ---------------------------------------------------------------------------

class TestLifecycle:
  def test_normal_plus_2_continuity_keeps_trackid(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    t0 = rr.points[0].trackId
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    assert rr.points[0].trackId == t0

  def test_continuity_across_dropped_sweeps(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    t0 = rr.points[0].trackId
    # 3 sweeps missed: frame_idx jumps from 0 to 4, life must jump by 2*4=8 to stay the same incarnation
    rr = ri.update(sweep(0, 4, 0x7, 1040, 1024, 9, 200_000_000))
    assert rr.points[0].trackId == t0

  def test_frame_idx_wraps_mod_16(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 14, 0x7, 1000, 1024, 1, 0))
    t0 = rr.points[0].trackId
    # frame_idx wraps 14 -> 1 (delta = (1-14)&0xF = 3), life must advance by 6
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 7, 150_000_000))
    assert rr.points[0].trackId == t0

  def test_life_wraps_mod_4096_stays_same_incarnation(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 14, 0x7, 1000, 1024, 4094, 0))
    t0 = rr.points[0].trackId
    # frame_idx 14 -> 0 (delta=2), life 4094 -> 2 ((2-4094)&0xFFF == 4 == 2*2)
    rr = ri.update(sweep(0, 0, 0x7, 1010, 1024, 2, 100_000_000))
    assert rr.points[0].trackId == t0

  def test_in_place_replacement_no_invalid_gap_gets_new_trackid(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    t0 = rr.points[0].trackId
    # frame_idx advances normally (+1) but life restarts at an unrelated odd value -> NOT +2*frame_delta
    rr = ri.update(sweep(0, 1, 0x7, 50, 1024, 5, 50_000_000))
    assert len(rr.points) == 1
    assert rr.points[0].trackId != t0

  def test_replacement_does_not_assume_life_restarts_at_1_3_5(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    t0 = rr.points[0].trackId
    # a "replacement" that happens to restart life at a big/even value must still be treated as a
    # replacement (not death) because it fails the frame/life identity, regardless of the new value's parity
    rr = ri.update(sweep(0, 1, 0x7, 50, 1024, 4000, 50_000_000))
    assert rr.points[0].trackId != t0
    assert len(rr.points) == 1

  def test_death_then_rebirth_gets_fresh_trackid(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    t0 = rr.points[0].trackId
    rr = ri.update(sweep(0, 1, 0xF, 1000, 1024, 3, 50_000_000))  # death
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 2, 0x7, 1000, 1024, 1, 100_000_000))  # rebirth
    assert len(rr.points) == 1
    assert rr.points[0].trackId != t0


# --- 6. trackId never reused, monotonically increasing ------------------------------------------------

def test_trackid_never_reused_across_many_births():
  ri = make_radar_interface()
  seen_ids = set()
  t = 0
  for i in range(10):
    rr = ri.update(sweep(0, i % 16, 0x7, 1000, 1024, 1, t))  # life=1 every time -> always a new incarnation after the first
    t += 50_000_000
    tid = rr.points[0].trackId
    assert tid not in seen_ids
    seen_ids.add(tid)
  assert seen_ids == set(range(10))


# --- 7. vRel derivative sign -------------------------------------------------------------------------

class TestVrel:
  def test_first_sighting_vrel_is_zero(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    assert rr.points[0].vRel == 0.0

  def test_decreasing_range_gives_negative_vrel(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 2000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1900, 1024, 3, 50_000_000))
    assert rr.points[0].vRel < 0

  def test_increasing_range_gives_positive_vrel(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1100, 1024, 3, 50_000_000))
    assert rr.points[0].vRel > 0

  def test_vrel_magnitude_two_sample(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1100, 1024, 3, 50_000_000))
    d1 = 0.05712 * 1000 - 3.0
    d2 = 0.05712 * 1100 - 3.0
    assert rr.points[0].vRel == pytest.approx((d2 - d1) / 0.05)

  def test_ols_helper_matches_closed_form_two_point(self):
    from collections import deque
    samples = deque([(0.0, 10.0), (0.1, 12.0)])
    assert _bosch_a_ols_vrel(samples) == pytest.approx(20.0)

  def test_ols_helper_three_point_linear(self):
    from collections import deque
    # perfectly linear d = 5 + 3*t -> slope must recover exactly 3.0
    samples = deque([(0.0, 5.0), (0.1, 5.3), (0.2, 5.6)])
    assert _bosch_a_ols_vrel(samples) == pytest.approx(3.0)

  def test_ols_helper_degenerate_dt_returns_zero(self):
    from collections import deque
    samples = deque([(0.0, 5.0), (0.0, 6.0)])
    assert _bosch_a_ols_vrel(samples) == 0.0

  def test_incarnation_does_not_carry_velocity_into_new_track(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 2000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1000, 1024, 3, 50_000_000))  # fast closing
    assert rr.points[0].vRel < -1000  # implausible-fast, but exercises the derivative
    # replacement: life breaks identity -> fresh incarnation, vRel must reset to first-sighting (0.0)
    rr = ri.update(sweep(0, 2, 0x7, 500, 1024, 99, 100_000_000))
    assert rr.points[0].vRel == 0.0


# --- 8. auxiliary tag join: enrichment only, never gates validity -------------------------------------

class TestAuxiliary:
  def test_aux_matching_cycle_is_attached(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True, aux_frame_idx=0, rawc9=123, rawca=456))
    st = ri._slots[0]
    assert st.aux_raw_c9 == 123
    assert st.aux_raw_ca == 456

  def test_aux_mismatched_cycle_not_attached_but_point_still_emitted(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True, aux_frame_idx=5, rawc9=123, rawca=456))
    assert len(rr.points) == 1  # point emitted regardless of aux mismatch
    st = ri._slots[0]
    assert math.isnan(st.aux_raw_c9) and math.isnan(st.aux_raw_ca)  # never attached

  def test_aux_absent_does_not_suppress_point(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=False))
    assert len(rr.points) == 1

  def test_aux_rawca_invalid_sentinel(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True, aux_frame_idx=0, rawc9=1, rawca=0x3FF))
    st = ri._slots[0]
    assert math.isnan(st.aux_raw_ca)


# --- 9. missing CAN frame within a cycle does not kill an existing point -------------------------------

def test_incomplete_main_frame_set_leaves_existing_point_untouched():
  ri = make_radar_interface()
  rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
  assert len(rr.points) == 1
  t0 = rr.points[0].trackId

  # Next cycle: only f0/f1/f2 arrive for slot 0 (f3 missing) -- still send the trigger so update() runs.
  f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[0]
  _, _, _, trig_f3 = BOSCH_A_MAIN_IDS[15]
  frames = [
    CanData(f0, make_f0(1, 0x7, 1000, 1024), BUS),
    CanData(f1, make_f1(1), BUS),
    CanData(f2, make_f2(1, 3), BUS),
    CanData(trig_f3, make_f3(1), BUS),
  ]
  rr = ri.update([(50_000_000, frames)])
  assert len(rr.points) == 1  # untouched, not dropped
  assert rr.points[0].trackId == t0


def test_incoherent_frame_index_across_main_frames_is_skipped():
  ri = make_radar_interface()
  rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
  t0 = rr.points[0].trackId

  f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[0]
  _, _, _, trig_f3 = BOSCH_A_MAIN_IDS[15]
  frames = [
    CanData(f0, make_f0(1, 0x7, 1000, 1024), BUS),
    CanData(f1, make_f1(1), BUS),
    CanData(f2, make_f2(2, 3), BUS),  # frame idx mismatch vs f0/f1
    CanData(f3, make_f3(1), BUS),
    CanData(trig_f3, make_f3(1), BUS),
  ]
  rr = ri.update([(50_000_000, frames)])
  assert len(rr.points) == 1  # unchanged from before, not re-derived, not dropped
  assert rr.points[0].trackId == t0


# --- 10. staleness gate -----------------------------------------------------------------------------

def test_stale_bus_clears_points_and_flags_temporary_unavailable():
  ri = make_radar_interface()
  rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
  assert len(rr.points) == 1

  # Advance the parser clock well past BOSCH_A_STALE_S with no trigger frame at all.
  f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[0]
  frames = [CanData(f0, make_f0(1, 0x7, 1000, 1024), BUS)]  # not a full/coherent set, and no trigger
  rr = ri.update([(300_000_000, frames)])  # +300ms, no trigger msg present
  assert rr is not None
  assert len(rr.points) == 0
  assert rr.errors.radarUnavailableTemporary is True


def test_no_can_data_returns_none_without_crash():
  ri = make_radar_interface()
  assert ri.update([]) is None


# --- misc integration: DBC wiring -------------------------------------------------------------------

def test_civic_bosch_radar_dbc_wired_and_available():
  assert CP.radarUnavailable is False
  ri = make_radar_interface()
  assert ri.bosch_a_radar is True
  assert ri.rcp is not None
