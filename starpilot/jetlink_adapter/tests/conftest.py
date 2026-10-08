import pytest

from openpilot.starpilot import jetlink_adapter

# every test reaches the vendored package the way the product does
jetlink_adapter.vendor_on_path()


@pytest.fixture(autouse=True)
def fresh_adapter_binding(monkeypatch):
  """The adapter binds Jetlink once per process and keeps the answer; tests that change what it finds start clean."""
  monkeypatch.setattr(jetlink_adapter, "_bound", None)
  monkeypatch.setattr(jetlink_adapter, "_failed_hooks", {})
  monkeypatch.setattr(jetlink_adapter, "_status_cache", (0.0, None))
