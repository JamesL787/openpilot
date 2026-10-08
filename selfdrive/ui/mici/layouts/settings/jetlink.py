"""Jetlink on the comma four's settings list: one toggle whose second line says what the link is doing.

USB only (iOS is not validated on this fork), parked only, and not beside a Chestnut, which owns the accelerator slot.
The words come from starpilot.jetlink_adapter.summary."""
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigToggle
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot import jetlink_adapter
from openpilot.starpilot.jetlink_adapter import summary

USB = jetlink_adapter.MODES.index('usb')
OFF = jetlink_adapter.MODES.index('off')


def available() -> bool:
  """Is Jetlink part of this build? Without the vendored package there is nothing to toggle."""
  return jetlink_adapter.VENDOR_DIR.is_dir()


class JetlinkBigToggle(BigToggle):
  def __init__(self):
    super().__init__("jetlink (usb)", "", initial_state=jetlink_adapter.stored_mode() == 'usb',
                     toggle_callback=self._on_toggle)
    self.set_enabled(lambda: not ui_state.started and not ui_state.usbgpu)
    self.set_value(self._line())

  @staticmethod
  def _on_toggle(checked: bool) -> None:
    if ui_state.started:
      return
    Params().put_int(jetlink_adapter.KEYS.link, USB if checked else OFF)

  @staticmethod
  def _line() -> str:
    sm = ui_state.sm
    live = None
    if ui_state.started and sm.seen['starpilotModelV2'] and sm.alive['starpilotModelV2']:
      m = sm['starpilotModelV2']
      live = {'backend': str(m.backend), 'accelerator': str(m.accelerator), 'held_frames': int(m.heldFrames),
              'remote_model': str(m.remoteModel), 'reason': str(m.reason)}
    return summary.describe(jetlink_adapter.status_cached(), live)

  def _update_state(self):
    super()._update_state()
    self.set_value(self._line())

  def refresh(self) -> None:
    self.set_checked(jetlink_adapter.stored_mode() == 'usb')
