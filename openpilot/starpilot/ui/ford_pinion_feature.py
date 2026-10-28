"""Parked, init-only pinion measurement preference shared by native UI and Galaxy."""
from opendbc.car.ford.aol import qualified as aol_qualified
from opendbc.car.ford.pinion import KEY
from openpilot.starpilot.saved_source import read_saved
from openpilot.starpilot.saved_document import commit_exact
from openpilot.starpilot.ui.feature_settings_state import FeatureRow

CHOICES = {0: "Off", 1: "On"}


def read_choice(params):
  raw, readable = read_saved(params, KEY, 8)
  valid = readable and raw in (None, b"0", b"1")
  return int(valid and raw == b"1"), raw, readable, valid


class FordPinionFeature:
  def __init__(self, owner):
    self.owner = owner

  def capability(self):
    cp = self.owner.vehicle_params()
    try:
      if cp is None:
        return None
      from opendbc.car.ford.pinion import GEOMETRY
      if cp.carFingerprint not in GEOMETRY or not aol_qualified(cp):
        return None
      return (str(cp.carFingerprint), int(cp.flags), int(cp.alternativeExperience), bool(cp.openpilotLongitudinalControl),
              bool(cp.pcmCruise), str(cp.steerControlType), bool(cp.passive), bool(cp.dashcamOnly), bool(cp.notCar),
              tuple((str(c.safetyModel), int(c.safetyParam)) for c in cp.safetyConfigs))
    except (AttributeError, TypeError, ValueError, OverflowError):
      return None

  def dependencies(self):
    values = []
    for key in ("SafeMode", "AlwaysOnLateral"):
      raw, readable = read_saved(self.owner.params, key, 8)
      if not readable or raw not in ((None, b"0") if key == "SafeMode" else (None, b"0", b"1")):
        return None
      values.append((key, raw))
    return tuple(values)

  def rows(self, parked):
    capability = self.capability()
    if capability is None:
      return ()
    value, raw, readable, valid = read_choice(self.owner.params)
    dependencies = self.dependencies()
    return (FeatureRow(KEY, "Use Pinion Yaw Sensor", CHOICES[value] if valid else "Invalid saved choice", raw,
                       choices=tuple(CHOICES.values()), available=parked and self.owner.authority("parked_preferences") and
                       readable and dependencies is not None, capability=capability,
                       dependencies=dependencies or (), repair_value="" if valid else CHOICES[0], default_value=CHOICES[0],
                       reason="Off by default. Uses steering-pinion curvature instead of RCM yaw in control and Panda safety. "
                              + "Applies next vehicle startup; Safe Mode must be off."),)

  def apply(self, request):
    value = next((code for code, label in CHOICES.items() if label == request.value), None)
    if (request.key != KEY or value is None or request.related_source is not None or request.display_unit or request.direction):
      return False

    def authorized():
      capability = self.capability()
      _, raw, readable, valid = read_choice(self.owner.params)
      dependencies = self.dependencies()
      return (self.owner.authority("parked_preferences") and bool(request.vehicle_fingerprint) and
              self.owner.vehicle_fingerprint() == request.vehicle_fingerprint and capability is not None and
              capability == request.capability and dependencies is not None and dependencies == request.dependencies and
              readable and raw == request.expected and (valid or value == 0))

    result = commit_exact(self.owner.params, key=KEY, max_bytes=8, raw=str(value).encode(), expected=request.expected,
                          authorized=authorized, temp_prefix=".ford-pinion-")
    return result.committed and result.verified

