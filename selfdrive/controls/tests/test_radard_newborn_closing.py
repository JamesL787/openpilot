"""NEWBORN_RANGE_CLOSING_EXEMPT (radard.py): a young Bosch-A track whose own range proves a clear closing passes
vel_sane in the vision match and is not lifted by FAR_RAIL_VISION_BOUND. Replay-only change; see the constant block."""
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.controls import radard

DT = radard.HONDA_BOSCH_A_RADAR_TS


@pytest.fixture(autouse=True)
def newborn_leads_on():
  # These switches ship off behind BoschANewbornLeads; every test here is about their ON behaviour.
  radard.set_bosch_a_newborn_leads(True)
  yield
  radard.set_bosch_a_newborn_leads(False)


def make_track(ranges, v_rel, v_ego=19.8, t0=100.0):
  track = radard.Track(39, v_rel + v_ego, radard.KalmanParams(DT))
  for i, d in enumerate(ranges):
    track.update(d, 0.0, v_rel, v_rel + v_ego, False, measurement_update=False, t_now=t0 + i * DT)
  return track


def linear(d0, d1, n):
  return [d0 + (d1 - d0) * i / (n - 1) for i in range(n)]


def test_closing_run_is_genuinely_closing():
  # 116 -> 90 m over 19 sweeps (~1.25 s, ~-20.6 m/s) at vEgo 19.8, published at the stationary bound.
  track = make_track(linear(116.0, 90.0, 19), -19.8)
  assert radard.young_range_genuinely_closing(track, 19.8)


def test_flat_run_is_not_closing():
  # 0000027a 8:33 track 15: range 62.6-63.6 m while U11 coasted -10.7.
  ranges = [63.0, 62.6, 63.4, 62.8, 63.6, 63.1, 62.7, 63.3, 63.0, 62.9]
  assert not radard.young_range_genuinely_closing(make_track(ranges, -10.7), 19.8)


def test_noisy_run_is_not_closing():
  # 00000284 22:35 track 17: 79 -> 83 -> 80 m while U11 coasted -10.5.
  ranges = linear(79.0, 83.0, 8) + linear(83.0, 80.0, 8)[1:]
  assert not radard.young_range_genuinely_closing(make_track(ranges, -10.5), 19.8)


def test_vrel_disagreeing_with_range_is_not_closing():
  ranges = linear(116.0, 90.0, 19)
  assert not radard.young_range_genuinely_closing(make_track(ranges, -16.0), 19.8)  # |~-20.6 - -16| > 3
  assert radard.young_range_genuinely_closing(make_track(ranges, -18.5), 19.8)


def test_short_or_old_or_slow_closing_is_not_closing():
  assert not radard.young_range_genuinely_closing(make_track(linear(116.0, 113.0, 4), -19.8), 19.8)  # too few samples
  old = make_track(linear(116.0, 90.0, 19), -19.8)
  old.update(89.0, 0.0, -19.8, 0.0, False, measurement_update=False, t_now=old.t_first + radard.YOUNG_TRACK_MAX_AGE_S + 0.1)
  assert not radard.young_range_genuinely_closing(old, 19.8)  # past YOUNG_TRACK_MAX_AGE_S
  # -6 m/s closing: inside the flat regime, not exempt
  assert not radard.young_range_genuinely_closing(make_track(linear(60.0, 52.5, 19), -6.0), 19.8)
  # -9 m/s at vEgo 25: past -8 but slower than half of ego speed
  assert not radard.young_range_genuinely_closing(make_track(linear(60.0, 48.8, 19), -9.0, v_ego=25.0), 25.0)


def test_exempt_switch_off():
  track = make_track(linear(116.0, 90.0, 19), -19.8)
  radard.NEWBORN_RANGE_CLOSING_EXEMPT = False
  try:
    assert not radard.young_range_genuinely_closing(track, 19.8)
  finally:
    radard.NEWBORN_RANGE_CLOSING_EXEMPT = True


def vision_lead(d, v):
  return SimpleNamespace(x=[d + radard.RADAR_TO_CAMERA], y=[0.0], v=[v], yStd=[0.5], xStd=[3.0], vStd=[2.0], prob=0.9)


@pytest.mark.parametrize("bosch, expected", [(True, True), (False, False)])
def test_vision_match_vel_sane_exemption(bosch, expected):
  # Camera has the stopped car at 16 m/s; the track's own range says vLead ~0.
  track = make_track(linear(116.0, 90.0, 19), -19.8)
  lead = vision_lead(track.dRel, 16.0)
  kw = dict(dist_scale=0.25, dist_floor=5.0, vel_limit=10.0, y_std_scale=1.0, y_floor=1.0)
  assert radard.track_matches_vision(track, lead, 19.8, honda_bosch_a=bosch, **kw) is expected


def test_vision_match_flat_track_still_rejected():
  track = make_track([63.0, 62.6, 63.4, 62.8, 63.6, 63.1, 62.7, 63.3, 63.0, 62.9], -19.8)
  lead = vision_lead(track.dRel, 16.0)
  assert not radard.track_matches_vision(track, lead, 19.8, dist_scale=0.25, dist_floor=5.0, vel_limit=10.0,
                                         y_std_scale=1.0, y_floor=1.0, honda_bosch_a=True)


KW = dict(dist_scale=0.25, dist_floor=5.0, vel_limit=10.0, y_std_scale=1.0, y_floor=1.0)


def test_newborn_lead_needs_closing():
  # 000002ae 26 track 2: clean -9 m/s fit at 70-74 m, vEgo 22.1 (slope above -0.5 * vEgo), camera agrees on speed.
  track = make_track(linear(73.9, 69.3, 10), -9.0, v_ego=22.1)
  assert track.cnt == 0 and not radard.young_range_genuinely_closing(track, 22.1)
  lead = vision_lead(track.dRel, 13.1)
  assert not radard.track_matches_vision(track, lead, 22.1, honda_bosch_a=True, **KW)
  assert radard.track_matches_vision(track, lead, 22.1, honda_bosch_a=False, **KW)
  radard.NEWBORN_LEAD_NEEDS_CLOSING = False
  try:
    assert radard.track_matches_vision(track, lead, 22.1, honda_bosch_a=True, **KW)
  finally:
    radard.NEWBORN_LEAD_NEEDS_CLOSING = True


def test_three_sweep_newborn_is_not_lead():
  # 00000294 3 track 48: 3 sweeps at -vEgo is too young to prove anything, so it is not a lead.
  track = make_track(linear(91.9, 89.4, 3), -17.0, v_ego=17.0)
  assert not radard.track_matches_vision(track, vision_lead(track.dRel, 0.0), 17.0, honda_bosch_a=True, **KW)


def test_newborn_lead_gate_ignores_measured_tracks():
  track = make_track(linear(73.9, 69.3, 10), -9.0, v_ego=22.1)
  track.update(69.0, 0.0, -9.0, 13.1, True, measurement_update=True, t_now=200.0)
  assert track.cnt > 0
  assert radard.track_matches_vision(track, vision_lead(track.dRel, 13.1), 22.1, honda_bosch_a=True, **KW)


def _newborn(ranges, v_rel, v_ego=19.8, follow=True, t0=100.0):
  track = radard.Track(39, v_rel + v_ego, radard.KalmanParams(DT))
  for i, d in enumerate(ranges):
    track.update(d, 0.0, v_rel, v_rel + v_ego, False, measurement_update=False, t_now=t0 + i * DT, newborn_follow=follow)
  return track


def test_newborn_kf_follows_own_range_to_stationary():
  # NEWBORN_KF_FOLLOW_RANGE: published at -8 (a first 4-sweep fit) but the range closes at ~-21 m/s; the KF follows the
  # range, bounded at stationary (vLeadK 0), with aLeadK 0 -- not frozen at vEgo - 8.
  track = _newborn(linear(116.0, 90.0, 19), -8.0)
  assert track.vLeadK == pytest.approx(0.0, abs=1e-9)
  assert track.aLeadK == 0.0


def test_newborn_kf_follows_a_flat_range_back_up():
  # 00000284 track 17 style: a closing burst, then flat. The KF ends near the flat fit, not at the burst.
  ranges = linear(88.7, 79.9, 10) + [79.1, 79.8, 80.9, 81.6, 82.2, 82.6, 83.0, 83.2, 83.1, 82.8, 81.9, 81.4, 80.8]
  track = _newborn(ranges, -10.5, v_ego=24.0)
  a = [(i * DT, d) for i, d in enumerate(ranges)]
  import numpy as np
  slope = np.polyfit([p[0] for p in a], [p[1] for p in a], 1)[0]
  assert track.vLeadK == pytest.approx(24.0 + slope)


def test_newborn_kf_untouched_without_flag_or_after_a_measurement():
  frozen = _newborn(linear(116.0, 90.0, 19), -8.0, follow=False)
  assert frozen.vLeadK == pytest.approx(11.8)
  track = radard.Track(39, 11.8, radard.KalmanParams(DT))
  track.update(116.0, 0.0, -8.0, 11.8, True, measurement_update=True, t_now=100.0)  # cnt -> 1
  for i, d in enumerate(linear(115.0, 90.0, 18)):
    track.update(d, 0.0, -8.0, 11.8, False, measurement_update=False, t_now=100.0 + (i + 1) * DT, newborn_follow=True)
  assert track.vLeadK == pytest.approx(11.8)
