from __future__ import annotations

from openpilot.system.ui.lib.multilang import tr_noop
from openpilot.selfdrive.ui.layouts.settings.starpilot.panel import _SettingsPage
from openpilot.selfdrive.ui.layouts.settings.starpilot.aethergrid import (
  DEFAULT_PANEL_STYLE,
  AetherSettingsView,
  SettingRow,
  SettingSection,
)


class StarPilotNavSettingsLayout(_SettingsPage):
  """Every navigation toggle in one place: route display, steering and gas/brake behavior."""

  def __init__(self):
    super().__init__()
    p = self._params

    def nav_desires():
      return p.get_bool("NavDesiresAllowed")

    def nav_long():
      return p.get_bool("LongitudinalTune") and p.get_bool("NavLongitudinalAllowed")

    route_rows = [
      SettingRow("NavigationUI", "toggle", tr_noop("Navigation Widgets"),
                 subtitle=tr_noop("Show navigation info on the driving screen."),
                 get_state=lambda: p.get_bool("NavigationUI"),
                 set_state=lambda s: p.put_bool("NavigationUI", s)),
      SettingRow("ClearNavOnOffroad", "toggle", tr_noop("Clear Route When Offroad"),
                 subtitle=tr_noop("Clear the active navigation destination when the device goes offroad."),
                 get_state=lambda: p.get_bool("ClearNavOnOffroad"),
                 set_state=lambda s: p.put_bool("ClearNavOnOffroad", s)),
      SettingRow("NavTrafficReroute", "toggle", tr_noop("Offer Faster Routes"),
                 subtitle=tr_noop("Check traffic every couple of minutes while navigating and offer a faster route when one saves at least 2 minutes and 10%. The route only changes if you tap Switch. Uses extra Mapbox requests."),
                 get_state=lambda: p.get_bool("NavTrafficReroute"),
                 set_state=lambda s: p.put_bool("NavTrafficReroute", s)),
    ]

    steering_rows = [
      SettingRow("NavDesiresAllowed", "toggle", tr_noop("Use Route Desires"),
                 subtitle=tr_noop("Allow navigation to request lane keep and turns."),
                 get_state=lambda: p.get_bool("NavDesiresAllowed"),
                 set_state=lambda s: p.put_bool("NavDesiresAllowed", s)),
      SettingRow("NavLanePositioningAllowed", "toggle", tr_noop("Route Lane Positioning"),
                 subtitle=tr_noop("Allow navigation to position in lane and request highway exit lane changes: blinker toward the exit for the first lane, blinker + nudge for each further lane."),
                 get_state=lambda: p.get_bool("NavLanePositioningAllowed"),
                 set_state=lambda s: p.put_bool("NavLanePositioningAllowed", s),
                 visible=nav_desires),
      SettingRow("NavExitAutoKeep", "toggle", tr_noop("Auto-Take Exit"),
                 subtitle=tr_noop("Take a same-side highway exit or on-ramp without the blinker or a wheel nudge when navigation lane guidance already puts you in the ramp-side edge lane. Never forks, above 8 m/s, withdrawn by any steering input. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavExitAutoKeep"),
                 set_state=lambda s: p.put_bool("NavExitAutoKeep", s),
                 visible=lambda: nav_desires() and p.get_bool("NavLanePositioningAllowed")),
    ]

    gas_brake_rows = [
      SettingRow("NavLongitudinalAllowed", "toggle", tr_noop("Use Route Speed Control"),
                 subtitle=tr_noop("Allow an active navigation route to reduce cruise speed for upcoming turns, ramps, and roundabouts."),
                 get_state=lambda: p.get_bool("NavLongitudinalAllowed"),
                 set_state=lambda s: p.put_bool("NavLongitudinalAllowed", s),
                 visible=lambda: p.get_bool("LongitudinalTune")),
      SettingRow("NavOffRampSlowdown", "toggle", tr_noop("Slow for Off-Ramps"),
                 subtitle=tr_noop("Ease down to 50 mph by the exit split when navigation takes an off-ramp and you are already in the exit-side lane. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavOffRampSlowdown"),
                 set_state=lambda s: p.put_bool("NavOffRampSlowdown", s),
                 visible=nav_long),
      SettingRow("NavJamSlowdown", "toggle", tr_noop("Slow for Traffic Jams"),
                 subtitle=tr_noop("Ease down before heavy traffic that Mapbox reports on the route ahead (not below 40 mph), and let go once you reach it. Mapbox traffic can be wrong or old; radar still does the real braking. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavJamSlowdown"),
                 set_state=lambda s: p.put_bool("NavJamSlowdown", s),
                 visible=nav_long),
    ]

    self._manager_view = AetherSettingsView(
      self,
      [
        SettingSection(title=tr_noop("Route"), rows=route_rows),
        SettingSection(title=tr_noop("Steering"), rows=steering_rows),
        SettingSection(title=tr_noop("Gas / Brake"), rows=gas_brake_rows),
      ],
      header_title=tr_noop("Navigation Settings"),
      header_subtitle=tr_noop("Every setting that changes what an active route does."),
      panel_style=DEFAULT_PANEL_STYLE,
    )
