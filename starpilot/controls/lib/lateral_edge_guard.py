"""D-110: hold a lane change toward a road edge the model places inside the target lane.

Independent implementation written to match the behavior of IQ.Pilot's lane edge guard (same thresholds,
debounce and fallbacks); no IQ.Pilot code is used. The car-side rule: the conservative distance to the edge
(nearest |y| over the lookahead window, minus one std) must leave room for one lane plus half the car plus a
margin, or the launch is held. It can only hold a lane change, never steer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

from cereal import log
from openpilot.common.constants import CV
from openpilot.common.swaglog import cloudlog

LaneChangeDirection = log.LaneChangeDirection

MIN_ACTIVE_SPEED_MPS = 20.0 * CV.MPH_TO_MS
MAX_VALID_ROAD_EDGE_STD_M = 1.0
EDGE_CONFIDENCE_SIGMA = 1.0
ROAD_EDGE_LOOKAHEAD_MIN_M = 5.0
ROAD_EDGE_LOOKAHEAD_MAX_M = 40.0
LANE_CENTER_OFFSET_M = 3.5          # assumed lane width when the ego lane lines are not trustworthy
VEHICLE_LATERAL_HALF_WIDTH_M = 0.95
EDGE_CLEARANCE_MARGIN_M = 0.25
REQUIRED_ROAD_EDGE_DISTANCE_M = LANE_CENTER_OFFSET_M + VEHICLE_LATERAL_HALF_WIDTH_M + EDGE_CLEARANCE_MARGIN_M
ADJACENT_LANE_LINE_PROB = 0.5       # an outer lane line this likely means there is a lane there after all
EGO_LANE_LINE_PROB_MIN = 0.5
MIN_MEASURED_LANE_WIDTH_M = 2.5
MAX_MEASURED_LANE_WIDTH_M = 4.5
BLOCK_DEBOUNCE_S = 0.30
CLEAR_DEBOUNCE_S = 0.50
UNAVAILABLE_HOLD_S = 0.50
_EPS = 1e-9

# modelV2 index per side: (road edge, outer lane line); ego lane lines are 1 (left) and 2 (right)
_SIDE_INDEX = {LaneChangeDirection.left: (0, 0), LaneChangeDirection.right: (1, 3)}


class RoadEdgeDataState(IntEnum):
  VALID = 0
  UNAVAILABLE = 1   # no usable points: held briefly, then treated as clear
  INVALID = 2       # present but untrustworthy (std, wrong side): treated as clear immediately


@dataclass(frozen=True)
class RoadEdgeMeasurement:
  state: RoadEdgeDataState
  lateral_distance_m: float | None = None
  conservative_distance_m: float | None = None
  should_block: bool = False


def _finite(value) -> float | None:
  try:
    out = float(value)
  except (TypeError, ValueError):
    return None
  return out if math.isfinite(out) else None


def evaluate_road_edge(edge, std_m, direction, lane_width_m: float = LANE_CENTER_OFFSET_M) -> RoadEdgeMeasurement:
  unavailable = RoadEdgeMeasurement(RoadEdgeDataState.UNAVAILABLE)
  invalid = RoadEdgeMeasurement(RoadEdgeDataState.INVALID)
  if edge is None or std_m is None:
    return unavailable
  try:
    points = list(zip(edge.x, edge.y, strict=True))
  except (AttributeError, TypeError, ValueError):
    return unavailable
  if not points:
    return unavailable

  try:
    std = float(std_m)
  except (TypeError, ValueError):
    return invalid
  if not (math.isfinite(std) and 0.0 <= std <= MAX_VALID_ROAD_EDGE_STD_M):
    return invalid

  sign = -1.0 if direction == LaneChangeDirection.left else 1.0
  nearest = math.inf
  for x_raw, y_raw in points:
    x, y = _finite(x_raw), _finite(y_raw)
    if x is None or y is None:
      return unavailable
    if ROAD_EDGE_LOOKAHEAD_MIN_M <= x <= ROAD_EDGE_LOOKAHEAD_MAX_M:
      if sign * y <= 0.0:
        return invalid  # an edge on or past the car's centerline is not this side's edge
      nearest = min(nearest, abs(y))
  if nearest == math.inf:
    return unavailable

  conservative = nearest - EDGE_CONFIDENCE_SIGMA * std
  required = lane_width_m + VEHICLE_LATERAL_HALF_WIDTH_M + EDGE_CLEARANCE_MARGIN_M
  return RoadEdgeMeasurement(RoadEdgeDataState.VALID, nearest, conservative, conservative < required)


class _SideDebounce:
  """Per-side latch: 0.30 s of block evidence sets it, 0.50 s of clear evidence releases it, and missing data
  holds the last answer for 0.50 s before falling back to clear."""

  def __init__(self, name: str):
    self.name = name
    self.reset()

  def reset(self) -> None:
    self.blocked = False
    self.pending_s = 0.0      # time the evidence has disagreed with the latch
    self.missing_s = 0.0
    self.fallback_logged = False

  def step(self, measurement: RoadEdgeMeasurement, dt: float) -> None:
    if measurement.state == RoadEdgeDataState.UNAVAILABLE:
      self.pending_s = 0.0
      self.missing_s += dt
      if self.missing_s >= UNAVAILABLE_HOLD_S - _EPS:
        self.blocked = False
        if not self.fallback_logged:
          self.fallback_logged = True
          cloudlog.warning(f"lateral edge guard: {self.name} road edge unavailable for {UNAVAILABLE_HOLD_S:.2f} s; not blocking")
      return

    self.missing_s = 0.0
    self.fallback_logged = False
    want_block = measurement.state == RoadEdgeDataState.VALID and measurement.should_block
    if want_block == self.blocked:
      self.pending_s = 0.0
      return
    self.pending_s += dt
    if self.pending_s >= (BLOCK_DEBOUNCE_S if want_block else CLEAR_DEBOUNCE_S) - _EPS:
      self.blocked = want_block
      self.pending_s = 0.0


class LateralEdgeGuard:
  def __init__(self, enabled: bool = False) -> None:
    self.enabled = bool(enabled)
    self._was_enabled = False
    self._sides = {LaneChangeDirection.left: _SideDebounce("left"), LaneChangeDirection.right: _SideDebounce("right")}
    self.measurements = {d: RoadEdgeMeasurement(RoadEdgeDataState.UNAVAILABLE) for d in self._sides}

  def _reset(self) -> None:
    for direction, side in self._sides.items():
      side.reset()
      self.measurements[direction] = RoadEdgeMeasurement(RoadEdgeDataState.UNAVAILABLE)

  @staticmethod
  def _lane_width(md) -> float:
    try:
      probs = md.laneLineProbs
      left_p, right_p = _finite(probs[1]), _finite(probs[2])
      if left_p is None or right_p is None or left_p <= EGO_LANE_LINE_PROB_MIN or right_p <= EGO_LANE_LINE_PROB_MIN:
        return LANE_CENTER_OFFSET_M
      width = _finite(abs(float(md.laneLines[2].y[0]) - float(md.laneLines[1].y[0])))
    except (AttributeError, TypeError, IndexError, ValueError):
      return LANE_CENTER_OFFSET_M
    if width is None:
      return LANE_CENTER_OFFSET_M
    return min(max(width, MIN_MEASURED_LANE_WIDTH_M), MAX_MEASURED_LANE_WIDTH_M)

  @staticmethod
  def _measure(md, direction, lane_width_m: float) -> RoadEdgeMeasurement:
    edge_idx, outer_idx = _SIDE_INDEX[direction]
    try:
      edge, std = md.roadEdges[edge_idx], md.roadEdgeStds[edge_idx]
    except (AttributeError, TypeError, IndexError):
      edge, std = None, None
    measurement = evaluate_road_edge(edge, std, direction, lane_width_m)
    if measurement.should_block:
      try:
        outer_p = _finite(md.laneLineProbs[outer_idx])
      except (AttributeError, TypeError, IndexError):
        outer_p = None
      if outer_p is not None and outer_p > ADJACENT_LANE_LINE_PROB:
        measurement = RoadEdgeMeasurement(measurement.state, measurement.lateral_distance_m,
                                          measurement.conservative_distance_m, False)
    return measurement

  def update(self, modeldata, v_ego_mps: float, dt_s: float, enabled: bool | None = None) -> None:
    if enabled is not None:
      self.enabled = bool(enabled)
    if not self.enabled or self.enabled != self._was_enabled:
      self._reset()
    self._was_enabled = self.enabled
    if not self.enabled:
      return

    dt = max(float(dt_s), 0.0)
    lane_width = self._lane_width(modeldata) if modeldata is not None else LANE_CENTER_OFFSET_M
    speed_active = v_ego_mps is not None and math.isfinite(v_ego_mps) and v_ego_mps >= MIN_ACTIVE_SPEED_MPS
    for direction, side in self._sides.items():
      measurement = self._measure(modeldata, direction, lane_width) if modeldata is not None else RoadEdgeMeasurement(RoadEdgeDataState.UNAVAILABLE)
      self.measurements[direction] = measurement
      if speed_active:
        side.step(measurement, dt)
      else:
        side.reset()

  def block_for_direction(self, direction) -> bool:
    side = self._sides.get(direction)
    return bool(self.enabled and side is not None and side.blocked)
