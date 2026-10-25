"""Clarity with a pedal interceptor: keep the PCM in ACC while openpilot is engaged (opt-in test mode).

openpilot normally cancels the PCM's own cruise the moment it engages on a car without PCM cruise. Out of ACC the
hybrid PCM creeps, and below ~2.5 mph that creep cancels most of our brake: -0.1 m/s2 against stock ACC's -0.5 with
less pressure (stock-ACC capture, route 00000037--a18acb298f). Stock ACC keeps POWERTRAIN_DATA ACC_STATUS set the whole
time, and with it set the PCM stops creeping.

openpilot still owns brake (BRAKE_COMMAND) and gas (interceptor). The PCM reads only our ACC_HUD, sent like stock's
braking frame: PCM_SPEED 0 (no drive torque; stock coasts as with ACC off) and PCM_GAS at stock's per-speed value.
The camera's standstill hold (CRUISE_STATES 8, CRUISE_SPEED 252, PCM_GAS 0) is never sent. Out of openpilot the PCM's
ACC is cancelled exactly as before.
"""
import numpy as np

from opendbc.car import structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.honda.values import CAR, HondaFlags

# stock ACC_HUD PCM_GAS while braking or coasting with PCM_SPEED 0, median by speed, made monotonic
PCM_GAS_BP = [v * CV.MPH_TO_MS for v in (0., 2., 4., 6.5, 10., 18., 22., 27., 35.)]
PCM_GAS_V = [38., 38., 48., 62., 66., 66., 74., 94., 98.]


def qualified(CP: structs.CarParams) -> bool:
  return (CP.carFingerprint == CAR.HONDA_CLARITY and CP.openpilotLongitudinalControl and not CP.pcmCruise and
          bool(CP.flags & HondaFlags.GAS_INTERCEPTOR) and not CP.flags & HondaFlags.BOSCH)


def hud_gas(v_ego: float) -> int:
  return int(round(float(np.interp(v_ego, PCM_GAS_BP, PCM_GAS_V))))
