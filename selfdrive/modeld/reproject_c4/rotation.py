"""Persistent per-unit narrow->wide camera rotation for the 3X->C4 stage."""

import numpy as np

from .geometry import R_NARROW_FROM_WIDE

ROTATION_PARAM = "ReprojectRotation"


def read_rotation() -> dict:
  try:
    from openpilot.common.params import Params
    d = Params().get(ROTATION_PARAM) or {}
    # Only a completed camera fit is authoritative across restarts. Partial or
    # legacy estimates must never replace VFN's known-good board/reference seed.
    if d.get("fitted") is True and len(d["rotvec"]) == 3 and np.isfinite(d["rotvec"]).all():
      return d
  except (AttributeError, KeyError, TypeError, ValueError):
    pass
  return {}


def load_rotation() -> tuple[float, float, float]:
  d = read_rotation()
  if d:
    return tuple(float(v) for v in d["rotvec"])
  # Keep VFN's already-proven direct-fit seed. Do not derive physical camera-pair
  # geometry from model-produced road calibration.
  return R_NARROW_FROM_WIDE


def save_rotation(rotvec, **extra) -> None:
  from openpilot.common.params import Params
  Params().put(ROTATION_PARAM, {"rotvec": [float(v) for v in rotvec], **extra}, block=True)
