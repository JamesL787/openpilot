from types import SimpleNamespace

from openpilot.common.parameterized import parameterized

from cereal import car, log
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR as HONDA
from opendbc.car.toyota.values import CAR as TOYOTA
from opendbc.car.nissan.values import CAR as NISSAN
from opendbc.car.gm.values import CAR as GM
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.car.helpers import convert_to_capnp
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque
from openpilot.selfdrive.controls.lib.latcontrol_torque_starpilot import (
  get_clarity_nidec_ff_scale,
  get_clarity_nidec_friction_scale,
)
from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle
from openpilot.selfdrive.locationd.helpers import Pose
from openpilot.common.mock.generators import generate_livePose
from openpilot.sunnypilot.selfdrive.car import interfaces as sunnypilot_interfaces
from openpilot.sunnypilot.selfdrive.controls.controlsd_ext import ControlsExt
from opendbc.sunnypilot.car.honda.values_ext import HondaFlagsSP


class TestLatControl:

  @parameterized.expand([(HONDA.HONDA_CIVIC, LatControlPID), (TOYOTA.TOYOTA_RAV4, LatControlTorque),
                         (NISSAN.NISSAN_LEAF, LatControlAngle), (GM.CHEVROLET_BOLT_EUV, LatControlTorque)])
  def test_saturation(self, car_name, controller):
    CarInterface = interfaces[car_name]
    CP = CarInterface.get_non_essential_params(car_name)
    CP_SP = CarInterface.get_non_essential_params_sp(CP, car_name)
    CI = CarInterface(CP, CP_SP)
    sunnypilot_interfaces.setup_interfaces(CI)
    CP_SP = convert_to_capnp(CP_SP)
    VM = VehicleModel(CP)

    controller = controller(CP.as_reader(), CP_SP.as_reader(), CI, DT_CTRL)

    CS = car.CarState.new_message()
    CS.vEgo = 30
    CS.steeringPressed = False

    params = log.LiveParametersData.new_message()

    lp = generate_livePose()
    pose = Pose.from_live_pose(lp.livePose)

    # Saturate for curvature limited and controller limited
    for _ in range(1000):
      _, _, lac_log = controller.update(True, CS, VM, params, False, 0, pose, True, 0.2)
    assert lac_log.saturated

    for _ in range(1000):
      _, _, lac_log = controller.update(True, CS, VM, params, False, 0, pose, False, 0.2)
    assert not lac_log.saturated

    for _ in range(1000):
      _, _, lac_log = controller.update(True, CS, VM, params, False, 1, pose, False, 0.2)
    assert lac_log.saturated


class TestControlsExt:

  @staticmethod
  def _build_controls_ext(
    car_fingerprint: str,
    lateral_tuning: str,
    params_bools: dict[str, bool] | None = None,
    params_values: dict[str, float] | None = None,
    cp_sp_flags: int | None = None,
  ):
    controls_ext = ControlsExt.__new__(ControlsExt)
    controls_ext.CP = SimpleNamespace(
      carFingerprint=car_fingerprint,
      lateralTuning=SimpleNamespace(which=lambda: lateral_tuning),
    )
    controls_ext.CP_SP = SimpleNamespace(flags=int(HondaFlagsSP.EPS_MODIFIED.value if cp_sp_flags is None else cp_sp_flags))
    controls_ext.params = SimpleNamespace(
      get_bool=lambda name: bool((params_bools or {}).get(name, False)),
      get=lambda name: (params_values or {}).get(name, 0.0),
    )
    return controls_ext

  def test_honda_torque_version_two_selects_new_controller(self, monkeypatch):
    lac = object()
    starpilot = object()
    captured = {}

    def _capture(*args, **kwargs):
      captured.update(kwargs)
      return starpilot

    monkeypatch.setattr(
      "openpilot.sunnypilot.selfdrive.controls.controlsd_ext.LatControlTorqueStarpilot",
      _capture,
    )

    controls_ext = self._build_controls_ext(
      HONDA.HONDA_CLARITY,
      "torque",
      {"EnforceTorqueControl": True},
      {"TorqueControlTune": 2.0},
    )
    assert controls_ext.initialize_lateral_control(lac, object(), 0.01) is starpilot
    assert captured["honda_firestar"] is False

  def test_honda_torque_version_two_passes_firestar_flag(self, monkeypatch):
    lac = object()
    starpilot = object()
    captured = {}

    def _capture(*args, **kwargs):
      captured.update(kwargs)
      return starpilot

    monkeypatch.setattr(
      "openpilot.sunnypilot.selfdrive.controls.controlsd_ext.LatControlTorqueStarpilot",
      _capture,
    )

    controls_ext = self._build_controls_ext(
      HONDA.HONDA_CLARITY,
      "torque",
      {"EnforceTorqueControl": True, "HondaTorqueFirestarTune": True},
      {"TorqueControlTune": 2.0},
    )
    assert controls_ext.initialize_lateral_control(lac, object(), 0.01) is starpilot
    assert captured["honda_firestar"] is True

  def test_honda_torque_version_requires_enforce_lateral_torque(self, monkeypatch):
    lac = object()
    starpilot = object()
    monkeypatch.setattr(
      "openpilot.sunnypilot.selfdrive.controls.controlsd_ext.LatControlTorqueStarpilot",
      lambda *args, **kwargs: starpilot,
    )

    controls_ext = self._build_controls_ext(
      HONDA.HONDA_CLARITY,
      "torque",
      {"EnforceTorqueControl": False, "HondaTorqueFirestarTune": True},
      {"TorqueControlTune": 2.0},
    )
    assert controls_ext.initialize_lateral_control(lac, object(), 0.01) is lac

  def test_honda_torque_version_defaults_to_existing_controller(self, monkeypatch):
    lac = object()
    v0 = object()
    monkeypatch.setattr(
      "openpilot.sunnypilot.selfdrive.controls.controlsd_ext.LatControlTorqueV0",
      lambda *args, **kwargs: v0,
    )

    controls_ext = self._build_controls_ext(
      HONDA.HONDA_CLARITY,
      "torque",
      {"EnforceTorqueControl": True},
      {"TorqueControlTune": 1.0},
    )
    assert controls_ext.initialize_lateral_control(lac, object(), 0.01) is lac

  def test_honda_torque_version_does_not_override_angle_pid(self, monkeypatch):
    lac = object()
    starpilot = object()
    monkeypatch.setattr(
      "openpilot.sunnypilot.selfdrive.controls.controlsd_ext.LatControlTorqueStarpilot",
      lambda *args, **kwargs: starpilot,
    )

    controls_ext = self._build_controls_ext(
      HONDA.HONDA_CLARITY,
      "pid",
      {"EnforceTorqueControl": True},
      {"TorqueControlTune": 2.0},
    )
    assert controls_ext.initialize_lateral_control(lac, object(), 0.01) is lac

  def test_non_honda_torque_falls_back_to_legacy_path(self, monkeypatch):
    lac = object()
    monkeypatch.setattr(
      "openpilot.sunnypilot.selfdrive.controls.controlsd_ext.LatControlTorqueV0",
      lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
      "openpilot.sunnypilot.selfdrive.controls.controlsd_ext.LatControlTorqueStarpilot",
      lambda *args, **kwargs: object(),
    )

    controls_ext = self._build_controls_ext(
      "not_honda",
      "torque",
      {"EnforceTorqueControl": True},
      {"TorqueControlTune": 2.0},
      cp_sp_flags=0,
    )
    assert controls_ext.initialize_lateral_control(lac, object(), 0.01) is lac

  def test_clarity_firestar_changes_torque_shapes(self):
    stock_ff = get_clarity_nidec_ff_scale(0.5, 0.8, 12.0, False)
    firestar_ff = get_clarity_nidec_ff_scale(0.5, 0.8, 12.0, True)
    stock_friction = get_clarity_nidec_friction_scale(12.0, 0.5, 0.8, False)
    firestar_friction = get_clarity_nidec_friction_scale(12.0, 0.5, 0.8, True)

    assert firestar_ff < stock_ff
    assert firestar_friction > stock_friction
