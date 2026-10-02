#!/usr/bin/env python3
"""Downloads map tiles ahead of time so the navigation map works offline.

Runs onroad and offroad, independent of the car screen:
  * Route tiles for whatever route is relevant: the live route from navigationd,
    the destination set from the device or The Galaxy (routed here when
    navigationd isn't running yet), and the route being previewed. Any network,
    kept small, paced gently onroad.
  * Offline areas the user saved, on Wi-Fi only, with progress for the UI.
    Deleted areas have their tiles removed; areas re-download every few months.
Tiles are stored per map style. Saved areas are kept in every style the map
colors setting uses (light, dark, or both for automatic day and night); a style
the user discards, and the old traffic styles, are deleted here, only while
offroad: removing thousands of tiles would compete with the drive for the disk.
"""

from __future__ import annotations

import json
import math
import shutil
import threading
import time

import cereal.messaging as messaging
from cereal import log
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.starpilot.navigation.destination_store import parse_destination_json
from openpilot.starpilot.navigation.map_tiles import LEGACY_STYLES, TileCache, TileService, image_extension, offline_root
from openpilot.starpilot.navigation.mapbox_usage import MapboxUsage, usage_path
from openpilot.starpilot.navigation.offline_maps import (
  AREA_REFRESH_SECONDS,
  OFFLINE_MAX_BYTES,
  OfflineArea,
  OfflineMaps,
  route_tiles,
)
from openpilot.starpilot.navigation.route_engine import Coordinate, MapboxRouteEngine

LOOP_SECONDS = 1.0
AREA_CHECK_SECONDS = 5.0
PREVIEW_CHECK_SECONDS = 3.0
STATUS_SECONDS = 2.0
STATUS_HEARTBEAT_SECONDS = 10.0  # rewrite even when unchanged so readers can tell the service is alive
ROUTE_RETRY_SECONDS = 60.0
LIVE_ROUTE_STALE_SECONDS = 30.0
AREA_VERIFY_ATTEMPTS = 3
AREA_RETRY_SECONDS = 3600.0    # after an incomplete download or a full disk

ROUTE_INTERVAL_ONROAD = 0.35   # ~3 tiles/s while driving; the car screen shares the link
ROUTE_INTERVAL_OFFROAD = 0.12
AREA_INTERVAL = 0.08           # Wi-Fi only

UNMETERED = (log.DeviceState.NetworkType.wifi, log.DeviceState.NetworkType.ethernet)
# The one state a saved area shows when it has several styles: the first found here wins.
STATE_PRIORITY = ("downloading", "waiting_wifi", "storage_full", "no_space", "incomplete", "queued", "complete")
# The style the map isn't showing is a spare copy: when it can't finish, the area still reads as saved.
SPARE_FAILURES = ("storage_full", "no_space", "incomplete")


def _queued() -> dict:
  return {"state": "queued", "done": 0, "total": 0, "bytes": 0, "completed_at": 0.0}


def combine_states(states: list[dict]) -> dict:
  """One progress entry for an area kept in several styles."""
  if not states:
    return _queued()
  kinds = [state.get("state") or "queued" for state in states]
  kind = next((candidate for candidate in STATE_PRIORITY if candidate in kinds), kinds[0])
  complete = all(state == "complete" for state in kinds)
  return {
    "state": kind,
    "done": sum(int(state.get("done") or 0) for state in states),
    "total": sum(int(state.get("total") or 0) for state in states),
    "bytes": sum(int(state.get("bytes") or 0) for state in states),
    "completed_at": min(float(state.get("completed_at") or 0.0) for state in states) if complete else
                    max(float(state.get("completed_at") or 0.0) for state in states),
    "metered_wifi": any(bool(state.get("metered_wifi")) for state in states),
  }


def area_summary(styles: dict[str, dict], shown: str, kept: tuple[str, ...]) -> dict:
  """An area's progress as the map colors user sees it: the shown style first. The other style
  counts only while it is still on its way; once the shown one is saved, the area is saved."""
  primary = styles.get(shown) or _queued()
  counted = [primary]
  if primary.get("state") != "complete":
    counted += [state for style in kept if style != shown
                if (state := styles.get(style) or _queued()).get("state") not in SPARE_FAILURES]
  summary = combine_states(counted)
  summary["bytes"] = sum(int((styles.get(style) or {}).get("bytes") or 0) for style in kept)
  return summary


def _wall() -> float:
  return time.time()  # noqa: TID251 - persisted timestamps must survive reboots


def _signature(points: list[tuple[float, float]]) -> tuple | None:
  return (len(points), points[0], points[-1]) if points else None


class Navtilesd:
  def __init__(self, maps: OfflineMaps | None = None, sm=None, params: Params | None = None,
               route_engine: MapboxRouteEngine | None = None, session=None, workers: int = 2, usage: MapboxUsage | None = None):
    self.maps = maps or OfflineMaps()
    self.params = params or Params()
    self.params_memory = Params(memory=True) if params is None else params
    self.sm = sm if sm is not None else messaging.SubMaster(["deviceState", "navRoute"])
    self.usage = usage or MapboxUsage(usage_path(self.maps.base))
    self.route_engine = route_engine or MapboxRouteEngine(usage=self.usage)

    self._session, self._workers = session, workers
    self.area_caches: dict[str, TileCache] = {}
    self.area_services: dict[str, TileService] = {}
    self.route_service: TileService | None = None
    self.area_styles: tuple[str, ...] = ()
    self.style = ""  # the style the map shows now: route tiles and save-as-you-drive use it
    self._deleting: set[str] = set()
    self._route_plan: tuple | None = None
    self._use_styles(self.maps.active_styles(), self.maps.display_style())

    self.started = False
    self.device_known = False  # no deviceState yet: don't assume offroad
    self.unmetered = False
    self.network_up = False
    self.metered_wifi = False

    self._live_points: list[tuple[float, float]] = []
    self._live_at = -math.inf
    self._destination_key: tuple | None = None
    self._destination_points: list[tuple[float, float]] = []
    self._destination_attempt = -math.inf
    self._destination_fetching = False
    self._preview_points: list[tuple[float, float]] = []
    self._preview_checked = -math.inf
    self._route_total = 0

    self._areas_checked = -math.inf
    self._active_area: OfflineArea | None = None
    self._active_style = ""
    self._active_keys: list = []
    self._active_refresh = False
    self._active_queued = False
    self._verify_attempts = 0
    self._area_status: dict[str, dict] = dict(self.maps.status().get("areas", {}))
    self._offline_bytes: int | None = None
    self._status_written = -math.inf
    self._status_heartbeat = -math.inf
    self._last_status: dict | None = None

  @property
  def area_cache(self) -> TileCache:
    return self.area_caches[self.style]

  @property
  def area_service(self) -> TileService:
    return self.area_services[self.style]

  def _use_styles(self, area_styles: tuple[str, ...], display: str) -> None:
    wanted = tuple(dict.fromkeys((*area_styles, display)))
    for style in [style for style in self.area_services if style not in wanted]:
      self.area_services.pop(style).close()
      self.area_caches.pop(style)
    for style in wanted:
      if style not in self.area_caches:
        self.area_caches[style] = TileCache(offline_root(self.maps.base), style, max_bytes=None)
        self.area_services[style] = TileService(self._token, cache=self.area_caches[style], style=style, session=self._session,
                                                workers=self._workers + 1, prefetch_interval=AREA_INTERVAL, usage=self.usage)
    if display != self.style:
      if self.route_service is not None:
        self.route_service.close()
      self.route_cache = TileCache(self.maps.base, display, pinned=self.area_caches[display])
      self.route_service = TileService(self._token, cache=self.route_cache, style=display, session=self._session,
                                       workers=self._workers, prefetch_interval=ROUTE_INTERVAL_OFFROAD, usage=self.usage)
      self.style = display
      self._route_plan = None  # fetch the route again in the new style
    self.area_styles = tuple(area_styles)

  def _update_style(self, wall: float) -> None:
    """Follow the map colors setting (and, for automatic, the sun), and delete retired styles."""
    area_styles, display = self.maps.active_styles(), self.maps.display_style(wall)
    if (area_styles, display) != (self.area_styles, self.style):
      cloudlog.info(f"navtilesd: map styles {self.area_styles} -> {area_styles}, showing {display}")
      if self._active_area is not None and self._active_style not in area_styles:
        self._stop_active()
      self._use_styles(area_styles, display)
    if self.started or not self.device_known:
      return  # deletions wait for offroad
    for style in LEGACY_STYLES:
      if style in self._deleting or style in area_styles or style == display:
        continue
      roots = [root for root in self.maps.style_roots(style) if root.exists()]
      if not roots:
        continue
      self._deleting.add(style)
      for entry in self._area_status.values():
        (entry.get("styles") or {}).pop(style, None)
      threading.Thread(target=self._delete_style, args=(style, roots), name="navtilesd-delete", daemon=True).start()

  def _delete_style(self, style: str, roots: list) -> None:
    for root in roots:
      shutil.rmtree(root, ignore_errors=True)
    self._offline_bytes = None
    self._deleting.discard(style)
    cloudlog.info(f"navtilesd: deleted map style {style}")

  def _scan_offline(self) -> int:
    """Bytes of saved tiles in every style on disk, kept ones included: they share the limit."""
    root = offline_root(self.maps.base)
    try:
      styles = [path.name.replace("_", "/", 1) for path in root.iterdir() if path.is_dir() and path.name.startswith("mapbox_")]
    except OSError:
      return 0
    return sum((self.area_caches.get(style) or TileCache(root, style, max_bytes=None)).scan() for style in styles)

  def _style_state(self, area_id: str, style: str) -> dict:
    entry = self._area_status.setdefault(area_id, {})
    return entry.setdefault("styles", {}).setdefault(style, _queued())

  def _areas_summary(self) -> dict[str, dict]:
    summary = {}
    for area_id, entry in self._area_status.items():
      styles = entry.get("styles") or {}
      summary[area_id] = {**area_summary(styles, self.style, self.area_styles), "styles": styles}
    return summary

  def _token(self) -> str:
    return str(self.params.get("MapboxPublicKey", encoding="utf-8") or "").strip()

  # ── network ─────────────────────────────────────────────────────────────

  def _update_device(self) -> None:
    if not self.sm.seen["deviceState"]:
      return
    self.device_known = True
    state = self.sm["deviceState"]
    network_up = state.networkType != log.DeviceState.NetworkType.none
    if network_up and not self.network_up:
      # A connection just came back: retry at once instead of waiting out the offline backoff.
      self.route_service.network_restored()
      for service in self.area_services.values():
        service.network_restored()
    self.network_up = network_up
    metered = bool(getattr(state, "networkMetered", False))
    self.unmetered = state.networkType in UNMETERED and not metered
    self.metered_wifi = state.networkType in UNMETERED and metered
    self.started = bool(state.started)

  # ── route tiles ─────────────────────────────────────────────────────────

  def _last_position(self) -> Coordinate | None:
    for params in (self.params_memory, self.params):
      raw = params.get("LastGPSPosition", encoding="utf-8")
      try:
        state = json.loads(raw) if isinstance(raw, str) else raw
        latitude, longitude = float(state["latitude"]), float(state["longitude"])
      except (TypeError, ValueError, KeyError):
        continue
      if math.isfinite(latitude) and math.isfinite(longitude) and (abs(latitude) > 1e-6 or abs(longitude) > 1e-6):
        return Coordinate(latitude, longitude)
    return None

  def _update_destination_route(self, now: float) -> None:
    destination = parse_destination_json(self.params.get("NavDestination", encoding="utf-8"))
    if destination is None:
      self._destination_key, self._destination_points = None, []
      return
    key = (round(float(destination["latitude"]), 6), round(float(destination["longitude"]), 6), destination.get("routeId"))
    if key != self._destination_key:
      self._destination_key, self._destination_points, self._destination_attempt = key, [], -math.inf
    if self._destination_points or self._destination_fetching or now - self._destination_attempt < ROUTE_RETRY_SECONDS:
      return
    start = self._last_position()
    token = str(self.params.get("MapboxSecretKey", encoding="utf-8") or "").strip()
    if start is None or not token or not self.network_up:
      return
    self._destination_attempt = now
    self._destination_fetching = True

    def worker():
      try:
        route = self.route_engine.fetch_route(token, start, destination)
        if route is not None and self._destination_key == key:
          self._destination_points = [(point.latitude, point.longitude) for point in route.geometry]
      except Exception:
        cloudlog.exception("navtilesd: destination route failed")
      finally:
        self._destination_fetching = False

    threading.Thread(target=worker, name="navtilesd-route", daemon=True).start()

  def _update_route(self, now: float) -> None:
    if self.sm.updated["navRoute"]:
      message = self.sm["navRoute"]
      self._live_points = [(c.latitude, c.longitude) for c in message.coordinates] if self.sm.valid["navRoute"] else []
      self._live_at = now
    live = self._live_points if now - self._live_at < LIVE_ROUTE_STALE_SECONDS else []

    if not live:
      self._update_destination_route(now)
    if now - self._preview_checked >= PREVIEW_CHECK_SECONDS:
      self._preview_checked = now
      self._preview_points = self.maps.preview_route()

    primary = live or self._destination_points
    plan = (_signature(primary), _signature(self._preview_points))
    self.route_service.prefetch_interval = ROUTE_INTERVAL_ONROAD if self.started else ROUTE_INTERVAL_OFFROAD
    if plan == self._route_plan:
      return
    self._route_plan = plan
    keys = route_tiles(primary)
    seen = set(keys)
    keys += [key for key in route_tiles(self._preview_points) if key not in seen]
    self._route_total = len(keys)
    self.route_service.prefetch(keys)
    cloudlog.info(f"navtilesd: route plan {len(keys)} tiles")

  # ── offline areas ───────────────────────────────────────────────────────

  def _needs_download(self, area: OfflineArea, style: str, wall: float) -> tuple[bool, bool]:
    """(needs work, refresh every tile) for one of the area's styles."""
    state = self._style_state(area.id, style)
    completed_at = float(state.get("completed_at") or 0.0)
    if state.get("state") in ("incomplete", "storage_full", "no_space"):
      retry = area.update_requested > completed_at or wall - completed_at > AREA_RETRY_SECONDS
      return retry, area.update_requested > completed_at > 0
    if state.get("state") != "complete":
      return True, area.update_requested > completed_at > 0
    if area.update_requested > completed_at:
      return True, True
    if wall - completed_at > AREA_REFRESH_SECONDS and not self.started:
      return True, True
    return False, False

  def _delete_area(self, area: OfflineArea, remaining: list[OfflineArea]) -> None:
    keep = set()
    for other in remaining:
      keep.update(other.tiles())
    root = offline_root(self.maps.base)
    try:
      styles = [path.name.replace("_", "/", 1) for path in root.iterdir() if path.is_dir() and path.name.startswith("mapbox_")]
    except OSError:
      styles = []
    freed = 0
    for style in styles:  # kept styles too: a deleted area goes from every one
      cache = self.area_caches.get(style) or TileCache(root, style, max_bytes=None)
      freed += sum(cache.remove(key) for key in area.tiles() if key not in keep and not self.maps.is_auto_saved(key))
    if self._offline_bytes is not None:
      self._offline_bytes = max(0, self._offline_bytes - freed)
    self.maps.forget_area(area.id)
    self._area_status.pop(area.id, None)
    cloudlog.info(f"navtilesd: deleted area {area.id}, freed {freed} bytes")

  def _stop_active(self, state: str | None = None) -> None:
    if self._active_area is not None and state is not None:
      self._style_state(self._active_area.id, self._active_style).update(state=state, completed_at=_wall())
    service = self.area_services.get(self._active_style)
    self._active_area = None
    self._active_keys = []
    if service is not None:
      service.prefetch([])

  def _update_save_viewed(self) -> None:
    """Pin tiles already on disk when save-as-you-drive is switched on.

    The setting handler leaves a one-shot request; here we queue every tile in the
    temporary cache so navtilesd promotes it into pinned storage and it turns green.
    """
    if not self.maps.promote_requested():
      return
    self.maps.clear_promote_request()
    if not self.maps.save_viewed_cache():
      return
    marked = self.maps.mark_cached_tiles()
    cloudlog.info(f"navtilesd: queued {marked} cached tiles to save as you drive")

  def _update_auto_saved(self) -> None:
    """Promote tiles viewed while driving into the same pinned store as saved areas."""
    if self._offline_bytes is None:
      return
    for key in self.maps.pending_auto_saved():
      try:
        data = self.route_cache.path(key).read_bytes()
      except OSError:
        if self.area_cache.contains(key):
          self.maps.finish_auto_saved(key)
          continue
        # The regular LRU won the race. Viewing this tile again will queue it again.
        self.maps.forget_auto_saved(key)
        continue
      if image_extension(data) is None:
        self.maps.forget_auto_saved(key)
        continue
      try:
        previous_size = self.area_cache.path(key).stat().st_size
      except OSError:
        previous_size = 0
      size_change = len(data) - previous_size
      if self._offline_bytes + max(0, size_change) > OFFLINE_MAX_BYTES:
        break
      if not self.area_cache.write(key, data):
        break
      self._offline_bytes = max(0, self._offline_bytes + size_change)
      self.route_cache.remove(key)
      self.maps.finish_auto_saved(key)

  def _update_areas(self, now: float, wall: float) -> None:
    if now - self._areas_checked >= AREA_CHECK_SECONDS:
      self._areas_checked = now
      self._update_style(wall)
      if self._offline_bytes is None:
        self._offline_bytes = self._scan_offline()
      areas = self.maps.areas(include_deleted=True)
      live = [area for area in areas if not area.deleted]
      for area in areas:
        if area.deleted:
          if self._active_area is not None and self._active_area.id == area.id:
            self._stop_active()
          self._delete_area(area, live)
      if self._active_area is not None:
        current = next((area for area in live if area.id == self._active_area.id), None)
        if current is None or current.update_requested != self._active_area.update_requested:
          self._stop_active()
        elif current.allow_metered != self._active_area.allow_metered:
          self._active_area = current
      if self._active_area is None:
        # Every area in the shown style before any spare copy in the other.
        styles = sorted(self.area_styles, key=lambda style: style != self.style)
        work = ((area, style) for style in styles for area in live)
        for area, style in work:
          needed, refresh = self._needs_download(area, style, wall)
          if needed:
            self._start_area(area, style, refresh)
            break

    area = self._active_area
    if area is None:
      return
    service = self.area_services[self._active_style]
    state = self._style_state(area.id, self._active_style)
    if not (self.unmetered or (area.allow_metered and self.network_up)):
      if service.prefetch_position or not service.idle:
        service.prefetch([])
      state["state"] = "waiting_wifi"
      state["metered_wifi"] = self.metered_wifi
      self._active_queued = False
      return
    if self._offline_bytes is not None and self._offline_bytes >= OFFLINE_MAX_BYTES and not self._active_refresh:
      self._stop_active("storage_full")
      return
    if service.stats["write_failed"]:
      service.stats["write_failed"] = 0
      self._stop_active("no_space")
      return
    if not self._active_queued:
      service.prefetch(self._active_keys, refresh=self._active_refresh)
      self._active_queued = True
    state["state"] = "downloading"
    state["done"] = min(state["total"], service.prefetch_position)
    if service.idle:
      self._verify_area(area, wall)

  def _start_area(self, area: OfflineArea, style: str, refresh: bool) -> None:
    self._active_area = area
    self._active_style = style
    self._active_keys = area.tiles()
    self._active_refresh = refresh
    self._verify_attempts = 0
    self._active_queued = False
    state = self._style_state(area.id, style)
    state.update(total=len(self._active_keys), done=0, state="queued")
    cloudlog.info(f"navtilesd: area {area.id} {style} {len(self._active_keys)} tiles refresh={refresh}")

  def _verify_area(self, area: OfflineArea, wall: float) -> None:
    service, cache = self.area_services[self._active_style], self.area_caches[self._active_style]
    missing = [key for key in self._active_keys if key not in service.not_found and not cache.contains(key)]
    state = self._style_state(area.id, self._active_style)
    if missing and self._verify_attempts < AREA_VERIFY_ATTEMPTS:
      # Some downloads failed (dropped connection); fetch just those again.
      self._verify_attempts += 1
      self._active_refresh = False
      self._active_keys = missing
      service.prefetch(missing)
      return
    total_bytes = 0
    for key in area.tiles():
      try:
        total_bytes += cache.path(key).stat().st_size
      except OSError:
        pass
    state.update(bytes=total_bytes, done=state["total"] - len(missing),
                 state="complete" if not missing else "incomplete", completed_at=wall)
    self._offline_bytes = self._scan_offline()
    self._active_area = None
    self._active_keys = []

  # ── status ──────────────────────────────────────────────────────────────

  def _write_status(self, now: float, wall: float) -> None:
    if now - self._status_written < STATUS_SECONDS:
      return
    status = {
      "route": {"total": self._route_total, "remaining": self.route_service.prefetch_remaining if self._route_total else 0},
      "areas": self._areas_summary(),
      "offline_bytes": self._offline_bytes or 0,
      "unmetered": self.unmetered,
      "offline": self.route_service.offline or not self.network_up,
    }
    if status != self._last_status or now - self._status_heartbeat >= STATUS_HEARTBEAT_SECONDS:
      self._last_status = json.loads(json.dumps(status))
      self.maps.write_status(dict(status, updated=wall))
      self._status_heartbeat = now
    self._status_written = now

  def step(self, now: float | None = None, wall: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    wall = _wall() if wall is None else wall
    self.sm.update(0)
    self._update_device()
    self._update_route(now)
    self._update_areas(now, wall)
    self._update_save_viewed()
    self._update_auto_saved()
    self._write_status(now, wall)

  def run(self) -> None:
    cloudlog.warning("navtilesd init")
    while True:
      try:
        self.step()
      except Exception:
        cloudlog.exception("navtilesd step failed")
      time.sleep(LOOP_SECONDS)


def main() -> None:
  Navtilesd().run()


if __name__ == "__main__":
  main()
