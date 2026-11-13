"""How much of its command the lateral controller should keep while the driver is steering against it. SHADOW: the
controller computes and logs this (starpilotLateralState.epsYield*), and nothing applies it.

Today a press is one sample of |steeringTorque| over a threshold: torque is cut to zero and faded back in. A driver
holding the wheel a little off the target sits at that threshold, so each cut drops their torque under it, the fade
brings it back and they cross again: 68-77% of the presses on two CR-Vs (2026-11) are re-presses within 1.5 s.

The reading is not only the driver. The sensor is a torsion bar under the steering wheel and the EPS motor is below
it, so the bar carries whatever it takes to move the wheel and the column above it, whoever moves them:
  reading = driver + offset + inertia * wheel acceleration + friction * memory + imbalance * sin(wheel angle)
  memory: -1..1, the way the wheel last moved (a stop over FRICTION_WIDTH deg); the column stays twisted that way at rest
Nothing in it is the EPS command or its firmware, so it needs no EPS calibration and holds for any Honda. The EPS jerking
a free wheel reads through the inertia term: on six cars (47-372 engaged min each) that term alone passes the stock
1200 threshold 93 times, 88 of them within 1.5 s after a press ended (the cut and fade make most of it).

This keeps a leaky total of the driver's torque AGAINST the controller, and gives authority up in proportion:
  against = driver torque opposing the way the controller wants to move the wheel, beyond a resting hand's
  evidence += (against - evidence / LEAK_S) * dt             (count-seconds)
  authority = 1 up to YIELD_START, 0 from YIELD_FULL, and back at RETURN_PER_S once the evidence has gone
A hard yank (YANK counts) yields at once, in either direction. Torque with the controller is not an override.

Only numpy-free arithmetic here, so the replay tool (tools/lateral/driver_yield_replay.py) and the car learner's
sensor fit (honda_eps_car_learner.TorqueSensorModel) run exactly this code.
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TorqueSensor:
  """steeringTorque with nobody on the wheel: offset + inertia * accel + friction * memory + imbalance * sin(angle)."""
  offset: float      # counts
  inertia: float     # counts per deg/s^2 of wheel acceleration
  friction: float    # counts, the column above the bar
  imbalance: float   # counts at 90 deg of wheel


# The six fitted cars' middle; an offset is a unit's own (the two CR-Vs: +121 and +84).
TORQUE_SENSOR_DEFAULT = TorqueSensor(offset=0.0, inertia=-0.25, friction=-70.0, imbalance=-170.0)
# Fitted (Huber) with the filter below over frames with quiet readings (under 350 counts) 0.5-3 s to either side and
# nothing selected between. Inertia from the 100-300 deg/s^2 frames where a car has a minute of them. R^2 over quiet
# frames 0.68-0.84 on the first six (rms 61-115 -> 33-53 counts); the Ridgeline's quiet reading is 45 counts rms to
# begin with. Not fitted: the RDX (logs of a shaking wheel) and the C020 (10 min).
TORQUE_SENSOR_BY_CALIBRATION = {
  "clarity_trw_a020": TorqueSensor(offset=-54.0, inertia=-0.20, friction=-91.0, imbalance=-127.0),     # 245 min
  "crv_tla_a040": TorqueSensor(offset=121.0, inertia=-0.26, friction=-65.0, imbalance=-203.0),         # 59 min
  "crv_tla_a220": TorqueSensor(offset=84.0, inertia=-0.21, friction=-56.0, imbalance=-197.0),          # 35 min
  "civic_tgg_a120": TorqueSensor(offset=20.0, inertia=-0.20, friction=-107.0, imbalance=-209.0),       # 72 min
  "civic_teg_a010": TorqueSensor(offset=-117.0, inertia=-0.26, friction=-91.0, imbalance=-157.0),      # 84 min
  "insight_txm_a040": TorqueSensor(offset=60.0, inertia=-0.24, friction=-50.0, imbalance=-160.0),      # 65 min
  "ridgeline_t6z_a110": TorqueSensor(offset=-92.0, inertia=-0.28, friction=-10.0, imbalance=-22.0),    # 14 min
}

FILTER_TAU = 0.03       # s, on the reading, the memory and the frame-to-frame steering rate
FRICTION_WIDTH = 0.1    # deg of wheel travel that turns the column's friction around

# First values, from two drivers of one car model; the shadow drives are for checking them.
# What the sensor model leaves of a quiet reading is under 150 counts 99% of the time on the six cars, under 300 99.9%.
DEADBAND = 400.0       # counts
DRAG = 3.0             # counts per deg/s of wheel speed: a hand carried along by the wheel
ERROR_MIN = 0.7        # deg: closer to the target than this the controller wants nothing, so nothing opposes it
LEAK_S = 0.7           # s
YIELD_START = 150.0    # count-seconds
YIELD_FULL = 450.0
YANK = 2400.0          # counts: past this the driver has the wheel now
RETURN_PER_S = 1.0     # authority per second coming back


def torque_sensor(calibration_name: str) -> TorqueSensor:
  return TORQUE_SENSOR_BY_CALIBRATION.get(calibration_name, TORQUE_SENSOR_DEFAULT)


class DriverYield:
  def __init__(self, dt: float, sensor: TorqueSensor = TORQUE_SENSOR_DEFAULT):
    self.dt = dt
    self.sensor = sensor
    self.alpha = dt / (FILTER_TAU + dt)
    self.prev_rate: float | None = None
    self.accel = 0.0
    self.stop = 0.0
    self.reading = 0.0
    self.memory = 0.0
    self.held = (0.0, 0.0, 0.0)   # last frame's reading, memory and sin(angle): the acceleration is a frame behind them
    self.wheel_torque = 0.0    # what moving the wheel put on the bar
    self.driver_torque = 0.0
    self.reset()

  def reset(self):
    """The yield starts over. The sensor's filters and the friction memory keep running: the wheel does not reset."""
    self.evidence = 0.0
    self.authority = 1.0

  def terms(self, steering_torque: float, angle_deg: float, rate_deg_s: float) -> tuple[float, float, float, float]:
    """(reading, wheel acceleration, friction memory, sin(wheel angle)), filtered and lined up in time. angle_deg is
    the wheel angle from straight ahead (steeringAngleDeg less the learned offset)."""
    if self.prev_rate is None:
      self.prev_rate, self.reading = rate_deg_s, steering_torque
      self.held = (steering_torque, 0.0, math.sin(math.radians(angle_deg)))
    self.accel += self.alpha * ((rate_deg_s - self.prev_rate) / self.dt - self.accel)
    self.prev_rate = rate_deg_s
    out = (self.held[0], self.accel, self.held[1], self.held[2])
    self.stop = min(max(self.stop + rate_deg_s * self.dt / FRICTION_WIDTH, -1.0), 1.0)
    self.reading += self.alpha * (steering_torque - self.reading)
    self.memory += self.alpha * (self.stop - self.memory)
    self.held = (self.reading, self.memory, math.sin(math.radians(angle_deg)))
    return out

  def measure(self, steering_torque: float, angle_deg: float, rate_deg_s: float) -> float:
    """The driver's torque (counts, positive turns the wheel toward positive angles). Run every frame, engaged or not."""
    reading, accel, memory, sin_angle = self.terms(steering_torque, angle_deg, rate_deg_s)
    s = self.sensor
    self.wheel_torque = s.inertia * accel + s.friction * memory + s.imbalance * sin_angle
    self.driver_torque = reading - s.offset - self.wheel_torque
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
