"""TEA-H020 rev-b PTM (modified EPS, comma in the firmware string) on the res architecture.

Same rule as the source branch's EPS_MODIFIED handling: the modified firmware string selects the tune. Only the exact
rev-b ID `39990-TEA,H02B` on a Civic Bosch gets the linear 3840 map and the H020 PID base gains; every other
vehicle and firmware (including the stock and earlier modified H020 images) keeps res's existing behavior.
"""

EPS_ID = b"39990-TEA,H02B"


def is_h020(car_fw):
  versions = {bytes(f.fwVersion).split(b"\0", 1)[0] for f in car_fw if f.ecu == "eps"}
  return versions == {EPS_ID}


def configure_h020(cp, candidate, car_fw):
  """Called after res's legacy modified-EPS tune."""
  if str(candidate) != "HONDA_CIVIC_BOSCH" or not is_h020(car_fw):
    return False
  cp.lateralTuning.init("pid")
  cp.lateralParams.torqueBP, cp.lateralParams.torqueV = [[0, 3840], [0, 3840]]
  # Civic Bosch/TGG four-point base schedule from ns-bosch-radar-testing 92428ab490.
  # Calibration p_scale/i_scale are applied by HondaEpsLateralCore as on the donor.
  mph = 0.44704
  bp = [0.0, 25.0 * mph - 1e-3, 25.0 * mph, 50.0 * mph]
  cp.lateralTuning.pid.kpBP, cp.lateralTuning.pid.kpV = [bp, [0.018, 0.024, 0.048, 0.060]]
  cp.lateralTuning.pid.kiBP, cp.lateralTuning.pid.kiV = [bp, [0.006, 0.008, 0.016, 0.020]]
  cp.lateralTuning.pid.kf = 0.0  # the firmware-inversion core supplies its own feedforward
  return True
