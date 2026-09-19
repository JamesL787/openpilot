import pytest

import openpilot.selfdrive.controls.lib.latcontrol_pid as latcontrol_pid


def _legacy_clarity_eps_pid_output_scale(desired_angle_deg: float, v_ego: float, is_left: bool) -> float:
  """Pre-symmetry Clarity scale, retained only as a regression oracle."""
  abs_angle = abs(desired_angle_deg)
  speed_weight = min(max((v_ego - 4.0) / 10.0, 0.0), 1.0)
  mid_turn_weight = min(max((abs_angle - 10.0) / 10.0, 0.0), 1.0)
  angle_weight = min(max((abs_angle - 16.0) / 12.0, 0.0), 1.0)

  mid_turn_scale = 0.1200 if is_left else 0.0150
  base_scale = 0.0722 if is_left else 0.0972

  scale = 1.0 + (speed_weight * mid_turn_weight * mid_turn_scale)
  scale += speed_weight * angle_weight * base_scale
  return max(scale, 0.6863)


@pytest.mark.parametrize("v_ego", [0.0, 4.0, 6.0, 12.0, 20.0, 30.0])
@pytest.mark.parametrize("angle_deg", [0.0, 5.0, 10.0, 16.0, 20.0, 28.0, 45.0, 90.0])
def test_clarity_eps_pid_output_scale_is_left_right_symmetric(angle_deg, v_ego):
  left = latcontrol_pid._clarity_eps_pid_output_scale(angle_deg, v_ego)
  right = latcontrol_pid._clarity_eps_pid_output_scale(-angle_deg, v_ego)
  assert left == pytest.approx(right, abs=1e-12)


@pytest.mark.parametrize("v_ego", [4.0, 6.0, 12.0, 20.0, 30.0])
@pytest.mark.parametrize("angle_deg", [10.0, 16.0, 20.0, 28.0, 45.0, 90.0])
def test_clarity_eps_pid_output_scale_preserves_legacy_lr_midpoint(angle_deg, v_ego):
  new_scale = latcontrol_pid._clarity_eps_pid_output_scale(angle_deg, v_ego)
  old_left = _legacy_clarity_eps_pid_output_scale(angle_deg, v_ego, True)
  old_right = _legacy_clarity_eps_pid_output_scale(-angle_deg, v_ego, False)
  assert new_scale == pytest.approx((old_left + old_right) / 2.0, abs=1e-12)


@pytest.mark.parametrize("v_ego", [0.0, 4.0, 12.0, 30.0])
def test_clarity_eps_pid_output_scale_center_is_unchanged(v_ego):
  assert latcontrol_pid._clarity_eps_pid_output_scale(0.0, v_ego) == pytest.approx(1.0)


@pytest.mark.parametrize("angle_deg", [-90.0, -28.0, 28.0, 90.0])
def test_clarity_eps_pid_output_scale_below_speed_gate_is_unchanged(angle_deg):
  assert latcontrol_pid._clarity_eps_pid_output_scale(angle_deg, 4.0) == pytest.approx(1.0)
