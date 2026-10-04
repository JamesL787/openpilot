from types import SimpleNamespace

import numpy as np
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


def make_empty_radar_data():
  # What the parser publishes on the sweep where a lifecycle discontinuity retires an incarnation:
  # the CAN identity is gone from RadarData until its replacement matures.
  rr = car.RadarData.new_message()
  rr.init('points', 0)
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
  assert radar_d.kalman_params.A[0][1] == pytest.approx(radard.HONDA_BOSCH_A_RADAR_TS)

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


def _bosch_sweeps(radar_d, sm):
  """Advance the liveTracks receive frame per call, i.e. one Bosch-A sweep per published message."""
  frame = [sm.recv_frame['liveTracks']]

  def sweep(radar_data):
    frame[0] += 1
    sm.recv_frame['liveTracks'] = frame[0]
    radar_d.update(sm, radar_data)
  return sweep


def test_civic_bosch_incarnation_gap_resets_lead_kalman(monkeypatch):
  # Bosch-A track IDs are 6-bit and are reused within a segment (00000231--5782493b00: ID 58 covers
  # two unrelated objects 27 s apart). radar_interface clears its own derivative history on a
  # lifecycle discontinuity, but radard's lead KF is a separate filter with separate state, and the
  # only thing that resets it is the CAN identity being absent from a liveTracks radard observes.
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)

  radar_d = radard.RadarD(honda_bosch_a_radar=True)
  sm = FakeSubMaster(live_tracks_frame=1)
  sweep = _bosch_sweeps(radar_d, sm)

  # Incarnation 1: an object closing hard, tracked long enough to own a settled filter.
  for _ in range(30):
    sweep(make_radar_data(v_rel=-12.0, track_id=58, d_rel=70.0))
  first = radar_d.tracks[58]
  assert first.cnt == 30
  assert float(first.kf.x[radard.SPEED][0]) == pytest.approx(-12.0, abs=1e-6)

  # The incarnation boundary is exactly one sweep wide: radar_interface pops the point on the
  # lifecycle break, and the replacement cannot be republished until a second coherent sample gives
  # it a finite derivative (`matured`). This is the whole of the reset signal radard receives.
  sweep(make_empty_radar_data())
  assert 58 not in radar_d.tracks

  # Incarnation 2 reuses the same CAN identity for a different object, opening instead of closing.
  for _ in range(3):
    sweep(make_radar_data(v_rel=3.0, track_id=58, d_rel=45.0))
  second = radar_d.tracks[58]
  assert second is not first
  assert second.cnt == 3
  # Seeded from the new object's own vLead, so it reports that object and no phantom acceleration.
  assert float(second.kf.x[radard.SPEED][0]) == pytest.approx(3.0, abs=1e-6)
  assert float(second.kf.x[radard.ACCEL][0]) == pytest.approx(0.0, abs=1e-6)


def test_civic_bosch_coalesced_incarnation_gap_injects_phantom_lead_accel(monkeypatch):
  # Pins the fragility of the reset above, so a regression cannot quietly widen it.
  #
  # radard polls modelV2 at DT_MDL (20 Hz) and reads the LATEST liveTracks through SubMaster, which
  # keeps no queue; card.py publishes liveTracks once per sweep (RadarInterface.update returns None
  # without a 0x2FF trigger), i.e. at ~14.35 Hz. The one-sweep gap above therefore survives only
  # while the sweep interval stays longer than the model period -- nominally true (14.35 Hz median,
  # p95 16.9 Hz on 000001df) but carried by a single message with no redundancy behind it.
  #
  # If that message is coalesced or dropped, radard never sees the identity leave, keeps the Track,
  # and the settled filter absorbs the identity change as a step. The lead KF has no notion of
  # incarnation -- the parser computes the boundary and does not propagate it.
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)

  radar_d = radard.RadarD(honda_bosch_a_radar=True)
  sm = FakeSubMaster(live_tracks_frame=1)
  sweep = _bosch_sweeps(radar_d, sm)

  for _ in range(30):
    sweep(make_radar_data(v_rel=-12.0, track_id=58, d_rel=70.0))
  first = radar_d.tracks[58]

  # Same sequence as the test above with the gap message missing, and nothing else changed.
  accels = []
  for _ in range(10):
    sweep(make_radar_data(v_rel=3.0, track_id=58, d_rel=45.0))
    accels.append(float(radar_d.tracks[58].kf.x[radard.ACCEL][0]))

  assert radar_d.tracks[58] is first, "no gap was observed, so the Track is never reconstructed"
  assert first.cnt == 40

  # Both objects are at constant velocity: the true lead acceleration is 0 throughout. The filter
  # reports an acceleration that never happened, ~0.92 m/s^2 per m/s of identity step, peaking near
  # 0.5 s and taking ~2.2 s to fall back under 0.5 m/s^2. For scale, D-042 records a 6 m/s step
  # injected by a vision fallback driving a measured -3.51 m/s^2 brake on 000001f3.
  assert max(accels) > 9.0
  assert accels[6] == pytest.approx(13.73, abs=0.05)


def test_civic_bosch_separates_kf_and_model_lead_probability_timing():
  radar_d = radard.RadarD(honda_bosch_a_radar=True)

  assert radar_d.kalman_params.A[0][1] == pytest.approx(radard.HONDA_BOSCH_A_RADAR_TS)
  assert radar_d.lead_prob_filters[0].dt == pytest.approx(radard.DT_MDL)
  assert radar_d.lead_prob_filters[1].dt == pytest.approx(radard.DT_MDL)


def test_model_lead_probability_filters_use_radar_timing_for_non_bosch_a_radars():
  radar_d = radard.RadarD(radar_ts=0.1)

  assert radar_d.kalman_params.A[0][1] == pytest.approx(0.1)
  # Nidec cadence can differ from Bosch-A cadence, so non-Bosch-A radars keep lead probabilities
  # on the same dt as the KF -- only Bosch-A decouples them onto model-loop timing (see
  # test_civic_bosch_separates_kf_and_model_lead_probability_timing above).
  assert radar_d.lead_prob_filters[0].dt == pytest.approx(0.1)


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


def make_onpath_track(track_id, *, d0=94.0, v_rel=radard.BOSCH_A_U11_LOW_RAIL_MPS, range_rate=None, seconds=1.05, offsets=(0.6, -0.9, 0.3, -0.4),
                      t0=100.0, existence=None):
  """Fresh measured Bosch-A sweeps of one track, with its path offset per sweep (yRel + model y at dRel).
  `existence`: RadarPoint.existence per sweep (cycled), or None for the unset default (-1)."""
  track = radard.Track(track_id, 0.0, radard.KalmanParams(radard.HONDA_BOSCH_A_RADAR_TS))
  rate = v_rel if range_rate is None else range_rate
  n = int(round(seconds * radard.BOSCH_A_FREQ_HZ)) + 1
  for i in range(n):
    t = t0 + i / radard.BOSCH_A_FREQ_HZ
    d = d0 + rate * (t - t0)
    track.update(d, 0.0, v_rel, v_rel + 13.5, True, True, t_now=t)
    track.update_onpath(t, offsets[i % len(offsets)], True, -1.0 if existence is None else existence[i % len(existence)])
  return track


def onpath_leads(tracks, *, v_ego=13.5, lead_msg=None, lead_prob=0.0, preferred_track_id=-1):
  """(leadOne as HEAD publishes it, radarState.leadOnpath or None), the way RadarD.update() builds them."""
  lead_one = radard.get_lead(
    v_ego, True, tracks, lead_msg if lead_msg is not None else make_lead(60.0, probability=lead_prob), v_ego,
    make_model_data(), False, make_plan(), make_toggles(), lead_prob=lead_prob, low_speed_override=True,
    preferred_track_id=preferred_track_id, honda_bosch_a_radar=True,
  )
  return lead_one, radard.get_onpath_lead(v_ego, tracks, SimpleNamespace(**lead_one), preferred_track_id)


def onpath_lead(tracks, **kwargs):
  return onpath_leads(tracks, **kwargs)[1]


def test_bosch_onpath_radar_only_track_is_adopted_after_a_second():
  # 00000297--f971b5896f 31:06-31:09: track 6, a stopped car on a curve, railed U11 -13.5 (1/64 log units), path offset within
  # ~1.3 m on single sweeps, model lead prob 0.00-0.28. HEAD published no lead until vision had it at 38 m.
  track = make_onpath_track(6, offsets=(0.7, -0.6, 1.2, -0.2, 0.4, -0.9, 0.1))
  lead_one, onpath = onpath_leads({6: track})
  assert onpath['status'] and onpath['radar'] and onpath['radarTrackId'] == 6
  # leadOne is exactly what HEAD publishes; the planner decides how much the on-path lead may brake
  assert not lead_one['status']


def test_bosch_onpath_adoption_needs_the_full_second():
  track = make_onpath_track(6, seconds=0.6)
  assert onpath_lead({6: track}) is None


@pytest.mark.parametrize("kwargs", [
  {"offsets": (0.3, -0.2, 0.4, 2.4, 0.1, -0.3, 0.2, 0.0, -0.1, 0.3, 0.2, -0.2, 0.1, 0.0, 0.2)},  # one sweep off path
  {"offsets": (1.1, -1.2, 0.9, 1.3)},                          # beside the path, never centred on it
  {"v_rel": -1.0, "d0": 60.0},                                 # not closing
  {"v_rel": -8.0, "range_rate": -1.0, "d0": 60.0},             # ranges flat while U11 says closing
  {"v_rel": -6.0, "range_rate": -12.0, "d0": 90.0},            # ranges closing twice as fast as an unrailed U11
])
def test_bosch_onpath_adoption_rejects(kwargs):
  track = make_onpath_track(9, **kwargs)
  assert onpath_lead({9: track}) is None


def test_bosch_onpath_adoption_coast_restarts_the_run():
  track = make_onpath_track(9, seconds=1.05)
  t = track.onpath_hist[-1][0] + 0.3
  track.update(track.dRel - 4.0, 0.0, radard.BOSCH_A_U11_LOW_RAIL_MPS, 0.0, False, False, t_now=t)
  track.update_onpath(t, float('nan'), False)
  assert onpath_lead({9: track}) is None


def test_bosch_onpath_adoption_never_replaces_a_radar_lead_and_needs_a_margin_over_vision():
  near = make_onpath_track(6, d0=60.0)
  # 297 46:50: the only lead was vision at 118 m, 4 m to the side of the radar car at 86 m, so they never matched

  def side_lead(d_rel):
    lead_msg = make_lead(d_rel)
    lead_msg.y = [4.0]
    return lead_msg

  lead_one, onpath = onpath_leads({6: near}, lead_msg=side_lead(near.dRel + 10.0), lead_prob=0.9)
  assert lead_one['status'] and not lead_one['radar']
  assert onpath['radarTrackId'] == 6
  lead_one, onpath = onpath_leads({6: near}, lead_msg=side_lead(near.dRel + 3.0), lead_prob=0.9)
  assert lead_one['status'] and not lead_one['radar'] and onpath is None
  # a vision-matched radar leadOne (the lift): leadOnpath is withdrawn and leadOne has full authority
  tracks = {2: make_track(2, 70.0, 10), 6: near}
  lead_one, onpath = onpath_leads(tracks, lead_msg=make_lead(70.0), lead_prob=0.99)
  assert lead_one['radarTrackId'] == 2 and onpath is None
  lead_one, onpath = onpath_leads({6: near}, lead_msg=make_lead(near.dRel), lead_prob=0.99)
  assert lead_one['radar'] and lead_one['radarTrackId'] == 6 and onpath is None


def test_bosch_onpath_lead_is_held_while_it_stays_on_the_path():
  track = make_onpath_track(6)
  assert onpath_lead({6: track})['radarTrackId'] == 6
  # later sweeps widen past the adoption test; the held track needs only its unbroken on-path run
  t = track.onpath_hist[-1][0]
  for i in range(1, 10):
    track.update(track.dRel - 1.0, 0.0, radard.BOSCH_A_U11_LOW_RAIL_MPS, 0.0, True, True, t_now=t + i / radard.BOSCH_A_FREQ_HZ)
    track.update_onpath(t + i / radard.BOSCH_A_FREQ_HZ, 1.6, True)
  assert onpath_lead({6: track}) is None
  assert onpath_lead({6: track}, preferred_track_id=6)['radarTrackId'] == 6


# 00000298--c4d2a4acbc 1018.35: track 2, born at 42 m, U11 railed at -13.5 (1/64 log units), ranges closing at -15.96 m/s (band edge
# -16.00 at 1/64, -14.5 at 1/72), path median 0.76 m (limit 0.8); OBJECT_EXISTENCE_PROBABILITY fell 59 -> 0 over the window (median 0.055).
BLIP_GEOMETRY = {"d0": 42.1, "v_rel": radard.BOSCH_A_U11_LOW_RAIL_MPS, "range_rate": -15.96, "offsets": (0.76, 0.7, 0.9, 0.5, 0.8, 1.1, 0.6)}
BLIP_EXISTENCE = tuple(r / 127.0 for r in (59, 50, 40, 30, 20, 12, 7, 5, 3, 1, 0, 0, 0, 0, 0, 0))


def test_bosch_onpath_adoption_blocked_by_low_median_existence():
  track = make_onpath_track(2, existence=BLIP_EXISTENCE, **BLIP_GEOMETRY)
  lead_one, onpath = onpath_leads({2: track})
  assert onpath is None
  # nothing else moves: the track is still there with its measured state, and leadOne is what HEAD publishes
  assert not lead_one['status'] and track.onpath_hist and not track.onpath_adopted


def test_bosch_onpath_existence_negative_control_same_geometry_is_adopted():
  # the blip's geometry alone passes every other gate, so the block above is the existence gate and nothing else
  assert onpath_lead({2: make_onpath_track(2, **BLIP_GEOMETRY)})['radarTrackId'] == 2
  # and a real car's value passes: 263 track 25, the lowest real adoption median seen (0.535)
  real = make_onpath_track(2, existence=(0.535,), **BLIP_GEOMETRY)
  assert onpath_lead({2: real})['radarTrackId'] == 2


def test_bosch_onpath_existence_uses_the_median_not_one_zero_sweep():
  # 270 track 63 / 280 track 7: real cars with single sweeps at existence 0 inside a 0.92-0.98 median window
  ex = (0.976,) * 6 + (0.0,)
  assert onpath_lead({6: make_onpath_track(6, existence=ex, offsets=(0.7, -0.6, 1.2, -0.2, 0.4, -0.9, 0.1))}) \
    is not None
  # boundary: a window median just under the floor blocks, just over adopts
  floor = radard.ONPATH_ADOPT_MIN_MEDIAN_EXISTENCE
  assert onpath_lead({6: make_onpath_track(6, existence=(floor - 0.01,))}) is None
  assert onpath_lead({6: make_onpath_track(6, existence=(floor + 0.01,))})['radarTrackId'] == 6


def test_bosch_onpath_existence_does_not_drop_a_held_lead():
  track = make_onpath_track(6, existence=(0.98,))
  assert onpath_lead({6: track})['radarTrackId'] == 6
  # existence collapses on the next second of on-path sweeps: a held lead is not re-checked
  t = track.onpath_hist[-1][0]
  for i in range(1, 16):
    tt = t + i / radard.BOSCH_A_FREQ_HZ
    track.update(track.dRel - 1.0, 0.0, radard.BOSCH_A_U11_LOW_RAIL_MPS, 0.0, True, True, t_now=tt)
    track.update_onpath(tt, 0.3, True, 0.0)
  assert onpath_lead({6: track}, preferred_track_id=6)['radarTrackId'] == 6
  # the same window would not be NEWLY adopted
  assert onpath_lead({6: track}) is None


def test_bosch_onpath_existence_unset_keeps_the_old_behaviour():
  # -1 (every other radar, and logs recorded before RadarPoint.existence) is ignored, so the blip is adopted as before
  assert onpath_lead({2: make_onpath_track(2, existence=(-1.0,), **BLIP_GEOMETRY)})['radarTrackId'] == 2
  # a window where only some sweeps carry a value uses those values only
  mixed = make_onpath_track(6, existence=(-1.0, -1.0, 0.9))
  assert onpath_lead({6: mixed})['radarTrackId'] == 6
  mixed_low = make_onpath_track(6, existence=(-1.0, -1.0, 0.05))
  assert onpath_lead({6: mixed_low}) is None


def test_bosch_onpath_adoption_is_not_used_below_the_low_speed_override_speed():
  track = make_onpath_track(6, d0=45.0, v_rel=-3.0)
  assert onpath_lead({6: track}, v_ego=3.0) is None


# BOSCH_A_LEAD_ACCEL_TAU_RADAR_DT: aLeadTau steps only on fresh Bosch-A sweeps (~14.35 Hz) but is
# built with DT_MDL, so its wall-clock decay is ~40 % slower than written. These pin the default-off
# behaviour and show the flag restores the 20 Hz wall-clock rates. Unit tests only, no replay.
def _a_lead_tau_after(track, seconds, decay):
  steps = int(round(seconds * radard.BOSCH_A_FREQ_HZ)) if track.aLeadTau.dt != radard.DT_MDL else int(round(seconds / radard.DT_MDL))
  for _ in range(steps):
    if decay:
      track.aLeadTau.update(0.0)
    else:
      track.aLeadTau.x = min(max(track.aLeadTau.x, 1e-2) * track.aLeadTauGrowth, radard._LEAD_ACCEL_TAU)
  return track.aLeadTau.x


def test_bosch_a_lead_accel_tau_timebase_default_off_is_unchanged(monkeypatch):
  monkeypatch.setattr(radard, "BOSCH_A_LEAD_ACCEL_TAU_RADAR_DT", False)
  radar_d = radard.RadarD(honda_bosch_a_radar=True)
  assert radar_d.a_lead_tau_dt == radard.DT_MDL
  track = radard.Track(1, 10.0, radar_d.kalman_params, radar_d.a_lead_tau_dt)
  assert track.aLeadTau.dt == radard.DT_MDL
  assert track.aLeadTauGrowth == pytest.approx(1.1)


def test_bosch_a_lead_accel_tau_timebase_flag_is_bosch_a_only(monkeypatch):
  monkeypatch.setattr(radard, "BOSCH_A_LEAD_ACCEL_TAU_RADAR_DT", True)
  assert radard.RadarD(honda_bosch_a_radar=True).a_lead_tau_dt == pytest.approx(radard.HONDA_BOSCH_A_RADAR_TS)
  assert radard.RadarD(radar_ts=0.1).a_lead_tau_dt == radard.DT_MDL


def test_bosch_a_lead_accel_tau_timebase_on_by_default():
  # baked in 2026-10-04 (STATUS 204): Bosch-A steps aLeadTau on the radar period, other radars keep DT_MDL.
  assert radard.BOSCH_A_LEAD_ACCEL_TAU_RADAR_DT
  assert radard.RadarD(honda_bosch_a_radar=True).a_lead_tau_dt == pytest.approx(radard.HONDA_BOSCH_A_RADAR_TS)
  assert radard.RadarD(radar_ts=0.1).a_lead_tau_dt == radard.DT_MDL


def test_bosch_a_lead_accel_tau_timebase_matches_20hz_wall_clock_rates():
  kp = radard.KalmanParams(radard.HONDA_BOSCH_A_RADAR_TS)
  ref = radard.Track(1, 10.0, kp)  # what the code intends: one step per 50 ms
  ref_decay = _a_lead_tau_after(ref, 1.0, decay=True)

  # today on Bosch-A: DT_MDL filter stepped at 14.35 Hz decays too slowly
  legacy = radard.Track(1, 10.0, kp)
  for _ in range(int(round(radard.BOSCH_A_FREQ_HZ))):
    legacy.aLeadTau.update(0.0)
  legacy_decay = legacy.aLeadTau.x
  assert legacy_decay > ref_decay * 1.5

  fixed = radard.Track(1, 10.0, kp, radard.HONDA_BOSCH_A_RADAR_TS)
  assert _a_lead_tau_after(fixed, 1.0, decay=True) == pytest.approx(ref_decay, rel=0.1)

  ref.aLeadTau.x = 0.05
  fixed.aLeadTau.x = 0.05
  assert _a_lead_tau_after(fixed, 0.5, decay=False) == pytest.approx(_a_lead_tau_after(ref, 0.5, decay=False), rel=0.05)


def test_bosch_a_lead_accel_tau_timebase_does_not_change_published_points(monkeypatch):
  toggles = make_toggles()
  monkeypatch.setattr(radard, "get_starpilot_toggles", lambda *_args: toggles)
  published = []
  for flag in (False, True):
    monkeypatch.setattr(radard, "BOSCH_A_LEAD_ACCEL_TAU_RADAR_DT", flag)
    radar_d = radard.RadarD(honda_bosch_a_radar=True)
    for frame in range(1, 6):
      radar_d.update(FakeSubMaster(live_tracks_frame=frame), make_radar_data(measured=True, v_rel=-1.0 * frame))
    published.append([(i, t.dRel, t.vRel, t.measured, t.vLeadK, t.aLeadK) for i, t in sorted(radar_d.tracks.items())])
  # same points, same KF state; only aLeadTau differs
  assert published[0] == published[1]
  assert [p[0] for p in published[0]] == [1]


# P1 range-first lead filter (report §12.3; STATUS 204)
def _run_range_kf(a_lead_after, t_brake=3.0, t_end=5.0, noise=0.0, walk=None, seed=0):
  rng = np.random.default_rng(seed)
  kf = radard.RangeLeadKF()
  h = 1 / 14.35
  t, d, vl, ve = 0.0, 50.0, 25.0, 25.0
  while t < t_end:
    vl = max(vl + (a_lead_after if t >= t_brake else 0.0) * h, 0.0)
    d += (vl - ve) * h
    t += h
    z = d + rng.normal(0.0, noise) + (walk(t) if walk else 0.0)
    kf.update(t, z, ve, 25.0)
  return kf


def test_range_kf_tracks_a_braking_lead():
  kf = _run_range_kf(-3.0, noise=0.07)
  assert kf.healthy
  assert kf.a_lead < -2.0
  assert kf.v_lead < 25.0 - 3.0


def test_range_kf_gross_outlier_is_not_absorbed():
  kf = _run_range_kf(0.0, t_end=3.0, walk=lambda t: 5.0 if abs(t - 2.5) < 0.04 else 0.0)
  assert abs(kf.a_lead) < 0.5


def test_range_kf_restarts_on_a_range_step():
  # a persistent 3 m jump (re-association) restarts the filter, which then publishes nothing for a while
  kf = _run_range_kf(0.0, t_end=3.0, walk=lambda t: 3.0 if t > 2.9 else 0.0)
  assert not kf.healthy


def _kf_lead(a_lead=-3.0, d_rel=30.0, y_rel=0.0, age=2.0):
  track = SimpleNamespace(range_kf=_run_range_kf(a_lead, noise=0.0), t_first=0.0, t_last=age)
  lead = dict(status=True, radar=True, dRel=d_rel, yRel=y_rel, vRel=0.0, vLead=25.0, vLeadK=25.0, aLeadK=0.0)
  return lead, track


def _vision(a, prob=0.9, v=19.0):
  # default v: the _kf_lead KF's own speed (25 m/s, -3 m/s^2 for 2 s), i.e. the camera agrees on size
  return SimpleNamespace(prob=prob, a=[a], v=[v])


def _adjust(lead, track, v_ego, vis, n=20, t0=0.0):
  out = lead
  for k in range(n):
    out = radard.range_lead_kf_adjust(lead, track, v_ego, vis, t0 + k * radard.DT_MDL)
  return out


def test_range_kf_adjust_adds_braking_only_when_camera_agrees():
  lead, track = _kf_lead()
  out = _adjust(lead, track, 25.0, _vision(-2.5))
  assert out['aLeadK'] == pytest.approx(-radard.RANGE_LEAD_KF_MAX_ACCEL_ADD)
  assert out['vLead'] < lead['vLead'] and out['vRel'] < lead['vRel'] and out['vLeadK'] < lead['vLeadK']
  assert out['dRel'] == lead['dRel']
  # camera not braking, unsure, or absent: native lead untouched
  for vis in (_vision(0.0), _vision(-1.0, prob=0.3), None):
    lead, track = _kf_lead()
    assert _adjust(lead, track, 25.0, vis) == lead


@pytest.mark.parametrize("kw,v_ego", [
  (dict(d_rel=5.0), 25.0), (dict(y_rel=2.0), 25.0), (dict(age=0.5), 25.0), ({}, 3.0),
])
def test_range_kf_adjust_gates(kw, v_ego):
  lead, track = _kf_lead(**kw)
  assert _adjust(lead, track, v_ego, _vision(-1.0)) == lead


def test_range_kf_adjust_bounded_by_camera_size():
  # replay 0000026b 11:40: camera lead closing ~2 m/s and braking -0.4, range KF far harder
  lead, track = _kf_lead()
  out = _adjust(lead, track, 25.0, _vision(-0.4, v=24.0), n=40)
  v_floor = 24.0 - radard.RANGE_LEAD_KF_VISION_V_MARGIN
  assert out['vLead'] >= v_floor - radard.RANGE_LEAD_KF_VREL_DEADBAND - 1e-6
  assert lead['vLead'] - out['vLead'] < 25.0 - track.range_kf.v_lead
  # accel floor -1.4 is not 0.5 below native 0: decel added up to that floor only
  assert out['aLeadK'] >= -0.4 - radard.RANGE_LEAD_KF_VISION_A_MARGIN - 1e-6
  # the camera agrees on size: the full correction
  lead, track = _kf_lead()
  out = _adjust(lead, track, 25.0, _vision(-2.5, v=19.0), n=40)
  assert out['vLead'] == pytest.approx(track.range_kf.v_lead + radard.RANGE_LEAD_KF_VREL_DEADBAND, abs=1e-6)


def test_range_kf_adjust_skips_when_camera_sees_less_closing_than_radar():
  # replay 0000026b 11:40: native radar closing 6.5 m/s, camera 2.1 m/s and braking -0.34
  lead, track = _kf_lead()
  lead.update(vRel=-6.5, vLead=21.3 - 6.5, vLeadK=21.3 - 6.5)
  assert _adjust(lead, track, 21.3, _vision(-0.34, v=21.3 - 2.1), n=40) == lead
  # camera closing at least the radar's (268 4:52: 6.1 vs 4.5): corrected
  lead, track = _kf_lead()
  lead.update(vRel=-4.5, vLead=25.0 - 4.5, vLeadK=25.0 - 4.5)
  assert _adjust(lead, track, 25.0, _vision(-0.34, v=25.0 - 6.1), n=40)['vLead'] < lead['vLead']


def test_range_kf_adjust_never_past_camera():
  # replay 2d6 21:44: native radar closing 1.1, camera 0.2 and braking -0.66; KF far harder. Nothing past the camera.
  lead, track = _kf_lead()
  lead.update(vRel=-1.1, vLead=15.4 - 1.1, vLeadK=15.4 - 1.1, aLeadK=-0.55)
  out = _adjust(lead, track, 15.4, _vision(-0.66, v=15.4 - 0.2), n=40)
  assert out['vLead'] >= lead['vLead'] - 1e-6
  assert out['aLeadK'] >= -0.66 - 1e-6


def test_range_kf_adjust_skips_lead_drifting_out_of_lane():
  lead, track = _kf_lead()
  prev = 0.0
  for k in range(30):
    drifting = dict(lead, yRel=0.2 + 1.0 * k * radard.DT_MDL)  # 1 m/s outward, past 1.5 m (geometry gate) at k=26
    out = radard.range_lead_kf_adjust(drifting, track, 25.0, _vision(-1.0), k * radard.DT_MDL)
    cur = drifting['aLeadK'] - out['aLeadK']
    if drifting['yRel'] > radard.RANGE_LEAD_KF_DRIFT_MIN_Y_M + 0.1:
      assert cur <= prev  # nothing new once drifting; what built up before bleeds off
    prev = cur
  assert out == drifting
  # same lead held in lane: corrected
  lead, track = _kf_lead()
  assert _adjust(dict(lead, yRel=0.8), track, 25.0, _vision(-1.0))['aLeadK'] < lead['aLeadK']


def test_range_kf_adjust_never_removes_braking():
  # range sees the lead accelerating while U11 says braking: nothing is relaxed
  lead, track = _kf_lead(a_lead=+2.0)
  lead.update(aLeadK=-2.0, vLead=10.0, vLeadK=10.0, vRel=-15.0)
  out = _adjust(lead, track, 25.0, _vision(-1.0))
  assert out['aLeadK'] == -2.0 and out['vLead'] == 10.0 and out['vRel'] == -15.0


def test_range_kf_adjust_is_slew_limited():
  # replay 00000268: gates chatter; one passing frame must not publish the full correction
  lead, track = _kf_lead()
  dt = radard.DT_MDL
  out = _adjust(lead, track, 25.0, _vision(-1.0), n=1)
  assert lead['aLeadK'] - out['aLeadK'] <= radard.RANGE_LEAD_KF_ADJ_A_RISE * dt + 1e-9
  assert lead['vRel'] - out['vRel'] <= radard.RANGE_LEAD_KF_ADJ_V_RISE * dt + 1e-9
  # built up, then the camera stops agreeing: the correction bleeds off at the fall rate, not at once
  full = _adjust(lead, track, 25.0, _vision(-1.0), t0=dt)
  prev = lead['aLeadK'] - full['aLeadK']
  t = 21 * dt
  for _ in range(40):
    out = radard.range_lead_kf_adjust(lead, track, 25.0, _vision(0.0), t)
    cur = lead['aLeadK'] - out['aLeadK']
    fall = max(radard.RANGE_LEAD_KF_ADJ_A_FALL, prev / radard.RANGE_LEAD_KF_ADJ_FALL_TAU_S) * dt
    assert 0.0 <= cur <= prev and prev - cur <= fall + 1e-9
    prev, t = cur, t + dt
  # the 8 m/s closing cap is gone within ~2.4 s, the 1.5 m/s^2 decel within ~1 s
  assert out['aLeadK'] == lead['aLeadK']
  for _ in range(10):
    out = radard.range_lead_kf_adjust(lead, track, 25.0, _vision(0.0), t)
    t += dt
  assert out == lead


def test_range_kf_adjust_drops_stale_correction():
  lead, track = _kf_lead()
  _adjust(lead, track, 25.0, _vision(-1.0))
  # not leadOne for a while, then back with the camera not braking: nothing carried over
  assert radard.range_lead_kf_adjust(lead, track, 25.0, _vision(0.0), 10.0) == lead


# D-077 birth-rail ramp (both switches OFF by default; replay comparison only, not driven).
def _born_track(u11, closing, v_ego=22.0, seconds=3.0, d0=60.0, u11_first=None):
  """Feed a fresh track at 15 Hz; U11 `u11` (or `u11_first` for the first 0.6 s), range closing at `closing` m/s.
  Returns [(age, published vRel)]."""
  track = radard.Track(1, 0.0, radard.KalmanParams(radard.HONDA_BOSCH_A_RADAR_TS))
  out = []
  dt = 1.0 / 15.0
  for i in range(int(seconds / dt)):
    t = 100.0 + i * dt
    v = u11_first if (u11_first is not None and i * dt < 0.6) else u11
    track.update(d0 - closing * i * dt, 0.0, v, v + v_ego, True, measurement_update=True, t_now=t)
    out.append((i * dt, track.get_RadarState()["vRel"]))
  return out


def _at(rows, age):
  return min(rows, key=lambda r: abs(r[0] - age))[1]


def test_birth_rail_ramp_off_by_default_publishes_the_rail():
  assert not radard.BIRTH_RAIL_RAMP_LOW and not radard.BIRTH_RAIL_RAMP_HIGH
  rows = _born_track(radard.BOSCH_A_U11_LOW_RAIL_MPS, 4.0)
  assert all(v == radard.BOSCH_A_U11_LOW_RAIL_MPS for _, v in rows)


def test_birth_rail_low_ramp_moving_lead_eases_in_then_reaches_the_rail(monkeypatch):
  monkeypatch.setattr(radard, "bosch_a_birth_rail_ramp_low_enabled", lambda: True)
  rows = _born_track(radard.BOSCH_A_U11_LOW_RAIL_MPS, 4.0)
  # Range fit -4 m/s, ramp -12 * f(age): the published closing is the larger of the two, never past the rail.
  assert -6.0 < _at(rows, 0.6) < -3.5
  assert -10.5 < _at(rows, 1.5) < -8.0
  assert _at(rows, 2.6) == radard.BOSCH_A_U11_LOW_RAIL_MPS
  assert all(v >= radard.BOSCH_A_U11_LOW_RAIL_MPS for _, v in rows)
  # Before the first range fit (~0.3 s) the full rail is published; afterwards the ramp only moves toward the rail.
  assert _at(rows, 0.1) == radard.BOSCH_A_U11_LOW_RAIL_MPS
  vs = [v for a, v in rows if a >= 0.4]
  assert all(b <= a + 0.05 for a, b in zip(vs, vs[1:], strict=False))


@pytest.mark.parametrize("closing,v_ego", [(22.0, 22.0), (19.0, 22.0), (4.0, 10.0)])
def test_birth_rail_low_ramp_keeps_full_rail_for_possible_stopped_object_or_low_speed(monkeypatch, closing, v_ego):
  monkeypatch.setattr(radard, "bosch_a_birth_rail_ramp_low_enabled", lambda: True)
  rows = _born_track(radard.BOSCH_A_U11_LOW_RAIL_MPS, closing, v_ego=v_ego)
  assert all(v <= radard.BOSCH_A_U11_LOW_RAIL_MPS for a, v in rows if a >= 0.4)


def test_birth_rail_ramp_ignores_tracks_that_reach_the_rail_later(monkeypatch):
  monkeypatch.setattr(radard, "bosch_a_birth_rail_ramp_low_enabled", lambda: True)
  rows = _born_track(radard.BOSCH_A_U11_LOW_RAIL_MPS, 4.0, u11_first=-5.0)
  assert all(v == radard.BOSCH_A_U11_LOW_RAIL_MPS for a, v in rows if a >= 0.6)


def test_birth_rail_high_ramp_publishes_less_opening_only(monkeypatch):
  monkeypatch.setattr(radard, "bosch_a_birth_rail_ramp_high_enabled", lambda: True)
  high = -radard.BOSCH_A_U11_LOW_RAIL_MPS
  rows = _born_track(high, -2.0)
  assert _at(rows, 0.5) < 6.0
  assert all(v <= high for _, v in rows)
  assert _at(rows, 2.6) == high
  # LOW stays off: a low-rail birth is untouched.
  assert all(v == radard.BOSCH_A_U11_LOW_RAIL_MPS for _, v in _born_track(radard.BOSCH_A_U11_LOW_RAIL_MPS, 4.0))
