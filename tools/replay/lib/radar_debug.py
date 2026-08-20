"""Pure helpers for the replay radar inspector.

The replay UI deliberately keeps this classification separate from radar
control code.  It is only a visualization of the already-published
``liveTracks`` and StarPilot lead messages.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


# Palette indices are installed by tools/replay/ui.py on the indexed top-down
# surface.  The values are intentionally stable so recorded screenshots and
# simple offline tests remain comparable.
RADAR_PALETTE = {
  "leadOne": 1,
  "leadTwo": 5,
  "leadLeft": 3,
  "leadRight": 6,
  "adjacentStopped": 4,
  "measured": 2,
  "estimated": 7,
}

RADAR_ROLE_PRIORITY = (
  "leadOne",
  "leadTwo",
  "leadLeft",
  "leadRight",
  "adjacentStopped",
)


def _field(reader: Any, name: str, default: Any = None) -> Any:
  if reader is None:
    return default
  try:
    return getattr(reader, name)
  except (AttributeError, KeyError, TypeError):
    return default


def _track_id(reader: Any) -> int:
  try:
    return int(_field(reader, "radarTrackId", -1))
  except (TypeError, ValueError):
    return -1


def radar_track_roles(radar_state: Any = None, starpilot_radar_state: Any = None) -> dict[int, tuple[str, ...]]:
  """Return published lead roles keyed by the native radar track ID."""
  role_readers = (
    ("leadOne", _field(radar_state, "leadOne")),
    ("leadTwo", _field(radar_state, "leadTwo")),
    ("leadLeft", _field(starpilot_radar_state, "leadLeft")),
    ("leadRight", _field(starpilot_radar_state, "leadRight")),
    ("adjacentStopped", _field(starpilot_radar_state, "adjacentStopped")),
  )

  roles: dict[int, list[str]] = {}
  for role, reader in role_readers:
    if not bool(_field(reader, "status", False)):
      continue
    track_id = _track_id(reader)
    if track_id < 0:
      continue
    roles.setdefault(track_id, []).append(role)

  return {track_id: tuple(track_roles) for track_id, track_roles in roles.items()}


def radar_track_style(track_id: int, measured: bool, roles: Mapping[int, Iterable[str]] | None = None) -> tuple[str, int]:
  """Return the display role and indexed-surface palette for one point."""
  try:
    track_id = int(track_id)
  except (TypeError, ValueError):
    track_id = -1

  point_roles = set(roles.get(track_id, ())) if roles is not None else set()
  for role in RADAR_ROLE_PRIORITY:
    if role in point_roles:
      return role, RADAR_PALETTE[role]

  role = "measured" if measured else "estimated"
  return role, RADAR_PALETTE[role]


def radar_track_summary(points: Iterable[Any], roles: Mapping[int, Iterable[str]] | None = None) -> dict[str, Any]:
  """Summarize the current published radar payload for the replay sidebar."""
  track_ids: list[int] = []
  measured = 0
  role_ids: dict[str, list[int]] = {role: [] for role in RADAR_ROLE_PRIORITY}

  for point in points or ():
    try:
      track_id = int(_field(point, "trackId", -1))
    except (TypeError, ValueError):
      track_id = -1
    if track_id >= 0:
      track_ids.append(track_id)
    if bool(_field(point, "measured", False)):
      measured += 1
    for role in (roles or {}).get(track_id, ()):
      if role in role_ids and track_id not in role_ids[role]:
        role_ids[role].append(track_id)

  return {
    "count": len(track_ids),
    "measured": measured,
    "track_ids": tuple(sorted(track_ids)),
    "role_ids": {role: tuple(sorted(ids)) for role, ids in role_ids.items()},
  }
