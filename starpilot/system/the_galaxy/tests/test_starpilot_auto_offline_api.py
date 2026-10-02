from pathlib import Path

import test_navigation_params as nav
from openpilot.starpilot.navigation.offline_maps import OfflineMaps

JS_ROOT = Path(__file__).resolve().parent.parent / "assets" / "mobile" / "js"
ROUTE = [[36.10 + i * 0.001, -115.20] for i in range(30)]


def _client(monkeypatch, tmp_path, position=(36.1, -115.2)):
  monkeypatch.setattr(nav.the_galaxy, "OfflineMaps", lambda: OfflineMaps(tmp_path))
  monkeypatch.setattr(nav.the_galaxy, "_get_navigation_last_position",
                      lambda: {"latitude": position[0], "longitude": position[1]} if position else None)
  client, fake_params = nav._params_client(monkeypatch, {"MapboxPublicKey": "pk.test", "IsMetric": False}, "mici")
  return client, OfflineMaps(tmp_path)


def test_summary_reports_position_key_radius_and_a_stopped_service(monkeypatch, tmp_path):
  client, _ = _client(monkeypatch, tmp_path)
  response = client.get("/api/starpilot_auto/offline")
  assert response.status_code == 200 and response.headers["Cache-Control"].startswith("no-store")
  payload = response.get_json()
  assert payload["items"] == [] and payload["mapboxPublic"] == "pk.test" and payload["isMetric"] is False
  assert payload["position"] == {"latitude": 36.1, "longitude": -115.2}
  assert payload["areaRadius"] == {"min_km": 1.0, "max_km": 150.0, "default_km": 10.0}
  assert payload["save_viewed_cache"] is False
  assert payload["service_running"] is False, "no status file means navtilesd hasn't run"


def test_area_estimate_then_save(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  area_estimate = client.post("/api/starpilot_auto/offline/estimate", json={"latitude": 36.1, "longitude": -115.2, "radius_km": 18}).get_json()["area"]
  assert area_estimate["radius_km"] == 18 and area_estimate["max_zoom"] == 15
  assert area_estimate["tiles"] > 0 and area_estimate["bytes"] > 0 and area_estimate["fits"]

  response = client.post("/api/starpilot_auto/offline/areas", json={"name": "Home", "latitude": 36.1, "longitude": -115.2, "radius_km": 18})
  assert response.status_code == 201
  [area] = maps.areas()
  assert (area.name, area.kind, area.radius_km, area.max_zoom) == ("Home", "area", 18.0, 15)
  item = client.get("/api/starpilot_auto/offline").get_json()["items"][0]
  assert item["state"] == "queued" and item["id"] == area.id


def test_area_zoom_can_be_chosen(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  assert client.get("/api/starpilot_auto/offline").get_json()["areaZooms"] == [14, 15, 16]
  auto = client.post("/api/starpilot_auto/offline/estimate", json={"latitude": 36.1, "longitude": -115.2, "radius_km": 5, "max_zoom": None}).get_json()["area"]
  chosen = client.post("/api/starpilot_auto/offline/estimate", json={"latitude": 36.1, "longitude": -115.2, "radius_km": 5, "max_zoom": 14}).get_json()["area"]
  assert (auto["max_zoom"], chosen["max_zoom"], chosen["detail"]) == (16, 14, "Road detail")
  assert chosen["tiles"] < auto["tiles"]

  assert client.post("/api/starpilot_auto/offline/areas", json={"latitude": 36.1, "longitude": -115.2, "radius_km": 40, "max_zoom": 16}).status_code == 201
  [area] = maps.areas()
  assert (area.radius_km, area.max_zoom) == (40.0, 16)
  for bad in (13, 17, "street"):
    assert client.post("/api/starpilot_auto/offline/estimate", json={"latitude": 36.1, "longitude": -115.2, "radius_km": 5, "max_zoom": bad}).status_code == 400


def test_area_rejects_out_of_range_sizes_and_bad_points(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  assert client.post("/api/starpilot_auto/offline/areas", json={"latitude": 36.1, "longitude": -115.2, "radius_km": 500, "max_zoom": 18}).status_code == 400
  assert client.post("/api/starpilot_auto/offline/areas", json={"latitude": 95, "longitude": 0, "radius_km": 10, "max_zoom": 16}).status_code == 400
  assert client.post("/api/starpilot_auto/offline/estimate", json={}).status_code == 400
  assert maps.areas() == []


def test_viewed_cache_setting_persists(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  assert client.post("/api/starpilot_auto/offline/settings", json={"save_viewed_cache": "yes"}).status_code == 400
  response = client.post("/api/starpilot_auto/offline/settings", json={"save_viewed_cache": True})
  assert response.status_code == 200 and response.get_json()["save_viewed_cache"] is True
  assert maps.save_viewed_cache() is True
  assert maps.promote_requested(), "enabling asks navtilesd to pin tiles already cached"
  assert client.get("/api/starpilot_auto/offline").get_json()["save_viewed_cache"] is True

  assert client.post("/api/starpilot_auto/offline/settings", json={"save_viewed_cache": False}).status_code == 200
  assert maps.save_viewed_cache() is False
  assert not maps.promote_requested(), "disabling withdraws the request"



def test_route_estimate_then_make_available_offline(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  estimate = client.post("/api/starpilot_auto/offline/estimate", json={"points": ROUTE}).get_json()
  assert estimate["tiles"] > 0 and estimate["fits"]

  body = {"name": "Bellagio", "origin_name": "Home", "points": ROUTE, "distance_m": 3300, "duration_s": 420}
  assert client.post("/api/starpilot_auto/offline/routes", json=body).status_code == 201
  [route] = maps.areas()
  assert route.kind == "route" and route.name == "Bellagio" and route.origin_name == "Home"
  assert len(route.tiles()) == estimate["tiles"]
  item = client.get("/api/starpilot_auto/offline").get_json()["items"][0]
  assert item["kind"] == "route" and item["distance_m"] == 3300 and len(item["points"]) == len(ROUTE)


def test_route_rejects_garbage(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  assert client.post("/api/starpilot_auto/offline/routes", json={"points": [[36.1, -115.2]]}).status_code == 400
  assert client.post("/api/starpilot_auto/offline/routes", json={"points": [["x", 1], [2, 3]]}).status_code == 400
  assert client.post("/api/starpilot_auto/offline/estimate", json={"points": "nope"}).status_code == 400
  assert maps.areas() == []


def test_saves_are_refused_when_offline_storage_is_full(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  monkeypatch.setattr(nav.the_galaxy, "OFFLINE_MAX_BYTES", 1)
  assert client.post("/api/starpilot_auto/offline/routes", json={"points": ROUTE}).status_code == 409
  assert client.post("/api/starpilot_auto/offline/areas", json={"latitude": 36.1, "longitude": -115.2, "radius_km": 10, "max_zoom": 16}).status_code == 409
  assert client.post("/api/starpilot_auto/offline/estimate", json={"points": ROUTE}).get_json()["fits"] is False
  assert maps.areas() == []


def test_update_download_now_and_delete(monkeypatch, tmp_path):
  client, maps = _client(monkeypatch, tmp_path)
  area = maps.add_area("Home", 36.1, -115.2, 10.0, 16)
  assert client.post(f"/api/starpilot_auto/offline/{area.id}/update").status_code == 200
  assert maps.get(area.id).update_requested > 0
  assert client.post(f"/api/starpilot_auto/offline/{area.id}/download_now").status_code == 200
  assert maps.get(area.id).allow_metered is True
  assert client.post(f"/api/starpilot_auto/offline/{area.id}/explode").status_code == 400

  assert client.delete(f"/api/starpilot_auto/offline/{area.id}").status_code == 200
  assert maps.get(area.id).deleted, "navtilesd removes the tiles, then the record"
  assert client.get("/api/starpilot_auto/offline").get_json()["items"][0]["state"] == "removing"
  assert client.delete("/api/starpilot_auto/offline/missing").status_code == 404
  assert client.post("/api/starpilot_auto/offline/missing/update").status_code == 404


def test_starpilot_auto_settings_moved_out_of_navigation():
  navigation = (JS_ROOT / "views" / "Navigation.js").read_text()
  vehicle = (JS_ROOT / "views" / "Vehicle.js").read_text()
  settings = (JS_ROOT / "views" / "Settings.js").read_text()
  assert 'auto: "Starpilot Auto"' not in navigation
  assert "StarpilotAutoOfflinePanel" in navigation and "StarpilotAutoIdentityPanel" not in navigation
  assert "StarpilotAutoIdentityPanel" in settings and "/navigation/auto" not in vehicle
  panel = (JS_ROOT / "components" / "StarpilotAutoOfflinePanel.js").read_text()
  assert "fetch(" not in panel, "network calls go through api.js"


def test_both_offline_downloaders_share_the_offline_maps_tab():
  navigation = (JS_ROOT / "views" / "Navigation.js").read_text()
  vehicle = (JS_ROOT / "views" / "Vehicle.js").read_text()
  assert 'maps: "Offline Maps"' in navigation and 'maps: "maps"' in navigation
  maps_tab = navigation.split("tab === 'maps'", 1)[1].split("</template>", 1)[0]
  assert "<StarpilotAutoOfflinePanel />" in maps_tab and "<MapsPanel />" in maps_tab
  assert "tab === 'auto'" not in navigation
  assert "/navigation/maps" in vehicle
  assert "StarpilotAutoOfflinePanel, GalaxySection" in navigation, "offline parent sections must render as Galaxy cards"
  assert 'title="Offline Maps for Starpilot Auto"' in maps_tab
  assert 'title="Speed Limit &amp; Curve Data"' in maps_tab


def test_offline_panel_dropdowns_are_galaxy_styled_and_list_only_drawn_zooms():
  panel = (JS_ROOT / "components" / "StarpilotAutoOfflinePanel.js").read_text()
  assert "<select" not in panel, "use GalaxySelect so the dropdowns match the rest of The Galaxy"
  assert panel.count("<GalaxySelect") == 3  # detail level, area zoom, map colors
  zooms = panel[panel.index("const COVERAGE_ZOOMS"):panel.index("]", panel.index("const COVERAGE_ZOOMS"))]
  assert [label for label in ("Regional", "Road", "City", "Street") if label in zooms] == ["Regional", "Road", "City", "Street"]
  assert "zoom in 19" not in panel


def _save_area_section(panel):
  return panel[panel.index("Save an Area"):panel.index("Save a Specific Route")]


def test_show_downloaded_tiles_toggle_does_not_move_the_layout():
  section = _save_area_section((JS_ROOT / "components" / "StarpilotAutoOfflinePanel.js").read_text())
  row = section[section.index('v-model="coverageEnabled"') - 200:section.index("Downloaded tile detail level")]
  assert row.index('v-model="coverageEnabled"') < row.index("Tile detail"), "the checkbox leads the row"
  assert 'v-if="coverageEnabled" class=' not in section and '<div v-if="coverageEnabled"' not in section


def test_area_picker_keeps_the_map_in_place():
  section = _save_area_section((JS_ROOT / "components" / "StarpilotAutoOfflinePanel.js").read_text())
  assert section.index("Pick on Map") < section.index('ref="map"') < section.index("Most detailed zoom"), \
    "the map sits right under the place buttons, above the area options"
  assert 'v-if="areaPoint"' not in section, "choosing a centre changes values, it doesn't insert controls"
  assert "Tap the map where the area should be centred." in section and "position:absolute" in section


def test_map_colors_setting(monkeypatch, tmp_path):
  from openpilot.starpilot.navigation.map_tiles import DARK_STYLE
  client, maps = _client(monkeypatch, tmp_path)
  summary = client.get("/api/starpilot_auto/offline").get_json()
  assert summary["map_theme"] == "auto" and summary["usage"]["tiles"] == 0 and summary["usage"]["free_tiles"] == 200_000
  assert client.post("/api/starpilot_auto/offline/settings", json={"map_theme": "traffic"}).status_code == 400
  assert client.post("/api/starpilot_auto/offline/settings", json={}).status_code == 400
  response = client.post("/api/starpilot_auto/offline/settings", json={"map_theme": "light"})
  assert response.status_code == 200 and response.get_json() == {"save_viewed_cache": False, "map_theme": "light"}
  assert maps.map_theme() == "light" and DARK_STYLE in maps.active_styles(), "the dark map stays downloaded"
