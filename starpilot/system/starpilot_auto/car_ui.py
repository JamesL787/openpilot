"""Car-sized StarPilot UI for Starpilot Auto, rendered offscreen in its own process.

The comma four's own screen uses the compact UI. For the car, this process
renders the car's own landscape StarPilot interface (ui/: road camera, path, HUD,
alerts, sidebar, settings; built on the comma 3X widgets but never changing the
3X's own screens) at the car's resolution in an EGL pbuffer, without a window,
display power, touch hardware or publishers. Frames
go to starpilot_autod through the same bounded shared-memory slot as mirroring,
and car touches arrive as datagrams. Offroad every touch works. Onroad the driving
view and map ignore touches; only the small quick-menu button (Navigate, end route,
home screen, back to driving, go offroad), the map's compass button (north-up or
heading-up) and the screens the menu opens accept them. Destinations are
set on one Navigate screen (car_navigate.py), onroad only below 10 mph of wheel speed.
How the drive is laid out (map beside the driving view, driving view only, map
only, map orientation, camera on or off) comes from car_screen.json, set in The
Galaxy and applied live.

Started and stopped by starpilot_autod; exits when demand stops or its parent dies.

Approach adapted from yummydirtx/openpilot ``tools/android_auto/native_renderer.py``
(MIT), pinned at 672a16f6183567c0ada53654f8527d97e1a483fa.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import signal
import sys
import time

from openpilot.starpilot.system.starpilot_auto.frame_source import (FLAG_ASYNC_READBACK, FLAG_NV12, FORMAT_NV12, FORMAT_RGBA,
                                                                  FrameProducer, FrameRequest, frame_bytes)
from openpilot.starpilot.system.starpilot_auto.gpu_nv12 import compose_rgba
from openpilot.starpilot.system.starpilot_auto.placement import RendererPlacement
from openpilot.starpilot.system.starpilot_auto.touch import DEFAULT_TOUCH_SOCKET, TouchEvent, TouchReceiver

# The comma's landscape UI is designed 1080 rows high. The car view lays out on a shorter
# canvas so an 800x480 head unit shrinks it 0.67x instead of 0.44x: text, lines and the
# driving view's widgets come out larger and crisper. The pane sizes below scale with it.
DESIGN_HEIGHT = 1080
LOGICAL_HEIGHT = 720
UI_SCALE = LOGICAL_HEIGHT / DESIGN_HEIGHT
MIN_LOGICAL_WIDTH = round(1600 * UI_SCALE)
STARTUP_DEMAND_WAIT = 15.0
NAV_SPLIT_MIN_WIDTH = round(1700 * UI_SCALE)  # logical width; narrower car screens keep the full driving view
NAV_SPLIT_FRACTION = 0.42
MAP_BORDER = 32  # physical pixels for motion between cached map redraws
HOME_ONROAD_TIMEOUT = 45.0  # back to the drive after this long untouched on the home screen
# A drive starts on the home screen, which stays up (no idle timeout) until a route starts,
# Drive view is tapped, a critical alert shows, or the car is past the Navigate speed lock.
STATE_REFRESH = 5.0
MAP_ONLY_BORDER = 14.0
STATUS_COLUMN_WIDTH = 300  # the comma's developer sidebar width
COMPASS_SIZE = 96.0
COMPASS_MARGIN = 24.0
COMPASS_TRIP_BAR_CLEARANCE = 44 + 96 + 20  # the trip bar's bottom gap, height, and a gap above it
STATS_INTERVAL = 10.0
GPU_SAMPLE_EVERY = 30  # only with STARPILOT_AUTO_GPU_TIMING=1; glFinish perturbs normal rendering
CAMERA_WAIT_STEP = 0.01    # s; keeps demand/stop checks responsive while waiting for the camera
CAMERA_MAX_GAP = 0.1       # s; a shown camera silent this long stops pacing (the encoder rate applies)

# Per-frame averages in render_stats. Wall-clock milliseconds except cpu_ms, the
# renderer thread's own CPU time: frame_ms well above cpu_ms means it was waiting
# (for its core, where it runs at SCHED_IDLE, or for the GPU driver), not working.
# gpu_ms, when explicitly enabled on every GPU_SAMPLE_EVERY-th frame, is how long the GPU
# still had to go after the CPU finished that frame.
STAT_KEYS = ("update_ms", "map_ms", "layout_ms", "map_draw_ms", "menu_ms", "compose_ms", "cache_ms", "convert_ms",
             "gpu_ms", "readback_ms", "readback_wait_ms", "publish_ms", "frame_ms", "cpu_ms")
DRAW_KEYS = ("layout_ms", "map_draw_ms", "menu_ms", "compose_ms", "cache_ms")  # the former draw_ms


# The value structs the layouts build every frame. Only these are touched: on the
# comma's cffi even reading .fields of an opaque raylib struct aborts the process.
FAST_STRUCTS = ("Vector2", "Vector3", "Vector4", "Rectangle", "Color", "Camera2D", "Matrix", "NPatchInfo")


def _has_pointer(ctype) -> bool:
  if ctype.kind == "pointer":
    return True
  if ctype.kind == "array":
    return _has_pointer(ctype.item)
  if ctype.kind == "struct":
    return any(_has_pointer(field.type) for _, field in ctype.fields or ())
  return False


def use_fast_struct_constructors(rl) -> list[str]:
  """Build pyray value structs (Vector2, Rectangle, Color, ...) with a plain ffi.new.

  pyray's generic constructor inspects every field on every call so it can
  handle pointer fields: about 15 us per struct on the comma, and the layouts
  build a few hundred per frame. A struct without pointers needs only ffi.new
  (about 3 us, identical bytes).
  """
  ffi = rl.ffi
  patched = []
  for name in FAST_STRUCTS:
    if getattr(getattr(rl, name, None), "__name__", "") != "func":
      continue  # missing, or no longer pyray's generated constructor
    try:
      ctype = ffi.typeof(name)
      ffi.sizeof(ctype)  # complete types only
    except Exception:
      continue
    if ctype.kind != "struct" or _has_pointer(ctype):
      continue
    pointer_type, new = ffi.typeof(f"{name} *"), ffi.new

    def construct(*args, _pointer_type=pointer_type, _new=new):
      return _new(_pointer_type, args)[0]

    construct.__name__ = f"fast_{name}"
    setattr(rl, name, construct)
    patched.append(name)
  return patched


class RenderStats:
  """Accumulates per-section frame times and reports averages every STATS_INTERVAL seconds."""

  def __init__(self, now: float):
    self.reset(now)

  def reset(self, now: float) -> None:
    self.started, self.frames = now, 0
    self.totals = dict.fromkeys(STAT_KEYS, 0.0)
    self.sampled: dict[str, int] = {}

  def add(self, key: str, seconds: float, sampled: bool = False) -> None:
    """``sampled``: measured on some frames only, so averaged over those."""
    self.totals[key] += seconds
    if sampled:
      self.sampled[key] = self.sampled.get(key, 0) + 1

  def frame_done(self, now: float, **extra) -> dict | None:
    self.frames += 1
    if now - self.started < STATS_INTERVAL:
      return None
    frames = self.frames
    report = {"event": "render_stats", "fps": round(frames / (now - self.started), 1),
              **{key: round(total * 1000 / max(1, self.sampled.get(key, frames)), 2) for key, total in self.totals.items()}}
    report["draw_ms"] = round(sum(report[key] for key in DRAW_KEYS), 2)
    report.update(extra)
    self.reset(now)
    return report


class NullPubMaster:
  """The comma's own UI already publishes uiDebug/bookmarkButton; a second publisher would collide."""

  def __init__(self, services, *args, **kwargs):
    self.services = services

  def send(self, *args, **kwargs) -> None:
    pass

  def wait_for_readers_to_update(self, *args, **kwargs) -> bool:
    return True

  def all_readers_updated(self, *args, **kwargs) -> bool:
    return True


def logical_size(request: FrameRequest) -> tuple[int, int, float, float]:
  """Logical UI size for the car's visible area, and the x/y scale to physical pixels."""
  visible_w, visible_h = request.width - request.margin_w, request.height - request.margin_h
  width = round(LOGICAL_HEIGHT * visible_w / visible_h)
  if width >= MIN_LOGICAL_WIDTH:
    return width, LOGICAL_HEIGHT, visible_w / width, visible_h / LOGICAL_HEIGHT
  # Narrower than about 3:2 (4:3, portrait): keep the minimum width and grow the height, so
  # both axes scale alike. Scaling them differently stretched the UI and misplaced clipping.
  height = round(MIN_LOGICAL_WIDTH * visible_h / visible_w)
  return MIN_LOGICAL_WIDTH, height, visible_w / MIN_LOGICAL_WIDTH, visible_h / height


class TouchInput:
  """Turn normalized car touches into the UI's MouseEvents, withdrawing them onroad."""

  def __init__(self, mouse_event, mouse_pos, logical_w: int, logical_h: int):
    self.MouseEvent, self.MousePos = mouse_event, mouse_pos
    self.logical_w, self.logical_h = logical_w, logical_h
    self.down = False
    self.pos = mouse_pos(0, 0)
    self.accepted = self.refused = 0

  def events(self, touches: list[TouchEvent], allowed: bool, now: float) -> list:
    result = []
    if self.down and not allowed:
      result.append(self._event(now, cancelled=True))
    for touch in touches:
      if touch.kind != "cancel":
        self.pos = self.MousePos(touch.x * self.logical_w, touch.y * self.logical_h)
      if touch.kind == "down":
        if not allowed:
          self.refused += 1
          continue
        if self.down:
          result.append(self._event(now, cancelled=True))
        self.down = True
        self.accepted += 1
        result.append(self._event(now, pressed=True))
      elif not self.down:
        continue
      elif touch.kind == "move":
        result.append(self._event(now))
      elif touch.kind == "up":
        result.append(self._event(now, released=True))
      else:
        result.append(self._event(now, cancelled=True))
    return result

  def _event(self, now: float, pressed: bool = False, released: bool = False, cancelled: bool = False):
    down = not (released or cancelled)
    if not down:
      self.down = False
    return self.MouseEvent(self.pos, 0, pressed, released, down, now, cancelled)


class CameraPacer:
  """Onroad, draw each frame of the camera on screen exactly once, as soon as it lands.

  The road cameras and the driving model run at 20 Hz. A 30 fps timer redraws
  every third frame for nothing and shows camera frames in an uneven 2-1
  cadence; a 20 fps timer drifts against the camera clock and periodically
  repeats one frame and skips the next. camerad hands the frame to VisionIPC
  before it publishes the matching CameraState, so waking on that message means
  CameraView's non-blocking recv already has the new frame.

  Only the shown camera's CameraState is subscribed, conflated and never
  deserialized: the pacer only needs to know that one arrived. When that camera
  goes quiet, it stops pacing and the encoder's frame rate applies again.
  """

  def __init__(self, sock_factory=None, stream_types=None):
    if sock_factory is None:
      from cereal import messaging

      def sock_factory(name):
        poller = messaging.Poller()
        return poller, messaging.sub_sock(name, poller=poller, conflate=True)
    if stream_types is None:
      from msgq.visionipc import VisionStreamType as stream_types
    self.state_for_stream = {int(stream_types.VISION_STREAM_ROAD): "roadCameraState",
                             int(stream_types.VISION_STREAM_WIDE_ROAD): "wideRoadCameraState",
                             int(stream_types.VISION_STREAM_DRIVER): "driverCameraState"}
    self._sock_factory = sock_factory
    self._socks: dict[str, tuple] = {}   # opened on first use, so an unshown camera costs nothing
    self._last_arrival: dict[str, float] = {}

  def wait(self, stream_type, now: float) -> bool:
    """True when a new frame of ``stream_type`` is ready, or when that camera is quiet; waits at most one step."""
    state = self.state_for_stream.get(int(stream_type))
    if state is None:
      return True
    if state not in self._socks:
      self._socks[state] = self._sock_factory(state)
    poller, sock = self._socks[state]
    quiet = now - self._last_arrival.get(state, float("-inf")) >= CAMERA_MAX_GAP
    # A quiet camera must not hold rendering back: just check whether it has resumed.
    arrived = bool(poller.poll(0 if quiet else int(CAMERA_WAIT_STEP * 1000))) and sock.receive(non_blocking=True) is not None
    if arrived:
      self._last_arrival[state] = now
    return arrived or quiet


def car_layout(settings: dict, started: bool, on_home: bool, width: int, height: int):
  """(main layout rect or None, map rect or None) in logical pixels.

  Offroad, and onroad once the driver has gone to the home screen, the main
  layout fills the screen. Onroad it follows The Galaxy's car screen settings.
  """
  import pyray as rl
  full = rl.Rectangle(0, 0, width, height)
  if not started or on_home:
    return full, None
  view = settings.get("onroad_view", "split")
  if view == "split" and width < NAV_SPLIT_MIN_WIDTH:
    view = "driving"
  if view == "driving":
    return full, None
  if view == "map":
    return None, full
  map_w = round(min(1100 * UI_SCALE, max(700 * UI_SCALE, width * NAV_SPLIT_FRACTION)))
  if settings.get("map_side") == "left":
    return rl.Rectangle(map_w, 0, width - map_w, height), rl.Rectangle(0, 0, map_w, height)
  return rl.Rectangle(0, 0, width - map_w, height), rl.Rectangle(width - map_w, 0, map_w, height)


def status_layout(settings: dict, main_rect, map_rect):
  """(main rect or None, map rect or None, status column) with the column carved out of the drive.

  The column sits at either edge, or in the split view between the driving view and the
  map. It takes its width from the driving view, or from the map when that is shown alone.
  """
  import pyray as rl
  panes = sorted(((name, rect) for name, rect in (("main", main_rect), ("map", map_rect)) if rect is not None),
                 key=lambda pane: pane[1].x)
  view = "split" if len(panes) == 2 else "driving" if main_rect is not None else "map"
  position = settings.get(f"status_position_{view}", "right")
  names = [name for name, _ in panes]
  index = {"left": 0, "center": 1}.get(position, len(names))
  widths = {name: rect.width for name, rect in panes}
  widths["main" if main_rect is not None else "map"] -= STATUS_COLUMN_WIDTH
  widths["status"] = STATUS_COLUMN_WIDTH
  first = panes[0][1]
  x, placed = first.x, {}
  for name in names[:index] + ["status"] + names[index:]:
    placed[name] = rl.Rectangle(x, first.y, widths[name], first.height)
    x += widths[name]
  return placed.get("main"), placed.get("map"), placed["status"]


def compass_rect(map_rect, lift: float = 0.0):
  """The map's orientation button: bottom-right of the map, clear of the centred trip bar.
  lift raises it further, for the offline badge drawn beneath it."""
  import pyray as rl
  return rl.Rectangle(map_rect.x + map_rect.width - COMPASS_MARGIN - COMPASS_SIZE,
                      map_rect.y + map_rect.height - COMPASS_TRIP_BAR_CLEARANCE - COMPASS_SIZE - lift,
                      COMPASS_SIZE, COMPASS_SIZE)


def next_orientation(orientation: str) -> str:
  return "north_up" if orientation == "heading_up" else "heading_up"


def _draw_compass_needle(x: float, y: float, bearing: float) -> None:
  """A north needle (red tip) centred at x, y, rotated so it points at screen north."""
  import math
  import pyray as rl
  from openpilot.starpilot.system.starpilot_auto.ui.nav_map import _triangle
  angle = math.radians(-bearing)

  def point(forward: float, side: float):
    return rl.Vector2(x + math.sin(angle) * forward + math.cos(angle) * side,
                      y - math.cos(angle) * forward + math.sin(angle) * side)

  tip, tail, left, right = point(30, 0), point(-30, 0), point(0, -11), point(0, 11)
  _triangle(tip, left, right, rl.Color(236, 72, 94, 255))
  _triangle(tail, left, right, rl.Color(236, 240, 246, 255))
  rl.draw_circle_v(rl.Vector2(x, y), 4.0, rl.Color(10, 13, 20, 255))


STALE_OVERLAY = object()  # never equal to a map's overlay content, so the overlay is drawn


class MapPane:
  """Redraw the world at 15 Hz; move its cached image on every car frame."""

  def __init__(self):
    self._map = None
    self._shown = False
    self._texture = None
    self._overlay = None
    self._overlay_key = STALE_OVERLAY
    self._msaa = None
    self._texture_valid = False
    self._cached_camera = None
    self._camera = None
    self._geometry = None
    self._heading_up = False
    self.button_rect = None  # the compass button, in logical pixels, while the map is shown
    self._compass_lift = 0.0
    self.redraws = 0

  def set_shown(self, shown: bool) -> None:
    if shown != self._shown and self._map is not None:
      (self._map.show_event if shown else self._map.hide_event)()
    self._shown = shown
    if not shown:
      self.button_rect = None

  def _ensure_map(self):
    if self._map is None:
      from openpilot.starpilot.system.starpilot_auto.ui.nav_map import NavMapView
      self._map = NavMapView(show_guidance=True, clip=False, show_navigation_waiting=True)
      self._map.show_event()
    return self._map

  def prepare(self, rect, scale_x: float, scale_y: float, now: float, *, heading_up: bool = True) -> None:
    """Advance motion every frame without increasing the expensive redraw rate."""
    import pyray as rl
    from openpilot.starpilot.system.starpilot_auto.ui.nav_map import Camera
    nav_map = self._ensure_map()
    nav_map.set_heading_up(heading_up)
    self._heading_up = heading_up
    geometry = rect.width, rect.height, scale_x, scale_y
    if geometry != self._geometry:
      self._texture_valid = False
      self._overlay_key = STALE_OVERLAY
      self._geometry = geometry
    self._scale = scale_x, scale_y
    width, height = max(1, round(rect.width * scale_x)) + 2 * MAP_BORDER, max(1, round(rect.height * scale_y)) + 2 * MAP_BORDER
    if self._texture is None or (self._texture.texture.width, self._texture.texture.height) != (width, height):
      self._unload_texture()
      from openpilot.system.ui.lib.msaa import MsaaTarget
      self._texture = rl.load_render_texture(width, height)
      self._overlay = rl.load_render_texture(width, height)
      rl.set_texture_filter(self._texture.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      rl.set_texture_filter(self._overlay.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      self._msaa = MsaaTarget.create(width, height)
      self._texture_valid = False
    nav_map.update()
    local = rl.Rectangle(0, 0, rect.width, rect.height)
    self._compass_lift = nav_map.offline_badge_lift(now)
    self.button_rect = compass_rect(rect, self._compass_lift)
    nav_map.offline_anchor = compass_rect(local, self._compass_lift)
    self._anchor = nav_map._advance_camera(local, now)
    self._camera = Camera(**vars(nav_map._camera))
    self._tile_scale = nav_map._tile_scale()
    px, py = MAP_BORDER / scale_x, MAP_BORDER / scale_y
    if not self._texture_valid or nav_map.needs_redraw(now):
      padded = rl.Rectangle(-px, -py, rect.width + 2 * px, rect.height + 2 * py)
      self._render_layer(self._texture, lambda: nav_map._draw_world(padded, self._camera, self._anchor, self._tile_scale, now))
      self._cached_camera = self._camera
      self._cached_anchor = self._anchor
      self._texture_valid = True
      nav_map._record_draw(now)
      nav_map._dirty = False
      self.redraws += 1
    elif not self._covers_view(local):
      # Hold for at most the next scheduled redraw; never expose an edge or
      # turn a GPS jump into unbounded extra GPU renders.
      self._camera, self._anchor = self._cached_camera, self._cached_anchor

    # The overlay's text (guidance, ETA, status badges) is its key, so it redraws only when
    # something on it changes, not for every resent instruction or on a clock tick.
    overlay_key = nav_map._overlay_state
    if overlay_key != self._overlay_key:
      self._render_layer(self._overlay, lambda: nav_map._draw_overlays(local, now), transparent=True)
      self._overlay_key = overlay_key

  def _covers_view(self, rect) -> bool:
    px, py = MAP_BORDER / self._scale[0], MAP_BORDER / self._scale[1]
    for x in (0, rect.width):
      for y in (0, rect.height):
        world = self._camera.to_world(x, y, self._anchor, self._tile_scale)
        sx, sy = self._cached_camera.to_screen(*world, self._cached_anchor, self._tile_scale)
        if not (-px + 1 <= sx <= rect.width + px - 1 and -py + 1 <= sy <= rect.height + py - 1):
          return False
    return True

  def _render_layer(self, target, draw, transparent=False) -> None:
    import pyray as rl
    rl.begin_texture_mode(self._msaa.render_texture if self._msaa is not None else target)
    rl.clear_background(rl.BLANK if transparent else self._map.background)
    # Keep the world opaque and overlays premultiplied; ordinary blending would
    # square translucent alpha before these textures are composited again.
    rl.rl_set_blend_factors_separate(rl.RL_SRC_ALPHA, rl.RL_ONE_MINUS_SRC_ALPHA, rl.RL_ONE, rl.RL_ONE_MINUS_SRC_ALPHA,
                                    rl.RL_FUNC_ADD, rl.RL_FUNC_ADD)
    rl.begin_blend_mode(rl.BlendMode.BLEND_CUSTOM_SEPARATE)
    rl.rl_push_matrix()
    rl.rl_translatef(MAP_BORDER, MAP_BORDER, 0)
    rl.rl_scalef(*self._scale, 1.0)
    draw()
    rl.rl_pop_matrix()
    rl.end_blend_mode()
    rl.end_texture_mode()
    if self._msaa is not None:
      self._msaa.resolve(target)

  def draw(self, rect) -> None:
    import pyray as rl
    if self._texture is None or not self._texture_valid:
      return
    texture = self._texture.texture
    sx, sy = self._scale
    origin = rl.Vector2(0, 0)
    source = rl.Rectangle(0, 0, texture.width, -texture.height)
    padded = rl.Rectangle(-MAP_BORDER / sx, -MAP_BORDER / sy, texture.width / sx, texture.height / sy)
    center = self._camera.to_screen(self._cached_camera.x, self._cached_camera.y, self._anchor, self._tile_scale)
    zoom = 2 ** (self._camera.zoom - self._cached_camera.zoom)
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    rl.rl_push_matrix()
    rl.rl_translatef(rect.x, rect.y, 0)
    rl.rl_push_matrix()
    rl.rl_translatef(*center, 0)
    rl.rl_rotatef(self._cached_camera.bearing - self._camera.bearing, 0, 0, 1)
    rl.rl_scalef(zoom, zoom, 1)
    rl.rl_translatef(-self._cached_anchor[0], -self._cached_anchor[1], 0)
    rl.draw_texture_pro(texture, source, padded, origin, 0, rl.WHITE)
    rl.rl_pop_matrix()
    self._map._draw_cached_car(self._camera, self._anchor)
    rl.begin_blend_mode(rl.BlendMode.BLEND_ALPHA_PREMULTIPLY)
    rl.draw_texture_pro(self._overlay.texture, source, padded, origin, 0, rl.WHITE)
    rl.end_blend_mode()
    rl.rl_pop_matrix()
    self._draw_compass(compass_rect(rect, self._compass_lift))
    rl.end_scissor_mode()

  def _draw_compass(self, button) -> None:
    """Drawn every frame (not in the cached overlay) so the needle turns with the map."""
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.starpilot.system.starpilot_auto.ui.nav_map import CARD_BG, CARD_BORDER, CAR_ACCENT
    center = rl.Vector2(button.x + button.width / 2, button.y + button.height / 2)
    radius = button.width / 2
    rl.draw_circle_v(center, radius, CARD_BG)
    # Blue ring while heading-up, so the mode reads at a glance.
    rl.draw_ring(center, radius - (5 if self._heading_up else 2), radius, 0, 360, 48,
                 CAR_ACCENT if self._heading_up else CARD_BORDER)
    bearing = self._camera.bearing if self._camera is not None else 0.0
    size = 72
    texture = gui_app.cached_render_texture("starpilot_auto_map_compass", size, size,
                                           lambda: _draw_compass_needle(size / 2, size / 2, 0.0), supersample=2)
    if texture is None:
      _draw_compass_needle(center.x, center.y, bearing)
      return
    rl.begin_blend_mode(rl.BlendMode.BLEND_ALPHA_PREMULTIPLY)
    rl.draw_texture_pro(texture, rl.Rectangle(0, 0, texture.width, -texture.height),
                        rl.Rectangle(center.x, center.y, size, size), rl.Vector2(size / 2, size / 2), -bearing, rl.WHITE)
    rl.end_blend_mode()

  def _unload_texture(self) -> None:
    import pyray as rl
    if self._texture is not None:
      rl.unload_render_texture(self._texture)
      self._texture = None
    if self._overlay is not None:
      rl.unload_render_texture(self._overlay)
      self._overlay = None
    self._overlay_key = STALE_OVERLAY
    self._texture_valid = False
    if self._msaa is not None:
      self._msaa.unload()
      self._msaa = None

  def close(self) -> None:
    self._unload_texture()


class MapOnlyStatus:
  """With the map filling the car screen, keep the drive's essentials on top of it:
  the engagement-coloured border, the current speed and every alert."""

  def __init__(self):
    from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer
    from openpilot.system.ui.lib.application import FontWeight, gui_app
    self._alerts = AlertRenderer()
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)

  def render(self, rect) -> None:
    import pyray as rl
    from openpilot.common.constants import CV
    from openpilot.selfdrive.ui.lib.starpilot_status import get_screen_edge_color
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.system.ui.lib.text_measure import measure_text_cached
    rl.draw_rectangle_lines_ex(rect, MAP_ONLY_BORDER, get_screen_edge_color(ui_state))

    car_state = ui_state.sm["carState"]
    v_ego = car_state.vEgoCluster if car_state.vEgoCluster > 0 else car_state.vEgo
    speed = max(0.0, v_ego * (CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH))
    speed_text, unit = f"{speed:.0f}", "km/h" if ui_state.is_metric else "mph"
    pill = rl.Rectangle(rect.x + 28, rect.y + rect.height - 28 - 84 - 16 - 132, 170, 132)
    rl.draw_rectangle_rounded(pill, 0.3, 10, rl.Color(10, 13, 20, 228))
    speed_size = measure_text_cached(self._font_bold, speed_text, 76)
    rl.draw_text_ex(self._font_bold, speed_text, rl.Vector2(pill.x + (pill.width - speed_size.x) / 2, pill.y + 14), 76, 0, rl.WHITE)
    unit_size = measure_text_cached(self._font_medium, unit, 28)
    rl.draw_text_ex(self._font_medium, unit, rl.Vector2(pill.x + (pill.width - unit_size.x) / 2, pill.y + 92), 28, 0,
                    rl.Color(170, 180, 196, 255))

    self._alerts.render(rect)


def vehicle_speed(ui_state) -> float | None:
  """The car's own wheel speed in m/s (never GPS), or None without a recent carState."""
  sm = ui_state.sm
  if not sm.recv_frame["carState"] or not sm.alive["carState"]:
    return None
  return sm["carState"].vEgo


def vehicle_parked(ui_state, environ=os.environ) -> bool:
  """Whether a recent carState has the car in Park. A Desktop Head Unit session counts
  as parked: the comma is on a desk."""
  from openpilot.starpilot.system.starpilot_auto.car_screen import DHU_ENV
  if environ.get(DHU_ENV) == "1":
    return True
  sm = ui_state.sm
  if not sm.recv_frame["carState"] or not sm.alive["carState"] or not sm.valid["carState"]:
    return False
  from cereal import car
  return sm["carState"].gearShifter == car.CarState.GearShifter.park


def navigation_speed(ui_state, environ=os.environ) -> float | None:
  """The speed the destination lock checks. A Desktop Head Unit session is pinned
  below the limit: the comma is on a desk, with no wheel speed to read."""
  from openpilot.starpilot.system.starpilot_auto.car_screen import DHU_ENV
  if environ.get(DHU_ENV) == "1":
    return 0.0
  return vehicle_speed(ui_state)


class OnroadControls:
  """The quick menu, the Navigate screen, and where car touches go.

  Each touch is routed when the finger goes down: to the menu if it starts on the
  button (or anywhere while the menu is open), to the main layout offroad, on the
  home screen or on the Navigate screen, otherwise nowhere.
  """

  def __init__(self, main_layout, params=None, params_memory=None, clock=time.monotonic, navigate_screen_factory=None):
    from openpilot.common.params import Params
    from openpilot.selfdrive.ui.layouts.main import MainState
    from openpilot.starpilot.navigation.destination_store import NavigationDestinationStore
    from openpilot.starpilot.system.starpilot_auto.car_menu import CarQuickMenu
    from openpilot.starpilot.system.starpilot_auto.car_navigate import CarNavigateCard
    self.main_layout = main_layout
    self._MainState = MainState
    self._params = params or Params()
    self.store = NavigationDestinationStore(self._params, params_memory or Params(memory=True))
    self._clock = clock
    self.menu = CarQuickMenu(go_home=self.go_home, go_driving=self.go_driving,
                             open_navigate=self.open_navigate, cancel_navigation=self.cancel_navigation,
                             go_offroad=self.go_offroad, on_open=self.refresh)
    self.target: str | None = None
    self.last_touch = clock()
    self.map_button = None  # the map's compass button while the map is on screen
    self.on_map_button = None
    self.bookmark_button = None  # the driving view's bookmark button while it is drawn
    self.on_bookmark = None
    self._state_read = -STATE_REFRESH
    self._started = False
    self._hold_home = False  # the home screen shown at drive start; no idle timeout while slow
    self.nav_allowed = True
    self.nav_open = False
    self._nav_return_home = False
    self._navigate_screen_factory = navigate_screen_factory
    self._navigate_screen = None
    # On the car's home screen the Navigate card (Home / Work, Start, Other destination)
    # replaces the Personal Records card.
    self.nav_card = CarNavigateCard(start=self.start_favorite, open_other=self.open_navigate, end_route=self.cancel_navigation,
                                    drive=self.go_driving)
    home = getattr(main_layout, "_layouts", {}).get(MainState.HOME)
    self._home = home
    if home is not None:
      home.nav_card = self.nav_card

  @property
  def navigate_screen(self):
    if self._navigate_screen is None:
      factory = self._navigate_screen_factory
      if factory is None:
        from openpilot.starpilot.system.starpilot_auto.car_navigate import CarNavigateScreen as factory
      self._navigate_screen = factory(self._route_started, self.close_navigate, self.open_offline_maps)
    return self._navigate_screen

  def on_home(self, started: bool) -> bool:
    return started and self.main_layout._current_mode != self._MainState.ONROAD

  def go_home(self) -> None:
    self.last_touch = self._clock()
    self.main_layout._set_current_layout(self._MainState.HOME)
    self.main_layout._sidebar.set_visible(True)
    self.menu.on_home = True
    self.menu.corner = "right"

  def go_driving(self) -> None:
    self._hold_home = False
    self.main_layout._set_mode_for_state()
    self.menu.on_home = False
    self.menu.corner = "left"

  def open_navigate(self) -> None:
    if not self.nav_allowed or self.nav_open:
      return
    self.menu.close()
    self.last_touch = self._clock()
    self._nav_return_home = not self._started or self.on_home(self._started)
    self.nav_open = True
    self.navigate_screen.show_event()

  def close_navigate(self, to_driving: bool = False) -> None:
    if not self.nav_open:
      return
    self.nav_open = False
    self._pop_overlays()
    self.navigate_screen.hide_event()
    self.refresh()
    if self._started and (to_driving or not self._nav_return_home):
      self.go_driving()

  def open_offline_maps(self) -> None:
    """From the Navigate screen to Settings > Offline Maps; its Back returns to the drive or home."""
    self.close_navigate()
    self.last_touch = self._clock()
    self.main_layout.open_starpilot_panel("OFFLINE_MAPS")
    self.menu.on_home = True
    self.menu.corner = "right"

  def _route_started(self) -> None:
    self.close_navigate(to_driving=True)

  def _pop_overlays(self) -> None:
    """Close a keyboard or dialog the Navigate screen left open over the main layout."""
    from openpilot.system.ui.lib.application import gui_app
    stack = gui_app._nav_stack
    if self.main_layout not in stack:
      return
    while len(stack) > 1 and stack[-1] is not self.main_layout:
      gui_app.pop_widget()

  def start_favorite(self, favorite: dict) -> None:
    """Home card Start (any speed): set the route, then open the drive in the chosen car screen layout."""
    self.store.set_destination(favorite)
    self.refresh()
    if self._started:
      self.go_driving()

  def go_offroad(self) -> None:
    """Menu Go offroad (confirmed, in Park): force the comma offroad until Resume Onroad on the home screen."""
    from openpilot.starpilot.common.starpilot_variables import update_starpilot_toggles
    if not self.menu.parked:
      return
    self._params.put_bool("ForceOnroad", False)
    self._params.put_bool("ForceOffroad", True)
    update_starpilot_toggles()

  def cancel_navigation(self) -> None:
    self.store.clear_navigation()
    self.refresh()

  def refresh(self) -> None:
    from openpilot.starpilot.navigation.destination_store import routing_configured
    self._state_read = self._clock()
    self.menu.routing_ok = routing_configured(self._params)
    destination = self.store.active_destination()
    self.menu.nav_active = destination is not None
    self.menu.destination_name = str((destination or {}).get("place_name") or (destination or {}).get("name") or "")
    self.menu.on_home = self.on_home(self._started)
    self.nav_card.routing_ok = self.menu.routing_ok
    self.nav_card.destination_name = self.menu.destination_name
    self.nav_card.set_favorites(self.store.favorite_destinations())

  def update(self, started: bool, speed_ms: float | None = 0.0, parked: bool = False) -> None:
    from openpilot.starpilot.system.starpilot_auto.car_navigate import locked_text, speed_allows_navigation
    now = self._clock()
    was_started, self._started = self._started, started
    self.menu.parked = parked
    if not parked:
      self.menu.confirming_offroad = False
    self.nav_allowed = speed_allows_navigation(started, speed_ms)
    lock = "" if self.nav_allowed else locked_text()
    self.menu.locked_text = lock
    self.nav_card.locked_text = lock
    self.nav_card.started = started
    if started and not was_started and self.nav_allowed:
      # Start the drive on the home screen instead of the drive layout, and keep the
      # main layout's own offroad->onroad switch from undoing it this frame.
      self.go_home()
      self.main_layout._prev_onroad = True
      self._hold_home = True
    elif not started:
      self._hold_home = False
    if self.nav_open and started:
      critical = self.main_layout._critical_full_alert_active()
      if not self.nav_allowed or critical or now - self.last_touch > HOME_ONROAD_TIMEOUT:
        self.close_navigate(to_driving=True)
    if now - self._state_read >= STATE_REFRESH:
      self.refresh()
    if not started:
      self.menu.close()
      return
    if self.on_home(started) and not self.nav_open:
      critical = self.main_layout._critical_full_alert_active()
      held = self._hold_home and self.nav_allowed
      if critical or (not held and now - self.last_touch > HOME_ONROAD_TIMEOUT):
        self.go_driving()
    self.menu.on_home = self.on_home(started)
    self.menu.corner = "right" if self.menu.on_home else "left"

  def _plain_button_at(self, x: float, y: float) -> str | None:
    """The plain button under a touch: the map's compass or the status column's bookmark slot."""
    for name, button in (("map_button", self.map_button), ("bookmark_button", self.bookmark_button)):
      if button is not None and button.x <= x <= button.x + button.width and button.y <= y <= button.y + button.height:
        return name
    return None

  def full_screen(self, started: bool) -> bool:
    """Whether the main layout (or the Navigate screen) fills the car screen instead of the drive layout."""
    return self.nav_open or self.on_home(started)

  def route(self, touches, touch_input, started: bool, screen) -> tuple[list, list]:
    """(events for the main layout or Navigate screen, events for the menu)."""
    layout_events, menu_events = [], []
    layout_ok = not started or self.full_screen(started)
    if self.target == "layout" and not layout_ok:
      layout_events += touch_input.events([], allowed=False, now=self._clock())
      self.target = None
    for touch in touches:
      x, y = touch.x * touch_input.logical_w, touch.y * touch_input.logical_h
      if touch.kind == "down":
        if started and not self.nav_open and self.menu.captures(x, y, screen):
          self.target = "menu"
        elif layout_ok:
          self.target = "layout"
        elif started:
          self.target = self._plain_button_at(x, y)
        else:
          self.target = None
        self.last_touch = self._clock()
      if self.target in ("map_button", "bookmark_button"):
        # A plain button: it acts when the finger lifts on it, and takes no widget events.
        if touch.kind in ("up", "cancel"):
          action = self.on_map_button if self.target == "map_button" else self.on_bookmark
          if touch.kind == "up" and self._plain_button_at(x, y) == self.target and action is not None:
            action()
          self.target = None
        continue
      events = touch_input.events([touch], allowed=self.target is not None, now=self._clock())
      (menu_events if self.target == "menu" else layout_events).extend(events)
    return layout_events, menu_events


def neutralize_side_effects() -> None:
  """Must run before any UI module is imported."""
  os.environ["BIG"] = "1"  # landscape layout; read by application.py at import
  for name in ("cereal.messaging", "openpilot.cereal.messaging"):
    try:
      module = __import__(name, fromlist=["PubMaster"])
      module.PubMaster = NullPubMaster
    except ImportError:
      pass


def wait_for_request(producer: FrameProducer) -> FrameRequest:
  deadline = time.monotonic() + STARTUP_DEMAND_WAIT
  while time.monotonic() < deadline:
    producer._next_open_check = 0.0
    # Geometry is available even if the car has not granted display focus yet.
    request = producer.pending_request(require_demand=False)
    if request is not None:
      return request
    time.sleep(0.1)
  raise TimeoutError("starpilot_autod never requested car frames")


def run(frames_path: str, touch_path: str) -> int:
  if os.geteuid() == 0:
    raise RuntimeError("The car UI must run as the comma user, not root")
  parent = os.getppid()
  # Core 6 at SCHED_IDLE: never compete with openpilot's own processes (see placement.py)
  placement = RendererPlacement(report=lambda event: print(json.dumps(event), flush=True))
  placement.start()
  neutralize_side_effects()
  producer = FrameProducer(frames_path)
  request = wait_for_request(producer)
  logical_w, logical_h, scale_x, scale_y = logical_size(request)
  visible_w, visible_h = request.width - request.margin_w, request.height - request.margin_h

  from openpilot.starpilot.system.starpilot_auto.headless_egl import FrameReadback, HeadlessContext
  context = HeadlessContext(request.width, request.height)
  import pyray as rl
  fast_structs = use_fast_struct_constructors(rl)
  from openpilot.system.ui.lib.application import MouseEvent, MousePos, gui_app
  from openpilot.selfdrive.ui.ui_state import device, ui_state

  ui_state.starpilot_auto_car_view = True
  gui_app._width, gui_app._height = logical_w, logical_h
  gui_app._scale = scale_y
  gui_app._render_texture = None
  gui_app._load_fonts()
  gui_app._set_styles()
  gui_app._patch_text_functions()
  gui_app._patch_scissor_mode()
  device.update = lambda: None               # display power and brightness belong to the comma's own UI
  ui_state.prime_state.start = lambda: None  # no second comma API poller
  ui_state.ui_params.start()
  ui_state.live_params.start()
  from openpilot.starpilot.system.starpilot_auto.ui.main import CarMainLayout
  from openpilot.starpilot.system.starpilot_auto.car_screen import STATUS_METRICS, CarScreenSettings, blind_spot_monitors_visible
  main_layout = CarMainLayout()
  map_pane = MapPane()
  car_settings = CarScreenSettings()
  controls = OnroadControls(main_layout)
  map_status: MapOnlyStatus | None = None

  # Everything built so far lives for the whole session. Frozen, it is never rescanned by the
  # collector, whose full passes over the UI's objects stalled a frame every few seconds.
  gc.collect()
  gc.freeze()

  def toggle_map_orientation() -> None:
    from openpilot.starpilot.system.starpilot_auto import car_screen
    orientation = next_orientation(car_settings.poll()["map_orientation"])
    try:
      car_settings.current = car_screen.update({"map_orientation": orientation})
    except (OSError, ValueError) as error:
      print(json.dumps({"event": "map_orientation_save_failed", "error": str(error)[:200]}), flush=True)

  controls.on_map_button = toggle_map_orientation
  controls.on_bookmark = main_layout._dev_sidebar.bookmark.press

  content = rl.load_render_texture(visible_w, visible_h)
  # The second UI shares the GPU with driver monitoring. Single-sample rendering
  # avoids a full-size multisampled color/depth target and its resolve every frame.
  converter = None
  if request.flags & FLAG_NV12:
    from openpilot.starpilot.system.starpilot_auto import gpu_nv12
    try:
      converter = gpu_nv12.Nv12Converter(request.width, request.height,
                                         margin_w=request.margin_w, margin_h=request.margin_h, compose=True)
    except Exception as error:
      print(json.dumps({"event": "nv12_unavailable", "error": str(error)[:200]}), flush=True)
  pixel_format = FORMAT_NV12 if converter is not None else FORMAT_RGBA
  # NV12 folds margins and the vertical flip into conversion. Only the RGBA
  # fallback needs a separate composition target.
  output = rl.load_render_texture(request.width, request.height) if converter is None else None
  readback = FrameReadback(frame_bytes(request.width, request.height, pixel_format),
                           asynchronous=bool(request.flags & FLAG_ASYNC_READBACK))
  rgba_regions = [(output.id, request.width, request.height, 0)] if output is not None else []
  gpu_timing = os.getenv("STARPILOT_AUTO_GPU_TIMING") == "1"
  print(json.dumps({"event": "pipeline", "format": "nv12" if converter is not None else "rgba",
                    "readback": "async" if readback.asynchronous else "sync",
                    "msaa": 0, "fused_compose": converter is not None, "gpu_timing": gpu_timing,
                    "fast_structs": len(fast_structs)}), flush=True)
  touch = TouchInput(MouseEvent, MousePos, logical_w, logical_h)
  # A few widgets (list buttons, StarPilot sliders) poll raylib's pointer directly;
  # without a window it would stay at 0,0, so report the car touch position instead.
  rl.get_mouse_position = lambda: rl.Vector2(touch.pos.x, touch.pos.y)
  receiver = TouchReceiver(touch_path)
  stats = RenderStats(time.monotonic())
  sampler = None
  from openpilot.starpilot.system.starpilot_auto import identity as identity_store
  config = identity_store.load_config()
  if config["render_profile"]:
    from openpilot.starpilot.system.starpilot_auto.render_profile import RenderSampler
    sampler = RenderSampler(identity_store.LOG_DIR / "render_profile.txt", max_bytes=config["render_profile_kb"] * 1024)
    sampler.start()
  frame_count = 0
  camera_pacer = CameraPacer()
  camera_stream = None  # the camera stream the last frame showed, when onroad
  in_flight = {"captured_ns": 0}
  stop = {"flag": False}
  signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
  print(f"car ui {logical_w}x{logical_h} -> {visible_w}x{visible_h} in {request.width}x{request.height}", flush=True)

  def publish_readback() -> None:
    """Hand the frame read back last to starpilot_autod."""
    started = time.monotonic()
    try:
      pixels = readback.finish()
      ready = time.monotonic()
      producer.publish(request, pixels, in_flight["captured_ns"], pixel_format, advance=False)
    finally:
      readback.release()
    stats.add("readback_wait_ms", ready - started)
    stats.add("publish_ms", time.monotonic() - ready)

  try:
    while not stop["flag"] and os.getppid() == parent:
      now = time.monotonic()
      placement.maintain(now)
      pending = producer.pending_request(now)
      if pending is None:
        # Stay warm while the head unit shows its own screen, without rendering
        # or readback. The supervisor owns our lifetime and stops us on teardown;
        # the parent check also handles a crashed daemon.
        if readback.pending:
          readback.release()
        if sampler is not None:
          sampler.rendering = False
        context.pause()
        time.sleep(0.05)
        stats.reset(time.monotonic())
        continue
      if pending != request:
        return 3  # new geometry: starpilot_autod starts a fresh renderer
      now_ns = time.monotonic_ns()
      # The requested frame rate (the encoder's budget) always applies. Rendering
      # only when it is due also keeps the schedule from running ahead of real time.
      capture_delay = producer.capture_delay(request, now_ns)
      if capture_delay > 0:
        if readback.pending:
          publish_readback()  # never hold a finished frame back just to pace the next one
        if sampler is not None:
          sampler.rendering = False
        # Sleep to the capture deadline instead of waking every 2 ms. Keep
        # demand/stop checks responsive even with a low configured frame rate.
        time.sleep(min(capture_delay, 0.05))
        continue
      if camera_stream is not None:
        # Within that budget, draw as soon as the camera on screen has a new frame.
        if readback.pending:
          publish_readback()
        if not camera_pacer.wait(camera_stream, now):
          if sampler is not None:
            sampler.rendering = False
          continue
        now_ns = time.monotonic_ns()
        now = now_ns / 1e9

      if sampler is not None:
        sampler.rendering = True
      frame_count += 1
      frame_began, cpu_began = now_ns / 1e9, time.thread_time()
      context.begin_frame(frame_began)
      viewport = rl.Rectangle(0, 0, logical_w, logical_h)
      ui_state.update()
      started = ui_state.started
      if sampler is not None:
        sampler.onroad = started
      speed_ms = navigation_speed(ui_state)
      controls.update(started, speed_ms, vehicle_parked(ui_state))
      # Last frame's map placement; the layout only changes with settings or a screen switch.
      controls.map_button = map_pane.button_rect if started and not controls.full_screen(started) else None
      # Last frame's status-column bookmark slot, if the column drew one.
      controls.bookmark_button = main_layout._dev_sidebar.bookmark_rect if started and not controls.full_screen(started) else None
      main_layout._dev_sidebar.bookmark_rect = None  # set again only if the column draws the slot this frame
      layout_events, menu_events = controls.route(receiver.drain(), touch, started, viewport)
      settings = car_settings.poll()
      main_layout._dev_sidebar.metric_override = [STATUS_METRICS[slot][0] for slot in settings["status_slots"]]
      main_rect, map_rect = car_layout(settings, started, controls.full_screen(started), logical_w, logical_h)
      status_rect = None
      if started and not controls.full_screen(started) and settings["show_status_column"] and any(slot != "blank" for slot in settings["status_slots"]):
        main_rect, map_rect, status_rect = status_layout(settings, main_rect, map_rect)
      ui_state.car_show_current_speed = settings["show_current_speed"]
      ui_state.car_directions_left = settings["directions_side"] == "left"
      ui_state.nav_map_beside_road = main_rect is not None and map_rect is not None
      ui_state.car_camera_off = started and not settings["camera"]
      onroad_view = main_layout._layouts.get(controls._MainState.ONROAD)
      camera_shown = (started and settings["camera"] and main_rect is not None and not controls.nav_open and
                      not controls.full_screen(started) and onroad_view is not None)
      camera_stream = onroad_view.stream_type if camera_shown else None
      ui_state.starpilot_auto_blind_spot_monitors_visible = blind_spot_monitors_visible(settings, speed_ms)
      mark = time.monotonic()
      stats.add("update_ms", mark - frame_began)
      map_pane.set_shown(map_rect is not None)
      if map_rect is not None:
        map_pane.prepare(map_rect, scale_x, scale_y, now, heading_up=settings["map_orientation"] == "heading_up")
      stats.add("map_ms", time.monotonic() - mark)
      if readback.pending:
        # The previous frame, read back while this one was updating. Waiting any
        # later only adds latency: on the comma the wait tracks the GPU's own
        # frame time (3-5 ms), not how long the CPU was busy in between.
        publish_readback()

      mark = time.monotonic()
      map_draw = 0.0
      rl.begin_texture_mode(content)
      rl.clear_background(rl.Color(6, 6, 15, 255))
      rl.rl_push_matrix()
      rl.rl_scalef(scale_x, scale_y, 1.0)
      gui_app._mouse_events = layout_events
      if layout_events:
        gui_app._last_mouse_event = layout_events[-1]
      for tick in list(gui_app._nav_stack_ticks):
        tick()
      widgets = gui_app._nav_stack[-gui_app._nav_stack_widgets_to_render:]
      if len(widgets) > 1 and widgets[-1].covers_background(viewport):
        widgets = widgets[-1:]
      for widget in widgets:
        if widget is main_layout and controls.nav_open:
          controls.navigate_screen.render(viewport)
        elif widget is main_layout:
          if main_rect is not None:
            widget.render(main_rect)
          if map_rect is not None:
            map_began = time.monotonic()
            map_pane.draw(map_rect)
            if main_rect is None:
              map_status = map_status or MapOnlyStatus()
              map_status.render(map_rect)
            map_draw += time.monotonic() - map_began
          if status_rect is not None:
            widget.render_status(status_rect)
        else:
          widget.render(viewport)
      menu_began = time.monotonic()
      stats.add("layout_ms", menu_began - mark - map_draw)
      stats.add("map_draw_ms", map_draw)
      if started and not controls.nav_open:
        gui_app._mouse_events = menu_events
        controls.menu.render(viewport)
      mark = time.monotonic()
      stats.add("menu_ms", mark - menu_began)
      rl.rl_pop_matrix()
      rl.end_texture_mode()
      if output is not None:
        # RGBA fallback: the same composition the NV12 conversion does.
        compose_rgba(content.texture, output, request.margin_w, request.margin_h)
      stats.add("compose_ms", time.monotonic() - mark)
      mark = time.monotonic()
      gui_app._populate_render_texture_cache()
      stats.add("cache_ms", time.monotonic() - mark)
      mark = time.monotonic()
      regions = converter.convert(content.texture) if converter is not None else rgba_regions
      stats.add("convert_ms", time.monotonic() - mark)
      if gpu_timing and frame_count % GPU_SAMPLE_EVERY == 0:
        mark = time.monotonic()
        readback.gpu_finish()
        stats.add("gpu_ms", time.monotonic() - mark, sampled=True)
      mark = time.monotonic()
      producer.advance(request, now_ns)
      readback.start(regions)
      in_flight["captured_ns"] = now_ns
      stats.add("readback_ms", time.monotonic() - mark)
      if not readback.asynchronous:
        publish_readback()
      done = time.monotonic()
      stats.add("frame_ms", done - frame_began)
      stats.add("cpu_ms", time.thread_time() - cpu_began)
      report = stats.frame_done(done, gpu_timing=gpu_timing)
      if report is not None:
        print(json.dumps(report), flush=True)
        if sampler is not None:
          sampler.summary = report
      gui_app._frame += 1
    return 0
  finally:
    if sampler is not None:
      sampler.close()
    receiver.close()
    map_pane.close()
    readback.close()
    if converter is not None:
      converter.close()
    rl.unload_render_texture(content)
    if output is not None:
      rl.unload_render_texture(output)
    context.close()
    ui_state.live_params.stop()


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--frames", required=True)
  parser.add_argument("--touch", default=DEFAULT_TOUCH_SOCKET)
  args = parser.parse_args()
  return run(args.frames, args.touch)


if __name__ == "__main__":
  sys.exit(main())
