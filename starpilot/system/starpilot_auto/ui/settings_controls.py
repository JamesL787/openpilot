"""Small car controls with bounded, single-line labels."""
import pyray as rl

from openpilot.starpilot.system.starpilot_auto.ui import settings_style as style
from openpilot.system.ui.widgets.button import Button as BaseButton


class Button(BaseButton):
  def __init__(self, *args, text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER, **kwargs):
    super().__init__(*args, text_alignment=text_alignment, **kwargs)
    # Labels are centered unless the caller asked for list-style (left) text, e.g. Wi-Fi names.
    self._align = 'left' if text_alignment == rl.GuiTextAlignment.TEXT_ALIGN_LEFT else 'center'

  def _render(self, rect):
    label = self._label._text
    style.button(rect, label() if callable(label) else label, self.is_pressed, style.px(24), self._align)
