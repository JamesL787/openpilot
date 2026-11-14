import pytest


@pytest.fixture(autouse=True)
def aol_alert_at_withdrawal(monkeypatch):
  """These contracts were written when commIssue sounded at the 30 ms command
  withdrawal. AOL_STALE_ALERT_NS = 0 restores exactly that path (the gate is then
  always due); test_stale_alert_debounce.py covers the shipped 100 ms delay."""
  from openpilot.selfdrive.selfdrived import selfdrived
  monkeypatch.setattr(selfdrived, 'AOL_STALE_ALERT_NS', 0)
