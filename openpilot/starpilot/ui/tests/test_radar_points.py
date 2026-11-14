"""Radar Point Display: projection, the per-renderer dots, the saved choice and its settings row."""

import json
import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from openpilot.starpilot.ui.appearance_owner import AppearanceOwner
from openpilot.starpilot.ui.feature_settings_state import row_change
from openpilot.starpilot.ui.onroad_customization import PARAM_KEY, decode_document, default_document, validate_document
from openpilot.starpilot.ui.presentation import Profile
from openpilot.starpilot.ui.radar_points import SERVICE, RadarPointsRenderer, project_radar_points, radar_points_enabled


def _scalar_reference(d_rel, in_y, path_x, path_z, transform, path_offset_z, clip_bounds, rect_bounds):
  clip_x, clip_y, clip_xmax, clip_ymax = clip_bounds
  rect_x, rect_y, rect_xmax, rect_ymax = rect_bounds
  result = []
  for d, y in zip(d_rel, in_y, strict=True):
    d, y = float(d), float(y)
    if not math.isfinite(d) or not math.isfinite(y):
      continue
    idx = max(int(np.searchsorted(path_x, d, side="right") - 1), 0)
    in_z = (float(path_z[idx]) if idx < len(path_z) else 0.0) + float(path_offset_z)
    row = [float(transform[i, 0]) * d + float(transform[i, 1]) * y + float(transform[i, 2]) * in_z for i in range(3)]
    if abs(row[2]) < 1e-6:
      continue
    x, screen_y = row[0] / row[2], row[1] / row[2]
    if not (clip_x <= x <= clip_xmax and clip_y <= screen_y <= clip_ymax):
      continue
    result.append((max(rect_x, min(x, rect_xmax)), max(rect_y, min(screen_y, rect_ymax))))
  return np.asarray(result, dtype=np.float64).reshape(-1, 2)


def _inputs(count=65):
  d_rel = np.asarray([4.0 + i * 2.4 for i in range(count)], dtype=np.float64)
  in_y = np.asarray([((i % 9) - 4) * 0.45 for i in range(count)], dtype=np.float64)
  path_x = np.linspace(0.0, 192.0, 33, dtype=np.float32)
  path_z = (0.15 * np.sin(path_x / 30.0)).astype(np.float32)
  transform = np.asarray([[18.0, 0.25, 960.0], [0.1, -16.0, 820.0], [0.045, 0.001, 1.0]], dtype=np.float32)
  return d_rel, in_y, path_x, path_z, transform, (-500.0, -500.0, 2420.0, 1580.0), (0.0, 0.0, 1920.0, 1080.0)


@pytest.mark.parametrize("count", [0, 1, 10, 20, 65])
def test_projection_matches_scalar_reference(count):
  d_rel, in_y, path_x, path_z, transform, clip, rect = _inputs(count)
  expected = _scalar_reference(d_rel, in_y, path_x, path_z, transform, 1.22, clip, rect)
  actual = project_radar_points(d_rel, in_y, path_x, path_z, transform, 1.22, clip, rect)
  assert actual.shape == expected.shape
  np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-10)


def test_projection_keeps_order_and_drops_non_finite_points():
  _, _, path_x, path_z, transform, clip, rect = _inputs(0)
  d_rel = np.asarray([20.0, np.nan, 8.0, 20.0, np.inf, 12.0], dtype=np.float64)
  in_y = np.asarray([1.0, 2.0, -1.0, 1.0, 3.0, -2.0], dtype=np.float64)
  expected = _scalar_reference(d_rel, in_y, path_x, path_z, transform, 1.22, clip, rect)
  actual = project_radar_points(d_rel, in_y, path_x, path_z, transform, 1.22, clip, rect)
  np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-10)
  assert actual.shape[0] == 4
  np.testing.assert_allclose(actual[0], actual[2], rtol=0.0, atol=1e-10)


def test_projection_drops_outside_clip_and_clamps_into_rect():
  d_rel, in_y, path_x, path_z, transform, _, _ = _inputs(30)
  clip, rect = (0.0, 0.0, 560.0, 1000.0), (100.0, 200.0, 540.0, 800.0)
  expected = _scalar_reference(d_rel, in_y, path_x, path_z, transform, 1.22, clip, rect)
  actual = project_radar_points(d_rel, in_y, path_x, path_z, transform, 1.22, clip, rect)
  np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-10)
  assert 0 < actual.shape[0] < 30
  assert np.all((actual[:, 0] >= 100.0) & (actual[:, 0] <= 540.0) & (actual[:, 1] >= 200.0) & (actual[:, 1] <= 800.0))


def test_projection_handles_path_edges_and_the_focal_plane():
  path_x, transform = np.asarray([0.0, 10.0], dtype=np.float32), np.eye(3, dtype=np.float32)
  bounds = (-100.0, -100.0, 100.0, 100.0)
  d_rel, in_y = np.asarray([-5.0, 0.0, 5.0, 25.0]), np.zeros(4)
  path_z = np.asarray([1.0, 2.0], dtype=np.float32)
  np.testing.assert_allclose(project_radar_points(d_rel, in_y, path_x, path_z, transform, 1.0, bounds, bounds),
                             _scalar_reference(d_rel, in_y, path_x, path_z, transform, 1.0, bounds, bounds), atol=1e-10)
  # w == 0: nothing to divide by, so nothing is drawn
  assert project_radar_points(np.asarray([1.0, 2.0]), np.zeros(2), path_x, np.zeros(2, dtype=np.float32), transform, 0.0,
                              bounds, bounds).shape == (0, 2)


class FakeSm(dict):
  def __init__(self, points):
    super().__init__({SERVICE: NS(points=points)})
    self.seen, self.alive, self.valid = {SERVICE: True}, {SERVICE: True}, {SERVICE: True}
    self.recv_frame = {SERVICE: 1, "modelV2": 1}
    self.reads = 0

  def __getitem__(self, key):
    self.reads += 1
    return super().__getitem__(key)


def _renderer_inputs():
  # identity-like transform: x = dRel / z, y = -yRel / z with z = path height + offset = 1
  path = np.asarray([[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]], dtype=np.float32)
  view = NS(_path=NS(raw_points=path), _car_space_transform=np.eye(3, dtype=np.float32), _path_offset_z=1.0)
  points = [NS(dRel=10.0, yRel=-20.0), NS(dRel=30.0, yRel=-40.0), NS(dRel=500.0, yRel=-40.0)]
  return view, FakeSm(points), NS(x=5.0, y=7.0, width=100.0, height=100.0)


def test_renderer_is_off_by_default_and_never_reads_messages_while_off():
  view, sm, rect = _renderer_inputs()
  dots = RadarPointsRenderer(7.0, 9.0)
  assert not dots.enabled
  assert dots.screen_points(sm, view, rect).shape == (0, 2)
  dots.draw(sm, view, rect)
  assert sm.reads == 0


def test_renderer_positions_cache_and_staleness():
  view, sm, rect = _renderer_inputs()
  dots = RadarPointsRenderer(7.0, 9.0)
  dots.enabled = True
  # screen coordinates: the third point is off the view and, with no margin, dropped
  np.testing.assert_allclose(dots.screen_points(sm, view, rect), [[10.0, 20.0], [30.0, 40.0]])
  dots.screen_points(sm, view, rect)
  assert sm.reads == 1  # same radar and model frame: reuse the projection
  sm.recv_frame[SERVICE] = 2
  sm[SERVICE].points.pop(0)
  reads = sm.reads
  np.testing.assert_allclose(dots.screen_points(sm, view, rect), [[30.0, 40.0]])
  assert sm.reads == reads + 1
  for flags in (sm.seen, sm.alive, sm.valid):
    flags[SERVICE] = False
    assert dots.screen_points(sm, view, rect).shape == (0, 2)
    flags[SERVICE] = True
  assert dots.screen_points(sm, view, rect).shape == (1, 2)
  view._path.raw_points = np.empty((0, 3), dtype=np.float32)
  assert dots.screen_points(sm, view, rect).shape == (0, 2)


def test_renderer_margin_pins_to_the_edge_and_compact_view_adds_the_rect_origin():
  view, sm, rect = _renderer_inputs()
  pinned = RadarPointsRenderer(7.0, 9.0, clip_margin=500.0)
  pinned.enabled = True
  np.testing.assert_allclose(pinned.screen_points(sm, view, rect), [[10.0, 20.0], [30.0, 40.0], [105.0, 40.0]])
  compact = RadarPointsRenderer(4.0, 5.5, rect_relative=True)
  compact.enabled = True
  np.testing.assert_allclose(compact.screen_points(sm, view, rect), [[15.0, 27.0], [35.0, 47.0]])


def test_saved_choice_is_an_optional_boolean_in_the_layout_document():
  document = default_document()
  assert "radarPoints" not in document and not radar_points_enabled(document)
  assert "radarPoints" not in validate_document(document)
  for value in (True, False):
    assert validate_document({**document, "radarPoints": value})["radarPoints"] is value
    assert radar_points_enabled({**document, "radarPoints": value}) is value
  for value in (1, "true", None):
    with pytest.raises(ValueError):
      validate_document({**document, "radarPoints": value})
    assert not radar_points_enabled({**document, "radarPoints": value})
  assert not radar_points_enabled(None)


@pytest.mark.parametrize("profile", list(Profile))
def test_settings_row_saves_only_while_parked_and_keeps_the_layout(tmp_path, profile):
  class Params:
    def get_param_path(self, key):
      return str(tmp_path / key)
  document = default_document()
  document["layouts"]["large"]["clock"].update(x=700, y=700, enabled=True)
  path = tmp_path / PARAM_KEY
  path.write_text(json.dumps(document))
  parked = True
  owner = AppearanceOwner(Params(), lambda: parked)

  def row():
    return next(row for row in owner.snapshot(profile).rows if row.key == "RadarPoints")

  assert (row().label, row().value, row().default_value, row().available) == ("Radar Point Display", "Off", "Off", True)
  request = row_change(row(), 1)
  assert request is not None and owner.apply(request)
  saved = decode_document(path.read_bytes())
  assert saved["radarPoints"] is True and saved["layouts"] == document["layouts"] and saved["reduceMotion"] is False
  assert row().value == "On"
  assert not owner.apply(request)  # the source it was made from is gone
  request = row_change(row(), -1)
  assert request is not None
  parked = False
  assert not owner.apply(request) and not row().available
  parked = True
  assert owner.apply(request) and decode_document(path.read_bytes())["radarPoints"] is False
  path.write_bytes(b"corrupt layout")
  assert not owner.apply(request) and path.read_bytes() == b"corrupt layout"
  assert (row().value, row().available) == ("Unavailable", False)
