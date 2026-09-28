import colorsys
import math
import time
import numpy as np
import pyray as rl
from cereal import messaging, car
from dataclasses import dataclass, field
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.controls.lib.lane_centering import get_lane_centering_visual_direction
from openpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT
from openpilot.selfdrive.ui.lib.starpilot_theme import get_param_color, get_theme_color, get_visual_color, is_stock_color_scheme, with_alpha
from openpilot.selfdrive.ui.onroad.radar_tracks import project_radar_points
from openpilot.selfdrive.ui.onroad.starpilot.rainbow_path import RainbowPath
from openpilot.selfdrive.ui.lib.starpilot_visuals import LeadInfoMode, blend_colors, lead_indicator_enabled, lead_info_mode, multi_lead_ui_enabled
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.selfdrive.ui.mici.onroad.starpilot_status import get_border_color
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

CLIP_MARGIN = 500
# Radar points (liveTracks), behind the "Radar Point Display" toggle (RadarTracksUI) like the big UI; sized down from its
# 7 / 9 px dots for the 536 px C4 screen (owner request). Drawn over the lead markers, so a lead's radar return shows
# against its vision marker; points off the screen are dropped rather than pinned to its edge.
RADAR_POINT_RADIUS = 4.0
RADAR_POINT_OUTLINE_RADIUS = 5.5
RADAR_POINT_FILL_COLOR = rl.Color(255, 40, 40, 230)
RADAR_POINT_OUTLINE_COLOR = rl.Color(0, 0, 0, 170)
# A close lead's marker is clamped against the bottom of the view and its speed label is cut off below it, so it is
# flipped: drawn on the lead's roof, pointing down, with its speed above it (owner request).
LEAD_ROOF_HEIGHT = 1.5         # m above the road where the flipped marker's tip sits
LEAD_LABEL_ROOM = 32           # px a speed label needs next to its marker: 2 px gap + the 26 px label box (30.2 px)
FLIPPED_LEAD_UNFLIP_SZ = 1.0   # hysteresis: stays flipped until the upright label has this many marker sizes to spare
# Stop-and-go (owner: "flip back without flicker"): a marker holds each flip at least this long, and a lead slot keeps
# its flip state through a dropout this short (route 00000267 seg 10 625.0 s: a flipped lead blinked out for one frame
# and came back upright inside the hysteresis band).
LEAD_FLIP_MIN_HOLD_S = 1.0
LEAD_FLIP_MEMORY_S = 1.0
# An adjacent-lane lead this close to an in-path lead is the same car; only the in-path marker and label are drawn
# (owner: "sometimes the speed label doubles"; 00000267 seg 16 38.2 s: leadOne and leadRight were radar track 41).
SAME_LEAD_D_REL = 1.5
SAME_LEAD_Y_REL = 1.0
# A side-lane lead's marker and label wait until the same radar track has held that slot this long; until then only its
# radar dot shows (owner: "just radar points on those"). 28f 8:37-12:30 (replay, Radar Work (Bob)): 62 oncoming cars
# reached leadLeft for ~0.9 s each at a railed ~17 mph, and 6b22b5da's radard latch still lets the first ~0.3 s through;
# 5 real same-direction side cars in that window held their slot 2.7 s (median).
SIDE_LEAD_MIN_AGE_S = 0.5
MIN_DRAW_DISTANCE = 10.0
MAX_DRAW_DISTANCE = 100.0
STOCK_LANE_LINES_COLOR = rl.Color(255, 255, 255, 255)
OCEAN_BLUE_LANE_LINES_COLOR = rl.Color(0, 176, 220, 255)
DEFAULT_LANE_LINES_WIDTH = 4.0
DEFAULT_PATH_WIDTH = 6.1
DEFAULT_ROAD_EDGES_WIDTH = 2.0
LANE_LINE_COLORS = {
  UIStatus.DISENGAGED: rl.Color(200, 200, 200, 255),
  UIStatus.OVERRIDE: rl.Color(255, 255, 255, 255),
  UIStatus.ENGAGED: rl.Color(0, 255, 64, 255),
}

THROTTLE_COLORS = [
  rl.Color(13, 248, 122, 102),   # HSLF(148/360, 0.94, 0.51, 0.4)
  rl.Color(114, 255, 92, 89),    # HSLF(112/360, 1.0, 0.68, 0.35)
  rl.Color(114, 255, 92, 0),     # HSLF(112/360, 1.0, 0.68, 0.0)
]

NO_THROTTLE_COLORS = [
  rl.Color(242, 242, 242, 102), # HSLF(148/360, 0.0, 0.95, 0.4)
  rl.Color(242, 242, 242, 89),  # HSLF(112/360, 0.0, 0.95, 0.35)
  rl.Color(242, 242, 242, 0),   # HSLF(112/360, 0.0, 0.95, 0.0)
]


def show_top_lead_info(mode: LeadInfoMode, multi_lead_ui: bool) -> bool:
  """The top-centre lead readout. Hidden in speed mode while every marker carries its own speed label
  (owner: "too redundant"); distance mode still shows, since the marker labels carry speed only."""
  if mode == LeadInfoMode.OFF:
    return False
  return not (multi_lead_ui and mode == LeadInfoMode.SPEED)


@dataclass
class ModelPoints:
  raw_points: np.ndarray = field(default_factory=lambda: np.empty((0, 3), dtype=np.float32))
  projected_points: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))


LEAD_LABEL_FONT_SIZE = 26  # owner: 20, then 24, read too small on the road (2026-09-24)
ADJACENT_LEFT_LEAD_COLOR = rl.Color(0, 150, 255, 255)
ADJACENT_RIGHT_LEAD_COLOR = rl.Color(180, 0, 255, 255)
ADJACENT_LEAD_MIN_ALPHA = 140
# adjacent-lane markers draw smaller than the in-path ones, with a smaller speed label (owner: "slightly smaller,
# with the speed label right below it")
ADJACENT_LEAD_SCALE = 0.7
ADJACENT_LEAD_LABEL_FONT_SIZE = 22
# radard's leadLeft/leadRight is any moving track past our own lane line, with no outer bound, so a car two
# lanes over or a roadside return can hold it. The marker only draws for a lead inside the neighbouring lane
# (owner: "only show up when there is an actual lead on that lane"). UI only; radard is unchanged.
ADJACENT_LANE_OUTER_MIN_PROB = 0.3  # below this the far lane line is not trusted and our own lane width stands in
ADJACENT_LANE_WIDTH_BOUNDS = (3.0, 4.5)
ADJACENT_LANE_OUTER_MARGIN = 0.5  # m past the far line still counts, for a car riding its lane edge


def lead_in_adjacent_lane(d_rel: float, y_rel: float, left: bool, lane_lines, lane_line_probs) -> bool:
  """True when a radar lead sits between our lane line and the next one out on that side.

  lane_lines are the four modelV2 lines as (N, 3) x/y/z arrays, left to right; model y == -yRel.
  """
  if len(lane_lines) < 4 or any(len(line) == 0 for line in lane_lines):
    return False
  if not (0.0 < d_rel <= float(lane_lines[1][-1, 0])):
    return False

  def y_at(i):
    return float(np.interp(d_rel, lane_lines[i][:, 0], lane_lines[i][:, 1]))

  inner_i, outer_i, sign = (1, 0, -1.0) if left else (2, 3, 1.0)
  inner = y_at(inner_i)
  if lane_line_probs[outer_i] >= ADJACENT_LANE_OUTER_MIN_PROB:
    outer = y_at(outer_i)
  else:
    outer = inner + sign * float(np.clip(y_at(2) - y_at(1), *ADJACENT_LANE_WIDTH_BOUNDS))
  outer += sign * ADJACENT_LANE_OUTER_MARGIN

  model_y = -y_rel
  return bool(min(inner, outer) < model_y < max(inner, outer))


def same_lead(a, b) -> bool:
  """Two published leads that are one car: the same radar track, or (vision-only, track -1) the same spot."""
  if not (a and a.status and b and b.status):
    return False
  a_track, b_track = getattr(a, "radarTrackId", -1), getattr(b, "radarTrackId", -1)
  if a_track >= 0 and a_track == b_track:
    return True
  return abs(a.dRel - b.dRel) < SAME_LEAD_D_REL and abs(a.yRel - b.yRel) < SAME_LEAD_Y_REL


@dataclass
class _FlipState:
  flipped: bool
  changed_at: float
  seen_at: float


@dataclass
class LeadVehicle:
  glow: list[float] = field(default_factory=list)
  chevron: list[float] = field(default_factory=list)
  fill_alpha: int = 0
  flipped: bool = False


class ModelRenderer(Widget):
  def __init__(self):
    super().__init__()
    self._longitudinal_control = False
    self._experimental_mode = False
    self._blend_filter = FirstOrderFilter(1.0, 0.25, 1 / gui_app.target_fps)
    self._prev_allow_throttle = True
    self._lane_line_probs = np.zeros(4, dtype=np.float32)
    self._road_edge_stds = np.zeros(2, dtype=np.float32)
    self._lead_vehicles = [LeadVehicle(), LeadVehicle()]
    self._adjacent_lead_vehicles = [LeadVehicle(), LeadVehicle()]
    self._multi_lead_ui = False
    self._lead_label_rects: list[rl.Rectangle] = []
    self._side_label_obstacles: list[rl.Rectangle] = []
    self._lead_info_mode = LeadInfoMode.OFF
    self._path_offset_z = HEIGHT_INIT[0]

    # Initialize ModelPoints objects
    self._path = ModelPoints()
    self._lane_lines = [ModelPoints() for _ in range(4)]
    self._road_edges = [ModelPoints() for _ in range(2)]
    self._acceleration_x = np.empty((0,), dtype=np.float32)

    self._acceleration_x_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    self._acceleration_x_filter2 = FirstOrderFilter(0.0, 1, 1 / gui_app.target_fps)

    self._torque_filter = FirstOrderFilter(0, 0.1, 1 / gui_app.target_fps)
    self._ll_color_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)

    # Transform matrix (3x3 for car space to screen space)
    self._car_space_transform = np.zeros((3, 3), dtype=np.float32)
    self._transform_dirty = True
    self._clip_region = None

    self._exp_gradient = Gradient(
      start=(0.0, 1.0),  # Bottom of path
      end=(0.0, 0.0),  # Top of path
      colors=[],
      stops=[],
    )
    self._path_gradient = Gradient(
      start=(0.0, 1.0),
      end=(0.0, 0.0),
      colors=THROTTLE_COLORS,
      stops=[0.0, 0.5, 1.0],
    )
    self._rainbow_path = RainbowPath()

    # Get longitudinal control setting from car parameters
    self._params = ui_state.ui_params
    if car_params := self._params.get("CarParams"):
      cp = messaging.log_from_bytes(car_params, car.CarParams)
      self._longitudinal_control = cp.openpilotLongitudinalControl

  def set_transform(self, transform: np.ndarray):
    transform = transform.astype(np.float32)
    if not np.array_equal(transform, self._car_space_transform):
      self._car_space_transform = transform
      self._transform_dirty = True

  def _render(self, rect: rl.Rectangle):
    sm = ui_state.sm

    self._torque_filter.update(-ui_state.sm['carOutput'].actuatorsOutput.torque)

    # Check if data is up-to-date
    if (sm.recv_frame["liveCalibration"] < ui_state.started_frame or
        sm.recv_frame["modelV2"] < ui_state.started_frame):
      return

    # Set up clipping region
    self._clip_region = rl.Rectangle(
      rect.x - CLIP_MARGIN, rect.y - CLIP_MARGIN, rect.width + 2 * CLIP_MARGIN, rect.height + 2 * CLIP_MARGIN
    )

    # Update state
    self._experimental_mode = sm['selfdriveState'].experimentalMode

    live_calib = sm['liveCalibration']
    self._path_offset_z = live_calib.height[0] if live_calib.height else HEIGHT_INIT[0]

    if sm.updated['carParams']:
      self._longitudinal_control = sm['carParams'].openpilotLongitudinalControl

    model = sm['modelV2']
    radar_state = sm['radarState'] if sm.valid['radarState'] else None
    lead_one = radar_state.leadOne if radar_state else None
    self._lead_info_mode = lead_info_mode(self._params)
    render_lead_indicator = self._should_render_lead_indicator(radar_state)
    self._multi_lead_ui = render_lead_indicator and multi_lead_ui_enabled(self._params)
    starpilot_radar_state = sm['starpilotRadarState'] if self._multi_lead_ui and sm.valid.get('starpilotRadarState', False) else None

    # Update model data when needed
    model_updated = sm.updated['modelV2']
    if model_updated or sm.updated['radarState'] or sm.updated['starpilotRadarState'] or self._transform_dirty:
      if model_updated:
        self._update_raw_points(model)

      path_x_array = self._path.raw_points[:, 0]
      if path_x_array.size == 0:
        return

      self._update_model(lead_one, path_x_array)
      if render_lead_indicator:
        self._update_leads(radar_state, path_x_array)
      self._update_adjacent_leads(starpilot_radar_state, path_x_array, radar_state if render_lead_indicator else None)
      self._transform_dirty = False

    self._draw_lane_lines()
    if self._params.get_bool("RainbowPath", default=False) and sm.valid.get('carState', False):
      self._rainbow_path.update(max(sm['carState'].vEgo, 0.0))
    self._draw_path(sm)

    if render_lead_indicator and radar_state:
      self._draw_lead_indicator(radar_state)
      if self._multi_lead_ui:
        self._draw_multi_lead_overlay(radar_state, starpilot_radar_state)
    self._draw_radar_points(sm)

  def _draw_radar_points(self, sm) -> None:
    """Every radar point (liveTracks) on screen as a small dot on the road."""
    if not self._params.get_bool("RadarTracksUI") or not sm.valid.get("liveTracks", False) or self._clip_region is None:
      return
    points = sm["liveTracks"].points
    if len(points) == 0 or self._path.raw_points.size == 0:
      return
    rect = self._rect
    bounds = (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
    screen = project_radar_points(
      np.fromiter((float(p.dRel) for p in points), dtype=np.float64, count=len(points)),
      np.fromiter((float(-p.yRel) for p in points), dtype=np.float64, count=len(points)),
      self._path.raw_points[:, 0], self._path.raw_points[:, 2], self._car_space_transform, float(self._path_offset_z),
      bounds, bounds,  # clip to the view itself: off-screen points are dropped, not clamped to the edge
    )
    for x, y in screen:
      center = rl.Vector2(float(x), float(y))
      rl.draw_circle_v(center, RADAR_POINT_OUTLINE_RADIUS, RADAR_POINT_OUTLINE_COLOR)
      rl.draw_circle_v(center, RADAR_POINT_RADIUS, RADAR_POINT_FILL_COLOR)

  def _should_render_lead_indicator(self, radar_state) -> bool:
    return radar_state is not None and lead_indicator_enabled(self._params, hide_by_default=True)

  def _update_raw_points(self, model):
    """Update raw 3D points from model data"""
    self._path.raw_points = np.array([model.position.x, model.position.y, model.position.z], dtype=np.float32).T

    # Model outputs can vary by branch/model family; keep renderer bounded to
    # the fixed number of lane/edge slots used by the UI.
    for lane_line in self._lane_lines:
      lane_line.raw_points = np.empty((0, 3), dtype=np.float32)
    lane_lines_count = min(len(self._lane_lines), len(model.laneLines))
    for i in range(lane_lines_count):
      lane_line = model.laneLines[i]
      self._lane_lines[i].raw_points = np.array([lane_line.x, lane_line.y, lane_line.z], dtype=np.float32).T

    for road_edge in self._road_edges:
      road_edge.raw_points = np.empty((0, 3), dtype=np.float32)
    road_edges_count = min(len(self._road_edges), len(model.roadEdges))
    for i in range(road_edges_count):
      road_edge = model.roadEdges[i]
      self._road_edges[i].raw_points = np.array([road_edge.x, road_edge.y, road_edge.z], dtype=np.float32).T

    lane_line_probs = np.array(model.laneLineProbs, dtype=np.float32)
    self._lane_line_probs = np.zeros(len(self._lane_lines), dtype=np.float32)
    self._lane_line_probs[:min(len(self._lane_lines), len(lane_line_probs))] = lane_line_probs[:len(self._lane_lines)]

    road_edge_stds = np.array(model.roadEdgeStds, dtype=np.float32)
    self._road_edge_stds = np.ones(len(self._road_edges), dtype=np.float32)
    self._road_edge_stds[:min(len(self._road_edges), len(road_edge_stds))] = road_edge_stds[:len(self._road_edges)]
    self._acceleration_x = np.array(model.acceleration.x, dtype=np.float32)

  def _update_leads(self, radar_state, path_x_array):
    """Update positions of lead vehicles"""
    self._lead_vehicles = [LeadVehicle(), LeadVehicle()]
    leads = [radar_state.leadOne, radar_state.leadTwo]

    for i, lead_data in enumerate(leads):
      if i == 1 and same_lead(leads[0], lead_data):
        # leadTwo is often leadOne again; the two slots keep separate flip memories, so drawing both could put one
        # marker on the roof and the other under the car (00000028a seg 28 1694.8 s, a 2.4 m lead)
        continue
      if lead_data and lead_data.status:
        d_rel, y_rel, v_rel = lead_data.dRel, lead_data.yRel, lead_data.vRel
        idx = self._get_path_length_idx(path_x_array, d_rel)

        # Get z-coordinate from path at the lead vehicle position
        z = self._path.raw_points[idx, 2] if idx < len(self._path.raw_points) else 0.0
        point = self._map_to_screen(d_rel, -y_rel, z + self._path_offset_z)
        top = self._map_to_screen(d_rel, -y_rel, z + self._path_offset_z - LEAD_ROOF_HEIGHT)
        if point or top:
          self._lead_vehicles[i] = self._place_lead(("path", i), d_rel, v_rel, point, top)

  def _update_adjacent_leads(self, starpilot_radar_state, path_x_array, radar_state=None):
    """Screen positions of the left/right adjacent-lane leads (starpilotRadarState), Developer UI only. A side lead
    that is the same car as an in-path lead is left out, so it is not drawn and labelled twice, and a side lead gets no
    marker or label until its radar track has held the slot SIDE_LEAD_MIN_AGE_S (its radar dot still draws)."""
    in_path = (radar_state.leadOne, radar_state.leadTwo) if radar_state is not None else ()
    self._adjacent_lead_vehicles = [LeadVehicle(), LeadVehicle()]
    ages = self.__dict__.setdefault("_side_lead_since", [None, None])
    if starpilot_radar_state is None:
      ages[:] = [None, None]
      return
    now = self._clock()
    lane_lines = [line.raw_points for line in self._lane_lines]
    for i, lead_data in enumerate((starpilot_radar_state.leadLeft, starpilot_radar_state.leadRight)):
      # how long this radar track has held the slot; a new track id or a status drop starts it over
      track = getattr(lead_data, "radarTrackId", -1) if lead_data and lead_data.status else None
      if track is None:
        ages[i] = None
        continue
      if ages[i] is None or ages[i][0] != track:
        ages[i] = (track, now)
      if now - ages[i][1] < SIDE_LEAD_MIN_AGE_S:
        continue
      if any(same_lead(lead_data, p) for p in in_path):
        continue
      if lead_in_adjacent_lane(lead_data.dRel, lead_data.yRel, i == 0, lane_lines, self._lane_line_probs):
        d_rel, y_rel, v_rel = lead_data.dRel, lead_data.yRel, lead_data.vRel
        idx = self._get_path_length_idx(path_x_array, d_rel)
        z = self._path.raw_points[idx, 2] if idx < len(self._path.raw_points) else 0.0
        point = self._map_to_screen(d_rel, -y_rel, z + self._path_offset_z)
        top = self._map_to_screen(d_rel, -y_rel, z + self._path_offset_z - LEAD_ROOF_HEIGHT)
        if point or top:
          self._adjacent_lead_vehicles[i] = self._place_lead(("side", i), d_rel + abs(y_rel), v_rel, point, top,
                                                             scale=ADJACENT_LEAD_SCALE)

  def _clock(self) -> float:
    return time.monotonic()

  def _place_lead(self, key, d_rel, v_rel, point, top, scale: float = 1.0) -> "LeadVehicle":
    """_update_lead_vehicle with per-slot flip memory: the flip state survives a dropout of up to
    LEAD_FLIP_MEMORY_S, and a flip is held at least LEAD_FLIP_MIN_HOLD_S before it may switch back."""
    now = self._clock()
    states = self.__dict__.setdefault("_flip_states", {})
    mem = states.get(key)
    if mem is not None and now - mem.seen_at > LEAD_FLIP_MEMORY_S:
      mem = None
    was = mem.flipped if mem else False
    lead = self._update_lead_vehicle(d_rel, v_rel, point, self._rect, scale=scale, top=top, was_flipped=was)
    if mem and lead.flipped != was and now - mem.changed_at < LEAD_FLIP_MIN_HOLD_S:
      held = self._update_lead_vehicle(d_rel, v_rel, point, self._rect, scale=scale, top=top, was_flipped=was, force_flip=was)
      if held.chevron:
        lead = held
    changed_at = mem.changed_at if mem and lead.flipped == was else now
    states[key] = _FlipState(lead.flipped, changed_at, now)
    return lead

  def _draw_multi_lead_overlay(self, radar_state, starpilot_radar_state) -> None:
    """Developer UI: adjacent-lane lead markers, and each marker's lead speed right beneath it."""
    self._lead_label_rects = []
    labelled = []
    for lead, lead_data in zip(self._lead_vehicles, (radar_state.leadOne, radar_state.leadTwo), strict=True):
      if lead.chevron and lead_data and lead_data.status:
        labelled.append((lead, lead_data, LEAD_LABEL_FONT_SIZE, 0))

    if starpilot_radar_state is not None:
      for lead, lead_data, color in zip(self._adjacent_lead_vehicles,
                                        (starpilot_radar_state.leadLeft, starpilot_radar_state.leadRight),
                                        (ADJACENT_LEFT_LEAD_COLOR, ADJACENT_RIGHT_LEAD_COLOR), strict=True):
        if not lead.glow or not lead.chevron or not (lead_data and lead_data.status):
          continue
        rl.draw_triangle_fan(lead.glow, len(lead.glow), rl.Color(218, 202, 37, 255))
        rl.draw_triangle_fan(lead.chevron, len(lead.chevron), with_alpha(color, max(lead.fill_alpha, ADJACENT_LEAD_MIN_ALPHA)))
        labelled.append((lead, lead_data, ADJACENT_LEAD_LABEL_FONT_SIZE, -1 if color is ADJACENT_LEFT_LEAD_COLOR else 1))

    use_si_metrics = ui_state.starpilot_toggles.get("UseSiMetrics", False)
    for lead, lead_data, font_size, side in labelled:
      text = self._format_lead_speed(getattr(lead_data, "vLead", 0.0), ui_state.is_metric, use_si_metrics)
      self._draw_lead_label(lead.chevron, text, font_size, side)

  def set_side_label_obstacles(self, rects: list[rl.Rectangle]) -> None:
    """HUD boxes (the speed-limit sign) that side-lane labels must not cover. Set each frame before render()."""
    self._side_label_obstacles = list(rects)

  def _below_obstacle(self, label_rect: rl.Rectangle, tried_x: list[float]):
    """The spot just below a HUD obstacle that one of the tried positions ran into, if it is free and on screen."""
    view = getattr(self, "_rect", None)
    for ob in getattr(self, "_side_label_obstacles", []):
      if not any(rl.check_collision_recs(rl.Rectangle(rx, label_rect.y, label_rect.width, label_rect.height), ob) for rx in tried_x):
        continue
      spot = rl.Rectangle(ob.x + (ob.width - label_rect.width) / 2, ob.y + ob.height + 2, label_rect.width, label_rect.height)
      on_screen = view is None or view.height <= 0 or spot.y + spot.height <= view.y + view.height
      if on_screen and not any(rl.check_collision_recs(spot, r) for r in self._lead_label_rects):
        return spot
    return None

  def _draw_lead_label(self, chevron, text: str, font_size: int = LEAD_LABEL_FONT_SIZE, side: int = 0) -> None:
    """Label under the marker (above it when the marker is flipped tip-down). Any label that would overlap another
    label is dropped, except that a side-lane label (side -1 left, +1 right) blocked only by other labels first tries
    sliding outward. A side-lane label never slides inward or off a HUD obstacle (the speed-limit sign): it is dropped,
    because either way it crossed over the in-path label and read as that car's speed. An in-path label slides off
    the sign toward the side it is on, then just below the sign, and is drawn in place if none fits (the sign alone
    never hides the in-path speed)."""
    from openpilot.selfdrive.ui.onroad.starpilot.path import _draw_text_with_outline

    font = gui_app.font(FontWeight.SEMI_BOLD)
    size = measure_text_cached(font, text, font_size)
    x = chevron[1][0] - size.x / 2
    view = getattr(self, "_rect", None)
    if view is not None and view.width > size.x + 6:  # keep a marker near the edge from pushing its label off-screen
      x = min(max(x, view.x + 3), view.x + view.width - size.x - 3)
    if chevron[1][1] > chevron[0][1]:  # flipped marker: tip below its base, label goes on top
      y = min(chevron[0][1], chevron[2][1]) - 2 - size.y
    else:
      y = max(chevron[0][1], chevron[2][1]) + 2
    label_rect = rl.Rectangle(x - 3, y - 1, size.x + 6, size.y + 2)
    obstacles = getattr(self, "_side_label_obstacles", [])
    blockers = self._lead_label_rects + obstacles

    def hits_at(rx: float) -> list[rl.Rectangle]:
      moved = rl.Rectangle(rx, label_rect.y, label_rect.width, label_rect.height)
      return [r for r in blockers if rl.check_collision_recs(moved, r)]

    def fits(rx: float) -> bool:
      view = getattr(self, "_rect", None)
      in_view = view is None or view.width <= 0 or (rx >= view.x and rx + label_rect.width <= view.x + view.width)
      return in_view and not hits_at(rx)

    hits = hits_at(label_rect.x)
    hit_obstacle = next((r for r in hits if any(r is ob for ob in obstacles)), None)
    if side and hit_obstacle is not None:
      # owner (2026-09-28): a right-lane label slid 180 px left off the sign, past the in-path label, and read as a
      # second in-path speed ("47 mph 56 mph ... super confusing"); the marker alone marks that car
      return
    dodge = side
    if not side and hit_obstacle is not None:
      # in-path label on the sign (e.g. a flipped cut-in at the right edge; owner: "make the cut-in label avoid the
      # sign too"): slide off it toward the side it is already on
      dodge = -1 if label_rect.x + label_rect.width / 2 < hit_obstacle.x + hit_obstacle.width / 2 else 1
    if hits and dodge:
      outward = (min(r.x for r in hits) - label_rect.width if dodge < 0 else max(r.x + r.width for r in hits))
      inward = (max(r.x + r.width for r in hits) if dodge < 0 else min(r.x for r in hits) - label_rect.width)
      # a side label slid inward lands on the far side of the label it hit (owner 2026-09-28, 28f seg 6: a right-lane
      # "56 mph" jumped left of the in-path "47 mph")
      new_x = next((rx for rx in ((outward,) if side else (outward, inward)) if fits(rx)), None)
      if new_x is not None:
        x += new_x - label_rect.x
        label_rect.x = new_x
        hits = []
      else:
        # No room beside it: if the sign is what blocks it, drop the label just below the sign (owner: "drop just
        # below the sign"), centred under it, rather than hiding the speed.
        below = None if side else self._below_obstacle(label_rect, [label_rect.x, outward, inward])
        if below is not None:
          x += below.x - label_rect.x
          y += below.y - label_rect.y
          label_rect = below
          hits = []
        elif side:
          return
        else:
          # the sign alone never hides the in-path speed: draw it in place unless it would cover another label
          hits = [r for r in hits if not any(r is ob for ob in obstacles)]
    if hits:
      return
    self._lead_label_rects.append(label_rect)
    _draw_text_with_outline(text, float(x), float(y), font, font_size)

  def _update_model(self, lead, path_x_array):
    """Update model visualization data based on model message"""
    model_ui_enabled = self._params.get_bool("ModelUI", default=True)
    path_width = 0.9
    lane_line_width = None
    road_edge_width = None
    if model_ui_enabled:
      path_width_value = self._params.get_float("PathWidth", default=DEFAULT_PATH_WIDTH)
      lane_line_width_value = self._params.get_float("LaneLinesWidth", default=DEFAULT_LANE_LINES_WIDTH)
      road_edge_width_value = self._params.get_float("RoadEdgesWidth", default=DEFAULT_ROAD_EDGES_WIDTH)
      custom_path_width = not math.isclose(path_width_value, DEFAULT_PATH_WIDTH, rel_tol=1e-5, abs_tol=1e-8)
      custom_lane_line_width = not math.isclose(lane_line_width_value, DEFAULT_LANE_LINES_WIDTH, rel_tol=1e-5, abs_tol=1e-8)
      custom_road_edge_width = not math.isclose(road_edge_width_value, DEFAULT_ROAD_EDGES_WIDTH, rel_tol=1e-5, abs_tol=1e-8)

      is_metric = self._params.get_bool("IsMetric") if custom_path_width or custom_lane_line_width or custom_road_edge_width else False
      if custom_path_width:
        path_width = self._path_width_to_half_m(path_width_value, is_metric)
      if custom_lane_line_width:
        lane_line_width = self._small_distance_to_half_m(lane_line_width_value, is_metric)
      if custom_road_edge_width:
        road_edge_width = self._small_distance_to_half_m(road_edge_width_value, is_metric)

    if model_ui_enabled and self._params.get_bool("DynamicPathWidth", default=False):
      if ui_state.status == UIStatus.ENGAGED:
        path_width *= 1.0
      elif ui_state.always_on_lateral_active:
        path_width *= 0.75
      else:
        path_width *= 0.50

    max_distance = np.clip(path_x_array[-1], MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE)
    max_idx = self._get_path_length_idx(self._lane_lines[0].raw_points[:, 0], max_distance)

    line_widths = [0.12, 0.16, 0.16, 0.16] if lane_line_width is None else [lane_line_width] * 4
    widths = [width * probability for width, probability in zip(line_widths, self._lane_line_probs, strict=True)]
    widths.extend([0.16 if road_edge_width is None else road_edge_width] * len(self._road_edges))
    lines = [*self._lane_lines, *self._road_edges]
    polygons = self._map_lines_to_polygons([line.raw_points for line in lines], widths, max_idx)
    for line, polygon in zip(lines, polygons, strict=True):
      line.projected_points = polygon

    # Update path using raw points
    if lead and lead.status:
      lead_d = lead.dRel * 2.0
      max_distance = np.clip(lead_d - min(lead_d * 0.35, 10.0), 0.0, max_distance)

    soon_acceleration = self._acceleration_x[len(self._acceleration_x) // 4] if len(self._acceleration_x) > 0 else 0
    self._acceleration_x_filter.update(soon_acceleration)
    self._acceleration_x_filter2.update(soon_acceleration)

    # make path width wider/thinner when initially braking/accelerating
    if self._experimental_mode and False:
      high_pass_acceleration = self._acceleration_x_filter.x - self._acceleration_x_filter2.x
      y_off = np.interp(high_pass_acceleration, [-1, 0, 1], [0.9 * 2, 0.9, 0.9 / 2])
    else:
      y_off = path_width

    max_idx = self._get_path_length_idx(path_x_array, max_distance)
    self._path.projected_points = self._map_line_to_polygon(
      self._path.raw_points, y_off, self._path_offset_z, max_idx, allow_invert=False
    )

    self._update_experimental_gradient()

  def _update_experimental_gradient(self):
    """Pre-calculate experimental mode gradient colors"""
    use_rainbow = self._params.get_bool("RainbowPath", default=False)
    if use_rainbow:
      self._exp_gradient = self._rainbow_path.get_gradient(0.0, 1.0)
      return

    if not self._experimental_mode or not self._params.get_bool("AccelerationPath", default=True):
      return

    max_len = min(len(self._path.projected_points) // 2, len(self._acceleration_x))
    segment_colors = []
    gradient_stops = []

    i = 0
    while i < max_len:
      # Some points (screen space) are out of frame (rect space)
      track_y = self._path.projected_points[i][1]
      if track_y < self._rect.y or track_y > (self._rect.y + self._rect.height):
        i += 1
        continue

      # Calculate color based on acceleration (0 is bottom, 1 is top)
      lin_grad_point = 1 - (track_y - self._rect.y) / self._rect.height

      # speed up: 120, slow down: 0
      path_hue = np.clip(60 + self._acceleration_x[i] * 35, 0, 120)

      saturation = min(abs(self._acceleration_x[i] * 1.5), 1)
      lightness = np.interp(saturation, [0.0, 1.0], [0.95, 0.62])
      alpha = np.interp(lin_grad_point, [0.75 / 2.0, 0.75], [0.4, 0.0])

      # Use HSL to RGB conversion
      color = self._hsla_to_color(path_hue / 360.0, saturation, lightness, alpha)

      gradient_stops.append(lin_grad_point)
      segment_colors.append(color)

      # Skip a point, unless next is last
      i += 1 + (1 if (i + 2) < max_len else 0)

    # Store the gradient in the path object
    self._exp_gradient.colors = segment_colors
    self._exp_gradient.stops = gradient_stops
    self._exp_gradient.start = (0.0, 1.0)
    self._exp_gradient.end = (0.0, 0.0)

  def _get_visible_gradient_bounds(self) -> tuple[float, float]:
    if self._path.projected_points.size == 0:
      return 1.0, 0.0

    polygon_y = self._path.projected_points[:, 1]
    visible_track_y = polygon_y[(polygon_y >= self._rect.y) & (polygon_y <= (self._rect.y + self._rect.height))]

    if visible_track_y.size == 0:
      return 1.0, 0.0

    gradient_bottom = np.clip((float(np.max(visible_track_y)) - self._rect.y) / self._rect.height, 0.0, 1.0)
    gradient_top = np.clip((float(np.min(visible_track_y)) - self._rect.y) / self._rect.height, 0.0, 1.0)
    return float(gradient_bottom), float(gradient_top)

  def _update_lead_vehicle(self, d_rel, v_rel, point, rect, scale: float = 1.0, top=None, was_flipped: bool = False,
                           force_flip: bool | None = None):
    """Marker under the lead (tip up at its bottom edge). When it and its speed label would not fit above the bottom
    of the view (a close lead) and the lead's roof point `top` is known, the marker flips: tip down on the roof."""
    speed_buff, lead_buff = 10.0, 40.0

    # Calculate fill alpha
    fill_alpha = 0
    if d_rel < lead_buff:
      fill_alpha = 255 * (1.0 - (d_rel / lead_buff))
      if v_rel < 0:
        fill_alpha += 255 * (-1 * (v_rel / speed_buff))
      fill_alpha = min(fill_alpha, 255)

    # Calculate size and position
    sz = np.clip((25 * 30) / (d_rel / 3 + 30), 15.0, 30.0) * scale
    g_xo = sz / 5
    g_yo = sz / 10

    # flip when the upright marker plus the label under it would not fit above the bottom of the view
    bottom_room = sz + LEAD_LABEL_ROOM + (sz * FLIPPED_LEAD_UNFLIP_SZ if was_flipped else 0.0)
    flip = top is not None and (point is None or point[1] > rect.height - bottom_room)
    if force_flip is not None and (top if force_flip else point) is not None:
      flip = force_flip  # hold the current form (stop-and-go), when that form can be drawn
    if flip:
      x = np.clip(top[0], 0.0, rect.width - sz / 2)
      y = min(max(top[1], sz + LEAD_LABEL_ROOM), rect.height - sz * 0.6)
      # tip down; points listed in reverse so the fan keeps the winding of the upright marker
      glow = [(x - (sz * 1.35) - g_xo, y - sz - g_yo), (x, y + g_yo), (x + (sz * 1.35) + g_xo, y - sz - g_yo)]
      chevron = [(x - (sz * 1.25), y - sz), (x, y), (x + (sz * 1.25), y - sz)]
      return LeadVehicle(glow=glow, chevron=chevron, fill_alpha=int(fill_alpha), flipped=True)

    if point is None:
      return LeadVehicle()
    x = np.clip(point[0], 0.0, rect.width - sz / 2)
    y = min(point[1], rect.height - sz * 0.6)

    glow = [(x + (sz * 1.35) + g_xo, y + sz + g_yo), (x, y - g_yo), (x - (sz * 1.35) - g_xo, y + sz + g_yo)]
    chevron = [(x + (sz * 1.25), y + sz), (x, y), (x - (sz * 1.25), y + sz)]

    return LeadVehicle(glow=glow, chevron=chevron, fill_alpha=int(fill_alpha))

  def _lane_centering_direction(self) -> int:
    toggles = ui_state.starpilot_toggles
    sm = ui_state.sm
    if (sm.recv_frame.get("modelV2", 0) < ui_state.started_frame or
        sm.recv_frame.get("carState", 0) < ui_state.started_frame):
      return 0

    car_state = sm["carState"]
    applied_correction = None
    if sm.recv_frame.get("controlsState", 0) >= ui_state.started_frame:
      try:
        applied_correction = sm["controlsState"].desiredCurvature - sm["modelV2"].action.desiredCurvature
      except (AttributeError, TypeError, ValueError):
        pass
    return get_lane_centering_visual_direction(
      sm["modelV2"], car_state.vEgo,
      toggles.get("lane_center_offset", 0.0),
      toggles.get("lane_centering_e2e_authority", 1.0),
      bool(toggles.get("lane_centering", False)),
      ui_state.status == UIStatus.ENGAGED or ui_state.always_on_lateral_active,
      bool(toggles.get("lane_centering_pause_on_signal", True)),
      bool(car_state.leftBlinker or car_state.rightBlinker),
      applied_correction,
    )

  def _lane_line_palette(self) -> tuple[bool, rl.Color, rl.Color, int]:
    stock_scheme = is_stock_color_scheme(self._params)
    line_status = UIStatus.ENGAGED if ui_state.status == UIStatus.DISENGAGED and ui_state.always_on_lateral_active else ui_state.status

    edge_color = get_param_color(self._params, "PathEdgesColor", 255)
    if edge_color is None:
      edge_color = (LANE_LINE_COLORS.get(line_status, LANE_LINE_COLORS[UIStatus.DISENGAGED]) if stock_scheme
                    else get_theme_color("PathEdge", rl.Color(0, 255, 64, 255)))

    lane_color = get_param_color(self._params, "LaneLinesColor", STOCK_LANE_LINES_COLOR.a)
    if lane_color is None:
      lane_color = STOCK_LANE_LINES_COLOR if stock_scheme else get_theme_color("LaneLines", STOCK_LANE_LINES_COLOR)

    lane_centering_direction = self._lane_centering_direction()
    return stock_scheme, edge_color, lane_color, lane_centering_direction

  def _get_ll_color(self, prob: float, adjacent: bool, left: bool, stock_scheme: bool,
                    edge_color: rl.Color, lane_color: rl.Color, lane_centering_direction: int = 0):
    alpha = np.clip(prob, 0.0, 0.7)
    lane_centering_line = adjacent and ((lane_centering_direction > 0 and not left) or
                                        (lane_centering_direction < 0 and left))
    if lane_centering_line:
      color = rl.Color(OCEAN_BLUE_LANE_LINES_COLOR.r, OCEAN_BLUE_LANE_LINES_COLOR.g,
                       OCEAN_BLUE_LANE_LINES_COLOR.b, int(alpha * OCEAN_BLUE_LANE_LINES_COLOR.a))
    elif adjacent:
      color = rl.Color(edge_color.r, edge_color.g, edge_color.b, int(alpha * edge_color.a))

      # turn adjacent lls orange if torque is high
      torque = self._torque_filter.x
      high_torque = abs(torque) > 0.6
      if high_torque and (left == (torque > 0)):
        color = blend_colors(
          color,
          rl.Color(255, 115, 0, int(alpha * 255)),  # orange
          np.interp(abs(torque), [0.6, 0.8], [0.0, 1.0])
        )
    else:
      color = rl.Color(lane_color.r, lane_color.g, lane_color.b, int(alpha * lane_color.a))

    if stock_scheme and ui_state.status == UIStatus.DISENGAGED and not ui_state.always_on_lateral_active:
      color = rl.Color(0, 0, 0, int(alpha * 255))

    return color

  def _draw_lane_lines(self):
    """Draw lane lines and road edges"""
    """Two closest lines should be green (lane line or road edges)"""
    stock_scheme, edge_color, lane_color, lane_centering_direction = self._lane_line_palette()
    for i, lane_line in enumerate(self._lane_lines):
      if lane_line.projected_points.size == 0:
        continue

      color = self._get_ll_color(float(self._lane_line_probs[i]), i in (1, 2), i in (0, 1),
                                 stock_scheme, edge_color, lane_color, lane_centering_direction)
      draw_polygon(self._rect, lane_line.projected_points, color)

    for i, road_edge in enumerate(self._road_edges):
      if road_edge.projected_points.size == 0:
        continue

      # if closest lane lines are not confident, make road edges green
      color = self._get_ll_color(float(1.0 - self._road_edge_stds[i]), float(self._lane_line_probs[i + 1]) < 0.25, i == 0,
                                 stock_scheme, edge_color, lane_color)
      draw_polygon(self._rect, road_edge.projected_points, color)

  def _draw_path(self, sm):
    """Draw path with dynamic coloring based on mode and throttle state."""
    if not self._path.projected_points.size:
      return

    lateral_ui_active = ui_state.status == UIStatus.ENGAGED or ui_state.always_on_lateral_active
    allow_throttle = sm['longitudinalPlan'].allowThrottle or not self._longitudinal_control or ui_state.always_on_lateral_active
    self._blend_filter.update(int(allow_throttle))
    use_rainbow = self._params.get_bool("RainbowPath", default=False)
    use_accel_path = not use_rainbow and self._params.get_bool("AccelerationPath", default=True)

    if use_rainbow:
      if len(self._exp_gradient.colors) > 1:
        draw_polygon(self._rect, self._path.projected_points, gradient=self._exp_gradient)
      else:
        fallback = get_border_color(ui_state)
        draw_polygon(self._rect, self._path.projected_points, rl.Color(fallback.r, fallback.g, fallback.b, 90))
    elif use_accel_path:
      if self._experimental_mode:
        if len(self._exp_gradient.colors) > 1:
          draw_polygon(self._rect, self._path.projected_points, gradient=self._exp_gradient)
        else:
          fallback = get_border_color(ui_state)
          draw_polygon(self._rect, self._path.projected_points, rl.Color(fallback.r, fallback.g, fallback.b, 90))
      else:
        blend_factor = round(self._blend_filter.x * 100) / 100
        blended_colors = self._blend_colors(NO_THROTTLE_COLORS, THROTTLE_COLORS, blend_factor)
        if lateral_ui_active and blend_factor < 1.0:
          blended_colors = self._blend_colors(blended_colors, THROTTLE_COLORS, 0.65)
        self._path_gradient.colors = blended_colors
        if ui_state.status == UIStatus.DISENGAGED and not ui_state.always_on_lateral_active:
          draw_polygon(self._rect, self._path.projected_points, rl.Color(0, 0, 0, 90))
        else:
          draw_polygon(self._rect, self._path.projected_points, gradient=self._path_gradient)
    else:
      path_color = get_visual_color(self._params, "PathColor", "Path", rl.Color(48, 255, 156, 255))
      self._path_gradient.colors = [
        with_alpha(path_color, path_color.a),
        with_alpha(path_color, int(path_color.a * 0.55)),
        with_alpha(path_color, int(path_color.a * 0.10)),
      ]
      draw_polygon(self._rect, self._path.projected_points, gradient=self._path_gradient)

  def _draw_lead_indicator(self, radar_state):
    # Draw lead vehicles if available
    lead_color = get_theme_color("LeadMarker", rl.Color(201, 34, 49, 255))
    for lead in self._lead_vehicles:
      if not lead.glow or not lead.chevron:
        continue

      rl.draw_triangle_fan(lead.glow, len(lead.glow), rl.Color(218, 202, 37, 255))
      rl.draw_triangle_fan(lead.chevron, len(lead.chevron), with_alpha(lead_color, lead.fill_alpha))

    lead_one = radar_state.leadOne
    if show_top_lead_info(self._lead_info_mode, getattr(self, "_multi_lead_ui", False)) and lead_one and lead_one.status:
      self._draw_lead_info(lead_one)

  @staticmethod
  def _format_lead_distance(lead_distance: float, is_metric: bool, use_si_metrics: bool) -> str:
    lead_distance = max(float(lead_distance), 0.0)
    if is_metric or use_si_metrics:
      return f"{round(lead_distance)} m"
    return f"{round(lead_distance * CV.METER_TO_FOOT)} ft"

  @staticmethod
  def _format_lead_speed(lead_speed: float, is_metric: bool, use_si_metrics: bool) -> str:
    lead_speed = max(float(lead_speed), 0.0)
    if use_si_metrics:
      return f"{round(lead_speed)} m/s"
    if is_metric:
      return f"{round(lead_speed * CV.MS_TO_KPH)} km/h"
    return f"{round(lead_speed * CV.MS_TO_MPH)} mph"

  def _format_lead_info(self, lead_data, is_metric: bool, use_si_metrics: bool) -> str:
    if self._lead_info_mode == LeadInfoMode.DISTANCE:
      return self._format_lead_distance(getattr(lead_data, "dRel", 0.0), is_metric, use_si_metrics)
    return self._format_lead_speed(getattr(lead_data, "vLead", 0.0), is_metric, use_si_metrics)

  def _draw_lead_info(self, lead_data) -> None:
    from openpilot.selfdrive.ui.onroad.starpilot.path import _draw_text_with_outline

    use_si_metrics = ui_state.starpilot_toggles.get("UseSiMetrics", False)
    text = self._format_lead_info(lead_data, ui_state.is_metric, use_si_metrics)
    font = gui_app.font(FontWeight.SEMI_BOLD)
    font_size = 40
    text_size = measure_text_cached(font, text, font_size)
    center_x = self._rect.x + self._rect.width / 2
    x = center_x - text_size.x / 2
    y = self._rect.y + 22
    _draw_text_with_outline(text, float(x), float(y), font, font_size)

  @staticmethod
  def _get_path_length_idx(pos_x_array: np.ndarray, path_distance: float) -> int:
    """Get the index corresponding to the given path height"""
    if len(pos_x_array) == 0:
      return 0
    idx = np.searchsorted(pos_x_array, path_distance, side='right') - 1
    return idx if idx >= 0 else 0

  def _map_to_screen(self, in_x, in_y, in_z):
    """Project a point in car space to screen space"""
    input_pt = np.array([in_x, in_y, in_z])
    pt = self._car_space_transform @ input_pt

    if abs(pt[2]) < 1e-6:
      return None

    x, y = pt[0] / pt[2], pt[1] / pt[2]

    clip = self._clip_region
    if not (clip.x <= x <= clip.x + clip.width and clip.y <= y <= clip.y + clip.height):
      return None

    return (x, y)

  def _map_line_to_polygon(self, line: np.ndarray, y_off: float, z_off: float, max_idx: int, allow_invert: bool = True) -> np.ndarray:
    """Convert 3D line to 2D polygon for rendering."""
    if line.shape[0] == 0:
      return np.empty((0, 2), dtype=np.float32)

    points = line[:max_idx + 1]
    n = len(points)
    if n == 0:
      return np.empty((0, 2), dtype=np.float32)

    offsets = np.array([[0, -y_off, z_off], [0, y_off, z_off]], dtype=np.float32)
    proj, valid = self._project_points(points, offsets[:, None, :])

    screen = proj[:2, :, valid]
    if not allow_invert:
      keep = screen[1, 0] == np.minimum.accumulate(screen[1, 0])
      screen = screen[:, :, keep]

    return np.concatenate((screen[:, 0].T, screen[:, 1, ::-1].T)).astype(np.float32, copy=False)

  def _map_lines_to_polygons(self, lines: list[np.ndarray], y_offsets: list[float], max_idx: int) -> list[np.ndarray]:
    points = [line[:max_idx + 1] for line in lines]
    counts = [len(line) for line in points]
    total = sum(counts)
    if total == 0:
      return [np.empty((0, 2), dtype=np.float32) for _ in lines]

    offsets = np.zeros((2, total, 3), dtype=np.float32)
    offsets[1, :, 1] = np.repeat(y_offsets, counts)
    offsets[0, :, 1] = -offsets[1, :, 1]
    proj, valid = self._project_points(np.concatenate(points), offsets)

    polygons = []
    start = 0
    for count in counts:
      end = start + count
      screen = proj[:2, :, start:end][:, :, valid[start:end]]
      polygons.append(np.concatenate((screen[:, 0].T, screen[:, 1, ::-1].T)).astype(np.float32, copy=False))
      start = end
    return polygons

  def _project_points(self, points: np.ndarray, offsets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(points)
    points_3d = points[None, :, :] + offsets
    proj = (self._car_space_transform @ points_3d.reshape(2 * n, 3).T).reshape(3, 2, n)

    valid = (points[:, 0] >= 0) & (np.abs(proj[2, 0]) >= 1e-6) & (np.abs(proj[2, 1]) >= 1e-6)
    np.divide(proj[:2], proj[2], out=proj[:2], where=valid)

    clip = self._clip_region
    x_min, x_max = clip.x, clip.x + clip.width
    y_min, y_max = clip.y, clip.y + clip.height
    for side in (0, 1):
      valid &= ((proj[0, side] >= x_min) & (proj[0, side] <= x_max) &
                (proj[1, side] >= y_min) & (proj[1, side] <= y_max))
    return proj, valid

  @staticmethod
  def _hsla_to_color(h, s, l, a):
    rgb = colorsys.hls_to_rgb(h, l, s)
    return rl.Color(
      int(rgb[0] * 255),
      int(rgb[1] * 255),
      int(rgb[2] * 255),
      int(a * 255)
    )

  @staticmethod
  def _blend_colors(begin_colors, end_colors, t):
    if t >= 1.0:
      return end_colors
    if t <= 0.0:
      return begin_colors

    inv_t = 1.0 - t
    return [rl.Color(
      int(inv_t * start.r + t * end.r),
      int(inv_t * start.g + t * end.g),
      int(inv_t * start.b + t * end.b),
      int(inv_t * start.a + t * end.a)
    ) for start, end in zip(begin_colors, end_colors, strict=True)]

  @staticmethod
  def _small_distance_to_half_m(value: float, is_metric: bool) -> float:
    if value <= 0:
      return 0.0
    if is_metric:
      return value / 200.0
    return value * (CV.INCH_TO_CM / 100.0) / 2.0

  @staticmethod
  def _path_width_to_half_m(value: float, is_metric: bool) -> float:
    if value <= 0:
      return 0.0
    if is_metric:
      return value / 2.0
    return value * CV.FOOT_TO_METER / 2.0
