"""Mapbox route speed limit: navigation publishes it, SLC uses it only as the online fallback."""
from types import SimpleNamespace as NS

import pytest

from openpilot.cereal import messaging
from openpilot.starpilot.navigation.route_engine import MapboxRouteEngine, NavigationRoute, max_speeds
from openpilot.starpilot.navigation.wire import navigation_envelope
from openpilot.starpilot.speed_limits import acceptance as acc, selection as sel
from openpilot.starpilot.speed_limits.navigation_observation import navigation_observation
from openpilot.starpilot.speed_limits.runtime import Runtime
from openpilot.starpilot.speed_limits.runtime_settings import parse

MONO = 100_000_000_000
MPH = 0.44704


def route_data(maxspeed):
  return {'distance': 2224., 'duration': 100., 'geometry': {'coordinates': [[0., 0.], [.01, 0.], [.02, 0.]]},
          'legs': [{'annotation': {'maxspeed': maxspeed}, 'steps': [
            {'distance': 2224., 'duration': 100., 'maneuver': {'type': 'depart', 'instruction': 'Head east'}},
            {'distance': 0., 'duration': 0., 'maneuver': {'type': 'arrive', 'instruction': 'You have arrived'}}]}]}


def test_mapbox_maxspeed_annotation_is_read_per_segment():
  assert max_speeds(route_data([{'speed': 45, 'unit': 'mph'}, {'speed': 100, 'unit': 'km/h'}]), 2) == \
    pytest.approx([45 * MPH, 100 / 3.6])
  # No posted limit, unknown, nonsense and unit-less entries are all unknown, never "no limit".
  assert max_speeds(route_data([{'none': True}, {'unknown': True}]), 2) == [None, None]
  assert max_speeds(route_data([{'speed': 'fast', 'unit': 'mph'}, {'speed': 45}]), 2) == [None, None]
  assert max_speeds(route_data([{'speed': 0, 'unit': 'mph'}, {'speed': 400, 'unit': 'km/h'}]), 2) == [None, None]
  assert max_speeds(route_data([{'speed': 45, 'unit': 'mph'}]), 2) == [None, None]  # misaligned with the geometry
  assert max_speeds({'legs': [{}]}, 2) == [None, None]


def test_route_progress_reports_the_matched_segment_limit_only_on_route():
  route = NavigationRoute(route_data([{'speed': 45, 'unit': 'mph'}, {'speed': 30, 'unit': 'mph'}]))
  assert route.progress((.005, 0.), 15., 90.).speed_limit_mps == pytest.approx(45 * MPH)
  assert route.progress((.015, 0.), 15., 90.).speed_limit_mps == pytest.approx(30 * MPH)
  assert route.progress((.015, 0.), 15., 270.).speed_limit_mps is None  # driving the other way: off route
  assert route.progress((.015, .01), 15., 90.).speed_limit_mps is None  # a kilometer away: off route
  assert NavigationRoute(route_data(None)).progress((.005, 0.), 15., 90.).speed_limit_mps is None


def test_directions_request_asks_for_maxspeed():
  calls = []
  class Response:
    status_code = 200
    headers = {'content-type': 'application/json'}
    def json(self):
      return {'code': 'Ok', 'routes': [route_data([{'speed': 45, 'unit': 'mph'}, {'unknown': True}])]}
  class Session:
    def get(self, url, params=None, **kwargs):
      calls.append(params)
      return Response()
  try:
    MapboxRouteEngine(Session()).fetch('pk.test', (0., 0.), {'longitude': .02, 'latitude': 0.})
  except Exception:
    pass  # response_json's transport details are covered elsewhere; only the request matters here
  assert calls and calls[0]['annotations'] == 'maxspeed' and calls[0]['overview'] == 'full'


def nav_message(speed_limit, *, status='guiding', control_valid=True, frame_ns=MONO):
  message = messaging.new_message('starpilotNavigation', valid=True)
  message.starpilotNavigation = navigation_envelope({
    'sessionId': 'nav', 'frameMonoTime': frame_ns, 'startedMonoTime': 1, 'revision': 'r1', 'enabled': True,
    'status': status, 'destinationName': 'Home', 'instruction': {}, 'nextManeuver': {}, 'route': [],
    'locationMonoTime': frame_ns, 'controlValid': control_valid, 'speedLimit': speed_limit})
  return message.starpilotNavigation


class NavSM:
  def __init__(self, navigation, stamp=MONO):
    self.data = {'starpilotNavigation': navigation}
    self.valid = {'starpilotNavigation': True}
    self.alive = {'starpilotNavigation': True}
    self.updated = {'starpilotNavigation': True}
    self.logMonoTime = {'starpilotNavigation': stamp}

  def __getitem__(self, name):
    return self.data[name]


def observe(navigation, now=MONO, stamp=MONO):
  return navigation_observation(NavSM(navigation, stamp), now_ns=now, drive_session='drive', car_fingerprint='civic')


def test_navigation_observation_is_valid_only_while_guiding_on_route():
  valid = observe(nav_message(45 * MPH))
  assert valid.kind is acc.ObservationKind.VALID and valid.candidate.source == 'online'
  assert valid.candidate.speed_mps == pytest.approx(45 * MPH)
  assert acc.observation_is_valid(valid)
  assert observe(nav_message(0.)).kind is acc.ObservationKind.UNKNOWN  # Mapbox had no limit here
  assert observe(nav_message(45 * MPH, control_valid=False)).kind is acc.ObservationKind.UNKNOWN  # off route
  assert observe(nav_message(45 * MPH, status='routing')).kind is acc.ObservationKind.ABSENT
  assert observe(nav_message(45 * MPH), now=MONO + 4_000_000_000).kind is acc.ObservationKind.STALE
  assert observe(nav_message(45 * MPH, frame_ns=MONO - 4_000_000_000)).kind is acc.ObservationKind.STALE
  assert navigation_observation(NS(logMonoTime={}, valid={}), now_ns=MONO, drive_session='d',
                                car_fingerprint='c').kind is acc.ObservationKind.ABSENT


def test_online_is_used_only_when_both_slots_have_no_limit():
  settings = parse({'SpeedLimitController': True, 'SLCPriority1': 'Dashboard', 'SLCPriority2': 'Vision'})
  assert settings.selection.online_fallback
  unknown = acc.Observation(acc.ObservationKind.UNKNOWN)
  online = observe(nav_message(45 * MPH))
  vision = acc.Observation(acc.ObservationKind.VALID, acc.Candidate('vision',
    acc.ObservationIdentity(acc.IdentityKind.GEOGRAPHIC, value='sign'), 35 * MPH))
  values = {sel.Source.DASHBOARD: unknown, sel.Source.VISION: unknown, sel.Source.MAP: unknown, sel.Source.ONLINE: online}
  chosen = sel.select_limit(values, settings.selection)
  assert chosen.selected_source is sel.Source.ONLINE and chosen.reason == 'online_fallback'
  chosen = sel.select_limit({**values, sel.Source.VISION: vision}, settings.selection)
  assert chosen.selected_source is sel.Source.VISION


def test_route_limit_fills_in_and_card_applies_its_command():
  """Peter's slots (Dashboard, Vision), no sign and no dash limit: the route's 45 mph is adopted."""
  from opendbc.car.honda.interface import CarInterface
  from opendbc.car.honda.values import CAR
  from openpilot.starpilot.longitudinal.tests.test_cruise_ceiling import messages
  from openpilot.starpilot.speed_limits import physical_actions
  from openpilot.starpilot.speed_limits.tests.test_runtime_replay import ReplaySM
  cp = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC)
  data, _ = messages()
  data['slcDashboardObservation'] = messaging.new_message('slcDashboardObservation').slcDashboardObservation
  limit = 45 * MPH
  runtime = Runtime(parse({'SpeedLimitController': True, 'SLCPriority1': 'Dashboard', 'SLCPriority2': 'Vision',
                           'SLCConfirmationLower': True}), session_id='nav-drive')
  command = None
  for i in range(80):  # 4 s at 20 Hz; navigation itself refreshes at 1 Hz
    dt = i * 50_000_000
    published = MONO + dt - dt % 1_000_000_000
    data['starpilotNavigation'] = nav_message(limit, frame_ns=published)
    sm = ReplaySM(data, MONO + dt)
    sm.logMonoTime['starpilotNavigation'] = published
    sm['carState'].vCruise = sm['carState'].vCruiseCluster = 40.0
    sm['carState'].vEgoCluster = 15.0
    sm['carControl'].enabled = sm['carControl'].longActive = True
    out = runtime.step(sm, cp, now_ns=MONO + dt, now_boot_ns=MONO + dt)
    if out.command is not None:
      command, state, now = out.command.slcCruiseCommand, out.message.slcState, MONO + dt
      break
  assert command is not None and command.source == 'online'
  assert dt == 0  # Testing adopts a valid automatic limit on its first observation (no SignFirst hold here)
  assert abs(state.acceptedSpeedLimit - limit) < .001
  current = physical_actions.state_current(ReplaySM({'slcState': state}, now), None, 'card-producer', now)
  assert physical_actions.command_applicable(command, current, None, 'card-producer', now, 40.0 / 3.6,
                                             long_active=True, button_event=False)


# Road speed limit add-on (navigation/road_limit.py): Mapbox limit without a destination.

def matching(maxspeed, *, confidence=.9, last_matched=True):
  return {'code': 'Ok', 'matchings': [{'confidence': confidence, 'legs': [
    {'annotation': {'maxspeed': [{'speed': 25, 'unit': 'mph'}]}}, {'annotation': {'maxspeed': maxspeed}}]}],
    'tracepoints': [{'matchings_index': 0, 'waypoint_index': 0}, {'matchings_index': 0, 'waypoint_index': 1},
                    {'matchings_index': 0, 'waypoint_index': 2} if last_matched else None]}


def test_matched_limit_reads_the_newest_points_road_only():
  from openpilot.starpilot.navigation.road_limit import matched_limit
  assert matched_limit(matching([{'unknown': True}, {'speed': 45, 'unit': 'mph'}])) == pytest.approx(45 * MPH)
  assert matched_limit(matching([{'speed': 45, 'unit': 'mph'}, {'unknown': True}])) is None  # newest segment unknown
  assert matched_limit(matching([{'none': True}])) is None
  assert matched_limit(matching([{'speed': 45, 'unit': 'mph'}], last_matched=False)) is None  # off any known road
  assert matched_limit(matching([{'speed': 45, 'unit': 'mph'}], confidence=4.6e-10)) == pytest.approx(45 * MPH)
  assert matched_limit({'code': 'NoMatch'}) is None and matched_limit({'code': 'Ok'}) is None


class SyncExecutor:
  def submit(self, fn, *args):
    from concurrent.futures import Future
    future = Future()
    try:
      future.set_result(fn(*args))
    except Exception as exc:
      future.set_exception(exc)
    return future


class Matcher:
  def __init__(self, limit=45 * MPH):
    self.limit, self.calls = limit, []

  def fetch(self, token, trace):
    self.calls.append(trace)
    if isinstance(self.limit, Exception):
      raise self.limit
    return self.limit


SETTINGS = {'token': 'pk.test', 'roadSpeedLimit': True}
DEG_PER_M = 1 / 111_195


def drive(road, start_ns, *, seconds, speed=15., bearing=90., x0=0., settings=SETTINGS, drive_id=1):
  out = None
  for i in range(seconds):
    now = start_ns + i * 1_000_000_000
    out = road.update(now, settings, (now, (x0 + i * speed * DEG_PER_M, 0.), speed, bearing), drive_id)
  return out, x0 + seconds * speed * DEG_PER_M


def road_limit(matcher):
  from openpilot.starpilot.navigation.road_limit import RoadLimit
  return RoadLimit(matcher, lambda settings: settings['roadSpeedLimit'], SyncExecutor())


def test_road_limit_is_published_while_moving_and_asks_every_ten_seconds():
  matcher = Matcher()
  road = road_limit(matcher)
  out, _ = drive(road, MONO, seconds=30)
  assert out['controlValid'] and out['speedLimit'] == pytest.approx(45 * MPH)
  assert len(matcher.calls) == 3 and all(3 <= len(trace) <= 6 for trace in matcher.calls)


def test_road_limit_off_or_without_key_asks_nothing_and_publishes_nothing():
  matcher = Matcher()
  for settings in ({'token': 'pk.test', 'roadSpeedLimit': False}, {'token': '', 'roadSpeedLimit': True}):
    assert drive(road_limit(matcher), MONO, seconds=30, settings=settings)[0] == {}
  assert matcher.calls == []


def test_road_limit_is_dropped_after_a_turn_or_far_from_the_match_and_kept_at_a_light():
  road = road_limit(Matcher())
  _, x = drive(road, MONO, seconds=5)
  assert road.update(MONO + 6_000_000_000, SETTINGS, (MONO + 6_000_000_000, (x, 0.), 0., 90.), 1)['controlValid']
  # Stopped at a light for a minute: nothing is asked and the limit stays.
  out, _ = drive(road, MONO + 7_000_000_000, seconds=60, speed=0., x0=x)
  assert out['controlValid']
  turned = road.update(MONO + 70_000_000_000, SETTINGS, (MONO + 70_000_000_000, (x, 0.), 5., 180.), 1)
  assert not turned['controlValid'] and turned['speedLimit'] == 0.
  road = road_limit(Matcher())
  _, x = drive(road, MONO, seconds=5)
  far = road.update(MONO + 6_000_000_000, SETTINGS, (MONO + 6_000_000_000, (x + 600 * DEG_PER_M, 0.), 0., 90.), 1)
  assert not far['controlValid']


class HeldExecutor:
  """Keeps each lookup in flight until the test finishes it."""
  def __init__(self):
    self.futures = []

  def submit(self, fn, *args):
    from concurrent.futures import Future
    future = Future()
    self.futures.append((future, fn, args))
    return future

  def finish(self):
    for future, fn, args in self.futures:
      if not future.done():
        future.set_result(fn(*args))


def test_road_limit_drops_a_lookup_that_finishes_after_gps_drops_out_or_the_feature_turns_off():
  # 2026-11-04 navigationd crash-loop: a lookup in flight when position went None (or the
  # setting went off) finished after reset() cleared pending, and unpacking None raised.
  from openpilot.starpilot.navigation.road_limit import RoadLimit
  off = {'token': 'pk.test', 'roadSpeedLimit': False}
  for dropout in ('gps', 'setting'):
    matcher, executor = Matcher(), HeldExecutor()
    road = RoadLimit(matcher, lambda settings: settings['roadSpeedLimit'], executor)
    _, x = drive(road, MONO, seconds=5)
    assert len(executor.futures) == 1 and road.pending is not None
    now = MONO + 5_000_000_000
    if dropout == 'gps':
      assert road.update(now, SETTINGS, None, 1) == {}
    else:
      assert road.update(now, off, (now, (x, 0.), 15., 90.), 1) == {}
    assert road.pending is None and road.future is not None
    executor.finish()
    now += 1_000_000_000
    out = road.update(now, SETTINGS, (now, (x, 0.), 15., 90.), 1)  # raised TypeError before the fix
    assert out['speedLimit'] == 0. and not out['controlValid']  # the stale answer is not published
    assert road.future is None and road.answer is None


def test_road_limit_unknown_failures_and_previous_drive_publish_no_limit():
  assert not drive(road_limit(Matcher(None)), MONO, seconds=30)[0]['controlValid']
  matcher = Matcher(OSError('offline'))
  out, _ = drive(road_limit(matcher), MONO, seconds=30)
  assert not out['controlValid'] and len(matcher.calls) == 1  # waits 30 s after a failure
  assert not drive(road_limit(Matcher()), MONO, seconds=30, drive_id=0)[0]['controlValid']  # not driving


def test_road_limit_reaches_slc_as_the_online_fallback_only_without_a_destination():
  road = nav_message(45 * MPH, status='noDestination')
  valid = observe(road)
  assert valid.kind is acc.ObservationKind.VALID and valid.candidate.source == 'online'
  # Off, or no limit here: absent, exactly as before the add-on.
  assert observe(nav_message(0., status='noDestination', control_valid=False)).kind is acc.ObservationKind.ABSENT
  assert observe(nav_message(45 * MPH, status='disabled')).kind is acc.ObservationKind.ABSENT
  settings = parse({'SpeedLimitController': True, 'SLCPriority1': 'Vision', 'SLCPriority2': 'Dashboard'})
  unknown = acc.Observation(acc.ObservationKind.UNKNOWN)
  values = {sel.Source.DASHBOARD: unknown, sel.Source.VISION: unknown, sel.Source.MAP: unknown, sel.Source.ONLINE: valid}
  assert sel.select_limit(values, settings.selection).selected_source is sel.Source.ONLINE


def test_navigation_runtime_merges_the_road_limit_only_without_a_destination(tmp_path):
  from openpilot.starpilot.navigation.owner import NavigationOwner
  from openpilot.starpilot.navigation.runtime import RouteRuntime
  owner = NavigationOwner(tmp_path)
  settings = {**owner.read(), 'enabled': True, 'token': 'pk.test'}
  owner.read_routing = lambda: dict(settings)  # ty: ignore[invalid-assignment]
  assert settings['roadSpeedLimit'] is True  # on by default
  matcher = Matcher()
  from openpilot.starpilot.navigation.road_limit import RoadLimit
  runtime = RouteRuntime(owner, engine=object(), executor=SyncExecutor(),
                         road_limit=RoadLimit(matcher, lambda s: s['roadSpeedLimit'], SyncExecutor()))
  result = None
  for i in range(5):
    now = MONO + i * 1_000_000_000
    result = runtime.update(now, (now, (i * 15 * DEG_PER_M, 0.), 15., 90.), 1)
  assert result['status'] == 'noDestination' and result['controlValid'] and result['speedLimit'] == pytest.approx(45 * MPH)
  settings['roadSpeedLimit'] = False
  result = runtime.update(MONO + 6_000_000_000, (MONO + 6_000_000_000, (0., 0.), 15., 90.), 1)
  assert not result['controlValid'] and result['speedLimit'] == 0.
