"""ADJACENT_RAIL_GATE: a Bosch-A track whose U11 sits on the rail while its range closes faster is not a leadLeft/leadRight.

Shape of 0000028f seg 6 track 49: a stationary roadside return at yRel ~3, closing at ~vEgo (21 m/s) while U11
reads the low rail (-13.5 as logged at 1/64; -12.0 at 1/72), published as a ~16 mph left-lane car.
"""
from types import SimpleNamespace

from openpilot.selfdrive.controls import radard

RAIL = radard.BOSCH_A_U11_LOW_RAIL_MPS
DT = 1.0 / 14.35  # Bosch-A sweep period
V_EGO = 21.0


def lanes():
  def line(y):
    return SimpleNamespace(x=[0.0, 200.0], y=[y, y])
  # model y == -yRel; laneLines[1] is the left boundary, [2] the right
  return SimpleNamespace(laneLines=[line(-5.4), line(-1.8), line(1.8), line(5.4)])


def drive(track, n, *, v_rel, closing, d0=75.0, y_rel=3.2, t0=0.0):
  """n measured sweeps: U11 reads v_rel while the range closes at `closing` m/s."""
  for i in range(n):
    t = t0 + i * DT
    track.update(d0 - closing * i * DT, y_rel, v_rel, V_EGO + v_rel, True, True, t_now=t)
  return t0 + n * DT


def new_track(identifier=49):
  return radard.Track(identifier, V_EGO + RAIL, radard.KalmanParams(radard.HONDA_BOSCH_A_RADAR_TS))


def test_railed_stationary_track_is_not_an_adjacent_lead_on_bosch_a():
  track = new_track()
  drive(track, 12, v_rel=RAIL, closing=V_EGO)
  assert track.rail_range_inconsistent
  assert track.potential_adjacent_lead(True, False, lanes())  # the lane test alone would take it
  assert not radard.get_adjacent_lead({49: track}, False, lanes(), left=True, honda_bosch_a=True)['status']


def test_gate_is_bosch_a_only():
  track = new_track()
  drive(track, 12, v_rel=RAIL, closing=V_EGO)
  assert radard.get_adjacent_lead({49: track}, False, lanes(), left=True, honda_bosch_a=False)['status']


def test_gate_can_be_disabled(monkeypatch):
  monkeypatch.setattr(radard, "ADJACENT_RAIL_GATE", False)
  track = new_track()
  drive(track, 12, v_rel=RAIL, closing=V_EGO)
  assert radard.get_adjacent_lead({49: track}, False, lanes(), left=True, honda_bosch_a=True)['status']


def test_railed_track_whose_range_agrees_stays_eligible():
  track = new_track()
  drive(track, 12, v_rel=RAIL, closing=-RAIL)
  assert not track.rail_range_inconsistent
  assert radard.get_adjacent_lead({49: track}, False, lanes(), left=True, honda_bosch_a=True)['status']


def test_off_rail_moving_car_stays_eligible():
  track = new_track()
  drive(track, 12, v_rel=-2.0, closing=2.0)
  assert not track.rail_range_inconsistent
  assert radard.get_adjacent_lead({49: track}, False, lanes(), left=True, honda_bosch_a=True)['status']


def test_latch_needs_consecutive_updates_and_clears_off_the_rail():
  track = new_track()
  # the short fit needs RANGE_VREL_SAMPLES sweeps; the latch then needs ADJACENT_RAIL_GATE_UPDATES more
  t = drive(track, radard.RANGE_VREL_SAMPLES + radard.ADJACENT_RAIL_GATE_UPDATES - 2, v_rel=RAIL, closing=V_EGO)
  assert not track.rail_range_inconsistent
  t = drive(track, 1, v_rel=RAIL, closing=V_EGO, d0=track.dRel - V_EGO * DT, t0=t)
  assert track.rail_range_inconsistent
  drive(track, 1, v_rel=RAIL + 1.0, closing=V_EGO, d0=track.dRel - V_EGO * DT, t0=t)
  assert not track.rail_range_inconsistent


def test_duplicate_cycle_does_not_advance_the_latch():
  track = new_track()
  t = drive(track, radard.RANGE_VREL_SAMPLES + radard.ADJACENT_RAIL_GATE_UPDATES - 2, v_rel=RAIL, closing=V_EGO)
  count = track.rail_range_count
  track.update(track.dRel, track.yRel, RAIL, V_EGO + RAIL, True, False, t_now=t - DT)
  assert track.rail_range_count == count
  assert not track.rail_range_inconsistent


def test_closer_railed_point_does_not_hide_a_real_adjacent_car():
  stationary = new_track(49)
  drive(stationary, 12, v_rel=RAIL, closing=V_EGO, d0=30.0)
  car = new_track(44)
  drive(car, 12, v_rel=-1.0, closing=1.0, d0=40.0)
  lead = radard.get_adjacent_lead({49: stationary, 44: car}, False, lanes(), left=True, honda_bosch_a=True)
  assert lead['status'] and lead['radarTrackId'] == 44
