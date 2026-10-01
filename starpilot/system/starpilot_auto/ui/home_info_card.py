"""Car home card glyphs, sharing the card's data and interaction logic."""

import pyray as rl
from openpilot.selfdrive.ui.widgets.home_info_card import HomeInfoCard, TEAL, MUTED_COLOR
from openpilot.system.ui.lib.vector_icon import draw_strokes


class CarHomeInfoCard(HomeInfoCard):
  @staticmethod
  def _draw_checkmark(center_x: float, center_y: float, scale: float = 1.0) -> None:
    draw_strokes([([(center_x - 14 * scale, center_y), (center_x - 3 * scale, center_y + 11 * scale),
                    (center_x + 16 * scale, center_y - 12 * scale)], 4 * scale)], TEAL, "home-check")

  @staticmethod
  def _draw_page_icon(rect: rl.Rectangle) -> None:
    center_x = rect.x + rect.width / 2
    center_y = rect.y + rect.height / 2
    thickness = 3.0
    draw_strokes([
      ([(center_x - 16, center_y - 7), (center_x + 14, center_y - 7)], thickness),
      ([(center_x + 6, center_y - 14), (center_x + 14, center_y - 7), (center_x + 6, center_y)], thickness),
      ([(center_x + 16, center_y + 8), (center_x - 14, center_y + 8)], thickness),
      ([(center_x - 6, center_y + 1), (center_x - 14, center_y + 8), (center_x - 6, center_y + 15)], thickness),
    ], MUTED_COLOR, "home-page")
