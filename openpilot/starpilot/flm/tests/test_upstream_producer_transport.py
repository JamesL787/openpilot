"""Installed source closure only; no kernel or model-output equivalence proof."""
import hashlib
from pathlib import Path

import pytest

from openpilot.starpilot.flm import producer_clock_equivalence as clock


APPROVED = {
  'selfdrive/modeld/modeld.py': 'cc4f0187df2505a623db079e1ee3b6dfea56577303aa104c1770fd744f16f2ba',
  'visionipc/visionipc_server.cc': 'a4325a5171eacb931eb271d06a992d2f27216040df113d92099f62cdfa67d81a',
  'visionipc/visionipc_client.cc': 'd142cd60eedabfc581e9770fcd6f0ca81b762ba9dbc608b54dd20a27a317a52d',
}


def test_exact_installed_upstream_closure_is_checked_before_contract():
  contract = clock.pinned_default_contract()
  assert len(clock.PRODUCER_SOURCE_HASHES) == 19
  assert {relative: expected for _, relative, expected in clock.PRODUCER_SOURCE_HASHES if relative in APPROVED} == APPROVED
  assert contract.producer_revision == clock.CLOSURE_SHA256
  assert contract.proof_sha256 == clock.CLOSURE_SHA256


@pytest.mark.parametrize('relative', tuple(APPROVED))
def test_unapproved_change_to_each_new_producer_fails_closed(monkeypatch, relative):
  original = Path.read_bytes
  reached = []
  def changed(path):
    body = original(path)
    if path.as_posix().endswith(relative):
      reached.append(path)
      assert hashlib.sha256(body).hexdigest() == APPROVED[relative]
      return body + b'\n'
    return body
  monkeypatch.setattr(Path, 'read_bytes', changed)
  with pytest.raises(ValueError, match='unsupported original mixed-producer source closure'):
    clock.pinned_default_contract()
  assert len(reached) == 1


def test_unapproved_second_producer_cannot_be_blessed_by_new_modeld_pin(monkeypatch):
  rows = list(clock.PRODUCER_SOURCE_HASHES)
  index = next(index for index, (_, relative, _) in enumerate(rows) if relative == 'system/sensord/sensord.py')
  package, relative, _ = rows[index]
  rows[index] = (package, relative, '0' * 64)
  monkeypatch.setattr(clock, 'PRODUCER_SOURCE_HASHES', tuple(rows))
  with pytest.raises(ValueError, match='unsupported original mixed-producer source closure'):
    clock.pinned_default_contract()


def test_actual_live_collector_startup_uses_installed_producer_contract():
  from types import SimpleNamespace
  from openpilot.starpilot.flm.fullrate_collector import FullrateCollector
  from openpilot.starpilot.flm.source_plant_runtime import start_original_capture

  enabled = []
  adapter = SimpleNamespace(enable_original_context_capture=lambda: enabled.append(True),
                            current_physical_valid=False, last_physical_ns=0, source_plant_clock=None)
  collector = FullrateCollector(adapter)
  assert start_original_capture(collector)
  assert enabled == [True]
  assert collector.original_source_capture is not None
  assert collector.original_source_clock_contract == clock.pinned_default_contract()
  assert adapter.source_plant_capture_error is None
  assert not adapter.current_physical_valid and adapter.last_physical_ns == collector.last_qualified_response == 0
  assert not collector.ready and collector.live_tracking is None


def test_changed_model_producer_still_blocks_actual_live_collector(monkeypatch):
  from types import SimpleNamespace
  from openpilot.starpilot.flm.fullrate_collector import FullrateCollector
  from openpilot.starpilot.flm.source_plant_runtime import start_original_capture

  original = Path.read_bytes
  def changed(path):
    body = original(path)
    return body + b'\n' if path.as_posix().endswith('selfdrive/modeld/modeld.py') else body
  monkeypatch.setattr(Path, 'read_bytes', changed)
  enabled = []
  adapter = SimpleNamespace(enable_original_context_capture=lambda: enabled.append(True),
                            current_physical_valid=False, last_physical_ns=0, source_plant_clock=None)
  collector = FullrateCollector(adapter)
  assert not start_original_capture(collector)
  assert enabled == []
  assert adapter.source_plant_capture_error == 'original_source_clock_contract_unavailable'
  assert not adapter.current_physical_valid and adapter.last_physical_ns == collector.last_qualified_response == 0
  assert getattr(collector, 'original_source_capture', None) is None
