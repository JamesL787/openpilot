from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from openpilot.starpilot.ui.onroad_state import speed_limit_bounds
from openpilot.starpilot.ui.presentation import Profile
from openpilot.starpilot.ui.speed_limit_widget import SpeedLimitWidget
from openpilot.starpilot.ui.tests.test_unified_speed_native import fonts, state


@pytest.mark.parametrize('profile', list(Profile))
@pytest.mark.parametrize('offset', [False, True])
def test_only_compact_rectangle_grows_for_visible_offset(profile, offset):
  current = state(show_slc_offset=offset)
  widget = object.__new__(SpeedLimitWidget)
  widget.fonts = fonts(profile)
  widget.profile = profile
  widget.scale = 1
  widget.text_scale = 1
  widget.pulse = Mock(color=lambda color, now: color)
  bounds = speed_limit_bounds(profile, current)
  assert bounds is not None
  with patch('openpilot.starpilot.ui.speed_limit_widget.rl.draw_rectangle_rounded_lines_ex') as outline, \
       patch('openpilot.starpilot.ui.speed_limit_widget.rl.draw_rectangle_rounded'), \
       patch('openpilot.starpilot.ui.speed_limit_widget.SpeedLimitShapes.arrow'):
    widget.shapes = Mock()
    widget._sign(current, bounds, 10.)
  rectangle = outline.call_args.args[0]
  assert rectangle.height == ((160 if offset else 116) if profile == Profile.COMPACT else 128)
  other = speed_limit_bounds(profile, replace(current, show_slc_offset=not offset))
  assert other is not None
  assert bounds[:3] == other[:3]
  assert abs(bounds[3] - other[3]) == (44 if profile == Profile.COMPACT else 0)
  texts = [call.args[0] for call in widget.fonts.draw.call_args_list]
  assert ('+5' in texts) == offset


@pytest.mark.parametrize('value', ['55', '125'])
@pytest.mark.parametrize('pending_arrow', [False, True])
def test_compact_rectangle_uses_original_geometry_and_measured_typography(value, pending_arrow):
  from openpilot.starpilot.ui.presentation import FontRole
  from openpilot.starpilot.ui.onroad_state import SpeedLimitObservation, ObservationKind
  current = state(show_slc_offset=False)
  current = replace(current, speed_limit=SpeedLimitObservation(ObservationKind.VALID, 'map', int(value) / 3.6,
    pending_speed_limit_mps=int(value) / 3.6 if pending_arrow else None))
  widget = object.__new__(SpeedLimitWidget)
  widget.fonts, widget.profile = fonts(Profile.COMPACT), Profile.COMPACT
  widget.scale, widget.text_scale = 1, 1
  widget.pulse = Mock(color=lambda color, now: color)
  widget.shapes = Mock()
  with patch('openpilot.starpilot.ui.speed_limit_widget.rl.draw_rectangle_rounded_lines_ex') as outline:
    widget._sign(current, speed_limit_bounds(Profile.COMPACT, current), 10.)
  rect = outline.call_args.args[0]
  assert (rect.x, rect.y, rect.width, rect.height) == (340, 28, 100, 116)
  assert outline.call_args.args[1:4] == (.14, 16, 2)
  calls = widget.fonts.draw.call_args_list
  for call, text, size, y, role in zip(calls, ['SPEED', 'LIMIT', value], [20, 20, 50 if len(value) <= 2 else 42],
                                        [38, 56, 86], [FontRole.SEMI_BOLD, FontRole.SEMI_BOLD, FontRole.BOLD], strict=True):
    measured = widget.fonts.measure(text, role, size)
    header_shift = 6 if pending_arrow and role == FontRole.SEMI_BOLD else 0
    # Without an actual pending arrow, the original screenshot's centered origin is exact.
    assert call.args[:5] == (text, role, size, 332 + (116 - measured.width) / 2 - header_shift, y)
  assert widget.shapes.arrow.called is pending_arrow
