"""The runner seam: Jetlink's own JoiningModelState (vendored) between a fake local ModelState and a fake large model.

Everything the product does at a handover happens here for real: the swap gate, the demotion paths, the reset of the local
model, the backoff. What is faked are the two ends and the link."""
import types

import numpy as np
import pytest

from jetlink.openpilot import joining
from openpilot.starpilot.jetlink_adapter import profiles, runner
from openpilot.starpilot.jetlink_adapter.tests.fakes import (FakeBig, FakeClock, FakeLog, FakeModelState, FakeProgress, p_spec,
                                                             wait_until)


@pytest.fixture(autouse=True)
def quick_rejoin(monkeypatch):
  monkeypatch.setattr(joining, "REJOIN_DELAY_QUICK", 0.02)
  monkeypatch.setattr(joining, "REJOIN_DELAY", 0.02)


class Stack:
  def __init__(self, big_modes=None, with_action_t=False, spec=None, default_mode="ok"):
    self.model = FakeModelState(with_action_t=with_action_t)
    self.local = runner.LocalRunner(self.model)
    self.log = FakeLog()
    self.clock = FakeClock()
    self.resets = 0
    self.bigs = []
    spec = spec or p_spec()

    def reset():
      self.resets += 1
      for array in self.local.numpy_inputs.values():
        array.fill(0)
      self.model.prev_desire.fill(0)

    def build(client, s):
      big = FakeBig(s, big_modes if not self.bigs else None)
      big.default_mode = default_mode
      self.bigs.append(big)
      return big

    client = types.SimpleNamespace(dead=False, leave=lambda *a, **k: None, ping=lambda timeout=None: None, close=lambda: None)
    self.joining = joining.JoiningModelState(self.local, lambda should_stop=None: (client, spec), build, None, reset_small=reset,
                                             progress=FakeProgress(), log=self.log)
    self.runner = runner.JetlinkRunner(self.joining, self.local, self.log, self.clock)
    self.eye = np.eye(3, dtype=np.float32)

  @property
  def big(self):
    return self.bigs[-1]

  def frame(self, in_control=False, blinker=False, prepare_only=False, drop_ratio=0.0, desire=None):
    r = self.runner
    r.set_control(in_control, drop_ratio, blinker)
    inputs = {r.desire_key: np.zeros(8, np.float32) if desire is None else desire, "traffic_convention": np.array([1., 0.]),
              "action_t": np.array([0.3, 0.6], dtype=np.float32)}
    bufs = {r.road_key: "road", r.wide_key: "wide"}
    tfm = {r.road_key: self.eye, r.wide_key: self.eye * 2}
    out = r.run(bufs, tfm, inputs, prepare_only, blinker_on=blinker)
    return out, r.snapshot()

  def promote(self):
    for _ in range(joining.SMALL_WARMUP_FRAMES):
      self.frame(in_control=True)
    assert wait_until(lambda: self.joining.big_model_available), "link never became ready"
    out, snap = self.frame(in_control=False)
    return out, snap

  def close(self):
    self.runner.close()


@pytest.fixture
def stack():
  made = []

  def make(**kw):
    s = Stack(**kw)
    made.append(s)
    return s
  yield make
  for s in made:
    s.close()


class TestPromotion:
  def test_it_starts_on_the_local_model_and_says_so(self, stack):
    s = stack()
    out, snap = s.frame(in_control=True)
    assert out["source"] == "local"
    assert snap.backend == runner.LOCAL and snap.handovers == 0 and not snap.settling
    assert s.runner.policy_generation == "v15" and s.runner.is_v15 and not s.runner.is_v16

  def test_it_swaps_in_only_when_nothing_is_in_control(self, stack):
    s = stack()
    for _ in range(joining.SMALL_WARMUP_FRAMES + 5):
      out, snap = s.frame(in_control=True)
    assert wait_until(lambda: s.joining.big_model_available)
    assert out["source"] == "local" and snap.accelerator == "ready"   # ready, waiting for a window
    out, snap = s.frame(in_control=False)
    assert out["source"] == "remote"
    assert snap.backend == runner.JETLINK and snap.accelerator == "running" and snap.handed_over

  def test_a_blinker_or_lane_change_holds_the_swap_off(self, stack):
    s = stack()
    for _ in range(joining.SMALL_WARMUP_FRAMES + 2):
      s.frame(in_control=True)
    assert wait_until(lambda: s.joining.big_model_available)
    out, _ = s.frame(in_control=False, blinker=True)
    assert out["source"] == "local"
    out, _ = s.frame(in_control=False, blinker=False)
    assert out["source"] == "remote"

  def test_the_remote_models_generation_comes_from_its_profile_not_the_fallback(self, stack):
    s = stack()
    assert s.runner.is_v15 and s.model.policy_generation == "v15"
    s.promote()
    r = s.runner
    assert r.remote_active and r.profile is profiles.CINQUE_TERRE_V3
    assert (r.policy_generation, r.is_v16, r.is_v15, r.mlsim) == ("v16", True, False, True)
    assert r.model_id == profiles.CINQUE_TERRE_V3.sha256
    # the local model object is untouched by any of that
    assert s.model.policy_generation == "v15" and s.model.is_v15 and not s.model.is_v16

  def test_the_swap_opens_a_settling_window_that_closes(self, stack):
    s = stack()
    _, snap = s.promote()
    assert snap.settling
    s.clock.advance(runner.SETTLE_SECONDS - 0.1)
    assert s.runner.snapshot().settling
    s.clock.advance(0.2)
    assert not s.runner.snapshot().settling

  def test_a_dropped_camera_frame_is_never_skipped_by_the_large_model(self, stack):
    s = stack()
    assert s.runner.can_prepare_only is True       # local: a dropped frame can be prepared and skipped
    s.promote()
    assert s.runner.can_prepare_only is False
    out, _ = s.frame(prepare_only=True)
    assert out["source"] == "remote"                 # it ran; the local flag did not skip it
    assert s.big.frames and s.big.frames[-1].mode == "ok"

  def test_prepare_only_reaches_the_local_model(self, stack):
    s = stack()
    out, _ = s.frame(in_control=True, prepare_only=True)
    assert out is None
    assert s.model.calls[-1].prepare_only is True


class TestTheFrame:
  def test_the_remote_gets_jetlinks_canonical_keys_and_the_local_its_own(self, stack):
    s = stack()
    s.frame(in_control=True)
    local_call = s.model.calls[-1]
    assert set(local_call.bufs) == {"input_imgs", "big_input_imgs"} and set(local_call.transforms) == {"input_imgs", "big_input_imgs"}
    assert local_call.bufs["input_imgs"] == "road" and local_call.bufs["big_input_imgs"] == "wide"
    s.promote()
    s.frame()
    remote = s.big.frames[-1]
    assert remote.bufs == {"img": "road", "big_img": "wide"}
    assert np.array_equal(remote.transforms["img"], s.eye) and np.array_equal(remote.transforms["big_img"], s.eye * 2)
    assert {"traffic_convention", "action_t"} <= set(remote.inputs) and any(k.startswith("desire") for k in remote.inputs)

  def test_action_t_is_required_even_when_the_local_profile_has_none(self, stack):
    s = stack(with_action_t=False)
    assert "action_t" not in s.model.numpy_inputs and s.runner.requires_action_t
    r = s.runner
    with pytest.raises(KeyError, match="action_t"):
      r.run({r.road_key: 1, r.wide_key: 2}, {r.road_key: s.eye, r.wide_key: s.eye}, {r.desire_key: np.zeros(8), "traffic_convention": np.zeros(2)}, False)

  def test_the_frame_builder_puts_action_t_in_for_a_jetlink_runner(self, stack):
    from openpilot.selfdrive.modeld.modeld import _runner_frame_args
    s = stack(with_action_t=False)
    from cereal import log
    bufs, tfm, inputs = _runner_frame_args(s.runner, "road", "wide", s.eye, s.eye, np.zeros(8, np.float32), np.zeros(2),
                                           0.4, 0.7, log.ModelDataV2.Action(), 10.0, np.zeros(2, np.float32))
    assert np.allclose(inputs["action_t"], [0.4, 0.7])   # lateral first, as the local runner orders it
    assert set(bufs) == {"input_imgs", "big_input_imgs"}

  def test_a_shared_warp_is_refused(self, stack):
    s = stack()
    with pytest.raises(RuntimeError, match="shared"):
      s.runner.run({}, {}, {}, False, shared_warp=object())

  def test_a_local_model_whose_queues_were_replaced_is_caught_before_it_runs(self, stack):
    s = stack()
    s.model.input_queues = {**s.model.input_queues, "img_q": object()}
    with pytest.raises(RuntimeError, match="queues changed"):
      s.frame(in_control=True)

  def test_the_local_model_is_pinned_while_attached_and_free_when_not(self, stack):
    s = stack()
    assert s.model.pinned
    assert runner.attach(lambda small, w, h: None, FakeModelState(), 1928, 1208, FakeLog()) is None


class TestHandback:
  def test_a_failure_hands_back_within_the_same_frame_and_resets_the_local_model(self, stack):
    s = stack(big_modes=["ok", "raise"])
    s.promote()
    s.model.numpy_inputs["desire"].fill(5)
    out, snap = s.frame()
    assert out["source"] == "local"                       # the frame was re-run locally, not dropped
    assert snap.backend == runner.LOCAL and snap.handed_over and snap.settling
    assert s.resets == 1
    assert not s.model.numpy_inputs["desire"].any() and not s.model.prev_desire.any()
    assert not s.runner.remote_active and s.runner.policy_generation == "v15"
    assert snap.reason

  def test_the_reset_reaches_every_recurrent_buffer_of_the_local_model(self, stack):
    s = stack()
    surface = s.local.numpy_inputs
    assert {"npy.prev_feat", "npy.desire", "numpy_inputs.desire", "full_prev_desired_curv"} <= set(surface)
    for array in surface.values():
      array.fill(7)
    for array in s.local.numpy_inputs.values():          # what Jetlink's reset does with this dict
      array.fill(0)
    assert not s.model.full_prev_desired_curv.any() and not s.model.npy["prev_feat"].any()
    # npy.desire / npy.prev_feat are views of the packed array: its first 16 floats clear, the rest is not ours to touch
    assert not s.model.packed[:16].any() and s.model.packed[16:].all()

  def test_non_finite_output_is_never_published_and_the_frame_is_rerun_locally(self, stack):
    s = stack(big_modes=["ok", "nan"])
    s.promote()
    out, snap = s.frame()
    assert out["source"] == "local"
    assert all(np.isfinite(v).all() for v in out.values() if isinstance(v, np.ndarray))
    assert snap.backend == runner.LOCAL and "non-finite" in snap.reason
    assert "non-finite" in s.log.text()

  def test_implausible_output_is_treated_the_same(self, stack):
    s = stack(big_modes=["ok", "huge"])
    s.promote()
    out, snap = s.frame()
    assert out["source"] == "local" and "implausible" in snap.reason

  def test_a_reply_without_the_action_head_is_refused(self, stack):
    s = stack()
    s.promote()
    s.big.run = lambda *a, **k: {"plan": np.zeros((1, 33, 15), np.float32), "source": "remote"}
    out, snap = s.frame()
    assert out["source"] == "local" and "missing" in snap.reason

  def test_a_local_model_failure_during_a_handback_is_not_swallowed(self, stack):
    s = stack(big_modes=["ok", "raise"])
    s.promote()
    s.model.fail = True
    with pytest.raises(RuntimeError, match="local model failed"):
      s.frame()

  def test_a_lagging_large_model_is_handed_back_by_the_next_frame(self, stack):
    s = stack()
    s.promote()
    s.big.behind = "held 5 frames in a row"
    out, snap = s.frame()
    assert out["source"] == "remote"                       # this frame is published as it came
    out, snap = s.frame()
    assert out["source"] == "local" and snap.backend == runner.LOCAL

  def test_dropped_camera_frames_behind_the_large_model_hand_back(self, stack):
    s = stack()
    s.promote()
    out, snap = s.frame(drop_ratio=joining.DROP_LIMIT * 2)
    assert out["source"] == "local" and snap.backend == runner.LOCAL

  def test_handback_is_allowed_while_engaged(self, stack):
    s = stack(big_modes=["ok", "raise"])
    s.promote()
    out, snap = s.frame(in_control=True)
    assert out["source"] == "local" and snap.backend == runner.LOCAL

  def test_nothing_re_promotes_while_the_driver_is_in_control(self, stack):
    s = stack(big_modes=["ok", "raise"])
    s.promote()
    s.frame(in_control=True)                              # handed back, driver engaged
    for _ in range(40):
      out, snap = s.frame(in_control=True)
      assert out["source"] == "local"
    assert wait_until(lambda: s.joining.big_model_available)
    assert s.frame(in_control=True)[1].backend == runner.LOCAL
    assert s.frame(in_control=False)[0]["source"] == "remote"

  def test_repeated_handbacks_lock_the_large_model_out_for_the_drive(self, stack):
    s = stack(default_mode="ok")
    for n in range(runner.MAX_HANDBACKS):
      s.promote() if n == 0 else self._repromote(s)
      s.big.modes = ["raise"]
      out, snap = s.frame()
      assert out["source"] == "local"
    assert s.runner.locked_out
    assert wait_until(lambda: s.joining.big_model_available)
    for _ in range(10):
      out, snap = s.frame(in_control=False)
      assert out["source"] == "local" and snap.accelerator == "unavailable"
    assert "handbacks" in s.log.text()

  @staticmethod
  def _repromote(s):
    assert wait_until(lambda: s.joining.big_model_available)
    out, _ = s.frame(in_control=False)
    assert out["source"] == "remote"


class TestHeldFrames:
  def test_a_held_output_is_published_with_its_true_age(self, stack):
    s = stack(big_modes=["ok", "hold", "hold", "ok"])
    s.promote()
    _, snap = s.frame()
    assert (snap.held_frames, snap.output_age_ms) == (1, 50.0)
    _, snap = s.frame()
    assert (snap.held_frames, snap.output_age_ms) == (2, 100.0)
    _, snap = s.frame()
    assert (snap.held_frames, snap.output_age_ms) == (0, 0.0)

  def test_the_local_model_never_reports_an_age(self, stack):
    s = stack()
    _, snap = s.frame(in_control=True)
    assert (snap.held_frames, snap.output_age_ms) == (0, 0.0)


class TestStatus:
  def test_the_status_names_the_external_model_when_it_runs_or_is_ready(self, stack):
    s = stack()
    for _ in range(joining.SMALL_WARMUP_FRAMES + 1):
      _, snap = s.frame(in_control=True)
    assert wait_until(lambda: s.joining.big_model_available)
    _, snap = s.frame(in_control=True)
    assert snap.accelerator == "ready" and snap.remote_model == profiles.CINQUE_TERRE_V3.name
    _, snap = s.frame(in_control=False)
    assert snap.accelerator == "running" and snap.remote_model == profiles.CINQUE_TERRE_V3.name

  def test_no_remote_model_is_named_while_joining(self, stack):
    s = stack()
    _, snap = s.frame(in_control=True)
    assert snap.accelerator in ("joining", "ready") and (snap.remote_model == "" or snap.accelerator == "ready")

  def test_a_handover_is_reported_once(self, stack):
    s = stack()
    _, snap = s.promote()
    assert snap.handed_over and snap.backend_changed
    snap = s.frame()[1]
    assert not snap.handed_over and not snap.backend_changed

  def test_the_reason_of_an_old_handback_is_not_shown_once_the_large_model_drives_again(self, stack):
    s = stack(big_modes=["ok", "raise"])
    s.promote()
    _, snap = s.frame()
    assert snap.backend == runner.LOCAL and snap.reason
    assert wait_until(lambda: s.joining.big_model_available)
    out, snap = s.frame(in_control=False)
    assert out["source"] == "remote" and snap.backend == runner.JETLINK and snap.reason == ""

  def test_a_lag_decision_moves_the_handover_count_without_changing_the_backend(self, stack):
    s = stack()
    s.promote()
    s.big.behind = "held 5 frames in a row"
    _, snap = s.frame()
    assert snap.handed_over and not snap.backend_changed and snap.backend == runner.JETLINK
    _, snap = s.frame()
    assert snap.backend_changed and snap.backend == runner.LOCAL
