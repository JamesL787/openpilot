"""Jetlink settings: the large driving model on an attached Jetson, Linux PC or Mac (USB) or iPhone or iPad (iOS), over
USB-C.

A short tile panel: the link setting, Off / USB / iOS as Zoompilot offers it (parked only, never beside a Chestnut), and
read-only status of the link, the USB-C port, the model it runs and what is driving right now. The words come from
starpilot.jetlink_adapter.summary so they are testable without a UI."""
from __future__ import annotations

from openpilot.common.params import Params
from openpilot.selfdrive.ui.layouts.settings.starpilot.panel import StarPilotPanel, create_tile_panel
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot import jetlink_adapter
from openpilot.starpilot.jetlink_adapter import summary
from openpilot.system.ui.lib.multilang import tr

LINK_KEY = jetlink_adapter.KEYS.link
MODE_TITLES = {'off': "Off", 'usb': "USB", 'ios': "iOS"}


def _live() -> dict | None:
  """modeld's own report of what is driving, while it publishes one."""
  sm = ui_state.sm
  if not ui_state.started or not (sm.seen['starpilotModelV2'] and sm.alive['starpilotModelV2']):
    return None
  m = sm['starpilotModelV2']
  return {'backend': str(m.backend), 'accelerator': str(m.accelerator), 'held_frames': int(m.heldFrames),
          'remote_model': str(m.remoteModel), 'reason': str(m.reason)}


def _status_line() -> str:
  return summary.describe(jetlink_adapter.status_cached(), _live())


def _model_line() -> str:
  status = jetlink_adapter.status_cached()
  if status is None:
    return "—"
  live = _live()
  if live and live['remote_model']:
    return live['remote_model']
  return status.active_model or status.default_model or "—"


def _toggle_enabled() -> bool:
  # parked only: the link's gadget, warp and model swap are all set up around ignition, not while driving. Where there is
  # no Jetlink, or a Chestnut owns the accelerator slot, the setting would do nothing
  return (not ui_state.started) and jetlink_adapter.status_cached() is not None and not ui_state.usbgpu


def _mode_line() -> str:
  return tr(MODE_TITLES.get(jetlink_adapter.stored_mode(), "Off"))


def _next_mode() -> None:
  """Off -> USB -> iOS -> Off. Parked only."""
  if ui_state.started:
    return
  modes = jetlink_adapter.MODES
  current = jetlink_adapter.stored_mode()
  index = modes.index(current) if current in modes else 0
  Params().put_int(LINK_KEY, (index + 1) % len(modes))


def _port_line() -> str:
  return summary.port_line(jetlink_adapter.status_cached()) or "—"


def build_jetlink_panel() -> StarPilotPanel:
  categories = [
    {
      "type": "value",
      "title": "Jetlink",
      "desc": ("Run the large driving model on a host connected by USB-C: USB for a Jetson, Linux PC or Mac, iOS for an " +
               "iPhone or iPad with the Jetlink app open. Tap to switch Off, USB, iOS. Turns off ADB. Changes only while parked."),
      "get_value": _mode_line,
      "on_click": _next_mode,
      "is_enabled": _toggle_enabled,
    },
    {"type": "value", "title": "Status", "get_value": _status_line, "on_click": lambda: None,
     "desc": "What the link is doing right now."},
    {"type": "value", "title": "USB-C Port", "get_value": _port_line, "on_click": lambda: None,
     "desc": "What is on the comma's USB-C port."},
    {"type": "value", "title": "Large Model", "get_value": _model_line, "on_click": lambda: None,
     "desc": "The external model Jetlink runs. This build runs one validated model."},
  ]
  return create_tile_panel(categories)
