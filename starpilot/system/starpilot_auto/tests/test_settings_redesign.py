"""Settings navigation, shared storage, and geometry across car screen sizes."""
from types import SimpleNamespace
from dataclasses import replace

import pyray as rl
import pytest

from openpilot.starpilot.system.starpilot_auto import car_screen
from openpilot.starpilot.system.starpilot_auto.ui import settings, settings_style as style
from openpilot.starpilot.system.starpilot_auto.ui.car_display_settings import CarDisplaySettings
from openpilot.starpilot.system.starpilot_auto.ui.settings_adapters import ResponsiveScroller
from openpilot.starpilot.system.starpilot_auto.ui.settings_dialogs import MultiOptionDialog, ConfirmDialog
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import AetherSliderDialog
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.list_view import toggle_item


@pytest.fixture
def fonts(monkeypatch):
  monkeypatch.setattr(style.gui_app, 'font', lambda *_: None)
  def measure(_font, value, size, **_kw):
    return SimpleNamespace(x=len(value) * size * .55, y=size)
  monkeypatch.setattr(style, 'measure_text_cached', measure)
  monkeypatch.setattr(settings, 'measure_text_cached', measure)
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot import aethergrid
  monkeypatch.setattr(aethergrid, 'measure_text_cached', measure)


@pytest.mark.parametrize('width', [280, 400, 560, 800, 1200, 2200])
@pytest.mark.parametrize('kind,value', [('toggle', ''), ('value', 'A long saved vehicle name'), ('action', 'Reset')])
def test_rows_reserve_space_for_text_and_controls(fonts, width, kind, value):
  height, text_width, size, sub_size, titles, subtitles, control, text_top, _stacked = style.row_layout(
    width, 'Turn Off Comma Display While Starpilot Auto Is Connected',
    'Tap the comma to wake it. Connection loss, warnings and critical alerts also wake it.', kind, value)
  assert height >= 96
  assert control.x >= 0 and control.x + control.width <= width
  assert control.y >= 0 and control.y + control.height <= height
  pad = style.ROW_PAD
  text_bottom = text_top + len(titles) * (size + style.LINE_GAP) + style.px(6) + len(subtitles) * (sub_size + style.LINE_GAP)
  assert pad <= text_top and text_bottom <= height - pad
  assert pad + text_width <= control.x or text_bottom <= control.y


def test_car_and_galaxy_updates_preserve_each_others_preferences(tmp_path, monkeypatch):
  path = tmp_path / 'car_screen.json'
  monkeypatch.setattr(car_screen, 'CAR_SCREEN_PATH', path)
  car = car_screen.CarScreenSettings(clock=lambda: 10)
  original = car.poll()
  car_screen.update({'map_side': 'left'})
  car_screen.update({'camera': False})
  assert original['map_side'] == 'right'
  assert car_screen.load()['map_side'] == 'left'
  assert not car_screen.load()['camera']
  before = path.read_bytes()
  with pytest.raises(ValueError):
    car_screen.update({'onroad_view': 'invalid'})
  with pytest.raises(ValueError):
    car_screen.update({'typo': True})
  assert path.read_bytes() == before


def test_car_display_hides_irrelevant_controls_and_applies_same_keys(fonts, tmp_path, monkeypatch):
  monkeypatch.setattr(car_screen, 'CAR_SCREEN_PATH', tmp_path / 'car_screen.json')
  view = CarDisplaySettings()
  view.update({'onroad_view': 'map'})
  ids = {row.id for section in view._sections for row in view._visible_rows(section)}
  assert 'map_orientation' in ids
  assert not {'camera', 'map_side'} & ids
  view.update({'blind_spot_monitors': False})
  ids = {row.id for section in view._sections for row in view._visible_rows(section)}
  assert 'blind_spot_min_speed_ms' not in ids
  view._pick('Map Side', [('left', 'Left'), ('right', 'Right')], 'right', lambda value: view.update({'map_side': value}))
  view._activate_target('value:0')
  assert car_screen.load()['map_side'] == 'left'
  assert view._choices is None


def test_car_display_warns_before_keeping_the_comma_display_on(fonts, tmp_path, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.ui import car_display_settings
  monkeypatch.setattr(car_screen, 'CAR_SCREEN_PATH', tmp_path / 'car_screen.json')
  pushed = []
  monkeypatch.setattr(car_display_settings.gui_app, 'push_widget', pushed.append)
  view = CarDisplaySettings()
  rows = {row.id: row for section in view._sections for row in section.rows}
  assert view.current['sleep_device_screen'] and rows['show_current_speed'].get_state()
  assert 'wake_StandbyWakeCriticalAlert' not in rows, 'critical alerts always wake the display'

  rows['sleep_device_screen'].set_state(False)
  assert isinstance(pushed[-1], ConfirmDialog) and 'additional CPU' in pushed[-1]._view._sections[0].rows[0].subtitle
  assert car_screen.load()['sleep_device_screen'], 'nothing changes until confirmed'
  pushed[-1]._callback(DialogResult.CANCEL)
  assert car_screen.load()['sleep_device_screen']
  pushed[-1]._callback(DialogResult.CONFIRM)
  assert not car_screen.load()['sleep_device_screen']
  ids = {row.id for section in view._sections if not section.visible or section.visible()
         for row in view._visible_rows(section)}
  assert not any(key.startswith('wake_') for key in ids), 'wake choices hide while the display stays on'

  rows['sleep_device_screen'].set_state(True)
  assert car_screen.load()['sleep_device_screen'] and len(pushed) == 1
  rows['wake_StandbyWakeTurnSignal'].set_state(True)
  rows['wake_StandbyWakeWarningAlert'].set_state(False)
  assert car_screen.load()['sleep_wake_events'] == ['StandbyWakeTurnSignal']
  rows['show_current_speed'].set_state(False)
  assert not car_screen.load()['show_current_speed']


def test_status_widgets_choose_the_column_position_per_layout(fonts, tmp_path, monkeypatch):
  monkeypatch.setattr(car_screen, 'CAR_SCREEN_PATH', tmp_path / 'car_screen.json')
  view = CarDisplaySettings(metrics=True)
  rows = {row.id: row for section in view._sections for row in section.rows}
  assert rows['status_position_split'].get_value() == 'Right'
  rows['status_position_split'].on_click()
  assert [row.title for row in view._sections[0].rows] == ['Left', 'Between', 'Right']
  view._activate_target('value:1')
  assert car_screen.load()['status_position_split'] == 'center'
  rows['status_position_map'].on_click()
  assert [row.title for row in view._sections[0].rows] == ['Left', 'Right']


class PageSpy(Widget):
  def __init__(self):
    super().__init__()
    self.events = []
    self._current_sub_panel = ''

  def show_event(self):
    self.events.append(('show', self._current_sub_panel))

  def hide_event(self):
    self.events.append(('hide', self._current_sub_panel))

  def set_current_sub_panel(self, value):
    self._current_sub_panel = value

  def _render(self, rect):
    pass


@pytest.fixture
def shell(fonts, monkeypatch, mocker):
  monkeypatch.setattr(settings, 'CarStarPilotLayout', mocker.Mock)
  def build(self):
    self._pages = {
      'display': settings.SettingsPage('display', 'Layout', 'Car Display', PageSpy()),
      'steering': settings.SettingsPage('steering', 'Steering', 'Driving', PageSpy(), 'behavior'),
      'bluetooth': settings.SettingsPage('bluetooth', 'Bluetooth', 'Connections', PageSpy()),
    }
  monkeypatch.setattr(settings.CarSettingsLayout, '_build_pages', build)
  return settings.CarSettingsLayout()


def test_page_changes_and_back_preserve_lifecycle_without_folder_hops(shell):
  shell.show_event()
  display = shell._current.widget
  shell.open_page('steering')
  owner = shell._current.widget
  assert display.events[-1] == ('hide', '')
  assert owner.events[-1] == ('show', 'behavior')
  owner._current_sub_panel = 'advanced'
  shell._navigate('advanced')
  assert owner.events[-2:] == [('hide', 'behavior'), ('show', 'advanced')]
  shell._back()
  assert owner._current_sub_panel == 'behavior'
  assert not shell._history
  shell.open_page('bluetooth')
  assert shell._section == 'Connections'
  assert shell._remembered['Driving'] == 'steering'
  shell.hide_event()
  assert shell._current.widget.events[-1] == ('hide', '')


def test_adapted_toggle_preserves_callback_and_lock(fonts, mocker):
  callback = mocker.Mock()
  item = toggle_item('Feature', initial_state=False, callback=callback)
  scroller = ResponsiveScroller([item])
  scroller._set_toggle(item, True)
  callback.assert_called_once_with(True)
  assert item.action_item.get_state()
  item.action_item.set_enabled(False)
  scroller._set_toggle(item, False)
  assert item.action_item.get_state()
  callback.assert_called_once()


@pytest.mark.parametrize('size', [(480, 800), (800, 480), (1280, 720), (1920, 720), (2560, 1080)])
def test_dialog_footers_and_slider_controls_fit(fonts, monkeypatch, size, mocker):
  # Use measured layout with drawing disabled; assert all actionable bounds.
  for name in ('draw_rectangle_rec', 'draw_rectangle_rounded', 'draw_rectangle_rounded_lines_ex', 'draw_text_ex', 'draw_circle_v'):
    monkeypatch.setattr(rl, name, lambda *_args: None)
  rect = rl.Rectangle(0, 0, *size)
  for dialog in (MultiOptionDialog('Choose a car', ['Car A', 'Car B'], 'Car A'), ConfirmDialog('Long confirmation message', 'Confirm')):
    dialog._view.render = mocker.Mock()
    dialog._render(rect)
    assert not rl.check_collision_recs(dialog._targets['confirm'], dialog._targets['cancel'])
    for bounds in dialog._targets.values():
      assert 0 <= bounds.x < bounds.x + bounds.width <= size[0]
      assert 0 <= bounds.y < bounds.y + bounds.height <= size[1]
      assert bounds.height >= 48
  slider = AetherSliderDialog('Minimum Speed', 0, 125, 1, 30, mocker.Mock(), presets=[0, 25, 50, 75, 100, 125])
  slider._render(rect)
  bounds = [slider._ok_rect, slider._cancel_rect, slider._minus_rect, slider._plus_rect, slider._track_rect]
  for index, box in enumerate(bounds):
    assert 0 <= box.x < box.x + box.width <= size[0]
    assert 0 <= box.y < box.y + box.height <= size[1]
    assert not any(rl.check_collision_recs(box, other) for other in bounds[index + 1:])


def test_selection_cancel_does_not_apply_changes(fonts, monkeypatch, mocker):
  callback = mocker.Mock()
  monkeypatch.setattr(style.gui_app, 'pop_widget', mocker.Mock())
  dialog = MultiOptionDialog('Choose a car', ['A', 'B'], 'A', callback=callback)
  dialog._on_option_clicked('B')
  dialog._set_result(DialogResult.CANCEL)
  callback.assert_called_once_with(DialogResult.CANCEL)


def test_bluetooth_pair_connect_and_confirm_use_existing_manager(fonts, monkeypatch, mocker):
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels import bluetooth
  from openpilot.starpilot.system.bluetooth.protocol import BluetoothStatus, BluetoothDevice
  new = BluetoothDevice('00:11:22:33:44:55', 'New car')
  saved = BluetoothDevice('00:11:22:33:44:66', 'Saved car', paired=True)
  manager = mocker.Mock()
  manager.status = BluetoothStatus(available=True, enabled=True, offroad=True, devices=(new, saved))
  manager.operation_for.return_value = ''
  page = bluetooth.BluetoothManagerUI.__new__(bluetooth.BluetoothManagerUI)
  page._manager = manager
  page._select_device(new.address)
  page._select_device(saved.address)
  manager.pair.assert_called_once_with(new.address)
  manager.connect.assert_called_once_with(saved.address)
  manager.status = replace(manager.status, offroad=False)
  page._select_device(new.address)
  manager.pair.assert_called_once()
  page._last_prompt_id = ''
  manager.status = replace(manager.status, prompt={'id': 'prompt-1', 'name': 'New car', 'kind': 'confirmation', 'value': '123456'})
  pushed = []
  monkeypatch.setattr(style.gui_app, 'push_widget', pushed.append)
  page._handle_prompt(manager.status)
  assert '123456' in pushed[0]._view._sections[0].rows[0].subtitle
  pushed[0]._callback(DialogResult.CONFIRM)
  manager.respond.assert_called_once_with('prompt-1', True)


def test_wifi_password_and_cancel_keep_connection_handlers(mocker):
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.network import WifiManagerUI, UIState
  from openpilot.system.ui.lib.wifi_manager import Network, SecurityType
  page = WifiManagerUI.__new__(WifiManagerUI)
  page.keyboard = mocker.Mock(text='password123')
  page.connect_to_network = mocker.Mock()
  network = Network('Home Wi-Fi', 90, SecurityType.OPEN, False)
  page._on_password_entered(network, DialogResult.CONFIRM)
  page.connect_to_network.assert_called_once_with(network, 'password123')
  page._on_password_entered(network, DialogResult.CANCEL)
  assert page.state == UIState.IDLE
  page.connect_to_network.assert_called_once()


def test_selected_page_stays_visible_after_resize(shell, monkeypatch):
  # No GPU: exercise the shell's real geometry with deterministic font metrics.
  for name in ('draw_rectangle_rec', 'draw_rectangle_rounded', 'draw_rectangle_rounded_lines_ex', 'draw_text_ex',
               'begin_scissor_mode', 'end_scissor_mode'):
    monkeypatch.setattr(rl, name, lambda *_args: None)
  monkeypatch.setattr(style, 'button', lambda *_args: None)
  monkeypatch.setattr(style, 'text', lambda *_args, **_kwargs: None)
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot import aethergrid
  monkeypatch.setattr(aethergrid, 'draw_chevron_icon', lambda *_args, **_kwargs: None)
  shell._nav_scroll.update = lambda *_: 0
  shell._tabs_scroll.update = lambda *_: shell._tabs_scroll.get_offset()
  for index in range(12):
    key = f'driving_{index}'
    shell._pages[key] = settings.SettingsPage(key, f'Driving Page {index}', 'Driving', PageSpy())
  shell.open_page('driving_11')
  for width in (1920, 800, 1280, 600):
    shell._render(rl.Rectangle(0, 0, width, 720))
    selected = shell._targets['page:driving_11']
    assert selected.width >= 130
    assert 0 <= selected.x < selected.x + selected.width <= width


def test_zoom_maps_touches_and_clipping_then_restores(monkeypatch, mocker):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  for name in ('rl_push_matrix', 'rl_pop_matrix', 'rl_scalef'):
    monkeypatch.setattr(rl, name, mocker.Mock())
  app = style.gui_app
  event = MouseEvent(MousePos(160, 320), 0, True, False, True, 0.0)
  monkeypatch.setattr(app, '_mouse_events', [event])
  monkeypatch.setattr(app, '_last_mouse_event', event)
  monkeypatch.setattr(app, '_scale', 0.5)
  patch = mocker.patch.object(app, '_patch_scissor_mode')
  with style.zoom(rl.Rectangle(160, 320, 800, 400), 1.6) as inner:
    assert (inner.x, inner.y, inner.width, inner.height) == (100, 200, 500, 250)
    assert app._mouse_events[0].pos == MousePos(100, 200) and app._last_mouse_event.pos == MousePos(100, 200)
    assert app._scale == 0.8 and style.zoom_level() == 1.6
  assert app._mouse_events == [event] and app._scale == 0.5 and style.zoom_level() == 1.0
  assert patch.call_count == 2
