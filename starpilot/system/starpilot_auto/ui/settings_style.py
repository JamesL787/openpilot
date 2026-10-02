"""Responsive Galaxy surfaces for the car's settings.

Text is measured before controls are placed. Narrow rows stack values below
labels; scrolling, rather than smaller type, accommodates short displays.

The car lays its UI out on a 720-row canvas (car_ui.LOGICAL_HEIGHT) and scales that to
the head unit (0.67x on an 800x480 screen), so sizes are written in design pixels and pass
through px(): at 1:1 they would be too small to read and soft on screen.
"""
from contextlib import contextmanager

import pyray as rl

from openpilot.system.ui.lib.application import FONT_SCALE, FontWeight, MousePos, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

# The Galaxy palette the car settings used before: blue-black surfaces with purple edges.
BG = rl.Color(6, 6, 15, 255)
SIDEBAR = rl.Color(10, 10, 22, 255)
SURFACE = rl.Color(14, 12, 23, 255)
BORDER = rl.Color(58, 42, 106, 255)
SELECTED = rl.Color(33, 24, 62, 255)
SELECTED_BORDER = rl.Color(118, 80, 214, 255)
TRACK = rl.Color(40, 34, 66, 255)
TEXT = rl.Color(248, 248, 255, 255)
MUTED = rl.Color(160, 160, 191, 255)
ACCENT = rl.Color(145, 96, 255, 255)

UNIT = 1.6  # logical pixels per design pixel


def px(value):
  return round(value * UNIT)


TEXT_SIZE = px(30)
BUTTON_SIZE = px(28)
MESSAGE_SIZE = px(30)


_zoom = [1.0]


def zoom_level():
  return _zoom[-1]


def zoom_rect(rect, k):
  return rl.Rectangle(rect.x / k, rect.y / k, rect.width / k, rect.height / k)


@contextmanager
def zoom(rect, k=UNIT):
  """Draw a subtree k times larger. Yields `rect` in the subtree's coordinates, with touches
  and clipping mapped to match, so views laid out at 1:1 read like the px() ones."""
  app = gui_app
  scale, events, last = app._scale, app._mouse_events, app._last_mouse_event

  def mapped(event):
    return event._replace(pos=MousePos(event.pos.x / k, event.pos.y / k))

  app._mouse_events = [mapped(event) for event in events]
  app._last_mouse_event = mapped(last)
  app._scale = scale * k
  app._patch_scissor_mode()
  rl.rl_push_matrix()
  rl.rl_scalef(k, k, 1.0)
  _zoom.append(_zoom[-1] * k)
  try:
    yield zoom_rect(rect, k)
  finally:
    _zoom.pop()
    rl.rl_pop_matrix()
    app._scale = scale
    app._patch_scissor_mode()
    app._mouse_events, app._last_mouse_event = events, last


def render_zoomed(widget, rect, k=UNIT):
  """Render `widget` k times larger into `rect`, keeping its parent clip in the same coordinates."""
  parent = widget._parent_rect
  with zoom(rect, k) as inner:
    if parent is not None:
      widget.set_parent_rect(zoom_rect(parent, k))
    try:
      return widget.render(inner)
    finally:
      widget._parent_rect = parent


def hairline():
  """One physical pixel in logical units, so outlines do not fade when the car scales the UI down."""
  return max(1.0, 1.0 / gui_app._scale) if gui_app._scale > 0 else 1.0


def roundness(rect, radius):
  """raylib's roundness for a corner radius in logical pixels."""
  return min(1.0, 2.0 * radius / max(1.0, min(rect.width, rect.height)))


def rounded(rect, radius, color):
  rl.draw_rectangle_rounded(rect, roundness(rect, radius), 16, color)


def outline(rect, radius, color):
  """Stroke just inside `rect`: raylib strokes outward, where a clip of the same size would cut it off."""
  t = hairline()
  inner = rl.Rectangle(rect.x + t, rect.y + t, max(0, rect.width - 2 * t), max(0, rect.height - 2 * t))
  rl.draw_rectangle_rounded_lines_ex(inner, roundness(inner, max(0.0, radius - t)), 16, t, color)


BUTTON_RADIUS = px(16)
ROW_RADIUS = px(18)


def text(rect, value, size=TEXT_SIZE, color=TEXT, bold=False, align='left'):
  """Fit a single line within its own reserved rectangle, with an ellipsis."""
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import truncate_text_ellipsis
  font = gui_app.font(FontWeight.SEMI_BOLD if bold else FontWeight.NORMAL)
  value = truncate_text_ellipsis(font, str(value).replace('·', '-').replace('…', '...'), max(0, rect.width), size)
  x = rect.x
  if align != 'left':
    slack = max(0, rect.width - measure_text_cached(font, value, size).x)
    x += slack / 2 if align == 'center' else slack
  # Glyphs are drawn at size * FONT_SCALE; centring that box centres the capitals.
  rl.draw_text_ex(font, value, rl.Vector2(round(x), round(rect.y + (rect.height - size * FONT_SCALE) / 2)), size, 0, color)


def text_width(value, size, bold=False):
  return measure_text_cached(gui_app.font(FontWeight.SEMI_BOLD if bold else FontWeight.NORMAL), str(value), size).x


def button(rect, label, selected=False, size=BUTTON_SIZE, align='center', enabled=True):
  # Corners and padding are logical sizes; inside a zoomed page they stay the same on screen.
  radius, pad = min(BUTTON_RADIUS / zoom_level(), rect.height / 2), px(16) / zoom_level()
  rounded(rect, radius, SELECTED if selected else SURFACE)
  outline(rect, radius, SELECTED_BORDER if selected else BORDER)
  text(rl.Rectangle(rect.x + pad, rect.y, max(0, rect.width - 2 * pad), rect.height), label, size,
       TEXT if enabled else MUTED, bold=selected, align=align)


def switch(rect, value, enabled=True):
  color = ACCENT if value else TRACK
  if not enabled:
    color = rl.Color(color.r, color.g, color.b, 100)
  rl.draw_rectangle_rounded(rect, 1, 16, color)
  radius = rect.height / 2 - px(5)
  x = rect.x + (rect.width - rect.height / 2 if value else rect.height / 2)
  rl.draw_circle_v(rl.Vector2(x, rect.y + rect.height / 2), radius, TEXT if enabled else MUTED)


def _split_word(font, word, width, size):
  """Break a word wider than the line (a URL or path) so none of it is cut off."""
  parts, part = [], ''
  for char in word:
    if part and measure_text_cached(font, part + char, size).x > width:
      parts.append(part)
      part = char
    else:
      part += char
  return parts + [part]


def lines(value, width, size):
  """Wrap text without imposing a fixed row height or truncating descriptions."""
  font = gui_app.font(FontWeight.NORMAL)
  result = []
  for paragraph in str(value).split('\n'):
    line = ''
    for word in paragraph.split():
      if measure_text_cached(font, word, size).x > width:
        *full, word = _split_word(font, word, width, size)
        result.extend(([line] if line else []) + full)
        line = ''
      candidate = f'{line} {word}'.strip()
      if line and measure_text_cached(font, candidate, size).x > width:
        result.append(line)
        line = word
      else:
        line = candidate
    result.append(line)
  return result


VALUE_SIZE = px(24)


def message(rect, value, size=MESSAGE_SIZE, color=MUTED):
  """Draw a wrapped status message centered in its area, so it is never cut off."""
  margin, leading = px(20), size + px(8)
  wrapped = lines(value, max(1, rect.width - 2 * margin), size)
  y = rect.y + (rect.height - len(wrapped) * leading) / 2
  for line in wrapped:
    text(rl.Rectangle(rect.x + margin, y, max(0, rect.width - 2 * margin), leading), line, size, color, align='center')
    y += leading


ROW_PAD = px(20)
LINE_GAP = px(5)


def row_layout(width, title, subtitle, kind, value=''):
  """Return measured text and disjoint control geometry, in row-local units."""
  pad = ROW_PAD
  size = px(30) if width >= px(600) else px(26)
  sub_size = px(24) if width >= px(600) else px(22)
  if kind == 'toggle':
    control_width, stacked = px(88), False
  else:
    # Size the value to its text so short values sit at the right edge; one too long for
    # the right side goes under the title instead of being cut off.
    measured = measure_text_cached(gui_app.font(FontWeight.NORMAL), str(value), VALUE_SIZE).x + px(8)
    control_width = min(max(px(120), measured), width * .45)
    stacked = bool(value) and (width < px(700) or measured > width * .45)
  reserve = 0 if stacked or (kind != 'toggle' and not value) else control_width + px(24)
  available = max(px(40), width - pad * 2 - reserve)
  title_lines = lines(title, available, size) if title else []
  subtitle_lines = lines(subtitle, available, sub_size) if subtitle else []
  gap = px(6) if title_lines and subtitle_lines else 0
  text_height = len(title_lines) * (size + LINE_GAP) + len(subtitle_lines) * (sub_size + LINE_GAP) + gap
  control_height = px(36) if stacked else px(44)
  height = max(px(96), text_height + pad * 2 + (control_height + px(12) if stacked else 0))
  # Beside a control, the text block is centered on the same line as the control.
  text_top = pad if stacked else (height - text_height) / 2
  control = rl.Rectangle(pad if stacked else width - pad - control_width,
                         height - pad - control_height if stacked else (height - control_height) / 2,
                         width - pad * 2 if stacked else control_width, control_height)
  return height, available, size, sub_size, title_lines, subtitle_lines, control, text_top, stacked


def render_settings(view, rect):
  """Draw SettingSection/SettingRow data using the Galaxy row language."""
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import SettingRow, SettingSection
  view.set_rect(rect)
  view._interactive_rects.clear()
  rl.draw_rectangle_rec(rect, BG)
  pad = px(16)
  area = rl.Rectangle(rect.x + pad, rect.y, max(1, rect.width - pad * 2), max(1, rect.height))
  view._scroll_rect = area
  blocks = []
  y = px(8)
  heading, description = px(32), px(23)
  if view._header_title and (not getattr(view, '_in_settings_shell', False) or getattr(view, '_choices', None)):
    for line in lines(tr(view._header_title), area.width - px(24), heading):
      blocks.append(('heading', y, line, heading + px(10)))
      y += heading + px(10)
  if view._header_subtitle:
    for line in lines(tr(view._header_subtitle), area.width - px(24), description):
      blocks.append(('description', y, line, description + px(7)))
      y += description + px(7)
  y += px(12)
  if view._tab_defs:
    # Wrap tabs; none disappear off the right edge.
    tab_x, tab_h = 0, px(54)
    for tab in view._tab_defs:
      label = tr(tab.get('label', tab.get('title', tab['id'])))
      w = min(area.width, max(px(130), measure_text_cached(gui_app.font(FontWeight.NORMAL), label, px(24)).x + px(32)))
      if tab_x and tab_x + w > area.width:
        y += tab_h + px(8)
        tab_x = 0
      blocks.append(('tab', y, (tab, label, tab_x, w), tab_h))
      tab_x += w + px(8)
    y += tab_h + px(16)
  sections = list(view._active_sections())
  if view._parent_toggle:
    parent = view._parent_toggle
    sections.insert(0, SettingSection('', [SettingRow('__parent', 'toggle', parent.label, parent.subtitle,
                                                      get_state=parent.get_state, set_state=parent.set_state)]))
  for section in sections:
    rows = view._visible_rows(section)
    if not rows:
      continue
    if section.title:
      blocks.append(('section', y, tr(section.title), px(46)))
      y += px(46)
    for row in rows:
      enabled = row.enabled() if row.enabled else True
      subtitle = row.disabled_label if not enabled and row.disabled_label else row.subtitle
      value = str(row.get_value() if row.get_value else row.action_text or ('Open' if row.navigate_to or row.on_click else ''))
      layout = row_layout(area.width, tr(row.title), tr(subtitle), row.type, value)
      blocks.append(('row', y, (row, enabled, value, layout), layout[0]))
      y += layout[0] + px(8)
    y += px(12)
  view._content_height = y
  view._scroll_panel.set_enabled(view.is_visible)
  view._scroll_offset = view._scroll_panel.update(area, max(y, area.height))
  rl.begin_scissor_mode(int(area.x), int(area.y), int(area.width), int(area.height))
  for kind, top, data, height in blocks:
    bounds = rl.Rectangle(area.x, area.y + top + view._scroll_offset, area.width, height)
    if not rl.check_collision_recs(bounds, area):
      continue
    if kind in ('heading', 'description', 'section'):
      text(bounds, data, heading if kind == 'heading' else description, MUTED if kind == 'description' else TEXT, kind != 'description')
    elif kind == 'tab':
      tab, label, x, width = data
      bounds.x += x
      bounds.width = width
      button(bounds, label, view._active_tab_key == tab['id'], px(24))
      view._interactive_rects[f"tab:{tab['id']}"] = bounds
    else:
      row, enabled, value, layout = data
      _, width, size, sub_size, title_lines, subtitle_lines, control, text_top, stacked = layout
      target = f'{row.type}:{row.id}' if row.id != '__parent' else f'parent_toggle:{view._parent_toggle.label}'
      view._interactive_rects[target] = bounds
      pressed = view._pressed_target == target
      rounded(bounds, ROW_RADIUS, SELECTED if pressed else SURFACE)
      outline(bounds, ROW_RADIUS, SELECTED_BORDER if pressed else BORDER)
      control = rl.Rectangle(bounds.x + control.x, bounds.y + control.y, control.width, control.height)
      ty = bounds.y + text_top
      for line in title_lines:
        text(rl.Rectangle(bounds.x + ROW_PAD, ty, width, size + LINE_GAP), line, size, TEXT if enabled else MUTED, True)
        ty += size + LINE_GAP
      ty += px(6) if title_lines and subtitle_lines else 0
      for line in subtitle_lines:
        text(rl.Rectangle(bounds.x + ROW_PAD, ty, width, sub_size + LINE_GAP), line, sub_size, MUTED)
        ty += sub_size + LINE_GAP
      if row.type == 'toggle':
        switch(control, row.get_state() if row.get_state else False, enabled)
      elif value:
        text(control, value, VALUE_SIZE, ACCENT if enabled else MUTED, align='left' if stacked else 'right')
  rl.end_scissor_mode()
  if y > area.height:
    # Draw the scrollbar in the right gutter, clear of the rows' edges and values.
    view._scrollbar.render(rl.Rectangle(area.x, area.y, area.width + pad - px(4), area.height), y, view._scroll_offset)
