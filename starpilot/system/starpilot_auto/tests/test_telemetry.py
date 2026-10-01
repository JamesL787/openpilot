import json
import os
import time
from pathlib import Path

import pytest

from openpilot.starpilot.system.starpilot_auto import telemetry

SUMMARY = {"dongle_id": "b0c4a280b2f96b86", "branch": "AAComma", "commit": "5abc56a29deadbeef", "car_fingerprint": "HONDA_CIVIC_2022"}


def t(second):
  return f"2026-09-29T10:00:{second:02d}.000+00:00"


def write_log(directory: Path, number: int, events: list[tuple], age: float = 3600) -> Path:
  path = directory / f"session-{number:06d}-20260929-100000.jsonl"
  path.write_text("\n".join(json.dumps({"t": t(second), "event": name, **values}) for second, name, values in events) + "\n")
  stamp = os.path.getmtime(path) - age
  os.utime(path, (stamp, stamp))
  return path


STREAMING = [
  (0, "session_start", {"receiver": "Honda HFL", "trigger": "auto"}),
  (1, "stage", {"state": "rfcomm"}),
  (5, "bootstrap_version", {"major": 1, "minor": 7, "head_unit": {"head_unit_make": "Honda", "head_unit_model": "Display Audio",
                                                                   "car_make": "Honda"}}),
  (9, "stage", {"state": "streaming"}),
  (12, "video_acknowledged", {}),
  (42, "session_ended", {}),
]


def test_session_record_streamed(tmp_path):
  record = telemetry.session_record(write_log(tmp_path, 7, STREAMING))
  assert record["seq"] == 7 and record["outcome"] == "streamed" and record["transport"] == "wireless"
  assert record["trigger"] == "auto" and record["furthest_stage"] == "streaming"
  assert record["time_to_first_frame_s"] == 12.0 and record["streamed_s"] == 30.0 and record["drops"] == 0
  assert record["head_unit"] == {"head_unit_make": "Honda", "head_unit_model": "Display Audio", "car_make": "Honda"}


def test_session_record_dropped_and_failed(tmp_path):
  dropped = STREAMING[:-1] + [(30, "attempt_failed", {"stage": "streaming", "error": "link lost", "kind": "ConnectionResetError"})]
  record = telemetry.session_record(write_log(tmp_path, 1, dropped))
  assert record["outcome"] == "dropped" and record["drops"] == 1 and record["error_kind"] == "ConnectionResetError"

  failed = [(0, "session_start", {"receiver": "usb"}), (1, "stage", {"state": "usb_accessory"}),
            (3, "attempt_failed", {"stage": "usb_accessory", "error": "no handshake", "kind": "BootstrapTimeout"})]
  record = telemetry.session_record(write_log(tmp_path, 2, failed))
  assert record["outcome"] == "failed" and record["transport"] == "wired" and record["failed_stage"] == "usb_accessory"
  assert record["failures"] == 1 and record["time_to_first_frame_s"] is None and "error" not in record


def test_session_record_holds_no_free_text(tmp_path):
  failed = [(0, "session_start", {"receiver": "Danny's Civic"}),
            (3, "attempt_failed", {"stage": "rfcomm", "error": "AA:BB:CC:DD:EE:FF refused", "kind": "OSError"})]
  text = json.dumps(telemetry.session_record(write_log(tmp_path, 1, failed)))
  assert "AA:BB" not in text and "Danny" not in text


def test_session_record_says_where_a_session_got_to(tmp_path):
  events = [(0, "session_start", {"receiver": "Danny's Civic"}), (1, "stage", {"state": "rfcomm"}), (2, "hfp_connected", {}),
            (2, "rfcomm_channel", {"channel": 8}), (4, "stage", {"state": "joining_wifi"}), (4, "stage", {"state": "rfcomm"}),
            (9, "stage", {"state": "authenticating"}),
            (10, "tls_failed", {"reason": "CERTIFICATE_VERIFY_FAILED", "error": "AA:BB:CC:DD:EE:FF bad cert for Danny"}),
            (11, "attempt_failed", {"stage": "authenticating", "error": "x", "kind": "SSLError"})]
  record = telemetry.session_record(write_log(tmp_path, 1, events))
  assert record["stages"] == [["rfcomm", 1.0], ["joining_wifi", 4.0], ["authenticating", 9.0]]
  assert record["facts"] == {"hands_free": True, "rfcomm_channel": 8, "tls_failed_reason": "CERTIFICATE_VERIFY_FAILED", "focus_lost": 0}
  assert "AA:BB" not in json.dumps(record) and "Danny" not in json.dumps(record)


def test_reconnect_errors_after_the_car_ends_the_projection_are_not_drops(tmp_path):
  events = STREAMING[:-1] + [
    (30, "session_ended", {"reason": "Head unit ended projection (reason 1)"}),
    (60, "attempt_failed", {"stage": "connecting_bluetooth", "error": "connecting to car: TimeoutError", "kind": "TimeoutError"}),
    (73, "attempt_failed", {"stage": "rfcomm", "error": "Host is down", "kind": "OSError"}),
  ]
  record = telemetry.session_record(write_log(tmp_path, 1, events))
  assert record["outcome"] == "streamed" and record["drops"] == 0 and record["failures"] == 0 and record["error_kind"] == ""
  assert record["facts"]["ended_by_car"] is True

  stalled = STREAMING[:-1] + [(20, "attempt_failed", {"stage": "streaming", "error": "stall", "kind": "TimeoutError"}),
                              (30, "session_ended", {"reason": "Head unit ended projection (reason 1)"})]
  record = telemetry.session_record(write_log(tmp_path, 2, stalled))
  assert record["outcome"] == "dropped" and record["drops"] == 1  # a stall before the car left still counts


def report(tmp_path, enabled, state=None, now=None):
  return telemetry.build_report(enabled, state or {}, SUMMARY, "wireless", tmp_path, "C3X", now=now)


def test_never_enabled_sends_nothing(tmp_path):
  assert report(tmp_path, False) is None


def test_enabled_reports_sessions_once(tmp_path):
  write_log(tmp_path, 1, STREAMING)
  write_log(tmp_path, 2, STREAMING)
  first = report(tmp_path, True)
  assert first["event"] == "enabled" and [s["seq"] for s in first["sessions"]] == [1, 2]
  assert first["device"] == telemetry.device_hash("b0c4a280b2f96b86") and "b0c4a280" not in json.dumps(first)
  assert first["connection"] == "wireless" and first["device_generation"] == "C3X" and first["car_fingerprint"] == "HONDA_CIVIC_2022"
  assert first["head_unit"]["head_unit_model"] == "Display Audio"

  later = report(tmp_path, True, {"last_enabled": True, "last_seq": 1})
  assert later["event"] == "heartbeat" and [s["seq"] for s in later["sessions"]] == [2]


def test_live_log_is_held_back(tmp_path):
  write_log(tmp_path, 1, STREAMING)
  write_log(tmp_path, 2, STREAMING, age=5)
  assert [s["seq"] for s in report(tmp_path, True)["sessions"]] == [1]


def test_disable_is_reported_once(tmp_path):
  payload = report(tmp_path, False, {"last_enabled": True, "last_seq": 4})
  assert payload["event"] == "disabled" and payload["enabled"] is False
  assert report(tmp_path, False, {"last_enabled": False, "last_seq": 4}) is None
  assert report(tmp_path, True, {"last_enabled": False, "last_seq": 4})["event"] == "enabled"


class Response:
  def __init__(self, status_code):
    self.status_code = status_code


def test_state_advances_only_after_the_server_accepts(tmp_path):
  logs, state_path = tmp_path / "logs", tmp_path / "telemetry.json"
  logs.mkdir()
  write_log(logs, 3, STREAMING)
  sent = []

  def send(status):
    return telemetry.send_report(True, SUMMARY, "wireless", "C3X", url="https://example.invalid/t", state_path=state_path, log_dir=logs,
                                 post=lambda url, **kwargs: sent.append((url, kwargs)) or Response(status))

  with pytest.raises(RuntimeError):
    send(500)
  assert not state_path.exists()
  assert send(200) is True
  assert json.loads(state_path.read_text()) == {"last_enabled": True, "last_seq": 3}
  assert sent[0][1]["json"]["sessions"][0]["seq"] == 3 and sent[0][1]["json"]["report_id"] != sent[1][1]["json"]["report_id"]
  assert send(200) is True and sent[2][1]["json"]["sessions"] == []


def test_no_url_means_no_request(tmp_path):
  assert telemetry.send_report(True, SUMMARY, "wireless", "C3X", url="", state_path=tmp_path / "s.json", post=lambda *a, **k: 1 / 0) is False



def failure(outcome="failed", stage="rfcomm", error="TimeoutError"):
  return {"outcome": outcome, "failed_stage": stage, "furthest_stage": stage, "error_kind": error}


def recorder(calls):
  def builder(note, drives):
    calls.append(("build", drives, note))
    return b"zip"

  def sender(data, name, note, summary, url=None):
    calls.append(("send", data, note, url))
  return builder, sender


def test_each_new_kind_of_failure_is_sent_once_a_day_without_drives(tmp_path):
  calls = []
  builder, sender = recorder(calls)
  state = tmp_path / "diag.json"
  send = lambda sessions, now: telemetry.send_failure_diagnostics({"sessions": sessions}, SUMMARY, state, now=now, builder=builder, sender=sender)

  assert send([failure()], 1000)
  assert calls[0][1] == 0 and "failed at rfcomm (TimeoutError)" in calls[0][2]
  assert calls[1][3] and calls[1][3].startswith("https://discord.com/api/webhooks/")
  assert not send([failure(), failure()], 2000)  # the same failure again: already reported today
  assert send([failure(stage="authenticating", error="SSLError")], 3000)  # a different failure is new
  assert "failed at authenticating (SSLError)" in calls[-1][2]
  assert send([failure()], 1000 + 86401)  # a day later the first kind is new again
  assert len([c for c in calls if c[0] == "send"]) == 3


def test_several_new_failures_share_one_report(tmp_path):
  calls = []
  builder, sender = recorder(calls)
  assert telemetry.send_failure_diagnostics({"sessions": [failure(), failure("dropped", "streaming", "TimeoutError")]}, SUMMARY,
                                            tmp_path / "diag.json", now=10, builder=builder, sender=sender)
  sends = [c for c in calls if c[0] == "send"]
  assert len(sends) == 1 and "new failures:" in sends[0][2]
  assert "dropped at streaming (TimeoutError)" in sends[0][2] and "failed at rfcomm (TimeoutError)" in sends[0][2]


def test_reports_are_capped_per_day(tmp_path):
  calls = []
  builder, sender = recorder(calls)
  state = tmp_path / "diag.json"
  sent = [telemetry.send_failure_diagnostics({"sessions": [failure(error=f"Error{n}")]}, SUMMARY, state, now=100 + n,
                                             builder=builder, sender=sender) for n in range(8)]
  assert sent == [True] * telemetry.DIAGNOSTICS_MAX_PER_WINDOW + [False] * (8 - telemetry.DIAGNOSTICS_MAX_PER_WINDOW)


def test_failure_diagnostics_skip_healthy_sessions_and_failed_uploads(tmp_path):
  state = tmp_path / "diag.json"
  streamed = {"sessions": [{"outcome": "streamed", "failed_stage": "", "furthest_stage": "streaming", "error_kind": ""}]}
  assert not telemetry.send_failure_diagnostics(streamed, SUMMARY, state, builder=lambda **_: b"", sender=lambda *_, **__: None)

  def broken(*_, **__):
    raise RuntimeError("discord down")

  with pytest.raises(RuntimeError):
    telemetry.send_failure_diagnostics({"sessions": [failure()]}, SUMMARY, state, now=5, builder=lambda **_: b"zip", sender=broken)
  saved = json.loads(state.read_text())  # a failed upload does not use up the failure or the daily allowance; it stays queued
  assert saved["sent"] == {} and saved["uploads"] == [] and list(saved["queued"]) == ["failed:rfcomm:TimeoutError"]
  calls = []
  builder, sender = recorder(calls)
  assert telemetry.send_failure_diagnostics({"sessions": []}, SUMMARY, state, now=6, builder=builder, sender=sender)
  assert "failed at rfcomm (TimeoutError)" in [c for c in calls if c[0] == "send"][0][2]


def test_send_report_hands_the_payload_to_the_callback(tmp_path):
  log_dir = tmp_path / "logs"
  log_dir.mkdir()
  write_log(log_dir, 1, [(0, "session_start", {"receiver": "usb"}), (1, "attempt_failed", {"stage": "usb_accessory", "error": "x", "kind": "BootstrapTimeout"})])

  class Response:
    status_code = 204

  seen = []
  assert telemetry.send_report(True, SUMMARY, "wired", "C3X", url="https://example.invalid", post=lambda *a, **k: Response(),
                               state_path=tmp_path / "state.json", log_dir=log_dir, sent=seen.append)
  assert telemetry.failed_sessions(seen[0])[0]["failed_stage"] == "usb_accessory"


def test_heavy_features_are_plain_flags(tmp_path):
  from types import SimpleNamespace
  toggles = SimpleNamespace(vision_speed_limit_detection=True, v_asm_enabled=0, model_name="secret")
  assert telemetry.heavy_features(toggles) == {"speed_limit_vision": True, "blind_spot_vision": False}
  assert telemetry.heavy_features(SimpleNamespace()) == {"speed_limit_vision": False, "blind_spot_vision": False}
  write_log(tmp_path, 1, STREAMING)
  payload = telemetry.build_report(True, {}, SUMMARY, "wireless", tmp_path, "C3X",
                                   features=telemetry.heavy_features(toggles))
  assert payload["features"] == {"speed_limit_vision": True, "blind_spot_vision": False}


def test_a_finished_session_is_reported_at_once_and_a_live_one_waits(tmp_path):
  write_log(tmp_path, 1, STREAMING)
  live = write_log(tmp_path, 2, STREAMING)
  os.utime(live, (time.time(), time.time()))
  assert [s["seq"] for s in report(tmp_path, True)["sessions"]] == [1]

  with live.open("a") as log:  # the daemon appends session_stop when the session is over
    log.write(json.dumps({"t": "2026-09-21T07:31:00+00:00", "event": "session_stop"}) + "\n")
  os.utime(live, (time.time(), time.time()))
  assert [s["seq"] for s in report(tmp_path, True)["sessions"]] == [1, 2]


def test_periodic_retry_only_sends_when_there_is_something_new(tmp_path):
  def retry(state):
    return telemetry.build_report(True, state, SUMMARY, "wireless", tmp_path, "C3X", only_if_new=True)

  assert retry({"last_enabled": True, "last_seq": 0}) is None  # no sessions and no on/off change: no heartbeat
  assert retry({"last_enabled": False, "last_seq": 0})["event"] == "enabled"
  write_log(tmp_path, 1, STREAMING)
  assert [s["seq"] for s in retry({"last_enabled": True, "last_seq": 0})["sessions"]] == [1]
  assert retry({"last_enabled": True, "last_seq": 1}) is None


def test_a_backlog_goes_out_oldest_first_in_batches_without_skipping(tmp_path):
  for n in range(1, telemetry.MAX_SESSIONS + 6):
    write_log(tmp_path, n, STREAMING)
  first = report(tmp_path, True, {"last_enabled": True, "last_seq": 0})
  assert [s["seq"] for s in first["sessions"]] == list(range(1, telemetry.MAX_SESSIONS + 1))
  second = report(tmp_path, True, {"last_enabled": True, "last_seq": telemetry.MAX_SESSIONS})
  assert [s["seq"] for s in second["sessions"]] == list(range(telemetry.MAX_SESSIONS + 1, telemetry.MAX_SESSIONS + 6))


def test_failures_found_while_driving_wait_for_the_car_to_be_off(tmp_path):
  calls = []
  builder, sender = recorder(calls)
  state = tmp_path / "diag.json"
  driving = telemetry.send_failure_diagnostics({"sessions": [failure()]}, SUMMARY, state, now=10, builder=builder, sender=sender,
                                               car_off=False)
  assert not driving and calls == []  # nothing is built or uploaded mid-drive
  assert telemetry.send_failure_diagnostics({"sessions": [failure("dropped", "streaming", "TimeoutError")]}, SUMMARY, state, now=20,
                                            builder=builder, sender=sender, car_off=True)
  note = [c for c in calls if c[0] == "send"][0][2]
  assert "failed at rfcomm (TimeoutError)" in note and "dropped at streaming (TimeoutError)" in note  # one upload carries both
  assert not telemetry.send_failure_diagnostics({"sessions": []}, SUMMARY, state, now=30, builder=builder, sender=sender)
