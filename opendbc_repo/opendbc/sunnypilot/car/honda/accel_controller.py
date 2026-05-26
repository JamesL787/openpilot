"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import numpy as np

from opendbc.car import structs

DriveMode = structs.CarStateSP.DriveMode

# ECO is the reference baseline — Honda's PCM already remaps throttle response by
# drive mode, so these curves only do a partial correction on top of that stock behavior.
# NORMAL and SPORT partially compensate for Honda's per-mode torque remap so OP
# doesn't double-amplify it, while preserving meaningful mode character.
#
# Measured remap (steady-state, route_09, 14–22 m/s, longActive only):
#   NORMAL: Honda gives ~1.30x more force/APP vs ECO
#   SPORT:  Honda gives ~1.44x more force/APP vs ECO
# Full correction would equalize all modes — instead we apply ~50% correction so
# NORMAL still feels ~1.18x ECO and SPORT ~1.20x ECO (combined OP cmd × Honda remap).
# Retune when cleaner log available (flat road, OP engaged, 60s per mode at cruise).
_GAS_BP_ECO    = [0.,  3.,  6., 10., 15., 20.]
_GAS_V_ECO     = [0.07, 0.22, 0.28, 0.37, 0.39, 0.39]

_GAS_BP_NORMAL = [0.,  3.,  6., 10., 15., 20.]
_GAS_V_NORMAL  = [0.09, 0.22, 0.35, 0.43, 0.50, 0.50]

_GAS_BP_SPORT  = [0.,  3.,  6., 10., 15., 20.]
_GAS_V_SPORT   = [0.08, 0.20, 0.32, 0.40, 0.46, 0.46]


class GasProfileController:
  def __init__(self):
    self._last_drive_mode: DriveMode = DriveMode.unknown

  def get_gas_multiplier(self, v_ego: float, drive_mode: DriveMode) -> tuple[float, bool]:
    """Returns (gas_multiplier, mode_changed). Caller resets adaptive state on mode_changed."""
    mode_changed = drive_mode != self._last_drive_mode and self._last_drive_mode != DriveMode.unknown
    self._last_drive_mode = drive_mode

    if drive_mode == DriveMode.eco:
      bp, v = _GAS_BP_ECO, _GAS_V_ECO
    elif drive_mode == DriveMode.sport:
      bp, v = _GAS_BP_SPORT, _GAS_V_SPORT
    else:
      bp, v = _GAS_BP_NORMAL, _GAS_V_NORMAL

    return float(np.interp(v_ego, bp, v)), mode_changed
