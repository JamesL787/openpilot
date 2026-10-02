"""Navigation map: Mapbox raster tiles, the route, the car and turn guidance.

Shown by the Navigation settings panel (destination and route preview) and, in
the Starpilot Auto car view, beside the driving view while onroad. It follows the
car heading-up while driving and shows the desire the driving model is being
fed, so a route turn is visible from the moment the model acts on it.

Kept cheap on purpose: tiles are downloaded and decoded on worker threads, at
most two textures are uploaded per frame, the route is projected with numpy and
only its visible part is drawn, and GPS positions are dead-reckoned between
fixes rather than polled faster. The planner republishes the same fix at 4 Hz
while the comma's own receiver only produces one a second, so a republished fix
keeps its original time, and a new fix's correction is eased in instead of jumping.
"""

from __future__ import annotations

import datetime
import json
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.onroad.starpilot.navigation_card import (
  ASSETS_PATH,
  FALLBACK_ICON,
  _format_distance,
  _modifier_suffix,
  _normalize_maneuver_type,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.navigation.destination_store import parse_destination_json
from openpilot.starpilot.navigation.offline_maps import OfflineMaps
from openpilot.starpilot.navigation.mapbox_usage import shared_usage
from openpilot.starpilot.navigation.map_tiles import (
  LIGHT_STYLE,
  TILE_SIZE,
  TileKey,
  TileCache,
  TileService,
  default_cache_dir,
  meters_per_world_unit,
  offline_root,
  tiles_covering,
  world_xy,
)
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

MAX_TEXTURES = 40  # 512x512 RGBA tiles, 1 MB each on the GPU
MIN_TEXTURES = 16  # otherwise twice what the map shows: this zoom level and the last one, to fall back on
UPLOADS_PER_FRAME = 1  # a 512x512 upload costs a few ms on the comma; two in one frame showed as a hitch
MAX_FALLBACK_LEVELS = 6
GPS_POLL_SECONDS = 0.2
GPS_STALE_SECONDS = 3.0
DEAD_RECKON_LIMIT = 1.6    # s; covers a late 1 Hz fix without running away when fixes stop
CORRECTION_TAU = 0.35      # s; how quickly a new fix's disagreement with dead reckoning is eased out
CORRECTION_MAX_METERS = 60.0  # larger disagreements snap: a GPS jump, not drift
TURN_RATE_MIN_SPEED = 3.0  # m/s; below this the GPS bearing is too noisy to estimate a turn from
TURN_RATE_MAX = 40.0       # deg/s; tighter than any turn taken at TURN_RATE_MIN_SPEED or above
ROUTE_SNAP_METERS = 15.0          # GPS error and lane offset: the marker sits on the route line within this
ROUTE_SNAP_RELEASE_METERS = 35.0  # the pull fades out by here, so leaving the route never jumps
ACQUIRE_POLL_SECONDS = 1.0
ACQUIRE_SATELLITE_WINDOW = 5.0  # s; a constellation report older than this no longer counts
ACQUIRE_GOOD_SATELLITES = 6     # the progress bar is full here; a fix usually follows
NAV_STALE_SECONDS = 3.5
ROUTE_STALE_SECONDS = 30.0  # navigationd republishes the route every few seconds while it has one
ROUTE_CHUNK_SEGMENTS = 128
TOKEN_REFRESH_SECONDS = 30.0
OFFLINE_STATUS_SECONDS = 2.0
MAP_MAX_FPS = 15.0       # redraw cap when drawing into a cached texture
MAP_IDLE_REDRAW = 1.0    # still redraw this often so the clock and badges stay current

FOLLOW_SPEEDS = (0.0, 8.0, 15.0, 25.0, 35.0)
FOLLOW_ZOOMS = (16.0, 15.8, 15.4, 14.9, 14.5)
ZOOM_SPEED_TAU_UP = 4.0    # s; the speed that picks the zoom lags acceleration...
ZOOM_SPEED_TAU_DOWN = 8.0  # ...and braking more, so a stop does not dive the map in
ZOOM_HOLD = 0.3            # zoom levels the speed curve must drift before the map follows
ZOOM_EASE = 1.2            # 1/s; follow-mode zoom glide, gentle enough to read through
PREVIEW_MAX_ZOOM = 16.0
FOLLOW_ANCHOR_Y = 0.70

MAP_BACKGROUND = rl.Color(20, 26, 38, 255)
MAP_BACKGROUND_LIGHT = rl.Color(238, 236, 230, 255)  # behind streets-v12 while tiles load
ROUTE_CASING = rl.Color(12, 40, 92, 255)
ROUTE_FILL = rl.Color(64, 150, 255, 255)
ROUTE_ALTERNATE = rl.Color(130, 145, 170, 190)
ROUTE_ALTERNATE_CASING = rl.Color(40, 48, 64, 230)
CAR_FILL = rl.Color(255, 255, 255, 255)
CAR_ACCENT = rl.Color(64, 150, 255, 255)
DEST_FILL = rl.Color(236, 72, 94, 255)
CARD_BG = rl.Color(10, 13, 20, 228)
CARD_BORDER = rl.Color(255, 255, 255, 26)
TEXT = rl.Color(240, 244, 250, 255)
SUBTEXT = rl.Color(170, 180, 196, 255)
DESIRE_ROUTE = rl.Color(52, 199, 120, 255)
DESIRE_DRIVER = rl.Color(64, 150, 255, 255)
DESIRE_HINT = rl.Color(232, 170, 70, 255)
BADGE_WARN = rl.Color(232, 170, 70, 255)
OFFLINE_COLLAPSE_SECONDS = 10.0  # the offline badge's words, then just its icon
OFFLINE_BADGE_HEIGHT = 56.0
OFFLINE_BADGE_GAP = 12.0
THEME_CYCLE = ("auto", "light", "dark")
THEME_NAMES = {"auto": "Auto", "light": "Light", "dark": "Dark"}
TOAST_SECONDS = 3.5
TOAST_WIDTH = 480.0
PROGRESS_TRACK = rl.Color(255, 255, 255, 36)
PROGRESS_FILL = rl.Color(64, 150, 255, 255)

DESIRE_NAMES = {
  1: "Turn left",
  2: "Turn right",
  3: "Lane change left",
  4: "Lane change right",
  5: "Keep left",
  6: "Keep right",
}
CENTER_LINE_HEIGHT = 40
TURN_HINT_DISTANCE = 160.0
KEEP_HINT_DISTANCE = 400.0


def desire_line(started: bool, desire: int, nav_desire: int, nav: dict | None) -> tuple[str, str, rl.Color] | None:
  """(label, detail, color) for what the driving model is being told, and why."""
  if not started:
    return None
  name = DESIRE_NAMES.get(desire)
  if name is not None:
    from_route = nav_desire == desire
    return f"Model: {name}", "From the route" if from_route else "From the turn signal", DESIRE_ROUTE if from_route else DESIRE_DRIVER
  if nav is None:
    return None
  modifier, distance = nav["modifier"], nav["distance"]
  if nav["type"] == "turn" and modifier in ("left", "sharpLeft", "right", "sharpRight") and distance <= TURN_HINT_DISTANCE:
    side = "left" if modifier in ("left", "sharpLeft") else "right"
    return f"Route turn {side} ahead", f"Signal {side} and the model will take it", DESIRE_HINT
  if modifier in ("slightLeft", "slightRight") and distance <= KEEP_HINT_DISTANCE:
    side = "left" if modifier == "slightLeft" else "right"
    return f"Keep {side} ahead", f"Nudge the wheel {side} to move over", DESIRE_HINT
  return None


ROUTE_DOWNLOAD_HINTS = {
  "none": "No connection. The download picks up once you're back online; offline maps keep the map ready without one.",
  "wifi": "No cellular? Stay on Wi-Fi until this finishes. Offline maps (Settings) make routing faster while it downloads.",
  "cell": "For faster routing, save this area in Offline maps (Settings).",
}


def network_kind(device_state) -> str:
  """The connection for the route download card: "wifi" (or ethernet), "cell" or "none"."""
  if device_state is None:
    return "none"
  kind = str(device_state.networkType)
  if kind in ("wifi", "ethernet"):
    return "wifi"
  return "cell" if kind.startswith("cell") else "none"


def route_download(route: dict, network: str, offline: bool) -> tuple[str, str, float] | None:
  """(title, hint, progress) while navtilesd is still saving the route's map tiles, from its status."""
  try:
    remaining, total = int(route.get("remaining") or 0), int(route.get("total") or 0)
  except (TypeError, ValueError):
    return None
  if remaining <= 0 or total <= 0:
    return None
  progress = min(1.0, (total - remaining) / total)
  if offline or network == "none":
    return f"Route map paused  •  {int(100 * progress)}%", ROUTE_DOWNLOAD_HINTS["none"], progress
  return f"Downloading route map  •  {int(100 * progress)}%", ROUTE_DOWNLOAD_HINTS[network], progress


def _decode_tile(data: bytes, extension: str):
  """Runs on a tile worker thread: PNG/JPEG bytes to a CPU-side raylib image."""
  image = rl.load_image_from_memory(extension, data, len(data))
  if image.width <= 0 or image.height <= 0:
    return None
  return image


class TileTextures:
  """GPU textures for decoded tiles, shared by every map in this process."""

  def __init__(self):
    self._params = Params()
    self._token = ""
    self._token_checked = -math.inf
    self._token_lock = threading.Lock()
    self._textures: OrderedDict[TileKey, rl.Texture] = OrderedDict()
    self._wanted = 0
    self._wanted_keys: tuple[TileKey, ...] = ()
    self.theme = "auto"  # the map colors setting, read with the style
    self.offline_maps = OfflineMaps()
    self._save_viewed = False
    self._save_viewed_read = -math.inf
    self.service: TileService | None = None
    self.style = ""
    self._style_read = -math.inf
    self.theme = self.offline_maps.map_theme()
    self._use_style(self.offline_maps.display_style(theme=self.theme))
    self._offline_status: dict = {}
    self._offline_status_read = -math.inf

  def _use_style(self, style: str) -> None:
    """Light and dark maps are different tile styles, cached separately."""
    if self.service is not None:
      self.service.close()
    for texture in self._textures.values():
      rl.unload_texture(texture)
    self._textures.clear()
    self.style = style
    # navtilesd promotes requested driven tiles from the regular cache into the
    # same pinned store used by explicit offline areas.
    offline = TileCache(offline_root(), style, max_bytes=None)
    regular = TileCache(default_cache_dir(), style, pinned=offline)
    self.service = TileService(self._read_token, decode=_decode_tile, cache=regular, style=style,
                               write_through=self._save_driven_tile, usage=shared_usage())

  def _check_style(self) -> bool:
    """Follow the map colors setting (and the sun, for automatic) within a couple of seconds.
    True when the map must redraw."""
    now = time.monotonic()
    if now - self._style_read < OFFLINE_STATUS_SECONDS:
      return False
    self._style_read = now
    self.theme = self.offline_maps.map_theme()
    style = self._theme_style(self.theme)
    if style == self.style:
      return False
    self._use_style(style)
    return True

  def _save_driven_tile(self, key: TileKey, data: bytes) -> bool | None:
    del data
    now = time.monotonic()
    if now - self._save_viewed_read >= OFFLINE_STATUS_SECONDS:
      self._save_viewed_read = now
      self._save_viewed = self.offline_maps.save_viewed_cache()
    if not self._save_viewed:
      return None
    return self.offline_maps.mark_auto_saved(key)

  @property
  def background(self) -> rl.Color:
    return MAP_BACKGROUND_LIGHT if self.style == LIGHT_STYLE else MAP_BACKGROUND

  def offline_status(self) -> dict:
    now = time.monotonic()
    if now - self._offline_status_read >= OFFLINE_STATUS_SECONDS:
      self._offline_status_read = now
      self._offline_status = self.offline_maps.status()
    return self._offline_status

  @property
  def has_token(self) -> bool:
    return bool(self._read_token())

  def _read_token(self) -> str:
    with self._token_lock:
      now = time.monotonic()
      if now - self._token_checked > TOKEN_REFRESH_SECONDS:
        self._token_checked = now
        try:
          self._token = str(self._params.get("MapboxPublicKey", encoding="utf-8") or "").strip()
        except Exception:
          self._token = ""
      return self._token

  def want(self, keys: Sequence[TileKey]) -> None:
    self._wanted = len(keys)
    self._wanted_keys = tuple(keys)
    self.service.want(keys)

  def style_problem(self, style: str) -> str | None:
    """Why the map can't show ``style`` here, or None when it can. Online, Mapbox serves it;
    offline, every tile in view (or an ancestor the map would stretch over it) must be on disk."""
    if style == self.style:
      return None
    online = self.has_token and not self.service.offline and not self.offline_status().get("offline")
    if online:
      return None
    if not self._wanted_keys:
      return "The map hasn't loaded here yet."
    caches = (TileCache(offline_root(), style, max_bytes=None), TileCache(default_cache_dir(), style))

    def on_disk(key: TileKey | None) -> bool:
      for _ in range(MAX_FALLBACK_LEVELS + 1):
        if key is None:
          return False
        if any(cache.path(key).is_file() for cache in caches):
          return True
        key = key.parent()
      return False

    if all(on_disk(key) for key in self._wanted_keys):
      return None
    name = "Light" if style == LIGHT_STYLE else "Dark"
    if not self.has_token:
      return f"{name} map isn't saved here. Add a Mapbox key in The Galaxy to download it."
    return f"{name} map isn't saved here, and the map is offline."

  def _theme_style(self, theme: str) -> str:
    """The style to show for ``theme``. Auto keeps both styles, so when the sun's pick
    can't be shown here (offline, not saved) it shows the other rather than a blank map."""
    style = self.offline_maps.display_style(theme=theme)
    if theme == "auto" and self.style and style != self.style and self.style_problem(style) is not None:
      return self.style
    return style

  def set_theme(self, theme: str) -> None:
    """Save the map colors setting (as The Galaxy does) and show it now."""
    self.offline_maps.set_map_theme(theme)
    self._style_read = -math.inf
    self._check_style()

  def upload(self) -> int:
    """Upload decoded tiles; nonzero when the map changed (new tiles, or a new style)."""
    switched = self._check_style()
    results = self.service.poll(UPLOADS_PER_FRAME)
    for key, image in results:
      texture = rl.load_texture_from_image(image)
      rl.unload_image(image)
      rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      rl.set_texture_wrap(texture, rl.TextureWrap.TEXTURE_WRAP_CLAMP)
      old = self._textures.pop(key, None)
      if old is not None:
        rl.unload_texture(old)
      self._textures[key] = texture
    # A car-sized map shows a handful of tiles; holding 40 kept most of them on the GPU for nothing.
    keep = min(MAX_TEXTURES, max(MIN_TEXTURES, 2 * self._wanted))
    while len(self._textures) > keep:
      key, texture = self._textures.popitem(last=False)
      rl.unload_texture(texture)
      self.service.forget(key)
    return len(results) + int(switched)

  def best(self, key: TileKey) -> tuple[rl.Texture, rl.Rectangle] | None:
    """The tile itself, or the part of the closest loaded ancestor that covers it."""
    candidate: TileKey | None = key
    for depth in range(MAX_FALLBACK_LEVELS + 1):
      if candidate is None:
        return None
      texture = self._textures.get(candidate)
      if texture is not None:
        self._textures.move_to_end(candidate)
        size = TILE_SIZE / (1 << depth)
        mask = (1 << depth) - 1
        return texture, rl.Rectangle((key.x & mask) * size, (key.y & mask) * size, size, size)
      candidate = candidate.parent()
    return None


_shared_tiles: TileTextures | None = None


def shared_tiles() -> TileTextures:
  global _shared_tiles
  if _shared_tiles is None:
    _shared_tiles = TileTextures()
  return _shared_tiles


@dataclass
class Camera:
  x: float = 0.0        # zoom-0 world position shown at the anchor
  y: float = 0.0
  zoom: float = FOLLOW_ZOOMS[0]
  bearing: float = 0.0  # this compass heading points up the screen

  def scale(self, tile_scale: float) -> float:
    return (2.0 ** self.zoom) * tile_scale

  def to_screen(self, wx, wy, anchor: tuple[float, float], tile_scale: float):
    """World (scalars or numpy arrays) to screen. Heading-up rotates by -bearing."""
    s = self.scale(tile_scale)
    dx, dy = (wx - self.x) * s, (wy - self.y) * s
    c, sn = math.cos(math.radians(self.bearing)), math.sin(math.radians(self.bearing))
    return anchor[0] + dx * c + dy * sn, anchor[1] - dx * sn + dy * c

  def to_world(self, sx: float, sy: float, anchor: tuple[float, float], tile_scale: float) -> tuple[float, float]:
    s = self.scale(tile_scale)
    rx, ry = sx - anchor[0], sy - anchor[1]
    c, sn = math.cos(math.radians(self.bearing)), math.sin(math.radians(self.bearing))
    return self.x + (rx * c - ry * sn) / s, self.y + (rx * sn + ry * c) / s


def _angle_delta(target: float, current: float) -> float:
  return (target - current + 540.0) % 360.0 - 180.0


def _route_world(points: Sequence[tuple[float, float]]) -> np.ndarray:
  if not points:
    return np.zeros((0, 2))
  return np.array([world_xy(lat, lon) for lat, lon in points], dtype=np.float64)


def _visible_runs(sx: np.ndarray, sy: np.ndarray, rect: rl.Rectangle, margin: float) -> list[tuple[int, int]]:
  """Index ranges [start, end] of consecutive route segments that touch the (padded) rect."""
  if len(sx) < 2:
    return []
  left, right = rect.x - margin, rect.x + rect.width + margin
  top, bottom = rect.y - margin, rect.y + rect.height + margin
  x0, x1, y0, y1 = sx[:-1], sx[1:], sy[:-1], sy[1:]
  visible = (np.maximum(x0, x1) >= left) & (np.minimum(x0, x1) <= right) & \
            (np.maximum(y0, y1) >= top) & (np.minimum(y0, y1) <= bottom)
  indices = np.flatnonzero(visible)
  if len(indices) == 0:
    return []
  breaks = np.flatnonzero(np.diff(indices) > 1)
  starts = np.concatenate(([indices[0]], indices[breaks + 1]))
  ends = np.concatenate((indices[breaks], [indices[-1]]))
  return [(int(s), int(e) + 1) for s, e in zip(starts, ends, strict=True)]


def _draw_polyline(sx: np.ndarray, sy: np.ndarray, start: int, end: int, styles: Sequence[tuple[float, rl.Color]],
                   caps: tuple[bool, bool] = (False, False), grid: float = 3.0) -> None:
  """Draw points start..end once per (thickness, color) style, e.g. a casing then a fill."""
  xs, ys = sx[start:end + 1], sy[start:end + 1]
  if len(xs) < 2:
    return
  # Drop consecutive points that land in the same few-pixel cell; zoomed-out routes collapse to a handful.
  cells = np.floor(np.stack((xs, ys), axis=1) / grid)
  keep = np.ones(len(xs), dtype=bool)
  keep[1:-1] = np.any(cells[1:-1] != cells[:-2], axis=1)
  points = np.ascontiguousarray(np.stack((xs[keep], ys[keep]), axis=1), dtype=np.float32)
  count = len(points)
  if count < 2:
    return
  pointer = rl.ffi.cast("Vector2 *", rl.ffi.from_buffer(points))
  ends = [rl.Vector2(float(points[i, 0]), float(points[i, 1])) for i, cap in ((0, caps[0]), (-1, caps[1])) if cap]
  for thick, color in styles:
    rl.draw_spline_linear(pointer, count, thick, color)
    for point in ends:
      rl.draw_circle_v(point, thick / 2.0, color)


def _draw_no_map_icon(x: float, y: float, color: rl.Color) -> None:
  """A folded three-panel map centred at x, y, struck through."""
  half_w, half_h, fold = 15.0, 13.0, 4.0
  xs = [x - half_w + i * 2 * half_w / 3 for i in range(4)]
  tops = [rl.Vector2(px, y - half_h + (fold if i % 2 == 0 else 0)) for i, px in enumerate(xs)]
  bottoms = [rl.Vector2(px, y + half_h - (0 if i % 2 == 0 else fold)) for i, px in enumerate(xs)]
  for i in range(3):
    rl.draw_line_ex(tops[i], tops[i + 1], 3.0, color)
    rl.draw_line_ex(bottoms[i], bottoms[i + 1], 3.0, color)
  for top, bottom in zip(tops, bottoms, strict=True):
    rl.draw_line_ex(top, bottom, 3.0, color)
  start, end = rl.Vector2(x - 18, y - 18), rl.Vector2(x + 18, y + 18)
  rl.draw_line_ex(start, end, 9.0, CARD_BG)  # a gap either side of the slash
  rl.draw_line_ex(start, end, 3.5, color)


def _triangle(a: rl.Vector2, b: rl.Vector2, c: rl.Vector2, color: rl.Color) -> None:
  """raylib culls clockwise triangles; order the vertices so any orientation draws."""
  if (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x) > 0:
    b, c = c, b
  rl.draw_triangle(a, b, c, color)


def acquisition_progress(satellites: int | None) -> float:
  """How full the "Finding GPS" bar is: satellites locked, out of the few a good fix needs."""
  if not satellites:
    return 0.04
  return max(0.04, min(1.0, satellites / ACQUIRE_GOOD_SATELLITES))


def _elapsed_text(seconds: float) -> str:
  seconds = max(0, int(seconds))
  return f"{seconds // 60}:{seconds % 60:02d}"


class GpsAcquisition:
  """Satellites the receiver is tracking while it has no fix, for the map's progress bar.

  u-blox reports a satellite count with every solution. The comma's Qualcomm receiver
  does not, so its per-constellation measurement reports are counted instead (a
  satellite in track or track-verify). Subscribed only while a fix is missing.
  """

  TRACKING_STATES = (4, 5)  # SVObservationState.trackVerify, .track

  def __init__(self, sm_factory=None):
    self._sm_factory = sm_factory
    self._sm = None
    self._by_source: dict[int, tuple[int, float]] = {}
    self._external: tuple[int, float] | None = None
    self.since: float | None = None

  def _ensure(self):
    if self._sm is None:
      if self._sm_factory is not None:
        self._sm = self._sm_factory()
      else:
        import cereal.messaging as messaging
        self._sm = messaging.SubMaster(["gpsLocationExternal", "qcomGnss"])
    return self._sm

  def reset(self) -> None:
    self._by_source.clear()
    self._external = None
    self.since = None

  def update(self, now: float) -> None:
    if self.since is None:
      self.since = now
    sm = self._ensure()
    sm.update(0)
    if sm.updated["gpsLocationExternal"]:
      self._external = (int(sm["gpsLocationExternal"].satelliteCount), now)
    if sm.updated["qcomGnss"]:
      gnss = sm["qcomGnss"]
      if gnss.which() == "measurementReport":
        report = gnss.measurementReport
        tracked = sum(1 for sv in report.sv if int(sv.observationState) in self.TRACKING_STATES)
        self._by_source[int(report.source)] = (tracked, now)

  def satellites(self, now: float) -> int | None:
    """Satellites currently tracked, or None when no receiver has reported recently."""
    if self._external is not None and now - self._external[1] < ACQUIRE_SATELLITE_WINDOW:
      return self._external[0]
    recent = [count for count, at in self._by_source.values() if now - at < ACQUIRE_SATELLITE_WINDOW]
    return sum(recent) if recent else None


@dataclass
class GpsFix:
  latitude: float
  longitude: float
  bearing: float
  speed: float
  received: float  # local monotonic time of the fix (dead reckoning starts here)
  fresh: bool
  published: float = 0.0  # when the planner last republished it (freshness)
  turn_rate: float = 0.0  # deg/s, from the last two fixes; dead reckoning follows the curve


class NavMapView(Widget):
  def __init__(self, *, show_guidance: bool = True, clip: bool = True, show_navigation_waiting: bool = False,
               heading_up: bool = True):
    super().__init__()
    self._show_guidance = show_guidance
    self._clip = clip  # off when the map owns its whole render target
    self._show_navigation_waiting = show_navigation_waiting
    self._heading_up = heading_up
    self._navigation_requested = False
    self._dirty = True
    self._rendering_prepared = False
    self._animating = False
    self._last_draw = -math.inf
    self._next_draw = -math.inf
    self._overlay_state: tuple | None = None
    # Set by a host that draws a button (the car map's compass): the offline badge sits
    # beneath this rectangle, in overlay coordinates, instead of top-right.
    self.offline_anchor: rl.Rectangle | None = None
    self.status_inset = 0.0  # room a host's top-right button (the car map's sun/moon) keeps clear
    self.toast_anchor: rl.Rectangle | None = None  # that button: its popup hangs below it
    self._toast: tuple[str, float] | None = None  # (text, hide at)
    self._offline_since: float | None = None
    self._tiles: TileTextures | None = None
    self._sm = None
    self._params_memory = Params(memory=True)
    self._params = Params()
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._icons: dict[str, rl.Texture] = {}

    self._camera = Camera()
    self._camera_ready = False
    self._last_frame = time.monotonic()

    self._gps: GpsFix | None = None
    self._last_gps_poll = -math.inf
    self._last_gps_raw = ""
    self._fix_key: tuple | None = None
    self._correction = (0.0, 0.0)  # world units, eased to zero from _correction_at
    self._bearing_correction = 0.0  # degrees, eased out alongside the position correction
    self._correction_at = -math.inf
    self._acquisition = GpsAcquisition()
    self._acquire_polled = -math.inf
    self._acquire_state: tuple | None = None
    self._display_bearing = 0.0
    self._zoom_speed: float | None = None
    self._zoom_time = -math.inf
    self._held_zoom: float | None = None

    self._route_world = np.zeros((0, 2))
    self._route_bounds: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
    self._route_key: tuple | None = None
    self._ended_route_key: tuple | None = None  # a route ended here; navigationd may still resend it
    self._route_received = -math.inf
    self._route_progress = 0
    self._nav: dict | None = None
    self._nav_received = -math.inf
    self._desire = 0
    self._nav_desire = 0

    self._preview_routes: list[np.ndarray] = []
    self._preview_selected = 0
    self._preview_destination: tuple[float, float] | None = None
    self._preview_active = False

  # ── public API ────────────────────────────────────────────────────────────

  def set_preview(self, routes: Sequence[Sequence[tuple[float, float]]], selected: int = 0,
                  destination: tuple[float, float] | None = None) -> None:
    """Show candidate routes (lat, lon lists) north-up, the selected one highlighted."""
    self._preview_routes = [_route_world(route) for route in routes]
    self._preview_selected = max(0, min(selected, len(self._preview_routes) - 1)) if self._preview_routes else 0
    self._preview_destination = destination
    self._preview_active = bool(self._preview_routes) or destination is not None
    self._dirty = True
    if routes:
      # navtilesd saves this route for offline use in the background, even if the car screen closes.
      self._ensure_started()
      try:
        self._tiles.offline_maps.set_preview_route(routes[self._preview_selected])
      except OSError:
        pass

  def clear_preview(self) -> None:
    self._preview_routes = []
    self._preview_destination = None
    self._preview_active = False
    self._dirty = True

  def set_heading_up(self, heading_up: bool) -> None:
    """Choose a rotating heading-up map or a label-readable north-up map."""
    heading_up = bool(heading_up)
    if heading_up != self._heading_up:
      self._heading_up = heading_up
      self._dirty = True

  def update(self) -> None:
    """Advance data (tiles, messages, GPS) without drawing; see needs_redraw."""
    self._update_state()

  def render_prepared(self, rect: rl.Rectangle) -> None:
    """Draw after update(), retaining widget layout/input without polling twice."""
    self._rendering_prepared = True
    try:
      self.render(rect)
    finally:
      self._rendering_prepared = False

  def needs_redraw(self, now: float) -> bool:
    """For callers that cache the map in a texture: is a new frame worth drawing?"""
    since = now - self._last_draw
    if since >= MAP_IDLE_REDRAW:
      return True
    # Keep an absolute schedule. Comparing against the last render's start
    # loses an entire car frame whenever preparation or jitter puts us just
    # short of the interval. Slack absorbs that jitter without raising the
    # average redraw budget.
    if now < self._next_draw - 0.25 / MAP_MAX_FPS:
      return False
    gps = self._gps
    moving = gps is not None and gps.fresh and gps.speed > 0.3 and not self._preview_active
    return self._dirty or self._animating or moving

  def _record_draw(self, now: float) -> None:
    self._last_draw = now
    interval = 1.0 / MAP_MAX_FPS
    self._next_draw += interval
    if self._next_draw <= now:
      self._next_draw = now + interval

  @property
  def background(self) -> rl.Color:
    return self._tiles.background if self._tiles is not None else MAP_BACKGROUND

  @property
  def offline(self) -> bool:
    return self._tiles is not None and self._tiles.service.offline

  def show_event(self):
    super().show_event()
    self._offline_since = None  # each showing gets its full offline badge again

  @property
  def theme(self) -> str:
    return self._tiles.theme if self._tiles is not None else "auto"

  def cycle_theme(self, now: float | None = None) -> bool:
    """The sun/moon button: map colors auto, light, dark, round again. Light or dark is skipped
    when its map can't be shown here, and the popup says why."""
    self._ensure_started()
    now = time.monotonic() if now is None else now
    current = self._tiles.theme
    index = THEME_CYCLE.index(current) if current in THEME_CYCLE else -1
    skipped = None
    for step in (1, 2):
      theme = THEME_CYCLE[(index + step) % len(THEME_CYCLE)]
      # Auto has both maps: it shows whichever of them it can, so it is always allowed.
      problem = None if theme == "auto" else self._tiles.style_problem(self._tiles.offline_maps.display_style(theme=theme))
      if problem is None:
        try:
          self._tiles.set_theme(theme)
        except OSError:
          self._show_toast("Couldn't save the map colors.", now)
          return False
        if skipped is not None:
          self._show_toast(f"{skipped} Showing {THEME_NAMES[theme]} instead.", now)
        self._dirty = True
        return True
      skipped = skipped or problem
    self._show_toast(skipped, now)
    return False

  def _show_toast(self, text: str, now: float) -> None:
    self._toast = (text, now + TOAST_SECONDS)
    self._dirty = True

  def _toast_text(self, now: float) -> str | None:
    return self._toast[0] if self._toast is not None and now < self._toast[1] else None

  def offline_badge_lift(self, now: float) -> float:
    """How far the anchor must rise so the offline badge beneath it clears the trip bar."""
    if self._offline_since is None or not self._show_guidance or self._preview_active or not self._nav_active(now):
      return 0.0
    return OFFLINE_BADGE_HEIGHT + OFFLINE_BADGE_GAP

  # ── state ─────────────────────────────────────────────────────────────────

  def _ensure_started(self) -> None:
    if self._tiles is None:
      self._tiles = shared_tiles()
    if self._sm is None:
      import cereal.messaging as messaging
      self._sm = messaging.SubMaster(["navInstruction", "navRoute", "starpilotModelV2"])

  def _update_state(self) -> None:
    if self._rendering_prepared:
      return
    self._ensure_started()
    if self._tiles.upload():
      self._dirty = True
    self._sm.update(0)
    now = time.monotonic()

    if self._sm.updated["navRoute"]:
      message = self._sm["navRoute"]
      points = [(c.latitude, c.longitude) for c in message.coordinates] if self._sm.valid["navRoute"] else []
      self._route_received = now
      key = (len(points), points[0], points[-1]) if points else None
      if key is None or key != self._ended_route_key:
        self._ended_route_key = None
        if key != self._route_key:
          self._route_key = key
          self._route_world = _route_world(points)
          self._route_progress = 0

    if self._sm.updated["navInstruction"]:
      message = self._sm["navInstruction"]
      if self._ended_route_key is not None:
        pass  # sent before navigationd saw the route end
      elif self._sm.valid["navInstruction"]:
        all_maneuvers = list(message.allManeuvers)
        upcoming = all_maneuvers[1] if len(all_maneuvers) > 1 else None
        self._nav = {
          "primary": message.maneuverPrimaryText,
          "secondary": message.maneuverSecondaryText,
          "distance": float(message.maneuverDistance),
          "type": message.maneuverType,
          "modifier": message.maneuverModifier,
          "remaining_distance": float(message.distanceRemaining),
          "remaining_time": float(message.timeRemaining),
          "next_type": upcoming.type if upcoming is not None else "",
          "next_modifier": upcoming.modifier if upcoming is not None else "",
        }
        self._nav_received = now
      else:
        self._nav = None

    if self._sm.updated["starpilotModelV2"]:
      model = self._sm["starpilotModelV2"]
      self._desire = int(model.desire)
      self._nav_desire = int(model.navDesire)
    elif not ui_state.started:
      self._desire = self._nav_desire = 0

    if now - self._last_gps_poll >= GPS_POLL_SECONDS:
      self._last_gps_poll = now
      self._poll_gps(now)
      requested = parse_destination_json(self._params.get("NavDestination", encoding="utf-8")) is not None
      if self._navigation_requested and not requested:
        self._end_route()
      elif requested and not self._navigation_requested:
        self._ended_route_key = None  # a destination again: navigationd's route is current
      self._navigation_requested = requested

    self._update_acquisition(now)

    if not self._offline_badge_shown():
      self._offline_since = None
    elif self._offline_since is None:
      self._offline_since = now

    overlay = self._overlay_content(now)
    if overlay != self._overlay_state:
      self._overlay_state = overlay
      self._dirty = True

  def _overlay_content(self, now: float) -> tuple:
    """Everything the overlays show, as text. navigationd resends its instruction every second
    with the same words; redrawing the cached overlay for each copy cost the car view a frame."""
    nav = self._nav if self._nav_active(now) else None
    guidance = None
    if nav is not None:
      guidance = (nav["primary"], nav["secondary"], nav["type"], nav["modifier"], nav["next_type"], nav["next_modifier"],
                  _format_distance(nav["distance"], ui_state.is_metric), self._trip_texts(nav))
    return (self._route_key, self._gps is not None and self._gps.fresh, self._center_message(), self._status_badges(),
            guidance, desire_line(ui_state.started, self._desire, self._nav_desire, nav), self._preview_active,
            self._route_download(), None if self._offline_since is None else self._offline_collapsed(now),
            self._toast_text(now))

  def _acquiring(self) -> bool:
    """Onroad without a fresh fix. Offroad the GPS receiver is not running at all."""
    return ui_state.started and not self._preview_active and (self._gps is None or not self._gps.fresh)

  def _update_acquisition(self, now: float) -> None:
    if not self._acquiring():
      if self._acquire_state is not None or self._acquisition.since is not None:
        self._acquisition.reset()
        self._acquire_state = None
      return
    if now - self._acquire_polled < ACQUIRE_POLL_SECONDS:
      return
    self._acquire_polled = now
    try:
      self._acquisition.update(now)
    except Exception:
      pass  # a missing service must never take the map down
    since = self._acquisition.since if self._acquisition.since is not None else now
    self._acquire_state = (self._acquisition.satellites(now), int(now - since))

  def _acquisition_text(self) -> tuple[str, float]:
    """(detail, progress) for the "Finding GPS" card and badge."""
    satellites, elapsed = self._acquire_state or (None, 0)
    if satellites is None:
      detail = f"Searching for satellites  •  {_elapsed_text(elapsed)}"
    else:
      detail = f"{satellites} satellite{'s' if satellites != 1 else ''} locked  •  {_elapsed_text(elapsed)}"
    return detail, acquisition_progress(satellites)

  def _nav_active(self, now: float) -> bool:
    return self._nav is not None and now - self._nav_received < NAV_STALE_SECONDS

  def _poll_gps(self, now: float) -> None:
    raw = self._params_memory.get("LastGPSPosition", encoding="utf-8") or ""
    fresh = True
    if not raw:
      raw = self._params.get("LastGPSPosition", encoding="utf-8") or ""
      fresh = False
    if not raw:
      self._gps = None
      return
    if raw == self._last_gps_raw and self._gps is not None:
      if now - self._gps.published > GPS_STALE_SECONDS:
        self._gps.fresh = False
      return
    self._last_gps_raw = raw
    try:
      state = json.loads(raw) if isinstance(raw, str) else raw
      latitude, longitude = float(state["latitude"]), float(state["longitude"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
      return
    if not (math.isfinite(latitude) and math.isfinite(longitude)) or (abs(latitude) < 1e-6 and abs(longitude) < 1e-6):
      return
    bearing = float(state.get("bearing", 0.0) or 0.0)
    bearing = bearing if math.isfinite(bearing) else 0.0
    speed = max(0.0, float(state.get("speed", 0.0) or 0.0))
    updated = float(state.get("updatedAtMonotonic", 0.0) or 0.0)
    fresh = fresh and bool(state.get("hasFix", True)) and (updated <= 0.0 or now - updated < GPS_STALE_SECONDS)
    # Starpilot Auto polls at 5 Hz while positions are published at 4 Hz. Starting dead
    # reckoning at read time instead of publish time introduces periodic backsteps.
    published = updated if ui_state.starpilot_auto_car_view and 0.0 < updated <= now else now

    fix_key = (latitude, longitude, bearing)
    if self._gps is not None and self._gps.fresh and fix_key == self._fix_key:
      # The planner republishes the last fix at 4 Hz with a new timestamp while the
      # receiver may only produce one a second. Restarting dead reckoning from the
      # old position each time made the car step back and stall.
      self._gps.speed, self._gps.fresh, self._gps.published = speed, fresh, published
      return

    previous = self._gps if self._gps is not None and self._gps.fresh and fresh else None
    before = self._car_world(published) if previous is not None else None
    before_heading = self._heading(published) if previous is not None else None
    turn_rate = 0.0
    if previous is not None and speed >= TURN_RATE_MIN_SPEED and 0.2 <= published - previous.received <= DEAD_RECKON_LIMIT:
      # Heading changes once a second while turning; following that curve between fixes keeps
      # the car off the tangent, whose error the next fix had to pull back each second.
      turn_rate = _angle_delta(bearing, previous.bearing) / (published - previous.received)
      turn_rate = max(-TURN_RATE_MAX, min(TURN_RATE_MAX, turn_rate))
    self._fix_key = fix_key
    self._gps = GpsFix(latitude, longitude, bearing, speed, published, fresh, published, turn_rate)
    self._correction, self._correction_at, self._bearing_correction = (0.0, 0.0), -math.inf, 0.0
    if before is not None:
      after = self._car_world(published)
      dx, dy = before[0] - after[0], before[1] - after[1]
      if math.hypot(dx, dy) * meters_per_world_unit(latitude) <= CORRECTION_MAX_METERS:
        self._correction, self._correction_at = (dx, dy), published
        self._bearing_correction = _angle_delta(before_heading, bearing)
    self._update_route_progress()

  def _car_world(self, now: float) -> tuple[float, float] | None:
    gps = self._gps
    if gps is None:
      return None
    x, y = world_xy(gps.latitude, gps.longitude)
    if gps.fresh and gps.speed > 0.5:
      # Move along the heading between fixes so the map glides instead of stepping once a second.
      dt = max(0.0, min(DEAD_RECKON_LIMIT, now - gps.received))
      scale = gps.speed / meters_per_world_unit(gps.latitude)
      start = math.radians(gps.bearing)
      rate = math.radians(gps.turn_rate)
      if abs(rate) < 1e-4:
        x += math.sin(start) * scale * dt
        y -= math.cos(start) * scale * dt
      else:  # along the arc the car is turning on
        end = start + rate * dt
        x += (math.cos(start) - math.cos(end)) * scale / rate
        y -= (math.sin(end) - math.sin(start)) * scale / rate
    if gps.fresh and now >= self._correction_at:
      # Ease out the gap between where dead reckoning had the car and the new fix.
      fade = math.exp(-(now - self._correction_at) / CORRECTION_TAU)
      x += self._correction[0] * fade
      y += self._correction[1] * fade
    return x, y

  def _heading(self, now: float) -> float:
    """The fix's bearing, turned on at its turn rate and with a new fix's disagreement eased in."""
    gps = self._gps
    if gps is None:
      return 0.0
    heading = gps.bearing
    if gps.fresh:
      heading += gps.turn_rate * max(0.0, min(DEAD_RECKON_LIMIT, now - gps.received))
      if now >= self._correction_at:
        heading += self._bearing_correction * math.exp(-(now - self._correction_at) / CORRECTION_TAU)
    return heading % 360.0

  def _end_route(self) -> None:
    """Drop the route as soon as its destination is removed.

    Ending a route removes NavDestination at once, but navigationd runs at 1 Hz:
    its empty navRoute lands up to a second later, and a republish of the old
    route can land first, so waiting on it left the blue line up after the route ended.
    """
    if self._route_key is not None:
      self._ended_route_key = self._route_key
    self._route_key = None
    self._route_world = np.zeros((0, 2))
    self._route_progress = 0
    self._nav = None
    self._dirty = True

  def _route_live(self, now: float) -> bool:
    return len(self._route_world) >= 2 and now - self._route_received <= ROUTE_STALE_SECONDS

  def _shown_car(self, now: float) -> tuple[float, float] | None:
    """Where the marker and the follow camera sit: pulled onto the route line near it.

    The raw fix is a lane or two off the route's centreline, which left the arrow
    beside the blue line rather than on it.
    """
    car = self._car_world(now)
    if car is None or self._preview_active or not self._route_live(now):
      return car
    at_car = self._route_split(now)
    if at_car is None:
      return car
    point = at_car[1]
    dx, dy = float(point[0]) - car[0], float(point[1]) - car[1]
    meters = math.hypot(dx, dy) * meters_per_world_unit(self._gps.latitude)
    pull = min(1.0, max(0.0, (ROUTE_SNAP_RELEASE_METERS - meters) / (ROUTE_SNAP_RELEASE_METERS - ROUTE_SNAP_METERS)))
    return car[0] + dx * pull, car[1] + dy * pull

  def _route_split(self, now: float) -> tuple[int, np.ndarray] | None:
    """(segment index, world point): where the car sits on the route, between vertices.

    Splitting at the nearest vertex made the blue line vanish a whole segment at a
    time, often ahead of the car on long straight segments.
    """
    route = self._route_world
    car = self._car_world(now)
    if car is None or len(route) < 2:
      return None
    start = max(0, self._route_progress - 2)
    end = min(len(route) - 1, self._route_progress + 40)
    if end <= start:
      return None
    a, b = route[start:end], route[start + 1:end + 1]
    ab = b - a
    lengths = np.sum(ab * ab, axis=1)
    lengths[lengths == 0.0] = 1e-30
    t = np.clip(np.sum((np.asarray(car) - a) * ab, axis=1) / lengths, 0.0, 1.0)
    projected = a + ab * t[:, None]
    index = int(np.argmin(np.sum((projected - car) ** 2, axis=1)))
    return start + index, projected[index]

  def _update_route_progress(self) -> None:
    if self._gps is None or len(self._route_world) < 2:
      return
    car = np.array(world_xy(self._gps.latitude, self._gps.longitude))
    start = max(0, self._route_progress - 20)
    window = self._route_world[start:start + 400]
    distances = np.sum((window - car) ** 2, axis=1)
    nearest = start + int(np.argmin(distances))
    if nearest < self._route_progress - 20 or nearest > self._route_progress + 380:
      nearest = int(np.argmin(np.sum((self._route_world - car) ** 2, axis=1)))
    self._route_progress = nearest

  # ── camera ────────────────────────────────────────────────────────────────

  @staticmethod
  def _tile_scale() -> float:
    # Draw tiles near one tile pixel per physical pixel: the car view renders a
    # 1080-high UI into a smaller screen, and map labels shrink with it otherwise.
    return max(1.0, min(2.0, 1.0 / max(0.25, float(getattr(gui_app, "_scale", 1.0) or 1.0))))

  def _target_camera(self, rect: rl.Rectangle, now: float) -> tuple[Camera, tuple[float, float], bool]:
    """(camera, anchor, snap). Preview fits the routes north-up; otherwise follow the car, heading-up or north-up."""
    tile_scale = self._tile_scale()
    center = (rect.x + rect.width / 2.0, rect.y + rect.height / 2.0)
    car = self._shown_car(now)

    if self._preview_active:
      pieces = [route for route in self._preview_routes if len(route)]
      if self._preview_destination is not None:
        pieces.append(np.array([world_xy(*self._preview_destination)]))
      if car is not None:
        pieces.append(np.array([car]))
      if pieces:
        points = np.concatenate(pieces)
        min_x, min_y = points.min(axis=0)
        max_x, max_y = points.max(axis=0)
        pad = 90.0
        span_x, span_y = max(max_x - min_x, 1e-7), max(max_y - min_y, 1e-7)
        fit = min((rect.width - 2 * pad) / (span_x * tile_scale), (rect.height - 2 * pad) / (span_y * tile_scale))
        zoom = max(3.0, min(PREVIEW_MAX_ZOOM, math.log2(max(fit, 1e-9))))
        return Camera((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, zoom, 0.0), center, False

    if car is None:
      return Camera(self._camera.x, self._camera.y, 4.0 if not self._camera_ready else self._camera.zoom, 0.0), center, False

    gps = self._gps
    if gps is not None and gps.fresh and gps.speed > 1.5:
      self._display_bearing = self._heading(now)
    zoom = self._follow_zoom(gps.speed if gps is not None and gps.fresh else None, now)
    # Raster-tile labels rotate with the map. North-up keeps them readable and
    # centers the car so every travel direction has equal look-ahead room.
    anchor = (center[0], rect.y + rect.height * FOLLOW_ANCHOR_Y) if self._heading_up else center
    bearing = self._display_bearing if self._heading_up else 0.0
    return Camera(car[0], car[1], zoom, bearing), anchor, True

  def _follow_zoom(self, speed: float | None, now: float) -> float:
    """Speed-based zoom, damped so ordinary speed changes do not pump the map in and out."""
    dt = max(0.0, min(1.0, now - self._zoom_time))
    self._zoom_time = now
    if speed is not None:
      if self._zoom_speed is None:
        self._zoom_speed = speed
      else:
        tau = ZOOM_SPEED_TAU_UP if speed > self._zoom_speed else ZOOM_SPEED_TAU_DOWN
        self._zoom_speed += (speed - self._zoom_speed) * (1.0 - math.exp(-dt / tau))
    # Without a fresh fix, hold the current zoom rather than snapping to a default.
    wanted = float(np.interp(self._zoom_speed or 0.0, FOLLOW_SPEEDS, FOLLOW_ZOOMS))
    if self._held_zoom is None or abs(wanted - self._held_zoom) >= ZOOM_HOLD:
      self._held_zoom = wanted
    return self._held_zoom

  def _step_camera(self, target: Camera, dt: float, follow: bool) -> None:
    if not self._camera_ready:
      self._camera = Camera(target.x, target.y, target.zoom, target.bearing)
      self._camera_ready = True
      return
    self._animating = abs(target.zoom - self._camera.zoom) > 0.01 or abs(_angle_delta(target.bearing, self._camera.bearing)) > 0.3 or \
      (not follow and abs(target.x - self._camera.x) + abs(target.y - self._camera.y) > 1e-9)
    alpha = 1.0 - math.exp(-dt * 5.0)
    if follow:
      # Position already glides via dead reckoning; lagging it would pull the car off its anchor.
      self._camera.x, self._camera.y = target.x, target.y
    else:
      far = abs(target.x - self._camera.x) + abs(target.y - self._camera.y) > 4.0 / (2.0 ** min(self._camera.zoom, target.zoom))
      if far:
        self._camera.x, self._camera.y = target.x, target.y
      else:
        self._camera.x += (target.x - self._camera.x) * alpha
        self._camera.y += (target.y - self._camera.y) * alpha
    zoom_alpha = 1.0 - math.exp(-dt * ZOOM_EASE) if follow else alpha
    self._camera.zoom += (target.zoom - self._camera.zoom) * zoom_alpha
    self._camera.bearing = (self._camera.bearing + _angle_delta(target.bearing, self._camera.bearing) * alpha) % 360.0

  # ── drawing ───────────────────────────────────────────────────────────────

  def _advance_camera(self, rect: rl.Rectangle, now: float):
    dt = max(0.0, min(0.5, now - self._last_frame))
    self._last_frame = now
    target, anchor, follow = self._target_camera(rect, now)
    self._step_camera(target, dt, follow)
    return anchor

  def _render(self, rect: rl.Rectangle):
    now = time.monotonic()
    anchor = self._advance_camera(rect, now)
    self._record_draw(now)
    self._dirty = False
    camera = self._camera
    tile_scale = self._tile_scale()

    rl.draw_rectangle_rec(rect, self.background)
    if self._clip:
      rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    try:
      if self._gps is not None or self._preview_active:
        self._draw_world(rect, camera, anchor, tile_scale, now)
        self._draw_car(camera, anchor, tile_scale, now)
    finally:
      if self._clip:
        rl.end_scissor_mode()

    self._draw_overlays(rect, now)

  def _draw_world(self, rect, camera, anchor, tile_scale, now: float | None = None):
    if self._gps is not None or self._preview_active:
      self._draw_tiles(rect, camera, anchor, tile_scale)
      self._draw_routes(rect, camera, anchor, tile_scale, time.monotonic() if now is None else now)
      self._draw_destination(camera, anchor, tile_scale)

  def _draw_overlays(self, rect: rl.Rectangle, now: float):
    center_message = self._center_message()
    if center_message is not None:
      self._draw_center_message(rect, *center_message)
    self._draw_status(rect)
    self._draw_offline_badge(now)
    self._draw_toast(rect, now)
    if self._show_guidance and not self._preview_active:
      self._draw_guidance(rect, now)
      self._draw_route_download(rect, now)
    self._draw_attribution(rect)

  def _draw_tiles(self, rect: rl.Rectangle, camera: Camera, anchor: tuple[float, float], tile_scale: float) -> None:
    level = int(max(0, min(18, round(camera.zoom))))
    corners = [camera.to_world(x, y, anchor, tile_scale) for x, y in (
      (rect.x, rect.y), (rect.x + rect.width, rect.y), (rect.x, rect.y + rect.height), (rect.x + rect.width, rect.y + rect.height))]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    keys = tiles_covering(min(xs), min(ys), max(xs), max(ys), level)
    if len(keys) > 48:  # extreme zoom-out mid-animation: skip a frame of tiles rather than stall
      return

    center_world = camera.to_world(anchor[0], anchor[1], anchor, tile_scale)
    world_tile = TILE_SIZE / (1 << level)
    keys.sort(key=lambda k: ((k.x + 0.5) * world_tile - center_world[0]) ** 2 + ((k.y + 0.5) * world_tile - center_world[1]) ** 2)
    self._tiles.want(keys)

    # Draw in tile-local coordinates relative to the camera so float32 never sees huge values.
    scale = (2.0 ** (camera.zoom - level)) * tile_scale
    cx, cy = camera.x * (1 << level), camera.y * (1 << level)
    rl.rl_push_matrix()
    rl.rl_translatef(anchor[0], anchor[1], 0.0)
    rl.rl_rotatef(-camera.bearing, 0.0, 0.0, 1.0)
    rl.rl_scalef(scale, scale, 1.0)
    origin = rl.Vector2(0.0, 0.0)
    for key in keys:
      found = self._tiles.best(key)
      if found is None:
        continue
      texture, source = found
      dest = rl.Rectangle(key.x * TILE_SIZE - cx, key.y * TILE_SIZE - cy, TILE_SIZE + 0.75, TILE_SIZE + 0.75)
      rl.draw_texture_pro(texture, source, dest, origin, 0.0, rl.WHITE)
    rl.rl_pop_matrix()

  def _project(self, points: np.ndarray, camera: Camera, anchor: tuple[float, float], tile_scale: float):
    return camera.to_screen(points[:, 0], points[:, 1], anchor, tile_scale)

  def _route_slice(self, rect: rl.Rectangle, camera: Camera, anchor: tuple[float, float], tile_scale: float,
                   margin: float) -> slice:
    """Conservatively trim offscreen route ends before Starpilot Auto's per-frame projection."""
    points = self._route_world
    if self._route_bounds is None or self._route_bounds[0] is not points:
      starts = np.arange(0, len(points) - 1, ROUTE_CHUNK_SEGMENTS)
      # Include both ends of every segment, including those crossing a chunk boundary.
      low = np.minimum.reduceat(np.minimum(points[:-1], points[1:]), starts, axis=0)
      high = np.maximum.reduceat(np.maximum(points[:-1], points[1:]), starts, axis=0)
      self._route_bounds = points, low, high
    _, low, high = self._route_bounds
    corners = np.array([camera.to_world(x, y, anchor, tile_scale) for x in (rect.x - margin, rect.x + rect.width + margin)
                        for y in (rect.y - margin, rect.y + rect.height + margin)])
    visible = np.flatnonzero(np.all(high >= corners.min(axis=0), axis=1) & np.all(low <= corners.max(axis=0), axis=1))
    if not len(visible):
      return slice(0, 0)
    # Keep everything between the first and last candidates: routes can leave and re-enter the view.
    return slice(int(visible[0]) * ROUTE_CHUNK_SEGMENTS, min(len(points), (int(visible[-1]) + 1) * ROUTE_CHUNK_SEGMENTS + 1))

  def _draw_routes(self, rect: rl.Rectangle, camera: Camera, anchor: tuple[float, float], tile_scale: float,
                   now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    margin = 40.0
    if self._preview_active:
      for index, route in enumerate(self._preview_routes):
        if index == self._preview_selected or len(route) < 2:
          continue
        sx, sy = self._project(route, camera, anchor, tile_scale)
        for start, end in _visible_runs(sx, sy, rect, margin):
          _draw_polyline(sx, sy, start, end, ((13.0, ROUTE_ALTERNATE_CASING), (7.0, ROUTE_ALTERNATE)))
      selected = self._preview_routes[self._preview_selected] if self._preview_routes else None
      if selected is not None and len(selected) >= 2:
        sx, sy = self._project(selected, camera, anchor, tile_scale)
        last = len(sx) - 1
        for start, end in _visible_runs(sx, sy, rect, margin):
          _draw_polyline(sx, sy, start, end, ((15.0, ROUTE_CASING), (9.0, ROUTE_FILL)), caps=(start == 0, end == last))
      return

    if not self._route_live(now):
      return
    route_slice = slice(0, None)
    # Short routes are cheaper to project directly than to search the bounds.
    if ui_state.starpilot_auto_car_view and len(self._route_world) >= 8192:
      route_slice = self._route_slice(rect, camera, anchor, tile_scale, margin)
    sx, sy = self._project(self._route_world[route_slice], camera, anchor, tile_scale)
    offset = route_slice.start or 0
    last = len(self._route_world) - 1 - offset
    split = max(0, min(self._route_progress, len(self._route_world) - 1)) - offset
    at_car = self._route_split(now)
    if at_car is not None:
      segment, point = at_car
      local = segment - offset
      if 0 <= local < len(sx) - 1:
        # Split exactly under the car: traveled up to it, blue from it.
        px, py = camera.to_screen(point[0], point[1], anchor, tile_scale)
        sx, sy = np.insert(sx, local + 1, px), np.insert(sy, local + 1, py)
        split, last = local + 1, last + 1
      else:
        split = local + 1
    # Only the road ahead is drawn: the part already driven trailed behind the marker as a grey tail.
    for start, end in _visible_runs(sx, sy, rect, margin):
      if end > split:
        begin = max(start, split)
        _draw_polyline(sx, sy, begin, end, ((18.0, ROUTE_CASING), (11.0, ROUTE_FILL)), caps=(begin == split, end == last))

  def _draw_destination(self, camera: Camera, anchor: tuple[float, float], tile_scale: float) -> None:
    if self._preview_active:
      if self._preview_destination is not None:
        destination = world_xy(*self._preview_destination)
      elif self._preview_routes and len(self._preview_routes[self._preview_selected]):
        destination = tuple(self._preview_routes[self._preview_selected][-1])
      else:
        return
    elif len(self._route_world) and time.monotonic() - self._route_received <= ROUTE_STALE_SECONDS:
      destination = tuple(self._route_world[-1])
    else:
      return
    x, y = camera.to_screen(destination[0], destination[1], anchor, tile_scale)
    rl.draw_circle_v(rl.Vector2(x, y), 20.0, rl.Color(255, 255, 255, 255))
    rl.draw_circle_v(rl.Vector2(x, y), 14.0, DEST_FILL)
    rl.draw_circle_v(rl.Vector2(x, y), 5.0, rl.Color(255, 255, 255, 255))

  def _draw_car(self, camera: Camera, anchor: tuple[float, float], tile_scale: float, now: float) -> None:
    car = self._shown_car(now)
    if car is None:
      return
    x, y = camera.to_screen(car[0], car[1], anchor, tile_scale)
    fresh = self._gps is not None and self._gps.fresh
    heading = math.radians((self._display_bearing if fresh else 0.0) - camera.bearing)
    self._draw_car_shape(x, y, heading, fresh)

  @staticmethod
  def _draw_car_shape(x: float, y: float, heading: float, fresh: bool) -> None:
    center = rl.Vector2(x, y)
    rl.draw_circle_v(center, 34.0, rl.Color(64, 150, 255, 50 if fresh else 25))
    if not fresh:
      rl.draw_circle_v(center, 13.0, rl.Color(255, 255, 255, 255))
      rl.draw_circle_v(center, 9.0, rl.Color(130, 140, 160, 255))
      return

    def point(forward: float, side: float) -> rl.Vector2:
      return rl.Vector2(x + math.sin(heading) * forward + math.cos(heading) * side,
                        y - math.cos(heading) * forward + math.sin(heading) * side)

    outline = [point(31, 0), point(-22, -23), point(-12, 0), point(-22, 23)]
    inner = [point(24, 0), point(-16, -17), point(-8, 0), point(-16, 17)]
    for shape, color in ((outline, CAR_FILL), (inner, CAR_ACCENT)):
      _triangle(shape[0], shape[1], shape[2], color)
      _triangle(shape[0], shape[2], shape[3], color)

  def _draw_cached_car(self, camera: Camera, anchor: tuple[float, float]) -> None:
    """Starpilot Auto's follow view keeps the marker anchored, even when the map cache is held."""
    if self._gps is None:
      return
    fresh = self._gps.fresh
    heading = (self._display_bearing if fresh else 0.0) - camera.bearing
    texture = gui_app.cached_render_texture(f"starpilot_auto_map_car:{fresh}", 72, 72,
                                           lambda: self._draw_car_shape(36, 36, 0, fresh), supersample=2)
    if texture is None:
      rl.rl_set_blend_factors_separate(rl.RL_SRC_ALPHA, rl.RL_ONE_MINUS_SRC_ALPHA, rl.RL_ONE, rl.RL_ONE_MINUS_SRC_ALPHA,
                                      rl.RL_FUNC_ADD, rl.RL_FUNC_ADD)
      rl.begin_blend_mode(rl.BlendMode.BLEND_CUSTOM_SEPARATE)
      self._draw_car_shape(*anchor, math.radians(heading), fresh)
      rl.end_blend_mode()
      return
    rl.begin_blend_mode(rl.BlendMode.BLEND_ALPHA_PREMULTIPLY)
    rl.draw_texture_pro(texture, rl.Rectangle(0, 0, texture.width, -texture.height),
                        rl.Rectangle(*anchor, 72, 72), rl.Vector2(36, 36), heading, rl.WHITE)
    rl.end_blend_mode()

  # ── overlays ──────────────────────────────────────────────────────────────

  def _text(self, text: str, x: float, y: float, size: int, color: rl.Color, bold: bool = False) -> None:
    rl.draw_text_ex(self._font_bold if bold else self._font_medium, text, rl.Vector2(x, y), size, 0, color)

  def _text_width(self, text: str, size: int, bold: bool = False) -> float:
    return measure_text_cached(self._font_bold if bold else self._font_medium, text, size).x

  def _fit_text(self, text: str, size: int, width: float, bold: bool = False) -> str:
    if self._text_width(text, size, bold) <= width:
      return text
    while text and self._text_width(text + "...", size, bold) > width:
      text = text[:-1]
    return text.rstrip() + "..."

  def _card(self, rect: rl.Rectangle) -> None:
    rl.draw_rectangle_rounded(rect, min(0.5, 36.0 / max(rect.height, 1.0)), 12, CARD_BG)
    rl.draw_rectangle_rounded_lines_ex(rect, min(0.5, 36.0 / max(rect.height, 1.0)), 12, 2, CARD_BORDER)

  def _icon(self, maneuver_type: str, modifier: str) -> rl.Texture:
    normalized = _normalize_maneuver_type(maneuver_type)
    if modifier == "uturn":
      name = "direction_uturn.png"
    else:
      suffix = _modifier_suffix(modifier)
      name = f"direction_{normalized}.png" if not suffix else f"direction_{normalized}_{suffix}.png"
    if not (ASSETS_PATH / name).exists():
      name = FALLBACK_ICON
    texture = self._icons.get(name)
    if texture is None:
      texture = rl.load_texture(str(ASSETS_PATH / name))
      rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
      self._icons[name] = texture
    return texture

  def _draw_icon(self, texture: rl.Texture, x: float, y: float, size: float) -> None:
    rl.draw_texture_pro(texture, rl.Rectangle(0, 0, texture.width, texture.height),
                        rl.Rectangle(x, y, size, size), rl.Vector2(0, 0), 0.0, rl.WHITE)

  def _progress_bar(self, x: float, y: float, width: float, height: float, progress: float) -> None:
    track = rl.Rectangle(x, y, width, height)
    rl.draw_rectangle_rounded(track, 1.0, 8, PROGRESS_TRACK)
    fill = rl.Rectangle(x, y, max(height, width * max(0.0, min(1.0, progress))), height)
    rl.draw_rectangle_rounded(fill, 1.0, 8, PROGRESS_FILL)

  def _draw_center_message(self, rect: rl.Rectangle, title: str, body: str, progress: float | None = None) -> None:
    lines = body.split("\n")
    extra = CENTER_LINE_HEIGHT * (len(lines) - 1)
    width = min(rect.width - 80, 720)
    height = (160 if progress is None else 196) + extra
    card = rl.Rectangle(rect.x + (rect.width - width) / 2, rect.y + rect.height / 2 - height / 2, width, height)
    self._card(card)
    self._text(title, card.x + 36, card.y + 30, 44, TEXT, bold=True)
    for index, line in enumerate(lines):
      self._text(self._fit_text(line, 30, width - 72), card.x + 36, card.y + 94 + index * CENTER_LINE_HEIGHT, 30, SUBTEXT)
    if progress is not None:
      self._progress_bar(card.x + 36, card.y + 146 + extra, width - 72, 14, progress)

  def _center_message(self) -> tuple[str, str] | tuple[str, str, float] | None:
    """(title, body), plus a progress fraction while the GPS is being acquired."""
    if self._preview_active:
      return None
    has_fresh_gps = self._gps is not None and self._gps.fresh
    acquiring = self._acquiring()
    detail, progress = self._acquisition_text() if acquiring else ("", None)
    if self._show_navigation_waiting and self._navigation_requested and not has_fresh_gps:
      if acquiring:
        return "Navigation active", f"Finding GPS to start your route\n{detail}", progress
      return "Navigation active", "Waiting for GPS to start your route."
    if self._gps is None:
      if acquiring:
        return "Finding GPS", detail, progress
      return "Waiting for GPS", "The map appears once the car has a location."
    return None

  def _offline_badge_shown(self) -> bool:
    """Offline with a Mapbox key; without one the missing key is the badge."""
    return self._tiles is not None and self._tiles.has_token and self._tiles.service.offline

  def _offline_collapsed(self, now: float) -> bool:
    return self._offline_since is not None and now - self._offline_since >= OFFLINE_COLLAPSE_SECONDS

  def _status_badges(self) -> tuple[tuple[tuple[str, rl.Color], ...], float | None]:
    """(badges, progress of the last badge's bar or None) for the top-right corner."""
    badges = []
    if self._tiles is not None and not self._tiles.has_token:
      badges.append(("Add a Mapbox key in The Galaxy", BADGE_WARN))
    elif self.offline_anchor is None and self._offline_badge_shown():
      badges.append(("Offline • cached map", BADGE_WARN))
    progress = None
    if self._gps is not None and not self._gps.fresh and not self._preview_active:
      if self._acquiring():
        satellites = (self._acquire_state or (None, 0))[0]
        label = "Finding GPS" if satellites is None else f"Finding GPS  •  {satellites} sat{'s' if satellites != 1 else ''}"
        progress = acquisition_progress(satellites)
        badges.append((label, BADGE_WARN))
      else:
        badges.append(("No GPS fix", BADGE_WARN))
    return tuple(badges), progress

  def _draw_status(self, rect: rl.Rectangle) -> None:
    badges, progress = self._status_badges()
    x = rect.x + rect.width - 24 - self.status_inset
    y = rect.y + 24
    for index, (label, color) in enumerate(badges):
      bar = progress is not None and index == len(badges) - 1
      width = self._text_width(label, 28) + 44
      badge = rl.Rectangle(x - width, y, width, 72 if bar else 56)
      self._card(badge)
      self._text(label, badge.x + 22, badge.y + 13, 28, color)
      if bar:
        self._progress_bar(badge.x + 22, badge.y + 52, width - 44, 8, progress)
      y += badge.height + 12

  def _draw_offline_badge(self, now: float) -> None:
    """Under the anchor (the compass): the words at first, then a crossed-out map icon."""
    anchor = self.offline_anchor
    if anchor is None or self._offline_since is None:
      return
    y = anchor.y + anchor.height + OFFLINE_BADGE_GAP
    if self._offline_collapsed(now):
      center = rl.Vector2(anchor.x + anchor.width / 2, y + OFFLINE_BADGE_HEIGHT / 2)
      rl.draw_circle_v(center, OFFLINE_BADGE_HEIGHT / 2, CARD_BG)
      rl.draw_ring(center, OFFLINE_BADGE_HEIGHT / 2 - 2, OFFLINE_BADGE_HEIGHT / 2, 0, 360, 36, CARD_BORDER)
      _draw_no_map_icon(center.x, center.y, BADGE_WARN)
      return
    label = "Offline • cached map"
    width = self._text_width(label, 28) + 44
    badge = rl.Rectangle(anchor.x + anchor.width - width, y, width, OFFLINE_BADGE_HEIGHT)
    self._card(badge)
    self._text(label, badge.x + 22, badge.y + 13, 28, BADGE_WARN)

  def _draw_toast(self, rect: rl.Rectangle, now: float) -> None:
    """Below the sun/moon button, right-aligned with it, until it times out."""
    text = self._toast_text(now)
    anchor = self.toast_anchor
    if text is None or anchor is None:
      return
    width = min(TOAST_WIDTH, anchor.x + anchor.width - rect.x - 24)
    lines = self._wrap(text, 26, width - 48, max_lines=3)
    width = min(width, max(self._text_width(line, 26) for line in lines) + 48)
    card = rl.Rectangle(anchor.x + anchor.width - width, anchor.y + anchor.height + 12, width, 28 + 34 * len(lines))
    self._card(card)
    for index, line in enumerate(lines):
      self._text(line, card.x + 24, card.y + 14 + 34 * index, 26, TEXT)

  def _route_download(self) -> tuple[str, str, float] | None:
    """The route download card's content: a route is set and navtilesd is still saving its map."""
    if self._tiles is None or self._preview_active or not self._navigation_requested or not self._tiles.has_token:
      return None
    status = self._tiles.offline_status()
    sm = ui_state.sm
    device_state = sm["deviceState"] if sm.valid.get("deviceState", False) else None
    return route_download(status.get("route") or {}, network_kind(device_state),
                          bool(status.get("offline")) or self._tiles.service.offline)

  def _wrap(self, text: str, size: int, width: float, max_lines: int = 2) -> list[str]:
    lines, line = [], ""
    for word in text.split():
      candidate = f"{line} {word}".strip()
      if line and self._text_width(candidate, size) > width:
        lines.append(line)
        line = word
      else:
        line = candidate
    if line:
      lines.append(line)
    if len(lines) > max_lines:
      lines = lines[:max_lines - 1] + [self._fit_text(" ".join(lines[max_lines - 1:]), size, width)]
    return lines

  def _draw_route_download(self, rect: rl.Rectangle, now: float) -> None:
    """Bottom centre, above the trip bar: how far the route's map has downloaded, and what to do meanwhile."""
    content = self._route_download()
    if content is None:
      return
    title, hint, progress = content
    width = min(rect.width - 48, 640.0)
    lines = self._wrap(hint, 26, width - 56)
    height = 100.0 + 34 * len(lines)
    bottom = rect.y + rect.height - 44
    if self._nav_active(now):
      bottom -= 96 + 12  # the trip bar
    card = rl.Rectangle(rect.x + (rect.width - width) / 2, bottom - height, width, height)
    self._card(card)
    self._text(self._fit_text(title, 32, width - 56, bold=True), card.x + 28, card.y + 22, 32, TEXT, bold=True)
    self._progress_bar(card.x + 28, card.y + 70, width - 56, 10, progress)
    for index, line in enumerate(lines):
      self._text(line, card.x + 28, card.y + 96 + 34 * index, 26, SUBTEXT)

  def _draw_attribution(self, rect: rl.Rectangle) -> None:
    label = "(c) Mapbox (c) OpenStreetMap"
    width = self._text_width(label, 20)
    self._text(label, rect.x + rect.width - width - 14, rect.y + rect.height - 30, 20, rl.Color(220, 226, 236, 150))

  def _draw_guidance(self, rect: rl.Rectangle, now: float) -> None:
    pad = 24.0
    nav = self._nav if self._nav_active(now) else None
    y = rect.y + pad
    card_width = min(rect.width - 2 * pad, 760.0)
    status_width = 0.0
    top_right_offline = self.offline_anchor is None and self._tiles is not None and self._tiles.service.offline
    if top_right_offline or (self._tiles is not None and self._gps is not None and not self._gps.fresh):
      status_width = 330.0
    card_width = min(card_width, rect.width - 2 * pad - status_width - self.status_inset)

    if nav is not None and nav["primary"]:
      has_next = bool(nav["next_type"] or nav["next_modifier"])
      height = 196.0 if nav["secondary"] else 168.0
      card = rl.Rectangle(rect.x + pad, y, card_width, height)
      self._card(card)
      icon_size = 112.0
      self._draw_icon(self._icon(nav["type"], nav["modifier"]), card.x + 24, card.y + (height - icon_size) / 2, icon_size)
      text_x = card.x + 24 + icon_size + 24
      text_width = card.x + card.width - text_x - 24
      self._text(_format_distance(nav["distance"], ui_state.is_metric), text_x, card.y + 20, 64, TEXT, bold=True)
      self._text(self._fit_text(nav["primary"], 38, text_width, bold=True), text_x, card.y + 94, 38, TEXT, bold=True)
      if nav["secondary"]:
        self._text(self._fit_text(nav["secondary"], 28, text_width), text_x, card.y + 142, 28, SUBTEXT)
      y += height + 12
      if has_next:
        then = rl.Rectangle(rect.x + pad, y, 250, 72)
        self._card(then)
        self._text("Then", then.x + 24, then.y + 18, 32, SUBTEXT, bold=True)
        self._draw_icon(self._icon(nav["next_type"], nav["next_modifier"]), then.x + 120, then.y + 8, 56)
        y += 84

    desire = desire_line(ui_state.started, self._desire, self._nav_desire, nav)
    if desire is not None:
      label, detail, color = desire
      label_width = self._text_width(label, 34, bold=True)
      width = min(card_width, max(label_width, self._text_width(detail, 26)) + 90)
      chip = rl.Rectangle(rect.x + pad, y, width, 104 if detail else 68)
      self._card(chip)
      rl.draw_circle_v(rl.Vector2(chip.x + 30, chip.y + 34), 10.0, color)
      self._text(label, chip.x + 54, chip.y + 16, 34, color, bold=True)
      if detail:
        self._text(self._fit_text(detail, 26, chip.width - 78), chip.x + 54, chip.y + 60, 26, SUBTEXT)

    if nav is not None:
      self._draw_trip_bar(rect, nav)

  @staticmethod
  def _trip_texts(nav: dict) -> tuple[str, str]:
    """(arrival time, "duration  •  distance") for the trip bar."""
    remaining_time = max(0.0, nav["remaining_time"])
    arrival = datetime.datetime.now() + datetime.timedelta(seconds=remaining_time)
    arrival_text = arrival.strftime("%H:%M") if ui_state.is_metric else arrival.strftime("%I:%M %p").lstrip("0")
    minutes = int(round(remaining_time / 60.0))
    duration = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{max(1, minutes)} min"
    return arrival_text, f"{duration}  •  {_format_distance(nav['remaining_distance'], ui_state.is_metric)}"

  def _draw_trip_bar(self, rect: rl.Rectangle, nav: dict) -> None:
    arrival_text, detail = self._trip_texts(nav)
    height = 96.0
    width = min(rect.width - 48, 640.0)
    bar = rl.Rectangle(rect.x + (rect.width - width) / 2, rect.y + rect.height - height - 44, width, height)
    self._card(bar)
    self._text(arrival_text, bar.x + 32, bar.y + 22, 50, DESIRE_ROUTE, bold=True)
    detail_width = self._text_width(detail, 36)
    self._text(detail, bar.x + bar.width - detail_width - 32, bar.y + 30, 36, TEXT)
