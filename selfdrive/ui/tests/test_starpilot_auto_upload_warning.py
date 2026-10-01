import importlib
from types import SimpleNamespace

import pytest

from openpilot.system.ui.widgets import DialogResult

MODULES = ["openpilot.selfdrive.ui.layouts.settings.starpilot.system_settings",
           "openpilot.starpilot.system.starpilot_auto.ui.settings_panels.starpilot.system_settings"]


class FakeParams:
  def __init__(self, **values):
    self.values = values

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def put_bool(self, key, value):
    self.values[key] = bool(value)


@pytest.fixture(params=MODULES)
def layout(request, monkeypatch):
  module = importlib.import_module(request.param)
  dialogs = []
  monkeypatch.setattr(module, "ConfirmDialog", lambda text, confirm, callback=None, **_: SimpleNamespace(text=text, callback=callback))
  monkeypatch.setattr(module.gui_app, "push_widget", dialogs.append)

  def make(**values):
    page = module.StarPilotSystemLayout.__new__(module.StarPilotSystemLayout)
    page._params = FakeParams(**values)
    return page, dialogs
  return make


@pytest.mark.parametrize("answer, expected", [(DialogResult.CONFIRM, False), (DialogResult.CANCEL, True)])
def test_turning_uploads_back_on_with_starpilot_auto_asks_first(layout, answer, expected):
  page, dialogs = layout(StarpilotAutoEnabled=True, NoUploads=True)
  page._on_no_uploads_toggle(False)
  assert len(dialogs) == 1 and "Starpilot Auto is on" in dialogs[0].text
  assert page._params.values["NoUploads"] is True, "nothing changes until the user answers"
  dialogs[0].callback(answer)
  assert page._params.values["NoUploads"] is expected


def test_turning_off_device_settings_with_starpilot_auto_asks_first(layout):
  page, dialogs = layout(StarpilotAutoEnabled=True, DeviceManagement=True)
  page.handle_action("DeviceManagement")
  assert len(dialogs) == 1 and page._params.values["DeviceManagement"] is True
  dialogs[0].callback(DialogResult.CONFIRM)
  assert page._params.values["DeviceManagement"] is False


def test_no_warning_without_starpilot_auto(layout):
  page, dialogs = layout(StarpilotAutoEnabled=False, NoUploads=True, DeviceManagement=True)
  page._on_no_uploads_toggle(False)
  page.handle_action("DeviceManagement")
  assert dialogs == []
  assert page._params.values["NoUploads"] is False and page._params.values["DeviceManagement"] is False
