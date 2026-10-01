"""Stable settings routes shared by the native and projected main layouts."""

from dataclasses import dataclass
from enum import IntEnum
import pyray as rl
from openpilot.system.ui.widgets import Widget


class PanelType(IntEnum):
  STARPILOT = 0
  NRDR = 1
  DEVICE = 2
  NETWORK = 3
  BLUETOOTH = 4
  TOGGLES = 5
  SOFTWARE = 6
  DEVELOPER = 7


@dataclass
class PanelInfo:
  name: str
  instance: Widget
  button_rect: rl.Rectangle = rl.Rectangle(0, 0, 0, 0)


