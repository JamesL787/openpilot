import unittest

from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import should_trigger_planner_fcw


class TestSubaruPlannerFcw(unittest.TestCase):
  def test_recorded_distant_follow_and_collision_boundaries(self):
    for present, probability, distance, lead_speed, ego_speed, expected in (
      (True, .99, 97.49, 25.63, 26.70, False),
      (True, .99, 15., 10., 20., True),
      (True, .99, 5., 20., 20., False),
      (True, .99, 5., 21., 20., False),
      (False, .99, 2., 0., 20., False),
      (True, .9, 5., 0., 20., False),
      (True, .99, 40., 10., 20., False),
      (True, .99, 39.99, 10., 20., True),
      (True, .99, 1., 19.51, 20., False),
      (True, .99, 1., 19.5, 20., True),
    ):
      with self.subTest(distance=distance, lead_speed=lead_speed, probability=probability):
        radar = log.RadarState.new_message()
        radar.leadOne.present = present
        radar.leadOne.modelProb = probability
        radar.leadOne.dRel = distance
        radar.leadOne.vLead = lead_speed
        self.assertEqual(should_trigger_planner_fcw(radar.leadOne, ego_speed), expected)
    self.assertFalse(should_trigger_planner_fcw(None, 20.))
