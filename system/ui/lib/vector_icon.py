"""Crisp procedural icons.

Icons are authored in canvas units (commonly a 60x60 canvas) with a Pen whose
primitives are clean at any scale: circular arcs are single rings, polylines
get round caps and joins, and fills are wound so raylib never culls them.

draw_vector_icon() rasterises an icon once into a cached texture at
ICON_SUPERSAMPLE x resolution, box-filters it down, and composites it on whole
pixels, so the result is anti-aliased whatever the target framebuffer is.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import pyray as rl

from openpilot.system.ui.lib.application import gui_app

ICON_SUPERSAMPLE = 4

Point = tuple[float, float]


class Pen:
  """Draws in canvas units: canvas point (px, py) lands at (x + px*s, y + py*s)."""

  def __init__(self, x: float, y: float, s: float, color: rl.Color):
    self.x = x
    self.y = y
    self.s = s
    self.color = color

  def v(self, px: float, py: float) -> rl.Vector2:
    return rl.Vector2(self.x + px * self.s, self.y + py * self.s)

  def dot(self, px: float, py: float, r: float, col: rl.Color | None = None):
    rl.draw_circle_v(self.v(px, py), r * self.s, col or self.color)

  def stroke(self, points: list[Point], thick: float, closed: bool = False, col: rl.Color | None = None):
    """Polyline with round caps and joins."""
    col = col or self.color
    pts = points + [points[0]] if closed else points
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
      rl.draw_line_ex(self.v(x0, y0), self.v(x1, y1), thick * self.s, col)
    for px, py in points:
      self.dot(px, py, thick / 2.0, col)

  def arc(self, cx: float, cy: float, r: float, start: float, end: float, thick: float, caps: bool = True,
          col: rl.Color | None = None):
    """Circular arc; angles in degrees, clockwise from +x (screen space)."""
    col = col or self.color
    segments = max(24, int(abs(end - start) / 3))
    rl.draw_ring(self.v(cx, cy), (r - thick / 2.0) * self.s, (r + thick / 2.0) * self.s, start, end, segments, col)
    if caps:
      for a in (start, end):
        self.dot(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)), thick / 2.0, col)

  def circle(self, cx: float, cy: float, r: float, thick: float, col: rl.Color | None = None):
    self.arc(cx, cy, r, 0.0, 360.0, thick, caps=False, col=col)

  def fill(self, points: list[Point], col: rl.Color | None = None):
    """Convex polygon fill. Raylib culls clockwise triangles, so fix winding."""
    col = col or self.color
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True))
    pts = points if area < 0 else points[::-1]
    for i in range(1, len(pts) - 1):
      rl.draw_triangle(self.v(*pts[0]), self.v(*pts[i]), self.v(*pts[i + 1]), col)

  def round_rect(self, rx: float, ry: float, rw: float, rh: float, r: float, col: rl.Color | None = None):
    s = self.s
    rl.draw_rectangle_rounded(rl.Rectangle(self.x + rx * s, self.y + ry * s, rw * s, rh * s),
                              min(1.0, 2.0 * r / min(rw, rh)), 16, col or self.color)

  def round_rect_outline(self, rx: float, ry: float, rw: float, rh: float, r: float, thick: float,
                         col: rl.Color | None = None):
    """Stroke centred on the rectangle edge, built from non-overlapping pieces."""
    col = col or self.color
    h = thick / 2.0
    s = self.s
    for cx, cy, a in ((rx + r, ry + r, 180), (rx + rw - r, ry + r, 270), (rx + rw - r, ry + rh - r, 0), (rx + r, ry + rh - r, 90)):
      self.arc(cx, cy, r, a, a + 90, thick, caps=False, col=col)
    for sx, sy, sw, sh in ((rx + r, ry - h, rw - 2 * r, thick), (rx + r, ry + rh - h, rw - 2 * r, thick),
                           (rx - h, ry + r, thick, rh - 2 * r), (rx + rw - h, ry + r, thick, rh - 2 * r)):
      rl.draw_rectangle_rec(rl.Rectangle(self.x + sx * s, self.y + sy * s, sw * s, sh * s), col)

  @staticmethod
  def ellipse(cx: float, cy: float, a: float, b: float, start: float, end: float, n: int = 96) -> list[Point]:
    return [(cx + a * math.cos(math.radians(start + (end - start) * i / n)),
             cy + b * math.sin(math.radians(start + (end - start) * i / n))) for i in range(n + 1)]

  @staticmethod
  def quad(p0: Point, p1: Point, p2: Point, n: int = 32) -> list[Point]:
    out = []
    for i in range(n + 1):
      t = i / n
      out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
                  (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]))
    return out

  @staticmethod
  def cubic(p0: Point, p1: Point, p2: Point, p3: Point, t0: float = 0.0, t1: float = 1.0, n: int = 48) -> list[Point]:
    out = []
    for i in range(n + 1):
      t = t0 + (t1 - t0) * i / n
      a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
      out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def _rgba(color) -> tuple[int, int, int, int]:
  if hasattr(color, "r"):
    return color.r, color.g, color.b, color.a
  components = tuple(color)
  return components[0], components[1], components[2], components[3] if len(components) > 3 else 255


def draw_vector_icon(name: str, x: float, y: float, s: float, color: rl.Color,
                     render: Callable[[float, float, float, rl.Color], None], canvas: float = 60.0,
                     padding: int | None = None):
  """Draw icon `name` with its canvas x canvas area at (x, y), scaled by s.

  render(x, y, s, color) draws the icon geometry. Overlapping parts must share
  one colour: the cache renders the icon opaque and applies the alpha of
  `color` once when compositing, so overlaps never show darker seams.
  """
  cache = getattr(gui_app, "cached_render_texture", None)
  if cache is None:
    render(x, y, s, color)
    return

  r, g, b, a = _rgba(color)
  # A few strokes extend beyond the authored canvas. Padding prevents those
  # edges from being clipped by the render texture.
  if padding is None:
    padding = max(2, int(math.ceil(canvas / 10.0 * s)))
  size = max(1, int(round(canvas * s))) + 2 * padding
  opaque = rl.Color(r, g, b, 255)
  cache_key = f"vector-icon:{name}:{round(s, 4)}:{size}:{(r, g, b)}"
  texture = cache(cache_key, size, size, lambda: render(padding, padding, s, opaque), supersample=ICON_SUPERSAMPLE)
  if texture is None:
    render(x, y, s, color)
    return

  # Render targets contain premultiplied alpha after drawing onto transparent
  # black. Use the matching blend mode (and a premultiplied tint). Snapping to
  # whole pixels keeps the texture 1:1 with the screen so edges stay sharp.
  rl.begin_blend_mode(rl.BlendMode.BLEND_ALPHA_PREMULTIPLY)
  try:
    rl.draw_texture_pro(
      texture,
      rl.Rectangle(0, 0, size, -size),
      rl.Rectangle(round(x) - padding, round(y) - padding, size, size),
      rl.Vector2(0, 0),
      0.0,
      rl.Color(a, a, a, a),
    )
  finally:
    rl.end_blend_mode()


def draw_strokes(strokes: list[tuple[list[Point], float]], color: rl.Color, name: str = "strokes"):
  """Draw screen-space polylines (points, thickness) with round caps and joins.

  The geometry is cached relative to its whole-pixel origin, so any sub-pixel
  offset is preserved inside the cached texture.
  """
  xs = [px for points, _ in strokes for px, _ in points]
  ys = [py for points, _ in strokes for _, py in points]
  x0, y0 = math.floor(min(xs)), math.floor(min(ys))
  rel = [([(round(px - x0, 2), round(py - y0, 2)) for px, py in points], round(thick, 2)) for points, thick in strokes]
  span = max(max(xs) - x0, max(ys) - y0, 1.0)
  pad = int(math.ceil(max(thick for _, thick in rel) / 2.0)) + 2

  def render(x: float, y: float, s: float, col: rl.Color):
    pen = Pen(x, y, s, col)
    for points, thick in rel:
      pen.stroke(points, thick)

  draw_vector_icon(f"{name}:{rel}", x0, y0, 1.0, color, render, canvas=span, padding=pad)
