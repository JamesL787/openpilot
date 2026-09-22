"""Live photometric match for the narrow-inset / wide-surround seam."""

import numpy as np

from .geometry import UV_FILL

EXPOSURE_GAIN_A, EXPOSURE_GAIN_P = 0.868, 0.708


def exposure_gain(narrow_exposure, wide_exposure, lo=0.25, hi=4.0):
  if not (narrow_exposure > 0 and wide_exposure > 0):
    return 1.0
  return float(np.clip(EXPOSURE_GAIN_A * (narrow_exposure / wide_exposure) ** EXPOSURE_GAIN_P, lo, hi))


class SeamMeter:
  BANDS = ((16, 50), (50, 100), (100, 160), (160, 235))
  IDENTITY = np.array([1, 0, 0, 0, 0] + [1] * len(BANDS), np.float32)

  def __init__(self, geometry, alpha=0.3, every=2):
    self.y_w, self.y_n, self.pos, self.cell, self.uv_w, self.uv_n = (
      geometry[k] for k in ("y_w", "y_n", "pos", "cell", "uv_w", "uv_n")
    )
    self.cell_bad = np.zeros(32 * 18, np.float32)
    self.CELL_ALPHA, self.CELL_LIMIT = 0.02, 0.2
    self.alpha, self.every, self.n_calls, self.moving = alpha, every, 0, False
    self.state = None

  @staticmethod
  def geometry(dw, dh, luma, chroma, n_pairs=2048, ring=(30.0, 130.0)) -> dict:
    iw, vw, inn, vn, dist = luma
    in_ring = vw & vn & (dist > ring[0]) & (dist < ring[1])
    sel = np.flatnonzero(in_ring)[::max(1, int(in_ring.sum()) // n_pairs)][:n_pairs]
    g = dict(y_w=iw.ravel()[sel], y_n=inn.ravel()[sel])
    g["pos"] = np.stack([
      (sel % dw + 0.5) / dw * 2 - 1,
      (sel // dw + 0.5) / dh * 2 - 1,
    ], 1).astype(np.float32)
    cell = np.floor((g["pos"] + 1) / 2 * [32, 18]).astype(int)
    g["cell"] = cell[:, 0] * 18 + cell[:, 1]
    iw2, vw2, inn2, vn2, _ = chroma
    in_ring2 = in_ring[::2, ::2] & vw2 & vn2
    sel2 = np.flatnonzero(in_ring2)[::max(1, int(in_ring2.sum()) // (n_pairs // 2))][:n_pairs // 2]
    g["uv_w"], g["uv_n"] = iw2.ravel()[sel2], inn2.ravel()[sel2]
    return g

  def measure(self, wide, narrow):
    yw = wide[self.y_w].astype(np.float32)
    yn = narrow[self.y_n].astype(np.float32)
    good = (yw > 16) & (yw < 235) & (yn > 16) & (yn < 235)
    if good.sum() < 256:
      return None
    yw, yn, pos = yw[good], yn[good], self.pos[good]
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
      return np.linalg.solve(A.T @ Aw + 1e-3 * np.eye(A.shape[1], dtype=np.float32), Aw.T @ lr)

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
    uw, un = wide[self.uv_w].astype(np.float32), narrow[self.uv_n].astype(np.float32)
    vw, vn = wide[self.uv_w + 1].astype(np.float32), narrow[self.uv_n + 1].astype(np.float32)
    du = float(np.median(un - UV_FILL - gy * (uw - UV_FILL)))
    dv = float(np.median(vn - UV_FILL - gy * (vw - UV_FILL)))
    return np.array([gy, du, dv, gx, gyp, *bands], np.float32)

  def update(self, wide, narrow, model_gain=1.0):
    self.n_calls += 1
    if self.state is None or self.moving or self.n_calls % self.every == 0:
      target = self.measure(wide, narrow)
      if target is None:
        # Amy HEAD fix: U/V and the lens-shading gradient are per-unit terms.
        # When the seam is too dark/saturated to measure, keep those terms and
        # only let luma/tone return toward the live exposure model.
        held = self.state[1:5] if self.state is not None else (0, 0, 0, 0)
        target = np.array([model_gain, *held] + [model_gain] * len(self.BANDS), np.float32)
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
    s[0] *= model_gain
    s[5:] *= model_gain
    return s
