"""Blendful setting ownership: custom-model gating and mutual exclusion with Lane Centering."""

import tempfile
import unittest
from unittest.mock import patch

from openpilot.common.params import Params
from openpilot.starpilot.ui.feature_settings_owner import FeatureSettingsOwner
from openpilot.starpilot.ui.feature_settings_state import FeatureRow, FeatureSettingsRequest, row_change


def required_change(row: FeatureRow, direction: int = 1) -> FeatureSettingsRequest:
  request = row_change(row, direction)
  if request is None:
    raise AssertionError(f"Expected an editable row: {row.key}")
  return request


class BlendfulSettingsTests(unittest.TestCase):
  def setUp(self):
    from opendbc.car.car_helpers import interfaces
    from opendbc.car.toyota.values import CAR
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.params = Params(self.temp.name)
    self.allowed = True
    self.groups = []
    self.owner = FeatureSettingsOwner(self.params, self._authority, vehicle_fingerprint=lambda: self.fingerprint)
    cp = interfaces[CAR.TOYOTA_COROLLA_TSS2].get_non_essential_params(CAR.TOYOTA_COROLLA_TSS2)
    self.fingerprint = cp.carFingerprint
    self.owner.vehicle_params = lambda: cp

  def _authority(self, group):
    self.groups.append(group)
    return self.allowed

  def _lane(self):
    state = self.owner.snapshot("lane", parked=False, system_long=False, lateral_context=False, metric=False)
    return state.rows

  def _row(self, key):
    return next(row for row in self._lane() if row.key == key)

  def test_blendful_hidden_without_a_custom_model(self):
    row = self._row("Blendful")
    self.assertFalse(row.available)
    self.assertIn("non-Default", row.reason)
    request = FeatureSettingsRequest("Blendful", None, "On", vehicle_fingerprint=self.fingerprint)
    self.assertFalse(self.owner.apply(request))
    self.assertIsNone(self.params.get("Blendful"))

  def test_enabling_blendful_turns_lane_centering_off(self):
    self.params.put_bool("LaneCentering", True, block=True)
    with patch("openpilot.starpilot.models.manager.preferences",
               return_value={"small": "custom-lateral", "big": ""}):
      row = self._row("Blendful")
      self.assertTrue(row.available)
      self.assertTrue(self.owner.apply(required_change(row)))
    self.assertTrue(self.params.get_bool("Blendful"))
    self.assertFalse(self.params.get_bool("LaneCentering"))

  def test_enabling_lane_centering_turns_blendful_off(self):
    self.params.put_bool("Blendful", True, block=True)
    self.params.put_bool("LaneCentering", False, block=True)
    with patch("openpilot.starpilot.models.manager.preferences",
               return_value={"small": "custom-lateral", "big": ""}):
      row = self._row("LaneCentering")
      self.assertTrue(row.available)
      self.assertTrue(self.owner.apply(required_change(row)))
    self.assertTrue(self.params.get_bool("LaneCentering"))
    self.assertFalse(self.params.get_bool("Blendful"))

  def test_turning_either_off_keeps_the_other_off(self):
    self.params.put_bool("Blendful", True, block=True)
    with patch("openpilot.starpilot.models.manager.preferences",
               return_value={"small": "custom-lateral", "big": ""}):
      row = self._row("Blendful")
      self.assertTrue(self.owner.apply(required_change(row)))
    self.assertFalse(self.params.get_bool("Blendful"))
    self.assertFalse(self.params.get_bool("LaneCentering"))

  def test_blendful_toggle_needs_the_displayed_source(self):
    with patch("openpilot.starpilot.models.manager.preferences",
               return_value={"small": "custom-lateral", "big": ""}):
      row = self._row("Blendful")
      request = required_change(row)
    self.params.put_bool("Blendful", True, block=True)
    self.assertFalse(self.owner.apply(request))
    self.assertTrue(self.params.get_bool("Blendful"))


if __name__ == "__main__":
  unittest.main()
