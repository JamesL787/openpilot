# Peter Bosch False-Clear Scalpel

UNIQUE POSSIBLE FALSE CLEARS: **5**

TRUE STALE: **2**

PREMATURE: **0**

BENIGN: **2**

AMBIGUOUS: **1**

ARM A FALSE-CLEAR DISCRIMINATOR: **No safe score-margin or longer-persistence discriminator emerged: the desired S33 ID24 clear has the smallest challenger advantage of the compared events.**

ARM B FALSE-CLEAR DISCRIMINATOR: **Current strict-match validity separates benign ID46 from stale ID53; duration above 25 m does not.**

S33 ID24 STILL CLEARLY STALE: **YES**

S24 ID53 STILL CLEARLY STALE: **YES**

SMALL RULE REFINEMENT EXISTS: **YES**

REFINEMENT: **For Arm B, count gross-distance cycles only while the preferred track fails strict matching (equivalently, reset the Arm-B streak on any strict pass); do not add an Arm-A score-ratio threshold.**

READY FOR PRODUCTION PATCH AFTER REFINEMENT: **NO**

The Arm-B false clear is cleanly removable, but Arm-A ID27 remains physically ambiguous without video or an independent identity cue. No production file was changed.

## Method

- Target association behavior: revision `42c2a191729afac16399e55496669b9dd29ee1df`.
- Inputs: only the five requested route intervals, with S33 ID24 and S24 ID53 used as already-established controls.
- Each event was inspected over approximately ±3 seconds. Duplicate leadOne/leadTwo clears were collapsed into one physical event.
- Strict and relaxed gates and the association score are those from the target revision. Relaxed normalized errors use the existing distance and lateral allowances; values above `1.0` fail that component.
- “Last strict” and “first strict” refer to the same native `radarTrackId`, not merely a geometrically similar replacement.
- Classification describes whether clearing the **preferred association state at that moment** was justified. It does not imply that the native Bosch identity died; a cleared identity may later reacquire through the unchanged strict path.

## Event classifications

| event | arm | classification | last strict before clear | first strict after clear | key evidence |
|---|---|---|---:|---:|---|
| R136 ID46, `1448.452` | B | **BENIGN_CLEAR** | `1448.451864` | `1448.503665` | Strict and relaxed pass at the clear; radar output remains ID46. |
| R139 ID10, `2868.761` | A | **BENIGN_CLEAR** | `2868.659850` | `2868.860440` | Brief vision interval already exists; ID10 strictly reacquires about 0.10 s later. |
| R139 ID61, `3315.386` | A | **TRUE_STALE_CLEAR** | `3314.538529` | `3317.633568` | Preferred lateral mismatch is 3.94 m/2.63× relaxed allowance; challenger score is 43–64× larger. |
| R139 ID41, `4251.234` | A | **TRUE_STALE_CLEAR** | none in available history | `4252.883630` | Preferred lateral mismatch is 7.92 m/5.28×; no earlier strict acquisition exists. |
| R139 ID27, `5180.834` | A | **AMBIGUOUS** | `5175.833379` | `5183.633792` | Track is smooth but 5.00 s removed from strict validity; challenger only modestly wins and also fails strict distance. |

## R136 ID46 — Arm B benign clear

ID46 is continuously present and measured through the requested window. Across 89 observations its largest consecutive changes are approximately `0.457 m` dRel, `0.115 m` yRel, and `0.125 m/s` vRel.

At the nominal clear:

| quantity | value |
|---|---:|
| time | `1448.451864` |
| ID46 dRel / yRel / vRel | `79.481 / -0.543 / -0.047` |
| model x / y / v / probability | `106.063 / +0.758 / 17.700 / 0.965` |
| model xStd / yStd / vStd | `8.946 / 0.357 / 2.362` |
| absolute distance mismatch | `25.062 m` |
| relaxed-normalized distance | `0.599` |
| absolute lateral mismatch | `0.214 m` |
| relaxed-normalized lateral | `0.143` |
| velocity mismatch | `2.493 m/s` |
| association score | `1.160e-2` |
| strict / relaxed | **PASS / PASS** |

The best other track is ID61, but it fails strict lateral and velocity and scores only `6.27e-8`. Logged leadOne remains radar ID46 continuously across the clear; the next strict pass is only `0.052 s` later.

### Gross-distance excursion

The `>25 m` run lasts seven model cycles from `1448.301990` through `1448.601948`, or **0.300 s**. Mismatch is `25.062..27.991 m` (median `26.469 m`) and does not immediately recover; it ends `1.167 m` higher than it begins. Nevertheless, ID46 passes relaxed matching on every cycle and passes strict matching repeatedly, including at the first cycle and the nominal clear.

This proves persistence alone cannot protect ID46. A strict-valid preferred track should reset Arm B even when model uncertainty permits a large absolute x disagreement.

## R139 ID10 — Arm A benign clear

ID10 has 49 observations in the ±3 s window; 48 are measured. Its one large velocity discontinuity is reflected at the clear by an unmeasured point and a failed velocity gate.

At the nominal clear:

| quantity | value |
|---|---:|
| time | `2868.761348` |
| ID10 dRel / yRel / vRel | `110.783 / -0.216 / -19.522` |
| model x / y / v / probability | `95.743 / -0.030 / 21.286 / 0.894` |
| model xStd / yStd / vStd | `10.691 / 0.342 / 2.119` |
| absolute distance mismatch | `16.560 m` |
| relaxed-normalized distance | `0.439` |
| absolute lateral mismatch | `0.246 m` |
| relaxed-normalized lateral | `0.164` |
| velocity mismatch | `18.884 m/s` |
| association score | `1.395e-5` |
| strict / relaxed | **FAIL / FAIL** (velocity) |

The challenger is ID51. It also fails strict distance and lateral. For the duplicated preferred states, it wins for two consecutive cycles at the respective clears. Ratios are approximately `1.55, 2.38` for one lead slot and `1.72, 2.79` for the other; the advantage continues to grow on the next cycle.

Logged output is already vision from `2868.723448` until ID10 strictly reacquires at `2868.872585`. Clearing preference adds no meaningful radar/vision discontinuity. This is a benign state cleanup, not evidence that an Arm-A margin should be raised.

## R139 ID61 — Arm A true stale association

ID61 remains a smooth native track: 89/89 observations are measured, with maximum consecutive dRel/yRel/vRel changes of `0.800 m`, `0.181 m`, and `0.219 m/s`. Native continuity alone does not prove continued association to the model lead.

At the nominal clear:

| quantity | value |
|---|---:|
| time | `3315.385996` |
| ID61 dRel / yRel / vRel | `32.072 / +1.661 / -11.219` |
| model x / y / v / probability | `40.901 / +2.279 / 0.803 / 0.476` |
| model xStd / yStd / vStd | `2.294 / 0.537 / 0.812` |
| absolute distance mismatch | `7.309 m` |
| relaxed-normalized distance | `0.464` |
| absolute lateral mismatch | `3.940 m` |
| relaxed-normalized lateral | `2.627` |
| velocity mismatch | `1.790 m/s` |
| preferred score | `2.975e-6` |
| strict / relaxed | **FAIL / FAIL** (lateral) |

Challenger ID9 wins for the two trigger cycles with score ratios `43.025` and `64.011` (median `53.518`, maximum through the following cycle `153.663`). ID9 still fails strict lateral, so clearing ID61 does not improperly select ID9.

Logged output had already changed to vision at `3315.148346`. It briefly returns to preferred ID61 at `3317.197616`, about `0.436 s` before ID61 finally passes strict again. Forcing strict reacquisition after a 3.94 m lateral disagreement is the intended stale-state behavior.

## R139 ID41 — Arm A true stale association

ID41 remains physically smooth as a Bosch track, but there is no strict pass before the clear in the available route history. At the nominal clear:

| quantity | value |
|---|---:|
| time | `4251.233888` |
| ID41 dRel / yRel / vRel | `50.122 / -3.260 / +5.476` |
| model x / y / v / probability | `58.567 / -4.657 / 19.930 / 0.975` |
| model xStd / yStd / vStd | `3.712 / 0.559 / 0.958` |
| absolute distance mismatch | `6.926 m` |
| relaxed-normalized distance | `0.304` |
| absolute lateral mismatch | `7.917 m` |
| relaxed-normalized lateral | `5.278` |
| velocity mismatch | `5.613 m/s` |
| preferred score | `3.088e-10` |
| strict / relaxed | **FAIL / FAIL** (lateral) |

Challenger ID31 wins the four immediately preceding cycles with ratios approximately `1.27, 1.29, 1.48, 15.00`; at the nominal clear timestamp its score advantage has already collapsed. This lag makes the exact clear timing imperfect, but the preferred ID41 association itself is not defensible: it has no prior strict provenance and misses lateral geometry by almost eight metres.

ID31 later becomes radar output through ordinary matching; ID41 itself does not become strict until `4252.883630`. The clear is classified true stale even though the native track remains alive.

## R139 ID27 — Arm A ambiguous

ID27 is continuous and measured in all 90 observations. Its maximum consecutive changes are `1.028 m` dRel, `0.070 m` yRel, and `0.328 m/s` vRel. It is therefore not a parser identity reset.

At the nominal clear:

| quantity | value |
|---|---:|
| time | `5180.834015` |
| ID27 dRel / yRel / vRel | `70.685 / +1.415 / +0.094` |
| model x / y / v / probability | `88.626 / +1.648 / 26.754 / 0.994` |
| model xStd / yStd / vStd | `5.709 / 0.355 / 1.302` |
| absolute distance mismatch | `16.421 m` |
| relaxed-normalized distance | `0.471` |
| absolute lateral mismatch | `3.063 m` |
| relaxed-normalized lateral | `2.042` |
| velocity mismatch | `0.342 m/s` |
| preferred score | `7.812e-6` |
| strict / relaxed | **FAIL / FAIL** (lateral) |

Challenger ID38 wins the two leadOne trigger cycles with ratios `1.082` and `2.094` (median `1.588`, maximum `2.094` at clear). It fails strict distance while passing lateral and velocity. The duplicated leadTwo state clears on the adjacent cycle with a similar two-cycle advantage.

ID27's last strict pass is `5.001 s` before clear. Logged output is already vision at `5180.602641`, returns to preferred ID27 at `5183.242537`, and ID27 becomes strict at `5183.633792`. The clear would suppress roughly `0.39 s` of relaxed-only reattachment. Without video or an independent identity reference, the smooth track plus later strict recovery cannot be reconciled conclusively with its large current lateral mismatch. This remains the one ambiguous event.

## Arm A comparison with S33 ID24

The desired S33 control clear is not characterized by a large score margin. Over its two trigger cycles, challenger ID44's score ratio is only `1.076` and `1.116` (median `1.096`). That is smaller than the triggering advantage in every possible-false-clear Arm-A event:

| event | consecutive challenger wins at clear | representative winning ratio(s) | interpretation |
|---|---:|---|---|
| S33 ID24 control | 2 | `1.076, 1.116` | desired stale clear |
| R139 ID10 | 2 per lead state | about `1.55..2.79` | benign; rapid strict reacquisition |
| R139 ID61 | 2 | `43.03, 64.01` | clearly stale association |
| R139 ID41 | 4 immediately preceding | `1.27, 1.29, 1.48, 15.00` | stale; no prior strict provenance |
| R139 ID27 | 2 | `1.082, 2.094` | ambiguous |

Therefore neither a minimum score ratio nor a third consecutive challenger win is a safe small refinement: either can preserve S33's stale ID24 preference. Arm A's evidence is contextual, and ID27 prevents declaring the two-cycle arm fully closed.

## Arm B comparison with stale ID53

At the 25 m threshold:

| case | consecutive cycles over 25 m | duration | mismatch min/median/max | trend | strict / relaxed during trigger |
|---|---:|---:|---|---|---|
| R136 ID46 | 7 | `0.300 s` | `25.062 / 26.469 / 27.991 m` | not recovering | repeated strict passes / relaxed always passes |
| S24 ID53 control | 3 | `0.097 s` | `25.286 / 26.427 / 28.477 m` | already beginning to recover | strict always fails / relaxed always fails |

Persistence gives the opposite of the desired separation: benign ID46 remains over 25 m three times longer than stale ID53 before its clear. ID53 remains clearly stale in the later control window, where disagreement is approximately `38..43 m`, its last strict pass is `16.858 s` old, and no useful challenger exists.

The smallest evidence-backed Arm-B refinement is to reset its gross-distance streak on a strict pass. That preserves ID46 without changing the 25 m threshold and still clears ID53. Requiring an overall relaxed failure would also separate these two examples, but strict validity is the narrower and stronger protection.

## Conclusion

Two of the five flags are benign bookkeeping clears, and two remove preferred associations that are clearly incompatible at the time of clearing. No inspected event is proven premature. Arm B has a clean correction: never age out a preferred association through gross distance while that same association is passing strict matching.

Arm A does not yet have an equally clean scalar refinement. The known desired S33 clear has only a 7.6–11.6% challenger advantage, so score-margin or longer-persistence requirements would preserve the exact stale preference the arm was designed to remove. ID27 remains ambiguous, making a production patch premature despite the otherwise favorable evidence.
