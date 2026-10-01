"""The comma four's Starpilot Auto page: one card per setting, reached from the Bluetooth screen.

Each card keeps a short title and value so nothing scrolls sideways. Changing the car, the
connection type, auto-connect or the car display asks for a slide to confirm first; a
tap that is not confirmed snaps back, because every card shows starpilot_autod's status.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.mici.layouts.settings import starpilot_auto_state as state
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiToggle, BigToggle, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog, BigMultiOptionDialog
from openpilot.common.params import Params
from openpilot.starpilot.system.starpilot_auto.sdp import STARPILOT_AUTO_WIRELESS_UUID
from openpilot.starpilot.system.starpilot_auto.connection_help import recovery_hint, setup_instructions
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller

TITLE = "Starpilot Auto"
PENDING_HOLD = 3.0  # s a confirmed change is shown before starpilot_autod's status catches up


class TextPage(NavScroller):
  """Longer text as a row of cards to swipe through, instead of one card that cuts it off."""

  def __init__(self, title: str, text: str, icon: rl.Texture | None = None):
    super().__init__()
    cards = [GreyBigButton(title, "swipe to read", icon)]
    cards += [GreyBigButton("", chunk) for chunk in state.split_text(text)]
    self._scroller.add_widgets(cards)


def _set_value(button: BigButton, value: str) -> None:
  if button.get_value() != value:  # relaying out a label every frame is not free
    button.set_value(value)


def show_text(title: str, text: str, icon: rl.Texture | None = None) -> None:
  """A short message in one card, a longer one as a page of cards."""
  if len(text) <= state.TEXT_CARD_CHARS:
    gui_app.push_widget(BigDialog(title, text))
  else:
    gui_app.push_widget(TextPage(title, text, icon))


class StarpilotAutoLayoutMici(NavScroller):
  def __init__(self, manager: Callable, bluetooth, icon: rl.Texture):
    """``manager`` returns the Bluetooth screen's StarpilotAutoManager, or None once Starpilot Auto or Bluetooth is off."""
    super().__init__()
    self._manager = manager
    self._bluetooth = bluetooth
    self._icon = icon
    self._pending: dict[str, tuple[object, float]] = {}

    self._connect_btn = BigButton("Connect", "starting")
    self._connect_btn.set_click_callback(self._connect_tapped)
    self._car_btn = BigButton("Car", "")
    self._car_btn.set_click_callback(self._choose_car)
    self._auto_toggle = BigToggle("Auto\nConnect", "On", toggle_callback=self._auto_tapped)
    # Short titles: a multi-toggle's title shares its width with the pills.
    self._connection_toggle = BigMultiToggle("Link Type", list(state.CONNECTION_OPTIONS), select_callback=self._connection_tapped)
    self._view_toggle = BigMultiToggle("Display", list(state.VIEW_OPTIONS), select_callback=self._view_tapped)
    self._params = Params()
    self._share_toggle = BigToggle("Help Other\nTesters", "On", toggle_callback=self._share_tapped)
    self._pair_btn = BigButton("Pair New Car", "Pair while parked")
    self._pair_btn.set_click_callback(self._pair)
    self._setup_btn = BigButton("Setup Help", "Tap to read")
    self._setup_btn.set_click_callback(self._show_setup)
    self._error_btn = BigButton("Last Error", "Tap to read")
    self._error_btn.set_click_callback(self._show_error)
    self._scroller.add_widgets([self._connect_btn, self._car_btn, self._auto_toggle, self._connection_toggle,
                                self._view_toggle, self._pair_btn, self._setup_btn, self._error_btn, self._share_toggle])
    self._refresh()

  def show_event(self):
    super().show_event()
    self._pending.clear()
    self._refresh()
    gui_app.add_nav_stack_tick(self._refresh)

  def hide_event(self):
    gui_app.remove_nav_stack_tick(self._refresh)
    super().hide_event()

  # ------------------------------------------------------------------ state

  def _shown(self, key: str, actual):
    """What a card shows: a just-confirmed value until the status agrees or the hold runs out."""
    pending = self._pending.get(key)
    if pending is None:
      return actual
    value, until = pending
    if value == actual or time.monotonic() > until:
      del self._pending[key]
      return actual
    return value

  def _refresh(self) -> None:
    manager = self._manager()
    if manager is None:
      if not self.is_dismissing:
        self.dismiss()  # Bluetooth or Starpilot Auto was switched off underneath
      return
    status = manager.status
    busy = manager.busy
    idle_ok = state.can_change_while(status) and not busy
    if self._connect_btn.get_text() != state.connect_label(status):
      self._connect_btn.set_text(state.connect_label(status))
    _set_value(self._connect_btn, state.connect_status_value(status))
    self._connect_btn.set_enabled(state.can_connect(status) and not busy)
    _set_value(self._car_btn, status.get("receiver_name") or "Choose a Car")
    self._car_btn.set_enabled(idle_ok)
    auto_connect = self._shown("auto", bool(status.get("auto_connect", True)))
    self._auto_toggle.set_checked(auto_connect)
    _set_value(self._auto_toggle, state.auto_connect_value(auto_connect))
    self._auto_toggle.set_enabled(bool(status) and not busy)
    _set_value(self._connection_toggle, self._shown("connection", state.connection_value(status)))
    self._connection_toggle.set_enabled(idle_ok)
    _set_value(self._view_toggle, self._shown("view", state.view_value(status)))
    self._view_toggle.set_enabled(bool(status) and not busy)
    share = self._params.get_bool("StarpilotAutoShareDiagnostics")
    self._share_toggle.set_checked(share)
    _set_value(self._share_toggle, "On" if share else "Off")
    self._pair_btn.set_enabled(not busy)
    items = [self._connect_btn]
    if state.show_car(status):
      items.append(self._car_btn)
    items += [self._auto_toggle, self._connection_toggle, self._view_toggle]
    if state.show_pairing(status, self._bluetooth.status.offroad):
      items.append(self._pair_btn)
    items.append(self._setup_btn)
    if state.show_error(status):
      items.append(self._error_btn)
    items.append(self._share_toggle)  # last, so it is there to find but not in the way
    if self._scroller.items != items:
      self._scroller.items[:] = items

  # ---------------------------------------------------------------- actions

  def _confirm(self, title: str, key: str | None, value, apply: Callable[[], None]) -> None:
    def confirmed():
      if key is not None:
        self._pending[key] = (value, time.monotonic() + PENDING_HOLD)
      apply()
    gui_app.push_widget(BigConfirmationDialog(title, self._icon, confirmed))

  def _connect_tapped(self) -> None:
    manager = self._manager()
    if manager is None:
      return
    if state.running(manager.status):
      manager.stop_projection()
    else:
      manager.start()

  def _auto_tapped(self, enabled: bool) -> None:
    manager = self._manager()
    if manager is not None:
      self._confirm(state.auto_connect_title(enabled), "auto", enabled, lambda: manager.set_auto_connect(enabled))

  def _share_tapped(self, enabled: bool) -> None:
    self._params.put_bool("StarpilotAutoShareDiagnostics", enabled)

  def _connection_tapped(self, connection: str) -> None:
    manager = self._manager()
    if manager is not None:
      self._confirm(state.connection_title(connection), "connection", connection,
                    lambda: manager.set_connection("wired" if connection == state.CONNECTION_OPTIONS[1] else "wireless"))

  def _view_tapped(self, view: str) -> None:
    manager = self._manager()
    if manager is not None:
      self._confirm(state.view_title(view), "view", view, lambda: manager.set_view("mirror" if view == state.VIEW_OPTIONS[1] else "car"))

  def _choose_car(self) -> None:
    cars = [device for device in self._bluetooth.status.devices if device.paired]
    if not cars:
      gui_app.push_widget(BigDialog(TITLE, "Pair your car first with \"pair new car\"."))
      return
    cars.sort(key=lambda device: str(STARPILOT_AUTO_WIRELESS_UUID) not in device.uuids)  # cars offering Starpilot Auto first
    labels: dict[str, object] = {}
    for device in cars:
      label = device.name if device.name not in labels else f"{device.name} {device.address[-5:]}"
      labels[label] = device
    manager = self._manager()
    current = manager.status.get("receiver_address", "") if manager is not None else ""
    dialog_holder = {}

    def apply():
      manager = self._manager()
      device = labels.get(dialog_holder["dialog"].get_selected_option())
      if manager is None or device is None or device.address.upper() == current.upper():
        return

      def select():
        manager.select_receiver(device.address, device.name)
      if current:
        self._confirm("slide to\nchange car", None, None, select)
      else:
        select()  # the first car: nothing to change from

    options = list(labels)
    default = next((label for label, device in labels.items() if device.address.upper() == current.upper()), options[0])
    dialog = BigMultiOptionDialog(options=options, default=default, right_btn_callback=apply)
    dialog_holder["dialog"] = dialog
    gui_app.push_widget(dialog)

  def _pair(self) -> None:
    manager = self._manager()
    if manager is None:
      return
    manager.prepare_pairing()
    self._bluetooth.set_scanning(True)
    # Back to the device list, where the car appears to be tapped.
    self.dismiss(lambda: gui_app.push_widget(BigDialog("pair your car", "Add a new device on the car, then tap it here.")))

  def _show_error(self) -> None:
    manager = self._manager()
    if manager is not None and manager.status.get("error"):
      show_text(TITLE, recovery_hint(manager.status) + " " + str(manager.status["error"]), self._icon)

  def _show_setup(self) -> None:
    manager = self._manager()
    if manager is not None:
      show_text("setup help", setup_instructions(manager.status), self._icon)
