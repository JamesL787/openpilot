"""Save an offline map area on the car, as in The Galaxy: drop a pin, size the circle, pick the detail.

The map frames the circle north-up and a tap moves the pin. Radius steps and the
detail level feed the same OfflineMaps.add_area() The Galaxy uses.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import pyray as rl

from openpilot.starpilot.navigation.map_tiles import TILE_SIZE, meters_per_world_unit, world_xy
from openpilot.starpilot.system.starpilot_auto.ui import settings_style as style
from openpilot.starpilot.system.starpilot_auto.ui.nav_map import BADGE_WARN, Camera, NavMapView
from openpilot.system.ui.lib.application import MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget

MILE_KM = 1.609344
RADII_KM = (1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0)
RADII_MI = (1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0)
DEFAULT_RADIUS = {True: 10.0, False: 5.0}  # in the display unit: 10 km, or 5 mi
LEVELS = ((None, "Auto"), (14, "Road"), (15, "City"), (16, "Street"))
DETAIL = {16: "Street detail", 15: "City detail", 14: "Road detail", 13: "Regional"}
CIRCLE_FILL = rl.Color(250, 204, 21, 40)
CIRCLE_EDGE = rl.Color(250, 204, 21, 230)


def radius_steps(metric: bool) -> tuple[float, ...]:
  """Radius choices in km, stepping through round numbers in the display unit."""
  return RADII_KM if metric else tuple(round(mi * MILE_KM, 3) for mi in RADII_MI)


def radius_label(radius_km: float, metric: bool) -> str:
  return f"{radius_km:g} km" if metric else f"{radius_km / MILE_KM:.0f} mi"


def lat_lon(x: float, y: float) -> tuple[float, float]:
  """Inverse of world_xy: zoom-0 Web Mercator pixels to (latitude, longitude)."""
  longitude = x / TILE_SIZE * 360.0 - 180.0
  latitude = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / TILE_SIZE))))
  return latitude, (longitude + 180.0) % 360.0 - 180.0


class AreaMapView(NavMapView):
  """North-up map framing the area's circle. A tap reports the (latitude, longitude) under it."""

  def __init__(self, on_pick: Callable[[float, float], None]):
    super().__init__(show_guidance=False, clip=True, heading_up=False)
    self._on_pick = on_pick
    self._anchor = (0.0, 0.0)
    self.radius_km = 10.0

  def set_area(self, latitude: float, longitude: float, radius_km: float) -> None:
    # The preview destination is drawn as the pin; preview mode keeps guidance off.
    self._preview_routes = []
    self._preview_destination = (latitude, longitude)
    self._preview_active = True
    self.radius_km = radius_km
    self._dirty = True

  def _world_radius(self) -> float:
    latitude = self._preview_destination[0] if self._preview_destination else 0.0
    return self.radius_km * 1000.0 / meters_per_world_unit(latitude)

  def _target_camera(self, rect: rl.Rectangle, now: float) -> tuple[Camera, tuple[float, float], bool]:
    center = (rect.x + rect.width / 2.0, rect.y + rect.height / 2.0)
    if self._preview_destination is None:
      return super()._target_camera(rect, now)
    x, y = world_xy(*self._preview_destination)
    fit = min(rect.width, rect.height) / (2.4 * self._world_radius() * self._tile_scale())
    return Camera(x, y, max(3.0, min(17.0, math.log2(max(fit, 1e-9)))), 0.0), center, False

  def _advance_camera(self, rect: rl.Rectangle, now: float):
    self._anchor = super()._advance_camera(rect, now)
    return self._anchor

  def _draw_world(self, rect, camera, anchor, tile_scale, now: float | None = None):
    super()._draw_world(rect, camera, anchor, tile_scale, now)
    if self._preview_destination is None:
      return
    x, y = camera.to_screen(*world_xy(*self._preview_destination), anchor, tile_scale)
    radius = self._world_radius() * camera.scale(tile_scale)
    rl.draw_circle_v(rl.Vector2(x, y), radius, CIRCLE_FILL)
    rl.draw_ring(rl.Vector2(x, y), max(0.0, radius - 3.0), radius, 0.0, 360.0, 96, CIRCLE_EDGE)
    self._draw_destination(camera, anchor, tile_scale)  # keep the pin above the circle

  def _draw_status(self, rect: rl.Rectangle) -> None:
    """Keep notices inside this small map: centered, and wrapped to its width."""
    if self._tiles is None:
      return
    if not self._tiles.has_token:
      # Without a key there are no tiles to see, so the notice takes the middle of the box.
      self._notice(rect, "Add a Mapbox key in The Galaxy", middle=True)
    elif self._tiles.service.offline:
      self._notice(rect, "Offline - cached map", middle=False)

  def _notice(self, rect: rl.Rectangle, label: str, middle: bool) -> None:
    size, line_h, pad = 24, 32.0, 20.0
    lines = style.lines(label, max(1.0, rect.width - 4 * pad), size)
    width = min(rect.width - 2 * pad, max(style.text_width(line, size) for line in lines) + 2 * pad)
    height = len(lines) * line_h + pad
    y = rect.y + (rect.height - height) / 2 if middle else rect.y + pad
    card = rl.Rectangle(rect.x + (rect.width - width) / 2, y, width, height)
    self._card(card)
    for index, line in enumerate(lines):
      style.text(rl.Rectangle(card.x, card.y + pad / 2 + index * line_h, card.width, line_h), line, size, BADGE_WARN, align='center')

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    if self._preview_destination is None:
      return
    world = self._camera.to_world(mouse_pos.x, mouse_pos.y, self._anchor, self._tile_scale())
    self._on_pick(*lat_lon(*world))


class AreaEditor(Widget):
  """The map with its pin and circle, and a column of radius, detail, estimate and Save."""

  def __init__(self, controller):
    super().__init__()
    self._controller = controller
    self.map = self._child(AreaMapView(controller.move_pin))
    self._targets: dict[str, rl.Rectangle] = {}
    self._pressed: str | None = None

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(touch_callback)
    self.map.set_touch_valid_callback(touch_callback)

  def _target(self, pos) -> str | None:
    return next((key for key, rect in self._targets.items() if rl.check_collision_point_rec(pos, rect)), None)

  def _handle_mouse_press(self, mouse_pos: MousePos) -> None:
    self._pressed = self._target(mouse_pos)

  def _handle_mouse_cancel(self) -> None:
    self._pressed = None

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    target, pressed, self._pressed = self._target(mouse_pos), self._pressed, None
    if target is not None and target == pressed:
      self._controller.activate(target)

  def _button(self, key: str, rect: rl.Rectangle, label: str, selected: bool = False, enabled: bool = True, size: int = 26) -> None:
    style.button(rect, label, selected or self._pressed == key, size, enabled=enabled)
    if enabled:
      self._targets[key] = rect

  def _render(self, rect: rl.Rectangle) -> None:
    chooser = self._controller.chooser
    if chooser is None:
      return
    self._targets.clear()
    pad, gap = 18.0, 12.0
    wide = rect.width >= 640
    map_rect = rl.Rectangle(rect.x + pad, rect.y + 4, rect.width * .52 - pad, rect.height - 8) if wide else \
      rl.Rectangle(rect.x + pad, rect.y + 4, rect.width - 2 * pad, rect.height * .42)
    self.map.set_area(chooser["latitude"], chooser["longitude"], chooser["radius_km"])
    self.map.render(map_rect)
    rl.draw_rectangle_rounded_lines_ex(map_rect, 0.04, 12, style.hairline(), style.BORDER)

    x = map_rect.x + map_rect.width + 2 * gap if wide else rect.x + pad
    y = rect.y + 4 if wide else map_rect.y + map_rect.height + gap
    w = rect.x + rect.width - pad - x
    bottom = rect.y + rect.height - 4
    style.text(rl.Rectangle(x, y, w, 38), chooser["name"], 30, bold=True)
    style.text(rl.Rectangle(x, y + 36, w, 28), tr("Tap the map to move the pin"), 22, style.MUTED)
    y += 72

    # Radius: - value +
    step, row_h = 84.0, 52.0
    self._button("area_radius:-1", rl.Rectangle(x, y, step, row_h), "-", size=32)
    self._button("area_radius:1", rl.Rectangle(x + w - step, y, step, row_h), "+", size=32)
    label = tr("{} radius").format(radius_label(chooser["radius_km"], self._controller.metric))
    style.text(rl.Rectangle(x + step, y, w - 2 * step, row_h), label, 26, bold=True, align='center')
    y += row_h + gap

    # Detail: four choices, in one row when they fit
    columns = 4 if w >= 520 else 2
    chip_w, chip_h = (w - gap * (columns - 1)) / columns, 46.0
    for index, (zoom, name) in enumerate(LEVELS):
      chip = rl.Rectangle(x + (index % columns) * (chip_w + gap), y + (index // columns) * (chip_h + gap), chip_w, chip_h)
      self._button(f"area_level:{zoom or 'auto'}", chip, tr(name), chooser["zoom"] == zoom, size=22)

    # The estimate sits right above Cancel and Save, which stay at the bottom.
    button_h, line_h = 52.0, 26.0
    buttons_y = bottom - button_h
    estimate, fits = self._controller.estimate_text()
    lines = style.lines(estimate, w, 20)[:2]
    for index, line in enumerate(lines):
      style.text(rl.Rectangle(x, buttons_y - gap - (len(lines) - index) * line_h, w, line_h), line, 20, style.TEXT if fits else style.MUTED)
    half = (w - gap) / 2
    self._button("add:cancel", rl.Rectangle(x, buttons_y, half, button_h), tr("Cancel"))
    self._button("area_save", rl.Rectangle(x + half + gap, buttons_y, half, button_h), tr("Save"), selected=fits, enabled=fits)
