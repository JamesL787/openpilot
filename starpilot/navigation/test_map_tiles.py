import os
import time

import requests

from openpilot.starpilot.navigation.map_tiles import (
  TILE_SIZE,
  TileCache,
  TileKey,
  TileService,
  corridor_tiles,
  tiles_covering,
  world_xy,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeResponse:
  def __init__(self, status_code=200, content=PNG):
    self.status_code = status_code
    self.content = content


class FakeSession:
  def __init__(self, response=None, error=None):
    self.response = response or FakeResponse()
    self.error = error
    self.calls = []

  def get(self, url, **kwargs):
    self.calls.append(url)
    if self.error is not None:
      raise self.error
    return self.response


def wait_for(predicate, timeout=3.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    if predicate():
      return True
    time.sleep(0.01)
  return False


def make_service(tmp_path, session, **kwargs):
  cache = TileCache(tmp_path, "test/style", min_free_bytes=0)
  return TileService(lambda: "token", cache=cache, session=session, **kwargs)


def test_world_xy_matches_tile_grid():
  x, y = world_xy(0.0, 0.0)
  assert abs(x - TILE_SIZE / 2) < 1e-9 and abs(y - TILE_SIZE / 2) < 1e-9
  # Same tile as the standard slippy-map formula (OSM wiki) gives for Las Vegas at z15.
  x, y = world_xy(36.3059, -115.3021)
  assert (int(x * (1 << 15) / TILE_SIZE), int(y * (1 << 15) / TILE_SIZE)) == (5888, 12833)


def test_tiles_covering_clamps_to_world():
  keys = tiles_covering(-10, -10, TILE_SIZE + 10, TILE_SIZE + 10, 1)
  assert sorted((k.x, k.y) for k in keys) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_corridor_tiles_follow_route_order_and_cover_long_segments():
  start, end = world_xy(36.30, -115.30), world_xy(36.30, -115.10)
  keys = corridor_tiles([start, end], zooms=(15,), radius_tiles=0)
  xs = [k.x for k in keys]
  assert xs == sorted(xs), "tiles near the start come first"
  assert xs == list(range(xs[0], xs[-1] + 1)), "no gaps along a long straight segment"


def test_corridor_tiles_interleave_zooms_and_respect_limit():
  points = [world_xy(36.30, -115.30), world_xy(36.10, -115.10)]
  keys = corridor_tiles(points, zooms=(13, 15), limit=50)
  assert len(keys) == 50
  assert {k.z for k in keys[:10]} == {13, 15}


def test_parent_key():
  assert TileKey(15, 101, 55).parent() == TileKey(14, 50, 27)
  assert TileKey(0, 0, 0).parent() is None


def test_visible_tile_downloads_caches_and_delivers(tmp_path):
  session = FakeSession()
  service = make_service(tmp_path, session)
  key = TileKey(15, 1, 2)
  service.want([key])
  assert wait_for(lambda: service.cache.contains(key))
  results = []
  assert wait_for(lambda: results.extend(service.poll()) or results)
  assert results[0][0] == key and results[0][1] == PNG
  service.close()


def test_cached_tile_is_served_without_network(tmp_path):
  cache = TileCache(tmp_path, "test/style", min_free_bytes=0)
  key = TileKey(14, 3, 4)
  assert cache.write(key, PNG)
  session = FakeSession(error=requests.ConnectionError("offline"))
  service = TileService(lambda: "token", cache=cache, session=session)
  service.want([key])
  results = []
  assert wait_for(lambda: results.extend(service.poll()) or results)
  assert session.calls == []
  service.close()


def test_visible_tiles_call_optional_write_through(tmp_path):
  regular = TileCache(tmp_path / "regular", "test/style", min_free_bytes=0)
  enabled = True
  saved = []

  def save(key, data):
    if enabled:
      saved.append((key, data))
      return True
    return None

  service = TileService(lambda: "token", cache=regular, session=FakeSession(),
                        write_through=save)
  first = TileKey(14, 3, 4)
  service.want([first])
  assert wait_for(lambda: bool(saved))
  assert saved == [(first, PNG)]

  enabled = False
  second = TileKey(14, 3, 5)
  service.want([second])
  assert wait_for(lambda: regular.contains(second))
  assert saved == [(first, PNG)]
  service.close()


def test_offline_backs_off_instead_of_spinning(tmp_path):
  session = FakeSession(error=requests.ConnectionError("offline"))
  service = make_service(tmp_path, session)
  service.want([TileKey(15, 9, 9)])
  assert wait_for(lambda: service.offline)
  time.sleep(0.3)
  assert len(session.calls) == 1
  service.close()


def test_prefetch_only_downloads_missing_tiles(tmp_path):
  session = FakeSession()
  service = make_service(tmp_path, session)
  cached, missing = TileKey(13, 1, 1), TileKey(13, 1, 2)
  service.cache.write(cached, PNG)
  service.prefetch([cached, missing])
  assert wait_for(lambda: service.cache.contains(missing))
  assert len(session.calls) == 1 and session.calls[0].endswith("/13/1/2")
  assert service.poll() == [], "prefetched tiles are not decoded or delivered"
  service.close()


def test_not_found_tile_is_not_retried_immediately(tmp_path):
  session = FakeSession(response=FakeResponse(404, b""))
  service = make_service(tmp_path, session)
  service.want([TileKey(15, 5, 5)])
  assert wait_for(lambda: len(session.calls) == 1)
  time.sleep(0.2)
  assert len(session.calls) == 1
  assert not service.offline
  service.close()


def test_cache_trims_least_recently_used(tmp_path):
  cache = TileCache(tmp_path, "test/style", max_bytes=len(PNG) * 3, min_free_bytes=0)
  cache.scan()
  keys = [TileKey(10, i, 0) for i in range(5)]
  for index, key in enumerate(keys):
    cache.write(key, PNG)
    path = cache.path(key)
    stamp = time.time() - 100 + index  # noqa: TID251 - file mtimes are wall-clock
    os.utime(path, (stamp, stamp))
  cache.trim()
  remaining = [key for key in keys if cache.contains(key)]
  assert remaining == keys[-2:]


def test_full_disk_skips_writes(tmp_path):
  cache = TileCache(tmp_path, "test/style", min_free_bytes=1 << 62)
  assert not cache.write(TileKey(1, 0, 0), PNG)
  assert not cache.contains(TileKey(1, 0, 0))
