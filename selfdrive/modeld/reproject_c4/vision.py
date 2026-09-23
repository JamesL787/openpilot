"""VisionIPC storage helpers for virtual camera frames."""

import numpy as np

from openpilot.system.camerad.cameras.nv12_info import get_nv12_info


def allocate_virtual_camera_frames(resolution: tuple[int, int]) -> tuple[np.ndarray, int, int, int]:
  """Allocate Venus-sized VisionIPC buffers and return their active NV12 body layout.

  The image body is stride * (Y height + UV height). The remaining Venus
  allocation is guard/kernel padding and must stay zero; Qualcomm consumers
  map the complete allocation even though image kernels only read the body.
  """
  stride, y_height, uv_height, allocation_size = get_nv12_info(*resolution)
  body_size = stride * (y_height + uv_height)
  if allocation_size < body_size:
    raise ValueError(f"NV12 allocation ({allocation_size}) is smaller than its image body ({body_size})")

  frames = np.zeros((2, allocation_size), dtype=np.uint8)
  return frames, body_size, stride, stride * y_height
