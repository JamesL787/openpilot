import numpy as np
import pytest

from opendbc.car.honda.carcontroller import bosch_overbrake_compensation


@pytest.mark.parametrize("accel", [-4.0, -3.5, -3.0, -1.0, -0.5, 0.0, 1.0])
def test_zero_outside_mid_band(accel):
  # never weakens saturated/emergency commands (<= -3.0) nor touches light braking or gas
  assert bosch_overbrake_compensation(accel, False) == 0.0


def test_zero_while_stopping():
  assert bosch_overbrake_compensation(-2.5, True) == 0.0


def test_bounded_and_monotonic_command():
  accels = np.linspace(-3.6, 0.0, 721)
  comp = np.array([bosch_overbrake_compensation(a, False) for a in accels])
  assert comp.min() >= 0.0 and comp.max() <= 0.15 + 1e-9
  cmd = accels + comp
  # a deeper request always yields an equal-or-deeper command, and the command is never positive
  assert np.all(np.diff(cmd) > 0.0)
  assert np.all(cmd[accels < -1.0] < -1.0)
