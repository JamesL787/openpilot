"""How many Mapbox requests this comma makes each month, for a small usage line in Offline Maps.

Counted here: map tiles (the Static Tiles API, by far the most requests) and
directions fetched on the device. Searches and maps opened in The Galaxy run in the
phone's browser and are not counted. Speed-limit lookups keep their own counter
(the MapBoxRequests param) and are read from there.

Several processes count at once (the car screen, navtilesd, navigationd), so each
keeps a small in-memory tally and merges it into usage.json under a file lock at
most every FLUSH_SECONDS. Months follow UTC, like Mapbox billing.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from openpilot.starpilot.navigation.map_tiles import offline_root

FREE_TILE_REQUESTS = 200_000       # Mapbox Static Tiles API free tier, per month
FREE_DIRECTIONS_REQUESTS = 100_000  # Mapbox Directions API free tier, per month
FLUSH_SECONDS = 30.0
FLUSH_COUNT = 200
MIN_VALID_YEAR = 2024  # before the clock is set the month is unknown; hold counts until it is
KINDS = ("tiles", "directions")


def usage_path(base: Path | None = None) -> Path:
  return offline_root(base) / "usage.json"


def month_key(wall: float) -> str | None:
  moment = time.gmtime(wall)
  return f"{moment.tm_year:04d}-{moment.tm_mon:02d}" if moment.tm_year >= MIN_VALID_YEAR else None


def _empty(month: str | None) -> dict[str, Any]:
  return {"month": month, "tiles": 0, "tile_bytes": 0, "directions": 0}


def read_usage(path: Path | None = None, wall: float | None = None) -> dict[str, Any]:
  """This month's counts (zeros after a month rollover nobody has flushed yet)."""
  path = path or usage_path()
  month = month_key(time.time() if wall is None else wall)  # noqa: TID251 - calendar month
  try:
    raw = json.loads(path.read_text())
  except (OSError, ValueError):
    raw = {}
  if not isinstance(raw, dict) or raw.get("month") != month:
    return _empty(month)
  return {**_empty(month), **{key: int(raw.get(key) or 0) for key in ("tiles", "tile_bytes", "directions")}}


class MapboxUsage:
  def __init__(self, path: Path | None = None, clock=time.monotonic, wall=time.time):  # noqa: TID251 - calendar month
    self.path = path or usage_path()
    self._clock, self._wall = clock, wall
    self._lock = threading.Lock()
    self._pending = _empty(None)
    self._count = 0
    self._flushed = clock()

  def add(self, kind: str, count: int = 1, nbytes: int = 0) -> None:
    if kind not in KINDS:
      raise ValueError(f"unknown Mapbox usage kind {kind}")
    with self._lock:
      self._pending[kind] += count
      if kind == "tiles":
        self._pending["tile_bytes"] += nbytes
      self._count += count
      due = self._count >= FLUSH_COUNT or self._clock() - self._flushed >= FLUSH_SECONDS
    if due:
      self.flush()

  def flush(self) -> bool:
    """Merge the pending counts into the file. False (counts kept) until the clock is set."""
    month = month_key(self._wall())
    if month is None:
      return False
    with self._lock:
      pending, self._pending, self._count = self._pending, _empty(None), 0
      self._flushed = self._clock()
    if not any(pending[key] for key in ("tiles", "tile_bytes", "directions")):
      return True
    try:
      self.path.parent.mkdir(parents=True, exist_ok=True)
      with self.path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = read_usage(self.path, self._wall())
        for key in ("tiles", "tile_bytes", "directions"):
          current[key] += pending[key]
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".usage-")
        with os.fdopen(fd, "w") as handle:
          json.dump(current, handle)
        os.replace(temporary, self.path)
      return True
    except OSError:
      with self._lock:  # try again next time rather than lose them
        for key in ("tiles", "tile_bytes", "directions"):
          self._pending[key] += pending[key]
      return False


_shared: MapboxUsage | None = None


def shared_usage() -> MapboxUsage:
  """The process-wide counter at the default path."""
  global _shared
  if _shared is None:
    _shared = MapboxUsage()
  return _shared
