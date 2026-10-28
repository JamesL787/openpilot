#!/usr/bin/env python3
# Drives the buzzer on GPIO 42 of MR.ONE clones (device type "tici") from selfdriveState.alertSound.
import os
import subprocess
import threading
import time

from cereal import car, messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE, TICI

AudibleAlert = car.CarControl.HUDControl.AudibleAlert

BUZZER_GPIO = 42
GPIO_ROOT = "/sys/class/gpio"
GPIO_DIR = f"{GPIO_ROOT}/gpio{BUZZER_GPIO}"

WARNING_ALERTS = (AudibleAlert.refuse, AudibleAlert.prompt, AudibleAlert.warningSoft)
WARNING_PULSES = 3
PULSE_S = 0.01


def buzzer_present() -> bool:
  return TICI and HARDWARE.get_device_type() == "tici"


def write_sysfs(path: str, value: str) -> bool:
  try:
    with open(path, "w") as f:
      f.write(value)
    return True
  except PermissionError:
    r = subprocess.run(["sudo", "tee", path], input=value, text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0
  except OSError:
    return False


class Buzzerd:
  def __init__(self, write=write_sysfs):
    self.write = write
    self.current_alert = AudibleAlert.none
    self.lock = threading.Lock()

  def enable_gpio(self) -> bool:
    if not os.path.isdir(GPIO_DIR):
      self.write(f"{GPIO_ROOT}/export", str(BUZZER_GPIO))
    return os.path.isdir(GPIO_DIR) and self.write(f"{GPIO_DIR}/direction", "out")

  def _beep(self, on: bool) -> None:
    self.write(f"{GPIO_DIR}/value", "1" if on else "0")

  def warning(self) -> None:
    with self.lock:
      for _ in range(WARNING_PULSES):
        self._beep(True)
        time.sleep(PULSE_S)
        self._beep(False)
        time.sleep(PULSE_S)

  def update_alert(self, new_alert) -> None:
    if new_alert == self.current_alert:
      return
    self.current_alert = new_alert
    if new_alert in WARNING_ALERTS:
      threading.Thread(target=self.warning, daemon=True).start()

  def run(self) -> None:
    sm = messaging.SubMaster(['selfdriveState'])
    rk = Ratekeeper(20)
    while True:
      sm.update(0)
      if sm.updated['selfdriveState']:
        self.update_alert(sm['selfdriveState'].alertSound.raw)
      rk.keep_time()


def main():
  buzzer = Buzzerd()
  if not buzzer_present() or not buzzer.enable_gpio():
    # idle instead of exiting, the manager would restart a process that returns
    cloudlog.warning("buzzer gpio not available, buzzerd idle")
    while True:
      time.sleep(3600)
  buzzer.run()


if __name__ == "__main__":
  main()
