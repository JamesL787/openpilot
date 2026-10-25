"""The atlas has smooth coverage, solid arrow joins, and bounded GPU ownership."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
from PIL import Image
import pytest

from openpilot.starpilot.ui import speed_limit_shapes as shapes
from openpilot.starpilot.ui.assets.generate_speed_limit_shapes import generate


def test_atlas_matches_generated_geometry_and_has_symmetric_antialiased_edges():
  with Image.open(shapes.ATLAS_PATH) as atlas:
    assert atlas.size == shapes.ATLAS_SIZE
    assert atlas.tobytes() == generate().tobytes()
    for name, (x, y, width, height) in shapes.SPRITES.items():
      alpha = np.asarray(atlas.crop((x, y, x+width, y+height)))[..., 3]
      assert np.array_equal(alpha, alpha[:, ::-1])
      assert ((alpha > 0) & (alpha < 255)).sum() > 10
      assert not alpha[0].any() and not alpha[-1].any()
      assert not alpha[:, 0].any() and not alpha[:, -1].any()
      if name.startswith('arrow'):
        for row in alpha:
          ink = np.flatnonzero(row > 40)
          assert not len(ink) or ink[-1] - ink[0] + 1 == len(ink)
        center = alpha[:, width//2]
        painted = np.flatnonzero(center > 40)
        assert painted[-1] - painted[0] + 1 == len(painted)
      if name == 'outline':
        assert not alpha[18:-18, 18:-18].any(), 'the camera must remain visible inside the sign'
        assert np.array_equal(alpha, alpha[::-1]), 'rounded corners must be symmetric'


@pytest.fixture
def gpu(monkeypatch):
  monkeypatch.setattr(shapes.rl, 'is_window_ready', lambda: True)
  calls = {}
  for name, value in (('load_image', NS(data=1, width=shapes.ATLAS_SIZE[0], height=shapes.ATLAS_SIZE[1])),
                      ('load_texture_from_image', NS(id=7)), ('unload_image', None), ('unload_texture', None),
                      ('set_texture_filter', None), ('set_texture_wrap', None), ('draw_texture_pro', None)):
    calls[name] = Mock(return_value=value)
    monkeypatch.setattr(shapes.rl, name, calls[name])
  return calls


def test_shapes_share_one_upload_and_arrow_is_one_draw_in_either_direction(gpu):
  owner = shapes.SpeedLimitShapes()
  owner.circle(389, 87, shapes.rl.RED)
  assert gpu['draw_texture_pro'].call_count == 2
  gpu['draw_texture_pro'].reset_mock()
  owner.outline(59, 66, shapes.rl.WHITE)
  owner.outline(59, 66, shapes.rl.WHITE)
  assert gpu['draw_texture_pro'].call_count == 2
  _, source, destination, _, _, _ = gpu['draw_texture_pro'].call_args.args
  assert (source.width, source.height) == (128, 144)
  assert (destination.x, destination.y) == (59, 66)
  for direction, rotation in ((1, 0), (-1, 180)):
    gpu['draw_texture_pro'].reset_mock()
    owner.arrow('compact', 389, 49, direction, shapes.rl.BLACK)
    gpu['draw_texture_pro'].assert_called_once()
    assert gpu['draw_texture_pro'].call_args.args[-2] == rotation
  gpu['load_image'].assert_called_once()
  gpu['load_texture_from_image'].assert_called_once()
  gpu['unload_image'].assert_called_once()
  owner.close()
  owner.close()
  gpu['unload_texture'].assert_called_once()


def test_bad_atlas_dimensions_release_image_without_uploading(gpu):
  gpu['load_image'].return_value.width = 4096
  with pytest.raises(ValueError, match='Invalid speed-limit'):
    shapes.SpeedLimitShapes().circle(0, 0, shapes.rl.RED)
  gpu['unload_image'].assert_called_once()
  gpu['load_texture_from_image'].assert_not_called()


def test_large_sign_scale_changes_destination_and_rotation_origin_only(gpu):
  owner = shapes.SpeedLimitShapes(1.25)
  owner.arrow('compact', 345.75, 111.25, -1, shapes.rl.BLACK)
  _, source, destination, origin, rotation, _ = gpu['draw_texture_pro'].call_args.args
  assert (source.width, source.height) == (16, 24)
  assert (destination.x, destination.y, destination.width, destination.height) == (345.75, 111.25, 20, 30)
  assert (origin.x, origin.y, rotation) == (10, 15, 180)
  owner.close()


def test_texture_setup_failure_releases_both_resources(gpu):
  gpu['set_texture_filter'].side_effect = RuntimeError('filter unavailable')
  with pytest.raises(RuntimeError, match='filter unavailable'):
    shapes.SpeedLimitShapes().circle(0, 0, shapes.rl.RED)
  gpu['unload_texture'].assert_called_once()
  gpu['unload_image'].assert_called_once()


def test_headless_context_loads_atlas_without_a_window(gpu, monkeypatch):
  monkeypatch.setattr(shapes.rl, 'is_window_ready', lambda: False)
  with pytest.raises(RuntimeError, match='graphics context'):
    shapes.SpeedLimitShapes().circle(0, 0, shapes.rl.RED)
  owner = shapes.SpeedLimitShapes(headless_context=True)
  owner.circle(0, 0, shapes.rl.RED)
  gpu['load_texture_from_image'].assert_called_once()


def test_short_outline_reuses_the_same_atlas_and_preserves_corner_scale(gpu):
  owner = shapes.SpeedLimitShapes()
  owner.outline(59, 58, shapes.rl.WHITE, short=True)
  assert gpu['draw_texture_pro'].call_count == 2
  rows = [call.args for call in gpu['draw_texture_pro'].call_args_list]
  assert [(r[1].x, r[1].y, r[1].width, r[1].height) for r in rows] == [(256, 0, 128, 64), (256, 80, 128, 64)]
  assert [(r[2].x, r[2].y, r[2].width, r[2].height) for r in rows] == [(59, -6, 128, 64), (59, 58, 128, 64)]
  assert all((r[3].x, r[3].y) == (64, 0) for r in rows)
  owner.outline(59, 66, shapes.rl.WHITE)
  owner.outline(59, 58, shapes.rl.WHITE, short=True)
  gpu['load_image'].assert_called_once()
  gpu['load_texture_from_image'].assert_called_once()
  owner.close()
  gpu['unload_texture'].assert_called_once()
