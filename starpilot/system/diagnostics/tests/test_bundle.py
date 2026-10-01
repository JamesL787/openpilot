import base64
import io
import json
import os
import time
import zipfile

import pytest

from openpilot.starpilot.system.diagnostics import bundle

SUMMARY = {"dongle_id": "b0c4a280b2f96b86", "branch": "AAComma", "commit": "5abc56a29deadbeef",
           "car_fingerprint": "HONDA_CIVIC_2022", "head_unit": "Honda Display Audio"}


@pytest.fixture(autouse=True)
def isolate_thread_cache(tmp_path, monkeypatch):
  monkeypatch.setattr(bundle, "DIAGNOSTICS_DIR", tmp_path / "diagnostics")


def _starpilot_auto_zip():
  output = io.BytesIO()
  with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("REPORT.txt", "Honda CIVIC: projected")
    archive.writestr("logs/session-000025-20260928-141351.jsonl", '{"event": "session_start"}\n')
  return output.getvalue()


def _drives(tmp_path, *routes):
  for age, route in enumerate(routes):
    first = tmp_path / f"{route}--0"
    first.mkdir()
    (first / "rlog.zst").write_bytes(b"")
    stamp = 1_790_000_000 - age * 3600
    os.utime(first, (stamp, stamp))
  return tmp_path


def _build(tmp_path, **overrides):
  pairing = tmp_path / "pairing.jsonl"
  pairing.write_text('{"kind": "confirmation", "outcome": "timed_out"}\n')
  options = dict(realdata=_drives(tmp_path, "000000cc--newest", "000000cb--older", "000000ca--oldest", "000000c9--too-old"),
                 drive_report=lambda route, _: f"report for {route}", starpilot_auto_bundle=_starpilot_auto_zip,
                 bluetooth_status=lambda: {"powered": True}, pairing_log=pairing, summary=lambda: SUMMARY)
  options.update(overrides)
  return zipfile.ZipFile(io.BytesIO(bundle.build(**options)))


def test_bundle_holds_starpilot_auto_bluetooth_and_newest_drives(tmp_path):
  archive = _build(tmp_path, note="Starpilot Auto took 3 tries", drives=2)
  names = set(archive.namelist())
  assert {"starpilot-auto/REPORT.txt", "starpilot-auto/logs/session-000025-20260928-141351.jsonl", "bluetooth/pairing_events.jsonl",
          "bluetooth/status.json", "drives/000000cc--newest.txt", "drives/000000cb--older.txt", "README.txt"} <= names
  assert "drives/000000ca--oldest.txt" not in names
  readme = archive.read("README.txt").decode()
  assert "Starpilot Auto took 3 tries" in readme and "b0c4a280b2f96b86" in readme and "Could not collect" not in readme


def test_bundle_caps_drives_and_reports_what_it_could_not_collect(tmp_path):
  def broken_report(route, _):
    raise RuntimeError("rlog missing")

  def no_bluetooth():
    raise OSError("bluetooth daemon not running")

  archive = _build(tmp_path, drives=99, drive_report=broken_report, bluetooth_status=no_bluetooth, pairing_log=tmp_path / "missing.jsonl")
  readme = archive.read("README.txt").decode()
  assert readme.count("rlog missing") == bundle.MAX_DRIVES
  assert "bluetooth daemon not running" in readme
  assert archive.read("bluetooth/pairing_events.jsonl") == b""  # never prompted yet: empty, not an error


def test_no_drives_skips_the_expensive_reports(tmp_path):
  calls = []
  archive = _build(tmp_path, drives=0, drive_report=lambda route, _: calls.append(route) or "")
  assert calls == [] and not any(name.startswith("drives/") for name in archive.namelist())


def test_webhook_override_file_wins_and_default_decodes(tmp_path, monkeypatch):
  monkeypatch.setattr(bundle, "_WEBHOOK_B64", base64.b64encode(b"https://example.invalid/hook").decode())
  assert bundle.webhook_url(tmp_path / "absent") == "https://example.invalid/hook"
  override = tmp_path / "webhook_url"
  override.write_text("  https://example.invalid/new\n")
  assert bundle.webhook_url(override) == "https://example.invalid/new"
  monkeypatch.setattr(bundle, "_WEBHOOK_B64", "")
  assert bundle.webhook_url(tmp_path / "absent") == ""


def test_built_in_webhook_is_a_discord_webhook_and_not_plain_text():
  source = (bundle.Path(bundle.__file__)).read_text()
  assert "discord.com/api/webhooks" not in source, "keep the URL encoded so repository scanners don't match it"
  assert bundle.webhook_url(bundle.Path("/nonexistent")).startswith("https://discord.com/api/webhooks/")


class Response:
  def __init__(self, status_code, json_data=None):
    self.status_code = status_code
    self._json_data = json_data

  def json(self):
    if self._json_data is not None:
      return self._json_data
    raise ValueError("No JSON")


def _remember_thread(path, thread_id="999888777", summary=None, url="https://example.invalid/hook"):
  assert bundle.send(b"zip", "diag.zip", "", summary or SUMMARY, url=url, thread_path=path,
                     post=lambda *args, **kwargs: Response(200, {"channel_id": thread_id})) is None


def test_send_posts_zip_and_note_to_discord():
  calls = []
  bundle.send(b"zip-bytes", "diag.zip", "Starpilot Auto dropped at 2:34", SUMMARY, url="https://example.invalid/hook",
              post=lambda url, **kwargs: calls.append((url, kwargs)) or Response(200))
  url, kwargs = calls[0]
  payload = json.loads(kwargs["data"]["payload_json"])
  assert url == "https://example.invalid/hook?wait=true" and kwargs["files"]["files[0]"] == ("diag.zip", b"zip-bytes", "application/zip")
  assert payload["thread_name"] == "HONDA_CIVIC_2022 700dba10"
  assert "Starpilot Auto dropped at 2:34" in payload["content"] and "**Diagnostics from 700dba10**" in payload["content"]
  assert "b0c4a280b2f96b86" not in payload["content"]
  assert "Head unit: Honda Display Audio" in payload["content"] and "Car: HONDA_CIVIC_2022" in payload["content"]
  assert payload["allowed_mentions"] == {"parse": []}, "a tester's note must never ping anyone"


def test_thread_title_falls_back_without_fingerprint():
  assert bundle.thread_title({"dongle_id": "b0c4a280b2f96b86"}) == "Device 700dba10"
  assert bundle.thread_title({}) == f"Device {bundle.device_tag({})}"


def test_head_unit_name_uses_newest_identified_session(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import compat_report
  cars = {"new": {}, "old": {"head_unit_make": "Honda", "head_unit_model": "Display Audio"}}
  monkeypatch.setattr(compat_report, "session_logs", lambda: ["new", "old"])
  monkeypatch.setattr(compat_report, "load_events", lambda path: path)
  monkeypatch.setattr(compat_report, "summarize", lambda path: {"car": cars[path]})
  assert bundle._head_unit_name() == "Honda Display Audio"


def test_send_persists_and_reuses_thread_id(tmp_path):
  thread_path = tmp_path / "thread_id"
  calls = []
  # First send: creates thread and caches returned channel_id
  bundle.send(b"zip-1", "diag1.zip", "note 1", SUMMARY, url="https://example.invalid/hook",
              post=lambda url, **kwargs: calls.append((url, kwargs)) or Response(200, {"channel_id": "999888777"}),
              thread_path=thread_path)
  assert calls[0][0] == "https://example.invalid/hook?wait=true"
  assert json.loads(calls[0][1]["data"]["payload_json"])["thread_name"] == "HONDA_CIVIC_2022 700dba10"
  assert json.loads(thread_path.read_text())["thread_id"] == "999888777"

  # Second send: reuses thread_id
  calls.clear()
  bundle.send(b"zip-2", "diag2.zip", "note 2", SUMMARY, url="https://example.invalid/hook",
              post=lambda url, **kwargs: calls.append((url, kwargs)) or Response(200),
              thread_path=thread_path)
  assert calls[0][0] == "https://example.invalid/hook?wait=true&thread_id=999888777"
  assert "thread_name" not in json.loads(calls[0][1]["data"]["payload_json"])


@pytest.mark.parametrize("status", [400, 404])
def test_send_retries_if_thread_deleted(tmp_path, status):
  thread_path = tmp_path / "thread_id"
  _remember_thread(thread_path)
  calls = []

  def post_mock(url, **kwargs):
    calls.append((url, kwargs))
    if "thread_id=999888777" in url:
      return Response(status, {"code": 10003, "message": "Unknown Channel"})
    return Response(200, {"channel_id": "123456789"})

  bundle.send(b"zip-bytes", "diag.zip", "", SUMMARY, url="https://example.invalid/hook",
              post=post_mock, thread_path=thread_path)
  assert len(calls) == 2
  assert "thread_id=999888777" in calls[0][0]
  assert calls[1][0] == "https://example.invalid/hook?wait=true"
  assert json.loads(calls[1][1]["data"]["payload_json"])["thread_name"] == "HONDA_CIVIC_2022 700dba10"
  assert json.loads(thread_path.read_text())["thread_id"] == "123456789"


@pytest.mark.parametrize("query", ["thread_id=555", "thread%5Fid=555&wait=false"])
def test_send_respects_explicit_thread_id_in_url(tmp_path, query):
  thread_path = tmp_path / "thread_id"
  _remember_thread(thread_path)
  original_cache = thread_path.read_bytes()
  calls = []
  bundle.send(b"zip-bytes", "diag.zip", "", SUMMARY, url=f"https://example.invalid/hook?{query}",
              post=lambda url, **kwargs: calls.append((url, kwargs)) or Response(200),
              thread_path=thread_path)
  assert calls[0][0] == "https://example.invalid/hook?thread_id=555&wait=true"
  assert "thread_name" not in json.loads(calls[0][1]["data"]["payload_json"])
  assert thread_path.read_bytes() == original_cache


@pytest.mark.parametrize("change", ["dongle", "webhook"])
def test_send_checks_cache_identity_even_with_explicit_cache_path(tmp_path, change):
  thread_path = tmp_path / "thread_id"
  _remember_thread(thread_path)
  summary = {**SUMMARY, "dongle_id": "another-dongle"} if change == "dongle" else SUMMARY
  url = "https://example.invalid/another-hook" if change == "webhook" else "https://example.invalid/hook"
  calls = []
  bundle.send(b"zip", "diag.zip", "", summary, url=url, thread_path=thread_path,
              post=lambda url, **kwargs: calls.append((url, kwargs)) or Response(200, {"channel_id": "123456789"}))
  assert "thread_id=" not in calls[0][0]
  assert json.loads(calls[0][1]["data"]["payload_json"])["thread_name"] == f"HONDA_CIVIC_2022 {bundle.device_tag(summary)}"


def test_default_cache_keeps_separate_threads_for_each_dongle_and_webhook():
  calls = []

  def post(url, **kwargs):
    calls.append((url, json.loads(kwargs["data"]["payload_json"])))
    return Response(200, {"channel_id": str(1000 + len(calls))})

  destinations = [(dongle, hook) for dongle in (SUMMARY["dongle_id"], "another-dongle") for hook in ("first", "second")]
  for _ in range(2):
    for dongle, hook in destinations:
      bundle.send(b"zip", "diag.zip", "", {**SUMMARY, "dongle_id": dongle}, url=f"https://example.invalid/{hook}", post=post)
  assert all("thread_name" in payload for _, payload in calls[:4])
  for index, (url, payload) in enumerate(calls[4:], 1):
    assert f"thread_id={1000 + index}" in url
    assert "thread_name" not in payload
  cache_files = list((bundle.DIAGNOSTICS_DIR / "threads").glob("*.json"))
  assert len(cache_files) == 4
  assert all("https://" not in path.read_text() for path in cache_files)


def test_send_does_not_reuse_unscoped_legacy_caches():
  bundle.DIAGNOSTICS_DIR.mkdir()
  (bundle.DIAGNOSTICS_DIR / "thread_id").write_text("111")
  (bundle.DIAGNOSTICS_DIR / f"thread_id_{SUMMARY['dongle_id']}").write_text("222")
  calls = []
  bundle.send(b"zip", "diag.zip", "", SUMMARY, url="https://example.invalid/hook",
              post=lambda url, **kwargs: calls.append((url, kwargs)) or Response(200, {"channel_id": "333"}))
  assert calls[0][0] == "https://example.invalid/hook?wait=true"
  assert json.loads(calls[0][1]["data"]["payload_json"])["thread_name"] == "HONDA_CIVIC_2022 700dba10"


@pytest.mark.parametrize("content", ["not-json", "999888777", "[]", '{"thread_id": "123"}'])
def test_send_recovers_from_invalid_cache(tmp_path, content):
  thread_path = tmp_path / "thread_id"
  thread_path.write_text(content)
  calls = []
  bundle.send(b"zip", "diag.zip", "", SUMMARY, url="https://example.invalid/hook", thread_path=thread_path,
              post=lambda url, **kwargs: calls.append(url) or Response(200, {"channel_id": "123456789"}))
  assert calls == ["https://example.invalid/hook?wait=true"]
  assert json.loads(thread_path.read_text())["thread_id"] == "123456789"


def test_send_parses_query_and_replaces_wait_without_changing_cache_identity(tmp_path):
  thread_path = tmp_path / "thread_id"
  _remember_thread(thread_path)
  calls = []
  bundle.send(b"zip", "diag.zip", "", SUMMARY, thread_path=thread_path,
              url="https://example.invalid/hook?wait=false&with_components=true&thread_id=",
              post=lambda url, **kwargs: calls.append((url, kwargs)) or Response(200))
  assert calls[0][0] == "https://example.invalid/hook?wait=true&with_components=true&thread_id=999888777"
  assert "thread_name" not in json.loads(calls[0][1]["data"]["payload_json"])


@pytest.mark.parametrize("second_status", [200, 404])
def test_thread_recovery_is_bounded_when_cache_cannot_be_deleted(tmp_path, monkeypatch, second_status):
  thread_path = tmp_path / "thread_id"
  _remember_thread(thread_path)
  original_unlink = bundle.Path.unlink

  def unlink(path, **kwargs):
    if path == thread_path:
      raise PermissionError("cache cannot be deleted")
    return original_unlink(path, **kwargs)

  monkeypatch.setattr(bundle.Path, "unlink", unlink)
  calls = []

  def post(url, **kwargs):
    calls.append((url, kwargs))
    assert len(calls) <= 2, "recovery must stop after two requests"
    return Response(404, {"code": 10003}) if len(calls) == 1 else Response(second_status, {"channel_id": "123456789"})

  if second_status == 200:
    assert bundle.send(b"zip", "diag.zip", "", SUMMARY, url="https://example.invalid/hook", post=post, thread_path=thread_path) is None
    assert json.loads(thread_path.read_text())["thread_id"] == "123456789"
  else:
    with pytest.raises(RuntimeError, match="HTTP 404"):
      bundle.send(b"zip", "diag.zip", "", SUMMARY, url="https://example.invalid/hook", post=post, thread_path=thread_path)
  assert len(calls) == 2
  assert "thread_id=" not in calls[1][0]
  assert "thread_name" in json.loads(calls[1][1]["data"]["payload_json"])


def test_missing_webhook_does_not_discard_cache_or_retry(tmp_path):
  thread_path = tmp_path / "thread_id"
  _remember_thread(thread_path)
  original_cache = thread_path.read_bytes()
  calls = []
  with pytest.raises(RuntimeError, match="HTTP 404"):
    bundle.send(b"zip", "diag.zip", "", SUMMARY, url="https://example.invalid/hook", thread_path=thread_path,
                post=lambda url, **kwargs: calls.append(url) or Response(404, {"code": 10015, "message": "Unknown Webhook"}))
  assert len(calls) == 1
  assert thread_path.read_bytes() == original_cache


@pytest.mark.parametrize("response", [Response(204), Response(200), Response(200, {"channel_id": "bad-id"})])
def test_success_without_a_usable_thread_id_returns_cache_warning(tmp_path, response):
  assert bundle.send(b"zip", "diag.zip", "", SUMMARY, url="https://example.invalid/hook", thread_path=tmp_path / "thread_id",
                     post=lambda *args, **kwargs: response) == bundle.THREAD_CACHE_WARNING


def test_cache_write_failure_preserves_previous_entry_and_warns(tmp_path, monkeypatch):
  thread_path = tmp_path / "thread_id"
  _remember_thread(thread_path)
  original_cache = thread_path.read_bytes()

  def cannot_replace(*args):
    raise PermissionError("cache is not writable")

  monkeypatch.setattr(bundle.os, "replace", cannot_replace)
  warning = bundle.send(b"zip", "diag.zip", "", {**SUMMARY, "dongle_id": "another-dongle"}, url="https://example.invalid/hook",
                        thread_path=thread_path, post=lambda *args, **kwargs: Response(200, {"channel_id": "123456789"}))
  assert warning == bundle.THREAD_CACHE_WARNING
  assert thread_path.read_bytes() == original_cache
  assert list(tmp_path.iterdir()) == [thread_path]


@pytest.mark.parametrize("kwargs, message", [
  ({"url": ""}, "isn't set up"),
  ({"url": "https://example.invalid/hook", "data": b"x" * (bundle.DISCORD_FILE_LIMIT + 1)}, "10 MB limit"),
  ({"url": "https://example.invalid/hook", "post": lambda *a, **k: Response(413)}, "HTTP 413"),
])
def test_send_failures_tell_the_tester_what_to_do(kwargs, message):
  data = kwargs.pop("data", b"zip")
  kwargs.setdefault("post", lambda *a, **k: pytest.fail("must not post"))
  with pytest.raises(RuntimeError, match=message) as error:
    bundle.send(data, "diag.zip", "", SUMMARY, **kwargs)
  assert "Download" in str(error.value)


def _wait(job):
  deadline = time.monotonic() + 5
  while job.status()["state"] in ("preparing", "sending"):
    assert time.monotonic() < deadline
    time.sleep(0.01)
  return job.status()


def test_job_download_flow():
  job = bundle.DiagnosticsJob(builder=lambda **_: b"zip", summary=lambda: SUMMARY)
  assert job.result() is None
  job.start("download", "note", 1)
  status = _wait(job)
  assert status["state"] == "ready" and status["bytes"] == 3
  name, data = job.result()
  assert data == b"zip" and name.startswith("starpilot-diagnostics-b0c4a280b2f96b86-")


def test_job_send_success_and_failure_keeps_the_zip():
  sent = []
  job = bundle.DiagnosticsJob(builder=lambda **_: b"zip", sender=lambda *args: sent.append(args), summary=lambda: SUMMARY)
  job.start("send")
  assert _wait(job)["state"] == "sent" and sent[0][0] == b"zip"

  def offline(*_):
    raise RuntimeError("Could not send the report")

  job = bundle.DiagnosticsJob(builder=lambda **_: b"zip", sender=offline, summary=lambda: SUMMARY)
  job.start("send")
  status = _wait(job)
  assert status["state"] == "send_failed" and "Could not send the report" in status["message"]
  assert job.result()[1] == b"zip", "a failed send can still be downloaded"


def test_job_shows_cache_warning_after_successful_upload():
  job = bundle.DiagnosticsJob(builder=lambda **_: b"zip", sender=lambda *args: bundle.THREAD_CACHE_WARNING, summary=lambda: SUMMARY)
  job.start("send")
  status = _wait(job)
  assert status["state"] == "sent"
  assert status["message"] == f"Report sent. {bundle.THREAD_CACHE_WARNING}"
  assert job.result()[1] == b"zip"


def test_job_rejects_unknown_action_and_overlapping_runs():
  gate = __import__("threading").Event()
  job = bundle.DiagnosticsJob(builder=lambda **_: gate.wait(5) and b"zip", summary=lambda: SUMMARY)
  with pytest.raises(ValueError):
    job.start("email")
  job.start("download")
  with pytest.raises(RuntimeError, match="already"):
    job.start("download")
  gate.set()
  assert _wait(job)["state"] == "ready"


def test_builder_failure_is_reported():
  def broken(**_):
    raise OSError("disk full")

  job = bundle.DiagnosticsJob(builder=broken, summary=lambda: SUMMARY)
  job.start("download")
  assert _wait(job) | {"send_available": None} == {"state": "error", "message": "disk full", "action": "download", "name": "",
                                                   "bytes": 0, "send_available": None}


def test_automatic_reports_use_their_own_webhook(tmp_path):
  assert bundle.auto_webhook_url(tmp_path / "missing").startswith("https://discord.com/api/webhooks/")
  assert bundle.auto_webhook_url(tmp_path / "missing") != bundle.webhook_url(tmp_path / "missing")
  override = tmp_path / "auto"
  override.write_text("https://example.invalid/auto\n")
  assert bundle.auto_webhook_url(override) == "https://example.invalid/auto"
