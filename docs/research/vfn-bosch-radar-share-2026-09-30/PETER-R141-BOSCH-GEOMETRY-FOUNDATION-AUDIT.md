# Peter R141 Bosch geometry foundation audit

## Summary

RANGE SCALE CURRENT:
0.05712 m/count

RANGE SCALE EMPIRICAL:
UNKNOWN — no retained interval contains raw Bosch `RANGE_RAW`

RANGE SCALE ERROR:
UNKNOWN

RANGE SCALE:
INCONCLUSIVE

CURRENT RANGE OFFSET:
-3.0 m

OFFSET ORIGIN:
INHERITED_ASSUMPTION — historical capture-derived fit carried into the Bosch-A parser; not firmware-proven and not independently re-measured here

BEST-SUPPORTED OFFSET:
UNKNOWN (the retained model comparison weakly favors -1 m, but model range is not ground truth and the scale was not independently established)

CURRENT DREL:
INCONCLUSIVE

POST-FIX YREL PHYSICAL ALIGNMENT:
PARTIAL

YREL PHYSICAL CHECK:
0 correct / 0 wrong / 5 ambiguous — no route video or raw azimuth payload was retained

RADAR VS MODEL MEDIAN RANGE BIAS:
-1.987 m over four stopped/near-stopped approach windows

RADAR VS MODEL ERROR SHAPE:
MIXED

29-FT SCENE:
  radar dRel = NOT RETAINED
  model x = NOT RETAINED
  model x-1.52 = NOT RETAINED
  residual = NOT COMPUTABLE

DISPLAYED "SECONDS" ACTUALLY MEANS:
HEADWAY-LIKE DISTANCE / EGO-SPEED, not raw TTC

DISPLAYED "DESIRED" ACTUALLY MEANS:
the positive `starpilotPlan.desiredFollowDistance` converted to display units; zero is the UI fallback when the field is absent or non-positive

UI ADDS DREL OFFSET/SCALE:
NO

FOUNDATION GEOMETRY TRUSTWORTHY:
PARTIAL

The main result is a data-availability limitation, not a clean calibration
validation. The parser's raw field identity and current equations are clear,
but the locally retained R141 artifact cannot independently prove meters per
raw count, absolute offset, or physical left/right side.

## 1. Provenance and scope

Repository inspected:

`/Users/REDACTED_USER/nrdr/openpilot-boschradar-inspect`

Branch and current revision:

```text
night-star-bosch-radar
70de34f885 honda: open Bosch-A radar gate to the full bosch_a harness category
parent: f96cfdb8f7 honda: fix inverted yRel sign in Bosch-A radar decoder
```

The worktree also has two unrelated pre-existing UI modifications:

```text
M selfdrive/ui/onroad/model_renderer.py
M starpilot/ui/qt/onroad/starpilot_annotated_camera.cc
```

They were not modified by this audit.

The retained R141 route artifacts are:

```text
/tmp/route141_analysis.json
/tmp/route141_windows.json
```

Route metadata from the artifact:

| item | value |
|---|---|
| dongle | `11c8fa231c0499ed` |
| route | `00000141--d3a05962de` |
| vehicle fingerprint | `HONDA_CIVIC_BOSCH` |
| recorded branch | `night-star-bosch-radar` |
| recorded commit | `7315fb15f58fd6a6f7e9ebe748b87f4fc6f21789` |
| recorded dirty flag | false |
| version | `0.11.2` |
| current route-relative bookmark events | 10 |

The route was therefore recorded before the current yRel sign-fix commit
`f96cfdb8f7`. Range values are unaffected by that sign change. For sign checks
below, the old logged yRel was reinterpreted offline as
`corrected_yRel = -logged_yRel`; this is not a new post-fix capture.

The original R141 rlog segments are no longer present under `/Users/REDACTED_USER
or `/tmp`. The extraction script remains at
`/tmp/extract_route141_bookmarks.py`. It explicitly retained only CAN address
`0x1DF`:

```python
if int(p.address) == 0x1DF:
  vals.append(...)
```

Consequently, no R141 `0x280..0x2FF`, `0x2C8..0x2CF`, or other Bosch object
payload is available for direct decoding in this audit. The four retained
streams are still sufficient for model/radar residuals and UI-source audit,
but not for the requested independent raw-range calibration.

## 2. Current Bosch geometry definitions

The current parser defines, in
`opendbc_repo/opendbc/car/honda/radar_interface.py`:

```text
RANGE_RAW    = DBC signal 23|12@0+
AZIMUTH_RAW  = DBC signal 39|11@0+
raw range carrier = logical 0x0016
raw azimuth center = 1024
azimuth_rad = (AZIMUTH_RAW - 1024) / 2048
dRel = 0.05712 * RANGE_RAW - 3.0
yRel = dRel * tan(azimuth_rad)
```

The source lines are current parser lines 56–68 and 421–437. Firmware tracing
proves the logical range carrier and its internal Q8 conversion (`q16 = 8 *
RANGE_RAW`), but it does not prove the conversion from that carrier to meters.
The worklog itself says exact physical scale/offset still require calibration.

The current sign-fix commit changes only the sign bridge:

```text
old: yRel = -dRel * tan(azimuth_rad)
new: yRel =  dRel * tan(azimuth_rad)
```

Its stated evidence was a visual road-camera check on other captures: a
stationary left-side queue was rendered on the right by both radar overlays
before the fix. That is useful independent historical evidence, but it is not
the requested R141 frame-by-frame visual validation.

## 3. Independent range-scale test

### Result

There are zero qualifying independent scale intervals in the retained R141
artifact.

The required estimator is:

```text
meters_per_count = integral(vEgo * dt) / abs(delta RANGE_RAW)
```

It cannot be evaluated because `RANGE_RAW` was not retained. Reconstructing it
from `dRel` would simply invert the current parser equation and would be
circular, so it was not done. Existing `dRel` samples were not substituted as
raw CAN evidence.

| requested evidence | result |
|---|---|
| 5–10 stopped-target intervals | 0 available |
| raw range start/end | unavailable |
| raw range delta | unavailable |
| integrated ego distance | not sufficient without raw delta |
| empirical m/count | not computable |
| median/mean/std/min/max | not computable |
| percent error vs 0.05712 | not computable |

This leaves `0.05712 m/count` as a historical empirical constant, not a
route-141 independently verified physical scale.

## 4. Where -3.0 m came from

The current parser's original Bosch-A rebuild commit (`59352e476e`) introduced
both constants with the comment that the firmware provides `q16 = 8 *
raw_range` while the physical slope/offset are “replay-refinable constants.”
The commit message describes replay validation, but does not cite a tape
measurement or a firmware meter conversion.

The worklogs describe the old 16-bit expression as:

```text
0.00357 * BE16 = 0.05712 * logical_0x0016 + 0.00357 * FRAME_INDEX
```

and explicitly say that the exact physical scale/offset still require
calibration. Therefore the defensible classification is:

```text
-3.0 m: INHERITED_ASSUMPTION
0.05712 m/count: historical capture-derived fit, also not independently proven here
```

It is not `FIRMWARE_PROVEN`, and there is no evidence in the retained R141
artifact that -3.0 was measured with a tape or derived from a known physical
target gap.

## 5. Model-supporting range comparison

This section is supporting evidence only. It does not prove absolute range,
because model lead x is itself an estimate and the saved route was recorded
before the sign fix.

For each row:

```text
model_equivalent_dRel = model lead0 x[0] - 1.52
residual = parser dRel - model_equivalent_dRel
```

The four selected windows are the cleanest stopped/near-stopped approaches in
the retained bookmark windows. Their native IDs remained stable throughout
the window.

| event | segment / route-relative bookmark | ID | duration | dRel start → end (m) | median vLead (m/s) | median residual (m) | MAE (m) | RMSE (m) | residual slope vs dRel |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R141-2 | 1 / 69.152 | 20 | 3.901 s | 28.530 → 20.933 | -0.086 | -4.685 | 4.482 | 4.747 | -0.014 |
| R141-5 | 3 / 232.425 | 53 | 3.902 s | 45.838 → 25.674 | -0.445 | -1.792 | 2.071 | 2.332 | +0.210 |
| R141-7 | 4 / 276.875 | 21 | 3.902 s | 16.706 → 10.366 | +0.485 | -2.110 | 2.176 | 2.212 | +0.054 |
| R141-10 | 6 / 361.767 | 40 | 3.891 s | 15.507 → 10.652 | +0.597 | -0.339 | 0.853 | 0.926 | +0.566 |

Aggregate across these four windows (316 matched rows):

```text
median residual = -1.987 m
mean residual   = -2.097 m
MAE             =  2.395 m
RMSE            =  2.903 m
```

The per-window slopes disagree materially, from approximately -0.014 to
 +0.566 m/m. That is not a clean single scale-error signature. The aggregate
 slope is approximately -0.035 m/m, but the sequence-level behavior is better
 classified as `MIXED`: bias plus model/association/target-motion effects.

### Offset-only sensitivity, not a calibration result

Holding the current scale fixed and shifting the current dRel by the offset
difference gives the following model residual sensitivity. This is included
only to show why an offset cannot be promoted from this evidence.

| candidate offset | median residual (m) | mean residual (m) | MAE (m) | RMSE (m) |
|---:|---:|---:|---:|---:|
| 0 m | +1.013 | +0.903 | 1.793 | 2.201 |
| -1 m | +0.013 | -0.097 | 1.501 | 2.010 |
| -2 m | -0.987 | -1.097 | 1.779 | 2.288 |
| -3 m | -1.987 | -2.097 | 2.395 | 2.903 |

The four-window model comparison weakly favors -1 m, but it is not a physical
ground truth and the independent scale prerequisite was not met. Therefore the
top-level offset verdict remains `UNKNOWN`, not “change to -1.”

For context, all ten retained bookmark windows were also inspected. The
non-stopped/moving windows produced substantially different residuals (for
example, approximately -9.4 m and -16.8 m medians), reinforcing that model
distance is not an absolute calibration reference.

## 6. Corrected yRel audit

### What could be checked

The retained artifact does contain `liveTracks`, but only the parser output:

```text
trackId, dRel, yRel, vRel, measured
```

It does not contain the raw Bosch azimuth bytes, camera frames, or a camera
annotation. The useful asymmetric scenes cited in the request around route
times approximately 152.3 s and 156.0 s are outside the retained bookmark
windows. Therefore no target can be labeled from the actual R141 camera as
LEFT, CENTER, or RIGHT.

The five representative retained raw-track rows below show the exact offline
sign reinterpretation. `logged yRel` is from the pre-fix route; `corrected
yRel` is its negation. “Physical side” is deliberately `UNKNOWN`, not guessed.

| segment / local time | track ID | dRel (m) | logged yRel (m) | offline corrected yRel (m) | nearest model lead | model y (m) | expected radar y = -model y (m) | physical side |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 / 3.570 s | 20 | 39.383 | -0.250 | +0.250 | 0 | -0.099 | +0.099 | UNKNOWN |
| 1 / 3.570 s | 15 | 53.834 | -3.580 | +3.580 | 1 | -0.078 | +0.078 | UNKNOWN |
| 1 / 4.233 s | 33 | 52.692 | -7.748 | +7.748 | 1 | -0.014 | +0.014 | UNKNOWN |
| 2 / 13.533 s | 26 | 28.987 | +0.269 | -0.269 | 0 | +0.443 | UNKNOWN |
| 2 / 13.059 s | 38 | 43.381 | -16.637 | +16.637 | 1 | +0.477 | UNKNOWN |

Across 1,350 retained liveTracks rows with a nearest model lead and a
longitudinal mismatch no larger than 10 m, the offline corrected-sign
comparison had:

```text
median abs(corrected yRel - (-model y)) = 0.184 m
fraction within 1.0 m = 65.3%
```

The old sign on the same retained rows had median absolute error 0.455 m and
64.1% within 1.0 m. This is only model-convention support; it is not a physical
side proof. Large outliers are present because the table includes clutter and
non-lead objects, and because the logged association was made before the sign
fix.

### Verdict

The source-level polarity is internally consistent with the current contract:

```text
AZIMUTH_RAW > 1024 -> yRel positive -> left in the standard car-frame convention
radard vision comparison -> track.yRel ~= -modelLead.y
```

The physical R141 check is `0/0/5` because the necessary camera/raw-angle
evidence is absent. The best evidence available supports `PARTIAL`, not a full
R141 physical confirmation. The existing sign-fix commit’s prior two-route
visual observation remains the strongest physical evidence currently recorded.

## 7. UI lead-metric audit

The two UI implementations use the same semantics.

### Distance

Sources:

```text
selfdrive/ui/onroad/model_renderer.py:536-541
starpilot/ui/qt/onroad/starpilot_annotated_camera.cc:697-702
```

Primary lead:

```text
lead_distance = leadOne.dRel
```

Adjacent lead only:

```text
lead_distance = dRel + abs(yRel)
```

Then the display applies only units conversion:

```text
metric: meters
imperial: dRel * 3.280839... -> rounded feet
```

The UI does not apply `0.05712`, `-3.0`, `RADAR_TO_CAMERA`, or any second
radar/camera correction. The displayed primary distance is whatever
`RadarState.LeadData.dRel` already contains.

### Lead speed

Source:

```text
RadarState.LeadData.vLead
```

Formula:

```text
displayed_speed = round(max(vLead, 0.0) * unit_conversion)
```

This means a negative lead speed is deliberately clamped to zero in the UI.
The displayed `0 mph` does not prove zero relative velocity or zero closing
speed.

### Seconds

Python UI source:

```text
v_ego = max(carState.vEgo, 0.0)
time_gap = lead_distance / max(v_ego, 1.0)
```

Qt UI source is algebraically identical:

```text
timeGap = leadDistance / max(speed / speedConversion, 1.0f)
```

Therefore the displayed number is a headway-like distance/ego-speed value,
with a 1 m/s denominator floor. It is not raw TTC, because it does not use
`vRel` or closing speed, and it is not model TTC.

For the approximate values written in the request:

```text
29 ft = 8.8392 m
11 mph = 4.9174 m/s
8.8392 / 4.9174 = 1.80 s
```

So a literal 2.79 s display cannot be reproduced from exactly 29 ft and 11
mph using the current formula. A 2.79 s display at 8.8392 m would imply
approximately 3.17 m/s (7.1 mph) when above the 1 m/s floor. The exact R141
underlying samples were not retained, so this discrepancy cannot be resolved
into a route-specific cause here.

For an actual raw-velocity TTC diagnostic, use:

```text
closing_speed = max(-vRel, 0.0)
TTC = dRel / closing_speed, when closing_speed > 0
```

That is not what the UI currently displays.

### “Desired: 0”

Python source `model_renderer.py:548-552` and Qt source
`starpilot_annotated_camera.cc:710-712` read:

```text
starpilotPlan.desiredFollowDistance
```

The Python path uses zero when the message is absent or the value is not
positive. The Qt path clamps the converted result to zero. The producer writes
the field from `starpilot_following.desired_follow_distance` in
`starpilot/controls/starpilot_planner.py:329`.

Thus `Desired: 0` is not a radar-measured gap and not a calculated TTC. It is
the UI representation of a non-positive/unavailable desired-follow-distance
value at that sample, or a mode-specific placeholder. The saved R141
extraction did not include `desiredFollowDistance`, so it cannot distinguish
those cases for this drive.

## 8. Conclusions

### Proven

- Current parser range carrier is a 12-bit DBC signal at `23|12@0+`.
- Firmware proves the internal logical carrier and Q8 scaling, not meters.
- Current post-fix parser uses `dRel = 0.05712*raw - 3.0` and `yRel = dRel*tan(angle)`.
- Current corrected sign is positive for the parser’s left-positive car-frame convention.
- R141 route artifacts were recorded on pre-sign-fix commit `7315fb15f5`.
- Retained CAN data is only Honda `0x1DF`; Bosch object payloads are absent.
- Primary UI distance is `dRel` plus only unit conversion.
- UI lead speed is nonnegative-clamped `vLead`.
- UI “seconds” is `dRel / max(vEgo, 1.0)`.
- UI “Desired” comes from `starpilotPlan.desiredFollowDistance`, with a zero fallback/clamp.

### Strong but limited evidence

- Four R141 stopped/near-stopped approach windows show a model-support residual
  median of -1.987 m under the current equation.
- Holding the current scale fixed, -1 m produces the smallest aggregate model
  residual among the tested offsets, but this is not calibration proof.
- Offline sign inversion slightly improves median agreement with the
  model-convention relation `track.yRel ~= -model.y` on retained points.
- The prior sign-fix commit contains two-route visual evidence that the old
  polarity rendered a left-side queue on the right.

### Still unknown

- Independent physical meters/count from R141.
- Independent absolute range offset from R141.
- The exact raw Bosch object payloads for the requested scenes.
- Physical left/center/right classification for five R141 frames.
- The actual raw inputs behind the screenshot-like 29-ft scene.
- Whether `Desired: 0` was a real non-positive planner value or an unavailable
  field at that moment.

## 9. Smallest next evidence request

Re-extract the original R141 rlogs while retaining all Bosch object CAN frames
and camera/model timestamps around the four stopped approaches and the 29-ft
scene; then repeat the scale, offset, and physical-side tests from raw payloads
rather than from already-decoded `dRel`/`yRel`.

No production code, repository files, commits, or pushes were changed by this
audit.
