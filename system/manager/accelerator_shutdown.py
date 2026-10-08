import time
from collections.abc import Callable

from openpilot.common.swaglog import cloudlog
from openpilot.starpilot import jetlink_adapter

# How long a power-off waits for the external accelerator to take its shutdown request. Waking a sleeping host and one
# round trip take ~10 s; a host that never answers must not keep the comma on
TIMEOUT = 25.0


def _mark_powering_off(value: bool) -> None:
  from openpilot.common.params import Params
  Params().put_bool("JetlinkPoweringOff", value)


class AcceleratorShutdown:
  """Bounded wait for an attached accelerator (Jetlink's Jetson/Mac) to power off with the comma.

  An accelerator on its own supply outlives the comma: it is asked once, through jetlinkd, which is why this runs in
  manager (jetlinkd is stopped by manager's cleanup, right after) and why it covers every DoShutdown writer, not only
  hardwared's power monitor: the UI's power-off buttons write the param directly. manager keeps its loop running while
  the request is pending, so jetlinkd and the other processes stay up to carry it.

  ready() is called on every manager loop while a shutdown is requested and returns True when the device may go down: at
  once with nothing to ask (link off, Chestnut, no host known to be there), when jetlinkd has taken the request, or after
  TIMEOUT. Never raises."""

  def __init__(self, request: Callable[[str], bool] = jetlink_adapter.request_shutdown,
               pending: Callable[[], bool] = jetlink_adapter.shutdown_pending,
               clock: Callable[[], float] = time.monotonic, timeout: float = TIMEOUT,
               mark: Callable[[bool], None] | None = None):
    # `mark(True)` while the wait is on: hardwared reads it so no drive starts under the power-off that follows
    self._mark = mark if mark is not None else _mark_powering_off
    self._request = request
    self._pending = pending
    self._clock = clock
    self._timeout = timeout
    self._asked_at: float | None = None
    self._waiting = False

  def ready(self, reason: str = "") -> bool:
    now = self._clock()
    if self._asked_at is None:
      self._asked_at = now
      try:
        self._waiting = bool(self._request(reason))
      except Exception:
        cloudlog.exception("accelerator shutdown request failed")
        self._waiting = False
      if self._waiting:
        cloudlog.warning(f"shutdown waits up to {self._timeout:.0f} s for the accelerator to power off: {reason}")
        self._set_mark(True)
    if not self._waiting:
      return True
    try:
      still_pending = bool(self._pending())
    except Exception:
      still_pending = False
    # the mark stays set on every way out: the device is going down, and nothing may start between here and power-off
    if not still_pending:
      return True
    if now - self._asked_at >= self._timeout:
      cloudlog.error(f"accelerator did not take the shutdown request within {self._timeout:.0f} s, shutting down anyway")
      return True
    return False

  def _set_mark(self, value: bool) -> None:
    try:
      self._mark(value)
    except Exception:
      cloudlog.exception("could not publish the accelerator power-off wait")
