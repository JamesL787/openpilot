"""Pure blend policy for the Clarity PID/NNFF hybrid.

Kept free of LatControl imports so it stays testable on hosts without the
device-built native extensions.

Ported from nrdr's latcontrol_clarity_hybrid.py (upstream/nrdr-development, 2026-07-29).
"""
import numpy as np

from cereal import log
from openpilot.common.constants import CV

# Keep the road-proven PID fully in charge below the transition and NNFF fully in
# charge above it. The user-selected speed is the centre of a narrow 6 mph blend,
# so the 30 mph default exactly preserves nrdr's road-tested 27-33 mph handoff.
NNLC_DEFAULT_ACTIVATION_SPEED_MPH = 30.0
NNLC_BLEND_HALF_WIDTH = 3.0 * CV.MPH_TO_MS
BLEND_TO_PID_SECONDS = 0.25
BLEND_TO_NNLC_SECONDS = 0.75
SETTINGS_REFRESH_FRAMES = 100


def clarity_nnlc_blend_target(v_ego: float, lane_change_state, activation_speed: float) -> float:
  """Fraction of NNFF in the output: 0.0 = pure PID, 1.0 = pure NNFF."""
  if lane_change_state != log.LaneChangeState.off:
    return 0.0
  activation_speed = float(np.clip(activation_speed, 0.0, 100.0 * CV.MPH_TO_MS))
  pid_full_speed = max(0.0, activation_speed - NNLC_BLEND_HALF_WIDTH)
  nnlc_full_speed = min(100.0 * CV.MPH_TO_MS, activation_speed + NNLC_BLEND_HALF_WIDTH)
  if nnlc_full_speed <= pid_full_speed:
    return float(v_ego >= activation_speed)
  return float(np.interp(v_ego, [pid_full_speed, nnlc_full_speed], [0.0, 1.0]))


def step_blend(current: float, target: float, dt: float) -> float:
  """Rate-limited move toward target: retreat to PID 3x faster than handing to NNFF."""
  transition_seconds = BLEND_TO_PID_SECONDS if target < current else BLEND_TO_NNLC_SECONDS
  max_delta = dt / transition_seconds
  return current + float(np.clip(target - current, -max_delta, max_delta))
