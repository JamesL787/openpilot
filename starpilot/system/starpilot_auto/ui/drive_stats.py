"""Drive statistics on the car screen.

The summary cards share one fitted value size and one label size so the numbers
line up at car-screen sizes, and the record icons are cached vector glyphs: the
car renderer draws without multisampling, so plain lines would be aliased.
"""

import pyray as rl

from openpilot.selfdrive.ui.widgets.drive_stats import (
  MUTED_COLOR,
  PURPLE,
  TEAL,
  TEXT_COLOR,
  TRACK_COLOR,
  DriveStatsDashboard,
  DriveSummary,
)
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.vector_icon import Pen, draw_vector_icon

SUMMARY_SIDE_PADDING = 16
SUMMARY_COLUMN_PADDING = 10
SUMMARY_LABEL_GAP = 4


def _format_thousands(value: float) -> str:
  if value >= 99950:
    return f"{value / 1000:.0f}k"
  return f"{value / 1000:.1f}k"


def _format_count(value: int) -> str:
  if value >= 10000:
    return _format_thousands(value)
  return f"{value:,}"


def _format_decimal(value: float) -> str:
  if value >= 9999.5:
    return _format_thousands(value)
  if value >= 100:
    return f"{value:,.0f}"
  return f"{value:.1f}"


def _draw_record_glyph(index: int, p: Pen) -> None:
  """Personal-record glyphs on a 64x64 canvas."""
  t = 3.0
  if index == 0:  # longest drive: arrow
    p.stroke([(19.0, 32.0), (44.0, 32.0)], t)
    p.stroke([(37.0, 24.5), (44.5, 32.0), (37.0, 39.5)], t)
  elif index == 1:  # completed: check in a circle
    p.circle(32.0, 32.0, 14.0, 2.6)
    p.stroke([(25.5, 32.5), (30.0, 37.0), (39.0, 26.5)], t)
  elif index == 2:  # trend: chart
    p.stroke([(19.0, 19.0), (19.0, 45.0), (45.0, 45.0)], t)
    p.stroke([(24.0, 38.0), (30.5, 30.5), (36.0, 35.0), (45.0, 24.0)], t)
  elif index == 3:  # lightning bolt
    p.stroke([(34.5, 17.0), (22.0, 34.5), (30.0, 34.5), (27.5, 47.0), (42.5, 27.5), (34.5, 27.5)], 2.8, closed=True)
  elif index == 4:  # shield with check
    p.stroke([(32.0, 18.0), (44.0, 23.0), (42.0, 35.0), (32.0, 46.0), (22.0, 35.0), (20.0, 23.0)], 2.8, closed=True)
    p.stroke([(27.0, 32.0), (31.0, 36.0), (38.0, 28.0)], 2.8)
  else:  # sparkles
    for cx, cy, r in ((35.0, 34.0, 11.0), (23.0, 22.0, 5.5), (44.0, 21.0, 4.5)):
      i = r * 0.24
      for tip, left, right in (((cx, cy - r), (cx - i, cy - i), (cx + i, cy - i)),
                               ((cx + r, cy), (cx + i, cy - i), (cx + i, cy + i)),
                               ((cx, cy + r), (cx + i, cy + i), (cx - i, cy + i)),
                               ((cx - r, cy), (cx - i, cy + i), (cx - i, cy - i))):
        p.fill([tip, right, (cx, cy), left])


class CarDriveStatsDashboard(DriveStatsDashboard):
  @staticmethod
  def _draw_record_icon(index: int, rect: rl.Rectangle) -> None:
    rl.draw_rectangle_rounded(rect, 0.18, 8, rl.Color(40, 33, 68, 255))
    s = min(rect.width, rect.height) / 64.0
    draw_vector_icon(f"drive-record:{index}", rect.x, rect.y, s, PURPLE,
                     lambda x, y, scale, color: _draw_record_glyph(index, Pen(x, y, scale, color)), canvas=64.0)

  def _fit_font_size(self, font: rl.Font, texts: list[str], width: float, font_size: int, minimum_size: int) -> int:
    size = font_size
    while size > minimum_size and any(measure_text_cached(font, text, size).x > width for text in texts):
      size -= 1
    return size

  def _draw_centered(self, font: rl.Font, text: str, center_x: float, y: float, font_size: int, color: rl.Color) -> None:
    text_width = measure_text_cached(font, text, font_size).x
    rl.draw_text_ex(font, text, rl.Vector2(center_x - text_width / 2, y), font_size, 0, color)

  @staticmethod
  def _summary_columns(summary: DriveSummary) -> tuple[tuple[str, str], ...]:
    return (
      (_format_count(summary.drives), tr("drives")),
      (_format_decimal(summary.distance), tr("km") if summary.unit == "kilometers" else tr("miles")),
      (_format_decimal(summary.hours), tr("hours")),
    )

  @staticmethod
  def _summary_column_width(card_width: float) -> float:
    return (card_width - 2 * SUMMARY_SIDE_PADDING) / 3

  def _draw_fitted_summary_card(self, rect: rl.Rectangle, title: str, summary: DriveSummary, accent: rl.Color,
                                value_size: int, label_size: int) -> None:
    self._draw_card(rect, accent)
    title_size = self._fit_font_size(self._font_semi_bold, [title], rect.width - 48, 30, 22)
    rl.draw_text_ex(self._font_semi_bold, title, rl.Vector2(rect.x + 24, rect.y + 28), title_size, 0, MUTED_COLOR)

    # Center the value + label group in the space below the title
    content_top = rect.y + 28 + title_size + 6
    content_bottom = rect.y + rect.height - 16
    value_height = measure_text_cached(self._font_bold, "0", value_size).y
    label_height = measure_text_cached(self._font_medium, "0", label_size).y
    group_height = value_height + SUMMARY_LABEL_GAP + label_height
    value_y = content_top + max(0.0, (content_bottom - content_top - group_height) / 2)
    label_y = value_y + value_height + SUMMARY_LABEL_GAP

    column_width = self._summary_column_width(rect.width)
    for index, (value, label) in enumerate(self._summary_columns(summary)):
      column_x = rect.x + SUMMARY_SIDE_PADDING + index * column_width
      if index > 0:
        rl.draw_line_ex(rl.Vector2(column_x, value_y + 6), rl.Vector2(column_x, label_y + label_height - 2), 2, TRACK_COLOR)

      center_x = column_x + column_width / 2
      self._draw_centered(self._font_bold, value, center_x, value_y, value_size, TEXT_COLOR)
      self._draw_centered(self._font_medium, label, center_x, label_y, label_size, MUTED_COLOR)

  def render_overview(self, rect: rl.Rectangle) -> None:
    gap = 18
    summary_height = 184
    card_width = (rect.width - gap) / 2
    summaries = (
      (tr("ALL TIME"), self._data.all_time, PURPLE),
      (tr("PAST WEEK"), self._data.past_week, TEAL),
    )

    # Share one value size and one label size across both cards so the numbers line up
    columns = [column for _, summary, _ in summaries for column in self._summary_columns(summary)]
    fit_width = self._summary_column_width(card_width) - 2 * SUMMARY_COLUMN_PADDING
    value_size = self._fit_font_size(self._font_bold, [value for value, _ in columns], fit_width, 52, 28)
    label_size = self._fit_font_size(self._font_medium, [label for _, label in columns], fit_width, 24, 18)

    for index, (title, summary, accent) in enumerate(summaries):
      card_rect = rl.Rectangle(rect.x + index * (card_width + gap), rect.y, card_width, summary_height)
      self._draw_fitted_summary_card(card_rect, title, summary, accent, value_size, label_size)

    graph_rect = rl.Rectangle(rect.x, rect.y + summary_height + gap, rect.width, rect.height - summary_height - gap)
    self._draw_distance_graph(graph_rect)
