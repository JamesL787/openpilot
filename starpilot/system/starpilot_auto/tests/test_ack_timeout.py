"""Video ACK watchdog: a stalled comma loop must not be mistaken for a silent car.

On 2026-10-01 Force Onroad started the dashcam encoders and the model mid-session; the comma's
streaming loop stalled about a second and the 1.5 s watchdog tore down a healthy projection.
These run a real TLS session against the fake head unit.
"""

import threading
import time
from types import SimpleNamespace

import pytest

from openpilot.starpilot.system.starpilot_auto import supervisor
from openpilot.starpilot.system.starpilot_auto.frame_source import FORMAT_RGBA
from openpilot.starpilot.system.starpilot_auto.session import PeerRequestedStop, ProjectionSession
from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import FakeHeadUnit
from openpilot.starpilot.system.starpilot_auto.tests.test_starpilot_auto import (delta_au, finish, identity, keyframe_au,  # noqa: F401
                                                                                  pump_until, run_until_streaming)

HONDA_SCREEN_TAKEBACK_S = 3.0  # the Civic gives its screen back after this long without video


def settle(session: ProjectionSession) -> None:
  """Read everything the car has sent. ACKs are counts, not frame ids: an ACK still unread from earlier frames
  would otherwise be credited to the next frame and hide a missing one."""
  deadline = time.monotonic() + 5
  while session.pump(0.2):
    assert time.monotonic() < deadline, "the car kept talking"
  assert session.unacked == 0


def held_frame(hu: FakeHeadUnit, session: ProjectionSession, tag: int = 2) -> float:
  """Send one frame the car receives but does not acknowledge yet; returns when it was sent."""
  settle(session)
  hu.hold_acks.set()
  pump_until(session, session.can_send)
  received = len(hu.frames)
  session.send_frame(delta_au(tag), tag, keyframe=False)
  deadline = time.monotonic() + 5
  while len(hu.frames) == received:
    assert time.monotonic() < deadline, "the car never received the frame"
    time.sleep(0.01)
  return session.pending[0]


def close(session: ProjectionSession, hu: FakeHeadUnit) -> None:
  hu.close()
  session.peer.close()


def test_timeout_leaves_room_for_a_stall_but_beats_the_car_taking_its_screen_back():
  assert 1.5 < ProjectionSession.ACK_TIMEOUT < HONDA_SCREEN_TAKEBACK_S


def test_a_loop_stall_longer_than_the_old_timeout_keeps_the_session(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  pump_until(session, session.can_send)
  session.send_frame(delta_au(2), 2, keyframe=False)  # the car acks this at once...
  time.sleep(2.0)  # ...while the comma's loop is stuck, as during the dashcam start-up
  session.check_progress()  # the old 1.5 s watchdog ended the projection here
  pump_until(session, lambda: session.acked == 2)
  assert not session.pending
  finish(session, hu)


def test_an_ack_queued_behind_a_message_burst_is_read_before_calling_the_car_silent(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  sent = held_frame(hu, session)
  for value in range(40):  # more than the streaming loop's 16-message batch
    hu.send_ping(value)
  hu.release_acks()  # the ACK arrives last, behind the burst
  time.sleep(0.3)
  session.check_progress(now=sent + ProjectionSession.ACK_TIMEOUT + 0.5)
  assert session.acked == 2 and not session.pending
  finish(session, hu)
  assert hu.ping_replies >= 40  # every queued ping was answered on the way


def test_a_car_that_stops_acking_still_times_out_at_the_new_limit(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  sent = held_frame(hu, session)
  session.check_progress(now=sent + 1.6)  # past the old 1.5 s limit: no longer fatal
  session.check_progress(now=sent + ProjectionSession.ACK_TIMEOUT - 0.05)
  with pytest.raises(TimeoutError, match="2.5 s"):
    session.check_progress(now=sent + ProjectionSession.ACK_TIMEOUT + 0.05)
  close(session, hu)


def test_a_real_silent_car_is_detected_in_real_time(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  held_frame(hu, session)
  started = time.monotonic()
  with pytest.raises(TimeoutError):
    while True:
      session.check_progress()
      assert time.monotonic() - started < ProjectionSession.ACK_TIMEOUT + 1.0, "a silent car was never detected"
      session.pump(0.05)
  assert time.monotonic() - started >= ProjectionSession.ACK_TIMEOUT - 0.2
  close(session, hu)


def test_draining_is_time_bounded_under_a_flood(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  sent = held_frame(hu, session)
  flooding = threading.Event()
  flooding.set()

  def flood():
    value = 0
    while flooding.is_set():
      try:
        hu.send_ping(value)
      except OSError:
        return
      value += 1

  flooder = threading.Thread(target=flood, daemon=True)
  flooder.start()
  time.sleep(0.2)
  started = time.monotonic()
  with pytest.raises(TimeoutError):
    session.check_progress(now=sent + ProjectionSession.ACK_TIMEOUT + 0.5)
  elapsed = time.monotonic() - started
  flooding.clear()
  assert elapsed < ProjectionSession.ACK_DRAIN_SECONDS + 0.4, f"drain ran {elapsed:.2f} s under a flood"
  close(session, hu)
  flooder.join(2)


def test_a_shutdown_queued_behind_a_late_ack_is_reported_as_the_shutdown(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  sent = held_frame(hu, session)
  hu.request_shutdown()
  time.sleep(0.2)
  with pytest.raises(PeerRequestedStop):
    session.check_progress(now=sent + ProjectionSession.ACK_TIMEOUT + 0.5)
  close(session, hu)


def test_unfocused_projection_never_times_out_on_old_frames(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  sent = held_frame(hu, session)
  hu.set_focus(False)  # the driver switched to the car's own screen
  pump_until(session, lambda: not session.focused)
  session.check_progress(now=sent + 10.0)  # well past the ACK limit, inside the separate 15 s silence check
  close(session, hu)


class _Source:
  frames = 0
  view = "synthetic"
  label = "synthetic"
  waiting_for_first_frame = False
  request = None
  source = SimpleNamespace(mark_sent=lambda captured_ns: None)

  def demand(self, seconds):
    pass

  def release_demand(self):
    pass

  def latest(self):
    self.frames += 1
    return SimpleNamespace(data=b"rgba", captured_ns=time.monotonic_ns(), pixel_format=FORMAT_RGBA)

  def send_touches(self, events):
    pass

  def check(self, now, *, focused):
    pass


@pytest.mark.parametrize("burst", [0, 40])
def test_streaming_survives_a_two_second_encoder_stall(identity, burst):
  """The real streaming loop, a real session and car: one encode stalls 2 s (the dashcam starting) while the
  car keeps acking and, in one case, sends a burst of messages. The projection must carry on."""
  hu = FakeHeadUnit(identity, window=4)
  session = run_until_streaming(hu, identity)
  encodes = [0]
  stalled_at = [0.0]
  stop = threading.Event()
  errors = []

  def encode(data, *, keyframe):
    encodes[0] += 1
    if encodes[0] == 5:
      stalled_at[0] = time.monotonic()
      for value in range(burst):
        hu.send_ping(value)
      time.sleep(2.0)
    if encodes[0] >= 25:
      stop.set()
    return (keyframe_au(encodes[0] % 250) if keyframe else delta_au(encodes[0] % 250)), keyframe

  sup = supervisor.Supervisor.__new__(supervisor.Supervisor)
  sup._stop = stop
  sup._status = {"state": "streaming"}
  sup._stage = lambda _: None
  sup._set = lambda **values: sup._status.update(values)
  sup.log = lambda *args, **kwargs: None

  def run():
    try:
      sup._stream(session, SimpleNamespace(encode_rgba=encode, last_encode_ms=1.0), _Source(),
                  SimpleNamespace(still_connected=lambda: True), 1 / 30)
    except BaseException as error:  # noqa: BLE001 - reported below
      errors.append(error)

  streamer = threading.Thread(target=run, daemon=True)
  streamer.start()
  streamer.join(20)
  assert not streamer.is_alive(), "streaming never finished"
  assert errors == [], f"the stall ended the projection: {errors[0]!r}" if errors else ""
  assert encodes[0] >= 25 and stalled_at[0] > 0
  pump_until(session, lambda: not session.pending)
  assert session.acked >= 24  # frames kept flowing and were acknowledged after the stall
  finish(session, hu)
