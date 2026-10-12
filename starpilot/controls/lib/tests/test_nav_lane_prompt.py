from openpilot.starpilot.controls.lib.nav_lane_prompt import nav_lane_move_prompt, prompt_window_m

W = {"left": 3.5, "right": 3.5}


def prompt(state, v=13.0, widths=W):
  return nav_lane_move_prompt(state, v, 8.9, widths, 2.0, 100.0)


def nav(mtype="turn", mod="right", dist=100.0):
  return {"valid": True, "maneuverType": mtype, "maneuverModifier": mod, "maneuverDistance": dist}


def test_city_turn_arms_only_close():
  assert prompt(nav(dist=100.0))["armed"]
  assert prompt(nav(dist=100.0))["side"] == "right"
  assert prompt(nav(dist=100.0))["kind"] == "turn"
  assert not prompt(nav(dist=1000.0))["armed"]


def test_exit_arms_about_a_mile_out_at_highway_speed():
  assert prompt(nav("off ramp", "slight right", 1500.0), v=29.0)["armed"]
  assert not prompt(nav("off ramp", "slight right", 1700.0), v=29.0)["armed"]


def test_window_scales_with_speed_and_kind():
  assert prompt_window_m("turn", 5.0) < prompt_window_m("turn", 15.0)
  assert prompt_window_m("exit", 29.0) > prompt_window_m("turn", 29.0)


def test_empty_lanes_still_arms():
  assert prompt(nav(mod="left"))["side"] == "left"


def test_not_armed_in_edge_lane_slow_or_invalid():
  assert not prompt(nav(), widths={"left": 3.5, "right": 0.0})["armed"]
  assert not prompt(nav(), v=5.0)["armed"]
  assert not prompt({})["armed"]
  assert not prompt(nav(mod="straight"))["armed"]
  assert not prompt(nav("fork", "slight right"))["armed"]


def test_too_close_to_finish_a_lane_change_clears():
  assert not prompt(nav(dist=40.0), v=13.0)["armed"]


def lane_nav(direction="right", edge=True, shared=False, dist=200.0):
  n = nav(dist=dist)
  n.update(activeLaneDirection=direction, activeLaneAtRoadEdge=edge, hasSharedSameSideLane=shared)
  return n


def test_turn_only_lane_prompts_earlier():
  assert not prompt(nav(dist=200.0))["armed"]
  p = prompt(lane_nav())
  assert p["armed"] and p["turn_lane"]


def test_shared_or_wrong_side_lane_is_not_turn_only():
  assert not prompt(lane_nav(shared=True))["turn_lane"]
  assert not prompt(lane_nav(direction="left"))["turn_lane"]
  assert not prompt(lane_nav(edge=False))["turn_lane"]


def test_turn_only_lane_still_needs_a_lane_to_move_into():
  assert not prompt(lane_nav(), widths={"left": 3.5, "right": 0.0})["armed"]


def test_on_ramp_is_prompted_like_an_exit():
  # D-113
  assert prompt(nav("on ramp", "slight right", 300.0), v=20.0)["kind"] == "exit"
  assert prompt(nav("on ramp", "slight right", 300.0), v=20.0)["armed"]
