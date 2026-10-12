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

TEXT = {
  "pass": ("Left lane is faster", "Check mirror, blinker to pass"),
  "return": ("Passed: move back right", "Check mirror, blinker when clear"),
  "exit": ("Your lane exits ahead", "Move {side} to stay on route"),
  "keepright": ("Keep right", "Right lane is open, check mirror"),
  "jam": ("Traffic ahead in {distance}", "Easing to {speed} for the slowdown"),
  "turn": ("Your lane turns ahead", "Move {side} to stay on route"),
  "merge": ("Merge {side} ahead", "Check mirror before merging"),
  "exitjam": ("Exit backed up in {distance}", "Move {side} early, check mirror"),
  "arrive": ("Destination on {side}", "In {distance}"),
}
MERGE_BLOCKED = "Car beside you on the {side}: wait"


def format_jam(distance_m: float, speed_ms: float, is_metric: bool) -> tuple[str, str]:
  if is_metric:
    distance = f"{distance_m:.0f} m" if distance_m < 1000.0 else f"{distance_m / 1000.0:.1f} km"
    return distance, f"{speed_ms * 3.6:.0f} km/h"
  miles = distance_m / 1609.344
  distance = f"{distance_m * 3.28084:.0f} ft" if miles < 0.1 else f"{miles:.1f} mi"
  return distance, f"{speed_ms / 0.44704:.0f} mph"


def parse_passing_prompt(raw, now: float) -> dict | None:
  """D-114 pass / move-back suggestion if it is armed and fresh, else None."""
  if isinstance(raw, (str, bytes)):
    try:
      raw = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
      return None
  if not isinstance(raw, dict) or not raw.get("armed", False):
    return None
  side, phase = raw.get("side"), raw.get("phase")
  if phase not in TEXT or side not in (("",) if phase == "jam" else ("left", "right")):
    return None
  try:
    ts = float(raw.get("ts", -math.inf))
    distance, speed = float(raw.get("distance", 0.0) or 0.0), float(raw.get("speed", 0.0) or 0.0)
  except (TypeError, ValueError):
    return None
  if not 0.0 <= now - ts <= PROMPT_STALE_SECONDS:
    return None
  if phase == "jam" and not (math.isfinite(distance) and math.isfinite(speed) and distance > 0.0 and speed > 0.0):
    return None
  if phase in ("exitjam", "arrive") and not (math.isfinite(distance) and distance > 0.0):
    return None
  return {"side": side, "phase": phase, "ts": ts, "distance": distance, "speed": speed, "blocked": bool(raw.get("blocked", False))}


class NavPassingPromptRenderer(Widget):
  """MICI pill under the navigation card. Gives way to the exit-lane and faster-route prompts."""

  def __init__(self, navigation_card=None, *other_prompts):
    super().__init__()
    self._font_bold = gui_app.font(FontWeight.BOLD)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._navigation_card = navigation_card
    self._other_prompts = other_prompts
    self._prompt: dict | None = None
    self._last_update = -math.inf

  def _update_state(self) -> None:
    now = time.monotonic()
    if now - self._last_update < PROMPT_UPDATE_INTERVAL:
      return
    self._last_update = now
    try:
      raw = ui_state.params_memory.get("NavPassingPrompt")
    except Exception:
      raw = None
    self._prompt = parse_passing_prompt(raw, now)

  def _top(self, rect: rl.Rectangle) -> int:
    card = self._navigation_card
    if card is not None and getattr(card, "_valid", False):
      interactive = card._interactive_rect
      if interactive.height > 0:
        return int(interactive.y + interactive.height + 8)
    return int(rect.y + 16)

  def _render(self, rect: rl.Rectangle) -> None:
    self._update_state()
    prompt = self._prompt
    if prompt is None or time.monotonic() - prompt["ts"] > PROMPT_STALE_SECONDS:
      return
    if any(getattr(other, "_prompt", None) is not None for other in self._other_prompts):
      return

    side = prompt["side"]
    title, detail = TEXT[prompt["phase"]]
    distance, speed = format_jam(prompt["distance"], prompt["speed"], ui_state.is_metric)
    if prompt["phase"] == "merge" and prompt.get("blocked"):
      detail = MERGE_BLOCKED
    title = title.format(side=side, distance=distance, speed=speed)
    detail = detail.format(side=side, distance=distance, speed=speed)
    accent = rl.Color(255, 176, 32, 220) if prompt["phase"] == "jam" else rl.Color(80, 200, 255, 210)
    title_size, detail_size = 30, 20

    left_safe, right_margin = 96, 12
    width = min(420, max(260, int(rect.width - left_safe - right_margin)))
    height = 74
    x, y = int(rect.x + left_safe), self._top(rect)
    box = rl.Rectangle(x, y, width, height)
    rl.draw_rectangle_rounded(box, 0.3, 10, rl.Color(7, 11, 18, 232))
    rl.draw_rectangle_rounded_lines_ex(box, 0.3, 10, 2, accent)

    cx, cy, size = x + 38, y + height / 2, 34 * (1.0 + 0.12 * math.sin(time.monotonic() * 6.0))
    if side:
      direction = -1.0 if side == "left" else 1.0
      tip = rl.Vector2(cx + direction * size / 2, cy)
      top = rl.Vector2(cx - direction * size / 2, cy - size / 2)
      bottom = rl.Vector2(cx - direction * size / 2, cy + size / 2)
      a, b = (bottom, top) if side == "left" else (top, bottom)
      rl.draw_triangle(tip, a, b, accent)
    else:  # jam: a downward slow-down chevron
      rl.draw_triangle(rl.Vector2(cx + size / 2, cy - size / 2), rl.Vector2(cx - size / 2, cy - size / 2),
                       rl.Vector2(cx, cy + size / 2), accent)

    text_x = x + 74
    text_w = width - 74 - 12
    while title_size > 22 and measure_text_cached(self._font_bold, title, title_size).x > text_w:
      title_size -= 2
    rl.draw_text_ex(self._font_bold, title, rl.Vector2(text_x, y + 10), title_size, 0, rl.WHITE)
    while detail_size > 14 and measure_text_cached(self._font_medium, detail, detail_size).x > text_w:
      detail_size -= 1
    rl.draw_text_ex(self._font_medium, detail, rl.Vector2(text_x, y + 46), detail_size, 0, rl.Color(200, 205, 214, 255))
