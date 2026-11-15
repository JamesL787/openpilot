"""modified-EPS steering in the car controller, the steering-pressed threshold, and the VSA yaw decode."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from opendbc.car import Bus, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.honda import yaw_rate
from opendbc.car.honda.carcontroller import CarController
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.interface import CarInterface
from opendbc.car import DT_CTRL
from opendbc.car.honda.modified_eps import (DEFAULT_SETTINGS, RELEASE_FRACTION, RELEASE_HOLD_S, ModifiedEpsSteering,
                                            SteeringPressedHysteresis, get_eps_modified_steering_pressed,
                                            lane_change_nudge_torque, modified_eps, steering_pressed_threshold)
from opendbc.car.honda.values import CAR, DBC, HondaFlags
from opendbc.car.honda.yaw_rate import YawRateCalibration, get_yaw_rate_calibration


def _modified_cp(car=CAR.HONDA_CLARITY):
  CP = CarInterface.get_non_essential_params(car)
  CP.flags |= int(HondaFlags.EPS_MODIFIED)
  return CP


def test_the_controllers_follow_carstates_press_in_either_direction():
  assert get_eps_modified_steering_pressed(True, 1500.0, 0.8, 0.0, False)[1]   # along the command: no 0.28 s hold
  assert get_eps_modified_steering_pressed(True, -1500.0, 0.8, 0.0, False)[1]
  assert not get_eps_modified_steering_pressed(False, 1500.0, 0.8, 1.0, True)[1]


def _press(torques, threshold=2000.0):
  h = SteeringPressedHysteresis()
  return [h.update(t, threshold) for t in torques]


def test_a_press_starts_over_the_threshold_in_either_direction():
  assert _press([1990.0, 2010.0]) == [False, True]
  assert _press([-2010.0]) == [True]


def test_a_press_holds_through_a_dip_under_the_threshold():
  # the cut takes away the torque the driver leans on: their reading drops, but not under the release level
  assert all(_press([2100.0] + [1300.0] * 200))


def test_a_press_ends_after_the_hold_under_the_release_level():
  pressed = _press([2100.0] + [1100.0] * 40)
  hold = round(RELEASE_HOLD_S / DT_CTRL)
  assert 1100.0 < RELEASE_FRACTION * 2000.0
  assert all(pressed[:hold]) and not any(pressed[hold + 1:])


def test_the_hold_restarts_when_the_torque_comes_back():
  hold = round(RELEASE_HOLD_S / DT_CTRL)
  torques = [2100.0] + [1000.0] * (hold - 5) + [1500.0] + [1000.0] * (hold - 5)
  assert all(_press(torques))


def test_carstate_uses_the_hysteresis_only_on_a_modified_eps():
  from opendbc.car.honda.carstate import CarState
  assert isinstance(CarState(_modified_cp()).steering_pressed_hysteresis, SteeringPressedHysteresis)
  assert not CarState(CarInterface.get_non_essential_params(CAR.HONDA_CLARITY)).modified_eps


def test_only_a_modified_eps_gets_the_steering_stage_and_threshold():
  stock = CarInterface.get_non_essential_params(CAR.HONDA_CLARITY)
  assert not modified_eps(stock)
  assert CarController(DBC[stock.carFingerprint], stock).modified_eps_steering is None
  assert lane_change_nudge_torque(stock) is None

  CP = _modified_cp()
  assert CarController(DBC[CP.carFingerprint], CP).modified_eps_steering is not None
  assert steering_pressed_threshold(CP, DEFAULT_SETTINGS.override_threshold) == 2000
  assert steering_pressed_threshold(CP, 1840) == 1840
  assert steering_pressed_threshold(CP, 0) == 1200          # 0 keeps the stock threshold
  assert lane_change_nudge_torque(CP) == 1200


class TestHondaSteeringCommandFidelity:
  """actuatorsOutput.torque may differ from actuators.torque ONLY when the car cannot deliver it.

  controlsd infers steer_limited_by_safety from that difference and uses it to freeze the lateral integrator, so any
  comfort shaping applied on this path is indistinguishable from safety limiting.
  """

  SETTINGS = replace(DEFAULT_SETTINGS, fade_down_s=0.0)
  SOFT = replace(DEFAULT_SETTINGS, fade_down_s=0.15)

  @staticmethod
  def _cc(torque, lat_active=True):
    CC = structs.CarControl.new_message()
    CC.latActive = lat_active
    CC.actuators.torque = torque
    return CC

  @staticmethod
  def _cs(v_ego=20.0, steering_pressed=False):
    return SimpleNamespace(out=SimpleNamespace(vEgo=v_ego, steeringPressed=steering_pressed, steeringTorque=0.0))

  def _drive(self, steering, torques, settings=None, **cs_kwargs):
    settings = settings or self.SETTINGS
    return [steering.update(self._cc(t), self._cs(**cs_kwargs), settings)[0] for t in torques]

  def _ready(self):
    steering = ModifiedEpsSteering()
    self._drive(steering, [0.0] * 200)  # let the engage ramp finish
    return steering

  def test_command_is_delivered_unchanged_once_the_override_ramp_is_up(self):
    commands = [0.10, 0.35, -0.20, 0.80, -0.75, 0.0]
    assert self._drive(self._ready(), commands) == pytest.approx(commands)

  def test_a_moving_command_is_not_reported_as_limited(self):
    ramp = [0.01 * n for n in range(60)]  # 1.0 authority/s
    delivered = self._drive(self._ready(), ramp)
    assert all(abs(cmd - out) <= 1e-2 for cmd, out in zip(ramp, delivered, strict=True))

  def test_min_steer_speed_zeroing_is_reported_as_limited(self):
    assert self._drive(ModifiedEpsSteering(), [0.5], v_ego=0.0) == [0.0]

  def test_override_cut_is_reported_as_limited(self):
    # a press cuts on its first frame, whichever way the driver pushes
    assert abs(0.5 - self._drive(self._ready(), [0.5], steering_pressed=True)[0]) > 1e-2

  def test_a_hard_cut_drops_the_request_at_once(self):
    assert DEFAULT_SETTINGS.fade_down_s == 0.0   # the soft cut is opt-in (HondaOverrideFadeDownSecs)
    torque, lkas, _ = self._ready().update(self._cc(0.5), self._cs(steering_pressed=True), DEFAULT_SETTINGS)
    assert torque == 0.0 and not lkas

  def test_a_soft_cut_eases_the_torque_out_with_the_request_on(self):
    steering, settings = self._ready(), self.SOFT
    self._drive(steering, [0.5] * 10, settings)
    out = [steering.update(self._cc(0.5), self._cs(steering_pressed=True), settings) for _ in range(40)]
    torques = [t for t, _, _ in out]
    fade = round(settings.fade_down_s / DT_CTRL)
    assert torques[0] == pytest.approx(0.5 * (1.0 - DT_CTRL / settings.fade_down_s))
    assert all(a > b for a, b in zip(torques[:fade], torques[1:fade], strict=False))
    assert all(t == 0.0 for t in torques[fade:])
    assert all(lkas for _, lkas, _ in out[:fade - 1]) and not any(lkas for _, lkas, _ in out[fade:])

  def test_a_soft_cut_spreads_a_step_in_the_command(self):
    # the lateral controller drops its feedforward on a press: that step must not reach the wheel at once
    steering, settings = self._ready(), self.SOFT
    self._drive(steering, [0.6] * 10, settings)
    torques = [steering.update(self._cc(-0.2), self._cs(steering_pressed=True), settings)[0] for _ in range(30)]
    steps = [abs(b - a) for a, b in zip([0.6] + torques, torques, strict=False)]
    assert max(steps) <= DT_CTRL / settings.fade_down_s + 1e-9
    assert torques[-1] == 0.0

  def test_assist_during_override_keeps_the_request_through_the_press(self):
    steering, settings = self._ready(), replace(self.SOFT, assist_during_override=True, torque_scale=0.3)
    out = [steering.update(self._cc(0.5), self._cs(steering_pressed=True), settings) for _ in range(60)]
    assert all(lkas for _, lkas, _ in out)
    assert out[-1][0] == pytest.approx(0.15)

  def test_steer_delta_limiter_is_reported_as_limited(self):
    delivered = self._drive(self._ready(), [1.0], settings=replace(self.SETTINGS, delta_limiter=True))
    assert abs(1.0 - delivered[0]) > 1e-2

  def test_the_car_controller_sends_the_command_through_the_stage(self):
    CP = _modified_cp()
    controller = CarController(DBC[CP.carFingerprint], CP)
    controller.modified_eps_settings = SimpleNamespace(current=lambda: self.SETTINGS)
    for _ in range(200):
      controller.modified_eps_steering.update(self._cc(0.0), self._cs(), self.SETTINGS)
    assert controller.modified_eps_steering.update(self._cc(0.4), self._cs(), self.SETTINGS)[0] == pytest.approx(0.4)


@pytest.mark.parametrize("car, frame, yaw_deg_s", [
  (CAR.HONDA_CLARITY, "989f88b60c000c72", 24.348),     # 610 counts, seeded zero 512, 0.246, +0.24 clockwise
  (CAR.HONDA_CLARITY, "645f4759f1000c62", -27.306),    # 401 counts: left turn, same route
  (CAR.HONDA_CLARITY, "7f5f4801f0000c72", -0.738),     # 509 counts: straight, 3 counts below the seeded zero
  (CAR.HONDA_CIVIC_BOSCH, "8263880e02000c57", 1.952),  # 521 counts, zero 513, 0.244 deg/s
  (CAR.HONDA_CIVIC_BOSCH, "6d638735ea000c40", -18.544),
  (CAR.HONDA_CIVIC_BOSCH, "806387ddfa000c48", 0.0),
  (CAR.HONDA_CRV_5G, "9620491a0d000c45", 22.6625),
  (CAR.HONDA_CRV_5G, "66a1071e0a000c53", -24.3775),
  (CAR.HONDA_CRV_5G, "7fa087de00000c50", 0.1225),
])
def test_honda_yaw_rate_from_vsa(car, frame, yaw_deg_s):
  CP = _modified_cp(car)   # the decode runs on modified-EPS cars only
  CI = CarInterface(CP)
  cp, bus = CI.can_parsers[Bus.pt], CanBus(CP).pt
  cp.update([(1_000_000_000, [(0x94, bytes.fromhex(frame), bus)])])  # register KINEMATICS before its first frame
  cp.vl["KINEMATICS"]
  cp.update([(1_010_000_000, [(0x94, bytes.fromhex(frame), bus)])])

  d = bytes.fromhex(frame)
  assert cp.vl["KINEMATICS"]["YAW_RATE"] == pytest.approx(((d[0] << 2 | d[1] >> 6) - 512) * 0.25)  # nominal zero
  ret = CI.CS.update(CI.can_parsers)
  assert ret.yawRate == pytest.approx(-yaw_deg_s * CV.DEG_TO_RAD)  # left-positive, like steeringAngleDeg


def test_honda_long_accel_scale():
  cp = CarInterface(CarInterface.get_non_essential_params(CAR.HONDA_CLARITY)).can_parsers[Bus.pt]
  frame = bytes.fromhex("989f88b60c000c72")   # LONG_ACCEL raw +12 (braking)
  cp.update([(1_000_000_000, [(0x94, frame, 0)])])
  cp.vl["KINEMATICS"]
  cp.update([(1_010_000_000, [(0x94, frame, 0)])])
  assert cp.vl["KINEMATICS"]["LONG_ACCEL"] == pytest.approx(12 * -0.049)


def test_yaw_rate_zero_is_learned_at_standstill():
  cal = YawRateCalibration(0.25, 508.0)
  to_dbc = lambda counts: (counts - 512.0) * 0.25  # noqa: E731
  assert cal.update(to_dbc(510.0), standstill=False) == pytest.approx(0.5)
  for _ in range(yaw_rate.SETTLE_FRAMES):
    cal.update(to_dbc(530.0), standstill=True)
  for _ in range(yaw_rate.LEARN_FRAMES - 1):
    cal.update(to_dbc(509.5), standstill=True)
  assert cal.zero == 508.0
  assert cal.update(to_dbc(509.5), standstill=True) == pytest.approx(0.0)
  assert cal.zero == pytest.approx(509.5)
  assert cal.update(to_dbc(519.5), standstill=False) == pytest.approx(2.5)
  assert cal.samples == 0


@pytest.mark.parametrize("counts, yaw_deg_s", [(-40, -9.84), (-4, -0.984), (0, 0.0), (3, 0.738), (4, 1.104), (5, 1.47), (40, 10.08)])
def test_clarity_clockwise_under_read_is_corrected(counts, yaw_deg_s):
  cal = get_yaw_rate_calibration(CAR.HONDA_CLARITY)
  assert cal.update((cal.zero + counts - 512.0) * 0.25, standstill=False) == pytest.approx(yaw_deg_s)


def test_yaw_rate_zero_rejects_a_faulted_sensor():
  cal = YawRateCalibration(0.25, 508.0)
  for _ in range(yaw_rate.SETTLE_FRAMES + yaw_rate.LEARN_FRAMES + 10):
    cal.update((530.0 - 512.0) * 0.25, standstill=True)
  assert cal.zero == 508.0


def test_stock_cars_do_not_require_the_yaw_message():
  CI = CarInterface(CarInterface.get_non_essential_params(CAR.HONDA_CLARITY))
  assert CI.CS.yaw_rate is None


def test_yaw_rate_only_on_checked_cars():
  for car in (CAR.HONDA_CLARITY, CAR.HONDA_CIVIC_BOSCH, CAR.HONDA_CRV_5G, CAR.HONDA_INSIGHT, CAR.HONDA_CIVIC):
    assert get_yaw_rate_calibration(car) is not None
  assert get_yaw_rate_calibration(CAR.HONDA_ACCORD) is None
