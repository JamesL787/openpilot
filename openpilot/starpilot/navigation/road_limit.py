"""Mapbox posted speed limit for the road being driven, without a destination.

Upstream StarPilot reads Mapbox's maxspeed only from an active route. This add-on
asks Mapbox Map Matching for the last few GPS points' road while no destination is
set, and publishes that limit through the same starpilotNavigation fields
(speedLimit, controlValid) that guidance uses. SLC still treats it as the online
fallback: used only when both chosen slots have no limit.

Turned off in Galaxy (Navigation > Route preferences), or with no Mapbox key,
nothing is requested and the limit comes only from an active route, as upstream.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math

from openpilot.starpilot.navigation.owner import ValidationError, response_json
from openpilot.starpilot.navigation.route_engine import MAX_SPEED_LIMIT_MPS, SPEED_UNITS, distance

INTERVAL_NS = 10_000_000_000  # one request per 10 s while moving: ~360 per hour of driving
RETRY_NS = 30_000_000_000     # after a failed request or a used-up allowance
MIN_SPEED = 4.                # m/s; stopped or creeping, the last answer is kept and nothing is asked
TRACE_POINTS = 6
TRACE_SPACING = 15.           # m between trace points
MAX_DISTANCE = 400.           # m from the newest matched point; covers one interval at highway speed
MAX_AGE_NS = 120_000_000_000
MAX_TURN = 60.                # degrees of heading change since the match: a turn onto another road


def matched_limit(data: dict) -> float | None:
  """Posted limit at the newest trace point, in m/s; None when Mapbox has none or matching failed."""
  try:
    if data.get('code') != 'Ok':
      return None
    last = data['tracepoints'][-1]
    if not isinstance(last, dict):
      return None  # the newest point is off any road Mapbox knows
    matching = data['matchings'][last['matchings_index']]
    # Not gated on matching confidence: Mapbox reports near zero even for good matches (its own docs example).
    for leg in reversed(matching['legs']):
      rows = leg.get('annotation', {}).get('maxspeed')
      if isinstance(rows, list) and rows:
        row = rows[-1]
        break
    else:
      return None
  except (KeyError, TypeError, IndexError, AttributeError):
    return None
  speed = row.get('speed') if isinstance(row, dict) else None
  factor = SPEED_UNITS.get(row.get('unit')) if isinstance(row, dict) else None
  if not isinstance(speed, (int, float)) or isinstance(speed, bool) or factor is None or not math.isfinite(speed):
    return None
  mps = speed * factor
  return mps if 0 < mps <= MAX_SPEED_LIMIT_MPS else None


class MapboxMatcher:
  def __init__(self, session, budget=None):
    self.session = session
    self.budget = budget  # MonthlyBudget('mapMatching'); refuses at 99% of the free allowance

  def fetch(self, token: str, trace: list) -> float | None:
    if self.budget is not None:
      self.budget.spend()
    url = 'https://api.mapbox.com/matching/v5/mapbox/driving/' + ';'.join(f'{x:.6f},{y:.6f}' for x, y in trace)
    params = {'access_token': token, 'annotations': 'maxspeed', 'overview': 'full', 'geometries': 'geojson',
              'radiuses': ';'.join(['25'] * len(trace))}
    return matched_limit(response_json(self.session, url, params))


def _heading_change(a, b) -> float:
  return abs((a - b + 180) % 360 - 180)


class RoadLimit:
  def __init__(self, matcher, enabled, executor=None):
    self.matcher = matcher
    self.enabled = enabled  # settings -> bool, read each update
    self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='road-limit')
    self.trace = []         # (coordinates, bearing)
    self.future = None
    self.pending = None
    self.answer = None      # (limit or None, coordinates, bearing, now_ns)
    self.next_request = 0

  def reset(self):
    self.trace, self.answer, self.pending = [], None, None

  def update(self, now_ns: int, settings: dict, position, drive_id: int) -> dict:
    """Fields to merge into the no-destination navigation status; empty when off."""
    if not self.enabled(settings) or not settings['token']:
      self.reset()
      return {}
    if self.future is not None and self.future.done():
      try:
        limit = self.future.result()
      except (ValidationError, OSError, ValueError, RuntimeError):  # RuntimeError: BudgetExhausted
        self.next_request = now_ns + RETRY_NS
      else:
        # reset() can clear self.pending while a lookup is still in flight (e.g. GPS
        # drops out and position goes None). Discard the stale result instead of
        # unpacking None, which crash-looped navigationd. (2026-11-04)
        if self.pending is not None:
          self.answer = (limit, *self.pending)
      self.future = self.pending = None
    if position is None:
      self.reset()
      return {}
    stamp, coordinates, speed, bearing = position
    if not self.trace or distance(self.trace[-1][0], coordinates) >= TRACE_SPACING:
      self.trace = (self.trace + [(coordinates, bearing)])[-TRACE_POINTS:]
    if self.future is None and now_ns >= self.next_request and speed >= MIN_SPEED and len(self.trace) >= 3:
      self.next_request = now_ns + INTERVAL_NS
      self.pending = (coordinates, bearing, now_ns)
      self.future = self.executor.submit(self.matcher.fetch, settings['token'], [row[0] for row in self.trace])
    limit = None
    if self.answer is not None:
      value, matched_at, matched_bearing, answered_ns = self.answer
      turned = bearing is not None and matched_bearing is not None and _heading_change(bearing, matched_bearing) > MAX_TURN
      if not turned and now_ns - answered_ns <= MAX_AGE_NS and distance(matched_at, coordinates) <= MAX_DISTANCE:
        limit = value
    return {'locationMonoTime': stamp, 'speedLimit': limit or 0.,
            'controlValid': bool(limit and drive_id > 0 and stamp >= drive_id)}
