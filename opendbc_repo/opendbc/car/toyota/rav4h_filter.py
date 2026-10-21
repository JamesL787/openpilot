"""Exact RAV4 Hybrid TSS-P smartDSU ownership; separate from Prius retrofit."""
from opendbc.can import CANParser
from opendbc.car import structs
from opendbc.car.toyota.values import CAR, ToyotaFlags

# Bit15 is a distinct exact-profile marker; reserve Dom bit14 for Lexus ALT_CRUISE.
LONG_WORD = 0x9049
STOCK_WORD = 0x9249


def hardware_supported(candidate, fingerprint, car_fw):
  if (candidate != CAR.TOYOTA_RAV4H or fingerprint.get(0, {}).get(0x2FF) != 8 or
      any(0x2FF in fingerprint.get(bus, {}) for bus in (1, 2)) or
      any(address in messages for messages in fingerprint.values() for address in (0x201, 0x2AA)) or
      any(address in fingerprint.get(2, {}) for address in (0x343, 0x4CB))):
    return False
  from opendbc.car.toyota.fingerprints import FW_VERSIONS
  expected = FW_VERSIONS[CAR.TOYOTA_RAV4H]
  required = (structs.CarParams.Ecu.eps, structs.CarParams.Ecu.fwdCamera, structs.CarParams.Ecu.fwdRadar)
  for ecu in required:
    observed = [fw for fw in car_fw if fw.ecu == ecu]
    if not observed:
      return False
    for fw in observed:
      if fw.logging or fw.bus != 0 or fw.brand != "toyota":
        return False
      key = (ecu, fw.address, fw.subAddress or None)
      if bytes(fw.fwVersion) not in expected.get(key, ()):
        return False
  return True


def configured(cp):
  if (cp is None or cp.brand != "toyota" or cp.carFingerprint != CAR.TOYOTA_RAV4H or
      not cp.pcmCruise or cp.dashcamOnly or cp.notCar or cp.passive or
      cp.steerControlType != structs.CarParams.SteerControlType.torque or len(cp.safetyConfigs) != 1):
    return False
  flags = int(ToyotaFlags.HYBRID | ToyotaFlags.LONG_FILTER)
  hold = bool(cp.flags & ToyotaFlags.AUTO_BRAKE_HOLD)
  if cp.flags != flags | (int(ToyotaFlags.AUTO_BRAKE_HOLD) if hold else 0):
    return False
  config = cp.safetyConfigs[0]
  return (config.safetyModel == structs.CarParams.SafetyModel.toyota and
          config.safetyParam in (LONG_WORD, STOCK_WORD) and
          cp.openpilotLongitudinalControl == (config.safetyParam == LONG_WORD) and
          (not hold or cp.openpilotLongitudinalControl))


def enabled(cp):
  return configured(cp) and cp.openpilotLongitudinalControl


def prepare_stock(cp):
  if not configured(cp):
    return False
  cp.flags &= ~int(ToyotaFlags.AUTO_BRAKE_HOLD)
  cp.alternativeExperience &= ~(128 | 256)
  cp.openpilotLongitudinalControl = False
  cp.safetyConfigs[0].safetyParam = STOCK_WORD
  cp.autoResumeSng = False
  return True


class Rav4hCANParser(CANParser):
  """Malformed smartDSU frames cannot refresh this exact owner's source lease."""

  def update(self, strings, sendcan=False):
    frames = [(stamp, [frame for frame in batch if frame[0] != 0x2FF or frame[2] != self.bus or len(frame[1]) == 8])
              for stamp, batch in strings]
    return super().update(frames, sendcan)
