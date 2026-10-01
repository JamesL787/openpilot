"""The car screen's StarPilot settings hub.

Owns the car settings panels. Map Data becomes Offline Maps (Map Data
stays inside it as the "Speed limit data" segment) and Navigation is the car's
page with route choices and a map preview.
"""

from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.main_panel import StarPilotLayout
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.panel import StarPilotPanelInfo, StarPilotPanelType
from openpilot.starpilot.system.starpilot_auto.ui.navigation import CarNavigationLayout
from openpilot.starpilot.system.starpilot_auto.ui.offline_maps import SEGMENT_DISPLAY, SEGMENT_ROAD_DATA, StarPilotOfflineMapsLayout
from openpilot.system.ui.lib.multilang import tr_noop


class CarStarPilotLayout(StarPilotLayout):
  CATEGORIES = [
    {"title": "Sounds & Alerts", "icon": "sound", "panel": "SOUNDS"},
    {"title": "Driving Model", "icon": "aicar", "panel": "DRIVING_MODEL"},
    {
      "title": "Driving Controls",
      "icon": "steering",
      "children": [
        {
          "title": "Navigation & Maps",
          "icon": "navigate",
          "children": [
            {"title": "Navigation", "panel": "NAVIGATION", "icon": "road"},
            {"title": "Offline Maps", "panel": "MAPS", "icon": "navigate"},
          ],
        },
        {"title": "Gas / Brake", "panel": "LONGITUDINAL", "icon": "road"},
        {"title": "Steering", "panel": "LATERAL", "icon": "steering"},
      ],
    },
    {"title": "System", "icon": "system", "panel": "SYSTEM"},
    {"title": "Appearance", "icon": "display", "panel": "VISUALS"},
    {"title": "Vehicle Settings", "icon": "vehicle", "panel": "VEHICLE"},
  ]

  def _create_maps_panel(self):
    return StarPilotPanelInfo(tr_noop("Offline Maps"), StarPilotOfflineMapsLayout())

  def _create_navigation_panel(self):
    return StarPilotPanelInfo(tr_noop("Navigation"), CarNavigationLayout())

  def open_panel(self, panel_key: str):
    """Jump straight to a panel, opening the hub folders above it so Back walks up them."""
    if panel_key in ("MAPS", "OFFLINE_MAPS"):
      segment = SEGMENT_ROAD_DATA if panel_key == "MAPS" else SEGMENT_DISPLAY
      self._panels[StarPilotPanelType.MAPS].instance.open_segment(segment)
      panel_key = "MAPS"

    def find(folders, path):
      for item in folders:
        if item.get("panel") == panel_key:
          return path, item
        found = find(item.get("children", []), path + [item])
        if found is not None:
          return found
      return None

    found = find(self.CATEGORIES, [])
    if found is None:
      return
    self.reset_to_root()
    folders, leaf = found
    for folder in folders:
      self._open_folder(folder)
    self._open_leaf(leaf)
