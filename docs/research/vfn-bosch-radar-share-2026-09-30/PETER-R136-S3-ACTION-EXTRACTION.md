# Peter R136 S3 Action Extraction

4-COUNT RANGE UPDATE CAUSES FLOOR: NO

NORMAL FLOOR PRECLIP TARGET: `-4.388995 m/s²`

FROZEN-DREL PRECLIP TARGET: `-4.388995 m/s²`

DIRECT INTERPOLATED MPC ACCEL AT FLOOR: `-1.989031 m/s²`

GET_ACCEL_FROM_PLAN RESULT: `-4.388995 m/s²`

EXTRACTION AMPLIFICATION: `-2.399964 m/s²` (production formula minus direct interpolated acceleration)

PRIMARY CAUSE: ACTION EXTRACTION

NEXT STEP: Preserve this exact frozen-input counterfactual and isolate the intended lead-obstacle response before considering any output-extraction or tuning change.

## Scope and method

- Route `00000136`, segment 3 only; stateful pre-roll begins at route-relative `221.900485 s`.
- The normal and frozen runs use the same target-revision planner, timestamps, planner state, feature flags, services, and MPC history.
- The frozen run clones only the floor-cycle `radarState` payload, then changes **only** `leadOne.dRel` from `7.16736` to the previous logged `7.39584 m`; the original log reader data is never modified.
- Normal floor pre-clip reproduction check: `-4.388995` vs expected `-4.388995` → PASS.

## Test 1 — dRel-only counterfactual

| floor-cycle input/output | normal | dRel frozen to 7.39584 m |
|---|---:|---:|
| lead0 dRel used (m) | `7.16736` | `7.39584` |
| pre-clip action target (m/s²) | `-4.388995` | `-4.388995` |
| published target after clip (m/s²) | `-3.5` | `-3.5` |
| solver a_solution[:5] | `[0.0, -2.377271, -2.620994, -1.814919, -0.208094]` | `[0.0, -2.377271, -2.620994, -1.814919, -0.208094]` |
| solver v_solution[:5] | `[2.069586, 1.987042, 1.466389, 0.696265, 0.204561]` | `[2.069586, 1.987042, 1.466389, 0.696265, 0.204561]` |
| solver x_solution[:5] | `[0.0, 0.14181, 0.502424, 0.869787, 1.057096]` | `[0.0, 0.14181, 0.502424, 0.869787, 1.057096]` |

Interpretation: freezing only the four-count range update does not prevent the under-floor MPC request.

## Test 2 and 3 — action extraction

| quantity | before 226.838976 | normal floor 226.900485 | frozen-dRel floor |
|---|---:|---:|---:|
| action_t (s) | `0.55` | `0.55` | `0.55` |
| v_now (m/s) | `2.079802` | `2.069586` | `2.069586` |
| a_now (m/s²) | `0.0` | `0.0` | `0.0` |
| v_target (m/s) | `1.241234` | `0.862612` | `0.862612` |
| current formula / pre-clip (m/s²) | `-3.04934` | `-4.388995` | `-4.388995` |
| direct interpolated accel (m/s²) | `-2.319327` | `-1.989031` | `-1.989031` |
| nearby velocity finite difference (m/s²) | `-2.118247` | `-2.217956` | `-2.217956` |
| formula − direct (m/s²) | `-0.730013` | `-2.399964` | `-2.399964` |
| bracketing CONTROL_N samples | `{'indices': [7, 8], 'times': [0.478516, 0.625], 'speeds': [1.392655, 1.082365], 'accels': [-2.173562, -2.472262]}` | `{'indices': [7, 8], 'times': [0.478516, 0.625], 'speeds': [1.021161, 0.696265], 'accels': [-2.154982, -1.814919]}` | `{'indices': [7, 8], 'times': [0.478516, 0.625], 'speeds': [1.021161, 0.696265], 'accels': [-2.154982, -1.814919]}` |

The current formula is `2 * (v_target - v_now) / action_t - a_now`. The direct column is `interp(action_t, CONTROL_N_T_IDX, a_desired_trajectory)`. The finite-difference column uses only the two `CONTROL_N_T_IDX` samples bracketing `action_t`.

## Answer

- The raw solver trajectory already changes materially: `a_solution[1]` is `-2.377271` on the normal floor cycle versus `-2.377271` with only dRel frozen.
- At the action time itself, however, direct interpolated MPC acceleration *relaxes* from `-2.319327` before the floor to `-1.989031 m/s²` at floor entry, while the production output becomes `-4.388995 m/s²`. The large before→floor action jump is therefore introduced/amplified by the velocity-based extraction rather than already present in the action-time acceleration trajectory.
- The production action reconstruction adds `-2.399964 m/s²` relative to direct acceleration interpolation at floor entry. It therefore magnifies the solved trajectory transition, but this report does not propose replacing it.
- The normal floor-cycle solver uses the new four-count range; the frozen replay result above answers whether that update is necessary for the request.
