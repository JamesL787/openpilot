"""Pinned numeric atlas and the larger stack's saved/touch geometry."""
from dataclasses import replace
from itertools import product
import io
import re
from types import SimpleNamespace

from PIL import Image
import numpy as np
import pyray as rl

from openpilot.starpilot.ui.presentation import BitmapFonts, FontRole, Profile, default_font_directory, font_filename, font_path, validate_bitmap_font
from openpilot.starpilot.ui.onroad_customization import default_document, validate_document
from openpilot.starpilot.ui.onroad_state import slc_controls
from openpilot.starpilot.ui.tests.test_speed_stack import road
from openpilot.starpilot.system.android_auto.projection_layout import default_layout_for_viewport, validate_layout_for_viewport


def test_numeric_subset_is_pinned_and_has_real_tabular_glyphs():
  filename = font_filename(Profile.LARGE, FontRole.SPEED)
  path = font_path(default_font_directory(), filename)
  assert filename == 'DINish-Speed.fnt'
  assert font_filename(Profile.COMPACT, FontRole.SPEED) == 'Inter-Bold.fnt'
  assert font_path(default_font_directory() / 'missing', filename) == path
  validate_bitmap_font(path)
  glyphs = {int(row['id']): row for line in path.read_text().splitlines() if line.startswith('char id=')
            for row in [dict(re.findall(r'(\w+)=(-?\d+)', line))]}
  assert set(map(ord, '0123456789–-?')) <= glyphs.keys()
  assert len({glyphs[ord(char)]['xadvance'] for char in '0123456789'}) == 1
  one = glyphs[ord('1')]
  x, y, w, h = (int(one[key]) for key in ('x', 'y', 'width', 'height'))
  with Image.open(path.with_suffix('.png')) as atlas:
    bounds = atlas.crop((x, y, x + w, y + h)).getchannel('A').getbbox()
    assert bounds is not None and bounds[0] > 0


def test_approved_limit_offset_and_action_sizes_fit_actual_fonts():
  from openpilot.starpilot.ui.large_speed_geometry import ACTION_TEXT, LIMIT_RECTS
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, "Native speed-group font fixture")
  try:
    for profile in Profile:
      with BitmapFonts(profile, default_font_directory()) as fonts:
        large = profile == Profile.LARGE
        limit_size, offset_size = (70, 46) if large else (58, 36)
        for value, offset in (('65', '+5'), ('120', '+10'), ('130', '-10'), ('145', '-137')):
          width = (fonts.measure(value, FontRole.BOLD, limit_size).width +
                   fonts.measure(offset, FontRole.MEDIUM, offset_size).width + (40 if large else 31))
          assert width <= LIMIT_RECTS[profile][2]
        ppi = (2160**2 + 1080**2)**.5 / 6 if large else 300
        for text, role, size, minimum in (('65', FontRole.BOLD, limit_size, 2.8),
                                         ('+5', FontRole.MEDIUM, offset_size, 2.0),
                                         ('H', FontRole.MEDIUM, ACTION_TEXT[profile][0], 2.8)):
          top, bottom = fonts.vertical_ink(text, role, size)
          assert (bottom - top) * 25.4 / ppi >= minimum
  finally:
    if owns_context:
      rl.close_window()


def test_set_speed_and_limit_keep_the_approved_origins_and_fixed_limit_size():
  from unittest.mock import patch
  from openpilot.starpilot.ui.onroad_large_widgets import UnifiedSpeedWidget
  from openpilot.starpilot.ui.layout_preview_renderer import sample_state
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, "Native speed-group placement fixture")
  try:
    with BitmapFonts(Profile.LARGE, default_font_directory()) as fonts:
      for metric, value, show_set in product((False, True), (60, 100, 199, None), (False, True)):
        document = default_document()
        document['showMaxSpeed'] = show_set
        document['layouts']['large']['cruise_limits'].update(x=188, y=95)
        current = sample_state('engaged', document)
        factor = 3.6 if metric else 2.2369362921
        observation = replace(current.speed_limit, speed_limit_mps=120 / factor,
                              presentation_adjusted_limit_mps=130 / factor)
        current = replace(current, metric=metric, cruise_kph=value / factor * 3.6 if value else None,
                          speed_limit=observation)
        calls = []
        with patch.object(fonts, 'draw', lambda *args, calls=calls: calls.append(args)):
          UnifiedSpeedWidget(fonts).render(rl.Rectangle(30, 30, 1800, 1020), current)
        calls = [call for call in calls if call[-1].a == 255]
        posted = next(call for call in calls if call[0] == '120' and call[1] == FontRole.BOLD)
        assert posted[2:4] == (70, 372)
        assert posted[4] + fonts.vertical_ink('120', FontRole.BOLD, 70)[0] == 154
        set_calls = [call for call in calls if call[1] == FontRole.SET_SPEED]
        assert bool(set_calls) == show_set
        if set_calls:
          text, role, size, x, y, _ = set_calls[0]
          assert x == 212 and fonts.measure(text, role, size).width <= 126
          assert y + fonts.vertical_ink(text, role, size)[0] == 146
  finally:
    if owns_context:
      rl.close_window()


def test_galaxy_card_pixels_align_without_reading_font_textures():
  from unittest.mock import patch
  from openpilot.starpilot.ui.layout_preview_renderer import _Canvas, sample_state
  from openpilot.starpilot.ui.onroad_large_widgets import UnifiedSpeedWidget
  from openpilot.starpilot.system.android_auto.projection_layout import (
    default_layout_for_viewport, projection_customization, validate_layout_for_viewport)

  original_readback = rl.load_image_from_texture

  def mobile_readback(texture):
    image = original_readback(texture)
    # Raylib's GLES texture readback unbinds the framebuffer instead of restoring
    # the active preview target. Reproduce that side effect on desktop too.
    rl.rl_disable_framebuffer()
    return image

  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, 'Galaxy card alignment fixture')
  target = rl.load_render_texture(*Profile.LARGE.size)
  try:
    for align, projection in product(('center', 'right'), (False, True)):
      # Start with cold font metrics, as when Galaxy creates its preview canvas.
      with BitmapFonts(Profile.LARGE, default_font_directory()) as fonts:
        document = default_document()
        document['speedAlign'] = align
        viewport = (1920, 1080) if projection else None
        if projection:
          layout = default_layout_for_viewport(viewport)
          layout['speedAlign'] = align
          layout['widgets']['cruise_limits']['opacity'] = 50
          document = projection_customization(validate_layout_for_viewport(layout, viewport), document)
        else:
          document['widgetColors']['large']['cruise_limits'] = {'cardFill': '#10191F80'}
          document = validate_document(document)
        state = sample_state('engaged', document)  # MAX 55 / Your ceiling, SLC 49.
        widget = UnifiedSpeedWidget(fonts)
        canvas = _Canvas.__new__(_Canvas)
        canvas.profile, canvas.viewport, canvas.fonts, canvas.target = Profile.LARGE, viewport, fonts, target
        with patch.object(canvas, 'view',
                          SimpleNamespace(_ordered_widgets=lambda content, state, widget=widget, **kw: widget.render(content, state)), create=True), \
             patch.object(canvas, '_settle', lambda state: None), \
             patch.dict('openpilot.starpilot.ui.layout_preview_renderer.RUNTIME_PREVIEW_WIDGETS', large=('cruise_limits',)), \
             patch.object(rl, 'load_image_from_texture', side_effect=mobile_readback) as readback:
          png = canvas.render_widget_art(state, document['layouts']['large'])
          # A saved 50% background must show on the first frame, without a slider
          # edit triggering another render after the font metrics are warm.
          assert png == canvas.render_widget_art(state, document['layouts']['large'])
          # Only the completed preview is read; measuring glyphs must never change its framebuffer.
          assert readback.call_count == 2
          assert readback.call_args.args[0].id == target.texture.id
        with Image.open(io.BytesIO(png)) as image:
          pixels = np.asarray(image.convert('RGBA'))
        assert pixels[100, 10, 3] == 0  # Unboxed widget art keeps the camera visible.
        ink = pixels[..., 3] > 200
        assert ink.any() and ink[:, 24:160].any() and ink[:, 184:].any()

  finally:
    rl.unload_render_texture(target)
    if owns_context:
      rl.close_window()


def test_native_captions_offsets_and_bounce_fit_their_touch_targets():
  from unittest.mock import Mock, patch
  from openpilot.starpilot.ui.onroad_compact_widgets import CompactHudRenderer
  from openpilot.starpilot.ui.onroad_large_widgets import UnifiedSpeedWidget
  from openpilot.starpilot.ui.onroad_state import speed_limit_bounds
  from openpilot.starpilot.ui.tests.test_unified_speed_native import state
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, 'SLC caption and touch fixture')
  try:
    for profile in Profile:
      with BitmapFonts(profile, default_font_directory()) as fonts:
        for metric, moved, elapsed in product((False, True), (False, True), (0, 750_000_000, 1_500_000_000)):
          current = state(metric=metric, observed_ns=10_000_000_000+elapsed)
          factor = 3.6 if metric else 2.2369362921
          current = replace(current, speed_limit=replace(current.speed_limit, speed_limit_mps=120/factor,
            pending_speed_limit_mps=120/factor, pending_adjusted_limit_mps=130/factor, presentation_adjusted_limit_mps=130/factor))
          if moved:
            for key in (('cruise_limits',) if profile == Profile.LARGE else ('max_speed', 'speed_limit')):
              saved = current.customization['layouts'][profile][key]
              saved['x'] += 100 if profile == Profile.LARGE else 16
              saved['y'] += 20 if profile == Profile.LARGE else 4
          calls = []
          with patch.object(fonts, 'draw', lambda *args, calls=calls: calls.append(args)), patch.object(rl, 'draw_line_ex'):
            if profile == Profile.LARGE:
              UnifiedSpeedWidget(fonts).render(rl.Rectangle(30, 30, 1800, 1020), current)
            else:
              hud = CompactHudRenderer(fonts, Mock())
              hud._set_speed_opacity(current, current.observed_ns)
              hud._set_speed_alpha.x = 1.
              hud.render_max_speed(current)
              hud._speed_limit_sign(current)
          ink = {call[0]: (call[3], call[4]+fonts.vertical_ink(call[0], call[1], call[2])[0],
                          call[3]+fonts.measure(call[0], call[1], call[2]).width,
                          call[4]+fonts.vertical_ink(call[0], call[1], call[2])[1])
                 for call in calls if call[-1].a == 255}
          assert ink['SET'][1] == ink['LIMIT'][1]
          assert ink['120'][3] == ink['+10'][3]
          assert ink['120'][2] < ink['+10'][0]
          left, top, right, bottom = speed_limit_bounds(profile, current)
          for label in ('LIMIT', '120', '+10'):
            x1, y1, x2, y2 = ink[label]
            assert left < x1 < x2 < right and top <= y1 < y2 < bottom
          controls = slc_controls(profile, replace(current, slc_prompt_open=True))
          assert ink['120'][3]+4 < controls[0].bounds[1]
  finally:
    if owns_context:
      rl.close_window()


def test_compact_preview_sprite_keeps_the_caption_arrow_and_override_cross():
  import json
  from unittest.mock import patch
  from openpilot.starpilot.ui.layout_preview_renderer import _Canvas, _straight_rgba, sample_state
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, 'SLC preview crop fixture')
  canvas = _Canvas(Profile.COMPACT)
  try:
    for y, scene in product((18, 0), ('slc_pending', 'slc_retained')):
      document = default_document()
      document['layouts']['compact']['speed_limit']['y'] = y
      with patch.dict('openpilot.starpilot.ui.layout_preview_renderer.RUNTIME_PREVIEW_WIDGETS', compact=('speed_limit',)):
        png = canvas.render_widget_art(sample_state(scene, document), document['layouts']['compact'])
      with Image.open(io.BytesIO(png)) as sheet:
        slot = json.loads(sheet.info['starpilot-widget-art'])['sprites']['speed_limit']
        sprite = sheet.crop((slot['x'], slot['y'], slot['x']+slot['width'], slot['y']+slot['height']))
        rebuilt = Image.new('RGBA', Profile.COMPACT.size)
        rebuilt.paste(sprite, (round(158+slot['offsetX']), round(y+slot['offsetY'])))
      image = rl.load_image_from_texture(canvas.target.texture)
      try:
        rl.image_flip_vertical(image)
        direct = np.frombuffer(_straight_rgba(bytes(rl.ffi.buffer(image.data, 536*240*4))), np.uint8).reshape(240, 536, 4)
      finally:
        rl.unload_image(image)
      assert np.array_equal(direct[..., 3], np.asarray(rebuilt)[..., 3])
      if y:
        assert slot['offsetY'] < 0 and np.asarray(sprite)[:round(-slot['offsetY']), :, 3].any()
      if scene == 'slc_retained':
        assert slot['offsetX'] < 0 and np.asarray(sprite)[:, :round(-slot['offsetX']), 3].any()
  finally:
    canvas.close()
    if owns_context:
      rl.close_window()


def test_v5_geometry_migrates_and_keeps_custom_actions_independent():
  doc = default_document()
  doc['version'] = 5
  doc['speedSources'] = True
  doc['layouts']['large']['cruise_limits'].update(x=1550, y=638)
  doc['layouts']['large']['speed_limit_actions'].update(x=1550, y=954)
  migrated = validate_document(doc)
  assert migrated['version'] == 8
  assert migrated['layouts']['large']['cruise_limits'] == {'x': 1342, 'y': 638, 'enabled': True}
  assert migrated['layouts']['large']['speed_limit_actions'] == {'x': 1254, 'y': 890, 'enabled': True}
  assert migrated['speedSources'] is True
  assert doc['layouts']['large']['cruise_limits']['x'] == 1550
  assert validate_document(migrated) == migrated
  doc['layouts']['large']['cruise_limits'].update(x=88, y=75)
  doc['layouts']['large']['speed_limit_actions'].update(x=88, y=447)
  assert validate_document(doc)['layouts']['large']['speed_limit_actions']['y'] == 248


def test_pending_choices_are_plain_accept_and_decline_with_padded_targets():
  state = road()
  state = replace(state, slc_prompt_open=True, speed_limit=replace(state.speed_limit, pending_speed_limit_mps=25))
  accept, decline = slc_controls(Profile.LARGE, state)
  assert accept.bounds == (100, 248, 372, 408)
  assert decline.bounds == (404, 248, 676, 408)
  assert (accept.label, decline.label) == ('Accept', 'Decline')


def test_projection_v1_layout_migrates_without_losing_other_widgets():
  viewport = (2880, 1080)
  doc = default_layout_for_viewport(viewport)
  doc['version'] = 1
  doc['widgets']['speed_limit_actions'].update(x=88, y=447)
  doc['widgets']['current_speed'].update(x=1400, y=100)
  migrated = validate_layout_for_viewport(doc, viewport)
  assert migrated['version'] == 4
  assert migrated['widgets']['speed_limit_actions']['y'] == 248
  assert migrated['widgets']['current_speed'] == doc['widgets']['current_speed']
  assert validate_layout_for_viewport(migrated, viewport) == migrated


def test_committed_projection_v1_right_edge_is_preserved_and_clamped():
  viewport = (1860, 1080)
  doc = default_layout_for_viewport(viewport)
  doc['version'] = 1
  doc['widgets']['cruise_limits'].update(x=1654, y=75)
  doc['widgets']['speed_limit_actions'].update(x=1654, y=500)
  migrated = validate_layout_for_viewport(doc, viewport)
  assert migrated['widgets']['cruise_limits']['x'] == 1342
  assert migrated['widgets']['speed_limit_actions'] == {'x': 1254, 'y': 248, 'enabled': True}

