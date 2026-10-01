from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.selfdrive.ui.onroad.model_renderer import ModelRenderer


@pytest.fixture
def renderer():
  result = object.__new__(ModelRenderer)
  result._car_space_transform = np.eye(3, dtype=np.float32)
  result._transform_dirty = False
  result._radar_transform_generation = 7
  result._clip_region = SimpleNamespace(x=-500, y=-500, width=2000, height=2000)
  return result


def test_transform_invalidates_only_when_float32_projection_changes(renderer):
  original = renderer._car_space_transform
  renderer.set_transform(original.astype(np.float64))
  assert renderer._car_space_transform is original
  assert not renderer._transform_dirty and renderer._radar_transform_generation == 7
  changed = original.copy()
  changed[0, 0] = 2
  renderer.set_transform(changed)
  assert renderer._transform_dirty and renderer._radar_transform_generation == 8
  renderer.set_transform(changed)
  assert renderer._transform_dirty and renderer._radar_transform_generation == 8
  changed[0, 0] = 3
  assert renderer._car_space_transform[0, 0] == 2


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("endpoints", [(10, 20), (10, 10), (20, 10)])
@pytest.mark.parametrize("distance", [5, 10, 15, 20, 25])
def test_scalar_endpoint_interpolation_matches_numpy(renderer, dtype, endpoints, distance):
  line = np.array([[0, 0, 2], [endpoints[0], 2, 3], [endpoints[1], 6, 5], [30, 8, 7]], dtype=dtype)
  endpoint = [distance, np.interp(distance, line[1:3, 0], line[1:3, 1]), np.interp(distance, line[1:3, 0], line[1:3, 2])]
  expanded = np.concatenate((line[:2], np.array([endpoint], dtype=dtype)))
  expected = renderer._map_line_to_polygon(expanded, 0.9, 1.2, 2, distance)
  actual = renderer._map_line_to_polygon(line, 0.9, 1.2, 1, distance)
  np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-6)


class _FakeSM:
  def __init__(self, **messages):
    self.messages = messages
    self.valid = dict.fromkeys(messages, True)

  def __getitem__(self, name):
    return self.messages[name]


def _lead(d_rel, y_rel=0.0, status=True):
  return SimpleNamespace(status=status, dRel=d_rel, yRel=y_rel)


def test_clip_by_lead_stops_at_the_first_lead_entry(renderer, monkeypatch):
  from openpilot.selfdrive.ui.onroad import model_renderer
  radar = SimpleNamespace(leadOne=_lead(20.0), leadTwo=_lead(12.0, status=False))
  # Adjacent leads only clip within 1.8 m laterally, so this one beside the path is ignored.
  starpilot_radar = SimpleNamespace(leadLeft=_lead(8.0, y_rel=3.0), leadRight=_lead(0.0, status=False))
  monkeypatch.setattr(model_renderer.ui_state, "sm", _FakeSM(radarState=radar, starpilotRadarState=starpilot_radar), raising=False)
  line = np.array([[x, 0.0, 0.0] for x in range(0, 45, 5)], dtype=np.float32)

  clipped = renderer._map_line_to_polygon(line, 1.0, 1.0, len(line) - 1, 40.0, clip_by_lead=True)
  left = clipped[:len(clipped) // 2]
  np.testing.assert_allclose(left[:, 0], [0, 5, 10, 15, 18.5])  # identity transform, z = 1: screen x = car x

  unclipped = renderer._map_line_to_polygon(line, 1.0, 1.0, len(line) - 1, 40.0)
  assert len(unclipped) == 2 * len(line)


def test_lead_at_the_first_point_hides_the_line(renderer, monkeypatch):
  from openpilot.selfdrive.ui.onroad import model_renderer
  radar = SimpleNamespace(leadOne=_lead(1.0), leadTwo=_lead(0.0, status=False))
  monkeypatch.setattr(model_renderer.ui_state, "sm", _FakeSM(radarState=radar), raising=False)
  line = np.array([[x, 0.0, 0.0] for x in range(0, 45, 5)], dtype=np.float32)
  assert renderer._map_line_to_polygon(line, 1.0, 1.0, len(line) - 1, 40.0, clip_by_lead=True).shape == (0, 2)
