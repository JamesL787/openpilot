"""NRDR Honda EPS Tuning Layout - Speed-dependent PID and EPS parameters only"""

from __future__ import annotations
from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from openpilot.selfdrive.ui.layouts.settings.starpilot.lateral import SteeringManagerView


class NRDRTuningLayout(SteeringManagerView):
  """Tuning panel focused only on NRDR Honda EPS parameters"""

  def _build_left_sections(self) -> list[dict]:
    p = self._controller._params
    sections: list[dict] = []

    def value_row(key: str, title: str, subtitle: str, get_value, pill_width: int = 120) -> dict:
      return {
        "target_id": f"select:{key}",
        "title": tr(title),
        "subtitle": tr(subtitle),
        "get_value": get_value,
        "pill_width": pill_width,
      }

    # Angle PID tuning - speed-dependent gains grouped by speed range
    low_speed_rows = [
      value_row("LatPScaleLowSpeed", "Kp", "Proportional gain. 100 = stock.", lambda: f"{p.get_int('LatPScaleLowSpeed')}%", 120),
      value_row("LatIScaleLowSpeed", "Ki", "Integral gain. 100 = stock.", lambda: f"{p.get_int('LatIScaleLowSpeed')}%", 120),
      value_row("LatFScaleLowSpeed", "Feedforward", "Feedforward gain. 100 = stock.", lambda: f"{p.get_int('LatFScaleLowSpeed')}%", 120),
    ]
    sections.append({
      "title": tr("Low Speed PID (0-25 mph)"),
      "rows": low_speed_rows,
      "visible": True,
      "height": self._section_block_height(self._section_height(len(low_speed_rows), self.ROW_HEIGHT)),
    })

    standard_rows = [
      value_row("LatPScaleStandard", "Kp", "Proportional gain. 100 = stock.", lambda: f"{p.get_int('LatPScaleStandard')}%", 120),
      value_row("LatIScaleStandard", "Ki", "Integral gain. 100 = stock.", lambda: f"{p.get_int('LatIScaleStandard')}%", 120),
      value_row("LatFScaleStandard", "Feedforward", "Feedforward gain. 100 = stock.", lambda: f"{p.get_int('LatFScaleStandard')}%", 120),
    ]
    sections.append({
      "title": tr("Standard Speed PID (26-49 mph)"),
      "rows": standard_rows,
      "visible": True,
      "height": self._section_block_height(self._section_height(len(standard_rows), self.ROW_HEIGHT)),
    })

    highway_rows = [
      value_row("LatPScaleHighway", "Kp", "Proportional gain. 100 = stock.", lambda: f"{p.get_int('LatPScaleHighway')}%", 120),
      value_row("LatIScaleHighway", "Ki", "Integral gain. 100 = stock.", lambda: f"{p.get_int('LatIScaleHighway')}%", 120),
      value_row("LatFScaleHighway", "Feedforward", "Feedforward gain. 100 = stock.", lambda: f"{p.get_int('LatFScaleHighway')}%", 120),
    ]
    sections.append({
      "title": tr("Highway Speed PID (50+ mph)"),
      "rows": highway_rows,
      "visible": True,
      "height": self._section_block_height(self._section_height(len(highway_rows), self.ROW_HEIGHT)),
    })

    # Honda EPS tuning sections
    honda_rows = [
      value_row("HondaCenterBoostThreshold", "Center Boost Angle", "Angle band where center boost and straight-line override tuning apply.", lambda: f"{p.get_float('HondaCenterBoostThreshold'):.1f} deg", 140),
      value_row("HondaCenterBoostMinSpeed", "Center Boost Min Speed", "Disable center boost below this speed to avoid low-speed center oscillation.", lambda: f"{p.get_int('HondaCenterBoostMinSpeed')} mph", 140),
      value_row("HondaCenterScale", "Center Scale", "Feedforward scale near center. Lower values reduce torque through straight unwind.", lambda: f"{p.get_float('HondaCenterScale'):.2f}", 120),
      {"target_id": f"select:HondaUnwindFreeze", "title": tr("Unwind Integrator Freeze"), "subtitle": tr("Freeze the PID integrator while steering naturally returns toward center."), "get_value": lambda: tr("On") if p.get_bool("HondaUnwindFreeze") else tr("Off")},
      {"target_id": f"select:HondaUnwindLookahead", "title": tr("Unwind Lookahead"), "subtitle": tr("Use model path lookahead to start unwind behavior earlier."), "get_value": lambda: tr("On") if p.get_bool("HondaUnwindLookahead") else tr("Off")},
      value_row("HondaUnwindBoostSeconds", "Unwind Boost Duration", "How long the low-speed unwind feedforward boost is held.", lambda: f"{p.get_float('HondaUnwindBoostSeconds'):.1f}s", 120),
      value_row("HondaUnwindFfMultiplier", "Unwind FF Multiplier", "Peak low-speed feedforward multiplier during unwind.", lambda: f"{p.get_float('HondaUnwindFfMultiplier'):.1f}x", 120),
    ]
    sections.append({
      "title": tr("NRDR Honda EPS: Center / Unwind"),
      "rows": honda_rows,
      "visible": True,
      "height": self._section_block_height(self._section_height(len(honda_rows), self.ROW_HEIGHT)),
    })

    override_rows = [
      {"target_id": f"select:NrdrIncreaseOverrideTolerance", "title": tr("Override Hysteresis"), "subtitle": tr("Raise driver override tolerance on sensitive Honda EPS torque sensors."), "get_value": lambda: tr("On") if p.get_bool("NrdrIncreaseOverrideTolerance") else tr("Off")},
      value_row("NrdrDriverOverrideThreshold", "Driver Override Threshold", "Raw torque-sensor threshold for driver steering. 1200 is stock Honda scale.", lambda: f"{p.get_int('NrdrDriverOverrideThreshold')}", 130),
      value_row("NrdrOverrideThresholdCenterBoost", "Center Override Threshold", "Override threshold used inside the center boost angle band.", lambda: f"{p.get_int('NrdrOverrideThresholdCenterBoost')}", 130),
      {"target_id": f"select:HondaDriverAssistDuringOverride", "title": tr("Assist During Override"), "subtitle": tr("Keep pass-through steering assist while the driver is applying torque."), "get_value": lambda: tr("On") if p.get_bool("HondaDriverAssistDuringOverride") else tr("Off")},
      value_row("HondaOverrideFadeUpSecs", "Override Fade Up", "Time to ramp controller authority back in after driver override.", lambda: f"{p.get_float('HondaOverrideFadeUpSecs'):.1f}s", 120),
      value_row("HondaOverrideFadeDownSecs", "Override Fade Down", "Time to ramp controller authority down during driver override.", lambda: f"{p.get_float('HondaOverrideFadeDownSecs'):.1f}s", 120),
      value_row("HondaOverrideTorqueScale", "Override Torque Scale", "Percent of controller torque retained during driver override.", lambda: f"{p.get_int('HondaOverrideTorqueScale')}%", 120),
    ]
    sections.append({
      "title": tr("NRDR Honda EPS: Override"),
      "rows": override_rows,
      "visible": True,
      "height": self._section_block_height(self._section_height(len(override_rows), self.ROW_HEIGHT)),
    })

    filter_rows = [
      {"target_id": f"select:HondaTorqueLowPassFilter", "title": tr("Torque Low Pass Filter"), "subtitle": tr("Smooth steering torque with speed-banded tau values."), "get_value": lambda: tr("On") if p.get_bool("HondaTorqueLowPassFilter") else tr("Off")},
    ]
    if p.get_bool("HondaTorqueLowPassFilter"):
      filter_rows.extend([
        value_row("HondaLpfTauLowSpeed", "LPF Tau: Low Speed", "Low-pass tau below 25 mph.", lambda: f"{p.get_float('HondaLpfTauLowSpeed'):.2f}", 120),
        value_row("HondaLpfTauStandard", "LPF Tau: Standard", "Low-pass tau from 25 to 50 mph.", lambda: f"{p.get_float('HondaLpfTauStandard'):.2f}", 120),
        value_row("HondaLpfTauHighway", "LPF Tau: Highway", "Low-pass tau above 50 mph.", lambda: f"{p.get_float('HondaLpfTauHighway'):.2f}", 120),
      ])
    filter_rows.append({"target_id": f"select:HondaNotchEnabled", "title": tr("Notch Filter"), "subtitle": tr("Remove a narrow EPS chatter band without broad low-pass lag."), "get_value": lambda: tr("On") if p.get_bool("HondaNotchEnabled") else tr("Off")})
    if p.get_bool("HondaNotchEnabled"):
      filter_rows.extend([
        value_row("HondaNotchFreq", "Notch Frequency", "Frequency removed from the torque command.", lambda: f"{p.get_float('HondaNotchFreq'):.1f} Hz", 140),
        value_row("HondaNotchQ", "Notch Q", "Width of the removed frequency band. Higher is narrower.", lambda: f"{p.get_float('HondaNotchQ'):.2f}", 120),
      ])
    filter_rows.append({"target_id": f"select:HondaSteerDeltaLimiter", "title": tr("Steer Delta Limiter"), "subtitle": tr("Legacy torque rate limiter. Usually leave off unless testing."), "get_value": lambda: tr("On") if p.get_bool("HondaSteerDeltaLimiter") else tr("Off")})
    if p.get_bool("HondaSteerDeltaLimiter"):
      filter_rows.extend([
        value_row("HondaSteerDeltaUp", "Steer Delta Up", "Maximum upward steering torque rate.", lambda: f"{p.get_float('HondaSteerDeltaUp'):.1f}", 120),
        value_row("HondaSteerDeltaDown", "Steer Delta Down", "Maximum downward steering torque rate.", lambda: f"{p.get_float('HondaSteerDeltaDown'):.1f}", 120),
      ])
    filter_rows.append(value_row("NrdrMinSteerSpeed", "Minimum Steer Speed", "Below this speed no steering torque is commanded. 0 means stock.", lambda: f"{p.get_int('NrdrMinSteerSpeed')} mph", 140))
    sections.append({
      "title": tr("NRDR Honda EPS: Filters / Limits"),
      "rows": filter_rows,
      "visible": True,
      "height": self._section_block_height(self._section_height(len(filter_rows), self.ROW_HEIGHT)),
    })

    return sections
