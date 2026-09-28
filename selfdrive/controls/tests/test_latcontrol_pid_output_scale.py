import pytest

from openpilot.selfdrive.controls.lib.latcontrol_pid import _clarity_eps_pid_output_scale as scale


@pytest.mark.parametrize("v", [0.0, 5.0, 10.0, 20.0, 30.0])
@pytest.mark.parametrize("angle", [0.0, 3.0, 12.0, 18.0, 25.0, 40.0, 90.0])
def test_same_both_ways(angle, v):
  assert scale(angle, v) == scale(-angle, v)


def test_no_change_near_centre_or_slow():
  assert scale(9.9, 30.0) == 1.0
  assert scale(-2.0, 30.0) == 1.0
  assert scale(60.0, 4.0) == 1.0


def test_full_turn_at_speed():
  assert scale(28.0, 14.0) == pytest.approx(1.0 + 0.0675 + 0.0847)
  assert scale(15.0, 14.0) == pytest.approx(1.0 + 0.5 * 0.0675)
