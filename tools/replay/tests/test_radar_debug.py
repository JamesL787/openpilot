from types import SimpleNamespace

from openpilot.tools.replay.lib.radar_debug import radar_track_roles, radar_track_style, radar_track_summary


def _lead(track_id, status=True):
  return SimpleNamespace(status=status, radarTrackId=track_id)


def test_roles_use_persistent_track_id_not_wire_position():
  roles = radar_track_roles(
    SimpleNamespace(leadOne=_lead(12), leadTwo=_lead(-1, False)),
    SimpleNamespace(leadLeft=_lead(12), leadRight=_lead(44), adjacentStopped=_lead(51)),
  )

  assert roles[12] == ("leadOne", "leadLeft")
  assert roles[44] == ("leadRight",)
  assert roles[51] == ("adjacentStopped",)


def test_lead_role_has_priority_over_measured_color():
  roles = {12: ("leadOne",)}
  assert radar_track_style(12, True, roles) == ("leadOne", 1)
  assert radar_track_style(63, True, roles) == ("measured", 2)
  assert radar_track_style(63, False, roles) == ("estimated", 7)


def test_summary_reports_ids_and_measurement_count():
  points = [
    SimpleNamespace(trackId=12, measured=True),
    SimpleNamespace(trackId=44, measured=False),
    SimpleNamespace(trackId=51, measured=True),
  ]
  summary = radar_track_summary(points, {12: ("leadOne",), 44: ("leadRight",)})

  assert summary["count"] == 3
  assert summary["measured"] == 2
  assert summary["track_ids"] == (12, 44, 51)
  assert summary["role_ids"]["leadOne"] == (12,)
  assert summary["role_ids"]["leadRight"] == (44,)
