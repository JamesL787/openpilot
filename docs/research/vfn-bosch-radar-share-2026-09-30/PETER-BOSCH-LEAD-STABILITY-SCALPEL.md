# Peter Bosch Lead-Stability Scalpel

LARGE YREL DISPLAY JUMPS: **1167**

LEADONE ID SWITCHES/MIN: **0.078**

SAME-TRACK LEFT/RIGHT FLIPS: **0**

OLD TRACK STILL ALIVE DURING SWITCH: **4**

LEADONE/LEADTWO DUPLICATE FRACTION: **42.19%**

LEAD SLOT SWAPS: **0**

RADAR<->VISION SWITCHES: **357**

PRIMARY CAUSE OF DISPLAY JUMP: **RADAR-VISION SWITCHING**

TRACKING ACTUALLY STABLE: **PARTIAL**

## Scope

- Repository revision under diagnosis: `42c2a191729afac16399e55496669b9dd29ee1df`.
- Route 136 segments read: `34`; route 139 segments read: `44`.
- `radarState` cycles: `91485`; continuously valid leadOne time: `51.55 min`.

## Strongest 15 classified lateral moves

| route/segment | route time (s) | lead slot | before | after | Δy (m) | classification |
|---|---:|---|---|---|---:|---|
| 00000136/S6 | 396.089127 | leadTwo | ID -1 / y=+2.548 / d=47.686 / v=-0.745 | ID 42 / y=-1.991 / d=37.041 / v=-1.797 | -4.539 | VISION_TO_RADAR |
| 00000136/S6 | 397.140194 | leadTwo | ID 42 / y=-2.917 / d=35.270 / v=-2.516 | ID -1 / y=+1.336 / d=48.334 / v=-1.903 | +4.253 | RADAR_TO_VISION |
| 00000136/S31 | 1879.575267 | leadTwo | ID 5 / y=-0.398 / d=58.176 / v=-9.938 | ID -1 / y=-4.501 / d=39.181 / v=-5.016 | -4.103 | RADAR_TO_VISION |
| 00000136/S6 | 396.551952 | leadTwo | ID -1 / y=+1.590 / d=49.033 / v=-1.148 | ID 42 / y=-2.161 / d=36.241 / v=-2.047 | -3.752 | VISION_TO_RADAR |
| 00000136/S6 | 396.399813 | leadTwo | ID 42 / y=-2.017 / d=36.527 / v=-1.953 | ID -1 / y=+1.315 / d=44.304 / v=-1.066 | +3.332 | RADAR_TO_VISION |
| 00000139/S33 | 1977.577205 | leadTwo | ID 24 / y=-2.943 / d=11.052 / v=-0.781 | ID -1 / y=+0.296 / d=19.428 / v=-0.150 | +3.239 | RADAR_TO_VISION |
| 00000139/S33 | 1977.518378 | leadOne | ID 24 / y=-2.943 / d=11.052 / v=-0.781 | ID -1 / y=+0.258 / d=18.859 / v=-0.252 | +3.201 | RADAR_TO_VISION |
| 00000139/S33 | 1977.416348 | leadOne | ID -1 / y=+0.272 / d=18.267 / v=-0.467 | ID 24 / y=-2.918 / d=11.109 / v=-0.828 | -3.190 | VISION_TO_RADAR |
| 00000139/S33 | 1977.376082 | leadTwo | ID -1 / y=+0.297 / d=18.918 / v=-0.554 | ID 24 / y=-2.871 / d=11.109 / v=-0.922 | -3.168 | VISION_TO_RADAR |
| 00000139/S33 | 1976.832729 | leadOne | ID -1 / y=+0.505 / d=16.344 / v=-0.790 | ID 24 / y=-2.524 / d=11.566 / v=-1.422 | -3.029 | VISION_TO_RADAR |
| 00000139/S33 | 1976.966722 | leadTwo | ID 24 / y=-2.634 / d=11.451 / v=-1.281 | ID -1 / y=+0.351 / d=17.490 / v=-0.709 | +2.985 | RADAR_TO_VISION |
| 00000139/S33 | 1976.776711 | leadOne | ID 24 / y=-2.471 / d=11.623 / v=-1.406 | ID -1 / y=+0.505 / d=16.344 / v=-0.790 | +2.976 | RADAR_TO_VISION |
| 00000136/S31 | 1879.471864 | leadTwo | ID -1 / y=-3.328 / d=39.338 / v=-4.265 | ID 5 / y=-0.398 / d=58.176 / v=-9.938 | +2.930 | VISION_TO_RADAR |
| 00000136/S31 | 1879.418017 | leadTwo | ID 5 / y=-0.405 / d=59.318 / v=-10.266 | ID -1 / y=-3.328 / d=39.338 / v=-4.265 | -2.923 | RADAR_TO_VISION |
| 00000139/S33 | 1976.934878 | leadOne | ID 24 / y=-2.570 / d=11.508 / v=-1.250 | ID -1 / y=+0.303 / d=16.226 / v=-0.732 | +2.873 | RADAR_TO_VISION |

## Transition accounting

- Large-jump classes: `{'UNKNOWN': 558, 'VISION_TO_RADAR': 297, 'RADAR_TO_VISION': 302, 'TRACK_SWITCH': 8, 'SAME_TRACK_Y_JUMP': 2}`.
- leadOne radar-ID changes: `4` (`0.078/min` of continuously valid leadOne time).
- radar→vision: `179`; vision→radar: `178`.
- Radar-ID association switches where the old ID remains in the immediately following `liveTracks` sweep: `4`.

## Same-track lateral flips

- Opposite-side crossings beyond ±0.25 m within one second: `0`.
- Affected radar track IDs: `[]`.
- Biggest same-ID >=0.50 m jump: `0.603 m` on ID `45`.

## leadOne/leadTwo duplication and swapping

- Duplicate same-radar-ID cycles: `38599/91485` = `42.19%` of all radarState cycles; `38599/38599` = `100.00%` of dual-radar cycles.
- Duplicate rows with identical dRel/yRel/vRel: `38599/38599` = `100.00%`.
- Longest contiguous duplicate run: `137.197 s` / `2744` cycles.
- Slot-swap family: `0` total (`0` strict A↔B swaps; `0` leadOne takeovers from prior leadTwo).

NEXT SCALPEL: Replay only the strongest old-track-alive leadOne switch and compare radard association scores for the two still-live IDs.
