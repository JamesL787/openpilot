from __future__ import annotations

import json
import math
import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

PROMPT_STALE_SECONDS = 2.0
PROMPT_UPDATE_INTERVAL = 0.1
BUTTON_ROW_TOP = 46  # taps above the buttons (on the title) do nothing


def parse_reroute_prompt(raw, now: float) -> dict | None:
  """D-111 faster-route offer if it is armed and fresh, else None."""
  if isinstance(raw, (str, bytes)):
    try:
      raw = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
      return None
  if not isinstance(raw, dict) or not raw.get("armed", False):
    return None
  try:
    if not 0.0 <= now - float(raw.get("ts", -math.inf)) <= PROMPT_STALE_SECONDS:
      return None
    return {
      "id": int(raw["id"]),
      "savings_s": max(float(raw.get("savings_s", 0.0) or 0.0), 0.0),
      "remaining_s": max(float(raw.get("remaining_s", 0.0) or 0.0), 0.0),
      "ts": float(raw["ts"]),
    }
  except (KeyError, TypeError, ValueError):
    return None


def response_for_tap(prompt: dict, box: rl.Rectangle, x: float, y: float) -> dict | None:
  """Button row only: left half is Switch, right half is Keep."""
  if y < box.y + BUTTON_ROW_TOP:
    return None
  return {"id": prompt["id"], "accept": x < box.x + box.width / 2.0}


def format_savings(savings_s: float) -> str:
  minutes = max(int(round(savings_s / 60.0)), 1)
  return f"{minutes} min faster"


class NavTrafficPromptRenderer(Widget):
  """MICI pill: a faster route was found. The route changes only if the driver taps Switch."""

  def __init__(self, lane_prompt=None, navigation_card=None):
    super().__init__()
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._lane_prompt = lane_prompt
    self._navigation_card = navigation_card
    self._prompt: dict | None = None
    self._answered_id: int | None = None
    self._box = rl.Rectangle(0, 0, 0, 0)
    self._last_update = -math.inf

  @property
  def _hit_rect(self) -> rl.Rectangle:
    return self._box if self._prompt is not None and self._box.width > 0 else rl.Rectangle(-1, -1, 0, 0)

  def _update_state(self) -> None:
    now = time.monotonic()
    if now - self._last_update < PROMPT_UPDATE_INTERVAL:
      return
    self._last_update = now
    try:
      raw = ui_state.params_memory.get("NavTrafficReroutePrompt")
    except Exception:
      raw = None
    prompt = parse_reroute_prompt(raw, now)
    self._prompt = None if prompt is not None and prompt["id"] == self._answered_id else prompt

  def _handle_mouse_release(self, mouse_pos) -> None:
    super()._handle_mouse_release(mouse_pos)
    prompt = self._prompt
    if prompt is None:
      return
    response = response_for_tap(prompt, self._box, mouse_pos.x, mouse_pos.y)
    if response is None:
      return
    try:
      ui_state.params_memory.put("NavTrafficRerouteResponse", response)
    except Exception:
      return
    self._answered_id = prompt["id"]
    self._prompt = None

  def _top(self, rect: rl.Rectangle) -> int:
    top = int(rect.y + 16)
    card = self._navigation_card
    if card is not None and getattr(card, "_valid", False):
      interactive = card._interactive_rect
      if interactive.height > 0:
        top = int(interactive.y + interactive.height + 8)
    if self._lane_prompt is not None and getattr(self._lane_prompt, "_prompt", None) is not None:
      top += 82
    return top

  def _render(self, rect: rl.Rectangle) -> None:
    prompt = self._prompt
    if prompt is None or time.monotonic() - prompt["ts"] > PROMPT_STALE_SECONDS:
      self._box = rl.Rectangle(0, 0, 0, 0)
      return

    left_safe, right_margin = 96, 12
    width = min(420, max(260, int(rect.width - left_safe - right_margin)))
    height = 96
    x, y = int(rect.x + left_safe), self._top(rect)
    self._box = rl.Rectangle(x, y, width, height)
    accent = rl.Color(70, 200, 120, 220)
    rl.draw_rectangle_rounded(self._box, 0.25, 10, rl.Color(7, 11, 18, 232))
    rl.draw_rectangle_rounded_lines_ex(self._box, 0.25, 10, 2, accent)

    title = f"Faster route: {format_savings(prompt['savings_s'])}"
    title_size = 28
    while title_size > 20 and measure_text_cached(self._font_bold, title, title_size).x > width - 24:
      title_size -= 2
    rl.draw_text_ex(self._font_bold, title, rl.Vector2(x + 12, y + 8), title_size, 0, rl.WHITE)

    half = (width - 36) / 2
    buttons = (
      (rl.Rectangle(x + 12, y + BUTTON_ROW_TOP, half, 40), "Switch", rl.Color(40, 140, 80, 255)),
      (rl.Rectangle(x + 24 + half, y + BUTTON_ROW_TOP, half, 40), f"Keep ({int(math.ceil(prompt['remaining_s']))})", rl.Color(60, 66, 78, 255)),
    )
    for button, label, color in buttons:
      rl.draw_rectangle_rounded(button, 0.4, 8, color)
      size = measure_text_cached(self._font_medium, label, 24)
      rl.draw_text_ex(self._font_medium, label, rl.Vector2(button.x + (button.width - size.x) / 2, button.y + (button.height - size.y) / 2),
                      24, 0, rl.WHITE)
