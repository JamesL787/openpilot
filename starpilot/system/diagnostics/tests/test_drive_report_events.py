import pytest

from openpilot.starpilot.system.diagnostics import drive_report


@pytest.mark.parametrize("event", ["upload_paused_starpilot_auto", "upload_resumed_starpilot_auto",
                                   "upload_paused_android_auto", "upload_resumed_android_auto"])
def test_upload_events_are_watched_under_both_names(event):
  assert drive_report.WATCHED_EVENTS.search(event)
