#!/usr/bin/env python3
import time

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process, DT_DMON
from openpilot.selfdrive.monitoring.driver_camera import DriverCameraDetector
from openpilot.selfdrive.monitoring.policy import DriverMonitoring


def get_rhd_override(params):
  return params.get_bool("IsRHD") if params.get_bool("IsRHDOverride") else None


def dmonitoringd_thread():
  config_realtime_process([0, 1, 2, 3], 5)

  params = Params()
  pm = messaging.PubMaster(['driverMonitoringState'])
  sm = messaging.SubMaster(
    ['driverStateV2', 'liveCalibration', 'carState', 'selfdriveState', 'modelV2', 'starpilotCarState',
     'roadCameraState', 'wideRoadCameraState', 'driverCameraState'],
    poll='driverStateV2',
    ignore_alive=['starpilotCarState', 'roadCameraState', 'wideRoadCameraState', 'driverCameraState'],
    ignore_avg_freq=['starpilotCarState', 'roadCameraState', 'wideRoadCameraState', 'driverCameraState'],
    ignore_valid=['starpilotCarState', 'roadCameraState', 'wideRoadCameraState', 'driverCameraState'],
  )
  camera_detector = DriverCameraDetector()
  camera_less_services = ['liveCalibration', 'carState', 'selfdriveState', 'modelV2']
  next_camera_less_step = time.monotonic()

  DM = DriverMonitoring(
    rhd_saved=params.get_bool("IsRhdDetected"),
    always_on=params.get_bool("AlwaysOnDM"),
    rhd_override=get_rhd_override(params),
  )
  demo_mode=False

  # 20Hz <- dmonitoringmodeld
  while True:
    camera_less = camera_detector.update(sm)
    sm.update(int(DT_DMON * 500) if camera_less else 100)

    if camera_less:
      # no driver camera, so no driverStateV2 to wait on: step and publish on a 20Hz timer instead
      now = time.monotonic()
      if now < next_camera_less_step:
        continue
      next_camera_less_step = max(next_camera_less_step + DT_DMON, now - DT_DMON)
      valid = sm.all_checks(camera_less_services)
      if valid:
        DM.run_step_without_camera(sm)
      pm.send('driverMonitoringState', DM.get_state_packet(valid=valid))
      continue

    if not sm.updated['driverStateV2']:
      # iterate when model has new output
      continue

    valid = sm.all_checks()
    if demo_mode and sm.valid['driverStateV2']:
      DM.run_step(sm, demo=True)
    elif valid:
      DM.run_step(sm, demo=demo_mode)

    # publish
    dat = DM.get_state_packet(valid=valid)
    pm.send('driverMonitoringState', dat)

    # load live always-on toggle
    if sm['driverStateV2'].frameId % 40 == 1:
      DM.always_on = params.get_bool("AlwaysOnDM")
      DM.wheel_on_right_default = params.get_bool("IsRhdDetected")
      DM.wheel_on_right_override = get_rhd_override(params)
      demo_mode = params.get_bool("IsDriverViewEnabled")

    # save rhd virtual toggle every 5 mins
    if (DM.wheel_on_right_override is None and sm['driverStateV2'].frameId % 6000 == 0 and not demo_mode and
     DM.wheelpos_offsetter.filtered_stat.n > DM.settings._WHEELPOS_FILTER_MIN_COUNT and
     DM.wheel_on_right == (DM.wheelpos_offsetter.filtered_stat.M > DM.settings._WHEELPOS_THRESHOLD)):
      params.put_bool("IsRhdDetected", DM.wheel_on_right)
      params.put_bool("IsRHD", DM.wheel_on_right)

def main():
  dmonitoringd_thread()


if __name__ == '__main__':
  main()
