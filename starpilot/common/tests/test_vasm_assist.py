import pytest

from openpilot.starpilot.common.vasm_assist import (
  FOCUS_LEAD_DIST, PASS_HOLD_MAX_S, PASS_HOLD_MIN_S, AdjacentLead, PassHold, focus_sides, pass_hold_seconds, pick_image_side,
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
