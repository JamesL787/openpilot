"""modeld.main(), the real frame loop, driven end to end.

Faked at the edges only: the camera (VisionIpc), messaging (SubMaster/PubMaster), the model artifacts (a ModelState stand-in),
realtime scheduling, and the host (a large-model state with injectable faults). In the middle is everything the product runs:
modeld's loop, the JetlinkRunner, Jetlink's own JoiningModelState (vendored), the adapter's engagement gate, the real Params
(isolated under a temporary root), the real parser/action/publish path, and real capnp messages for every service.

What this proves is that the pieces are wired to each other correctly across a drive: promotion only while disengaged, a
handback while engaged that costs no published frame beyond the dropped one, no hand-back caused by a swap's own stall,
status published on every frame, the runtime params following the backend while the user's selection never changes, and a
local-model failure still ending modeld as before. It does not prove the large model drives well."""
import types

import numpy as np
import pytest

from cereal import car, messaging
from jetlink.openpilot import joining
from openpilot.common.params import Params
from openpilot.selfdrive.modeld import modeld
from openpilot.starpilot.jetlink_adapter import profiles
from openpilot.starpilot.jetlink_adapter.tests.fakes import FakeBig, FakeLog, FakeModelState, FakeProgress, p_spec, wait_until


class LoopDone(Exception):
  pass


class FakeBuf:
  def __init__(self):
    self.data = np.zeros(16, np.uint8)


class FakeVipc:
  """Camera client. `script(i)` runs before frame i is handed over and may mutate sm state or raise LoopDone."""
  script = None
  skip_after: dict = {}
  count = 0
  frame_id = 0

  @staticmethod
  def available_streams(name, block=False):
    return {modeld.VisionStreamType.VISION_STREAM_ROAD}

  def __init__(self, name, stream, conflate):
    self.width, self.height, self.buffer_len = 1928, 1208, 5
    self.timestamp_sof = self.timestamp_eof = 0

  def connect(self, blocking):
    return True

  def recv(self):
    i = FakeVipc.count
    FakeVipc.count += 1
    FakeVipc.script(i)
    FakeVipc.frame_id += 1 + FakeVipc.skip_after.get(i, 0)        # camera frames the loop never sees
    self.frame_id = FakeVipc.frame_id
    self.timestamp_sof = int(self.frame_id * 5e7)
    self.timestamp_eof = self.timestamp_sof + int(3e7)
    return FakeBuf()


SERVICES = ("deviceState", "carState", "roadCameraState", "liveCalibration", "driverMonitoringState", "carControl", "liveDelay",
            "starpilotPlan", "starpilotCarState")


class FakeSm:
  def __init__(self, services):
    self.msgs = {s: messaging.new_message(s) for s in services}
    self.frame = 0
    self.updated = dict.fromkeys(services, False)
    self.seen = dict.fromkeys(services, True)
    self.alive = dict.fromkeys(services, True)
    self.valid = dict.fromkeys(services, True)

  def update(self, timeout=0):
    self.frame += 1
    self.updated = dict.fromkeys(self.updated, False)
    self.updated["liveCalibration"] = self.frame == 1

  def __getitem__(self, key):
    return getattr(self.msgs[key], key)

  def all_alive(self, services=None):
    return all(self.alive[s] for s in (services or self.alive))

  def all_valid(self, services=None):
    return all(self.valid[s] for s in (services or self.valid))


class FakePm:
  sent: list = []

  def __init__(self, services):
    pass

  def send(self, name, msg):
    FakePm.sent.append((name, msg))


@pytest.fixture
def drive(monkeypatch, tmp_path):
  """Run modeld.main() for `frames` frames; returns the harness after it ends."""
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  monkeypatch.setenv("OPENPILOT_PREFIX", "jetlink-loop-test")
  params = Params()
  cp = car.CarParams.new_message(brand="honda", carFingerprint="HONDA_CLARITY")
  params.put("CarParams", cp.to_bytes())

  def run(frames, script, big_modes=None, skip_after=None, fail_local_at=None, link_on=True, prepared=True, chestnut=False):
    sm_holder = {}
    FakePm.sent = []
    FakeVipc.count, FakeVipc.frame_id, FakeVipc.skip_after = 0, 0, skip_after or {}
    model = FakeModelState()
    bigs = []
    harness = types.SimpleNamespace(bigs=bigs, model=model, joining=None, runner=None, params=params, sent=FakePm.sent)

    def make_sm(services):
      sm_holder["sm"] = harness.sm = FakeSm(services)
      return sm_holder["sm"]

    def frame_script(i):
      sm = sm_holder["sm"]
      sm["carState"].vEgo = 15.0
      sm["roadCameraState"].frameId = FakeVipc.frame_id
      sm["roadCameraState"].sensor = "ar0231"
      sm["deviceState"].deviceType = "tici"
      sm["liveCalibration"].rpyCalib = [0.0, 0.0, 0.0]
      sm["liveDelay"].lateralDelay = 0.2
      script(i, harness)
      if fail_local_at is not None and i == fail_local_at:
        model.fail = True
      if i >= frames:
        raise LoopDone()
    FakeVipc.script = staticmethod(frame_script)

    def attach(small, w, h):
      if not link_on:
        return None
      spec = p_spec()

      def build(client, s):
        big = FakeBig(s, big_modes if not bigs else None)
        bigs.append(big)
        return big
      client = types.SimpleNamespace(dead=False, leave=lambda *a, **k: None, ping=lambda timeout=None: None, close=lambda: None)

      def reset():
        for array in small.numpy_inputs.values():
          array.fill(0)
        harness.model.prev_desire.fill(0)
      j = joining.JoiningModelState(small, lambda should_stop=None: (client, spec), build, None, reset_small=reset,
                                    progress=FakeProgress(), log=FakeLog())
      harness.joining = j
      return j

    monkeypatch.setattr(joining, "REJOIN_DELAY_QUICK", 0.02)
    monkeypatch.setattr(joining, "REJOIN_DELAY", 0.02)
    monkeypatch.setattr(modeld, "VisionIpcClient", FakeVipc)
    monkeypatch.setattr(modeld, "SubMaster", make_sm)
    monkeypatch.setattr(modeld, "PubMaster", FakePm)
    monkeypatch.setattr(modeld, "config_realtime_process", lambda *a, **k: None)
    monkeypatch.setattr(modeld, "usbgpu_present", lambda: chestnut)
    monkeypatch.setattr(modeld, "_load_model_state", lambda *a, **k: model)
    monkeypatch.setattr(modeld, "_isolate_next_model_artifact_load", lambda: 0)
    monkeypatch.setattr(modeld.jetlink_adapter, "prepare", lambda: prepared)
    monkeypatch.setattr(modeld.jetlink_adapter, "attach", attach)
    monkeypatch.setattr(modeld.atexit, "register", lambda fn: harness.__dict__.setdefault("closers", []).append(fn))
    monkeypatch.setattr(modeld.sentry, "set_tag", lambda *a, **k: None)
    try:
      modeld.main(demo=False)
    except LoopDone:
      pass
    finally:
      for close in harness.__dict__.get("closers", []):
        close()
    harness.status = [m.starpilotModelV2 for n, m in FakePm.sent if n == "starpilotModelV2"]
    harness.models = [m.modelV2 for n, m in FakePm.sent if n == "modelV2"]
    harness.actions = [m.drivingModelData.action for n, m in FakePm.sent if n == "drivingModelData"]
    return harness
  run.params = params
  return run


def backends(h):
  return [str(s.backend) for s in h.status]


def engage(i, h, engaged_frames):
  cc = h.sm["carControl"]
  cc.enabled = i in engaged_frames
  cc.latActive = cc.enabled


class TestADrive:
  def test_the_local_model_alone_is_what_it_was(self, drive):
    h = drive(40, lambda i, h: None, link_on=False)
    assert backends(h) == ["local"] * len(h.status) and len(h.models) > 30
    assert all(str(s.accelerator) == "none" and not s.remoteModel for s in h.status)   # nothing is published about a link
    assert h.params.get("ModelVersion") == "v15"

  def test_a_disengaged_car_is_promoted_after_the_local_warmup_and_publishes_the_switch(self, drive):
    def script(i, h):
      engage(i, h, set())
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
    h = drive(60, script)
    seq = backends(h)
    assert seq[0] == "local" and "jetlink" in seq
    first = seq.index("jetlink")
    assert seq[first:] == ["jetlink"] * (len(seq) - first)                              # and stays
    s = h.status[first]
    assert str(s.accelerator) == "running" and s.remoteModel == profiles.CINQUE_TERRE_V3.name and s.handovers >= 1
    assert h.params.get("ModelVersion") == "v16" and "Jetlink" in h.params.get("DrivingModelName", encoding="utf-8")

  def test_the_users_model_selection_is_never_pointed_at_the_external_model(self, drive):
    def script(i, h):
      engage(i, h, set())
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
    h = drive(40, script)
    assert "jetlink" in backends(h)
    assert all(s.reason == "" for s in h.status if str(s.backend) == "jetlink")
    assert h.params.get("Model", encoding="utf-8") == "rdf43" and h.params.get("DrivingModel", encoding="utf-8") == "rdf43"

  def test_an_engaged_car_is_never_promoted(self, drive):
    def script(i, h):
      engage(i, h, set(range(200)))
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
    h = drive(60, script)
    assert set(backends(h)) == {"local"} and str(h.status[-1].accelerator) == "ready"

  def test_a_paused_always_on_lateral_that_will_resume_is_never_promoted_over(self, drive):
    def script(i, h):
      engage(i, h, set())
      fp = h.sm["starpilotCarState"]
      fp.alwaysOnLateralAllowed, fp.alwaysOnLateralEnabled = True, False       # armed, paused by a blinker or the brake
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
    h = drive(60, script)
    # the car's AOL flag is read from StarPilotCarParams: unknown counts as possible, so it waits
    assert set(backends(h)) == {"local"}

  def test_an_aol_that_the_car_cannot_run_does_not_block_the_swap_once_the_car_params_say_so(self, drive):
    from cereal import custom
    drive.params.put("StarPilotCarParams", custom.StarPilotCarParams.new_message(alternativeExperience=0).to_bytes())

    def script(i, h):
      engage(i, h, set())
      fp = h.sm["starpilotCarState"]
      fp.alwaysOnLateralAllowed = True            # a main-cruise toggle: "allowed" without any AOL to resume
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
    h = drive(80, script)
    seq = backends(h)
    assert seq[0] == "local" and seq[-1] == "jetlink"                    # waited for the car params, then swapped

  def test_stale_engagement_inputs_hold_it_off(self, drive):
    def script(i, h):
      engage(i, h, set())
      h.sm.alive["carControl"] = False
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
    h = drive(50, script)
    assert set(backends(h)) == {"local"}

  def test_a_handback_while_engaged_costs_the_dropped_frames_and_nothing_else(self, drive):
    def script(i, h):
      engage(i, h, set(range(40, 200)))
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
      if i == 39:
        h.bigs[-1].modes = ["raise"]
    h = drive(70, script, skip_after={41: 2})
    seq = backends(h)
    assert "jetlink" in seq and seq[-1] == "local"
    frames_remote = [i for i, b in enumerate(seq) if b == "jetlink"]
    assert seq[frames_remote[-1] + 1:] == ["local"] * (len(seq) - frames_remote[-1] - 1)
    # the status and the model message are one frame, and the action never went missing or non-finite
    assert len(h.status) == len(h.models) == len(h.actions)
    assert all(np.isfinite([a.desiredCurvature, a.desiredAcceleration]).all() for a in h.actions)
    assert h.params.get("ModelVersion") == "v15"                         # restored from the local model

  def test_a_swaps_own_stall_does_not_hand_it_back(self, drive):
    """The camera frames dropped while a swap stalls modeld reach the drop filter on the next frame. The large model hands
    back past a dropped-frame ratio just short of modeldLagging, so unless the filter's warm-up is re-run at a handover the
    swap hands itself straight back."""
    def script(i, h):
      engage(i, h, set(range(30)))                                              # engaged for the first 30 frames, then free
      if i == 0:
        assert wait_until(lambda: h.joining.big_model_available)
    probe = drive(60, script)
    swap = backends(probe).index("jetlink")                                   # the loop iteration the swap lands on
    assert swap >= 30                                                         # past modeld's own 10-frame drop warm-up
    h = drive(100, script, skip_after={swap + 1: 2})                          # two camera frames lost right after it
    seq = backends(h)
    assert seq.index("jetlink") >= 0 and seq[-1] == "jetlink"
    assert [i for i in range(1, len(seq)) if seq[i - 1] == "jetlink" and seq[i] == "local"] == []
    # the same stall without the forgiveness would have crossed the limit
    from jetlink.openpilot import joining as jl
    assert 2 * 0.05 / (10.0 + 0.05) / (1 + 2 * 0.05 / (10.0 + 0.05)) > jl.DROP_LIMIT

  def test_a_failing_local_model_still_ends_modeld(self, drive):
    def script(i, h):
      engage(i, h, set())
    with pytest.raises(RuntimeError, match="local model failed"):
      drive(30, script, link_on=False, fail_local_at=10)

  def test_an_unprepared_link_never_attaches(self, drive):
    h = drive(30, lambda i, h: engage(i, h, set()), prepared=False)
    assert h.joining is None and h.status and set(backends(h)) == {"local"}

  def test_a_fitted_chestnut_refuses_the_attach_even_if_the_adapter_said_yes(self, drive):
    """Jetlink's own enabled() already keeps the link off beside a Chestnut; modeld does not rely on it alone."""
    h = drive(10, lambda i, h: engage(i, h, set()), chestnut=True)
    assert h.joining is None and set(backends(h)) <= {"local"}
