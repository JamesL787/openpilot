from types import SimpleNamespace

from cereal import car, log
from openpilot.common.realtime import DT_DMON
from openpilot.selfdrive.monitoring.driver_camera import DriverCameraDetector
from openpilot.selfdrive.monitoring.policy import DriverMonitoring

MonitoringPolicy = log.DriverMonitoringState.MonitoringPolicy


class FakeSM:
  def __init__(self, road=True, wide=True, driver_frames=0):
    self.alive = {'roadCameraState': road, 'wideRoadCameraState': wide, 'driverCameraState': driver_frames > 0}
    self.recv_frame = {'roadCameraState': 1, 'wideRoadCameraState': 1, 'driverCameraState': driver_frames}


class DictSM(dict):
  alive = {'starpilotCarState': True}
  valid = {'starpilotCarState': True}


def dict_sm(engaged=False, steering_pressed=False):
  sm = DictSM()
  sm.update({
    'carState': SimpleNamespace(vEgo=20., steeringPressed=steering_pressed, gasPressed=False, gearShifter=car.CarState.GearShifter.drive),
    'selfdriveState': SimpleNamespace(enabled=engaged),
    'starpilotCarState': SimpleNamespace(alwaysOnLateralEnabled=False),
  })
  return sm


class TestDriverCameraDetector:
  def test_only_a_tici_can_be_driver_camera_less(self):
    for device_type in ("tizi", "mici"):
      detector = DriverCameraDetector(device_type=device_type)
      assert not any(detector.update(FakeSM(), now=t) for t in range(0, 600, 5))

  def test_tici_with_road_and_wide_but_no_driver_camera(self):
    detector = DriverCameraDetector(device_type="tici", detect_seconds=20.)
    assert not detector.update(FakeSM(), now=100.)
    assert not detector.update(FakeSM(), now=119.)
    assert detector.update(FakeSM(), now=120.)

  def test_a_driver_camera_that_publishes_is_never_absent(self):
    detector = DriverCameraDetector(device_type="tici", detect_seconds=20.)
    assert not any(detector.update(FakeSM(driver_frames=5), now=t) for t in range(0, 600, 5))

  def test_driver_frames_arriving_late_clear_it(self):
    detector = DriverCameraDetector(device_type="tici", detect_seconds=20.)
    detector.update(FakeSM(), now=0.)
    assert detector.update(FakeSM(), now=30.)
    assert not detector.update(FakeSM(driver_frames=1), now=31.)

  def test_dead_road_or_wide_camera_is_not_mistaken_for_no_driver_camera(self):
    detector = DriverCameraDetector(device_type="tici", detect_seconds=20.)
    for t in range(0, 300, 5):
      assert not detector.update(FakeSM(road=False), now=t)
      assert not detector.update(FakeSM(wide=False), now=t)


class TestRunStepWithoutCamera:
  def test_policy_is_wheeltouch_and_timeouts_stay_long(self):
    DM = DriverMonitoring()
    DM.run_step_without_camera(dict_sm(engaged=True))
    assert DM.active_policy == MonitoringPolicy.wheeltouch
    assert DM.settings._WHEELTOUCH_POLICY_ALERT_3_TIMEOUT == 86400.
    assert DM.alert_level == 0

  def test_wheel_touch_resets_awareness(self):
    DM = DriverMonitoring()
    for _ in range(int(60 / DT_DMON)):
      DM.run_step_without_camera(dict_sm(engaged=True))
    assert DM.awareness < 1.
    DM.run_step_without_camera(dict_sm(engaged=True, steering_pressed=True))
    assert DM.awareness == 1.

  def test_awareness_is_not_consumed_while_disengaged(self):
    DM = DriverMonitoring()
    for _ in range(int(60 / DT_DMON)):
      DM.run_step_without_camera(dict_sm(engaged=False))
    assert DM.awareness == 1.
