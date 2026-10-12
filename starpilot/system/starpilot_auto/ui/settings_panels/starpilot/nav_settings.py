from __future__ import annotations

from openpilot.system.ui.lib.multilang import tr_noop
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.panel import _SettingsPage
from openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.aethergrid import (
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
                 subtitle=tr_noop("Take a same-side highway exit or on-ramp without the blinker or a wheel nudge when navigation lane guidance already puts you in the ramp-side edge lane. Also follows the route at a fork. Above 8 m/s, withdrawn by any steering input. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavExitAutoKeep"),
                 set_state=lambda s: p.put_bool("NavExitAutoKeep", s),
                 visible=lambda: nav_desires() and p.get_bool("NavLanePositioningAllowed")),
      SettingRow("NavPassingSuggest", "toggle", tr_noop("Suggest Passing"),
                 subtitle=tr_noop("On a navigated highway, suggest passing when you and the car ahead are 5+ mph under the limit for 5 s and V-ASM sees the left side clear, then suggest moving back right after the pass. Prompt and chime only; your blinker does the lane change. Radar cannot see cars behind: check your mirror. Needs V-ASM. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavPassingSuggest"),
                 set_state=lambda s: p.put_bool("NavPassingSuggest", s),
                 visible=lambda: p.get_bool("VASMEnabled")),
      SettingRow("NavExitOnlyWarn", "toggle", tr_noop("Warn About Exit-Only Lanes"),
                 subtitle=tr_noop("Warn with a banner and chime when you are in an exit-only lane up to about a mile before an exit your route does not take, or in a city turn-only lane about 1000 ft before a turn your route does not take. Uses Mapbox lane data, which some roads lack. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavExitOnlyWarn"),
                 set_state=lambda s: p.put_bool("NavExitOnlyWarn", s)),
      SettingRow("NavKeepRightReminder", "toggle", tr_noop("Keep Right Reminder"),
                 subtitle=tr_noop("On a navigated highway, remind you to move right after a minute of cruising with the right lane open, not slower, and V-ASM clear on the right. At most once every 5 minutes. Prompt and chime only. Needs V-ASM. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavKeepRightReminder"),
                 set_state=lambda s: p.put_bool("NavKeepRightReminder", s),
                 visible=lambda: p.get_bool("VASMEnabled")),
      SettingRow("NavMergeWarn", "toggle", tr_noop("Warn About Merges"),
                 subtitle=tr_noop("Banner and chime about 1000 ft before the route merges, telling you which side; says to wait while V-ASM sees a car beside you on that side. Prompt only; your hands do the merge. Needs V-ASM. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavMergeWarn"),
                 set_state=lambda s: p.put_bool("NavMergeWarn", s),
                 visible=lambda: p.get_bool("VASMEnabled")),
      SettingRow("NavJamExitWarn", "toggle", tr_noop("Warn When Your Exit Is Backed Up"),
                 subtitle=tr_noop("When Mapbox traffic shows the next exit on the route backed up within 2 miles, prompt you to move toward the exit early while a lane on that side exists. Prompt and chime only. Mapbox traffic can be wrong or old. Needs V-ASM. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavJamExitWarn"),
                 set_state=lambda s: p.put_bool("NavJamExitWarn", s),
                 visible=lambda: p.get_bool("VASMEnabled")),
      SettingRow("NavArrivalHelp", "toggle", tr_noop("Show Destination Side"),
                 subtitle=tr_noop("In the last 1/4 mile, show which side of the road the destination is on. Banner only: no chime and no slowdown. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavArrivalHelp"),
                 set_state=lambda s: p.put_bool("NavArrivalHelp", s)),
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
      SettingRow("NavStopAnticipate", "toggle", tr_noop("Hand Mapped Stops to the Model"),
                 subtitle=tr_noop("When Conditional Experimental Mode is on, switch to Experimental Mode about 8 s (at least 260 ft) before a traffic signal, stop sign, or railway crossing that Mapbox marks on the route, so the model can stop for it. Mapbox does not mark every control. Experimental and off by default; not road-validated."),
                 get_state=lambda: p.get_bool("NavStopAnticipate"),
                 set_state=lambda s: p.put_bool("NavStopAnticipate", s),
                 visible=lambda: p.get_bool("ConditionalExperimental")),
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
