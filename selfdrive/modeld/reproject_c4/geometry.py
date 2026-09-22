"""Lens models and geometry for the comma 3X -> comma 4 reprojection stage.

Phase 2 intentionally adopts Amy's current fleet-derived 3X wide-lens geometry
and 50 px composite feather as one coherent optics experiment.
"""

import numpy as np

from openpilot.common.transformations.camera import DEVICE_CAMERAS


# Amy's fleet median of 40 self-calibrated 3X units. This is paired with the
# per-unit direct camera rotation fit below, rather than a single board-calibrated
# wide lens.
X3_WIDE_POP = dict(f=597.732, cx=963.936, cy=603.959,
                   k=(-0.011968, 0.024043, -0.0091132), tc=1.51354)
X3_NARROW = dict(f=2600.85, cx=964.0, cy=604.0, k1=-0.36400)
C4_WIDE = dict(f=442.555, cx=672.380, cy=378.718,
               k=(0.0089611, 0.029156, -0.015066), tc=1.39626)

# Fleet-median narrow->wide seed used only when there is no completed per-unit
# fit and no usable persisted wideFromDeviceEuler to seed from.
POP_ROTATION = (0.0154781, -0.0225994, -0.00068013)

C4_NARROW_K = DEVICE_CAMERAS[("mici", "os04c10")].fcam.intrinsics
ZMIN = np.cos(np.radians(88.0))
FEATHER_PX = 50
UV_FILL = 128
C4_CAM = (1344, 760)


def calib_from_rotvec(rotvec):
  return dict(wide=X3_WIDE_POP, narrow=X3_NARROW, R=tuple(float(v) for v in rotvec))


def rotvec_from_wide_from_device_euler(euler):
  """Convert model/device Euler [roll,pitch,yaw] into camera-axis rotvec [pitch,yaw,roll]."""
  r, p, y = euler
  return (float(p), float(y), float(r))


def matrix_to_rotvec(M):
  a = np.arccos(np.clip((np.trace(M) - 1) / 2, -1, 1))
  if a < 1e-9:
    return np.zeros(3)
  return a / (2 * np.sin(a)) * np.array([
    M[2, 1] - M[1, 2],
    M[0, 2] - M[2, 0],
    M[1, 0] - M[0, 1],
  ])


def _dtheta_d(t, k):
  return 1 + 3 * k[0] * t**2 + 5 * k[1] * t**4 + 7 * k[2] * t**6


def _theta_d(th, L):
  k, tc = L["k"], L["tc"]
  p = lambda t: t * (1 + k[0] * t**2 + k[1] * t**4 + k[2] * t**6)
  return np.where(th <= tc, p(th), p(tc) + _dtheta_d(tc, k) * (th - tc))


def unproject_fisheye(px, L):
  dx, dy = px[..., 0] - L["cx"], px[..., 1] - L["cy"]
  r = np.hypot(dx, dy)
  td = r / L["f"]
  th = td
  # Amy verified this reaches double precision by the third step for these lenses.
  for _ in range(4):
    th = th - (_theta_d(th, L) - td) / _dtheta_d(np.minimum(th, L["tc"]), L["k"])
  s = np.sin(th)
  rr = np.where(r > 0, r, 1)
  return np.stack([s * dx / rr, s * dy / rr, np.cos(th)], -1)


def unproject_pinhole(px, f, cx, cy):
  d = np.stack([
    (px[..., 0] - cx) / f,
    (px[..., 1] - cy) / f,
    np.ones(px.shape[:-1]),
  ], -1)
  return d / np.linalg.norm(d, axis=-1, keepdims=True)


def project_fisheye(rays, L):
  rho = np.hypot(rays[..., 0], rays[..., 1])
  th = np.arctan2(rho, rays[..., 2])
  r = L["f"] * _theta_d(th, L)
  rr = np.where(rho > 0, rho, 1)
  return np.stack([
    L["cx"] + r * rays[..., 0] / rr,
    L["cy"] + r * rays[..., 1] / rr,
  ], -1)


def project_pinhole_k1(rays, L):
  x, y = rays[..., 0] / rays[..., 2], rays[..., 1] / rays[..., 2]
  s = 1 + L["k1"] * (x * x + y * y)
  return np.stack([
    L["cx"] + L["f"] * x * s,
    L["cy"] + L["f"] * y * s,
  ], -1)


def rotvec_to_matrix(v):
  v = np.asarray(v, dtype=np.float64)
  a = np.linalg.norm(v)
  if a == 0:
    return np.eye(3)
  k = v / a
  K = np.array([
    [0, -k[2], k[1]],
    [k[2], 0, -k[0]],
    [-k[1], k[0], 0],
  ])
  return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def sample_coords(out_cam, dst_w, dst_h, scale, calib):
  """Float 3X wide/narrow source coordinates for each comma 4 output pixel."""
  xs, ys = np.meshgrid(
    (np.arange(dst_w) + 0.5) / scale,
    (np.arange(dst_h) + 0.5) / scale,
  )
  px = np.stack([xs, ys], -1)
  if out_cam == "wide":
    rays = unproject_fisheye(px, C4_WIDE)
  else:
    rays = unproject_pinhole(px, C4_NARROW_K[0, 0], C4_NARROW_K[0, 2], C4_NARROW_K[1, 2])
  rays_w = rays @ rotvec_to_matrix(calib["R"]).T
  mw = project_fisheye(rays_w, calib["wide"]) * scale
  mw[rays_w[..., 2] < ZMIN] = -1
  mn = project_pinhole_k1(rays, calib["narrow"]) * scale
  mn[rays[..., 2] <= 0] = -1
  return mw, mn


def _nv12_index(xy, src_w, src_h, stride, uv_offset, chroma):
  """Nearest-neighbour byte index into a source NV12 buffer plus validity mask."""
  xy = np.clip(np.nan_to_num(xy, nan=-1.0), -1e6, 1e6)
  x = np.round(xy[..., 0] - 0.5).astype(np.int64)
  y = np.round(xy[..., 1] - 0.5).astype(np.int64)
  w, h = (src_w // 2, src_h // 2) if chroma else (src_w, src_h)
  valid = (x >= 0) & (x < w) & (y >= 0) & (y < h)
  x = np.clip(x, 0, w - 1)
  y = np.clip(y, 0, h - 1)
  idx = (uv_offset + y * stride + 2 * x) if chroma else (y * stride + x)
  return idx, valid
