"""Clarity with a pedal interceptor: keep the PCM in ACC while openpilot is engaged.

openpilot normally cancels the PCM's own cruise the moment it engages on a car without PCM cruise. Out of ACC the
hybrid PCM creeps, and below ~2.5 mph that creep cancels most of our brake: -0.1 m/s2 against stock ACC's -0.5 with
less pressure (stock-ACC capture, route 00000037--a18acb298f). Stock ACC keeps POWERTRAIN_DATA ACC_STATUS set the whole
time, and with it set the PCM stops creeping.

openpilot still owns brake (BRAKE_COMMAND) and gas (interceptor). The PCM reads only our ACC_HUD, sent like stock's
braking frame: PCM_SPEED 0 (no drive torque; stock coasts as with ACC off) and PCM_GAS at stock's per-speed value.
The camera's standstill hold (CRUISE_STATES 8, CRUISE_SPEED 252, PCM_GAS 0) is never sent. Out of openpilot the PCM's
ACC is cancelled exactly as before. On for every qualified Clarity; with openpilot off (passive) the PCM's cruise state
is reported as it is.
"""
import numpy as np

from opendbc.car import structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.honda.values import CAR, HondaFlags

# Standstill hold floor while openpilot is stopping. The Clarity runs stopAccel 0.0 (StarPilot's entry), so with creep
# gone the hold was only the creep term plus whatever request was left at the stop: 43-51 on the hybrid field
# (00000039--a3fe07ccbe). Stock ACC holds at ~102 (0.40) once settled; nrdr-development, at upstream's stopAccel -2.0,
# holds at ~107-145.
STANDSTILL_HOLD_BRAKE = 0.40

# stock ACC_HUD PCM_GAS while braking or coasting with PCM_SPEED 0, median by speed, made monotonic
PCM_GAS_BP = [v * CV.MPH_TO_MS for v in (0., 2., 4., 6.5, 10., 18., 22., 27., 35.)]
PCM_GAS_V = [38., 38., 48., 62., 66., 66., 74., 94., 98.]


def qualified(CP: structs.CarParams) -> bool:
  return (CP.carFingerprint == CAR.HONDA_CLARITY and CP.openpilotLongitudinalControl and not CP.pcmCruise and
          bool(CP.flags & HondaFlags.GAS_INTERCEPTOR) and not CP.flags & HondaFlags.BOSCH)


class StandstillHold:
  """Latched once the car stops while openpilot is stopping; released when openpilot leaves the stopping state.
  carState.standstill flickers at ~2 Hz while stopped (XMISSION_SPEED noise around 0), and following it pumped the
  brake between ~45 and ~80 twice a second (00000039--3b, stop at 86.9 s)."""
  def __init__(self):
    self.latched = False

  def update(self, brake: float, standstill: bool, stopping: bool) -> float:
    self.latched = stopping and (self.latched or standstill)
    return max(brake, STANDSTILL_HOLD_BRAKE) if self.latched else brake


def hud_gas(v_ego: float) -> int:
  return int(round(float(np.interp(v_ego, PCM_GAS_BP, PCM_GAS_V))))
