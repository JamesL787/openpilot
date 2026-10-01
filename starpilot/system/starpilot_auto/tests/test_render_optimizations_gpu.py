"""Compare real GPU pixels with and without gradient uniform caching."""
import numpy as np

from openpilot.starpilot.system.starpilot_auto.tests.test_gpu_nv12 import gpu as gpu, read_frame


def test_cached_gradient_uniforms_match_forced_uploads(request, monkeypatch):
  from openpilot.system.ui.lib import shader_polygon
  rl = request.getfixturevalue("gpu")
  monkeypatch.setattr(shader_polygon.ShaderState, "_instance", None)
  state = shader_polygon.ShaderState.get_instance()
  target = rl.load_render_texture(64, 64)
  points = np.array([[6, 56], [4, 4], [60, 4], [56, 56]], dtype=np.float32)
  gradient = shader_polygon.Gradient((0, 0), (1, 1), [rl.Color(255, 20, 80, 100), rl.Color(20, 255, 80, 200)], [0, 1])
  rect = rl.Rectangle(0, 0, 64, 64)

  def render(force):
    rl.begin_texture_mode(target)
    rl.clear_background(rl.Color(20, 30, 40, 255))
    for alpha, stop, offset in ((100, 1, 0), (100, 1, 0), (140, 0.7, 8), (140, 0.7, 8), (100, 1, 0)):
      if force:
        state.uniform_values.clear()
      gradient.colors[0].a = alpha
      gradient.stops[1] = stop
      rect.x = offset
      shader_polygon.draw_polygon(rect, points, gradient=gradient)
    rl.end_texture_mode()
    return read_frame(64 * 64 * 4, [(target.id, 64, 64, 0)])

  try:
    expected = render(True)
    assert len(set(expected)) > 4  # ensure the shader actually drew a gradient
    assert render(False) == expected
    assert render(False) == expected  # cache persists into the next frame
  finally:
    state.cleanup()
    rl.unload_render_texture(target)
