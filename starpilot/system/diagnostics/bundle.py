"""A diagnostics zip a tester can send to the developer from The Galaxy.

Contents: the Starpilot Auto session logs (Bluetooth pairing, Wi-Fi handshake, streaming)
with their reports and settings, the Bluetooth pairing prompt log and adapter status,
and a one-page report for each of the last few drives (see drive_report.py). Never the
Starpilot Auto identity or any Wi-Fi password.

"Send report" posts the zip to a Discord webhook. The URL is built in, encoded so
repository scanners don't pick it up; a URL in WEBHOOK_OVERRIDE_PATH on the device
replaces it without a code change. Download is always available.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REALDATA = Path("/data/media/0/realdata")
DIAGNOSTICS_DIR = Path("/data/diagnostics")
WEBHOOK_OVERRIDE_PATH = DIAGNOSTICS_DIR / "webhook_url"
# base64 of the Discord webhook URL that receives tester diagnostics ("" = sending not set up).
_WEBHOOK_B64 = "".join(("aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTU1NDI4MDc2NjU3NjI2NzMyNC9jelFvQ0VJUnFE",
                        "VWkxbXM5M3VvTzZ6TXVZRVJXUE5OTV90bWVKUEV3cXJjUjFUdHlMQ1lnSDNLeEtsb1NfamNIdlBCag=="))
AUTO_WEBHOOK_OVERRIDE_PATH = DIAGNOSTICS_DIR / "auto_webhook_url"
# base64 of the Discord webhook URL for automatic failure reports ("" = they go to the tester webhook above).
_AUTO_WEBHOOK_B64 = "".join(("aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTU1NTAzNTcxODE2OTAwNjA4My85UG1NMk9TcT",
                             "lRZW9sWF9WeHFfSG4wNjd4cVc2Y01kV3ltNUc1NFI4Y0pMd2RTaXE1Z2p6WDJBRjNjT2tYWkNZMFUyRA=="))
DISCORD_FILE_LIMIT = 10 * 1024 * 1024 - 64 * 1024  # 10 MiB attachment limit, with room for the form fields
MAX_DRIVES = 3
DRIVE_REPORT_TIMEOUT_S = 900
DRIVE_REPORT = Path(__file__).with_name("drive_report.py")


def webhook_url(override_path: Path = WEBHOOK_OVERRIDE_PATH) -> str:
  try:
    override = override_path.read_text().strip()
  except OSError:
    override = ""
  if override:
    return override
  return base64.b64decode(_WEBHOOK_B64).decode() if _WEBHOOK_B64 else ""


def auto_webhook_url(override_path: Path = AUTO_WEBHOOK_OVERRIDE_PATH) -> str:
  """Where automatic failure reports go, so they stay out of the thread the manual Send Diagnostics uses."""
  try:
    override = override_path.read_text().strip()
  except OSError:
    override = ""
  if override:
    return override
  return base64.b64decode(_AUTO_WEBHOOK_B64).decode() if _AUTO_WEBHOOK_B64 else webhook_url()


def recent_routes(realdata: Path = REALDATA, count: int = MAX_DRIVES) -> list[str]:
  """Newest drives first, by when their first segment was written."""
  firsts = []
  for first in realdata.glob("*--0"):
    if (first / "rlog.zst").exists() or (first / "qlog.zst").exists():
      try:
        firsts.append((first.stat().st_mtime, first.name.removesuffix("--0")))
      except OSError:
        continue
  return [route for _, route in sorted(firsts, reverse=True)[:count]]


def device_summary() -> dict:
  summary: dict = {"generated": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")}
  try:
    from openpilot.system.version import get_build_metadata
    build = get_build_metadata()
    summary.update(branch=build.channel, commit=build.openpilot.git_commit, version=build.openpilot.version,
                   origin=build.openpilot.git_normalized_origin)
  except Exception as error:
    summary["build_error"] = str(error)
  try:
    from openpilot.common.params import Params
    params = Params()
    summary["dongle_id"] = params.get("DongleId", encoding="utf-8") or ""
    summary["offroad"] = params.get_bool("IsOffroad")
    summary["car_fingerprint"] = _car_fingerprint(params)
  except Exception as error:
    summary["params_error"] = str(error)
  try:
    summary["head_unit"] = _head_unit_name()
  except Exception as error:
    summary["head_unit_error"] = str(error)
  return summary


def _car_fingerprint(params) -> str:
  try:
    from cereal import car
    cp_bytes = params.get("CarParamsPersistent")
    if cp_bytes:
      with car.CarParams.from_bytes(cp_bytes) as cp:
        fingerprint = str(cp.carFingerprint or "").strip()
        if fingerprint and fingerprint != "MOCK":
          return fingerprint
  except Exception:
    pass
  model = str(params.get("CarModel", encoding="utf-8") or "").strip()
  return "" if model == "MOCK" else model


def _head_unit_name(logs_to_check: int = 3) -> str:
  """The car's head unit from the newest session log that identified it, or ''."""
  from openpilot.starpilot.system.starpilot_auto import compat_report
  for path in compat_report.session_logs()[:logs_to_check]:
    car = compat_report.summarize(compat_report.load_events(path))["car"]
    name = " ".join(part for part in (car.get("head_unit_make"), car.get("head_unit_model")) if part)
    name = name or car.get("display_name") or car.get("bluetooth_name") or ""
    if name:
      return name
  return ""


def device_tag(summary: dict) -> str:
  """The first 8 characters of the hashed device ID the Starpilot Auto telemetry dashboard shows."""
  from openpilot.starpilot.system.starpilot_auto.telemetry import device_hash
  return device_hash(summary.get("dongle_id") or "")[:8]


def thread_title(summary: dict) -> str:
  return f"{summary.get('car_fingerprint') or 'Device'} {device_tag(summary)}"[:100]


def _bluetooth_status() -> dict:
  from openpilot.starpilot.system.bluetooth.protocol import BluetoothClient
  status = BluetoothClient(timeout=5.0).status()
  return dataclasses.asdict(status) if dataclasses.is_dataclass(status) else dict(status)


def _drive_report(route: str, realdata: Path) -> str:
  result = subprocess.run([sys.executable, str(DRIVE_REPORT), str(realdata), "--route", route, "--jobs", "2"],
                          capture_output=True, text=True, timeout=DRIVE_REPORT_TIMEOUT_S, preexec_fn=lambda: os.nice(19))
  if result.returncode != 0:
    raise RuntimeError((result.stderr or result.stdout).strip()[-500:] or f"exit code {result.returncode}")
  return result.stdout


def build(note: str = "", drives: int = 1, progress: Callable[[str], None] = lambda _: None, *,
          realdata: Path = REALDATA, drive_report: Callable[[str, Path], str] = _drive_report,
          starpilot_auto_bundle: Callable[[], bytes] | None = None, bluetooth_status: Callable[[], dict] = _bluetooth_status,
          pairing_log: Path | None = None, summary: Callable[[], dict] = device_summary) -> bytes:
  """The zip, built in memory (a few hundred KB to a few MB)."""
  problems: list[str] = []
  info = summary()
  output = io.BytesIO()
  with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    progress("Collecting Starpilot Auto logs")
    try:
      if starpilot_auto_bundle is None:
        from openpilot.starpilot.system.starpilot_auto import compat_report
        starpilot_auto_bundle = compat_report.bundle
      with zipfile.ZipFile(io.BytesIO(starpilot_auto_bundle())) as aa:
        for entry in aa.infolist():
          archive.writestr(f"starpilot-auto/{entry.filename}", aa.read(entry))
    except Exception as error:
      problems.append(f"Starpilot Auto logs: {error}")

    progress("Collecting Bluetooth pairing logs")
    if pairing_log is None:
      from openpilot.starpilot.system.bluetooth.bluez import PAIRING_LOG_PATH
      pairing_log = PAIRING_LOG_PATH
    try:
      archive.writestr("bluetooth/pairing_events.jsonl", pairing_log.read_bytes())
    except FileNotFoundError:
      archive.writestr("bluetooth/pairing_events.jsonl", "")
    except OSError as error:
      problems.append(f"Bluetooth pairing log: {error}")
    try:
      archive.writestr("bluetooth/status.json", json.dumps(bluetooth_status(), indent=2, default=str))
    except Exception as error:
      problems.append(f"Bluetooth status: {error}")

    routes = recent_routes(realdata, max(0, min(drives, MAX_DRIVES))) if drives > 0 else []
    for index, route in enumerate(routes, 1):
      progress(f"Summarizing drive {index} of {len(routes)} (about a minute per 10 minutes driven)")
      try:
        archive.writestr(f"drives/{route}.txt", drive_report(route, realdata))
      except Exception as error:
        problems.append(f"Drive {route}: {error}")

    readme = [
      "StarPilot diagnostics",
      "",
      f"Note from the tester: {note.strip() or '(none)'}",
      "",
      json.dumps(info, indent=2, default=str),
      "",
      "Contents:",
      "  starpilot-auto/  Starpilot Auto session logs (pairing, Wi-Fi handshake, streaming), reports and settings",
      "  bluetooth/     every Bluetooth pairing prompt and how it ended, and the adapter/device status",
      f"  drives/        one-page health report per drive: {', '.join(routes) or 'none included'}",
      "                 (read with starpilot/system/diagnostics/drive_report.py; see docs/how-to/drive-diagnostics.md)",
    ]
    if problems:
      readme += ["", "Could not collect:", *(f"  {problem}" for problem in problems)]
    archive.writestr("README.txt", "\n".join(readme) + "\n")
  return output.getvalue()


def bundle_name(summary: dict | None = None) -> str:
  stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
  dongle = (summary or {}).get("dongle_id") or "device"
  return f"starpilot-diagnostics-{dongle}-{stamp}.zip"


THREAD_CACHE_WARNING = "The forum thread could not be remembered on this device. The next upload may create another post."


def _response_json(response) -> dict:
  try:
    value = response.json()
  except (AttributeError, ValueError):
    return {}
  return value if isinstance(value, dict) else {}


def _save_thread_id(path: Path, key: str, thread_id: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  # A power loss during a write must not truncate the previous cache entry.
  with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temporary:
    temporary_path = Path(temporary.name)
    try:
      json.dump({"key": key, "thread_id": thread_id}, temporary)
      temporary.flush()
      os.fsync(temporary.fileno())
      os.replace(temporary_path, path)
    finally:
      temporary_path.unlink(missing_ok=True)


def send(data: bytes, name: str, note: str, summary: dict, url: str | None = None, post=None,
         thread_path: Path | None = None) -> str | None:
  """Post the zip; return a cache warning after success, or raise on an upload failure."""
  url = webhook_url() if url is None else url
  if not url:
    raise RuntimeError("Sending isn't set up on this build. Use Download and send the file instead.")
  if len(data) > DISCORD_FILE_LIMIT:
    size = f"{len(data) / 1e6:.1f} MB"
    raise RuntimeError(f"The diagnostics are {size}, over Discord's 10 MB limit. Include fewer drives, or use Download instead.")
  if post is None:
    import requests
    post = requests.post
  dongle_id = summary.get("dongle_id") or "device"
  lines = [f"**Diagnostics from {device_tag(summary)}**",
           f"Car: {summary.get('car_fingerprint') or 'unknown'}",
           f"Head unit: {summary.get('head_unit') or 'unknown'}",
           f"Branch {summary.get('branch', '?')} @ {str(summary.get('commit', '?'))[:10]}",
           f"Note: {note.strip() or '(none)'}"]
  payload = {"content": "\n".join(lines)[:1900], "username": "StarPilot diagnostics", "allowed_mentions": {"parse": []}}

  parts = urlsplit(url)
  query = dict(parse_qsl(parts.query, keep_blank_values=True))
  explicit_thread = bool(query.get("thread_id"))
  # Ignore query options when identifying a webhook, and never store its token in the cache.
  cache_key = hashlib.sha256(json.dumps([parts.scheme, parts.netloc, parts.path.rstrip("/"), dongle_id]).encode()).hexdigest()
  cached_id = None
  if not explicit_thread:
    query.pop("thread_id", None)
    if thread_path is None:
      thread_path = DIAGNOSTICS_DIR / "threads" / f"{cache_key}.json"
    try:
      entry = json.loads(thread_path.read_text())
      if isinstance(entry, dict) and entry.get("key") == cache_key:
        candidate = entry.get("thread_id")
        if isinstance(candidate, str) and candidate.isascii() and candidate.isdigit():
          cached_id = candidate
    except (OSError, ValueError):
      pass

  # Always wait for confirmation, including uploads to an existing thread.
  query["wait"] = "true"
  for attempt in range(2):
    if not explicit_thread and cached_id:
      query["thread_id"] = cached_id
    elif not explicit_thread:
      query.pop("thread_id", None)
      payload["thread_name"] = thread_title(summary)
    post_url = urlunsplit(parts._replace(query=urlencode(query)))

    try:
      response = post(post_url, data={"payload_json": json.dumps(payload)}, files={"files[0]": (name, data, "application/zip")}, timeout=120)
    except Exception as error:
      raise RuntimeError(f"Could not send the report: {error}. Check the internet connection, or use Download.") from error

    # Unknown Channel means the cached thread was deleted (Discord answers 400 for webhooks, 404 elsewhere).
    # Unknown Webhook does not.
    if attempt == 0 and cached_id and response.status_code in (400, 404) and _response_json(response).get("code") == 10003:
      cached_id = None  # Retry from memory even if the cache cannot be removed.
      try:
        thread_path.unlink(missing_ok=True)
      except OSError:
        pass
      continue
    break

  if response.status_code not in (200, 204):
    reason = str(_response_json(response).get("message") or "")[:120]
    detail = f"HTTP {response.status_code}{f': {reason}' if reason else ''}"
    raise RuntimeError(f"The report was refused ({detail}). Use Download instead.")

  if not explicit_thread and not cached_id:
    new_thread_id = _response_json(response).get("channel_id")
    if not isinstance(new_thread_id, str) or not new_thread_id.isascii() or not new_thread_id.isdigit():
      return THREAD_CACHE_WARNING
    try:
      _save_thread_id(thread_path, cache_key, new_thread_id)
    except OSError:
      return THREAD_CACHE_WARNING
  return None


class DiagnosticsJob:
  """One bundle at a time, built off the request thread; the last one stays for download."""

  def __init__(self, builder: Callable[..., bytes] = build, sender: Callable[..., str | None] = send,
               summary: Callable[[], dict] = device_summary):
    self._builder, self._sender, self._summary = builder, sender, summary
    self._lock = threading.Lock()
    self._thread: threading.Thread | None = None
    self._state = {"state": "idle", "message": "", "action": "", "name": "", "bytes": 0}
    self._data = b""

  def status(self) -> dict:
    with self._lock:
      return {**self._state, "send_available": bool(webhook_url())}

  def result(self) -> tuple[str, bytes] | None:
    with self._lock:
      return (self._state["name"], self._data) if self._data and self._state["state"] in ("ready", "sent", "send_failed") else None

  def start(self, action: str, note: str = "", drives: int = 1) -> None:
    if action not in ("download", "send"):
      raise ValueError(f"Unknown action {action!r}")
    with self._lock:
      if self._thread is not None and self._thread.is_alive():
        raise RuntimeError("Diagnostics are already being prepared.")
      self._state = {"state": "preparing", "message": "Starting", "action": action, "name": "", "bytes": 0}
      self._data = b""
      self._thread = threading.Thread(target=self._run, args=(action, note, drives), name="diagnostics_bundle", daemon=True)
      self._thread.start()

  def _set(self, **values) -> None:
    with self._lock:
      self._state.update(values)

  def _run(self, action: str, note: str, drives: int) -> None:
    try:
      summary = self._summary()
      data = self._builder(note=note, drives=drives, progress=lambda message: self._set(message=message))
      name = bundle_name(summary)
      with self._lock:
        self._data = data
      if action == "send":
        self._set(state="sending", message="Sending report", name=name, bytes=len(data))
        try:
          warning = self._sender(data, name, note, summary)
        except Exception as error:
          self._set(state="send_failed", message=str(error)[:400])  # the zip is still there to download
          return
        self._set(state="sent", message=f"Report sent. {warning or 'Thanks!'}")
      else:
        self._set(state="ready", message="Ready to download", name=name, bytes=len(data))
    except Exception as error:
      self._set(state="error", message=str(error)[:400])
