#!/usr/bin/env python3
"""Read-only readiness check for wireless Starpilot Auto, run on the comma before a car test.

  python3 tools/starpilot_auto/preflight.py [--car AA:BB:CC:DD:EE:FF]

Changes nothing: no pairing, no network activation, no Bluetooth class change.
Each line is PASS, WARN (works, with a caveat) or FAIL (fix before the car test).
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys

RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
  RESULTS.append((status, name, detail))
  print(f"{status:4}  {name}" + (f": {detail}" if detail else ""), flush=True)


def run(command: list[str], timeout: float = 5.0) -> tuple[int, str]:
  try:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return result.returncode, (result.stdout + result.stderr).strip()
  except (OSError, subprocess.TimeoutExpired) as error:
    return -1, str(error)


def check_identity() -> None:
  from openpilot.starpilot.system.starpilot_auto.identity import IdentityError, expiry_warning, load_identity
  try:
    ident = load_identity()
    record("WARN" if expiry_warning(ident) else "PASS", "phone identity", f"expires {ident.expires[:10]} ({ident.days_left} days)")
    record("PASS" if ident.root else "WARN", "car verification root", "present" if ident.root else "root-cert.pem missing: car not verified")
  except IdentityError as error:
    record("FAIL", "phone identity", str(error))


def check_encoder() -> None:
  import time
  from openpilot.starpilot.system.starpilot_auto import hw_encoder
  from openpilot.starpilot.system.starpilot_auto.encoder import H264Encoder
  hardware_ok = False
  for name, factory in (("hardware H.264", lambda: hw_encoder.HardwareH264Encoder(1280, 720, margin_height=240)),
                        ("software H.264", lambda: H264Encoder(1280, 720, fps=30))):
    encoder = None
    try:
      if name.startswith("hardware") and not hw_encoder.LIBRARY.is_file():
        raise RuntimeError(f"{hw_encoder.LIBRARY} missing (prebuilt library not deployed)")
      encoder = factory()
      frames = 30
      started = time.monotonic()
      for index in range(frames):
        encoder.encode_rgba(bytes([index * 8 % 256]) * (1280 * 720 * 4), keyframe=index == 0)
      per_frame = (time.monotonic() - started) * 1000 / frames
      ok = per_frame < (30 if name.startswith("hardware") else 60)
      record("PASS" if ok else "WARN", name, f"{encoder.backend}, {per_frame:.1f} ms/frame at 720p")
      hardware_ok = hardware_ok or name.startswith("hardware")
    except Exception as error:
      fatal = name.startswith("software") and not hardware_ok  # software only matters as the fallback
      record("FAIL" if fatal else "WARN", name, f"{type(error).__name__}: {error}")
    finally:
      if encoder is not None:
        encoder.close()


def check_car_view() -> None:
  node = "/dev/dri/renderD128"
  record("PASS" if os.access(node, os.R_OK | os.W_OK) else "WARN", "GPU render node (car layout)",
         node if os.access(node, os.R_OK | os.W_OK) else f"{node} not accessible; the car will get the comma-screen mirror")
  import ctypes
  for library in ("libEGL.so", "libgbm.so"):
    try:
      ctypes.CDLL(library)
      record("PASS", library)
    except OSError as error:
      record("WARN", library, f"{error}; the car will get the comma-screen mirror")


def check_bluetooth(car: str) -> None:
  record("PASS" if hasattr(socket, "AF_BLUETOOTH") else "WARN", "Python Bluetooth sockets",
         "native" if hasattr(socket, "AF_BLUETOOTH") else "not compiled in; libc fallback will be used")
  code, out = run(["bluetoothctl", "--version"])
  record("PASS" if code == 0 else "WARN", "BlueZ", out.splitlines()[0] if out else "bluetoothctl unavailable")
  record("PASS" if os.path.exists("/sys/class/bluetooth/hci0") else "FAIL", "Bluetooth adapter",
         "hci0 present" if os.path.exists("/sys/class/bluetooth/hci0") else "turn Bluetooth on in StarPilot settings")
  tools = [tool for tool in ("btmgmt", "hciconfig") if shutil.which(tool)]
  code, _ = run(["sudo", "-n", "true"])
  record("PASS" if tools and code == 0 else "WARN", "phone Class of Device control",
         f"{', '.join(tools)} with sudo -n" if tools and code == 0 else "unavailable; the comma keeps its own class (usually fine)")
  try:
    from openpilot.starpilot.system.starpilot_auto.bluez_phone import BluezPhone
    phone = BluezPhone(lambda *a, **k: None)
    try:
      _, adapter = phone.adapter()
      record("PASS", "adapter", f"{adapter.get('Name', '')} class {int(adapter.get('Class', 0)):#08x} powered={adapter.get('Powered')}")
      if car:
        device = phone.device(car)
        if device is None:
          record("FAIL", "car", f"{car} unknown to BlueZ; pair it first")
        else:
          record("PASS" if device["paired"] else "FAIL", "car paired", f"{device['name']} paired={device['paired']}")
          record("PASS" if device["starpilot_auto"] else "WARN", "car advertises Starpilot Auto Wireless",
                 "yes" if device["starpilot_auto"] else "UUID not in BlueZ cache yet; SDP will be queried directly")
    finally:
      phone.close()
  except Exception as error:
    record("FAIL", "BlueZ D-Bus", str(error))


def check_wifi() -> None:
  code, out = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
  if code != 0:
    record("FAIL", "NetworkManager", out[:200])
    return
  wifi = [line for line in out.splitlines() if ":wifi:" in line]
  record("PASS" if wifi else "FAIL", "Wi-Fi device", "; ".join(wifi) or "none")
  if any(":connected:" in line for line in wifi):
    record("WARN", "current Wi-Fi use", "joining the car's network replaces it until Starpilot Auto stops (hotspot/tethering included)")
  code, out = run(["nmcli", "radio", "wifi"])
  record("PASS" if out.strip() == "enabled" else "FAIL", "Wi-Fi radio", out.strip())
  code, out = run(["iw", "list"], timeout=5)
  if code == 0:
    record("PASS" if "5180 MHz" in out or "5745 MHz" in out else "WARN", "5 GHz support",
           "yes" if "5180 MHz" in out or "5745 MHz" in out else "not reported; car networks are usually 5 GHz")
  code, out = run(["ip", "route", "show", "default"])
  record("PASS", "default route (kept during projection)", out.splitlines()[0] if out else "none")


def check_ui() -> None:
  code, out = run(["pgrep", "-af", "selfdrive.ui.ui|selfdrive/ui/ui.py"])
  record("PASS" if code == 0 else "WARN", "UI process", "running" if code == 0 else "not found; projected frames come from the UI")
  record("PASS" if os.path.isdir("/dev/shm") else "FAIL", "shared memory", "/dev/shm")


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--car", default="", help="Bluetooth address of the paired car, if known")
  args = parser.parse_args()
  if not args.car:
    try:
      from openpilot.starpilot.system.starpilot_auto.identity import load_config
      args.car = load_config()["receiver_address"]
    except Exception:
      pass
  for check in (check_identity, check_encoder, check_car_view, lambda: check_bluetooth(args.car), check_wifi, check_ui):
    try:
      check()
    except Exception as error:
      record("FAIL", getattr(check, "__name__", "check"), str(error))
  failures = [name for status, name, _ in RESULTS if status == "FAIL"]
  print(json.dumps({"ready": not failures, "failures": failures}))
  return 1 if failures else 0


if __name__ == "__main__":
  sys.exit(main())
