#!/usr/bin/env python3
import math
import numpy as np
from collections import deque
from types import SimpleNamespace
from typing import Any

import capnp
from cereal import messaging, log, car, custom
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL, Priority, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.common.simple_kalman import KF1D
from openpilot.starpilot.common.starpilot_variables import get_starpilot_toggles
from opendbc.car.honda.radar_interface import (BOSCH_A_DIRECT_VREL_CENTER_RAW, BOSCH_A_DIRECT_VREL_MIN_RAW,
                                               BOSCH_A_DIRECT_VREL_SCALE_MPS, BOSCH_A_FREQ_HZ)
from opendbc.car.honda.values import HONDA_BOSCH_A


# Default lead acceleration decay set to 50% at 1s
_LEAD_ACCEL_TAU = 0.6

# Shadow range-derived vRel, computed for whichever radar lead is selected -- not only Bosch-A.
# Timestamps come from the message clock so replay is faithful; wall-clock time made every
# accelerated replay of this field meaningless. The fit is plain LSQ with no outlier rejection, so
# it inherits the range channel's ~1% gross outliers: read it as a diagnostic, not as a validated
# velocity.
#
# Telemetry only (D-044) EXCEPT on Bosch-A with RANGE_VREL_ASSIST on (built in), where D-053 lets it
# correct the published lead velocity in one direction. The outlier caveat above is precisely why
# that assist needs RANGE_VREL_ASSIST_ARM_UPDATES; see the block below.
RANGE_VREL_SAMPLES = 5   # deque length AND the minimum fit length; do not diverge these
RANGE_VREL_MIN_SPAN_S = 0.12
RANGE_VREL_MAX_SPAN_S = 0.60

# --- Range-derived vRel assist (built in for Bosch-A; was the RangeDerivedVrel param) ----------
# D-053 amends D-044's "nothing consumes it" for Bosch-A only. On in the owner's drives from 0000023e; replay, static
# and limited road evidence. RANGE_VREL_ASSIST = False (replays, tests) is the shipped U11 behaviour. ONE-SIDED: the
# range LSQ above may only make the published closing speed MORE closing, never less. It exists
# because U11 -- the Bosch-A native relative velocity -- is both late and rail-bounded, and both
# failures understate closing:
#
#   * D-041, route 000001f9 at 29:52. U11 railed at -13.5 m/s on 88 of 88 active frames with
#     healthy u10 while the range closed smoothly at -19.4 m/s. D-041 publishes the rail as a
#     BOUND and says recovering the true value past it "needs the range channel and is
#     deliberately left to a separate, validated change". This is that change, still unvalidated.
#   * D-043 / D-044, routes 000001fe/fb/fd. U11 detects a closing onset 0.88-1.28 s late while a
#     4-sample range LSQ lands within 0.07-0.14 s. At 000001f3 19:27 the fitted range rate was
#     -6.7 m/s while U11 still read -2.08.
#
# WHAT THIS CANNOT DO, and it is the hazard, not a caveat: the LSQ is fitted to the same range
# channel U11 is being checked against, so a RANGE error is invisible to it. STATUS.md's t~=11 s
# false brake is exactly that -- U11 (-6.0) and the fitted rate (-4.5 to -6.4) agreed with each
# other while the range itself walked ~6 m inward. On those recorded figures the disagreement
# never reaches MIN_DISAGREEMENT and this assist stays inert, but a range walk that outran U11
# would be amplified by it, bounded only by MAX_CORRECTION and the guards in the rework block below.
#
# 2026-09-16 REWORK. The first version was replayed open-loop, with the real Track, over every
# liveTracks sweep of three routes: 00000232, 00000236 and 00000237. It did recover what it was
# built for (236 12:51, a nearly stopped car behind a -13.5 rail), but it also corrected three
# times with no closing to recover, and its KF step did harm in a fourth case:
#   * 232 3:02.8, a range WALK. Range 59.0 -> 56.1 -> 59.1 m over ~2.6 s while U11 read +2.1 ->
#     +0.1 -> +1.1; the 5-sample fit followed the walk and armed at 4.3-4.6 m/s.
#   * 236 22:13.6, a NEW TRACK settling. Range 77.2 -> 59.5 m in 1.8 s then flat: a +10 m/s^2
#     relative acceleration no car does. Correction hit the 8.0 cap.
#   * 236 14:45, EGO STOPPED. vEgo 0.0, U11 +1.5..+2.3, 5-sample fit -9 to -12.7. Cap again.
#   * Feeding the corrected speed to the lead KF made aLeadK absorb every arming step as an
#     acceleration: worst extra aLeadK dip -3.8 / -7.2 / -6.0 m/s^2 on the three routes, and
#     long_mpc and conditional_chill_mode read aLeadK directly. At 236 18:55 the vRel correction
#     itself matched the range; that dip was the harm.
# The rework keeps the short fit (and the vRelRangeDerived telemetry) byte-identical, adds a
# second, longer fit that must AGREE before anything is published, and adds guards that each
# CLEAR the correction outright. The only clamps are MAX_CORRECTION and the zero-speed cap, and
# both are physical bounds rather than tuned values. The lead KF is fed the NATIVE speed again;
# the correction is applied at publish time only, so aLeadK never sees it. Still replay-only:
# nothing here has been driven. (Since then: on in the owner's Civic drives from 0000023e.)
RANGE_VREL_ASSIST = True

# Minimum disagreement, m/s, before arming. D-043 deliberately does not chase "the milder
# 0.6-2.5 m/s overshoots at deceleration onset"; this is the mirror of that, and 2.0 m/s is also
# the band tools/bosch_a_vrel_shadow_report.py already reports against. It is NOT a noise floor on
# its own: with 5 evenly spaced samples the LSQ slope moves 0.2/h per metre of error on the newest
# sample, h = 1/14.35 s, so a single 1 m range outlier shifts the fit ~2.9 m/s and clears this on
# its own. ARM_UPDATES is what rejects that, not this threshold.
RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS = 2.0

# Consecutive measured updates above that threshold before any correction is applied. One gross
# range outlier cannot arm this: as it walks the 5-sample window its leverage on the fit runs
# +2h, +h, 0, -h, -2h (normalised by sum (t - tbar)^2 = 10h^2), so it can only push the fit the
# SAME way for two consecutive fits. Three would therefore be sufficient; five is taken instead to
# match ONSET_SUSTAIN_SAMPLES in tools/bosch_a_vrel_shadow_report.py, so the offline onset report
# the driver runs to judge this feature uses the same rule the car does. Cost 5/14.35 = 0.35 s
# against a recorded 0.88-1.28 s U11 lag.
RANGE_VREL_ASSIST_ARM_UPDATES = 5

# Hard cap on the extra closing, m/s. Sized by the only two recorded events that need it:
# 000001f9 29:52 wants 5.9 (rail -13.5 vs range -19.4) and 000001f3 19:27 wants 4.6 (U11 -2.08 vs
# range -6.7). This is n = 2 and NOT a distribution -- it is a bound on the damage a bad fit can
# do, not a fitted value. Lowering it below ~6.0 makes the feature unable to do the one thing
# D-041 left for it.
RANGE_VREL_ASSIST_MAX_CORRECTION_MPS = 8.0

# Geometry. A range derivative is a RADIAL rate, not a longitudinal one. Together these bound the
# azimuth at asin(1.5 / 8.0) = 10.8 deg, where cos = 0.982: reading the radial rate as
# longitudinal understates the longitudinal component by at most 1.8% and admits at most 0.19 of
# any lateral rate. Adjacent-lane tracks sit at 17-23 deg (see Track.get_RadarState) and are
# excluded outright.
RANGE_VREL_ASSIST_MIN_D_REL_M = 8.0
RANGE_VREL_ASSIST_MAX_ABS_Y_REL_M = 1.5

# --- Rework guards (2026-09-16). Chosen on the three-route replay above, which is OPEN-LOOP: a
# corrected lead changes what the car does next, and none of that is in these numbers. Every value
# below keeps all three recorded false corrections at exactly zero -- n = 3 known hurts, not a
# distribution. Replay figures are m/s*s (the correction integrated over the case). "Help" is the
# five recorded under-reads the rework still corrects -- 236 12:51 and 18:55, 237 5:21, 14:25 and
# 19:49 -- which total 42.7 m/s*s with every constant at the value below.
#
# The LONG fit. The same plain LSQ over the last 15 measured range samples (~1.0 s at 14.35 Hz), in
# its own deque that every measured update appends to, lead or not, and that is never cleared: a
# history that spans a gap is rejected by span instead. The disagreement acted on is the SMALLER of
# the short and long ones, so both fits must see the extra closing. With h = 1/14.35 s:
#   * a persistent range STEP of s metres moves four consecutive 5-sample fits by 2.87s, 4.30s,
#     4.30s and 2.87s m/s, so a 0.7 m step alone holds MIN_DISAGREEMENT for four fits, one short of
#     ARM_UPDATES. The 15-sample fit moves at most 1.43s, so there the step has to be 1.4 m.
#   * the price is lag: the long slope is the rate ~0.49 s ago. It under-reads a growing closing
#     rate (the one-sided rule turns that into a later, smaller correction, never a wrong-way one)
#     and over-reads a shrinking one, which the min() with the short fit bounds.
#   * a single gross outlier of e metres moves it by at most e/(40h) = 0.36e m/s and leaves an RMS
#     residual of 0.22-0.25e, so an outlier big enough to push it 2 m/s (5.6 m) fails the residual.
#   * a track cannot correct until it has 15 measured samples. On the replay that requirement,
#     not the speed floor, is what zeroed 236 14:45: it was a new track, and it stayed at zero with
#     the speed floor, the residual and the plausibility guards all removed.
# Replayed alternatives: 10 samples (span floor 0.4 s) let the walk (1.8 m/s*s) and the settle (1.3)
# back through; 20 kept every hurt at zero but corrected 29% less (30.4 m/s*s of help, not 42.7).
RANGE_VREL_LONG_SAMPLES = 15
RANGE_VREL_LONG_MIN_SPAN_S = 0.6
RANGE_VREL_LONG_MAX_SPAN_S = 1.5

# RMS residual of the long fit, metres. A constant relative acceleration a leaves only ~a*W^2/26.8
# of residual over the W = 0.98 s window (0.36 m at 10 m/s^2), so this does not reject a physical
# braking event; it rejects range behaviour no car produces. The 236 22:13.6 settle ran 1.17 ->
# 0.89 -> 0.63 m; a 0.7 limit let 0.4 m/s*s of it through and no limit let 0.7 through.
# It is NOT free, and it is the one guard here that is a judgement call: removing it also recovered
# more of the real closing at 236 18:55 (11.0 m/s*s, not 7.0) and 237 5:21 (10.9, not 9.8), where
# a far lead's range is noisier. 0.6 trades that help for zero phantom correction on a settle.
# It does NOT catch the 232 3:02.8 walk (0.20-0.37 m): the short/long agreement does, with ONE
# sample of margin at ARM_UPDATES = 5 (at 4, 1.0 m/s*s of the walk got through), so do not lower
# that. The 236 22:13.6 settle is ALSO held off by exactly one arm update (at 4, 0.4 m/s*s got
# through on replay): both recorded phantoms rest on that one-update margin.
RANGE_VREL_ASSIST_MAX_LONG_RESIDUAL_M = 0.6

# Ego speed floor, m/s (the aligned ego speed, vLead - vRel). This is conservatism, not evidence:
# 236 14:45 was a standstill, but the long-history requirement above already zeroed it, and floors
# of 0 and 3.0 kept every replayed hurt at zero too (both added 2.0 s of correction). Below 13.5 m/s
# a lead that is not reversing cannot put U11 on its rail, so the D-041 case cannot occur there.
RANGE_VREL_ASSIST_MIN_V_EGO_MPS = 5.0

# Plausibility: the lead speed the long fit implies (aligned ego speed plus the long slope) must not
# be more than this far below zero. Defence in depth only: it changed no replayed output at 5.0, at
# 3.0 or removed, including with the speed floor at 0. It is loose on purpose, because the lagging
# long fit makes a STOPPED lead read backwards while ego brakes -- a 1.0 margin halved the help at
# 236 12:51 (3.2 -> 1.6 m/s*s) -- so it rejects only a fit that describes no lead at all.
RANGE_VREL_ASSIST_MAX_BACKWARD_LEAD_MPS = 5.0

# U11's low saturation rail (radar_interface.py). ON the rail U11 is a bound, not a reading, so the
# short disagreement there falling back under MIN_DISAGREEMENT says nothing about whether the
# closing has ended. There ARMING and HOLDING use the long disagreement alone, while the correction
# is still sized by the smaller of the two. Without the rule, 236 12:51 (U11 exactly -13.50 on every
# sample while the range closed near -16) kept disarming on short-fit noise: 2.4 m/s*s, not 3.2.
# Sizing by the long fit alone recovered more at 12:51 (4.9) but over-corrected the tail of both
# replayed rail approaches as the closing rate shrank, leaving the published vRel up to 1.8 m/s
# (236 12:54) and 1.6 m/s (237 10:00) further from a centred 2 s range difference than the native
# rail was.
BOSCH_A_U11_LOW_RAIL_MPS = (BOSCH_A_DIRECT_VREL_MIN_RAW - BOSCH_A_DIRECT_VREL_CENTER_RAW) * BOSCH_A_DIRECT_VREL_SCALE_MPS

# --- Rail fast path (2026-09-26, STATUS 130; extends D-053, rides RANGE_VREL_ASSIST).
# REPLAY evidence only, open loop. 00000271 9:26 (BM0): a near-stopped car published at 118.8 m
# with U11 on the rail from before publication; true closing about -21..-23. Both range fits read
# -21..-28 from the 5th sample on, but the assist could not arm until the 15-sample long history
# filled (1.0 s) plus 5 arm updates: first correction 1.22 s after publication, 0.9 s before the
# driver braked. Once armed, the min(short, long) sizing followed the short fit's dips and
# published -15.4..-16.3 while the trailing 1 s range fit read -18.1..-19.9.
# ON the rail only (U11 is a bound there, D-041), and only when BOTH fits corroborate:
#   * the long fit may be taken over RAIL_LONG_MIN_SAMPLES (span floor RAIL_LONG_MIN_SPAN_S),
#     with the same residual, backward-lead and span-ceiling guards;
#   * RAIL_ARM_UPDATES consecutive measured updates on which the SMALLER of the short and long
#     disagreements clears MIN_DISAGREEMENT arm it (off the rail the 5-update rule is unchanged);
#   * while railed the correction is sized by the MEAN of the two disagreements, which is never
#     beyond the more-closing range fit, and stays under MAX_CORRECTION and the vLead >= 0 bound.
# Set RANGE_VREL_RAIL_FAST to False to restore the pre-130 rail behaviour exactly.
RANGE_VREL_RAIL_FAST = True
RANGE_VREL_RAIL_LONG_MIN_SAMPLES = 8
RANGE_VREL_RAIL_LONG_MIN_SPAN_S = 0.45
RANGE_VREL_RAIL_ARM_UPDATES = 3
RANGE_VREL_RAIL_SIZE_MEAN = True

# --- Vision-corroborated range assist (2026-09-26, extends D-053, rides RANGE_VREL_ASSIST).
# REPLAY evidence only (open- and closed-loop), nothing driven; default OFF. 0000026c--10bec2e200 4:08:
# a lead braking on a curve at 80 -> 60 m. U11 lagged (-2.7 -> -13.5 over 1.3 s) while the range closed
# at -7 .. -23, but the track sat at yRel 9.3 -> 6.3 m, so the |yRel| <= 1.5 lane proxy blocked D-053.
# A path-relative replacement for that gate was rejected (STATUS 148): without the lateral gate the
# curve range WALK at 70-95 m (26c 649.9, 237 942.8, 236 2211.4) armed the assist.
# Here three D-053 blocks are relaxed ONLY while the camera corroborates the closing itself, i.e. a
# model lead with prob >= VISION_ASSIST_MIN_PROB whose range matches the track within
# VISION_ASSIST_RANGE_TOL of dRel, whose lateral position matches within VISION_ASSIST_MAX_DY_M, and
# whose own closing speed (vEgo - v) is >= VISION_ASSIST_MIN_CLOSING_MPS:
#   * the |yRel| lane gate (the 10.8 deg azimuth bound still applies),
#   * a long fit that fails span/residual (the short fit decides instead, VISION_ASSIST_SHORT_ONLY),
#   * the 5-update arm count (VISION_ASSIST_ARM_UPDATES).
# Whenever the correction exists only because of one of these (the plain rule would publish zero), it
# is bounded so the published vRel claims at most VISION_ASSIST_CLOSING_MARGIN_MPS more closing than
# vision, and it is zero on any update vision stops corroborating. Once the plain rule would have armed
# on its own, the correction is exactly the plain one: this can never publish LESS closing than D-053.
# Numbers, from the 32-route open-loop replay (STATUS 152): MIN_CLOSING 3 m/s let a slow real closing
# (vision 3-4 m/s, 0245 773.9, 025e 313.6, 0271 1434.3) arm early to a vision-unconfirmed -1.0 dip;
# 5 m/s removed all three and kept 26c 4:08 (vision closing 5.3-6.5). MIN_PROB 0.7, not 0.9: the 26c
# lead is at p 0.74-0.82 during the onset. The 26c gain is small (0.25 s earlier at -1.5, 0.15 s at
# -1.0, the same at -2.0): past 257.0 the MPC, not the radar, limits the response.
# Built in (was the RangeVisionAssist param, default on; on in the owner's drives from 0000027e). Acts only with
# RANGE_VREL_ASSIST on. VISION_ASSIST_GEOMETRY forces it on per track for replay harnesses; it stays False here.
RANGE_VISION_ASSIST = True
VISION_ASSIST_GEOMETRY = False
VISION_ASSIST_MIN_PROB = 0.7
VISION_ASSIST_RANGE_TOL = 0.15
VISION_ASSIST_MAX_DY_M = 3.0
VISION_ASSIST_MIN_CLOSING_MPS = 5.0
VISION_ASSIST_CLOSING_MARGIN_MPS = 3.0
VISION_ASSIST_MAX_AZIMUTH_DEG = 10.8
VISION_ASSIST_ARM_UPDATES = 3          # arm updates needed while corroborated on every one of them
VISION_ASSIST_SHORT_ONLY = True        # corroborated: a long fit failing span/residual falls back to the short fit

# Last, the correction is capped at the native lead speed, so a corrected vLead is never published
# below zero. A physical bound like MAX_CORRECTION, not a tuned value: on the replay it bound only
# at 236 12:51, where it trimmed 0.2 m/s*s.

# radar tracks
SPEED, ACCEL = 0, 1     # Kalman filter states enum

# Young-track range bound (route 0000027a ~8:33, BM2). Track 15 was born at 64 m with U11 -11.1 and was then held
# at -10.7 by the D-043 coast for 0.9 s while its own range stayed at 62.6-63.6 m; vision (p 0.95, 73-81 m, own speed)
# said not closing, and chill braked to -2.0 (aEgo -2.7). For a Bosch-A lead track under YOUNG_TRACK_MAX_AGE_S old
# whose range history since birth (every fresh sweep, coasted ones included: a coast holds vRel, not the range) fits
# a line of |slope| <= YOUNG_TRACK_FLAT_MAX_RATE with a small residual, and whose model lead contradicts the closing
# (YOUNG_TRACK_VISION_GATE), the published vRel may claim at most YOUNG_TRACK_FLAT_MARGIN more closing than that
# slope. Reporting only: the point is published, the KF, the D-053 assist and the association are untouched, and a
# track whose range falls faster than the rate cap is never bounded. The one-sided coast bound (STATUS 111/129) is
# unchanged; this acts on radarState leads only, for their first second. Replay evidence only (STATUS 149).
#
# Noisy far-range tracks (route 00000284 22:35, BM 22:38). Track 17 was born at ~79 m with U11 -10.5 and held there
# by the coast for ~1.5 s while its range went 79 -> 83 -> 80 m and vision (p 1.00, own speed) said not closing;
# chill braked to -1.8. The fit residual was 0.56-1.28 m (> 0.6) and the hold outlasted 1.0 s, so the bound never
# fired. A fit with residual up to YOUNG_TRACK_NOISY_MAX_RESIDUAL_M now also bounds, but its floor is lowered by
# YOUNG_TRACK_NOISY_SE_K standard errors of the slope, so noise buys closing rather than removing it; a fit within
# YOUNG_TRACK_MAX_RESIDUAL_M keeps the original floor exactly. The age window is 2.0 s to cover the hold. Replay on
# 35 routes: 284 1358 -1.46 -> -0.88, no other event softer by > 0.3 or later at -1.5 (STATUS 162).
YOUNG_TRACK_FLAT_RANGE_BOUND = True
YOUNG_TRACK_MAX_AGE_S = 2.0       # 1.0 until STATUS 162
YOUNG_TRACK_MIN_SAMPLES = 6
YOUNG_TRACK_MIN_SPAN_S = 0.35
YOUNG_TRACK_MAX_RESIDUAL_M = 0.6
YOUNG_TRACK_NOISY_MAX_RESIDUAL_M = 2.0
YOUNG_TRACK_NOISY_SE_K = 2.0
YOUNG_TRACK_FLAT_MAX_RATE = 6.0   # 3.0 opened only at 0.61 s on 27a (the first 0.4 s fit is -4.6)
YOUNG_TRACK_FLAT_MARGIN = 3.0
# Only when the matching model lead (leadsV3[i]) is confident, not nearer than the radar lead, and itself not closing:
# the bound needs the camera to contradict the coast as well as the track's own range. Without this gate the bound
# also softened two real approaches whose young track sat on a flat stretch of range (00000266 795.4, -1.5 crossing
# 0.35 s later; 00000237 1188.2), both with vision closing 7-8.5 m/s.
YOUNG_TRACK_VISION_GATE = True
YOUNG_TRACK_VISION_MIN_PROB = 0.9
YOUNG_TRACK_VISION_MAX_CLOSING = 2.0
YOUNG_TRACK_VISION_MIN_ACCEL = -1.0
YOUNG_TRACK_VISION_RANGE_MARGIN_M = 5.0

# stationary qualification parameters
V_EGO_STATIONARY = 4.   # no stationary object flag below this speed

RADAR_TO_CENTER = 2.7   # (deprecated) RADAR is ~ 2.7m ahead from center of car
RADAR_TO_CAMERA = 1.52  # RADAR is ~ 1.5m ahead from center of mesh frame
G90_RADAR_LOW_SPEED_MAX_DIST = 12.0
G90_RADAR_LOW_SPEED_MAX_Y = 0.6
HONDA_BOSCH_A_RADAR_TS = 1.0 / BOSCH_A_FREQ_HZ
HONDA_BOSCH_A_LOW_SPEED_MIN_COUNT = 3
HONDA_BOSCH_A_CHALLENGER_STALE_CYCLES = 2
HONDA_BOSCH_A_GROSS_DISTANCE_STALE_CYCLES = 3
HONDA_BOSCH_A_GROSS_DISTANCE_M = 25.0


def is_bosch_a_radar_car(CP) -> bool:
  return CP.brand == "honda" and CP.carFingerprint in HONDA_BOSCH_A and not CP.radarUnavailable


# Adjacent-lane stopped-vehicle detector, used as a stop-line hint on red-light
# approaches. The qualifier is the DECELERATION HISTORY, not the current speed: roadside
# furniture and curb-parked cars never show a moving -> stopped transition, so testing
# for "anything slow in the next lane" instead would brake us early for parked cars.
ADJACENT_STOP_MOVING_V = 5.0      # m/s — must have genuinely been moving
ADJACENT_STOP_REST_V = 1.5        # m/s — and then genuinely at rest
ADJACENT_STOP_MOVING_FRAMES = 15  # 0.75 s at 20 Hz, both ways: rejects speed noise
ADJACENT_STOP_REST_FRAMES = 15
ADJACENT_STOP_MIN_Y = 1.8         # m — inside this is our own lane
ADJACENT_STOP_MAX_Y = 7.5         # m — beyond this is roadside, not an adjacent lane
ADJACENT_STOP_MAX_D = 110.0       # m
ADJACENT_STOP_QUEUE_GAP_M = 5.0   # m — anything stopped beyond the furthest qualifier means
                                  # the bar is past it too, so the hint would stop us short


class KalmanParams:
  def __init__(self, dt: float):
    # Lead Kalman Filter params, calculating K from A, C, Q, R requires the control library.
    # hardcoding a lookup table to compute K for values of radar_ts between 0.01s and 0.2s
    assert dt > .01 and dt < .2, "Radar time step must be between .01s and 0.2s"
    self.A = [[1.0, dt], [0.0, 1.0]]
    self.C = [1.0, 0.0]
    dts = [i * 0.01 for i in range(1, 21)]
    K0 = [0.12287673, 0.14556536, 0.16522756, 0.18281627, 0.1988689,  0.21372394,
          0.22761098, 0.24069424, 0.253096,   0.26491023, 0.27621103, 0.28705801,
          0.29750003, 0.30757767, 0.31732515, 0.32677158, 0.33594201, 0.34485814,
          0.35353899, 0.36200124]
    K1 = [0.29666309, 0.29330885, 0.29042818, 0.28787125, 0.28555364, 0.28342219,
          0.28144091, 0.27958406, 0.27783249, 0.27617149, 0.27458948, 0.27307714,
          0.27162685, 0.27023228, 0.26888809, 0.26758976, 0.26633338, 0.26511557,
          0.26393339, 0.26278425]
    self.K = [[np.interp(dt, dts, K0)], [np.interp(dt, dts, K1)]]


def young_track_vision_contradicts(lead, vis, v_ego: float) -> bool:
  """YOUNG_TRACK_VISION_GATE: a confident model lead at or beyond the radar lead's range that is not closing."""
  if float(vis.prob) < YOUNG_TRACK_VISION_MIN_PROB or not len(vis.x) or not len(vis.v) or not len(vis.a):
    return False
  return (float(vis.x[0]) >= float(lead.dRel) - YOUNG_TRACK_VISION_RANGE_MARGIN_M and
          float(vis.v[0]) - float(v_ego) >= -YOUNG_TRACK_VISION_MAX_CLOSING and
          float(vis.a[0]) >= YOUNG_TRACK_VISION_MIN_ACCEL)


def vision_assist_closing(d_rel: float, y_rel: float, vis, v_ego: float) -> float | None:
  """VISION_ASSIST_GEOMETRY: the model lead's closing speed (m/s, > 0) when it corroborates this track closing, else None."""
  if vis is None or float(vis.prob) < VISION_ASSIST_MIN_PROB or not len(vis.x) or not len(vis.v) or not len(vis.y):
    return None
  vx = float(vis.x[0]) - RADAR_TO_CAMERA
  if abs(vx - float(d_rel)) > VISION_ASSIST_RANGE_TOL * max(float(d_rel), 1.0):
    return None
  if abs(float(y_rel) + float(vis.y[0])) > VISION_ASSIST_MAX_DY_M:
    return None
  closing = float(v_ego) - float(vis.v[0])
  return closing if closing >= VISION_ASSIST_MIN_CLOSING_MPS else None


class Track:
  def __init__(self, identifier: int, v_lead: float, kalman_params: KalmanParams):
    self.identifier = identifier
    self.cnt = 0
    self.aLeadTau = FirstOrderFilter(_LEAD_ACCEL_TAU, 0.45, DT_MDL)
    self.K_A = kalman_params.A
    self.K_C = kalman_params.C
    self.K_K = kalman_params.K
    self.kf = KF1D([[v_lead], [0.0]], self.K_A, self.K_C, self.K_K)

    self.leadTrackID = 0

    # A range-derived vRel, published alongside the radar's own vRel so the two can be compared on
    # real drives. Measured on 000001fe/fb/fd, U11 (the Bosch-A native velocity) detects a closing
    # onset 0.88-1.28 s late while a 4-sample range LSQ lands within 0.07-0.14 s; and on 00000141
    # R141-8 U11 diverged from the range by 13.7 m/s while the range moved 1.9 m.
    #
    # Shadow telemetry under D-044; since D-053 it ALSO drives range_assist_correction below, but
    # only on Bosch-A, only for the lead track, and only with RANGE_VREL_ASSIST on.
    self.range_hist: deque = deque(maxlen=RANGE_VREL_SAMPLES)
    self.vRelRange = float('nan')
    # Freshness bit for the fit above. vRelRange is only ASSIGNED once the deque is full, so after
    # a dropout clears it the field holds the pre-gap value for up to four updates. That is
    # harmless for telemetry and unacceptable for control, so D-053 reads this rather than
    # isfinite(vRelRange).
    self.vRelRangeFresh = False
    # D-053 rework: the LONG range history (see RANGE_VREL_LONG_SAMPLES). Appended on every measured
    # update whether or not this track is a lead, so a track that becomes one already has it; never
    # cleared. The fit over it is only computed while the assist is evaluating this track, and the
    # three fields below hold that last fit (NaN before one) for tests and debugging.
    self.range_hist_long: deque = deque(maxlen=RANGE_VREL_LONG_SAMPLES)
    self.vRelRangeLong = float('nan')
    self.vRelRangeLongResidual = float('nan')
    self.vRelRangeLongSpan = float('nan')

    # D-053 range-derived vRel assist. Inert unless RadarD passes range_assist=True, which needs
    # RANGE_VREL_ASSIST, a Bosch-A car, and this track having been leadOne/leadTwo last
    # cycle. range_assist_correction is m/s of EXTRA closing and is never negative.
    self.range_assist_active = False
    self.range_assist_arm_count = 0
    self._range_long_min_samples = RANGE_VREL_LONG_SAMPLES  # lowered per update on the rail fast path
    self.range_assist_rail_count = 0
    self.range_assist_correction = 0.0
    self.vision_assist_count = 0
    self.vision_assist_early = False  # armed only through the vision path; see _update_range_assist
    # Last liveTracks timestamp this track was updated with, used to tell a DUPLICATE radard
    # cycle (no new message; t_now unchanged) from a COAST (new message, measured False).
    # measurement_update is False for both and they need opposite handling -- see
    # _update_range_assist.
    self._range_assist_last_t = float('nan')
    # YOUNG_TRACK_FLAT_RANGE_BOUND: first update time and every fresh-sweep (t, dRel) of the track's first
    # YOUNG_TRACK_MAX_AGE_S. Coasted sweeps count: a Bosch-A coast holds vRel but publishes the live gated range.
    self.t_first = float('nan')
    self.young_range_hist: list = []

    # deceleration history for the adjacent-lane stopped-vehicle detector
    self.moving_frames = 0
    self.rest_frames = 0
    self.seen_moving = False

  def update(self, d_rel: float, y_rel: float, v_rel: float, v_lead: float, measured: bool,
             measurement_update: bool | None = None, t_now: float = 0.0,
             range_assist: bool = False, vision_closing: float | None = None, vision_assist: bool = False):
    # relative values, copy
    self.dRel = d_rel   # LONG_DIST
    self.yRel = y_rel   # -LAT_DIST
    self.vRel = v_rel   # REL_SPEED
    self.vLead = v_lead
    self.measured = measured   # measured or estimate

    # `measurement_update` is separate from the published measured bit so legacy radar sources keep
    # their existing behaviour. Civic Bosch emits real measurements at ~15 Hz while radard is driven
    # at the ~20 Hz model rate; duplicate liveTracks payloads must not be absorbed twice.
    if measurement_update is None:
      # Preserve the historical Track.update behaviour for direct/legacy callers. The radar source
      # adapter supplies an explicit False only for a duplicate Civic Bosch payload.
      measurement_update = True

    # computed velocity and accelerations
    # Shadow estimator: real measurements only -- a duplicate payload would forge a zero-dt sample.
    if not self.t_first == self.t_first:
      self.t_first = float(t_now)
    if float(t_now) - self.t_first <= YOUNG_TRACK_MAX_AGE_S and \
       (not self.young_range_hist or float(t_now) > self.young_range_hist[-1][0]):
      self.young_range_hist.append((float(t_now), float(d_rel)))

    if measurement_update:
      self.vRelRangeFresh = False
      self.range_hist.append((float(t_now), float(d_rel)))
      if len(self.range_hist) >= RANGE_VREL_SAMPLES:
        ts = np.array([p[0] for p in self.range_hist])
        ds = np.array([p[1] for p in self.range_hist])
        span = ts[-1] - ts[0]
        # Reject a stale or gappy history: an LSQ across a dropout is meaningless.
        if RANGE_VREL_MIN_SPAN_S <= span <= RANGE_VREL_MAX_SPAN_S:
          self.vRelRange = float(np.polyfit(ts - ts[-1], ds, 1)[0])
          self.vRelRangeFresh = True
        else:
          self.vRelRange = float('nan')
          if span > RANGE_VREL_MAX_SPAN_S:
            self.range_hist.clear()
            self.range_hist.append((float(t_now), float(d_rel)))
      self.range_hist_long.append((float(t_now), float(d_rel)))

    # D-053. Must run after the fits above. It only sets range_assist_correction: the KF below is
    # fed the NATIVE speed, and get_RadarState applies the correction to vRel, vLead and vLeadK at
    # publish time. The first version fed the corrected speed here, and aLeadK absorbed every
    # arming step as a hard acceleration (see the rework note at the top of this file).
    self._update_range_assist(range_assist, measurement_update, t_now, vision_closing, vision_assist)

    if measurement_update and self.cnt > 0:
      self.kf.update(self.vLead)

    self.vLeadK = float(self.kf.x[SPEED][0])
    self.aLeadK = float(self.kf.x[ACCEL][0])

    if measurement_update:
      # Learn if constant acceleration
      if abs(self.aLeadK) < 0.5:
        self.aLeadTau.x = min(max(self.aLeadTau.x, 1e-2) * 1.1, _LEAD_ACCEL_TAU)
      else:
        self.aLeadTau.update(0.0)

      # Track the moving -> stopped transition. Only sustained runs count, so one noisy
      # speed sample can neither arm nor trip the detector.
      if self.vLead > ADJACENT_STOP_MOVING_V:
        self.moving_frames += 1
        self.rest_frames = 0
        if self.moving_frames >= ADJACENT_STOP_MOVING_FRAMES:
          self.seen_moving = True
      elif abs(self.vLead) < ADJACENT_STOP_REST_V:
        self.moving_frames = 0
        self.rest_frames += 1
      else:
        # coasting between the two bands: hold state, restart both runs
        self.moving_frames = 0
        self.rest_frames = 0

      self.cnt += 1

  def _clear_range_assist(self) -> None:
    self.range_assist_active = False
    self.vision_assist_count = 0
    self.vision_assist_early = False
    self.range_assist_arm_count = 0
    self.range_assist_rail_count = 0
    self.range_assist_correction = 0.0

  def _update_range_assist(self, enabled: bool, measurement_update: bool, t_now: float,
                           vision_closing: float | None = None, vision_assist: bool = False) -> None:
    """One-sided correction of the native vRel toward the range-derived rate. D-053, TEST.

    Sets self.range_assist_correction to m/s of EXTRA closing, always >= 0: this may only make the
    lead look slower than U11 says, never faster. Every rejection path clears it outright, so the
    fallback is the shipped U11 behaviour and never a half-applied correction. Understating
    closing still brakes (D-041); that is why failing back to native is the safe direction here.

    Deliberately NOT in scope: which track is selected. track_matches_vision and
    vision_track_probability keep scoring the native self.vRel, so this can change what is
    reported about the chosen lead but never change the choice.
    """
    last_t = self._range_assist_last_t
    self._range_assist_last_t = float(t_now)

    if not enabled:
      self._clear_range_assist()
      return

    if not measurement_update:
      # TWO different things land here and they need OPPOSITE handling. Both arrive as
      # measurement_update False because RadarD collapses them into one bit on Bosch-A
      # (measured = pt.measured and radar_fresh), so they are separated here by the clock.
      #
      #   * A DUPLICATE radard cycle. radard runs at the 20 Hz model rate over a 14.35 Hz radar,
      #     so ~1 cycle in 4 carries no new liveTracks message: t_now has not advanced, dRel/yRel/
      #     vRel are the same values as last cycle, the range history is not appended to and the
      #     lead KF is not stepped. Nothing was re-measured, so there is nothing to re-decide --
      #     HOLD. Clearing instead would reset the arm count roughly every fourth cycle, so the
      #     assist could never reach RANGE_VREL_ASSIST_ARM_UPDATES on a car at all, and once
      #     armed the published vRel would flicker between corrected and native at ~5 Hz.
      #   * A COAST. The parser keeps publishing the object with measured False, so a new message
      #     DOES arrive and t_now advances. A coast also refreshes last_seen_nanos, so it is not
      #     bounded by BOSCH_A_STALE_S and 121.8 s of continuous coasting has been measured
      #     (D-052). Holding a correction across that is unbounded staleness -- CLEAR.
      #
      # If the two are ever given separate bits at the call site, split this on those bits rather
      # than on the clock; the clock comparison is standing in for information RadarD discarded.
      if last_t == float(t_now):
        return
      self._clear_range_assist()
      return

    if not (self.measured and self.vRelRangeFresh):
      self._clear_range_assist()
      return

    vis_ok = (VISION_ASSIST_GEOMETRY or vision_assist) and vision_closing is not None
    bypass = False
    if self.dRel < RANGE_VREL_ASSIST_MIN_D_REL_M:
      self._clear_range_assist()
      return
    if abs(self.yRel) > RANGE_VREL_ASSIST_MAX_ABS_Y_REL_M:
      if not (vis_ok and np.degrees(np.arctan2(abs(self.yRel), self.dRel)) <= VISION_ASSIST_MAX_AZIMUTH_DEG):
        self._clear_range_assist()
        return
      bypass = True

    # Inside Track, vLead is vRel plus the delay-aligned ego speed, so this recovers that ego speed.
    v_ego_aligned = self.vLead - self.vRel
    if v_ego_aligned < RANGE_VREL_ASSIST_MIN_V_EGO_MPS:
      self._clear_range_assist()
      return

    # Quantized U11 sits exactly on the rail value, so half a step of tolerance is exact.
    on_rail = self.vRel <= BOSCH_A_U11_LOW_RAIL_MPS + BOSCH_A_DIRECT_VREL_SCALE_MPS / 2
    rail_fast = RANGE_VREL_RAIL_FAST and on_rail
    # Clamped: a rail minimum above the deque length could never be reached.
    self._range_long_min_samples = (min(RANGE_VREL_RAIL_LONG_MIN_SAMPLES, RANGE_VREL_LONG_SAMPLES)
                                    if rail_fast else RANGE_VREL_LONG_SAMPLES)
    min_span = RANGE_VREL_RAIL_LONG_MIN_SPAN_S if rail_fast else RANGE_VREL_LONG_MIN_SPAN_S
    # Short long-history: only the corroborated rail arm may count (see below).
    short_long_hist = len(self.range_hist_long) < RANGE_VREL_LONG_SAMPLES
    long_ok = (self._fit_long_range() and min_span <= self.vRelRangeLongSpan <= RANGE_VREL_LONG_MAX_SPAN_S and
               self.vRelRangeLongResidual <= RANGE_VREL_ASSIST_MAX_LONG_RESIDUAL_M)
    short_only = False
    if not long_ok:
      if not (vis_ok and VISION_ASSIST_SHORT_ONLY):
        self._clear_range_assist()
        return
      short_only = True
    long_rate = self.vRelRange if short_only else self.vRelRangeLong
    if v_ego_aligned + long_rate < -RANGE_VREL_ASSIST_MAX_BACKWARD_LEAD_MPS:
      self._clear_range_assist()
      return

    # Positive means the range says MORE closing than U11 -- the only direction acted on, and the
    # same sign convention as "understatement" in tools/bosch_a_vrel_shadow_report.py. Both fits
    # must agree, so the smaller disagreement is the one that counts.
    disagreement = min(self.vRel - self.vRelRange, self.vRel - long_rate)
    # On the U11 rail only the long fit decides arming and holding; the size below stays the smaller.
    decision = self.vRel - long_rate if on_rail else disagreement
    size = disagreement
    if rail_fast:
      # Rail fast path: sized by the mean of the two fits (never beyond the more-closing one).
      if RANGE_VREL_RAIL_SIZE_MEAN:
        size = 0.5 * ((self.vRel - self.vRelRange) + (self.vRel - long_rate))
      if disagreement >= RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS:
        self.range_assist_rail_count += 1
      else:
        self.range_assist_rail_count = 0

    if self.range_assist_active:
      # Hysteresis: hold while ANY closing disagreement remains, so the correction decays
      # continuously to zero as U11 catches up rather than stepping off at the arming threshold.
      if decision <= 0.0:
        self._clear_range_assist()
        return
      if bypass or short_only:
        # Held only because vision corroborates: the plain gates would have cleared on this update.
        self.vision_assist_early = True
      if self.vision_assist_early:
        # Armed only because vision corroborated. Keep running the plain arm rule; until it would
        # have armed on its own the correction is vision-bounded, and it is zero whenever vision
        # stops corroborating, which is what the plain rule would publish at that moment.
        if bypass or short_only or decision < RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS:
          self.range_assist_arm_count = 0
        elif not short_long_hist:
          self.range_assist_arm_count += 1
        if not (bypass or short_only) and (self.range_assist_arm_count >= RANGE_VREL_ASSIST_ARM_UPDATES or
                                           (rail_fast and self.range_assist_rail_count >= RANGE_VREL_RAIL_ARM_UPDATES)):
          self.vision_assist_early = False
        elif not vis_ok:
          self.range_assist_correction = 0.0
          return
    else:
      if decision < RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS:
        self.range_assist_arm_count = 0
        self.range_assist_correction = 0.0
        return
      if not short_long_hist or short_only:
        self.range_assist_arm_count += 1
      rail_armed = rail_fast and self.range_assist_rail_count >= RANGE_VREL_RAIL_ARM_UPDATES
      arm_needed = RANGE_VREL_ASSIST_ARM_UPDATES
      if vis_ok:
        self.vision_assist_count += 1
        if self.vision_assist_count >= self.range_assist_arm_count:
          arm_needed = min(arm_needed, VISION_ASSIST_ARM_UPDATES)
      else:
        self.vision_assist_count = 0
      if self.range_assist_arm_count < arm_needed and not rail_armed:
        self.range_assist_correction = 0.0
        return
      self.range_assist_active = True
      self.vision_assist_early = bypass or short_only or (self.range_assist_arm_count < RANGE_VREL_ASSIST_ARM_UPDATES and
                                                          not rail_armed)

    # Active with a negative smaller disagreement (only possible on the rail) publishes zero while
    # staying armed. The last bound keeps a corrected vLead from being published below zero.
    correction = float(min(max(size, 0.0), RANGE_VREL_ASSIST_MAX_CORRECTION_MPS, max(self.vLead, 0.0)))
    if self.vision_assist_early:
      # Never claim more closing than vision corroborates plus the margin: published vRel >= -(closing + margin).
      correction = min(correction, max(self.vRel + vision_closing + VISION_ASSIST_CLOSING_MARGIN_MPS, 0.0))
    self.range_assist_correction = correction

  def _fit_long_range(self) -> bool:
    """Plain LSQ over range_hist_long. Sets vRelRangeLong (slope, m/s), vRelRangeLongResidual (RMS,
    m) and vRelRangeLongSpan (s) and returns True, or sets all three to NaN and returns False when
    the history is not full or its timestamps are degenerate."""
    self.vRelRangeLong = self.vRelRangeLongResidual = self.vRelRangeLongSpan = float('nan')
    if len(self.range_hist_long) < self._range_long_min_samples:
      return False
    hist = np.array(self.range_hist_long, dtype=np.float64)
    ts = hist[:, 0] - hist[-1, 0]
    ds = hist[:, 1]
    t_bar = ts.mean()
    d_bar = ds.mean()
    sxx = float(((ts - t_bar) ** 2).sum())
    if not sxx > 0.0:
      return False
    slope = float(((ts - t_bar) * (ds - d_bar)).sum() / sxx)
    residual = ds - (d_bar + slope * (ts - t_bar))
    self.vRelRangeLong = slope
    self.vRelRangeLongResidual = float(np.sqrt((residual ** 2).mean()))
    self.vRelRangeLongSpan = float(ts[-1] - ts[0])
    return True

  def young_flat_range_vrel_floor(self, t_now: float) -> float | None:
    """YOUNG_TRACK_FLAT_RANGE_BOUND: the least vRel (most closing) this young track's flat range supports, else None."""
    if not (t_now - self.t_first <= YOUNG_TRACK_MAX_AGE_S) or len(self.young_range_hist) < YOUNG_TRACK_MIN_SAMPLES:
      return None
    a = np.array(self.young_range_hist, dtype=np.float64)
    ts = a[:, 0] - a[-1, 0]
    if ts[-1] - ts[0] < YOUNG_TRACK_MIN_SPAN_S:
      return None
    slope, icpt = np.polyfit(ts, a[:, 1], 1)
    if abs(slope) > YOUNG_TRACK_FLAT_MAX_RATE:
      return None
    resid = a[:, 1] - (icpt + slope * ts)
    rms = float(np.sqrt((resid ** 2).mean()))
    if rms <= YOUNG_TRACK_MAX_RESIDUAL_M:
      return float(slope) - YOUNG_TRACK_FLAT_MARGIN
    if rms > YOUNG_TRACK_NOISY_MAX_RESIDUAL_M:
      return None
    # Noisy range: widen the floor by the slope's standard error.
    se = float(np.sqrt((resid ** 2).sum() / (len(ts) - 2) / ((ts - ts.mean()) ** 2).sum()))
    return float(slope) - YOUNG_TRACK_FLAT_MARGIN - YOUNG_TRACK_NOISY_SE_K * se

  def get_RadarState(self, model_prob: float = 0.0, shadow_telemetry: bool = False):
    """`shadow_telemetry` is opt-in because this dict is assigned to TWO different capnp structs:
    log.capnp LeadData (radarState.leadOne/leadTwo) and custom.capnp LeadData
    (starpilotRadarState.leadLeft/leadRight). Only the former carries the shadow fields, and only
    the followed lead should: adjacent tracks sit at up to 17-23 deg azimuth, where a range
    derivative is radial rate and NOT longitudinal velocity, so publishing it there would be
    misleading as well as a schema error."""
    # D-053. The KF runs on the native speed, so the correction is applied here, once, to all three
    # published speeds: vRel and vLead (long_mpc) and vLeadK, keeping the published lead
    # self-consistent. aLeadK and aLeadTau stay
    # native on purpose -- see the rework note at the top of this file. The correction is zero
    # unless RadarD armed the assist for this track, so every other caller is unchanged. Note
    # self.vRel and self.vLead themselves stay NATIVE -- the adjacent-lane detectors and the vision
    # association read those -- and so does self.vLeadK, so nothing applies the correction twice.
    correction = float(self.range_assist_correction)
    state = {
      "dRel": float(self.dRel),
      "yRel": float(self.yRel),
      "vRel": float(self.vRel) - correction,
      "vLead": float(self.vLead) - correction,
      "vLeadK": float(self.vLeadK) - correction,
      "aLeadK": float(self.aLeadK),
      "aLeadTau": float(self.aLeadTau.x),
      "status": True,
      "fcw": self.is_potential_fcw(model_prob),
      "modelProb": model_prob,
      "radar": True,
      "radarTrackId": self.identifier,
    }
    if shadow_telemetry:
      state["vRelRangeDerived"] = float(self.vRelRange)
      state["measuredRadar"] = bool(self.measured)
    return state

  def potential_adjacent_lead(self, left: bool, standstill: bool, model_data: capnp._DynamicStructReader):
    if standstill or self.vLead < 1 or self.leadTrackID == self.identifier:
      return False

    if left:
      left_lane = np.interp(self.dRel, model_data.laneLines[1].x, model_data.laneLines[1].y)
      return -self.yRel < left_lane
    right_lane = np.interp(self.dRel, model_data.laneLines[2].x, model_data.laneLines[2].y)
    return -self.yRel > right_lane

  def is_adjacent_stopped(self, model_data: capnp._DynamicStructReader):
    """A neighbouring-lane vehicle that was seen moving and has now come to rest.

    Deliberately not potential_adjacent_lead, which is moving-target-only and would have
    to be loosened to "anything slow" to catch these. Lane geometry mirrors it (model
    y == -yRel, laneLines[1] left boundary and [2] right), plus an outer bound so
    roadside returns past the neighbouring lane don't qualify.
    """
    if not (self.seen_moving and self.rest_frames >= ADJACENT_STOP_REST_FRAMES):
      return False

    if self.leadTrackID == self.identifier:
      return False

    return self.in_adjacent_lane(model_data)

  def in_adjacent_lane(self, model_data: capnp._DynamicStructReader):
    """Lane geometry only, no deceleration history — also used to spot a queue ahead."""
    if not (ADJACENT_STOP_MIN_Y < abs(self.yRel) < ADJACENT_STOP_MAX_Y):
      return False

    if not (0.0 < self.dRel < ADJACENT_STOP_MAX_D):
      return False

    model_y = -self.yRel
    left_lane = np.interp(self.dRel, model_data.laneLines[1].x, model_data.laneLines[1].y)
    right_lane = np.interp(self.dRel, model_data.laneLines[2].x, model_data.laneLines[2].y)
    return bool(model_y < left_lane or model_y > right_lane)

  def potential_low_speed_lead(self, v_ego: float):
    # stop for stuff in front of you and low speed, even without model confirmation
    # Radar points closer than 0.75, are almost always glitches on toyota radars
    return abs(self.yRel) < 1.0 and (v_ego < V_EGO_STATIONARY) and (0.75 < self.dRel < 25)

  def is_potential_fcw(self, model_prob: float):
    return model_prob > .9

  def __str__(self):
    ret = f"x: {self.dRel:4.1f}  y: {self.yRel:4.1f}  v: {self.vRel:4.1f}  a: {self.aLeadK:4.1f}"
    return ret


def laplacian_pdf(x: float, mu: float, b: float):
  b = max(b, 1e-4)
  return math.exp(-abs(x-mu)/b)


def vision_track_probability(track: Track, lead: capnp._DynamicStructReader, v_ego: float) -> float:
  offset_vision_dist = lead.x[0] - RADAR_TO_CAMERA
  prob_d = laplacian_pdf(track.dRel, offset_vision_dist, lead.xStd[0])
  prob_y = laplacian_pdf(track.yRel, -lead.y[0], lead.yStd[0])
  prob_v = laplacian_pdf(track.vRel + v_ego, lead.v[0], lead.vStd[0])
  return prob_d * prob_y * prob_v


def g90_radar_lead_lateral_sane(track: Track) -> bool:
  # The G90 extended radar channels can report close side ghosts in tight turns.
  # Keep the gate tight at close range, then widen gradually with distance.
  max_y = min(6.0, 1.5 + 0.08 * max(track.dRel, 0.0))
  return abs(track.yRel) <= max_y


def g90_low_speed_radar_lead_sane(track: Track, v_ego: float) -> bool:
  return (track.cnt >= 3 and v_ego < 3.0 and
          0.75 < track.dRel < G90_RADAR_LOW_SPEED_MAX_DIST and
          abs(track.yRel) < G90_RADAR_LOW_SPEED_MAX_Y)


def honda_bosch_a_low_speed_radar_lead_sane(track: Track, v_ego: float) -> bool:
  """Require a few real Bosch sweeps before a radar-only low-speed takeover."""
  return track.cnt >= HONDA_BOSCH_A_LOW_SPEED_MIN_COUNT and track.potential_low_speed_lead(v_ego)


def track_matches_vision(track: Track, lead: capnp._DynamicStructReader, v_ego: float, *,
                         dist_scale: float, dist_floor: float, vel_limit: float,
                         y_std_scale: float, y_floor: float) -> bool:
  offset_vision_dist = lead.x[0] - RADAR_TO_CAMERA
  dist_sane = abs(track.dRel - offset_vision_dist) < max(abs(offset_vision_dist) * dist_scale, dist_floor)
  # NOTE: the `or` makes this check inert for any lead above 3 m/s, i.e. essentially always at road
  # speed -- a radar track whose velocity disagrees with vision by any amount still passes. Removing
  # it was measured on 000001fb (6 segments, 5390 radar-lead frames with a confident vision lead):
  # only 37 frames (0.69%) would begin failing, and 0 on 000001fd. But failing here drops the radar
  # match and leaves a vision-only lead, and on exactly those frames radar and vision disagree by
  # >10 m/s with no evidence vision is the correct one -- on 000001fe 35:36 vision missed a real 9 m
  # closure that radar tracked correctly. Deleting radar leads is the 000001f9 failure mode, so this
  # is left as-is deliberately: inert, but inert in the safe direction. Do not "fix" it without
  # first establishing which sensor is right on the frames it would start rejecting.
  vel_sane = (abs(track.vRel + v_ego - lead.v[0]) < vel_limit) or (v_ego + track.vRel > 3)
  lat_sane = abs(track.yRel + lead.y[0]) < max(y_floor, y_std_scale * max(float(lead.yStd[0]), 0.2))
  return dist_sane and vel_sane and lat_sane


def match_vision_to_track(v_ego: float, lead: capnp._DynamicStructReader, model_data: capnp._DynamicStructReader, tracks: dict[int, Track],
                          starpilot_toggles: SimpleNamespace, g90_radar_filter: bool = False,
                          preferred_track_id: int = -1):
  # No lane-change side filter here. StarPilot's HumanLaneChanges dropped every track on the far side
  # of 0 m (left change: yRel <= 0) during laneChangeStarting. It never changed WHICH car was followed
  # -- this function only pairs a radar track with the vision lead, which must also agree laterally --
  # it only took the radar away from it. Route 00000293 (owner-bookmarked, replay-reproduced): 10:49
  # the new lane's car (track 61) crossed to y -0.2..-0.4 as we arrived and went vision-only through
  # the -3.5 brake; 29:13-29:16 track 12 sat at y +0.2..+1.2 on a curve, vision put it 65-73 m away
  # while radar had 53-62 m, the +0.55 merge push held, and radar's return at 51.6 m forced -1.4.
  # D-041/D-042: a gate that can only delete radar points is removed rather than tuned.

  if g90_radar_filter:
    tracks = {k: v for k, v in tracks.items() if g90_radar_lead_lateral_sane(v)}

  if not tracks:
    return None

  track = max(tracks.values(), key=lambda candidate: vision_track_probability(candidate, lead, v_ego))

  # if no 'sane' match is found return -1
  # stationary radar points can be false positives
  if track_matches_vision(track, lead, v_ego,
                          dist_scale=0.25, dist_floor=5.0,
                          vel_limit=10.0, y_std_scale=1.0, y_floor=1.0):
    return track

  # Some vehicles intermittently drop a good radar match on large leads (semis are
  # a common offender). If the same track is still present and only missed the
  # strict vision gate by a small margin, keep the previous radar match instead of
  # oscillating between radar and vision estimates.
  preferred_track = tracks.get(preferred_track_id)
  if preferred_track is not None and preferred_track.cnt >= 3:
    if track_matches_vision(preferred_track, lead, v_ego,
                            dist_scale=0.40, dist_floor=8.0,
                            vel_limit=13.0, y_std_scale=2.0, y_floor=1.5):
      return preferred_track
  return None


def get_RadarState_from_vision(lead_msg: capnp._DynamicStructReader, v_ego: float, model_v_ego: float, model_prob: float):
  prev_aLeadK = getattr(get_RadarState_from_vision, "prev_aLeadK", 0.0)
  blended_aLeadK = 0.8 * float(lead_msg.a[0]) + 0.2 * prev_aLeadK
  get_RadarState_from_vision.prev_aLeadK = blended_aLeadK
  return {
    "dRel": float(lead_msg.x[0] - RADAR_TO_CAMERA),
    "yRel": float(-lead_msg.y[0]),
    "vRel": float(lead_msg.v[0] - model_v_ego),
    "vLead": float(v_ego + (lead_msg.v[0] - model_v_ego)),
    "vLeadK": float(v_ego + (lead_msg.v[0] - model_v_ego)),
    "aLeadK": blended_aLeadK,
    "aLeadTau": 0.3,
    "fcw": False,
    "modelProb": float(model_prob),
    "status": True,
    "radar": False,
    "radarTrackId": -1,
    # A vision lead has no radar range channel to derive a velocity from, and is never a radar
    # measurement. Explicit so the telemetry is not read as "range LSQ said zero".
    "vRelRangeDerived": float('nan'),
    "measuredRadar": False,
  }



def get_lead(v_ego: float, ready: bool, tracks: dict[int, Track], lead_msg: capnp._DynamicStructReader,
             model_v_ego: float, model_data: capnp._DynamicStructReader, standstill: bool,
             starpilot_plan: capnp._DynamicStructReader, starpilot_toggles: SimpleNamespace,
             low_speed_override: bool = True, g90_radar_filter: bool = False, lead_prob: float | None = None,
             preferred_track_id: int = -1, honda_bosch_a_radar: bool = False) -> dict[str, Any]:
  lead_detection_probability = float(getattr(starpilot_toggles, "lead_detection_probability", 0.35))
  filtered_lead_prob = float(lead_msg.prob if lead_prob is None else lead_prob)

  # Determine leads, this is where the essential logic happens
  if len(tracks) > 0 and ready and filtered_lead_prob > lead_detection_probability:
    track = match_vision_to_track(v_ego, lead_msg, model_data, tracks, starpilot_toggles, g90_radar_filter,
                                  preferred_track_id=preferred_track_id)
  else:
    track = None

  lead_dict = {'status': False}
  if track is not None:
    lead_dict = track.get_RadarState(filtered_lead_prob, shadow_telemetry=True)
  elif (track is None) and ready and (filtered_lead_prob > lead_detection_probability):
    lead_dict = get_RadarState_from_vision(lead_msg, v_ego, model_v_ego, filtered_lead_prob)

  if low_speed_override:
    if g90_radar_filter:
      low_speed_tracks = [c for c in tracks.values() if g90_low_speed_radar_lead_sane(c, v_ego)]
    elif honda_bosch_a_radar:
      low_speed_tracks = [c for c in tracks.values() if honda_bosch_a_low_speed_radar_lead_sane(c, v_ego)]
    else:
      low_speed_tracks = [c for c in tracks.values() if c.potential_low_speed_lead(v_ego)]

    model_lead_available = ready and filtered_lead_prob > lead_detection_probability

    # Keep a previously selected Bosch radar track through ordinary model-probability fluctuations
    # when it is still coherent. If the model has a valid lead, the old track must still agree with
    # that lead; no model lead leaves the mature radar track eligible for continuity.
    if honda_bosch_a_radar:
      preferred_track = tracks.get(preferred_track_id)
      if (preferred_track is not None and honda_bosch_a_low_speed_radar_lead_sane(preferred_track, v_ego)):
        preferred_matches_model = (not model_lead_available or
                                   track_matches_vision(preferred_track, lead_msg, v_ego,
                                                        dist_scale=0.25, dist_floor=5.0,
                                                        vel_limit=10.0, y_std_scale=1.0, y_floor=1.0))
        preferred_is_current = (not lead_dict.get('status', False) or
                                lead_dict.get('radarTrackId', -1) == preferred_track_id or
                                (lead_dict.get('status', False) and not lead_dict.get('radar', False)))
        if preferred_is_current and preferred_matches_model:
          lead_dict = preferred_track.get_RadarState(filtered_lead_prob, shadow_telemetry=True)

    def candidate_is_established(candidate: Track) -> bool:
      if not honda_bosch_a_radar:
        return True
      if candidate.cnt < HONDA_BOSCH_A_LOW_SPEED_MIN_COUNT:
        return False
      if not lead_dict.get('status', False):
        # A mature centered Bosch point may provide the radar-only low-speed lead.
        return True
      if lead_dict.get('radarTrackId', -1) == candidate.identifier:
        return True
      # Do not replace an established lead with an unrelated closer point when there is no model
      # evidence to arbitrate them. A different candidate may take over only after it agrees with
      # the available model lead; radar-only takeover remains possible when lead_dict is invalid.
      return (model_lead_available and
              track_matches_vision(candidate, lead_msg, v_ego,
                                   dist_scale=0.25, dist_floor=5.0,
                                   vel_limit=10.0, y_std_scale=1.0, y_floor=1.0))

    low_speed_tracks = [c for c in low_speed_tracks if candidate_is_established(c)]
    if len(low_speed_tracks) > 0:
      closest_track = min(low_speed_tracks, key=lambda c: c.dRel)

      # Only choose new track if it is actually closer than the previous one
      if (not lead_dict['status']) or (closest_track.dRel < lead_dict['dRel']):
        lead_dict = closest_track.get_RadarState(shadow_telemetry=True)

  for track in tracks.values():
    track.leadTrackID = lead_dict.get('radarTrackId', -1)

  if 'dRel' in lead_dict:
    lead_dict['dRel'] -= starpilot_plan.increasedStoppedDistance

  return lead_dict


def get_adjacent_lead(tracks: dict[int, Track], standstill: bool, model_data: capnp._DynamicStructReader, left: bool = True) -> dict[str, Any]:
  lead_dict = {'status': False}

  adjacent_tracks = [c for c in tracks.values() if c.potential_adjacent_lead(left, standstill, model_data)]
  if len(adjacent_tracks) > 0:
    closest_track = min(adjacent_tracks, key=lambda c: c.dRel)
    lead_dict = closest_track.get_RadarState()

  return lead_dict


def get_adjacent_stopped(tracks: dict[int, Track], model_data: capnp._DynamicStructReader) -> dict[str, Any]:
  """Stop-line hint: a vehicle that decelerated to a stop in a neighbouring lane.

  Takes the FARTHEST qualifying vehicle, then drops the hint entirely if a queue reaches
  past it. Cars already stopped when we acquire them never show the moving -> stopped
  transition, so the qualifying set is biased toward the back of a line; without this the
  hint marks a mid-queue bumper and stops us short of the bar.
  """
  if len(model_data.laneLines) < 4:
    return {'status': False}

  candidates = [c for c in tracks.values() if c.is_adjacent_stopped(model_data)]
  if not candidates:
    return {'status': False}

  furthest = max(candidates, key=lambda c: c.dRel)
  for c in tracks.values():
    if (c.dRel > furthest.dRel + ADJACENT_STOP_QUEUE_GAP_M and
        abs(c.vLead) < ADJACENT_STOP_REST_V and
        c.in_adjacent_lane(model_data)):
      return {'status': False}
  return {
    'status': True,
    'dRel': float(furthest.dRel),
    'yRel': float(furthest.yRel),
    'radarTrackId': int(furthest.identifier),
  }


class RadarD:
  def __init__(self, radar_ts: float = DT_MDL, delay: float = 0.0, g90_radar_filter: bool = False,
               honda_bosch_a_radar: bool = False):
    self.current_time = 0.0

    self.tracks: dict[int, Track] = {}
    self.honda_bosch_a_radar = honda_bosch_a_radar
    self.young_flat_bound_count = 0
    # The lead KF consumes Bosch measurements at the physical radar cadence. Lead probability
    # filters, however, consume modelV2 leads every model cycle and must retain model-loop timing.
    kf_dt = HONDA_BOSCH_A_RADAR_TS if self.honda_bosch_a_radar else radar_ts
    self.kalman_params = KalmanParams(kf_dt)
    self.g90_radar_filter = g90_radar_filter
    lead_prob_dt = DT_MDL if self.honda_bosch_a_radar else radar_ts
    self.lead_prob_filters = [FirstOrderFilter(0.0, 0.2, lead_prob_dt) for _ in range(2)]
    self.prev_lead_track_ids = [-1, -1]
    self.preferred_stale_track_ids = [-1, -1]
    self.preferred_challenger_stale_counts = [0, 0]
    self.preferred_gross_distance_stale_counts = [0, 0]

    self.v_ego = 0.0
    self.v_ego_hist = deque([0.0], maxlen=int(round(delay / DT_MDL)) + 1)
    self.last_v_ego_frame = -1
    self._last_tracks_frame = -1

    self.radar_state: capnp._DynamicStructBuilder | None = None
    self.radar_state_valid = False

    self.ready = False

    self.starpilot_radar_state = custom.StarPilotRadarState.new_message()
    self.starpilot_toggles = get_starpilot_toggles()

  def _range_vrel_assist_enabled(self) -> bool:
    """D-053 assist switch, built in for Bosch-A (was the RangeDerivedVrel param). Replays flip RANGE_VREL_ASSIST."""
    return RANGE_VREL_ASSIST

  def _reset_preferred_stale_evidence(self, lead_index: int, track_id: int = -1) -> None:
    self.preferred_stale_track_ids[lead_index] = track_id
    self.preferred_challenger_stale_counts[lead_index] = 0
    self.preferred_gross_distance_stale_counts[lead_index] = 0

  def _update_honda_bosch_a_preferred_staleness(self, lead_index: int, lead: capnp._DynamicStructReader,
                                               lead_prob: float) -> None:
    if not self.honda_bosch_a_radar:
      return

    preferred_id = self.prev_lead_track_ids[lead_index]
    if self.preferred_stale_track_ids[lead_index] != preferred_id:
      self._reset_preferred_stale_evidence(lead_index, preferred_id)

    lead_detection_probability = float(getattr(self.starpilot_toggles, "lead_detection_probability", 0.35))
    preferred_track = self.tracks.get(preferred_id)
    if preferred_id < 0 or preferred_track is None or not self.ready or lead_prob <= lead_detection_probability:
      self._reset_preferred_stale_evidence(lead_index, preferred_id)
      return

    strict_match = track_matches_vision(preferred_track, lead, self.v_ego,
                                        dist_scale=0.25, dist_floor=5.0,
                                        vel_limit=10.0, y_std_scale=1.0, y_floor=1.0)
    relaxed_match = track_matches_vision(preferred_track, lead, self.v_ego,
                                         dist_scale=0.40, dist_floor=8.0,
                                         vel_limit=13.0, y_std_scale=2.0, y_floor=1.5)

    # Arm A: a preferred track that no longer passes continuity may be stale when another live
    # track has a better association score. Clearing preference never selects that challenger;
    # the unchanged strict match path below remains the only way it can become a radar lead.
    if relaxed_match:
      self.preferred_challenger_stale_counts[lead_index] = 0
    else:
      best_track = max(self.tracks.values(), key=lambda candidate: vision_track_probability(candidate, lead, self.v_ego))
      preferred_score = vision_track_probability(preferred_track, lead, self.v_ego)
      best_score = vision_track_probability(best_track, lead, self.v_ego)
      if best_track.identifier != preferred_id and best_score > preferred_score:
        self.preferred_challenger_stale_counts[lead_index] += 1
      else:
        self.preferred_challenger_stale_counts[lead_index] = 0

    # Arm B: gross absolute range disagreement is independent evidence of staleness, but a strict
    # match is authoritative and resets the streak even when model uncertainty permits >25 m error.
    distance_mismatch = abs(preferred_track.dRel - (lead.x[0] - RADAR_TO_CAMERA))
    if strict_match:
      self.preferred_gross_distance_stale_counts[lead_index] = 0
    elif distance_mismatch > HONDA_BOSCH_A_GROSS_DISTANCE_M:
      self.preferred_gross_distance_stale_counts[lead_index] += 1
    else:
      self.preferred_gross_distance_stale_counts[lead_index] = 0

    challenger_stale = self.preferred_challenger_stale_counts[lead_index] >= HONDA_BOSCH_A_CHALLENGER_STALE_CYCLES
    distance_stale = self.preferred_gross_distance_stale_counts[lead_index] >= HONDA_BOSCH_A_GROSS_DISTANCE_STALE_CYCLES
    if challenger_stale or distance_stale:
      self.prev_lead_track_ids[lead_index] = -1
      self._reset_preferred_stale_evidence(lead_index)

  def update(self, sm: messaging.SubMaster, rr: car.RadarData):
    self.ready = sm.seen['modelV2']
    self.current_time = 1e-9 * max(sm.logMonoTime.values())

    if sm.recv_frame['carState'] != self.last_v_ego_frame:
      self.v_ego = sm['carState'].vEgo
      self.v_ego_hist.append(self.v_ego)
      self.last_v_ego_frame = sm.recv_frame['carState']

    radar_fresh = True
    if self.honda_bosch_a_radar:
      radar_fresh = sm.recv_frame['liveTracks'] != self._last_tracks_frame
      self._last_tracks_frame = sm.recv_frame['liveTracks']

    ar_pts = {pt.trackId: [pt.dRel, pt.yRel, pt.vRel, pt.measured] for pt in rr.points}

    # D-053. Bosch-A only, and only for the tracks that were the lead on the previous cycle.
    # prev_lead_track_ids is the authoritative "which track is the lead" state; Track.leadTrackID
    # is NOT -- get_lead stamps it on every track and is called twice, so it ends up holding
    # leadTwo's id for all of them. Restricting the assist to the two lead tracks keeps the
    # correction out of track_matches_vision / vision_track_probability scoring for everything
    # else, which is what makes this a reporting change rather than an association change.
    range_assist_enabled = self.honda_bosch_a_radar and self._range_vrel_assist_enabled()
    lead_track_ids = {i for i in self.prev_lead_track_ids if i >= 0} if range_assist_enabled else set()
    vision_assist = range_assist_enabled and (VISION_ASSIST_GEOMETRY or RANGE_VISION_ASSIST)

    # *** remove missing points from meta data ***
    for ids in list(self.tracks.keys()):
      if ids not in ar_pts:
        self.tracks.pop(ids, None)

    # *** compute the tracks ***
    for ids, rpt in ar_pts.items():
      # align v_ego by a fixed time to align it with the radar measurement
      v_lead = rpt[2] + self.v_ego_hist[0]

      # create the track if it doesn't exist or it's a new track
      if ids not in self.tracks:
        self.tracks[ids] = Track(ids, v_lead, self.kalman_params)
      measured = rpt[3] if not self.honda_bosch_a_radar else bool(rpt[3] and radar_fresh)
      # Non-Bosch sources retain the historical per-model-cycle update semantics. Only Civic Bosch
      # suppresses duplicate measurement updates when liveTracks has not advanced.
      measurement_update = True if not self.honda_bosch_a_radar else measured
      vis_closing = None
      if vision_assist and ids in lead_track_ids and len(sm['modelV2'].leadsV3):
        vis_closing = vision_assist_closing(rpt[0], rpt[1], sm['modelV2'].leadsV3[0], self.v_ego)
      self.tracks[ids].update(rpt[0], rpt[1], rpt[2], v_lead, measured, measurement_update,
                              t_now=sm.logMonoTime['liveTracks'] * 1e-9,
                              range_assist=ids in lead_track_ids, vision_closing=vis_closing,
                              vision_assist=vision_assist)

    # *** publish radarState ***
    self.radar_state_valid = sm.all_checks()
    self.radar_state = log.RadarState.new_message()
    self.radar_state.mdMonoTime = sm.logMonoTime['modelV2']
    self.radar_state.radarErrors = rr.errors
    self.radar_state.carStateMonoTime = sm.logMonoTime['carState']

    self.starpilot_radar_state = custom.StarPilotRadarState.new_message()

    if len(sm['modelV2'].velocity.x):
      model_v_ego = sm['modelV2'].velocity.x[0]
    else:
      model_v_ego = self.v_ego

    leads_v3 = sm['modelV2'].leadsV3
    if len(leads_v3) > 1:
      for i in range(2):
        lead_prob = float(leads_v3[i].prob)
        if lead_prob > self.lead_prob_filters[i].x:
          self.lead_prob_filters[i].x = lead_prob
        else:
          self.lead_prob_filters[i].update(lead_prob)

        self._update_honda_bosch_a_preferred_staleness(i, leads_v3[i], self.lead_prob_filters[i].x)

      self.radar_state.leadOne = get_lead(self.v_ego, self.ready, self.tracks, leads_v3[0], model_v_ego, sm['modelV2'],
                                          sm['carState'].standstill, sm['starpilotPlan'], self.starpilot_toggles, low_speed_override=True,
                                          g90_radar_filter=self.g90_radar_filter, lead_prob=self.lead_prob_filters[0].x,
                                          preferred_track_id=self.prev_lead_track_ids[0],
                                          honda_bosch_a_radar=self.honda_bosch_a_radar)
      self.radar_state.leadTwo = get_lead(self.v_ego, self.ready, self.tracks, leads_v3[1], model_v_ego, sm['modelV2'],
                                          sm['carState'].standstill, sm['starpilotPlan'], self.starpilot_toggles, low_speed_override=False,
                                          g90_radar_filter=self.g90_radar_filter, lead_prob=self.lead_prob_filters[1].x,
                                          preferred_track_id=self.prev_lead_track_ids[1],
                                          honda_bosch_a_radar=self.honda_bosch_a_radar)

      if YOUNG_TRACK_FLAT_RANGE_BOUND and self.honda_bosch_a_radar:
        t_live = sm.logMonoTime['liveTracks'] * 1e-9
        for lead, vis in ((self.radar_state.leadOne, leads_v3[0]), (self.radar_state.leadTwo, leads_v3[1])):
          track = self.tracks.get(int(lead.radarTrackId)) if lead.status and lead.radar else None
          if track is not None and YOUNG_TRACK_VISION_GATE and not young_track_vision_contradicts(lead, vis, self.v_ego):
            track = None
          floor = track.young_flat_range_vrel_floor(t_live) if track is not None else None
          if floor is not None and lead.vRel < floor:
            dv = floor - lead.vRel
            lead.vRel = floor
            lead.vLead = lead.vLead + dv
            lead.vLeadK = lead.vLeadK + dv
            self.young_flat_bound_count += 1

      for i, lead in enumerate((self.radar_state.leadOne, self.radar_state.leadTwo)):
        if lead.status and getattr(lead, "radar", False):
          track_id = int(getattr(lead, "radarTrackId", -1))
          if track_id != self.prev_lead_track_ids[i]:
            self._reset_preferred_stale_evidence(i, track_id)
          self.prev_lead_track_ids[i] = track_id
        elif (not lead.status) or (self.prev_lead_track_ids[i] not in self.tracks):
          self.prev_lead_track_ids[i] = -1
          self._reset_preferred_stale_evidence(i)

    if self.ready and (self.starpilot_toggles.adjacent_lead_tracking or self.starpilot_toggles.human_lane_changes):
      self.starpilot_radar_state.leadLeft = get_adjacent_lead(self.tracks, sm['carState'].standstill, sm['modelV2'], left=True)
      self.starpilot_radar_state.leadRight = get_adjacent_lead(self.tracks, sm['carState'].standstill, sm['modelV2'], left=False)

    # Not gated on the adjacent-lead toggles: this is a separate signal with a separate
    # consumer (Force Stop), and leaving leadLeft/leadRight untouched keeps existing
    # lane-change and UI behaviour unchanged.
    if self.ready:
      self.starpilot_radar_state.adjacentStopped = get_adjacent_stopped(self.tracks, sm['modelV2'])

    self.starpilot_toggles = get_starpilot_toggles(sm)

  def publish(self, pm: messaging.PubMaster):
    assert self.radar_state is not None

    radar_msg = messaging.new_message("radarState")
    radar_msg.valid = self.radar_state_valid
    radar_msg.radarState = self.radar_state
    pm.send("radarState", radar_msg)

    starpilot_radar_msg = messaging.new_message("starpilotRadarState")
    starpilot_radar_msg.valid = self.radar_state_valid
    starpilot_radar_msg.starpilotRadarState = self.starpilot_radar_state
    pm.send("starpilotRadarState", starpilot_radar_msg)


# fuses camera and radar data for best lead detection
def main() -> None:
  config_realtime_process(5, Priority.CTRL_LOW)

  # wait for stats about the car to come in from controls
  cloudlog.info("radard is waiting for CarParams")
  CP = messaging.log_from_bytes(Params().get("CarParams", block=True), car.CarParams)
  cloudlog.info("radard got CarParams")

  # *** setup messaging
  sm = messaging.SubMaster(['modelV2', 'carState', 'liveTracks'], poll='modelV2',
                           ignore_valid=['starpilotPlan'])
  pm = messaging.PubMaster(['radarState'])

  radar_ts = float(getattr(CP, "radarTimeStepDEPRECATED", DT_MDL) or DT_MDL)
  if not 0.01 < radar_ts < 0.2:
    radar_ts = DT_MDL

  g90_radar_filter = CP.brand == "hyundai" and CP.carFingerprint == "GENESIS_G90"
  honda_bosch_a_radar = is_bosch_a_radar_car(CP)
  RD = RadarD(radar_ts=radar_ts, delay=CP.radarDelay, g90_radar_filter=g90_radar_filter,
              honda_bosch_a_radar=honda_bosch_a_radar)

  sm = sm.extend(['starpilotPlan'])
  pm = pm.extend(['starpilotRadarState'])

  while 1:
    sm.update()

    RD.update(sm, sm['liveTracks'])
    RD.publish(pm)


if __name__ == "__main__":
  main()
