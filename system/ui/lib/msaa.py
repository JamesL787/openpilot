"""Multisampled offscreen rendering.

Raylib render textures are single-sampled, so everything drawn into one (the
device UI when it renders through a texture, and the Starpilot Auto frames) is
aliased even though the window asks for FLAG_MSAA_4X_HINT. MsaaTarget is a
multisampled framebuffer that raylib can draw into with begin_texture_mode();
resolve() then blits it into an ordinary RenderTexture (GLES3 / GL3).
"""
import math
import os
import sys

import cffi
import pyray as rl
import raylib

from openpilot.common.swaglog import cloudlog

UI_MSAA_SAMPLES = int(os.getenv("UI_MSAA_SAMPLES", "4"))

GL_FRAMEBUFFER = 0x8D40
GL_READ_FRAMEBUFFER = 0x8CA8
GL_DRAW_FRAMEBUFFER = 0x8CA9
GL_RENDERBUFFER = 0x8D41
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_DEPTH_ATTACHMENT = 0x8D00
GL_RGBA8 = 0x8058
GL_DEPTH_COMPONENT24 = 0x81A6
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_COLOR_BUFFER_BIT = 0x4000
GL_NEAREST = 0x2600
GL_MAX_SAMPLES = 0x8D57
GL_SCISSOR_TEST = 0x0C11

_ffi = cffi.FFI()
_ffi.cdef("""
  void glGenFramebuffers(int n, unsigned int *ids);
  void glDeleteFramebuffers(int n, const unsigned int *ids);
  void glBindFramebuffer(unsigned int target, unsigned int id);
  void glGenRenderbuffers(int n, unsigned int *ids);
  void glDeleteRenderbuffers(int n, const unsigned int *ids);
  void glBindRenderbuffer(unsigned int target, unsigned int id);
  void glRenderbufferStorageMultisample(unsigned int target, int samples, unsigned int format, int width, int height);
  void glFramebufferRenderbuffer(unsigned int target, unsigned int attachment, unsigned int rbtarget, unsigned int rb);
  unsigned int glCheckFramebufferStatus(unsigned int target);
  void glBlitFramebuffer(int sx0, int sy0, int sx1, int sy1, int dx0, int dy0, int dx1, int dy1, unsigned int mask, unsigned int filter);
  void glGetIntegerv(unsigned int pname, int *data);
  void glDisable(unsigned int cap);
""")
_gl = None


def _load_gl():
  global _gl
  if _gl is None:
    if sys.platform == "darwin":
      _gl = _ffi.dlopen("/System/Library/Frameworks/OpenGL.framework/OpenGL")
    else:
      _gl = _ffi.dlopen("libGLESv2.so")
  return _gl


class MsaaTarget:
  def __init__(self, width: int, height: int, samples: int = UI_MSAA_SAMPLES):
    gl = _load_gl()
    max_samples = _ffi.new("int *")
    gl.glGetIntegerv(GL_MAX_SAMPLES, max_samples)
    self.samples = max(1, min(samples, max_samples[0]))
    self.width = width
    self.height = height

    ids = _ffi.new("unsigned int[2]")
    gl.glGenRenderbuffers(2, ids)
    self._renderbuffers = (ids[0], ids[1])
    fbo = _ffi.new("unsigned int *")
    gl.glGenFramebuffers(1, fbo)
    self._fbo = fbo[0]

    gl.glBindRenderbuffer(GL_RENDERBUFFER, ids[0])
    gl.glRenderbufferStorageMultisample(GL_RENDERBUFFER, self.samples, GL_RGBA8, width, height)
    gl.glBindRenderbuffer(GL_RENDERBUFFER, ids[1])
    gl.glRenderbufferStorageMultisample(GL_RENDERBUFFER, self.samples, GL_DEPTH_COMPONENT24, width, height)
    gl.glBindRenderbuffer(GL_RENDERBUFFER, 0)

    gl.glBindFramebuffer(GL_FRAMEBUFFER, self._fbo)
    gl.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, ids[0])
    gl.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, ids[1])
    status = gl.glCheckFramebufferStatus(GL_FRAMEBUFFER)
    gl.glBindFramebuffer(GL_FRAMEBUFFER, 0)
    if status != GL_FRAMEBUFFER_COMPLETE:
      self.unload()
      raise RuntimeError(f"MSAA framebuffer incomplete: {status:#x}")

    # begin_texture_mode() only reads the framebuffer id and texture size.
    self.render_texture = rl.RenderTexture(
      self._fbo,
      rl.Texture(0, width, height, 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8),
      rl.Texture(0, width, height, 1, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8),
    )

  @classmethod
  def create(cls, width: int, height: int) -> "MsaaTarget | None":
    """Return a target, or None when MSAA is disabled or unsupported."""
    if UI_MSAA_SAMPLES <= 1:
      return None
    try:
      return cls(width, height)
    except Exception as exc:
      cloudlog.warning(f"UI MSAA unavailable, rendering without anti-aliasing: {exc}")
      return None

  def resolve(self, dest: rl.RenderTexture) -> None:
    """Blit the multisampled frame into dest. Call after end_texture_mode()."""
    gl = _load_gl()
    gl.glDisable(GL_SCISSOR_TEST)
    gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, self._fbo)
    gl.glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dest.id)
    gl.glBlitFramebuffer(0, 0, self.width, self.height, 0, 0, dest.texture.width, dest.texture.height,
                         GL_COLOR_BUFFER_BIT, GL_NEAREST)
    gl.glBindFramebuffer(GL_FRAMEBUFFER, 0)

  def unload(self) -> None:
    gl = _load_gl()
    if self._fbo:
      gl.glDeleteFramebuffers(1, _ffi.new("unsigned int *", self._fbo))
      self._fbo = 0
    if self._renderbuffers:
      gl.glDeleteRenderbuffers(2, _ffi.new("unsigned int[2]", self._renderbuffers))
      self._renderbuffers = ()


# raylib's DrawRectangleRounded() emits its corner fans with vertices that are
# recomputed per triangle, so neighbouring edges do not always match exactly.
# Single-sampled rendering hides the hairline cracks; with MSAA, samples fall
# through them and small, finely segmented pills (toggles) show speckles. This
# replacement draws one fan over a shared outline, which is watertight.
_SMOOTH_CIRCLE_ERROR_RATE = 0.5
_ROUNDED_OUTLINES: dict[tuple, tuple[object, int, object]] = {}
_MAX_CACHED_OUTLINES = 512


def _rounded_outline(width: float, height: float, radius: float, segments: int) -> tuple[object, int]:
  key = (width, height, radius, segments)
  cached = _ROUNDED_OUTLINES.get(key)
  if cached is not None:
    return cached[:2]
  if len(_ROUNDED_OUTLINES) >= _MAX_CACHED_OUTLINES:
    _ROUNDED_OUTLINES.clear()

  corners = ((width - radius, height - radius, 0.0), (radius, height - radius, 90.0),
             (radius, radius, 180.0), (width - radius, radius, 270.0))
  points = [(width / 2, height / 2)]
  for cx, cy, start in corners:
    for i in range(segments + 1):
      angle = math.radians(start + 90.0 * i / segments)
      points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
  points.append(points[1])
  # Raylib fans need counter-clockwise winding on screen (y down), i.e. the
  # reverse of the angle order above.
  points[1:] = points[:0:-1]

  array = rl.ffi.new("Vector2[]", len(points))
  for i, (px, py) in enumerate(points):
    array[i].x = px
    array[i].y = py
  # Keep the owning array alive alongside the pointer raylib is handed.
  _ROUNDED_OUTLINES[key] = (rl.ffi.cast("Vector2 *", array), len(points), array)
  return _ROUNDED_OUTLINES[key][:2]


def draw_rectangle_rounded(rec, roundness: float, segments: int, color) -> None:
  if not isinstance(rec, rl.ffi.CData):
    rec = rl.Rectangle(*rec)
  if not isinstance(color, rl.ffi.CData):
    color = rl.Color(*color)
  width, height = float(rec.width), float(rec.height)
  radius = min(width, height) * min(roundness, 1.0) / 2.0
  if radius <= 0.0 or width < 1.0 or height < 1.0:
    raylib.DrawRectangleRec(rec, color)
    return
  if segments < 4:
    th = math.acos(2 * (1 - _SMOOTH_CIRCLE_ERROR_RATE / radius) ** 2 - 1) if radius > _SMOOTH_CIRCLE_ERROR_RATE else math.pi / 2
    segments = max(4, int(math.ceil(2 * math.pi / th / 4.0)))
  points, count = _rounded_outline(round(width, 2), round(height, 2), round(radius, 2), int(segments))
  # Called for most UI surfaces every frame, so skip pyray's wrapper overhead.
  raylib.rlPushMatrix()
  raylib.rlTranslatef(float(rec.x), float(rec.y), 0.0)
  raylib.DrawTriangleFan(points, count, color)
  raylib.rlPopMatrix()


def install_watertight_shapes() -> None:
  """Route rl.draw_rectangle_rounded through the watertight version."""
  rl.draw_rectangle_rounded = draw_rectangle_rounded
