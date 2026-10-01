from collections import deque
from types import SimpleNamespace
import threading
import time

import pytest

from openpilot.starpilot.system.starpilot_auto.compat_report import summarize
from openpilot.starpilot.system.starpilot_auto.session import ProjectionSession


def ack_session():
  session = ProjectionSession.__new__(ProjectionSession)
  session.retired_sessions = deque()
  session.session_id = 1
  session.config_ack_slack = 1
  session.unacked = 1
  session.pending = deque([time.monotonic()])
  session.max_ack_seconds = 0
  session.acked = session.epoch_acked = 0
  session.video_confirmed = False
  events = []
  session._log = lambda name, **values: events.append(name)
  return session, events


def test_configuration_ack_alone_does_not_confirm_video():
  session, events = ack_session()
  session._handle_ack(1, 1)
  assert not events
  assert session.unacked == 0  # preserve the existing flow-control behavior
  session._handle_ack(1, 1)  # the additional ACK proves at least one was a frame
  assert events == ["video_acknowledged"]


@pytest.mark.parametrize("separate_config", [False, True])
def test_video_confirmation_with_optional_or_separate_config_ack(separate_config):
  session, events = ack_session()
  if separate_config:
    session._handle_ack(0, 1)
    assert not events
  session._handle_ack(1, 1)
  if not separate_config:
    assert not events  # one ACK is still ambiguous
  session.unacked = 1
  session.pending.append(time.monotonic())
  session._handle_ack(1, 1)
  assert events == ["video_acknowledged"]


def test_combined_config_and_frame_ack_confirms_video():
  session, events = ack_session()
  session._handle_ack(1, 2)
  assert events == ["video_acknowledged"]


def test_successful_retry_clears_outcome_failure_but_keeps_history():
  failure = {"event": "attempt_failed", "stage": "streaming", "error": "link lost"}
  events = [{"event": "video_acknowledged"}, failure]
  assert summarize(events)["outcome"] == "projected, then failed: link lost"
  events.append({"event": "video_acknowledged"})
  report = summarize(events)
  assert report["outcome"] == "projected"
  assert report["errors"] == [{"stage": "streaming", "error": "link lost"}]
  events.append(failure)
  assert summarize(events)["outcome"] == "projected, then failed: link lost"


@pytest.mark.parametrize("timeout", [False, True])
def test_usb_tool_distinguishes_timeout_from_user_cancellation(monkeypatch, mocker, timeout):
  from openpilot.tools.starpilot_auto import usb_device

  supervisor = SimpleNamespace(config={}, _stop=threading.Event(), log=mocker.Mock(recent=[]), _close_sockets=lambda: None)
  supervisor.status = lambda: {"state": "waiting_for_usb"}
  timers = []

  class Timer:
    def __init__(self, seconds, callback):
      self.callback = callback
      timers.append(self)

    def start(self):
      pass

    def cancel(self):
      pass

  def attempt():
    if timeout:
      timers[0].callback()
    else:
      supervisor._stop.set()
    raise usb_device.Cancelled()

  supervisor._attempt_usb = attempt
  monkeypatch.setattr(usb_device, "Supervisor", lambda: supervisor)
  monkeypatch.setattr(usb_device.threading, "Timer", Timer)
  monkeypatch.setattr(usb_device.signal, "signal", lambda *args: None)
  monkeypatch.setattr(usb_device.identity_store, "load_identity", lambda: SimpleNamespace(expires="test", days_left=1))
  monkeypatch.setattr("sys.argv", ["usb_device", "--wait", "1"])
  assert usb_device.main() == int(timeout)
