#!/usr/bin/env python3
"""Read-only H020 activation/CarParams report; run from the existing res checkout on the device."""
import json
from cereal import car
import cereal.messaging as messaging
from openpilot.common.params import Params
from opendbc.sunnypilot.car.honda.h020_ptm import read_config
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import use_honda_eps_controller
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import CALIBRATION_PROVENANCE


def main():
  raw = Params().get("CarParams")
  if not raw:
    raise SystemExit("No CarParams: let the existing res software identify the vehicle first.")
  cp = messaging.log_from_bytes(raw, car.CarParams)
  cfg = read_config()
  print(json.dumps({"fingerprint": str(cp.carFingerprint), "dashcamOnly": cp.dashcamOnly,
                   "lateralTuning": cp.lateralTuning.which(), "torqueBP": list(cp.lateralParams.torqueBP),
                   "torqueV": list(cp.lateralParams.torqueV), "config": cfg,
                   "controller_selected": use_honda_eps_controller(cp),
                   "firmware": [{"ecu": str(f.ecu), "address": hex(f.address),
                                 "version": bytes(f.fwVersion).decode("ascii", errors="replace")} for f in cp.carFw],
                   "provenance": CALIBRATION_PROVENANCE}, indent=2))


if __name__ == "__main__":
  main()
