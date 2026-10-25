from dataclasses import replace
from unittest.mock import Mock, patch

import pyray as rl
import pytest

from openpilot.starpilot.ui.large_speed_geometry import LARGE_SIGN_SCALE
from openpilot.starpilot.ui.onroad_state import speed_limit_bounds, slc_controls, compact_sign_obscured_by_actions, SpeedLimitObservation, ObservationKind
from openpilot.starpilot.ui.presentation import Profile
from openpilot.starpilot.ui.speed_limit_widget import SpeedLimitWidget
from openpilot.starpilot.ui.tests.test_unified_speed_native import fonts, state
from openpilot.starpilot.ui.unified_speed_presentation import resolve_unified_speed


@pytest.fixture(autouse=True)
def historical_outline():
  with patch.object(rl, 'draw_rectangle_rounded_lines_ex') as outline:
    yield outline


@pytest.mark.parametrize('profile', list(Profile))
@pytest.mark.parametrize('offset', [False, True])
@pytest.mark.parametrize('vienna', [False, True])
def test_only_small_rectangular_sign_extends_for_visible_offset(profile, offset, vienna, historical_outline):
  current = state(show_slc_offset=offset)
  current = replace(current, appearance=replace(current.appearance, use_vienna_sign=vienna))
  widget = SpeedLimitWidget(fonts(profile), profile)
  widget.shapes = Mock()
  with patch('openpilot.starpilot.ui.speed_limit_widget.rl.draw_rectangle_rounded') as fill:
    widget.render(current)
  fill.assert_not_called()
  scale = LARGE_SIGN_SCALE if profile == Profile.LARGE else 1
  bounds = speed_limit_bounds(profile, current)
  tall = speed_limit_bounds(profile, replace(current, show_slc_offset=True))
  assert bounds is not None and tall is not None
  extended = profile == Profile.COMPACT and not vienna
  assert bounds[:3] == tall[:3]
  assert bounds[3] == tall[3] - (44 if extended and not offset else 0)
  if vienna:
    widget.shapes.outline.assert_not_called()
    widget.shapes.circle.assert_called_once()
    historical_outline.assert_not_called()
  elif profile == Profile.COMPACT:
    widget.shapes.outline.assert_not_called()
    rect, rounding, segments, stroke, _ = historical_outline.call_args.args
    assert (rect.x, rect.y, rect.width, rect.height) == (bounds[0]+22, bounds[1]+20, 100, 116+(44 if offset else 0))
    assert (rounding, segments, stroke) == (.14, 16, 2)
  else:
    historical_outline.assert_not_called()
    widget.shapes.outline.assert_called_once()
    assert widget.shapes.outline.call_args.args[:2] == (bounds[0]+12+59*scale, bounds[1]+12+66*scale)
    assert widget.shapes.outline.call_args.kwargs == {}
  assert ('+5' in [call.args[0] for call in widget.fonts.draw.call_args_list]) == offset


@pytest.mark.parametrize('value', (65, 120))
@pytest.mark.parametrize('metric', (False, True))
@pytest.mark.parametrize('show', (False, True))
@pytest.mark.parametrize('offset', (None, 0., .01, -.01, 5., -10.))
def test_small_sign_has_space_only_for_a_visible_offset(value, metric, show, offset, historical_outline):
  factor = 3.6 if metric else 2.2369362921
  current = state(metric=metric, show_slc_offset=show)
  current = replace(current, appearance=replace(current.appearance, show_speed_limit_sign=True, use_vienna_sign=False),
    speed_limit=SpeedLimitObservation(ObservationKind.VALID, 'vision', value / factor,
    offset_mps=None if offset is None else offset / factor, action_enabled=False))
  shown = resolve_unified_speed(current)
  widget = SpeedLimitWidget(fonts(Profile.COMPACT), Profile.COMPACT)
  widget.shapes = Mock()
  widget.render(current)
  bounds = speed_limit_bounds(Profile.COMPACT, current)
  assert bounds is not None
  extended = bool(shown.offset_text)
  widget.shapes.outline.assert_not_called()
  rect = historical_outline.call_args.args[0]
  assert (rect.width, rect.height) == (100, 160 if extended else 116)
  assert bounds[3] - bounds[1] == (196 if extended else 152)
  number = next(call.args for call in widget.fonts.draw.call_args_list if call.args[0] == str(value))
  assert number[4] == bounds[1] + 12 + 66
  assert number[2] == (50 if value < 100 else 42)


def test_small_offset_layout_transitions_reuse_the_same_widget(historical_outline):
  widget = SpeedLimitWidget(fonts(Profile.COMPACT), Profile.COMPACT)
  widget.shapes = Mock()
  for enabled in (False, True, False):
    current = state(show_slc_offset=enabled)
    widget.render(current)
    assert historical_outline.call_args.args[0].height == (160 if enabled else 116)


@pytest.mark.parametrize('y', [20, 50, 108])
def test_compact_confirmation_overlap_remains_conservative(y):
  current = state(slc_prompt_open=True)
  current.customization['layouts']['compact']['speed_limit']['y'] = y
  obscured = compact_sign_obscured_by_actions(current)
  assert obscured is (y == 108)
  assert (speed_limit_bounds(Profile.COMPACT, current) is None) is obscured
  assert slc_controls(Profile.COMPACT, current)


def test_small_rectangular_no_offset_regression(historical_outline):
  current = state(show_slc_offset=False)
  widget = SpeedLimitWidget(fonts(Profile.COMPACT), Profile.COMPACT)
  widget.shapes = Mock()
  widget.render(current)
  bounds = speed_limit_bounds(Profile.COMPACT, current)
  assert bounds is not None and bounds[3] - bounds[1] == 152
  rect = historical_outline.call_args.args[0]
  assert (rect.width, rect.height) == (100, 116)
