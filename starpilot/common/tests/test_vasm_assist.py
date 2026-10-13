import pytest

from openpilot.starpilot.common.vasm_assist import (
  FOCUS_LEAD_DIST, LONG_VEHICLE_CLEAR_M, LONG_VEHICLE_MAX_S, PASS_BRIDGE_S,
  PASS_HOLD_MAX_S, PASS_HOLD_MIN_S, AdjacentLead, PassHold, focus_sides, pass_hold_seconds, pick_image_side,
)

MPH = 0.44704


def test_d118_hold_scales_with_how_fast_you_pass():
  assert pass_hold_seconds(0.0, 5 * MPH) == pytest.approx(12.0 / (5 * MPH))  # ~5.4 s
  assert pass_hold_seconds(0.0, 3 * MPH) == PASS_HOLD_MAX_S, "slow pass: capped"
  assert pass_hold_seconds(0.0, 10 * MPH) == pytest.approx(12.0 / (10 * MPH))  # ~2.7 s
  assert pass_hold_seconds(0.0, 30 * MPH) == PASS_HOLD_MIN_S, "fast pass: floor"
  assert pass_hold_seconds(5.0, 10 * MPH) > pass_hold_seconds(0.0, 10 * MPH), "last seen further ahead: longer"


def _passed_car(d_rel=3.0, v_rel=-10 * MPH, track_id=7):
  return AdjacentLead(True, d_rel, v_rel, track_id)


def test_d118_radar_losing_a_car_we_were_passing_holds_that_side():
  hold = PassHold()
  assert not hold.update("right", _passed_car(d_rel=8.0), 0.0)
  assert not hold.update("right", _passed_car(d_rel=3.0), 0.5)
  assert hold.update("right", None, 0.6), "radar lost it right beside us"
  expected_end = 0.5 + pass_hold_seconds(3.0, 10 * MPH)
  assert hold.update("right", None, expected_end - 0.05)
  assert not hold.update("right", None, expected_end + 0.05)
  assert not hold.update("left", None, 0.6), "only the side we passed on"


def test_d118_a_different_car_replacing_it_also_starts_the_hold():
  hold = PassHold()
  hold.update("left", _passed_car(track_id=7), 0.0)
  assert hold.update("left", AdjacentLead(True, 40.0, 0.0, 9), 0.1)


def test_d118_no_hold_without_a_close_recent_pass():
  far = PassHold()
  far.update("left", _passed_car(d_rel=30.0), 0.0)
  assert not far.update("left", None, 0.1), "last seen 30 m ahead: not about to be beside us"

  not_passing = PassHold()
  not_passing.update("left", _passed_car(v_rel=+1.0), 0.0)
  assert not not_passing.update("left", None, 0.1), "it was pulling away, not being passed"

  stale = PassHold()
  stale.update("left", _passed_car(), 0.0)
  stale.update("left", AdjacentLead(False, 0.0, 0.0), 0.1)  # lost, hold starts from the 0.0 sighting
  assert stale.update("left", None, 0.2)

  pulled_away = PassHold()
  pulled_away.update("left", _passed_car(), 0.0)
  pulled_away.update("left", _passed_car(v_rel=+2.0), 0.1)
  assert not pulled_away.update("left", None, 0.2), "same car sped up before radar lost it"


def test_d118_vision_only_leads_compare_by_distance():
  hold = PassHold()
  hold.update("left", AdjacentLead(True, 4.0, -3.0, -1), 0.0)
  assert not hold.update("left", AdjacentLead(True, 3.0, -3.0, -1), 0.1), "same car, closer"
  assert hold.update("left", AdjacentLead(True, 25.0, -3.0, -1), 0.2), "a jump means radar lost it"


def test_d118_reset_clears_holds():
  hold = PassHold()
  hold.update("left", _passed_car(), 0.0)
  assert hold.update("left", None, 0.1)
  hold.reset()
  assert not hold.update("left", None, 0.2)


def test_d118_focus_sides():
  none = {"left": None, "right": None}
  assert focus_sides(False, False, none) == set()
  assert focus_sides(True, False, none) == {"left"}
  assert focus_sides(False, False, none, "right") == {"right"}
  near = {"left": AdjacentLead(True, FOCUS_LEAD_DIST - 1, 0.0), "right": AdjacentLead(True, FOCUS_LEAD_DIST + 1, 0.0)}
  assert focus_sides(False, False, near) == {"left"}
  assert focus_sides(False, False, {"left": AdjacentLead(False, 2.0, 0.0), "right": None}) == set()


def test_d118_pick_side_focuses_without_starving_the_other():
  configured = ["left", "right"]
  last = {"left": 9.8, "right": 9.5}
  assert pick_image_side(set(), configured, "left", last, 10.0) == "left", "no focus: normal alternation"
  assert pick_image_side({"left", "right"}, configured, "right", last, 10.0) == "right", "both: alternate"
  assert pick_image_side({"left"}, configured, "right", last, 10.0) == "left"
  assert pick_image_side({"left"}, configured, "left", {"left": 9.8, "right": 9.0}, 10.0) == "right", "other side waited 1 s"
  assert pick_image_side({"left"}, ["left"], "left", last, 10.0) == "left"
  assert pick_image_side({"right"}, ["left"], "left", last, 10.0) == "left", "focused side not configured"


def _drive(hold, t0, t1, v_ego, camera, side="right", dt=0.05):
  """Step the hold from t0 to t1 with no radar car; returns [(t, held)]."""
  out, t = [], t0
  while t < t1 - 1e-9:
    out.append((t, hold.update(side, None, t, v_ego, camera(t))))
    t += dt
  return out


def _handed_off(v_ego=32.0, v_rel=-4.0, d_rel=8.0):
  hold = PassHold()
  assert not hold.update("right", AdjacentLead(True, d_rel, v_rel, 44), 0.0, v_ego)
  return hold


def test_d121_without_v_ego_it_is_the_d118_hold():
  hold = PassHold()
  hold.update("right", _passed_car(d_rel=3.0), 0.0)
  assert hold.update("right", None, 0.1, None, True)
  end = pass_hold_seconds(3.0, 10 * MPH)
  assert hold.update("right", None, end - 0.05, None, True)
  assert not hold.update("right", None, end + 0.05, None, True), "camera alone adds nothing without v_ego"


def test_d121_car_pass_ends_with_the_camera_after_the_bridge():
  # route 324-style car pass: radar loses it at 8 m, camera sees ~2 s at 4 m/s (8 m), then clear
  hold = _handed_off()
  cam = lambda t: 2.0 <= t < 4.0  # noqa: E731
  held = dict(_drive(hold, 0.05, 8.0, 32.0, cam))
  assert all(h for t, h in held.items() if t < 4.0)
  assert all(h for t, h in held.items() if 4.0 <= t <= 4.0 + PASS_BRIDGE_S - 0.06)
  plain_end = pass_hold_seconds(8.0, 4.0)  # 5 s: the D-118 hold outlasts this camera pass and its bridge
  assert all(h for t, h in held.items() if t < plain_end - 0.06)
  assert not any(h for t, h in held.items() if t > plain_end + 0.06), "a car is not held like a truck"


def test_d121_bridges_a_short_drop_out_on_a_plain_trailer_side():
  # route 324 seg 108: 0.4 s drop-out mid-trailer after the plain hold had ended
  hold = _handed_off(v_rel=-4.6, d_rel=8.9)
  cam = lambda t: 2.2 <= t < 5.7 or 6.1 <= t < 8.0  # noqa: E731
  held = dict(_drive(hold, 0.05, 8.0, 32.4, cam))
  assert all(h for t, h in held.items() if 2.2 <= t < 8.0)


def test_d121_long_drop_out_is_not_bridged():
  hold = _handed_off(v_rel=-8.0, d_rel=2.0)  # D-118 hold ends at 1.75 s
  cam = lambda t: 1.0 <= t < 1.5 or t >= 3.5  # noqa: E731
  held = dict(_drive(hold, 0.05, 4.0, 32.0, cam))
  assert held[min(held, key=lambda t: abs(t - 2.0))], "inside the bridge"
  assert not held[min(held, key=lambda t: abs(t - 2.5))], "a 2 s gap is not bridged"


def test_d121_semi_is_held_until_its_front_is_well_behind():
  # route 324 seg 101: radar lost it at 8.7 m closing 3.0 m/s; we sped up 31.4 -> 33 m/s; camera on 3.2-10.4 s
  hold = _handed_off(v_ego=31.4, v_rel=-3.0, d_rel=8.7)
  v = lambda t: 31.4 + 1.6 * min(t / 10.4, 1.0)  # noqa: E731
  out, t = [], 0.05
  while t < 20.0:
    out.append((t, hold.update("right", None, t, v(t), 3.2 <= t < 10.4)))
    t += 0.05
  end = max(t for t, h in out if h)
  assert end > 10.4 + 1.0, "held past the camera losing the tractor"
  # dead-reckoned: rear at -LONG_VEHICLE_CLEAR_M when the integrated closing covers d_rel + 38 m
  d, t = 8.7, 0.0
  while d > -LONG_VEHICLE_CLEAR_M:
    d -= (v(t) - (31.4 - 3.0)) * 0.05
    t += 0.05
  assert end == pytest.approx(t, abs=0.15)


def test_d121_semi_hold_is_capped_when_the_gap_stops_closing():
  hold = _handed_off(v_ego=32.0, v_rel=-4.0)
  out = _drive(hold, 0.05, LONG_VEHICLE_MAX_S + 5, 32.0, lambda t: 1.0 <= t < 6.0)  # 20 m seen
  # then we slow to the truck's speed: it never slides back
  hold2 = _handed_off(v_ego=32.0, v_rel=-4.0)
  out = _drive(hold2, 0.05, 6.0, 32.0, lambda t: 1.0 <= t < 6.0)
  out += _drive(hold2, 6.0, LONG_VEHICLE_MAX_S + 5, 28.0, lambda t: False)
  assert dict(out)[min(dict(out), key=lambda t: abs(t - (LONG_VEHICLE_MAX_S - 1)))]
  assert not out[-1][1], "capped"


def test_d121_reset_drops_a_followed_vehicle():
  hold = _handed_off()
  _drive(hold, 0.05, 6.0, 32.0, lambda t: 1.0 <= t < 6.0)
  hold.reset()
  assert not hold.update("right", None, 6.05, 32.0, False)
