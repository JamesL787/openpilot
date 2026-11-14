"""
EPS CAN bus diagnostic tool for Honda/Acura EPS ECUs.

Checks whether the EPS (Electric Power Steering) ECU is alive on the CAN bus
for a routine communication sanity check or recovery troubleshooting. Runs three checks:

  1. Passive sniff  – listen for any raw CAN traffic from the EPS physical addr
  2. UDS ping       – send Tester Present and wait for a positive response
  3. UDS session    – try Default → Extended diagnostic sessions and read the
                      Application Software ID (part number)

By default checks buses 0 and 1. Pass --bus to pin to a single bus.

Usage (on the comma device via SSH):
  python3 eps-diag.py            # check buses 0 and 1, address 0x18DA30F1
  python3 eps-diag.py -b 1       # pin to bus 1
  python3 eps-diag.py --scan     # brute-force scan all common Honda ECU addrs
"""

from __future__ import annotations

import argparse
import os
import sys
import time

DEPENDENCY_ERROR = None
try:
  from panda import Panda
  from opendbc.car.structs import CarParams
  from opendbc.car.uds import UdsClient, SESSION_TYPE, DATA_IDENTIFIER_TYPE, NegativeResponseError, MessageTimeoutError
except ImportError as e:
  DEPENDENCY_ERROR = e

# ── addresses ────────────────────────────────────────────────────────────────
EPS_ADDR = 0x18DA30F1   # tester → EPS  (29-bit, ISO 15765-4 physical)
DEFAULT_BUSES = (0, 1)


def response_addr_for(req_addr: int) -> int:
  """Honda ISO-TP physical response for a 29-bit request (0x18DAXXF1 → 0x18DAF1XX)."""
  return (req_addr & 0xFFFF0000) | 0x0000F100 | ((req_addr >> 8) & 0xFF)

# A handful of other Honda ECU addresses useful for --scan
HONDA_SCAN_ADDRS = [
  (0x18DA30F1, "EPS"),
  (0x18DA10F1, "PCM/ECM"),
  (0x18DA60F1, "Combination meter"),
  (0x18DA28F1, "SRS airbag"),
  (0x18DA0EF1, "VSA/ABS"),
  (0x18DA21F1, "Transmission"),
  (0x18DA3DF1, "LKAS camera"),
  (0x18DAB0F1, "LKAS camera alt"),
]

SNIFF_DURATION_S = 3.0   # seconds to passively listen
UDS_TIMEOUT_S    = 3.0   # seconds to wait for each UDS response


def connect_panda() -> Panda:
  p = Panda(disable_checks=True)
  try:
    p.set_safety_mode(CarParams.SafetyModel.elm327)
    print(f"  Connected to Panda (serial: {p.get_serial()})")
  except Exception:
    try:
      p.close()
    except Exception as e:
      print(f"  Cleanup: could not close Panda ({e})")
    raise
  return p


def format_app_id(data) -> str:
  if isinstance(data, (bytes, bytearray)):
    return bytes(data).decode("latin-1", "replace").strip("\x00").strip()
  return str(data).strip("\x00").strip()


def car_eps_fw_from_params():
  """EPS firmware string from CarParamsPersistent / CarParams, or None."""
  try:
    from cereal import car
  except Exception:
    if os.path.isdir("/data/openpilot"):
      sys.path.append("/data/openpilot")
    try:
      from cereal import car
    except Exception:
      return None
  for p in ("/data/params/d/CarParamsPersistent", "/data/params/d/CarParams"):
    try:
      data = open(p, "rb").read()
    except OSError:
      continue
    try:
      with car.CarParams.from_bytes(data) as CP:
        for fw in CP.carFw:
          if fw.ecu == "eps":
            v = format_app_id(bytes(fw.fwVersion))
            if v:
              return v
    except Exception:
      continue
  return None


def passive_sniff(panda: Panda, buses: list[int], resp_addr: int,
                  duration: float = SNIFF_DURATION_S) -> dict[int, bool]:
  """Listen for raw CAN frames from the EPS response address on each bus."""
  bus_list = list(buses)
  label = ", ".join(str(b) for b in bus_list)
  print(f"\n{'='*60}")
  print(f"[1/3] Passive CAN sniff on bus(es) {label} for {duration:.0f}s …")
  print(f"      Watching for frames from 0x{resp_addr:08X} (EPS response addr)")

  print("      Passive silence is inconclusive: this diagnostic address is not a periodic heartbeat.")
  # can_clear(bus) only drops queued TX; 0xFFFF drops buffered RX so stale frames aren't counted.
  for bus in bus_list:
    panda.can_clear(bus)
  panda.can_clear(0xFFFF)

  deadline = time.monotonic() + duration
  eps_counts = {b: 0 for b in bus_list}
  all_extended: dict[int, set[int]] = {b: set() for b in bus_list}

  while time.monotonic() < deadline:
    for addr, dat, recv_bus in panda.can_recv():
      if recv_bus not in eps_counts:
        continue
      if addr > 0x7FF:                         # 29-bit extended frame
        all_extended[recv_bus].add(addr)
      if addr == resp_addr:
        eps_counts[recv_bus] += 1
        print(f"  *** EPS frame on bus {recv_bus}! addr=0x{addr:08X}  data={dat.hex()}")

  results = {}
  for bus in bus_list:
    count = eps_counts[bus]
    results[bus] = count > 0
    if count:
      print(f"  RESULT bus {bus}: EPS responding passively ({count} frames)")
    else:
      print(f"  RESULT bus {bus}: No frames from EPS response addr")
      ext = all_extended[bus]
      if ext:
        print("    Other 29-bit addresses seen: " +
              ", ".join(f"0x{a:08X}" for a in sorted(ext)))
      else:
        print("    No 29-bit extended frames seen on this bus.")

  return results


def request(label, operation):
  """Separate communication evidence from support for a requested operation."""
  try:
    data = operation()
    print(f"  {label}: accepted")
    return True, True, data
  except NegativeResponseError as e:
    print(f"  {label}: ECU responded; request rejected ({e})")
    return True, False, None
  except MessageTimeoutError:
    print(f"  {label}: no response within timeout")
    return False, False, None


def uds_tester_present(uds, bus):
  received, _, _ = request(f"Tester Present (bus {bus})", uds.tester_present)
  return received


def uds_session_and_id(uds, bus):
  received, accepted, _ = request(f"Default session (bus {bus})",
    lambda: uds.diagnostic_session_control(SESSION_TYPE.DEFAULT))
  result = {"responded": received, "default": accepted, "extended": False, "app_id": None}
  for extended in (False, True):
    if extended:
      received, accepted, _ = request("Extended session",
        lambda: uds.diagnostic_session_control(SESSION_TYPE.EXTENDED_DIAGNOSTIC))
      result["responded"] |= received
      result["extended"] = accepted
      if not accepted:
        continue
    received, accepted, data = request("Application Software ID",
      lambda: uds.read_data_by_identifier(DATA_IDENTIFIER_TYPE.APPLICATION_SOFTWARE_IDENTIFICATION))
    result["responded"] |= received
    if accepted:
      result["app_id"] = format_app_id(data) or result["app_id"]
    if result["app_id"]:
      break
  return result


def scan_all(panda, bus):
  print(f"Scanning common Honda ECU addresses on bus {bus}")
  responding = False
  for addr, name in HONDA_SCAN_ADDRS:
    uds = UdsClient(panda, addr, bus=bus, timeout=1.5)
    received, _, _ = request(f"0x{addr:08X} {name}", uds.tester_present)
    responding |= received
  return responding


def print_recovery_advice(confirmed, detected_eps=None):
  print("\nRecovery troubleshooting (requested with --recovery):")
  if confirmed:
    print("  ECU communication was observed. This does not establish firmware or steering operation.")
  else:
    print("  Communication was not confirmed; this alone does not diagnose a brick or bootloader fault.")
  print("  Check ignition ON, Panda connection, selected bus/address, and the original flash output.")
  print("  If troubleshooting a failed flash, retain the matching stock recovery image.")
  print("  Use python3 flash.py for a deliberate recovery attempt; recovery is not guaranteed.")
  if detected_eps:
    print(f"  Cached EPS identifier (not live confirmation): {detected_eps}")


def main(argv=None):
  ap = argparse.ArgumentParser(description="Honda/Acura EPS communication sanity check")
  ap.add_argument("-b", "--bus", default=None, type=lambda x: int(x, 0),
                  help="Pin a CAN bus (default: check 0 and 1)")
  ap.add_argument("--addr", default=EPS_ADDR, type=lambda x: int(x, 0), help="EPS UDS request address")
  ap.add_argument("--scan", action="store_true", help="Scan common ECUs; success does not specifically confirm EPS")
  ap.add_argument("--sniff-only", action="store_true", help="Passive only; silence is inconclusive")
  ap.add_argument("--recovery", action="store_true", help="Include failed-flash troubleshooting guidance")
  args = ap.parse_args(argv)
  buses = [args.bus] if args.bus is not None else list(DEFAULT_BUSES)
  panda = None
  clients = []
  print("Honda/Acura EPS communication sanity check")
  print("Communication results do not verify firmware correctness or steering operation.")
  try:
    if DEPENDENCY_ERROR is not None:
      raise RuntimeError(f"Openpilot dependencies unavailable: {DEPENDENCY_ERROR}")
    panda = connect_panda()
    if args.scan:
      results = [scan_all(panda, bus) for bus in buses]
      confirmed = any(results)
      print("Scan communication confirmed (not necessarily EPS)." if confirmed else "Scan communication not confirmed.")
      return 0 if confirmed else 1
    sniff = passive_sniff(panda, buses, response_addr_for(args.addr))
    confirmed = any(sniff.values())
    live_id = None
    if not args.sniff_only:
      for bus in buses:
        uds = UdsClient(panda, args.addr, bus=bus, timeout=UDS_TIMEOUT_S)
        clients.append(uds)
        ping = uds_tester_present(uds, bus)
        result = uds_session_and_id(uds, bus)
        if not (ping or result["responded"]):
          # Nothing answered on this bus: restoring its session would only time
          # out and print a misleading power-cycle warning.
          clients.remove(uds)
        confirmed |= ping or result["responded"]
        live_id = live_id or result["app_id"]
        print(f"  Bus {bus}: default session accepted={result['default']}, "
              f"extended session accepted={result['extended']}, software ID read={bool(result['app_id'])}")
    print("\nEPS communication confirmed." if confirmed else "\nEPS communication not confirmed.")
    cached = None
    if live_id:
      print(f"  EPS software ID read live: {live_id}")
    else:
      cached = car_eps_fw_from_params()
      if cached:
        print(f"  Cached CarParams EPS identifier (not current firmware confirmation): {cached}")
    if args.recovery:
      print_recovery_advice(confirmed, cached)
    return 0 if confirmed else 1
  except Exception as e:
    print(f"\nEPS check could not run: {e}")
    print("Check dependencies, Panda connection, ignition ON, and that openpilot has released the Panda.")
    return 2
  finally:
    for uds in clients:
      try:
        uds.diagnostic_session_control(SESSION_TYPE.DEFAULT)
      except Exception as e:
        print(f"  Cleanup: could not restore default session ({e}); power-cycle before resuming use.")
    if panda is not None:
      try:
        panda.close()
      except Exception as e:
        print(f"  Cleanup: could not close Panda ({e})")


if __name__ == "__main__":
  sys.exit(main())
