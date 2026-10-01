"""GPU checks for the Starpilot Auto map's inexpensive intermediate frames."""

from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.starpilot.system.starpilot_auto.ui import nav_map
from openpilot.starpilot.system.starpilot_auto.car_ui import MAP_BORDER, MapPane
from openpilot.starpilot.system.starpilot_auto.tests.test_gpu_nv12 import gpu as gpu, read_frame


@pytest.fixture
def scene(gpu, monkeypatch):  # noqa: F811
  rl = gpu
  monkeypatch.setattr(nav_map.gui_app, "font", lambda _: None)
  monkeypatch.setattr(nav_map, "Params", lambda **kwargs: None)
  view = nav_map.NavMapView(clip=False)
  view._camera = nav_map.Camera(zoom=0)
  view._animating = True
  monkeypatch.setattr(view, "update", lambda: None)
  monkeypatch.setattr(view, "_advance_camera", lambda rect, now: (160, 120))
  monkeypatch.setattr(view, "_tile_scale", lambda: 1.0)
  monkeypatch.setattr(view, "_draw_cached_car", lambda *args: None)
  draws = []

  def world(rect, camera, anchor, scale, now=None):
    for x in range(-1000, 1000, 40):
      # Draw in world coordinates, including heading and zoom.
      corners = [rl.Vector2(*camera.to_screen(wx, wy, anchor, scale)) for wx, wy in
                 ((x, -1000), (x + 8, -1000), (x + 8, 1000), (x, 1000))]
      nav_map._triangle(*corners[:3], rl.WHITE)
      nav_map._triangle(corners[0], corners[2], corners[3], rl.WHITE)

  def overlays(rect, now):
    draws.append(now)
    rl.draw_rectangle(10, 10, 100, 30, rl.Color(30, 180, 90, 160))

  monkeypatch.setattr(view, "_draw_world", world)
  monkeypatch.setattr(view, "_draw_overlays", overlays)
  pane = MapPane()
  pane._map = view
  target = rl.load_render_texture(320, 240)
  rect = rl.Rectangle(0, 0, 320, 240)
  scale = [1.0, 1.0]
  scissor = rl.begin_scissor_mode
  monkeypatch.setattr(rl, "begin_scissor_mode", lambda x, y, w, h: scissor(int(x * scale[0]), int(y * scale[1]),
                                                                         int(w * scale[0]), int(h * scale[1])))
  rl.set_shapes_texture(rl.Texture(rl.rl_get_texture_id_default(), 1, 1, 1, 7), rl.Rectangle(0, 0, 1, 1))

  def frame(now):
    pane.prepare(rect, *scale, now)
    rl.begin_texture_mode(target)
    rl.clear_background(rl.MAGENTA)
    rl.rl_push_matrix()
    rl.rl_scalef(*scale, 1)
    pane.draw(rect)
    rl.rl_pop_matrix()
    rl.end_texture_mode()
    return np.frombuffer(read_frame(320 * 240 * 4, [(target.id, 320, 240, 0)]), np.uint8).reshape(240, 320, 4)[::-1].copy()

  yield SimpleNamespace(rl=rl, view=view, pane=pane, rect=rect, frame=frame, overlays=draws, scale=scale)
  pane.close()
  assert pane._texture is pane._overlay is pane._msaa is None
  rl.unload_render_texture(target)


@pytest.mark.parametrize("fps", [15, 20, 30, 60])
def test_motion_on_every_car_frame_without_more_world_redraws(scene, fps):
  reference = scene.frame(100.0)
  for frame in range(1, fps * 2):
    scene.view._camera.x = frame * 3
    pixels = scene.frame(100.0 + frame / fps)
    # Moving pixels advance on intermediate frames, not just every second frame.
    expected = np.roll(reference[100], -3 * frame, axis=0)
    assert np.array_equal(pixels[100, 40:280], expected[40:280])
    assert not np.any(np.all(pixels[:, :, :3] == (255, 0, 255), axis=2))
  # At 60 FPS the existing jitter allowance can bring the boundary redraw
  # forward by one car frame; it does not change the average 15 Hz schedule.
  assert 30 <= scene.pane.redraws <= 31
  assert len(scene.overlays) == 1, "the overlay redraws when its content changes, not on a clock tick"


def test_stationary_map_remains_idle(scene):
  scene.view._animating = False
  before = scene.frame(100.0)
  for frame in range(1, 60):
    assert np.array_equal(scene.frame(100.0 + frame / 30), before)
  assert scene.pane.redraws == 2


@pytest.mark.parametrize("bearing,zoom", [(1.5, 0), (-1.5, 0), (0, .02), (1.5, .02)])
def test_rotation_zoom_and_fixed_overlay(scene, bearing, zoom):
  scene.frame(100.0)
  scene.view._camera.bearing, scene.view._camera.zoom = bearing, zoom
  interpolated = scene.frame(100.0 + 1 / 30)
  assert scene.pane.redraws == 1
  direct = scene.frame(100.0 + 2 / 30)
  # Resampling a cached image may change edge pixels, but not orientation or HUD placement.
  assert np.abs(interpolated.astype(float) - direct).mean() < 3
  assert np.all(interpolated[:, :, 3] == 255)
  assert not np.any(np.all(interpolated[:, :, :3] == (255, 0, 255), axis=2))


def test_jump_holds_cache_until_scheduled_redraw(scene):
  before = scene.frame(100.0)
  scene.view._camera.x = 10000
  assert np.array_equal(scene.frame(100.0 + 1 / 30), before)
  assert scene.pane.redraws == 1
  scene.frame(100.0 + 2 / 30)
  assert scene.pane.redraws == 2
  assert scene.pane._cached_camera.x == 10000


def test_resize_and_overlay_state_invalidate_cache(scene):
  scene.frame(100.0)
  scene.view._overlay_state = ("new instructions",)
  scene.frame(100.01)
  assert len(scene.overlays) == 2
  assert scene.pane.redraws == 1
  scene.pane.prepare(scene.rl.Rectangle(0, 0, 400, 200), 1, 1, 100.02)
  assert scene.pane._texture.texture.width == 400 + 2 * MAP_BORDER
  assert scene.pane._texture.texture.height == 200 + 2 * MAP_BORDER
  assert scene.pane.redraws == 2
  # Logical geometry can also change without reallocating physical textures.
  scene.pane.prepare(scene.rl.Rectangle(0, 0, 800, 400), .5, .5, 100.03)
  assert scene.pane.redraws == 3


def test_scaled_split_map_does_not_bleed_into_driving_view(scene):
  scene.scale[:] = [.5, .5]
  scene.rect.x, scene.rect.width, scene.rect.height = 64, 576, 480
  scene.frame(100.0)
  scene.view._camera.x = 3
  pixels = scene.frame(100.0 + 1 / 30)
  assert np.all(pixels[:, :32, :3] == (255, 0, 255))
  assert not np.any(np.all(pixels[:, 32:, :3] == (255, 0, 255), axis=2))


def test_translucent_route_does_not_make_world_cache_transparent(scene, monkeypatch):
  monkeypatch.setattr(scene.view, "_draw_world", lambda *args: scene.rl.draw_rectangle(-1000, -1000, 2000, 2000,
                                                                                     nav_map.ROUTE_ALTERNATE))
  pixels = scene.frame(100.0)
  assert np.all(pixels[:, :, 3] == 255)
  alpha = nav_map.ROUTE_ALTERNATE.a / 255
  expected = [round(alpha * getattr(nav_map.ROUTE_ALTERNATE, c) + (1 - alpha) * getattr(nav_map.MAP_BACKGROUND, c)) for c in "rgb"]
  assert np.max(np.abs(pixels[100, 160, :3].astype(float) - expected)) <= 1


@pytest.mark.parametrize("fresh", [False, True])
@pytest.mark.parametrize("heading", [0, 37, 90, 245])
def test_cached_marker_stays_anchored_and_preserves_shape(scene, monkeypatch, fresh, heading):
  view, app, rl = scene.view, nav_map.gui_app, scene.rl
  monkeypatch.setattr(app, "_cached_render_textures", {})
  monkeypatch.setattr(app, "_pending_render_textures", {})
  monkeypatch.setattr(view, "_draw_world", lambda *args: None)
  monkeypatch.setattr(view, "_draw_cached_car", nav_map.NavMapView._draw_cached_car.__get__(view))
  view._gps = nav_map.GpsFix(36.3, -115.3, heading, 20, 100, fresh)
  view._display_bearing = heading
  direct = scene.frame(100.0)
  app._populate_render_texture_cache()
  try:
    scene.view._camera.x = 3
    cached = scene.frame(100.0 + 1 / 30)
    assert len(app._cached_render_textures) == 1
    # Supersampling changes edge coverage, not marker position, orientation or color.
    assert np.abs(direct[84:156, 124:196].astype(float) - cached[84:156, 124:196]).mean() < 4
    assert np.array_equal(direct[120, 160], cached[120, 160])
  finally:
    for texture in app._cached_render_textures.values():
      rl.unload_render_texture(texture)
    app._cached_render_textures.clear()
