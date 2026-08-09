from __future__ import annotations

import datetime
import glob
import os
import shutil
import subprocess

import pyray as rl

from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.html_render import HtmlModal
from openpilot.selfdrive.ui.layouts.settings.starpilot.panel import _SettingsPage
from openpilot.selfdrive.ui.layouts.settings.starpilot.aethergrid import (
  AetherSettingsView,
  DEFAULT_PANEL_STYLE,
  HubTile,
  SettingRow,
  SettingSection,
  TileGrid,
)


PANEL_STYLE = DEFAULT_PANEL_STYLE

TUNE_REPORT_PATH = "/data/nrdr_tune_report.txt"
TUNE_REPORT_TMP = TUNE_REPORT_PATH + ".tmp"
MEDIA_ROOT = "/data/media/0"
# This device records to realdata_konik, not realdata.
RLOG_GLOBS = (f"{MEDIA_ROOT}/realdata_konik/*/rlog.zst", f"{MEDIA_ROOT}/realdata_konik/*/rlog.bz2")


class NRDRManagerView(AetherSettingsView):
  @property
  def vertical_scrolling_disabled(self) -> bool:
    return True

  def __init__(self, controller: "NRDRTuningLayout"):
    super().__init__(controller, [], panel_style=PANEL_STYLE)
    self._grid = TileGrid(columns=2, padding=12)
    self._grid.set_touch_valid_callback(lambda: self._scroll_panel.is_touch_valid())
    self._child(self._grid)

    self._grid.add_tile(HubTile(
      title=tr("NRDR Lateral"),
      desc=tr("Configure Clarity EPS behavior, speed-banded PID gains, driver override, filters, and online tuning."),
      icon_key="steering",
      on_click=lambda: controller._navigate_to("lateral"),
      bg_color="#8B5CF6",
    ))
    self._grid.add_tile(HubTile(
      title=tr("NRDR Long"),
      desc=tr("Configure Honda Nidec gas, brake, stopping, and longitudinal PID behavior."),
      icon_key="road",
      on_click=lambda: controller._navigate_to("longitudinal"),
      bg_color="#8B5CF6",
    ))

  def _render(self, rect: rl.Rectangle):
    self.set_rect(rect)
    self._interactive_rects.clear()

    margin = 10.0
    self._scroll_rect = rl.Rectangle(
      rect.x + margin,
      rect.y + margin,
      rect.width - margin * 2,
      rect.height - margin * 2,
    )
    self._content_height = self._scroll_rect.height
    self._scroll_panel.set_enabled(self.is_visible)
    self._scroll_offset = self._scroll_panel.update(self._scroll_rect, self._scroll_rect.height)
    self._draw_scroll_content(self._scroll_rect, self._scroll_rect.width)

  def _draw_scroll_content(self, rect: rl.Rectangle, width: float):
    self._grid.set_parent_rect(self._scroll_rect)
    self._grid.render(rl.Rectangle(rect.x, rect.y, width, rect.height))


class NRDRTuningLayout(_SettingsPage):
  # ── Tune Report (ported from nrdr-nightly) ──
  # Runs tune_report.py over this device's rlogs in a background process and shows the result.
  # Read-only and param-free, so nothing here needs a device rebuild.

  def _scanning(self) -> bool:
    return self._scan_proc is not None

  def _on_tune_report_scan(self):
    if self._scanning():
      return

    paths = []
    for pattern in RLOG_GLOBS:
      paths.extend(sorted(glob.glob(pattern)))
    if not paths:
      gui_app.push_widget(HtmlModal(text=tr("No drive logs found in /data/media/0/realdata_konik.")))
      return

    try:
      self._scan_fh = open(TUNE_REPORT_TMP, "w")
      self._scan_proc = subprocess.Popen(
        ["python3", os.path.join(BASEDIR, "tune_report.py"), *paths],
        stdout=self._scan_fh,
        stderr=subprocess.STDOUT,
        cwd=BASEDIR,
      )
    except Exception as e:
      if self._scan_fh is not None:
        self._scan_fh.close()
        self._scan_fh = None
      self._scan_proc = None
      gui_app.push_widget(HtmlModal(text=tr("Could not start the tune report scan.") + f"<br><br>{e}"))

  def _poll_tune_report_scan(self):
    if self._scan_proc is None or self._scan_proc.poll() is None:
      return

    if self._scan_fh is not None:
      self._scan_fh.close()
      self._scan_fh = None
    self._scan_proc = None

    # Keep the output either way: on failure it holds the traceback, which is what you want to read.
    try:
      os.replace(TUNE_REPORT_TMP, TUNE_REPORT_PATH)
    except OSError:
      pass

    self._show_tune_report()

  def _show_tune_report(self):
    if not os.path.exists(TUNE_REPORT_PATH):
      gui_app.push_widget(HtmlModal(text=tr("No tune report yet. Press SCAN to analyze the drive logs on this device.")))
      return

    stamp = datetime.datetime.fromtimestamp(os.path.getmtime(TUNE_REPORT_PATH)).strftime("%d-%b-%Y %H:%M:%S").upper()
    text = f"<b>{stamp}</b><br><br>"
    try:
      with open(TUNE_REPORT_PATH) as f:
        text += f.read().replace("\n", "<br>")
    except Exception:
      pass
    gui_app.push_widget(HtmlModal(text=text))

  def _on_tune_report_delete(self):
    gui_app.push_widget(ConfirmDialog(
      tr("Delete ALL dashcam media in /data/media/0? This permanently erases every recorded drive on the "
         "device and cannot be undone."),
      tr("Delete"),
      tr("Cancel"),
      callback=self._on_tune_report_delete_confirmed,
    ))

  def _on_tune_report_delete_confirmed(self, result: DialogResult):
    if result != DialogResult.CONFIRM:
      return
    try:
      entries = os.listdir(MEDIA_ROOT)
    except OSError:
      entries = []
    for entry in entries:
      path = os.path.join(MEDIA_ROOT, entry)
      try:
        if os.path.isdir(path) and not os.path.islink(path):
          shutil.rmtree(path, ignore_errors=True)
        else:
          os.remove(path)
      except OSError:
        pass

  def _update_state(self):
    super()._update_state()
    self._poll_tune_report_scan()

  def __init__(self):
    super().__init__()
    self._scan_proc: subprocess.Popen | None = None
    self._scan_fh = None
    p = self._params

    def toggle(key: str, title: str, subtitle: str, *, visible=None) -> SettingRow:
      return SettingRow(
        key, "toggle", tr_noop(title), subtitle=tr_noop(subtitle),
        get_state=lambda k=key: p.get_bool(k),
        set_state=lambda state, k=key: p.put_bool(k, state),
        visible=visible,
      )

    def value(key: str, title: str, subtitle: str, get_value, on_click, *, visible=None) -> SettingRow:
      return SettingRow(
        key, "value", tr_noop(title), subtitle=tr_noop(subtitle),
        get_value=get_value, on_click=on_click, visible=visible,
      )

    pid_sections = []
    for label, suffix in (("Low Speed PID (0-25 mph)", "LowSpeed"),
                          ("Standard Speed PID (26-49 mph)", "Standard"),
                          ("Highway PID (50+ mph)", "Highway")):
      pid_sections.append(SettingSection(title=tr_noop(label), rows=[
        value(
          f"LatPScale{suffix}", "Proportional Scale", "Scales proportional steering response. 100% preserves the base tune.",
          lambda s=suffix: f"{p.get_int(f'LatPScale{s}')}%",
          lambda s=suffix: self._show_slider(f"LatPScale{s}", 0, 500, step=5, unit="%", title="Proportional Scale"),
        ),
        value(
          f"LatIScale{suffix}", "Integral Scale", "Scales integral correction. 100% preserves the base tune.",
          lambda s=suffix: f"{p.get_int(f'LatIScale{s}')}%",
          lambda s=suffix: self._show_slider(f"LatIScale{s}", 0, 500, step=5, unit="%", title="Integral Scale"),
        ),
        value(
          f"LatFScale{suffix}", "Feedforward Scale", "Scales steering feedforward. 100% preserves the base tune.",
          lambda s=suffix: f"{p.get_int(f'LatFScale{s}')}%",
          lambda s=suffix: self._show_slider(f"LatFScale{s}", 0, 500, step=5, unit="%", title="Feedforward Scale"),
        ),
      ]))

    learning_rows = [
      toggle("NrdrLearnSteerRatio", "Learn Steering Ratio", "Use paramsd's learned steering ratio instead of the static car value."),
      toggle("NrdrLearnStiffness", "Learn Tire Stiffness", "Use paramsd's learned tire stiffness instead of 1.0."),
      toggle("NrdrLearnAngleOffset", "Learn Angle Offset", "Use paramsd's learned steering angle offset instead of zero."),
      toggle("NrdrTuneLearner", "2D Online Tune Learner", "Learn a speed-and-angle feedforward trim map while driving."),
      value(
        "NrdrTuneLearnerStrength", "Tune Learner Strength", "Maximum learned trim authority as a percent of full steering output.",
        lambda: f"{p.get_int('NrdrTuneLearnerStrength')}%",
        lambda: self._show_slider("NrdrTuneLearnerStrength", 0, 30, unit="%", title="Tune Learner Strength"),
        visible=lambda: p.get_bool("NrdrTuneLearner"),
      ),
      value(
        "NrdrTuneLearnerRate", "Tune Learner Rate", "Learning speed. Zero freezes learning while retaining the saved map.",
        lambda: f"{p.get_int('NrdrTuneLearnerRate')}%",
        lambda: self._show_slider("NrdrTuneLearnerRate", 0, 100, unit="%", title="Tune Learner Rate"),
        visible=lambda: p.get_bool("NrdrTuneLearner"),
      ),
      toggle("NrdrTuneLearnerReset", "Reset Tune Learner Map", "Clear the saved 2D trim map. This switch clears after controls process it."),
    ]

    center_rows = [
      value(
        "HondaCenterBoostThreshold", "Center Boost Angle", "Angle band where center boost and straight-line override tuning apply.",
        lambda: f"{p.get_float('HondaCenterBoostThreshold'):.1f} deg",
        lambda: self._show_slider("HondaCenterBoostThreshold", 0.0, 10.0, step=0.1, unit=" deg", value_type="float", title="Center Boost Angle"),
      ),
      value(
        "HondaCenterBoostMinSpeed", "Center Boost Min Speed", "Disable center boost below this speed to avoid low-speed oscillation.",
        lambda: f"{p.get_int('HondaCenterBoostMinSpeed')} mph",
        lambda: self._show_slider("HondaCenterBoostMinSpeed", 0, 90, unit=" mph", title="Center Boost Min Speed"),
      ),
      value(
        "HondaCenterScale", "Center Scale", "Feedforward scale near center. Lower values reduce torque through straight unwind.",
        lambda: f"{p.get_float('HondaCenterScale'):.2f}",
        lambda: self._show_slider("HondaCenterScale", 0.0, 5.0, step=0.05, value_type="float", title="Center Scale"),
      ),
      toggle("HondaUnwindFreeze", "Unwind Integrator Freeze", "Freeze the PID integrator while steering naturally returns toward center."),
      toggle("HondaUnwindLookahead", "Unwind Lookahead", "Use model path lookahead to begin unwind behavior earlier."),
      value(
        "HondaUnwindBoostSeconds", "Unwind Boost Duration", "Maximum duration of the low-speed unwind feedforward boost.",
        lambda: f"{p.get_float('HondaUnwindBoostSeconds'):.1f}s",
        lambda: self._show_slider("HondaUnwindBoostSeconds", 0.0, 3.0, step=0.1, unit="s", value_type="float", title="Unwind Boost Duration"),
      ),
      value(
        "HondaUnwindFfMultiplier", "Unwind FF Multiplier", "Peak low-speed feedforward multiplier during unwind.",
        lambda: f"{p.get_float('HondaUnwindFfMultiplier'):.1f}x",
        lambda: self._show_slider("HondaUnwindFfMultiplier", 1.0, 4.0, step=0.1, unit="x", value_type="float", title="Unwind FF Multiplier"),
      ),
    ]

    stiction_rows = [
      toggle("NrdrLatStiction", "Lateral Stiction", "Emulate high-torque EPS breakaway friction: hold steering output flat between "
                                                     "corrections instead of tracking small dither. Clarity EPS only."),
    ]


    override_rows = [
      toggle("NrdrIncreaseOverrideTolerance", "Override Hysteresis", "Double the override tolerance after steering input leaves center."),
      value(
        "NrdrDriverOverrideThreshold", "Driver Override Threshold", "Raw torque-sensor threshold outside the center boost angle band.",
        lambda: str(p.get_int("NrdrDriverOverrideThreshold")),
        lambda: self._show_slider("NrdrDriverOverrideThreshold", 0, 5000, title="Driver Override Threshold"),
      ),
      value(
        "NrdrOverrideThresholdCenterBoost", "Center Override Threshold", "Raw torque threshold inside the center boost angle band.",
        lambda: str(p.get_int("NrdrOverrideThresholdCenterBoost")),
        lambda: self._show_slider("NrdrOverrideThresholdCenterBoost", 0, 5000, title="Center Override Threshold"),
      ),
      toggle("HondaDriverAssistDuringOverride", "Assist During Override", "Keep controller torque while the driver is applying steering torque."),
      value(
        "HondaOverrideFadeUpSecs", "Override Fade Up", "Time to ramp controller authority back in after driver override.",
        lambda: f"{p.get_float('HondaOverrideFadeUpSecs'):.1f}s",
        lambda: self._show_slider("HondaOverrideFadeUpSecs", 0.0, 10.0, step=0.1, unit="s", value_type="float", title="Override Fade Up"),
      ),
      value(
        "HondaOverrideFadeDownSecs", "Override Fade Down", "Time to ramp controller authority down during driver override.",
        lambda: f"{p.get_float('HondaOverrideFadeDownSecs'):.1f}s",
        lambda: self._show_slider("HondaOverrideFadeDownSecs", 0.0, 10.0, step=0.1, unit="s", value_type="float", title="Override Fade Down"),
      ),
      value(
        "HondaOverrideTorqueScale", "Override Torque Scale", "Percent of controller torque retained during driver override.",
        lambda: f"{p.get_int('HondaOverrideTorqueScale')}%",
        lambda: self._show_slider("HondaOverrideTorqueScale", 0, 100, unit="%", title="Override Torque Scale"),
      ),
    ]

    filter_rows = [
      toggle("HondaTorqueLowPassFilter", "Torque Low Pass Filter", "Smooth steering torque using speed-banded time constants."),
      value(
        "HondaLpfTauLowSpeed", "LPF Tau: Low Speed", "Low-pass time constant below 25 mph.",
        lambda: f"{p.get_float('HondaLpfTauLowSpeed'):.2f}",
        lambda: self._show_slider("HondaLpfTauLowSpeed", 0.0, 5.0, step=0.01, value_type="float", title="LPF Tau: Low Speed"),
        visible=lambda: p.get_bool("HondaTorqueLowPassFilter"),
      ),
      value(
        "HondaLpfTauStandard", "LPF Tau: Standard", "Low-pass time constant from 25 to 50 mph.",
        lambda: f"{p.get_float('HondaLpfTauStandard'):.2f}",
        lambda: self._show_slider("HondaLpfTauStandard", 0.0, 5.0, step=0.01, value_type="float", title="LPF Tau: Standard"),
        visible=lambda: p.get_bool("HondaTorqueLowPassFilter"),
      ),
      value(
        "HondaLpfTauHighway", "LPF Tau: Highway", "Low-pass time constant above 50 mph.",
        lambda: f"{p.get_float('HondaLpfTauHighway'):.2f}",
        lambda: self._show_slider("HondaLpfTauHighway", 0.0, 5.0, step=0.01, value_type="float", title="LPF Tau: Highway"),
        visible=lambda: p.get_bool("HondaTorqueLowPassFilter"),
      ),
      toggle("HondaSteerDeltaLimiter", "Steer Delta Limiter", "Legacy torque rate limiter. Leave off unless testing."),
      value(
        "HondaSteerDeltaUp", "Steer Delta Up", "Maximum upward steering torque rate.",
        lambda: f"{p.get_float('HondaSteerDeltaUp'):.1f}",
        lambda: self._show_slider("HondaSteerDeltaUp", 0.0, 100.0, step=0.1, value_type="float", title="Steer Delta Up"),
        visible=lambda: p.get_bool("HondaSteerDeltaLimiter"),
      ),
      value(
        "HondaSteerDeltaDown", "Steer Delta Down", "Maximum downward steering torque rate.",
        lambda: f"{p.get_float('HondaSteerDeltaDown'):.1f}",
        lambda: self._show_slider("HondaSteerDeltaDown", 0.0, 100.0, step=0.1, value_type="float", title="Steer Delta Down"),
        visible=lambda: p.get_bool("HondaSteerDeltaLimiter"),
      ),
      value(
        "NrdrMinSteerSpeed", "Minimum Steer Speed", "Below this speed no steering torque is commanded. Zero uses the stock limit.",
        lambda: f"{p.get_int('NrdrMinSteerSpeed')} mph",
        lambda: self._show_slider("NrdrMinSteerSpeed", 0, 45, unit=" mph", title="Minimum Steer Speed"),
      ),
    ]

    tune_report_rows = [
      SettingRow(
        "TuneReportScan", "action", tr_noop("Tune Report"),
        subtitle=tr_noop("Analyze this device's drive logs and report, per speed band and turn direction, how "
                         "well the lateral tune is tracking. Scanning a full day of logs can take a few minutes."),
        action_text=tr_noop("SCAN"),
        # action_text is rendered as a plain string, so the running state shows via the
        # disabled subtitle instead; enabled=False also blocks a second launch.
        enabled=lambda: not self._scanning(),
        disabled_label=tr_noop("Scanning drive logs... the report opens automatically when it finishes."),
        on_click=self._on_tune_report_scan,
      ),
      SettingRow(
        "TuneReportView", "action", tr_noop("View Tune Report"),
        subtitle=tr_noop("Show the report from the last scan."),
        action_text=tr_noop("VIEW"),
        on_click=self._show_tune_report,
      ),
      SettingRow(
        "TuneReportDelete", "action", tr_noop("Delete Dashcam Media"),
        subtitle=tr_noop("Permanently wipe every recorded drive in /data/media/0. This cannot be undone."),
        action_text=tr_noop("DELETE"),
        action_danger=True,
        on_click=self._on_tune_report_delete,
      ),
    ]

    lateral_sections = [
      SettingSection(title=tr_noop("Tune Report"), rows=tune_report_rows),
      *pid_sections,
      SettingSection(title=tr_noop("Live Parameters / Auto Tuning"), rows=learning_rows),
      SettingSection(title=tr_noop("Center / Unwind"), rows=center_rows),
      SettingSection(title=tr_noop("Lateral Stiction"), rows=stiction_rows),
      SettingSection(title=tr_noop("Driver Override"), rows=override_rows),
      SettingSection(title=tr_noop("Filters / Limits"), rows=filter_rows),
    ]

    long_control_rows = [
      toggle("NrdrHondaEcuMatchedLong", "Nidec ECU-Matched Long", "Shape Honda gas and brake commands closer to the stock Nidec ECU."),
      toggle("HondaLiveLearningGas", "Live Learning Gas", "Adapt Honda gas and wind compensation factors while driving."),
      value(
        "HondaStoppingDecelRate", "Honda Stopping Decel Rate", "Brake command rate used by Honda carcontroller while stopping.",
        lambda: f"{p.get_int('HondaStoppingDecelRate')}%",
        lambda: self._show_slider("HondaStoppingDecelRate", 0, 100, unit="%", title="Honda Stopping Decel Rate"),
      ),
    ]
    long_pid_rows = [
      value(
        "LongPidTuneScale", "Longitudinal PID Tune Scale", "Scale Honda longitudinal PID output. 100% preserves the base tune.",
        lambda: f"{p.get_int('LongPidTuneScale')}%",
        lambda: self._show_slider("LongPidTuneScale", 0, 500, step=5, unit="%", title="Longitudinal PID Tune Scale"),
      ),
      toggle("StaticFeedforwardLong", "Keep Feedforward Static", "Apply the PID scale only to feedback while preserving feedforward."),
    ]
    stopping_rows = [
      value(
        "HondaStopAccel", "Stop Accel", "Target acceleration once stopped. More negative values hold the brake more firmly.",
        lambda: f"{p.get_float('HondaStopAccel'):.2f} m/s2",
        lambda: self._show_slider("HondaStopAccel", -4.0, 0.0, step=0.01, unit=" m/s2", value_type="float", title="Stop Accel"),
      ),
      value(
        "HondaStoppingDecelRateLong", "Planner Stopping Rate", "Rate at which commanded deceleration ramps while stopping.",
        lambda: f"{p.get_float('HondaStoppingDecelRateLong'):.2f} m/s2",
        lambda: self._show_slider("HondaStoppingDecelRateLong", 0.0, 5.0, step=0.01, unit=" m/s2", value_type="float", title="Planner Stopping Rate"),
      ),
      value(
        "HondaVEgoStopping", "Stop Speed", "Speed below which Honda longcontrol treats the car as stopping.",
        lambda: f"{p.get_float('HondaVEgoStopping'):.2f} m/s",
        lambda: self._show_slider("HondaVEgoStopping", 0.0, 3.0, step=0.01, unit=" m/s", value_type="float", title="Stop Speed"),
      ),
      value(
        "HondaVEgoStarting", "Start Speed", "Speed above which Honda longcontrol treats the car as moving again.",
        lambda: f"{p.get_float('HondaVEgoStarting'):.2f} m/s",
        lambda: self._show_slider("HondaVEgoStarting", 0.0, 3.0, step=0.01, unit=" m/s", value_type="float", title="Start Speed"),
      ),
    ]

    self._manager_view = NRDRManagerView(self)
    self._sub_panels["lateral"] = AetherSettingsView(
      self,
      lateral_sections,
      header_title=tr_noop("NRDR Lateral"),
      header_subtitle=tr_noop("Clarity EPS tuning, driver override, filtering, and online learning."),
      panel_style=PANEL_STYLE,
    )
    self._sub_panels["longitudinal"] = AetherSettingsView(
      self,
      [
        SettingSection(title=tr_noop("Honda Nidec Control"), rows=long_control_rows),
        SettingSection(title=tr_noop("Longitudinal PID"), rows=long_pid_rows),
        SettingSection(title=tr_noop("Stopping"), rows=stopping_rows),
      ],
      header_title=tr_noop("NRDR Long"),
      header_subtitle=tr_noop("Honda Nidec gas, brake, stopping, and PID tuning."),
      panel_style=PANEL_STYLE,
    )
    self._wire_sub_panels()

  def navigate_back(self):
    self._go_back()
