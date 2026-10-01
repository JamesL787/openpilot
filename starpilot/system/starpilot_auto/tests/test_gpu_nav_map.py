"""Starpilot Auto route trimming must preserve the rendered route, including its end caps."""

import time

import numpy as np
import pytest

from openpilot.starpilot.system.starpilot_auto.ui import nav_map
from openpilot.starpilot.system.starpilot_auto.tests.test_gpu_nv12 import gpu as gpu, read_frame


@pytest.mark.parametrize("bearing", [0, 37, 90, 245])
@pytest.mark.parametrize("progress", [0, 4990, 5000, 5010, 9999])
@pytest.mark.parametrize("position", [0, 5000, 9999])
def test_trimmed_route_matches_full_route(gpu, monkeypatch, bearing, progress, position):  # noqa: F811
  rl = gpu
  monkeypatch.setattr(nav_map.gui_app, "font", lambda _: None)
  monkeypatch.setattr(nav_map, "Params", lambda **kwargs: None)
  view = nav_map.NavMapView()
  camera, anchor = nav_map.Camera(110., 98., 14.8, bearing), (180, 120)
  x = np.linspace(-100000, 100000, 10000)
  view._route_world = np.column_stack((110 + x / 2**15, 98 + 100 * np.sin(x / 200) / 2**15))
  camera.x, camera.y = view._route_world[position]
  view._route_received = time.monotonic()
  view._route_progress = progress
  target = rl.load_render_texture(360, 240)
  rl.set_shapes_texture(rl.Texture(rl.rl_get_texture_id_default(), 1, 1, 1, 7), rl.Rectangle(0, 0, 1, 1))
  try:
    frames = []
    for enabled in (False, True):
      monkeypatch.setattr(nav_map.ui_state, "starpilot_auto_car_view", enabled)
      rl.begin_texture_mode(target)
      rl.clear_background(rl.BLACK)
      view._draw_routes(rl.Rectangle(0, 0, 360, 240), camera, anchor, 1.5)
      rl.end_texture_mode()
      frames.append(read_frame(360 * 240 * 4, [(target.id, 360, 240, 0)]))
    assert len(set(frames[0])) > 2, "the reference must actually draw a route"
    assert frames[0] == frames[1]
    assert view._route_bounds is not None
  finally:
    rl.unload_render_texture(target)
