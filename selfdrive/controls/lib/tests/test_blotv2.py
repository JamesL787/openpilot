import pytest
from cereal import log
from openpilot.selfdrive.controls.lib.blotv2 import BLoTv2Supervisor
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
