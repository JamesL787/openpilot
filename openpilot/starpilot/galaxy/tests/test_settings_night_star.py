"""Night Star port: Galaxy settings tests of our own, kept out of test_settings.py (the lint caps a file at 120 KB)."""

from dataclasses import replace
import unittest

from openpilot.starpilot.galaxy.tests import test_settings as base


class NightStarSettingsTest(unittest.TestCase):
  setUp = base.SettingsGatewayTest.setUp
  page = base.SettingsGatewayTest.page

  def test_force_turn_desires_is_a_galaxy_setting(self):
    # comma four owners set it here; their device settings don't carry the lane change rows
    from opendbc.car.car_helpers import interfaces
    from opendbc.car.honda.values import CAR as HONDA
    from openpilot.starpilot.lateral.lane_change_preferences import read_saved as read_lane_change

    cp = interfaces[HONDA.HONDA_CLARITY].get_non_essential_params(HONDA.HONDA_CLARITY)
    self.context.value = replace(self.context.value, cp=cp)
    page = self.page("lane_change")
    turn = next(i for i, row in enumerate(page["rows"]) if row["label"] == "Force turn desires")
    speed = next(i for i, row in enumerate(page["rows"]) if row["label"] == "Turn desire speed")
    self.assertEqual((page["rows"][turn]["value"], page["rows"][speed]["value"]), ("Off", "15.0"))
    self.assertIn("without a navigation route", page["rows"][turn]["reason"])
    intent = self.gateway.preview(page["view"], turn, 1, self.session, self.generation)
    self.assertIn("Force turn desires to On", intent["question"])
    self.assertIn("after the current signal ends", intent["question"])
    self.assertTrue(self.gateway.confirm(intent["intent"], self.session, self.generation))
    self.assertTrue(read_lane_change(self.params).policy.turn_desires)
    page = self.page("lane_change")
    intent = self.gateway.preview(page["view"], speed, -1, self.session, self.generation)
    self.assertTrue(self.gateway.confirm(intent["intent"], self.session, self.generation))
    self.assertEqual(self.page("lane_change")["rows"][speed]["value"], "14.0")
    self.assertEqual(self.params.get("LaneChangePreferences")["version"], 5)
