import time
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.mici.layouts.settings import starpilot_auto, starpilot_auto_state as state, bluetooth


@pytest.mark.parametrize("status,expected", [
  ({}, "starting"),
  ({"state": "streaming", "stats": {"fps": 30.0}}, "projecting, 30 fps"),
  ({"state": "suspended"}, "car showing its screen"),
  ({"state": "backoff", "retry_in": 7.6}, "retrying in 8 s"),
  ({"state": "waiting_for_usb", "connection": "wired"}, "waiting for usb"),
  ({"state": "idle", "error": "boom"}, "stopped with an error"),
  ({"state": "idle", "connection": "wireless", "receiver_name": ""}, "choose a car"),
  ({"state": "idle", "connection": "wired", "auto_connect": True}, "starts next drive"),
  ({"state": "idle", "receiver_name": "Civic", "auto_connect": True, "auto_paused": True}, "paused until next drive"),
  ({"state": "idle", "receiver_name": "Civic", "auto_connect": False}, "off"),
  ({"state": "joining_wifi", "label": "joining car wi-fi"}, "joining car wi-fi"),
])
def test_status_value_is_short(status, expected):
  assert state.status_value(status) == expected
  assert len(expected) <= 24 and expected.isascii(), "a card's value line, in glyphs the font has"


def test_cards_follow_the_connection_and_what_can_change():
  wireless = {"state": "idle", "connection": "wireless", "receiver_address": "AA", "running": False}
  wired = {**wireless, "connection": "wired", "receiver_address": ""}
  assert state.show_car(wireless) and not state.show_car(wired)
  assert state.show_pairing(wireless, offroad=True) and not state.show_pairing(wireless, offroad=False) and not state.show_pairing(wired, True)
  assert state.can_connect(wireless) and state.can_connect(wired) and not state.can_connect({**wireless, "receiver_address": ""})
  assert state.can_change_while(wireless) and not state.can_change_while({**wireless, "running": True})
  assert state.connect_label({"running": True}) == "Disconnect" and state.connect_label(wireless) == "Connect"
  assert state.connection_value(wired) == "USB" and state.view_value({"configured_view": "mirror"}) == "Screen Mirror"


def test_daemon_values_always_match_the_rendered_toggle_options():
  for connection in ("wireless", "wired"):
    assert state.connection_value({"connection": connection}) in state.CONNECTION_OPTIONS
  for view in ("car", "mirror"):
    assert state.view_value({"configured_view": view}) in state.VIEW_OPTIONS


def test_multi_toggle_survives_a_stale_display_value():
  toggle = starpilot_auto.BigMultiToggle.__new__(starpilot_auto.BigMultiToggle)
  toggle._options = ["Wireless", "USB"]
  toggle.value = "wireless"
  assert toggle._option_index() == 0
  toggle.value = "USB"
  assert toggle._option_index() == 1
  toggle.value = "usb"
  assert toggle._option_index() == 1, "a stale value keeps the last selection instead of jumping to the first"


def test_split_text_keeps_every_word_within_the_limit():
  text = "Could not find the car's Starpilot Auto service: [Errno 112] Host is down " * 4 + "x" * 130
  cards = state.split_text(text, 40)
  assert all(len(card) <= 40 for card in cards)
  assert "".join(cards).replace(" ", "") == text.replace(" ", "")
  assert state.split_text("short") == ["short"] and state.split_text("") == []


class FakeManager:
  def __init__(self, status=None):
    self.status = status or {"state": "idle", "connection": "wireless", "receiver_address": "AA:01", "receiver_name": "Civic",
                             "auto_connect": True, "configured_view": "car", "running": False}
    self.busy = False
    self.calls = []

  def __getattr__(self, name):
    return lambda *args: self.calls.append((name, *args))


@pytest.fixture
def ui(monkeypatch):
  pushed = []

  class Confirmation:
    def __init__(self, title, icon, callback, **kwargs):
      self.title, self.callback = title, callback

  class Options:
    def __init__(self, options, default, right_btn_callback):
      self.options, self.default, self.callback = options, default, right_btn_callback
      self.selected = default

    def get_selected_option(self):
      return self.selected

  monkeypatch.setattr(starpilot_auto, "BigConfirmationDialog", Confirmation)
  monkeypatch.setattr(starpilot_auto, "BigMultiOptionDialog", Options)
  monkeypatch.setattr(starpilot_auto, "BigDialog", lambda title, text: ("dialog", title, text))
  monkeypatch.setattr(starpilot_auto.gui_app, "push_widget", pushed.append)
  manager = FakeManager()
  page = starpilot_auto.StarpilotAutoLayoutMici.__new__(starpilot_auto.StarpilotAutoLayoutMici)
  page._manager, page._icon, page._pending = lambda: manager, None, {}
  cars = [SimpleNamespace(name="Civic", address="AA:01", paired=True, uuids=[]),
          SimpleNamespace(name="Ioniq", address="AA:02", paired=True, uuids=[str(starpilot_auto.STARPILOT_AUTO_WIRELESS_UUID)])]
  page._bluetooth = SimpleNamespace(status=SimpleNamespace(devices=cars, offroad=True))
  return SimpleNamespace(page=page, manager=manager, pushed=pushed)


@pytest.mark.parametrize("tap,value,call,title", [
  ("_auto_tapped", False, ("set_auto_connect", False), "Slide for Auto\nConnect Off"),
  ("_auto_tapped", True, ("set_auto_connect", True), "Slide for Auto\nConnect On"),
  ("_connection_tapped", "USB", ("set_connection", "wired"), "slide to\nuse USB"),
  ("_view_tapped", "Screen Mirror", ("set_view", "mirror"), "slide to\nmirror comma"),
  ("_view_tapped", "Starpilot Auto", ("set_view", "car"), "slide to use\nStarpilot Auto"),
])
def test_changes_wait_for_a_slide_to_confirm(ui, tap, value, call, title):
  getattr(ui.page, tap)(value)
  (dialog,) = ui.pushed
  assert dialog.title == title and ui.manager.calls == [], "nothing changes until the slide"
  dialog.callback()
  assert ui.manager.calls == [call]


def test_auto_connect_value_is_on_or_off():
  assert state.auto_connect_value(True) == "On"
  assert state.auto_connect_value(False) == "Off"


def test_connect_card_shows_live_status_and_real_error_excerpt():
  assert state.connect_status_value({"state": "streaming", "stats": {"fps": 30}}) == "projecting, 30 fps"
  value = state.connect_status_value({"state": "idle", "error": "finding starpilot auto: Could not find the car service"})
  assert value.startswith("Error: finding starpilot auto:") and value.endswith("...")
  assert len(value) <= state.CONNECT_STATUS_CHARS


def test_confirmed_value_shows_until_the_status_catches_up(ui):
  ui.page._auto_tapped(False)
  ui.pushed[0].callback()
  assert ui.page._shown("auto", True) is False, "the daemon has not caught up yet"
  assert ui.page._shown("auto", False) is False and "auto" not in ui.page._pending
  ui.page._pending["view"] = ("Screen Mirror", time.monotonic() - 1)
  assert ui.page._shown("view", "Starpilot Auto") == "Starpilot Auto", "a change that never lands stops showing"


def test_changing_the_car_confirms_but_the_first_car_does_not(ui):
  ui.page._choose_car()
  chooser = ui.pushed.pop()
  assert chooser.options == ["Ioniq", "Civic"] and chooser.default == "Civic", "cars with Starpilot Auto first, no suffix"
  chooser.selected = "Ioniq"
  chooser.callback()
  confirmation = ui.pushed.pop()
  assert confirmation.title == "slide to\nchange car" and ui.manager.calls == []
  confirmation.callback()
  assert ui.manager.calls == [("select_receiver", "AA:02", "Ioniq")]

  ui.manager.calls.clear()
  ui.manager.status["receiver_address"] = ""
  ui.page._choose_car()
  chooser = ui.pushed.pop()
  chooser.callback()
  assert ui.manager.calls == [("select_receiver", "AA:02", "Ioniq")] and not ui.pushed


def test_disconnect_is_one_tap(ui):
  ui.manager.status["running"] = True
  ui.page._connect_tapped()
  assert ui.manager.calls == [("stop_projection",)] and not ui.pushed


def test_long_errors_become_a_page_of_cards(monkeypatch):
  pushed = []
  monkeypatch.setattr(starpilot_auto.gui_app, "push_widget", pushed.append)
  monkeypatch.setattr(starpilot_auto, "BigDialog", lambda title, text: ("dialog", title, text))
  monkeypatch.setattr(starpilot_auto, "TextPage", lambda title, text, icon=None: ("page", title, text))
  starpilot_auto.show_text("Starpilot Auto", "Stop Starpilot Auto before changing the car")
  starpilot_auto.show_text("Starpilot Auto", "x " * 100)
  assert pushed[0][0] == "dialog" and pushed[1][0] == "page" and pushed[1][1] == "Starpilot Auto"


def test_bluetooth_device_actions_work_with_starpilot_auto_off(monkeypatch):
  pushed, calls = [], []
  monkeypatch.setattr(bluetooth.gui_app, "push_widget", pushed.append)

  class Options:
    def __init__(self, options, default, right_btn_callback):
      self.options, self.callback = options, right_btn_callback

    def get_selected_option(self):
      return "disconnect"

  monkeypatch.setattr(bluetooth, "BigMultiOptionDialog", Options)
  layout = bluetooth.BluetoothLayoutMici.__new__(bluetooth.BluetoothLayoutMici)
  layout._starpilot_auto = None
  layout._manager = SimpleNamespace(status=SimpleNamespace(selected_audio="", offroad=True),
                                    disconnect=lambda address: calls.append(address))
  layout._device_actions(SimpleNamespace(address="11:22", audio=False, connected=True))
  pushed[0].callback()
  assert calls == ["11:22"]
