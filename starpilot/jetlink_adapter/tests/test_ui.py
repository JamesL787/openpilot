"""The words the settings panels show, and the parked-only rule."""
import types

import pytest

from openpilot.starpilot.jetlink_adapter import summary


def status(**kw):
  base = dict(enabled=True, mode="usb", transport="USB", present=True, port="host", ready=True, reason=None, progress=None,
              model="Cinque Terre V3", default_model="Cinque Terre V3", standin=None)
  base.update(kw)
  s = types.SimpleNamespace(**base)
  s.runnable = s.ready or s.standin is not None
  return s


def test_not_installed():
  assert summary.describe(None) == "Not installed"


def test_off_and_off_beside_a_chestnut():
  assert summary.describe(status(enabled=False, mode="off")) == "Off"
  assert summary.describe(status(enabled=False, mode="usb")) == "Off (Chestnut fitted)"


def test_an_unusable_link_leads_with_the_reason():
  assert summary.describe(status(reason="no warp built for this camera")) == "Unavailable: no warp built for this camera"


def test_while_driving_it_says_which_model_drives_and_how_late_it_is():
  live = {"backend": "jetlink", "accelerator": "running", "held_frames": 0, "remote_model": "Cinque Terre V3"}
  assert summary.describe(status(), live) == "Driving on Cinque Terre V3"
  assert summary.describe(status(), {**live, "held_frames": 2}) == "Driving on Cinque Terre V3 (2 held)"


@pytest.mark.parametrize("state,words", [("ready", "Ready: disengage to switch"), ("joining", "Connecting"),
                                         ("retrying", "Reconnecting"), ("unavailable", "Unavailable this drive")])
def test_while_the_local_model_drives(state, words):
  assert summary.describe(status(), {"backend": "local", "accelerator": state, "held_frames": 0, "remote_model": ""}) == words


def test_the_reason_a_join_is_not_up_is_shown_with_its_state():
  live = {"backend": "local", "accelerator": "retrying", "held_frames": 0, "remote_model": "", "reason": "lost jetlink"}
  assert summary.describe(status(), live) == "Reconnecting (lost jetlink)"
  assert summary.describe(status(), {**live, "accelerator": "joining", "reason": "UnsupportedModel: x"}) == "Connecting (UnsupportedModel: x)"
  assert summary.describe(status(), {**live, "accelerator": "unavailable", "reason": "3 handbacks"}) == "Unavailable this drive: 3 handbacks"


def test_parked_states():
  assert summary.describe(status(present=False, port=None)) == "Waiting for the host"
  assert summary.describe(status(present=False, port="empty")) == "Waiting for the host (nothing on the USB port)"
  assert summary.describe(status(present=False)) == "Waiting for the host (a device is on the USB port)"
  assert summary.describe(status(present=False, progress={"msg": "downloaded, builds when the jetson is on"})) == \
    "Downloaded, builds when the jetson is on (a device is on the USB port)"
  assert summary.describe(status(progress={"msg": "building the engine"})) == "Building the engine"
  assert summary.describe(status(ready=False)) == "Host connected, model not built yet"
  assert summary.describe(status()) == "Ready"


def test_the_port_line():
  assert summary.port_line(None) == ""
  assert summary.port_line(status(transport="iOS over USB (192.168.60.2)")) == "Jetlink connected: iOS over USB (192.168.60.2)"
  assert summary.port_line(status(present=False, port="empty")) == "Nothing on the USB port"
  assert summary.port_line(status(present=False)) == "A device is on the USB port, not connected"
  assert summary.port_line(status(present=False, port=None)) == ""


def test_the_setting_label_names_each_mode():
  from openpilot.starpilot import jetlink_adapter as ja
  assert summary.setting_label("usb", ja.SUPPORTED_MODES) == "USB"
  assert summary.setting_label("ios", ja.SUPPORTED_MODES) == "iOS"
  assert "unsupported" in summary.setting_label("ios", ("off", "usb"))


class TestTheTiles:
  def test_the_panel_is_registered_under_driving_controls_and_navigation_tests_still_hold(self):
    from openpilot.selfdrive.ui.layouts.settings.starpilot.main_panel import StarPilotLayout
    from openpilot.selfdrive.ui.layouts.settings.starpilot.panel import StarPilotPanelType
    controls = next(c for c in StarPilotLayout.CATEGORIES if c["title"] == "Driving Controls")
    leaf = next(c for c in controls["children"] if c["title"] == "Jetlink")
    assert leaf["panel"] == "JETLINK" and StarPilotLayout.PANEL_TYPE_MAP["JETLINK"] == StarPilotPanelType.JETLINK

  def test_the_link_cycles_off_usb_ios_only_while_parked(self, monkeypatch):
    from openpilot.selfdrive.ui.layouts.settings.starpilot import jetlink as panel
    from openpilot.starpilot import jetlink_adapter as ja
    written, stored = [], ["off"]

    class FakeParams:
      def put_int(self, key, value):
        written.append((key, value))
        stored[0] = ja.MODES[value]
    monkeypatch.setattr(panel, "Params", FakeParams)
    monkeypatch.setattr(panel.jetlink_adapter, "stored_mode", lambda: stored[0])
    monkeypatch.setattr(panel.ui_state, "started", True, raising=False)
    panel._next_mode()
    assert written == []                                   # driving: refused
    monkeypatch.setattr(panel.ui_state, "started", False, raising=False)
    seen = []
    for _ in range(3):
      panel._next_mode()
      seen.append(panel._mode_line())
    assert seen == ["USB", "iOS", "Off"]
    assert [v for _, v in written] == [ja.MODES.index("usb"), ja.MODES.index("ios"), ja.MODES.index("off")]

  def test_the_mici_button_cycles_the_same_modes(self):
    from openpilot.selfdrive.ui.mici.layouts.settings import jetlink as mici
    assert [mici.next_mode(m) for m in ("off", "usb", "ios", "bogus")] == ["usb", "ios", "off", "off"]

  def test_the_toggle_is_unavailable_while_driving_or_beside_a_chestnut(self, monkeypatch):
    from openpilot.selfdrive.ui.layouts.settings.starpilot import jetlink as panel
    monkeypatch.setattr(panel.jetlink_adapter, "status_cached", lambda: object())
    monkeypatch.setattr(panel.ui_state, "usbgpu", False, raising=False)
    monkeypatch.setattr(panel.ui_state, "started", False, raising=False)
    assert panel._toggle_enabled() is True
    monkeypatch.setattr(panel.ui_state, "started", True, raising=False)
    assert panel._toggle_enabled() is False
    monkeypatch.setattr(panel.ui_state, "started", False, raising=False)
    monkeypatch.setattr(panel.ui_state, "usbgpu", True, raising=False)
    assert panel._toggle_enabled() is False
