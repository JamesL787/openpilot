#!/usr/bin/env python3
"""Read-only H020 startup report. Exit 2 on an activation mismatch/blocker."""
import json
from openpilot.selfdrive.controls.lib.honda_eps_h020_activation import load_activation, validate_final_params, H020ActivationError
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import use_honda_eps_controller
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import CALIBRATION_PROVENANCE


def build_report(cp, raw, params, requested, activation_path=None):
  blockers = []
  snapshot = {"enabled": False}
  try:
    snapshot = load_activation(cp, raw, activation_path)
    validate_final_params(cp, snapshot, params)
  except H020ActivationError as e:
    blockers.append(str(e))
  if requested.get("enabled") and not snapshot.get("enabled"):
    blockers.append("Enabled config has no matching activated CarParams; restart card/controlsd together offroad")
  selected = not blockers and use_honda_eps_controller(cp, snapshot)
  return {"fingerprint": str(cp.carFingerprint), "fingerprintSource": str(cp.fingerprintSource),
          "fuzzyFingerprint": cp.fuzzyFingerprint, "dashcamOnly": cp.dashcamOnly,
          "lateralTuning": cp.lateralTuning.which(), "torqueBP": list(cp.lateralParams.torqueBP),
          "torqueV": list(cp.lateralParams.torqueV), "requested_config": requested, "startup_config": snapshot,
          "restart_required": snapshot != requested, "controller_selected": bool(selected), "blockers": blockers,
          "firmware": [{"ecu": str(f.ecu), "address": hex(f.address),
                        "version": bytes(f.fwVersion).decode("ascii", errors="replace")} for f in cp.carFw],
          "provenance": CALIBRATION_PROVENANCE,
          "limits": ["PTM build is an owner declaration, not an ECU image/hash readback",
                     "No H020 route validation; TGG donor baseline; firmware shaping gates unresolved"]}


def main():
  from cereal import car
  import cereal.messaging as messaging
  from openpilot.common.params import Params
  from opendbc.sunnypilot.car.honda.h020_ptm import read_config
  params = Params()
  raw = params.get("CarParams")
  if not raw:
    raise SystemExit("No CarParams: inspect card startup errors before continuing.")
  cp = messaging.log_from_bytes(raw, car.CarParams)
  report = build_report(cp, raw, params, read_config())
  print(json.dumps(report, indent=2))
  return 2 if report["blockers"] else 0


if __name__ == "__main__":
  raise SystemExit(main())
