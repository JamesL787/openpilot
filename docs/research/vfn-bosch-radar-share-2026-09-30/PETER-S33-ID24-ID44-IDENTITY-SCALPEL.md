# Peter S33 ID24/ID44 Identity Scalpel

ID24 FIRST ACQUIRED BY: **UNKNOWN (ALREADY SELECTED AT S33 START)**

ID24 MEDIAN LATERAL MISMATCH: **3.129 m**

ID44 MEDIAN LATERAL MISMATCH: **1.642 m**

ID44 PRIMARY STRICT FAILURE: **DISTANCE**

TRACK24 LIKELY TRUE PHYSICAL LEAD: **NO**

TRACK44 LIKELY TRUE PHYSICAL LEAD: **NO**

BOSCH YREL SIGN CORRECT: **YES**

ROOT PROBLEM: **WRONG PREFERRED TRACK**

NEXT SCALPEL: **Replay only this cluster with preferred ID24 cleared once its relaxed lateral gate fails for two consecutive cycles, and verify that leadOne remains vision rather than latching either side target.**

## ID24 preference acquisition

- S33 begins at its first visible radarState cycle, route-relative `1973.073132 s`, with leadOne already set to ID24.
- No preceding radarState/liveTracks cycle exists in segment 33, so `prev_lead_track_id[0]` at the moment it originally became 24 is not observable under this task’s segment-only constraint.
- The first visible ID24 geometry itself passes all strict gates (`PASS/PASS/PASS`), but that does **not** prove whether the hidden acquisition was strict matching, preferred fallback, or low-speed override.
- The first 0.5 s of available rows below use exact strict gates and Laplacian score from the target revision.

| t | model lead0 p/x/y/v/xσ/yσ/vσ | ID24 d/y/v; D/V/Y; score | ID44 d/y/v; D/V/Y; score | max ID | result | reason |
|---:|---|---|---|---:|---|---|
| 1973.073132 | 0.490/24.171/1.170/-0.025/3.211/1.047/0.466 | 20.476/-0.460/-5.344; PASS/PASS/PASS; 0.03381 | UNAVAILABLE AT SEGMENT BOUNDARY | UNKNOWN | 24/R | ACQUISITION PREDATES AVAILABLE INPUT |
| 1973.127558 | 0.415/23.757/1.130/0.022/3.601/1.090/0.546 | 20.134/-0.501/-5.250; PASS/PASS/PASS; 0.05405 | MISSING | 24 | 24/R | — |
| 1973.182041 | 0.425/23.674/0.791/-0.047/3.253/1.005/0.517 | 19.848/-0.582/-5.422; PASS/PASS/PASS; 0.0451 | MISSING | 24 | 24/R | — |
| 1973.228853 | 0.525/22.781/0.644/0.103/3.297/0.952/0.562 | 19.448/-0.617/-5.641; PASS/PASS/PASS; 0.03586 | MISSING | 24 | 24/R | — |
| 1973.275255 | 0.505/23.146/0.711/0.234/3.513/0.964/0.620 | 19.448/-0.617/-5.641; PASS/PASS/PASS; 0.02923 | MISSING | 24 | 24/R | — |
| 1973.330660 | 0.479/23.002/0.775/0.196/3.709/1.027/0.587 | 19.163/-0.683/-5.062; PASS/PASS/PASS; 0.06418 | MISSING | 24 | 24/R | — |
| 1973.385160 | 0.479/22.179/0.522/0.001/3.705/1.105/0.450 | 18.877/-0.738/-5.188; PASS/PASS/PASS; 0.03552 | MISSING | 24 | 24/R | — |
| 1973.423957 | 0.480/22.078/0.446/0.116/3.986/1.197/0.467 | 18.877/-0.738/-5.188; PASS/PASS/PASS; 0.02839 | MISSING | 24 | 24/R | — |
| 1973.466650 | 0.475/22.192/0.457/0.275/4.438/1.338/0.521 | 18.591/-0.781/-5.156; PASS/PASS/PASS; 0.02536 | MISSING | 24 | 24/R | — |
| 1973.531733 | 0.436/21.840/0.532/0.199/3.980/1.296/0.452 | 18.306/-0.841/-4.547; PASS/PASS/PASS; 0.06055 | MISSING | 24 | 24/R | — |

## ID24 versus ID44 in the oscillation window

| t | ID24 d/y/v | ID44 d/y/v | model lead0 x/y/v | ID44 |Δd|/allow | D | |Δv|/allow | V | |Δy|/allow | Y |
|---:|---|---|---|---:|:--:|---:|:--:|---:|:--:|
| 1976.632409 | d=11.794, y=-2.375, v=-1.453 | d=7.567, y=+1.920, v=-0.859 | 17.833/-0.448/+0.285 | 8.746/5.000 | FAIL | 0.070/10.0 | PASS | 1.472/1.472 | PASS |
| 1976.682656 | d=11.737, y=-2.429, v=-1.484 | d=7.567, y=+1.924, v=-1.031 | 18.159/-0.405/+0.354 | 9.072/5.000 | FAIL | 0.332/10.0 | PASS | 1.519/1.437 | FAIL |
| 1976.730995 | d=11.623, y=-2.471, v=-1.406 | d=7.510, y=+1.914, v=-1.141 | 18.018/-0.550/+0.279 | 8.988/5.000 | FAIL | 0.395/10.0 | PASS | 1.364/1.516 | PASS |
| 1976.776711 | d=11.623, y=-2.471, v=-1.406 | d=7.510, y=+1.914, v=-1.141 | 17.864/-0.505/+0.312 | 8.834/5.000 | FAIL | 0.457/10.0 | PASS | 1.408/1.487 | PASS |
| 1976.832728 | d=11.566, y=-2.524, v=-1.422 | d=8.024, y=+2.020, v=-0.359 | 18.044/-0.394/+0.312 | 8.500/5.000 | FAIL | 0.295/10.0 | PASS | 1.626/1.503 | FAIL |
| 1976.882429 | d=11.508, y=-2.570, v=-1.250 | d=7.967, y=+2.014, v=-1.016 | 18.590/-0.322/+0.368 | 9.103/5.000 | FAIL | 0.428/10.0 | PASS | 1.691/1.513 | FAIL |
| 1976.934878 | d=11.451, y=-2.634, v=-1.281 | d=7.910, y=+2.003, v=-1.078 | 17.746/-0.303/+0.302 | 8.317/5.000 | FAIL | 0.447/10.0 | PASS | 1.700/1.460 | FAIL |
| 1976.966721 | d=11.451, y=-2.634, v=-1.281 | d=7.910, y=+2.003, v=-1.078 | 18.984/-0.384/+0.325 | 9.554/5.000 | FAIL | 0.498/10.0 | PASS | 1.619/1.345 | FAIL |
| 1977.032028 | d=11.394, y=-2.674, v=-1.234 | d=7.853, y=+2.030, v=-1.031 | 17.908/-0.449/+0.253 | 8.535/5.000 | FAIL | 0.450/10.0 | PASS | 1.581/1.270 | FAIL |
| 1977.081471 | d=11.337, y=-2.713, v=-1.203 | d=7.796, y=+2.027, v=-0.922 | 18.306/-0.605/+0.237 | 8.990/5.000 | FAIL | 0.363/10.0 | PASS | 1.422/1.243 | FAIL |
| 1977.133126 | d=11.280, y=-2.752, v=-1.172 | d=7.796, y=+2.027, v=-0.844 | 18.017/-0.509/+0.170 | 8.701/5.000 | FAIL | 0.262/10.0 | PASS | 1.518/1.310 | FAIL |
| 1977.180656 | d=11.280, y=-2.752, v=-1.172 | d=7.796, y=+2.027, v=-0.844 | 18.766/-0.384/+0.201 | 9.450/5.000 | FAIL | 0.334/10.0 | PASS | 1.643/1.399 | FAIL |
| 1977.231586 | d=11.223, y=-2.802, v=-1.094 | d=7.739, y=+2.012, v=-0.828 | 19.111/-0.301/+0.173 | 9.853/5.000 | FAIL | 0.349/10.0 | PASS | 1.711/1.500 | FAIL |
| 1977.276460 | d=11.166, y=-2.828, v=-0.984 | d=7.681, y=+2.005, v=-0.781 | 19.962/-0.422/+0.170 | 10.761/5.000 | FAIL | 0.332/10.0 | PASS | 1.583/1.482 | FAIL |
| 1977.317323 | d=11.166, y=-2.828, v=-0.984 | d=7.681, y=+2.005, v=-0.781 | 20.449/-0.295/+0.218 | 11.248/5.000 | FAIL | 0.409/10.0 | PASS | 1.710/1.516 | FAIL |
| 1977.376082 | d=11.109, y=-2.871, v=-0.922 | d=7.624, y=+1.998, v=-0.719 | 19.787/-0.272/+0.222 | 10.643/5.000 | FAIL | 0.396/10.0 | PASS | 1.726/1.564 | FAIL |
| 1977.416348 | d=11.109, y=-2.918, v=-0.828 | d=7.624, y=+1.998, v=-0.625 | 19.624/-0.132/+0.145 | 10.480/5.000 | FAIL | 0.266/10.0 | PASS | 1.867/1.635 | FAIL |
| 1977.479655 | d=11.052, y=-2.943, v=-0.781 | d=7.624, y=+1.998, v=-0.562 | 19.489/-0.199/+0.142 | 10.345/5.000 | FAIL | 0.269/10.0 | PASS | 1.799/1.597 | FAIL |
| 1977.518378 | d=11.052, y=-2.943, v=-0.781 | d=7.624, y=+1.998, v=-0.562 | 20.379/-0.258/+0.232 | 11.235/5.000 | FAIL | 0.390/10.0 | PASS | 1.740/1.516 | FAIL |
| 1977.577205 | d=10.994, y=-2.980, v=-0.688 | d=7.567, y=+1.987, v=-0.531 | 21.043/-0.291/+0.313 | 11.956/5.000 | FAIL | 0.476/10.0 | PASS | 1.696/1.452 | FAIL |
| 1977.631368 | d=10.937, y=-3.016, v=-0.641 | d=7.567, y=+1.991, v=-0.469 | 21.324/-0.279/+0.305 | 12.237/5.000 | FAIL | 0.443/10.0 | PASS | 1.712/1.539 | FAIL |
| 1977.677836 | d=10.880, y=-3.057, v=-0.641 | d=7.567, y=+1.991, v=-0.391 | 19.559/-0.288/+0.277 | 10.472/5.000 | FAIL | 0.372/10.0 | PASS | 1.704/1.527 | FAIL |
| 1977.723439 | d=10.880, y=-3.057, v=-0.641 | d=7.567, y=+1.991, v=-0.391 | 17.266/-0.387/+0.237 | 8.179/5.000 | FAIL | 0.339/10.0 | PASS | 1.604/1.428 | FAIL |
| 1977.781658 | d=10.880, y=-3.103, v=-0.672 | d=7.567, y=+1.995, v=-0.359 | 19.108/-0.354/+0.322 | 10.020/5.000 | FAIL | 0.372/10.0 | PASS | 1.641/1.387 | FAIL |

## Geometry summary

| track | median lateral mismatch | median longitudinal mismatch | median velocity mismatch | interpretation |
|---:|---:|---:|---:|---|
| 24 | 3.129 m | 5.989 m | 0.638 m/s | Adjacent/side geometry in this window; stale preference, not a clean same-lane match. |
| 44 | 1.642 m | 9.502 m | 0.372 m/s | Closer in combined score and lateral geometry, but still fails strict distance most often. |

- ID44 strict failure counts over `24` cycles: `{'DISTANCE': 24, 'VELOCITY': 0, 'LATERAL': 21}`.
- **Which track is geometrically closer to model lead0: 44**, by the exact combined association score; neither is a clean physical match.

## Bosch yRel sign check

- Target RadarInterface computes `yRel = -dRel * tan(azimuth_rad)`; target radard compares `abs(track.yRel + lead.y[0])`, i.e. expects `track.yRel ≈ -model_y`.
- Centered strict-match examples from this same segment:

| t | ID | radar yRel | model y | |radar+model| | |radar-model| |
|---:|---:|---:|---:|---:|---:|
| 1973.182041 | 24 | -0.582 | +0.791 | 0.209 | 1.373 |
| 1973.228853 | 24 | -0.617 | +0.644 | 0.026 | 1.261 |
| 1973.275255 | 24 | -0.617 | +0.711 | 0.094 | 1.329 |
| 1973.330660 | 24 | -0.683 | +0.775 | 0.091 | 1.458 |
| 1973.385160 | 24 | -0.738 | +0.522 | 0.216 | 1.260 |
| 1973.423957 | 24 | -0.738 | +0.446 | 0.291 | 1.184 |
| 1973.466650 | 24 | -0.781 | +0.457 | 0.325 | 1.238 |
| 1973.531733 | 24 | -0.841 | +0.532 | 0.308 | 1.373 |

- Median expected-sign mismatch: `0.213 m`; median opposite-sign mismatch: `1.295 m`.
- **Bosch yRel sign into radard is correct.** The ID24 disagreement is not explained by a global sign inversion.
