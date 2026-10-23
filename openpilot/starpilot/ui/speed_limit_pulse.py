"""Speed-limit change highlight shared by both native layouts."""

import math

import pyray as rl

from openpilot.starpilot.ui.onroad_state import ObservationKind, OnroadState
from openpilot.starpilot.ui.unified_speed_presentation import displayed_limit_mps


CONFIRMATION_PURPLE = (170, 115, 235)
CONFIRMATION_PULSES = ((0.0, .7), (.9, .7), (2.6, .3), (3.1, .3))
CONFIRMATION_CYCLE_SECONDS = 4.4


class SpeedLimitPulse:
  def __init__(self):
    self.last_limit = 0.0
    self.start_time = -math.inf
    self.manual_pending = False
    self.display_pulsing = False
    self._started_frame: int | None = None

  def update(self, state: OnroadState, now: float, *, visible: bool = True) -> None:
    if state.drive_frame != self._started_frame:
      self.last_limit = 0.0
      self.display_pulsing = False
      self.start_time = -math.inf
      self._started_frame = state.drive_frame
    observation = state.speed_limit
    limit = displayed_limit_mps(observation)
    pending = (observation.kind == ObservationKind.VALID and observation.pending_speed_limit_mps is not None and
               observation.pending_speed_limit_mps > 0)
    if not visible or limit is None:
      self.start_time = -math.inf
      self.manual_pending = self.display_pulsing = False
      if limit is not None:
        self.last_limit = limit
      return
    if not pending:
      if (not observation.action_enabled and observation.kind == ObservationKind.VALID and
          limit != self.last_limit):
        self.start_time = now
        self.display_pulsing = True
      elif not self.display_pulsing or observation.action_enabled:
        self.start_time = -math.inf
        self.display_pulsing = False
      self.manual_pending = False
      self.last_limit = limit
      return
    self.display_pulsing = False
    manual = not observation.automatic_adoption_pending
    if observation.pending_since_ns > 0:
      self.start_time = observation.pending_since_ns / 1e9
    elif limit != self.last_limit or manual != self.manual_pending or not math.isfinite(self.start_time):
      self.start_time = now
    self.manual_pending = manual
    self.last_limit = limit

  def color(self, base: rl.Color, now: float) -> rl.Color:
    if isinstance(base, (tuple, list)):
      base = rl.Color(*base)
    elapsed = now - self.start_time
    if not math.isfinite(elapsed) or elapsed < 0:
      return base
    if self.manual_pending:
      phase = elapsed % CONFIRMATION_CYCLE_SECONDS
      fraction = 0.0
      for start, duration in CONFIRMATION_PULSES:
        if start <= phase < start + duration:
          fraction = math.sin(math.pi * (phase - start) / duration) ** 2
          break
      target = CONFIRMATION_PURPLE
    else:
      if elapsed >= 3.0:
        return base
      fraction = (1 - math.cos(2 * math.pi * elapsed)) / 2
      target = (188, 132, 255)
    return rl.Color(*(round(value + (target - value) * fraction)
                      for value, target in zip((base.r, base.g, base.b), target, strict=True)), base.a)
