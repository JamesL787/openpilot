import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opendbc.car import structs
from opendbc.car.ford.values import CAR, FordFlags
from openpilot.starpilot.ui.ford_lateral_feature import FordLateralFeature


class TestFordSelectorVisibility(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.cp = structs.CarParams(brand='ford', carFingerprint=CAR.FORD_MUSTANG_MACH_E_MK1,
      flags=int(FordFlags.CANFD), alternativeExperience=32, pcmCruise=True,
      steerControlType='angle', transmissionType='automatic',
      safetyConfigs=[{'safetyModel': 'ford', 'safetyParam': 18}])
    self.params = SimpleNamespace(get_param_path=lambda key: str(self.root / key))
    self.owner = SimpleNamespace(params=self.params, vehicle_params=lambda: self.cp,
      authority=lambda _: True, vehicle_fingerprint=lambda: self.cp.carFingerprint)
    self.feature = FordLateralFeature(self.owner)
    self.save('AlwaysOnLateral', b'1')
    self.save('SafeMode', b'0')

  def save(self, key, value):
    (self.root / key).write_bytes(value)

  def test_aol_marked_mach_e_visible_without_mutating_configuration(self):
    for alpha in (False, True):
      self.cp.openpilotLongitudinalControl = alpha
      self.cp.safetyConfigs[0].safetyParam = 18 + int(alpha)
      before = self.cp.to_dict()
      rows = self.feature.rows(True)
      self.assertEqual(len(rows), 1)
      self.assertEqual(rows[0].choices, ('Current curvature', 'BluePilot angle'))
      self.assertTrue(rows[0].available)
      self.assertIn('works with Always On Lateral', rows[0].reason)
      self.assertEqual(self.cp.to_dict(), before)

  def test_saved_aol_off_allows_selection_without_waiting_for_cp_restart(self):
    self.save('AlwaysOnLateral', b'0')
    self.assertTrue(self.feature.rows(True)[0].available)
    self.assertEqual(self.cp.alternativeExperience, 32)
    self.assertEqual(self.cp.safetyConfigs[0].safetyParam, 18)

  def test_onroad_and_safe_mode_still_deny_selection(self):
    self.save('AlwaysOnLateral', b'0')
    self.assertFalse(self.feature.rows(False)[0].available)
    self.save('SafeMode', b'1')
    self.assertFalse(self.feature.rows(True)[0].available)

  def test_reader_uses_the_same_display_only_capability(self):
    self.cp = self.cp.as_reader()
    self.assertEqual(len(self.feature.rows(True)), 1)
    self.assertEqual(self.cp.alternativeExperience, 32)

  def test_invalid_native_owner_remains_hidden(self):
    for word in (0, 2, 130, 65535):
      self.cp.safetyConfigs[0].safetyParam = word
      self.assertEqual(self.feature.rows(True), ())

  def test_unrelated_experience_and_brand_remain_hidden(self):
    self.cp.alternativeExperience = 16
    self.assertEqual(self.feature.rows(True), ())
    self.cp.alternativeExperience = 32
    self.cp.brand = 'toyota'
    self.assertEqual(self.feature.rows(True), ())

  def test_existing_unmarked_mach_e_stays_available(self):
    self.cp.alternativeExperience = 0
    self.save('AlwaysOnLateral', b'0')
    self.assertTrue(self.feature.rows(True)[0].available)
