"""Bind the H020 startup decision to the exact CarParams bytes card publishes.

No new capnp/Params keys. card writes the record atomically BEFORE publishing CarParams;
controlsd loads it once and never rereads the operator's config during controller selection.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from opendbc.sunnypilot.car.honda.h020_ptm import SUPPORTED_BUILDS, is_h020_ptm

ACTIVATION_PATH = Path("/data/honda_eps_h020_activation.json")


class H020ActivationError(RuntimeError):
  pass


def is_h020(cp):
  return is_h020_ptm(cp.carFw)


def requires_activation(cp):
  # Recognize the port's transport map even if its PID was overwritten or is from an older prototype.
  return (is_h020(cp) and list(cp.lateralParams.torqueBP) == [0, 3840]
          and list(cp.lateralParams.torqueV) == [0, 3840])


def expected_tune(cp):
  if not is_h020(cp) or str(cp.carFingerprint) != "HONDA_CIVIC_BOSCH" or cp.lateralTuning.which() != "pid":
    return False
  p = cp.lateralTuning.pid
  bp = [0., 25 * 0.44704 - 1e-3, 25 * 0.44704, 50 * 0.44704]

  def close(a, b):
    return len(a) == len(b) and all(abs(float(x) - y) < 1e-6 for x, y in zip(a, b, strict=True))

  return (list(cp.lateralParams.torqueBP) == [0, 3840] and list(cp.lateralParams.torqueV) == [0, 3840]
          and close(p.kpBP, bp) and close(p.kiBP, bp)
          and close(p.kpV, [0.018, 0.024, 0.048, 0.060])
          and close(p.kiV, [0.006, 0.008, 0.016, 0.020]) and abs(p.kf) < 1e-12)


def validate_final_params(cp, config, params):
  if not config.get("enabled"):
    return
  if params.get_bool("EnforceTorqueControl") or params.get_bool("NeuralNetworkLateralControl"):
    raise H020ActivationError("H020 activation blocked: turn off EnforceTorqueControl and NeuralNetworkLateralControl; restart offroad")
  if not is_h020(cp):
    raise H020ActivationError("H020 activation blocked: fresh EPS query did not return exact 39990-TEA,H020")
  if str(cp.carFingerprint) != "HONDA_CIVIC_BOSCH" or cp.dashcamOnly or cp.fuzzyFingerprint or str(cp.fingerprintSource) != "fw":
    raise H020ActivationError("H020 activation blocked: need a fresh, exact Civic Bosch firmware fingerprint; do not force a platform")
  if not expected_tune(cp):
    raise H020ActivationError("H020 activation blocked: final PID/map differs from the expected H020 tune after setup_interfaces")


def publish_activation(cp_bytes, config, path=None):
  dest = Path(path or ACTIVATION_PATH)
  dest.parent.mkdir(parents=True, exist_ok=True)
  record = {"version": 1, "cp_sha256": hashlib.sha256(cp_bytes).hexdigest(), "config": config}
  fd, temp = tempfile.mkstemp(prefix=dest.name + ".", dir=str(dest.parent))
  try:
    with os.fdopen(fd, "w") as f:
      json.dump(record, f)
      f.flush()
      os.fsync(f.fileno())
    os.replace(temp, dest)
  finally:
    if os.path.exists(temp):
      os.unlink(temp)


def load_activation(cp, cp_bytes=None, path=None):
  """Return the latched config, or fail visibly for a tuned H020 with no matching startup record."""
  raw = cp.to_bytes() if cp_bytes is None else cp_bytes
  try:
    record = json.loads(Path(path or ACTIVATION_PATH).read_text())
    if not isinstance(record, dict) or record["version"] != 1 or record["cp_sha256"] != hashlib.sha256(raw).hexdigest():
      raise ValueError("CarParams hash mismatch")
    config = record["config"]
    if not isinstance(config, dict):
      raise ValueError("invalid config snapshot")
    if config.get("enabled") and (config.get("enabled") is not True or config.get("ptm_build") not in SUPPORTED_BUILDS
                                  or config.get("calibration_stage") != "provisional"):
      raise ValueError("unrecognized enabled config snapshot")
    if config.get("enabled") and not expected_tune(cp):
      raise H020ActivationError("H020 activation record matches CarParams but its final tune is incompatible")
    if requires_activation(cp) and not config.get("enabled"):
      raise ValueError("H020 tune paired with a disabled activation record")
    return config
  except (OSError, ValueError, KeyError, TypeError) as e:
    if requires_activation(cp):
      raise H020ActivationError(f"H020 tuned CarParams has no valid card activation record: {e}; restart card/controlsd together offroad") from e
    return {"enabled": False}
