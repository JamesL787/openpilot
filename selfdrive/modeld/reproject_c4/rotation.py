"""Persistent per-unit narrow->wide camera rotation for the 3X->C4 stage."""

import numpy as np

from .geometry import POP_ROTATION, rotvec_from_wide_from_device_euler

ROTATION_PARAM = "ReprojectRotation"
# Phase 2 changes the wide-lens intrinsics and feather width. A Phase 1 fit was
# solved under different geometry and must not silently survive this migration.
GEOMETRY_VERSION = 2


def read_rotation() -> dict:
  try:
    from openpilot.common.params import Params
    d = Params().get(ROTATION_PARAM) or {}
    if (d.get("fitted") is True and d.get("geometryVersion") == GEOMETRY_VERSION
        and len(d["rotvec"]) == 3 and np.isfinite(d["rotvec"]).all()):
      return d
  except (AttributeError, KeyError, TypeError, ValueError):
    pass
  return {}


def load_rotation() -> tuple[float, float, float]:
  """Use the fitted rotation, then the persisted model seed, then the fleet median."""
  d = read_rotation()
  if d:
    return tuple(float(v) for v in d["rotvec"])

  try:
    from cereal import log
    from openpilot.common.params import Params
    calibration_params = Params().get("CalibrationParams")
    if calibration_params:
      with log.Event.from_bytes(calibration_params) as msg:
        euler = list(msg.liveCalibration.wideFromDeviceEuler)
      if len(euler) == 3 and np.isfinite(euler).all():
        return rotvec_from_wide_from_device_euler(euler)
  except Exception:
    pass

  return POP_ROTATION


def save_rotation(rotvec, **extra) -> None:
  from openpilot.common.params import Params
  Params().put(ROTATION_PARAM, {
    "rotvec": [float(v) for v in rotvec],
    "geometryVersion": GEOMETRY_VERSION,
    **extra,
  })
