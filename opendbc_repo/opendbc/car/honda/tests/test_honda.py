import re
from types import SimpleNamespace
import pytest

from cereal import custom
from opendbc.car import Bus, structs
from opendbc.car.structs import CarParams
from opendbc.car import gen_empty_fingerprint
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda import carcontroller as cc_mod
from opendbc.car.honda.carcontroller import (
  BOSCH_BRAKE_FORCE_ON,
  BOSCH_BRAKE_FORCE_RELEASE,
  CarController,
  get_eps_modified_steering_pressed,
  get_honda_bosch_wind_brake_mps2,
  update_honda_bosch_braking,
  update_honda_bosch_live_learning,
)
from opendbc.car.honda import yaw_rate
from opendbc.car.honda.hondacan import CanBus, create_acc_commands, create_brake_command, create_lkas_hud
from opendbc.car.honda.fingerprints import FW_VERSIONS
from opendbc.car.honda.yaw_rate import YawRateCalibration, get_yaw_rate_calibration
from opendbc.car.tests.test_car_interfaces import get_test_starpilot_toggles
from opendbc.car.honda.values import CAR, DBC, HONDA_BOSCH, HONDA_BOSCH_TJA_CONTROL, CarControllerParams, HondaFlags, HondaSafetyFlags, \
                                     HondaStarPilotFlags

HONDA_FW_VERSION_RE = rb"[A-Z0-9]{5}-[A-Z0-9]{3}(-|,)[A-Z0-9]{4}(\x00){2}$"


def get_test_toggles() -> SimpleNamespace:
  return SimpleNamespace(always_on_lateral_lkas=False, force_torque_controller=False, nnff=False, nnff_lite=False)


class TestHondaFingerprint:
  @staticmethod
  def _acc_control_values(active, accel, gas=500, gas_force=0.5, braking=False):
    class FakePacker:
      @staticmethod
      def make_can_msg(name, bus, values):
        return name, bus, values

    can = SimpleNamespace(pt=1)
    commands = create_acc_commands(FakePacker(), can, True, active, accel, gas, 0, CAR.HONDA_CRV_5G, gas_force, braking)
    assert commands[-1][0] == "ACC_CONTROL"
    return commands[-1][2]

  def test_bosch_acc_commands_reject_fault_route_gas_brake_conflict(self):
    # Route 00000002--aa8501ddcb broadcast P061B while Alpha Long sent
    # approximately accel=-0.27, positive gas, and both brake bits. Drag/grade
    # compensation calculated positive gas. Same-domain arbitration selects
    # propulsion rather than reproducing the observed simultaneous request.
    braking = update_honda_bosch_braking(False, 0.2, False, True)
    values = self._acc_control_values(True, -0.27, gas=160, gas_force=0.2, braking=braking)

    assert values["GAS_COMMAND"] == 160
    assert values["ACCEL_COMMAND"] == pytest.approx(-0.27)
    assert values["BRAKE_REQUEST"] == 0
    assert values["BRAKE_LIGHTS"] == 0

  @pytest.mark.parametrize("active", [False, True])
  @pytest.mark.parametrize("accel", [-3.5, -0.27, -0.2, -0.1, 0.0, 0.01, 2.0])
  @pytest.mark.parametrize("gas_force", [-0.5, 0.0, 0.5])
  @pytest.mark.parametrize("braking", [False, True])
  def test_bosch_acc_commands_never_request_gas_and_braking_together(self, active, accel, gas_force, braking):
    values = self._acc_control_values(active, accel, gas_force=gas_force, braking=braking)

    assert not (values["GAS_COMMAND"] > 0 and values["BRAKE_REQUEST"] == 1)
    assert not (values["GAS_COMMAND"] > 0 and values["BRAKE_LIGHTS"] == 1)
    if values["GAS_COMMAND"] > 0:
      assert active

  def test_bosch_acc_commands_preserve_road_load_gas_above_brake_threshold(self):
    # Route 00000003--1423cb6de2 showed severe cycling when the prior fix cut
    # this positive drag/grade-compensated gas at raw accel zero.
    values = self._acc_control_values(True, -0.1, gas=500, gas_force=0.3)

    assert values["GAS_COMMAND"] == 500
    assert values["ACCEL_COMMAND"] == pytest.approx(-0.1)
    assert values["BRAKE_REQUEST"] == 0
    assert values["BRAKE_LIGHTS"] == 0

  def test_bosch_acc_commands_do_not_send_gas_without_positive_force(self):
    values = self._acc_control_values(True, 0.2, gas=500, gas_force=-0.4)

    assert values["GAS_COMMAND"] == -30000

  def test_bosch_braking_uses_force_hysteresis(self):
    braking = update_honda_bosch_braking(False, BOSCH_BRAKE_FORCE_ON - 0.01, False, True)
    assert braking

    braking = update_honda_bosch_braking(braking, -0.05, False, True)
    assert braking

    braking = update_honda_bosch_braking(braking, BOSCH_BRAKE_FORCE_RELEASE + 0.01, False, True)
    assert not braking

  def test_bosch_braking_preserves_stopping_and_resets_inactive(self):
    assert update_honda_bosch_braking(False, 0.5, True, True)
    assert not update_honda_bosch_braking(True, -1.0, False, False)

  def test_honda_lkas_hud_shows_lane_lines_when_lateral_only_is_active(self):
    class FakePacker:
      @staticmethod
      def make_can_msg(name, bus, values):
        return name, bus, values

    CP = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC_BOSCH)
    hud_control = SimpleNamespace(lanesVisible=False)

    cmds = create_lkas_hud(FakePacker(), 0, CP, hud_control, True, True, False, False, {})

    assert cmds[0][2]["SOLID_LANES"] is True

  def test_civic_bosch_stopping_defaults_are_carparams_derived(self):
    CP = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC_BOSCH)

    assert CP.stopAccel == pytest.approx(-2.0)
    assert CP.stoppingDecelRate == pytest.approx(0.1)
    assert CP.vEgoStarting == pytest.approx(0.5)
    assert CP.vEgoStopping == pytest.approx(0.5)

  def test_fw_version_format(self):
    # Asserts all FW versions follow an expected format
    for fw_by_ecu in FW_VERSIONS.values():
      for fws in fw_by_ecu.values():
        for fw in fws:
          assert re.match(HONDA_FW_VERSION_RE, fw) is not None, fw

  def test_tja_bosch_only(self):
    assert set(HONDA_BOSCH_TJA_CONTROL).issubset(set(HONDA_BOSCH)), "Nidec car found in TJA control list"

  def test_eps_modified_steering_pressed_filter_matches_nrdr_thresholds(self):
    filter_s, pressed = get_eps_modified_steering_pressed(True, 1500.0, 0.8, 0.27, False)
    assert pressed
    assert filter_s == pytest.approx(0.28)

    filter_s, pressed = get_eps_modified_steering_pressed(True, -1500.0, 0.8, 0.0, False)
    assert pressed
    assert filter_s == pytest.approx(1.0)

    filter_s, pressed = get_eps_modified_steering_pressed(False, 1500.0, 0.8, 1.0, True)
    assert not pressed
    assert filter_s == pytest.approx(0.0)

  def test_honda_bosch_wind_brake_curve_matches_reference_points(self):
    assert get_honda_bosch_wind_brake_mps2(0.0) == pytest.approx(0.0)
    assert get_honda_bosch_wind_brake_mps2(22.4) == pytest.approx(0.136)
    assert get_honda_bosch_wind_brake_mps2(40.2) == pytest.approx(0.441)

  def test_honda_bosch_live_learning_increases_factors_when_under_accelerating(self):
    gas_factor, wind_factor, wind_factor_before_brake = update_honda_bosch_live_learning(
      1.0,
      1.0,
      0.0,
      desired_accel=1.0,
      actual_accel=0.5,
      gas_pedal_force=1.2,
      wind_brake_mps2=0.136,
      brake_pressed=False,
      v_ego=22.4,
    )

    assert gas_factor == pytest.approx(1.012)
    assert wind_factor == pytest.approx(1.000136)
    assert wind_factor_before_brake == pytest.approx(wind_factor)

  def test_honda_bosch_live_learning_restores_wind_factor_while_braking(self):
    gas_factor, wind_factor, wind_factor_before_brake = update_honda_bosch_live_learning(
      1.4,
      1.1,
      1.3,
      desired_accel=-0.2,
      actual_accel=0.0,
      gas_pedal_force=-0.1,
      wind_brake_mps2=0.136,
      brake_pressed=True,
      v_ego=22.4,
    )

    assert gas_factor == pytest.approx(1.4)
    assert wind_factor == pytest.approx(1.3)
    assert wind_factor_before_brake == pytest.approx(1.3)

  def test_official_modified_eps_firmwares_restored(self):
    assert b'39990-TVA,A150\x00\x00' in FW_VERSIONS[CAR.HONDA_ACCORD][(CarParams.Ecu.eps, 0x18DA30F1, None)]
    assert b'39990-TBA,A030\x00\x00' in FW_VERSIONS[CAR.HONDA_CIVIC][(CarParams.Ecu.eps, 0x18DA30F1, None)]
    assert b'39990-TBA-C120\x00\x00' in FW_VERSIONS[CAR.HONDA_CIVIC_BOSCH][(CarParams.Ecu.eps, 0x18DA30F1, None)]
    assert b'39990-TGG,A020\x00\x00' in FW_VERSIONS[CAR.HONDA_CIVIC_BOSCH][(CarParams.Ecu.eps, 0x18DA30F1, None)]
    assert b'39990-TLA,A040\x00\x00' in FW_VERSIONS[CAR.HONDA_CRV_5G][(CarParams.Ecu.eps, 0x18DA30F1, None)]

  def test_modified_eps_candidates_keep_support_and_apply_nrdr_linear_max_tunes(self):
    # The NRDR linear-max RWD images ramp linearly to the firmware cap, so the piecewise stock
    # breakpoints collapse to a single ramp and the gains drop to match. See eps_tools/rwd/.
    # 39990-TBA-C120 (Civic) caps at 3840; 39990-TLA-A040 (CR-V 5G) caps at 4096 -- its own range.
    toggles = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)

    civic_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TBA,A030\x00\x00', address=0x18DA30F1, subAddress=0)]
    civic_cp = CarInterface.get_params(CAR.HONDA_CIVIC, gen_empty_fingerprint(), civic_fw, False, False, False, toggles)
    assert not civic_cp.dashcamOnly
    assert civic_cp.flags & HondaFlags.EPS_MODIFIED
    assert list(civic_cp.lateralParams.torqueBP) == [0, 3840]
    assert list(civic_cp.lateralParams.torqueV) == [0, 3840]
    # shares the modified-EPS Bosch tune: four-point handoff at 25 mph
    civic_matched_bp = [0.0, 25.0 * CV.MPH_TO_MS - 1e-3, 25.0 * CV.MPH_TO_MS, 50.0 * CV.MPH_TO_MS]
    assert list(civic_cp.lateralTuning.pid.kpBP) == pytest.approx(civic_matched_bp)
    assert list(civic_cp.lateralTuning.pid.kiBP) == pytest.approx(civic_matched_bp)
    assert list(civic_cp.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
    assert list(civic_cp.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
    assert civic_cp.lateralTuning.pid.kf == pytest.approx(3.6e-6)
    assert civic_cp.steerAtStandstill
    assert civic_cp.minSteerSpeed == pytest.approx(-1.0)

    civic_bosch_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TGG,A020\x00\x00', address=0x18DA30F1, subAddress=0)]
    civic_bosch_cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), civic_bosch_fw, False, False, False, toggles)
    assert not civic_bosch_cp.dashcamOnly
    assert civic_bosch_cp.flags & HondaFlags.EPS_MODIFIED

    accord_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TVA,A150\x00\x00', address=0x18DA30F1, subAddress=0)]
    accord_cp = CarInterface.get_params(CAR.HONDA_ACCORD, gen_empty_fingerprint(), accord_fw, False, False, False, toggles)
    assert not accord_cp.dashcamOnly
    assert accord_cp.flags & HondaFlags.EPS_MODIFIED
    assert list(accord_cp.lateralTuning.pid.kpV) == pytest.approx([0.3])
    assert list(accord_cp.lateralTuning.pid.kiV) == pytest.approx([0.09])

    crv_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TLA,A040\x00\x00', address=0x18DA30F1, subAddress=0)]
    crv_cp = CarInterface.get_params(CAR.HONDA_CRV_5G, gen_empty_fingerprint(), crv_fw, False, False, False, toggles)
    assert not crv_cp.dashcamOnly
    assert crv_cp.flags & HondaFlags.EPS_MODIFIED
    assert list(crv_cp.lateralParams.torqueBP) == [0, 4096]
    assert list(crv_cp.lateralParams.torqueV) == [0, 4096]
    # shares the same four-point handoff-at-25mph tune as the modified Civic above
    assert list(crv_cp.lateralTuning.pid.kpBP) == pytest.approx(civic_matched_bp)
    assert list(crv_cp.lateralTuning.pid.kiBP) == pytest.approx(civic_matched_bp)
    assert list(crv_cp.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
    assert list(crv_cp.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
    assert crv_cp.lateralTuning.pid.kf == pytest.approx(3.6e-6)
    assert crv_cp.steerAtStandstill
    assert crv_cp.minSteerSpeed == pytest.approx(-1.0)

  def test_modified_civic_bosch_keeps_official_support(self):
    toggles = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)
    car_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TGG,A020\x00\x00', address=0x18DA30F1, subAddress=0)]

    CP = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), car_fw, False, False, False, toggles)

    assert not CP.dashcamOnly
    assert CP.flags & HondaFlags.EPS_MODIFIED
    # NRDR: modified-EPS Hondas run the angle-space PID controller, as they do on nrdr-nightly
    assert CP.lateralTuning.which() == "pid"
    clarity_matched_bp = [0.0, 25.0 * CV.MPH_TO_MS - 1e-3, 25.0 * CV.MPH_TO_MS, 50.0 * CV.MPH_TO_MS]
    assert list(CP.lateralParams.torqueBP) == [0, 4096]
    assert list(CP.lateralParams.torqueV) == [0, 4096]
    assert list(CP.lateralTuning.pid.kpBP) == pytest.approx(clarity_matched_bp)
    assert list(CP.lateralTuning.pid.kiBP) == pytest.approx(clarity_matched_bp)
    assert list(CP.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
    assert list(CP.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
    assert CP.lateralTuning.pid.kf == pytest.approx(3.6e-6)

  def test_force_torque_toggle_still_overrides_modified_eps_pid(self):
    torque_toggles = SimpleNamespace(force_torque_controller=True, nnff=False, nnff_lite=False)
    car_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TGG,A020\x00\x00', address=0x18DA30F1, subAddress=0)]

    CP = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), car_fw, False, False, False, torque_toggles)

    assert CP.lateralTuning.which() == "torque"

  @pytest.mark.parametrize("toggle", ["force_torque_controller", "nnff", "nnff_lite"])
  def test_torque_conversion_uses_the_measured_modified_civic_bosch_tune(self, toggle):
    # The params.toml row is the stock EPS (LAF 1.69, friction 0.25): 3-6x stiffer than the PID on the modified rack.
    toggles = SimpleNamespace(**{**dict(force_torque_controller=False, nnff=False, nnff_lite=False), toggle: True})
    modified_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TGG,A020\x00\x00', address=0x18DA30F1, subAddress=0)]
    stock_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TGG-A120\x00\x00', address=0x18DA30F1, subAddress=0)]

    CP = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), modified_fw, False, False, False, toggles)
    assert CP.lateralTuning.which() == "torque"
    assert CP.lateralTuning.torque.latAccelFactor == pytest.approx(11.5)
    assert CP.lateralTuning.torque.friction == pytest.approx(0.025)
    assert CP.lateralTuning.torque.latAccelOffset == 0.0

    stock_cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), stock_fw, False, False, False, toggles)
    assert not stock_cp.flags & HondaFlags.EPS_MODIFIED
    assert stock_cp.lateralTuning.torque.latAccelFactor == pytest.approx(1.6917, abs=1e-3)
    assert stock_cp.lateralTuning.torque.friction == pytest.approx(0.2546, abs=1e-3)

    # unmeasured modified-EPS Hondas keep the table
    accord_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TVA,A150\x00\x00', address=0x18DA30F1, subAddress=0)]
    accord_cp = CarInterface.get_params(CAR.HONDA_ACCORD, gen_empty_fingerprint(), accord_fw, False, False, False, toggles)
    assert accord_cp.flags & HondaFlags.EPS_MODIFIED
    assert accord_cp.lateralTuning.torque.latAccelFactor != pytest.approx(11.5)

  def test_honda_clarity_supports_pid_and_torque_paths(self):
    pid_toggles = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)
    car_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TRW,A020\x00\x00', address=0x18DA30F1, subAddress=0)]

    pid_cp = CarInterface.get_params(CAR.HONDA_CLARITY, gen_empty_fingerprint(), car_fw, False, False, False, pid_toggles)

    assert not pid_cp.dashcamOnly
    assert pid_cp.flags & HondaFlags.EPS_MODIFIED
    assert pid_cp.lateralTuning.which() == "pid"
    # Modified EPS: 3840 command range and the road-tested hard handoff at 25 mph. The runtime
    # LatPScale/LatIScale params are neutral 100% so they trim rather than re-band this curve.
    assert list(pid_cp.lateralParams.torqueBP) == [0, 3840]
    assert list(pid_cp.lateralParams.torqueV) == [0, 3840]
    clarity_matched_bp = [0.0, 25.0 * CV.MPH_TO_MS - 1e-3, 25.0 * CV.MPH_TO_MS, 50.0 * CV.MPH_TO_MS]
    assert list(pid_cp.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
    assert list(pid_cp.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
    assert list(pid_cp.lateralTuning.pid.kpBP) == pytest.approx(clarity_matched_bp)
    assert list(pid_cp.lateralTuning.pid.kiBP) == pytest.approx(clarity_matched_bp)
    assert pid_cp.lateralTuning.pid.kf == pytest.approx(3.6e-6)
    assert pid_cp.autoResumeSng
    assert pid_cp.minEnableSpeed == pytest.approx(-1.0)
    assert pid_cp.stopAccel == pytest.approx(0.0)

    torque_toggles = SimpleNamespace(force_torque_controller=True, nnff=False, nnff_lite=False)
    torque_cp = CarInterface.get_params(CAR.HONDA_CLARITY, gen_empty_fingerprint(), car_fw, False, False, False, torque_toggles)

    assert torque_cp.lateralTuning.which() == "torque"

  def test_honda_clarity_is_marked_hybrid(self):
    CP = CarInterface.get_non_essential_params(CAR.HONDA_CLARITY)

    assert CP.flags & HondaFlags.HYBRID

  @pytest.mark.parametrize("car, frame, yaw_deg_s", [
    (CAR.HONDA_CLARITY, "989f88b60c000c72", 25.5),       # 610 counts, zero 508: a right turn on a Clarity route
    (CAR.HONDA_CLARITY, "645f4759f1000c62", -26.75),     # 401 counts: left turn, same route
    (CAR.HONDA_CLARITY, "7f5f4801f0000c72", 0.25),       # 509 counts: straight
    (CAR.HONDA_CIVIC_BOSCH, "8263880e02000c57", 1.952),  # 521 counts, zero 513, 0.244 deg/s: Peter's Civic
    (CAR.HONDA_CIVIC_BOSCH, "6d638735ea000c40", -18.544),  # 437 counts
    (CAR.HONDA_CIVIC_BOSCH, "806387ddfa000c48", 0.0),    # 513 counts
  ])
  def test_honda_yaw_rate_from_vsa(self, car, frame, yaw_deg_s):
    CP = CarInterface.get_non_essential_params(car)
    CI = CarInterface(CP, custom.StarPilotCarParams.new_message())
    cp, bus = CI.can_parsers[Bus.pt], CanBus(CP).pt
    cp.update([(1_000_000_000, [(0x94, bytes.fromhex(frame), bus)])])  # register KINEMATICS before its first frame
    cp.vl["KINEMATICS"]
    cp.update([(1_010_000_000, [(0x94, bytes.fromhex(frame), bus)])])

    d = bytes.fromhex(frame)
    assert cp.vl["KINEMATICS"]["YAW_RATE"] == pytest.approx(((d[0] << 2 | d[1] >> 6) - 512) * 0.25)  # nominal zero
    ret, _ = CI.CS.update(CI.can_parsers, get_test_starpilot_toggles())  # one frame: the seeded zero, nothing learned yet
    assert ret.yawRate == pytest.approx(-yaw_deg_s * CV.DEG_TO_RAD)  # left-positive, like steeringAngleDeg

  def test_honda_long_accel_scale(self):
    CP = CarInterface.get_non_essential_params(CAR.HONDA_CLARITY)
    cp = CarInterface(CP, custom.StarPilotCarParams.new_message()).can_parsers[Bus.pt]
    frame = bytes.fromhex("989f88b60c000c72")   # LONG_ACCEL raw +12 (braking) through the same right turn
    cp.update([(1_000_000_000, [(0x94, frame, 0)])])
    cp.vl["KINEMATICS"]
    cp.update([(1_010_000_000, [(0x94, frame, 0)])])
    assert cp.vl["KINEMATICS"]["LONG_ACCEL"] == pytest.approx(12 * -0.049)

  def test_yaw_rate_zero_is_learned_at_standstill(self):
    cal = YawRateCalibration(0.25, 508.0)
    to_dbc = lambda counts: (counts - 512.0) * 0.25  # noqa: E731
    assert cal.update(to_dbc(510.0), standstill=False) == pytest.approx(0.5)   # seeded zero 508
    for _ in range(yaw_rate.SETTLE_FRAMES):
      cal.update(to_dbc(530.0), standstill=True)       # still settling: ignored
    for _ in range(yaw_rate.LEARN_FRAMES - 1):
      cal.update(to_dbc(509.5), standstill=True)
    assert cal.zero == 508.0                            # not enough standstill yet
    assert cal.update(to_dbc(509.5), standstill=True) == pytest.approx(0.0)
    assert cal.zero == pytest.approx(509.5)
    assert cal.update(to_dbc(519.5), standstill=False) == pytest.approx(2.5)  # moving: learned zero kept
    assert cal.samples == 0

  def test_yaw_rate_zero_rejects_a_faulted_sensor(self):
    cal = YawRateCalibration(0.25, 508.0)
    for _ in range(yaw_rate.SETTLE_FRAMES + yaw_rate.LEARN_FRAMES + 10):
      cal.update((530.0 - 512.0) * 0.25, standstill=True)  # 18 counts off nominal
    assert cal.zero == 508.0

  def test_yaw_rate_only_on_checked_cars(self):
    assert get_yaw_rate_calibration(CAR.HONDA_CLARITY) is not None
    assert get_yaw_rate_calibration(CAR.HONDA_CIVIC_BOSCH) is not None
    assert get_yaw_rate_calibration(CAR.HONDA_ACCORD) is None

  def test_honda_clarity_brake_command_uses_hybrid_signals(self):
    class FakePacker:
      @staticmethod
      def make_can_msg(name, bus, values):
        return name, bus, values

    CAN = SimpleNamespace(pt=0)

    _, _, values = create_brake_command(
      FakePacker(),
      CAN,
      apply_brake=159,
      pump_on=True,
      pcm_override=True,
      pcm_cancel_cmd=False,
      fcw=False,
      car_fingerprint=CAR.HONDA_CLARITY,
      stock_brake={"CHIME": 0},
      honda_flags=HondaFlags.HYBRID,
    )

    assert values["COMPUTER_BRAKE_HYBRID"] == 159
    assert values["BRAKE_PUMP_REQUEST_HYBRID"] is True
    assert "COMPUTER_BRAKE" not in values
    assert "BRAKE_PUMP_REQUEST" not in values

  def test_canfd_bosch_alpha_long_is_available(self):
    toggles = get_test_toggles()

    CP = CarInterface.get_params(CAR.HONDA_PILOT_4G, gen_empty_fingerprint(), [], True, False, False, toggles)

    assert CP.alphaLongitudinalAvailable
    assert CP.openpilotLongitudinalControl
    assert CP.safetyConfigs[-1].safetyParam & HondaSafetyFlags.BOSCH_CANFD
    assert CP.safetyConfigs[-1].safetyParam & HondaSafetyFlags.BOSCH_LONG

  def test_mvl_handover_is_scoped_to_accord_11g(self):
    toggles = get_test_toggles()
    accord_cp = CarInterface.get_params(CAR.HONDA_ACCORD_11G, gen_empty_fingerprint(), [], True, False, False, toggles)
    crv_cp = CarInterface.get_params(CAR.HONDA_CRV_6G, gen_empty_fingerprint(), [], True, False, False, toggles)

    assert Bus.radar in DBC[accord_cp.carFingerprint]
    assert Bus.radar not in DBC[crv_cp.carFingerprint]
    assert accord_cp.safetyConfigs[-1].safetyParam & HondaSafetyFlags.BOSCH_CANFD_MVL
    assert not crv_cp.safetyConfigs[-1].safetyParam & HondaSafetyFlags.BOSCH_CANFD_MVL

  def test_nidec_pedal_detection_enables_interceptor_path(self):
    toggles = get_test_toggles()
    fingerprint = gen_empty_fingerprint()
    fingerprint[0][0x201] = 6

    CP = CarInterface.get_params(CAR.HONDA_CIVIC, fingerprint, [], False, False, False, toggles)
    accel_limits = CarInterface.get_pid_accel_limits(CP, current_speed=5.0, cruise_speed=12.0)

    assert CP.enableGasInterceptorDEPRECATED
    assert not CP.pcmCruise
    assert accel_limits == (CarControllerParams.NIDEC_ACCEL_MIN, CarControllerParams.NIDEC_ACCEL_MAX)

  def test_honda_camera_message_flag_uses_fingerprint_detection(self):
    toggles = get_test_toggles()
    fingerprint = gen_empty_fingerprint()
    fingerprint[0][0x35E] = 8

    CP = CarInterface.get_params(CAR.HONDA_ACCORD, fingerprint, [], True, False, False, toggles)
    FPCP = CarInterface.get_starpilot_params(CAR.HONDA_ACCORD, fingerprint, [], CP, toggles)

    assert FPCP.flags & HondaStarPilotFlags.HAS_CAMERA_MESSAGES

  def test_honda_live_learning_params_reload(self, monkeypatch):
    toggles = get_test_toggles()

    class FakeParams:
      def get_float(self, key, block=False, return_default=False, default=0.0):
        if key == "HondaGasFactorParams":
          return 1.25
        if key == "HondaWindFactorParams":
          return 0.85
        return default

    monkeypatch.setattr("opendbc.car.honda.carcontroller.Params", lambda: FakeParams())

    CP = CarInterface.get_params(CAR.HONDA_ACCORD, gen_empty_fingerprint(), [], True, False, False, toggles)
    controller = CarController(DBC[CP.carFingerprint], CP)

    assert controller.bosch_gas_factor == pytest.approx(1.25)
    assert controller.bosch_wind_factor == pytest.approx(0.85)

  def test_honda_bosch_controller_does_not_deepen_planner_braking(self, monkeypatch):
    toggles = get_test_toggles()
    CP = CarInterface.get_params(CAR.HONDA_HRV_3G, gen_empty_fingerprint(), [], True, False, False, toggles)
    controller = CarController(DBC[CP.carFingerprint], CP)

    monkeypatch.setattr("opendbc.car.honda.carcontroller.hondacan.create_steering_control", lambda *args, **kwargs: (0, []))
    monkeypatch.setattr("opendbc.car.honda.carcontroller.hondacan.create_acc_commands", lambda *args, **kwargs: [])

    CC = structs.CarControl.new_message()
    CC.enabled = True
    CC.longActive = True
    CC.latActive = False
    CC.cruiseControl.cancel = False
    CC.cruiseControl.resume = False
    CC.hudControl.speedVisible = False
    CC.hudControl.setSpeed = 0.0
    CC.hudControl.visualAlert = structs.CarControl.HUDControl.VisualAlert.none
    CC.actuators.accel = -0.3
    CC.actuators.torque = 0.0
    CC.actuators.longControlState = structs.CarControl.Actuators.LongControlState.pid

    controller.frame = 2
    CS = SimpleNamespace(
      out=SimpleNamespace(vEgo=25.0, aEgo=1.5, steeringPressed=False, gasPressed=False, brakePressed=False),
      v_cruise_factor=1.0,
    )

    new_actuators, _ = controller.update(CC.as_reader(), CS, 0, toggles)
    assert new_actuators.accel == pytest.approx(-0.3)

  def test_honda_hrv_3g_uses_matched_longitudinal_delay(self):
    toggles = get_test_toggles()

    hrv3g_cp = CarInterface.get_params(CAR.HONDA_HRV_3G, gen_empty_fingerprint(), [], True, False, False, toggles)
    accord_cp = CarInterface.get_params(CAR.HONDA_ACCORD, gen_empty_fingerprint(), [], True, False, False, toggles)

    assert hrv3g_cp.longitudinalActuatorDelay == pytest.approx(0.4)
    assert accord_cp.longitudinalActuatorDelay == pytest.approx(0.5)


class TestHondaSteeringCommandFidelity:
  """actuatorsOutput.torque may differ from actuators.torque ONLY when the car cannot deliver it.

  controlsd infers steer_limited_by_safety from that difference and uses it to freeze the lateral
  integrator, so any comfort shaping applied on this path is indistinguishable from safety
  limiting. The torque LPF that used to live here held a steady-state gap of tau * slew, which
  tripped the 1e-2 threshold continuously and kept the integrator frozen for whole drives.
  """

  LIVE_DEFAULTS = {
    "override_fade_down_s": 0.0,
    "override_fade_up_s": 1.5,
    "override_torque_scale": 0.0,
    "increase_override_tolerance": False,
    "steer_delta_limiter_enabled": False,
    "steer_delta_up": 3.0,
    "steer_delta_down": 3.0,
    "driver_assist_during_override": False,
    "min_steer_speed": 1.0 * CV.MPH_TO_MS,
  }

  @staticmethod
  def _controller():
    CP = CarInterface.get_non_essential_params(CAR.HONDA_CLARITY)
    CP.flags |= int(HondaFlags.EPS_MODIFIED)
    return CarController(DBC[CP.carFingerprint], CP)

  @staticmethod
  def _cc(torque, lat_active=True):
    CC = structs.CarControl.new_message()
    CC.latActive = lat_active
    CC.actuators.torque = torque
    return CC

  @staticmethod
  def _cs(v_ego=20.0, steering_pressed=False, steering_torque=0.0, steer_threshold=None):
    cs = SimpleNamespace(out=SimpleNamespace(vEgo=v_ego, steeringPressed=steering_pressed, steeringTorque=steering_torque))
    if steer_threshold is not None:
      cs.steer_threshold = steer_threshold
    return cs

  def _drive(self, controller, torques, live=None, **cs_kwargs):
    live = {**self.LIVE_DEFAULTS, **(live or {})}
    delivered = []
    for torque in torques:
      out, _, _ = controller._update_steering_torque(self._cc(torque), self._cs(**cs_kwargs), live)
      delivered.append(out)
    return delivered

  def test_command_is_delivered_unchanged_once_the_override_ramp_is_up(self):
    # The default path must be bit-for-bit transparent, or steer_limited_by_safety latches True.
    controller = self._controller()
    self._drive(controller, [0.0] * 200)  # let the engage ramp finish

    commands = [0.10, 0.35, -0.20, 0.80, -0.75, 0.0]
    assert self._drive(controller, commands) == pytest.approx(commands)

  def test_a_moving_command_is_not_reported_as_limited(self):
    # The regression itself: a fast ramp used to leave a tau * slew gap on every frame.
    controller = self._controller()
    self._drive(controller, [0.0] * 200)

    ramp = [0.01 * n for n in range(60)]  # 1.0 authority/s, 10x the old trip threshold
    delivered = self._drive(controller, ramp)

    assert all(abs(cmd - out) <= 1e-2 for cmd, out in zip(ramp, delivered, strict=True))

  def test_min_steer_speed_zeroing_is_reported_as_limited(self):
    controller = self._controller()
    delivered = self._drive(controller, [0.5], v_ego=0.0)
    assert delivered == [0.0]

  def test_override_cut_is_reported_as_limited(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    delivered = self._drive(controller, [0.5] * cc_mod.OVERRIDE_ONSET_FRAMES, steering_pressed=True)
    assert abs(0.5 - delivered[-1]) > 1e-2

  # Route 283's fade settings (HondaOverrideFadeDownSecs 0.2, HondaOverrideFadeUpSecs 0.5).
  LIVE_283 = {"override_fade_down_s": 0.2, "override_fade_up_s": 0.5}

  def _drive_frames(self, controller, frames, torque=0.5, threshold=2000.0):
    # frames: (raw_pressed, sensor_torque) per control frame; returns the override ramp after each.
    live = {**self.LIVE_DEFAULTS, **self.LIVE_283}
    ramps = []
    for pressed, sensor in frames:
      controller._update_steering_torque(self._cc(torque), self._cs(steering_pressed=pressed, steering_torque=sensor,
                                                                    steer_threshold=threshold), live)
      ramps.append(controller.override_ramp)
    return ramps

  def test_hands_holding_blips_do_not_cut_the_output(self):
    # Routes 283/284 pattern: 1-5 frame blips at 2005-2300 against a 2000 threshold while hands hold.
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    cycle = [(True, 2300.0)] * 5 + [(False, 1600.0)] * 8
    ramps = self._drive_frames(controller, cycle * 10, threshold=2000.0)
    assert min(ramps) == pytest.approx(1.0)
    assert not controller.override_held

  def test_sustained_press_at_the_threshold_confirms_after_the_onset_window(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    n = cc_mod.OVERRIDE_ONSET_FRAMES
    ramps = self._drive_frames(controller, [(True, 2100.0)] * (n + 5))
    assert ramps[n - 2] == pytest.approx(1.0) and controller.override_held and ramps[-1] < 1.0

  def test_firm_press_confirms_on_the_first_frame(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    self._drive_frames(controller, [(True, 2000.0 * cc_mod.OVERRIDE_INSTANT_FRAC)])
    assert controller.override_held

  def test_onset_counter_is_leaky_not_reset_by_a_one_frame_dropout(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    self._drive_frames(controller, [(True, 2100.0)] * 5 + [(False, 1900.0)] + [(True, 2100.0)] * 4)
    assert controller.override_held

  def test_override_releases_after_hold_once_sensor_unloads(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    self._drive_frames(controller, [(True, 2500.0)] * 5)
    assert controller.override_held
    hold_frames = round(cc_mod.OVERRIDE_RELEASE_HOLD_S / cc_mod.DT_CTRL)
    ramps = self._drive_frames(controller, [(False, 200.0)] * (hold_frames + 20))
    assert all(b <= a + 1e-9 for a, b in zip(ramps[:hold_frames - 1], ramps[1:hold_frames - 1], strict=False))  # held: no fade-up
    assert ramps[-1] > ramps[hold_frames]                      # then fades back up
    assert not controller.override_held

  def test_override_stays_held_while_sensor_is_above_release_level(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    self._drive_frames(controller, [(True, 2500.0)] * 5)
    self._drive_frames(controller, [(False, 1600.0)] * 200)  # 2 s at 0.8 x threshold
    assert controller.override_held
    self._drive_frames(controller, [(False, 1400.0)])        # below 0.75 x threshold
    assert not controller.override_held

  def test_hold_steering_pressed_without_a_threshold_uses_time_only(self):
    held, hold_s = cc_mod.hold_steering_pressed(True, 0.0, None, False, 0.0)
    assert held and hold_s == pytest.approx(cc_mod.OVERRIDE_RELEASE_HOLD_S)
    n = 0
    while held:
      held, hold_s = cc_mod.hold_steering_pressed(False, 5000.0, None, held, hold_s)
      n += 1
    assert n == round(cc_mod.OVERRIDE_RELEASE_HOLD_S / cc_mod.DT_CTRL)

  # Same-direction assist (NrdrSameDirectionAssist, STATUS 182). Routes 28a/28b fades: up 0.5 s, down 0.
  LIVE_28A = {"override_fade_down_s": 0.0, "override_fade_up_s": 0.5, "same_direction_assist": True}

  def _press(self, controller, frames, live=None, v_ego=6.0, threshold=2000.0):
    # frames: (command, sensor_torque) with the raw press flag set; returns delivered torque per frame.
    live = {**self.LIVE_DEFAULTS, **self.LIVE_28A, **(live or {})}
    out = []
    for cmd, sensor in frames:
      pressed = abs(sensor) > threshold
      delivered, _, _ = controller._update_steering_torque(
        self._cc(cmd), self._cs(v_ego=v_ego, steering_pressed=pressed, steering_torque=sensor, steer_threshold=threshold), live)
      out.append(delivered)
    return out

  def _ready(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    return controller

  @staticmethod
  def _transitions(delivered):
    on = [abs(x) > 1e-3 for x in delivered]
    return sum(a != b for a, b in zip(on, on[1:], strict=False))

  def test_same_direction_help_press_keeps_torque_without_chatter(self):
    # 28b 2:04 shape: firm same-sign help around 2600 with +/-150 jitter, 5 s.
    controller = self._ready()
    frames = [(0.8, 2600.0 + (150.0 if (n // 10) % 2 else -150.0)) for n in range(500)]
    out = self._press(controller, frames)
    assert out[-1] == pytest.approx(0.8)
    assert self._transitions(out[30:]) == 0
    # The debounce still cuts first (fade down 0); the exemption then fades torque back in without a step.
    assert max(abs(x) for x in out[6:20]) == 0.0
    assert max(abs(b - a) for a, b in zip(out[6:], out[7:], strict=False)) < 0.05

  def test_toggle_off_keeps_the_cut(self):
    controller = self._ready()
    out = self._press(controller, [(0.8, 2600.0)] * 300, live={"same_direction_assist": False})
    assert max(abs(x) for x in out[10:]) == 0.0

  def test_opposite_press_cuts_and_exemption_needs_the_entry_hold(self):
    # 28b 2:04: 0.5 s opposite (driver turns before the plan), then same sign.
    controller = self._ready()
    out = self._press(controller, [(-0.6, 2400.0)] * 50 + [(0.8, 2600.0)] * 200)
    assert max(abs(x) for x in out[6:50]) == 0.0
    entry = round(cc_mod.SAME_DIR_ENTRY_S / cc_mod.DT_CTRL)
    assert max(abs(x) for x in out[50:50 + entry - 1]) == 0.0
    assert out[-1] > 0.5

  def test_a_short_same_sign_blip_at_the_start_of_a_fight_is_not_exempted(self):
    controller = self._ready()
    out = self._press(controller, [(0.8, 2400.0)] * 10 + [(0.8, -2400.0)] * 100)
    assert max(abs(x) for x in out) < 1e-9 or max(abs(x) for x in out[10:]) == 0.0

  def test_press_above_the_ceiling_cuts_at_once(self):
    controller = self._ready()
    self._press(controller, [(0.8, 2600.0)] * 100)
    out = self._press(controller, [(0.8, 2000.0 * cc_mod.SAME_DIR_CEILING_FRAC + 1.0)])
    assert out[-1] == 0.0

  def test_time_cap_fades_out_and_holds_until_release(self):
    controller = self._ready()
    n = round((cc_mod.SAME_DIR_MAX_S + 1.0) / cc_mod.DT_CTRL)
    out = self._press(controller, [(0.8, 2600.0)] * n)
    cap = round((cc_mod.SAME_DIR_MAX_S + cc_mod.SAME_DIR_ENTRY_S) / cc_mod.DT_CTRL)
    assert out[cap - 10] == pytest.approx(0.8)
    assert out[-1] == 0.0
    assert max(abs(b - a) for a, b in zip(out[cap - 20:], out[cap - 19:], strict=False)) < 0.05  # faded, not stepped

  def test_letting_go_of_a_help_press_keeps_the_torque(self):
    # MetaDrive logic test on 087646dc: the release hold kept the press while |tq| fell to 0, and tq * cmd = 0
    # read as a fight, so every help release stepped 0.8 -> 0.
    controller = self._ready()
    self._press(controller, [(0.8, 2600.0)] * 200)
    out = self._press(controller, [(0.8, 2600.0 - 260.0 * n) for n in range(10)] + [(0.8, 0.0)] * 100)
    assert min(out) == pytest.approx(0.8)

  def test_a_grip_hovering_at_the_ceiling_does_not_toggle_the_torque(self):
    # MetaDrive: 3500 +/- 100 at 5 Hz gave 38 edges in 4 s.
    controller = self._ready()
    self._press(controller, [(0.8, 2600.0)] * 100)
    ceiling = 2000.0 * cc_mod.SAME_DIR_CEILING_FRAC
    out = self._press(controller, [(0.8, ceiling + (-100.0 if (n // 10) % 2 else 100.0)) for n in range(400)])
    assert self._transitions(out) == 0
    assert max(abs(x) for x in out) == 0.0
    # back under the re-entry level for the entry hold, the help is kept again
    out = self._press(controller, [(0.8, 2600.0)] * 100)
    assert out[-1] == pytest.approx(0.8)

  def test_speed_hovering_at_the_band_edge_exits_once(self):
    # MetaDrive: 25 +/- 0.5 mph at 0.5 Hz gave 6 transitions.
    controller = self._ready()
    self._press(controller, [(0.8, 2600.0)] * 100)
    out = []
    for n in range(800):
      v = cc_mod.SAME_DIR_MAX_SPEED + (0.25 if (n // 100) % 2 == 0 else -0.25)
      out += self._press(controller, [(0.8, 2600.0)], v_ego=v)
    assert self._transitions(out) == 1
    assert out[-1] == 0.0

  def test_above_the_speed_band_the_press_cuts(self):
    controller = self._ready()
    out = self._press(controller, [(0.8, 2600.0)] * 200, v_ego=cc_mod.SAME_DIR_MAX_SPEED + 0.5)
    assert max(abs(x) for x in out[10:]) == 0.0

  def test_command_crossing_zero_holds_then_cuts_once_it_is_a_fight(self):
    # Plan crosses the wheel while the hand holds: command sweeps +0.3 -> -0.3 slowly.
    controller = self._ready()
    self._press(controller, [(0.3, 2600.0)] * 100)
    sweep = [0.3 - 0.6 * n / 200 for n in range(200)]
    out, exempt = [], []
    for cmd in sweep:
      out += self._press(controller, [(cmd, 2600.0)])
      exempt.append(controller.same_dir_assist.exempt)
    neutral_end = next(i for i, cmd in enumerate(sweep) if cmd <= -cc_mod.SAME_DIR_MIN_CMD)
    assert all(exempt[:neutral_end])  # neutral band keeps the state, no flicker
    assert not any(exempt[neutral_end:])  # command now opposes the hand: a fight, cut
    assert max(abs(x) for x in out[neutral_end:]) == 0.0
    assert max(abs(b - a) for a, b in zip(out, out[1:], strict=False)) <= cc_mod.SAME_DIR_MIN_CMD + 1e-6

  def test_steer_delta_limiter_is_reported_as_limited(self):
    controller = self._controller()
    self._drive(controller, [0.0] * 200)
    delivered = self._drive(controller, [1.0], live={"steer_delta_limiter_enabled": True})
    assert abs(1.0 - delivered[0]) > 1e-2
