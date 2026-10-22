"""The latest limit, its attention animation and override mark on both screens."""

import math
import time

import pyray as rl

from openpilot.starpilot.ui.onroad_customization import placement
from openpilot.starpilot.ui.onroad_state import OnroadState, speed_limit_bounds
from openpilot.starpilot.ui.presentation import BitmapFonts, FontRole, Profile
from openpilot.starpilot.ui.speed_limit_pulse import SpeedLimitPulse
from openpilot.starpilot.ui.unified_speed_presentation import displayed_adjusted_limit_mps, resolve_unified_speed


INK = rl.Color(241, 246, 243, 255)
MUTED = rl.Color(190, 208, 202, 255)


def draw_text(fonts, text, role, size, x, y, color=INK):
  if isinstance(color, (tuple, list)):
    color = rl.Color(*color)
  radius = 1.15 if fonts.profile == Profile.LARGE else 1.
  contour = rl.Color(6, 14, 10, round(color.a * .90))
  for dx, dy in ((-radius, 0), (radius, 0), (0, -radius), (0, radius)):
    fonts.draw(text, role, size, x + dx, y + dy, contour)
  fonts.draw(text, role, size, x, y + (1.5 if fonts.profile == Profile.LARGE else 1.2),
             rl.Color(7, 16, 12, round(color.a * .32)))
  fonts.draw(text, role, size, x, y, color)


def draw_line(profile, start, end, stroke, color):
  radius = 1.4 if profile == Profile.LARGE else 1.
  rl.draw_line_ex(start, end, stroke + 2 * radius, rl.Color(6, 14, 10, round(color.a * .87)))
  rl.draw_line_ex(start, end, stroke, color)


def draw_ink(fonts, text, role, size, x, top, color=INK):
  ink_top, ink_bottom = fonts.vertical_ink(text, role, size)
  draw_text(fonts, text, role, size, x, top - ink_top, color)
  return fonts.measure(text, role, size).width, ink_bottom - ink_top


def draw_caption(fonts, label, x, top, color=MUTED, *, unit=None):
  large = fonts.profile == Profile.LARGE
  width, height = draw_ink(fonts, label, FontRole.MEDIUM, 32 if large else 24, x, top, color)
  if unit:
    size = 24 if large else 20
    unit_top, _ = fonts.vertical_ink(unit, FontRole.NORMAL, size)
    # Exclude the p descender when aligning mph to the caption baseline.
    _, baseline = fonts.vertical_ink('mh' if unit == 'mph' else unit, FontRole.NORMAL, size)
    gap = 12 if large else 8
    unit_width, _ = draw_ink(fonts, unit, FontRole.NORMAL, size, x + width + gap,
                             top + height - (baseline - unit_top), color)
    width += gap + unit_width
  return width, height


class SpeedLimitWidget:
  def __init__(self, fonts: BitmapFonts, profile: Profile):
    self.fonts = fonts
    self.profile = profile
    self.pulse = SpeedLimitPulse()

  def render(self, state: OnroadState) -> None:
    bounds = speed_limit_bounds(self.profile, state)
    now = state.observed_ns / 1e9 if state.observed_ns else time.monotonic()
    self.pulse.update(state, now, visible=bounds is not None)
    if bounds is None:
      return
    shown, obs = resolve_unified_speed(state), state.speed_limit
    pending = shown.pending and not obs.automatic_adoption_pending
    elapsed = max(0., now - obs.pending_since_ns / 1e9)
    hop = -6 * math.sin(math.pi * (elapsed % 1.5) / 1.5) ** 2 if pending else 0
    large = self.profile == Profile.LARGE
    x, top, _, _ = bounds
    x, top = x + 12, max(0, top + 12)
    number_top = top + (40 if large else 32) + hop
    color = self.pulse.color(INK, now)
    set_visible = shown.mode != 'limit_only' if large else (state.cruise_active and state.cruise_kph is not None and
      placement(state.customization, self.profile, 'max_speed')['enabled'])
    heading_width, heading_height = draw_caption(self.fonts, 'LIMIT', x, top, unit=None if set_visible else shown.unit)
    width, height = draw_ink(self.fonts, shown.posted_text, FontRole.BOLD, 70 if large else 58, x, number_top, color)
    end = x + width
    if shown.offset_text:
      size = 46 if large else 36
      a, b = self.fonts.vertical_ink(shown.offset_text, FontRole.MEDIUM, size)
      gap = 12 if large else 10
      draw_ink(self.fonts, shown.offset_text, FontRole.MEDIUM, size, end + gap, number_top + height - (b - a), color)
    if pending:
      target = displayed_adjusted_limit_mps(obs)
      if target is not None and state.speed_mps is not None and target != state.speed_mps:
        ax, ay = x + heading_width + (20 if large else 14), top + heading_height / 2
        direction = -1 if target > state.speed_mps else 1
        half_height, wing, stroke = (14, 9, 3) if large else (10, 6, 2)
        tip = rl.Vector2(ax, ay + direction * half_height)
        draw_line(self.profile, rl.Vector2(ax, ay - direction * half_height), tip, stroke, color)
        for dx in (-wing, wing):
          draw_line(self.profile, tip, rl.Vector2(ax + dx, tip.y - direction * wing), stroke, color)
    if obs.driver_override_active:
      color = rl.Color(197, 163, 255, 240)
      left, top, right, bottom = x - 4, number_top - 3, x + width + 4, number_top + height + 3
      draw_line(self.profile, rl.Vector2(left, top), rl.Vector2(right, bottom), 3 if large else 2.5, color)
      draw_line(self.profile, rl.Vector2(right, top), rl.Vector2(left, bottom), 3 if large else 2.5, color)
