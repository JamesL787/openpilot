# Peter Bosch ID27 Lane/Identity Scalpel

ID27 AT CLEAR: **LEFT_ADJACENT**

MODEL LEAD0 AT CLEAR: **EGO_LANE**

ID38 AT CLEAR: **RIGHT_ADJACENT**

ID27 STRICT RECOVERY CAUSED BY: **ID27_MOVED_TOWARD_MODEL**

ID27 RELAXED REATTACHMENT: **JUSTIFIED**

ID27 CLEAR CLASSIFICATION: **TRUE_STALE**

SAME FAILURE PATTERN AS S33 ID24: **PARTIAL**

ARM A NOW CLOSED: **YES**

READY FOR PRODUCTION PATCH: **YES**

ID27 was genuinely on the wrong side of the ego lane at the Arm-A clear. Its later strict recovery was not created by wider uncertainty: ID27 physically moved back toward the model lead and into the ego lane, while the model lead simultaneously moved toward ID27. The relaxed-only reattachment occurred after that real convergence was already well established.

## Scope and method

- Revision: `42c2a191729afac16399e55496669b9dd29ee1df`.
- Input: route `00000139`, segment 41, log window `5175.0..5184.2` only.
- Raw log: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--41--rlog.zst`.
- Radar coordinates were converted to model convention with `radar_model_y = -yRel`.
- At each radar distance, the ego-lane boundaries were interpolated from `modelV2.laneLines[1]` and `[2]`. Values between those boundaries are `EGO_LANE`; values below the negative/left boundary are `LEFT_ADJACENT`; values above the positive/right boundary are `RIGHT_ADJACENT`.
- Strict matching uses the target-revision distance, lateral, and velocity gates. The normalized values below are absolute mismatch divided by strict allowance.
- `laneChangeState` remained `off` and `laneChangeDirection` remained `none` for every inspected model cycle. No lane-change filter explains the result.
- No production file was changed.

## Lane-relative geometry over the full window

Model lead0 remains in `EGO_LANE` throughout `5175.0..5184.2`.

ID27's lane-state transitions are:

| time | classification | radar_model_y | interpolated left/right boundaries |
|---:|---|---:|---|
| 5175.034841 | EGO_LANE | -0.284 | -1.869 / +1.895 |
| 5179.485084 | LEFT_ADJACENT | -1.211 | -1.205 / +2.580 |
| 5179.532737 | EGO_LANE | -1.211 | -1.258 / +2.550 |
| 5179.685200 | LEFT_ADJACENT | -1.246 | -1.229 / +2.533 |
| 5182.334097 | EGO_LANE | -0.946 | -0.978 / +2.787 |
| 5182.386639 | LEFT_ADJACENT | -0.945 | -0.922 / +2.817 |
| 5182.485113 | EGO_LANE | -0.881 | -0.954 / +2.789 |

After `5182.485113`, ID27 remains in the ego lane through relaxed reattachment and strict recovery.

ID38 is on the right side for the entire clear cluster. It first briefly reaches the ego-lane boundary at `5181.384256`, after the Arm-A clear. Thus, at the clear itself:

- model lead0 is in the ego lane and on its positive/right side;
- ID38 is just outside the right boundary and is on the **same lateral side** as model lead0;
- preferred ID27 is outside the left boundary and is on the **opposite lateral side**.

The track on the same physical side as model lead0 is therefore **ID38**, although neither radar track is cleanly in the ego lane at the exact clear cycle.

## Three decisive moments

### A — last strict ID27 before clear

Time: `5175.833379`

| quantity | value |
|---|---:|
| model x / y / v | 83.957 / +0.339 / 28.491 |
| model xStd / yStd / vStd | 3.822 / 0.289 / 1.447 |
| model probability | 0.9987 |
| ID27 dRel / yRel / vRel | 65.772 / +0.578 / +0.453 |
| absolute D / allowance / normalized | 16.665 / 20.609 / 0.809 |
| absolute Y / allowance / normalized | 0.918 / 1.000 / 0.918 |
| absolute V / allowance / normalized | 1.723 / 10.000 / 0.172 |
| strict result | PASS |
| model / ID27 lane | EGO_LANE / EGO_LANE |

ID27 was a legitimate strict match at this earlier point.

### B — Arm-A clear

Time: `5180.834015`

| quantity | value |
|---|---:|
| model x / y / v | 88.626 / +1.648 / 26.754 |
| model xStd / yStd / vStd | 5.709 / 0.355 / 1.302 |
| model probability | 0.9943 |
| ID27 dRel / yRel / vRel | 70.685 / +1.415 / +0.094 |
| absolute D / allowance / normalized | 16.421 / 21.776 / 0.754 |
| absolute Y / allowance / normalized | 3.063 / 1.000 / 3.063 |
| absolute V / allowance / normalized | 0.342 / 10.000 / 0.034 |
| strict result | FAIL — lateral only |
| model / ID27 lane | EGO_LANE / LEFT_ADJACENT |

The distance and velocity gates are healthy. ID27 fails because it is laterally on the opposite side of the lane from the model lead.

### C — first strict ID27 after clear

Time: `5183.633792`

| quantity | value |
|---|---:|
| model x / y / v | 86.992 / +0.688 / 26.289 |
| model xStd / yStd / vStd | 3.712 / 0.287 / 1.448 |
| model probability | 0.9972 |
| ID27 dRel / yRel / vRel | 66.744 / +0.293 / -0.844 |
| absolute D / allowance / normalized | 18.728 / 21.368 / 0.876 |
| absolute Y / allowance / normalized | 0.982 / 1.000 / 0.982 |
| absolute V / allowance / normalized | 0.190 / 10.000 / 0.019 |
| strict result | PASS |
| model / ID27 lane | EGO_LANE / EGO_LANE |

## Why strict validity returned

From B to C, lateral mismatch drops from `3.063 m` to `0.982 m`, a `2.082 m` improvement. The components are:

- **ID27 movement toward model:** `radar_model_y` changes from `-1.415` to `-0.293`, contributing about `1.122 m` of convergence.
- **Model movement toward ID27:** model y changes from `+1.648` to `+0.688`, contributing about `0.960 m`.
- **Uncertainty:** yStd decreases from `0.355` to `0.287`; it does not widen. The strict lateral allowance remains the fixed `1.0 m` floor at both moments.
- **Distance:** absolute mismatch worsens from `16.421` to `18.728 m`, and normalized distance error rises from `0.754` to `0.876`. Distance alignment did not create the pass.
- **Velocity:** mismatch improves only from `0.342` to `0.190 m/s`; both are far inside the 10 m/s gate.

The single largest contribution is **ID27_MOVED_TOWARD_MODEL**, with nearly equal supporting movement from the model lead. Strict recovery is a real geometry crossover, not a gate/uncertainty artifact.

## ID27 versus ID38 around the clear

All rows have model lead0 in `EGO_LANE`, lane-change state `off`, and direction `none`. `D/Y/V` are strict-normalized errors.

| t | model y | ID27 model-y / lane | ID27 D/Y/V | ID27 score | ID38 model-y / lane | ID38 D/Y/V | ID38 score |
|---:|---:|---|---|---:|---|---|---:|
| 5180.334109 | +1.461 | -1.356 / LEFT_ADJACENT | .688 / 2.817 / .008 | 2.21e-5 | +2.461 / RIGHT_ADJACENT | 2.065 / 1.001 / .095 | 8.69e-6 |
| 5180.387006 | +1.397 | -1.391 / LEFT_ADJACENT | .741 / 2.788 / .035 | 1.55e-5 | +2.421 / RIGHT_ADJACENT | 2.095 / 1.023 / .116 | 5.64e-6 |
| 5180.434499 | +1.363 | -1.391 / LEFT_ADJACENT | .616 / 2.754 / .005 | 3.07e-5 | +2.421 / RIGHT_ADJACENT | 2.022 / 1.057 / .086 | 5.21e-6 |
| 5180.483424 | +1.394 | -1.389 / LEFT_ADJACENT | .574 / 2.782 / .038 | 1.96e-5 | +2.417 / RIGHT_ADJACENT | 1.997 / 1.023 / .119 | 3.49e-6 |
| 5180.537829 | +1.325 | -1.421 / LEFT_ADJACENT | .452 / 2.746 / .006 | 5.08e-5 | +2.394 / RIGHT_ADJACENT | 1.926 / 1.069 / .087 | 7.58e-6 |
| 5180.585252 | +1.456 | -1.421 / LEFT_ADJACENT | .620 / 2.877 / .009 | 2.68e-5 | +2.394 / RIGHT_ADJACENT | 2.024 / .938 / .091 | 1.12e-5 |
| 5180.635495 | +1.520 | -1.419 / LEFT_ADJACENT | .708 / 2.939 / .010 | 2.07e-5 | +2.394 / RIGHT_ADJACENT | 2.072 / .873 / .073 | 1.75e-5 |
| 5180.683464 | +1.511 | -1.416 / LEFT_ADJACENT | .662 / 2.927 / .013 | 1.90e-5 | +2.397 / RIGHT_ADJACENT | 2.039 / .886 / .099 | 1.17e-5 |
| 5180.735794 | +1.525 | -1.416 / LEFT_ADJACENT | .488 / 2.941 / .047 | 2.43e-5 | +2.400 / RIGHT_ADJACENT | 1.934 / .875 / .133 | 1.38e-5 |
| 5180.785476 | +1.573 | -1.416 / LEFT_ADJACENT | .617 / 2.989 / .050 | 2.36e-5 | +2.400 / RIGHT_ADJACENT | 2.010 / .827 / .135 | 2.55e-5 |
| 5180.834015 | +1.648 | -1.415 / LEFT_ADJACENT | .754 / 3.063 / .034 | 7.81e-6 | +2.400 / RIGHT_ADJACENT | 2.089 / .752 / .122 | 1.64e-5 |
| 5180.883419 | +1.679 | -1.380 / LEFT_ADJACENT | .761 / 3.059 / .055 | 4.38e-6 | +2.383 / RIGHT_ADJACENT | 2.089 / .704 / .147 | 9.41e-6 |
| 5180.934513 | +1.604 | -1.413 / LEFT_ADJACENT | .645 / 3.017 / .042 | 1.14e-5 | +2.386 / RIGHT_ADJACENT | 2.017 / .782 / .135 | 1.29e-5 |
| 5180.983610 | +1.599 | -1.413 / LEFT_ADJACENT | .637 / 3.012 / .010 | 1.84e-5 | +2.386 / RIGHT_ADJACENT | 2.011 / .787 / .104 | 3.13e-5 |
| 5181.034052 | +1.619 | -1.411 / LEFT_ADJACENT | .627 / 3.030 / .003 | 1.69e-5 | +2.383 / RIGHT_ADJACENT | 2.005 / .764 / .100 | 2.23e-5 |
| 5181.084577 | +1.525 | -1.406 / LEFT_ADJACENT | .475 / 2.932 / .037 | 1.41e-5 | +2.383 / RIGHT_ADJACENT | 1.908 / .858 / .137 | 6.34e-6 |
| 5181.135128 | +1.633 | -1.403 / LEFT_ADJACENT | .610 / 3.036 / .099 | 6.18e-6 | +2.383 / RIGHT_ADJACENT | 1.984 / .750 / .203 | 7.17e-6 |
| 5181.183791 | +1.580 | -1.403 / LEFT_ADJACENT | .628 / 2.983 / .045 | 1.11e-5 | +2.383 / RIGHT_ADJACENT | 1.995 / .803 / .149 | 7.36e-6 |
| 5181.235275 | +1.624 | -1.364 / LEFT_ADJACENT | .673 / 2.988 / .011 | 8.25e-6 | +2.380 / RIGHT_ADJACENT | 2.018 / .756 / .117 | 5.72e-6 |
| 5181.283561 | +1.527 | -1.394 / LEFT_ADJACENT | .669 / 2.920 / .008 | 8.48e-6 | +2.356 / RIGHT_ADJACENT | 2.011 / .830 / .117 | 4.89e-6 |

Score alone alternates, but lane-side identity does not: ID27 stays on the opposite/left side, while ID38 stays on the same positive/right side as model lead0. ID38 is therefore the physically more compatible side target during the clear cluster, even though its longitudinal mismatch prevents strict selection.

## Relaxed-only ID27 reattachment

Logged leadOne returns to radar ID27 at `5183.242537`. The nearest model cycle is `5183.233683`:

| quantity | value |
|---|---:|
| model x / y / v | 83.805 / +0.937 / 25.978 |
| ID27 dRel / yRel / vRel | 66.915 / +0.555 / -0.906 |
| ID27 radar_model_y | -0.555 |
| absolute lateral mismatch | 1.492 m |
| strict lateral allowance / result | 1.000 / FAIL |
| relaxed lateral allowance / normalized / result | 1.500 / 0.995 / PASS |
| strict distance / velocity | PASS / PASS |
| ID27 lane | EGO_LANE |

This pass is close to the relaxed boundary, but it is not a stale wrong-side reattachment. By then:

- ID27 has been back in the ego lane continuously since `5182.485113`;
- model y has moved from `+1.648` toward `+0.937`;
- ID27 model-y has moved from `-1.415` toward `-0.555`;
- lateral mismatch has fallen from `3.063` to `1.492 m`;
- strict validity follows about `0.39 s` later at `0.982 m` mismatch.

Classification: **JUSTIFIED_CONTINUITY**.

## Comparison with S33 ID24

The existing S33 control facts show a partially matching pattern:

| property | ID27 | S33 ID24 |
|---|---|---|
| preferred track side during stale period | Opposite side from model lead; left-adjacent while model is ego/right-biased | Opposite side from model lead; ID24 model-y is positive while model y is negative |
| challenger side | ID38 is on model lead's positive/right side | ID44 is on model lead's negative side |
| lateral mismatch around failure | about 3.06 m | about 3.13 m median |
| lateral trend after clear | collapses from 3.06 to 0.98 m | remains around 3 m and chatters on relaxed tolerance |
| uncertainty mechanism | yStd decreases; not causal | relaxed `2*yStd` boundary causes pass/fail chatter |
| strict recovery | real two-sided geometric convergence; ID27 re-enters ego lane | no comparable strict recovery in the analyzed S33 cluster |

Both begin with the same **wrong-side preferred-track** symptom, so the failure pattern is **PARTIAL**. They diverge afterward: S33 ID24 remains stale and chatters, whereas ID27 genuinely migrates back into compatible geometry and is properly reacquired.

## Conclusion

Arm A was correct to clear ID27 at `5180.834`: the preferred association was on the opposite side of the ego lane from both model lead0's lateral side and the better-scoring challenger. The later return of the same numeric Bosch identity does not make the clear premature; it reflects a later physical geometry change, first qualifying for relaxed continuity and then for strict matching.

This closes the last ambiguous Arm-A event. Combined with the prior Arm-B refinement—reset gross-distance aging whenever the preferred track passes strict matching—the evidence supports proceeding to a small Civic-Bosch-only production patch.
