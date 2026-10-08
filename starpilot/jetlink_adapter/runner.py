"""
The runner seam between this fork's modeld and Jetlink's joining model.

Jetlink hands modeld one object, a JoiningModelState, that drives as the *small* model until a Jetson/Mac is there and then
swaps the *large* model in underneath. That object is written against a differently shaped ModelState than this fork's, so
two explicit facades sit on either side of it rather than a pile of attribute fallbacks:

    modeld ──> JetlinkRunner ──> JoiningModelState ──> LocalRunner ──> ModelState  (small model, local fallback)
                  (this fork's                     └──> JetlinkModelState ──> USB ──> host   (large model)
                   ModelState.run signature)

``LocalRunner`` is what Jetlink sees as ``small``: ``run(bufs, transforms, inputs, after_enqueue)`` with Jetlink's canonical
camera keys (``img`` / ``big_img``), delegating to ``ModelState.run(..., prepare_only, after_output_sync, blinker_on=)``, and
exposing exactly the state Jetlink's in-place reset (``jetlink.openpilot.warp.prepare_reset``) needs to clear.

``JetlinkRunner`` is what modeld runs: the same ``run(...)`` and attribute surface as ModelState, with this fork's
extra arguments, plus the per-frame control hand-off (``set_control``) and a ``snapshot()`` for the status message. It
knows which backend produced the last output and which generation flags apply *to that backend*; the remote model's
flags come from ``profiles`` (validated by the model's SHA-256), never from the local fallback.

Only modeld imports this module: it needs numpy and, through the model, tinygrad.
"""
from __future__ import annotations

import time
from typing import NamedTuple

import numpy as np

from openpilot.starpilot.jetlink_adapter import profiles

# After a backend switch, either way, this long counts as "settling": selfdrived holds engagement off and tolerates the
# one invalid pose a switch can cost (see jetlink_events). A second is ~20 frames, which is what the large model needs to
# prove it keeps up (jetlink.openpilot.model_state.PROVING_FRAMES) and the small model needs to refill its history
SETTLE_SECONDS = 1.0

# Backend switches back to the small model before the large one is locked out for the rest of the drive. Jetlink retries
# on its own (quickly three times, then 5, 10, 20, 40, 60 s); a link that keeps handing back is a cable or a host that
# cannot keep 20 Hz, and each swap costs a frame or two of modeld
MAX_HANDBACKS = 3

# 20 Hz: how old a held plan is, per frame held
FRAME_PERIOD_MS = 50.0

# the large model's output is physical quantities in metres, seconds and probabilities; a value past this is a corrupted
# reply, not a plan. The server rejects non-finite output already (Status.NOT_FINITE); this is the comma's own check
MAX_ABS_REMOTE_OUTPUT = 1e6

LOCAL = 'local'
JETLINK = 'jetlink'

# the model Jetlink runs when the fork gives it no pick (the vendored package's pinned default)
DEFAULT_REMOTE = profiles.CINQUE_TERRE_V3


class FrameContext(NamedTuple):
  """What a frame needs beyond Jetlink's four-argument run(), handed to the local model through LocalRunner."""
  prepare_only: bool = False
  blinker_on: bool = False


class RemoteOutputInvalid(RuntimeError):
  """The large model returned something that must not be published."""


def _reset_surface(model) -> dict[str, np.ndarray]:
  """Every host-side array of the local ModelState that carries history across frames, under unique names.

  Jetlink's reset zeroes ``numpy_inputs.values()`` in place and the GPU queues through a TinyJit it captured at attach
  time. ModelState keeps recurrent state in more places than the one dict Jetlink knows: ``npy`` (views of the packed NPY
  inputs, including prev_feat), ``numpy_inputs``, and ``full_prev_desired_curv`` (the multi-second curvature history
  that feeds ``prev_desired_curv``). All of them are listed here so a handback starts from the same all-zero history as a
  modeld start. The arrays are referenced, never copied, so the fills land in the model's own memory."""
  surface: dict[str, np.ndarray] = {}
  for name, array in model.npy.items():
    surface[f"npy.{name}"] = array
  for name, array in model.numpy_inputs.items():
    surface[f"numpy_inputs.{name}"] = array
  curv = getattr(model, 'full_prev_desired_curv', None)
  if curv is not None:
    surface['full_prev_desired_curv'] = curv
  return surface


class LocalRunner:
  """This fork's ModelState, presented to Jetlink as ``small``."""

  def __init__(self, model):
    self.model = model
    self.road_key = model.road_key
    self.wide_key = model.wide_key
    self.desire_key = model.desire_key
    self.vision_input_names = model.vision_input_names
    # captured by Jetlink's reset at attach(): pin the identities. ModelState._reset_state() allocates new queues, which
    # would leave the reset clearing buffers the model no longer reads, so it refuses to run from now on
    self.input_queues = model.input_queues
    self.prev_desire = model.prev_desire
    self.numpy_inputs = _reset_surface(model)
    self._queue_ids = {k: id(v) for k, v in model.input_queues.items()}
    self._array_ids = {k: id(v) for k, v in self.numpy_inputs.items()}
    model.pin_buffers()
    # JoiningModelState writes these on both models, every frame (setters in joining.py); nothing here reads them
    self.lat_delay = 0.0
    self.PLANPLUS_CONTROL = 1.0
    self.frame_drop_ratio = 0.0
    self.in_control = True
    self._frame = FrameContext()

  def set_frame(self, frame: FrameContext) -> None:
    self._frame = frame

  def buffers_intact(self) -> bool:
    """Are the queues and arrays Jetlink's reset captured still the model's own?"""
    m = self.model
    return (m.input_queues is self.input_queues and m.prev_desire is self.prev_desire and
            {k: id(v) for k, v in m.input_queues.items()} == self._queue_ids and
            {k: id(v) for k, v in _reset_surface(m).items()} == self._array_ids)

  def run(self, bufs, transforms, inputs, after_enqueue=None):
    """Jetlink's call: canonical keys in, ModelState's own out.

    ``after_enqueue`` is Jetlink's "publish health while the host works"; for the local model the closest hook is
    ModelState's ``after_output_sync``, which runs after the GPU queue has synchronized. They are different moments, and
    the only user of either (Chestnut's telemetry) is excluded while Jetlink runs, so modeld passes None."""
    frame, self._frame = self._frame, FrameContext()
    return self.model.run(
      {self.road_key: bufs['img'], self.wide_key: bufs['big_img']},
      {self.road_key: transforms['img'], self.wide_key: transforms['big_img']},
      inputs, frame.prepare_only, after_output_sync=after_enqueue, blinker_on=frame.blinker_on)


class Snapshot(NamedTuple):
  """What modeld publishes in starpilotModelV2 about the runner, taken after each run()."""
  backend: str                # LOCAL | JETLINK: which runner produced the output just returned
  accelerator: str            # jetlink.openpilot.STATES, or 'unavailable' while locked out
  settling: bool
  handovers: int
  held_frames: int            # consecutive held frames at the end of this one (0: fresh)
  output_age_ms: float
  remote_model: str           # the external model that runs, or is ready to; '' when unknown
  handed_over: bool           # Jetlink's handover count moved since the last snapshot: a swap, a demote, or a lag decision
  backend_changed: bool       # the backend that produced the output differs from the last snapshot's
  reason: str                 # why the last demotion happened, '' otherwise


class JetlinkRunner:
  """modeld's model while Jetlink is attached. The same surface modeld uses on a ModelState, backed by the joining model."""

  # modeld must put action_t in every frame: the large model requires it whether or not the local profile has it
  requires_action_t = True
  uses_external_gpu = False
  fused = False
  last_warp_output = None

  def __init__(self, joining, local: LocalRunner, log, clock=time.monotonic):
    self._joining = joining
    self._local = local
    self._log = log
    self._clock = clock
    self._remote_active = False
    self._profile: profiles.RemoteProfile | None = None
    self._handovers_seen = joining.handovers
    self._handbacks = 0
    self._locked_out = False
    self._settle_until = 0.0
    self._held_total = 0
    self._held_run = 0
    self._last_reason = ''
    self._in_control = True
    self._blinker_on = False
    self._last_backend = LOCAL

  # -- the ModelState surface modeld reads -----------------------------------------

  @property
  def road_key(self) -> str:
    return self._local.road_key

  @property
  def wide_key(self) -> str:
    return self._local.wide_key

  @property
  def desire_key(self) -> str:
    return self._local.desire_key

  @property
  def numpy_inputs(self):
    return self._local.model.numpy_inputs

  @property
  def off_policy_enabled(self) -> bool:
    return self._local.model.off_policy_enabled

  @property
  def off_policy_numpy_inputs(self):
    return self._local.model.off_policy_numpy_inputs

  @property
  def vision_input_names(self):
    return self._local.vision_input_names

  @property
  def local_model(self):
    """The small model's own ModelState: what drives, and what hands back."""
    return self._local.model

  @property
  def remote_active(self) -> bool:
    return self._remote_active

  @property
  def profile(self) -> profiles.RemoteProfile | None:
    return self._profile if self._remote_active else None

  @property
  def can_prepare_only(self) -> bool:
    # a dropped camera frame can be skipped only by the local warp-history pipeline. The large model keeps its history on
    # the host and needs every frame, so it never skips
    return (not self._remote_active) and self._local.model.can_prepare_only

  @property
  def model_id(self) -> str:
    return self._profile.sha256 if self._remote_active else self._local.model.model_id

  @property
  def policy_generation(self) -> str:
    return self._profile.generation if self._remote_active else self._local.model.policy_generation

  @property
  def mlsim(self) -> bool:
    return self._profile.mlsim if self._remote_active else self._local.model.mlsim

  @property
  def is_v9(self) -> bool:
    return self._profile.is_v9 if self._remote_active else self._local.model.is_v9

  @property
  def is_v14(self) -> bool:
    return self._profile.is_v14 if self._remote_active else self._local.model.is_v14

  @property
  def is_v15(self) -> bool:
    return self._profile.is_v15 if self._remote_active else self._local.model.is_v15

  @property
  def is_v16(self) -> bool:
    return self._profile.is_v16 if self._remote_active else self._local.model.is_v16

  @property
  def handovers(self) -> int:
    return self._joining.handovers

  @property
  def settling(self) -> bool:
    return self._clock() < self._settle_until

  @property
  def locked_out(self) -> bool:
    return self._locked_out

  # -- the per-frame hand-off -------------------------------------------------------

  def set_control(self, in_control: bool, frame_drop_ratio: float, blinker_on: bool = False) -> None:
    """Before every run(): is anything in control, and how many camera frames has modeld dropped.

    The large model swaps in only while nothing is in control, and not while a blinker or lane change is active (the
    host's desire history cannot be flushed on a blinker cancel, so a swap starts from empty history and never in the
    middle of a maneuver). After MAX_HANDBACKS handbacks the gate stays shut for the drive."""
    self._in_control = bool(in_control)
    self._blinker_on = bool(blinker_on)
    self._joining.in_control = self._in_control or self._blinker_on or self._locked_out
    self._joining.frame_drop_ratio = float(frame_drop_ratio)

  def run(self, bufs, transforms, inputs, prepare_only: bool, after_output_sync=None, shared_warp=None, *,
          blinker_on: bool = False):
    if shared_warp is not None:
      raise RuntimeError("a shared camera warp is a Chestnut Model Laboratory feature; Jetlink does not take one")
    if not self._local.buffers_intact():
      raise RuntimeError("the local model's queues changed after Jetlink captured its reset")

    frame = {'img': bufs[self.road_key], 'big_img': bufs[self.wide_key]}
    tfm = {'img': transforms[self.road_key], 'big_img': transforms[self.wide_key]}
    if 'action_t' not in inputs:
      raise KeyError("action_t: the large model needs it in every frame (modeld puts it there for a JetlinkRunner)")

    was_remote = self._remote_active
    self._local.set_frame(FrameContext(prepare_only=bool(prepare_only) and not was_remote, blinker_on=bool(blinker_on)))
    held_before = self._held_count()
    output = self._joining.run(frame, tfm, inputs, after_output_sync)
    self._observe(was_remote, held_before)

    if output is not None and self._remote_active:
      try:
        self._check_remote_output(output)
      except RemoteOutputInvalid as e:
        # unusable large-model output must not be published or acted on: hand back and re-run this frame locally, as
        # Jetlink does for a model that raises
        self._log.error("jetlink: %s; handing back to the small model", e)
        self._joining.demote_invalid()
        self._local.set_frame(FrameContext(prepare_only=False, blinker_on=bool(blinker_on)))
        output = self._joining.run(frame, tfm, inputs, None)
        self._last_reason = f"invalid output: {e}"
        self._observe(True, held_before)
    return output

  # -- bookkeeping --------------------------------------------------------------------

  def _held_count(self) -> int:
    trips = getattr(self._joining, 'trips', None)
    return int(getattr(trips, 'held', 0)) if self._remote_active and trips is not None else 0

  def _observe(self, was_remote: bool, held_before: int) -> None:
    """Fold what the joining model did during run() into the runner's view."""
    now_remote = self._joining.big_model_state == 'running'
    if now_remote and (not was_remote or self._profile is None):
      # a swap this frame: bind the model's identity from the spec the server reported (it passed validate_spec to get
      # here, so this cannot raise for a model Jetlink built)
      self._profile = profiles.require_profile(self._joining.spec)
      self._held_total = 0
      self._held_run = 0
    self._remote_active = now_remote
    if was_remote and not now_remote:
      self._handbacks += 1
      if not self._last_reason:
        self._last_reason = 'link lost or fell behind'
      if self._handbacks >= MAX_HANDBACKS and not self._locked_out:
        self._locked_out = True
        self._log.error("jetlink: %d handbacks this drive, staying on the small model until the car restarts",
                        self._handbacks)
    if now_remote != was_remote:
      self._settle_until = self._clock() + SETTLE_SECONDS
      if now_remote:
        self._last_reason = ''
    if now_remote:
      total = self._held_count()
      self._held_run = self._held_run + 1 if (was_remote and total > held_before) else 0
      self._held_total = total
    else:
      self._held_run = 0

  def _check_remote_output(self, output: dict[str, np.ndarray]) -> None:
    for name, value in output.items():
      if not isinstance(value, np.ndarray) or value.dtype.kind != 'f':
        continue
      if not np.isfinite(value).all():
        raise RemoteOutputInvalid(f"non-finite output in {name}")
      if value.size and float(np.max(np.abs(value))) > MAX_ABS_REMOTE_OUTPUT:
        raise RemoteOutputInvalid(f"implausible magnitude in {name}")
    if 'plan' not in output or 'action' not in output:
      raise RemoteOutputInvalid("reply is missing the plan or action head")

  def _remote_model_name(self, state: str) -> str:
    """The external model that runs, or is ready to. Before the first swap the server's spec has not been bound, but
    phase 1 runs Jetlink's pinned default and nothing else (validate_spec), so that is the model that is ready."""
    if self._profile is not None and self._remote_active:
      return self._profile.name
    return DEFAULT_REMOTE.name if state in ('ready', 'running') else ''

  def _reason(self) -> str:
    """Why the large model is not driving, in a few words: the last demotion, else the last build that failed. Empty while it
    drives: a demotion's reason says nothing about a model that has since rejoined."""
    if self._remote_active:
      return ''
    return self._last_reason or getattr(self._joining, 'last_demotion', '') or getattr(self._joining, 'last_failure', '')

  def snapshot(self) -> Snapshot:
    handed = self._joining.handovers != self._handovers_seen
    self._handovers_seen = self._joining.handovers
    backend = JETLINK if self._remote_active else LOCAL
    changed, self._last_backend = backend != self._last_backend, backend
    state = self._joining.big_model_state
    if self._locked_out and state != 'running':
      state = 'unavailable'
    return Snapshot(
      backend=backend,
      accelerator=state,
      settling=self.settling,
      handovers=int(self._joining.handovers),
      held_frames=self._held_run,
      output_age_ms=self._held_run * FRAME_PERIOD_MS,
      remote_model=self._remote_model_name(state),
      handed_over=handed,
      backend_changed=changed,
      reason=self._reason())

  def close(self) -> None:
    close = getattr(self._joining, 'close', None)
    if close is not None:
      close()


def attach(adapter_attach, model, cam_w: int, cam_h: int, log) -> JetlinkRunner | None:
  """Join Jetlink to a loaded local model: the JetlinkRunner modeld should run, or None to keep the plain model.

  ``adapter_attach`` is ``jetlink_adapter.attach``. Jetlink returns the object it was given when it cannot build its
  joining model (and None when prepare() did not say yes); both mean "stay on the local model", and the second is silent
  because the offroad alert already says why."""
  local = LocalRunner(model)
  joined = adapter_attach(local, cam_w, cam_h)
  if joined is None:
    model.unpin_buffers()
    return None
  if joined is local:
    log.error("jetlink: the joining model could not be built, staying on the local model")
    model.unpin_buffers()
    return None
  return JetlinkRunner(joined, local, log)
