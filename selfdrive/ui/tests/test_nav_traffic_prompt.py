import pyray as rl

from openpilot.selfdrive.ui.onroad.starpilot.nav_traffic_prompt import format_savings, parse_reroute_prompt, response_for_tap


def test_parse_reroute_prompt_needs_armed_and_fresh():
  raw = {"armed": True, "id": 3, "savings_s": 420, "remaining_s": 12.5, "ts": 100.0}
  assert parse_reroute_prompt(raw, 101.0)["id"] == 3
  assert parse_reroute_prompt('{"armed": true, "id": 3, "ts": 100.0}', 100.5)["id"] == 3
  assert parse_reroute_prompt(raw, 103.0) is None, "stale: navigationd stopped refreshing it"
  assert parse_reroute_prompt({**raw, "armed": False}, 101.0) is None
  assert parse_reroute_prompt({"armed": True, "ts": 100.0}, 101.0) is None, "no id: nothing to answer"
  assert parse_reroute_prompt("not json", 101.0) is None


def test_only_the_button_row_answers_and_halves_pick_switch_or_keep():
  prompt = {"id": 7}
  box = rl.Rectangle(100, 50, 400, 96)
  assert response_for_tap(prompt, box, 150, 60) is None, "a tap on the title does nothing"
  assert response_for_tap(prompt, box, 150, 120) == {"id": 7, "accept": True}
  assert response_for_tap(prompt, box, 450, 120) == {"id": 7, "accept": False}


def test_format_savings():
  assert format_savings(30) == "1 min faster"
  assert format_savings(420) == "7 min faster"
