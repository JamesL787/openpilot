import tempfile
import unittest
from pathlib import Path

from opendbc.car.supported_brands import SUPPORTED_BRANDS
from tools.ci.process_replay_coverage import REQUIRED_REPLAY_LABELS, SHARED_PROCESS_INPUT_LABELS, replay_coverage, write_coverage

ALL_LABELS = REQUIRED_REPLAY_LABELS | SHARED_PROCESS_INPUT_LABELS


class TestProcessReplayCoverage(unittest.TestCase):
  def report(self, platforms=None, labels=None):
    active = {brand: [brand.upper() + "_CAR"] for brand in SUPPORTED_BRANDS}
    return replay_coverage(active if platforms is None else platforms, ALL_LABELS if labels is None else labels, {}, full_test=True)

  def test_supported_brand_recordings_and_shared_inputs_are_required(self):
    report = self.report()
    self.assertEqual(report["errors"], [])
    self.assertEqual(report["unrecorded_gaps"], [])
    self.assertEqual(report["shared_process_input_labels"], sorted(SHARED_PROCESS_INPUT_LABELS))
    for label in ALL_LABELS:
      with self.subTest(label=label):
        self.assertTrue(self.report(labels=ALL_LABELS - {label})["errors"])

  def test_every_required_vehicle_recording_is_a_supported_brand(self):
    self.assertEqual({label.rstrip("0123456789").lower() for label in REQUIRED_REPLAY_LABELS}, set(SUPPORTED_BRANDS))
    self.assertFalse({label.rstrip("0123456789").lower() for label in SHARED_PROCESS_INPUT_LABELS} & set(SUPPORTED_BRANDS))

  def test_recording_from_an_unsupported_brand_or_an_unrecorded_active_brand_fails(self):
    self.assertTrue(self.report(labels=ALL_LABELS | {"FORD"})["errors"])
    active = self.report()["active_platforms"]
    self.assertTrue(self.report(platforms={**active, "new_brand": ["NEW_CAR"]})["errors"])

  def test_partial_run_reports_without_errors(self):
    report = replay_coverage({"honda": ["HONDA_CAR"]}, {"HONDA"}, {}, full_test=False)
    self.assertEqual(report["errors"], [])
    self.assertFalse(report["full_test"])

  def test_artifact_and_summary_carry_no_qualification_claim(self):
    with tempfile.TemporaryDirectory() as temporary:
      destination = Path(temporary) / "coverage.json"
      summary = Path(temporary) / "summary.md"
      write_coverage(self.report(), destination, summary)
      self.assertIn('"scope": "process_replay_input_inventory"', destination.read_text())
      self.assertIn("dashcam mode", summary.read_text())
      self.assertIn("does not qualify the fleet", summary.read_text())


if __name__ == "__main__":
  unittest.main()
