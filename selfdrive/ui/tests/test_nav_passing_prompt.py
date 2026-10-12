from openpilot.selfdrive.ui.onroad.starpilot.nav_passing_prompt import parse_passing_prompt


def test_parse_passing_prompt_needs_armed_fresh_side_and_phase():
  raw = {"armed": True, "side": "left", "phase": "pass", "ts": 100.0}
  assert parse_passing_prompt(raw, 101.0) == {"side": "left", "phase": "pass", "ts": 100.0}
  assert parse_passing_prompt('{"armed": true, "side": "right", "phase": "return", "ts": 100.0}', 100.5)["phase"] == "return"
  assert parse_passing_prompt(raw, 103.0) is None, "stale: the planner stopped refreshing it"
  assert parse_passing_prompt({**raw, "armed": False}, 101.0) is None
  assert parse_passing_prompt({**raw, "phase": "merge"}, 101.0) is None
  assert parse_passing_prompt({**raw, "side": ""}, 101.0) is None
  assert parse_passing_prompt("not json", 101.0) is None
  assert parse_passing_prompt({}, 101.0) is None
