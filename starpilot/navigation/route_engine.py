from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import requests

from cereal import log
from openpilot.common.constants import CV

DIRECTIONS = ("left", "right", "straight")
MODIFIABLE_DIRECTIONS = ("left", "right")

EARTH_MEAN_RADIUS = 6371007.2
SPEED_CONVERSIONS = {
  "km/h": CV.KPH_TO_MS,
  "mph": CV.MPH_TO_MS,
}

OFF_ROUTE_SPEED_BREAKPOINTS = [0.0, 5.0, 10.0, 20.0, 40.0]
OFF_ROUTE_DISTANCE_BREAKPOINTS = [40.0, 50.0, 60.0, 80.0, 100.0]
UPCOMING_TURN_SPEED_BREAKPOINTS = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]
UPCOMING_TURN_DISTANCE_BREAKPOINTS = [20.0, 25.0, 30.0, 45.0, 60.0, 75.0, 90.0, 105.0, 120.0]
UTURN_MODIFIER = "uturn"

LANE_DIRECTIONS = frozenset({
  "none",
  "left",
  "right",
  "straight",
  "slightLeft",
  "slightRight",
})


@dataclass(frozen=True)
class Coordinate:
  latitude: float
  longitude: float

  def __sub__(self, other: "Coordinate") -> "Coordinate":
    return Coordinate(self.latitude - other.latitude, self.longitude - other.longitude)

  def __add__(self, other: "Coordinate") -> "Coordinate":
    return Coordinate(self.latitude + other.latitude, self.longitude + other.longitude)

  def __mul__(self, scale: float) -> "Coordinate":
    return Coordinate(self.latitude * scale, self.longitude * scale)

  def dot(self, other: "Coordinate") -> float:
    return self.latitude * other.latitude + self.longitude * other.longitude

  def distance_to(self, other: "Coordinate") -> float:
    dlat = math.radians(other.latitude - self.latitude)
    dlon = math.radians(other.longitude - self.longitude)

    haversine_dlat = math.sin(dlat / 2.0) ** 2
    haversine_dlon = math.sin(dlon / 2.0) ** 2

    a = haversine_dlat + math.cos(math.radians(self.latitude)) * math.cos(math.radians(other.latitude)) * haversine_dlon
    return 2.0 * math.asin(math.sqrt(a)) * EARTH_MEAN_RADIUS


@dataclass(frozen=True)
class RouteStep:
  banner_instructions: list[dict[str, Any]]
  distance: float
  duration: float
  maneuver: str
  location: Coordinate
  cumulative_distance: float
  maxspeed_ms: float
  modifier: str
  instruction: str


@dataclass(frozen=True)
class RouteProgress:
  closest_index: int
  closest_segment_index: int
  distance_from_route: float
  current_step: RouteStep
  next_step: RouteStep | None
  current_step_index: int
  distance_to_end_of_step: float
  distance_remaining: float
  time_remaining: float
  current_speed_limit_ms: float
  all_maneuvers: list[dict[str, Any]]
  along_distance: float = 0.0  # metres along the route geometry to the car's projection


def bearing_between_two_points(point_one: Coordinate, point_two: Coordinate) -> float:
  lat_one = math.radians(point_one.latitude)
  lat_two = math.radians(point_two.latitude)
  dlon = math.radians(point_two.longitude - point_one.longitude)

  bearing_radians = math.atan2(
    math.sin(dlon) * math.cos(lat_two),
    math.cos(lat_one) * math.sin(lat_two) - math.sin(lat_one) * math.cos(lat_two) * math.cos(dlon),
  )
  return (math.degrees(bearing_radians) + 360.0) % 360.0


def minimum_distance(a: Coordinate, b: Coordinate, p: Coordinate) -> float:
  if a.distance_to(b) < 0.01:
    return a.distance_to(p)

  ap = p - a
  ab = b - a
  t = np.clip(ap.dot(ab) / ab.dot(ab), 0.0, 1.0)
  projection = a + ab * t
  return projection.distance_to(p)

def project_onto_segment(a: Coordinate, b: Coordinate, p: Coordinate) -> tuple[float, float]:
  lat_scale = EARTH_MEAN_RADIUS * math.pi / 180.0
  ref_lat = math.radians((a.latitude + b.latitude + p.latitude) / 3.0)
  lon_scale = lat_scale * math.cos(ref_lat)

  ab_x = (b.longitude - a.longitude) * lon_scale
  ab_y = (b.latitude - a.latitude) * lat_scale
  ap_x = (p.longitude - a.longitude) * lon_scale
  ap_y = (p.latitude - a.latitude) * lat_scale

  segment_length_sq = ab_x * ab_x + ab_y * ab_y
  if segment_length_sq <= 1e-6:
    return 0.0, math.hypot(ap_x, ap_y)

  t = float(np.clip((ap_x * ab_x + ap_y * ab_y) / segment_length_sq, 0.0, 1.0))
  proj_x = ab_x * t
  proj_y = ab_y * t
  return t, math.hypot(ap_x - proj_x, ap_y - proj_y)


def string_to_direction(direction: str) -> str:
  normalized = direction or ""
  for direction_name in DIRECTIONS:
    if direction_name not in normalized:
      continue
    if "slight" in normalized and direction_name in MODIFIABLE_DIRECTIONS:
      return f"slight{direction_name.capitalize()}"
    if "sharp" in normalized and direction_name in MODIFIABLE_DIRECTIONS:
      return f"sharp{direction_name.capitalize()}"
    return direction_name

  if "uturn" in normalized or "u-turn" in normalized:
    return UTURN_MODIFIER

  return "none"


def normalize_lane_direction(direction: str) -> str:
  normalized = string_to_direction(direction)
  return normalized if normalized in LANE_DIRECTIONS else "none"


def maxspeed_to_ms(maxspeed: dict[str, str | float]) -> float:
  unit = str(maxspeed["unit"])
  speed = float(maxspeed["speed"])
  return float(SPEED_CONVERSIONS[unit] * speed)


def field_valid(dat: dict[str, Any], field: str) -> bool:
  return field in dat and dat[field] is not None


def parse_banner_instructions(banners: Any, distance_to_maneuver: float = 0.0) -> dict[str, Any] | None:
  if not banners:
    return None

  instruction: dict[str, Any] = {}
  current_banner = banners[0]
  for banner in banners:
    if distance_to_maneuver < banner["distanceAlongGeometry"]:
      current_banner = banner

  instruction["showFull"] = distance_to_maneuver < current_banner["distanceAlongGeometry"]

  primary = current_banner["primary"]
  if field_valid(primary, "text"):
    instruction["maneuverPrimaryText"] = primary["text"]
  if field_valid(primary, "type"):
    instruction["maneuverType"] = primary["type"]
  if field_valid(primary, "modifier"):
    instruction["maneuverModifier"] = string_to_direction(primary["modifier"])

  if field_valid(current_banner, "secondary"):
    instruction["maneuverSecondaryText"] = current_banner["secondary"]["text"]

  if field_valid(current_banner, "sub"):
    lanes = []
    for component in current_banner["sub"]["components"]:
      if component["type"] != "lane":
        continue

      lane = {
        "active": component["active"],
        "directions": [normalize_lane_direction(direction) for direction in component["directions"]],
      }
      if field_valid(component, "active_direction"):
        lane["activeDirection"] = normalize_lane_direction(component["active_direction"])
      lanes.append(lane)
    instruction["lanes"] = lanes

  return instruction


@dataclass
class NavigationRoute:
  geometry: list[Coordinate]
  geometry_cumulative_distances: list[float]
  bearings: list[float]
  steps: list[RouteStep]
  total_distance: float
  total_duration: float
  eco_cost: float = 0.0
  is_eco_recommended: bool = False
  eco_savings_pct: float = 0.0
  congestion: list[str] = field(default_factory=list)       # Mapbox level per geometry segment (D-112)
  segment_speeds: list[float] = field(default_factory=list)  # Mapbox typical speed per geometry segment, m/s

  def calculate_eco_cost(self) -> float:
    """Calculate estimated fuel/energy consumption index for a route.
    
    Physics model:
    - Base rolling resistance / engine displacement is proportional to distance.
    - Aerodynamic drag power scales cubically with vehicle speed (v^3), meaning work per unit distance
      scales quadratically (v^2). Speeds exceeding 15 m/s (~34 mph) suffer rapid aerodynamic penalty.
    - Low-speed stop-and-go congestion (< 4 m/s ~ 9 mph) penalizes idling and repeated acceleration cycles.
    """
    total_energy = 0.0
    for step in self.steps:
      d_m = step.distance
      dt_s = max(1.0, step.duration)
      v_ms = d_m / dt_s
      step_cost = (d_m / 1000.0) * (1.0 + 0.8 * max(0.0, (v_ms - 15.0) / 10.0) ** 2)
      if v_ms < 4.0 and d_m > 0:
        step_cost += (dt_s / 60.0) * 0.4
      total_energy += step_cost
    if total_energy == 0.0 and self.total_distance > 0.0:
      v_avg = self.total_distance / max(1.0, self.total_duration)
      total_energy = (self.total_distance / 1000.0) * (1.0 + 0.8 * max(0.0, (v_avg - 15.0) / 10.0) ** 2)
    return float(total_energy)

  @classmethod
  def from_mapbox_route(cls, route_data: dict[str, Any]) -> "NavigationRoute" | None:
    geometry_data = route_data.get("geometry") or []
    steps_data = route_data.get("steps") or []
    if not geometry_data or not steps_data:
      return None

    geometry = [Coordinate(float(coord["latitude"]), float(coord["longitude"])) for coord in geometry_data]
    cumulative_distances = [0.0]
    for index in range(1, len(geometry)):
      cumulative_distances.append(cumulative_distances[-1] + geometry[index - 1].distance_to(geometry[index]))

    maxspeeds = [maxspeed_to_ms(item) for item in route_data.get("maxspeed", []) if field_valid(item, "speed") and field_valid(item, "unit")]

    steps: list[RouteStep] = []
    for step in steps_data:
      location = Coordinate(float(step["location"]["latitude"]), float(step["location"]["longitude"]))
      closest_index = min(range(len(geometry)), key=lambda idx: location.distance_to(geometry[idx]))
      maxspeed_ms = maxspeeds[min(closest_index, len(maxspeeds) - 1)] if maxspeeds else 0.0
      steps.append(RouteStep(
        banner_instructions=step.get("bannerInstructions", []),
        distance=float(step["distance"]),
        duration=float(step["duration"]),
        maneuver=str(step["maneuver"]),
        location=location,
        cumulative_distance=cumulative_distances[closest_index],
        maxspeed_ms=maxspeed_ms,
        modifier=string_to_direction(str(step.get("modifier", "none"))),
        instruction=str(step.get("instruction", "")),
      ))

    bearings = [bearing_between_two_points(geometry[index], geometry[index + 1]) for index in range(len(geometry) - 1)]
    return cls(
      geometry=geometry,
      geometry_cumulative_distances=cumulative_distances,
      bearings=bearings,
      steps=steps,
      total_distance=float(route_data.get("totalDistance", 0.0)),
      total_duration=float(route_data.get("totalDuration", 0.0)),
      congestion=[str(level) for level in route_data.get("congestion", [])],
      segment_speeds=[float(speed) if isinstance(speed, (int, float)) else 0.0 for speed in route_data.get("speed", [])],
    )

  def route_bearing_misaligned(self, closest_segment_index: int, current_bearing: float | None, v_ego: float) -> bool:
    if current_bearing is None or v_ego < 2.5 or closest_segment_index < 0 or closest_segment_index >= len(self.bearings):
      return False

    route_bearing = self.bearings[closest_segment_index]
    normalized_bearing = (current_bearing + 360.0) % 360.0
    bearing_difference = abs(normalized_bearing - route_bearing)
    return min(bearing_difference, 360.0 - bearing_difference) > 75.0

  def get_progress(self, position: Coordinate) -> RouteProgress | None:
    if not self.geometry or not self.steps:
      return None
    if len(self.geometry) == 1:
      closest_index = 0
      closest_segment_index = 0
      min_distance = position.distance_to(self.geometry[0])
      closest_cumulative = 0.0
    else:
      best_segment_index = 0
      best_distance = float("inf")
      best_t = 0.0

      for index in range(len(self.geometry) - 1):
        t, segment_distance = project_onto_segment(self.geometry[index], self.geometry[index + 1], position)
        if segment_distance < best_distance:
          best_distance = segment_distance
          best_segment_index = index
          best_t = t

      closest_segment_index = best_segment_index
      segment_start = self.geometry_cumulative_distances[closest_segment_index]
      segment_end = self.geometry_cumulative_distances[closest_segment_index + 1]
      closest_cumulative = segment_start + (segment_end - segment_start) * best_t
      min_distance = best_distance
      closest_index = min(closest_segment_index + (1 if best_t >= 0.5 else 0), len(self.geometry) - 1)

    current_step_index = max(
      (idx for idx, step in enumerate(self.steps) if step.cumulative_distance <= (closest_cumulative + 1e-3)),
      default=-1,
    )
    current_step = self.steps[current_step_index if current_step_index >= 0 else 0]
    next_step_index = current_step_index + 1
    next_step = self.steps[next_step_index] if 0 <= next_step_index < len(self.steps) else None

    distance_to_end_of_step = max(0.0, current_step.distance - (closest_cumulative - current_step.cumulative_distance))
    distance_remaining = max(0.0, self.total_distance - closest_cumulative)

    current_step_distance = max(current_step.distance, 1.0)
    remaining_current_duration = current_step.duration * min(distance_to_end_of_step / current_step_distance, 1.0)
    later_duration = sum(step.duration for step in self.steps[next_step_index:])
    time_remaining = max(0.0, remaining_current_duration + later_duration)

    all_maneuvers: list[dict[str, Any]] = []
    start_index = max(current_step_index, 0)
    end_index = min(start_index + 3, len(self.steps))
    for index in range(start_index, end_index):
      step = self.steps[index]
      maneuver_distance = distance_to_end_of_step if index == start_index else max(0.0, step.cumulative_distance - closest_cumulative)
      all_maneuvers.append({
        "distance": maneuver_distance,
        "type": step.maneuver,
        "modifier": step.modifier,
      })

    return RouteProgress(
      closest_index=closest_index,
      closest_segment_index=closest_segment_index,
      distance_from_route=min_distance,
      current_step=current_step,
      next_step=next_step,
      current_step_index=max(current_step_index, 0),
      distance_to_end_of_step=distance_to_end_of_step,
      distance_remaining=distance_remaining,
      time_remaining=time_remaining,
      current_speed_limit_ms=current_step.maxspeed_ms,
      all_maneuvers=all_maneuvers,
      along_distance=closest_cumulative,
    )

  def upcoming_turn_modifier(self, progress: RouteProgress, position: Coordinate, v_ego: float) -> str:
    if progress.next_step is None:
      return "none"

    distance_threshold = float(np.interp(v_ego, UPCOMING_TURN_SPEED_BREAKPOINTS, UPCOMING_TURN_DISTANCE_BREAKPOINTS))
    if position.distance_to(progress.next_step.location) <= distance_threshold:
      return progress.next_step.modifier
    return "none"

  def off_route_distance_exceeded(self, progress: RouteProgress, v_ego: float) -> bool:
    distance_threshold = float(np.interp(v_ego, OFF_ROUTE_SPEED_BREAKPOINTS, OFF_ROUTE_DISTANCE_BREAKPOINTS))
    return progress.distance_from_route > distance_threshold

  def arrived(self, progress: RouteProgress, v_ego: float) -> bool:
    if v_ego >= 2.0 or not progress.all_maneuvers:
      return False
    current = progress.all_maneuvers[0]
    destination_step = current["type"] == "arrive" or progress.current_step.maneuver == "arrive" or progress.current_step.instruction.startswith("Your destination")
    if not destination_step and progress.next_step is not None:
      destination_step = progress.next_step.maneuver == "arrive" and progress.distance_to_end_of_step <= max(15.0, v_ego * 8.0)
    return destination_step and progress.distance_remaining <= 40.0

  def build_instruction_payload(self, progress: RouteProgress, *, use_vienna_sign: bool = False) -> dict[str, Any]:
    parsed = parse_banner_instructions(progress.current_step.banner_instructions, progress.distance_to_end_of_step) or {}
    primary_text = parsed.get("maneuverPrimaryText") or progress.current_step.instruction
    secondary_text = parsed.get("maneuverSecondaryText") or ""
    maneuver_type = parsed.get("maneuverType") or progress.current_step.maneuver
    maneuver_modifier = parsed.get("maneuverModifier") or progress.current_step.modifier
    lanes = []
    for lane in parsed.get("lanes", []):
      directions = [direction for direction in lane.get("directions", []) if direction in LANE_DIRECTIONS]
      active_direction = lane.get("activeDirection", "none")
      lanes.append({
        "directions": directions or ["none"],
        "active": bool(lane.get("active", False)),
        "activeDirection": active_direction if active_direction in LANE_DIRECTIONS else "none",
      })

    return {
      "maneuverPrimaryText": primary_text,
      "maneuverSecondaryText": secondary_text,
      "maneuverDistance": progress.distance_to_end_of_step,
      "maneuverType": maneuver_type,
      "maneuverModifier": maneuver_modifier,
      "distanceRemaining": progress.distance_remaining,
      "timeRemaining": progress.time_remaining,
      "timeRemainingTypical": progress.time_remaining,
      "lanes": lanes,
      "showFull": bool(parsed.get("showFull", True)),
      "speedLimit": progress.current_speed_limit_ms,
      "speedLimitSign": log.NavInstruction.SpeedLimitSign.vienna if use_vienna_sign else log.NavInstruction.SpeedLimitSign.mutcd,
      "allManeuvers": progress.all_maneuvers,
    }


class MapboxRouteEngine:
  DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"

  def __init__(self, session: Any = requests, usage: Any = None):
    self._session = session
    self._usage = usage  # MapboxUsage, counting each directions request

  def fetch_route(self, token: str, start: Coordinate, destination: dict[str, Any], bearing: float | None = None) -> NavigationRoute | None:
    route_id = str(destination.get("routeId") or "main")
    requested_route_index = int(route_id[4:]) if route_id.startswith("alt-") and route_id[4:].isdigit() else 0
    # prefer_eco may promote an alternative to index 0, so "main" needs the alternatives too.
    routes = self.fetch_routes(token, start, destination, bearing,
                               alternatives=requested_route_index > 0 or bool(destination.get("prefer_eco", False)))
    if not routes:
      return None
    return routes[requested_route_index] if requested_route_index < len(routes) else routes[0]

  def fetch_routes(self, token: str, start: Coordinate, destination: dict[str, Any], bearing: float | None = None,
                   alternatives: bool = True) -> list[NavigationRoute]:
    """The main route first, then Mapbox's alternatives (routeId "alt-1", "alt-2", ...)."""
    if not token:
      return []

    end = Coordinate(float(destination["latitude"]), float(destination["longitude"]))
    params: dict[str, str] = {
      "access_token": token,
      "geometries": "geojson",
      "steps": "true",
      "overview": "full",
      "annotations": "maxspeed,congestion,speed",
      "alternatives": "true" if alternatives else "false",
      "banner_instructions": "true",
    }
    avoid_tolls = bool(destination.get("avoid_tolls", False))
    avoid_highways = bool(destination.get("avoid_highways", False))
    avoid_ferries = bool(destination.get("avoid_ferries", False))
    prefer_eco = bool(destination.get("prefer_eco", False))

    excludes = []
    if avoid_tolls:
      excludes.append("toll")
    if avoid_highways:
      excludes.append("motorway")
    if avoid_ferries:
      excludes.append("ferry")
    if excludes:
      params["exclude"] = ",".join(excludes)

    if bearing is not None:
      params["bearings"] = f"{int((bearing + 360.0) % 360.0)},90;"

    url = f"{self.DIRECTIONS_URL}/{start.longitude},{start.latitude};{end.longitude},{end.latitude}"
    try:
      response = self._session.get(url, params=params, timeout=5)
      if self._usage is not None:
        self._usage.add("directions")
      data = response.json() if response.status_code == 200 else {}
    except (requests.RequestException, ValueError):
      return []

    if data.get("code") != "Ok":
      return []
    routes = []
    for route in data.get("routes") or []:
      parsed = self._parse_route(route)
      if parsed is not None:
        routes.append(parsed)

    for r in routes:
      r.eco_cost = r.calculate_eco_cost()

    if prefer_eco and len(routes) > 1:
      best_eco_idx = min(range(len(routes)), key=lambda i: routes[i].eco_cost)
      baseline_cost = routes[0].eco_cost
      best_cost = routes[best_eco_idx].eco_cost
      savings = max(0.0, (baseline_cost - best_cost) / baseline_cost * 100.0) if baseline_cost > 0.0 else 0.0
      routes[best_eco_idx].is_eco_recommended = True
      routes[best_eco_idx].eco_savings_pct = savings

      # Always reorder (for "main" and "alt-N" alike) so "alt-N" indexes the same list that the
      # Galaxy and device previews show: best eco route first, the rest in Mapbox order.
      if best_eco_idx != 0:
        eco_route = routes.pop(best_eco_idx)
        routes.insert(0, eco_route)

    return routes

  @staticmethod
  def _parse_route(route: dict[str, Any]) -> NavigationRoute | None:
    legs = route.get("legs")
    leg = legs[0] if legs else None
    if leg is None:
      return None

    route_data = {
      "steps": [
        {
          "maneuver": step["maneuver"]["type"],
          "instruction": step["maneuver"]["instruction"],
          "distance": step["distance"],
          "duration": step["duration"],
          "location": {
            "longitude": step["maneuver"]["location"][0],
            "latitude": step["maneuver"]["location"][1],
          },
          "modifier": step["maneuver"].get("modifier", "none"),
          "bannerInstructions": step.get("bannerInstructions", []),
        }
        for step in leg.get("steps", [])
      ],
      "totalDistance": route["distance"],
      "totalDuration": route["duration"],
      "geometry": [
        {"longitude": coord[0], "latitude": coord[1]}
        for coord in route["geometry"]["coordinates"]
      ],
      "maxspeed": [
        {"speed": item["speed"], "unit": item["unit"]}
        for item in leg.get("annotation", {}).get("maxspeed", [])
        if field_valid(item, "speed") and field_valid(item, "unit")
      ],
      "congestion": list(leg.get("annotation", {}).get("congestion", [])),
      "speed": list(leg.get("annotation", {}).get("speed", [])),
    }
    return NavigationRoute.from_mapbox_route(route_data)
