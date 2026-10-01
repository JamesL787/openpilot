"""Mapbox raster tiles for the on-device navigation map, with a disk cache.

Tiles the map needs right now are fetched first; tiles along the active route
are prefetched slowly in the background so the map keeps working when the
connection drops, without ever making the driver wait for a download. Cached
tiles are served whether or not the network is up. Nothing here touches the
GPU: finished tiles are handed to the caller's ``decode`` function on a worker
thread, and the UI thread only uploads the decoded images.
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

TILE_SIZE = 512
MIN_ZOOM = 0
MAX_ZOOM = 18
# Neither style has traffic: raster tiles bake it in, and a saved tile would keep
# showing the traffic from the day it was downloaded.
LIGHT_STYLE = "mapbox/streets-v12"
DARK_STYLE = "mapbox/dark-v11"
DEFAULT_STYLE = DARK_STYLE
# Styles used before, with traffic baked into their tiles. navtilesd deletes them.
LEGACY_STYLES = ("mapbox/navigation-night-v1",)
TILE_URL = "https://api.mapbox.com/styles/v1/{style}/tiles/{size}/{z}/{x}/{y}"

MAX_DISK_BYTES = 300 * 1024 * 1024
MIN_FREE_DISK_BYTES = 1024 * 1024 * 1024  # never fill /data for a map
REFRESH_AGE_SECONDS = 30 * 24 * 3600      # re-fetch stale tiles in the background when online
OFFLINE_BACKOFF_SECONDS = 20.0
AUTH_BACKOFF_SECONDS = 300.0
MISSING_RETRY_SECONDS = 600.0
PREFETCH_INTERVAL_SECONDS = 0.35          # at most ~3 background downloads a second
REQUEST_TIMEOUT = (4.0, 8.0)
WORKERS = 2

# Route corridor prefetch: the zooms the follow view uses, and how far to reach.
PREFETCH_ZOOMS = (13, 15)
PREFETCH_MAX_TILES = 1200


@dataclass(frozen=True, slots=True)
class TileKey:
  z: int
  x: int
  y: int

  def parent(self) -> TileKey | None:
    if self.z <= MIN_ZOOM:
      return None
    return TileKey(self.z - 1, self.x >> 1, self.y >> 1)


def default_cache_dir() -> Path:
  if os.path.isdir("/data/media/0"):
    return Path("/data/media/0/navigation_tiles")
  return Path.home() / ".comma" / "navigation_tiles"


def world_xy(latitude: float, longitude: float) -> tuple[float, float]:
  """Web Mercator position in zoom-0 pixels (0..TILE_SIZE)."""
  latitude = max(-85.05112878, min(85.05112878, latitude))
  x = (longitude + 180.0) / 360.0 * TILE_SIZE
  sin_lat = math.sin(math.radians(latitude))
  y = (0.5 - math.log((1.0 + sin_lat) / (1.0 - sin_lat)) / (4.0 * math.pi)) * TILE_SIZE
  return x, y


def meters_per_world_unit(latitude: float) -> float:
  """Ground meters covered by one zoom-0 pixel at this latitude."""
  return 40075016.686 * math.cos(math.radians(latitude)) / TILE_SIZE


def tiles_covering(min_x: float, min_y: float, max_x: float, max_y: float, zoom: int) -> list[TileKey]:
  """Tiles at ``zoom`` covering a zoom-0 bounding box."""
  scale = (1 << zoom) / TILE_SIZE
  limit = (1 << zoom) - 1
  x0, x1 = max(0, int(math.floor(min_x * scale))), min(limit, int(math.floor(max_x * scale)))
  y0, y1 = max(0, int(math.floor(min_y * scale))), min(limit, int(math.floor(max_y * scale)))
  return [TileKey(zoom, x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def corridor_tiles(points: Sequence[tuple[float, float]], zooms: Iterable[int] = PREFETCH_ZOOMS,
                   radius_tiles: int = 1, limit: int = PREFETCH_MAX_TILES) -> list[TileKey]:
  """Tiles along a zoom-0 polyline, in route order and interleaved by zoom.

  Walking the route in order means the part the car reaches first is cached
  first; interleaving zooms means a coarse map of the whole route exists early.
  """
  per_zoom: list[list[TileKey]] = []
  for zoom in zooms:
    scale = (1 << zoom) / TILE_SIZE
    limit_xy = (1 << zoom) - 1
    seen: set[TileKey] = set()
    ordered: list[TileKey] = []
    previous: tuple[float, float] | None = None
    for point in points:
      samples = [point]
      if previous is not None:
        # Densify long segments so no tile along them is skipped.
        steps = int(max(abs(point[0] - previous[0]), abs(point[1] - previous[1])) * scale * 2)
        samples = [(previous[0] + (point[0] - previous[0]) * i / (steps + 1),
                    previous[1] + (point[1] - previous[1]) * i / (steps + 1)) for i in range(1, steps + 2)]
      previous = point
      for sx, sy in samples:
        tx, ty = int(sx * scale), int(sy * scale)
        for dy in range(-radius_tiles, radius_tiles + 1):
          for dx in range(-radius_tiles, radius_tiles + 1):
            x, y = tx + dx, ty + dy
            if 0 <= x <= limit_xy and 0 <= y <= limit_xy:
              key = TileKey(zoom, x, y)
              if key not in seen:
                seen.add(key)
                ordered.append(key)
    per_zoom.append(ordered)

  result: list[TileKey] = []
  cursors = [0] * len(per_zoom)
  # Coarse zooms have far fewer tiles; advance each list proportionally so they finish together.
  while len(result) < limit and any(cursors[i] < len(per_zoom[i]) for i in range(len(per_zoom))):
    progress = [cursors[i] / max(1, len(per_zoom[i])) if cursors[i] < len(per_zoom[i]) else 2.0 for i in range(len(per_zoom))]
    index = progress.index(min(progress))
    result.append(per_zoom[index][cursors[index]])
    cursors[index] += 1
  return result


def image_extension(data: bytes) -> str | None:
  if data.startswith(b"\x89PNG"):
    return ".png"
  if data.startswith(b"\xff\xd8"):
    return ".jpg"
  return None


def _existing_ancestor(path: Path) -> Path:
  while not path.exists() and path != path.parent:
    path = path.parent
  return path


def offline_root(base: Path | None = None) -> Path:
  """Where downloaded offline areas keep their tiles; never trimmed automatically."""
  return Path(base or default_cache_dir()) / "offline"


def style_dir_name(style: str) -> str:
  return style.replace("/", "_")


class TileCache:
  """Tiles on disk as ``<root>/<style>/<z>/<x>/<y>.png``, trimmed oldest-first past a size cap.

  ``max_bytes=None`` never trims (offline areas). A ``pinned`` cache is consulted
  on reads, so tiles saved in an offline area are never downloaded twice.
  """

  def __init__(self, root: Path, style: str, max_bytes: int | None = MAX_DISK_BYTES, min_free_bytes: int = MIN_FREE_DISK_BYTES,
               pinned: TileCache | None = None):
    self.root = Path(root) / style_dir_name(style)
    self.max_bytes = max_bytes
    self.min_free_bytes = min_free_bytes
    self.pinned = pinned
    self._lock = threading.Lock()
    self._size: int | None = None
    self._touched: set[TileKey] = set()

  def path(self, key: TileKey) -> Path:
    return self.root / str(key.z) / str(key.x) / f"{key.y}.png"

  def read(self, key: TileKey) -> tuple[bytes, float] | None:
    """Tile bytes and their age in seconds, or None."""
    path = self.path(key)
    try:
      stat = path.stat()
      data = path.read_bytes()
    except OSError:
      return self.pinned.read(key) if self.pinned is not None else None
    if self.max_bytes is not None and key not in self._touched:
      # Recently viewed tiles survive trimming; one touch per tile per session is enough.
      self._touched.add(key)
      try:
        os.utime(path, None)
      except OSError:
        pass
    return data, max(0.0, time.time() - stat.st_mtime)  # noqa: TID251 - file mtimes are wall-clock

  def age(self, key: TileKey) -> float | None:
    """Seconds since a cached tile was written, or None when it isn't cached."""
    try:
      return max(0.0, time.time() - self.path(key).stat().st_mtime)  # noqa: TID251 - file mtimes are wall-clock
    except OSError:
      return self.pinned.age(key) if self.pinned is not None else None

  def contains(self, key: TileKey) -> bool:
    return self.path(key).is_file() or (self.pinned is not None and self.pinned.contains(key))

  def remove(self, key: TileKey) -> int:
    """Delete a tile from this cache (not the pinned one); returns the bytes freed."""
    path = self.path(key)
    try:
      size = path.stat().st_size
      path.unlink()
    except OSError:
      return 0
    with self._lock:
      if self._size is not None:
        self._size -= size
    return size

  def write(self, key: TileKey, data: bytes) -> bool:
    path = self.path(key)
    try:
      if shutil.disk_usage(_existing_ancestor(path)).free < self.min_free_bytes:
        return False
      path.parent.mkdir(parents=True, exist_ok=True)
      fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tile-")
      with os.fdopen(fd, "wb") as handle:
        handle.write(data)
      old_size = path.stat().st_size if path.exists() else 0
      os.replace(temp_name, path)
    except OSError:
      return False
    with self._lock:
      if self._size is not None:
        self._size += len(data) - old_size
      over = self.max_bytes is not None and self._size is not None and self._size > self.max_bytes
    if over:
      self.trim()
    return True

  def scan(self) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(self.root):
      for name in filenames:
        try:
          total += os.stat(os.path.join(dirpath, name)).st_size
        except OSError:
          pass
    with self._lock:
      self._size = total
    return total

  def trim(self) -> None:
    """Delete the least recently used tiles until the cache is 90% of its cap."""
    entries: list[tuple[float, int, str]] = []
    for dirpath, _, filenames in os.walk(self.root):
      for name in filenames:
        full = os.path.join(dirpath, name)
        try:
          stat = os.stat(full)
        except OSError:
          continue
        entries.append((stat.st_mtime, stat.st_size, full))
    total = sum(size for _, size, _ in entries)
    if self.max_bytes is None:
      with self._lock:
        self._size = total
      return
    target = int(self.max_bytes * 0.9)
    entries.sort()
    for _, size, full in entries:
      if total <= target:
        break
      try:
        os.unlink(full)
        total -= size
      except OSError:
        pass
    with self._lock:
      self._size = total


class TileService:
  """Background tile loading. The UI calls ``want`` each frame and ``poll`` for results."""

  def __init__(self, token: Callable[[], str], decode: Callable[[bytes, str], Any] | None = None,
               cache: TileCache | None = None, style: str = DEFAULT_STYLE, session: Any = None,
               workers: int = WORKERS, clock: Callable[[], float] = time.monotonic,
               prefetch_interval: float = PREFETCH_INTERVAL_SECONDS,
               write_through: Callable[[TileKey, bytes], bool | None] | None = None, usage: Any = None):
    self.style = style
    self._usage = usage  # MapboxUsage: every tile request made counts toward the month's Mapbox usage
    self.prefetch_interval = prefetch_interval
    self.cache = cache or TileCache(default_cache_dir(), style)
    self._token = token
    self._decode = decode or (lambda data, ext: data)
    self._session = session or requests.Session()
    self._clock = clock
    self._write_through = write_through

    self._cond = threading.Condition()
    self._visible: list[TileKey] = []
    self._prefetch: list[TileKey] = []
    self._prefetch_index = 0
    self._prefetch_refresh = False
    self.not_found: set[TileKey] = set()
    self._refresh: deque[TileKey] = deque(maxlen=256)
    self._inflight: set[TileKey] = set()
    self._delivered: set[TileKey] = set()
    self._missing: dict[TileKey, float] = {}
    self._results: deque[tuple[TileKey, Any]] = deque()
    self._offline_until = 0.0
    self._last_prefetch = 0.0
    self._stopped = False
    self.stats = {"network": 0, "disk": 0, "prefetched": 0, "failed": 0, "write_failed": 0}

    self._threads = [threading.Thread(target=self._scan_cache, name="nav-tiles-scan", daemon=True)]
    self._threads += [threading.Thread(target=self._worker, name=f"nav-tiles-{i}", daemon=True) for i in range(workers)]
    for thread in self._threads:
      thread.start()

  @property
  def offline(self) -> bool:
    return self._clock() < self._offline_until

  @property
  def prefetch_remaining(self) -> int:
    with self._cond:
      return max(0, len(self._prefetch) - self._prefetch_index)

  def want(self, keys: Sequence[TileKey]) -> None:
    """The tiles the map needs now, most important first. Replaces the previous set."""
    with self._cond:
      self._visible = [key for key in keys if key not in self._delivered]
      if self._visible:
        self._cond.notify_all()

  def forget(self, key: TileKey) -> None:
    """The caller dropped this tile; it may be asked for (and delivered) again."""
    with self._cond:
      self._delivered.discard(key)

  @property
  def idle(self) -> bool:
    """The background plan has been worked through and nothing is downloading."""
    with self._cond:
      return self._prefetch_index >= len(self._prefetch) and not self._inflight and not self._refresh

  @property
  def prefetch_position(self) -> int:
    with self._cond:
      return self._prefetch_index

  def prefetch(self, keys: Sequence[TileKey], refresh: bool = False) -> None:
    """Background download plan, e.g. the route corridor. Replaces the previous plan.

    ``refresh`` also downloads cached tiles, except ones written within
    ``REFRESH_AGE_SECONDS``, which are still fresh.
    """
    with self._cond:
      self._prefetch = list(keys)
      self._prefetch_index = 0
      self._prefetch_refresh = refresh
      self._cond.notify_all()

  def poll(self, limit: int = 2) -> list[tuple[TileKey, Any]]:
    results = []
    with self._cond:
      while self._results and len(results) < limit:
        results.append(self._results.popleft())
    return results

  def close(self) -> None:
    with self._cond:
      self._stopped = True
      self._cond.notify_all()

  def _scan_cache(self) -> None:
    if self.cache.max_bytes is None:
      return
    try:
      if self.cache.scan() > self.cache.max_bytes:
        self.cache.trim()
    except Exception:
      pass

  def _next_job(self) -> tuple[TileKey, bool] | None:
    """(key, deliver) under the lock; deliver=False is a background download only."""
    now = self._clock()
    for key in self._visible:
      if key in self._inflight or key in self._delivered:
        continue
      retry_at = self._missing.get(key)
      if retry_at is not None and now < retry_at:
        continue
      return key, True

    if self.offline or now - self._last_prefetch < self.prefetch_interval:
      return None
    while self._refresh:
      key = self._refresh.popleft()
      if key not in self._inflight:
        self._last_prefetch = now
        return key, False
    while self._prefetch_index < len(self._prefetch):
      key = self._prefetch[self._prefetch_index]
      self._prefetch_index += 1
      if key in self._inflight or now < self._missing.get(key, 0.0) or key in self.not_found:
        continue
      if self._prefetch_refresh:
        age = self.cache.age(key)
        if age is not None and age < REFRESH_AGE_SECONDS:
          continue
      elif self.cache.contains(key):
        continue
      self._last_prefetch = now
      return key, False
    return None

  def _worker(self) -> None:
    while True:
      with self._cond:
        job = None
        while not self._stopped:
          job = self._next_job()
          if job is not None:
            break
          self._cond.wait(timeout=max(0.02, self.prefetch_interval))
        if self._stopped:
          return
        key, deliver = job
        self._inflight.add(key)
      try:
        self._run_job(key, deliver)
      except Exception:
        self.stats["failed"] += 1
      finally:
        with self._cond:
          self._inflight.discard(key)

  def _run_job(self, key: TileKey, deliver: bool) -> None:
    if deliver:
      cached = self.cache.read(key)
      if cached is not None:
        data, age = cached
        self.stats["disk"] += 1
        self._save_viewed(key, data)
        self._deliver(key, data)
        if age > REFRESH_AGE_SECONDS:
          with self._cond:
            self._refresh.append(key)
        return

    data = self._download(key)
    if data is None:
      if deliver:
        # Not cached and not downloadable right now: wait for the network to come back.
        with self._cond:
          self._missing[key] = max(self._missing.get(key, 0.0), self._offline_until, self._clock() + 2.0)
      return
    if not self.cache.write(key, data):
      self.stats["write_failed"] += 1
    if deliver:
      self._save_viewed(key, data)
    if deliver:
      self._deliver(key, data)
    else:
      self.stats["prefetched"] += 1

  def _save_viewed(self, key: TileKey, data: bytes) -> None:
    if self._write_through is None or image_extension(data) is None:
      return
    try:
      if self._write_through(key, data) is False:
        self.stats["write_failed"] += 1
    except Exception:
      self.stats["write_failed"] += 1

  def _deliver(self, key: TileKey, data: bytes) -> None:
    extension = image_extension(data)
    if extension is None:
      return
    image = self._decode(data, extension)
    if image is None:
      return
    with self._cond:
      if self._stopped:
        return
      self._delivered.add(key)
      self._results.append((key, image))

  def _download(self, key: TileKey) -> bytes | None:
    if self.offline:
      return None
    token = self._token()
    if not token:
      with self._cond:
        self._offline_until = self._clock() + OFFLINE_BACKOFF_SECONDS
      return None
    url = TILE_URL.format(style=self.style, size=TILE_SIZE, z=key.z, x=key.x, y=key.y)
    try:
      response = self._session.get(url, params={"access_token": token}, timeout=REQUEST_TIMEOUT,
                                   headers={"Accept": "image/png,image/jpeg"})
    except requests.RequestException:
      with self._cond:
        self._offline_until = self._clock() + OFFLINE_BACKOFF_SECONDS
      return None

    status = response.status_code
    if self._usage is not None:
      self._usage.add("tiles", nbytes=len(response.content or b"") if status == 200 else 0)
    if status == 200 and image_extension(response.content) is not None:
      self.stats["network"] += 1
      return response.content
    self.stats["failed"] += 1
    with self._cond:
      if status in (401, 403):
        self._offline_until = self._clock() + AUTH_BACKOFF_SECONDS
      elif status == 429 or status >= 500:
        self._offline_until = self._clock() + OFFLINE_BACKOFF_SECONDS
      else:
        self._missing[key] = self._clock() + MISSING_RETRY_SECONDS
        if status == 404:
          self.not_found.add(key)
    return None

  def network_restored(self) -> None:
    """Retry everything that failed while offline."""
    with self._cond:
      self._offline_until = 0.0
      self._missing.clear()
      self._cond.notify_all()
