import pyray as rl
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.vector_icon import Pen, draw_vector_icon
from openpilot.system.ui.widgets import Widget
from openpilot.selfdrive.ui.lib.mode_banner import ModeBannerVariant, draw_mode_banner_gradient, get_mode_banner_variant
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.common.experimental_state import requested_experimental_mode

CORNER_RADIUS = 18
BACKGROUND = rl.Color(6, 6, 15, 255)  # the car home screen behind the button


def _draw_corner_mask(corner: int, p: Pen) -> None:
  """The area outside a quarter circle on a 64x64 canvas; corner 0-3 is top-left, top-right, bottom-right, bottom-left."""
  tip = ((0.0, 0.0), (64.0, 0.0), (64.0, 64.0), (0.0, 64.0))[corner]
  center = (64.0 - tip[0], 64.0 - tip[1])  # the arc's centre is the opposite corner
  start = 180.0 + 90.0 * corner
  arc = Pen.ellipse(center[0], center[1], 64.0, 64.0, start, start + 90.0, n=48)
  # A fan from the square's corner point covers everything between it and the arc.
  for a, b in zip(arc, arc[1:], strict=False):
    p.fill([tip, a, b])


class ExperimentalModeButton(Widget):
  def __init__(self):
    super().__init__()

    self.img_width = 80
    self.horizontal_padding = 25
    self.button_height = 125

    self.params = ui_state.ui_params
    self.experimental_mode = requested_experimental_mode(self.params, ui_state.params_memory)
    self.mode_variant = get_mode_banner_variant(self.params, ui_state.params_memory)

    self.chill_pixmap = gui_app.texture("icons/couch.png", self.img_width, self.img_width)
    self.experimental_pixmap = gui_app.texture("icons/experimental_grey.png", self.img_width, self.img_width)

  def show_event(self):
    self.experimental_mode = requested_experimental_mode(self.params, ui_state.params_memory)
    self.mode_variant = get_mode_banner_variant(self.params, ui_state.params_memory)

  def _render(self, rect):
    draw_mode_banner_gradient(rect, self.mode_variant, 0xCC if self.is_pressed else 0xFF)
    # The gradient is square. Round it by covering each corner with a cached, supersampled
    # mask in the background colour; the car renderer has no MSAA, so plain arcs are jagged.
    x0, y0 = int(rect.x), int(rect.y)
    x1, y1 = x0 + int(rect.width) - CORNER_RADIUS, y0 + int(rect.height) - CORNER_RADIUS
    for corner, (x, y) in enumerate(((x0, y0), (x1, y0), (x1, y1), (x0, y1))):
      draw_vector_icon(f"exp-mode-corner:{corner}", x, y, CORNER_RADIUS / 64.0, BACKGROUND,
                       lambda px, py, scale, color, corner=corner: _draw_corner_mask(corner, Pen(px, py, scale, color)),
                       canvas=64.0, padding=1)

    # Draw vertical separator line
    line_x = rect.x + rect.width - self.img_width - (2 * self.horizontal_padding)
    separator_color = rl.Color(0, 0, 0, 55)
    rl.draw_line_ex(rl.Vector2(line_x, rect.y), rl.Vector2(line_x, rect.y + rect.height), 2, separator_color)

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
