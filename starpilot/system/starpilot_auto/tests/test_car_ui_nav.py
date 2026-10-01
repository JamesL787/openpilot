import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from openpilot.starpilot.system.starpilot_auto import car_screen, car_ui
from openpilot.starpilot.system.starpilot_auto.touch import TouchEvent


# ── car_screen.json ───────────────────────────────────────────────────────────

def test_settings_default_validate_and_round_trip(tmp_path):
  path = tmp_path / "car_screen.json"
  assert car_screen.load(path) == car_screen.DEFAULTS
  saved = car_screen.save({"onroad_view": "map", "map_side": "left", "camera": False,
                           "blind_spot_monitors": False, "blind_spot_min_speed_ms": 8.0, "bogus": 1}, path)
  assert saved == {**car_screen.DEFAULTS, "onroad_view": "map", "map_side": "left", "camera": False,
                   "blind_spot_monitors": False, "blind_spot_min_speed_ms": 8.0}
  assert car_screen.load(path) == saved
  assert car_screen.normalize({"onroad_view": "sideways", "camera": "yes", "blind_spot_monitors": "yes",
                               "blind_spot_min_speed_ms": -1, "map_orientation": "sideways"}) == car_screen.DEFAULTS
  path.write_text("{not json")
  assert car_screen.load(path) == car_screen.DEFAULTS


def test_default_status_slots_are_not_shared_between_settings(tmp_path):
  first = car_screen.load(tmp_path / "missing.json")
  first["status_slots"][0] = "cpu"
  assert car_screen.load(tmp_path / "missing.json")["status_slots"] == car_screen.DEFAULTS["status_slots"]
  assert car_screen.DEFAULTS["status_slots"][0] == "steer_delay"


def test_device_screen_sleep_is_on_by_default_and_strictly_boolean(tmp_path):
  assert car_screen.DEFAULTS["sleep_device_screen"]
  path = tmp_path / "car_screen.json"
  assert not car_screen.save({"sleep_device_screen": False, "sleep_wake_events": []}, path)["sleep_device_screen"]
  assert not car_screen.load(path)["sleep_device_screen"], "a choice made with the wake settings is kept"
  for invalid in ("true", "false", 1, None):
    assert car_screen.normalize({"sleep_device_screen": invalid, "sleep_wake_events": []})["sleep_device_screen"]
  # Saved before sleeping became the default, the stored value was the old default.
  old = {**car_screen.DEFAULTS, "sleep_device_screen": False}
  del old["sleep_wake_events"]
  path.write_text(json.dumps(old))
  assert car_screen.load(path)["sleep_device_screen"]


def test_device_screen_sleep_is_offered_on_the_3x_but_off_by_default(monkeypatch, tmp_path):
  assert car_screen.device_sleep_default("mici") and car_screen.device_sleep_default("pc")
  assert not car_screen.device_sleep_default("tizi") and not car_screen.device_sleep_default("tici")
  from openpilot.selfdrive.ui import ui_state as ui_state_module
  assert {"mici", "tizi"} <= set(ui_state_module.STARPILOT_AUTO_SLEEP_DEVICES), "the display can sleep for Starpilot Auto on both"

  monkeypatch.setitem(car_screen.DEFAULTS, "sleep_device_screen", False)  # a 3X
  path = tmp_path / "car_screen.json"
  assert not car_screen.load(path)["sleep_device_screen"]
  # Every file saved before the 3X had a choice stored the old universal default (on); on a 3X that isn't a choice.
  path.write_text(json.dumps({"camera": False, "sleep_device_screen": True, "sleep_wake_events": []}))
  assert not car_screen.load(path)["sleep_device_screen"] and not car_screen.load(path)["camera"]
  chosen = car_screen.update({"sleep_device_screen": True}, path)
  assert chosen["sleep_device_screen"] and chosen["sleep_device_screen_set"]
  assert car_screen.load(path)["sleep_device_screen"], "turned on from settings, it stays on"
  assert not car_screen.update({"sleep_device_screen": False}, path)["sleep_device_screen"]


def test_wake_events_speed_and_status_positions_validate(tmp_path):
  assert car_screen.DEFAULTS["sleep_wake_events"] == ["StandbyWakeWarningAlert"]
  assert "StandbyWakeCriticalAlert" not in car_screen.SLEEP_WAKE_EVENTS, "critical alerts are not optional"
  path = tmp_path / "car_screen.json"
  saved = car_screen.update({"sleep_wake_events": ["StandbyWakeTurnSignal", "StandbyWakeEngage"], "show_current_speed": False,
                             "status_position_split": "center", "status_position_driving": "left",
                             "status_position_map": "left"}, path)
  assert saved["sleep_wake_events"] == ["StandbyWakeTurnSignal", "StandbyWakeEngage"]
  assert not saved["show_current_speed"]
  assert (saved["status_position_split"], saved["status_position_driving"], saved["status_position_map"]) == ("center", "left", "left")
  for bad in ({"sleep_wake_events": ["StandbyWakeCriticalAlert"]}, {"sleep_wake_events": ["StandbyWakeEngage"] * 2},
              {"sleep_wake_events": "StandbyWakeEngage"}, {"show_current_speed": "no"},
              {"status_position_driving": "center"}, {"status_position_map": "center"}, {"status_position_split": "top"}):
    with pytest.raises(ValueError):
      car_screen.update(bad, path)
  assert car_screen.load(tmp_path / "missing.json")["sleep_wake_events"] is not car_screen.DEFAULTS["sleep_wake_events"]


@pytest.mark.parametrize("map_side", ["right", "left"])
@pytest.mark.parametrize("position", ["left", "center", "right"])
def test_status_column_in_the_split_view(map_side, position):
  settings = {**car_screen.DEFAULTS, "map_side": map_side, "status_position_split": position}
  main, map_rect = car_ui.car_layout(settings, True, False, 1920, 1080)
  new_main, new_map, status = car_ui.status_layout(settings, main, map_rect)
  assert (new_map.width, status.width) == (map_rect.width, car_ui.STATUS_COLUMN_WIDTH)
  assert new_main.width == main.width - car_ui.STATUS_COLUMN_WIDTH
  order = [name for _, name in sorted(((new_main.x, "main"), (new_map.x, "map"), (status.x, "status")))]
  expected = ["main", "map"] if map_side == "right" else ["map", "main"]
  expected.insert({"left": 0, "center": 1, "right": 2}[position], "status")
  assert order == expected
  # Side by side, covering the screen exactly.
  rects = sorted((new_main, new_map, status), key=lambda rect: rect.x)
  assert rects[0].x == 0 and rects[-1].x + rects[-1].width == 1920
  assert all(a.x + a.width == b.x for a, b in zip(rects, rects[1:], strict=False))
  assert all(rect.y == 0 and rect.height == 1080 for rect in rects)


@pytest.mark.parametrize("view", ["driving", "map"])
@pytest.mark.parametrize("position", ["left", "right"])
def test_status_column_beside_a_single_view(view, position):
  settings = {**car_screen.DEFAULTS, "onroad_view": view, f"status_position_{view}": position}
  main, map_rect = car_ui.car_layout(settings, True, False, 1920, 1080)
  new_main, new_map, status = car_ui.status_layout(settings, main, map_rect)
  shown = new_main if view == "driving" else new_map
  assert (new_map if view == "driving" else new_main) is None
  assert shown.width == 1920 - car_ui.STATUS_COLUMN_WIDTH and status.width == car_ui.STATUS_COLUMN_WIDTH
  assert status.x == (0 if position == "left" else 1920 - car_ui.STATUS_COLUMN_WIDTH)
  assert shown.x == (car_ui.STATUS_COLUMN_WIDTH if position == "left" else 0)


def test_map_orientation_defaults_north_up_and_accepts_heading_up(tmp_path):
  assert car_screen.DEFAULTS["map_orientation"] == "north_up"
  path = tmp_path / "car_screen.json"
  assert car_screen.save({"map_orientation": "heading_up"}, path)["map_orientation"] == "heading_up"
  assert car_screen.load(path)["map_orientation"] == "heading_up"


def test_blind_spot_monitors_support_off_always_and_minimum_speed():
  assert car_screen.blind_spot_monitors_visible(car_screen.DEFAULTS, None)
  assert not car_screen.blind_spot_monitors_visible({**car_screen.DEFAULTS, "blind_spot_monitors": False}, 30.0)
  settings = {**car_screen.DEFAULTS, "blind_spot_min_speed_ms": 10.0}
  assert not car_screen.blind_spot_monitors_visible(settings, None)
  assert not car_screen.blind_spot_monitors_visible(settings, 9.99)
  assert car_screen.blind_spot_monitors_visible(settings, 10.0)


def test_settings_reload_live_when_the_file_changes(tmp_path):
  path = tmp_path / "car_screen.json"
  clock = [0.0]
  watcher = car_screen.CarScreenSettings(path, clock=lambda: clock[0])
  assert watcher.poll()["onroad_view"] == "split"
  car_screen.save({"onroad_view": "driving"}, path)
  assert watcher.poll()["onroad_view"] == "split", "checked at most once a second"
  clock[0] += car_screen.RELOAD_SECONDS
  assert watcher.poll()["onroad_view"] == "driving"
  path.unlink()
  clock[0] += car_screen.RELOAD_SECONDS
  assert watcher.poll() == car_screen.DEFAULTS


# ── layout ────────────────────────────────────────────────────────────────────

def rect_tuple(rect):
  return None if rect is None else (rect.x, rect.y, rect.width, rect.height)


def layout(settings, started=True, on_home=False, width=1920):
  main, map_rect = car_ui.car_layout({**car_screen.DEFAULTS, **settings}, started, on_home, width, 1080)
  return rect_tuple(main), rect_tuple(map_rect)


def test_split_puts_the_map_on_the_chosen_side():
  main, map_rect = layout({"onroad_view": "split", "map_side": "right"})
  assert main[0] == 0 and map_rect[0] == main[2] and main[2] + map_rect[2] == 1920 and 700 <= map_rect[2] <= 1100
  main, map_rect = layout({"onroad_view": "split", "map_side": "left"})
  assert map_rect[0] == 0 and main[0] == map_rect[2] and main[2] + map_rect[2] == 1920


def test_driving_only_and_map_only():
  assert layout({"onroad_view": "driving"}) == ((0, 0, 1920, 1080), None)
  assert layout({"onroad_view": "map"}) == (None, (0, 0, 1920, 1080))


def test_narrow_screens_offroad_and_the_home_screen_get_the_full_layout():
  assert layout({"onroad_view": "split"}, width=1600) == ((0, 0, 1600, 1080), None)
  assert layout({"onroad_view": "map"}, started=False) == ((0, 0, 1920, 1080), None)
  assert layout({"onroad_view": "map"}, on_home=True) == ((0, 0, 1920, 1080), None)


# ── onroad controls ───────────────────────────────────────────────────────────

class FakeParams:
  def __init__(self, values=None):
    self.values = dict(values or {})

  def get(self, key, encoding=None, **kwargs):
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.values.get(key))

  def put(self, key, value):
    self.values[key] = value

  def put_bool(self, key, value):
    self.values[key] = bool(value)

  def remove(self, key):
    self.values.pop(key, None)


@pytest.fixture
def controls():
  import json
  from openpilot.selfdrive.ui.layouts.main import MainState

  class FakeMainLayout:
    _current_mode = MainState.ONROAD
    critical = False

    def __init__(self):
      self._sidebar = SimpleNamespace(visible=False, set_visible=lambda v: setattr(self._sidebar, "visible", v))

    def _set_current_layout(self, mode):
      self._current_mode = mode

    def open_starpilot_panel(self, key):
      self.opened_panel = key
      self._current_mode = MainState.SETTINGS

    def _set_mode_for_state(self):
      self._current_mode = MainState.ONROAD
      self._sidebar.visible = False

    def _critical_full_alert_active(self):
      return self.critical

  favorites = [
    {"id": "w", "name": "Office", "latitude": 36.1, "longitude": -115.2, "is_work": True},
    {"id": "h", "name": "House", "latitude": 36.3, "longitude": -115.3, "is_home": True},
  ]
  params = FakeParams({"MapboxSecretKey": "sk", "FavoriteDestinations": json.dumps(favorites)})
  clock = [100.0]
  result = car_ui.OnroadControls(FakeMainLayout(), params=params, params_memory=FakeParams(), clock=lambda: clock[0],
                                 navigate_screen_factory=FakeNavigateScreen)
  result.clock = clock
  result.params = params
  return result


class FakeNavigateScreen:
  def __init__(self, on_started, on_close, on_offline_maps):
    self.on_started, self.on_close, self.on_offline_maps = on_started, on_close, on_offline_maps
    self.events = []

  def show_event(self):
    self.events.append("show")

  def hide_event(self):
    self.events.append("hide")


def touch_input():
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  return car_ui.TouchInput(MouseEvent, MousePos, 1920, 1080)


def screen():
  import pyray as rl
  return rl.Rectangle(0, 0, 1920, 1080)


def tap(x, y):
  return [TouchEvent("down", x / 1920, y / 1080), TouchEvent("up", x / 1920, y / 1080)]


def test_onroad_taps_on_the_drive_go_nowhere_but_the_button_opens_the_menu(controls):
  touches = touch_input()
  layout_events, menu_events = controls.route(tap(900, 500), touches, True, screen())
  assert layout_events == [] and menu_events == []

  button = controls.menu.button_rect(screen())
  layout_events, menu_events = controls.route(tap(button.x + 10, button.y + 10), touches, True, screen())
  assert layout_events == [] and [e.left_pressed for e in menu_events] == [True, False]

  controls.menu.open = True
  layout_events, menu_events = controls.route(tap(900, 500), touches, True, screen())
  assert layout_events == [] and len(menu_events) == 2, "an open menu takes every touch"


def test_offroad_and_home_screen_touches_reach_the_layout(controls):
  touches = touch_input()
  layout_events, menu_events = controls.route(tap(900, 500), touches, False, screen())
  assert len(layout_events) == 2 and menu_events == []
  controls.go_home()
  assert controls.on_home(True)
  layout_events, _ = controls.route(tap(900, 500), touches, True, screen())
  assert len(layout_events) == 2


def test_leaving_the_home_screen_cancels_a_held_touch(controls):
  touches = touch_input()
  controls.go_home()
  controls.route([TouchEvent("down", 0.5, 0.5)], touches, True, screen())
  controls.go_driving()
  layout_events, _ = controls.route([], touches, True, screen())
  assert [e.cancelled for e in layout_events] == [True]


def row_keys(controls):
  return [row.key for row in controls.menu.rows()]


def drive(controls):
  """Mid-drive on the drive layout (a drive itself starts on the home screen)."""
  controls.update(True, 0.0)
  controls.go_driving()


def test_menu_puts_navigate_first(controls):
  drive(controls)
  assert row_keys(controls) == ["navigate", "home", "offroad"]
  assert controls.menu.rows()[0].enabled


def test_navigate_opens_the_navigate_screen_and_takes_touches(controls):
  touches = touch_input()
  drive(controls)
  controls.menu.open = True
  controls.menu.activate("navigate")
  assert controls.nav_open and not controls.menu.open
  assert controls.navigate_screen.events == ["show"]
  assert controls.full_screen(True)
  button = controls.menu.button_rect(screen())
  layout_events, menu_events = controls.route(tap(button.x + 10, button.y + 10), touches, True, screen())
  assert len(layout_events) == 2 and menu_events == [], "the menu button is hidden under the Navigate screen"

  controls.navigate_screen.on_close()
  assert not controls.nav_open and controls.navigate_screen.events == ["show", "hide"]
  assert not controls.on_home(True)


def test_starting_a_route_returns_to_the_drive_even_from_the_home_screen(controls):
  controls.update(True, 0.0)
  controls.go_home()
  controls.open_navigate()
  controls.navigate_screen.on_close()
  assert controls.on_home(True), "Back returns to where the driver came from"
  controls.open_navigate()
  controls.navigate_screen.on_started()
  assert not controls.nav_open and not controls.on_home(True)


def test_home_screen_navigate_card_opens_the_same_screen():
  from openpilot.selfdrive.ui.layouts.main import MainState

  home = SimpleNamespace(nav_card=None)
  main_layout = SimpleNamespace(_layouts={MainState.HOME: home}, _current_mode=MainState.HOME)
  controls = car_ui.OnroadControls(main_layout, params=FakeParams({"MapboxSecretKey": "sk"}), params_memory=FakeParams(),
                                   navigate_screen_factory=FakeNavigateScreen)
  assert home.nav_card is controls.nav_card, "the Navigate card replaces Personal Records on the car"
  controls.update(False)
  controls.nav_card.activate("other")
  assert controls.nav_open and controls.full_screen(False)


MPH = 0.44704


@pytest.mark.parametrize("started, speed, allowed", [
  (False, None, True),      # offroad: always
  (True, 0.0, True),
  (True, 9.9 * MPH, True),
  (True, 10.0 * MPH, False),
  (True, -12.0 * MPH, False),  # reversing fast still counts
  (True, None, False),      # no wheel speed onroad: treat as moving
])
def test_speed_gate_uses_wheel_speed_below_10_mph(started, speed, allowed):
  from openpilot.starpilot.system.starpilot_auto.car_navigate import speed_allows_navigation
  assert speed_allows_navigation(started, speed) is allowed


def test_moving_locks_navigate_and_closes_the_screen(controls):
  controls.update(True, 5 * MPH)
  controls.open_navigate()
  assert controls.nav_open
  controls.update(True, 15 * MPH)
  assert not controls.nav_open and not controls.on_home(True)
  row = controls.menu.rows()[0]
  assert row.key == "navigate" and not row.enabled and "10 mph" in row.subtitle
  controls.open_navigate()
  assert not controls.nav_open, "can't be opened while moving"
  controls.update(True, 3 * MPH)
  assert controls.menu.rows()[0].enabled


def test_navigate_screen_closes_when_idle_or_on_a_critical_alert(controls):
  controls.update(True, 0.0)
  controls.open_navigate()
  controls.clock[0] += car_ui.HOME_ONROAD_TIMEOUT + 1
  controls.update(True, 0.0)
  assert not controls.nav_open
  controls.open_navigate()
  controls.main_layout.critical = True
  controls.update(True, 0.0)
  assert not controls.nav_open


def test_ending_a_route_works_at_any_speed(controls):
  controls.params.values["NavDestination"] = '{"name": "House", "place_name": "House", "latitude": 36.3, "longitude": -115.3}'
  controls.update(True, 40 * MPH)
  assert row_keys(controls) == ["navigate", "cancel", "home", "offroad"]
  assert "House" in controls.menu.destination_name
  controls.menu.activate("cancel")
  assert "NavDestination" not in controls.params.values


def test_menu_home_back_and_cancel(controls):
  controls.menu.activate("home")
  assert controls.on_home(True) and controls.main_layout._sidebar.visible
  controls.update(True)
  assert controls.menu.on_home
  assert row_keys(controls)[-2:] == ["driving", "offroad"]
  controls.menu.activate("driving")
  assert not controls.on_home(True)

  controls.params.values["NavDestination"] = '{"name": "House", "place_name": "House", "latitude": 36.3, "longitude": -115.3}'
  controls.clock[0] += car_ui.STATE_REFRESH
  controls.update(True)
  assert controls.menu.nav_active and "cancel" in row_keys(controls)
  controls.menu.activate("cancel")
  assert "NavDestination" not in controls.params.values


def test_go_offroad_needs_park_and_a_confirmation(controls, monkeypatch):
  from openpilot.starpilot.common import starpilot_variables
  updates = []
  monkeypatch.setattr(starpilot_variables, "update_starpilot_toggles", lambda: updates.append(True))

  controls.update(True, 0.0, parked=False)
  offroad = controls.menu.rows()[-1]
  assert offroad.key == "offroad" and not offroad.enabled
  controls.menu.activate("offroad")
  assert not controls.menu.confirming_offroad

  controls.update(True, 0.0, parked=True)
  controls.menu.activate("button")
  controls.menu.activate("offroad")
  assert row_keys(controls) == ["offroad_prompt", "offroad_confirm", "offroad_cancel"]
  controls.menu.activate("offroad_cancel")
  assert not controls.menu.confirming_offroad and controls.menu.open
  assert "ForceOffroad" not in controls.params.values

  controls.menu.activate("offroad")
  controls.update(True, 0.0, parked=False)
  assert not controls.menu.confirming_offroad, "shifting out of Park drops the confirmation"

  controls.update(True, 0.0, parked=True)
  controls.menu.activate("offroad")
  controls.menu.activate("offroad_confirm")
  assert controls.params.values["ForceOffroad"] is True and controls.params.values["ForceOnroad"] is False
  assert updates and not controls.menu.open and not controls.menu.confirming_offroad


def test_vehicle_parked_reads_the_gear():
  from cereal import car
  gear = car.CarState.GearShifter

  class SM(dict):
    def __init__(self, shifter, alive=True):
      super().__init__(carState=SimpleNamespace(gearShifter=shifter))
      self.recv_frame, self.alive, self.valid = {"carState": 1}, {"carState": alive}, {"carState": True}

  assert car_ui.vehicle_parked(SimpleNamespace(sm=SM(gear.park)), environ={})
  assert not car_ui.vehicle_parked(SimpleNamespace(sm=SM(gear.drive)), environ={})
  assert not car_ui.vehicle_parked(SimpleNamespace(sm=SM(gear.park, alive=False)), environ={})
  assert car_ui.vehicle_parked(SimpleNamespace(sm=SM(gear.drive)), environ={car_screen.DHU_ENV: "1"})


def test_home_screen_returns_to_the_drive_when_idle_or_on_a_critical_alert(controls):
  drive(controls)
  controls.go_home()
  controls.clock[0] += car_ui.HOME_ONROAD_TIMEOUT - 1
  controls.update(True)
  assert controls.on_home(True)
  controls.clock[0] += 2
  controls.update(True)
  assert not controls.on_home(True)

  controls.go_home()
  controls.main_layout.critical = True
  controls.update(True)
  assert not controls.on_home(True)


def test_a_drive_starts_on_the_home_screen_and_stays_while_slow(controls):
  controls.update(False, 0.0)
  controls.main_layout._prev_onroad = False
  controls.update(True, 0.0)
  assert controls.on_home(True) and controls.main_layout._prev_onroad
  assert controls.main_layout._sidebar.visible and controls.menu.corner == "right"
  controls.clock[0] += car_ui.HOME_ONROAD_TIMEOUT * 10
  controls.update(True, 5 * MPH)
  assert controls.on_home(True), "no idle timeout on the drive-start home screen below the Navigate lock"
  controls.update(True, 20 * MPH)
  assert not controls.on_home(True), "past the Navigate lock the drive layout takes over"


def test_drive_start_home_yields_to_a_critical_alert(controls):
  controls.update(True, 0.0)
  controls.main_layout.critical = True
  controls.update(True, 0.0)
  assert not controls.on_home(True)


def test_connecting_mid_drive_at_speed_opens_the_drive(controls):
  controls.update(True, 30 * MPH)
  assert not controls.on_home(True)


def test_card_start_is_drive_view_until_a_favorite_is_picked(controls):
  controls.update(True, 0.0)
  card = controls.nav_card
  assert card.drive_view and card.allowed("start")
  card.activate("home")
  assert not card.drive_view and card.allowed("start"), "a picked favorite turns it back into Start"
  card.activate("home")
  card.activate("start")
  assert not controls.on_home(True) and "NavDestination" not in controls.params.values
  controls.update(False, 0.0)
  assert not card.drive_view and not card.allowed("start"), "offroad there is no drive view"


def test_navigation_needs_a_secret_key(controls):
  controls.params.values.pop("MapboxSecretKey")
  controls.menu.open = True
  controls.update(True)
  row = controls.menu.rows()[0]
  assert row.key == "navigate" and not row.enabled and "Mapbox" in row.subtitle


def test_map_pane_show_and_hide_events():
  class FakeMap:
    def __init__(self):
      self.events = []

    def show_event(self):
      self.events.append("show")

    def hide_event(self):
      self.events.append("hide")

  pane = car_ui.MapPane()
  pane._map = FakeMap()
  pane.set_shown(True)
  pane.set_shown(True)
  pane.set_shown(False)
  assert pane._map.events == ["show", "hide"]


def test_starpilot_auto_map_enables_navigation_waiting_state(monkeypatch):
  created = []

  class FakeMap:
    def __init__(self, **kwargs):
      created.append(kwargs)

    def show_event(self):
      pass

  module = ModuleType("openpilot.starpilot.system.starpilot_auto.ui.nav_map")
  module.NavMapView = FakeMap
  monkeypatch.setitem(sys.modules, module.__name__, module)

  pane = car_ui.MapPane()
  assert pane._ensure_map() is pane._map
  assert created == [{"show_guidance": True, "clip": False, "show_navigation_waiting": True}]



def test_opening_the_menu_shows_current_navigation_state_at_once(controls):
  controls.update(True)
  assert not controls.menu.nav_active
  controls.params.values["NavDestination"] = '{"name": "House", "place_name": "House", "latitude": 36.3, "longitude": -115.3}'
  controls.menu.activate("button")  # no update() in between: the rows must already be right
  assert controls.menu.open and "cancel" in [row.key for row in controls.menu.rows()]


def test_button_moves_off_the_sidebar_flag_on_the_home_screen(controls):
  left = controls.menu.button_rect(screen())
  assert left.x < 200
  controls.go_home()
  right = controls.menu.button_rect(screen())
  assert right.x + right.width > 1800
  controls.menu.open = True
  panel = controls.menu.panel_rect(screen())
  assert panel.x + panel.width <= 1920 and panel.x > 1000, "the panel opens toward the screen from the right corner"
  controls.go_driving()
  assert controls.menu.button_rect(screen()).x < 200


# ── home screen Navigate card ─────────────────────────────────────────────────

def test_card_offers_home_and_work(controls):
  controls.update(False, 0.0)
  card = controls.nav_card
  assert card.home["name"] == "House" and card.work["name"] == "Office"
  assert not card.allowed("start"), "Start waits for Home or Work"
  card.activate("work")
  assert card.selected == "work" and card.allowed("start")
  card.activate("work")
  assert card.selected is None, "tapping again deselects"


def test_card_start_goes_to_the_drive_layout(controls):
  controls.update(True, 0.0)
  controls.go_home()
  card = controls.nav_card
  card.activate("home")
  card.activate("start")
  assert "House" in controls.params.values["NavDestination"]
  assert not controls.on_home(True), "Start opens the drive in the chosen car screen layout"
  assert card.selected is None and card.destination_name == "House" and card.allowed("end")
  card.activate("end")
  assert "NavDestination" not in controls.params.values and not card.destination_name


def test_card_start_offroad_sets_the_route_for_the_next_drive(controls):
  controls.update(False)
  controls.nav_card.activate("work")
  controls.nav_card.activate("start")
  assert "Office" in controls.params.values["NavDestination"]


def test_card_other_opens_the_navigate_page(controls):
  controls.update(True, 0.0)
  controls.go_home()
  controls.nav_card.activate("other")
  assert controls.nav_open


def test_card_home_work_and_start_work_at_any_speed_but_search_locks(controls):
  drive(controls)
  controls.go_home()
  controls.update(True, 40 * MPH)
  card = controls.nav_card
  assert "10 mph" in card.status_text()
  assert all(card.allowed(key) for key in ("home", "work", "start")) and not card.allowed("other")
  card.activate("work")
  card.activate("start")
  assert "Office" in controls.params.values["NavDestination"] and not controls.on_home(True)


def test_card_can_end_a_route_while_moving(controls):
  controls.params.values["NavDestination"] = '{"name": "House", "place_name": "House", "latitude": 36.3, "longitude": -115.3}'
  controls.update(True, 20 * MPH)
  card = controls.nav_card
  assert "House" in card.status_text()
  card.activate("end")
  assert "NavDestination" not in controls.params.values


def test_card_without_a_work_favorite(controls):
  import json
  controls.params.values["FavoriteDestinations"] = json.dumps([{"id": "h", "name": "House", "latitude": 36.3, "longitude": -115.3,
                                                                "is_home": True}])
  controls.update(True, 0.0)
  card = controls.nav_card
  assert card.work is None and not card.allowed("work") and card.allowed("home")


def test_dhu_session_is_pinned_below_the_limit():
  from openpilot.starpilot.system.starpilot_auto.car_screen import DHU_ENV
  sm = SimpleNamespace(recv_frame={"carState": 0}, alive={"carState": False})
  ui_state = SimpleNamespace(sm=sm)
  assert car_ui.navigation_speed(ui_state, environ={}) is None, "a real car without carState stays locked"
  assert car_ui.navigation_speed(ui_state, environ={DHU_ENV: "1"}) == 0.0


# ── Navigate screen ───────────────────────────────────────────────────────────

class FakePage:
  def __init__(self, on_started=None, **kwargs):
    from openpilot.starpilot.navigation.destination_store import same_destination
    self._same = same_destination
    self._draft_destination = None
    self._active_destination = None
    self._search_results = []
    self._favorites = []
    self._recent_destinations = []
    self._query = ""
    self._search_loading = False
    self._search_error = ""
    self._preview_routes = []
    self._preview_route_index = 0
    self._selected_favorite = None
    self.targets = []
    self.live_queries = []

  def set_live_query(self, text, now=None, immediate=False):
    self.live_queries.append((text, immediate))

  def _same_destination(self, left, right):
    return self._same(left, right)

  def _favorite_for_destination(self, destination):
    return next((f for f in self._favorites if self._same(f, destination)), None)

  @staticmethod
  def _duration_text(seconds):
    return f"{round(seconds / 60)} min"

  def _activate_navigation_target(self, target):
    self.targets.append(target)


@pytest.fixture
def nav_screen(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.car_navigate import CarNavigateScreen
  from openpilot.starpilot.system.starpilot_auto.ui import navigation
  monkeypatch.setattr(navigation, "CarNavigationLayout", FakePage)
  closed = []
  screen = CarNavigateScreen(on_started=lambda: None, on_close=lambda: closed.append(True), on_offline_maps=lambda: closed.append("offline"))
  screen.closed = closed
  return screen


def test_screen_lists_results_favorites_and_recents_with_full_addresses(nav_screen):
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.navigation import SearchResult
  page = nav_screen.page
  page._search_results = [SearchResult("Blue Bottle Coffee", "1 Ferry Building, San Francisco, CA 94111, United States", 37.8, -122.4)]
  page._favorites = [
    {"id": "o", "name": "Office", "place_name": "500 Howard St, San Francisco", "latitude": 37.7, "longitude": -122.3, "is_work": True},
    {"id": "g", "name": "Gym", "latitude": 37.6, "longitude": -122.2},
  ]
  page._recent_destinations = [{"name": "Airport", "place_name": "Airport", "latitude": 37.6, "longitude": -122.4}]
  page._draft_destination = {"name": "Gym", "latitude": 37.6, "longitude": -122.2}

  sections = dict(nav_screen.list_rows())
  assert list(sections) == ["Results", "Favorites", "Recent"]
  result = sections["Results"][0]
  assert result.target == "result:0" and result.subtitle.startswith("1 Ferry Building")
  office, gym = sorted(sections["Favorites"], key=lambda row: row.title != "Office")
  assert office.badge == "Work" and office.subtitle == "500 Howard St, San Francisco"
  assert gym.selected and gym.subtitle == "" and gym.target == "favorite:g"
  assert sections["Recent"][0].subtitle == "", "no subtitle that just repeats the title"
  assert nav_screen.notice() is None


def test_screen_notices(nav_screen):
  page = nav_screen.page
  assert nav_screen.notice()[0] == "No places yet"
  page._query = "zzzz"
  assert nav_screen.notice()[0] == "No matches"
  page._search_loading = True
  assert nav_screen.notice()[0] == "Searching…"


def test_screen_route_and_favorite_chips(nav_screen):
  page = nav_screen.page
  page._draft_destination = {"name": "Gym", "latitude": 37.6, "longitude": -122.2}
  page._preview_routes = [SimpleNamespace(total_duration=600), SimpleNamespace(total_duration=900)]
  page._preview_route_index = 1
  assert nav_screen.route_chips() == [("route:0", "Fastest · 10 min", False), ("route:1", "Route 2 · 15 min", True)]
  assert [chip[1:] for chip in nav_screen.favorite_chips()] == [("Save", False), ("Home", False), ("Work", False)]
  page._favorites = [{"id": "g", "name": "Gym", "latitude": 37.6, "longitude": -122.2, "is_home": True}]
  assert [chip[1:] for chip in nav_screen.favorite_chips()] == [("Saved", True), ("Home", True), ("Work", False)]
  page._preview_routes = page._preview_routes[:1]
  assert nav_screen.route_chips() == [], "no chips without a choice"


def test_screen_taps_activate_and_drags_scroll(nav_screen):
  import pyray as rl
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  nav_screen._list_rect = rl.Rectangle(0, 200, 800, 600)
  nav_screen._content_height = 1400
  nav_screen._targets = [("back", rl.Rectangle(0, 0, 80, 80), False), ("favorite:g", rl.Rectangle(0, 300, 800, 108), True)]

  nav_screen._handle_mouse_press(MousePos(100, 350))
  nav_screen._handle_mouse_release(MousePos(100, 352))
  assert nav_screen.page.targets == ["favorite:g"]

  nav_screen._handle_mouse_press(MousePos(100, 350))
  nav_screen._handle_mouse_event(MouseEvent(MousePos(100, 250), 0, False, False, True, 0.0))
  nav_screen._handle_mouse_release(MousePos(100, 250))
  assert nav_screen.page.targets == ["favorite:g"], "a drag scrolls instead of tapping"
  assert nav_screen.scroll == 100

  nav_screen._handle_mouse_press(MousePos(40, 40))
  nav_screen._handle_mouse_release(MousePos(40, 40))
  assert nav_screen.closed == [True]


def test_search_field_opens_a_keyboard_in_place_of_the_map_and_searches_as_you_type(nav_screen):
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.navigation import SearchResult
  page = nav_screen.page
  page._favorites = [{"id": "g", "name": "Gym", "place_name": "12 Main St", "latitude": 37.6, "longitude": -122.2}]
  page._recent_destinations = [{"name": "Airport", "latitude": 37.6, "longitude": -122.4}]
  nav_screen.activate("action:search")
  assert nav_screen.searching and nav_screen.page.targets == [], "the car's own keyboard, not the comma's dialog"
  assert nav_screen.notice() is None and [title for title, _ in nav_screen.list_rows()] == ["Favorites", "Recent"]

  for key in "mai":
    nav_screen.activate(f"key:{key}")
  assert nav_screen.typed == "mai" and page.live_queries[-1] == ("mai", False), "each key updates the live query"
  sections = dict(nav_screen.list_rows())
  assert [row.title for row in sections["Saved places"]] == ["Gym"], "saved places matching the text show at once"

  page._search_results = [SearchResult("Main Street Cafe", "Reno, NV")]
  assert [title for title, _ in nav_screen.list_rows()] == ["Suggestions", "Saved places"]
  nav_screen.activate("key:back")
  nav_screen.activate("key:space")
  nav_screen.activate("key:space")
  assert nav_screen.typed == "ma " and page.live_queries[-1] == ("ma ", False), "no double spaces"
  page._search_results = []
  page._favorites = []
  assert nav_screen.notice()[0] == "Keep typing"

  nav_screen.activate("back")
  assert not nav_screen.searching and nav_screen.closed == [], "Back puts the keyboard away before leaving"
  nav_screen.activate("action:search")
  nav_screen.activate("key:clear")
  assert nav_screen.typed == "" and page.live_queries[-1] == ("", False)
  nav_screen.activate("key:x")
  nav_screen.activate("key:done")
  assert not nav_screen.searching and page.live_queries[-1] == ("x", True), "Done searches at once"

  nav_screen.activate("action:search")
  nav_screen.activate("result:0")
  assert not nav_screen.searching and page.targets[-1] == "result:0", "picking a place brings the map back"


def test_navigate_keyboard_keys_are_tap_targets(nav_screen, monkeypatch):
  import pyray as rl
  from openpilot.starpilot.system.starpilot_auto import car_navigate
  for name in ("draw_rectangle_rounded", "draw_text_ex", "draw_line_ex"):
    monkeypatch.setattr(car_navigate.rl, name, lambda *args: None)
  monkeypatch.setattr(car_navigate, "measure_text_cached", lambda font, text, size: rl.Vector2(len(text) * size * 0.5, size))
  monkeypatch.setattr(nav_screen, "_font", lambda weight: None)
  nav_screen._targets = []
  panel = rl.Rectangle(900, 140, 980, 900)
  nav_screen._draw_keyboard(panel)
  keys = {target: area for target, area, _ in nav_screen._targets}
  assert {"key:a", "key:0", "key:back", "key:space", "key:done", "key:&"} <= set(keys)
  for area in keys.values():
    assert panel.x <= area.x and area.x + area.width <= panel.x + panel.width + 0.01
    assert panel.y <= area.y and area.y + area.height <= panel.y + panel.height + 0.01
  assert keys["key:space"].width > 3 * keys["key:a"].width


def test_live_query_waits_for_a_pause_and_keeps_results_while_loading(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui import navigation
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.navigation import SearchResult
  page = navigation.CarNavigationLayout.__new__(navigation.CarNavigationLayout)
  page._live_query, page._search_due = "", None
  page._query, page._search_results, page._search_loading, page._search_error = "", [], False, ""
  page._search_generation, page._draft_destination, page._selected_favorite = 0, None, None
  started = []

  def start(query):
    started.append(query)
    page._query, page._search_results, page._search_loading = query, [], True
  page._start_search = start

  page.set_live_query("reno c", now=10.0)
  page._run_due_search(10.2)
  assert started == [], "nothing is sent mid-word"
  page.set_live_query("reno ca", now=10.2)
  page._run_due_search(10.4)
  assert started == []
  page._run_due_search(10.2 + navigation.SEARCH_DEBOUNCE_SECONDS)
  assert started == ["reno ca"], "one search after the pause, for the latest text"

  page._search_results = [SearchResult("Reno Cafe")]
  page._search_loading = False
  page.set_live_query("reno caf", now=20.0, immediate=True)
  page._run_due_search(20.0)
  assert started[-1] == "reno caf" and [r.name for r in page._search_results] == ["Reno Cafe"], \
    "the last results stay up until the new ones arrive"

  page.set_live_query("re", now=30.0, immediate=True)
  page._run_due_search(30.0)
  assert started[-1] == "reno caf" and page._search_results == [] and page._query == "re", "too short: cleared, not sent"
  assert navigation.LiveSearchClient.search.__kwdefaults__["limit"] == navigation.LIVE_RESULT_LIMIT > 4


def test_navigate_screen_links_to_offline_maps_settings(controls, nav_screen):
  nav_screen.activate("offline_maps")
  assert nav_screen.closed == ["offline"]

  controls.update(True, 0.0)
  controls.open_navigate()
  controls.navigate_screen.on_offline_maps()
  assert not controls.nav_open and controls.main_layout.opened_panel == "OFFLINE_MAPS"
  assert controls.on_home(True), "Settings takes touches onroad like the home screen"
  touches = touch_input()
  layout_events, _ = controls.route(tap(900, 500), touches, True, screen())
  assert len(layout_events) == 2


def test_status_column_has_seven_slots_and_upgrades_six(tmp_path):
  assert len(car_screen.DEFAULTS["status_slots"]) == car_screen.STATUS_SLOT_COUNT == 7
  path = tmp_path / "car_screen.json"
  six = ["cpu", "gpu", "memory", "temperature", "friction", "steer_delay"]
  path.write_text(json.dumps({"status_slots": six}))
  assert car_screen.load(path)["status_slots"] == [*six, car_screen.DEFAULTS["status_slots"][-1]]
  seven = [*six[:5], "blank", "starpilot_logo"]
  assert car_screen.update({"status_slots": seven}, path)["status_slots"] == seven
  with pytest.raises(ValueError):
    car_screen.update({"status_slots": six}, path)


def test_map_compass_button_toggles_orientation_onroad(controls):
  import pyray as rl
  _, map_rect = car_ui.car_layout({"onroad_view": "split", "map_side": "right"}, True, False, 1920, 1080)
  button = car_ui.compass_rect(map_rect)
  assert map_rect.x < button.x and button.x + button.width < map_rect.x + map_rect.width
  toggles = []
  controls.map_button = button
  controls.on_map_button = lambda: toggles.append(True)
  touches = touch_input()
  cx, cy = button.x + button.width / 2, button.y + button.height / 2
  layout_events, menu_events = controls.route(tap(cx, cy), touches, True, screen())
  assert toggles == [True] and layout_events == [] and menu_events == []

  # Dragging off the button before lifting does nothing; the rest of the map still ignores taps.
  controls.route([TouchEvent("down", cx / 1920, cy / 1080), TouchEvent("up", 100 / 1920, 100 / 1080)], touches, True, screen())
  controls.route(tap(map_rect.x + 50, 300), touches, True, screen())
  assert toggles == [True]
  controls.map_button = None
  controls.route(tap(cx, cy), touches, True, screen())
  assert toggles == [True]
  assert isinstance(button, type(rl.Rectangle(0, 0, 0, 0)))


def test_directions_side_validates(tmp_path):
  path = tmp_path / "car_screen.json"
  assert car_screen.DEFAULTS["directions_side"] == "right"
  assert car_screen.update({"directions_side": "left"}, path)["directions_side"] == "left"
  with pytest.raises(ValueError):
    car_screen.update({"directions_side": "up"}, path)
  assert car_screen.normalize({"directions_side": "up"})["directions_side"] == "right"


def test_bookmark_button_bookmarks_on_release_onroad(controls):
  import pyray as rl
  button = rl.Rectangle(300, 700, 96, 96)
  bookmarks = []
  controls.bookmark_button = button
  controls.on_bookmark = lambda: bookmarks.append(True)
  touches = touch_input()
  cx, cy = button.x + button.width / 2, button.y + button.height / 2
  layout_events, menu_events = controls.route(tap(cx, cy), touches, True, screen())
  assert bookmarks == [True] and layout_events == [] and menu_events == []

  # Sliding off before lifting does nothing, and neither does a tap once the button is gone.
  controls.route([TouchEvent("down", cx / 1920, cy / 1080), TouchEvent("up", 100 / 1920, 100 / 1080)], touches, True, screen())
  controls.bookmark_button = None
  controls.route(tap(cx, cy), touches, True, screen())
  assert bookmarks == [True]


def test_next_orientation_flips():
  assert car_ui.next_orientation("north_up") == "heading_up"
  assert car_ui.next_orientation("heading_up") == "north_up"
