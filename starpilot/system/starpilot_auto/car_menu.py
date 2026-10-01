"""The car view's small onroad button: Navigate, end the route, home screen, back to driving, go offroad.

Onroad the car view ignores taps on the driving view itself; this button and its
menu are what it accepts instead, so a stray touch never changes anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

BUTTON_SIZE = 84.0
MARGIN = 28.0
PANEL_WIDTH = 600.0
ROW_HEIGHT = 96.0

PANEL_BG = rl.Color(12, 15, 24, 250)
PANEL_BORDER = rl.Color(255, 255, 255, 30)
ROW_PRESSED = rl.Color(255, 255, 255, 22)
DIVIDER = rl.Color(255, 255, 255, 18)
TEXT = rl.Color(240, 244, 250, 255)
SUBTEXT = rl.Color(160, 170, 186, 255)
ACCENT = rl.Color(64, 150, 255, 255)
DANGER = rl.Color(236, 96, 110, 255)
BUTTON_BG = rl.Color(12, 15, 24, 170)


@dataclass
class MenuRow:
  key: str
  title: str
  subtitle: str = ""
  color: rl.Color = TEXT
  enabled: bool = True


class CarQuickMenu(Widget):
  def __init__(self, *, go_home: Callable[[], None], go_driving: Callable[[], None],
               open_navigate: Callable[[], None], cancel_navigation: Callable[[], None],
               go_offroad: Callable[[], None] | None = None, on_open: Callable[[], None] | None = None):
    super().__init__()
    self._on_open = on_open  # refresh navigation state before the rows are shown
    self._go_home = go_home
    self._go_driving = go_driving
    self._open_navigate = open_navigate
    self._cancel_navigation = cancel_navigation
    self._go_offroad = go_offroad
    self._font_bold = self._font_medium = None  # loaded on first draw
    self.open = False
    self.on_home = False
    self.nav_active = False
    self.destination_name = ""
    self.routing_ok = True
    self.locked_text = ""  # why Navigate can't be opened right now (moving too fast)
    self.parked = False  # Go offroad needs the car in Park
    self.confirming_offroad = False
    # Bottom-left over the drive; bottom-right on the home screen, where the sidebar's
    # flag button owns the bottom-left corner.
    self.corner = "left"
    self._screen = rl.Rectangle(0, 0, 0, 0)
    self._pressed_key: str | None = None

  # ── geometry ──────────────────────────────────────────────────────────────

  def button_rect(self, screen: rl.Rectangle) -> rl.Rectangle:
    x = screen.x + MARGIN if self.corner == "left" else screen.x + screen.width - MARGIN - BUTTON_SIZE
    return rl.Rectangle(x, screen.y + screen.height - MARGIN - BUTTON_SIZE, BUTTON_SIZE, BUTTON_SIZE)

  def rows(self) -> list[MenuRow]:
    if self.confirming_offroad:
      return [MenuRow("offroad_prompt", "Go offroad?", "Resume from the home screen when ready", TEXT, False),
              MenuRow("offroad_confirm", "Go offroad", color=DANGER),
              MenuRow("offroad_cancel", "Cancel")]
    if not self.routing_ok:
      rows = [MenuRow("navigate", "Navigate", "Add a Mapbox secret key in The Galaxy", SUBTEXT, False)]
    elif self.locked_text:
      rows = [MenuRow("navigate", "Navigate", self.locked_text, SUBTEXT, False)]
    elif self.nav_active:
      rows = [MenuRow("navigate", "Navigate", f"To {self.destination_name} • tap to change" if self.destination_name else "Change destination", ACCENT)]
    else:
      rows = [MenuRow("navigate", "Navigate", "Search, favorites and recent places", ACCENT)]
    if self.nav_active:
      # Ending a route never needs the car to slow down.
      rows.append(MenuRow("cancel", "End route", color=DANGER))
    rows.append(MenuRow("driving", "Back to driving") if self.on_home else MenuRow("home", "Home screen"))
    if self._go_offroad is not None:
      if self.parked:
        rows.append(MenuRow("offroad", "Go offroad", "Force the comma offroad", DANGER))
      else:
        rows.append(MenuRow("offroad", "Go offroad", "Shift into Park first", SUBTEXT, False))
    return rows

  def panel_rect(self, screen: rl.Rectangle) -> rl.Rectangle:
    height = len(self.rows()) * ROW_HEIGHT
    button = self.button_rect(screen)
    width = min(PANEL_WIDTH, screen.width - 2 * MARGIN)
    x = button.x if self.corner == "left" else button.x + BUTTON_SIZE - width
    return rl.Rectangle(x, button.y - 16 - height, width, height)

  def captures(self, x: float, y: float, screen: rl.Rectangle) -> bool:
    """Whether a touch starting here belongs to the menu. While open it takes every touch
    (a tap outside closes it) so nothing reaches the driving view underneath."""
    return self.open or rl.check_collision_point_rec(rl.Vector2(x, y), self.button_rect(screen))

  # ── input ─────────────────────────────────────────────────────────────────

  def _key_at(self, pos) -> str | None:
    point = rl.Vector2(pos.x, pos.y)
    if rl.check_collision_point_rec(point, self.button_rect(self._screen)):
      return "button"
    if not self.open:
      return None
    panel = self.panel_rect(self._screen)
    if not rl.check_collision_point_rec(point, panel):
      return "outside"
    index = int((pos.y - panel.y) // ROW_HEIGHT)
    rows = self.rows()
    return rows[index].key if 0 <= index < len(rows) and rows[index].enabled else "inert"

  def _handle_mouse_press(self, mouse_pos) -> None:
    self._pressed_key = self._key_at(mouse_pos)

  def _handle_mouse_release(self, mouse_pos) -> None:
    key = self._key_at(mouse_pos)
    pressed, self._pressed_key = self._pressed_key, None
    if key is None or key != pressed:
      return
    self.activate(key)

  def activate(self, key: str) -> None:
    if key == "button":
      self.open = not self.open
      self.confirming_offroad = False
      if self.open and self._on_open is not None:
        self._on_open()
    elif key == "outside":
      self.close()
    elif key == "home":
      self.close()
      self._go_home()
    elif key == "driving":
      self.close()
      self._go_driving()
    elif key == "navigate":
      self.close()
      self._open_navigate()
    elif key == "cancel":
      self.close()
      self._cancel_navigation()
    elif key == "offroad" and self.parked:
      self.confirming_offroad = True
    elif key == "offroad_cancel":
      self.confirming_offroad = False
    elif key == "offroad_confirm":
      self.close()
      if self.parked and self._go_offroad is not None:
        self._go_offroad()

  def close(self) -> None:
    self.open = False
    self.confirming_offroad = False

  # ── drawing ───────────────────────────────────────────────────────────────

  def _render(self, rect: rl.Rectangle) -> None:
    if self._font_bold is None:
      self._font_bold = gui_app.font(FontWeight.BOLD)
      self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._screen = rect
    button = self.button_rect(rect)
    center = rl.Vector2(button.x + BUTTON_SIZE / 2, button.y + BUTTON_SIZE / 2)
    rl.draw_circle_v(center, BUTTON_SIZE / 2, BUTTON_BG)
    rl.draw_circle_lines_v(center, BUTTON_SIZE / 2, PANEL_BORDER)
    color = ACCENT if self.open else rl.Color(255, 255, 255, 200)
    # Three dots: a quiet "more" glyph that doesn't compete with the driving view.
    for dx in (-18, 0, 18):
      rl.draw_circle_v(rl.Vector2(center.x + dx, center.y), 5.5, color)

    if not self.open:
      return
    panel = self.panel_rect(rect)
    rl.draw_rectangle_rounded(panel, 18.0 / max(panel.height, 1.0), 10, PANEL_BG)
    rl.draw_rectangle_rounded_lines_ex(panel, 18.0 / max(panel.height, 1.0), 10, 2, PANEL_BORDER)
    for index, row in enumerate(self.rows()):
      row_rect = rl.Rectangle(panel.x, panel.y + index * ROW_HEIGHT, panel.width, ROW_HEIGHT)
      if self._pressed_key == row.key and row.enabled:
        rl.draw_rectangle_rec(row_rect, ROW_PRESSED)
      if index:
        rl.draw_line_ex(rl.Vector2(row_rect.x + 24, row_rect.y), rl.Vector2(row_rect.x + row_rect.width - 24, row_rect.y), 1, DIVIDER)
      title_size, sub_size = 38, 26
      text_x = row_rect.x + 30
      max_width = row_rect.width - 60
      title = self._fit(self._font_bold, row.title, title_size, max_width)
      if row.subtitle:
        rl.draw_text_ex(self._font_bold, title, rl.Vector2(text_x, row_rect.y + 14), title_size, 0, row.color)
        subtitle = self._fit(self._font_medium, row.subtitle, sub_size, max_width)
        rl.draw_text_ex(self._font_medium, subtitle, rl.Vector2(text_x, row_rect.y + 58), sub_size, 0, SUBTEXT)
      else:
        rl.draw_text_ex(self._font_bold, title, rl.Vector2(text_x, row_rect.y + (ROW_HEIGHT - title_size) / 2), title_size, 0, row.color)

  @staticmethod
  def _fit(font, text: str, size: int, width: float) -> str:
    if measure_text_cached(font, text, size).x <= width:
      return text
    while text and measure_text_cached(font, text + "...", size).x > width:
      text = text[:-1]
    return text.rstrip() + "..."
