"""Present existing settings actions as responsive rows without changing their policy."""
import re
from html import unescape

from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import AetherSettingsView, SettingRow, SettingSection
from openpilot.system.ui.lib.application import gui_app
from openpilot.starpilot.system.starpilot_auto.ui.settings_dialogs import alert_dialog
from openpilot.selfdrive.ui.widgets.ssh_key import SshKeyAction, SshKeyActionState
from openpilot.system.ui.widgets.list_view import ButtonAction, DualButtonAction, MultipleButtonAction, TextAction, ToggleAction


def resolve(value):
  return value() if callable(value) else value


def plain(value):
  return unescape(re.sub('<[^>]+>', ' ', str(value or ''))).strip()


def toggle_rows(definitions):
  return [SettingRow(f'toggle_{i}', 'toggle', definition['title'], definition.get('subtitle', ''),
                     enabled=definition.get('is_enabled'), disabled_label=definition.get('disabled_label', ''),
                     get_state=definition['get_state'], set_state=definition['set_state'])
          for i, definition in enumerate(definitions)]


def adjustor_rows(adjustors):
  return [SettingRow(key, 'value', row._title, row._subtitle, get_value=row.formatted_value,
                     on_click=lambda row=row: row._set_active_state(True)) for key, row in adjustors.items()]


class ResponsiveScroller(AetherSettingsView):
  """Adapt car-owned ListItems, preserving live labels, locks and callbacks."""
  def __init__(self, items, **_kwargs):
    super().__init__(self, [])
    self._items = items
    self._choices = None

  def show_event(self):
    super().show_event()
    for item in self._items:
      item.show_event()
      if item.description_opened_callback:
        item.description_opened_callback()

  def _set_toggle(self, item, value):
    action = item.action_item
    if not item.enabled or not action.enabled:
      return
    action.set_state(value)
    if action.toggle._callback:
      action.toggle._callback(value)
    if item.callback:
      item.callback()

  def _select(self, action, index):
    if action.enabled:
      action.set_selected_button(index)
      if action.callback:
        action.callback(index)
    self.back()

  def _choose(self, item):
    self._choices = item
    self._scroll_panel.set_offset(0)

  def back(self):
    if self._choices is None:
      return False
    self._choices = None
    self._scroll_panel.set_offset(0)
    return True

  def _render(self, rect):
    rows = []
    if self._choices is not None:
      item = self._choices
      rows = [SettingRow('back', 'value', 'Back', on_click=self.back)] + [
        SettingRow(str(i), 'value', resolve(label), get_value=lambda i=i: 'Selected' if item.action_item.get_selected_button() == i else '',
                   enabled=lambda: item.action_item.enabled, on_click=lambda i=i: self._select(item.action_item, i))
        for i, label in enumerate(item.action_item.buttons)
      ]
    else:
      for index, item in enumerate(self._items):
        if not item.is_visible:
          continue
        # Some ListItem subclasses refresh button text/enabled state here.
        item._update_state()
        action = item.action_item
        description = plain(item.description)
        subtitle = description if len(description) < 180 else description[:150].rsplit(' ', 1)[0] + '…'
        def enabled(item=item, action=action):
          return item.enabled and (action is None or action.enabled)
        key = str(index)
        if isinstance(action, ToggleAction):
          rows.append(SettingRow(key, 'toggle', item.title, subtitle, enabled=enabled,
                                 get_state=action.get_state, set_state=lambda value, item=item: self._set_toggle(item, value)))
        elif isinstance(action, DualButtonAction):
          for side, button in enumerate((action.left_button, action.right_button)):
            if button.is_visible:
              rows.append(SettingRow(f'{key}:{side}', 'value', resolve(button._label._text),
                                     enabled=lambda button=button, enabled=enabled: enabled() and button.enabled,
                                     on_click=button._click_callback))
        elif isinstance(action, MultipleButtonAction):
          rows.append(SettingRow(key, 'value', item.title, subtitle, enabled=enabled,
                                 get_value=lambda action=action: resolve(action.buttons[action.get_selected_button()]),
                                 on_click=lambda item=item: self._choose(item)))
        elif isinstance(action, SshKeyAction):
          if action._error_message:
            gui_app.push_widget(alert_dialog(action._error_message))
            action._error_message = ''
          rows.append(SettingRow(key, 'value', item.title, action._username or subtitle,
                                 enabled=lambda action=action: action.enabled and action._state != SshKeyActionState.LOADING,
                                 get_value=lambda action=action: action._state.value, on_click=action._handle_button_click))
        elif isinstance(action, (ButtonAction, TextAction)):
          rows.append(SettingRow(key, 'value', item.title, subtitle, enabled=enabled, on_click=item.callback,
                                 get_value=lambda action=action: (action.value or action.text) if isinstance(action, ButtonAction) else action.text))
          if isinstance(action, ButtonAction) and action._button._long_press_callback:
            rows.append(SettingRow(key + ':fast', 'value', 'Fast Update', 'Use the existing fast-update workflow.',
                                   enabled=enabled, on_click=action._button._long_press_callback))
        else:
          rows.append(SettingRow(key, 'value', item.title, subtitle, enabled=enabled, on_click=item.callback))
        if len(description) >= 180:
          rows.append(SettingRow(key + ':details', 'value', 'About ' + item.title,
                                 on_click=lambda description=description: gui_app.push_widget(alert_dialog(description))))
    self._sections = [SettingSection('', rows)]
    super()._render(rect)


def render_existing(manager, rect, sections):
  if not hasattr(manager, '_responsive_view'):
    manager._responsive_view = manager._child(AetherSettingsView(manager._controller, sections))
  manager._responsive_view._sections = sections
  manager._responsive_view.set_parent_rect(rect)
  manager._responsive_view.render(rect)
