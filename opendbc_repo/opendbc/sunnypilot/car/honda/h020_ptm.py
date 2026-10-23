"""Compatibility gate for H020 on the C3XL res architecture (no new Params keys or schemas)."""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from opendbc.sunnypilot.car.honda.h020_builds import PTM_BUILDS

CONFIG_PATH = Path("/data/honda_eps_h020.json")
_STARTUP_CONFIG = ContextVar("h020_startup_config", default=None)

SUPPORTED_BUILDS = set(PTM_BUILDS)
PTM_VERSIONS = {build["fw_version"].encode() for build in PTM_BUILDS.values()}


def read_config(path=None):
  try:
    data = json.loads(Path(path or CONFIG_PATH).read_text())
    if (data.get("enabled") is True and data.get("ptm_build") in SUPPORTED_BUILDS
        and data.get("calibration_stage") == "provisional"):
      return data
  except (OSError, ValueError, TypeError, AttributeError):
    pass
  return {"enabled": False}


@contextmanager
def startup_config(config):
  """The one config snapshot card read, shared with get_params_sp during this startup."""
  token = _STARTUP_CONFIG.set(config)
  try:
    yield
  finally:
    _STARTUP_CONFIG.reset(token)


def requested_config():
  snapshot = _STARTUP_CONFIG.get()
  return read_config() if snapshot is None else snapshot


def h020_version(car_fw):
  versions = {bytes(f.fwVersion).split(b"\0", 1)[0] for f in car_fw if f.ecu == "eps"}
  return next(iter(versions)) if len(versions) == 1 and versions <= PTM_VERSIONS else None


def is_h020_ptm(car_fw):
  return h020_version(car_fw) is not None


def build_matches_firmware(car_fw, config):
  build = PTM_BUILDS.get(config.get("ptm_build"))
  return build is not None and h020_version(car_fw) == build["fw_version"].encode()


def configure_h020(cp, candidate, car_fw, config=None):
  """Called after res's legacy modified-EPS tune. Other vehicles/stock firmware keep the original behavior."""
  cfg = requested_config() if config is None else config
  if not cfg.get("enabled") or str(candidate) != "HONDA_CIVIC_BOSCH" or not build_matches_firmware(car_fw, cfg):
    # New firmware requires its matching controller profile. Legacy/stock/unrelated behavior is untouched.
    if h020_version(car_fw) == b"39990-TEA,H02B":
      cp.dashcamOnly = True
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
