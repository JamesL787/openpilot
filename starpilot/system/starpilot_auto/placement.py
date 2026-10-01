"""Runs the car renderer on core 6 at the lowest priority.

Cores while driving (from drive logs, 2026-09-27):
  0-3  small cores, 75-95% busy: location, calibration, sensors, logging, vision helpers
  4    car interface, controls
  5    selfdrived, planner, the comma's own screen
  6    camera process, ~9% busy (6 and 7 are reserved at boot)
  7    driving model, driver monitoring model

Kept off 0-3: already near full, and they run the location and calibration checks.
Kept off 4, 5, 7: steering, planning and the models come first.
On 6: about 90% idle. The renderer was already landing there unpinned; now it's deliberate.

Safeguards:
- SCHED_IDLE, so the camera process always gets the core first. It has no special
  priority of its own, since it expects core 6 to itself (system/camerad/main.cc).
- Every renderer thread is placed, including ones the graphics driver starts later.
- Parked, power saving turns cores 4-7 off. The pin is re-applied every
  PLACEMENT_CHECK_INTERVAL seconds once core 6 is back, like selfdrive/ui/ui.py.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

RENDER_CORE = 6
PLACEMENT_CHECK_INTERVAL = 1.0  # s
FALLBACK_NICE = 10  # if SCHED_IDLE is unavailable


def _thread_ids() -> list[int]:
  try:
    return [int(tid) for tid in os.listdir("/proc/self/task")]
  except OSError:
    return [0]


def _core_online(core: int) -> bool:
  if core == 0:
    return True
  try:
    with open(f"/sys/devices/system/cpu/cpu{core}/online") as f:
      return f.read().strip() == "1"
  except OSError:
    return False


class RendererPlacement:
  """Keeps every renderer thread SCHED_IDLE on RENDER_CORE while that core is online."""

  def __init__(self, core: int = RENDER_CORE, report: Callable[[dict[str, Any]], None] | None = None,
               thread_ids: Callable[[], list[int]] = _thread_ids, core_online: Callable[[int], bool] = _core_online):
    self.core = core
    self.report = report or (lambda _event: None)
    self.thread_ids = thread_ids
    self.core_online = core_online
    self.next_check = 0.0
    self.pinned = False

  def start(self) -> None:
    """Call first, before any thread exists, so later threads inherit the policy."""
    inherited = sorted(os.sched_getaffinity(0))
    policy = "idle"
    try:
      os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
    except (AttributeError, OSError):
      policy = f"nice{FALLBACK_NICE}"
      try:
        os.nice(FALLBACK_NICE)
      except OSError:
        policy = "default"
    self.report({"event": "cpu_placement", "policy": policy, "inherited_cores": inherited, "core": self.core})
    self.maintain(0.0)

  def maintain(self, now: float) -> None:
    if now < self.next_check:
      return
    self.next_check = now + PLACEMENT_CHECK_INTERVAL
    if not self.core_online(self.core):
      if self.pinned:
        self.report({"event": "cpu_placement", "pinned": False, "reason": f"core {self.core} offline"})
      self.pinned = False
      return

    target = {self.core}
    changed = False
    for tid in self.thread_ids():
      try:
        if os.sched_getaffinity(tid) != target:
          os.sched_setaffinity(tid, target)
          changed = True
      except OSError:
        pass  # the thread exited
    if changed or not self.pinned:
      self.report({"event": "cpu_placement", "pinned": True, "cores": sorted(os.sched_getaffinity(0))})
    self.pinned = True
