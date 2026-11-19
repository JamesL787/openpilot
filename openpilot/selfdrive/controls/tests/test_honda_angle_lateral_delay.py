"""Clarity angle mode: modeld and controlsd both use lagd's learned delay (the calibration schedule is torque-mode)."""
from opendbc.car.honda.clarity_angle_mode import apply_angle_mode
from opendbc.car.honda.tests.test_modified_eps import eps, params
from opendbc.car.honda.values import CAR
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import lateral_delay_schedule

PTM = b'39990-TRW,A020\x00\x00'


def clarity(angle):
  cp = apply_angle_mode(params(CAR.HONDA_CLARITY, [eps(PTM)]), angle)
  cp.carFw = [eps(PTM)]
  return cp


def test_torque_mode_keeps_the_calibration_schedule():
  assert lateral_delay_schedule(clarity(False)) is not None


def test_angle_mode_uses_lagd():
  assert lateral_delay_schedule(clarity(True)) is None
