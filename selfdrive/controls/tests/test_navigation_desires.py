from types import SimpleNamespace

from cereal import log

from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper, LaneChangeDirection, LaneChangeState


def make_car_state(**overrides):
  defaults = {
    "vEgo": 20.0,
    "leftBlinker": False,
    "rightBlinker": False,
    "leftBlindspot": False,
    "rightBlindspot": False,
    "steeringPressed": False,
    "steeringTorque": 0.0,
    "standstill": False,
    "cruiseState": SimpleNamespace(enabled=True),
  }
  defaults.update(overrides)
  return SimpleNamespace(**defaults)


def make_toggles(**overrides):
  defaults = {
    "lane_changes": True,
    "lane_change_delay": 0.0,
    "lane_detection_width": 3.0,
    "minimum_lane_change_speed": 10.0,
    "nudgeless": True,
    "nudgeless_lane_change_only_when_engaged": False,
    "one_lane_change": False,
    "use_turn_desires": False,
    "lane_changes_require_cruise": False,
    "nav_desires_allowed": True,
    "nav_lane_positioning_allowed": True,
  }
  defaults.update(overrides)
  return SimpleNamespace(**defaults)


def make_plan(**overrides):
  defaults = {
    "laneWidthLeft": 4.0,
    "laneWidthRight": 4.0,
  }
  defaults.update(overrides)
  return SimpleNamespace(**defaults)

def test_nav_desires_keep_left_when_route_requests_it():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "slightLeft"}

  helper.update(
    make_car_state(vEgo=20.0, steeringPressed=True, steeringTorque=1.0),
    True,
    0.0,
    make_plan(laneWidthLeft=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.keepLeft
  assert helper.nav_desire == log.Desire.keepLeft, "published so the map can show the route is steering the model"


def test_nav_desires_turn_right_below_lane_change_speed():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "right", "maneuverDistance": 10.0}

  helper.update(
    make_car_state(vEgo=5.0, rightBlinker=True),
    True,
    0.0,
    make_plan(),
    make_toggles(minimum_lane_change_speed=10.0, nav_lane_positioning_allowed=False),
  )

  assert helper.desire == log.Desire.turnRight


def test_nav_desires_turn_requires_matching_blinker():
  for modifier, opposite_blinker in (("left", "rightBlinker"), ("right", "leftBlinker")):
    helper = DesireHelper()
    helper.nav_desires_allowed = True
    helper._update_nav_params = lambda: None
    helper._nav_instruction_state = {"valid": True, "maneuverModifier": modifier, "maneuverDistance": 10.0}

    helper.update(
      make_car_state(vEgo=5.0, **{opposite_blinker: True}),
      True,
      0.0,
      make_plan(),
      make_toggles(minimum_lane_change_speed=10.0, nav_lane_positioning_allowed=False),
    )

    assert helper.desire == log.Desire.none


def test_nav_desires_turn_right_waits_until_turn_is_close():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "right", "maneuverDistance": 300.0}

  helper.update(
    make_car_state(vEgo=5.0),
    True,
    0.0,
    make_plan(),
    make_toggles(minimum_lane_change_speed=10.0),
  )

  assert helper.desire == log.Desire.none


def test_nav_desires_off_ramp_lane_guidance_becomes_keep_right():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "activeLaneDirection": "slightRight",
    "maneuverDistance": 120.0,
  }

  helper.update(
    make_car_state(vEgo=22.5, steeringPressed=True, steeringTorque=-1.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.keepRight


def test_nav_desires_off_ramp_lane_guidance_waits_until_split_is_close():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "activeLaneDirection": "slightRight",
    "maneuverDistance": 300.0,
  }

  helper.update(
    make_car_state(vEgo=22.5),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.none


def test_nav_desires_ambiguous_off_ramp_waits_longer_before_keep_right():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "activeLaneDirection": "slightRight",
    "sameSideLaneCount": 3,
    "maneuverDistance": 120.0,
  }

  helper.update(
    make_car_state(vEgo=22.5),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.none


def test_nav_desires_edge_exit_lane_with_shared_transition_lane_does_not_keep_right():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "activeLaneDirection": "slightRight",
    "laneCount": 3,
    "sameSideLaneCount": 2,
    "activeLaneAtRoadEdge": True,
    "hasSharedSameSideLane": True,
    "maneuverDistance": 10.0,
  }

  helper.update(
    make_car_state(vEgo=22.5),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.none


def test_nav_desires_wide_highway_edge_exit_lane_keeps_right():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "activeLaneDirection": "slightRight",
    "laneCount": 7,
    "sameSideLaneCount": 2,
    "activeLaneAtRoadEdge": True,
    "hasSharedSameSideLane": True,
    "maneuverDistance": 105.0,
  }

  helper.update(
    make_car_state(vEgo=19.0, steeringPressed=True, steeringTorque=-1.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.keepRight


def test_nav_desires_shared_transition_lane_keeps_when_active_lane_is_not_outermost():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "activeLaneDirection": "slightRight",
    "sameSideLaneCount": 2,
    "activeLaneAtRoadEdge": False,
    "hasSharedSameSideLane": True,
    "maneuverDistance": 10.0,
  }

  helper.update(
    make_car_state(vEgo=22.5, steeringPressed=True, steeringTorque=-1.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.keepRight


def test_nav_desires_ambiguous_fork_slight_right_only_keeps_close_to_split():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "fork",
    "maneuverModifier": "slightRight",
    "activeLaneDirection": "slightRight",
    "sameSideLaneCount": 3,
    "maneuverDistance": 60.0,
  }

  helper.update(
    make_car_state(vEgo=22.5, steeringPressed=True, steeringTorque=-1.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.keepRight


def test_nav_desires_ambiguous_fork_slight_right_does_not_nudge_too_early():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "fork",
    "maneuverModifier": "slightRight",
    "activeLaneDirection": "slightRight",
    "sameSideLaneCount": 3,
    "maneuverDistance": 120.0,
  }

  helper.update(
    make_car_state(vEgo=22.5),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nudgeless=True),
  )

  assert helper.desire == log.Desire.none


def test_nav_desires_fork_with_active_straight_lane_does_not_turn_left():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "fork",
    "maneuverModifier": "left",
    "activeLaneDirection": "straight",
    "maneuverDistance": 15.0,
  }

  helper.update(
    make_car_state(vEgo=5.0),
    True,
    0.0,
    make_plan(laneWidthLeft=4.2),
    make_toggles(nudgeless=True, minimum_lane_change_speed=10.0),
  )

  assert helper.desire == log.Desire.none


def test_nav_desires_do_not_override_lane_change_state_machine():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "slightRight"}
  helper.lane_change_state = LaneChangeState.laneChangeStarting
  helper.lane_change_direction = LaneChangeDirection.left
  helper.lane_change_ll_prob = 0.5

  helper.update(
    make_car_state(vEgo=25.0, leftBlinker=True),
    True,
    0.5,
    make_plan(),
    make_toggles(),
  )

  assert helper.desire == log.Desire.laneChangeLeft


def test_lane_changes_require_cruise_blocks_blinker_lane_change_without_cruise():
  helper = DesireHelper()

  helper.update(
    make_car_state(leftBlinker=True, cruiseState=SimpleNamespace(enabled=False)),
    True,
    0.0,
    make_plan(),
    make_toggles(lane_changes_require_cruise=True),
  )

  assert helper.lane_change_state == LaneChangeState.off
  assert helper.lane_change_direction == LaneChangeDirection.none
  assert helper.desire == log.Desire.none


def test_lane_changes_require_cruise_allows_blinker_lane_change_with_cruise():
  helper = DesireHelper()

  helper.update(
    make_car_state(leftBlinker=True, cruiseState=SimpleNamespace(enabled=True)),
    True,
    0.0,
    make_plan(),
    make_toggles(lane_changes_require_cruise=True),
  )

  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.lane_change_direction == LaneChangeDirection.left


def test_lane_changes_without_cruise_requirement_keep_existing_behavior():
  helper = DesireHelper()

  helper.update(
    make_car_state(leftBlinker=True, cruiseState=SimpleNamespace(enabled=False)),
    True,
    0.0,
    make_plan(),
    make_toggles(lane_changes_require_cruise=False),
  )

  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.lane_change_direction == LaneChangeDirection.left


def test_nudgeless_only_when_engaged_allows_automatic_lane_change_when_engaged():
  helper = DesireHelper()

  for _ in range(2):
    helper.update(
      make_car_state(leftBlinker=True),
      True,
      0.0,
      make_plan(),
      make_toggles(nudgeless_lane_change_only_when_engaged=True),
      controls_enabled=True,
    )

  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  assert helper.lane_change_direction == LaneChangeDirection.left


def test_nudgeless_only_when_engaged_requires_nudge_when_aol_only():
  helper = DesireHelper()
  toggles = make_toggles(nudgeless_lane_change_only_when_engaged=True)

  for _ in range(2):
    helper.update(
      make_car_state(leftBlinker=True),
      True,
      0.0,
      make_plan(),
      toggles,
      controls_enabled=False,
    )

  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.lane_change_direction == LaneChangeDirection.left

  helper.update(
    make_car_state(leftBlinker=True, steeringPressed=True, steeringTorque=1.0),
    True,
    0.0,
    make_plan(),
    toggles,
    controls_enabled=False,
  )

  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  assert helper.lane_change_direction == LaneChangeDirection.left


def test_lane_change_nudge_uses_raw_torque_threshold():
  helper = DesireHelper()
  toggles = make_toggles(nudgeless_lane_change_only_when_engaged=True)

  for _ in range(2):
    helper.update(
      make_car_state(leftBlinker=True),
      True,
      0.0,
      make_plan(),
      toggles,
      controls_enabled=False,
    )

  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.lane_change_direction == LaneChangeDirection.left

  helper.update(
    make_car_state(leftBlinker=True, steeringPressed=False, steeringTorque=1300.0),
    True,
    0.0,
    make_plan(),
    toggles,
    controls_enabled=False,
  )

  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  assert helper.lane_change_direction == LaneChangeDirection.left


def test_nav_desires_nudgeless_only_when_engaged_blocks_keep_when_aol_only():
  helper = DesireHelper()
  helper.nav_desires_allowed = True
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "slightLeft"}

  helper.update(
    make_car_state(vEgo=20.0),
    True,
    0.0,
    make_plan(laneWidthLeft=4.2),
    make_toggles(nudgeless=True, nudgeless_lane_change_only_when_engaged=True),
    controls_enabled=False,
  )

  assert helper.desire == log.Desire.none

  helper.update(
    make_car_state(vEgo=20.0, steeringPressed=True, steeringTorque=-1.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nav_desires_allowed=True, nav_lane_positioning_allowed=False, nudgeless=True),
  )

  assert helper.desire == log.Desire.none


def test_turn_desire_fires_below_lane_change_speed_when_no_stop():
  helper = DesireHelper()

  helper.update(
    make_car_state(vEgo=5.0, rightBlinker=True),
    True,
    0.0,
    make_plan(),
    make_toggles(use_turn_desires=True, minimum_lane_change_speed=10.0),
  )

  assert helper.desire == log.Desire.turnRight


def test_nav_desires_disabled_leave_desire_unchanged():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "left"}

  helper.update(
    make_car_state(vEgo=5.0),
    True,
    0.0,
    make_plan(),
    make_toggles(minimum_lane_change_speed=10.0, nav_desires_allowed=False),
  )

  assert helper.desire == log.Desire.none


def test_disabling_nav_desires_clears_active_route_desire_immediately():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "slightRight"}
  car_state = make_car_state(vEgo=20.0, steeringPressed=True, steeringTorque=-1.0)
  plan = make_plan(laneWidthRight=4.2)

  helper.update(car_state, True, 0.0, plan, make_toggles(nav_desires_allowed=True, nav_lane_positioning_allowed=True))
  assert helper.desire == log.Desire.keepRight

  helper.update(car_state, True, 0.0, plan, make_toggles(nav_desires_allowed=False, nav_lane_positioning_allowed=True))
  assert helper.desire == log.Desire.none


def test_nav_lane_positioning_requires_driver_confirmation():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "slightRight"}

  helper.update(
    make_car_state(vEgo=20.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nav_desires_allowed=True, nav_lane_positioning_allowed=True, nudgeless=True),
  )

  assert helper.desire == log.Desire.none

  helper.update(
    make_car_state(vEgo=20.0, steeringPressed=True, steeringTorque=-1.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.2),
    make_toggles(nav_desires_allowed=True, nav_lane_positioning_allowed=False, nudgeless=True),
  )

  assert helper.desire == log.Desire.none


def test_nav_exit_lane_change_enters_pre_lane_change_and_requires_blinker():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "maneuverDistance": 300.0,
  }

  toggles = make_toggles(nav_desires_allowed=True, nav_exit_lane_change=True, nudgeless=True)

  # Frame 1: Car approaching exit without steering nudge -> enters preLaneChange, but does NOT launch into starting
  helper.update(
    make_car_state(vEgo=25.0, steeringPressed=False, steeringTorque=0.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.0),
    toggles,
  )

  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.lane_change_direction == LaneChangeDirection.right
  assert helper.nav_exit_lane_change is True

  # Frame 2: Even with nudgeless enabled, nav exit lane change refuses to launch without the driver's blinker
  helper.update(
    make_car_state(vEgo=25.0, steeringPressed=False, steeringTorque=0.0),
    True,
    0.0,
    make_plan(laneWidthRight=4.0),
    toggles,
  )

  assert helper.lane_change_state == LaneChangeState.preLaneChange

  # Frame 3: a steering nudge alone no longer confirms a nav exit lane change
  helper.update(
    make_car_state(vEgo=25.0, steeringPressed=True, steeringTorque=-1.5),
    True,
    0.0,
    make_plan(laneWidthRight=4.0),
    toggles,
  )
  assert helper.lane_change_state == LaneChangeState.preLaneChange

  # Frame 4: Driver confirms with the blinker toward the exit -> transitions to laneChangeStarting
  helper.update(
    make_car_state(vEgo=25.0, rightBlinker=True),
    True,
    0.0,
    make_plan(laneWidthRight=4.0),
    toggles,
  )

  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  assert helper.nav_exit_lane_change is True
  assert helper.lane_change_direction == LaneChangeDirection.right


def test_nav_exit_lane_change_blocked_by_vision_asm():
  import time
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {
    "valid": True,
    "maneuverType": "off ramp",
    "maneuverModifier": "right",
    "maneuverDistance": 250.0,
  }

  now = time.monotonic()
  helper.params_memory.put("VASMLastUpdateMonoTime", str(now))
  helper.params_memory.put("VASMRightActive", "1")

  toggles = make_toggles(nav_desires_allowed=True, nav_exit_lane_change=True, v_asm_enabled=True)

  # Frame 1: Enter preLaneChange
  helper.update(
    make_car_state(vEgo=25.0, rightBlindspot=False),
    True,
    0.0,
    make_plan(laneWidthRight=4.0),
    toggles,
  )
  assert helper.lane_change_state == LaneChangeState.preLaneChange

  # Frame 2: Driver signals right, but Vision ASM detects obstacle -> stays blocked in preLaneChange!
  helper.update(
    make_car_state(vEgo=25.0, rightBlindspot=False, rightBlinker=True),
    True,
    0.0,
    make_plan(laneWidthRight=4.0),
    toggles,
  )
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def _prompt_helper():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverType": "off ramp", "maneuverModifier": "right", "maneuverDistance": 900.0}
  published = []
  helper.params_memory.put_nonblocking = lambda k, v: published.append((k, v))
  return helper, published


def test_lane_move_prompt_marks_blocked_when_blindspot_occupied():
  helper, published = _prompt_helper()
  toggles = make_toggles(nav_desires_allowed=True)
  helper._publish_lane_move_prompt(make_car_state(vEgo=25.0, rightBlindspot=True), make_plan(laneWidthRight=4.0), toggles, True)
  key, prompt = published[-1]
  assert key == "NavLaneMovePrompt" and prompt["armed"] and prompt["side"] == "right" and prompt["blocked"]
  helper._publish_lane_move_prompt(make_car_state(vEgo=25.0, rightBlindspot=False), make_plan(laneWidthRight=4.0), toggles, True)
  assert published[-1][1]["armed"] and not published[-1][1]["blocked"]
  helper._publish_lane_move_prompt(make_car_state(vEgo=25.0, leftBlindspot=True), make_plan(laneWidthRight=4.0), toggles, True)
  assert not published[-1][1]["blocked"]


def test_prompted_lane_move_blocked_by_blindspot_until_clear():
  helper, _ = _prompt_helper()
  toggles = make_toggles(nav_desires_allowed=True)
  plan = make_plan(laneWidthRight=4.0)
  nudge = dict(vEgo=25.0, rightBlinker=True, steeringPressed=True, steeringTorque=-3.0)
  for _ in range(40):
    helper.update(make_car_state(rightBlindspot=True, **nudge), True, 0.0, plan, toggles)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  helper.update(make_car_state(rightBlindspot=False, **nudge), True, 0.0, plan, toggles)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def test_turn_desire_heading_recoil_clears_desire():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverModifier": "right", "maneuverDistance": 10.0}

  # Turn active with right blinker
  cs = make_car_state(vEgo=5.0, rightBlinker=True, yawRate=0.0)
  helper.update(cs, True, 0.0, make_plan(), make_toggles(minimum_lane_change_speed=10.0))
  assert helper.desire == log.Desire.turnRight

  # Vehicle turns sharply past 55 degrees heading recoil (yawRate = 1.5 rad/s * 0.05s * 15 frames = 1.125 rad > 0.96 rad)
  for _ in range(15):
    cs_turning = make_car_state(vEgo=5.0, rightBlinker=True, yawRate=1.5)
    helper.update(cs_turning, True, 0.0, make_plan(), make_toggles(minimum_lane_change_speed=10.0))

  # Desire must recoil to none so the car does not overshoot past apex
  assert helper.desire == log.Desire.none


def test_turn_desire_pulse_resets_between_turns():
  # IQ.Pilot runs the pulse every frame; a non-turn frame must clear the recoil so the next turn fires
  helper = DesireHelper()
  toggles = make_toggles(use_turn_desires=True)
  turning = make_car_state(vEgo=5.0, leftBlinker=True, yawRate=0.3)
  for _ in range(80):
    helper.update(turning, True, 0.0, make_plan(), toggles)
  assert helper.desire == log.Desire.none
  for _ in range(20):
    helper.update(make_car_state(vEgo=5.0, yawRate=0.0), True, 0.0, make_plan(), toggles)
  helper.update(turning, True, 0.0, make_plan(), toggles)
  assert helper.desire == log.Desire.turnLeft


def test_turn_recoil_prefers_model_yaw_rate():
  helper = DesireHelper()
  helper._last_modeldata = SimpleNamespace(orientationRate=SimpleNamespace(z=[0.7]))
  assert helper._measured_yaw_rate(SimpleNamespace(yawRate=0.1)) == 0.7
  helper._last_modeldata = None
  assert helper._measured_yaw_rate(SimpleNamespace(yawRate=0.1)) == 0.1


def test_nav_exit_lane_change_only_on_rising_edge():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverType": "off ramp", "maneuverModifier": "slight right", "maneuverDistance": 400.0}
  toggles = make_toggles(nav_exit_lane_change=True, nudgeless=False)
  helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  helper.update(make_car_state(vEgo=25.0), False, 0.0, make_plan(), toggles)
  for _ in range(5):
    helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.off


def test_nav_exit_lane_change_ignores_forks():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverType": "fork", "maneuverModifier": "slightRight", "maneuverDistance": 400.0}
  helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), make_toggles(nav_exit_lane_change=True))
  assert helper.lane_change_state == LaneChangeState.off


def test_nav_exit_opposite_blinker_becomes_normal_lane_change():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverType": "off ramp", "maneuverModifier": "right", "maneuverDistance": 300.0}
  toggles = make_toggles(nav_exit_lane_change=True, nudgeless=False)
  helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), toggles)
  assert helper.nav_exit_lane_change is True
  helper.update(make_car_state(vEgo=25.0, leftBlinker=True), True, 0.0, make_plan(laneWidthLeft=4.0), toggles)
  assert helper.nav_exit_lane_change is False
  assert helper.lane_change_direction == LaneChangeDirection.left
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def test_nav_exit_second_lane_needs_nudge_with_blinker():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverType": "off ramp", "maneuverModifier": "right", "maneuverDistance": 400.0}
  toggles = make_toggles(nav_exit_lane_change=True, nudgeless=True)
  helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), toggles)
  helper.update(make_car_state(vEgo=25.0, rightBlinker=True), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  for _ in range(300):
    helper.update(make_car_state(vEgo=25.0, rightBlinker=True), True, 0.0, make_plan(), toggles)
    if helper.lane_change_state == LaneChangeState.preLaneChange:
      break
  assert helper.lane_change_state == LaneChangeState.preLaneChange and helper.nav_exit_lane_change
  for _ in range(5):
    helper.update(make_car_state(vEgo=25.0, rightBlinker=True), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  helper.update(make_car_state(vEgo=25.0, rightBlinker=True, steeringPressed=True, steeringTorque=-1.5), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def _exit_state(**overrides):
  state = {"valid": True, "maneuverType": "off ramp", "maneuverModifier": "right", "maneuverDistance": 80.0,
           "activeLaneDirection": "slightRight", "laneCount": 2, "sameSideLaneCount": 1,
           "activeLaneAtRoadEdge": True, "hasSharedSameSideLane": True}
  state.update(overrides)
  return state


def _exit_desire(car=None, toggles=None, state=None, plan=None):
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = state or _exit_state()
  helper.update(make_car_state(**(car or {})), True, 0.0, plan or make_plan(laneWidthRight=0.0),
                make_toggles(**{"nav_lane_positioning_allowed": False, "lane_detection_width": 0.0, **(toggles or {})}))
  return helper.desire


def test_nav_exit_auto_keep_takes_same_side_exit_without_nudge_or_blinker():
  assert _exit_desire(toggles={"nav_exit_auto_keep": True}) == log.Desire.keepRight


def test_nav_exit_auto_keep_is_off_by_default():
  assert _exit_desire() == log.Desire.none
  assert _exit_desire(toggles={"nav_exit_auto_keep": False}) == log.Desire.none


def test_nav_exit_auto_keep_gates():
  on = {"nav_exit_auto_keep": True}
  assert _exit_desire(car={"rightBlindspot": True}, toggles=on) == log.Desire.none
  assert _exit_desire(car={"leftBlinker": True}, toggles=on) == log.Desire.none
  assert _exit_desire(car={"vEgo": 5.0}, toggles=on) == log.Desire.none
  assert _exit_desire(state=_exit_state(maneuverDistance=300.0), toggles=on) == log.Desire.none
  assert _exit_desire(state=_exit_state(maneuverType="turn"), toggles=on) == log.Desire.none


def test_nav_exit_auto_keep_follows_a_fork():
  # D-119: route 325 seg 54, fork/right with lane guidance marking the right branch; D-107 left it to a wheel nudge
  on = {"nav_exit_auto_keep": True}
  assert _exit_desire(state=_exit_state(maneuverType="fork"), toggles=on) == log.Desire.keepRight
  left = _exit_state(maneuverType="fork", maneuverModifier="slightLeft", activeLaneDirection="slightLeft")
  assert _exit_desire(state=left, toggles=on, plan=make_plan(laneWidthLeft=0.0)) == log.Desire.keepLeft
  assert _exit_desire(state=_exit_state(maneuverType="fork")) == log.Desire.none
  assert _exit_desire(car={"rightBlindspot": True}, state=_exit_state(maneuverType="fork"), toggles=on) == log.Desire.none
  assert _exit_desire(car={"steeringPressed": True, "steeringTorque": 1.0}, state=_exit_state(maneuverType="fork"),
                      toggles=on) == log.Desire.none


def test_nav_exit_auto_keep_withdrawn_by_driver_steering():
  on = {"nav_exit_auto_keep": True}
  assert _exit_desire(car={"steeringPressed": True, "steeringTorque": 1.0}, toggles=on) == log.Desire.none
  assert _exit_desire(car={"steeringPressed": True, "steeringTorque": -1.0},
                      toggles={**on, "nav_lane_positioning_allowed": True}) == log.Desire.keepRight


def _started_left_lane_change(toggles):
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  for _ in range(2):
    helper.update(make_car_state(leftBlinker=True), True, 1.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  return helper


def _steer(helper, toggles, torque, frames, **cs):
  for _ in range(frames):
    helper.update(make_car_state(leftBlinker=True, steeringPressed=True, steeringTorque=torque, **cs), True, 1.0, make_plan(), toggles)


def test_counter_torque_cancel_is_off_by_default():
  toggles = make_toggles()
  helper = _started_left_lane_change(toggles)
  _steer(helper, toggles, -1.0, 20)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def test_counter_torque_cancel_needs_quarter_second_of_opposing_torque():
  toggles = make_toggles(lane_change_counter_torque_cancel=True)
  helper = _started_left_lane_change(toggles)
  _steer(helper, toggles, -1.0, 4)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting, "0.20 s is not enough"
  helper.update(make_car_state(leftBlinker=True), True, 1.0, make_plan(), toggles)
  _steer(helper, toggles, -1.0, 4)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting, "a release resets the count"
  _steer(helper, toggles, -1.0, 1)
  assert helper.lane_change_state == LaneChangeState.off, "the fifth frame is 0.25 s"
  assert helper.lane_change_direction == LaneChangeDirection.none
  assert helper.desire == log.Desire.none


def test_counter_torque_cancel_ignores_torque_toward_the_move():
  toggles = make_toggles(lane_change_counter_torque_cancel=True)
  helper = _started_left_lane_change(toggles)
  _steer(helper, toggles, 1.0, 20)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def test_counter_torque_cancel_does_not_relaunch_on_held_blinker():
  toggles = make_toggles(lane_change_counter_torque_cancel=True)
  helper = _started_left_lane_change(toggles)
  _steer(helper, toggles, -1.0, 5)
  assert helper.lane_change_state == LaneChangeState.off
  for _ in range(50):
    helper.update(make_car_state(leftBlinker=True), True, 1.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.off, "needs a fresh blinker press"
  helper.update(make_car_state(), True, 1.0, make_plan(), toggles)
  helper.update(make_car_state(leftBlinker=True), True, 1.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def test_counter_torque_cancel_does_not_relaunch_nav_exit_move():
  toggles = make_toggles(lane_change_counter_torque_cancel=True)
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._get_nav_exit_lane_change_direction = lambda _t: LaneChangeDirection.right
  helper.update(make_car_state(), True, 1.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.preLaneChange and helper.nav_exit_lane_change
  helper.update(make_car_state(rightBlinker=True), True, 1.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  for _ in range(5):
    helper.update(make_car_state(rightBlinker=True, steeringPressed=True, steeringTorque=1.0), True, 1.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.off
  for _ in range(50):
    helper.update(make_car_state(), True, 1.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.off, "the same exit request does not relaunch"


def _edge_model(left_y):
  xs = [float(x) for x in range(0, 55, 5)]

  def edge(y):
    return SimpleNamespace(x=xs, y=[y] * len(xs))
  return SimpleNamespace(roadEdges=[edge(left_y), edge(8.0)], roadEdgeStds=[0.2, 0.2],
                         laneLines=[edge(-5.4), edge(-1.8), edge(1.8), edge(5.4)], laneLineProbs=[0.0, 0.9, 0.9, 0.0])


def _edge_guard_launch(toggles, left_y):
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  md = _edge_model(left_y)
  for _ in range(10):
    helper.update(make_car_state(), True, 1.0, make_plan(), toggles, modeldata=md)
  for _ in range(3):
    helper.update(make_car_state(leftBlinker=True), True, 1.0, make_plan(), toggles, modeldata=md)
  return helper


def test_edge_guard_is_off_by_default():
  assert _edge_guard_launch(make_toggles(), -4.0).lane_change_state == LaneChangeState.laneChangeStarting


def test_edge_guard_holds_lane_change_toward_a_near_road_edge():
  toggles = make_toggles(lane_change_edge_guard=True)
  assert _edge_guard_launch(toggles, -4.0).lane_change_state == LaneChangeState.preLaneChange
  assert _edge_guard_launch(toggles, -8.0).lane_change_state == LaneChangeState.laneChangeStarting


def test_counter_torque_cancel_window_closes_after_one_and_a_half_seconds():
  # on Peter's drives drivers held the wheel against the move while settling into the new lane, after the line
  toggles = make_toggles(lane_change_counter_torque_cancel=True)
  helper = _started_left_lane_change(toggles)
  for _ in range(30):
    helper.update(make_car_state(leftBlinker=True), True, 1.0, make_plan(), toggles)
  _steer(helper, toggles, -1.0, 20)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def _lane_model(left_y):
  def line(y):
    return SimpleNamespace(y=[y])
  return SimpleNamespace(laneLineProbs=[0.9, 0.9, 0.9, 0.9], laneLines=[line(left_y - 3.6), line(left_y), line(left_y + 3.6), line(left_y + 7.2)])


def test_counter_torque_cancel_window_closes_once_the_car_reaches_the_line():
  toggles = make_toggles(lane_change_counter_torque_cancel=True)
  helper = _started_left_lane_change(toggles)
  for left_y in (-1.8, -1.5, -1.2, -0.9):   # the left line closes in as the car moves left
    helper.update(make_car_state(leftBlinker=True), True, 1.0, make_plan(), toggles, modeldata=_lane_model(left_y))
  for _ in range(10):
    helper.update(make_car_state(leftBlinker=True, steeringPressed=True, steeringTorque=-1.0), True, 1.0, make_plan(), toggles,
                  modeldata=_lane_model(-0.9))
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting

  helper2 = _started_left_lane_change(toggles)
  for _ in range(5):
    helper2.update(make_car_state(leftBlinker=True, steeringPressed=True, steeringTorque=-1.0), True, 1.0, make_plan(), toggles,
                   modeldata=_lane_model(-1.7))
  assert helper2.lane_change_state == LaneChangeState.off, "before the line, a firm 0.25 s still cancels"


# D-113: a highway on-ramp is handled the way an off-ramp is

def test_on_ramp_lane_guidance_becomes_keep_right_with_nudge():
  state = _exit_state(maneuverType="on ramp")
  assert _exit_desire(state=state, car={"steeringPressed": True, "steeringTorque": -1.0},
                      toggles={"nav_lane_positioning_allowed": True}) == log.Desire.keepRight


def test_on_ramp_keep_waits_until_split_is_close():
  state = _exit_state(maneuverType="on ramp", maneuverDistance=300.0)
  assert _exit_desire(state=state, car={"steeringPressed": True, "steeringTorque": -1.0},
                      toggles={"nav_lane_positioning_allowed": True}) == log.Desire.none


def test_on_ramp_auto_keep_takes_ramp_without_nudge_or_blinker():
  assert _exit_desire(state=_exit_state(maneuverType="on ramp"), toggles={"nav_exit_auto_keep": True}) == log.Desire.keepRight


def test_on_ramp_auto_keep_is_off_by_default_and_keeps_its_gates():
  state = _exit_state(maneuverType="on ramp")
  on = {"nav_exit_auto_keep": True}
  assert _exit_desire(state=state) == log.Desire.none
  assert _exit_desire(state=state, car={"rightBlindspot": True}, toggles=on) == log.Desire.none
  assert _exit_desire(state=state, car={"leftBlinker": True}, toggles=on) == log.Desire.none
  assert _exit_desire(state=state, car={"vEgo": 5.0}, toggles=on) == log.Desire.none
  assert _exit_desire(state=state, car={"steeringPressed": True, "steeringTorque": 1.0}, toggles=on) == log.Desire.none
  assert _exit_desire(state=_exit_state(maneuverType="on ramp", activeLaneDirection="straight"), toggles=on) == log.Desire.none


def test_on_ramp_without_lane_guidance_enters_pre_lane_change_and_needs_blinker():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverType": "on ramp", "maneuverModifier": "slight right", "maneuverDistance": 400.0}
  toggles = make_toggles(nav_exit_lane_change=True, nudgeless=True)
  helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.lane_change_direction == LaneChangeDirection.right
  for _ in range(5):
    helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  helper.update(make_car_state(vEgo=25.0, rightBlinker=True), True, 0.0, make_plan(), toggles)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def test_merge_is_not_treated_as_a_ramp():
  helper = DesireHelper()
  helper._update_nav_params = lambda: None
  helper._nav_instruction_state = {"valid": True, "maneuverType": "merge", "maneuverModifier": "slight left", "maneuverDistance": 300.0}
  helper.update(make_car_state(vEgo=25.0), True, 0.0, make_plan(), make_toggles(nav_exit_lane_change=True))
  assert helper.lane_change_state == LaneChangeState.off
