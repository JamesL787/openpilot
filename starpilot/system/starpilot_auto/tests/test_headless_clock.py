import pytest

from openpilot.starpilot.system.starpilot_auto import headless_egl


@pytest.fixture
def clock():
  # Only the frame clock; no EGL context needed.
  context = object.__new__(headless_egl.HeadlessContext)
  context.frame_time = context._fps_frame_time = 1 / 30
  context._last_frame = None
  return context


def test_frame_time_follows_the_real_frame_interval(clock):
  for i in range(60):
    clock.begin_frame(10.0 + i * 0.05)  # the camera's 20 Hz
  assert clock.frame_time == pytest.approx(0.05)
  assert round(1 / clock._fps_frame_time) == 20


def test_a_stall_advances_animations_by_at_most_the_clamp(clock):
  clock.begin_frame(10.0)
  clock.begin_frame(15.0)
  assert clock.frame_time == headless_egl.MAX_FRAME_TIME


def test_pause_keeps_the_last_interval(clock):
  clock.begin_frame(10.0)
  clock.begin_frame(10.05)
  clock.pause()
  clock.begin_frame(99.0)  # first frame after the car showed its own screen
  assert clock.frame_time == pytest.approx(0.05)
