"""The car screen's Navigation page.

The comma's settings page (StarPilotNavigationLayout) does search, favorites and
starting a route. The car adds route alternatives from Mapbox, a map preview
beside the list on wide screens, a callback once a route starts, and predictive
search: results follow the text as it is typed (set_live_query), a short pause
after the last key. Suggestions share one Mapbox Search Box session until a
place is picked, which is how Mapbox bills them.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from typing import Any

import pyray as rl

from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import (
  AetherListColors,
  draw_empty_state_card,
  draw_section_header,
  draw_selection_list_row,
  with_alpha,
)
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.navigation import (
  NAV_EMPTY_HEIGHT,
  NAV_GAP,
  NAV_INSET,
  NAV_SECTION_HEIGHT,
  PANEL_STYLE,
  MapboxSearchClient,
  MapboxSearchError,
  NavigationManagerView,
  SearchResult,
  StarPilotNavigationLayout,
)
from openpilot.starpilot.system.starpilot_auto.ui.nav_map import NavMapView
from openpilot.selfdrive.ui.onroad.starpilot.navigation_card import _format_distance
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.starpilot.navigation.route_engine import Coordinate, MapboxRouteEngine, NavigationRoute
from openpilot.system.ui.lib.multilang import tr

NAV_ROUTE_ROW_HEIGHT = 104.0
NAV_MAP_MIN_WIDTH = 1100.0  # below this the page is list-only
NAV_MAP_FRACTION = 0.5
SEARCH_DEBOUNCE_SECONDS = 0.35  # after the last key, before asking Mapbox
MIN_SEARCH_CHARS = 3            # MapboxSearchClient.search needs this many
LIVE_RESULT_LIMIT = 6


class CarMapboxSearchClient(MapboxSearchClient):
  # Geocoding v6 honours the type filter; the Search Box reverse endpoint answers with street addresses.
  REVERSE_URL = "https://api.mapbox.com/search/geocode/v6/reverse"

  def reverse(self, latitude: float, longitude: float, public_token: str, language: str = "") -> str:
    """The city at a point, e.g. "Las Vegas", or "" when unknown. Never a street address."""
    if not public_token:
      return ""
    params: dict[str, Any] = {
      "access_token": public_token,
      "latitude": latitude,
      "longitude": longitude,
      "types": "place",
      "limit": 1,
    }
    if language.strip():
      params["language"] = language.strip()
    try:
      payload = self._get_json(self.REVERSE_URL, params)
    except MapboxSearchError:
      return ""
    features = payload.get("features") or []
    if not isinstance(features, list) or not features or not isinstance(features[0], dict):
      return ""
    result = self._normalize_result(features[0])
    return result.name if result is not None else ""


class LiveSearchClient(MapboxSearchClient):
  """Predictive search lists a few more suggestions than the comma's search page."""

  def search(self, query: str, public_token: str, session_token: str, *, proximity: tuple[float, float] | None = None,
             language: str = "", limit: int = LIVE_RESULT_LIMIT) -> list[SearchResult]:
    return super().search(query, public_token, session_token, proximity=proximity, language=language, limit=limit)


class CarNavigationLayout(StarPilotNavigationLayout):
  """``on_started`` runs after a route starts. Offline maps have their own page (offline_maps.py)."""

  def __init__(self, on_started=None):
    super().__init__()
    self._on_started = on_started
    self._search_client = LiveSearchClient()
    from openpilot.starpilot.navigation.mapbox_usage import shared_usage
    self._route_engine = MapboxRouteEngine(usage=shared_usage())
    self._map = NavMapView(show_guidance=True)
    self._route_pending: queue.Queue = queue.Queue()
    self._route_generation = 0
    self._preview_routes: list[NavigationRoute] = []
    self._preview_route_index = 0
    self._routes_loading = False
    self._routes_error = ""
    self._live_query = ""
    self._search_due: float | None = None

  def show_event(self):
    self._clear_route_preview()
    self._live_query = ""
    self._search_due = None
    super().show_event()
    self._map.show_event()

  # ── predictive search ─────────────────────────────────────────────────────

  def set_live_query(self, text: str, now: float | None = None, immediate: bool = False) -> None:
    """The search field's text as the driver types. The search runs SEARCH_DEBOUNCE_SECONDS after
    the last change (at once with ``immediate``); earlier results stay listed until new ones arrive."""
    now = time.monotonic() if now is None else now
    if text != self._live_query:
      self._live_query = text
      self._search_due = now if immediate else now + SEARCH_DEBOUNCE_SECONDS
    elif immediate and self._search_due is not None:
      self._search_due = now

  def _run_due_search(self, now: float) -> None:
    if self._search_due is None or now < self._search_due:
      return
    self._search_due = None
    query = self._live_query.strip()
    if query == self._query and (self._search_results or self._search_loading or self._search_error):
      return
    if self._draft_destination is not None:
      self._clear_route_preview()
    if len(query) < MIN_SEARCH_CHARS:
      # Too short for Mapbox: drop the old results quietly; the car lists matching saved places.
      self._search_generation += 1
      self._query, self._search_results, self._search_loading, self._search_error = query, [], False, ""
      self._draft_destination = self._selected_favorite = None
      return
    shown = self._search_results
    self._start_search(query)
    if self._search_loading:
      self._search_results = shown  # no blank list between keystrokes

  def hide_event(self):
    self._route_generation += 1
    super().hide_event()
    self._map.hide_event()

  def _update_state(self):
    self._consume_route_results()
    self._run_due_search(time.monotonic())
    super()._update_state()

  def _consume_route_results(self):
    while True:
      try:
        generation, payload = self._route_pending.get_nowait()
      except queue.Empty:
        return
      if generation != self._route_generation:
        continue
      self._routes_loading = False
      if isinstance(payload, Exception) or not payload:
        self._routes_error = tr("No route found. Check your connection and try again.")
      else:
        self._preview_routes = payload
        self._preview_route_index = 0
        self._routes_error = ""
      self._update_map_preview()

  def _select_destination(self, payload: dict[str, Any], favorite: dict[str, Any] | None = None):
    super()._select_destination(payload, favorite)
    # A place was picked: the Search Box session ends, and the next search starts a new one.
    self._session_token = str(uuid.uuid4())
    if self._draft_destination is not None:
      self._fetch_route_preview(self._draft_destination)

  def _clear_route_preview(self):
    self._route_generation += 1
    self._preview_routes = []
    self._preview_route_index = 0
    self._routes_loading = False
    self._routes_error = ""
    self._map.clear_preview()

  def _update_map_preview(self):
    if self._draft_destination is None:
      self._map.clear_preview()
      return
    destination = (float(self._draft_destination["latitude"]), float(self._draft_destination["longitude"]))
    routes = [[(point.latitude, point.longitude) for point in route.geometry] for route in self._preview_routes]
    self._map.set_preview(routes, self._preview_route_index, destination)

  def _fetch_route_preview(self, destination: dict[str, Any]):
    self._clear_route_preview()
    self._update_map_preview()
    position = self._last_position()
    token = str(self._params.get("MapboxSecretKey", encoding="utf-8") or "").strip()
    if position is None or not token:
      return
    generation = self._route_generation
    self._routes_loading = True
    start = Coordinate(position[1], position[0])
    target = dict(destination)

    def worker():
      try:
        routes = self._route_engine.fetch_routes(token, start, target, alternatives=True)
        self._route_pending.put((generation, routes[:3]))
      except Exception as error:
        self._route_pending.put((generation, error))

    threading.Thread(target=worker, daemon=True, name="navigation-route-preview").start()

  def _start_navigation(self):
    if self._draft_destination is not None and self._preview_routes:
      self._draft_destination["routeId"] = "main" if self._preview_route_index == 0 else f"alt-{self._preview_route_index}"
    had_draft = self._draft_destination is not None
    super()._start_navigation()
    if had_draft and self._draft_destination is None:  # the route was accepted
      self._clear_route_preview()
      if self._on_started is not None:
        self._on_started()

  def _cancel_navigation(self):
    super()._cancel_navigation()
    self._clear_route_preview()

  def _activate_navigation_target(self, target_id: str | None):
    if target_id and target_id.startswith("route:"):
      try:
        index = int(target_id.split(":", 1)[1])
      except ValueError:
        return
      if 0 <= index < len(self._preview_routes):
        self._preview_route_index = index
        self._update_map_preview()
      return
    super()._activate_navigation_target(target_id)

  def _draw_summary_row(self, rect: rl.Rectangle, manager: NavigationManagerView) -> None:
    if self._draft_destination is None or not self._preview_routes:
      return super()._draw_summary_row(rect, manager)

    route = self._preview_routes[self._preview_route_index]
    title = f"{self._duration_text(route.total_duration)}  •  {_format_distance(route.total_distance, ui_state.is_metric)}"
    subtitle = str(self._draft_destination.get("place_name") or self._draft_destination.get("name") or "")
    enabled = self._routing_available()
    action_width = 260
    action_rect = rl.Rectangle(rect.x + rect.width - action_width, rect.y, action_width, rect.height)
    hovered, pressed = manager._interactive_state("action:start", action_rect, pad_y=4)
    draw_selection_list_row(
      rect,
      title=title,
      subtitle=subtitle,
      action_text=tr("Start") if enabled else tr("Unavailable"),
      current=False,
      hovered=hovered,
      pressed=pressed,
      action_width=action_width,
      action_pill=True,
      action_pill_height=64,
      action_pill_width=220,
      title_size=34,
      subtitle_size=24,
      action_text_size=24,
      action_fill=with_alpha(AetherListColors.SUCCESS, 38 if enabled else 10),
      action_border=with_alpha(AetherListColors.SUCCESS, 85 if enabled else 25),
      action_text_color=AetherListColors.HEADER if enabled else AetherListColors.MUTED,
      current_bg=AetherListColors.CURRENT_BG,
      current_border=AetherListColors.CURRENT_BORDER,
      row_separator=PANEL_STYLE.divider_color,
    )

  def _draw_action_buttons(self, x: float, y: float, width: float, manager: NavigationManagerView) -> float:
    # The route choices sit between the summary row and the action buttons.
    routes_height = self._draw_route_section(x, y, width, manager)
    action_height = super()._draw_action_buttons(x, y + routes_height, width, manager)
    if action_height > 0:
      return routes_height + action_height
    return max(0.0, routes_height - NAV_GAP)

  def _measure_navigation_content_height(self, content_width: float) -> float:
    height = super()._measure_navigation_content_height(content_width)
    if self._draft_destination is not None or self._active_destination is not None:
      height += self._route_section_height()
    if not self._search_results and not self._favorites and not self._recent_destinations and not self._search_loading and not self._search_error:
      height += NAV_GAP
    return height

  def _render(self, rect):
    if rect.width < NAV_MAP_MIN_WIDTH or self._manager_view is None:
      return super()._render(rect)
    map_width = rect.width * NAV_MAP_FRACTION
    list_rect = rl.Rectangle(rect.x, rect.y, rect.width - map_width, rect.height)
    map_rect = rl.Rectangle(rect.x + rect.width - map_width, rect.y + NAV_INSET, map_width - NAV_INSET, rect.height - NAV_INSET * 2)
    self._manager_view.render(list_rect)
    self._map.render(map_rect)

  @staticmethod
  def _duration_text(seconds: float) -> str:
    minutes = max(1, int(round(seconds / 60.0)))
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"

  def _route_rows(self) -> list[tuple[str, str, str]]:
    """(target id, title, subtitle) per previewed route."""
    rows = []
    fastest = min((route.total_duration for route in self._preview_routes), default=0.0)
    for index, route in enumerate(self._preview_routes):
      title = tr("Recommended route") if index == 0 else tr("Alternative {}").format(index)
      subtitle = f"{self._duration_text(route.total_duration)}  •  {_format_distance(route.total_distance, ui_state.is_metric)}"
      if index > 0 and route.total_duration > fastest + 30:
        subtitle += "  •  " + tr("+{} slower").format(self._duration_text(route.total_duration - fastest))
      rows.append((f"route:{index}", title, subtitle))
    return rows

  def _route_section_height(self) -> float:
    if self._draft_destination is None:
      return 0.0
    if self._routes_loading or self._routes_error:
      return NAV_EMPTY_HEIGHT + NAV_GAP
    if len(self._preview_routes) > 1:
      return NAV_SECTION_HEIGHT + len(self._preview_routes) * NAV_ROUTE_ROW_HEIGHT + NAV_GAP
    return 0.0

  def _draw_route_section(self, x: float, y: float, width: float, manager: NavigationManagerView) -> float:
    if self._draft_destination is None:
      return 0.0
    if self._routes_loading or self._routes_error:
      draw_empty_state_card(
        rl.Rectangle(x, y, width, NAV_EMPTY_HEIGHT),
        tr("Finding routes...") if self._routes_loading else tr("Route unavailable"),
        tr("Checking traffic with Mapbox") if self._routes_loading else self._routes_error,
        title_size=30,
        body_size=22,
        border=with_alpha(AetherListColors.WARNING if self._routes_error else PANEL_STYLE.surface_border, 45 if self._routes_error else 14),
        style=PANEL_STYLE,
      )
      return NAV_EMPTY_HEIGHT + NAV_GAP
    if len(self._preview_routes) <= 1:
      return 0.0
    draw_section_header(
      rl.Rectangle(x, y, width, NAV_SECTION_HEIGHT),
      tr("Routes"),
      trailing_text=str(len(self._preview_routes)),
      title_size=30,
      trailing_size=24,
      style=PANEL_STYLE,
    )
    row_y = y + NAV_SECTION_HEIGHT
    rows = self._route_rows()
    for index, (target_id, title, subtitle) in enumerate(rows):
      row_rect = rl.Rectangle(x, row_y, width, NAV_ROUTE_ROW_HEIGHT)
      hovered, pressed = manager._interactive_state(target_id, row_rect)
      selected = index == self._preview_route_index
      draw_selection_list_row(
        row_rect,
        title=title,
        subtitle=subtitle,
        action_text=tr("Selected") if selected else tr("Use"),
        current=selected,
        hovered=hovered,
        pressed=pressed,
        is_last=index == len(rows) - 1,
        action_width=190,
        action_pill=True,
        action_pill_height=58,
        action_pill_width=150,
        title_size=30,
        subtitle_size=22,
        action_text_size=23,
        current_bg=AetherListColors.CURRENT_BG,
        current_border=AetherListColors.CURRENT_BORDER,
        row_separator=PANEL_STYLE.divider_color,
      )
      row_y += NAV_ROUTE_ROW_HEIGHT
    return NAV_SECTION_HEIGHT + len(rows) * NAV_ROUTE_ROW_HEIGHT + NAV_GAP
