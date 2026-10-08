"""A large-model reply through the fork's own parse -> action -> modelV2 path, and across handovers.

The reply is built from the pinned model's real output layout (profiles.py, read off its ONNX), parsed by the same Parser
the local supercombo path uses, turned into an action with the *remote* model's generation flags, and published with
fill_model_msg. This cannot show the model drives well (that needs the model and a route); it shows its output is a valid
input to everything downstream, and that switching backends neither raises nor publishes non-finite values."""
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import log, messaging
from openpilot.selfdrive.modeld.fill_model_msg import PublishState, fill_model_msg, fill_pose_msg
from openpilot.selfdrive.modeld.modeld import get_action_from_model
from openpilot.starpilot.jetlink_adapter import profiles
from openpilot.starpilot.jetlink_adapter.tests.fakes import parsed_output

P = profiles.CINQUE_TERRE_V3
TOGGLES = SimpleNamespace()


def action_from(output, prev, profile, v_ego=15.0):
  return get_action_from_model(output, prev, 0.3, 0.6, v_ego, profile.mlsim, profile.is_v9, profile.is_v14, profile.is_v15, TOGGLES,
                               0.1, 0.3, is_v16=profile.is_v16)


def publish(output, action, state, frame=100):
  driving, model = messaging.new_message("drivingModelData"), messaging.new_message("modelV2")
  fill_model_msg(driving, model, output, action, state, frame, frame, frame, 0.0, 123456789, 0.01, True)
  pose = messaging.new_message("cameraOdometry")
  fill_pose_msg(pose, output, frame, 0, 123456789, True)
  return driving, model, pose


def finite_msg(msg):
  def walk(x):
    if isinstance(x, float):
      assert np.isfinite(x), x
    elif isinstance(x, (list, tuple)):
      for y in x:
        walk(y)
    elif isinstance(x, dict):
      for y in x.values():
        walk(y)
  walk(msg.to_dict())


class TestARemoteReply:
  def test_every_head_the_parser_and_publisher_need_is_there_and_finite(self):
    out = parsed_output(1)
    for key in ("plan", "plan_stds", "action", "lane_lines", "road_edges", "lead", "lead_prob", "meta", "desire_state", "pose",
                "wide_from_device_euler", "road_transform"):
      assert key in out and np.isfinite(out[key]).all(), key

  def test_the_action_uses_the_v16_action_head(self):
    out = parsed_output(2)
    prev = log.ModelDataV2.Action()
    action = action_from(out, prev, P, v_ego=20.0)
    raw_curv, raw_accel = out["action"][0]
    # v16: curvature is the head's output over v^2 (v floored at 1), then smoothed from prev=0; acceleration likewise
    expected_curv = raw_curv / 20.0 ** 2
    assert abs(action.desiredCurvature) <= abs(expected_curv) + 1e-9 and np.sign(action.desiredCurvature) == np.sign(expected_curv)
    assert abs(action.desiredAcceleration) <= abs(raw_accel) + 1e-9
    # and not what the v15 / plan-based path would do: wrong flags change the answer
    wrong = get_action_from_model(out, prev, 0.3, 0.6, 20.0, True, False, False, False, TOGGLES, 0.1, 0.3, is_v16=False)
    assert wrong.desiredAcceleration != action.desiredAcceleration or wrong.desiredCurvature != action.desiredCurvature

  def test_it_publishes_a_valid_model_message_with_leads_and_pose(self):
    out = parsed_output(3)
    action = action_from(out, log.ModelDataV2.Action(), P)
    driving, model, pose = publish(out, action, PublishState())
    finite_msg(model)
    finite_msg(driving)
    finite_msg(pose)
    m = model.modelV2
    assert len(m.leadsV3) == 3 and all(0.0 <= lead.prob <= 1.0 for lead in m.leadsV3)
    assert len(m.velocity.x) == len(m.position.x) == 33
    assert m.action.desiredCurvature == pytest.approx(action.desiredCurvature)
    assert len(m.meta.desireState) == 8 and sum(m.meta.desireState) == pytest.approx(1.0, abs=1e-3)
    assert len(pose.cameraOdometry.trans) == 3

  def test_the_ego_velocity_radar_fusion_reads_comes_from_the_plan_head(self):
    out = parsed_output(4)
    _, model, _ = publish(out, action_from(out, log.ModelDataV2.Action(), P), PublishState())
    from openpilot.selfdrive.modeld.constants import Plan
    assert list(model.modelV2.velocity.x) == pytest.approx(out["plan"][0][:, Plan.VELOCITY][:, 0].tolist(), rel=1e-5)


class TestAcrossHandovers:
  def test_alternating_backends_keeps_every_published_message_finite_and_the_action_smooth(self):
    local = SimpleNamespace(mlsim=True, is_v9=False, is_v14=False, is_v15=True, is_v16=False)
    state, prev, history = PublishState(), log.ModelDataV2.Action(), []
    for frame in range(60):
      remote = (frame // 10) % 2 == 1
      if frame % 10 == 0 and frame:
        state = PublishState()                       # modeld resets the rolling publish state at a handover
      out = parsed_output(frame)
      # the local model in this stand-in has the same head layout; its generation flags are the local ones
      profile = P if remote else local
      action = action_from(out, prev, profile, v_ego=12.0)
      driving, model, pose = publish(out, action, state, frame)
      finite_msg(model)
      history.append((action.desiredCurvature, action.desiredAcceleration))
      prev = action
    curvature = np.array([c for c, _ in history])
    accel = np.array([a for _, a in history])
    assert np.isfinite(curvature).all() and np.isfinite(accel).all()
    # smoothing bounds one frame's step: the action moves a fraction of the way to a new target per frame
    assert np.abs(np.diff(accel)).max() < 4.0

  def test_resetting_the_publish_state_restarts_the_rolling_averages(self):
    out = parsed_output(5)
    state = PublishState()
    publish(out, action_from(out, log.ModelDataV2.Action(), P), state)
    assert state.disengage_buffer.any() or state.prev_brake_5ms2_probs.any() or state.prev_brake_3ms2_probs.any()
    fresh = PublishState()
    assert not fresh.disengage_buffer.any() and not fresh.prev_brake_3ms2_probs.any()
