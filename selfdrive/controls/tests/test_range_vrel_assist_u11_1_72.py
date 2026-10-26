"""The rail cases of test_range_vrel_assist.py at the production U11 scale, 1/72 m/s per count (D-074).

test_range_vrel_assist.py pins U11 back to 1/64 (rail -13.5) so the numbers logged under the old decode keep their
meaning. On the car the decode is 1/72 and the rail is -12.0, so without this file the rail logic at the scale the car
runs is covered by nothing (JamesL787/openpilot#17 review). Nothing here is patched to 1/64: every case reads radard's
own constants.

What this file is and is not:
- The range series are the recorded ones (the range channel does not depend on the U11 scale). The U11 side is
  RE-DERIVED: a lead closing faster than the rail reads the 1/72 rail, -12.0, where the logs show -13.5. No route was
  logged at 1/72, so these are static unit tests against synthetic U11, not replay evidence.
- Arithmetic cases: the correction is range_rate - rail, so it grows by 1.5 m/s (the rail moved up by 1.5).
- Gate cases: the gates whose threshold is tied to the rail (the D-071 NC veto: "3.5 m/s above the rail") moved with
  it and were NOT re-tuned. TestNcVetoAt172 pins what they do now so a change is visible; it is not a claim that this
  behaviour is right.
"""
import pytest

from openpilot.selfdrive.controls import radard
from openpilot.selfdrive.controls.radard import (
  RANGE_VREL_ASSIST_ARM_UPDATES,
  RANGE_VREL_ASSIST_MAX_CORRECTION_MPS,
  RANGE_VREL_LONG_SAMPLES,
)

DT = radard.HONDA_BOSCH_A_RADAR_TS
V_EGO = 20.0
Q = radard.BOSCH_A_U11_SCALE_MPS
RAIL = radard.BOSCH_A_U11_LOW_RAIL_MPS
SETTLE = RANGE_VREL_LONG_SAMPLES + RANGE_VREL_ASSIST_ARM_UPDATES - 1
RAIL_CASE = dict(d0=76.0, range_rate=-19.4)   # 000001f9 29:52 (D-041): range closing -19.4 m/s, U11 on the rail
ZIGZAG_05 = {i: (0.5 if i % 2 else -0.5) for i in range(40)}
ZIGZAG_08 = {i: (0.8 if i % 2 else -0.8) for i in range(40)}


def new_track(v_lead=V_EGO):
  return radard.Track(1, v_lead, radard.KalmanParams(DT))


def feed(track, n, *, d0, range_rate, v_rel=RAIL, v_ego=V_EGO, d_offsets=None):
  for i in range(n):
    t = i * DT
    d = d0 + range_rate * t + (d_offsets or {}).get(i, 0.0)
    track.update(d, 0.0, v_rel, v_ego + v_rel, True, True, t_now=t, range_assist=True)


def rail_glitch_series(track, n, *, u11, rate):
  """Same series as test_range_vrel_assist.rail_glitch_series: a 0.25 m range glitch every fifth sweep."""
  best, max_arm, first = 0.0, 0, None
  for i in range(n):
    t = i * DT
    track.update(80.0 + rate * t + (0.25 if i % 5 == 4 else 0.0), 0.0, u11, V_EGO + u11, True, True,
                 t_now=t, range_assist=True)
    best = max(best, track.range_assist_correction)
    max_arm = max(max_arm, track.range_assist_arm_count)
    if first is None and track.range_assist_correction > 0.0:
      first = i
  return best, max_arm, first


@pytest.fixture
def pre130(monkeypatch):
  monkeypatch.setattr(radard, "RANGE_VREL_RAIL_FAST", False)


class TestProductionScale:
  def test_scale_and_rail(self):
    assert pytest.approx(1.0 / 72.0) == Q
    assert RAIL == pytest.approx(-12.0)
    assert radard.ONPATH_ADOPT_RAIL_VREL_MPS == pytest.approx(RAIL + radard.ONPATH_ADOPT_RAIL_VREL_MARGIN_MPS)
    assert -11.99 > RAIL + Q / 2, "-11.99 is OFF the rail at 1/72"
    assert -13.5 < RAIL, "a -13.5 U11 value can not be produced at 1/72; tests that mean the rail must use RAIL"


class TestRecordedRailCaseAt172:
  def test_rail_is_corrected_to_the_range_rate(self):
    track = new_track()
    feed(track, SETTLE, **RAIL_CASE)
    assert track.range_assist_active
    assert track.range_assist_correction == pytest.approx(19.4 - 12.0, abs=0.05)   # 7.4 (5.9 at 1/64)
    assert track.get_RadarState()["vRel"] == pytest.approx(-19.4, abs=0.05)

  def test_recorded_gap_fits_under_the_cap(self):
    """7.4 m/s against the 8.0 m/s cap: the headroom fell from 2.1 to 0.6 m/s. A recorded closing faster than
    -20.0 m/s on the rail is now cut by the cap at 1/72 where it was not at 1/64."""
    assert 19.4 - 12.0 < RANGE_VREL_ASSIST_MAX_CORRECTION_MPS
    assert 19.4 - 12.0 > RANGE_VREL_ASSIST_MAX_CORRECTION_MPS - 1.0


class TestZeroSpeedCapAt172:
  def test_correction_stops_at_a_stationary_lead(self):
    # The 1/64 case had the lead at 1.5 m/s with v_ego 15.0. At the 1/72 rail the same lead is v_ego 13.5.
    track = new_track(v_lead=1.5)
    feed(track, SETTLE, d0=80.0, range_rate=-16.0, v_ego=13.5)
    assert track.range_assist_correction == pytest.approx(1.5)
    assert track.get_RadarState()["vLead"] == pytest.approx(0.0, abs=1e-9)
    assert track.vRel - track.vRelRange == pytest.approx(4.0, abs=0.01)       # 2.5 at 1/64
    assert track.vRel - track.vRelRangeLong == pytest.approx(4.0, abs=0.01)


class TestLongResidualAt172:
  def test_moderate_scatter_still_arms(self):
    track = new_track()
    feed(track, 40, **RAIL_CASE, d_offsets=ZIGZAG_05)
    assert track.range_assist_active
    assert track.range_assist_correction == pytest.approx(7.4, abs=0.1)

  def test_large_scatter_is_inert(self):
    track = new_track()
    feed(track, 40, **RAIL_CASE, d_offsets=ZIGZAG_08)
    assert track.range_assist_correction == 0.0


@pytest.mark.usefixtures("pre130")
class TestRailRuleAt172:
  def test_on_rail_the_long_fit_alone_arms(self):
    # Same 2.5 m/s excess over the rail as the 1/64 case (-16.0 against -13.5): same size, same arming sweep.
    best, _, first = rail_glitch_series(new_track(), 60, u11=RAIL, rate=RAIL - 2.5)
    assert best == pytest.approx(2.577, abs=0.05)
    assert first == SETTLE - 1

  def test_one_quantum_above_the_rail_does_not(self):
    best, max_arm, _ = rail_glitch_series(new_track(), 60, u11=RAIL + Q, rate=RAIL - 2.5 + Q)
    assert best == 0.0
    assert max_arm == RANGE_VREL_ASSIST_ARM_UPDATES - 1

  def test_control_without_the_rail_rule(self, monkeypatch):
    monkeypatch.setattr(radard, "BOSCH_A_U11_LOW_RAIL_MPS", -99.0)
    best, max_arm, _ = rail_glitch_series(new_track(), 60, u11=RAIL, rate=RAIL - 2.5)
    assert best == 0.0
    assert max_arm == RANGE_VREL_ASSIST_ARM_UPDATES - 1


def _veto_ab(monkeypatch, rate, d0, ncs, nc_sigma=30, n=25):
  """RAIL_FAST on the 1/72 rail with per-sweep NC; returns (published vRel switch off, switch on)."""
  def run():
    track, out = new_track(v_lead=30.0 + RAIL), []
    for i in range(n):
      t = i * DT
      track.update(d0 + rate * t, 0.0, RAIL, 30.0 + RAIL, True, True, t_now=t, range_assist=True,
                   nc_vrel=ncs[i % len(ncs)], nc_valid=True, nc_sigma=nc_sigma)
      out.append(track.vRel - track.range_assist_correction)
    return out
  off = run()
  monkeypatch.setattr(radard, "RANGE_VREL_RAIL_NC_VETO", True)
  on = run()
  return off, on


class TestNcVetoAt172:
  """D-071 (PROPOSED, default OFF) fires when the NC median is RANGE_VREL_RAIL_NC_VETO_ABOVE_RAIL_MPS (3.5) above the
  rail. NC is -NC*dRel and does not depend on the U11 scale, but the rail moved from -13.5 to -12.0, so the firing
  point moved from NC >= -10.0 to NC >= -8.5. The 3.5 was set on 1/64 replays and is UNTUNED at 1/72. These tests pin
  the current behaviour; they do not say it is right."""

  def test_threshold_moved_with_the_rail(self):
    assert RAIL + radard.RANGE_VREL_RAIL_NC_VETO_ABOVE_RAIL_MPS == pytest.approx(-8.5)

  def test_297_shape_no_longer_vetoes(self, monkeypatch):
    # 297 48:12 tid 4: NC median -8.4..-8.7, under the 1/72 threshold. At 1/64 this case vetoed the excursion.
    off, on = _veto_ab(monkeypatch, -16.2, 72.0, [-9.2, -8.0, -9.8, -8.7, -8.4, -9.5], nc_sigma=40)
    assert min(off) < -16.0, "RAIL_FAST must publish the excursion in the flag-off control"
    assert on == off

  def test_278_shape_no_longer_fires(self, monkeypatch):
    # 278 4:38.5 tid 61: NC median about -9.6. At 1/64 the veto fired here and removed a correction that ground truth
    # said was real (D-071). At 1/72 it does not fire.
    off, on = _veto_ab(monkeypatch, -16.2, 66.0, [-9.6, -9.8, -9.5, -9.7, -9.6], nc_sigma=15)
    assert min(off) < -16.0
    assert on == off

  def test_mechanism_still_fires_above_the_moved_threshold(self, monkeypatch):
    """Negative control: without it, the two tests above would pass on a veto that never fires at all."""
    off, on = _veto_ab(monkeypatch, -16.2, 72.0, [-8.0])
    assert min(off) < -16.0
    assert all(v == RAIL for v in on), "the veto publishes the rail itself (D-041 bound)"


def test_far_rail_bound_still_lifts_route_298_bm3():
  """FAR_RAIL_VISION_BOUND does not depend on the scale beyond 'on the rail'. The floor is the same -7.5 m/s, but the
  lift over the rail is 4.5 m/s at 1/72 (it was 6.0 at 1/64)."""
  from types import SimpleNamespace
  lead = SimpleNamespace(dRel=121.0, vRel=RAIL, vRelRangeDerived=float('nan'), radar=True, status=True)
  hist = [radard.far_rail_model_sample(SimpleNamespace(prob=0.5, x=[121.0 + radard.RADAR_TO_CAMERA], v=[17.0]))
          for _ in range(20)]
  floor = radard.far_rail_vrel_floor(lead, hist, 21.5)
  assert floor == pytest.approx(17.0 - 21.5 - radard.FAR_RAIL_MARGIN_MPS)
  assert floor - RAIL == pytest.approx(4.5)
