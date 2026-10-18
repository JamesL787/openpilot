import hashlib
import json
from pathlib import Path
import unittest

from openpilot.starpilot.models.catalog import BUNDLED_CURRENT, CATALOG, CATALOG_PATH, DEFAULT_SMALL, resolve_selection
from openpilot.starpilot.models.status import (ModelHealth, ModelLoad, ModelOutput, ModelProcess,
                                              ModelVariant, project_status)


def _local_rebuilds(*model_ids):
  """Personal branch: StarPilot IDs only load here when rebuilt for this tinygrad and listed in the local catalog."""
  from dataclasses import replace
  from unittest.mock import patch
  from openpilot.starpilot.models import catalog as catalog_module
  entries = catalog_module.model_entries()
  for model_id in model_ids:
    entries[model_id] = replace(catalog_module.BY_ID[model_id], selectable=True, compiler_revision=catalog_module.COMPILER_REVISION)
  return patch.object(catalog_module, "model_entries", lambda root=None: dict(entries))


class TestModelCatalogStatus(unittest.TestCase):
  def test_catalog_pins_current_source_and_lists_model_metadata(self):
    manifest_ids = [row['id'] for row in json.loads(CATALOG_PATH.read_text())['models']]
    self.assertEqual(len(manifest_ids), len(set(manifest_ids)))
    catalog_ids = [entry.model_id for entry in CATALOG]
    self.assertEqual(len(catalog_ids), len(set(catalog_ids)))
    # personal branch: the built-in comma small model replaces RDF V4; StarPilot's rows stay known, never selectable
    self.assertCountEqual(catalog_ids, [BUNDLED_CURRENT, DEFAULT_SMALL, *manifest_ids])
    entry = resolve_selection(None)
    self.assertEqual(entry.model_id, DEFAULT_SMALL)
    source = Path(__file__).resolve().parents[4] / entry.source_path
    from openpilot.common.file_chunker import get_existing_chunks
    digest = hashlib.sha256()
    for part in get_existing_chunks(source)[1:]:
      with part.open('rb') as stream:
        while block := stream.read(1024 * 1024):
          digest.update(block)
    self.assertEqual(digest.hexdigest(), entry.source_sha256)
    self.assertEqual(entry.version, "v16")
    with self.assertRaises(ValueError):
      resolve_selection("rdf43")  # published for 9d0446a4, not loadable on this tinygrad
    with self.assertRaises(ValueError):
      resolve_selection("unknown-model")
    with self.assertRaises(ValueError):
      resolve_selection("")

  def test_loaded_identity_requires_same_process_and_fresh_both_outputs(self):
    process = ModelProcess(421, 5000, True)
    load = ModelLoad(421, 5000, 1_100_000_000, BUNDLED_CURRENT, ModelVariant.SMALL, "a" * 64)
    output = ModelOutput(1_180_000_000, True, 1_185_000_000, True, False, False)
    self.assertEqual(project_status(None, process, load, output, 1_200_000_000).health, ModelHealth.ACTIVE)
    self.assertEqual(project_status(None, ModelProcess(422, 5001, True), load, output,
                                    1_200_000_000).health, ModelHealth.IDENTITY_UNAVAILABLE)
    self.assertEqual(project_status(None, process, load, output, 1_500_000_001).health, ModelHealth.STALE)
    self.assertEqual(project_status(None, process, load, ModelOutput(1_050_000_000, True, 1_185_000_000,
                                                                     True, False, False), 1_200_000_000).health,
                     ModelHealth.STALE)
    self.assertEqual(project_status(None, process, load, ModelOutput(1_180_000_000, True, 1_185_000_000,
                                                                     True, True, True), 1_200_000_000).health,
                     ModelHealth.FAILED)

  def test_verified_actual_big_is_not_overridden_by_cached_load_marker(self):
    with _local_rebuilds('cinquev3', 'sc23'):
      self._test_verified_actual_big_is_not_overridden_by_cached_load_marker()

  def _test_verified_actual_big_is_not_overridden_by_cached_load_marker(self):
    process = ModelProcess(421, 5000, True)
    load = ModelLoad(421, 5000, 1_100_000_000, "cinquev3", ModelVariant.CHESTNUT, "a" * 64)
    for marker in (None, False, True):
      output = ModelOutput(1_180_000_000, True, 1_185_000_000, True, True, marker)
      self.assertEqual(project_status("cinquev3", process, load, output, 1_200_000_000).health, ModelHealth.ACTIVE)
      invalid = ModelOutput(1_180_000_000, False, 1_185_000_000, True, True, marker)
      self.assertEqual(project_status("cinquev3", process, load, invalid, 1_200_000_000).health, ModelHealth.STALE)
      small = ModelOutput(1_180_000_000, True, 1_185_000_000, True, False, marker)
      self.assertEqual(project_status("cinquev3", process, load, small, 1_200_000_000).health, ModelHealth.FAILED)

  def test_runtime_stall_preserves_requested_big_and_active_small_identity(self):
    with _local_rebuilds('cinquev3', 'sc23'):
      self._test_runtime_stall_preserves_requested_big_and_active_small_identity()

  def _test_runtime_stall_preserves_requested_big_and_active_small_identity(self):
    process = ModelProcess(421, 5000, True)
    load = ModelLoad(421, 5000, 1_100_000_000, 'sc23', ModelVariant.SMALL, 'a' * 64, 'chestnut-run-stalled')
    output = ModelOutput(1_180_000_000, True, 1_185_000_000, True, False, False)
    status = project_status('cinquev3', process, load, output, 1_200_000_000)
    self.assertEqual((status.requested_id, status.loaded_id, status.health), ('cinquev3', 'sc23', ModelHealth.ACTIVE))
    self.assertTrue(status.pending_next_start)
    self.assertEqual(status.fallback_reason, 'chestnut-run-stalled')

  def test_catalog_selection_preserves_actual_fallback_identity(self):
    with _local_rebuilds('cinquev3', 'sc23'):
      self._test_catalog_selection_preserves_actual_fallback_identity()

  def _test_catalog_selection_preserves_actual_fallback_identity(self):
    process = ModelProcess(421, 5000, True)
    load = ModelLoad(421, 5000, 1_100_000_000, "sc23", ModelVariant.SMALL, "a" * 64, "chestnut-load-failed")
    output = ModelOutput(1_180_000_000, True, 1_185_000_000, True, False, False)
    status = project_status("cinquev3", process, load, output, 1_200_000_000)
    self.assertEqual((status.requested_id, status.loaded_id, status.health), ("cinquev3", "sc23", ModelHealth.ACTIVE))
    self.assertTrue(status.pending_next_start)
    self.assertEqual(status.fallback_reason, "chestnut-load-failed")
    impossible = ModelLoad(421, 5000, 1_100_000_000, "cinquev3", ModelVariant.SMALL, "a" * 64)
    self.assertEqual(project_status("cinquev3", process, impossible, output, 1_200_000_000).health, ModelHealth.IDENTITY_UNAVAILABLE)

  def test_no_saved_choice_or_stale_receipt_claims_active(self):
    process = ModelProcess(421, 5000, True)
    self.assertEqual(project_status(None, None, None, None, 1_200_000_000).health, ModelHealth.UNAVAILABLE)
    self.assertEqual(project_status(None, process, None, None, 1_200_000_000).health, ModelHealth.LOADING)
    stale_load = ModelLoad(421, 4999, 1_100_000_000, BUNDLED_CURRENT, ModelVariant.SMALL, "a" * 64)
    self.assertEqual(project_status(None, process, stale_load, None, 1_200_000_000).health, ModelHealth.LOADING)


if __name__ == "__main__":
  unittest.main()
