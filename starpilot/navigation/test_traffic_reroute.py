import math

import pytest

from openpilot.starpilot.navigation.navigationd import Navigationd
from openpilot.starpilot.navigation.route_engine import Coordinate, MapboxRouteEngine, NavigationRoute
from openpilot.starpilot.navigation.traffic_reroute import (
  TRAFFIC_PROMPT_TIMEOUT_S, TRAFFIC_REFRESH_INTERVAL_S, TRAFFIC_RETRY_BASE_S, TRAFFIC_RETRY_MAX_S, TRAFFIC_SWITCH_COOLDOWN_S,
  TrafficReroutePolicy, congestion_ahead, retry_delay_s, route_overlap_fraction, same_route,
)

LAT0, LON0 = 30.0, -97.0
DEG_PER_M_LAT = 1.0 / 111_195.0


def _route(points, duration=600.0, congestion=None, speeds=None, step_every=None):
  """Route through (north_m, east_m) points. Steps at the start, the end and every step_every points."""
  coords = [(LAT0 + n * DEG_PER_M_LAT, LON0 + e * DEG_PER_M_LAT / math.cos(math.radians(LAT0))) for n, e in points]
  step_idx = sorted({0, len(coords) - 1, *(range(0, len(coords), step_every) if step_every else [])})
  steps = []
  for i, idx in enumerate(step_idx):
    nxt = step_idx[i + 1] if i + 1 < len(step_idx) else idx
    steps.append({"maneuver": "depart" if i == 0 else ("arrive" if idx == len(coords) - 1 else "turn"), "instruction": "",
                  "distance": 100.0 * (nxt - idx), "duration": duration * (nxt - idx) / max(len(coords) - 1, 1),
                  "location": {"latitude": coords[idx][0], "longitude": coords[idx][1]}, "modifier": "straight"})
  route = NavigationRoute.from_mapbox_route({
    "geometry": [{"latitude": lat, "longitude": lon} for lat, lon in coords], "steps": steps,
    "totalDistance": 100.0 * (len(coords) - 1), "totalDuration": duration,
    "congestion": congestion or [], "speed": speeds or [],
  })
  assert route is not None
  return route


def _north(n_points, east=0.0, **kw):
  return _route([(100.0 * i, east) for i in range(n_points)], **kw)


# ===== policy =====
def test_policy_needs_two_confirmations_and_both_savings_thresholds():
  policy = TrafficReroutePolicy()
  assert policy.evaluate(0.0, 3000.0, 2800.0, 5000.0, False).reason == "insufficient_savings", "200 s is under 10 %"
  assert policy.evaluate(0.0, 600.0, 500.0, 5000.0, False).reason == "insufficient_savings", "17 % but under 120 s"
  first = policy.evaluate(0.0, 3000.0, 2600.0, 5000.0, False)
  assert first.reason == "awaiting_confirmation" and first.confirmations == 1
  assert policy.evaluate(30.0, 3000.0, 2600.0, 5000.0, False).reason == "awaiting_confirmation", "a different candidate restarts"
  second = policy.evaluate(60.0, 3000.0, 2600.0, 5000.0, True)
  assert second.reason == "switch" and second.savings_s == pytest.approx(400.0)


def test_policy_guard_cooldown_and_same_route_reset_the_count():
  policy = TrafficReroutePolicy()
  policy.evaluate(0.0, 3000.0, 2600.0, 5000.0, False)
  assert policy.evaluate(30.0, 3000.0, 2600.0, 400.0, True).reason == "maneuver_guard"
  assert policy.evaluate(60.0, 3000.0, 2600.0, 5000.0, True).reason == "awaiting_confirmation", "count restarted"
  assert policy.evaluate(90.0, 3000.0, None, 5000.0, True).reason == "same_route"
  policy.mark_answered(100.0)
  assert policy.evaluate(100.0 + TRAFFIC_SWITCH_COOLDOWN_S - 1.0, 3000.0, 2000.0, 5000.0, True).reason == "cooldown"
  assert policy.evaluate(100.0 + TRAFFIC_SWITCH_COOLDOWN_S, 3000.0, 2000.0, 5000.0, True).reason == "awaiting_confirmation"


def test_retry_backoff():
  assert retry_delay_s(1) == TRAFFIC_RETRY_BASE_S
  assert retry_delay_s(2) == 2 * TRAFFIC_RETRY_BASE_S
  assert retry_delay_s(20) == TRAFFIC_RETRY_MAX_S


# ===== geometry =====
def test_same_route_matches_the_remaining_part_and_rejects_a_parallel_road():
  current = _north(41)                     # 4 km north
  ahead = _route([(1000.0 + 100.0 * i, 0.0) for i in range(31)])   # the same road from 1 km on
  parallel = _north(41, east=400.0)        # a road 400 m east
  assert same_route(ahead, current, reference_start_m=1000.0)
  assert route_overlap_fraction(parallel, current) == 0.0
  assert not same_route(ahead, current, reference_start_m=3500.0), "most of it is behind the cut"


def test_congestion_ahead_finds_the_first_long_enough_run():
  levels = ["low"] * 10 + ["heavy"] + ["low"] * 4 + ["severe", "heavy", "heavy"] + ["low"] * 22
  speeds = [25.0] * 15 + [4.0, 6.0, 0.0] + [25.0] * 22
  route = _north(41, congestion=levels, speeds=speeds)
  jam = congestion_ahead(route, along_m=50.0)
  assert jam is not None
  distance, speed = jam
  assert distance == pytest.approx(1450.0, abs=5.0), "the single 100 m heavy segment is skipped as too short"
  assert speed == pytest.approx(4.0)
  assert congestion_ahead(route, along_m=50.0, lookahead_m=1000.0) is None
  inside = congestion_ahead(route, along_m=1550.0)
  assert inside is not None and inside[0] == pytest.approx(0.0)
  assert congestion_ahead(_north(41), along_m=0.0) is None, "no annotations: no jam"


def test_route_engine_requests_and_parses_congestion():
  class Response:
    status_code = 200

    def json(self):
      return {"code": "Ok", "routes": [{
        "distance": 200.0, "duration": 20.0,
        "geometry": {"coordinates": [[LON0, LAT0], [LON0, LAT0 + 0.001], [LON0, LAT0 + 0.002]]},
        "legs": [{"annotation": {"maxspeed": [], "congestion": ["low", "heavy"], "speed": [20.0, 3.5]},
                  "steps": [{"maneuver": {"type": "depart", "instruction": "", "location": [LON0, LAT0]},
                             "distance": 200.0, "duration": 20.0}]}],
      }]}

  class Session:
    def get(self, url, params, timeout):
      self.params = params
      return Response()

  session = Session()
  routes = MapboxRouteEngine(session=session).fetch_routes("tok", Coordinate(LAT0, LON0), {"latitude": LAT0 + 0.002, "longitude": LON0})
  assert "congestion" in session.params["annotations"] and "speed" in session.params["annotations"]
  assert routes[0].congestion == ["low", "heavy"]
  assert routes[0].segment_speeds == [20.0, 3.5]


# ===== navigationd flow =====
class MemParams:
  def __init__(self, values=None):
    self.values = dict(values or {})

  def get(self, key, encoding=None):
    return self.values.get(key)

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def put_nonblocking(self, key, value):
    self.values[key] = value

  put = put_nonblocking

  def remove(self, key):
    self.values.pop(key, None)


def _navigationd(current, reroute=True, jam=False):
  nd = Navigationd.__new__(Navigationd)
  import threading
  nd.params = MemParams({"NavTrafficReroute": reroute, "NavJamSlowdown": jam})
  nd.params_memory = MemParams()
  nd._route_lock = threading.Lock()
  nd._route = current
  nd._route_generation = 1
  nd._route_fetched_at = 0.0
  nd._route_fetch_inflight = False
  nd._last_position = Coordinate(LAT0, LON0)
  nd._last_bearing = 0.0
  nd._off_route_started_at = nd._bearing_misaligned_started_at = nd._arrival_started_at = None
  nd._traffic_policy = TrafficReroutePolicy()
  nd._traffic_fetch_inflight = False
  nd._traffic_next_check_at = 0.0
  nd._traffic_failures = 0
  nd._traffic_candidate = None
  nd._traffic_route = None
  nd._traffic_route_at = -math.inf
  nd._reroute_prompt = None
  nd._reroute_prompt_id = 0
  return nd


def _faster_detour():
  # leaves the current road east and rejoins far north: a different road for most of its length
  return _route([(0.0, 0.0), (0.0, 300.0)] + [(100.0 * i, 300.0) for i in range(1, 41)], duration=2400.0)


def _check(nd, current, routes, now, next_maneuver_m=5000.0):
  nd._handle_traffic_routes(routes, current, 1, 0.0, next_maneuver_m, True, now)


def test_a_faster_route_is_only_offered_after_two_checks_and_never_switched_without_the_driver():
  current = _north(41, duration=3000.0)
  nd = _navigationd(current)
  fresh_current = _north(41, duration=3000.0)
  _check(nd, current, [fresh_current, _faster_detour()], 0.0)
  assert nd._reroute_prompt is None
  _check(nd, current, [fresh_current, _faster_detour()], 30.0)
  assert nd._reroute_prompt is not None and nd._reroute_prompt["savings_s"] == pytest.approx(600.0)
  assert nd._route is current, "the route never changes on its own"

  progress = current.get_progress(nd._last_position)
  nd._update_reroute_prompt(progress, 31.0)
  shown = nd.params_memory.values["NavTrafficReroutePrompt"]
  assert shown["armed"] and shown["id"] == nd._reroute_prompt["id"]
  nd._update_reroute_prompt(progress, 30.0 + TRAFFIC_PROMPT_TIMEOUT_S)
  assert nd._reroute_prompt is None and "NavTrafficReroutePrompt" not in nd.params_memory.values
  assert nd._route is current, "no answer keeps the current route"
  assert nd._traffic_policy.in_cooldown(31.0 + TRAFFIC_PROMPT_TIMEOUT_S)


def test_driver_accept_switches_and_decline_keeps():
  for accept in (True, False):
    current = _north(41, duration=3000.0)
    nd = _navigationd(current)
    detour = _faster_detour()
    for now in (0.0, 30.0):
      _check(nd, current, [_north(41, duration=3000.0), detour], now)
    prompt_id = nd._reroute_prompt["id"]
    nd.params_memory.values["NavTrafficRerouteResponse"] = {"id": prompt_id, "accept": accept}
    nd._update_reroute_prompt(current.get_progress(nd._last_position), 35.0)
    assert nd._reroute_prompt is None
    assert (nd._route is detour) == accept
    assert nd._route_generation == (2 if accept else 1)
    assert "NavTrafficRerouteResponse" not in nd.params_memory.values


def test_a_stale_response_id_is_ignored():
  current = _north(41, duration=3000.0)
  nd = _navigationd(current)
  for now in (0.0, 30.0):
    _check(nd, current, [_north(41, duration=3000.0), _faster_detour()], now)
  nd.params_memory.values["NavTrafficRerouteResponse"] = {"id": 999, "accept": True}
  nd._update_reroute_prompt(current.get_progress(nd._last_position), 35.0)
  assert nd._reroute_prompt is not None and nd._route is current


def test_no_offer_near_a_maneuver_or_without_a_fresh_time_for_the_current_route():
  current = _north(41, duration=3000.0)
  nd = _navigationd(current)
  for now in (0.0, 30.0):
    _check(nd, current, [_north(41, duration=3000.0), _faster_detour()], now, next_maneuver_m=300.0)
  assert nd._reroute_prompt is None
  nd2 = _navigationd(current)
  for now in (0.0, 30.0):
    _check(nd2, current, [_faster_detour()], now)
  assert nd2._reroute_prompt is None


def test_a_prompt_is_withdrawn_when_the_route_changes_underneath_it():
  current = _north(41, duration=3000.0)
  nd = _navigationd(current)
  for now in (0.0, 30.0):
    _check(nd, current, [_north(41, duration=3000.0), _faster_detour()], now)
  nd._route_generation += 1   # an off-route reroute landed
  nd._update_reroute_prompt(current.get_progress(nd._last_position), 31.0)
  assert nd._reroute_prompt is None


def test_failed_check_backs_off_and_success_schedules_the_next():
  current = _north(41)
  nd = _navigationd(current)
  nd._handle_traffic_routes([], current, 1, 0.0, 5000.0, True, 100.0)
  assert nd._traffic_next_check_at == pytest.approx(100.0 + TRAFFIC_RETRY_BASE_S)
  nd._handle_traffic_routes([], current, 1, 0.0, 5000.0, True, 200.0)
  assert nd._traffic_next_check_at == pytest.approx(200.0 + 2 * TRAFFIC_RETRY_BASE_S)
  nd._handle_traffic_routes([_north(41)], current, 1, 0.0, 5000.0, True, 300.0)
  assert nd._traffic_next_check_at == pytest.approx(300.0 + TRAFFIC_REFRESH_INTERVAL_S)
  nd._handle_traffic_routes([_north(41)], current, 0, 0.0, 5000.0, True, 400.0)
  assert nd._traffic_next_check_at == pytest.approx(300.0 + TRAFFIC_REFRESH_INTERVAL_S), "stale generation ignored"


def test_jam_uses_the_freshest_traffic_and_drops_old_data(monkeypatch):
  levels = ["low"] * 10 + ["heavy"] * 5 + ["low"] * 25
  current = _north(41)                         # fetched at t=0 without congestion
  nd = _navigationd(current, reroute=False, jam=True)
  progress = current.get_progress(nd._last_position)
  assert nd._jam_ahead(current, progress, 10.0) is None
  nd._handle_traffic_routes([_north(41, congestion=levels, speeds=[3.0] * 40)], current, 1, 0.0, 5000.0, False, 100.0)
  jam = nd._jam_ahead(current, progress, 110.0)
  assert jam is not None and jam[0] == pytest.approx(1000.0, abs=5.0) and jam[1] == pytest.approx(3.0)
  assert nd._jam_ahead(current, progress, 100.0 + 601.0) is None, "older than 10 min is not used"
  nd.params.values["NavJamSlowdown"] = False
  assert nd._jam_ahead(current, progress, 110.0) is None
