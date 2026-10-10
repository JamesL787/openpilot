"""Jetlink on the comma four's settings list: one button cycling off, usb, ios (Zoompilot's AcceleratorLinkToggle), a
pill each, whose second line names the mode and says what the link is doing.

usb is a Jetson, Linux PC or Mac; ios an iPhone or iPad with the Jetlink app open. Parked only, and not beside a
Chestnut, which owns the accelerator slot. The words come from starpilot.jetlink_adapter.summary."""
from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiToggle
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot import jetlink_adapter
from openpilot.starpilot.jetlink_adapter import summary

MODES = jetlink_adapter.MODES
MODE_LABELS = {'off': "off", 'usb': "usb", 'ios': "iOS"}


def available() -> bool:
  """Is Jetlink part of this build? Without the vendored package there is nothing to toggle."""
  return jetlink_adapter.VENDOR_DIR.is_dir()


def next_mode(mode: str) -> str:
  return MODES[(MODES.index(mode) + 1) % len(MODES)] if mode in MODES else MODES[0]


class JetlinkBigToggle(BigMultiToggle):
  """The pills follow the param, not a tap: a tap writes the next mode and the pills show what is stored."""

  def __init__(self):
    super().__init__("jetlink", [MODE_LABELS[m] for m in MODES])
    self._mode = jetlink_adapter.stored_mode()
    self.set_enabled(lambda: not ui_state.started and not ui_state.usbgpu)
    self._show()

  def _handle_mouse_release(self, mouse_pos) -> None:
    BigButton._handle_mouse_release(self, mouse_pos)
    if self.enabled and not ui_state.started:
      self._mode = next_mode(self._mode)
      Params().put_int(jetlink_adapter.KEYS.link, MODES.index(self._mode))
    self._show()

  def _draw_content(self, btn_y: float) -> None:
    BigButton._draw_content(self, btn_y)
    x = self._rect.x + self._rect.width - self._txt_enabled_toggle.width
    for i, mode in enumerate(MODES):
      self._draw_pill(x, btn_y + 35 * i, mode == self._mode)

  def _show(self) -> None:
    line = MODE_LABELS.get(self._mode, "off")
    if self._mode != 'off':
      line += f" · {self._line()}"
    if line != self.value:
      self.set_value(line)

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
    self._show()

  def refresh(self) -> None:
    self._mode = jetlink_adapter.stored_mode()
    self._show()
