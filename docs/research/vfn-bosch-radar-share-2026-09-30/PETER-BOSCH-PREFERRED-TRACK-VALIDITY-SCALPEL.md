# Peter Bosch Preferred-Track Validity Scalpel

R136/S21 ID3: **GOOD_CONTINUITY**

R139/S40 ID50 WINDOW1: **AMBIGUOUS**

R139/S40 ID50 WINDOW2: **AMBIGUOUS**

R139/S24 ID53: **STALE**

BEST DISCRIMINATOR: **COMBINATION**

SIMPLE TWO-MISS CLEAR SAFE: **NO**

BETTER STATE RULE SUGGESTED: **Clear after repeated relaxed failures only when the preferred track is grossly distance-incompatible or a consistently better-scoring challenger exists; preserve a smooth sole preferred track during bounded model divergence.**

## Method

- Target logic: revision `42c2a191729afac16399e55496669b9dd29ee1df`.
- Inputs: only the cumulative local rlogs containing the four requested intervals.
- Association score is the exact target-revision product of the longitudinal, lateral, and velocity Laplacian terms.
- Preferred-track normalization uses the existing relaxed allowances: distance `max(0.40*|model_x-1.52|, 8 m)`, lateral `max(2*yStd, 1.5 m)`, and velocity `13 m/s` (including the production ground-speed escape condition when judging pass/fail).
- “Last strict” uses the unchanged strict production gate. Searches stopped at the most recent passing cycle; `NONE` means the current numeric identity had no earlier strict pass in the available route history.
- Every model cycle in each requested interval was evaluated. The tables show seven evenly spaced exact snapshots; the all-cycle extrema and medians below cover every cycle.
- `M` means the live-track point was measured. `D/Y/V` columns are absolute mismatch divided by relaxed allowance for the preferred track and strict-normalized mismatch for the best other track.

## Classification summary

| interval | last strict before start | preferred relaxed D/Y/V median | score median (range) | continuity | best other | result |
|---|---:|---|---|---|---|---|
| R136/S21 ID3 | `1363.650660`, 4.071 s earlier | 0.397 / 0.801 / 0.042 | 6.02e-5 (8.24e-6..2.91e-3) | 83 observations; smooth; becomes strict again at 1368.999836 | none | GOOD_CONTINUITY |
| R139/S40 ID50 W1 | no previous strict pass | 0.405 / 0.880 / 0.030 | 8.98e-6 (1.11e-6..6.20e-5) | 47 observations; smooth | ID43, always strict-failing and much lower score | AMBIGUOUS |
| R139/S40 ID50 W2 | no previous strict pass | 0.327 / 0.835 / 0.062 | 1.65e-5 (1.11e-6..1.17e-4) | 36 observations; smooth; becomes strict at 5081.633270 | ID43, always strict-failing and much lower score | AMBIGUOUS |
| R139/S24 ID53 | `4153.240537`, 16.858 s earlier | 0.922 / 0.643 / 0.192 | 1.92e-4 (2.49e-8..1.07e-3) | same ID persists, but history contains a 22.64 m/s velocity discontinuity | none | STALE |

## R136/S21 ID3 — good continuity

Model lead ranges over all evaluated cycles: `x=32.31..37.72 m`, `y=-0.716..-0.205 m`, `v=10.78..11.82 m/s`, probability `0.9992..1.0`, `xStd=1.17..2.37`, `yStd=0.20..0.273`, `vStd=0.458..0.742`.

ID3 is the only live radar track. From its last strict pass through the interval it has 83 true live-track observations, maximum gap 0.081 s, median/max steps of `0.057/0.228 m` in dRel, `0.014/0.034 m` in yRel, and `0.047/0.500 m/s` in vRel. The mismatch shrinks rather than diverges, and strict matching resumes at `1368.999836`.

| t | model p; x/y/v; xStd/yStd/vStd | ID3 d/y/v; cnt/state | relaxed abs D/allow; abs Y/allow; abs V/allow | score | best other |
|---:|---|---|---|---:|---|
| 1367.451282 | 1.000; 36.76/-0.71/+10.91; 1.86/0.23/0.63 | 28.87/-0.86/-2.42; 90/M | 6.37/14.10; 1.57/1.50; 0.68/13.00 | 1.20e-5 | none |
| 1367.751340 | 1.000; 36.13/-0.54/+11.37; 1.89/0.25/0.64 | 28.64/-0.80/-2.31; 94/M | 5.96/13.84; 1.33/1.50; 1.10/13.00 | 4.01e-5 | none |
| 1368.050919 | 1.000; 36.80/-0.51/+11.03; 1.75/0.25/0.63 | 28.36/-0.73/-2.06; 99/M | 6.93/14.11; 1.24/1.50; 0.61/13.00 | 5.26e-5 | none |
| 1368.351904 | 1.000; 35.00/-0.49/+11.25; 1.33/0.23/0.53 | 28.19/-0.73/-1.77; 103/M | 5.29/13.39; 1.22/1.50; 0.70/13.00 | 2.45e-5 | none |
| 1368.651152 | 1.000; 33.91/-0.49/+11.01; 1.22/0.21/0.51 | 28.30/-0.70/-0.98; 108/M | 4.08/12.95; 1.19/1.50; 0.12/13.00 | 9.17e-5 | none |
| 1368.951369 | 1.000; 33.80/-0.40/+11.49; 1.62/0.21/0.56 | 28.36/-0.61/-0.66; 112/M | 3.93/12.91; 1.01/1.50; 0.14/13.00 | 6.17e-4 | none |
| 1369.251123 | 1.000; 32.31/-0.21/+11.20; 1.22/0.20/0.50 | 28.24/-0.52/-0.83; 117/M | 2.55/12.32; 0.73/1.50; 0.06/13.00 | 2.91e-3 | none |

This is the clearest counterexample to unconditional two-miss clearing: the track is physically continuous, has no competing radar object, its score improves by over two orders of magnitude, and it naturally regains strict validity.

## R139/S40 ID50 window 1 — ambiguous, continuity favors retention

Model lead ranges: `x=45.31..50.57 m`, `y=-0.934..-0.548 m`, `v=22.26..23.88 m/s`, probability `0.9999..1.0`, `xStd=1.14..1.59`, `yStd=0.219..0.288`, `vStd=0.427..0.587`.

ID50 has no earlier strict pass in the available history, so it cannot satisfy the strong “was once a clean strict match” criterion. It is nevertheless extremely smooth: 47 observations, 0.079 s maximum gap, median/max dRel steps `0.057/0.171 m`, yRel `0.017/0.056 m`, and vRel `0.016/0.125 m/s`. ID43 is the best other track on every cycle, but fails strict matching 64/64 times; its median score is only `4.07e-10` versus ID50's `8.98e-6`.

| t | model p; x/y/v; xStd/yStd/vStd | ID50 d/y/v; cnt/state | relaxed abs D/allow; abs Y/allow; abs V/allow | score | best other: ID d/y/v; strict-normalized D/Y/V; score; strict |
|---:|---|---|---|---:|---|
| 5076.632586 | 1.000; 50.37/-0.88/+23.57; 1.59/0.29/0.58 | 39.38/-0.73/-0.66; 27/M | 9.47/19.54; 1.61/1.50; 0.26/13.00 | 6.20e-6 | 43 71.43/+1.19/-0.95; 1.85/0.31/0.06; 8.56e-8; FAIL |
| 5077.131776 | 1.000; 49.52/-0.69/+23.45; 1.48/0.28/0.51 | 39.27/-0.63/-0.77; 35/M | 8.73/19.20; 1.32/1.50; 0.12/13.00 | 1.82e-5 | 43 71.37/+1.36/-1.00; 1.95/0.67/0.03; 5.94e-9; FAIL |
| 5077.683257 | 1.000; 47.95/-0.56/+23.44; 1.27/0.25/0.47 | 38.93/-0.55/-0.94; 43/M | 7.50/18.57; 1.11/1.50; 0.15/13.00 | 2.21e-5 | 43 70.74/+1.52/-1.19; 2.10/0.96/0.04; 4.25e-11; FAIL |
| 5078.231155 | 1.000; 47.24/-0.57/+23.29; 1.30/0.23/0.50 | 38.98/-0.55/-0.86; 51/M | 6.74/18.29; 1.12/1.50; 0.16/13.00 | 3.40e-5 | 43 69.66/+1.46/-1.53; 2.09/0.89/0.05; 7.44e-11; FAIL |
| 5078.733614 | 1.000; 47.73/-0.76/+23.14; 1.29/0.24/0.51 | 38.64/-0.58/-0.94; 59/M | 7.57/18.48; 1.34/1.50; 0.24/13.00 | 7.03e-6 | 43 68.00/+1.39/-1.91; 1.89/0.64/0.07; 8.48e-10; FAIL |
| 5079.233268 | 1.000; 46.99/-0.77/+23.07; 1.21/0.24/0.50 | 38.64/-0.66/-0.75; 66/M | 6.83/18.19; 1.43/1.50; 0.43/13.00 | 4.26e-6 | 43 67.71/+1.29/-1.78; 1.96/0.52/0.06; 3.76e-10; FAIL |
| 5079.783206 | 1.000; 45.67/-0.82/+22.64; 1.14/0.22/0.49 | 38.53/-0.64/-0.62; 74/M | 5.62/17.66; 1.46/1.50; 0.99/13.00 | 1.22e-6 | 43 67.77/+1.36/-1.56; 2.14/0.54/0.01; 7.70e-11; FAIL |

## R139/S40 ID50 window 2 — ambiguous, then strict-valid

Model lead ranges: `x=43.77..46.52 m`, `y=-0.848..-0.576 m`, `v=21.70..23.16 m/s`, probability `1.0`, `xStd=1.09..1.45`, `yStd=0.213..0.254`, `vStd=0.461..0.780`.

There is still no strict pass before this window, but ID50 remains smooth (36 observations; maximum gap 0.081 s; median/max dRel step `0.057/0.171 m`, yRel `0.018/0.056 m`, vRel `0.016/0.078 m/s`) and becomes strict-valid at `5081.633270`. ID43 again fails strict matching on all 48 evaluated cycles and has a median score roughly 100,000 times smaller.

| t | model p; x/y/v; xStd/yStd/vStd | ID50 d/y/v; cnt/state | relaxed abs D/allow; abs Y/allow; abs V/allow | score | best other: ID d/y/v; strict-normalized D/Y/V; score; strict |
|---:|---|---|---|---:|---|
| 5079.531438 | 1.000; 45.41/-0.85/+22.78; 1.26/0.25/0.53 | 38.41/-0.68/-0.77; 71/M | 5.48/17.56; 1.52/1.50; 0.71/13.00 | 8.51e-6 | 43 67.77/+1.32/-1.64; 2.18/0.48/0.02; 6.92e-10; FAIL |
| 5079.931773 | 1.000; 45.09/-0.79/+22.99; 1.19/0.22/0.50 | 38.58/-0.60/-0.59; 76/M | 4.99/17.43; 1.40/1.50; 0.65/13.00 | 7.89e-6 | 43 67.71/+1.49/-1.53; 2.22/0.69/0.03; 3.72e-11; FAIL |
| 5080.331058 | 1.000; 43.85/-0.83/+22.57; 1.22/0.22/0.59 | 38.30/-0.56/-0.59; 82/M | 4.04/16.93; 1.39/1.50; 0.97/13.00 | 1.15e-5 | 43 67.54/+1.58/-1.41; 2.38/0.76/0.02; 2.31e-11; FAIL |
| 5080.732353 | 1.000; 44.08/-0.74/+22.39; 1.36/0.22/0.58 | 38.01/-0.48/-0.66; 88/M | 4.55/17.02; 1.23/1.50; 1.01/13.00 | 2.62e-5 | 43 66.74/+1.76/-1.48; 2.27/1.02/0.02; 1.58e-10; FAIL |
| 5081.083368 | 1.000; 45.21/-0.68/+22.85; 1.32/0.24/0.65 | 37.96/-0.44/-0.56; 94/M | 5.74/17.48; 1.12/1.50; 0.64/13.00 | 4.39e-5 | 43 65.32/+1.91/-1.89; 1.98/1.24/0.07; 1.52e-10; FAIL |
| 5081.481130 | 1.000; 46.52/-0.66/+22.54; 1.37/0.25/0.67 | 37.56/-0.37/-0.72; 100/M | 7.44/18.00; 1.03/1.50; 0.74/13.00 | 2.51e-5 | 43 63.89/+2.03/-2.19; 1.68/1.37/0.07; 1.56e-9; FAIL |
| 5081.883107 | 1.000; 45.01/-0.59/+22.54; 1.27/0.23/0.63 | 36.93/-0.34/-0.92; 106/M | 6.57/17.40; 0.94/1.50; 0.49/13.00 | 4.68e-5 | 43 61.55/+2.10/-2.70; 1.66/1.51/0.13; 1.25e-10; FAIL |

The two ID50 windows cannot prove identity correctness because the track entered preference without any observed strict match. They do show why two misses alone are insufficient evidence of staleness: the identity is continuous, the only challenger is dramatically worse, and ID50 itself later becomes strict-valid.

## R139/S24 ID53 — stale association control

Model lead ranges: `x=107.53..117.53 m`, `y=-1.613..-0.399 m`, `v=18.86..21.22 m/s`, probability `0.255..0.906`, `xStd=3.95..9.43`, `yStd=0.345..0.650`, `vStd=1.43..1.92`.

The last strict pass was 16.858 s before this interval. ID53 remains numerically present, but the model/radar distance disagreement is `37.7..43.2 m`; normalized relaxed distance mismatch stays near the limit with median `0.922`, and the longer history contains a 22.64 m/s vRel discontinuity. There is no alternative radar track, but absence of a challenger does not rescue such gross geometry.

| t | model p; x/y/v; xStd/yStd/vStd | ID53 d/y/v; cnt/state | relaxed abs D/allow; abs Y/allow; abs V/allow | score | best other |
|---:|---|---|---|---:|---|
| 4169.837523 | 0.906; 114.69/-0.43/+21.22; 3.95/0.35/1.42 | 73.08/+2.14/-4.41; 253/M | 40.09/45.27; 1.71/1.50; 3.44/13.00 | 2.49e-8 | none |
| 4170.138281 | 0.594; 116.87/-0.73/+19.93; 5.34/0.43/1.69 | 72.17/+2.08/-4.45; 257/M | 43.18/46.14; 1.35/1.50; 2.21/13.00 | 3.71e-6 | none |
| 4170.437793 | 0.586; 114.65/-1.20/+20.33; 5.51/0.47/1.63 | 71.54/+2.06/-4.31; 261/M | 41.59/45.25; 0.86/1.50; 2.49/13.00 | 1.80e-5 | none |
| 4170.737838 | 0.458; 112.42/-1.17/+19.71; 7.08/0.51/1.81 | 70.51/+2.10/-4.33; 266/M | 40.39/44.36; 0.93/1.50; 1.89/13.00 | 1.92e-4 | none |
| 4170.989710 | 0.322; 114.02/-1.33/+19.92; 7.50/0.60/1.61 | 69.43/+2.17/-4.41; 270/M | 43.08/45.00; 0.84/1.50; 2.22/13.00 | 1.99e-4 | none |
| 4171.288022 | 0.364; 107.53/-1.61/+20.09; 8.72/0.63/1.67 | 68.34/+2.27/-4.50; 274/M | 37.66/42.40; 0.66/1.50; 2.49/13.00 | 1.07e-3 | none |
| 4171.588717 | 0.323; 107.68/-1.21/+19.94; 9.30/0.64/1.67 | 66.63/+2.34/-4.75; 278/M | 39.53/42.47; 1.13/1.50; 2.64/13.00 | 5.03e-4 | none |

## Comparison with S33 ID24

The existing S33 scalpel—not a new broad replay—provides the reference:

| case | time since last strict | relaxed distance behavior | relaxed lateral behavior | score/challenger trend | native-track continuity |
|---|---|---|---|---|---|
| S33 ID24 | at least 3.10 s from the last documented strict pass at 1973.531733 | still within relaxed distance allowance | repeatedly straddles/fails the relaxed lateral boundary | ID44 has the maximum score every cycle; ID24 survives only as preferred fallback | smooth and continuously alive |
| R136 ID3 | 4.071 s | 0.205..0.546 normalized, improving | 0.486..1.048, improving | no challenger; score rises from e-5 to e-3 | exceptionally smooth; regains strict |
| R139 ID50 W1 | no prior strict | 0.294..0.496 | 0.720..1.097 | ID43 score is orders of magnitude worse and always strict-fails | exceptionally smooth |
| R139 ID50 W2 | no prior strict | 0.224..0.413 | 0.613..1.016 | ID43 remains orders of magnitude worse and always strict-fails | exceptionally smooth; becomes strict |
| R139 ID53 | 16.858 s | 0.870..0.957, representing about 38–43 m absolute error | 0.438..1.139 | no challenger, but geometry is grossly incompatible | same ID persists, with a major historical vRel discontinuity |

Time since strict by itself cannot distinguish S33 ID24 from good ID3: ID3's age is actually longer. Track continuity also cannot distinguish them because both are smooth. The useful separation is contextual: ID3/ID50 are sole clearly best candidates whose geometry trends toward strict validity, whereas S33 has a persistent better-scoring challenger and ID53 has gross absolute longitudinal disagreement.

## Conclusion

The two-consecutive-miss diagnostic correctly removes S33 ID24, but it also clears at least one demonstrably recoverable radar association and two smooth, potentially legitimate associations. It is therefore not safe as a production rule by itself. A state rule needs both persistence and evidence that the preferred identity has become implausible: gross normalized/absolute distance disagreement, or a persistent materially better-scoring competing track. No production code was changed.
