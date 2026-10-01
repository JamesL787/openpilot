"""Offline map planning and the small amount of state the UI and navtilesd share.

Three kinds of map tiles:
  * Route tiles: the corridor along a route plus street-level detail around its
    turns and destination. They live in the regular tile cache and age out
    least-recently-used first when it fills.
  * Driven tiles: when enabled, tiles opened on the map are pinned in the same
    offline storage as downloaded areas and count toward the same limit.
  * Offline areas: everything within a radius, downloaded on Wi-Fi and pinned
    until the area is deleted. Areas refresh themselves every few months.

State is plain JSON files beside the tiles, each written atomically by one side:
  offline/areas/<id>.json      area definitions (UI writes, navtilesd deletes)
  offline/auto_saved/...       markers protecting tiles saved while driving
  offline/auto_saved_pending/  tiles waiting to be promoted from regular cache
  offline/settings.json        save-as-you-drive and map colors, plus styles to delete (UI writes, map and navtilesd read)
  offline/usage.json           Mapbox requests this month (see mapbox_usage.py)
  offline/promote_viewed       one-shot request to pin tiles already in the regular cache
  offline/status.json          download progress (navtilesd writes)
  offline/preview_route.json   the route being previewed in the UI (UI writes)
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openpilot.starpilot.navigation.map_tiles import (
  TILE_SIZE,
  TileCache,
  TileKey,
  corridor_tiles,
  default_cache_dir,
  DARK_STYLE,
  LIGHT_STYLE,
  offline_root,
  style_dir_name,
  tiles_covering,
  world_xy,
)

ROUTE_ZOOMS = (12, 14, 15)       # overview, highway and city follow views
DETAIL_ZOOM = 16                 # street-level view the map uses at low speed
DETAIL_RADIUS_M = 300.0
TURN_ANGLE_DEGREES = 35.0
MAX_DETAIL_POINTS = 150

AREA_MIN_ZOOM = 8
AVERAGE_TILE_BYTES = 30_000      # navigation-night 512 px tiles: ~17 KB suburban, ~42 KB downtown
OFFLINE_MAX_BYTES = 2 * 1024 ** 3
AREA_REFRESH_SECONDS = 90 * 24 * 3600
PREVIEW_ROUTE_MAX_AGE = 30 * 60
SERVICE_STALE_SECONDS = 30.0     # navtilesd rewrites its status every few seconds while it runs
MAX_ROUTE_POINTS = 5000
MAX_DISPLAY_POINTS = 400

AREA_MIN_RADIUS_KM = 1.0
AREA_MAX_RADIUS_KM = 150.0
# The native on-device picker remains button-based; The Galaxy supports every
# radius in this range and derives detail with ``area_zoom_for_radius``.
AREA_PRESETS = ((10.0, 16), (30.0, 15), (60.0, 14), (150.0, 13))
AREA_ZOOM_CHOICES = (14, 15, 16)  # detail The Galaxy lets the user pick instead of the radius default

# Map colors. "auto" keeps both styles and shows light between sunrise and sunset.
MAP_THEMES = ("light", "dark", "auto")
DEFAULT_MAP_THEME = "auto"
THEME_STYLES = {"light": (LIGHT_STYLE,), "dark": (DARK_STYLE,), "auto": (LIGHT_STYLE, DARK_STYLE)}
SUNSET_ELEVATION = -0.833  # degrees: the sun's upper edge on the horizon, refraction included
FALLBACK_DAY_HOURS = (7, 19)  # local clock hours for light maps before the device has ever had a location


def sun_elevation(latitude: float, longitude: float, wall: float) -> float:
  """The sun's elevation in degrees (NOAA's low-precision formulas, well under a degree off)."""
  days = wall / 86400.0 + 2440587.5 - 2451545.0  # since J2000
  anomaly = math.radians((357.529 + 0.98560028 * days) % 360.0)
  mean_longitude = 280.459 + 0.98564736 * days
  ecliptic = math.radians(mean_longitude + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly))
  obliquity = math.radians(23.439 - 0.00000036 * days)
  right_ascension = math.atan2(math.cos(obliquity) * math.sin(ecliptic), math.cos(ecliptic))
  declination = math.asin(math.sin(obliquity) * math.sin(ecliptic))
  sidereal_hours = (18.697374558 + 24.06570982441908 * days) % 24.0
  hour_angle = math.radians(sidereal_hours * 15.0 + longitude) - right_ascension
  lat = math.radians(latitude)
  return math.degrees(math.asin(math.sin(lat) * math.sin(declination) +
                                math.cos(lat) * math.cos(declination) * math.cos(hour_angle)))


def is_daytime(position: tuple[float, float] | None, wall: float) -> bool:
  if position is None:
    return FALLBACK_DAY_HOURS[0] <= time.localtime(wall).tm_hour < FALLBACK_DAY_HOURS[1]
  return sun_elevation(position[0], position[1], wall) > SUNSET_ELEVATION


def theme_style(theme: str, position: tuple[float, float] | None, wall: float) -> str:
  """The style the map shows right now."""
  if theme == "light":
    return LIGHT_STYLE
  if theme == "auto":
    return LIGHT_STYLE if is_daytime(position, wall) else DARK_STYLE
  return DARK_STYLE


def parse_position(raw: Any) -> tuple[float, float] | None:
  """(latitude, longitude) from a LastGPSPosition value, or None."""
  try:
    state = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    latitude, longitude = float(state["latitude"]), float(state["longitude"])
  except (TypeError, ValueError, KeyError):
    return None
  if not (math.isfinite(latitude) and math.isfinite(longitude)) or (abs(latitude) < 1e-6 and abs(longitude) < 1e-6):
    return None
  return latitude, longitude


def last_known_position() -> tuple[float, float] | None:
  """The device's live position, else the last one saved. Only used to place the sun."""
  try:
    from openpilot.common.params import Params
    for params in (Params(memory=True), Params()):
      position = parse_position(params.get("LastGPSPosition", encoding="utf-8"))
      if position is not None:
        return position
  except Exception:
    pass
  return None


def _now() -> float:
  return time.time()  # noqa: TID251 - persisted timestamps must survive reboots


def _write_json(path: Path, payload: Any) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
  with os.fdopen(fd, "w") as handle:
    json.dump(payload, handle)
  os.replace(temp_name, path)


def _read_json(path: Path) -> Any:
  try:
    return json.loads(path.read_text())
  except (OSError, ValueError):
    return None


# ── tile planning ──────────────────────────────────────────────────────────

def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
  lat1, lat2 = math.radians(a[0]), math.radians(b[0])
  dlon = math.radians(b[1] - a[1])
  x = math.sin(dlon) * math.cos(lat2)
  y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
  return math.degrees(math.atan2(x, y)) % 360.0


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
  lat = math.radians((a[0] + b[0]) / 2.0)
  dx = math.radians(b[1] - a[1]) * math.cos(lat) * 6371000.0
  dy = math.radians(b[0] - a[0]) * 6371000.0
  return math.hypot(dx, dy)


def turn_points(points: Sequence[tuple[float, float]], min_angle: float = TURN_ANGLE_DEGREES) -> list[tuple[float, float]]:
  """Where a route geometry changes direction sharply: its turns, forks and ramps.

  Headings are measured over ~25 m either side so curves drawn with many short
  segments don't register as turns.
  """
  if len(points) < 3:
    return []
  turns = []
  for i in range(1, len(points) - 1):
    j = i - 1
    while j > 0 and _distance_m(points[j], points[i]) < 25.0:
      j -= 1
    k = i + 1
    while k < len(points) - 1 and _distance_m(points[i], points[k]) < 25.0:
      k += 1
    if _distance_m(points[j], points[i]) < 5.0 or _distance_m(points[i], points[k]) < 5.0:
      continue
    change = abs((_bearing(points[i], points[k]) - _bearing(points[j], points[i]) + 540.0) % 360.0 - 180.0)
    if change >= min_angle and (not turns or _distance_m(turns[-1], points[i]) > DETAIL_RADIUS_M):
      turns.append(points[i])
  return turns


def detail_tiles(points: Iterable[tuple[float, float]], zoom: int = DETAIL_ZOOM, radius_m: float = DETAIL_RADIUS_M) -> list[TileKey]:
  keys: list[TileKey] = []
  seen: set[TileKey] = set()
  for latitude, longitude in points:
    cx, cy = world_xy(latitude, longitude)
    meters_per_unit = 40075016.686 * math.cos(math.radians(latitude)) / TILE_SIZE
    r = radius_m / meters_per_unit
    for key in tiles_covering(cx - r, cy - r, cx + r, cy + r, zoom):
      if key not in seen:
        seen.add(key)
        keys.append(key)
  return keys


def route_tiles(points: Sequence[tuple[float, float]]) -> list[TileKey]:
  """Tiles for driving a route offline: street detail at the destination and
  turns first (small and most needed), then the corridor in driving order."""
  if not points:
    return []
  focus = [points[-1]] + turn_points(points)[:MAX_DETAIL_POINTS] + [points[0]]
  keys = detail_tiles(focus)
  seen = set(keys)
  corridor = corridor_tiles([world_xy(lat, lon) for lat, lon in points], zooms=ROUTE_ZOOMS)
  keys += [key for key in corridor if key not in seen]
  return keys


def area_tiles(latitude: float, longitude: float, radius_km: float, max_zoom: int, min_zoom: int = AREA_MIN_ZOOM) -> list[TileKey]:
  """Tiles within a radius, coarse zooms first and each zoom from the centre out,
  so an interrupted download is still useful."""
  cx, cy = world_xy(latitude, longitude)
  meters_per_unit = 40075016.686 * math.cos(math.radians(latitude)) / TILE_SIZE
  r = radius_km * 1000.0 / meters_per_unit
  keys: list[TileKey] = []
  for zoom in range(min_zoom, max_zoom + 1):
    scale = (1 << zoom) / TILE_SIZE
    tiles = [key for key in tiles_covering(cx - r, cy - r, cx + r, cy + r, zoom)
             if math.hypot((key.x + 0.5) / scale - cx, (key.y + 0.5) / scale - cy) <= r + 0.75 / scale]
    tiles.sort(key=lambda key: ((key.x + 0.5) / scale - cx) ** 2 + ((key.y + 0.5) / scale - cy) ** 2)
    keys += tiles
  return keys


def estimate_area(latitude: float, longitude: float, radius_km: float, max_zoom: int) -> tuple[int, int]:
  """(tile count, approximate bytes)."""
  count = len(area_tiles(latitude, longitude, radius_km, max_zoom))
  return count, count * AVERAGE_TILE_BYTES


def area_zoom_for_radius(radius_km: float) -> int:
  """Choose useful detail without letting a large radius explode in size."""
  if not AREA_MIN_RADIUS_KM <= radius_km <= AREA_MAX_RADIUS_KM:
    raise ValueError("Area radius is out of range")
  if radius_km <= 10.0:
    return 16
  if radius_km <= 30.0:
    return 15
  if radius_km <= 60.0:
    return 14
  return 13


def format_bytes(size: float) -> str:
  if size >= 1024 ** 3:
    return f"{size / 1024 ** 3:.1f} GB"
  if size >= 1024 ** 2:
    return f"{size / 1024 ** 2:.0f} MB"
  return f"{max(size, 0) / 1024:.0f} KB"


# ── shared state ───────────────────────────────────────────────────────────

@dataclass
class OfflineArea:
  """A saved offline item: an area around a point, or a route (``kind == "route"``)."""
  id: str
  name: str
  latitude: float
  longitude: float
  radius_km: float
  max_zoom: int
  created: float
  update_requested: float = 0.0
  deleted: bool = False
  allow_metered: bool = False  # "Download now": use any connection, not just unmetered Wi-Fi
  kind: str = "area"
  points: list[list[float]] | None = None  # route geometry as [lat, lon]
  distance_m: float = 0.0
  duration_s: float = 0.0
  origin_name: str = ""

  def tiles(self) -> list[TileKey]:
    if self.kind == "route":
      return route_tiles([(lat, lon) for lat, lon in self.points or []])
    return area_tiles(self.latitude, self.longitude, self.radius_km, self.max_zoom)


def clean_route_points(raw: Any) -> list[tuple[float, float]] | None:
  """Validate [lat, lon] pairs (or {latitude, longitude}) and thin very long routes."""
  if not isinstance(raw, list) or len(raw) < 2 or len(raw) > 20 * MAX_ROUTE_POINTS:
    return None
  points: list[tuple[float, float]] = []
  for item in raw:
    try:
      if isinstance(item, dict):
        latitude, longitude = float(item["latitude"]), float(item["longitude"])
      else:
        latitude, longitude = float(item[0]), float(item[1])
    except (KeyError, IndexError, TypeError, ValueError):
      return None
    if not (math.isfinite(latitude) and math.isfinite(longitude) and -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
      return None
    points.append((latitude, longitude))
  return thin_points(points, MAX_ROUTE_POINTS)


def thin_points(points: Sequence[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
  if len(points) <= limit:
    return list(points)
  stride = math.ceil(len(points) / limit)
  thinned = list(points[::stride])
  if thinned[-1] != points[-1]:
    thinned.append(points[-1])
  return thinned


class OfflineMaps:
  def __init__(self, base: Path | None = None, position=last_known_position):
    self._position = position
    self.base = Path(base or default_cache_dir())
    self.root = offline_root(self.base)
    self.areas_dir = self.root / "areas"
    self.status_path = self.root / "status.json"
    self.preview_path = self.root / "preview_route.json"
    self.settings_path = self.root / "settings.json"
    self.promote_path = self.root / "promote_viewed"
    self.auto_saved_dir = self.root / "auto_saved"
    self.auto_saved_pending_dir = self.root / "auto_saved_pending"

  # areas (UI side)
  def areas(self, include_deleted: bool = False) -> list[OfflineArea]:
    areas = []
    try:
      paths = sorted(self.areas_dir.glob("*.json"))
    except OSError:
      return []
    for path in paths:
      raw = _read_json(path)
      if not isinstance(raw, dict):
        continue
      try:
        area = OfflineArea(**{field: raw[field] for field in OfflineArea.__dataclass_fields__ if field in raw})
      except TypeError:
        continue
      if include_deleted or not area.deleted:
        areas.append(area)
    return sorted(areas, key=lambda area: area.created)

  def add_area(self, name: str, latitude: float, longitude: float, radius_km: float, max_zoom: int) -> OfflineArea:
    area = OfflineArea(uuid.uuid4().hex[:12], name, float(latitude), float(longitude), float(radius_km), int(max_zoom), _now())
    self._save_area(area)
    return area

  def add_route(self, name: str, points: Sequence[tuple[float, float]], distance_m: float = 0.0, duration_s: float = 0.0,
                origin_name: str = "") -> OfflineArea:
    latitude, longitude = points[-1]
    area = OfflineArea(uuid.uuid4().hex[:12], name, float(latitude), float(longitude), 0.0, 0, _now(), kind="route",
                       points=[[round(lat, 6), round(lon, 6)] for lat, lon in points], distance_m=float(distance_m),
                       duration_s=float(duration_s), origin_name=origin_name)
    self._save_area(area)
    return area

  def get(self, area_id: str) -> OfflineArea | None:
    return next((area for area in self.areas(include_deleted=True) if area.id == area_id), None)

  def summary(self) -> dict[str, Any]:
    """Saved items merged with their download progress, for The Galaxy."""
    status = self.status()
    progress = status.get("areas") or {}
    updated = float(status.get("updated") or 0.0)
    items = []
    for area in self.areas(include_deleted=True):
      state = progress.get(area.id) or {}
      item = {
        "id": area.id, "kind": area.kind, "name": area.name, "latitude": area.latitude, "longitude": area.longitude,
        "radius_km": area.radius_km, "max_zoom": area.max_zoom, "created": area.created, "allow_metered": area.allow_metered,
        "state": "removing" if area.deleted else state.get("state", "queued"),
        "done": int(state.get("done") or 0), "total": int(state.get("total") or 0), "bytes": int(state.get("bytes") or 0),
        "completed_at": float(state.get("completed_at") or 0.0), "metered_wifi": bool(state.get("metered_wifi")),
      }
      if area.kind == "route":
        item.update(distance_m=area.distance_m, duration_s=area.duration_s, origin_name=area.origin_name,
                    points=[[lat, lon] for lat, lon in thin_points([(lat, lon) for lat, lon in area.points or []], MAX_DISPLAY_POINTS)])
      items.append(item)
    return {
      "items": items,
      "offline_bytes": int(status.get("offline_bytes") or 0),
      "max_bytes": OFFLINE_MAX_BYTES,
      "unmetered": bool(status.get("unmetered")),
      "offline": bool(status.get("offline")),
      "route": status.get("route") or {},
      "service_running": updated > 0 and _now() - updated < SERVICE_STALE_SECONDS,
      "refresh_days": AREA_REFRESH_SECONDS // 86400,
      "save_viewed_cache": self.save_viewed_cache(),
      "map_theme": self.map_theme(),
      "usage": self.usage(),
    }

  def _settings(self) -> dict[str, Any]:
    raw = _read_json(self.settings_path)
    return raw if isinstance(raw, dict) else {}

  def save_viewed_cache(self) -> bool:
    return bool(self._settings().get("save_viewed_cache"))

  def map_theme(self) -> str:
    theme = self._settings().get("map_theme")
    return theme if theme in MAP_THEMES else DEFAULT_MAP_THEME

  def active_styles(self) -> tuple[str, ...]:
    """Styles kept downloaded for saved areas."""
    return THEME_STYLES[self.map_theme()]

  def display_style(self, wall: float | None = None) -> str:
    return theme_style(self.map_theme(), self._position() if self.map_theme() == "auto" else None,
                       _now() if wall is None else wall)

  @property
  def style(self) -> str:
    """The style shown now; the one coverage and save-as-you-drive work in."""
    return self.display_style()

  def dropped_styles(self, theme: str) -> list[str]:
    """Styles in use now that ``theme`` would stop using: the ones to ask keep-or-delete about."""
    return [style for style in self.active_styles() if style not in THEME_STYLES[theme]]

  def set_map_theme(self, theme: str, discard_dropped: bool = False) -> None:
    """Switch map colors. Dropped styles stay on disk (for switching back) unless discarded;
    navtilesd deletes discarded ones and downloads saved areas in any new style on Wi-Fi."""
    if theme not in MAP_THEMES:
      raise ValueError(f"Unknown map colors {theme!r}")
    settings = self._settings()
    discard = [style for style in settings.get("discard_styles") or [] if style not in THEME_STYLES[theme]]
    if discard_dropped:
      discard += [style for style in self.dropped_styles(theme) if style not in discard]
    settings.pop("show_traffic", None)
    _write_json(self.settings_path, {**settings, "map_theme": theme, "discard_styles": discard})

  def pending_discards(self) -> list[str]:
    styles = self._settings().get("discard_styles") or []
    return [style for style in styles if isinstance(style, str) and style not in self.active_styles()]

  def clear_discards(self, styles: Iterable[str]) -> None:
    settings = self._settings()
    done = set(styles)
    settings["discard_styles"] = [style for style in settings.get("discard_styles") or [] if style not in done]
    _write_json(self.settings_path, settings)

  def style_roots(self, style: str) -> list[Path]:
    """Every directory holding tiles of ``style``: saved areas and the temporary cache."""
    return [self.root / style_dir_name(style), self.base / style_dir_name(style)]

  def usage(self) -> dict[str, Any]:
    from openpilot.starpilot.navigation.mapbox_usage import FREE_DIRECTIONS_REQUESTS, FREE_TILE_REQUESTS, read_usage
    return {**read_usage(self.root / "usage.json"), "free_tiles": FREE_TILE_REQUESTS, "free_directions": FREE_DIRECTIONS_REQUESTS}

  def set_save_viewed_cache(self, enabled: bool) -> None:
    _write_json(self.settings_path, {**self._settings(), "save_viewed_cache": bool(enabled)})
    if enabled:
      # Tiles already in the temporary cache should turn green right away, not only
      # ones viewed after this point. navtilesd picks up the request and promotes them.
      self.request_promote_cached()
    else:
      self.clear_promote_request()

  def request_promote_cached(self) -> None:
    try:
      self.promote_path.parent.mkdir(parents=True, exist_ok=True)
      self.promote_path.touch()
    except OSError:
      pass

  def promote_requested(self) -> bool:
    return self.promote_path.is_file()

  def clear_promote_request(self) -> None:
    try:
      self.promote_path.unlink()
    except OSError:
      pass

  def cached_regular_tiles(self) -> list[TileKey]:
    """Tiles present in the temporary route cache."""
    root = TileCache(self.base, self.style).root
    keys = []
    try:
      for path in root.glob("*/*/*.png"):
        try:
          keys.append(TileKey(int(path.parent.parent.name), int(path.parent.name), int(path.stem)))
        except ValueError:
          continue
    except OSError:
      pass
    return keys

  def mark_cached_tiles(self) -> int:
    """Queue every tile already in the temporary cache for promotion into pinned storage.

    Called when save-as-you-drive is switched on so tiles on disk turn green without
    waiting to be viewed again. Already-pinned or already-marked tiles are left alone.
    """
    pinned = TileCache(self.root, self.style)
    marked = 0
    for key in self.cached_regular_tiles():
      if pinned.contains(key) or self.is_auto_saved(key):
        continue
      if self.mark_auto_saved(key):
        marked += 1
    return marked

  def auto_saved_marker(self, key: TileKey) -> Path:
    return self.auto_saved_dir / str(key.z) / str(key.x) / f"{key.y}.saved"

  def auto_saved_pending_marker(self, key: TileKey) -> Path:
    return self.auto_saved_pending_dir / str(key.z) / str(key.x) / f"{key.y}.saved"

  def mark_auto_saved(self, key: TileKey) -> bool:
    path, pending = self.auto_saved_marker(key), self.auto_saved_pending_marker(key)
    try:
      path.parent.mkdir(parents=True, exist_ok=True)
      path.touch(exist_ok=True)
      pending.parent.mkdir(parents=True, exist_ok=True)
      pending.touch(exist_ok=True)
      return True
    except OSError:
      return False

  def is_auto_saved(self, key: TileKey) -> bool:
    return self.auto_saved_marker(key).is_file()

  def pending_auto_saved(self, limit: int = 256) -> list[TileKey]:
    keys = []
    try:
      paths = self.auto_saved_pending_dir.glob("*/*/*.saved")
      for path in paths:
        try:
          keys.append(TileKey(int(path.parent.parent.name), int(path.parent.name), int(path.stem)))
        except ValueError:
          continue
        if len(keys) >= limit:
          break
    except OSError:
      pass
    return keys

  def finish_auto_saved(self, key: TileKey) -> None:
    try:
      self.auto_saved_pending_marker(key).unlink()
    except OSError:
      pass

  def forget_auto_saved(self, key: TileKey) -> None:
    self.finish_auto_saved(key)
    try:
      self.auto_saved_marker(key).unlink()
    except OSError:
      pass

  def coverage(self, zoom: int, west: float, south: float, east: float, north: float, limit: int = 4000) -> dict[str, Any]:
    """Actual tile files in the viewport at one exact zoom, bounded for the web map.

    Saved tiles take precedence over temporary route-cache duplicates. Planning and
    download counters deliberately aren't used as evidence of cached coverage.
    """
    if not 0 <= zoom <= 18 or not all(math.isfinite(v) for v in (west, south, east, north)) or not -90 <= south <= north <= 90:
      raise ValueError("Invalid coverage bounds or zoom")
    if east < west:
      east += 360
    if east < west:
      raise ValueError("Invalid coverage bounds")
    n = 1 << zoom
    first_x = math.floor((west + 180) / 360 * n)
    last_x = math.floor((east + 180) / 360 * n)
    def tile_y(latitude):
      lat = math.radians(max(-85.05112878, min(85.05112878, latitude)))
      return max(0, min(n - 1, math.floor((1 - math.asinh(math.tan(lat)) / math.pi) / 2 * n)))
    first_y, last_y = tile_y(north), tile_y(south)
    found = {}
    for base, saved in ((self.root, True), (self.base, False)):
      root = TileCache(base, self.style).root / str(zoom)
      try:
        columns = list(root.iterdir())
      except OSError:
        continue
      for column in columns:
        if not column.name.isdigit():
          continue
        x = int(column.name)
        if not 0 <= x < n or (last_x - first_x < n and (x - first_x) % n > last_x - first_x):
          continue
        try:
          for tile in column.iterdir():
            if tile.suffix != ".png" or not tile.stem.isdigit():
              continue
            y = int(tile.stem)
            if not first_y <= y <= last_y or (x, y) in found:
              continue
            try:
              if not tile.is_file() or tile.stat().st_size == 0:
                continue
            except OSError:
              continue
            if len(found) >= limit:
              return {"zoom": zoom, "tiles": list(found.values()), "truncated": True}
            found[x, y] = [x, y, saved]
        except OSError:
          continue
    return {"zoom": zoom, "tiles": list(found.values()), "truncated": False}

  def request_update(self, area_id: str) -> None:
    for area in self.areas():
      if area.id == area_id:
        area.update_requested = _now()
        self._save_area(area)

  def allow_metered(self, area_id: str) -> None:
    for area in self.areas():
      if area.id == area_id:
        area.allow_metered = True
        self._save_area(area)

  def delete_area(self, area_id: str) -> None:
    """Marks the area; navtilesd removes its tiles (keeping any another area shares) and then the record."""
    for area in self.areas():
      if area.id == area_id:
        area.deleted = True
        self._save_area(area)

  def forget_area(self, area_id: str) -> None:
    try:
      (self.areas_dir / f"{area_id}.json").unlink()
    except OSError:
      pass

  def _save_area(self, area: OfflineArea) -> None:
    _write_json(self.areas_dir / f"{area.id}.json", asdict(area))

  # progress (navtilesd side)
  def status(self) -> dict[str, Any]:
    raw = _read_json(self.status_path)
    return raw if isinstance(raw, dict) else {}

  def write_status(self, status: dict[str, Any]) -> None:
    _write_json(self.status_path, status)

  # the route being previewed (UI side)
  def set_preview_route(self, points: Sequence[tuple[float, float]]) -> None:
    _write_json(self.preview_path, {"at": _now(), "points": [[round(lat, 6), round(lon, 6)] for lat, lon in points]})

  def preview_route(self) -> list[tuple[float, float]]:
    raw = _read_json(self.preview_path)
    if not isinstance(raw, dict) or _now() - float(raw.get("at", 0.0)) > PREVIEW_ROUTE_MAX_AGE:
      return []
    try:
      return [(float(lat), float(lon)) for lat, lon in raw.get("points", [])]
    except (TypeError, ValueError):
      return []
