"""Dom pedal protocol for the qualified Corolla/RAV4 TSS2 camera-longitudinal owners."""
import numpy as np
from opendbc.can import CANParser
from opendbc.car import structs, CanData
from opendbc.car.toyota.values import CAR, ToyotaFlags, MIN_ACC_SPEED, PEDAL_TRANSITION

LONG_WORD = 0x2049
STOCK_WORD = 0x2249
CAMERA_PEDAL_CARS = frozenset((CAR.TOYOTA_COROLLA_TSS2, CAR.TOYOTA_RAV4_TSS2))


def checksum(data):
  crc = 0xFF
  for value in reversed(data[:-1]):
    crc ^= value
    for _ in range(8):
      crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
  return crc


def hardware_supported(candidate, fingerprint, car_fw):
  if candidate not in CAMERA_PEDAL_CARS or fingerprint.get(0, {}).get(0x201) != 6:
    return False
  if any(0x201 in fingerprint.get(bus, {}) for bus in (1, 2)) or any(
      addr in messages for messages in fingerprint.values() for addr in (0x2FF, 0x2AA)):
    return False
  from opendbc.car.toyota.fingerprints import FW_VERSIONS
  known = FW_VERSIONS[candidate]
  for ecu in (structs.CarParams.Ecu.eps, structs.CarParams.Ecu.fwdCamera):
    observed = [fw for fw in car_fw if fw.ecu == ecu]
    if not observed or any(fw.logging or fw.bus != 0 or fw.brand != 'toyota' or
        bytes(fw.fwVersion) not in known.get((ecu, fw.address, fw.subAddress or None), ()) for fw in observed):
      return False
  return True


def configured(cp):
  if cp is None or cp.brand != 'toyota' or cp.carFingerprint not in CAMERA_PEDAL_CARS or (
      cp.notCar or cp.passive or cp.dashcamOnly or not cp.pcmCruise or
      cp.steerControlType != structs.CarParams.SteerControlType.torque or len(cp.safetyConfigs) != 1):
    return False
  required = ToyotaFlags.TSS2 | ToyotaFlags.NO_DSU | ToyotaFlags.RAISED_ACCEL_LIMIT | ToyotaFlags.GAS_INTERCEPTOR
  allowed = required | ToyotaFlags.HYBRID | ToyotaFlags.HAS_BSM
  config = cp.safetyConfigs[0]
  return (cp.flags & required == required and not int(cp.flags) & ~int(allowed) and
          config.safetyModel == structs.CarParams.SafetyModel.toyota and
          config.safetyParam in (LONG_WORD, STOCK_WORD) and
          cp.openpilotLongitudinalControl == (config.safetyParam == LONG_WORD))


def prepare_stock(cp):
  if not configured(cp):
    return False
  cp.openpilotLongitudinalControl = False
  cp.safetyConfigs[0].safetyParam = STOCK_WORD
  cp.autoResumeSng = False
  return True


def command(packer, value, counter):
  active = value > .001
  fields = {'ENABLE': active, 'COUNTER_PEDAL': counter & 15}
  if active:
    fields['GAS_COMMAND'] = fields['GAS_COMMAND2'] = value * 255.
  address, data, bus = packer.make_can_msg('GAS_COMMAND', 0, fields)
  data = bytearray(data)
  # A disabled pedal must contain raw zeros, not a physical-zero offset encoding.
  if not active:
    data[:4] = bytes(4)
  data[-1] = checksum(data)
  return CanData(address, bytes(data), bus)


def amount(cp, cc, cs, accel):
  if not (configured(cp) and cp.openpilotLongitudinalControl and cc.longActive and
          cs.out.canValid and not cs.out.canTimeout and cs.pedal_ready and
          not cs.out.gasPressed and not cs.out.brakePressed):
    return 0.
  if cs.out.standstill:
    return .12 if accel > 0 else 0.
  scale = float(np.interp(cs.out.vEgo, [0., MIN_ACC_SPEED, MIN_ACC_SPEED + PEDAL_TRANSITION], [.4, .5, 0.]))
  offset = float(np.interp(cs.out.vEgo, [0., 2.3, MIN_ACC_SPEED + PEDAL_TRANSITION], [-.4, 0., .2]))
  return float(np.clip(scale * (accel + offset), 0., .5))


class PedalCANParser(CANParser):
  def __init__(self, *args):
    super().__init__(*args)
    self.pedal_counter = None
    self.pedal_valid = False

  def update(self, strings, sendcan=False):
    batches = []
    for stamp, frames in strings:
      accepted = []
      for frame in frames:
        address, data, bus = frame
        if address == 0x201 and bus == self.bus:
          counter = data[4] & 15 if len(data) == 6 else None
          valid = len(data) == 6 and data[-1] == checksum(data)
          if valid:
            valid = self.pedal_counter is None or counter == (self.pedal_counter + 1) & 15
            self.pedal_counter = counter
          self.pedal_valid = valid and data[4] >> 4 == 0
          if not valid:
            continue
        accepted.append(frame)
      batches.append((stamp, accepted))
    return super().update(batches, sendcan)
