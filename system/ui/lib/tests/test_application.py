from importlib.resources import as_file
from types import SimpleNamespace

from openpilot.system.ui.lib import application


def test_raylib_target_fps_limits_mici(monkeypatch):
  monkeypatch.setattr(application, "OFFSCREEN", False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "mici")

  assert application._raylib_target_fps(60) == 60


def test_raylib_target_fps_limits_other_devices(monkeypatch):
  monkeypatch.setattr(application, "OFFSCREEN", False)
  monkeypatch.setattr(application, "DEVICE_TYPE", "tici")

  assert application._raylib_target_fps(60) == 60


def test_raylib_target_fps_disables_limit_for_offscreen(monkeypatch):
  monkeypatch.setattr(application, "OFFSCREEN", True)
  monkeypatch.setattr(application, "DEVICE_TYPE", "tici")

  assert application._raylib_target_fps(60) == 0


def test_burn_in_shift_transitions_between_positions(monkeypatch):
  app = object.__new__(application.GuiApplication)
  app._burn_in_start_time = 100.0

  monkeypatch.setattr(application, "BURN_IN_PREVENTION", True)
  monkeypatch.setattr(application, "BURN_IN_SHIFT_INTERVAL", 10.0)
  monkeypatch.setattr(application, "BURN_IN_SHIFT_PIXELS", 2)
  monkeypatch.setattr(application, "BURN_IN_SHIFT_TRANSITION_SECONDS", 2.0)

  assert app._burn_in_shift(108.0) == (0.0, 0.0)
  midpoint = app._burn_in_shift(109.0)
  assert midpoint == (-1.0, 0.0)
  assert app._burn_in_shift(110.0) == (-2.0, 0.0)


def test_brand_font_assets_include_wordmark_glyphs():
  with as_file(application.FONT_DIR.joinpath("como-heavy.fnt")) as font_path:
    lines = font_path.read_text().splitlines()

  glyphs = {}
  for line in lines:
    if not line.startswith("char id="):
      continue
    fields = dict(field.split("=", 1) for field in line.split() if "=" in field)
    glyphs[int(fields["id"])] = (int(fields["width"]), int(fields["height"]))

  for char in set("StarPilot"):
    assert glyphs[ord(char)][0] > 0
    assert glyphs[ord(char)][1] > 0


def test_brand_font_is_not_replaced_by_language_fallback(monkeypatch):
  brand_font = SimpleNamespace(texture=SimpleNamespace(id=1))
  unifont = SimpleNamespace(texture=SimpleNamespace(id=2))
  monkeypatch.setattr(application.multilang, "requires_unifont", lambda: True)
  monkeypatch.setattr(application.gui_app, "font", lambda weight: {
    application.FontWeight.BRAND: brand_font,
    application.FontWeight.UNIFONT: unifont,
  }[weight])

  assert application.font_fallback(brand_font) is brand_font
  assert application.font_fallback(SimpleNamespace(texture=SimpleNamespace(id=3))) is unifont
