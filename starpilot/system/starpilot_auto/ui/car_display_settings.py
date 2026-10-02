"""Car-display controls backed by the same settings as Galaxy."""
from openpilot.starpilot.system.starpilot_auto import car_screen
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import AetherSettingsView, SettingRow, SettingSection
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.panel import FrameCachedParams
from openpilot.system.ui.lib.application import gui_app
from openpilot.starpilot.system.starpilot_auto.ui.settings_dialogs import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets import DialogResult

LAYOUTS = [('split', 'Map + Driving'), ('driving', 'Driving View'), ('map', 'Map Only')]
ORIENTATIONS = [('north_up', 'North Up'), ('heading_up', 'Heading Up')]
POSITIONS = {'left': 'Left', 'center': 'Between', 'right': 'Right'}
STATUS_POSITION_TITLES = {'split': 'Map + Driving', 'driving': 'Driving View', 'map': 'Map Only'}
DISPLAY_ON_WARNING = ('Keep the comma display on while Starpilot Auto is connected? The comma then draws its own screen ' +
                      'as well as the car\'s, which uses additional CPU.')


class CarDisplaySettings(AetherSettingsView):
  def __init__(self, metrics=False):
    self._settings = car_screen.CarScreenSettings()
    self._params = FrameCachedParams()
    self._choices = None
    sections = [SettingSection('Layout', [
      self.choice('onroad_view', 'While Driving', LAYOUTS, 'Choose what appears on the car display.'),
      self.choice('map_side', 'Map Side', [('left', 'Left'), ('right', 'Right')],
                  visible=lambda: self.current['onroad_view'] == 'split'),
      self.choice('directions_side', 'Directions Side', [('left', 'Left'), ('right', 'Right')],
                  'Where the next-turn card sits on the driving view when the map is not beside it.',
                  visible=lambda: self.current['onroad_view'] != 'map'),
      self.choice('map_orientation', 'Map Orientation', ORIENTATIONS,
                  visible=lambda: self.current['onroad_view'] != 'driving'),
      self.toggle('camera', 'Show Road Camera', 'Keep speed, driving status and alerts visible when the camera is hidden.',
                  visible=lambda: self.current['onroad_view'] != 'map'),
      self.toggle('show_current_speed', 'Show Current Speed', 'The speed readout at the top of the driving view.',
                  visible=lambda: self.current['onroad_view'] != 'map'),
    ]), SettingSection('Blind Spots', [
      self.toggle('blind_spot_monitors', 'Show Blind Spot Monitors', 'Show blind-spot borders, lane warnings and configured side cameras.'),
      SettingRow('blind_spot_min_speed_ms', 'value', 'Blind Spot Minimum Speed',
                 'Set 0 to show monitors at every speed.',
                 visible=lambda: self.current['blind_spot_monitors'], get_value=self._speed_text, on_click=self._speed_picker),
    ]), SettingSection('Comma Display', [
      SettingRow('sleep_device_screen', 'toggle', 'Turn Off Comma Display',
                 'After the screen timeout while Starpilot Auto is connected. Tap the comma to wake it; ' +
                 'connection loss and critical alerts always wake it. On by default on comma four; off by default on comma 3X.',
                 get_state=lambda: self.current['sleep_device_screen'], set_state=self._set_sleep),
    ]), SettingSection('Wake Comma Display For', [
      SettingRow(f'wake_{key}', 'toggle', label, visible=lambda: self.current['sleep_device_screen'],
                 get_state=lambda key=key: key in self.current['sleep_wake_events'],
                 set_state=lambda value, key=key: self._set_wake(key, value))
      for key, label in car_screen.SLEEP_WAKE_EVENTS.items()
    ], visible=lambda: self.current['sleep_device_screen'])]
    if metrics:
      shown = lambda: self.current['show_status_column']
      sections = [SettingSection('Status Column', [
        self.toggle('show_status_column', 'Show Status Column', 'Turn off to hide the status column on the car display.'),
        *[SettingRow(f'slot_{i}', 'value', f'Slot {i + 1}', visible=shown,
                   get_value=lambda i=i: car_screen.STATUS_METRICS[self.current['status_slots'][i]][1],
                   on_click=lambda i=i: self._slot_picker(i)) for i in range(car_screen.STATUS_SLOT_COUNT)]
      ]), SettingSection('Status Column Position', [
        self.choice(f'status_position_{view}', STATUS_POSITION_TITLES[view], [(p, POSITIONS[p]) for p in positions],
                    'Between puts it between the driving view and the map.' if 'center' in positions else '',
                    visible=shown)
        for view, positions in car_screen.STATUS_POSITIONS.items()
      ], visible=shown)]
    super().__init__(self, sections, header_title='Status Widgets' if metrics else 'Car Display',
                     header_subtitle='Car display only · Changes also appear in Galaxy.')
    self._root_sections = sections

  @property
  def current(self):
    return self._settings.poll()

  def update(self, change):
    try:
      self._settings.current = car_screen.update(change)
    except (OSError, ValueError) as error:
      gui_app.push_widget(alert_dialog(f'Could not save the car display setting: {error}'))

  def toggle(self, key, title, subtitle='', visible=None):
    return SettingRow(key, 'toggle', title, subtitle, visible=visible,
                      get_state=lambda: self.current[key], set_state=lambda value: self.update({key: value}))

  def choice(self, key, title, options, subtitle='', visible=None):
    return SettingRow(key, 'value', title, subtitle, visible=visible,
                      get_value=lambda: dict(options)[self.current[key]],
                      on_click=lambda: self._pick(title, options, self.current[key], lambda value: self.update({key: value})))

  def _set_sleep(self, value):
    if value:
      self.update({'sleep_device_screen': True})
      return
    def confirm(result):
      if result == DialogResult.CONFIRM:
        self.update({'sleep_device_screen': False})
    gui_app.push_widget(ConfirmDialog(DISPLAY_ON_WARNING, 'Keep It On', callback=confirm))

  def _set_wake(self, key, value):
    # Read the latest version so another display's changes are preserved.
    events = [event for event in car_screen.load()['sleep_wake_events'] if event != key]
    if value:
      events.append(key)
    self.update({'sleep_wake_events': [event for event in car_screen.SLEEP_WAKE_EVENTS if event in events]})

  def _pick(self, title, options, current, apply):
    # Inline, scrollable choices fit short screens and retain a single Back path.
    def choose(value):
      apply(value)
      self.back()
    self._choices = self._header_title
    self._header_title = title
    self._sections = [SettingSection('', [SettingRow(str(i), 'value', label,
      get_value=lambda value=value: 'Selected' if value == current else '',
      on_click=lambda value=value: choose(value)) for i, (value, label) in enumerate(options)])]
    self._scroll_panel.set_offset(0)

  def back(self):
    if self._choices is None:
      return False
    self._header_title = self._choices
    self._choices = None
    self._sections = self._root_sections
    return True

  def _slot_picker(self, index):
    def apply(value):
      # Read the latest version so another display's changes are preserved.
      slots = car_screen.load()['status_slots']
      slots[index] = value
      self.update({'status_slots': slots})
    self._pick(f'Slot {index + 1}', [(key, item[1]) for key, item in car_screen.STATUS_METRICS.items()],
               self.current['status_slots'][index], apply)

  def _speed_text(self):
    metric = self._params.get_bool('IsMetric')
    factor = 3.6 if metric else 2.2369362921
    return f"{round(self.current['blind_spot_min_speed_ms'] * factor)} {'km/h' if metric else 'mph'}"

  def _speed_picker(self):
    from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import AetherSliderDialog
    from openpilot.system.ui.widgets import DialogResult
    metric = self._params.get_bool('IsMetric')
    factor = 3.6 if metric else 2.2369362921
    def apply(result, value):
      if result == DialogResult.CONFIRM:
        self.update({'blind_spot_min_speed_ms': value / factor})
    gui_app.push_widget(AetherSliderDialog('Blind Spot Minimum Speed', 0, 200 if metric else 125, 1,
      self.current['blind_spot_min_speed_ms'] * factor, apply, unit='km/h' if metric else 'mph'))
