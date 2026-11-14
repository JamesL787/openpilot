"""Radar points on the road view: one dot per point in radarTracks.

Off by default. The choice is the optional `radarPoints` boolean in the onroad layout document, set from
"Radar Point Display" in the appearance settings. Display only: this never touches radar or control code.
"""

import numpy as np

SERVICE = "radarTracks"
DOCUMENT_KEY = "radarPoints"
FILL_COLOR = (255, 40, 40, 230)
OUTLINE_COLOR = (0, 0, 0, 170)
NO_POINTS = np.empty((0, 2), dtype=np.float64)


def radar_points_enabled(document) -> bool:
  return type(document) is dict and document.get(DOCUMENT_KEY) is True


def project_radar_points(
  d_rel: np.ndarray,
  in_y: np.ndarray,
  path_x: np.ndarray,
  path_z: np.ndarray,
  transform: np.ndarray,
  path_offset_z: float,
  clip_bounds: tuple[float, float, float, float],
  rect_bounds: tuple[float, float, float, float],
) -> np.ndarray:
  """Project radar points into screen space, preserving source order.

  Each point sits on the model path's height at its distance. Points that land outside clip_bounds are dropped;
  the rest are clamped into rect_bounds.
  """
  if d_rel.size == 0 or path_x.size == 0:
    return NO_POINTS

  finite = np.isfinite(d_rel) & np.isfinite(in_y)
  if not np.any(finite):
    return NO_POINTS

  d_rel = d_rel[finite]
  in_y = in_y[finite]

  path_indices = np.searchsorted(path_x, d_rel, side="right") - 1
  path_indices = np.maximum(path_indices, 0)

  line_z = np.zeros(d_rel.shape, dtype=np.float64)
  valid_z = path_indices < path_z.size
  if np.any(valid_z):
    line_z[valid_z] = path_z[path_indices[valid_z]]

  in_z = line_z + float(path_offset_z)

  t = transform.astype(np.float64, copy=False)
  point_w = t[2, 0] * d_rel + t[2, 1] * in_y + t[2, 2] * in_z
  valid_w = np.abs(point_w) >= 1e-6

  x = np.zeros_like(d_rel)
  y = np.zeros_like(d_rel)
  x_num = t[0, 0] * d_rel + t[0, 1] * in_y + t[0, 2] * in_z
  y_num = t[1, 0] * d_rel + t[1, 1] * in_y + t[1, 2] * in_z
  np.divide(x_num, point_w, out=x, where=valid_w)
  np.divide(y_num, point_w, out=y, where=valid_w)

  clip_x, clip_y, clip_xmax, clip_ymax = clip_bounds
  visible = (
    valid_w
    & (x >= clip_x) & (x <= clip_xmax)
    & (y >= clip_y) & (y <= clip_ymax)
  )
  if not np.any(visible):
    return NO_POINTS

  rect_x, rect_y, rect_xmax, rect_ymax = rect_bounds
  return np.column_stack((
    np.clip(x[visible], rect_x, rect_xmax),
    np.clip(y[visible], rect_y, rect_ymax),
  ))


class RadarPointsRenderer:
  """Draws the dots for one model renderer. `enabled` is set by the road view before each frame.

  rect_relative: the renderer's transform gives coordinates relative to its rect (compact UI) rather than the screen.
  clip_margin: how far outside the view a point may land and still be drawn, pinned to the view's edge. With 0,
  points off the view are dropped.
  """

  def __init__(self, radius: float, outline_radius: float, *, rect_relative: bool = False, clip_margin: float = 0.0):
    self.enabled = False
    self._radius = radius
    self._outline_radius = outline_radius
    self._rect_relative = rect_relative
    self._clip_margin = clip_margin
    self._key = None
    self._points = NO_POINTS

  def screen_points(self, sm, renderer, rect) -> np.ndarray:
    """Absolute screen positions of the current radar points; empty when off, stale or invalid."""
    if not self.enabled or not (sm.seen[SERVICE] and sm.alive[SERVICE] and sm.valid[SERVICE]):
      self._key = None
      return NO_POINTS
    path = renderer._path.raw_points
    if path.size == 0:
      self._key = None
      return NO_POINTS

    transform = renderer._car_space_transform
    key = (sm.recv_frame[SERVICE], sm.recv_frame["modelV2"], transform.tobytes(), float(renderer._path_offset_z),
           float(rect.x), float(rect.y), float(rect.width), float(rect.height))
    if key == self._key:
      return self._points

    points = sm[SERVICE].points
    count = len(points)
    origin_x, origin_y = (0.0, 0.0) if self._rect_relative else (float(rect.x), float(rect.y))
    view = (origin_x, origin_y, origin_x + float(rect.width), origin_y + float(rect.height))
    margin = self._clip_margin
    clip = (view[0] - margin, view[1] - margin, view[2] + margin, view[3] + margin)
    screen = project_radar_points(
      np.fromiter((float(point.dRel) for point in points), dtype=np.float64, count=count),
      np.fromiter((float(-point.yRel) for point in points), dtype=np.float64, count=count),
      path[:, 0], path[:, 2], transform, float(renderer._path_offset_z), clip, view,
    )
    if self._rect_relative and screen.size:
      screen = screen + (float(rect.x), float(rect.y))
    self._key, self._points = key, screen
    return screen

  def draw(self, sm, renderer, rect) -> None:
    if not self.enabled:
      return
    from openpilot.starpilot.ui.raylib import rl
    fill, outline = rl.Color(*FILL_COLOR), rl.Color(*OUTLINE_COLOR)
    for x, y in self.screen_points(sm, renderer, rect):
      center = rl.Vector2(float(x), float(y))
      rl.draw_circle_v(center, self._outline_radius, outline)
      rl.draw_circle_v(center, self._radius, fill)
