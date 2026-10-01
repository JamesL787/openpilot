from types import SimpleNamespace

from openpilot.starpilot.system.starpilot_auto import car_ui

STREAMS = SimpleNamespace(VISION_STREAM_ROAD=0, VISION_STREAM_DRIVER=1, VISION_STREAM_WIDE_ROAD=2)
STEP_MS = int(car_ui.CAMERA_WAIT_STEP * 1000)


class FakeSock:
  """A conflated CameraState socket and its poller: ``arrivals`` says whether each poll finds a message."""

  def __init__(self):
    self.arrivals: list[bool] = []
    self.timeouts: list[int] = []
    self._ready = False

  def poll(self, timeout_ms: int):
    self.timeouts.append(timeout_ms)
    self._ready = self.arrivals.pop(0) if self.arrivals else False
    return [self] if self._ready else []

  def receive(self, non_blocking: bool = False):
    ready, self._ready = self._ready, False
    return b"msg" if ready else None


def make_pacer():
  socks: dict[str, FakeSock] = {}

  def factory(name):
    socks[name] = FakeSock()
    return socks[name], socks[name]

  return car_ui.CameraPacer(sock_factory=factory, stream_types=STREAMS), socks


def test_draws_once_per_frame_of_the_shown_camera():
  pacer, socks = make_pacer()
  assert pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.0)  # nothing seen yet: quiet, draw now
  road = socks["roadCameraState"]
  road.arrivals = [True, False, True, False]
  assert pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.0)
  assert not pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.01)
  assert pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.05)
  assert not pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.06)  # same frame is never drawn twice
  assert road.timeouts == [0, 0, STEP_MS, STEP_MS, STEP_MS]


def test_subscribes_only_to_the_camera_on_screen():
  pacer, socks = make_pacer()
  pacer.wait(STREAMS.VISION_STREAM_WIDE_ROAD, 10.0)
  assert list(socks) == ["wideRoadCameraState"]
  pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.0)
  assert sorted(socks) == ["roadCameraState", "wideRoadCameraState"]


def test_quiet_camera_renders_at_the_encoder_rate():
  pacer, socks = make_pacer()
  pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.0)
  road = socks["roadCameraState"]
  road.arrivals = [True]
  assert pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.0)
  assert not pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.05)
  # The camera stopped: every later frame is drawn without waiting, not one per CAMERA_MAX_GAP.
  for i in range(10):
    assert pacer.wait(STREAMS.VISION_STREAM_ROAD, 10.001 + car_ui.CAMERA_MAX_GAP + i / 30)
  assert road.timeouts[-10:] == [0] * 10
  # And pacing resumes when it comes back.
  road.arrivals = [True]
  assert pacer.wait(STREAMS.VISION_STREAM_ROAD, 11.0)
  assert not pacer.wait(STREAMS.VISION_STREAM_ROAD, 11.03)


def test_unknown_stream_does_not_block():
  pacer, socks = make_pacer()
  assert pacer.wait(99, 10.0)
  assert socks == {}


def test_camera_pacing_respects_the_frame_cap_and_never_runs_ahead():
  """The render loop's order: the producer's schedule first, then the camera. 60 s of a
  20 Hz camera under a 15 fps cap (the software encoder) must render at ~15 fps and leave
  no backlog, so switching to a view without the camera renders right away."""
  from openpilot.starpilot.system.starpilot_auto.frame_source import FrameProducer, FrameRequest
  producer = object.__new__(FrameProducer)
  producer._next_capture_ns = 0
  request = FrameRequest(1280, 720, 0, 0, 1_000_000 // 15)
  pacer, socks = make_pacer()
  pacer.wait(STREAMS.VISION_STREAM_ROAD, 0.0)
  road = socks["roadCameraState"]
  camera_period_ns, step_ns = 50_000_000, 1_000_000
  renders, now_ns = 0, 1_000_000_000
  end_ns = now_ns + 60_000_000_000
  next_camera_ns = now_ns
  arrived = False
  while now_ns < end_ns:
    if now_ns >= next_camera_ns:
      arrived, next_camera_ns = True, next_camera_ns + camera_period_ns
    if producer.capture_delay(request, now_ns) == 0:
      road.arrivals = [arrived]
      arrived = False
      if pacer.wait(STREAMS.VISION_STREAM_ROAD, now_ns / 1e9):
        producer.advance(request, now_ns)
        renders += 1
    now_ns += step_ns
  assert 14.5 <= renders / 60 <= 15.5
  assert producer._next_capture_ns - now_ns <= request.interval_us * 1000
  assert producer.capture_delay(request, now_ns + request.interval_us * 1000) == 0


def test_camera_pacing_follows_the_camera_under_a_higher_cap():
  """Under a 30 fps cap, a live 20 Hz camera paces rendering to ~20 fps."""
  from openpilot.starpilot.system.starpilot_auto.frame_source import FrameProducer, FrameRequest
  producer = object.__new__(FrameProducer)
  producer._next_capture_ns = 0
  request = FrameRequest(1280, 720, 0, 0, 1_000_000 // 30)
  pacer, socks = make_pacer()
  pacer.wait(STREAMS.VISION_STREAM_ROAD, 0.0)
  road = socks["roadCameraState"]
  renders, now_ns = 0, 1_000_000_000
  end_ns = now_ns + 10_000_000_000
  next_camera_ns = now_ns
  arrived = False
  while now_ns < end_ns:
    if now_ns >= next_camera_ns:
      arrived, next_camera_ns = True, next_camera_ns + 50_000_000
    if producer.capture_delay(request, now_ns) == 0:
      road.arrivals = [arrived]
      arrived = False
      if pacer.wait(STREAMS.VISION_STREAM_ROAD, now_ns / 1e9):
        producer.advance(request, now_ns)
        renders += 1
    now_ns += 1_000_000
  assert 19.5 <= renders / 10 <= 20.5
