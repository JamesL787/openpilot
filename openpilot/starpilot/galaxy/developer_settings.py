"""Galaxy-only, next-drive developer preferences."""

from dataclasses import replace

from openpilot.starpilot.longitudinal.voacc import KEY, DESCRIPTION
from openpilot.starpilot.saved_document import commit_exact
from openpilot.starpilot.saved_source import read_saved
from openpilot.starpilot.ui.feature_settings_state import FeatureRow, FeatureSettingsState


AA_WIFI_KEY = "AndroidAutoDedicatedWifi"
AA_WIFI_DESCRIPTION = ("Experimental. Join the car's Wi-Fi on a second interface so the comma stays on home Wi-Fi or your " +
                       "phone hotspot during wireless Android Auto. Applies from the next Android Auto connection.")
DRIVER_MONITORING_RESET = "reset_driver_monitoring"
DRIVER_MONITORING_RESET_DESCRIPTION = "Clear saved wheel-side detection. Automatic detection restarts on the next drive."


class DeveloperSettingsOwner:
  def __init__(self, params, authorized, *, panda_wake=None, android_auto=None):
    self.params = params
    self.authorized = authorized
    self.panda_wake = panda_wake
    self.android_auto = android_auto  # returns the Android Auto daemon client

  def _android_auto_enabled(self):
    if self.android_auto is None:
      return None
    try:
      return bool(self.android_auto().call("status")["status"].get("dedicated_wifi_interface"))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
      return None  # the service is off; there is nothing to configure

  def _driver_monitoring_reset_allowed(self):
    return self.authorized() and not self.params.get_bool("IsDriverViewEnabled")

  def snapshot(self):
    raw, readable = read_saved(self.params, KEY, 8)
    valid = readable and raw in (None, b"0", b"1")
    parked = self.authorized()
    row = FeatureRow(KEY, "Use VOACC", ("On" if raw == b"1" else "Off") if valid else "Invalid saved value",
                     raw, ("Off", "On") if valid else (), available=parked and valid,
                     reason=(DESCRIPTION if parked else "Park the vehicle to change this setting.") if valid else
                            "Invalid saved value", default_value="Off")
    rhd_raw, rhd_readable = read_saved(self.params, "IsRhdDetected", 8)
    reset_available = self._driver_monitoring_reset_allowed() and rhd_readable
    reset_reason = (DRIVER_MONITORING_RESET_DESCRIPTION if reset_available else
                    "Park the vehicle and close driver camera preview before resetting driver monitoring.")
    reset_row = FeatureRow(DRIVER_MONITORING_RESET, "Reset Driver Monitoring", "Ready" if reset_available else "Unavailable",
                           rhd_raw if rhd_readable else None, available=reset_available, reason=reset_reason)
    firmware_rows = (() if self.panda_wake is None else
                     tuple(replace(item, vehicle_fingerprint=item.capability[0])
                           for item in self.panda_wake.rows(parked) if item.key == "IgnoreIgnitionLine"))
    enabled = self._android_auto_enabled()
    android_auto_rows = () if enabled is None else (
      FeatureRow(AA_WIFI_KEY, "Android Auto: Stay on Wi-Fi", "On" if enabled else "Off", b"1" if enabled else b"0", ("Off", "On"),
                 available=parked, reason=AA_WIFI_DESCRIPTION if parked else "Park the vehicle to change this setting.",
                 default_value="On"),)
    summary = "Changes apply next drive. Panda firmware changes require a device restart." if firmware_rows else "Changes apply next drive."
    return FeatureSettingsState("developer", "Developer driving options", summary,
                                (row, reset_row, *firmware_rows, *android_auto_rows), parked)

  def apply(self, request):
    if request.key == DRIVER_MONITORING_RESET:
      if request.value != "confirm" or not self._driver_monitoring_reset_allowed():
        return False
      current, readable = read_saved(self.params, "IsRhdDetected", 8)
      if not readable or current != request.expected:
        return False
      try:
        self.params.remove("IsRhdDetected")
        self.params.put_bool("OnroadCycleRequested", True, block=True)
      except (OSError, RuntimeError, TypeError, ValueError):
        return False
      return True
    if request.key == "IgnoreIgnitionLine":
      return self.panda_wake is not None and self.panda_wake.apply(request)
    if request.key == AA_WIFI_KEY:
      return self._apply_android_auto(request)
    if request.key != KEY or request.value not in ("Off", "On") or request.expected not in (None, b"0", b"1"):
      return False
    result = commit_exact(self.params, key=KEY, max_bytes=8, raw=b"1" if request.value == "On" else b"0",
                          expected=request.expected, authorized=self.authorized, temp_prefix=".voacc-")
    return result.committed and result.verified

  def _apply_android_auto(self, request):
    enabled, client = self._android_auto_enabled(), self.android_auto
    if (enabled is None or client is None or request.value not in ("Off", "On") or request.expected != (b"1" if enabled else b"0") or
        not self.authorized()):
      return False
    try:
      client().call("set_dedicated_wifi", enabled=request.value == "On")
    except (OSError, RuntimeError, ValueError):
      return False
    return self._android_auto_enabled() == (request.value == "On")
