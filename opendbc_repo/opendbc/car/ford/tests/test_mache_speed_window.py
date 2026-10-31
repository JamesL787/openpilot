import pytest
from opendbc.car.ford import mache_lateral as original
from opendbc.car import Bus
from opendbc.can import CANPacker

candidate = original


def cp():
  from opendbc.car import gen_empty_fingerprint
  from opendbc.car.ford.interface import CarInterface
  from opendbc.car.ford.values import CAR

  fingerprint = gen_empty_fingerprint()
  fingerprint[0] = {0x5A: 8, 0x3A6: 8, 0x3A7: 8}
  result = CarInterface.get_params(CAR.FORD_MUSTANG_MACH_E_MK1, fingerprint, [], True, False, False)
  result.alternativeExperience = 32
  assert result.safetyConfigs[-1].safetyParam == 19 and result.flags == 3
  return result


@pytest.mark.parametrize("sign", [-1, 1])
def test_recorded_native_window_prevents_first_rejection_and_cascade(sign):
  from opendbc.safety.tests.test_ford_mach_e_extended import TestFordMachEExtended
  from opendbc.safety.tests.test_ford_aol import TestFordAolDriverIntent

  f = TestFordMachEExtended()
  f.SAFETY_PARAM = 19
  f.setUp()
  a = TestFordAolDriverIntent()
  a.setUp()

  def setup():
    a.reset(19)
    a.arm()
    a.pump(12, mask=3, speed=8.805556, curvature=sign * 0.02)
    f._rx(f._pcm_status_msg(True))
    a.safety.aol_set_host_request(3)
    assert a.safety.aol_get_permission_mask() == 3
    assert f.announce()
    a.pump(2, mask=3, main=4, speed=8.775, curvature=sign * 0.02)
    f._set_prev_desired_angle(sign * 0.02)

  demand = original.FordLateralResult(active=True, curvature=sign * 0.02, path_angle=sign * 0.0035, curvature_rate=-0.001023)
  setup()
  old = original.bounded_command(candidate.MachELateralController(cp()), demand, sign * 0.02, 8.775)
  assert not f._tx(f.command(curvature=old.curvature, angle=old.path_angle, rate=old.curvature_rate, increment_timer=False))
  assert not f._tx(f.command(curvature=sign * 0.02, angle=0, rate=0, increment_timer=False))
  setup()
  new = candidate.bounded_command(candidate.MachELateralController(cp()), demand, sign * 0.02, 8.775, speed_window=(8.775, 8.806, 0.031))
  assert new.curvature == old.curvature and new.path_angle == 0
  assert f._tx(f.command(curvature=new.curvature, angle=new.path_angle, rate=new.curvature_rate, increment_timer=False))
  assert f._tx(f.command(curvature=sign * 0.02, angle=0, rate=0, increment_timer=False))
  a.tearDown()


@pytest.mark.parametrize("speed", [0, 2.99, 3, 5, 8.7, 8.8, 12, 30])
@pytest.mark.parametrize("active", [False, True])
def test_zero_span_window_preserves_default_command(speed, active):
  d = original.FordLateralResult(active=active, curvature=0.02, path_angle=0.1)
  assert candidate.bounded_command(candidate.MachELateralController(cp()), d, 0.019, speed) == candidate.bounded_command(
    candidate.MachELateralController(cp()), d, 0.019, speed, speed_window=(speed, speed, 0.0)
  )


@pytest.mark.parametrize("param,ae,supported", [(19, 32, True), (18, 32, False), (19, 0, False), (147, 32, False), (67, 32, False)])
def test_exact_profile(param, ae, supported):
  c = cp()
  c.safetyConfigs[0].safetyParam = param
  c.alternativeExperience = ae
  assert candidate.path_speed_window_supported(c) == supported


def test_actual_carstate_tracks_six_raw_samples():
  from opendbc.car.ford.carstate import CarState

  c = cp()
  cs = CarState(c)
  parsers = cs.get_can_parsers(c)
  p = CANPacker("ford_lincoln_base_pt")
  values = [8.7, 8.805556, 8.79, 8.78, 8.775, 8.77, 8.76]
  for i, v in enumerate(values):
    parsers[Bus.pt].update(
      [[(i + 1) * 20_000_000, [p.make_can_msg("BrakeSysFeatures", 0, {"Veh_V_ActlBrk": v * 3.6, "VehVActlBrk_D_Qf": 3, "VehVActlBrk_No_Cnt": i + 1})]]]
    )
    cs.update(parsers)
  assert cs.bluepilot_speed_window is not None
  assert cs.bluepilot_speed_samples is not None
  assert cs.bluepilot_speed_window[1] >= 8.8
  assert len(cs.bluepilot_speed_samples) == 6

  for i in range(7, 13):
    parsers[Bus.pt].update(
      [[(i + 1) * 20_000_000, [p.make_can_msg("BrakeSysFeatures", 0, {"Veh_V_ActlBrk": 8.7 * 3.6, "VehVActlBrk_D_Qf": 3, "VehVActlBrk_No_Cnt": i + 1})]]]
    )
    cs.update(parsers)
  assert cs.bluepilot_speed_window is not None
  assert cs.bluepilot_speed_window[1] < 8.8


@pytest.mark.parametrize("high", [8.79, 8.8, 8.81, 9.0])
def test_rising_window_previous_nonzero_path(high):
  demand = original.FordLateralResult(active=True, curvature=0.02, path_angle=0.05)
  out = candidate.bounded_command(candidate.MachELateralController(cp()), demand, 0.02, 8.775, 0.05, speed_window=(8.7, high, 0.1))
  if high >= 8.8:
    assert out.path_angle == 0
  else:
    assert 0 <= out.path_angle <= 0.05
  assert out.curvature == 0.02


def test_controller_uses_native_speed_window():
  from opendbc.can import CANParser
  from opendbc.car import structs
  from opendbc.car.ford.carcontroller import CarController
  from opendbc.car.ford.carstate import CarState
  from opendbc.car.ford.values import DBC
  from openpilot.common.prefix import OpenpilotPrefix

  with OpenpilotPrefix():
    c = cp()
    controller = CarController(DBC[c.carFingerprint], c)
    controller.manual_turn_inputs = None
    controller.mache_extended_announced = True
    assert controller.mache_lateral is not None
    controller.mache_lateral.curvature_last = 0.02
    controller.mache_lateral.update = lambda *_: candidate.FordLateralResult(active=True, curvature=0.02, path_angle=0.0035)
    state = CarState(c)
    state.update(state.get_can_parsers(c))
    state.bluepilot_speed_window = (8.775, 8.806, 0.031)
    cs = structs.CarState(canValid=True, vEgo=8.775, vEgoRaw=8.775, gearShifter=structs.CarState.GearShifter.drive)
    cs.cruiseState.available = True
    state.out = cs.as_reader()
    command = structs.CarControl(latActive=True, longActive=True)
    _, frames = controller.update(command.as_reader(), state, 1_000_000_000)
    parser = CANParser("ford_lincoln_base_pt", [("LateralMotionControl2", 50)], 0)
    parser.update([[1_000_000_000, frames]])
    assert any(address == 0x3D6 for address, _, _ in frames)
    assert abs(parser.vl["LateralMotionControl2"]["LatCtlPath_An_Actl"]) < 0.00001
    assert abs(abs(parser.vl["LateralMotionControl2"]["LatCtlCurv_No_Actl"]) - 0.02) < 0.00001
