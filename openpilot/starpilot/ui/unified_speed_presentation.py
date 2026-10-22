"""The selected set speed and latest received limit, shared by both layouts."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class UnifiedSpeedPresentation:
  mode: str
  max_text: str
  posted_text: str
  offset_text: str | None
  unit: str
  source: str
  pending: bool
  active_side: str
  limit_text: str
  status: str
  proposal_text: str

  @property
  def max_status(self) -> str:
    return 'Not set' if self.max_text == '–' else 'Set speed'

  @property
  def limit_status(self) -> str:
    return self.status


def positive(value):
  return value is not None and math.isfinite(value) and value > 0


def retaining_limit(observation):
  return (str(observation.kind) != 'valid' and bool(getattr(observation, 'session_id', None)) and
          (positive(observation.last_received_speed_limit_mps) or observation.action_enabled and
           positive(observation.accepted_speed_limit_mps) and positive(observation.effective_cluster_target_mps)))


def displayed_limit_mps(observation):
  if str(observation.kind) == 'valid':
    return observation.speed_limit_mps
  if positive(observation.last_received_speed_limit_mps):
    return observation.last_received_speed_limit_mps
  return observation.accepted_speed_limit_mps if retaining_limit(observation) else None


def displayed_adjusted_limit_mps(observation):
  posted = displayed_limit_mps(observation)
  if not positive(posted):
    return None
  if str(observation.kind) != 'valid' and positive(observation.last_received_adjusted_limit_mps):
    return observation.last_received_adjusted_limit_mps
  if str(observation.kind) == 'valid':
    for value in (getattr(observation, 'presentation_adjusted_limit_mps', None), getattr(observation, 'pending_adjusted_limit_mps', None)):
      if positive(value):
        return value
  if observation.accepted_speed_limit_mps == posted:
    for value in (getattr(observation, 'accepted_adjusted_limit_mps', None), observation.effective_cluster_target_mps):
      if positive(value):
        return value
  return posted + (observation.offset_mps or 0)


def resolve_unified_speed(state) -> UnifiedSpeedPresentation:
  obs = state.speed_limit
  factor = 3.6 if state.metric else 2.2369362921
  def speed(value):
    return str(round(value * factor)) if positive(value) else '–'
  posted = displayed_limit_mps(obs)
  target = displayed_adjusted_limit_mps(obs)
  pending = str(obs.kind) == 'valid' and positive(obs.pending_speed_limit_mps)
  show_max = state.customization.get('showMaxSpeed', True)
  has_slc = positive(posted) or str(obs.kind) == 'stale'
  mode = 'split' if show_max and has_slc else 'limit_only' if has_slc else 'max_only' if show_max else 'hidden'
  offset = None
  if state.show_slc_offset and positive(target) and positive(posted):
    adjustment = round(target * factor) - round(posted * factor)
    if adjustment:
      offset = f'{adjustment:+d}'
  status = 'Cruise off'
  if getattr(obs, 'status', '') == 'display_hold' or str(obs.kind) != 'valid' and positive(obs.last_received_speed_limit_mps):
    status = 'Unavailable'
  elif not obs.action_enabled:
    status = 'Display only'
  elif obs.driver_override_active:
    status = 'Set-speed override'
  elif pending:
    status = 'Adopting limit' if getattr(obs, 'automatic_adoption_pending', False) else 'Confirm speed limit'
  elif state.longitudinal_overridden:
    status = 'Using accelerator'
  elif state.cruise_active:
    status = 'Using set speed'
  max_text = speed(state.cruise_kph / 3.6) if positive(state.cruise_kph) else '–'
  source = obs.source if str(obs.kind) == 'valid' else (
    obs.last_received_source if positive(obs.last_received_speed_limit_mps) else obs.accepted_source)
  return UnifiedSpeedPresentation(mode, max_text, speed(posted), offset, 'km/h' if state.metric else 'mph',
                                  source, pending,
                                  'max' if state.cruise_active else 'none', speed(target), status,
                                  speed(getattr(obs, 'pending_adjusted_limit_mps', None) or obs.pending_speed_limit_mps) if pending else '–')
