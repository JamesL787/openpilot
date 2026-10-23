from typing import TypedDict
from unittest.mock import patch

import pytest

from opendbc.car.honda.interface import CarInterface as HondaInterface
from opendbc.car.honda.values import CAR as HONDA
from opendbc.car.hyundai.interface import CarInterface as HyundaiInterface
from opendbc.car.hyundai.values import CAR as HYUNDAI
from opendbc.car.toyota.interface import CarInterface as ToyotaInterface
from opendbc.car.toyota.values import CAR as TOYOTA
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
from openpilot.starpilot.longitudinal.cruise_ceiling import CruiseCeiling, CurveCeiling
from openpilot.starpilot.longitudinal.encouragement import BOOST_RATE, Encouragement, MAX_BOOST, SOURCES
from openpilot.starpilot.longitudinal.tests.test_conditional_handoff import Frame, NOW
from openpilot.starpilot.longitudinal.tests.test_cruise_ceiling import ACTIVE


class PlannerOptions(TypedDict, total=False):
  curve_ceiling: CurveCeiling
  cruise_ceiling: CruiseCeiling
  traffic_mode: bool


def frame(tick):
  sm = Frame()
  now = NOW + tick * 50_000_000
  sm.logMonoTime = dict.fromkeys(sm, now - 5_000_000)
  sm['selfdriveState'].experimentalMode = True
  sm['modelV2'].action.desiredAcceleration = 0.
  sm['modelV2'].action.shouldStop = False
  sm['radarState'].leadOne.present = sm['radarState'].leadTwo.present = False
  return sm, now


def cp():
  return HondaInterface.get_non_essential_params(HONDA.HONDA_CIVIC)


def step(owner, tick, **changes):
  sm, now = frame(tick)
  args = {'now_ns': now, 'drive_id': 1, 'dt': .05, 'target_speed': 27., 'model_accel': 0.,
              'mpc_accel': .8, 'cruise_accel': .8, 'lateral_accel': 0., 'blocked': False}
  args.update(changes)
  return owner.update(sm, cp(), **args)


def test_ramp_settling_bound_and_near_target_taper():
  owner = Encouragement()
  values = [step(owner, tick) for tick in range(250)]
  assert values[:40] == [0.] * 40
  assert values[-1] == pytest.approx(MAX_BOOST)
  assert all(0 <= b - a <= BOOST_RATE * .05 + 1e-9 for a, b in zip(values, values[1:], strict=False))
  assert step(owner, 250, target_speed=20.3) == pytest.approx(MAX_BOOST / 18.)
  assert step(owner, 251, target_speed=20.) == 0.
  assert owner.boost == 0.


@pytest.mark.parametrize('field', ['blocked', 'negative', 'curve', 'stale', 'future', 'invalid', 'dead', 'frequency',
                                  'missing', 'radar_fault', 'lead1', 'lead2', 'stop', 'brake', 'gas', 'force', 'off', 'standard',
                                  'standstill', 'nan', 'duplicate', 'drive'])
def test_immediate_withdrawal_and_fresh_ramp(field):
  owner = Encouragement()
  for tick in range(90):
    step(owner, tick)
  assert owner.boost > 0
  sm, now = frame(90)
  args = {'now_ns': now, 'drive_id': 1, 'dt': .05, 'target_speed': 27., 'model_accel': 0.,
              'mpc_accel': .8, 'cruise_accel': .8, 'lateral_accel': 0., 'blocked': False}
  if field == 'blocked':
    args['blocked'] = True
  if field == 'negative':
    args['model_accel'] = -.001
  if field == 'curve':
    args['lateral_accel'] = .5
  if field == 'stale':
    sm.logMonoTime['modelV2'] = now - 250_000_001
  if field == 'future':
    sm.logMonoTime['radarState'] = now + 1
  if field == 'invalid':
    sm.valid['carState'] = False
  if field == 'dead':
    sm.alive['radarState'] = False
  if field == 'frequency':
    sm.freq_ok = {'modelV2': False}
  if field == 'missing':
    del sm.logMonoTime['carState']
  if field == 'radar_fault':
    sm['radarState'].radarErrors.radarFault = True
  if field == 'lead1':
    sm['radarState'].leadOne.present = True
  if field == 'lead2':
    sm['radarState'].leadTwo.present = True
  if field == 'stop':
    sm['modelV2'].action.shouldStop = True
  if field == 'brake':
    sm['carState'].brakePressed = True
  if field == 'gas':
    sm['carState'].gasPressed = True
  if field == 'force':
    sm['controlsState'].forceDecel = True
  if field == 'off':
    sm['carControl'].longActive = False
  if field == 'standard':
    sm['selfdriveState'].experimentalMode = False
  if field == 'standstill':
    sm['carState'].standstill = True
  if field == 'nan':
    args['target_speed'] = float('nan')
  if field == 'duplicate':
    sm.logMonoTime['modelV2'] = owner.last_model_ns
  if field == 'drive':
    args['drive_id'] = 2
  assert owner.update(sm, cp(), **args) == args['model_accel']
  assert owner.boost == 0.
  assert step(owner, 91) == 0.


@pytest.mark.parametrize('source', SOURCES)
def test_each_input_must_be_fresh(source):
  owner = Encouragement()
  for tick in range(90):
    step(owner, tick)
  sm, now = frame(90)
  sm.logMonoTime[source] = now - 250_000_001
  assert owner.update(sm, cp(), now_ns=now, drive_id=1, dt=.05, target_speed=27., model_accel=0.,
                      mpc_accel=.8, cruise_accel=.8, lateral_accel=0., blocked=False) == 0.


@pytest.mark.parametrize('factory,car', [(HondaInterface, HONDA.HONDA_CIVIC),
                                       (HyundaiInterface, HYUNDAI.HYUNDAI_IONIQ_6),
                                       (ToyotaInterface, TOYOTA.TOYOTA_RAV4_TSS2)])
def test_real_native_planner_clear_road_across_families(factory, car):
  params = factory.get_non_essential_params(car)
  params.openpilotLongitudinalControl = True
  original, current = (LongitudinalPlanner(params, init_v=20.) for _ in range(2))
  for tick in range(120):
    sm, now = frame(tick)
    with patch.object(original.encouragement, 'update', side_effect=lambda *a, **kw: kw['model_accel']):
      original.update(sm, now_ns=now)
    current.update(sm, now_ns=now)
    assert current.mpc.solution_status == original.mpc.solution_status == 0
    assert current.output_a_target >= original.output_a_target
    assert current.output_a_target <= current.a_cruise + 1e-6
    assert current.output_a_target - original.output_a_target <= MAX_BOOST + 1e-6
  assert current.output_a_target > original.output_a_target + .05


@pytest.mark.parametrize('case', ['model_brake', 'stop', 'lead1', 'lead2', 'curve', 'slc', 'turn', 'force',
                                 'throttle', 'standard', 'brake', 'gas', 'stale', 'traffic'])
def test_native_planner_limits_and_immediate_withdrawal(case):
  original, current = (LongitudinalPlanner(cp(), init_v=20.) for _ in range(2))
  for tick in range(100):
    sm, now = frame(tick)
    options: PlannerOptions = {}
    if tick == 90:
      original.output_a_target = current.output_a_target
      original.a_cruise = current.a_cruise
    if tick >= 90:
      if case == 'model_brake':
        sm['modelV2'].action.desiredAcceleration = -.01
      if case == 'stop':
        sm['modelV2'].action.shouldStop = True
      if case in ('lead1', 'lead2'):
        lead = sm['radarState'].leadOne if case == 'lead1' else sm['radarState'].leadTwo
        lead.present, lead.dRel, lead.vLead, lead.vLeadK, lead.vRel = True, 35., 15., 15., -5.
      if case == 'curve':
        options['curve_ceiling'] = CurveCeiling(19., sm.logMonoTime['modelV2'])
      if case == 'slc':
        options['cruise_ceiling'] = CruiseCeiling(19., ACTIVE)
      if case == 'turn':
        sm['carState'].steeringAngleDeg = 5.
      if case == 'force':
        sm['controlsState'].forceDecel = True
      if case == 'throttle':
        sm['modelV2'].meta.disengagePredictions.gasPressProbs = [0.] * 6
      if case == 'standard':
        sm['selfdriveState'].experimentalMode = False
      if case == 'brake':
        sm['carState'].brakePressed = True
      if case == 'gas':
        sm['carState'].gasPressed = True
      if case == 'stale':
        sm.logMonoTime['modelV2'] = now - 250_000_001
      if case == 'traffic':
        options['traffic_mode'] = True
    with patch.object(original.encouragement, 'update', side_effect=lambda *a, **kw: kw['model_accel']):
      original.update(sm, now_ns=now, **options)
    current.update(sm, now_ns=now, **options)
    assert current.mpc.solution_status == original.mpc.solution_status == 0
    if tick >= 90:
      assert current.output_a_target <= original.output_a_target + 1e-6
      assert current.encouragement.boost == 0.
      assert current.output_should_stop == original.output_should_stop


def test_native_planner_preserves_manual_override_input_and_boost():
  planner = LongitudinalPlanner(cp(), init_v=20.)
  for tick in range(120):
    sm, now = frame(tick)
    with patch.object(planner.accel_boost, 'update', wraps=planner.accel_boost.update) as manual:
      planner.update(sm, now_ns=now)
    assert manual.call_args.args[1] == 0.
  assert planner.encouragement.boost > 0.
  assert planner.accel_boost.boost_eligible
  for tick in range(120, 160):
    sm, now = frame(tick)
    sm['carState'].gasPressed = True
    planner.update(sm, now_ns=now)
    assert planner.encouragement.boost == 0.
  assert planner.accel_boost.total_boost == pytest.approx(.05)


@pytest.mark.parametrize('factory,car', [(HondaInterface, HONDA.HONDA_CIVIC),
                                       (HyundaiInterface, HYUNDAI.HYUNDAI_IONIQ_6),
                                       (ToyotaInterface, TOYOTA.TOYOTA_RAV4_TSS2)])
def test_native_planner_reaches_clear_road_boost_plateau(factory, car):
  params = factory.get_non_essential_params(car)
  params.openpilotLongitudinalControl = True
  planner = LongitudinalPlanner(params, init_v=20.)
  for tick in range(220):
    sm, now = frame(tick)
    planner.update(sm, now_ns=now)
    assert planner.mpc.solution_status == 0
    assert planner.output_a_target <= planner.a_cruise + 1e-6
  assert planner.encouragement.boost == pytest.approx(MAX_BOOST)
  assert planner.output_a_target == pytest.approx(MAX_BOOST, abs=.01)
