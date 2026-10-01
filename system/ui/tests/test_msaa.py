from openpilot.system.ui.lib import msaa


def _outline(width, height, radius, segments):
  points, count = msaa._rounded_outline(width, height, radius, segments)
  return [(points[i].x, points[i].y) for i in range(count)]


def test_rounded_outline_is_closed_fan_inside_bounds():
  pts = _outline(110.0, 56.0, 28.0, 24)

  assert pts[0] == (55.0, 28.0)  # fan centre
  assert pts[1] == pts[-1]  # outline closes on its first vertex
  for x, y in pts:
    assert -1e-3 <= x <= 110.0 + 1e-3
    assert -1e-3 <= y <= 56.0 + 1e-3


def test_rounded_outline_winds_counter_clockwise_on_screen():
  outline = _outline(200.0, 80.0, 12.0, 8)[1:-1]
  area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(outline, outline[1:] + outline[:1], strict=True))
  # Negative shoelace area in y-down coordinates is counter-clockwise on
  # screen, which raylib needs to avoid back-face culling the fan.
  assert area < 0


def test_msaa_can_be_disabled(monkeypatch):
  monkeypatch.setattr(msaa, "UI_MSAA_SAMPLES", 1)
  assert msaa.MsaaTarget.create(100, 100) is None
