"""Controller-timed automatic pulses and the stationary manual confirmation rhythm."""
from dataclasses import replace

import pyray as rl
import pytest

from openpilot.starpilot.ui.onroad_state import ObservationKind, OnroadState, SpeedLimitObservation
from openpilot.starpilot.ui.speed_limit_pulse import SpeedLimitPulse


def rgba(color):
  return tuple(color) if isinstance(color, tuple) else (color.r, color.g, color.b, color.a)


def state(automatic=True, **changes):
  obs = SpeedLimitObservation(ObservationKind.VALID, 'dashboard', 20., pending_speed_limit_mps=20.,
                             automatic_adoption_pending=automatic, pending_since_ns=10_000_000_000)
  return replace(OnroadState(True, False, 10., 80., obs, drive_frame=1), **changes)


def test_three_slow_flashes_stop_at_the_controller_deadline():
  pulse = SpeedLimitPulse()
  pulse.update(state(), 10.25)
  assert pulse.start_time == 10.
  for now in (10., 11., 12., 13., 14.):
    assert rgba(pulse.color(rl.WHITE, now)) == rgba(rl.WHITE)
  for now in (10.5, 11.5, 12.5):
    assert rgba(pulse.color(rl.WHITE, now)) == (188, 132, 255, 255)


def test_manual_confirmation_repeats_two_slow_pulses_rest_and_two_fast_pulses():
  pulse = SpeedLimitPulse()
  pulse.update(state(False), 10.)
  base = rl.Color(244, 247, 245, 96)
  for cycle in (0., 4.4):
    for elapsed in (.35, 1.25, 2.75, 3.25):
      now = 10. + cycle + elapsed
      pulse.update(state(False), now)
      assert rgba(pulse.color(base, now)) == (170, 115, 235, 96)
    for elapsed in (0., .8, 1.6, 2.1, 2.59, 3., 3.4, 3.9, 4.39):
      assert rgba(pulse.color(base, 10. + cycle + elapsed)) == rgba(base)
  assert rgba(pulse.color(base, 9.9)) == rgba(base)


@pytest.mark.parametrize('kind', list(ObservationKind))
def test_finished_or_unavailable_manual_decision_stops_pulsing(kind):
  pulse = SpeedLimitPulse()
  current = state(False)
  pulse.update(current, 10.)
  observation = replace(current.speed_limit, kind=kind, speed_limit_mps=20. if kind == ObservationKind.VALID else None,
                        pending_speed_limit_mps=None, last_received_speed_limit_mps=20.)
  pulse.update(replace(current, speed_limit=observation), 10.1)
  assert rgba(pulse.color(rl.WHITE, 10.35)) == rgba(rl.WHITE)
  assert pulse.start_time == -float('inf')


def test_manual_widget_reappearance_and_new_decision_use_controller_time():
  pulse = SpeedLimitPulse()
  pulse.update(state(False), 10., visible=False)
  pulse.update(state(False), 12.6)
  assert rgba(pulse.color(rl.WHITE, 12.75)) == (170, 115, 235, 255)
  current = state(False)
  current = replace(current, speed_limit=replace(current.speed_limit, pending_since_ns=13_000_000_000,
                                               speed_limit_mps=25., pending_speed_limit_mps=25.))
  pulse.update(current, 13.)
  assert rgba(pulse.color(rl.WHITE, 13.)) == rgba(rl.WHITE)
  assert rgba(pulse.color(rl.WHITE, 13.35)) == (170, 115, 235, 255)


def test_missing_pending_timestamp_starts_once_and_resets_for_a_new_drive():
  pulse = SpeedLimitPulse()
  current = state(False)
  current = replace(current, speed_limit=replace(current.speed_limit, pending_since_ns=0))
  pulse.update(current, 10.)
  pulse.update(current, 10.35)
  assert rgba(pulse.color(rl.WHITE, 10.35)) == (170, 115, 235, 255)
  pulse.update(replace(current, drive_frame=2), 20.)
  assert pulse.start_time == 20.


def test_switching_between_manual_and_automatic_uses_the_current_rhythm():
  pulse = SpeedLimitPulse()
  pulse.update(state(), 10.)
  pulse.update(state(False), 10.)
  assert rgba(pulse.color(rl.WHITE, 10.35)) == (170, 115, 235, 255)
  pulse.update(state(), 10.)
  assert rgba(pulse.color(rl.WHITE, 10.5)) == (188, 132, 255, 255)
  assert rgba(pulse.color(rl.WHITE, 13.)) == rgba(rl.WHITE)


def test_reappearing_widget_uses_remaining_controller_time():
  pulse = SpeedLimitPulse()
  pulse.update(state(), 10., visible=False)
  pulse.update(state(), 12.)
  assert rgba(pulse.color(rl.WHITE, 12.5)) == (188, 132, 255, 255)
  assert rgba(pulse.color(rl.WHITE, 13.)) == rgba(rl.WHITE)


def display_state(limit=20., **changes):
  current = state()
  return replace(current, speed_limit=replace(current.speed_limit, speed_limit_mps=limit,
    pending_speed_limit_mps=None, automatic_adoption_pending=False, action_enabled=False, pending_since_ns=0), **changes)


def test_display_only_new_limit_pulses_without_restarting_on_repeated_messages():
  pulse = SpeedLimitPulse()
  pulse.update(display_state(), 10.)
  pulse.update(display_state(), 10.5)
  assert rgba(pulse.color(rl.WHITE, 10.5)) == (188, 132, 255, 255)
  pulse.update(display_state(), 13.5)
  assert rgba(pulse.color(rl.WHITE, 13.5)) == rgba(rl.WHITE)
  pulse.update(display_state(25.), 14.)
  pulse.update(display_state(25.), 14.5)
  assert rgba(pulse.color(rl.WHITE, 14.5)) == (188, 132, 255, 255)


def test_display_only_hidden_stale_and_reappearance_do_not_invent_new_limit():
  pulse = SpeedLimitPulse()
  pulse.update(display_state(), 10., visible=False)
  pulse.update(display_state(), 10.5)
  assert rgba(pulse.color(rl.WHITE, 10.5)) == rgba(rl.WHITE)
  current = display_state()
  stale = replace(current, speed_limit=replace(current.speed_limit, kind=ObservationKind.STALE,
                  speed_limit_mps=None, last_received_speed_limit_mps=25.))
  pulse.update(stale, 11.)
  assert rgba(pulse.color(rl.WHITE, 11.5)) == rgba(rl.WHITE)
  pulse.update(display_state(25.), 12.)
  assert rgba(pulse.color(rl.WHITE, 12.5)) == rgba(rl.WHITE)


def test_display_only_new_drive_can_highlight_its_first_limit():
  pulse = SpeedLimitPulse()
  pulse.update(display_state(), 10.)
  pulse.update(display_state(drive_frame=2), 20.)
  assert rgba(pulse.color(rl.WHITE, 20.5)) == (188, 132, 255, 255)
