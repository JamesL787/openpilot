import ctypes as C
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from openpilot.starpilot.system.starpilot_auto import car_ui, headless_egl, supervisor
from openpilot.starpilot.system.starpilot_auto.render_profile import RenderSampler
from openpilot.starpilot.system.starpilot_auto.frame_source import (FLAG_ASYNC_READBACK, FLAG_NV12, FORMAT_NV12, FORMAT_RGBA, FrameConsumer,
                                                                  FrameProducer, FrameRequest, frame_bytes)


def test_capture_wait_matches_the_pacing_deadline():
  producer = FrameProducer()
  request = FrameRequest(4, 2, 0, 0, 100_000)
  producer._next_capture_ns = 1_100_000_000
  assert producer.capture_delay(request, 1_000_000_000) == pytest.approx(0.075)
  assert not producer.due(request, 1_074_999_999)
  assert producer.due(request, 1_075_000_000)
  assert producer.capture_delay(request, 1_500_000_000) == 0


def test_renderer_can_initialize_without_focus_and_resume_demand(tmp_path):
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  producer = FrameProducer(path)
  request = FrameRequest(4, 2, 0, 0, 33333)
  try:
    consumer.configure(request)
    assert car_ui.wait_for_request(producer) == request
    assert producer.pending_request() is None
    consumer.demand()
    assert producer.pending_request() == request
    consumer.release_demand()
    assert producer.pending_request() is None
    consumer.demand()
    assert producer.pending_request() == request
  finally:
    producer._close()
    consumer.close()


def test_screen_sleep_requires_focused_recently_sent_frames(tmp_path, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import frame_source
  clock = [100.0]
  monkeypatch.setattr(frame_source.time, "monotonic_ns", lambda: int(clock[0] * 1e9))
  path = str(tmp_path / "car_frames")
  consumer, reader = FrameConsumer(path), FrameProducer(path)
  request = FrameRequest(4, 2, 0, 0, 33333)
  try:
    consumer.configure(request)
    consumer.demand()
    assert not reader.recently_sent(clock[0]), "startup/demand alone is not proof of projection"
    assert reader.pending_request(clock[0]) == request
    reader.publish(request, bytes(32), 100_000_000_000)
    assert not reader.recently_sent(clock[0]), "rendered but unsent frames must not turn off the screen"
    consumer.mark_sent(100_000_000_000)
    assert reader.recently_sent(clock[0])
    consumer.release_demand()
    assert not reader.recently_sent(clock[0]), "focus loss wakes immediately"
    consumer.demand()
    clock[0] = 101.0
    consumer.demand()
    assert not reader.recently_sent(clock[0]), "fresh demand cannot hide a stalled renderer or encoder"
    consumer.mark_sent(102_000_000_000)
    assert not reader.recently_sent(clock[0]), "future timestamps fail awake"
    consumer.mark_sent(101_000_000_000)
    assert reader.recently_sent(clock[0])
    consumer.configure(request)
    consumer.demand()
    assert not reader.recently_sent(clock[0]), "a new session cannot inherit a previous heartbeat"
    consumer.mark_sent(101_000_000_000)
    consumer.close()
    assert not reader.recently_sent(clock[0]), "disconnect/fallback releases demand"
  finally:
    reader.close()
    if not consumer.mm.closed:
      consumer.close()


class FakeGL:
  """Enough GLES for FrameReadback: framebuffer reads into memory or a pixel-pack buffer."""

  def __init__(self, size: int):
    self.calls: list = []
    self.value = 17
    self.pack_bound = False
    self.pbo = (C.c_ubyte * size)()
    self.mapped = False
    self.fences = 0

  def __getattr__(self, name):
    raise AttributeError(name)

  def functions(self):
    gl = self

    class Function:
      def __init__(self, fn):
        self.fn = fn

      def __call__(self, *args):
        return self.fn(*args)

    def read_pixels(x, y, width, height, format_, type_, pointer):
      assert (x, y, format_, type_) == (0, 0, 0x1908, 0x1401)
      offset = pointer.value or 0
      address = C.addressof(gl.pbo) + offset if gl.pack_bound else offset
      C.memset(address, gl.value, width * height * 4)
      gl.value += 1  # each region gets its own byte value

    def bind_buffer(target, buffer):
      assert target == 0x88EB
      gl.pack_bound = bool(buffer.value if hasattr(buffer, "value") else buffer)

    def fence_sync(*args):
      gl.fences += 1
      return 1234

    def map_range(target, offset, length, access):
      assert gl.pack_bound and access == 0x0001
      gl.mapped = True
      return C.addressof(gl.pbo)

    def unmap(target):
      gl.mapped = False
      return 1

    table = {
      "glBindFramebuffer": lambda *args: gl.calls.append(args), "glReadPixels": read_pixels,
      "glGenBuffers": lambda count, pointer: setattr(pointer._obj, "value", 9), "glDeleteBuffers": lambda *args: None,
      "glBindBuffer": bind_buffer, "glBufferData": lambda *args: None, "glMapBufferRange": map_range, "glUnmapBuffer": unmap,
      "glFenceSync": fence_sync, "glClientWaitSync": lambda *args: 0x911A, "glDeleteSync": lambda *args: None,
      "glFlush": lambda: None, "glFinish": lambda: None,
    }
    return SimpleNamespace(**{name: Function(fn) for name, fn in table.items()})


def test_sync_readback_reuses_storage_and_published_frames_are_independent(monkeypatch, tmp_path):
  fake = FakeGL(32)
  gl = fake.functions()
  monkeypatch.setattr(headless_egl.C, "CDLL", lambda _: gl)
  readback = headless_egl.FrameReadback(32)
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  producer = FrameProducer(path)
  request = FrameRequest(4, 2, 0, 0, 33333)
  try:
    consumer.configure(request)
    consumer.demand()
    assert producer.pending_request() == request
    readback.start([(42, 4, 2, 0)])
    first = readback.finish()
    producer.publish(request, first, 1)
    readback.release()
    frame = consumer.latest()
    readback.start([(42, 4, 2, 0)])
    assert readback.finish() is first and bytes(first) == bytes([18]) * 32
    readback.release()
    assert frame.data == bytes([17]) * 32
    assert fake.calls == [(0x8D40, 42), (0x8D40, 0)] * 2

    def fail_read(*args):
      raise RuntimeError("read failed")

    gl.glReadPixels.fn = fail_read
    with pytest.raises(RuntimeError, match="read failed"):
      readback.start([(42, 4, 2, 0)])
    assert fake.calls[-1] == (0x8D40, 0) and not readback.pending
  finally:
    producer._close()
    consumer.close()


def test_async_readback_packs_nv12_regions_behind_a_fence(monkeypatch, tmp_path):
  width, height = 8, 4
  size = frame_bytes(width, height, FORMAT_NV12)
  fake = FakeGL(size)
  monkeypatch.setattr(headless_egl.C, "CDLL", lambda _: fake.functions())
  readback = headless_egl.FrameReadback(size, asynchronous=True)
  regions = [(1, width // 4, height, 0), (2, width // 4, height // 2, width * height)]
  readback.start(regions)
  assert readback.pending and fake.fences == 1 and not fake.pack_bound
  with pytest.raises(RuntimeError):
    readback.start(regions)  # one frame in flight at a time
  pixels = readback.finish()
  assert bytes(pixels) == bytes([17]) * (width * height) + bytes([18]) * (width * height // 2)
  assert fake.mapped
  readback.release()
  assert not fake.mapped and not fake.pack_bound and not readback.pending
  with pytest.raises(ValueError):
    readback.start([(1, width, height, 0)])  # RGBA-sized region does not fit an NV12 frame


def test_nv12_frames_round_trip_with_their_format(tmp_path):
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  producer = FrameProducer(path)
  request = FrameRequest(8, 4, 0, 0, 33333, FLAG_NV12 | FLAG_ASYNC_READBACK)
  try:
    consumer.configure(request)
    consumer.demand()
    assert producer.pending_request() == request and producer.pending_request().flags == FLAG_NV12 | FLAG_ASYNC_READBACK
    producer.advance(request, 5_000)
    scheduled = producer._next_capture_ns
    producer.publish(request, bytes(range(48)), 5_000, FORMAT_NV12, advance=False)
    assert producer._next_capture_ns == scheduled  # capture time already set the schedule
    frame = consumer.latest()
    assert frame.pixel_format == FORMAT_NV12 and frame.data == bytes(range(48)) and frame.captured_ns == 5_000
    producer.publish(request, bytes(128), 6_000)  # an RGBA-only producer (mirroring) still works
    frame = consumer.latest()
    assert frame.pixel_format == FORMAT_RGBA and len(frame.data) == 128
  finally:
    producer._close()
    consumer.close()


def test_render_stats_report_sections_and_the_former_draw_total():
  stats = car_ui.RenderStats(0.0)
  for _ in range(4):
    for key, seconds in (("layout_ms", 0.020), ("map_draw_ms", 0.004), ("compose_ms", 0.002), ("cpu_ms", 0.015),
                         ("frame_ms", 0.030)):
      stats.add(key, seconds)
    report = stats.frame_done(5.0)
  assert report is None
  report = stats.frame_done(car_ui.STATS_INTERVAL)
  assert report["event"] == "render_stats" and report["fps"] == 0.5
  assert report["layout_ms"] == 16.0 and report["draw_ms"] == 20.8 and report["cpu_ms"] == 12.0
  assert stats.frames == 0 and stats.started == car_ui.STATS_INTERVAL


def test_render_stats_average_sampled_keys_over_their_samples():
  stats = car_ui.RenderStats(0.0)
  for index in range(30):
    stats.add("frame_ms", 0.020)
    if index % 10 == 0:
      stats.add("gpu_ms", 0.004, sampled=True)
    stats.frame_done(1.0)
  report = stats.frame_done(car_ui.STATS_INTERVAL)
  assert report["frame_ms"] == pytest.approx(19.35, abs=0.01) and report["gpu_ms"] == 4.0


def hot_render_function(sampler):
  sampler.sample(sys._getframe())


def test_sampler_reports_parameter_keys_without_values_or_wrapping(tmp_path):
  sampler = RenderSampler(tmp_path / "profile.txt")
  sampler.rendering = True
  # Code objects are hashable; use a small stand-in with attributes for the sampler.
  class Code:
    co_name = "get"
    co_filename = "/data/openpilot/common/params.py"
    co_firstlineno = 220

  frame = SimpleNamespace(f_code=Code(), f_lineno=222, f_locals={"key": "BorderWidth", "value": "private-value"}, f_back=None)
  sampler.sample(frame)
  report = sampler.report()
  assert "100.0%  get(BorderWidth)" in report
  assert "not read counts" in report and "private-value" not in report
  sampler.flush()
  assert not sampler.param_samples


def test_render_sampler_counts_render_stacks_and_idle(tmp_path):
  clock = [0.0]
  sampler = RenderSampler(tmp_path / "render_profile.txt", clock=lambda: clock[0])
  sampler.sample(sys._getframe())  # renderer idle
  sampler.rendering, sampler.onroad = True, True
  for _ in range(3):
    hot_render_function(sampler)
  sampler.summary = {"event": "render_stats", "fps": 19.5, "layout_ms": 31.0}
  clock[0] = 60.0
  text = sampler.report()
  assert "onroad (100% onroad), rendering 75% of 4 samples" in text
  assert "render_stats fps=19.5 layout_ms=31.0" in text
  inclusive = text.split("-- on the stack")[1].split("-- innermost function")[0]
  assert "hot_render_function" not in inclusive  # on every sample: not worth a line
  innermost = text.split("-- innermost function")[1].split("-- innermost line")[0]
  assert "100.0%  test_stream_efficiency.py" in innermost and "hot_render_function" in innermost
  sampler.flush()
  assert (tmp_path / "render_profile.txt").read_text() == text
  assert sampler.samples == 0 and sampler.report() == ""


def test_render_sampler_file_rotates_at_its_size_cap(tmp_path):
  path = tmp_path / "render_profile.txt"
  sampler = RenderSampler(path, max_bytes=300)
  for index in range(5):
    sampler._write(f"window {index} " + "x" * 100 + "\n")
  assert path.read_text().startswith("window 4")
  assert (tmp_path / "render_profile.1.txt").read_text().startswith("window 2")
  assert path.stat().st_size <= 300 and not (tmp_path / "render_profile.2.txt").exists()


def test_render_sampler_thread_samples_the_render_thread(tmp_path):
  sampler = RenderSampler(tmp_path / "render_profile.txt", interval=0.001, window=3600)
  sampler.rendering = True
  sampler.start()
  deadline = time.monotonic() + 2.0
  while sampler.samples < 5 and time.monotonic() < deadline:
    sum(range(10_000))
  sampler.close()
  text = (tmp_path / "render_profile.txt").read_text()
  assert "test_render_sampler_thread_samples_the_render_thread" in text


@pytest.mark.parametrize("scenario", ["ready", "idle", "blocked", "unfocused", "input_burst"])
@pytest.mark.parametrize("source_view", ["car", "mirror", "synthetic"])
def test_stream_waits_only_when_needed_and_preserves_flow_control(monkeypatch, scenario, source_view):
  clock = [100.0]
  monkeypatch.setattr(supervisor.time, "monotonic", lambda: clock[0])
  monkeypatch.setattr(supervisor.time, "sleep", lambda _: pytest.fail("stream must wait on input, not sleep"))
  stop = threading.Event()
  waits, sent, demands, touches = [], [], [], []
  pending_input = [40 if scenario == "input_burst" else 0]

  class Session:
    focused = scenario != "unfocused"
    needs_keyframe = True
    touch_events = []
    blocked = scenario == "blocked"

    def can_send(self):
      return self.focused and not self.blocked

    def pump(self, timeout):
      waits.append(timeout)
      clock[0] += timeout
      if pending_input[0]:
        pending_input[0] -= 1
        self.touch_events.append(pending_input[0])
        return True
      if len(waits) == 2:
        self.focused = True
        self.blocked = False
      return False

    def check_progress(self):
      pass

    def send_frame(self, data, timestamp, *, keyframe):
      assert self.can_send()
      sent.append(clock[0])
      self.needs_keyframe = False
      if len(sent) == 3:
        stop.set()

    def stats(self):
      return {}

  session = Session()

  class Source:
    frames = 0
    label = source_view
    view = source_view
    source = SimpleNamespace(mark_sent=lambda captured_ns: sent_headers.append(captured_ns))

    def demand(self, seconds):
      demands.append(True)

    def release_demand(self):
      demands.append(False)

    def latest(self):
      if scenario == "idle" and len(waits) == 1:
        return None
      self.frames += 1
      return SimpleNamespace(data=b"rgba", captured_ns=int(clock[0] * 1e9), pixel_format=FORMAT_RGBA)

    def send_touches(self, events):
      touches.extend(events)

    def check(self, now, *, focused):
      pass

  def encode(data, *, keyframe):
    clock[0] += 0.035
    return b"h264", keyframe

  sup = supervisor.Supervisor.__new__(supervisor.Supervisor)
  sent_headers = []
  sup._stop = stop
  sup._status = {"state": "streaming"}
  sup._stage = lambda _: None
  sup._set = lambda **values: sup._status.update(values)
  sup.log = lambda *args, **kwargs: None
  sup._stream(session, SimpleNamespace(encode_rgba=encode, last_encode_ms=35), Source(),
              SimpleNamespace(still_connected=lambda: True), 1 / 30)
  assert len(sent) == 3
  assert len(sent_headers) == (3 if source_view == "car" else 0)
  assert sent[1] - sent[0] == pytest.approx(0.035)
  assert sent[2] - sent[1] == pytest.approx(0.035)
  if scenario == "ready":
    assert waits == [0.0] * 3
  elif scenario == "idle":
    assert waits[1] == pytest.approx(1 / 120)
  elif scenario in ("blocked", "unfocused"):
    assert waits[:2] == [0.05, 0.05]
    assert demands[0] is (scenario == "blocked")
    assert demands[-1]
  elif scenario == "input_burst":
    assert len(touches) == 40
    assert len(waits) == 41  # video still progresses after each bounded batch


def test_fast_struct_constructors_match_pyray_and_skip_pointer_structs(monkeypatch):
  import pyray as rl
  originals = {name: getattr(rl, name) for name in rl.ffi.list_types()[0] if hasattr(rl, name)}
  for name, original in originals.items():
    monkeypatch.setattr(rl, name, original)  # every constructor is restored after the test
  patched = car_ui.use_fast_struct_constructors(rl)
  assert {"Vector2", "Rectangle", "Color", "Camera2D"} <= set(patched) <= set(car_ui.FAST_STRUCTS)
  assert rl.Font is originals["Font"] and rl.Image is originals["Image"]
  for name, args in (("Vector2", (1.5, -2.0)), ("Rectangle", (1, 2, 3, 4)), ("Color", (1, 2, 3, 255)),
                     ("Camera2D", ((1.0, 2.0), (3.0, 4.0), 5.0, 1.0))):
    fast, slow = getattr(rl, name)(*args), originals[name](*args)
    assert bytes(rl.ffi.buffer(rl.ffi.addressof(fast))) == bytes(rl.ffi.buffer(rl.ffi.addressof(slow)))
  assert car_ui.use_fast_struct_constructors(rl) == []  # already fast: nothing left to replace


class FlakyEncoder:
  """Fails the encodes listed in ``failures`` (by call number) like a stalled VPU; ``reopen`` recovers."""
  backend = "qcom-v4l2"

  def __init__(self, failures, *, can_reopen=True, reopen_fails=False):
    self.failures, self.calls, self.reopens, self.last_encode_ms = set(failures), 0, 0, 12.0
    self.fresh, self.keyframes = True, []
    self.reopen_fails = reopen_fails
    if not can_reopen:
      self.reopen = None

  def encode_rgba(self, data, *, keyframe):
    self.calls += 1
    if self.calls in self.failures:
      raise RuntimeError("Hardware encode exceeded 500 ms (input done, frame pending; copy 1.0 ms, queue 0.1 ms, wait 499.0 ms)")
    keyframe, self.fresh = keyframe or self.fresh, False
    self.keyframes.append(keyframe)
    return b"h264", keyframe

  def reopen(self):
    if self.reopen_fails:
      raise RuntimeError("encoder control failed")
    self.reopens += 1
    self.fresh = True  # a fresh driver session starts with an IDR


def stream_with(encoder, frames_to_send, monkeypatch):
  clock = [100.0]
  monkeypatch.setattr(supervisor.time, "monotonic", lambda: clock[0])
  stop, sent, events = threading.Event(), [], []

  class Session:
    focused, needs_keyframe, touch_events = True, True, []

    def can_send(self):
      return True

    def pump(self, timeout):
      clock[0] += 0.033
      return False

    def check_progress(self):
      pass

    def send_frame(self, data, timestamp, *, keyframe):
      sent.append(keyframe)
      self.needs_keyframe = False
      if len(sent) == frames_to_send:
        stop.set()

    def stats(self):
      return {}

  class Source:
    frames, label, view = 0, "mirror", "mirror"

    def demand(self, seconds):
      pass

    def latest(self):
      return SimpleNamespace(data=b"rgba", captured_ns=int(clock[0] * 1e9), pixel_format=FORMAT_RGBA)

    def check(self, now, *, focused):
      pass

  sup = supervisor.Supervisor.__new__(supervisor.Supervisor)
  sup._stop = stop
  sup._status = {"state": "streaming"}
  sup._stage = lambda _: None
  sup._set = lambda **values: sup._status.update(values)
  sup.log = lambda name, **values: events.append((name, values))
  sup._stream(Session(), encoder, Source(), SimpleNamespace(still_connected=lambda: True), 1 / 30)
  return sent, events, sup._status.get("stats")


def test_a_stalled_hardware_encode_reopens_the_encoder_instead_of_ending_the_session(monkeypatch):
  encoder = FlakyEncoder({3})
  sent, events, _ = stream_with(encoder, 5, monkeypatch)
  assert encoder.reopens == 1
  assert sent == [True, False, True, False, False], "the frame after a reopen is an IDR the car can decode alone"
  recovered = [values for name, values in events if name == "encoder_recovered"]
  assert len(recovered) == 1 and "input done, frame pending" in recovered[0]["error"]
  assert recovered[0]["recent_recoveries"] == 1


def test_repeated_encoder_failures_still_end_the_attempt(monkeypatch):
  encoder = FlakyEncoder(range(2, 100))
  with pytest.raises(RuntimeError, match="exceeded 500 ms"):
    stream_with(encoder, 50, monkeypatch)
  assert encoder.reopens == supervisor.ENCODER_RECOVERIES


def test_encoder_recoveries_spread_over_time_do_not_add_up(monkeypatch):
  # One stall every ~4 s (120 frames at 30 fps) never puts 3 in one 10 s window.
  encoder = FlakyEncoder(range(120, 1200, 120))
  sent, events, _ = stream_with(encoder, 1000, monkeypatch)
  assert encoder.reopens == 8
  assert not [name for name, _ in events if name == "encoder_failed"]


def test_software_encoder_errors_are_not_retried(monkeypatch):
  encoder = FlakyEncoder({2}, can_reopen=False)
  with pytest.raises(RuntimeError):
    stream_with(encoder, 5, monkeypatch)


def test_a_failed_reopen_ends_the_attempt_with_the_original_error(monkeypatch):
  encoder = FlakyEncoder({2}, reopen_fails=True)
  with pytest.raises(RuntimeError, match="exceeded 500 ms"):
    stream_with(encoder, 5, monkeypatch)


def test_session_logs_are_pruned_by_number_not_by_the_clock(tmp_path, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import identity as identity_store
  for name in ("session-20260924-133852.jsonl", "session-20260925-141805.jsonl"):
    (tmp_path / name).write_text("{}\n")
  monkeypatch.setattr(supervisor, "MAX_LOG_FILES", 3)
  stamps = iter(["20260728-080512", "20260926-150936", "20260728-080530"])  # the clock is unsynced right after boot
  monkeypatch.setattr(identity_store, "timestamp", lambda: next(stamps))
  for _ in range(3):
    log = supervisor.EventLog(tmp_path)
    log.open()
    log("session_start")
    log.close()
  assert sorted(p.name for p in tmp_path.glob("session-*.jsonl")) == [
    "session-000001-20260728-080512.jsonl", "session-000002-20260926-150936.jsonl", "session-000003-20260728-080530.jsonl"]
