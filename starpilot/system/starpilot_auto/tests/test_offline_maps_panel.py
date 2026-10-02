import json
import time

import pytest

from openpilot.starpilot.system.starpilot_auto.ui import offline_maps as page_module
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.navigation import SearchResult
from openpilot.starpilot.navigation.offline_maps import OfflineMaps


class FakeParams:
  def __init__(self, values=None):
    self.values = dict(values or {})

  def get(self, key, encoding=None, default=None, **kwargs):
    return self.values.get(key, default)

  def put(self, key, value):
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


class FakeSearchClient:
  def __init__(self):
    self.results = []

  def reverse(self, latitude, longitude, public_token, language=""):
    return "Las Vegas"

  def search(self, query, public_token, session_token, **kwargs):
    return self.results


GPS = json.dumps({"latitude": 36.1, "longitude": -115.2, "hasFix": True})
DESTINATION = json.dumps({"name": "Office", "place_name": "Office", "latitude": 36.2, "longitude": -115.1})


@pytest.fixture
def page(tmp_path):
  params = FakeParams({"MapboxPublicKey": "pk"})
  layout = page_module.StarPilotOfflineMapsLayout(offline=OfflineMaps(tmp_path), params=params)
  layout._search_client = FakeSearchClient()
  layout.params = params
  layout.refresh()
  return layout


def wait_for(layout, condition, timeout=5.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    layout._consume_pending()
    if condition():
      return
    time.sleep(0.01)
  raise AssertionError("timed out")


def kinds(layout):
  return [kind for kind, _, _ in layout.layout_rows()]


def test_empty_page_leads_with_storage_and_adding(page):
  assert kinds(page) == ["storage", "theme", "add_header", "add_buttons", "saved_header", "empty"]
  assert [target for target, _ in page.add_buttons()] == ["add:here", "add:search"]
  text, _ = page.connection_text()
  assert "not running" in text


def test_around_me_needs_gps(page):
  page.activate("add:here")
  assert "GPS" in page.message and "message" in kinds(page)


def test_save_an_area_around_me(page):
  page.params.values["LastGPSPosition"] = GPS
  page.activate("add:here")
  assert page.chooser["radius_km"] > 0 and page.chooser["zoom"] is None
  wait_for(page, lambda: page.chooser["estimate"] is not None and page.chooser["name"] == "Las Vegas")
  assert page.estimate_text()[1]
  page.activate("area_save")
  assert page.chooser is None
  area = page.areas[0]
  assert area.name == "Las Vegas" and area.max_zoom == page_module.area_zoom_for_radius(area.radius_km)


def test_area_editor_moves_the_pin_and_sets_radius_and_detail(page, monkeypatch):
  monkeypatch.setattr(page_module.ui_state, "is_metric", True, raising=False)
  page.open_chooser(36.1, -115.2, "Here")
  page.step_radius(1)
  assert page.chooser["radius_km"] == 15.0
  page.activate("area_radius:-1")
  page.activate("area_radius:-1")
  assert page.chooser["radius_km"] == 5.0
  page.activate("area_level:14")
  assert page.area_zoom() == 14
  page.move_pin(36.2, -115.3)
  assert (page.chooser["latitude"], page.chooser["radius_km"], page.chooser["zoom"]) == (36.2, 5.0, 14)
  wait_for(page, lambda: page.chooser["estimate"] is not None)
  page.activate("area_level:auto")
  assert page.chooser["estimate"] is None and page.area_zoom() == 16
  wait_for(page, lambda: page.chooser["estimate"] is not None)
  page.activate("area_save")
  assert (page.areas[0].radius_km, page.areas[0].max_zoom) == (5.0, 16)


def test_map_taps_convert_back_to_the_same_place():
  from openpilot.starpilot.navigation.map_tiles import world_xy
  from openpilot.starpilot.system.starpilot_auto.ui.offline_area_editor import lat_lon, radius_label, radius_steps
  latitude, longitude = lat_lon(*world_xy(36.1, -115.2))
  assert abs(latitude - 36.1) < 1e-9 and abs(longitude + 115.2) < 1e-9
  assert radius_label(radius_steps(False)[3], False) == "5 mi" and radius_label(10.0, True) == "10 km"


def test_area_map_draws_with_the_base_maps_arguments(monkeypatch):
  # NavMapView._render passes `now` to _draw_world; the editor's override must accept it ("Around me" crashed without it).
  from openpilot.starpilot.system.starpilot_auto.ui import offline_area_editor as editor
  from openpilot.starpilot.system.starpilot_auto.ui.nav_map import Camera, NavMapView
  calls = []
  monkeypatch.setattr(NavMapView, "_draw_world", lambda self, *args: calls.append(args))
  monkeypatch.setattr(editor.rl, "draw_circle_v", lambda *args: None)
  monkeypatch.setattr(editor.rl, "draw_ring", lambda *args: None)
  view = object.__new__(editor.AreaMapView)
  view._preview_destination, view.radius_km = (36.1, -115.2), 10.0
  view._draw_destination = lambda *args: calls.append("pin")
  view._draw_world(editor.rl.Rectangle(0, 0, 400, 300), Camera(), (200.0, 150.0), 1.0, 12.5)
  assert calls[0][-1] == 12.5 and calls[-1] == "pin"


def test_destination_button_and_current_route(page):
  page.params.values["NavDestination"] = DESTINATION
  assert [target for target, _ in page.add_buttons()] == ["add:here", "add:destination", "add:search"]
  assert "route" in kinds(page)
  page.activate("add:destination")
  assert page.chooser["name"] == "Office"


def test_search_a_place_then_choose_its_size(page):
  page._search_client.results = [SearchResult("Reno", "Nevada", 39.5, -119.8)]
  page._search("reno")
  wait_for(page, lambda: page.search_results)
  assert "result" in kinds(page)
  page.activate("result:0")
  assert page.chooser["name"] == "Reno" and page.search_results == []


def test_manage_a_saved_area(page, monkeypatch):
  area = page._offline.add_area("Home area", 36.1, -115.2, 10, 16)
  page.refresh()
  page.activate(f"area:{area.id}")
  assert "area_actions" in kinds(page)
  page.activate("area_action:update")
  assert page._offline.get(area.id).update_requested > 0
  page.activate(f"area:{area.id}")
  assert page.selected_area_id is None, "tapping again closes it"

  page.activate(f"area:{area.id}")
  dialogs = []
  monkeypatch.setattr(page_module, "ConfirmDialog", lambda text, label, callback: dialogs.append(callback) or text)
  monkeypatch.setattr(page_module.gui_app, "push_widget", lambda widget: None)
  page.activate("area_action:delete")
  dialogs[0](page_module.DialogResult.CONFIRM)
  assert page._offline.get(area.id).deleted and page.selected_area_id is None


class FakeRoadData:
  def __init__(self):
    self.events = []

  def show_event(self):
    self.events.append("show")

  def hide_event(self):
    self.events.append("hide")


def test_speed_limit_data_is_a_segment_of_the_same_page(tmp_path):
  built = []
  layout = page_module.StarPilotOfflineMapsLayout(offline=OfflineMaps(tmp_path), params=FakeParams({"MapboxPublicKey": "pk"}),
                                                  road_data_factory=lambda: built.append(FakeRoadData()) or built[-1])
  layout.show_event()
  assert layout.segment == page_module.SEGMENT_DISPLAY and built == [], "mapd's page is only built when opened"

  layout.open_segment(page_module.SEGMENT_ROAD_DATA)
  road = built[0]
  assert road.events == ["show"]

  layout.hide_event()
  layout.show_event()
  assert layout.segment == page_module.SEGMENT_ROAD_DATA, "a dialog closing doesn't bounce back to the map display"
  assert road.events == ["show", "hide", "show"]

  layout.open_segment(page_module.SEGMENT_DISPLAY)
  assert road.events[-1] == "hide" and len(built) == 1


def test_map_colors_switch_without_asking_about_deletes(page, monkeypatch):
  from openpilot.starpilot.navigation.map_tiles import DARK_STYLE, LIGHT_STYLE
  from openpilot.system.ui.widgets import DialogResult
  pushed = []
  monkeypatch.setattr(page_module.gui_app, "push_widget", pushed.append)
  monkeypatch.setattr(page_module, "MultiOptionDialog", lambda title, options, current, callback=None:
                      type("Picker", (), {"options": options, "selection": current, "callback": staticmethod(callback)})())

  def choose(label, result=DialogResult.CONFIRM):
    page.activate("theme")
    picker = pushed[-1]
    picker.selection = label
    picker.callback(result)

  choose("Light & dark (automatic)")
  assert page._offline.map_theme() == "auto" and "sunset" in page.theme_text()
  choose("Light")
  assert page._offline.map_theme() == "light" and len(pushed) == 2, "only the picker: nothing to delete"
  assert page._offline.active_styles() == (LIGHT_STYLE, DARK_STYLE)
  choose("Dark", DialogResult.CANCEL)
  assert page._offline.map_theme() == "light", "cancelling the picker changes nothing"


def test_storage_card_shows_this_months_mapbox_usage(page):
  page.summary = {**page.summary, "usage": {"tiles": 12345, "free_tiles": 200000, "directions": 3}}
  assert page.usage_text() == "Mapbox this month: 12,345 of 200,000 free tile requests • 3 route lookups"
