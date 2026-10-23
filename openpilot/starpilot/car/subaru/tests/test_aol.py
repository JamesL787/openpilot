import unittest
from dataclasses import replace

from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.subaru.interface import CarInterface
from opendbc.car.subaru.stock_aol import ANGLE_CARS, TORQUE_CARS, qualified
from opendbc.car.subaru.tests.test_ascent_angle import setup_controller, step
from opendbc.car.subaru.values import CAR
from openpilot.starpilot.aol.intent import AolSettings
from openpilot.starpilot.aol.vehicle import policy_for, native_matches_cp
from openpilot.starpilot.car.subaru.aol import SubaruStockCardIntent


class TestSubaruStockAol(unittest.TestCase):
  def test_exact_factory_profiles_and_stock_off_choices(self):
    for car in CAR:
      for alpha in (False, True):
        for source in ('fixed', 'fw', 'can'):
          cp = CarInterface.get_params(car, gen_empty_fingerprint(), [], alpha, False, False)
          cp.fingerprintSource = source
          admitted = car in ANGLE_CARS | TORQUE_CARS
          self.assertEqual(qualified(cp), admitted)
          policy = policy_for(cp)
          self.assertFalse(policy.full_axis_runtime_required)
          self.assertFalse(cp.openpilotLongitudinalControl)
          if admitted:
            cp.alternativeExperience |= policy.alternative_experience_addition
            self.assertTrue(qualified(cp, marked_only=True))
            self.assertTrue(policy_for(cp).full_axis_runtime_required)
            self.assertTrue(native_matches_cp(cp, int(cp.safetyConfigs[0].safetyModel.raw), cp.safetyConfigs[0].safetyParam))
            cp.safetyConfigs[0].safetyParam |= 2
            self.assertFalse(qualified(cp))

  def test_successful_full_engagement_brake_reverse_fault_main_and_off(self):
    settings = AolSettings(True, 0., 0, 0, (0, 0, 0), (0, 0, 0))
    intent = SubaruStockCardIntent(settings)
    cs = structs.CarState(canValid=True, vEgo=15, gearShifter=structs.CarState.GearShifter.drive)
    cs.cruiseState.available = cs.cruiseState.enabled = True
    def observe(enabled, active, stamp):
      intent.observe_full_engagement(cs.as_reader(), enabled=enabled, active=active, source_ns=stamp,
                                    observation_valid=True, now_ns=stamp, fault_active=False)
    intent.update(cs.as_reader(), now_ns=1)
    self.assertFalse(intent.allowed_latch)
    observe(False, False, 10)
    observe(True, False, 20)
    self.assertFalse(intent.allowed_latch)
    observe(True, True, 30)
    self.assertTrue(intent.allowed_latch)
    cs.brakePressed = True
    cs.cruiseState.enabled = False
    intent.update(cs.as_reader(), now_ns=40)
    self.assertTrue(intent.allowed_latch)
    cs.gearShifter = structs.CarState.GearShifter.reverse
    intent.update(cs.as_reader(), now_ns=50)
    self.assertTrue(intent.allowed_latch)
    cs.steerFaultTemporary = True
    intent.update(cs.as_reader(), now_ns=60)
    self.assertTrue(intent.allowed_latch)
    cs.gearShifter = structs.CarState.GearShifter.drive
    cs.steerFaultTemporary = False
    cs.steerFaultPermanent = True
    intent.update(cs.as_reader(), now_ns=70)
    self.assertFalse(intent.allowed_latch)
    cs.steerFaultPermanent = False
    intent.update(cs.as_reader(), fault_active=False, now_ns=80)
    observe(False, False, 90)
    observe(True, True, 100)
    self.assertTrue(intent.allowed_latch)
    cs.cruiseState.available = False
    intent.update(cs.as_reader(), now_ns=110)
    self.assertFalse(intent.allowed_latch)
    cs.cruiseState.available = True
    intent.update(cs.as_reader(), now_ns=120)
    self.assertFalse(intent.allowed_latch)
    intent.settings = replace(settings, enabled=False)
    observe(False, False, 130)
    observe(True, True, 140)
    self.assertFalse(intent.allowed_latch)

  def test_angle_controller_only_marked_profile_accepts_independent_lateral(self):
    for car in ANGLE_CARS:
      for enrolled in (False, True):
        cp, controller, command, state = setup_controller(car)
        cp.alternativeExperience = 32 if enrolled else 0
        command.enabled = False
        command.latActive = True
        state.out.brakePressed = True
        state.out.cruiseState.enabled = False
        step(controller, command, state)
        _, decoded = step(controller, command, state)
        self.assertEqual(bool(decoded['LKAS_Request']), enrolled)
        state.out.gearShifter = structs.CarState.GearShifter.reverse
        _, decoded = step(controller, command, state)
        self.assertEqual(decoded['LKAS_Request'], 0)
