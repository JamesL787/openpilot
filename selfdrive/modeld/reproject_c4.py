"""Reproject comma 3X cameras into comma 4 camera geometry on QCOM before an untouched comma 4 model.

VFN port checkpoint:
  VFN base: bc92128375bb36454cb8f00b474f6e35cf26fd9e
  Amy source checkpoint: 6a13f4c413e810ab776afdb703b02878aff7383f

This intentionally takes Amy's current photometric/seam matching and JIT-table-input
infrastructure while PRESERVING VFN's currently-working geometry:
  * VFN fcam/ecam camera naming
  * board/reference X3 wide lens
  * R_NARROW_FROM_WIDE unchanged
  * 24 px feather unchanged
  * inset softening not enabled

Do not silently switch this file to Amy's population wide lens, 50 px feather, or active
rotation refinement. Those are separate experiments.
"""
import hashlib
import json
import os

import numpy as np
from tinygrad import Tensor, TinyJit

from openpilot.common.transformations.camera import DEVICE_CAMERAS
from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

X3_WIDE = dict(f=596.669, cx=957.566, cy=581.537, k=(-0.014942, -0.0023814, -0.00064424), tc=1.51354)
X3_NARROW = dict(f=2600.85, cx=964.0, cy=604.0, k1=-0.36400)
C4_WIDE = dict(f=442.555, cx=672.380, cy=378.718, k=(0.0089611, 0.029156, -0.015066), tc=1.39626)
R_NARROW_FROM_WIDE = (-0.0167946, 0.0022473, -0.0011422)

DEFAULT_CALIB = dict(wide=X3_WIDE, narrow=X3_NARROW, R=R_NARROW_FROM_WIDE)

ZMIN = np.cos(np.radians(88.0))
FEATHER_PX = 24
UV_FILL = 128
EXPOSURE_GAIN_A, EXPOSURE_GAIN_P = 0.868, 0.708


def calib_from_rotvec(rotvec):
  """Build a calibration using VFN's known-good board/reference wide lens.

  Do NOT substitute Amy's fleet-population lens here until it is tested as a
  separate geometry experiment.
  """
  return dict(wide=X3_WIDE, narrow=X3_NARROW, R=tuple(float(v) for v in rotvec))


def exposure_gain(narrow_exposure, wide_exposure, lo=0.25, hi=4.0):
  """Encoded-domain feed-forward gain from camera exposure metadata."""
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


def matrix_to_rotvec(M):
  a = np.arccos(np.clip((np.trace(M) - 1) / 2, -1, 1))
  if a < 1e-9:
    return np.zeros(3)
  return a / (2 * np.sin(a)) * np.array([M[2, 1] - M[1, 2], M[0, 2] - M[2, 0], M[1, 0] - M[0, 1]])


def rotvec_from_wide_from_device_euler(euler):
  """Convert model device-frame (roll,pitch,yaw) residual to camera-axis rotvec."""
  r, p, y = euler
  return (float(p), float(y), float(r))


def sample_coords(out_cam, dst_w, dst_h, scale=1.0, calib=None):
  """Float 3X wide/narrow coordinates for every comma 4 output pixel."""
  calib = calib or DEFAULT_CALIB
  xs, ys = np.meshgrid((np.arange(dst_w) + 0.5) / scale, (np.arange(dst_h) + 0.5) / scale)
  px = np.stack([xs, ys], -1)
  if out_cam == "wide":
    rays = unproject_fisheye(px, C4_WIDE)
  else:
    Kn = DEVICE_CAMERAS[("mici", "os04c10")].fcam.intrinsics
    rays = unproject_pinhole(px, Kn[0, 0], Kn[0, 2], Kn[1, 2])
  rays_w = rays @ rotvec_to_matrix(calib["R"]).T
  mw = project_fisheye(rays_w, calib["wide"]) * scale
  mw[rays_w[..., 2] < ZMIN] = -1
  mn = project_pinhole_k1(rays, calib["narrow"]) * scale
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


def build_tables(src_wh, dst_wh, calib=None, feather=FEATHER_PX):
  sw, sh = src_wh
  dw, dh = dst_wh
  calib = calib or DEFAULT_CALIB
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
      mw, mn = sample_coords(cam, dw // 2 if chroma else dw, dh // 2 if chroma else dh, 0.5 if chroma else 1.0, calib)
      iw, vw = _nv12_index(mw, sw, sh, s_stride, s_uv, chroma)
      inn, vn = _nv12_index(mn, sw, sh, s_stride, s_uv, chroma)
      sc = (0.5 if chroma else 1.0) * (calib["narrow"]["f"] / DEVICE_CAMERAS[("mici", "os04c10")].fcam.intrinsics[0, 0])
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

    alpha = np.round(np.clip(dist / feather, 0, 1) * val_n * 255).astype(np.int64)
    pw = idx_w | (alpha << ALPHA_SHIFT) | (~val_w * INVALID_BIT)
    out[cam] = dict(pw=pw.astype(np.int32), size=d_size, body=n_body, uv_offset=d_uv)
    if cam == "narrow":
      # Keep the narrow sample unsoftened. Amy's optional blend-zone softening
      # intentionally destroys some narrow detail and remains a separate A/B.
      out[cam]["pn"] = idx_n.astype(np.int32)
  return out


TABLE_VERSION = 3


def calib_tag(calib, feather=FEATHER_PX):
  tag = "" if calib is None else "_" + hashlib.sha1(json.dumps(calib, sort_keys=True, default=float).encode()).hexdigest()[:10]
  return tag + ("" if feather == FEATHER_PX else f"_f{feather:g}")


def load_tables(src_wh, dst_wh, cache_dir=None, calib=None, feather=FEATHER_PX):
  """Cache expensive lookup-table construction on disk."""
  if cache_dir is None:
    return build_tables(src_wh, dst_wh, calib, feather)
  os.makedirs(cache_dir, exist_ok=True)
  p = os.path.join(
    cache_dir,
    f"reproject_c4_v{TABLE_VERSION}_{src_wh[0]}x{src_wh[1]}_{dst_wh[0]}x{dst_wh[1]}{calib_tag(calib, feather)}.npz",
  )
  if os.path.exists(p):
    z = np.load(p)
    tables = {"wide": {}, "narrow": {}}
    for key in z.files:
      cam, k = key.split("_", 1)
      tables[cam][k] = z[key] if z[key].ndim else int(z[key])
    return tables
  tables = build_tables(src_wh, dst_wh, calib, feather)
  np.savez_compressed(p + ".tmp.npz", **{f"{cam}_{k}": v for cam, tab in tables.items() for k, v in tab.items()})
  os.replace(p + ".tmp.npz", p)
  return tables


class SeamMeter:
  """Live photometric match for the narrow-inset/wide-surround seam.

  Current Amy design, adapted to VFN:
    * 2048 luma pairs
    * exposure-model feed-forward
    * U/V offsets
    * four brightness bands
    * x/y lens-shading gradient
    * robust one-pass reweighting
    * persistent bad-cell rejection
    * 6x6 normal-equation solve instead of general lstsq
  """
  BANDS = ((16, 50), (50, 100), (100, 160), (160, 235))

  def __init__(self, src_wh=(1928, 1208), dst_wh=(1344, 760), calib=None,
               n_pairs=2048, ring=(30.0, 130.0), alpha=0.3, every=2, feedforward=True):
    sw, sh = src_wh
    dw, dh = dst_wh
    calib = calib or DEFAULT_CALIB
    s_stride, s_yh, _, _ = get_nv12_info(sw, sh)
    s_uv = s_stride * s_yh
    sc = calib["narrow"]["f"] / DEVICE_CAMERAS[("mici", "os04c10")].fcam.intrinsics[0, 0]

    mw, mn = sample_coords("narrow", dw, dh, 1.0, calib)
    dist = np.minimum(np.minimum(mn[..., 0], sw - mn[..., 0]), np.minimum(mn[..., 1], sh - mn[..., 1])) / sc
    iw, vw = _nv12_index(mw, sw, sh, s_stride, s_uv, False)
    inn, vn = _nv12_index(mn, sw, sh, s_stride, s_uv, False)
    in_ring = vw & vn & (dist > ring[0]) & (dist < ring[1])
    sel = np.flatnonzero(in_ring)[::max(1, int(in_ring.sum()) // n_pairs)][:n_pairs]

    self.y_w = iw.ravel()[sel]
    self.y_n = inn.ravel()[sel]
    self.pos = np.stack([
      (sel % dw + 0.5) / dw * 2 - 1,
      (sel // dw + 0.5) / dh * 2 - 1,
    ], 1).astype(np.float32)

    self.cell = (np.floor((self.pos + 1) / 2 * [32, 18])).astype(int)
    self.cell = self.cell[:, 0] * 18 + self.cell[:, 1]
    self.cell_bad = np.zeros(32 * 18, np.float32)
    self.CELL_ALPHA = 0.02
    self.CELL_LIMIT = 0.2

    mw2, mn2 = sample_coords("narrow", dw // 2, dh // 2, 0.5, calib)
    iw2, vw2 = _nv12_index(mw2, sw, sh, s_stride, s_uv, True)
    inn2, vn2 = _nv12_index(mn2, sw, sh, s_stride, s_uv, True)
    in_ring2 = in_ring[::2, ::2] & vw2 & vn2
    sel2 = np.flatnonzero(in_ring2)[::max(1, int(in_ring2.sum()) // (n_pairs // 2))][:n_pairs // 2]
    self.uv_w = iw2.ravel()[sel2]
    self.uv_n = inn2.ravel()[sel2]

    self.alpha = alpha
    self.every = every
    self.n_calls = 0
    self.moving = False
    self.feedforward = feedforward
    self.state = None

  def measure(self, wide, narrow):
    yw = wide[self.y_w].astype(np.float32)
    yn = narrow[self.y_n].astype(np.float32)
    good = (yw > 16) & (yw < 235) & (yn > 16) & (yn < 235)
    if good.sum() < 256:
      return None

    yw = yw[good]
    yn = yn[good]
    pos = self.pos[good]
    ratio = yn / yw
    gy = float(np.median(ratio))

    band = np.searchsorted([hi for _, hi in self.BANDS[:-1]], yw)
    A = np.zeros((len(yw), len(self.BANDS) + 2), np.float32)
    A[np.arange(len(yw)), band] = 1
    A[:, -2:] = pos
    lr = np.log(np.clip(ratio, 0.25, 4.0))

    cells = self.cell[good]
    w = (self.cell_bad[cells] < self.CELL_LIMIT).astype(np.float32)
    if w.sum() < 256:
      w[:] = 1

    def solve(wt):
      Aw = A * wt[:, None]
      return np.linalg.solve(
        A.T @ Aw + 1e-3 * np.eye(A.shape[1], dtype=np.float32),
        Aw.T @ lr,
      )

    c = solve(w)
    res = lr - A @ c
    wr = w * np.clip(1 - (res / 0.3) ** 2, 0, 1) ** 2
    if wr.sum() >= 256:
      c = solve(wr)

    n = np.bincount(cells, minlength=len(self.cell_bad))
    bad = np.bincount(cells, weights=np.abs(lr - A @ c), minlength=len(self.cell_bad))
    seen = n > 0
    self.cell_bad[seen] += self.CELL_ALPHA * (bad[seen] / n[seen] - self.cell_bad[seen])

    counts = np.bincount(band, minlength=len(self.BANDS))
    bands = [float(np.exp(c[i])) if counts[i] >= 100 else gy for i in range(len(self.BANDS))]
    gx = float(np.clip(c[-2], -0.5, 0.5))
    gyp = float(np.clip(c[-1], -0.5, 0.5))

    uw = wide[self.uv_w].astype(np.float32)
    un = narrow[self.uv_n].astype(np.float32)
    vw = wide[self.uv_w + 1].astype(np.float32)
    vn = narrow[self.uv_n + 1].astype(np.float32)
    du = float(np.median(un - UV_FILL - gy * (uw - UV_FILL)))
    dv = float(np.median(vn - UV_FILL - gy * (vw - UV_FILL)))

    return np.array([gy, du, dv, gx, gyp, *bands], np.float32)

  def update(self, wide, narrow, model_gain=1.0):
    self.n_calls += 1
    if self.state is None or self.moving or self.n_calls % self.every == 0:
      m = self.measure(wide, narrow)
      target = m if m is not None else np.array(
        [model_gain, 0, 0, 0, 0] + [model_gain] * len(self.BANDS),
        np.float32,
      )
      if self.feedforward:
        target = target.copy()
        target[0] /= model_gain
        target[5:] /= model_gain

      if self.state is None:
        self.state = target
      else:
        jump = abs(float(target[0] - self.state[0])) / max(float(self.state[0]), 0.1)
        self.state += min(self.alpha + 3 * jump, 0.9) * (target - self.state)
        self.moving = jump > 0.03

    s = self.state.copy()
    if self.feedforward:
      s[0] *= model_gain
      s[5:] *= model_gain

    return dict(
      gain_y=float(s[0]),
      gain_c=float(s[0]),
      u_off=float(s[1]),
      v_off=float(s[2]),
      gx=float(s[3]),
      gy=float(s[4]),
      bands=[float(v) for v in s[5:]],
    )


class Reprojector:
  """Holds lookup tables on the target device and runs the gathers."""

  def __init__(self, src_wh=(1928, 1208), dst_wh=(1344, 760), device=None,
               cache_dir=None, calib=None, feather=FEATHER_PX):
    tables = load_tables(src_wh, dst_wh, cache_dir, calib, feather)
    self.size = tables["wide"]["size"]
    self.body = tables["wide"]["body"]
    self.uv_offset = tables["wide"]["uv_offset"]
    self.device = device
    self.t = {
      cam: {k: Tensor(v, device=device).realize() for k, v in tab.items() if isinstance(v, np.ndarray)}
      for cam, tab in tables.items()
    }

    self.params_np = np.zeros(12, np.float32)
    self.params_np[0] = 1
    self.params_np[5:9] = 1
    if str(device or "").startswith("QCOM"):
      self.gains = Tensor.from_blob(self.params_np.ctypes.data, (12,), dtype="float32", device=device)
      self.host_params = True
    else:
      self.gains = Tensor(self.params_np, device=device).contiguous().realize()
      self.host_params = False

    assert self.body == 3 * (self.body - self.uv_offset)
    self.plane = Tensor([0, 0, 1], dtype="uint8", device=device).realize()
    d_stride = get_nv12_info(*dst_wh)[0]
    self.stride = d_stride
    self.dw, self.dh = dst_wh
    self.idx = Tensor.arange(self.body, dtype="int32").to(device).realize()
    self.dst = None
    self._run = TinyJit(self._both)

  def bind(self, host_wide: np.ndarray, host_narrow: np.ndarray):
    assert host_wide.nbytes == self.body and host_narrow.nbytes == self.body
    assert host_wide.dtype == host_narrow.dtype == np.uint8
    dev = self.gains.device
    self.dst = (
      Tensor.from_blob(host_wide.ctypes.data, (self.body,), dtype="uint8", device=dev),
      Tensor.from_blob(host_narrow.ctypes.data, (self.body,), dtype="uint8", device=dev),
    )
    self._run = TinyJit(self._both)

  def reload(self, tables):
    """Swap table tensors without changing/re-capturing the JIT graph.

    The table tensors are explicit TinyJit inputs. This ports the important
    6a13f4c4 infrastructure, but VFN does not activate live geometry refinement
    in this patch series.
    """
    assert tables["wide"]["body"] == self.body
    assert tables["wide"]["uv_offset"] == self.uv_offset
    self.t = {
      cam: {k: Tensor(v, device=self.device).realize() for k, v in tab.items() if isinstance(v, np.ndarray)}
      for cam, tab in tables.items()
    }

  def _chroma(self):
    return self.plane.reshape(3, 1).expand(3, self.body // 3).reshape(self.body).bool()

  def _wide(self, wide, pw):
    return (pw < INVALID_BIT).where(
      wide[pw & IDX_BITS],
      self._chroma().cast("uint8") * UV_FILL,
    )

  def _narrow(self, wide, narrow, gains, pw, pn):
    chroma = self._chroma()
    off = gains[1:3].reshape(1, 2).expand(self.body // 2, 2).reshape(self.body)
    w = wide[pw & IDX_BITS].float()

    # Amy 49cd7170: use arithmetic on Adreno. A dependent 256-entry luma LUT
    # plus row/column broadcasts roughly doubled the stage time on 3X.
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

  def __call__(self, wide, narrow, gain_y=1.0, gain_c=1.0,
               u_off=0.0, v_off=0.0, gx=0.0, gy=0.0, bands=None):
    if bands is None:
      bands = [gain_y] * len(SeamMeter.BANDS)

    self.params_np[:5] = (gain_c, u_off, v_off, gx, gy)
    self.params_np[5:5 + len(bands)] = bands
    if not self.host_params:
      self.gains.assign(Tensor(self.params_np, device=self.gains.device)).realize()

    # Tables are JIT inputs. Replacing them later does not force a 1.3 s
    # re-capture like Amy observed before 6a13f4c4.
    return self._run(
      wide,
      narrow,
      self.gains,
      self.t["wide"]["pw"],
      self.t["narrow"]["pw"],
      self.t["narrow"]["pn"],
    )


class RotationRefiner:
  """Shadow-only proposal generator.

  This class intentionally does NOT mutate the active geometry. It lets VFN
  collect the same 600-frame confidence-gated residual that Amy uses, but
  returns a candidate for logging only. Active persistence/LUT swapping is
  deliberately deferred.
  """

  def __init__(self, rotvec, n_frames=600, k=0.7, max_step=np.radians(1.0),
               min_step=np.radians(0.02), min_speed=8.0,
               max_std=np.radians(0.5)):
    self.rotvec = np.array(rotvec, np.float64)
    self.n_frames = n_frames
    self.k = k
    self.max_step = max_step
    self.min_step = min_step
    self.min_speed = min_speed
    self.max_std = max_std
    self.acc = np.zeros(3)
    self.n = 0
    self.windows = 0
    self.last_residual = None

  def push_shadow(self, euler, stds, v_ego):
    e = np.asarray(euler, np.float64)
    s = np.asarray(stds, np.float64)
    if v_ego < self.min_speed or not (np.isfinite(e).all() and np.isfinite(s).all()) or (s > self.max_std).any():
      return None

    self.acc += e
    self.n += 1
    if self.n < self.n_frames:
      return None

    residual = np.array(rotvec_from_wide_from_device_euler(self.acc / self.n))
    self.acc[:] = 0
    self.n = 0
    self.windows += 1
    self.last_residual = residual

    step = residual * self.k
    mag = np.linalg.norm(step)
    if mag < self.min_step:
      return dict(converged=True, residual=residual, step=step, candidate=self.rotvec.copy())

    if mag > self.max_step:
      step *= self.max_step / mag
    candidate = matrix_to_rotvec(rotvec_to_matrix(self.rotvec) @ rotvec_to_matrix(step))
    return dict(converged=False, residual=residual, step=step, candidate=candidate)
