"""Modified-EPS Honda steering in the car controller (from vfn), for every Honda on a recognized modified EPS.

Kept free of openpilot settings: openpilot attaches a source of ModifiedEpsSettings (starpilot/car/honda/modified_eps.py)
to the car controller and car state; without one the defaults below apply.

INVARIANT: every stage here may only reduce the command because the car genuinely cannot deliver it -- below the
minimum steer speed, cut for a driver override, or held back by the opt-in steer-delta limiter. controlsd turns any
difference between CC.actuators.torque and what is sent into steer_limited_by_safety, which freezes the lateral
integrator, so comfort shaping (the output low-pass) lives in the lateral controller, never here.
"""
from dataclasses import dataclass

from opendbc.car import DT_CTRL, rate_limit
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.honda.values import HondaFlags, STEER_THRESHOLD

STOCK_STEER_THRESHOLD = 1200


@dataclass(frozen=True)
class ModifiedEpsSettings:
  override_threshold: int = 2000         # HondaDriverOverrideThreshold, driver torque for steeringPressed (stock 1200)
  min_steer_speed_mph: int = 1           # HondaMinSteerSpeed, no torque below this
  fade_down_s: float = 0.0               # HondaOverrideFadeDownSecs, soft cut on a press, request held while it eases out (0 = cut at once)
  fade_up_s: float = 0.5                 # HondaOverrideFadeUpSecs, torque fade back in after a press
  torque_scale: float = 0.0              # HondaOverrideTorqueScale / 100, torque kept while pressed
  assist_during_override: bool = False   # HondaDriverAssistDuringOverride, keep LKAS active while pressed
  delta_limiter: bool = False            # HondaSteerDeltaLimiter, the stock steer rate limit, opt-in
  delta_up: float = 3.0                  # HondaSteerDeltaUp, per second of the normalized command
  delta_down: float = 3.0                # HondaSteerDeltaDown
  angle_cap3: bool = False               # HondaClarityAngleCap3, Clarity angle mode: prefer mode 4 (3.0 m/s^2) on build 0x05
  angle_rate_limit_deg_s: float = 300.0  # HondaEpsAngleRateLimit, Clarity angle mode: cap on the target's rate in CarController (0 = off)


DEFAULT_SETTINGS = ModifiedEpsSettings()


def modified_eps(CP) -> bool:
  return (CP.brand == "honda" and bool(CP.flags & HondaFlags.EPS_MODIFIED) and
          not CP.passive and not CP.dashcamOnly and not CP.notCar)


def current_settings(source) -> ModifiedEpsSettings:
  return source.current() if source is not None else DEFAULT_SETTINGS


def steering_pressed_threshold(CP, override_threshold: int) -> float:
  # A modified EPS pushes column torque of its own, which trips the stock threshold. The setting is in stock-1200 units;
  # a car whose stock threshold differs scales it.
  stock = STEER_THRESHOLD.get(CP.carFingerprint, STOCK_STEER_THRESHOLD)
  if override_threshold <= 0:
    return stock
  return override_threshold if stock == STOCK_STEER_THRESHOLD else stock * override_threshold / STOCK_STEER_THRESHOLD


def lane_change_nudge_torque(CP) -> float | None:
  # With steeringPressed raised on a modified EPS, a lane-change nudge still counts at the car's stock threshold.
  return STEER_THRESHOLD.get(CP.carFingerprint, STOCK_STEER_THRESHOLD) if modified_eps(CP) else None


# A press starts over the threshold and ends once the torque has stayed under RELEASE_FRACTION of it for RELEASE_HOLD_S.
# With one level the press flickered: the cut takes away the torque the driver leans on, their reading drops under the
# line, the fade brings it back and they cross again (2026-11 logs, 7 cars: 58-79% of presses within 1.5 s of the last).
# The hold is 0.1 s: 0.3 s kept openpilot off ~0.3 s after the driver let go (Clarity 11-15: 0.29 s, then the 0.5 s
# fade), and on the CR-V A220's recorded torque 0.1 s cut the re-presses within 1.5 s as far as 0.15 s did.
RELEASE_FRACTION = 0.6
RELEASE_HOLD_S = 0.1


class SteeringPressedHysteresis:
  def __init__(self):
    self.pressed = False
    self.below_s = 0.0

  def update(self, steering_torque: float, threshold: float) -> bool:
    if not self.pressed:
      self.pressed = abs(steering_torque) > threshold
      self.below_s = 0.0
    else:
      self.below_s = self.below_s + DT_CTRL if abs(steering_torque) < RELEASE_FRACTION * threshold else 0.0
      self.pressed = self.below_s < RELEASE_HOLD_S - 1e-6
    return self.pressed


def get_eps_modified_steering_pressed(
  raw_pressed: bool, steering_torque: float, torque_cmd: float, filter_s: float, previous_pressed: bool
) -> tuple[float, bool]:
  # carstate's steeringPressed (SteeringPressedHysteresis) is the press. The 0.28 s hold this used to add on a press
  # along the command guarded the wrong side: the EPS's own column torque reads against its command 60-85% of the time.
  return 0.0, bool(raw_pressed)


class ModifiedEpsSteering:
  def __init__(self):
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_prev = False
    self.override_ramp = 1.0
    self.lat_active_prev = False
    self.last_torque = 0.0

  def update(self, CC, CS, settings: ModifiedEpsSettings) -> tuple[float, bool, bool]:
    """Returns (torque to send, LKAS active, filtered steering pressed)."""
    torque_cmd = float(CC.actuators.torque) if CC.latActive else 0.0
    steering_pressed = False
    releasing = False
    below_min_steer_speed = CS.out.vEgo < settings.min_steer_speed_mph * CV.MPH_TO_MS
    if below_min_steer_speed:
      torque_cmd = 0.0

    if CC.latActive:
      # The same press detector as the modified-EPS lateral controllers, so the actuator never fades on a press the
      # controller does not see (false safety limiting and integrator-freeze churn).
      self.steering_pressed_filter_s, steering_pressed = get_eps_modified_steering_pressed(
        bool(CS.out.steeringPressed), float(CS.out.steeringTorque), torque_cmd,
        self.steering_pressed_filter_s, self.steering_pressed_prev)
      self.steering_pressed_prev = steering_pressed

      if not self.lat_active_prev:
        self.override_ramp = 0.0
      if steering_pressed and settings.fade_down_s > 0.0:
        # Soft cut: ease the torque out with the LKAS request still on, then drop it. A step to 0 jerked the wheel
        # (2.6-49 deg in 0.3 s after a press), and the EPS already fades our torque itself as the driver's rises. The
        # request is not held for the whole press: with it on the firmware damps wheel rate (Clarity A030 Kp*(R5 - R6)),
        # which the driver would feel as drag. The limit also spreads the lateral controller's own steps, such as its
        # feedforward dropping out on the press.
        step = DT_CTRL / settings.fade_down_s
        self.override_ramp = max(settings.torque_scale, self.override_ramp - step)
        target = torque_cmd * self.override_ramp
        torque_cmd = rate_limit(target, self.last_torque, -step, step)
        releasing = self.override_ramp > settings.torque_scale or abs(torque_cmd - target) > 1e-4
      elif steering_pressed:
        self.override_ramp = settings.torque_scale
        torque_cmd *= self.override_ramp
      else:
        self.override_ramp = 1.0 if settings.fade_up_s <= 0.0 else min(1.0, self.override_ramp + DT_CTRL / settings.fade_up_s)
        torque_cmd *= self.override_ramp
    else:
      self.override_ramp = 0.0
      self.steering_pressed_filter_s = 0.0
      self.steering_pressed_prev = False

    # Unlike a low-pass filter, the limiter withholds authority for as long as it is saturated, so reporting it as
    # limiting -- and freezing the integrator against it -- is correct.
    if settings.delta_limiter:
      torque_cmd = rate_limit(torque_cmd, self.last_torque, -settings.delta_down * DT_CTRL, settings.delta_up * DT_CTRL)

    self.last_torque = torque_cmd
    self.lat_active_prev = CC.latActive
    lkas_active = CC.latActive and (settings.assist_during_override or releasing or not steering_pressed) and not below_min_steer_speed
    return torque_cmd, lkas_active, steering_pressed
