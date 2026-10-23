#!/usr/bin/env python3
"""Read-only: report whether the H020 rev-b controller is selected for the CarParams card published."""
import json

from openpilot.selfdrive.controls.lib.honda_eps_calibrations import CALIBRATION_PROVENANCE
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import use_honda_eps_controller
from opendbc.sunnypilot.car.honda.h020_ptm import is_h020


def build_report(cp):
  return {"fingerprint": str(cp.carFingerprint), "fingerprintSource": str(cp.fingerprintSource),
          "fuzzyFingerprint": cp.fuzzyFingerprint, "dashcamOnly": cp.dashcamOnly,
          "lateralTuning": cp.lateralTuning.which(), "torqueBP": list(cp.lateralParams.torqueBP),
          "torqueV": list(cp.lateralParams.torqueV), "h020_rev_b_eps": is_h020(cp.carFw),
          "controller_selected": use_honda_eps_controller(cp),
          "firmware": [{"ecu": str(f.ecu), "address": hex(f.address),
                        "version": bytes(f.fwVersion).decode("ascii", errors="replace")} for f in cp.carFw],
          "provenance": CALIBRATION_PROVENANCE,
          "limits": ["EPS version string cannot tell the 4250 and 3200 tracker images apart",
                     "No H020 route validation; TGG donor baseline; firmware shaping gates unverified"]}


def main():
  from cereal import car
  import cereal.messaging as messaging
  from openpilot.common.params import Params
  raw = Params().get("CarParams")
  if not raw:
    raise SystemExit("No CarParams: let the existing res software identify the vehicle first.")
  print(json.dumps(build_report(messaging.log_from_bytes(raw, car.CarParams)), indent=2))


if __name__ == "__main__":
  main()
