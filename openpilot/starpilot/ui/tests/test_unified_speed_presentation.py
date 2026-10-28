"""Presentation follows selected set speed and the latest source observation."""
from dataclasses import replace

import pytest

from openpilot.starpilot.ui.onroad_state import ObservationKind, OnroadState, SpeedLimitObservation
from openpilot.starpilot.ui.unified_speed_presentation import resolve_unified_speed


def state(**changes):
  obs = SpeedLimitObservation(ObservationKind.VALID, 'vision', 30., accepted_speed_limit_mps=20.,
    accepted_adjusted_limit_mps=22., accepted_source='dashboard', presentation_adjusted_limit_mps=32.,
    action_enabled=True, session_id='drive')
  return replace(OnroadState(True, False, 20., 100., obs, metric=True, longitudinal_active=True), **changes)


@pytest.mark.parametrize('metric,posted,offset', [(True, '108', '+7'), (False, '67', '+5')])
def test_latest_received_source_and_offset_are_independent_of_accepted_history(metric, posted, offset):
  shown = resolve_unified_speed(state(metric=metric))
  assert (shown.posted_text, shown.source, shown.offset_text) == (posted, 'vision', offset)
  assert shown.active_side == 'max'


def test_set_speed_is_the_only_active_speed_role_even_below_or_above_the_input_limit():
  for selected in (50., 79.2, 120.):
    shown = resolve_unified_speed(state(cruise_kph=selected))
    assert shown.max_text == str(round(selected))
    assert shown.max_status == 'Set speed'
    assert (shown.active_side, shown.status) == ('max', 'Using set speed')


@pytest.mark.parametrize('automatic,status', [(False, 'Confirm speed limit'), (True, 'Adopting limit')])
def test_pending_limit_is_shown_immediately_with_its_own_offset(automatic, status):
  current = state()
  obs = replace(current.speed_limit, pending_speed_limit_mps=30., pending_adjusted_limit_mps=32., automatic_adoption_pending=automatic)
  shown = resolve_unified_speed(replace(current, speed_limit=obs))
  assert (shown.posted_text, shown.offset_text, shown.status) == ('108', '+7', status)
  assert shown.pending


def test_manual_override_and_pedal_status_preserve_the_set_speed_and_sign():
  current = state()
  manual = resolve_unified_speed(replace(current, speed_limit=replace(current.speed_limit, driver_override_active=True)))
  pedal = resolve_unified_speed(replace(current, longitudinal_overridden=True))
  assert manual.status == 'Set-speed override'
  assert pedal.status == 'Using accelerator'
  assert manual.max_text == pedal.max_text == '100'
  assert manual.posted_text == pedal.posted_text == '108'


def test_retained_limit_is_information_only_without_a_separate_ceiling():
  current = state()
  retained = replace(current.speed_limit, kind=ObservationKind.UNKNOWN, speed_limit_mps=None,
                     effective_cluster_target_mps=22., effective_cap_mps=None)
  shown = resolve_unified_speed(replace(current, speed_limit=retained))
  assert (shown.posted_text, shown.offset_text, shown.source) == ('72', '+7', 'dashboard')
  assert shown.active_side == 'max'


def test_display_only_and_unset_speed_remain_explicit():
  current = state(cruise_kph=None, longitudinal_active=False)
  shown = resolve_unified_speed(replace(current, speed_limit=replace(current.speed_limit, action_enabled=False)))
  assert (shown.max_text, shown.max_status, shown.status) == ('–', 'Not set', 'Display only')


def test_hidden_max_and_offset_preferences_keep_the_latest_sign():
  current = state()
  shown = resolve_unified_speed(replace(current, customization={**current.customization, 'showMaxSpeed': False}, show_slc_offset=False))
  assert (shown.mode, shown.posted_text, shown.offset_text) == ('limit_only', '108', None)


@pytest.mark.parametrize('pending,adjusted,presentation,offset,expected', [
  (30., 33., 32., 2., '119'),
  (30., None, 32., 2., '115'),
  (30., None, None, 2., '115'),
  (25., None, 32., 2., '97'),
])
def test_confirmation_proposal_uses_the_pending_target_and_its_offset(pending, adjusted, presentation, offset, expected):
  current = state()
  observation = replace(current.speed_limit, pending_speed_limit_mps=pending, pending_adjusted_limit_mps=adjusted,
                        presentation_adjusted_limit_mps=presentation, offset_mps=offset)
  assert resolve_unified_speed(replace(current, speed_limit=observation)).proposal_text == expected
