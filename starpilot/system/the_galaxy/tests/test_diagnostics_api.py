import time
import zipfile
import io
from pathlib import Path

import test_navigation_params as nav
from openpilot.starpilot.system.diagnostics import bundle as diagnostics_bundle
from openpilot.starpilot.system.the_galaxy import the_galaxy

JS_ROOT = Path(__file__).resolve().parent.parent / "assets" / "mobile" / "js"
DiagnosticsJob = diagnostics_bundle.DiagnosticsJob


def _zip():
  output = io.BytesIO()
  with zipfile.ZipFile(output, "w") as archive:
    archive.writestr("README.txt", "StarPilot diagnostics")
  return output.getvalue()


def _client(monkeypatch, onroad=False, sender=None):
  calls = {"build": [], "send": []}

  def builder(note="", drives=1, progress=lambda _: None):
    calls["build"].append((note, drives))
    progress("Summarizing drive 1 of 1")
    return _zip()

  def default_sender(data, name, note, summary):
    calls["send"].append((name, note))

  monkeypatch.setattr(the_galaxy.diagnostics_bundle, "DiagnosticsJob",
                      lambda: DiagnosticsJob(builder=builder, sender=sender or default_sender,
                                                                summary=lambda: {"dongle_id": "tester"}))
  monkeypatch.setattr(the_galaxy.diagnostics_bundle, "recent_routes", lambda: ["000000cb--604289c5b5"])
  client, _ = nav._params_client(monkeypatch, {"IsOffroad": not onroad, "IsOnroad": onroad}, "mici")
  return client, calls


def _settle(client):
  deadline = time.monotonic() + 5
  while (status := client.get("/api/diagnostics/status").get_json())["state"] in ("preparing", "sending"):
    assert time.monotonic() < deadline
    time.sleep(0.01)
  return status


def test_status_before_anything_is_prepared(monkeypatch):
  client, _ = _client(monkeypatch)
  response = client.get("/api/diagnostics/status")
  status = response.get_json()
  assert response.status_code == 200 and response.headers["Cache-Control"].startswith("no-store")
  assert status["state"] == "idle" and status["drives_available"] == 1 and status["offroad"]
  assert client.get("/api/diagnostics/download").status_code == 404


def test_download_flow(monkeypatch):
  client, calls = _client(monkeypatch)
  response = client.post("/api/diagnostics/start", json={"action": "download", "note": "Starpilot Auto took 3 tries", "drives": 9})
  assert response.status_code == 202
  assert _settle(client)["state"] == "ready"
  assert calls["build"] == [("Starpilot Auto took 3 tries", diagnostics_bundle.MAX_DRIVES)] and calls["send"] == []
  download = client.get("/api/diagnostics/download")
  assert download.status_code == 200 and download.mimetype == "application/zip"
  assert "starpilot-diagnostics-tester-" in download.headers["Content-Disposition"]
  assert zipfile.ZipFile(io.BytesIO(download.data)).read("README.txt") == b"StarPilot diagnostics"
  download.close()


def test_send_flow_and_failed_send_can_still_download(monkeypatch):
  client, calls = _client(monkeypatch)
  assert client.post("/api/diagnostics/start", json={"action": "send", "note": "hi", "drives": 0}).status_code == 202
  status = _settle(client)
  assert status["state"] == "sent" and "Report sent" in status["message"] and calls["send"][0][1] == "hi"

  def offline(*_):
    raise RuntimeError("Could not send the report")

  client, _ = _client(monkeypatch, sender=offline)
  client.post("/api/diagnostics/start", json={"action": "send", "drives": 0})
  assert _settle(client)["state"] == "send_failed"
  assert client.get("/api/diagnostics/download").status_code == 200


def test_drive_reports_need_the_car_off_but_logs_can_go_anytime(monkeypatch):
  client, calls = _client(monkeypatch, onroad=True)
  response = client.post("/api/diagnostics/start", json={"action": "send", "drives": 1})
  assert response.status_code == 409 and "Turn the car off" in response.get_json()["error"]
  assert client.post("/api/diagnostics/start", json={"action": "send", "drives": 0}).status_code == 202
  _settle(client)
  assert calls["build"] == [("", 0)]


def test_bad_requests(monkeypatch):
  client, _ = _client(monkeypatch)
  assert client.post("/api/diagnostics/start", json={"action": "email"}).status_code == 400
  assert client.post("/api/diagnostics/start", json={"action": "send", "drives": "lots"}).status_code == 400


def test_logs_page_opens_on_the_starpilot_auto_tab():
  logs = (JS_ROOT / "views" / "Logs.js").read_text()
  panel = (JS_ROOT / "components" / "SendDiagnosticsPanel.js").read_text()
  api = (JS_ROOT / "api.js").read_text()
  assert logs.index('starpilotAuto: "Starpilot Auto"') < logs.index('troubleshoot: "Troubleshoot"'), "first tab is the default"
  assert "<SendDiagnosticsPanel />" in logs and "<StarpilotAutoDiagnosticsPanel />" in logs
  assert "Logs.js?v=send-diagnostics-3" in (JS_ROOT / "app.js").read_text()
  assert "Send report</button>" in panel
  assert "/api/diagnostics/start" in api and "/api/diagnostics/status" in api
  assert "/api/diagnostics/download" in panel and "fetch(" not in panel and "status.send_available" in panel
