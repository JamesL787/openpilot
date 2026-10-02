import json
import sys
import time
from pathlib import Path

import pytest

from openpilot.starpilot.system.starpilot_auto import hw_encoder
from openpilot.starpilot.system.starpilot_auto.car_ui import TouchInput, logical_size
from openpilot.starpilot.system.starpilot_auto.frame_source import FrameRequest
from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import FakeHeadUnit, make_identity
from openpilot.starpilot.system.starpilot_auto.tests.test_starpilot_auto import connect, keyframe_au, pump_until
from openpilot.starpilot.system.starpilot_auto.touch import (ACTION_DRAG, ACTION_POINTER_UP, ACTION_PRESS, ACTION_RELEASE, InputConfig,
                                                           TouchEvent, TouchMapper, TouchReceiver, TouchSender, parse_input_config)
from openpilot.starpilot.system.starpilot_auto.view import ViewSource
from openpilot.starpilot.system.starpilot_auto.wire import field


@pytest.fixture
def sock_dir():
  """Unix socket paths must stay under ~100 bytes; pytest's tmp_path can be longer on macOS."""
  import shutil
  import tempfile
  directory = Path(tempfile.mkdtemp(prefix="starpilot_auto"))
  yield directory
  shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(scope="module")
def identity(tmp_path_factory):
  return make_identity(tmp_path_factory.mktemp("identity"))


def touch_message(action, *locations, index=0):
  body = b"".join(field(1, field(1, x) + field(2, y) + field(3, pid)) for pid, x, y in locations)
  return field(1, 1) + field(3, body + field(2, index) + field(3, action))


# --------------------------------------------------------------------- touch

def test_input_config_packed_keycodes_and_touchscreen():
  packed = bytes([0x0a, 0x03, 0x04, 0x13, 0x54])  # field 1, packed [4, 19, 84]
  config = parse_input_config(packed + field(2, field(1, 1920) + field(2, 720)))
  assert config == InputConfig((4, 19, 84), 1920, 720)


def test_touch_mapping_respects_margins_and_scaling():
  mapper = TouchMapper(InputConfig((), 1920, 1080), 1280, 720, 0, 240)  # touch space larger than video
  assert mapper.decode(touch_message(ACTION_PRESS, (0, 960, 540))) == [TouchEvent("down", 0.5, 0.5)]
  assert mapper.decode(touch_message(ACTION_DRAG, (0, 1920, 540))) == [TouchEvent("move", 1.0, 0.5)]
  assert mapper.decode(touch_message(ACTION_RELEASE, (0, 480, 180))) == [TouchEvent("up", 0.25, 0.0)]
  assert mapper.decode(touch_message(ACTION_PRESS, (0, 960, 10))) == []  # a press in the black margin is ignored
  assert mapper.decode(touch_message(ACTION_DRAG, (0, 960, 540))) == []


def test_touch_follows_first_pointer_only_and_cancels_on_reset():
  mapper = TouchMapper(InputConfig(), 1280, 720, 0, 0)
  assert mapper.decode(touch_message(ACTION_PRESS, (7, 640, 360)))[0].kind == "down"
  assert mapper.decode(touch_message(ACTION_POINTER_UP, (7, 640, 360), (8, 10, 10), index=1)) == [TouchEvent("move", 0.5, 0.5)]
  assert mapper.reset() == [TouchEvent("cancel", 0.0, 0.0)] and mapper.reset() == []
  assert mapper.decode(field(1, 1) + field(4, b"")) == []  # button events are not touches


def test_touch_socket_roundtrip(sock_dir):
  path = str(sock_dir / "touch.sock")
  receiver = TouchReceiver(path)
  sender = TouchSender(path)
  sender.send([TouchEvent("down", 0.1, 0.2), TouchEvent("up", 0.1, 0.2)])
  time.sleep(0.05)
  assert receiver.drain() == [TouchEvent("down", 0.1, 0.2), TouchEvent("up", 0.1, 0.2)]
  sender.close()
  receiver.close()
  orphan = TouchSender(path)
  orphan.send([TouchEvent("down", 0.5, 0.5)])  # nobody listening: dropped, never raises
  orphan.close()


# ------------------------------------------------------------------- car ui

def make_touch_input():
  from collections import namedtuple
  pos = namedtuple("Pos", "x y")
  event = namedtuple("Event", "pos slot left_pressed left_released left_down t cancelled")
  return TouchInput(event, pos, 2880, 1080)


def test_car_touch_is_offroad_only():
  touch = make_touch_input()
  events = touch.events([TouchEvent("down", 0.5, 0.5)], allowed=True, now=1.0)
  assert events[0].left_pressed and events[0].pos == (1440.0, 540.0)
  events = touch.events([], allowed=False, now=1.1)  # the car started while a finger was down
  assert len(events) == 1 and events[0].cancelled and not events[0].left_down
  assert touch.events([TouchEvent("down", 0.5, 0.5), TouchEvent("up", 0.5, 0.5)], allowed=False, now=1.2) == []
  assert touch.refused == 1


def test_car_touch_click_sequence():
  touch = make_touch_input()
  events = touch.events([TouchEvent("down", 0.1, 0.1), TouchEvent("move", 0.2, 0.1), TouchEvent("up", 0.2, 0.1)], True, 2.0)
  assert [(e.left_pressed, e.left_released, e.left_down) for e in events] == [(True, False, True), (False, False, True),
                                                                               (False, True, False)]


def test_logical_size_fills_car_viewport():
  assert logical_size(FrameRequest(1280, 720, 0, 240, 33333)) == (1920, 720, 1280 / 1920, 480 / 720)
  # An 800x480 head unit draws the UI at 0.67x, not 0.44x as on a 1080-row canvas.
  assert logical_size(FrameRequest(800, 480, 0, 0, 33333)) == (1200, 720, 800 / 1200, 480 / 720)
  # Narrower screens keep the minimum width and grow taller rather than stretching sideways.
  width, height, scale_x, scale_y = logical_size(FrameRequest(800, 600, 0, 0, 33333))
  assert (width, height) == (1067, 800) and abs(scale_x - scale_y) < 1e-3
  width, height, scale_x, scale_y = logical_size(FrameRequest(1080, 1920, 0, 0, 33333))
  assert width == 1067 and abs(scale_x - scale_y) < 1e-3


# --------------------------------------------------------------- view source

def renderer_command(tmp_path, sock_dir, record):
  return [sys.executable, "-m", "openpilot.starpilot.system.starpilot_auto.tests.fake_renderer", "--frames", str(tmp_path / "car"),
          "--touch", str(sock_dir / "touch.sock"), "--record", str(record)]


def wait_frame(view, timeout=10.0):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    view.demand()
    frame = view.latest()
    if frame is not None:
      return frame
    time.sleep(0.01)
  raise AssertionError("no frame")


def test_view_source_car_renderer_frames_and_touches(tmp_path, sock_dir):
  record = tmp_path / "touches.jsonl"
  request = FrameRequest(64, 32, 0, 0, 20_000)
  view = ViewSource("car", request, lambda *a, **k: None, mirror_path=str(tmp_path / "mirror"), car_path=str(tmp_path / "car"),
                    touch_path=str(sock_dir / "touch.sock"), renderer_command=renderer_command(tmp_path, sock_dir, record))
  try:
    frame = wait_frame(view)
    assert frame.data[:1] == bytes([200]) and view.label == "car"
    view.send_touches([TouchEvent("down", 0.25, 0.75)])
    deadline = time.monotonic() + 5
    while not record.exists() and time.monotonic() < deadline:
      view.demand()
      time.sleep(0.02)
    assert json.loads(record.read_text().splitlines()[0]) == ["down", 0.25, 0.75]
  finally:
    view.close()
  assert view.process is None


def test_view_source_falls_back_to_mirror_when_renderer_dies(tmp_path, sock_dir):
  from openpilot.starpilot.system.starpilot_auto.frame_source import FrameProducer
  events = []
  request = FrameRequest(64, 32, 0, 0, 20_000)
  view = ViewSource("car", request, lambda name, **values: events.append(name), mirror_path=str(tmp_path / "mirror"),
                    car_path=str(tmp_path / "car"), touch_path=str(sock_dir / "touch.sock"),
                    renderer_command=[sys.executable, "-c", "import sys; sys.exit(4)"])
  try:
    deadline = time.monotonic() + 5
    while view.view == "car":
      assert time.monotonic() < deadline
      view.check()
      time.sleep(0.05)
    assert "renderer exited with 4" in view.label and "car_view_fallback" in events
    producer = FrameProducer(str(tmp_path / "mirror"))  # the comma UI keeps serving the mirror slot
    pending = producer.pending_request()
    producer.publish(pending, bytes([9]) * (64 * 32 * 4), time.monotonic_ns())
    assert view.latest().data[:1] == bytes([9])
  finally:
    view.close()


def test_view_source_car_timers_pause_while_car_shows_its_own_screen(tmp_path, sock_dir):
  from openpilot.starpilot.system.starpilot_auto.view import CAR_STALL_TIMEOUT, CAR_STARTUP_TIMEOUT
  request = FrameRequest(64, 32, 0, 0, 20_000)
  view = ViewSource("car", request, lambda *a, **k: None, mirror_path=str(tmp_path / "mirror"), car_path=str(tmp_path / "car"),
                    touch_path=str(sock_dir / "touch.sock"), renderer_command=[sys.executable, "-c", "import time; time.sleep(60)"])
  try:
    start = view.started_at
    view.check(start + 1, focused=False)
    view.check(start + CAR_STARTUP_TIMEOUT + 60, focused=False)  # car never granted focus yet: not a startup failure
    view.check(start + CAR_STARTUP_TIMEOUT + 62, focused=True)
    assert view.view == "car"
    view.frames, view.last_frame_at = 10, start + CAR_STARTUP_TIMEOUT + 62
    view.check(view.last_frame_at + 1, focused=False)  # driver switched to the car's own radio screen
    view.check(view.last_frame_at + CAR_STALL_TIMEOUT + 120, focused=False)
    view.check(view.last_frame_at + CAR_STALL_TIMEOUT + 121, focused=True)
    assert view.view == "car"
    view.check(view.last_frame_at + CAR_STALL_TIMEOUT + 1, focused=True)  # a real stall while projecting still falls back
    assert "frames stopped" in view.label
  finally:
    view.close()


# ------------------------------------------------------------ session touches

def test_session_delivers_car_touches(identity):
  hu = FakeHeadUnit(identity)
  session = connect(hu, identity)
  session.authenticate()
  session.start("StarPilot", "comma.ai")
  pump_until(session, lambda: session.focused)
  assert session.touch is not None
  hu.send_touch(ACTION_PRESS, 640, 360)
  hu.send_touch(ACTION_RELEASE, 640, 360)
  pump_until(session, lambda: len(session.touch_events) == 2)
  assert [e.kind for e in session.touch_events] == ["down", "up"] and session.touch_events[0].x == pytest.approx(0.5)
  hu.set_focus(False)
  hu.send_touch(ACTION_PRESS, 640, 360)  # touches while the car shows its own screen are not ours
  pump_until(session, lambda: not session.focused)
  session.send_frame(keyframe_au(1), 1, keyframe=True) if session.can_send() else None
  session.shutdown()
  session.peer.close()
  hu.thread.join(5)
  assert len(session.touch_events) == 2


# ------------------------------------------------------------------ encoders

def test_normalize_hardware_access_unit():
  raw = b"\x00\x00\x00\x01\x67\x42" + b"\x00\x00\x00\x01\x68\xce" + b"\x00\x00\x00\x01\x09\xf0" + b"\x00\x00\x00\x01\x65\x88"
  data = hw_encoder.normalize_access_unit(raw, keyframe=True)
  assert data.startswith(hw_encoder.AUD) and data.count(b"\x00\x00\x00\x01\x09") == 1
  with pytest.raises(RuntimeError):
    hw_encoder.normalize_access_unit(b"\x00\x00\x00\x01\x41\x00", keyframe=True)


def test_hardware_encoder_reads_only_the_encoded_bytes():
  import ctypes
  from types import SimpleNamespace

  raw = b"\x00\x00\x00\x01\x67\x42\x00\x00\x00\x01\x68\xce\x00\x00\x00\x01\x65\x88"
  encoder = hw_encoder.HardwareH264Encoder.__new__(hw_encoder.HardwareH264Encoder)
  encoder.handle = 1
  encoder.width = encoder.height = 2
  encoder.frame_index = 0
  encoder.error = ctypes.create_string_buffer(512)
  # Include stale trailing bytes; they must never enter the access unit.
  encoder.output = ctypes.create_string_buffer(raw + b"stale", 4096)
  encoder.lib = SimpleNamespace(starpilot_auto_encoder_encode=lambda *args: len(raw))
  data, keyframe = encoder.encode_rgba(bytes(16))
  assert data == hw_encoder.AUD + raw
  assert keyframe and encoder.frame_index == 1
  encoder.lib.starpilot_auto_encoder_encode = lambda *args: len(encoder.output) + 1
  with pytest.raises(RuntimeError, match="too large"):
    encoder.encode_rgba(bytes(16))


def test_create_encoder_falls_back_to_software(monkeypatch, tmp_path):
  monkeypatch.setattr(hw_encoder, "LIBRARY", tmp_path / "missing.so")
  events = []
  encoder, fps = hw_encoder.create_encoder(320, 240, preference="auto", bitrate_kbps=2000, margin_height=0, software_fps=15,
                                           log=lambda name, **values: events.append((name, values)))
  try:
    assert encoder.backend == "libx264" and fps == 15 and encoder.fps == 15
    assert events[0][0] == "encoder_fallback" and "not built" in events[0][1]["reason"]
  finally:
    encoder.close()
  with pytest.raises(RuntimeError):
    hw_encoder.create_encoder(320, 240, preference="hardware", bitrate_kbps=2000, margin_height=0, software_fps=15, log=lambda *a, **k: None)


def test_supervisor_car_view_end_to_end_with_touch(identity, tmp_path, sock_dir, monkeypatch):
  import socket
  import threading
  from openpilot.starpilot.system.starpilot_auto import bt_sockets, identity as identity_store, supervisor as supervisor_module
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import rfcomm_head_unit
  from openpilot.starpilot.system.starpilot_auto.tests.test_starpilot_auto import STARPILOT_AUTO_RECORD, ClosableSdpSocket, FakeBluez, FakeLease, sdp_response
  from openpilot.starpilot.system.starpilot_auto.touch import ACTION_PRESS, ACTION_RELEASE

  data = tmp_path / "starpilot_auto"
  (data / "identity").mkdir(parents=True)
  for src, name in ((identity["phone_cert"], "phone-cert.pem"), (identity["phone_key"], "phone-key.pem"), (identity["root"], "root-cert.pem")):
    (data / "identity" / name).write_bytes(Path(src).read_bytes())
  (data / "identity" / "phone-key.pem").chmod(0o600)
  monkeypatch.setattr(identity_store, "IDENTITY_DIR", data / "identity")
  monkeypatch.setattr(identity_store, "CONFIG_PATH", data / "config.json")
  monkeypatch.setattr(identity_store, "LOG_DIR", data / "logs")
  monkeypatch.setattr(supervisor_module, "SDP_SETTLE", (0.01,))
  monkeypatch.setattr(hw_encoder, "LIBRARY", tmp_path / "missing.so")
  hu = FakeHeadUnit(identity)

  def fake_rfcomm(address, channel, timeout=15.0):
    phone, car = socket.socketpair()

    def car_side():
      with car:
        rfcomm_head_unit(car, ("127.0.0.1", hu.port), pings=False)
        time.sleep(1.0)
    threading.Thread(target=car_side, daemon=True).start()
    return phone

  monkeypatch.setattr(bt_sockets, "connect_l2cap", lambda *a, **k: ClosableSdpSocket([sdp_response(STARPILOT_AUTO_RECORD)]))
  monkeypatch.setattr(bt_sockets, "connect_rfcomm", fake_rfcomm)
  record = tmp_path / "touches.jsonl"
  client = type("C", (), {"status": lambda s: type("St", (), {"selected_audio": ""})()})()
  sup = supervisor_module.Supervisor(bluez_factory=FakeBluez, lease_factory=lambda *a: FakeLease(), bluetooth_client=client,
                                     frame_path=str(tmp_path / "mirror"), car_frame_path=str(tmp_path / "car"),
                                     touch_path=str(sock_dir / "touch.sock"),
                                     renderer_command=renderer_command(tmp_path, sock_dir, record))
  sup.select_receiver("AA:BB:CC:DD:EE:01", "Civic")
  try:
    sup.start()
    deadline = time.monotonic() + 20
    while len(hu.frames) < 3:
      assert time.monotonic() < deadline, sup.status()
      time.sleep(0.05)
    status = sup.status()
    assert status["view"] == "car" and status["encoder"] == "libx264" and status["target_fps"] == 15
    hu.send_touch(ACTION_PRESS, 640, 360)
    hu.send_touch(ACTION_RELEASE, 640, 360)
    while not record.exists() or len(record.read_text().splitlines()) < 2:
      assert time.monotonic() < deadline, sup.status()
      time.sleep(0.05)
    assert [json.loads(line)[0] for line in record.read_text().splitlines()] == ["down", "up"]
  finally:
    sup.stop()
    hu.close()
  hu.thread.join(5)
  assert hu.error is None, hu.error
  assert sup.status()["state"] == "idle"


# -------------------------------------------------------------------- config

def test_config_migrates_legacy_defaults(tmp_path):
  from openpilot.starpilot.system.starpilot_auto import identity as identity_store
  path = tmp_path / "config.json"
  path.write_text(json.dumps({"receiver_address": "AA:BB", "fps": 12, "bitrate_kbps": 4000, "view": "mirror"}))
  config = identity_store.load_config(path)
  assert config["fps"] == 0 and config["bitrate_kbps"] == 6000
  assert config["receiver_address"] == "AA:BB" and config["view"] == "mirror"
  identity_store.save_config(config, path)
  assert json.loads(path.read_text())["config_version"] == identity_store.CONFIG_VERSION
  path.write_text(json.dumps({"config_version": 2, "fps": 12, "bitrate_kbps": 4000}))
  assert identity_store.load_config(path)["fps"] == 12  # a cap chosen after versioning is kept
  path.write_text(json.dumps({"fps": 20, "bitrate_kbps": 8000}))
  assert identity_store.load_config(path)["fps"] == 20 and identity_store.load_config(path)["bitrate_kbps"] == 8000


class _EncoderProbe:
  supports_nv12 = False
  backend = "probe"

  def __init__(self):
    self.closed = 0

  def close(self):
    self.closed += 1


def _project_with_failing_view(identity, tmp_path, monkeypatch, view_factory, stream=None):
  from types import SimpleNamespace
  from openpilot.starpilot.system.starpilot_auto import hw_encoder, supervisor as supervisor_module
  from openpilot.starpilot.system.starpilot_auto.tests.test_starpilot_auto import make_supervisor

  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, lambda *a, **k: None)
  mode = SimpleNamespace(width=320, height=240, margin_width=0, margin_height=0, fps=30, as_dict=lambda: {})
  session = SimpleNamespace(authenticate=lambda: None, start=lambda *a: mode, head_unit_subject="", shutdown=lambda: None)
  encoder = _EncoderProbe()
  monkeypatch.setattr(supervisor_module, "ProjectionSession", lambda *a, **k: session)
  monkeypatch.setattr(hw_encoder, "create_encoder", lambda *a, **k: (encoder, 30))
  monkeypatch.setattr(supervisor_module, "ViewSource", view_factory)
  if stream is not None:
    monkeypatch.setattr(sup, "_stream", stream)
  with pytest.raises((RuntimeError, OSError)):
    sup._project(None, None, SimpleNamespace(cert="c", key="k", root=None), connect=lambda: object())
  return encoder


def test_encoder_is_released_when_the_view_fails_to_start(identity, tmp_path, monkeypatch):
  def broken_view(*a, **k):
    raise RuntimeError("boom")
  assert _project_with_failing_view(identity, tmp_path, monkeypatch, broken_view).closed == 1


def test_encoder_is_released_when_closing_the_view_fails(identity, tmp_path, monkeypatch):
  from types import SimpleNamespace

  def closing_fails():
    raise OSError("close failed")
  view = lambda *a, **k: SimpleNamespace(label="car", close=closing_fails)  # noqa: E731

  def stream(*a, **k):
    raise RuntimeError("boom")
  assert _project_with_failing_view(identity, tmp_path, monkeypatch, view, stream).closed == 1


def test_stop_leaves_a_replacement_session_alone(identity, tmp_path, monkeypatch):
  import threading
  from openpilot.starpilot.system.starpilot_auto.tests.test_starpilot_auto import make_supervisor

  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, lambda *a, **k: None)
  release = threading.Event()
  replacement = threading.Thread(target=release.wait, args=(10,), daemon=True)
  replacement.start()
  closed = []
  new_socket = type("S", (), {"shutdown": lambda s, *a: closed.append("shutdown"), "close": lambda s: closed.append("close")})()

  def old_session():
    while not sup._stop.is_set():
      time.sleep(0.005)
    with sup._lock:  # the old session exits and a concurrent start() launches its replacement
      sup._thread = replacement
      sup._sockets.add(new_socket)
      sup._set(state="streaming", running=True)

  old = threading.Thread(target=old_session, daemon=True)
  sup._thread = old
  old.start()
  sup.stop(timeout=0.4, graceful=0.2)
  assert sup._thread is replacement and replacement.is_alive()
  assert closed == [] and new_socket in sup._sockets
  assert sup._status["running"] is True and sup._status["state"] == "streaming"
  release.set()
