"""Mapbox route speed limit as the online fallback source.

During navigation, Mapbox Directions returns a posted limit (``maxspeed``) for each
segment of the route. navigation/runtime publishes the limit of the segment the car
is matched to, and only while the car is on the route. Selection uses it only when
neither priority slot has a limit (``online_fallback``).
"""
import hashlib
import json
import math

from openpilot.starpilot.navigation.wire import navigation_state
from openpilot.starpilot.speed_limits import acceptance as acc

MAX_AGE_NS = 3_000_000_000  # navigation publishes at 1 Hz


def navigation_observation(sm, *, now_ns: int, drive_session: str, car_fingerprint: str) -> acc.Observation:
  stamp = int(sm.logMonoTime.get('starpilotNavigation', 0))
  if stamp <= 0:
    return acc.Observation(acc.ObservationKind.ABSENT)
  if not sm.valid.get('starpilotNavigation', False) or not 0 < stamp <= now_ns or now_ns - stamp > MAX_AGE_NS:
    return acc.Observation(acc.ObservationKind.STALE)
  state = navigation_state(sm['starpilotNavigation'])
  # noDestination: the road limit add-on (navigation/road_limit.py) publishes one only when it has a limit.
  road_limit = state is not None and str(state.status) == 'noDestination' and state.controlValid
  if state is None or not state.enabled or (str(state.status) != 'guiding' and not road_limit):
    return acc.Observation(acc.ObservationKind.ABSENT)
  frame_ns, speed = int(state.frameMonoTime), float(state.speedLimit)
  if not 0 < frame_ns <= now_ns or now_ns - frame_ns > MAX_AGE_NS:
    return acc.Observation(acc.ObservationKind.STALE)
  # controlValid: this drive, on the route, fresh location. Off route the segment is unknown.
  if not state.controlValid or not math.isfinite(speed) or speed <= 0:
    return acc.Observation(acc.ObservationKind.UNKNOWN)
  identity = hashlib.sha256(json.dumps((drive_session, car_fingerprint, str(state.sessionId), str(state.revision),
    round(speed, 2)), separators=(',', ':')).encode()).hexdigest()
  return acc.Observation(acc.ObservationKind.VALID, acc.Candidate('online',
    acc.ObservationIdentity(acc.IdentityKind.GEOGRAPHIC, value=identity), speed))
