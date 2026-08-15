from cereal import car
from opendbc.car.hyundai.values import CAR as HYUNDAI_CAR

from openpilot.selfdrive.selfdrived.selfdrived import commanded_torque_at_max_for_saturation


def test_immediate_max_output_saturation_is_torque_controller_only():
  CP = car.CarParams.new_message()
  CP.steerControlType = car.CarParams.SteerControlType.torque
  CP.lateralTuning.init("torque")

  assert commanded_torque_at_max_for_saturation(CP, 1.0)
  assert not commanded_torque_at_max_for_saturation(CP, 0.99)

  CP.lateralTuning.init("pid")
  assert not commanded_torque_at_max_for_saturation(CP, 1.0)

  CP.lateralTuning.init("torque")
  CP.steerControlType = car.CarParams.SteerControlType.angle
  assert not commanded_torque_at_max_for_saturation(CP, 1.0)


def test_gv70_uses_normal_saturation_timer_at_max_output():
  CP = car.CarParams.new_message()
  CP.carFingerprint = HYUNDAI_CAR.GENESIS_GV70_ELECTRIFIED_1ST_GEN
  CP.steerControlType = car.CarParams.SteerControlType.torque
  CP.lateralTuning.init("torque")

  assert not commanded_torque_at_max_for_saturation(CP, 1.0)
