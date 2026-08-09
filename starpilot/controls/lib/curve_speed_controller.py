#!/usr/bin/env python3
import numpy as np

from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL

from openpilot.starpilot.common.starpilot_variables import CITY_SPEED_LIMIT, DEFAULT_LATERAL_ACCELERATION

CSC_MIN_SPEED = CITY_SPEED_LIMIT * CV.MPH_TO_MS
CSC_MAX_DECEL_RATE = 1.5

# Static lateral-accel target, m/s^2. The settings slider spans LAT_ACCEL_MIN..LAT_ACCEL_MAX
# in 0.1 steps; the clamp here is the defense against a hand-edited param.
LAT_ACCEL_PARAM = "CurveSpeedLateralAccel"
LAT_ACCEL_MIN = 1.5
LAT_ACCEL_MAX = 3.0

# Re-read the param about once a second; log_data() runs at DT_MDL whenever CSC is not
# actively holding a curve target, so this is the cheap place to pick up live edits.
PARAM_REFRESH_FRAMES = int(round(1.0 / DT_MDL))


class CurveSpeedController:
  def __init__(self, StarPilotVCruise):
    self.starpilot_planner = StarPilotVCruise.starpilot_planner

    # Retained for the cscTraining field starpilot_planner publishes. The controller no
    # longer learns, so it is permanently False.
    self.enable_training = False
    self.target_set = False
    self.target = 0.0

    self._frame = 0
    self.lateral_acceleration = DEFAULT_LATERAL_ACCELERATION
    self.update_lateral_acceleration()

  def update_lateral_acceleration(self):
    """Read the static lateral-accel target from params, clamped to the slider's range."""
    try:
      raw = self.starpilot_planner.params.get_float(LAT_ACCEL_PARAM)
    except Exception:
      raw = None

    value = DEFAULT_LATERAL_ACCELERATION if raw is None else float(raw)

    if not np.isfinite(value):
      value = DEFAULT_LATERAL_ACCELERATION

    self.lateral_acceleration = float(np.clip(value, LAT_ACCEL_MIN, LAT_ACCEL_MAX))

  def log_data(self, v_ego, sm):
    """No learning. Kept as the periodic refresh hook so slider edits apply without a restart."""
    self.enable_training = False

    self._frame += 1
    if self._frame % PARAM_REFRESH_FRAMES == 0:
      self.update_lateral_acceleration()

  def update_target(self, v_ego):
    lateral_acceleration = self.lateral_acceleration
    if self.starpilot_planner.starpilot_weather.weather_id != 0:
      lateral_acceleration -= self.lateral_acceleration * self.starpilot_planner.starpilot_weather.reduce_lateral_acceleration

    if self.target_set:
      csc_speed = (lateral_acceleration / abs(self.starpilot_planner.road_curvature))**0.5
      csc_speed = max(float(csc_speed), CSC_MIN_SPEED)
      if csc_speed >= v_ego:
        self.target = v_ego
      else:
        time_to_curve = max(float(self.starpilot_planner.time_to_curve), DT_MDL)
        decel_rate = float(np.clip((v_ego - csc_speed) / time_to_curve, 0.0, CSC_MAX_DECEL_RATE))
        self.target = float(np.clip(self.target - decel_rate * DT_MDL, csc_speed, v_ego))
    else:
      self.target_set = True
      self.target = v_ego
