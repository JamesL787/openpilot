"""Jetlink settings: the large driving model on an attached Jetson or Mac, over USB.

A short tile panel: the on/off setting (parked only, never beside a Chestnut) and read-only status of the link, the model it
runs and what is driving right now. The words come from starpilot.jetlink_adapter.summary so they are testable without a
UI. iOS is not offered here: that transport is not validated on this fork."""
from __future__ import annotations

from openpilot.common.params import Params
from openpilot.selfdrive.ui.layouts.settings.starpilot.panel import StarPilotPanel, create_tile_panel
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot import jetlink_adapter
from openpilot.starpilot.jetlink_adapter import summary
from openpilot.system.ui.lib.multilang import tr

LINK_KEY = jetlink_adapter.KEYS.link
USB = jetlink_adapter.MODES.index('usb')
OFF = jetlink_adapter.MODES.index('off')


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


def _get_enabled() -> bool:
  return jetlink_adapter.stored_mode() == 'usb'


def _set_enabled(state: bool) -> None:
  if ui_state.started:
    return
  Params().put_int(LINK_KEY, USB if state else OFF)


def build_jetlink_panel() -> StarPilotPanel:
  categories = [
    {
      "type": "toggle",
      "title": "Jetlink (USB)",
      "desc": ("Run the large driving model on a Jetson or Mac connected by USB-C. The local model keeps driving until the host is " +
               "ready and switches back by itself if the link fails. Changes only while parked."),
      "get_state": _get_enabled,
      "set_state": _set_enabled,
      "is_enabled": _toggle_enabled,
      "disabled_label": tr("Parked only"),
    },
    {"type": "value", "title": "Status", "get_value": _status_line, "on_click": lambda: None,
     "desc": "What the link is doing right now."},
    {"type": "value", "title": "Large Model", "get_value": _model_line, "on_click": lambda: None,
     "desc": "The external model Jetlink runs. This build runs one validated model."},
  ]
  return create_tile_panel(categories)
