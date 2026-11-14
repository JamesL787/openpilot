"""Blendful's settings row and the Lane Centering / Blendful toggle (kept out of feature_settings_owner.py for size)."""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from openpilot.starpilot.saved_document import commit_exact

if TYPE_CHECKING:
  from openpilot.starpilot.ui.feature_settings_owner import FeatureRow, FeatureSettingsOwner, FeatureSettingsRequest


def model_selected(owner: FeatureSettingsOwner) -> bool:
  """Blendful's custom-model gate: a non-Default model chosen for either slot."""
  try:
    from openpilot.starpilot.models.catalog import DEFAULT_SMALL
    from openpilot.starpilot.models.manager import preferences
    prefs = preferences()
    return bool(prefs.get("small") != DEFAULT_SMALL or prefs.get("big") != "")
  except (OSError, ValueError, TypeError):
    return False


def row(owner: FeatureSettingsOwner, allowed: bool) -> FeatureRow:
  selected = model_selected(owner)
  base = owner._bool_row("Blendful", "Blendful (Alpha)", allowed and selected)
  if not selected:
    return replace(base, available=False,
                   reason="Select a non-Default model to use Blendful")
  return replace(base, reason=base.reason if not base.available else
                 ("Adds a gentle nudge toward lane center on top of the model's own steering, stronger when lane " +
                  "lines are clear. Yields around obstacles. Turns Lane Centering off; not available with the " +
                  "Default model."))


def _flip_off(owner: FeatureSettingsOwner, key: str, expected: bytes, group: str) -> bool:
  def authorized() -> bool:
    return owner.authority(group) and owner._readable(key) and owner._raw(key) == expected
  result = commit_exact(owner.params, key=key, max_bytes=8, raw=b"0", expected=expected,
                        authorized=authorized, temp_prefix=".lane-center-toggle-")
  return result.committed and result.verified


def apply_toggle(owner: FeatureSettingsOwner, request: FeatureSettingsRequest) -> bool:
  """Lane Centering and Blendful are mutually exclusive: turning either on flips the other off."""
  from openpilot.starpilot.lateral.lane_runtime import runtime_supported
  key = request.key
  other = "Blendful" if key == "LaneCentering" else "LaneCentering"
  if (request.value not in ("On", "Off") or request.dependencies or request.capability is not None or
      request.related_source is not None or request.display_unit or request.direction or
      not request.vehicle_fingerprint or request.vehicle_fingerprint != owner.vehicle_fingerprint()):
    return False
  group = "lane" if owner.authority("lane") else "lane_live"
  if not owner.authority(group) or not owner._readable(key) or owner._raw(key) != request.expected:
    return False
  current, _, valid = owner._value(key)
  if not valid or current not in ("0", "1"):
    return False
  if not runtime_supported(owner.vehicle_params()):
    return False
  if key == "Blendful" and request.value == "On" and not model_selected(owner):
    return False
  if request.value == "On" and owner._raw(other) == b"1" and not _flip_off(owner, other, b"1", group):
    return False

  def authorized() -> bool:
    return (owner.authority(group) and owner._readable(key) and owner._raw(key) == request.expected and
            request.vehicle_fingerprint == owner.vehicle_fingerprint() and
            (request.value == "Off" or owner._raw(other) != b"1") and
            (key != "Blendful" or model_selected(owner)) and
            runtime_supported(owner.vehicle_params()))
  result = commit_exact(owner.params, key=key, max_bytes=8, raw=b"1" if request.value == "On" else b"0",
                        expected=request.expected, authorized=authorized, temp_prefix=".lane-center-toggle-")
  return result.committed and result.verified
