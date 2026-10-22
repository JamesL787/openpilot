"""Speed-limit change highlight shared by both native layouts."""

import math

import pyray as rl

from openpilot.starpilot.ui.onroad_state import OnroadState
from openpilot.starpilot.ui.unified_speed_presentation import displayed_limit_mps


class SpeedLimitPulse:
  def __init__(self):
    self.last_limit = 0.0
    self.start_time = -math.inf
    self._started_frame: int | None = None

  def update(self, state: OnroadState, now: float, *, visible: bool = True) -> None:
    if state.drive_frame != self._started_frame:
      self.last_limit = 0.0
      self.start_time = -math.inf
      self._started_frame = state.drive_frame
    observation = state.speed_limit
    if not visible:
      self.start_time = -math.inf
      return
    limit = displayed_limit_mps(observation)
    if limit is None:
      return
    if observation.automatic_adoption_pending and observation.pending_since_ns > 0:
      self.start_time = observation.pending_since_ns / 1e9
    elif observation.automatic_adoption_pending and limit != self.last_limit:
      self.start_time = now
    elif not observation.automatic_adoption_pending:
      self.start_time = -math.inf
    self.last_limit = limit

  def color(self, base: rl.Color, now: float) -> rl.Color:
    if isinstance(base, (tuple, list)):
      base = rl.Color(*base)
    elapsed = now - self.start_time
    if not 0.0 <= elapsed < 3.0:
      return base
    fraction = (1 - math.cos(2 * math.pi * elapsed)) / 2
    return rl.Color(*(round(value + (target - value) * fraction)
                      for value, target in zip((base.r, base.g, base.b), (188, 132, 255), strict=True)), base.a)
