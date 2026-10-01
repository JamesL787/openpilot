import json
from pathlib import Path

import test_navigation_params as nav
from openpilot.starpilot.system.starpilot_auto import car_screen

JS_ROOT = Path(__file__).resolve().parent.parent / "assets" / "mobile" / "js"


def _client(monkeypatch, tmp_path):
  path = tmp_path / "car_screen.json"
  monkeypatch.setattr(car_screen, "CAR_SCREEN_PATH", path)
  client, _ = nav._params_client(monkeypatch, {"IsOffroad": True, "StarpilotAutoEnabled": True}, "mici")
  return client, path


def test_defaults_then_partial_updates_are_saved_for_car_ui(monkeypatch, tmp_path):
  client, path = _client(monkeypatch, tmp_path)
  response = client.get("/api/starpilot_auto/car_screen")
  assert response.status_code == 200 and response.headers["Cache-Control"].startswith("no-store")
  assert response.get_json()["settings"] == car_screen.DEFAULTS
  assert {metric["value"] for metric in response.get_json()["status_metrics"]} == set(car_screen.STATUS_METRICS)

  assert client.post("/api/starpilot_auto/car_screen", json={"map_side": "left"}).get_json()["settings"]["map_side"] == "left"
  assert client.post("/api/starpilot_auto/car_screen", json={"map_orientation": "heading_up"}).get_json()["settings"]["map_orientation"] == "heading_up"
  blind_spot = client.post("/api/starpilot_auto/car_screen", json={"blind_spot_monitors": False, "blind_spot_min_speed_ms": 8.0}).get_json()["settings"]
  assert not blind_spot["blind_spot_monitors"] and blind_spot["blind_spot_min_speed_ms"] == 8.0
  saved = client.post("/api/starpilot_auto/car_screen", json={"camera": False}).get_json()["settings"]
  assert saved == {**car_screen.DEFAULTS, "map_side": "left", "map_orientation": "heading_up", "camera": False,
                   "blind_spot_monitors": False, "blind_spot_min_speed_ms": 8.0}, "earlier changes are kept"
  assert json.loads(path.read_text()) == saved
  assert car_screen.load(path) == saved
  awake = client.post("/api/starpilot_auto/car_screen", json={"sleep_device_screen": False}).get_json()["settings"]
  assert awake == {**saved, "sleep_device_screen": False, "sleep_device_screen_set": True}, \
    "sleeping is the default here; staying on is the choice, and it is marked as chosen"
  assert car_screen.load(path) == awake
  placed = client.post("/api/starpilot_auto/car_screen", json={
    "sleep_wake_events": ["StandbyWakeTurnSignal"], "show_current_speed": False,
    "status_position_split": "center", "status_position_driving": "left", "status_position_map": "left"}).get_json()["settings"]
  assert placed == {**awake, "sleep_wake_events": ["StandbyWakeTurnSignal"], "show_current_speed": False,
                    "status_position_split": "center", "status_position_driving": "left", "status_position_map": "left"}
  slots = ["cpu", "cpu", "memory", "temperature", "friction", "steer_delay", "blank"]
  assert client.post("/api/starpilot_auto/car_screen", json={"status_slots": slots}).get_json()["settings"]["status_slots"] == slots


def test_invalid_values_are_rejected_without_saving(monkeypatch, tmp_path):
  client, path = _client(monkeypatch, tmp_path)
  assert client.post("/api/starpilot_auto/car_screen", json={"onroad_view": "sideways"}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"map_orientation": "sideways"}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"camera": "off"}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"blind_spot_monitors": "off"}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"blind_spot_min_speed_ms": -1}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"sleep_device_screen": "true"}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"sleep_wake_events": ["StandbyWakeCriticalAlert"]}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"show_current_speed": "no"}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"status_position_driving": "center"}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"status_slots": ["cpu"] * 5}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"status_slots": ["cpu"] * 5 + ["unknown"]}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"status_slots": ["cpu"] * 6}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", json={"status_slots": ["cpu"] * 6 + ["unknown"]}).status_code == 400
  assert client.post("/api/starpilot_auto/car_screen", data="nope", content_type="application/json").status_code == 400
  assert not path.exists()


def test_car_screen_settings_have_a_dedicated_starpilot_auto_section():
  settings = (JS_ROOT / "views" / "Settings.js").read_text()
  panel = (JS_ROOT / "components" / "StarpilotAutoCarScreenPanel.js").read_text()
  assert "StarpilotAutoCarScreenPanel" in settings and "activeSection.name === 'Starpilot Auto' && values.StarpilotAutoEnabled" in settings
  assert 'title="Layout"' in settings and 'section="layout"' in settings
  assert 'title="Status Widgets"' in settings and 'section="widgets"' in settings
  assert 'title="Car Display"' not in settings
  assert 'title="Starpilot Auto"' in settings and 'p.key === "StarpilotAutoEnabled"' in settings
  assert 'v-else-if="error"' in panel and "attempt < 3" in panel and "@click=\"load\"" in panel
  for value in ('"split"', '"driving"', '"map"', "map_side", "map_orientation", "north_up", "heading_up", "camera",
                "blind_spot_monitors", "blind_spot_min_speed_ms", "status_slots"):
    assert value in panel
  assert panel.count("<GalaxySelect") == 1 and "v-for=\"(metric, index) in settings.status_slots\"" in panel
  assert "fetch(" not in panel


def test_disabled_blocks_layout_and_identity_but_not_live_ui(monkeypatch):
  client, _ = nav._params_client(monkeypatch, {"IsOffroad": True, "StarpilotAutoEnabled": False}, "mici")
  for path in ("car_screen", "identity", "identity/download", "identity/upload"):
    assert client.post("/api/starpilot_auto/" + path, json={}).status_code == 403
  assert client.get("/api/starpilot_auto/identity").status_code == 403
  assert client.get("/api/starpilot_auto/car_screen").status_code == 403
  monkeypatch.setattr(nav.the_galaxy.utilities, "get_ui_stream_port", lambda: 8091)
  memory = nav.WritableFakeParams()
  monkeypatch.setattr(nav.the_galaxy, "params_memory", memory)
  response = client.post("/api/ui_stream/start")
  assert response.status_code == 200
  assert memory.values["UiStreamRequested"] is True
