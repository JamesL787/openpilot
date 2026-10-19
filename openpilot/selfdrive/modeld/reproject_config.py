"""Onroad-session selection for the comma 3X -> virtual comma 4 camera path (from vfn).

On a comma 3X driving a Chestnut big model, reprojectd turns the 1928x1208 road/wide pair into a virtual 1344x760
comma 4 pair and modeld reads that instead of camerad. With 7.0 uploading whole NV12 frames to the Chestnut for its
warp, that also cuts the per-frame USB upload from about 7.5 MB to 3.2 MB.

There is deliberately no user-facing switch. The session marker is latched when the Chestnut big-model path is
selected, survives modeld restarts and brief Chestnut disconnects, and is cleared on an onroad/offroad transition
or manager restart (its params flags).
"""

from functools import cache

from openpilot.common.hardware import AGNOS, HARDWARE
from openpilot.common.params import Params

REPROJECT_SESSION_PARAM = "ReprojectSessionActive"
REPROJECT_CAMERA_SIZE = (1344, 760)
REPROJECT_DEVICE_TYPES = ("tizi",)   # the 3X; the lens and pair geometry in reproject_c4 are the 3X's
# Personal branch: off. 7.0's catalog compiles Chestnut models with WARP_DEV=QCOM, so the model warp already runs on
# the comma GPU and only the warped model inputs cross USB; the virtual pair would just be a second full-frame QCOM
# warp (and a second resample). It only pays when the model warp runs on the Chestnut, as comma master's does.
REPROJECT_ENABLED = False


@cache
def _device_supported() -> bool:
  if not REPROJECT_ENABLED:
    return False
  try:
    return AGNOS and HARDWARE.get_device_type() in REPROJECT_DEVICE_TYPES
  except Exception:
    return False


def _big_model_selected(chestnut_ready: bool) -> bool:
  if not chestnut_ready:
    return False
  try:
    from openpilot.starpilot.models.manager import resolve_runtime
    selection = resolve_runtime(chestnut_available=True)
  except Exception:
    return False
  return bool(selection.allow_big and selection.big_path is not None)


def select_reproject_session(params: Params, chestnut_ready: bool | None = None) -> bool:
  """Select (and latch) this session's camera path; a later Chestnut drop does not re-probe it."""
  if not _device_supported():
    return False
  if params.get_bool(REPROJECT_SESSION_PARAM):
    return True
  if chestnut_ready is None:
    try:
      from openpilot.selfdrive.modeld.helpers import chestnut_present
      chestnut_ready = chestnut_present()
    except Exception:
      chestnut_ready = False
  if not _big_model_selected(chestnut_ready):
    return False
  params.put_bool(REPROJECT_SESSION_PARAM, True, block=True)
  return True


def reproject_expected(params: Params | None = None) -> bool:
  """Manager/calibrationd view of the already selected session path."""
  return _device_supported() and (params or Params()).get_bool(REPROJECT_SESSION_PARAM)
