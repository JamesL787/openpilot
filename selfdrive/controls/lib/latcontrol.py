import capnp
import numpy as np
from abc import abstractmethod, ABC
from types import SimpleNamespace

from openpilot.selfdrive.locationd.helpers import Pose


def integrator_wind_blocked(requested: float, applied: float, rel_threshold: float) -> bool:
  """Is the actuator genuinely prevented from following us, or is this just intentional shaping?

  controlsd's `abs(requested - applied) > 1e-2` cannot tell the two apart. On a Honda whose
  carcontroller low-pass filters and ramps the command on purpose, that absolute test is true on
  ~99% of frames and starves the integrator (measured 80% of steady-turn frames frozen).

  A RELATIVE test separates them cleanly. Measured over 67k logged frames on a modified-EPS
  Civic Bosch, |requested-applied|/|requested| is:
      steady turns (LPF phase lag) : p50 0.12  p75 0.23  p90 0.44
      first 0.3 s of override fade : p50 0.92  p75 0.98  p90 1.00
  At a 0.30 threshold that is 18% of steady-turn frames against 100% of early-fade frames.

  The sign term catches a reversal, where the actuator is moving opposite to the request.

  rel_threshold <= 0 disables the relative test and restores the legacy absolute behaviour.
  """
  gap = abs(requested - applied)
  if rel_threshold <= 0.0:
    return gap > 1e-2
  if requested * applied < 0.0:
    return True
  return gap > max(1e-2, rel_threshold * abs(requested))


class LatControl(ABC):
  def __init__(self, CP, CI, dt):
    self.dt = dt
    self.sat_limit = CP.steerLimitTimer
    self.sat_time = 0.
    self.sat_check_min_speed = 10.

    # we define the steer torque scale as [-1.0...1.0]
    self.steer_max = 1.0

  @abstractmethod
  def update(self, active: bool, CS, VM, params, steer_limited_by_safety: bool, desired_curvature: float, curvature_limited: bool, lat_delay: float, calibrated_pose: Pose, model_data: capnp._DynamicStructReader, starpilot_toggles: SimpleNamespace):
    pass

  def reset(self):
    self.sat_time = 0.

  def _check_saturation(self, saturated, CS, steer_limited_by_safety, curvature_limited):
    # Saturated only if control output is not being limited by car torque/angle rate limits
    if (saturated or curvature_limited) and CS.vEgo > self.sat_check_min_speed and not steer_limited_by_safety and not CS.steeringPressed:
      self.sat_time += self.dt
    else:
      self.sat_time -= self.dt
    self.sat_time = np.clip(self.sat_time, 0.0, self.sat_limit)
    return self.sat_time > (self.sat_limit - 1e-3)
