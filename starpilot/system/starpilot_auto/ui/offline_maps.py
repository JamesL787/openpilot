"""Offline Maps: both kinds of offline data in one place.

  * Map display: what the navigation map has saved. Save new areas, update or
    delete them. navtilesd does the downloading; this page only writes area
    records through OfflineMaps and reads the progress navtilesd reports.
  * Speed limit data: mapd's road data by state or country (the Map Data page,
    embedded as-is).
"""

from __future__ import annotations

import json
import math
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pyray as rl
from openpilot.starpilot.system.starpilot_auto.ui import settings_style as style

from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import (
  AETHER_LIST_METRICS,
  AetherListColors,
  AetherSegmentedControl,
  DEFAULT_PANEL_STYLE,
  PanelManagerView,
  draw_action_pill,
  draw_empty_state_card,
  draw_list_group_shell,
  draw_section_header,
  draw_selection_list_row,
  with_alpha,
)
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.navigation import SearchResult
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.panel import FrameCachedParams, _SettingsPage
from openpilot.starpilot.navigation.destination_store import NavigationDestinationStore
from openpilot.starpilot.navigation.map_tiles import LIGHT_STYLE
from openpilot.starpilot.navigation.offline_maps import OFFLINE_MAX_BYTES, OfflineMaps, area_zoom_for_radius, estimate_area, format_bytes
from openpilot.starpilot.system.starpilot_auto.ui.navigation import CarMapboxSearchClient
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.starpilot.system.starpilot_auto.ui.settings_dialogs import ConfirmDialog, MultiOptionDialog
from openpilot.system.ui.widgets.keyboard import Keyboard

PANEL_STYLE = DEFAULT_PANEL_STYLE
METRICS = replace(AETHER_LIST_METRICS, header_height=0)

INSET = 18.0
GAP = 14.0
STORAGE_HEIGHT = 190.0
SECTION_HEIGHT = 72.0
ROW_HEIGHT = 118.0
BUTTON_HEIGHT = 84.0
EMPTY_HEIGHT = 140.0
REFRESH_SECONDS = 2.0

THEME_LABELS = {"light": "Light", "dark": "Dark", "auto": "Light & dark (automatic)"}
STYLE_NAMES = {LIGHT_STYLE: "light"}  # any other style is the dark one
KEEP_QUESTION = "Keep the saved {} maps? Keeping them lets you switch back, or use light & dark, without downloading them again. " + \
                "Deleting frees the space."

SEGMENT_DISPLAY = 0
SEGMENT_ROAD_DATA = 1
SEGMENT_HEIGHT = 68.0
CAPTION_HEIGHT = 44.0
CAPTION_SIZE = 26
CAPTION_LINE = 34.0
STATUS_SIZE = 27
STATUS_LINE = 36.0
SEGMENT_CAPTIONS = (
  "The map on the comma and car screen. Saved areas keep it working without signal.",
  "Road data for speed limits and curve control, by state or country. Doesn't draw the map.",
)


def _road_data_layout():
  from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.maps import StarPilotMapsLayout
  return StarPilotMapsLayout()


class OfflineMapsManagerView(PanelManagerView):
  METRICS = METRICS
  PANEL_STYLE = PANEL_STYLE

  def __init__(self, controller: StarPilotOfflineMapsLayout):
    super().__init__()
    self._controller = controller

  def _draw_header(self, rect: rl.Rectangle):
    del rect

  def _measure_content_height(self, content_width: float) -> float:
    self._controller.row_width = max(1.0, content_width - INSET * 2)
    return INSET * 2 + sum(height for _, height, _ in self._controller.layout_rows())

  def _draw_scroll_content(self, scroll_rect: rl.Rectangle, content_width: float):
    self._controller.draw_rows(scroll_rect, content_width, self._scroll_offset, self)

  def _activate_target(self, target_id: str | None):
    if target_id:
      self._controller.activate(target_id)


class StarPilotOfflineMapsLayout(_SettingsPage):
  def __init__(self, offline: OfflineMaps | None = None, params=None, road_data_factory: Callable[[], Any] | None = None):
    super().__init__()
    self._params = params or FrameCachedParams()
    self._store = NavigationDestinationStore(self._params)
    self._offline = offline or OfflineMaps()
    self._search_client = CarMapboxSearchClient()
    self._keyboard: Keyboard | None = None
    self._pending: queue.Queue[tuple[str, int, Any]] = queue.Queue()
    self._generation = 0
    self._session_token = str(uuid.uuid4())

    self.summary: dict[str, Any] = {}
    self.showing_light = False
    self.areas: list = []
    self.selected_area_id: str | None = None
    # The area being set up: {"latitude", "longitude", "name", "radius_km", "zoom" (None = auto), "estimate"}
    self.chooser: dict[str, Any] | None = None
    self._editor = None  # built on first use: its map loads fonts and tiles
    self.search_results: list[SearchResult] = []
    self.search_busy = False
    self.message = ""
    self._refreshed = -1.0
    self._manager_view = OfflineMapsManagerView(self)

    self.segment = SEGMENT_DISPLAY
    self._road_data_factory = road_data_factory or _road_data_layout
    self._road_data = None  # built on first use: it subscribes to mapd
    self._segments: AetherSegmentedControl | None = None
    self._shown = False

  # ── segments ──────────────────────────────────────────────────────────────

  @property
  def road_data(self):
    if self._road_data is None:
      self._road_data = self._road_data_factory()
    return self._road_data

  def _segment_view(self, segment: int):
    return self.road_data if segment == SEGMENT_ROAD_DATA else self._manager_view

  def open_segment(self, segment: int) -> None:
    segment = SEGMENT_ROAD_DATA if segment == SEGMENT_ROAD_DATA else SEGMENT_DISPLAY
    if segment == self.segment:
      return
    if self._shown:
      self._segment_view(self.segment).hide_event()
    self.segment = segment
    if self._shown:
      self._segment_view(segment).show_event()

  def _render(self, rect: rl.Rectangle):
    if self._segments is None:
      self._segments = AetherSegmentedControl([tr("Map display"), tr("Speed limit data")], lambda: self.segment, self.open_segment,
                                              style=PANEL_STYLE, suppress_background=True)
    self._segments.render(rl.Rectangle(rect.x + INSET, rect.y, rect.width - INSET * 2, SEGMENT_HEIGHT))
    # The caption wraps rather than being cut off; the page below moves down to make room.
    caption_y = rect.y + SEGMENT_HEIGHT + 8
    caption_w = rect.width - INSET * 2 - 8
    editing = self.chooser is not None and self.segment == SEGMENT_DISPLAY  # the editor needs the room
    captions = [] if editing else style.lines(tr(SEGMENT_CAPTIONS[self.segment]), caption_w, CAPTION_SIZE)
    for index, line in enumerate(captions):
      style.text(rl.Rectangle(rect.x + INSET + 4, caption_y + 5 + index * CAPTION_LINE, caption_w, CAPTION_LINE), line, CAPTION_SIZE, style.MUTED)
    top = SEGMENT_HEIGHT + 8 + (max(CAPTION_HEIGHT, len(captions) * CAPTION_LINE + 10) if captions else 4)
    body = rl.Rectangle(rect.x, rect.y + top, rect.width, max(1.0, rect.height - top))
    if self.chooser is not None and self.segment == SEGMENT_DISPLAY:
      if self._editor is None:
        from openpilot.starpilot.system.starpilot_auto.ui.offline_area_editor import AreaEditor
        self._editor = AreaEditor(self)
      self._editor.render(body)
    else:
      self._segment_view(self.segment).render(body)

  def hide_event(self):
    self._shown = False
    if self.segment == SEGMENT_ROAD_DATA:
      self.road_data.hide_event()
    super().hide_event()

  def show_event(self):
    # The segment survives a re-show (dialogs hide and re-show the page); deep links pick one with open_segment.
    self._shown = True
    if self.segment == SEGMENT_ROAD_DATA:
      self.road_data.show_event()
    self._generation += 1
    self._session_token = str(uuid.uuid4())
    self.chooser = None
    self.search_results = []
    self.search_busy = False
    self.message = ""
    self.selected_area_id = None
    self.refresh()
    super().show_event()

  def _update_state(self):
    self._consume_pending()
    if self._refreshed < 0 or time.monotonic() - self._refreshed >= REFRESH_SECONDS:
      self.refresh()

  def refresh(self) -> None:
    self._refreshed = time.monotonic()
    self.summary = self._offline.summary()
    self.showing_light = self.summary.get("map_theme") == "auto" and self._offline.display_style() == LIGHT_STYLE
    self.areas = self._offline.areas(include_deleted=True)
    if self.selected_area_id is not None and not any(a.id == self.selected_area_id and not a.deleted for a in self.areas):
      self.selected_area_id = None

  # ── state helpers ─────────────────────────────────────────────────────────

  @property
  def used_bytes(self) -> int:
    return int(self.summary.get("offline_bytes") or 0)

  def _progress(self, area_id: str) -> dict[str, Any]:
    return next((item for item in self.summary.get("items") or [] if item.get("id") == area_id), {})

  def connection_text(self) -> tuple[str, rl.Color]:
    if not self.summary.get("service_running"):
      return tr("Map service not running • downloads resume when it starts"), AetherListColors.WARNING
    if self.summary.get("offline"):
      return tr("No connection • the map uses what's saved"), AetherListColors.WARNING
    if self.summary.get("unmetered"):
      return tr("On Wi-Fi • downloads run now"), AetherListColors.SUCCESS
    return tr("Not on Wi-Fi • downloads wait for Wi-Fi"), AetherListColors.MUTED

  def area_title(self, area) -> str:
    return tr("Route to {}").format(area.name) if area.kind == "route" else area.name

  def area_status(self, area) -> str:
    if area.deleted:
      return tr("Removing…")
    state = self._progress(area.id)
    kind = state.get("state") or "queued"
    total, done = int(state.get("total") or 0), int(state.get("done") or 0)
    percent = f"{100 * done // total}%" if total else "0%"
    if kind == "complete":
      return tr("Saved • {} • updated {}").format(format_bytes(state.get("bytes") or 0), self._age_text(float(state.get("completed_at") or 0.0)))
    if kind == "downloading":
      return tr("Downloading {} • {} of {} tiles").format(percent, f"{done:,}", f"{total:,}")
    if kind == "waiting_wifi":
      if state.get("metered_wifi"):
        return tr("This Wi-Fi is marked metered • tap, then Download now")
      return tr("Waiting for Wi-Fi • {} done").format(percent)
    if kind == "incomplete":
      return tr("Partly saved • retrying later")
    if kind == "storage_full":
      return tr("Offline storage is full ({})").format(format_bytes(OFFLINE_MAX_BYTES))
    if kind == "no_space":
      return tr("Not enough free space on the device")
    return tr("Queued • downloads on Wi-Fi")

  @staticmethod
  def _age_text(timestamp: float) -> str:
    days = int(max(0.0, time.time() - timestamp) // 86400)  # noqa: TID251 - compared with a saved wall-clock time
    if days == 0:
      return tr("today")
    return tr("yesterday") if days == 1 else tr("{} days ago").format(days)

  def route_text(self) -> str | None:
    """The active route's offline status, or None without a route."""
    if self._store.active_destination() is None:
      return None
    route = self.summary.get("route") or {}
    total, remaining = int(route.get("total") or 0), int(route.get("remaining") or 0)
    if not total:
      return tr("Saved automatically once the route is ready")
    if remaining <= 0:
      return tr("Saved • the map works without a connection")
    percent = 100 * (total - remaining) // total
    if self.summary.get("offline"):
      return tr("Waiting for a connection • {}% saved").format(percent)
    return tr("Saving for offline • {}%").format(percent)

  def _last_position(self) -> tuple[float, float] | None:
    """(latitude, longitude) of the last GPS fix."""
    raw = self._params.get("LastGPSPosition", encoding="utf-8") or ""
    try:
      data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
      latitude, longitude = float(data["latitude"]), float(data["longitude"])
    except (TypeError, ValueError, KeyError):
      return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)) or (abs(latitude) < 1e-6 and abs(longitude) < 1e-6):
      return None
    return latitude, longitude

  def _public_key(self) -> str:
    return str(self._params.get("MapboxPublicKey", encoding="utf-8") or "").strip()

  # ── actions ───────────────────────────────────────────────────────────────

  def activate(self, target: str) -> None:
    self.message = ""
    if target == "add:here":
      position = self._last_position()
      if position is None:
        self.message = tr("No location yet. Try again once the device has GPS.")
      else:
        self.open_chooser(position[0], position[1], "", reverse=True)
    elif target == "add:destination":
      destination = self._store.active_destination()
      if destination is not None:
        name = str(destination.get("name") or destination.get("place_name") or tr("Destination"))
        self.open_chooser(float(destination["latitude"]), float(destination["longitude"]), name)
    elif target == "add:search":
      self._open_search_keyboard()
    elif target == "add:cancel":
      self.chooser = None
      self.search_results = []
    elif target.startswith("result:"):
      index = int(target.split(":", 1)[1])
      if 0 <= index < len(self.search_results):
        self._pick_result(self.search_results[index])
    elif target.startswith("area_radius:") and self.chooser is not None:
      self.step_radius(int(target.split(":", 1)[1]))
    elif target.startswith("area_level:") and self.chooser is not None:
      level = target.split(":", 1)[1]
      self.chooser["zoom"] = None if level == "auto" else int(level)
      self._estimate()
    elif target == "area_save":
      self.save_area()
    elif target.startswith("area:"):
      area_id = target.split(":", 1)[1]
      self.selected_area_id = None if self.selected_area_id == area_id else area_id
    elif target == "area_action:update" and self.selected_area_id:
      self._offline.request_update(self.selected_area_id)
      self.refresh()
    elif target == "area_action:now" and self.selected_area_id:
      self._offline.allow_metered(self.selected_area_id)
      self.refresh()
    elif target == "area_action:delete" and self.selected_area_id:
      self._confirm_delete(self.selected_area_id)
    elif target == "theme":
      self._pick_theme()

  @property
  def metric(self) -> bool:
    return bool(ui_state.is_metric)

  def open_chooser(self, latitude: float, longitude: float, name: str, reverse: bool = False) -> None:
    """Drop the pin and open the area editor, keeping the radius and detail of an editor already open."""
    from openpilot.starpilot.system.starpilot_auto.ui.offline_area_editor import DEFAULT_RADIUS, MILE_KM
    previous = self.chooser or {}
    default_km = DEFAULT_RADIUS[self.metric] * (1.0 if self.metric else MILE_KM)
    self._generation += 1
    self.search_results = []
    self.chooser = {"latitude": latitude, "longitude": longitude, "name": name or f"{latitude:.3f}, {longitude:.3f}",
                    "radius_km": previous.get("radius_km", default_km), "zoom": previous.get("zoom"), "estimate": None}
    if reverse:
      self._name_pin(latitude, longitude)
    self._estimate()

  def move_pin(self, latitude: float, longitude: float) -> None:
    if self.chooser is not None:
      self.open_chooser(latitude, longitude, "", reverse=True)

  def _name_pin(self, latitude: float, longitude: float) -> None:
    generation, public_key, search_client = self._generation, self._public_key(), self._search_client
    if not public_key:
      return

    def worker():
      try:
        place = search_client.reverse(latitude, longitude, public_key)
      except Exception:
        return
      if place:
        self._pending.put(("name", generation, place))

    threading.Thread(target=worker, daemon=True, name="offline-area-name").start()

  def area_zoom(self) -> int:
    chooser = self.chooser or {}
    return chooser.get("zoom") or area_zoom_for_radius(chooser.get("radius_km", 10.0))

  def step_radius(self, direction: int) -> None:
    from openpilot.starpilot.system.starpilot_auto.ui.offline_area_editor import radius_steps
    steps = radius_steps(self.metric)
    current = min(range(len(steps)), key=lambda index: abs(steps[index] - self.chooser["radius_km"]))
    self.chooser["radius_km"] = steps[max(0, min(len(steps) - 1, current + direction))]
    self._estimate()

  def _estimate(self) -> None:
    """Size the area in the background; a newer change makes an older result stale."""
    chooser = self.chooser
    chooser["estimate"] = None
    key = (chooser["latitude"], chooser["longitude"], chooser["radius_km"], self.area_zoom())
    generation = self._generation

    def worker():
      self._pending.put(("estimate", generation, (key, estimate_area(*key))))

    threading.Thread(target=worker, daemon=True, name="offline-area-estimate").start()

  def estimate_text(self) -> tuple[str, bool]:
    """(text, whether the area can be saved)."""
    from openpilot.starpilot.system.starpilot_auto.ui.offline_area_editor import DETAIL
    estimate = self.chooser and self.chooser.get("estimate")
    if not estimate:
      return tr("Sizing up the area…"), False
    tiles, size = estimate
    if self.used_bytes + size > OFFLINE_MAX_BYTES:
      return tr("Too large for the space left. Try a smaller radius or less detail."), False
    return tr("{} • about {} • {} tiles").format(tr(DETAIL.get(self.area_zoom(), "")), format_bytes(size), f"{tiles:,}"), True

  def save_area(self) -> None:
    chooser = self.chooser
    if chooser is None or not self.estimate_text()[1]:
      return
    self._offline.add_area(chooser["name"], chooser["latitude"], chooser["longitude"], chooser["radius_km"], self.area_zoom())
    self.chooser = None
    self.refresh()

  def _open_search_keyboard(self) -> None:
    if not self._public_key():
      self.message = tr("Mapbox search isn't set up. Add a Mapbox public key in The Galaxy.")
      return
    if self._keyboard is None:
      self._keyboard = Keyboard(min_text_size=3)
    keyboard = self._keyboard
    keyboard.reset(min_text_size=3)
    keyboard.set_title(tr("Save a map around…"), tr("Enter a city, place or address"))
    keyboard.set_text("")
    keyboard.set_callback(lambda result: self._search(keyboard.text) if result == DialogResult.CONFIRM else None)
    gui_app.push_widget(keyboard)

  def _search(self, query: str) -> None:
    query = query.strip()
    if len(query) < 3:
      return
    self._generation += 1
    generation, public_key, token = self._generation, self._public_key(), self._session_token
    self.chooser = None
    self.search_results = []
    self.search_busy = True
    position = self._last_position()
    proximity = (position[1], position[0]) if position else None

    def worker():
      try:
        self._pending.put(("search", generation, self._search_client.search(query, public_key, token, proximity=proximity)))
      except Exception as error:
        self._pending.put(("search", generation, error))

    threading.Thread(target=worker, daemon=True, name="offline-area-search").start()

  def _pick_result(self, result: SearchResult) -> None:
    if result.has_coordinates:
      self.open_chooser(float(result.latitude), float(result.longitude), result.name)
      return
    self._generation += 1
    generation, public_key, token = self._generation, self._public_key(), self._session_token
    self.search_busy = True

    def worker():
      try:
        self._pending.put(("resolve", generation, self._search_client.resolve(result, public_key, token)))
      except Exception as error:
        self._pending.put(("resolve", generation, error))

    threading.Thread(target=worker, daemon=True, name="offline-area-resolve").start()

  def _consume_pending(self) -> None:
    while True:
      try:
        kind, generation, payload = self._pending.get_nowait()
      except queue.Empty:
        return
      if generation != self._generation:
        continue
      if kind == "name" and self.chooser is not None:
        self.chooser["name"] = payload
      elif kind == "estimate" and self.chooser is not None:
        key, estimate = payload
        if key == (self.chooser["latitude"], self.chooser["longitude"], self.chooser["radius_km"], self.area_zoom()):
          self.chooser["estimate"] = estimate
      elif kind == "search":
        self.search_busy = False
        if isinstance(payload, Exception):
          self.message = tr("Search is unavailable. Check your connection and try again.")
        else:
          self.search_results = payload
          if not payload:
            self.message = tr("No places found. Try another search.")
      elif kind == "resolve":
        self.search_busy = False
        if isinstance(payload, SearchResult) and payload.has_coordinates:
          self.open_chooser(float(payload.latitude), float(payload.longitude), payload.name)
        else:
          self.message = tr("Couldn't find that place on the map. Try another result.")

  def _confirm_delete(self, area_id: str) -> None:
    area = next((item for item in self.areas if item.id == area_id), None)
    if area is None:
      return

    def on_result(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._offline.delete_area(area_id)
        self.selected_area_id = None
        self.refresh()

    gui_app.push_widget(ConfirmDialog(tr("Delete the offline map for {}?").format(self.area_title(area)), tr("Delete"), callback=on_result))

  def theme_text(self) -> str:
    theme = self.summary.get("map_theme") or self._offline.map_theme()
    if theme != "auto":
      return tr("{} map • no traffic").format(tr(THEME_LABELS[theme]))
    now = tr("light now") if self.showing_light else tr("dark now")
    return tr("Light from sunrise, dark from sunset • {}").format(now)

  def _pick_theme(self) -> None:
    labels = {theme: tr(label) for theme, label in THEME_LABELS.items()}
    current = self._offline.map_theme()
    dialog = None

    def apply(theme: str, discard: bool) -> None:
      try:
        self._offline.set_map_theme(theme, discard_dropped=discard)
      except (OSError, ValueError) as error:
        self.message = tr("Couldn't change map colors: {}").format(error)
      self.refresh()

    def on_pick(result: DialogResult) -> None:
      theme = next((key for key, label in labels.items() if label == dialog.selection), current)
      if result != DialogResult.CONFIRM or theme == current:
        return
      dropped = self._offline.dropped_styles(theme)
      if not dropped:
        apply(theme, False)
        return
      names = " and ".join(tr(STYLE_NAMES.get(style, "dark")) for style in dropped)
      # Cancel (or leaving the dialog) keeps them: nothing is deleted without a clear yes.
      gui_app.push_widget(ConfirmDialog(
        tr(KEEP_QUESTION).format(names),
        tr("Delete"), cancel_text=tr("Keep"),
        callback=lambda answer: apply(theme, answer == DialogResult.CONFIRM)))

    dialog = MultiOptionDialog(tr("Map colors"), list(labels.values()), labels[current], callback=on_pick)
    gui_app.push_widget(dialog)

  def usage_text(self) -> str:
    usage = self.summary.get("usage") or {}
    tiles, free = int(usage.get("tiles") or 0), int(usage.get("free_tiles") or 200_000)
    text = tr("Mapbox this month: {} of {} free tile requests").format(f"{tiles:,}", f"{free:,}")
    routes = int(usage.get("directions") or 0)
    return text + (tr(" • {} route lookups").format(f"{routes:,}") if routes else "")

  # ── layout ────────────────────────────────────────────────────────────────

  def add_buttons(self) -> list[tuple[str, str]]:
    buttons = [("add:here", tr("Around me"))]
    if self._store.active_destination() is not None:
      buttons.append(("add:destination", tr("Around destination")))
    buttons.append(("add:search", tr("Search a place")))
    return buttons

  def layout_rows(self) -> list[tuple[str, float, Any]]:
    """(kind, height, data) rows, shared by drawing and measuring."""
    rows: list[tuple[str, float, Any]] = [("storage", self.storage_height() + GAP, None), ("theme", ROW_HEIGHT + GAP, None),
                                         ("add_header", SECTION_HEIGHT, None)]
    # While an area is being set up the editor replaces this list (see _render).
    rows.append(("add_buttons", BUTTON_HEIGHT + GAP, None))
    if self.search_busy:
      rows.append(("searching", ROW_HEIGHT, None))
    rows += [("result", ROW_HEIGHT, index) for index in range(len(self.search_results))]
    if self.search_results:
      rows.append(("cancel", BUTTON_HEIGHT + GAP, None))
    if self.message:
      rows.append(("message", EMPTY_HEIGHT + GAP, None))
    route = self.route_text()
    if route is not None:
      rows += [("route_header", SECTION_HEIGHT, None), ("route", ROW_HEIGHT + GAP, route)]
    rows.append(("saved_header", SECTION_HEIGHT, None))
    for area in self.areas:
      rows.append(("area", ROW_HEIGHT, area))
      if area.id == self.selected_area_id and not area.deleted:
        rows.append(("area_actions", BUTTON_HEIGHT + GAP, area))
    if not self.areas:
      rows.append(("empty", EMPTY_HEIGHT, None))
    return rows

  # ── drawing ───────────────────────────────────────────────────────────────

  def _pill(self, manager, rect: rl.Rectangle, target: str, label: str, color=None) -> None:
    hovered, pressed = manager._interactive_state(target, rect, pad_y=4)
    color = color or AetherListColors.PRIMARY
    draw_action_pill(rect, label, with_alpha(color, 54 if hovered or pressed else 24), with_alpha(color, 110), AetherListColors.HEADER,
                     font_size=26)

  def _pills(self, manager, x: float, y: float, width: float, pills: list[tuple[str, str, Any]]) -> None:
    pill_w = (width - GAP * (len(pills) - 1)) / len(pills)
    for index, (target, label, color) in enumerate(pills):
      self._pill(manager, rl.Rectangle(x + index * (pill_w + GAP), y, pill_w, BUTTON_HEIGHT), target, label, color)

  def _row(self, manager, rect: rl.Rectangle, target: str | None, title: str, subtitle: str, action: str = "", current: bool = False):
    hovered, pressed = manager._interactive_state(target, rect) if target else (False, False)
    draw_selection_list_row(
      rect, title=title, subtitle=subtitle, action_text=action, current=current, hovered=hovered, pressed=pressed,
      action_width=170 if action else 0, action_pill=bool(action), action_pill_height=58, action_pill_width=140,
      title_size=32, subtitle_size=24, action_text_size=24, row_separator=PANEL_STYLE.divider_color,
      current_bg=AetherListColors.CURRENT_BG, current_border=AetherListColors.CURRENT_BORDER,
    )

  def _draw_storage(self, rect: rl.Rectangle) -> None:
    draw_list_group_shell(rect, style=PANEL_STYLE)
    x, width = rect.x + 30, rect.width - 60
    saved = [area for area in self.areas if not area.deleted]
    used = tr("{} of {} used").format(format_bytes(self.used_bytes), format_bytes(OFFLINE_MAX_BYTES))
    count = tr("{} saved map").format(len(saved)) if len(saved) == 1 else tr("{} saved maps").format(len(saved))
    # Size used on the left, map count on the right of the same line, above the bar.
    style.text(rl.Rectangle(x, rect.y + 20, width * .62, 50), used, 38, bold=True)
    style.text(rl.Rectangle(x + width * .62, rect.y + 20, width * .38, 50), count, 28, style.MUTED, align='right')

    bar = rl.Rectangle(x, rect.y + 86, width, 16)
    fraction = min(1.0, self.used_bytes / OFFLINE_MAX_BYTES)
    rl.draw_rectangle_rounded(bar, 1.0, 8, with_alpha(AetherListColors.HEADER, 22))
    if fraction > 0:
      color = AetherListColors.WARNING if fraction > 0.9 else AetherListColors.PRIMARY
      rl.draw_rectangle_rounded(rl.Rectangle(bar.x, bar.y, max(bar.height, bar.width * fraction), bar.height), 1.0, 8, color)

    text, color = self.connection_text()
    rl.draw_circle_v(rl.Vector2(x + 8, rect.y + 145), 7, color)
    for index, line in enumerate(self.status_lines(rect.width)):
      style.text(rl.Rectangle(x + 28, rect.y + 126 + index * STATUS_LINE, width - 28, 40), line, STATUS_SIZE, style.MUTED)

  def status_lines(self, card_width: float) -> list[str]:
    width = max(1.0, card_width - 60 - 28)
    return style.lines(self.connection_text()[0], width, STATUS_SIZE) + style.lines(self.usage_text(), width, STATUS_SIZE)

  def storage_height(self) -> float:
    """The storage card grows by a line for each extra line of status, so none of it is cut off."""
    width = getattr(self, "row_width", None)
    return STORAGE_HEIGHT if width is None else STORAGE_HEIGHT + STATUS_LINE * max(0, len(self.status_lines(width)) - 1)

  def draw_rows(self, scroll_rect: rl.Rectangle, content_width: float, scroll_offset: float, manager) -> None:
    x = scroll_rect.x + INSET
    width = max(1.0, content_width - INSET * 2)
    self.row_width = width
    y = scroll_rect.y + scroll_offset + INSET
    for kind, height, data in self.layout_rows():
      rect = rl.Rectangle(x, y, width, height)
      if kind == "storage":
        self._draw_storage(rl.Rectangle(x, y, width, self.storage_height()))
      elif kind == "theme":
        self._row(manager, rl.Rectangle(x, y, width, ROW_HEIGHT), "theme", tr("Map colors"), self.theme_text(), tr("Change"))
      elif kind == "add_header":
        title = tr("Save a new area")
        draw_section_header(rect, title, title_size=30, style=PANEL_STYLE)
      elif kind == "add_buttons":
        self._pills(manager, x, y, width, [(target, label, None) for target, label in self.add_buttons()])
      elif kind == "cancel":
        self._pills(manager, x, y, width, [("add:cancel", tr("Cancel"), None)])
      elif kind == "searching":
        self._row(manager, rect, None, tr("Searching…"), "")
      elif kind == "result":
        result = self.search_results[data]
        self._row(manager, rect, f"result:{data}", result.name, result.subtitle, tr("Choose"))
      elif kind == "message":
        draw_empty_state_card(rl.Rectangle(x, y, width, EMPTY_HEIGHT), tr("Can't do that yet"), self.message, title_size=28, body_size=24,
                              border=with_alpha(AetherListColors.WARNING, 60), style=PANEL_STYLE)
      elif kind == "route_header":
        draw_section_header(rect, tr("Current route"), title_size=30, style=PANEL_STYLE)
      elif kind == "route":
        destination = self._store.active_destination() or {}
        self._row(manager, rl.Rectangle(x, y, width, ROW_HEIGHT), None,
                  tr("To {}").format(destination.get("name") or destination.get("place_name") or tr("destination")), data)
      elif kind == "saved_header":
        draw_section_header(rect, tr("Saved maps"), trailing_text=tr("Updated every {} days").format(self.summary.get("refresh_days") or 90),
                            title_size=30, trailing_size=24, style=PANEL_STYLE)
      elif kind == "area":
        selected = self.selected_area_id == data.id
        action = "" if data.deleted else (tr("Close") if selected else tr("Manage"))
        self._row(manager, rect, None if data.deleted else f"area:{data.id}", self.area_title(data), self.area_status(data), action, selected)
      elif kind == "area_actions":
        state = self._progress(data.id)
        waiting = state.get("state") == "waiting_wifi" and not data.allow_metered
        first = ("area_action:now", tr("Download now"), AetherListColors.SUCCESS) if waiting else ("area_action:update", tr("Update now"), None)
        self._pills(manager, x, y, width, [first, ("area_action:delete", tr("Delete"), AetherListColors.DANGER)])
      elif kind == "empty":
        draw_empty_state_card(rl.Rectangle(x, y, width, EMPTY_HEIGHT), tr("No saved maps yet"),
                              tr("Save an area on Wi-Fi so the map keeps working without signal."),
                              title_size=30, body_size=24, border=with_alpha(PANEL_STYLE.surface_border, 14), style=PANEL_STYLE)
      y += height
