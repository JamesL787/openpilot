"""Anonymous Starpilot Auto usage report: is it on, wired or wireless, and how its sessions ended.

Sent once per drive end and once per boot, alongside the existing StarPilot stats. It carries
only enums, counters, on/off flags for the CPU- and memory-heavy features, and the car/head-unit
identity strings; never logs, Bluetooth addresses, Wi-Fi credentials or the identity. The device is
identified by a hash of its dongle ID."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from openpilot.starpilot.system.starpilot_auto import identity as identity_store

SCHEMA = 1
TELEMETRY_URL = "https://telemetry.didesigns.fyi/v1/starpilot-auto/report"  # https endpoint that receives the report; "" = not sent
URL_OVERRIDE_PATH = identity_store.DATA_DIR / "telemetry_url"
STATE_PATH = identity_store.DATA_DIR / "telemetry.json"
DIAGNOSTICS_STATE_PATH = identity_store.DATA_DIR / "failure_diagnostics.json"
DIAGNOSTICS_KEY = "StarpilotAutoShareDiagnostics"  # on by default; the user turns it off in Settings
DIAGNOSTICS_WINDOW_S = 24 * 3600  # the same kind of failure is reported once per window, however often it repeats
DIAGNOSTICS_MAX_PER_WINDOW = 5    # and a device sends at most this many reports per window
DIAGNOSTICS_MAX_QUEUED = 10       # kinds of failure waiting for the car to be off
MAX_SESSIONS = 20
LOG_SETTLE_S = 120  # a log written this recently may still be a live session, unless it already ended
FINISHED_EVENT = '"event": "session_stop"'  # the daemon's last line in a finished session log
TIMEOUT_S = 10
# Features that each start their own background process, so they decide most of a device's CPU and memory use
# (measured on a C3X drive, 2026-09-30). Report key -> starpilot toggle.
HEAVY_FEATURES = {
  "speed_limit_vision": "vision_speed_limit_detection",  # speed_limit_vision: ~150 MB, 30-45% of a little core
  "blind_spot_vision": "v_asm_enabled",                  # adj_spot_monitor_vision: ~115 MB, ~30% of a little core
}


def heavy_features(toggles) -> dict[str, bool]:
  return {key: bool(getattr(toggles, name, False)) for key, name in HEAVY_FEATURES.items()}


def telemetry_url(override_path: Path = URL_OVERRIDE_PATH) -> str:
  try:
    override = override_path.read_text().strip()
  except OSError:
    override = ""
  return override or TELEMETRY_URL


def device_hash(dongle_id: str) -> str:
  return hashlib.sha256(f"starpilot-auto:{dongle_id}".encode()).hexdigest()[:32]


def _seconds(start: str, end: str) -> float | None:
  try:
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 1)
  except (TypeError, ValueError):
    return None


def _session_number(path: Path) -> int:
  match = re.fullmatch(r"session-(\d{6})-.*\.jsonl", path.name)
  return int(match[1]) if match else 0


CAR_ENDED = "Head unit ended projection"  # the car closed the projection itself, as it does when it is switched off
SAFE_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,40}")  # an enum-like word; anything with spaces, colons or quotes is dropped
VIDEO_MODE = re.compile(r"(\d+)x(\d+) @ (\d+) fps")


def _token(value) -> str | None:
  return value if isinstance(value, str) and SAFE_TOKEN.fullmatch(value) else None


def _count(value) -> int | None:
  return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 100_000 else None


def stage_timings(events: list[dict], started: str) -> list[list]:
  """[stage, seconds since the session started] for the first time each connection stage was entered."""
  from openpilot.starpilot.system.starpilot_auto.compat_report import STAGE_ORDER
  seen: dict[str, float | None] = {}
  for event in events:
    state = event.get("state")
    if event["event"] == "stage" and state in STAGE_ORDER and state not in seen:
      seen[state] = _seconds(started, event.get("t", ""))
  return [[stage, seconds] for stage, seconds in seen.items()]


def session_facts(report: dict) -> dict:
  """What the session established before it ended, as booleans, counters and enum-like words: where a failure sat, without a log."""
  bluetooth, wifi, tls, usb = report["bluetooth"], report["wifi"], report["tls"], report["usb"]
  mode = VIDEO_MODE.search(str(report["video"].get("chosen", "")))
  facts = {
    "hands_free": bluetooth.get("hands_free"),
    "rfcomm_channel": _count(bluetooth.get("rfcomm_channel")),
    "wifi_joined": wifi.get("joined"),
    "wifi_security": _token(wifi.get("security")),
    "tls_established": "version" in tls or None,
    "tls_version": _token(tls.get("version")),
    "tls_failed_reason": _token(tls.get("failed")),
    "auth_rejected_status": _count(tls.get("rejected_status")),
    "usb_started_as": _token(usb.get("started_as")),
    "usb_no_handshake_s": _count(int(usb["no_handshake_after_s"])) if isinstance(usb.get("no_handshake_after_s"), (int, float)) else None,
    "video_mode": f"{mode[1]}x{mode[2]}@{mode[3]}" if mode else None,
    "focus_lost": _count(report["focus"]["lost"]),
  }
  return {key: value for key, value in facts.items() if value is not None and (value is not False or key in ("hands_free", "wifi_joined"))}


def _finished(path: Path) -> bool:
  """True when the log's last line is the daemon's session_stop, so nothing more will be written to it."""
  with path.open("rb") as log:
    log.seek(0, os.SEEK_END)
    log.seek(max(0, log.tell() - 512))
    lines = log.read().decode(errors="replace").strip().splitlines()
  return bool(lines) and FINISHED_EVENT in lines[-1]


def session_record(path: Path) -> dict:
  """One session log reduced to enums and counters."""
  from openpilot.starpilot.system.starpilot_auto import compat_report
  events = compat_report.load_events(path)
  report = compat_report.summarize(events)
  started = events[0].get("t", "") if events else ""
  first_frame = next((event["t"] for event in events if event["event"] == "video_acknowledged"), "")
  # Once the car ends the projection (it was switched off), the reconnect attempts that follow are not drops.
  car_ended = next((index for index, event in enumerate(events) if first_frame and event["event"] == "session_ended"
                    and str(event.get("reason", "")).startswith(CAR_ENDED) and event.get("t", "") >= first_frame), None)
  failures = [event for index, event in enumerate(events) if event["event"] == "attempt_failed" and (car_ended is None or index < car_ended)]
  drops = [event for event in failures if first_frame and event.get("t", "") >= first_frame]

  if first_frame:
    outcome = "dropped" if drops else "streamed"
  elif failures:
    outcome = "failed"
  else:
    outcome = "stopped"

  car = report["car"]
  last_failure = failures[-1] if failures else {}
  record = {
    "seq": _session_number(path),
    "started": started,
    "transport": report["transport"],
    "trigger": report["trigger"],
    "outcome": outcome,
    "furthest_stage": report["furthest_stage"],
    "failed_stage": str(last_failure.get("stage", "")),
    "error_kind": str(last_failure.get("kind", "")),
    "failures": len(failures),
    "drops": len(drops),
    "time_to_first_frame_s": _seconds(started, first_frame) if first_frame else None,
    "streamed_s": _seconds(first_frame, events[-1].get("t", "")) if first_frame else None,
    "stages": stage_timings(events, started),
    "facts": session_facts(report),
    "head_unit": {key: car[key] for key in ("head_unit_make", "head_unit_model", "head_unit_software_version",
                                            "car_make", "car_model", "car_year") if car.get(key)},
  }
  if car_ended is not None:
    record["facts"]["ended_by_car"] = True
  return record


def _load_state(path: Path) -> dict:
  try:
    state = json.loads(path.read_text())
    return state if isinstance(state, dict) else {}
  except (OSError, ValueError):
    return {}


def _save_state(path: Path, state: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temporary:
    temporary_path = Path(temporary.name)
    try:
      json.dump(state, temporary)
      temporary.flush()
      os.fsync(temporary.fileno())
      os.replace(temporary_path, path)
    finally:
      temporary_path.unlink(missing_ok=True)


def build_report(enabled: bool, state: dict, summary: dict, connection: str, log_dir: Path,
                 device_generation: str, now: float | None = None, features: dict | None = None,
                 only_if_new: bool = False) -> dict | None:
  """The payload to send, or None when there is nothing to say (never used, or the disable was already reported).

  Sessions go oldest first, at most MAX_SESSIONS per report; the rest follow in the next report. With ``only_if_new``
  a report with no new sessions and no on/off change is not worth sending (the periodic retry uses this)."""
  last_enabled = state.get("last_enabled")
  if not enabled and last_enabled is not True:
    return None  # never turned on here, or the turn-off was already sent

  now = time.time() if now is None else now
  last_seq = int(state.get("last_seq", 0))
  sessions = []
  logs = sorted(log_dir.glob("session-*.jsonl"), key=identity_store.session_log_order)
  for path in logs:
    number = _session_number(path)
    if number <= last_seq:
      continue
    if len(sessions) >= MAX_SESSIONS:
      break  # the rest go in the next report
    try:
      if now - path.stat().st_mtime < LOG_SETTLE_S and not _finished(path):
        break  # still being written, and newer logs are newer still; report this one next time
      sessions.append(session_record(path))
    except OSError:
      continue

  event = "heartbeat" if last_enabled is enabled else "enabled" if enabled else "disabled"
  if only_if_new and event == "heartbeat" and not sessions:
    return None
  head_unit = next((s["head_unit"] for s in reversed(sessions) if s["head_unit"]), {})
  return {
    "schema": SCHEMA,
    "report_id": uuid.uuid4().hex,
    "device": device_hash(summary.get("dongle_id") or ""),
    "event": event,
    "enabled": enabled,
    "connection": connection,
    "device_generation": device_generation,
    "branch": summary.get("branch", ""),
    "commit": str(summary.get("commit", ""))[:10],
    "car_fingerprint": summary.get("car_fingerprint", ""),
    "head_unit": head_unit,
    "features": features or {},
    "sessions": sessions,
  }


def send_report(enabled: bool, summary: dict, connection: str, device_generation: str, url: str | None = None, post=None,
                state_path: Path = STATE_PATH, log_dir: Path | None = None, sent=None, features: dict | None = None,
                only_if_new: bool = False) -> bool:
  """Post the report if there is one; remember what was sent only after the server accepts it. ``sent`` gets the payload."""
  url = telemetry_url() if url is None else url
  if not url:
    return False
  state = _load_state(state_path)
  payload = build_report(enabled, state, summary, connection, log_dir or identity_store.LOG_DIR, device_generation, features=features,
                         only_if_new=only_if_new)
  if payload is None:
    return False
  if post is None:
    import requests
    post = requests.post
  response = post(url, json=payload, timeout=TIMEOUT_S, headers={"User-Agent": "starpilot-auto-telemetry/1"})
  if not 200 <= response.status_code < 300:
    raise RuntimeError(f"telemetry endpoint answered HTTP {response.status_code}")
  last_seq = max([int(state.get("last_seq", 0)), *(session["seq"] for session in payload["sessions"])])
  _save_state(state_path, {"last_enabled": enabled, "last_seq": last_seq})
  if sent is not None:
    sent(payload)
  return True


def failure_signature(session: dict) -> str:
  """What kind of failure a session had: its outcome, where it stopped and the error class."""
  return f"{session['outcome']}:{session['failed_stage'] or session['furthest_stage'] or 'start'}:{session['error_kind'] or 'none'}"


def failed_sessions(payload: dict) -> list[dict]:
  """The failed or dropped sessions in a report, newest first."""
  return [s for s in reversed(payload["sessions"]) if s["outcome"] in ("failed", "dropped")]


def send_failure_diagnostics(payload: dict, summary: dict, state_path: Path = DIAGNOSTICS_STATE_PATH, now: float | None = None,
                             builder=None, sender=None, car_off: bool = True) -> bool:
  """Send the developer the diagnostics report without drives for each kind of failure not sent in the last day.

  New kinds in ``payload`` are queued first, so one found while driving, or one whose upload failed, waits for the next
  upload instead of being lost. Uploads happen only with the car off: nobody reads them mid-drive, and building the bundle
  is work the comma should not do then. Queued kinds share one upload. A kind already sent within the window is skipped,
  and a device sends at most DIAGNOSTICS_MAX_PER_WINDOW reports per window, so a connection stuck in a retry loop cannot
  flood the channel."""
  now = time.time() if now is None else now
  state = _load_state(state_path)
  sent = {key: float(at) for key, at in (state.get("sent") or {}).items()
          if isinstance(at, (int, float)) and 0 <= now - at < DIAGNOSTICS_WINDOW_S}
  uploads = [float(at) for at in state.get("uploads") or [] if isinstance(at, (int, float)) and 0 <= now - at < DIAGNOSTICS_WINDOW_S]
  saved_queue = state.get("queued") or {}
  queued = {key: kind for key, kind in saved_queue.items() if isinstance(kind, str) and key not in sent}
  for session in failed_sessions(payload):
    signature = failure_signature(session)
    if signature not in sent and signature not in queued and len(queued) < DIAGNOSTICS_MAX_QUEUED:
      queued[signature] = f"{session['outcome']} at {session['failed_stage'] or session['furthest_stage'] or 'start'} ({session['error_kind'] or 'no error'})"
  if queued != saved_queue:
    _save_state(state_path, {"sent": sent, "uploads": uploads, "queued": queued})
  if not queued or not car_off or len(uploads) >= DIAGNOSTICS_MAX_PER_WINDOW:
    return False

  if builder is None or sender is None:
    from openpilot.starpilot.system.diagnostics import bundle
    builder, sender = builder or bundle.build, sender or bundle.send
  from openpilot.starpilot.system.diagnostics.bundle import auto_webhook_url, bundle_name
  kinds = list(queued.values())
  note = f"Automatic report, new failure{'s' if len(kinds) > 1 else ''}: {'; '.join(kinds)}. No drives included."
  sender(builder(note=note, drives=0), bundle_name(summary), note, summary, url=auto_webhook_url())
  _save_state(state_path, {"sent": {**sent, **dict.fromkeys(queued, now)}, "uploads": [*uploads, now], "queued": {}})
  return True


def send_auto_telemetry(toggles=None, only_if_new: bool = False, car_off: bool = True) -> None:
  """Report Starpilot Auto use. Called at drive end, after boot, and every few minutes with ``only_if_new`` so sessions
  still go out when the comma loses power with the car or had no internet earlier. ``toggles`` saves a settings reload.
  Failure diagnostics found with the car on are queued and uploaded at the next call with ``car_off``."""
  try:
    if not telemetry_url():
      return
    from openpilot.common.params import Params
    from openpilot.system.hardware import HARDWARE
    from openpilot.starpilot.common.starpilot_variables import get_starpilot_toggles
    from openpilot.starpilot.system.diagnostics.bundle import device_summary
    from openpilot.starpilot.system.starpilot_stats import get_device_generation

    params = Params()
    summary = device_summary()

    share_diagnostics = params.get_bool(DIAGNOSTICS_KEY)

    def share_failure(payload):
      if share_diagnostics:
        try:
          send_failure_diagnostics(payload, summary, car_off=car_off)
        except Exception as error:
          print(f"Failed to send Starpilot Auto failure diagnostics: {error}")

    reported = send_report(params.get_bool(identity_store.ENABLED_KEY), summary, identity_store.load_config()["connection"],
                get_device_generation(HARDWARE.get_device_type()), sent=share_failure,
                features=heavy_features(toggles or get_starpilot_toggles()), only_if_new=only_if_new)
    if share_diagnostics and car_off and not reported:
      share_failure({"sessions": []})  # nothing new to report, but failures queued while driving still go out
  except Exception as error:
    print(f"Failed to send Starpilot Auto telemetry: {error}")
