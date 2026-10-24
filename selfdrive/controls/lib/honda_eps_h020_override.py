"""The source branch's modified-EPS press detector (kept in opendbc, where the car controller needs it too)."""
from openpilot.common.realtime import DT_CTRL
from opendbc.sunnypilot.car.honda.h020_ptm import get_eps_modified_steering_pressed as _detector


def get_eps_modified_steering_pressed(raw_pressed, steering_torque, torque_cmd, filter_s, previous_pressed):
  return _detector(raw_pressed, steering_torque, torque_cmd, filter_s, previous_pressed, DT_CTRL)
