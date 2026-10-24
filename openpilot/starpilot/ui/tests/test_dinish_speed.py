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
  from openpilot.starpilot.ui.large_speed_geometry import ACTION_TEXT, LARGE_SIGN_SCALE, LIMIT_RECTS
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, "Native speed-group font fixture")
  try:
    for profile in Profile:
      with BitmapFonts(profile, default_font_directory()) as fonts:
        large = profile == Profile.LARGE
        scale = LARGE_SIGN_SCALE if large else 1
        text_scale = scale * Profile.COMPACT.font_scale / profile.font_scale
        limit_size, offset_size = 58 * text_scale, 36 * text_scale
        for value, offset in (('65', '+5'), ('120', '+10'), ('130', '-10'), ('145', '-137')):
          a, b = fonts.horizontal_ink(value, FontRole.BOLD, limit_size)
          value_width = b - a
          a, b = fonts.horizontal_ink(offset, FontRole.MEDIUM, offset_size)
          offset_width = b - a
          width = max(value_width, offset_width) + 20 * scale
          assert width <= LIMIT_RECTS[profile][2]
        action_width = 272 if large else 168
        assert all(fonts.measure(label, FontRole.MEDIUM, ACTION_TEXT[profile][0]).width + 4 <= action_width
                   for label in ('Accept', 'Decline'))
        ppi = (2160**2 + 1080**2)**.5 / 6 if large else 300
        for text, role, size, minimum in (('65', FontRole.BOLD, limit_size, 2.5 if large else 2.8),
                                         ('+5', FontRole.MEDIUM, offset_size, 1.5 if large else 2.0),
                                         ('H', FontRole.MEDIUM, ACTION_TEXT[profile][0], 2.8)):
          top, bottom = fonts.vertical_ink(text, role, size)
          assert (bottom - top) * 25.4 / ppi >= minimum
  finally:
    if owns_context:
      rl.close_window()


def test_large_sign_is_secondary_to_set_speed_at_the_saved_position():
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
        assert abs(posted[2] - 58 * .95 * Profile.COMPACT.font_scale / Profile.LARGE.font_scale) < 1e-6
        left, right = fonts.horizontal_ink('120', FontRole.BOLD, posted[2])
        assert abs(posted[3] + (left + right) / 2 - 428.05) < 1e-6
        assert posted[4] + fonts.vertical_ink('120', FontRole.BOLD, posted[2])[0] == 142.5
        set_calls = [call for call in calls if call[1] == FontRole.SET_SPEED]
        assert bool(set_calls) == show_set
        if set_calls:
          text, role, size, x, y, _ = set_calls[0]
          assert x == 212 and fonts.measure(text, role, size).width <= 148
          assert y + fonts.vertical_ink(text, role, size)[0] == 146
          assert size == (120 if value in (60, None) else 87)
          left, right = fonts.horizontal_ink(text, role, size)
          assert x + right + 16 <= 372
          unit = next(call for call in calls if call[0] == ('km/h' if metric else 'mph'))
          assert unit[2] == 28
          assert unit[4] + fonts.vertical_ink(unit[0], unit[1], unit[2])[1] < 146
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


def test_native_signs_offsets_and_captions_fit_their_touch_targets():
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
          ink = {call[0]: (call[3]+fonts.horizontal_ink(call[0], call[1], call[2])[0], call[4]+fonts.vertical_ink(call[0], call[1], call[2])[0],
                          call[3]+fonts.horizontal_ink(call[0], call[1], call[2])[1],
                          call[4]+fonts.vertical_ink(call[0], call[1], call[2])[1])
                 for call in calls if call[-1].a == 255}
          if profile == Profile.LARGE:
            assert ink['SET'][2] < ink['SPEED'][0]
          else:
            assert 'SET' not in ink and 'SPEED' in ink
          assert ink['120'][3] < ink['+10'][1]
          bounds = speed_limit_bounds(profile, current)
          assert bounds is not None
          left, top, right, bottom = bounds
          for label in ('LIMIT', '120', '+10'):
            x1, y1, x2, y2 = ink[label]
            assert left < x1 < x2 < right and top <= y1 < y2 < bottom
          controls = slc_controls(profile, replace(current, slc_prompt_open=True))
          assert ink['120'][3]+4 < controls[0].bounds[1]
  finally:
    if owns_context:
      rl.close_window()


def test_compact_preview_sprite_keeps_the_sign_offset_arrow_and_override_cross():
  import json
  from unittest.mock import patch
  from openpilot.starpilot.ui.layout_preview_renderer import _Canvas, _straight_rgba, sample_state
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, 'SLC preview crop fixture')
  canvas = _Canvas(Profile.COMPACT)
  try:
    for y, scene in product((20, 0, 64, 108), ('slc_pending', 'slc_retained')):
      document = default_document()
      document['layouts']['compact']['speed_limit']['y'] = y
      assert validate_document(document)['layouts']['compact']['speed_limit']['y'] == y
      with patch.dict('openpilot.starpilot.ui.layout_preview_renderer.RUNTIME_PREVIEW_WIDGETS', compact=('speed_limit',)):
        png = canvas.render_widget_art(sample_state(scene, document), document['layouts']['compact'])
      with Image.open(io.BytesIO(png)) as sheet:
        slot = json.loads(sheet.info['starpilot-widget-art'])['sprites']['speed_limit']
        sprite = sheet.crop((slot['x'], slot['y'], slot['x']+slot['width'], slot['y']+slot['height']))
        rebuilt = Image.new('RGBA', Profile.COMPACT.size)
        rebuilt.paste(sprite, (round(330+slot['offsetX']), round(y+slot['offsetY'])))
      image = rl.load_image_from_texture(canvas.target.texture)
      try:
        rl.image_flip_vertical(image)
        direct = np.frombuffer(_straight_rgba(bytes(rl.ffi.buffer(image.data, 536*240*4))), np.uint8).reshape(240, 536, 4)
      finally:
        rl.unload_image(image)
      assert np.array_equal(direct[..., 3], np.asarray(rebuilt)[..., 3])
      assert slot['offsetX'] == slot['offsetY'] == 0
      assert (slot['width'], slot['height']) == (118, min(176, Profile.COMPACT.size[1] - y))
      if scene == 'slc_retained':
        assert np.any(direct[..., 3]), (y, scene)
  finally:
    canvas.close()
    if owns_context:
      rl.close_window()


def test_large_sources_and_confirmation_text_have_clearance_below_both_signs():
  from unittest.mock import patch
  from openpilot.starpilot.ui.large_speed_geometry import CARD_HEIGHT, GAP, SOURCE_ROW_HEIGHT
  from openpilot.starpilot.ui.onroad import OnroadView
  from openpilot.starpilot.ui.onroad_large_widgets import UnifiedSpeedWidget
  from openpilot.starpilot.ui.onroad_state import SourceReading
  from openpilot.starpilot.ui.tests.test_unified_speed_native import state
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, 'Large sign sources and confirmation spacing')
  try:
    with BitmapFonts(Profile.LARGE, default_font_directory()) as fonts:
      widget = UnifiedSpeedWidget(fonts)
      view = OnroadView.__new__(OnroadView)
      view.fonts = fonts
      for vienna, separate in product((False, True), repeat=2):
        current = state(slc_prompt_open=True)
        current.customization.update(speedSources=True, speedSourcesCard=separate)
        current = replace(current, appearance=replace(current.appearance, use_vienna_sign=vienna),
          speed_limit=replace(current.speed_limit, source_readings=tuple(
            SourceReading(source, True, 'valid', 50/3.6) for source in ('dashboard', 'map', 'vision'))))
        calls = []
        with patch.object(fonts, 'draw', lambda *args, sink=calls: sink.append(args)):
          widget.render(rl.Rectangle(30, 30, 1800, 1020), current)
          view._slc_actions(current)
        foreground = [call for call in calls if call[-1].a == 255]
        action_top = min(y+fonts.vertical_ink(text, role, size)[0]
                         for text, role, size, _, y, _ in foreground if text in ('Accept', 'Decline'))
        source_bottom = 75+CARD_HEIGHT+(GAP if separate else 0)+SOURCE_ROW_HEIGHT
        assert source_bottom+8 <= action_top
      widget.close()
  finally:
    if owns_context:
      rl.close_window()


def test_both_sign_styles_contain_text_and_arrows_at_each_profile_scale():
  from unittest.mock import patch
  from openpilot.starpilot.ui.speed_limit_widget import SpeedLimitWidget
  from openpilot.starpilot.ui.tests.test_unified_speed_native import state
  from openpilot.starpilot.ui.speed_limit_shapes import ATLAS_PATH, SPRITES
  glyphs = {}
  with Image.open(ATLAS_PATH) as atlas:
    for size in ('large', 'compact'):
      sx, sy, sw, sh = SPRITES[f'arrow_{size}']
      bbox = atlas.crop((sx, sy, sx+sw, sy+sh)).getchannel('A').point(lambda alpha: 255 if alpha > 40 else 0).getbbox()
      assert bbox is not None
      glyphs[size] = (bbox[0]-sw/2, bbox[1]-sh/2, bbox[2]-sw/2, bbox[3]-sh/2)
  owns_context = not rl.is_window_ready()
  if owns_context:
    rl.init_window(128, 128, 'Contained signs on both device profiles')
  try:
    for profile in Profile:
      with BitmapFonts(profile, default_font_directory()) as fonts:
        widget = SpeedLimitWidget(fonts, profile)
        scale = widget.scale
        positions = ((88, 75), (188, 95), (1642, 882)) if profile == Profile.LARGE else ((330, 20), (100, 0), (358, 108))
        for vienna, (posted, offset), elapsed, (saved_x, y), direction in product(
            (False, True), ((65, 5), (120, 10), (130, -10), (145, -137), (199, -191), (200, -192), (55, 0)),
            (0, 350_000_000, 2_100_000_000), positions, (-1, 1)):
          if not vienna and posted > 145:
            continue
          case = (profile, vienna, posted, offset, elapsed, saved_x, y, direction)
          current = state(observed_ns=10_000_000_000+elapsed)
          key = 'cruise_limits' if profile == Profile.LARGE else 'speed_limit'
          current.customization['layouts'][profile][key].update(x=saved_x, y=y)
          x = saved_x+184 if profile == Profile.LARGE else saved_x
          current = replace(current, speed_mps=(posted+offset+direction*2)/3.6,
            appearance=replace(current.appearance, use_vienna_sign=vienna),
            speed_limit=replace(current.speed_limit, speed_limit_mps=posted/3.6,
              pending_speed_limit_mps=posted/3.6, presentation_adjusted_limit_mps=(posted+offset)/3.6))
          calls = []
          with patch.object(fonts, 'draw', lambda *args, sink=calls: sink.append(args)), \
               patch.object(widget.shapes, 'arrow') as arrow_draw:
            widget.render(current)
          ink = []
          for text, role, size, left, top, color in calls:
            a, b = fonts.horizontal_ink(text, role, size)
            c, d = fonts.vertical_ink(text, role, size)
            box = left+a, top+c, left+b, top+d
            if vienna:
              cx, cy = x+59*scale, y+67*scale
              assert all((px-cx)**2+(py-cy)**2 <= (47*scale)**2
                         for px, py in product((box[0], box[2]), (box[1], box[3]))), case
              # The original compact no-offset numeral carries the manual confirmation pulse.
              # Other Vienna layouts keep black numerals while pulsing the ring.
              expected_color = ((170, 115, 235, 255)
                                if profile == Profile.COMPACT and not offset and elapsed == 350_000_000
                                else (0, 0, 0, 255))
              assert (color.r, color.g, color.b, color.a) == expected_color, case
            else:
              assert x+7*scale <= box[0] < box[2] <= x+111*scale, case
              sign_height = 176 if profile == Profile.COMPACT and offset else 132
              assert y+7*scale <= box[1] < box[3] <= y+(sign_height-7)*scale, case
            ink.append((text, box))
            nominal_size = size/widget.text_scale
            if role == FontRole.BOLD:
              if profile == Profile.COMPACT and not vienna:
                assert nominal_size == (50 if len(text) <= 2 else 42), case
              elif profile == Profile.COMPACT and vienna and not offset:
                assert nominal_size == (58 if len(text) <= 2 else 48), case
              else:
                assert 31.99 <= nominal_size <= (48.01 if len(text)>2 else 54.01) if vienna else nominal_size == 58, case
            elif role == FontRole.MEDIUM:
              if profile == Profile.COMPACT and not vienna:
                assert nominal_size == 30, case
              else:
                assert 23.99 <= nominal_size <= 36.01 if vienna else nominal_size == 36, case
          arrow_draw.assert_called_once()
          size, ax, ay, arrow_direction, _ = arrow_draw.call_args.args
          assert size == ('compact' if vienna else 'large'), case
          assert arrow_direction == direction, case
          glyph = glyphs[size]
          left, top, right, bottom = glyph if direction>0 else (-glyph[2], -glyph[3], -glyph[0], -glyph[1])
          arrow = ax+left*scale, ay+top*scale, ax+right*scale, ay+bottom*scale
          if vienna:
            assert all((px-cx)**2+(py-cy)**2 <= (47*scale)**2
                       for px, py in product((arrow[0], arrow[2]), (arrow[1], arrow[3]))), case
          else:
            assert x+7*scale <= arrow[0] < arrow[2] <= x+111*scale, case
            assert y+7*scale <= arrow[1] < arrow[3] <= y+125*scale, case
            assert all(box[2]+4*scale <= arrow[0] for text, box in ink if text in ('SPEED', 'LIMIT')), (case, ink, arrow)
            assert arrow[3]+6*scale <= next(box[1] for text, box in ink if text==str(posted))
          ink.append(('arrow', arrow))
          for index, (_, a) in enumerate(ink):
            for _, b in ink[index+1:]:
              assert not (a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]), (case, a, b)
        widget.close()
  finally:
    if owns_context:
      rl.close_window()


def test_v5_geometry_migrates_and_keeps_custom_actions_independent():
  doc = default_document()
  doc['version'] = 5
  doc['speedSources'] = True
  doc['layouts']['large']['cruise_limits'].update(x=1550, y=638)
  doc['layouts']['large']['speed_limit_actions'].update(x=1550, y=954)
  migrated = validate_document(doc)
  assert migrated['version'] == 10
  assert migrated['layouts']['large']['cruise_limits'] == {'x': 1550, 'y': 638, 'enabled': True}
  assert migrated['layouts']['large']['speed_limit_actions'] == {'x': 1550, 'y': 902, 'enabled': True}
  assert migrated['speedSources'] is True
  assert doc['layouts']['large']['cruise_limits']['x'] == 1550
  assert validate_document(migrated) == migrated
  doc['layouts']['large']['cruise_limits'].update(x=88, y=75)
  doc['layouts']['large']['speed_limit_actions'].update(x=88, y=447)
  assert validate_document(doc)['layouts']['large']['speed_limit_actions']['y'] == 296


def test_pending_choices_are_plain_accept_and_decline_with_padded_targets():
  state = road()
  state = replace(state, slc_prompt_open=True, speed_limit=replace(state.speed_limit, pending_speed_limit_mps=25))
  accept, decline = slc_controls(Profile.LARGE, state)
  assert accept.bounds == (100, 296, 372, 444)
  assert decline.bounds == (404, 296, 676, 444)
  assert (accept.label, decline.label) == ('Accept', 'Decline')


def test_projection_v1_layout_migrates_without_losing_other_widgets():
  viewport = (2880, 1080)
  doc = default_layout_for_viewport(viewport)
  doc['version'] = 1
  doc['widgets']['speed_limit_actions'].update(x=88, y=447)
  doc['widgets']['current_speed'].update(x=1400, y=100)
  migrated = validate_layout_for_viewport(doc, viewport)
  assert migrated['version'] == 5
  assert migrated['widgets']['speed_limit_actions']['y'] == 296
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
  assert migrated['widgets']['speed_limit_actions'] == {'x': 1254, 'y': 296, 'enabled': True}

