"""Starpilot Auto connection controls; Bluetooth keeps ownership of pairing prompts."""
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.system.starpilot_auto.connection_help import recovery_hint, setup_instructions
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import AetherSettingsView, SettingRow, SettingSection
from openpilot.system.ui.lib.starpilot_auto_manager import StarpilotAutoManager
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import DialogResult
from openpilot.starpilot.system.starpilot_auto.ui.settings_dialogs import ConfirmDialog, alert_dialog


class StarpilotAutoSettings(AetherSettingsView):
  def __init__(self, open_bluetooth):
    self._manager = None
    self._open_bluetooth = open_bluetooth
    self._choosing = False
    self._waiting_devices = False
    self._pairing = False
    def ready():
      return self._manager is not None and bool(self.status) and not self._manager.busy

    def stopped():
      return ready() and not self.status.get('running')
    sections = [SettingSection('Connection', [
      SettingRow('status', 'value', 'Starpilot Auto', get_value=self._status_text),
      SettingRow('connect', 'value', 'Projection', get_value=lambda: 'Disconnect' if self.status.get('running') else 'Connect',
                 enabled=ready, on_click=self._connect),
      SettingRow('car', 'value', 'Car', get_value=lambda: self.status.get('receiver_name') or 'Choose a car',
                 enabled=stopped, disabled_label='Disconnect before changing the car.', on_click=self._choose_car,
                 visible=lambda: self.status.get('connection') != 'wired'),
      SettingRow('auto', 'toggle', 'Connect Automatically', 'Connect to your car at the start of every drive, over Bluetooth or USB.',
                 get_state=lambda: self.status.get('auto_connect', True),
                 set_state=lambda value: self._manager.set_auto_connect(value), enabled=ready),
      SettingRow('pair', 'value', 'Pair a New Car', 'Pair while parked. Confirm the code on both displays.',
                 on_click=self._pair, enabled=lambda: ready() and not ui_state.started,
                 disabled_label='Park and go offroad to pair a new car.', visible=lambda: self.status.get('connection') != 'wired'),
    ]), SettingSection('Setup & Advanced', [
      SettingRow('setup', 'value', 'Setup Help', 'First connection, automatic reconnect and cable requirements.',
                 on_click=lambda: gui_app.push_widget(alert_dialog(setup_instructions(self.status)))),
      SettingRow('transport', 'value', 'Connection Type', get_value=lambda: 'USB' if self.status.get('connection') == 'wired' else 'Wireless',
                 enabled=stopped, disabled_label='Disconnect before changing the connection type.',
                 on_click=lambda: self._manager.set_connection('wireless' if self.status.get('connection') == 'wired' else 'wired')),
      SettingRow('mirror', 'toggle', 'Mirror Comma Display', 'Use the comma layout instead of the independent car display.',
                 enabled=ready, get_state=lambda: self.status.get('configured_view', 'car') == 'mirror',
                 set_state=lambda value: self._manager.set_view('mirror' if value else 'car')),
      SettingRow('certificate', 'value', 'Certificate Setup',
                 'In Galaxy, open Toggles → Starpilot Auto → Starpilot Auto Certificate to install or renew your certificate.'),
      SettingRow('error', 'value', 'Last Connection Error', visible=lambda: bool(self.status.get('error')),
                 on_click=lambda: gui_app.push_widget(alert_dialog(recovery_hint(self.status) + '\n\n' + str(self.status.get('error', ''))))),
    ])]
    self._root_sections = sections
    super().__init__(self, sections, header_title='Starpilot Auto', header_subtitle='Connection and pairing · Display options are under Car Display.')

  @property
  def status(self):
    return self._manager.status if self._manager else {}

  def _status_text(self):
    status = self.status
    if not status:
      return 'Service unavailable · Check Bluetooth'
    if status.get('state') == 'streaming':
      return f"Connected to {status.get('receiver_name') or 'car'}"
    if status.get('auto_paused'):
      return 'Paused until next drive'
    return str(status.get('label') or status.get('state', 'Disconnected')).replace('_', ' ').capitalize()

  def _connect(self):
    if self.status.get('running'):
      gui_app.push_widget(ConfirmDialog('Disconnect Starpilot Auto? The car display will close.', 'Disconnect',
        callback=lambda result: self._manager.stop_projection() if result == DialogResult.CONFIRM and self._manager else None))
    else:
      self._manager.start()

  def _choose_car(self):
    self._manager.refresh_devices()
    self._waiting_devices = True

  def _pair(self):
    self._manager.prepare_pairing()
    self._pairing = True

  def back(self):
    if not self._choosing:
      return False
    self._sections = self._root_sections
    self._choosing = False
    self._scroll_panel.set_offset(0)
    return True

  def _select(self, device):
    self._manager.select_receiver(device['address'], device.get('name', ''))
    self.back()

  def _update_state(self):
    if not self._manager:
      return
    error = self._manager.consume_error()
    if error:
      self._pairing = self._waiting_devices = False
      gui_app.push_widget(alert_dialog(error))
    if self._pairing and not self._manager.busy:
      self._pairing = False
      self._open_bluetooth()
      return
    if self._waiting_devices and not self._manager.busy:
      self._waiting_devices = False
      self._choosing = True
      self._sections = [SettingSection('Choose a Car', [
        SettingRow(device['address'], 'value', device.get('name') or device['address'], device['address'],
                   on_click=lambda device=device: self._select(device)) for device in self._manager.devices
      ] or [SettingRow('empty', 'value', 'No paired cars', 'Choose Pair a New Car to get started.')])]
      self._scroll_panel.set_offset(0)

  def show_event(self):
    super().show_event()
    if self._manager is None:
      self._manager = StarpilotAutoManager()
    self._manager.set_active(True)

  def hide_event(self):
    if self._manager:
      self._manager.stop()
      self._manager = None
    self._pairing = self._waiting_devices = False
    self.back()
    super().hide_event()
