import unittest

from opendbc.car import structs
from opendbc.car.honda.values import HondaSafetyFlags
from opendbc.safety.tests.test_honda_interceptor import TestHondaInterceptor

AOL_WORD = int(HondaSafetyFlags.GAS_INTERCEPTOR | HondaSafetyFlags.NIDEC_PEDAL_AOL)


class TestHondaNidecInterceptorAol(TestHondaInterceptor):
  """Nidec + gas interceptor (no PCM cruise) always-on lateral: lateral on main + host request, long only after SET/RES."""

  def setup_aol(self, word=AOL_WORD, ticks=20):
    self.init(word)
    self.safety.set_aol_test_heartbeat(True)
    for tick in range(ticks):
      self.feed(tick)
    self.tick = ticks
    self.gesture()

  def init(self, word):
    super().init(word)
    self.safety_word = word
    # SGSP's native Nidec pedal AOL is scoped by alternativeExperience 32 and needs fresh EPS and gear frames.
    self.safety.set_alternative_experience(32)
    self.safety.set_safety_hooks(structs.CarParams.SafetyModel.hondaNidec, word)
    self.safety.set_timer(0)

  def tearDown(self):
    self.safety.set_alternative_experience(0)

  def feed(self, tick, **kw):
    super().feed(tick, **kw)
    self.rx("STEER_STATUS", 0, {"STEER_STATUS": 0, "STEER_TORQUE_SENSOR": 0})
    self.rx("GEARBOX_CVT", 0, {"GEAR_SHIFTER": 4})
    self.safety.safety_tick()

  def gesture(self):
    """The physical grant: MAIN off then on (SGSP grants lateral only after one, ours granted on MAIN alone)."""
    if self.safety_word == AOL_WORD:
      self.rx("SCM_FEEDBACK", 0, {"MAIN_ON": 0})
      self.step()

  def step(self, **kwargs):
    self.feed(self.tick, **kwargs)
    self.tick += 1

  def steer(self, torque=0x100):
    return self.tx(self.packer.make_can_msg("STEERING_CONTROL", 0, {"STEER_TORQUE": torque, "STEER_TORQUE_REQUEST": 1}))

  def test_lateral_without_engagement_long_needs_set_resume(self):
    self.setup_aol()
    self.assertFalse(self.safety.get_controls_allowed())
    self.assertEqual(self.safety.aol_get_permission_mask(), 0)
    self.assertFalse(self.steer())

    self.safety.aol_set_host_request(1)
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)
    self.assertTrue(self.steer())
    self.assertFalse(self.tx(self.command()))  # gas still needs a normal engagement

    self.safety.aol_set_host_request(3)
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)  # a long request alone grants nothing
    self.step(button=3)
    self.step(button=0)
    self.assertTrue(self.safety.get_controls_allowed())
    self.safety.aol_set_host_request(3)
    self.assertEqual(self.safety.aol_get_permission_mask(), 3)
    self.assertTrue(self.tx(self.command()))
    self.assertTrue(self.steer())

  def test_main_off_cancel_heartbeat_and_stale_main_fail_closed(self):
    self.setup_aol()
    self.safety.aol_set_host_request(1)
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)

    self.step(button=2)  # cancel
    self.assertEqual(self.safety.aol_get_permission_mask(), 0)
    self.gesture()  # SGSP: a cancel ends the session; lateral returns only with a new physical gesture
    self.safety.aol_set_host_request(1)
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)

    self.assertTrue(self.rx("SCM_FEEDBACK", 0, {"MAIN_ON": 0}))
    self.assertEqual(self.safety.aol_get_permission_mask(), 0)
    self.assertFalse(self.steer())
    self.step()
    self.safety.aol_set_host_request(1)
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)

    self.safety.set_aol_test_heartbeat(False)
    self.assertEqual(self.safety.aol_get_permission_mask(), 0)
    self.safety.set_aol_test_heartbeat(True)
    self.gesture()  # SGSP: dropping the engaged heartbeat ends the session too
    self.safety.aol_set_host_request(1)
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)

    self.safety.set_timer((self.tick - 1) * 10_000 + 300_001)  # main older than 300 ms
    self.assertEqual(self.safety.aol_get_permission_mask(), 0)
    self.assertFalse(self.steer())

  def test_brake_ends_long_but_not_lateral(self):
    self.setup_aol()
    self.step(button=3)
    self.step(button=0)
    self.safety.aol_set_host_request(3)
    self.assertEqual(self.safety.aol_get_permission_mask(), 3)
    self.step(brake=True)
    self.step(brake=True)
    self.safety.aol_set_host_request(3)
    self.assertFalse(self.safety.get_controls_allowed())
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)
    self.assertTrue(self.steer())
    self.assertFalse(self.tx(self.command()))

  def test_plain_interceptor_word_has_no_aol(self):
    self.setup_aol(word=32)
    self.safety.aol_set_host_request(3)
    self.assertEqual(self.safety.aol_get_permission_mask(), 0)
    self.assertFalse(self.steer())
    self.step(button=3)
    self.step(button=0)
    self.assertTrue(self.safety.get_controls_allowed())
    self.assertTrue(self.steer())
    self.assertTrue(self.tx(self.command()))

  def test_other_words_with_the_aol_bit_never_grant(self):
    for word in (36 | 512, 4 | 512, 512):
      with self.subTest(word=word):
        self.init(word)
        self.safety.set_aol_test_heartbeat(True)
        self.safety.aol_set_host_request(3)
        self.assertEqual(self.safety.aol_get_permission_mask(), 0)
        self.assertFalse(self.steer())
    # the AOL bit on an alt-main word does not enable the interceptor either
    self.init(36 | 512)
    self.assertFalse(self.tx(self.command()))

  def test_mode_change_removes_the_policy(self):
    self.setup_aol()
    self.safety.aol_set_host_request(1)
    self.assertEqual(self.safety.aol_get_permission_mask(), 1)
    self.assertEqual(self.safety.set_safety_hooks(structs.CarParams.SafetyModel.hondaNidec, 32), 0)
    self.safety.aol_set_host_request(1)
    self.assertEqual(self.safety.aol_get_permission_mask(), 0)


if __name__ == "__main__":
  unittest.main()
