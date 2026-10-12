"""D-114: suggest passing a slow lead on a navigated highway, then suggest moving back right.
D-115: warn when the car sits in an exit-only lane the route does not take, and remind to keep right.
D-117: the same for a city turn-only lane; merge, jammed-exit and destination-side notices.

Prompt only. Nothing here steers: the driver's blinker starts the existing lane change, which keeps its own
blind-spot block. Starting values, not tuned; no replay or road evidence yet.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MPH = 0.44704
SPEED_DEFICIT = 5 * MPH       # at least this far under the allowed speed (owner, 2026-10-12)
SLOW_SECONDS = 5.0            # for at least this long (owner, 2026-10-12: 10 s, lowered to 5 s same day)
SHOULDER_EDGE_GAP = 1.5       # m: road edge closer than this beyond the outer line = a shoulder, not a lane (D-114 Open)
MIN_LIMIT = 45 * MPH          # highway proxy: no suggestions below a 45 mph limit
LEAD_MAX_HEADWAY_S = 3.0      # the lead is the cause only when it is this close in time...
LEAD_MAX_DIST = 80.0          # ...or distance
LEFT_CLEAR_DIST = 100.0       # no left-lane car within this distance counts as a clear lane
LEFT_FASTER_BY = 5 * MPH      # or the left-lane car is at least this much faster than our lead
ROUTE_CLEAR_DIST = 2000.0     # no pass suggestion with a route maneuver closer than this
RETURN_DELAY_S = 3.0          # after the passed car leaves radar view
PASS_TIMEOUT_S = 120.0        # give up waiting for the pass
RETURN_TIMEOUT_S = 30.0       # stop suggesting the return
EXIT_WARN_DIST = 1600.0       # D-115: warn about an exit-only lane this far ahead (~1 mile)
KEEP_RIGHT_SECONDS = 60.0     # D-115: cruising with the right lane open this long before the reminder
KEEP_RIGHT_SHOW_S = 15.0      # show the reminder this long
KEEP_RIGHT_COOLDOWN_S = 300.0 # then not again for this long
RIGHT_CLEAR_DIST = 150.0      # no right-lane car within this distance, or one at least our speed
TURN_WARN_DIST = 300.0        # D-117: warn about a turn-only lane this far ahead (city blocks are short)
MERGE_WARN_DIST = 300.0       # D-117: announce a route "merge" step this far ahead (the end of an on-ramp)
EXIT_JAM_WARN_DIST = 3000.0   # D-117: suggest moving over early for a jammed exit from this far out

LEFT_MODIFIERS = ("left", "sharpleft", "slightleft")
RIGHT_MODIFIERS = ("right", "sharpright", "slightright")

IDLE, PASSING, RETURN = "idle", "passing", "return"


@dataclass
class Lead:
  status: bool = False
  d_rel: float = 0.0
  v_lead: float = 0.0


@dataclass
class PassingInputs:
  enabled: bool             # NavPassingSuggest toggle
  nav_state: dict           # NavInstructionState
  v_ego: float
  speed_limit: float        # m/s, 0 when unknown
  min_lane_change_speed: float
  lead: Lead                # own lane
  lead_left: Lead
  lead_right: Lead
  lane_width_left: float
  lane_width_right: float
  lane_detection_width: float
  vasm_live: bool
  blocked_left: bool        # V-ASM or car blind spot
  blocked_right: bool
  left_blinker: bool
  right_blinker: bool
  exit_warn: bool = False   # NavExitOnlyWarn toggle
  keep_right: bool = False  # NavKeepRightReminder toggle
  edge_gap_left: float = 99.0   # m, road edge beyond the outer lane line at 20 m (edge_gap()); 99 = unknown
  edge_gap_right: float = 99.0
  speed_offset: float = 0.0  # m/s, the owner's SLC offset: allowed speed is limit + offset (owner, 2026-10-12)
  merge_warn: bool = False   # D-117 NavMergeWarn toggle
  exit_jam_warn: bool = False  # D-117 NavJamExitWarn toggle
  arrival_help: bool = False   # D-117 NavArrivalHelp toggle


def lane_beside(width: float, detection_width: float, edge_gap: float = 99.0) -> bool:
  """A drivable lane on that side. Every D-114/D-115 prompt asks this one question.

  Width alone counts a paved shoulder as a lane: on I-35 (00000324, 00000321, 2026-10-12) the model draws the outer
  line on the road edge in the edge lane, so the "lane" beyond the yellow or right white line still measures 3+ m. The
  edge then sits within ~1 m of that line (shoulder p95 0.86 m), while a real lane leaves the edge 2.2+ m beyond the
  next lane's outer line (p1 2.17 m). /routes/an2/shsep.py.
  """
  return width >= detection_width and edge_gap >= SHOULDER_EDGE_GAP


def _left_lane(i: PassingInputs) -> bool:
  return lane_beside(i.lane_width_left, i.lane_detection_width, i.edge_gap_left)


def _right_lane(i: PassingInputs) -> bool:
  return lane_beside(i.lane_width_right, i.lane_detection_width, i.edge_gap_right)


def edge_gap(line_x, line_y, edge_x, edge_y, x: float = 20.0) -> float:
  """How far the road edge lies beyond an outer lane line, lateral metres at x metres ahead."""
  return abs(float(np.interp(x, edge_x, edge_y))) - abs(float(np.interp(x, line_x, line_y)))


def _route_side_within(nav_state: dict, dist: float) -> str | None:
  """'left'/'right'/'ahead' for a route maneuver closer than dist, else None."""
  try:
    distance = float(nav_state.get("maneuverDistance", -1.0))
  except (TypeError, ValueError):
    return "ahead"
  if distance < 0 or distance >= dist:
    return None
  modifier = str(nav_state.get("maneuverModifier", "")).replace(" ", "").lower()
  if modifier in LEFT_MODIFIERS:
    return "left"
  if modifier in RIGHT_MODIFIERS:
    return "right"
  return "ahead"


def _float(nav_state: dict, key: str) -> float:
  try:
    return float(nav_state.get(key, -1.0))
  except (TypeError, ValueError):
    return -1.0


def _side(modifier) -> str:
  modifier = str(modifier).replace(" ", "").lower()
  return "left" if modifier in LEFT_MODIFIERS else "right" if modifier in RIGHT_MODIFIERS else ""


class NavPassingAdvisor:
  def __init__(self):
    self.state = IDLE
    self.slow_since: float | None = None
    self.state_since = 0.0
    self.passed_seen = False
    self.passed_gone_since: float | None = None
    self.keep_right_since: float | None = None
    self.keep_right_shown_at = -KEEP_RIGHT_COOLDOWN_S

  def _set(self, state: str, now: float):
    self.state, self.state_since = state, now
    self.passed_seen, self.passed_gone_since = False, None
    if state != IDLE:
      self.slow_since = None

  def _pass_ready(self, i: PassingInputs, now: float) -> bool:
    lead = i.lead
    limit = i.speed_limit
    allowed = limit + max(i.speed_offset, 0.0)
    lead_close = lead.status and (lead.d_rel < max(i.v_ego * LEAD_MAX_HEADWAY_S, 1.0) or lead.d_rel < LEAD_MAX_DIST)
    slow = (limit >= MIN_LIMIT and i.v_ego >= i.min_lane_change_speed and i.v_ego <= allowed - SPEED_DEFICIT
            and lead_close and lead.v_lead <= allowed - SPEED_DEFICIT)
    if not slow:
      self.slow_since = None
      return False
    if self.slow_since is None:
      self.slow_since = now
    if now - self.slow_since < SLOW_SECONDS:
      return False
    left_lane = _left_lane(i)
    left_faster = (not i.lead_left.status or i.lead_left.d_rel > LEFT_CLEAR_DIST or
                   i.lead_left.v_lead >= lead.v_lead + LEFT_FASTER_BY)
    route_clear = _route_side_within(i.nav_state, ROUTE_CLEAR_DIST) is None
    return left_lane and left_faster and route_clear and not i.blocked_left

  @staticmethod
  def _exit_trap(i: PassingInputs) -> tuple[str, str]:
    """D-115/D-117: (side to move to, "exit"|"turn") when the car is in the edge lane of an exit- or turn-only
    lane ahead, else ("", "")."""
    side = i.nav_state.get("exitOnlySide", "")
    kind = "turn" if i.nav_state.get("exitOnlyKind", "") == "turn" else "exit"
    distance = _float(i.nav_state, "exitOnlyDistance")
    if side not in ("left", "right") or not 0.0 < distance <= (TURN_WARN_DIST if kind == "turn" else EXIT_WARN_DIST):
      return "", ""
    away = "left" if side == "right" else "right"
    edge_lane, away_lane = (_right_lane(i), _left_lane(i)) if side == "right" else (_left_lane(i), _right_lane(i))
    away_blinker = i.left_blinker if away == "left" else i.right_blinker
    in_edge_lane = not edge_lane and away_lane
    return (away, kind) if in_edge_lane and not away_blinker else ("", "")

  @staticmethod
  def _merge(i: PassingInputs) -> str:
    """D-117: the side to merge to when the route's next step is a merge within MERGE_WARN_DIST, else ''."""
    if str(i.nav_state.get("maneuverType", "")) != "merge":
      return ""
    distance = _float(i.nav_state, "maneuverDistance")
    side = _side(i.nav_state.get("maneuverModifier", ""))
    if not side or not 0.0 < distance <= MERGE_WARN_DIST:
      return ""
    return "" if (i.left_blinker if side == "left" else i.right_blinker) else side

  @staticmethod
  def _exit_jam(i: PassingInputs) -> str:
    """D-117: the side to move to early when the route's exit is jammed and a lane is still between us and it."""
    side = i.nav_state.get("exitJamSide", "")
    distance = _float(i.nav_state, "exitJamDistance")
    if side not in ("left", "right") or not 0.0 < distance <= EXIT_JAM_WARN_DIST:
      return ""
    lane_toward = _left_lane(i) if side == "left" else _right_lane(i)
    blinker = i.left_blinker if side == "left" else i.right_blinker
    return side if lane_toward and not blinker else ""

  def _keep_right(self, i: PassingInputs, now: float) -> bool:
    """D-115: cruising in a lane with an open, not-slower right lane for a while. Idle state only."""
    if now - self.keep_right_shown_at < KEEP_RIGHT_SHOW_S:
      if i.right_blinker or i.left_blinker or not _right_lane(i):
        self.keep_right_shown_at = now - KEEP_RIGHT_SHOW_S  # acted on or gone: end it now
        return False
      return True
    right = i.lead_right
    right_open = (_right_lane(i) and not i.blocked_right and
                  (not right.status or right.d_rel > RIGHT_CLEAR_DIST or right.v_lead >= i.v_ego))
    cruising = (i.speed_limit >= MIN_LIMIT and i.v_ego >= i.min_lane_change_speed and self.slow_since is None
                and not i.left_blinker and not i.right_blinker)
    route_ok = _route_side_within(i.nav_state, ROUTE_CLEAR_DIST) not in ("left", "ahead")
    if not (right_open and cruising and route_ok):
      self.keep_right_since = None
      return False
    if self.keep_right_since is None:
      self.keep_right_since = now
    if now - self.keep_right_since < KEEP_RIGHT_SECONDS or now - self.keep_right_shown_at < KEEP_RIGHT_COOLDOWN_S:
      return False
    self.keep_right_shown_at, self.keep_right_since = now, None
    return True

  def update(self, i: PassingInputs, now: float) -> dict:
    nav_ok = bool(i.nav_state) and bool(i.nav_state.get("valid", False))
    # Route information, not lane change suggestions: no V-ASM needed. "blocked" tells the driver V-ASM sees a car.
    trap, kind = self._exit_trap(i) if i.exit_warn and nav_ok else ("", "")
    merge = self._merge(i) if i.merge_warn and nav_ok else ""
    exit_jam = self._exit_jam(i) if i.exit_jam_warn and nav_ok else ""
    prompt = self._update_passing(i, now)
    if trap:
      return {"armed": True, "side": trap, "phase": kind, "ts": now}
    if merge:
      return {"armed": True, "side": merge, "phase": "merge", "ts": now,
              "blocked": bool(i.blocked_left if merge == "left" else i.blocked_right)}
    if exit_jam:
      return {"armed": True, "side": exit_jam, "phase": "exitjam", "ts": now,
              "distance": _float(i.nav_state, "exitJamDistance")}
    if not prompt["armed"] and i.arrival_help and nav_ok:
      side = i.nav_state.get("arriveSide", "")
      distance = _float(i.nav_state, "arriveDistance")
      if side in ("left", "right") and distance > 0.0:
        return {"armed": True, "side": side, "phase": "arrive", "ts": now, "distance": distance}
    return prompt

  def _update_passing(self, i: PassingInputs, now: float) -> dict:
    out = {"armed": False, "side": "", "phase": "", "ts": now}
    # Nav-only, and no suggestions at all without a live V-ASM: the radar cannot see a car coming up from behind.
    if not ((i.enabled or i.keep_right) and i.vasm_live and i.nav_state and i.nav_state.get("valid", False)):
      self._set(IDLE, now)
      self.slow_since = self.keep_right_since = None
      return out

    route_side = _route_side_within(i.nav_state, ROUTE_CLEAR_DIST)
    right_lane = _right_lane(i)

    if self.state == IDLE:
      if self._pass_ready(i, now) and i.enabled:  # always evaluated: keep-right reads slow_since
        if i.left_blinker:
          self._set(PASSING, now)
        else:
          out.update(armed=True, side="left", phase="pass")
      elif i.keep_right and self._keep_right(i, now):
        out.update(armed=True, side="right", phase="keepright")
      return out

    if self.state == PASSING:
      if now - self.state_since > PASS_TIMEOUT_S or i.right_blinker:
        self._set(IDLE, now)
        return out
      if route_side == "left":
        return out  # the route wants the left side: never suggest moving back
      if route_side == "right":
        self._set(RETURN, now)  # the route needs the right side soon: suggest the return now
      else:
        # the passed car shows up as the right-lane lead, then drops out of the forward radar view
        if i.lead_right.status:
          self.passed_seen, self.passed_gone_since = True, None
        elif self.passed_seen:
          if self.passed_gone_since is None:
            self.passed_gone_since = now
          if now - self.passed_gone_since >= RETURN_DELAY_S:
            self._set(RETURN, now)
      if self.state != RETURN:
        return out

    # RETURN
    if i.right_blinker or now - self.state_since > RETURN_TIMEOUT_S or route_side == "left":
      self._set(IDLE, now)
      return out
    if right_lane and not i.blocked_right:
      out.update(armed=True, side="right", phase="return")
    return out
