"""The sign flashes only during the controller's three-second automatic window."""
from dataclasses import replace

import pyray as rl

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


def test_a_manual_proposal_never_flashes_and_leaving_automatic_stops_the_flash():
  pulse = SpeedLimitPulse()
  pulse.update(state(False), 10.)
  assert rgba(pulse.color(rl.WHITE, 10.5)) == rgba(rl.WHITE)
  pulse.update(state(), 11.)
  pulse.update(state(False), 11.1)
  assert rgba(pulse.color(rl.WHITE, 11.5)) == rgba(rl.WHITE)


def test_reappearing_widget_uses_remaining_controller_time():
  pulse = SpeedLimitPulse()
  pulse.update(state(), 10., visible=False)
  pulse.update(state(), 12.)
  assert rgba(pulse.color(rl.WHITE, 12.5)) == (188, 132, 255, 255)
  assert rgba(pulse.color(rl.WHITE, 13.)) == rgba(rl.WHITE)
