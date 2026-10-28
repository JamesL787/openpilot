"""Conservative GM query-family and legacy CAN alias discovery."""
from opendbc.car.gm.values import CAR, CanBus


def automatic_volt_candidate(candidate, fingerprint, candidates):
  # Never replace an identified vehicle, firmware result, or explicit choice.
  # Only the known gateway/CC CAN collision can enter this refinement.
  if candidate is not None or set(candidates.get(CanBus.POWERTRAIN, ())) != {
      CAR.CHEVROLET_VOLT, CAR.CHEVROLET_VOLT_CC}:
    return candidate
  pt = fingerprint.get(CanBus.POWERTRAIN, {})
  camera = fingerprint.get(CanBus.CAMERA, {})
  required = {0xD3: 2, 0x130: 1, 0x17D: 6, 0x210: 4, 0x236: 5,
              0x184: 8, 0x34A: 5, 0x1C4: 8, 0xC9: 8, 0x1E1: 7, 0xF1: 6}
  # This recorded F1-brake installation mirrors PT on buses 0 and 2. A live
  # camera, interceptor, SASCM, radar bus, or another DLC/layout remains outside
  # this rule and retains normal discovery/manual configuration ownership.
  if (not pt or pt != camera or
      any(messages for bus, messages in fingerprint.items() if bus not in (CanBus.POWERTRAIN, CanBus.CAMERA)) or
      any(pt.get(address) != size for address, size in required.items()) or
      any(address in pt for address in (0xBE, 0x201, 0x2FF, 0x320))):
    return candidate
  # The recorded car has ordinary cruise, no ACC and no camera. The absent
  # camera is not evidence of an ACC actuator owner. Read actual ECM cruise
  # activity and retain button-only control; explicit ACC selections are above.
  return CAR.CHEVROLET_VOLT_CC


# Frequent normal-bus frames observed on mirrored pedal installations. This is
# only diagnostic query-family evidence, never a vehicle/control fingerprint.
PEDAL_NORMAL_BUS_LAYOUT = {0xD3: 2, 0xBE: 6, 0xC9: 8, 0x1C4: 8,
                           0xF1: 6, 0x1E1: 7, 0x201: 6}


def pedal_normal_bus0_topology(fingerprint):
  if any(messages for bus, messages in fingerprint.items() if bus not in (0, 2)):
    return False
  return all(fingerprint.get(bus, {}).get(address) == size
             for bus in (0, 2) for address, size in PEDAL_NORMAL_BUS_LAYOUT.items())
