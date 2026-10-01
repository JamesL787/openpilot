import atexit
import cffi
import math
import os
import queue
import time
import signal
import sys
import pyray as rl
import threading
import platform
import subprocess
from contextlib import contextmanager
from collections.abc import Callable
from collections import deque
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple
from importlib.resources import as_file, files
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.ui.lib.multilang import multilang
from openpilot.common.realtime import Ratekeeper

DEVICE_TYPE = HARDWARE.get_device_type()
_DEFAULT_FPS = int(os.getenv("FPS", "60"))
FPS_LOG_INTERVAL = 5  # Seconds between logging FPS drops
FPS_DROP_THRESHOLD = 0.9  # FPS drop threshold for triggering a warning
FPS_CRITICAL_THRESHOLD = 0.5  # Critical threshold for triggering strict actions
MOUSE_THREAD_RATE = 140  # touch controller runs at 140Hz
DESKTOP_MOUSE_THREAD_RATE = int(os.getenv("DESKTOP_MOUSE_RATE", "500"))
DESKTOP_CLICK_DEBOUNCE = float(os.getenv("DESKTOP_CLICK_DEBOUNCE", "0.2"))
UI_IDLE_FPS = int(os.getenv("UI_IDLE_FPS", "0"))
UI_INTERACTION_FPS_DURATION = 1.25
MAX_TOUCH_SLOTS = 2
TOUCH_HISTORY_TIMEOUT = 3.0  # Seconds before touch points fade out
REMOTE_PHYSICAL_QUIET = 0.5  # untouched panel time before a remote press is accepted

BIG_UI = os.getenv("BIG", "0") == "1"
MACOS = platform.system() == "Darwin"
ENABLE_VSYNC = os.getenv("ENABLE_VSYNC", "0") == "1"
MICI_FORCE_RENDER_TEXTURE = os.getenv("MICI_FORCE_RENDER_TEXTURE", "0") == "1"
BURN_IN_PREVENTION = os.getenv("BURN_IN_PREVENTION", "0" if PC else "1") == "1"
BURN_IN_SHIFT_INTERVAL = max(1.0, float(os.getenv("BURN_IN_SHIFT_INTERVAL", "180")))
BURN_IN_SHIFT_PIXELS = max(0, int(os.getenv("BURN_IN_SHIFT_PIXELS", "2")))
BURN_IN_SHIFT_TRANSITION_SECONDS = min(
  BURN_IN_SHIFT_INTERVAL,
  max(0.1, float(os.getenv("BURN_IN_SHIFT_TRANSITION_SECONDS", "1"))),
)
WHITE_LUMINANCE_CAP = min(1.0, max(0.0, float(os.getenv(
  "WHITE_LUMINANCE_CAP", "1.0"
))))
SHOW_FPS = os.getenv("SHOW_FPS") == "1"
SHOW_TOUCHES = os.getenv("SHOW_TOUCHES") == "1"
STRICT_MODE = os.getenv("STRICT_MODE") == "1"
SCALE = float(os.getenv("SCALE", "1.0"))
GRID_SIZE = int(os.getenv("GRID", "0"))
PROFILE_RENDER = int(os.getenv("PROFILE_RENDER", "0"))
PROFILE_STATS = int(os.getenv("PROFILE_STATS", "100"))  # Number of functions to show in profile output
RECORD = os.getenv("RECORD") == "1"
RECORD_OUTPUT = str(Path(os.getenv("RECORD_OUTPUT", "output")).with_suffix(".mp4"))
RECORD_QUALITY = int(os.getenv("RECORD_QUALITY", "23"))  # Dynamic bitrate quality level (CRF); 0 is lossless (bigger size), max is 51, default is 23 for x264
RECORD_BITRATE = os.getenv("RECORD_BITRATE", "")  # Target bitrate e.g. "2000k" (overrides RECORD_QUALITY when set)
RECORD_SPEED = int(os.getenv("RECORD_SPEED", "1"))  # Speed multiplier
OFFSCREEN = os.getenv("OFFSCREEN") == "1"  # Disable FPS limiting for fast offline rendering


def _raylib_target_fps(fps: int) -> int:
  return 0 if OFFSCREEN or (DEVICE_TYPE == "mici" and not PC) else fps

GL_VERSION = """
#version 300 es
precision highp float;
"""
if platform.system() == "Darwin":
  GL_VERSION = """
    #version 330 core
  """

BURN_IN_MODE = "BURN_IN" in os.environ
BURN_IN_SHIFT_PATTERN = (
  (0, 0),
  (-1, 0),
  (-1, -1),
  (0, -1),
  (1, -1),
  (1, 0),
  (1, 1),
  (0, 1),
  (-1, 1),
)
BURN_IN_VERTEX_SHADER = GL_VERSION + """
in vec3 vertexPosition;
in vec2 vertexTexCoord;
uniform mat4 mvp;
out vec2 fragTexCoord;
void main() {
  fragTexCoord = vertexTexCoord;
  gl_Position = mvp * vec4(vertexPosition, 1.0);
}
"""
BURN_IN_FRAGMENT_SHADER = GL_VERSION + """
in vec2 fragTexCoord;
uniform sampler2D texture0;
out vec4 fragColor;
void main() {
  vec4 sampled = texture(texture0, fragTexCoord);
  float intensity = sampled.b;
  // Map blue intensity to green -> yellow -> red to highlight burn-in risk.
  vec3 start = vec3(0.0, 1.0, 0.0);
  vec3 middle = vec3(1.0, 1.0, 0.0);
  vec3 end = vec3(1.0, 0.0, 0.0);
  vec3 gradient = mix(start, middle, clamp(intensity * 2.0, 0.0, 1.0));
  gradient = mix(gradient, end, clamp((intensity - 0.5) * 2.0, 0.0, 1.0));
  fragColor = vec4(gradient, sampled.a);
}
"""
WHITE_LUMINANCE_FRAGMENT_SHADER = GL_VERSION + """
in vec2 fragTexCoord;
uniform sampler2D texture0;
uniform float whiteLuminanceCap;
out vec4 fragColor;
void main() {
  vec4 sampled = texture(texture0, fragTexCoord);
  float luminance = dot(sampled.rgb, vec3(0.2126, 0.7152, 0.0722));
  float chroma = max(max(sampled.r, sampled.g), sampled.b) - min(min(sampled.r, sampled.g), sampled.b);

  // Gently compress only near-white, low-saturation pixels. Saturated alert colors
  // and the vast majority of camera pixels pass through unchanged.
  float knee = max(0.0, whiteLuminanceCap - 0.05);
  if (luminance > knee) {
    float kneeRange = max(0.0001, 1.0 - knee);
    float targetLuminance = knee + (whiteLuminanceCap - knee) * ((luminance - knee) / kneeRange);
    float neutralAmount = 1.0 - smoothstep(0.08, 0.25, chroma);
    sampled.rgb *= mix(1.0, targetLuminance / max(luminance, 0.0001), neutralAmount);
  }

  fragColor = sampled;
}
"""

DEFAULT_TEXT_SIZE = 60
DEFAULT_TEXT_COLOR = rl.Color(255, 255, 255, int(255 * 0.9))

# Compensate for ascent/descent so migrated layouts keep their established alignment.
# The real scales for the fonts below range from 1.212 to 1.266
FONT_SCALE = 1.242 if BIG_UI else 1.16

ASSETS_DIR = files("openpilot.selfdrive").joinpath("assets")
FONT_DIR = ASSETS_DIR.joinpath("fonts")


class FontWeight(StrEnum):
  NORMAL = "Inter-Regular.fnt" if BIG_UI else "Inter-Medium.fnt"
  MEDIUM = "Inter-Medium.fnt"
  BOLD = "Inter-Bold.fnt"
  SEMI_BOLD = "Inter-SemiBold.fnt"
  UNIFONT = "unifont.fnt"
  BRAND = "como-heavy.fnt"

  # Small UI fonts
  DISPLAY_REGULAR = "Inter-Regular.fnt"
  ROMAN = "Inter-Regular.fnt"
  DISPLAY = "Inter-Bold.fnt"


def font_fallback(font: rl.Font) -> rl.Font:
  """Fall back to unifont for languages that require it."""
  if multilang.requires_unifont():
    try:
      if font.texture.id == gui_app.font(FontWeight.BRAND).texture.id:
        return font
    except (AttributeError, KeyError):
      pass
    return gui_app.font(FontWeight.UNIFONT)
  return font


class MousePos(NamedTuple):
  x: float
  y: float


class MousePosWithTime(NamedTuple):
  x: float
  y: float
  t: float


class MouseEvent(NamedTuple):
  pos: MousePos
  slot: int
  left_pressed: bool
  left_released: bool
  left_down: bool
  t: float
  # The touch was withdrawn (remote control lost its viewer, or a physical
  # touch took over). It is deliberately neither a press nor a release, so code
  # that does not know about cancel can never read it as a click or a swipe; it
  # just sees the finger go up. Aware code resets its gesture state.
  cancelled: bool = False


class _RemoteWithdrawn(NamedTuple):
  """Stand-in for a streamer ``cancel`` when there is no streamer to ask."""
  kind: str = "cancel"


_REMOTE_WITHDRAWN = _RemoteWithdrawn()


class FrameTiming(NamedTuple):
  frame_ms: float = 0.0
  cpu_ms: float = 0.0
  draw_ms: float = 0.0
  update_ms: float = 0.0
  present_ms: float = 0.0


class DesktopMouseSample(NamedTuple):
  pos: MousePos
  left_pressed: bool
  left_released: bool
  left_down: bool
  t: float


class DesktopMouseProvider:
  def sample(self) -> tuple[MousePos, bool]:
    raise NotImplementedError

  def close(self) -> None:
    pass

  @staticmethod
  def create() -> "DesktopMouseProvider | None":
    if MACOS:
      return MacOSDesktopMouseProvider()
    if platform.system() == "Linux":
      return LinuxDesktopMouseProvider()
    if platform.system() == "Windows":
      return WindowsDesktopMouseProvider()
    return None


class MacOSDesktopMouseProvider(DesktopMouseProvider):
  def __init__(self):
    import Quartz
    self._quartz = Quartz

  def sample(self) -> tuple[MousePos, bool]:
    q = self._quartz
    loc = q.CGEventGetLocation(q.CGEventCreate(None))
    left_down = (
      q.CGEventSourceButtonState(q.kCGEventSourceStateHIDSystemState, q.kCGMouseButtonLeft) or
      q.CGEventSourceButtonState(q.kCGEventSourceStateCombinedSessionState, q.kCGMouseButtonLeft)
    )
    return MousePos(loc.x, loc.y), bool(left_down)


class LinuxDesktopMouseProvider(DesktopMouseProvider):
  def __init__(self):
    from Xlib import X, display
    self._button_mask = X.Button1Mask
    self._display = display.Display()
    self._root = self._display.screen().root

  def sample(self) -> tuple[MousePos, bool]:
    data = self._root.query_pointer()._data
    return MousePos(data["root_x"], data["root_y"]), bool(data["mask"] & self._button_mask)

  def close(self) -> None:
    self._display.close()


class WindowsDesktopMouseProvider(DesktopMouseProvider):
  def __init__(self):
    import ctypes
    self._ctypes = ctypes
    self._user32 = ctypes.windll.user32

    class POINT(ctypes.Structure):
      _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    self._point_cls = POINT
    try:
      self._user32.SetProcessDPIAware()
    except AttributeError:
      pass

  def sample(self) -> tuple[MousePos, bool]:
    point = self._point_cls()
    self._user32.GetCursorPos(self._ctypes.byref(point))
    left_down = bool(self._user32.GetAsyncKeyState(0x01) & 0x8000)
    return MousePos(point.x, point.y), left_down


class MouseState:
  def __init__(self, scale: float = 1.0):
    self._scale = scale
    self._events: deque[MouseEvent] = deque(maxlen=MOUSE_THREAD_RATE)  # bound event list
    self._prev_mouse_event: list[MouseEvent | None] = [None] * MAX_TOUCH_SLOTS

    self._rk = Ratekeeper(MOUSE_THREAD_RATE, print_delay_threshold=None)
    self._lock = threading.Lock()
    self._exit_event = threading.Event()
    self._thread = None
    self._desktop_left_down = False
    self._desktop_click_active = False
    self._desktop_click_suppressed = False
    self._desktop_last_click_t = -math.inf
    self._desktop_samples: deque[DesktopMouseSample] = deque(maxlen=DESKTOP_MOUSE_THREAD_RATE)
    self._desktop_provider: DesktopMouseProvider | None = None

  def get_events(self) -> list[MouseEvent]:
    with self._lock:
      events = list(self._events)
      self._events.clear()
    return events

  def start(self):
    self._exit_event.clear()
    if self._thread is None or not self._thread.is_alive():
      self._thread = threading.Thread(target=self._run_thread, daemon=True)
      self._thread.start()

  def start_desktop_mouse_sampler(self):
    try:
      self._desktop_provider = DesktopMouseProvider.create()
    except Exception:
      cloudlog.exception("Failed to initialize desktop mouse sampler")
      self._desktop_provider = None

    if self._desktop_provider is None:
      return

    self._exit_event.clear()
    if self._thread is None or not self._thread.is_alive():
      self._thread = threading.Thread(target=self._run_desktop_thread, daemon=True)
      self._thread.start()

  def stop(self):
    self._exit_event.set()
    if self._thread is not None and self._thread.is_alive():
      self._thread.join()
    if self._desktop_provider is not None:
      self._desktop_provider.close()
      self._desktop_provider = None
    self._desktop_left_down = False
    self._desktop_click_active = False
    self._desktop_click_suppressed = False

  def _desktop_mouse_pos(self) -> MousePos:
    mouse_pos = rl.get_mouse_position()
    return MousePos(mouse_pos.x, mouse_pos.y)

  def _desktop_window_pos(self) -> MousePos:
    window_pos = rl.get_window_position()
    return MousePos(window_pos.x, window_pos.y)

  def _run_thread(self):
    while not self._exit_event.is_set():
      rl.poll_input_events()
      self._handle_mouse_event()
      self._rk.keep_time()

  def _run_desktop_thread(self):
    rk = Ratekeeper(DESKTOP_MOUSE_THREAD_RATE, print_delay_threshold=None)
    prev_pos: MousePos | None = None
    prev_left_down = False

    while not self._exit_event.is_set():
      try:
        assert self._desktop_provider is not None
        pos, left_down = self._desktop_provider.sample()
      except Exception:
        cloudlog.exception("Desktop mouse sampler failed")
        self._desktop_provider = None
        break

      left_pressed = left_down and not prev_left_down
      left_released = prev_left_down and not left_down
      if left_pressed or left_released or pos != prev_pos:
        with self._lock:
          self._desktop_samples.append(DesktopMouseSample(
            pos,
            left_pressed,
            left_released,
            left_down,
            time.monotonic(),
          ))

      prev_pos = pos
      prev_left_down = left_down
      rk.keep_time()

  def _get_desktop_samples(self) -> list[DesktopMouseSample]:
    with self._lock:
      samples = list(self._desktop_samples)
      self._desktop_samples.clear()
    return samples

  def _debounce_desktop_mouse_event(self, ev: MouseEvent) -> MouseEvent | None:
    if ev.left_pressed:
      if ev.t - self._desktop_last_click_t < DESKTOP_CLICK_DEBOUNCE:
        self._desktop_click_active = False
        self._desktop_click_suppressed = True
        return None

      self._desktop_click_active = True
      self._desktop_click_suppressed = False
      return ev

    if self._desktop_click_suppressed:
      if ev.left_released or not ev.left_down:
        self._desktop_click_suppressed = False
      return None

    if ev.left_released:
      if not self._desktop_click_active:
        return None

      self._desktop_click_active = False
      self._desktop_last_click_t = ev.t
      return ev

    if ev.left_down and not self._desktop_click_active:
      return None

    return ev

  def _handle_mouse_event(self):
    # TODO: read touch events from evdev directly to get real kernel timestamps.
    #  Polling at 140Hz with time.monotonic() causes timing jitter that makes scroll
    #  velocity oscillate (alternating high/low). Real timestamps would also let us
    #  detect swipe-stop-lift via event gaps instead of the fragile decel heuristic.
    if PC:
      if self._desktop_provider is not None:
        scale = self._scale if self._scale != 0 else 1.0
        window_pos = self._desktop_window_pos()
        for sample in self._get_desktop_samples():
          local_pos = MousePos(
            (sample.pos.x - window_pos.x) / scale,
            (sample.pos.y - window_pos.y) / scale,
          )
          event = self._debounce_desktop_mouse_event(MouseEvent(
            local_pos,
            0,
            sample.left_pressed,
            sample.left_released,
            sample.left_down,
            sample.t,
          ))
          if event is not None:
            self._append_mouse_event(event)
        return

      left_down = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)
      left_pressed = (
        rl.is_mouse_button_pressed(rl.MouseButton.MOUSE_BUTTON_LEFT) or  # noqa: TID251
        (left_down and not self._desktop_left_down)
      )
      left_released = (
        rl.is_mouse_button_released(rl.MouseButton.MOUSE_BUTTON_LEFT) or  # noqa: TID251
        (self._desktop_left_down and not left_down)
      )
      self._append_mouse_event(MouseEvent(
        self._desktop_mouse_pos(),
        0,
        left_pressed,
        left_released,
        left_down,
        time.monotonic(),
      ))
      self._desktop_left_down = left_down
      return

    for slot in range(MAX_TOUCH_SLOTS):
      mouse_pos = rl.get_touch_position(slot)
      x = mouse_pos.x / self._scale if self._scale != 1.0 else mouse_pos.x
      y = mouse_pos.y / self._scale if self._scale != 1.0 else mouse_pos.y
      self._append_mouse_event(MouseEvent(
        MousePos(x, y),
        slot,
        rl.is_mouse_button_pressed(slot),  # noqa: TID251
        rl.is_mouse_button_released(slot),  # noqa: TID251
        rl.is_mouse_button_down(slot),
        time.monotonic(),
      ))

  def _append_mouse_event(self, ev: MouseEvent):
    if ev.left_pressed and ev.left_released:
      press_ev = MouseEvent(ev.pos, ev.slot, True, False, True, ev.t)
      release_ev = MouseEvent(ev.pos, ev.slot, False, True, False, ev.t)
      self._append_mouse_event(press_ev)
      self._append_mouse_event(release_ev)
      return

    # Only add changes
    prev = self._prev_mouse_event[ev.slot]
    if prev is None or ev[:5] != prev[:5]:
      with self._lock:
        self._events.append(ev)
      self._prev_mouse_event[ev.slot] = ev


class GuiApplication:
  # Starpilot Auto capture state; class defaults keep partially constructed apps (tests) safe.
  _starpilot_auto_frame_producer = None
  _starpilot_auto_texture = None
  _starpilot_auto_failed = False
  _starpilot_auto_enabled = False
  _starpilot_auto_owns_render_texture = False

  @property
  def starpilot_auto_enabled(self) -> bool:
    return self._starpilot_auto_enabled

  def set_starpilot_auto_enabled(self, enabled: bool) -> None:
    if enabled != self._starpilot_auto_enabled:
      self._starpilot_auto_enabled = enabled
      self._starpilot_auto_failed = False

  def __init__(self, width: int | None = None, height: int | None = None):
    self._set_log_callback()

    self._fonts: dict[FontWeight, rl.Font] = {}
    self._width = width if width is not None else GuiApplication._default_width()
    self._height = height if height is not None else GuiApplication._default_height()

    if PC and os.getenv("SCALE") is None:
      self._scale = self._calculate_auto_scale()
    else:
      self._scale = SCALE

    # Scale, then ensure dimensions are even
    self._scaled_width = int(self._width * self._scale)
    self._scaled_height = int(self._height * self._scale)
    self._scaled_width += self._scaled_width % 2
    self._scaled_height += self._scaled_height % 2
    self._pixel_scale_x = 1.0
    self._pixel_scale_y = 1.0
    self._render_texture_width = self._scaled_width
    self._render_texture_height = self._scaled_height

    self._render_texture: rl.RenderTexture | None = None
    self._burn_in_shader: rl.Shader | None = None
    self._white_luminance_shader: rl.Shader | None = None
    self._ffmpeg_proc: subprocess.Popen | None = None
    self._ffmpeg_queue: queue.Queue | None = None
    self._ffmpeg_thread: threading.Thread | None = None
    self._ffmpeg_stop_event: threading.Event | None = None
    self._ui_stream = None
    self._ui_stream_pending = False
    self._ui_stream_owns_texture = False
    self._ui_stream_texture: rl.RenderTexture | None = None
    self._ui_stream_scale_failed = False
    self._ui_stream_error = ""
    self._ui_stream_control_allowed = False
    self._ui_stream_control_reason = "not enabled by this app"
    # Starpilot Auto projection (starpilot_autod) pulls frames through shared memory.
    self._starpilot_auto_frame_producer = None
    self._starpilot_auto_texture: rl.RenderTexture | None = None
    self._starpilot_auto_buffer: bytearray | None = None
    self._starpilot_auto_failed = False
    # Live remote touch and its arbitration against the physical screen.
    self._remote_down = False
    self._remote_pos = MousePos(0, 0)
    self._physical_slots_down: set[int] = set()
    self._last_physical_event_t = -math.inf
    self._stream_paused = False
    self._progress_hook: Callable[[str], None] | None = None
    self._textures: dict[str, rl.Texture] = {}
    self._cached_render_textures: dict[str, rl.RenderTexture] = {}
    self._pending_render_textures: dict[str, tuple[int, int, Callable[[], None]]] = {}
    self._target_fps: int = _DEFAULT_FPS
    self._full_target_fps: int = _DEFAULT_FPS
    self._idle_target_fps: int = max(10, _DEFAULT_FPS // 4)
    self._adaptive_rendering = False
    self._full_rate_rendering = False
    self._high_fps_until = 0.0
    self._last_fps_log_time: float = time.monotonic()
    self._burn_in_start_time = time.monotonic()
    self._frame = 0
    self.frame_timing = FrameTiming()
    self._window_close_requested = False
    self._nav_stack: list[object] = []
    self._nav_stack_ticks: list[Callable[[], None]] = []
    self._nav_stack_widgets_to_render = 1 if self.big_ui() else 2

    self._mouse = MouseState(self._scale)
    self._mouse_events: list[MouseEvent] = []
    self._last_mouse_event: MouseEvent = MouseEvent(MousePos(0, 0), 0, False, False, False, 0.0)

    self._should_render = True

    # Debug variables
    self._mouse_history: deque[MousePosWithTime] = deque(maxlen=MOUSE_THREAD_RATE)
    self._show_touches = SHOW_TOUCHES
    self._show_fps = SHOW_FPS
    self._grid_size = GRID_SIZE
    self._profile_render_frames = PROFILE_RENDER
    self._render_profiler = None
    self._render_profile_start_time = None

  @property
  def frame(self):
    return self._frame

  def set_show_touches(self, show: bool):
    self._show_touches = show

  def set_show_fps(self, show: bool):
    self._show_fps = show

  @property
  def show_touches(self) -> bool:
    return self._show_touches

  @property
  def target_fps(self):
    return self._target_fps

  def _set_target_fps(self, fps: int) -> None:
    fps = max(1, int(fps))
    if fps == self._target_fps:
      return
    rl.set_target_fps(_raylib_target_fps(fps))
    self._target_fps = fps

  def configure_adaptive_rendering(self, enabled: bool, idle_fps: int | None = None) -> None:
    """Enable low-rate rendering for static BIG-UI offroad screens.

    The normal target remains unchanged unless a caller opts in. This keeps
    MICI and all existing non-BIG layouts on their current scheduling path.
    """
    # Recording feeds raw frames to ffmpeg at the fixed full FPS, so changing
    # the producer rate would make idle portions play back too quickly.
    self._adaptive_rendering = bool(enabled and not OFFSCREEN and not RECORD)
    if idle_fps is None or idle_fps <= 0:
      idle_fps = UI_IDLE_FPS if UI_IDLE_FPS > 0 else max(10, self._full_target_fps // 4)
    self._idle_target_fps = min(self._full_target_fps, max(1, int(idle_fps)))
    self._full_rate_rendering = False
    self._high_fps_until = time.monotonic() + UI_INTERACTION_FPS_DURATION if self._adaptive_rendering else 0.0
    if self._adaptive_rendering:
      self._apply_render_mode()
    else:
      self._set_target_fps(self._full_target_fps)

  def request_high_fps(self, duration: float = UI_INTERACTION_FPS_DURATION) -> None:
    if not self._adaptive_rendering:
      return
    self._high_fps_until = max(self._high_fps_until, time.monotonic() + max(0.0, duration))
    self._apply_render_mode()

  def set_render_mode(self, active: bool) -> None:
    if not self._adaptive_rendering:
      return
    self._full_rate_rendering = active
    self._apply_render_mode()

  def _apply_render_mode(self) -> None:
    if not self._adaptive_rendering:
      return
    high_rate = self._full_rate_rendering or time.monotonic() < self._high_fps_until
    self._set_target_fps(self._full_target_fps if high_rate else self._idle_target_fps)

  def request_close(self):
    self._window_close_requested = True

  def init_window(self, title: str, fps: int = _DEFAULT_FPS):
    with self._startup_profile_context():
      def _request_close(sig, frame):
        self.request_close()
      signal.signal(signal.SIGINT, _request_close)
      atexit.register(self.close)

      flags = rl.ConfigFlags.FLAG_MSAA_4X_HINT
      if ENABLE_VSYNC:
        flags |= rl.ConfigFlags.FLAG_VSYNC_HINT
      rl.set_config_flags(flags)

      rl.init_window(self._scaled_width, self._scaled_height, title)
      screen_width = max(rl.get_screen_width(), 1)
      screen_height = max(rl.get_screen_height(), 1)
      self._pixel_scale_x = max(1.0, rl.get_render_width() / screen_width) if PC else 1.0
      self._pixel_scale_y = max(1.0, rl.get_render_height() / screen_height) if PC else 1.0
      self._render_texture_width = max(1, int(round(self._scaled_width * self._pixel_scale_x)))
      self._render_texture_height = max(1, int(round(self._scaled_height * self._pixel_scale_y)))

      # The streamer starts on demand (a browser opening Live UI posts
      # UiStreamRequested), so it does not take part in this decision. Where the
      # texture below is not allocated, the streamer allocates it at request time
      # on the render thread.
      streaming = False

      # Keep big-UI burn-in movement in final-frame composition. Translating the live EGL
      # camera/widget pass can corrupt the camera presentation instead of shifting the UI.
      needs_render_texture = ((self._scale != 1.0 and not PC) or BURN_IN_MODE or RECORD or
                              MICI_FORCE_RENDER_TEXTURE or
                              (BURN_IN_PREVENTION and DEVICE_TYPE != "mici") or
                              WHITE_LUMINANCE_CAP < 1.0 or
                              streaming)
      if PC and self._scale != 1.0:
        rl.set_mouse_scale(1 / self._scale, 1 / self._scale)
      if PC:
        self._mouse.start_desktop_mouse_sampler()
      if needs_render_texture:
        if MICI_FORCE_RENDER_TEXTURE:
          cloudlog.warning("Forcing render texture path for mici UI")
        self._render_texture = rl.load_render_texture(self._render_texture_width, self._render_texture_height)
        texture = getattr(self._render_texture, "texture", None)
        if texture is None or getattr(texture, "id", 0) == 0:
          cloudlog.error("Render texture allocation failed")
          self._render_texture = None
          if streaming:
            cloudlog.error("UI streamer disabled: render texture unavailable")
            self.stop_ui_stream()
            streaming = False
        else:
          rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)

      if RECORD and self._render_texture is None:
        cloudlog.error("RECORD disabled: render texture unavailable")

      if RECORD and self._render_texture is not None:
        output_fps = fps * RECORD_SPEED
        ffmpeg_args = [
          'ffmpeg',
          '-v', 'warning',          # Reduce ffmpeg log spam
          '-nostats',               # Suppress encoding progress
          '-f', 'rawvideo',         # Input format
          '-pix_fmt', 'rgba',       # Input pixel format
          '-s', f'{self._render_texture_width}x{self._render_texture_height}',  # Input resolution
          '-r', str(fps),           # Input frame rate
          '-i', 'pipe:0',           # Input from stdin
          '-vf', 'vflip,format=yuv420p',  # Flip vertically and convert to yuv420p
          '-r', str(output_fps),    # Output frame rate (for speed multiplier)
          '-c:v', 'libx264',
          '-preset', 'veryfast',
          '-crf', str(RECORD_QUALITY)
        ]
        if RECORD_BITRATE:
          # NOTE: custom bitrate overrides crf setting
          ffmpeg_args += ['-b:v', RECORD_BITRATE, '-maxrate', RECORD_BITRATE, '-bufsize', RECORD_BITRATE]
        ffmpeg_args += [
          '-y',                     # Overwrite existing file
          '-f', 'mp4',              # Output format
          RECORD_OUTPUT,            # Output file path
        ]
        self._ffmpeg_proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE)
        self._ffmpeg_queue = queue.Queue(maxsize=60)  # Buffer up to 60 frames
        self._ffmpeg_stop_event = threading.Event()
        self._ffmpeg_thread = threading.Thread(target=self._ffmpeg_writer_thread, daemon=True)
        self._ffmpeg_thread.start()

      rl.set_target_fps(_raylib_target_fps(fps))

      self._full_target_fps = fps
      self._target_fps = fps
      self._set_styles()
      self._load_fonts()
      self._patch_text_functions()
      self._patch_scissor_mode()
      if BURN_IN_MODE and self._burn_in_shader is None:
        self._burn_in_shader = rl.load_shader_from_memory(BURN_IN_VERTEX_SHADER, BURN_IN_FRAGMENT_SHADER)
      if WHITE_LUMINANCE_CAP < 1.0 and self._white_luminance_shader is None:
        self._white_luminance_shader = rl.load_shader_from_memory(BURN_IN_VERTEX_SHADER, WHITE_LUMINANCE_FRAGMENT_SHADER)
        cap_location = rl.get_shader_location(self._white_luminance_shader, "whiteLuminanceCap")
        cap_value = rl.ffi.new("float[]", [WHITE_LUMINANCE_CAP])
        rl.set_shader_value(self._white_luminance_shader, cap_location, cap_value,
                            rl.ShaderUniformDataType.SHADER_UNIFORM_FLOAT)

      if not PC:
        self._mouse.start()

  @contextmanager
  def _startup_profile_context(self):
    if "PROFILE_STARTUP" not in os.environ:
      yield
      return

    import cProfile
    import io
    import pstats

    profiler = cProfile.Profile()
    start_time = time.monotonic()
    profiler.enable()

    # do the init
    yield

    profiler.disable()
    elapsed_ms = (time.monotonic() - start_time) * 1e3

    stats_stream = io.StringIO()
    pstats.Stats(profiler, stream=stats_stream).sort_stats("cumtime").print_stats(25)
    print("\n=== Startup profile ===")
    print(stats_stream.getvalue().rstrip())

    green = "\033[92m"
    reset = "\033[0m"
    print(f"{green}UI window ready in {elapsed_ms:.1f} ms{reset}")
    sys.exit(0)

  def _ffmpeg_writer_thread(self):
    """Background thread that writes frames to ffmpeg."""
    while True:
      try:
        data = self._ffmpeg_queue.get(timeout=1.0)
        if data is None:  # Sentinel to stop
          break
        self._ffmpeg_proc.stdin.write(data)
      except queue.Empty:
        if self._ffmpeg_stop_event.is_set():
          break
        continue
      except Exception:
        break

  def push_widget(self, widget: object):
    if widget in self._nav_stack:
      cloudlog.warning("Widget already in stack, cannot push again!")
      return

    # disable previous widget to prevent input processing
    if len(self._nav_stack) > 0:
      prev_widget = self._nav_stack[-1]
      # TODO: change these to touch_valid
      prev_widget.set_enabled(False)

    self._nav_stack.append(widget)
    self.request_high_fps()
    widget.show_event()
    widget.set_enabled(True)

  def pop_widget(self, idx: int | None = None):
    # Pops widget instantly without animation
    if len(self._nav_stack) < 2:
      cloudlog.warning("At least one widget should remain on the stack, ignoring pop!")
      return

    idx_to_pop = len(self._nav_stack) - 1 if idx is None else idx
    if idx_to_pop <= 0 or idx_to_pop >= len(self._nav_stack):
      cloudlog.warning(f"Invalid index {idx_to_pop} to pop, ignoring!")
      return

    # only re-enable previous widget if popping top widget
    if idx_to_pop == len(self._nav_stack) - 1:
      prev_widget = self._nav_stack[idx_to_pop - 1]
      prev_widget.set_enabled(True)

    widget = self._nav_stack.pop(idx_to_pop)
    widget.hide_event()
    self.request_high_fps()

  def pop_widgets_to(self, widget: object, callback: Callable[[], None] | None = None, instant: bool = False):
    # Pops middle widgets instantly without animation then dismisses top, animated out if NavWidget
    if widget not in self._nav_stack:
      cloudlog.warning("Widget not in stack, cannot pop to it!")
      return

    # Nothing to pop, ensure we still run callback
    top_widget = self._nav_stack[-1]
    if top_widget == widget:
      if callback:
        callback()
      return

    # instantly pop widgets in between, then dismiss top widget for animation
    while len(self._nav_stack) > 1 and self._nav_stack[-2] != widget:
      self.pop_widget(len(self._nav_stack) - 2)

    if not instant:
      top_widget.dismiss(callback)
    else:
      self.pop_widget()

  def get_active_widget(self):
    if len(self._nav_stack) > 0:
      return self._nav_stack[-1]
    return None

  def widget_in_stack(self, widget: object) -> bool:
    return widget in self._nav_stack

  def add_nav_stack_tick(self, tick_function: Callable[[], None]):
    if tick_function not in self._nav_stack_ticks:
      self._nav_stack_ticks.append(tick_function)

  def remove_nav_stack_tick(self, tick_function: Callable[[], None]):
    if tick_function in self._nav_stack_ticks:
      self._nav_stack_ticks.remove(tick_function)

  def set_progress_hook(self, hook: Callable[[str], None] | None) -> None:
    self._progress_hook = hook

  def _mark_progress(self, phase: str) -> None:
    if self._progress_hook is not None:
      self._progress_hook(phase)

  def mark_progress(self, phase: str) -> None:
    """Expose lightweight phase markers to complex widgets."""
    self._mark_progress(phase)

  def set_should_render(self, should_render: bool):
    self._should_render = should_render
    if should_render:
      self.request_high_fps()

  def texture(self, asset_path: str, width: int | None = None, height: int | None = None,
              alpha_premultiply=False, keep_aspect_ratio=True, flip_x: bool = False) -> rl.Texture:
    if width is not None:
      width = round(width)
    if height is not None:
      height = round(height)

    cache_key = f"{asset_path}_{width}_{height}_{alpha_premultiply}_{keep_aspect_ratio}_{flip_x}"
    if cache_key in self._textures:
      return self._textures[cache_key]

    with as_file(ASSETS_DIR.joinpath(asset_path)) as fspath:
      image_obj = self._load_image_from_path(fspath.as_posix(), width, height, alpha_premultiply, keep_aspect_ratio, flip_x)
      texture_obj = self._load_texture_from_image(image_obj)

    # Set logical size so widget layout math stays at 1x coordinates.
    if width is not None and height is not None:
      texture_obj.width = width
      texture_obj.height = height

    self._textures[cache_key] = texture_obj
    return texture_obj

  def cached_render_texture(self, cache_key: str, width: int, height: int,
                            render: Callable[[], None], supersample: int = 1) -> object | None:
    """Return a cached texture, scheduling cache misses between frames.

    Raylib render-texture modes are not nestable. Widgets call this while the
    main framebuffer (often another render texture) is active, so cache misses
    must be populated after the frame has been presented.

    Render textures have no MSAA, so vector content drawn into them is aliased.
    A power-of-two ``supersample`` renders at that multiple (``render`` still
    draws in ``width`` x ``height`` coordinates) and box-filters back down.
    """
    cached = self._cached_render_textures.get(cache_key)
    if cached is not None:
      return cached.texture

    self._pending_render_textures.setdefault(
      cache_key, (max(1, int(width)), max(1, int(height)), render, max(1, int(supersample)))
    )
    return None

  @staticmethod
  def _render_into_texture(target: rl.RenderTexture, draw: Callable[[], None],
                           src_factor: int, zoom: float = 1.0) -> None:
    began_texture_mode = False
    began_blend_mode = False
    began_mode_2d = False
    try:
      rl.begin_texture_mode(target)
      began_texture_mode = True
      rl.clear_background(rl.Color(0, 0, 0, 0))
      # Alpha is kept straight while RGB is premultiplied (src_factor
      # RL_SRC_ALPHA) or copied as-is (RL_ONE, for already-premultiplied input).
      # The result is composited with BLEND_ALPHA_PREMULTIPLY without squaring
      # translucent vector alpha.
      rl.rl_set_blend_factors_separate(
        src_factor, rl.RL_ONE_MINUS_SRC_ALPHA,
        rl.RL_ONE, rl.RL_ONE_MINUS_SRC_ALPHA,
        rl.RL_FUNC_ADD, rl.RL_FUNC_ADD,
      )
      rl.begin_blend_mode(rl.BlendMode.BLEND_CUSTOM_SEPARATE)
      began_blend_mode = True
      if zoom != 1.0:
        rl.begin_mode_2d(rl.Camera2D(rl.Vector2(0, 0), rl.Vector2(0, 0), 0.0, zoom))
        began_mode_2d = True
      draw()
    finally:
      if began_mode_2d:
        rl.end_mode_2d()
      if began_blend_mode:
        rl.end_blend_mode()
      if began_texture_mode:
        rl.end_texture_mode()
    rl.set_texture_filter(target.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    rl.set_texture_wrap(target.texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)

  def _populate_render_texture_cache(self) -> None:
    pending = self._pending_render_textures
    self._pending_render_textures = {}
    for cache_key, (width, height, render, supersample) in pending.items():
      if cache_key in self._cached_render_textures:
        continue

      scale = 1
      while scale * 2 <= supersample:
        scale *= 2
      cached = rl.load_render_texture(width * scale, height * scale)
      try:
        self._render_into_texture(cached, render, rl.RL_SRC_ALPHA, float(scale))
        # Halve repeatedly: a bilinear tap centred between four texels at an
        # exact 2:1 ratio is a 2x2 box filter, so the chain is a scale x scale box.
        while scale > 1:
          scale //= 2
          source = cached
          cached = rl.load_render_texture(width * scale, height * scale)
          try:
            self._render_into_texture(cached, lambda src=source, w=width * scale, h=height * scale: rl.draw_texture_pro(
              src.texture, rl.Rectangle(0, 0, src.texture.width, -src.texture.height),
              rl.Rectangle(0, 0, w, h), rl.Vector2(0, 0), 0.0, rl.WHITE), rl.RL_ONE)
          finally:
            rl.unload_render_texture(source)
      except Exception:
        rl.unload_render_texture(cached)
        raise
      self._cached_render_textures[cache_key] = cached

  def _load_image_from_path(self, image_path: str, width: int | None = None, height: int | None = None,
                            alpha_premultiply: bool = False, keep_aspect_ratio: bool = True, flip_x: bool = False) -> rl.Image:
    """Load and resize an image, storing it for later automatic unloading."""
    image = rl.load_image(image_path)

    if alpha_premultiply:
      rl.image_alpha_premultiply(image)

    # Scale up load size for sharper rendering, capped at source resolution.
    if width is not None and height is not None:
      width = min(int(width * self._scale * self._pixel_scale_x), image.width)
      height = min(int(height * self._scale * self._pixel_scale_y), image.height)

    if width is not None and height is not None:
      same_dimensions = image.width == width and image.height == height

      # Resize with aspect ratio preservation if requested
      if not same_dimensions:
        if keep_aspect_ratio:
          orig_width = image.width
          orig_height = image.height

          scale_width = width / orig_width
          scale_height = height / orig_height

          # Calculate new dimensions
          scale = min(scale_width, scale_height)
          new_width = int(orig_width * scale)
          new_height = int(orig_height * scale)

          rl.image_resize(image, new_width, new_height)
        else:
          rl.image_resize(image, width, height)
    else:
      assert keep_aspect_ratio, "Cannot resize without specifying width and height"

    if flip_x:
      rl.image_flip_horizontal(image)

    return image

  def _load_texture_from_image(self, image: rl.Image) -> rl.Texture:
    """Send image to GPU and unload original image."""
    texture = rl.load_texture_from_image(image)
    # Set texture filtering to smooth the result
    rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    # prevent artifacts from wrapping coordinates
    rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)

    rl.unload_image(image)
    return texture

  # ---------------------------------------------------------------- ui streamer

  def request_ui_stream(self) -> None:
    """Ask for the streamer to start. Safe from the UI loop; touches no GL.

    The actual bind, texture allocation and thread start happen on the render
    thread in :meth:`_start_pending_ui_stream`, because allocating a render
    texture is a GL operation.
    """
    if self._ui_stream is None:
      self._ui_stream_pending = True
      self._ui_stream_error = ""

  def ui_stream_running(self) -> bool:
    return self._ui_stream is not None

  def ui_stream_state(self) -> tuple[str, str, int]:
    """``(state, detail, port)`` for publication to Galaxy.

    Galaxy waits on this, not on the consumed request flag: the flag only
    proves the request was seen, while the viewer page is served by the
    listener and must not be loaded before it is bound. ``running`` means
    bound and serving (a paused stream included -- the viewer reports that
    itself); ``error`` carries the reason the last start attempt failed.
    """
    stream = self._ui_stream
    if stream is not None:
      try:
        return "running", "", stream.port
      except Exception:  # pragma: no cover - server socket already gone
        return "running", "", 0
    if self._ui_stream_pending:
      return "starting", "", 0
    if self._ui_stream_error:
      return "error", self._ui_stream_error, 0
    return "off", "", 0

  def set_ui_stream_control(self, allowed: bool, reason: str = "") -> None:
    """Policy for remote touch input from the streamer, set by the app.

    Off until the app opts in, so only a UI that decides when remote taps are
    safe (``selfdrive.ui`` refuses them while driving) can ever receive them.
    """
    self._ui_stream_control_allowed = allowed
    self._ui_stream_control_reason = reason

  def _arbitrate_input(self, physical: list[MouseEvent], now: float) -> list[MouseEvent]:
    """This frame's events: physical touches plus live remote control.

    Render thread only. Remote input shares slot 0 with the touchscreen, so
    exactly one source owns it at a time, and the physical screen wins:

    * a remote press is refused while a finger is down or the panel was
      touched within ``REMOTE_PHYSICAL_QUIET``;
    * a finger landing during a remote gesture withdraws it with a ``cancelled``
      event first, so the physical gesture starts clean.

    A remote gesture only ever ends in a real release when its viewer lifted.
    Every other ending -- preemption, a stalled or vanished viewer, control
    refused (onroad), the streamer stopping -- is a cancel, which widgets
    treat as the finger going away without a click.
    """
    touching = False
    for event in physical:
      if event.left_down:
        self._physical_slots_down.add(event.slot)
      else:
        self._physical_slots_down.discard(event.slot)
      # Desktop hover (no button) is not a touch.
      touching |= event.left_down or event.left_released
    if touching:
      self._last_physical_event_t = now
    physical_busy = bool(self._physical_slots_down) or now - self._last_physical_event_t < REMOTE_PHYSICAL_QUIET

    events: list[MouseEvent] = []
    if self._remote_down and (touching or self._physical_slots_down):
      events.append(self._remote_event(now, cancelled=True))
      self._preempt_remote("someone touched the comma screen")
      return events + physical

    for remote in self._drain_remote(now):
      if remote.kind == "down":
        if physical_busy:
          self._preempt_remote("the comma screen is in use")
          break
        self._remote_down = True
        self._remote_pos = MousePos(remote.x * self._width, remote.y * self._height)
        events.append(self._remote_event(now, pressed=True))
      elif not self._remote_down:
        continue  # the press never reached the UI; nothing to move, release or cancel
      elif remote.kind == "move":
        self._remote_pos = MousePos(remote.x * self._width, remote.y * self._height)
        events.append(self._remote_event(now))
      elif remote.kind == "up":
        self._remote_pos = MousePos(remote.x * self._width, remote.y * self._height)
        events.append(self._remote_event(now, released=True))
      else:
        events.append(self._remote_event(now, cancelled=True))
    return physical + events

  def _remote_event(self, now: float, pressed: bool = False, released: bool = False, cancelled: bool = False) -> MouseEvent:
    """A slot-0 event at the remote pointer. Coordinates arrive normalized to
    the captured image, which is the whole logical canvas."""
    down = not (released or cancelled)
    if not down:
      self._remote_down = False
    return MouseEvent(self._remote_pos, 0, pressed, released, down, now, cancelled)

  def _drain_remote(self, now: float) -> list:
    stream = self._ui_stream
    if stream is None:
      # The streamer stopped under a held remote press: withdraw it.
      return [_REMOTE_WITHDRAWN] if self._remote_down else []
    try:
      stream.set_control_allowed(self._ui_stream_control_allowed, self._ui_stream_control_reason)
      return stream.drain_control(now)
    except Exception as exc:
      cloudlog.error(f"UI streamer input failed: {exc}")
      return [_REMOTE_WITHDRAWN] if self._remote_down else []

  def _preempt_remote(self, reason: str) -> None:
    self._remote_down = False
    stream = self._ui_stream
    if stream is not None:
      try:
        stream.preempt_control(reason)
      except Exception as exc:
        cloudlog.error(f"UI streamer input failed: {exc}")

  def ui_stream_wants_frames(self) -> bool:
    """True while a browser is actually pulling images.

    The screen power policy uses this to keep rendering without waking the
    display: a watcher needs frames, not a lit panel. Telemetry-only interest
    deliberately does not count, since it needs no rendering.
    """
    stream = self._ui_stream
    return (stream is not None and stream.image_demand_active()) or self.starpilot_auto_wants_frames()

  def starpilot_auto_wants_frames(self) -> bool:
    """True while starpilot_autod is projecting and asking for frames."""
    producer = self._starpilot_auto_producer()
    try:
      return producer is not None and producer.demand_active()
    except Exception:
      return False

  def _starpilot_auto_producer(self):
    if not self._starpilot_auto_enabled:
      return None
    if self._starpilot_auto_frame_producer is None and not self._starpilot_auto_failed:
      try:
        from openpilot.starpilot.system.starpilot_auto.frame_source import FrameProducer
        self._starpilot_auto_frame_producer = FrameProducer()
      except Exception as exc:
        self._starpilot_auto_failed = True
        cloudlog.error(f"Starpilot Auto frame source unavailable: {exc}")
    return self._starpilot_auto_frame_producer

  def _ensure_starpilot_auto_texture(self) -> None:
    """Allocate the main render texture before drawing when projection needs frames.

    Render thread only, between frames, exactly like a Live UI start. Reclaim
    projection-only resources when the master switch is disabled.
    """
    if not self._starpilot_auto_enabled:
      if self._starpilot_auto_frame_producer is not None:
        self._starpilot_auto_frame_producer.close()
        self._starpilot_auto_frame_producer = None
      self._release_starpilot_auto_texture()
      # Only reclaim a main texture allocated for projection. Live UI can take
      # ownership while connected; its capture and rendering must keep working.
      if self._starpilot_auto_owns_render_texture and self._ui_stream is None and not self._ui_stream_pending:
        self._unload_render_texture(self._render_texture)
        self._render_texture = None
        self._starpilot_auto_owns_render_texture = False
      return
    if self._render_texture is not None or not self.starpilot_auto_wants_frames():
      return
    render_texture = rl.load_render_texture(self._render_texture_width, self._render_texture_height)
    texture = getattr(render_texture, "texture", None)
    if texture is None or getattr(texture, "id", 0) == 0:
      self._unload_render_texture(render_texture)
      self._starpilot_auto_failed = True
      self._starpilot_auto_frame_producer = None
      cloudlog.error("Starpilot Auto capture disabled: render texture allocation failed")
      return
    rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
    self._render_texture = render_texture
    self._starpilot_auto_owns_render_texture = True

  def _capture_starpilot_auto_frame(self) -> None:
    """Scale the finished frame into the negotiated video geometry and publish it.

    The GPU letterboxes the UI into the requested content rectangle, so the
    readback is already the encoder's size, top-down and undistorted. Any
    failure disables projection capture only; the native UI keeps rendering.
    """
    if not self._starpilot_auto_enabled:
      return
    producer = self._starpilot_auto_frame_producer
    if producer is None or self._render_texture is None:
      return
    try:
      now_ns = time.monotonic_ns()
      request = producer.pending_request(now_ns / 1e9)
      if request is None or not producer.due(request, now_ns):
        return
      target = self._starpilot_auto_texture
      if target is None or target.texture.width != request.width or target.texture.height != request.height:
        self._release_starpilot_auto_texture()
        target = rl.load_render_texture(request.width, request.height)
        if getattr(getattr(target, "texture", None), "id", 0) == 0:
          raise RuntimeError(f"{request.width}x{request.height} projection texture unavailable")
        rl.set_texture_filter(target.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
        self._starpilot_auto_texture = target
      rl.begin_texture_mode(target)
      rl.clear_background(rl.BLACK)
      x, y, w, h = request.content(self._render_texture_width, self._render_texture_height)
      rl.draw_texture_pro(self._render_texture.texture,
                          rl.Rectangle(0, 0, float(self._render_texture_width), float(self._render_texture_height)),
                          rl.Rectangle(float(x), float(y), float(w), float(h)), rl.Vector2(0, 0), 0.0, rl.WHITE)
      rl.end_texture_mode()
      image = rl.load_image_from_texture(target.texture)
      try:
        if image.format != rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8 or \
           (image.width, image.height) != (request.width, request.height):
          raise RuntimeError(f"unexpected projection readback {image.width}x{image.height} format {image.format}")
        size = request.width * request.height * 4
        producer.publish(request, rl.ffi.buffer(image.data, size), now_ns)
      finally:
        rl.unload_image(image)
    except Exception as exc:
      self._starpilot_auto_failed = True
      self._starpilot_auto_frame_producer = None
      self._release_starpilot_auto_texture()
      cloudlog.error(f"Starpilot Auto capture disabled: {exc}")

  def _release_starpilot_auto_texture(self) -> None:
    texture, self._starpilot_auto_texture = self._starpilot_auto_texture, None
    if texture is not None and rl.is_window_ready():
      self._unload_render_texture(texture)

  def _start_pending_ui_stream(self) -> None:
    """Honour a pending start request. Render thread only.

    Allocates the main render texture if this device does not already draw
    through one. Every failure -- configuration, GL, bind or thread start --
    is contained here: it disables streaming, records a reason for Galaxy and
    leaves the ordinary UI exactly as it was. Nothing from this path may reach
    the render loop.
    """
    if not self._ui_stream_pending:
      return
    self._ui_stream_pending = False
    if self._ui_stream is not None:
      return

    try:
      self._start_ui_stream()
    except Exception as exc:
      # A GL, allocation or thread-start failure must not terminate rendering.
      self._fail_ui_stream(f"startup failed: {exc}")

  def _fail_ui_stream(self, reason: str) -> None:
    """Record why streaming is unavailable and log it once."""
    self._ui_stream_error = reason
    cloudlog.error(f"UI streamer unavailable: {reason}")

  def _start_ui_stream(self) -> None:
    """Bind, allocate and serve. Only called by :meth:`_start_pending_ui_stream`."""
    try:
      from openpilot.system.ui.lib import ui_stream as ui_stream_module
    except Exception as exc:
      self._fail_ui_stream(f"import failed: {exc}")
      return

    # Resolve configuration before touching GL or binding, so STREAM=0 costs
    # nothing and an invalid configuration cannot leave a half-built streamer.
    try:
      default_fps = ui_stream_module.DEFAULT_FPS if self.big_ui() else ui_stream_module.COMPACT_UI_FPS
      config = ui_stream_module.parse_config(os.environ, default_fps)
    except ui_stream_module.StreamConfigError as exc:
      self._fail_ui_stream(str(exc))
      return
    if config is None:
      self._ui_stream_error = ""  # STREAM=0 is a deliberate kill switch, not a failure
      return

    # Opening Live UI opts into the texture path on every device, including
    # MICI. This runs between frames on the render thread, before drawing into
    # the new target. Keep it until window close to avoid repeated composition
    # switches when viewers disconnect and return.
    allocated_texture = False
    render_texture = None
    if self._render_texture is None:
      render_texture = rl.load_render_texture(self._render_texture_width, self._render_texture_height)
      texture = getattr(render_texture, "texture", None)
      if texture is None or getattr(texture, "id", 0) == 0:
        self._unload_render_texture(render_texture)
        self._fail_ui_stream("render texture allocation failed")
        return
      try:
        rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      except Exception as exc:
        self._unload_render_texture(render_texture)
        self._fail_ui_stream(f"render texture filtering failed: {exc}")
        return
      allocated_texture = True

    try:
      stream = ui_stream_module.UiStream(config)
    except OSError as exc:
      if allocated_texture:
        self._unload_render_texture(render_texture)
      self._fail_ui_stream(f"cannot bind {config.bind}:{config.port}: {exc}")
      return

    # Publish the streamer before serve(): a thread-start failure then rolls
    # back through stop_ui_stream(), which closes the listener it already owns.
    if allocated_texture:
      self._render_texture = render_texture
    self._ui_stream = stream
    self._ui_stream_owns_texture = allocated_texture
    self._stream_paused = False
    try:
      stream.serve()
    except Exception as exc:
      self.stop_ui_stream()
      self._fail_ui_stream(f"cannot start streamer threads: {exc}")
      return
    self._ui_stream_error = ""
    cloudlog.warning(f"UI streamer started on {config} (texture allocated: {allocated_texture})")

  @staticmethod
  def _unload_render_texture(render_texture) -> None:
    """Best-effort rollback of a texture allocated for streaming only."""
    if render_texture is None:
      return
    try:
      rl.unload_render_texture(render_texture)
    except Exception as exc:  # pragma: no cover - defensive
      cloudlog.error(f"UI streamer: render texture rollback failed: {exc}")

  def _read_stream_texture(self, buffer: bytearray) -> bool:
    """Render-thread readback of the main UI texture into owned storage."""
    return self._read_texture_into(self._render_texture.texture, buffer)

  def _read_scaled_stream_texture(self, buffer: bytearray) -> bool:
    """Downscale the UI into the stream texture on the GPU, then read it back.

    Reading back only the encoded size moves a fraction of the bytes across
    the GPU->CPU readback (which blocks the render thread) and leaves the
    worker nothing to resize. Drawing with a positive source height also
    lands the rows top-down, so the worker skips its vertical flip.
    """
    target = self._ui_stream_texture
    width, height = target.texture.width, target.texture.height
    rl.begin_texture_mode(target)
    rl.clear_background(rl.BLACK)
    rl.draw_texture_pro(self._render_texture.texture,
                        rl.Rectangle(0, 0, float(self._render_texture_width), float(self._render_texture_height)),
                        rl.Rectangle(0, 0, float(width), float(height)), rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.end_texture_mode()
    return self._read_texture_into(target.texture, buffer)

  def _ensure_stream_texture(self, width: int, height: int) -> bool:
    """Keep a ``width`` x ``height`` render texture for GPU downscaling.

    Returns ``False`` when it cannot be allocated; the caller then falls back
    to a full-size readback with a CPU resize, which is slower but correct.
    """
    current = self._ui_stream_texture
    if current is not None and current.texture.width == width and current.texture.height == height:
      return True
    self._release_stream_texture()
    render_texture = rl.load_render_texture(width, height)
    texture = getattr(render_texture, "texture", None)
    if texture is None or getattr(texture, "id", 0) == 0:
      self._unload_render_texture(render_texture)
      cloudlog.error(f"UI streamer: {width}x{height} scaling texture unavailable, using CPU resize")
      return False
    self._ui_stream_texture = render_texture
    return True

  def _release_stream_texture(self) -> None:
    render_texture = self._ui_stream_texture
    self._ui_stream_texture = None
    if render_texture is not None and rl.is_window_ready():
      self._unload_render_texture(render_texture)

  def _read_texture_into(self, source: rl.Texture, buffer: bytearray) -> bool:
    image = None
    try:
      image = rl.load_image_from_texture(source)
      if image is None or image.data == rl.ffi.NULL or image.width <= 0 or image.height <= 0:
        return False
      if image.format != rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8:
        self._ui_stream.fail_capture(f"unsupported texture format: {image.format}")
        return False
      nbytes = image.width * image.height * 4
      if nbytes != len(buffer):
        # Dimensions disagree with _render_texture_width/_height. Retrying every
        # pacing interval would fail forever, so disable once and log.
        self._ui_stream.fail_capture(
          f"readback size mismatch: {image.width}x{image.height} needs {nbytes} bytes, buffer is {len(buffer)}")
        return False
      buffer[:nbytes] = rl.ffi.buffer(image.data, nbytes)
      return True
    finally:
      if image is not None:
        rl.unload_image(image)

  def _capture_stream_frame(self) -> None:
    """Idle-shutdown check plus one paced capture. Render thread only."""
    self._service_ui_stream(capture=True)

  def _service_ui_stream(self, capture: bool) -> None:
    """Run the streamer's per-frame housekeeping.

    Called on every render-loop iteration, including the ones skipped because
    the screen is off: idle shutdown must not wait for the display to wake, or
    a request that never got a viewer would keep its listener and worker alive
    indefinitely. ``capture=False`` is that skipped-frame case -- there is no
    new frame to read back.
    """
    stream = self._ui_stream
    if stream is None:
      return
    self._mark_progress("gui_app.before_stream_capture")
    try:
      # Nobody has wanted this for a while: give the sockets, threads and
      # buffers back until the next request.
      if stream.self_stop_due():
        cloudlog.warning("UI streamer stopping: idle with no viewers")
        self.stop_ui_stream()
      elif capture and self._render_texture is not None:
        self._capture_into(stream)
    except Exception as exc:
      cloudlog.error(f"UI streamer disabled after capture error: {exc}")
      self.stop_ui_stream()
    self._mark_progress("gui_app.after_stream_capture")

  def _capture_into(self, stream) -> None:
    source = (self._render_texture_width, self._render_texture_height)
    width, height = stream.output_size(*source)
    if (width, height) != source and self._ui_stream_texture is None and not self._ui_stream_scale_failed:
      self._ui_stream_scale_failed = not self._ensure_stream_texture(width, height)
    if (width, height) != source and self._ui_stream_texture is not None:
      stream.maybe_capture(time.monotonic(), width, height, self._read_scaled_stream_texture,
                           bottom_up=False, source_size=source)
    else:
      stream.maybe_capture(time.monotonic(), *source, self._read_stream_texture)

  def _record_frame(self) -> None:
    """Hand one rendered frame to the ffmpeg writer thread.

    No-ops when recording was disabled because the render texture could not be
    allocated, so a texture failure never crashes the render loop.
    """
    if self._render_texture is None or self._ffmpeg_queue is None:
      return
    image = rl.load_image_from_texture(self._render_texture.texture)
    data_size = image.width * image.height * 4
    data = bytes(rl.ffi.buffer(image.data, data_size))
    self._ffmpeg_queue.put(data)  # Async write via background thread
    rl.unload_image(image)

  def stop_ui_stream(self) -> None:
    """Idempotent streamer shutdown. Safe even if the window is already gone.

    A render texture allocated for streaming is deliberately retained until the
    window closes (§4): tearing it down would be a second live composition
    switch, and close() unloads it anyway.
    """
    stream = self._ui_stream
    self._ui_stream = None
    self._ui_stream_pending = False
    self._stream_paused = False
    if stream is not None:
      # A held remote press is withdrawn by the next frame's arbitration.
      stream.stop()
    # Unlike the main texture this one is only read, never composited, so
    # freeing it costs nothing visible; it is small and cheap to re-create.
    self._release_stream_texture()
    self._ui_stream_scale_failed = False

  def stream_telemetry_due(self, now: float) -> bool:
    stream = self._ui_stream
    return stream is not None and stream.telemetry_due(now)

  def publish_stream_telemetry(self, payload: bytes) -> None:
    stream = self._ui_stream
    if stream is not None:
      stream.set_telemetry(payload)

  def close_ffmpeg(self):
    if self._ffmpeg_thread is not None:
      # Signal thread to stop, send sentinel, then wait for it to drain
      self._ffmpeg_stop_event.set()
      self._ffmpeg_queue.put(None)
      self._ffmpeg_thread.join(timeout=30)

    if self._ffmpeg_proc is not None:
      self._ffmpeg_proc.stdin.flush()
      self._ffmpeg_proc.stdin.close()
      try:
        self._ffmpeg_proc.wait(timeout=30)
      except subprocess.TimeoutExpired:
        self._ffmpeg_proc.terminate()
        self._ffmpeg_proc.wait()

  def close(self):
    # Stop the streamer first so cleanup runs even if the window is already gone.
    self.stop_ui_stream()

    if not rl.is_window_ready():
      return

    for texture in self._textures.values():
      rl.unload_texture(texture)
    self._textures = {}

    for render_texture in self._cached_render_textures.values():
      rl.unload_render_texture(render_texture)
    self._cached_render_textures = {}
    self._pending_render_textures = {}

    for font in self._fonts.values():
      rl.unload_font(font)
    self._fonts = {}

    self._release_starpilot_auto_texture()

    if self._render_texture is not None:
      rl.unload_render_texture(self._render_texture)
      self._render_texture = None

    if self._burn_in_shader:
      rl.unload_shader(self._burn_in_shader)
      self._burn_in_shader = None

    if self._white_luminance_shader:
      rl.unload_shader(self._white_luminance_shader)
      self._white_luminance_shader = None

    self._mouse.stop()

    self.close_ffmpeg()

    rl.close_window()

  @property
  def mouse_events(self) -> list[MouseEvent]:
    return self._mouse_events

  @property
  def last_mouse_event(self) -> MouseEvent:
    return self._last_mouse_event

  def render(self):
    try:
      if self._profile_render_frames > 0:
        import cProfile
        self._render_profiler = cProfile.Profile()
        self._render_profile_start_time = time.monotonic()
        self._render_profiler.enable()

      while not (self._window_close_requested or rl.window_should_close()):
        frame_start = time.monotonic()
        cpu_start = time.thread_time()
        self._mark_progress("gui_app.loop_start")
        self._apply_render_mode()
        if PC:
          # Thread is not used on PC, need to manually add mouse events.
          self._mouse._handle_mouse_event()

        # Store all mouse events for the current frame
        self._mouse_events = self._arbitrate_input(self._mouse.get_events(), time.monotonic())
        if len(self._mouse_events) > 0:
          self._last_mouse_event = self._mouse_events[-1]
          self.request_high_fps()

        # Skip rendering when screen is off
        if not self._should_render:
          self._mark_progress("gui_app.skip_render")
          # Bind a requested streamer even now. The screen policy only resumes
          # rendering once a viewer is pulling images, and a viewer can only
          # connect to a bound listener, so deferring the start until the
          # display wakes would deadlock the two against each other.
          if self._ui_stream_pending:
            self._mark_progress("gui_app.before_stream_start")
            self._start_pending_ui_stream()
            self._mark_progress("gui_app.after_stream_start")
          if self._ui_stream is not None and not self._stream_paused:
            self._stream_paused = True
            self._ui_stream.pause()
          self._service_ui_stream(capture=False)
          if PC:
            rl.poll_input_events()
          time.sleep(1 / self._target_fps)
          yield False
          continue

        if self._ui_stream is not None and self._stream_paused:
          self._stream_paused = False
          self._ui_stream.resume()

        # Honour a pending start before the frame is drawn, so a texture
        # allocated now receives this frame and the first capture is valid.
        if self._ui_stream_pending:
          self._mark_progress("gui_app.before_stream_start")
          self._start_pending_ui_stream()
          self._mark_progress("gui_app.after_stream_start")
        self._ensure_starpilot_auto_texture()

        if self._render_texture:
          self._mark_progress("gui_app.before_begin_texture_mode")
          rl.begin_texture_mode(self._render_texture)
          self._mark_progress("gui_app.after_begin_texture_mode")
          self._mark_progress("gui_app.before_clear_background")
          rl.clear_background(rl.BLACK)
          self._mark_progress("gui_app.after_clear_background")
        else:
          self._mark_progress("gui_app.before_begin_drawing")
          rl.begin_drawing()
          self._mark_progress("gui_app.after_begin_drawing")
          self._mark_progress("gui_app.before_clear_background")
          rl.clear_background(rl.BLACK)
          self._mark_progress("gui_app.after_clear_background")

        render_scale_x = self._scale * (self._pixel_scale_x if self._render_texture else 1.0)
        render_scale_y = self._scale * (self._pixel_scale_y if self._render_texture else 1.0)
        needs_render_scale = render_scale_x != 1.0 or render_scale_y != 1.0
        direct_burn_in_shift = self._burn_in_shift() if self._render_texture is None else (0, 0)
        needs_render_transform = needs_render_scale or direct_burn_in_shift != (0, 0)
        if needs_render_transform:
          rl.rl_push_matrix()
          if needs_render_scale:
            rl.rl_scalef(render_scale_x, render_scale_y, 1.0)
          if direct_burn_in_shift != (0, 0):
            rl.rl_translatef(direct_burn_in_shift[0], direct_burn_in_shift[1], 0.0)

        # Allow a Widget to still run a function regardless of the stack depth
        self._mark_progress("gui_app.before_nav_ticks")
        for tick in self._nav_stack_ticks:
          tick()
        self._mark_progress("gui_app.after_nav_ticks")

        # Only render top widgets
        self._mark_progress("gui_app.before_widget_render")
        viewport = rl.Rectangle(0, 0, self.width, self.height)
        widgets = self._nav_stack[-self._nav_stack_widgets_to_render:]
        if len(widgets) > 1 and widgets[-1].covers_background(viewport):
          widgets = widgets[-1:]
        for widget in widgets:
          widget.render(rl.Rectangle(0, 0, self.width, self.height))
        self._mark_progress("gui_app.after_widget_render")

        self._mark_progress("gui_app.frame_ready")
        draw_end = time.monotonic()
        yield True
        update_end = time.monotonic()

        if needs_render_transform:
          rl.rl_pop_matrix()

        if self._render_texture:
          self._mark_progress("gui_app.end_texture_mode")
          rl.end_texture_mode()
          self._mark_progress("gui_app.before_present_begin_drawing")
          rl.begin_drawing()
          self._mark_progress("gui_app.after_present_begin_drawing")
          self._mark_progress("gui_app.before_present_clear_background")
          rl.clear_background(rl.BLACK)
          self._mark_progress("gui_app.after_present_clear_background")
          src_rect = rl.Rectangle(0, 0, float(self._render_texture_width), -float(self._render_texture_height))
          shift_x, shift_y = self._burn_in_shift()
          dst_rect = rl.Rectangle(shift_x, shift_y, float(self._scaled_width), float(self._scaled_height))
          texture = self._render_texture.texture
          if texture:
            self._mark_progress("gui_app.before_present_draw_texture")
            if BURN_IN_MODE and self._burn_in_shader:
              rl.begin_shader_mode(self._burn_in_shader)
              rl.draw_texture_pro(texture, src_rect, dst_rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
              rl.end_shader_mode()
            elif self._white_luminance_shader:
              rl.begin_shader_mode(self._white_luminance_shader)
              rl.draw_texture_pro(texture, src_rect, dst_rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
              rl.end_shader_mode()
            else:
              rl.draw_texture_pro(texture, src_rect, dst_rect, rl.Vector2(0, 0), 0.0, rl.WHITE)
            self._mark_progress("gui_app.after_present_draw_texture")

        if self._show_fps:
          rl.draw_fps(10, 10)

        if self._show_touches:
          self._draw_touch_points()

        if self._grid_size > 0:
          self._draw_grid()

        self._mark_progress("gui_app.before_end_drawing")
        rl.end_drawing()
        self._mark_progress("gui_app.after_end_drawing")
        present_end = time.monotonic()
        self._populate_render_texture_cache()

        if RECORD:
          self._record_frame()

        self._capture_stream_frame()
        self._mark_progress("gui_app.before_starpilot_auto_capture")
        self._capture_starpilot_auto_frame()
        self._mark_progress("gui_app.after_starpilot_auto_capture")

        self.frame_timing = FrameTiming(
          (time.monotonic() - frame_start) * 1000,
          (time.thread_time() - cpu_start) * 1000,
          (draw_end - frame_start) * 1000,
          (update_end - draw_end) * 1000,
          (present_end - update_end) * 1000,
        )
        self._monitor_fps()
        self._frame += 1
        self._mark_progress("gui_app.loop_idle")

        if self._profile_render_frames > 0 and self._frame >= self._profile_render_frames:
          self._output_render_profile()
    except KeyboardInterrupt:
      pass

  def _burn_in_shift(self, now: float | None = None) -> tuple[float, float]:
    if not BURN_IN_PREVENTION or BURN_IN_SHIFT_PIXELS == 0:
      return 0.0, 0.0

    elapsed = (time.monotonic() if now is None else now) - self._burn_in_start_time
    elapsed = max(0.0, elapsed)
    pattern_count = len(BURN_IN_SHIFT_PATTERN)
    cycle_elapsed = elapsed % (BURN_IN_SHIFT_INTERVAL * pattern_count)
    pattern_index = int(cycle_elapsed // BURN_IN_SHIFT_INTERVAL)
    segment_elapsed = cycle_elapsed - pattern_index * BURN_IN_SHIFT_INTERVAL

    # Blend into the next position at the end of each interval. This keeps the
    # burn-in protection active without teleporting the entire UI by two pixels.
    transition_start = BURN_IN_SHIFT_INTERVAL - BURN_IN_SHIFT_TRANSITION_SECONDS
    transition = min(1.0, max(0.0, (segment_elapsed - transition_start) / BURN_IN_SHIFT_TRANSITION_SECONDS))
    start_x, start_y = BURN_IN_SHIFT_PATTERN[pattern_index]
    end_x, end_y = BURN_IN_SHIFT_PATTERN[(pattern_index + 1) % pattern_count]
    x = start_x + (end_x - start_x) * transition
    y = start_y + (end_y - start_y) * transition
    return x * BURN_IN_SHIFT_PIXELS, y * BURN_IN_SHIFT_PIXELS

  def font(self, font_weight: FontWeight = FontWeight.NORMAL) -> rl.Font:
    return self._fonts[font_weight]

  @property
  def width(self):
    return self._width

  @property
  def height(self):
    return self._height

  def _load_fonts(self):
    for font_weight_file in FontWeight:
      with as_file(FONT_DIR) as fspath:
        fnt_path = fspath / font_weight_file
        font = rl.load_font(fnt_path.as_posix())
        if font_weight_file != FontWeight.UNIFONT:
          rl.gen_texture_mipmaps(font.texture)
          rl.set_texture_filter(font.texture, rl.TextureFilter.TEXTURE_FILTER_TRILINEAR)
        self._fonts[font_weight_file] = font
    rl.gui_set_font(self._fonts[FontWeight.NORMAL])

  def _set_styles(self):
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiControlProperty.BORDER_WIDTH, 0)
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiDefaultProperty.TEXT_SIZE, DEFAULT_TEXT_SIZE)
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiDefaultProperty.BACKGROUND_COLOR, rl.color_to_int(rl.BLACK))
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiControlProperty.TEXT_COLOR_NORMAL, rl.color_to_int(DEFAULT_TEXT_COLOR))
    rl.gui_set_style(rl.GuiControl.DEFAULT, rl.GuiControlProperty.BASE_COLOR_NORMAL, rl.color_to_int(rl.Color(50, 50, 50, 255)))

  def _patch_text_functions(self):
    # Wrap pyray text APIs to apply a global text size scale.
    if not hasattr(rl, "_orig_draw_text_ex"):
      rl._orig_draw_text_ex = rl.draw_text_ex

    def _draw_text_ex_scaled(font, text, position, font_size, spacing, tint):
      font = font_fallback(font)
      return rl._orig_draw_text_ex(font, text, position, font_size * FONT_SCALE, spacing, tint)

    rl.draw_text_ex = _draw_text_ex_scaled

  def _patch_scissor_mode(self):
    if not hasattr(rl, "_orig_begin_scissor_mode"):
      rl._orig_begin_scissor_mode = rl.begin_scissor_mode

    scale_x = self._scale * (self._pixel_scale_x if self._render_texture else 1.0)
    scale_y = self._scale * (self._pixel_scale_y if self._render_texture else 1.0)
    if scale_x == 1.0 and scale_y == 1.0:
      rl.begin_scissor_mode = rl._orig_begin_scissor_mode
      return

    def _begin_scissor_mode_scaled(x, y, width, height):
      return rl._orig_begin_scissor_mode(
        int(x * scale_x), int(y * scale_y),
        int(math.ceil(width * scale_x)), int(math.ceil(height * scale_y)))

    rl.begin_scissor_mode = _begin_scissor_mode_scaled

  def _set_log_callback(self):
    ffi_libc = cffi.FFI()
    ffi_libc.cdef("""
      int vasprintf(char **strp, const char *fmt, void *ap);
      void free(void *ptr);
    """)
    libc = ffi_libc.dlopen(None)

    @rl.ffi.callback("void(int, char *, void *)")
    def trace_log_callback(log_level, text, args):
      try:
        text_addr = int(rl.ffi.cast("uintptr_t", text))
        args_addr = int(rl.ffi.cast("uintptr_t", args))
        text_libc = ffi_libc.cast("char *", text_addr)
        args_libc = ffi_libc.cast("void *", args_addr)

        out = ffi_libc.new("char **")
        if libc.vasprintf(out, text_libc, args_libc) >= 0 and out[0] != ffi_libc.NULL:
          text_str = ffi_libc.string(out[0]).decode("utf-8", "replace")
          libc.free(out[0])
        else:
          text_str = rl.ffi.string(text).decode("utf-8", "replace")
      except Exception as e:
        text_str = f"[Log decode error: {e}]"

      if log_level == rl.TraceLogLevel.LOG_ERROR:
        cloudlog.error(f"raylib: {text_str}")
      elif log_level == rl.TraceLogLevel.LOG_WARNING:
        cloudlog.warning(f"raylib: {text_str}")
      elif log_level == rl.TraceLogLevel.LOG_INFO:
        cloudlog.info(f"raylib: {text_str}")
      elif log_level == rl.TraceLogLevel.LOG_DEBUG:
        cloudlog.debug(f"raylib: {text_str}")
      else:
        cloudlog.error(f"raylib: Unknown level {log_level}: {text_str}")

    # ensure we get all the logs forwarded to us
    rl.set_trace_log_level(rl.TraceLogLevel.LOG_DEBUG)

    # Store callback reference
    self._trace_log_callback = trace_log_callback
    rl.set_trace_log_callback(self._trace_log_callback)

  def _monitor_fps(self):
    fps = rl.get_fps()

    # Log FPS drop below threshold at regular intervals
    if fps < self._target_fps * FPS_DROP_THRESHOLD:
      current_time = time.monotonic()
      if current_time - self._last_fps_log_time >= FPS_LOG_INTERVAL:
        timing = self.frame_timing
        cloudlog.warning(f"FPS dropped below {self._target_fps}: {fps} " +
                         f"(frame={timing.frame_ms:.1f}ms cpu={timing.cpu_ms:.1f}ms " +
                         f"draw={timing.draw_ms:.1f}ms update={timing.update_ms:.1f}ms present={timing.present_ms:.1f}ms)")
        self._last_fps_log_time = current_time

    # Strict mode: terminate UI if FPS drops too much
    if STRICT_MODE and fps < self._target_fps * FPS_CRITICAL_THRESHOLD:
      cloudlog.error(f"FPS dropped critically below {fps}. Shutting down UI.")
      self.close_ffmpeg()
      os._exit(1)

  def _draw_touch_points(self):
    current_time = time.monotonic()

    for mouse_event in self._mouse_events:
      if mouse_event.left_pressed:
        self._mouse_history.clear()
      self._mouse_history.append(MousePosWithTime(mouse_event.pos.x * self._scale, mouse_event.pos.y * self._scale, current_time))

    # Remove old touch points that exceed the timeout
    while self._mouse_history and (current_time - self._mouse_history[0].t) > TOUCH_HISTORY_TIMEOUT:
      self._mouse_history.popleft()

    if self._mouse_history:
      mouse_pos = self._mouse_history[-1]
      rl.draw_circle(int(mouse_pos.x), int(mouse_pos.y), 15, rl.RED)
      for idx, mouse_pos in enumerate(self._mouse_history):
        perc = idx / len(self._mouse_history)
        color = rl.Color(min(int(255 * (1.5 - perc)), 255), int(min(255 * (perc + 0.5), 255)), 50, 255)
        rl.draw_circle(int(mouse_pos.x), int(mouse_pos.y), 5, color)

  def _draw_grid(self):
    grid_color = rl.Color(60, 60, 60, 255)
    # Draw vertical lines
    x = 0
    while x <= self._scaled_width:
      rl.draw_line(x, 0, x, self._scaled_height, grid_color)
      x += self._grid_size
    # Draw horizontal lines
    y = 0
    while y <= self._scaled_height:
      rl.draw_line(0, y, self._scaled_width, y, grid_color)
      y += self._grid_size

  def _output_render_profile(self):
    import io
    import pstats

    self._render_profiler.disable()
    elapsed_ms = (time.monotonic() - self._render_profile_start_time) * 1e3
    avg_frame_time = elapsed_ms / self._frame if self._frame > 0 else 0

    stats_stream = io.StringIO()
    pstats.Stats(self._render_profiler, stream=stats_stream).sort_stats("cumtime").print_stats(PROFILE_STATS)
    print("\n=== Render loop profile ===")
    print(stats_stream.getvalue().rstrip())

    green = "\033[92m"
    reset = "\033[0m"
    print(f"\n{green}Rendered {self._frame} frames in {elapsed_ms:.1f} ms{reset}")
    print(f"{green}Average frame time: {avg_frame_time:.2f} ms ({1000/avg_frame_time:.1f} FPS){reset}")
    sys.exit(0)

  def _calculate_auto_scale(self) -> float:
    if os.getenv("SP_HEADLESS_TEST") == "1":
      return 1.0

     # Create temporary window to query monitor info
    rl.init_window(1, 1, "")
    w, h = rl.get_monitor_width(0), rl.get_monitor_height(0)
    rl.close_window()

    if w == 0 or h == 0 or (w >= self._width and h >= self._height):
      return 1.0

    # Apply 0.95 factor for window decorations/taskbar margin
    return max(0.3, min(w / self._width, h / self._height) * 0.95)

  @staticmethod
  def _default_width() -> int:
    return 2160 if GuiApplication.big_ui() else 536

  @staticmethod
  def _default_height() -> int:
    return 1080 if GuiApplication.big_ui() else 240

  @staticmethod
  def big_ui() -> bool:
    return HARDWARE.get_device_type() in ('tici', 'tizi') or BIG_UI


gui_app = GuiApplication()
