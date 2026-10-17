"""BLoTv3 longitudinal necessity policy.

The supervisor never commands acceleration. It changes only two runtime inputs
the stock MPC already owns: acceleration-change/jerk cost and following time.
That keeps trajectory generation inside one solver while making its response
proportional to measured need.
"""
from dataclasses import dataclass
import math
from typing import Any

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longitudinal_lead import (
  LeadObservation,
  closing_speed,
  time_to_collision,
  total_decel_requirement,
)
from openpilot.selfdrive.modeld.constants import ModelConstants

# Shared necessity frame.
D_MIN = 4.0
MIN_GAP_BUDGET = 1.0

# NRDR: upstream also redefines the acceleration envelope here. That is deliberately
# NOT ported -- StarPilot takes its limits from starpilotPlan.maxAcceleration, and
# BLOTV3_ACCEL_MAX resolves to opendbc's ACCEL_MAX (2.0) anyway, so it would only
# fight the planner for no gain. The supervisor below never commands acceleration.

# Recovery and model-forecast response.
MIN_BOOST_BRAKE = 0.8
EXCESS_ON = 0.4
EXCESS_OFF = 0.15
EXCESS_DEBOUNCE = 0.4
MODEL_HARD_THRESHOLD = -0.5
MODEL_ARM_DEBOUNCE = 0.3
MODEL_LEAD_PROB_MIN = 0.5

# Launch response.
LAUNCH_VREL_ON = 0.5
LAUNCH_VREL_OFF = 0.2
LAUNCH_ALEAD_ON = 0.5
LAUNCH_SHORTFALL_ON = 0.6
LAUNCH_SHORTFALL_OFF = 0.2
LAUNCH_DEBOUNCE = 0.4
RATCHET_LEAD_BRAKE = 0.2
# After excess braking eases behind a lead that is pulling away, the low jerk cost stays this
# long. The recovery trigger disarms at the plan's zero crossing -- exactly where the MPC has to
# swing to acceleration as fast as it braked -- so without a tail the pickup is made with the
# stock stiff cost. Upstream evidence (SpysyWeeb/Spysypilot cdf8e54c9, necessity_supervisor.py):
# route 0x3b t=392, a truck that drove off, +0.26 m/s2 early in the pickup and 0.15 s over the
# ramp. That is upstream's replay measurement on upstream's tree, NOT ours -- see STATUS item 41.
PURSUIT_TAIL_S = 3.0

# MPC policy bounds and continuity.
JERK_SCALE_MIN = 0.3
JERK_SCALE_RATE = 1.5
ONSET_LEAD_DECEL = 0.4
ONSET_PAD_MAX = 0.45
STOPPED_LEAD_PAD_MAX = 0.75
ONSET_FULL_DECEL = 1.5
# ONSET_MAX_A_REQ gates the emergency bypass AND both t_follow pads: above 1.5 m/s2 of
# required decel the pads ramp back out (ONSET_RATE_DOWN). D-058 part 1 (7495a6fb, from upstream
# BLoTv3) removed the pad gate so the pads saturated instead; that was reverted 2026-09-28.
# A pad asks for more following distance, so adding one while the car already needs a hard
# brake makes the brake harder. Closed-loop replay sim, routes 00000293/00000294, 8 hard
# brakes: with BLoTv3 on, every peak was harder than off (by 0.03-0.8 m/s2) and the closest
# gap was the same within ~1 m. Owner-bookmarked 294 6:25 (lead braked -5 then turned off at
# 35 m): -4.2 on vs -3.4 off in the sim. Replay evidence only, not driven.
ONSET_MAX_A_REQ = 1.5
EMERGENCY_SHORTFALL_MIN = 0.15
ONSET_RATE_UP = 0.8
ONSET_RATE_DOWN = 0.5
MIN_TTC = 3.5
MIN_SPEED = 1.0


@dataclass(frozen=True, slots=True)
class LongitudinalPolicy:
  jerk_scale: float
  t_follow: float
  required_decel: float
  emergency: bool
  recovery_active: bool
  model_active: bool
  launch_active: bool


class DebouncedTrigger:
  def __init__(self, debounce: float, dt: float):
    self.debounce = debounce
    self.dt = dt
    self._seconds = 0.0

  def reset(self) -> None:
    self._seconds = 0.0

  def step(self, arm: bool, disarm: bool) -> bool:
    if arm:
      self._seconds += self.dt
    elif disarm:
      self.reset()
    return self._seconds + 1e-9 >= self.debounce


def model_predicted_acceleration(model_lead: Any) -> float | None:
  """Return the model lead's first-horizon acceleration when trustworthy."""
  try:
    if model_lead is None or float(model_lead.prob) < MODEL_LEAD_PROB_MIN or len(model_lead.v) < 2:
      return None
    v0 = float(model_lead.v[0])
    v1 = float(model_lead.v[1])
    horizon = float(ModelConstants.LEAD_T_IDXS[1] - ModelConstants.LEAD_T_IDXS[0])
  except (AttributeError, IndexError, TypeError, ValueError):
    return None

  if horizon <= 0.0 or not all(math.isfinite(value) for value in (v0, v1, horizon)):
    return None
  return (v1 - v0) / horizon


class BLoTv3Supervisor:
  def __init__(self, dt: float = DT_MDL):
    self.dt = dt
    self.jerk_scale = 1.0
    self.t_follow_pad = 0.0
    self._recovery = DebouncedTrigger(EXCESS_DEBOUNCE, dt)
    self._model = DebouncedTrigger(MODEL_ARM_DEBOUNCE, dt)
    self._launch = DebouncedTrigger(LAUNCH_DEBOUNCE, dt)
    self._triggers = (self._recovery, self._model, self._launch)
    # True while the supervisor is actually softening for a lead. Latches the low-speed
    # hold below; see update().
    self._responsive = False
    # Seconds of pursuit tail left. Initialised here as well as in reset() because this
    # __init__ does not call reset() -- upstream's does, so upstream carries it only in
    # reset(). Without this the first update() frame reads an undefined attribute.
    self._pursuit_s = 0.0

  def reset(self) -> None:
    self.jerk_scale = 1.0
    self.t_follow_pad = 0.0
    self._responsive = False
    self._pursuit_s = 0.0
    for trigger in self._triggers:
      trigger.reset()

  def _slew(self, current: float, target: float, rate: float) -> float:
    step = rate * self.dt
    return min(max(target, current - step), current + step)

  def update(self, lead: LeadObservation, v_ego: float, a_mpc: float,
             t_follow_base: float, predicted_lead_accel: float | None = None) -> LongitudinalPolicy:
    scale_target = 1.0
    pad_target = 0.0
    required_decel = 0.0
    emergency = False
    recovery_active = False
    model_active = False
    launch_active = False

    if lead.present and v_ego > MIN_SPEED:
      required_decel = total_decel_requirement(
        v_ego, lead, D_MIN, MIN_GAP_BUDGET,
      )
      closing = closing_speed(v_ego, lead)
      braking_shortfall = required_decel + a_mpc if math.isfinite(a_mpc) else math.inf
      emergency = (
        time_to_collision(v_ego, lead) < MIN_TTC
        and required_decel >= ONSET_MAX_A_REQ
        and braking_shortfall > EMERGENCY_SHORTFALL_MIN
      )

      if not emergency:
        excess = -a_mpc - required_decel
        recovery_active = self._recovery.step(
          arm=excess > EXCESS_ON and -a_mpc > MIN_BOOST_BRAKE,
          disarm=excess < EXCESS_OFF or -a_mpc <= MIN_BOOST_BRAKE,
        )

        predicted_hard = (
          predicted_lead_accel is not None
          and math.isfinite(predicted_lead_accel)
          and predicted_lead_accel < MODEL_HARD_THRESHOLD
        )
        model_active = self._model.step(
          arm=predicted_hard,
          disarm=not predicted_hard,
        )

        receding = lead.speed - v_ego
        shortfall = lead.acceleration - a_mpc
        launch_active = self._launch.step(
          arm=(
            receding > LAUNCH_VREL_ON
            and lead.acceleration > LAUNCH_ALEAD_ON
            and required_decel < 0.1
            and shortfall > LAUNCH_SHORTFALL_ON
          ),
          disarm=(
            shortfall < LAUNCH_SHORTFALL_OFF
            or lead.acceleration < LAUNCH_ALEAD_ON
            or receding < LAUNCH_VREL_OFF
          ),
        )

        # The pursuit tail: excess braking behind a lead that is already pulling away keeps the
        # low jerk cost for a bounded time after the braking eases, so the swing to acceleration
        # is not made with the stiff cost. It touches jerk_scale ONLY -- never t_follow.
        if recovery_active and lead.acceleration > LAUNCH_ALEAD_ON:
          self._pursuit_s = PURSUIT_TAIL_S
        elif lead.acceleration <= 0.0:
          self._pursuit_s = 0.0
        else:
          self._pursuit_s = max(self._pursuit_s - self.dt, 0.0)

        if recovery_active or model_active or launch_active or self._pursuit_s > 0.0:
          scale_target = JERK_SCALE_MIN

        # Do not stiffen a previously responsive solution in the middle of a
        # lead-braking/ego-closing reversal.
        if (
          scale_target > self.jerk_scale
          and lead.acceleration < -RATCHET_LEAD_BRAKE
          and closing > 0.0
        ):
          scale_target = self.jerk_scale

        onset_lead_accel = lead.acceleration
        if model_active and predicted_lead_accel is not None:
          onset_lead_accel = min(onset_lead_accel, predicted_lead_accel)

        recovering = v_ego <= lead.speed + 0.2 or lead.acceleration > 0.2
        # The pads only apply below ONSET_MAX_A_REQ of need; see the constant.
        if (
          onset_lead_accel < -ONSET_LEAD_DECEL
          and required_decel < ONSET_MAX_A_REQ
          and not recovering
        ):
          pad_target = ONSET_PAD_MAX * min(
            -onset_lead_accel / ONSET_FULL_DECEL,
            1.0,
          )
        if (
          lead.speed < 2.0
          and 0.3 < required_decel < ONSET_MAX_A_REQ
          and not recovering
        ):
          pad_target = max(
            pad_target,
            STOPPED_LEAD_PAD_MAX * min(required_decel / 1.2, 1.0),
          )

        self._responsive = scale_target < 1.0 or pad_target > 0.0
      else:
        # The emergency bypass hands the frame back to the MPC unsoftened, and it must
        # also drop the low-speed hold -- otherwise the hold would carry a softened
        # jerk cost into the one situation that wants the stock cost.
        self._responsive = False
        self._pursuit_s = 0.0
        for trigger in self._triggers:
          trigger.reset()
    else:
      # A crawl (v_ego <= MIN_SPEED) with the lead still present keeps the latch; only
      # losing the lead clears it. The pursuit tail is NOT held through the crawl -- a
      # pull-away that ends in a crawl is not a pursuit.
      if not lead.present:
        self._responsive = False
      self._pursuit_s = 0.0
      for trigger in self._triggers:
        trigger.reset()

    # Hold whatever softening was built while necessity-braking through the crawl and the
    # standstill transition. The previous form only held at the exact JERK_SCALE_MIN floor,
    # so a partially-softened approach (the common case: a pad without a full trigger, or a
    # slew still in flight when v_ego crossed MIN_SPEED) started stiffening back toward 1.0
    # in the last metres of the stop. The latch is set only by an in-motion frame that was
    # actually softening, and is cleared by the emergency bypass and by lead loss.
    if lead.present and v_ego <= MIN_SPEED and self._responsive:
      scale_target = min(scale_target, self.jerk_scale)

    self.jerk_scale = self._slew(
      self.jerk_scale,
      scale_target,
      JERK_SCALE_RATE,
    )
    self.t_follow_pad = self._slew(
      self.t_follow_pad,
      pad_target,
      ONSET_RATE_UP if pad_target > self.t_follow_pad else ONSET_RATE_DOWN,
    )

    return LongitudinalPolicy(
      jerk_scale=self.jerk_scale,
      t_follow=t_follow_base + self.t_follow_pad,
      required_decel=required_decel,
      emergency=emergency,
      recovery_active=recovery_active,
      model_active=model_active,
      launch_active=launch_active,
    )
