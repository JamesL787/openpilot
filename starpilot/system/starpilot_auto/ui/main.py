"""Car screens using the shared main layout's initialization and lifecycle."""

import pyray as rl

from openpilot.selfdrive.ui.layouts.main import MainLayout, MainState
from openpilot.selfdrive.ui.layouts.settings.types import PanelType
from openpilot.starpilot.system.starpilot_auto.ui.developer_sidebar import CarDeveloperSidebar
from openpilot.starpilot.system.starpilot_auto.ui.home import CarHomeLayout
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.system.starpilot_auto.ui.onroad import CarOnroadView
from openpilot.starpilot.system.starpilot_auto.ui.onroad_widgets import request_bookmark
from openpilot.starpilot.system.starpilot_auto.ui.settings import CarSettingsLayout
from openpilot.starpilot.system.starpilot_auto.ui.sidebar import CarSidebar


class CarMainLayout(MainLayout):
  def _create_sidebar(self):
    return CarSidebar()

  def _create_developer_sidebar(self):
    return CarDeveloperSidebar()

  def _create_layouts(self):
    return {MainState.HOME: CarHomeLayout(), MainState.SETTINGS: CarSettingsLayout(), MainState.ONROAD: CarOnroadView()}

  def _update_layout_rects(self):
    super()._update_layout_rects()
    # car_ui places the status column itself (car_ui.status_layout), outside this layout's rect.
    left_w = self._sidebar_rect.width if self._sidebar.is_visible else 0
    self._content_rect = rl.Rectangle(self._rect.x + left_w, self._rect.y, self._rect.width - left_w, self._rect.height)

  def _render_main_content(self):
    self._update_layout_rects()
    mode_before_sidebar = self._current_mode
    sidebar_visible_before = self._sidebar.is_visible
    if self._sidebar.is_visible:
      self._sidebar.render(self._sidebar_rect)
    if self._current_mode != mode_before_sidebar or self._sidebar.is_visible != sidebar_visible_before:
      return
    self._layouts[self._current_mode].render(self._content_rect if self._sidebar.is_visible else self._rect)

  def _on_bookmark_clicked(self):
    request_bookmark(ui_state.params_memory)

  def render_status(self, rect: rl.Rectangle):
    """The status column, wherever car_ui placed it: an edge, or between the driving view and the map."""
    self._dev_sidebar.update()
    self._dev_sidebar.render(rect)

  def open_starpilot_panel(self, panel_key: str):
    self.open_settings(PanelType.STARPILOT)
    self._layouts[MainState.SETTINGS].open_panel(panel_key)
