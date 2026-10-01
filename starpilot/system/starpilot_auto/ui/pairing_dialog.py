"""Responsive pairing presentation for the car screen."""

import pyray as rl
from openpilot.selfdrive.ui.widgets.pairing_dialog import PairingDialog
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.lib.text_measure import measure_text_cached


class CarPairingDialog(PairingDialog):
  def _render(self, rect: rl.Rectangle) -> int:
    rl.clear_background(rl.Color(6, 6, 15, 255))

    self._check_qr_refresh()

    margin = max(24, int(min(rect.width, rect.height) * 0.04))
    content_rect = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)
    y = content_rect.y

    # Close button container
    close_size = max(64, min(90, int(rect.height * 0.09)))
    close_rect = rl.Rectangle(content_rect.x, y, close_size, close_size)
    
    # Draw button backing
    close_bg = rl.Color(28, 28, 54, 255) if self._close_btn.is_pressed else rl.Color(18, 18, 36, 255)
    close_border = rl.Color(139, 108, 197, 200) if self._close_btn.is_pressed else rl.Color(35, 35, 68, 255)
    rl.draw_rectangle_rounded(close_rect, 0.25, 8, close_bg)
    rl.draw_rectangle_rounded_lines_ex(close_rect, 0.25, 8, 1.5, close_border)
    self._close_btn.render(close_rect)

    y += close_size + max(16, int(rect.height * 0.025))

    # Responsive column split
    left_width = int(content_rect.width * 0.52 - 20)
    right_width = int(content_rect.width - left_width - 40)

    # Title
    title = tr("Pair your device to your comma account")
    title_font = gui_app.font(FontWeight.BOLD)
    title_font_size = max(44, min(64, int(rect.height * 0.06)))

    title_wrapped = wrap_text(title_font, title, title_font_size, left_width)
    title_color = rl.Color(250, 248, 255, 255)
    rl.draw_text_ex(title_font, "\n".join(title_wrapped), rl.Vector2(content_rect.x, y), title_font_size, 0.0, title_color)
    y += len(title_wrapped) * title_font_size + max(24, int(rect.height * 0.03))

    # Two columns: instructions and QR code
    remaining_height = content_rect.height - (y - content_rect.y)

    # Instructions
    self._render_instructions(rl.Rectangle(content_rect.x, y, left_width, remaining_height))

    # QR code container & placement
    qr_max_size = min(right_width, int(content_rect.height * 0.8))
    qr_size = max(200, qr_max_size - 40)
    qr_x = content_rect.x + left_width + 40 + (right_width - qr_size) // 2
    qr_y = content_rect.y + max(20, (content_rect.height - qr_size) // 2)
    self._render_qr_code(rl.Rectangle(qr_x, qr_y, qr_size, qr_size))

    return -1

  def _render_instructions(self, rect: rl.Rectangle) -> None:
    instructions = [
      tr("Go to connect.comma.ai on your phone"),
      tr("Click \"add new device\" and scan the QR code"),
      tr("Bookmark connect.comma.ai to your home screen to use it like an app"),
    ]

    font = gui_app.font(FontWeight.NORMAL)
    bold_font = gui_app.font(FontWeight.BOLD)
    y = rect.y
    inst_font_size = max(32, min(42, int(rect.height * 0.12)))

    step_gap = max(20, int(rect.height * 0.06))

    for i, text in enumerate(instructions):
      circle_radius = max(20, int(inst_font_size * 0.6))
      circle_x = rect.x + circle_radius + 4
      text_x = rect.x + circle_radius * 2 + 24
      text_width = rect.width - (circle_radius * 2 + 30)

      wrapped = wrap_text(font, text, inst_font_size, int(text_width))
      text_height = len(wrapped) * inst_font_size
      circle_y = y + circle_radius + 4

      # Cosmic purple badge for step number
      rl.draw_circle(int(circle_x), int(circle_y), circle_radius, rl.Color(139, 108, 197, 255))
      rl.draw_circle_lines(int(circle_x), int(circle_y), circle_radius + 1, rl.Color(180, 150, 240, 180))
      number = str(i + 1)
      num_font_size = int(circle_radius * 1.2)
      number_size = measure_text_cached(bold_font, number, num_font_size)
      rl.draw_text_ex(bold_font, number, rl.Vector2(circle_x - number_size.x // 2, circle_y - number_size.y // 2), num_font_size, 0, rl.WHITE)

      # Instruction text
      rl.draw_text_ex(font, "\n".join(wrapped), rl.Vector2(text_x, y), inst_font_size, 0.0, rl.Color(220, 218, 235, 255))
      y += text_height + step_gap

  def _render_qr_code(self, rect: rl.Rectangle) -> None:
    # Outer plate with cosmic glow
    pad = 16
    plate_rect = rl.Rectangle(rect.x - pad, rect.y - pad, rect.width + pad * 2, rect.height + pad * 2)
    rl.draw_rectangle_rounded(plate_rect, 0.06, 12, rl.Color(250, 250, 255, 255))
    rl.draw_rectangle_rounded_lines_ex(plate_rect, 0.06, 12, 2.0, rl.Color(139, 108, 197, 200))

    if not self.qr_texture:
      error_font = gui_app.font(FontWeight.BOLD)
      rl.draw_text_ex(
        error_font, tr("QR Code Error"), rl.Vector2(rect.x + 20, rect.y + rect.height // 2 - 15), 30, 0.0, rl.RED
      )
      return

    source = rl.Rectangle(0, 0, self.qr_texture.width, self.qr_texture.height)
    rl.draw_texture_pro(self.qr_texture, source, rect, rl.Vector2(0, 0), 0, rl.WHITE)
