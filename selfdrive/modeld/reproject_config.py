"""Internal onroad-session selection for the C3X->virtual-C4 camera path.

There is deliberately no user-facing reprojection switch. The session marker
is latched by manager/modeld when the onroad Chestnut big-model camera path is
selected, survives modeld restarts and temporary Chestnut disconnects, and is
cleared by manager on an onroad/offroad transition or manager restart.
"""

from openpilot.common.params import Params
from openpilot.system.hardware import TICI
from openpilot.system.hardware.usb import chestnut_firmware_ready
from openpilot.starpilot.assets.model_manager import get_model_profile
from openpilot.starpilot.common.model_lab import load_model_lab_config

REPROJECT_SESSION_PARAM = "ReprojectSessionActive"
REPROJECT_CAMERA_SIZE = (1344, 760)


def select_reproject_session(params: Params, chestnut_ready: bool | None = None) -> bool:
  """Select/reuse this session's camera path; do not re-probe the link later."""
  if not TICI:
    return False
  if params.get_bool(REPROJECT_SESSION_PARAM):
    return True

  # Model Laboratory deliberately keeps using camerad's native camera stream.
  # A configured big profile is not the runtime path while Model Laboratory is
  # requested, including when its AMD artifacts later fail and small fallback
  # takes over.
  if load_model_lab_config(params)["enabled"]:
    return False

  big_model_id, _, _ = get_model_profile(params, "big")
  if not big_model_id:
    return False

  if chestnut_ready is None:
    try:
      chestnut_ready = chestnut_firmware_ready()
    except Exception:
      chestnut_ready = False
  if not chestnut_ready:
    return False

  params.put_bool(REPROJECT_SESSION_PARAM, True)
  return True


def reproject_expected(params: Params | None = None) -> bool:
  """Manager/calibrationd view of the already selected session path."""
  return TICI and (params or Params()).get_bool(REPROJECT_SESSION_PARAM)
