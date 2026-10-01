import pyray as rl
import time
from dataclasses import dataclass
from collections.abc import Callable
from cereal import log
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

SIDEBAR_WIDTH = 300
METRIC_HEIGHT = 126
METRIC_WIDTH = 240
METRIC_MARGIN = 30
FONT_SIZE = 35

SETTINGS_BTN = rl.Rectangle(50, 35, 200, 117)
HOME_BTN = rl.Rectangle(60, 860, 180, 180)

ThermalStatus = log.DeviceState.ThermalStatus
NetworkType = log.DeviceState.NetworkType


# Color scheme - Galaxy palette
class Colors:
  WHITE = rl.Color(240, 240, 248, 255)
  WHITE_DIM = rl.Color(160, 160, 185, 200)
  GRAY = rl.Color(38, 38, 58, 255)

  # Status colors (Galaxy palette)
  GOOD = rl.Color(94, 200, 200, 255)      # Stellar Teal
  WARNING = rl.Color(212, 160, 96, 255)   # Solar Amber
  DANGER = rl.Color(224, 85, 119, 255)    # Nebula Rose

  # UI elements & Galaxy theme
  SIDEBAR_BG = rl.Color(10, 10, 22, 255)        # Deep cosmic void (#0a0a16)
  SIDEBAR_BORDER = rl.Color(30, 30, 62, 255)    # Subtle boundary line (#1e1e3e)
  SIDEBAR_ACCENT = rl.Color(139, 92, 246, 50)   # Cosmic purple accent glow
  CARD_BG = rl.Color(18, 18, 36, 255)           # Galaxy card plate (#121224)
  CARD_BORDER = rl.Color(35, 35, 68, 255)       # Card border (#232344)
  BUTTON_NORMAL = rl.WHITE
  BUTTON_PRESSED = rl.Color(200, 200, 220, 255)
  BUTTON_BG = rl.Color(18, 18, 36, 220)
  BUTTON_BORDER = rl.Color(35, 35, 68, 255)
  BUTTON_ACTIVE_BG = rl.Color(139, 108, 197, 60)
  BUTTON_ACTIVE_BORDER = rl.Color(139, 92, 246, 180)
  TEXT_LABEL = rl.Color(128, 128, 168, 255)     # Muted lavender
  TEXT_VALUE = rl.Color(240, 240, 248, 255)     # Bright cosmic white
  METRIC_BORDER = rl.Color(35, 35, 68, 255)


NETWORK_TYPES = {
  NetworkType.none: tr_noop("--"),
  NetworkType.wifi: tr_noop("Wi-Fi"),
  NetworkType.ethernet: tr_noop("ETH"),
  NetworkType.cell2G: tr_noop("2G"),
  NetworkType.cell3G: tr_noop("3G"),
  NetworkType.cell4G: tr_noop("LTE"),
  NetworkType.cell5G: tr_noop("5G"),
}


@dataclass(slots=True)
class MetricData:
  label: str
  value: str
  color: rl.Color

  def update(self, label: str, value: str, color: rl.Color):
    self.label = label
    self.value = value
    self.color = color


class CarSidebar(Widget):
  def __init__(self):
    super().__init__()
    self._net_type = NETWORK_TYPES.get(NetworkType.none)
    self._net_strength = 0

    self._temp_status = MetricData(tr_noop("TEMP"), "--°C", Colors.GOOD)
    self._panda_status = MetricData(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)
    self._connect_status = MetricData(tr_noop("CONNECT"), tr_noop("OFFLINE"), Colors.WARNING)
    self._recording_audio = False

    self._settings_btn_rect = rl.Rectangle(SETTINGS_BTN.x, SETTINGS_BTN.y, SETTINGS_BTN.width, SETTINGS_BTN.height)
    self._home_btn_rect = rl.Rectangle(HOME_BTN.x, HOME_BTN.y, HOME_BTN.width, HOME_BTN.height)

    self._home_img = gui_app.texture("images/button_home.png", HOME_BTN.width, HOME_BTN.height)
    self._flag_img = gui_app.texture("images/button_flag.png", HOME_BTN.width, HOME_BTN.height)
    self._settings_img = gui_app.texture("images/button_settings.png", SETTINGS_BTN.width, SETTINGS_BTN.height)
    self._mic_img = gui_app.texture("icons/microphone.png", 30, 30)
    self._mic_indicator_rect = rl.Rectangle(0, 0, 0, 0)
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self._font_medium = gui_app.font(FontWeight.MEDIUM)
    self._font_bold = gui_app.font(FontWeight.BOLD)

    # Callbacks
    self._on_settings_click: Callable | None = None
    self._on_flag_click: Callable | None = None
    self._open_settings_callback: Callable | None = None

  def set_callbacks(self, on_settings: Callable | None = None, on_flag: Callable | None = None,
                    open_settings: Callable | None = None):
    self._on_settings_click = on_settings
    self._on_flag_click = on_flag
    self._open_settings_callback = open_settings

  def _render(self, rect: rl.Rectangle):
    # Deep cosmic background
    rl.draw_rectangle_rec(rect, Colors.SIDEBAR_BG)
    # Right border divider with purple accent glow
    rl.draw_line_ex(rl.Vector2(rect.x + rect.width - 1, rect.y),
                    rl.Vector2(rect.x + rect.width - 1, rect.y + rect.height),
                    2.0, Colors.SIDEBAR_BORDER)
    rl.draw_line_ex(rl.Vector2(rect.x + rect.width - 1, rect.y),
                    rl.Vector2(rect.x + rect.width - 1, rect.y + rect.height),
                    1.0, Colors.SIDEBAR_ACCENT)

    self._draw_buttons(rect)
    self._draw_network_indicator(rect)
    self._draw_metrics(rect)

  def _update_state(self):
    sm = ui_state.sm
    if not sm.updated['deviceState']:
      return

    device_state = sm['deviceState']

    self._recording_audio = ui_state.recording_audio
    self._update_network_status(device_state)
    self._update_temperature_status(device_state)
    self._update_connection_status(device_state)
    self._update_panda_status()

  def _update_network_status(self, device_state):
    self._net_type = NETWORK_TYPES.get(device_state.networkType.raw, tr_noop("Unknown"))
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _update_temperature_status(self, device_state):
    thermal_status = device_state.thermalStatus
    temperature = f"{int(device_state.maxTempC)}°C"

    if thermal_status == ThermalStatus.ok:
      self._temp_status.update(tr_noop("TEMP"), temperature, Colors.GOOD)
    elif thermal_status == ThermalStatus.warmDEPRECATED:
      self._temp_status.update(tr_noop("TEMP"), temperature, Colors.WARNING)
    else:
      self._temp_status.update(tr_noop("TEMP"), temperature, Colors.DANGER)

  def _update_connection_status(self, device_state):
    last_ping = device_state.lastAthenaPingTime
    if last_ping == 0:
      self._connect_status.update(tr_noop("CONNECT"), tr_noop("OFFLINE"), Colors.WARNING)
    elif time.monotonic_ns() - last_ping < 80_000_000_000:  # 80 seconds in nanoseconds
      self._connect_status.update(tr_noop("CONNECT"), tr_noop("ONLINE"), Colors.GOOD)
    else:
      self._connect_status.update(tr_noop("CONNECT"), tr_noop("ERROR"), Colors.DANGER)

  def _update_panda_status(self):
    if ui_state.panda_type == log.PandaState.PandaType.unknown:
      self._panda_status.update(tr_noop("NO"), tr_noop("PANDA"), Colors.DANGER)
    else:
      self._panda_status.update(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN):
      if self._on_settings_click:
        self._on_settings_click()
    elif rl.check_collision_point_rec(mouse_pos, HOME_BTN) and ui_state.started:
      if self._on_flag_click:
        self._on_flag_click()
    elif self._recording_audio and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect):
      if self._open_settings_callback:
        self._open_settings_callback()

  def _draw_buttons(self, rect: rl.Rectangle):
    mouse_pos = gui_app.last_mouse_event.pos
    mouse_down = self.is_pressed and gui_app.last_mouse_event.left_down

    # Settings button
    settings_down = mouse_down and rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN)
    tint = Colors.BUTTON_PRESSED if settings_down else Colors.BUTTON_NORMAL
    rl.draw_texture(self._settings_img, int(SETTINGS_BTN.x), int(SETTINGS_BTN.y), tint)

    # Home/Flag button
    flag_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, HOME_BTN)
    button_img = self._flag_img if ui_state.started else self._home_img
    tint = Colors.BUTTON_PRESSED if (ui_state.started and flag_pressed) else Colors.BUTTON_NORMAL
    rl.draw_texture(button_img, int(HOME_BTN.x), int(HOME_BTN.y), tint)

    # Microphone button
    if self._recording_audio:
      self._mic_indicator_rect = rl.Rectangle(rect.x + rect.width - 130, rect.y + 245, 75, 40)

      mic_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect)
      bg_color = rl.Color(Colors.DANGER.r, Colors.DANGER.g, Colors.DANGER.b, int(255 * 0.65)) if mic_pressed else Colors.DANGER

      rl.draw_rectangle_rounded(self._mic_indicator_rect, 1, 10, bg_color)
      rl.draw_texture(self._mic_img, int(self._mic_indicator_rect.x + (self._mic_indicator_rect.width - self._mic_img.width) / 2),
                      int(self._mic_indicator_rect.y + (self._mic_indicator_rect.height - self._mic_img.height) / 2), Colors.WHITE)

  def _draw_network_indicator(self, rect: rl.Rectangle):
    # Signal strength dots
    x_start = rect.x + 58
    y_pos = rect.y + 196
    dot_size = 27
    dot_spacing = 37

    for i in range(5):
      color = Colors.GOOD if i < self._net_strength else Colors.GRAY
      x = int(x_start + i * dot_spacing + dot_size // 2)
      y = int(y_pos + dot_size // 2)
      rl.draw_circle(x, y, dot_size // 2, color)

    # Network type text
    text_y = rect.y + 247
    text_pos = rl.Vector2(rect.x + 58, text_y)
    rl.draw_text_ex(self._font_regular, tr(self._net_type), text_pos, FONT_SIZE, 0, Colors.WHITE)

  def _draw_metrics(self, rect: rl.Rectangle):
    metrics = [(self._temp_status, 338), (self._panda_status, 496), (self._connect_status, 654)]

    for metric, y_offset in metrics:
      self._draw_metric(rect, metric, rect.y + y_offset)

  def _draw_metric(self, rect: rl.Rectangle, metric: MetricData, y: float):
    metric_rect = rl.Rectangle(rect.x + METRIC_MARGIN, y, METRIC_WIDTH, METRIC_HEIGHT)

    # Galaxy card plate
    rl.draw_rectangle_rounded(metric_rect, 0.3, 10, Colors.CARD_BG)

    # Draw colored left edge (clipped rounded rectangle)
    edge_rect = rl.Rectangle(metric_rect.x + 4, metric_rect.y + 4, 100, 118)
    rl.begin_scissor_mode(int(metric_rect.x + 4), int(metric_rect.y), 18, int(metric_rect.height))
    rl.draw_rectangle_rounded(edge_rect, 0.3, 10, metric.color)
    rl.end_scissor_mode()

    # Draw border
    rl.draw_rectangle_rounded_lines_ex(metric_rect, 0.3, 10, 2, Colors.METRIC_BORDER)

    # Draw label and value - large bold high-contrast text
    labels = [tr(metric.label), tr(metric.value)]
    text_y = metric_rect.y + (metric_rect.height / 2 - len(labels) * FONT_SIZE * FONT_SCALE)
    for text in labels:
      text_size = measure_text_cached(self._font_bold, text, FONT_SIZE)
      text_y += text_size.y
      text_pos = rl.Vector2(
        metric_rect.x + 22 + (metric_rect.width - 22 - text_size.x) / 2,
        text_y
      )
      rl.draw_text_ex(self._font_bold, text, text_pos, FONT_SIZE, 0, Colors.WHITE)
