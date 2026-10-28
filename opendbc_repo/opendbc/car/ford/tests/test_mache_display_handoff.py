"""Recorded Mach-E turn inputs retain Dom display state across steering handoff."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.can import CANParser
from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.ford.carcontroller import CarController
from opendbc.car.ford.carstate import CarState
from opendbc.car.ford.interface import CarInterface
from opendbc.car.ford.values import CAR, DBC
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests import test_ford_aol
from openpilot.common.params import Params, ParamKeyFlag, ParamKeyType
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.starpilot.car.ford.cluster_preferences import FordClusterPreference, KEY


class RecordedPreview:
  def __init__(self):
    self.model = SimpleNamespace(orientationRate=SimpleNamespace(z=[0.] * 33),
                                 meta=SimpleNamespace(laneChangeState=0, laneChangeDirection=0))

  def update(self):
    pass

  def apply_blend_settings(self, controller):
    lateral = controller.mache_lateral or controller.classic_lateral
    lateral.set_blend_settings(.4, .4, .85)

  def lateral_snapshot(self, speed):
    return self.model, ModelConstants.T_IDXS, .2, True

  def assist_permission(self):
    return (), False


def run_turn(*, hands_free, angle, torque, desired, speed, yaw, identity=CAR.FORD_MUSTANG_MACH_E_MK1):
  native = test_ford_aol.TestFordAolDriverIntent()
  native.setUp()
  native.reset(18 if identity == CAR.FORD_MUSTANG_MACH_E_MK1 else 66)
  native.arm()
  with OpenpilotPrefix():
    saved = Params()
    Path(saved.get_param_path(KEY)).write_bytes(b"1" if hands_free else b"0")
    fingerprint = gen_empty_fingerprint()
    fingerprint[0].update({0x5A: 8, 0x3A6: 8, 0x3A7: 8})
    fingerprint[2].update({0x3D6: 8, 0x186: 8})
    cp = CarInterface.get_params(identity, fingerprint, [], False, False, False)
    cp.alternativeExperience = 32
    assert cp.safetyConfigs[-1].safetyParam == (18 if identity == CAR.FORD_MUSTANG_MACH_E_MK1 else 66)
    assert cp.flags == 3
    controller = CarController(DBC[cp.carFingerprint], cp)
    controller.hands_free_cluster_input = FordClusterPreference(saved)
    controller.manual_turn_inputs = RecordedPreview()
    state = CarState(cp)
    state.update(state.get_can_parsers(cp))
    cs = structs.CarState(canValid=True, vEgo=speed, vEgoRaw=speed, yawRate=yaw,
                         gearShifter=structs.CarState.GearShifter.drive)
    cs.cruiseState.available = True
    command = structs.CarControl(latActive=False)
    command.actuators.curvature = desired
    state.acc_tja_status_stock_values['FcwVisblWarn_B_Rq'] = 1
    state.acc_tja_status_stock_values['FcwAudioWarn_B_Rq'] = 1
    parser = CANParser('ford_lincoln_base_pt', [('ACCDATA_3', 5)], 0)
    steering = []
    displays = []

    def step():
      native.pump(1, mask=int(command.latActive), speed=speed, curvature=yaw / speed)
      state.out = cs.as_reader()
      _, frames = controller.update(command.as_reader(), state, (1_000_000 + native.tick * 10_000) * 1000)
      if identity != CAR.FORD_MUSTANG_MACH_E_MK1:
        lateral_frames = [(index, data) for index, (address, data, _) in enumerate(frames) if address == 0x3D6]
        announcements = [(index, data) for index, (address, data, _) in enumerate(frames) if address == 0x3CA]
        assert len(announcements) <= 1
        for index, data in lateral_frames:
          active = ((data[0] >> 4) & 7) != 0
          previous_active = bool(steering and ((steering[-1][0] >> 4) & 7))
          if active != previous_active:
            assert announcements and announcements[0][0] < index
            assert bool(announcements[0][1][4] & 2) == active
        if not command.latActive:
          assert all(not (data[4] & 2) for _, data in announcements)
      for address, data, bus in frames:
        assert native.safety.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data))
        if address == 0x3D6:
          steering.append(bytes(data))
        if address == 0x18A:
          parser.update([(native.tick * 10_000_000, [(address, data, bus)])])
          displays.append(dict(parser.vl['ACCDATA_3']))
      return frames

    # Startup remains stock until an active replacement is actually accepted.
    for _ in range(25):
      assert not {address for address, _, _ in step()} & {0x18A, 0x3D8}
      assert native.safety.safety_fwd_hook(2, 0x18A) == 0
    native.arm()
    command.latActive = True
    for _ in range(60):
      step()
    assert displays and displays[-1]['Tja_D_Stat'] == (7 if hands_free else 2)
    assert native.safety.aol_get_permission_mask() == 1
    assert native.safety.safety_fwd_hook(2, 0x18A) == -1

    # Both original onset tuples have driver input, a right signal and >12deg.
    cs.steeringPressed = True
    cs.steeringAngleDeg = angle
    cs.steeringTorque = torque
    cs.rightBlinker = True
    if identity != CAR.FORD_MUSTANG_MACH_E_MK1:
      # Generic curvature retains its existing 45deg/3s preturned detector.
      for _ in range(310):
        step()
    count = len(displays)
    for _ in range(40):
      frames = step()
      if any(address == 0x3D6 for address, _, _ in frames):
        assert ((steering[-1][0] >> 4) & 7) == 0
        assert native.safety.safety_fwd_hook(2, 0x3D6) == 0
        assert native.safety.safety_fwd_hook(2, 0x18A) == -1
        assert native.safety.safety_fwd_hook(2, 0x3D8) == -1
      assert native.safety.aol_get_permission_mask() == 1
    assert len(displays) > count
    for display in displays[count:]:
      assert display['Tja_D_Stat'] == (7 if hands_free else 2)
      assert display['FcwVisblWarn_B_Rq'] == 1
      assert display['FcwAudioWarn_B_Rq'] == 1

    cs.steeringPressed = False
    cs.steeringAngleDeg = 0.
    cs.steeringTorque = 0.
    cs.rightBlinker = False
    for _ in range(50):
      step()
    assert ((steering[-1][0] >> 4) & 7) == 1
    assert displays[-1]['Tja_D_Stat'] == (7 if hands_free else 2)
    command.latActive = False
    for _ in range(25):
      assert not {address for address, _, _ in step()} & {0x18A, 0x3D8}
    assert native.safety.safety_fwd_hook(2, 0x18A) == 0
    assert native.safety.safety_fwd_hook(2, 0x3D8) == 0
    assert native.safety.aol_get_permission_mask() == 0
    return steering


@pytest.mark.parametrize('angle,torque,desired,speed,yaw', [
  (-12.2, -1.6875, .000041086183, 2.55, -.006),
  (-38.7, -2., -.000324735534, 2.563888788, -.033),
])
def test_recorded_turn_keeps_dom_display_and_hands_free_does_not_change_steering(angle, torque, desired, speed, yaw):
  hands_free = run_turn(hands_free=True, angle=angle, torque=torque, desired=desired, speed=speed, yaw=yaw)
  plain = run_turn(hands_free=False, angle=angle, torque=torque, desired=desired, speed=speed, yaw=yaw)
  assert plain == hands_free


@pytest.mark.parametrize('saved', [False, True])
@pytest.mark.parametrize('flag', [ParamKeyFlag.CLEAR_ON_MANAGER_START, ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION,
                                 ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION, ParamKeyFlag.CLEAR_ON_IGNITION_ON])
def test_cluster_preference_survives_native_cleanup(tmp_path, saved, flag):
  params = Params(str(tmp_path))
  key = 'FordHandsFreeCluster'
  assert params.check_key(key) and params.get_type(key) == ParamKeyType.BOOL
  params.put(key, saved, block=True)
  sentinel = Path(params.get_param_path('FordUnregisteredSentinel'))
  sentinel.write_bytes(b'1')
  params.clear_all(flag)
  assert params.get(key) == saved and not sentinel.exists()
  reopened = Params(str(tmp_path))
  assert reopened.get(key) == saved
  assert Path(reopened.get_param_path(key)).read_bytes() == (b'1' if saved else b'0')
  assert FordClusterPreference(reopened).enabled == saved


@pytest.mark.parametrize('identity', [CAR.FORD_ESCAPE_MK4_5, CAR.FORD_EXPEDITION_MK4, CAR.FORD_F_150_MK14,
                                      CAR.FORD_F_150_LIGHTNING_MK1, CAR.FORD_RANGER_MK2])
def test_generic_curvature_native_display_handoff_retains_hands_free_during_manual_turn(identity):
  # Nonzero demand exercises the bounded first-active command, not just UI.
  inputs = dict(identity=identity, angle=-55., torque=-2., desired=.000041086183, speed=2.55, yaw=-.006)
  hands_free = run_turn(hands_free=True, **inputs)
  plain = run_turn(hands_free=False, **inputs)
  assert plain == hands_free
