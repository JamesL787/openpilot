import pyray as rl
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.selfdrive.ui.lib.mode_banner import ModeBannerVariant, draw_mode_banner_gradient, get_mode_banner_variant
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.common.experimental_state import (
  requested_experimental_mode,
  next_manual_ce_status,
  next_manual_cc_status,
  sync_manual_ce_state,
  sync_manual_cc_state,
  CEStatus,
  CCStatus,
)


class ExperimentalModeButton(Widget):
  def __init__(self):
    super().__init__()

    self.img_width = 80
    self.horizontal_padding = 25
    self.button_height = 125

    self.params = Params()
    self.experimental_mode = requested_experimental_mode(self.params, ui_state.params_memory)
    self.mode_variant = get_mode_banner_variant(self.params, ui_state.params_memory)

    self.chill_pixmap = gui_app.texture("icons/couch.png", self.img_width, self.img_width)
    self.experimental_pixmap = gui_app.texture("icons/experimental_grey.png", self.img_width, self.img_width)

    # Set up click callback for toggle behavior
    self.set_click_callback(self._on_toggle)

  def show_event(self):
    self.experimental_mode = requested_experimental_mode(self.params, ui_state.params_memory)
    self.mode_variant = get_mode_banner_variant(self.params, ui_state.params_memory)

  def _on_toggle(self):
    # Handle conditional modes or direct toggle based on which mode is enabled
    if self.params.get_bool("ConditionalExperimental"):
      current_status = ui_state.params_memory.get_int("CEStatus", default=CEStatus["OFF"])
      override_value = next_manual_ce_status(current_status, self.experimental_mode)
      ui_state.params_memory.put_int("CEStatus", override_value)
      sync_manual_ce_state(self.params, override_value)
      self.experimental_mode = override_value == CEStatus["USER_OVERRIDDEN"]
    elif self.params.get_bool("ConditionalChill"):
      current_status = ui_state.params_memory.get_int("CCStatus", default=CCStatus["OFF"])
      override_value = next_manual_cc_status(current_status, self.experimental_mode)
      ui_state.params_memory.put_int("CCStatus", override_value)
      sync_manual_cc_state(self.params, override_value)
      self.experimental_mode = override_value == CCStatus["USER_EXPERIMENTAL"]
    else:
      # Direct toggle for regular experimental mode
      new_mode = not self.experimental_mode
      self.params.put_bool("ExperimentalMode", new_mode)
      self.experimental_mode = new_mode
    self.mode_variant = get_mode_banner_variant(self.params, ui_state.params_memory)

  def _render(self, rect):
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    draw_mode_banner_gradient(rect, self.mode_variant, 0xCC if self.is_pressed else 0xFF)
    rl.draw_rectangle_rounded_lines_ex(self._rect, 0.19, 10, 5, rl.BLACK)
    rl.end_scissor_mode()

    # Draw vertical separator line
    line_x = rect.x + rect.width - self.img_width - (2 * self.horizontal_padding)
    separator_color = rl.Color(0, 0, 0, 77)  # 0x4d = 77
    rl.draw_line_ex(rl.Vector2(line_x, rect.y), rl.Vector2(line_x, rect.y + rect.height), 3, separator_color)

    # Draw text label (left aligned)
    if self.mode_variant == ModeBannerVariant.CONDITIONAL_EXPERIMENTAL:
      text = tr("CONDITIONAL EXPERIMENTAL")
    elif self.mode_variant == ModeBannerVariant.CONDITIONAL_CHILL:
      text = tr("CONDITIONAL CHILL")
    else:
      text = tr("EXPERIMENTAL MODE ON") if self.experimental_mode else tr("CHILL MODE ON")

    text_x = rect.x + self.horizontal_padding
    font = gui_app.font(FontWeight.NORMAL)
    font_size = 45
    available_width = line_x - text_x - self.horizontal_padding
    measured_width = measure_text_cached(font, text, font_size).x
    if measured_width > available_width:
      font_size = max(32, int(font_size * available_width / measured_width))
    text_y = rect.y + rect.height / 2 - font_size * FONT_SCALE // 2  # Center vertically

    rl.draw_text_ex(font, text, rl.Vector2(int(text_x), int(text_y)), font_size, 0, rl.BLACK)

    # Draw icon (right aligned)
    icon_x = rect.x + rect.width - self.horizontal_padding - self.img_width
    icon_y = rect.y + (rect.height - self.img_width) / 2
    icon_rect = rl.Rectangle(icon_x, icon_y, self.img_width, self.img_width)

    # Draw current mode icon
    current_icon = self.experimental_pixmap if self.experimental_mode else self.chill_pixmap
    source_rect = rl.Rectangle(0, 0, current_icon.width, current_icon.height)
    rl.draw_texture_pro(current_icon, source_rect, icon_rect, rl.Vector2(0, 0), 0, rl.WHITE)
