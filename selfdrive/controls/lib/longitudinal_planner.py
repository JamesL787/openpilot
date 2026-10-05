#!/usr/bin/env python3
import math
import numpy as np
import time
import cereal.messaging as messaging
from opendbc.car.honda.values import HONDA_BOSCH_A
from opendbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.starpilot.common.model_versions import is_tinygrad_model_version
from openpilot.starpilot.common.starpilot_variables import get_longitudinal_actuator_delay
from openpilot.starpilot.controls.lib.starpilot_vcruise import FT_TO_M, OFFSET_FT_MAX, OFFSET_FT_MIN
from openpilot.selfdrive.controls.lib.accel_boost import AccelBoost
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc, get_safe_obstacle_distance
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import desired_follow_distance
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import should_trigger_planner_fcw
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import STOP_DISTANCE
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.controls.lib.lead_behavior import is_radarless_matched_follow_window
from openpilot.selfdrive.controls.lib.lead_follow_policy import apply as apply_follow_policy
from openpilot.selfdrive.controls.lib.lead_follow_policy import is_nonurgent_duplicate_vision_follow
from openpilot.selfdrive.controls.lib.longitudinal_vehicle_tunes import (
  get_far_follow_output_slew_rates,
  get_follow_prebrake_min_headway,
  get_honda_accord_lead_departure_tune,
  get_honda_accord_stop_go_accel_cap,
  get_honda_accord_stop_go_accel_rise_rate,
  get_vision_low_speed_stop_buffer_lead_speed_limits,
  get_toyota_rav4_tss2_lead_departure_tune,
  get_toyota_rav4_tss2_lead_creep_tune,
  get_force_stop_distance_bias,
  get_force_stop_handoff_distance,
  get_stop_sign_low_speed_hold,
  allow_radar_standstill_gap_settle,
  is_gm_silverado_early_follow_lead,
  is_toyota_rav4_tss2_post_departure_tune,
  get_toyota_rav4_tss2_early_lead_cap,
  is_toyota_rav4_tss2_radar_follow_lead,
  get_toyota_sienna_post_departure_restop_cap,
  get_untracked_slow_lead_decel_scale,
  get_toyota_prius_stopped_lead_obstacle_bias,
  get_honda_crv_5g_stopped_lead_obstacle_bias,
  get_honda_crv_5g_low_speed_stopped_lead_cap,
  allow_honda_crv_5g_vision_gap_settle,
  get_honda_crv_5g_early_radar_follow_cap,
  get_standstill_gap_settle_max_extra_gap,
  get_standstill_stopped_lead_guard_distance_margin,
  get_standstill_stopped_lead_guard_max_ego_speed,
  get_standstill_stopped_lead_guard_max_lead_speed,
  is_ford_f150_lightning_stopped_radar_follow_lead,
  get_tracked_lead_catchup_bias_gain,
  get_tracked_lead_catchup_bias_cap,
  get_tracked_lead_catchup_speed_range,
  get_tracked_lead_catchup_fade_margins,
  get_tracked_lead_catchup_cruise_error_full,
  get_tracked_lead_catchup_headway_margins,
)
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET
from openpilot.common.swaglog import cloudlog
from cereal import log

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

# Lane-change merge assist: cap braking for a lead we're leaving and add a mild push.
LC_MERGE_STATES = (
  LaneChangeState.preLaneChange,
  LaneChangeState.laneChangeStarting,
  LaneChangeState.laneChangeFinishing,
)
LC_MERGE_CLOSING_MIN = 0.5
LC_MERGE_TTC_MIN = 4.0
LC_MERGE_MIN_DIST = 30.0
LC_MERGE_BRAKE_FLOOR = -0.4
LC_MERGE_TTC_ACCEL = 6.0
LC_MERGE_ACCEL_MIN_DIST = 30.0
LC_MERGE_HEADROOM_MIN = 2.0
LC_MERGE_ACCEL_BIAS = 0.55
# Late start (STATUS 119, replay evidence only, not driven). The final comfort-floor clip let
# MPC lead braking below the -1.0 cruise floor through only as a_desired (the MPC one step
# ahead, not at action_t) caught up, so the output trailed the MPC's own demand (items 45/46):
# 25e 318.1 MPC -1.5 at 319.0, stock ACC 319.92, output 320.92. A persistent lead-sourced MPC
# demand now passes that floor.
MPC_LEAD_BRAKE_PASSES_COMFORT_FLOOR = True
# The floor is also a spike filter: when the lead source switches (radar lead dropped, far
# vision lead picked up) the MPC can ask -1.6..-2.0 for one or two ticks with no closing
# speed (25f 634.9, 0237 796.0). Only a demand that has been lead-sourced for this many
# consecutive ticks from a closing or braking lead (the LEAD_CLOSING_FLOOR test) passes, and
# only its mildest value over those ticks.
MPC_LEAD_BRAKE_PERSIST_TICKS = 3
# Fast-closing pass (STATUS 150; open- and closed-loop replay only, not driven). 271 BM0 (route
# 00000271 seg9+28.4, a near-stopped car at 105 m closing 20 m/s): after the D-053 rail fast
# path corrected vRel, the output sat at the -1.0 comfort floor from -3.19 to -2.79 s before
# the bookmark. A per-line trace shows what held it: the close-lead brake cap asked about -2.3
# but is built against the comfort floor (`get_close_lead_brake_cap(..., output_accel_min)`),
# while the MPC itself was still ramping from its cruise-to-lead source switch (-0.13 ... -0.97)
# and so was above -1.0 the whole time; the persistence pass above never had anything to pass.
# Opening the floor for every closing lead (STATUS 120 F2/F2L) added ~39 new hard brakes, so
# the cap may pass the comfort floor only for a lead that is closing fast, is short on time, is
# the lead the MPC is braking for, and that vision sees closing too:
#   radar lead, -vRel >= FAST_CLOSING_LEAD_MIN_CLOSING, dRel / -vRel <= FAST_CLOSING_LEAD_MAX_TTC,
#   mpc.source is this lead, and the model lead (prob >= FAST_CLOSING_LEAD_MIN_VISION_PROB,
#   x within FAST_CLOSING_LEAD_VISION_MATCH of dRel) closes at >= FAST_CLOSING_LEAD_MIN_VISION_CLOSING.
# The vision test is what keeps a U11 rail phantom (-13.5 m/s published on a flat range, 276
# 13:46.6) out: vision sees no closing there. Replayed without it (28 routes) the pass made 4 more
# new -1.5 crossings, e.g. 0261 413.7 -2.72 and 025f 43.5 -2.73 where stock ACC held 0.09 / -0.50.
# 10 m/s and 6 s: every entry on the 28 routes is a lead at 31-105 m closing 10-21 m/s; 8 m/s /
# 7 s moved 2 more brakes earlier and deepened 3 more, with the same new crossings. The floor
# then opens to the cap's own value, not to the vehicle minimum. Once fired it stays for the same track while it still closes at
# >= FAST_CLOSING_LEAD_HOLD_CLOSING, so the brake does not snap back to -1.0 as soon as the
# closing speed dips under the entry value. A first version held while the lead was closing at
# all (LEAD_CLOSING_FLOOR test): on 0237 it kept the pass 8 s after entry and made a new -1.56
# at 1201.6 on a lead closing 4.7 m/s at 28 m, where the logged alpha build commanded -0.65.
FAST_CLOSING_LEAD_PASSES_COMFORT_FLOOR = True
FAST_CLOSING_LEAD_MIN_CLOSING = 10.0
FAST_CLOSING_LEAD_HOLD_CLOSING = 5.0
FAST_CLOSING_LEAD_MAX_TTC = 6.0
FAST_CLOSING_LEAD_MIN_VISION_PROB = 0.5
FAST_CLOSING_LEAD_MIN_VISION_CLOSING = 6.0
FAST_CLOSING_LEAD_VISION_MATCH = 0.15
# The vision test passed in one tick and mpc.source == this lead in another is still entry, if they
# are at most FAST_CLOSING_LEAD_VISION_MEMORY_TICKS apart on the same radar track (closing speed and
# TTC are tested in the entry tick itself). STATUS 204: 26b 2233.6-2233.8 the model lead matched dRel
# within 15 % for five ticks only; mpc.source flickered lead0/cruise across them, and whether it read
# lead0 in the last matching tick (2233.84) decided between -1.9 and -1.1 for 2 s on a lead closing
# 11 m/s at 52 m. A 0.003 m/s^2 difference in MPC warm start three seconds earlier was enough to flip
# it. The rail-phantom guard is unchanged: such a lead never passes the vision test at all.
FAST_CLOSING_LEAD_VISION_MEMORY_TICKS = 5
# The pass is built against max(vehicle minimum, -FAST_CLOSING_LEAD_MAX_BRAKE), not the vehicle minimum (STATUS 150).
# Uncapped, the pass was held because the owner reported rough braking, and on the current tree it still deepened 22
# approaches (frames < -3.0 1363 -> 1626 over 32 routes). Capped at -2.0 it brakes earlier and softer instead: fleet
# frames < -3.0 1363 -> 1328, and in closed loop 271 BM0 peaks at -3.05 with a 13.5 m gap instead of -5.68 / 9.0 m.
# 0 restores the uncapped pass; 1.5 changed nothing on the fleet.
FAST_CLOSING_LEAD_MAX_BRAKE = 2.0
# The merge floor (-0.4) let go only under a 4 s TTC at the current closing speed; on 25b
# 1338.6 it held -0.4 for 1.3 s while the MPC asked -1.5..-4.2 and the lead braked 3-5 m/s^2,
# 0.85 s behind stock ACC. It now lets go when the MPC asks this much inside LC_MERGE_TTC_ACCEL.
LC_MERGE_RELEASE_MPC_DEMAND = -1.5
# Route 00000293 (owner-bookmarked, both called bad): the TTC gates above use the current closing speed only.
# 10:48 (left change): the floor held -0.4 for ~1 s while the lead braked at aLeadK -1.2..-3.5 and closed
# 1 -> 5 m/s at TTC 6-8 s; it let go only at dRel 30 and the car went straight to -3.5 (aEgo -4.0).
# A lead braking harder than this now releases the floor, so the MPC starts on it while it is still far.
LC_MERGE_RELEASE_LEAD_BRAKE = -1.0
# 29:12 (right change): the +0.55 push held for ~4 s toward a car 49-72 m ahead closing at 2-6.4 m/s
# (TTC 7.6 s) until the change finished, then -1.4 (aEgo -2.0). The push is now withheld while closing
# faster than this on the lead; the -0.4 floor still applies.
LC_MERGE_PUSH_MAX_CLOSING = 3.0

A_CRUISE_MAX_BP = [0.0, 5., 10., 15., 20., 25., 40.]
A_CRUISE_MAX_VALS = [1.125, 1.125, 1.125, 1.125, 1.25, 1.25, 1.5]
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
ALLOW_THROTTLE_THRESHOLD = 0.4
ALLOW_THROTTLE_HYSTERESIS = 0.05
ALLOW_THROTTLE_ENABLE_THRESHOLD = ALLOW_THROTTLE_THRESHOLD + ALLOW_THROTTLE_HYSTERESIS
ALLOW_THROTTLE_DISABLE_THRESHOLD = ALLOW_THROTTLE_THRESHOLD - ALLOW_THROTTLE_HYSTERESIS
ALLOW_THROTTLE_TRANSITION_CONFIRM_TIME = 0.25
MIN_ALLOW_THROTTLE_SPEED = 5.0
FORCE_DECEL_MIN_ACCEL = -0.05
MODEL_LAUNCH_DISARM_SPEED = 2.0
MODEL_LAUNCH_COMMIT_TIME = 3.5
MODEL_LAUNCH_MOVING_SPEED = 1.2
MODEL_LAUNCH_MAX_ACCEL = 1.5
RAW_LEAD_SAFETY_MIN_CLOSING_SPEED = 0.5
RAW_LEAD_SAFETY_TTC = 7.0
RAW_LEAD_SAFETY_DISTANCE = 40.0
RAW_RADAR_STOPPED_LEAD_MAX_SPEED = 1.0
RAW_RADAR_STOPPED_LEAD_MAX_DISTANCE = 120.0
RAW_LEAD_LOW_SPEED_HOLD_MAX_EGO_SPEED = 4.5
RAW_LEAD_LOW_SPEED_HOLD_MAX_LEAD_SPEED = 3.5
RAW_LEAD_LOW_SPEED_HOLD_MAX_DISTANCE = 10.0
RAW_LEAD_LOW_SPEED_HOLD_MAX_LATERAL_OFFSET = 1.75
RAW_LEAD_LOW_SPEED_HOLD_MIN_CLOSING_SPEED = 0.15
# Stopped/slow radar lead approach hold (26c 4:26 surge). lead_control_active is tracking_lead (radar dRel <
# model plan length + 6 m, starpilot_planner/should_track_lead) OR raw_close_lead_needs_control (TTC < 7 s or
# aLeadK < -0.5, inside max(40 m, 3 v; 5 v for a stopped radar lead)). Approaching a stopped car, the model plans to stop short of it, so its plan length
# sits at or below dRel - 6 m and tracking_lead drops; and the braking that the lead caused lengthens the TTC
# past 7 s and lets aLeadK settle, so the raw path drops too. The lead is still there and ego still closes on it,
# but the MPC loses it (source `cruise`) and plans acceleration toward it: route 0000026c--10bec2e200 replay
# 270.2-271.5, command -1.00 -> +1.24 at 2.4 m/s with a stopped radar+vision lead 22 m ahead; 758.9-761.4, three
# release/re-engage cycles between -0.3 and -1.2 on a stopped lead 60-75 m ahead at 8 m/s. The hold keeps a lead
# that was ALREADY controlling in control while it stays the same radar track, vision-matched, in lane, slow and
# not pulling away. It never admits a lead that was not controlling, so it cannot create a far stopped-lead
# brake on its own (phantom stationary returns are the reason the entry gates are strict), and it only preserves
# the authority the lead already had (D-048: vision corroboration is required to keep it).
# Ego speed cap: without it, replay on 22 routes added 6 new <= -1.5 clusters at 8.6-11.5 m/s approaching stopped
# queues 47-72 m ahead (00000232 1232.9, 00000236 416.2, 00000239 206.5, 0000026c 758.8). Below 5 m/s the hold
# keeps the 4:26 fix; the 12:28 pumping at 8 m/s is left to the normal gates.
STOPPED_RADAR_LEAD_HOLD_MAX_EGO_SPEED = 5.0
STOPPED_RADAR_LEAD_HOLD_MAX_LEAD_SPEED = 3.5
STOPPED_RADAR_LEAD_HOLD_MIN_CLOSING_SPEED = -0.5
STOPPED_RADAR_LEAD_HOLD_MAX_LATERAL_OFFSET = 1.75
STOPPED_RADAR_LEAD_HOLD_MIN_MODEL_PROB = 0.5
STANDSTILL_LEAD_NUDGE_ACCEL = 0.05
STANDSTILL_LEAD_NUDGE_MIN_SPEED = 0.0
STANDSTILL_LEAD_NUDGE_MIN_LEAD_ACCEL = 0.2
STANDSTILL_LEAD_DEPART_MIN_ACCEL = 0.35
STANDSTILL_LEAD_DEPART_MAX_EGO_SPEED = 1.5
STANDSTILL_LEAD_DEPART_MIN_LEAD_SPEED = 0.6
STANDSTILL_LEAD_DEPART_MIN_GAP_MARGIN = 0.8
STANDSTILL_LEAD_DEPART_MIN_MODEL_ACCEL = 0.08
STANDSTILL_LEAD_CREEP_RELEASE_MIN_ACCEL = 0.18
STANDSTILL_LEAD_CREEP_RELEASE_CONFIRM_TIME = 0.30
RADAR_STANDSTILL_GAP_SETTLE_ACCEL = 0.18
LEAD_DEPART_CONFIDENT_CONFIRM_TIME = 0.35
LEAD_DEPART_RELEASE_HOLD_TIME = 1.5
LEAD_DEPART_RELEASE_HOLD_CONFIRM_TIME = 0.15
STANDSTILL_STOPPED_LEAD_GUARD_MAX_EGO_SPEED = 0.5
STANDSTILL_STOPPED_LEAD_GUARD_MAX_LEAD_SPEED = 0.45
STANDSTILL_STOPPED_LEAD_GUARD_MAX_LEAD_DELTA = 0.50
STANDSTILL_STOPPED_LEAD_GUARD_MIN_MODEL_PROB = 0.95
STANDSTILL_STOPPED_LEAD_GUARD_MAX_LATERAL_OFFSET = 1.75
STANDSTILL_STOPPED_LEAD_GUARD_MIN_DISTANCE = 3.0
STANDSTILL_STOPPED_LEAD_GUARD_DISTANCE_MARGIN = 3.0
STANDSTILL_STOPPED_LEAD_GUARD_MIN_BRAKE = 0.16
STANDSTILL_STOPPED_LEAD_GUARD_MAX_BRAKE = 0.26
LEAD_DEPART_ACCEL_HOLD_TIME = 1.2
LEAD_DEPART_ACCEL_HOLD_MAX_EGO_SPEED = 2.0
# Engagement horizon for the close-lead brake cap. Was 25.0 s, which is not "close" by any reading of
# the name: on Peter route 000001eb at 5:48 it engaged on a lead 71.1 m away at 15.2 s TTC and pulled
# commanded accel from +0.89 to -0.32 while the MPC itself still reported source `cruise`. 8.0 s sits
# with this file's other lead-safety horizons (RAW_LEAD_SAFETY_TTC 7.0, FCW_MAX_TTC 4.0) and still
# engages on the genuine close approaches (000001e8 at 9:00 gates at 5.5 s) and keeps the
# existing 9.2 s vision-approach behaviour, while clearing 000001eb 5:48 (15.2 s) and its
# rubber-banding neighbour (17.6 s) with margin.
CLOSE_LEAD_BRAKE_CAP_MAX_TTC = 10.0

# The cap used to be a step: nothing below required_decel 0.2, full demand at and above it. That
# discontinuity is the accel->decel->accel cycling reported as rubber banding -- 000001eb at 5:48
# shows it toggling off/on/off inside 1.2 s as required_decel crosses 0.2. Ramp the demand in over a
# band instead, so a marginal geometry produces a marginal cap rather than a step.
# Telemetry-only reference geometry (see get_lead_geometry_required_accel).
LEAD_GEOMETRY_STANDOFF_M = 4.0
LEAD_GEOMETRY_MIN_GAP_M = 0.5
LEAD_GEOMETRY_MIN_LEAD_BRAKE = 0.1
# Telemetry clamp. The 0.5 m floor stops a divide-by-zero but not an explosion: at dRel <= the
# standoff the match term reaches v_ego^2/1.0, e.g. 400 m/s^2 at 20 m/s. Nothing beyond the tyre
# limit carries information, so saturate rather than log a number that is technically finite and
# practically meaningless.
LEAD_GEOMETRY_MAX_REQUIRED_ACCEL = 12.0

CLOSE_LEAD_BRAKE_CAP_RAMP_MIN = 0.2
CLOSE_LEAD_BRAKE_CAP_RAMP_FULL = 0.5
# Experimental Mode close-lead cap: how fast it may go deeper than chill's floor (D-073).
# In chill the cap is built against accel_limits_turns[0] (about -1.0, deepening only as a_desired
# follows), in Experimental Mode against the vehicle minimum (-3.5), so one aLeadK step turned into a
# one-frame brake step of up to 3 m/s^2 while the MPC/e2e blend asked for -0.04..-0.97. That set all
# 14 jabs on 000002a6 / 000002a4 (Exp on in every window; replay trace, car planner 87505f426).
# Building the Exp cap against chill's floor outright removed the jabs but, closed loop with the
# fitted plant, cut 283 27:40's closest gap 20.6 -> 10.3 m (TTC 7.8 -> 3.6 s) and 2a6 15:08's
# 15.1 -> 11.1 m. Letting the floor follow the cap below chill's at 1.5 m/s^3 cut the biggest 0.5 s
# brake step 3.64 -> 1.88 (283 18:52), 3.02 -> 1.72 (2a4 17:02), 1.75 -> 1.19 (2a6 15:08) and kept
# most closest gaps within 1 m; worst 283 27:40 20.6 -> 16.6 m, TTC 5.8 s (chill 9.3 m / 3.2 s),
# 2a6 9:00 11.1 -> 10.3 m. Only the aLeadK share is rate limited: what the closing speed alone
# demands (the same cap with aLeadK not counted) applies at once, so a stopped car close ahead still
# gets the full brake on the first frame, and 280 12:51 (closing 13.5 m/s) and 2a6 9:08 (5 m gap)
# replay as before. Replay only: the plant misses the real brakes' ~0.8 m/s^2 overshoot (STATUS 195).
# The fast-closing path is not rate limited.
EXP_CLOSE_LEAD_FLOOR_RATE = 1.5   # m/s^3, how fast the Exp cap floor may deepen below chill's
EXP_CLOSE_LEAD_FLOOR_RELAX = 2.0  # m/s^3, how fast it returns once the cap stops asking

# Off-axis radar leads (STATUS 74e): at bearing |yRel|/dRel above this the lead is on a curve relative
# to the ego x axis, where Bosch-A radial range-rate is not the lead's longitudinal speed and aLeadK
# (its derivative) picks up the bearing change. Route 0000025b: 11:05, 11:29, 11:32 were in-lane leads
# at bearing 0.19-0.27 with aLeadK -5.1/-7.8/-8.5 while vision saw a >= -0.08; alpha commanded -3.45
# each time, stock ACC did not brake. The genuine brakes on the same route (13:19, 22:20, 22:34) sit at
# bearing 0.00 with vision a -0.7..-1.35. A cap-only gate changed no output frame (STATUS 74d): ~20
# planner sites and the MPC read aLeadK, so the bound is applied once, at planner input. radarState and
# radard are untouched (D-041/D-042); only aLeadK is bounded, to what vision corroborates, with a floor.
# Bosch-A Hondas only: the radial range-rate is the measured Bosch-A behaviour; other radars are unmeasured.
# 0.12 -> 0.10 (STATUS 74g): 00000237 15:42.5 was the same failure at bearing 0.116-0.119, an in-lane lead at
# 89 m with aLeadK -6.0 vs vision a +0.06; live alpha commanded -2.0 and reached aEgo -2.7. Genuine brakes on
# the fleet sit at bearing <= 0.004; a 10-route replay changed no protected episode at 0.10.
# 0.10 -> 0.075 (STATUS 104): 0000025f 13:58.4 was the same failure at bearing 0.078-0.101 (aLeadK -4.2 vs
# vision a ~0.0 at p 0.99); alpha -3.45 in replay against stock cmd -0.49. A closed-loop pass (current Bosch-A
# parser + radard re-run from logged CAN) over 17 routes changed 2 of 200 episodes, both false brakes (25f
# 13:58.4 -3.45 -> -1.22, 260 9:07.8 -3.20 -> -1.01), and none of the 125 genuine-brake episodes. 00000263
# 6:14.3 (real hard lead at bearing up to 0.149) is unchanged because vision a -1.55 caps the bound.
OFF_AXIS_LEAD_MIN_BEARING = 0.075
# Hold (STATUS 107/108): once a radar track has sat at or above the threshold, it stays eligible for the bound for
# this many planner frames (20 Hz, so 1.0 s) after its bearing falls back under it. 00000267 15:13.3: the lead
# swung to the centre on a curve exit, bearing 0.084 -> 0.070 while aLeadK was still -9.1..-9.4 against vision
# a ~0.0 at p 0.95; 0.075 alone left alpha at -3.45 (stock -0.60), the hold gives -1.45. 00000237 18:09.4 (owner
# confirmed a phantom brake) -2.57 -> -0.73. Closed-loop replay on 19 routes changed no other episode. The rejected
# alternative, bounding on radar/vision speed disagreement, delayed a real closing brake (0000025f 8:02.6) 0.35 s
# because vision under-read the closure.
OFF_AXIS_LEAD_HOLD_FRAMES = 20
OFF_AXIS_LEAD_MAX_BRAKE = 1.5
OFF_AXIS_LEAD_VISION_MIN_PROB = 0.5

# Radar track re-association onto a nearer vision lead (route 00000278 ~6:19, track 21). The track slid from a car at
# 65-69 m onto a nearer car that vision had at 48-50 m with p >= 0.96, doing ~20.5 m/s against ego 21.8 (not closing).
# The range walked 66 -> 51.6 m in ~1 s, U11 -0.4 -> -6.6, D-053 took it to -13.2/-10.0, aLeadK -5.5 on a "16 m/s" lead,
# and alpha commanded -3.5 (aEgo -4.4) for a car vision saw doing its speed. A genuine hard brake has radar and vision
# on the same range throughout; here radar started >= 10 m beyond vision and converged onto it. While that holds and
# vision stays confident, at or nearer the radar range, and not closing, the radar lead's vRel/vLead/vLeadK are bounded
# to vision's closing less a margin and aLeadK to vision's accel with a floor. Planner input only, like the off-axis
# bound: radarState and radard are untouched, the point stays published and its range is kept (D-041/D-042).
REASSOC_LEAD_BOUND = True

# Radar-only on-path lead (radarState.leadOnpath, ONPATH_RADAR_ADOPT in radard.py): a Bosch-A track that sat on the
# driving path for a second while the model did not see it. radard publishes it BESIDE an unchanged leadOne, and it
# gets bounded authority here (D-048: a lead without vision corroboration does not get full authority). A second
# planner instance runs every cycle on the same inputs with leadOne replaced by leadOnpath, so its state stays in
# step; while leadOnpath is present the published target is that planner's, clipped to
# [min(own, -ONPATH_LEAD_MAX_BRAKE), own]. One-sided: it can only add braking to what this planner already asks,
# never remove braking and never add acceleration, and it adds nothing once this planner itself brakes harder than
# the cap. Full authority returns when radard's own leadOne takes the track (vision match or its normal radar path),
# because leadOnpath is then not published; the output is this planner's again on that cycle. The point is never
# deleted and its range is never moved (D-041/D-042), so nothing here can pull the car toward a stopped object.
# The cap is on the resulting target, not a delta: from +0.46 it may go to -0.80 (00000276 13:45.2).
# 1.0 m/s^2: the off-axis bound's accepted residue on a false brake was -1.01 .. -1.22 (25f 13:58.4, 260 9:07.8).
# Replay evidence only (closed-loop alpha_closed_loop_replay, 2026-09-29), route 00000297--f971b5896f:
#   31:08.0 stopped car, adopted 1.35 s before HEAD's radar lead: -1.00 from 31:08.0 (HEAD -0.3); peak -2.86 vs HEAD
#     -3.24 (uncapped -2.37), sim aEgo min -3.79 vs -4.06; ends 1.4 m farther back than HEAD (uncapped 2.4 m).
#   30:18.1 stationary object on a curve edge, passed ~2.5 m to the side: -1.00 for 0.35 s (uncapped -2.87 and 1.0 s
#     of extra braking), 0.4 m/s lost vs HEAD (uncapped 1.9 m/s).
# A deeper cap buys back the uncapped gap on 31:08 and gives back the false brake at 30:18 one for one; there is no
# road evidence either way.
ONPATH_LEAD_BOUND = True
ONPATH_LEAD_MAX_BRAKE = 1.0


# Brake release rate limit (replay only, no road evidence). While the previous published target is a brake
# (< 0), the next target may rise by at most BRAKE_RELEASE_JERK * dt. It never lowers a target by more than that
# step allows, never delays brake onset (a falling target passes through unchanged), and is skipped on reset and
# at standstill so a stop-and-go departure is not slowed. Evidence, closed-loop replay of 12 windows on
# 00000294/293/292/25e (tools/longitudinal/alpha_closed_loop_replay.py, forced engagement, 2026-09-29):
# the step-to-step movement of our target is dominated by the close-lead caps (close_lead_brake_cap moved it on
# 468 cycles, mean |step| 0.72 m/s^2) and by vision_low_speed_stop_buffer toggling -1.3 <-> -0.3 at a creep.
# Removing the caps outright gives mvl-like smoothness but loses the 293 1965 stop, so the caps stay and only
# their release is slewed. J = 2.5: geo-mean RMS d(cmd)/dt 0.74x base (1.5 gave 0.69x, 4.0 gave 0.76x),
# first-brake time unchanged in every window, peak brake within 0.1, min gap >= base - 0.1 m.
# Rerun on the repeatable log-clock replay (45e9d316c, 16 windows incl. 725/1383/2304 stop-and-go): mean jerk RMS
# 0.82x today, 9 fewer accel sign flips, brake onset identical in all 16, no trusted min gap below today's.
# Shipped ON (owner, 2026-09-29) with no road evidence yet.
# Costs: a brake hold of up to |a| / J seconds longer (-2.5 -> 0 takes 1 s) before throttle on a lead pull-away.
BRAKE_RELEASE_LIMIT = True
BRAKE_RELEASE_JERK = 2.5  # m/s^3
# Release dwell (closed-loop replay only, not driven; 2026-09-29 plan2 study vs mvl sp-honda-dev-202608). Near a
# close lead the MPC answer can alternate every cycle (25e 732.5-733.0: raw MPC -1.99, -0.50, -1.70, -0.46, ... at
# 2 m/s, 4.5 m) and the published target dithered -1.00 <-> -0.88 between the comfort-floor clip and the release
# slew above. The alternation rides on the caps writing self.a_desired into the next MPC x0; cutting that feedback
# diverged the replay (725: min gap 5.3 -> -98.8 m), so the feedback stays and only the output is held: a brake may
# rise only after it has asked for no rise for BRAKE_RELEASE_DWELL_TICKS cycles (a short running-min). It only
# ever holds more braking, so it cannot delay onset. Log-clock replay, 16 windows vs the shipped slew: geo-mean
# jerk RMS 0.986x, 23 fewer accel sign flips (725 24 -> 15, 559 25 -> 19), onset never later, trusted min gap never
# below base -0.1 m, 725/1965 peak brake unchanged. 4 ticks, or holding only after a fall, removed fewer flips.
# Costs: every brake release starts BRAKE_RELEASE_DWELL_TICKS * DT_MDL (0.1 s) later.
BRAKE_RELEASE_DWELL = True
BRAKE_RELEASE_DWELL_TICKS = 2
# Coast-ceiling slew (closed-loop replay only, not driven; same study). When the model's throttle gate closes, the
# output ceiling drops from the accel limit to the coast accel in one cycle (294 568.16: +0.46 -> -0.42 at 5.4 m/s).
# mvl reaches the same coast limit through a jerk-limited cruise target. The ceiling now moves at most
# COAST_CEILING_JERK * dt per cycle from where the output was. It only ever allows more throttle than the ceiling for
# a few cycles and never overrides a lower MPC or cap target. Alone it cost 0.4 m of min gap in 294 559 (fails the
# gap rule); with BRAKE_RELEASE_DWELL it passed (16 windows: jerk RMS 0.975x, 27 fewer flips vs the shipped slew).
COAST_CEILING_SLEW = True
COAST_CEILING_JERK = 2.5  # m/s^3
# Brake onset shaping (D-078, proposed; closed-loop replay only, not driven; default OFF). STATUS 208 found 89% of
# harsh-brake frames on 7 owner routes had the radar closing speed within 3 m/s of the truth, so the harshness is the
# planner's onset, not a bad radar number. While every active lead is far in time (worst-case TTC = dRel / closing)
# and in distance, and none is braking hard, a deepening brake may fall at most BRAKE_ONSET_JERK * dt per step. The
# jerk allowance grows as TTC shrinks and the limit is off below BRAKE_ONSET_TTC_OFF_S, inside BRAKE_ONSET_MIN_GAP,
# with no lead, on a stop/red-light/forced-stop, reset or standstill (panic bypass: see D-081). Output only: self.a_desired
# still feeds the MPC x0 (cutting that feedback diverged the replay, see BRAKE_RELEASE_DWELL above).
# Throttle cuts are not touched (the limit starts from min(prev, 0); COAST_CEILING_SLEW owns those). Replay round 1
# (2026-10-04, 7 routes) limited throttle cuts too and softened 236 13:15.7 (lead 17 m at 10.6 m/s braking -1.1),
# so the gap gate went 1.0 -> 1.5 s and the lead-decel gate -1.5 -> -1.0.
# Costs: up to |a| / J seconds later to reach a far-lead brake; the on-path bound in update() still applies after.
BRAKE_ONSET_LIMIT = False  # True forces it on; otherwise the BrakeOnsetLimit toggle (Advanced Longitudinal Tuning)
BRAKE_ONSET_TTC_OFF_S = 3.0  # at or below: no limit
BRAKE_ONSET_TTC_BP = [3.0, 6.0]  # s
BRAKE_ONSET_JERK_V = [6.0, 1.5]  # m/s^3 allowed fall rate at those TTCs
BRAKE_ONSET_MIN_GAP_M = 10.0
BRAKE_ONSET_MIN_GAP_T = 1.5  # s of v_ego; the gap gate is max(MIN_GAP_M, MIN_GAP_T * v_ego)
BRAKE_ONSET_LEAD_DECEL = -1.0  # m/s^2; a lead braking harder than this disables the limit
# D-081 (proposed; closed-loop replay only, not driven). The panic bypass (closing fast inside the follow window plus
# rising uncertainty) used to switch the limit off outright. On 2df 24:45 (track 6 born at 55 m closing 12 m/s, TTC
# ~4.6 s, a car turning in that then accelerated) that sent the target +0.57 -> -1.70 in one 50 ms step. Under a
# panic bypass the limit now still applies, but only while the worst TTC is above BRAKE_ONSET_PANIC_TTC_S; the gap and
# lead-braking gates are unchanged.
BRAKE_ONSET_PANIC_TTC_S = 4.0
# Replay round 1 also softened 2df 25:54 (stopped traffic, radar and vision both closing 12-14 m/s, already braking
# -1.2): -3.5 arrived ~0.3 s later. So the limit applies under a panic bypass only when the published target was above
# BRAKE_ONSET_PANIC_MAX_PRIOR_BRAKE as the bypass began (latched for that bypass).
BRAKE_ONSET_PANIC_MAX_PRIOR_BRAKE = -0.5  # m/s^2
# Stock-like onset ramp (D-083, proposed; open-loop replay only, not driven), part of the BrakeOnsetLimit toggle.
# STATUS 215: stock ACC on route 299 brings fast-closing brakes in at a worst step of -1.4..-3.4 m/s^3 even at TTC
# 2.6-3.3 s (20:34: car 55 m ahead closing 12.5 m/s, command -0.3 -> -2.2 over ~2.5 s, then held), while ours, with
# the limit off below TTC 3 s, stepped at -36..-40 m/s^3 on U11-rail onsets (2d5 11:58: -1.8 -> -3.6 in one 50 ms
# frame after a single-frame vRel of -20 put TTC at 2.4 s). With BRAKE_ONSET_STOCK_RAMP the jerk schedule tops out at
# BRAKE_ONSET_STOCK_JERK_V and the TTC switch-off moves down to BRAKE_ONSET_STOCK_TTC_FLOOR_S; in between, the limit
# stands down instead when the ramp-aware need (closing^2 / 2(d - MIN_GAP_M - closing * ramp lag), plus the lead's
# own decel) exceeds BRAKE_ONSET_STOCK_MAX_NEED on two consecutive frames, so a lone vRel spike cannot end the ramp
# but a sustained need beyond what a gentle onset can still deliver does. Peak braking is never reduced: only the
# deepening rate is capped, the gap, lead-braking and stop gates are unchanged, and a panic bypass that began already
# braking still switches it off. Cost: a far-lead brake reaches its depth up to |a| / 3 s later (about 1 s for -3).
BRAKE_ONSET_STOCK_RAMP = True
BRAKE_ONSET_STOCK_JERK_V = [3.0, 1.5]  # m/s^3 at BRAKE_ONSET_TTC_BP; below the first TTC it stays 3.0
BRAKE_ONSET_STOCK_TTC_FLOOR_S = 2.0  # at or below: no limit, undebounced
BRAKE_ONSET_STOCK_MAX_NEED = 3.0  # m/s^2; planner floor is -3.5
# Panic bypass keeps the stock ramp (D-084, proposed; replay only, not driven). STATUS 218: on 2e5 7:58 a car merging
# in from a construction-blocked lane was born at 61 m, vRel -9.5, TTC 6.4; the panic bypass fired with the previous
# target at -0.53, just under BRAKE_ONSET_PANIC_MAX_PRIOR_BRAKE, so the latch called it a hard panic and switched the
# ramp off (closed-loop sim worst jerk -8.2 m/s^3). With this switch the bypass no longer ends the D-083 ramp: it
# stays on down to BRAKE_ONSET_STOCK_TTC_FLOOR_S and still stands down on a sustained BRAKE_ONSET_STOCK_MAX_NEED.
# Closed-loop sim (min a / worst jerk / min gap): 2e5 -2.62/-8.2/37.8 -> -2.67/-2.0/36.9; 2df 25:54 stopped traffic
# (the latch's own case) min gap 8.7 -> 7.1 m near standstill; 236 9:22 -2.80 -> -2.83, gap -0.1 m; 2df 24:46, 2d5
# 11:58 and 236 12:54 unchanged (the need gate already ends the ramp there). Off restores the D-081 latch.
BRAKE_ONSET_STOCK_PANIC_RAMP = True
# Stock brake feel (D-086, proposed; closed-loop sim replay only, not driven), the StockBrakeFeel toggle, off by
# default. Owner: "copy exactly how stock does it ... we are overemphasizing the safety issues and sacrificing the smooth
# feel". This replaces BrakeOnsetLimit's onset shaping (D-078/D-083/D-084) with stock Honda ACC's own law, fitted from
# ACC_CONTROL ACCEL_COMMAND on 12 stock-ACC routes (51k closing-lead frames at 10 Hz, stock_acc_reference.py corpus;
# STATUS 220). Stock's depth follows time to contact and barely follows the kinematic need; its p25 command (the depth
# stock is at or past only a quarter of the time) by TTC, made monotone, is STOCK_FEEL_DEPTH_V at STOCK_FEEL_DEPTH_BP:
#   TTC s     2-2.5 2.5-3  3-4  4-5  5-6  6-7  7-8  8-10 10-12 12-15 15-20 20+
#   p50      -2.59 -1.93 -1.69 -1.79 -1.51 -1.24 -1.17 -0.89 -0.72 -0.51 -0.31 -0.10
#   p25      -3.21 -2.41 -2.08 -2.29 -2.11 -1.70 -1.61 -1.28 -1.09 -0.88 -0.74 -0.35
#   below 2 s stock commands -3.8..-4.0 (n 37, 2 routes)
# Its per-frame deepening rate is p50 0.4-0.6 / p90 1.0-1.6 m/s^3 at every TTC (p98 2-3), and its -0.3 -> -1.0 onsets
# took a median 0.3-0.5 m/s^3 at TTC 8 s or more; that is STOCK_FEEL_JERK_V at STOCK_FEEL_JERK_BP. While any lead
# closes faster than STOCK_FEEL_MIN_CLOSING and the worst TTC is over STOCK_FEEL_TTC_FLOOR_S, the target may go no
# deeper than the depth table and may deepen no faster than the jerk table. No gap, lead-braking or need gate: stock has
# none. Below the floor (stock itself is at -3.8..-4 there), when no lead is closing, and when stopping, at a red light
# or forced stop, the planner is untouched. Cost, accepted by the owner: a closing that needs more than stock's depth
# closes the gap further, and a lead that brakes hard is met at stock's depth until the TTC falls under the floor.
STOCK_FEEL_DEPTH_BP = [2.0, 2.25, 2.75, 3.5, 4.5, 5.5, 6.5, 7.5, 9.0, 11.0, 13.5, 17.5, 25.0]  # s
STOCK_FEEL_DEPTH_V = [-3.5, -3.2, -2.4, -2.3, -2.3, -2.1, -1.7, -1.6, -1.28, -1.09, -0.88, -0.74, -0.35]  # m/s^2
STOCK_FEEL_JERK_BP = [2.0, 2.5, 6.0, 10.0]  # s
STOCK_FEEL_JERK_V = [3.0, 2.0, 1.0, 0.6]  # m/s^3
STOCK_FEEL_TTC_FLOOR_S = 2.0
STOCK_FEEL_MIN_CLOSING = 0.5  # m/s
# Newborn lead aLeadK bound (D-080, proposed; replay only, not driven), part of the BrakeOnsetLimit toggle. STATUS 212:
# on 2e2 (bookmark ~283 s) a radar lead first seen while its velocity estimate was still converging published aLeadK
# -3 / -2.5 when ~0.75 m/s^2 was needed, and on 2e1 a jumping track reached -13.7; the planner braked early and twice,
# and the onset limit stood aside because aLeadK < BRAKE_ONSET_LEAD_DECEL. For the first NEWBORN_LEAD_FRAMES a radar
# track has been a lead (or after it drops out for NEWBORN_LEAD_GAP_FRAMES or its range jumps NEWBORN_LEAD_JUMP_M),
# its aLeadK may go no lower than -NEWBORN_LEAD_MIN_BRAKE, or lower only as far as a quadratic fit to its own range
# history (once NEWBORN_LEAD_FIT_FRAMES long) says it is slowing. Planner input only: dRel, vRel, TTC and radarState
# are untouched and the point is never dropped (D-041/D-042); only the assumed lead decel is bounded.
NEWBORN_LEAD_FRAMES = 40        # 2.0 s as a lead
NEWBORN_LEAD_GAP_FRAMES = 10    # absent this long (0.5 s): newborn again
NEWBORN_LEAD_JUMP_M = 4.0       # range step from the last sample: newborn again
NEWBORN_LEAD_FIT_FRAMES = 16    # 0.8 s of range history before the fit may lower the floor
NEWBORN_LEAD_MIN_BRAKE = 1.0    # aLeadK floor without range confirmation (= -BRAKE_ONSET_LEAD_DECEL)


# Experimental-mode exit crossfade (log, open-loop and closed-loop replay evidence only; not driven).
# The planner publishes min(mpc, e2e) while experimental mode is on and mpc the frame it turns off, so every
# EXP->ACC flip is a one-frame target step of mpc - min(mpc, e2e).
# Route 00000280--d02d9c2f8e 30:42.89: CEM released on an open 3-5 deg climb and aTarget stepped +0.01 -> +0.99
# in one 20 Hz frame; CURVATURE then re-entered/released at 30:43.49/30:44.09 and 30:46.14/30:46.84, each
# release another ~+1.1 step. Corpus (45 routes, 10 h engaged, 995 flips): 79 of 561 exits stepped > 0.5.
# Change: on EXP->ACC fade from min(mpc, e2e) to mpc over EXP_MODE_EXIT_BLEND_TIME. Entries are NOT slowed:
# the weight jumps back to 1 on the frame experimental mode turns on, so a stop is braked for exactly as today.
# A fade that allowed slowing entries was rejected: with any e2e bypass threshold tried (-0.5, -0.3, 0.0) it
# held up to 1.44 m/s^2 more accel than HEAD on entries followed by a real stop within 10 s.
# Cost (open loop, 1.0 s): the car keeps the experimental (lower) target for up to 1 s longer after a release;
# speed withheld vs HEAD over 1.5 s p50 0.02 p90 0.26 max 0.72 m/s. If e2e is braking when CEM releases, that
# braking fades out over <= 1 s instead of ending at once. Closed-loop replay (CEM fed from shadow replay, with
# STOP_LIGHT_HOLD_CLEAR_RELEASE_TIME and CURVE_MODE_HOLD_TIME): route 280 29:30-31:10 aTarget steps > 0.5 9 -> 5;
# red-light stops 00000293 ~7:00 and 00000296 ~9:30 brake at the same frame with the same or larger min gap.
EXP_MODE_EXIT_BLEND = True
EXP_MODE_EXIT_BLEND_TIME = 1.0  # s for a full min(mpc, e2e) -> mpc fade after experimental mode turns off


def exp_mode_blend_weight(weight: float, exp_active: bool, dt: float) -> float:
  """Weight of min(mpc, e2e) against mpc: 1 at once while experimental mode is on, then decays to 0
  at 1/EXP_MODE_EXIT_BLEND_TIME per second after it turns off."""
  if exp_active or not EXP_MODE_EXIT_BLEND:
    return 1.0 if exp_active else 0.0
  return float(max(0.0, weight - dt / EXP_MODE_EXIT_BLEND_TIME))


def exp_mode_blend_target(a_mpc: float, a_e2e: float, weight: float) -> float:
  """mpc at weight 0, min(mpc, e2e) at weight 1; never above mpc and never below min(mpc, e2e)."""
  return float(a_mpc + weight * min(0.0, a_e2e - a_mpc))


def brake_release_limited_target(prev: float, target: float, dt: float) -> float:
  """While braking, the target may rise at most BRAKE_RELEASE_JERK * dt per step; it may always fall."""
  if prev >= 0.0:
    return float(target)
  return float(min(target, prev + BRAKE_RELEASE_JERK * dt))


def brake_onset_ttc(leads, min_closing: float = 1e-3) -> float:
  """Worst time to contact (s) over the active closing leads; inf when none is closing."""
  ttc_min = float('inf')
  for lead in leads:
    if lead is None or not bool(getattr(lead, 'status', False)):
      continue
    closing = max(0.0, -float(lead.vRel))
    if closing > min_closing:
      ttc_min = min(ttc_min, float(lead.dRel) / closing)
  return ttc_min


def brake_onset_jerk(leads, v_ego: float, ttc_off: float = BRAKE_ONSET_TTC_OFF_S,
                     jerk_v=BRAKE_ONSET_JERK_V, ttc_bp=BRAKE_ONSET_TTC_BP) -> float | None:
  """Allowed brake fall rate (m/s^3) when every active lead is far in time and distance, else None (no limit)."""
  ttc_min = float('inf')
  any_active = False
  for lead in leads:
    if lead is None or not bool(getattr(lead, 'status', False)):
      continue
    any_active = True
    d_rel = float(lead.dRel)
    if d_rel < max(BRAKE_ONSET_MIN_GAP_M, BRAKE_ONSET_MIN_GAP_T * max(v_ego, 0.0)):
      return None
    if float(getattr(lead, 'aLeadK', 0.0)) < BRAKE_ONSET_LEAD_DECEL:
      return None
    closing = max(0.0, -float(lead.vRel))
    if closing > 1e-3:
      ttc_min = min(ttc_min, d_rel / closing)
  if not any_active or ttc_min <= ttc_off:
    return None
  return float(np.interp(ttc_min, ttc_bp, jerk_v))


def brake_onset_need(leads, prev: float, jerk: float) -> float:
  """Worst constant decel (m/s^2, positive) that still stops BRAKE_ONSET_MIN_GAP_M behind each active lead after a
  ramp from min(prev, 0) at jerk; inf when the ramp lag alone uses up the gap."""
  need = 0.0
  for lead in leads:
    if lead is None or not bool(getattr(lead, 'status', False)):
      continue
    closing = max(0.0, -float(lead.vRel))
    lead_decel = max(0.0, -float(getattr(lead, 'aLeadK', 0.0)))
    room = float(lead.dRel) - BRAKE_ONSET_MIN_GAP_M
    if closing <= 1e-3:
      need = max(need, lead_decel)
      continue
    if room <= 0.0:
      return float('inf')
    flat = closing ** 2 / (2.0 * room)
    lag = max(0.0, flat + min(prev, 0.0)) / (2.0 * max(jerk, 1e-3))
    room -= closing * lag
    if room <= 0.0:
      return float('inf')
    need = max(need, closing ** 2 / (2.0 * room) + lead_decel)
  return float(need)


def stock_onset_jerk(leads, v_ego: float, prev: float, hard_panic: bool, prev_over: bool,
                     jerk_v=BRAKE_ONSET_STOCK_JERK_V, ttc_bp=BRAKE_ONSET_TTC_BP) -> tuple[float | None, bool]:
  """D-083 allowed fall rate and this frame's need-over flag: off at or below the TTC floor or under a hard panic
  bypass, and off when the ramp-aware need is over BRAKE_ONSET_STOCK_MAX_NEED on this and the previous frame."""
  jerk = brake_onset_jerk(leads, v_ego, float('inf') if hard_panic else BRAKE_ONSET_STOCK_TTC_FLOOR_S,
                          jerk_v, ttc_bp)
  over = jerk is not None and brake_onset_need(leads, prev, jerk) > BRAKE_ONSET_STOCK_MAX_NEED
  if over and prev_over:
    jerk = None
  return jerk, over


def stock_feel_target(leads, prev: float, target: float, dt: float) -> float:
  """D-086 stock Honda ACC brake law: while a lead is closing and the worst TTC is over STOCK_FEEL_TTC_FLOOR_S, the
  target goes no deeper than stock's depth at that TTC and deepens no faster than stock's rate; otherwise unchanged."""
  ttc = brake_onset_ttc(leads, STOCK_FEEL_MIN_CLOSING)
  if not ttc > STOCK_FEEL_TTC_FLOOR_S or ttc == float('inf'):
    return float(target)
  target = max(target, float(np.interp(ttc, STOCK_FEEL_DEPTH_BP, STOCK_FEEL_DEPTH_V)))
  return brake_onset_limited_target(prev, target, dt, float(np.interp(ttc, STOCK_FEEL_JERK_BP, STOCK_FEEL_JERK_V)))


def brake_onset_limited_target(prev: float, target: float, dt: float, jerk: float | None) -> float:
  """A brake below min(prev, 0) may deepen at most jerk * dt per step; throttle cuts, rises and jerk None pass through."""
  start = min(prev, 0.0)
  if jerk is None or target >= start:
    return float(target)
  return float(max(target, start - jerk * dt))


def brake_release_dwell_target(prev: float, target: float, rise_ticks: int) -> tuple[float, int]:
  """While braking, a rise is held for the first BRAKE_RELEASE_DWELL_TICKS cycles that ask for it; returns (target, rise_ticks)."""
  if target <= prev + 1e-3:
    return float(target), 0
  rise_ticks += 1
  if prev < 0.0 and rise_ticks <= BRAKE_RELEASE_DWELL_TICKS:
    return float(prev), rise_ticks
  return float(target), rise_ticks


def onpath_lead_view(sm):
  """SubMaster view with radarState.leadOne replaced by leadOnpath, or None when there is no on-path lead."""
  try:
    radar_state = sm['radarState']
  except (KeyError, AttributeError):
    return None
  lead = getattr(radar_state, 'leadOnpath', None)
  if lead is None or not bool(getattr(lead, 'status', False)):
    return None
  return _BoundedSubMaster(sm, _BoundedRadarState(radar_state, lead, radar_state.leadTwo))


def onpath_bounded_target(own: float, with_onpath: float) -> float:
  """The on-path lead may lower the target by at most down to -ONPATH_LEAD_MAX_BRAKE, and never raise it."""
  return float(np.clip(with_onpath, min(own, -ONPATH_LEAD_MAX_BRAKE), own))
REASSOC_LEAD_WINDOW_FRAMES = 30         # 1.5 s of history per radar track
REASSOC_LEAD_MIN_OFFSET_M = 10.0        # track was this far beyond the vision lead ...
REASSOC_LEAD_MIN_DROP_M = 6.0           # ... and its range has since dropped this much
REASSOC_LEAD_VISION_MIN_PROB = 0.9
REASSOC_LEAD_VISION_NEAR_MARGIN_M = 3.0 # vision lead at or nearer the radar range (plus this)
REASSOC_LEAD_VISION_MAX_CLOSING = 2.0   # vision closing speed (m/s) at or under this: "not closing"
REASSOC_LEAD_VISION_MIN_ACCEL = -1.5
REASSOC_LEAD_HOLD_FRAMES = 60           # armed for at most 3.0 s
REASSOC_LEAD_VREL_MARGIN = 1.5          # published closing may exceed vision's by this much
REASSOC_LEAD_MIN_BRAKE = 1.0            # aLeadK floor: -max(this, vision brake)


# Slow radar lead stop-distance gate (route 00000278 ~4:33, BM0). After an experimental -> chill switch 93 m behind a
# 1.8-2.5 m/s radar lead at 16 m/s, chill's raw close-lead gate admitted the slow (not stopped) lead only inside
# max(40 m, 3 v), shorter than the distance a -1.0 comfort brake needs to shed 14 m/s of closing, so the close cap
# first bit at 73 m and the ACC MPC braked late to -2.65. A slow radar lead the model also sees (modelProb) is admitted
# inside closing^2 / (2 * SLOW_RADAR_LEAD_GATE_DECEL) + standoff (capped at the stopped-lead limit) instead.
SLOW_RADAR_LEAD_STOP_GATE = True
SLOW_RADAR_LEAD_GATE_MAX_SPEED = 3.0
SLOW_RADAR_LEAD_GATE_MIN_PROB = 0.9
SLOW_RADAR_LEAD_GATE_DECEL = 1.0
SLOW_RADAR_LEAD_GATE_STANDOFF = 10.0

# Planner-local MPC action time (D-072, PROPOSED; driver trial toggle, shipped on). The
# planner reads its output off the MPC trajectory at action_t = longitudinal actuator delay + DT_MDL,
# about 0.55 s on the Civic (CP delay 0.50, or the live LongitudinalActuatorDelay toggle). Reading
# 0.55 s ahead turns every small wiggle in the MPC's far plan into an output step, which shows up as
# jerk and light brake taps. mvl-boston/openpilot sp-honda-dev-202608 (5372439bf) plans with 0.30.
# Replay, open loop, of this switch alone (planner at 44918d843 + this change; 10 routes: 00000236
# seg 11-12, 00000237 seg 9-10, 00000297 seg 47-48, 00000298 seg 3-4, and all engaged time of
# 0000029b/29c/29d/29e/29f and 000002a2): frames over 2 m/s^3 443 -> 396, RMS jerk down 0-7 % per
# route (236 flat), light brake taps 24 -> 23, brake onsets 64 -> 53. Cost: the -0.5 onset of the
# hardest brake is up to 0.3 s later (297 48:12 +0.30, 0000029e 5:33 +0.25, 0000029d 3:50 +0.20)
# and its peak up to 0.09 m/s^2 softer. D-072 has the table.
# Only the read-off point moves. CP.longitudinalActuatorDelay, the carcontroller's learner that also
# reads it, self.longitudinal_actuator_delay (every reaction_t gate below), the model-launch read,
# the cruise and lane-change caps all keep the actuator delay. Built in ON (it shipped as the
# PlannerShortActionTime toggle, default on at Peter's request); replays set PLANNER_ACTION_T_OVERRIDE
# = False for the old read-off. Off is action_t = actuator delay + DT_MDL exactly, as before.
# Closed-loop replay with the fitted plant (car-matched to 07b66420): the command is smoother (jerk
# x0.64-0.93, taps 19 -> 14) but the car's accel changes only ~3 %, brake onsets are 0.1-0.3 s later
# and 0000029d's closest gap drops 6.0 -> 5.6 m. Replay evidence only; not road-validated. Peter asked for it on the road (2026-09-30).
PLANNER_ACTION_T_OVERRIDE = True
PLANNER_ACTION_T_S = 0.30


def get_planner_action_t(actuator_delay: float, enabled: bool | None = None) -> float:
  """Time on the MPC trajectory the planner reads its output from. enabled=None means the
  PLANNER_ACTION_T_OVERRIDE constant alone."""
  if PLANNER_ACTION_T_OVERRIDE if enabled is None else enabled:
    return PLANNER_ACTION_T_S
  return actuator_delay + DT_MDL


VISION_LEAD_APPROACH_MIN_MODEL_PROB = 0.85
VISION_LEAD_APPROACH_FULL_MODEL_PROB = 0.98
PLANNER_SAFETY_WARNING_INTERVAL = 5.0
VISION_UNTRACKED_SLOW_LEAD_MIN_MODEL_PROB = 0.9
VISION_UNTRACKED_SLOW_LEAD_FULL_MODEL_PROB = 0.97
VISION_UNTRACKED_SLOW_LEAD_MIN_CLOSING_SPEED = 3.0
VISION_UNTRACKED_SLOW_LEAD_MIN_CLOSING_RATIO = 0.16
VISION_UNTRACKED_SLOW_LEAD_FULL_CLOSING_RATIO = 0.24
VISION_UNTRACKED_SLOW_LEAD_TRIGGER_TTC = 16.0
VISION_UNTRACKED_SLOW_LEAD_FULL_TTC = 8.0
VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_MODEL_PROB = 0.95
VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_CLOSING_SPEED = 2.0
VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_CLOSING_RATIO = 0.12
VISION_UNTRACKED_SLOW_LEAD_EARLY_TRIGGER_TTC = 24.0
VISION_UNTRACKED_SLOW_LEAD_NEAR_MAX_DISTANCE = 45.0
VISION_UNTRACKED_SLOW_LEAD_NEAR_MIN_MODEL_PROB = 0.90
VISION_UNTRACKED_SLOW_LEAD_NEAR_MIN_CLOSING_RATIO = 0.09
VISION_UNTRACKED_SLOW_LEAD_RELAXED_ENTRY_MAX_LATERAL_OFFSET = 1.2
VISION_UNTRACKED_SLOW_LEAD_MAX_DISTANCE_TIME = 4.4
VISION_UNTRACKED_SLOW_LEAD_MIN_DISTANCE = 80.0
VISION_UNTRACKED_SLOW_LEAD_MAX_DISTANCE = 120.0
VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_DISTANCE_TIME = 5.7
VISION_UNTRACKED_SLOW_LEAD_MAX_DECEL = 0.85
VISION_UNTRACKED_SLOW_LEAD_MIN_DECEL = 0.1
VISION_UNTRACKED_SLOW_LEAD_RELAXED_MODEL_PROB = 0.68
VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_LEAD_SPEED = 8.0
VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_TTC = 10.0
VISION_UNTRACKED_SLOW_LEAD_RELAXED_MIN_CLOSING_SPEED = 10.0
VISION_UNTRACKED_SLOW_LEAD_RELAXED_FULL_CLOSING_SPEED = 16.0
VISION_UNTRACKED_SLOW_LEAD_CONFIRM_TIME = 0.30
VISION_UNTRACKED_SLOW_LEAD_IMMEDIATE_DECEL = 0.55
VISION_UNTRACKED_SLOW_LEAD_IMMEDIATE_DISTANCE = 45.0
VISION_UNTRACKED_SLOW_LEAD_IMMEDIATE_LEAD_BRAKE = 0.10
VISION_UNTRACKED_APPROACH_LIFT_MIN_EGO_SPEED = 18.0
VISION_UNTRACKED_APPROACH_LIFT_MIN_MODEL_PROB = 0.95
VISION_UNTRACKED_APPROACH_LIFT_MAX_LATERAL_OFFSET = 1.2
VISION_UNTRACKED_APPROACH_LIFT_MIN_CLOSING_SPEED = 0.75
VISION_UNTRACKED_APPROACH_LIFT_MAX_DISTANCE = 130.0
VISION_UNTRACKED_APPROACH_LIFT_MIN_GAP_EXCESS = 6.0
VISION_UNTRACKED_APPROACH_LIFT_TRIGGER_TIME = 20.0
VISION_UNTRACKED_APPROACH_LIFT_FULL_TIME = 6.0
VISION_UNTRACKED_APPROACH_LIFT_MAX_ACCEL = 0.22
VISION_UNTRACKED_APPROACH_LIFT_CONFIRM_TIME = 0.30
VISION_UNTRACKED_APPROACH_LIFT_HOLD_TIME = 0.75
VISION_UNTRACKED_APPROACH_LIFT_RATE_DOWN = 0.35
VISION_UNTRACKED_APPROACH_LIFT_RATE_UP = 0.25
VISION_SLOW_LEAD_MAX_SPEED = 5.0
VISION_SLOW_LEAD_MIN_CLOSING_SPEED = 1.5
VISION_SLOW_LEAD_TRIGGER_TTC = 4.5
VISION_SLOW_LEAD_FULL_TTC = 2.0
VISION_SLOW_LEAD_MAX_DECEL = 1.2
VISION_SLOW_LEAD_MIN_DECEL = 0.18
VISION_SLOW_LEAD_MIN_MODEL_PROB = 0.9
LEAD_APPROACH_TFOLLOW_TRIGGER_TIME = 4.5
LEAD_APPROACH_TFOLLOW_FULL_TIME = 1.5
LEAD_APPROACH_TFOLLOW_MAX_DELTA = 0.162
LEAD_APPROACH_TFOLLOW_MAX_CLOSING_SPEED = 6.0
LEAD_APPROACH_TFOLLOW_MAX_LEAD_BRAKE = 2.5
LEAD_APPROACH_TFOLLOW_MIN_CLOSING_SPEED = 0.75
LEAD_APPROACH_TFOLLOW_MIN_LEAD_BRAKE = 0.2
LEAD_APPROACH_TFOLLOW_WINDOW_MIN = 6.0
LEAD_APPROACH_TFOLLOW_WINDOW_GAIN = 0.35
LEAD_APPROACH_TFOLLOW_RATE_UP = 1.0
LEAD_APPROACH_TFOLLOW_RATE_DOWN = 0.60
VISION_LEAD_TFOLLOW_MAX_EXTRA_DELTA = 0.216
VISION_LEAD_TFOLLOW_SLOW_LEAD_SPEED = 20.0
VISION_LEAD_TFOLLOW_GAP_BUFFER_MIN = 8.0
VISION_LEAD_TFOLLOW_GAP_BUFFER_GAIN = 0.35
VISION_LOW_SPEED_STOP_BUFFER_MAX_EGO_SPEED = 6.5
VISION_LOW_SPEED_STOP_BUFFER_MAX_LEAD_SPEED = 3.25
VISION_LOW_SPEED_STOP_BUFFER_HOLD_MAX_LEAD_SPEED = 4.0
VISION_LOW_SPEED_STOP_BUFFER_MIN_MODEL_PROB = 0.9
VISION_LOW_SPEED_STOP_BUFFER_MIN_CLOSING_SPEED = 0.35
VISION_LOW_SPEED_STOP_BUFFER_MIN_HOLD_REL_SPEED = -0.2
VISION_LOW_SPEED_STOP_BUFFER_BASE = 3.8
VISION_LOW_SPEED_STOP_BUFFER_EGO_GAIN = 0.80
VISION_LOW_SPEED_STOP_BUFFER_LEAD_GAIN = 0.25
VISION_LOW_SPEED_STOP_BUFFER_RELEASE_MARGIN = 0.9
VISION_LOW_SPEED_STOP_BUFFER_HOLD_TIME = 0.8
VISION_LOW_SPEED_STOP_BUFFER_MIN_BRAKE = 1.25
VISION_LOW_SPEED_STOP_BUFFER_BRAKE_GAIN = 0.25
VISION_CLOSE_STOP_HOLD_MAX_EGO_SPEED = 0.75
VISION_CLOSE_STOP_HOLD_MAX_LEAD_SPEED = 0.8
VISION_CLOSE_STOP_HOLD_MAX_DISTANCE = 3.5
VISION_CLOSE_STOP_HOLD_MIN_MODEL_PROB = 0.95
VISION_CLOSE_SETTLE_MAX_EGO_SPEED = 0.75
VISION_CLOSE_SETTLE_MAX_LEAD_SPEED = 2.75
VISION_CLOSE_SETTLE_MAX_DISTANCE = 4.2
MANUAL_STOP_RESUME_OVERRIDE_MIN_ACCEL = 0.2
FORCE_STOP_HANDOFF_MAX_VCRUISE = 0.5
POST_DEPARTURE_FOLLOW_SETTLE_LATCH_TIME = 75.0
POST_DEPARTURE_FOLLOW_SETTLE_MIN_SPEED = 8.0
POST_DEPARTURE_FOLLOW_SETTLE_MAX_ARM_SPEED = 16.0
POST_DEPARTURE_FOLLOW_SETTLE_MIN_MODEL_PROB = 0.9
POST_DEPARTURE_FOLLOW_SETTLE_MAX_LATERAL_OFFSET = 1.15
POST_DEPARTURE_FOLLOW_SETTLE_MAX_CLOSING_SPEED = 0.8
POST_DEPARTURE_FOLLOW_SETTLE_MAX_LEAD_BRAKE = 0.10
POST_DEPARTURE_FOLLOW_SETTLE_ARM_MIN_LEAD_DELTA = -0.10
POST_DEPARTURE_FOLLOW_SETTLE_ARM_MIN_LEAD_ACCEL = 0.20
POST_DEPARTURE_FOLLOW_SETTLE_ARM_MIN_HEADWAY_MARGIN = 0.08
POST_DEPARTURE_FOLLOW_SETTLE_COMPLETE_HEADWAY_MARGIN = 0.05

# Uncertainty-based filter disable thresholds
UNCERT_SLOPE_TRIG = 0.12  # per second
UNCERT_MAG_TRIG = 0.50
UNCERT_PANIC_MIN_CLOSING_SPEED = 2.0
UNCERT_PANIC_MIN_CLOSING_SPEED_GAIN = 0.08
UNCERT_PANIC_MAX_GAP_BUFFER_MIN = 8.0
UNCERT_PANIC_MAX_GAP_BUFFER_GAIN = 0.35
STEADY_FOLLOW_SMOOTHING_MIN_SPEED = 22.0
STEADY_FOLLOW_SMOOTHING_MIN_CLOSING_SPEED = 0.15
STEADY_FOLLOW_SMOOTHING_MAX_CLOSING_SPEED = 1.8
STEADY_FOLLOW_SMOOTHING_MIN_HEADWAY = 0.95
STEADY_FOLLOW_SMOOTHING_HEADWAY_BELOW_TARGET = 0.35
STEADY_FOLLOW_SMOOTHING_HEADWAY_ABOVE_TARGET = 0.90
STEADY_FOLLOW_SMOOTHING_MAX_LEAD_BRAKE = 0.35
STEADY_FOLLOW_SMOOTHING_FILTER_FACTOR_FLOOR = 0.24
EXPERIMENTAL_RELEASE_ACCEL_HOLD_TIME = 0.75
# At low speed, preserve the existing handoff slew long enough to bridge a
# brief slow-lead CEM dropout without extending high-speed release behavior.
EXPERIMENTAL_RELEASE_ACCEL_LOW_SPEED_HOLD_TIME = 3.0
EXPERIMENTAL_RELEASE_ACCEL_LOW_SPEED_THRESHOLD = 12.0
EXPERIMENTAL_RELEASE_ACCEL_MIN_SPEED = 2.5
EXPERIMENTAL_RELEASE_ACCEL_MIN_LEAD_SPEED = 5.0
EXPERIMENTAL_RELEASE_ACCEL_MIN_LEAD_DELTA = -1.0
EXPERIMENTAL_RELEASE_ACCEL_MAX_LEAD_DELTA = 1.5
EXPERIMENTAL_RELEASE_ACCEL_MAX_LEAD_BRAKE = 0.2
EXPERIMENTAL_RELEASE_ACCEL_MIN_MODEL_PROB = 0.9
EXPERIMENTAL_RELEASE_ACCEL_MAX_LATERAL_OFFSET = 1.5
EXPERIMENTAL_RELEASE_ACCEL_MIN_HEADWAY_MARGIN = 0.0
EXPERIMENTAL_RELEASE_ACCEL_MIN_DELTA_A = 0.12
EXPERIMENTAL_RELEASE_ACCEL_STEP = 0.06
EXPERIMENTAL_SPEED_HANDOFF_BAND = 5.0 * CV.MPH_TO_MS
EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE = -0.15
# Experimental-mode lead-departure assist (STATUS 136b-136g). Started as the TEST toggle
# ExpLeadDepartureAssist, default off: 518 exp-mode gas presses on 100 vision-only alpha-long routes
# showed 110 with the e2e target below the MPC while asking for accel >= 0, 57 of them with a lead
# pulling away (e2e +0.0..+0.5 while the MPC allowed +0.7..+0.9). Tuned on open-loop replay (136b),
# then confirmed on four logged drives with the toggle on (136c-136f): logged aTarget matched the
# replay within 0.02 on 95-97% of acting frames, no hard brake in the 5-8 s after an episode was
# caused by it, and 0 frames lifted while a lead closed faster than 0.5 m/s or braked harder than
# -1.0. Baked in in 136g; Accel Boost built in on (136h; the GasOverrideBoost toggle
# was removed 2026-10-03, replays set toggles.gas_override_boost False): still Experimental Mode only (get_exp_lead_departure_weight
# requires a lead at or beyond the follow distance, and update_exp_lead_departure only runs on the
# tinygrad-model branch below), and every other gate is unchanged. When a lead is at or beyond the
# follow distance and pulling away, lift the e2e target part of the way toward the MPC. Stateless
# apart from a weight filter; e2e braking below EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE is never touched,
# and the result never exceeds the MPC target.
EXP_LEAD_DEPARTURE_MIN_SPEED = 4.5  # m/s, ~10 mph
EXP_LEAD_DEPARTURE_VREL_BP = [0.3, 1.0]  # m/s lead pulling away -> weight 0..1 (replay, STATUS 136b)
EXP_LEAD_DEPARTURE_MIN_LEAD_ACCEL = -0.2  # m/s^2, a lead braking harder than this disarms
EXP_LEAD_DEPARTURE_MIN_MODEL_PROB = 0.5  # vision leads only; radar leads pass
EXP_LEAD_DEPARTURE_GAP_FRACTION = 0.6  # share of the e2e -> MPC gap closed at full weight
EXP_LEAD_DEPARTURE_MAX_LIFT = 0.5  # m/s^2 added to e2e at most
EXP_LEAD_DEPARTURE_RISE_TAU = 0.5  # s, weight filter going up
EXP_LEAD_DEPARTURE_FALL_TAU = 0.15  # s, and going down
EXP_LEAD_DEPARTURE_MAX_LIFT_RISE = 1.0  # m/s^3, the lift itself never rises faster
# Release: the lift falls at most this fast (0.5 m/s^2 over ~0.17 s) instead of stepping to 0, which on 00000283
# felt as a lift-off (11 one-frame drops > 0.3, STATUS 136d). Still instant for the urgent cases below, a planned
# stop or e2e braking; never lets the output exceed the MPC.
EXP_LEAD_DEPARTURE_MAX_LIFT_FALL = 3.0  # m/s^3
EXP_LEAD_DEPARTURE_URGENT_VREL = -0.5  # m/s, a lead closing faster than this drops the lift at once
EXP_LEAD_DEPARTURE_URGENT_LEAD_ACCEL = -1.0  # m/s^2, and a lead braking harder than this

TRACKED_VISION_MODEL_FLOOR_MIN_SPEED = 10.0
TRACKED_VISION_MODEL_FLOOR_MIN_MODEL_PROB = 0.95
TRACKED_VISION_MODEL_FLOOR_MIN_MODEL_DECEL = 0.80
TRACKED_VISION_MODEL_FLOOR_MIN_CLOSING_SPEED = 1.0
TRACKED_VISION_MODEL_FLOOR_MAX_TTC = 22.0
TRACKED_VISION_MODEL_FLOOR_MIN_GAP_MARGIN = -2.0
TRACKED_VISION_MODEL_FLOOR_MAX_GAP_BUFFER_MIN = 4.0
TRACKED_VISION_MODEL_FLOOR_MAX_GAP_BUFFER_GAIN = 0.25
TRACKED_VISION_MODEL_FLOOR_MIN_DECEL = 0.35
TRACKED_VISION_MODEL_FLOOR_MAX_DECEL = 1.10
TRACKED_VISION_MODEL_FLOOR_LEAD_BRAKE_MAX = 0.18
TRACKED_VISION_MODEL_CAP_MIN_SPEED = 14.0
TRACKED_VISION_MODEL_CAP_MAX_SPEED = 32.0
TRACKED_VISION_MODEL_CAP_MIN_MODEL_PROB = 0.95
TRACKED_VISION_MODEL_CAP_MAX_MODEL_DECEL = 0.75
TRACKED_VISION_MODEL_CAP_MIN_CLOSING_SPEED = 0.75
TRACKED_VISION_MODEL_CAP_MAX_CLOSING_SPEED = 4.0
TRACKED_VISION_MODEL_CAP_MAX_LEAD_BRAKE = 0.55
TRACKED_VISION_MODEL_CAP_MIN_TTC = 7.0
TRACKED_VISION_MODEL_CAP_MIN_GAP_MARGIN = -1.5
TRACKED_VISION_MODEL_CAP_MAX_GAP_BUFFER_MIN = 4.0
TRACKED_VISION_MODEL_CAP_MAX_GAP_BUFFER_GAIN = 0.25
TRACKED_VISION_MODEL_CAP_MIN_DECEL = 0.45
TRACKED_VISION_MODEL_CAP_MAX_DECEL = 1.10

# Lookup table for turns
_A_TOTAL_MAX_V = [3.5, 3.5, 3.2]
_A_TOTAL_MAX_BP = [0., 20., 40.]

_preap_follow_cache = None


def get_preap_follow_limit(v_ego):
  global _preap_follow_cache
  if _preap_follow_cache is None:
    try:
      from opendbc.car.tesla.preap.constants import ACCEL_PREAP_BP, ACCEL_PREAP_FOLLOW
      _preap_follow_cache = (ACCEL_PREAP_BP, ACCEL_PREAP_FOLLOW)
    except ImportError:
      _preap_follow_cache = (None, None)
  bp, values = _preap_follow_cache
  if bp is None:
    return None
  return float(np.interp(v_ego, bp, values))


def get_longitudinal_personality(sm):
  return sm['selfdriveState'].personality


def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)

def get_coast_accel(pitch):
  return np.sin(pitch) * -5.65 - 0.3  # fitted from data using xx/projects/allow_throttle/compute_coast_accel.py


def limit_accel_in_turns(v_ego, angle_steers, a_target, CP):
  """
  This function returns a limited long acceleration allowed, depending on the existing lateral acceleration
  this should avoid accelerating when losing the target in turns
  """
  # FIXME: This function to calculate lateral accel is incorrect and should use the VehicleModel
  # The lookup table for turns should also be updated if we do this
  a_total_max = np.interp(v_ego, _A_TOTAL_MAX_BP, _A_TOTAL_MAX_V)
  a_y = v_ego ** 2 * angle_steers * CV.DEG_TO_RAD / (CP.steerRatio * CP.wheelbase)
  a_x_allowed = math.sqrt(max(a_total_max ** 2 - a_y ** 2, 0.))

  return [a_target[0], min(a_target[1], a_x_allowed)]


def should_publish_planner_fcw(crash_cnt: int, car_state, radar_state) -> bool:
  return (
    crash_cnt > 2 and
    not car_state.standstill and
    should_trigger_planner_fcw(radar_state.leadOne, float(car_state.vEgo))
  )


def get_vehicle_min_accel(CP, v_ego):
  # Planner-side physical decel capability estimate for GM pedal-long paths.
  is_gm = getattr(CP, "carName", "") == "gm" or getattr(CP, "brand", "") == "gm"
  if is_gm and getattr(CP, "enableGasInterceptorDEPRECATED", False):
    try:
      from opendbc.car.gm.values import GMFlags, CAR
      if bool(CP.flags & GMFlags.PEDAL_LONG.value):
        bolt_pedal_long_cars = {
          CAR.CHEVROLET_BOLT_CC_2017,
          CAR.CHEVROLET_BOLT_CC_2018_2021,
          CAR.CHEVROLET_BOLT_ACC_2022_2023_PEDAL,
          CAR.CHEVROLET_BOLT_CC_2022_2023,
          CAR.CHEVROLET_MALIBU_HYBRID_CC,
        }
        if CP.carFingerprint in bolt_pedal_long_cars:
          return float(np.interp(v_ego, [0.0, 1.5, 4.0, 8.0, 15.0, 30.0],
                                 [-0.93, -1.28, -1.98, -2.58, -2.86, -2.95]))
        return float(np.interp(v_ego, [0.0, 1.5, 4.0, 8.0, 15.0, 30.0],
                               [-0.95, -1.3, -1.85, -2.3, -2.6, -2.8]))
    except Exception:
      pass
  return float(ACCEL_MIN)


def far_lead_vision_braking(model_msg):
  """The camera's lead is braking: leadsV3[0].a[0] <= -FAR_LEAD_COAST_MAX_LEAD_BRAKE at prob >= FAR_LEAD_COAST_VISION_MIN_PROB."""
  leads = getattr(model_msg, "leadsV3", None) if model_msg is not None else None
  if leads is None or not len(leads) or not len(leads[0].a):
    return False
  return (float(leads[0].prob) >= FAR_LEAD_COAST_VISION_MIN_PROB and
          float(leads[0].a[0]) <= -FAR_LEAD_COAST_MAX_LEAD_BRAKE)


def get_far_lead_coast_cap(lead, v_ego, desired_gap, output_a_target, model_msg=None):
  if lead is None or not bool(getattr(lead, "status", False)):
    return float(output_a_target)
  if far_lead_vision_braking(model_msg):
    return float(output_a_target)

  v_ego = float(v_ego)
  lead_distance = float(getattr(lead, "dRel", float("inf")))
  lead_speed = float(getattr(lead, "vLead", v_ego))
  closing_speed = v_ego - lead_speed
  if (
    v_ego <= 10.0 or
    closing_speed <= 0.5 or
    lead_distance < FAR_LEAD_COAST_MIN_DISTANCE or
    lead_distance <= float(desired_gap) + FAR_LEAD_COAST_MIN_GAP_MARGIN or
    lead_distance / max(closing_speed, 0.1) < FAR_LEAD_COAST_MIN_TTC or
    max(0.0, -float(getattr(lead, "aLeadK", 0.0))) > FAR_LEAD_COAST_MAX_LEAD_BRAKE
  ):
    return float(output_a_target)

  return max(float(output_a_target), -FAR_LEAD_COAST_MAX_DECEL)


# Early coast for far radar leads (report §12.3 P5; STATUS 204). The Bosch-A radar holds a lead out
# to ~150 m, well before the follow law reacts, so a closing far lead caps throttle instead of letting
# the cruise target accelerate into a brake later. It only lowers a positive target; it never brakes and
# never raises a braking target. The cap tapers with TTC so entering it is not a step. Owner, 2026-10-04.
FAR_RADAR_EARLY_COAST_MIN_SPEED = 10.0
FAR_RADAR_EARLY_COAST_MIN_DISTANCE = 45.0
FAR_RADAR_EARLY_COAST_MAX_DISTANCE = 150.0
FAR_RADAR_EARLY_COAST_MAX_LATERAL = 1.5
FAR_RADAR_EARLY_COAST_MIN_CLOSING = 1.0
FAR_RADAR_EARLY_COAST_TTC_BP = [10.0, 15.0, 20.0]
FAR_RADAR_EARLY_COAST_CAP_V = [0.0, 0.3, 2.0]


def get_far_radar_lead_early_coast_cap(lead, v_ego, output_a_target):
  if lead is None or not bool(getattr(lead, "status", False)) or not bool(getattr(lead, "radar", False)):
    return float(output_a_target)
  v_ego = float(v_ego)
  lead_distance = float(getattr(lead, "dRel", float("inf")))
  closing_speed = v_ego - float(getattr(lead, "vLead", v_ego))
  if (
    v_ego <= FAR_RADAR_EARLY_COAST_MIN_SPEED or
    closing_speed < FAR_RADAR_EARLY_COAST_MIN_CLOSING or
    not (FAR_RADAR_EARLY_COAST_MIN_DISTANCE <= lead_distance <= FAR_RADAR_EARLY_COAST_MAX_DISTANCE) or
    abs(float(getattr(lead, "yRel", 0.0))) > FAR_RADAR_EARLY_COAST_MAX_LATERAL
  ):
    return float(output_a_target)
  cap = float(np.interp(lead_distance / closing_speed, FAR_RADAR_EARLY_COAST_TTC_BP, FAR_RADAR_EARLY_COAST_CAP_V))
  return min(float(output_a_target), cap)


# Soft final stop behind a stopped radar lead (report §12.3 P6; STATUS 204). Between 3.0 and vEgoStopping
# (0.5 m/s) the braking target is limited to a speed-scaled floor (-0.6 at 0.5 m/s, -1.0 at 2.0 m/s, none
# at 3.0 m/s) but never softer than STOP_SOFTEN_MARGIN x the decel that stops the car STOP_DISTANCE short of
# the lead, so the car still stops before the obstacle point. Below vEgoStopping longcontrol's stopping state
# and the standstill stopped-lead guard own the stop; this does not touch them. Owner, 2026-10-04.
STOP_SOFTEN_MIN_SPEED = 0.5
STOP_SOFTEN_SPEED_BP = [0.5, 1.5, 2.0, 3.0]
STOP_SOFTEN_FLOOR_V = [0.6, 0.8, 1.0, 3.5]
STOP_SOFTEN_MAX_LEAD_SPEED = 0.5
STOP_SOFTEN_MAX_LATERAL = 1.5
STOP_SOFTEN_MIN_REMAINING = 0.5
STOP_SOFTEN_MARGIN = 1.5


def get_soft_stop_floor(lead, v_ego):
  """Lowest aTarget the final stop needs, or None when the soft stop does not apply."""
  if lead is None or not bool(getattr(lead, "status", False)) or not bool(getattr(lead, "radar", False)):
    return None
  v_ego = float(v_ego)
  if not (STOP_SOFTEN_MIN_SPEED <= v_ego < STOP_SOFTEN_SPEED_BP[-1]):
    return None
  if (float(getattr(lead, "vLead", 0.0)) > STOP_SOFTEN_MAX_LEAD_SPEED or
      abs(float(getattr(lead, "yRel", 0.0))) > STOP_SOFTEN_MAX_LATERAL):
    return None
  remaining = float(getattr(lead, "dRel", 0.0)) - STOP_DISTANCE
  if remaining < STOP_SOFTEN_MIN_REMAINING:
    return None
  needed = STOP_SOFTEN_MARGIN * v_ego ** 2 / (2.0 * remaining)
  return -max(float(np.interp(v_ego, STOP_SOFTEN_SPEED_BP, STOP_SOFTEN_FLOOR_V)), needed)


# Restored planner constants retained by CEM, stop, and departure paths.
A_CRUISE_MIN = -1.0
# A soft decel profile (ECO -0.5, traffic -0.35) is a cruise-decel preference. With a closing lead
# it held aTarget at the floor for 0.6-1.05 s and then released to the rail (STATUS 42/43, 60):
# the felt two-stage brake. While a lead is closing, the floor is at least A_CRUISE_MIN.
# Replay, 24f bookmarked brakes: hold removed, peak unchanged (STATUS 61).
LEAD_CLOSING_FLOOR_VREL = -0.3
# 24f 272.7: the hold began while vRel was ~0 and the lead was already braking at -0.3..-0.5.
LEAD_CLOSING_FLOOR_ALEAD = -0.25
# The stop distance runs ~9 m long through the mid-approach, which leaves the obstacle slack
# so it stays silent and deceleration sags. Multiplicative so the trim scales with what is
# left. Note the car parks where the obstacle sits, so this is also a placement bias — 0.85
# stopped ~4.6 m short, 0.93 ~1.6 m.
FORCE_STOP_OBSTACLE_TRIM = 0.93
STANDSTILL_LEAD_CREEP_RELEASE_MIN_LEAD_SPEED = 0.25
STANDSTILL_LEAD_CREEP_RELEASE_MIN_LEAD_ACCEL = 0.08
STANDSTILL_LEAD_CREEP_RELEASE_MIN_GAP_MARGIN = 0.1
RADAR_STANDSTILL_GAP_SETTLE_CONFIRM_TIME = 0.50
RADAR_STANDSTILL_GAP_SETTLE_ENTRY_MARGIN = 0.60
RADAR_STANDSTILL_GAP_SETTLE_EXIT_MARGIN = 0.15
RADAR_STANDSTILL_GAP_SETTLE_MAX_EXTRA_GAP = 1.5
RADAR_STANDSTILL_GAP_SETTLE_MAX_EGO_SPEED = 0.45
RADAR_STANDSTILL_GAP_SETTLE_MAX_LEAD_SPEED = 0.15
RADAR_STANDSTILL_GAP_SETTLE_MAX_LATERAL_OFFSET = 1.0
LEAD_DEPART_CONFIDENT_MIN_GAP = 3.75
LEAD_DEPART_CONFIDENT_MAX_GAP = 5.25
LEAD_DEPART_CONFIDENT_MIN_LEAD_SPEED = 0.3
LEAD_DEPART_CONFIDENT_MIN_LEAD_DELTA = 0.25
LEAD_DEPART_CONFIDENT_MIN_LEAD_ACCEL = 0.2
LEAD_DEPART_RELEASE_HOLD_MIN_DISTANCE = 3.0
LEAD_DEPART_RELEASE_HOLD_MIN_LEAD_SPEED = 0.55
LEAD_DEPART_RELEASE_HOLD_MIN_LEAD_DELTA = 0.25
LEAD_DEPART_RELEASE_HOLD_MAX_LEAD_BRAKE = 0.15
LEAD_DEPART_RELEASE_HOLD_MIN_MODEL_PROB = 0.95
LEAD_DEPART_RELEASE_HOLD_MAX_LATERAL_OFFSET = 1.0
LEAD_DEPART_RELEASE_HOLD_CONFLICT_SPEED = 0.25
LEAD_DEPART_RELEASE_HOLD_CONFLICT_DISTANCE_MARGIN = 3.0
VEHICLE_FAR_FOLLOW_SLEW_MIN_SPEED = 10.0
VEHICLE_FAR_FOLLOW_SLEW_MIN_DISTANCE = 25.0
VEHICLE_FAR_FOLLOW_SLEW_MIN_DISTANCE_TIME = 1.35
VEHICLE_FAR_FOLLOW_SLEW_MIN_HEADWAY = 1.35
VEHICLE_FAR_FOLLOW_SLEW_MIN_TTC = 8.0
VEHICLE_FAR_FOLLOW_SLEW_MAX_LATERAL_OFFSET = 1.5
# Far-lead coast cap (StarPilot Dom 79c61f479a), built in (was FarLeadCoastCap; on in the owner's Civic drives
# through 0000028b). It trusts dRel/vLead at range, where closing speed can read low: the Bosch-A rail interval
# and range-derived closing speed are what keep that reading honest. Replay of route 00000268 (STATUS 110),
# forced on vs off: all 9 brake episodes identical; every far approach had a braking lead or a TTC under 8 s.
FAR_LEAD_COAST_MIN_DISTANCE = 45.0
FAR_LEAD_COAST_MIN_TTC = 8.0
FAR_LEAD_COAST_MIN_GAP_MARGIN = 6.0
FAR_LEAD_COAST_MAX_LEAD_BRAKE = 0.35
FAR_LEAD_COAST_MAX_DECEL = 0.20
# The cap also stands down while the camera sees its lead braking. Route 0000028f 11:29: lead #34 braked
# ~19 -> 6 m/s; radar aLeadK read +0.1..+0.5 while camera a read -1.2..-1.6, so the cap held -0.20 for
# 11:29.3-11:30.8 and the car re-braked at -3.6 at 11:33.5. Replay of 6 drives (28f 28b 28a 289 287 286):
# 4 moments changed, all with the camera lead slowing; no episode minimum below -1.5 changed (open loop).
FAR_LEAD_COAST_VISION_MIN_PROB = 0.5
RADAR_DEPART_CONFLICT_MAX_EGO_SPEED = 1.6
RADAR_DEPART_CONFLICT_MIN_RADAR_LATERAL = 1.5
RADAR_DEPART_CONFLICT_MAX_RADAR_DISTANCE = 18.0
RADAR_DEPART_CONFLICT_MIN_MODEL_PROB = 0.95
RADAR_DEPART_CONFLICT_MAX_MODEL_DISTANCE = 18.0
RADAR_DEPART_CONFLICT_MAX_MODEL_LATERAL = 0.9
RADAR_DEPART_CONFLICT_MAX_MODEL_LEAD_SPEED = 2.0
RADAR_DEPART_CONFLICT_MAX_DISTANCE_MISMATCH = 4.0
LEAD_DEPART_ACCEL_HOLD_MIN_LEAD_SPEED = 0.6
LEAD_DEPART_ACCEL_HOLD_MIN_LEAD_DELTA = 0.5
LEAD_DEPART_ACCEL_HOLD_MIN_GAP = 3.5
LEAD_DEPART_ACCEL_HOLD_FULL_GAP = 6.0
LEAD_DEPART_ACCEL_HOLD_FULL_LEAD_SPEED = 2.2
LEAD_DEPART_ACCEL_HOLD_MIN_MODEL_PROB = 0.85
LEAD_DEPART_ACCEL_HOLD_MIN_MODEL_ACCEL = 0.12
LEAD_DEPART_ACCEL_HOLD_MAX_LEAD_BRAKE = 0.2
LEAD_DEPART_ACCEL_HOLD_MIN_ACCEL = 0.25
LEAD_DEPART_ACCEL_HOLD_MAX_ACCEL = 0.55
LEAD_DEPART_ACCEL_ASSIST = 0.10
LEAD_DEPART_ACCEL_HOLD_REUSE_MIN_GAP = 3.75
LEAD_DEPART_ACCEL_HOLD_REUSE_MAX_CLOSING_SPEED = 0.45
LEAD_DEPART_ACCEL_HOLD_REUSE_MAX_LEAD_BRAKE = 0.2
LEAD_DEPART_ACCEL_HOLD_REUSE_MIN_HEADWAY_MARGIN = 0.10
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_EGO_SPEED = 4.5
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_DISTANCE = 4.0
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_DISTANCE = 18.0
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_SPEED = 4.0
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LATERAL_OFFSET = 1.75
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_MODEL_PROB = 0.9
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_LEAD_DELTA = -0.5
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_DELTA = 0.75
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_LEAD_ACCEL = -0.4
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_ACCEL = 0.25
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_ACCEL = 0.08
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_ACCEL = 0.22
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MAX_EGO_SPEED = 1.25
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_GAP = 4.0
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_LEAD_SPEED = 1.2
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_LEAD_DELTA = 0.8
LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_LEAD_ACCEL = 0.5
VISION_CLOSE_STOP_HOLD_MIN_BRAKE = 0.20
VISION_CLOSE_STOP_HOLD_MAX_BRAKE = 0.36
VISION_CLOSE_SETTLE_MAX_LEAD_DELTA = 2.6
VISION_CLOSE_SETTLE_MIN_BRAKE = 0.16
VISION_CLOSE_SETTLE_MAX_BRAKE = 0.30
VISION_CLOSE_FINAL_GUARD_MAX_EGO_SPEED = 0.5
VISION_CLOSE_FINAL_GUARD_MAX_LEAD_SPEED = 2.75
VISION_CLOSE_FINAL_GUARD_MAX_DISTANCE = 4.5
VISION_CLOSE_FINAL_GUARD_MIN_BRAKE = 0.18
VISION_CLOSE_FINAL_GUARD_MAX_BRAKE = 0.28
VISION_CLOSE_RELEASE_HOLD_MAX_EGO_SPEED = 2.5
VISION_CLOSE_RELEASE_HOLD_MAX_LEAD_SPEED = 3.5
VISION_CLOSE_RELEASE_HOLD_MAX_DISTANCE = 4.2
VISION_CLOSE_RELEASE_HOLD_MIN_MODEL_PROB = 0.98
VISION_CLOSE_RELEASE_HOLD_MIN_LEAD_DELTA = -0.1
VISION_CLOSE_RELEASE_HOLD_MAX_LEAD_DELTA = 1.5
VISION_CLOSE_RELEASE_HOLD_MIN_BRAKE = 0.18
VISION_CLOSE_RELEASE_HOLD_MAX_BRAKE = 0.40
# Give a driver-initiated launch enough time to clear a stale model stop/light
# prediction before the stop request is allowed to reassert.
MANUAL_STOP_RESUME_OVERRIDE_TIME = 6.0
MANUAL_STOP_RESUME_OVERRIDE_MAX_SPEED = 2.0

def get_exp_lead_departure_weight(lead, v_ego, t_follow):
  """0..1: how clearly the lead is pulling away from at or beyond the follow distance."""
  if lead is None or not lead.status or float(v_ego) < EXP_LEAD_DEPARTURE_MIN_SPEED:
    return 0.0
  if not bool(getattr(lead, "radar", False)) and float(getattr(lead, "modelProb", 0.0)) < EXP_LEAD_DEPARTURE_MIN_MODEL_PROB:
    return 0.0
  if float(getattr(lead, "aLeadK", 0.0)) < EXP_LEAD_DEPARTURE_MIN_LEAD_ACCEL:
    return 0.0
  if float(lead.dRel) < float(t_follow) * float(v_ego):
    return 0.0
  return float(np.interp(float(lead.vRel), EXP_LEAD_DEPARTURE_VREL_BP, [0.0, 1.0]))


def apply_exp_lead_departure(output_a_target, output_a_target_e2e, output_a_target_mpc, weight):
  """Lift the arbitrated target toward the MPC while e2e is the limit and not braking. Never lowers it."""
  if weight <= 0.0 or output_a_target_e2e < EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE or output_a_target_mpc <= output_a_target_e2e:
    return output_a_target
  # Fade out toward the e2e brake threshold instead of switching off at it, so the lift never steps.
  brake_fade = float(np.interp(output_a_target_e2e, [EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE, 0.0], [0.0, 1.0]))
  lift = brake_fade * min(EXP_LEAD_DEPARTURE_MAX_LIFT, EXP_LEAD_DEPARTURE_GAP_FRACTION * (output_a_target_mpc - output_a_target_e2e))
  return max(output_a_target, min(output_a_target_mpc, output_a_target_e2e + weight * lift))


def get_planner_v_ego(CP, car_state):
  v_ego = max(car_state.vEgo, car_state.vEgoCluster)

  is_gm = getattr(CP, "carName", "") == "gm" or getattr(CP, "brand", "") == "gm"
  if is_gm and getattr(CP, "enableGasInterceptorDEPRECATED", False):
    try:
      from opendbc.car.gm.values import GMFlags
      is_gm_pedal_long = bool(CP.flags & GMFlags.PEDAL_LONG.value)
      if is_gm_pedal_long:
        return float(car_state.vEgo)
    except Exception:
      pass

  return float(v_ego)


def get_accel_from_plan_classic(CP, speeds, accels, vEgoStopping, actuator_delay=None):
  if len(speeds) == CONTROL_N:
    delay = max(DT_MDL, float(CP.longitudinalActuatorDelay if actuator_delay is None else actuator_delay))
    v_target_now = np.interp(DT_MDL, CONTROL_N_T_IDX, speeds)
    a_target_now = np.interp(DT_MDL, CONTROL_N_T_IDX, accels)

    v_target = np.interp(delay + DT_MDL, CONTROL_N_T_IDX, speeds)
    if v_target != v_target_now:
      a_target = 2 * (v_target - v_target_now) / delay - a_target_now
    else:
      a_target = a_target_now

    v_target_1sec = np.interp(delay + DT_MDL + 1.0, CONTROL_N_T_IDX, speeds)
  else:
    v_target = 0.0
    v_target_1sec = 0.0
    a_target = 0.0
  should_stop = (v_target < vEgoStopping and
                 v_target_1sec < vEgoStopping)
  return a_target, should_stop


def get_accel_from_plan(speeds, accels, action_t=DT_MDL, vEgoStopping=0.05):
  if len(speeds) == CONTROL_N:
    v_now = speeds[0]
    a_now = accels[0]

    v_target = np.interp(action_t, CONTROL_N_T_IDX, speeds)
    a_target = 2 * (v_target - v_now) / (action_t) - a_now
    v_target_1sec = np.interp(action_t + 1.0, CONTROL_N_T_IDX, speeds)
  else:
    v_target = 0.0
    v_target_1sec = 0.0
    a_target = 0.0
  should_stop = (v_target < vEgoStopping and
                 v_target_1sec < vEgoStopping)
  return a_target, should_stop


def off_axis_lead_a_lead(lead, model_msg, held=False):
  """aLeadK bounded for an off-axis radar lead (STATUS 74e); None when the lead is left as is.
  held: the track was off-axis within OFF_AXIS_LEAD_HOLD_FRAMES (STATUS 108), so the bearing test is waived."""
  if lead is None or not bool(getattr(lead, "status", False)) or not bool(getattr(lead, "radar", False)):
    return None
  d_rel = float(lead.dRel)
  a_lead = float(lead.aLeadK)
  if d_rel <= 1.0 or a_lead >= -OFF_AXIS_LEAD_MAX_BRAKE:
    return None
  if abs(float(lead.yRel)) / d_rel < OFF_AXIS_LEAD_MIN_BEARING and not held:
    return None
  vision_brake = 0.0
  leads = getattr(model_msg, "leadsV3", None) if model_msg is not None else None
  if leads is not None and len(leads) and float(leads[0].prob) >= OFF_AXIS_LEAD_VISION_MIN_PROB and len(leads[0].a):
    vision_brake = max(0.0, -float(leads[0].a[0]))
  bounded = max(a_lead, -max(OFF_AXIS_LEAD_MAX_BRAKE, vision_brake))
  return bounded if bounded > a_lead else None


def fast_closing_accel_min(vehicle_accel_min):
  """Floor the close-lead cap is built against while FAST_CLOSING_LEAD_* passes the comfort floor."""
  if FAST_CLOSING_LEAD_MAX_BRAKE <= 0.0:
    return vehicle_accel_min
  return max(vehicle_accel_min, -FAST_CLOSING_LEAD_MAX_BRAKE)


class _OverrideLead:
  """Read-only view of a radarState lead with some fields replaced; every other field is the original."""
  def __init__(self, lead, **fields):
    self._lead = lead
    for k, v in fields.items():
      setattr(self, k, v)

  def __getattr__(self, name):
    return getattr(self._lead, name)


class ReassociationHold:
  """REASSOC_LEAD_BOUND: per radar track, recent (frame, dRel, vision x) and the armed window."""
  def __init__(self):
    self.frame = 0
    self.hist: dict[int, list] = {}
    self.armed: dict[int, int] = {}
    self.bound_frames = 0

  @staticmethod
  def _vision(model_msg, v_ego):
    leads = getattr(model_msg, "leadsV3", None) if model_msg is not None else None
    if leads is None or not len(leads) or float(leads[0].prob) < REASSOC_LEAD_VISION_MIN_PROB or \
       not len(leads[0].x) or not len(leads[0].v) or not len(leads[0].a):
      return None
    v = leads[0]
    return float(v.x[0]), float(v.v[0]) - float(v_ego), float(v.a[0])

  def bound(self, lead, model_msg, v_ego):
    """Bounded view of `lead`, or None when it is left as is. Call once per lead per frame, after tick()."""
    if lead is None or not bool(getattr(lead, "status", False)) or not bool(getattr(lead, "radar", False)):
      return None
    tid = int(getattr(lead, "radarTrackId", -1))
    d_rel = float(lead.dRel)
    vis = self._vision(model_msg, v_ego)
    h = self.hist.setdefault(tid, [])
    h.append((self.frame, d_rel, None if vis is None else vis[0]))
    while h and self.frame - h[0][0] > REASSOC_LEAD_WINDOW_FRAMES:
      h.pop(0)
    if vis is None:
      self.armed.pop(tid, None)
      return None
    vis_x, vis_vrel, vis_a = vis
    agrees = (vis_x <= d_rel + REASSOC_LEAD_VISION_NEAR_MARGIN_M and vis_vrel >= -REASSOC_LEAD_VISION_MAX_CLOSING and
              vis_a >= REASSOC_LEAD_VISION_MIN_ACCEL)
    if not agrees:
      self.armed.pop(tid, None)
      return None
    if tid not in self.armed:
      slid = any(x is not None and d - x >= REASSOC_LEAD_MIN_OFFSET_M and d - d_rel >= REASSOC_LEAD_MIN_DROP_M
                 for _, d, x in h)
      if not slid:
        return None
      self.armed[tid] = self.frame
    elif self.frame - self.armed[tid] > REASSOC_LEAD_HOLD_FRAMES:
      return None
    v_rel = float(lead.vRel)
    v_rel_bound = vis_vrel - REASSOC_LEAD_VREL_MARGIN
    a_bound = -max(REASSOC_LEAD_MIN_BRAKE, -vis_a)
    a_lead = float(lead.aLeadK)
    if v_rel >= v_rel_bound and a_lead >= a_bound:
      return None
    dv = max(0.0, v_rel_bound - v_rel)
    self.bound_frames += 1
    return _OverrideLead(lead, vRel=v_rel + dv, vLead=float(lead.vLead) + dv, vLeadK=float(lead.vLeadK) + dv,
                         aLeadK=max(a_lead, a_bound))

  def tick(self):
    self.frame += 1
    if len(self.hist) > 64:
      self.hist = {k: h for k, h in self.hist.items() if h and self.frame - h[-1][0] <= REASSOC_LEAD_WINDOW_FRAMES}
      self.armed = {k: f for k, f in self.armed.items() if k in self.hist}


def bound_reassociated_leads(sm, hold):
  try:
    radar_state = sm['radarState']
    model_msg = sm['modelV2']
    v_ego = float(sm['carState'].vEgo)
  except (KeyError, AttributeError):
    return sm
  hold.tick()
  leads = []
  changed = False
  for lead in (radar_state.leadOne, radar_state.leadTwo):
    b = hold.bound(lead, model_msg, v_ego)
    leads.append(lead if b is None else b)
    changed |= b is not None
  if not changed:
    return sm
  return _BoundedSubMaster(sm, _BoundedRadarState(radar_state, leads[0], leads[1]))


class _BoundedLead:
  """Read-only view of a radarState lead with aLeadK replaced; every other field is the original."""
  def __init__(self, lead, a_lead):
    self._lead = lead
    self.aLeadK = a_lead

  def __getattr__(self, name):
    return getattr(self._lead, name)


class _BoundedRadarState:
  def __init__(self, radar_state, lead_one, lead_two):
    self._radar_state = radar_state
    self.leadOne = lead_one
    self.leadTwo = lead_two

  def __getattr__(self, name):
    return getattr(self._radar_state, name)


class _BoundedSubMaster:
  """SubMaster view whose radarState carries the bounded leads; everything else delegates."""
  def __init__(self, sm, radar_state):
    self._sm = sm
    self._radar_state = radar_state

  def __getitem__(self, key):
    return self._radar_state if key == 'radarState' else self._sm[key]

  def __contains__(self, key):
    return key in self._sm

  def __getattr__(self, name):
    return getattr(self._sm, name)


def uses_off_axis_lead_bound(CP):
  return getattr(CP, "brand", "") == "honda" and CP.carFingerprint in HONDA_BOSCH_A


class OffAxisLeadHold:
  """Frames since each radar track last sat at bearing >= OFF_AXIS_LEAD_MIN_BEARING (STATUS 108)."""
  def __init__(self):
    self.frame = 0
    self.last_off_axis: dict[int, int] = {}

  def observe(self, radar_state) -> None:
    self.frame += 1
    for lead in (radar_state.leadOne, radar_state.leadTwo):
      if bool(getattr(lead, "status", False)) and bool(getattr(lead, "radar", False)) and float(lead.dRel) > 1.0 and \
         abs(float(lead.yRel)) / float(lead.dRel) >= OFF_AXIS_LEAD_MIN_BEARING:
        self.last_off_axis[int(lead.radarTrackId)] = self.frame
    if len(self.last_off_axis) > 64:
      self.last_off_axis = {k: f for k, f in self.last_off_axis.items() if self.frame - f <= OFF_AXIS_LEAD_HOLD_FRAMES}

  def held(self, lead) -> bool:
    last = self.last_off_axis.get(int(getattr(lead, "radarTrackId", -1)))
    return last is not None and self.frame - last <= OFF_AXIS_LEAD_HOLD_FRAMES


def bound_off_axis_leads(sm, hold=None):
  try:
    radar_state = sm['radarState']
    model_msg = sm['modelV2']
  except (KeyError, AttributeError):
    return sm
  if hold is not None:
    hold.observe(radar_state)
  leads = []
  changed = False
  for lead in (radar_state.leadOne, radar_state.leadTwo):
    a_lead = off_axis_lead_a_lead(lead, model_msg, hold is not None and hold.held(lead))
    if a_lead is None:
      leads.append(lead)
    else:
      leads.append(_BoundedLead(lead, a_lead))
      changed = True
  if not changed:
    return sm
  return _BoundedSubMaster(sm, _BoundedRadarState(radar_state, leads[0], leads[1]))


class NewbornLeadHold:
  """D-080: per radar track, (frame, dRel, aEgo) since it became a lead; bounds aLeadK while it is newborn."""
  def __init__(self):
    self.frame = 0
    self.hist: dict[int, list] = {}
    self.bound_frames = 0

  def _range_decel(self, h):
    """Lead accel from a quadratic fit to the range history plus ego accel, or None if too short."""
    if len(h) < NEWBORN_LEAD_FIT_FRAMES:
      return None
    t = np.array([f - h[-1][0] for f, _, _ in h], dtype=float) * DT_MDL
    d = np.array([x for _, x, _ in h], dtype=float)
    a_rel = 2.0 * float(np.polyfit(t, d, 2)[0])
    return a_rel + float(np.mean([a for _, _, a in h]))

  def bound(self, lead, a_ego):
    """aLeadK for `lead`, or None when it is left as is. Call once per lead per frame, after tick()."""
    if lead is None or not bool(getattr(lead, "status", False)) or not bool(getattr(lead, "radar", False)):
      return None
    tid = int(getattr(lead, "radarTrackId", -1))
    d_rel = float(lead.dRel)
    h = self.hist.get(tid)
    if h is None or self.frame - h[-1][0] > NEWBORN_LEAD_GAP_FRAMES or abs(d_rel - h[-1][1]) > NEWBORN_LEAD_JUMP_M:
      h = self.hist[tid] = [(self.frame, d_rel, float(a_ego))]
    elif h[-1][0] != self.frame:  # leadOne and leadTwo on one track: record it once
      h.append((self.frame, d_rel, float(a_ego)))
    if self.frame - h[0][0] >= NEWBORN_LEAD_FRAMES:
      return None
    a_lead = float(lead.aLeadK)
    a_range = self._range_decel(h)
    a_floor = -NEWBORN_LEAD_MIN_BRAKE if a_range is None else min(-NEWBORN_LEAD_MIN_BRAKE, a_range)
    if a_lead >= a_floor:
      return None
    self.bound_frames += 1
    return a_floor

  def tick(self):
    self.frame += 1
    if len(self.hist) > 64:
      self.hist = {k: h for k, h in self.hist.items() if self.frame - h[-1][0] <= NEWBORN_LEAD_GAP_FRAMES}


def bound_newborn_leads(sm, hold):
  try:
    radar_state = sm['radarState']
    a_ego = float(sm['carState'].aEgo)
  except (KeyError, AttributeError):
    return sm
  hold.tick()
  leads = []
  changed = False
  for lead in (radar_state.leadOne, radar_state.leadTwo):
    a_lead = hold.bound(lead, a_ego)
    leads.append(lead if a_lead is None else _BoundedLead(lead, a_lead))
    changed |= a_lead is not None
  if not changed:
    return sm
  return _BoundedSubMaster(sm, _BoundedRadarState(radar_state, leads[0], leads[1]))


class LongitudinalPlanner:
  def _short_action_t_active(self) -> bool:
    """D-072: built in on through PLANNER_ACTION_T_OVERRIDE."""
    return PLANNER_ACTION_T_OVERRIDE

  def __init__(self, CP, init_v=0.0, init_a=0.0, dt=DT_MDL, onpath_shadow=False):
    self.CP = CP
    # ONPATH_LEAD_BOUND: the planner that sees leadOnpath as leadOne; never nested
    self.onpath_planner = None
    if ONPATH_LEAD_BOUND and not onpath_shadow and uses_off_axis_lead_bound(CP):
      self.onpath_planner = LongitudinalPlanner(CP, init_v, init_a, dt, onpath_shadow=True)
    self.onpath_bound_active = False
    self.bound_off_axis_radar_leads = uses_off_axis_lead_bound(CP)
    self.off_axis_lead_hold = OffAxisLeadHold()
    self.reassociation_hold = ReassociationHold()
    self.newborn_lead_hold = NewbornLeadHold()
    self._onset_panic_prev = False
    self._onset_panic_soft = False
    self._onset_need_over = False
    self.longitudinal_actuator_delay = max(DT_MDL, float(CP.longitudinalActuatorDelay))
    self.close_lead_brake_cap_value = 0.0
    self.lead_geometry_required_accel = 0.0
    self.mpc = LongitudinalMpc(dt=dt)
    self.fcw = False
    self.dt = dt
    self.exp_close_lead_floor = 0.0
    self.model_allow_throttle = True
    self.model_allow_throttle_transition_t = 0.0
    self.allow_throttle = True
    self.mode = 'acc'
    self.is_preap = (
      CP.brand == "tesla" and CP.carFingerprint == "TESLA_MODEL_S_PREAP" and
      CP.openpilotLongitudinalControl and not CP.pcmCruise
    )
    self.nap_adaptive_accel = False
    self._preap_params = None
    self._preap_param_frame = 0

    self.generation = None

    self.a_desired = init_a
    self.v_desired_filter = FirstOrderFilter(init_v, 2.0, self.dt)
    self.v_model_error = 0.0
    self.output_a_target = 0.0
    self.mpc_lead_demand_hist = []
    self.brake_release_rise_ticks = BRAKE_RELEASE_DWELL_TICKS + 1
    self.coast_ceiling = None
    self.fast_closing_lead_track = None
    self.fast_closing_tick = 0
    self.fast_closing_vision_seen = {}
    self.stopped_radar_lead_hold_track = None
    self.stopped_radar_lead_hold_active = False
    self.output_should_stop = False
    self.far_follow_brake_slew_rate, self.far_follow_release_slew_rate = get_far_follow_output_slew_rates(CP)
    self.untracked_slow_lead_decel_scale = get_untracked_slow_lead_decel_scale(CP)
    self.tracked_lead_catchup_headway_margins = get_tracked_lead_catchup_headway_margins(CP)
    self.far_follow_output_slew_active = False
    self.model_launch_armed = False
    self.model_launch_stop_seen = False
    self.confident_lead_depart_elapsed = 0.0
    self.slow_creep_lead_depart_elapsed = 0.0
    self.lead_depart_release_candidate_elapsed = 0.0
    self.lead_depart_release_pending = False
    self.lead_depart_release_hold_remaining = 0.0
    self.radar_standstill_gap_settle_elapsed = 0.0
    self.radar_standstill_gap_settle_active = False
    self.tracked_lead_catchup_bias_gain = get_tracked_lead_catchup_bias_gain(CP)
    self.tracked_lead_catchup_bias_cap = get_tracked_lead_catchup_bias_cap(CP)
    self.tracked_lead_catchup_speed_range = get_tracked_lead_catchup_speed_range(CP)
    self.tracked_lead_catchup_fade_margins = get_tracked_lead_catchup_fade_margins(CP)
    self.tracked_lead_catchup_cruise_error_full = get_tracked_lead_catchup_cruise_error_full(CP)

    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)
    self.j_desired_trajectory = np.zeros(CONTROL_N)
    self.solverExecutionTime = 0.0

    # ---- Rubberband mitigation state ----
    # Two uncertainty tracks (slow/fast) for asymmetric gating
    self.uncert_slow = FirstOrderFilter(0.0, 1.6, self.dt)  # ~lam=0.6
    self.uncert_fast = FirstOrderFilter(0.0, 0.9, self.dt)  # faster cool-down for accel decisions
    # Lead stability tracking
    self.prev_lead_dist = None
    self.last_big_brake_t = 0.0
    self.stable_lead = False
    # Smoothed lead distance
    self.lead_dist_f = None

    # Uncertainty slope tracking
    self._uncert_last = 0.0
    self._uncert_last_t = None
    self._panic_bypass_log_t = 0.0
    self._safety_warning_log_t = 0.0
    self.effective_t_follow = None
    self.vision_low_speed_stop_hold_until = 0.0
    self.untracked_slow_lead_confirm_t = 0.0
    self.untracked_vision_approach_lift_confirm_t = 0.0
    self.untracked_vision_approach_lift_cap = None
    self.untracked_vision_approach_lift_target = None
    self.untracked_vision_approach_lift_hold_until = 0.0
    self.manual_stop_resume_override_until = 0.0
    self.lead_depart_accel_hold_until = 0.0
    self.lead_depart_accel_hold_floor = None
    self.post_departure_follow_settle_until = 0.0
    self.duplicate_vision_comfort_lead_source = None
    self.prev_experimental_mode = None
    self.exp_lead_departure_weight = 0.0
    self.exp_lead_departure_lift = 0.0
    self.accel_boost = AccelBoost(self.dt)
    self.experimental_release_accel_until = 0.0
    self.exp_mode_blend_weight = 0.0

    if self.is_preap:
      try:
        from openpilot.common.params import Params
        self._preap_params = Params()
        self.nap_adaptive_accel = self._preap_params.get_bool("NAPAdaptiveAccel")
      except Exception:
        self._preap_params = None
        self.nap_adaptive_accel = False

  @property
  def mlsim(self):
    return is_tinygrad_model_version(self.generation)

  def get_mpc_mode(self) -> str:
    if not self.mlsim:
      return self.mode
    return getattr(self.mpc, 'mode', 'acc')

  @staticmethod
  def get_model_speed_error(model_msg, v_ego):
    try:
      temporal_pose = model_msg.temporalPoseDEPRECATED
    except AttributeError:
      try:
        temporal_pose = model_msg.temporalPose
      except AttributeError:
        return 0.0
    if len(temporal_pose.trans):
      return float(np.clip(temporal_pose.trans[0] - v_ego, -5.0, 5.0))
    return 0.0

  @staticmethod
  def parse_model(model_msg, model_error, v_ego, starpilot_toggles):
    if (len(model_msg.position.x) == ModelConstants.IDX_N and
      len(model_msg.velocity.x) == ModelConstants.IDX_N and
      len(model_msg.acceleration.x) == ModelConstants.IDX_N):
      x = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.position.x) - model_error * T_IDXS_MPC
      v = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.velocity.x) - model_error
      a = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.acceleration.x)
      j = np.zeros(len(T_IDXS_MPC))
    else:
      x = np.zeros(len(T_IDXS_MPC))
      v = np.zeros(len(T_IDXS_MPC))
      a = np.zeros(len(T_IDXS_MPC))
      j = np.zeros(len(T_IDXS_MPC))

    if starpilot_toggles.taco_tune:
      max_lat_accel = np.interp(v_ego, [5, 10, 20], [1.5, 2.0, 3.0])
      curvatures = np.interp(T_IDXS_MPC, ModelConstants.T_IDXS, model_msg.orientationRate.z) / np.clip(v, 0.3, 100.0)
      max_v = np.sqrt(max_lat_accel / (np.abs(curvatures) + 1e-3)) - 2.0
      v = np.minimum(max_v, v)

    if len(model_msg.meta.disengagePredictions.gasPressProbs) > 1:
      throttle_prob = model_msg.meta.disengagePredictions.gasPressProbs[1]
    else:
      throttle_prob = 1.0
    return x, v, a, j, throttle_prob

  @staticmethod
  def get_model_launch_accel(model_v, model_a, action_t, v_ego):
    if len(model_v) != len(T_IDXS_MPC) or len(model_a) != len(T_IDXS_MPC):
      return None
    if float(np.interp(MODEL_LAUNCH_COMMIT_TIME, T_IDXS_MPC, model_v)) <= MODEL_LAUNCH_DISARM_SPEED:
      return None

    moving_idxs = np.flatnonzero(np.asarray(model_v) > MODEL_LAUNCH_MOVING_SPEED)
    if len(moving_idxs) == 0:
      return None

    t_cut = min(float(T_IDXS_MPC[int(moving_idxs[0])]), MODEL_LAUNCH_COMMIT_TIME)
    shifted_t = T_IDXS_MPC + t_cut
    shifted_v = np.interp(shifted_t, T_IDXS_MPC, model_v)
    shifted_a = np.interp(shifted_t, T_IDXS_MPC, model_a)
    safe_action_t = max(float(action_t), 1e-3)
    v_target = float(np.interp(safe_action_t, T_IDXS_MPC, shifted_v))
    a_launch = 2.0 * (v_target - float(shifted_v[0])) / safe_action_t - float(shifted_a[0])
    accel_cap = float(np.interp(
      float(v_ego),
      [MODEL_LAUNCH_MOVING_SPEED, MODEL_LAUNCH_DISARM_SPEED],
      [MODEL_LAUNCH_MAX_ACCEL, 0.0],
    ))
    return float(np.clip(a_launch, 0.0, accel_cap))

  @staticmethod
  def get_lead_geometry_required_accel(lead, v_ego: float) -> float:
    """Telemetry only: a DIAGNOSTIC SCENARIO ENVELOPE, not a physical requirement. Nothing consumes it.

    It is the larger of two scenarios, and neither is a guarantee: `match` assumes the lead holds
    its current speed, `stop` assumes the lead decelerates at exactly the current aLeadK until it
    stops. It therefore understates a lead that brakes harder later and overstates one that stops
    braking, and it inherits aLeadK's staleness (~0.5-0.7 s on this platform) and noise -- the
    0.1 m/s^2 branch threshold is below aLeadK's own noise, so `stop` can arm on noise alone.
    Read it as "roughly what this geometry implies", never as a control reference.

    The denominator is the PHYSICAL standoff, not the follow distance. An earlier version used
    `dRel - (t_follow*v_ego + standoff)` floored at 0.5 m, which treats a comfort target as a
    barrier: inside the follow distance -- the normal case -- the gap clamped to the floor and
    closing^2/(2*gap) exploded. It logged 40.62 m/s^2 on 00000206 at the very event it was added to
    explain, and reached 21.01 with 0.79% of frames over 10 m/s^2 on 000001fb. Re-derived against
    the standoff it never exceeds 4.64 m/s^2 over 7500 frames on those two routes, and during real
    braking on 00000206 commanded/required has a median of 1.02.

    Two terms, whichever is larger, and zero when neither applies:
      match: null the closing rate before contact        closing^2 / 2d
      stop:  both come to rest, if the lead is braking    v_ego^2 / 2*(d + lead stopping distance)
    """
    if lead is None or not lead.status:
      return 0.0
    d = max(float(lead.dRel) - LEAD_GEOMETRY_STANDOFF_M, LEAD_GEOMETRY_MIN_GAP_M)
    v_lead = max(float(lead.vLead), 0.0)
    closing = max(v_ego - v_lead, 0.0)
    lead_brake = max(-float(lead.aLeadK), 0.0)
    if closing <= 0.0 and lead_brake <= LEAD_GEOMETRY_MIN_LEAD_BRAKE:
      return 0.0
    match_term = closing ** 2 / (2.0 * d)
    stop_term = 0.0
    if lead_brake > LEAD_GEOMETRY_MIN_LEAD_BRAKE:
      stop_term = v_ego ** 2 / (2.0 * (d + v_lead ** 2 / (2.0 * lead_brake)))
    return float(min(max(match_term, stop_term), LEAD_GEOMETRY_MAX_REQUIRED_ACCEL))

  def get_close_lead_brake_cap(self, lead, v_ego, accel_min, count_lead_brake=True):
    if lead is None or not lead.status:
      return None

    lead_brake = max(0.0, -float(lead.aLeadK)) if count_lead_brake else 0.0
    reaction_t = max(self.longitudinal_actuator_delay, self.dt)
    closing_speed = max(0.0, v_ego - lead.vLead)
    projected_closing_speed = closing_speed + lead_brake * reaction_t
    if projected_closing_speed < 0.1 and lead_brake < 0.5:
      return None

    target_gap = float(np.clip(2.0 + 0.2 * v_ego, 2.0, 6.0))
    delay_buffer = projected_closing_speed * reaction_t
    available_gap = max(float(lead.dRel) - target_gap - delay_buffer, 0.5)
    projected_ttc = available_gap / max(projected_closing_speed, 0.1)
    if projected_ttc > CLOSE_LEAD_BRAKE_CAP_MAX_TTC:
      return None
    # Lead braking is counted ONCE. To null a closing speed c over a usable gap d while the lead
    # decelerates at b, the ego demand is c^2/(2d) + b. Using the lead-brake-inflated
    # projected_closing_speed in the quadratic term AND adding b again double-counted it: on
    # 000001e8 at 9:00 that inflated the demand from 4.27 to 4.87 m/s^2. The quadratic term is the
    # smaller one either way -- at that sample aLeadK supplied 85% of the total -- so this makes the
    # cap correct, not gentle. A spurious aLeadK still dominates it; that is an input problem, and
    # deliberately not something this function pretends to solve.
    match_decel = (closing_speed ** 2) / (2.0 * available_gap)
    required_decel = match_decel + 0.7 * lead_brake
    # A lead cannot shed more speed than it has. When the cap is built below the cruise comfort floor
    # (experimental mode, where accel_min is the vehicle minimum; or chill once accel_limits_turns[0]
    # has followed a_desired below -1.0), the lead-brake term is bounded by the stop geometry -- ego stops within the
    # usable gap plus the lead's own stopping distance at aLeadK, the same stop term
    # get_lead_geometry_required_accel uses -- and never taken below the match term. It bites only
    # when the lead would stop well inside the gap (a slow or stopped lead, or an extreme aLeadK).
    # Routes 00000278 / 0000027a: the 0.7*aLeadK term set the peak brake in 8 of the 9 exp-mode
    # bookmarks, counting a stopped or crawling lead's "braking" and pulsing with aLeadK. Open-loop
    # replay, 30 routes (STATUS 148): 7 of those 8 peaks -3.50..-1.97 -> -1.20..-1.89, the 27a 327 s
    # pulse -2.97 -> -0.53; every softer brake still meets this stop geometry. 278 379 s stays at
    # -3.5: a radar range jump reporting aLeadK -5.5 on a 16 m/s lead.
    # Not below the comfort floor: there the cap is at most -1.0 and the aLeadK term is what buys the
    # standstill gap. Closed loop (STATUS 64 method), bounding it in chill lost 1.3 m / 0.7 s TTC on 24f
    # E (stopping 1.0 m closer) and ended 258 63:50's second stop 3.2 m closer; measuring the
    # stop to STOP_DISTANCE instead of target_gap still lost 0.9 m on E and 2.5 m on 258.
    if lead_brake > 0.0 and accel_min < A_CRUISE_MIN:
      v_lead = max(float(lead.vLead), 0.0)
      stop_decel = v_ego ** 2 / (2.0 * (available_gap + v_lead ** 2 / (2.0 * lead_brake)))
      required_decel = max(match_decel, min(required_decel, stop_decel))

    ramp = float(np.clip((required_decel - CLOSE_LEAD_BRAKE_CAP_RAMP_MIN) /
                         (CLOSE_LEAD_BRAKE_CAP_RAMP_FULL - CLOSE_LEAD_BRAKE_CAP_RAMP_MIN), 0.0, 1.0))
    if ramp <= 0.0:
      return None

    return max(accel_min, -required_decel * ramp)

  def get_vision_untracked_slow_lead_cap(self, lead, v_ego, accel_min):
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))

    lead_brake = max(0.0, -float(lead.aLeadK))
    reaction_t = max(self.longitudinal_actuator_delay, self.dt)
    closing_speed = max(0.0, v_ego - lead.vLead)
    projected_closing_speed = closing_speed + lead_brake * reaction_t
    closing_ratio = projected_closing_speed / max(float(v_ego), 0.1)
    projected_ttc = float(lead.dRel) / max(projected_closing_speed, 0.1)

    standard_entry = bool(
      projected_closing_speed >= VISION_UNTRACKED_SLOW_LEAD_MIN_CLOSING_SPEED and
      closing_ratio >= VISION_UNTRACKED_SLOW_LEAD_MIN_CLOSING_RATIO and
      projected_ttc <= VISION_UNTRACKED_SLOW_LEAD_TRIGGER_TTC
    )
    centered_relaxed_entry = (
      abs(float(getattr(lead, "yRel", 0.0))) <= VISION_UNTRACKED_SLOW_LEAD_RELAXED_ENTRY_MAX_LATERAL_OFFSET
    )
    high_confidence_early_entry = bool(
      centered_relaxed_entry and
      lead_prob + 1e-6 >= VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_MODEL_PROB and
      projected_closing_speed >= VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_CLOSING_SPEED and
      closing_ratio >= VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_CLOSING_RATIO and
      projected_ttc <= VISION_UNTRACKED_SLOW_LEAD_EARLY_TRIGGER_TTC
    )
    near_early_entry = bool(
      centered_relaxed_entry and
      float(lead.dRel) <= VISION_UNTRACKED_SLOW_LEAD_NEAR_MAX_DISTANCE and
      lead_prob + 1e-6 >= VISION_UNTRACKED_SLOW_LEAD_NEAR_MIN_MODEL_PROB and
      projected_closing_speed >= VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_CLOSING_SPEED and
      closing_ratio >= VISION_UNTRACKED_SLOW_LEAD_NEAR_MIN_CLOSING_RATIO and
      projected_ttc <= VISION_UNTRACKED_SLOW_LEAD_EARLY_TRIGGER_TTC
    )
    if not (standard_entry or high_confidence_early_entry or near_early_entry):
      return None

    trigger_ttc = VISION_UNTRACKED_SLOW_LEAD_TRIGGER_TTC
    min_closing_ratio = VISION_UNTRACKED_SLOW_LEAD_MIN_CLOSING_RATIO
    if high_confidence_early_entry:
      trigger_ttc = VISION_UNTRACKED_SLOW_LEAD_EARLY_TRIGGER_TTC
      min_closing_ratio = VISION_UNTRACKED_SLOW_LEAD_EARLY_MIN_CLOSING_RATIO
    if near_early_entry:
      trigger_ttc = VISION_UNTRACKED_SLOW_LEAD_EARLY_TRIGGER_TTC
      min_closing_ratio = VISION_UNTRACKED_SLOW_LEAD_NEAR_MIN_CLOSING_RATIO

    min_model_prob = VISION_UNTRACKED_SLOW_LEAD_MIN_MODEL_PROB
    max_distance_time = VISION_UNTRACKED_SLOW_LEAD_MAX_DISTANCE_TIME
    if float(lead.vLead) <= VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_LEAD_SPEED and \
        projected_ttc <= VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_TTC:
      closing_relax = float(np.clip((projected_closing_speed - VISION_UNTRACKED_SLOW_LEAD_RELAXED_MIN_CLOSING_SPEED) /
                                    (VISION_UNTRACKED_SLOW_LEAD_RELAXED_FULL_CLOSING_SPEED -
                                     VISION_UNTRACKED_SLOW_LEAD_RELAXED_MIN_CLOSING_SPEED), 0.0, 1.0))
      ttc_relax = float(np.clip((VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_TTC - projected_ttc) /
                                (VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_TTC -
                                 VISION_UNTRACKED_SLOW_LEAD_FULL_TTC), 0.0, 1.0))
      relax_factor = closing_relax * ttc_relax
      min_model_prob = float(np.interp(relax_factor, [0.0, 1.0],
                                       [VISION_UNTRACKED_SLOW_LEAD_MIN_MODEL_PROB,
                                        VISION_UNTRACKED_SLOW_LEAD_RELAXED_MODEL_PROB]))
      max_distance_time = float(np.interp(relax_factor, [0.0, 1.0],
                                          [VISION_UNTRACKED_SLOW_LEAD_MAX_DISTANCE_TIME,
                                           VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_DISTANCE_TIME]))

    max_distance = float(np.clip(max_distance_time * v_ego,
                                 VISION_UNTRACKED_SLOW_LEAD_MIN_DISTANCE,
                                 VISION_UNTRACKED_SLOW_LEAD_MAX_DISTANCE))
    if float(lead.dRel) > max_distance:
      return None

    if lead_prob + 1e-6 < min_model_prob:
      return None

    time_factor = float(np.clip((trigger_ttc - projected_ttc) /
                                (trigger_ttc - VISION_UNTRACKED_SLOW_LEAD_FULL_TTC),
                                0.0, 1.0))
    prob_factor = float(np.clip((lead_prob - min_model_prob) /
                                (VISION_UNTRACKED_SLOW_LEAD_FULL_MODEL_PROB - min_model_prob),
                                0.0, 1.0))
    closing_factor = float(np.clip((closing_ratio - min_closing_ratio) /
                                   (VISION_UNTRACKED_SLOW_LEAD_FULL_CLOSING_RATIO - min_closing_ratio),
                                   0.0, 1.0))
    approach_decel = VISION_UNTRACKED_SLOW_LEAD_MAX_DECEL * self.untracked_slow_lead_decel_scale * np.clip(
      0.5 * time_factor + 0.3 * prob_factor + 0.2 * closing_factor, 0.0, 1.0)
    if approach_decel < VISION_UNTRACKED_SLOW_LEAD_MIN_DECEL:
      return None

    return max(accel_min, -approach_decel)

  @staticmethod
  def get_vision_untracked_approach_lift_cap(lead, v_ego, t_follow):
    """Trim throttle before a confident vision lead reaches the tracking window."""
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None
    if float(v_ego) < VISION_UNTRACKED_APPROACH_LIFT_MIN_EGO_SPEED:
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < VISION_UNTRACKED_APPROACH_LIFT_MIN_MODEL_PROB:
      return None
    if abs(float(getattr(lead, "yRel", 0.0))) > VISION_UNTRACKED_APPROACH_LIFT_MAX_LATERAL_OFFSET:
      return None
    if float(lead.dRel) > VISION_UNTRACKED_APPROACH_LIFT_MAX_DISTANCE:
      return None

    closing_speed = float(v_ego) - float(lead.vLead)
    if closing_speed < VISION_UNTRACKED_APPROACH_LIFT_MIN_CLOSING_SPEED:
      return None

    desired_gap = float(desired_follow_distance(v_ego, lead.vLead, t_follow))
    gap_excess = float(lead.dRel) - desired_gap
    if gap_excess < VISION_UNTRACKED_APPROACH_LIFT_MIN_GAP_EXCESS:
      return 0.0

    time_to_desired_gap = gap_excess / max(closing_speed, 0.1)
    if time_to_desired_gap > VISION_UNTRACKED_APPROACH_LIFT_TRIGGER_TIME:
      return None

    # This path only removes positive acceleration. Braking remains exclusively
    # owned by lead tracking and the existing close-lead safety caps.
    return float(np.interp(
      time_to_desired_gap,
      [VISION_UNTRACKED_APPROACH_LIFT_FULL_TIME, VISION_UNTRACKED_APPROACH_LIFT_TRIGGER_TIME],
      [0.0, VISION_UNTRACKED_APPROACH_LIFT_MAX_ACCEL],
    ))

  def update_vision_untracked_approach_lift_cap(self, raw_cap, output_a_target, prev_output_a_target,
                                                now_t, untracked):
    if untracked and raw_cap is not None:
      if self.untracked_vision_approach_lift_cap is None:
        self.untracked_vision_approach_lift_confirm_t = min(
          self.untracked_vision_approach_lift_confirm_t + self.dt,
          VISION_UNTRACKED_APPROACH_LIFT_CONFIRM_TIME,
        )
        if self.untracked_vision_approach_lift_confirm_t >= VISION_UNTRACKED_APPROACH_LIFT_CONFIRM_TIME:
          self.untracked_vision_approach_lift_cap = float(prev_output_a_target)
      if self.untracked_vision_approach_lift_cap is not None:
        self.untracked_vision_approach_lift_target = float(raw_cap)
        self.untracked_vision_approach_lift_hold_until = now_t + VISION_UNTRACKED_APPROACH_LIFT_HOLD_TIME
    elif self.untracked_vision_approach_lift_cap is None:
      self.untracked_vision_approach_lift_confirm_t = 0.0

    active_cap = self.untracked_vision_approach_lift_cap
    if active_cap is None:
      return None

    holding = untracked and now_t < self.untracked_vision_approach_lift_hold_until
    target = self.untracked_vision_approach_lift_target if holding else float(output_a_target)
    if target is None:
      target = float(output_a_target)

    lower = active_cap - VISION_UNTRACKED_APPROACH_LIFT_RATE_DOWN * self.dt
    upper = active_cap + VISION_UNTRACKED_APPROACH_LIFT_RATE_UP * self.dt
    active_cap = float(np.clip(target, lower, upper))
    self.untracked_vision_approach_lift_cap = active_cap

    if not holding and active_cap >= float(output_a_target) - 1e-6:
      self.untracked_vision_approach_lift_confirm_t = 0.0
      self.untracked_vision_approach_lift_cap = None
      self.untracked_vision_approach_lift_target = None
      self.untracked_vision_approach_lift_hold_until = 0.0
      return None

    return active_cap

  def get_vision_slow_stopped_lead_cap(self, lead, v_ego, accel_min, t_follow):
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < VISION_SLOW_LEAD_MIN_MODEL_PROB or float(lead.vLead) > VISION_SLOW_LEAD_MAX_SPEED:
      return None

    lead_brake = max(0.0, -float(lead.aLeadK))
    reaction_t = max(self.longitudinal_actuator_delay, self.dt)
    closing_speed = max(0.0, v_ego - lead.vLead)
    projected_closing_speed = closing_speed + lead_brake * reaction_t
    if projected_closing_speed < VISION_SLOW_LEAD_MIN_CLOSING_SPEED:
      return None

    stop_gap = float(max(STOP_DISTANCE + 1.0, 2.5 + 0.15 * max(float(lead.vLead), 0.0)))
    delay_buffer = projected_closing_speed * reaction_t
    available_gap = max(float(lead.dRel) - stop_gap - delay_buffer, 0.5)
    projected_ttc = available_gap / max(projected_closing_speed, 0.1)
    if projected_ttc > VISION_SLOW_LEAD_TRIGGER_TTC:
      return None

    time_factor = float(np.clip((VISION_SLOW_LEAD_TRIGGER_TTC - projected_ttc) /
                                (VISION_SLOW_LEAD_TRIGGER_TTC - VISION_SLOW_LEAD_FULL_TTC), 0.0, 1.0))
    prob_factor = float(np.clip((lead_prob - VISION_SLOW_LEAD_MIN_MODEL_PROB) /
                                (VISION_LEAD_APPROACH_FULL_MODEL_PROB - VISION_SLOW_LEAD_MIN_MODEL_PROB), 0.0, 1.0))
    speed_factor = float(np.clip((VISION_SLOW_LEAD_MAX_SPEED - max(float(lead.vLead), 0.0)) /
                                 VISION_SLOW_LEAD_MAX_SPEED, 0.0, 1.0))
    required_decel = (projected_closing_speed ** 2) / (2.0 * available_gap)
    decel_scale = 0.45 + 0.35 * time_factor + 0.20 * speed_factor
    approach_decel = min(VISION_SLOW_LEAD_MAX_DECEL, required_decel * decel_scale)
    approach_decel *= 0.65 + 0.35 * prob_factor
    if approach_decel < VISION_SLOW_LEAD_MIN_DECEL:
      return None

    return max(accel_min, -approach_decel)

  def get_dynamic_t_follow(self, base_t_follow, lead, v_ego):
    base_t_follow = float(base_t_follow)
    target_t_follow = base_t_follow

    if lead is not None and lead.status:
      lead_prob = float(getattr(lead, "modelProb", 1.0 if bool(getattr(lead, "radar", False)) else 0.0))
      if bool(getattr(lead, "radar", False)) or lead_prob >= VISION_LEAD_APPROACH_MIN_MODEL_PROB:
        lead_brake = max(0.0, -float(lead.aLeadK))
        closing_speed = max(0.0, v_ego - lead.vLead)
        if closing_speed >= LEAD_APPROACH_TFOLLOW_MIN_CLOSING_SPEED or lead_brake >= LEAD_APPROACH_TFOLLOW_MIN_LEAD_BRAKE:
          desired_gap = float(desired_follow_distance(v_ego, lead.vLead, base_t_follow))
          approach_window = max(LEAD_APPROACH_TFOLLOW_WINDOW_MIN, LEAD_APPROACH_TFOLLOW_WINDOW_GAIN * float(v_ego))
          if float(lead.dRel) <= desired_gap + approach_window:
            reaction_t = max(self.longitudinal_actuator_delay, self.dt)
            projected_closing_speed = closing_speed + 0.5 * lead_brake * reaction_t
            gap_to_follow = max(float(lead.dRel) - desired_gap, 0.0)
            time_to_follow = gap_to_follow / max(projected_closing_speed, 0.1)
            time_factor = float(np.clip((LEAD_APPROACH_TFOLLOW_TRIGGER_TIME - time_to_follow) /
                                        (LEAD_APPROACH_TFOLLOW_TRIGGER_TIME - LEAD_APPROACH_TFOLLOW_FULL_TIME), 0.0, 1.0))
            closing_factor = float(np.clip(closing_speed / LEAD_APPROACH_TFOLLOW_MAX_CLOSING_SPEED, 0.0, 1.0))
            brake_factor = float(np.clip(lead_brake / LEAD_APPROACH_TFOLLOW_MAX_LEAD_BRAKE, 0.0, 1.0))
            target_delta = LEAD_APPROACH_TFOLLOW_MAX_DELTA * np.clip(
              0.55 * time_factor + 0.25 * closing_factor + 0.20 * brake_factor, 0.0, 1.0)
            if not bool(getattr(lead, "radar", False)):
              gap_deficit = max(desired_gap - float(lead.dRel), 0.0)
              gap_buffer = max(VISION_LEAD_TFOLLOW_GAP_BUFFER_MIN,
                               VISION_LEAD_TFOLLOW_GAP_BUFFER_GAIN * float(v_ego))
              gap_factor = float(np.clip(gap_deficit / gap_buffer, 0.0, 1.0))
              slow_lead_factor = float(np.clip((VISION_LEAD_TFOLLOW_SLOW_LEAD_SPEED - float(lead.vLead)) /
                                               VISION_LEAD_TFOLLOW_SLOW_LEAD_SPEED, 0.0, 1.0))
              vision_extra = VISION_LEAD_TFOLLOW_MAX_EXTRA_DELTA * np.clip(
                0.40 * time_factor + 0.30 * gap_factor + 0.20 * slow_lead_factor + 0.10 * closing_factor,
                0.0, 1.0)
              target_delta += vision_extra
            target_t_follow = base_t_follow + float(target_delta)

    if self.effective_t_follow is None:
      self.effective_t_follow = base_t_follow

    rate = LEAD_APPROACH_TFOLLOW_RATE_UP if target_t_follow > self.effective_t_follow else LEAD_APPROACH_TFOLLOW_RATE_DOWN
    step = rate * self.dt
    self.effective_t_follow = float(np.clip(target_t_follow, self.effective_t_follow - step, self.effective_t_follow + step))
    self.effective_t_follow = max(base_t_follow, self.effective_t_follow)
    return self.effective_t_follow

  def get_vision_low_speed_stop_buffer_cap(self, lead, v_ego, accel_min):
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None, False

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < VISION_LOW_SPEED_STOP_BUFFER_MIN_MODEL_PROB:
      return None, False

    lead_speed = max(float(lead.vLead), 0.0)
    relative_speed = float(v_ego) - lead_speed
    max_lead_speed, hold_max_lead_speed = get_vision_low_speed_stop_buffer_lead_speed_limits(
      self.CP,
      VISION_LOW_SPEED_STOP_BUFFER_MAX_LEAD_SPEED,
      VISION_LOW_SPEED_STOP_BUFFER_HOLD_MAX_LEAD_SPEED,
    )
    closing_speed = max(0.0, v_ego - lead_speed)
    entry_context = (
      v_ego <= VISION_LOW_SPEED_STOP_BUFFER_MAX_EGO_SPEED and
      lead_speed <= max_lead_speed and
      closing_speed >= VISION_LOW_SPEED_STOP_BUFFER_MIN_CLOSING_SPEED
    )
    hold_context = (
      v_ego <= VISION_LOW_SPEED_STOP_BUFFER_MAX_EGO_SPEED and
      lead_speed <= hold_max_lead_speed and
      relative_speed >= VISION_LOW_SPEED_STOP_BUFFER_MIN_HOLD_REL_SPEED
    )

    now_t = time.monotonic()
    entry_buffer = max(3.2, VISION_LOW_SPEED_STOP_BUFFER_BASE +
                       VISION_LOW_SPEED_STOP_BUFFER_EGO_GAIN * float(v_ego) +
                       VISION_LOW_SPEED_STOP_BUFFER_LEAD_GAIN * lead_speed)
    release_buffer = entry_buffer + VISION_LOW_SPEED_STOP_BUFFER_RELEASE_MARGIN
    if entry_context and float(lead.dRel) <= entry_buffer:
      self.vision_low_speed_stop_hold_until = now_t + VISION_LOW_SPEED_STOP_BUFFER_HOLD_TIME

    latched = now_t < self.vision_low_speed_stop_hold_until
    active = bool(
      (entry_context and float(lead.dRel) <= entry_buffer) or
      (latched and hold_context and float(lead.dRel) <= release_buffer)
    )
    if not active:
      return None, False

    min_stop_brake = VISION_LOW_SPEED_STOP_BUFFER_MIN_BRAKE + VISION_LOW_SPEED_STOP_BUFFER_BRAKE_GAIN * float(v_ego)
    return max(accel_min, -min_stop_brake), True

  def get_vision_close_stop_hold_cap(self, lead, v_ego, accel_min, should_stop):
    if not should_stop or lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < VISION_CLOSE_STOP_HOLD_MIN_MODEL_PROB:
      return None

    lead_speed = max(float(lead.vLead), 0.0)
    near_standstill_settle = bool(
      float(v_ego) <= VISION_CLOSE_SETTLE_MAX_EGO_SPEED and
      lead_speed <= VISION_CLOSE_SETTLE_MAX_LEAD_SPEED and
      float(lead.dRel) <= VISION_CLOSE_SETTLE_MAX_DISTANCE
    )
    max_lead_speed = VISION_CLOSE_SETTLE_MAX_LEAD_SPEED if near_standstill_settle else VISION_CLOSE_STOP_HOLD_MAX_LEAD_SPEED
    max_distance = VISION_CLOSE_SETTLE_MAX_DISTANCE if near_standstill_settle else VISION_CLOSE_STOP_HOLD_MAX_DISTANCE
    if (
      float(v_ego) > VISION_CLOSE_STOP_HOLD_MAX_EGO_SPEED or
      lead_speed > max_lead_speed or
      float(lead.dRel) > max_distance
    ):
      return None

    distance_factor = float(np.clip((max_distance - float(lead.dRel)) /
                                    max(max_distance - 1.8, 0.1), 0.0, 1.0))
    speed_factor = float(np.clip(float(v_ego) / max(VISION_CLOSE_STOP_HOLD_MAX_EGO_SPEED, 0.1), 0.0, 1.0))
    hold_brake = VISION_CLOSE_STOP_HOLD_MIN_BRAKE + 0.08 * distance_factor + 0.08 * speed_factor
    if near_standstill_settle:
      settle_brake = VISION_CLOSE_SETTLE_MIN_BRAKE + 0.10 * distance_factor + 0.04 * speed_factor
      hold_brake = max(hold_brake, settle_brake)
    hold_brake = float(np.clip(hold_brake, VISION_CLOSE_STOP_HOLD_MIN_BRAKE, VISION_CLOSE_STOP_HOLD_MAX_BRAKE))
    brake_floor = -hold_brake
    return brake_floor if accel_min >= 0.0 else max(accel_min, brake_floor)

  def get_vision_close_release_hold_cap(self, lead, v_ego, accel_min, should_stop):
    if should_stop or lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < VISION_CLOSE_RELEASE_HOLD_MIN_MODEL_PROB:
      return None

    lead_speed = max(float(lead.vLead), 0.0)
    lead_delta = lead_speed - float(v_ego)
    near_standstill_settle = bool(
      float(v_ego) <= VISION_CLOSE_SETTLE_MAX_EGO_SPEED and
      lead_speed <= VISION_CLOSE_SETTLE_MAX_LEAD_SPEED and
      float(lead.dRel) <= VISION_CLOSE_SETTLE_MAX_DISTANCE and
      lead_delta <= VISION_CLOSE_SETTLE_MAX_LEAD_DELTA
    )
    max_lead_speed = VISION_CLOSE_SETTLE_MAX_LEAD_SPEED if near_standstill_settle else VISION_CLOSE_RELEASE_HOLD_MAX_LEAD_SPEED
    max_distance = VISION_CLOSE_SETTLE_MAX_DISTANCE if near_standstill_settle else VISION_CLOSE_RELEASE_HOLD_MAX_DISTANCE
    max_lead_delta = VISION_CLOSE_SETTLE_MAX_LEAD_DELTA if near_standstill_settle else VISION_CLOSE_RELEASE_HOLD_MAX_LEAD_DELTA
    if (
      float(v_ego) > VISION_CLOSE_RELEASE_HOLD_MAX_EGO_SPEED or
      lead_speed > max_lead_speed or
      float(lead.dRel) > max_distance or
      lead_delta < VISION_CLOSE_RELEASE_HOLD_MIN_LEAD_DELTA or
      lead_delta > max_lead_delta
    ):
      return None

    distance_factor = float(np.clip((max_distance - float(lead.dRel)) /
                                    max(max_distance - 2.8, 0.1), 0.0, 1.0))
    speed_factor = float(np.clip(float(v_ego) / max(VISION_CLOSE_RELEASE_HOLD_MAX_EGO_SPEED, 0.1), 0.0, 1.0))
    delta_factor = float(np.clip((max_lead_delta - lead_delta) /
                                 max(max_lead_delta - VISION_CLOSE_RELEASE_HOLD_MIN_LEAD_DELTA, 0.1),
                                 0.0, 1.0))
    hold_brake = VISION_CLOSE_RELEASE_HOLD_MIN_BRAKE + 0.12 * distance_factor + 0.06 * speed_factor + 0.04 * delta_factor
    if near_standstill_settle:
      settle_brake = VISION_CLOSE_SETTLE_MIN_BRAKE + 0.08 * distance_factor + 0.02 * delta_factor
      hold_brake = max(hold_brake, settle_brake)
    hold_brake = float(np.clip(hold_brake, VISION_CLOSE_RELEASE_HOLD_MIN_BRAKE, VISION_CLOSE_RELEASE_HOLD_MAX_BRAKE))
    brake_floor = -hold_brake
    return brake_floor if accel_min >= 0.0 else max(accel_min, brake_floor)

  def get_vision_close_settle_cap(self, lead, v_ego, accel_min, stop_guard_active):
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < VISION_CLOSE_STOP_HOLD_MIN_MODEL_PROB:
      return None

    lead_speed = max(float(lead.vLead), 0.0)
    lead_delta = lead_speed - float(v_ego)
    if (
      float(v_ego) > VISION_CLOSE_SETTLE_MAX_EGO_SPEED or
      lead_speed > VISION_CLOSE_SETTLE_MAX_LEAD_SPEED or
      float(lead.dRel) > VISION_CLOSE_SETTLE_MAX_DISTANCE or
      lead_delta > VISION_CLOSE_SETTLE_MAX_LEAD_DELTA
    ):
      return None

    if not stop_guard_active and lead_delta < 0.0:
      return None

    distance_factor = float(np.clip((VISION_CLOSE_SETTLE_MAX_DISTANCE - float(lead.dRel)) /
                                    max(VISION_CLOSE_SETTLE_MAX_DISTANCE - 2.8, 0.1), 0.0, 1.0))
    delta_factor = float(np.clip((VISION_CLOSE_SETTLE_MAX_LEAD_DELTA - lead_delta) /
                                 max(VISION_CLOSE_SETTLE_MAX_LEAD_DELTA, 0.1), 0.0, 1.0))
    hold_brake = VISION_CLOSE_SETTLE_MIN_BRAKE + 0.10 * distance_factor + 0.04 * delta_factor
    hold_brake = float(np.clip(hold_brake, VISION_CLOSE_SETTLE_MIN_BRAKE, VISION_CLOSE_SETTLE_MAX_BRAKE))
    brake_floor = -hold_brake
    return brake_floor if accel_min >= 0.0 else max(accel_min, brake_floor)

  def get_vision_close_final_guard_cap(self, lead, v_ego, accel_min):
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    lead_speed = max(float(lead.vLead), 0.0)
    if (
      lead_prob < VISION_CLOSE_STOP_HOLD_MIN_MODEL_PROB or
      float(v_ego) > VISION_CLOSE_FINAL_GUARD_MAX_EGO_SPEED or
      lead_speed > VISION_CLOSE_FINAL_GUARD_MAX_LEAD_SPEED or
      float(lead.dRel) > VISION_CLOSE_FINAL_GUARD_MAX_DISTANCE
    ):
      return None

    distance_factor = float(np.clip((VISION_CLOSE_FINAL_GUARD_MAX_DISTANCE - float(lead.dRel)) /
                                    max(VISION_CLOSE_FINAL_GUARD_MAX_DISTANCE - 2.8, 0.1), 0.0, 1.0))
    hold_brake = VISION_CLOSE_FINAL_GUARD_MIN_BRAKE + 0.10 * distance_factor
    hold_brake = float(np.clip(hold_brake, VISION_CLOSE_FINAL_GUARD_MIN_BRAKE, VISION_CLOSE_FINAL_GUARD_MAX_BRAKE))
    brake_floor = -hold_brake
    return brake_floor if accel_min >= 0.0 else max(accel_min, brake_floor)

  def _update_manual_stop_resume_override(self, sm):
    now_t = time.monotonic()
    lead = sm["radarState"].leadOne
    no_lead = not bool(getattr(lead, "status", False))
    try:
      starpilot_car_state = sm["starpilotCarState"]
    except KeyError:
      starpilot_car_state = None
    accel_pressed = bool(
      getattr(starpilot_car_state, "accelPressed", False) or
      getattr(sm["carState"], "gasPressed", False)
    )
    model_should_stop = bool(getattr(sm["modelV2"].action, "shouldStop", False))
    standstill = bool(getattr(sm["carState"], "standstill", False))
    forcing_stop = bool(getattr(sm["starpilotPlan"], "forcingStop", False))
    red_light = bool(getattr(sm["starpilotPlan"], "redLight", False))

    if standstill and no_lead and accel_pressed and (forcing_stop or red_light or model_should_stop):
      self.manual_stop_resume_override_until = now_t + MANUAL_STOP_RESUME_OVERRIDE_TIME

    return bool(
      no_lead and
      float(getattr(sm["carState"], "vEgo", 0.0)) < MANUAL_STOP_RESUME_OVERRIDE_MAX_SPEED and
      now_t < self.manual_stop_resume_override_until
    )

  def is_confident_lead_depart(self, lead, v_ego):
    if lead is None or not lead.status:
      return False

    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    if not lead_radar and lead_prob < LEAD_DEPART_ACCEL_HOLD_MIN_MODEL_PROB:
      return False

    lead_speed = max(float(lead.vLead), 0.0)
    lead_delta = lead_speed - float(v_ego)
    lead_accel = float(getattr(lead, "aLeadK", 0.0))
    return bool(
      float(lead.dRel) >= LEAD_DEPART_CONFIDENT_MIN_GAP and
      float(lead.dRel) <= LEAD_DEPART_CONFIDENT_MAX_GAP and
      lead_speed >= LEAD_DEPART_CONFIDENT_MIN_LEAD_SPEED and
      lead_delta >= LEAD_DEPART_CONFIDENT_MIN_LEAD_DELTA and
      lead_accel >= LEAD_DEPART_CONFIDENT_MIN_LEAD_ACCEL
    )

  def is_slow_creep_lead_depart(self, lead, v_ego, standstill_nudge_gap):
    if lead is None or not lead.status:
      return False

    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    if not lead_radar and lead_prob < STANDSTILL_STOPPED_LEAD_GUARD_MIN_MODEL_PROB:
      return False

    if abs(float(getattr(lead, "yRel", 0.0))) > STANDSTILL_STOPPED_LEAD_GUARD_MAX_LATERAL_OFFSET:
      return False

    lead_gap = float(getattr(lead, "dRel", 0.0))
    lead_speed = max(float(getattr(lead, "vLead", 0.0)), 0.0)
    lead_accel = float(getattr(lead, "aLeadK", 0.0))
    creep_tune = get_toyota_rav4_tss2_lead_creep_tune(self.CP)
    min_lead_speed, min_lead_accel = (
      (STANDSTILL_LEAD_CREEP_RELEASE_MIN_LEAD_SPEED,
       STANDSTILL_LEAD_CREEP_RELEASE_MIN_LEAD_ACCEL)
      if creep_tune is None else creep_tune
    )
    return bool(
      float(v_ego) <= STANDSTILL_LEAD_DEPART_MAX_EGO_SPEED and
      lead_gap >= standstill_nudge_gap + STANDSTILL_LEAD_CREEP_RELEASE_MIN_GAP_MARGIN and
      lead_speed >= min_lead_speed and
      lead_accel >= min_lead_accel
    )

  def get_safe_depart_release_hold_lead(self, v_ego):
    credible_leads = [
      lead for lead in (self.lead_one, self.lead_two)
      if lead is not None and
      bool(getattr(lead, "status", False)) and
      (bool(getattr(lead, "radar", False)) or
       float(getattr(lead, "modelProb", 0.0)) >= LEAD_DEPART_RELEASE_HOLD_MIN_MODEL_PROB) and
      abs(float(getattr(lead, "yRel", 0.0))) <= LEAD_DEPART_RELEASE_HOLD_MAX_LATERAL_OFFSET
    ]
    moving_leads = [
      lead for lead in credible_leads
      if float(getattr(lead, "dRel", 0.0)) >= LEAD_DEPART_RELEASE_HOLD_MIN_DISTANCE and
      float(getattr(lead, "vLead", 0.0)) >= LEAD_DEPART_RELEASE_HOLD_MIN_LEAD_SPEED and
      float(getattr(lead, "vLead", 0.0)) - float(v_ego) >= LEAD_DEPART_RELEASE_HOLD_MIN_LEAD_DELTA and
      max(0.0, -float(getattr(lead, "aLeadK", 0.0))) <= LEAD_DEPART_RELEASE_HOLD_MAX_LEAD_BRAKE
    ]
    if not moving_leads:
      return None

    selected_lead = min(moving_leads, key=lambda lead: float(lead.dRel))
    stopped_conflict = any(
      lead is not selected_lead and
      float(getattr(lead, "dRel", float("inf"))) <= float(selected_lead.dRel) + LEAD_DEPART_RELEASE_HOLD_CONFLICT_DISTANCE_MARGIN and
      float(getattr(lead, "vLead", 0.0)) < LEAD_DEPART_RELEASE_HOLD_CONFLICT_SPEED
      for lead in credible_leads
    )
    return None if stopped_conflict else selected_lead

  def get_vehicle_far_follow_slew_target(self, v_ego, prev_target, target, output_should_stop, panic_bypass):
    if self.far_follow_brake_slew_rate <= 0.0 or self.far_follow_release_slew_rate <= 0.0 or output_should_stop or panic_bypass:
      self.far_follow_output_slew_active = False
      return target

    centered_leads = [
      lead for lead in (self.lead_one, self.lead_two)
      if bool(getattr(lead, "status", False)) and
      abs(float(getattr(lead, "yRel", 0.0))) <= VEHICLE_FAR_FOLLOW_SLEW_MAX_LATERAL_OFFSET
    ]
    safe_far_follow = bool(centered_leads and float(v_ego) >= VEHICLE_FAR_FOLLOW_SLEW_MIN_SPEED)
    for lead in centered_leads:
      distance = float(getattr(lead, "dRel", 0.0))
      closing_speed = max(0.0, float(v_ego) - float(getattr(lead, "vLead", v_ego)))
      ttc = distance / max(closing_speed, 0.1) if closing_speed > 0.1 else float("inf")
      headway = distance / max(float(v_ego), 1e-3)
      safe_far_follow &= bool(
        distance >= max(VEHICLE_FAR_FOLLOW_SLEW_MIN_DISTANCE,
                        VEHICLE_FAR_FOLLOW_SLEW_MIN_DISTANCE_TIME * float(v_ego)) and
        headway >= VEHICLE_FAR_FOLLOW_SLEW_MIN_HEADWAY and
        ttc >= VEHICLE_FAR_FOLLOW_SLEW_MIN_TTC
      )

    slew_was_active = self.far_follow_output_slew_active
    self.far_follow_output_slew_active = safe_far_follow
    if not safe_far_follow or not slew_was_active:
      return target

    return float(np.clip(
      target,
      float(prev_target) - self.far_follow_brake_slew_rate * self.dt,
      float(prev_target) + self.far_follow_release_slew_rate * self.dt,
    ))

  @staticmethod
  def is_radar_standstill_gap_settle_candidate(lead, v_ego, target_gap, active=False,
                                               allow_vision=False, max_extra_gap=RADAR_STANDSTILL_GAP_SETTLE_MAX_EXTRA_GAP):
    if lead is None or not lead.status or (not bool(getattr(lead, "radar", False)) and not allow_vision):
      return False
    if float(v_ego) > RADAR_STANDSTILL_GAP_SETTLE_MAX_EGO_SPEED:
      return False
    if abs(float(getattr(lead, "yRel", 0.0))) > RADAR_STANDSTILL_GAP_SETTLE_MAX_LATERAL_OFFSET:
      return False
    if abs(float(getattr(lead, "vLead", 0.0))) > RADAR_STANDSTILL_GAP_SETTLE_MAX_LEAD_SPEED:
      return False
    if allow_vision and (
      bool(getattr(lead, "radar", False)) or
      float(getattr(lead, "modelProb", 0.0)) < 0.99
    ):
      return False

    lead_gap = float(getattr(lead, "dRel", 0.0))
    min_margin = RADAR_STANDSTILL_GAP_SETTLE_EXIT_MARGIN if active else RADAR_STANDSTILL_GAP_SETTLE_ENTRY_MARGIN
    return bool(
      lead_gap > target_gap + min_margin and
      lead_gap <= target_gap + float(max_extra_gap)
    )

  def update_radar_standstill_gap_settle(self, sm, target_gap, allow_vision=False, max_extra_gap=None):
    vetoed = bool(
      getattr(sm["carState"], "brakePressed", False) or
      getattr(sm["carState"], "gasPressed", False) or
      getattr(sm["starpilotPlan"], "forcingStop", False) or
      getattr(sm["starpilotPlan"], "redLight", False)
    )
    candidates = [
      lead for lead in (self.lead_one, self.lead_two)
      if self.is_radar_standstill_gap_settle_candidate(
        lead,
        float(sm["carState"].vEgo),
        target_gap,
        active=self.radar_standstill_gap_settle_active,
        allow_vision=allow_vision,
        max_extra_gap=(RADAR_STANDSTILL_GAP_SETTLE_MAX_EXTRA_GAP if max_extra_gap is None else max_extra_gap),
      )
    ]

    if vetoed or not candidates:
      self.radar_standstill_gap_settle_elapsed = 0.0
      self.radar_standstill_gap_settle_active = False
      return False

    if self.radar_standstill_gap_settle_active:
      return True

    if not bool(sm["carState"].standstill):
      self.radar_standstill_gap_settle_elapsed = 0.0
      return False

    self.radar_standstill_gap_settle_elapsed = min(
      RADAR_STANDSTILL_GAP_SETTLE_CONFIRM_TIME,
      self.radar_standstill_gap_settle_elapsed + self.dt,
    )
    self.radar_standstill_gap_settle_active = (
      self.radar_standstill_gap_settle_elapsed + 1e-6 >= RADAR_STANDSTILL_GAP_SETTLE_CONFIRM_TIME
    )
    return self.radar_standstill_gap_settle_active

  @staticmethod
  def get_centered_model_lead(model_data):
    try:
      leads = model_data.leadsV3
    except Exception:
      return None

    best_candidate = None
    for i in range(3):
      try:
        lead = leads[i]
        prob = float(lead.prob)
        x = float(lead.x[0])
        y = float(lead.y[0])
        v = float(lead.v[0])
      except Exception:
        continue

      if (
        prob < RADAR_DEPART_CONFLICT_MIN_MODEL_PROB or
        x <= 0.0 or
        x > RADAR_DEPART_CONFLICT_MAX_MODEL_DISTANCE or
        abs(y) > RADAR_DEPART_CONFLICT_MAX_MODEL_LATERAL or
        max(v, 0.0) > RADAR_DEPART_CONFLICT_MAX_MODEL_LEAD_SPEED
      ):
        continue

      if best_candidate is None or x < best_candidate[0]:
        best_candidate = (x, y, v, prob)

    return best_candidate

  def has_offcenter_radar_depart_conflict(self, sm):
    if float(getattr(sm["carState"], "vEgo", 0.0)) > RADAR_DEPART_CONFLICT_MAX_EGO_SPEED:
      return False

    centered_model_lead = self.get_centered_model_lead(sm["modelV2"])
    if centered_model_lead is None:
      return False

    centered_model_dist = float(centered_model_lead[0])
    for lead in (self.lead_one, self.lead_two):
      if not lead.status or not bool(getattr(lead, "radar", False)):
        continue

      lead_dist = float(getattr(lead, "dRel", 0.0))
      if lead_dist <= 0.0 or lead_dist > RADAR_DEPART_CONFLICT_MAX_RADAR_DISTANCE:
        continue
      if abs(float(getattr(lead, "yRel", 0.0))) < RADAR_DEPART_CONFLICT_MIN_RADAR_LATERAL:
        continue
      if abs(lead_dist - centered_model_dist) > RADAR_DEPART_CONFLICT_MAX_DISTANCE_MISMATCH:
        continue

      return True

    return False

  def get_lead_depart_accel_floor(self, lead, v_ego, model_desired_accel):
    if lead is None or not lead.status:
      return None

    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    if not lead_radar and lead_prob < LEAD_DEPART_ACCEL_HOLD_MIN_MODEL_PROB:
      return None

    lead_speed = max(float(lead.vLead), 0.0)
    lead_brake = max(0.0, -float(getattr(lead, "aLeadK", 0.0)))
    lead_delta = lead_speed - float(v_ego)
    confident_depart = self.is_confident_lead_depart(lead, v_ego)
    min_lead_speed = LEAD_DEPART_CONFIDENT_MIN_LEAD_SPEED if confident_depart else LEAD_DEPART_ACCEL_HOLD_MIN_LEAD_SPEED
    min_lead_delta = LEAD_DEPART_CONFIDENT_MIN_LEAD_DELTA if confident_depart else LEAD_DEPART_ACCEL_HOLD_MIN_LEAD_DELTA
    min_gap = LEAD_DEPART_CONFIDENT_MIN_GAP if confident_depart else LEAD_DEPART_ACCEL_HOLD_MIN_GAP
    min_model_accel = 0.0 if confident_depart else LEAD_DEPART_ACCEL_HOLD_MIN_MODEL_ACCEL
    if (
      float(v_ego) > LEAD_DEPART_ACCEL_HOLD_MAX_EGO_SPEED or
      lead_speed < min_lead_speed or
      lead_delta < min_lead_delta or
      float(lead.dRel) < min_gap or
      lead_brake > LEAD_DEPART_ACCEL_HOLD_MAX_LEAD_BRAKE or
      float(model_desired_accel) < min_model_accel
    ):
      return None

    gap_factor = float(np.clip((float(lead.dRel) - LEAD_DEPART_ACCEL_HOLD_MIN_GAP) /
                               max(LEAD_DEPART_ACCEL_HOLD_FULL_GAP - LEAD_DEPART_ACCEL_HOLD_MIN_GAP, 0.1), 0.0, 1.0))
    lead_factor = float(np.clip((lead_speed - LEAD_DEPART_ACCEL_HOLD_MIN_LEAD_SPEED) /
                                max(LEAD_DEPART_ACCEL_HOLD_FULL_LEAD_SPEED - LEAD_DEPART_ACCEL_HOLD_MIN_LEAD_SPEED, 0.1), 0.0, 1.0))
    departure_tune = get_honda_accord_lead_departure_tune(self.CP)
    if departure_tune is None:
      departure_tune = get_toyota_rav4_tss2_lead_departure_tune(self.CP)
    max_accel = LEAD_DEPART_ACCEL_HOLD_MAX_ACCEL if departure_tune is None else departure_tune[0]
    assist = LEAD_DEPART_ACCEL_ASSIST if departure_tune is None else departure_tune[1]
    accel_cap = LEAD_DEPART_ACCEL_HOLD_MIN_ACCEL + (max_accel - LEAD_DEPART_ACCEL_HOLD_MIN_ACCEL) * np.clip(
      0.55 * lead_factor + 0.45 * gap_factor, 0.0, 1.0)
    assisted_model_accel = float(model_desired_accel) + assist
    return min(accel_cap, max(assisted_model_accel, LEAD_DEPART_ACCEL_HOLD_MIN_ACCEL))

  def get_reusable_lead_depart_accel_floor(self, lead, v_ego, t_follow):
    if self.lead_depart_accel_hold_floor is None or lead is None or not lead.status:
      return None

    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    if not lead_radar and lead_prob < LEAD_DEPART_ACCEL_HOLD_MIN_MODEL_PROB:
      return None

    if abs(float(getattr(lead, "yRel", 0.0))) > STANDSTILL_STOPPED_LEAD_GUARD_MAX_LATERAL_OFFSET:
      return None

    d_rel = float(getattr(lead, "dRel", 0.0))
    if d_rel < LEAD_DEPART_ACCEL_HOLD_REUSE_MIN_GAP:
      return None

    lead_brake = max(0.0, -float(getattr(lead, "aLeadK", 0.0)))
    if lead_brake > LEAD_DEPART_ACCEL_HOLD_REUSE_MAX_LEAD_BRAKE:
      return None

    closing_speed = max(float(v_ego) - float(getattr(lead, "vLead", 0.0)), 0.0)
    if closing_speed > LEAD_DEPART_ACCEL_HOLD_REUSE_MAX_CLOSING_SPEED:
      return None

    actual_headway = d_rel / max(float(v_ego), 1e-3)
    headway_margin = actual_headway - float(t_follow)
    if headway_margin < LEAD_DEPART_ACCEL_HOLD_REUSE_MIN_HEADWAY_MARGIN:
      return None

    return float(self.lead_depart_accel_hold_floor)

  def get_low_speed_weak_lead_accel_cap(self, lead, v_ego):
    if lead is None or not lead.status:
      return None

    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    if not lead_radar and lead_prob < LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_MODEL_PROB:
      return None

    d_rel = float(getattr(lead, "dRel", 0.0))
    lead_speed = max(float(getattr(lead, "vLead", 0.0)), 0.0)
    lead_delta = lead_speed - float(v_ego)
    lead_accel = float(getattr(lead, "aLeadK", 0.0))
    lead_lateral = abs(float(getattr(lead, "yRel", 0.0)))
    if (
      float(v_ego) > LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_EGO_SPEED or
      d_rel > LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_DISTANCE or
      lead_speed > LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_SPEED or
      lead_lateral > LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LATERAL_OFFSET or
      lead_delta > LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_DELTA or
      lead_accel > LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_ACCEL
    ):
      return None

    if (
      float(v_ego) <= LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MAX_EGO_SPEED and
      d_rel >= LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_GAP and
      lead_speed >= LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_LEAD_SPEED and
      lead_delta >= LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_LEAD_DELTA and
      lead_accel >= LOW_SPEED_WEAK_LEAD_ACCEL_CAP_STRONG_DEPART_MIN_LEAD_ACCEL
    ):
      return None

    distance_factor = float(np.clip(
      (d_rel - LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_DISTANCE) /
      max(LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_DISTANCE - LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_DISTANCE, 0.1),
      0.0, 1.0,
    ))
    delta_factor = float(np.clip(
      (lead_delta - LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_LEAD_DELTA) /
      max(LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_DELTA - LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_LEAD_DELTA, 0.1),
      0.0, 1.0,
    ))
    accel_factor = float(np.clip(
      (lead_accel - LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_LEAD_ACCEL) /
      max(LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_LEAD_ACCEL - LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_LEAD_ACCEL, 0.1),
      0.0, 1.0,
    ))
    cap_strength = float(np.clip(0.5 * distance_factor + 0.3 * delta_factor + 0.2 * accel_factor, 0.0, 1.0))
    return LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_ACCEL + (
      LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MAX_ACCEL - LOW_SPEED_WEAK_LEAD_ACCEL_CAP_MIN_ACCEL
    ) * cap_strength

  def get_honda_accord_stop_go_accel_target(self, lead, v_ego, previous_target, target, blocked):
    """Smooth the Accord's low-speed lead launch without touching braking targets."""
    if blocked or target <= 0.0:
      return float(target)

    cap = get_honda_accord_stop_go_accel_cap(self.CP, lead, v_ego)
    if cap is None:
      return float(target)

    limited_target = min(float(target), cap)
    if limited_target > float(previous_target):
      rise_rate = get_honda_accord_stop_go_accel_rise_rate(self.CP)
      if rise_rate > 0.0:
        limited_target = min(
          limited_target,
          max(0.0, float(previous_target) + rise_rate * self.dt),
        )
    return float(limited_target)

  def get_standstill_stopped_lead_guard_cap(self, lead, v_ego, accel_min, stop_distance,
                                            release_ready, confident_depart_ready):
    if lead is None or not lead.status or release_ready or confident_depart_ready:
      return None
    max_ego_speed = get_standstill_stopped_lead_guard_max_ego_speed(
      self.CP, STANDSTILL_STOPPED_LEAD_GUARD_MAX_EGO_SPEED,
    )
    if float(v_ego) > max_ego_speed:
      return None

    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    if not lead_radar and lead_prob < STANDSTILL_STOPPED_LEAD_GUARD_MIN_MODEL_PROB:
      return None

    if abs(float(getattr(lead, "yRel", 0.0))) > STANDSTILL_STOPPED_LEAD_GUARD_MAX_LATERAL_OFFSET:
      return None

    lead_speed = max(float(getattr(lead, "vLead", 0.0)), 0.0)
    lead_delta = lead_speed - float(v_ego)
    max_lead_speed = get_standstill_stopped_lead_guard_max_lead_speed(
      self.CP, STANDSTILL_STOPPED_LEAD_GUARD_MAX_LEAD_SPEED,
    )
    max_distance = max(
      STANDSTILL_STOPPED_LEAD_GUARD_MIN_DISTANCE,
      float(stop_distance) + get_standstill_stopped_lead_guard_distance_margin(self.CP),
    )
    if (
      float(getattr(lead, "dRel", float("inf"))) > max_distance or
      lead_speed > max_lead_speed or
      lead_delta > STANDSTILL_STOPPED_LEAD_GUARD_MAX_LEAD_DELTA
    ):
      return None

    distance_factor = float(np.clip((max_distance - float(lead.dRel)) /
                                    max(max_distance - STANDSTILL_STOPPED_LEAD_GUARD_MIN_DISTANCE, 0.1),
                                    0.0, 1.0))
    speed_factor = float(np.clip(lead_speed / max(max_lead_speed, 0.1), 0.0, 1.0))
    delta_factor = float(np.clip((STANDSTILL_STOPPED_LEAD_GUARD_MAX_LEAD_DELTA - lead_delta) /
                                 max(STANDSTILL_STOPPED_LEAD_GUARD_MAX_LEAD_DELTA, 0.1),
                                 0.0, 1.0))
    hold_brake = STANDSTILL_STOPPED_LEAD_GUARD_MIN_BRAKE + 0.06 * distance_factor + 0.02 * speed_factor + 0.02 * delta_factor
    hold_brake = float(np.clip(
      hold_brake,
      STANDSTILL_STOPPED_LEAD_GUARD_MIN_BRAKE,
      STANDSTILL_STOPPED_LEAD_GUARD_MAX_BRAKE,
    ))
    brake_floor = -hold_brake
    return brake_floor if accel_min >= 0.0 else max(accel_min, brake_floor)

  def post_departure_follow_settle_active(self, lead, v_ego, t_follow):
    if lead is None or not lead.status:
      return False
    if float(v_ego) < POST_DEPARTURE_FOLLOW_SETTLE_MIN_SPEED:
      return False

    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    if not lead_radar and lead_prob < POST_DEPARTURE_FOLLOW_SETTLE_MIN_MODEL_PROB:
      return False

    if abs(float(getattr(lead, "yRel", 0.0))) > POST_DEPARTURE_FOLLOW_SETTLE_MAX_LATERAL_OFFSET:
      return False

    actual_headway = float(lead.dRel) / max(float(v_ego), 1e-3)
    headway_margin = actual_headway - float(t_follow)
    lead_brake = max(0.0, -float(getattr(lead, "aLeadK", 0.0)))
    closing_speed = max(float(v_ego) - float(lead.vLead), 0.0)
    now = time.monotonic()
    if now > self.post_departure_follow_settle_until:
      self.post_departure_follow_settle_until = 0.0
      lead_delta = float(lead.vLead) - float(v_ego)
      lead_accel = float(getattr(lead, "aLeadK", 0.0))
      # Rolling launches can miss the standstill release edge that normally arms
      # this latch. Confirm the same safe pull-away state from lead motion instead.
      rolling_departure = (
        float(v_ego) <= POST_DEPARTURE_FOLLOW_SETTLE_MAX_ARM_SPEED and
        lead_delta >= POST_DEPARTURE_FOLLOW_SETTLE_ARM_MIN_LEAD_DELTA and
        lead_accel >= POST_DEPARTURE_FOLLOW_SETTLE_ARM_MIN_LEAD_ACCEL and
        headway_margin >= POST_DEPARTURE_FOLLOW_SETTLE_ARM_MIN_HEADWAY_MARGIN
      )
      if not rolling_departure:
        return False
      self.post_departure_follow_settle_until = now + POST_DEPARTURE_FOLLOW_SETTLE_LATCH_TIME

    if (
      headway_margin <= POST_DEPARTURE_FOLLOW_SETTLE_COMPLETE_HEADWAY_MARGIN or
      lead_brake > POST_DEPARTURE_FOLLOW_SETTLE_MAX_LEAD_BRAKE or
      closing_speed > POST_DEPARTURE_FOLLOW_SETTLE_MAX_CLOSING_SPEED
    ):
      self.post_departure_follow_settle_until = 0.0
      return False

    return True

  def update_experimental_release_accel_state(self, experimental_mode, now_t, v_ego=None):
    if self.prev_experimental_mode is True and not experimental_mode:
      low_speed_release = v_ego is not None and float(v_ego) < EXPERIMENTAL_RELEASE_ACCEL_LOW_SPEED_THRESHOLD
      hold_time = EXPERIMENTAL_RELEASE_ACCEL_LOW_SPEED_HOLD_TIME if low_speed_release else EXPERIMENTAL_RELEASE_ACCEL_HOLD_TIME
      self.experimental_release_accel_until = now_t + hold_time
    elif experimental_mode:
      self.experimental_release_accel_until = 0.0
    self.prev_experimental_mode = bool(experimental_mode)

  def get_experimental_speed_handoff_weight(self, v_ego, experimental_mode, following_lead,
                                            starpilot_toggles, hold_experimental):
    if not experimental_mode or hold_experimental:
      return 0.0

    limit_key = "conditional_limit_lead" if following_lead else "conditional_limit"
    limit = float(getattr(starpilot_toggles, limit_key, 0.0) or 0.0)
    if limit <= 1.0:
      return 0.0

    return float(np.clip(
      (float(v_ego) - (limit - EXPERIMENTAL_SPEED_HANDOFF_BAND)) / EXPERIMENTAL_SPEED_HANDOFF_BAND,
      0.0,
      1.0,
    ))

  @staticmethod
  def is_cem_following_lead(tracking_lead, d_rel, t_follow, v_ego):
    return bool(tracking_lead and float(d_rel) < (float(t_follow) * 2.0) * float(v_ego))

  def update_exp_lead_departure(self, output_a_target, output_a_target_e2e, output_a_target_mpc, v_ego, t_follow,
                                hold_experimental):
    raw = 0.0
    if not hold_experimental:
      raw = get_exp_lead_departure_weight(self.lead_one, v_ego, t_follow)
    lead = self.lead_one
    lead_closing = lead is not None and lead.status and (
      float(lead.vRel) < 0.0 or float(getattr(lead, "aLeadK", 0.0)) < EXP_LEAD_DEPARTURE_MIN_LEAD_ACCEL)
    if hold_experimental or lead_closing:
      # Disarm at once when the lead closes or brakes or a stop is planned; the lift then releases below.
      self.exp_lead_departure_weight = 0.0
    else:
      tau = EXP_LEAD_DEPARTURE_RISE_TAU if raw > self.exp_lead_departure_weight else EXP_LEAD_DEPARTURE_FALL_TAU
      self.exp_lead_departure_weight += (raw - self.exp_lead_departure_weight) * self.dt / (tau + self.dt)
    lift = apply_exp_lead_departure(output_a_target, output_a_target_e2e, output_a_target_mpc, self.exp_lead_departure_weight)
    lift = min(lift - output_a_target, self.exp_lead_departure_lift + EXP_LEAD_DEPARTURE_MAX_LIFT_RISE * self.dt)
    urgent = (hold_experimental or output_a_target_e2e < EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE or
              (lead is not None and lead.status and (float(lead.vRel) < EXP_LEAD_DEPARTURE_URGENT_VREL or
                                                     float(getattr(lead, "aLeadK", 0.0)) < EXP_LEAD_DEPARTURE_URGENT_LEAD_ACCEL)))
    if not urgent:
      released = min(self.exp_lead_departure_lift - EXP_LEAD_DEPARTURE_MAX_LIFT_FALL * self.dt,
                     output_a_target_mpc - output_a_target)
      lift = max(lift, released, 0.0)
    self.exp_lead_departure_lift = lift
    return output_a_target + lift

  @staticmethod
  def apply_experimental_speed_handoff(output_a_target, output_a_target_mpc, output_a_target_e2e, speed_handoff):
    if speed_handoff <= 0.0:
      return output_a_target
    if output_a_target_e2e < min(output_a_target_mpc, EXPERIMENTAL_HANDOFF_KEEP_E2E_BRAKE):
      return output_a_target
    return (1.0 - speed_handoff) * output_a_target + speed_handoff * output_a_target_mpc

  def get_experimental_release_accel_target(self, lead, v_ego, base_t_follow,
                                            prev_output_a_target, output_a_target,
                                            release_active):
    if not release_active or lead is None or not lead.status or v_ego < EXPERIMENTAL_RELEASE_ACCEL_MIN_SPEED:
      return None

    lead_speed = float(lead.vLead)
    lead_delta = lead_speed - float(v_ego)
    lead_brake = max(0.0, -float(getattr(lead, "aLeadK", 0.0)))
    lead_radar = bool(getattr(lead, "radar", False))
    lead_prob = float(getattr(lead, "modelProb", 1.0 if lead_radar else 0.0))
    actual_headway = float(lead.dRel) / max(float(v_ego), 1e-3)
    if lead_speed < EXPERIMENTAL_RELEASE_ACCEL_MIN_LEAD_SPEED:
      return None
    if not (EXPERIMENTAL_RELEASE_ACCEL_MIN_LEAD_DELTA <= lead_delta <= EXPERIMENTAL_RELEASE_ACCEL_MAX_LEAD_DELTA):
      return None
    if lead_brake > EXPERIMENTAL_RELEASE_ACCEL_MAX_LEAD_BRAKE:
      return None
    if not lead_radar and lead_prob < EXPERIMENTAL_RELEASE_ACCEL_MIN_MODEL_PROB:
      return None
    if abs(float(getattr(lead, "yRel", 0.0))) > EXPERIMENTAL_RELEASE_ACCEL_MAX_LATERAL_OFFSET:
      return None
    if actual_headway < float(base_t_follow) + EXPERIMENTAL_RELEASE_ACCEL_MIN_HEADWAY_MARGIN:
      return None
    if float(output_a_target) - float(prev_output_a_target) < EXPERIMENTAL_RELEASE_ACCEL_MIN_DELTA_A:
      return None

    return min(float(output_a_target), float(prev_output_a_target) + EXPERIMENTAL_RELEASE_ACCEL_STEP)

  def get_tracked_vision_model_brake_floor(self, lead, v_ego, accel_min, t_follow, model_desired):
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None
    if float(v_ego) < TRACKED_VISION_MODEL_FLOOR_MIN_SPEED:
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < TRACKED_VISION_MODEL_FLOOR_MIN_MODEL_PROB:
      return None

    model_brake = max(0.0, -float(model_desired))
    if model_brake < TRACKED_VISION_MODEL_FLOOR_MIN_MODEL_DECEL:
      return None

    lead_brake = max(0.0, -float(getattr(lead, "aLeadK", 0.0)))
    reaction_t = max(self.longitudinal_actuator_delay, self.dt)
    projected_closing_speed = max(0.0, float(v_ego) - float(lead.vLead)) + lead_brake * reaction_t
    if projected_closing_speed < TRACKED_VISION_MODEL_FLOOR_MIN_CLOSING_SPEED:
      return None

    desired_gap = float(desired_follow_distance(v_ego, lead.vLead, t_follow))
    gap_margin = float(lead.dRel) - desired_gap
    max_gap_margin = max(TRACKED_VISION_MODEL_FLOOR_MAX_GAP_BUFFER_MIN,
                         TRACKED_VISION_MODEL_FLOOR_MAX_GAP_BUFFER_GAIN * float(v_ego))
    if gap_margin < TRACKED_VISION_MODEL_FLOOR_MIN_GAP_MARGIN or gap_margin > max_gap_margin:
      return None

    projected_ttc = float(lead.dRel) / max(projected_closing_speed, 0.1)
    if projected_ttc > TRACKED_VISION_MODEL_FLOOR_MAX_TTC:
      return None

    floor_decel = float(np.interp(
      model_brake,
      [TRACKED_VISION_MODEL_FLOOR_MIN_MODEL_DECEL, 1.6],
      [TRACKED_VISION_MODEL_FLOOR_MIN_DECEL, TRACKED_VISION_MODEL_FLOOR_MAX_DECEL],
    ))
    floor_decel += float(np.interp(lead_brake, [0.0, 0.8], [0.0, TRACKED_VISION_MODEL_FLOOR_LEAD_BRAKE_MAX]))
    return max(accel_min, -min(TRACKED_VISION_MODEL_FLOOR_MAX_DECEL, floor_decel))

  def get_tracked_vision_model_brake_cap(self, lead, v_ego, t_follow, model_desired):
    if lead is None or not lead.status or bool(getattr(lead, "radar", False)):
      return None
    if not (TRACKED_VISION_MODEL_CAP_MIN_SPEED <= float(v_ego) <= TRACKED_VISION_MODEL_CAP_MAX_SPEED):
      return None

    lead_prob = float(getattr(lead, "modelProb", 0.0))
    if lead_prob < TRACKED_VISION_MODEL_CAP_MIN_MODEL_PROB:
      return None

    model_brake = max(0.0, -float(model_desired))
    if model_brake > TRACKED_VISION_MODEL_CAP_MAX_MODEL_DECEL:
      return None

    lead_brake = max(0.0, -float(getattr(lead, "aLeadK", 0.0)))
    if lead_brake > TRACKED_VISION_MODEL_CAP_MAX_LEAD_BRAKE:
      return None

    reaction_t = max(self.longitudinal_actuator_delay, self.dt)
    projected_closing_speed = max(0.0, float(v_ego) - float(lead.vLead)) + lead_brake * reaction_t
    if not (TRACKED_VISION_MODEL_CAP_MIN_CLOSING_SPEED <= projected_closing_speed <= TRACKED_VISION_MODEL_CAP_MAX_CLOSING_SPEED):
      return None

    desired_gap = float(desired_follow_distance(v_ego, lead.vLead, t_follow))
    gap_margin = float(lead.dRel) - desired_gap
    max_gap_margin = max(TRACKED_VISION_MODEL_CAP_MAX_GAP_BUFFER_MIN,
                         TRACKED_VISION_MODEL_CAP_MAX_GAP_BUFFER_GAIN * float(v_ego))
    if gap_margin < TRACKED_VISION_MODEL_CAP_MIN_GAP_MARGIN or gap_margin > max_gap_margin:
      return None

    projected_ttc = float(lead.dRel) / max(projected_closing_speed, 0.1)
    if projected_ttc < TRACKED_VISION_MODEL_CAP_MIN_TTC:
      return None

    cap_decel = float(np.interp(
      model_brake,
      [0.0, TRACKED_VISION_MODEL_CAP_MAX_MODEL_DECEL],
      [TRACKED_VISION_MODEL_CAP_MIN_DECEL, TRACKED_VISION_MODEL_CAP_MAX_DECEL],
    ))
    cap_decel += float(np.interp(
      projected_closing_speed,
      [TRACKED_VISION_MODEL_CAP_MIN_CLOSING_SPEED, TRACKED_VISION_MODEL_CAP_MAX_CLOSING_SPEED],
      [0.0, 0.08],
    ))
    return -min(TRACKED_VISION_MODEL_CAP_MAX_DECEL, cap_decel)

  @staticmethod
  def raw_close_lead_needs_control(lead, v_ego):
    if lead is None or not lead.status:
      return False

    d_rel = max(float(lead.dRel), 0.0)
    lead_speed = max(float(getattr(lead, "vLead", 0.0)), 0.0)
    closing_speed = float(v_ego - lead.vLead)
    lead_braking = float(lead.aLeadK) < -0.5
    centered_lead = abs(float(getattr(lead, "yRel", 0.0))) <= RAW_LEAD_LOW_SPEED_HOLD_MAX_LATERAL_OFFSET
    if (
      centered_lead and
      float(v_ego) <= RAW_LEAD_LOW_SPEED_HOLD_MAX_EGO_SPEED and
      lead_speed <= RAW_LEAD_LOW_SPEED_HOLD_MAX_LEAD_SPEED and
      d_rel <= RAW_LEAD_LOW_SPEED_HOLD_MAX_DISTANCE and
      closing_speed >= RAW_LEAD_LOW_SPEED_HOLD_MIN_CLOSING_SPEED
    ):
      return True

    if closing_speed <= RAW_LEAD_SAFETY_MIN_CLOSING_SPEED and not lead_braking:
      return False

    dynamic_distance = max(RAW_LEAD_SAFETY_DISTANCE, 3.0 * float(v_ego))
    if bool(getattr(lead, "radar", False)) and lead_speed <= RAW_RADAR_STOPPED_LEAD_MAX_SPEED:
      dynamic_distance = max(
        dynamic_distance,
        min(RAW_RADAR_STOPPED_LEAD_MAX_DISTANCE, 5.0 * float(v_ego)),
      )
    if (SLOW_RADAR_LEAD_STOP_GATE and bool(getattr(lead, "radar", False)) and
        lead_speed <= SLOW_RADAR_LEAD_GATE_MAX_SPEED and
        float(getattr(lead, "modelProb", 0.0)) >= SLOW_RADAR_LEAD_GATE_MIN_PROB and closing_speed > 0.0):
      dynamic_distance = max(dynamic_distance, min(
        RAW_RADAR_STOPPED_LEAD_MAX_DISTANCE,
        closing_speed ** 2 / (2.0 * SLOW_RADAR_LEAD_GATE_DECEL) + SLOW_RADAR_LEAD_GATE_STANDOFF))
    ttc = d_rel / max(closing_speed, 0.1) if closing_speed > 0.1 else float("inf")
    return d_rel < dynamic_distance and (ttc < RAW_LEAD_SAFETY_TTC or lead_braking)

  @staticmethod
  def stopped_radar_lead_hold_qualifies(lead, v_ego):
    if lead is None or not lead.status or not bool(getattr(lead, "radar", False)):
      return False
    if float(getattr(lead, "modelProb", 0.0)) < STOPPED_RADAR_LEAD_HOLD_MIN_MODEL_PROB:
      return False
    if abs(float(getattr(lead, "yRel", 0.0))) > STOPPED_RADAR_LEAD_HOLD_MAX_LATERAL_OFFSET:
      return False
    if float(v_ego) >= STOPPED_RADAR_LEAD_HOLD_MAX_EGO_SPEED:
      return False
    return (float(lead.vLead) <= STOPPED_RADAR_LEAD_HOLD_MAX_LEAD_SPEED and
            float(v_ego) - float(lead.vLead) >= STOPPED_RADAR_LEAD_HOLD_MIN_CLOSING_SPEED)

  def update_stopped_radar_lead_hold(self, lead, v_ego, base_lead_control_active):
    # Arms on a qualifying lead one while lead control is already active; holds lead control only for that
    # same radar track. See STOPPED_RADAR_LEAD_HOLD_*.
    if not self.stopped_radar_lead_hold_qualifies(lead, v_ego):
      self.stopped_radar_lead_hold_track = None
      return False
    track_id = int(getattr(lead, "radarTrackId", -1))
    if base_lead_control_active:
      self.stopped_radar_lead_hold_track = track_id
      return False
    if self.stopped_radar_lead_hold_track != track_id:
      self.stopped_radar_lead_hold_track = None
      return False
    return True

  def slew_coast_ceiling(self, ceiling, prev_output, reset):
    # Output ceiling moved at most COAST_CEILING_JERK * dt per cycle; a falling ceiling starts from the last output.
    step = COAST_CEILING_JERK * self.dt
    if reset or self.coast_ceiling is None:
      self.coast_ceiling = float(ceiling)
    elif ceiling < self.coast_ceiling:
      self.coast_ceiling = float(max(ceiling, min(self.coast_ceiling, prev_output) - step))
    else:
      self.coast_ceiling = float(min(ceiling, self.coast_ceiling + step))
    return self.coast_ceiling

  def get_mpc_lead_brake_accel_min(self, accel_min, mpc_target):
    # Output floor for the final clip: accel_min, lowered to a persistent MPC lead-brake demand.
    lead_demand = None
    if mpc_target is not None and self.mpc.source in ('lead0', 'lead1'):
      lead = self.lead_one if self.mpc.source == 'lead0' else self.lead_two
      if lead.status and (float(lead.vRel) < LEAD_CLOSING_FLOOR_VREL or float(lead.aLeadK) < LEAD_CLOSING_FLOOR_ALEAD):
        lead_demand = float(mpc_target)
    self.mpc_lead_demand_hist = (self.mpc_lead_demand_hist + [lead_demand])[-MPC_LEAD_BRAKE_PERSIST_TICKS:]
    if (not MPC_LEAD_BRAKE_PASSES_COMFORT_FLOOR or len(self.mpc_lead_demand_hist) < MPC_LEAD_BRAKE_PERSIST_TICKS or
        None in self.mpc_lead_demand_hist):
      return accel_min
    return min(accel_min, max(self.mpc_lead_demand_hist))

  def fast_closing_lead_passes_floor(self, lead, lead_source, v_ego, model_msg):
    # True when this lead's close-lead brake cap may pass the comfort floor (FAST_CLOSING_LEAD_*).
    if not FAST_CLOSING_LEAD_PASSES_COMFORT_FLOOR or lead is None or not lead.status or not bool(getattr(lead, "radar", False)):
      return False
    track = int(getattr(lead, "radarTrackId", -1))
    if self.fast_closing_lead_track is not None and track == self.fast_closing_lead_track:
      if -float(lead.vRel) >= FAST_CLOSING_LEAD_HOLD_CLOSING:
        return True
      self.fast_closing_lead_track = None
      return False
    closing = -float(lead.vRel)
    d_rel = float(lead.dRel)
    if closing < FAST_CLOSING_LEAD_MIN_CLOSING or d_rel > FAST_CLOSING_LEAD_MAX_TTC * closing:
      return False
    leads = getattr(model_msg, "leadsV3", None) if model_msg is not None else None
    vision = leads[0] if leads and len(leads[0].x) > 0 and len(leads[0].v) > 0 else None
    if (vision is not None and float(vision.prob) >= FAST_CLOSING_LEAD_MIN_VISION_PROB and
        abs(float(vision.x[0]) - d_rel) <= FAST_CLOSING_LEAD_VISION_MATCH * d_rel and
        v_ego - float(vision.v[0]) >= FAST_CLOSING_LEAD_MIN_VISION_CLOSING):
      self.fast_closing_vision_seen[track] = self.fast_closing_tick
    seen = self.fast_closing_vision_seen.get(track)
    if self.mpc.source != lead_source or seen is None or self.fast_closing_tick - seen > FAST_CLOSING_LEAD_VISION_MEMORY_TICKS:
      return False
    self.fast_closing_lead_track = track
    return True

  def get_lane_change_merge_accel_floor(self, sm, starpilot_toggles, scene_v_ego, v_cruise, action_t, blocked,
                                        mpc_demand=None):
    # Accel floor (m/s^2) to apply as max(output_a_target, floor) while merging out, else None.
    if blocked or not getattr(starpilot_toggles, "lane_change_close_gap", False):
      return None

    meta = sm['modelV2'].meta
    if meta.laneChangeState not in LC_MERGE_STATES:
      return None

    CS = sm['carState']
    if CS.standstill or bool(getattr(CS, "brakePressed", False)):
      return None
    if scene_v_ego < float(getattr(starpilot_toggles, "minimum_lane_change_speed", 0.0)):
      return None

    direction = meta.laneChangeDirection
    if (direction == LaneChangeDirection.left and CS.leftBlindspot) or \
       (direction == LaneChangeDirection.right and CS.rightBlindspot):
      return None

    # Only intervene when there's a lead we're merging around; leave curve/open-road braking alone.
    lead = self.lead_one
    if not lead.status:
      return None

    d_rel = float(lead.dRel)
    closing = scene_v_ego - float(lead.vLead)
    ttc = d_rel / closing if closing > LC_MERGE_CLOSING_MIN else float('inf')
    # A close lead (small gap or short time-to-reach) keeps full braking authority.
    if ttc < LC_MERGE_TTC_MIN or d_rel < LC_MERGE_MIN_DIST:
      return None
    if (LC_MERGE_RELEASE_MPC_DEMAND is not None and mpc_demand is not None and
        mpc_demand < LC_MERGE_RELEASE_MPC_DEMAND and ttc < LC_MERGE_TTC_ACCEL):
      return None
    if LC_MERGE_RELEASE_LEAD_BRAKE is not None and float(lead.aLeadK) < LC_MERGE_RELEASE_LEAD_BRAKE:
      return None

    floor = LC_MERGE_BRAKE_FLOOR
    push_ok = LC_MERGE_PUSH_MAX_CLOSING is None or closing <= LC_MERGE_PUSH_MAX_CLOSING
    if (push_ok and self.allow_throttle and ttc >= LC_MERGE_TTC_ACCEL and d_rel >= LC_MERGE_ACCEL_MIN_DIST and
        np.isfinite(v_cruise) and (v_cruise - scene_v_ego) >= LC_MERGE_HEADROOM_MIN):
      cruise_cap = max(0.0, (v_cruise - scene_v_ego) / max(action_t, self.dt))
      floor = min(LC_MERGE_ACCEL_BIAS, cruise_cap)
    return floor

  def update(self, sm, starpilot_toggles):
    self._update(sm, starpilot_toggles)
    if self.onpath_planner is None:
      return
    onpath_sm = onpath_lead_view(sm)
    self.onpath_planner._update(onpath_sm if onpath_sm is not None else sm, starpilot_toggles)
    self.onpath_bound_active = onpath_sm is not None
    if self.onpath_bound_active:
      self.output_a_target = onpath_bounded_target(self.output_a_target, self.onpath_planner.output_a_target)

  def _update(self, sm, starpilot_toggles):
    if self.bound_off_axis_radar_leads:
      if REASSOC_LEAD_BOUND:
        sm = bound_reassociated_leads(sm, self.reassociation_hold)
      sm = bound_off_axis_leads(sm, self.off_axis_lead_hold)
    if BRAKE_ONSET_LIMIT or bool(getattr(starpilot_toggles, "brake_onset_limit", False)):
      sm = bound_newborn_leads(sm, self.newborn_lead_hold)
    if self.is_preap:
      self._preap_param_frame += 1
      if self._preap_params is not None and (self._preap_param_frame % 20) == 0:
        self.nap_adaptive_accel = self._preap_params.get_bool("NAPAdaptiveAccel")

    self.generation = getattr(starpilot_toggles, "model_version", None)
    self.longitudinal_actuator_delay = max(DT_MDL, get_longitudinal_actuator_delay(self.CP, starpilot_toggles))
    experimental_mode = bool(sm['selfdriveState'].experimentalMode)
    self.mode = 'blended' if experimental_mode else 'acc'
    self.mpc.mode = 'acc'
    if not self.mlsim:
      self.mpc.mode = self.mode

    if len(sm['carControl'].orientationNED) == 3:
      accel_coast = get_coast_accel(sm['carControl'].orientationNED[1])
    else:
      accel_coast = ACCEL_MAX

    v_ego = get_planner_v_ego(self.CP, sm['carState'])
    scene_v_ego = float(sm['carState'].vEgo)
    v_cruise = sm['starpilotPlan'].vCruise
    if not np.isfinite(v_cruise):
      cloudlog.error(f"Longitudinal planner received non-finite vCruise={v_cruise}, falling back to v_ego={v_ego:.2f}")
      v_cruise = max(v_ego, 0.0)
    v_cruise_initialized = sm['carState'].vCruise != V_CRUISE_UNSET

    long_control_off = sm['controlsState'].longControlState == LongCtrlState.off
    force_slow_decel = sm['controlsState'].forceDecel

    # Reset current state when not engaged, or user is controlling the speed
    reset_state = long_control_off if self.CP.openpilotLongitudinalControl else not sm['selfdriveState'].enabled
    # PCM cruise speed may be updated a few cycles later, check if initialized
    reset_state = reset_state or not v_cruise_initialized

    # No change cost when user is controlling the speed, or when standstill
    prev_accel_constraint = not (reset_state or sm['carState'].standstill)

    if self.mpc.mode == 'acc':
      accel_limits = [sm['starpilotPlan'].minAcceleration, sm['starpilotPlan'].maxAcceleration]
      closing_lead = sm['radarState'].leadOne
      if closing_lead.status and (closing_lead.vRel < LEAD_CLOSING_FLOOR_VREL or
                                  closing_lead.aLeadK < LEAD_CLOSING_FLOOR_ALEAD):
        accel_limits[0] = min(accel_limits[0], A_CRUISE_MIN)
      steer_angle_without_offset = sm['carState'].steeringAngleDeg - sm['liveParameters'].angleOffsetDeg
      accel_limits_turns = limit_accel_in_turns(v_ego, steer_angle_without_offset, accel_limits, self.CP)
      accel_limits_turns[0] = max(get_vehicle_min_accel(self.CP, v_ego), accel_limits_turns[0])
    else:
      accel_limits = [ACCEL_MIN, ACCEL_MAX]
      accel_limits_turns = [ACCEL_MIN, ACCEL_MAX]

    if reset_state:
      self.v_desired_filter.x = v_ego
      # Clip aEgo to cruise limits to prevent large accelerations when becoming active
      self.a_desired = np.clip(sm['carState'].aEgo, accel_limits[0], accel_limits[1])
      self.model_allow_throttle = True
      self.model_allow_throttle_transition_t = 0.0

    # Prevent divergence, smooth in current v_ego
    self.v_desired_filter.x = max(0.0, self.v_desired_filter.update(v_ego))
    # Compute model v_ego error
    self.v_model_error = self.get_model_speed_error(sm['modelV2'], v_ego)
    x, v, a, j, throttle_prob = self.parse_model(sm['modelV2'], self.v_model_error, v_ego, starpilot_toggles)
    if bool(sm['carState'].standstill):
      self.model_launch_armed = True
      self.model_launch_stop_seen |= bool(
        sm['modelV2'].action.shouldStop or
        getattr(sm['starpilotPlan'], 'redLight', False) or
        getattr(sm['starpilotPlan'], 'forcingStop', False)
      )
    elif scene_v_ego > MODEL_LAUNCH_DISARM_SPEED:
      self.model_launch_armed = False
      self.model_launch_stop_seen = False
    model_launch_v = np.array(v, copy=True)
    model_launch_a = np.array(a, copy=True)
    # Don't clip at low speeds since throttle_prob doesn't account for creep. Raw
    # gasPressProb can cross both hysteresis thresholds for only a few model frames,
    # so confirm transitions before changing the physical coast cap.
    if v_ego <= MIN_ALLOW_THROTTLE_SPEED:
      self.model_allow_throttle = True
      self.model_allow_throttle_transition_t = 0.0
    else:
      transition_requested = (
        throttle_prob <= ALLOW_THROTTLE_DISABLE_THRESHOLD if self.model_allow_throttle
        else throttle_prob > ALLOW_THROTTLE_ENABLE_THRESHOLD
      )
      if transition_requested:
        self.model_allow_throttle_transition_t += self.dt
        if self.model_allow_throttle_transition_t + 1e-6 >= ALLOW_THROTTLE_TRANSITION_CONFIRM_TIME:
          self.model_allow_throttle = not self.model_allow_throttle
          self.model_allow_throttle_transition_t = 0.0
      else:
        self.model_allow_throttle_transition_t = 0.0
    self.allow_throttle = self.model_allow_throttle and not sm['starpilotPlan'].disableThrottle

    if not self.allow_throttle:
      clipped_accel_coast = max(accel_coast, accel_limits_turns[0])
      # Hold the output cap to the physical coasting limit until throttle is
      # allowed again. Relaxing back toward positive accel while the gate is
      # still closed can stall downhill coastdown well above the target speed.
      accel_limits_turns[1] = min(accel_limits_turns[1], clipped_accel_coast)
    no_throttle_output_max = accel_limits_turns[1]

    if force_slow_decel:
      v_cruise = 0.0
    # clip limits, cannot init MPC outside of bounds
    accel_limits_turns[0] = min(accel_limits_turns[0], self.a_desired + 0.05)
    accel_limits_turns[1] = max(accel_limits_turns[1], self.a_desired - 0.05)

    tracking_lead = bool(sm['starpilotPlan'].trackingLead)
    self.lead_one = sm['radarState'].leadOne
    self.lead_two = sm['radarState'].leadTwo
    raw_close_lead_control = any(self.raw_close_lead_needs_control(lead, scene_v_ego) for lead in (self.lead_one, self.lead_two))
    early_truck_follow = (
      not experimental_mode and
      any(is_gm_silverado_early_follow_lead(self.CP, lead, scene_v_ego) for lead in (self.lead_one, self.lead_two))
    )
    rav4_radar_follow = (
      not experimental_mode and
      any(is_toyota_rav4_tss2_radar_follow_lead(self.CP, lead, scene_v_ego)
          for lead in (self.lead_one, self.lead_two))
    )
    lightning_stopped_radar_follow = (
      experimental_mode and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      not bool(getattr(sm['starpilotPlan'], 'stopSignConfirmed', False)) and
      any(is_ford_f150_lightning_stopped_radar_follow_lead(self.CP, lead, scene_v_ego)
          for lead in (self.lead_one, self.lead_two))
    )
    # StarPilot trackingLead is debounce/model-length based. Keep a raw close-lead
    # safety path so ACC/chill does not ignore a visible lead during that debounce.
    lead_control_active = (
      tracking_lead or raw_close_lead_control or early_truck_follow or rav4_radar_follow or
      lightning_stopped_radar_follow
    )
    self.stopped_radar_lead_hold_active = self.update_stopped_radar_lead_hold(self.lead_one, scene_v_ego, lead_control_active)
    lead_control_active = lead_control_active or self.stopped_radar_lead_hold_active
    lead_one_active = bool(self.lead_one.status and lead_control_active)
    effective_t_follow = self.get_dynamic_t_follow(sm['starpilotPlan'].tFollow, self.lead_one if lead_one_active else None, v_ego)

    if self.is_preap and self.nap_adaptive_accel and lead_one_active:
      follow_limit = get_preap_follow_limit(v_ego)
      if follow_limit is not None:
        safe_dist = get_safe_obstacle_distance(v_ego, effective_t_follow)
        lead_dist_ratio = float(self.lead_one.dRel) / max(safe_dist, 1.0)
        cap_strength = float(np.clip(1.0 - (lead_dist_ratio - 1.2) / 0.3, 0.0, 1.0))
        if cap_strength > 0.0:
          accel_limits_turns[1] = min(
            accel_limits_turns[1],
            accel_limits_turns[1] * (1.0 - cap_strength) + follow_limit * cap_strength,
          )

    lead_dist = self.lead_one.dRel if lead_one_active else 50.0

    # Smooth lead distance (EMA) to avoid chatter in thresholds
    alpha = max(0.02, min(0.15, 0.05 + 0.002 * v_ego))
    if self.lead_dist_f is None:
      self.lead_dist_f = float(lead_dist)
    else:
      self.lead_dist_f += alpha * (float(lead_dist) - self.lead_dist_f)

    # Lead stability estimation and recent-brake timer
    now_t = time.monotonic()
    self.update_experimental_release_accel_state(experimental_mode, now_t, scene_v_ego)
    # relative speed (ego - lead) positive when closing
    v_rel = (v_ego - self.lead_one.vLead) if lead_one_active else 0.0
    if self.prev_lead_dist is None:
      d_rel_dot = 0.0
    else:
      d_rel_dot = (lead_dist - self.prev_lead_dist) / max(self.dt, 1e-3)
    self.prev_lead_dist = lead_dist
    
    # Calculate scene uncertainty from model desire prediction entropy and disengage predictions
    uncertainty = 0.0
    if hasattr(sm['modelV2'], 'meta'):
      # Desire prediction entropy (maneuver uncertainty), normalized to [0, 1]
      desire_entropy = 0.0
      if hasattr(sm['modelV2'].meta, 'desirePrediction'):
        desire_probs = sm['modelV2'].meta.desirePrediction
        if len(desire_probs) > 1:
          probs = np.asarray(desire_probs, dtype=float)
          total = float(np.sum(probs))
          if total > 1e-6:
            p = probs / total
            entropy = -np.sum(p * np.log(p + 1e-10))
            max_entropy = np.log(len(p))
            desire_entropy = float(entropy / max(max_entropy, 1e-6))  # normalized entropy in [0,1]
          else:
            desire_entropy = 0.0  # guard against all-zero vector

      # Disengage prediction risk (intervention likelihood)
      disengage_risk = 0.0
      raw_brake_max = -1.0
      lam = -1.0
      if hasattr(sm['modelV2'].meta, 'disengagePredictions'):
        # Use brake press probabilities as primary risk indicator
        brake_probs = sm['modelV2'].meta.disengagePredictions.brakePressProbs
        if len(brake_probs) > 0:
          # Exponentially decayed max over the full horizon
          probs = np.asarray(brake_probs, dtype=float)
          # Clip tiny brake blips so they don't inflate uncertainty
          if float(np.max(probs)) < 0.015:
            probs = probs * 0.5
          raw_brake_max = float(np.max(probs))
          # Time vector assuming model horizon step = DT_MDL
          t = np.arange(len(probs), dtype=float) * DT_MDL
          lam = 0.6  # decay rate per second (tunable: 0.5–0.9 typical)
          weights = np.exp(-lam * t)
          disengage_risk = float(np.max(probs * weights))
      # Combined uncertainty metric (range roughly 0..2), with dual-track filtering
      raw_uncertainty = desire_entropy + disengage_risk

    # Remember time of last non-trivial model brake risk
    if locals().get('raw_brake_max', -1) > 0.02:
      self.last_big_brake_t = now_t

    # Stable lead heuristic (short window, cheap to compute)
    recently_braked = (now_t - self.last_big_brake_t) < 0.7
    self.stable_lead = (
      lead_one_active and
      abs(v_rel) < 0.5 and
      abs(d_rel_dot) < 0.5 and
      not recently_braked
    )

    # Update filters
    self.uncert_slow.update(raw_uncertainty)
    self.uncert_fast.update(raw_uncertainty)
    # Use a more permissive track for accel decisions
    uncertainty = self.uncert_slow.x
    uncertainty_accel = min(self.uncert_slow.x, self.uncert_fast.x)

    # --- Slope-based panic bypass ---
    if self._uncert_last_t is None:
      uncert_slope = 0.0
    else:
      dt_u = max(1e-3, now_t - self._uncert_last_t)
      uncert_slope = (uncertainty - self._uncert_last) / dt_u
    self._uncert_last = uncertainty
    self._uncert_last_t = now_t

    panic_close_window = False
    closing_fast = False
    desired_gap = None
    closing_speed = 0.0
    if lead_one_active:
      desired_gap = float(desired_follow_distance(v_ego, self.lead_one.vLead, effective_t_follow))
      scene_desired_gap = float(desired_follow_distance(scene_v_ego, self.lead_one.vLead, effective_t_follow))
      close_gap_window = max(UNCERT_PANIC_MAX_GAP_BUFFER_MIN,
                             UNCERT_PANIC_MAX_GAP_BUFFER_GAIN * float(v_ego))
      panic_close_window = float(self.lead_one.dRel) <= scene_desired_gap + close_gap_window
      closing_speed = max(0.0, scene_v_ego - self.lead_one.vLead)
      closing_fast = closing_speed >= max(
        UNCERT_PANIC_MIN_CLOSING_SPEED,
        UNCERT_PANIC_MIN_CLOSING_SPEED_GAIN * float(scene_v_ego),
      )

    # Only bypass lead smoothing when we're closing meaningfully and already
    # near the follow window. Far or nearly pace-matched leads should stay on
    # the smoothed path so the planner doesn't flip-flop between accel and brake.
    panic_bypass = panic_close_window and closing_fast and (
      uncert_slope > UNCERT_SLOPE_TRIG or uncertainty >= UNCERT_MAG_TRIG
    )
    # Duplicate vision tracks can share the same noisy velocity spike. Keep the
    # comfort path unless distance, TTC, or lead braking makes the scene urgent.
    nonurgent_duplicate_vision_follow = is_nonurgent_duplicate_vision_follow(
      self.lead_one, self.lead_two, scene_v_ego, effective_t_follow, self.mpc,
    )
    if panic_bypass and nonurgent_duplicate_vision_follow:
      panic_bypass = False

    steady_follow_filter_floor = 0.0
    if lead_one_active and desired_gap is not None and not panic_bypass:
      lead_brake = max(0.0, -float(getattr(self.lead_one, "aLeadK", 0.0)))
      lead_radar = bool(getattr(self.lead_one, "radar", False))
      lead_prob = float(getattr(self.lead_one, "modelProb", 1.0 if lead_radar else 0.0))
      actual_headway = float(self.lead_one.dRel) / max(scene_v_ego, 1e-3)
      matched_follow_window = (
        is_radarless_matched_follow_window(
          scene_v_ego,
          self.lead_one.dRel,
          self.lead_one.vLead,
          effective_t_follow,
          radar=lead_radar,
          lead_brake=lead_brake,
          lead_prob=lead_prob,
        ) or (
          lead_radar and
          scene_v_ego >= STEADY_FOLLOW_SMOOTHING_MIN_SPEED and
          STEADY_FOLLOW_SMOOTHING_MIN_CLOSING_SPEED <= closing_speed <= STEADY_FOLLOW_SMOOTHING_MAX_CLOSING_SPEED and
          actual_headway >= max(STEADY_FOLLOW_SMOOTHING_MIN_HEADWAY,
                                effective_t_follow - STEADY_FOLLOW_SMOOTHING_HEADWAY_BELOW_TARGET) and
          actual_headway <= effective_t_follow + STEADY_FOLLOW_SMOOTHING_HEADWAY_ABOVE_TARGET and
          lead_brake <= STEADY_FOLLOW_SMOOTHING_MAX_LEAD_BRAKE
        )
      )
      if matched_follow_window:
        steady_follow_filter_floor = STEADY_FOLLOW_SMOOTHING_FILTER_FACTOR_FLOOR

    if panic_bypass:
      if now_t - self._panic_bypass_log_t > 5.0:
        self._panic_bypass_log_t = now_t
        try:
          cloudlog.warning(
            "LON_SLOPE close bypass: "
            f"slope={uncert_slope:.3f}/s uncertainty={uncertainty:.3f} "
            f"v_ego={v_ego:.2f} v_rel={(v_ego - self.lead_one.vLead) if lead_one_active else 0.0:.2f} "
            f"lead_dist={self.lead_dist_f if self.lead_dist_f is not None else -1:.2f}"
          )
        except Exception:
          pass

    personality = get_longitudinal_personality(sm)

    self.mpc.set_weights(sm['starpilotPlan'].accelerationJerk,
                         sm['starpilotPlan'].dangerJerk,
                         sm['starpilotPlan'].speedJerk,
                         prev_accel_constraint,
                         personality=personality,
                         v_ego=v_ego,
                         lead_dist=self.lead_dist_f if lead_one_active and self.lead_dist_f is not None else 50.0,
                         uncertainty=uncertainty,
                         panic_bypass=panic_bypass,
                         filter_time_factor_floor=steady_follow_filter_floor)
    self.mpc.set_accel_limits(accel_limits_turns[0], accel_limits_turns[1])
    self.mpc.set_cur_state(self.v_desired_filter.x, self.a_desired)
    # After deciding the MPC mode via get_mpc_mode(), ensure MPC uses that mode when not mlsim
    dec_mpc_mode = self.get_mpc_mode()
    if not self.mlsim:
      self.mpc.mode = dec_mpc_mode
    # Hand the forced stop to the solver as a position. The obstacle sits STOP_DISTANCE
    # beyond the line because the safe-distance term already includes it — placing it on
    # the line parks us short. Below that the existing v_cruise=0 path finishes the stop,
    # since forcingStopLength is decaying to zero and the obstacle would land behind us.
    force_stop_x = None
    force_stop_handoff_m = get_force_stop_handoff_distance(self.CP.carFingerprint)
    if sm['starpilotPlan'].forcingStop and sm['starpilotPlan'].forcingStopLength > force_stop_handoff_m:
      stop_length = float(sm['starpilotPlan'].forcingStopLength)
    else:
      # pre-commit the envelope is only a speed ceiling, which the solver tracks with a lag;
      # getattr so a stale cereal build degrades to the old behaviour instead of raising
      stop_length = float(getattr(sm['starpilotPlan'], 'approachStopLength', 0.0))
    if stop_length > force_stop_handoff_m:
      # ForceStopDistanceOffset shifts the perceived line for the v_cruise ceiling, so it has
      # to shift the obstacle too or the slider barely moves anything now that stop_x leads.
      offset_ft = max(OFFSET_FT_MIN, min(OFFSET_FT_MAX, int(getattr(starpilot_toggles, 'force_stop_distance_offset', 0) or 0)))
      force_stop_x = (
        stop_length * FORCE_STOP_OBSTACLE_TRIM + offset_ft * FT_TO_M + STOP_DISTANCE +
        get_force_stop_distance_bias(self.CP.carFingerprint)
      )

    stopped_lead_obstacle_bias = (0.0, 0.0)
    if (
      self.mode == 'acc' and
      not bool(getattr(sm['modelV2'].action, 'shouldStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['carState'], 'standstill', False))
    ):
      stopped_lead_obstacle_bias = tuple(
        max(
          get_toyota_prius_stopped_lead_obstacle_bias(self.CP, lead, scene_v_ego),
          get_honda_crv_5g_stopped_lead_obstacle_bias(self.CP, lead, scene_v_ego),
        )
        for lead in (self.lead_one, self.lead_two)
      )

    self.mpc.update(sm['radarState'], v_cruise, x, v, a, j,
                    sm['starpilotPlan'].dangerFactor, effective_t_follow,
                    personality=personality, tracking_lead=lead_control_active,
                    optional_far_lead_comfort=True,
                    smooth_duplicate_vision=nonurgent_duplicate_vision_follow and not panic_bypass,
                    stop_x=force_stop_x,
                    silverado_early_follow=early_truck_follow,
                    modelV2=sm['modelV2'],  # HumanFollowing, always on (STATUS 118)
                    lead_obstacle_bias=stopped_lead_obstacle_bias,
                    tracked_lead_catchup_headway_margins=self.tracked_lead_catchup_headway_margins,
                    tracked_lead_catchup_bias_gain=self.tracked_lead_catchup_bias_gain,
                    tracked_lead_catchup_bias_cap=self.tracked_lead_catchup_bias_cap,
                    tracked_lead_catchup_speed_range=self.tracked_lead_catchup_speed_range,
                    tracked_lead_catchup_fade_margins=self.tracked_lead_catchup_fade_margins,
                    tracked_lead_catchup_cruise_error_full=self.tracked_lead_catchup_cruise_error_full,
                    lead_detection_probability=float(getattr(starpilot_toggles, "lead_detection_probability", 0.35)))

    self.a_desired_trajectory_full = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.a_solution)
    self.v_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.v_solution)
    self.a_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.a_solution)
    self.j_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC[:-1], self.mpc.j_solution)

    # TODO counter is only needed because radar is glitchy, remove once radar is gone
    self.fcw = should_publish_planner_fcw(self.mpc.crash_cnt, sm['carState'], sm['radarState'])
    if self.fcw:
      cloudlog.info("FCW triggered")

    # Safety checks for rubber-banding mitigation
    max_jerk = np.max(np.abs(self.mpc.j_solution))
    max_accel_change = np.max(np.abs(np.diff(self.mpc.a_solution)))
    if (max_jerk > 5.0 or max_accel_change > 2.0) and now_t - self._safety_warning_log_t >= PLANNER_SAFETY_WARNING_INTERVAL:
      cloudlog.warning(
        f"Longitudinal planner output discontinuity: jerk={max_jerk:.2f} m/s^3, "
        f"accel_change={max_accel_change:.2f} m/s^2"
      )
      self._safety_warning_log_t = now_t

    # Interpolate 0.05 seconds and save as starting point for next iteration
    a_prev = self.a_desired
    self.a_desired = float(np.interp(self.dt, CONTROL_N_T_IDX, self.a_desired_trajectory))
    self.v_desired_filter.x = self.v_desired_filter.x + self.dt * (self.a_desired + a_prev) / 2.0

    # Anticipatory pre-brake to avoid "coming in hot" when closing on a lead
    if lead_one_active:
      rel_v = max(0.0, v_ego - self.lead_one.vLead)
      # dynamic time headway adds a small buffer when uncertainty is elevated
      base_th = get_follow_prebrake_min_headway(self.CP, effective_t_follow)
      th = base_th + 0.6 * max(0.0, uncertainty - 0.42)
      desired_gap = th * v_ego
      if (self.lead_dist_f is not None and self.lead_dist_f < desired_gap and rel_v > 0.5):
        k_rel, k_unc = 0.04, 0.20
        pre_brake = k_rel * rel_v + k_unc * max(0.0, uncertainty - 0.42)
        pre_brake = min(pre_brake, 0.06)
        self.a_desired = float(self.a_desired - pre_brake)

    # Small deadzone around zero accel to kill micro-dithers
    if -0.05 < self.a_desired < 0.05:
      self.a_desired = 0.0

    classic_model = bool(getattr(starpilot_toggles, "classic_model", False))
    tinygrad_model = bool(getattr(starpilot_toggles, "tinygrad_model", False))
    experimental_mlsim = bool(tinygrad_model and self.mlsim and self.mode != 'acc')
    action_t = self.longitudinal_actuator_delay + DT_MDL
    short_action_t = self._short_action_t_active()
    plan_action_t = get_planner_action_t(self.longitudinal_actuator_delay, short_action_t)
    prev_output_a_target = float(self.output_a_target)
    model_launch_accel = None
    if self.model_launch_armed and not bool(sm['modelV2'].action.shouldStop):
      model_launch_accel = self.get_model_launch_accel(model_launch_v, model_launch_a, action_t, scene_v_ego)

    output_a_target_mpc = None
    if self.mode == 'acc':
      self.exp_lead_departure_weight = 0.0
      self.exp_lead_departure_lift = 0.0
    if classic_model:
      output_a_target, output_should_stop = get_accel_from_plan_classic(
        self.CP, self.v_desired_trajectory, self.a_desired_trajectory, starpilot_toggles.vEgoStopping,
        actuator_delay=(plan_action_t - DT_MDL) if short_action_t else self.longitudinal_actuator_delay)
    elif tinygrad_model:
      output_a_target_mpc, output_should_stop_mpc = get_accel_from_plan(
        self.v_desired_trajectory, self.a_desired_trajectory,
        action_t=plan_action_t, vEgoStopping=starpilot_toggles.vEgoStopping)
      output_a_target_e2e = sm['modelV2'].action.desiredAcceleration
      accel_boost_on = bool(getattr(starpilot_toggles, "gas_override_boost", True))
      if accel_boost_on:
        # Port of commaai/openpilot PR 39015: boost the e2e target ahead of arbitration.
        # Upstream compares against min(mpc, a_cruise). a_cruise here is the accel that reaches v_cruise
        # within the actuator delay, the same formula as the downstream lead cruise cap.
        a_cruise = max(0.0, (v_cruise - scene_v_ego + 0.01) / max(action_t, self.dt))
        model_limited = experimental_mode and self.accel_boost.apply(output_a_target_e2e) < min(output_a_target_mpc, a_cruise)
        self.accel_boost.update(bool(sm['selfdriveState'].enabled), bool(getattr(sm['carState'], 'gasPressed', False)),
                                scene_v_ego, model_limited)
        output_a_target_e2e = self.accel_boost.apply(output_a_target_e2e)
      else:
        self.accel_boost.update(False, False, scene_v_ego, False)
      output_should_stop_e2e = sm['modelV2'].action.shouldStop

      exp_active = not (self.mode == 'acc' or self.generation == 'v9')
      if reset_state or sm['carState'].standstill:
        self.exp_mode_blend_weight = 1.0 if exp_active else 0.0
      else:
        self.exp_mode_blend_weight = exp_mode_blend_weight(self.exp_mode_blend_weight, exp_active, self.dt)
      output_a_target = exp_mode_blend_target(output_a_target_mpc, output_a_target_e2e, self.exp_mode_blend_weight)
      if not exp_active:
        output_should_stop = output_should_stop_mpc
      else:
        output_should_stop = output_should_stop_e2e or output_should_stop_mpc
        cem_following_lead = self.is_cem_following_lead(
          tracking_lead,
          self.lead_one.dRel,
          sm['starpilotPlan'].tFollow,
          scene_v_ego,
        )
        speed_handoff = self.get_experimental_speed_handoff_weight(
          scene_v_ego,
          experimental_mode,
          cem_following_lead,
          starpilot_toggles,
          bool(
            output_should_stop_e2e or
            getattr(sm['starpilotPlan'], 'forcingStop', False) or
            getattr(sm['starpilotPlan'], 'redLight', False)
          ),
        )
        output_a_target = self.apply_experimental_speed_handoff(
          output_a_target, output_a_target_mpc, output_a_target_e2e, speed_handoff,
        )
        hold_experimental = bool(
          output_should_stop_e2e or
          getattr(sm['starpilotPlan'], 'forcingStop', False) or
          getattr(sm['starpilotPlan'], 'redLight', False)
        )
        if accel_boost_on:
          output_a_target = self.update_exp_lead_departure(
            output_a_target, output_a_target_e2e, output_a_target_mpc, scene_v_ego,
            sm['starpilotPlan'].tFollow, hold_experimental,
          )
        else:
          self.exp_lead_departure_weight = 0.0
          self.exp_lead_departure_lift = 0.0
    else:
      output_a_target, output_should_stop = get_accel_from_plan(
        self.v_desired_trajectory, self.a_desired_trajectory,
        action_t=plan_action_t, vEgoStopping=starpilot_toggles.vEgoStopping)

    comfort_output_accel_min = get_vehicle_min_accel(self.CP, v_ego) if experimental_mlsim else accel_limits_turns[0]
    vision_cap_accel_min = min(comfort_output_accel_min, get_vehicle_min_accel(self.CP, v_ego))
    output_accel_min = comfort_output_accel_min
    model_desired_accel = float(sm['modelV2'].action.desiredAcceleration)

    raw_approach_lift_cap = None
    if not tracking_lead:
      approach_lift_caps = [
        cap for cap in (
          self.get_vision_untracked_approach_lift_cap(self.lead_one, v_ego, effective_t_follow),
          self.get_vision_untracked_approach_lift_cap(self.lead_two, v_ego, effective_t_follow),
        ) if cap is not None
      ]
      if approach_lift_caps:
        raw_approach_lift_cap = min(approach_lift_caps)

      if not experimental_mode:
        # Apply the RAV4's mild early-lead response before ordinary lead tracking
        # is admitted. This only removes throttle while a centered, confident
        # lead is already braking; the normal safety path remains authoritative.
        rav4_pretracking_caps = [
          cap for cap in (
            get_toyota_rav4_tss2_early_lead_cap(
              self.CP, self.lead_one, v_ego, vision_cap_accel_min,
            ),
            get_toyota_rav4_tss2_early_lead_cap(
              self.CP, self.lead_two, v_ego, vision_cap_accel_min,
            ),
          ) if cap is not None
        ]
        if rav4_pretracking_caps:
          rav4_pretracking_cap = min(rav4_pretracking_caps)
          self.a_desired = min(self.a_desired, rav4_pretracking_cap)
          output_a_target = min(output_a_target, rav4_pretracking_cap)

        early_radar_caps = [
          cap for cap in (
            get_honda_crv_5g_early_radar_follow_cap(
              self.CP, self.lead_one, v_ego, vision_cap_accel_min,
            ),
            get_honda_crv_5g_early_radar_follow_cap(
              self.CP, self.lead_two, v_ego, vision_cap_accel_min,
            ),
          ) if cap is not None
        ]
        if early_radar_caps:
          early_radar_cap = min(early_radar_caps)
          self.a_desired = min(self.a_desired, early_radar_cap)
          output_a_target = min(output_a_target, early_radar_cap)

      pretracking_vision_caps = []
      for lead in (self.lead_one, self.lead_two):
        if lead.status and not bool(getattr(lead, "radar", False)):
          pretracking_cap = self.get_vision_untracked_slow_lead_cap(lead, v_ego, vision_cap_accel_min)
          if pretracking_cap is not None:
            pretracking_vision_caps.append((pretracking_cap, lead))

      if pretracking_vision_caps:
        pretracking_vision_cap, pretracking_vision_lead = min(pretracking_vision_caps, key=lambda cap_and_lead: cap_and_lead[0])
        lead_brake = max(0.0, -float(getattr(pretracking_vision_lead, "aLeadK", 0.0)))
        immediate_pretracking_cap = (
          pretracking_vision_cap <= -VISION_UNTRACKED_SLOW_LEAD_IMMEDIATE_DECEL or
          float(getattr(pretracking_vision_lead, "dRel", float("inf"))) <= VISION_UNTRACKED_SLOW_LEAD_IMMEDIATE_DISTANCE or
          lead_brake >= VISION_UNTRACKED_SLOW_LEAD_IMMEDIATE_LEAD_BRAKE or
          float(getattr(pretracking_vision_lead, "vLead", float("inf"))) <= VISION_UNTRACKED_SLOW_LEAD_RELAXED_MAX_LEAD_SPEED
        )

        if immediate_pretracking_cap:
          self.untracked_slow_lead_confirm_t = VISION_UNTRACKED_SLOW_LEAD_CONFIRM_TIME
        else:
          self.untracked_slow_lead_confirm_t = min(
            self.untracked_slow_lead_confirm_t + self.dt,
            VISION_UNTRACKED_SLOW_LEAD_CONFIRM_TIME,
          )

        if self.untracked_slow_lead_confirm_t >= VISION_UNTRACKED_SLOW_LEAD_CONFIRM_TIME:
          self.a_desired = min(self.a_desired, pretracking_vision_cap)
          output_a_target = min(output_a_target, pretracking_vision_cap)
      else:
        self.untracked_slow_lead_confirm_t = 0.0
    else:
      self.untracked_slow_lead_confirm_t = 0.0

    approach_lift_cap = self.update_vision_untracked_approach_lift_cap(
      raw_approach_lift_cap,
      output_a_target,
      prev_output_a_target,
      now_t,
      not tracking_lead,
    )
    if approach_lift_cap is not None:
      self.a_desired = min(self.a_desired, approach_lift_cap)
      output_a_target = min(output_a_target, approach_lift_cap)

    close_lead_caps = []
    rav4_early_lead_caps = []
    vision_low_speed_stop_active = False
    vision_brake_cap_active = False
    self.close_lead_brake_cap_value = 0.0
    # Worst case over BOTH leads: the MPC may be constrained by lead two, and publishing only
    # lead one's value silently described the wrong object.
    self.lead_geometry_required_accel = max(
      self.get_lead_geometry_required_accel(self.lead_one, v_ego),
      self.get_lead_geometry_required_accel(self.lead_two, v_ego),
    )
    fast_closing_cap = None
    if not lead_control_active or not any(
        lead.status and bool(getattr(lead, "radar", False)) and int(getattr(lead, "radarTrackId", -1)) == self.fast_closing_lead_track
        for lead in (self.lead_one, self.lead_two)):
      self.fast_closing_lead_track = None
    self.fast_closing_tick += 1
    self.fast_closing_vision_seen = {k: t for k, t in self.fast_closing_vision_seen.items()
                                     if self.fast_closing_tick - t <= FAST_CLOSING_LEAD_VISION_MEMORY_TICKS}
    exp_close_lead_cap = None
    exp_close_lead_floor = min(self.exp_close_lead_floor, accel_limits_turns[0])
    if lead_control_active:
      for lead, lead_source in ((self.lead_one, 'lead0'), (self.lead_two, 'lead1')):
        rav4_early_lead_cap = get_toyota_rav4_tss2_early_lead_cap(
          self.CP, lead, v_ego, output_accel_min,
        )
        if rav4_early_lead_cap is not None:
          rav4_early_lead_caps.append(rav4_early_lead_cap)
        fast_closing = self.fast_closing_lead_passes_floor(lead, lead_source, v_ego, sm['modelV2'])
        cap = self.get_close_lead_brake_cap(lead, v_ego, fast_closing_accel_min(vision_cap_accel_min) if fast_closing
                                           else output_accel_min)
        if cap is not None and experimental_mlsim and not fast_closing:
          # D-073: the part of the Exp cap that comes from the lead's aLeadK may only go deeper than chill's
          # floor at EXP_CLOSE_LEAD_FLOOR_RATE; what the closing speed alone demands applies at once.
          exp_close_lead_cap = cap if exp_close_lead_cap is None else min(exp_close_lead_cap, cap)
          closing_cap = self.get_close_lead_brake_cap(lead, v_ego, output_accel_min, count_lead_brake=False)
          cap = max(cap, exp_close_lead_floor if closing_cap is None else min(exp_close_lead_floor, closing_cap))
        if cap is not None:
          close_lead_caps.append(cap)
          self.close_lead_brake_cap_value = min(self.close_lead_brake_cap_value, cap)
          if fast_closing:
            fast_closing_cap = cap if fast_closing_cap is None else min(fast_closing_cap, cap)
        cap = get_honda_crv_5g_low_speed_stopped_lead_cap(
          self.CP, lead, v_ego, vision_cap_accel_min,
        )
        if cap is not None:
          close_lead_caps.append(cap)
        slow_stop_cap = self.get_vision_slow_stopped_lead_cap(lead, v_ego, vision_cap_accel_min, effective_t_follow)
        if slow_stop_cap is not None:
          close_lead_caps.append(slow_stop_cap)
          vision_brake_cap_active = True
        low_speed_stop_cap, low_speed_stop_active = self.get_vision_low_speed_stop_buffer_cap(lead, v_ego, vision_cap_accel_min)
        if low_speed_stop_cap is not None:
          close_lead_caps.append(low_speed_stop_cap)
          vision_brake_cap_active = True
        vision_low_speed_stop_active |= low_speed_stop_active
    if exp_close_lead_cap is not None and exp_close_lead_cap < exp_close_lead_floor:
      self.exp_close_lead_floor = max(output_accel_min, exp_close_lead_floor - EXP_CLOSE_LEAD_FLOOR_RATE * self.dt)
    else:
      self.exp_close_lead_floor = min(0.0, self.exp_close_lead_floor + EXP_CLOSE_LEAD_FLOOR_RELAX * self.dt)
    if fast_closing_cap is not None:
      # The floor opens to the fast-closing cap's own value only (FAST_CLOSING_LEAD_*).
      output_accel_min = min(output_accel_min, fast_closing_cap)
    if close_lead_caps:
      close_lead_brake_cap = min(close_lead_caps)
      self.a_desired = min(self.a_desired, close_lead_brake_cap)
      output_a_target = min(output_a_target, close_lead_brake_cap)

    standstill_nudge_gap = STOP_DISTANCE - 0.5
    moving_leads = [lead for lead in (self.lead_one, self.lead_two)
                    if lead.status and
                    lead.vLead > STANDSTILL_LEAD_NUDGE_MIN_SPEED and lead.dRel >= standstill_nudge_gap]
    accelerating_nudge_lead = any(
      lead.status and
      float(getattr(lead, "vLead", 0.0)) > STANDSTILL_LEAD_NUDGE_MIN_SPEED and
      float(getattr(lead, "aLeadK", 0.0)) >= STANDSTILL_LEAD_NUDGE_MIN_LEAD_ACCEL and
      float(getattr(lead, "dRel", 0.0)) >= standstill_nudge_gap
      for lead in (self.lead_one, self.lead_two)
    )
    confident_depart_detected = any(self.is_confident_lead_depart(lead, float(sm['carState'].vEgo))
                                    for lead in (self.lead_one, self.lead_two))
    lead_depart_ready = any(
      lead.status and
      lead.vLead >= STANDSTILL_LEAD_DEPART_MIN_LEAD_SPEED and
      lead.dRel >= standstill_nudge_gap + STANDSTILL_LEAD_DEPART_MIN_GAP_MARGIN
      for lead in (self.lead_one, self.lead_two)
    )
    depart_safety_veto = (not bool(getattr(starpilot_toggles, "radar_takeoffs", False))
                          and self.has_offcenter_radar_depart_conflict(sm))
    safe_depart_release_hold_lead = self.get_safe_depart_release_hold_lead(float(sm['carState'].vEgo))
    depart_release_hold_context = bool(
      lead_control_active and
      float(sm['carState'].vEgo) <= STANDSTILL_LEAD_DEPART_MAX_EGO_SPEED and
      not depart_safety_veto and
      not bool(getattr(sm['carState'], 'brakePressed', False)) and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      safe_depart_release_hold_lead is not None
    )
    if depart_release_hold_context:
      self.lead_depart_release_candidate_elapsed = min(
        LEAD_DEPART_RELEASE_HOLD_CONFIRM_TIME,
        self.lead_depart_release_candidate_elapsed + self.dt,
      )
    else:
      self.lead_depart_release_candidate_elapsed = 0.0
      self.lead_depart_release_pending = False
      self.lead_depart_release_hold_remaining = 0.0

    if self.lead_depart_release_hold_remaining > 0.0:
      self.lead_depart_release_hold_remaining = max(0.0, self.lead_depart_release_hold_remaining - self.dt)
    depart_release_hold_active = bool(depart_release_hold_context and self.lead_depart_release_hold_remaining > 0.0)
    if (
      lead_control_active and
      sm['carState'].standstill and
      not depart_safety_veto and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      confident_depart_detected
    ):
      self.confident_lead_depart_elapsed = min(
        LEAD_DEPART_CONFIDENT_CONFIRM_TIME,
        self.confident_lead_depart_elapsed + self.dt,
      )
    else:
      self.confident_lead_depart_elapsed = 0.0
    confident_depart_ready = (
      confident_depart_detected and
      self.confident_lead_depart_elapsed >= LEAD_DEPART_CONFIDENT_CONFIRM_TIME
    )
    slow_creep_depart_detected = any(
      self.is_slow_creep_lead_depart(lead, float(sm['carState'].vEgo), standstill_nudge_gap)
      for lead in (self.lead_one, self.lead_two)
    )
    if (
      lead_control_active and
      sm['carState'].standstill and
      not depart_safety_veto and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      slow_creep_depart_detected
    ):
      self.slow_creep_lead_depart_elapsed = min(
        STANDSTILL_LEAD_CREEP_RELEASE_CONFIRM_TIME,
        self.slow_creep_lead_depart_elapsed + self.dt,
      )
    else:
      self.slow_creep_lead_depart_elapsed = 0.0
    slow_creep_depart_ready = (
      slow_creep_depart_detected and
      self.slow_creep_lead_depart_elapsed >= STANDSTILL_LEAD_CREEP_RELEASE_CONFIRM_TIME
    )
    radar_gap_settle_active = False
    if allow_radar_standstill_gap_settle(self.CP) or allow_honda_crv_5g_vision_gap_settle(self.CP):
      radar_gap_settle_active = self.update_radar_standstill_gap_settle(
        sm,
        standstill_nudge_gap,
        allow_vision=allow_honda_crv_5g_vision_gap_settle(self.CP),
        max_extra_gap=get_standstill_gap_settle_max_extra_gap(self.CP),
      )
    else:
      self.radar_standstill_gap_settle_elapsed = 0.0
      self.radar_standstill_gap_settle_active = False

    standstill_stopped_lead_guard_cap = None
    standstill_guard_lead_present = any(bool(getattr(lead, "status", False)) for lead in (self.lead_one, self.lead_two))
    if standstill_guard_lead_present and (bool(sm['carState'].standstill) or float(sm['carState'].vEgo) <= STANDSTILL_STOPPED_LEAD_GUARD_MAX_EGO_SPEED):
      release_ready = bool(
        lead_depart_ready or confident_depart_ready or slow_creep_depart_ready or
        radar_gap_settle_active or depart_release_hold_active
      )
      standstill_stopped_lead_guard_caps = [
        cap for cap in (
          self.get_standstill_stopped_lead_guard_cap(
            self.lead_one,
            float(sm['carState'].vEgo),
            output_accel_min,
            standstill_nudge_gap,
            release_ready,
            confident_depart_ready,
          ),
          self.get_standstill_stopped_lead_guard_cap(
            self.lead_two,
            float(sm['carState'].vEgo),
            output_accel_min,
            standstill_nudge_gap,
            release_ready,
            confident_depart_ready,
          ),
        ) if cap is not None
      ]
      if standstill_stopped_lead_guard_caps:
        standstill_stopped_lead_guard_cap = min(standstill_stopped_lead_guard_caps)
        output_should_stop = True

    if lead_control_active and sm['carState'].standstill and moving_leads and not depart_safety_veto:
      output_a_target = max(output_a_target, STANDSTILL_LEAD_NUDGE_ACCEL)

    if (
      lead_control_active and
      sm['carState'].standstill and
      (confident_depart_ready or lead_depart_ready or slow_creep_depart_ready) and
      not depart_safety_veto and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      (confident_depart_ready or slow_creep_depart_ready or model_desired_accel >= STANDSTILL_LEAD_DEPART_MIN_MODEL_ACCEL)
    ):
      vision_low_speed_stop_active = False
      output_should_stop = False
      depart_min_accel = STANDSTILL_LEAD_DEPART_MIN_ACCEL
      if slow_creep_depart_ready and not (confident_depart_ready or lead_depart_ready):
        depart_min_accel = STANDSTILL_LEAD_CREEP_RELEASE_MIN_ACCEL
      output_a_target = max(output_a_target, depart_min_accel)
      self.post_departure_follow_settle_until = now_t + POST_DEPARTURE_FOLLOW_SETTLE_LATCH_TIME

    if depart_release_hold_context and bool(self.output_should_stop) and not bool(output_should_stop):
      self.lead_depart_release_pending = True
    if (
      depart_release_hold_context and
      self.lead_depart_release_pending and
      not bool(output_should_stop) and
      self.lead_depart_release_candidate_elapsed >= LEAD_DEPART_RELEASE_HOLD_CONFIRM_TIME
    ):
      self.lead_depart_release_hold_remaining = LEAD_DEPART_RELEASE_HOLD_TIME
      self.lead_depart_release_pending = False
      depart_release_hold_active = True
    elif bool(output_should_stop) and self.lead_depart_release_hold_remaining <= 0.0:
      self.lead_depart_release_pending = False

    if depart_release_hold_active:
      vision_low_speed_stop_active = False
      output_should_stop = False
      self.post_departure_follow_settle_until = now_t + POST_DEPARTURE_FOLLOW_SETTLE_LATCH_TIME

    if lead_control_active and lead_depart_ready and not depart_safety_veto and not output_should_stop and float(sm['carState'].vEgo) <= STANDSTILL_LEAD_DEPART_MAX_EGO_SPEED:
      output_a_target = max(output_a_target, STANDSTILL_LEAD_DEPART_MIN_ACCEL)
      self.post_departure_follow_settle_until = now_t + POST_DEPARTURE_FOLLOW_SETTLE_LATCH_TIME

    if radar_gap_settle_active:
      vision_low_speed_stop_active = False
      output_should_stop = False
      output_a_target = RADAR_STANDSTILL_GAP_SETTLE_ACCEL

    lead_present = any(bool(getattr(lead, "status", False)) for lead in (self.lead_one, self.lead_two))
    confirmed_lead_release = bool(confident_depart_ready or lead_depart_ready or slow_creep_depart_ready)
    model_launch_allowed = bool(
      model_launch_accel is not None and
      not output_should_stop and
      not vision_low_speed_stop_active and
      not bool(getattr(sm['carState'], 'brakePressed', False)) and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      not depart_safety_veto and
      (
        (lead_present and lead_control_active and confirmed_lead_release) or
        (not lead_present and (self.mode != 'acc' or self.model_launch_stop_seen))
      )
    )
    if model_launch_allowed:
      output_a_target = max(output_a_target, model_launch_accel)

    if depart_safety_veto or output_should_stop or bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) or bool(getattr(sm['starpilotPlan'], 'redLight', False)):
      self.lead_depart_accel_hold_until = 0.0
      self.lead_depart_accel_hold_floor = None

    lead_depart_accel_floor = None
    lead_depart_accel_floor_reused = False
    if lead_control_active and not output_should_stop and not depart_safety_veto:
      lead_depart_accel_floors = [
        floor for floor in (
          self.get_lead_depart_accel_floor(self.lead_one, scene_v_ego, model_desired_accel),
          self.get_lead_depart_accel_floor(self.lead_two, scene_v_ego, model_desired_accel),
        ) if floor is not None
      ]
      if lead_depart_accel_floors:
        lead_depart_accel_floor = max(lead_depart_accel_floors)
        self.lead_depart_accel_hold_floor = lead_depart_accel_floor
        if sm['carState'].standstill:
          self.lead_depart_accel_hold_until = now_t + LEAD_DEPART_ACCEL_HOLD_TIME
      elif self.lead_depart_accel_hold_floor is not None and now_t < self.lead_depart_accel_hold_until:
        reusable_hold_floors = [
          floor for floor in (
            self.get_reusable_lead_depart_accel_floor(self.lead_one, scene_v_ego, effective_t_follow),
            self.get_reusable_lead_depart_accel_floor(self.lead_two, scene_v_ego, effective_t_follow),
          ) if floor is not None
        ]
        if reusable_hold_floors:
          lead_depart_accel_floor = max(reusable_hold_floors)
          lead_depart_accel_floor_reused = True
        else:
          self.lead_depart_accel_hold_floor = None
      elif now_t >= self.lead_depart_accel_hold_until:
        self.lead_depart_accel_hold_floor = None

    lead_depart_accel_hold_active = (
      lead_depart_accel_floor is not None and
      now_t < self.lead_depart_accel_hold_until and
      float(sm['carState'].vEgo) <= LEAD_DEPART_ACCEL_HOLD_MAX_EGO_SPEED
    )

    low_speed_weak_lead_accel_cap = None
    if not output_should_stop:
      low_speed_weak_lead_accel_caps = [
        cap for cap in (
          self.get_low_speed_weak_lead_accel_cap(self.lead_one, scene_v_ego),
          self.get_low_speed_weak_lead_accel_cap(self.lead_two, scene_v_ego),
        ) if cap is not None
      ]
      if low_speed_weak_lead_accel_caps:
        low_speed_weak_lead_accel_cap = min(low_speed_weak_lead_accel_caps)

    close_stop_active = bool(output_should_stop or vision_low_speed_stop_active)

    close_stop_hold_cap = None
    if lead_control_active and close_stop_active:
      close_stop_hold_caps = [
        cap for cap in (
          self.get_vision_close_stop_hold_cap(self.lead_one, v_ego, output_accel_min, close_stop_active),
          self.get_vision_close_stop_hold_cap(self.lead_two, v_ego, output_accel_min, close_stop_active),
        ) if cap is not None
      ]
      if close_stop_hold_caps:
        close_stop_hold_cap = min(close_stop_hold_caps)

    close_release_hold_cap = None
    if lead_control_active and not close_stop_active:
      close_release_hold_caps = [
        cap for cap in (
          self.get_vision_close_release_hold_cap(self.lead_one, v_ego, vision_cap_accel_min, close_stop_active),
          self.get_vision_close_release_hold_cap(self.lead_two, v_ego, vision_cap_accel_min, close_stop_active),
        ) if cap is not None
      ]
      if close_release_hold_caps:
        close_release_hold_cap = min(close_release_hold_caps)

    close_settle_guard_active = bool(
      output_should_stop or
      vision_low_speed_stop_active or
      sm['controlsState'].longControlState == LongCtrlState.stopping
    )
    close_settle_cap = None
    if lead_control_active:
      close_settle_caps = [
        cap for cap in (
          self.get_vision_close_settle_cap(self.lead_one, v_ego, output_accel_min, close_settle_guard_active),
          self.get_vision_close_settle_cap(self.lead_two, v_ego, output_accel_min, close_settle_guard_active),
        ) if cap is not None
      ]
      if close_settle_caps:
        close_settle_cap = min(close_settle_caps)

    close_final_guard_cap = None
    if lead_control_active:
      close_final_guard_caps = [
        cap for cap in (
          self.get_vision_close_final_guard_cap(self.lead_one, v_ego, output_accel_min),
          self.get_vision_close_final_guard_cap(self.lead_two, v_ego, output_accel_min),
        ) if cap is not None
      ]
      if close_final_guard_caps:
        close_final_guard_cap = min(close_final_guard_caps)

    if lead_control_active and np.isfinite(v_cruise) and any(lead.status for lead in (self.lead_one, self.lead_two)):
      # This is only an acceleration cap. A negative cap would manufacture hard
      # braking on abrupt cruise-target drops instead of letting the MPC decelerate.
      cruise_accel_cap = max(0.0, (v_cruise - v_ego + 0.01) / max(action_t, self.dt))
      output_a_target = min(output_a_target, cruise_accel_cap)

    if vision_brake_cap_active:
      output_accel_min = min(output_accel_min, vision_cap_accel_min)

    policy_lead = self.lead_two if self.mpc.source == "lead1" else self.lead_one
    post_departure_active = self.post_departure_follow_settle_active(
      policy_lead, scene_v_ego, effective_t_follow,
    )
    # The RAV4's post-departure path used to bypass the ordinary follow cap for
    # the entire settle latch. When a slow lead changed lanes, that let the
    # cruise branch request full acceleration before the next lead was stable.
    # Keep the normal catch-up cap on this car; urgent braking remains outside
    # this comfort policy and is still allowed through unchanged.
    post_departure_bypass = post_departure_active and not is_toyota_rav4_tss2_post_departure_tune(self.CP)
    follow_result = apply_follow_policy(
      self.lead_one,
      self.lead_two,
      source=self.mpc.source,
      active=lead_control_active,
      v_ego=scene_v_ego,
      t_follow=effective_t_follow,
      previous_target=prev_output_a_target,
      raw_target=output_a_target,
      tracking=tracking_lead,
      post_departure=post_departure_bypass,
      blocked=bool(output_should_stop or vision_low_speed_stop_active or close_lead_caps),
      panic_bypass=panic_bypass,
    )
    comfort_follow_lead = follow_result.lead
    comfort_lead = follow_result.lead
    if follow_result.target < output_a_target:
      self.a_desired = min(self.a_desired, follow_result.target)
    else:
      self.a_desired = max(self.a_desired, follow_result.target)
    output_a_target = follow_result.target

    # Model-backed braking remains outside the ordinary follow policy. These
    # floors are safety responses, not comfort arbitration.
    model_brake_floor_active = False
    if comfort_follow_lead is not None and not panic_bypass and not output_should_stop and not vision_low_speed_stop_active:
      tracked_vision_model_brake_floor = self.get_tracked_vision_model_brake_floor(
        comfort_follow_lead, scene_v_ego, output_accel_min, effective_t_follow, model_desired_accel,
      )
      if tracked_vision_model_brake_floor is not None:
        model_brake_floor_active = True
        self.a_desired = min(self.a_desired, tracked_vision_model_brake_floor)
        output_a_target = min(output_a_target, tracked_vision_model_brake_floor)

    if comfort_follow_lead is not None and not panic_bypass and not output_should_stop and not vision_low_speed_stop_active:
      tracked_vision_model_brake_cap = self.get_tracked_vision_model_brake_cap(
        comfort_follow_lead, scene_v_ego, effective_t_follow, model_desired_accel,
      )
      if tracked_vision_model_brake_cap is not None:
        self.a_desired = max(self.a_desired, tracked_vision_model_brake_cap)
        output_a_target = max(output_a_target, tracked_vision_model_brake_cap)

    output_accel_max = no_throttle_output_max if not self.allow_throttle else accel_limits_turns[1]
    if COAST_CEILING_SLEW:
      output_accel_max = self.slew_coast_ceiling(output_accel_max, prev_output_a_target,
                                                 reset_state or bool(sm['carState'].standstill))
    final_accel_min = self.get_mpc_lead_brake_accel_min(output_accel_min, output_a_target_mpc)
    output_a_target = float(np.clip(output_a_target, final_accel_min, output_accel_max))

    if close_stop_hold_cap is not None:
      self.a_desired = min(self.a_desired, close_stop_hold_cap)
      output_a_target = min(output_a_target, close_stop_hold_cap)

    if standstill_stopped_lead_guard_cap is not None:
      self.a_desired = min(self.a_desired, standstill_stopped_lead_guard_cap)
      output_a_target = min(output_a_target, standstill_stopped_lead_guard_cap)

    if close_settle_cap is not None:
      self.a_desired = min(self.a_desired, close_settle_cap)
      output_a_target = min(output_a_target, close_settle_cap)

    if close_final_guard_cap is not None:
      self.a_desired = min(self.a_desired, close_final_guard_cap)
      output_a_target = min(output_a_target, close_final_guard_cap)

    if rav4_early_lead_caps:
      rav4_early_lead_cap = min(rav4_early_lead_caps)
      self.a_desired = min(self.a_desired, rav4_early_lead_cap)
      output_a_target = min(output_a_target, rav4_early_lead_cap)

    if close_release_hold_cap is not None:
      self.a_desired = min(self.a_desired, close_release_hold_cap)
      output_a_target = min(output_a_target, close_release_hold_cap)

    if depart_safety_veto:
      self.a_desired = min(self.a_desired, 0.0)
      output_a_target = min(output_a_target, 0.0)
      if sm['carState'].standstill:
        output_should_stop = True

    if lead_depart_accel_hold_active:
      output_a_target = max(output_a_target, lead_depart_accel_floor)

    if low_speed_weak_lead_accel_cap is not None and not (lead_depart_accel_hold_active and lead_depart_accel_floor_reused):
      self.a_desired = min(self.a_desired, low_speed_weak_lead_accel_cap)
      output_a_target = min(output_a_target, low_speed_weak_lead_accel_cap)

    if (
      lead_control_active and
      (bool(sm['carState'].standstill) or float(sm['carState'].vEgo) <= STANDSTILL_STOPPED_LEAD_GUARD_MAX_EGO_SPEED) and
      output_should_stop and
      accelerating_nudge_lead and
      not depart_safety_veto
    ):
      output_a_target = max(output_a_target, STANDSTILL_LEAD_NUDGE_ACCEL)

    force_stop_handoff = bool(
      getattr(sm['starpilotPlan'], 'forcingStop', False) and
      not lead_control_active and
      (
        float(getattr(sm['starpilotPlan'], 'forcingStopLength', float('inf'))) < 1.0 or
        float(getattr(sm['starpilotPlan'], 'vCruise', float('inf'))) <= FORCE_STOP_HANDOFF_MAX_VCRUISE
      )
    )

    if force_stop_handoff:
      output_should_stop = True

    manual_stop_resume_override = self._update_manual_stop_resume_override(sm)
    if manual_stop_resume_override:
      output_a_target = max(output_a_target, MANUAL_STOP_RESUME_OVERRIDE_MIN_ACCEL)
      output_should_stop = False

    experimental_release_accel_target = self.get_experimental_release_accel_target(
      comfort_follow_lead,
      scene_v_ego,
      effective_t_follow,
      prev_output_a_target,
      output_a_target,
      bool(
        now_t < self.experimental_release_accel_until and
        not output_should_stop and
        not vision_low_speed_stop_active and
        not getattr(sm['starpilotPlan'], 'forcingStop', False) and
        not getattr(sm['starpilotPlan'], 'redLight', False)
      ),
    )
    if experimental_release_accel_target is not None:
      self.a_desired = min(self.a_desired, experimental_release_accel_target)
      output_a_target = min(output_a_target, experimental_release_accel_target)

    if depart_release_hold_active:
      output_a_target = max(output_a_target, STANDSTILL_LEAD_CREEP_RELEASE_MIN_ACCEL)

    output_a_target = self.get_vehicle_far_follow_slew_target(
      scene_v_ego,
      prev_output_a_target,
      output_a_target,
      bool(output_should_stop or vision_low_speed_stop_active),
      panic_bypass,
    )

    # Dom gates this on its inside-gap closing cap, which this planner does not have; a nearer
    # second lead or an active model brake floor holds it off instead.
    far_lead_coast_other = self.lead_two if comfort_lead is self.lead_one else self.lead_one
    far_lead_coast_allowed = (
      not experimental_mode and
      comfort_lead is not None and
      desired_gap is not None and
      not output_should_stop and
      not vision_low_speed_stop_active and
      not close_lead_caps and
      not panic_bypass and
      not depart_safety_veto and
      not model_brake_floor_active and
      not (bool(getattr(far_lead_coast_other, "status", False)) and
           float(getattr(far_lead_coast_other, "dRel", float("inf"))) < float(getattr(comfort_lead, "dRel", 0.0))) and
      not bool(getattr(sm['starpilotPlan'], 'forcingStop', False)) and
      not bool(getattr(sm['starpilotPlan'], 'redLight', False)) and
      not bool(getattr(sm['starpilotPlan'], 'stopSignConfirmed', False))
    )
    if far_lead_coast_allowed:
      output_a_target = get_far_lead_coast_cap(comfort_lead, scene_v_ego, desired_gap, output_a_target,
                                               sm['modelV2'])
    output_a_target = get_far_radar_lead_early_coast_cap(comfort_lead, scene_v_ego, output_a_target)

    soft_stop_floor = None if (panic_bypass or bool(getattr(sm['starpilotPlan'], 'forcingStop', False))) else \
      get_soft_stop_floor(comfort_lead, scene_v_ego)
    if soft_stop_floor is not None and output_a_target < soft_stop_floor:
      # output only: raising self.a_desired would feed a softer x0 into the next MPC solve (see BRAKE_RELEASE_DWELL)
      output_a_target = soft_stop_floor

    if radar_gap_settle_active:
      output_a_target = RADAR_STANDSTILL_GAP_SETTLE_ACCEL
      output_should_stop = False

    sienna_restop_caps = [
      cap for cap in (
        get_toyota_sienna_post_departure_restop_cap(
          self.CP, self.lead_one, scene_v_ego, output_accel_min,
          standstill_nudge_gap, now_t, self.post_departure_follow_settle_until,
        ),
        get_toyota_sienna_post_departure_restop_cap(
          self.CP, self.lead_two, scene_v_ego, output_accel_min,
          standstill_nudge_gap, now_t, self.post_departure_follow_settle_until,
        ),
      ) if cap is not None
    ]
    if sienna_restop_caps:
      sienna_restop_cap = min(sienna_restop_caps)
      self.a_desired = min(self.a_desired, sienna_restop_cap)
      output_a_target = min(output_a_target, sienna_restop_cap)
      output_should_stop = True

    lc_merge_floor = self.get_lane_change_merge_accel_floor(
      sm, starpilot_toggles, scene_v_ego, v_cruise, action_t,
      blocked=bool(
        output_should_stop or vision_low_speed_stop_active or depart_safety_veto or
        getattr(sm['starpilotPlan'], 'forcingStop', False) or
        getattr(sm['starpilotPlan'], 'redLight', False)
      ),
      mpc_demand=output_a_target_mpc if self.mpc.source in ('lead0', 'lead1') else None,
    )
    if lc_merge_floor is not None:
      output_a_target = float(min(max(output_a_target, lc_merge_floor), output_accel_max))
      self.a_desired = max(self.a_desired, min(lc_merge_floor, output_accel_max))

    # Force-decel is the driver-monitoring no-response path. Keep a small
    # braking floor until the vehicle is actually stopped; normal MPC tapering
    # can otherwise leave it creeping indefinitely at the maneuver-test cutoff.
    if force_slow_decel and scene_v_ego > 0.1:
      output_a_target = min(output_a_target, FORCE_DECEL_MIN_ACCEL)

    try:
      starpilot_car_state = sm['starpilotCarState']
    except KeyError:
      starpilot_car_state = None
    driver_accel_pressed = bool(
      getattr(sm['carState'], 'gasPressed', False) or
      getattr(starpilot_car_state, 'accelPressed', False)
    )
    accord_stop_go_blocked = bool(
      not lead_control_active or
      output_should_stop or
      vision_low_speed_stop_active or
      depart_safety_veto or
      radar_gap_settle_active or
      getattr(sm['starpilotPlan'], 'forcingStop', False) or
      getattr(sm['starpilotPlan'], 'redLight', False) or
      driver_accel_pressed
    )
    accord_stop_go_target = self.get_honda_accord_stop_go_accel_target(
      policy_lead, scene_v_ego, prev_output_a_target, output_a_target, accord_stop_go_blocked,
    )
    if accord_stop_go_target < output_a_target:
      self.a_desired = min(self.a_desired, accord_stop_go_target)
      output_a_target = accord_stop_go_target

    stock_feel = bool(getattr(starpilot_toggles, "stock_brake_feel", False))
    brake_onset_enabled = BRAKE_ONSET_LIMIT or bool(getattr(starpilot_toggles, "brake_onset_limit", False))
    onset_gates = not reset_state and not bool(sm['carState'].standstill) and not (
      output_should_stop or vision_low_speed_stop_active or
      getattr(sm['starpilotPlan'], 'forcingStop', False) or getattr(sm['starpilotPlan'], 'redLight', False))
    if stock_feel and onset_gates:
      output_a_target = stock_feel_target((self.lead_one, self.lead_two), prev_output_a_target, output_a_target, self.dt)
      self._onset_need_over = False
    elif brake_onset_enabled and onset_gates:
      if panic_bypass and not self._onset_panic_prev:
        self._onset_panic_soft = prev_output_a_target > BRAKE_ONSET_PANIC_MAX_PRIOR_BRAKE
      onset_leads = (self.lead_one, self.lead_two)
      if BRAKE_ONSET_STOCK_RAMP:
        onset_jerk, self._onset_need_over = stock_onset_jerk(
          onset_leads, scene_v_ego, prev_output_a_target,
          panic_bypass and not self._onset_panic_soft and not BRAKE_ONSET_STOCK_PANIC_RAMP, self._onset_need_over)
      else:
        if not panic_bypass:
          onset_ttc_off = BRAKE_ONSET_TTC_OFF_S
        else:
          onset_ttc_off = BRAKE_ONSET_PANIC_TTC_S if self._onset_panic_soft else float('inf')
        onset_jerk = brake_onset_jerk(onset_leads, scene_v_ego, onset_ttc_off)
      output_a_target = brake_onset_limited_target(prev_output_a_target, output_a_target, self.dt, onset_jerk)
    else:
      self._onset_need_over = False
    self._onset_panic_prev = panic_bypass
    if BRAKE_RELEASE_LIMIT and not reset_state and not bool(sm['carState'].standstill):
      # prev is the last published target (after the on-path bound in update(), which runs after this)
      output_a_target = brake_release_limited_target(prev_output_a_target, output_a_target, self.dt)
    if BRAKE_RELEASE_DWELL and not reset_state and not bool(sm['carState'].standstill):
      output_a_target, self.brake_release_rise_ticks = brake_release_dwell_target(
        prev_output_a_target, output_a_target, self.brake_release_rise_ticks)
    else:
      self.brake_release_rise_ticks = BRAKE_RELEASE_DWELL_TICKS + 1

    self.output_a_target = output_a_target
    self.output_should_stop = bool(output_should_stop or vision_low_speed_stop_active)

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    plan_send.valid = sm.all_checks(service_list=['carState', 'controlsState', 'selfdriveState', 'radarState'])

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']
    longitudinalPlan.solverExecutionTime = self.mpc.solve_time

    longitudinalPlan.speeds = self.v_desired_trajectory.tolist()
    longitudinalPlan.accels = self.a_desired_trajectory.tolist()
    longitudinalPlan.jerks = self.j_desired_trajectory.tolist()

    # LongControl needs to know about whichever lead MPC is following. Using
    # leadOne only leaves the stop-release guard blind when source=lead1.
    selected_lead = sm['radarState'].leadTwo if self.mpc.source == "lead1" else sm['radarState'].leadOne
    longitudinalPlan.hasLead = bool(selected_lead.status)
    longitudinalPlan.longitudinalPlanSource = self.mpc.source
    longitudinalPlan.fcw = self.fcw

    # Lead trajectories the MPC actually solved against, for offline comparison of the
    # extrapolated path against the model-predicted one.
    longitudinalPlan.leadTrajectoryX0 = self.mpc.lead_xv_0[:, 0].tolist()
    longitudinalPlan.leadTrajectoryV0 = self.mpc.lead_xv_0[:, 1].tolist()
    longitudinalPlan.leadTrajectoryX1 = self.mpc.lead_xv_1[:, 0].tolist()
    longitudinalPlan.leadTrajectoryV1 = self.mpc.lead_xv_1[:, 1].tolist()

    longitudinalPlan.aTarget = float(self.output_a_target)
    longitudinalPlan.accelBoost = float(self.accel_boost.value)
    force_stop_handoff = bool(
      sm['starpilotPlan'].forcingStop and (
        sm['starpilotPlan'].forcingStopLength < 1.0 or
        sm['starpilotPlan'].vCruise <= FORCE_STOP_HANDOFF_MAX_VCRUISE
      )
    )
    stop_sign_hold_speed = get_stop_sign_low_speed_hold(self.CP)
    stop_sign_low_speed_hold = bool(
      stop_sign_hold_speed is not None and
      bool(getattr(sm['starpilotPlan'], 'stopSignConfirmed', False)) and
      float(getattr(sm['carState'], 'vEgo', 0.0)) <= stop_sign_hold_speed and
      not bool(getattr(sm['carState'], 'gasPressed', False))
    )
    longitudinalPlan.shouldStop = bool(self.output_should_stop) or force_stop_handoff or stop_sign_low_speed_hold
    longitudinalPlan.allowBrake = True
    longitudinalPlan.allowThrottle = bool(self.allow_throttle)
    longitudinalPlan.closeLeadBrakeCap = float(self.close_lead_brake_cap_value
                                               if self.close_lead_brake_cap_value < 0.0 else 0.0)
    longitudinalPlan.leadGeometryRequiredAccel = float(self.lead_geometry_required_accel)

    pm.send('longitudinalPlan', plan_send)
