#!/usr/bin/env python3
"""Small, deterministic policy for ordinary moving-lead following.

Stop, departure, and model-target decisions remain in longitudinal_planner.
This policy only shapes the non-urgent follow output after MPC has selected a
lead.  Keeping that boundary explicit prevents comfort smoothing from weakening
the raw lead safety path.
"""

from dataclasses import dataclass

import numpy as np

from openpilot.selfdrive.controls.lib.lead_behavior import is_radarless_matched_follow_window
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import desired_follow_distance


FOLLOW_MIN_SPEED = 8.0
FOLLOW_MATCHED_MIN_SPEED = 22.0
FOLLOW_MAX_LEAD_BRAKE = 0.35
FOLLOW_GAP_BUFFER_MIN = 4.0
FOLLOW_GAP_BUFFER_GAIN = 0.15
FOLLOW_HEADWAY_MARGIN = 0.90
FOLLOW_STEADY_DEADBAND_MAX_TARGET = 0.28
FOLLOW_STEADY_DEADBAND_MAX_CLOSING = 0.75
FOLLOW_STEADY_DEADBAND_MAX_HEADWAY_MARGIN = 0.90


@dataclass(frozen=True)
class FollowResult:
  lead: object | None
  accel_cap: float | None
  target: float


def _lead_brake(lead) -> float:
  return max(0.0, -float(getattr(lead, "aLeadK", 0.0)))


def _lead_prob(lead) -> float:
  return float(getattr(lead, "modelProb", 1.0 if bool(getattr(lead, "radar", False)) else 0.0))


def _headway(lead, v_ego: float) -> float:
  return float(lead.dRel) / max(float(v_ego), 1e-3)


def _matched(lead, v_ego: float, t_follow: float) -> bool:
  if lead is None or not lead.status or float(v_ego) < FOLLOW_MATCHED_MIN_SPEED:
    return False

  relative_speed = float(v_ego) - float(lead.vLead)
  if not (-1.2 <= relative_speed <= 2.2) or _lead_brake(lead) > FOLLOW_MAX_LEAD_BRAKE:
    return False

  radar = bool(getattr(lead, "radar", False))
  if not radar and not is_radarless_matched_follow_window(
    v_ego, lead.dRel, lead.vLead, t_follow,
    radar=False, lead_brake=_lead_brake(lead), lead_prob=_lead_prob(lead),
  ):
    return False

  headway = _headway(lead, v_ego)
  return max(1.05, float(t_follow) - 0.35) <= headway <= float(t_follow) + 0.90


def select_lead(lead_one, lead_two, source: str, active: bool, v_ego: float, t_follow: float):
  """Return the lead already selected by MPC; never fuse or re-select tracks."""
  if not active:
    return None
  if source == "lead1":
    return lead_two if lead_two is not None and lead_two.status else None
  if source == "lead0":
    return lead_one if lead_one is not None and lead_one.status else None
  if lead_one is not None and lead_one.status:
    return lead_one
  if lead_two is not None and lead_two.status:
    return lead_two
  return None


def is_nonurgent_duplicate_vision_follow(lead_one, lead_two, v_ego: float, t_follow: float, mpc) -> bool:
  """Keep MPC's duplicate-track filter only for clearly non-urgent vision pairs."""
  if (lead_one is None or lead_two is None or not lead_one.status or not lead_two.status or
      bool(getattr(lead_one, "radar", False)) or bool(getattr(lead_two, "radar", False))):
    return False
  if not mpc.leads_are_near_duplicates(lead_one, lead_two, v_ego, vision_min_speed=10.0):
    return False

  closing_speed = max(0.0, float(v_ego) - float(lead_one.vLead))
  ttc = float(lead_one.dRel) / max(closing_speed, 0.1) if closing_speed > 0.1 else float("inf")
  headway = float(lead_one.dRel) / max(float(v_ego), 1e-3)
  return ttc > 6.0 and headway > max(0.85, float(t_follow) - 0.45)


def _catchup_cap(lead, v_ego: float, t_follow: float, *, source: str, tracking: bool,
                 post_departure: bool) -> float | None:
  if lead is None or not lead.status or post_departure:
    return None

  radar = bool(getattr(lead, "radar", False))
  brake = _lead_brake(lead)
  if v_ego < FOLLOW_MIN_SPEED:
    return None

  lead_delta = float(lead.vLead) - float(v_ego)
  minimum_delta = -0.5
  if lead_delta < minimum_delta:
    return None

  gap_error = float(lead.dRel) - float(desired_follow_distance(v_ego, lead.vLead, t_follow))
  buffer = max(FOLLOW_GAP_BUFFER_MIN, FOLLOW_GAP_BUFFER_GAIN * float(v_ego))
  if gap_error > buffer:
    return None

  if radar and tracking and _matched(lead, v_ego, t_follow):
    if gap_error > buffer - 0.75:
      return None
    if source == "cruise" and gap_error <= 0.75 and lead_delta < minimum_delta:
      return 0.04

  edge = np.interp(lead_delta, [-0.5, 0.0, 1.0], [0.16, 0.08, 0.02])
  near = min(float(edge), 0.03)
  gap_factor = float(np.clip(max(gap_error, 0.0) / max(buffer, 0.1), 0.0, 1.0))
  cap = float(np.interp(gap_factor, [0.0, 1.0], [near, float(edge)]))
  allowance = float(np.clip(gap_error / 4.0, 0.0, 1.0))
  if v_ego >= 12.0:
    allowance *= 0.55 * float(np.clip((0.35 - brake) / 0.35, 0.0, 1.0))
  cap += allowance * 0.55
  entry = float(np.clip((v_ego - 8.0) / 4.0, 0.0, 1.0))
  cap = float(np.interp(entry, [0.0, 1.0], [1.5, cap]))
  return min(1.5, cap)


def _steady_follow_deadband(lead, v_ego: float, t_follow: float, previous: float, target: float) -> float:
  """Remove only small sign reversals in an already matched, non-urgent follow."""
  if not _matched(lead, v_ego, t_follow):
    return float(target)
  if float(lead.vLead) - float(v_ego) > 0.15:
    return float(target)
  if max(0.0, float(v_ego) - float(lead.vLead)) > FOLLOW_STEADY_DEADBAND_MAX_CLOSING:
    return float(target)
  if _headway(lead, v_ego) - float(t_follow) > FOLLOW_STEADY_DEADBAND_MAX_HEADWAY_MARGIN:
    return float(target)
  if (
    float(previous) * float(target) < 0.0 and
    abs(float(previous)) <= FOLLOW_STEADY_DEADBAND_MAX_TARGET and
    abs(float(target)) <= FOLLOW_STEADY_DEADBAND_MAX_TARGET
  ):
    return 0.0
  return float(target)


def apply(lead_one, lead_two, *, source: str, active: bool, v_ego: float, t_follow: float,
          previous_target: float, raw_target: float, tracking: bool, post_departure: bool,
          blocked: bool, panic_bypass: bool) -> FollowResult:
  if blocked or panic_bypass or post_departure:
    return FollowResult(None, None, float(raw_target))

  lead = select_lead(lead_one, lead_two, source, active, v_ego, t_follow)
  if lead is None:
    return FollowResult(None, None, float(raw_target))

  cap = _catchup_cap(lead, v_ego, t_follow, source=source, tracking=tracking,
                     post_departure=post_departure)
  target = float(raw_target)
  if cap is not None:
    target = min(target, cap)
  target = _steady_follow_deadband(lead, v_ego, t_follow, previous_target, target)
  return FollowResult(lead, cap, target)
