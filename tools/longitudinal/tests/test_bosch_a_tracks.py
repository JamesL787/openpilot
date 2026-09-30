from types import SimpleNamespace

import numpy as np

import opendbc.car.honda.radar_interface as RI
from opendbc.can.packer import CANPacker
from openpilot.tools.longitudinal import bosch_a_tracks as bat

PACKER = CANPacker(RI.BOSCH_A_DBC_NAME)


def _sweep(slot, tid, range_m, life, frame_idx, u11_raw=864):
  vals = [{"STATUS": 1, "FRAME_IDX": frame_idx, "RANGE": range_m, "AZIMUTH_RAW": 1024 + 20},
          {"FRAME_IDX": frame_idx, "OBJECT_EXISTENCE_PROBABILITY_RAW": 100},
          {"FRAME_IDX": frame_idx, "LIFECYCLE_RAW": life, "NORMALIZED_CLOSING": -1.5},
          {"FRAME_IDX": frame_idx, "TRACK_ID": tid},
          {"FRAME_IDX": frame_idx, "REL_VELOCITY_RAW": u11_raw}]
  names = [f"BOSCH_A_S{slot:02d}_F{k}" for k in range(4)] + [f"BOSCH_A_S{slot:02d}_AUX"]
  frames = []
  for name, v in zip(names, vals, strict=True):
    addr, dat, _ = PACKER.make_can_msg(name, 2, v)
    frames.append(SimpleNamespace(address=addr, dat=dat, src=2))
  # the sweep closes on slot 15's AUX (0x297); send an empty one so a single-slot sweep still ends
  addr, dat, _ = PACKER.make_can_msg("BOSCH_A_S15_AUX", 2, {})
  frames.append(SimpleNamespace(address=addr, dat=dat, src=2))
  return frames


def _run(sweeps):
  ex = bat.Extractor()
  ex.t0 = 0
  ex.ctx.update(v_ego=20.0, lead1_tid=7.0)
  for i, (tid, rng, life, idx) in enumerate(sweeps):
    ex.on_can(int(i * 0.07e9), _sweep(4, tid, rng, life, idx))
  return ex.table({"route": "synthetic", "segments": [0]})


def test_rows_decode_every_frame_and_join_the_lead():
  tab = _run([(7, 50.0, 100 + 2 * i, i) for i in range(5)])
  assert len(tab["trk_t"]) == 5 and np.all(tab["trk_tid"] == 7) and np.all(tab["trk_slot"] == 4)
  assert np.allclose(tab["trk_d_rel"], 50.0) and np.allclose(tab["trk_f2_NORMALIZED_CLOSING"], -1.5)
  assert np.all(tab["trk_y_rel"] > 0)  # azimuth above center is left, positive
  assert np.allclose(tab["trk_vrel_u11"], 0.0) and np.all(tab["trk_is_lead"] == 1)
  assert np.all(tab["trk_have"]) and tab["trk_raw"].shape == (5, 5, 8)
  assert np.all(tab["trk_valid"] == 1) and list(tab["trk_brk"]) == [1, 0, 0, 0, 0]
  assert any(",f0_RANGE_SIGMA_RAW,FW_LID_" in n or "_lid_b" in n for n in tab["lid_names"])
  assert np.all(tab["trk_u11_railed"] == 0) and np.all(np.isfinite(tab["trk_u10"])) and np.all(tab["trk_spread_ms"] >= 0)


def test_u11_on_a_rail_is_flagged():
  ex = bat.Extractor()
  ex.t0 = 0
  for i in range(2):
    ex.on_can(int(i * 0.07e9), _sweep(4, 7, 50.0, 100 + 2 * i, i, u11_raw=0))
  assert list(ex.table({"route": "synthetic", "segments": [0]})["trk_u11_railed"]) == [1.0, 1.0]


def test_identity_breaks_on_a_counter_reset_and_holds_through_saturation():
  life = [100, 102, 10, 12, RI.BOSCH_A_LIFE_SATURATED, RI.BOSCH_A_LIFE_SATURATED]
  tab = _run([(7, 50.0, lf, i) for i, lf in enumerate(life)])
  # 12 -> 0xFFE is not +2: a break too; the saturated hold after it cannot testify and is kept
  assert list(tab["trk_brk"]) == [1, 0, 2, 0, 2, 3]
  assert list(tab["trk_inc"]) == [1, 1, 2, 2, 3, 3]


def test_lsq_slope_reads_a_closing_track_and_restarts_at_a_new_incarnation():
  t = np.arange(20) * 0.07
  d = 60.0 - 12.0 * t
  inc = np.where(np.arange(20) < 10, 1, 2)
  s = bat.lsq_slope(t, d, inc)
  assert np.isnan(s[2]) and np.allclose(s[3:10], -12.0) and np.isnan(s[10])  # 4 points of the new incarnation first
  assert np.allclose(s[13:], -12.0)
  assert np.isnan(bat.lsq_slope(t, d, inc, 0.5)[5]) and np.allclose(bat.lsq_slope(t, d, inc, 0.5)[6:10], -12.0)


def test_a_saturated_hold_ends_the_strict_fit_window():
  n = 16
  t = np.arange(n) * 0.07
  d = 60.0 - 12.0 * t
  brk = np.array([1] + [0] * 7 + [3] * 3 + [0] * 5)
  key, sat = bat.strict_key(np.full(n, 7), np.ones(n), brk)
  s = bat.lsq_slope(t, np.where(sat, np.nan, d), key)
  assert np.allclose(s[3:8], -12.0) and np.all(np.isnan(s[8:14])) and np.allclose(s[14:], -12.0)
  assert np.allclose(bat.lsq_slope(t, d, np.ones(n))[3:], -12.0)  # the parser-mirror key keeps fitting through it


def test_parse_segs_and_svg():
  assert bat.parse_segs("3-5,11") == {3, 4, 5, 11} and bat.parse_segs(None) is None
  svg = bat._svg_panels("x", 0.0, 1.0, [{"label": "p", "series": [("a", [0, 1], [1, 2]), ("b", [0, 1], [np.nan, 3], "#000", "dots")]}],
                        [(0.5, "#f00", "mark")])
  assert svg.startswith("<svg") and "polyline" in svg and "circle" in svg
