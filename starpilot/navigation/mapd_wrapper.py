#!/usr/bin/env python3
from __future__ import annotations

import json
import signal
import subprocess
import time

from collections import defaultdict, deque
from pathlib import Path

MAPD_DIR = Path(__file__).resolve().parent
MAPD_BIN = MAPD_DIR / "mapd"
OFFLINE_ROOT = Path("/data/media/0/osm/offline")
RESTART_DELAY_S = 0.25
MISSING_TILE_BACKOFF_S = 30.0
FAILURE_WINDOW_S = 3.0
FAILURE_THRESHOLD = 3
MISSING_COVERAGE_EXIT_CODE = 3
WAIT_FOR_GPS_EXIT_CODE = 4
ROAD_STATE_POLL_S = 1.0
ACTIVITY_SUMMARY_S = 60.0
MAX_FORWARDED_LINES_PER_SUMMARY = 10


def _cloudlog():
  from openpilot.common.swaglog import cloudlog
  return cloudlog


def extract_bounds_filename(line: str) -> str | None:
  try:
    payload = json.loads(line)
  except json.JSONDecodeError:
    return None

  if payload.get("msg") != "Loading bounds file":
    return None

  filename = payload.get("filename")
  return filename if isinstance(filename, str) else None


def is_offline_read_error(line: str) -> bool:
  try:
    payload = json.loads(line)
  except json.JSONDecodeError:
    return False

  return payload.get("msg") == "could not unmarshal offline data"


def is_null_island_tile(filename: str) -> bool:
  try:
    min_lat, min_lon, max_lat, max_lon = (float(value) for value in Path(filename).name.split("_"))
  except (TypeError, ValueError):
    return False

  return min_lat <= 0 <= max_lat and min_lon <= 0 <= max_lon


class CorruptTileMonitor:
  def __init__(self, threshold: int = FAILURE_THRESHOLD, window_s: float = FAILURE_WINDOW_S):
    self.threshold = threshold
    self.window_s = window_s
    self.current_filename: str | None = None
    self.failures: dict[str, deque[float]] = defaultdict(deque)

  def observe(self, line: str, now: float | None = None) -> str | None:
    filename = extract_bounds_filename(line)
    if filename is not None:
      self.current_filename = filename
      return None

    if not is_offline_read_error(line) or self.current_filename is None:
      return None

    ts = time.monotonic() if now is None else now
    failures = self.failures[self.current_filename]
    failures.append(ts)

    cutoff = ts - self.window_s
    while failures and failures[0] < cutoff:
      failures.popleft()

    if len(failures) >= self.threshold:
      return self.current_filename
    return None


class MapdActivityLog:
  """Records in the drive log what mapd is doing; its own output is otherwise discarded.

  Logs each change of offline tile (a dense city tile makes every mapd loop slower), a
  per-minute count of tile loads (a tile re-read every loop), and mapd's warnings and
  errors, rate-limited.
  """

  def __init__(self, log=None, summary_s: float = ACTIVITY_SUMMARY_S, max_lines: int = MAX_FORWARDED_LINES_PER_SUMMARY):
    self._log = log
    self.summary_s = summary_s
    self.max_lines = max_lines
    self.tile: str | None = None
    self.window_start: float | None = None
    self.loads = 0
    self.forwarded = 0
    self.dropped = 0

  def _event(self, name: str, **values) -> None:
    (self._log or _cloudlog().event)(name, **values)

  def observe(self, line: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if self.window_start is None:
      self.window_start = now
    elif now - self.window_start >= self.summary_s:
      self._event("mapd_activity", tile=Path(self.tile).name if self.tile else None, tile_loads=self.loads,
                  window_s=round(now - self.window_start, 1), dropped_lines=self.dropped)
      self.window_start, self.loads, self.forwarded, self.dropped = now, 0, 0, 0

    filename = extract_bounds_filename(line)
    if filename is not None:
      self.loads += 1
      if filename != self.tile:
        self.tile = filename
        try:
          size = Path(filename).stat().st_size
        except OSError:
          size = None
        self._event("mapd_tile_loaded", tile=Path(filename).name, size_bytes=size)
      return

    try:
      payload = json.loads(line)
    except json.JSONDecodeError:
      return
    if not isinstance(payload, dict) or str(payload.get("level", "")).lower() not in ("warn", "warning", "error", "fatal", "panic"):
      return
    if self.forwarded >= self.max_lines:
      self.dropped += 1
      return
    self.forwarded += 1
    self._event("mapd_log", level=str(payload["level"]).lower(), msg=str(payload.get("msg", ""))[:200],
                error=str(payload.get("error", ""))[:200] or None)


def quarantine_offline_tile(filename: str) -> Path | None:
  tile_path = Path(filename)
  try:
    tile_path.relative_to(OFFLINE_ROOT)
  except ValueError:
    _cloudlog().warning(f"mapd_wrapper refusing to quarantine unexpected path: {filename}")
    return None

  if not tile_path.is_file():
    return None

  quarantined = tile_path.with_name(f"{tile_path.name}.corrupt.{time.monotonic_ns()}")
  try:
    tile_path.rename(quarantined)
  except OSError:
    _cloudlog().exception(f"mapd_wrapper failed to quarantine offline data: {tile_path}")
    return None
  return quarantined


def terminate_child(proc: subprocess.Popen[str]) -> None:
  if proc.poll() is not None:
    return

  proc.terminate()
  try:
    proc.wait(timeout=2)
  except subprocess.TimeoutExpired:
    proc.kill()
    try:
      proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
      _cloudlog().error(f"mapd_wrapper child did not exit after kill: pid={proc.pid}")


def run_mapd_once() -> int:
  try:
    OFFLINE_ROOT.mkdir(parents=True, exist_ok=True)
  except PermissionError:
    _cloudlog().exception(f"mapd_wrapper cannot create offline directory: {OFFLINE_ROOT}")
    return 2
  except OSError:
    _cloudlog().exception(f"mapd_wrapper failed to prepare offline directory: {OFFLINE_ROOT}")
    return 2

  proc = subprocess.Popen(
    [MAPD_BIN.as_posix()],
    cwd=MAPD_DIR,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
  )
  assert proc.stdout is not None

  def _handle_signal(signum, _frame):
    terminate_child(proc)
    raise SystemExit(128 + signum)

  signal.signal(signal.SIGTERM, _handle_signal)
  signal.signal(signal.SIGINT, _handle_signal)

  monitor = CorruptTileMonitor()
  activity = MapdActivityLog()

  for line in proc.stdout:
    print(line, end="")
    try:
      activity.observe(line)
    except Exception:
      pass  # diagnostics must never stop mapd
    bad_tile = monitor.observe(line)

    # mapd reports an unmarshal failure even when no offline tile is installed.
    # Stop its resulting hot loop until the next onroad process cycle.
    missing_tile = monitor.current_filename
    if is_offline_read_error(line) and missing_tile is not None and not Path(missing_tile).is_file():
      if is_null_island_tile(missing_tile):
        _cloudlog().info(f"mapd_wrapper received a location before GPS fix; waiting to restart mapd: {missing_tile}")
        terminate_child(proc)
        return WAIT_FOR_GPS_EXIT_CODE

      _cloudlog().info(f"mapd_wrapper has no offline tile for {missing_tile}; stopping mapd until the next drive")
      terminate_child(proc)
      return MISSING_COVERAGE_EXIT_CODE

    if bad_tile is None:
      continue

    quarantined = quarantine_offline_tile(bad_tile)
    if quarantined is None:
      if not OFFLINE_ROOT.exists():
        _cloudlog().warning(f"mapd_wrapper detected repeated offline read failures for {bad_tile}, but {OFFLINE_ROOT} does not exist; backing off mapd restarts")
        terminate_child(proc)
        return 2

      _cloudlog().warning(f"mapd_wrapper detected repeated offline read failures for {bad_tile}, but could not quarantine it")
    else:
      message = f"mapd_wrapper quarantined corrupt offline tile: {bad_tile} -> {quarantined}"
      print(message, flush=True)
      _cloudlog().warning(message)

    terminate_child(proc)
    return 1 if quarantined is not None else 2

  return proc.wait()


def wait_for_road_state_change(params: Params) -> None:
  initial_onroad = params.get_bool("IsOnroad")
  while params.get_bool("IsOnroad") == initial_onroad:
    time.sleep(ROAD_STATE_POLL_S)


def wait_for_gps_fix_or_road_state_change(params: Params, sm=None) -> None:
  initial_onroad = params.get_bool("IsOnroad")
  if sm is None:
    from cereal import messaging
    sm = messaging.SubMaster(["gpsLocationExternal"])

  while params.get_bool("IsOnroad") == initial_onroad:
    sm.update(1000)
    if sm.updated["gpsLocationExternal"] and sm["gpsLocationExternal"].hasFix:
      return


def main() -> None:
  from openpilot.common.params import Params

  params = Params()
  while True:
    exit_code = run_mapd_once()
    if exit_code == 1:
      time.sleep(RESTART_DELAY_S)
      continue
    if exit_code == 2:
      time.sleep(MISSING_TILE_BACKOFF_S)
      continue
    if exit_code == MISSING_COVERAGE_EXIT_CODE:
      wait_for_road_state_change(params)
      continue
    if exit_code == WAIT_FOR_GPS_EXIT_CODE:
      wait_for_gps_fix_or_road_state_change(params)
      continue
    raise SystemExit(exit_code)


if __name__ == "__main__":
  main()
