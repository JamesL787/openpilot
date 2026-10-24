"""Every PTM EPS image's calibration for LatControlHondaEps: its firmware tables, its car's measured (or carried-over,
or spec-predicted) vehicle constants, where each value came from, and the PTM build it requires.

The law these feed is in honda_eps_firmware_ff; this file is data. Adding an image: docs/HONDA_EPS_CONTROLLER.md.
"""
from opendbc.car.honda.steer_ratio import (
  HONDA_VGR_CIVIC_TBA_C020, HONDA_VGR_CIVIC_TBA_C120, HONDA_VGR_CLARITY_TRW_A020, HONDA_VGR_CRV_TLA_A040,
  HONDA_VGR_INSIGHT_TXM_A040, HONDA_VGR_INVERSE_BY_PROFILE, HONDA_VGR_RDX_TJB_A220,
)
from openpilot.selfdrive.controls.lib.honda_eps_firmware_ff import CLARITY_TRW_A020_LAT_DELAY_SCHEDULE, ColumnLoadModel, \
  EpsFirmwareCalibration, R6_GAIN_BP, computed_r6
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import CIVIC_TBA_C020_RACK, CIVIC_TEG_A010_RACK, CIVIC_TGG_A120_RACK, \
  CLARITY_TRW_A020_RACK, INSIGHT_TXM_A040_RACK, RDX_TJB_A220_RACK
from openpilot.selfdrive.controls.lib.honda_eps_spec_plant import CIVIC_2019_SEDAN_SPEC, CRV_2017_SPEC, \
  CRV_2020_SPEC, spec_rack_table

# --- the images ------------------------------------------------------------------------------------------------
# Every table below was read from the image the car's owners actually run (the latest builds on the dev machine;
# the shared "Proper Torque Mod" Drive copies are stale for the A030 and C020). The work notes, extractor and the
# per-image table live in rwd-xray-2026chatgpt/EPS_FW_CONTROLLER_MULTICAR_20260927 (notes/firmware_profiles.md).
#
# Which command-map row is live is set per VEHICLE VARIANT, in the image itself: a ROM record table (Clarity
# 0x4B9DC, 89-byte records) keys 5-character variant codes (TRWF3, TBCA9, TGGA5, ...) to row indices, and byte
# 0x0F of the car's record (0 whenever its enable byte 0x0E is 0) is what fn_2AD2E writes to the row selector
# 0xFFF87B7C that the command map, P and D tables read. Checked against both measured cars: every Clarity record
# says 0 (row 0 live), and on the C020 only TBCA9/TBHC8 say 1 (row 1 live on the owner's car). Per image below.

# Clarity column load, fitted on route 00000352 (gain/plant.py: target the firmware's A030 output, every engaged,
# unpressed frame with the scale word >= 240, which keeps resting-hand turns; regressors k0, k1, c, friction with a
# 2 deg/s knee, inertia j (not deployed), bias, roll; motion shifted by the best lag). R^2 0.82 in-route, 0.72 on the
# held-out route. The same recipe per route on 35c-38c (14 routes) gives friction -272..-344 (median -311), k0 median
# -6.2, so this is representative.
CLARITY_TRW_A020_LOAD = ColumnLoadModel(k0=-7.00387, k1=-0.21857, c=-6.8317, friction=-314.07279, bias=20.46793, kroll=-7.20003)

# 10th-gen Civic column, fitted jointly on the C020 owner's routes 00000287 + 00000289 + 00000294 (hands off, from the
# firmware's own P + KFF output rebuilt out of its 0x6A1 error telemetry, so in pre-scale counts: scale_q8 256).
# Held out one route at a time, R^2 0.64 / 0.74 / 0.79 against 0.61 / 0.70 / 0.76 for the Clarity model, which
# over-asks this column (actual / model 0.77-0.98 at 4-22 m/s, 0.5-0.8 at 2-4 m/s). Bias and roll are the Civic's
# own now that three drives identify them.
CIVIC_TBA_C020_LOAD = ColumnLoadModel(k0=-5.574, k1=-0.1831, c=-4.540, friction=-326.5, bias=-83.6, kroll=-3.185)

# TEG-A010 column, the standard recipe (tools/lateral/fit_column_load.py --source teg: target 0x6A3 w0 = P + D +
# KFF*R5/1024 exactly, row-independent) on the owner's 11 telemetry routes 0000012d-00000139 (2026-10-14/15, 81 min of
# frames): R^2 0.735, held out by route 0.39-0.78 against -0.73-0.74 for the 08-18 fit it replaces
# (k0 -9.205 k1 -0.3252 c -9.039 friction -550.7 bias -83.6 kroll -3.185). By regime on routes 134/139 after fitting
# 133/137: hold 15+ m/s RMS 255 vs 866, turn-in 9-15 306 vs 430, unwind 15+ 142 vs 714; straights similar. Few
# turns below 9 m/s in these drives, so the crawl regimes are untested.
CIVIC_TEG_A010_LOAD = ColumnLoadModel(k0=-7.833, k1=-0.169, c=-8.29, friction=-311.2, bias=59.18, kroll=-4.457)
# CR-V 5G column (HONDA_CRV_5G, 39990-TLA-A040), fitted on the owner's route 00000006--82bb552a2c (native V5 telemetry,
# 40,193 hands-off active groups; RiskyBiscuit-arc/openpilot STATUS 225 / D-092, tools/lateral/fit_crv_eps_load.py) in
# this model's own units: m/s, angle with the liveParameters offset removed, liveParameters roll. R^2 0.843, alternating
# 60 s holdouts 0.857 / 0.820. Close to the Clarity's in every term but the speed term (-0.143 vs -0.219).
CRV_TLA_A040_LOAD = ColumnLoadModel(k0=-7.29446, k1=-0.143159, c=-4.60337, friction=-297.83, bias=-19.899, kroll=-3.58048)
# Insight column (HONDA_INSIGHT, 39990-TXM,A040), measured the way CLARITY_TRW_A020_LOAD was (gain/plant.py) on the owner's
# konik route f133facb1b9b7420|0000001e--2987344626 (2026-10-08, 15.8 mi, 26.9 min engaged and unpressed). That
# build has no telemetry, so the target is the firmware law rebuilt from the sent E4 through row 0 and the car's
# [0, 3840] map with R6 from the Insight's A table (on the Clarity that rebuild matches the A030 output at corr 0.987
# hands off), and the scale-word gate is a |driver torque| < 300 cut (on the Clarity the scale word stays >= 240 up to
# ~500 counts; the fit hardly moves between cuts of 200, 300 and 500). Regressors k0, k1, c, friction (2 deg/s knee),
# inertia j (-0.34, not deployed), bias, roll; best motion lag 40 ms; R^2 0.76.
INSIGHT_TXM_A040_LOAD = ColumnLoadModel(k0=-4.876, k1=-0.1376, c=-4.452, friction=-397.2, bias=65.41, kroll=-4.29)

CLARITY_TRW_A020_R6_CENTRE, CLARITY_TRW_A020_R6_BP, CLARITY_TRW_A020_R6_GAIN = computed_r6(HONDA_VGR_CLARITY_TRW_A020)

# Default residual-PID trims: vfn 35ddc44b's modified-EPS angle PID with the P/I trims the Clarity ran on it
# (2026-09-26, LatPScale 125/100/125, LatIScale 70/95/35), fixed because the replay validated the feedforward
# against exactly that PID.
CLARITY_TRW_A020_P_SCALE = (1.25, 1.00, 1.25)
CLARITY_TRW_A020_I_SCALE = (0.70, 0.95, 0.35)
# The C020 owner's trims on route 00000284 (LatPScale 115/125/115, LatIScale 75/95/100), the drive their port of
# this controller was checked against. Every Civic-platform car starts here.
CIVIC_TBA_C020_P_SCALE = (1.15, 1.25, 1.15)
CIVIC_TBA_C020_I_SCALE = (0.75, 0.95, 1.00)
# The CR-V owner drives this controller untrimmed (RiskyBiscuit-arc ns-bosch-updated CRV_5G_P/I_SCALE), on the
# CarParams base gains.
CRV_TLA_A040_P_SCALE = (1.0, 1.0, 1.0)
CRV_TLA_A040_I_SCALE = (1.0, 1.0, 1.0)

# The TargetMap-D R5 row every Civic-family image carries in all seven rows, and the Clarity's own row 0.
TARGET_MAP_D_R5 = (0, 1926, 4938, 8455, 12036, 15926, 20138, 26955, 30000)
CLARITY_TRW_A020_R5 = (0, 2000, 4000, 6000, 8000, 12000, 16000, 20000, 30000)
P_ROW_PMINUS5 = (117, 148, 184, 220, 245, 257, 263, 265, 265)
CLARITY_TRW_A020_P_KEYS = (0, 222, 443, 665, 887, 1108, 1330, 1552, 1774)  # P row 0 key axis (0x13B5E)
FLAT_ENVELOPE = ((0, 50, 100, 150, 200, 250, 300, 350, 400), (1774,) * 9)
# C020 / TEG / A030 speed envelope (axis 0x13644, values 0x136C2 on the C020): 1552 from 120 km/h, 1108 from 160
CIVIC_TBA_C020_ENVELOPE = ((0, 50, 100, 150, 200, 240, 300, 321, 400), (1774, 1774, 1774, 1774, 1774, 1552, 1219, 1108, 1108))
# C020 row 1 (axis 0x13806); the TEG-A010 and the 09-12 A030 images carry the C020's axes in every row
CIVIC_TBA_C020_ROW1_KEYS = (0, 115, 254, 449, 654, 862, 1111, 1549, 1774)
CIVIC_TBA_C120_P_KEYS = (3, 173, 441, 665, 887, 1104, 1317, 1610, 1774)
# Every image's R6, computed from its own A table (see computed_r6). The TGG-A120 shares the C020's A table; the
# TEG-A010 and A030 share the C120's (centre divisor 20972); the CR-V A220's is byte-identical to the A040's.
CIVIC_TBA_C020_R6_CENTRE, CIVIC_TBA_C020_R6_BP, CIVIC_TBA_C020_R6_GAIN = computed_r6(HONDA_VGR_CIVIC_TBA_C020)
CIVIC_TBA_C120_R6_CENTRE, _, CIVIC_TBA_C120_R6_GAIN = computed_r6(HONDA_VGR_CIVIC_TBA_C120)
CIVIC_TEG_A010_R6_CENTRE, CIVIC_TEG_A010_R6_BP, CIVIC_TEG_A010_R6_GAIN = CIVIC_TBA_C120_R6_CENTRE, R6_GAIN_BP, CIVIC_TBA_C120_R6_GAIN
INSIGHT_TXM_A040_R6_CENTRE, _, INSIGHT_TXM_A040_R6_GAIN = computed_r6(HONDA_VGR_INSIGHT_TXM_A040)
CRV_TLA_A040_R6_CENTRE, _, CRV_TLA_A040_R6_GAIN = computed_r6(HONDA_VGR_CRV_TLA_A040)

# Clarity 39990-TRW-A020, the P-minus-5 build (07-28, bin sha256 92cde599; P117..265 D737 KFF45 NoR6L2 Tracker3200
# Norm1650), the Clarity standard: what routes 352/353 and the whole replay validation ran on, and the parent of the
# A280-flat build owners move to (which edits only the A280 cells, so every table here holds). The older ClarityMax
# 07-22 P123..279 build differed only in the P row (123, 156, 194, 232, 258, 270, 277, 279, 279) and is not supported.
CLARITY_TRW_A020 = EpsFirmwareCalibration(
  name="clarity_trw_a020",
  e4_per_output=3840.0,
  # command map row 0 (0x13810 / 0x1388E); key = trunc(trunc(E4 * 56756 / 32768) / 4)
  r5_key_bp=(0, 111, 222, 333, 443, 665, 887, 1108, 1663), r5_v=CLARITY_TRW_A020_R5, key_clamp=1663,
  # 1774 up to 100 km/h, so the 1663 key clamp binds first until ~107 km/h; 1330 from 130 km/h (0x13660 / 0x136DE)
  envelope_bp=(0, 50, 100, 150, 200, 260, 300, 350, 400), envelope_v=(1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330, 1330),
  # P row 0 (0x13B5E / 0x13BDC)
  kp_key_bp=CLARITY_TRW_A020_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CLARITY_TRW_A020_R6_CENTRE, r6_angle_bp=CLARITY_TRW_A020_R6_BP, r6_angle_gain=CLARITY_TRW_A020_R6_GAIN,
  load=CLARITY_TRW_A020_LOAD, p_scale=CLARITY_TRW_A020_P_SCALE, i_scale=CLARITY_TRW_A020_I_SCALE,
  r5_per_key=18.04,
  cmd_delay_s=0.12, cmd_delay_highway_s=0.10,  # measured
  lat_delay_schedule=CLARITY_TRW_A020_LAT_DELAY_SCHEDULE,  # measured
  rack=CLARITY_TRW_A020_RACK,
)

# Model-delay schedules for the Civics (2026-10-18), each the car's measured lag from the camera frame to its own yaw
# curvature, less modeld's fixed 0.075 s (frame + half a model step), so a plan model read at the told delay lands on
# time (honda_eps_firmware_ff, model-delay schedule). Before this they took the Clarity's, and lagd (0.37-0.39 on
# the TEG) told them much more than the car takes, which ran them early.
# - TEG-A010: 0.26-0.31 s at every speed on its owner's routes 12e/12f/133/134/137/139/13d (Pop v2, this
#   controller's port to its owner's fork, the command delay taken out), so 0.20 s flat.
# - C020 (provisional): 0.37-0.43 s on route 380 (NovaSpark, the older PID + firmware FF with a 0.09-0.10 s output
#   filter and no command delay); with this controller's filter (0.07 / 0.05 / 0.01 s) that is ~0.35-0.41 in town and
#   ~0.33 on the highway, so 0.28 / 0.26 s. Re-measure on a drive with this controller.
CIVIC_TEG_A010_LAT_DELAY_SCHEDULE = ((3.5, 7.0, 12.0, 20.0, 30.0), (0.20, 0.20, 0.20, 0.20, 0.20))
CIVIC_TBA_C020_LAT_DELAY_SCHEDULE = ((3.5, 7.0, 12.0, 20.0, 30.0), (0.28, 0.28, 0.28, 0.26, 0.26))
# - RDX TJB-A220 (2026-10-23, highway): 0.21-0.27 s from the frame (median 0.24) at 28-32 m/s on this controller,
#   routes 412ed2539bfc2c42/00000003 segments 8-16 and 00000004 segments 4-9 (a plan model, no command delay). The
#   Clarity's 0.30 s told it ~0.13 s too much, and the car ran early into a ~1 Hz highway weave. 0.17 s from 20 m/s.
# - RDX TJB-A220 (2026-10-23, town): route 0000000b segments 6-9 at 12-20 m/s on turning samples, schedule ~0.19 s
#   (0.26 s from the frame); the Clarity's 0.08-0.10 s at 7-12 m/s ran ~65 ms short there. Crawl (3.5 m/s) still the
#   Clarity's 0.15 s until a parking-lot drive measures it.
RDX_TJB_A220_LAT_DELAY_SCHEDULE = ((3.5, 7.0, 12.0, 20.0, 30.0), (0.15, 0.16, 0.18, 0.17, 0.17))

# Civic Bosch 39990-TBA-C020, the CORRECTED Proper Torque Mod of 2026-10-16, revision b (RWD sha256 df67bf6f; KB
# PTM_FIX_FAMILY_20261016/out/C020, independent_verify 48/48, brick_check 70/70), a data-only fix of nrdr's Drive
# release (39990-TBA,C020-Trk4000-PTM, 2d8836e8). That release equals the owner's earlier 08-05 ClarityPminus5
# TargetMapD Telem build except tracker-1 (4000 here, 4500 there: ~2 ms of R6 lag, ~3 deg at 6.2 Hz; A280 is flat in
# rows 0-1 now, which is what stopped the stutter). Rows 0-5 carry the Clarity's R5 at key x 3840/4096 on their own
# axes, P on the Clarity's knots x 4096/3840, row 6 back to stock. Row 1 is live (TBCA9/TBHC8; telemetry on route 294:
# 94 counts RMS vs 200 for row 0 at 11-20 m/s). Its R6, column load and trims were measured on the 08-05 build
# (routes 284/287/289/294); the fix touches neither the rate path nor the column, so they carry over. Key clamp 1663
# (0x137F2). Not checked: the envelope above 89 km/h. Sent 3840 per unit here (opendbc HONDA_CIVIC_BOSCH, the image's
# clamp), the build was made for 4096, so per unit of output it asks 0.94x the Clarity's R5 and reaches the clamp at
# full output; the inversion uses 3840. On the 08-05 build (TargetMap-D) this map would be 7-13 % hot mid-range.
CIVIC_TBA_C020_R5 = (0, 1943, 4291, 7599, 11065, 14579, 18798, 26202, 30002)  # rev b row 1 (0x13884)
CIVIC_TBA_C020 = EpsFirmwareCalibration(
  name="civic_tba_c020", e4_per_output=3840.0,
  r5_key_bp=CIVIC_TBA_C020_ROW1_KEYS, r5_v=CIVIC_TBA_C020_R5, key_clamp=1663,
  envelope_bp=CIVIC_TBA_C020_ENVELOPE[0], envelope_v=CIVIC_TBA_C020_ENVELOPE[1],
  kp_key_bp=tuple(round(k * 4096 / 3840) for k in CLARITY_TRW_A020_P_KEYS), kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TBA_C020_R6_CENTRE, r6_angle_bp=CIVIC_TBA_C020_R6_BP, r6_angle_gain=CIVIC_TBA_C020_R6_GAIN,
  load=CIVIC_TBA_C020_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  cmd_delay_s=0.15, cmd_delay_highway_s=0.15,  # measured
  lat_delay_schedule=CIVIC_TBA_C020_LAT_DELAY_SCHEDULE,
  rack=CIVIC_TBA_C020_RACK,
)
# TEG-A010, the CORRECTED Proper Torque Mod of 2026-10-16, revision b (RWD sha256 04147917, payload 110e29ba; KB
# PTM_FIX_FAMILY_20261016/out/TEG, proof/), a data-only fix of the Tracker1-3200 build (10-03 A280-flat, bin 4fa7c252):
# 177 bytes, the command-map Y and P key axes of rows 0-5, row 6 (map, P, D) back to stock, and the two checksums.
# That build pasted TargetMap-D onto row 3's key axis (3.1x incremental gain at key 222, u ~0.13) with P on the row's
# own knots. Rev b keeps every row's own key axis and writes the Clarity's R5 for each key (a knot past the 1663 clamp
# on the line through the Clarity's 30000 at 1663), and puts rows 0-5 P on the Clarity's knots, so rows 2 and 3 now make
# the same R5 per key and the TEGA1/TEGA2 variant no longer changes the command. The owner's car runs ROW 3 (TEGA2),
# measured on its telemetry on the earlier build (tools/lateral/live_row_fit.py teg, routes 0000012f and 00000139:
# median |R5 - row 3| 9 counts, rows 0-2 1046-1325). Kp values, D, clamps and envelope are those of every row. Load and
# rack were measured on the earlier build; the fix touches neither the rate path nor the column, so they carry over.
# R6 is computed from its A table (the C120's), which its telemetry confirms within 0.8% once railed frames are left
# out. Both builds report 39990-TEG,A010: a car still on the earlier image must be reflashed with this calibration (on
# it the car would make about half the R5 this expects up to key 222).
CIVIC_TEG_A010_R5 = (0, 4000, 6000, 8937, 11838, 16000, 20000, 28000, 32000)  # rev b row 3 (0x137D0)
CIVIC_TEG_A010 = EpsFirmwareCalibration(
  name="civic_teg_a010", e4_per_output=3840.0,
  r5_key_bp=(0, 222, 333, 495, 656, 887, 1108, 1552, 1774), r5_v=CIVIC_TEG_A010_R5, key_clamp=1663,
  envelope_bp=CIVIC_TBA_C020_ENVELOPE[0], envelope_v=CIVIC_TBA_C020_ENVELOPE[1],  # read from the image: the C020's
  kp_key_bp=CLARITY_TRW_A020_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TEG_A010_R6_CENTRE, r6_angle_bp=CIVIC_TEG_A010_R6_BP, r6_angle_gain=CIVIC_TEG_A010_R6_GAIN,
  load=CIVIC_TEG_A010_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  # plan_timing on routes 12e/134/137/139 under upstream's Civic delay (0.175 s = 0.15 + a 0.025 s compensation for a
  # model-action interpolation it lacks): -0.05 s weighted at 5-12 m/s, so ~0.20 s here; 0.15 stays below it (the
  # C020 family's value). By speed band (2026-10-18) it runs as early above 15 m/s, where that delay had faded out, so
  # it holds flat. That was Pop v2 told lagd's 0.38 s: its own schedule (above) now carries that part for plan models.
  cmd_delay_s=0.15, cmd_delay_highway_s=0.15,
  lat_delay_schedule=CIVIC_TEG_A010_LAT_DELAY_SCHEDULE,
  rack=CIVIC_TEG_A010_RACK,
)
# Civic 39990-TBA-A030 (Nidec), the CORRECTED Proper Torque Mod of 2026-10-16, revision b (RWD sha256 55c37266; KB
# PTM_FIX_FAMILY_20261016/out/A030), a data-only fix of the Drive A030 release. Its rows 0-5 carry exactly the TEG
# rev b's row 3 (the same key axis, the Clarity's R5 per key, the Clarity's P knots), so the variant row (TBAA3 1,
# TBCA1 2, TBCA2 3, others 0) no longer changes the command. The rate path is the TEG's too: tracker-1 3200, R6 clamp
# 32765, key clamp 1663, NORM 1650 and a byte-identical A table, so it has the TEG's computed R6 and takes its load and
# command delay, and its rack map: it is the same 2016-18 Civic sedan as the TEG (US vs Japanese part number; the same
# published steering specs and a byte-identical A table), so the TEG's yaw-fitted rack is the A030's geometry until an
# A030 drive refits it (inferred, not measured on an A030). Its own spec prediction would be 2% further off. Its tracker-2 reads 5968
# (the Drive release's; the owners' 09-12 build has 3869); it does not feed R6. Both builds report 39990-TBA,A030: a
# car on the 09-12 or the Drive image must be reflashed with this calibration.
CIVIC_TBA_A030 = EpsFirmwareCalibration(
  name="civic_tba_a030", e4_per_output=3840.0,
  r5_key_bp=(0, 222, 333, 495, 656, 887, 1108, 1552, 1774), r5_v=CIVIC_TEG_A010_R5, key_clamp=1663,
  envelope_bp=CIVIC_TBA_C020_ENVELOPE[0], envelope_v=CIVIC_TBA_C020_ENVELOPE[1],
  kp_key_bp=CLARITY_TRW_A020_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TEG_A010_R6_CENTRE, r6_angle_bp=CIVIC_TEG_A010_R6_BP, r6_angle_gain=CIVIC_TEG_A010_R6_GAIN,
  load=CIVIC_TEG_A010_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  cmd_delay_s=0.15, cmd_delay_highway_s=0.15,
  lat_delay_schedule=CIVIC_TEG_A010_LAT_DELAY_SCHEDULE,
  rack=CIVIC_TEG_A010_RACK,
)
# Civic Bosch 39990-TBA-C120, the CORRECTED Proper Torque Mod of 2026-10-16, revision b (RWD sha256 9261b8db; KB
# PTM_FIX_FAMILY_20261016/out/C120), a data-only fix of the Drive C120 release (tracker-1 4250 and tracker-2 5968, as the
# 08-11 C020Profile build). Its variants select rows 0-4; each row keeps its own key axis and carries the Clarity's R5
# for each key, and P sits on the Clarity's knots, so every row makes the same command. Row 1 (= row 2) is modelled.
# Flat envelope. E4 = -3840 * u: opendbc sends HONDA_CIVIC_BOSCH 3840, the C120's own key clamp. Not
# measured: load (R6 is computed from its A table). Both builds report 39990-TBA,C120: a car on an earlier image must be reflashed.
# Its rack map is predicted from the 2019-21 Civic sedan's specs through its own A table (no C120 yaw fit yet).
CIVIC_TBA_C120_SPEC_RACK = spec_rack_table(CIVIC_2019_SEDAN_SPEC, HONDA_VGR_INVERSE_BY_PROFILE[HONDA_VGR_CIVIC_TBA_C120])
CIVIC_TBA_C120 = EpsFirmwareCalibration(
  name="civic_tba_c120", e4_per_output=3840.0,
  r5_key_bp=(0, 103, 263, 459, 660, 861, 1111, 1549, 1774), r5_v=(0, 1856, 4739, 8288, 11910, 15532, 20054, 27946, 32000),
  key_clamp=1663, envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=CLARITY_TRW_A020_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TBA_C120_R6_CENTRE, r6_angle_bp=R6_GAIN_BP, r6_angle_gain=CIVIC_TBA_C120_R6_GAIN,
  load=CIVIC_TBA_C020_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  cmd_delay_s=0.15, cmd_delay_highway_s=0.15,  # the C020's (same Civic Bosch chassis)
  lat_delay_schedule=CIVIC_TBA_C020_LAT_DELAY_SCHEDULE,
  rack=CIVIC_TBA_C120_SPEC_RACK,
)
# Civic hatch 39990-TGG-A120, the CORRECTED Proper Torque Mod of 2026-10-16, revision b (RWD sha256 6640806d; KB
# PTM_FIX_FAMILY_20261016/out/TGG), a data-only fix of the Drive TGG release (tracker-1 4250, as the 08-07 build). Row 0
# is live: both variant records (TGGA5, TGGA6, at 0x4B500) select it. It keeps its own key axis and carries the
# Clarity's R5 for each key at this car's 4096 E4 per unit (Clarity(key x 3840/4096)), with P on the Clarity's knots
# x 4096/3840, and A280 is flat in it. Flat envelope. R6 is computed from its A table (the C020's); on the owner's
# routes the 0x18F rate word reads 4.85 per published deg/s at centre and 1.21x that to lock (displacement windows,
# five routes), against 4.80 and 1.21x computed, so R6 = 32 x the word holds within 1 %. Both builds report
# 39990-TGG,A120: a car on an earlier image must be reflashed.
# Live row, measured without telemetry: fitting the load below through each row's law of the 08-07 image, row 0 fits
# best on all five routes (held out 0.838 / 0.558 / 0.840 / 0.703 / 0.735; rows 1-5, the [0,222,333,...] axis: 0.822 /
# 0.484 / 0.811 / 0.634 / 0.681; row 6 needs a positive viscous term), as both variant records say.
# Rack map: yaw-fitted on the owner's car (honda_eps_rack_map.CIVIC_TGG_A120_RACK).
# Load: fitted through the law of the build those drives ran, the 08-07 C020Pminus5 Trk4250 KFF45 image (row 0 on
# TargetMap-D R5 0..30000, P-minus-5 on the C120's P keys, 4096 E4 per unit), not rev b's: the column is the car's,
# whichever image moves it. Routes 83ccc6a9a4e14d0b/0000000b-00000010, 73 min of engaged unpressed frames, R^2 0.794,
# held out by route 0.838 / 0.558 / 0.840 / 0.703 / 0.735 (the C020's load it carried: 0.761 / 0.520 / 0.641 / 0.267 /
# 0.318). Its column is 2x stiffer than the C020's at 5 m/s (k0 -15.7 vs -5.6), alike by 30 m/s: carrying the C020's
# under-asked the hold in tight turns, the owner's "low speed sometimes doesn't turn hard enough", while the
# highway was right.
CIVIC_TGG_A120_LOAD = ColumnLoadModel(k0=-15.67, k1=-0.157, c=-5.449, friction=-388.8, bias=75.77, kroll=-0.6084)
CIVIC_TGG_A120 = EpsFirmwareCalibration(
  name="civic_tgg_a120", e4_per_output=3840.0,  # built for 4096 (below), sent 3840: its key clamp is 1663
  r5_key_bp=(0, 103, 263, 459, 660, 862, 1111, 1549, 1774), r5_v=(0, 1740, 4443, 7769, 11167, 14579, 18798, 26202, 30002),
  key_clamp=1663, envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=tuple(round(k * 4096 / 3840) for k in CLARITY_TRW_A020_P_KEYS), kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CIVIC_TBA_C020_R6_CENTRE, r6_angle_bp=CIVIC_TBA_C020_R6_BP, r6_angle_gain=CIVIC_TBA_C020_R6_GAIN,
  load=CIVIC_TGG_A120_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  cmd_delay_s=0.15, cmd_delay_highway_s=0.15,  # the C020's (same Civic Bosch chassis)
  lat_delay_schedule=CIVIC_TBA_C020_LAT_DELAY_SCHEDULE,
  rack=CIVIC_TGG_A120_RACK,
)
# Insight 39990-TXM-A040, the CORRECTED Proper Torque Mod of 2026-10-16, revision b (payload sha256 089a8a72, RWD 7ba37432;
# KB PTM_FIX_FAMILY_20261016/out/TXM, proof/), on the released PTM 39990-TXM,A040-PTM.rwd (rwd 833a41bf, the 08-08 C020Surface Trk1-4000
# Trk2-3869 build, full image 1f1cfe6b). The release wrote TargetMap-D, a curve made for the C020's axis, onto row 0's
# key axis, which IS the Clarity's (0x11B3C: 0,111,222,...,1663 at the same E4 3840 per unit output). So it ran
# 1.14 / 1.32 / 1.53 / 1.50x the Clarity at outputs 0.10 / 0.15 / 0.20 / 0.30, and the residual PID ~1.5-1.9x hotter there.
# The corrected build puts the Clarity's own map values on rows 0-5 (0x11BBA, each on its own stock axis) and the
# Clarity's own P table (knots and values, 0x11E8A/0x11F08), returns row 6 (forced override) to stock and flattens
# A280 rows 0-3. Rows 0-1 are then the Clarity's tables exactly: the executed firmware (SH-2A emulation) matches the
# Clarity's output at every u. Both builds report 39990-TXM,A040: a car on the
# released image must be reflashed together with this calibration (on it the released image runs up to 1.5x hot).
# Row 0 is live: all three variant records (TXMA0/1/2, at 0xECF7) select row 0. The envelope was not located; flat is
# assumed (the 1663 clamp binds). Load measured (INSIGHT_TXM_A040_LOAD, in firmware output counts, so it holds across
# the reflash); R6 computed from its A table. Not measured: envelope.
INSIGHT_TXM_A040 = EpsFirmwareCalibration(
  name="insight_txm_a040", e4_per_output=3840.0,
  r5_key_bp=(0, 111, 222, 333, 443, 665, 887, 1108, 1663), r5_v=CLARITY_TRW_A020_R5, key_clamp=1663,
  envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=CLARITY_TRW_A020_P_KEYS, kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=INSIGHT_TXM_A040_R6_CENTRE, r6_angle_bp=R6_GAIN_BP, r6_angle_gain=INSIGHT_TXM_A040_R6_GAIN,
  load=INSIGHT_TXM_A040_LOAD, p_scale=CIVIC_TBA_C020_P_SCALE, i_scale=CIVIC_TBA_C020_I_SCALE,
  # Inferred: on LatControlPID its route 0000001e ran the plan 0.06 s early (exit 0.12), and this controller runs
  # ~0.13 s (Clarity) to ~0.18 s (C020) ahead of the PID, so ~0.19-0.24 s early here; 0.15 stays below that. Re-check
  # with plan_timing.py after a drive on this controller.
  cmd_delay_s=0.15,
  rack=INSIGHT_TXM_A040_RACK,
)
# CR-V 5G 39990-TLA-A040, the CORRECTED Proper Torque Mod of 2026-10-16, revision b (RWD sha256 2e6a8802; KB
# PTM_FIX_FAMILY_20261016/out/A040), a data-only fix of the Drive A040 release; the owner's 10-06 A280-flat build
# (8cf8e537 lineage) has the same rate path (tracker-1 3200, tracker-2 3870, R6 clamp 32765, key clamp 1774). Every
# variant record selects row 0 except TLBA2 (row 1, identical to row 0). Row 0 keeps the CR-V's stock key axis and
# carries the Clarity's R5 for each key at this car's 4096 E4 per unit (Clarity(key x 3840/4096); its last knot, 1663,
# holds to the 1774 clamp), with P on the Clarity's knots x 4096/3840. Key clamp 1774 (the others' 1663). Both builds
# report 39990-TLA,A040: a car on an earlier image must be reflashed.
# R6 is computed from its A table (centre divisor 16783: -125 per published deg/s). The owner's telemetry fit of V5
# feedback_R6 on steeringRateDeg, hands off, route 82bb (-121.6 at a 15 ms lag on the t9-67523237 build, norm 1450;
# x 1650/1450 = -138.4) is an angle average against the B-table rate, not the centre value.
# Column load measured on the same drive (CRV_TLA_A040_LOAD). P/I trims: the owner's (CRV_TLA_A040_P_SCALE /
# CRV_TLA_A040_I_SCALE, untrimmed). Rack map predicted from the 2017-19 CR-V's specs through its A table (no yaw fit).
CRV_TLA_A040_SPEC_RACK = spec_rack_table(CRV_2017_SPEC, HONDA_VGR_INVERSE_BY_PROFILE[HONDA_VGR_CRV_TLA_A040])
CRV_TLA_A040 = EpsFirmwareCalibration(
  name="crv_tla_a040", e4_per_output=4096.0,
  r5_key_bp=(0, 219, 443, 662, 887, 1108, 1330, 1552, 1663), r5_v=(0, 3699, 7497, 11200, 15001, 18747, 22502, 26252, 28127),
  key_clamp=1774, envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=tuple(round(k * 4096 / 3840) for k in CLARITY_TRW_A020_P_KEYS), kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CRV_TLA_A040_R6_CENTRE, r6_angle_bp=R6_GAIN_BP, r6_angle_gain=CRV_TLA_A040_R6_GAIN,
  load=CRV_TLA_A040_LOAD, p_scale=CRV_TLA_A040_P_SCALE, i_scale=CRV_TLA_A040_I_SCALE,
  rack=CRV_TLA_A040_SPEC_RACK,
)
# CR-V 5G 39990-TLA-A220 (2020+), the CORRECTED PTM build of 2026-10-16, revision b (payload sha256 a62337a9, RWD 2c992997;
# KB PTM_FIX_FAMILY_20261016/out/A220, proof/) on stock df85f988: command map and P table Clarity-equivalent, D737, KFF45, Norm1650, Trk3200,
# clamps 7373/1774/9000, speed clamp 0, row 6 stock.
# It replaces the 10-06 build (RWD 8f175250), which pasted the A040 PTM's TargetMap-D Y and P117..265 Y onto the A220's
# own, much more compressed axes: 0.71x the Clarity below key 161 and up to 1.76x above it, a 4.1x incremental-gain kink
# at output ~0.09, where highway lane keeping sits (p90 key 169 on the owner's routes 0x30A-0x30D). Both builds report
# 39990-TLA,A220, so a car still on the 10-06 build must be reflashed: on this calibration it would get ~0.7x on the
# highway and ~2x in turns. The corrected rows: at each row's own stock X knots, Y = the Clarity's row 0 at key x
# 3840/4096 (the A220 takes E4 0..4096 per unit output, the Clarity 0..3840); the P table is the Clarity's own knots x
# 4096/3840 with the Clarity's values. The executed firmware (SH-2A emulation) is within 0.6% of the Clarity's output
# from 0.05 to 0.93 (key quantization). The
# controller block is the A040's shifted -0x448 (only RAM literals differ), every calibration literal resolves to the
# SAME table address, and the PTM edits left the command axes, P axis, envelope and VGR tables stock. Read from THIS
# image: the command-map key axis (rows 0-3 at 0x11AE0 + 18*row), the P axis (0x11E2E), the speed envelope (values
# 0x119AE + 18*row, axis 0x11930), the key clamp (header word 0x11ADE, 1774), the A/B VGR tables, E4 scale (opendbc
# gives every modified HONDA_CRV_5G [0, 4096]).
# What differs from the A040 is the COMMAND AXIS: rows 0-3 are [0,161,222,322,409,534,696,998|1050,1663] (rows 4-5 are
# the A040-like [0,222,437,..,1774]; the corrected build resamples each row on its own axis). The P axis is the A040's.
# Live row is VARIANT-DEPENDENT but barely: the ROM record table at 0xECF7 (91-byte records, enable byte 0x0E, row byte
# 0x0F, same layout as the A040's, where it reproduces TLBA2 -> 1) selects row 0 for TLAA3/TLAY2/TLAY8/TLBL1 and, with
# the enable byte 0, TLAY6/TLAY7/TLBK6/TLDY6; row 1 for TLAA4 (identical to row 0); row 2 for TLBA4; row 3 for TLBA5.
# Rows 2-3 differ from row 0 only at the 7th knot (1050, not 998: up to 1001 counts of R5 at key 998); the PTM's target
# map, P and D rows are Clarity-equivalent in all of rows 0-5. Row 0 is taken. The car's variant cannot be read from openpilot.
# Envelope: unlike the A040's flat table, row 0 caps |key| at 1330 from 150 km/h (1774 up to 125 km/h); rows 1 and 2-3
# differ only above 150 km/h (row 1: 1108 from 175 km/h), so the row choice does not matter below 150 km/h.
# Carried over, NOT read from this image: load = CRV_TLA_A040_LOAD and the P/I trims (the CR-V's, see CRV_TLA_A040). R6 is computed
# from its A table: the motor-to-angle constant (3121, 0x19C00), the A table (16783 at centre, 0x11338, byte-identical to
# the A040's) and NORM (1650, PTM halfword 0x42558) all equal the A040's, so it has the A040's R6.
# Rack map predicted from the 2020+ CR-V's specs through the same A table (no yaw fit).
CRV_TLA_A220_SPEC_RACK = spec_rack_table(CRV_2020_SPEC, HONDA_VGR_INVERSE_BY_PROFILE[HONDA_VGR_CRV_TLA_A040])
CRV_TLA_A220 = EpsFirmwareCalibration(
  name="crv_tla_a220", e4_per_output=4096.0,
  r5_key_bp=(0, 161, 222, 322, 409, 534, 696, 998, 1663), r5_v=(0, 2720, 3750, 5439, 6917, 9038, 11775, 16880, 28127), key_clamp=1774,
  envelope_bp=(0, 50, 100, 150, 200, 250, 300, 350, 400), envelope_v=(1774, 1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330),
  kp_key_bp=tuple(round(k * 4096 / 3840) for k in CLARITY_TRW_A020_P_KEYS), kp_v=P_ROW_PMINUS5,
  r6_per_deg_s=CRV_TLA_A040.r6_per_deg_s, r6_angle_bp=CRV_TLA_A040.r6_angle_bp, r6_angle_gain=CRV_TLA_A040.r6_angle_gain,
  load=CRV_TLA_A040_LOAD, p_scale=CRV_TLA_A040_P_SCALE, i_scale=CRV_TLA_A040_I_SCALE,
  rack=CRV_TLA_A220_SPEC_RACK,
)

# Acura RDX 3G 39990-TJB-A220, the Route-A PTM, Trk1641 build with the runtime ROM CRC fix (RDX-PTM-101526-RomCRC.rwd,
# RWD sha256 3dd8b91b = KB TJB_A220_PTM_ROUTE_A_20261014/BUILD_Trk1641). Not the Clarity's controller family: TJB runs
# THR (Odyssey) code shifted +0x9C, with its own units, and the build ports the Clarity's tables into them (Route A).
# In the Clarity's units the law is the one honda_eps_firmware_ff inverts:
# - key: TJB takes a = E4/4 (|a| <= 1024, E4 4096); the Clarity's key is q = trunc(E4 * 56756/32768 / 4) = 1.732 a, so
#   every TJB a-axis below is x 56756/32768 and command_key() reads it unchanged (to integer rounding).
# - target map row 0 (0x57BAE/0x57BC0), = rows 1-3: 0, 3968, ..., 27776, 30000 at a = 0..1024 by 128, the Clarity's
#   row 0 at the same E4 within 1 % (each segment capped at TJB's Q26 slope limit, 31 per a).
# - P: TJB's Kp is >> 6, the Clarity's / 1024, so x 16: 7..17 -> 112..272 at a = 0,58,..,1024 (0x57C70/0x57C82),
#   within -4.3..+3.2 % of the Clarity's P117..265 at each knot. D 46 x 16 = 736 (the Clarity's 737); clamps P 7373,
#   D 1774, output 8868 (the Clarity's 9000: the motor sum caps at 8868 on both); FF45 in a code cave at the P+D sum,
#   as the Clarity's. A280 (G/H) flat. Speed envelope flat at a 1024 (0x57B3C). Emulator-exact (1500/1500 per stage).
# - R6: TJB's feedback ref has no NORM; the build scales it x 15768/32768 (= 1650/3429, the Clarity's NORM ratio) at
#   its load. Ref and the 0x18F STEER_ANGLE_RATE word come from one motor-speed product, written through struct
#   pointers (so no literal names the words): 0x1C668 takes the per-call motor position change d (wrapped to +-16384)
#   and writes ref = (d * k) >> 7 to FFF8B4B4 and x = (d * k) >> 12 = ref / 32 to FFF8B4AA; 0x1D300 publishes
#   FFF8B25E = two cascaded unity-gain one-poles (0x2FF26, 12946/32768) of (x + x_prev) / 2, clamped +-24000. So
#   ref = 32 x the published word, as on the Clarity. The word is 7.8 per published deg/s at centre (steer_ratio
#   HONDA_VGR_RDX_TJB_A220; the same method gives the Clarity's 3.82 against its firmware's 3.81), so R6 here =
#   0.4812 x 32 x -7.8 = -120.1 per published deg/s at centre: 0.98 of the Clarity's. Its angle shape is the rate
#   word's (the linear map's slope, as computed_r6). The drives cannot pin it by themselves: on routes c6 / c7 the
#   load fit through the law was flat in R^2 from 0.5x to 2x R6, since R6 trades off against the viscous term.
# - Helper A and the override fade (driver torque) stay stock, as the PTM rule keeps them: they back off harder than
#   the Clarity's once a hand pushes, but on the owner's drives they keep 0.95-0.99 of LKAS on average, as the
#   Clarity's tables would (1.00-1.015x); scale_q8 256 is the hands-off value as everywhere.
_, _, RDX_TJB_A220_R6_GAIN = computed_r6(HONDA_VGR_RDX_TJB_A220)
RDX_TJB_A220_R6_CENTRE = -120.1
_RDX_A = 56756 / 32768  # TJB a -> the Clarity's key q
# Load: fitted through this law (at the R6 above) on the sent 0xE4, since the car has no telemetry build: routes
# 412ed2539bfc2c42/000000c6 and c7 (LatControlPID) and cc and d2 (this controller), 34 min of engaged, unpressed
# frames; R^2 0.822, held out by route 0.636 / 0.847 / 0.833 / 0.790 (the two-route fit it replaces: 0.606 / 0.795 /
# 0.780 / 0.751). Route b8 is left out: which PTM build it ran is not known.
RDX_TJB_A220_LOAD = ColumnLoadModel(k0=-11.19, k1=-0.1363, c=-2.479, friction=-241.5, bias=119.2, kroll=-3.592)
# Trims, picked in a closed-loop replay (tools/lateral/eps_closed_loop.py) of the owner's routes cc and d2: the logged
# targets drive HondaEpsLateralCore into this firmware law and column (no stiction), with 40 ms of angle sensing and
# 20 ms of command transport. Driven by the logged 0xE4 alone that plant reproduces the wheel's 0.6-2.5 Hz motion at
# gain 1.03 on the freeway on both routes (correlation 0.92-0.94; 9-20 m/s 0.98 / 1.21, so town is the looser);
# closed, it reproduces the freeway ping-pong the owner reported, 1-2 Hz wheel/target 1.33 against 1.29 measured on
# d2 (cc: 1.26 / 1.18). The loop is delay-limited (0.96 with no delay, 1.42 at 70 ms), so gain is what
# rings, and the default 5 deg/s friction knee is most of it at speed: the desired rate is under 5 deg/s 95 % of the
# time there, so the knee acts as a ~47 counts per deg/s rate gain. A 15 deg/s knee at speed and P x0.7 above 50 mph
# take the freeway 1-2 Hz gain 1.32 -> 0.95 on d2 (cc 1.26 -> 1.10, 9-20 m/s 1.39 -> 1.19) for tracking RMS 0.35 ->
# 0.39 deg, with 0.1-0.5 Hz tracking unchanged (1.05 -> 1.06). Rejected there: the output LPF (default taus: 1.41 on
# the freeway, 2.13 at 9-20 m/s, its lag costs more than it smooths), a D term on the measured rate (unstable in some
# windows at 0.002-0.006), and P alone (x0.6: 1.10, but tracking 0.40 deg).
RDX_TJB_A220_P_SCALE = (1.0, 1.0, 0.7)
RDX_TJB_A220_FRICTION_WIDTH_V = (20.0, 15.0)
ACURA_RDX_TJB_A220 = EpsFirmwareCalibration(
  name="rdx_tjb_a220", e4_per_output=4096.0,
  r5_key_bp=tuple(round(a * _RDX_A) for a in (0, 128, 256, 384, 512, 640, 768, 896, 1024)),
  r5_v=(0, 3968, 7936, 11904, 15872, 19840, 23808, 27776, 30000), key_clamp=round(1024 * _RDX_A),
  envelope_bp=FLAT_ENVELOPE[0], envelope_v=FLAT_ENVELOPE[1],
  kp_key_bp=tuple(round(a * _RDX_A) for a in (0, 58, 109, 243, 320, 448, 640, 896, 1024)),
  kp_v=tuple(16 * k for k in (7, 8, 9, 11, 13, 15, 16, 17, 17)),
  r6_per_deg_s=RDX_TJB_A220_R6_CENTRE, r6_angle_bp=R6_GAIN_BP, r6_angle_gain=RDX_TJB_A220_R6_GAIN,
  load=RDX_TJB_A220_LOAD, p_scale=RDX_TJB_A220_P_SCALE, i_scale=CRV_TLA_A040_I_SCALE,
  lat_delay_schedule=RDX_TJB_A220_LAT_DELAY_SCHEDULE,
  rack=RDX_TJB_A220_RACK, friction_width_v=RDX_TJB_A220_FRICTION_WIDTH_V,
)

# normalize_honda_eps_fw(EPS fwVersion) -> (fingerprint, profile). TGG-A020 is a separate application from the A120 (its RWD updates only A010/A020)
# and has no PTM build, so it is absent on purpose.
EPS_FIRMWARE_CALIBRATIONS = {
  "39990-TRW-A020": ("HONDA_CLARITY", CLARITY_TRW_A020),
  "39990-TBA-C020": ("HONDA_CIVIC_BOSCH", CIVIC_TBA_C020),
  "39990-TBA-C120": ("HONDA_CIVIC_BOSCH", CIVIC_TBA_C120),
  "39990-TGG-A120": ("HONDA_CIVIC_BOSCH", CIVIC_TGG_A120),
  "39990-TBA-A030": ("HONDA_CIVIC", CIVIC_TBA_A030),
  "39990-TEG-A010": ("HONDA_CIVIC", CIVIC_TEG_A010),
  "39990-TXM-A040": ("HONDA_INSIGHT", INSIGHT_TXM_A040),
  "39990-TLA-A040": ("HONDA_CRV_5G", CRV_TLA_A040),
  "39990-TLA-A220": ("HONDA_CRV_5G", CRV_TLA_A220),
  # Stock A220 accepts every RDX 3G image as a source, so the 2019-21 and 2022+ (MMR) cars run the same PTM image on
  # the same rack; the vehicle side was measured on a 2019.
  "39990-TJB-A220": (("ACURA_RDX_3G", "ACURA_RDX_3G_MMR"), ACURA_RDX_TJB_A220),
}


# --- where each calibration value came from --------------------------------------------------------------------
# One line per quantity per image, so what is measured and what is carried over is auditable in one place (and is
# logged when LatControlHondaEps starts). Each value starts with its kind:
#   firmware  read or computed from the image the owners run
#   measured  fitted on that car's own drives (the routes say which)
#   inferred  carried over from a related car or derived indirectly; re-measure when its logs exist
#   spec      predicted from the car's published specs and its A table (honda_eps_spec_plant); re-measure when its logs exist
#   default   the controller-wide default, nothing car-specific yet
#   none      not applicable (no rack map: the road curve or the firmware table is the geometry)
PROVENANCE_KINDS = ('firmware', 'measured', 'inferred', 'spec', 'default', 'none')
PROVENANCE_FIELDS = ('row', 'kp_axis', 'key_clamp', 'envelope', 'r6', 'load', 'trims', 'cmd_delay', 'model_delay', 'rack')
CALIBRATION_PROVENANCE = {
  "clarity_trw_a020": {
    "row": "measured: telemetry R5 = row 0 exactly; every TRW variant record selects row 0",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table; telemetry 363/365/369 agrees within 0.7% (unrailed)",
    "load": "measured: route 352, against the firmware output (14 routes agree)",
    "trims": "measured: the tune the car drove on vfn 35ddc44b",
    "cmd_delay": "measured: plan_timing, routes 37e / 380; highway 3f1 / 3f5 by speed band",
    "model_delay": "measured: routes 36c/36d/373/377 and 362-36b",
    "rack": "measured: VSA yaw, routes 341-36b",
  },
  "civic_tba_c020": {
    "row": "measured: telemetry R5 = row 1 (route 294, live_row_fit); TBCA9/TBHC8 select row 1",
    "kp_axis": "firmware", "key_clamp": "firmware",
    "envelope": "firmware (not road-checked above 89 km/h)",
    "r6": "firmware: computed from its A table; telemetry 287/289/294 agrees within 1.9% (unrailed)",
    "load": "measured: owner telemetry 287/289/294; a 14-route refit agrees",
    "trims": "measured: the owner's tune, route 284",
    "cmd_delay": "measured: plan_timing 290/293/289; confirmed with it on, 2b7/2c6/2d4; flat to 40 m/s per route 380",
    "model_delay": "measured: route 380 by speed band, on the older controller (provisional; re-measure on this one)",
    "rack": "measured: VSA yaw, routes 294/289/2b7/2c6/2d4/1b8/251",
  },
  "civic_tba_a030": {
    "row": "firmware: rev b rows 0-5 are the TEG's row 3, so every variant (TBCA1 row 2, TBCA2 row 3) makes the same command",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table (the C120's, as the TEG-A010)",
    "load": "inferred: the TEG-A010 owner's",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "inferred: the TEG-A010's", "model_delay": "inferred: the TEG-A010's (the same car)",
    "rack": "inferred: the TEG-A010's (the same 2016-18 Civic sedan: same specs and A table)",
  },
  "civic_teg_a010": {
    "row": "measured: row 3 (TEGA2), telemetry R5 vs E4 on routes 0000012f/00000139 (live_row_fit.py teg); rev b rows 2-3 agree",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table (the C120's); telemetry 133/134/137/13d agrees within 0.8% (unrailed)",
    "load": "measured: the owner's 11 telemetry routes 0000012d-00000139 (fit_column_load.py --source teg)",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "measured: plan_timing on routes 12e/134/137/139, sized below the ~0.20 s measured; flat by speed band",
    "model_delay": "measured: routes 12e-13d by speed band (lag from the frame to its yaw curvature)",
    "rack": "measured: VSA yaw (GPS-checked scale), routes 0000012d-00000139",
  },
  "civic_tba_c120": {
    "row": "firmware: rev b rows 0-4 all carry the Clarity's R5 per key on their own axes",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table",
    "load": "inferred: the C020's",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "inferred: the C020's (same chassis)", "model_delay": "inferred: the C020's (same chassis)",
    "rack": "spec: Honda lock turns and lock ratio through its A table, R0 +-2.5%",
  },
  "civic_tgg_a120": {
    "row": "measured: row 0, its drives fit row 0's law best on all five routes (no telemetry); both variant records agree",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table (the C020's); the owner's 0x18F rate word agrees within 1 %",
    "load": "measured: the owner's routes 0000000b-00000010, through the 08-07 build's law they ran",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "inferred: the C020's (same chassis; on time to 0.15 s early on routes 0c/0d/0f, older code)",
    "model_delay": "inferred: the C020's (same chassis)",
    "rack": "measured: VSA yaw (GPS-checked scale), routes 0000000b-00000010",
  },
  "insight_txm_a040": {
    "row": "firmware: row 0 in every build and variant",
    "kp_axis": "firmware", "key_clamp": "firmware",
    "envelope": "default: not located in the image; flat assumed (the 1663 clamp binds first)",
    "r6": "firmware: computed from its A table",
    "load": "measured: the owner's konik route 0000001e",
    "trims": "inferred: the C020 owner's",
    "cmd_delay": "inferred: its LatControlPID drive (0.06 s early) plus this controller's lead over the PID",
    "model_delay": "default: the Clarity's schedule",
    "rack": "measured: VSA yaw (GPS-checked scale), route 0000001e",
  },
  "crv_tla_a040": {
    "row": "firmware: every variant record selects row 0 (TLBA2 row 1, identical)",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table; the owner's telemetry fit (route 82bb) agrees at centre",
    "load": "measured: the owner's telemetry route 82bb",
    "trims": "measured: the owner drives it untrimmed",
    "cmd_delay": "default (the owner's LatControlPID drive ran 0.08 s late: re-check on this controller)",
    "model_delay": "default: the Clarity's schedule",
    "rack": "spec: Honda lock turns and lock ratio through its A table, R0 +-2.5%",
  },
  "rdx_tjb_a220": {
    "row": "firmware: rows 0-3 carry the same Route-A target, P and D (0x57BAE + 0x300*row), so the variant row does not matter",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: ref = 32 x its 0x18F rate word (0x1C668 / 0x1D300) x 0.4812 (the build); the word measured at 7.8 per deg/s on routes b8/c7/cc/d2",
    "load": "measured: the owner's routes 000000c6 / c7 / cc / d2 (a 2019), rebuilt through the law from the sent 0xE4; the MMR takes it",
    "trims": "measured: closed-loop replay of routes cc / d2 (P x0.7 above 50 mph, a 15 deg/s friction knee at speed)",
    "cmd_delay": "measured: plan_timing on this controller, routes cc / d2: on time at 5-12 m/s (+0.04 / +0.03 s), so the default stands",
    "model_delay": "measured: 12 m/s and up, routes 00000003 / 00000004 / 0000000b on this controller; the Clarity's at crawl",
    "rack": "measured: VSA yaw (GPS-checked scale), routes 000000b8 / c6 / c7 / cc / d2 (a 2019; the MMR takes it), through its road-measured linear map",
  },
  "crv_tla_a220": {
    "row": "firmware: rows 0-5 all Clarity-equivalent in the corrected build, so the untraced variant row does not matter",
    "kp_axis": "firmware", "key_clamp": "firmware", "envelope": "firmware",
    "r6": "firmware: computed from its A table (byte-identical to the A040's)",
    "load": "inferred: the A040 owner's (the A220 drives 0x30A-0x30D ran the 10-06 build: refit after the reflash)",
    "trims": "inferred: the A040 owner's",
    "cmd_delay": "default", "model_delay": "default: the Clarity's schedule",
    "rack": "spec: Honda lock turns and lock ratio through its A table, R0 +-2.5%",
  },
}


# The corrected (revision b, 2026-10-16) PTM build each calibration models, by RWD sha256 prefix (KB
# PTM_FIX_FAMILY_20261016/out/<car>). Each earlier PTM build reports the same EPS version string, so openpilot cannot tell
# them apart, and every calibrated image steers with LatControlHondaEps: the owner must flash this build first.
REQUIRED_PTM_RWD = {
  "civic_tba_c020": "df67bf6f",
  "civic_tba_a030": "55c37266",
  "civic_teg_a010": "04147917",
  "civic_tba_c120": "9261b8db",
  "civic_tgg_a120": "6640806d",
  "insight_txm_a040": "7ba37432",
  "crv_tla_a040": "2e6a8802",
  "crv_tla_a220": "2c992997",
  "rdx_tjb_a220": "3dd8b91b",
}


def provenance(cal: EpsFirmwareCalibration) -> dict:
  return CALIBRATION_PROVENANCE[cal.name]


def provenance_summary(cal: EpsFirmwareCalibration) -> str:
  """'measured: r6, load, ... | inferred: ... | default: ...', for the startup log."""
  groups = {}
  for key in PROVENANCE_FIELDS:
    groups.setdefault(provenance(cal)[key].split(':')[0].split(' ')[0], []).append(key)
  return ' | '.join(f"{kind}: {', '.join(keys)}" for kind, keys in groups.items())


def select_eps_firmware_calibration(fingerprint: str, eps_fw: str) -> EpsFirmwareCalibration | None:
  """The profile for this car's EPS image, or None when there is no PTM build for it (or it is on another car)."""
  entry = EPS_FIRMWARE_CALIBRATIONS.get(eps_fw)
  if entry is None or fingerprint not in (entry[0] if isinstance(entry[0], tuple) else (entry[0],)):
    return None
  return entry[1]
