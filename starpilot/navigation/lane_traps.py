"""D-115: find an exit-only lane ahead that the route does not take.

Mapbox reports lanes at every junction on a step, including exits the route drives past. At such a junction an edge
lane that is not valid for the route and only points toward that edge is an exit-only lane: staying in it takes the
car off the route.
"""
from __future__ import annotations

EXIT_INDICATIONS = {
  "right": {"right", "slight right", "sharp right"},
  "left": {"left", "slight left", "sharp left"},
}
LOOKAHEAD_M = 2000.0


def _edge_exit_lanes(lanes: list[dict], side: str) -> int:
  """How many lanes at that edge exit the route (0 when none)."""
  ordered = lanes if side == "left" else list(reversed(lanes))
  count = 0
  for lane in ordered:
    indications = set(lane.get("indications") or [])
    if lane.get("valid", False) or not indications or not indications <= EXIT_INDICATIONS[side]:
      break
    count += 1
  return count if count < len(lanes) else 0  # every lane leaving means the route takes it


def exit_only_ahead(route, along_m: float, lookahead_m: float = LOOKAHEAD_M) -> dict | None:
  """The nearest junction within lookahead_m whose edge lane(s) leave the route: {distance, side, lanes}."""
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
        count = _edge_exit_lanes(lanes, side)
        if count:
          return {"distance": distance, "side": side, "lanes": count}
  return None
