import http.client
import json
import socket
import sys
import threading
import time

import numpy as np
import pytest

from openpilot.system.ui.lib import ui_stream
from openpilot.system.ui.lib.ui_stream import StreamConfig, StreamConfigError, UiStream


@pytest.fixture
def make_stream():
  created: list[UiStream] = []

  def _make(**kwargs) -> UiStream:
    config = StreamConfig(bind="127.0.0.1", port=0, **kwargs)
    stream = UiStream(config)
    stream.serve()
    created.append(stream)
    return stream

  yield _make

  for stream in created:
    stream.stop()


def get(stream: UiStream, path: str, timeout: float = 5.0):
  conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=timeout)
  conn.request("GET", path)
  return conn, conn.getresponse()


# ------------------------------------------------------------------ config


def test_parse_config_kill_switch_ignores_other_variables():
  # STREAM=0 is the only way to turn the feature off, and it wins over any
  # other (even invalid) stream variable.
  assert ui_stream.parse_config({"STREAM": "0", "STREAM_PORT": "nonsense"}) is None
  assert ui_stream.parse_config({"STREAM": "0"}) is None


def test_parse_config_available_by_default():
  # The streamer starts on demand, so an unset STREAM means "available".
  expected = StreamConfig(bind="0.0.0.0", port=8091, quality=60, fps=20, width=1280)
  assert ui_stream.parse_config({}) == expected
  assert ui_stream.parse_config({"STREAM": "1"}) == expected
  assert ui_stream.parse_config({"STREAM_PORT": "1234"}).port == 1234


def test_parse_config_device_default_fps():
  # mici passes its own default; an explicit STREAM_FPS still wins.
  assert ui_stream.parse_config({}, ui_stream.COMPACT_UI_FPS).fps == ui_stream.COMPACT_UI_FPS
  assert ui_stream.parse_config({"STREAM_FPS": "20"}, ui_stream.COMPACT_UI_FPS).fps == 20


def test_parse_config_overrides():
  config = ui_stream.parse_config({
    "STREAM": "1", "STREAM_BIND": "127.0.0.1", "STREAM_PORT": "9000",
    "STREAM_QUALITY": "80", "STREAM_FPS": "20", "STREAM_WIDTH": "0",
  })
  assert config == StreamConfig(bind="127.0.0.1", port=9000, quality=80, fps=20, width=0)


@pytest.mark.parametrize("env, token", [
  ({"STREAM": "1", "STREAM_BIND": "localhost"}, "STREAM_BIND"),
  ({"STREAM": "1", "STREAM_PORT": "80"}, "STREAM_PORT"),
  ({"STREAM": "1", "STREAM_PORT": "abc"}, "STREAM_PORT"),
  ({"STREAM": "1", "STREAM_QUALITY": "0"}, "STREAM_QUALITY"),
  ({"STREAM": "1", "STREAM_QUALITY": "100"}, "STREAM_QUALITY"),
  ({"STREAM": "1", "STREAM_FPS": "0"}, "STREAM_FPS"),
  ({"STREAM": "1", "STREAM_FPS": "31"}, "STREAM_FPS"),
  ({"STREAM": "1", "STREAM_WIDTH": "100"}, "STREAM_WIDTH"),
  ({"STREAM": "1", "STREAM_WIDTH": "5000"}, "STREAM_WIDTH"),
])
def test_parse_config_invalid(env, token):
  with pytest.raises(StreamConfigError, match=token):
    ui_stream.parse_config(env)


def test_from_env_disabled_returns_none():
  assert UiStream.from_env({"STREAM": "0"}) is None


def test_from_env_invalid_returns_none():
  assert UiStream.from_env({"STREAM": "1", "STREAM_PORT": "1"}) is None


# -------------------------------------------------------------------- viewer


def test_viewer_served_with_framing(make_stream):
  stream = make_stream()
  conn, response = get(stream, "/")
  try:
    body = response.read()
    assert response.status == 200
    assert response.getheader("Content-Type").startswith("text/html")
    assert response.getheader("Cache-Control") == "no-store"
    assert int(response.getheader("Content-Length")) == len(body)
    assert b"StarPilot Live UI" in body
  finally:
    conn.close()


def test_viewer_holds_a_connection_through_a_pause():
  html = ui_stream.viewer_html().decode()
  # A paused streamer answers 503 until rendering resumes, so the viewer keeps
  # asking for a bounded grace period instead of treating it as a dead link...
  assert "PAUSED_GRACE_MS" in html and "pausedWaiting" in html
  # ...and stops once the pause is clearly not lifting, so a parked car cannot
  # be held rendering by a forgotten tab.
  assert 'if (streamState === "paused" && !pausedWaiting()) return;' in html


def test_viewer_explains_that_the_streamer_stops_when_idle():
  html = ui_stream.viewer_html().decode()
  # Reloading the viewer cannot restart a self-stopped streamer; only a start
  # request through Galaxy can.
  assert "open Live UI in Galaxy to start it again" in html


def test_viewer_targets_parent_origin_not_wildcard():
  html = ui_stream.viewer_html().decode()
  assert "resolveParentOrigin" in html
  assert "parentOrigin" in html
  assert "postMessage(msg, PARENT_ORIGIN)" in html
  assert 'postMessage(msg, "*")' not in html


def test_unknown_path_404(make_stream):
  stream = make_stream()
  conn, response = get(stream, "/nope")
  try:
    assert response.status == 404
    assert response.read()
  finally:
    conn.close()


def test_unsupported_method_405(make_stream):
  stream = make_stream()
  conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
  try:
    conn.request("POST", "/")
    response = conn.getresponse()
    assert response.status == 405
    assert response.getheader("Allow") == "GET"
    response.read()
  finally:
    conn.close()


def test_head_supported_for_finite_responses(make_stream):
  stream = make_stream()
  for path in ("/", "/status"):
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    try:
      conn.request("HEAD", path)
      response = conn.getresponse()
      assert response.status == 200
      assert int(response.getheader("Content-Length")) > 0
      assert response.read() == b""  # HEAD body is suppressed
    finally:
      conn.close()


def test_head_rejected_for_demand_endpoints(make_stream):
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8frame\xff\xd9")
  for path in ("/stream", "/frames", "/snapshot", "/telemetry", "/nope"):
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    try:
      conn.request("HEAD", path)
      response = conn.getresponse()
      expected = 404 if path == "/nope" else 405
      assert response.status == expected
      assert response.read() == b""
    finally:
      conn.close()
  assert stream._active_streams == 0  # HEAD created no demand


def test_status_reports_counters(make_stream):
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8fake\xff\xd9")
  conn, response = get(stream, "/status")
  try:
    payload = json.loads(response.read())
    assert response.status == 200
    assert payload["state"] == "ready"
    assert payload["frameSequence"] == 1
    assert payload["counters"]["published"] == 1
    assert payload["maxStreams"] == ui_stream.MAX_STREAMS
  finally:
    conn.close()


def test_telemetry_requires_interest_and_data(make_stream):
  stream = make_stream()
  conn, response = get(stream, "/telemetry")
  try:
    assert response.status == 503
    response.read()
  finally:
    conn.close()

  payload = json.dumps({"schemaVersion": 1, "vEgo": 1.0}).encode()
  stream.set_telemetry(payload)
  conn, response = get(stream, "/telemetry")
  try:
    assert response.status == 200
    assert response.read() == payload
  finally:
    conn.close()


def test_telemetry_max_age(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "TELEMETRY_MAX_AGE", 0.01)
  stream = make_stream()
  stream.set_telemetry(b'{"schemaVersion":1}')
  time.sleep(0.05)
  conn, response = get(stream, "/telemetry")
  try:
    assert response.status == 503
    response.read()
  finally:
    conn.close()


# ----------------------------------------------------------------- snapshot


def test_snapshot_without_frame_503(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "SNAPSHOT_WAIT", 0.1)
  stream = make_stream()
  conn, response = get(stream, "/snapshot")
  try:
    assert response.status == 503
    assert response.getheader("Retry-After") == "1"
    response.read()
  finally:
    conn.close()


def test_snapshot_serves_fresh_frame(make_stream):
  stream = make_stream()
  frame = b"\xff\xd8jpeg-body\xff\xd9"
  stream.publish_encoded_frame(frame)
  conn, response = get(stream, "/snapshot")
  try:
    assert response.status == 200
    assert response.getheader("Content-Type") == "image/jpeg"
    assert response.read() == frame
  finally:
    conn.close()


def test_snapshot_waits_for_new_frame(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "SNAPSHOT_MAX_AGE", -1.0)
  monkeypatch.setattr(ui_stream, "SNAPSHOT_WAIT", 2.0)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8old\xff\xd9")

  result: dict[str, object] = {}

  def request():
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    conn.request("GET", "/snapshot")
    response = conn.getresponse()
    result["status"] = response.status
    result["body"] = response.read()
    conn.close()

  thread = threading.Thread(target=request)
  thread.start()
  time.sleep(0.2)
  stream.publish_encoded_frame(b"\xff\xd8new\xff\xd9")
  thread.join(timeout=5.0)

  assert result["status"] == 200
  assert result["body"] == b"\xff\xd8new\xff\xd9"


def test_concurrent_snapshots_coalesce(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "SNAPSHOT_MAX_AGE", -1.0)
  monkeypatch.setattr(ui_stream, "SNAPSHOT_WAIT", 2.0)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8old\xff\xd9")

  results: list[bytes] = []
  lock = threading.Lock()

  def request():
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    conn.request("GET", "/snapshot")
    response = conn.getresponse()
    body = response.read()
    conn.close()
    if response.status == 200:
      with lock:
        results.append(body)

  threads = [threading.Thread(target=request) for _ in range(3)]
  for thread in threads:
    thread.start()
  time.sleep(0.3)
  stream.publish_encoded_frame(b"\xff\xd8coalesced\xff\xd9")
  for thread in threads:
    thread.join(timeout=5.0)

  assert results == [b"\xff\xd8coalesced\xff\xd9"] * 3
  assert stream._active_streams == 0
  # The shared lease ends with the last waiter, not SNAPSHOT_LEASE seconds later.
  assert stream.image_demand_active() is False


def test_snapshot_lease_ends_with_the_snapshot(make_stream, monkeypatch):
  # A snapshot is one frame of demand. Holding SNAPSHOT_LEASE (3 s) after it
  # succeeded would keep capturing and encoding ~30 frames for one request.
  monkeypatch.setattr(ui_stream, "SNAPSHOT_MAX_AGE", -1.0)
  stream = make_stream()

  def request():
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    conn.request("GET", "/snapshot")
    response = conn.getresponse()
    response.read()
    conn.close()

  thread = threading.Thread(target=request)
  thread.start()
  deadline = time.monotonic() + 2.0
  while not stream.image_demand_active() and time.monotonic() < deadline:
    time.sleep(0.01)
  assert stream.image_demand_active() is True  # lease held while waiting
  stream.publish_encoded_frame(b"\xff\xd8snap\xff\xd9")
  thread.join(timeout=5.0)

  assert stream.image_demand_active() is False
  assert stream._snapshot_deadline == 0.0


def test_snapshot_lease_released_on_timeout(make_stream, monkeypatch):
  # Same for the failing path: a 503 must not leave demand behind either.
  monkeypatch.setattr(ui_stream, "SNAPSHOT_MAX_AGE", -1.0)
  monkeypatch.setattr(ui_stream, "SNAPSHOT_WAIT", 0.1)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8old\xff\xd9")

  conn, response = get(stream, "/snapshot")
  try:
    assert response.status == 503
    response.read()
  finally:
    conn.close()
  assert stream.image_demand_active() is False


# ------------------------------------------------------------------- stream


def _read_multipart_part(response) -> tuple[dict[str, str], bytes]:
  """One part as (lower-cased headers, body)."""
  # Skip status header already parsed; read one part.
  buf = b""
  while b"\r\n\r\n" not in buf:
    chunk = response.read(1)
    if not chunk:
      break
    buf += chunk
  header, _, rest = buf.partition(b"\r\n\r\n")
  assert header.lstrip(b"\r\n").startswith(b"--frame")
  headers = {}
  for line in header.decode().splitlines()[1:]:
    key, _, value = line.partition(":")
    headers[key.strip().lower()] = value.strip()
  content_length = int(headers["content-length"])
  body = rest
  while len(body) < content_length:
    chunk = response.read(content_length - len(body))
    if not chunk:
      break
    body += chunk
  assert response.read(2) == b"\r\n"
  return headers, body[:content_length]


def _read_multipart_frame(response) -> bytes:
  return _read_multipart_part(response)[1]


def test_stream_multipart_delivery(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "STREAM_IDLE_DEADLINE", 0.5)
  stream = make_stream()
  frame = b"\xff\xd8stream-frame\xff\xd9"
  stream.publish_encoded_frame(frame)

  conn, response = get(stream, "/stream")
  try:
    assert response.status == 200
    assert response.getheader("Content-Type") == "multipart/x-mixed-replace; boundary=frame"
    assert _read_multipart_frame(response) == frame
  finally:
    conn.close()
  deadline = time.monotonic() + 2.0
  while stream._active_streams and time.monotonic() < deadline:
    time.sleep(0.02)
  assert stream._active_streams == 0


def test_stream_parts_carry_sequence_and_capture_time(make_stream, monkeypatch):
  # The viewer paces playback by capture time, so every part carries it.
  monkeypatch.setattr(ui_stream, "STREAM_IDLE_DEADLINE", 0.5)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8one\xff\xd9", captured_at=time.monotonic())
  conn, response = get(stream, "/stream")
  try:
    headers, _ = _read_multipart_part(response)
    first_capture = float(headers["x-capture-ms"])
    assert int(headers["x-frame-seq"]) == stream.current_sequence()
    assert first_capture == pytest.approx(stream._latest_at * 1000, abs=0.1)
    stream.publish_encoded_frame(b"\xff\xd8two\xff\xd9", captured_at=time.monotonic() + 0.05)
    headers, body = _read_multipart_part(response)
    assert body == b"\xff\xd8two\xff\xd9"
    assert int(headers["x-frame-seq"]) == stream.current_sequence()
    assert float(headers["x-capture-ms"]) - first_capture == pytest.approx(50, abs=5)
  finally:
    conn.close()


def test_frames_endpoint_is_the_stream_under_a_plain_type(make_stream, monkeypatch):
  # WebKit consumes multipart/x-mixed-replace itself, so the viewer's player
  # reads the same framing from /frames.
  monkeypatch.setattr(ui_stream, "STREAM_IDLE_DEADLINE", 0.5)
  stream = make_stream()
  frame = b"\xff\xd8frames\xff\xd9"
  stream.publish_encoded_frame(frame)
  conn, response = get(stream, "/frames")
  try:
    assert response.status == 200
    assert response.getheader("Content-Type") == "application/octet-stream"
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert _read_multipart_frame(response) == frame
  finally:
    conn.close()


def test_stream_socket_limits_unsent_bytes(monkeypatch):
  class Connection:
    def __init__(self):
      self.options = {}

    def setsockopt(self, level, option, value):
      self.options[(level, option)] = value

    def settimeout(self, timeout):
      self.timeout = timeout

  handler = object.__new__(ui_stream._StreamRequestHandler)
  handler.connection = Connection()
  monkeypatch.setattr(ui_stream, "_TCP_NOTSENT_LOWAT", 25)
  handler._tune_stream_socket()
  assert handler.connection.options[(socket.IPPROTO_TCP, 25)] == ui_stream.STREAM_NOTSENT_LOWAT
  assert handler.connection.options[(socket.IPPROTO_TCP, socket.TCP_NODELAY)] == 1
  assert handler.connection.timeout == ui_stream.STREAM_WRITE_TIMEOUT


def test_stream_rejects_stale_first_frame(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "SNAPSHOT_MAX_AGE", 1.0)
  monkeypatch.setattr(ui_stream, "STREAM_FIRST_FRAME_WAIT", 0.3)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8stale\xff\xd9", captured_at=time.monotonic() - 5.0)
  conn, response = get(stream, "/stream")
  try:
    assert response.status == 503
    response.read()
  finally:
    conn.close()
  assert stream._active_streams == 0


def test_stream_waits_past_stale_first_frame(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "SNAPSHOT_MAX_AGE", 1.0)
  monkeypatch.setattr(ui_stream, "STREAM_FIRST_FRAME_WAIT", 2.0)
  monkeypatch.setattr(ui_stream, "STREAM_IDLE_DEADLINE", 0.5)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8stale\xff\xd9", captured_at=time.monotonic() - 5.0)

  result: dict[str, object] = {}

  def request():
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    conn.request("GET", "/stream")
    response = conn.getresponse()
    result["status"] = response.status
    result["body"] = _read_multipart_frame(response) if response.status == 200 else response.read()
    conn.close()

  thread = threading.Thread(target=request)
  thread.start()
  time.sleep(0.3)
  stream.publish_encoded_frame(b"\xff\xd8fresh\xff\xd9")
  thread.join(timeout=5.0)

  assert result["status"] == 200
  assert result["body"] == b"\xff\xd8fresh\xff\xd9"


def test_stream_started_while_paused_gets_the_resumed_frame(make_stream, monkeypatch):
  # Live UI opened while the comma screen is asleep: the listener is bound but
  # paused. Connecting is the image demand that makes the screen policy resume
  # rendering with the panel off, so the request has to wait, not 503.
  monkeypatch.setattr(ui_stream, "STREAM_FIRST_FRAME_WAIT", 2.0)
  monkeypatch.setattr(ui_stream, "STREAM_IDLE_DEADLINE", 0.5)
  stream = make_stream()
  stream.pause()

  result: dict[str, object] = {}

  def request():
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    conn.request("GET", "/stream")
    response = conn.getresponse()
    result["status"] = response.status
    result["body"] = _read_multipart_frame(response) if response.status == 200 else response.read()
    conn.close()

  thread = threading.Thread(target=request)
  thread.start()
  # The demand the render loop needs to see before it resumes.
  deadline = time.monotonic() + 2.0
  while not stream.image_demand_active() and time.monotonic() < deadline:
    time.sleep(0.01)
  assert stream.image_demand_active() is True
  stream.resume()
  stream.publish_encoded_frame(b"\xff\xd8woken\xff\xd9")
  thread.join(timeout=5.0)

  assert result["status"] == 200
  assert result["body"] == b"\xff\xd8woken\xff\xd9"


def test_stream_limit_enforced(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "STREAM_FIRST_FRAME_WAIT", 0.5)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8frame\xff\xd9")

  held: list[tuple[http.client.HTTPConnection, object]] = []

  def hold():
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    conn.request("GET", "/stream")
    response = conn.getresponse()
    response.read(1)  # block until headers/first bytes
    # Retain both objects: a Connection: close response closes the socket on GC.
    held.append((conn, response))

  threads = [threading.Thread(target=hold) for _ in range(ui_stream.MAX_STREAMS)]
  for thread in threads:
    thread.start()

  deadline = time.monotonic() + 5.0
  while stream._active_streams < ui_stream.MAX_STREAMS and time.monotonic() < deadline:
    time.sleep(0.02)
  assert stream._active_streams == ui_stream.MAX_STREAMS

  conn, response = get(stream, "/stream")
  try:
    assert response.status == 503
    assert response.getheader("Retry-After") == "1"
    response.read()
  finally:
    conn.close()

  for thread in threads:
    thread.join(timeout=5.0)
  for conn, _response in held:
    conn.close()


def test_stream_waits_through_pause_for_the_resumed_frame(make_stream):
  # A viewer connecting while the screen is asleep must be able to wait: holding
  # a stream slot is the demand that makes the screen policy resume rendering.
  # Refusing immediately would deadlock the two against each other.
  stream = make_stream()
  stream.pause()

  frames: list[object] = []

  def wait():
    frames.append(stream.wait_for_frame(stream.current_sequence(), 3.0))

  thread = threading.Thread(target=wait)
  thread.start()
  time.sleep(0.2)
  assert not frames  # still waiting, not refused
  stream.resume()
  stream.publish_encoded_frame(b"\xff\xd8woken\xff\xd9")
  thread.join(timeout=5.0)

  assert frames and frames[0] is not None
  assert frames[0].jpeg == b"\xff\xd8woken\xff\xd9"


def test_wait_for_frame_still_refuses_a_stopping_stream(make_stream):
  stream = make_stream()
  stream.stop()
  assert stream.wait_for_frame(-1, 0.5) is None


def test_pause_closes_and_invalidates(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "STREAM_IDLE_DEADLINE", 3.0)
  stream = make_stream()
  stream.publish_encoded_frame(b"\xff\xd8live\xff\xd9")
  assert stream.latest_frame(10.0) is not None

  stream.pause()
  assert stream.latest_frame(10.0) is None
  assert stream.status()["state"] == "paused"
  stream.resume()
  assert stream.status()["state"] == "starting"


# -------------------------------------------------------------- ownership


def _demand_snapshot(stream: UiStream) -> None:
  stream.extend_telemetry_interest()
  with stream._lock:
    stream._snapshot_deadline = time.monotonic() + 10.0


def _reader(payload: bytes):
  def read(buffer: bytearray) -> bool:
    buffer[:len(payload)] = payload
    return True
  return read


def test_capture_skipped_without_demand(make_stream):
  stream = make_stream()
  calls = []

  def read(buffer):
    calls.append(1)
    return True

  assert stream.maybe_capture(time.monotonic(), 8, 8, read) is False
  assert calls == []


def test_capture_requires_free_slot(make_stream):
  stream = make_stream()
  _demand_snapshot(stream)
  with stream._lock:
    stream._slot.state = ui_stream._SlotState.ENCODING

  read_calls = []
  assert stream.maybe_capture(time.monotonic(), 4, 4, _reader(b"\x00" * 64)) is False
  assert read_calls == []
  assert stream.status()["counters"]["droppedBusy"] == 1


def test_capture_read_failure_releases_slot(make_stream):
  stream = make_stream()
  _demand_snapshot(stream)

  def read(buffer):
    raise RuntimeError("gl failed")

  assert stream.maybe_capture(time.monotonic(), 4, 4, read) is False
  assert stream.status()["counters"]["captureErrors"] == 1
  assert stream._slot.state == ui_stream._SlotState.FREE


def test_capture_pacing(make_stream):
  stream = make_stream(fps=5)
  _demand_snapshot(stream)
  now = time.monotonic()
  assert stream.maybe_capture(now, 4, 4, _reader(b"\x00" * 64)) is True
  # Wait for the worker to release the slot so pacing is the only blocker.
  deadline = time.monotonic() + 2.0
  while stream._slot.state != ui_stream._SlotState.FREE and time.monotonic() < deadline:
    time.sleep(0.01)
  assert stream.maybe_capture(now + 0.01, 4, 4, _reader(b"\x00" * 64)) is False
  assert stream.status()["counters"]["skippedPacing"] == 1


def _wait_slot_free(stream: UiStream) -> None:
  deadline = time.monotonic() + 2.0
  while stream._slot.state != ui_stream._SlotState.FREE and time.monotonic() < deadline:
    time.sleep(0.005)


def test_capture_pacing_tolerates_render_jitter(make_stream):
  # A 20 fps stream on a 20 fps UI must take every frame even when a frame
  # lands a couple of ms early; strict pacing would halve the rate.
  stream = make_stream(fps=20)
  _demand_snapshot(stream)
  t0 = time.monotonic()
  taken = 0
  for i, jitter in enumerate((0.0, -0.003, 0.002, -0.004, 0.001, -0.002)):
    _wait_slot_free(stream)
    taken += stream.maybe_capture(t0 + i * 0.05 + jitter, 4, 4, _reader(b"\x00" * 64))
  assert taken == 6
  assert stream.status()["counters"]["skippedPacing"] == 0


def test_capture_pacing_does_not_drift_faster_than_target(make_stream):
  # A 60 fps UI streaming at 20 fps takes every third frame, not every other.
  stream = make_stream(fps=20)
  _demand_snapshot(stream)
  t0 = time.monotonic()
  taken = 0
  for i in range(60):
    _wait_slot_free(stream)
    taken += stream.maybe_capture(t0 + i / 60, 4, 4, _reader(b"\x00" * 64))
  assert taken == 20


def test_output_size_scales_evenly_and_never_upscales(make_stream):
  stream = make_stream(width=1280)
  assert stream.output_size(2160, 1080) == (1280, 640)
  assert stream.output_size(536, 240) == (536, 240)
  assert make_stream(width=0).output_size(2160, 1080) == (2160, 1080)


def test_top_down_capture_is_not_flipped(make_stream):
  pytest.importorskip("cv2")
  stream = make_stream(width=0, quality=95)
  _demand_snapshot(stream)
  width, height = 8, 8
  raw = bytearray(width * height * 4)
  for y in range(height):
    color = bytes((255, 0, 0, 255)) if y < height // 2 else bytes((0, 0, 255, 255))
    raw[y * width * 4:(y + 1) * width * 4] = color * width

  assert stream.maybe_capture(time.monotonic(), width, height, _reader(bytes(raw)),
                              bottom_up=False, source_size=(16, 16)) is True
  frame = stream.wait_for_frame(-1, 2.0)
  assert frame is not None
  status = stream.status()
  assert (status["sourceWidth"], status["sourceHeight"]) == (16, 16)

  import cv2
  decoded = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_COLOR)
  assert decoded[0, 0][2] > 200 and decoded[0, 0][0] < 50    # top stays red
  assert decoded[-1, 0][0] > 200 and decoded[-1, 0][2] < 50  # bottom stays blue


def test_capture_publishes_encoded_frame(make_stream):
  pytest.importorskip("cv2")
  stream = make_stream(width=4, quality=95)
  _demand_snapshot(stream)

  width, height = 8, 8
  # Top half red, bottom half blue in the readback buffer.
  raw = bytearray(width * height * 4)
  for y in range(height):
    color = bytes((255, 0, 0, 255)) if y < height // 2 else bytes((0, 0, 255, 255))
    for x in range(width):
      offset = (y * width + x) * 4
      raw[offset:offset + 4] = color

  assert stream.maybe_capture(time.monotonic(), width, height, _reader(bytes(raw))) is True
  frame = stream.wait_for_frame(-1, 2.0)
  assert frame is not None
  # Published dimensions are the encoded ones, not the capture size.
  assert (frame.width, frame.height) == (4, 4)
  status = stream.status()
  assert (status["sourceWidth"], status["sourceHeight"]) == (width, height)
  assert (status["outputWidth"], status["outputHeight"]) == (4, 4)

  import cv2
  decoded = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_COLOR)
  assert decoded.shape[:2] == (4, 4)  # 8x8 downscaled to width 4, aspect preserved
  # The readback is bottom-up, so after the single flip the buffer's blue bottom
  # half becomes the image top half (and vice versa).
  top = decoded[0, 0]     # BGR of buffer bottom (blue)
  bottom = decoded[-1, 0]
  assert top[0] > 200 and top[2] < 50
  assert bottom[2] > 200 and bottom[0] < 50


def test_capture_downscale_never_upscales(make_stream):
  pytest.importorskip("cv2")
  stream = make_stream(width=1000, quality=70)
  _demand_snapshot(stream)
  assert stream.maybe_capture(time.monotonic(), 8, 6, _reader(b"\x00" * (8 * 6 * 4))) is True
  frame = stream.wait_for_frame(-1, 2.0)
  assert frame is not None
  assert (frame.width, frame.height) == (8, 6)
  import cv2
  decoded = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_COLOR)
  assert decoded.shape[:2] == (6, 8)


def test_idle_release_frees_buffers_via_worker(make_stream, monkeypatch):
  # Drives the production path: the encoder worker evaluates the armed deadline.
  monkeypatch.setattr(ui_stream, "IDLE_RELEASE_GRACE", 0.0)
  stream = make_stream()
  _demand_snapshot(stream)
  assert stream.maybe_capture(time.monotonic(), 4, 4, _reader(b"\x00" * 64)) is True
  assert stream.wait_for_frame(-1, 2.0) is not None
  deadline = time.monotonic() + 2.0
  while stream._slot.state != ui_stream._SlotState.FREE and time.monotonic() < deadline:
    time.sleep(0.01)

  # Drop demand, then arm the grace period the way the render loop does.
  with stream._lock:
    stream._snapshot_deadline = 0.0
    stream._telemetry_deadline = 0.0
  assert stream.maybe_capture(time.monotonic(), 4, 4, _reader(b"\x00" * 64)) is False

  deadline = time.monotonic() + 2.0
  while stream._slot.buffer is not None and time.monotonic() < deadline:
    time.sleep(0.02)
  assert stream.latest_frame(10.0) is None
  assert stream._slot.buffer is None


def test_idle_release_runs_while_screen_off(make_stream, monkeypatch):
  # Screen-off skips maybe_capture entirely; the worker must still release.
  monkeypatch.setattr(ui_stream, "IDLE_RELEASE_GRACE", 0.0)
  stream = make_stream()
  _demand_snapshot(stream)
  assert stream.maybe_capture(time.monotonic(), 4, 4, _reader(b"\x00" * 64)) is True
  assert stream.wait_for_frame(-1, 2.0) is not None
  deadline = time.monotonic() + 2.0
  while stream._slot.state != ui_stream._SlotState.FREE and time.monotonic() < deadline:
    time.sleep(0.01)

  with stream._lock:
    stream._snapshot_deadline = 0.0
    stream._telemetry_deadline = 0.0
  stream.pause()

  deadline = time.monotonic() + 2.0
  while stream._slot.buffer is not None and time.monotonic() < deadline:
    time.sleep(0.02)
  assert stream._slot.buffer is None


# ----------------------------------------------------------------- shutdown


def test_shutdown_is_idempotent_and_rebindable(make_stream):
  stream = make_stream()
  port = stream.port
  stream.stop()
  stream.stop()

  replacement = UiStream(StreamConfig(bind="127.0.0.1", port=port))
  try:
    replacement.serve()
    conn, response = get(replacement, "/status")
    try:
      assert response.status == 200
      response.read()
    finally:
      conn.close()
  finally:
    replacement.stop()


def test_server_bind_failure_returns_none(monkeypatch):
  blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  blocker.bind(("127.0.0.1", 0))
  blocker.listen(1)
  port = blocker.getsockname()[1]
  try:
    assert UiStream.from_env({"STREAM": "1", "STREAM_BIND": "127.0.0.1", "STREAM_PORT": str(port)}) is None
  finally:
    blocker.close()


# --------------------------------------------------------------- idle self-stop


def test_self_stop_due_after_idle_period(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "IDLE_SELF_STOP", 0.2)
  stream = make_stream()
  # Fresh: the clock starts on the first poll, so nothing is due yet.
  assert stream.self_stop_due() is False
  time.sleep(0.3)
  assert stream.self_stop_due() is True


def test_self_stop_reset_by_image_demand(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "IDLE_SELF_STOP", 0.2)
  stream = make_stream()
  assert stream.self_stop_due() is False
  assert stream.begin_stream() is True
  time.sleep(0.3)
  # A connected viewer must never be reaped.
  assert stream.self_stop_due() is False
  stream.end_stream()
  assert stream.self_stop_due() is False  # restarts the clock
  time.sleep(0.3)
  assert stream.self_stop_due() is True


def test_self_stop_reset_by_telemetry_interest(make_stream, monkeypatch):
  monkeypatch.setattr(ui_stream, "IDLE_SELF_STOP", 0.2)
  stream = make_stream()
  assert stream.self_stop_due() is False
  stream.extend_telemetry_interest()
  time.sleep(0.3)
  # Telemetry-only viewers count as demand too.
  assert stream.self_stop_due() is False


def test_self_stop_not_due_before_serving():
  # Port 0 is an ephemeral bind, so build the config directly (parse_config
  # rejects it, as it should for real configuration).
  stream = UiStream(StreamConfig(bind="127.0.0.1", port=0))
  try:
    # Bound but not serving: teardown is not the render loop's business yet.
    assert stream.self_stop_due() is False
  finally:
    stream.stop()
  assert stream.self_stop_due() is False


def test_encoder_dependencies_not_imported_until_demand(make_stream):
  # Regression guard: importing cv2 at serve() time would charge every device
  # for a feature nobody is watching.
  sys.modules.pop("cv2", None)
  make_stream()
  time.sleep(0.6)  # at least one worker wake
  assert "cv2" not in sys.modules


@pytest.mark.parametrize("failed_thread", ["ui_stream_encode", "ui_stream_http"])
def test_partial_thread_start_shutdown_is_bounded(monkeypatch, failed_thread):
  stream = UiStream(StreamConfig(bind="127.0.0.1", port=0))
  port = stream.port
  original_start = threading.Thread.start

  def start(thread):
    if thread.name == failed_thread:
      raise RuntimeError("injected start failure")
    return original_start(thread)

  monkeypatch.setattr(threading.Thread, "start", start)
  with pytest.raises(RuntimeError, match="injected"):
    stream.serve()
  errors = []

  def stop():
    try:
      stream.stop()
    except Exception as exc:
      errors.append(exc)

  cleanup = threading.Thread(target=stop, daemon=True)
  cleanup.start()
  cleanup.join(1)
  assert not cleanup.is_alive(), "shutdown blocked after partial startup"
  assert not errors
  stream.stop()
  replacement = UiStream(StreamConfig(bind="127.0.0.1", port=port))
  replacement.stop()


def test_snapshot_resumes_from_pause_through_image_demand(make_stream):
  stream = make_stream()
  stream.pause()
  result = []
  waiter = threading.Thread(target=lambda: result.append(stream.acquire_snapshot_frame(1)))
  waiter.start()
  deadline = time.monotonic() + 0.5
  while not stream.image_demand_active() and time.monotonic() < deadline:
    time.sleep(0.005)
  assert stream.image_demand_active()
  # The screen policy sees this demand and resumes rendering without panel power.
  stream.resume()
  stream.publish_encoded_frame(b"snapshot")
  waiter.join(1)
  assert not waiter.is_alive()
  assert result[0].jpeg == b"snapshot"
  assert not stream.image_demand_active()


def test_capture_unavailable_reports_reason_without_holding_render(make_stream):
  stream = make_stream()
  stream.fail_capture("MICI requires a render texture")
  assert stream.begin_stream()
  assert not stream.image_demand_active()
  assert stream.wait_for_frame(0, 1) is None
  assert stream.acquire_snapshot_frame(1) is None
  conn, response = get(stream, "/status")
  status = json.loads(response.read())
  conn.close()
  assert status["state"] == "error"
  assert status["captureError"] == "MICI requires a render texture"
  stream.end_stream()
  stream.extend_telemetry_interest()
  stream.set_telemetry(b'{}')
  assert stream.telemetry_snapshot(2) == b'{}'


# ------------------------------------------------------------ remote control


def test_parse_config_control_kill_switch():
  assert ui_stream.parse_config({}).control is True
  assert ui_stream.parse_config({"STREAM_CONTROL": "0"}).control is False


def _post_input(stream: UiStream, body, headers: dict[str, str] | None = None, path: str = "/input"):
  conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
  data = body if isinstance(body, bytes) else json.dumps(body).encode()
  merged = {"Content-Type": "application/json", ui_stream.CONTROL_HEADER: "1"}
  merged.update(headers or {})
  try:
    conn.request("POST", path, body=data, headers={k: v for k, v in merged.items() if v is not None})
    response = conn.getresponse()
    return response.status, json.loads(response.read() or b"{}")
  finally:
    conn.close()


def _batch(gesture_id, *events):
  """events: (type, x, y)"""
  return {"gesture": gesture_id, "events": [{"type": kind, "x": x, "y": y} for kind, x, y in events]}


def _tap(x=0.5, y=0.5, gesture_id="g1"):
  return _batch(gesture_id, ("down", x, y), ("up", x, y))


def _submit(stream, gesture_id, *events, now=None):
  body = _batch(gesture_id, *events)
  return stream.submit_control(body["gesture"], body["events"], now=now)


def test_control_refused_until_the_app_allows_it(make_stream):
  stream = make_stream()
  status, body = _post_input(stream, _tap())
  assert status == 403 and "not ready" in body["error"]
  assert stream.drain_control() == []

  stream.set_control_allowed(False, "the car is onroad")
  status, body = _post_input(stream, _tap())
  assert status == 403 and "onroad" in body["error"]


def test_control_kill_switch_refuses_input(make_stream):
  stream = make_stream(control=False)
  stream.set_control_allowed(True)
  status, body = _post_input(stream, _tap())
  assert status == 403 and "STREAM_CONTROL=0" in body["error"]
  assert stream.status()["control"]["available"] is False


def test_control_events_are_forwarded_live_in_order(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  assert _post_input(stream, _batch("g1", ("down", 0.25, 0.75)))[0] == 200
  assert stream.drain_control() == [ui_stream.ControlEvent("down", 0.25, 0.75)]
  assert _post_input(stream, _batch("g1", ("move", 0.5, 0.75)))[0] == 200
  assert stream.drain_control() == [ui_stream.ControlEvent("move", 0.5, 0.75)]
  status, body = _post_input(stream, _batch("g1", ("up", 0.5, 0.75)))
  assert status == 200 and body == {"ok": True, "error": ""}
  assert stream.drain_control() == [ui_stream.ControlEvent("up", 0.5, 0.75)]
  assert stream.status()["control"]["active"] is False


@pytest.mark.parametrize("headers, expected", [
  ({ui_stream.CONTROL_HEADER: None}, 403),                # a plain cross-site form/fetch cannot add it
  ({"Content-Type": "text/plain"}, 415),                  # the no-preflight content type
  ({"Origin": "http://evil.example"}, 403),               # cross-origin page
  ({"Host": "evil.example"}, 403),                        # DNS rebinding
])
def test_control_rejects_requests_a_hostile_page_could_send(make_stream, headers, expected):
  stream = make_stream()
  stream.set_control_allowed(True)
  status, _ = _post_input(stream, _tap(), headers=headers)
  assert status == expected
  assert stream.drain_control() == []


def test_control_accepts_same_origin_viewer(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  status, _ = _post_input(stream, _tap(), headers={"Origin": f"http://127.0.0.1:{stream.port}"})
  assert status == 200


def test_control_preflight_and_get_are_refused(make_stream):
  stream = make_stream()
  for method in ("OPTIONS", "GET"):
    conn = http.client.HTTPConnection("127.0.0.1", stream.port, timeout=5.0)
    try:
      conn.request(method, "/input")
      response = conn.getresponse()
      assert response.status == 405
      response.read()
    finally:
      conn.close()


@pytest.mark.parametrize("body", [
  b"not json",
  {"events": [{"type": "down", "x": 0.5, "y": 0.5}]},                        # no gesture id
  {"gesture": "", "events": [{"type": "down", "x": 0.5, "y": 0.5}]},
  {"gesture": "g1", "events": []},
  {"gesture": "g1", "events": [{"type": "tap", "x": 0.5, "y": 0.5}]},
  {"gesture": "g1", "events": [{"type": "down", "x": "0.5", "y": 0.5}]},
  {"gesture": "g1", "events": [{"type": "down", "x": True, "y": 0.5}]},
  {"gesture": "g1", "events": [{"type": "move", "x": 0.5, "y": 0.5}]},       # move before down
  {"gesture": "g1", "events": [{"type": "down", "x": 0.5, "y": 0.5}] * 2},   # second down
  {"gesture": "g1", "events": [{"type": "down", "x": 0.5, "y": 0.5}, {"type": "up", "x": 0.5, "y": 0.5},
                               {"type": "move", "x": 0.5, "y": 0.5}]},        # event after up
  {"gesture": "g1", "events": [{"type": "down", "x": 0.5, "y": 0.5}] * (ui_stream.CONTROL_MAX_EVENTS + 1)},
])
def test_control_rejects_malformed_batches_atomically(make_stream, body):
  stream = make_stream()
  stream.set_control_allowed(True)
  status, _ = _post_input(stream, body)
  assert status in (400, 413)
  assert stream.drain_control() == []
  assert stream.status()["control"]["active"] is False


def test_control_clamps_coordinates(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  assert _submit(stream, "g1", ("down", -3, 9))[0] == 200
  assert stream.drain_control() == [ui_stream.ControlEvent("down", 0.0, 1.0)]


def test_control_one_viewer_owns_the_pointer(make_stream):
  # Viewer B can neither press nor move/release while A's gesture is held.
  stream = make_stream()
  stream.set_control_allowed(True)
  assert _submit(stream, "a", ("down", 0.1, 0.1))[0] == 200
  assert _submit(stream, "b", ("down", 0.9, 0.9)) == (409, "another viewer is using remote control")
  assert _submit(stream, "b", ("move", 0.9, 0.9))[0] == 409
  assert _submit(stream, "b", ("up", 0.9, 0.9))[0] == 409
  assert [e.kind for e in stream.drain_control()] == ["down"]
  assert _submit(stream, "a", ("up", 0.2, 0.2))[0] == 200
  assert _submit(stream, "b", ("down", 0.9, 0.9))[0] == 200  # free again


def test_control_finished_gesture_cannot_be_resumed(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  _submit(stream, "a", ("down", 0.1, 0.1), ("up", 0.1, 0.1))
  assert _submit(stream, "a", ("down", 0.1, 0.1))[0] == 409


def test_control_coalesces_moves_between_frames(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  _submit(stream, "g1", ("down", 0.1, 0.1))
  for i in range(10):
    _submit(stream, "g1", ("move", i / 10, 0.5))
  events = stream.drain_control()
  assert [e.kind for e in events] == ["down", "move"]
  assert events[-1].x == pytest.approx(0.9)


def test_control_silent_gesture_is_cancelled_not_released(make_stream):
  # A release would click whatever is under the finger; a vanished viewer
  # must only ever produce a cancel -- and before any 0.5 s hold action.
  assert ui_stream.CONTROL_SILENCE < 0.5
  stream = make_stream()
  stream.set_control_allowed(True)
  _submit(stream, "g1", ("down", 0.3, 0.4), now=100.0)
  assert [e.kind for e in stream.drain_control(now=100.0)] == ["down"]
  assert stream.drain_control(now=100.0 + ui_stream.CONTROL_SILENCE - 0.05) == []
  assert [e.kind for e in stream.drain_control(now=100.0 + ui_stream.CONTROL_SILENCE)] == ["cancel"]
  status, error = _submit(stream, "g1", ("up", 0.3, 0.4), now=100.5)
  assert status == 409 and "stalled" in error


def test_control_keepalive_holds_a_long_press(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  _submit(stream, "g1", ("down", 0.3, 0.4), now=100.0)
  stream.drain_control(now=100.0)
  for t in (100.3, 100.6, 100.9, 101.2):
    _submit(stream, "g1", ("move", 0.3, 0.4), now=t)
    assert [e.kind for e in stream.drain_control(now=t)] == ["move"]


def test_control_revoked_mid_gesture_cancels(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  _submit(stream, "g1", ("down", 0.6, 0.6))
  stream.drain_control()
  stream.set_control_allowed(False, "the car is onroad")
  assert [e.kind for e in stream.drain_control()] == ["cancel"]
  assert stream.drain_control() == []
  stream.set_control_allowed(True)
  assert _submit(stream, "g1", ("move", 0.6, 0.6))[0] == 409  # not resurrected


def test_control_preempted_gesture_tells_its_viewer_why(make_stream):
  stream = make_stream()
  stream.set_control_allowed(True)
  _submit(stream, "g1", ("down", 0.5, 0.5))
  stream.drain_control()
  stream.preempt_control("someone touched the comma screen")
  assert _submit(stream, "g1", ("move", 0.5, 0.5)) == (409, "someone touched the comma screen")
  assert stream.drain_control() == []
  assert _submit(stream, "g2", ("down", 0.5, 0.5))[0] == 200


def test_status_reports_control(make_stream):
  stream = make_stream()
  control = stream.status()["control"]
  assert control["available"] is True and control["allowed"] is False
  stream.set_control_allowed(True)
  _submit(stream, "g1", ("down", 0.5, 0.5))
  control = stream.status()["control"]
  assert control["allowed"] is True and control["active"] is True


def test_viewer_control_is_opt_in_and_preflighted():
  html = ui_stream.viewer_html().decode()
  assert 'id="control-toggle"' in html
  assert ui_stream.CONTROL_HEADER in html
  assert '"Content-Type": "application/json"' in html
  assert "var controlOn = false;" in html
