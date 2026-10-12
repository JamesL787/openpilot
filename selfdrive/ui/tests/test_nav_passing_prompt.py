from openpilot.selfdrive.ui.onroad.starpilot.nav_passing_prompt import TEXT, format_jam, parse_passing_prompt


def test_parse_passing_prompt_needs_armed_fresh_side_and_phase():
  raw = {"armed": True, "side": "left", "phase": "pass", "ts": 100.0}
  assert parse_passing_prompt(raw, 101.0) == {"side": "left", "phase": "pass", "ts": 100.0, "distance": 0.0, "speed": 0.0}
  assert parse_passing_prompt('{"armed": true, "side": "right", "phase": "return", "ts": 100.0}', 100.5)["phase"] == "return"
  assert parse_passing_prompt(raw, 103.0) is None, "stale: the planner stopped refreshing it"
  assert parse_passing_prompt({**raw, "armed": False}, 101.0) is None
  assert parse_passing_prompt({**raw, "phase": "merge"}, 101.0) is None
  assert parse_passing_prompt({**raw, "side": ""}, 101.0) is None
  assert parse_passing_prompt("not json", 101.0) is None
  assert parse_passing_prompt({}, 101.0) is None


def test_d115_exit_and_keep_right_phases_parse():
  for phase, side in (("exit", "left"), ("exit", "right"), ("keepright", "right")):
    assert parse_passing_prompt({"armed": True, "side": side, "phase": phase, "ts": 1.0}, 1.5)["phase"] == phase
  assert TEXT["exit"][1].format(side="left") == "Move left to stay on route"


def test_d116_jam_notice_has_no_side_and_needs_distance_and_speed():
  raw = {"armed": True, "side": "", "phase": "jam", "ts": 1.0, "distance": 1200.0, "speed": 20.1}
  assert parse_passing_prompt(raw, 1.5)["distance"] == 1200.0
  assert parse_passing_prompt({**raw, "side": "left"}, 1.5) is None
  assert parse_passing_prompt({**raw, "distance": 0.0}, 1.5) is None
  assert parse_passing_prompt({**raw, "speed": "nan"}, 1.5) is None
  assert format_jam(1200.0, 20.1168, False) == ("0.7 mi", "45 mph")
  assert format_jam(120.0, 20.0, False) == ("394 ft", "45 mph")
  assert format_jam(1200.0, 12.5, True) == ("1.2 km", "45 km/h")
