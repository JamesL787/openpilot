import math

import pytest
from cereal import log
from openpilot.selfdrive.controls.lib.blotv3 import (
  JERK_SCALE_MIN,
  MIN_SPEED,
  ONSET_MAX_A_REQ,
  ONSET_PAD_MAX,
  PURSUIT_TAIL_S,
  STOPPED_LEAD_PAD_MAX,
  BLoTv3Supervisor,
)
from openpilot.selfdrive.controls.lib.longitudinal_lead import LeadObservation


def make_radar_lead(*, status: bool, d_rel: float = 40.0, v_lead: float = 10.0,
                    a_lead: float = 0.0, model_prob: float = 1.0):
  """Builds a real cereal RadarState.LeadData message, matching what the planner
  actually reads off radarState.leadOne -- not a hand-rolled stand-in. This is the
  boundary a `present` vs `status` field mismatch would otherwise slip past."""
  lead = log.RadarState.LeadData.new_message()
  lead.status = status
  lead.dRel = d_rel
  lead.vLead = v_lead
  lead.vLeadK = v_lead
  lead.aLeadK = a_lead
  lead.modelProb = model_prob
  return lead


def test_from_radar_reads_real_capnp_status_field():
  lead = make_radar_lead(status=True, d_rel=40.0, v_lead=10.0, a_lead=-1.0, model_prob=0.9)
  observation = LeadObservation.from_radar(lead, service_valid=True)
  assert observation.present
  assert observation.distance == 40.0
  assert observation.speed == 10.0
  assert observation.acceleration == -1.0
  assert observation.model_prob == pytest.approx(0.9)


def test_from_radar_absent_when_status_false():
  lead = make_radar_lead(status=False)
  observation = LeadObservation.from_radar(lead, service_valid=True)
  assert not observation.present


def test_from_radar_absent_when_service_invalid():
  lead = make_radar_lead(status=True)
  observation = LeadObservation.from_radar(lead, service_valid=False)
  assert not observation.present


def test_from_radar_absent_when_lead_is_none():
  observation = LeadObservation.from_radar(None, service_valid=True)
  assert not observation.present


def test_supervisor_stays_neutral_with_no_lead():
  supervisor = BLoTv3Supervisor(dt=0.05)
  policy = supervisor.update(LeadObservation(), v_ego=20.0, a_mpc=0.0, t_follow_base=1.45)
  assert policy.jerk_scale == 1.0
  assert policy.t_follow == 1.45
  assert not (policy.emergency or policy.recovery_active or policy.model_active or policy.launch_active)


def test_supervisor_softens_jerk_when_mpc_under_brakes_moderate_closing():
  # ttc = 30/5 = 6s, clear of MIN_TTC (3.5s), so this exercises the recovery path
  # rather than the emergency bypass.
  supervisor = BLoTv3Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  policy = None
  for _ in range(20):
    policy = supervisor.update(lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  assert not policy.emergency
  assert policy.jerk_scale < 1.0
  assert policy.recovery_active


def test_supervisor_reset_clears_state():
  supervisor = BLoTv3Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  for _ in range(20):
    supervisor.update(lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  assert supervisor.jerk_scale < 1.0

  supervisor.reset()
  assert supervisor.jerk_scale == 1.0
  assert supervisor.t_follow_pad == 0.0
  for trigger in supervisor._triggers:
    assert trigger._seconds == 0.0


def test_matched_mpc_braking_is_not_emergency():
  # Stopped lead close enough that ttc < MIN_TTC and required_decel >= ONSET_MAX_A_REQ,
  # but a_mpc already matches the required deceleration -- the MPC isn't actually
  # falling short, so this must not trip emergency (and reset the softening triggers).
  supervisor = BLoTv3Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = supervisor.update(lead, v_ego=15.0, a_mpc=-7.03, t_follow_base=1.45)
  assert policy.required_decel >= 1.5
  assert not policy.emergency


def test_unmatched_mpc_braking_is_emergency():
  # Same close/fast scenario, but the MPC isn't braking at all -- a real shortfall,
  # so this must still trip emergency.
  supervisor = BLoTv3Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = supervisor.update(lead, v_ego=15.0, a_mpc=0.0, t_follow_base=1.45)
  assert policy.required_decel >= 1.5
  assert policy.emergency


def test_nonfinite_mpc_target_keeps_emergency():
  supervisor = BLoTv3Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = supervisor.update(lead, v_ego=15.0, a_mpc=math.nan, t_follow_base=1.45)
  assert policy.emergency


def test_stopped_lead_uses_larger_onset_pad():
  # Slow lead with a moderate but sub-emergency required_decel: only the
  # stopped-lead branch should fire (lead.acceleration == 0 keeps the raw-onset
  # branch silent), and it should pad by STOPPED_LEAD_PAD_MAX, not ONSET_PAD_MAX.
  supervisor = BLoTv3Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=15.0, speed=1.0, acceleration=0.0, model_prob=1.0)
  policy = None
  for _ in range(60):
    policy = supervisor.update(lead, v_ego=5.0, a_mpc=0.0, t_follow_base=1.45)
  assert not policy.emergency
  expected_pad = STOPPED_LEAD_PAD_MAX * min(policy.required_decel / 1.2, 1.0)
  assert expected_pad > ONSET_PAD_MAX * min(policy.required_decel / 1.2, 1.0)
  assert (policy.t_follow - 1.45) == pytest.approx(expected_pad, abs=0.02)


def test_model_forecast_pads_onset_beyond_raw_measurement():
  # lead.acceleration alone (-0.2) is too mild to trip the onset-pad branch, but a
  # sustained hard model forecast should pull onset_lead_accel below the -0.4
  # threshold and pad following time -- the raw-measurement-only baseline must not.
  lead = LeadObservation(present=True, distance=30.0, speed=8.0, acceleration=-0.2, model_prob=1.0)

  baseline = BLoTv3Supervisor(dt=0.05)
  baseline_policy = None
  for _ in range(20):
    baseline_policy = baseline.update(lead, v_ego=10.0, a_mpc=0.0, t_follow_base=1.45)
  assert baseline_policy.t_follow == pytest.approx(1.45, abs=1e-6)

  forecasted = BLoTv3Supervisor(dt=0.05)
  forecasted_policy = None
  for _ in range(20):
    forecasted_policy = forecasted.update(lead, v_ego=10.0, a_mpc=0.0, t_follow_base=1.45,
                                          predicted_lead_accel=-1.0)
  assert forecasted_policy.model_active
  assert forecasted_policy.t_follow > baseline_policy.t_follow


def test_jerk_scale_holds_floor_through_standstill_with_lead_present():
  # Drive jerk_scale down to its floor via ordinary recovery, then transition to a
  # near-stopped lead-present state with nothing left armed. Without the standstill
  # hold this would immediately start slewing back toward 1.0; with it, the floor
  # should be held instead.
  supervisor = BLoTv3Supervisor(dt=0.05)
  moving_lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  for _ in range(40):
    supervisor.update(moving_lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  assert supervisor.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6)

  stopped_lead = LeadObservation(present=True, distance=2.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  assert MIN_SPEED >= 0.5
  for _ in range(10):
    policy = supervisor.update(stopped_lead, v_ego=0.5, a_mpc=0.0, t_follow_base=1.45)
    assert policy.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6)


def test_onset_pad_released_above_onset_max_a_req():
  # Hard-braking lead at 40 m: required_decel is ~3.8 m/s2, well above ONSET_MAX_A_REQ,
  # but ttc (4 s) clears MIN_TTC so this is not an emergency. D-058 part 1 let the onset pad
  # saturate here; reverted 2026-09-28 (route 294 6:25, see ONSET_MAX_A_REQ): the pad built
  # while need was mild ramps back out once the car already needs a hard brake.
  supervisor = BLoTv3Supervisor(dt=0.05)
  mild = LeadObservation(present=True, distance=60.0, speed=19.0, acceleration=-1.5, model_prob=1.0)
  for _ in range(40):
    policy = supervisor.update(mild, v_ego=20.0, a_mpc=0.0, t_follow_base=1.45)
  assert policy.required_decel < ONSET_MAX_A_REQ
  built = policy.t_follow - 1.45
  assert built > 0.2
  hard = LeadObservation(present=True, distance=40.0, speed=10.0, acceleration=-3.0, model_prob=1.0)
  pads = []
  for _ in range(40):
    policy = supervisor.update(hard, v_ego=20.0, a_mpc=0.0, t_follow_base=1.45)
    pads.append(policy.t_follow - 1.45)
  assert not policy.emergency
  assert policy.required_decel > ONSET_MAX_A_REQ
  assert all(b <= a + 1e-9 for a, b in zip([built] + pads[:-1], pads, strict=True))  # slews down, never jumps up
  assert pads[-1] == pytest.approx(0.0, abs=1e-6)


def test_stopped_lead_pad_released_above_onset_max_a_req():
  # Stopped lead at 20 m from 15 m/s: required_decel ~7.0 m/s2 and the MPC is already
  # matching it, so the emergency bypass stays clear (see test_matched_mpc_braking_is_not_emergency).
  # Above ONSET_MAX_A_REQ the near-stopped-lead pad does not build (D-058 part 1 reverted).
  supervisor = BLoTv3Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = None
  for _ in range(40):
    policy = supervisor.update(lead, v_ego=15.0, a_mpc=-7.03, t_follow_base=1.45)
  assert not policy.emergency
  assert policy.required_decel > ONSET_MAX_A_REQ
  assert (policy.t_follow - 1.45) == pytest.approx(0.0, abs=1e-6)


def test_partial_softening_is_held_through_the_crawl():
  # Arm recovery just long enough that jerk_scale is mid-slew -- strictly between
  # JERK_SCALE_MIN and 1.0 -- then cross below MIN_SPEED with the lead still there.
  # The old exact-floor hold did nothing here and the scale stiffened back toward 1.0
  # in the last metres of the stop; the latch must hold it instead.
  supervisor = BLoTv3Supervisor(dt=0.05)
  moving_lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  for _ in range(11):
    supervisor.update(moving_lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  partial = supervisor.jerk_scale
  assert JERK_SCALE_MIN < partial < 1.0

  stopped_lead = LeadObservation(present=True, distance=2.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  for _ in range(10):
    policy = supervisor.update(stopped_lead, v_ego=0.5, a_mpc=0.0, t_follow_base=1.45)
    assert policy.jerk_scale == pytest.approx(partial, abs=1e-6)


def test_lead_loss_clears_the_crawl_hold_for_a_re_acquired_lead():
  # Soften on one lead, lose it for a couple of frames, then pick a different lead up
  # while still crawling. The latch must not survive the gap: a freshly acquired lead
  # inherits no softening from the vehicle that is gone, and the scale keeps slewing
  # back to 1.0 until this lead earns softening of its own.
  supervisor = BLoTv3Supervisor(dt=0.05)
  moving_lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  for _ in range(40):
    supervisor.update(moving_lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  assert supervisor.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6)

  for _ in range(2):
    supervisor.update(LeadObservation(), v_ego=0.5, a_mpc=0.0, t_follow_base=1.45)
  after_gap = supervisor.jerk_scale
  assert JERK_SCALE_MIN < after_gap < 1.0

  new_lead = LeadObservation(present=True, distance=6.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = None
  for _ in range(40):
    policy = supervisor.update(new_lead, v_ego=0.5, a_mpc=0.0, t_follow_base=1.45)
  assert policy.jerk_scale == pytest.approx(1.0, abs=1e-6)


def test_crawl_hold_releases_after_the_emergency_bypass():
  # The emergency bypass wants the stock jerk cost. Once it fires in motion it must drop
  # the latch, so a following crawl no longer holds the softened scale.
  supervisor = BLoTv3Supervisor(dt=0.05)
  moving_lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  for _ in range(40):
    supervisor.update(moving_lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  assert supervisor.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6)

  emergency_lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  emergency_policy = supervisor.update(emergency_lead, v_ego=15.0, a_mpc=0.0, t_follow_base=1.45)
  assert emergency_policy.emergency

  policy = None
  for _ in range(40):
    policy = supervisor.update(emergency_lead, v_ego=0.5, a_mpc=0.0, t_follow_base=1.45)
  assert policy.jerk_scale == pytest.approx(1.0, abs=1e-6)


# --- The pursuit tail (ported from upstream cdf8e54c9; see STATUS item 41) -------------------
#
# Excess braking behind a lead that is ALREADY pulling away keeps the low jerk cost for a
# bounded PURSUIT_TAIL_S after the braking eases, because the recovery trigger disarms at the
# plan's zero crossing -- exactly where the MPC has to swing to acceleration. Unit-test evidence
# only: no replay and no road validation of this path on our tree.


def _run(supervisor, lead, *, v_ego, a_mpc, seconds, t_follow_base=1.45):
  """Step the supervisor for `seconds` of 0.05 s frames and return the last policy."""
  policy = None
  for _ in range(max(1, round(seconds / 0.05))):
    policy = supervisor.update(lead, v_ego=v_ego, a_mpc=a_mpc, t_follow_base=t_follow_base)
  return policy


def _pulling_away_brake_phase(supervisor):
  """Excess braking while the lead is already leaving: arms recovery, so the tail is armed."""
  lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=1.0, model_prob=1.0)
  policy = _run(supervisor, lead, v_ego=10.0, a_mpc=-1.0, seconds=1.0)
  assert policy.recovery_active, "precondition: the recovery trigger must arm to arm the tail"
  assert not policy.emergency, "precondition: this must exercise recovery, not the emergency bypass"
  assert supervisor.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6)
  return policy


def test_the_low_jerk_cost_outlasts_the_braking_behind_a_lead_pulling_away():
  # THE negative control for this port: with the tail reverted, `recovery_active` goes False as
  # soon as the braking eases and jerk_scale slews straight back toward 1.0, so the second
  # assertion fails.
  supervisor = BLoTv3Supervisor(dt=0.05)
  _pulling_away_brake_phase(supervisor)

  eased = LeadObservation(present=True, distance=32.0, speed=8.0, acceleration=2.0, model_prob=1.0)
  policy = _run(supervisor, eased, v_ego=10.0, a_mpc=-0.2, seconds=1.0)
  assert not policy.recovery_active, "the braking has eased, so recovery must be off"
  assert not policy.launch_active, "this must isolate the tail, not the launch trigger"
  assert policy.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6), "the tail holds the low cost"


def test_the_pursuit_tail_ends_on_its_own():
  # Bounded, not a latch. PURSUIT_TAIL_S of a still-accelerating lead must expire.
  supervisor = BLoTv3Supervisor(dt=0.05)
  _pulling_away_brake_phase(supervisor)

  eased = LeadObservation(present=True, distance=32.0, speed=8.0, acceleration=2.0, model_prob=1.0)
  policy = _run(supervisor, eased, v_ego=10.0, a_mpc=-0.2, seconds=PURSUIT_TAIL_S + 1.0)
  assert not policy.recovery_active
  assert policy.jerk_scale == pytest.approx(1.0, abs=1e-6)


def test_the_pursuit_tail_ends_when_the_lead_stops_pulling_away():
  # `lead.acceleration <= 0.0` clears the tail outright rather than letting it run down.
  supervisor = BLoTv3Supervisor(dt=0.05)
  _pulling_away_brake_phase(supervisor)

  coasting = LeadObservation(present=True, distance=32.0, speed=8.0, acceleration=0.0, model_prob=1.0)
  policy = _run(supervisor, coasting, v_ego=10.0, a_mpc=-0.2, seconds=1.0)
  assert policy.jerk_scale == pytest.approx(1.0, abs=1e-6)


def test_easing_behind_a_lead_that_never_pulled_away_returns_to_stock():
  # The tail must not arm on braking alone. Same braking phase, lead acceleration 0.0.
  supervisor = BLoTv3Supervisor(dt=0.05)
  flat = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  assert _run(supervisor, flat, v_ego=10.0, a_mpc=-1.0, seconds=1.0).recovery_active
  policy = _run(supervisor, flat, v_ego=10.0, a_mpc=-0.2, seconds=1.0)
  assert policy.jerk_scale == pytest.approx(1.0, abs=1e-6)


def test_the_pursuit_tail_never_touches_following_time():
  # The safety-relevant property: the tail changes the jerk cost only. t_follow is the gap the
  # driver feels, and a tail that padded it would silently change following distance.
  supervisor = BLoTv3Supervisor(dt=0.05)
  _pulling_away_brake_phase(supervisor)

  eased = LeadObservation(present=True, distance=32.0, speed=8.0, acceleration=2.0, model_prob=1.0)
  policy = _run(supervisor, eased, v_ego=10.0, a_mpc=-0.2, seconds=1.0, t_follow_base=1.45)
  assert policy.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6), "precondition: tail is holding"
  assert policy.t_follow == pytest.approx(1.45, abs=1e-9)
  assert supervisor.t_follow_pad == pytest.approx(0.0, abs=1e-9)


def test_lead_loss_clears_the_pursuit_tail():
  supervisor = BLoTv3Supervisor(dt=0.05)
  _pulling_away_brake_phase(supervisor)
  assert supervisor._pursuit_s > 0.0

  supervisor.update(LeadObservation(), v_ego=10.0, a_mpc=0.0, t_follow_base=1.45)
  assert supervisor._pursuit_s == 0.0


def test_reset_clears_the_pursuit_tail():
  supervisor = BLoTv3Supervisor(dt=0.05)
  _pulling_away_brake_phase(supervisor)
  assert supervisor._pursuit_s > 0.0

  supervisor.reset()
  assert supervisor._pursuit_s == 0.0


def test_pursuit_tail_state_exists_before_the_first_update():
  # This __init__ does not call reset(); upstream's does. Without the explicit initialiser the
  # first frame that reaches the decay branch raises AttributeError.
  assert BLoTv3Supervisor(dt=0.05)._pursuit_s == 0.0
