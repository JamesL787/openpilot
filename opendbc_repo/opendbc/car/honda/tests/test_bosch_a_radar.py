import math
import random

import pytest

from opendbc.can.dbc import DBC as DbcFile
from opendbc.can.parser import get_raw_value
from opendbc.car.can_definitions import CanData
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.radar_interface import (
  BOSCH_A_AZIMUTH_SCALE_RAD,
  BOSCH_A_AUX_IDS,
  BOSCH_A_DBC_NAME,
  BOSCH_A_DIRECT_VREL_INVALID,
  BOSCH_A_DIRECT_VREL_MAX_RAW,
  BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW,
  BOSCH_A_FREQ_HZ,
  BOSCH_A_MAIN_IDS,
  BOSCH_A_NUM_SLOTS,
  BOSCH_A_RANGE_SCALE_M,
  BOSCH_A_STALE_S,
  BOSCH_A_SWEEP_END_MSG,
  BOSCH_A_TRIGGER_MSG,
  _bosch_a_aux_id,
  _bosch_a_direct_vrel,
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
BUS = CanBus(CP).camera


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


def make_f3(frame_idx=0, edge_a_raw=0, edge_b_raw=0, sigma_a_raw=0, track_id=0xFF):
  B0 = (edge_a_raw >> 3) & 0xFF
  B1 = ((edge_a_raw & 0x7) << 5) | ((frame_idx & 0xF) << 1)
  B2 = (edge_b_raw >> 3) & 0xFF
  B3 = (edge_b_raw & 0x7) << 5
  B4 = (sigma_a_raw >> 2) & 0xFF
  B5 = (sigma_a_raw & 0x3) << 6
  return bytes([B0, B1, B2, B3, B4, B5, track_id & 0xFF, 0])


def make_aux(frame_idx=0, rawc9=0, rawca=0, direct_vrel_raw=BOSCH_A_DIRECT_VREL_INVALID,
             direct_vrel_uncertainty_raw=0x3FF):
  B0 = (direct_vrel_raw >> 3) & 0xFF
  B1 = ((direct_vrel_raw & 0x7) << 5) | ((frame_idx & 0xF) << 1)
  B2 = (direct_vrel_uncertainty_raw >> 2) & 0xFF
  B3 = (direct_vrel_uncertainty_raw & 0x3) << 6
  B5 = (rawc9 & 0x3) << 6
  B4 = (rawc9 >> 2) & 0xFF
  B7 = (rawca & 0x3) << 6
  B6 = (rawca >> 2) & 0xFF
  return bytes([B0, B1, B2, B3, B4, B5, B6, B7])


def make_main_frames(slot, frame_idx, status, range_raw, angle_raw, life, track_id=1):
  f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[slot]
  return [
    CanData(f0, make_f0(frame_idx, status, range_raw, angle_raw), BUS),
    CanData(f1, make_f1(frame_idx), BUS),
    CanData(f2, make_f2(frame_idx, life), BUS),
    CanData(f3, make_f3(frame_idx, track_id=track_id), BUS),
  ]


def make_radar_interface():
  return CarInterface.RadarInterface(CP)


def sweep(slot, frame_idx, status, range_raw, angle_raw, life, t_nanos, with_aux=False, aux_frame_idx=None,
          rawc9=0, rawca=0, extra_slots=(), track_id=1, direct_vrel_raw=BOSCH_A_DIRECT_VREL_INVALID,
          direct_vrel_uncertainty_raw=0x3FF):
  """Build one update() input: a full main-frame set for `slot` (+ optional aux), plus the trigger
  frame (slot 15's f3) so update() always processes the cycle unless the caller is testing slot 15
  itself or an incomplete-frame scenario via extra_slots."""
  f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[slot]
  aux = BOSCH_A_AUX_IDS[slot]
  frames = make_main_frames(slot, frame_idx, status, range_raw, angle_raw, life, track_id)
  if with_aux:
    frames.append(CanData(aux, make_aux(aux_frame_idx if aux_frame_idx is not None else frame_idx, rawc9, rawca,
                                        direct_vrel_raw, direct_vrel_uncertainty_raw), BUS))
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

  def test_f3_fields(self):
    msg = self.dbc.msgs[0x283]
    rng = random.Random(3)
    for _ in range(500):
      b = [rng.randint(0, 255) for _ in range(8)]
      dat = bytes(b)
      assert get_raw_value(dat, msg.sigs['AZIMUTH_EDGE_A_RAW']) == (b[0] << 3) | (b[1] >> 5)
      assert get_raw_value(dat, msg.sigs['FRAME_IDX']) == (b[1] >> 1) & 0x0F
      assert get_raw_value(dat, msg.sigs['AZIMUTH_EDGE_B_RAW']) == (b[2] << 3) | (b[3] >> 5)
      assert get_raw_value(dat, msg.sigs['AZIMUTH_EDGE_SIGMA_A_RAW']) == (b[4] << 2) | (b[5] >> 6)

  def test_track_id_is_f3_byte6_and_does_not_overlap_existing_fields(self):
    def affected_bits(signal):
      bits = set()
      for byte in range(8):
        for bit in range(8):
          data = bytearray(8)
          data[byte] = 1 << bit
          if get_raw_value(bytes(data), signal) != 0:
            bits.add((byte, bit))
      return bits

    expected_bits = {(6, bit) for bit in range(8)}
    f3_ids = [BOSCH_A_MAIN_IDS[slot][3] for slot in range(BOSCH_A_NUM_SLOTS)]
    for message_id in f3_ids:
      msg = self.dbc.msgs[message_id]
      track_id = msg.sigs['TRACK_ID']
      assert track_id.start_bit == 55
      assert track_id.size == 8
      assert track_id.is_little_endian is False
      assert affected_bits(track_id) == expected_bits

      existing_bits = set()
      for name, signal in msg.sigs.items():
        if name != 'TRACK_ID':
          existing_bits |= affected_bits(signal)
      assert not existing_bits & expected_bits

    rng = random.Random(33)
    msg = self.dbc.msgs[BOSCH_A_MAIN_IDS[0][3]]
    for _ in range(500):
      data = bytes(rng.randint(0, 255) for _ in range(8))
      assert get_raw_value(data, msg.sigs['TRACK_ID']) == data[6]

  def test_aux_fields(self):
    msg = self.dbc.msgs[0x2C8]
    rng = random.Random(4)
    for _ in range(500):
      b = [rng.randint(0, 255) for _ in range(8)]
      dat = bytes(b)
      assert get_raw_value(dat, msg.sigs['FRAME_IDX']) == (b[1] >> 1) & 0x0F
      assert get_raw_value(dat, msg.sigs['REL_VELOCITY_RAW']) == (b[0] << 3) | (b[1] >> 5)
      assert get_raw_value(dat, msg.sigs['REL_VELOCITY_UNCERTAINTY_RAW']) == (b[2] << 2) | (b[3] >> 6)
      assert get_raw_value(dat, msg.sigs['FW_LID_00C9_RAW']) == (b[4] << 2) | (b[5] >> 6)
      assert get_raw_value(dat, msg.sigs['FW_LID_00CA_RAW']) == (b[6] << 2) | (b[7] >> 6)

  def test_descriptor_backed_raw_fields_cover_all_unmapped_main_bits(self):
    f0_ids = [
      ['25', '26', '28', '29'], ['34', '35', '37', '38'], ['43', '44', '46', '47'],
      ['52', '53', '55', '56'], ['61', '62', '64', '65'], ['70', '71', '73', '74'],
      ['7F', '80', '82', '83'], ['8E', '8F', '91', '92'], ['9D', '9E', 'A0', 'A1'],
      ['AC', 'AD', 'AF', 'B0'], ['BB', 'BC', 'BE', 'BF'], ['CA', 'CB', 'CD', 'CE'],
      ['D9', 'DA', 'DC', 'DD'], ['E8', 'E9', 'EB', 'EC'], ['F7', 'F8', 'FA', 'FB'],
      ['06', '07', '09', '0A'],
    ]
    f1_ids = [
      ['2B', '18', '2C', '19', '2D'], ['3A', '23', '3B', '24', '3C'], ['49', '2E', '4A', '2F', '4B'],
      ['58', '39', '59', '3A', '5A'], ['67', '44', '68', '45', '69'], ['76', '4F', '77', '50', '78'],
      ['85', '5A', '86', '5B', '87'], ['94', '65', '95', '66', '96'], ['A3', '70', 'A4', '71', 'A5'],
      ['B2', '7B', 'B3', '7C', 'B4'], ['C1', '86', 'C2', '87', 'C3'], ['D0', '91', 'D1', '92', 'D2'],
      ['DF', '9C', 'E0', '9D', 'E1'], ['EE', 'A7', 'EF', 'A8', 'F0'], ['FD', 'B2', 'FE', 'B3', 'FF'],
      ['0C', 'BD', '0D', 'BE', '0E'],
    ]
    f2_ids = [
      ['2F', '1A', '30', '1B', '1C'], ['3E', '25', '3F', '26', '27'], ['4D', '30', '4E', '31', '32'],
      ['5C', '3B', '5D', '3C', '3D'], ['6B', '46', '6C', '47', '48'], ['7A', '51', '7B', '52', '53'],
      ['89', '5C', '8A', '5D', '5E'], ['98', '67', '99', '68', '69'], ['A7', '72', 'A8', '73', '74'],
      ['B6', '7D', 'B7', '7E', '7F'], ['C5', '88', 'C6', '89', '8A'], ['D4', '93', 'D5', '94', '95'],
      ['E3', '9E', 'E4', '9F', 'A0'], ['F2', 'A9', 'F3', 'AA', 'AB'], ['01', 'B4', '02', 'B5', 'B6'],
      ['10', 'BF', '11', 'C0', 'C1'],
    ]
    positions = {
      'F0': [(44, 4), (11, 2), (7, 7), (55, 8)],
      'F1': [(46, 7), (23, 11), (15, 8), (39, 9), (7, 6)],
      'F2': [(29, 1), (23, 10), (46, 7), (39, 9), (55, 9)],
    }
    ids_by_frame = {'F0': f0_ids, 'F1': f1_ids, 'F2': f2_ids}
    for slot in range(BOSCH_A_NUM_SLOTS):
      for frame in ('F0', 'F1', 'F2'):
        msg = self.dbc.msgs[BOSCH_A_MAIN_IDS[slot][int(frame[-1])]]
        for logical_id, (start_bit, size) in zip(ids_by_frame[frame][slot], positions[frame], strict=True):
          signal = msg.sigs[f'FW_LID_{logical_id}_RAW']
          assert signal.start_bit == start_bit
          assert signal.size == size
          assert signal.is_little_endian is False

        def affected_bits(signal):
          bits = set()
          for byte in range(8):
            for bit in range(8):
              data = bytearray(8)
              data[byte] = 1 << bit
              if get_raw_value(bytes(data), signal) != 0:
                bits.add((byte, bit))
          return bits

        fields = [msg.sigs[f'FW_LID_{logical_id}_RAW'] for logical_id in ids_by_frame[frame][slot]]
        covered = set()
        for signal in fields:
          bits = affected_bits(signal)
          assert not covered & bits
          covered |= bits

        existing_bits = set()
        for name, signal in msg.sigs.items():
          if not name.startswith('FW_LID_'):
            existing_bits |= affected_bits(signal)
        assert not existing_bits & covered


# --- 3. range / azimuth extraction + invalid sentinels ------------------------------------------------

class TestRangeAzimuth:
  def test_range_scale_and_offset(self):
    ri = make_radar_interface()
    raw_range = 1000
    ri.update(sweep(0, 0, 0x7, raw_range, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, raw_range, 1024, 3, 50_000_000))
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
    ri.update(sweep(0, 0, 0x7, 1000, 1024 + 100, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1000, 1024 + 100, 3, 50_000_000))  # raw_angle > center -> right of center
    d = 0.05712 * 1000 - 3.0
    expected_y = -d * math.tan(100.0 / 2048.0)
    assert rr.points[0].yRel == pytest.approx(expected_y)
    assert rr.points[0].yRel < 0

  def test_yrel_sign_left_of_center_is_positive(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024 - 100, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1000, 1024 - 100, 3, 50_000_000))
    assert rr.points[0].yRel > 0

  def test_yrel_zero_on_boresight(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1000, 1024, 3, 50_000_000))
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

  def test_first_valid_sample_is_withheld(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    assert len(rr.points) == 0

  def test_invalid_observation_does_not_mature_or_preserve_birth_history(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 1, 0xF, 1000, 1024, 3, 50_000_000))
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 2, 0x7, 1000, 1024, 1, 100_000_000))
    assert len(rr.points) == 0

  def test_incomplete_observation_does_not_mature_or_add_history(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    assert len(rr.points) == 0

    f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[0]
    _, _, _, trig_f3 = BOSCH_A_MAIN_IDS[15]
    frames = [
      CanData(f0, make_f0(1, 0x7, 1010, 1024), BUS),
      CanData(f1, make_f1(1), BUS),
      CanData(f2, make_f2(1, 3), BUS),
      CanData(trig_f3, make_f3(1), BUS),
    ]
    rr = ri.update([(50_000_000, frames)])
    assert len(rr.points) == 0

    rr = ri.update(sweep(0, 2, 0x7, 1020, 1024, 5, 100_000_000))
    assert len(rr.points) == 1
    assert math.isfinite(rr.points[0].vRel)

  def test_second_same_incarnation_sample_emits_finite_derivative(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    assert len(rr.points) == 1
    assert math.isfinite(rr.points[0].vRel)
    assert rr.points[0].measured is True
    assert math.isnan(rr.points[0].aRel)
    assert math.isnan(rr.points[0].yvRel)


# --- 5. lifecycle continuity ---------------------------------------------------------------------------

class TestLifecycle:
  def test_normal_plus_2_continuity_keeps_trackid(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    t0 = rr.points[0].trackId
    rr = ri.update(sweep(0, 2, 0x7, 1020, 1024, 5, 100_000_000))
    assert rr.points[0].trackId == t0

  def test_continuity_across_dropped_sweeps(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    t0 = rr.points[0].trackId
    # 3 sweeps missed: frame_idx jumps from 0 to 4, life must jump by 2*4=8 to stay the same incarnation
    rr = ri.update(sweep(0, 4, 0x7, 1040, 1024, 9, 200_000_000))
    assert rr.points[0].trackId == t0

  def test_frame_idx_wraps_mod_16(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 14, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 15, 0x7, 1005, 1024, 3, 50_000_000))
    t0 = rr.points[0].trackId
    # frame_idx wraps 14 -> 1 (delta = (1-14)&0xF = 3), life must advance by 6
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 7, 150_000_000))
    assert rr.points[0].trackId == t0

  def test_life_wraps_mod_4096_stays_same_incarnation(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 14, 0x7, 1000, 1024, 4094, 0))
    rr = ri.update(sweep(0, 15, 0x7, 1005, 1024, 0, 50_000_000))
    t0 = rr.points[0].trackId
    # frame_idx 14 -> 0 (delta=2), life 4094 -> 2 ((2-4094)&0xFFF == 4 == 2*2)
    rr = ri.update(sweep(0, 0, 0x7, 1010, 1024, 2, 100_000_000))
    assert rr.points[0].trackId == t0

  def test_in_place_replacement_no_invalid_gap_resets_history_but_keeps_can_id(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    t0 = rr.points[0].trackId
    # frame_idx advances normally (+1) but life jumps by an unrelated odd amount -> NOT +2*frame_delta
    rr = ri.update(sweep(0, 2, 0x7, 50, 1024, 7, 100_000_000))
    assert len(rr.points) == 0  # replacement birth sample is withheld
    rr = ri.update(sweep(0, 3, 0x7, 50, 1024, 9, 150_000_000))
    assert len(rr.points) == 1
    assert rr.points[0].trackId == t0

  def test_replacement_does_not_assume_life_restarts_at_1_3_5(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    t0 = rr.points[0].trackId
    # a "replacement" that happens to restart life at a big/even value must still be treated as a
    # replacement (not death) because it fails the frame/life identity, regardless of the new value's parity
    rr = ri.update(sweep(0, 2, 0x7, 50, 1024, 4000, 100_000_000))
    assert len(rr.points) == 0  # replacement birth sample is withheld
    rr = ri.update(sweep(0, 3, 0x7, 50, 1024, 4002, 150_000_000))
    assert rr.points[0].trackId == t0
    assert rr.points[0].vRel == 0.0
    assert len(rr.points) == 1

  def test_death_then_rebirth_reuses_can_id_with_clean_history(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    t0 = rr.points[0].trackId
    rr = ri.update(sweep(0, 1, 0xF, 1000, 1024, 3, 50_000_000))  # death
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 2, 0x7, 1000, 1024, 1, 100_000_000))  # rebirth, first sample withheld
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 3, 0x7, 1000, 1024, 3, 150_000_000))
    assert len(rr.points) == 1
    assert rr.points[0].trackId == t0


# --- 6. CAN track identity is the RadarPoint identity -----------------------------------------------

def test_trackid_comes_from_can_and_is_not_synthetic():
  ri = make_radar_interface()
  seen_ids = set()
  t = 0
  for i in range(10):
    frame_idx = (2 * i) % 16
    can_track_id = i + 1
    ri.update(sweep(0, frame_idx, 0x7, 1000, 1024, 1, t, track_id=can_track_id))
    t += 50_000_000
    rr = ri.update(sweep(0, (frame_idx + 1) % 16, 0x7, 1000, 1024, 3, t, track_id=can_track_id))
    t += 50_000_000
    assert can_track_id in {point.trackId for point in rr.points}
    seen_ids.add(can_track_id)
  assert seen_ids == set(range(1, 11))


# --- 7. vRel derivative sign -------------------------------------------------------------------------

class TestVrel:
  def test_direct_aux_vrel_is_preferred_over_ols(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True,
                    direct_vrel_raw=800, direct_vrel_uncertainty_raw=80))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000, with_aux=True,
                         direct_vrel_raw=800, direct_vrel_uncertainty_raw=80))
    assert rr.points[0].vRel == pytest.approx((800 - 864) / 64.0)

  def test_direct_aux_vrel_domain_and_sentinel(self):
    assert _bosch_a_direct_vrel(0) == pytest.approx(-13.5)
    assert _bosch_a_direct_vrel(BOSCH_A_DIRECT_VREL_MAX_RAW) == pytest.approx(13.5)
    assert _bosch_a_direct_vrel(1729) is None
    assert _bosch_a_direct_vrel(BOSCH_A_DIRECT_VREL_INVALID) is None
    assert _bosch_a_direct_vrel(0x7FF) is None
    assert _bosch_a_direct_vrel(None) is None
    assert _bosch_a_direct_vrel(0, BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW) == pytest.approx(-13.5)
    assert _bosch_a_direct_vrel(0, BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW + 1) is None
    assert _bosch_a_direct_vrel(864, 0x3FE) is None
    assert _bosch_a_direct_vrel(864, 0x3FF) is None

  def test_high_aux_uncertainty_falls_back_to_ols(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=False))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000, with_aux=True,
                         direct_vrel_raw=0, direct_vrel_uncertainty_raw=1023))
    # The raw U11 value would decode to -13.5 m/s, but u10=1023 is a saturated/high-uncertainty
    # candidate.  The valid adjacent range change remains usable through the OLS fallback.
    assert rr.points[0].vRel == pytest.approx((10 * (BOSCH_A_RANGE_SCALE_M)) / 0.05)
    assert rr.points[0].vRel != pytest.approx(-13.5)

  def test_interior_high_uncertainty_aux_does_not_rescue_ols_outlier(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 2000, 1024, 1, 0, with_aux=False))
    ri.update(sweep(0, 1, 0x7, 1945, 1024, 3, 70_000_000, with_aux=False))
    rr = ri.update(sweep(0, 2, 0x7, 1889, 1024, 5, 140_000_000, with_aux=True,
                         direct_vrel_raw=554, direct_vrel_uncertainty_raw=437))
    # The range slope is intentionally an OLS outlier. U11 is interior, but U10 says the native
    # candidate is too uncertain to authorize. Neither untrusted velocity may be published.
    assert len(rr.points) == 0
    assert len(ri._tracks[1].samples) == 1

  def test_first_sighting_vrel_is_zero(self):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    assert len(rr.points) == 0

  def test_decreasing_range_gives_negative_vrel(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 2000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1990, 1024, 3, 50_000_000))
    assert rr.points[0].vRel < 0

  def test_increasing_range_gives_positive_vrel(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    assert rr.points[0].vRel > 0

  def test_vrel_magnitude_two_sample(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
    d1 = 0.05712 * 1000 - 3.0
    d2 = 0.05712 * 1010 - 3.0
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

  def test_incarnation_does_not_carry_velocity_across_lifecycle_break(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 2000, 1024, 1, 0))
    rr = ri.update(sweep(0, 1, 0x7, 1990, 1024, 3, 50_000_000))
    assert rr.points[0].vRel < 0
    # replacement: life breaks identity -> fresh incarnation; its first sample is withheld.
    rr = ri.update(sweep(0, 2, 0x7, 500, 1024, 99, 100_000_000))
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 3, 0x7, 500, 1024, 101, 150_000_000))
    assert rr.points[0].vRel == 0.0

  def test_discontinuous_range_is_not_published_as_a_native_velocity_observation(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True, direct_vrel_raw=864))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000, with_aux=True, direct_vrel_raw=864))
    assert len(rr.points) == 1
    rr = ri.update(sweep(0, 2, 0x7, 100, 1024, 5, 100_000_000, with_aux=True, direct_vrel_raw=864))
    assert len(rr.points) == 0
    assert len(ri._tracks[1].samples) == 2


# --- 8. auxiliary tag join: enrichment only, never gates validity -------------------------------------

class TestAuxiliary:
  def test_aux_matching_cycle_is_attached(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True, aux_frame_idx=0, rawc9=123, rawca=456))
    st = ri._slots[0]
    assert st.logical_00c9_raw == 123
    assert st.logical_00ca_raw == 456

  def test_aux_mismatched_cycle_not_attached_but_point_still_emitted(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True, aux_frame_idx=5, rawc9=123, rawca=456))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000, with_aux=True, aux_frame_idx=5, rawc9=123, rawca=456))
    assert len(rr.points) == 1  # point emitted regardless of aux mismatch
    st = ri._slots[0]
    assert math.isnan(st.logical_00c9_raw) and math.isnan(st.logical_00ca_raw)  # never attached

  def test_aux_absent_does_not_suppress_point(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=False))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000, with_aux=False))
    assert len(rr.points) == 1

  def test_aux_param_invalid_sentinel(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True, aux_frame_idx=0, rawc9=1, rawca=0x3FF))
    st = ri._slots[0]
    assert st.logical_00c9_raw == 1
    assert math.isnan(st.logical_00ca_raw)

  def test_sigma_does_not_share_aux_param_invalid_sentinel(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, with_aux=True,
                    aux_frame_idx=0, rawc9=0x3FF, rawca=500))
    st = ri._slots[0]
    assert st.logical_00c9_raw == 0x3FF
    assert st.logical_00ca_raw == 500


# --- 9. missing CAN frame within a cycle does not kill an existing point -------------------------------

def test_incomplete_main_frame_set_leaves_existing_point_untouched():
  ri = make_radar_interface()
  ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
  rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
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
  ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
  rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
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
  ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
  rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000))
  assert len(rr.points) == 1

  # Advance the parser clock well past BOSCH_A_STALE_S with no trigger frame at all.
  f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[0]
  frames = [CanData(f0, make_f0(1, 0x7, 1000, 1024), BUS)]  # not a full/coherent set, and no trigger
  rr = ri.update([(300_000_000, frames)])  # +300ms, no trigger msg present
  assert rr is not None
  assert len(rr.points) == 0
  assert rr.errors.radarUnavailableTemporary is True


def test_stale_bus_clears_pending_birth_history_before_maturity():
  ri = make_radar_interface()
  rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0))
  assert len(rr.points) == 0
  assert len(ri._tracks[1].samples) == 1

  # The birth has started, but no RadarPoint exists yet. A silent bus must still clear the pending
  # lifecycle/history state rather than allowing it to survive indefinitely.
  f0, _, _, _ = BOSCH_A_MAIN_IDS[0]
  rr = ri.update([(300_000_000, [CanData(f0, make_f0(1, 0x7, 1000, 1024), BUS)])])
  assert rr is not None
  assert len(rr.points) == 0
  assert rr.errors.radarUnavailableTemporary is True
  assert not ri._tracks


# --- 11. persistent CAN identity is separate from wire-slot assembly -------------------------------

class TestPersistentCanIdentity:
  def test_same_slot_same_can_identity_is_stable(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, track_id=42))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000, track_id=42))
    assert len(rr.points) == 1
    assert rr.points[0].trackId == 42
    assert set(ri._tracks) == {42}

  def test_slot_migration_preserves_identity_and_ols_history(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, track_id=23))
    rr = ri.update(sweep(1, 1, 0x7, 1010, 1024, 3, 50_000_000, track_id=23))
    assert len(rr.points) == 1
    assert rr.points[0].trackId == 23
    assert len(ri._tracks[23].samples) == 2
    assert ri._tracks[23].wire_slot == 1

  def test_slot_zero_one_zero_keeps_one_logical_track(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, track_id=17))
    ri.update(sweep(1, 1, 0x7, 1010, 1024, 3, 50_000_000, track_id=17))
    rr = ri.update(sweep(0, 2, 0x7, 1020, 1024, 5, 100_000_000, track_id=17))
    assert len(rr.points) == 1
    assert [point.trackId for point in rr.points] == [17]
    assert len(ri._tracks) == 1
    assert len(ri._tracks[17].samples) == 3
    assert ri._tracks[17].wire_slot == 0

  def test_same_slot_replacement_preserves_returning_identity_history(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, track_id=2))
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000, track_id=2))
    assert [point.trackId for point in rr.points] == [2]
    assert len(ri._tracks[2].samples) == 2

    # Bosch can put a different persistent object in the same wire slot while the slot's lifecycle
    # counter continues. The old logical track is not dead: retain its state until its own staleness
    # deadline so it can resume without a synthetic birth or an OLS reset.
    rr = ri.update(sweep(0, 2, 0x7, 1500, 1024, 5, 100_000_000, track_id=63))
    assert set(ri._tracks) == {2, 63}
    assert len(ri._tracks[2].samples) == 2
    assert len(rr.points) == 0
    assert 2 not in ri.pts

    rr = ri.update(sweep(0, 3, 0x7, 1020, 1024, 7, 150_000_000, track_id=2))
    assert [point.trackId for point in rr.points] == [2]
    assert len(ri._tracks[2].samples) == 3
    assert math.isfinite(rr.points[0].vRel)

  def test_two_wire_slots_with_different_ids_publish_two_points(self):
    ri = make_radar_interface()
    first_extra = make_main_frames(1, 0, 0x7, 1400, 1024, 11, track_id=22)
    ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, extra_slots=first_extra, track_id=11))
    second_extra = make_main_frames(1, 1, 0x7, 1410, 1024, 13, track_id=22)
    rr = ri.update(sweep(0, 1, 0x7, 1010, 1024, 3, 50_000_000,
                         extra_slots=second_extra, track_id=11))
    assert {point.trackId for point in rr.points} == {11, 22}
    assert len(rr.points) == 2

  @pytest.mark.parametrize('track_id', [0, 0xFF, 0x40, 0xA5])
  def test_invalid_can_identity_never_creates_logical_track(self, track_id):
    ri = make_radar_interface()
    rr = ri.update(sweep(0, 0, 0x7, 1000, 1024, 1, 0, track_id=track_id))
    assert len(rr.points) == 0
    assert not ri._tracks

  def test_track_id_reuse_after_death_starts_with_clean_history(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 2000, 1024, 1, 0, track_id=9))
    rr = ri.update(sweep(0, 1, 0x7, 1990, 1024, 3, 50_000_000, track_id=9))
    assert rr.points[0].trackId == 9
    rr = ri.update(sweep(0, 2, 0xF, 1900, 1024, 5, 100_000_000, track_id=9))
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 3, 0x7, 1000, 1024, 1, 150_000_000, track_id=9))
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 4, 0x7, 1000, 1024, 3, 200_000_000, track_id=9))
    assert len(rr.points) == 1
    assert rr.points[0].trackId == 9
    assert rr.points[0].vRel == 0.0

  def test_lifecycle_discontinuity_keeps_can_id_but_clears_derivative(self):
    ri = make_radar_interface()
    ri.update(sweep(0, 0, 0x7, 2000, 1024, 1, 0, track_id=31))
    rr = ri.update(sweep(0, 1, 0x7, 1990, 1024, 3, 50_000_000, track_id=31))
    assert rr.points[0].vRel < 0
    rr = ri.update(sweep(0, 2, 0x7, 500, 1024, 99, 100_000_000, track_id=31))
    assert len(rr.points) == 0
    rr = ri.update(sweep(0, 3, 0x7, 500, 1024, 101, 150_000_000, track_id=31))
    assert len(rr.points) == 1
    assert rr.points[0].trackId == 31
    assert rr.points[0].vRel == 0.0


def test_no_can_data_returns_none_without_crash():
  ri = make_radar_interface()
  assert ri.update([]) is None


def test_bosch_a_azimuth_scale_is_exact_firmware_scale():
  assert BOSCH_A_AZIMUTH_SCALE_RAD == pytest.approx(1.0 / 2048.0)


def test_bosch_a_observed_sweep_end_and_publish_trigger_are_distinct():
  # 0x297 is the observed final object-family frame, but 0x2FF intentionally
  # remains the publish trigger while companion data is optional.
  assert BOSCH_A_TRIGGER_MSG == 0x2FF
  assert BOSCH_A_SWEEP_END_MSG == 0x297


def test_bosch_a_timing_contract():
  assert BOSCH_A_FREQ_HZ == 15
  assert BOSCH_A_STALE_S == pytest.approx(0.20)


# --- misc integration: DBC wiring -------------------------------------------------------------------

def test_civic_bosch_radar_dbc_wired_and_available():
  assert CP.radarUnavailable is False
  ri = make_radar_interface()
  assert ri.bosch_a_radar is True
  assert ri.rcp is not None


def test_civic_bosch_object_feed_uses_camera_side_acc_can():
  ri = make_radar_interface()
  can = CanBus(CP)

  assert ri.rcp.bus == can.camera
  assert ri.rcp.bus != can.radar
