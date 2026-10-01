"""The car screen's driving view.

CarOnroadView is the comma's StarPilot onroad view with the car's changes layered
on top. It constructs car versions through shared widget factories,
so each widget is initialized and registered once:

  * no favorites radial menu (the car routes onroad touches to its quick menu)
  * the side-camera bubbles cover the bottom alert band, so alerts are drawn after
    them and lane-change banners the bubbles make redundant are dropped
  * a larger labeled lateral-pause badge above the torque bar
  * a compact "Stopped mm:ss" timer in place of the speed, with a smaller
    steering-wheel button moved toward the edge to give it room
  * MAX laid out like the speed-limit card (label at the top edge, large value)
  * with the map beside the road: no turn card (the map shows it larger) and the
    speed-limit sign without its per-source list; without it, the turn card on the
    side the car's Directions Side setting picks
  * the stop / curve gauge tight under the LIMIT card
  * a smaller driver-monitoring icon (the bookmark button is a status-column slot)
  * the camera can be turned off from the car's settings
"""

from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui.onroad.augmented_road_view import CAMERA_VIEW_NONE, AugmentedRoadView
from openpilot.selfdrive.ui.onroad.starpilot.pause_indicators import render_longitudinal_paused
from openpilot.selfdrive.ui.onroad.starpilot.pulse_glide import render_pulse_glide
from openpilot.selfdrive.ui.onroad.starpilot.starpilot_onroad_view import StarPilotOnroadView
from openpilot.selfdrive.ui.onroad.starpilot.weather_icon import render_weather_icon
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.system.starpilot_auto.ui.onroad_widgets import (
  BUBBLE_REDUNDANT_ALERTS,
  DM_SIZE,
  CarAetherGaugeWidget,
  CarAlertRenderer,
  CarDriverMonitorWidget,
  CarDriverStateRenderer,
  CarHudRenderer,
  CarPipSideCamera,
  CarSetSpeedWidget,
  CarSpeedLimitWidget,
  CarStoppedTimerWidget,
  NoFavoriteMenu,
  RIGHT_COLUMN_ANCHOR,
  lateral_pause_rect,
  render_lateral_paused,
)
from openpilot.system.ui.lib.application import gui_app


class CarOnroadView(StarPilotOnroadView):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.layout_manager.right_anchor = RIGHT_COLUMN_ANCHOR

  def _create_hud_renderer(self):
    return CarHudRenderer()

  def _create_alert_renderer(self):
    return CarAlertRenderer()

  def _create_driver_state_renderer(self):
    return CarDriverStateRenderer()

  def _create_driver_monitor_widget(self):
    return CarDriverMonitorWidget(self.driver_state_renderer)

  def _create_aethergauge_widget(self):
    return CarAetherGaugeWidget(self._hud_renderer)

  def _create_pip_sidecam(self):
    return CarPipSideCamera()

  def _create_favorite_menu(self):
    return NoFavoriteMenu()

  def _create_set_speed_widget(self):
    return CarSetSpeedWidget(self._hud_renderer)

  def _create_speed_limit_widget(self):
    return CarSpeedLimitWidget()

  def _create_stopped_timer_widget(self):
    return CarStoppedTimerWidget(self.is_in_reverse)

  def _blind_spot_monitors_visible(self) -> bool:
    return ui_state.starpilot_auto_blind_spot_monitors_visible

  @staticmethod
  def _camera_view() -> int:
    if ui_state.car_camera_off:
      return CAMERA_VIEW_NONE
    return AugmentedRoadView._camera_view()

  def _render(self, rect: rl.Rectangle):
    # Keyed off the last frame's side camera: this frame's alert draws before it decides.
    bubbles_up = self._pip_sidecam.showing
    self.alert_renderer.hidden_alert_names = BUBBLE_REDUNDANT_ALERTS if bubbles_up else frozenset()
    self.alert_renderer.covers = self._pip_sidecam.covers if bubbles_up else None
    self.alert_renderer.deferred = bubbles_up
    try:
      super()._render(rect)
    finally:
      self.alert_renderer.deferred = False
    if bubbles_up and ui_state.started:
      # Alerts go above the side-camera bubbles.
      rl.begin_scissor_mode(
        int(round(self._content_rect.x)), int(round(self._content_rect.y)),
        int(round(self._content_rect.width)), int(round(self._content_rect.height)),
      )
      try:
        self.alert_renderer.render(self._content_rect)
      finally:
        rl.end_scissor_mode()

  def _render_slc(self):
    self._speed_limit_widget.directions_on_left = self._hud_renderer.directions_on_left
    super()._render_slc()

  def _render_bottom_row_widgets(self):
    # Hide if any alert (stock or StarPilot) is active
    alert_showing, _ = self.alert_renderer.will_render()
    if alert_showing is not None:
      return

    starpilot_car_state = ui_state.sm["starpilotCarState"] if ui_state.sm.valid.get("starpilotCarState", False) else None
    plan = ui_state.sm["starpilotPlan"] if ui_state.sm.valid.get("starpilotPlan", False) else None
    lateral_paused = starpilot_car_state.pauseLateral if starpilot_car_state else False
    longitudinal_paused = (starpilot_car_state.pauseLongitudinal or starpilot_car_state.forceCoast) if starpilot_car_state else False

    if lateral_paused:
      render_lateral_paused(lateral_pause_rect(self._content_rect, gui_app.width), self._font_bold)

    dm = self.driver_state_renderer
    # Ensure DM position has been initialized/calculated
    if not dm or dm.position_x == 0.0:
      return

    # DM-adjacent badges in order of priority. Lateral pause has its own badge above.
    active_badges = []
    if longitudinal_paused:
      active_badges.append("longitudinal_paused")
    if starpilot_car_state and starpilot_car_state.pulseAndGlide:
      active_badges.append("pulse_glide")

    badge_w = 120
    badge_h = 72
    spacing = 20
    dm_r = DM_SIZE / 2

    for i, badge in enumerate(active_badges):
      if not dm.is_rhd:
        bx = dm.position_x + dm_r + spacing + i * (badge_w + spacing)
      else:
        bx = dm.position_x - dm_r - spacing - badge_w - i * (badge_w + spacing)

      by = dm.position_y - badge_h / 2
      badge_rect = rl.Rectangle(bx, by, badge_w, badge_h)

      if badge == "longitudinal_paused":
        render_longitudinal_paused(badge_rect)
      elif badge == "pulse_glide":
        pulse_glide_coasting = bool(getattr(plan, "pulseGlideCoasting", False)) if plan else False
        render_pulse_glide(badge_rect, pulse_glide_coasting)

    # Weather, on the opposite side of the DM icon
    if plan and plan.weatherId != 0:
      weather_w = 120
      weather_h = 120
      if not dm.is_rhd:
        wx = self._content_rect.x + self._content_rect.width - 30 - weather_w
      else:
        wx = self._content_rect.x + 30

      cy = dm.position_y - weather_h / 2
      render_weather_icon(rl.Rectangle(wx, cy, weather_w, weather_h))
