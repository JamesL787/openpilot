"""Compatibility gate for H020 on the C3XL res architecture (no new Params keys or schemas)."""
import json
from pathlib import Path

CONFIG_PATH = Path("/data/honda_eps_h020.json")
SUPPORTED_BUILDS = {"20261011-trk4250", "20261011-trk3200"}


def read_config(path=None):
  try:
    data = json.loads(Path(path or CONFIG_PATH).read_text())
    if (data.get("enabled") is True and data.get("ptm_build") in SUPPORTED_BUILDS
        and data.get("calibration_stage") == "provisional"):
      return data
  except (OSError, ValueError, TypeError, AttributeError):
    pass
  return {"enabled": False}


def is_h020_ptm(car_fw):
  versions = [bytes(f.fwVersion).split(b"\0", 1)[0] for f in car_fw if f.ecu == "eps"]
  return bool(versions) and all(v == b"39990-TEA,H020" for v in versions)


def configure_h020(cp, candidate, car_fw, config=None):
  """Called after res's legacy modified-EPS tune. Other vehicles/stock firmware keep the original behavior."""
  cfg = read_config() if config is None else config
  if not cfg.get("enabled") or str(candidate) != "HONDA_CIVIC_BOSCH" or not is_h020_ptm(car_fw):
    return False
  cp.lateralTuning.init("pid")
  cp.lateralParams.torqueBP, cp.lateralParams.torqueV = [[0, 3840], [0, 3840]]
  # Exact Civic Bosch/TGG base schedule from ns-bosch-radar-testing 92428ab490.
  # Calibration p_scale/i_scale are applied by HondaEpsLateralCore as on the donor.
  mph = 0.44704
  bp = [0.0, 25.0 * mph - 1e-3, 25.0 * mph, 50.0 * mph]
  cp.lateralTuning.pid.kpBP, cp.lateralTuning.pid.kpV = [bp, [0.018, 0.024, 0.048, 0.060]]
  cp.lateralTuning.pid.kiBP, cp.lateralTuning.pid.kiV = [bp, [0.006, 0.008, 0.016, 0.020]]
  cp.lateralTuning.pid.kf = 0.0  # the firmware-inversion core supplies its own feedforward
  return True
