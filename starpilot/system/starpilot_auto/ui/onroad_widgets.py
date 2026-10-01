"""Car versions of onroad widgets, used by CarOnroadView (onroad.py)."""

from __future__ import annotations

import math
from collections.abc import Callable

import pyray as rl
from cereal import log

from openpilot.selfdrive.ui.lib.starpilot_status import ENGAGED_COLOR, TRAFFIC_COLOR
from openpilot.selfdrive.ui.onroad.driver_state import DMOJI_SIZE, DriverStateRenderer
from openpilot.selfdrive.ui.onroad.exp_button import ExpButton
from openpilot.selfdrive.ui.onroad.alert_renderer import (
  ALERT_PADDING,
  MID_FONT_SIZE_1,
  MID_FONT_SIZE_2,
  SMALL_FONT_SIZE,
  Alert,
  AlertRenderer,
)
from openpilot.selfdrive.ui.onroad.hud_renderer import COLORS, CRUISE_DISABLED_CHAR, FONT_SIZES, HudRenderer
from openpilot.selfdrive.ui.onroad.starpilot.compass import get_compass_text
from openpilot.selfdrive.ui.onroad.starpilot.navigation_card import NavigationCardRenderer
from openpilot.selfdrive.ui.onroad.starpilot.pip_sidecam import PipSideCamera
from openpilot.selfdrive.ui.onroad.starpilot import slc_speed_limit as slc
from openpilot.selfdrive.ui.onroad.starpilot.slc_speed_limit import render_speed_limit_at
from openpilot.selfdrive.ui.onroad.starpilot.widget_style import CONTROL_BORDER, CONTROL_WIDTH, WIDGET_ANCHOR_OFFSET, draw_control_card
from openpilot.selfdrive.ui.onroad.starpilot.widgets import (
  AetherGaugeWidget,
  DriverMonitorWidget,
  SetSpeedWidget,
  SpeedLimitWidget,
  StoppedTimerWidget,
)
from openpilot.selfdrive.ui.ui_state import UIStatus, ui_state
from openpilot.system.ui.lib.application import FONT_SCALE, font_fallback, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import draw_text_with_shadow, measure_text_cached

AlertSize = log.SelfdriveState.AlertSize

# The side-camera bubbles sit over the bottom alert band. They already show the
# lane change, so these banners are dropped when a bubble would cover their text.
BUBBLE_REDUNDANT_ALERTS = frozenset({
  "preLaneChangeLeft",
  "preLaneChangeRight",
  "laneChange",
  "laneChangeBlocked",
  "laneChangeBlockedLoud",
})

LATERAL_PAUSE_WIDTH = 220
LATERAL_PAUSE_HEIGHT = 96
TORQUE_BAR_MAX_RISE = 82  # max offset + thickness in torque_bar.py
TORQUE_BAR_GAP = 24

# The steering-wheel (experimental mode) button and the column under it (pedals)
# sit closer to the right edge than on the comma, leaving the stopped timer more room.
EXP_BUTTON_SIZE = 160
EXP_ICON_SIZE = 120
RIGHT_COLUMN_ANCHOR = 130  # column centre, from the camera pane's right edge (the comma uses 146)
CONTROL_TOP = 45  # the MAX card's and the steering wheel's top edge, below the pane's top (widget_layout_manager)
SPEED_UNIT_GAP = 22  # between the speed's ink and the unit's
# The experimental icon's dark outline (offset px, alpha), outer ring first; see ExpButton.ICON_OUTLINE.
EXP_ICON_OUTLINE = ((6, 60), (3, 150))
# MAX and LIMIT cards are laid out by glyph ink, not line boxes: a line box carries ~19%
# empty space above digits, which left a gap under the label and the value off centre.
CARD_INK_MARGIN = 16        # card edge to the label's ink; the value's space ends as far from the bottom
CARD_VALUE_INSET = 10       # the value's ink keeps this clear of the card's sides
SET_SPEED_VALUE_FONT = 120  # the value fills the space under the label
LIMIT_OFFSET_VALUE_FONT = 100  # leaves room for the offset chip
LIMIT_CHIP_LIFT = 6         # the offset chip's bottom margin matches the label's top one
# The stop / curve gauge draws nothing in the top 25px of the comma's box (the curve's road
# starts there); the car trims it so the road sits one column gap under the LIMIT card.
GAUGE_TOP_TRIM = 25.0
# A smaller driver-monitoring icon. The bookmark button is a status-column slot (developer_sidebar.py).
DM_SIZE = 160
DM_ICON_SIZE = round(DMOJI_SIZE * DM_SIZE / 192)  # the comma draws a 128 icon in a 192 slot
BOOKMARK_ICON_SIZE = 64
BOOKMARK_FLASH_SECONDS = 1.2
BOOKMARK_COUNTER = "WheelButtonBookmarkCounter"
# The next-turn card on the left clears the MAX / LIMIT column by the margin it keeps on the right.
DIRECTIONS_LEFT_X = WIDGET_ANCHOR_OFFSET + CONTROL_WIDTH / 2 + 40


def top_center_span(rect: rl.Rectangle) -> tuple[float, float]:
  """(left, right) of the space between the MAX card and the steering wheel. The speed and the
  Stopped timer centre in it: the wheel sits closer to its edge than MAX does to its own, so the
  pane's centre would put them nearer MAX."""
  left = rect.x + WIDGET_ANCHOR_OFFSET + CONTROL_WIDTH / 2
  right = rect.x + rect.width - RIGHT_COLUMN_ANCHOR - EXP_BUTTON_SIZE / 2
  return left, right


_ink_cache: dict[tuple, rl.Rectangle] = {}


def text_ink(font: rl.Font | None, text: str, font_size: float) -> rl.Rectangle:
  """The painted part of ``text`` drawn at (0, 0) and ``font_size``: glyph boxes, without the
  line box's empty space or the first and last glyphs' side bearings."""
  if font is None or not font.glyphCount:
    size = measure_text_cached(font, text, font_size)
    return rl.Rectangle(0, 0, size.x, size.y)
  font = font_fallback(font)  # what draw_text_ex will draw with
  key = (font.texture.id, text, font_size)
  ink = _ink_cache.get(key)
  if ink is None:
    scale = font_size * FONT_SCALE / font.baseSize
    pen, left, top, right, bottom = 0.0, math.inf, math.inf, -math.inf, -math.inf
    for char in text:
      index = rl.get_glyph_index(font, ord(char))
      glyph, box = font.glyphs[index], font.recs[index]
      if box.width > 0 and box.height > 0:
        left, right = min(left, pen + glyph.offsetX * scale), max(right, pen + (glyph.offsetX + box.width) * scale)
        top, bottom = min(top, glyph.offsetY * scale), max(bottom, (glyph.offsetY + box.height) * scale)
      pen += (glyph.advanceX or box.width) * scale
    ink = rl.Rectangle(left, top, right - left, bottom - top) if right > left else rl.Rectangle(0, 0, 0, 0)
    if len(_ink_cache) > 256:
      _ink_cache.clear()
    _ink_cache[key] = ink
  return ink


def fit_font_size(font: rl.Font | None, text: str, font_size: int, width: float) -> int:
  """``font_size``, shrunk until the text's ink fits ``width`` (three digits in km/h)."""
  ink_width = text_ink(font, text, font_size).width
  return font_size if ink_width <= width else max(1, int(font_size * width / ink_width))


def draw_ink(font: rl.Font | None, text: str, font_size: float, center_x: float, ink_top: float, color: rl.Color) -> float:
  """Draw ``text`` with its ink centred on ``center_x`` and starting at ``ink_top``; return the ink's bottom."""
  ink = text_ink(font, text, font_size)
  rl.draw_text_ex(font, text, rl.Vector2(center_x - ink.x - ink.width / 2, ink_top - ink.y), font_size, 0, color)
  return ink_top + ink.height


def draw_card_value(font: rl.Font | None, text: str, font_size: int, rect: rl.Rectangle, top: float, bottom: float,
                    color: rl.Color) -> None:
  """A card's value, as large as fits, centred between ``top`` and ``bottom`` by its ink."""
  font_size = fit_font_size(font, text, font_size, rect.width - 2 * CARD_VALUE_INSET)
  ink = text_ink(font, text, font_size)
  draw_ink(font, text, font_size, rect.x + rect.width / 2, top + (bottom - top - ink.height) / 2, color)


def lateral_pause_rect(camera_rect: rl.Rectangle, display_width: float) -> rl.Rectangle:
  """Place the car's pause badge above the torque bar, centered in the camera pane."""
  torque_scale = camera_rect.height / 240.0 * (camera_rect.width / max(1.0, display_width))
  torque_bar_top = camera_rect.y + camera_rect.height - TORQUE_BAR_MAX_RISE * torque_scale
  return rl.Rectangle(
    camera_rect.x + (camera_rect.width - LATERAL_PAUSE_WIDTH) / 2,
    torque_bar_top - TORQUE_BAR_GAP - LATERAL_PAUSE_HEIGHT,
    LATERAL_PAUSE_WIDTH,
    LATERAL_PAUSE_HEIGHT,
  )


def render_lateral_paused(rect: rl.Rectangle, font: rl.Font):
  """Larger labeled lateral-pause badge."""
  rl.draw_rectangle_rounded(rect, 0.28, 12, rl.Color(0, 0, 0, 166))
  rl.draw_rectangle_rounded_lines_ex(rect, 0.28, 12, 5, TRAFFIC_COLOR)

  cy = rect.y + rect.height / 2.0
  label_center_x = rect.x + rect.width * 0.29
  icon_cx = rect.x + rect.width * 0.72
  font_size = max(1, int(rect.height * 0.44))
  label_size = measure_text_cached(font, "Lat", font_size)
  label_pos = rl.Vector2(label_center_x - label_size.x / 2, cy - label_size.y / 2)
  draw_text_with_shadow(font, "Lat", label_pos, font_size, rl.WHITE, shadow_alpha=190)

  # A larger version of the comma's curved-arrow pause symbol.
  rl.draw_ring(rl.Vector2(int(icon_cx), int(cy)), 26, 32, 45, 315, 0, rl.Color(255, 255, 255, 120))
  rl.draw_triangle(
    rl.Vector2(int(icon_cx + 16), int(cy - 27)),
    rl.Vector2(int(icon_cx + 34), int(cy - 16)),
    rl.Vector2(int(icon_cx + 27), int(cy - 34)),
    rl.Color(255, 255, 255, 120),
  )
  rl.draw_rectangle(int(icon_cx - 11), int(cy - 21), 7, 42, rl.WHITE)
  rl.draw_rectangle(int(icon_cx + 4), int(cy - 21), 7, 42, rl.WHITE)


class CarAlertRenderer(AlertRenderer):
  """Alerts that can be drawn after the side camera and dropped where it covers them."""

  def __init__(self):
    super().__init__()
    # Event names (the part of alertType before "/") dropped while their text would
    # land under something drawn on top, as reported by covers(text_rect).
    self.hidden_alert_names: frozenset[str] = frozenset()
    self.covers: Callable[[rl.Rectangle], bool] | None = None
    # Deferred: the road view's own pass skips the alert; the owner draws it later.
    self.deferred = False
    self._cover_rect = rl.Rectangle(0, 0, 0, 0)

  def render(self, rect: rl.Rectangle | None = None):
    if self.deferred:
      return None
    return super().render(rect)

  def _render(self, rect: rl.Rectangle):
    self._cover_rect = rect
    return super()._render(rect)

  def get_alert(self, sm) -> Alert | None:
    alert = super().get_alert(sm)
    if alert is not None and self._is_covered(alert, self._cover_rect):
      self._prev_alert = None  # vanish rather than slide out from under the cover
      return None
    return alert

  def _is_covered(self, alert: Alert, rect: rl.Rectangle) -> bool:
    if self.covers is None or (alert.alert_type or "").split("/", 1)[0] not in self.hidden_alert_names:
      return False
    return self.covers(self._text_bounds(alert, rect))

  def _text_bounds(self, alert: Alert, rect: rl.Rectangle) -> rl.Rectangle:
    """Where a settled alert's text lands: text1 centred in its band, text2 just below."""
    band = self._get_alert_rect(rect, alert.size)
    if alert.size == AlertSize.full:
      return band
    max_width = int(band.width - ALERT_PADDING * 2)
    lines = [(self._alert_text1_label, alert.text1, SMALL_FONT_SIZE if alert.size == AlertSize.small else MID_FONT_SIZE_1)]
    if alert.size == AlertSize.mid and alert.text2:
      lines.append((self._alert_text2_label, alert.text2, MID_FONT_SIZE_2))
    width = height = text1_height = 0.0
    for label, text, font_size in lines:
      label.set_text(text)
      label.set_font_size(font_size)
      line_height = label.get_content_height(max_width)
      text1_height = text1_height or line_height
      height += line_height
      width = max(width, label.text_width)
    return rl.Rectangle(band.x + (band.width - width) / 2, band.y + (band.height - text1_height) / 2, width, height)


class CarPipSideCamera(PipSideCamera):
  """Remembers what the last frame drew, so the view can lay alerts out around it."""

  def __init__(self):
    super().__init__()
    self._drawn: list[tuple[str, rl.Rectangle]] = []  # ("bubble" | "curved", rect)

  def _render(self, content_rect: rl.Rectangle):
    self._drawn = []
    return super()._render(content_rect)

  def _blind_spot_monitors_visible(self) -> bool:
    return ui_state.starpilot_auto_blind_spot_monitors_visible

  def _draw_bubble(self, bubble: rl.Rectangle, crop: rl.Rectangle):
    super()._draw_bubble(bubble, crop)
    self._drawn.append(("bubble", bubble))

  def _draw_curved(self, content_rect: rl.Rectangle, crop: rl.Rectangle):
    super()._draw_curved(content_rect, crop)
    self._drawn.append(("curved", content_rect))

  @property
  def showing(self) -> bool:
    return bool(self._drawn)

  def covers(self, area: rl.Rectangle) -> bool:
    """Whether the last frame's side camera overlaps area."""
    for shape, rect in self._drawn:
      if shape == "curved":
        if rect.x < area.x + area.width and area.x < rect.x + rect.width and \
           rect.y < area.y + area.height and area.y < rect.y + rect.height:
          return True
        continue
      radius = rect.width / 2
      cx, cy = rect.x + radius, rect.y + radius
      nearest_x = min(max(cx, area.x), area.x + area.width)
      nearest_y = min(max(cy, area.y), area.y + area.height)
      if (cx - nearest_x) ** 2 + (cy - nearest_y) ** 2 < radius ** 2:
        return True
    return False


STOPPED_COLOR = rl.Color(255, 40, 40, 255)  # bright red, readable over any background


class CarStoppedTimerWidget(StoppedTimerWidget):
  """A compact "Stopped" label and mm:ss timer in place of the speed readout.

  Centred between the MAX card and the steering wheel, where the speed it replaces sits, with
  the label's ink level with the top of the MAX card and the wheel, and sized to fit that gap.
  """

  LABEL_FONT = 104
  TIMER_FONT = 88
  HORIZONTAL_MARGIN = 38
  TEXT_TOP = CONTROL_TOP  # the label's ink, not its line box
  LINE_GAP = 18           # between the label's ink and the timer's

  def _render(self, rect: rl.Rectangle) -> None:
    duration = self._duration
    label_text, timer_text = "Stopped", f"{duration // 60:02d}:{duration % 60:02d}"
    full_width = measure_text_cached(self._font_bold, label_text, self.LABEL_FONT).x
    left, right = top_center_span(rect)
    available = max(1.0, right - left - 2 * self.HORIZONTAL_MARGIN)
    scale = min(1.0, available / full_width) if full_width > 0 else 1.0
    scale = max(0.6, scale)
    label_font = max(1, int(self.LABEL_FONT * scale))
    timer_font = max(1, int(self.TIMER_FONT * scale))
    label_size = measure_text_cached(self._font_bold, label_text, label_font)
    timer_size = measure_text_cached(self._font_normal, timer_text, timer_font)
    label_ink = text_ink(self._font_bold, label_text, label_font)
    timer_ink = text_ink(self._font_normal, timer_text, timer_font)

    duration_color = self._duration_color()
    center_x = (left + right) / 2
    label_y = rect.y + self.TEXT_TOP - label_ink.y
    timer_y = rect.y + self.TEXT_TOP + label_ink.height + self.LINE_GAP - timer_ink.y
    self._draw_text(self._font_bold, label_text, rl.Vector2(center_x - label_size.x / 2, label_y), label_font, duration_color)
    self._draw_text(self._font_normal, timer_text, rl.Vector2(center_x - timer_size.x / 2, timer_y), timer_font, rl.WHITE)

  # A soft dark halo on every side (radius, alpha per copy), so the text reads over a bright
  # road or sky without an opaque panel behind the car HUD.
  SHADOW_RINGS = ((5, 28), (3, 48), (1, 90))
  SHADOW_DIRECTIONS = tuple((math.cos(math.radians(a)), math.sin(math.radians(a))) for a in range(0, 360, 45))

  @classmethod
  def _draw_text(cls, font: rl.Font, text: str, pos: rl.Vector2, font_size: int, color: rl.Color) -> None:
    for radius, alpha in cls.SHADOW_RINGS:
      shadow = rl.Color(0, 0, 0, alpha)
      for dx, dy in cls.SHADOW_DIRECTIONS:
        rl.draw_text_ex(font, text, rl.Vector2(pos.x + dx * radius, pos.y + dy * radius), font_size, 0, shadow)
    rl.draw_text_ex(font, text, pos, font_size, 0, color)

  def _duration_color(self) -> rl.Color:
    return STOPPED_COLOR


class CarSetSpeedWidget(SetSpeedWidget):
  """MAX laid out like the speed-limit card below it: the label tight to the top edge,
  the value large and centred in the space left under it."""

  def _render(self, rect: rl.Rectangle) -> None:
    draw_control_card(rect)
    hud = self.hud_renderer
    max_color, value_color = COLORS.GREY, COLORS.DARK_GREY
    if hud.is_cruise_set:
      value_color = COLORS.WHITE
      if ui_state.status == UIStatus.ENGAGED:
        max_color = COLORS.ENGAGED
      elif ui_state.status in (UIStatus.DISENGAGED, UIStatus.OVERRIDE):
        max_color = COLORS.DISENGAGED

    label_bottom = draw_ink(self._font_semi_bold, tr("MAX"), FONT_SIZES.max_speed, rect.x + rect.width / 2,
                            rect.y + CARD_INK_MARGIN, max_color)
    value = CRUISE_DISABLED_CHAR if not hud.is_cruise_set else str(round(hud.set_speed))
    draw_card_value(self._font_bold, value, SET_SPEED_VALUE_FONT, rect, label_bottom, rect.y + rect.height - CARD_INK_MARGIN,
                    value_color)


class CarSpeedLimitWidget(SpeedLimitWidget):
  """The US card shares MAX's layout, so the two stacked cards line up; the pending
  sign and the round Vienna sign are the comma's."""

  directions_on_left = False  # set each frame by the view

  def _render(self, rect: rl.Rectangle) -> None:
    state = self._slc_state
    if state is None:
      return
    # Beside the map the per-source list is noise; the sign alone is enough. The turn card
    # on the left takes the list's place.
    expanded = ui_state.ui_params.get_bool("SpeedLimitSources") and not ui_state.nav_map_beside_road and \
               not self.directions_on_left
    if state["use_vienna"] or (state["speed_limit_changed"] and state["unconfirmed_valid"]):
      self._sign_rect = render_speed_limit_at(state, rect, expanded)
      return
    self._draw_card(state, rect)
    if expanded:
      slc._draw_sources_bubble(state, rect)
    self._sign_rect = rect

  @staticmethod
  def _draw_card(state: dict, rect: rl.Rectangle) -> None:
    border = slc._speed_limit_pulse_color(CONTROL_BORDER, CONTROL_BORDER.a)
    text_color = slc._speed_limit_pulse_color(rl.Color(255, 255, 255, 255), 255)
    draw_control_card(rect, border=border)
    label_color = slc._source_label_color(255, is_overridden=state["slc_overridden_speed"] != 0)
    label_bottom = draw_ink(slc._get_semi_bold(), slc._active_source_label(state), slc.FONT_SOURCE, rect.x + rect.width / 2,
                            rect.y + CARD_INK_MARGIN, label_color)
    bottom, font_size = rect.y + rect.height - CARD_INK_MARGIN, SET_SPEED_VALUE_FONT
    if state["show_offset"]:
      chip_area = rl.Rectangle(rect.x, rect.y, rect.width, rect.height - LIMIT_CHIP_LIFT)
      slc._draw_offset_chip(chip_area, state["offset_str"], text_color)
      bottom, font_size = rect.y + rect.height - LIMIT_CHIP_LIFT - slc.OFFSET_CHIP_BOTTOM - slc.OFFSET_CHIP_HEIGHT, LIMIT_OFFSET_VALUE_FONT
    draw_card_value(slc._get_bold(), state["speed_limit_str"], font_size, rect, label_bottom, bottom, text_color)


class CarNavigationCardRenderer(NavigationCardRenderer):
  def render(self, rect: rl.Rectangle | None = None):
    if ui_state.nav_map_beside_road:  # the map beside the road shows the same turn, larger
      return None
    return super().render(rect)

  @property
  def on_left(self) -> bool:
    return self._valid and ui_state.car_directions_left and not ui_state.nav_map_beside_road

  def _card_x(self, rect: rl.Rectangle, width: float) -> int:
    """The car's Directions Side: right-aligned like the comma, or just right of the MAX / LIMIT column."""
    if ui_state.car_directions_left:
      return int(rect.x + DIRECTIONS_LEFT_X)
    return super()._card_x(rect, width)


class CarExpButton(ExpButton):
  ICON_OUTLINE = EXP_ICON_OUTLINE


class CarHudRenderer(HudRenderer):
  def __init__(self):
    super().__init__()
    self._exp_button = CarExpButton(EXP_BUTTON_SIZE, EXP_ICON_SIZE)

  def _create_navigation_card(self):
    return CarNavigationCardRenderer()

  @property
  def directions_on_left(self) -> bool:
    return self._navigation_card.on_left

  def _draw_current_speed(self, rect: rl.Rectangle) -> None:
    """The speed's ink level with the top of the MAX card and the steering wheel and centred
    between them, the unit and compass below it; off with the car's Show Current Speed setting."""
    if not ui_state.car_show_current_speed:
      return
    left, right = top_center_span(rect)
    center_x = (left + right) / 2
    bottom = draw_ink(self._font_bold, str(round(self.speed)), FONT_SIZES.current_speed, center_x, rect.y + CONTROL_TOP,
                      COLORS.WHITE)
    unit = tr("km/h") if ui_state.is_metric else tr("mph")
    bottom = draw_ink(self._font_medium, unit, FONT_SIZES.speed_unit, center_x, bottom + SPEED_UNIT_GAP, COLORS.WHITE_TRANSLUCENT)
    compass_text = get_compass_text()
    if compass_text:
      size = measure_text_cached(self._font_bold, compass_text, 50)
      draw_text_with_shadow(self._font_bold, compass_text, rl.Vector2(center_x - size.x / 2, bottom + SPEED_UNIT_GAP), 50, rl.WHITE)


class CarAetherGaugeWidget(AetherGaugeWidget):
  """The stop / curve gauge pulled up tight under the LIMIT card."""

  HEIGHT = AetherGaugeWidget.HEIGHT - GAUGE_TOP_TRIM
  ROAD_BOTTOM = AetherGaugeWidget.ROAD_BOTTOM - GAUGE_TOP_TRIM


class CarDriverStateRenderer(DriverStateRenderer):
  def __init__(self):
    super().__init__(DM_ICON_SIZE)


class CarDriverMonitorWidget(DriverMonitorWidget):
  def get_size(self) -> tuple[float, float]:
    return float(DM_SIZE), float(DM_SIZE)


def request_bookmark(params_memory) -> None:
  """Bookmark the drive. The comma's own UI owns bookmarkButton, so this steps the counter feedbackd
  also watches for steering-wheel bookmarks; each step becomes a userBookmark."""
  params_memory.put_int(BOOKMARK_COUNTER, params_memory.get_int(BOOKMARK_COUNTER) + 1)


class CarBookmarkButton:
  """A status-column card; the car routes its taps (car_ui.OnroadControls), since the drive takes no touches."""

  def __init__(self, clock: Callable[[], float] = rl.get_time):
    self._clock = clock
    self._flashed_at = -math.inf

  def press(self) -> None:
    request_bookmark(ui_state.params_memory)
    self._flashed_at = self._clock()  # the card lights up briefly to confirm it

  def lit(self) -> float:
    """1.0 just after a press, fading to 0 over BOOKMARK_FLASH_SECONDS."""
    return max(0.0, 1.0 - (self._clock() - self._flashed_at) / BOOKMARK_FLASH_SECONDS)

  def render(self, rect: rl.Rectangle, font: rl.Font, font_size: int) -> None:
    """The bookmark icon and BOOKMARK in a metric card's outline; SAVED in green after a press."""
    lit = self.lit()
    roundness = 0.3
    if lit > 0:
      rl.draw_rectangle_rounded(rect, roundness, 10, rl.Color(ENGAGED_COLOR.r, ENGAGED_COLOR.g, ENGAGED_COLOR.b, int(70 * lit)))
      rl.draw_rectangle_rounded_lines_ex(rect, roundness, 10, 3, rl.Color(ENGAGED_COLOR.r, ENGAGED_COLOR.g, ENGAGED_COLOR.b, int(255 * lit)))
    else:
      rl.draw_rectangle_rounded_lines_ex(rect, roundness, 10, 2, rl.Color(255, 255, 255, 85))
    label = tr("SAVED") if lit > 0 else tr("BOOKMARK")
    icon = gui_app.texture("icons_mici/onroad/bookmark.png", BOOKMARK_ICON_SIZE, BOOKMARK_ICON_SIZE)
    gap = 14
    text_width = measure_text_cached(font, label, font_size).x
    room = rect.width - 36 - BOOKMARK_ICON_SIZE - gap
    if text_width > room > 0:
      font_size = max(1, int(font_size * room / text_width))
      text_width = measure_text_cached(font, label, font_size).x
    x = rect.x + (rect.width - BOOKMARK_ICON_SIZE - gap - text_width) / 2
    rl.draw_texture(icon, int(x), int(rect.y + (rect.height - BOOKMARK_ICON_SIZE) / 2), rl.WHITE)
    rl.draw_text_ex(font, label, rl.Vector2(x + BOOKMARK_ICON_SIZE + gap, rect.y + (rect.height - font_size) / 2), font_size, 0,
                    ENGAGED_COLOR if lit > 0 else rl.WHITE)


class NoFavoriteMenu:
  """The car routes onroad touches to its own quick menu, never the radial menu."""

  def process_mouse_events(self, events, rect) -> bool:
    return False

  def blocks_pointer(self, mouse_pos) -> bool:
    return False

  def collapse(self) -> None:
    pass

  def render(self, rect) -> None:
    pass

  def render_corner_hint(self, rect) -> None:
    pass
