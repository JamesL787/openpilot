from cereal import car
from openpilot.system.hardware.tici import buzzerd
from openpilot.system.hardware.tici.buzzerd import Buzzerd, GPIO_DIR, GPIO_ROOT

AudibleAlert = car.CarControl.HUDControl.AudibleAlert


class SyncThread:
  # runs the target inline so alert dispatch is deterministic
  def __init__(self, target, daemon=True):
    self.target = target

  def start(self):
    self.target()


class TestBuzzerd:
  def _buzzer(self, mocker):
    writes = []
    mocker.patch.object(buzzerd.threading, "Thread", SyncThread)
    mocker.patch.object(buzzerd.time, "sleep")
    return Buzzerd(write=lambda path, val: writes.append((path, val)) or True), writes

  def test_warning_pulses_three_times(self, mocker):
    b, writes = self._buzzer(mocker)
    b.warning()
    assert writes == [(f"{GPIO_DIR}/value", v) for _ in range(3) for v in ("1", "0")]

  def test_only_warning_alerts_beep(self, mocker):
    for alert in (AudibleAlert.refuse, AudibleAlert.prompt, AudibleAlert.warningSoft):
      b, writes = self._buzzer(mocker)
      b.update_alert(alert)
      assert len(writes) == 6
    for alert in (AudibleAlert.engage, AudibleAlert.disengage, AudibleAlert.warningImmediate, AudibleAlert.none):
      b, writes = self._buzzer(mocker)
      b.update_alert(alert)
      assert writes == []

  def test_repeated_alert_beeps_once_per_change(self, mocker):
    b, writes = self._buzzer(mocker)
    for _ in range(5):
      b.update_alert(AudibleAlert.prompt)
    assert len(writes) == 6
    b.update_alert(AudibleAlert.none)
    b.update_alert(AudibleAlert.prompt)
    assert len(writes) == 12

  def test_enable_gpio_exports_when_missing(self, mocker):
    b, writes = self._buzzer(mocker)
    mocker.patch.object(buzzerd.os.path, "isdir", return_value=False)
    assert not b.enable_gpio()
    assert writes == [(f"{GPIO_ROOT}/export", "42")]

  def test_enable_gpio_sets_direction(self, mocker):
    b, writes = self._buzzer(mocker)
    mocker.patch.object(buzzerd.os.path, "isdir", return_value=True)
    assert b.enable_gpio()
    assert writes == [(f"{GPIO_DIR}/direction", "out")]

  def test_only_present_on_tici_device_type(self, mocker):
    mocker.patch.object(buzzerd, "TICI", False)
    assert not buzzerd.buzzer_present()
    mocker.patch.object(buzzerd, "TICI", True)
    mocker.patch.object(buzzerd.HARDWARE, "get_device_type", return_value="tizi")
    assert not buzzerd.buzzer_present()
    mocker.patch.object(buzzerd.HARDWARE, "get_device_type", return_value="tici")
    assert buzzerd.buzzer_present()
