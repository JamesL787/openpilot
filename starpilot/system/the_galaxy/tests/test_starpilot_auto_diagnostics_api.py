import io
import json
import zipfile
from pathlib import Path

import test_navigation_params as nav
from openpilot.starpilot.system.starpilot_auto import compat_report, identity as identity_store

JS_ROOT = Path(__file__).resolve().parent.parent / "assets" / "mobile" / "js"

WIRED_SESSION = [
  {"t": "2026-09-27T20:00:00.000+00:00", "event": "session_start", "receiver": "usb", "generation": 1, "trigger": "manual"},
  {"t": "2026-09-27T20:00:00.100+00:00", "event": "usb_gadget_prepared", "mode": "handshake", "released": "g1"},
  {"t": "2026-09-27T20:00:00.200+00:00", "event": "stage", "state": "waiting_for_usb", "detail": ""},
  {"t": "2026-09-27T20:00:10.200+00:00", "event": "usb_no_accessory_start", "waited": 10.0},
  {"t": "2026-09-27T20:00:10.900+00:00", "event": "stage", "state": "usb_accessory", "detail": "direct"},
  {"t": "2026-09-27T20:00:11.000+00:00", "event": "usb_accessory_ready", "method": "direct",
   "strings": {"manufacturer": "Android", "model": "Starpilot Auto", "serial": "redacted"}},
  {"t": "2026-09-27T20:00:11.100+00:00", "event": "stage", "state": "authenticating", "detail": ""},
  {"t": "2026-09-27T20:00:11.200+00:00", "event": "tls_failed", "reason": "NO_SHARED_CIPHER", "library": "SSL", "error": "x"},
  {"t": "2026-09-27T20:00:11.300+00:00", "event": "attempt_failed", "stage": "authenticating",
   "error": "authenticating: [SSL: NO_SHARED_CIPHER] no shared cipher", "kind": "SSLError"},
]
WIRELESS_SESSION = [
  {"t": "2026-09-27T21:00:00.000+00:00", "event": "session_start", "receiver": "Honda CIVIC", "generation": 1, "trigger": "onroad"},
  {"t": "2026-09-27T21:00:00.100+00:00", "event": "stage", "state": "connecting_bluetooth", "detail": "Honda CIVIC"},
  {"t": "2026-09-27T21:00:02.000+00:00", "event": "bootstrap_version", "major": 1, "minor": 3,
   "head_unit": {"car_make": "Honda", "car_model": "Civic", "car_year": "2022"}},
  {"t": "2026-09-27T21:00:03.000+00:00", "event": "bootstrap_credentials", "ssid": "StarpilotAuto-1234", "bssid": "AA:BB:CC:DD:EE:FF",
   "security": "wpa2", "ap_type": 1, "key_length": 12},
  {"t": "2026-09-27T21:00:05.000+00:00", "event": "stage", "state": "authenticating", "detail": ""},
  {"t": "2026-09-27T21:00:05.200+00:00", "event": "tls_established", "version": "TLSv1.2", "cipher": "ECDHE-RSA-AES128-GCM-SHA256"},
  {"t": "2026-09-27T21:00:05.500+00:00", "event": "discovered", "head_unit": {"2": ["Honda"], "3": ["Civic"], "5": ["redacted"],
   "17": [{"1": ["Honda"], "2": ["CIVIC"], "4": ["redacted"], "6": ["Gen4"]}]},
   "channels": [{"id": 3, "services": [3], "display_type": None, "video_configs": [{"1": [1]}, {"1": [2], "4": [240]}]},
                {"id": 5, "services": [3], "display_type": 1, "video_configs": [{"1": [2]}]}]},
  {"t": "2026-09-27T21:00:05.700+00:00", "event": "projection_ready", "mode": {"width": 1280, "height": 720, "fps": 30,
   "margin_width": 0, "margin_height": 240}, "head_unit_subject": "O=Honda"},
  {"t": "2026-09-27T21:00:05.800+00:00", "event": "video_focus", "focus": 1, "unsolicited": 0, "focused": True},
  {"t": "2026-09-27T21:00:05.900+00:00", "event": "video_acknowledged", "session": 1, "ack_ms": 40},
  {"t": "2026-09-27T21:00:06.000+00:00", "event": "control_ignored", "channel": 0, "kind": 18, "count": 1, "bytes": 2, "message": {"1": [1]}},
  {"t": "2026-09-27T21:00:06.100+00:00", "event": "control_ignored", "channel": 0, "kind": 18, "count": 2, "bytes": 2, "message": {"1": [1]}},
]


def _write(directory: Path, name: str, events: list[dict]) -> None:
  directory.mkdir(parents=True, exist_ok=True)
  (directory / name).write_text("".join(json.dumps(event) + "\n" for event in events) + '{"t": "cut sh')


def _client(monkeypatch, tmp_path, enabled=True):
  logs = tmp_path / "logs"
  _write(logs, "session-000001-20260927-130000.jsonl", WIRED_SESSION)
  _write(logs, "session-000002-20260927-140000.jsonl", WIRELESS_SESSION)
  (logs / "car_ui.log").write_text("renderer started\n")
  (logs / "notes.txt").write_text("not a session log")
  monkeypatch.setattr(identity_store, "LOG_DIR", logs)
  monkeypatch.setattr(identity_store, "CONFIG_PATH", tmp_path / "config.json")
  client, _ = nav._params_client(monkeypatch, {"IsOffroad": True, "StarpilotAutoEnabled": enabled}, "mici")
  return client


def test_reports_summarize_what_a_compatibility_report_needs():
  wired = compat_report.summarize(WIRED_SESSION)
  assert wired["transport"] == "wired" and wired["usb"]["method"] == "direct" and wired["usb"]["no_handshake_after_s"] == 10.0
  assert wired["tls"]["failed"] == "NO_SHARED_CIPHER" and wired["outcome"].startswith("failed: authenticating")
  assert wired["usb"]["accessory_strings"]["model"] == "Starpilot Auto" and wired["furthest_stage"] == "authenticating"

  wireless = compat_report.summarize(WIRELESS_SESSION)
  assert wireless["outcome"] == "projected" and wireless["wifi"]["security"] == "wpa2"
  assert wireless["car"]["car_model"] == "CIVIC" and wireless["car"]["head_unit_model"] == "Gen4", "headunit_info wins"
  assert wireless["video"]["offered"] == ["800x480 H.264", "1280x720 H.264 margins 0x240", "1280x720 H.264 (display 1)"]
  assert wireless["ignored"] == [{"event": "control_ignored", "channel": 0, "kind": 18, "count": 2, "example": {"1": [1]}}]
  text = compat_report.render_text(wireless, "session-000002")
  assert "margins 0x240" in wireless["video"]["offered"][1]
  assert "Outcome: projected" in text and "StarpilotAuto-1234" not in text and "AA:BB:CC:DD:EE:FF" not in text


def test_focus_and_streaming_without_acknowledged_video_is_not_projection():
  events = [record for record in WIRELESS_SESSION if record["event"] != "video_acknowledged"]
  events.insert(-2, {"t": "", "event": "stage", "state": "streaming", "detail": ""})
  events.append({"t": "", "event": "attempt_failed", "stage": "streaming", "error": "projecting: No video acknowledgements", "kind": "TimeoutError"})
  report = compat_report.summarize(events)
  assert report["focus"]["granted"] == 1 and report["outcome"] == "failed: projecting: No video acknowledgements"
  report = compat_report.summarize([*WIRELESS_SESSION, events[-1]])
  assert report["outcome"] == "projected, then failed: projecting: No video acknowledgements"


def test_diagnostics_list_newest_first_even_with_starpilot_auto_off(monkeypatch, tmp_path):
  client = _client(monkeypatch, tmp_path, enabled=False)
  response = client.get("/api/starpilot_auto/diagnostics")
  assert response.status_code == 200 and response.headers["Cache-Control"].startswith("no-store")
  sessions = response.get_json()["sessions"]
  assert [session["name"] for session in sessions] == ["session-000002-20260927-140000.jsonl", "session-000001-20260927-130000.jsonl"]
  assert sessions[0]["outcome"] == "projected" and sessions[0]["car"]["car_make"] == "Honda" and sessions[1]["transport"] == "wired"


def test_one_report_and_its_raw_log(monkeypatch, tmp_path):
  client = _client(monkeypatch, tmp_path)
  report = client.get("/api/starpilot_auto/diagnostics/session-000001-20260927-130000.jsonl").get_json()
  assert report["report"]["usb"]["method"] == "direct" and "Outcome: failed" in report["text"]
  log = client.get("/api/starpilot_auto/diagnostics/session-000001-20260927-130000.jsonl?format=log")
  assert log.status_code == 200 and "attachment" in log.headers["Content-Disposition"] and b"usb_no_accessory_start" in log.data
  log.close()
  for name in ("notes.txt", "..%2Fconfig.json", "car_ui.log", "session-missing.jsonl"):
    assert client.get(f"/api/starpilot_auto/diagnostics/{name}?format=log").status_code == 404


def test_bundle_has_logs_reports_and_settings_but_no_identity(monkeypatch, tmp_path):
  client = _client(monkeypatch, tmp_path)
  identity = tmp_path / "identity"
  identity.mkdir()
  (identity / "phone-key.pem").write_text("PRIVATE KEY")
  response = client.get("/api/starpilot_auto/diagnostics/bundle")
  assert response.status_code == 200 and response.mimetype == "application/zip"
  assert "starpilot-auto-" in response.headers["Content-Disposition"]
  with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
    names = set(archive.namelist())
    assert {"REPORT.txt", "config.json", "logs/car_ui.log", "logs/session-000001-20260927-130000.jsonl",
            "reports/session-000002-20260927-140000.json"} <= names
    assert not any("identity" in name or name.endswith(".pem") or "notes" in name for name in names)
    assert "Outcome: projected" in archive.read("REPORT.txt").decode()
    assert json.loads(archive.read("config.json"))["usb_mode"] == "auto"


def test_logs_page_offers_the_diagnostics_panel_without_settings_duplicate():
  settings = (JS_ROOT / "views" / "Settings.js").read_text()
  logs = (JS_ROOT / "views" / "Logs.js").read_text()
  panel = (JS_ROOT / "components" / "StarpilotAutoDiagnosticsPanel.js").read_text()
  assert "<StarpilotAutoDiagnosticsPanel />" in logs
  assert "StarpilotAutoDiagnosticsPanel" not in settings and 'title="Diagnostics"' not in settings
  assert "/api/starpilot_auto/diagnostics/bundle" in panel and "format=log" in panel and "fetch(" not in panel
