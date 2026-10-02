import json
from starpilot.system.starpilot_auto.session import START_CODE
import socket
import ssl
import struct
import threading
import time
from pathlib import Path

import pytest

from openpilot.starpilot.system.starpilot_auto import bootstrap as bs
from openpilot.starpilot.system.starpilot_auto import hfp, sdp
from openpilot.starpilot.system.starpilot_auto.frame_source import FrameConsumer, FrameProducer, FrameRequest, fit_content
from openpilot.starpilot.system.starpilot_auto.session import (AuthenticationRejected, ProjectionSession, VideoMode, choose_video_mode)
from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import FakeHeadUnit, make_identity, rfcomm_head_unit
from openpilot.starpilot.system.starpilot_auto.wire import field, one, parse_fields, signed


@pytest.fixture(scope="module")
def identity(tmp_path_factory):
  return make_identity(tmp_path_factory.mktemp("identity"))


# ---------------------------------------------------------------------- wire

def test_wire_roundtrip_and_negative_ints():
  data = field(1, 5) + field(2, "abc") + field(3, -1)
  fields = parse_fields(data)
  assert one(fields, 1) == 5 and one(fields, 2) == b"abc" and signed(one(fields, 3)) == -1


def test_wire_rejects_truncation():
  with pytest.raises(ValueError):
    parse_fields(field(2, "abcdef")[:-2])


# ----------------------------------------------------------------------- sdp

def sdp_response(attributes: bytes, continuation: bytes = b"") -> bytes:
  params = struct.pack(">H", len(attributes)) + attributes + bytes([len(continuation)]) + continuation
  return struct.pack(">BHH", sdp.PDU_SEARCH_ATTRIBUTE_RESPONSE, 0, len(params)) + params


PROTOCOLS = b"\x35\x20\x09\x00\x04\x35\x0c\x35\x03\x19\x01\x00\x35\x05\x19\x00\x03\x08\x08"  # L2CAP + RFCOMM ch 8
STARPILOT_AUTO_RECORD = PROTOCOLS + b"\x09\x00\x01\x35\x11\x1c" + sdp.STARPILOT_AUTO_WIRELESS_UUID.bytes


class FakeSdpSocket:
  def __init__(self, responses):
    self.responses = list(responses)
    self.requests = []

  def settimeout(self, _):
    pass

  def send(self, data):
    self.requests.append(data)

  def recv(self, _):
    return self.responses.pop(0)


class ClosableSdpSocket(FakeSdpSocket):
  def __enter__(self):
    return self

  def __exit__(self, *_):
    pass

  def shutdown(self, *_):
    pass

  def close(self):
    pass


def test_sdp_request_matches_phone_shape():
  request = sdp.build_request(b"")
  assert request[0] == sdp.PDU_SEARCH_ATTRIBUTE_REQUEST and request[1:3] == b"\x00\x00"
  assert sdp.STARPILOT_AUTO_WIRELESS_UUID.bytes in request and b"\x03\xf0" in request and request.endswith(b"\x00")


def test_sdp_follows_continuation_and_finds_channel():
  first, second = STARPILOT_AUTO_RECORD[:10], STARPILOT_AUTO_RECORD[10:]
  sock = FakeSdpSocket([sdp_response(first, b"\x01\x02"), sdp_response(second)])
  assert sdp.query_channel(sock) == 8
  assert sock.requests[1].endswith(b"\x02\x01\x02")


def test_sdp_missing_service_and_error_response():
  with pytest.raises(sdp.SdpError, match="does not advertise"):
    sdp.query_channel(FakeSdpSocket([sdp_response(b"\x35\x00")]))
  error = struct.pack(">BHHH", sdp.PDU_ERROR_RESPONSE, 0, 2, 3)
  with pytest.raises(sdp.SdpError, match="invalid request syntax"):
    sdp.query_channel(FakeSdpSocket([error]))


def test_sdp_channel_encodings():
  assert sdp.rfcomm_channel(b"\x19\x00\x03\x09\x00\x0c") == 12
  assert sdp.rfcomm_channel(b"\x19\x00\x03\x08\x00" + b"\x19\x00\x03\x08\x05") == 5
  assert sdp.rfcomm_channel(b"\x19\x01\x00") is None


# ----------------------------------------------------------------- bootstrap

def run_bootstrap(start_request_delay=5.0, join_seconds=0.3, join_ping_interval=bs.JOIN_PING_INTERVAL,
                  initial_kick_delay=bs.INITIAL_KICK_SECONDS, **hu_options):
  phone, car = socket.socketpair()
  joined = []
  result_holder = {}

  def car_side():
    try:
      result_holder["seen"] = rfcomm_head_unit(car, ("192.168.50.1", 5288), **hu_options)
    except BaseException as error:
      result_holder["error"] = error

  thread = threading.Thread(target=car_side, daemon=True)
  thread.start()
  events = []
  boot = bs.WirelessBootstrap(phone, lambda name, **values: events.append((name, values)), stage_timeout=5.0,
                              start_request_delay=start_request_delay, join_ping_interval=join_ping_interval, initial_kick_delay=initial_kick_delay)

  def join(credentials):
    time.sleep(join_seconds)  # the car pings while we join
    joined.append(credentials)

  result = boot.run(join)
  thread.join(5)
  phone.close()
  car.close()
  assert "error" not in result_holder, result_holder.get("error")
  return result, joined, result_holder["seen"], events


def test_bootstrap_standard_flow():
  result, joined, seen, events = run_bootstrap()
  assert (result.endpoint.ip, result.endpoint.port) == ("192.168.50.1", 5288)
  creds = joined[0]
  assert (creds.ssid, creds.key, creds.bssid, creds.security) == ("HondaAA", "secret-key", "AA:BB:CC:DD:EE:FF", 8)
  assert signed(one(seen["start_response"], 3)) == 0 and 1 not in seen["start_response"]
  assert signed(one(seen["connect_status"], 1)) == 0
  assert all("secret-key" not in repr(values) for _, values in events)


def test_bootstrap_pings_the_car_during_a_slow_join():
  _, joined, seen, _ = run_bootstrap(join_seconds=0.75, join_ping_interval=0.2)
  assert joined[0].ssid == "HondaAA" and seen.get("phone_pings", 0) >= 2
  _, _, seen, _ = run_bootstrap(join_seconds=0.3, join_ping_interval=0)
  assert "phone_pings" not in seen


def test_bootstrap_version_log_keeps_head_unit_but_not_vehicle_id():
  info = bs.describe_version_request(field(1, 1) + field(2, 3) + field(5, field(1, "Hyundai") + field(4, "VIN-SECRET")) +
                                     field(4, field(1, "192.168.1.1") + field(2, 5288) + field(4, 36)))
  assert info[5][0] == {1: ["Hyundai"], 4: ["redacted"]}
  assert info[4][0][4] == [36], "a channel number in the endpoint is kept"


def test_bootstrap_version_first_and_fragmented():
  result, joined, seen, _ = run_bootstrap(version_first=True, byte_by_byte=True)
  assert result.version == (1, 3) and result.head_unit.get("car_make") == "Honda"
  assert one(seen["version_response"], 1) == 1 and signed(one(seen["version_response"], 4)) == 0
  assert joined[0].ssid == "HondaAA"


def test_bootstrap_asks_car_to_start_projection():
  result, joined, seen, events = run_bootstrap(start_request_delay=0.2, version_first=True, wait_for_phone_start=True)
  assert seen["phone_start_request"] == b"" and joined[0].ssid == "HondaAA"
  assert ("bootstrap_tx", {"message": "WifiStartRequest", "bytes": 0}) in events


def test_bootstrap_takes_endpoint_from_start_response():
  # 2025 Honda (session 25): version exchange, phone asks, car answers with a StartResponse.
  result, joined, seen, events = run_bootstrap(start_request_delay=0.1, version_first=True, wait_for_phone_start=True,
                                               answer_start=True)
  assert (result.endpoint.ip, result.endpoint.port) == ("192.168.50.1", 5288) and joined[0].ssid == "HondaAA"
  assert seen["messages"].count(bs.WIFI_START_REQUEST) == 1
  assert not any(name == "bootstrap_ignored" for name, _ in events)


def test_bootstrap_waits_out_a_busy_start_response():
  # The car says "not ready" (status alone), then sends the endpoint on its own.
  result, joined, _, events = run_bootstrap(start_request_delay=0.1, version_first=True, wait_for_phone_start=True,
                                            answer_start=True, busy_replies=1, busy_follow_up=True)
  assert result.endpoint.port == 5288 and joined[0].ssid == "HondaAA"
  assert ("bootstrap_start_refused", {"status": -1, "endpoint": False}) in events


def test_bootstrap_asks_again_after_a_busy_start_response():
  result, joined, seen, _ = run_bootstrap(start_request_delay=0.1, version_first=True, wait_for_phone_start=True,
                                          answer_start=True, busy_replies=2)
  assert result.endpoint.port == 5288 and joined[0].ssid == "HondaAA"
  assert seen["messages"].count(bs.WIFI_START_REQUEST) == 3


def test_bootstrap_start_response_without_endpoint_is_not_an_endpoint(monkeypatch):
  now = [0.0]
  monkeypatch.setattr(bs.time, "monotonic", lambda: now[0])
  boot = bs.WirelessBootstrap(None, lambda *a, **k: None, stage_timeout=1, start_request_delay=0.3)
  sent = []
  monkeypatch.setattr(boot, "send", lambda message, payload=b"": sent.append(message))
  replies = [(bs.WIFI_START_RESPONSE, field(3, 0)), (bs.WIFI_START_RESPONSE, field(1, "10.0.0.1") + field(2, 5288) + field(3, -3))]

  def receive(timeout):
    now[0] += 0.2
    if replies:
      return replies.pop(0)
    raise bs.BootstrapTimeout("wifi_start", "head unit did not answer in time")

  monkeypatch.setattr(boot, "next_frame", receive)
  with pytest.raises(bs.BootstrapTimeout):
    boot.run(lambda _: pytest.fail("Unexpected join"))
  assert bs.WIFI_START_REQUEST in sent, "a refused start is asked again"


def test_bootstrap_detects_alternate_info_layout():
  _, joined, _, _ = run_bootstrap(oaa_layout=True)
  assert joined[0].key == "secret-key" and joined[0].bssid == "AA:BB:CC:DD:EE:FF"


def test_bootstrap_setup_info_without_start_request():
  result, joined, seen, _ = run_bootstrap(setup_info_only=True, pings=False)
  assert result.endpoint.port == 5288 and joined[0].key == "secret-key"
  assert bs.WIFI_INFO_REQUEST not in seen["messages"]


def test_bootstrap_join_failure_reports_status():
  phone, car = socket.socketpair()
  seen = {}

  def car_side():
    try:
      seen.update(rfcomm_head_unit(car, ("10.0.0.1", 5000), pings=False))
    except BaseException as error:
      seen["error"] = error

  thread = threading.Thread(target=car_side, daemon=True)
  thread.start()

  def join(_):
    raise RuntimeError("wrong key")

  with pytest.raises(bs.BootstrapError) as error:
    bs.WirelessBootstrap(phone, lambda *a, **k: None, stage_timeout=5.0).run(join)
  assert error.value.stage == "joining_wifi"
  thread.join(5)
  phone.close()
  car.close()
  assert signed(one(seen["connect_status"], 1)) == bs.STATUS_NETWORK_UNAVAILABLE


def test_bootstrap_timeout_names_stage():
  phone, car = socket.socketpair()
  with pytest.raises(bs.BootstrapError) as error:
    bs.WirelessBootstrap(phone, lambda *a, **k: None, stage_timeout=0.3).run(lambda _: None)
  assert error.value.stage == "wifi_start"
  car.close()
  phone.close()


def test_frame_reader_bounds():
  reader = bs.FrameReader()
  assert reader.feed(bs.encode_frame(1, b"ab")[:3]) == []
  assert reader.feed(bs.encode_frame(1, b"ab")[3:] + bs.encode_frame(8)) == [(1, b"ab"), (8, b"")]
  with pytest.raises(ValueError):
    reader.feed(struct.pack(">HH", 60000, 1))


# ----------------------------------------------------------------------- hfp

def test_hfp_service_level_connection():
  assert hfp.respond("AT+BRSF=767") == ["+BRSF: 995", "OK"]  # a phone's feature set, not "nothing"
  assert hfp.respond("AT+BAC=1,2") == ["OK"]
  assert hfp.respond("AT+BCC") == ["ERROR"]  # never start call audio we cannot carry
  assert hfp.respond("AT+BIA=1,1,1,1,1,1,1,0") == ["OK"]
  assert hfp.respond("AT+CIND=?")[0].startswith("+CIND: (\"call\"")
  assert hfp.respond("AT+CIND?") == ["+CIND: 0,0,1,5,0,5,0", "OK"]
  assert hfp.respond("AT+CMER=3,0,0,1") == ["OK"]
  assert hfp.respond("ATD5551234;") == ["ERROR"]
  assert hfp.respond("AT+UNKNOWN") == ["ERROR"]


def test_hfp_serve_over_socket():
  a, b = socket.socketpair()
  stop = threading.Event()
  thread = threading.Thread(target=hfp.serve, args=(a, stop, lambda *x, **y: None), daemon=True)
  thread.start()
  b.sendall(b"AT+BRSF=0\rAT+CIND=?\r")
  time.sleep(0.2)
  data = b.recv(4096)
  assert b"+BRSF: 995" in data and data.count(b"OK") == 2
  b.close()
  thread.join(2)
  stop.set()


# -------------------------------------------------------------- frame source

def test_fit_content_letterboxes_compact_ui():
  x, y, w, h = fit_content(536, 240, 1280, 720, 0, 240)
  assert (w, h) == (1072, 480) and x == 104 and y == 120
  assert fit_content(536, 240, 800, 480, 0, 0) == (0, 60, 800, 358)


def test_frame_handoff(tmp_path):
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  producer = FrameProducer(path)
  request = FrameRequest(64, 32, 0, 0, 100_000)
  consumer.configure(request)
  assert producer.pending_request() is None  # no demand yet
  consumer.demand(1.0)
  producer._next_open_check = 0
  pending = producer.pending_request()
  assert pending == request
  now_ns = time.monotonic_ns()
  assert producer.due(pending, now_ns)
  producer.publish(pending, bytes([7]) * (64 * 32 * 4), now_ns)
  assert not producer.due(pending, now_ns + 10_000_000)  # paced to 10 fps
  frame = consumer.latest()
  assert frame is not None and frame.data[:4] == b"\x07" * 4 and frame.captured_ns == now_ns
  assert consumer.latest() is None  # nothing newer
  consumer.release_demand()
  assert producer.pending_request() is None
  consumer.close()


def test_frame_consumer_rejects_torn_write(tmp_path):
  path = str(tmp_path / "frames")
  consumer = FrameConsumer(path)
  consumer.configure(FrameRequest(16, 16, 0, 0, 50_000))
  consumer.demand()
  producer = FrameProducer(path)
  request = producer.pending_request()
  producer.publish(request, bytes(16 * 16 * 4), time.monotonic_ns())
  struct.pack_into("<Q", consumer.mm, 8, 5)  # writer mid-update
  assert consumer.latest() is None
  consumer.close()


# ------------------------------------------------------------------- session

def test_choose_video_mode_prefers_720p():
  channels = [{"id": 3, "video_configs": [parse_fields(field(1, 1)), parse_fields(field(1, 2) + field(4, 240)),
                                          parse_fields(field(1, 3))]}]
  assert choose_video_mode(channels) == VideoMode(3, 1, 1280, 720, 30, 0, 240)
  with pytest.raises(ValueError):
    choose_video_mode([{"id": 3, "video_configs": [parse_fields(field(1, 2) + field(10, 7))]}])  # H.265 only


def keyframe_au(tag: int) -> bytes:
  return b"\x00\x00\x00\x01\x09\xf0" + b"\x00\x00\x00\x01\x67\x42" + b"\x00\x00\x00\x01\x68\xce" + b"\x00\x00\x00\x01\x65" + bytes([tag])


def delta_au(tag: int) -> bytes:
  return b"\x00\x00\x00\x01\x09\xf0" + b"\x00\x00\x00\x01\x41" + bytes([tag])


def connect(hu: FakeHeadUnit, identity, verify=True) -> ProjectionSession:
  sock = socket.create_connection(("127.0.0.1", hu.port), timeout=5)
  return ProjectionSession(sock, str(identity["phone_cert"]), str(identity["phone_key"]), None,
                           str(identity["root"]) if verify else None)


def pump_until(session, predicate, timeout=5.0):
  deadline = time.monotonic() + timeout
  while not predicate():
    assert time.monotonic() < deadline, "condition not reached"
    session.pump(0.05)


def test_session_end_to_end_with_focus_epochs(identity):
  hu = FakeHeadUnit(identity)
  session = connect(hu, identity)
  session.authenticate()
  assert "Honda" in session.head_unit_subject
  mode = session.start("StarPilot", "comma.ai")
  assert (mode.width, mode.height, mode.margin_height) == (1280, 720, 240)
  pump_until(session, lambda: session.focused)
  with pytest.raises(ValueError):
    session.send_frame(delta_au(1), 1, keyframe=False)  # a new epoch must start with a keyframe
  session.send_frame(keyframe_au(1), 1, keyframe=True)
  for i in range(2, 6):
    pump_until(session, session.can_send)
    session.send_frame(delta_au(i), i, keyframe=False)
  pump_until(session, lambda: session.acked == 5)

  hu.set_focus(False)  # driver switched to the car's own screen
  pump_until(session, lambda: not session.focused)
  hu.set_focus(True)
  pump_until(session, lambda: session.focused)
  assert session.needs_keyframe and session.session_id == 2
  session.send_frame(keyframe_au(9), 9, keyframe=True)
  pump_until(session, lambda: session.acked == 6)
  session.shutdown()
  session.peer.close()
  hu.thread.join(5)
  assert hu.error is None, hu.error
  assert hu.device_name == "StarPilot" and hu.start_indications == [1, 2]
  assert [sid for sid, _ in hu.frames] == [1, 1, 1, 1, 1, 2] and hu.shutdown_received.is_set()



def run_until_streaming(hu: FakeHeadUnit, identity, log=None) -> ProjectionSession:
  sock = socket.create_connection(("127.0.0.1", hu.port), timeout=5)
  session = ProjectionSession(sock, str(identity["phone_cert"]), str(identity["phone_key"]), log, str(identity["root"]))
  session.authenticate()
  session.start("StarPilot", "comma.ai")
  pump_until(session, lambda: session.focused)
  session.send_frame(keyframe_au(1), 1, keyframe=True)
  pump_until(session, lambda: session.acked == 1)
  return session


def finish(session: ProjectionSession, hu: FakeHeadUnit) -> None:
  session.shutdown()
  session.peer.close()
  hu.thread.join(5)
  assert hu.error is None, hu.error


def test_session_accepts_a_legacy_tls_only_head_unit(identity):
  hu = FakeHeadUnit(identity, ciphers="AES128-SHA:@SECLEVEL=0")  # e.g. Sony XAV-AX3200: TLS_RSA_WITH_AES_128_CBC_SHA only
  finish(run_until_streaming(hu, identity), hu)
  assert hu.cipher == "AES128-SHA"


def test_session_picks_the_strongest_shared_cipher_not_the_head_units_first(identity):
  # A head unit listing a legacy suite first must not talk the comma down to it.
  hu = FakeHeadUnit(identity, ciphers="AES128-SHA:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:@SECLEVEL=0")
  finish(run_until_streaming(hu, identity), hu)
  assert "GCM" in hu.cipher and hu.cipher != "AES128-SHA"


def test_session_answers_pings_during_the_handshake(identity):
  events = []
  hu = FakeHeadUnit(identity, ping_during_auth=True)
  finish(run_until_streaming(hu, identity, lambda name, **values: events.append(name)), hu)
  assert hu.ping_replies >= 2 and "handshake_ignored" not in events


def test_session_waits_for_a_slow_discovery_response(identity):
  hu = FakeHeadUnit(identity, discovery_delay=4.0)  # longer than the 3 s streaming receive deadline
  finish(run_until_streaming(hu, identity), hu)


def test_session_projects_to_the_main_display_not_the_cluster(identity):
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import discovery_response
  hu = FakeHeadUnit(identity, discovery=discovery_response(cluster_channel=5))
  session = run_until_streaming(hu, identity)
  assert session.mode.channel == 3 and 5 not in hu.opened
  finish(session, hu)



def test_session_subscribes_to_driving_status_before_asking_for_the_screen(identity):
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import discovery_response
  events = []
  hu = FakeHeadUnit(identity, discovery=discovery_response(sensor_channel=7), sensor_channel=7, focus_needs_driving_status=True)
  session = run_until_streaming(hu, identity, lambda name, **values: events.append((name, values)))
  assert session.sensor_channel == 7 and 7 in hu.opened
  assert hu.sensors_started == [13, 10], "driving status, then night mode, and nothing the phone does not use"
  opened = next(values for name, values in events if name == "sensors_opened")
  assert opened["started"] == {13: 0, 10: 0} and opened["offered"] == [1, 3, 7, 8, 10, 13, 21]
  pump_until(session, lambda: any(name == "sensor_event" for name, _ in events))
  finish(session, hu)


def test_session_sends_its_bluetooth_address_before_asking_for_the_screen(identity):
  from openpilot.starpilot.system.starpilot_auto.session import parse_bluetooth_service
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import CAR_BT_ADDRESS, discovery_response
  events = []
  hu = FakeHeadUnit(identity, discovery=discovery_response(sensor_channel=7, bluetooth_channel=8), sensor_channel=7,
                    bluetooth_channel=8, focus_needs_driving_status=True, focus_needs_bluetooth=True)
  sock = socket.create_connection(("127.0.0.1", hu.port), timeout=5)
  session = ProjectionSession(sock, str(identity["phone_cert"]), str(identity["phone_key"]),
                              lambda name, **values: events.append((name, values)), str(identity["root"]))
  session.authenticate()
  session.start("StarPilot", "comma.ai", "AA:BB:CC:DD:EE:FF")
  pump_until(session, lambda: session.focused)
  assert session.bluetooth_channel == 8 and 8 in hu.opened
  assert hu.pairing_requests == [("AA:BB:CC:DD:EE:FF", 2)], "the comma's address, with the car's own pairing method"
  opened = next(values for name, values in events if name == "bluetooth_opened")
  assert opened["car_address"] == CAR_BT_ADDRESS and opened["methods"] == [2] and opened["response"] is not None
  assert parse_bluetooth_service(field(1, "x") + field(2, 1) + field(2, b"\x03\x04"))["pairing_methods"] == [1, 3, 4]
  finish(session, hu)


def test_session_without_a_bluetooth_address_still_opens_the_channel(identity):
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import discovery_response
  hu = FakeHeadUnit(identity, discovery=discovery_response(bluetooth_channel=8), bluetooth_channel=8)
  session = run_until_streaming(hu, identity)
  assert session.bluetooth_channel == 8 and hu.pairing_requests == []
  finish(session, hu)


def test_session_without_a_sensor_service_still_projects(identity):
  hu = FakeHeadUnit(identity)
  session = run_until_streaming(hu, identity)
  assert session.sensor_channel is None and hu.sensors_started == []
  finish(session, hu)


def test_session_takes_touch_from_the_projected_display(identity):
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import discovery_response
  hu = FakeHeadUnit(identity, discovery=discovery_response(cluster_channel=5, cluster_input_channel=6))
  session = run_until_streaming(hu, identity)
  assert session.input_channel == 1 and 6 not in hu.opened, "the cluster's input is listed first but not the driver's screen"
  finish(session, hu)


def test_input_channel_matches_display_or_falls_back_to_the_only_one():
  session = ProjectionSession.__new__(ProjectionSession)
  session.channels = [{"id": 6, "input": True, "display_id": 1}, {"id": 3, "video_configs": []},
                      {"id": 1, "input": True}, {"id": 5, "video_configs": [], "display_id": 1}]
  assert session.input_channel_for(3)["id"] == 1 and session.input_channel_for(5)["id"] == 6
  session.channels = [{"id": 3, "video_configs": []}, {"id": 1, "input": True, "display_id": 2}]
  assert session.input_channel_for(3)["id"] == 1, "a single input service is used even without a matching id"
  session.channels = [{"id": 3, "video_configs": []}, {"id": 1, "input": True, "display_id": 2}, {"id": 2, "input": True, "display_id": 1}]
  assert session.input_channel_for(3)["id"] == 1, "no input names the projected display: a guess beats no touch"
  session.channels = [{"id": 3, "video_configs": []}, {"id": 5, "video_configs": [], "display_id": 2},
                      {"id": 1, "input": True, "display_id": 2}, {"id": 2, "input": True, "display_id": 1}]
  assert session.input_channel_for(3)["id"] == 2, "the guess skips an input that belongs to another screen's video"
  session.channels = [{"id": 3, "video_configs": []}]
  assert session.input_channel_for(3) is None

def test_session_takes_a_1080p_only_head_unit(identity):
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import discovery_response
  hu = FakeHeadUnit(identity, discovery=discovery_response(resolutions=((3, 0, 0),)), accepted_config=0)
  session = run_until_streaming(hu, identity)
  assert (session.mode.width, session.mode.height) == (1920, 1080)
  finish(session, hu)


def test_discovery_log_names_the_head_unit_without_its_vehicle_id(identity):
  from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import discovery_response
  records = []
  hu = FakeHeadUnit(identity, discovery=discovery_response(headunit_info=True))
  finish(run_until_streaming(hu, identity, lambda name, **values: records.append((name, values))), hu)
  discovered = next(values for name, values in records if name == "discovered")
  assert discovered["head_unit"][2] == ["Honda"] and discovered["head_unit"][17][0][2] == ["IONIQ 6"]
  assert "VIN-SECRET" not in json.dumps(records, default=str)


def test_no_supported_mode_error_lists_the_offer():
  channels = [{"id": 3, "video_configs": [parse_fields(field(1, 4) + field(10, 3)), parse_fields(field(1, 2) + field(10, 7))]},
              {"id": 5, "display_type": 1, "video_configs": [parse_fields(field(1, 2))]}]
  with pytest.raises(ValueError, match=r"2560x1440 H\.264, 1280x720 H\.265, 1280x720 H\.264 \(display 1\)"):
    choose_video_mode(channels)


def test_ignored_messages_are_rate_limited():
  events = []
  session = ProjectionSession.__new__(ProjectionSession)
  session._log = lambda name, **values: events.append(values["count"])
  session.ignored_counts = {}
  for _ in range(250):
    session.ignored("channel_ignored", 9, 0x8001, b"\x08\x01")
  assert events == [1, 2, 3, 4, 5, 100, 200]

def test_session_accepts_newer_head_unit_protocol(identity):
  hu = FakeHeadUnit(identity, version=(4, 1))  # 2025 Honda Civic head unit
  session = connect(hu, identity)
  session.authenticate()
  mode = session.start("StarPilot", "comma.ai")
  assert hu.version_reply == (6, 1, 0) and mode.width == 1280
  session.shutdown()
  session.peer.close()
  hu.thread.join(5)
  assert hu.error is None, hu.error


@pytest.mark.parametrize("ack_codec_config", [True, False, 0])
def test_session_sends_codec_config_before_each_epoch(identity, ack_codec_config):
  hu = FakeHeadUnit(identity, ack_codec_config=ack_codec_config)
  session = connect(hu, identity)
  session.authenticate()
  session.start("StarPilot", "comma.ai")
  pump_until(session, lambda: session.focused)
  session.send_frame(keyframe_au(1), 1, keyframe=True)
  for i in range(2, 5):
    pump_until(session, session.can_send)
    session.send_frame(delta_au(i), i, keyframe=False)
  pump_until(session, lambda: session.acked == 4)
  hu.set_focus(False)
  pump_until(session, lambda: not session.focused)
  hu.set_focus(True)
  pump_until(session, lambda: session.focused)
  session.send_frame(keyframe_au(9), 9, keyframe=True)
  pump_until(session, lambda: session.acked == 5)
  session.shutdown()
  session.peer.close()
  hu.thread.join(5)
  assert hu.error is None, hu.error
  sps_pps = b"\x00\x00\x00\x01\x67\x42\x00\x00\x00\x01\x68\xce"
  assert hu.codec_configs == [(1, sps_pps, 0), (2, sps_pps, 4)]  # one per epoch, before its keyframe
  for _, frame in hu.frames:  # like a phone: no AUD, no repeated SPS/PPS in the picture data
    assert b"\x09\xf0" not in frame[:6]
    assert all(frame[m.end()] & 31 not in (7, 8, 9) for m in START_CODE.finditer(frame))


def test_session_keeps_unsolicited_focus_grant(identity):
  hu = FakeHeadUnit(identity, unsolicited_focus=True)
  session = connect(hu, identity)
  session.authenticate()
  session.start("StarPilot", "comma.ai")
  pump_until(session, lambda: session.focused, timeout=2.0)
  session.send_frame(keyframe_au(1), 1, keyframe=True)
  pump_until(session, lambda: session.acked == 1)
  session.shutdown()
  session.peer.close()
  hu.thread.join(5)
  assert hu.error is None and hu.start_indications == [1]


def test_session_authentication_rejected(identity):
  hu = FakeHeadUnit(identity, reject_auth=True)
  session = connect(hu, identity)
  with pytest.raises(AuthenticationRejected):
    session.authenticate()
  session.peer.close()
  hu.close()


def test_session_refuses_untrusted_head_unit(identity, tmp_path):
  other = make_identity(tmp_path / "other")
  hu = FakeHeadUnit({**identity, "hu_cert": other["hu_cert"], "hu_key": other["hu_key"]}, require_client_cert=False)
  session = connect(hu, identity)
  with pytest.raises(ssl.SSLError):
    session.authenticate()
  session.peer.close()
  hu.close()


# ---------------------------------------------------------------- supervisor

class FakeLease:
  def __init__(self, *_):
    self.local_ip = ""
    self.acquired = []
    self.releases = []

  def acquire(self, credentials, cancelled=lambda: False, timeout=40.0):
    self.acquired.append(credentials.ssid)
    self.local_ip = "127.0.0.1"
    return self.local_ip

  def still_connected(self):
    return True

  def release(self, restore=True):
    self.releases.append(restore)


class FakeBluez:
  def __init__(self, log):
    self.acquired = 0
    self.released = 0
    self.class_restored = 0
    self.hfp_registrations = 0
    self.trusted = []
    self.adapter_ready = True
    self.connected = True
    self.paired_devices = [("AA:BB:CC:DD:EE:01", "Civic", True)]

  def acquire(self):
    self.acquired += 1

  def release(self):
    self.released += 1

  def restore_class(self):
    self.class_restored += 1

  def register_hfp(self):
    self.hfp_registrations += 1

  def set_trusted(self, address):
    self.trusted.append(address)

  def close(self):
    pass

  def device(self, address):
    return {"address": address, "paired": True, "connected": self.connected, "name": "Civic", "starpilot_auto": True}

  def devices(self):
    return [{**self.device(address), "name": name, "starpilot_auto": aa} for address, name, aa in self.paired_devices]

  def snapshot(self, address):
    return self.adapter_ready, self.device(address)

  def connect_device(self, address):
    pass


def test_supervisor_full_wireless_session(identity, tmp_path, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import bt_sockets, identity as identity_store, supervisor as supervisor_module

  data = tmp_path / "starpilot_auto"
  (data / "identity").mkdir(parents=True)
  for src, name in ((identity["phone_cert"], "phone-cert.pem"), (identity["phone_key"], "phone-key.pem"), (identity["root"], "root-cert.pem")):
    (data / "identity" / name).write_bytes(Path(src).read_bytes())
  (data / "identity" / "phone-key.pem").chmod(0o600)
  monkeypatch.setattr(identity_store, "IDENTITY_DIR", data / "identity")
  monkeypatch.setattr(identity_store, "CONFIG_PATH", data / "config.json")
  monkeypatch.setattr(identity_store, "LOG_DIR", data / "logs")
  monkeypatch.setattr(supervisor_module, "SDP_SETTLE", (0.01,))

  hu = FakeHeadUnit(identity)
  rfcomm_seen = {}

  def fake_l2cap(address, psm, timeout=10.0):
    return ClosableSdpSocket([sdp_response(STARPILOT_AUTO_RECORD)])

  def fake_rfcomm(address, channel, timeout=15.0):
    assert channel == 8
    phone, car = socket.socketpair()
    def car_side():
      with car:
        rfcomm_seen.update(rfcomm_head_unit(car, ("127.0.0.1", hu.port), pings=False))
        time.sleep(1.0)
    threading.Thread(target=car_side, daemon=True).start()
    return phone

  monkeypatch.setattr(bt_sockets, "connect_l2cap", fake_l2cap)
  monkeypatch.setattr(bt_sockets, "connect_rfcomm", fake_rfcomm)

  frame_path = str(tmp_path / "frames")
  sup = supervisor_module.Supervisor(bluez_factory=FakeBluez, lease_factory=FakeLease,
                                     bluetooth_client=type("C", (), {"status": lambda s: type("St", (), {"selected_audio": ""})()})(),
                                     frame_path=frame_path)
  sup.select_receiver("AA:BB:CC:DD:EE:01", "Civic")
  lease_holder = {}
  original_lease = sup._lease
  sup._lease = lambda: lease_holder.setdefault("lease", original_lease())

  stop_producer = threading.Event()

  def producer_loop():
    producer = FrameProducer(frame_path)
    while not stop_producer.is_set():
      producer._next_open_check = 0
      request = producer.pending_request()
      now_ns = time.monotonic_ns()
      if request is not None and producer.due(request, now_ns):
        producer.publish(request, bytes([now_ns % 251]) * (request.width * request.height * 4), now_ns)
      time.sleep(0.01)

  threading.Thread(target=producer_loop, daemon=True).start()
  try:
    sup.start()
    deadline = time.monotonic() + 20
    while len(hu.frames) < 5:
      status = sup.status()
      assert time.monotonic() < deadline, status
      time.sleep(0.05)
    status = sup.status()
    assert status["state"] == "streaming" and status["mode"]["width"] == 1280
    sup.stop()
  finally:
    stop_producer.set()
    hu.close()
  hu.thread.join(5)
  assert hu.error is None, hu.error
  assert hu.shutdown_received.is_set()
  lease = lease_holder["lease"]
  assert lease.acquired == ["HondaAA"] and lease.releases[-1] is True
  assert sup.status()["state"] == "idle" and sup.status()["error"] == ""
  assert signed(one(rfcomm_seen["connect_status"], 1)) == 0
  logs = list((data / "logs").glob("session-*.jsonl"))
  assert logs and "secret-key" not in logs[0].read_text()


def make_supervisor(identity, tmp_path, monkeypatch, rfcomm):
  from openpilot.starpilot.system.starpilot_auto import bt_sockets, identity as identity_store, supervisor as supervisor_module
  data = tmp_path / "starpilot_auto"
  (data / "identity").mkdir(parents=True)
  for src, name in ((identity["phone_cert"], "phone-cert.pem"), (identity["phone_key"], "phone-key.pem"), (identity["root"], "root-cert.pem")):
    (data / "identity" / name).write_bytes(Path(src).read_bytes())
  (data / "identity" / "phone-key.pem").chmod(0o600)
  monkeypatch.setattr(identity_store, "IDENTITY_DIR", data / "identity")
  monkeypatch.setattr(identity_store, "CONFIG_PATH", data / "config.json")
  monkeypatch.setattr(identity_store, "LOG_DIR", data / "logs")
  monkeypatch.setattr(supervisor_module, "SDP_SETTLE", (0.01,))
  monkeypatch.setattr(supervisor_module, "BACKOFF_SECONDS", (0.2,))
  monkeypatch.setattr(bt_sockets, "connect_l2cap", lambda *a, **k: ClosableSdpSocket([sdp_response(STARPILOT_AUTO_RECORD)] * 4))
  monkeypatch.setattr(bt_sockets, "connect_rfcomm", rfcomm)
  leases = []

  def lease_factory(*args):
    leases.append(FakeLease())
    return leases[-1]

  client = type("C", (), {"status": lambda s: type("St", (), {"selected_audio": ""})()})()
  sup = supervisor_module.Supervisor(bluez_factory=FakeBluez, lease_factory=lease_factory, bluetooth_client=client,
                                     frame_path=str(tmp_path / "frames"))
  sup.select_receiver("AA:BB:CC:DD:EE:01", "Civic")
  return sup, leases


def test_supervisor_retries_after_rejection(identity, tmp_path, monkeypatch):
  cars = []

  def rfcomm(address, channel, timeout=15.0):
    hu = FakeHeadUnit(identity, reject_auth=True)
    cars.append(hu)
    phone, car = socket.socketpair()
    def car_side():
      with car:
        rfcomm_head_unit(car, ("127.0.0.1", hu.port), pings=False)
        time.sleep(1.0)
    threading.Thread(target=car_side, daemon=True).start()
    return phone

  sup, leases = make_supervisor(identity, tmp_path, monkeypatch, rfcomm)
  sup.start()
  deadline = time.monotonic() + 15
  while len(cars) < 2:
    assert time.monotonic() < deadline, sup.status()
    time.sleep(0.05)
  assert "rejected" in sup.status()["error"]
  sup.stop()
  for hu in cars:
    hu.close()
  assert False in leases[0].releases and leases[0].releases[-1] is True  # retries keep the old Wi-Fi parked
  assert sup.status()["state"] == "idle"


def test_supervisor_stop_while_waiting_for_car(identity, tmp_path, monkeypatch):
  held = []

  def rfcomm(address, channel, timeout=15.0):
    phone, car = socket.socketpair()
    held.append(car)  # the car never answers
    return phone

  sup, leases = make_supervisor(identity, tmp_path, monkeypatch, rfcomm)
  sup.start()
  deadline = time.monotonic() + 5
  while sup.status()["state"] != "wifi_start":
    assert time.monotonic() < deadline, sup.status()
    time.sleep(0.02)
  started = time.monotonic()
  sup.stop()
  assert time.monotonic() - started < 5
  assert sup.status()["state"] == "idle" and leases[0].releases[-1] is True
  for car in held:
    car.close()


# ------------------------------------------------------------------- network

class FakeNetworkManager:
  def __init__(self, fail_with_bssid=False):
    self.fail_with_bssid = fail_with_bssid
    self.active_device_connection = "/active/home"
    self.states = {}
    self.added = []
    self.calls = []

  def call(self, path, interface, member, signature=None, body=(), timeout=10.0):
    from openpilot.starpilot.system.starpilot_auto import network
    self.calls.append(member)
    if member == "GetDevices":
      return [["/dev/wlan0"]]
    if member == "AddAndActivateConnection2":
      settings = body[0]
      self.added.append(settings)
      active = f"/active/aa{len(self.added)}"
      locked = "bssid" in settings["802-11-wireless"]
      self.states[active] = network.ACTIVE_STATE_DEACTIVATED if (locked and self.fail_with_bssid) else network.ACTIVE_STATE_ACTIVATED
      self.active_device_connection = active
      return [f"/settings/aa{len(self.added)}", active]
    if member == "GetSettings":
      return [{"connection": {"id": ("s", "home" if path == "/settings/home" else "starpilot-auto")}}]
    if member == "ListConnections":
      return [[]]
    return []

  def get(self, path, interface, name):
    values = {"WirelessEnabled": True, "DeviceType": 2, "Interface": "wlan0", "ActiveConnection": self.active_device_connection,
              "Connection": "/settings/home", "Ip4Config": "/ip4/1"}
    if name == "State":
      return self.states.get(path, 4)
    if name == "AddressData":
      return [{"address": ("s", "192.168.50.23")}]
    return values[name]


def make_lease(nm):
  from openpilot.starpilot.system.starpilot_auto.network import NetworkLease
  lease = NetworkLease(lambda *a, **k: None)
  router = type("R", (), {"close": lambda self: None})()

  def reopen(*args, **kwargs):  # the real lease reopens D-Bus lazily on its next call
    lease.router = router

  def call(*args, **kwargs):
    reopen()
    return nm.call(*args, **kwargs)

  def get(*args, **kwargs):
    reopen()
    return nm.get(*args, **kwargs)

  lease._call, lease._get = call, get
  lease._delete_stale_profiles = lambda: None
  return lease


def credentials():
  return bs.WifiCredentials(ssid="HondaAA", key="secret-key", bssid="AA:BB:CC:DD:EE:FF", security=8, ap_type=1)


def test_network_lease_settings_keep_internet_route():
  from openpilot.starpilot.system.starpilot_auto.network import connection_settings
  settings = connection_settings(credentials(), "wlan0")
  assert settings["ipv4"]["never-default"] == ("b", True) and settings["ipv4"]["ignore-auto-dns"] == ("b", True)
  assert settings["connection"]["autoconnect"] == ("b", False) and settings["802-11-wireless-security"]["psk"] == ("s", "secret-key")
  assert settings["802-11-wireless"]["bssid"] == ("ay", bytes.fromhex("AABBCCDDEEFF"))


@pytest.mark.parametrize("security,key_mgmt,pmf", [(8, "wpa-psk", None), (32, "sae", 3), (40, "wpa-psk", 2)])
def test_network_lease_security_modes(security, key_mgmt, pmf):
  from dataclasses import replace
  from openpilot.starpilot.system.starpilot_auto.network import connection_settings
  wireless = connection_settings(replace(credentials(), security=security), "wlan0")["802-11-wireless-security"]
  assert wireless["key-mgmt"] == ("s", key_mgmt) and wireless.get("pmf") == (None if pmf is None else ("i", pmf))


def test_network_lease_refuses_security_a_phone_cannot_join():
  from dataclasses import replace
  from openpilot.starpilot.system.starpilot_auto.network import NetworkError, connection_settings
  with pytest.raises(NetworkError, match="WEP"):
    connection_settings(replace(credentials(), security=2), "wlan0")


def test_network_lease_retries_without_bssid_and_restores_previous():
  nm = FakeNetworkManager(fail_with_bssid=True)
  lease = make_lease(nm)
  assert lease.acquire(credentials(), timeout=2.0) == "192.168.50.23"
  assert "bssid" in nm.added[0]["802-11-wireless"] and "bssid" not in nm.added[1]["802-11-wireless"]
  lease.release(restore=True)
  assert nm.calls[-1] == "ActivateConnection"  # home Wi-Fi comes back


def test_network_lease_does_not_undo_user_network_change():
  nm = FakeNetworkManager()
  lease = make_lease(nm)
  lease.acquire(credentials(), timeout=2.0)
  nm.active_device_connection = "/active/user-picked"  # user chose another network meanwhile
  lease.release(restore=True)
  assert "ActivateConnection" not in nm.calls


def test_network_lease_retry_keeps_previous_for_final_stop():
  nm = FakeNetworkManager()
  lease = make_lease(nm)
  lease.acquire(credentials(), timeout=2.0)
  lease.release(restore=False)
  assert "ActivateConnection" not in nm.calls and lease.previous_connection == "/settings/home"
  lease.acquire(credentials(), timeout=2.0)
  lease.release(restore=True)
  assert nm.calls.count("ActivateConnection") == 1


def test_bootstrap_slow_join_preserves_strict_diy_dongle_sequence():
  _, joined, seen, _ = run_bootstrap(join_seconds=0.75, join_ping_interval=0.1, pings=False, strict_legacy=True)
  assert joined[0].ssid == "HondaAA"
  assert seen["messages"] == [bs.WIFI_INFO_REQUEST, bs.WIFI_START_RESPONSE, bs.WIFI_CONNECT_STATUS]


def test_bootstrap_negotiating_peer_still_gets_join_pings():
  _, _, seen, _ = run_bootstrap(join_seconds=0.75, join_ping_interval=0.1, pings=False, version_first=True)
  assert seen.get("phone_pings", 0) >= 2


def test_bootstrap_silent_peer_receives_one_prompt():
  _, joined, seen, events = run_bootstrap(initial_kick_delay=0.05, wait_for_phone_start=True, pings=False)
  assert joined[0].ssid == "HondaAA"
  assert seen["messages"].count(bs.WIFI_START_REQUEST) == 1
  assert sum(name == "bootstrap_initial_kick" for name, _ in events) == 1


def test_bootstrap_version_prompt_does_not_get_an_extra_initial_prompt():
  _, _, seen, events = run_bootstrap(initial_kick_delay=0.05, start_request_delay=0.1,
                                   version_first=True, wait_for_phone_start=True)
  assert seen["messages"].count(bs.WIFI_START_REQUEST) == 1
  assert not any(name == "bootstrap_initial_kick" for name, _ in events)


@pytest.mark.parametrize("stage", ["wifi_start", "wifi_info"])
def test_bootstrap_stage_deadline_survives_continuous_pings(monkeypatch, stage):
  now = [0.0]
  monkeypatch.setattr(bs.time, "monotonic", lambda: now[0])
  boot = bs.WirelessBootstrap(None, lambda *a, **k: None, stage_timeout=1)
  sent = []
  monkeypatch.setattr(boot, "send", lambda message, payload=b"": sent.append(message))
  first = [True]

  def receive(timeout):
    now[0] += 0.2
    if first[0] and stage == "wifi_info":
      first[0] = False
      return bs.WIFI_START_REQUEST, field(1, "10.0.0.1") + field(2, 5288)
    return bs.WIFI_PING_REQUEST, b""

  monkeypatch.setattr(boot, "next_frame", receive)
  with pytest.raises(bs.BootstrapTimeout) as error:
    boot.run(lambda _: pytest.fail("Unexpected join"))
  assert error.value.stage == stage and now[0] < 1.5
  assert bs.WIFI_PING_RESPONSE in sent and bs.WIFI_START_REQUEST not in sent


def test_bootstrap_hint_cannot_hide_disconnect():
  phone, car = socket.socketpair()
  try:
    car.sendall(bs.encode_frame(bs.WIFI_SETUP_INFO, field(4, field(1, "10.0.0.1") + field(2, 5288))))
    car.close()
    with pytest.raises(bs.BootstrapError, match="closed"):
      bs.WirelessBootstrap(phone, lambda *a, **k: None).run(lambda _: pytest.fail("Unexpected join"))
  finally:
    phone.close()
    car.close()


def test_bootstrap_hint_grace_is_not_extended_by_pings(monkeypatch):
  now = [0.0]
  monkeypatch.setattr(bs.time, "monotonic", lambda: now[0])
  boot = bs.WirelessBootstrap(None, lambda *a, **k: None, stage_timeout=10)
  monkeypatch.setattr(boot, "send", lambda *a: None)
  payload = field(4, field(1, "10.0.0.1") + field(2, 5288)) + field(5, field(1, "test") + field(3, "secret-key") + field(4, 8))

  def receive(timeout):
    now[0] += 0.25
    return (bs.WIFI_SETUP_INFO, payload) if now[0] == 0.25 else (bs.WIFI_PING_REQUEST, b"")

  monkeypatch.setattr(boot, "next_frame", receive)
  joined = []
  result = boot.run(joined.append)
  assert result.endpoint.ip == "10.0.0.1" and joined[0].ssid == "test"
  assert 3 <= now[0] < 5


@pytest.mark.parametrize("bssid", ["00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:00:00:00:00:01", "bad", ""])
def test_network_placeholder_bssid_does_not_waste_retry(bssid):
  from dataclasses import replace
  nm = FakeNetworkManager(fail_with_bssid=True)
  lease = make_lease(nm)
  assert lease.acquire(replace(credentials(), bssid=bssid)) == "192.168.50.23"
  assert len(nm.added) == 1 and "bssid" not in nm.added[0]["802-11-wireless"]
  lease.release()


def test_network_normalizes_hyphenated_bssid():
  from dataclasses import replace
  from openpilot.starpilot.system.starpilot_auto.network import connection_settings
  settings = connection_settings(replace(credentials(), bssid="aa-bb-cc-dd-ee-ff"), "wlan0")
  assert settings["802-11-wireless"]["bssid"] == ("ay", bytes.fromhex("aabbccddeeff"))
