"""Tests for the range-derived vRel assist (D-053 rework, TEST feature, default OFF).

The assist lets the range-LSQ closing rate correct the Bosch-A native U11 velocity, in ONE
direction only: it may report more closing, never less. Read the RANGE_VREL_ASSIST_* comment
blocks in radard.py before changing a number here -- every constant carries the evidence that set
it, and several of these tests exist only to make a specific failure mode visible.

The rework adds a ~1 s long fit that must AGREE with the short fit before arming, clear-only guards
(long-fit residual, span, ego-speed floor, backward-lead plausibility, rail rule, zero-speed cap),
and keeps the lead Kalman filter on native U11 so aLeadK never sees the correction. Every guard
has a negative control next to it that breaks the guard and proves the test notices (D-009).

The tests that matter most are the negative ones. This feature reads the range channel to check a
velocity channel, so it is BLIND to a range error. `TestTheRangeWalkFault`, `TestRecorded232Walk`
and `TestRecorded236Settle` pin that the recorded range faults leave the assist inert. If a future
change makes one of those fire, this feature has become a brake-harder amplifier for a fault the
branch has actually recorded.

Geometry and velocities are taken from recorded routes wherever a recorded number exists, so a
change that breaks one of these breaks against road data rather than an invented scenario (D-009).
Nothing here is road evidence FOR the assist: these are static unit tests against synthetic range
series, and the reworked assist has only been replayed open-loop, never run on a car.
"""
import math

import numpy as np
import pytest

from openpilot.selfdrive.controls import radard
from openpilot.selfdrive.controls.radard import (
  BOSCH_A_U11_LOW_RAIL_MPS,
  RANGE_VREL_ASSIST_ARM_UPDATES,
  RANGE_VREL_ASSIST_MAX_ABS_Y_REL_M,
  RANGE_VREL_ASSIST_MAX_CORRECTION_MPS,
  RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS,
  RANGE_VREL_ASSIST_MIN_D_REL_M,
  RANGE_VREL_LONG_SAMPLES,
)

DT = radard.HONDA_BOSCH_A_RADAR_TS   # ~0.0697 s, the physical Bosch-A sweep period
DT_MDL = 0.05                        # radard's own loop rate: 20 Hz, the model rate
V_EGO = 20.0
RAIL = BOSCH_A_U11_LOW_RAIL_MPS      # exactly -13.5: raw 0 against center 864 at 1/64 m/s
Q = radard.BOSCH_A_DIRECT_VREL_SCALE_MPS
SETTLE = RANGE_VREL_LONG_SAMPLES + RANGE_VREL_ASSIST_ARM_UPDATES - 1


def new_track(track_id: int = 1, v_lead: float = V_EGO) -> radard.Track:
  return radard.Track(track_id, v_lead, radard.KalmanParams(DT))


def feed(track, n, *, d0, range_rate, v_rel, y_rel=0.0, t0=0.0, dt=DT, v_ego=V_EGO,
         range_assist=True, measured=True, d_offsets=None, vision_closing=None, vision_assist=False):
  """Drive `track` through n Bosch-A sweeps of a constant-rate range series.

  `range_rate` is d(dRel)/dt in m/s -- negative closes. `v_rel` is what U11 claims, independently,
  so a test can make the two disagree by exactly the amount it wants. `d_offsets` injects a
  per-sample range error for the outlier tests. Returns the list of (t, dRel) actually fed.
  """
  fed = []
  for i in range(n):
    t = t0 + i * dt
    d = d0 + range_rate * (i * dt)
    if d_offsets is not None:
      d += d_offsets.get(i, 0.0)
    track.update(d, y_rel, v_rel, v_ego + v_rel, measured, measured,
                 t_now=t, range_assist=range_assist, vision_closing=vision_closing, vision_assist=vision_assist)
    fed.append((t, d))
  return fed


def feed_radard_cadence(track, n_cycles, *, d0, range_rate, v_rel, y_rel=0.0, v_ego=V_EGO,
                        range_assist=True, coast_sweeps=(), start_cycle=0):
  """Drive `track` the way RadarD actually drives it: a 20 Hz loop over a 14.35 Hz radar.

  Every other helper here feeds one Track.update per radar sweep, which is NOT what happens on the
  car. radard runs at the model rate, so roughly one cycle in four carries no new liveTracks
  message and RadarD passes `measured=False, measurement_update=False` with an UNCHANGED t_now and
  unchanged point data. That is a DUPLICATE, not a coast, and conflating the two made the assist
  unable to arm at all. `coast_sweeps` marks sweeps that do arrive but with the parser's measured
  bit clear -- a real coast, where t_now DOES advance. `start_cycle` continues an earlier call.

  Returns a (sweep_index, fresh, correction) trace, one entry per radard cycle.
  """
  trace = []
  last_sweep = int((start_cycle - 1) * DT_MDL / DT) if start_cycle > 0 else -1
  for k in range(start_cycle, start_cycle + n_cycles):
    sweep = int(k * DT_MDL / DT)
    fresh = sweep != last_sweep
    last_sweep = sweep
    t_now = sweep * DT
    measured = fresh and sweep not in coast_sweeps
    track.update(d0 + range_rate * t_now, y_rel, v_rel, v_ego + v_rel, measured, measured,
                 t_now=t_now, range_assist=range_assist)
    trace.append((sweep, fresh, track.range_assist_correction))
  return trace


@pytest.fixture
def pre130(monkeypatch):
  """Pin the pre-130 rail behaviour (no rail fast path) for tests written against the original
  15-sample long window and 5-update arm rule; the fast path has its own tests (TestRailFastPath)."""
  monkeypatch.setattr(radard, "RANGE_VREL_RAIL_FAST", False)


def settle(track, **kwargs):
  """Feed exactly enough sweeps to fill the long window and then arm: the long fit needs
  RANGE_VREL_LONG_SAMPLES samples before it exists, and arming needs RANGE_VREL_ASSIST_ARM_UPDATES
  qualifying updates, the first of which is the one that fills the window. Tests that patch
  RANGE_VREL_LONG_SAMPLES must feed an explicit count: SETTLE is bound at import."""
  return feed(track, SETTLE, **kwargs)


def peak(track, n, **kwargs):
  """Feed n sweeps one at a time and return the largest correction seen."""
  best = 0.0
  offsets = kwargs.pop("d_offsets", None) or {}
  d0, rate = kwargs.pop("d0"), kwargs.pop("range_rate")
  v_rel, v_ego = kwargs.pop("v_rel"), kwargs.pop("v_ego", V_EGO)
  y_rel = kwargs.pop("y_rel", 0.0)
  for i in range(n):
    t = i * DT
    track.update(d0 + rate * t + offsets.get(i, 0.0), y_rel, v_rel, v_ego + v_rel, True, True,
                 t_now=t, range_assist=True)
    best = max(best, track.range_assist_correction)
  assert not kwargs, kwargs
  return best


# ---------------------------------------------------------------------------------------------
# Default OFF
# ---------------------------------------------------------------------------------------------

class TestDefaultOff:
  def test_param_default_is_off(self):
    """A TEST feature must not change behaviour for anyone who has not opted in."""
    from openpilot.common.params import Params
    p = Params()
    p.remove("RangeDerivedVrel")
    assert p.get_bool("RangeDerivedVrel") is False

  def test_track_is_inert_without_the_flag(self):
    """Same geometry as the rail case below, which corrects hard when armed."""
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, range_assist=False)
    assert track.range_assist_correction == 0.0
    assert track.get_RadarState()["vRel"] == RAIL

  def test_radard_leaves_the_flag_off_for_non_bosch_a(self, monkeypatch):
    """The toggle is Bosch-A only: the param must not be consulted at all elsewhere."""
    radar_d = radard.RadarD(honda_bosch_a_radar=False)
    calls = []
    monkeypatch.setattr(radar_d, "_range_vrel_assist_enabled",
                        lambda: calls.append(1) or True)
    assert (radar_d.honda_bosch_a_radar and radar_d._range_vrel_assist_enabled()) is False
    assert calls == [], "the param was read on a car the assist can never apply to"

  def test_param_read_failure_falls_back_to_off(self, monkeypatch):
    """A device whose params_pyx.so predates RangeDerivedVrel raises on the read. That must
    degrade to the shipped U11 behaviour, not to an enabled feature."""
    radar_d = radard.RadarD(honda_bosch_a_radar=True)

    class Boom:
      def get_bool(self, _key):
        raise KeyError("RangeDerivedVrel")

    radar_d._range_assist_params = Boom()
    assert radar_d._range_vrel_assist_enabled() is False


# ---------------------------------------------------------------------------------------------
# One-sidedness -- the single most important property
# ---------------------------------------------------------------------------------------------

class TestOneSided:
  def test_range_claiming_less_closing_is_ignored(self):
    """U11 says -8, the range says -2. Acting on this would RELEASE braking. D-041/D-043 both
    forbid that direction: an understated closing rate still brakes, an overstated one does not."""
    track = new_track()
    settle(track, d0=60.0, range_rate=-2.0, v_rel=-8.0)
    assert track.range_assist_correction == 0.0
    assert not track.range_assist_active
    assert track.get_RadarState()["vRel"] == pytest.approx(-8.0)

  def test_opening_lead_with_closing_u11_is_ignored(self):
    track = new_track()
    settle(track, d0=60.0, range_rate=3.0, v_rel=-1.0)
    assert track.range_assist_correction == 0.0

  def test_correction_is_never_negative(self):
    armed = []
    for range_rate in (-20.0, -12.0, -6.0, -2.0, 0.0, 2.0, 6.0):
      track = new_track()
      settle(track, d0=70.0, range_rate=range_rate, v_rel=-5.0)
      assert track.range_assist_correction >= 0.0
      assert track.get_RadarState()["vRel"] <= -5.0 + 1e-9, (
          f"range_rate={range_rate} made the lead look FASTER than U11 said")
      if track.range_assist_correction > 0.0:
        armed.append(range_rate)
    assert armed, "precondition: some range rate in the sweep must arm, or this proves nothing"

  def test_native_vrel_is_untouched_so_association_cannot_move(self):
    """track_matches_vision and vision_track_probability read self.vRel/self.vLead. The assist
    changes what is reported ABOUT the lead, never which track is chosen -- see D-053's rejected
    alternatives. If this fails, the assist has become an association change."""
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL)
    assert track.range_assist_correction > 0.0
    assert track.vRel == RAIL
    assert track.vLead == V_EGO + RAIL


# ---------------------------------------------------------------------------------------------
# Arming
# ---------------------------------------------------------------------------------------------

ONSET = dict(d0=45.0, range_rate=-6.7, v_rel=-2.08)   # 000001f3 at 19:27, see TestRecordedOnsetLag


class TestArming:
  def test_no_partial_correction_while_arming(self):
    """Exactly zero for every qualifying update before the threshold, not a ramp up to it."""
    track = new_track()
    qualifying = 0
    for i in range(SETTLE):
      t = i * DT
      track.update(45.0 - 6.7 * t, 0.0, -2.08, V_EGO - 2.08, True, True, t_now=t, range_assist=True)
      if math.isfinite(track.vRelRangeLong):
        qualifying += 1
      if qualifying < RANGE_VREL_ASSIST_ARM_UPDATES:
        assert track.range_assist_correction == 0.0, (i, qualifying)
    assert qualifying == RANGE_VREL_ASSIST_ARM_UPDATES
    assert track.range_assist_correction > 0.0

  def test_arms_exactly_on_the_nth_update(self):
    track = new_track()
    settle(track, **ONSET)
    assert track.range_assist_active
    assert track.range_assist_arm_count == RANGE_VREL_ASSIST_ARM_UPDATES

  def test_one_update_short_stays_inert(self):
    track = new_track()
    feed(track, SETTLE - 1, **ONSET)
    assert not track.range_assist_active
    assert track.range_assist_correction == 0.0
    assert track.range_assist_arm_count == RANGE_VREL_ASSIST_ARM_UPDATES - 1

  def test_disagreement_below_threshold_never_arms(self):
    """Just under MIN_DISAGREEMENT, held for far longer than the arm count."""
    track = new_track()
    feed(track, 40, d0=70.0, range_rate=-6.8, v_rel=-5.0)
    assert track.range_assist_correction == 0.0
    assert track.range_assist_arm_count == 0

  def test_arm_streak_resets_on_one_agreeing_update(self):
    """Arming must require CONSECUTIVE disagreement; an intermittent one must not accumulate."""
    track = new_track()
    feed(track, SETTLE - 2, **ONSET)
    assert track.range_assist_arm_count == RANGE_VREL_ASSIST_ARM_UPDATES - 2
    track.update(track.dRel - 6.7 * DT, 0.0, -6.7, V_EGO - 6.7, True, True,
                 t_now=(SETTLE - 2) * DT, range_assist=True)
    assert track.range_assist_arm_count == 0
    assert track.range_assist_correction == 0.0


# ---------------------------------------------------------------------------------------------
# Gross outliers and the window arithmetic behind the long fit
# ---------------------------------------------------------------------------------------------

class TestGrossOutlierRejection:
  """The reason the long fit and ARM_UPDATES exist. The range channel carries ~1% gross outliers
  and the short LSQ has no outlier rejection, so a single bad sample clears MIN_DISAGREEMENT on
  its own."""

  def test_single_outlier_swings_the_short_fit_past_the_threshold(self):
    """Precondition for the tests below -- if this stops holding, the long fit is being validated
    against a scenario that no longer exercises it."""
    track = new_track()
    feed(track, 5, d0=60.0, range_rate=-1.0, v_rel=-1.0, d_offsets={4: -1.0})
    assert track.vRelRangeFresh
    assert track.vRel - track.vRelRange > RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS

  def test_single_outlier_does_not_arm(self):
    track = new_track()
    assert peak(track, 40, d0=60.0, range_rate=-1.0, v_rel=-1.0, d_offsets={20: -1.0}) == 0.0

  def test_two_separated_outliers_do_not_arm(self):
    track = new_track()
    assert peak(track, 50, d0=60.0, range_rate=-1.0, v_rel=-1.0, d_offsets={20: -1.0, 32: -1.2}) == 0.0


class TestWindowArithmetic:
  """Pins the numbers the rework-guards comment block in radard.py quotes: a newest-sample outlier
  of e moves the 15-sample slope by e/(40h) and leaves an RMS residual of ~0.22-0.25 e."""

  def _fit(self, offsets):
    track = new_track()
    feed(track, RANGE_VREL_LONG_SAMPLES, d0=60.0, range_rate=-1.0, v_rel=-1.0, d_offsets=offsets)
    assert math.isfinite(track.vRelRangeLong)
    return track

  def test_newest_sample_outlier(self):
    track = self._fit({14: -1.0})
    assert track.vRel - track.vRelRangeLong == pytest.approx(1.0 / (40 * DT), abs=1e-3)
    assert track.vRelRangeLongResidual == pytest.approx(0.2248, abs=2e-3)

  def test_middle_sample_outlier(self):
    track = self._fit({7: -1.0})
    assert track.vRel - track.vRelRangeLong == pytest.approx(0.0, abs=1e-6)
    assert track.vRelRangeLongResidual == pytest.approx(0.2494, abs=2e-3)

  def test_persistent_step_swings_the_short_fit_for_exactly_four_updates(self):
    """A 0.7 m range step is what the 232 walk looks like to a 5-sample fit. The short fit sees it
    for four updates, one fewer than ARM_UPDATES; the long fit never gets near the threshold."""
    track = new_track()
    short_hits, long_worst = 0, 0.0
    for i in range(40):
      t = i * DT
      track.update(60.0 - 1.0 * t - (0.7 if i >= 20 else 0.0), 0.0, -1.0, V_EGO - 1.0, True, True,
                   t_now=t, range_assist=True)
      if track.vRelRangeFresh and track.vRel - track.vRelRange >= RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS:
        short_hits += 1
      if math.isfinite(track.vRelRangeLong):
        long_worst = max(long_worst, track.vRel - track.vRelRangeLong)
    assert short_hits == RANGE_VREL_ASSIST_ARM_UPDATES - 1
    assert long_worst < 1.1
    assert track.range_assist_correction == 0.0


# ---------------------------------------------------------------------------------------------
# Bounds and clear-only guards, each with its negative control
# ---------------------------------------------------------------------------------------------

class TestCorrectionCap:
  """The cap is a bound on the damage a bad fit can do, not a fitted value. A large range error
  must not become an equally large brake demand."""

  def test_correction_is_capped(self):
    track = new_track(v_lead=28.0)
    first = None
    for i in range(SETTLE + 5):
      t = i * DT
      track.update(100.0 - 15.0 * t, 0.0, -2.0, 30.0 - 2.0, True, True, t_now=t, range_assist=True)
      if first is None and track.range_assist_correction > 0.0:
        first = i
    assert first == SETTLE - 1
    assert track.range_assist_correction == RANGE_VREL_ASSIST_MAX_CORRECTION_MPS
    state = track.get_RadarState()
    assert state["vRel"] == pytest.approx(-2.0 - RANGE_VREL_ASSIST_MAX_CORRECTION_MPS)
    assert state["vLead"] - state["vRel"] == pytest.approx(30.0)

  def test_vlead_and_vrel_move_together(self):
    """vRel and vLead differ by v_ego and must stay consistent, or the planner's closing-speed and
    follow-distance terms disagree with each other."""
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL)
    state = track.get_RadarState()
    assert track.range_assist_correction > 0.0
    assert state["vLead"] - state["vRel"] == pytest.approx(V_EGO)


class TestZeroSpeedCap:
  """The correction may slow the reported lead to a standstill, never past it: a lead reported
  backing toward us is a brake demand no recorded case justified."""

  def test_correction_stops_at_a_stationary_lead(self):
    track = new_track(v_lead=1.5)
    settle(track, d0=80.0, range_rate=-16.0, v_rel=RAIL, v_ego=15.0)
    assert track.range_assist_correction == pytest.approx(1.5)
    assert track.get_RadarState()["vLead"] == pytest.approx(0.0, abs=1e-9)

  def test_control_the_fits_wanted_more(self):
    """Without this the cap test would pass on a disagreement that never exceeded 1.5."""
    track = new_track(v_lead=1.5)
    settle(track, d0=80.0, range_rate=-16.0, v_rel=RAIL, v_ego=15.0)
    assert track.vRel - track.vRelRange == pytest.approx(2.5, abs=0.01)
    assert track.vRel - track.vRelRangeLong == pytest.approx(2.5, abs=0.01)


class TestSpeedFloor:
  """236 14:45: ego stopped, U11 +1.5..+2.3 against a fit of -9 to -12.7. Below the floor the
  range derivative of a creeping queue is not a closing speed."""

  def test_below_floor_is_inert(self):
    track = new_track(v_lead=3.0)
    feed(track, 40, d0=30.0, range_rate=-3.5, v_rel=-1.0, v_ego=4.0)
    assert track.range_assist_correction == 0.0
    assert track.range_assist_arm_count == 0

  def test_control_without_the_floor(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_MIN_V_EGO_MPS", 0.0)
    track = new_track(v_lead=3.0)
    feed(track, 40, d0=30.0, range_rate=-3.5, v_rel=-1.0, v_ego=4.0)
    assert track.range_assist_correction == pytest.approx(2.5, abs=0.01)


class TestPlausibility:
  """A fit that makes the lead drive backwards faster than MAX_BACKWARD_LEAD is a range fault,
  not a closing speed."""

  def test_implausible_backward_lead_is_inert(self):
    track = new_track(v_lead=10.0)
    feed(track, 40, d0=90.0, range_rate=-27.0, v_rel=-10.0)
    assert track.range_assist_correction == 0.0

  def test_control_without_the_guard(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_MAX_BACKWARD_LEAD_MPS", math.inf)
    track = new_track(v_lead=10.0)
    feed(track, 40, d0=90.0, range_rate=-27.0, v_rel=-10.0)
    assert track.range_assist_correction == RANGE_VREL_ASSIST_MAX_CORRECTION_MPS


ZIGZAG_05 = {i: (0.5 if i % 2 else -0.5) for i in range(40)}
ZIGZAG_08 = {i: (0.8 if i % 2 else -0.8) for i in range(40)}


class TestLongResidual:
  """A range series that does not look like a line over ~1 s is not a closing speed to act on."""

  def test_moderate_scatter_still_arms(self):
    track = new_track()
    feed(track, 40, d0=76.0, range_rate=-19.4, v_rel=RAIL, d_offsets=ZIGZAG_05)
    assert track.range_assist_active
    assert track.range_assist_correction == pytest.approx(5.9, abs=0.1)
    assert track.vRelRangeLongResidual == pytest.approx(0.4989, abs=0.01)

  def test_large_scatter_is_inert(self):
    track = new_track()
    feed(track, 40, d0=76.0, range_rate=-19.4, v_rel=RAIL, d_offsets=ZIGZAG_08)
    assert track.range_assist_correction == 0.0

  def test_control_without_the_guard(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_MAX_LONG_RESIDUAL_M", math.inf)
    track = new_track()
    feed(track, 40, d0=76.0, range_rate=-19.4, v_rel=RAIL, d_offsets=ZIGZAG_08)
    assert track.range_assist_correction == pytest.approx(5.9, abs=0.1)


@pytest.mark.usefixtures("pre130")
class TestLongHistoryRequirement:
  def test_no_long_fit_before_the_window_fills(self):
    track = new_track()
    feed(track, RANGE_VREL_LONG_SAMPLES - 1, d0=76.0, range_rate=-19.4, v_rel=RAIL)
    assert math.isnan(track.vRelRangeLong)
    assert track.range_assist_correction == 0.0

  def test_control_with_a_short_long_window(self, monkeypatch):
    # The deque maxlen is fixed in Track.__init__, so patch BEFORE building the track.
    monkeypatch.setattr(radard, "RANGE_VREL_LONG_SAMPLES", 5)
    monkeypatch.setattr(radard, "RANGE_VREL_LONG_MIN_SPAN_S", 0.2)
    track = new_track()
    feed(track, 9, d0=76.0, range_rate=-19.4, v_rel=RAIL)
    assert track.range_assist_correction > 0.0


def run_span_gap(gap, n_after=22):
  """10 measured sweeps, `gap` coasts with t advancing, then measured sweeps. Returns the index
  (after the gap) of the first non-zero correction, or None."""
  track = new_track()
  k = 0
  for _ in range(10):
    t = k * DT
    track.update(76.0 - 19.4 * t, 0.0, RAIL, V_EGO + RAIL, True, True, t_now=t, range_assist=True)
    k += 1
  for _ in range(gap):
    t = k * DT
    track.update(76.0 - 19.4 * t, 0.0, RAIL, V_EGO + RAIL, False, False, t_now=t, range_assist=True)
    k += 1
  for j in range(n_after):
    t = k * DT
    track.update(76.0 - 19.4 * t, 0.0, RAIL, V_EGO + RAIL, True, True, t_now=t, range_assist=True)
    k += 1
    if track.range_assist_correction > 0.0:
      return j
  return None


@pytest.mark.usefixtures("pre130")
class TestLongSpanGap:
  """The long window counts samples, not time. A coast gap stretches its span; past
  LONG_MAX_SPAN the fit is straddling two different stretches of road."""

  def test_short_gap_is_accepted(self):
    assert run_span_gap(7) == 8

  def test_long_gap_waits_for_the_window_to_roll_past_it(self):
    assert run_span_gap(8) == 18

  def test_control_without_the_span_limit(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_LONG_MAX_SPAN_S", math.inf)
    assert run_span_gap(8) == 8


def rail_glitch_series(track, n, *, u11, rate):
  """A closing lead with a 0.25 m range glitch every fifth sweep. Returns (peak, max arm count)."""
  best, max_arm, first = 0.0, 0, None
  for i in range(n):
    t = i * DT
    d = 80.0 + rate * t + (0.25 if i % 5 == 4 else 0.0)
    track.update(d, 0.0, u11, V_EGO + u11, True, True, t_now=t, range_assist=True)
    best = max(best, track.range_assist_correction)
    max_arm = max(max_arm, track.range_assist_arm_count)
    if first is None and track.range_assist_correction > 0.0:
      first = i
  return best, max_arm, first


class TestRailRule:
  """On the U11 low rail the channel is a bound, not a reading (D-041), so the long fit alone
  decides arming there. Off the rail both fits must disagree."""

  def test_rail_value_is_exact(self):
    assert RAIL == -13.5
    assert -13.49 > RAIL + Q / 2, "-13.49 is OFF the rail; tests that mean the rail must use RAIL"

  @pytest.mark.usefixtures("pre130")   # original rail rule; fast-path timing/size: TestRailFastPath
  def test_on_rail_the_long_fit_alone_arms(self):
    best, _, first = rail_glitch_series(new_track(), 60, u11=RAIL, rate=-16.0)
    assert best == pytest.approx(2.577, abs=0.05)
    assert first == SETTLE - 1

  def test_one_quantum_above_the_rail_does_not(self):
    best, max_arm, _ = rail_glitch_series(new_track(), 60, u11=RAIL + Q, rate=-(16.0 - Q))
    assert best == 0.0
    assert max_arm == RANGE_VREL_ASSIST_ARM_UPDATES - 1

  def test_control_without_the_rail_rule(self, monkeypatch):
    monkeypatch.setattr(radard, "BOSCH_A_U11_LOW_RAIL_MPS", -99.0)
    best, max_arm, _ = rail_glitch_series(new_track(), 60, u11=RAIL, rate=-16.0)
    assert best == 0.0
    assert max_arm == RANGE_VREL_ASSIST_ARM_UPDATES - 1


# ---------------------------------------------------------------------------------------------
# Recorded phantoms the rework exists to refuse
# ---------------------------------------------------------------------------------------------

WALK_232 = np.array([(-1.20, 57.30, 2.00), (0.00, 59.00, 1.91), (0.08, 58.94, 1.83), (0.61, 56.94, 0.58),
                     (0.75, 56.69, 0.44), (0.87, 56.75, 0.39), (1.62, 56.06, 0.02), (1.69, 56.19, 0.05),
                     (2.02, 57.75, 0.70), (2.56, 59.12, 1.09)])
WALK_232_PHASES = np.linspace(0.0, DT, 8, endpoint=False)


def run_232_walk(phase):
  """Returns (peak correction, max arm count, 99 if it ever went active)."""
  a, v_ego = WALK_232, 21.7
  track = radard.Track(1, v_ego + a[0, 2], radard.KalmanParams(DT))
  best, max_arm = 0.0, 0
  t = a[0, 0] + phase
  while t <= a[-1, 0]:
    d = float(np.interp(t, a[:, 0], a[:, 1]))
    u = float(np.interp(t, a[:, 0], a[:, 2]))
    track.update(d, 0.1, u, v_ego + u, True, True, t_now=t, range_assist=True)
    max_arm = max(max_arm, 99 if track.range_assist_active else track.range_assist_arm_count)
    best = max(best, track.range_assist_correction)
    t += DT
  return best, max_arm


def short_fit_only(self):
  self.vRelRangeLong, self.vRelRangeLongResidual, self.vRelRangeLongSpan = self.vRelRange, 0.0, 1.0
  return True


class TestRecorded232Walk:
  """00000232--3a01619ce5 at 3:02.8: range walked 59.0 -> 56.1 -> 59.1 m while U11 read
  +2.1 -> +0.1 -> +1.1. The original D-053 armed on it. Anchor points are from the log, the series
  between them is interpolated, and every sampling phase is tried."""

  @pytest.mark.parametrize("phase", WALK_232_PHASES)
  def test_walk_is_refused_with_one_update_of_margin(self, phase):
    best, max_arm = run_232_walk(phase)
    assert best == 0.0
    assert max_arm == RANGE_VREL_ASSIST_ARM_UPDATES - 1, "the margin is ONE update; see radard.py"

  def test_control_one_fewer_arm_update_fires(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_ARM_UPDATES", RANGE_VREL_ASSIST_ARM_UPDATES - 1)
    assert all(run_232_walk(p)[0] > 2.0 for p in WALK_232_PHASES)

  def test_control_short_fit_only_fires(self, monkeypatch):
    monkeypatch.setattr(radard.Track, "_fit_long_range", short_fit_only)
    assert all(run_232_walk(p)[0] > 4.0 for p in WALK_232_PHASES)


SETTLE_236 = np.array([(0.00, 77.19, -3.47), (0.47, 69.12, -5.36), (0.74, 65.81, -5.83), (0.87, 64.81, -5.70),
                       (1.01, 63.62, -5.70), (1.28, 61.81, -5.42), (1.61, 59.88, -4.69), (1.81, 59.50, -3.89),
                       (2.15, 58.81, -2.73), (2.42, 59.19, -1.83)])


def run_236_settle(lead_in=3, coast=5):
  """00000236 22:13.6 track 44: a few sweeps on the old far target, a coast, then the new one.
  Returns (peak correction, max arm count, 99 if it ever went active)."""
  a, v_ego = SETTLE_236, 23.0
  track = radard.Track(44, v_ego - 2.5, radard.KalmanParams(DT))
  best, max_arm = 0.0, 0
  s = -(lead_in + coast)
  while s * DT <= a[-1, 0]:
    t = s * DT
    if s < -coast:
      d, u, m = 81.0, -2.5, True
    elif s < 0:
      d, u, m = 81.0, -2.5, False
    else:
      d, u, m = float(np.interp(t, a[:, 0], a[:, 1])), float(np.interp(t, a[:, 0], a[:, 2])), True
    track.update(d, 0.8, u, v_ego + u, m, m, t_now=t, range_assist=True)
    best = max(best, track.range_assist_correction)
    max_arm = max(max_arm, 99 if track.range_assist_active else track.range_assist_arm_count)
    s += 1
  return best, max_arm


class TestRecorded236Settle:
  """00000236--60bfb34cb1 at 22:13.6: a newly associated track settled 77.2 -> 59.5 m in 1.8 s,
  which a range fit reads as fast closing. The original D-053 hit its 8.0 cap on it."""

  def test_settle_is_refused_with_one_update_of_margin(self):
    best, max_arm = run_236_settle()
    assert best == 0.0
    assert max_arm == RANGE_VREL_ASSIST_ARM_UPDATES - 1

  @pytest.mark.parametrize("lead_in,coast", [(0, 0), (15, 5)])
  def test_refused_across_history_variants(self, lead_in, coast):
    assert run_236_settle(lead_in, coast)[0] == 0.0

  def test_control_looser_residual_fires(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_MAX_LONG_RESIDUAL_M", math.inf)
    assert run_236_settle()[0] > 2.0

  def test_control_one_fewer_arm_update_fires(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_ARM_UPDATES", RANGE_VREL_ASSIST_ARM_UPDATES - 1)
    assert run_236_settle()[0] > 2.0


# ---------------------------------------------------------------------------------------------
# Geometry gates
# ---------------------------------------------------------------------------------------------

class TestGeometryGates:
  """A range derivative is a RADIAL rate. These two gates are what keep it close enough to a
  longitudinal one to be read as one."""

  def test_close_lead_is_inert(self):
    track = new_track()
    settle(track, d0=RANGE_VREL_ASSIST_MIN_D_REL_M - 1.0, range_rate=-0.05, v_rel=2.5)
    assert track.range_assist_correction == 0.0

  def test_control_without_the_distance_floor(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_MIN_D_REL_M", 0.0)
    track = new_track()
    settle(track, d0=RANGE_VREL_ASSIST_MIN_D_REL_M - 1.0, range_rate=-0.05, v_rel=2.5)
    assert track.range_assist_correction == pytest.approx(2.55, abs=0.01)

  @pytest.mark.parametrize("y_rel", [1.7, -1.7])
  def test_lateral_offset_is_inert(self, y_rel):
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, y_rel=y_rel)
    assert track.range_assist_correction == 0.0

  def test_gate_pair_bounds_the_projection_error(self):
    """Pins the pair to the 10.8 deg / 1.8% projection error claimed in the constant block, so
    that widening either constant fails here rather than silently invalidating the comment."""
    azimuth = math.degrees(math.asin(RANGE_VREL_ASSIST_MAX_ABS_Y_REL_M / RANGE_VREL_ASSIST_MIN_D_REL_M))
    assert azimuth == pytest.approx(10.8, abs=0.1)
    assert math.cos(math.radians(azimuth)) == pytest.approx(0.982, abs=0.001)

  def test_leaving_the_gate_disarms_immediately(self):
    """Not a decay: an armed correction whose geometry stops qualifying is dropped on that update,
    because the radial-rate assumption is what licensed it in the first place."""
    for y_rel, expect_active in ((3.0, False), (0.0, True)):
      track = new_track()
      fed = settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL)
      assert track.range_assist_active
      t = fed[-1][0] + DT
      track.update(76.0 - 19.4 * t, y_rel, RAIL, V_EGO + RAIL, True, True, t_now=t, range_assist=True)
      assert track.range_assist_active is expect_active, y_rel


class FakeVisionLead:
  """The four leadsV3[0] fields vision_assist_closing reads."""
  def __init__(self, prob=0.95, x=77.52, y=-1.7, v=6.0):
    self.prob, self.x, self.y, self.v = prob, [x], [y], [v]


class TestVisionAssistGeometry:
  """VISION_ASSIST_GEOMETRY (default OFF): the |yRel| lane gate is lifted only while a confident
  model lead at the same range and lateral position is itself closing. 0000026c--10bec2e200 4:08
  is the case it was written for; STATUS 148 is why the lateral gate is not simply removed. Static
  tests only; the open-loop replay numbers are in the constant block."""

  def test_default_is_off(self):
    assert radard.VISION_ASSIST_GEOMETRY is False

  def test_off_ignores_vision(self):
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, y_rel=1.7, vision_closing=18.0)
    assert track.range_assist_correction == 0.0

  def test_on_with_corroboration_arms_off_lane(self, monkeypatch):
    monkeypatch.setattr(radard, "VISION_ASSIST_GEOMETRY", True)
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, y_rel=1.7, vision_closing=18.0)
    assert track.range_assist_active
    assert track.range_assist_correction == pytest.approx(5.9, abs=0.05)

  def test_control_on_without_vision_stays_inert(self, monkeypatch):
    monkeypatch.setattr(radard, "VISION_ASSIST_GEOMETRY", True)
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, y_rel=1.7, vision_closing=None)
    assert track.range_assist_correction == 0.0

  def test_bypassed_correction_is_bounded_by_vision_closing(self, monkeypatch):
    """Published vRel may claim at most VISION_ASSIST_CLOSING_MARGIN_MPS more closing than vision."""
    monkeypatch.setattr(radard, "VISION_ASSIST_GEOMETRY", True)
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, y_rel=1.7, vision_closing=12.0)
    bound = RAIL + 12.0 + radard.VISION_ASSIST_CLOSING_MARGIN_MPS
    assert track.range_assist_correction == pytest.approx(bound, abs=1e-6)
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, y_rel=1.7, vision_closing=5.0)
    assert track.range_assist_correction == 0.0

  @pytest.mark.parametrize("vision_closing", [4.0, 9.0, 18.0])
  def test_in_lane_never_below_the_plain_rule(self, monkeypatch, vision_closing):
    """In lane the vision path may arm earlier, bounded by vision, but once the plain rule would
    have armed the correction is exactly the plain one: never less closing than with the flag off."""
    def run(on):
      monkeypatch.setattr(radard, "VISION_ASSIST_GEOMETRY", on)
      track, out = new_track(), []
      for i in range(SETTLE + 10):
        t = i * DT
        track.update(76.0 - 19.4 * t, 0.0, -9.0, V_EGO - 9.0, True, True, t_now=t, range_assist=True,
                     vision_closing=vision_closing)
        out.append(track.range_assist_correction)
      return out
    monkeypatch.setattr(radard, "VISION_ASSIST_ARM_UPDATES", 3)
    off, on = run(False), run(True)
    assert any(b > a for a, b in zip(off, on, strict=True)) == (vision_closing > 9.0 - radard.VISION_ASSIST_CLOSING_MARGIN_MPS)
    assert all(b >= a - 1e-9 for a, b in zip(off, on, strict=True))
    assert on[-1] == pytest.approx(off[-1])
    bound = -9.0 + vision_closing + radard.VISION_ASSIST_CLOSING_MARGIN_MPS
    assert all(b <= max(bound, 0.0) + 1e-9 for a, b in zip(off, on, strict=True) if a == 0.0)

  def test_azimuth_limit_still_applies(self, monkeypatch):
    """The 26c curve track at 9.3 m lateral and 30 m would be 17 deg off-axis: still inert."""
    monkeypatch.setattr(radard, "VISION_ASSIST_GEOMETRY", True)
    track = new_track()
    settle(track, d0=30.0, range_rate=-19.4, v_rel=RAIL, y_rel=9.3, vision_closing=18.0)
    assert track.range_assist_correction == 0.0

  def test_param_switch_matches_code_flag(self):
    """The RangeVisionAssist param reaches Track as vision_assist=True: same result as the code flag."""
    track = new_track()
    settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL, y_rel=1.7, vision_closing=18.0, vision_assist=True)
    assert track.range_assist_active
    assert track.range_assist_correction == pytest.approx(5.9, abs=0.05)

  @pytest.mark.parametrize("values, expected", [
    ({"RangeDerivedVrel": True, "RangeVisionAssist": True}, (True, True)),
    ({"RangeDerivedVrel": True, "RangeVisionAssist": False}, (True, False)),
    ({"RangeDerivedVrel": False, "RangeVisionAssist": True}, (False, False)),   # needs the parent toggle
    ({"RangeDerivedVrel": True}, (True, False)),                                # .so without the key: D-053 survives
  ])
  def test_param_read(self, values, expected):
    class FakeParams:
      def get_bool(self, key):
        if key not in values:
          raise KeyError(key)
        return values[key]
    rd = radard.RadarD.__new__(radard.RadarD)
    rd._range_assist_params, rd._range_assist_frame = FakeParams(), 99
    rd._range_assist_enabled = rd._vision_assist_enabled = False
    assert rd._range_vrel_assist_enabled() is expected[0]
    assert rd._vision_assist_enabled is expected[1]

  def test_helper_gates(self, monkeypatch):
    f = radard.vision_assist_closing
    assert f(76.0, 1.7, FakeVisionLead(), 20.0) == pytest.approx(14.0)
    assert f(76.0, 1.7, None, 20.0) is None
    assert f(76.0, 1.7, FakeVisionLead(prob=0.5), 20.0) is None       # not confident
    assert f(76.0, 1.7, FakeVisionLead(x=100.0), 20.0) is None        # range mismatch
    assert f(76.0, 1.7, FakeVisionLead(y=2.0), 20.0) is None          # lateral mismatch (sign flip)
    assert f(76.0, 1.7, FakeVisionLead(v=18.0), 20.0) is None         # vision not closing enough


# ---------------------------------------------------------------------------------------------
# Disarming
# ---------------------------------------------------------------------------------------------

def armed_rail_track():
  track = new_track()
  fed = settle(track, d0=76.0, range_rate=-19.4, v_rel=RAIL)
  assert track.range_assist_active
  return track, fed[-1][0] + DT


class TestDisarm:
  def test_coast_clears(self):
    """A coast means the velocity is doubtful. The Bosch-A coast path holds last_trusted_vrel and
    can run for a long time -- measured at 121.8 s of continuous suppression of the followed lead on
    000001fb -- so holding a correction across it would be unbounded staleness."""
    track, t = armed_rail_track()
    track.update(76.0 - 19.4 * t, 0.0, RAIL, V_EGO + RAIL, False, False, t_now=t, range_assist=True)
    assert track.range_assist_correction == 0.0
    assert track.get_RadarState()["vRel"] == RAIL

  def test_dropout_clears(self):
    """After a gap the short window is rebuilt; vRelRange holds the PRE-GAP value until it refills.
    Acting on that stale rate is exactly the trap vRelRangeFresh exists to close."""
    track, t = armed_rail_track()
    t += 1.0
    track.update(track.dRel - 19.4, 0.0, RAIL, V_EGO + RAIL, True, True, t_now=t, range_assist=True)
    assert not track.vRelRangeFresh
    assert track.range_assist_correction == 0.0

  def test_flag_off_clears(self):
    track, t = armed_rail_track()
    track.update(76.0 - 19.4 * t, 0.0, RAIL, V_EGO + RAIL, True, True, t_now=t, range_assist=False)
    assert track.range_assist_correction == 0.0

  def test_correction_decays_as_u11_catches_up(self):
    """Once armed the hold is on ANY closing disagreement, not on MIN_DISAGREEMENT, so the
    correction walks to zero instead of stepping off a 2 m/s cliff into the planner."""
    track = new_track()
    fed = settle(track, **ONSET)
    assert track.range_assist_active
    t = fed[-1][0]
    seen = [track.range_assist_correction]
    for u11 in (-3.0, -4.0, -5.0, -6.0, -6.5, -6.7):
      t += DT
      track.update(45.0 - 6.7 * t, 0.0, u11, V_EGO + u11, True, True, t_now=t, range_assist=True)
      seen.append(track.range_assist_correction)
    assert all(b <= a + 1e-9 for a, b in zip(seen[:-1], seen[1:], strict=True)), seen
    assert seen[-1] == pytest.approx(0.0, abs=1e-6)
    assert any(0.0 < c < RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS for c in seen), seen


# ---------------------------------------------------------------------------------------------
# The real radard cadence: a 20 Hz loop over a 14.35 Hz radar
# ---------------------------------------------------------------------------------------------

RAIL_CASE = dict(d0=76.0, range_rate=-19.4, v_rel=RAIL)


class TestRadardLoopCadence:
  """Every other test in this file feeds one update per radar sweep. radard does not. On the car
  RadarD is driven at the 20 Hz model rate and collapses two different conditions into one bit --
  `measured = pt.measured and radar_fresh` -- so a DUPLICATE cycle (no new liveTracks message) and a
  COAST (new message, parser's measured bit clear) both arrive at Track.update as
  measurement_update False. They need opposite handling, and these tests pin that."""

  def test_duplicates_exist_at_this_cadence(self):
    """Guard the premise: if this stops holding, the tests below stop testing anything."""
    trace = feed_radard_cadence(new_track(), 20, **RAIL_CASE)
    assert sum(not fresh for _, fresh, _ in trace) >= 4
    assert {sweep for sweep, _, _ in trace} == set(range(trace[-1][0] + 1))

  def test_assist_arms_at_radard_cadence(self):
    """The defect this class exists for. Clearing on every non-measurement update reset the arm
    count roughly every fourth cycle, so the consecutive qualifying fits were unreachable and the
    feature was permanently inert on a car."""
    trace = feed_radard_cadence(new_track(), 40, **RAIL_CASE)
    assert trace[-1][2] > 0.0

  def test_duplicate_cycle_holds_the_correction(self):
    """Nothing was re-measured, so nothing may change -- otherwise the published vRel flickers
    between corrected and native at ~5 Hz, which the planner would see as velocity noise."""
    trace = feed_radard_cadence(new_track(), 40, **RAIL_CASE)
    armed_at = next(i for i, (_, _, c) in enumerate(trace) if c > 0.0)
    dups = [i for i in range(armed_at + 1, len(trace)) if not trace[i][1]]
    assert dups
    for i in dups:
      assert trace[i][2] == trace[i - 1][2]

  def test_coast_is_not_swallowed_by_the_hold(self):
    """The hold must not swallow a coast: a coast advances t_now, and D-052 measured 121.8 s of
    continuous coasting, so holding across one is unbounded staleness."""
    track = new_track()
    feed_radard_cadence(track, 40, **RAIL_CASE)
    coasts = {32, 33, 34}
    trace = feed_radard_cadence(track, 24, **RAIL_CASE, coast_sweeps=coasts, start_cycle=40)
    assert any(s == 31 and c > 0.0 for s, _, c in trace), "precondition: armed before the coast"
    assert all(c == 0.0 for s, _, c in trace if s in coasts)

  def test_hold_is_not_time_bound(self):
    """The hold is 'nothing arrived', not 'not much time has passed'. A stale t_now held for far
    longer than any real duplicate must still hold, because the alternative -- a bound in cycles or
    seconds -- would be a tuned constant with no evidence behind it."""
    track = new_track()
    fed = settle(track, **RAIL_CASE)
    held = track.range_assist_correction
    assert held > 0.0
    last_t, last_d = fed[-1]
    for _ in range(40):
      track.update(last_d, 0.0, RAIL, V_EGO + RAIL, False, False, t_now=last_t, range_assist=True)
    assert track.range_assist_correction == held


# ---------------------------------------------------------------------------------------------
# Recorded cases
# ---------------------------------------------------------------------------------------------

class TestRecordedRailCase:
  """000001f9 at 29:52 (D-041). U11 railed at -13.5 m/s on 88 of 88 active frames with healthy u10
  while the range closed at -19.4 m/s. D-041 publishes the rail as a bound and leaves recovering the
  true value to 'a separate, validated change'. This is that change -- still unvalidated on the road."""

  def test_rail_is_corrected_to_the_range_rate(self):
    track = new_track()
    settle(track, **RAIL_CASE)
    assert track.range_assist_active
    assert track.range_assist_correction == pytest.approx(5.9, abs=0.05)
    assert track.get_RadarState()["vRel"] == pytest.approx(-19.4, abs=0.05)

  def test_recorded_gap_fits_under_the_cap(self):
    """5.9 m/s against an 8.0 m/s cap. If the cap is lowered below this the feature can no longer do
    the one thing D-041 left for it."""
    assert 19.4 - 13.5 < RANGE_VREL_ASSIST_MAX_CORRECTION_MPS


def onset_first_correction():
  """U11 stuck at -2.08 while the range kinks from -2.08 to -6.7 m/s at sweep 20."""
  track = new_track()
  for i in range(60):
    t = i * DT
    d = 45.0 - 2.08 * min(i, 20) * DT - 6.7 * max(i - 20, 0) * DT
    track.update(d, 0.0, -2.08, V_EGO - 2.08, True, True, t_now=t, range_assist=True)
    if track.range_assist_correction > 0.0:
      return i
  return None


class TestRecordedOnsetLag:
  """000001f3 at 19:27 (D-043). The fitted range rate was -6.7 m/s while U11 still read -2.08, and
  U11's onset lag was measured at 0.88-1.28 s."""

  def test_onset_is_corrected(self):
    track = new_track()
    settle(track, **ONSET)
    assert track.range_assist_correction == pytest.approx(4.62, abs=0.05)

  def test_correction_beats_the_u11_lag(self):
    """0.77 s from the kink to the first correction against a measured 0.88 s minimum U11 onset
    lag. The original D-053 took 0.42 s; the long fit costs the rest. If this grows past the lag,
    the feature can no longer beat the channel it is correcting."""
    first = onset_first_correction()
    assert first == 31
    assert (first - 20) * DT < 0.88

  def test_control_a_longer_window_loses_to_the_lag(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_LONG_SAMPLES", 20)
    first = onset_first_correction()
    assert (first - 20) * DT > 0.88


class TestTheRangeWalkFault:
  """THE NEGATIVE CONTROL THAT MATTERS. STATUS.md's t~=11 s false brake on 00000231--5782493b00:
  track 6 walked 71.8 -> 61.6 m while vision held 75-78 m at prob 0.93-1.00 and the real gap GREW.
  The range itself was wrong, so U11 (-6.0) and the range fit (-4.5 to -6.4) AGREED. This assist
  is fitted to that same range and is blind to it by construction (STATUS.md records this).

  These tests pin that the recorded figures leave it inert. [INFERRED from the recorded figures,
  not replayed] -- the numbers are from the STATUS.md event table, driven through the real Track
  here rather than through a log.

  If a change makes this fire, the assist has become an amplifier for the only false brake this
  branch has recorded. Do not 'fix' these tests."""

  @pytest.mark.parametrize("fitted", [-4.5, -5.0, -5.5, -6.0, -6.4])
  def test_the_fault_leaves_the_assist_inert(self, fitted):
    track = new_track()
    settle(track, d0=71.8, range_rate=fitted, v_rel=-6.02)
    assert track.range_assist_correction == 0.0, (
        f"fitted range rate {fitted} against U11 -6.02 armed the assist on the recorded false brake")
    assert track.get_RadarState()["vRel"] == pytest.approx(-6.02)

  def test_the_worst_recorded_disagreement_is_inside_the_threshold(self):
    """disagreement = vRel - vRelRange, positive when the RANGE claims more closing. Across the
    recorded -4.5 .. -6.4 fit band against U11's -6.02 the worst case is +0.38 m/s, so the margin
    to MIN_DISAGREEMENT is 1.62 m/s. That margin is the whole safety argument for the threshold,
    so state it as a number rather than leaving it implicit."""
    worst = max(-6.02 - fitted for fitted in (-4.5, -5.0, -5.5, -6.0, -6.4))
    assert worst == pytest.approx(0.38, abs=0.01)
    assert RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS - worst == pytest.approx(1.62, abs=0.01)


# ---------------------------------------------------------------------------------------------
# Kalman path
# ---------------------------------------------------------------------------------------------

class TestKalmanPath:
  """The original D-053 fed the corrected vLead into the lead KF, and aLeadK -- which the MPC
  brakes on -- dipped to -3.8/-7.2/-6.0 m/s^2 on replay; 236 18:55 was the harm. The rework shifts
  the published speeds only. These tests pin that the filter never sees the correction."""

  def _twins(self):
    corrected, native = new_track(), new_track()
    for tr, assist in ((corrected, True), (native, False)):
      feed(tr, 25, range_assist=assist, **RAIL_CASE)
    assert corrected.range_assist_correction > 0.0
    return corrected, native

  def test_filter_state_is_native(self):
    corrected, native = self._twins()
    assert corrected.vLeadK == native.vLeadK
    assert corrected.aLeadK == native.aLeadK

  def test_published_speed_is_shifted_and_acceleration_is_not(self):
    corrected, native = self._twins()
    c, n = corrected.get_RadarState(), native.get_RadarState()
    assert c["vLeadK"] == pytest.approx(n["vLeadK"] - corrected.range_assist_correction)
    assert c["aLeadK"] == n["aLeadK"]
    assert c["aLeadTau"] == n["aLeadTau"]


# ---------------------------------------------------------------------------------------------
# D-009 negative control: break the mechanism, prove the tests notice
# ---------------------------------------------------------------------------------------------

class TestNegativeControlOfTheTestsThemselves:
  """D-009: a test suite that passes against a broken mechanism is not evidence. Each of these
  breaks one guard on purpose and asserts that the property it defends actually fails."""

  @pytest.mark.usefixtures("pre130")   # the rail fast path arms inside the duplicate gaps; see D-009 note
  def test_without_the_duplicate_hold_the_assist_never_arms(self, monkeypatch):
    """The negative control for the duplicate-cycle hold, and the one that found a real defect.
    Defeating the t_now comparison the hold rests on reproduces exactly the pre-fix behaviour --
    clear on EVERY non-measurement update -- and at the cadence radard actually runs at the assist
    can then never arm. If this test starts passing with the correction non-zero, the hold has
    stopped doing anything and TestRadardLoopCadence is no longer evidence."""
    original = radard.Track._update_range_assist

    def never_holds(self, enabled, measurement_update, t_now, vision_closing=None, vision_assist=False):
      # NaN never compares equal, so the duplicate branch falls through to the clear.
      self._range_assist_last_t = float('nan')
      return original(self, enabled, measurement_update, t_now, vision_closing)

    monkeypatch.setattr(radard.Track, "_update_range_assist", never_holds)
    trace = feed_radard_cadence(new_track(), 60, **RAIL_CASE)
    assert all(c == 0.0 for _, _, c in trace)

  def test_without_arm_count_or_long_fit_an_outlier_fires(self, monkeypatch):
    """The correction is transient here -- it appears while the outlier is in the window and is
    gone soon after -- so this watches the peak, not the settled state."""
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_ARM_UPDATES", 1)
    monkeypatch.setattr(radard.Track, "_fit_long_range", short_fit_only)
    track = new_track()
    assert peak(track, 40, d0=60.0, range_rate=-1.0, v_rel=-1.0, d_offsets={20: -1.0}) > 0.0, (
        "with the arm count and long fit disabled a single outlier should have armed: TestGrossOutlierRejection proves nothing")

  def test_lowering_the_threshold_fires_the_range_walk_fault(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS", 0.1)
    track = new_track()
    settle(track, d0=71.8, range_rate=-6.4, v_rel=-6.02)
    assert track.range_assist_correction > 0.0, (
        "lowering MIN_DISAGREEMENT should fire the t~=11 s fault: TestTheRangeWalkFault proves nothing")

  def test_widening_the_lateral_gate_corrects_an_offset_track(self, monkeypatch):
    monkeypatch.setattr(radard, "RANGE_VREL_ASSIST_MAX_ABS_Y_REL_M", 99.0)
    track = new_track()
    settle(track, y_rel=8.0, **RAIL_CASE)
    assert track.range_assist_correction > 0.0, (
        "widening the lateral gate should correct an 8 m offset track: the gate tests prove nothing")

  def test_feeding_the_correction_to_the_filter_moves_aleadk(self, monkeypatch):
    """If the KF did see the correction, TestKalmanPath must notice."""
    original = radard.Track._update_range_assist

    def leaks_into_kf(self, enabled, measurement_update, t_now, vision_closing=None, vision_assist=False):
      original(self, enabled, measurement_update, t_now, vision_closing)
      self.vLead -= self.range_assist_correction

    monkeypatch.setattr(radard.Track, "_update_range_assist", leaks_into_kf)
    corrected, native = new_track(), new_track()
    feed(corrected, 25, range_assist=True, **RAIL_CASE)
    feed(native, 25, range_assist=False, **RAIL_CASE)
    assert corrected.aLeadK != native.aLeadK


# ---------------------------------------------------------------------------------------------
# Rail fast path (STATUS 130): on the U11 rail an 8-sample long fit and 3 corroborated updates arm
# ---------------------------------------------------------------------------------------------

def rail_series(track, n, d_of, v_ego=30.0):
  """Railed U11 against an arbitrary range function d_of(i, t). Returns per-sweep
  (short disagreement, long disagreement, correction); NaN where a fit does not exist."""
  out = []
  for i in range(n):
    t = i * DT
    track.update(d_of(i, t), 0.0, RAIL, v_ego + RAIL, True, True, t_now=t, range_assist=True)
    ds = track.vRel - track.vRelRange if track.vRelRangeFresh else float('nan')
    out.append((ds, track.vRel - track.vRelRangeLong, track.range_assist_correction))
  return out


class TestRailFastPath:
  def test_corroborated_rail_arms_early_and_sized_between_the_fits(self, monkeypatch):
    # Range closes ~7 m/s faster than the rail, easing (+1.2 m/s^2) so the two fits differ.
    def closing(i, t):
      return 90.0 - 20.5 * t + 1.2 * t * t
    out = rail_series(new_track(v_lead=30.0 + RAIL), 20, closing)
    first = next(i for i, (_, _, c) in enumerate(out) if c > 0.0)
    assert first == radard.RANGE_VREL_RAIL_LONG_MIN_SAMPLES + radard.RANGE_VREL_RAIL_ARM_UPDATES - 2
    for ds, dl, c in out[first:]:
      assert min(ds, dl) - 1e-9 <= c <= max(ds, dl) + 1e-9, "never beyond the more-closing fit"
    monkeypatch.setattr(radard, "RANGE_VREL_RAIL_FAST", False)   # control: the pre-130 timing
    old = rail_series(new_track(v_lead=30.0 + RAIL), 30, closing)
    assert next(i for i, (_, _, c) in enumerate(old) if c > 0.0) > first + 5

  def test_flat_range_on_the_rail_never_corrects(self):
    # 00000276 13:46.6, lead tid 5: U11 on -13.5 for 0.8 s while the range sat at 56 then 55 m.
    track = new_track(v_lead=30.0 + RAIL)
    out = rail_series(track, 30, lambda i, t: 56.0 if i < 6 else 55.0)
    assert all(c == 0.0 for _, _, c in out)
    assert track.range_assist_rail_count == 0

  def test_single_range_step_does_not_arm(self):
    # Range consistent with the rail, then one persistent 1.5 m step: the short fit spikes, the
    # 8-sample long fit does not corroborate for 3 updates.
    track = new_track(v_lead=30.0 + RAIL)
    out = rail_series(track, 40, lambda i, t: 80.0 + RAIL * t - (1.5 if i >= 10 else 0.0))
    assert max(ds for ds, _, _ in out if ds == ds) > RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS, "the step must reach the short fit"
    assert all(c == 0.0 for _, _, c in out)

  def test_rail_fast_correction_respects_the_cap_and_the_zero_speed_bound(self):
    # Range closing 35 m/s against the -13.5 rail: ~21.5 m/s of disagreement, capped at 8.0.
    out = rail_series(new_track(v_lead=40.0 + RAIL), 25, lambda i, t: 100.0 - 35.0 * t, v_ego=40.0)
    assert any(c > 0.0 for _, _, c in out), "the case must arm, or the cap is untested"
    assert max(c for _, _, c in out) == RANGE_VREL_ASSIST_MAX_CORRECTION_MPS
    # Slow ego: native vLead = 16 - 13.5 = 2.5 m/s, range closing 20 m/s (inside the backward-lead
    # guard). The correction may never publish vLead below zero.
    track = new_track(v_lead=16.0 + RAIL)
    out = rail_series(track, 25, lambda i, t: 60.0 - 20.0 * t, v_ego=16.0)
    assert any(c > 0.0 for _, _, c in out), "the case must arm, or the bound is untested"
    assert all(c <= 16.0 + RAIL + 1e-9 for _, _, c in out)
    assert track.vLead - track.range_assist_correction >= -1e-9

  def test_off_the_rail_the_fast_path_changes_nothing(self, monkeypatch):
    # U11 one quantum above the rail, the same 20 m/s closing range: the 15-sample/5-update rule
    # must decide, bit for bit the same as with the fast path switched off.
    def run():
      track = new_track(v_lead=30.0 + RAIL + Q)
      res = []
      for i in range(30):
        t = i * DT
        track.update(90.0 - 20.0 * t, 0.0, RAIL + Q, 30.0 + RAIL + Q, True, True, t_now=t, range_assist=True)
        res.append(track.range_assist_correction)
      return res, track.range_assist_rail_count
    on, rail_count = run()
    assert rail_count == 0
    first = next(i for i, c in enumerate(on) if c > 0.0)
    assert first == SETTLE - 1, "off the rail the pre-130 timing must hold"
    monkeypatch.setattr(radard, "RANGE_VREL_RAIL_FAST", False)
    off, _ = run()
    assert on == off


# YOUNG_TRACK_FLAT_RANGE_BOUND (route 0000027a ~8:33, BM2): a newborn track coasted at -10.7 on a flat range.
def _young_coast(track, ranges, v_rel=-10.7, measured_first=3, t0=0.0):
  for i, d in enumerate(ranges):
    measured = i < measured_first
    track.update(d, 0.0, v_rel, V_EGO + v_rel, measured, measured, t_now=t0 + i * DT, range_assist=True)
  return t0 + (len(ranges) - 1) * DT


ROUTE_27A_TRACK_15 = [64.375, 64.0, 63.5625, 62.5625, 62.5625, 62.875, 62.5625, 62.9375, 63.1875, 63.25, 63.5625,
                      63.5, 63.5625]


def test_young_flat_range_bound_covers_route_27a_track_15():
  track = new_track(15)
  t = _young_coast(track, ROUTE_27A_TRACK_15)
  floor = track.young_flat_range_vrel_floor(t)
  assert floor is not None
  assert -4.0 < floor < -2.0   # the range fit is ~-0.2 m/s; the coast claims -10.7
  # Coasted sweeps count (a coast holds vRel, not the range) and the bound only ever reads the range.
  assert len(track.young_range_hist) == len(ROUTE_27A_TRACK_15)


def test_young_flat_range_bound_needs_samples_and_expires():
  track = new_track(15)
  t = _young_coast(track, ROUTE_27A_TRACK_15[:4])
  assert track.young_flat_range_vrel_floor(t) is None          # too few sweeps
  track = new_track(15)
  t = _young_coast(track, ROUTE_27A_TRACK_15)
  assert track.young_flat_range_vrel_floor(t + radard.YOUNG_TRACK_MAX_AGE_S) is None   # no longer young


def test_young_flat_range_bound_leaves_closing_range_alone():
  # A real newborn closer: the range itself falls at 10 m/s, so the fit is outside the flat band.
  track = new_track(16)
  t = _young_coast(track, [64.0 - 10.0 * DT * i for i in range(13)], v_rel=-10.5)
  assert track.young_flat_range_vrel_floor(t) is None


def test_young_flat_range_bound_ignores_duplicate_cycles_and_noisy_range():
  track = new_track(17)
  for i in range(12):
    t = (i // 2) * DT   # every sweep delivered twice, as a 20 Hz loop over a 14 Hz radar does
    track.update(63.0, 0.0, -10.7, V_EGO - 10.7, i % 2 == 0, i % 2 == 0, t_now=t, range_assist=True)
  assert len(track.young_range_hist) == 6
  noisy = new_track(18)
  t = _young_coast(noisy, [63.0 + (2.5 if i % 2 else -2.5) for i in range(13)])
  assert noisy.young_flat_range_vrel_floor(t) is None   # residual too large to call the range flat


# Noisy far-range tracks (route 00000284 22:35): track 17's range history since birth, ~79 m, coasted at -10.5.
ROUTE_284_TRACK_17 = [79.1, 79.8, 80.9, 81.6, 82.2, 82.6, 83.0, 83.2, 83.1, 82.8, 81.9, 81.4, 80.8, 80.4, 80.0]


def _plain_floor(ranges):
  ts = np.arange(len(ranges)) * DT
  return float(np.polyfit(ts, ranges, 1)[0]) - radard.YOUNG_TRACK_FLAT_MARGIN


def test_young_flat_range_bound_covers_route_284_track_17():
  track = new_track(17)
  t = _young_coast(track, ROUTE_284_TRACK_17, v_rel=-10.5)
  floor = track.young_flat_range_vrel_floor(t)
  assert floor is not None
  assert -10.5 + 3.0 < floor < _plain_floor(ROUTE_284_TRACK_17) - 1.0   # bounds, but noise buys back closing


def test_young_flat_range_bound_clean_fit_floor_unchanged():
  # Within YOUNG_TRACK_MAX_RESIDUAL_M the floor is exactly the original slope minus margin (27a unchanged).
  track = new_track(15)
  t = _young_coast(track, ROUTE_27A_TRACK_15)
  assert track.young_flat_range_vrel_floor(t) == pytest.approx(_plain_floor(ROUTE_27A_TRACK_15))


def test_young_flat_range_bound_noise_lowers_the_floor():
  floors = []
  for amp in (0.0, 1.0, 1.5, 1.9):
    track = new_track(18)
    t = _young_coast(track, [63.0 + (amp if i % 2 else -amp) for i in range(13)])
    floors.append(track.young_flat_range_vrel_floor(t))
  assert None not in floors
  assert floors == sorted(floors, reverse=True)   # more noise, more closing allowed
  assert floors[-1] < floors[0] - 2.0


def test_young_flat_range_bound_noisy_off_is_the_old_rule(monkeypatch):
  monkeypatch.setattr(radard, "YOUNG_TRACK_NOISY_MAX_RESIDUAL_M", radard.YOUNG_TRACK_MAX_RESIDUAL_M)
  track = new_track(17)
  t = _young_coast(track, ROUTE_284_TRACK_17, v_rel=-10.5)
  assert track.young_flat_range_vrel_floor(t) is None


def test_young_track_vision_gate():
  from types import SimpleNamespace
  lead = SimpleNamespace(dRel=62.9)

  def vis(x=77.0, v=22.5, a=0.0, p=0.97):
    return SimpleNamespace(prob=p, x=[x], v=[v], a=[a])

  assert radard.young_track_vision_contradicts(lead, vis(), 22.2)              # route 27a BM2: camera not closing
  assert not radard.young_track_vision_contradicts(lead, vis(v=13.1), 21.6)    # camera closing 8.5 m/s (237 1188.2)
  assert not radard.young_track_vision_contradicts(lead, vis(x=50.0), 22.2)    # camera lead nearer than the radar one
  assert not radard.young_track_vision_contradicts(lead, vis(p=0.5), 22.2)
  assert not radard.young_track_vision_contradicts(lead, vis(a=-2.0), 22.2)
