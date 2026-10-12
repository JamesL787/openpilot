"""D-111 / D-112: mid-drive traffic re-check, the faster-route switch policy, and congestion ahead on the route.

Our own implementation. The switch rules follow IQ.Pilot's TrafficReroutePolicy where its constants were readable in
the shipped binary (500 m maneuver guard, 2 confirmations, 10 % savings, 15 s retry base); the values marked "ours"
were not recoverable there and are our choice. Nothing here switches a route by itself: a "switch" decision only
raises a prompt, and the route changes only when the driver accepts it on screen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TRAFFIC_REFRESH_INTERVAL_S = 120.0      # ours
TRAFFIC_CONFIRM_RECHECK_S = 30.0        # ours: re-check sooner once a candidate qualifies, to confirm it
TRAFFIC_RETRY_BASE_S = 15.0             # IQ.Pilot
TRAFFIC_RETRY_MAX_S = 240.0             # ours
TRAFFIC_MANEUVER_GUARD_M = 500.0        # IQ.Pilot: never offer a new route this close to the next maneuver
TRAFFIC_SWITCH_CONFIRMATIONS = 2        # IQ.Pilot
TRAFFIC_SWITCH_MIN_SAVINGS_RATIO = 0.10  # IQ.Pilot
TRAFFIC_SWITCH_MIN_SAVINGS_S = 120.0    # ours
TRAFFIC_SWITCH_COOLDOWN_S = 600.0       # ours: after the driver accepts or declines
TRAFFIC_PROMPT_TIMEOUT_S = 20.0         # ours: no answer keeps the current route

# Two routes are "the same" when nearly every sampled point of one lies on the other
SAME_ROUTE_SAMPLE_M = 50.0
SAME_ROUTE_CELL_DEG = 0.0005            # ~55 m of latitude
SAME_ROUTE_FRACTION = 0.90

# D-112: Mapbox congestion levels that count as a jam, and how far ahead we look for one
JAM_LEVELS = ("heavy", "severe")
JAM_LOOKAHEAD_M = 2000.0
JAM_MIN_LENGTH_M = 150.0                # shorter runs are usually a signal queue, not a jam
JAM_DATA_MAX_AGE_S = 600.0              # older congestion data is not used
JAM_MAX_ROUTE_OFFSET_M = 40.0           # the car must be on the route the data came from


def retry_delay_s(failures: int) -> float:
  return min(TRAFFIC_RETRY_BASE_S * (2.0 ** max(failures - 1, 0)), TRAFFIC_RETRY_MAX_S)


def _sample_points(geometry, cumulative, start_m: float = 0.0, step_m: float = SAME_ROUTE_SAMPLE_M):
  """Points every step_m along a polyline, from start_m to its end."""
  if not geometry:
    return []
  if len(geometry) == 1:
    return [geometry[0]]
  out = []
  target = max(start_m, 0.0)
  seg = 0
  end = cumulative[-1]
  while target <= end:
    while seg < len(geometry) - 2 and cumulative[seg + 1] < target:
      seg += 1
    length = cumulative[seg + 1] - cumulative[seg]
    t = 0.0 if length <= 0.0 else min(max((target - cumulative[seg]) / length, 0.0), 1.0)
    a, b = geometry[seg], geometry[seg + 1]
    out.append(type(a)(a.latitude + (b.latitude - a.latitude) * t, a.longitude + (b.longitude - a.longitude) * t))
    target += step_m
  return out


def _cell(point) -> tuple[int, int]:
  return int(math.floor(point.latitude / SAME_ROUTE_CELL_DEG)), int(math.floor(point.longitude / SAME_ROUTE_CELL_DEG))


def route_overlap_fraction(candidate, reference, reference_start_m: float = 0.0) -> float:
  """Share of the candidate's sampled points that fall within one grid cell of the reference route's remaining part
  (from reference_start_m on). 1.0 means the candidate drives the same roads."""
  ref_points = _sample_points(reference.geometry, reference.geometry_cumulative_distances, reference_start_m, SAME_ROUTE_SAMPLE_M / 2.0)
  if not ref_points:
    return 0.0
  cells = set()
  for point in ref_points:
    lat, lon = _cell(point)
    for dlat in (-1, 0, 1):
      for dlon in (-1, 0, 1):
        cells.add((lat + dlat, lon + dlon))
  cand_points = _sample_points(candidate.geometry, candidate.geometry_cumulative_distances)
  if not cand_points:
    return 0.0
  return sum(_cell(point) in cells for point in cand_points) / len(cand_points)


def same_route(candidate, reference, reference_start_m: float = 0.0) -> bool:
  return route_overlap_fraction(candidate, reference, reference_start_m) >= SAME_ROUTE_FRACTION


@dataclass(frozen=True)
class TrafficDecision:
  reason: str          # cooldown | maneuver_guard | same_route | insufficient_savings | awaiting_confirmation | switch
  savings_s: float = 0.0
  confirmations: int = 0


class TrafficReroutePolicy:
  """Decides when a faster candidate is worth offering. One evaluate() per traffic check."""

  def __init__(self) -> None:
    self._confirmations = 0
    self._cooldown_until = -math.inf

  def reset_candidate(self) -> None:
    self._confirmations = 0

  def mark_answered(self, now: float) -> None:
    """The driver accepted or declined (or let the prompt time out): no new offer for the cooldown."""
    self._confirmations = 0
    self._cooldown_until = now + TRAFFIC_SWITCH_COOLDOWN_S

  def in_cooldown(self, now: float) -> bool:
    return now < self._cooldown_until

  def evaluate(self, now: float, current_duration_s: float, candidate_duration_s: float | None,
               next_maneuver_distance_m: float, matches_previous_candidate: bool) -> TrafficDecision:
    if self.in_cooldown(now):
      self.reset_candidate()
      return TrafficDecision("cooldown")
    if next_maneuver_distance_m < TRAFFIC_MANEUVER_GUARD_M:
      self.reset_candidate()
      return TrafficDecision("maneuver_guard")
    if candidate_duration_s is None:
      self.reset_candidate()
      return TrafficDecision("same_route")

    savings = current_duration_s - candidate_duration_s
    if savings < max(TRAFFIC_SWITCH_MIN_SAVINGS_S, TRAFFIC_SWITCH_MIN_SAVINGS_RATIO * current_duration_s):
      self.reset_candidate()
      return TrafficDecision("insufficient_savings", savings)

    self._confirmations = self._confirmations + 1 if matches_previous_candidate and self._confirmations > 0 else 1
    if self._confirmations < TRAFFIC_SWITCH_CONFIRMATIONS:
      return TrafficDecision("awaiting_confirmation", savings, self._confirmations)
    return TrafficDecision("switch", savings, self._confirmations)


def congestion_ahead(route, along_m: float, lookahead_m: float = JAM_LOOKAHEAD_M) -> tuple[float, float] | None:
  """(distance to the start of the first jam within lookahead_m, Mapbox typical speed there in m/s) or None.

  A jam is a run of JAM_LEVELS congestion at least JAM_MIN_LENGTH_M long. Annotations are per geometry segment.
  The speed is the slowest positive per-segment speed in the run, or 0.0 when Mapbox gave none."""
  congestion = getattr(route, "congestion", None) or []
  speeds = getattr(route, "segment_speeds", None) or []
  cumulative = route.geometry_cumulative_distances
  segments = min(len(congestion), len(cumulative) - 1)
  run_start = None
  run_speed = math.inf
  for index in range(segments):
    seg_start, seg_end = cumulative[index], cumulative[index + 1]
    if seg_end <= along_m:
      continue
    if seg_start - along_m > lookahead_m and run_start is None:
      break
    if congestion[index] in JAM_LEVELS:
      if run_start is None:
        run_start = max(seg_start, along_m)
        run_speed = math.inf
      if index < len(speeds) and speeds[index] > 0.0:
        run_speed = min(run_speed, speeds[index])
      if seg_end - run_start >= JAM_MIN_LENGTH_M:
        return run_start - along_m, (0.0 if run_speed == math.inf else run_speed)
    else:
      run_start = None
  return None
