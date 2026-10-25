from unittest.mock import Mock, patch

import pyray as rl
import pytest
from types import SimpleNamespace

from openpilot.selfdrive.ui.mici.onroad.augmented_road_view import AugmentedRoadView
from openpilot.selfdrive.ui.onroad import model_source
from openpilot.selfdrive.ui.ui_state import ChestnutState, UIState


@pytest.mark.parametrize('raw, expected', [(True, True), (False, False), (b'1', True), (b'0', False),
                                          ('1', True), ('0', False), (None, None), (b'invalid', None)])
def test_native_chestnut_status_accepts_typed_params(raw, expected):
  params = Mock()
  params.get.return_value = raw
  params.get_bool.return_value = False
  state = Mock(spec=UIState, params=params, started=True, chestnut_compiled=True, usb_connected=False)
  with patch('openpilot.selfdrive.ui.ui_state.get_cache', return_value=None), \
       patch('openpilot.selfdrive.ui.ui_state.cable_connected', return_value=False):
    UIState.update_params(state)
  assert state.chestnut_active is expected


@pytest.mark.parametrize('indicator', [False, None])
def test_custom_model_source_layer_uses_native_status_animation(indicator):
  view = Mock(spec=AugmentedRoadView, _hud_renderer=Mock(), _long_indicator=Mock())
  rect = rl.Rectangle(0, 0, 476, 240)
  AugmentedRoadView.render_model_source_layer(view, rect, show_long_indicator=indicator)
  view._hud_renderer._draw_model_source.assert_called_once_with(rect)
  if indicator is None:
    view._long_indicator.set_should_draw.assert_not_called()
    view._long_indicator.render.assert_not_called()
  else:
    view._long_indicator.set_should_draw.assert_called_once_with(False)
    view._long_indicator.render.assert_called_once_with(rect)


@pytest.mark.parametrize('compiled', [False, True])
@pytest.mark.parametrize('prior', [ChestnutState.UNCOMPILED, ChestnutState.FAILED, ChestnutState.LOADING])
def test_catalog_gpu_output_does_not_require_retired_bundled_artifact(compiled, prior):
  sm = Mock()
  sm.__getitem__ = Mock(side_effect=lambda service: SimpleNamespace(chestnutPresent=True) if service == 'deviceState' else SimpleNamespace(big=True))
  sm.recv_frame = {'modelV2': 12}
  sm.logMonoTime = {'modelV2': 1_000_000_000}
  sm.valid = {'modelV2': True}
  sm.alive = {'modelV2': True}
  state = Mock(spec=UIState, sm=sm, started=True, started_frame=10, chestnut_present=True, chestnut_compiled=compiled,
                          chestnut_loading=False, chestnut_active=True, chestnut_state=prior)
  with patch('openpilot.selfdrive.ui.ui_state.time.monotonic_ns', return_value=1_100_000_000):
    UIState._update_chestnut_state(state)
  assert state.chestnut_state == ChestnutState.ACTIVE


@pytest.mark.parametrize('big, valid, alive, age, active', [(False, True, True, 100_000_000, False),
                                                         (True, False, True, 100_000_000, True),
                                                         (True, True, False, 100_000_000, True),
                                                         (True, True, True, 300_000_000, True)])
def test_catalog_gpu_fallback_or_stale_output_stays_failed(big, valid, alive, age, active):
  sm = Mock()
  sm.__getitem__ = Mock(side_effect=lambda service: SimpleNamespace(chestnutPresent=True) if service == 'deviceState' else SimpleNamespace(big=big))
  sm.recv_frame = {'modelV2': 12}
  sm.logMonoTime = {'modelV2': 1_000_000_000}
  sm.valid = {'modelV2': valid}
  sm.alive = {'modelV2': alive}
  state = Mock(spec=UIState, sm=sm, started=True, started_frame=10, chestnut_present=True, chestnut_compiled=False,
                          chestnut_loading=False, chestnut_active=active, chestnut_output_seen=True, chestnut_state=ChestnutState.ACTIVE)
  with patch('openpilot.selfdrive.ui.ui_state.time.monotonic_ns', return_value=1_000_000_000 + age):
    UIState._update_chestnut_state(state)
  assert state.chestnut_state == ChestnutState.FAILED


@pytest.mark.parametrize('detected,installed,checking,expected', [
  (True, True, False, ChestnutState.READY),
  (True, False, True, ChestnutState.LOADING),
  (True, False, False, ChestnutState.UNCOMPILED),
  (False, True, False, ChestnutState.DISCONNECTED),
])
def test_offroad_status_uses_selected_download(detected, installed, checking, expected):
  sm = Mock()
  sm.__getitem__ = Mock(return_value=SimpleNamespace(chestnutPresent=detected))
  state = Mock(spec=UIState, sm=sm, started=False, chestnut_alert=False, chestnut_compiled=installed, chestnut_checking=checking)
  UIState._update_chestnut_state(state)
  assert state.chestnut_state == expected


def test_offroad_selection_rechecks_without_a_ui_restart():
  params = Mock()
  params.get.return_value = None
  params.get_bool.return_value = False
  artifacts = Mock()
  artifacts.selected_gpu_status.side_effect = [(False, True), (True, False), (False, False)]
  state = Mock(spec=UIState, params=params, started=False, _gpu_artifacts=artifacts, _gpu_artifacts_at=None,
               usb_connected=False)
  with patch('openpilot.selfdrive.ui.ui_state.get_cache', return_value=None), \
       patch('openpilot.selfdrive.ui.ui_state.cable_connected', return_value=False), \
       patch('openpilot.selfdrive.ui.ui_state.time.monotonic', side_effect=[1., 1.2, 2., 3., 4.]):
    UIState.update_params(state)
    assert state.chestnut_checking and not state.chestnut_compiled
    UIState.update_params(state)
    artifacts.selected_gpu_status.assert_called_once()
    UIState.update_params(state)
    assert state.chestnut_compiled and not state.chestnut_checking
    UIState.update_params(state)
    assert not state.chestnut_compiled and not state.chestnut_checking
    state.started = True
    UIState.update_params(state)
    assert artifacts.selected_gpu_status.call_count == 3


@pytest.fixture(params=[1, 3])
def source(request, monkeypatch):
  monkeypatch.setattr(model_source.gui_app, 'texture', lambda path, width, height: SimpleNamespace(path=path, width=width, height=height))
  ui = SimpleNamespace(started_frame=10, chestnut_present=True, chestnut_output_seen=False, chestnut_state=ChestnutState.LOADING,
                       chestnut_loading=False, chestnut_active=False, replay_clock=None)
  ui.sm = Mock(recv_frame={'carState': 12, 'modelV2': 12})
  ui.sm.__getitem__ = Mock(return_value=SimpleNamespace(enabled=False))
  clock, draw = Mock(return_value=10.), Mock()
  monkeypatch.setattr(model_source, 'ui_state', ui)
  monkeypatch.setattr(rl, 'get_time', clock)
  monkeypatch.setattr(rl, 'draw_texture_ex', draw)
  return SimpleNamespace(widget=model_source.ModelSource(scale=request.param), ui=ui, clock=clock, draw=draw, scale=request.param)


@pytest.mark.parametrize('state,small_engaged,texture', [
  (ChestnutState.LOADING, False, '_loading'),
  (ChestnutState.LOADING, True, '_loading'),
  (ChestnutState.ACTIVE, False, '_active'),
  (ChestnutState.UNCOMPILED, False, '_failed'),
  (ChestnutState.FAILED, False, '_failed'),
  (ChestnutState.FAILED, True, '_fallback'),
  (ChestnutState.DISCONNECTED, True, '_fallback'),
  (ChestnutState.ACTIVE, True, '_active'),
])
def test_shared_gpu_icons_and_alignment(source, state, small_engaged, texture):
  source.ui.chestnut_state = state
  source.widget._small_model_engaged = small_engaged
  rect = rl.Rectangle(30, 30, 2070, 1020)
  source.widget._render(rect)
  icon, pos = source.draw.call_args.args[:2]
  assert icon is getattr(source.widget, texture)
  assert pos.x + icon.width == rect.x + rect.width
  assert pos.y + icon.height / 2 == rect.y + rect.height / 2
  assert icon.width == (75 if texture == '_failed' else 60) * source.scale
  assert icon.height == (52 if texture == '_fallback' else 44) * source.scale


@pytest.mark.parametrize('state', [ChestnutState.DISCONNECTED, ChestnutState.READY])
def test_shared_gpu_icon_hidden_without_a_status(source, state):
  source.ui.chestnut_state = state
  source.widget._render(rl.Rectangle(0, 0, 476, 240))
  source.draw.assert_not_called()


def test_shared_gpu_loading_pulses_without_disappearing(source):
  import math

  source.widget._alpha_filter.x = 1.
  source.clock.return_value = 0.
  source.widget._render(rl.Rectangle(0, 0, 476, 240))
  low = source.draw.call_args.args[-1].a
  source.clock.return_value = math.pi / 6
  source.widget._render(rl.Rectangle(0, 0, 476, 240))
  high = source.draw.call_args.args[-1].a
  assert 0 < low < high == 255


@pytest.mark.parametrize('state', [ChestnutState.LOADING, ChestnutState.ACTIVE, ChestnutState.FAILED])
def test_shared_gpu_loading_persists_and_other_states_fade(source, state):
  source.ui.chestnut_state = state
  rect = rl.Rectangle(0, 0, 476, 240)
  source.widget._render(rect)
  source.clock.return_value = 13.
  for _ in range(120):
    source.widget._render(rect)
  source.draw.reset_mock()
  source.widget._render(rect)
  assert source.draw.called == (state == ChestnutState.LOADING)
  source.ui.chestnut_state = ChestnutState.ACTIVE if state == ChestnutState.FAILED else ChestnutState.FAILED
  source.widget._render(rect)
  assert source.draw.call_args.args[0] is (source.widget._active if state == ChestnutState.FAILED else source.widget._failed)


@pytest.mark.parametrize('recv_frame,loading,active,expected', [(9, False, False, False), (12, True, False, False),
                                                           (12, False, True, False), (12, False, False, True)])
def test_shared_gpu_marks_small_model_on_engagement(source, recv_frame, loading, active, expected):
  source.ui.sm.recv_frame['modelV2'] = recv_frame
  source.ui.sm.__getitem__.return_value.enabled = True
  source.ui.chestnut_loading, source.ui.chestnut_active = loading, active
  source.widget._update_state()
  assert source.widget._small_model_engaged is expected


@pytest.mark.parametrize('present,detected', [(False, False), (True, True), (True, False)])
@pytest.mark.parametrize('active', [False, None])
def test_gpu_fallback_on_engagement_requires_chestnut_for_this_drive(source, present, detected, active):
  ui = source.ui
  ui.started, ui.replay_clock = True, None
  ui.chestnut_present, ui.chestnut_output_seen, ui.chestnut_active = present, present, active
  ui.sm.__getitem__.return_value = SimpleNamespace(chestnutPresent=detected, enabled=False, big=False)
  ui.sm.logMonoTime = {'modelV2': 1_000_000_000}
  ui.sm.valid = ui.sm.alive = {'modelV2': True}
  with patch('openpilot.selfdrive.ui.ui_state.time.monotonic_ns', return_value=1_100_000_000):
    UIState._update_chestnut_state(ui)
  assert ui.chestnut_state == (ChestnutState.FAILED if present else ChestnutState.DISCONNECTED)
  assert ui.chestnut_present is present
  for now, engaged in ((10., False), (14., True), (18., False), (22., True)):
    source.clock.return_value = now
    ui.sm.__getitem__.return_value.enabled = engaged
    source.draw.reset_mock()
    source.widget._update_state()
    source.widget._render(rl.Rectangle(30, 30, 2100, 1020))
    if not present:
      source.draw.assert_not_called()
    elif engaged:
      assert source.draw.call_args.args[0] is source.widget._fallback


def test_gpu_fallback_clears_before_next_drive_without_chestnut(source):
  source.ui.chestnut_state = ChestnutState.FAILED
  source.ui.chestnut_output_seen = True
  source.ui.sm.__getitem__.return_value.enabled = True
  rect = rl.Rectangle(30, 30, 2100, 1020)
  source.widget._update_state()
  source.widget._render(rect)
  assert source.draw.call_args.args[0] is source.widget._fallback
  source.ui.chestnut_present = False
  source.ui.chestnut_output_seen = False
  source.ui.chestnut_state = ChestnutState.DISCONNECTED
  source.ui.started_frame = 20
  source.ui.sm.recv_frame = {'carState': 22, 'modelV2': 22}
  for now, engaged in ((20., False), (24., True)):
    source.clock.return_value = now
    source.ui.sm.__getitem__.return_value.enabled = engaged
    source.draw.reset_mock()
    source.widget._update_state()
    source.widget._render(rect)
    source.draw.assert_not_called()
  source.ui.chestnut_present = True
  source.ui.chestnut_state = ChestnutState.FAILED
  source.ui.started_frame = 30
  source.ui.sm.recv_frame = {'carState': 32, 'modelV2': 32}
  for now, engaged, icon in ((30., False, '_failed'), (34., True, '_fallback')):
    source.clock.return_value = now
    source.ui.sm.__getitem__.return_value.enabled = engaged
    source.draw.reset_mock()
    source.widget._update_state()
    source.widget._render(rect)
    assert source.draw.call_args.args[0] is getattr(source.widget, icon)


@pytest.mark.parametrize('replay', [False, True])
@pytest.mark.parametrize('initial', [ChestnutState.LOADING, ChestnutState.ACTIVE])
def test_gpu_disconnect_warning_survives_lost_presence_during_same_drive(source, replay, initial):
  ui = source.ui
  ui.started, ui.replay_clock = True, object() if replay else None
  ui.replay_sample = SimpleNamespace(valid=True, now_ns=1_100_000_000)
  ui.chestnut_output_seen = False
  ui.chestnut_loading = initial == ChestnutState.LOADING
  ui.sm.__getitem__.return_value = SimpleNamespace(chestnutPresent=True, enabled=False, big=initial == ChestnutState.ACTIVE)
  ui.sm.logMonoTime = {'modelV2': 1_000_000_000}
  ui.sm.valid = {'modelV2': initial == ChestnutState.ACTIVE}
  ui.sm.alive = {'modelV2': True}
  rect = rl.Rectangle(30, 30, 2100, 1020)
  with patch('openpilot.selfdrive.ui.ui_state.time.monotonic_ns', return_value=1_100_000_000):
    UIState._update_chestnut_state(ui)
    assert ui.chestnut_state == initial
    source.widget._update_state()
    source.widget._render(rect)
    ui.sm.__getitem__.return_value = SimpleNamespace(chestnutPresent=False, enabled=True, big=False)
    ui.sm.valid['modelV2'] = True
    ui.chestnut_loading, ui.chestnut_active = False, False
    UIState._update_chestnut_state(ui)
  assert ui.chestnut_state == (ChestnutState.DISCONNECTED if replay else ChestnutState.FAILED)
  source.draw.reset_mock()
  source.widget._update_state()
  source.widget._render(rect)
  assert source.draw.call_args.args[0] is source.widget._fallback


@pytest.mark.parametrize('had_gpu', [False, True])
def test_replay_gpu_fallback_after_returning_to_onroad(source, had_gpu):
  ui = source.ui
  ui.started, ui.replay_clock = True, object()
  ui.chestnut_present = had_gpu
  ui.replay_sample = SimpleNamespace(valid=True, now_ns=1_100_000_000)
  ui.sm.logMonoTime = {'modelV2': 1_000_000_000}
  ui.sm.valid = ui.sm.alive = {'modelV2': True}
  ui.sm.__getitem__.return_value = SimpleNamespace(chestnutPresent=had_gpu, enabled=False, big=had_gpu)
  UIState._update_chestnut_state(ui)
  assert ui.chestnut_state == (ChestnutState.ACTIVE if had_gpu else ChestnutState.DISCONNECTED)
  assert ui.chestnut_output_seen is had_gpu
  ui.sm.__getitem__.return_value = SimpleNamespace(chestnutPresent=False, enabled=True, big=False)
  UIState._update_chestnut_state(ui)
  assert ui.chestnut_state == ChestnutState.DISCONNECTED
  assert ui.chestnut_output_seen is had_gpu
  source.widget._update_state()
  source.widget._render(rl.Rectangle(30, 30, 2100, 1020))
  if had_gpu:
    source.draw.assert_called_once()
    assert source.draw.call_args.args[0] is source.widget._fallback
  else:
    source.draw.assert_not_called()


@pytest.mark.parametrize('active', [False, None])
def test_gpu_output_without_chestnut_does_not_show_live_fallback(source, active):
  ui = source.ui
  ui.started, ui.chestnut_present, ui.chestnut_active = True, False, active
  ui.sm.logMonoTime = {'modelV2': 1_000_000_000}
  ui.sm.valid = ui.sm.alive = {'modelV2': True}
  ui.sm.__getitem__.return_value = SimpleNamespace(chestnutPresent=False, enabled=True, big=True)
  with patch('openpilot.selfdrive.ui.ui_state.time.monotonic_ns', return_value=1_100_000_000):
    UIState._update_chestnut_state(ui)
  assert ui.chestnut_state == ChestnutState.DISCONNECTED and ui.chestnut_output_seen
  source.widget._update_state()
  source.widget._render(rl.Rectangle(30, 30, 2100, 1020))
  source.draw.assert_not_called()


def test_compact_gpu_layer_keeps_original_position():
  from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer

  hud = HudRenderer.__new__(HudRenderer)
  hud._model_source = Mock()
  hud._draw_model_source(rl.Rectangle(20, 8, 476, 240))
  rect = hud._model_source.render.call_args.args[0]
  assert (rect.x + rect.width, rect.y + rect.height / 2) == (486, 209)


def test_startup_invalid_big_frame_remains_loading_until_first_valid_output():
  sm = Mock()
  sm.__getitem__ = Mock(side_effect=lambda service: SimpleNamespace(chestnutPresent=True) if service == 'deviceState' else SimpleNamespace(big=True))
  sm.recv_frame = {'modelV2': 12}
  sm.logMonoTime = {'modelV2': 1_000_000_000}
  sm.valid = {'modelV2': False}
  sm.alive = {'modelV2': True}
  state = Mock(spec=UIState, sm=sm, started=True, started_frame=10, chestnut_present=True, chestnut_compiled=True,
               chestnut_loading=False, chestnut_active=True, chestnut_output_seen=False, chestnut_state=ChestnutState.LOADING)
  with patch('openpilot.selfdrive.ui.ui_state.time.monotonic_ns', return_value=1_100_000_000):
    UIState._update_chestnut_state(state)
    assert state.chestnut_state == ChestnutState.LOADING
    assert not state.chestnut_output_seen
    sm.valid['modelV2'] = True
    state.chestnut_active = False
    UIState._update_chestnut_state(state)
    assert state.chestnut_state == ChestnutState.ACTIVE
    assert state.chestnut_output_seen
    sm.valid['modelV2'] = False
    UIState._update_chestnut_state(state)
    assert state.chestnut_state == ChestnutState.FAILED


def test_initial_valid_small_output_is_failed_despite_loaded_big_marker():
  sm = Mock()
  sm.__getitem__ = Mock(side_effect=lambda service: SimpleNamespace(chestnutPresent=True) if service == 'deviceState' else SimpleNamespace(big=False))
  sm.recv_frame = {'modelV2': 12}
  sm.logMonoTime = {'modelV2': 1_000_000_000}
  sm.valid = {'modelV2': True}
  sm.alive = {'modelV2': True}
  state = Mock(spec=UIState, sm=sm, started=True, started_frame=10, chestnut_present=True, chestnut_compiled=True,
               chestnut_loading=True, chestnut_active=True, chestnut_output_seen=False, chestnut_state=ChestnutState.LOADING)
  with patch('openpilot.selfdrive.ui.ui_state.time.monotonic_ns', return_value=1_100_000_000):
    UIState._update_chestnut_state(state)
  assert state.chestnut_state == ChestnutState.FAILED


@pytest.mark.parametrize('state,small_engaged,texture', [
  (ChestnutState.LOADING, False, 'white'),
  (ChestnutState.ACTIVE, False, 'green'),
  (ChestnutState.FAILED, False, 'orange'),
  (ChestnutState.UNCOMPILED, False, 'orange'),
  (ChestnutState.FAILED, True, 'crossed'),
  (ChestnutState.ACTIVE, True, 'green'),
])
def test_large_hud_gpu_icons_match_mici_states(state, small_engaged, texture):
  # the 3X (LARGE) HUD carries the mici Chestnut icon, at the physical size of vfn's Big UI GPU widget
  from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer

  icons = {key: SimpleNamespace(name=key, width=240, height=176) for key in ('white', 'green', 'orange', 'crossed')}
  renderer = Mock(spec=HudRenderer, _small_model_engaged=small_engaged,
                  _txt_chestnut=icons['white'], _txt_chestnut_green=icons['green'],
                  _txt_chestnut_orange=icons['orange'], _txt_chestnut_crossed=icons['crossed'])
  renderer._chestnut_alpha_filter = Mock()
  renderer._chestnut_alpha_filter.update.return_value = 1.
  renderer._chestnut_drive_frame = None
  box = rl.Rectangle(1942, 285, 144, 144)  # under the default 192 px wheel
  for now in (10., 1000.):  # steady: no fade-out however long the state holds
    with patch('openpilot.selfdrive.ui.onroad.hud_renderer.ui_state', SimpleNamespace(chestnut_state=state, chestnut_present=True, replay_clock=None,
                                                                                    chestnut_output_seen=False, started_frame=1)), \
         patch('openpilot.selfdrive.ui.onroad.hud_renderer.rl.get_time', return_value=now), \
         patch('openpilot.selfdrive.ui.onroad.hud_renderer.rl.draw_texture_ex') as draw:
      HudRenderer._draw_model_source(renderer, rl.Rectangle(0, 0, 2160, 1080))
      assert draw.call_args.args[0] is icons[texture]
      assert draw.call_args.args[1].x == 2160 - 30 - 240 and draw.call_args.args[1].y == 1080 - 30 - 176
      HudRenderer._draw_model_source(renderer, rl.Rectangle(0, 0, 2160, 1080), box)
      icon, pos, _, scale = draw.call_args.args[:4]
      assert icon is icons[texture] and scale == pytest.approx(0.6)
      assert pos.x == pytest.approx(1942) and pos.y == pytest.approx(285 + (144 - 176 * 0.6) / 2)
      if state != ChestnutState.LOADING and not (small_engaged and state == ChestnutState.FAILED):
        assert draw.call_args.args[4].a == 255


def test_large_hud_draws_nothing_without_chestnut():
  from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer
  renderer = Mock(spec=HudRenderer, _small_model_engaged=False, _chestnut_drive_frame=None)
  renderer._chestnut_alpha_filter = Mock()
  with patch('openpilot.selfdrive.ui.onroad.hud_renderer.ui_state', SimpleNamespace(
         chestnut_state=ChestnutState.DISCONNECTED, chestnut_present=False, replay_clock=None, chestnut_output_seen=False,
         started_frame=1)), \
       patch('openpilot.selfdrive.ui.onroad.hud_renderer.rl.draw_texture_ex') as draw:
    HudRenderer._draw_model_source(renderer, rl.Rectangle(0, 0, 2160, 1080))
  draw.assert_not_called()


def test_large_model_source_layer_uses_hud_icon():
  from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView as LargeRoadView
  view = Mock(spec=LargeRoadView, _hud_renderer=Mock())
  rect = rl.Rectangle(0, 0, 2160, 1080)
  box = rl.Rectangle(1942, 285, 144, 144)
  LargeRoadView.render_model_source_layer(view, rect, box)
  view._hud_renderer._update_state.assert_called_once_with()
  view._hud_renderer._draw_model_source.assert_called_once_with(rect, box)


def test_model_source_box_sits_under_the_wheel_glyph_and_follows_the_layout():
  from openpilot.starpilot.ui import onroad_large_widgets as widgets
  state = SimpleNamespace(customization={})
  content = rl.Rectangle(0, 0, 2160, 1080)
  with patch.object(widgets, 'offset', return_value=(0, 0)), patch.object(widgets, 'widget_size', return_value=(192, 192)):
    wheel = widgets.wheel_box(content, state)
    box = widgets.model_source_box(content, state)
  assert (wheel.x, wheel.y, wheel.width) == (2160 - 146 - 96, 45, 192)
  assert (box.x, box.y, box.width, box.height) == (wheel.x + 24, 45 + 192 + 24, 144, 144)
  with patch.object(widgets, 'offset', return_value=(-40, 10)), patch.object(widgets, 'widget_size', return_value=(160, 160)):
    moved = widgets.model_source_box(content, state)
  assert (moved.x, moved.y, moved.width) == (2160 - 146 - 96 - 40 + 20, 55 + 160 + 24, 120)
