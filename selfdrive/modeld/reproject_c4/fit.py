"""Direct narrow<->wide rotation fit from synchronized camera frame pairs."""

import numpy as np

from .geometry import (
  C4_NARROW_K,
  matrix_to_rotvec,
  rotvec_to_matrix,
  sample_coords,
  unproject_fisheye,
  unproject_pinhole,
)

MIN_MATCHES = 15


def render_layers(narrow_y, wide_y, calib, dst_wh=(1344, 760)):
  sh, sw = narrow_y.shape
  mw, mn = sample_coords("narrow", dst_wh[0], dst_wh[1], 1.0, calib)
  xn = np.round(mn[..., 0] - 0.5).astype(int)
  yn = np.round(mn[..., 1] - 0.5).astype(int)
  xw = np.round(mw[..., 0] - 0.5).astype(int)
  yw = np.round(mw[..., 1] - 0.5).astype(int)
  vn = (xn >= 0) & (xn < sw) & (yn >= 0) & (yn < sh)
  vw = (xw >= 0) & (xw < sw) & (yw >= 0) & (yw < sh)
  inset = np.where(vn, narrow_y[yn.clip(0, sh - 1), xn.clip(0, sw - 1)], 0).astype(np.float32)
  surround = np.where(vw, wide_y[yw.clip(0, sh - 1), xw.clip(0, sw - 1)], 0).astype(np.float32)
  return inset, surround, mw, vn & vw


def phase_shift(a, b):
  h, w = a.shape
  win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
  A = np.fft.rfft2((a - a.mean()) * win)
  B = np.fft.rfft2((b - b.mean()) * win)
  R = A * np.conj(B)
  R /= np.abs(R) + 1e-6
  r = np.fft.irfft2(R, s=(h, w))
  py, px = divmod(int(np.argmax(r)), w)
  peak = r[py, px]
  m = np.ones_like(r, bool)
  m[max(0, py - 5):py + 6, max(0, px - 5):px + 6] = False
  side = r[m]
  psr = (peak - side.mean()) / (side.std() + 1e-9)

  def sub(c, l, rr):
    d = l - 2 * c + rr
    return 0.0 if d >= 0 else float(0.5 * (l - rr) / d)

  dx = px + sub(peak, r[py, (px - 1) % w], r[py, (px + 1) % w])
  dy = py + sub(peak, r[(py - 1) % h, px], r[(py + 1) % h, px])
  if dx > w / 2:
    dx -= w
  if dy > h / 2:
    dy -= h
  return -dx, -dy, float(psr)


def match_rays(narrow_y, wide_y, calib, dst_wh=(1344, 760), patch=96, stride=64,
               min_psr=5.0, max_shift=None):
  inset, surround, mw, valid = render_layers(narrow_y, wide_y, calib, dst_wh)
  dw, dh = dst_wh
  max_shift = max_shift or patch / 3
  pa, pb = [], []
  for y in range(0, dh - patch + 1, stride):
    for x in range(0, dw - patch + 1, stride):
      if valid[y:y + patch, x:x + patch].mean() < 0.98:
        continue
      a = inset[y:y + patch, x:x + patch]
      b = surround[y:y + patch, x:x + patch]
      if a.std() < 4 or b.std() < 4:
        continue
      dx, dy, psr = phase_shift(a, b)
      if psr < min_psr or abs(dx) > max_shift or abs(dy) > max_shift:
        continue
      pa.append((x + patch / 2, y + patch / 2))
      pb.append((x + patch / 2 + dx, y + patch / 2 + dy))
  if len(pa) < 4:
    return None
  pa, pb = np.float32(pa), np.float32(pb)
  rays_n = unproject_pinhole(pa, C4_NARROW_K[0, 0], C4_NARROW_K[0, 2], C4_NARROW_K[1, 2])
  xb = np.round(pb[:, 0] - 0.5).astype(int).clip(0, dw - 1)
  yb = np.round(pb[:, 1] - 0.5).astype(int).clip(0, dh - 1)
  rays_w = unproject_fisheye(mw[yb, xb], calib["wide"])
  return rays_n, rays_w


def kabsch(rays_n, rays_w):
  for _ in range(2):
    U, _, Vt = np.linalg.svd(rays_w.T @ rays_n)
    d = np.sign(np.linalg.det(U @ Vt))
    Rm = U @ np.diag([1, 1, d]) @ Vt
    res = np.degrees(np.arccos(np.clip((rays_n @ Rm.T * rays_w).sum(1), -1, 1)))
    keep = res <= np.percentile(res, 80)
    rays_n, rays_w = rays_n[keep], rays_w[keep]
  return matrix_to_rotvec(Rm), int(len(rays_n)), float(np.sqrt(np.mean(res[keep] ** 2)))


def fit_rotation(narrow_y, wide_y, calib0, dst_wh=(1344, 760), iters=3, coarse=True):
  calib = dict(calib0)
  R = np.asarray(calib0["R"], float)
  for it in range(iters):
    calib["R"] = tuple(R)
    if it == 0 and coarse:
      m = match_rays(narrow_y, wide_y, calib, dst_wh, patch=192, stride=96, max_shift=64)
    else:
      m = match_rays(narrow_y, wide_y, calib, dst_wh)
    if m is None:
      return None
    R, n, rms = kabsch(*m)
  if n < MIN_MATCHES:
    return None
  return tuple(float(v) for v in R), n, rms


def mean_rotvec(rotvecs):
  M = sum(rotvec_to_matrix(v) for v in rotvecs) / len(rotvecs)
  U, _, Vt = np.linalg.svd(M)
  d = np.sign(np.linalg.det(U @ Vt))
  return tuple(float(v) for v in matrix_to_rotvec(U @ np.diag([1, 1, d]) @ Vt))


def combine_fits(rotvecs, trim=0.2):
  """VFN's conservative trimmed rotation mean plus pitch/yaw SE stop metric."""
  m = mean_rotvec(rotvecs)
  dev = np.array([
    np.linalg.norm(matrix_to_rotvec(rotvec_to_matrix(m).T @ rotvec_to_matrix(v)))
    for v in rotvecs
  ])
  keep = np.argsort(dev)[:max(1, int(round(len(rotvecs) * (1 - trim))))]
  kept = np.array([rotvecs[i] for i in keep])
  mean = mean_rotvec(kept)
  se = float(np.degrees(np.linalg.norm(kept[:, :2].std(0)) / np.sqrt(len(kept)))) if len(kept) > 1 else float("inf")
  return mean, keep, float(np.degrees(dev[keep].max())), se
