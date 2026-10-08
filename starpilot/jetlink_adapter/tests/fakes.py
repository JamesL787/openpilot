"""Fakes for the Jetlink seam: a ModelState stand-in, a large-model state with controllable faults, and a link.

The joining model under test is Jetlink's own JoiningModelState (the vendored one); only the two ends it joins are faked."""
import threading
import types

import numpy as np

from jetlink.openpilot.model_state import Trips
from openpilot.selfdrive.modeld.parse_model_outputs import Parser
from openpilot.starpilot.jetlink_adapter import profiles

P = profiles.CINQUE_TERRE_V3


def raw_output(seed: int = 0, scale: float = 0.1) -> np.ndarray:
  return (np.random.default_rng(seed).standard_normal(P.output_shapes["outputs"][1]) * scale).astype(np.float32)


def parsed_output(seed: int = 0) -> dict[str, np.ndarray]:
  """What JetlinkModelState._outputs returns: the real Parser over the pinned model's real head slices."""
  raw = raw_output(seed)
  sliced = {k: raw[np.newaxis, a:b] for k, (a, b) in P.output_slices.items()}
  return Parser().parse_outputs(sliced)


class FakeTensor:
  device = "CPU"

  def __init__(self, n=4):
    self.n = n


class FakeModelState:
  """The parts of selfdrive.modeld.modeld.ModelState that the seam touches."""
  road_key, wide_key, desire_key = "input_imgs", "big_input_imgs", "desire"
  vision_input_names = ["input_imgs", "big_input_imgs"]
  off_policy_enabled = False
  off_policy_numpy_inputs: dict = {}
  can_prepare_only = True
  model_id = "rdf43"
  policy_generation = "v15"
  mlsim, is_v9, is_v14, is_v15, is_v16 = True, False, False, True, False
  uses_external_gpu = False

  def __init__(self, with_action_t=False):
    self.input_queues = {"img_q": FakeTensor(), "feat_q": FakeTensor(), "packed_npy_inputs": FakeTensor()}
    self.packed = np.ones(24, dtype=np.float32)
    self.npy = {"desire": self.packed[:8], "prev_feat": self.packed[8:16], "tfm": np.ones((3, 3), np.float32)}
    self.numpy_inputs = {"desire": np.ones(8, np.float32), "lateral_control_params": np.ones(2, np.float32)}
    if with_action_t:
      self.numpy_inputs["action_t"] = np.ones(2, np.float32)
    self.prev_desire = np.ones(8, np.float32)
    self.full_prev_desired_curv = np.ones((1, 100, 1), np.float32)
    self.pinned = False
    self.calls = []
    self.output_seed = 100
    self.fail = False

  def pin_buffers(self):
    self.pinned = True

  def unpin_buffers(self):
    self.pinned = False

  def run(self, bufs, transforms, inputs, prepare_only, after_output_sync=None, shared_warp=None, *, blinker_on=False):
    if self.fail:
      raise RuntimeError("local model failed")
    self.calls.append(types.SimpleNamespace(bufs=bufs, transforms=transforms, inputs=inputs, prepare_only=prepare_only,
                                            blinker_on=blinker_on, after_output_sync=after_output_sync))
    if prepare_only:
      return None
    return {"source": "local", **parsed_output(self.output_seed)}


class FakeBig:
  """JetlinkModelState's frame-facing surface. `mode` per frame: 'ok', 'hold', 'raise', 'nan', 'huge'."""

  def __init__(self, spec, modes=None):
    self.spec = spec
    self.chestnut = True
    self.lat_delay = 0.0
    self.behind = None
    self.trips = Trips()
    self.client = types.SimpleNamespace(dead=False, leave=lambda *a, **k: None, ping=lambda timeout=None: None, close=lambda: None)
    self.frames = []
    self.modes = list(modes or [])
    self.default_mode = "ok"
    self.closed = False
    self._frame = 0

  def run(self, bufs, transforms, inputs, after_enqueue=None):
    self._frame += 1
    mode = self.modes.pop(0) if self.modes else self.default_mode
    self.frames.append(types.SimpleNamespace(bufs=bufs, transforms=transforms, inputs=inputs, mode=mode))
    if mode == "raise":
      raise RuntimeError("link lost")
    out = {"source": "remote", **parsed_output(self._frame)}
    if mode == "hold":
      self.trips.held += 1
    elif mode == "nan":
      out["plan"] = out["plan"].copy()
      out["plan"][0, 0, 0] = np.nan
    elif mode == "huge":
      out["plan"] = out["plan"].copy()
      out["plan"][0, 0, 0] = 1e9
    return out

  def close(self):
    self.closed = True


class FakeProgress:
  def __init__(self):
    self.reports = []

  def report(self, stage, frac, msg="", drops=0):
    self.reports.append((stage, msg))

  def clear(self):
    pass


class FakeLog:
  def __init__(self):
    self.lines = []

  def _add(self, level, msg, *args, **kw):
    self.lines.append((level, msg % args if args else msg))

  def warning(self, msg, *a, **k):
    self._add("warning", msg, *a)

  def error(self, msg, *a, **k):
    self._add("error", msg, *a)

  def info(self, msg, *a, **k):
    self._add("info", msg, *a)

  def exception(self, msg, *a, **k):
    self._add("exception", msg, *a)

  def event(self, name, **fields):
    self.lines.append(("event", name))

  def text(self):
    return "\n".join(m for _, m in self.lines)


class FakeClock:
  def __init__(self):
    self.t = 1000.0

  def __call__(self):
    return self.t

  def advance(self, dt):
    self.t += dt


def wait_until(predicate, timeout=5.0):
  done = threading.Event()
  t = 0.0
  while t < timeout:
    if predicate():
      return True
    done.wait(0.01)
    t += 0.01
  return predicate()


def p_spec():
  from jetlink.spec import ModelSpec
  return ModelSpec(sha256=P.sha256, nbytes=P.nbytes, frame_skip=P.frame_skip, input_shapes=dict(P.input_shapes),
                   output_shapes=dict(P.output_shapes), output_slices={k: slice(*v) for k, v in P.output_slices.items()},
                   checkpoint=None)
