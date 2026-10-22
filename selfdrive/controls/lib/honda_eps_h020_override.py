"""Source controller's modified-EPS press detector, isolated from newer Honda/StarPilot imports."""
from openpilot.common.realtime import DT_CTRL


def get_eps_modified_steering_pressed(raw_pressed, steering_torque, torque_cmd, filter_s, previous_pressed):
  if not raw_pressed:
    return 0.0, False
  torque_product = float(steering_torque) * float(torque_cmd)
  torque_cmd_abs = abs(float(torque_cmd))
  if previous_pressed or torque_cmd_abs < 0.10 or torque_product < 0.0:
    return 1.0, True
  filter_s = min(1.0, filter_s + DT_CTRL)
  return filter_s, filter_s >= 0.28
