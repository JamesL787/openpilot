import time
import pyray as rl
from openpilot.selfdrive.ui.layouts.home import HomeLayout, HomeLayoutState
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.system.starpilot_auto.ui.home_info_card import CarHomeInfoCard
from openpilot.starpilot.system.starpilot_auto.ui.setup import CarSetupWidget
from openpilot.starpilot.common.starpilot_variables import update_starpilot_toggles
from openpilot.starpilot.system.starpilot_auto.ui.drive_stats import CarDriveStatsDashboard
from openpilot.starpilot.system.starpilot_auto.ui.exp_mode_button import ExperimentalModeButton
from openpilot.starpilot.system.starpilot_auto.ui.offroad_alerts import UpdateAlert, OffroadAlert
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr, trn
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets import Widget

HEADER_HEIGHT = 80
HEAD_BUTTON_FONT_SIZE = 40
CONTENT_MARGIN = 40
SPACING = 25
RIGHT_COLUMN_WIDTH = 750
REFRESH_INTERVAL = 10.0


class CarHomeLayout(HomeLayout):
  """The car screen's home: the comma home restyled for the car, with the Navigate card."""

  def __init__(self):
    self.nav_card: Widget | None = None
    super().__init__()
    self.resume_onroad_rect = rl.Rectangle(0, 0, 360, HEADER_HEIGHT - 10)

  def _create_update_alert(self):
    return UpdateAlert()

  def _create_offroad_alert(self):
    return OffroadAlert()

  def _create_drive_stats(self):
    return CarDriveStatsDashboard(self.params)

  def _create_setup_widget(self):
    return CarSetupWidget()

  def _create_exp_mode_button(self):
    return ExperimentalModeButton()

  def _create_home_info_card(self):
    return CarHomeInfoCard(params=self.params, drive_stats=self._drive_stats)

  def _render(self, rect: rl.Rectangle):
    # Cosmic dark void background
    rl.draw_rectangle_rec(rect, rl.Color(6, 6, 15, 255))

    current_time = time.monotonic()
    if current_time - self.last_refresh >= REFRESH_INTERVAL:
      self._refresh()
      self.last_refresh = current_time

    self._render_header()

    # Render content based on current state
    if self.current_state == HomeLayoutState.HOME:
      self._render_home_content()
    elif self.current_state == HomeLayoutState.UPDATE:
      self._render_update_view()
    elif self.current_state == HomeLayoutState.ALERTS:
      self._render_alerts_view()

  def _update_state(self):
    self.header_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, self._rect.y + CONTENT_MARGIN, self._rect.width - 2 * CONTENT_MARGIN, HEADER_HEIGHT
    )

    content_y = self._rect.y + CONTENT_MARGIN + HEADER_HEIGHT + SPACING
    content_height = self._rect.height - CONTENT_MARGIN - HEADER_HEIGHT - SPACING - CONTENT_MARGIN

    self.content_rect = rl.Rectangle(
      self._rect.x + CONTENT_MARGIN, content_y, self._rect.width - 2 * CONTENT_MARGIN, content_height
    )

    left_width = self.content_rect.width - RIGHT_COLUMN_WIDTH - SPACING

    self.left_column_rect = rl.Rectangle(self.content_rect.x, self.content_rect.y, left_width, self.content_rect.height)

    self.right_column_rect = rl.Rectangle(
      self.content_rect.x + left_width + SPACING, self.content_rect.y, RIGHT_COLUMN_WIDTH, self.content_rect.height
    )

    self.update_notif_rect.x = self.header_rect.x
    self.update_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

    notif_x = self.header_rect.x + (220 if self.update_available else 0)
    self.alert_notif_rect.x = notif_x
    self.alert_notif_rect.y = self.header_rect.y + (self.header_rect.height - 60) // 2

    self.resume_onroad_rect.x = notif_x + (self.alert_notif_rect.width + 20 if self.alert_count > 0 else 0)
    self.resume_onroad_rect.y = self.alert_notif_rect.y

  @staticmethod
  def _force_offroad() -> bool:
    # Only the car screen offers Resume Onroad; the comma screen uses Settings.
    return bool(ui_state.starpilot_toggles.get("force_offroad"))

  def _resume_onroad(self):
    """Clear Force Offroad (from Settings, The Galaxy or the car view's menu) back to Default."""
    self.params.put_bool("ForceOffroad", False)
    self.params.put_bool("ForceOnroad", False)
    ui_state.starpilot_toggles["force_offroad"] = False
    update_starpilot_toggles()

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if self._force_offroad() and rl.check_collision_point_rec(mouse_pos, self.resume_onroad_rect):
      self._resume_onroad()

  def _render_header(self):
    font = gui_app.font(FontWeight.MEDIUM)

    version_text_width = self.header_rect.width

    # Update notification button (Galaxy cosmic purple pill)
    if self.update_available:
      version_text_width -= self.update_notif_rect.width

      is_active = self.current_state == HomeLayoutState.UPDATE
      highlight_color = rl.Color(139, 108, 197, 255) if is_active else rl.Color(117, 88, 176, 255)
      border_color = rl.Color(180, 155, 245, 255) if is_active else rl.Color(150, 120, 220, 180)
      rl.draw_rectangle_rounded(self.update_notif_rect, 0.4, 12, highlight_color)
      rl.draw_rectangle_rounded_lines_ex(self.update_notif_rect, 0.4, 12, 1.5, border_color)

      text = tr("UPDATE")
      text_size = measure_text_cached(font, text, HEAD_BUTTON_FONT_SIZE)
      text_x = self.update_notif_rect.x + (self.update_notif_rect.width - text_size.x) // 2
      text_y = self.update_notif_rect.y + (self.update_notif_rect.height - text_size.y) // 2
      rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

    # Alert notification button (Galaxy nebula rose pill)
    if self.alert_count > 0:
      version_text_width -= self.alert_notif_rect.width

      is_active = self.current_state == HomeLayoutState.ALERTS
      highlight_color = rl.Color(224, 85, 119, 255) if is_active else rl.Color(192, 68, 102, 255)
      border_color = rl.Color(245, 140, 170, 255) if is_active else rl.Color(220, 110, 140, 180)
      rl.draw_rectangle_rounded(self.alert_notif_rect, 0.4, 12, highlight_color)
      rl.draw_rectangle_rounded_lines_ex(self.alert_notif_rect, 0.4, 12, 1.5, border_color)

      alert_text = trn("{} ALERT", "{} ALERTS", self.alert_count).format(self.alert_count)
      text_size = measure_text_cached(font, alert_text, HEAD_BUTTON_FONT_SIZE)
      text_x = self.alert_notif_rect.x + (self.alert_notif_rect.width - text_size.x) // 2
      text_y = self.alert_notif_rect.y + (self.alert_notif_rect.height - text_size.y) // 2
      rl.draw_text_ex(font, alert_text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

    # Resume onroad button (Galaxy aurora green pill), shown on the car view while Force Offroad is on
    force_offroad = self._force_offroad()
    if force_offroad:
      version_text_width -= self.resume_onroad_rect.width + (20 if self.alert_count > 0 else 0)

      rl.draw_rectangle_rounded(self.resume_onroad_rect, 0.4, 12, rl.Color(38, 150, 110, 255))
      rl.draw_rectangle_rounded_lines_ex(self.resume_onroad_rect, 0.4, 12, 1.5, rl.Color(110, 220, 170, 200))

      resume_text = tr("RESUME ONROAD")
      text_size = measure_text_cached(font, resume_text, HEAD_BUTTON_FONT_SIZE)
      text_x = self.resume_onroad_rect.x + (self.resume_onroad_rect.width - text_size.x) // 2
      text_y = self.resume_onroad_rect.y + (self.resume_onroad_rect.height - text_size.y) // 2
      rl.draw_text_ex(font, resume_text, rl.Vector2(int(text_x), int(text_y)), HEAD_BUTTON_FONT_SIZE, 0, rl.WHITE)

    # Version text (right aligned)
    if self.update_available or self.alert_count > 0 or force_offroad:
      version_text_width -= SPACING * 1.5

    version_rect = rl.Rectangle(self.header_rect.x + self.header_rect.width - version_text_width, self.header_rect.y,
                                version_text_width, self.header_rect.height)
    brand_text = "StarPilot"
    detail_text = self._version_text.removeprefix(brand_text)
    brand_font = gui_app.font(FontWeight.BRAND)
    version_font_size = 46

    def _measure_header(font_size: int) -> tuple[rl.Vector2, rl.Vector2]:
      return (measure_text_cached(brand_font, brand_text, font_size + 2),
              measure_text_cached(font, detail_text, font_size))

    brand_size, detail_size = _measure_header(version_font_size)
    total_width = brand_size.x + detail_size.x
    if total_width > version_rect.width:
      version_font_size = max(28, int(version_font_size * version_rect.width / total_width))
      brand_size, detail_size = _measure_header(version_font_size)
      total_width = brand_size.x + detail_size.x

    rendered_width = min(total_width, version_rect.width)
    text_x = version_rect.x + version_rect.width - rendered_width
    brand_rect = rl.Rectangle(text_x, version_rect.y, min(brand_size.x, rendered_width), version_rect.height)
    gui_label(brand_rect, brand_text, version_font_size + 2, rl.Color(250, 248, 255, 255), font_weight=FontWeight.BRAND, elide_right=False)

    detail_width = max(0.0, rendered_width - brand_rect.width)
    if detail_text and detail_width > 0:
      detail_rect = rl.Rectangle(brand_rect.x + brand_rect.width, version_rect.y, detail_width, version_rect.height)
      gui_label(detail_rect, detail_text, version_font_size, rl.Color(160, 160, 195, 255), font_weight=FontWeight.MEDIUM)





  def _render_right_column(self):
    exp_height = 125
    exp_rect = rl.Rectangle(
      self.right_column_rect.x, self.right_column_rect.y, self.right_column_rect.width, exp_height
    )
    self._exp_mode_button.render(exp_rect)

    if self.nav_card is not None:
      top = exp_rect.y + exp_height + SPACING
      self.nav_card.render(rl.Rectangle(self.right_column_rect.x, top, self.right_column_rect.width,
                                        self.right_column_rect.y + self.right_column_rect.height - top))
      return

    top = exp_rect.y + exp_height + SPACING
    setup_rect = rl.Rectangle(
      self.right_column_rect.x,
      top,
      self.right_column_rect.width,
      self.right_column_rect.y + self.right_column_rect.height - top,
    )
    if ui_state.prime_state.is_paired():
      self._home_info_card.render(setup_rect)
    else:
      self._setup_widget.render(setup_rect)
