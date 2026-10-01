"""Shared setup and recovery instructions for the comma and car displays."""


def setup_instructions(status: dict) -> str:
  common = ("1. Enable Starpilot Auto and Bluetooth on the comma. In Galaxy, open Toggles > Starpilot Auto > " +
            "Starpilot Auto Certificate and install your Starpilot Auto app file. ")
  if status.get("connection") == "wired":
    return common + (
      "2. Select USB as the connection type. Use a short data-capable cable from the car's Starpilot Auto USB port " +
      "to the comma. Charging-only ports and cables cannot project. No Bluetooth pairing is needed. " +
      "3. Allow Starpilot Auto on the car screen. Leave auto-connect on; USB setup starts when the comma goes onroad " +
      "and reconnects after a cable interruption. Use Connect to test while parked. " +
      "Disconnect pauses auto-connect until the next drive or until you tap Connect.")
  return common + (
    "2. Your car must support wireless Starpilot Auto; Bluetooth audio alone is not enough. " +
    "While parked, set the comma to Offroad in Settings > System, then select Pair a New Car. " +
    "Add a device on the car, select the car in the comma's list, and confirm the code on both screens. " +
    "Allow Starpilot Auto on the car. If needed, select Choose Car after pairing. " +
    "3. Set the comma back to Auto in Settings > System and leave auto-connect on. " +
    "It connects onroad or when the chosen car connects over Bluetooth. Wi-Fi must be enabled; " +
    "the comma joins the car's Wi-Fi automatically. " +
    "Disconnect pauses auto-connect until the next drive or until you tap Connect.")


def recovery_hint(status: dict) -> str:
  """Suggest the next useful action without presenting protocol internals as setup steps."""
  error = str(status.get("error", "")).lower()
  if "identity" in error or "certificate" in error:
    return "Check the certificate in Galaxy > Toggles > Starpilot Auto, and check the comma's date and time."
  stage = status.get("last_stage") or status.get("state")
  if status.get("connection") == "wired" and stage in ("waiting_for_usb", "usb_accessory", "authenticating"):
    return "Use the car's Starpilot Auto USB port and a data-capable cable. Allow Starpilot Auto on the car screen."
  if stage in ("connecting_bluetooth", "discovering", "rfcomm", "wifi_start", "wifi_info"):
    return "Select this comma for Starpilot Auto on the car. Pause Starpilot Auto on another phone if the car is using it."
  if stage in ("joining_wifi", "connecting_tcp"):
    return "Keep Wi-Fi enabled on the comma. It joins the car network automatically; no hotspot or password entry is needed."
  return "Reconnection is automatic while the car is present. If it keeps failing, export the connection logs from Galaxy > Toggles > Starpilot Auto."
