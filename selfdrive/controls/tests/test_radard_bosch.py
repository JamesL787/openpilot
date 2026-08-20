from types import SimpleNamespace

import pytest

from cereal import car
from openpilot.selfdrive.controls import radard


def make_toggles():
  return SimpleNamespace(
    lead_detection_probability=0.35,
    adjacent_lead_tracking=False,
    human_lane_changes=False,
  )


def make_radar_data(v_rel=0.0, *, track_id=1, d_rel=7.0, y_rel=0.0, measured=True):
  rr = car.RadarData.new_message()
  point = rr.init('points', 1)[0]
  point.trackId = track_id
  point.dRel = d_rel
  point.yRel = y_rel
  point.vRel = v_rel
  point.measured = measured
  return rr


class FakeSubMaster:
  def __init__(self, live_tracks_frame=1, *, model_seen=True):
    self.seen = {'modelV2': model_seen}
    self.recv_frame = {'liveTracks': live_tracks_frame, 'carState': 1}
    self.logMonoTime = {'modelV2': 1_000_000_000, 'carState': 1_000_000_000, 'liveTracks': 1_000_000_000}
    self._data = {
      'carState': SimpleNamespace(vEgo=0.0, standstill=False),
      'modelV2': SimpleNamespace(
        velocity=SimpleNamespace(x=[0.0]),
        leadsV3=[],
        laneLines=[],
        meta=SimpleNamespace(laneChangeState=0),
      ),
      'starpilotPlan': SimpleNamespace(increasedStoppedDistance=0.0),
    }

  def __getitem__(self, key):
    return self._data[key]

  def all_checks(self):
    return True


def make_track(track_id, d_rel, count):
  track = radard.Track(track_id, 0.0, radard.KalmanParams(radard.CIVIC_BOSCH_RADAR_TS))
  for _ in range(count):
    track.update(d_rel, 0.0, 0.0, 0.0, True, True)
  return track


def make_lead(d_rel, *, probability=0.99):
  return SimpleNamespace(
    prob=probability,
    x=[d_rel + radard.RADAR_TO_CAMERA],
    y=[0.0],
    v=[0.0],
    a=[0.0],
    xStd=[1.0],
    yStd=[1.0],
    vStd=[1.0],
  )


def make_model_data():
  return SimpleNamespace(meta=SimpleNamespace(laneChangeState=0))


def make_plan():
  return SimpleNamespace(increasedStoppedDistance=0.0)


def test_civic_bosch_duplicate_live_tracks_frame_does_not_update_kf(monkeypatch):
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)

  radar_d = radard.RadarD(civic_bosch_radar=True)
  assert radar_d.kalman_params.A[0][1] == pytest.approx(1.0 / 15.0)

  sm = FakeSubMaster(live_tracks_frame=1)
  radar_d.update(sm, make_radar_data(v_rel=0.0))
  track = radar_d.tracks[1]
  first_kf_speed = float(track.kf.x[radard.SPEED][0])
  assert track.cnt == 1

  # This is the same liveTracks receive frame. The changed point is deliberately treated as a
  # stale duplicate to prove the downstream KF does not absorb it a second time.
  radar_d.update(sm, make_radar_data(v_rel=4.0))
  assert track.cnt == 1
  assert not track.measured
  assert float(track.kf.x[radard.SPEED][0]) == pytest.approx(first_kf_speed)

  # The next actual Bosch sweep updates normally.
  sm.recv_frame['liveTracks'] = 2
  radar_d.update(sm, make_radar_data(v_rel=4.0))
  assert track.cnt == 2
  assert float(track.kf.x[radard.SPEED][0]) != pytest.approx(first_kf_speed)


def test_civic_bosch_separates_kf_and_model_lead_probability_timing():
  radar_d = radard.RadarD(civic_bosch_radar=True)

  assert radar_d.kalman_params.A[0][1] == pytest.approx(1.0 / 15.0)
  assert radar_d.lead_prob_filters[0].dt == pytest.approx(radard.DT_MDL)
  assert radar_d.lead_prob_filters[1].dt == pytest.approx(radard.DT_MDL)


def test_model_lead_probability_filters_use_model_timing_for_all_radars():
  radar_d = radard.RadarD(radar_ts=0.1)

  assert radar_d.kalman_params.A[0][1] == pytest.approx(0.1)
  # Lead probabilities are model-cycle inputs even when a caller supplies a different radar KF dt.
  assert radar_d.lead_prob_filters[0].dt == pytest.approx(radard.DT_MDL)


def test_non_civic_bosch_radars_keep_per_model_cycle_update_semantics(monkeypatch):
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)

  radar_d = radard.RadarD()
  sm = FakeSubMaster(live_tracks_frame=1)
  radar_d.update(sm, make_radar_data(measured=False))
  radar_d.update(sm, make_radar_data(measured=False, v_rel=2.0))
  assert radar_d.tracks[1].cnt == 2


def test_bosch_close_new_candidate_does_not_replace_established_lead():
  tracks = {
    2: make_track(2, 2.0, 1),
    7: make_track(7, 7.0, 5),
  }
  lead = radard.get_lead(
    1.0, True, tracks, make_lead(7.0), 0.0, make_model_data(), False, make_plan(), make_toggles(),
    lead_prob=0.99, civic_bosch_radar=True,
  )
  assert lead['radarTrackId'] == 7


def test_bosch_persistent_candidate_that_matches_vision_can_take_over():
  tracks = {
    2: make_track(2, 2.0, 3),
    7: make_track(7, 7.0, 5),
  }
  lead = radard.get_lead(
    1.0, True, tracks, make_lead(2.0), 0.0, make_model_data(), False, make_plan(), make_toggles(),
    lead_prob=0.99, civic_bosch_radar=True,
  )
  assert lead['radarTrackId'] == 2


def test_bosch_mature_radar_only_candidate_can_takeover_without_model_lead():
  tracks = {4: make_track(4, 5.0, 3)}
  lead = radard.get_lead(
    1.0, False, tracks, make_lead(5.0, probability=0.0), 0.0, make_model_data(), False, make_plan(), make_toggles(),
    lead_prob=0.0, civic_bosch_radar=True,
  )
  assert lead['status']
  assert lead['radarTrackId'] == 4


def test_bosch_preferred_lead_survives_model_probability_fluctuation():
  tracks = {
    2: make_track(2, 2.0, 3),
    7: make_track(7, 7.0, 5),
  }
  lead = radard.get_lead(
    1.0, False, tracks, make_lead(7.0, probability=0.0), 0.0, make_model_data(), False, make_plan(), make_toggles(),
    lead_prob=0.0, preferred_track_id=7, civic_bosch_radar=True,
  )
  assert lead['radarTrackId'] == 7
