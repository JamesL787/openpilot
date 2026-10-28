"""The replay UI's radar point roles (Night Star port, adapted from ns-bosch-radar-testing for 7.0's leads and flags)."""
from types import SimpleNamespace

import numpy as np

from openpilot.tools.replay.lib.radar_debug import RADAR_PALETTE, radar_track_roles, radar_track_style, radar_track_summary


def _lead(track_id, status=True):
  return SimpleNamespace(status=status, radarTrackId=track_id)


def _point(track_id, measured, d_rel=30.0, y_rel=0.0):
  return SimpleNamespace(trackId=track_id, dRel=d_rel, yRel=y_rel, vRel=0.0, deprecated=SimpleNamespace(measured=measured))


def test_roles_come_from_the_published_leads_by_track_id():
  roles = radar_track_roles(SimpleNamespace(leadOne=_lead(12), leadTwo=_lead(44)))
  assert roles == {12: ("leadOne",), 44: ("leadTwo",)}
  assert radar_track_roles(SimpleNamespace(leadOne=_lead(12, status=False), leadTwo=_lead(-1))) == {}
  assert radar_track_roles(None) == {}


def test_lead_role_wins_over_the_measured_colour():
  roles = {12: ("leadOne",)}
  assert radar_track_style(12, True, roles) == ("leadOne", 1)
  assert radar_track_style(63, True, roles) == ("measured", 2)
  assert radar_track_style(63, False, roles) == ("estimated", 7)


def test_summary_counts_measured_points_from_the_deprecated_flag():
  points = [_point(12, True), _point(44, False), _point(51, True)]
  summary = radar_track_summary(points, {12: ("leadOne",), 44: ("leadTwo",)})
  assert summary["count"] == 3 and summary["measured"] == 2
  assert summary["track_ids"] == (12, 44, 51)
  assert summary["role_ids"] == {"leadOne": (12,), "leadTwo": (44,)}


def test_points_are_drawn_in_their_role_colour():
  from openpilot.tools.replay.lib.ui_helpers import UP, get_blank_lid_overlay, maybe_update_radar_points, to_topdown_pt
  overlay = get_blank_lid_overlay(UP)
  points = [_point(12, True, d_rel=20.0), _point(44, False, d_rel=40.0)]
  maybe_update_radar_points(points, overlay, {12: ("leadOne",)})
  for point, color in ((points[0], RADAR_PALETTE["leadOne"]), (points[1], RADAR_PALETTE["estimated"])):
    px, py = to_topdown_pt(point.dRel, -point.yRel)
    assert overlay[px, py] == color
  # without roles every point stays white, as on stock 7.0
  plain = get_blank_lid_overlay(UP)
  maybe_update_radar_points(points, plain)
  px, py = to_topdown_pt(20.0, 0.0)
  assert plain[px, py] == 255 and np.count_nonzero(plain == 255) > 0
