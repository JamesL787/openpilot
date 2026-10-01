"""A cancelled touch (remote control withdrawn) must never act like a release."""
import pyray as rl
import pytest
from types import SimpleNamespace

from openpilot.selfdrive.ui.layouts.settings.starpilot import aethergrid
from openpilot.system.ui import widgets
from openpilot.system.ui.lib import scroll_panel2
from openpilot.system.ui.lib.application import MouseEvent, MousePos, MouseState, gui_app
from openpilot.system.ui.widgets import nav_widget, slider
from openpilot.system.ui.widgets.scroller import _Scroller, ScrollState


class Item(widgets.Widget):
  def __init__(self, rect=(0, 0, 402, 180)):
    super().__init__()
    self.set_rect(rl.Rectangle(*rect))
    self.clicks = 0
    self.cancels = 0
    self.set_click_callback(self._clicked)

  def _clicked(self):
    self.clicks += 1

  def _handle_mouse_cancel(self):
    self.cancels += 1

  def _render(self, _):
    pass


def ev(x, y, *, pressed=False, released=False, down=None, cancelled=False, t=1.0):
  if down is None:
    down = not (released or cancelled)
  return MouseEvent(MousePos(x, y), 0, pressed, released, down, t, cancelled)


@pytest.fixture
def ui(monkeypatch):
  monkeypatch.setattr(rl, "begin_scissor_mode", lambda *args: None)
  monkeypatch.setattr(rl, "end_scissor_mode", lambda: None)
  monkeypatch.setattr(rl, "get_frame_time", lambda: 1 / 60)
  monkeypatch.setattr(rl, "get_time", lambda: 1.0)
  monkeypatch.setattr(rl, "get_mouse_wheel_move", lambda: 0)
  monkeypatch.setattr(gui_app, "texture", lambda *args, **kwargs: rl.Texture())
  monkeypatch.setattr(gui_app, "_show_touches", False)
  monkeypatch.setattr(gui_app, "_mouse_events", [])
  monkeypatch.setattr(widgets, "PC", False)
  monkeypatch.setattr(widgets, "device", SimpleNamespace(awake=True))
  monkeypatch.setattr(scroll_panel2, "TICI", True)

  def run(widget, *events):
    gui_app._mouse_events = list(events)
    widget._process_mouse_events()
  return run


def test_cancel_is_neither_press_nor_release():
  # Code that has never heard of cancel sees the finger go away, nothing more.
  cancel = ev(10, 10, cancelled=True)
  assert (cancel.left_pressed, cancel.left_released, cancel.left_down) == (False, False, False)
  assert MouseEvent(MousePos(0, 0), 0, False, False, False, 0.0).cancelled is False


def test_mouse_state_still_filters_unchanged_touches():
  state = MouseState()
  state._append_mouse_event(ev(1, 1, t=1.0))
  state._append_mouse_event(ev(1, 1, t=2.0))  # same touch, later poll
  assert len(state.get_events()) == 1


def test_cancelled_press_does_not_click(ui):
  item = Item()
  ui(item, ev(100, 100, pressed=True))
  assert item.is_pressed
  ui(item, ev(100, 100, cancelled=True))
  assert item.clicks == 0 and item.cancels == 1 and not item.is_pressed


def test_cancel_leaves_no_press_for_a_later_release_to_complete(ui):
  item = Item()
  ui(item, ev(100, 100, pressed=True), ev(100, 100, cancelled=True))
  ui(item, ev(100, 100, released=True))  # a stray release (e.g. another source)
  assert item.clicks == 0


def test_cancel_only_notifies_the_widget_that_was_pressed(ui):
  pressed, other = Item(), Item((500, 0, 100, 100))
  ui(pressed, ev(100, 100, pressed=True))
  ui(other, ev(100, 100, pressed=True))
  for widget in (pressed, other):
    ui(widget, ev(100, 100, cancelled=True))
  assert (pressed.cancels, other.cancels) == (1, 0)


def test_a_new_tap_after_cancel_still_clicks(ui):
  item = Item()
  ui(item, ev(100, 100, pressed=True), ev(100, 100, cancelled=True))
  ui(item, ev(100, 100, pressed=True), ev(100, 100, released=True))
  assert item.clicks == 1


def test_cancelled_scroll_does_not_fling_or_click(ui):
  items = [Item() for _ in range(8)]
  scroller = _Scroller(items, scroll_indicator=False, edge_shadows=False)
  scroller.set_rect(rl.Rectangle(0, 0, 536, 240))
  scroller.scroll_panel.set_offset(-500)
  scroller.render()

  def frame(*events):
    gui_app._mouse_events = list(events)
    scroller.render()

  frame(ev(200, 100, pressed=True, t=1.0))
  for i in range(1, 6):
    frame(ev(200 - i * 40, 100, t=1.0 + i * 0.01))  # fast swipe
  assert scroller.scroll_panel.state == ScrollState.MANUAL_SCROLL
  offset = scroller.scroll_panel.get_offset()
  frame(ev(0, 100, cancelled=True, t=1.06))
  assert scroller.scroll_panel.state != ScrollState.MANUAL_SCROLL
  assert scroller.scroll_panel._velocity == 0.0
  frame()
  assert scroller.scroll_panel.get_offset() == pytest.approx(offset, abs=1.0)  # no fling
  assert sum(item.clicks for item in items) == 0


class Slider(slider.SliderBase):
  def _load_assets(self):
    pass

  def _render(self, _):
    pass


def test_cancelled_slide_does_not_confirm(ui):
  s = Slider.__new__(Slider)
  widgets.Widget.__init__(s)
  s.set_rect(rl.Rectangle(0, 0, 500, 100))
  s._drag_threshold = -250
  s._confirmed_time = 0.0
  s._start_x_circle = 450.0
  s._is_dragging_circle = True
  s._scroll_x_circle_filter = slider.FirstOrderFilter(0, 0.05, 1 / 60)
  s._handle_mouse_event(ev(50, 50))  # dragged 400 px left: past the confirm threshold
  s._scroll_x_circle_filter.x = s._scroll_x_circle
  s._handle_mouse_cancel()
  assert s._is_dragging_circle is False and s._scroll_x_circle_filter.x == 0.0
  # Every release reaches the slider; one right after the cancel must not confirm.
  s._handle_mouse_event(ev(0, 0, released=True))
  assert s._confirmed_time == 0.0


class Page(nav_widget.NavWidget):
  def _render(self, _):
    pass


def test_cancelled_swipe_down_does_not_dismiss(ui, monkeypatch):
  monkeypatch.setattr(nav_widget.NavWidget, "_back_enabled", lambda self: True)
  page = Page()
  page.set_rect(rl.Rectangle(0, 0, 536, 240))
  page._handle_mouse_event(ev(200, 10, pressed=True))
  page._handle_mouse_event(ev(200, 200))  # well past SWIPE_AWAY_THRESHOLD
  page._handle_mouse_cancel()
  assert page._drag_start_pos is None and not page._playing_dismiss_animation
  # A later gesture that starts outside the dismiss area and ends low must not
  # be measured from the cancelled one's start.
  page._handle_mouse_event(ev(200, 230, pressed=True))
  page._handle_mouse_event(ev(200, 235, released=True))
  assert not page._playing_dismiss_animation


# ------------------------------------------------------------ StarPilot widgets


def test_cancelled_slider_tile_press_cannot_fire_its_long_press_later(monkeypatch):
  # The base widget hands every out-of-rect event to _handle_mouse_event, so a
  # press timer left running would fire on_test() on some later, unrelated touch.
  clock = SimpleNamespace(t=100.0)
  monkeypatch.setattr(aethergrid.time, "monotonic", lambda: clock.t)
  tile = aethergrid.SliderTile.__new__(aethergrid.SliderTile)
  widgets.Widget.__init__(tile)
  tile.set_rect(rl.Rectangle(0, 0, 200, 100))
  tests = []
  tile.on_test = lambda: tests.append(1)
  tile._is_dragging = tile._long_press_triggered = False
  tile._press_start_time = None
  tile._handle_mouse_press(MousePos(50, 50))
  tile._handle_mouse_cancel()
  clock.t += 5.0
  tile._handle_mouse_event(ev(900, 50))  # a later touch elsewhere on screen
  assert tests == []


def test_cancelled_dialog_press_cannot_be_confirmed_by_a_later_release():
  dialog = aethergrid.AetherSliderDialog.__new__(aethergrid.AetherSliderDialog)
  widgets.Widget.__init__(dialog)
  results = []
  dialog._user_callback = lambda result, value: results.append((result, value))
  dialog._on_change = None
  dialog._ok_rect = rl.Rectangle(0, 0, 100, 50)
  dialog._cancel_rect = rl.Rectangle(200, 0, 100, 50)
  dialog._track_rect = rl.Rectangle(0, 100, 300, 20)
  dialog._minus_rect = dialog._plus_rect = rl.Rectangle(-100, -100, 1, 1)
  dialog._preset_rects = []
  dialog._pressed_zone = None
  dialog._is_pressed_ok = dialog._is_pressed_cancel = dialog._is_dragging = False
  dialog._current_val = 5.0
  dialog._handle_mouse_press(MousePos(50, 25))  # on OK
  assert dialog._is_pressed_ok
  dialog._current_val = 9.0  # as if a drag had moved it
  dialog._handle_mouse_cancel()
  dialog._handle_mouse_release(MousePos(50, 25))  # a later release over OK
  assert results == [] and dialog._current_val == 5.0


def test_cancelled_stepper_hold_reverts_the_value():
  # +/- auto-repeat while held; a withdrawn hold must not keep what it added.
  control = aethergrid.AetherInlineRangeControl.__new__(aethergrid.AetherInlineRangeControl)
  changes = []
  control._on_change = changes.append
  control.reset_interaction()
  control._value_at_press = 3.0
  control.current_val = 7.0  # after a few repeats
  control._pressed_button = 1
  control._handle_mouse_cancel()
  assert control.current_val == 3.0 and changes == [3.0] and control._pressed_button == 0
