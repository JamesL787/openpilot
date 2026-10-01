from openpilot.starpilot.navigation.map_tiles import DEFAULT_STYLE, TileCache, TileKey
from openpilot.starpilot.navigation.offline_maps import OfflineMaps
import pytest


def put(base, z, x, y, data=b'png'):
  path = TileCache(base, DEFAULT_STYLE).path(TileKey(z, x, y))
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(data)


def test_coverage_reports_present_tiles_at_exact_zoom(tmp_path):
  maps = OfflineMaps(tmp_path)
  maps.add_area('Not downloaded', 0, 0, 10, 16)
  put(maps.root, 2, 2, 2)
  put(maps.base, 2, 2, 2)  # saved wins over the temporary duplicate
  put(maps.base, 2, 1, 1)
  put(maps.root, 3, 2, 2)
  put(maps.root, 2, 3, 3, b'')
  result = maps.coverage(2, -180, -85, 180, 85)
  assert sorted(result['tiles']) == [[1, 1, False], [2, 2, True]]
  assert not result['truncated']
  assert maps.coverage(16, -180, -85, 180, 85)['tiles'] == []
  assert maps.coverage(2, 1, -20, 20, -1)['tiles'] == [[2, 2, True]]
  assert maps.coverage(2, -180, -85, 180, 85, limit=1)['truncated']


def test_coverage_wraps_at_dateline_and_tracks_deletions(tmp_path):
  maps = OfflineMaps(tmp_path)
  put(maps.root, 2, 0, 2)
  put(maps.root, 2, 3, 2)
  put(maps.root, 2, 1, 2)
  for west, east in [(170, 190), (170, -170), (-190, -170)]:
    assert sorted(maps.coverage(2, west, -20, east, -1)['tiles']) == [[0, 2, True], [3, 2, True]]
  TileCache(maps.root, DEFAULT_STYLE).path(TileKey(2, 0, 2)).unlink()
  assert maps.coverage(2, 170, -20, 190, -1)['tiles'] == [[3, 2, True]]


def test_auto_saved_tiles_share_pinned_coverage_and_track_pending_promotion(tmp_path):
  maps = OfflineMaps(tmp_path)
  key = TileKey(2, 1, 1)
  assert maps.mark_auto_saved(key)
  assert maps.pending_auto_saved() == [key]
  put(maps.root, 2, 1, 1)
  assert maps.coverage(2, -180, -85, 180, 85)['tiles'] == [[1, 1, True]]
  maps.finish_auto_saved(key)
  assert maps.pending_auto_saved() == [] and maps.is_auto_saved(key)


@pytest.mark.parametrize('zoom,bounds', [(19, (-180, -85, 180, 85)), (2, (0, 20, 10, -20)), (2, (float('nan'), 0, 10, 20))])
def test_coverage_rejects_invalid_bounds(tmp_path, zoom, bounds):
  with pytest.raises(ValueError):
    OfflineMaps(tmp_path).coverage(zoom, *bounds)
