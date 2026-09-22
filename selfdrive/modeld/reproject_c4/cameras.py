"""Pair camerad narrow/wide frames by exposure start time, not frame counter."""

from msgq.visionipc import VisionIpcClient
from openpilot.common.swaglog import cloudlog


def recv_pair(narrow: VisionIpcClient, wide: VisionIpcClient):
  """Newest narrow plus the wide exposure taken with it, or None.

  The narrow client conflates. The wide client must not, so its queue can be
  drained until its SOF matches the current narrow exposure. Camera frame IDs
  are not a reliable cross-camera pairing key after resets.
  """
  buf_n = narrow.recv()
  if buf_n is None:
    return None
  while True:
    buf_w = wide.recv()
    if buf_w is None or narrow.timestamp_sof < wide.timestamp_sof + 25_000_000:
      break
  if buf_w is None:
    return None
  if abs(narrow.timestamp_sof - wide.timestamp_sof) > 10_000_000:
    cloudlog.error(
      f"reproject: frames out of sync! narrow {narrow.frame_id} ({narrow.timestamp_sof / 1e9:.5f}), "
      f"wide {wide.frame_id} ({wide.timestamp_sof / 1e9:.5f})"
    )
  return buf_n, buf_w
