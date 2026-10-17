"""YOUNG_TRACK_VISION_HOLD (radard.py): at a crawl, a young Bosch-A track whose U11 reads clearly slower than a
confident camera lead that is pulling away does not take the lead until it is older or agrees. Replay-only change;
see the constant block. Numbers below are route 00000361 24:33 track 43 and 51:30 track 38."""
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.controls import radard

DT = radard.HONDA_BOSCH_A_RADAR_TS
KW = dict(dist_scale=0.25, dist_floor=5.0, vel_limit=10.0, y_std_scale=1.0, y_floor=1.0)


@pytest.fixture(autouse=True)
def hold_on():
  radard.set_bosch_a_newborn_leads(True)
  radard.YOUNG_TRACK_VISION_HOLD = True
  yield
  radard.YOUNG_TRACK_VISION_HOLD = True


def make_track(ranges, v_rel, v_ego, t0=100.0):
  track = radard.Track(43, v_rel + v_ego, radard.KalmanParams(DT))
  for i, d in enumerate(ranges):
    track.update(d, 0.0, v_rel, v_rel + v_ego, True, measurement_update=True, t_now=t0 + i * DT)
  return track


def vision_lead(d, v, a=0.0, prob=1.0):
  return SimpleNamespace(x=[d + radard.RADAR_TO_CAMERA], y=[0.0], v=[v], a=[a], yStd=[0.5], xStd=[3.0], vStd=[2.0],
                         prob=prob)


def test_361_2433_young_slow_track_is_held():
  # Sweeps at age 0.06-0.20 s: range opening 6.17 -> 6.30 m, U11 -0.3, vEgo 0.5, camera 2.5 m/s accelerating.
  track = make_track([6.17, 6.23, 6.30], -0.3, 0.5)
  lead = vision_lead(track.dRel, 2.5, a=1.9)
  assert radard.young_track_vision_hold(track, lead, 0.5)
  assert not radard.track_matches_vision(track, lead, 0.5, honda_bosch_a=True, **KW)
  assert radard.track_matches_vision(track, lead, 0.5, honda_bosch_a=False, **KW)


def test_hold_ends_when_u11_agrees():
  # Age 0.34 s: U11 caught up to +1.8 (vLead 2.4 vs camera 2.9).
  track = make_track([6.17, 6.23, 6.30, 6.36, 6.80], 1.8, 0.6)
  assert not radard.young_track_vision_hold(track, vision_lead(track.dRel, 2.9, a=1.9), 0.6)


def test_hold_ends_with_age():
  n = int(radard.YOUNG_HOLD_MAX_AGE_S / DT) + 2
  track = make_track([6.17 + 0.05 * i for i in range(n)], -0.3, 0.5)
  assert track.t_last - track.t_first > radard.YOUNG_HOLD_MAX_AGE_S
  assert not radard.young_track_vision_hold(track, vision_lead(track.dRel, 2.5), 0.5)


def test_closing_range_is_never_held():
  # 361 51:30 pattern: the track's own range closes, so radar's slower reading stands.
  track = make_track([8.9, 8.7, 8.5, 8.3], -2.5, 1.5)
  assert not radard.young_track_vision_hold(track, vision_lead(track.dRel, 0.55 + 1.5), 1.5)


@pytest.mark.parametrize("v_ego, vis_v, vis_a, prob", [
  (3.5, 6.0, 0.0, 1.0),   # above the crawl limit
  (0.5, 2.5, 0.0, 0.8),   # camera not confident
  (0.5, 2.5, -1.5, 1.0),  # camera lead braking
  (0.5, 1.0, 0.0, 1.0),   # disagreement under YOUNG_HOLD_MIN_SLOWER
])
def test_no_hold_outside_conditions(v_ego, vis_v, vis_a, prob):
  track = make_track([6.17, 6.23, 6.30], -0.3, v_ego)
  assert not radard.young_track_vision_hold(track, vision_lead(track.dRel, vis_v, a=vis_a, prob=prob), v_ego)


def test_radar_faster_than_camera_is_never_held():
  track = make_track([6.6, 6.65, 6.7], 1.5, 1.0)
  assert not radard.young_track_vision_hold(track, vision_lead(track.dRel, 0.3), 1.0)


def test_switch_off_is_inert():
  track = make_track([6.17, 6.23, 6.30], -0.3, 0.5)
  lead = vision_lead(track.dRel, 2.5, a=1.9)
  radard.YOUNG_TRACK_VISION_HOLD = False
  assert not radard.young_track_vision_hold(track, lead, 0.5)
  assert radard.track_matches_vision(track, lead, 0.5, honda_bosch_a=True, **KW)
