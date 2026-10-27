import time

from openpilot.system.hardware import HARDWARE

# camerad on a tici disables a driver sensor that fails to probe and then never publishes driverCameraState
# while road and wide keep running. Only a tici with both of those alive and no driver frame ever is treated as camera-less.
DETECT_SECONDS = 20.


class DriverCameraDetector:
  def __init__(self, device_type: str | None = None, detect_seconds: float = DETECT_SECONDS):
    self.eligible = (HARDWARE.get_device_type() if device_type is None else device_type) == "tici"
    self.detect_seconds = detect_seconds
    self.road_alive_since: float | None = None
    self.absent = False

  def update(self, sm, now: float | None = None) -> bool:
    if not self.eligible:
      return False
    now = time.monotonic() if now is None else now

    if sm.recv_frame['driverCameraState'] > 0 or sm.recv_frame.get('driverStateV2', 0) > 0:
      self.road_alive_since = None
      self.absent = False
    elif sm.alive['roadCameraState'] and sm.alive['wideRoadCameraState']:
      if self.road_alive_since is None:
        self.road_alive_since = now
      self.absent = now - self.road_alive_since >= self.detect_seconds
    else:
      self.road_alive_since = None
    return self.absent
