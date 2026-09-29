import math
import numpy as np

from types import SimpleNamespace

from cereal import car
from opendbc.car.gm.values import CC_ONLY_CAR, GMFlags
from openpilot.common.constants import CV


# WARNING: this value was determined based on the model's training distribution,
#          model predictions above this speed can be unpredictable
# V_CRUISE's are in kph
V_CRUISE_MIN = 8
V_CRUISE_MAX = 145
V_CRUISE_UNSET = 255
V_CRUISE_INITIAL = 40
V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 105
IMPERIAL_INCREMENT = round(CV.MPH_TO_KPH, 1)  # round here to avoid rounding errors incrementing set speed

ButtonEvent = car.CarState.ButtonEvent
ButtonType = car.CarState.ButtonEvent.Type
CRUISE_LONG_PRESS = 50
CRUISE_NEAREST_FUNC = {
  ButtonType.accelCruise: math.ceil,
  ButtonType.decelCruise: math.floor,
}
CRUISE_INTERVAL_SIGN = {
  ButtonType.accelCruise: +1,
  ButtonType.decelCruise: -1,
}
ACCEL_CRUISE_BUTTONS = (ButtonType.accelCruise,)
# Gas-release set speed (ICBM only, built in): when the driver lets off the gas above the set speed,
# the set speed becomes the speed at release, rounded to a whole display unit. Peter asked for this 2026-09-23.
# The margin keeps a small overshoot of the set speed from moving it.
GAS_RELEASE_SET_MARGIN_KPH = 1.0 * CV.MPH_TO_KPH


def is_speed_limit_confirmation_pending(starpilot_plan) -> bool:
  """Only consume cruise buttons when SLC has a limit awaiting confirmation."""
  return bool(starpilot_plan.speedLimitChanged and starpilot_plan.unconfirmedSlcSpeedLimit >= 1)


class VCruiseHelper:
  def __init__(self, CP, FPCP=None):
    self.CP = CP
    self.v_cruise_kph = V_CRUISE_UNSET
    self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.v_cruise_kph_last = 0
    self.gas_pressed_prev = False
    self.button_timers = {
      ButtonType.decelCruise: 0,
      ButtonType.accelCruise: 0,
    }
    self.button_hard_states = dict.fromkeys(self.button_timers, False)
    self.button_change_states = {btn: {"standstill": False, "enabled": False} for btn in self.button_timers}
    # Keep the confirmation button from leaking into cruise-speed handling when the
    # planner clears the confirmation state between the press and release events.
    self.confirmation_button_suppressed = set()

    self.gm_cc_only = self.CP.carFingerprint in CC_ONLY_CAR and self.CP.flags & GMFlags.CC_LONG.value
    self.redneck_non_pcm = bool(FPCP is not None and
                                getattr(FPCP, "redneckCruiseAvailable", False) and
                                not getattr(FPCP, "pcmCruiseSpeed", True))

  def _get_short_press_delta(self, is_metric, starpilot_toggles: SimpleNamespace) -> float:
    base_delta = 1. if is_metric else IMPERIAL_INCREMENT
    return base_delta * self._get_cruise_delta_interval(starpilot_toggles.cruise_increase)

  @staticmethod
  def _get_cruise_delta_interval(interval: float | None) -> float:
    return interval if isinstance(interval, (int, float)) and interval > 0 else 1.0

  def _get_cruise_delta_intervals(self, starpilot_toggles: SimpleNamespace) -> tuple[float, float]:
    short_interval = self._get_cruise_delta_interval(getattr(starpilot_toggles, "cruise_increase", None))
    long_interval = self._get_cruise_delta_interval(getattr(starpilot_toggles, "cruise_increase_long", None))
    return short_interval, long_interval

  def _uses_software_cruise(self) -> bool:
    return bool(self.gm_cc_only or self.redneck_non_pcm or not self.CP.pcmCruise)

  @property
  def v_cruise_initialized(self):
    return self.v_cruise_kph != V_CRUISE_UNSET

  @staticmethod
  def _is_hard_cruise_button(button_type, starpilot_car_state) -> bool:
    if starpilot_car_state is None:
      return False
    if button_type == ButtonType.accelCruise:
      return bool(getattr(starpilot_car_state, "accelHardCruise", False))
    if button_type == ButtonType.decelCruise:
      return bool(getattr(starpilot_car_state, "decelHardCruise", False))
    return False

  def update_v_cruise(self, CS, enabled, is_metric, speed_limit_changed, starpilot_toggles, starpilot_car_state=None,
                      slc_target_with_offset=0.0):
    self.v_cruise_kph_last = self.v_cruise_kph

    if CS.cruiseState.available:
      if self._uses_software_cruise():
        # if stock cruise is completely disabled, then we can use our own set speed logic
        self._update_v_cruise_non_pcm(CS, enabled, is_metric, speed_limit_changed, starpilot_toggles, starpilot_car_state,
                                      slc_target_with_offset)
        self._update_v_cruise_gas_release(CS, enabled, is_metric, starpilot_toggles)
        self.v_cruise_cluster_kph = self.v_cruise_kph
        self.update_button_timers(CS, enabled, starpilot_car_state)
      else:
        self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH
        self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
        if CS.cruiseState.speed == 0:
          self.v_cruise_kph = V_CRUISE_UNSET
          self.v_cruise_cluster_kph = V_CRUISE_UNSET
        elif CS.cruiseState.speed == -1:
          self.v_cruise_kph = -1
          self.v_cruise_cluster_kph = -1
    else:
      self.v_cruise_kph = V_CRUISE_UNSET
      self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.gas_pressed_prev = bool(CS.gasPressed)

  def _update_v_cruise_gas_release(self, CS, enabled, is_metric, starpilot_toggles):
    gas_released = self.gas_pressed_prev and not CS.gasPressed
    if not (gas_released and enabled and self.redneck_non_pcm and self.v_cruise_initialized and
            getattr(starpilot_toggles, "set_speed_on_gas_release", False)):
      return
    v_ego_kph = CS.vEgo * CV.MS_TO_KPH
    if v_ego_kph <= self.v_cruise_kph + GAS_RELEASE_SET_MARGIN_KPH:
      return
    if is_metric:
      v_cruise_kph = float(round(v_ego_kph))
    else:
      v_cruise_kph = round(round(v_ego_kph * CV.KPH_TO_MPH) * CV.MPH_TO_KPH, 1)  # exact mph, as SLC stores it
    self.v_cruise_kph = float(np.clip(v_cruise_kph, V_CRUISE_MIN, V_CRUISE_MAX))

  def _update_v_cruise_non_pcm(self, CS, enabled, is_metric, speed_limit_changed, starpilot_toggles, starpilot_car_state=None,
                                slc_target_with_offset=0.0):
    # handle button presses. TODO: this should be in state_control, but a decelCruise press
    # would have the effect of both enabling and changing speed is checked after the state transition
    if not enabled:
      return

    long_press = False
    button_type = None
    button_is_hard = False

    v_cruise_delta = 1. if is_metric else IMPERIAL_INCREMENT

    for b in CS.buttonEvents:
      event_button_type = b.type.raw
      if event_button_type in self.button_timers:
        if speed_limit_changed and b.pressed:
          self.confirmation_button_suppressed.add(event_button_type)
        elif not b.pressed and event_button_type in self.confirmation_button_suppressed:
          self.confirmation_button_suppressed.remove(event_button_type)
          return

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers and not b.pressed:
        if self.button_timers[b.type.raw] > CRUISE_LONG_PRESS:
          return  # end long press
        button_type = b.type.raw
        button_is_hard = self.button_hard_states.get(button_type, False) or self._is_hard_cruise_button(button_type, starpilot_car_state)
        break
    else:
      for k, timer in self.button_timers.items():
        if timer and timer % CRUISE_LONG_PRESS == 0:
          button_type = k
          long_press = True
          button_is_hard = self.button_hard_states.get(button_type, False)
          break

    if button_type is None:
      return

    if button_type in self.confirmation_button_suppressed:
      return

    # Don't adjust speed when pressing to confirm or deny speed limit changes
    if speed_limit_changed:
      return

    # Don't adjust speed when pressing resume to exit standstill
    cruise_standstill = self.button_change_states[button_type]["standstill"] or CS.cruiseState.standstill
    if button_type in ACCEL_CRUISE_BUTTONS and cruise_standstill:
      return

    # Don't adjust speed if we've enabled since the button was depressed (some ports enable on rising edge)
    if not self.button_change_states[button_type]["enabled"]:
      return

    short_interval, long_interval = self._get_cruise_delta_intervals(starpilot_toggles)
    v_cruise_delta_interval = long_interval if long_press or button_is_hard else short_interval
    # SLC stores exact conversions (50 mph = 80.5 kph), which drift off the 1.6 kph imperial grid as speed rises.
    # Map an exact mph value onto the grid first, or a long press only moves to the nearest 5-unit multiple (80.0)
    # instead of stepping a full 5 units. Route 0000025b: long-press - from an SLC 50 left vCruise at 49.7.
    previous_v_cruise_kph = self.v_cruise_kph
    if not is_metric:
      speed_mph = round(self.v_cruise_kph * CV.KPH_TO_MPH)
      if abs(self.v_cruise_kph - speed_mph * CV.MPH_TO_KPH) <= 0.06:
        self.v_cruise_kph = round(speed_mph * v_cruise_delta, 1)
    v_cruise_delta = v_cruise_delta * v_cruise_delta_interval
    if v_cruise_delta_interval % 5 == 0 and self.v_cruise_kph % v_cruise_delta != 0:  # partial interval
      self.v_cruise_kph = CRUISE_NEAREST_FUNC[button_type](self.v_cruise_kph / v_cruise_delta) * v_cruise_delta
    else:
      self.v_cruise_kph += v_cruise_delta * CRUISE_INTERVAL_SIGN[button_type]

    # Round to stored cruise-speed precision so the SLC target can be matched exactly.
    slc_target_with_offset_kph = round(slc_target_with_offset * CV.MS_TO_KPH, 1)
    # Preserve an active SLC target when an accel increment would otherwise skip it.
    crossed_slc_target = (
      button_type in ACCEL_CRUISE_BUTTONS and
      previous_v_cruise_kph < slc_target_with_offset_kph < self.v_cruise_kph
    )
    if crossed_slc_target:
      self.v_cruise_kph = slc_target_with_offset_kph

    # If set is pressed while overriding, clip cruise speed to minimum of vEgo
    if CS.gasPressed and button_type in (ButtonType.decelCruise, ButtonType.setCruise):
      self.v_cruise_kph = max(self.v_cruise_kph, CS.vEgo * CV.MS_TO_KPH)

    self.v_cruise_kph = np.clip(round(self.v_cruise_kph, 1), V_CRUISE_MIN, V_CRUISE_MAX)

  def update_button_timers(self, CS, enabled, starpilot_car_state=None):
    # increment timer for buttons still pressed
    for k in self.button_timers:
      if self.button_timers[k] > 0:
        self.button_timers[k] += 1

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers:
        # Start/end timer and store current state on change of button pressed
        button_type = b.type.raw
        self.button_timers[button_type] = 1 if b.pressed else 0
        self.button_change_states[button_type] = {"standstill": CS.cruiseState.standstill, "enabled": enabled}
        self.button_hard_states[button_type] = self._is_hard_cruise_button(button_type, starpilot_car_state) if b.pressed else False

  def initialize_v_cruise(self, CS, experimental_mode: bool, resume_prev_button: bool,
                          starpilot_toggles: SimpleNamespace, desired_speed_limit: float = 0.0) -> None:
    if self.CP.pcmCruise and not self._uses_software_cruise():
      return

    engage_floor_kph = max(V_CRUISE_MIN, 7.0 * CV.MPH_TO_KPH)
    resume_pressed = any(b.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for b in CS.buttonEvents)
    remembered_resume = resume_prev_button and (self.gm_cc_only or self.redneck_non_pcm)

    if self.v_cruise_initialized and (resume_pressed or remembered_resume):
      self.v_cruise_kph = self.v_cruise_kph_last
    elif desired_speed_limit > 0 and getattr(starpilot_toggles, "set_speed_limit", False):
      # Respect the exact SLC limit+offset on engage instead of snapping upward to
      # the custom cruise-button interval.
      initialized_speed_limit_kph = round(desired_speed_limit * CV.MS_TO_KPH, 1)
      self.v_cruise_kph = float(np.clip(initialized_speed_limit_kph, V_CRUISE_MIN, V_CRUISE_MAX))
    elif self.redneck_non_pcm and CS.cruiseState.speedCluster > 0:
      self.v_cruise_kph = float(np.clip(CS.cruiseState.speedCluster * CV.MS_TO_KPH, V_CRUISE_MIN, V_CRUISE_MAX))
    else:
      self.v_cruise_kph = int(round(np.clip(CS.vEgo * CV.MS_TO_KPH, engage_floor_kph, V_CRUISE_MAX)))

    self.v_cruise_cluster_kph = self.v_cruise_kph
