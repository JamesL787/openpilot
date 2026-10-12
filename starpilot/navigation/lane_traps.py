"""D-115: find an exit-only lane ahead that the route does not take.
D-117: the same check finds a city turn-only lane at a junction the route goes straight through.

Mapbox reports lanes at every junction on a step, including exits the route drives past. At such a junction an edge
lane that is not valid for the route and only points toward that edge is an exit-only lane: staying in it takes the
car off the route. When it only points a full turn (left/right/sharp/u-turn, no "slight"), it is a turn lane.
"""
from __future__ import annotations

EXIT_INDICATIONS = {
  "right": {"right", "slight right", "sharp right"},
  "left": {"left", "slight left", "sharp left", "uturn"},
}
TURN_INDICATIONS = {
  "right": {"right", "sharp right"},
  "left": {"left", "sharp left", "uturn"},
}
LOOKAHEAD_M = 2000.0


def _edge_exit_lanes(lanes: list[dict], side: str) -> tuple[int, bool]:
  """How many lanes at that edge leave the route (0 when none), and whether they all only turn."""
  ordered = lanes if side == "left" else list(reversed(lanes))
  count, turn = 0, True
  for lane in ordered:
    indications = set(lane.get("indications") or [])
    if lane.get("valid", False) or not indications or not indications <= EXIT_INDICATIONS[side]:
      break
    count += 1
    turn &= indications <= TURN_INDICATIONS[side]
  if count >= len(lanes):
    return 0, False  # every lane leaving means the route takes it
  return count, turn and count > 0


def exit_only_ahead(route, along_m: float, lookahead_m: float = LOOKAHEAD_M) -> dict | None:
  """The nearest junction within lookahead_m whose edge lane(s) leave the route: {distance, side, lanes, kind}.

  kind is "turn" for a turn-only lane, "exit" otherwise."""
  if route is None:
    return None
  for step in route.steps:
    for junction_m, lanes in getattr(step, "junction_lanes", ()):
      distance = junction_m - along_m
      if distance <= 0.0:
        continue
      if distance > lookahead_m:
        return None  # junctions run in route order
      for side in ("right", "left"):
        count, turn = _edge_exit_lanes(lanes, side)
        if count:
          return {"distance": distance, "side": side, "lanes": count, "kind": "turn" if turn else "exit"}
  return None


def control_ahead(route, along_m: float, lookahead_m: float) -> dict | None:
  """D-117: the nearest Mapbox-flagged traffic control within lookahead_m: {distance, kind}."""
  if route is None:
    return None
  for step in route.steps:
    for junction_m, kind in getattr(step, "junction_controls", ()):
      distance = junction_m - along_m
      if distance <= 0.0:
        continue
      if distance > lookahead_m:
        return None
      return {"distance": distance, "kind": kind}
  return None
