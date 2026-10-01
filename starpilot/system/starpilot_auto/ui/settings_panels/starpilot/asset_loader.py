from __future__ import annotations

from importlib.resources import as_file, files

import pyray as rl

from openpilot.system.ui.lib.application import gui_app


def starpilot_texture(asset_path: str, width: int | None = None, height: int | None = None,
                      alpha_premultiply: bool = False, keep_aspect_ratio: bool = True) -> rl.Texture:
  if width is not None:
    width = round(width)
  if height is not None:
    height = round(height)

  cache_key = f"starpilot_{asset_path}_{width}_{height}_{alpha_premultiply}_{keep_aspect_ratio}"
  if cache_key in gui_app._textures:
    return gui_app._textures[cache_key]

  starpilot_assets = files("openpilot.starpilot").joinpath("assets")
  with as_file(starpilot_assets.joinpath(asset_path)) as fspath:
    image_obj = gui_app._load_image_from_path(fspath.as_posix(), width, height, alpha_premultiply, keep_aspect_ratio)
    texture_obj = gui_app._load_texture_from_image(image_obj)

  if gui_app._scale != 1.0 and width is not None and height is not None:
    texture_obj.width = width
    texture_obj.height = height

  gui_app._textures[cache_key] = texture_obj
  return texture_obj
