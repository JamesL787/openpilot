"""Reproject comma 3X cameras into comma 4 camera geometry on QCOM before an untouched comma 4 model.

Adapted for VFN's camera naming (fcam/ecam instead of narrow_road/wide_road).
Upstream source: AmyJeanes/openpilot-upstream:tizi-to-mici, commit 34a1dae74ebfaa88c28f89508cb2a04254be8878.
"""
import os

import numpy as np
from tinygrad import Tensor, TinyJit

from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

X3_WIDE = dict(f=596.669, cx=957.566, cy=581.537, k=(-0.014942, -0.0023814, -0.00064424), tc=1.51354)
X3_NARROW = dict(f=2600.85, cx=964.0, cy=604.0, k1=-0.36400)
C4_WIDE = dict(f=442.555, cx=672.380, cy=378.718, k=(0.0089611, 0.029156, -0.015066), tc=1.39626)
R_NARROW_FROM_WIDE = (-0.0167946, 0.0022473, -0.0011422)
ZMIN = np.cos(np.radians(88.0))
FEATHER_PX = 24
UV_FILL = 128
EXPOSURE_GAIN_A, EXPOSURE_GAIN_P = 0.868, 0.708


def exposure_gain(narrow_exposure, wide_exposure, lo=0.25, hi=4.0):
  """Gain applied to the 3X wide surround so it matches the narrow inset."""
  if not (narrow_exposure > 0 and wide_exposure > 0):
    return 1.0
  return float(np.clip(EXPOSURE_GAIN_A * (narrow_exposure / wide_exposure) ** EXPOSURE_GAIN_P, lo, hi))


def _theta_d(th, L):
  k, tc = L["k"], L["tc"]
  p = lambda t: t * (1 + k[0] * t**2 + k[1] * t**4 + k[2] * t**6)
  dp = lambda t: 1 + 3 * k[0] * t**2 + 5 * k[1] * t**4 + 7 * k[2] * t**6
  return np.where(th <= tc, p(th), p(tc) + dp(tc) * (th - tc))


def _dtheta_d(th, L):
  k = L["k"]
  t = np.minimum(th, L["tc"])
  return 1 + 3 * k[0] * t**2 + 5 * k[1] * t**4 + 7 * k[2] * t**6


def unproject_fisheye(px, L):
  dx, dy = px[..., 0] - L["cx"], px[..., 1] - L["cy"]
  r = np.hypot(dx, dy)
  td = r / L["f"]
  th = td.copy()
  for _ in range(10):
    th = th - (_theta_d(th, L) - td) / _dtheta_d(th, L)
  s = np.sin(th)
  rr = np.where(r > 0, r, 1)
  return np.stack([s * dx / rr, s * dy / rr, np.cos(th)], -1)


def unproject_pinhole(px, f, cx, cy):
  d = np.stack([(px[..., 0] - cx) / f, (px[..., 1] - cy) / f, np.ones(px.shape[:-1])], -1)
  return d / np.linalg.norm(d, axis=-1, keepdims=True)


def project_fisheye(rays, L):
  rho = np.hypot(rays[..., 0], rays[..., 1])
  th = np.arctan2(rho, rays[..., 2])
  r = L["f"] * _theta_d(th, L)
  rr = np.where(rho > 0, rho, 1)
  return np.stack([L["cx"] + r * rays[..., 0] / rr, L["cy"] + r * rays[..., 1] / rr], -1)


def project_pinhole_k1(rays, L):
  x, y = rays[..., 0] / rays[..., 2], rays[..., 1] / rays[..., 2]
  s = 1 + L["k1"] * (x * x + y * y)
  return np.stack([L["cx"] + L["f"] * x * s, L["cy"] + L["f"] * y * s], -1)


def rotvec_to_matrix(v):
  v = np.asarray(v, dtype=np.float64)
  a = np.linalg.norm(v)
  if a == 0:
    return np.eye(3)
  k = v / a
  K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
  return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def sample_coords(out_cam, dst_w, dst_h, scale=1.0):
  """Float 3X wide/narrow coordinates for every comma 4 output pixel."""
  xs, ys = np.meshgrid((np.arange(dst_w) + 0.5) / scale, (np.arange(dst_h) + 0.5) / scale)
  px = np.stack([xs, ys], -1)
  if out_cam == "wide":
    rays = unproject_fisheye(px, C4_WIDE)
  else:
    Kn = DEVICE_CAMERAS[("mici", "os04c10")].fcam.intrinsics
    rays = unproject_pinhole(px, Kn[0, 0], Kn[0, 2], Kn[1, 2])
  rays_w = rays @ rotvec_to_matrix(R_NARROW_FROM_WIDE).T
  mw = project_fisheye(rays_w, X3_WIDE) * scale
  mw[rays_w[..., 2] < ZMIN] = -1
  mn = project_pinhole_k1(rays, X3_NARROW) * scale
  mn[rays[..., 2] <= 0] = -1
  return mw, mn


def _nv12_index(xy, src_w, src_h, stride, uv_offset, chroma):
  """Nearest-neighbour byte index into a source NV12 buffer."""
  xy = np.clip(np.nan_to_num(xy, nan=-1.0), -1e6, 1e6)
  x = np.round(xy[..., 0] - 0.5).astype(np.int64)
  y = np.round(xy[..., 1] - 0.5).astype(np.int64)
  w, h = (src_w // 2, src_h // 2) if chroma else (src_w, src_h)
  valid = (x >= 0) & (x < w) & (y >= 0) & (y < h)
  x = np.clip(x, 0, w - 1)
  y = np.clip(y, 0, h - 1)
  idx = (uv_offset + y * stride + 2 * x) if chroma else (y * stride + x)
  return idx, valid


IDX_BITS, ALPHA_SHIFT, INVALID_BIT = 0x3fffff, 22, 1 << 30


def build_tables(src_wh, dst_wh):
  sw, sh = src_wh
  dw, dh = dst_wh
  s_stride, s_yh, s_uvh, _ = get_nv12_info(sw, sh)
  s_uv = s_stride * s_yh
  assert s_stride * (s_yh + s_uvh) <= IDX_BITS + 1
  d_stride, d_yh, d_uvh, d_size = get_nv12_info(dw, dh)
  d_uv = d_stride * d_yh
  n_body = d_stride * (d_yh + d_uvh)
  out = {}
  for cam in ("wide", "narrow"):
    idx_w = np.zeros(n_body, np.int64)
    idx_n = np.zeros(n_body, np.int64)
    val_w = np.zeros(n_body, bool)
    val_n = np.zeros(n_body, bool)
    dist = np.zeros(n_body, np.float32)
    for chroma in (False, True):
      mw, mn = sample_coords(cam, dw // 2 if chroma else dw, dh // 2 if chroma else dh, 0.5 if chroma else 1.0)
      iw, vw = _nv12_index(mw, sw, sh, s_stride, s_uv, chroma)
      inn, vn = _nv12_index(mn, sw, sh, s_stride, s_uv, chroma)
      sc = (0.5 if chroma else 1.0) * (X3_NARROW["f"] / DEVICE_CAMERAS[("mici", "os04c10")].fcam.intrinsics[0, 0])
      d = np.minimum(
        np.minimum(mn[..., 0], sw * (0.5 if chroma else 1) - mn[..., 0]),
        np.minimum(mn[..., 1], sh * (0.5 if chroma else 1) - mn[..., 1]),
      ) / sc
      if chroma:
        rows = np.arange(dh // 2)[:, None]
        cols = np.arange(dw // 2)[None, :]
        for plane in (0, 1):
          flat = d_uv + rows * d_stride + 2 * cols + plane
          idx_w[flat] = iw + plane
          idx_n[flat] = inn + plane
          val_w[flat] = vw
          val_n[flat] = vn
          dist[flat] = d
      else:
        flat = np.arange(dh)[:, None] * d_stride + np.arange(dw)[None, :]
        idx_w[flat] = iw
        idx_n[flat] = inn
        val_w[flat] = vw
        val_n[flat] = vn
        dist[flat] = d
    alpha = np.round(np.clip(dist / FEATHER_PX, 0, 1) * val_n * 255).astype(np.int64)
    pw = idx_w | (alpha << ALPHA_SHIFT) | (~val_w * INVALID_BIT)
    out[cam] = dict(pw=pw.astype(np.int32), size=d_size, body=n_body, uv_offset=d_uv)
    if cam == "narrow":
      out[cam]["pn"] = idx_n.astype(np.int32)
  return out


TABLE_VERSION = 2


def load_tables(src_wh, dst_wh, cache_dir=None):
  """Cache expensive lookup-table construction on disk."""
  if cache_dir is None:
    return build_tables(src_wh, dst_wh)
  os.makedirs(cache_dir, exist_ok=True)
  p = os.path.join(cache_dir, f"reproject_c4_v{TABLE_VERSION}_{src_wh[0]}x{src_wh[1]}_{dst_wh[0]}x{dst_wh[1]}.npz")
  if os.path.exists(p):
    z = np.load(p)
    tables = {"wide": {}, "narrow": {}}
    for key in z.files:
      cam, k = key.split("_", 1)
      tables[cam][k] = z[key] if z[key].ndim else int(z[key])
    return tables
  tables = build_tables(src_wh, dst_wh)
  np.savez_compressed(p + ".tmp.npz", **{f"{cam}_{k}": v for cam, tab in tables.items() for k, v in tab.items()})
  os.replace(p + ".tmp.npz", p)
  return tables


class Reprojector:
  """Holds lookup tables on the target device and runs the gathers."""

  def __init__(self, src_wh=(1928, 1208), dst_wh=(1344, 760), device=None, cache_dir=None):
    tables = load_tables(src_wh, dst_wh, cache_dir)
    self.size = tables["wide"]["size"]
    self.body = tables["wide"]["body"]
    self.uv_offset = tables["wide"]["uv_offset"]
    self.t = {
      cam: {k: Tensor(v, device=device).realize() for k, v in tab.items() if isinstance(v, np.ndarray)}
      for cam, tab in tables.items()
    }
    self.gains_np = np.ones(2, np.float32) if str(device or "").startswith("QCOM") else None
    if self.gains_np is not None:
      self.gains = Tensor.from_blob(self.gains_np.ctypes.data, (2,), dtype="float32", device=device)
    else:
      self.gains = Tensor(np.ones(2, np.float32), device=device).contiguous().realize()
    assert self.body == 3 * (self.body - self.uv_offset)
    self.plane = Tensor([0, 0, 1], dtype="uint8", device=device).realize()
    self.dst = None
    self._run = TinyJit(self._both)

  def bind(self, host_wide: np.ndarray, host_narrow: np.ndarray):
    """Write results directly into modeld's host-side packed frame slots."""
    assert host_wide.nbytes == self.body and host_narrow.nbytes == self.body
    assert host_wide.dtype == host_narrow.dtype == np.uint8
    dev = self.gains.device
    self.dst = (
      Tensor.from_blob(host_wide.ctypes.data, (self.body,), dtype="uint8", device=dev),
      Tensor.from_blob(host_narrow.ctypes.data, (self.body,), dtype="uint8", device=dev),
    )
    self._run = TinyJit(self._both)

  def _chroma(self):
    return self.plane.reshape(3, 1).expand(3, self.body // 3).reshape(self.body).bool()

  def _wide(self, wide):
    pw = self.t["wide"]["pw"]
    return (pw < INVALID_BIT).where(wide[pw & IDX_BITS], self._chroma().cast("uint8") * UV_FILL)

  def _narrow(self, wide, narrow, gain_y, gain_c):
    t = self.t["narrow"]
    pw = t["pw"]
    chroma = self._chroma()
    w = wide[pw & IDX_BITS].float()
    w = chroma.where((w - UV_FILL) * gain_c + UV_FILL, w * gain_y).clip(0, 255)
    w = (pw < INVALID_BIT).where(w, chroma.cast("float32") * UV_FILL)
    a = ((pw >> ALPHA_SHIFT) & 0xff).float() * (1 / 255)
    return a * narrow[t["pn"]].float() + (1 - a) * w

  def _both(self, wide, narrow, gains):
    out_w = self._wide(wide)
    out_n = self._narrow(wide, narrow, gains[0], gains[1]).round().cast("uint8")
    if self.dst is not None:
      out_w, out_n = self.dst[0].assign(out_w), self.dst[1].assign(out_n)
    return out_w.realize(), out_n.realize()

  def __call__(self, wide, narrow, gain_y=1.0, gain_c=1.0):
    if self.gains_np is not None:
      self.gains_np[:] = (gain_y, gain_c)
    else:
      self.gains.assign(Tensor(np.array([gain_y, gain_c], np.float32), device=self.gains.device)).realize()
    return self._run(wide, narrow, self.gains)
