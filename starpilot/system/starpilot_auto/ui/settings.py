"""Car settings: one sidebar, flat page selection, and a single Back path."""
from dataclasses import dataclass

import pyray as rl

from openpilot.selfdrive.ui.layouts.settings.types import PanelType
from openpilot.starpilot.system.starpilot_auto.ui import settings_style as style
from openpilot.starpilot.system.starpilot_auto.ui.car_display_settings import CarDisplaySettings
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.bluetooth import BluetoothManagerUI
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.developer import DeveloperLayout
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.device import DeviceLayout
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.network import NetworkUI
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.software import SoftwareLayout
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.toggles import TogglesLayout
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.panel import StarPilotPanel, StarPilotPanelType
from openpilot.starpilot.system.starpilot_auto.ui.starpilot_settings import CarStarPilotLayout
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.bluetooth_manager import BluetoothManager
from openpilot.system.ui.lib.scroll_panel2 import GuiScrollPanel2
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.widgets import Widget

SECTIONS = ('Car Display', 'Navigation', 'Driving', 'Sounds & Alerts', 'Connections', 'Vehicle', 'Device & System')


def sidebar_width(width):
  # On portrait/small screens the same labelled navigation becomes a drawer.
  return 0 if width < style.px(760) else min(style.px(320), max(style.px(210), width * .22))


@dataclass
class SettingsPage:
  key: str
  title: str
  section: str
  widget: Widget
  subpanel: str = ''
  scope: str = ''


class CarSettingsLayout(Widget):
  def __init__(self):
    super().__init__()
    self._close_callback = None
    self._active = False
    self._drawer = False
    self._targets = {}
    self._pressed = None
    self._nav_scroll = GuiScrollPanel2(horizontal=False)
    self._tabs_scroll = GuiScrollPanel2(horizontal=True, handle_out_of_bounds=False)
    self._section = SECTIONS[0]
    self._page = 'display'
    self._history = []
    self._pages = {}
    self._remembered = {}
    self._hub = CarStarPilotLayout()
    self._build_pages()

  def _add(self, key, title, section, widget, subpanel='', scope=''):
    self._pages[key] = SettingsPage(key, title, section, widget, subpanel, scope)
    if hasattr(widget, 'set_navigate_callback'):
      widget.set_navigate_callback(self._navigate)
      widget.set_back_callback(self._back)

  def _build_pages(self):
    panels = self._hub._panels
    def panel(kind):
      return panels[kind].instance
    def add_subpages(prefix, section, owner, names, scope='Shared with comma display'):
      for subpanel, title in names:
        self._add(f'{prefix}:{subpanel}', title, section, owner, subpanel, scope)

    self._add('display', 'Layout', 'Car Display', CarDisplaySettings())
    self._add('widgets', 'Status Widgets', 'Car Display', CarDisplaySettings(metrics=True))
    appearance = panel(StarPilotPanelType.VISUALS)
    add_subpages('appearance', 'Car Display', appearance, [
      ('hud', 'Driving Widgets'), ('model', 'Road & Path'), ('declutter', 'Visibility'), ('dev', 'Advanced Metrics'),
      ('dev_sidebar', 'Comma Status Widgets'),
    ])
    self._add('navigation', 'Routes', 'Navigation', panel(StarPilotPanelType.NAVIGATION))
    self._add('maps', 'Offline Maps', 'Navigation', panel(StarPilotPanelType.MAPS))
    add_subpages('appearance', 'Navigation', appearance, [('nav', 'Map Labels')])
    self._add('toggles', 'General', 'Driving', TogglesLayout(), scope='Driving behavior · Applies to the vehicle')
    longitudinal = panel(StarPilotPanelType.LONGITUDINAL)
    add_subpages('longitudinal', 'Driving', longitudinal, [
      ('tune', 'Gas / Brake'), ('personality', 'Personalities'), ('slc', 'Speed Limits'),
      ('csc', 'Curve Speed'), ('ce', 'Drive Modes'), ('vision_speed_limits', 'Vision Speed Limits'),
      ('daily', 'Weather & Comfort'), ('advanced', 'Actuators'),
    ], 'Driving behavior · Applies to the vehicle')
    add_subpages('lateral', 'Driving', panel(StarPilotPanelType.LATERAL), [
      ('behavior', 'Steering'), ('lane_changes', 'Lane Changes'), ('advanced', 'Steering Tuning'),
    ], 'Driving behavior · Applies to the vehicle')
    self._add('model', 'Driving Model', 'Driving', panel(StarPilotPanelType.DRIVING_MODEL))
    self._add('sounds', 'Sounds & Alerts', 'Sounds & Alerts', panel(StarPilotPanelType.SOUNDS))
    wifi = WifiManager()
    wifi.set_active(False)
    bluetooth = BluetoothManager()
    bluetooth.set_active(False)
    self._add('wifi', 'Wi-Fi', 'Connections', NetworkUI(wifi))
    self._add('bluetooth', 'Bluetooth', 'Connections', BluetoothManagerUI(bluetooth))
    from openpilot.starpilot.system.starpilot_auto.ui.connection_settings import StarpilotAutoSettings
    self._add('starpilot_auto', 'Starpilot Auto', 'Connections', StarpilotAutoSettings(lambda: self.open_page('bluetooth'), bluetooth))
    self._add('vehicle', 'Vehicle Settings', 'Vehicle', panel(StarPilotPanelType.VEHICLE))
    self._add('device', 'Device', 'Device & System', DeviceLayout(), scope='Comma device')
    self._add('system', 'Preferences', 'Device & System', panel(StarPilotPanelType.SYSTEM), scope='Comma device')
    add_subpages('appearance', 'Device & System', appearance, [('system', 'Camera & Startup')])
    self._add('software', 'Software', 'Device & System', SoftwareLayout())
    self._add('developer', 'Developer', 'Device & System', DeveloperLayout())

  @property
  def _current(self):
    return self._pages[self._page]

  def set_callbacks(self, on_close):
    self._close_callback = on_close

  def refresh_developer_visibility(self):
    pass

  def get_panel_depth(self):
    return len(self._history)

  def set_current_panel(self, panel_type):
    pages = {PanelType.DEVICE: 'device', PanelType.NETWORK: 'wifi', PanelType.BLUETOOTH: 'bluetooth',
             PanelType.TOGGLES: 'toggles', PanelType.SOFTWARE: 'software', PanelType.DEVELOPER: 'developer'}
    # Opening Settings again retains the last page; deep links remain explicit.
    if panel_type in pages:
      self.open_page(pages[panel_type])

  def open_panel(self, key):
    page = {'MAPS': 'maps', 'OFFLINE_MAPS': 'maps', 'NAVIGATION': 'navigation', 'SOUNDS': 'sounds',
            'SYSTEM': 'system', 'DRIVING_MODEL': 'model', 'LONGITUDINAL': 'longitudinal:tune',
            'LATERAL': 'lateral:behavior', 'VISUALS': 'display', 'VEHICLE': 'vehicle'}.get(key)
    if page:
      self.open_page(page)
      if key in ('MAPS', 'OFFLINE_MAPS'):
        self._current.widget.open_segment(1 if key == 'MAPS' else 0)

  def open_page(self, key):
    if self._active:
      self._current.widget.hide_event()
    self._drawer = False
    self._page = key
    self._section = self._current.section
    self._remembered[self._section] = key
    self._history = []
    if hasattr(self._current.widget, 'set_current_sub_panel'):
      self._current.widget.set_current_sub_panel(self._current.subpanel)
    if hasattr(self._current.widget, 'back'):
      self._current.widget.back()
    self._tabs_scroll.set_offset(0)
    self._reveal_tab = True
    if self._active:
      self._current.widget.show_event()

  def _navigate(self, subpanel):
    owner = self._current.widget
    previous = self._history[-1] if self._history else self._current.subpanel
    # Old controllers assign the destination before notifying the shell.
    owner.set_current_sub_panel(previous)
    owner.hide_event()
    if subpanel:
      self._history.append(subpanel)
    else:
      self._history.clear()
    owner.set_current_sub_panel(subpanel or self._current.subpanel)
    owner.show_event()

  def _back(self):
    if self._drawer:
      self._drawer = False
    elif hasattr(self._current.widget, 'back') and self._current.widget.back():
      pass
    elif hasattr(getattr(self._current.widget, '_scroller', None), 'back') and self._current.widget._scroller.back():
      pass
    elif self._history:
      self._current.widget.hide_event()
      self._history.pop()
      self._current.widget.set_current_sub_panel(self._history[-1] if self._history else self._current.subpanel)
      self._current.widget.show_event()
    elif self._close_callback:
      self._close_callback()

  def _target(self, point):
    return next((key for key, rect in self._targets.items() if rl.check_collision_point_rec(point, rect)), None)

  def _handle_mouse_press(self, pos):
    self._pressed = self._target(pos)

  def _handle_mouse_cancel(self):
    self._pressed = None

  def _handle_mouse_release(self, pos):
    target = self._target(pos)
    valid = self._nav_scroll.is_touch_valid() and self._tabs_scroll.is_touch_valid()
    if target and target == self._pressed and valid:
      if target == 'back':
        self._back()
      elif target == 'sections':
        self._drawer = not self._drawer
      elif target.startswith('section:'):
        section = target[8:]
        key = self._remembered.get(section) or next(key for key, page in self._pages.items() if page.section == section)
        self.open_page(key)
      elif target.startswith('page:'):
        self.open_page(target[5:])
      elif target in ('previous', 'next'):
        self._step_tabs(-1 if target == 'previous' else 1)
    self._pressed = None

  def _first_tab(self, limit, right, width):
    """The first tab edge from which everything up to `right` is visible, no later than tab `limit`."""
    return next((i for i, start in enumerate(self._tab_starts[:limit + 1]) if right - start <= width), limit)

  def _step_tabs(self, step):
    starts = self._tab_starts
    left = -self._tabs_scroll.get_offset()
    current = max(i for i, start in enumerate(starts) if start <= left + 1)
    if step < 0:
      index = current - 1 if starts[current] >= left - 1 else current
    else:
      last = self._first_tab(len(starts) - 1, starts[-1] + self._tab_widths[-1], self._tab_view_width)
      index = min(current + 1, last)
    self._tabs_scroll.set_offset(-starts[max(0, index)])

  def _button(self, key, rect, label, selected=False, clip=None, size=None, align='center'):
    size = size or style.px(26)
    from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import draw_chevron_icon
    icon = style.px(20)
    if key in ('previous', 'next'):
      draw_chevron_icon(rl.Rectangle(rect.x + (rect.width - icon) / 2, rect.y + (rect.height - icon) / 2, icon, icon), style.MUTED,
                        thickness=style.px(4), direction='left' if key == 'previous' else 'right')
    elif key == 'back':
      # Laid out like the section rows under it, with a chevron before the label.
      style.button(rect, '', self._pressed == 'back', size)
      inset = style.px(16)
      draw_chevron_icon(rl.Rectangle(rect.x + inset, rect.y + (rect.height - icon) / 2, icon, icon), style.TEXT,
                        thickness=style.px(4), direction='left')
      text_x = rect.x + inset + icon + style.px(10)
      style.text(rl.Rectangle(text_x, rect.y, max(0, rect.x + rect.width - inset - text_x), rect.height), label, size)
    else:
      style.button(rect, label, selected, size, align)
      if selected and key.startswith('section:'):
        # The selected section carries the accent bar at its left edge, as the old settings did.
        bar_h = rect.height * .5
        style.rounded(rl.Rectangle(rect.x + style.px(6), rect.y + (rect.height - bar_h) / 2, style.px(4), bar_h), style.px(2), style.ACCENT)
    bounds = rl.get_collision_rec(rect, clip) if clip else rect
    if bounds.width > 0 and bounds.height > 0:
      self._targets[key] = bounds

  def _draw_navigation(self, rect, back=True):
    """Back, then one row per section, all the same width, on the sidebar's own panel."""
    rl.draw_rectangle_rec(rect, style.SIDEBAR)
    edge = style.hairline()
    rl.draw_rectangle_rec(rl.Rectangle(rect.x + rect.width - edge, rect.y, edge, rect.height), style.SELECTED)
    gap, margin = style.px(8), style.px(12)
    area = rl.Rectangle(rect.x + margin, rect.y + margin, rect.width - 2 * margin, max(1, rect.height - 2 * margin))
    rows = (['back'] if back else []) + [f'section:{section}' for section in SECTIONS]
    back_gap = style.px(10) if back else 0  # sets Back apart from the sections
    row_height = min(style.px(70), max(style.px(48), (area.height - back_gap - gap * (len(rows) - 1)) / len(rows)))
    offset = self._nav_scroll.update(area, len(rows) * row_height + (len(rows) - 1) * gap + back_gap)
    size = style.px(22) if rect.width < style.px(260) else style.px(24)
    rl.begin_scissor_mode(int(area.x), int(area.y), int(area.width), int(area.height))
    y = area.y + offset
    for key in rows:
      item = rl.Rectangle(area.x, y, area.width, row_height)
      if key == 'back':
        self._button('back', item, 'Back', clip=area, size=size)
        y += back_gap
      else:
        section = key[8:]
        label = {'Sounds & Alerts': 'Sounds', 'Device & System': 'System'}.get(section, section)
        self._button(key, item, label, section == self._section, area, size=size, align='left')
      y += row_height + gap
    rl.end_scissor_mode()

  def _render(self, rect):
    self._targets.clear()
    rl.draw_rectangle_rec(rect, style.BG)
    width = sidebar_width(rect.width)
    if width:
      self._draw_navigation(rl.Rectangle(rect.x, rect.y, width, rect.height))
    gap = style.px(16) if width else style.px(8)
    margin = style.px(12)
    content = rl.Rectangle(rect.x + width + gap, rect.y + margin, max(1, rect.width - width - gap * 2), rect.height - 2 * margin)
    # The header row: the section title. Without the sidebar, Back and Sections lead it.
    head_h, font = style.px(52), style.px(24)
    title_x = content.x + style.px(16)
    if not width:
      self._button('back', rl.Rectangle(content.x, content.y, style.px(120), head_h), 'Back', size=font)
      self._button('sections', rl.Rectangle(content.x + style.px(128), content.y, style.px(140), head_h), 'Sections', size=font)
      title_x = content.x + style.px(284)
    title_w = max(0, content.x + content.width - title_x)
    style.text(rl.Rectangle(title_x, content.y, title_w, head_h), self._section, style.px(28), bold=True)
    pages = [page for page in self._pages.values() if page.section == self._section]
    tab_font, tab_h, tab_gap, inset, arrow = style.px(25), style.px(54), style.px(8), style.px(16), style.px(44)
    widths = [max(style.px(130), measure_text_cached(gui_app.font(FontWeight.NORMAL), page.title, tab_font).x + style.px(40)) for page in pages]
    starts = [sum(widths[:i]) + tab_gap * i for i in range(len(pages))]
    total = sum(widths) + tab_gap * max(0, len(pages) - 1)
    # Tabs that fit line up with the rows below; arrows take the edges only when they overflow.
    overflow = total > content.width - 2 * inset
    tabs_y = content.y + head_h + style.px(12)
    tabs = rl.Rectangle(content.x + arrow + tab_gap, tabs_y, max(1, content.width - 2 * (arrow + tab_gap)), tab_h) if overflow else \
      rl.Rectangle(content.x + inset, tabs_y, max(1, content.width - 2 * inset), tab_h)
    self._tab_starts, self._tab_widths, self._tab_view_width = starts, widths, tabs.width
    # Scroll only to tab edges, so no tab is left half-drawn at the left.
    extent = starts[self._first_tab(len(pages) - 1, total, tabs.width)] + tabs.width if overflow else total
    if getattr(self, '_reveal_tab', False) or getattr(self, '_last_tab_width', None) != tabs.width:
      self._last_tab_width = tabs.width
      index = next(i for i, page in enumerate(pages) if page.key == self._page)
      self._tabs_scroll.set_offset(-starts[self._first_tab(index, starts[index] + widths[index], tabs.width)])
      self._reveal_tab = False
    offset = self._tabs_scroll.update(tabs, extent)
    clip_pad = max(style.px(3), 2 * style.hairline())
    rl.begin_scissor_mode(int(tabs.x), int(tabs.y - clip_pad), int(tabs.width), int(tabs.height + 2 * clip_pad))
    for page, x, w in zip(pages, starts, widths, strict=True):
      self._button(f'page:{page.key}', rl.Rectangle(tabs.x + offset + x, tabs.y, w, tabs.height), page.title, page.key == self._page, tabs, tab_font)
    rl.end_scissor_mode()
    if overflow:
      self._button('previous', rl.Rectangle(content.x, tabs.y, arrow, tab_h), '‹')
      self._button('next', rl.Rectangle(content.x + content.width - arrow, tabs.y, arrow, tab_h), '›')
    scope_h = style.px(32) if self._current.scope else 0
    if scope_h:
      style.text(rl.Rectangle(content.x + inset, tabs_y + tab_h + style.px(8), content.width - 2 * inset, scope_h),
                 self._current.scope, style.px(22), style.MUTED)
    top = tabs_y - content.y + tab_h + style.px(12) + scope_h
    body = rl.Rectangle(content.x, content.y + top, content.width, max(1, content.height - top))
    if self._drawer and not width:
      self._targets = {key: value for key, value in self._targets.items() if key in ('back', 'sections')}
      self._draw_navigation(body, back=False)
    else:
      widget = self._current.widget
      widget.set_parent_rect(body)
      view = getattr(widget, '_sub_panels', {}).get(getattr(widget, '_current_sub_panel', ''), getattr(widget, '_manager_view', widget))
      if view is not None:
        view._in_settings_shell = True
      rl.begin_scissor_mode(int(body.x), int(body.y), int(body.width), int(body.height))
      if isinstance(widget, StarPilotPanel):
        # StarPilot pages keep their 1:1 layouts; drawing them zoomed matches the px() pages.
        style.render_zoomed(widget, body)
      else:
        widget.render(body)
      rl.end_scissor_mode()

  def show_event(self):
    super().show_event()
    self._active = True
    self._current.widget.show_event()

  def hide_event(self):
    self._current.widget.hide_event()
    self._active = False
    self._pressed = None
    super().hide_event()
