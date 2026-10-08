"""Jetlink's own join() with the fork's hooks: the validated-model gate, and the vendored patch."""
import subprocess
import types
from pathlib import Path

import pytest

from jetlink.openpilot import joining
from openpilot.starpilot import jetlink_adapter as ja
from openpilot.starpilot.jetlink_adapter import profiles, runner
from openpilot.starpilot.jetlink_adapter.tests.fakes import FakeBig, FakeLog, FakeModelState, FakeProgress, p_spec, wait_until

VENDOR = Path(ja.VENDOR_DIR)


class FakeParts:
  """The pieces of jetlink.openpilot.parts.Parts that join() reads."""

  def __init__(self, op):
    self.op = op
    self.log = FakeLog()
    self.progress = FakeProgress()
    self.spec = types.SimpleNamespace(load=lambda: p_spec())
    self.warps = types.SimpleNamespace(geometry=lambda: (1928, 1208, 512, 256), load=lambda *a: "warp-jit")


@pytest.fixture
def fake_join(monkeypatch):
  """join() over a fake link, fake warp and fake large model state; the real joining model and the real adapter."""
  from jetlink.openpilot import link as links
  from jetlink.openpilot import model_state, warp
  built = []
  specs = {"spec": p_spec()}

  class FakeLink:
    def __init__(self, log):
      pass

    def close(self):
      pass
  monkeypatch.setattr(links, "Link", FakeLink)
  monkeypatch.setattr(links, "present_early", lambda link, bg: None)
  monkeypatch.setattr(links, "open_link", lambda parts, link, should_stop=None: (types.SimpleNamespace(
    dead=False, leave=lambda *a, **k: None, ping=lambda timeout=None: None, close=lambda: None), specs["spec"]))
  monkeypatch.setattr(warp, "Warp", lambda jit, frame_size, log: "warp")
  monkeypatch.setattr(warp, "prepare_reset", lambda small: (lambda: None))

  def make_state(client, spec, warp_, *, face, log, event):
    big = FakeBig(spec)
    built.append(big)
    return big
  monkeypatch.setattr(model_state, "JetlinkModelState", make_state)
  monkeypatch.setattr(joining, "REJOIN_DELAY_QUICK", 0.02)
  monkeypatch.setattr(joining, "REJOIN_DELAY", 0.02)

  op = ja.Adapter()
  yield types.SimpleNamespace(parts=FakeParts(op), built=built, specs=specs)


def attach_and_run(fake):
  model = FakeModelState()
  jr = runner.attach(lambda small, w, h: joining.join(fake.parts, w, h, small), model, 1928, 1208, FakeLog())
  assert jr is not None
  import numpy as np
  eye = np.eye(3, dtype=np.float32)

  def frame(in_control):
    jr.set_control(in_control, 0.0, False)
    inputs = {jr.desire_key: np.zeros(8, np.float32), "traffic_convention": np.array([1., 0.]), "action_t": np.array([.3, .6])}
    out = jr.run({jr.road_key: 1, jr.wide_key: 2}, {jr.road_key: eye, jr.wide_key: eye}, inputs, False)
    return out, jr.snapshot()
  return jr, frame


def test_a_validated_server_model_is_promoted(fake_join):
  jr, frame = attach_and_run(fake_join)
  try:
    for _ in range(joining.SMALL_WARMUP_FRAMES):
      frame(True)
    assert wait_until(lambda: jr._joining.big_model_available)
    out, snap = frame(False)
    assert out["source"] == "remote" and snap.backend == runner.JETLINK and jr.profile is profiles.CINQUE_TERRE_V3
  finally:
    jr.close()


@pytest.mark.parametrize("change", [{"sha256": "f" * 64}, {"frame_skip": 1}])
def test_an_unvalidated_server_model_is_never_promoted_and_the_reason_is_kept(fake_join, change):
  from jetlink.spec import ModelSpec
  good = p_spec()
  fake_join.specs["spec"] = ModelSpec(**{**good.__dict__, **change})
  jr, frame = attach_and_run(fake_join)
  try:
    for _ in range(joining.SMALL_WARMUP_FRAMES):
      frame(True)
    assert wait_until(lambda: jr._joining.big_model_available)
    for _ in range(10):
      out, snap = frame(False)
      assert out["source"] == "local" and snap.backend == runner.LOCAL
    assert not fake_join.built                              # the large model state was never built
    assert wait_until(lambda: "UnsupportedModel" in jr._joining.last_failure)
    assert "UnsupportedModel" in snap.reason or wait_until(lambda: "UnsupportedModel" in jr.snapshot().reason)
  finally:
    jr.close()


def test_the_join_that_cannot_be_built_leaves_the_plain_local_model(fake_join, monkeypatch):
  def broken(parts, w, h, small):
    raise RuntimeError("no warp")
  from openpilot.starpilot.jetlink_adapter import _guarded
  guarded_attach = _guarded(None)(lambda small, w, h: broken(None, w, h, small))
  model = FakeModelState()
  assert runner.attach(guarded_attach, model, 1928, 1208, FakeLog()) is None
  assert not model.pinned                                   # and the model's reset guard is released


def test_attach_returning_the_small_model_means_the_join_failed(monkeypatch):
  model = FakeModelState()
  log = FakeLog()
  assert runner.attach(lambda small, w, h: small, model, 1928, 1208, log) is None
  assert "could not be built" in log.text() and not model.pinned


def test_the_local_modifications_patch_describes_the_vendored_file_exactly():
  """LOCAL_MODIFICATIONS.patch is the review artifact for the vendored package: reversing it must apply cleanly, so the file
  and the patch cannot drift apart."""
  patch = VENDOR / "LOCAL_MODIFICATIONS.patch"
  assert patch.is_file()
  result = subprocess.run(["patch", "-R", "-p1", "--dry-run", "-i", str(patch)], cwd=VENDOR, capture_output=True, text=True)
  assert result.returncode == 0, result.stdout + result.stderr


def test_the_hook_the_patch_adds_is_the_one_the_adapter_provides():
  source = (VENDOR / "jetlink/openpilot/joining.py").read_text()
  assert "validate_spec" in source and "def demote_invalid" in source
  assert callable(ja.Adapter.validate_spec)
