"""Bind the H020 startup decision to the exact CarParams bytes card publishes.

No new capnp/Params keys. card writes the record atomically BEFORE publishing CarParams;
controlsd loads it once and never rereads the operator's config during controller selection.
"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from opendbc.car.carlog import carlog
from opendbc.sunnypilot.car.honda.h020_ptm import PTM_VERSIONS, SUPPORTED_BUILDS, build_matches_firmware, is_h020_ptm

ACTIVATION_PATH = Path("/data/honda_eps_h020_activation.json")


class H020ActivationError(RuntimeError):
  pass


def is_h020(cp):
  return is_h020_ptm(cp.carFw)


def has_h020_response(cp):
  return any(f.ecu == "eps" and bytes(f.fwVersion).split(b"\0", 1)[0] in PTM_VERSIONS for f in cp.carFw)


def requires_activation(cp):
  # Recognize the port's transport map even if its PID was overwritten or is from an older prototype.
  return is_h020(cp) and list(cp.lateralParams.torqueBP) == [0, 3840] and list(cp.lateralParams.torqueV) == [0, 3840]


def expected_tune(cp):
  if not is_h020(cp) or str(cp.carFingerprint) != "HONDA_CIVIC_BOSCH" or cp.lateralTuning.which() != "pid":
    return False
  p = cp.lateralTuning.pid
  bp = [0.0, 25 * 0.44704 - 1e-3, 25 * 0.44704, 50 * 0.44704]

  def close(a, b):
    return len(a) == len(b) and all(abs(float(x) - y) < 1e-6 for x, y in zip(a, b, strict=True))

  return (
    list(cp.lateralParams.torqueBP) == [0, 3840]
    and list(cp.lateralParams.torqueV) == [0, 3840]
    and close(p.kpBP, bp)
    and close(p.kiBP, bp)
    and close(p.kpV, [0.018, 0.024, 0.048, 0.060])
    and close(p.kiV, [0.006, 0.008, 0.016, 0.020])
    and abs(p.kf) < 1e-12
  )


def validate_final_params(cp, config, params):
  if not config.get("enabled"):
    return config
  if not is_h020(cp):
    if has_h020_response(cp):
      raise H020ActivationError("H020 activation blocked: conflicting EPS responses include H020 PTM; cannot use an ordinary fallback")
    carlog.error("H020 config enabled but exact H020 PTM EPS is absent; ignoring H020 config and using the original res path")
    return {"enabled": False}
  if not build_matches_firmware(cp.carFw, config):
    raise H020ActivationError("H020 activation blocked: declared PTM build does not match the queried EPS firmware family (H020 versus H02B)")
  if params.get_bool("EnforceTorqueControl") or params.get_bool("NeuralNetworkLateralControl"):
    raise H020ActivationError("H020 activation blocked: turn off EnforceTorqueControl and NeuralNetworkLateralControl; restart offroad")
  if str(cp.carFingerprint) != "HONDA_CIVIC_BOSCH" or cp.dashcamOnly or cp.fuzzyFingerprint or str(cp.fingerprintSource) != "fw":
    from openpilot.selfdrive.controls.lib.honda_eps_h020_fingerprint import firmware_match_report, match_summary

    detail = match_summary(firmware_match_report(cp))
    raise H020ActivationError("H020 activation blocked: need a fresh, exact Civic Bosch firmware fingerprint; do not force a platform; " + detail)
  if not expected_tune(cp):
    raise H020ActivationError("H020 activation blocked: final PID/map differs from the expected H020 tune after setup_interfaces")
  return config


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


def load_activation(cp, cp_bytes, path=None):
  """Return the latched config, or fail visibly for a tuned H020 with no matching startup record."""
  # A capnp copy may serialize differently, and serializing a previously written builder warns.
  # The record binds the ORIGINAL published bytes, so require them rather than reserializing CP.
  raw = cp_bytes
  try:
    record = json.loads(Path(path or ACTIVATION_PATH).read_text())
    if not isinstance(record, dict) or record["version"] != 1 or record["cp_sha256"] != hashlib.sha256(raw).hexdigest():
      raise ValueError("CarParams hash mismatch")
    config = record["config"]
    if not isinstance(config, dict):
      raise ValueError("invalid config snapshot")
    if config.get("enabled") and (
      config.get("enabled") is not True or config.get("ptm_build") not in SUPPORTED_BUILDS or config.get("calibration_stage") != "provisional"
    ):
      raise ValueError("unrecognized enabled config snapshot")
    if config.get("enabled") and not build_matches_firmware(cp.carFw, config):
      raise H020ActivationError("H020 activation record build does not match the queried EPS firmware family")
    if config.get("enabled") and not expected_tune(cp):
      raise H020ActivationError("H020 activation record matches CarParams but its final tune is incompatible")
    if requires_activation(cp) and not config.get("enabled"):
      raise ValueError("H020 tune paired with a disabled activation record")
    return config
  except (OSError, ValueError, KeyError, TypeError) as e:
    if requires_activation(cp):
      raise H020ActivationError(f"H020 tuned CarParams has no valid card activation record: {e}; restart card/controlsd together offroad") from e
    return {"enabled": False}


class H020RuntimeGuard:
  """One disk check/second only for an active H020 port; any mismatch latches until process restart."""

  def __init__(self, cp, cp_bytes, config, params, log_error, clock=None):
    self.cp = cp
    self.raw = cp_bytes
    self.config = dict(config)
    self.params = params
    self.log_error = log_error
    self.clock = clock or time.monotonic
    self.next_check = 0.0
    self.next_log = 0.0
    self.failure = None

  def check(self):
    now = self.clock()
    if self.failure is None and now >= self.next_check:
      self.next_check = now + 1.0
      try:
        if self.params.get("CarParams") != self.raw:
          raise H020ActivationError("published CarParams changed or disappeared")
        if load_activation(self.cp, self.raw) != self.config:
          raise H020ActivationError("activation snapshot changed")
      except (OSError, H020ActivationError) as e:
        self.failure = str(e)
    if self.failure is not None and now >= self.next_log:
      self.log_error(f"H020 lateral output blocked: {self.failure}; restart controlsd offroad; output remains zero until restart")
      self.next_log = now + 5.0
    return self.failure is None
