"""Car-specific setup card and pairing dialog."""

import pyray as rl
from openpilot.selfdrive.ui.widgets.setup import SetupWidget
from openpilot.starpilot.system.starpilot_auto.ui.pairing_dialog import CarPairingDialog
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text


class CarSetupWidget(SetupWidget):
  def _create_pairing_dialog(self):
    return CarPairingDialog()

  def _render_registration(self, rect: rl.Rectangle):
    """Render registration prompt with Galaxy card plate and accent styling."""

    # Galaxy card plate with refined border
    card_rect = rl.Rectangle(rect.x, rect.y, rect.width, rect.height)
    rl.draw_rectangle_rounded(card_rect, 0.04, 16, rl.Color(18, 18, 36, 255))
    rl.draw_rectangle_rounded_lines_ex(card_rect, 0.04, 16, 1.5, rl.Color(35, 35, 68, 255))

    # Cosmic purple top accent bar
    accent_rect = rl.Rectangle(rect.x + 24, rect.y + 12, rect.width - 48, 5)
    rl.draw_rectangle_rounded(accent_rect, 1.0, 8, rl.Color(139, 108, 197, 255))

    x = rect.x + 64
    y = rect.y + 48
    w = rect.width - 128

    # Title
    font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font, tr("Finish Setup"), rl.Vector2(x, y), 75, 0, rl.WHITE)
    y += 113  # 75 + 38 spacing

    # Description
    desc = tr("Pair your device with comma connect (connect.comma.ai) and claim your comma prime offer.")
    light_font = gui_app.font(FontWeight.NORMAL)
    wrapped = wrap_text(light_font, desc, 50, int(w))
    for line in wrapped:
      rl.draw_text_ex(light_font, line, rl.Vector2(x, y), 50, 0, rl.WHITE)
      y += 50 * FONT_SCALE

    button_rect = rl.Rectangle(x, y + 30, w, 200)
    self._pair_device_btn.render(button_rect)
