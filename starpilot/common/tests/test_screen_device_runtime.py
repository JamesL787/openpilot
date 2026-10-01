"""Run the real Device class without opening a display or native IPC sockets."""
import ast
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.starpilot.common import screen_settings as screen


class Params:
  def __init__(self, values):
    self.values = values
  def get(self, key):
    return self.values.get(key)
  def get_int(self, key, **kwargs):
    return int(self.values.get(key, 101 if 'Brightness' in key else 30))
  def get_bool(self, key):
    return bool(self.values.get(key, False))


class Messages(dict):
  def __init__(self):
    super().__init__(selfdriveState=SimpleNamespace(enabled=False, alertSize='none', alertStatus='normal'),
                     starpilotSelfdriveState=SimpleNamespace(alertSize='none', alertStatus='normal'),
                     carState=SimpleNamespace(leftBlinker=False, rightBlinker=False, brakePressed=False, gasPressed=False,
                                              gearShifter='drive', buttonEvents=[]))
    self.updated = dict.fromkeys(self, True)
    self.recv_frame = dict.fromkeys(self, 1)
    self.recv_time = dict.fromkeys(self, 100)
    self.logMonoTime = dict.fromkeys(self, 1)
    self.valid = dict.fromkeys(self, True)
    self.alive = dict.fromkeys(self, True)


def make_device(*, device_type="tici", **settings):
  status = Enum('UIStatus', 'DISENGAGED ENGAGED OVERRIDE')
  state = SimpleNamespace(started=True, ignition=True, status=status.DISENGAGED, light_sensor=-1, started_time=0, started_frame=0, starpilot_toggles={},
                          params_memory=Params({}), ui_params=Params({'ScreenManagement': True, 'ScreenBrightness': 101,
                                           'ScreenBrightnessOnroad': 101, 'StandbyMode': True, **settings}), sm=Messages())
  rendering = {'value': True}
  app = SimpleNamespace(target_fps=20, big_ui=lambda: False, mouse_events=[],
                        set_should_render=lambda value: rendering.__setitem__('value', value),
                        ui_stream_wants_frames=lambda: False, starpilot_auto_enabled=False)
  app.rendering = rendering
  clock = {'now': 100}
  app.clock = clock
  env = {**vars(screen), 'ui_state': state, 'gui_app': app, 'UIStatus': status, 'BACKLIGHT_OFFROAD': 65,
         'STREAM_OFFROAD_HOLD_MAX': 600.0, 'STARPILOT_AUTO_SLEEP_STALE_GRACE': 3.0, 'STARPILOT_AUTO_SLEEP_DEVICES': ('mici', 'tizi', 'tici'),
         'STARPILOT_AUTO_SLEEP_WAKE_KEYS': frozenset({'StandbyWakeWarningAlert', 'StandbyWakeCriticalAlert'}),
         'CarScreenSettings': lambda: SimpleNamespace(poll=lambda: {'sleep_device_screen': False}),
         'FrameProducer': lambda path: None, 'CAR_FRAME_PATH': '',
         'np': np, 'time': SimpleNamespace(monotonic=lambda: clock['now']), 'FirstOrderFilter': FirstOrderFilter,
         'Callable': Callable, 'HARDWARE': SimpleNamespace(set_display_power=lambda value: None, get_device_type=lambda: device_type),
         'cloudlog': SimpleNamespace(debug=lambda value: None), 'PC': False, 'TICI': True}
  source = Path(__file__).resolve().parents[3] / 'selfdrive/ui/ui_state.py'
  node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'Device')
  exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), env)
  device = env['Device']()
  device._brightness_filter = SimpleNamespace(update=lambda value: value)
  device._ignition = True
  device._interaction_time = 90
  return device, state, app


def test_driving_and_parked_offsets_apply_independently():
  device, state, _ = make_device(StandbyMode=False, ScreenBrightnessOffset=-20, ScreenBrightnessOnroadOffset=15)
  assert device._calculate_brightness() == 75
  state.started = False
  assert device._calculate_brightness() == 52


@pytest.mark.parametrize('wake', ['button', 'touch', 'offroad', 'ignition', 'critical'])
@pytest.mark.parametrize('management', [False, True])
def test_manual_screen_off_and_wake_only_change_display(wake, management):
  device, state, app = make_device(ScreenManagement=management, StandbyMode=False)
  original_settings = dict(state.ui_params.values)
  state.params_memory.values[screen.SCREEN_OFF_TOGGLE_PARAM] = 1
  device._update_wakefulness()
  assert not device.awake
  assert device._calculate_brightness() == 0
  device._update_wakefulness()
  assert not device.awake
  if wake == 'button':
    state.params_memory.values[screen.SCREEN_OFF_TOGGLE_PARAM] = 2
  elif wake == 'touch':
    app.mouse_events = [SimpleNamespace(left_down=True)]
  elif wake == 'offroad':
    state.started = False
  elif wake == 'ignition':
    state.ignition = False
  else:
    state.sm['selfdriveState'].alertStatus = 'critical'
    state.sm['selfdriveState'].alertSize = 'full'
  device._update_wakefulness()
  assert device.awake
  assert device._calculate_brightness() > 0
  assert state.ui_params.values == original_settings


def test_screen_off_action_ignores_offroad_and_old_requests():
  device, state, app = make_device(StandbyMode=False)
  state.started = False
  state.params_memory.values[screen.SCREEN_OFF_TOGGLE_PARAM] = 1
  device._update_wakefulness()
  assert device.awake
  state.started = True
  device._update_wakefulness()
  assert device.awake
  app.mouse_events = [SimpleNamespace(left_down=True)]
  state.params_memory.values[screen.SCREEN_OFF_TOGGLE_PARAM] = 2
  device._update_wakefulness()
  assert not device.awake


def test_offset_is_ignored_in_manual_and_when_screen_settings_disabled():
  device, _, _ = make_device(StandbyMode=False, ScreenBrightnessOnroad=22, ScreenBrightnessOnroadOffset=50)
  assert device._calculate_brightness() == 22
  device._params.values['ScreenManagement'] = False
  device._refresh_screen_settings(force=True)
  assert device._calculate_brightness() == 65


def test_parked_zero_can_be_woken_by_touch_then_times_out_without_standby():
  device, state, app = make_device(StandbyMode=False, ScreenBrightness=0)
  state.started = state.ignition = device._ignition = False
  assert device._calculate_brightness() == 0
  app.mouse_events = [SimpleNamespace(left_down=True)]
  device._update_wakefulness()
  assert device._calculate_brightness() == 5
  app.mouse_events = []
  device._interaction_time = 90
  device._update_wakefulness()
  assert not device.awake
  assert device._calculate_brightness() == 0


@pytest.mark.parametrize('key,field,value', [
  ('StandbyWakeInfoAlert', 'alertSize', 'small'),
  ('StandbyWakeWarningAlert', 'alertStatus', 'userPrompt'),
  ('StandbyWakeCriticalAlert', 'alertStatus', 'critical'),
])
def test_only_selected_alert_categories_wake(key, field, value):
  settings = dict.fromkeys(screen.SCREEN_WAKE_KEYS, False)
  device, state, _ = make_device(**settings)
  state.sm['selfdriveState'].alertSize = 'small'
  setattr(state.sm['selfdriveState'], field, value)
  device._update_wakefulness()
  assert device._calculate_brightness() == 0
  device._params.values[key] = True
  device._refresh_screen_settings(force=True)
  device._interaction_time = 90
  device._update_wakefulness()
  assert device._calculate_brightness() == 65


@pytest.mark.parametrize('key,field', [
  ('StandbyWakeTurnSignal', 'leftBlinker'),
])
def test_selected_driver_input_wakes_once_and_can_sleep_while_held(key, field):
  device, state, _ = make_device(**dict.fromkeys(screen.SCREEN_WAKE_KEYS, False))
  device._params.values[key] = True
  device._refresh_screen_settings(force=True)
  device._update_wakefulness()
  setattr(state.sm['carState'], field, True)
  device._update_wakefulness()
  assert device._calculate_brightness() == 65
  device._interaction_time = 90
  device._update_wakefulness()
  assert device._calculate_brightness() == 0


def test_runtime_limits_legacy_offsets_to_thirty_percent():
  device, state, _ = make_device(StandbyMode=False, ScreenBrightnessOffset=-100, ScreenBrightnessOnroadOffset=-100)
  assert device._calculate_brightness() == 46
  state.started = False
  assert device._calculate_brightness() == 46


@pytest.mark.parametrize('key', sorted(screen.SCREEN_WAKE_KEYS))
@pytest.mark.parametrize('selected', [False, True])
def test_every_wake_choice_controls_its_own_event(key, selected):
  settings = dict.fromkeys(screen.SCREEN_WAKE_KEYS, False)
  settings[key] = selected
  device, state, app = make_device(**settings)
  device._update_wakefulness()  # Seed signals; startup is not a driver event.
  if key == 'StandbyWakeEngage':
    state.sm['selfdriveState'].enabled = True
    state.status = type(state.status).ENGAGED
  elif key == 'StandbyWakeDisengage':
    state.sm['selfdriveState'].enabled = True
    state.status = type(state.status).ENGAGED
    device._update_wakefulness()
    state.sm['selfdriveState'].enabled = False
    state.status = type(state.status).DISENGAGED
  elif key.endswith('Alert'):
    alert = state.sm['selfdriveState']
    alert.alertSize = 'small'
    alert.alertStatus = {'StandbyWakeInfoAlert': 'normal', 'StandbyWakeWarningAlert': 'userPrompt', 'StandbyWakeCriticalAlert': 'critical'}[key]
  elif key == 'StandbyWakeButton':
    state.params_memory.values['StandbyButtonPressTime'] = 99_500_000_000
  elif key == 'StandbyWakeTurnSignal':
    state.sm['carState'].leftBlinker = True
  else:
    pytest.fail('No stimulus for wake option ' + key)
  device._interaction_time = 90
  device._update_wakefulness()
  assert (device._calculate_brightness() > 0) is selected


def test_external_button_press_is_fresh_and_consumed_once():
  settings = dict.fromkeys(screen.SCREEN_WAKE_KEYS, False)
  settings['StandbyWakeButton'] = True
  device, state, _ = make_device(**settings)
  device._update_wakefulness()
  state.params_memory.values['StandbyButtonPressTime'] = 99_500_000_000
  device._update_wakefulness()
  assert (device._calculate_brightness() > 0) is True
  device._interaction_time = 90
  device._update_wakefulness()
  assert device._calculate_brightness() == 0
  state.params_memory.values['StandbyButtonPressTime'] = 95_000_000_000
  device._update_wakefulness()
  assert device._calculate_brightness() == 0


def test_consumed_button_press_is_not_replayed_between_ui_frames():
  device, state, _ = make_device(StandbyWakeButton=True)
  device._update_wakefulness()
  state.params_memory.values['StandbyButtonPressTime'] = 99_500_000_000
  device._update_wakefulness()
  assert device._calculate_brightness() > 0
  device._interaction_time = 90
  device._update_wakefulness()
  assert device._calculate_brightness() == 0


def test_hidden_secondary_alert_does_not_bypass_primary_category_selection():
  settings = dict.fromkeys(screen.SCREEN_WAKE_KEYS, False)
  settings['StandbyWakeInfoAlert'] = True
  device, state, _ = make_device(**settings)
  state.sm['selfdriveState'].alertStatus = 'critical'
  state.sm['selfdriveState'].alertSize = 'full'
  state.sm['starpilotSelfdriveState'].alertSize = 'small'
  device._update_wakefulness()
  assert device._active_standby_alerts() == {'StandbyWakeCriticalAlert'}
  assert device._calculate_brightness() == 0


@pytest.mark.parametrize('device_type', ['tici', 'mici'])
def test_dom_alert_predicate_does_not_depend_on_renderer_hide_setting(device_type):
  device, state, _ = make_device(device_type=device_type)
  state.starpilot_toggles['hide_alerts'] = True
  state.sm['selfdriveState'].alertSize = 'small'
  device._update_wakefulness()
  assert (device._calculate_brightness() > 0) is True


def test_bluetooth_wake_during_ignition_only_standby():
  settings = dict.fromkeys(screen.SCREEN_WAKE_KEYS, False)
  settings["StandbyWakeButton"] = True
  device, state, _ = make_device(**settings)
  state.started = False
  state.ignition = device._ignition = True
  device._update_wakefulness()
  state.params_memory.values['StandbyButtonPressTime'] = 99_500_000_000
  device._update_wakefulness()
  assert (device._calculate_brightness() > 0) is True


# ------------------------------------------------- streaming keeps frames alive


def _sleep_the_display(device, state, app):
  """Drive the device to display-off via the interactive timeout."""
  state.started = state.ignition = device._ignition = False
  app.mouse_events = []
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()


def test_stream_viewer_keeps_rendering_while_display_sleeps():
  device, state, app = make_device(StandbyMode=False)
  app.ui_stream_wants_frames = lambda: True
  _sleep_the_display(device, state, app)
  # The panel is off -- no burn-in, no backlight power -- but frames keep coming
  # so the stream does not stop.
  assert device.awake is False
  assert app.rendering['value'] is True


def test_rendering_follows_display_without_a_viewer():
  device, state, app = make_device(StandbyMode=False)
  app.ui_stream_wants_frames = lambda: False
  _sleep_the_display(device, state, app)
  assert device.awake is False
  assert app.rendering['value'] is False


def test_offroad_stream_hold_is_capped():
  device, state, app = make_device(StandbyMode=False)
  app.ui_stream_wants_frames = lambda: True
  _sleep_the_display(device, state, app)
  assert app.rendering['value'] is True

  # A tab left open on a parked car must not render forever.
  app.clock['now'] += 601
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  assert app.rendering['value'] is False


def test_onroad_stream_hold_is_not_capped():
  device, state, app = make_device(StandbyMode=True)
  app.ui_stream_wants_frames = lambda: True
  state.started = state.ignition = device._ignition = True
  app.mouse_events = []
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  assert app.rendering['value'] is True

  app.clock['now'] += 10_000
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  # Ignition is on, so there is no drain to bound.
  assert app.rendering['value'] is True


def test_offroad_cap_is_a_budget_a_reconnecting_viewer_cannot_refill():
  # Viewers come and go: a stream reconnect, a snapshot, a tab returning from
  # the background. A gap in demand must not hand out a fresh 10 minutes, or a
  # forgotten tab would render a parked car forever.
  device, state, app = make_device(StandbyMode=False)
  app.ui_stream_wants_frames = lambda: True
  _sleep_the_display(device, state, app)
  assert app.rendering['value'] is True

  app.clock['now'] += 590
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  assert app.rendering['value'] is True

  # Viewer drops (the streamer pauses), then reconnects a moment later.
  app.ui_stream_wants_frames = lambda: False
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  assert app.rendering['value'] is False
  app.clock['now'] += 20
  app.ui_stream_wants_frames = lambda: True
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  assert app.rendering['value'] is True  # 590 s spent, still inside the budget

  app.clock['now'] += 20
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  assert app.rendering['value'] is False  # 610 s held in total


def test_offroad_budget_is_not_spent_while_nobody_watches():
  # The idle hour between viewers is not charged to the budget either.
  device, state, app = make_device(StandbyMode=False)
  app.ui_stream_wants_frames = lambda: False
  _sleep_the_display(device, state, app)
  assert app.rendering['value'] is False

  app.clock['now'] += 3600
  app.ui_stream_wants_frames = lambda: True
  device._interaction_time = app.clock['now'] - 1
  device._update_wakefulness()
  assert app.rendering['value'] is True


def test_waking_the_display_resets_the_stream_hold():
  device, state, app = make_device(StandbyMode=False)
  app.ui_stream_wants_frames = lambda: True
  _sleep_the_display(device, state, app)
  assert device._stream_hold_since != 0.0

  app.mouse_events = [SimpleNamespace(left_down=True)]
  device._update_wakefulness()
  assert device.awake is True
  assert app.rendering['value'] is True
  assert device._stream_hold_since == 0.0
