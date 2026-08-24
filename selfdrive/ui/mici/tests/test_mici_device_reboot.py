from openpilot.selfdrive.ui.mici.layouts.settings import device


class FakeParams:
  def __init__(self):
    self.writes = []

  def put_bool(self, key, value):
    self.writes.append((key, value))

  def put_bool_nonblocking(self, *_args, **_kwargs):
    raise AssertionError("reboot command must be written synchronously")


class FakeHardware:
  def __init__(self, error=None):
    self.error = error
    self.reboot_calls = 0

  def reboot(self):
    self.reboot_calls += 1
    if self.error is not None:
      raise self.error


def test_user_reboot_is_allowed_onroad(monkeypatch):
  # DoReboot is deferred by manager.py's should_defer_reboot() whenever started/ignition is
  # true -- the normal state for someone sitting in the car adjusting settings. Confirmed live
  # against a real device (2026-08-24): should_defer_reboot("DoReboot", started=False,
  # ignition=True) returns True (silently swallowed, no on-screen feedback), while
  # should_defer_reboot("DoUserReboot", ...) never defers. This must write DoUserReboot and
  # call HARDWARE.reboot() directly, matching the standard UI's _perform_reboot.
  hardware = FakeHardware()
  monkeypatch.setattr(device, "HARDWARE", hardware)
  fake_params = FakeParams()
  monkeypatch.setattr(device.ui_state, "params", fake_params)

  device._perform_user_reboot()

  assert fake_params.writes == [("DoUserReboot", True)]
  assert hardware.reboot_calls == 1
  assert ("DoReboot", True) not in fake_params.writes


def test_failed_direct_reboot_keeps_manager_fallback(monkeypatch):
  hardware = FakeHardware(RuntimeError("reboot failed"))
  monkeypatch.setattr(device, "HARDWARE", hardware)
  fake_params = FakeParams()
  monkeypatch.setattr(device.ui_state, "params", fake_params)
  monkeypatch.setattr(device.cloudlog, "exception", lambda *_args, **_kwargs: None)

  device._perform_user_reboot()

  assert fake_params.writes == [("DoUserReboot", True)]
  assert hardware.reboot_calls == 1
