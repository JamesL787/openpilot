import math

from cereal import car
from opendbc.car import apply_hysteresis
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET

ButtonType = car.CarState.ButtonEvent.Type

SEND_BUTTON_NONE = 0
SEND_BUTTON_INCREASE = 1
SEND_BUTTON_DECREASE = 2

HYST_GAP = 0.0
INCREASE_INACTIVE_TIMER = 0.12
DECREASE_INACTIVE_TIMER = 0.05
LEAD_INCREASE_INACTIVE_TIMER = 0.05
MANUAL_BUTTON_INACTIVE_TIMER = 0.5
# ICBM yields for the whole time a physical cruise button is held (the Honda ECU auto-repeats 5 mph
# per ~0.5 s under a hold; bench routes 264 at 101.5 s and 265 at 156.5 s showed ICBM pressing decel
# against a held RES+ once the old 0.5 s window expired). The cap guards a missed release edge.
MANUAL_BUTTON_HELD_MAX_S = 10.0
# Distance (gap) and LKAS presses get the same yield with a longer post-release window. ICBM frames
# carry the car's next SCM_BUTTONS counter (D-065) with CRUISE_SETTING=0, so the ECU drops the car's
# own frame that carries the press. Stock-ACC routes 26f/270 (log decode, limited road evidence): 9
# gap presses, 2/2 registered with no ICBM frame within 0.5 s, 1/7 with ICBM frames overlapping
# (270 2:36-2:45, six presses in 8 s for one gap step). Repeat presses came 0.69-0.71 s after the
# previous release, so a 0.5 s window would let a burst land between them; 1.0 s covers them.
SETTING_BUTTON_INACTIVE_TIMER = 1.0
# Press pacing near the target (counter sync only). A counter-synced press lands on the cluster 0.15-0.42 s
# after its first frame (p10-p90, median 0.235 s; routes 271, 26f, 270, log decode) while pairs go out every
# 0.16 s (decel) / 0.2 s (accel), so pressing until the cluster shows the target leaves one step in flight
# and overshoots by 1 mph, and the next run reverses it. That was the largest single cause of the direction
# reversals in the 271 replay (153 of 352 simulated). With one step (1 mph/km/h) left, ICBM now waits
# PRESS_SETTLE_S after its last press frame (>= the p90 lag, so an in-flight step shows first) and then sends
# one PRESS_PULSE_S pulse (one pressed pair: 2 car frames at 25 Hz). Runs with more than one step left are
# unchanged, so a large lead-driven drop runs at the full rate down to the last mph.
PRESS_SETTLE_S = 0.45
PRESS_PULSE_S = 0.1
# After a decrease press, ICBM does not start an increase for INCREASE_AFTER_DECREASE_LOCKOUT_S. Only the
# increase is held (never a decrease), so it cannot delay a lead-driven drop. 271 replay: the curve-speed
# target switching on and off every ~1 s (seg 24-25) and lead targets moving by 1-3 mph drove the rest of
# the reversals.
INCREASE_AFTER_DECREASE_LOCKOUT_S = 1.0
LEAD_RECOVERY_LOOKAHEAD_POINTS = 4
LEAD_RECOVERY_HOLD_BUFFER_MS = 1.5 * CV.MPH_TO_MS
LEAD_COAST_BUFFER_MS = 1.0 * CV.MPH_TO_MS
LEAD_EXTRA_COAST_BUFFER_FACTOR = 0.6
LEAD_EXTRA_COAST_BUFFER_MAX_MS = 3.0 * CV.MPH_TO_MS
LEAD_EXTRA_COAST_HEADWAY_MIN_S = 1.5
LEAD_EXTRA_COAST_HEADWAY_MAX_S = 3.0
LEAD_CLOSING_REL_SPEED_MIN_MS = 0.5 * CV.MPH_TO_MS
LEAD_PROACTIVE_COAST_HEADWAY_MAX_S = 4.0
LEAD_DEPARTURE_REL_SPEED_MIN_MS = 1.0 * CV.MPH_TO_MS
LEAD_DEPARTURE_HEADWAY_MIN_S = 1.8
LEAD_DEPARTURE_HEADWAY_MAX_S = 4.5
LEAD_DEPARTURE_BOOST_MIN_MS = 1.25 * CV.MPH_TO_MS
LEAD_DEPARTURE_BOOST_MAX_MS = 3.0 * CV.MPH_TO_MS
LEAD_DEPARTURE_BOOST_FACTOR = 0.50
LEAD_DEPARTURE_PLAN_POINTS = 3

# Far lead (stock ACC only; always on for Honda ICBM since STATUS 128): the chill planner's speeds are ICBM's only lead input
# and they do not come down for a slow or stopped lead 100 m out (route 25e 723-727 s, replay: the plan
# stayed at the set speed until the lead was 83 m away, then wanted 22 -> 8 m/s in 3 s and the car's own
# ACC braked -3.5). This target is the speed from which a constant FAR_LEAD_DECEL_MS2 stop reaches the
# lead's speed with FAR_LEAD_HEADWAY_S of headway (never under FAR_LEAD_MIN_GAP_M). It is taken as the
# minimum with the plan-derived target, so it only ever lowers the set speed.
# Was 1.5 m/s^2 for every lead (STATUS 94, 25e replay: "what the set speed can follow at ~2 steps/s").
# Route 271 (log decode, limited road evidence) measured what a lowered set speed actually buys from
# stock ACC with no closing lead: ACCEL_COMMAND median -0.39 / -0.59 / -0.83 m/s^2 at 3-5 / 5-8 / 8-12 mph
# over the set (p10 -0.89), aEgo only -0.18..-0.27. So 1.5 assumed a decel the set-speed channel cannot
# deliver and started the walk late (BM0 9:26, BM4 29:52). 0.8 is what the channel reaches at 8-12 mph
# over the set. It applies only to a corroborated lead (radar-backed, or modelProb >= 0.7): vision-only
# range and closing speed at 85-105 m were wrong in 271 BM3 (+35-45 m) and BM4 (vRel about half of radar),
# so an uncorroborated lead keeps the old 1.5. Replay evidence only (STATUS 126), never driven.
FAR_LEAD_DECEL_MS2 = 0.8
FAR_LEAD_UNCORROBORATED_DECEL_MS2 = 1.5
FAR_LEAD_CORROBORATED_MODEL_PROB = 0.7
FAR_LEAD_MIN_GAP_M = 6.0
FAR_LEAD_HEADWAY_S = 1.5
# Model-only far lead. The planner drops a vision-only lead beyond its vision limit, so plan.hasLead stays False
# and the far-lead target above never saw it. Route 276 8:27.9 (log decode, limited road evidence): a vision
# lead from 114 m slowing 25 -> 3 mph, vRel -3.8 -> -11.3, hasLead False to the end, in-lane radar only at 52 m;
# the driver cancelled. The far-lead target (never the planner) now also takes radarState.leadOne when it is
# vision-only with modelProb >= FAR_LEAD_MODEL_ONLY_PROB and closing faster than FAR_LEAD_MODEL_ONLY_CLOSING_MS.
# It always uses FAR_LEAD_UNCORROBORATED_DECEL_MS2: vision range and closing speed at 85-105 m were wrong in
# route 271 BM3 (range +35-45 m) and BM4 (vRel about half of radar), both errors put the target too high, so
# this helps only partly on such a lead. 8 m/s is above the 5-7 m/s vision vRel that 271/276 vision leads
# showed on cars that turned out to hold speed. Replay (/tmp/icbm3, routes 276/271/26f/270): it never binds,
# because on all four routes such a lead already had plan.hasLead and took the path above (8:27.9 included, where
# the car was engaged at 28.6 mph, 3.6 mph above the Honda floor, so no set-speed target could do much). It is a
# backstop for a hasLead dropout on a confident closing vision lead. Not driven.
FAR_LEAD_MODEL_ONLY_PROB = 0.5
FAR_LEAD_MODEL_ONLY_CLOSING_MS = 8.0

# Increase block. Route 276 14:36.7 (log decode, limited road evidence): the radar lead (tid 5) left the path, a
# slower car on a curve at 87-102 m showed only as a flickering vision lead (p 0.26-0.43), and ICBM raised the
# set 37.9 -> 43.5 mph toward it; radar published it 0.2 s before the driver braked -2.52. ICBM now holds the
# set (target capped at the cluster, so a decrease is never delayed):
# - for INCREASE_BLOCK_AFTER_LEAD_CHANGE_S after leadOne (or plan.hasLead) is lost or changes source, track id
#   or range by more than LEAD_CHANGE_RANGE_JUMP_M. This is also the lead-source hysteresis: 276 17:22.5 hunted
#   13 reversals in 24 s with leadOne flipping radar 70 m <-> vision 95 m; a nearer lead still lowers the set at
#   once, the farther one can only raise it after the lead has been stable for this long.
# - while a target within INCREASE_BLOCK_RANGE_M is closing faster than INCREASE_BLOCK_CLOSING_MS: radarState
#   leadOne/leadTwo, or the model's lead with prob >= INCREASE_BLOCK_MODEL_PROB. Both are path-relative by
#   construction (the model's lead is the lead on its path; radard only publishes tracks matched to it), so
#   there is no raw-yRel gate: the real lead at 14:36.7 sat at yRel +8 on the curve.
# Replay (/tmp/icbm3 sim, base -> fix; open loop in vEgo): 14:36.7 no INCREASE from -8 s to the brake (base
# pressed 37.9 -> 42.9 from -2.2 s); reversals 276 50 -> 27, 271 110 -> 88, 26f 34 -> 22, 270 31 -> 19; 271
# bookmarks and 276 6:58.1 unchanged (6:58.1 loses a 46.6 -> 48.5 bounce mid-drop). Cost: open-road seconds
# > 2 mph below target +9 / +29 / +4 / +14 s (276/271/26f/270), mostly the loss hold under a flickering
# vision lead. The loss/range/track-id hold does most of the work; the closing test alone changes little.
# Radar<->vision flips count as a change (dropping them all: 26f reversals 22 -> 31), except a flip of the
# same car: range within LEAD_CHANGE_RANGE_JUMP_M and neither side closing faster than
# LEAD_SOURCE_FLIP_CLOSING_MS, at least LEAD_SOURCE_FLIP_MIN_HEADWAY_S ahead. Route 277 3:51.5 (replay, open
# loop): a departing lead at 77-94 m flickering radar<->vision at 52-57 mph re-armed the hold and left the set up
# to 5 mph low for 12.6 s; with the exemption the hold there drops 16.6 -> 8.1 s and the set sits at 53.4-55.9
# instead of 51.0-52.8. A flip onto a closing car (vRel < -1 m/s) still holds, as does any flip with a larger
# range jump (276 17:22.5: radar 70 m <-> vision 95 m). The headway gate keeps the hold as hysteresis close in:
# without it 277 11:07 (lead at 37-45 m, 2.3 s) gained 5 reversals (route 32 -> 38); 2.0 s changed nothing,
# 2.5 s gave 34, 3.0 s 35 and lost 271's open-road gain (502.7 -> 507.5 s). Not driven.
INCREASE_BLOCK_AFTER_LEAD_CHANGE_S = 2.0
LEAD_CHANGE_RANGE_JUMP_M = 15.0
LEAD_SOURCE_FLIP_CLOSING_MS = 1.0
LEAD_SOURCE_FLIP_MIN_HEADWAY_S = 2.5
INCREASE_BLOCK_RANGE_M = 110.0
INCREASE_BLOCK_CLOSING_MS = 5.0
INCREASE_BLOCK_MODEL_PROB = 0.25
MODEL_LEAD_RADAR_TO_CAMERA_M = 1.52  # radard.RADAR_TO_CAMERA

# Launch (stock ACC only): after a full stop, raise the set speed straight to the cruise target once the
# car is moving again, instead of holding at the 25 mph floor until vEgo passes it. Route 260 8:39-8:51:
# the car launched to 25 mph with no ICBM press for 11 s, while the lead pulled away from 8 to 34 m.
# Stock ACC keeps the radar and does the following, so a set speed above the lead's speed does not close
# on it. Ends when the car has caught up to the target, stops again, or the driver takes over.
LAUNCH_STOPPED_SPEED_MS = 0.3
LAUNCH_MOVING_SPEED_MS = 2.0 * CV.MPH_TO_MS
LAUNCH_CAUGHT_UP_MARGIN_MS = 2.0 * CV.MPH_TO_MS
# Close lead: route 277 16:34.1 (log decode, limited road evidence): launching behind a radar lead 7-38 m ahead
# (vLead 12 -> 30 mph), the launch raised the set 24.9 -> 48.5 mph, the lead-driven target then cut it to 28.6
# and the driver braked. While a radar-backed (or modelProb >= FAR_LEAD_CORROBORATED_MODEL_PROB) leadOne is
# within LAUNCH_LEAD_CAP_RANGE_M or LAUNCH_LEAD_CAP_HEADWAY_S of vEgo, the launch target is capped at
# max(normal target, vLead + LAUNCH_LEAD_SPEED_MARGIN_MS). The lead-speed term keeps the set off the 25 mph
# floor while the lead pulls away (route 260 8:39). The launch also ends once the set has reached the cap and
# vEgo is within LAUNCH_CAUGHT_UP_MARGIN_MS of a lead doing >= 25 mph, so ICBM follows the lead-driven target;
# ending it behind a slower lead put the set back on the floor behind a faster lead for up to 2.3 s per launch.
# 277 had the lead at 2.7-2.9 s from -3 s to the brake, so 2.5 s would have released the cap there. Replay
# (/tmp/icbm4, open loop): 16:34.1 peaks at 35.4 instead of 48.5 mph; 11 of 15 launches on 5 routes changed.
# The gas-release floor, the other path around the lead-driven target, is not capped: that cut 277 38:26.4
# from 46.0 to 41.6 mph while the driver was passing a lead at 47-61 m. Launch with no lead is unchanged.
LAUNCH_LEAD_CAP_RANGE_M = 30.0
LAUNCH_LEAD_CAP_HEADWAY_S = 3.0
LAUNCH_LEAD_SPEED_MARGIN_MS = 5.0 * CV.MPH_TO_MS
# Route 262 3:43-4:26: the launch raised the set speed to 49.7 mph by 3:50, then held it for 36 s while
# the lead drove 30-45 mph, because it only ended at vEgo >= target - 2 mph. It now also ends once the set
# speed has been raised and the car has caught up to the normal (lead or plan) target, so ICBM follows the
# lead again.

# Gas release (built into ICBM): when the driver releases the gas above the set speed on the dash,
# hold the ICBM target at or above the release speed until a cruise button, the brake, a stop or a
# disengage. Route 262 1:29 and 2:25: the old path moved openpilot's v_cruise (the 55 mph ICBM max), not
# the dash set speed, so a release at 37 mph over a 24.9 mph set speed changed nothing.
GAS_RELEASE_SET_MARGIN_MS = 1.0 * CV.MPH_TO_MS
# The floor is for the moments right after a release on an open road. It used to last until a button, the
# brake, a stop or a disengage, so it also held the set speed up against a lead the car was closing on:
# route 271 (replay of the floor on logged inputs) had it block lead-driven set drops for ~35 s in 5 episodes;
# BM4 29:52 held 33.6 mph from a release 94.6 s earlier while the plan wanted 18-25 mph, and BM2 22:01 held
# 50 mph so no press went out at all. The floor now expires GAS_RELEASE_FLOOR_MAX_S after the release, and is
# dropped for good earlier once a lead that is closing (vRel < -LEAD_CLOSING_REL_SPEED_MIN_MS) and still more
# than GAS_RELEASE_FLOOR_LEAD_HEADWAY_S ahead wants the set lower than the floor (BM4: radar lead at 87-91 m,
# ~5 s at 40 mph). A nearer lead does not clear it: stock ACC follows that lead on its own radar whatever the
# set speed (STATUS 84), and the floor's own motivating case, route 262 1:29 (release at 37 mph behind a radar
# lead at 43.6 m, 2.6 s, closing 2.2 m/s), was cleared on the frame after the release by a closing-only rule.
# 4.0 s is LEAD_PROACTIVE_COAST_HEADWAY_MAX_S, the headway ICBM already treats as the lead's own range.
# On an open road the target is the cruise target, which already caps the floor, so neither limit changes
# what the floor does there. Replay evidence only (STATUS 126).
GAS_RELEASE_FLOOR_MAX_S = 15.0
GAS_RELEASE_FLOOR_LEAD_HEADWAY_S = 4.0
# Gas snap: the floor alone ramps the set speed at 1 mph per press after the release (route 263 13:44:
# 26 -> 41 mph took 3.1 s while the car slowed 42.4 -> 40.4 mph), so while the gas is still held ICBM
# pulses DECEL_SET, which on a Honda snaps the set speed to vEgo under gas (route 260 seg 9: 29 -> 32 mph).
# Only above set + 1 mph (Honda: set >= 25 mph, so never at low speed, where DECEL_SET would set 25) and
# not above the cruise target (vCruise, SLC, CSC), so it only ever raises the set speed to where the
# driver already is.
GAS_SNAP_PRESS_S = 0.2
GAS_SNAP_INTERVAL_S = 0.6

HONDA_MINIMUM_SET_SPEED_MPH = 25
# Honda reports the set speed in whole km/h, truncated: 54 mph -> 86 km/h -> 53.4 mph, which rounds to 53. With a
# 54 mph target, route 263 10:05-10:27 hunted +/- between 85, 86 and 88 km/h (~40 presses in 5 s, the dash beeps).
# The truncation loses up to 0.62 mph, so adding half of that before rounding recovers the whole mph the car holds.
HONDA_KPH_TRUNCATION_MPH = 0.5 * CV.KPH_TO_MPH
HONDA_MINIMUM_SET_SPEED_KPH = 40

CRUISE_BUTTON_TIMERS = {
  int(ButtonType.decelCruise): 0,
  int(ButtonType.accelCruise): 0,
  int(ButtonType.setCruise): 0,
  int(ButtonType.resumeCruise): 0,
  int(ButtonType.cancel): 0,
  int(ButtonType.mainCruise): 0,
  int(ButtonType.gapAdjustCruise): 0,
  int(ButtonType.lkas): 0,
}
SETTING_BUTTONS = frozenset({int(ButtonType.gapAdjustCruise), int(ButtonType.lkas)})
# Buttons that move the ACC set speed or cancel it; only these cancel ICBM launch and the gas-release floor.
SPEED_BUTTONS = frozenset(set(CRUISE_BUTTON_TIMERS) - SETTING_BUTTONS)


def select_redneck_target_speed(v_cruise_kph: float, speed_cluster_ms: float,
                                starpilot_target_speed_ms: float, plan_speeds_ms: list[float],
                                lookahead_points: int, allow_plan_decrease: bool = True,
                                lead_present: bool = False, lead_distance_m: float = 0.0,
                                lead_rel_speed_ms: float = 0.0,
                                lead_speed_ms: float | None = None,
                                slc_target_speed_ms: float = 0.0,
                                csc_target_speed_ms: float = 0.0,
                                lead_corroborated: bool = False) -> float:
  target_speed_ms = float(speed_cluster_ms)
  if slc_target_speed_ms > 0:
    target_speed_ms = float(slc_target_speed_ms)
    # SLC is an upper bound for the button-spammed stock setpoint. A driver-set
    # speed below the posted target must still be able to slow the car down.
    if 0 < v_cruise_kph < V_CRUISE_UNSET:
      target_speed_ms = min(target_speed_ms, float(v_cruise_kph) * CV.KPH_TO_MS)
  elif v_cruise_kph > 0:
    target_speed_ms = float(v_cruise_kph) * CV.KPH_TO_MS
  elif starpilot_target_speed_ms > 0:
    target_speed_ms = float(starpilot_target_speed_ms)

  # Curve Speed Control publishes its own target (starpilotPlan.cscSpeed). The branches above
  # use the driver set speed or SLC and never see it, so apply it here as a cap only.
  if csc_target_speed_ms > 0:
    target_speed_ms = min(target_speed_ms, float(csc_target_speed_ms))

  lead_closing = lead_present and lead_rel_speed_ms < -LEAD_CLOSING_REL_SPEED_MIN_MS
  # ICBMFarLead: inf (no effect) unless card.py passed the lead speed and the lead is closing.
  far_lead_target_ms = float("inf")
  if lead_closing and lead_speed_ms is not None:
    far_lead_target_ms = get_far_lead_target_ms(lead_distance_m, lead_speed_ms, lead_corroborated)

  if allow_plan_decrease and len(plan_speeds_ms) > 0:
    if lead_present and not lead_closing and target_speed_ms > speed_cluster_ms and plan_speeds_ms[0] > speed_cluster_ms:
      recovery_lookahead_points = min(len(plan_speeds_ms), LEAD_RECOVERY_LOOKAHEAD_POINTS)
      recovery_target_speed_ms = max(speed_cluster_ms, min(plan_speeds_ms[:recovery_lookahead_points]))
      departure_boost_ms = get_lead_departure_boost_ms(
        speed_cluster_ms,
        lead_distance_m,
        lead_rel_speed_ms,
        plan_speeds_ms,
      )
      if departure_boost_ms > 0.0:
        recovery_target_speed_ms = max(recovery_target_speed_ms, speed_cluster_ms + departure_boost_ms)
      return min(target_speed_ms, recovery_target_speed_ms, far_lead_target_ms)

    decrease_target_speed_ms = min(plan_speeds_ms[:lookahead_points])
    lead_headway_s = lead_distance_m / speed_cluster_ms if lead_distance_m > 0.0 and speed_cluster_ms > 0.1 else float("inf")
    proactive_coast = lead_closing and lead_headway_s <= LEAD_PROACTIVE_COAST_HEADWAY_MAX_S

    if not proactive_coast and lead_present and target_speed_ms > speed_cluster_ms and \
        decrease_target_speed_ms >= speed_cluster_ms - LEAD_RECOVERY_HOLD_BUFFER_MS:
      return min(speed_cluster_ms, far_lead_target_ms)

    if lead_present and (decrease_target_speed_ms < speed_cluster_ms or proactive_coast):
      decrease_target_speed_ms = max(0.0, decrease_target_speed_ms - get_lead_coast_buffer_ms(
        speed_cluster_ms,
        lead_distance_m,
        lead_rel_speed_ms,
      ))

    if proactive_coast and target_speed_ms > speed_cluster_ms and \
        decrease_target_speed_ms >= speed_cluster_ms - LEAD_RECOVERY_HOLD_BUFFER_MS:
      return min(speed_cluster_ms, far_lead_target_ms)

    if decrease_target_speed_ms < target_speed_ms:
      return min(decrease_target_speed_ms, far_lead_target_ms)

  return min(target_speed_ms, far_lead_target_ms)


def get_lead_coast_buffer_ms(speed_cluster_ms: float, lead_distance_m: float, lead_rel_speed_ms: float) -> float:
  lead_closing_speed_ms = max(-float(lead_rel_speed_ms), 0.0)
  if lead_closing_speed_ms <= 0.0:
    return LEAD_COAST_BUFFER_MS

  headway_factor = 0.0
  if lead_distance_m > 0.0 and speed_cluster_ms > 0.1:
    headway_s = lead_distance_m / speed_cluster_ms
    headway_factor = min(max(
      (LEAD_EXTRA_COAST_HEADWAY_MAX_S - headway_s) /
      (LEAD_EXTRA_COAST_HEADWAY_MAX_S - LEAD_EXTRA_COAST_HEADWAY_MIN_S),
      0.0,
    ), 1.0)

  extra_buffer_ms = min(LEAD_EXTRA_COAST_BUFFER_MAX_MS, lead_closing_speed_ms * LEAD_EXTRA_COAST_BUFFER_FACTOR)
  return LEAD_COAST_BUFFER_MS + extra_buffer_ms * (0.5 + (0.5 * headway_factor))


def is_far_lead_corroborated(radar: bool, model_prob: float) -> bool:
  """A lead whose range and closing speed are trusted for the lower far-lead decel: radar-backed, or a
  confident vision lead."""
  return bool(radar) or float(model_prob) >= FAR_LEAD_CORROBORATED_MODEL_PROB


def get_far_lead_target_ms(lead_distance_m: float, lead_speed_ms: float, corroborated: bool = False) -> float:
  """Speed from which a constant decel (FAR_LEAD_DECEL_MS2 for a corroborated lead, else
  FAR_LEAD_UNCORROBORATED_DECEL_MS2) reaches lead_speed_ms at the desired gap. inf if no lead."""
  if lead_distance_m <= 0.0:
    return float("inf")
  decel_ms2 = FAR_LEAD_DECEL_MS2 if corroborated else FAR_LEAD_UNCORROBORATED_DECEL_MS2
  lead_speed_ms = max(float(lead_speed_ms), 0.0)
  gap_m = max(FAR_LEAD_MIN_GAP_M, FAR_LEAD_HEADWAY_S * lead_speed_ms)
  return math.sqrt(max(0.0, lead_speed_ms ** 2 + 2.0 * decel_ms2 * (lead_distance_m - gap_m)))


def get_model_only_far_lead_target_ms(lead) -> float:
  """Far-lead target for a vision-only radarState lead the planner ignores (route 276 8:27.9). inf unless the
  lead is vision-only, confident (modelProb >= FAR_LEAD_MODEL_ONLY_PROB) and closing faster than
  FAR_LEAD_MODEL_ONLY_CLOSING_MS. Always the uncorroborated decel."""
  if lead is None or not getattr(lead, "status", False) or getattr(lead, "radar", False):
    return float("inf")
  if float(getattr(lead, "modelProb", 0.0)) < FAR_LEAD_MODEL_ONLY_PROB or \
      float(lead.vRel) >= -FAR_LEAD_MODEL_ONLY_CLOSING_MS:
    return float("inf")
  return get_far_lead_target_ms(max(float(lead.dRel), 0.0), float(lead.vLead), corroborated=False)


def lead_key(lead) -> tuple | None:
  """(radar, track id, dRel, vRel) of a published lead, None if there is none."""
  if lead is None or not getattr(lead, "status", False):
    return None
  radar = bool(getattr(lead, "radar", False))
  return radar, int(getattr(lead, "radarTrackId", -1)) if radar else -1, float(lead.dRel), float(getattr(lead, "vRel", 0.0))


def lead_changed(prev_key: tuple | None, key: tuple | None, v_ego: float = 0.0) -> bool:
  """True when a lead was lost, or changed source (radar/vision), radar track id, or range by more than
  LEAD_CHANGE_RANGE_JUMP_M. A new lead appearing is not a change: it can only lower the target. A source flip
  within the range jump with neither side closing faster than LEAD_SOURCE_FLIP_CLOSING_MS is the same car
  (route 277 3:51.5), not a change."""
  if prev_key is None:
    return False
  if key is None:
    return True
  if abs(prev_key[2] - key[2]) > LEAD_CHANGE_RANGE_JUMP_M:
    return True
  if prev_key[0] != key[0]:
    near = min(prev_key[2], key[2]) < LEAD_SOURCE_FLIP_MIN_HEADWAY_S * max(float(v_ego), 1.0)
    return near or min(prev_key[3], key[3]) < -LEAD_SOURCE_FLIP_CLOSING_MS
  return prev_key[1] != key[1]


def closing_target_in_path(radar_leads, model_leads, v_ego: float, model_v_ego: float | None = None) -> bool:
  """A path-relative target within INCREASE_BLOCK_RANGE_M closing faster than INCREASE_BLOCK_CLOSING_MS:
  a published radarState lead, or the model's current lead (modelV2.leadsV3[0]) with prob >=
  INCREASE_BLOCK_MODEL_PROB."""
  for lead in radar_leads:
    if lead is not None and getattr(lead, "status", False) and 0.0 < float(lead.dRel) <= INCREASE_BLOCK_RANGE_M and \
        float(lead.vRel) < -INCREASE_BLOCK_CLOSING_MS:
      return True
  if model_leads is not None and len(model_leads) > 0:
    lead = model_leads[0]
    if float(lead.prob) >= INCREASE_BLOCK_MODEL_PROB and len(lead.x) and len(lead.v):
      d_rel = float(lead.x[0]) - MODEL_LEAD_RADAR_TO_CAMERA_M
      v_ref = float(v_ego if model_v_ego is None else model_v_ego)
      if 0.0 < d_rel <= INCREASE_BLOCK_RANGE_M and float(lead.v[0]) - v_ref < -INCREASE_BLOCK_CLOSING_MS:
        return True
  return False


class IncreaseBlock:
  """Caps the ICBM target at the cluster set speed for INCREASE_BLOCK_AFTER_LEAD_CHANGE_S after a lead change
  and while a path-relative target is closing (route 276 14:36.7, 17:22.5). Never lowers a target."""
  def __init__(self):
    self.prev_key = None
    self.prev_has_lead = False
    self.frames = 0

  def update(self, lead, has_lead: bool, closing: bool, v_ego: float = 0.0) -> bool:
    key = lead_key(lead)
    if lead_changed(self.prev_key, key, v_ego) or (self.prev_has_lead and not has_lead):
      self.frames = int(INCREASE_BLOCK_AFTER_LEAD_CHANGE_S / DT_CTRL)
    elif self.frames > 0:
      self.frames -= 1
    self.prev_key = key
    self.prev_has_lead = bool(has_lead)
    return closing or self.frames > 0

  @staticmethod
  def apply(target_ms: float, speed_cluster_ms: float, blocked: bool) -> float:
    if not blocked or speed_cluster_ms <= 0.0:
      return float(target_ms)
    return min(float(target_ms), float(speed_cluster_ms))


def get_lead_departure_boost_ms(speed_cluster_ms: float, lead_distance_m: float, lead_rel_speed_ms: float,
                                plan_speeds_ms: list[float]) -> float:
  if lead_rel_speed_ms < LEAD_DEPARTURE_REL_SPEED_MIN_MS or speed_cluster_ms <= 0.1 or lead_distance_m <= 0.0:
    return 0.0

  plan_points = min(len(plan_speeds_ms), LEAD_DEPARTURE_PLAN_POINTS)
  if plan_points <= 0 or min(plan_speeds_ms[:plan_points]) <= speed_cluster_ms:
    return 0.0

  headway_s = lead_distance_m / speed_cluster_ms
  if headway_s < LEAD_DEPARTURE_HEADWAY_MIN_S:
    return 0.0

  headway_factor = min(max(
    (headway_s - LEAD_DEPARTURE_HEADWAY_MIN_S) /
    (LEAD_DEPARTURE_HEADWAY_MAX_S - LEAD_DEPARTURE_HEADWAY_MIN_S),
    0.0,
  ), 1.0)
  extra_boost_ms = max(lead_rel_speed_ms - LEAD_DEPARTURE_REL_SPEED_MIN_MS, 0.0) * LEAD_DEPARTURE_BOOST_FACTOR
  boost_ms = LEAD_DEPARTURE_BOOST_MIN_MS + extra_boost_ms * (0.5 + (0.5 * headway_factor))
  return min(boost_ms, LEAD_DEPARTURE_BOOST_MAX_MS)


def get_minimum_set_speed(is_metric: bool, brand: str = "") -> int:
  # Honda stock ACC will not hold a set speed below 25 mph, so asking for less
  # just spams DECEL_SET into a floor the car ignores.
  if brand == "honda":
    return HONDA_MINIMUM_SET_SPEED_KPH if is_metric else HONDA_MINIMUM_SET_SPEED_MPH
  return 30 if is_metric else 20


def update_launch_state(launch_active: bool, was_stopped: bool, enabled: bool, v_ego: float, standstill: bool,
                        gas_pressed: bool, driver_button: bool, launch_target_ms: float,
                        set_speed_ms: float | None = None, hold_target_ms: float | None = None,
                        lead_cap_ms: float = float("inf")) -> tuple[bool, bool]:
  """Returns (launch_active, was_stopped). A launch never starts while the car is stopped, so ICBM does
  not press RES+ at standstill (on a Honda that resumes the car by itself). lead_cap_ms: close_lead_cap_ms;
  once the set has reached it and the car has caught up with the lead's speed, the launch ends and ICBM
  follows the lead-driven target (route 277 16:34.1)."""
  if not enabled or driver_button:
    return False, False
  if standstill or v_ego < LAUNCH_STOPPED_SPEED_MS:
    return False, True
  if was_stopped and v_ego >= LAUNCH_MOVING_SPEED_MS and not gas_pressed:
    launch_active, was_stopped = True, False
  if launch_active and v_ego >= launch_target_ms - LAUNCH_CAUGHT_UP_MARGIN_MS:
    launch_active = False
  if launch_active and set_speed_ms is not None and hold_target_ms is not None and \
      set_speed_ms >= launch_target_ms - LAUNCH_CAUGHT_UP_MARGIN_MS and \
      v_ego >= hold_target_ms - LAUNCH_CAUGHT_UP_MARGIN_MS:
    launch_active = False
  if launch_active and set_speed_ms is not None and lead_cap_ms < launch_target_ms and \
      lead_cap_ms - LAUNCH_LEAD_SPEED_MARGIN_MS >= HONDA_MINIMUM_SET_SPEED_MPH * CV.MPH_TO_MS and \
      set_speed_ms >= lead_cap_ms - LAUNCH_CAUGHT_UP_MARGIN_MS and \
      v_ego >= lead_cap_ms - LAUNCH_LEAD_SPEED_MARGIN_MS - LAUNCH_CAUGHT_UP_MARGIN_MS:
    launch_active = False
  return launch_active, was_stopped


def close_lead_cap_ms(lead, v_ego: float, normal_target_ms: float) -> float:
  """Cap for the launch target behind a close lead (route 277 16:34.1): max(normal
  target, vLead + LAUNCH_LEAD_SPEED_MARGIN_MS) while a corroborated leadOne is within LAUNCH_LEAD_CAP_RANGE_M
  or LAUNCH_LEAD_CAP_HEADWAY_S; inf otherwise."""
  if lead is None or not getattr(lead, "status", False) or \
      not is_far_lead_corroborated(getattr(lead, "radar", False), getattr(lead, "modelProb", 0.0)):
    return float("inf")
  d_rel = float(lead.dRel)
  if d_rel > max(LAUNCH_LEAD_CAP_RANGE_M, LAUNCH_LEAD_CAP_HEADWAY_S * max(float(v_ego), 0.0)):
    return float("inf")
  return max(float(normal_target_ms), max(float(lead.vLead), 0.0) + LAUNCH_LEAD_SPEED_MARGIN_MS)


def update_gas_release_floor(floor_ms: float, gas_pressed_prev: bool, gas_pressed: bool, enabled: bool, v_ego: float,
                             standstill: bool, brake_pressed: bool, driver_button: bool, set_speed_ms: float,
                             is_metric: bool, snapped: bool = False) -> float:
  """Returns the ICBM target floor in m/s (0 = none). The caller caps it at the cruise target. snapped: a gas
  snap raised the set speed during this press, so the release is floored even with the set already near vEgo."""
  if not enabled or driver_button or brake_pressed or standstill or v_ego < LAUNCH_STOPPED_SPEED_MS:
    return 0.0
  if gas_pressed_prev and not gas_pressed and (snapped or v_ego > set_speed_ms + GAS_RELEASE_SET_MARGIN_MS):
    if is_metric:
      return round(v_ego * CV.MS_TO_KPH) * CV.KPH_TO_MS
    return round(v_ego * CV.MS_TO_MPH) * CV.MPH_TO_MS
  return floor_ms


def gas_release_floor_expired(age_s: float, lead_present: bool, lead_rel_speed_ms: float, normal_target_ms: float,
                              floored_target_ms: float, lead_distance_m: float = 0.0, v_ego: float = 0.0) -> bool:
  """True once the gas-release floor should be dropped: GAS_RELEASE_FLOOR_MAX_S after the release, or when
  a closing lead beyond GAS_RELEASE_FLOOR_LEAD_HEADWAY_S wants the set speed below the floored target."""
  if age_s > GAS_RELEASE_FLOOR_MAX_S:
    return True
  lead_closing = lead_present and lead_rel_speed_ms < -LEAD_CLOSING_REL_SPEED_MIN_MS
  lead_far = lead_distance_m > GAS_RELEASE_FLOOR_LEAD_HEADWAY_S * max(v_ego, 1.0)
  return lead_closing and lead_far and normal_target_ms < floored_target_ms


def want_gas_snap(enabled: bool, gas_pressed: bool, driver_button: bool, brake_pressed: bool, v_ego: float,
                  set_speed_ms: float, cap_ms: float) -> bool:
  return enabled and gas_pressed and not driver_button and not brake_pressed and \
    set_speed_ms + GAS_RELEASE_SET_MARGIN_MS < v_ego <= cap_ms


def update_manual_button_timers(CS: car.CarState, button_timers: dict[int, int], button_held: dict[int, int]) -> None:
  """button_held[t] counts frames since the press edge (0 = not held); button_timers[t] counts frames
  since the release edge (0 = never released or a new press). Both advance once per frame."""
  for button_type in button_timers:
    if button_held[button_type] > 0:
      button_held[button_type] += 1
    if button_timers[button_type] > 0:
      button_timers[button_type] += 1

  for event in CS.buttonEvents:
    button_type = event.type.raw if hasattr(event.type, "raw") else int(event.type)
    if button_type in button_timers:
      if event.pressed:
        button_held[button_type] = 1
        button_timers[button_type] = 0
      else:
        button_held[button_type] = 0
        button_timers[button_type] = 1


def manual_button_active(button_timers: dict[int, int], button_held: dict[int, int]) -> bool:
  """True while any cruise button is physically held (up to MANUAL_BUTTON_HELD_MAX_S, after which a
  missed release is assumed) and for MANUAL_BUTTON_INACTIVE_TIMER (SETTING_BUTTON_INACTIVE_TIMER for
  distance/LKAS) after its release."""
  held_max = int(MANUAL_BUTTON_HELD_MAX_S / DT_CTRL)
  release_max = int(MANUAL_BUTTON_INACTIVE_TIMER / DT_CTRL)
  setting_release_max = int(SETTING_BUTTON_INACTIVE_TIMER / DT_CTRL)
  return any(0 < held <= held_max for held in button_held.values()) or \
    any(0 < timer <= (setting_release_max if button in SETTING_BUTTONS else release_max)
        for button, timer in button_timers.items())


def is_speed_button_press(button_events) -> bool:
  """A driver press of a set-speed or cancel button. Distance and LKAS presses are excluded: they do not
  move the set speed, so they must not cancel ICBM launch or clear the gas-release floor."""
  for event in button_events:
    if not getattr(event, "pressed", False):
      continue
    button_type = event.type.raw if hasattr(event.type, "raw") else int(event.type)
    if button_type not in SETTING_BUTTONS:
      return True
  return False


class RedneckCruise:
  def __init__(self, CP, FPCP):
    self.CP = CP
    self.FPCP = FPCP

    self.v_target = 0
    self.v_target_ms_last = 0.0
    self.v_cruise_cluster = 0
    self.v_cruise_min = 0
    self.state = "inactive"
    self.pre_active_timer = 0
    self.is_ready = False
    self.is_ready_prev = False
    self.cruise_button_timers = dict(CRUISE_BUTTON_TIMERS)
    self.cruise_button_held = dict(CRUISE_BUTTON_TIMERS)
    self.manual_button_pressed = False
    self.gas_snap_frame = 0
    self.press_frames = 0
    self.idle_frames = int(PRESS_SETTLE_S / DT_CTRL)
    self.frames_since_decrease = int(INCREASE_AFTER_DECREASE_LOCKOUT_S / DT_CTRL)

  @staticmethod
  def _send_button_for_state(state: str) -> int:
    if state == "increasing":
      return SEND_BUTTON_INCREASE
    if state == "decreasing":
      return SEND_BUTTON_DECREASE
    return SEND_BUTTON_NONE

  def _reset(self) -> None:
    self.state = "inactive"
    self.pre_active_timer = 0
    self.is_ready = False
    self.is_ready_prev = False

  def _update_calculations(self, CS: car.CarState, v_target_ms: float, is_metric: bool) -> None:
    speed_conv = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH
    ms_conv = CV.KPH_TO_MS if is_metric else CV.MPH_TO_MS

    self.v_target_ms_last = apply_hysteresis(v_target_ms, self.v_target_ms_last, HYST_GAP * ms_conv)
    self.v_target = round(self.v_target_ms_last * speed_conv)
    self.v_cruise_min = get_minimum_set_speed(is_metric, getattr(self.CP, "brand", ""))
    cluster = CS.cruiseState.speedCluster * speed_conv
    if not is_metric and getattr(self.CP, "brand", "") == "honda":
      cluster += HONDA_KPH_TRUNCATION_MPH
    self.v_cruise_cluster = round(cluster)
    # The hold branches of select_redneck_target_speed return the cluster speed itself. On a Honda in mph
    # that is the truncated km/h value, which rounds one mph lower than the truncation-corrected cluster
    # for about a third of set speeds (49 mph -> 78 km/h -> 48.47 mph: target 48, cluster 49), so "hold"
    # pressed DECEL, the next branch pressed RES+ and the pair repeated. Route 271 seg28+36.7 (replay):
    # 34 reversals in 45 s cycling 48 <-> 49 mph behind a lead pulling away. A target equal to the cluster
    # is a hold.
    if abs(v_target_ms - CS.cruiseState.speedCluster) < 1e-3:
      self.v_target = self.v_cruise_cluster

  def _update_readiness(self, CS: car.CarState, CC: car.CarControl) -> None:
    update_manual_button_timers(CS, self.cruise_button_timers, self.cruise_button_held)
    button_pressed = manual_button_active(self.cruise_button_timers, self.cruise_button_held)
    self.manual_button_pressed = button_pressed
    # cruiseControl.override is only set under openpilot long, so the stock-ACC gas override is
    # checked directly. Honda DECEL/SET under gas snaps the set speed to vEgo (route 260 seg 6/9:
    # 39 -> 25 mph at 14 mph, 29 -> 32 mph while ICBM was decreasing).
    self.is_ready = CC.enabled and not CC.cruiseControl.override and not CC.cruiseControl.cancel and not CC.cruiseControl.resume and \
      not button_pressed and not getattr(CS, "gasPressed", False)

  def _desired_state(self) -> str:
    if self.v_target > self.v_cruise_cluster:
      return "increasing"
    if self.v_target < self.v_cruise_cluster and self.v_cruise_cluster > self.v_cruise_min:
      return "decreasing"
    return "holding"

  @staticmethod
  def _get_pre_active_frames(state: str, lead_present: bool) -> int:
    if state == "decreasing":
      timer = DECREASE_INACTIVE_TIMER
    elif lead_present:
      timer = LEAD_INCREASE_INACTIVE_TIMER
    else:
      timer = INCREASE_INACTIVE_TIMER
    return int(timer / DT_CTRL)

  def _arm_pre_active(self, desired_state: str, lead_present: bool) -> None:
    if desired_state == "holding":
      self.state = "holding"
      self.pre_active_timer = 0
      return

    self.state = "preActive"
    self.pre_active_timer = self._get_pre_active_frames(desired_state, lead_present)

  def _update_state_machine(self, lead_present: bool) -> int:
    desired_state = self._desired_state()

    if not self.is_ready:
      self.state = "inactive"
      self.pre_active_timer = 0
    elif self.state == "inactive":
      if not self.is_ready_prev:
        self._arm_pre_active(desired_state, lead_present)
    elif self.state == "preActive":
      if desired_state == "holding":
        self.state = "holding"
        self.pre_active_timer = 0
      else:
        desired_frames = self._get_pre_active_frames(desired_state, lead_present)
        self.pre_active_timer = max(0, min(self.pre_active_timer, desired_frames) - 1)
        if self.pre_active_timer <= 0:
          self.state = desired_state
    elif self.state == "holding":
      if desired_state != "holding":
        self._arm_pre_active(desired_state, lead_present)
    elif self.state != desired_state:
      if desired_state == "holding":
        self.state = "holding"
      else:
        self._arm_pre_active(desired_state, lead_present)

    return self._send_button_for_state(self.state)

  def _gas_snap_button(self, CS: car.CarState, CC: car.CarControl, gas_snap: bool) -> int:
    # Pulsed, so a press never lands after the gas is released (without gas, DECEL_SET lowers the set speed).
    if not gas_snap or not getattr(CS, "gasPressed", False) or not CC.enabled or CC.cruiseControl.cancel or \
        CC.cruiseControl.resume or self.manual_button_pressed:
      self.gas_snap_frame = 0
      return SEND_BUTTON_NONE
    phase = self.gas_snap_frame % int(GAS_SNAP_INTERVAL_S / DT_CTRL)
    self.gas_snap_frame += 1
    return SEND_BUTTON_DECREASE if phase < int(GAS_SNAP_PRESS_S / DT_CTRL) else SEND_BUTTON_NONE

  def _pace_presses(self, send_button: int) -> int:
    """Counter sync only: settle-then-pulse for the last step, and no increase right after a decrease."""
    self.frames_since_decrease += 1
    if send_button == SEND_BUTTON_INCREASE and self.frames_since_decrease < int(INCREASE_AFTER_DECREASE_LOCKOUT_S / DT_CTRL):
      send_button = SEND_BUTTON_NONE
    if send_button != SEND_BUTTON_NONE and abs(self.v_target - self.v_cruise_cluster) <= 1:
      if self.press_frames == 0 and self.idle_frames < int(PRESS_SETTLE_S / DT_CTRL):
        send_button = SEND_BUTTON_NONE
      elif self.press_frames >= int(PRESS_PULSE_S / DT_CTRL):
        self.press_frames = 0
        send_button = SEND_BUTTON_NONE
    if send_button == SEND_BUTTON_NONE:
      self.press_frames = 0
      self.idle_frames += 1
    else:
      self.press_frames += 1
      self.idle_frames = 0
      if send_button == SEND_BUTTON_DECREASE:
        self.frames_since_decrease = 0
    return send_button

  def run(self, CS: car.CarState, CC: car.CarControl, v_target_ms: float, is_metric: bool,
          lead_present: bool = False, gas_snap: bool = False, counter_sync: bool = False) -> tuple[int, int]:
    if self.FPCP.pcmCruiseSpeed or not self.FPCP.redneckCruiseAvailable:
      self._reset()
      return SEND_BUTTON_NONE, 0

    self._update_calculations(CS, v_target_ms, is_metric)
    self._update_readiness(CS, CC)
    send_button = self._update_state_machine(lead_present)
    if counter_sync:
      send_button = self._pace_presses(send_button)
    snap_button = self._gas_snap_button(CS, CC, gas_snap)
    if snap_button != SEND_BUTTON_NONE:
      send_button = snap_button

    self.is_ready_prev = self.is_ready
    return send_button, self.v_target
