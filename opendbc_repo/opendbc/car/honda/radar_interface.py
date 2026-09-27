#!/usr/bin/env python3
import math
from collections import deque
from dataclasses import dataclass, field

from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.values import DBC
from opendbc.car.interfaces import RadarInterfaceBase


def _create_nidec_can_parser(car_fingerprint):
  radar_messages = [0x400] + list(range(0x430, 0x43A)) + list(range(0x440, 0x446))
  messages = [(m, 20) for m in radar_messages]
  return CANParser(DBC[car_fingerprint][Bus.radar], messages, 1)


# ============================================================================
# Honda Bosch-A 16-slot object bank
# ============================================================================
# 16 CAN-visible object slots. Each slot has 4 main frames (f0..f3, one CAN ID each -- NOT sub-frames
# muxed onto a shared ID) plus one synchronized auxiliary 5th frame. This supersedes any prior model of
# 0x280/0x284/0x288/0x28C as pieces of one object, or of 0x2C8/0x2C9 as a separate "coarse" list: it is
# ONE 16-slot bank with one auxiliary frame per slot. See honda_bosch_a_radar.dbc for the bit geometry.
BOSCH_A_DBC_NAME = 'honda_bosch_a_radar'
BOSCH_A_NUM_SLOTS = 16


def _bosch_a_main_base(slot: int) -> int:
  return 0x280 + 4 * slot if slot < 4 else 0x2D0 + 4 * (slot - 4)


def _bosch_a_aux_id(slot: int) -> int:
  return 0x2C8 + slot if slot < 8 else 0x290 + (slot - 8)


BOSCH_A_MAIN_IDS = [[_bosch_a_main_base(s) + i for i in range(4)] for s in range(BOSCH_A_NUM_SLOTS)]
BOSCH_A_AUX_IDS = [_bosch_a_aux_id(s) for s in range(BOSCH_A_NUM_SLOTS)]
BOSCH_A_ALL_IDS = [addr for ids in BOSCH_A_MAIN_IDS for addr in ids] + BOSCH_A_AUX_IDS

# Publish RadarPoints when the last MAIN object frame arrives. Passive captures prove that slot 15's
# companion frame, 0x297, follows 0x2FF and is the final observed object-family frame in a full sweep:
#
#   ... 0x2FC, 0x2FD, 0x2FE, 0x2FF, 0x297
#
# Keep 0x2FF as the RadarPoint trigger while the companion data remains optional/debug-only. Making
# 0x297 the sole trigger would allow one dropped auxiliary frame to suppress an otherwise-valid point
# update, contrary to the parser's "aux never gates validity" contract.
BOSCH_A_TRIGGER_MSG = BOSCH_A_MAIN_IDS[BOSCH_A_NUM_SLOTS - 1][3]
BOSCH_A_SWEEP_END_MSG = BOSCH_A_AUX_IDS[BOSCH_A_NUM_SLOTS - 1]  # 0x297

# Coherent Bosch-A sweep cadence, measured from 0x280 inter-arrival across Peter's routes:
# median 14.35 Hz (p5 12.5, p95 16.9). This also sets the lead-Kalman dt in radard, so the
# previous round 15 ran the filter ~4.5% fast.
BOSCH_A_FREQ_HZ = 14.35

# Range: f0 raw_range (12-bit, B2:B3 high nibble) -> meters. Firmware q16 = 8*raw_range.
#
# The scale is firmware-exact, not fitted. AC004 converts the internal value with
# (q16 - n) / 128, and q16 = sat16(round(8 * raw_range)), so
#
#     range_m = (8 * raw_range - n) / 128 = raw_range / 16 - n / 128
#
# Corroboration that 1/16 is the designed mapping rather than a coincidence: 8 * 4095 = 32760
# fits int16 with 7 counts to spare, so the *8 exists to make the 12-bit field fill the internal
# word; full scale is 4095/16 = 255.9 m; and /128 (Q7) is this firmware's unit for physical
# quantities throughout. The previous 0.05712 was 16 * 0.00357, and that 0.00357 was solved from
# a single tape point with the offset assumed, so it read progressively short with distance
# (~9% low, -9 m at 60 m against vision).
BOSCH_A_RANGE_SCALE_M = 1.0 / 16.0

# Offset. The firmware term is -n/128, where n is assembled from a configuration word plus a
# runtime addend and is therefore a PER-UNIT CALIBRATION VALUE, not a constant; 335 (-2.617 m) is
# only the fallback the firmware uses when the config word reads zero. -3.0 is retained because it
# sits inside the plausible calibration range and the choice barely moves the residual. Do not
# re-fit this against vision: read it from the radar's own configuration instead.
BOSCH_A_RANGE_OFFSET_M = -3.0

# Azimuth: f0 raw_angle (11-bit, B4:B5 high 3 bits), offset-binary about 1024.
#
# The f3 angular-edge pair independently closes the exact center-angle scale:
#   azimuth_rad = (raw_angle - 1024) / 2048
#
# This supersedes the older empirical 0.032 deg/count fit.
BOSCH_A_AZIMUTH_SCALE_RAD = 1.0 / 2048.0
BOSCH_A_AZIMUTH_CENTER = 1024

# Invalid sentinels (section 3/4/5/6 of the spec).
BOSCH_A_STATUS_INVALID = 0xF
BOSCH_A_RANGE_RAW_INVALID = 0xFFF
BOSCH_A_ANGLE_RAW_INVALID = 0x7FF
BOSCH_A_LIFE_INVALID = 0xFFF

# LIFECYCLE_RAW is a 12-bit counter that advances by 2 per frame index, so it reaches its highest
# even value, 0xFFE, after 2047 frames -- about 137 s of continuous tracking at the ~14.9 Hz sweep
# rate -- and then stops advancing. It is NOT the invalid sentinel (0xFFF): STATUS, range, azimuth
# and track id all stay valid, and the object is still really there.
#
# Measured on 00000232--fc8dad0d18 (device commit 0083ffa, replayed through this parser):
# track 37 was born at route t=442.7 s, saturated at t=580.2 s at an age of 137.4 s, and was then
# observed on every sweep for 121.8 s (1,815 sweeps) while `life_delta == 2 * frame_delta` failed
# every time -- so the range history was cleared every sweep, no point ever matured, and the object
# was published exactly 0 times. Its last published geometry was dRel 38.9 m, yRel -0.1 m: the lead
# we were following. The device's own recording agrees -- liveTracks carries id 37 in 894/894 frames
# of segment 8 and 569/893 of segment 9, then 0 in segments 10-12, and the radar lead goes from
# 1200/1200 frames to 0/1200 across that boundary. Track 34 did the same at an age of 137.5 s.
#
# A saturated counter cannot testify either way about identity, and per D-041/D-042 the safe
# direction is to keep publishing geometry rather than delete a real object: the range-innovation
# gate below still decides whether each sweep is trustworthy, and staleness still retires a genuine
# disappearance. The cost, recorded against D-049: an ID reuse that happens WHILE the counter is
# saturated cannot be detected here at all.
BOSCH_A_LIFE_SATURATED = 0xFFE
BOSCH_A_TRACK_ID_MIN = 1
BOSCH_A_TRACK_ID_MAX = 0x3F
# AUX logical 0x00CA has an explicit 0x3FF invalid sentinel. Firmware proves the normalization below;
# captures strongly support interpreting the active value as previous/current range ratio.
BOSCH_A_RANGE_RATIO_INVALID = 0x3FF
BOSCH_A_LOGICAL_00CA_INVALID = BOSCH_A_RANGE_RATIO_INVALID  # compatibility/debug alias
BOSCH_A_RANGE_RATIO_SCALE = 0.001
BOSCH_A_RANGE_RATIO_OFFSET = 0.5

# The synchronized AUX frame contains an 11-bit offset-binary velocity-like field and a 10-bit
# companion quality/uncertainty field.  The byte locations are now decoded in the DBC.  The exact
# Bosch descriptor name is still being verified, so keep the conversion constants isolated here.
# Capture validation shows active values in [0, 1728], with 0x7FE used as the inactive sentinel.
BOSCH_A_DIRECT_VREL_INVALID = 0x7FE
BOSCH_A_DIRECT_VREL_MIN_RAW = 0
BOSCH_A_DIRECT_VREL_MAX_RAW = 1728
BOSCH_A_DIRECT_VREL_CENTER_RAW = 864
BOSCH_A_DIRECT_VREL_SCALE_MPS = 1.0 / 64.0
# The domain endpoints are SATURATION RAILS: at raw 0 or 1728 the true |vRel| is >= 13.5 m/s and
# the exact value is not recoverable from this field. A rail is therefore a BOUND, not an unknown,
# and it must still be published.
#
# This was briefly treated as "no measurement" and routed to the coast path. That was a safety
# regression, because a stationary car approached at any speed above 13.5 m/s (30 mph) rails on
# EVERY sweep -- so the coast never ended, it outlived BOSCH_A_STALE_S, and the radar point was
# deleted. Measured on route 000001f9 at 29:52: two stopped cars, 88 of 88 active frames on the low
# rail with healthy u10 (78-94), range closing smoothly at -19.4 m/s. The radar lead was dropped,
# radard fell back to the vision lead which reported only -11.4 m/s, and the planner commanded 0.00
# while closing on stopped traffic at 76 m with a 6.6 s TTC. The driver had to intervene.
#
# Publishing the rail understates the closing rate (a stopped car reads as vLead = vEgo - 13.5), and
# that understatement is why it looked worth "fixing". But understating closing still brakes;
# deleting the object does not. Recovering the true value past the rail needs the range channel and
# is deliberately left for a separate, validated change.
BOSCH_A_DIRECT_VREL_RAILS_RAW = (BOSCH_A_DIRECT_VREL_MIN_RAW, BOSCH_A_DIRECT_VREL_MAX_RAW)
# D-063 (replay and static only; road evidence pending): the GATES must read a rail as the bound it
# is, too. The publish path above already does; the range-innovation gate (D-054) and the re-anchor
# test (D-057) did not -- they extrapolated the range at exactly -13.5 m/s. Route 0000025e at 12:03,
# stock ACC: track 59, the lead in lane from 102.8 m, U11 on the low rail on 51% of sweeps while
# the range closed at -15.4 to -17 m/s. The 2-3.5 m/s shortfall accumulated against the anchor, the
# range was rejected, the re-anchor refused because the fitted slope sat more than 3 m/s past the
# railed median, and the lead stayed dark until 41 m. A railed U11 now predicts an INTERVAL of range
# -- from the rail out to this physical cap -- and a range inside it is not an innovation. The cap is
# not a tuning value: it is a closing speed no same-direction or stationary target reaches from a
# car under ~145 km/h, and it keeps a rail from vouching for an unbounded range jump.
# This only lets the gates accept more; nothing is withheld that was published before, and the
# published vRel is still the rail itself.
BOSCH_A_DIRECT_VREL_RAIL_BOUND_MPS = 20.0
# The rail interval only vouches for a track in our own lane. Replayed over 7 routes (STATUS 82, 89):
# with the interval on every track, 21 points were lost, all on tracks 24-32 m off-axis, and the
# over-closers were railed U11s on adjacent-lane tracks (25e track 6, 25f track 33, 262 track 9)
# whose range closed at 7-10 m/s. A 4 m gate kept the lead gains and lost 0 points; 2 m also cleared
# the adjacent-lane over-closers. Off-path tracks keep the exact (pre-D-063) gate.
BOSCH_A_RAIL_INTERVAL_MAX_Y_M = 2.0
# On a DEGRADED sweep (range sigma, existence or u10 flagged) the interval applies only when the RANGE corroborates
# the rail: a least-squares fit over the TAIL of the rejected run plus this sweep (the shortest tail meeting the D-043
# minimum window, 4 samples over 0.25 s) must lie within 3 m/s (the D-043 tolerance) of the rail interval. Otherwise the gate reads the rail
# exactly, as with the toggle off. A degraded sweep is gated at the tight 2.0 m limit because the sweep is
# suspect; the interval must not widen that on the rail's word alone. Replay evidence (STATUS 129):
# - Route 0000025e 6:43 (403 s), track 48: a range walk 47.9 -> 35.3 m admitted through the interval against a
#   0.53 s old baseline, all sweeps degraded, while the rejected run's last five ranges sat at 34.9-36.1 m (fit
#   about -2 m/s, 11 m/s off the rail) and U11 left the rail on the next sweep. A fit over the last 8 sweeps still
#   averaged the finished walk in (about -20 m/s) and admitted it; hence the shortest tail. The admitted rail was coasted for 0.25 s at 35 m
#   and the planner went to -3.23 (vision and toggle-off lead at 42 m, -0.03). With the fit test it is not admitted.
#   (Item 92's 402.912 s single-sweep admission has no run to fit and is read exactly too.)
# - Route 0000025e 12:03, track 59, the case D-063 exists for: degraded on EVERY sweep from 87 m in, admitted at
#   724.233 s against a baseline 2.16 s old. Its rejected run closes at about 16-18 m/s, inside the interval, so it
#   is still admitted. Item 92's first suggestion (exact on every degraded sweep) kept it dark until 32 m, as with
#   the toggle off; a baseline-age floor (0.31 s) kept 12:03 but still admitted the 6:43 walk.
# The D-057 re-anchor already refuses any window holding a degraded sweep, so this only changes the D-054 gate.
# No new number: the window and tolerance are D-043's. A bool so the replay can A/B it.
BOSCH_A_RAIL_INTERVAL_EXACT_WHEN_DEGRADED = True
# The item 92 coast bound is two-sided with the rail interval on. Its LESS-closing side exists to undo a
# rail-interval admission (a rail coasted on a range the interval let in), so it now acts only inside a hold such
# an admission started (`rail_hold`); every other coast keeps the one-sided STATUS 111 bound. Applied to every
# coast it softened three protected brakes in the 26-route replay, each a stale over-closing coast on a track the
# interval never touched: 00000232 1147.2 (-2.25 -> -1.88), 00000266 560.0 (-1.79 -> -1.38) and 00000266 795.4
# (-1.5 crossing 3.75 s later). Replay evidence only (STATUS 129); a bool so the replay can A/B it.
BOSCH_A_RAIL_INTERVAL_DOWN_SIDE_ONLY_ON_RAIL_HOLD = True
# D-063 ships behind this toggle, default off: replay and static evidence only, never driven. With it
# off both gate calls below run `exact`, which is the pre-D-063 gate unchanged.
BOSCH_A_RAIL_INTERVAL_PARAM = "BoschARailInterval"
# The D-063 addendum's coast bound (_bosch_a_coast_vrel) also runs, without the rail interval, when the
# D-053 range-derived vRel toggle is on. The coast is exactly where D-053 cannot act: radard disarms its
# assist on every unmeasured sample. Route 00000268 9:52.3-9:54.7 (STATUS 110): a 5 m range step as track
# 25 moved in made two opening U11 samples (+3.3, +4.1) the trusted vRel; the true closing U11 then failed
# the one-sided check against the stale fit and +4.06 was coasted for 2.35 s while the live, gated range
# closed 52.2 -> 38.3 m (~-6 m/s) and vision agreed. The bound pulls such a coast to within 3 m/s of the
# coast's own fresh range fit. Item 91's two wrong-direction brakes came from the rail-interval ADMISSION,
# not from this bound (item 92), so the bound is split out here, one-sided (more closing only; see
# _bosch_a_coast_vrel). Replay evidence only (STATUS 111).
BOSCH_A_COAST_RANGE_BOUND_PARAM = "RangeDerivedVrel"
# A coast that says the car ahead is reversing (vEgo + coasted vRel < -BOSCH_A_COAST_REVERSING_MARGIN_MPS) gets
# the two-sided bound even outside a rail hold: pulled to within BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS of
# the coast's own fresh range fit. With no fit yet it is floored at vLead = -margin instead. Everywhere else
# the STATUS 129 rule stands (less-closing side only inside a rail hold). Route 00000287 2:39 (STATUS 177): track
# 49 coasted its birth vRel -11.4 for 2.9 s while its range fell at about -4 m/s and ego slowed to 9.6 m/s, so
# the planner saw a lead reversing at -1.8 m/s and asked for -2.87; vision had the car at vRel -6 and the
# radar re-measured -6.8 on the next sweep. Replay: the coast publishes -7.2 instead of -11.4. A plain floor at
# vLead >= -margin only reached -10.8, and widening the down side to 5 m/s on every coast -9.2. STATUS 129's
# three protected brakes are stale over-closing coasts on real slower cars, not reversing ones, so they keep
# the one-sided bound. The point is always kept (D-041/D-042); only an implied reversing speed is bounded. A
# vEgo of None (not yet known) turns this off. Replay evidence only (STATUS 179); rides the same toggles as the
# coast bound (BoschARailInterval or RangeDerivedVrel).
BOSCH_A_COAST_REVERSING_MARGIN_MPS = 1.0
# u10 is a genuine uncertainty on U11, but it is CONFOUNDED WITH DYNAMICS. Measured against an
# event-local reference (quadratic fit to a centred window, derivative at the centre) over 16,834
# frames: median |err| rises 0.26 -> 0.88 -> 1.44 -> 1.95 m/s across u10 bins 0-64 / 64-128 /
# 128-192 / 192-256, but median |a_rel| rises 0.73 -> 2.13 -> 3.51 -> 4.59 m/s^2 alongside it.
# corr(u10,|err|) = +0.40 and corr(u10,|a_rel|) = +0.43. Holding dynamics out, the quality signal is
# real (calm-frame corr +0.52) -- but u10 climbs during genuine hard braking just as reliably.
#
# 511 is the value validated in d5000fe344 by replaying 20 bookmarks through the real
# RadarInterface and radard's Kalman filter, where it collapsed recorded spikes up to -26.5 m/s^2
# aLeadK. It was briefly lowered to 128 on error statistics alone; that undid the validated result
# and caused a measured regression -- on route 000001f3 at 19:27 u10 sat above 128 for 0.81 s during
# a real ~8 m/s^2 lead decel, the coast outlived BOSCH_A_STALE_S, the lead was deleted, and the
# vision fallback injected a 5 m / 6 m/s step that drove a -3.51 m/s^2 brake. Restored here.
#
# Do not re-tune this from offline error statistics. u10's confounding with dynamics means a lower
# threshold preferentially rejects real manoeuvring; the coast paths below are what must stay safe,
# not this number.
BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW = 511

# Multi-sweep velocity/range consistency. The existing per-sweep innovation gate cannot see a
# velocity error at all: over one ~70 ms sweep even a 3 m/s error moves the range by 0.2 m, far
# under its 2-5 m thresholds. Comparing U11 against a range rate fitted over several sweeps does
# have that power.
#
# Scope, measured on Peter's nine flagged events: this catches GROSS disagreement -- the 000001eb
# 6:59 event reported vRel -10.58 m/s while the range was actually opening at +0.46 m/s, an 11 m/s
# contradiction, across a track-identity change. It deliberately does NOT try to catch the milder
# 0.6-2.5 m/s overshoots seen at deceleration onset: a trailing window legitimately lags
# instantaneous velocity during real braking, so a threshold tight enough to catch those would also
# reject genuine hard decels. Those are the u10 gate's job.
#
# The test is ONE-SIDED, and that matters. U11 lags the true closure at a deceleration onset -- at
# 000001f3 19:27 the fitted range rate was -6.7 m/s while U11 still read -2.08 -- so a symmetric
# |U11 - rate| test fires during genuine hard braking and coasts exactly when the velocity is most
# needed. Lag can only make U11 UNDER-report closing while the lead is braking, so only the other
# direction is evidence of a fault: U11 claiming more closing than the geometry can support.
# Checked both ways: 000001eb 6:59 (U11 -10.58 while the range OPENED at +0.46) is rejected;
# the 000001f3 onset is not. In the mirror case, a lead accelerating away, the one-sided test
# coasts a more-conservative velocity, so it fails safe.
BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES = 4
BOSCH_A_VREL_RATE_CHECK_MIN_SPAN_S = 0.25
BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS = 3.0

# Measurement-authority policy. These are replay-derived safety/tuning gates, not recovered Bosch
# constants. Range innovation is measured from the previous accepted observation so a reset cannot
# become the baseline for following sweeps.
BOSCH_A_RANGE_SIGMA_DEGRADED_RAW = 4
BOSCH_A_RANGE_INNOVATION_MAX_M = 2.0
BOSCH_A_RANGE_INNOVATION_HARD_MAX_M = 5.0
BOSCH_A_FALLBACK_RANGE_RATE_MAX_MPS = 50.0
BOSCH_A_USE_TAN_LATERAL_PROJECTION = True

# Accepted-range history is retained for continuity and the adjacent two-point fallback. Rejected
# range resets never enter it, and it is not used for a multi-sample OLS velocity fit.
BOSCH_A_VREL_MAX_SAMPLES = 8

# D-057 (replay and static only; road evidence pending): re-anchor a range-rejected identity on a LASTING,
# clean step. Replay of every range-rejection run on 00000232 / 236 / 237 / 239 / 23a (D-054 + D-055): the 13 runs of
# >= 3 sweeps that RETURNED to the baseline all lasted <= 1.2 s and every one was degraded (existence 0
# on 62-83% of sweeps, U11 railed at -13.5). The lead lockouts were not: 236 track 38 (27.4 s) and 237
# track 31 (20.4 s) had non-degraded tails whose range moved at the U11 rate. A run re-anchors only when
# it has outlasted every returning excursion, its last WINDOW sweeps are all non-degraded with U11
# present, and their range fits a line at the U11 rate (RMS <= MAX_RMS, slope within the D-043 rate
# disagreement). Until then the identity stays coasted, never deleted (D-041). Re-based onto D-055 and
# replayed on 232/236/237/239/23a/23b/23e: 0 point-sweeps lost on every route; restores 236 track 38
# (17.1 s) and 237 track 31 (16.2 s) as the lead and 237 track 63 (51.4 s, non-lead); re-admitted
# measured vRel over-closes the next-1 s range slope by >3 m/s on 2.2 / 2.2 / 0 % of sweeps (236 /
# 237 / 23a) against 5.4 / 5.9 / 2.6 % for the already-published reference.
BOSCH_A_REANCHOR_MIN_SPAN_S = 1.5
BOSCH_A_REANCHOR_WINDOW = 8
BOSCH_A_REANCHOR_MAX_RMS_M = 1.0

# Staleness gate -- TUNING constant, reused plumbing pattern (not a firmware fact). At the observed
# ~15 Hz cadence, 0.20 s is approximately three missed sweeps.
BOSCH_A_STALE_S = 0.20


@dataclass
class _BoschASlotState:
  last_seen_nanos: int | None = None

  # Firmware logical-ID companion data -- telemetry/debug only for now, never a RadarPoint validity
  # gate. 0x00C9 has a firmware transform but no proven physical meaning; 0x00CA has an explicit
  # invalid sentinel and its physical meaning remains unresolved.
  logical_00c9_raw: float = float('nan')
  logical_00ca_raw: float = float('nan')
  direct_vrel_raw: int | None = None
  direct_vrel_uncertainty_raw: int | None = None

  def reset(self):
    self.last_seen_nanos = None
    self.logical_00c9_raw = float('nan')
    self.logical_00ca_raw = float('nan')
    self.direct_vrel_raw = None
    self.direct_vrel_uncertainty_raw = None


@dataclass
class _BoschATrackState:
  """Persistent state for one Bosch CAN object identity, independent of wire slot."""
  track_id: int
  prev_frame_idx: int | None = None
  prev_life: int | None = None
  last_seen_nanos: int | None = None
  wire_slot: int | None = None
  samples: deque = field(default_factory=lambda: deque(maxlen=BOSCH_A_VREL_MAX_SAMPLES))
  # (time, range) of the last observation that PASSED the range-innovation gate, accepted or coasted
  # (D-054). The gate measures the next sweep against it. It is never a velocity-derivative baseline:
  # `samples` above stays accepted-only, and a range-rejected sweep never moves either of them.
  range_anchor: tuple[float, float] | None = None
  # D-057: the current run of range-REJECTED sweeps, (time, range, U11 or None, degraded).
  # Cleared by any accepted sweep and by a lifecycle discontinuity.
  rejected_run: list = field(default_factory=list)
  # D-062: the current run of range-PASSED sweeps whose vRel failed the rate check, same tuple shape.
  # Cleared by any rate-consistent sweep, any range rejection and a lifecycle discontinuity.
  inconsistent_run: list = field(default_factory=list)
  rejoin_samples: list | None = None  # D-059: gated ranges since a join, until a fresh rate fit agrees with vRel
  # D-063: the current D-059 hold was started (or joined) by a rail-interval admission. Only such a hold's coast
  # may be pulled LESS closing toward its fresh fit (_bosch_a_coast_vrel); cleared whenever the hold ends.
  rail_hold: bool = False
  last_trusted_vrel: float | None = None
  last_trusted_vrel_nanos: int | None = None


def _bosch_a_direct_vrel(raw_value: int | float | None,
                         uncertainty_raw: int | float | None = None) -> float | None:
  """Decode the capture-validated AUX relative-velocity candidate.

  None means that AUX was absent/invalid and the caller should use the existing fallback policy. The [0, 1728]
  active domain is deliberately enforced here because values above the observed +13.5 m/s rail have
  not appeared on active objects; 0x7FE is the observed inactive sentinel.
  """
  if raw_value is None:
    return None
  raw = int(raw_value)
  if raw == BOSCH_A_DIRECT_VREL_INVALID:
    return None
  if not BOSCH_A_DIRECT_VREL_MIN_RAW <= raw <= BOSCH_A_DIRECT_VREL_MAX_RAW:
    return None
  # u10 is retained as a raw quality indicator because its physical units remain unresolved.  The
  # conservative threshold is evidence-backed tuning, not a recovered firmware validity rule.
  if uncertainty_raw is not None and int(uncertainty_raw) > BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW:
    return None
  return (raw - BOSCH_A_DIRECT_VREL_CENTER_RAW) * BOSCH_A_DIRECT_VREL_SCALE_MPS


def _bosch_a_range_ratio(raw_value: int | float | None) -> float | None:
  if raw_value is None:
    return None
  raw = int(raw_value)
  if raw == BOSCH_A_RANGE_RATIO_INVALID or not 0 <= raw < BOSCH_A_RANGE_RATIO_INVALID:
    return None
  return BOSCH_A_RANGE_RATIO_OFFSET + BOSCH_A_RANGE_RATIO_SCALE * raw


def _bosch_a_range_ratio_vrel(raw_value: int | float | None, d_rel: float, dt: float) -> float | None:
  """Return the range rate implied by the empirical previous/current range ratio."""
  ratio = _bosch_a_range_ratio(raw_value)
  if ratio is None or dt <= 0.0 or not math.isfinite(d_rel):
    return None
  return d_rel * (1.0 - ratio) / dt


def _bosch_a_direct_vrel_interval(direct_vrel: float, exact: bool = False) -> tuple[float, float]:
  """D-063: the vRel interval a decoded U11 vouches for. A rail is a one-sided bound, anything else exact."""
  low_rail = (BOSCH_A_DIRECT_VREL_MIN_RAW - BOSCH_A_DIRECT_VREL_CENTER_RAW) * BOSCH_A_DIRECT_VREL_SCALE_MPS
  high_rail = (BOSCH_A_DIRECT_VREL_MAX_RAW - BOSCH_A_DIRECT_VREL_CENTER_RAW) * BOSCH_A_DIRECT_VREL_SCALE_MPS
  if exact:
    return direct_vrel, direct_vrel
  if direct_vrel <= low_rail:
    return -BOSCH_A_DIRECT_VREL_RAIL_BOUND_MPS, direct_vrel
  if direct_vrel >= high_rail:
    return direct_vrel, BOSCH_A_DIRECT_VREL_RAIL_BOUND_MPS
  return direct_vrel, direct_vrel


def _bosch_a_distance_to_interval(value: float, interval: tuple[float, float]) -> float:
  return max(0.0, interval[0] - value, value - interval[1])


def _bosch_a_range_innovation_rejected(baseline: tuple[float, float], now_s: float, dRel: float,
                                       direct_vrel: float | None, ratio: float | None, degraded: bool,
                                       exact: bool = False) -> bool:
  """Does this range contradict one (time, range) baseline? See the D-054 comment at the call site."""
  previous_time, previous_range = baseline
  dt = now_s - previous_time
  if dt <= 0.0:
    return True
  residuals_m = []
  if direct_vrel is not None:
    low, high = _bosch_a_direct_vrel_interval(direct_vrel, exact)
    residuals_m.append(_bosch_a_distance_to_interval(dRel, (previous_range + low * dt, previous_range + high * dt)))
  if ratio is not None:
    residuals_m.append(abs(previous_range - dRel * ratio))
  if not residuals_m:
    return abs((dRel - previous_range) / dt) > BOSCH_A_FALLBACK_RANGE_RATE_MAX_MPS
  innovation_m = min(residuals_m)
  return (innovation_m > BOSCH_A_RANGE_INNOVATION_HARD_MAX_M or
          (degraded and innovation_m > BOSCH_A_RANGE_INNOVATION_MAX_M))


def _bosch_a_measurement_degraded(range_sigma_raw: int, existence_raw: int,
                                  direct_vrel_uncertainty_raw: int | None) -> bool:
  range_quality_bad = range_sigma_raw >= BOSCH_A_RANGE_SIGMA_DEGRADED_RAW or existence_raw in (0, 0x7F)
  velocity_quality_bad = (direct_vrel_uncertainty_raw is not None and
                          direct_vrel_uncertainty_raw > BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW)
  return range_quality_bad or velocity_quality_bad


def _bosch_a_lasting_clean_step(run: list, exact: bool = False) -> bool:
  """D-057: True when the trailing window of a range-rejected run is long, clean and moving at the U11 rate."""
  if len(run) < BOSCH_A_REANCHOR_WINDOW or run[-1][0] - run[0][0] < BOSCH_A_REANCHOR_MIN_SPAN_S:
    return False
  window = run[-BOSCH_A_REANCHOR_WINDOW:]
  if any(degraded or u11 is None for _, _, u11, degraded in window):
    return False
  ts = [w[0] for w in window]
  ds = [w[1] for w in window]
  n = len(window)
  t_mean = sum(ts) / n
  d_mean = sum(ds) / n
  denom = sum((t - t_mean) ** 2 for t in ts)
  if denom <= 1e-9:
    return False
  rate = sum((t - t_mean) * (d - d_mean) for t, d in zip(ts, ds, strict=True)) / denom
  rms = (sum((d - (d_mean + rate * (t - t_mean))) ** 2 for t, d in zip(ts, ds, strict=True)) / n) ** 0.5
  u11 = sorted(w[2] for w in window)[n // 2]
  return (rms <= BOSCH_A_REANCHOR_MAX_RMS_M and
          _bosch_a_distance_to_interval(rate, _bosch_a_direct_vrel_interval(u11, exact)) <= BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS)


def _bosch_a_fresh_range_rate(run: list) -> float | None:
  """Least-squares range rate over a run of (t_s, dRel, ...) tuples that grows on EVERY sweep of a coast
  (`rejoin_samples`, `inconsistent_run`), i.e. one that is not frozen the way `samples` is during a coast
  (D-062). None until the D-043 minimum window (4 samples over 0.25 s) is met."""
  if len(run) < BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES or run[-1][0] - run[0][0] < BOSCH_A_VREL_RATE_CHECK_MIN_SPAN_S:
    return None
  ts = [w[0] for w in run]
  ds = [w[1] for w in run]
  n = len(run)
  t_mean = sum(ts) / n
  d_mean = sum(ds) / n
  denom = sum((t - t_mean) ** 2 for t in ts)
  if denom <= 1e-9:
    return None
  return sum((t - t_mean) * (d - d_mean) for t, d in zip(ts, ds, strict=True)) / denom


def _bosch_a_trailing_fit_window(run: list) -> list:
  """The shortest tail of `run` that meets the D-043 minimum window (BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES samples
  over BOSCH_A_VREL_RATE_CHECK_MIN_SPAN_S), or the whole run when it is shorter. The rate the range has NOW, not
  the average over a step that is already over (STATUS 129, 0000025e 6:43)."""
  for start in range(len(run) - BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES, -1, -1):
    if run[-1][0] - run[start][0] >= BOSCH_A_VREL_RATE_CHECK_MIN_SPAN_S:
      return run[start:]
  return run


def _bosch_a_coast_vrel(track, rail_interval: bool, range_bound: bool = False, v_ego: float | None = None) -> float:
  """The vRel a coast publishes. Off (pre-D-063): the last trusted vRel, verbatim. With BoschARailInterval on
  (D-063 addendum, STATUS 92): the same value bounded to within BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS of
  a FRESH fit over the ranges of the coast itself, when one exists. Replayed on 0000025e 6:43 (track 48): the
  rail interval admitted a slot-merge range walk, the D-059 hold then coasted the -13.5 rail for 1.5 s while
  its own post-join fit read +0.8 m/s and said so (fresh_ok false on every sweep), and the planner asked for
  -3.45 m/s^2 against a lead the log and vision put at -1..-3 m/s. With the bound, replay of that window
  bottomed at -2.39 and never crossed -3.0. The hold's one-sided law (a vRel that over-closes the fresh
  range fit by > 3 m/s is not trusted) is applied to the value it coasts, both ways, so a stale opening
  vRel is pulled toward a closing fit once one exists. Never a one-sweep derivative: the fit is the D-043
  multi-sample fit, and with fewer than 4 fresh samples (0.25 s) the coast is unchanged. That is why it
  cannot act on 0000025e 12:05 (+11.1 coasted for 0.2 s at track birth, no fresh samples yet) nor on the
  first 5 sweeps after the 6:43 re-root, which still coast the rail. The point is always kept (D-041/D-042).
  Replay evidence only (STATUS 92).

  With only RangeDerivedVrel on (`range_bound`, STATUS 111) the bound is ONE-SIDED, D-053's rule: a coast may
  be made more closing, never less. The two-sided clamp without the rail interval softened 6 protected
  brakes on the 20-route replay (237 9:58.5 -3.10 -> -2.38, 266 8:04 -1.98 -> -1.48, 266 9:20.9 -1.66 ->
  -1.11, ...): the down side exists to undo a rail-interval admission, which this path never makes.

  With the rail interval on, the down side is likewise limited to a coast inside a hold that a rail-interval
  admission started (`track.rail_hold`, STATUS 129); every other coast gets the one-sided bound. Applied to every
  coast, the down side softened three protected brakes in the 26-route replay (00000232 1147.2 -2.25 -> -1.88,
  00000266 560.0 -1.79 -> -1.38, 00000266 795.4 -1.5 crossing 3.75 s later), none of them near a rail admission.

  Either toggle on, a coast that implies the car ahead is reversing (v_ego + vRel < -BOSCH_A_COAST_REVERSING_MARGIN_MPS)
  also gets the down side, or with no fit a floor at vLead = -margin (route 00000287 2:39, STATUS 179)."""
  vrel = track.last_trusted_vrel
  if not (rail_interval or range_bound):
    return vrel
  rate = None
  if track.rejoin_samples is not None:
    rate = _bosch_a_fresh_range_rate(track.rejoin_samples)
  if rate is None:
    rate = _bosch_a_fresh_range_rate(track.inconsistent_run)
  reversing = v_ego is not None and v_ego + vrel < -BOSCH_A_COAST_REVERSING_MARGIN_MPS
  if rate is None:
    if reversing:
      vrel = max(vrel, -(v_ego + BOSCH_A_COAST_REVERSING_MARGIN_MPS))
    return vrel
  vrel = min(vrel, rate + BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS)
  if reversing or (rail_interval and (track.rail_hold or not BOSCH_A_RAIL_INTERVAL_DOWN_SIDE_ONLY_ON_RAIL_HOLD)):
    vrel = max(vrel, rate - BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS)
  return vrel


def _bosch_a_rail_interval_enabled() -> bool:
  """BoschARailInterval, read once at startup the way interface.py reads BoschARadar. Any failure,
  including a params_pyx.so that predates the key, means off: the pre-D-063 gates."""
  try:
    from openpilot.common.params import Params
    return bool(Params().get_bool(BOSCH_A_RAIL_INTERVAL_PARAM))
  except Exception:
    return False


def _bosch_a_coast_range_bound_enabled() -> bool:
  """RangeDerivedVrel, read once at startup like BoschARailInterval. Any failure means off: coasts publish
  the last trusted vRel verbatim, as before STATUS 111."""
  try:
    from openpilot.common.params import Params
    return bool(Params().get_bool(BOSCH_A_COAST_RANGE_BOUND_PARAM))
  except Exception:
    return False


def _create_bosch_a_can_parser(CP):
  messages = [(addr, BOSCH_A_FREQ_HZ) for addr in BOSCH_A_ALL_IDS]
  # Bus.radar selects the Bosch-A DBC; the object/fusion feed itself is
  # physically on the camera-side ACC-CAN.
  return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, CanBus(CP).camera)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.radar_off_can = CP.radarUnavailable
    self.bosch_a_radar = (not self.radar_off_can and Bus.radar in DBC[CP.carFingerprint] and
                           DBC[CP.carFingerprint][Bus.radar] == BOSCH_A_DBC_NAME)
    # Ego speed, set by card before each update (STATUS 179's reversing-coast bound). None until then.
    self.v_ego: float | None = None

    if self.radar_off_can:
      self.rcp = None
      self.trigger_msg = 0x445
    elif self.bosch_a_radar:
      self.rcp = _create_bosch_a_can_parser(CP)
      self.trigger_msg = BOSCH_A_TRIGGER_MSG
      self._slots = [_BoschASlotState() for _ in range(BOSCH_A_NUM_SLOTS)]
      self._tracks: dict[int, _BoschATrackState] = {}
      self._slot_track_ids: list[int | None] = [None] * BOSCH_A_NUM_SLOTS
      self._last_trigger_nanos = -1
      self.rail_interval = _bosch_a_rail_interval_enabled()
      self.coast_range_bound = _bosch_a_coast_range_bound_enabled()
    else:
      # Nidec
      self.rcp = _create_nidec_can_parser(CP.carFingerprint)
      self.trigger_msg = 0x445
      self.track_id = 0
      self.radar_fault = False
      self.radar_wrong_config = False

    self.updated_messages = set()

  def update(self, can_strings):
    if self.radar_off_can or self.rcp is None:
      return super().update(None)

    vls = self.rcp.update(can_strings)
    self.updated_messages.update(vls)

    if self.trigger_msg not in self.updated_messages:
      if self.bosch_a_radar and self._last_trigger_nanos >= 0:
        now = self.rcp._last_update_nanos
        if (now - self._last_trigger_nanos) * 1e-9 > BOSCH_A_STALE_S:
          return self._bosch_a_stale_radardata()
      return None

    rr = self._update(self.updated_messages)
    self.updated_messages.clear()
    return rr

  def _bosch_a_stale_radardata(self):
    # Whole-bus silence: clear every live point/history and emit an EMPTY RadarData (not None) so
    # radard drops any lead within a cycle instead of freezing a phantom. The next observation starts
    # a fresh incarnation for its CAN identity.
    self.pts.clear()
    self._tracks.clear()
    self._slot_track_ids = [None] * BOSCH_A_NUM_SLOTS
    for slot_state in self._slots:
      slot_state.reset()
    self._last_trigger_nanos = -1
    stale = structs.RadarData()
    if not self.rcp.can_valid:
      stale.errors.canError = True
    stale.errors.radarUnavailableTemporary = True
    return stale

  def _bosch_a_retire_track(self, track_id: int):
    self._tracks.pop(track_id, None)
    self.pts.pop(track_id, None)
    for slot, slot_track_id in enumerate(self._slot_track_ids):
      if slot_track_id == track_id:
        self._slot_track_ids[slot] = None

  def _bosch_a_retire_stale_tracks(self, now: int):
    for track_id, track in list(self._tracks.items()):
      if track.last_seen_nanos is not None and (now - track.last_seen_nanos) * 1e-9 > BOSCH_A_STALE_S:
        self._bosch_a_retire_track(track_id)

  def _update(self, updated_messages):
    if self.bosch_a_radar:
      return self._update_bosch_a(updated_messages)
    return self._update_nidec(updated_messages)

  def _update_bosch_a(self, updated_messages):
    ret = structs.RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True

    now = self.rcp._last_update_nanos
    self._last_trigger_nanos = now
    self._bosch_a_retire_stale_tracks(now)

    observations = []

    for slot in range(BOSCH_A_NUM_SLOTS):
      f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[slot]
      aux = BOSCH_A_AUX_IDS[slot]
      st = self._slots[slot]

      if not (f0 in updated_messages and f1 in updated_messages and
              f2 in updated_messages and f3 in updated_messages):
        # Incomplete main-frame set: a missing CAN frame must not be treated as a lifecycle mismatch or
        # death/replacement. Logical tracks are retired independently by their global staleness gate.
        continue

      v0 = self.rcp.vl[f0]
      v1 = self.rcp.vl[f1]
      v2 = self.rcp.vl[f2]
      v3 = self.rcp.vl[f3]

      idx0 = int(v0['FRAME_IDX'])
      if not (idx0 == int(v1['FRAME_IDX']) == int(v2['FRAME_IDX']) == int(v3['FRAME_IDX'])):
        # The four main frames don't share a common cycle index -- not a coherent observation this
        # window. Only combine main-frame data from a coherent common frame index (section 2).
        continue

      status = int(v0['STATUS'])
      range_raw = int(v0['RANGE_RAW'])
      angle_raw = int(v0['AZIMUTH_RAW'])
      range_sigma_raw = int(v0['RANGE_SIGMA_RAW'])
      existence_raw = int(v1['OBJECT_EXISTENCE_PROBABILITY_RAW'])
      life = int(v2['LIFECYCLE_RAW'])
      track_id = int(v3['TRACK_ID'])
      track_id_valid = BOSCH_A_TRACK_ID_MIN <= track_id <= BOSCH_A_TRACK_ID_MAX
      st.last_seen_nanos = now
      direct_vrel_raw = None
      direct_vrel_uncertainty_raw = None
      range_ratio_raw = None

      # Attach synchronized companion data only when its cycle matches. Missing AUX never invalidates
      # an otherwise coherent F0-F3 object; it only removes independent motion/quality evidence.
      if aux in updated_messages:
        av = self.rcp.vl[aux]
        if int(av['FRAME_IDX']) == idx0:
          direct_vrel_raw = int(av['REL_VELOCITY_RAW'])
          direct_vrel_uncertainty_raw = int(av['REL_VELOCITY_UNCERTAINTY_RAW'])
          range_ratio_raw = int(av['RANGE_RATIO_RAW'])
          logical_00c9_raw = av['FW_LID_00C9_RAW']
          logical_00ca_raw = av['FW_LID_00CA_RAW']
          st.logical_00c9_raw = logical_00c9_raw
          st.logical_00ca_raw = (
            logical_00ca_raw if logical_00ca_raw != BOSCH_A_LOGICAL_00CA_INVALID else float('nan')
          )
          st.direct_vrel_raw = direct_vrel_raw
          st.direct_vrel_uncertainty_raw = direct_vrel_uncertainty_raw

      object_valid = (status != BOSCH_A_STATUS_INVALID and range_raw != BOSCH_A_RANGE_RAW_INVALID and
                      angle_raw != BOSCH_A_ANGLE_RAW_INVALID and life != BOSCH_A_LIFE_INVALID)

      observations.append({
        'slot': slot,
        'frame_idx': idx0,
        'life': life,
        'track_id': track_id,
        'track_id_valid': track_id_valid,
        'object_valid': object_valid,
        'range_sigma_raw': range_sigma_raw,
        'existence_raw': existence_raw,
        'direct_vrel_raw': direct_vrel_raw,
        'direct_vrel_uncertainty_raw': direct_vrel_uncertainty_raw,
        'range_ratio_raw': range_ratio_raw,
      })

    # First collapse duplicate wire observations of one CAN identity. The dictionary is also the
    # output uniqueness boundary: one valid Bosch identity can never create two RadarPoints.
    valid_by_id = {}
    # D-055 (replay and static only; road evidence pending): an identity valid in ANY slot this sweep
    # is decided by its own valid observation below, never hidden by an invalid one, mirroring the
    # slot-replacement guard. Only an accept re-creates a hidden point; a coast updates an existing
    # one. So when the radar migrated an object to another slot and the old slot went invalid in the
    # same sweep, the hide below deleted a point the coast would have kept. Measured on 00000232 /
    # 236 / 237 / 239 / 23a: 2,252 withheld point-sweeps, 504 of them the lead (00000237 track 9:
    # 21.2 s dark). On the fresh routes 0000023b / 23e (driven on D-054, 0756f810): 0 point-sweeps
    # lost, 9 + 331 restored (33 lead), all coasts — no new measured vRel enters control.
    valid_this_sweep = {o['track_id'] for o in observations if o['object_valid'] and o['track_id_valid']}
    for observation in observations:
      if not (observation['object_valid'] and observation['track_id_valid']):
        # An invalid observation ends publication for the object currently occupying this wire slot,
        # but it does not immediately destroy the persistent state. The object may be multiplexed to
        # another slot or may return before the per-identity stale deadline; a later lifecycle break
        # or staleness expiry will clear its derivative history.
        ids_to_hide = {self._slot_track_ids[observation['slot']]}
        if observation['track_id_valid']:
          ids_to_hide.add(observation['track_id'])
        for invalid_id in ids_to_hide - {None} - valid_this_sweep:
          self.pts.pop(invalid_id, None)
        continue
      track_id = observation['track_id']
      current = valid_by_id.get(track_id)
      if current is None:
        valid_by_id[track_id] = observation
        continue

      # Prefer the wire slot currently associated with the persistent state. If neither candidate is
      # preferred, retain the lower slot for deterministic handling of a malformed duplicate frame.
      track = self._tracks.get(track_id)
      current_score = (0 if track is not None and track.wire_slot == current['slot'] else 1, current['slot'])
      candidate_score = (0 if track is not None and track.wire_slot == observation['slot'] else 1,
                         observation['slot'])
      if candidate_score < current_score:
        valid_by_id[track_id] = observation

    valid_ids = set(valid_by_id)
    for track_id, observation in sorted(valid_by_id.items(), key=lambda item: item[1]['slot']):
      slot = observation['slot']
      idx0 = observation['frame_idx']
      life = observation['life']

      # A wire-slot replacement ends publication for the old occupant, but not its persistent
      # identity/history. If the old ID is still valid in another slot this sweep, keep its point;
      # otherwise hide it until that ID returns or reaches its own stale deadline.
      old_id = self._slot_track_ids[slot]
      if old_id is not None and old_id != track_id and old_id not in valid_ids:
        self.pts.pop(old_id, None)

      track = self._tracks.get(track_id)
      if track is None:
        track = _BoschATrackState(track_id=track_id)
        self._tracks[track_id] = track

      same_incarnation = False
      if track.prev_frame_idx is not None and track.prev_life is not None:
        frame_delta = (idx0 - track.prev_frame_idx) & 0xF
        life_delta = (life - track.prev_life) & 0xFFF
        same_incarnation = life_delta == 2 * frame_delta
        if not same_incarnation and life == BOSCH_A_LIFE_SATURATED and track.prev_life == BOSCH_A_LIFE_SATURATED:
          # The counter is pinned at its maximum and can no longer advance (see the constant's
          # evidence block). Without this, an object tracked for ~137 s is deleted for as long as it
          # remains visible -- measured at 121.8 s of continuous suppression of the followed lead.
          same_incarnation = True

      if not same_incarnation:
        # The CAN identity remains the externally-visible key, but a lifecycle discontinuity starts a
        # new incarnation and must not inherit the previous object's range-rate history.
        track.samples.clear()
        track.range_anchor = None
        track.rejected_run.clear()
        track.inconsistent_run.clear()
        track.rejoin_samples = None
        track.rail_hold = False
        track.last_trusted_vrel = None
        track.last_trusted_vrel_nanos = None
        self.pts.pop(track_id, None)

      v0 = self.rcp.vl[BOSCH_A_MAIN_IDS[slot][0]]
      range_raw = int(v0['RANGE_RAW'])
      angle_raw = int(v0['AZIMUTH_RAW'])
      dRel = BOSCH_A_RANGE_SCALE_M * range_raw + BOSCH_A_RANGE_OFFSET_M
      azimuth_rad = BOSCH_A_AZIMUTH_SCALE_RAD * (angle_raw - BOSCH_A_AZIMUTH_CENTER)
      # The firmware's internal geometry path uses tan(angle) for a forward-axis distance.  The
      # Bosch object range is consumed as that forward-axis quantity here, so use the same projection
      # rather than treating it as radial/slant range.  Keep the switch explicit while the final
      # output bridge remains under static review.
      #
      # Sign: AZIMUTH_RAW > center (positive azimuth_rad) is a LEFT-of-center detection in car frame's
      # y axis (left is positive), matching the Nidec RadarPoint.yRel contract. Confirmed against real
      # captures 2026-08-22: a stationary cluster of queued vehicles visible on the left in the road
      # camera was rendering on the right in both the Qt and raylib radar-track overlays with the
      # previously-flipped sign.
      lateral_projection = math.tan if BOSCH_A_USE_TAN_LATERAL_PROJECTION else math.sin
      yRel = dRel * lateral_projection(azimuth_rad)

      now_s = now * 1e-9
      direct_vrel_raw = observation['direct_vrel_raw']
      direct_vrel_uncertainty_raw = observation['direct_vrel_uncertainty_raw']
      direct_vrel = _bosch_a_direct_vrel(direct_vrel_raw, direct_vrel_uncertainty_raw)
      live_direct_vrel = _bosch_a_direct_vrel(direct_vrel_raw)
      range_ratio_raw = observation['range_ratio_raw']

      # A live U11 rejected solely by the conservative U10 qualification threshold is neither an
      # unavailable velocity nor permission to synthesize a one-sweep range derivative. It is also
      # NOT permission to skip range-innovation checking below: u10 correlates with range_sigma in
      # replay data, so a high-u10 sweep is exactly the condition where a bad/discontinuous range
      # (slot migration, reset) is most likely, not less likely. Range acceptance is therefore
      # decided on the same terms as every other sweep first; only once the range clears that gate
      # does a high-u10 U11 fall back to coasting instead of publishing a synthesized derivative.
      high_u10_live_vrel = (direct_vrel is None and live_direct_vrel is not None and
                            direct_vrel_uncertainty_raw is not None and
                            direct_vrel_uncertainty_raw > BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW)

      # Qualified U11 and the range-ratio field are independent corroboration paths for the range;
      # high-U10 U11 is deliberately excluded from this decision.
      #
      # D-054: a sweep is range-rejected only if it contradicts BOTH the last ACCEPTED sample and
      # `range_anchor`, the last range that passed this gate (a velocity coast also advances it). Each
      # baseline on its own locked a real object out, measured through this parser on 00000232 / 236 /
      # 237 / 239 / 23a:
      # - Accepted sample only (the parser before D-054). A coast held it still while the range kept
      #   moving, and every later sweep was predicted across the growing gap with the very U11 the coast
      #   had just distrusted. 00000232 track 43, the followed lead pulling away 78.5 -> 84.5 m: the
      #   D-043 rate check coasted four sweeps, the error grew 0.86 / 1.12 / 1.53 / 1.87 / 2.11 m, the
      #   degraded 2.0 m limit rejected it, the point was deleted after BOSCH_A_STALE_S, and radar lost
      #   the lead for 15 s while it closed from 84 m to 27 m.
      # - Anchor only (the first D-054 draft). 00000237 track 12, a new object at 25 m whose range walked
      #   out to 28.06 m while U11 said -2 m/s. The rate check rightly coasted the walk, the walk became
      #   the baseline, and the real ranges (25.3 m closing to 17 m) were rejected against it for 53 s
      #   while the accepted sample still tracked them.
      # The recorded range resets this gate exists for contradict both baselines.
      previous_sample = track.samples[-1] if track.samples else None
      range_anchor = track.range_anchor
      ratio_vrel = None
      range_rejected = False
      rail_admitted = False
      degraded = _bosch_a_measurement_degraded(
        observation['range_sigma_raw'], observation['existence_raw'], direct_vrel_uncertainty_raw,
      )
      if range_anchor is not None:
        ratio = _bosch_a_range_ratio(range_ratio_raw)
        # Deliberately still timed from the last ACCEPTED sample, as before D-054: changing a
        # published vRel is a separate decision, recorded as open in STATUS.md.
        if previous_sample is not None and now_s > previous_sample[0]:
          ratio_vrel = _bosch_a_range_ratio_vrel(range_ratio_raw, dRel, now_s - previous_sample[0])
        baselines = [range_anchor] if previous_sample in (None, range_anchor) else [range_anchor, previous_sample]
        # D-063: a railed U11 vouches for an interval of range, but only with the toggle on and only
        # for a track in our lane; otherwise the gate reads the rail as the exact value, as before.
        exact_gate = not self.rail_interval or abs(yRel) > BOSCH_A_RAIL_INTERVAL_MAX_Y_M
        if not exact_gate and degraded and BOSCH_A_RAIL_INTERVAL_EXACT_WHEN_DEGRADED:
          # A DEGRADED sweep gets the interval only when the range corroborates the rail: a fit over the recent
          # rejected run plus this sweep moves at a railed speed (BOSCH_A_RAIL_INTERVAL_EXACT_WHEN_DEGRADED).
          run_rate = _bosch_a_fresh_range_rate(_bosch_a_trailing_fit_window(track.rejected_run + [(now_s, dRel)]))
          exact_gate = (run_rate is None or direct_vrel is None or
                        _bosch_a_distance_to_interval(run_rate, _bosch_a_direct_vrel_interval(direct_vrel)) >
                        BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS)
        range_rejected = all(_bosch_a_range_innovation_rejected(baseline, now_s, dRel, direct_vrel, ratio, degraded, exact=exact_gate)
                             for baseline in baselines)
        rail_admitted = not exact_gate and not range_rejected and all(
          _bosch_a_range_innovation_rejected(baseline, now_s, dRel, direct_vrel, ratio, degraded, exact=True)
          for baseline in baselines)

      if range_rejected:
        track.inconsistent_run.clear()
        track.rejected_run.append((now_s, dRel, direct_vrel, degraded))
        if _bosch_a_lasting_clean_step(track.rejected_run, exact=exact_gate):
          rail_admitted = not exact_gate and not _bosch_a_lasting_clean_step(track.rejected_run, exact=True)
          # D-057: the step has outlasted every returning excursion measured, cleanly and at the U11
          # rate. Re-root the accepted history and the anchor on it and gate this sweep as passed.
          recent = track.rejected_run[-BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES:]
          track.samples.clear()
          track.samples.extend((t, d) for t, d, _, _ in recent[:-1])
          track.range_anchor = recent[-2][:2]
          previous_sample = track.samples[-1]
          range_anchor = track.range_anchor
          range_rejected = False
          track.rejected_run.clear()
      else:
        if track.rejected_run:
          # D-059: a join. The range passed only after a rejection run, so `samples` straddle the gap.
          track.rejoin_samples = []
          track.rail_hold = False
        track.rejected_run.clear()
      if rail_admitted:
        if track.rejoin_samples is None:
          track.rejoin_samples = []
        track.rail_hold = True

      if range_rejected:
        # Keep the last trusted point briefly as an unmeasured coast. The rejected geometry is not
        # published and never becomes the baseline for a later derivative or for this gate.
        accepted_fresh = range_anchor is not None and now_s - range_anchor[0] <= BOSCH_A_STALE_S
        point = self.pts.get(track_id)
        if accepted_fresh and point is not None:
          point.measured = False
        else:
          self.pts.pop(track_id, None)
        track.prev_frame_idx = idx0
        track.prev_life = life
        track.last_seen_nanos = now
        track.wire_slot = slot
        for old_slot, old_id in enumerate(self._slot_track_ids):
          if old_slot != slot and old_id == track_id:
            self._slot_track_ids[old_slot] = None
        self._slot_track_ids[slot] = track_id
        continue

      # The range passed the gate: it is the gate's baseline from here on, whatever happens to vRel.
      # Only a range that was actually GATED can advance it. With no anchor there was no gate, so a
      # coast now (a high-u10 birth) would root the gate on an unchecked, unpublished range: measured
      # on 00000239 that withheld 2,236 sweeps the pre-D-054 parser published, rejecting later sweeps
      # 2-17 m off such a birth range. The first ACCEPTED sample below roots the anchor instead.
      if range_anchor is not None:
        track.range_anchor = (now_s, dRel)

      # Multi-sweep consistency: does the range actually move the way this velocity claims?
      # Fitted over the accepted range history, so it is immune to the single-sweep blindness above.
      vrel_candidate = direct_vrel if direct_vrel is not None else ratio_vrel
      vrel_inconsistent = False
      if vrel_candidate is not None and len(track.samples) >= BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES - 1:
        ts = [sample[0] for sample in track.samples] + [now_s]
        ds = [sample[1] for sample in track.samples] + [dRel]
        span = ts[-1] - ts[0]
        if span >= BOSCH_A_VREL_RATE_CHECK_MIN_SPAN_S:
          n = len(ts)
          t_mean = sum(ts) / n
          d_mean = sum(ds) / n
          denom = sum((t - t_mean) ** 2 for t in ts)
          if denom > 1e-9:
            # strict=True: ts and ds are same-length by construction. A silent truncation here
            # would bias the fitted rate and weaken the one-sided gate rather than erroring.
            rate = sum((t - t_mean) * (d - d_mean) for t, d in zip(ts, ds, strict=True)) / denom
            # One-sided: only U11 claiming MORE closing than the range supports is a fault.
            vrel_inconsistent = vrel_candidate < rate - BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS

      # D-062: `samples` only grow on accepted sweeps, so during a coast the fit above is frozen. If the
      # lead turns from opening to closing, U11 pulls away from that stale rate and the check latches: route
      # 00000258 43:29-43:46, track 13 held vRel -0.45 for 12.7 s (fit frozen while it opened at +2.8 m/s)
      # as its range fell 124 -> 31 m, then FCW. Appending coasted ranges to `samples` instead (F1)
      # re-admits over-closing U11: replayed on 00000231, newly measured vRel over-closed the next-1 s
      # range slope by >3 m/s on 17.0% of sweeps (reference 6.8%), the D-056 failure. So only a coast run
      # that passes the D-057 lasting-clean-step test (>=1.5 s, non-degraded, ranges fit a line within
      # 1 m and at the U11 rate) re-roots the fit. Replayed on 24 routes against the coast it replaces,
      # re-rooted vRel was nearer the next-1 s range slope on 235 sweeps, the coast on 79 (lead 73/35),
      # and total error halved; 00000241 and 0000024f leads went the other way, by over-closing (STATUS 70).
      if vrel_inconsistent:
        track.inconsistent_run.append((now_s, dRel, direct_vrel, degraded))
        if _bosch_a_lasting_clean_step(track.inconsistent_run):
          recent = track.inconsistent_run[-BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES:]
          track.samples.clear()
          track.samples.extend((t, d) for t, d, _, _ in recent[:-1])
          previous_sample = track.samples[-1]
          track.inconsistent_run.clear()
          vrel_inconsistent = False
      else:
        track.inconsistent_run.clear()

      # D-059: after a join, `samples` hold pre-gap ranges plus the joined one, so the fit above is set by
      # the gap rather than by the object and cannot see a contradicting U11. Replayed on 00000232 / 236 /
      # 237 / 239 / 23a / 23b / 23e: measured vRel in the second after a join over-closed the next-1 s
      # range slope by >3 m/s on 21.0 % of sweeps (33.1 % where the rejected run's own slope contradicted
      # U11) against 4.6 % for all measured points. Hold such a vRel as a coast until the same one-sided
      # check also passes over the post-join ranges alone.
      # - `samples` are left exactly as before: clearing them instead (fitting only the fresh ranges)
      #   admitted 106 new measured sweeps that over-closed on 16 % and lost 65 point-sweeps (the D-056
      #   failure mode). With them untouched, this can only withdraw measured vRel, never add it.
      # - The hold needs a trusted vRel to coast and re-publishes a point the rejection had dropped: a
      #   join must never delete an object the radar is reporting and the gate just accepted (D-041/D-042).
      # Replay vs D-057: 0 lost, 0 new measured, 612 sweeps withdrawn (30 lead); the withdrawn vRel
      # over-closed on 29.2 % (105 / 359 scored).
      rejoin_hold = False
      if track.rejoin_samples is not None:
        track.rejoin_samples.append((now_s, dRel))
        del track.rejoin_samples[:-BOSCH_A_REANCHOR_WINDOW]
        fresh_ok = False
        if vrel_candidate is not None and len(track.rejoin_samples) >= BOSCH_A_VREL_RATE_CHECK_MIN_SAMPLES:
          ts = [x[0] for x in track.rejoin_samples]
          ds = [x[1] for x in track.rejoin_samples]
          if ts[-1] - ts[0] >= BOSCH_A_VREL_RATE_CHECK_MIN_SPAN_S:
            n = len(ts)
            t_mean = sum(ts) / n
            d_mean = sum(ds) / n
            denom = sum((t - t_mean) ** 2 for t in ts)
            if denom > 1e-9:
              rate = sum((t - t_mean) * (d - d_mean) for t, d in zip(ts, ds, strict=True)) / denom
              fresh_ok = vrel_candidate >= rate - BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS
        if fresh_ok:
          track.rejoin_samples = None
          track.rail_hold = False
        else:
          rejoin_hold = track.last_trusted_vrel is not None and not (high_u10_live_vrel or vrel_inconsistent)
      if rejoin_hold:
        track.samples.append((now_s, dRel))
      if high_u10_live_vrel or vrel_inconsistent or rejoin_hold:
        # The range cleared innovation checking above, so geometry here is trustworthy; only vRel is
        # in question. Preserve current geometry but coast only a recent authoritative motion
        # estimate without a KF update, rather than publishing a one-sweep-derivative synthesis.
        # A coast means the VELOCITY is doubtful, not that the object is gone: object existence is
        # decided earlier by STATUS/existence/range validity, which route elsewhere. Dropping the
        # point here therefore discards a geometry the radar is still reporting and the range
        # innovation check just accepted. Measured on 000001fb segments 34-35 through the real
        # RadarInterface: 28 suppression gaps, 70% of them longer than BOSCH_A_STALE_S, i.e. long
        # enough for radard to delete the track and fall back to vision. That is the 000001f9
        # failure mode -- there a stopped car was dropped and the planner commanded 0.00 at 76 m.
        #
        # Keep publishing the geometry and hold the last trusted velocity, flagged measured=False.
        # An understated closing rate still brakes; a deleted object does not. Genuine disappearance
        # is still handled by _bosch_a_retire_stale_tracks, which every coast path leaves armed by
        # refreshing last_seen_nanos only while the radar keeps reporting this identity.
        point = self.pts.get(track_id)
        if point is None and rejoin_hold:
          point = self.pts[track_id] = structs.RadarData.RadarPoint()
          point.trackId = track_id
          point.aRel = float('nan')
          point.yvRel = float('nan')
        if point is not None and track.last_trusted_vrel is not None:
          point.dRel = dRel
          point.yRel = yRel
          point.vRel = _bosch_a_coast_vrel(track, self.rail_interval, self.coast_range_bound, self.v_ego)
          point.measured = False
        elif point is not None:
          # No trusted velocity was ever established for this identity, so there is nothing to
          # coast and no way to publish a defensible vRel.
          self.pts.pop(track_id, None)

        # Do not let a coast-only range observation become a future derivative baseline.
        track.prev_frame_idx = idx0
        track.prev_life = life
        track.last_seen_nanos = now
        track.wire_slot = slot
        for old_slot, old_id in enumerate(self._slot_track_ids):
          if old_slot != slot and old_id == track_id:
            self._slot_track_ids[old_slot] = None
        self._slot_track_ids[slot] = track_id
        continue

      # Native U11 is unavailable here (sentinel/out-of-range -- the high-u10-but-live case above
      # already returned before this point) and the range-ratio field is unusable or degraded too.
      # The remaining option is the raw one-sweep (dRel-previous_range)/dt derivative, which is
      # structurally the same hazard the high-u10 case guards against: a synthesized rate becoming an
      # authoritative measurement. Coast a recent trusted velocity instead, on the same terms as above,
      # rather than publish it.
      # A true birth observation (no previous accepted range yet) can never mature into a published
      # point this cycle regardless of vRel source -- `matured` below requires a second sample -- so
      # only intercept once a fallback derivative would actually have something to poison.
      u11_and_ratio_unavailable = (direct_vrel is None and (ratio_vrel is None or degraded) and
                                   previous_sample is not None)
      if u11_and_ratio_unavailable:
        # A coast means the VELOCITY is doubtful, not that the object is gone: object existence is
        # decided earlier by STATUS/existence/range validity, which route elsewhere. Dropping the
        # point here therefore discards a geometry the radar is still reporting and the range
        # innovation check just accepted. Measured on 000001fb segments 34-35 through the real
        # RadarInterface: 28 suppression gaps, 70% of them longer than BOSCH_A_STALE_S, i.e. long
        # enough for radard to delete the track and fall back to vision. That is the 000001f9
        # failure mode -- there a stopped car was dropped and the planner commanded 0.00 at 76 m.
        #
        # Keep publishing the geometry and hold the last trusted velocity, flagged measured=False.
        # An understated closing rate still brakes; a deleted object does not. Genuine disappearance
        # is still handled by _bosch_a_retire_stale_tracks, which every coast path leaves armed by
        # refreshing last_seen_nanos only while the radar keeps reporting this identity.
        point = self.pts.get(track_id)
        if point is not None and track.last_trusted_vrel is not None:
          point.dRel = dRel
          point.yRel = yRel
          point.vRel = _bosch_a_coast_vrel(track, self.rail_interval, self.coast_range_bound, self.v_ego)
          point.measured = False
        elif point is not None:
          # No trusted velocity was ever established for this identity, so there is nothing to
          # coast and no way to publish a defensible vRel.
          self.pts.pop(track_id, None)

        # Do not let a coast-only range observation become a future derivative baseline.
        track.prev_frame_idx = idx0
        track.prev_life = life
        track.last_seen_nanos = now
        track.wire_slot = slot
        for old_slot, old_id in enumerate(self._slot_track_ids):
          if old_slot != slot and old_id == track_id:
            self._slot_track_ids[old_slot] = None
        self._slot_track_ids[slot] = track_id
        continue

      track.samples.append((now_s, dRel))
      track.range_anchor = (now_s, dRel)
      sample_count = len(track.samples)

      # Prefer qualified native U11; otherwise the range-ratio field. The raw one-sweep derivative is
      # never published as a measurement -- see the coast/drop branch above, which intercepts before
      # this point whenever neither native U11 nor the ratio field is usable.
      if direct_vrel is not None:
        vRel = direct_vrel
      else:
        vRel = ratio_vrel
      trustworthy_vrel = True

      # A birth observation has no range-rate yet. Keep it as history, but do not publish a RadarPoint
      # until a second coherent observation of the same CAN identity supplies a finite derivative.
      matured = sample_count >= 2 and math.isfinite(vRel)
      if trustworthy_vrel:
        track.last_trusted_vrel = vRel
        track.last_trusted_vrel_nanos = now
      if matured and track_id not in self.pts:
        self.pts[track_id] = structs.RadarData.RadarPoint()
        self.pts[track_id].trackId = track_id
        self.pts[track_id].aRel = float('nan')
        self.pts[track_id].yvRel = float('nan')

      if matured:
        self.pts[track_id].dRel = dRel
        self.pts[track_id].yRel = yRel
        self.pts[track_id].vRel = vRel
        self.pts[track_id].measured = True
      else:
        self.pts.pop(track_id, None)

      track.prev_frame_idx = idx0
      track.prev_life = life
      track.last_seen_nanos = now
      track.wire_slot = slot
      for old_slot, old_id in enumerate(self._slot_track_ids):
        if old_slot != slot and old_id == track_id:
          self._slot_track_ids[old_slot] = None
      self._slot_track_ids[slot] = track_id

    ret.points = [self.pts[track_id] for track_id in sorted(self.pts)]
    return ret

  def _update_nidec(self, updated_messages):
    ret = structs.RadarData()

    for ii in sorted(updated_messages):
      cpt = self.rcp.vl[ii]
      if ii == 0x400:
        # check for radar faults
        self.radar_fault = cpt['RADAR_STATE'] != 0x79
        self.radar_wrong_config = cpt['RADAR_STATE'] == 0x69
      elif cpt['LONG_DIST'] < 255:
        if ii not in self.pts or cpt['NEW_TRACK']:
          self.pts[ii] = structs.RadarData.RadarPoint()
          self.pts[ii].trackId = self.track_id
          self.track_id += 1
        self.pts[ii].dRel = cpt['LONG_DIST']  # from front of car
        self.pts[ii].yRel = -cpt['LAT_DIST']  # in car frame's y axis, left is positive
        self.pts[ii].vRel = cpt['REL_SPEED']
        self.pts[ii].aRel = float('nan')
        self.pts[ii].yvRel = float('nan')
        self.pts[ii].measured = True
      else:
        if ii in self.pts:
          del self.pts[ii]

    if not self.rcp.can_valid:
      ret.errors.canError = True
    if self.radar_fault:
      ret.errors.radarFault = True
    if self.radar_wrong_config:
      ret.errors.wrongConfig = True

    ret.points = list(self.pts.values())

    return ret
