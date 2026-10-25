"""Rasterize fixed SLC geometry once; runtime only tints and draws atlas quads."""

import numpy as np
from PIL import Image

from openpilot.starpilot.ui.speed_limit_shapes import ATLAS_PATH, ATLAS_SIZE, SPRITES


SAMPLES = 8


def coverage(mask, width, height):
  return mask.reshape(height, SAMPLES, width, SAMPLES).mean(axis=(1, 3))


def generate():
  atlas = Image.new('RGBA', ATLAS_SIZE)
  for name, (x, y, width, height) in SPRITES.items():
    px = (np.arange(width * SAMPLES) + .5) / SAMPLES - width / 2
    py = (np.arange(height * SAMPLES) + .5) / SAMPLES - height / 2
    xx, yy = np.meshgrid(px, py)
    rgba = np.full((height, width, 4), 255, dtype=np.uint8)
    if name in ('disc', 'ring'):
      radius = np.hypot(xx, yy)
      # End the white backing inside the opaque rim, avoiding an outer white fringe.
      mask = radius <= 55 if name == 'disc' else (radius <= 59) & (radius >= 51)
      rgba[..., 3] = np.rint(coverage(mask, width, height) * 255).astype(np.uint8)
    elif name == 'outline':
      # Signed distance to a rounded rectangle; supersampling is offline only.
      qx, qy = np.abs(xx) - 49, np.abs(yy) - 56
      distance = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - 8
      rgba[..., 3] = np.rint(coverage((distance >= -2) & (distance <= 0), width, height) * 255).astype(np.uint8)
    else:
      half_height, wing, stem, head, outline = (14, 9, 3, 9, 1.4) if name == 'arrow_large' else (6, 4, 2, 4, 1)
      base = half_height - head
      points = ((-stem/2, -half_height), (stem/2, -half_height), (stem/2, base), (wing, base),
                (0, half_height), (-wing, base), (-stem/2, base))
      inside = ((np.abs(xx) <= stem/2) & (yy >= -half_height) & (yy <= base)) | (
        (yy >= base) & (yy <= half_height) & (np.abs(xx) <= wing * (half_height - yy) / head))
      distance_sq = np.full_like(xx, np.inf)
      for (ax, ay), (bx, by) in zip(points, (*points[1:], points[0]), strict=True):
        dx, dy = bx - ax, by - ay
        t = np.clip(((xx - ax) * dx + (yy - ay) * dy) / (dx*dx + dy*dy), 0, 1)
        distance_sq = np.minimum(distance_sq, (xx - ax - t*dx)**2 + (yy - ay - t*dy)**2)
      fill = coverage(inside, width, height)
      border = coverage((distance_sq <= outline**2) & ~inside, width, height) * .87
      alpha = fill + border
      for channel, dark in enumerate((6, 14, 10)):
        rgba[..., channel] = np.rint(np.divide(fill * 255 + border * dark, alpha,
                                              out=np.full_like(alpha, dark), where=alpha > 0)).astype(np.uint8)
      rgba[..., 3] = np.rint(alpha * 255).astype(np.uint8)
    atlas.paste(Image.fromarray(rgba), (x, y))
  return atlas


if __name__ == '__main__':
  generate().save(ATLAS_PATH, optimize=True)
