"""How the Starpilot Auto car view lays out the drive: settings from The Galaxy.

Kept in its own file beside config.json because the Starpilot Auto supervisor
rewrites config.json from memory during a session; these settings change while
connected and car_ui re-reads them within a second, so they apply live.
"""

from __future__ import annotations

import json
import fcntl
import math
import os
import tempfile
import time
from pathlib import Path

from openpilot.starpilot.system.starpilot_auto.identity import DATA_DIR

CAR_SCREEN_PATH = DATA_DIR / "car_screen.json"
ONROAD_VIEWS = ("split", "driving", "map")  # map + driving view, driving view only, map only
MAP_SIDES = ("right", "left")
DIRECTIONS_SIDES = ("right", "left")  # the driving view's next-turn card, when the map isn't beside it
MAP_ORIENTATIONS = ("north_up", "heading_up")
MAX_BLIND_SPOT_SPEED_MS = 60.0
STATUS_METRICS = {
  "acceleration": (1, "Current Acceleration"),
  "max_acceleration": (2, "Maximum Acceleration"),
  "steer_delay": (3, "Steering Delay"),
  "friction": (4, "Friction"),
  "lateral_acceleration": (5, "Lateral Acceleration"),
  "steer_ratio": (6, "Steer Ratio"),
  "stiffness": (7, "Stiffness Factor"),
  "lateral_engagement": (8, "Lateral Engagement %"),
  "longitudinal_engagement": (9, "Longitudinal Engagement %"),
  "steering_angle": (10, "Steering Angle"),
  "torque": (11, "Torque Used"),
  "actuator_acceleration": (12, "Actuator Acceleration"),
  "danger_factor": (13, "MPC Danger Factor"),
  "acceleration_jerk": (14, "Acceleration Jerk"),
  "danger_jerk": (15, "Danger Jerk"),
  "speed_jerk": (16, "Speed Jerk"),
  "model": (17, "Model Name"),
  "cpu": (18, "CPU Usage"),
  "gpu": (19, "GPU Usage"),
  "temperature": (20, "Temperature"),
  "memory": (21, "Memory Usage"),
  "storage": (22, "Free Storage"),
  "starpilot_logo": (23, "StarPilot Logo"),
  "clock": (24, "Clock"),
  "bookmark": (25, "Bookmark Button"),  # tap to bookmark the drive
  "blank": (-1, "Blank"),  # keeps its place in the column, draws nothing
}
STATUS_SLOT_COUNT = 7
# Where the status column goes in each driving layout. In the split view "center" puts it
# between the driving view and the map; it always takes its width from the driving view.
STATUS_POSITIONS = {
  "split": ("left", "center", "right"),
  "driving": ("left", "right"),
  "map": ("left", "right"),
}
# What wakes the comma's display while it sleeps for Starpilot Auto (the Standby wake keys).
# Critical / takeover alerts always wake it and are not listed.
SLEEP_WAKE_EVENTS = {
  "StandbyWakeWarningAlert": "Warning alerts",
  "StandbyWakeInfoAlert": "Informational alerts",
  "StandbyWakeEngage": "Engagement",
  "StandbyWakeDisengage": "Disengagement",
  "StandbyWakeTurnSignal": "Turn signals",
  "StandbyWakeButton": "Steering wheel or Bluetooth button",
}


def device_sleep_default(device_type: str) -> bool:
  """Whether the comma's display turns off during Starpilot Auto unless the user chooses otherwise:
  on by default on comma four; available on comma 3X (tizi, and the older tici) but off by default,
  since its larger screen stays useful beside the car's."""
  return device_type not in ("tizi", "tici")


def _device_type() -> str:
  try:
    from openpilot.system.hardware import HARDWARE
    return HARDWARE.get_device_type()
  except Exception:
    return "pc"


DEFAULTS = {
  "onroad_view": "split",
  "map_side": "right",
  "directions_side": "right",
  "map_orientation": "north_up",
  "camera": True,
  "blind_spot_monitors": True,
  "blind_spot_min_speed_ms": 0.0,
  "sleep_device_screen": device_sleep_default(_device_type()),
  # Set once the user picks sleep on or off. Files from before the 3X had a choice saved the old
  # default (on) without meaning it, so on a 3X a saved "on" only counts when it was chosen.
  "sleep_device_screen_set": False,
  "sleep_wake_events": ["StandbyWakeWarningAlert"],
  "show_current_speed": True,
  "show_status_column": True,
  "status_slots": ["steer_delay", "friction", "cpu", "gpu", "temperature", "memory", "starpilot_logo"],
  "status_position_split": "right",
  "status_position_driving": "right",
  "status_position_map": "right",
}
RELOAD_SECONDS = 1.0
# Set by tools/starpilot_auto/dhu_device.py for a Desktop Head Unit session; the car view
# then treats the car as below the 10 mph destination lock.
DHU_ENV = "STARPILOT_STARPILOT_AUTO_DHU"


def default_settings() -> dict:
  """Return settings whose mutable values are independent of ``DEFAULTS``."""
  return {**DEFAULTS, "status_slots": list(DEFAULTS["status_slots"]), "sleep_wake_events": list(DEFAULTS["sleep_wake_events"])}


def normalize(raw: object) -> dict:
  settings = default_settings()
  if isinstance(raw, dict):
    if raw.get("onroad_view") in ONROAD_VIEWS:
      settings["onroad_view"] = raw["onroad_view"]
    if raw.get("map_side") in MAP_SIDES:
      settings["map_side"] = raw["map_side"]
    if raw.get("directions_side") in DIRECTIONS_SIDES:
      settings["directions_side"] = raw["directions_side"]
    if raw.get("map_orientation") in MAP_ORIENTATIONS:
      settings["map_orientation"] = raw["map_orientation"]
    if isinstance(raw.get("camera"), bool):
      settings["camera"] = raw["camera"]
    if isinstance(raw.get("blind_spot_monitors"), bool):
      settings["blind_spot_monitors"] = raw["blind_spot_monitors"]
    # Files saved before the wake choices existed stored the old default (awake); the device's default applies now.
    if isinstance(raw.get("sleep_device_screen_set"), bool):
      settings["sleep_device_screen_set"] = raw["sleep_device_screen_set"]
    saved_sleep = raw.get("sleep_device_screen")
    if isinstance(saved_sleep, bool) and "sleep_wake_events" in raw and \
       (not saved_sleep or settings["sleep_device_screen"] or settings["sleep_device_screen_set"]):
      settings["sleep_device_screen"] = saved_sleep
    wake_events = raw.get("sleep_wake_events")
    if isinstance(wake_events, list) and all(isinstance(event, str) and event in SLEEP_WAKE_EVENTS for event in wake_events) and \
       len(set(wake_events)) == len(wake_events):
      settings["sleep_wake_events"] = list(wake_events)
    if isinstance(raw.get("show_current_speed"), bool):
      settings["show_current_speed"] = raw["show_current_speed"]
    if isinstance(raw.get("show_status_column"), bool):
      settings["show_status_column"] = raw["show_status_column"]
    for view, positions in STATUS_POSITIONS.items():
      if raw.get(f"status_position_{view}") in positions:
        settings[f"status_position_{view}"] = raw[f"status_position_{view}"]
    status_slots = raw.get("status_slots")
    if isinstance(status_slots, list) and len(status_slots) == STATUS_SLOT_COUNT - 1:
      # Saved before the seventh slot existed: keep the six, add the default seventh.
      status_slots = [*status_slots, DEFAULTS["status_slots"][-1]]
    if isinstance(status_slots, list) and len(status_slots) == STATUS_SLOT_COUNT and \
       all(isinstance(slot, str) and slot in STATUS_METRICS for slot in status_slots):
      settings["status_slots"] = list(status_slots)
    minimum_speed = raw.get("blind_spot_min_speed_ms")
    if isinstance(minimum_speed, (int, float)) and not isinstance(minimum_speed, bool) and math.isfinite(minimum_speed):
      if 0.0 <= minimum_speed <= MAX_BLIND_SPOT_SPEED_MS:
        settings["blind_spot_min_speed_ms"] = float(minimum_speed)
  return settings


def blind_spot_monitors_visible(settings: dict, speed_ms: float | None) -> bool:
  """Whether Starpilot Auto-specific blind-spot visuals should be drawn at this speed."""
  if not settings.get("blind_spot_monitors", True):
    return False
  minimum = float(settings.get("blind_spot_min_speed_ms", 0.0))
  return minimum <= 0.0 or (speed_ms is not None and speed_ms >= minimum)


def load(path: Path | None = None) -> dict:
  try:
    return normalize(json.loads((path or CAR_SCREEN_PATH).read_text()))
  except (OSError, ValueError):
    return default_settings()


def save(settings: dict, path: Path | None = None) -> dict:
  path = path or CAR_SCREEN_PATH
  clean = normalize(settings)
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".car-screen-")
  try:
    with os.fdopen(fd, "w") as handle:
      json.dump(clean, handle, indent=2)
    os.replace(temporary, path)
  except BaseException:
    try:
      os.unlink(temporary)
    except OSError:
      pass
    raise
  return clean


def update(change: dict, path: Path | None = None) -> dict:
  """Merge a change under a process-shared lock for Galaxy and the car UI."""
  path = path or CAR_SCREEN_PATH
  path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  with path.with_suffix('.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    if "sleep_device_screen" in change:
      change = {**change, "sleep_device_screen_set": True}
    merged = {**load(path), **change}
    if set(change) - DEFAULTS.keys() or normalize(merged) != merged:
      raise ValueError('Unknown or invalid car screen setting.')
    return save(merged, path)


class CarScreenSettings:
  """The current settings, re-read when the file changes (checked about once a second)."""

  def __init__(self, path: Path | None = None, clock=time.monotonic):
    self.path = path or CAR_SCREEN_PATH
    self._clock = clock
    self._checked = -RELOAD_SECONDS
    self._stamp: tuple | None = None
    self.current = default_settings()

  def poll(self) -> dict:
    now = self._clock()
    if now - self._checked < RELOAD_SECONDS:
      return self.current
    self._checked = now
    try:
      stat = self.path.stat()
      stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
      stamp = None
    if stamp != self._stamp:
      self._stamp = stamp
      self.current = load(self.path) if stamp is not None else default_settings()
    return self.current
