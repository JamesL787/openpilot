from openpilot.starpilot.navigation.lane_traps import control_ahead, exit_only_ahead
from openpilot.starpilot.navigation.route_engine import MapboxRouteEngine

STRAIGHT = {"valid": True, "indications": ["straight"]}
EXIT_RIGHT = {"valid": False, "indications": ["slight right"]}


def mapbox_route(intersections: list) -> dict:
  # due east along the equator, ~111 m per 0.001 deg: 0 -> 0.03 deg is ~3.3 km
  coords = [[i * 0.001, 0.0] for i in range(31)]
  return {
    "distance": 3330.0, "duration": 120.0,
    "geometry": {"coordinates": coords},
    "legs": [{"steps": [
      {"maneuver": {"type": "depart", "instruction": "Head east", "location": coords[0]},
       "distance": 3330.0, "duration": 120.0, "intersections": intersections},
      {"maneuver": {"type": "arrive", "instruction": "Arrive", "location": coords[-1]},
       "distance": 0.0, "duration": 0.0},
    ]}],
  }


def parse(intersections: list):
  route = MapboxRouteEngine._parse_route(mapbox_route(intersections))
  assert route is not None
  return route


def test_exit_only_lane_at_a_passed_exit_is_found_with_side_and_distance():
  route = parse([{"location": [0.010, 0.0], "lanes": [STRAIGHT, STRAIGHT, EXIT_RIGHT]}])
  trap = exit_only_ahead(route, along_m=0.0)
  assert trap is not None
  assert trap["side"] == "right" and trap["lanes"] == 1
  assert 1100.0 < trap["distance"] < 1125.0


def test_two_exit_only_lanes_and_left_side():
  exit_left = {"valid": False, "indications": ["left"]}
  route = parse([{"location": [0.010, 0.0], "lanes": [exit_left, exit_left, STRAIGHT]}])
  assert exit_only_ahead(route, 0.0) == {"distance": route.steps[0].junction_lanes[0][0], "side": "left", "lanes": 2,
                                     "kind": "turn"}


def test_shared_lane_or_the_route_taking_the_exit_is_not_a_trap():
  shared = {"valid": True, "indications": ["straight", "slight right"]}
  assert exit_only_ahead(parse([{"location": [0.010, 0.0], "lanes": [STRAIGHT, shared]}]), 0.0) is None
  # the route takes the exit: straight lanes invalid, exit lane valid
  taken = [{"valid": False, "indications": ["straight"]}, {"valid": True, "indications": ["slight right"]}]
  assert exit_only_ahead(parse([{"location": [0.010, 0.0], "lanes": taken}]), 0.0) is None
  # no indications at all says nothing
  assert exit_only_ahead(parse([{"location": [0.010, 0.0], "lanes": [STRAIGHT, {"valid": False}]}]), 0.0) is None


def test_lookahead_and_passed_junctions():
  route = parse([{"location": [0.025, 0.0], "lanes": [STRAIGHT, EXIT_RIGHT]}])
  assert exit_only_ahead(route, 0.0) is None  # ~2.8 km away
  assert exit_only_ahead(route, 1500.0) is not None
  assert exit_only_ahead(route, 2900.0) is None  # already past it
  assert exit_only_ahead(None, 0.0) is None


def test_malformed_intersections_do_not_break_the_route():
  route = parse([{"location": [0.010, 0.0], "lanes": ["junk", None]}, "junk", {"lanes": [EXIT_RIGHT]},
                 {"location": [0.012, 0.0], "lanes": [STRAIGHT, EXIT_RIGHT]}])
  trap = exit_only_ahead(route, 0.0)
  assert trap is not None and 1300.0 < trap["distance"] < 1350.0


def test_highway_exit_is_exit_kind_and_city_turn_lane_is_turn_kind():
  route = parse([{"location": [0.010, 0.0], "lanes": [STRAIGHT, STRAIGHT, EXIT_RIGHT]}])
  assert exit_only_ahead(route, 0.0)["kind"] == "exit"
  turn_left = {"valid": False, "indications": ["uturn", "left"]}
  route = parse([{"location": [0.002, 0.0], "lanes": [turn_left, STRAIGHT, STRAIGHT]}])
  trap = exit_only_ahead(route, 0.0)
  assert trap["side"] == "left" and trap["kind"] == "turn"
  # a lane that also goes straight is not a trap
  route = parse([{"location": [0.002, 0.0], "lanes": [{"valid": True, "indications": ["left", "straight"]}, STRAIGHT]}])
  assert exit_only_ahead(route, 0.0) is None


def test_traffic_controls_are_parsed_and_found_in_route_order():
  route = parse([
    {"location": [0.004, 0.0], "traffic_signal": True},
    {"location": [0.006, 0.0], "lanes": [STRAIGHT, STRAIGHT]},           # lanes only: not a control
    {"location": [0.008, 0.0], "stop_sign": True},
    {"location": [0.020, 0.0], "railway_crossing": True},
    {"location": [0.025, 0.0], "traffic_signal": False},
  ])
  assert [kind for _, kind in route.steps[0].junction_controls] == ["signal", "stop", "rail"]
  first = control_ahead(route, 0.0, 600.0)
  assert first["kind"] == "signal" and 440.0 < first["distance"] < 450.0
  assert control_ahead(route, 500.0, 600.0)["kind"] == "stop"   # the signal is behind
  assert control_ahead(route, 1000.0, 600.0) is None              # the crossing is 1.2 km on
  assert control_ahead(route, 2000.0, 600.0)["kind"] == "rail"
  assert control_ahead(None, 0.0, 600.0) is None
