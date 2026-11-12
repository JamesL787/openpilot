"""How much of its command the lateral controller should keep while the driver is steering against it. SHADOW: the
controller computes and logs this (starpilotLateralState.epsYield*), and nothing applies it.

Today a press is one sample of |steeringTorque| over a threshold: torque is cut to zero and faded back in. A driver
holding the wheel a little off the target sits at that threshold, so each cut drops their torque under it, the fade
brings it back and they cross again: 68-77% of the presses on two CR-Vs (2026-11) are re-presses within 1.5 s.

This keeps a leaky total of the driver's torque AGAINST the controller instead, and gives authority up in proportion:
  driver = steeringTorque - sensor offset - the EPS's own share of the reading - wheel inertia
  against = driver torque opposing the way the controller wants to move the wheel, beyond a resting hand's
  evidence += (against - evidence / LEAK_S) * dt             (count-seconds)
  authority = 1 up to YIELD_START, 0 from YIELD_FULL, and back at RETURN_PER_S once the evidence has gone
A hard yank (YANK counts) yields at once, in either direction. Torque with the controller is not an override.

The sensor terms are per car, from the car learner's torque-sensor model (honda_eps_car_learner.TorqueSensorModel); a
car nobody has measured takes the defaults. Only numpy-free arithmetic here, so the replay tool
(tools/lateral/driver_yield_replay.py) runs exactly this code over a log.
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TorqueSensor:
  """steeringTorque with nobody on the wheel: offset + eps_share * firmware output + inertia * wheel acceleration."""
  offset: float      # counts
  eps_share: float   # counts per count of firmware output
  inertia: float     # counts per deg/s^2


# Both CR-Vs' eps_share and inertia; the offset is a unit's own and its sign is not known in advance.
TORQUE_SENSOR_DEFAULT = TorqueSensor(offset=0.0, eps_share=0.13, inertia=-0.6)
# Measured hands off (no reading over 400 counts within 1.5 s): 59 min of the A040's routes 02-0b, 19 min of the A220's.
# The reading's rms falls from 81 / 75 to 49 / 44 counts once these are taken out.
TORQUE_SENSOR_BY_CALIBRATION = {
  "crv_tla_a040": TorqueSensor(offset=124.0, eps_share=0.130, inertia=-0.59),
  "crv_tla_a220": TorqueSensor(offset=90.0, eps_share=0.122, inertia=-0.70),
}

# First values, from two drivers of one car model; the shadow drives are for checking them.
# A resting hand: away from any cut, with the wheel moving toward the target, the driver torque against the controller
# is 100-140 counts at the 90th percentile at every wheel speed on both cars, and no hands-off frame passes 220.
DEADBAND = 400.0       # counts
DRAG = 3.0             # counts per deg/s of wheel speed
ERROR_MIN = 0.7        # deg: closer to the target than this the controller wants nothing, so nothing opposes it
LEAK_S = 0.7           # s
YIELD_START = 150.0    # count-seconds
YIELD_FULL = 450.0
YANK = 2400.0          # counts: past this the driver has the wheel now
RETURN_PER_S = 1.0     # authority per second coming back
ACCEL_TAU = 0.03       # s, on the frame-to-frame steering rate


def torque_sensor(calibration_name: str) -> TorqueSensor:
  return TORQUE_SENSOR_BY_CALIBRATION.get(calibration_name, TORQUE_SENSOR_DEFAULT)


class DriverYield:
  def __init__(self, dt: float, sensor: TorqueSensor = TORQUE_SENSOR_DEFAULT):
    self.dt = dt
    self.sensor = sensor
    self.accel_alpha = dt / (ACCEL_TAU + dt)
    self.reset()

  def reset(self):
    self.prev_rate: float | None = None
    self.accel = 0.0
    self.driver_torque = 0.0
    self.evidence = 0.0
    self.authority = 1.0

  def measure(self, steering_torque: float, firmware_output: float, rate_deg_s: float) -> float:
    """The driver's torque (counts, positive turns the wheel toward positive angles). Run every frame, engaged or not."""
    if self.prev_rate is not None:
      self.accel += self.accel_alpha * ((rate_deg_s - self.prev_rate) / self.dt - self.accel)
    self.prev_rate = rate_deg_s
    s = self.sensor
    self.driver_torque = steering_torque - s.offset - s.eps_share * firmware_output - s.inertia * self.accel
    return self.driver_torque

  def update(self, angle_error_deg: float, rate_deg_s: float) -> float:
    """Authority (0..1) for the driver torque just measured. angle_error_deg: desired - measured wheel angle."""
    drag = DRAG * abs(rate_deg_s)
    against = 0.0
    if abs(angle_error_deg) > ERROR_MIN:
      against = max(0.0, -self.driver_torque * math.copysign(1.0, angle_error_deg) - DEADBAND - drag)
    self.evidence = max(0.0, self.evidence + (against - self.evidence / LEAK_S) * self.dt)
    if abs(self.driver_torque) - drag > YANK:
      self.evidence = max(self.evidence, YIELD_FULL)
    target = 1.0 - min(max((self.evidence - YIELD_START) / (YIELD_FULL - YIELD_START), 0.0), 1.0)
    self.authority = min(target, self.authority + RETURN_PER_S * self.dt)
    return self.authority
