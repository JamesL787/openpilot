#!/usr/bin/env python3
from __future__ import annotations
import json
import threading
from math import inf, isfinite
from time import monotonic

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog

from openpilot.starpilot.navigation.destination_store import parse_destination_json
from openpilot.starpilot.navigation.route_engine import Coordinate, MapboxRouteEngine, NavigationRoute, RouteProgress
from openpilot.starpilot.navigation.traffic_reroute import (
  JAM_DATA_MAX_AGE_S, JAM_MAX_ROUTE_OFFSET_M, TRAFFIC_CONFIRM_RECHECK_S, TRAFFIC_MANEUVER_GUARD_M, TRAFFIC_PROMPT_TIMEOUT_S,
  TRAFFIC_REFRESH_INTERVAL_S, TrafficReroutePolicy, congestion_ahead, retry_delay_s, same_route,
)

NAVIGATIOND_HZ = 1
REROUTE_TRIGGER_SECONDS = 2.0
ARRIVAL_CLEAR_SECONDS = 5.0
LOCATION_STATE_STALE_SECONDS = 2.5
NAV_ROUTE_REPUBLISH_SECONDS = 5.0  # map views that start after the route was sent still get it
REROUTE_ACCEPT_MAX_OFFSET_M = 40.0  # an accepted candidate must still start under the car


class Navigationd:
  def __init__(self, route_engine: MapboxRouteEngine | None = None):
    self.params = Params()
    self.params_memory = Params(memory=True)
    if route_engine is None:
      from openpilot.starpilot.navigation.mapbox_usage import shared_usage
      route_engine = MapboxRouteEngine(usage=shared_usage())
    self.route_engine = route_engine

    self.pm = messaging.PubMaster(["navInstruction", "navRoute"])
    self.rk = Ratekeeper(NAVIGATIOND_HZ)

    self._route_lock = threading.Lock()
    self._route: NavigationRoute | None = None
    self._active_destination: dict[str, object] | None = None
    self._requested_destination_key: tuple[str, str, float, float] | None = None
    self._route_fetch_inflight = False
    self._route_generation = 0
    self._published_route_generation = -1
    self._published_route_at = 0.0

    self._last_position: Coordinate | None = None
    self._last_bearing: float | None = None
    self._off_route_started_at: float | None = None
    self._bearing_misaligned_started_at: float | None = None
    self._arrival_started_at: float | None = None
    self._last_nav_state: dict[str, object] | None = None
    self._route_fetched_at = -inf

    # D-111 traffic re-check and D-112 congestion data
    self._traffic_policy = TrafficReroutePolicy()
    self._traffic_fetch_inflight = False
    self._traffic_next_check_at = 0.0
    self._traffic_failures = 0
    self._traffic_candidate: NavigationRoute | None = None   # last qualifying candidate, to confirm it on the next check
    self._traffic_route: NavigationRoute | None = None       # fresh copy of the current route's path (traffic only)
    self._traffic_route_at = -inf
    self._reroute_prompt: dict[str, object] | None = None
    self._reroute_prompt_id = 0

  @staticmethod
  def _destination_key(destination: dict[str, object] | None) -> tuple | None:
    if destination is None:
      return None
    return (
      str(destination["place_name"]).casefold(),
      str(destination.get("routeId") or "main"),
      round(float(destination["latitude"]), 6),
      round(float(destination["longitude"]), 6),
      bool(destination.get("avoid_tolls", False)),
      bool(destination.get("avoid_highways", False)),
      bool(destination.get("avoid_ferries", False)),
      bool(destination.get("prefer_eco", False)),
    )

  def _snapshot_route(self) -> tuple[NavigationRoute | None, dict[str, object] | None, int]:
    with self._route_lock:
      return self._route, self._active_destination, self._route_generation

  def _route_token(self) -> str:
    return self.params.get("MapboxSecretKey", encoding="utf-8") or ""

  def _clear_route(self, *, remove_destination: bool = False) -> None:
    with self._route_lock:
      self._route = None
      self._active_destination = None
      self._requested_destination_key = None
      self._route_generation += 1

    self._off_route_started_at = None
    self._bearing_misaligned_started_at = None
    self._arrival_started_at = None
    self._reset_traffic()
    self._publish_nav_state(None, None, False)
    self.params_memory.remove("NavInstructionCollapsed")

    if remove_destination:
      self.params.remove("NavDestination")

  def _start_route_fetch(self, destination: dict[str, object]) -> None:
    if self._last_position is None or self._route_fetch_inflight:
      return

    token = self._route_token()
    if not token:
      return

    position = self._last_position
    bearing = self._last_bearing
    destination_key = self._destination_key(destination)
    if destination_key is None:
      return

    with self._route_lock:
      self._route_fetch_inflight = True
      self._requested_destination_key = destination_key

    def worker():
      route = self.route_engine.fetch_route(token, position, destination, bearing)
      with self._route_lock:
        still_current = self._requested_destination_key == destination_key
        self._route_fetch_inflight = False
        if not still_current:
          return
        if route is None:
          return

        self._route = route
        self._active_destination = destination
        self._route_generation += 1
        self._route_fetched_at = monotonic()

      self._reset_traffic()
      self._off_route_started_at = None
      self._bearing_misaligned_started_at = None
      self._arrival_started_at = None

    threading.Thread(target=worker, daemon=True).start()

  # ===== D-111 / D-112: traffic re-check =====
  def _reset_traffic(self) -> None:
    self._traffic_policy.reset_candidate()
    self._traffic_candidate = None
    self._traffic_route = None
    self._traffic_route_at = -inf
    self._traffic_next_check_at = monotonic() + TRAFFIC_REFRESH_INTERVAL_S
    self._clear_reroute_prompt()

  def _clear_reroute_prompt(self) -> None:
    if self._reroute_prompt is not None:
      self._reroute_prompt = None
      self.params_memory.remove("NavTrafficReroutePrompt")

  def _maybe_check_traffic(self, route: NavigationRoute | None, destination: dict[str, object] | None,
                           progress: RouteProgress | None, now: float) -> None:
    reroute_on = self.params.get_bool("NavTrafficReroute")
    if not (reroute_on or self.params.get_bool("NavJamSlowdown")):
      return
    if route is None or destination is None or progress is None or self._last_position is None:
      return
    if self._traffic_fetch_inflight or self._route_fetch_inflight or self._reroute_prompt is not None:
      return
    if now < self._traffic_next_check_at or progress.current_step_index >= len(route.steps) - 1:
      return
    token = self._route_token()
    if not token:
      return

    position, bearing = self._last_position, self._last_bearing
    along_m, next_maneuver_m = progress.along_distance, progress.distance_to_end_of_step
    with self._route_lock:
      generation = self._route_generation
    self._traffic_fetch_inflight = True

    def worker():
      try:
        routes = self.route_engine.fetch_routes(token, position, destination, bearing, alternatives=reroute_on)
        self._handle_traffic_routes(routes, route, generation, along_m, next_maneuver_m, reroute_on, monotonic())
      finally:
        self._traffic_fetch_inflight = False

    threading.Thread(target=worker, daemon=True).start()

  def _handle_traffic_routes(self, routes: list[NavigationRoute], current: NavigationRoute, generation: int, along_m: float,
                             next_maneuver_m: float, reroute_on: bool, now: float) -> None:
    with self._route_lock:
      if generation != self._route_generation:
        return  # rerouted while the request was out
    if not routes:
      self._traffic_failures += 1
      self._traffic_next_check_at = now + retry_delay_s(self._traffic_failures)
      return
    self._traffic_failures = 0
    self._traffic_next_check_at = now + TRAFFIC_REFRESH_INTERVAL_S

    fresh_current = next((r for r in routes if same_route(r, current, along_m)), None)
    if fresh_current is not None:
      self._traffic_route, self._traffic_route_at = fresh_current, now
    if not reroute_on:
      return
    if fresh_current is None:
      # without a fresh time for the route we are on there is nothing fair to compare against
      self._traffic_policy.reset_candidate()
      self._traffic_candidate = None
      cloudlog.info("nav traffic: current route not among the refreshed routes")
      return

    others = [r for r in routes if r is not fresh_current and not same_route(r, current, along_m)]
    best = min(others, key=lambda r: r.total_duration) if others else None
    matches_previous = best is not None and self._traffic_candidate is not None and same_route(best, self._traffic_candidate)
    decision = self._traffic_policy.evaluate(now, fresh_current.total_duration, best.total_duration if best else None,
                                             next_maneuver_m, matches_previous)
    cloudlog.info(f"nav traffic: {decision.reason} savings={decision.savings_s:.0f}s confirmations={decision.confirmations}")
    self._traffic_candidate = best if decision.reason in ("awaiting_confirmation", "switch") else None
    if decision.reason == "awaiting_confirmation":
      self._traffic_next_check_at = now + TRAFFIC_CONFIRM_RECHECK_S
    elif decision.reason == "switch" and best is not None:
      with self._route_lock:
        if generation != self._route_generation:
          return
        self._reroute_prompt_id += 1
        self._reroute_prompt = {"id": self._reroute_prompt_id, "route": best, "savings_s": decision.savings_s,
                                "shown_at": now, "generation": generation}

  def _read_reroute_response(self) -> dict[str, object]:
    raw = self.params_memory.get("NavTrafficRerouteResponse") or {}
    if isinstance(raw, (str, bytes)):
      try:
        raw = json.loads(raw) if raw else {}
      except json.JSONDecodeError:
        raw = {}
    return raw if isinstance(raw, dict) else {}

  def _update_reroute_prompt(self, progress: RouteProgress | None, now: float) -> None:
    prompt = self._reroute_prompt
    if prompt is None:
      return
    with self._route_lock:
      generation = self._route_generation
    if prompt["generation"] != generation or progress is None:
      self._clear_reroute_prompt()
      return

    response = self._read_reroute_response()
    if response.get("id") == prompt["id"]:
      self.params_memory.remove("NavTrafficRerouteResponse")
      self._traffic_policy.mark_answered(now)
      self._clear_reroute_prompt()
      if bool(response.get("accept", False)):
        self._accept_reroute(prompt["route"])
      else:
        cloudlog.info("nav traffic: driver kept the current route")
      return

    if now - float(prompt["shown_at"]) >= TRAFFIC_PROMPT_TIMEOUT_S:
      self._traffic_policy.mark_answered(now)
      self._clear_reroute_prompt()
      cloudlog.info("nav traffic: prompt timed out, keeping the current route")
      return
    if progress.distance_to_end_of_step < TRAFFIC_MANEUVER_GUARD_M:
      self._traffic_policy.reset_candidate()
      self._clear_reroute_prompt()
      return

    self.params_memory.put_nonblocking("NavTrafficReroutePrompt", {
      "armed": True,
      "id": prompt["id"],
      "savings_s": round(float(prompt["savings_s"])),
      "remaining_s": round(max(TRAFFIC_PROMPT_TIMEOUT_S - (now - float(prompt["shown_at"])), 0.0), 1),
      "ts": now,
    })

  def _accept_reroute(self, candidate: NavigationRoute) -> None:
    position = self._last_position
    progress = candidate.get_progress(position) if position is not None else None
    if progress is None or progress.distance_from_route > REROUTE_ACCEPT_MAX_OFFSET_M:
      cloudlog.warning("nav traffic: accepted route no longer starts at the car; not switching")
      return
    with self._route_lock:
      self._route = candidate
      self._route_generation += 1
      self._route_fetched_at = monotonic()
    self._off_route_started_at = None
    self._bearing_misaligned_started_at = None
    self._arrival_started_at = None
    self._reset_traffic()
    cloudlog.warning("nav traffic: driver switched to the faster route")

  def _jam_ahead(self, route: NavigationRoute | None, progress: RouteProgress | None, now: float) -> tuple[float, float] | None:
    if route is None or progress is None or self._last_position is None or not self.params.get_bool("NavJamSlowdown"):
      return None
    source, fetched_at, source_progress = route, self._route_fetched_at, progress
    traffic_route = self._traffic_route
    if traffic_route is not None and self._traffic_route_at > fetched_at:
      source, fetched_at, source_progress = traffic_route, self._traffic_route_at, None
    if now - fetched_at > JAM_DATA_MAX_AGE_S:
      return None
    if source_progress is None:
      source_progress = source.get_progress(self._last_position)
    if source_progress is None or source_progress.distance_from_route > JAM_MAX_ROUTE_OFFSET_M:
      return None
    return congestion_ahead(source, source_progress.along_distance)

  @staticmethod
  def _timer_expired(started_at: float | None, threshold: float, now: float) -> bool:
    return started_at is not None and (now - started_at) >= threshold

  @staticmethod
  def _bump_timer(started_at: float | None, condition: bool, now: float) -> float | None:
    if not condition:
      return None
    return started_at if started_at is not None else now

  def _update_location(self) -> tuple[bool, float]:
    raw_state = self.params_memory.get("LastGPSPosition", encoding="utf-8") or ""
    if not raw_state:
      return False, 0.0

    try:
      gps_state = json.loads(raw_state)
    except json.JSONDecodeError:
      return False, 0.0

    if not isinstance(gps_state, dict) or not gps_state.get("hasFix", False):
      return False, 0.0

    latitude = float(gps_state.get("latitude", 0.0) or 0.0)
    longitude = float(gps_state.get("longitude", 0.0) or 0.0)
    if not isfinite(latitude) or not isfinite(longitude) or (abs(latitude) < 1e-6 and abs(longitude) < 1e-6):
      return False, 0.0

    updated_at = float(gps_state.get("updatedAtMonotonic", 0.0) or 0.0)
    if updated_at > 0.0 and (monotonic() - updated_at) > LOCATION_STATE_STALE_SECONDS:
      return False, 0.0

    self._last_position = Coordinate(latitude, longitude)

    bearing = float(gps_state.get("bearing", 0.0) or 0.0)
    self._last_bearing = bearing if isfinite(bearing) else None

    speed = float(gps_state.get("speed", 0.0) or 0.0)
    return True, max(speed, 0.0)

  def _maybe_update_route(self, current_destination: dict[str, object] | None) -> tuple[NavigationRoute | None, dict[str, object] | None, int]:
    route, active_destination, route_generation = self._snapshot_route()

    if current_destination is None:
      if route is not None or active_destination is not None:
        self._clear_route()
        route, active_destination, route_generation = self._snapshot_route()
      return route, active_destination, route_generation

    if route is None or self._destination_key(current_destination) != self._destination_key(active_destination):
      self._start_route_fetch(current_destination)

    return self._snapshot_route()

  def _build_progress(self, route: NavigationRoute | None, location_valid: bool, v_ego: float) -> tuple[RouteProgress | None, dict[str, object] | None]:
    if route is None or not location_valid or self._last_position is None:
      self._off_route_started_at = None
      self._bearing_misaligned_started_at = None
      self._arrival_started_at = None
      return None, None

    progress = route.get_progress(self._last_position)
    if progress is None:
      return None, None

    now = monotonic()
    off_route = route.off_route_distance_exceeded(progress, v_ego)
    misaligned = route.route_bearing_misaligned(progress.closest_segment_index, self._last_bearing, v_ego)
    arrived = route.arrived(progress, v_ego)

    self._off_route_started_at = self._bump_timer(self._off_route_started_at, off_route and not arrived, now)
    self._bearing_misaligned_started_at = self._bump_timer(self._bearing_misaligned_started_at, misaligned and not arrived, now)
    self._arrival_started_at = self._bump_timer(self._arrival_started_at, arrived, now)

    if not off_route:
      self._off_route_started_at = None
    if not misaligned:
      self._bearing_misaligned_started_at = None
    if not arrived:
      self._arrival_started_at = None

    return progress, {
      "offRoute": off_route,
      "misaligned": misaligned,
      "arrived": arrived,
      "now": now,
    }

  def _maybe_recompute(self, route: NavigationRoute | None, destination: dict[str, object] | None, progress: RouteProgress | None, route_state: dict[str, object] | None) -> None:
    if route is None or destination is None or progress is None or route_state is None:
      return

    if progress.current_step_index >= len(route.steps) - 1:
      return

    now = float(route_state["now"])
    should_reroute = self._timer_expired(self._off_route_started_at, REROUTE_TRIGGER_SECONDS, now)
    should_reroute |= self._timer_expired(self._bearing_misaligned_started_at, REROUTE_TRIGGER_SECONDS, now)
    if should_reroute:
      self._start_route_fetch(destination)

    if self._timer_expired(self._arrival_started_at, ARRIVAL_CLEAR_SECONDS, now):
      self._clear_route(remove_destination=True)

  def _publish_nav_instruction(
    self,
    route: NavigationRoute | None,
    progress: RouteProgress | None,
    location_valid: bool,
    payload: dict[str, object] | None = None,
  ) -> None:
    msg = messaging.new_message("navInstruction")
    msg.valid = bool(route is not None and progress is not None and location_valid)

    if msg.valid and route is not None and progress is not None and self._last_position is not None and payload is not None:
      nav_instruction = msg.navInstruction
      nav_instruction.maneuverPrimaryText = payload["maneuverPrimaryText"]
      nav_instruction.maneuverSecondaryText = payload["maneuverSecondaryText"]
      nav_instruction.maneuverDistance = float(payload["maneuverDistance"])
      nav_instruction.maneuverType = str(payload["maneuverType"])
      nav_instruction.maneuverModifier = str(payload["maneuverModifier"])
      nav_instruction.distanceRemaining = float(payload["distanceRemaining"])
      nav_instruction.timeRemaining = float(payload["timeRemaining"])
      nav_instruction.timeRemainingTypical = float(payload["timeRemainingTypical"])
      nav_instruction.lanes = payload["lanes"]
      nav_instruction.showFull = bool(payload["showFull"])
      nav_instruction.speedLimit = float(payload["speedLimit"])
      nav_instruction.speedLimitSign = payload["speedLimitSign"]
      nav_instruction.allManeuvers = payload["allManeuvers"]

    self.pm.send("navInstruction", msg)

  def _publish_nav_state(
    self,
    route: NavigationRoute | None,
    progress: RouteProgress | None,
    location_valid: bool,
    payload: dict[str, object] | None = None,
    jam: tuple[float, float] | None = None,
  ) -> None:
    if route is None or progress is None or not location_valid:
      if self._last_nav_state is not None:
        self.params_memory.remove("NavInstructionState")
        self._last_nav_state = None
      return

    if payload is None:
      return

    all_maneuvers = payload.get("allManeuvers") or []
    next_maneuver = all_maneuvers[1] if len(all_maneuvers) > 1 and isinstance(all_maneuvers[1], dict) else {}
    active_lane_direction = ""
    active_lane_index = -1
    lanes = payload.get("lanes") or []
    for index, lane in enumerate(lanes):
      if not isinstance(lane, dict) or not bool(lane.get("active", False)):
        continue
      candidate = str(lane.get("activeDirection") or "")
      if (not candidate or candidate == "none") and len(lane.get("directions") or []) == 1:
        candidate = str((lane.get("directions") or [""])[0] or "")
      if candidate and candidate != "none":
        active_lane_direction = candidate
        active_lane_index = index
        break

    active_lane_side = ""
    if active_lane_direction in ("slightLeft", "left", "sharpLeft"):
      active_lane_side = "left"
    elif active_lane_direction in ("slightRight", "right", "sharpRight"):
      active_lane_side = "right"

    same_side_lane_count = 0
    active_lane_at_road_edge = False
    has_shared_same_side_lane = False
    if active_lane_side:
      same_side_directions = {"slightLeft", "left", "sharpLeft"} if active_lane_side == "left" else {"slightRight", "right", "sharpRight"}
      active_lane_at_road_edge = active_lane_index == 0 if active_lane_side == "left" else active_lane_index == len(lanes) - 1
      for lane in lanes:
        if not isinstance(lane, dict):
          continue
        directions = {str(direction) for direction in lane.get("directions") or [] if direction}
        if directions & same_side_directions:
          same_side_lane_count += 1
          has_shared_same_side_lane |= len(directions - same_side_directions) > 0

    state = {
      "valid": True,
      "maneuverModifier": str(payload.get("maneuverModifier") or ""),
      "maneuverType": str(payload.get("maneuverType") or ""),
      "laneCount": len(lanes),
      "activeLaneDirection": active_lane_direction,
      "activeLaneIndex": active_lane_index,
      "activeLaneAtRoadEdge": active_lane_at_road_edge,
      "hasSharedSameSideLane": has_shared_same_side_lane,
      "sameSideLaneCount": same_side_lane_count,
      "maneuverPrimaryText": str(payload.get("maneuverPrimaryText") or ""),
      "maneuverSecondaryText": str(payload.get("maneuverSecondaryText") or ""),
      "maneuverDistance": float(payload.get("maneuverDistance") or 0.0),
      "nextManeuverType": str(next_maneuver.get("type") or ""),
      "nextManeuverModifier": str(next_maneuver.get("modifier") or ""),
      "nextManeuverDistance": float(next_maneuver.get("distance") or 0.0),
      "jamDistance": -1.0,
      "jamSpeed": 0.0,
    }
    if jam is not None:
      state["jamDistance"] = float(round(jam[0] / 10.0) * 10.0)
      state["jamSpeed"] = round(float(jam[1]), 1)
    if state != self._last_nav_state:
      self.params_memory.put_nonblocking("NavInstructionState", state)
      self._last_nav_state = state

  def _publish_nav_route_if_needed(self) -> None:
    route, _, route_generation = self._snapshot_route()
    now = monotonic()
    republish_due = route is not None and now - self._published_route_at >= NAV_ROUTE_REPUBLISH_SECONDS
    if route_generation == self._published_route_generation and not republish_due:
      return

    msg = messaging.new_message("navRoute")
    msg.valid = route is not None
    if route is not None:
      msg.navRoute.coordinates = [
        {"latitude": coordinate.latitude, "longitude": coordinate.longitude}
        for coordinate in route.geometry
      ]

    self.pm.send("navRoute", msg)
    self._published_route_generation = route_generation
    self._published_route_at = now

  def run(self) -> None:
    cloudlog.warning("navigationd init")

    while True:
      location_valid, v_ego = self._update_location()
      current_destination = parse_destination_json(self.params.get("NavDestination", encoding="utf-8"))
      route, active_destination, _ = self._maybe_update_route(current_destination)

      progress, route_state = self._build_progress(route, location_valid, v_ego)
      self._maybe_recompute(route, current_destination or active_destination, progress, route_state)
      updated_route, active_destination, _ = self._snapshot_route()
      if updated_route is not route and updated_route is not None and location_valid and self._last_position is not None:
        progress = updated_route.get_progress(self._last_position)
      route = updated_route
      if route is None:
        progress = None

      payload = None
      if route is not None and progress is not None and location_valid:
        payload = route.build_instruction_payload(
          progress,
          use_vienna_sign=self.params.get_bool("UseVienna"),
        )

      now = monotonic()
      if location_valid:
        self._maybe_check_traffic(route, current_destination or active_destination, progress, now)
      self._update_reroute_prompt(progress if location_valid else None, now)
      jam = self._jam_ahead(route, progress, now) if location_valid else None

      self._publish_nav_instruction(route, progress, location_valid, payload)
      self._publish_nav_state(route, progress, location_valid, payload, jam)
      self._publish_nav_route_if_needed()
      self.rk.keep_time()


def main() -> None:
  Navigationd().run()


if __name__ == "__main__":
  main()
