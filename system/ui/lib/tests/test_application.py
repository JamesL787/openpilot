import os
import math
import queue
from importlib.resources import as_file
from types import SimpleNamespace

import pytest

from openpilot.system.ui.lib import application


def test_raylib_target_fps_uses_mici_display_refresh(monkeypatch):
  monkeypatch.setattr(application, "OFFSCREEN", False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "mici")
  monkeypatch.setattr(application, "PC", False)

  assert application._raylib_target_fps(60) == 0


def test_raylib_target_fps_limits_mici_desktop_preview(monkeypatch):
  monkeypatch.setattr(application, "OFFSCREEN", False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "mici")
  monkeypatch.setattr(application, "PC", True)

  assert application._raylib_target_fps(60) == 60


def test_raylib_target_fps_limits_other_devices(monkeypatch):
  monkeypatch.setattr(application, "OFFSCREEN", False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "tici")

  assert application._raylib_target_fps(60) == 60


def test_raylib_target_fps_disables_limit_for_offscreen(monkeypatch):
  monkeypatch.setattr(application, "OFFSCREEN", True)
  monkeypatch.setattr(application, "DEVICE_TYPE", "tici")

  assert application._raylib_target_fps(60) == 0


@pytest.mark.parametrize("covered", [False, True])
def test_render_preserves_visible_layers_and_measures_complete_frame(monkeypatch, covered):
  monkeypatch.setattr(application, "PC", False)
  monkeypatch.setattr(application, "RECORD", False)
  monkeypatch.setattr(application.GuiApplication, "_set_log_callback", lambda _: None)
  app = application.GuiApplication(536, 240)
  app._scale = 1.0
  app._nav_stack_widgets_to_render = 2
  app._mouse = SimpleNamespace(get_events=list)
  app._burn_in_shift = lambda: (0, 0)
  app._monitor_fps = lambda: None
  app._show_fps = app._show_touches = False
  app._grid_size = app._profile_render_frames = 0

  clock = SimpleNamespace(wall=10.0, cpu=1.0)
  monkeypatch.setattr(application.time, "monotonic", lambda: clock.wall)
  monkeypatch.setattr(application.time, "thread_time", lambda: clock.cpu)
  monkeypatch.setattr(application.rl, "window_should_close", lambda: False)
  monkeypatch.setattr(application.rl, "begin_drawing", lambda: None)
  monkeypatch.setattr(application.rl, "clear_background", lambda _: None)
  rendered = []

  def draw(name):
    rendered.append(name)
    clock.wall += 0.004
    clock.cpu += 0.003

  def present():
    clock.wall += 0.011
    clock.cpu += 0.001

  def populate_cache():
    clock.wall += 0.003
    clock.cpu += 0.002

  monkeypatch.setattr(application.rl, "end_drawing", present)
  app._populate_render_texture_cache = populate_cache
  app._nav_stack = [
    SimpleNamespace(render=lambda _: draw("road")),
    SimpleNamespace(covers_background=lambda _: covered, render=lambda _: draw("panel")),
  ]
  frames = app.render()
  assert next(frames)
  clock.wall += 0.002
  clock.cpu += 0.001
  app.request_close()
  with pytest.raises(StopIteration):
    next(frames)

  assert rendered == (["panel"] if covered else ["road", "panel"])
  draws = len(rendered)
  assert app.frame_timing == pytest.approx(application.FrameTiming(
    draws * 4 + 16, draws * 3 + 4, draws * 4, 2, 11,
  ))


def test_burn_in_shift_transitions_between_positions(monkeypatch):
  app = object.__new__(application.GuiApplication)
  app._burn_in_start_time = 100.0

  monkeypatch.setattr(application, "BURN_IN_PREVENTION", True)
  monkeypatch.setattr(application, "BURN_IN_SHIFT_INTERVAL", 10.0)
  monkeypatch.setattr(application, "BURN_IN_SHIFT_PIXELS", 2)
  monkeypatch.setattr(application, "BURN_IN_SHIFT_TRANSITION_SECONDS", 2.0)

  assert app._burn_in_shift(108.0) == (0.0, 0.0)
  midpoint = app._burn_in_shift(109.0)
  assert midpoint == (-1.0, 0.0)
  assert app._burn_in_shift(110.0) == (-2.0, 0.0)


def test_brand_font_assets_include_wordmark_glyphs():
  with as_file(application.FONT_DIR.joinpath("como-heavy.fnt")) as font_path:
    lines = font_path.read_text().splitlines()

  glyphs = {}
  for line in lines:
    if not line.startswith("char id="):
      continue
    fields = dict(field.split("=", 1) for field in line.split() if "=" in field)
    glyphs[int(fields["id"])] = (int(fields["width"]), int(fields["height"]))

  for char in set("StarPilot"):
    assert glyphs[ord(char)][0] > 0
    assert glyphs[ord(char)][1] > 0


def test_brand_font_is_not_replaced_by_language_fallback(monkeypatch):
  brand_font = SimpleNamespace(texture=SimpleNamespace(id=1))
  unifont = SimpleNamespace(texture=SimpleNamespace(id=2))
  monkeypatch.setattr(application.multilang, "requires_unifont", lambda: True)
  monkeypatch.setattr(application.gui_app, "font", lambda weight: {
    application.FontWeight.BRAND: brand_font,
    application.FontWeight.UNIFONT: unifont,
  }[weight])

  assert application.font_fallback(brand_font) is brand_font
  assert application.font_fallback(SimpleNamespace(texture=SimpleNamespace(id=3))) is unifont


def test_scissor_mode_shifted_for_direct_framebuffer(monkeypatch):
  orig_scissor_calls = []
  monkeypatch.setattr(application.rl, "begin_scissor_mode", lambda x, y, w, h: orig_scissor_calls.append((x, y, w, h)))
  if hasattr(application.rl, "_orig_begin_scissor_mode"):
    delattr(application.rl, "_orig_begin_scissor_mode")

  app = object.__new__(application.GuiApplication)
  app._scale = 1.0
  app._pixel_scale_x = 1.0
  app._pixel_scale_y = 1.0
  app._render_texture = None
  app._burn_in_shift = lambda: (2.0, -1.0)

  app._patch_scissor_mode()
  application.rl.begin_scissor_mode(100, 200, 300, 400)

  assert orig_scissor_calls[-1] == (102, 199, 300, 400)

  # Inside an offscreen render texture, scissor must remain unshifted
  app._render_texture = SimpleNamespace()
  application.rl.begin_scissor_mode(100, 200, 300, 400)
  assert orig_scissor_calls[-1] == (100, 200, 300, 400)

  # Clean up patched function
  if hasattr(application.rl, "_orig_begin_scissor_mode"):
    application.rl.begin_scissor_mode = application.rl._orig_begin_scissor_mode


def test_needs_render_texture_bypassed_on_tici_by_default(monkeypatch):
  monkeypatch.setattr(application, "PC", False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "tici")
  monkeypatch.setattr(application, "BURN_IN_MODE", False)
  monkeypatch.setattr(application, "RECORD", False)
  monkeypatch.setattr(application, "MICI_FORCE_RENDER_TEXTURE", False)
  monkeypatch.setattr(application, "TICI_FORCE_RENDER_TEXTURE", False)
  monkeypatch.setattr(application, "WHITE_LUMINANCE_CAP", 1.0)

  app = object.__new__(application.GuiApplication)
  app._scale = 1.0

  # On TICI by default, render texture MUST be False (saving 21.8 ms)
  assert app._needs_render_texture() is False

  # Explicit override forces render texture
  monkeypatch.setattr(application, "TICI_FORCE_RENDER_TEXTURE", True)
  assert app._needs_render_texture() is True

  # Recording mode forces render texture
  monkeypatch.setattr(application, "TICI_FORCE_RENDER_TEXTURE", False)
  monkeypatch.setattr(application, "RECORD", True)
  assert app._needs_render_texture() is True


# ------------------------------------------------------------- ui streamer hooks


def _bare_app() -> application.GuiApplication:
  app = object.__new__(application.GuiApplication)
  app._ui_stream = None
  app._ui_stream_pending = False
  app._ui_stream_owns_texture = False
  app._ui_stream_texture = None
  app._ui_stream_scale_failed = False
  app._ui_stream_error = ""
  app._stream_paused = False
  app._progress_hook = None
  app._ui_stream_control_allowed = False
  app._ui_stream_control_reason = "not enabled by this app"
  app._remote_down = False
  app._remote_pos = application.MousePos(0, 0)
  app._physical_slots_down = set()
  app._last_physical_event_t = -math.inf
  return app


class _FakeStream:
  """Minimal stand-in for ui_stream.UiStream."""

  def __init__(self, config=None, serve_error: Exception | None = None):
    self.config = config
    self.port = 8091
    self.serve_error = serve_error
    self.served = 0
    self.stopped = 0

  def serve(self):
    self.served += 1
    if self.serve_error is not None:
      raise self.serve_error

  def stop(self):
    self.stopped += 1


def test_request_ui_stream_only_marks_pending():
  # request_ui_stream is called from the UI loop thread, so it must not bind,
  # allocate or touch GL -- only flag the render thread to do that.
  app = _bare_app()
  app.request_ui_stream()
  assert app._ui_stream_pending is True
  assert app._ui_stream is None


def test_request_ui_stream_ignored_while_running():
  app = _bare_app()
  app._ui_stream = SimpleNamespace()
  app.request_ui_stream()
  assert app._ui_stream_pending is False


def test_start_pending_ui_stream_clears_flag_when_disabled(monkeypatch):
  # STREAM=0 kills the feature: the request is consumed, nothing starts, and
  # the flag does not survive to retry every frame.
  monkeypatch.setenv("STREAM", "0")
  app = _bare_app()
  app._ui_stream_pending = True
  app._start_pending_ui_stream()
  assert app._ui_stream_pending is False
  assert app._ui_stream is None


def test_ui_stream_state_reports_off_starting_running_and_error():
  # Galaxy loads the viewer page -- which the listener itself serves -- only
  # once this says "running", so the four states must be distinguishable.
  app = _bare_app()
  assert app.ui_stream_state() == ("off", "", 0)

  app.request_ui_stream()
  assert app.ui_stream_state() == ("starting", "", 0)

  app._ui_stream = _FakeStream()
  assert app.ui_stream_state() == ("running", "", 8091)

  app._ui_stream = None
  app._ui_stream_pending = False
  app._ui_stream_error = "cannot bind 0.0.0.0:8091: in use"
  state, detail, port = app.ui_stream_state()
  assert state == "error" and "in use" in detail and port == 0


def test_request_ui_stream_clears_a_previous_failure():
  app = _bare_app()
  app._ui_stream_error = "cannot bind"
  app.request_ui_stream()
  assert app.ui_stream_state()[0] == "starting"


def test_start_pending_ui_stream_contains_gl_exceptions(monkeypatch):
  # A GL failure must disable streaming, not escape into the render loop.
  monkeypatch.delenv("STREAM", raising=False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "tici")
  app = _bare_app()
  app._render_texture = None
  app._render_texture_width = 64
  app._render_texture_height = 32
  app._ui_stream_pending = True

  def explode(width, height):
    raise RuntimeError("gl exploded")

  monkeypatch.setattr(application.rl, "load_render_texture", explode)

  app._start_pending_ui_stream()  # must not raise
  assert app._ui_stream is None
  assert app._render_texture is None
  state, detail, _ = app.ui_stream_state()
  assert state == "error" and "gl exploded" in detail


def test_start_pending_ui_stream_rolls_back_a_dead_texture(monkeypatch):
  monkeypatch.delenv("STREAM", raising=False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "tici")
  app = _bare_app()
  app._render_texture = None
  app._render_texture_width = 64
  app._render_texture_height = 32
  app._ui_stream_pending = True

  dead = SimpleNamespace(texture=SimpleNamespace(id=0))
  unloaded = []
  monkeypatch.setattr(application.rl, "load_render_texture", lambda w, h: dead)
  monkeypatch.setattr(application.rl, "unload_render_texture", lambda rt: unloaded.append(rt))

  app._start_pending_ui_stream()
  assert unloaded == [dead]
  assert app._ui_stream is None and app._render_texture is None
  assert app.ui_stream_state()[0] == "error"


def test_start_pending_ui_stream_rolls_back_a_failed_thread_start(monkeypatch):
  # serve() starts threads. If that fails the listener is already bound, so the
  # rollback has to close it instead of leaving a half-built streamer behind.
  monkeypatch.delenv("STREAM", raising=False)
  from openpilot.system.ui.lib import ui_stream as ui_stream_module

  created: list[_FakeStream] = []

  def factory(config):
    stream = _FakeStream(config, serve_error=RuntimeError("no threads"))
    created.append(stream)
    return stream

  monkeypatch.setattr(ui_stream_module, "UiStream", factory)
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width = 64
  app._render_texture_height = 32
  app._ui_stream_pending = True

  app._start_pending_ui_stream()
  assert created and created[0].stopped == 1
  assert app._ui_stream is None
  state, detail, _ = app.ui_stream_state()
  assert state == "error" and "no threads" in detail


def test_read_stream_texture_copies_rgba(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._ui_stream = SimpleNamespace(fail_capture=lambda reason: None)

  raw = application.rl.ffi.new("unsigned char[]", 16)
  for i in range(16):
    raw[i] = i
  image = SimpleNamespace(data=raw, width=2, height=2,
                          format=application.rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
  unloaded = []
  monkeypatch.setattr(application.rl, "load_image_from_texture", lambda texture: image)
  monkeypatch.setattr(application.rl, "unload_image", lambda img: unloaded.append(img))

  out = bytearray(16)
  assert app._read_stream_texture(out) is True
  assert out == bytearray(range(16))
  assert unloaded == [image]


def test_read_stream_texture_rejects_non_rgba_and_disables(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  failures = []
  app._ui_stream = SimpleNamespace(fail_capture=lambda reason: failures.append(reason))

  raw = application.rl.ffi.new("unsigned char[]", 16)
  image = SimpleNamespace(data=raw, width=2, height=2,
                          format=application.rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8)
  monkeypatch.setattr(application.rl, "load_image_from_texture", lambda texture: image)
  monkeypatch.setattr(application.rl, "unload_image", lambda img: None)

  assert app._read_stream_texture(bytearray(16)) is False
  assert failures and "format" in failures[0]


def test_read_stream_texture_dimension_mismatch_disables(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  failures = []
  app._ui_stream = SimpleNamespace(fail_capture=lambda reason: failures.append(reason))

  raw = application.rl.ffi.new("unsigned char[]", 64)
  image = SimpleNamespace(data=raw, width=4, height=4,
                          format=application.rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
  monkeypatch.setattr(application.rl, "load_image_from_texture", lambda texture: image)
  monkeypatch.setattr(application.rl, "unload_image", lambda img: None)

  # Buffer sized for 2x2 (16 bytes) but the readback is 4x4 (64 bytes).
  assert app._read_stream_texture(bytearray(16)) is False
  assert failures and "mismatch" in failures[0]


def test_read_stream_texture_unloads_on_failure(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._ui_stream = SimpleNamespace(fail_capture=lambda reason: None)
  unloaded = []
  monkeypatch.setattr(application.rl, "load_image_from_texture",
                      lambda texture: (_ for _ in ()).throw(RuntimeError("gl")))
  monkeypatch.setattr(application.rl, "unload_image", lambda img: unloaded.append(img))

  try:
    app._read_stream_texture(bytearray(16))
  except RuntimeError:
    pass
  assert unloaded == []


def test_capture_stream_frame_delegates_with_texture_dims():
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width = 100
  app._render_texture_height = 50
  calls = []
  app._ui_stream = SimpleNamespace(self_stop_due=lambda: False,
                                   output_size=lambda w, h: (w, h),
                                   maybe_capture=lambda now, w, h, read, **kw: calls.append((w, h, read)))

  app._capture_stream_frame()
  assert calls and calls[0][0] == 100 and calls[0][1] == 50


def test_capture_stream_frame_downscales_on_gpu(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width = 2160
  app._render_texture_height = 1080
  scaled = SimpleNamespace(texture=SimpleNamespace(id=2, width=1280, height=640))
  monkeypatch.setattr(application.rl, "load_render_texture", lambda w, h: scaled)
  calls = []
  app._ui_stream = SimpleNamespace(self_stop_due=lambda: False, output_size=lambda w, h: (1280, 640),
                                   maybe_capture=lambda now, w, h, read, **kw: calls.append((w, h, read, kw)))

  app._capture_stream_frame()
  assert app._ui_stream_texture is scaled
  w, h, read, kw = calls[0]
  assert (w, h) == (1280, 640)
  assert read == app._read_scaled_stream_texture
  assert kw == {"bottom_up": False, "source_size": (2160, 1080)}


def test_capture_stream_frame_falls_back_to_cpu_resize(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width = 2160
  app._render_texture_height = 1080
  allocations = []

  def dead(w, h):
    allocations.append((w, h))
    return SimpleNamespace(texture=SimpleNamespace(id=0))
  monkeypatch.setattr(application.rl, "load_render_texture", dead)
  monkeypatch.setattr(application.rl, "unload_render_texture", lambda rt: None)
  calls = []
  app._ui_stream = SimpleNamespace(self_stop_due=lambda: False, output_size=lambda w, h: (1280, 640),
                                   maybe_capture=lambda now, w, h, read, **kw: calls.append((w, h, read)))

  app._capture_stream_frame()
  app._capture_stream_frame()
  assert allocations == [(1280, 640)]  # one attempt, not one per frame
  assert all((w, h, read) == (2160, 1080, app._read_stream_texture) for w, h, read in calls)


def test_capture_stream_frame_noop_without_texture():
  app = _bare_app()
  app._render_texture = None
  app._render_texture_width = 100
  app._render_texture_height = 50
  calls = []
  app._ui_stream = SimpleNamespace(self_stop_due=lambda: False,
                                   output_size=lambda w, h: (w, h),
                                   maybe_capture=lambda now, w, h, read, **kw: calls.append(1))
  app._capture_stream_frame()
  assert calls == []


def test_service_ui_stream_stops_when_idle_without_capturing(monkeypatch):
  # The skipped-frame path: idle shutdown must run while the screen is off, and
  # there is no new frame to read back.
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width = 100
  app._render_texture_height = 50
  captures = []
  stops = []
  app._ui_stream = SimpleNamespace(self_stop_due=lambda: True,
                                   output_size=lambda w, h: (w, h),
                                   maybe_capture=lambda now, w, h, read, **kw: captures.append(1),
                                   stop=lambda: stops.append(1))

  app._service_ui_stream(capture=False)
  assert captures == [] and stops == [1]
  assert app._ui_stream is None


def test_service_ui_stream_skips_capture_while_screen_is_off():
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width = 100
  app._render_texture_height = 50
  captures = []
  app._ui_stream = SimpleNamespace(self_stop_due=lambda: False,
                                   output_size=lambda w, h: (w, h),
                                   maybe_capture=lambda now, w, h, read, **kw: captures.append(1),
                                   stop=lambda: None)

  app._service_ui_stream(capture=False)
  assert captures == []


def test_render_loop_starts_and_services_the_stream_while_screen_is_off(monkeypatch):
  # Galaxy can request the stream while the display is asleep. Rendering only
  # resumes once a viewer pulls images, and a viewer needs a bound listener, so
  # the skipped-frame path must still start it -- and still run idle shutdown.
  app = _bare_app()
  app._window_close_requested = False
  app._adaptive_rendering = False
  app._should_render = False
  app._target_fps = 10_000
  app._profile_render_frames = 0
  app._frame = 0
  app._mouse = SimpleNamespace(_handle_mouse_event=lambda: None, get_events=list)
  app._ui_stream_pending = True

  closes = iter([False, True])
  monkeypatch.setattr(application.rl, "window_should_close", lambda: next(closes))
  monkeypatch.setattr(application.rl, "poll_input_events", lambda: None)

  events = []
  stream = SimpleNamespace(pause=lambda: events.append("pause"),
                           resume=lambda: events.append("resume"),
                           self_stop_due=lambda: True,
                           output_size=lambda w, h: (w, h),
                                   maybe_capture=lambda now, w, h, read, **kw: events.append("capture"),
                           stop=lambda: events.append("stop"))

  def fake_start():
    events.append("start")
    app._ui_stream_pending = False
    app._ui_stream = stream

  monkeypatch.setattr(app, "_start_pending_ui_stream", fake_start)

  assert list(app.render()) == [False]
  assert events == ["start", "pause", "stop"]
  assert app._ui_stream is None


def test_record_frame_noop_without_texture():
  app = _bare_app()
  app._render_texture = None
  app._ffmpeg_queue = None
  app._record_frame()  # must not raise even though RECORD may be enabled


def test_record_frame_noop_without_ffmpeg_queue(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._ffmpeg_queue = None
  called = []
  monkeypatch.setattr(application.rl, "load_image_from_texture", lambda texture: called.append(1))
  app._record_frame()
  assert called == []


def test_record_frame_enqueues(monkeypatch):
  app = _bare_app()
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  frames = queue.Queue()
  app._ffmpeg_queue = frames

  raw = application.rl.ffi.new("unsigned char[]", 8)
  image = SimpleNamespace(data=raw, width=2, height=1)
  monkeypatch.setattr(application.rl, "load_image_from_texture", lambda texture: image)
  monkeypatch.setattr(application.rl, "unload_image", lambda img: None)

  app._record_frame()
  assert frames.get_nowait() == bytes(8)


def test_stop_ui_stream_is_idempotent():
  app = _bare_app()
  stops = []
  app._ui_stream = SimpleNamespace(stop=lambda: stops.append(1))
  app._stream_paused = True

  app.stop_ui_stream()
  assert stops == [1]
  assert app._ui_stream is None
  assert app._stream_paused is False

  app.stop_ui_stream()
  assert stops == [1]


def test_stream_telemetry_narrow_methods():
  app = _bare_app()
  published = []
  app._ui_stream = SimpleNamespace(
    telemetry_due=lambda now: now > 5.0,
    set_telemetry=lambda payload: published.append(payload),
  )
  assert app.stream_telemetry_due(6.0) is True
  assert app.stream_telemetry_due(1.0) is False
  app.publish_stream_telemetry(b"{}")
  assert published == [b"{}"]


def test_stream_telemetry_methods_without_stream():
  app = _bare_app()
  assert app.stream_telemetry_due(100.0) is False
  app.publish_stream_telemetry(b"{}")  # must not raise


def test_mici_stream_allocates_texture_on_request_and_reuses_it(monkeypatch):
  from openpilot.system.ui.lib import ui_stream as ui_stream_module

  monkeypatch.delenv("STREAM", raising=False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "mici")
  monkeypatch.setattr(application, "MICI_FORCE_RENDER_TEXTURE", False)
  real_stream = ui_stream_module.UiStream
  monkeypatch.setattr(ui_stream_module, "UiStream",
                      lambda config: real_stream(ui_stream_module.StreamConfig(bind="127.0.0.1", port=0)))
  app = _bare_app()
  app._render_texture = None
  app._render_texture_width = 536
  app._render_texture_height = 240
  texture = SimpleNamespace(texture=SimpleNamespace(id=7))
  allocations = []
  filters = []

  def allocate(width, height):
    allocations.append((width, height))
    return texture

  monkeypatch.setattr(application.rl, "load_render_texture", allocate)
  monkeypatch.setattr(application.rl, "set_texture_filter", lambda *args: filters.append(args))
  app.request_ui_stream()
  assert allocations == []  # Request handling itself must not touch GL.
  try:
    app._start_pending_ui_stream()
    assert app.ui_stream_state()[0] == "running"
    assert not app._ui_stream.status()["captureFailed"]
    assert app._render_texture is texture
    assert allocations == [(536, 240)]
    assert filters == [(texture.texture, application.rl.TextureFilter.TEXTURE_FILTER_BILINEAR)]
    captures = []
    monkeypatch.setattr(app._ui_stream, "maybe_capture", lambda now, w, h, read: captures.append((w, h)))
    app._capture_stream_frame()
    assert captures == [(536, 240)]

    app.stop_ui_stream()
    assert app._render_texture is texture
    app.request_ui_stream()
    app._start_pending_ui_stream()
    assert app.ui_stream_state()[0] == "running"
    assert not app._ui_stream.status()["captureFailed"]
    assert allocations == [(536, 240)]
  finally:
    app.stop_ui_stream()


class _FakeControl:
  """Stand-in for the streamer's control queue: hands out scripted batches."""

  def __init__(self, allowed=True):
    self.allowed = allowed
    self.batches: list[list] = []
    self.policy: list = []
    self.preempted: list[str] = []

  def set_control_allowed(self, allowed, reason):
    self.policy.append((allowed, reason))

  def drain_control(self, now):
    return self.batches.pop(0) if self.batches else []

  def preempt_control(self, reason):
    self.preempted.append(reason)


def _remote_app(allowed=True):
  app = _bare_app()
  app._width, app._height = 2160, 1080
  app._ui_stream_control_allowed = allowed
  app._ui_stream_control_reason = "" if allowed else "the car is onroad"
  app._ui_stream = _FakeControl(allowed)
  return app, app._ui_stream


def _touch(x, y, pressed=False, released=False, down=False, slot=0, t=0.0):
  return application.MouseEvent(application.MousePos(x, y), slot, pressed, released, down, t)


def _remote(kind, x=0.25, y=0.5):
  from openpilot.system.ui.lib.ui_stream import ControlEvent
  return ControlEvent(kind, x, y)


def _flags(events):
  return [(e.left_pressed, e.left_released, e.left_down, e.cancelled) for e in events]


def test_remote_input_maps_normalized_points_onto_the_logical_canvas():
  app, control = _remote_app()
  control.batches = [[_remote("down", 0.25, 0.5), _remote("move", 0.5, 0.5), _remote("up", 0.5, 0.5)]]
  events = app._arbitrate_input([], 10.0)
  assert control.policy == [(True, "")]
  assert [(e.pos.x, e.pos.y) for e in events] == [(540.0, 540.0), (1080.0, 540.0), (1080.0, 540.0)]
  assert _flags(events) == [(True, False, True, False), (False, False, True, False), (False, True, False, False)]
  assert all(e.slot == 0 for e in events)


def test_remote_cancel_is_not_a_release():
  app, control = _remote_app()
  control.batches = [[_remote("down")], [_remote("cancel")]]
  app._arbitrate_input([], 10.0)
  events = app._arbitrate_input([], 10.1)
  assert _flags(events) == [(False, False, False, True)]
  assert (events[0].pos.x, events[0].pos.y) == (540.0, 540.0)  # at the finger, not (0, 0)


def test_remote_events_without_a_delivered_press_are_dropped():
  app, control = _remote_app()
  control.batches = [[_remote("move"), _remote("up"), _remote("cancel")]]
  assert app._arbitrate_input([], 10.0) == []


def test_remote_press_refused_while_the_panel_is_in_use():
  app, control = _remote_app()
  press = _touch(10, 10, pressed=True, down=True)
  assert app._arbitrate_input([press], 10.0) == [press]
  control.batches = [[_remote("down"), _remote("up")]]
  assert app._arbitrate_input([], 10.1) == []  # finger still on the panel
  assert control.preempted == ["the comma screen is in use"]
  release = _touch(10, 10, released=True)
  app._arbitrate_input([release], 10.2)
  control.batches = [[_remote("down")]]
  assert app._arbitrate_input([], 10.2 + application.REMOTE_PHYSICAL_QUIET / 2) == []  # not quiet yet
  control.batches = [[_remote("down")]]
  assert _flags(app._arbitrate_input([], 10.2 + application.REMOTE_PHYSICAL_QUIET))[0][0] is True


def test_physical_touch_takes_over_a_remote_gesture():
  # The remote finger is withdrawn with a cancel *before* the physical press,
  # so the two never merge on slot 0 and the physical tap starts clean.
  app, control = _remote_app()
  control.batches = [[_remote("down")]]
  app._arbitrate_input([], 10.0)
  press = _touch(10, 10, pressed=True, down=True, t=10.1)
  control.batches = [[_remote("move")]]
  events = app._arbitrate_input([press], 10.1)
  assert _flags(events[:1]) == [(False, False, False, True)]
  assert events[1:] == [press]
  assert control.preempted == ["someone touched the comma screen"]
  assert app._remote_down is False


def test_desktop_hover_does_not_block_or_preempt_remote_input():
  app, control = _remote_app()
  control.batches = [[_remote("down")]]
  hover = _touch(10, 10)
  events = app._arbitrate_input([hover], 10.0)
  assert events[0] == hover and _flags(events[1:])[0][0] is True
  assert app._arbitrate_input([hover], 10.1) == [hover]
  assert app._remote_down is True and control.preempted == []


def test_remote_input_is_refused_until_the_app_opts_in(monkeypatch):
  # Only an app that decides when remote taps are safe may receive them.
  monkeypatch.setattr(application.GuiApplication, "_set_log_callback", lambda _: None)
  app = application.GuiApplication(536, 240)
  app._ui_stream = _FakeControl()
  assert app._arbitrate_input([], 10.0) == []
  assert app._ui_stream.policy == [(False, "not enabled by this app")]


def test_streamer_stopping_under_a_remote_press_cancels_it():
  app, control = _remote_app()
  control.stop = lambda: None
  control.batches = [[_remote("down")]]
  app._arbitrate_input([], 10.0)
  app.stop_ui_stream()
  assert _flags(app._arbitrate_input([], 10.1)) == [(False, False, False, True)]
  assert app._arbitrate_input([], 10.2) == []


# ------------------------------------------------------------ starpilot auto

def _fake_projection_gl(monkeypatch, pixels: bytes):
  drawn = []
  raw = application.rl.ffi.new("unsigned char[]", pixels)
  image = SimpleNamespace(data=raw, width=0, height=0, format=application.rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)

  def load_render_texture(w, h):
    image.width, image.height = w, h
    return SimpleNamespace(texture=SimpleNamespace(id=7, width=w, height=h))

  monkeypatch.setattr(application.rl, "load_render_texture", load_render_texture)
  monkeypatch.setattr(application.rl, "set_texture_filter", lambda *a: None)
  monkeypatch.setattr(application.rl, "begin_texture_mode", lambda t: None)
  monkeypatch.setattr(application.rl, "end_texture_mode", lambda: None)
  monkeypatch.setattr(application.rl, "clear_background", lambda c: None)
  monkeypatch.setattr(application.rl, "draw_texture_pro", lambda tex, src, dst, *a: drawn.append((dst.x, dst.y, dst.width, dst.height)))
  monkeypatch.setattr(application.rl, "load_image_from_texture", lambda texture: image)
  monkeypatch.setattr(application.rl, "unload_image", lambda img: None)
  monkeypatch.setattr(application.rl, "is_window_ready", lambda: False)
  return drawn


def test_starpilot_auto_capture_letterboxes_and_publishes(monkeypatch, tmp_path):
  from openpilot.starpilot.system.starpilot_auto.frame_source import FrameConsumer, FrameProducer, FrameRequest
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  consumer.configure(FrameRequest(800, 480, 0, 0, 50_000))
  app = _bare_app()
  app.set_starpilot_auto_enabled(True)
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width, app._render_texture_height = 536, 240
  app._starpilot_auto_frame_producer = FrameProducer(path)
  drawn = _fake_projection_gl(monkeypatch, bytes([9]) * (800 * 480 * 4))

  assert not app.ui_stream_wants_frames()
  app._capture_starpilot_auto_frame()
  assert drawn == []  # no demand, no GPU work

  consumer.demand(1.0)
  app._starpilot_auto_frame_producer._next_open_check = 0
  assert app.ui_stream_wants_frames()  # keeps rendering while the display sleeps
  app._capture_starpilot_auto_frame()
  assert drawn == [(0.0, 60.0, 800.0, 358.0)]
  frame = consumer.latest()
  assert frame is not None and (frame.width, frame.height) == (800, 480) and frame.data[:1] == b"\x09"
  consumer.close()


def test_starpilot_auto_capture_failure_disables_only_projection(monkeypatch, tmp_path):
  from openpilot.starpilot.system.starpilot_auto.frame_source import FrameConsumer, FrameProducer, FrameRequest
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  consumer.configure(FrameRequest(800, 480, 0, 0, 50_000))
  consumer.demand(1.0)
  app = _bare_app()
  app.set_starpilot_auto_enabled(True)
  app._render_texture = SimpleNamespace(texture=SimpleNamespace(id=1))
  app._render_texture_width, app._render_texture_height = 536, 240
  app._starpilot_auto_frame_producer = FrameProducer(path)
  _fake_projection_gl(monkeypatch, bytes(16))

  def explode(texture):
    raise RuntimeError("readback failed")

  monkeypatch.setattr(application.rl, "load_image_from_texture", explode)
  app._capture_starpilot_auto_frame()
  assert app._starpilot_auto_failed and app._starpilot_auto_frame_producer is None and app._starpilot_auto_texture is None
  assert not app.starpilot_auto_wants_frames()
  consumer.close()


@pytest.mark.parametrize("live_ui", [False, True])
def test_starpilot_auto_disable_releases_projection_and_preserves_live_ui(monkeypatch, tmp_path, live_ui):
  from openpilot.starpilot.system.starpilot_auto.frame_source import FrameConsumer, FrameProducer, FrameRequest
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  consumer.configure(FrameRequest(800, 480, 0, 0, 50_000))
  consumer.demand(1.0)
  app = _bare_app()
  app.set_starpilot_auto_enabled(True)
  producer = app._starpilot_auto_frame_producer = FrameProducer(path)
  assert producer.demand_active()
  main_texture = app._render_texture = object()
  capture_texture = app._starpilot_auto_texture = object()
  app._starpilot_auto_owns_render_texture = True
  stream = SimpleNamespace(image_demand_active=lambda: True)
  app._ui_stream = stream if live_ui else None
  unloaded = []
  monkeypatch.setattr(application.rl, "is_window_ready", lambda: True)
  monkeypatch.setattr(app, "_unload_render_texture", unloaded.append)
  monkeypatch.setattr(application.rl, "load_render_texture", lambda *a: pytest.fail("disabled projection allocated a texture"))

  app.set_starpilot_auto_enabled(False)
  app._ensure_starpilot_auto_texture()
  app._capture_starpilot_auto_frame()
  assert app._starpilot_auto_frame_producer is None and producer.mm is None
  assert not app.starpilot_auto_wants_frames()
  assert app.ui_stream_wants_frames() is live_ui
  assert capture_texture in unloaded
  assert (main_texture not in unloaded) is live_ui
  assert app._ui_stream is (stream if live_ui else None)
  if live_ui:
    app._ui_stream = None
    app._ensure_starpilot_auto_texture()
    assert main_texture in unloaded
  consumer.close()


def test_starpilot_auto_default_off_never_opens_frame_source(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import frame_source
  monkeypatch.setattr(frame_source, "FrameProducer", lambda: pytest.fail("disabled projection opened a frame source"))
  app = _bare_app()
  assert not app.starpilot_auto_enabled
  assert not app.starpilot_auto_wants_frames()
  app._ensure_starpilot_auto_texture()
  app._capture_starpilot_auto_frame()
