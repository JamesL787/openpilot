# Bosch-A robust longitudinal-velocity design

Offline-only investigation for the Honda Civic Bosch-A radar integration. No
openpilot production file was changed, and nothing was committed or pushed.

## Executive result

~~~yaml
TARGET_OPENPILOT_HEAD: 42c2a191729afac16399e55496669b9dd29ee1df
TARGET_COMMIT: honda: harden Bosch radar measurement handling
CORPUS: 0000010c, 00000112, 00000114, 00000116, 00000125, 00000136, 00000139
NEW_PETER_ROUTES_INCLUDED: 00000136, 00000139
COORDINATE_A: decoded Bosch range, the coordinate published as dRel
COORDINATE_B: slant-range longitudinal x = range*cos(azimuth)
ESTIMATOR: median of all pairwise temporal slopes over accepted positions
BIRTH_VARIANT: A4B3 = three-sample estimate at the fourth accepted observation
BEST_AGGREGATE_ERROR: A5, but with approximately 270 ms acquisition age
BEST_LATENCY_TRADEOFF: A4, approximately 201 ms acquisition age
PETER_RESET: PASS for accepted-history admission; reset is not rebased
ID22_COUNTERFACTUAL: improved aLeadK tail, but severe negative tail remains
ID35_COUNTERFACTUAL: A4/A5 worsened the selected-track aLeadK tail
RADARD_REPLAY: completed through an exact-target RadarD/KF/lead harness
LONGITUDINAL_PLAN_REPLAY: not performed; no aTarget or 0x1DF claim is made
PRODUCTION_RECOMMENDATION: DO NOT IMPLEMENT A4/A5 YET
~~~

The central result is that a robust temporal estimate can be built from the
same longitudinal coordinate the interface publishes as dRel:

~~~text
x = decoded_range
vRel = median((x[j] - x[i]) / (t[j] - t[i]) for every i < j)
~~~

The slant-range alternative is:

~~~text
x = decoded_range * cos(theta)
y = -decoded_range * sin(theta)
~~~

The available evidence does not justify changing the published Bosch range
contract to slant range. A4 is the safer coordinate choice for a future
experiment, but the RadarD counterfactual rejects shipping either A4 or A5 as
the complete fix.

## Scope and revisions

The target openpilot revision was inspected without checking out the user's
dirty working tree:

~~~text
42c2a191729afac16399e55496669b9dd29ee1df
honda: harden Bosch radar measurement handling
~~~

The local openpilot checkout was on another branch with unrelated changes;
those files were left untouched. The offline tools in this workspace are not
production imports.

The expanded corpus contains the five earlier Peter/C020 route families plus
the two new Peter routes found in ~/Downloads today:

| route | valid geometry rows, per candidate |
|---|---:|
| 0000010c | 25,048 |
| 00000112 | 7,025 |
| 00000114 | 46,788 |
| 00000116 | 17,931 |
| 00000125 | 52,740 |
| 00000136 | 61,597 |
| 00000139 | 73,608 |
| **total** | **284,737** |

The final all export has 284,737 rows for each of the eight candidate
variants, or 2,277,896 candidate rows. It exports every reconstructed
physical observation that passes the common geometry/identity checks; it is
not limited to model-matched objects.

## What was corrected in the offline evaluator

The evaluator was audited before using the new routes:

1. AUX frame index is (B1 >> 1) & 0xF, not the low nibble of B1.
2. Theil-Sen/pairwise slope aggregation uses the true statistical median. An
   even number of slopes averages the two middle values; it does not choose
   the upper middle value.
3. Invalid status, range, azimuth, lifecycle, and TRACK_ID values are rejected
   using the target parser's sentinel rules.
4. U11 is not used by the trajectory candidates. It is exported separately as
   a comparison field so the trajectory experiment does not accidentally blend
   the questioned wire candidate into itself.
5. carState.vEgo is exported and used as an independent relative-velocity
   reference alongside model lead velocity.
6. A3, A4B3, A4, A5, B3, B4B3, B4, and B5 are written for every accepted
   physical observation, not only for model matches.
7. Per-route/segment state is reset correctly, and late AUX arrival upgrades
   an existing physical observation instead of creating a duplicate row.

## Candidate definitions

All variants retain the target parser's persistent CAN TRACK_ID and lifecycle
handling. A birth requires accepted geometry history; no one-sweep synthetic
velocity is published.

| candidate | longitudinal coordinate | window/behavior |
|---|---|---|
| A3 | decoded range | median pairwise slopes over three accepted positions |
| A4B3 | decoded range | three-point estimate at the fourth accepted observation, then A4 |
| A4 | decoded range | median pairwise slopes over four accepted positions |
| A5 | decoded range | median pairwise slopes over five accepted positions |
| B3 | range*cos(theta) | same three-position estimator on slant longitudinal x |
| B4B3 | range*cos(theta) | three-point birth variant, then B4 |
| B4 | range*cos(theta) | four-position estimator |
| B5 | range*cos(theta) | five-position estimator |

The A lateral coordinate is -dRel*tan(theta), matching the current parser's
published coordinate. The B geometry uses -range*sin(theta) only as its
alternative Cartesian y coordinate.

## Full-corpus comparison

The following values are candidate estimate minus the matched model relative
velocity. Model lead velocity is compared against modelV2.velocity.x; an
independent table in the CSV compares the same candidate against carState.vEgo.
Neither is Bosch's hidden S+0x28 value.

| candidate | n | bias | MAE | RMSE | p95 abs | p99 abs | max abs | age median | age p95 | age max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A3 | 62,266 | -0.043 | 1.283 | 3.027 | 4.457 | 11.263 | 60.010 | 132 ms | 143 ms | 946 ms |
| A4B3 | 62,266 | -0.043 | 1.233 | 2.957 | 4.240 | 10.853 | 53.474 | 201 ms | 212 ms | 1,017 ms |
| A4 | 62,027 | -0.029 | 1.211 | 2.862 | 4.175 | 10.527 | 53.383 | 201 ms | 212 ms | 1,017 ms |
| A5 | 61,796 | -0.016 | 1.166 | 2.745 | 4.054 | 9.945 | 49.507 | 270 ms | 281 ms | 1,076 ms |
| B4 | 62,399 | -0.030 | 1.214 | 2.873 | 4.187 | 10.589 | 54.076 | 201 ms | 212 ms | 1,017 ms |
| B5 | 62,161 | -0.016 | 1.168 | 2.753 | 4.055 | 9.987 | 50.210 | 270 ms | 281 ms | 1,076 ms |

Against carState.vEgo, A4 bias is -0.003 m/s and A5 bias is +0.010 m/s.
That corrected result matters: the earlier apparent +0.5--0.6 m/s bias came
from the old upper-middle median implementation and the earlier matching
setup, not evidence for a production offset.

A5 has the best aggregate error, but it adds roughly one 15 Hz sweep of age.
A4 is the reasonable latency candidate. Neither passes the safety decision
because the sparse position-matched tails still reach approximately 50--53
m/s, and RadarD behavior is not determined by aggregate velocity error alone.

## Peter reset sequence

The exact synthetic reset sequence used for the prior Peter investigation was
replayed through the corrected estimator admission logic. The native identity
was 23 and the rows were:

~~~text
time ms:       0, 70.696, 120.413, 200.552, 260.482, 331.286
range raw:     203, 198, 64, 82, 96, 102
U11 raw:       713, 740, 463, 554, 727, 795
U10 raw:       136, 92, 612, 437, 101, 31
range sigma:   2, 2, 4, 4, 2, 1
existence raw: 3, 76, 0, 0, 0, 0
00CA raw:      512, 510, 509, 508, 508, 508
~~~

The large range reset is rejected and does not become the next derivative
baseline. The evaluator preserves the last accepted range and does not emit a
new -30/-40/-50 m/s trajectory velocity from the reset. This is a pass for the
admission rule, not proof that every historical Peter route can be reproduced
with the same identity bookkeeping.

## RadarD/KF counterfactual

The counterfactual harness uses the target branch's Civic Bosch RadarD cadence
and KF timestep (1/15), the target Track update behavior, vision matching,
preferred-track continuity, lead selection, and Civic low-speed maturity gate.
It changes only the source velocity supplied to the track simulation; IDs,
range, lateral position, timestamps, ego speed, and model rows are preserved.

There was a smoke validation against route 00000125 segment 4: the simulator
matched the logged lead ID on 757 comparable model rows, with mean absolute
aLeadK difference 0.0595 and maximum difference 0.9705. This validates the
shape of the downstream harness, not the full vehicle control loop.

### Targeted events

| route/segment/ID | physical obs | current logged vRel | current aLeadK min | A4 vRel | A5 vRel | A4 aLeadK min | A5 aLeadK min |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0000010c / 11 / 23 | 7 | no comparable current vRel | -10.253 | no mature A4 | no mature A5 | n/a | n/a |
| 00000125 / 4 / 50 | 894 | -5.188..6.688 | -4.134 | -6.125..10.116 | -5.041..8.138 | -4.023 | -4.023 |
| 00000125 / 6 / 22 | 138 | -1.156..7.485 | -7.247 | -2.855..4.208 | -2.746..3.820 | -6.822 | -6.822 |
| 00000125 / 11 / 35 | 71 | -5.203..6.078 | -7.827 | -6.210..4.865 | -5.785..4.469 | -9.327 | -9.327 |

The route 0000010c event uses older synthetic IDs in the historical log, so it
cannot be claimed as an exact current-branch RadarInterface reproduction. The
event CSV still preserves every available physical observation for ID 23.

ID50 is ordinary in this counterfactual; the relevant concern there is lead
selection/track context rather than an obvious trajectory catastrophe. ID22
improves modestly but retains a severe negative aLeadK tail. ID35 is the
decisive rejection: the A4/A5 candidate makes the selected-track aLeadK
minimum worse, approximately -9.33 m/s2 versus the current logged minimum
near -7.83 m/s2. Therefore a temporal range estimator alone is not the fix for
Peter's EXP braking behavior.

The harness stops at RadarD/KF and lead-state reconstruction. It does not run
LongitudinalPlan, LongControl, Honda CAN packing, or raw 0x1DF generation. No
claim about final aTarget, actuator acceleration, or brake command can be
made from this artifact.

## Sin versus tan

The current parser uses:

~~~text
yRel = -dRel * tan(azimuth)
~~~

The alternative uses -dRel*sin(azimuth) while treating the slant range as the
longitudinal coordinate. Across the available matched data, A4/B4 and A5/B5
are statistically tied. The previously investigated route-125 windows showed
a maximum sin/tan lateral difference of about 0.035 m. That is not large
enough to explain the severe braking events.

The evidence continues to support the current sign convention: positive Bosch
azimuth produces negative OpenPilot yRel. No parser-wide left/right reversal
was found in this pass.

## What this does and does not establish

### Proven or directly verified

- The two new Peter routes 00000136 and 00000139 were included in the replay.
- AUX frame index extraction is (B1 >> 1) & 0xF.
- The true median, not upper-middle selection, removes the old artificial
  positive velocity bias.
- Accepted-history protection prevents the known range reset from rebasing the
  temporal fallback.
- Every candidate trajectory is exported for every accepted physical
  observation, with carState vEgo retained as a separate reference.
- Target RadarD/KF/lead behavior can be reproduced closely enough for a
  controlled source-velocity counterfactual.
- A4/A5 do not universally remove the severe ID22/ID35 downstream tails.

### Strong evidence / working hypotheses

- A4 is the best initial range-coordinate experiment if a parser experiment is
  still desired; A5 trades lower aggregate error for more latency.
- The remaining severe braking behavior is likely downstream of, or coupled to,
  track/lead selection, KF state, planner arbitration, or EXP tuning rather
  than being solved by replacing OLS with a trajectory slope alone.
- The current tan coordinate is internally consistent and should not be
  changed as part of the vRel experiment.

### Still unknown

- The exact Bosch S+0x28 row membership, weighting, promotion, and reset policy
  are not reproduced bit-for-bit.
- The physical meaning and authority rules of the AUX U11/U10 fields are not
  fully closed, so U11 remains a separately compared native candidate rather
  than an input to A/B.
- The counterfactual does not determine whether the final severe command is
  introduced in aLeadK, longitudinalPlan.aTarget, LongControl, or Honda CAN
  command packing.
- Route 0000010c's old synthetic identity encoding limits direct comparison
  with the current persistent TRACK_ID parser.

## Recommendation

Do not implement A4, A5, a sin/tan change, or a velocity bias from this pass.
The next production-relevant replay should run the exact target pipeline past
RadarD through LongitudinalPlan, LongControl, and Honda 0x1DF, with current
and candidate vRel as the only changed input. Record:

~~~text
radarState.leadOne / leadTwo
Track vRel and vLeadK / aLeadK
longitudinalPlan.aTarget and shouldStop
controlsState.longControlState
carControl.actuators.accel
ACC_CONTROL.ACCEL_COMMAND / BRAKE_REQUEST
~~~

If the planner target is sane but LongControl or the CAN command remains too
negative, investigate that downstream path. If the planner itself becomes too
negative while the track identity and geometry are sane, investigate lead
selection and EXP/MPC arbitration. Do not add a final CAN smoothing filter or
an arbitrary acceleration offset to hide the source.

## Artifacts

- analysis/trajectory_eval_final/bosch_vrel_trajectory_comparison.csv — full
  model- and carState-relative statistics, including age percentiles.
- analysis/trajectory_eval_final/bosch_vrel_trajectory_all.csv — every
  candidate trajectory estimate for every accepted physical observation.
- analysis/trajectory_eval_final/bosch_vrel_trajectory_samples.csv — matched
  samples used for the aggregate comparison.
- analysis/trajectory_counterfactual/bosch_radard_counterfactual.csv —
  exact-target RadarD/KF event replay rows.
- analysis/trajectory_counterfactual/bosch_radard_event_comparison.csv —
  model-cycle event comparison.
- analysis/trajectory_counterfactual/bosch_radard_event_tracks.csv — full
  per-observation event export for Peter reset/ID23 and route-125 IDs 50, 22,
  and 35.
- tools/bosch_vrel_trajectory_eval.py — corrected offline evaluator.
- tools/bosch_radard_counterfactual.py — offline RadarD/KF counterfactual
  harness.

## Reproducibility

Both offline tools compile under the workspace virtual environment:

~~~text
./.venv/bin/python -m py_compile tools/bosch_vrel_trajectory_eval.py tools/bosch_radard_counterfactual.py
~~~

The evaluator accepts Peter rlog paths as positional inputs and writes its
three CSV outputs under --out. The RadarD harness accepts the evaluator's
bosch_vrel_trajectory_all.csv with --candidate-csv, selected rlogs via
--log-glob, and writes the three counterfactual CSV outputs under --out.
The checked-in report artifacts are the final outputs from those offline
replays; no production checkout was modified.
