"""The Night Star settings page: the fork's own settings, edited live (onroad too).

Every row here is read again while driving (the EPS rows once a second, the controller rows each refresh), except Angle
Mode (Clarity only), which picks the steering type and so applies at the next car start. Every calibrated EPS image
steers with LatControlHondaEps, so the controller has no row. The output low-pass bands are fixed by design and have no
row.
"""
import math

from openpilot.starpilot.saved_document import commit_exact
from openpilot.starpilot.saved_source import read_saved
from openpilot.starpilot.ui.feature_settings_state import FeatureRow

SEATBELT_KEY = "DisableSeatbeltCheck"
ANGLE_MODE_KEY = "HondaClarityAngleMode"
ANGLE_CAP3_KEY = "HondaClarityAngleCap3"
ANGLE_HOLD_KEY = "HondaClarityAngleHoldOverride"
CLARITY = "HONDA_CLARITY"

# key -> (label, reason)
BOOL_ROWS = {
  "HondaDriverAssistDuringOverride": ("Assist During Override",
                                      "Keep steering assist active while you override the wheel."),
  ANGLE_MODE_KEY: ("Angle Mode",
                   "Steer by wheel angle through the EPS's own angle loop. Needs the angle-mode EPS firmware (build 0x04); "
                   "on any other EPS firmware steering stays unavailable, so turn this off. Takes effect at the next start."),
  ANGLE_CAP3_KEY: ("Angle Lateral Cap 3.0 m/s\u00b2",
                   "Angle mode only: steer with the EPS's 3.0 m/s\u00b2 lateral-acceleration clamp (mode 4) instead of 4.0. Needs "
                   "EPS build 0x05, 0x06 or 0x08; on other builds it has no effect. Switches when lateral is off."),
  ANGLE_HOLD_KEY: ("Angle Hold Through Override",
                   "Angle mode only: keep steering engaged while you override the wheel. Assist fades to zero while you steer and "
                   "ramps back after you let go, instead of dropping out and re-engaging. Needs EPS build 0x06 or 0x08."),
  SEATBELT_KEY: ("Disable Seatbelt Check", "Allow engaging and staying engaged with the driver's seatbelt unlatched."),
}
# key -> (label, reason, minimum, maximum, step, unit, integer)
NUMBER_ROWS = {
  "HondaEpsAngleRateLimit": ("Steering Angle Rate Limit", "Ceiling on how fast the desired wheel angle may move. 0 turns it off.",
                             0.0, 1000.0, 10.0, "deg/s", True),
  "HondaDriverOverrideThreshold": ("Override Torque Threshold",
                                   "Driver torque that counts as an override. A modified EPS needs more than stock (1200).",
                                   1200.0, 3000.0, 20.0, "", True),
  "HondaMinSteerSpeed": ("Minimum Steer Speed", "No steering torque below this speed.", 0.0, 25.0, 1.0, "mph", True),
  "HondaOverrideTorqueScale": ("Torque During Override", "Share of the steering command kept while you override.",
                               0.0, 100.0, 5.0, "%", True),
  # the car controller clamps both fades to 0-10 s (starpilot/car/honda/modified_eps.py)
  "HondaOverrideFadeDownSecs": ("Override Fade Down",
                                "Time to ease the steering command out when you override. 0 cuts it at once.",
                                0.0, 10.0, 0.1, "s", False),
  "HondaOverrideFadeUpSecs": ("Override Fade Up", "Time to bring the steering command back after you let go of the wheel.",
                              0.0, 10.0, 0.1, "s", False),
}
# in the order a press runs: what counts as one, the fade out, what is kept during it, the fade back in
EPS_KEYS = ("HondaDriverOverrideThreshold", "HondaOverrideFadeDownSecs", "HondaOverrideTorqueScale", "HondaOverrideFadeUpSecs",
            "HondaDriverAssistDuringOverride", "HondaMinSteerSpeed")
KEYS = frozenset((*BOOL_ROWS, *NUMBER_ROWS))


def _format(number: float, integer: bool) -> str:
  return str(int(round(number))) if integer else str(round(number, 3))


class NightStarFeature:
  def __init__(self, owner):
    self.params = owner.params
    self.authority = owner.authority
    self.vehicle_params = owner.vehicle_params
    self.vehicle_fingerprint = owner.vehicle_fingerprint

  def capability(self):
    """(fingerprint, flags, calibrated) for a Honda on a modified EPS, else None."""
    cp = self.vehicle_params()
    if cp is None:
      return None
    from opendbc.car.honda.modified_eps import modified_eps
    try:
      if not modified_eps(cp):
        return None
      from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import eps_firmware_calibration
      calibration = eps_firmware_calibration(cp)
    except (AttributeError, TypeError, ValueError):
      return None
    return str(cp.carFingerprint), int(cp.flags), calibration is not None

  def _keys(self, capability) -> tuple[str, ...]:
    keys = []
    if capability is not None:
      _, _, calibrated = capability
      if calibrated:  # read by LatControlHondaEps (torque) and the honda CarController (Clarity angle mode)
        keys.append("HondaEpsAngleRateLimit")
      keys.extend(EPS_KEYS)
      fingerprint, _, _ = capability
      if fingerprint == CLARITY:   # read once at car start (starpilot/car/honda/clarity_angle_mode.py)
        keys.append(ANGLE_MODE_KEY)
        keys.append(ANGLE_CAP3_KEY)   # live, read with the EPS rows; used only on EPS builds 0x05, 0x06, 0x08
        keys.append(ANGLE_HOLD_KEY)   # live; used only on EPS builds 0x06, 0x08
    keys.append(SEATBELT_KEY)
    return tuple(keys)

  def _saved_bool(self, key):
    raw, readable = read_saved(self.params, key, 8)
    if not readable or raw not in (None, b"0", b"1"):
      return None
    return (raw == b"1") if raw is not None else self._default_on(key)

  def _default_on(self, key) -> bool:
    # get_default_value is typed: True for a BOOL key whose default is "1" (no BOOL row defaulted on before Angle Mode)
    return self.params.get_default_value(key) in (True, "1", b"1")

  def _default(self, key) -> str:
    value = self.params.get_default_value(key)
    return "" if value is None else str(value)

  def _row(self, key, live, capability) -> FeatureRow:
    raw, readable = read_saved(self.params, key, 32)
    allowed = live
    binding = {} if key == SEATBELT_KEY else {"capability": capability, "vehicle_fingerprint": self.vehicle_fingerprint()}
    if key in BOOL_ROWS:
      label, reason = BOOL_ROWS[key]
      value = self._saved_bool(key) if readable else None
      valid = value is not None
      return FeatureRow(key, label, ("On" if value else "Off") if valid else "Invalid saved choice", source=raw,
                        choices=("Off", "On") if valid else (), default_value="On" if self._default_on(key) else "Off",
                        available=allowed and valid, reason=reason if valid else "Invalid saved choice", **binding)
    label, reason, low, high, step, unit, integer = NUMBER_ROWS[key]
    try:
      number = float(raw.decode() if raw is not None else self._default(key))
      valid = readable and math.isfinite(number) and low <= number <= high
    except (ValueError, UnicodeDecodeError):
      number, valid = 0.0, False
    return FeatureRow(key, label, _format(number, integer) if valid else "Invalid saved value", source=raw,
                      step=step if valid else 0.0, minimum=low, maximum=high, unit=unit,
                      default_value=self._default(key) or None, available=allowed and valid,
                      reason=reason if valid else "Invalid saved value", **binding)

  def rows(self, parked):
    del parked  # these settings are live
    capability = self.capability()
    live = self.authority("preferences")
    return tuple(self._row(key, live, capability) for key in self._keys(capability))

  def apply(self, request):
    key = request.key
    capability = self.capability()
    if (key not in self._keys(capability) or request.dependencies or request.related_source is not None or
        request.display_unit or request.direction):
      return False
    if key != SEATBELT_KEY and (request.capability is None or request.capability != capability or
                                not request.vehicle_fingerprint or self.vehicle_fingerprint() != request.vehicle_fingerprint):
      return False
    if key in BOOL_ROWS:
      if request.value not in ("Off", "On") or request.expected not in (None, b"0", b"1"):
        return False
      raw = b"1" if request.value == "On" else b"0"
    else:
      _, _, low, high, _, _, integer = NUMBER_ROWS[key]
      try:
        number = float(request.value)
      except ValueError:
        return False
      if not math.isfinite(number) or not low <= number <= high:   # off-grid is fine: the Clarity saved 219 deg/s
        return False
      raw = _format(number, integer).encode()

    def authorized():
      return (self.authority("preferences") and self.capability() == capability and
              (key == SEATBELT_KEY or self.vehicle_fingerprint() == request.vehicle_fingerprint))

    result = commit_exact(self.params, key=key, max_bytes=32, expected=request.expected, raw=raw,
                          authorized=authorized, temp_prefix=".night-star-")
    return result.committed and result.verified
