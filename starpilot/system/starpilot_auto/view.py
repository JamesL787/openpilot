"""What the car shows: the car-sized StarPilot UI, a mirror of the comma screen, or a test pattern.

The car view runs ``car_ui`` as a child process and reads its frames from a
dedicated shared-memory slot. If it fails to start, exits, or stops producing
frames, the view falls back to mirroring the comma screen for the rest of the
session instead of ending projection. The fallback reason is reported in status.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from openpilot.starpilot.system.starpilot_auto.frame_source import DEFAULT_PATH, FrameConsumer, FrameRequest, SyntheticFrames
from openpilot.starpilot.system.starpilot_auto.touch import DEFAULT_TOUCH_SOCKET, TouchEvent, TouchSender

CAR_FRAME_PATH = "/dev/shm/starpilot_starpilot_auto_car_frame"
CAR_STARTUP_TIMEOUT = 25.0   # loading the full UI (fonts, textures, layouts) takes a few seconds on device
CAR_STALL_TIMEOUT = 5.0


class ViewSource:
  def __init__(self, view: str, request: FrameRequest, log, *, synthetic: bool = False, mirror_path: str = DEFAULT_PATH,
               car_path: str = CAR_FRAME_PATH, touch_path: str = DEFAULT_TOUCH_SOCKET, renderer_command: list[str] | None = None,
               renderer_log: Path | None = None):
    self.log = log
    self.request = request
    self.mirror_path, self.car_path, self.touch_path = mirror_path, car_path, touch_path
    self.renderer_command = renderer_command or [sys.executable, "-m", "openpilot.starpilot.system.starpilot_auto.car_ui",
                                                 "--frames", car_path, "--touch", touch_path]
    self.renderer_log = renderer_log
    self.process: subprocess.Popen | None = None
    self.touch: TouchSender | None = None
    self.fallback_reason = ""
    self.started_at = time.monotonic()
    self.last_frame_at = 0.0
    self.unfocused_since: float | None = None
    self.frames = 0
    if synthetic:
      self.view = "synthetic"
      self.source = SyntheticFrames()
      self.source.configure(request)
    elif view == "car":
      self.view = "car"
      self._start_car()
    else:
      self.view = "mirror"
      self.source = self._consumer(mirror_path)

  def _consumer(self, path: str) -> FrameConsumer:
    consumer = FrameConsumer(path)
    consumer.configure(self.request)
    consumer.demand(1.0)
    return consumer

  def _start_car(self) -> None:
    self.source = self._consumer(self.car_path)
    output = subprocess.DEVNULL
    if self.renderer_log is not None:
      try:
        self.renderer_log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        output = open(self.renderer_log, "w")
      except OSError:
        output = subprocess.DEVNULL
    try:
      self.process = subprocess.Popen(self.renderer_command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                      close_fds=True)
    finally:
      if output is not subprocess.DEVNULL:
        output.close()
    try:
      os.setpriority(os.PRIO_PROCESS, self.process.pid, 19)  # driving processes at normal priority must never wait on the car screen
    except OSError:
      pass
    self.touch = TouchSender(self.touch_path)
    self.started_at = time.monotonic()
    self.log("car_view_started", pid=self.process.pid)

  @property
  def label(self) -> str:
    return f"mirror (car view failed: {self.fallback_reason})" if self.fallback_reason else self.view

  @property
  def waiting_for_first_frame(self) -> bool:
    return self.frames == 0

  def demand(self, seconds: float = 1.0) -> None:
    self.source.demand(seconds)

  def release_demand(self) -> None:
    self.source.release_demand()

  def latest(self):
    frame = self.source.latest()
    if frame is not None:
      self.frames += 1
      self.last_frame_at = time.monotonic()
    return frame

  def send_touches(self, events: list[TouchEvent]) -> None:
    if self.touch is not None and self.view == "car" and events:
      self.touch.send(events)

  def check(self, now: float | None = None, *, focused: bool = True) -> None:
    """Fall back to mirroring when the car view is not healthy.

    Frames are only pulled while the car shows projection, so the startup and
    stall timers are paused while it shows its own screen.
    """
    if self.view != "car":
      return
    now = time.monotonic() if now is None else now
    if not focused:
      if self.unfocused_since is None:
        self.unfocused_since = now
    elif self.unfocused_since is not None:
      paused = now - self.unfocused_since
      self.started_at += paused
      self.last_frame_at += paused
      self.unfocused_since = None
    reason = ""
    code = self.process.poll() if self.process is not None else None
    if code is not None:
      reason = f"renderer exited with {code}"
    elif not focused:
      pass
    elif self.frames == 0 and now - self.started_at > CAR_STARTUP_TIMEOUT:
      reason = f"no frames after {CAR_STARTUP_TIMEOUT:.0f} s"
    elif self.frames and now - self.last_frame_at > CAR_STALL_TIMEOUT:
      reason = f"frames stopped for {CAR_STALL_TIMEOUT:.0f} s"
    if reason:
      self.fallback(reason)

  def fallback(self, reason: str) -> None:
    self.log("car_view_fallback", reason=reason)
    self._stop_car()
    self.fallback_reason = reason
    self.view = "mirror"
    self.frames = 0
    self.source = self._consumer(self.mirror_path)

  def _stop_car(self) -> None:
    if self.touch is not None:
      self.touch.close()
      self.touch = None
    process, self.process = self.process, None
    if process is not None and process.poll() is None:
      process.terminate()
      try:
        process.wait(timeout=3.0)
      except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)
    self.source.close()

  def close(self) -> None:
    if self.view == "car" or self.process is not None:
      self._stop_car()
    else:
      self.source.close()


def renderer_available() -> bool:
  """The car view needs the GPU render node; everywhere else it would only fall back."""
  return os.path.exists("/dev/dri/renderD128")
