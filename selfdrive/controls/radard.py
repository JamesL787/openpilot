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
                                               BOSCH_A_DIRECT_VREL_SCALE_MPS, BOSCH_A_FREQ_HZ,
                                               bosch_a_u11_scale72_enabled, bosch_a_u11_scale_mps)
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
# D-074: the U11 scale radard assumes must match the one radar_interface decoded with. These two module values are
# the 1/64 ones (-13.5 m/s rail) unless main() finds BoschAU11Scale72 on and calls set_bosch_a_u11_scale72(True).
BOSCH_A_U11_SCALE_MPS = BOSCH_A_DIRECT_VREL_SCALE_MPS
BOSCH_A_U11_LOW_RAIL_MPS = (BOSCH_A_DIRECT_VREL_MIN_RAW - BOSCH_A_DIRECT_VREL_CENTER_RAW) * BOSCH_A_U11_SCALE_MPS

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
# --- NC veto on the rail fast path (D-071 PROPOSED; OFF, enabling is Peter's call). REPLAY/LOG evidence only, nothing driven.
# Supersedes D-070's NC cap (removed: inert on all six episodes, because at 297 48:12 NC was outside its 50 m / sigma < 32
# limits, tid 4 at 55.9-72.9 m, sigma 20-42). This is a one-sided rule: when the track's own NORMALIZED_CLOSING says it
# is closing clearly LESS than the U11 rail,
# RAIL_FAST's correction is zeroed and the rail itself is published (the D-041 bound; never above it, never dropped or
# coasted). Evidence (tools/longitudinal/stopshadow/ncveto.txt; truth = future ground-frame range fit t+0.2..t+1.2 s, which
# uses no NC, no U11 and no past range):
#   * 297 48:12.47-12.68 (00000297--f971b5896f, tid 4, 61.8-64.0 m): RAIL_FAST published -16.54/-16.24/-15.85/-13.99;
#     NC per sweep -8.0..-9.8, 5-sample median -8.3..-8.7 (4.8-5.2 above the rail); truth -8.1..-8.8.
#   * The gain cases it must not touch: 271 9:26 (NC median -14.8..-17.3 at 34-106 m), 237 10:00 (-13.3..-14.5), 298 4:10
#     (-20.3), 236 12:51/12:54 (the closest: 236 12:52.60-12:53.35 tid 40 at 64-78 m, median -10.9..-11.5 while truth was
#     -15..-21; NC under-read closing there by 4-9 m/s, which is why the threshold sits 3.5 above the rail and single
#     sweeps are not trusted; at 2.0 the veto removed 16 frames of that gain in replay).
#   * Open-loop A/B (ncveto.txt): 297 48:12 lead vRel -16.54 -> -13.50 on 5 frames, planner up to 0.46 softer for 0.6 s,
#     planner minimum unchanged (-3.65 / -3.66: the rail itself still over-reads closing there). 0 changed frames on 271,
#     236 x2, 237, 298 and 6 more railed-lead windows (245 x2, 26b x2, 289, 297 46:59); A/A 0.
#   * A median, not one sweep: 236 12:52.85 had a single NC of -10.4 (3.1 above the rail) with truth -18.1.
#   * Not the short/long fit agreement of candidate (b): at 297 the two fits agreed (-16.6/-16.5, -15.5/-16.2) because both
#     sit on the newborn range-convergence tail; and not a min-age / rsig gate (rejected, would lose 271/298).
# Reads RadarPoint.ncVRel/ncValid/ncSigma (published unlimited) and applies the limits below. Off: byte-identical.
RANGE_VREL_RAIL_NC_VETO = False
# Veto when the median NC is at least this far ABOVE (less closing than) the rail. 3.5: 297 medians sit 4.8-5.1 above;
# the nearest gain case (236 12:52.6-12:53.35) sits 2.0-2.6 above. At 5.0 the veto misses 297's -15.85 sweep. Over all
# non-oncoming railed rows (8 routes, < 100 m, sigma < 64) a median >= rail + 3.5 met truth past rail - 1.0 on 3 of 26
# rows (26b 24:11 tid 30, truth -14.8..-15.3, never a RAIL_FAST row).
RANGE_VREL_RAIL_NC_VETO_ABOVE_RAIL_MPS = 3.5
# Median of the last up-to-5 valid NC sweeps no older than 0.5 s, and at least 3 of them (about 5 sweeps at 14.35 Hz).
RANGE_VREL_RAIL_NC_VETO_SAMPLES = 5
RANGE_VREL_RAIL_NC_VETO_MIN_SAMPLES = 3
RANGE_VREL_RAIL_NC_VETO_WINDOW_S = 0.5
# NC samples the veto accepts. The ncValid limits of D-069's value-replacing use (50 m, sigma < 32) are unchanged; the veto
# may only zero a RAIL_FAST correction, so it reads NC further out. REPLAY/LOG (stopshadow/ncveto.txt):
#   * 80 m: 297 48:12 tid 4's excursion was at 61.8-64.0 m. Against the future ground-frame range fit, the 5-sample NC
#     median on non-oncoming railed rows errs -0.3 / +0.1 m/s at 50-75 / 75-100 m but +3.1 past 100 m (NC under-reads
#     closing far out, e.g. 271 9:27 at 104 m: NC -16.2 vs truth -21..-23), so the veto stops short of 100 m.
#   * sigma < 64: 297's NC sigma was 20-42 over the railed stretch. The median of several sweeps carries the confidence;
#     64 only drops the unusable tail of the 7-bit field.
RANGE_VREL_RAIL_NC_VETO_MAX_D_REL_M = 80.0
RANGE_VREL_RAIL_NC_VETO_MAX_SIGMA_RAW = 64

# --- Adjacent-lead rail gate (2026-09-28). REPLAY evidence only, nothing driven.
# The range assist above only runs on leadOne/leadTwo, so every other track publishes the raw U11
# rail: vLead = vEgo - 13.5 even for a stopped object. 0000028f seg 6 ~30.5-34 s (UI Work, STATUS
# 108): track 49 at yRel ~3.2, range 74.6 -> 7.9 m in 3.5 s (closing ~ vEgo 21 m/s, i.e. stationary),
# U11 pinned at -13.5 throughout, was published as leadLeft at ~16 mph; track 43 (yRel ~9) the same.
# leadLeft/leadRight feed the UI and the conditional-chill adjacent-lead veto.
# A Bosch-A track stops being ELIGIBLE as leadLeft/leadRight once, on the rail, the fresh short range
# fit says at least RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS more closing than the rail on
# ADJACENT_RAIL_GATE_UPDATES consecutive measured updates; it stays so until U11 leaves the rail.
# The point itself is still published and still eligible as leadOne/leadTwo (D-041/D-042); only
# the adjacent-lead label changes. Set ADJACENT_RAIL_GATE to False to restore the old behaviour.
ADJACENT_RAIL_GATE = True
ADJACENT_RAIL_GATE_UPDATES = 3

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

# --- Camera x-rate cap on a range walk (2026-09-29, extends D-053, rides RANGE_VREL_ASSIST). ON (owner, 2026-09-29).
# REPLAY evidence only (open-loop radarState from logged CAN, plus the closed-loop planner tool on logged ego); not driven.
# The assist fits the radar range and cannot see a range error. 00000297--f971b5896f 40:23.5 and 42:18.3: the radar
# range fell faster than the matched camera lead's own x did, and the assist published that extra closing.
# This judges the correction against the CAMERA'S RANGE (leadsV3[0].x), not its speed output: the model's speed
# under-reads real far closing (STATUS 162; 297 53:40, 280 25:03 and 236 18:55 have the camera x falling 5-9 m/s
# while its speed said 2-4), which is why the camera-speed version of this cap was dropped there.
# Every model cycle a same-car camera sample (prob >= MIN_PROB, VISION_ASSIST_RANGE_TOL / MAX_DY_M geometry) is kept
# on the lead track with the track's own dRel, over the trailing WINDOW_S. camera_xrate_verdict() then judges it; the
# rules are the ones in the UI Work replay viewer (keep the two identical):
#   FEW     fewer than MIN_POINTS                                               -> no action
#   STEP    a two-level fit (>= STEP_MIN_SIDE points a side) with SSE_S < STEP_SSE_RATIO * SSE_L and a level change
#           > STEP_MIN_M is a camera lead switch (a plain fit reads the 297 10:55 74 -> 60 m jump as 7-10 m/s of
#           closing). Only the points after the break are kept; fewer than POST_MIN_POINTS or a span under
#           POST_MIN_SPAN_S of them                                              -> no action
#   NOISY   line residual sd >= max(MAX_RESID_SD_M, RESID_SD_REL * mean camera range)  -> no action
#   AGREE   |camera slope - radar dRel slope| over the same samples < max(AGREE_MPS, AGREE_REL * mean range) -> none
#   JUDGED  otherwise: published closing may exceed the camera x-rate closing by at most MARGIN_MPS.
# It only LOWERS a correction: never arms one, never touches U11, the KF, selection or the point (D-041/D-042).
# The U11 rail is exempt (D-041, 000001f9 29:52), as the rail rules above decide alone there.
# Chosen on replay (per-event m/s*s of leadOne correction, base -> cap):
#   WINDOW 3 s, MIN_POINTS 20: a 2 s window cut 237 19:49 to 12.84 and 258 56:18 to 0.47.
#   MIN_PROB 0.9: 0.8 cut 280 25:03 to 20.62 (0.7: 18.77 under the fixed-sd rule); 0.9 keeps 21.81.
#   MARGIN 2: margin 3 left 297 42:18.3 at 7.34 (2: 6.81).
#   Cut: 297 42:18.3 8.45 -> 6.81, 40:23.5 1.77 -> 1.15, 283 9:12 4.40 -> 0.34 (post-break refit).
#   Kept (within 0.02): 297 39:01.7, 53:40.5, 15:00, 236 12:51, 236 18:55, 237 5:21, 258 56:18, 026b 28:27, 280 25:03,
#   271 9:26, 026c 4:08. Cost: 237 14:25 9.80 -> 8.72 and 19:49 15.74 -> 15.01 (radar range fell ~9.5 m/s against a
#   camera x of ~5 at the tail of a real approach).
#   AGREE_REL 0: 0.03 is what cost 42:18. At 95-107 m it widens agreement to ~3 m/s and the walk's 2.0-2.6 m/s
#   disagreement passed as AGREE (6.81). At 0, 42:18 goes to 2.34 (planner cmd -1.95 -> -1.50) and every kept event
#   is unchanged (237 19:49 14.92). The UI Work viewer uses 0 too (40c62a24d).
#   Corpus (UI Work arm scan, 378 arms, 40 routes, 635e99ca3): the one hard phantom is 283 9:12 (a radar track walking
#   in behind a lead change; U11 alone read -6.6, so this cap removes the assist's extra only). 241 3:36, the other
#   hard one, was a real slow car. A camera-SPEED gate was re-tested there and rejected again: it caught 14/87 helped
#   arms and 241, whose camera speed lagged its real slowdown.
#   NOT FIXED: 297 10:55.1 (7.22 -> 7.22) and 0000025e 7:04.2 (10.53 -> 10.53). The walk arms at the camera's own
#   lead switch and peaks within 1 s, before 20 matched points exist; after that the 60 m camera range scatters
#   3.2-3.7 m (limit max(3, 2.5)) and reads NOISY until the correction has decayed.
RANGE_VREL_CAM_XRATE = True
RANGE_VREL_CAM_XRATE_MIN_PROB = 0.9
RANGE_VREL_CAM_XRATE_WINDOW_S = 3.0
RANGE_VREL_CAM_XRATE_MIN_POINTS = 20
RANGE_VREL_CAM_XRATE_STEP_MIN_SIDE = 5
RANGE_VREL_CAM_XRATE_STEP_SSE_RATIO = 0.5
RANGE_VREL_CAM_XRATE_STEP_MIN_M = 6.0
RANGE_VREL_CAM_XRATE_POST_MIN_POINTS = 10
RANGE_VREL_CAM_XRATE_POST_MIN_SPAN_S = 1.0
RANGE_VREL_CAM_XRATE_MAX_RESID_SD_M = 3.0
RANGE_VREL_CAM_XRATE_RESID_SD_REL = 0.04
RANGE_VREL_CAM_XRATE_AGREE_MPS = 2.0
RANGE_VREL_CAM_XRATE_AGREE_REL = 0.0
RANGE_VREL_CAM_XRATE_MARGIN_MPS = 2.0

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

# ONPATH_RADAR_ADOPT: a radar-only track that sits on the driving path for a second is published as
# radarState.leadOnpath, beside an unchanged leadOne, so the planner can brake for it before the camera sees it. Above
# V_EGO_STATIONARY, get_lead only consults radar when the model lead's probability clears lead_detection_probability,
# and then only the track that matches the model lead; the only radar-only path is the low-speed override
# (v_ego < 4 m/s, dRel < 25 m). A car the model does not yet see is therefore invisible to the planner however long
# radar has it on the path. Route 00000297--f971b5896f (owner bookmark 31:11.2): track 6, a stopped car on a curve
# (yRel -9 .. -14 m, path offset within ~1.3 m), measured on every sweep from 94 m down to 39 m over 3.5 s while
# leadsV3[0].prob was 0.00-0.28; the lead arrived at 31:09.6 (vision, 38 m) and the brake was -3.1 .. -3.5 with aEgo
# -4.1 .. -4.35. 46:49-46:51 (bookmark 46:54): track 45, a car at ~6 m/s, on path 106 -> 69 m for ~2 s while the lead
# was none and then a vision lead at 118 m that the track could not match; brake -3.5.
#
# The gate is persistence on the path, not a single sweep: every fresh measured sweep of the last
# ONPATH_ADOPT_MIN_SPAN_S has |yRel + model path y at dRel| <= ONPATH_ADOPT_HARD_WIDTH_M, their median is within
# ONPATH_ADOPT_MEDIAN_WIDTH_M and ONPATH_ADOPT_CORE_FRAC of them are within ONPATH_ADOPT_CORE_WIDTH_M; a coast longer
# than ONPATH_ADOPT_MAX_COAST_S or one sweep outside the hard width restarts it. The median/fraction form, not a
# plain 1.0 m width, is from 297 31:06-31:09: the model path 70-90 m out on that curve put the stopped car at
# -1.7 .. +1.3 m on single sweeps, and a strict 1.0 m width never held it for a second before vision had it.
# The track must also close (mean U11 <= -ONPATH_ADOPT_MIN_CLOSING_MPS) and its own ranges must agree: an LSQ over
# the window with rms <= ONPATH_ADOPT_MAX_RANGE_RESIDUAL_M whose slope is within ONPATH_ADOPT_RATE_TOL_MPS of the mean
# U11, except that a slope FASTER than U11 is accepted when U11 sits near the rail (D-041/D-063: a railed U11 is a
# bound; 297 track 6 read -13.5 railed against a range slope of -13 .. -19).
#
# Why it is a separate field and not leadOne: stationary on-path returns also come from overhead structures and
# roadside clutter on curves, and Bosch-A publishes no elevation. Over 50 routes (replay, 2026-09-29) the gate made
# 109 adoptions, 76 later confirmed by HEAD or the model; of 33 unconfirmed most were real cars (a lead leaving the
# lane, a far car on a curve the model saw at low probability), but 00000297--f971b5896f 30:18.1 was a stationary
# object at 28 m on a sharp curve (engaged, 9 m/s) that the car passed ~2.5 m to the side, and its window was better
# centred (median 0.66 m, 87 % within 1.0 m) than the true stopped car at 31:07 (0.67 m, 80 %). No width in this form
# separates them (and D-061: path gates made a brake worse). As leadOne it drew -3.5 m/s^2 for ~1 s. So the track
# gets bounded authority (D-048): the planner lets leadOnpath add braking only down to ONPATH_LEAD_MAX_BRAKE
# (longitudinal_planner.py), leadOne is never changed, and leadOnpath is withdrawn the cycle radard's own leadOne
# becomes a radar lead (vision match or its normal radar path) or a vision leadOne is not
# ONPATH_ADOPT_VISION_MARGIN_M farther away. Nothing is deleted and no range is moved (D-041/D-042).
# ON (owner, 2026-09-29), with the planner cap. Replay evidence only, no road evidence. Cost: a second planner/MPC
# instance every cycle (1.44 -> 2.89 ms per planner step on the aarch64 VM); not yet timed on the device.
ONPATH_RADAR_ADOPT = True
ONPATH_ADOPT_MIN_SPAN_S = 1.0
ONPATH_ADOPT_MIN_SAMPLES = 10          # ~14 sweeps a second at BOSCH_A_FREQ_HZ; a few coasts are tolerated
ONPATH_ADOPT_HARD_WIDTH_M = 2.0
ONPATH_ADOPT_MEDIAN_WIDTH_M = 0.8
ONPATH_ADOPT_CORE_WIDTH_M = 1.0
ONPATH_ADOPT_CORE_FRAC = 0.7
ONPATH_ADOPT_MAX_COAST_S = 0.15
ONPATH_ADOPT_MIN_CLOSING_MPS = 2.0
ONPATH_ADOPT_MAX_RANGE_RESIDUAL_M = 1.0
ONPATH_ADOPT_RATE_TOL_MPS = 2.5
# Mean U11 at or below ONPATH_ADOPT_RAIL_VREL_MPS is treated as railed: 1.0 m/s inside the low rail, i.e. -12.5 at
# the 1/64 rail of -13.5. D-074 keeps the 1.0 margin and moves the value with the rail (-11.0 at 1/72); a fixed
# -12.5 would sit outside a -12.0 rail and silently stop treating any railed track as railed.
ONPATH_ADOPT_RAIL_VREL_MARGIN_MPS = 1.0
ONPATH_ADOPT_RAIL_VREL_MPS = BOSCH_A_U11_LOW_RAIL_MPS + ONPATH_ADOPT_RAIL_VREL_MARGIN_MPS
ONPATH_ADOPT_MAX_D_REL_M = 120.0
ONPATH_ADOPT_VISION_MARGIN_M = 5.0

# ONPATH_ADOPT_MIN_MEDIAN_EXISTENCE: a track is not NEWLY adopted as leadOnpath while the median of the radar's own
# OBJECT_EXISTENCE_PROBABILITY (RadarPoint.existence = raw / 127, Bosch-A only) over its adoption window
# (the measured on-path sweeps of the last ONPATH_ADOPT_MIN_SPAN_S) is below this. Route 00000298--c4d2a4acbc
# 1018.35 (log): track 2 was born at 42 m, y +1.07, and closed at -16 m/s by range with U11 railed at -13.5 and a
# constant ~1.3 deg bearing, then vanished at 23 m 1.2 s later; the camera never saw it (the model lead was a car at
# ~121-125 m). It passed every geometry gate at the edge (path median 0.76 of 0.8, range slope -15.96 against a band
# edge of -16.00; the rail term only exempts) and drew a 0.2 s brake to -1.00 (the ONPATH_LEAD_MAX_BRAKE cap).
# Its existence went 59 -> 0 over the window, median 0.055; every real adoption checked had a median of 0.54-0.99
# (297 track 6 0.976, track 45 0.992; 263 track 25 0.535 lowest), and single sweeps at 0 do occur on real cars
# (270 track 63, 280 track 7), hence the median and not a minimum. Over the 130 adoptions of the 598b524ba study a
# floor of 0.2 or 0.3 removes only this one.
# Replay (closed loop, car planner + fitted plant, 12 windows incl. 297 31:08 / 46:49 and the protected brakes):
# 298 1018.35 minimum accel -1.00 -> -0.02; the other 11 windows are frame-identical. No road evidence.
# Held leads are not re-checked, a value of -1 (not provided: every other radar and older logs) never gates, and
# nothing is deleted: the track stays a radar point, leadOne/leadTwo are unchanged; it only does not get the extra
# bounded leadOnpath brake (D-041/D-042/D-048).
ONPATH_ADOPT_MIN_MEDIAN_EXISTENCE = 0.2

# Far birth-rail vision bound (route 00000298 Bookmark 3, ~1020.3-1021.4). Far leadOne track 60 was born at ~121 m
# with U11 on the low rail (-13.5) and no range fit yet, while the camera saw a car at that range doing 16-18 m/s;
# the planner held ~-0.85 for 1.2 s and the car reached aEgo -1.21. A railed U11 is only a bound (D-063). For a
# Bosch-A radar lead (leadOne, leadTwo or leadOnpath) at dRel >= FAR_RAIL_MIN_D_REL_M whose published vRel is on the
# rail, when the model lead in the same slot sat at the same range (|x - RADAR_TO_CAMERA - dRel| <=
# max(FAR_RAIL_RANGE_TOL_M, FAR_RAIL_RANGE_TOL_FRAC * dRel), prob >= FAR_RAIL_VISION_MIN_PROB) on at least
# FAR_RAIL_MIN_MATCHES of the last FAR_RAIL_HIST_FRAMES model frames with steady speed (pstdev <=
# FAR_RAIL_MAX_SPEED_STDEV_MPS), the published vRel may claim at most FAR_RAIL_MARGIN_MPS more closing than
# median(camera v) - vEgo. vLead/vLeadK move by the same amount; aLeadK, the track, U11, the KF and lead selection are
# untouched, and nothing is deleted or coasted (D-041/D-042). Range veto: when the track's own vRelRangeDerived closes
# at least as fast as the floor, the rail stands -- without it 266 484 (range fit -15..-19) braked 0.05 s later.
# Replay (car-matched 07b66420, params 2026-09-30T16:44:42Z, fitted plant): 298 BM3 sim accel -1.20 -> -0.58; 283
# 881.5, 23e 2342.9, 297 525.6, 263 358, 266 484, 266 560 identical to base. Does not touch the 0.2 s leadOnpath step
# at 298 1018.35 (25 m). Replay evidence only; not road-validated.
FAR_RAIL_VISION_BOUND = True
FAR_RAIL_MIN_D_REL_M = 80.0
FAR_RAIL_VREL_TOL_MPS = 0.05          # published vRel within this of BOSCH_A_U11_LOW_RAIL_MPS counts as railed
FAR_RAIL_HIST_FRAMES = 20             # model frames (radard runs once per modelV2)
FAR_RAIL_MIN_MATCHES = 12
FAR_RAIL_VISION_MIN_PROB = 0.15
FAR_RAIL_RANGE_TOL_M = 8.0
FAR_RAIL_RANGE_TOL_FRAC = 0.08
FAR_RAIL_MAX_SPEED_STDEV_MPS = 2.0
FAR_RAIL_MARGIN_MPS = 3.0

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


def set_bosch_a_u11_scale72(enabled: bool) -> None:
  """D-074: point radard's U11-scale-derived values at the scale radar_interface decodes with. Called once in main().
  OFF restores the 1/64 values exactly; no threshold other than the rail and the half-count it is built from moves."""
  global BOSCH_A_U11_SCALE_MPS, BOSCH_A_U11_LOW_RAIL_MPS, ONPATH_ADOPT_RAIL_VREL_MPS
  BOSCH_A_U11_SCALE_MPS = bosch_a_u11_scale_mps(enabled)
  BOSCH_A_U11_LOW_RAIL_MPS = (BOSCH_A_DIRECT_VREL_MIN_RAW - BOSCH_A_DIRECT_VREL_CENTER_RAW) * BOSCH_A_U11_SCALE_MPS
  ONPATH_ADOPT_RAIL_VREL_MPS = BOSCH_A_U11_LOW_RAIL_MPS + ONPATH_ADOPT_RAIL_VREL_MARGIN_MPS


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


def far_rail_model_sample(vis) -> tuple[float, float, float] | None:
  """FAR_RAIL_VISION_BOUND history entry for one model lead: (prob, range at the radar, speed), or None."""
  if vis is None or not len(vis.x) or not len(vis.v):
    return None
  return float(vis.prob), float(vis.x[0]) - RADAR_TO_CAMERA, float(vis.v[0])


def far_rail_vrel_floor(lead, hist, v_ego: float) -> float | None:
  """FAR_RAIL_VISION_BOUND: the least vRel a far railed Bosch-A radar lead may publish, or None when it does not apply."""
  if not (lead.status and lead.radar and lead.dRel >= FAR_RAIL_MIN_D_REL_M and
          lead.vRel <= BOSCH_A_U11_LOW_RAIL_MPS + FAR_RAIL_VREL_TOL_MPS):
    return None
  tol = max(FAR_RAIL_RANGE_TOL_M, FAR_RAIL_RANGE_TOL_FRAC * lead.dRel)
  speeds = [h[2] for h in hist if h is not None and h[0] >= FAR_RAIL_VISION_MIN_PROB and abs(h[1] - lead.dRel) <= tol]
  if len(speeds) < FAR_RAIL_MIN_MATCHES or float(np.std(speeds)) > FAR_RAIL_MAX_SPEED_STDEV_MPS:
    return None
  floor = float(np.median(speeds)) - float(v_ego) - FAR_RAIL_MARGIN_MPS
  v_range = float(lead.vRelRangeDerived)
  if math.isfinite(v_range) and v_range <= floor:
    return None  # the track's own range fit closes at least as fast: the rail stands
  return floor


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


def camera_xrate_sample(d_rel: float, y_rel: float, vis) -> float | None:
  """RANGE_VREL_CAM_XRATE: the camera range (m, radar frame) of a confident model lead matched to this track, else None."""
  if vis is None or float(vis.prob) < RANGE_VREL_CAM_XRATE_MIN_PROB or not len(vis.x) or not len(vis.y):
    return None
  cam_d = float(vis.x[0]) - RADAR_TO_CAMERA
  if abs(cam_d - float(d_rel)) > VISION_ASSIST_RANGE_TOL * max(float(d_rel), 1.0):
    return None
  if abs(float(y_rel) + float(vis.y[0])) > VISION_ASSIST_MAX_DY_M:
    return None
  return cam_d


def _line_fit(t, y) -> tuple[float, float]:
  """Least-squares slope and residual sum of squares of y on t."""
  tm, ym = t.mean(), y.mean()
  slope = float(((t - tm) * (y - ym)).sum()) / float(((t - tm) ** 2).sum())
  return slope, float(((y - ym - slope * (t - tm)) ** 2).sum())


def camera_xrate_verdict(samples) -> tuple[str, float | None]:
  """RANGE_VREL_CAM_XRATE. `samples` are (t, camera range, radar dRel). Returns (verdict, camera closing m/s, + closes);
  the closing is only meaningful for AGREE and JUDGED. See the constant block for the rules."""
  n = len(samples)
  if n < RANGE_VREL_CAM_XRATE_MIN_POINTS:
    return "FEW", None
  arr = np.asarray(samples, dtype=float)
  t, x, d = arr[:, 0] - arr[-1, 0], arr[:, 1], arr[:, 2]
  slope, sse_l = _line_fit(t, x)
  k = RANGE_VREL_CAM_XRATE_STEP_MIN_SIDE
  if n >= 2 * k:
    c1, c2 = np.cumsum(x), np.cumsum(x * x)
    n1 = np.arange(k, n - k + 1, dtype=float)
    s1, q1 = c1[k - 1:n - k], c2[k - 1:n - k]
    s2, q2 = c1[-1] - s1, c2[-1] - q1
    n2 = n - n1
    sse_s = (q1 - s1 * s1 / n1) + (q2 - s2 * s2 / n2)
    i = int(np.argmin(sse_s))
    if sse_s[i] < RANGE_VREL_CAM_XRATE_STEP_SSE_RATIO * sse_l and abs(s2[i] / n2[i] - s1[i] / n1[i]) > RANGE_VREL_CAM_XRATE_STEP_MIN_M:
      t, x, d = t[k + i:], x[k + i:], d[k + i:]   # a camera lead switch: judge only what came after it
      if len(t) < RANGE_VREL_CAM_XRATE_POST_MIN_POINTS or t[-1] - t[0] < RANGE_VREL_CAM_XRATE_POST_MIN_SPAN_S:
        return "STEP", None
      slope, sse_l = _line_fit(t, x)
  radar_slope, _ = _line_fit(t, d)
  m, x_mean = len(t), float(x.mean())
  if (sse_l / max(m - 2, 1)) ** 0.5 >= max(RANGE_VREL_CAM_XRATE_MAX_RESID_SD_M, RANGE_VREL_CAM_XRATE_RESID_SD_REL * x_mean):
    return "NOISY", None
  if abs(slope - radar_slope) < max(RANGE_VREL_CAM_XRATE_AGREE_MPS, RANGE_VREL_CAM_XRATE_AGREE_REL * x_mean):
    return "AGREE", -slope
  return "JUDGED", -slope


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
    # RANGE_VREL_RAIL_NC_VETO: (t, ncVRel) of the last measured sweeps whose NC passed the veto's range and sigma limits.
    self.nc_veto_hist: deque = deque(maxlen=RANGE_VREL_RAIL_NC_VETO_SAMPLES)
    self.nc_veto_shadow = False
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
    # RANGE_VREL_CAM_XRATE: (model t, camera range, dRel) of same-car camera samples over the trailing window.
    self.cam_hist: deque = deque()
    # YOUNG_TRACK_FLAT_RANGE_BOUND: first update time and every fresh-sweep (t, dRel) of the track's first
    # YOUNG_TRACK_MAX_AGE_S. Coasted sweeps count: a Bosch-A coast holds vRel but publishes the live gated range.
    self.t_first = float('nan')
    self.young_range_hist: list = []

    # ONPATH_RADAR_ADOPT: fresh measured sweeps (t, dRel, vRel, path offset, existence) of the current on-path run;
    # existence is NaN when the radar does not provide it (ONPATH_ADOPT_MIN_MEDIAN_EXISTENCE)
    self.onpath_hist: deque = deque(maxlen=64)
    self._onpath_last_meas_t = float('nan')
    self.onpath_adopted = False  # published as leadOnpath (ONPATH_RADAR_ADOPT); cleared with the run

    # ADJACENT_RAIL_GATE: consecutive railed updates the range contradicts, and the latch they set
    self.rail_range_count = 0
    self.rail_range_inconsistent = False

    # deceleration history for the adjacent-lane stopped-vehicle detector
    self.moving_frames = 0
    self.rest_frames = 0
    self.seen_moving = False

  def update(self, d_rel: float, y_rel: float, v_rel: float, v_lead: float, measured: bool,
             measurement_update: bool | None = None, t_now: float = 0.0,
             range_assist: bool = False, vision_closing: float | None = None, vision_assist: bool = False,
             camera_sample: tuple[float, float | None] | None = None,
             nc_vrel: float = 0.0, nc_valid: bool = False, nc_sigma: int = 127):
    # relative values, copy
    self.dRel = d_rel   # LONG_DIST
    self.yRel = y_rel   # -LAT_DIST
    self.vRel = v_rel   # REL_SPEED
    self.vLead = v_lead
    self.measured = measured   # measured or estimate
    # Bosch-A NORMALIZED_CLOSING vRel for this sweep, unlimited (telemetry and RANGE_VREL_RAIL_NC_VETO); 0/False/127 elsewhere
    self.ncVRel = float(nc_vrel)
    self.ncValid = bool(nc_valid)
    self.ncSigma = int(nc_sigma)

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
      if (nc_valid and int(nc_sigma) < RANGE_VREL_RAIL_NC_VETO_MAX_SIGMA_RAW
          and 0.0 < d_rel < RANGE_VREL_RAIL_NC_VETO_MAX_D_REL_M):
        self.nc_veto_hist.append((float(t_now), float(nc_vrel)))

    # D-053. Must run after the fits above. It only sets range_assist_correction: the KF below is
    # fed the NATIVE speed, and get_RadarState applies the correction to vRel, vLead and vLeadK at
    # publish time. The first version fed the corrected speed here, and aLeadK absorbed every
    # arming step as a hard acceleration (see the rework note at the top of this file).
    if camera_sample is not None:
      # One call per radard (model) cycle: append the matched camera range, then drop what left the window.
      t_cam, cam_d = camera_sample
      if cam_d is not None:
        self.cam_hist.append((float(t_cam), float(cam_d), float(d_rel)))
      while self.cam_hist and self.cam_hist[0][0] < t_cam - RANGE_VREL_CAM_XRATE_WINDOW_S:
        self.cam_hist.popleft()
    self._update_range_assist(range_assist, measurement_update, t_now, vision_closing, vision_assist)

    if measurement_update:
      self._update_rail_range_inconsistent()

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

  def update_onpath(self, t_now: float, path_offset: float, measured: bool, existence: float = -1.0) -> None:
    """ONPATH_RADAR_ADOPT bookkeeping, once per fresh liveTracks message. `path_offset` is NaN off the model path.
    `existence`: RadarPoint.existence (0..1), negative when the radar does not provide it."""
    if measured:
      if path_offset == path_offset and abs(path_offset) <= ONPATH_ADOPT_HARD_WIDTH_M:
        if not self.onpath_hist or t_now > self.onpath_hist[-1][0]:
          ex = float(existence) if existence >= 0.0 else float('nan')
          self.onpath_hist.append((float(t_now), float(self.dRel), float(self.vRel), float(path_offset), ex))
      else:
        self.onpath_hist.clear()
      self._onpath_last_meas_t = float(t_now)
    elif not (t_now - self._onpath_last_meas_t <= ONPATH_ADOPT_MAX_COAST_S):
      self.onpath_hist.clear()
    if not self.onpath_hist:
      self.onpath_adopted = False

  def onpath_adoptable(self, held: bool = False) -> bool:
    """True when this track has been on the driving path long enough to be a radar-only lead.
    `held`: it was leadOnpath last cycle, so only an unbroken on-path run is required."""
    if not self.onpath_hist or not (self.dRel <= ONPATH_ADOPT_MAX_D_REL_M):
      return False
    if held:
      return True
    t_last = self.onpath_hist[-1][0]
    win = [x for x in self.onpath_hist if x[0] >= t_last - ONPATH_ADOPT_MIN_SPAN_S - 1e-6]
    if len(win) < ONPATH_ADOPT_MIN_SAMPLES or self.onpath_hist[0][0] > t_last - ONPATH_ADOPT_MIN_SPAN_S + 1e-6:
      return False
    offs = np.abs(np.array([x[3] for x in win]))
    if np.median(offs) > ONPATH_ADOPT_MEDIAN_WIDTH_M or np.mean(offs <= ONPATH_ADOPT_CORE_WIDTH_M) < ONPATH_ADOPT_CORE_FRAC:
      return False
    ts = np.array([x[0] for x in win]) - t_last
    ds = np.array([x[1] for x in win])
    v_mean = float(np.mean([x[2] for x in win]))
    if v_mean > -ONPATH_ADOPT_MIN_CLOSING_MPS:
      return False
    slope, icpt = np.polyfit(ts, ds, 1)
    rms = float(np.sqrt(np.mean((ds - (slope * ts + icpt)) ** 2)))
    if rms > ONPATH_ADOPT_MAX_RANGE_RESIDUAL_M or slope > v_mean + ONPATH_ADOPT_RATE_TOL_MPS:
      return False
    if not (slope >= v_mean - ONPATH_ADOPT_RATE_TOL_MPS or v_mean <= ONPATH_ADOPT_RAIL_VREL_MPS):
      return False
    # ONPATH_ADOPT_MIN_MEDIAN_EXISTENCE: only when the radar provided the value on this window's sweeps
    ex = [x[4] for x in win if x[4] == x[4]]
    return not (ex and float(np.median(ex)) < ONPATH_ADOPT_MIN_MEDIAN_EXISTENCE)

  def _clear_range_assist(self) -> None:
    self.range_assist_active = False
    self.vision_assist_count = 0
    self.vision_assist_early = False
    self.range_assist_arm_count = 0
    self.range_assist_rail_count = 0
    self.range_assist_correction = 0.0
    self.nc_veto_shadow = False

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

    self.nc_veto_shadow = False
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
    on_rail = self.vRel <= BOSCH_A_U11_LOW_RAIL_MPS + BOSCH_A_U11_SCALE_MPS / 2
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
    if rail_fast and correction > 0.0:
      nc_med = self.nc_veto_median(t_now)
      # nc_veto_shadow marks every update where the veto WOULD fire, switch on or off (leadOne/leadTwo ncVetoShadow).
      self.nc_veto_shadow = nc_med is not None and nc_med >= BOSCH_A_U11_LOW_RAIL_MPS + RANGE_VREL_RAIL_NC_VETO_ABOVE_RAIL_MPS
      if RANGE_VREL_RAIL_NC_VETO and self.nc_veto_shadow:
        # NC says clearly less closing than the rail: publish the rail itself (D-041 bound), no RAIL_FAST correction.
        correction = 0.0
    if self.vision_assist_early:
      # Never claim more closing than vision corroborates plus the margin: published vRel >= -(closing + margin).
      correction = min(correction, max(self.vRel + vision_closing + VISION_ASSIST_CLOSING_MARGIN_MPS, 0.0))
    if RANGE_VREL_CAM_XRATE and correction > 0.0 and not on_rail:
      verdict, cam_closing = camera_xrate_verdict(self.cam_hist)
      if verdict == "JUDGED":
        # Range walk: published closing may exceed the camera's own x-rate closing by at most the margin.
        correction = min(correction, max(self.vRel + cam_closing + RANGE_VREL_CAM_XRATE_MARGIN_MPS, 0.0))
    self.range_assist_correction = correction

  def _update_rail_range_inconsistent(self) -> None:
    """ADJACENT_RAIL_GATE latch. Rail-agnostic here; only Bosch-A callers act on it (a -13.5 vRel is a
    real reading on other radars)."""
    if self.vRel > BOSCH_A_U11_LOW_RAIL_MPS + BOSCH_A_U11_SCALE_MPS / 2:
      self.rail_range_count = 0
      self.rail_range_inconsistent = False
      return
    if self.vRelRangeFresh and self.vRel - self.vRelRange >= RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS:
      self.rail_range_count += 1
      if self.rail_range_count >= ADJACENT_RAIL_GATE_UPDATES:
        self.rail_range_inconsistent = True
    else:
      self.rail_range_count = 0

  def nc_veto_median(self, t_now: float) -> float | None:
    """RANGE_VREL_RAIL_NC_VETO: median of the recent wide-limit NC vRels, or None with too few fresh samples."""
    vals = [v for t, v in self.nc_veto_hist if float(t_now) - t <= RANGE_VREL_RAIL_NC_VETO_WINDOW_S]
    if len(vals) < RANGE_VREL_RAIL_NC_VETO_MIN_SAMPLES:
      return None
    return float(np.median(vals))

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
    # published speeds: vRel and vLead (long_mpc) and vLeadK (the planner), keeping the published lead
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
      state["ncVetoShadow"] = bool(self.nc_veto_shadow)
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


def get_onpath_lead(v_ego: float, tracks: dict[int, Track], lead_one, preferred_track_id: int = -1) -> dict[str, Any] | None:
  """ONPATH_RADAR_ADOPT (see the constant block): the radar-only on-path lead, published as radarState.leadOnpath
  beside an unchanged leadOne. None when leadOne is already a radar lead (it is never replaced), when the nearest
  adoptable track is not ONPATH_ADOPT_VISION_MARGIN_M nearer than a vision leadOne, or below V_EGO_STATIONARY."""
  if v_ego < V_EGO_STATIONARY or (lead_one.status and lead_one.radar):
    return None
  candidates = [c for c in tracks.values()
                if c.onpath_adoptable(held=c.onpath_adopted and c.identifier == preferred_track_id)]
  if not candidates:
    return None
  closest_track = min(candidates, key=lambda c: c.dRel)
  if lead_one.status and not closest_track.dRel < lead_one.dRel - ONPATH_ADOPT_VISION_MARGIN_M:
    return None
  closest_track.onpath_adopted = True
  return closest_track.get_RadarState(shadow_telemetry=True)


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
    "ncVetoShadow": False,
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


def get_adjacent_lead(tracks: dict[int, Track], standstill: bool, model_data: capnp._DynamicStructReader, left: bool = True,
                      honda_bosch_a: bool = False) -> dict[str, Any]:
  lead_dict = {'status': False}

  rail_gate = ADJACENT_RAIL_GATE and honda_bosch_a
  adjacent_tracks = [c for c in tracks.values()
                     if c.potential_adjacent_lead(left, standstill, model_data) and not (rail_gate and c.rail_range_inconsistent)]
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
    self.far_rail_bound_count = 0
    self.far_rail_hist = [deque(maxlen=FAR_RAIL_HIST_FRAMES) for _ in range(2)]  # per model lead slot
    # The lead KF consumes Bosch measurements at the physical radar cadence. Lead probability
    # filters, however, consume modelV2 leads every model cycle and must retain model-loop timing.
    kf_dt = HONDA_BOSCH_A_RADAR_TS if self.honda_bosch_a_radar else radar_ts
    self.kalman_params = KalmanParams(kf_dt)
    self.g90_radar_filter = g90_radar_filter
    lead_prob_dt = DT_MDL if self.honda_bosch_a_radar else radar_ts
    self.lead_prob_filters = [FirstOrderFilter(0.0, 0.2, lead_prob_dt) for _ in range(2)]
    self.prev_lead_track_ids = [-1, -1]
    self.prev_onpath_track_id = -1  # radarState.leadOnpath last cycle (ONPATH_RADAR_ADOPT)
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

    ar_pts = {pt.trackId: [pt.dRel, pt.yRel, pt.vRel, pt.measured, pt.ncVRel, pt.ncValid, pt.ncSigma, getattr(pt, 'existence', -1.0)] for pt in rr.points}

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
      cam_sample = None
      if RANGE_VREL_CAM_XRATE and ids in lead_track_ids:
        vis = sm['modelV2'].leadsV3[0] if len(sm['modelV2'].leadsV3) else None
        cam_sample = (sm.logMonoTime['modelV2'] * 1e-9, camera_xrate_sample(rpt[0], rpt[1], vis))
      self.tracks[ids].update(rpt[0], rpt[1], rpt[2], v_lead, measured, measurement_update,
                              t_now=sm.logMonoTime['liveTracks'] * 1e-9,
                              range_assist=ids in lead_track_ids, vision_closing=vis_closing,
                              vision_assist=vision_assist, camera_sample=cam_sample,
                              nc_vrel=rpt[4], nc_valid=rpt[5], nc_sigma=rpt[6])

    # ONPATH_RADAR_ADOPT: path offset of every track on a fresh sweep (yRel + = left, model y + = right)
    if ONPATH_RADAR_ADOPT and self.honda_bosch_a_radar and radar_fresh:
      position = getattr(sm['modelV2'], 'position', None) if self.ready else None
      px = np.asarray(position.x) if position is not None and len(position.x) else None
      py = np.asarray(position.y) if px is not None else None
      t_live = sm.logMonoTime['liveTracks'] * 1e-9
      for ids, rpt in ar_pts.items():
        off = float('nan')
        if px is not None and 1.0 < rpt[0] <= px[-1]:
          off = rpt[1] + float(np.interp(rpt[0], px, py))
        self.tracks[ids].update_onpath(t_live, off, bool(rpt[3]), float(rpt[7]))

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
    if FAR_RAIL_VISION_BOUND and self.honda_bosch_a_radar:
      for i in range(2):
        self.far_rail_hist[i].append(far_rail_model_sample(leads_v3[i]) if len(leads_v3) > i else None)
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

      if ONPATH_RADAR_ADOPT and self.honda_bosch_a_radar:
        onpath = get_onpath_lead(self.v_ego, self.tracks, self.radar_state.leadOne, self.prev_onpath_track_id)
        if onpath is not None:
          self.radar_state.leadOnpath = onpath
        self.prev_onpath_track_id = onpath['radarTrackId'] if onpath is not None else -1

      if YOUNG_TRACK_FLAT_RANGE_BOUND and self.honda_bosch_a_radar:
        t_live = sm.logMonoTime['liveTracks'] * 1e-9
        young_leads = [(self.radar_state.leadOne, leads_v3[0]), (self.radar_state.leadTwo, leads_v3[1])]
        if ONPATH_RADAR_ADOPT and self.honda_bosch_a_radar:
          young_leads.append((self.radar_state.leadOnpath, leads_v3[0]))
        for lead, vis in young_leads:
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

      if FAR_RAIL_VISION_BOUND and self.honda_bosch_a_radar:
        far_leads = [(self.radar_state.leadOne, 0), (self.radar_state.leadTwo, 1)]
        if ONPATH_RADAR_ADOPT:
          far_leads.append((self.radar_state.leadOnpath, 0))
        for lead, slot in far_leads:
          floor = far_rail_vrel_floor(lead, self.far_rail_hist[slot], self.v_ego)
          if floor is not None and lead.vRel < floor:
            dv = floor - lead.vRel
            lead.vRel = floor
            lead.vLead = lead.vLead + dv
            lead.vLeadK = lead.vLeadK + dv
            self.far_rail_bound_count += 1

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
      self.starpilot_radar_state.leadLeft = get_adjacent_lead(self.tracks, sm['carState'].standstill, sm['modelV2'], left=True,
                                                              honda_bosch_a=self.honda_bosch_a_radar)
      self.starpilot_radar_state.leadRight = get_adjacent_lead(self.tracks, sm['carState'].standstill, sm['modelV2'], left=False,
                                                              honda_bosch_a=self.honda_bosch_a_radar)

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
  # D-074: same param, read once, as radar_interface reads it in card; a restart is needed after a change.
  set_bosch_a_u11_scale72(honda_bosch_a_radar and bosch_a_u11_scale72_enabled())
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
