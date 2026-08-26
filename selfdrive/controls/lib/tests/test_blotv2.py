import math

import pytest
from cereal import log
from openpilot.selfdrive.controls.lib.blotv2 import (
  JERK_SCALE_MIN,
  MIN_SPEED,
  ONSET_PAD_MAX,
  STOPPED_LEAD_PAD_MAX,
  BLoTv2Supervisor,
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
  supervisor = BLoTv2Supervisor(dt=0.05)
  policy = supervisor.update(LeadObservation(), v_ego=20.0, a_mpc=0.0, t_follow_base=1.45)
  assert policy.jerk_scale == 1.0
  assert policy.t_follow == 1.45
  assert not (policy.emergency or policy.recovery_active or policy.model_active or policy.launch_active)


def test_supervisor_softens_jerk_when_mpc_under_brakes_moderate_closing():
  # ttc = 30/5 = 6s, clear of MIN_TTC (3.5s), so this exercises the recovery path
  # rather than the emergency bypass.
  supervisor = BLoTv2Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  policy = None
  for _ in range(20):
    policy = supervisor.update(lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  assert not policy.emergency
  assert policy.jerk_scale < 1.0
  assert policy.recovery_active


def test_supervisor_reset_clears_state():
  supervisor = BLoTv2Supervisor(dt=0.05)
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
  supervisor = BLoTv2Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = supervisor.update(lead, v_ego=15.0, a_mpc=-7.03, t_follow_base=1.45)
  assert policy.required_decel >= 1.5
  assert not policy.emergency


def test_unmatched_mpc_braking_is_emergency():
  # Same close/fast scenario, but the MPC isn't braking at all -- a real shortfall,
  # so this must still trip emergency.
  supervisor = BLoTv2Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = supervisor.update(lead, v_ego=15.0, a_mpc=0.0, t_follow_base=1.45)
  assert policy.required_decel >= 1.5
  assert policy.emergency


def test_nonfinite_mpc_target_keeps_emergency():
  supervisor = BLoTv2Supervisor(dt=0.05)
  lead = LeadObservation(present=True, distance=20.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  policy = supervisor.update(lead, v_ego=15.0, a_mpc=math.nan, t_follow_base=1.45)
  assert policy.emergency


def test_stopped_lead_uses_larger_onset_pad():
  # Slow lead with a moderate but sub-emergency required_decel: only the
  # stopped-lead branch should fire (lead.acceleration == 0 keeps the raw-onset
  # branch silent), and it should pad by STOPPED_LEAD_PAD_MAX, not ONSET_PAD_MAX.
  supervisor = BLoTv2Supervisor(dt=0.05)
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

  baseline = BLoTv2Supervisor(dt=0.05)
  baseline_policy = None
  for _ in range(20):
    baseline_policy = baseline.update(lead, v_ego=10.0, a_mpc=0.0, t_follow_base=1.45)
  assert baseline_policy.t_follow == pytest.approx(1.45, abs=1e-6)

  forecasted = BLoTv2Supervisor(dt=0.05)
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
  supervisor = BLoTv2Supervisor(dt=0.05)
  moving_lead = LeadObservation(present=True, distance=30.0, speed=5.0, acceleration=0.0, model_prob=1.0)
  for _ in range(40):
    supervisor.update(moving_lead, v_ego=10.0, a_mpc=-1.0, t_follow_base=1.45)
  assert supervisor.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6)

  stopped_lead = LeadObservation(present=True, distance=2.0, speed=0.0, acceleration=0.0, model_prob=1.0)
  assert MIN_SPEED >= 0.5
  for _ in range(10):
    policy = supervisor.update(stopped_lead, v_ego=0.5, a_mpc=0.0, t_follow_base=1.45)
    assert policy.jerk_scale == pytest.approx(JERK_SCALE_MIN, abs=1e-6)
