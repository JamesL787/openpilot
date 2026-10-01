"""Starting a route on the car view.

CarNavigateCard sits on the car's home screen: pick Home or Work, press Start, and the
drive opens in the chosen car screen layout. "Other destination" opens
CarNavigateScreen, which fills the car screen: search, favorites and recent
destinations on the left, the route preview on the right. Tapping the search field
puts a keyboard where the map was and suggestions follow the typing. Starting a
route (or the Back button) returns to where the driver was.

Onroad a destination can only be set below NAV_UNLOCK_MPH, measured by the car's own
wheel speed; the Navigate screen closes by itself if the car goes faster. A Desktop
Head Unit session (car_screen.DHU_ENV, set by tools/starpilot_auto/dhu_device.py) pins the speed
below the limit, since a comma on a desk has no wheel speed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

NAV_UNLOCK_MPH = 10.0
MPH_TO_MS = 0.44704

PAD = 32.0
TOP_BAR = 140.0
ROUND_BUTTON = 80.0
SEARCH_HEIGHT = 92.0
SECTION_HEIGHT = 64.0
ROW_HEIGHT = 104.0
ROW_GAP = 6.0
ICON = 56.0
CHIP_HEIGHT = 60.0
DRAG_SLOP = 18.0
PANEL_RADIUS = 24.0

SCREEN_BG = rl.Color(6, 6, 15, 255)
TEXT = rl.Color(248, 248, 255, 255)
SUBTEXT = rl.Color(160, 160, 191, 255)
ACCENT = rl.Color(145, 96, 255, 255)
ACCENT_BORDER = rl.Color(139, 92, 246, 210)
ACCENT_SURFACE = rl.Color(33, 24, 62, 255)
START = rl.Color(52, 199, 137, 255)
DANGER = rl.Color(224, 85, 119, 255)
WARNING = rl.Color(212, 160, 96, 255)
CARD_BG = rl.Color(14, 12, 23, 255)
CARD_BORDER = rl.Color(58, 42, 106, 255)
TILE_BG = rl.Color(18, 18, 36, 255)
TILE_PRESSED = rl.Color(28, 28, 54, 255)
ROUND_BG = rl.Color(18, 18, 36, 255)
DIVIDER = rl.Color(58, 42, 106, 120)

# The Navigate screen's keyboard: (key, width in key units) per row. "back" deletes a letter.
KEY_ROWS = (
  tuple((key, 1) for key in "1234567890"),
  tuple((key, 1) for key in "qwertyuiop"),
  tuple((key, 1) for key in "asdfghjkl"),
  (*((key, 1) for key in "zxcvbnm."), ("back", 2)),
  (("-", 1), (",", 1), ("'", 1), ("&", 1), ("space", 4), ("done", 2)),
)
KEY_GAP = 12.0
KEY_PAD = 24.0
KEY_MAX_HEIGHT = 124.0
MAX_QUERY_LENGTH = 80


def fit_text(font, text: str, size: int, width: float) -> str:
  """Shorten text with an ellipsis to fit width."""
  if width <= 0:
    return ""
  if measure_text_cached(font, text, size).x <= width:
    return text
  while text and measure_text_cached(font, text + "…", size).x > width:
    text = text[:-1]
  return text.rstrip(" ,") + "…"


def draw_chevron(x: float, y: float, color, *, left: bool = False, size: float = 16.0, thickness: float = 5.0) -> None:
  tip = x - size * 0.75 if left else x + size * 0.75
  rl.draw_line_ex(rl.Vector2(x, y - size), rl.Vector2(tip, y), thickness, color)
  rl.draw_line_ex(rl.Vector2(tip, y), rl.Vector2(x, y + size), thickness, color)


def speed_allows_navigation(started: bool, speed_ms: float | None) -> bool:
  """Destinations can be set offroad, or onroad below NAV_UNLOCK_MPH of wheel speed.
  An unknown speed onroad (no recent carState) counts as moving."""
  if not started:
    return True
  return speed_ms is not None and abs(speed_ms) < NAV_UNLOCK_MPH * MPH_TO_MS


def locked_text() -> str:
  return tr("Slow below {} mph to set a destination").format(int(NAV_UNLOCK_MPH))


@dataclass
class ListRow:
  target: str  # the Navigation page's target id: "result:0", "favorite:<id>", "recent:2"
  kind: str  # "result", "favorite" or "recent"
  title: str
  subtitle: str = ""
  badge: str = ""
  selected: bool = False


def _place_detail(place: dict, title: str) -> str:
  detail = str(place.get("place_name") or place.get("address") or "").strip()
  return "" if detail.casefold() == title.casefold() else detail


class CarNavigateScreen(Widget):
  """Full-screen destination picker for the car.

  The car's Navigation page (CarNavigationLayout) does the work: search,
  route previews, favorites and starting the route. This screen only draws it for a
  car screen and turns taps into the page's target ids.

  Tapping the search field swaps the map for a keyboard drawn here (no full-screen
  dialog): suggestions fill the list as the driver types, and picking one brings the
  map back with its route preview.
  """

  def __init__(self, on_started: Callable[[], None], on_close: Callable[[], None], on_offline_maps: Callable[[], None]):
    super().__init__()
    from openpilot.starpilot.system.starpilot_auto.ui.navigation import CarNavigationLayout
    self._on_close = on_close
    self._on_offline_maps = on_offline_maps
    self.page = CarNavigationLayout(on_started=on_started)
    self.searching = False  # the keyboard is up in place of the map
    self.typed = ""         # the search field's text while searching
    self.scroll = 0.0
    self._content_height = 0.0
    self._list_rect = rl.Rectangle(0, 0, 0, 0)
    self._targets: list[tuple[str, rl.Rectangle, bool]] = []  # (target, rect, in the scrolling list)
    self._pressed: str | None = None
    self._press_y = 0.0
    self._last_y = 0.0
    self._dragging = False
    self._last_query = ""
    self._fonts: dict = {}

  def show_event(self):
    super().show_event()
    self.page.show_event()
    self.scroll = 0.0
    self.searching, self.typed = False, ""

  def hide_event(self):
    super().hide_event()
    self.page.hide_event()

  # ── the page's state, shaped for the car ──────────────────────────────────

  def _typed_query(self) -> str:
    return self.typed.strip() if self.searching else ""

  def list_rows(self) -> list[tuple[str, list[ListRow]]]:
    """(section title, rows) for the scrolling list. While typing, saved places that match
    the text show at once under Mapbox's suggestions."""
    from openpilot.starpilot.navigation.destination_store import ordered_favorite_destinations
    page = self.page
    draft = page._draft_destination
    typed = self._typed_query().casefold()
    sections = []
    if page._search_results and (not self.searching or typed):
      rows = [ListRow(f"result:{i}", "result", r.name, r.subtitle,
                      selected=r.has_coordinates and page._same_destination(draft, r.to_destination()))
              for i, r in enumerate(page._search_results)]
      sections.append((tr("Suggestions") if self.searching else tr("Results"), rows))

    def matches(place: dict) -> bool:
      return not typed or any(typed in str(place.get(key) or "").casefold() for key in ("name", "place_name", "address"))

    favorite_rows, recent_rows = [], []
    for favorite in ordered_favorite_destinations(page._favorites):
      if matches(favorite):
        title = str(favorite.get("name") or tr("Saved place"))
        badge = tr("Home") if favorite.get("is_home") else tr("Work") if favorite.get("is_work") else ""
        favorite_rows.append(ListRow(f"favorite:{favorite.get('id')}", "favorite", title, _place_detail(favorite, title), badge,
                                     page._same_destination(draft, favorite)))
    for index, recent in enumerate(page._recent_destinations):
      if matches(recent):
        title = str(recent.get("name") or recent.get("place_name") or tr("Recent place"))
        recent_rows.append(ListRow(f"recent:{index}", "recent", title, _place_detail(recent, title),
                                   selected=page._same_destination(draft, recent)))
    if typed:
      if favorite_rows or recent_rows:
        sections.append((tr("Saved places"), favorite_rows + recent_rows))
    else:
      if favorite_rows:
        sections.append((tr("Favorites"), favorite_rows))
      if recent_rows:
        sections.append((tr("Recent"), recent_rows))
    return sections

  def notice(self) -> tuple[str, str, rl.Color] | None:
    """(title, body, colour) of a message above the list, if any."""
    page = self.page
    rows = self.list_rows()
    if page._search_error:
      return tr("Search unavailable"), page._search_error, WARNING
    if page._search_loading and not rows:
      return tr("Searching…"), page._query, SUBTEXT
    if rows:
      return None
    typed = self._typed_query()
    if self.searching and len(typed) < 3:
      if typed:
        return tr("Keep typing"), tr("Suggestions appear after 3 letters."), SUBTEXT
      return tr("Where to?"), tr("Type a place, business or address."), SUBTEXT
    if page._query or typed:
      return tr("No matches"), tr("Try a different place or address."), SUBTEXT
    return tr("No places yet"), tr("Search for a place or address to begin."), SUBTEXT

  def route_chips(self) -> list[tuple[str, str, bool]]:
    """(target, label, selected) per previewed route, when there's a choice."""
    page = self.page
    if len(page._preview_routes) < 2:
      return []
    chips = []
    for index, route in enumerate(page._preview_routes):
      name = tr("Fastest") if index == 0 else tr("Route {}").format(index + 1)
      chips.append((f"route:{index}", f"{name} · {page._duration_text(route.total_duration)}", index == page._preview_route_index))
    return chips

  def favorite_chips(self) -> list[tuple[str, str, bool]]:
    page = self.page
    favorite = page._selected_favorite or page._favorite_for_destination(page._draft_destination)
    return [
      ("action:favorite", tr("Saved") if favorite else tr("Save"), favorite is not None),
      ("action:home", tr("Home"), bool(favorite and favorite.get("is_home"))),
      ("action:work", tr("Work"), bool(favorite and favorite.get("is_work"))),
    ]

  def route_summary(self) -> tuple[str, rl.Color]:
    from openpilot.selfdrive.ui.onroad.starpilot.navigation_card import _format_distance
    from openpilot.selfdrive.ui.ui_state import ui_state
    page = self.page
    if page._routes_loading:
      return tr("Finding routes…"), SUBTEXT
    if page._routes_error:
      return page._routes_error, WARNING
    if not page._routing_available():
      return tr("Add a Mapbox secret key in The Galaxy to navigate"), WARNING
    if page._preview_routes:
      route = page._preview_routes[page._preview_route_index]
      return f"{page._duration_text(route.total_duration)} · {_format_distance(route.total_distance, ui_state.is_metric)}", TEXT
    return tr("Route preview needs a GPS fix"), SUBTEXT

  def activate(self, target: str) -> None:
    if target == "back":
      if self.searching:
        self.searching = False  # Back puts the keyboard away first
      else:
        self._on_close()
    elif target == "offline_maps":
      self._on_offline_maps()
    elif target == "action:search":
      if not self.searching:
        self.searching, self.typed = True, self.page._query
    elif target.startswith("key:"):
      self._key(target[4:])
    else:
      if target.split(":", 1)[0] in ("result", "favorite", "recent"):
        self.searching = False  # a place was picked: back to the map and its route preview
      self.page._activate_navigation_target(target)

  def _key(self, key: str) -> None:
    if key == "done":
      self.searching = False
      self.page.set_live_query(self.typed, immediate=True)
      return
    if key == "back":
      self.typed = self.typed[:-1]
    elif key == "clear":
      self.typed = ""
    elif key == "space":
      if self.typed and not self.typed.endswith(" "):
        self.typed += " "
    elif len(self.typed) < MAX_QUERY_LENGTH:
      self.typed += key
    self.page.set_live_query(self.typed)

  # ── input ─────────────────────────────────────────────────────────────────

  def _target_at(self, x: float, y: float) -> str | None:
    point = rl.Vector2(x, y)
    for target, area, scrolled in reversed(self._targets):
      if scrolled and not rl.check_collision_point_rec(point, self._list_rect):
        continue
      if rl.check_collision_point_rec(point, area):
        return target
    return None

  def _max_scroll(self) -> float:
    return max(0.0, self._content_height - self._list_rect.height)

  def _handle_mouse_press(self, mouse_pos) -> None:
    self._pressed = self._target_at(mouse_pos.x, mouse_pos.y)
    self._press_y = self._last_y = mouse_pos.y
    self._dragging = False

  def _handle_mouse_event(self, mouse_event) -> None:
    if not mouse_event.left_down or mouse_event.left_pressed:
      return
    y = mouse_event.pos.y
    in_list = rl.check_collision_point_rec(rl.Vector2(mouse_event.pos.x, self._press_y), self._list_rect)
    if in_list and (self._dragging or abs(y - self._press_y) > DRAG_SLOP):
      self._dragging = True
      self._pressed = None
      self.scroll = min(self._max_scroll(), max(0.0, self.scroll - (y - self._last_y)))
    self._last_y = y

  def _handle_mouse_release(self, mouse_pos) -> None:
    pressed, self._pressed = self._pressed, None
    if not self._dragging and pressed is not None and self._target_at(mouse_pos.x, mouse_pos.y) == pressed:
      self.activate(pressed)
    self._dragging = False

  # ── drawing ───────────────────────────────────────────────────────────────

  def _font(self, weight: FontWeight):
    if weight not in self._fonts:
      self._fonts[weight] = gui_app.font(weight)
    return self._fonts[weight]

  def _target(self, target: str, area: rl.Rectangle, scrolled: bool = False) -> bool:
    """Register a tap target; returns whether it's being pressed."""
    self._targets.append((target, area, scrolled))
    return self._pressed == target

  def _render(self, rect: rl.Rectangle) -> None:
    self.page._update_state()  # consume search and route results; the page itself isn't rendered
    if self.page._query != self._last_query:
      self._last_query, self.scroll = self.page._query, 0.0
    self._targets = []
    rl.draw_rectangle_rec(rect, SCREEN_BG)
    list_w = min(820.0, max(620.0, rect.width * 0.43))
    self._draw_top_bar(rect, list_w)
    body_y = rect.y + TOP_BAR
    body_h = rect.y + rect.height - PAD - body_y
    self._draw_list_column(rl.Rectangle(rect.x + PAD, body_y, list_w, body_h))
    side_x = rect.x + PAD + list_w + 32
    side = rl.Rectangle(side_x, body_y, rect.x + rect.width - PAD - side_x, body_h)
    if self.searching:
      self._draw_keyboard(side)
    else:
      self._draw_map_panel(side)

  def _draw_top_bar(self, rect: rl.Rectangle, list_w: float) -> None:
    medium = self._font(FontWeight.MEDIUM)
    back = rl.Rectangle(rect.x + PAD, rect.y + (TOP_BAR - ROUND_BUTTON) / 2, ROUND_BUTTON, ROUND_BUTTON)
    pressed = self._target("back", back)
    center = rl.Vector2(back.x + ROUND_BUTTON / 2, back.y + ROUND_BUTTON / 2)
    rl.draw_circle_v(center, ROUND_BUTTON / 2, TILE_PRESSED if pressed else ROUND_BG)
    draw_chevron(center.x + 5, center.y, TEXT, left=True)

    # Offline maps live in Settings; this is the car's way there.
    label = tr("Offline maps")
    width = measure_text_cached(medium, label, 28).x + 104
    button = rl.Rectangle(rect.x + rect.width - PAD - width, rect.y + (TOP_BAR - SEARCH_HEIGHT) / 2, width, SEARCH_HEIGHT)
    pressed = self._target("offline_maps", button)
    rl.draw_rectangle_rounded(button, 0.5, 12, TILE_PRESSED if pressed else TILE_BG)
    arrow = rl.Vector2(button.x + 42, button.y + SEARCH_HEIGHT / 2)  # download glyph: an arrow into a tray
    rl.draw_line_ex(rl.Vector2(arrow.x, arrow.y - 16), rl.Vector2(arrow.x, arrow.y + 6), 4, SUBTEXT)
    rl.draw_line_ex(rl.Vector2(arrow.x - 9, arrow.y - 3), rl.Vector2(arrow.x, arrow.y + 7), 4, SUBTEXT)
    rl.draw_line_ex(rl.Vector2(arrow.x + 9, arrow.y - 3), rl.Vector2(arrow.x, arrow.y + 7), 4, SUBTEXT)
    rl.draw_line_ex(rl.Vector2(arrow.x - 14, arrow.y + 16), rl.Vector2(arrow.x + 14, arrow.y + 16), 4, SUBTEXT)
    rl.draw_text_ex(medium, label, rl.Vector2(button.x + 72, button.y + (SEARCH_HEIGHT - 28) / 2), 28, 0, TEXT)

    field_x = back.x + ROUND_BUTTON + 24
    field = rl.Rectangle(field_x, rect.y + (TOP_BAR - SEARCH_HEIGHT) / 2, button.x - 24 - field_x, SEARCH_HEIGHT)
    self._draw_search_field(field)

  def _draw_search_field(self, field: rl.Rectangle) -> None:
    medium = self._font(FontWeight.MEDIUM)
    page = self.page
    pressed = self._target("action:search", field)
    active = self.searching
    rl.draw_rectangle_rounded(field, 0.5, 16, TILE_PRESSED if pressed else TILE_BG)
    if active:
      rl.draw_rectangle_rounded_lines_ex(field, 0.5, 16, 3, ACCENT_BORDER)
    glass = rl.Vector2(field.x + 48, field.y + SEARCH_HEIGHT / 2 - 4)
    glass_color = ACCENT if active or pressed else SUBTEXT
    rl.draw_ring(glass, 11, 16, 0, 360, 24, glass_color)
    rl.draw_line_ex(rl.Vector2(glass.x + 11, glass.y + 11), rl.Vector2(glass.x + 22, glass.y + 22), 5, glass_color)

    right = field.x + field.width - 24
    text = self.typed if active else page._query
    if active and self.typed:
      clear = rl.Rectangle(field.x + field.width - 84, field.y + (SEARCH_HEIGHT - 64) / 2, 64, 64)
      clear_pressed = self._target("key:clear", clear)
      c = rl.Vector2(clear.x + 32, clear.y + 32)
      rl.draw_circle_v(c, 22, TILE_PRESSED if clear_pressed else rl.Color(SUBTEXT.r, SUBTEXT.g, SUBTEXT.b, 60))
      rl.draw_line_ex(rl.Vector2(c.x - 8, c.y - 8), rl.Vector2(c.x + 8, c.y + 8), 3, TEXT)
      rl.draw_line_ex(rl.Vector2(c.x + 8, c.y - 8), rl.Vector2(c.x - 8, c.y + 8), 3, TEXT)
      right = clear.x - 12
    if page._search_loading:
      status = tr("Searching…")
      status_w = measure_text_cached(medium, status, 24).x
      rl.draw_text_ex(medium, status, rl.Vector2(right - status_w, field.y + (SEARCH_HEIGHT - 24) / 2), 24, 0, SUBTEXT)
      right -= status_w + 16
    text_x = field.x + 88
    width = right - text_x
    if text:
      shown = text
      if measure_text_cached(medium, shown, 34).x > width:  # typing: keep the end in view
        while shown and measure_text_cached(medium, "…" + shown, 34).x > width:
          shown = shown[1:]
        shown = "…" + shown
      rl.draw_text_ex(medium, shown, rl.Vector2(text_x, field.y + (SEARCH_HEIGHT - 34) / 2), 34, 0, TEXT)
      end_x = text_x + measure_text_cached(medium, shown, 34).x
    else:
      placeholder = tr("Search for a place or address")
      rl.draw_text_ex(medium, fit_text(medium, placeholder, 34, width), rl.Vector2(text_x, field.y + (SEARCH_HEIGHT - 34) / 2),
                      34, 0, SUBTEXT)
      end_x = text_x - 4
    if active and int(rl.get_time() * 2) % 2 == 0:  # caret
      rl.draw_rectangle_rec(rl.Rectangle(end_x + 4, field.y + 24, 3, SEARCH_HEIGHT - 48), ACCENT)

  def _draw_list_column(self, column: rl.Rectangle) -> None:
    bold, medium = self._font(FontWeight.BOLD), self._font(FontWeight.MEDIUM)
    self._list_rect = column
    view = column
    rl.begin_scissor_mode(int(view.x), int(view.y), int(view.width), int(view.height))
    y = view.y - self.scroll
    notice = self.notice()
    if notice is not None:
      title, body, color = notice
      icon = rl.Vector2(view.x + 34, y + 58)
      rl.draw_circle_v(icon, 22, rl.Color(color.r, color.g, color.b, 35))
      rl.draw_circle_v(icon, 6, color)
      text_x = view.x + 78
      rl.draw_text_ex(bold, fit_text(bold, title, 32, view.width - 90), rl.Vector2(text_x, y + 24), 32, 0, color)
      rl.draw_text_ex(medium, fit_text(medium, body, 26, view.width - 90), rl.Vector2(text_x, y + 68), 26, 0, SUBTEXT)
      y += 124
    for title, rows in self.list_rows():
      rl.draw_text_ex(bold, title.upper(), rl.Vector2(view.x + 8, y + (SECTION_HEIGHT - 24) / 2 + 6), 24, 1.8, SUBTEXT)
      y += SECTION_HEIGHT
      for index, row in enumerate(rows):
        self._draw_row(row, rl.Rectangle(view.x, y, view.width, ROW_HEIGHT), last=index == len(rows) - 1)
        y += ROW_HEIGHT + ROW_GAP
      y += 8
    rl.end_scissor_mode()
    self._content_height = y + self.scroll - view.y + 12
    self.scroll = min(self.scroll, self._max_scroll())

    if self._max_scroll() > 0:
      # A thin bar shows there's more below.
      track = view.height - 16
      bar_h = max(60.0, track * view.height / self._content_height)
      bar_y = view.y + 8 + (track - bar_h) * self.scroll / self._max_scroll()
      rl.draw_rectangle_rounded(rl.Rectangle(view.x + view.width - 5, bar_y, 4, bar_h), 1.0, 4, rl.Color(145, 96, 255, 125))

  def _draw_row(self, row: ListRow, area: rl.Rectangle, last: bool = False) -> None:
    bold, medium = self._font(FontWeight.BOLD), self._font(FontWeight.MEDIUM)
    pressed = self._target(row.target, area, scrolled=True)
    if pressed or row.selected:
      rl.draw_rectangle_rounded(area, 0.3, 12, TILE_PRESSED if pressed else ACCENT_SURFACE)
    elif not last:
      rl.draw_line_ex(rl.Vector2(area.x + 24 + ICON + 22, area.y + area.height + ROW_GAP / 2),
                      rl.Vector2(area.x + area.width - 12, area.y + area.height + ROW_GAP / 2), 1, DIVIDER)
    self._draw_icon(row.kind, rl.Vector2(area.x + 24 + ICON / 2, area.y + area.height / 2), ACCENT if row.selected else SUBTEXT)

    text_x = area.x + 24 + ICON + 22
    right = area.x + area.width - 24
    if row.badge:
      badge_w = measure_text_cached(medium, row.badge, 24).x + 32
      badge = rl.Rectangle(right - badge_w, area.y + (area.height - 44) / 2, badge_w, 44)
      rl.draw_rectangle_rounded(badge, 0.5, 10, rl.Color(ACCENT.r, ACCENT.g, ACCENT.b, 40))
      rl.draw_text_ex(medium, row.badge, rl.Vector2(badge.x + 16, badge.y + 10), 24, 0, ACCENT)
      right = badge.x - 16
    width = right - text_x
    if row.subtitle:
      rl.draw_text_ex(bold, fit_text(bold, row.title, 34, width), rl.Vector2(text_x, area.y + 14), 34, 0, TEXT)
      rl.draw_text_ex(medium, fit_text(medium, row.subtitle, 26, width), rl.Vector2(text_x, area.y + 58), 26, 0, SUBTEXT)
    else:
      rl.draw_text_ex(bold, fit_text(bold, row.title, 34, width), rl.Vector2(text_x, area.y + (area.height - 34) / 2), 34, 0, TEXT)

  @staticmethod
  def _draw_icon(kind: str, center: rl.Vector2, color) -> None:
    rl.draw_circle_v(center, ICON / 2, rl.Color(color.r, color.g, color.b, 22))
    if kind == "recent":  # clock
      rl.draw_ring(center, 13, 17, 0, 360, 24, color)
      rl.draw_line_ex(center, rl.Vector2(center.x, center.y - 9), 4, color)
      rl.draw_line_ex(center, rl.Vector2(center.x + 7, center.y + 3), 4, color)
    elif kind == "favorite":  # bookmark
      rl.draw_rectangle_rec(rl.Rectangle(center.x - 11, center.y - 15, 22, 22), color)
      rl.draw_triangle(rl.Vector2(center.x - 11, center.y + 7), rl.Vector2(center.x - 11, center.y + 16), rl.Vector2(center.x, center.y + 7), color)
      rl.draw_triangle(rl.Vector2(center.x + 11, center.y + 7), rl.Vector2(center.x, center.y + 7), rl.Vector2(center.x + 11, center.y + 16), color)
    else:  # map pin
      rl.draw_circle_v(rl.Vector2(center.x, center.y - 5), 12, color)
      rl.draw_triangle(rl.Vector2(center.x - 10, center.y + 1), rl.Vector2(center.x, center.y + 17), rl.Vector2(center.x + 10, center.y + 1), color)
      rl.draw_circle_v(rl.Vector2(center.x, center.y - 5), 5, TILE_BG)

  def _draw_keyboard(self, panel: rl.Rectangle) -> None:
    """Letters and digits for the search field, in place of the map. Search is case-blind, so no shift."""
    bold, medium = self._font(FontWeight.BOLD), self._font(FontWeight.MEDIUM)
    rl.draw_rectangle_rounded(panel, 2 * PANEL_RADIUS / max(1.0, min(panel.width, panel.height)), 16, CARD_BG)
    hint = tr("Suggestions update as you type")
    rl.draw_text_ex(medium, fit_text(medium, hint, 26, panel.width - 2 * KEY_PAD), rl.Vector2(panel.x + KEY_PAD, panel.y + 26),
                    26, 0, SUBTEXT)
    units = max(sum(width for _key, width in row) for row in KEY_ROWS)
    unit = (panel.width - 2 * KEY_PAD - (units - 1) * KEY_GAP) / units
    top = panel.y + 76
    key_h = min(KEY_MAX_HEIGHT, unit * 1.5, (panel.y + panel.height - KEY_PAD - top - (len(KEY_ROWS) - 1) * KEY_GAP) / len(KEY_ROWS))
    y = panel.y + panel.height - KEY_PAD - len(KEY_ROWS) * key_h - (len(KEY_ROWS) - 1) * KEY_GAP
    for row in KEY_ROWS:
      row_units = sum(width for _key, width in row)
      x = panel.x + KEY_PAD + (units - row_units) * (unit + KEY_GAP) / 2
      for key, width in row:
        area = rl.Rectangle(x, y, width * unit + (width - 1) * KEY_GAP, key_h)
        pressed = self._target(f"key:{key}", area)
        done = key == "done"
        fill = ACCENT if done else TILE_BG
        if pressed:
          fill = rl.Color(fill.r, fill.g, fill.b, 170) if done else TILE_PRESSED
        rl.draw_rectangle_rounded(area, 0.25, 10, fill)
        center = rl.Vector2(area.x + area.width / 2, area.y + area.height / 2)
        if key == "back":  # a left arrow
          rl.draw_line_ex(rl.Vector2(center.x - 16, center.y), rl.Vector2(center.x + 18, center.y), 4, TEXT)
          draw_chevron(center.x - 4, center.y, TEXT, left=True, size=12, thickness=4)
        else:
          label = {"space": tr("space"), "done": tr("Done")}.get(key, key)
          size = 30 if key in ("space", "done") else 40
          font = bold if done else medium
          label_w = measure_text_cached(font, label, size).x
          rl.draw_text_ex(font, label, rl.Vector2(center.x - label_w / 2, center.y - size / 2), size, 0,
                          rl.Color(8, 6, 20, 255) if done else TEXT)
        x += area.width + KEY_GAP
      y += key_h + KEY_GAP

  def _chip(self, target: str, label: str, selected: bool, x: float, y: float) -> float:
    medium = self._font(FontWeight.MEDIUM)
    width = measure_text_cached(medium, label, 26).x + 44
    area = rl.Rectangle(x, y, width, CHIP_HEIGHT)
    pressed = self._target(target, area)
    fill = ACCENT_SURFACE if selected else TILE_PRESSED if pressed else TILE_BG
    rl.draw_rectangle_rounded(area, 0.5, 10, fill)
    if selected:
      rl.draw_rectangle_rounded_lines_ex(area, 0.5, 10, 2, ACCENT_BORDER)
    rl.draw_text_ex(medium, label, rl.Vector2(x + 22, y + (CHIP_HEIGHT - 26) / 2), 26, 0, ACCENT if selected else SUBTEXT)
    return width

  def _big_button(self, target: str, label: str, color, area: rl.Rectangle, enabled: bool = True) -> None:
    bold = self._font(FontWeight.BOLD)
    pressed = enabled and self._target(target, area)
    alpha = 60 if not enabled else 200 if pressed else 255
    rl.draw_rectangle_rounded(area, 0.35, 10, rl.Color(color.r, color.g, color.b, alpha))
    width = measure_text_cached(bold, label, 40).x
    rl.draw_text_ex(bold, label, rl.Vector2(area.x + (area.width - width) / 2, area.y + (area.height - 40) / 2), 40, 0,
                    rl.Color(8, 20, 14, 255) if enabled else SUBTEXT)

  def _draw_map_panel(self, panel: rl.Rectangle) -> None:
    bold, medium = self._font(FontWeight.BOLD), self._font(FontWeight.MEDIUM)
    page = self.page
    draft = page._draft_destination
    route_chips = self.route_chips() if draft is not None else []
    sheet_h = 166.0 if draft is None else 258.0 + (CHIP_HEIGHT + 16 if route_chips else 0)
    map_rect = rl.Rectangle(panel.x, panel.y, panel.width, panel.height - sheet_h - 16)
    rl.draw_rectangle_rounded(map_rect, 2 * PANEL_RADIUS / map_rect.width, 16, TILE_BG)
    page._map.render(map_rect)

    sheet = rl.Rectangle(panel.x, panel.y + panel.height - sheet_h, panel.width, sheet_h)
    rl.draw_rectangle_rounded(sheet, 2 * PANEL_RADIUS / sheet.width, 16, CARD_BG)
    inner_x, inner_w = sheet.x + 30, sheet.width - 60

    if draft is None:
      active = page._active_destination
      if active is not None:
        button = rl.Rectangle(sheet.x + sheet.width - 30 - 240, sheet.y + (sheet_h - 96) / 2, 240, 96)
        self._big_button("action:cancel", tr("End route"), DANGER, button)
        name = str(active.get("name") or active.get("place_name") or "")
        rl.draw_text_ex(medium, tr("Navigating to").upper(), rl.Vector2(inner_x, sheet.y + 30), 23, 1.5, ACCENT)
        rl.draw_text_ex(bold, fit_text(bold, name, 38, button.x - inner_x - 24), rl.Vector2(inner_x, sheet.y + 72), 38, 0, TEXT)
      else:
        rl.draw_text_ex(bold, tr("Where to?"), rl.Vector2(inner_x, sheet.y + 40), 38, 0, TEXT)
        rl.draw_text_ex(medium, fit_text(medium, tr("Search or pick a saved place to preview the route"), 27, inner_w),
                        rl.Vector2(inner_x, sheet.y + 94), 27, 0, SUBTEXT)
      return

    start = rl.Rectangle(sheet.x + sheet.width - 30 - 240, sheet.y + 30, 240, 110)
    can_start = page._routing_available()
    self._big_button("action:start", tr("Start"), START, start, enabled=can_start)
    text_w = start.x - inner_x - 24
    name = str(draft.get("name") or draft.get("place_name") or tr("Destination"))
    rl.draw_text_ex(bold, fit_text(bold, name, 40, text_w), rl.Vector2(inner_x, sheet.y + 40), 40, 0, TEXT)
    summary, color = self.route_summary()
    rl.draw_text_ex(medium, fit_text(medium, summary, 28, text_w), rl.Vector2(inner_x, sheet.y + 96), 28, 0, color)

    y = sheet.y + 176
    for chips in (route_chips, self.favorite_chips()):
      if not chips:
        continue
      x = inner_x
      for target, label, selected in chips:
        x += self._chip(target, label, selected, x, y) + 14
      y += CHIP_HEIGHT + 16


class CarNavigateCard(Widget):
  """The car home screen's Navigate card: Home / Work, Start, and Other destination.

  OnroadControls feeds it state (favorites, lock, active route) and handles the actions.
  """

  PAD = 26.0
  HEADER = 112.0
  TILE_HEIGHT = 230.0
  START_HEIGHT = 110.0
  OTHER_HEIGHT = 104.0
  GAP = 22.0

  def __init__(self, *, start: Callable[[dict], None], open_other: Callable[[], None], end_route: Callable[[], None],
               drive: Callable[[], None] | None = None):
    super().__init__()
    self._start, self._open_other, self._end_route, self._drive = start, open_other, end_route, drive
    self.started = False  # onroad: with nothing selected, Start becomes Drive view
    self.home: dict | None = None
    self.work: dict | None = None
    self.selected: str | None = None  # "home" or "work"
    self.locked_text = ""
    self.routing_ok = True
    self.destination_name = ""  # of the active route, if any
    self._pressed: str | None = None
    self._fonts: dict = {}

  def show_event(self):
    super().show_event()
    self.selected = None

  # ── state ─────────────────────────────────────────────────────────────────

  def set_favorites(self, favorites: list[dict]) -> None:
    self.home = next((f for f in favorites if f.get("is_home")), None)
    self.work = next((f for f in favorites if f.get("is_work")), None)
    if self.selected and self.favorite(self.selected) is None:
      self.selected = None

  def favorite(self, key: str) -> dict | None:
    return self.home if key == "home" else self.work if key == "work" else None

  @property
  def drive_view(self) -> bool:
    """Whether the Start button is Drive view: onroad, with no Home or Work picked."""
    return self.started and self._drive is not None and self.favorite(self.selected or "") is None

  @property
  def can_set(self) -> bool:
    return self.routing_ok and not self.locked_text

  def allowed(self, key: str) -> bool:
    # Home / Work and Start are one tap each, so they work at any speed; the search
    # screen behind Other destination keeps the speed lock.
    if key == "end":
      return bool(self.destination_name)
    if key == "start":
      return self.drive_view or (self.routing_ok and self.favorite(self.selected or "") is not None)
    if key == "other":
      return self.can_set
    return self.routing_ok and self.favorite(key) is not None

  def status_text(self) -> str:
    if not self.routing_ok:
      return tr("Add a Mapbox secret key in The Galaxy to navigate")
    if self.destination_name:
      return tr("Navigating to {}").format(self.destination_name)
    if self.locked_text:
      return tr("Pick Home or Work; search unlocks below {} mph").format(int(NAV_UNLOCK_MPH))
    if self.started:
      return tr("Pick Home or Work, or go to the drive view")
    return tr("Pick Home or Work, then Start")

  # ── geometry and input ────────────────────────────────────────────────────

  def layout(self, rect: rl.Rectangle) -> dict[str, rl.Rectangle]:
    pad, gap = self.PAD, self.GAP
    inner_w = rect.width - 2 * pad
    y = rect.y + self.HEADER
    tile_w = (inner_w - gap) / 2
    rects = {
      "end": rl.Rectangle(rect.x + rect.width - pad - 200, rect.y + 24, 200, 64),
      "home": rl.Rectangle(rect.x + pad, y, tile_w, self.TILE_HEIGHT),
      "work": rl.Rectangle(rect.x + pad + tile_w + gap, y, tile_w, self.TILE_HEIGHT),
    }
    y += self.TILE_HEIGHT + gap
    rects["start"] = rl.Rectangle(rect.x + pad, y, inner_w, self.START_HEIGHT)
    y += self.START_HEIGHT + gap
    rects["other"] = rl.Rectangle(rect.x + pad, y, inner_w, self.OTHER_HEIGHT)
    return rects

  def key_at(self, x: float, y: float) -> str | None:
    for key, area in self.layout(self._rect).items():
      if (key != "end" or self.destination_name) and rl.check_collision_point_rec(rl.Vector2(x, y), area):
        return key
    return None

  def _handle_mouse_press(self, mouse_pos) -> None:
    self._pressed = self.key_at(mouse_pos.x, mouse_pos.y)

  def _handle_mouse_release(self, mouse_pos) -> None:
    pressed, self._pressed = self._pressed, None
    key = self.key_at(mouse_pos.x, mouse_pos.y)
    if key is not None and key == pressed:
      self.activate(key)

  def activate(self, key: str) -> None:
    if not self.allowed(key):
      return
    if key in ("home", "work"):
      self.selected = None if self.selected == key else key
    elif key == "start" and self.drive_view:
      self._drive()
    elif key == "start":
      favorite = self.favorite(self.selected or "")
      self.selected = None
      if favorite is not None:
        self._start(favorite)
    elif key == "other":
      self._open_other()
    elif key == "end":
      self._end_route()

  # ── drawing ───────────────────────────────────────────────────────────────

  def _font(self, weight: FontWeight):
    if weight not in self._fonts:
      self._fonts[weight] = gui_app.font(weight)
    return self._fonts[weight]

  def _centered(self, font, text: str, size: int, area: rl.Rectangle, y: float, color) -> None:
    text = fit_text(font, text, size, area.width - 32)
    width = measure_text_cached(font, text, size).x
    rl.draw_text_ex(font, text, rl.Vector2(area.x + (area.width - width) / 2, y), size, 0, color)

  def _render(self, rect: rl.Rectangle) -> None:
    bold, medium = self._font(FontWeight.BOLD), self._font(FontWeight.MEDIUM)
    roundness = 2 * PANEL_RADIUS / max(1, min(rect.width, rect.height))
    rl.draw_rectangle_rounded(rect, roundness, 16, CARD_BG)
    rl.draw_rectangle_rounded_lines_ex(rect, roundness, 16, 2, CARD_BORDER)
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x + self.PAD, rect.y, 110, 4), 1.0, 4, ACCENT)
    rects = self.layout(rect)

    rl.draw_text_ex(bold, tr("Navigate"), rl.Vector2(rect.x + self.PAD, rect.y + 22), 36, 0, TEXT)
    status_width = rect.width - 2 * self.PAD - (220 if self.destination_name else 0)
    status_color = ACCENT if self.destination_name and self.can_set else SUBTEXT
    rl.draw_text_ex(medium, fit_text(medium, self.status_text(), 26, status_width),
                    rl.Vector2(rect.x + self.PAD, rect.y + 66), 26, 0, status_color)
    if self.destination_name:
      end = rects["end"]
      rl.draw_rectangle_rounded(end, 0.5, 10, rl.Color(DANGER.r, DANGER.g, DANGER.b, 70 if self._pressed == "end" else 40))
      rl.draw_rectangle_rounded_lines_ex(end, 0.5, 10, 2, DANGER)
      self._centered(bold, tr("End route"), 28, end, end.y + 17, DANGER)

    for key, label in (("home", tr("Home")), ("work", tr("Work"))):
      area, favorite = rects[key], self.favorite(key)
      enabled, selected = self.allowed(key), self.selected == key
      pressed = self._pressed == key and enabled
      fill = TILE_PRESSED if pressed else ACCENT_SURFACE if selected else TILE_BG
      rl.draw_rectangle_rounded(area, 0.16, 12, fill)
      rl.draw_rectangle_rounded_lines_ex(area, 0.16, 12, 3 if selected else 2,
                                         ACCENT_BORDER if selected or pressed else CARD_BORDER)
      center = rl.Vector2(area.x + area.width / 2, area.y + 48)
      color = ACCENT if enabled else SUBTEXT
      rl.draw_circle_v(center, 28, rl.Color(color.r, color.g, color.b, 22))
      if key == "home":
        rl.draw_line_ex(rl.Vector2(center.x - 17, center.y), rl.Vector2(center.x, center.y - 15), 3, color)
        rl.draw_line_ex(rl.Vector2(center.x, center.y - 15), rl.Vector2(center.x + 17, center.y), 3, color)
        rl.draw_rectangle_lines_ex(rl.Rectangle(center.x - 12, center.y, 24, 16), 3, color)
      else:
        rl.draw_rectangle_lines_ex(rl.Rectangle(center.x - 15, center.y - 8, 30, 24), 3, color)
        rl.draw_rectangle_lines_ex(rl.Rectangle(center.x - 7, center.y - 15, 14, 7), 3, color)
        rl.draw_line_ex(rl.Vector2(center.x - 15, center.y + 2), rl.Vector2(center.x + 15, center.y + 2), 3, color)
      self._centered(bold, label, 44, area, area.y + 88, TEXT if enabled else SUBTEXT)
      if favorite is None:
        detail = tr("Set in Other destinations")
      else:
        detail = str(favorite.get("name") or favorite.get("place_name") or label)
      self._centered(medium, detail, 28, area, area.y + 144, SUBTEXT)
      if selected:
        self._centered(medium, tr("Selected"), 24, area, area.y + 187, ACCENT)

    start, enabled = rects["start"], self.allowed("start")
    alpha = 255 if enabled else 60
    rl.draw_rectangle_rounded(start, 0.3, 10, rl.Color(START.r, START.g, START.b, 210 if enabled and self._pressed == "start" else alpha))
    target = self.favorite(self.selected or "")
    if self.drive_view:
      label = tr("Drive view")
    elif enabled and target:
      label = tr("Start to {}").format(target.get("name") or tr("destination"))
    else:
      label = tr("Start")
    self._centered(bold, label, 44, start, start.y + (start.height - 44) / 2, rl.Color(8, 24, 14, 255) if enabled else SUBTEXT)

    other, enabled = rects["other"], self.allowed("other")
    rl.draw_rectangle_rounded(other, 0.25, 10, TILE_PRESSED if enabled and self._pressed == "other" else TILE_BG)
    rl.draw_rectangle_rounded_lines_ex(other, 0.25, 12, 2,
                                       ACCENT_BORDER if enabled and self._pressed == "other" else CARD_BORDER)
    text_width = other.width - 110
    rl.draw_text_ex(bold, fit_text(bold, tr("Other destinations"), 38, text_width),
                    rl.Vector2(other.x + 30, other.y + 16), 38, 0, TEXT if enabled else SUBTEXT)
    rl.draw_text_ex(medium, fit_text(medium, tr("Search, favorites and recent places"), 26, text_width),
                    rl.Vector2(other.x + 30, other.y + 62), 26, 0, SUBTEXT)
    draw_chevron(other.x + other.width - 42, other.y + other.height / 2, ACCENT if enabled else SUBTEXT, size=13, thickness=3)
