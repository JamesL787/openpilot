"""Car-owned dialogs with a scrollable body and a fixed, non-overlapping footer."""
import re
from html import unescape

import pyray as rl

from openpilot.starpilot.system.starpilot_auto.ui import settings_style as style
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import AetherSettingsView, SettingRow, SettingSection
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget, DialogResult


class SettingsDialog(Widget):
  def __init__(self, title, confirm_text, cancel_text, callback):
    super().__init__()
    self.title = title
    self._confirm_text = confirm_text
    self._cancel_text = cancel_text
    self._callback = callback
    self._targets = {}
    self._pressed = None
    self._view = self._child(AetherSettingsView(self, []))

  def _set_result(self, result):
    gui_app.pop_widget()
    if self._callback:
      self._callback(result)

  def _handle_mouse_press(self, pos):
    self._pressed = next((key for key, rect in self._targets.items() if rl.check_collision_point_rec(pos, rect)), None)

  def _handle_mouse_cancel(self):
    self._pressed = None

  def _handle_mouse_release(self, pos):
    key = self._pressed
    self._pressed = None
    if key in self._targets and rl.check_collision_point_rec(pos, self._targets[key]):
      self._set_result(DialogResult.CONFIRM if key == 'confirm' else DialogResult.CANCEL)

  def _render(self, rect):
    px = style.px
    rl.draw_rectangle_rec(rect, rl.Color(0, 0, 0, 180))
    margin, pad, button_h = px(12), px(24), px(56)
    width, height = min(px(1100), rect.width - 2 * margin), rect.height - 2 * margin
    box = rl.Rectangle(rect.x + (rect.width - width) / 2, rect.y + margin, width, height)
    style.rounded(box, px(24), style.BG)
    style.outline(box, px(24), style.BORDER)
    style.text(rl.Rectangle(box.x + pad, box.y + margin, box.width - 2 * pad, px(52)), self.title, px(30), bold=True)
    body_top = px(76)
    footer_y = box.y + box.height - button_h - px(16)
    body = rl.Rectangle(box.x + px(8), box.y + body_top, box.width - px(16), max(1, footer_y - px(8) - box.y - body_top))
    self._view.set_parent_rect(body)
    self._view.render(body)
    gap = px(12)
    button_width = (box.width - 2 * pad - gap) / 2 if self._cancel_text else box.width - 2 * pad
    self._targets.clear()
    if self._cancel_text:
      cancel = rl.Rectangle(box.x + pad, footer_y, button_width, button_h)
      style.button(cancel, self._cancel_text)
      self._targets['cancel'] = cancel
    confirm = rl.Rectangle(box.x + box.width - pad - button_width, footer_y, button_width, button_h)
    style.button(confirm, self._confirm_text, self._can_confirm(), enabled=self._can_confirm())
    if self._can_confirm():
      self._targets['confirm'] = confirm

  def _can_confirm(self):
    return True


class MultiOptionDialog(SettingsDialog):
  def __init__(self, title, options, current='', option_font_weight=None, callback=None):
    super().__init__(title, 'Select', 'Cancel', callback)
    self.options = options
    self.current = current
    self.selection = current
    self._view._sections = [SettingSection('', [SettingRow(str(i), 'value', label,
      get_value=lambda label=label: 'Selected' if self.selection == label else '',
      on_click=lambda label=label: self._on_option_clicked(label)) for i, label in enumerate(options)])]

  def _on_option_clicked(self, option):
    self.selection = option

  def _can_confirm(self):
    return bool(self.selection)


class ConfirmDialog(SettingsDialog):
  def __init__(self, text, confirm_text, cancel_text=None, rich=False, callback=None):
    super().__init__('Confirm' if cancel_text != '' else 'Information', confirm_text, 'Cancel' if cancel_text is None else cancel_text, callback)
    self.set_text(text)

  def set_text(self, text):
    description = unescape(re.sub('<[^>]+>', ' ', str(text)))
    self._view._sections = [SettingSection('', [SettingRow('message', 'value', '', description)])]


def alert_dialog(message, button_text=None):
  return ConfirmDialog(message, button_text or 'OK', cancel_text='')
