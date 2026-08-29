from types import SimpleNamespace

import pytest

from cereal import car
from openpilot.selfdrive.controls import radard
from opendbc.car.honda.values import CAR as HONDA_CAR


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


def make_track(track_id, d_rel, count, *, y_rel=0.0, v_rel=0.0):
  track = radard.Track(track_id, 0.0, radard.KalmanParams(radard.HONDA_BOSCH_A_RADAR_TS))
  for _ in range(count):
    track.update(d_rel, y_rel, v_rel, v_rel, True, True)
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


def make_staleness_radar_d(*, honda_bosch_a_radar=True):
  radar_d = radard.RadarD(honda_bosch_a_radar=honda_bosch_a_radar)
  radar_d.ready = True
  radar_d.v_ego = 0.0
  radar_d.starpilot_toggles = make_toggles()
  return radar_d


@pytest.mark.parametrize("candidate", [HONDA_CAR.HONDA_CIVIC_BOSCH, HONDA_CAR.HONDA_CRV_5G, HONDA_CAR.HONDA_INSIGHT])
def test_bosch_a_platforms_enable_bosch_a_radard_semantics(candidate):
  cp = SimpleNamespace(brand="honda", carFingerprint=candidate, radarUnavailable=False)
  assert radard.is_bosch_a_radar_car(cp)


def test_unavailable_bosch_a_radar_does_not_enable_bosch_a_radard_semantics():
  cp = SimpleNamespace(brand="honda", carFingerprint=HONDA_CAR.HONDA_CRV_5G, radarUnavailable=True)
  assert not radard.is_bosch_a_radar_car(cp)


@pytest.mark.parametrize("candidate", [HONDA_CAR.HONDA_CIVIC_2022, HONDA_CAR.HONDA_ACCORD_11G])
def test_non_bosch_a_platforms_do_not_enable_bosch_a_radard_semantics(candidate):
  # radarless and CANFD Bosch platforms respectively -- same HONDA_BOSCH family, but excluded
  # from HONDA_BOSCH_A regardless of radarUnavailable.
  cp = SimpleNamespace(brand="honda", carFingerprint=candidate, radarUnavailable=False)
  assert not radard.is_bosch_a_radar_car(cp)


def test_civic_bosch_duplicate_live_tracks_frame_does_not_update_kf(monkeypatch):
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)

  radar_d = radard.RadarD(honda_bosch_a_radar=True)
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


def test_civic_bosch_unmeasured_coast_updates_geometry_without_kf(monkeypatch):
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)

  radar_d = radard.RadarD(honda_bosch_a_radar=True)
  sm = FakeSubMaster(live_tracks_frame=1)
  radar_d.update(sm, make_radar_data(v_rel=-1.0, d_rel=20.0, y_rel=0.1, measured=True))
  track = radar_d.tracks[1]
  trusted_kf_speed = float(track.kf.x[radard.SPEED][0])
  trusted_kf_accel = float(track.kf.x[radard.ACCEL][0])

  sm.recv_frame['liveTracks'] = 2
  radar_d.update(sm, make_radar_data(v_rel=-1.0, d_rel=18.9, y_rel=0.2, measured=False))
  assert track.dRel == pytest.approx(18.9)
  assert track.yRel == pytest.approx(0.2)
  assert track.vRel == pytest.approx(-1.0)
  assert not track.measured
  assert track.cnt == 1
  assert float(track.kf.x[radard.SPEED][0]) == pytest.approx(trusted_kf_speed)
  assert float(track.kf.x[radard.ACCEL][0]) == pytest.approx(trusted_kf_accel)


def test_civic_bosch_separates_kf_and_model_lead_probability_timing():
  radar_d = radard.RadarD(honda_bosch_a_radar=True)

  assert radar_d.kalman_params.A[0][1] == pytest.approx(1.0 / 15.0)
  assert radar_d.lead_prob_filters[0].dt == pytest.approx(radard.DT_MDL)
  assert radar_d.lead_prob_filters[1].dt == pytest.approx(radard.DT_MDL)


def test_model_lead_probability_filters_use_model_timing_for_all_radars():
  radar_d = radard.RadarD(radar_ts=0.1)

  assert radar_d.kalman_params.A[0][1] == pytest.approx(0.1)
  # Lead probabilities are model-cycle inputs even when a caller supplies a different radar KF dt.
  assert radar_d.lead_prob_filters[0].dt == pytest.approx(radard.DT_MDL)


def test_non_honda_bosch_a_radars_keep_per_model_cycle_update_semantics(monkeypatch):
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
    lead_prob=0.99, honda_bosch_a_radar=True,
  )
  assert lead['radarTrackId'] == 7


def test_bosch_persistent_candidate_that_matches_vision_can_take_over():
  tracks = {
    2: make_track(2, 2.0, 3),
    7: make_track(7, 7.0, 5),
  }
  lead = radard.get_lead(
    1.0, True, tracks, make_lead(2.0), 0.0, make_model_data(), False, make_plan(), make_toggles(),
    lead_prob=0.99, honda_bosch_a_radar=True,
  )
  assert lead['radarTrackId'] == 2


def test_bosch_mature_radar_only_candidate_can_takeover_without_model_lead():
  tracks = {4: make_track(4, 5.0, 3)}
  lead = radard.get_lead(
    1.0, False, tracks, make_lead(5.0, probability=0.0), 0.0, make_model_data(), False, make_plan(), make_toggles(),
    lead_prob=0.0, honda_bosch_a_radar=True,
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
    lead_prob=0.0, preferred_track_id=7, honda_bosch_a_radar=True,
  )
  assert lead['radarTrackId'] == 7


def test_bosch_arm_a_clears_after_two_better_challenger_cycles():
  radar_d = make_staleness_radar_d()
  radar_d.tracks = {
    27: make_track(27, 10.0, 5, y_rel=3.0),
    38: make_track(38, 10.0, 5, y_rel=2.0),
  }
  radar_d.prev_lead_track_ids[0] = 27
  lead = make_lead(10.0)

  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.prev_lead_track_ids[0] == 27
  assert radar_d.preferred_challenger_stale_counts[0] == 1

  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.prev_lead_track_ids[0] == -1
  assert radar_d.preferred_challenger_stale_counts[0] == 0


def test_bosch_arm_a_clear_does_not_select_non_strict_challenger():
  radar_d = make_staleness_radar_d()
  radar_d.tracks = {
    27: make_track(27, 10.0, 5, y_rel=3.0),
    38: make_track(38, 10.0, 5, y_rel=2.0),
  }
  radar_d.prev_lead_track_ids[0] = 27
  lead_msg = make_lead(10.0)

  for _ in range(2):
    radar_d._update_honda_bosch_a_preferred_staleness(0, lead_msg, 0.99)

  lead = radard.get_lead(
    0.0, True, radar_d.tracks, lead_msg, 0.0, make_model_data(), False, make_plan(), make_toggles(),
    low_speed_override=False, lead_prob=0.99, preferred_track_id=radar_d.prev_lead_track_ids[0],
    honda_bosch_a_radar=True,
  )
  assert lead['status']
  assert not lead['radar']
  assert lead['radarTrackId'] == -1


def test_bosch_arm_a_resets_when_preferred_relaxed_match_recovers():
  radar_d = make_staleness_radar_d()
  preferred = make_track(27, 10.0, 5, y_rel=3.0)
  radar_d.tracks = {
    27: preferred,
    38: make_track(38, 10.0, 5, y_rel=2.0),
  }
  radar_d.prev_lead_track_ids[0] = 27
  lead = make_lead(10.0)

  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.preferred_challenger_stale_counts[0] == 1

  preferred.yRel = 1.4  # strict lateral fail, existing relaxed lateral pass
  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.preferred_challenger_stale_counts[0] == 0

  preferred.yRel = 3.0
  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.prev_lead_track_ids[0] == 27
  assert radar_d.preferred_challenger_stale_counts[0] == 1


def test_bosch_arm_b_clears_after_three_non_strict_gross_distance_cycles():
  radar_d = make_staleness_radar_d()
  radar_d.tracks = {53: make_track(53, 79.0, 5)}
  radar_d.prev_lead_track_ids[0] = 53
  lead = make_lead(110.0)

  for expected_count in (1, 2):
    radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
    assert radar_d.prev_lead_track_ids[0] == 53
    assert radar_d.preferred_gross_distance_stale_counts[0] == expected_count

  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.prev_lead_track_ids[0] == -1
  assert radar_d.preferred_gross_distance_stale_counts[0] == 0


def test_bosch_arm_b_strict_match_resets_gross_distance_streak():
  radar_d = make_staleness_radar_d()
  radar_d.tracks = {46: make_track(46, 78.5, 5)}
  radar_d.prev_lead_track_ids[0] = 46
  lead = make_lead(104.0)  # 25.5 m mismatch, inside the 26 m strict allowance

  for _ in range(4):
    radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
    assert radar_d.prev_lead_track_ids[0] == 46
    assert radar_d.preferred_gross_distance_stale_counts[0] == 0


def test_bosch_stale_evidence_does_not_leak_to_new_preferred_id():
  radar_d = make_staleness_radar_d()
  radar_d.tracks = {
    1: make_track(1, 10.0, 5, y_rel=3.0),
    2: make_track(2, 10.0, 5, y_rel=2.0),
    3: make_track(3, 10.0, 5, y_rel=3.0),
  }
  lead = make_lead(10.0)

  radar_d.prev_lead_track_ids[0] = 1
  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.preferred_challenger_stale_counts[0] == 1

  radar_d.prev_lead_track_ids[0] = 3
  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.prev_lead_track_ids[0] == 3
  assert radar_d.preferred_stale_track_ids[0] == 3
  assert radar_d.preferred_challenger_stale_counts[0] == 1


def test_non_bosch_radar_does_not_apply_preferred_stale_logic():
  radar_d = make_staleness_radar_d(honda_bosch_a_radar=False)
  radar_d.tracks = {
    27: make_track(27, 10.0, 5, y_rel=3.0),
    38: make_track(38, 10.0, 5, y_rel=2.0),
  }
  radar_d.prev_lead_track_ids[0] = 27

  for _ in range(4):
    radar_d._update_honda_bosch_a_preferred_staleness(0, make_lead(10.0), 0.99)

  assert radar_d.prev_lead_track_ids[0] == 27
  assert radar_d.preferred_challenger_stale_counts == [0, 0]
  assert radar_d.preferred_gross_distance_stale_counts == [0, 0]


def test_bosch_duplicate_lead_preferences_keep_independent_stale_state():
  radar_d = make_staleness_radar_d()
  radar_d.tracks = {
    24: make_track(24, 10.0, 5, y_rel=3.0),
    44: make_track(44, 10.0, 5, y_rel=2.0),
  }
  radar_d.prev_lead_track_ids = [24, 24]
  lead = make_lead(10.0)

  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  radar_d._update_honda_bosch_a_preferred_staleness(1, lead, 0.99)
  assert radar_d.prev_lead_track_ids == [24, 24]
  assert radar_d.preferred_challenger_stale_counts == [1, 1]

  radar_d._update_honda_bosch_a_preferred_staleness(0, lead, 0.99)
  assert radar_d.prev_lead_track_ids == [-1, 24]
  radar_d._update_honda_bosch_a_preferred_staleness(1, lead, 0.99)
  assert radar_d.prev_lead_track_ids == [-1, -1]


def test_bosch_full_update_clears_stale_preference_then_strictly_reacquires(monkeypatch):
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)

  radar_d = radard.RadarD(honda_bosch_a_radar=True)
  sm = FakeSubMaster(live_tracks_frame=0)
  lead = make_lead(10.0)
  lead.xStd[0] = 10.0
  sm._data['modelV2'].leadsV3 = [lead, make_lead(10.0, probability=0.0)]

  frame = 0

  def update(a_y_rel):
    nonlocal frame
    frame += 1
    timestamp = frame * 50_000_000
    sm.recv_frame['liveTracks'] = frame
    sm.logMonoTime.update(modelV2=timestamp, carState=timestamp, liveTracks=timestamp)

    rr = car.RadarData.new_message()
    points = rr.init('points', 2)
    for point, track_id, d_rel, y_rel in (
      (points[0], 27, 10.0, a_y_rel),
      (points[1], 38, 16.0, 0.5),
    ):
      point.trackId = track_id
      point.dRel = d_rel
      point.yRel = y_rel
      point.vRel = 0.0
      point.measured = True
    radar_d.update(sm, rr)
    return radar_d.radar_state.leadOne

  # Establish ID27 through the unchanged strict path and mature ID38 enough to exercise the
  # Civic-Bosch low-speed candidate path later.
  for _ in range(3):
    output = update(0.0)
    assert output.radar and output.radarTrackId == 27
  assert radar_d.prev_lead_track_ids[0] == 27
  assert radar_d.preferred_stale_track_ids[0] == 27

  # ID27 now fails relaxed lateral continuity. ID38 scores better, is mature and low-speed eligible,
  # but fails the unchanged strict distance gate, so it must not replace the valid vision lead.
  output = update(3.0)
  assert radar_d.preferred_challenger_stale_counts[0] == 1
  assert radar_d.honda_bosch_a_radar
  assert radard.honda_bosch_a_low_speed_radar_lead_sane(radar_d.tracks[38], radar_d.v_ego)
  assert not radard.track_matches_vision(radar_d.tracks[38], lead, radar_d.v_ego,
                                         dist_scale=0.25, dist_floor=5.0,
                                         vel_limit=10.0, y_std_scale=1.0, y_floor=1.0)
  assert output.status and not output.radar and output.radarTrackId == -1
  assert radar_d.prev_lead_track_ids[0] == 27

  output = update(3.0)
  assert output.status and not output.radar and output.radarTrackId == -1
  assert radar_d.prev_lead_track_ids[0] == -1
  assert radar_d.preferred_stale_track_ids[0] == -1
  assert radar_d.preferred_challenger_stale_counts[0] == 0
  assert radar_d.preferred_gross_distance_stale_counts[0] == 0

  # When ID27 becomes a normal strict match again, it is legitimately reacquired and owns clean
  # preference state; no evidence from the stale incarnation survives.
  output = update(0.0)
  assert output.radar and output.radarTrackId == 27
  assert radar_d.prev_lead_track_ids[0] == 27
  assert radar_d.preferred_stale_track_ids[0] == 27
  assert radar_d.preferred_challenger_stale_counts[0] == 0
  assert radar_d.preferred_gross_distance_stale_counts[0] == 0
