from dataclasses import replace

from openpilot.starpilot.controls.lib.nav_passing import (
  EXIT_WARN_DIST, KEEP_RIGHT_COOLDOWN_S, KEEP_RIGHT_SECONDS, KEEP_RIGHT_SHOW_S, MPH, PASS_TIMEOUT_S, RETURN_DELAY_S,
  SLOW_SECONDS, Lead, NavPassingAdvisor, PassingInputs, edge_gap,
)

LIMIT = 65 * MPH
NAV = {"valid": True, "maneuverType": "off ramp", "maneuverModifier": "slight right", "maneuverDistance": 8000.0}


def inputs(**kw):
  base = PassingInputs(
    enabled=True, nav_state=dict(NAV), v_ego=55 * MPH, speed_limit=LIMIT, min_lane_change_speed=20 * MPH,
    lead=Lead(True, 30.0, 55 * MPH), lead_left=Lead(False), lead_right=Lead(False),
    lane_width_left=3.6, lane_width_right=3.6, lane_detection_width=2.5,
    vasm_live=True, blocked_left=False, blocked_right=False, left_blinker=False, right_blinker=False,
  )
  return replace(base, **kw)


def run(adv, i, t0, seconds, dt=0.5):
  out, t = None, t0
  while t <= t0 + seconds:
    out = adv.update(i, t)
    t += dt
  return out, t


def test_suggests_pass_left_only_after_the_slow_window():
  adv = NavPassingAdvisor()
  out, t = run(adv, inputs(), 0.0, SLOW_SECONDS - 1.0)
  assert not out["armed"]
  out, _ = run(adv, inputs(), t, 1.5)
  assert out["armed"] and out["side"] == "left" and out["phase"] == "pass"


def test_speed_offset_raises_the_allowed_speed():
  # 65 limit + 5 offset: 63 mph with a 63 mph lead is only 2 under the limit, but 7 under the allowed 70
  i = inputs(v_ego=63 * MPH, lead=Lead(True, 30.0, 63 * MPH))
  out, _ = run(NavPassingAdvisor(), i, 0.0, SLOW_SECONDS + 1.0)
  assert not out["armed"]
  out, _ = run(NavPassingAdvisor(), replace(i, speed_offset=5 * MPH), 0.0, SLOW_SECONDS + 1.0)
  assert out["armed"] and out["phase"] == "pass"
  # 68 mph is only 2 under the allowed 70: no suggestion
  out, _ = run(NavPassingAdvisor(), replace(i, v_ego=68 * MPH, lead=Lead(True, 30.0, 68 * MPH), speed_offset=5 * MPH),
               0.0, SLOW_SECONDS + 1.0)
  assert not out["armed"]


def test_no_suggestion_without_route_toggle_or_live_vasm():
  for kw in ({"enabled": False}, {"vasm_live": False}, {"nav_state": {}}, {"nav_state": {"valid": False}}):
    adv = NavPassingAdvisor()
    out, _ = run(adv, inputs(**kw), 0.0, SLOW_SECONDS + 2)
    assert not out["armed"], kw


def test_blocks_on_each_pass_condition():
  cases = [
    {"v_ego": 62 * MPH},                                 # under the limit by less than 5 mph
    {"speed_limit": 40 * MPH, "v_ego": 30 * MPH},        # not a highway limit
    {"speed_limit": 0.0},                                # limit unknown
    {"lead": Lead(False)},                               # no lead: nothing to pass
    {"lead": Lead(True, 150.0, 55 * MPH)},               # lead far away is not the cause
    {"lane_width_left": 1.0},                            # no left lane
    {"edge_gap_left": 0.3},                              # left "lane" is the yellow-line shoulder
    {"lead_left": Lead(True, 40.0, 56 * MPH)},           # left lane no faster
    {"blocked_left": True},                              # V-ASM / blind spot sees a car
    {"nav_state": dict(NAV, maneuverDistance=1500.0)},   # route maneuver within 2 km
  ]
  for kw in cases:
    adv = NavPassingAdvisor()
    out, _ = run(adv, inputs(**kw), 0.0, SLOW_SECONDS + 2)
    assert not out["armed"], kw


def test_faster_left_lane_allows_pass():
  adv = NavPassingAdvisor()
  out, _ = run(adv, inputs(lead_left=Lead(True, 40.0, 62 * MPH)), 0.0, SLOW_SECONDS + 2)
  assert out["armed"] and out["side"] == "left"


def test_slow_timer_resets_when_condition_breaks():
  adv = NavPassingAdvisor()
  _, t = run(adv, inputs(), 0.0, SLOW_SECONDS - 2)
  adv.update(inputs(v_ego=64 * MPH), t)
  out, _ = run(adv, inputs(), t + 0.5, SLOW_SECONDS - 2)
  assert not out["armed"]


def pass_then_blinker(adv):
  _, t = run(adv, inputs(), 0.0, SLOW_SECONDS + 1)
  out = adv.update(inputs(left_blinker=True), t)
  assert not out["armed"] and adv.state == "passing"
  return t + 0.5


def test_no_return_prompt_while_alongside_then_return_after_passed_car_is_gone():
  adv = NavPassingAdvisor()
  t = pass_then_blinker(adv)
  beside = inputs(lead=Lead(True, 60.0, 70 * MPH), lead_right=Lead(True, 10.0, 55 * MPH), v_ego=64 * MPH)
  out, t = run(adv, beside, t, 20.0)
  assert not out["armed"]
  gone = replace(beside, lead_right=Lead(False))
  out, t = run(adv, gone, t, RETURN_DELAY_S - 1.0)
  assert not out["armed"]
  out, t = run(adv, gone, t, 1.5)
  assert out["armed"] and out["side"] == "right" and out["phase"] == "return"
  out = adv.update(replace(gone, blocked_right=True), t)
  assert not out["armed"]  # waits while the right side is occupied
  out = adv.update(replace(gone, right_blinker=True), t + 0.5)
  assert not out["armed"] and adv.state == "idle"


def test_route_needing_right_suggests_return_early_and_left_never():
  adv = NavPassingAdvisor()
  t = pass_then_blinker(adv)
  out = adv.update(inputs(nav_state=dict(NAV, maneuverDistance=1500.0), lead_right=Lead(True, 10.0, 55 * MPH)), t)
  assert out["armed"] and out["side"] == "right"

  adv = NavPassingAdvisor()
  t = pass_then_blinker(adv)
  left_route = dict(NAV, maneuverModifier="slight left", maneuverDistance=1500.0)
  out, _ = run(adv, inputs(nav_state=left_route, lead_right=Lead(False)), t, 30.0)
  assert not out["armed"]


def test_pass_gives_up_after_timeout_and_vasm_loss_clears_state():
  adv = NavPassingAdvisor()
  t = pass_then_blinker(adv)
  adv.update(inputs(lead=Lead(False)), t + PASS_TIMEOUT_S + 1)
  assert adv.state == "idle"

  adv = NavPassingAdvisor()
  t = pass_then_blinker(adv)
  adv.update(inputs(vasm_live=False), t)
  assert adv.state == "idle"


# D-115 exit-only lane warning
EXIT_NAV = dict(NAV, exitOnlyDistance=900.0, exitOnlySide="right")


def exit_inputs(**kw):
  # rightmost lane: no lane to the right, one to the left; no slow lead, no passing toggle
  base = dict(enabled=False, exit_warn=True, nav_state=dict(EXIT_NAV), lane_width_right=1.0, lead=Lead(False), vasm_live=False)
  base.update(kw)
  return inputs(**base)


def test_exit_only_lane_warns_to_move_left_without_vasm():
  out = NavPassingAdvisor().update(exit_inputs(), 0.0)
  assert out["armed"] and out["side"] == "left" and out["phase"] == "exit"


def test_exit_only_warning_needs_toggle_route_edge_lane_and_range():
  cases = [
    {"exit_warn": False},
    {"nav_state": dict(EXIT_NAV, valid=False)},
    {"lane_width_right": 3.6},                       # not in the edge lane
    {"lane_width_left": 1.0},                        # nowhere to go
    {"nav_state": dict(EXIT_NAV, exitOnlyDistance=EXIT_WARN_DIST + 100.0)},
    {"nav_state": dict(EXIT_NAV, exitOnlyDistance=-1.0)},
    {"nav_state": dict(EXIT_NAV, exitOnlySide="")},
    {"left_blinker": True},                          # already moving
  ]
  for kw in cases:
    assert not NavPassingAdvisor().update(exit_inputs(**kw), 0.0)["armed"], kw


def test_exit_only_lane_beside_a_shoulder_counts_as_the_edge_lane():
  # the right shoulder measures lane-wide, but its outer line sits on the road edge
  out = NavPassingAdvisor().update(exit_inputs(lane_width_right=3.4, edge_gap_right=0.3), 0.0)
  assert out["armed"] and out["side"] == "left" and out["phase"] == "exit"
  # nowhere to go when the only lane on the left is the yellow-line shoulder
  out = NavPassingAdvisor().update(exit_inputs(edge_gap_left=0.3), 0.0)
  assert not out["armed"]


def test_left_exit_only_lane_warns_to_move_right():
  i = exit_inputs(nav_state=dict(EXIT_NAV, exitOnlySide="left"), lane_width_left=1.0, lane_width_right=3.6)
  out = NavPassingAdvisor().update(i, 0.0)
  assert out["armed"] and out["side"] == "right" and out["phase"] == "exit"


# D-115 keep-right reminder
def keep_inputs(**kw):
  base = dict(enabled=False, keep_right=True, lead=Lead(False), v_ego=LIMIT)
  base.update(kw)
  return inputs(**base)


def test_keep_right_after_a_minute_then_shows_and_cools_down():
  adv = NavPassingAdvisor()
  out, t = run(adv, keep_inputs(), 0.0, KEEP_RIGHT_SECONDS - 1.0)
  assert not out["armed"]
  out, t = run(adv, keep_inputs(), t, 1.5)
  assert out["armed"] and out["side"] == "right" and out["phase"] == "keepright"
  out, t = run(adv, keep_inputs(), t, KEEP_RIGHT_SHOW_S)
  assert not out["armed"]
  out, t = run(adv, keep_inputs(), t, KEEP_RIGHT_COOLDOWN_S - KEEP_RIGHT_SHOW_S - 5.0)
  assert not out["armed"]


def test_keep_right_ends_on_blinker():
  adv = NavPassingAdvisor()
  out, t = run(adv, keep_inputs(), 0.0, KEEP_RIGHT_SECONDS + 1.0)
  assert out["armed"]
  assert not adv.update(keep_inputs(right_blinker=True), t)["armed"]
  assert not adv.update(keep_inputs(), t + 0.5)["armed"]


def test_keep_right_blocked_cases():
  cases = [
    {"keep_right": False},
    {"vasm_live": False},
    {"lane_width_right": 1.0},                                   # already rightmost
    {"edge_gap_right": 0.3},                                     # right "lane" is the shoulder
    {"blocked_right": True},
    {"lead_right": Lead(True, 60.0, LIMIT - 10 * MPH)},          # right lane is slower
    {"lead": Lead(True, 30.0, 50 * MPH), "v_ego": 50 * MPH},     # stuck behind a slow lead
    {"speed_limit": 35 * MPH},
    {"nav_state": dict(NAV, maneuverModifier="slight left", maneuverDistance=1000.0)},
  ]
  for kw in cases:
    adv = NavPassingAdvisor()
    out, _ = run(adv, keep_inputs(**kw), 0.0, KEEP_RIGHT_SECONDS + 5.0)
    assert not out["armed"], kw


def test_keep_right_allows_a_faster_right_lane_car():
  adv = NavPassingAdvisor()
  out, _ = run(adv, keep_inputs(lead_right=Lead(True, 60.0, LIMIT + 2 * MPH)), 0.0, KEEP_RIGHT_SECONDS + 1.0)
  assert out["armed"]


def test_edge_gap_measures_road_edge_beyond_the_outer_line_at_20m():
  x = [0.0, 10.0, 20.0, 40.0]
  assert abs(edge_gap(x, [-5.4] * 4, x, [-6.0] * 4) - 0.6) < 1e-6    # left shoulder: edge just past the line
  assert abs(edge_gap(x, [5.4] * 4, x, [9.0] * 4) - 3.6) < 1e-6      # real lane: shoulder-width gap beyond it
