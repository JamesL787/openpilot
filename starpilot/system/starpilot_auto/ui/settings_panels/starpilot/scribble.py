from __future__ import annotations
import math
import pyray as rl
from openpilot.system.ui.lib.vector_icon import Pen, draw_vector_icon


def _draw_custom_icon_geometry(key: str, x: float, y: float, s: float, color: rl.Color):
  """Draw icon `key` with its 60x60 canvas at (x, y), scaled by s."""
  p = Pen(x, y, s, color)

  # One outline family: a single stroke weight, round caps and joins, and each glyph
  # filling roughly the same 44x44 area of the canvas so the tiles read as a set.
  t = 3.8

  if key == "sound":
    # Sounds & Alerts: speaker with two sound waves
    p.stroke([(11.0, 24.0), (19.0, 24.0), (29.0, 14.5), (29.0, 45.5), (19.0, 36.0), (11.0, 36.0)], t, closed=True)
    for r, span in ((9.0, 42.0), (17.0, 46.0)):
      p.arc(31.0, 30.0, r, -span, span, t)

  elif key == "steering":
    # Driving Controls: steering wheel with a hub and three spokes
    p.circle(30.0, 30.0, 19.5, t)
    p.circle(30.0, 30.0, 5.0, t)
    p.stroke([(11.0, 28.0), (25.0, 29.0)], t)
    p.stroke([(35.0, 29.0), (49.0, 28.0)], t)
    p.stroke([(30.0, 35.0), (30.0, 49.0)], t)

  elif key == "navigate":
    # Map Data: location pin over a ground ellipse
    cx, cy, r, tip = 30.0, 22.0, 11.0, 44.0
    swing = math.degrees(math.acos(r / (tip - cy)))
    a0, a1 = 90.0 + swing, 450.0 - swing
    p.arc(cx, cy, r, a0, a1, t, caps=False)
    for a in (a0, a1):
      p.stroke([(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))), (cx, tip)], t)
    p.circle(cx, cy, 3.6, t)

  elif key == "system":
    # System Settings: a gear outline with a centre hole
    teeth, r_base, r_tip, cx, cy = 8, 14.0, 19.5, 30.0, 30.0
    outline = []
    for i in range(teeth):
      a = i * 360.0 / teeth
      for r, da in ((r_base, -13.0), (r_tip, -8.0), (r_tip, 8.0), (r_base, 13.0)):
        outline.append((cx + r * math.cos(math.radians(a + da)), cy + r * math.sin(math.radians(a + da))))
      for k in range(1, 4):  # the valley between this tooth and the next
        v = a + 13.0 + (45.0 - 26.0) * k / 4
        outline.append((cx + r_base * math.cos(math.radians(v)), cy + r_base * math.sin(math.radians(v))))
    p.stroke(outline, t, closed=True)
    p.circle(cx, cy, 5.5, t)

  elif key == "display":
    # Appearance: three tuning sliders with ring knobs
    for row, knob in ((17.0, 21.0), (30.0, 38.0), (43.0, 26.0)):
      p.stroke([(10.0, row), (knob - 6.0, row)], t)
      p.stroke([(knob + 6.0, row), (50.0, row)], t)
      p.circle(knob, row, 4.5, t)

  elif key == "vehicle":
    # Vehicle Settings: car in profile with the wheels cut out of the sill
    w1, w2, wy, tire_r = 17.0, 43.0, 40.0, 5.5
    body = (Pen.quad((8.0, 35.0), (10.0, 29.5), (17.5, 28.5))
            + Pen.quad((17.5, 28.5), (21.5, 18.5), (26.5, 18.0))[1:]
            + [(36.5, 18.0)]
            + Pen.quad((36.5, 18.0), (47.5, 22.0), (52.0, 35.0))[1:])
    p.stroke(body, t)
    p.stroke([(8.0, 35.0), (8.0, wy), (w1 - tire_r - 2.5, wy)], t)
    p.stroke([(w1 + tire_r + 2.5, wy), (w2 - tire_r - 2.5, wy)], t)
    p.stroke([(w2 + tire_r + 2.5, wy), (52.0, wy), (52.0, 35.0)], t)
    for wx in (w1, w2):
      p.circle(wx, wy, tire_r, t)

  elif key == "road":
    # Curvy Road: a road narrowing into the distance with a dashed centre line
    p.stroke([(12.0, 50.0), (25.0, 10.0)], t)
    p.stroke([(48.0, 50.0), (35.0, 10.0)], t)
    for y0, y1 in ((44.0, 38.0), (31.0, 26.5), (20.0, 17.0)):
      p.stroke([(30.0, y0), (30.0, y1)], t)

  elif key == "aicar":
    # Driving Model: front view of a car with forward perception arcs
    for r in (7.0, 14.0):
      p.arc(30.0, 24.0, r, -130.0, -50.0, t)
    p.dot(30.0, 24.0, 2.6)
    p.stroke([(12.0, 49.0), (12.0, 39.0), (18.5, 30.0), (41.5, 30.0), (48.0, 39.0), (48.0, 49.0)], t, closed=True)
    p.stroke([(17.5, 41.0), (22.5, 41.0)], t)
    p.stroke([(37.5, 41.0), (42.5, 41.0)], t)

  elif key == "first_aid":
    # First Aid Kit
    t = 2.6
    p.stroke(Pen.ellipse(30.0, 20.0, 6.0, 4.5, 180.0, 360.0, 32), t)
    p.round_rect_outline(12.0, 20.0, 36.0, 25.0, 3.5, t)
    p.stroke([(30.0, 26.0), (30.0, 39.0)], 3.6)
    p.stroke([(23.5, 32.5), (36.5, 32.5)], 3.6)


def draw_custom_icon(key: str, x: float, y: float, s: float, color: rl.Color):
  """Draw a custom icon, caching its static vector geometry on the GPU."""
  draw_vector_icon(f"aethergrid:{key}", x, y, s, color,
                   lambda ix, iy, i_s, icolor: _draw_custom_icon_geometry(key, ix, iy, i_s, icolor))
