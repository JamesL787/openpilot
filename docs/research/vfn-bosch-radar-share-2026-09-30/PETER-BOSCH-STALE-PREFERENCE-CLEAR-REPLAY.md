# Peter Bosch Stale-Preference Clear Replay

S33 BASELINE RADAR/VISION SWITCHES: **5**

S33 TEST RADAR/VISION SWITCHES: **3**

S33 LARGE Y JUMPS BASELINE/TEST: **5/3**

ID24 STALE REATTACHMENT ELIMINATED: **YES**

STRICT RADAR REACQUISITION STILL WORKS: **YES**

ROUTE136/139 SWITCH REDUCTION: **20.6%**

POSSIBLE LOST-GOOD-RADAR CASES: **10**

DUPLICATE-LEAD FRACTION CHANGED: **42.22% -> 41.46%**

STALE-PREFERENCE CLEAR LOOKS CORRECT: **NO**

READY FOR SMALL CODE PATCH: **NO**

## S33 known chatter

| t | baseline output ID/type | baseline pref | test output ID/type | test pref | miss count | cleared this cycle |
|---:|---|---:|---|---:|---:|:--:|
| 1976.632409 | 24/R | 24 | 24/R | 24 | 0 | False |
| 1976.682656 | 24/R | 24 | 24/R | 24 | 0 | False |
| 1976.730995 | 24/R | 24 | 24/R | 24 | 0 | False |
| 1976.776711 | -1/V | 24 | -1/V | 24 | 1 | False |
| 1976.832728 | 24/R | 24 | 24/R | 24 | 0 | False |
| 1976.882429 | 24/R | 24 | 24/R | 24 | 0 | False |
| 1976.934878 | -1/V | 24 | -1/V | 24 | 1 | False |
| 1976.966721 | -1/V | 24 | -1/V | -1 | 0 | True |
| 1977.032028 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.081471 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.133126 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.180656 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.231586 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.276460 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.317323 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.376082 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.416348 | 24/R | 24 | -1/V | -1 | 0 | False |
| 1977.479655 | 24/R | 24 | -1/V | -1 | 0 | False |
| 1977.518378 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.577205 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.631368 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.677836 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.723439 | -1/V | 24 | -1/V | -1 | 0 | False |
| 1977.781658 | -1/V | 24 | -1/V | -1 | 0 | False |

- The second consecutive relaxed-match failure clears ID24 at route-relative `1976.966721 s`.
- ID24 does not reattach through preferred fallback after the clear.
- ID44 does not become selected because it continues to fail strict matching.

## Route-level comparison

| route | baseline R↔V | test R↔V | baseline large-y | test large-y | baseline ID switches | test ID switches | mean radar run baseline/test | duplicate baseline/test | strict reacquisitions | replay fidelity vs logged |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 00000136 | 154 | 112 | 208 | 166 | 4 | 4 | 11.79/15.40 s | 50.33%/49.47% | 0 | 99.99% |
| 00000139 | 201 | 170 | 425 | 393 | 0 | 0 | 7.87/8.89 s | 36.05%/35.37% | 3 | 100.00% |

## Possible lost-good-radar intervals (>1 s)

| route | segment | start mono | duration | ID | median Δd/Δy/Δv | strict pass | relaxed pass | baseline path | inspection |
|---|---:|---:|---:|---:|---|---:|---:|---|---|
| 00000136 | 5 | 436.226 | 2.834 s | 42 | 13.85 m / 1.39 m / 0.19 m/s | 0% | 100% | PREFERRED | LIKELY_MISMATCHED |
| 00000136 | 5 | 447.259 | 3.258 s | 42 | 9.92 m / 1.21 m / 0.43 m/s | 0% | 100% | PREFERRED | LIKELY_MISMATCHED |
| 00000136 | 21 | 1367.722 | 1.247 s | 3 | 5.44 m / 1.20 m / 0.51 m/s | 0% | 100% | PREFERRED | AMBIGUOUS |
| 00000136 | 21 | 1390.367 | 2.257 s | 53 | 10.49 m / 1.29 m / 0.65 m/s | 0% | 100% | PREFERRED | LIKELY_MISMATCHED |
| 00000139 | 18 | 3759.426 | 1.095 s | 26 | 9.19 m / 1.21 m / 0.19 m/s | 0% | 100% | PREFERRED | LIKELY_MISMATCHED |
| 00000139 | 19 | 3857.867 | 1.003 s | 26 | 9.20 m / 1.25 m / 0.39 m/s | 0% | 100% | PREFERRED | LIKELY_MISMATCHED |
| 00000139 | 20 | 3876.114 | 1.104 s | 26 | 11.85 m / 0.79 m / 1.18 m/s | 0% | 100% | PREFERRED | LIKELY_MISMATCHED |
| 00000139 | 24 | 4170.099 | 1.199 s | 53 | 41.43 m / 0.96 m / 2.21 m/s | 0% | 100% | PREFERRED | LIKELY_MISMATCHED |
| 00000139 | 40 | 5076.901 | 2.599 s | 50 | 7.53 m / 1.24 m / 0.36 m/s | 0% | 100% | PREFERRED | AMBIGUOUS |
| 00000139 | 40 | 5079.792 | 1.796 s | 50 | 5.27 m / 1.25 m / 0.80 m/s | 0% | 100% | PREFERRED | AMBIGUOUS |

## Interpretation

- Baseline replay agrees with logged radar/vision identity on route 136 at `99.99%` and route 139 at `100.00%` of lead slots.
- Strict reacquisition after a preference clear occurred `3` times, so clearing preference does not disable normal strict matching.
- This is an association-state diagnostic only; no parser, threshold, MPC, or production file was changed.
