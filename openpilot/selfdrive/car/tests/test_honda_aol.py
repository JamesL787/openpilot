"""Honda AOL host qualification and serialized integration tests."""

import unittest
from unittest import mock

from openpilot.cereal import log, messaging
from openpilot.common.prefix import OpenpilotPrefix
from opendbc.car.structs import car
from opendbc.car import gen_empty_fingerprint
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR, CarControllerParams, HondaFlags
from openpilot.common.params import Params
from openpilot.selfdrive.car.card import Car
from openpilot.starpilot.car.honda.aol import CLASSIC_BOSCH_AOL_CARS, qualified_honda


def car_state(*, brake=False):
  return car.CarState(canValid=True, gearShifter=car.CarState.GearShifter.drive,
                      vEgo=20.0, brakePressed=brake)


class HondaFamilyQualificationTests(unittest.TestCase):
  def setUp(self):
    # Some upstream interfaces set this shared table while constructing CP.
    self.addCleanup(setattr, CarControllerParams, 'BOSCH_GAS_LOOKUP_V', list(CarControllerParams.BOSCH_GAS_LOOKUP_V))

  def test_stock_cruise_off_disables_standard_state_without_disarming_aol(self):
    from openpilot.selfdrive.car.car_events import CarEvents
    from openpilot.selfdrive.selfdrived.events import ET
    from openpilot.selfdrive.selfdrived.state import StateMachine, State
    from openpilot.starpilot.aol.intent import disarming_fault
    from opendbc.car.honda.stock_aol import qualified
    fingerprint = gen_empty_fingerprint()
    fingerprint[1][0x1A3] = 8
    cp = CarInterface.get_params(CAR.HONDA_ACCORD, fingerprint, [], False, False, False)
    cp.alternativeExperience = 32
    self.assertTrue(qualified(cp, marked_only=True))
    for speed, name in ((20., log.OnroadEvent.EventName.cruiseDisabled),
                        (0., log.OnroadEvent.EventName.speedTooLow)):
      with self.subTest(speed=speed):
        state = car_state()
        state.vEgo = speed
        state.cruiseState.available = True
        events = CarEvents(cp).update(state, state, car.CarControl())
        event = next(event for event in events.to_msg() if event.name == name)
        self.assertTrue(event.userDisable)
        self.assertFalse(event.immediateDisable)
        self.assertFalse(disarming_fault([event], state))
        machine = StateMachine()
        machine.state = State.enabled
        machine.update(events)
        self.assertEqual(machine.state, State.disabled)
        for fault in (log.OnroadEvent.EventName.accFaulted, log.OnroadEvent.EventName.canError,
                      log.OnroadEvent.EventName.steerUnavailable):
          guarded = CarEvents(cp).update(state, state, car.CarControl())
          guarded.add(fault)
          self.assertTrue(disarming_fault(guarded.to_msg(), state))
        cp.alternativeExperience = 0
        ordinary = CarEvents(cp).update(state, state, car.CarControl())
        self.assertTrue(ordinary.contains(ET.IMMEDIATE_DISABLE))
        self.assertTrue(disarming_fault(ordinary.to_msg(), state))
        cp.alternativeExperience = 32

  def test_exact_classic_bosch_cp_family_and_rejections(self):
    self.assertEqual(len(CLASSIC_BOSCH_AOL_CARS), 10)
    all_honda = tuple(candidate for candidate in CAR if candidate.config.flags & HondaFlags.BOSCH)
    for candidate in all_honda:
      with self.subTest(candidate=candidate):
        cp = CarInterface.get_params(candidate, gen_empty_fingerprint(), [], True, False, False)
        self.assertEqual(qualified_honda(cp), candidate in CLASSIC_BOSCH_AOL_CARS)
        if candidate in CLASSIC_BOSCH_AOL_CARS:
          self.assertEqual(cp.brand, 'honda')
          self.assertTrue(cp.openpilotLongitudinalControl)
          self.assertFalse(cp.pcmCruise)
          self.assertEqual(len(cp.safetyConfigs), 1)
          self.assertIn(cp.safetyConfigs[0].safetyParam, (2, 3, 131))
          cp.safetyConfigs[0].safetyParam |= 32
          self.assertTrue(qualified_honda(cp))
          cp.safetyConfigs[0].safetyParam |= 4
          self.assertFalse(qualified_honda(cp))

    for candidate in CLASSIC_BOSCH_AOL_CARS:
      with self.subTest(stock=candidate):
        cp = CarInterface.get_params(candidate, gen_empty_fingerprint(), [], False, False, False)
        self.assertFalse(qualified_honda(cp))

    cp = CarInterface.get_params(CAR.HONDA_ACCORD, gen_empty_fingerprint(), [], True, False, False)
    cp.passive = True
    self.assertFalse(qualified_honda(cp))
    cp.passive = False
    cp.dashcamOnly = True
    self.assertFalse(qualified_honda(cp))
    cp.dashcamOnly = False
    cp.brand = 'other'
    self.assertFalse(qualified_honda(cp))
    cp.brand = 'honda'
    cp.notCar = True
    self.assertFalse(qualified_honda(cp))
    cp.notCar = False
    cp.flags |= int(HondaFlags.BOSCH_ALT_RADAR)
    self.assertFalse(qualified_honda(cp))
    cp.flags &= ~int(HondaFlags.BOSCH_ALT_RADAR)
    cp.safetyConfigs[0].safetyModel = car.CarParams.SafetyModel.hondaNidec
    self.assertFalse(qualified_honda(cp))
    cp.safetyConfigs[0].safetyModel = car.CarParams.SafetyModel.hondaBosch
    cp.safetyConfigs = [car.CarParams.SafetyConfig(safetyModel=car.CarParams.SafetyModel.hondaBosch, safetyParam=2),
                        car.CarParams.SafetyConfig(safetyModel=car.CarParams.SafetyModel.noOutput, safetyParam=0)]
    self.assertFalse(qualified_honda(cp))

  def test_card_serializes_opt_in_only_for_actual_eligible_cp(self):
    class FakeHonda:
      CC = object()
      CS = object()

      def __init__(self, candidate, alpha_long):
        self.CP = CarInterface.get_params(candidate, gen_empty_fingerprint(), [], alpha_long, False, False)

      def init(self, _cp, _recv, _send):
        pass

    class FakeRadar(RadarInterfaceBase):
      def update(self, can_packets):
        return None

    for candidate in sorted(CLASSIC_BOSCH_AOL_CARS, key=str):
      for alpha_long in (False, True):
        with self.subTest(candidate=candidate, alpha_long=alpha_long), OpenpilotPrefix(), \
             mock.patch.dict('os.environ', {'AOL_REPLAY_RUNTIME': '1', 'SIMULATION': '1'}):
          messaging.reset_context()
          params = Params()
          params.put_bool('OpenpilotEnabledToggle', True, block=True)
          params.put_bool('AlwaysOnLateral', True, block=True)
          honda = FakeHonda(candidate, alpha_long)
          card = Car(honda, FakeRadar(honda.CP))
          expected = alpha_long or candidate != CAR.HONDA_ACCORD
          self.assertEqual(card.aol_qualified, expected)
          self.assertEqual(bool(card.CP.safetyConfigs[0].safetyParam & 32), alpha_long)
          stock_owned = candidate != CAR.HONDA_ACCORD
          experience = 32 if expected and stock_owned else 0
          if alpha_long and stock_owned:
            word = 2211 if candidate == CAR.ACURA_RDX_3G else 2082 | int(bool(card.CP.flags & HondaFlags.BOSCH_ALT_BRAKE))
            self.assertEqual(card.CP.safetyConfigs[0].safetyParam, word)
          self.assertEqual(card.CP.alternativeExperience, experience)
          with car.CarParams.from_bytes(params.get('CarParams')) as published:
            self.assertEqual(bool(published.safetyConfigs[0].safetyParam & 32), alpha_long)
            self.assertEqual(published.alternativeExperience, experience)


class HondaHostTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    super().setUpClass()
    from openpilot.starpilot.aol.tests.honda_native_fixture import honda_native_pair
    cls.honda_native_origins = cls.enterClassContext(honda_native_pair())

  def test_real_car_params_selfdrive_controls_chain_fails_closed(self):
    from openpilot.starpilot.aol.tests import test_honda_recovery_lifecycle as current
    # The source-bound contract starts unarmed. Actual SET/CAN, C++ negotiation,
    # native USB status and accepted controller TX establish the later grant.
    # Fresh DM lockout retains an already armed LAT owner under shared policy;
    # invalid DM, saved OFF, and unacknowledged LONG still fail closed.
    caller = current.TestHondaCurrentCaller()
    for scenario in ('driver_lockout', 'settings_off', 'long_reengage'):
      with self.subTest(scenario=scenario):
        caller.run_current_caller(
          candidate=CAR.HONDA_CIVIC_BOSCH, word=2082, alpha=True,
          host_scenario=scenario, serialized=True)


class CardAxisSessionTests(unittest.TestCase):
  def test_native_lookup_uses_selfdrived_axis_session(self):
    # pandad stamps aolSafetyWire with aolAxisState's session; card's own producer session never matches it.
    card = Car.__new__(Car)
    card.slc_producer_session = 'card'
    card.sm = messaging.SubMaster(['aolAxisState'])
    self.assertEqual(card.aol_axis_session(), 'card')
    axis = messaging.new_message('aolAxisState')
    axis.aolAxisState.sessionId = 'selfdrived'
    card.sm.update_msgs(1.0, [axis.as_reader()])
    self.assertEqual(card.aol_axis_session(), 'selfdrived')


class HondaNidecInterceptorAolTests(unittest.TestCase):
  """Nidec + gas interceptor (openpilot long, no PCM cruise): AOL from the saved request alone, safety word 32 | 512."""

  @staticmethod
  def interceptor_cp(candidate=CAR.HONDA_CLARITY):
    fp = gen_empty_fingerprint()
    fp[0][0x201] = 6
    return CarInterface.get_params(candidate, fp, [], False, False, False)

  def test_policy_word_and_native_receipt(self):
    from opendbc.car.honda.nidec_interceptor import qualified as interceptor_qualified
    from opendbc.car.honda.stock_aol import qualified as qualified_stock
    from openpilot.starpilot.car.honda.aol import native_accepts_cp, native_profile_supported, policy_for
    cp = self.interceptor_cp()
    self.assertTrue(qualified_stock(cp) and cp.flags & HondaFlags.GAS_INTERCEPTOR)
    self.assertEqual(cp.safetyConfigs[0].safetyParam, 32)
    policy = policy_for(cp)
    self.assertTrue(policy.intent_supported and policy.settings_supported and policy.normal_runtime_supported)
    self.assertTrue(policy.runtime_supported)  # SGSP's native policy; card adds the AOL bit and alt-exp 32
    self.assertEqual(policy.safety_param_addition, 512)
    self.assertEqual(policy.alternative_experience_addition, 32)
    cp.safetyConfigs[0].safetyParam |= policy.safety_param_addition
    cp.alternativeExperience |= policy.alternative_experience_addition
    self.assertTrue(policy_for(cp).runtime_supported)
    self.assertTrue(interceptor_qualified(cp))  # the pedal stays on with the AOL word
    self.assertIsNotNone(CarInterface(cp).CC.nidec_interceptor)
    nidec = int(car.CarParams.SafetyModel.hondaNidec)
    self.assertTrue(native_profile_supported(nidec, 544) and native_accepts_cp(cp, nidec, 544))
    self.assertFalse(native_accepts_cp(cp, nidec, 32))

  def test_stock_clarity_is_not_offered_the_pedal_word(self):
    # SGSP's native Nidec pedal AOL offers the pedal word to every qualified interceptor car; a stock Clarity gets none.
    from openpilot.starpilot.car.honda.aol import policy_for
    stock = CarInterface.get_params(CAR.HONDA_CLARITY, gen_empty_fingerprint(), [], False, False, False)
    self.assertEqual(policy_for(stock).safety_param_addition & 512, 0)
    cp = self.interceptor_cp()
    cp.safetyConfigs[0].safetyParam = 36
    self.assertNotEqual(policy_for(cp).safety_param_addition, 512)

  def test_card_opts_in_from_saved_request_without_replay_env(self):
    test = self

    class FakeHonda:
      CC = object()
      CS = object()

      def __init__(self):
        self.CP = test.interceptor_cp()

      def init(self, _cp, _recv, _send):
        pass

    class FakeRadar(RadarInterfaceBase):
      def update(self, can_packets):
        return None

    from openpilot.starpilot.feature_runtime import enabled as feature_enabled
    for aol_on in (False, True):
      with self.subTest(aol_on=aol_on), OpenpilotPrefix(), mock.patch.dict('os.environ', {'SIMULATION': '1'}):
        messaging.reset_context()
        params = Params()
        params.put_bool('OpenpilotEnabledToggle', True, block=True)
        params.put_bool('AlwaysOnLateral', aol_on, block=True)
        params.put('LKASButtonControl', 9, block=True)
        honda = FakeHonda()
        card = Car(honda, FakeRadar(honda.CP))
        self.assertEqual(card.aol_qualified, aol_on)
        self.assertEqual(card.CP.safetyConfigs[0].safetyParam, 544 if aol_on else 32)
        with car.CarParams.from_bytes(params.get('CarParams')) as published:
          self.assertEqual(published.safetyConfigs[0].safetyParam, 544 if aol_on else 32)
          self.assertEqual(feature_enabled(params, published, 'aol', {}), aol_on)
