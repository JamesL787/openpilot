"""D-114: suggest passing a slow lead on a navigated highway, then suggest moving back right.

Prompt only. Nothing here steers: the driver's blinker starts the existing lane change, which keeps its own
blind-spot block. Starting values, not tuned; no replay or road evidence yet.
"""
from __future__ import annotations

from dataclasses import dataclass

MPH = 0.44704
SPEED_DEFICIT = 5 * MPH       # at least this far under the limit (owner, 2026-10-12)
SLOW_SECONDS = 10.0           # for at least this long (owner, 2026-10-12)
MIN_LIMIT = 45 * MPH          # highway proxy: no suggestions below a 45 mph limit
LEAD_MAX_HEADWAY_S = 3.0      # the lead is the cause only when it is this close in time...
LEAD_MAX_DIST = 80.0          # ...or distance
LEFT_CLEAR_DIST = 100.0       # no left-lane car within this distance counts as a clear lane
LEFT_FASTER_BY = 5 * MPH      # or the left-lane car is at least this much faster than our lead
ROUTE_CLEAR_DIST = 2000.0     # no pass suggestion with a route maneuver closer than this
RETURN_DELAY_S = 3.0          # after the passed car leaves radar view
PASS_TIMEOUT_S = 120.0        # give up waiting for the pass
RETURN_TIMEOUT_S = 30.0       # stop suggesting the return

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


class NavPassingAdvisor:
  def __init__(self):
    self.state = IDLE
    self.slow_since: float | None = None
    self.state_since = 0.0
    self.passed_seen = False
    self.passed_gone_since: float | None = None

  def _set(self, state: str, now: float):
    self.state, self.state_since = state, now
    self.passed_seen, self.passed_gone_since = False, None
    if state != IDLE:
      self.slow_since = None

  def _pass_ready(self, i: PassingInputs, now: float) -> bool:
    lead = i.lead
    limit = i.speed_limit
    lead_close = lead.status and (lead.d_rel < max(i.v_ego * LEAD_MAX_HEADWAY_S, 1.0) or lead.d_rel < LEAD_MAX_DIST)
    slow = (limit >= MIN_LIMIT and i.v_ego >= i.min_lane_change_speed and i.v_ego <= limit - SPEED_DEFICIT
            and lead_close and lead.v_lead <= limit - SPEED_DEFICIT)
    if not slow:
      self.slow_since = None
      return False
    if self.slow_since is None:
      self.slow_since = now
    if now - self.slow_since < SLOW_SECONDS:
      return False
    left_lane = i.lane_width_left >= i.lane_detection_width
    left_faster = (not i.lead_left.status or i.lead_left.d_rel > LEFT_CLEAR_DIST or
                   i.lead_left.v_lead >= lead.v_lead + LEFT_FASTER_BY)
    route_clear = _route_side_within(i.nav_state, ROUTE_CLEAR_DIST) is None
    return left_lane and left_faster and route_clear and not i.blocked_left

  def update(self, i: PassingInputs, now: float) -> dict:
    out = {"armed": False, "side": "", "phase": "", "ts": now}
    # Nav-only, and no suggestions at all without a live V-ASM: the radar cannot see a car coming up from behind.
    if not (i.enabled and i.vasm_live and i.nav_state and i.nav_state.get("valid", False)):
      self._set(IDLE, now)
      self.slow_since = None
      return out

    route_side = _route_side_within(i.nav_state, ROUTE_CLEAR_DIST)
    right_lane = i.lane_width_right >= i.lane_detection_width

    if self.state == IDLE:
      if self._pass_ready(i, now):
        if i.left_blinker:
          self._set(PASSING, now)
        else:
          out.update(armed=True, side="left", phase="pass")
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
