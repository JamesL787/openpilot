"""Keep car presentation changes out of native screens and construct widgets once."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pyray as rl
import pytest

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget
from openpilot.starpilot.system.starpilot_auto import ui
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot import aethergrid as car_grid
from openpilot.selfdrive.ui.layouts.settings.starpilot import aethergrid as native_grid


def test_car_settings_have_no_native_panel_dependencies():
  root = Path(ui.__file__).parent
  files = list((root / "settings_panels").rglob("*.py"))
  files += [root / name for name in ("settings.py", "starpilot_settings.py", "navigation.py", "offline_maps.py")]
  for path in files:
    for node in ast.walk(ast.parse(path.read_text())):
      imports = [node.module or ""] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
      for name in imports:
        assert name not in ("openpilot.system.ui.widgets.network", "openpilot.system.ui.widgets.bluetooth"), (path, name)
        assert not name.startswith("openpilot.selfdrive.ui.layouts.settings") or name.endswith(".types"), (path, name)


def test_simplifying_car_categories_does_not_change_native_hub(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui.starpilot_settings import CarStarPilotLayout
  from openpilot.selfdrive.ui.layouts.settings.starpilot.main_panel import StarPilotLayout
  native_categories = list(StarPilotLayout.CATEGORIES)
  monkeypatch.setattr(CarStarPilotLayout, "CATEGORIES", [{"title": "Navigation", "panel": "NAVIGATION", "icon": "road"}])
  assert StarPilotLayout.CATEGORIES == native_categories
  assert not issubclass(CarStarPilotLayout, StarPilotLayout)
  assert car_grid.HubTile is not native_grid.HubTile
  assert car_grid.BreadcrumbController is not native_grid.BreadcrumbController


def test_car_tiles_omit_constellations_and_native_tiles_keep_them(monkeypatch):
  for module, expected in ((native_grid, 1), (car_grid, 0)):
    tile = module.AetherTile.__new__(module.AetherTile)
    tile._squish = 1.0
    tile._draw_constellation = Mock()
    tile._draw_constellation_disconnected = Mock()
    monkeypatch.setattr(module, "draw_hud_background", lambda rect, accent, *_args, **_kwargs: (rect, accent))
    tile._render_hud_background(rl.Rectangle(0, 0, 300, 200), rl.WHITE)
    assert tile._draw_constellation.call_count == expected
    tile._draw_constellation_disconnected.assert_not_called()


def test_car_icons_use_supersampled_vectors_without_changing_native_icons(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot import scribble
  from openpilot.selfdrive.ui.layouts.settings.starpilot import scribble as native_icons
  from openpilot.system.ui.lib import vector_icon
  cache = Mock(return_value=None)
  geometry = Mock()
  monkeypatch.setattr(vector_icon.gui_app, "cached_render_texture", cache)
  monkeypatch.setattr(scribble, "_draw_custom_icon_geometry", geometry)
  scribble.draw_custom_icon("sound", 10, 20, 1.0, rl.WHITE)
  assert cache.call_args.kwargs["supersample"] == 4
  geometry.assert_called_once()
  assert native_icons.draw_custom_icon is not scribble.draw_custom_icon


@pytest.mark.parametrize("size", [(1920, 1080), (2400, 1080)])
def test_pairing_keeps_dark_responsive_car_presentation(monkeypatch, size):
  from openpilot.starpilot.system.starpilot_auto.ui import pairing_dialog as car
  from openpilot.selfdrive.ui.widgets import pairing_dialog as native
  monkeypatch.setattr(car.gui_app, "font", lambda *_args: None)
  monkeypatch.setattr(car, "wrap_text", lambda *_args: ["Pair device"])
  monkeypatch.setattr(native, "wrap_text", lambda *_args: ["Pair device"])
  for name in ("draw_rectangle_rounded", "draw_rectangle_rounded_lines_ex", "draw_text_ex"):
    monkeypatch.setattr(rl, name, lambda *_args: None)
  colors = []
  monkeypatch.setattr(rl, "clear_background", lambda c: colors.append((c.r, c.g, c.b, c.a)))
  for cls in (car.CarPairingDialog, native.PairingDialog):
    dialog = cls.__new__(cls)
    dialog.qr_texture = None
    dialog._close_btn = SimpleNamespace(is_pressed=False, render=Mock())
    dialog._check_qr_refresh = Mock()
    dialog._render_instructions = Mock()
    dialog._render_qr_code = Mock()
    dialog._render(rl.Rectangle(0, 0, *size))
    qr = dialog._render_qr_code.call_args.args[0]
    assert qr.width > 0 and qr.x + qr.width <= size[0]
  assert colors == [(6, 6, 15, 255), (224, 224, 224, 255)]
  assert car.CarPairingDialog._get_pairing_url is native.PairingDialog._get_pairing_url


def test_both_car_pairing_entry_points_use_car_dialog(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui import setup
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels import device
  sentinel = object()
  monkeypatch.setattr(setup, "CarPairingDialog", lambda: sentinel)
  monkeypatch.setattr(device, "PairingDialog", lambda: sentinel)
  assert setup.CarSetupWidget._create_pairing_dialog(None) is sentinel
  assert device.DeviceLayout._create_pairing_dialog(None) is sentinel


def test_car_blindspot_policy_never_changes_native_defaults(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui.onroad import CarOnroadView
  from openpilot.starpilot.system.starpilot_auto.ui.onroad_widgets import CarPipSideCamera
  from openpilot.selfdrive.ui.onroad.starpilot.starpilot_onroad_view import StarPilotOnroadView
  from openpilot.selfdrive.ui.onroad.starpilot.pip_sidecam import PipSideCamera
  monkeypatch.setattr(ui_state, "starpilot_auto_blind_spot_monitors_visible", False)
  assert not CarOnroadView._blind_spot_monitors_visible(None)
  assert not CarPipSideCamera._blind_spot_monitors_visible(None)
  assert StarPilotOnroadView._blind_spot_monitors_visible(None)
  assert PipSideCamera._blind_spot_monitors_visible(None)


def test_main_initializes_only_the_car_screens(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui import main as car
  from openpilot.selfdrive.ui.layouts import main as native
  builds = {}
  for name in ("CarSidebar", "CarDeveloperSidebar", "CarHomeLayout", "CarSettingsLayout", "CarOnroadView"):
    factory = Mock(return_value=object())
    builds[name] = factory
    monkeypatch.setattr(car, name, factory)
  monkeypatch.setattr(native, "PC", True)
  monkeypatch.setattr(native.messaging, "PubMaster", Mock())
  monkeypatch.setattr(native.MainLayout, "_setup_callbacks", Mock())
  monkeypatch.setattr(native.gui_app, "push_widget", Mock())
  monkeypatch.setattr(native.gui_app, "configure_adaptive_rendering", Mock())
  view = car.CarMainLayout()
  for factory in builds.values():
    factory.assert_called_once_with()
  assert view._layouts[native.MainState.HOME] is builds["CarHomeLayout"].return_value
  assert car.CarMainLayout.__init__ is native.MainLayout.__init__


def test_onroad_factories_register_car_widgets_once(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui import onroad as car
  from openpilot.selfdrive.ui.onroad.starpilot import starpilot_onroad_view as native

  class FakeWidget(Widget):
    priority = 0

    def __init__(self, *_args):
      super().__init__()

    def _render(self, _rect):
      pass

  def init_road(view, *_args):
    Widget.__init__(view)
    view._closed = True
    view._content_rect = rl.Rectangle(0, 0, 1920, 1080)
    view._hud_renderer = SimpleNamespace(_exp_button=object())
    view.driver_state_renderer = object()

  monkeypatch.setattr(native.AugmentedRoadView, "__init__", init_road)
  monkeypatch.setattr(native.gui_app, "font", lambda *_args: None)
  for name in ("TorqueBar", "SetSpeedWidget", "SteeringWheelWidget", "PedalIconsWidget",
               "PersonalityButtonWidget", "ModelSourceWidget"):
    monkeypatch.setattr(native, name, FakeWidget)
  builds = {}
  for name in ("CarPipSideCamera", "CarSpeedLimitWidget", "CarStoppedTimerWidget", "NoFavoriteMenu",
               "CarAetherGaugeWidget", "CarDriverMonitorWidget"):
    builds[name] = Mock(side_effect=FakeWidget)
    monkeypatch.setattr(car, name, builds[name])
  for name in ("PipSideCamera", "SpeedLimitWidget", "StoppedTimerWidget", "FavoriteRadialMenu",
               "AetherGaugeWidget", "DriverMonitorWidget"):
    monkeypatch.setattr(native, name, Mock(side_effect=AssertionError("constructed a discarded native widget")))
  view = car.CarOnroadView()
  for factory in builds.values():
    assert factory.call_count == 1
  for widget in (view._pip_sidecam, view._speed_limit_widget, view._stopped_timer_widget,
                 view._aethergauge_widget, view._driver_monitor_widget):
    assert view._children.count(widget) == 1
  assert view.layout_manager.zones["left"].count(view._speed_limit_widget) == 1
