import numpy as np

# Starting values, not tuned: replay of routes 2f2/2f5 then Peter's drive decide them.
EXIT_PROMPT_SECONDS = 60.0
EXIT_PROMPT_MIN_M, EXIT_PROMPT_MAX_M = 400.0, 1600.0
TURN_PROMPT_SECONDS = 10.0
TURN_PROMPT_MIN_M, TURN_PROMPT_MAX_M = 60.0, 200.0

# Mapbox lane guidance says the valid lane is turn-only: turn lanes start earlier than a plain turn
TURN_LANE_SECONDS = 18.0
TURN_LANE_MIN_M, TURN_LANE_MAX_M = 100.0, 300.0
LEFT_MODIFIERS = ("left", "sharpleft", "slightleft")
MIN_LEAD_SECONDS = 4.0  # too close to finish a lane change: stop prompting
RIGHT_MODIFIERS = ("right", "sharpright", "slightright")


def prompt_window_m(kind: str, v_ego: float) -> float:
  if kind == "exit":
    return float(np.clip(v_ego * EXIT_PROMPT_SECONDS, EXIT_PROMPT_MIN_M, EXIT_PROMPT_MAX_M))
  return float(np.clip(v_ego * TURN_PROMPT_SECONDS, TURN_PROMPT_MIN_M, TURN_PROMPT_MAX_M))


def is_turn_only_lane(nav_state: dict, side: str) -> bool:
  """Guidance marks a lane at the road edge on the turn side that no other direction shares."""
  direction = str(nav_state.get("activeLaneDirection", ""))
  on_side = direction in (("slightLeft", "left", "sharpLeft") if side == "left" else ("slightRight", "right", "sharpRight"))
  return on_side and bool(nav_state.get("activeLaneAtRoadEdge", False)) and not bool(nav_state.get("hasSharedSameSideLane", False))


def nav_lane_move_prompt(nav_state: dict, v_ego: float, min_speed: float, adjacent_lane_width: dict,
                         lane_detection_width: float, now: float) -> dict:
  """Dict for NavLaneMovePrompt. armed=False means the UI shows nothing."""
  out = {"armed": False, "side": "", "kind": "", "distance_m": 0.0, "window_m": 0.0, "turn_lane": False, "ts": now}
  if not nav_state or not nav_state.get("valid", False):
    return out

  maneuver_type = str(nav_state.get("maneuverType", "")).lower()
  modifier = str(nav_state.get("maneuverModifier", "")).replace(" ", "").lower()
  if modifier in LEFT_MODIFIERS:
    side = "left"
  elif modifier in RIGHT_MODIFIERS:
    side = "right"
  else:
    return out

  # fork keeps its own keepLeft/keepRight path; only exits and plain turns get a move-over prompt
  if maneuver_type in ("off ramp", "on ramp"):  # D-113: an on-ramp is prompted like an exit
    kind = "exit"
  elif maneuver_type in ("turn", "end of road") and modifier in ("left", "right", "sharpleft", "sharpright"):
    kind = "turn"
  else:
    return out

  try:
    distance = float(nav_state.get("maneuverDistance", 0.0))
  except (TypeError, ValueError):
    return out

  turn_lane = kind == "turn" and is_turn_only_lane(nav_state, side)
  window = prompt_window_m(kind, v_ego)
  if turn_lane:
    window = max(window, float(np.clip(v_ego * TURN_LANE_SECONDS, TURN_LANE_MIN_M, TURN_LANE_MAX_M)))
  out.update(side=side, kind=kind, distance_m=distance, window_m=window, turn_lane=turn_lane)
  if not v_ego * MIN_LEAD_SECONDS < distance <= window or v_ego < min_speed:
    return out

  # No adjacent lane on that side (width below the detection threshold): already in the edge lane
  width = adjacent_lane_width.get(side)
  if width is not None and width < lane_detection_width:
    return out

  out["armed"] = True
  return out
