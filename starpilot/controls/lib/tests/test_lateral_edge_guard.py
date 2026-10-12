from types import SimpleNamespace

from cereal import log
from openpilot.common.realtime import DT_MDL
from openpilot.starpilot.controls.lib.lateral_edge_guard import (
  MIN_ACTIVE_SPEED_MPS,
  REQUIRED_ROAD_EDGE_DISTANCE_M,
  LateralEdgeGuard,
  RoadEdgeDataState,
  evaluate_road_edge,
)

LEFT = log.LaneChangeDirection.left
RIGHT = log.LaneChangeDirection.right
SPEED = MIN_ACTIVE_SPEED_MPS + 5.0


def _edge(y):
  xs = [float(x) for x in range(0, 55, 5)]
  return SimpleNamespace(x=xs, y=[y] * len(xs))


def model(left=-8.0, right=8.0, std=0.2, outer_probs=(0.0, 0.0)):
  return SimpleNamespace(roadEdges=[_edge(left), _edge(right)], roadEdgeStds=[std, std],
                         laneLines=[_edge(-5.4), _edge(-1.8), _edge(1.8), _edge(5.4)],
                         laneLineProbs=[outer_probs[0], 0.9, 0.9, outer_probs[1]])


def run(guard, md, frames, v=SPEED):
  for _ in range(frames):
    guard.update(md, v, DT_MDL)


def test_edge_inside_one_lane_blocks_and_far_edge_does_not():
  near = evaluate_road_edge(_edge(-4.0), 0.2, LEFT)
  assert near.state == RoadEdgeDataState.VALID and near.should_block
  far = evaluate_road_edge(_edge(-8.0), 0.2, LEFT)
  assert far.state == RoadEdgeDataState.VALID and not far.should_block
  assert REQUIRED_ROAD_EDGE_DISTANCE_M == 3.5 + 0.95 + 0.25


def test_bad_or_wrong_side_edge_never_blocks():
  assert evaluate_road_edge(_edge(-4.0), 1.5, LEFT).state == RoadEdgeDataState.INVALID
  assert evaluate_road_edge(_edge(4.0), 0.2, LEFT).state == RoadEdgeDataState.INVALID
  assert evaluate_road_edge(None, None, LEFT).state == RoadEdgeDataState.UNAVAILABLE


def test_disabled_guard_never_blocks():
  guard = LateralEdgeGuard()
  run(guard, model(left=-4.0), 40)
  assert not guard.block_for_direction(LEFT)


def test_block_debounce_and_side_selection():
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-4.0), 5)
  assert not guard.block_for_direction(LEFT), "0.25 s is under the 0.30 s block debounce"
  run(guard, model(left=-4.0), 1)
  assert guard.block_for_direction(LEFT)
  assert not guard.block_for_direction(RIGHT)


def test_clear_debounce_and_missing_model_falls_back_to_not_blocking():
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-4.0), 6)
  run(guard, model(), 9)
  assert guard.block_for_direction(LEFT), "0.45 s is under the 0.50 s clear debounce"
  run(guard, model(), 1)
  assert not guard.block_for_direction(LEFT)
  run(guard, model(left=-4.0), 6)
  run(guard, None, 10)
  assert not guard.block_for_direction(LEFT)


def test_visible_outer_lane_line_or_low_speed_does_not_block():
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-4.0, outer_probs=(0.9, 0.0)), 20)
  assert not guard.block_for_direction(LEFT)
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-4.0), 20, v=MIN_ACTIVE_SPEED_MPS - 1.0)
  assert not guard.block_for_direction(LEFT)


def test_update_enabled_argument_turns_guard_off_and_resets():
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-4.0), 6)
  assert guard.block_for_direction(LEFT)
  guard.update(model(left=-4.0), SPEED, DT_MDL, enabled=False)
  assert not guard.block_for_direction(LEFT)


def test_missing_edge_holds_the_last_answer_for_half_a_second():
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-4.0), 6)
  run(guard, None, 9)
  assert guard.block_for_direction(LEFT), "0.45 s of missing data keeps the block"
  run(guard, None, 1)
  assert not guard.block_for_direction(LEFT), "0.50 s falls back to not blocking"


def test_invalid_edge_starts_the_clear_debounce_instead_of_the_hold():
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-4.0), 6)
  run(guard, model(left=-4.0, std=1.5), 9)
  assert guard.block_for_direction(LEFT)
  run(guard, model(left=-4.0, std=1.5), 1)
  assert not guard.block_for_direction(LEFT)


def test_measured_lane_width_is_clamped_and_falls_back():
  md = model()
  md.laneLines[1] = _edge(-3.0)
  md.laneLines[2] = _edge(3.0)
  assert LateralEdgeGuard._lane_width(md) == 4.5
  md.laneLines[2] = _edge(-2.0)
  assert LateralEdgeGuard._lane_width(md) == 2.5
  md.laneLineProbs[1] = 0.5
  assert LateralEdgeGuard._lane_width(md) == 3.5, "ego line prob must exceed 0.5"


def test_wider_measured_lane_moves_the_block_threshold():
  md = model(left=-5.0)
  md.laneLines[1] = _edge(-2.2)
  md.laneLines[2] = _edge(2.2)
  # 5.0 - 0.2 = 4.8 clears the default 4.7 but not 4.4 + 0.95 + 0.25 = 5.6
  guard = LateralEdgeGuard(enabled=True)
  run(guard, model(left=-5.0), 10)
  assert not guard.block_for_direction(LEFT)
  run(guard, md, 6)
  assert guard.block_for_direction(LEFT)
