"""Covers assets/mobile/js/components/auto_offline_helpers.js through node."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HELPERS_PATH = Path(__file__).resolve().parent.parent / "assets" / "mobile" / "js" / "components" / "auto_offline_helpers.js"
MIN_NODE_MAJOR = 23

HARNESS = f'''
import * as helpers from {json.dumps(HELPERS_PATH.as_uri())}
const run = new Function(...Object.keys(helpers), process.env.AUTO_OFFLINE_SNIPPET)
process.stdout.write(JSON.stringify(run(...Object.values(helpers)) ?? null))
'''


def evaluate(snippet):
  node = shutil.which("node")
  if node is None:
    pytest.skip("node is not installed")
  version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
  if int(version.lstrip("v").split(".")[0]) < MIN_NODE_MAJOR:
    pytest.skip(f"node {version} cannot import a bare .js ES module; need v{MIN_NODE_MAJOR}+")
  result = subprocess.run([node, "--input-type=module"], input=HARNESS, env={**os.environ, "AUTO_OFFLINE_SNIPPET": snippet, "TZ": "UTC"},
                          capture_output=True, text=True, timeout=60)
  assert result.returncode == 0, result.stderr
  return json.loads(result.stdout)


def test_formatting():
  assert evaluate('''return [formatBytes(0), formatBytes(9 * 1024 * 1024), formatBytes(2 * 1024 ** 3),
    formatDistance(35405, false), formatDistance(3300, false), formatDistance(3300, true),
    formatDuration(1860), formatDuration(4500), radiusLabel(30, false), radiusLabel(30, true)]''') == [
    "0 KB", "9 MB", "2.0 GB", "22 mi", "2.1 mi", "3.3 km", "31 min", "1 h 15 min", "19 mi", "30 km"]


def test_preset_detail_description():
  assert evaluate('''return [
    presetDetailDescription({radius_km: 10, max_zoom: 16}, false),
    presetDetailDescription({radius_km: 30, max_zoom: 15}, false),
    presetDetailDescription({radius_km: 60, max_zoom: 14}, true),
    presetDetailDescription({radius_km: 150, max_zoom: 13}, false),
  ]''') == [
    "Full street-level detail: local roads, street names, alleys and turns within a 6 mi radius.",
    "City & metro detail: city streets, avenues and neighborhood connectors within a 19 mi radius.",
    "Road network: major thoroughfares, state routes and county highways within a 60 km radius.",
    "Regional highways: interstates, freeways and major transit corridors within a 93 mi radius.",
  ]


def test_item_status_wording_and_actions():
  result = evaluate('''const now = 1000000
  return {
    complete: itemStatus({state: "complete", bytes: 121000000, completed_at: now - 3 * 86400}, now),
    downloading: itemStatus({state: "downloading", done: 420, total: 1928}, now),
    metered: itemStatus({state: "waiting_wifi", metered_wifi: true, done: 0, total: 1928}, now),
    allowed: itemStatus({state: "waiting_wifi", allow_metered: true, done: 10, total: 100}, now),
    queued: itemStatus({}, now),
    removing: itemStatus({state: "removing"}, now),
    full: itemStatus({state: "storage_full"}, now),
  }''')
  assert result["complete"]["text"] == "Saved · 115 MB · updated 3 days ago" and result["complete"]["canUpdate"]
  assert result["downloading"]["text"] == "Downloading 21% · 420 of 1,928 tiles" and abs(result["downloading"]["progress"] - 420 / 1928) < 1e-9
  assert not result["downloading"]["canUpdate"]
  assert "marked metered" in result["metered"]["text"] and result["metered"]["canDownloadNow"]
  assert not result["allowed"]["canDownloadNow"], "already allowed on metered"
  assert result["queued"]["text"] == "Queued · downloads on Wi-Fi"
  assert not result["removing"]["canDelete"]
  assert result["full"]["tone"] == "danger"


def test_service_notice():
  notices = evaluate("""return [serviceNotice(null), serviceNotice({service_running: false}).tone,
    serviceNotice({service_running: true, offline: true}).tone, serviceNotice({service_running: true})]""")
  assert notices == [None, "warn", "warn", None]


def test_circle_polygon_is_closed_and_has_the_right_radius():
  ring = evaluate("return circlePolygon(36.1, -115.2, 10, 32)")
  assert len(ring) == 33 and ring[0] == ring[-1]
  # 10 km north of 36.1°N is ~0.0904° of latitude.
  north = max(point[1] for point in ring)
  assert abs((north - 36.1) - 10 / 110.574) < 1e-4


def test_directions_become_lat_lon_routes():
  routes = evaluate('''return directionsToRoutes({routes: [
    {distance: 1000, duration: 120, geometry: {coordinates: [[-115.2, 36.1], [-115.19, 36.11]]}},
    {distance: 1200, duration: 150, geometry: {coordinates: [[-115.2, 36.1], [-115.18, 36.12], [-115.19, 36.11]]}},
    {distance: 5, duration: 1, geometry: {coordinates: [[-115.2, 36.1]]}},
  ]})''')
  assert [route["id"] for route in routes] == ["main", "alt-1"]
  assert routes[0]["points"] == [[36.1, -115.2], [36.11, -115.19]]
  assert routes[1]["label"] == "Alternative 1" and routes[1]["duration_s"] == 150


def test_saved_items_become_map_features_and_bounds():
  result = evaluate('''const items = [
    {id: "a", kind: "area", name: "Home", latitude: 36.1, longitude: -115.2, radius_km: 10},
    {id: "r", kind: "route", name: "Trip", points: [[36.1, -115.2], [36.2, -115.1]]},
    {id: "x", kind: "area", name: "Gone", latitude: 1, longitude: 1, radius_km: 5, state: "removing"},
  ]
  const geo = itemsToGeoJson(items)
  return {areas: geo.areas.features.map(f => f.properties.id), routes: geo.routes.features.map(f => [f.properties.id, f.geometry.coordinates]),
          routeBounds: itemBounds(items[1]), areaBounds: itemBounds(items[0])}''')
  assert result["areas"] == ["a"]
  assert result["routes"] == [["r", [[-115.2, 36.1], [-115.1, 36.2]]]]
  assert result["routeBounds"] == [-115.2, 36.1, -115.1, 36.2]
  west, south, east, north = result["areaBounds"]
  assert west < -115.2 < east and south < 36.1 < north


def test_downloaded_tile_footprints_show_exact_zoom_and_storage_kind():
  result = evaluate('return coverageToGeoJson({zoom: 1, tiles: [[1, 1, true], [0, 0, false]]})')
  saved, cached = result['features']
  assert saved['properties'] == {'saved': True, 'zoom': 1}
  assert cached['properties']['saved'] is False
  ring = saved['geometry']['coordinates'][0]
  assert ring[0] == ring[-1] == [0, 0]
  assert ring[1] == [180, 0]
  assert abs(ring[2][1] + 85.05112878) < 1e-6
