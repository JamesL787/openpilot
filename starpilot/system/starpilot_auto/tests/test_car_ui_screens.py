"""The car screen's own UI (starpilot/system/starpilot_auto/ui): car-only layout that the comma screen never draws."""

from types import SimpleNamespace

import pyray as rl
import pytest
from cereal import log

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.panel import StarPilotPanelType
from openpilot.selfdrive.ui.onroad.alert_renderer import ALERT_HEIGHTS, AlertSize
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.system.starpilot_auto.ui import developer_sidebar as car_sidebar
from openpilot.starpilot.system.starpilot_auto.ui import onroad_widgets
from openpilot.starpilot.system.starpilot_auto.ui import starpilot_settings
from openpilot.starpilot.system.starpilot_auto.ui.onroad_widgets import (
  CarAlertRenderer,
  CarPipSideCamera,
  CarStoppedTimerWidget,
  lateral_pause_rect,
)

SCREEN = rl.Rectangle(0, 0, 1920, 1080)
CHAR_WIDTH = 20  # the fake labels measure every character this wide


# ── alerts around the side camera ────────────────────────────────────────────

class FakeAlertSM(dict):
  def __init__(self, alert_type: str, text1: str = "Changing Lanes"):
    super().__init__(selfdriveState=log.SelfdriveState.new_message(
      alertSize="small", alertText1=text1, alertStatus="normal", alertType=alert_type,
    ))
    self.updated = {"selfdriveState": True}
    self.recv_frame = {"selfdriveState": 10}


class FakeLabel:
  def __init__(self):
    self.text = ""
    self.text_width = 0.0

  def set_text(self, text):
    self.text = text

  def set_font_size(self, _size):
    pass

  def get_content_height(self, _max_width):
    self.text_width = len(self.text) * CHAR_WIDTH
    return 60.0


def _alert_renderer(monkeypatch, covers=None):
  monkeypatch.setattr(ui_state, "starpilot_toggles", {})
  monkeypatch.setattr(ui_state, "started_frame", 0)
  renderer = CarAlertRenderer.__new__(CarAlertRenderer)
  renderer._prev_alert = None
  renderer._current_alert = None
  renderer._alpha_filter = FirstOrderFilter(0, 0.05, 0.05)
  renderer._alert_y_filter = FirstOrderFilter(0, 0.05, 0.05)
  renderer._draw_background = lambda _alert: None
  renderer._draw_text = lambda _alert: None
  renderer._alert_text1_label = FakeLabel()
  renderer._alert_text2_label = FakeLabel()
  renderer.hidden_alert_names = frozenset({"laneChange"})
  renderer.covers = covers
  renderer.deferred = False
  renderer._cover_rect = SCREEN
  return renderer


def test_alert_text_bounds_are_the_centred_text_not_the_whole_band(monkeypatch):
  renderer = _alert_renderer(monkeypatch)
  alert = renderer.get_alert(FakeAlertSM("laneChange/warning", text1="x" * 10))

  bounds = renderer._text_bounds(alert, SCREEN)

  assert (bounds.x, bounds.width) == (860, 200)
  band_top = SCREEN.height - ALERT_HEIGHTS[AlertSize.small]
  assert bounds.y == band_top + (ALERT_HEIGHTS[AlertSize.small] - 60) / 2
  assert bounds.height == 60


def test_hidden_banner_drops_only_when_its_text_is_covered(monkeypatch):
  covered = []
  renderer = _alert_renderer(monkeypatch, covers=lambda area: covered.append(area) or area.width > 400)
  monkeypatch.setattr(ui_state, "sm", FakeAlertSM("laneChange/warning", text1="x" * 10))
  renderer._render(SCREEN)
  assert renderer._current_alert is not None  # 200px of text fits between the bubbles

  monkeypatch.setattr(ui_state, "sm", FakeAlertSM("laneChange/warning", text1="x" * 40))
  renderer._render(SCREEN)
  assert renderer._current_alert is None and renderer._prev_alert is None


def test_only_named_alerts_can_be_hidden(monkeypatch):
  renderer = _alert_renderer(monkeypatch, covers=lambda _area: True)
  monkeypatch.setattr(ui_state, "sm", FakeAlertSM("steerSaturated/warning"))
  assert not renderer._is_covered(renderer.get_alert(ui_state.sm), SCREEN)

  renderer.covers = None
  monkeypatch.setattr(ui_state, "sm", FakeAlertSM("laneChange/warning"))
  assert not renderer._is_covered(renderer.get_alert(ui_state.sm), SCREEN)


def test_deferred_alert_skips_the_road_views_own_pass(monkeypatch):
  renderer = _alert_renderer(monkeypatch)
  drawn = []
  monkeypatch.setattr(onroad_widgets.AlertRenderer, "render", lambda self, rect=None: drawn.append(rect))
  renderer.deferred = True
  assert renderer.render(SCREEN) is None and drawn == []
  renderer.deferred = False
  renderer.render(SCREEN)
  assert drawn == [SCREEN]


# ── side camera ──────────────────────────────────────────────────────────────

def test_pip_reports_whether_it_drew_this_frame(monkeypatch):
  camera = CarPipSideCamera.__new__(CarPipSideCamera)
  camera._closed = True
  camera._shape = "bubble"
  camera._drawn = []
  camera._mask = {"center_left": [100, 200], "center_right": [900, 200], "crop_size": 100}
  monkeypatch.setattr(onroad_widgets.PipSideCamera, "_draw_bubble", lambda *_args: None)
  camera._acquire_frame = lambda: True
  monkeypatch.setattr(ui_state, "started", True)

  camera.active_sides = lambda: ["left"]
  camera._render(SCREEN)
  assert camera.showing

  camera.active_sides = list
  camera._render(SCREEN)
  assert not camera.showing
  assert not camera.covers(SCREEN)

  camera.active_sides = lambda: ["left"]
  camera._acquire_frame = lambda: False
  camera._render(SCREEN)
  assert not camera.showing


def test_pip_bubbles_cover_only_what_they_overlap():
  camera = CarPipSideCamera.__new__(CarPipSideCamera)
  camera._closed = True
  bubble = rl.Rectangle(24, 432, 624, 624)  # a 312px bubble in the bottom-left corner
  camera._drawn = [("bubble", bubble)]

  assert camera.covers(rl.Rectangle(500, 950, 400, 60))  # runs into the bubble
  assert not camera.covers(rl.Rectangle(700, 950, 400, 60))  # clear of it, in the gap
  assert not camera.covers(rl.Rectangle(560, 440, 80, 40))  # the corner beside the circle

  camera._drawn = [("curved", rl.Rectangle(0, 0, 1920, 1080))]
  assert camera.covers(rl.Rectangle(700, 950, 400, 60))


# ── stopped timer and lateral pause ──────────────────────────────────────────

def test_stopped_timer_replaces_speed_in_full_and_split_camera_panes(monkeypatch):
  monkeypatch.setattr(onroad_widgets, "measure_text_cached",
                      lambda _font, text, size: SimpleNamespace(x=len(text) * size * 0.55, y=size * 0.8))
  for rect in (rl.Rectangle(0, 0, 1920, 1080), rl.Rectangle(806, 0, 1114, 1080)):
    widget = CarStoppedTimerWidget.__new__(CarStoppedTimerWidget)
    widget._font_bold = widget._font_normal = None
    widget._duration = 61
    draws = []
    monkeypatch.setattr(onroad_widgets.rl, "draw_text_ex", lambda *args, draws=draws: draws.append(args))
    widget._render(rect)

    shadows = len(CarStoppedTimerWidget.SHADOW_RINGS) * len(CarStoppedTimerWidget.SHADOW_DIRECTIONS)
    assert len(draws) == 2 * (shadows + 1)  # the halo and the foreground for each line
    label, timer = draws[shadows], draws[-1]
    assert (label[1], timer[1]) == ("Stopped", "01:01")
    # The shadow surrounds the text: it spreads left, right, up and down by the same amount.
    offsets = [(pos.x - label[2].x, pos.y - label[2].y) for _font, _text, pos, *_ in draws[:shadows]]
    spread = max(radius for radius, _alpha in CarStoppedTimerWidget.SHADOW_RINGS)
    for axis in (0, 1):
      assert min(o[axis] for o in offsets) == pytest.approx(-spread)
      assert max(o[axis] for o in offsets) == pytest.approx(spread)
    # The label's ink starts level with the top of the MAX card and the steering wheel.
    label_ink = onroad_widgets.text_ink(None, "Stopped", label[3])
    assert label[2].y + label_ink.y == rect.y + onroad_widgets.CONTROL_TOP
    timer_ink = onroad_widgets.text_ink(None, "01:01", timer[3])
    assert timer[2].y + timer_ink.y == pytest.approx(rect.y + onroad_widgets.CONTROL_TOP + label_ink.height +
                                                     CarStoppedTimerWidget.LINE_GAP)
    # Centred between the MAX card's right edge and the steering wheel's left edge (as far from
    # each), where the speed it replaces sits, and clear of both.
    max_right = rect.x + onroad_widgets.WIDGET_ANCHOR_OFFSET + onroad_widgets.CONTROL_WIDTH / 2
    wheel_left = rect.x + rect.width - onroad_widgets.RIGHT_COLUMN_ANCHOR - onroad_widgets.EXP_BUTTON_SIZE / 2
    center = (max_right + wheel_left) / 2
    assert center > rect.x + rect.width / 2, "the wheel hugs its edge more than MAX does"
    assert abs(label[2].x + len("Stopped") * label[3] * 0.55 / 2 - center) < 1
    assert abs(timer[2].x + len("01:01") * timer[3] * 0.55 / 2 - center) < 1
    left = max_right + CarStoppedTimerWidget.HORIZONTAL_MARGIN
    right = wheel_left - CarStoppedTimerWidget.HORIZONTAL_MARGIN
    assert label[2].x >= left - 1 and label[2].x + len("Stopped") * label[3] * 0.55 <= right + 1


def test_lateral_pause_is_centered_above_torque_bar():
  display_width = 1920
  for camera in (rl.Rectangle(0, 0, 1920, 1080), rl.Rectangle(806, 0, 1114, 1080)):
    badge = lateral_pause_rect(camera, display_width)
    scale = camera.height / 240.0 * (camera.width / display_width)
    torque_bar_top = camera.y + camera.height - onroad_widgets.TORQUE_BAR_MAX_RISE * scale

    assert badge.width > 120 and badge.height > 72  # larger than the comma's badge
    assert badge.x + badge.width / 2 == pytest.approx(camera.x + camera.width / 2, abs=1e-3)
    assert badge.y + badge.height == pytest.approx(torque_bar_top - onroad_widgets.TORQUE_BAR_GAP, abs=1e-3)


# ── status sidebar ───────────────────────────────────────────────────────────

class FakeSidebarParams:
  def get_int(self, key, **kwargs):
    return {"DeveloperSidebarMetric1": 5, "DeveloperSidebarMetric2": 6, "DeveloperSidebarMetric3": 7}.get(key, 0)

  def get_bool(self, key, default=False, **kwargs):
    return default  # the comma's Developer Sidebar is off

  def get_float(self, key, **kwargs):
    return 0.0

  def get(self, key, **kwargs):
    return None


class FakeDeviceSM(dict):
  frame = 100

  def __init__(self, device_state):
    super().__init__(deviceState=device_state)
    self.valid = {"deviceState": True}


@pytest.fixture
def status_sidebar(monkeypatch):
  from openpilot.selfdrive.ui.onroad.starpilot import developer_sidebar as module
  monkeypatch.setattr(module.gui_app, "font", lambda *args, **kwargs: None)
  monkeypatch.setattr(module.ui_state, "ui_params", FakeSidebarParams(), raising=False)
  device_state = SimpleNamespace(cpuUsagePercent=[20, 40], gpuUsagePercent=63, maxTempC=71.4,
                                 memoryUsagePercent=48, freeSpacePercent=72.9)
  monkeypatch.setattr(module.ui_state, "sm", FakeDeviceSM(device_state), raising=False)
  monkeypatch.setattr(module.ui_state, "started_frame", 0, raising=False)
  monkeypatch.setattr(module.ui_state, "starpilot_toggles", {}, raising=False)
  return car_sidebar.CarDeveloperSidebar()


def test_sidebar_follows_the_comma_toggle_without_car_slots(status_sidebar):
  status_sidebar.update()
  assert not status_sidebar.visible


def test_car_slots_show_the_sidebar_with_device_metrics(status_sidebar):
  status_sidebar.metric_override = [3, 4, 18, 19, 20, 21]
  status_sidebar.update()
  assert status_sidebar.visible
  assert status_sidebar._active_ids == [3, 4, 18, 19, 20, 21]
  assert [status_sidebar._metrics[i] for i in (18, 19, 20, 21, 22)] == [
    ("CPU", "30%"), ("GPU", "63%"), ("TEMP", "71°C"), ("MEMORY", "48%"), ("STORAGE", "72% FREE")]


@pytest.mark.parametrize("hour,minute,expected", [(0, 5, "12:05 AM"), (9, 30, "9:30 AM"), (12, 0, "12:00 PM"), (23, 59, "11:59 PM")])
def test_clock_slot_shows_local_time(status_sidebar, monkeypatch, hour, minute, expected):
  monkeypatch.setattr(car_sidebar.time, "tzset", lambda: None)
  monkeypatch.setattr(car_sidebar.time, "localtime", lambda *_: SimpleNamespace(tm_hour=hour, tm_min=minute))
  status_sidebar.metric_override = [car_sidebar.CLOCK_METRIC]
  status_sidebar.update()
  assert status_sidebar._active_ids == [car_sidebar.CLOCK_METRIC]
  assert status_sidebar._metrics[car_sidebar.CLOCK_METRIC] == ("TIME", expected)


def test_empty_car_slot_is_not_a_toggle_fallback(status_sidebar):
  status_sidebar.metric_override = [0, 18]
  status_sidebar.update()
  assert status_sidebar._active_ids == [18]


def test_logo_and_blank_slots_keep_their_places(status_sidebar, monkeypatch):
  status_sidebar.metric_override = [18, car_sidebar.BLANK_METRIC, car_sidebar.LOGO_METRIC, 19]
  status_sidebar.update()
  draws = []
  monkeypatch.setattr(status_sidebar, "_draw_metric", lambda rect, first, second, color, y: draws.append((first, y)))
  monkeypatch.setattr(status_sidebar, "_draw_logo", lambda rect, y: draws.append(("logo", y)))
  monkeypatch.setattr(car_sidebar.rl, "draw_rectangle_rec", lambda *args: None)
  status_sidebar.render(rl.Rectangle(0, 0, 300, 1080))
  assert [name for name, _ in draws] == ["CPU", "logo", "GPU"]
  step = draws[1][1] - draws[0][1]
  assert step > 2 * car_sidebar.METRIC_HEIGHT, "the blank slot keeps its space"
  assert draws[2][1] - draws[1][1] == step / 2


def test_car_max_card_puts_the_label_at_the_top_edge(monkeypatch):
  monkeypatch.setattr(onroad_widgets, "measure_text_cached",
                      lambda _font, text, size: SimpleNamespace(x=len(text) * size * 0.55, y=size * 0.8))
  monkeypatch.setattr(onroad_widgets, "draw_control_card", lambda rect: None)
  monkeypatch.setattr(onroad_widgets, "tr", lambda text: text)
  draws = []
  monkeypatch.setattr(onroad_widgets.rl, "draw_text_ex", lambda font, text, pos, size, spacing, color: draws.append((text, pos, size)))
  widget = onroad_widgets.CarSetSpeedWidget.__new__(onroad_widgets.CarSetSpeedWidget)
  widget._font_semi_bold = widget._font_bold = None
  widget.hud_renderer = SimpleNamespace(is_cruise_set=True, set_speed=65.0)
  rect = rl.Rectangle(58, 45, 176, 196)
  widget._render(rect)
  (label, label_pos, label_size), (value, value_pos, value_size) = draws
  assert (label, value) == ("MAX", "65")
  assert label_pos.y == rect.y + onroad_widgets.CARD_INK_MARGIN
  label_bottom, value_bottom = label_pos.y + label_size * 0.8, value_pos.y + value_size * 0.8
  bottom = rect.y + rect.height - onroad_widgets.CARD_INK_MARGIN
  assert abs((value_pos.y - label_bottom) - (bottom - value_bottom)) < 1e-6, "value centred below"


class _GlyphFont(SimpleNamespace):
  """Two glyphs with the proportions of Inter's digits: ink from 19% to 81% of the line box,
  and a "1" whose ink sits right of its advance's centre."""

  def __init__(self):
    super().__init__(baseSize=100, glyphCount=2, texture=SimpleNamespace(id=7),
                     glyphs=[SimpleNamespace(offsetX=4, offsetY=19, advanceX=60), SimpleNamespace(offsetX=10, offsetY=19, advanceX=40)],
                     recs=[SimpleNamespace(width=52, height=62), SimpleNamespace(width=24, height=62)])


def test_card_text_is_placed_by_its_ink(monkeypatch):
  monkeypatch.setattr(onroad_widgets.rl, "get_glyph_index", lambda font, codepoint: 1 if chr(codepoint) == "1" else 0)
  monkeypatch.setattr(onroad_widgets, "FONT_SCALE", 1.0)
  onroad_widgets._ink_cache.clear()
  font = _GlyphFont()
  ink = onroad_widgets.text_ink(font, "15", 100)
  assert (ink.x, ink.y, ink.width, ink.height) == (10, 19, 86, 62)  # "1" ink 10..34, "5" ink 44..96
  draws = []
  monkeypatch.setattr(onroad_widgets.rl, "draw_text_ex", lambda font, text, pos, size, spacing, color: draws.append(pos))
  bottom = onroad_widgets.draw_ink(font, "15", 100, 500, 200, None)
  assert bottom == 262
  assert draws[0].y == 200 - 19, "the line box's empty top is not counted"
  assert draws[0].x + ink.x + ink.width / 2 == 500, "centred by ink, not by advance"


def test_car_limit_card_matches_the_max_card(monkeypatch):
  monkeypatch.setattr(onroad_widgets, "measure_text_cached",
                      lambda _font, text, size: SimpleNamespace(x=len(text) * size * 0.55, y=size * 0.8))
  monkeypatch.setattr(onroad_widgets, "draw_control_card", lambda rect, **kwargs: None)
  chips = []
  monkeypatch.setattr(onroad_widgets.slc, "_draw_offset_chip", lambda rect, text, color: chips.append(rect))
  monkeypatch.setattr(onroad_widgets.slc, "_get_bold", lambda: None)
  monkeypatch.setattr(onroad_widgets.slc, "_get_semi_bold", lambda: None)
  monkeypatch.setattr(onroad_widgets.slc, "tr", lambda text: text)
  draws = []
  monkeypatch.setattr(onroad_widgets.rl, "draw_text_ex", lambda font, text, pos, size, spacing, color: draws.append((text, pos, size)))
  rect = rl.Rectangle(58, 256, 176, 196)
  state = {"slc_overridden_speed": 0, "speed_limit_source": "Map Data", "show_offset": False, "offset_str": "+5",
           "speed_limit_str": "45"}
  onroad_widgets.CarSpeedLimitWidget._draw_card(state, rect)
  (label, label_pos, _), (value, value_pos, value_size) = draws
  assert (label, value) == ("MAP", "45")
  assert label_pos.y == rect.y + onroad_widgets.CARD_INK_MARGIN and value_size == onroad_widgets.SET_SPEED_VALUE_FONT
  assert chips == []

  draws.clear()
  onroad_widgets.CarSpeedLimitWidget._draw_card({**state, "show_offset": True}, rect)
  (_, label_pos, label_size), (_, value_pos, value_size) = draws
  chip_top = rect.y + rect.height - onroad_widgets.LIMIT_CHIP_LIFT - onroad_widgets.slc.OFFSET_CHIP_BOTTOM - onroad_widgets.slc.OFFSET_CHIP_HEIGHT
  label_bottom, value_bottom = label_pos.y + label_size * 0.8, value_pos.y + value_size * 0.8
  assert abs((value_pos.y - label_bottom) - (chip_top - value_bottom)) < 1e-6, "value centred between label and chip"
  chip_bottom = chips[0].y + chips[0].height - onroad_widgets.slc.OFFSET_CHIP_BOTTOM
  assert rect.y + rect.height - chip_bottom == onroad_widgets.CARD_INK_MARGIN, "chip as far from the bottom as the label from the top"


def test_unavailable_gpu_sample_is_not_reported_as_zero(status_sidebar):
  ui_state.sm["deviceState"].gpuUsagePercent = -1
  status_sidebar.metric_override = [19] * 6
  status_sidebar.update()
  assert status_sidebar._metrics[19] == ("GPU", "N/A")


# ── StarPilot settings hub ───────────────────────────────────────────────────

class _FakeHubTile:
  def __init__(self, title, desc, icon_key, on_click, bg_color=None):
    self.title, self.on_click = title, on_click


class _FakeGrid:
  def __init__(self):
    self.tiles = []

  def clear(self):
    self.tiles = []

  def add_tile(self, tile):
    self.tiles.append(tile)


class _PanelSpy:
  def __init__(self, name):
    self.name = name
    self.segment = None
    self.current_sub_panel = ""

  def show_event(self):
    pass

  def hide_event(self):
    pass

  def open_segment(self, segment):
    self.segment = segment

  def set_current_sub_panel(self, sub_panel):
    self.current_sub_panel = sub_panel


def _hub(monkeypatch):
  import openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.main_panel as main_panel
  monkeypatch.setattr(main_panel, "HubTile", _FakeHubTile)

  def base_init(layout):
    layout._current_panel = StarPilotPanelType.MAIN
    layout._hub_path = []
    layout._selected_leaf = None
    layout._current_category_idx = None
    layout._panel_stack = []
    layout._depth_callback = None
    layout._main_grid = _FakeGrid()
    layout._panels = {panel_type: SimpleNamespace(name=panel_type.name, instance=None if panel_type == StarPilotPanelType.MAIN
                                                  else _PanelSpy(panel_type.name)) for panel_type in StarPilotPanelType}
    layout._panels[StarPilotPanelType.MAPS] = layout._create_maps_panel()
    layout._panels[StarPilotPanelType.NAVIGATION] = layout._create_navigation_panel()
    layout._rebuild_grid()

  built = {}

  def offline_maps():
    built["offline_maps"] = built.get("offline_maps", 0) + 1
    return _PanelSpy("OFFLINE_MAPS")

  monkeypatch.setattr(main_panel.StarPilotLayout, "__init__", base_init)
  monkeypatch.setattr(starpilot_settings, "StarPilotOfflineMapsLayout", offline_maps)
  monkeypatch.setattr(starpilot_settings, "CarNavigationLayout", lambda: _PanelSpy("CAR_NAVIGATION"))
  layout = starpilot_settings.CarStarPilotLayout()
  depths = []
  layout.set_depth_callback(depths.append)
  return layout, depths, built


def test_car_hub_has_offline_maps_in_place_of_map_data(monkeypatch):
  layout, _, built = _hub(monkeypatch)
  controls = next(item for item in layout.CATEGORIES if item["title"] == "Driving Controls")
  nav_maps = controls["children"][0]
  assert [child["title"] for child in nav_maps["children"]] == ["Navigation", "Offline Maps"]
  assert layout._panels[StarPilotPanelType.MAPS].instance.name == "OFFLINE_MAPS"
  assert built["offline_maps"] == 1
  assert layout._panels[StarPilotPanelType.NAVIGATION].instance.name == "CAR_NAVIGATION"


def test_open_panel_jumps_to_offline_maps_with_the_folders_behind_it(monkeypatch):
  layout, depths, _ = _hub(monkeypatch)
  layout.open_panel("OFFLINE_MAPS")
  assert layout._current_panel == StarPilotPanelType.MAPS
  assert [folder["title"] for folder in layout._hub_path] == ["Driving Controls", "Navigation & Maps"]
  assert depths[-1] == 3
  layout.navigate_back()
  assert layout._current_panel == StarPilotPanelType.MAIN and depths[-1] == 2, "Back walks up to Navigation & Maps"


def test_map_data_deep_link_opens_offline_maps_on_the_speed_limit_segment(monkeypatch):
  layout, _, _ = _hub(monkeypatch)
  offline = layout._panels[StarPilotPanelType.MAPS].instance
  layout.open_panel("MAPS")
  assert layout._current_panel == StarPilotPanelType.MAPS and offline.segment == 1
  layout.open_panel("OFFLINE_MAPS")
  assert offline.segment == 0, "the car screen's Offline Maps button lands on the map display"


def test_comma_hub_is_unchanged():
  from openpilot.selfdrive.ui.layouts.settings.starpilot.main_panel import StarPilotLayout
  controls = next(item for item in StarPilotLayout.CATEGORIES if item["title"] == "Driving Controls")
  assert [child["title"] for child in controls["children"][0]["children"]] == ["Map Data", "Navigation"]
  assert not hasattr(StarPilotLayout, "open_panel")


# ── Navigation page ──────────────────────────────────────────────────────────

def _nav_page(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui import navigation
  page = navigation.CarNavigationLayout.__new__(navigation.CarNavigationLayout)
  page._map = SimpleNamespace(clear_preview=lambda: None, set_preview=lambda *args: page.previews.append(args))
  page.previews = []
  page._route_generation = 0
  page._preview_routes = [SimpleNamespace(geometry=[]), SimpleNamespace(geometry=[])]
  page._preview_route_index = 0
  page._routes_loading = False
  page._routes_error = ""
  page._draft_destination = {"latitude": 36.1, "longitude": -115.2, "name": "Office"}
  page.started = []
  page._on_started = lambda: page.started.append(True)
  return navigation, page


def test_start_uses_the_chosen_route_and_reports_only_accepted_starts(monkeypatch):
  navigation, page = _nav_page(monkeypatch)
  sent = []

  def start(self):
    sent.append(dict(self._draft_destination))
    if self._draft_destination["name"] != "Invalid":
      self._draft_destination = None

  monkeypatch.setattr(navigation.StarPilotNavigationLayout, "_start_navigation", start)
  page._activate_navigation_target("route:1")
  page._start_navigation()
  assert sent[-1]["routeId"] == "alt-1"
  assert page.started == [True] and page._preview_routes == []

  page._draft_destination = {"latitude": 36.1, "longitude": -115.2, "name": "Invalid"}
  page._start_navigation()
  assert page.started == [True], "a refused destination is not a started route"


def test_route_choices_sit_between_summary_and_actions(monkeypatch):
  navigation, page = _nav_page(monkeypatch)
  calls = []
  monkeypatch.setattr(navigation.CarNavigationLayout, "_draw_route_section", lambda self, x, y, w, m: calls.append(("routes", y)) or 300.0)
  monkeypatch.setattr(navigation.StarPilotNavigationLayout, "_draw_action_buttons",
                      lambda self, x, y, w, m: calls.append(("actions", y)) or 78.0)
  assert page._draw_action_buttons(0, 100, 500, None) == 378.0
  assert calls == [("routes", 100), ("actions", 400)]


# ── status column and current speed ─────────────────────────────────────────

def test_car_layout_leaves_the_status_column_to_car_ui():
  from openpilot.selfdrive.ui.layouts.main import MainState
  from openpilot.starpilot.system.starpilot_auto.ui.main import CarMainLayout
  calls = []
  layout = CarMainLayout.__new__(CarMainLayout)
  layout._rect = rl.Rectangle(0, 0, 1500, 1080)
  layout._current_mode = MainState.ONROAD
  layout._sidebar = SimpleNamespace(is_visible=False, render=lambda rect: calls.append("sidebar"))
  layout._dev_sidebar = SimpleNamespace(visible=True, update=lambda: calls.append("update"),
                                        render=lambda rect: calls.append(("status", rect.x)))
  layout._layouts = {MainState.ONROAD: SimpleNamespace(render=lambda rect: calls.append(("onroad", rect.width)))}
  layout._render_main_content()
  assert calls == [("onroad", 1500)], "the driving view keeps its whole rect and draws no column of its own"
  layout.render_status(rl.Rectangle(1500, 0, 300, 1080))
  assert calls[1:] == ["update", ("status", 1500)]


def test_current_speed_sits_level_with_the_controls_and_can_be_hidden(monkeypatch):
  hud = onroad_widgets.CarHudRenderer.__new__(onroad_widgets.CarHudRenderer)
  hud._font_bold = hud._font_medium = None
  hud.speed = 42.4
  tops = []
  centers = []
  monkeypatch.setattr(onroad_widgets, "draw_ink",
                      lambda font, text, size, x, top, color: tops.append((text, top)) or centers.append(x) or top + 100)
  monkeypatch.setattr(onroad_widgets, "get_compass_text", lambda: None)
  monkeypatch.setattr(ui_state, "is_metric", False)
  rect = rl.Rectangle(0, 30, 1200, 1000)
  monkeypatch.setattr(ui_state, "car_show_current_speed", True)
  hud._draw_current_speed(rect)
  assert tops == [("42", rect.y + onroad_widgets.CONTROL_TOP), ("mph", rect.y + onroad_widgets.CONTROL_TOP + 100 +
                                                                     onroad_widgets.SPEED_UNIT_GAP)]
  assert centers == [sum(onroad_widgets.top_center_span(rect)) / 2] * 2, "centred between MAX and the wheel, like Stopped"
  tops.clear()
  monkeypatch.setattr(ui_state, "car_show_current_speed", False)
  hud._draw_current_speed(rect)
  assert tops == []


# ── bookmark, driver monitoring, gauge and directions ────────────────────────

def test_bookmark_steps_the_counter_feedbackd_watches():
  class Memory(dict):
    def get_int(self, key):
      return self.get(key, 0)

    def put_int(self, key, value):
      self[key] = value

  memory = Memory()
  onroad_widgets.request_bookmark(memory)
  onroad_widgets.request_bookmark(memory)
  assert memory == {"WheelButtonBookmarkCounter": 2}


def test_bookmark_is_a_status_slot_not_a_button_over_the_dm_icon(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import car_screen
  from openpilot.starpilot.system.starpilot_auto.ui import developer_sidebar, onroad
  assert onroad_widgets.DM_SIZE < 192 and onroad_widgets.DM_ICON_SIZE < 128
  assert not hasattr(onroad.CarOnroadView, "_dm_center"), "nothing is drawn above the DM icon any more"
  assert car_screen.STATUS_METRICS["bookmark"][0] == developer_sidebar.BOOKMARK_METRIC
  assert car_screen.normalize({"status_slots": ["bookmark", *car_screen.DEFAULTS["status_slots"][1:]]})["status_slots"][0] == "bookmark"

  sidebar = developer_sidebar.CarDeveloperSidebar.__new__(developer_sidebar.CarDeveloperSidebar)
  sidebar._visible, sidebar.metric_override = True, [developer_sidebar.BLANK_METRIC, developer_sidebar.BOOKMARK_METRIC]
  sidebar._slot_ids = list(sidebar.metric_override)
  sidebar._metrics, sidebar._font_bold, sidebar.bookmark_rect = {}, None, None
  drawn = []
  sidebar.bookmark = SimpleNamespace(render=lambda rect, font, size: drawn.append(rect))
  monkeypatch.setattr(developer_sidebar.rl, "draw_rectangle_rec", lambda *args: None)
  column = rl.Rectangle(1500, 0, 300, 1080)
  sidebar.render(column)
  assert drawn == [sidebar.bookmark_rect], "the tap target is exactly the card that was drawn"
  card = sidebar.bookmark_rect
  assert column.x <= card.x and card.x + card.width <= column.x + column.width and card.y > column.height / 2

  sidebar._slot_ids = sidebar.metric_override = [developer_sidebar.BLANK_METRIC, 18]
  sidebar._metrics, sidebar._metric_colors, sidebar._metric_color = {18: ("CPU", "5%")}, {}, None
  sidebar._draw_metric = lambda *args: None
  sidebar.render(column)
  assert sidebar.bookmark_rect is None, "no slot, no tap target"


def test_bookmark_card_confirms_a_press(monkeypatch):
  now = [100.0]
  requests = []
  monkeypatch.setattr(onroad_widgets, "request_bookmark", lambda memory: requests.append(True))
  button = onroad_widgets.CarBookmarkButton(clock=lambda: now[0])
  assert button.lit() == 0
  button.press()
  assert requests == [True] and button.lit() == 1.0
  now[0] += onroad_widgets.BOOKMARK_FLASH_SECONDS / 2
  assert button.lit() == pytest.approx(0.5)
  now[0] += onroad_widgets.BOOKMARK_FLASH_SECONDS
  assert button.lit() == 0


def test_gauge_is_pulled_up_under_the_limit_card():
  native = onroad_widgets.AetherGaugeWidget
  car = onroad_widgets.CarAetherGaugeWidget
  assert native.ROAD_BOTTOM - car.ROAD_BOTTOM == native.HEIGHT - car.HEIGHT == onroad_widgets.GAUGE_TOP_TRIM > 0


@pytest.mark.parametrize("left", [False, True])
def test_directions_card_follows_the_directions_side(monkeypatch, left):
  monkeypatch.setattr(ui_state, "car_directions_left", left)
  card = onroad_widgets.CarNavigationCardRenderer.__new__(onroad_widgets.CarNavigationCardRenderer)
  rect = rl.Rectangle(30, 30, 1860, 1020)
  x = card._card_x(rect, 560)
  if left:
    assert x == int(rect.x + onroad_widgets.DIRECTIONS_LEFT_X)
    # clear of the MAX / LIMIT column
    assert x > rect.x + onroad_widgets.WIDGET_ANCHOR_OFFSET + onroad_widgets.CONTROL_WIDTH / 2
  else:
    assert x == int(rect.x + rect.width - 560 - 40)
