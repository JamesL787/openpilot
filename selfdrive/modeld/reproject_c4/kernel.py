"""QCOM reprojection kernel: gathered C4 wide plus narrow/wide composite."""

import numpy as np
from tinygrad import Tensor, TinyJit

from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
from .geometry import UV_FILL
from .meter import SeamMeter
from .tables import ALPHA_SHIFT, IDX_BITS, INVALID_BIT


class Reprojector:
  def __init__(self, tables, dst_wh, device):
    self.stride, yh, uvh, _ = get_nv12_info(*dst_wh)
    self.dw, self.dh = dst_wh
    self.uv_offset = self.stride * yh
    self.body = self.stride * (yh + uvh)
    assert self.body == 3 * (self.body - self.uv_offset)
    self.device = device
    self.reload(tables)
    self.params_np = SeamMeter.IDENTITY.copy()
    if str(device or "").startswith("QCOM"):
      self.gains = Tensor.from_blob(self.params_np.ctypes.data, self.params_np.shape, dtype="float32", device=device)
      self.host_params = True
    else:
      self.gains = Tensor(self.params_np, device=device).contiguous().realize()
      self.host_params = False
    self.plane = Tensor([0, 0, 1], dtype="uint8", device=device).realize()
    self.idx = Tensor.arange(self.body, dtype="int32").to(device).realize()
    self.dst = None
    self._run = TinyJit(self._both)

  def bind(self, host_wide: np.ndarray, host_narrow: np.ndarray):
    assert host_wide.nbytes == self.body and host_narrow.nbytes == self.body
    assert host_wide.dtype == host_narrow.dtype == np.uint8
    self.dst = (
      Tensor.from_blob(host_wide.ctypes.data, (self.body,), dtype="uint8", device=self.device),
      Tensor.from_blob(host_narrow.ctypes.data, (self.body,), dtype="uint8", device=self.device),
    )
    self._run = TinyJit(self._both)

  def reload(self, tables):
    assert len(tables["wide"]["pw"]) == self.body
    self.t = {
      cam: {k: Tensor(v, device=self.device).realize() for k, v in tables[cam].items()}
      for cam in ("wide", "narrow")
    }

  def _chroma(self):
    return self.plane.reshape(3, 1).expand(3, self.body // 3).reshape(self.body).bool()

  def _wide(self, wide, pw):
    return (pw < INVALID_BIT).where(wide[pw & IDX_BITS], self._chroma().cast("uint8") * UV_FILL)

  def _narrow(self, wide, narrow, gains, pw, pn):
    chroma = self._chroma()
    off = gains[1:3].reshape(1, 2).expand(self.body // 2, 2).reshape(self.body)
    w = wide[pw & IDX_BITS].float()
    centres = [0.5 * (lo + hi) for lo, hi in SeamMeter.BANDS]
    tone = gains[5]
    for i in range(1, len(centres)):
      tone = tone + (gains[5 + i] - gains[4 + i]) * (
        (w - centres[i - 1]) * (1 / (centres[i] - centres[i - 1]))
      ).clip(0, 1)
    x = (self.idx % self.stride).float() * (2.0 / self.dw) - 1
    y = (self.idx // self.stride).float() * (2.0 / self.dh) - 1
    w = chroma.where(
      (w - UV_FILL) * gains[0] + UV_FILL + off,
      w * tone * (1 + gains[3] * x + gains[4] * y),
    ).clip(0, 255)
    w = (pw < INVALID_BIT).where(w, chroma.cast("float32") * UV_FILL)
    a = ((pw >> ALPHA_SHIFT) & 0xff).float() * (1 / 255)
    return a * narrow[pn].float() + (1 - a) * w

  def _both(self, wide, narrow, gains, pw_w, pw_n, pn):
    out_w = self._wide(wide, pw_w)
    out_n = self._narrow(wide, narrow, gains, pw_n, pn).round().cast("uint8")
    if self.dst is not None:
      out_w, out_n = self.dst[0].assign(out_w), self.dst[1].assign(out_n)
    return out_w.realize(), out_n.realize()

  def __call__(self, wide, narrow, match=None):
    self.params_np[:] = SeamMeter.IDENTITY if match is None else match
    if not self.host_params:
      self.gains.assign(Tensor(self.params_np, device=self.device)).realize()
    return self._run(wide, narrow, self.gains, self.t["wide"]["pw"], self.t["narrow"]["pw"], self.t["narrow"]["pn"])
