"""Closed, init-only measurement selection; disabled behavior stays unchanged."""
from types import SimpleNamespace

import pytest
from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.ford.interface import CarInterface
from opendbc.car.ford.pinion import GEOMETRY, ENABLE, SHIFT, MASK, decode, select, configured, Measurement
from opendbc.car.ford.aol import qualified
from opendbc.car.vehicle_model import VehicleModel, calc_slip_factor
from opendbc.can.packer import CANPacker
from opendbc.safety.tests.libsafety import libsafety_py


def params(car, long=False):
  fp = gen_empty_fingerprint()
  fp[0][0x5A] = 8
  fp[2].update({0x3D6: 8, 0x186: 8})
  return CarInterface.get_params(car, fp, [], long, False, False)


def test_closed_decoder_matches_native_exhaustively():
  n = libsafety_py.libsafety
  for word in range(65536):
    decoded = decode(word)
    assert n.get_ford_pinion_base(word) == (decoded[0] if decoded is not None else 65535)


@pytest.mark.parametrize('car', list(GEOMETRY))
@pytest.mark.parametrize('long', [False, True])
def test_default_off_and_exact_geometry_selection(car, long):
  cp = params(car, long)
  before = cp.to_dict()
  assert not select(cp, False)
  assert cp.to_dict() == before
  assert select(cp, True)
  assert configured(cp) and qualified(cp)
  assert decode(cp.safetyConfigs[-1].safetyParam)[1] == GEOMETRY[car]
  # Cross-family/identity corruption is not accepted by the host.
  cp.safetyConfigs[-1].safetyParam = (cp.safetyConfigs[-1].safetyParam & ~MASK) | ENABLE | ((GEOMETRY[car] % 12 + 1) << SHIFT)
  assert not configured(cp) and not qualified(cp)


@pytest.mark.parametrize('car', list(GEOMETRY))
def test_geometry_matches_actual_vehicle_model_and_native_sign(car):
  cp = params(car)
  index = GEOMETRY[car]
  n = libsafety_py.libsafety
  vm = VehicleModel(cp)
  assert n.get_ford_pinion_slip(index) == pytest.approx(calc_slip_factor(vm), abs=2e-10)
  assert n.get_ford_pinion_ratio(index) == pytest.approx(cp.steerRatio)
  assert n.get_ford_pinion_wheelbase(index) == pytest.approx(cp.wheelbase)
  assert select(cp, True)
  host = Measurement(cp)
  packer = CANPacker('ford_lincoln_base_pt')
  for speed in (0., 5., 15., 30.):
    for angle in (-100., -10., 0., 10., 100.):
      n.set_alternative_experience(0)
      n.set_safety_hooks(structs.CarParams.SafetyModel.ford, cp.safetyConfigs[-1].safetyParam)
      assert n.get_ford_pinion_enabled()
      for counter in range(6):
        a, d, b = packer.make_can_msg('BrakeSysFeatures', 0, {'Veh_V_ActlBrk': speed * 3.6, 'VehVActlBrk_D_Qf': 3})
        assert n.safety_rx_hook(libsafety_py.make_CANPacket(a, b, d))
        a, d, b = packer.make_can_msg('SteeringPinion_Data', 0, {'StePinComp_An_Est': angle, 'StePinCompAnEst_D_Qf': 3, 'StePinAn_No_Cnt': counter})
        assert n.safety_rx_hook(libsafety_py.make_CANPacket(a, b, d))
      state = SimpleNamespace(vEgoRaw=max(speed, .1), yawRate=99., steeringAngleDeg=angle)
      expected = -host.curvature(state) * 50000
      assert n.get_curvature_meas_min() == pytest.approx(expected, abs=1.)
      assert n.get_curvature_meas_max() == pytest.approx(expected, abs=1.)
      # A valid but contradictory yaw packet never changes selected pinion measurement.
      a, d, b = packer.make_can_msg('Yaw_Data_FD1', 0, {'VehYaw_W_Actl': 1., 'VehYawWActl_D_Qf': 3})
      assert n.safety_rx_hook(libsafety_py.make_CANPacket(a, b, d))
      assert n.get_curvature_meas_min() == pytest.approx(expected, abs=1.)


def test_default_measurement_is_yaw_even_with_conflicting_pinion():
  cp = params(next(iter(GEOMETRY)))
  m = Measurement(cp)
  state = SimpleNamespace(vEgoRaw=15., yawRate=.3, steeringAngleDeg=100.)
  assert m.curvature(state) == -.3 / 15.
  assert not m.enabled


@pytest.mark.parametrize('index,base', [(1, 32), (3, 66), (10, 10), (11, 18)])
@pytest.mark.parametrize('long', [False, True])
@pytest.mark.parametrize('manual', [False, True])
def test_pinion_inventory_and_invalid_quality_withdraw_authority(index, base, long, manual):
  from opendbc.safety.tests.test_ford_aol import TestFordAolDriverIntent
  n = TestFordAolDriverIntent()
  n.setUp()
  base |= int(long) | (256 if manual else 0)
  n.reset(base)
  count = n.safety.get_ford_pinion_rx_count()
  n.safety.set_safety_hooks(structs.CarParams.SafetyModel.ford, base | ENABLE | index << SHIFT)
  n.safety.set_aol_test_heartbeat(True)
  assert n.safety.get_ford_pinion_rx_count() == count + 1
  original_rx = n.rx

  def rx(name, values):
    if name == 'Yaw_Data_FD1':
      original_rx('SteeringPinion_Data', {'StePinComp_An_Est': 0., 'StePinCompAnEst_D_Qf': 3, 'StePinAn_No_Cnt': n.tick % 16})
    original_rx(name, values)
  n.rx = rx
  try:
    n.arm()
    assert n.safety.aol_get_permission_mask() == 1
    a, d, b = n.packer.make_can_msg('SteeringPinion_Data', 0,
                                   {'StePinComp_An_Est': 100., 'StePinCompAnEst_D_Qf': 0, 'StePinAn_No_Cnt': (n.tick + 1) % 16})
    assert not n.safety.safety_rx_hook(libsafety_py.make_CANPacket(a, b, d))
    assert n.safety.aol_get_permission_mask() == 0
    assert n.safety.get_curvature_meas_max() == 0
  finally:
    n.tearDown()


@pytest.mark.parametrize('failure', ['missing', 'wrong_bus', 'short', 'counter'])
def test_pinion_integrity_is_required_not_substituted_by_healthy_yaw(failure):
  from opendbc.safety.tests.test_ford_aol import TestFordAolDriverIntent
  n = TestFordAolDriverIntent()
  n.setUp()
  n.reset(66)
  n.safety.set_safety_hooks(structs.CarParams.SafetyModel.ford, 66 | ENABLE | 7 << SHIFT)
  n.safety.set_aol_test_heartbeat(True)
  original_rx = n.rx
  inject = True

  def rx(name, values):
    if name == 'Yaw_Data_FD1':
      if inject:
        original_rx('SteeringPinion_Data', {'StePinComp_An_Est': 0., 'StePinCompAnEst_D_Qf': 3, 'StePinAn_No_Cnt': n.tick % 16})
      elif failure != 'missing':
        a, d, b = n.packer.make_can_msg('SteeringPinion_Data', 0,
                                      {'StePinComp_An_Est': 100., 'StePinCompAnEst_D_Qf': 3, 'StePinAn_No_Cnt': 2})
        n.safety.safety_rx_hook(libsafety_py.make_CANPacket(a, 1 if failure == 'wrong_bus' else b, d[:7] if failure == 'short' else d))
    original_rx(name, values)
  n.rx = rx
  try:
    n.arm()
    inject = False
    n.pump(120, mask=1)
    assert n.safety.aol_get_permission_mask() == 0
  finally:
    n.tearDown()


@pytest.mark.parametrize('car', [c for c in GEOMETRY if 'MONDEO' not in c])
@pytest.mark.parametrize('long', [False, True])
def test_angle_selection_preserves_pinion_and_aol_exact_profile(car, long):
  from opendbc.bluepilot_lateral.hosts.starpilot import select as angle_select, qualified as angle_qualified
  from opendbc.car.ford.aol import base_safety_param, AOL_WORDS
  cp = params(car, long)
  assert select(cp, True)
  assert angle_select(cp, 1)
  assert configured(cp) and angle_qualified(cp)
  cp.safetyConfigs[-1].safetyParam |= base_safety_param(cp)
  cp.alternativeExperience = 32
  assert cp.safetyConfigs[-1].safetyParam in AOL_WORDS
  assert configured(cp) and angle_qualified(cp) and qualified(cp, marked_only=True)


@pytest.mark.parametrize('word', [32 | ENABLE, 32 | (1 << SHIFT), 32 | ENABLE | (13 << SHIFT),
                                  66 | ENABLE | (1 << SHIFT), 32 | ENABLE | (1 << SHIFT) | 0x4000,
                                  32 | ENABLE | (1 << SHIFT) | 0x8000])
def test_invalid_pinion_native_profile_denies_all_commands(word):
  n = libsafety_py.libsafety
  n.set_alternative_experience(32)
  n.set_safety_hooks(structs.CarParams.SafetyModel.ford, word)
  n.set_controls_allowed(True)
  assert not n.get_ford_pinion_enabled()
  for address in (0x3D3, 0x3D6, 0x3CA, 0x186, 0x18A, 0x3D8):
    assert not n.safety_tx_hook(libsafety_py.make_CANPacket(address, 0, bytes(8)))


def test_pinion_rx_capacity_guard_withdraws_authority_without_overwrite():
  n = libsafety_py.libsafety
  n.set_alternative_experience(32)
  n.set_safety_hooks(structs.CarParams.SafetyModel.ford, 66 | ENABLE | (7 << SHIFT))
  assert n.test_ford_pinion_rx_overflow()
