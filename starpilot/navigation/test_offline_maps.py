import json
import math
import os
import time
from types import SimpleNamespace

import pytest
from cereal import log

from openpilot.starpilot.navigation import navtilesd as navtilesd_module
from openpilot.starpilot.navigation.map_tiles import REFRESH_AGE_SECONDS, TILE_SIZE, TileKey, world_xy
from openpilot.starpilot.navigation.offline_maps import (
  DETAIL_ZOOM,
  ROUTE_ZOOMS,
  OfflineMaps,
  area_tiles,
  estimate_area,
  route_tiles,
  turn_points,
)
from openpilot.starpilot.navigation.route_engine import Coordinate

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WIFI, CELL = log.DeviceState.NetworkType.wifi, log.DeviceState.NetworkType.cell4G


def l_shaped_route(steps=40, step_deg=0.0005):
  """East for a while, then a right-angle turn north."""
  east = [(36.0, -115.0 + i * step_deg) for i in range(steps)]
  north = [(36.0 + i * step_deg, east[-1][1]) for i in range(1, steps)]
  return east + north


def test_turn_points_find_a_right_angle_turn():
  route = l_shaped_route()
  turns = turn_points(route)
  assert len(turns) == 1
  corner = route[39]
  assert abs(turns[0][0] - corner[0]) < 1e-3 and abs(turns[0][1] - corner[1]) < 1e-3


def test_turn_points_ignore_a_gentle_curve():
  # A quarter circle of ~1 km radius drawn with many short segments.
  curve = [(36.0 + 0.009 * math.sin(t / 50 * math.pi / 2), -115.0 + 0.011 * (1 - math.cos(t / 50 * math.pi / 2))) for t in range(51)]
  assert turn_points(curve) == []


def test_route_tiles_put_destination_detail_first_then_the_corridor():
  route = l_shaped_route()
  keys = route_tiles(route)
  assert len(keys) == len(set(keys))
  dest_x, dest_y = world_xy(*route[-1])
  scale = (1 << DETAIL_ZOOM) / TILE_SIZE
  assert keys[0].z == DETAIL_ZOOM
  assert abs(keys[0].x - dest_x * scale) < 2 and abs(keys[0].y - dest_y * scale) < 2
  assert {key.z for key in keys} == {DETAIL_ZOOM, *ROUTE_ZOOMS}
  first_corridor = next(index for index, key in enumerate(keys) if key.z != DETAIL_ZOOM)
  assert all(key.z != DETAIL_ZOOM for key in keys[first_corridor:])


def test_area_tiles_cover_the_radius_coarse_zooms_first():
  keys = area_tiles(36.1, -115.2, 10.0, 14)
  zooms = [key.z for key in keys]
  assert zooms == sorted(zooms) and zooms[0] == 8 and zooms[-1] == 14
  center_x, center_y = world_xy(36.1, -115.2)
  z14 = [key for key in keys if key.z == 14]
  scale = (1 << 14) / TILE_SIZE
  assert (int(center_x * scale), int(center_y * scale)) == (z14[0].x, z14[0].y), "centre first"
  # ~20 km across at z14 (~1.9 km tiles here) is roughly 10 x 10 tiles inside the circle.
  assert 60 < len(z14) < 130


def test_estimate_grows_with_radius_and_zoom():
  small, small_bytes = estimate_area(36.1, -115.2, 10.0, 14)
  larger, _ = estimate_area(36.1, -115.2, 20.0, 14)
  deeper, _ = estimate_area(36.1, -115.2, 10.0, 15)
  assert small_bytes > 0 and larger > 3 * small and deeper > 3 * small


def test_offline_maps_state_round_trips(tmp_path):
  maps = OfflineMaps(tmp_path)
  area = maps.add_area("Summerlin", 36.1, -115.3, 10.0, 15)
  assert [a.name for a in maps.areas()] == ["Summerlin"]
  maps.request_update(area.id)
  assert maps.areas()[0].update_requested > 0
  maps.delete_area(area.id)
  assert maps.areas() == [] and maps.areas(include_deleted=True)[0].deleted
  maps.forget_area(area.id)
  assert maps.areas(include_deleted=True) == []

  maps.set_preview_route([(36.1, -115.3), (36.2, -115.2)])
  assert maps.preview_route() == [(36.1, -115.3), (36.2, -115.2)]
  payload = json.loads(maps.preview_path.read_text())
  payload["at"] -= 3600
  maps.preview_path.write_text(json.dumps(payload))
  assert maps.preview_route() == [], "stale previews are ignored"

  maps.write_status({"route": {"total": 3}})
  assert maps.status()["route"]["total"] == 3


# ── navtilesd ────────────────────────────────────────────────────────────────

class FakeResponse:
  status_code = 200
  content = PNG


class FakeSession:
  def __init__(self):
    self.urls = []

  def get(self, url, **kwargs):
    self.urls.append(url)
    return FakeResponse()


class FakeParams:
  def __init__(self, values):
    self.values = values

  def get(self, key, encoding=None):
    return self.values.get(key)


class FakeSM:
  def __init__(self, network=WIFI, started=False):
    self.device = SimpleNamespace(networkType=network, started=started, networkMetered=False)
    self.seen = {"deviceState": True, "navRoute": False}
    self.updated = {"deviceState": True, "navRoute": False}
    self.valid = {"deviceState": True, "navRoute": True}
    self.nav_route = None

  def update(self, timeout=0):
    pass

  def __getitem__(self, key):
    return self.device if key == "deviceState" else self.nav_route


class FakeRouteEngine:
  def __init__(self, points):
    self.points = points
    self.calls = 0

  def fetch_route(self, token, start, destination, bearing=None):
    self.calls += 1
    return SimpleNamespace(geometry=[Coordinate(lat, lon) for lat, lon in self.points])


def put(base, z, x, y, style=None):
  """A tile on disk under ``base`` (the temporary cache, or the offline root) in ``style`` (default: dark)."""
  from openpilot.starpilot.navigation.map_tiles import DEFAULT_STYLE, TileCache
  path = TileCache(base, style or DEFAULT_STYLE).path(TileKey(z, x, y))
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(PNG)
  return path


def run_until(daemon, predicate, timeout=10.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    daemon.step()
    if predicate():
      return True
    time.sleep(0.02)
  return False


@pytest.fixture
def fast(monkeypatch):
  monkeypatch.setattr(navtilesd_module, "ROUTE_INTERVAL_OFFROAD", 0.0)
  monkeypatch.setattr(navtilesd_module, "AREA_INTERVAL", 0.0)
  monkeypatch.setattr(navtilesd_module, "AREA_CHECK_SECONDS", 0.0)
  monkeypatch.setattr(navtilesd_module, "STATUS_SECONDS", 0.0)


def make_daemon(tmp_path, params=None, sm=None, route_points=None):
  params = FakeParams(params or {"MapboxPublicKey": "pk", "MapboxSecretKey": "sk"})
  session = FakeSession()
  maps = OfflineMaps(tmp_path)
  maps.set_map_theme("dark")  # one style, so tile counts are per area; the default keeps both
  daemon = navtilesd_module.Navtilesd(maps=maps, sm=sm or FakeSM(), params=params,
                                      route_engine=FakeRouteEngine(route_points or l_shaped_route(12, 0.002)), session=session)
  daemon.area_service.prefetch_interval = 0.0
  daemon.area_cache.min_free_bytes = daemon.route_cache.min_free_bytes = 0  # tmp_path may be on a small partition
  return daemon, session


def test_destination_set_offroad_is_routed_and_saved(tmp_path, fast):
  destination = {"name": "Work", "place_name": "Work", "latitude": 36.02, "longitude": -114.98}
  gps = json.dumps({"latitude": 36.0, "longitude": -115.0})
  daemon, session = make_daemon(tmp_path, {"MapboxPublicKey": "pk", "MapboxSecretKey": "sk",
                                           "NavDestination": json.dumps(destination), "LastGPSPosition": gps})
  assert run_until(daemon, lambda: daemon.route_service.idle and daemon._route_total > 0 and
                   daemon.maps.status().get("route", {}).get("remaining") == 0)
  assert daemon.route_engine.calls == 1
  assert len(session.urls) == daemon._route_total
  assert all(daemon.route_cache.contains(key) for key in route_tiles(daemon._destination_points))


def test_areas_wait_for_wifi_then_complete(tmp_path, fast):
  sm = FakeSM(network=CELL)
  daemon, session = make_daemon(tmp_path, sm=sm)
  area = daemon.maps.add_area("Home", 36.1, -115.2, 1.0, 11)
  for _ in range(5):
    daemon.step()
    time.sleep(0.02)
  assert daemon.maps.status()["areas"][area.id]["state"] == "waiting_wifi"
  assert session.urls == [], "no area downloads on cellular"

  sm.device.networkType = WIFI
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "complete")
  state = daemon.maps.status()["areas"][area.id]
  assert state["done"] == state["total"] == len(area.tiles())
  assert state["bytes"] == len(PNG) * len(area.tiles())
  assert all(daemon.area_cache.contains(key) for key in area.tiles())


def test_metered_wifi_waits_until_download_now(tmp_path, fast):
  sm = FakeSM(network=WIFI)
  sm.device.networkMetered = True
  daemon, session = make_daemon(tmp_path, sm=sm)
  area = daemon.maps.add_area("Home", 36.1, -115.2, 1.0, 10)
  for _ in range(5):
    daemon.step()
    time.sleep(0.02)
  state = daemon.maps.status()["areas"][area.id]
  assert state["state"] == "waiting_wifi" and state["metered_wifi"]
  assert session.urls == []

  daemon.maps.allow_metered(area.id)
  assert run_until(daemon, lambda: daemon.maps.status()["areas"][area.id]["state"] == "complete")


def test_route_tiles_already_in_an_area_are_not_downloaded(tmp_path, fast):
  daemon, session = make_daemon(tmp_path)
  key = TileKey(15, 5889, 12869)
  daemon.area_cache.write(key, PNG)
  daemon.route_service.prefetch_interval = 0.0
  daemon.route_service.prefetch([key, TileKey(15, 5890, 12869)])
  deadline = time.monotonic() + 5.0
  while time.monotonic() < deadline and not (daemon.route_service.idle and session.urls):
    time.sleep(0.02)
  assert [url.split("/")[-1] for url in session.urls] == ["12869"] and "/5890/" in session.urls[0]


def test_tiles_saved_while_driving_are_promoted_into_pinned_storage(tmp_path, fast):
  daemon, _ = make_daemon(tmp_path)
  key = TileKey(15, 5889, 12869)
  assert daemon.route_cache.write(key, PNG)
  assert daemon.maps.mark_auto_saved(key)
  daemon.step()
  assert daemon.area_cache.contains(key)
  assert not daemon.route_cache.path(key).is_file()
  assert daemon.maps.pending_auto_saved() == []
  assert daemon.maps.status()["offline_bytes"] == len(PNG)


def test_deleting_an_area_keeps_tiles_also_saved_while_driving(tmp_path, fast):
  daemon, _ = make_daemon(tmp_path)
  area = daemon.maps.add_area("Driven", 36.1, -115.2, 1.0, 10)
  key = area.tiles()[0]
  assert daemon.area_cache.write(key, PNG)
  assert daemon.maps.mark_auto_saved(key)
  daemon.maps.finish_auto_saved(key)
  daemon._offline_bytes = len(PNG)
  daemon._delete_area(area, [])
  assert daemon.area_cache.contains(key)
  assert daemon._offline_bytes == len(PNG)


def test_deleting_an_area_keeps_tiles_another_area_shares(tmp_path, fast):
  daemon, _ = make_daemon(tmp_path)
  first = daemon.maps.add_area("A", 36.1, -115.2, 1.0, 10)
  second = daemon.maps.add_area("B", 36.1, -115.2, 1.0, 11)
  assert run_until(daemon, lambda: all(daemon.maps.status().get("areas", {}).get(a.id, {}).get("state") == "complete" for a in (first, second)))
  shared = set(first.tiles()) & set(second.tiles())
  only_second = set(second.tiles()) - set(first.tiles())
  assert shared and only_second

  daemon.maps.delete_area(second.id)
  assert run_until(daemon, lambda: not daemon.maps.areas(include_deleted=True)[1:])
  assert all(daemon.area_cache.contains(key) for key in shared)
  assert not any(daemon.area_cache.contains(key) for key in only_second)
  assert second.id not in daemon.maps.status().get("areas", {})


def test_full_disk_is_reported_instead_of_retrying(tmp_path, fast):
  daemon, _ = make_daemon(tmp_path)
  daemon.area_cache.min_free_bytes = 1 << 62
  area = daemon.maps.add_area("Home", 36.1, -115.2, 1.0, 10)
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "no_space")


def test_update_skips_fresh_tiles_and_refreshes_stale_ones(tmp_path, fast):
  daemon, session = make_daemon(tmp_path)
  area = daemon.maps.add_area("Home", 36.1, -115.2, 1.0, 10)
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "complete")
  first_pass = len(session.urls)
  completed_at = daemon.maps.status()["areas"][area.id]["completed_at"]

  time.sleep(0.01)
  daemon.maps.request_update(area.id)
  assert run_until(daemon, lambda: daemon.maps.status()["areas"][area.id]["completed_at"] > completed_at)
  assert len(session.urls) == first_pass, "tiles downloaded within 30 days are not fetched again"

  stale = time.time() - REFRESH_AGE_SECONDS - 60  # noqa: TID251 - file mtimes are wall-clock
  for key in area.tiles():
    os.utime(daemon.area_cache.path(key), (stale, stale))
  completed_at = daemon.maps.status()["areas"][area.id]["completed_at"]
  time.sleep(0.01)
  daemon.maps.request_update(area.id)
  assert run_until(daemon, lambda: daemon.maps.status()["areas"][area.id]["completed_at"] > completed_at)
  assert len(session.urls) == 2 * first_pass, "stale tiles are refreshed"


def test_enabling_save_as_you_drive_promotes_cached_tiles(tmp_path, fast):
  daemon, _ = make_daemon(tmp_path)
  keys = [TileKey(15, 5889, 12869), TileKey(15, 5890, 12869)]
  for key in keys:
    assert daemon.route_cache.write(key, PNG)

  daemon.maps.set_save_viewed_cache(True)
  assert run_until(daemon, lambda: all(daemon.area_cache.contains(key) for key in keys))
  assert all(daemon.maps.is_auto_saved(key) for key in keys)
  assert daemon.maps.pending_auto_saved() == []
  assert not daemon.maps.promote_requested()


def test_promote_cached_tiles_skips_already_pinned(tmp_path):
  maps = OfflineMaps(tmp_path)
  key = TileKey(2, 1, 1)
  put(maps.root, 2, 1, 1)
  put(maps.base, 2, 1, 1)
  assert maps.mark_cached_tiles() == 0
  assert maps.pending_auto_saved() == []


def test_saved_route_downloads_its_route_tiles(tmp_path, fast):
  daemon, session = make_daemon(tmp_path)
  points = l_shaped_route(15, 0.002)
  route = daemon.maps.add_route("Trip", points, 5000.0, 600.0, "Home")
  assert route.kind == "route" and route.tiles() == route_tiles(points)
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(route.id, {}).get("state") == "complete")
  assert all(daemon.area_cache.contains(key) for key in route_tiles(points))

  summary = daemon.maps.summary()
  [item] = summary["items"]
  assert item["kind"] == "route" and item["state"] == "complete" and item["origin_name"] == "Home"
  assert summary["service_running"] is True


def test_summary_thins_long_routes_for_display(tmp_path):
  maps = OfflineMaps(tmp_path)
  points = [(36.0 + i * 1e-4, -115.0) for i in range(3000)]
  maps.add_route("Long", points)
  [item] = maps.summary()["items"]
  assert len(item["points"]) <= 401 and item["points"][-1] == [points[-1][0], points[-1][1]]
  assert maps.summary()["service_running"] is False


def test_clean_route_points_validates_and_thins():
  from openpilot.starpilot.navigation.offline_maps import MAX_ROUTE_POINTS, clean_route_points
  assert clean_route_points([[36.1, -115.2], {"latitude": 36.2, "longitude": -115.1}]) == [(36.1, -115.2), (36.2, -115.1)]
  assert clean_route_points([[36.1, -115.2]]) is None
  assert clean_route_points([[36.1, -115.2], [91, 0]]) is None
  assert clean_route_points("nope") is None
  long_route = [[36.0 + i * 1e-5, -115.0] for i in range(MAX_ROUTE_POINTS * 3)]
  thinned = clean_route_points(long_route)
  assert len(thinned) <= MAX_ROUTE_POINTS + 1 and thinned[-1] == tuple(long_route[-1])


def test_map_colors_pick_styles_and_keep_other_settings(tmp_path):
  from openpilot.starpilot.navigation.map_tiles import DARK_STYLE, LIGHT_STYLE
  maps = OfflineMaps(tmp_path, position=lambda: None)
  assert maps.map_theme() == "auto" and maps.active_styles() == (LIGHT_STYLE, DARK_STYLE), "both colors download by default"
  maps.set_save_viewed_cache(True)
  maps.set_map_theme("light")
  assert maps.style == LIGHT_STYLE and maps.save_viewed_cache() is True
  maps.set_save_viewed_cache(False)
  assert maps.map_theme() == "light", "each setting keeps the other"
  assert maps.summary()["map_theme"] == "light"
  with pytest.raises(ValueError):
    maps.set_map_theme("traffic")


def test_dropped_styles_are_kept_unless_discarded(tmp_path):
  from openpilot.starpilot.navigation.map_tiles import DARK_STYLE, LIGHT_STYLE
  maps = OfflineMaps(tmp_path, position=lambda: None)
  maps.set_map_theme("auto")
  assert maps.dropped_styles("light") == [DARK_STYLE] and maps.dropped_styles("auto") == []
  maps.set_map_theme("light")
  assert maps.pending_discards() == [], "kept by default"
  maps.set_map_theme("dark", discard_dropped=True)
  assert maps.pending_discards() == [LIGHT_STYLE]
  maps.set_map_theme("light")
  assert maps.pending_discards() == [], "choosing it again before it was deleted cancels the delete"


def test_automatic_colors_follow_the_sun():
  from openpilot.starpilot.navigation.map_tiles import DARK_STYLE, LIGHT_STYLE
  from openpilot.starpilot.navigation.offline_maps import sun_elevation, theme_style
  las_vegas = (36.17, -115.14)
  noon = 1790622000.0    # 2026-09-28 19:00 UTC, about local solar noon
  midnight = 1790665200.0  # 2026-09-29 07:00 UTC
  assert sun_elevation(*las_vegas, noon) > 45 and sun_elevation(*las_vegas, midnight) < -30
  assert theme_style("auto", las_vegas, noon) == LIGHT_STYLE
  assert theme_style("auto", las_vegas, midnight) == DARK_STYLE
  assert theme_style("light", las_vegas, midnight) == LIGHT_STYLE and theme_style("dark", las_vegas, noon) == DARK_STYLE
  # Sunset in Las Vegas on 2026-09-28 is about 18:32 local (01:32 UTC the next day).
  assert theme_style("auto", las_vegas, 1790645520.0 - 600) == LIGHT_STYLE
  assert theme_style("auto", las_vegas, 1790645520.0 + 600) == DARK_STYLE


def test_light_and_dark_keeps_areas_in_both_styles(tmp_path, fast):
  from openpilot.starpilot.navigation.map_tiles import DARK_STYLE, LIGHT_STYLE
  daemon, session = make_daemon(tmp_path, sm=FakeSM(network=WIFI))
  area = daemon.maps.add_area("Home", 36.1, -115.2, 1.0, 10)
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "complete")
  assert all(DARK_STYLE in url for url in session.urls)

  daemon.maps.set_map_theme("auto")
  session.urls.clear()
  daemon.step()
  assert daemon.area_styles == (LIGHT_STYLE, DARK_STYLE)
  assert daemon.maps.status()["areas"][area.id]["state"] != "complete", "the light copy still needs downloading"
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "complete")
  assert session.urls and all(LIGHT_STYLE in url for url in session.urls), "the dark copy is kept, not fetched again"
  for style in (LIGHT_STYLE, DARK_STYLE):
    assert all(daemon.area_caches[style].contains(key) for key in area.tiles())
  state = daemon.maps.status()["areas"][area.id]
  assert state["done"] == state["total"] == 2 * len(area.tiles())


def test_discarded_and_traffic_styles_are_deleted(tmp_path, fast):
  from openpilot.starpilot.navigation.map_tiles import DARK_STYLE, LEGACY_STYLES, LIGHT_STYLE
  daemon, _ = make_daemon(tmp_path, sm=FakeSM(network=WIFI))
  legacy = daemon.maps.style_roots(LEGACY_STYLES[0])
  put(daemon.maps.root, 2, 1, 1, LEGACY_STYLES[0])
  put(daemon.maps.base, 2, 1, 1, LEGACY_STYLES[0])
  area = daemon.maps.add_area("Home", 36.1, -115.2, 1.0, 10)
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "complete")
  assert run_until(daemon, lambda: not legacy[0].exists() and not legacy[1].exists()), "tiles with old traffic baked in are removed"

  daemon.maps.set_map_theme("light", discard_dropped=True)
  dark = daemon.maps.style_roots(DARK_STYLE)[0]
  assert dark.exists()
  assert run_until(daemon, lambda: not dark.exists() and daemon.maps.pending_discards() == [])
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "complete")
  assert all(daemon.area_caches[LIGHT_STYLE].contains(key) for key in area.tiles())


def test_mapbox_usage_counts_across_processes_by_month(tmp_path):
  from openpilot.starpilot.navigation import mapbox_usage
  path = tmp_path / "usage.json"
  wall = [1790622000.0]  # September 2026
  first = mapbox_usage.MapboxUsage(path, clock=lambda: 0.0, wall=lambda: wall[0])
  second = mapbox_usage.MapboxUsage(path, clock=lambda: 0.0, wall=lambda: wall[0])
  first.add("tiles", nbytes=1000)
  second.add("tiles", 2, nbytes=500)
  second.add("directions")
  assert mapbox_usage.read_usage(path, wall[0])["tiles"] == 0, "held in memory until a flush"
  assert first.flush() and second.flush()
  assert mapbox_usage.read_usage(path, wall[0]) == {"month": "2026-09", "tiles": 3, "tile_bytes": 1500, "directions": 1}
  wall[0] += 5 * 86400  # October
  assert mapbox_usage.read_usage(path, wall[0])["tiles"] == 0
  first.add("tiles")
  first.flush()
  assert mapbox_usage.read_usage(path, wall[0])["tiles"] == 1


def test_mapbox_usage_waits_for_the_clock(tmp_path):
  from openpilot.starpilot.navigation import mapbox_usage
  path = tmp_path / "usage.json"
  wall = [0.0]
  usage = mapbox_usage.MapboxUsage(path, clock=lambda: 0.0, wall=lambda: wall[0])
  usage.add("tiles")
  assert not usage.flush() and not path.exists()
  wall[0] = 1790622000.0
  usage.add("tiles")
  assert usage.flush()
  assert mapbox_usage.read_usage(path, wall[0])["tiles"] == 2, "counts from before the clock was set are kept"


def test_tile_downloads_count_as_usage(tmp_path, fast):
  daemon, session = make_daemon(tmp_path, sm=FakeSM(network=WIFI))
  area = daemon.maps.add_area("Home", 36.1, -115.2, 1.0, 10)
  assert run_until(daemon, lambda: daemon.maps.status().get("areas", {}).get(area.id, {}).get("state") == "complete")
  assert daemon.usage.flush()
  assert daemon.maps.usage()["tiles"] == len(session.urls) > 0


def test_map_deletions_wait_for_offroad(tmp_path, fast):
  from openpilot.starpilot.navigation.map_tiles import LEGACY_STYLES
  sm = FakeSM(network=WIFI, started=True)
  daemon, _ = make_daemon(tmp_path, sm=sm)
  legacy = daemon.maps.style_roots(LEGACY_STYLES[0])
  put(daemon.maps.root, 2, 1, 1, LEGACY_STYLES[0])
  daemon.maps.set_map_theme("light", discard_dropped=False)
  daemon.maps.set_map_theme("dark", discard_dropped=True)
  for _ in range(5):
    daemon.step()
    time.sleep(0.02)
  assert legacy[0].exists(), "nothing is deleted onroad"
  assert daemon.maps.pending_discards() != [], "the delete is still queued"

  sm.device.started = False
  assert run_until(daemon, lambda: not legacy[0].exists() and daemon.maps.pending_discards() == [])


def test_map_deletions_wait_until_the_device_state_is_known(tmp_path, fast):
  from openpilot.starpilot.navigation.map_tiles import LEGACY_STYLES
  sm = FakeSM(network=WIFI)
  sm.seen["deviceState"] = False
  daemon, _ = make_daemon(tmp_path, sm=sm)
  put(daemon.maps.root, 2, 1, 1, LEGACY_STYLES[0])
  for _ in range(3):
    daemon.step()
  assert daemon.maps.style_roots(LEGACY_STYLES[0])[0].exists()
