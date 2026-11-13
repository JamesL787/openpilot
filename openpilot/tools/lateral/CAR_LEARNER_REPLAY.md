# HondaEps car learner: replay on two CR-Vs (2026-11-12)

The learner (`selfdrive/controls/lib/honda_eps_car_learner.py`) replayed over each owner's rlogs in route order, through
the shadow daemon's own chunk builder:

```
python openpilot/tools/lateral/replay_car_learner.py <route dir> [...]            # as on the car
python openpilot/tools/lateral/replay_car_learner.py --no-freeze <route dir> ...  # what all of the data gives
```

Nothing here was driven. Design and criteria: `CAR_LEARNER_DESIGN.md`.

## Summary

| | CR-V A040 (153 min, 6 routes) | CR-V A220 (64 min, 5 routes) |
|---|---|---|
| column load | **frozen at 69 min** | not frozen: 21 of 30 s past 20 deg/s |
| yaw decode | **frozen at 109 min**: 0.2461 + 0.264 | not frozen: 11 + 9 chunks with pairs, needs 12 each |
| rack map | not frozen: halves 1.7% apart, limit 1.5% | waiting for the yaw; 45-100° bands at 7-10 of 15 s |
| command delay | measured, 1454 of 3000 entry frames | 122 of 3000 entry frames |
| model delay | measured, 11 / 66 / 128 s of 90 / 120 / 120 | 0 / 0 / 21 s |
| near-centre gain | 0.95 in town, 0.80-0.84 from 15 m/s | 0.60-0.65 up to 30 m/s |

The A220 does not freeze on these logs, and that is the right answer for 64 minutes of which 23 are usable. Its
candidate load already beats the shipped (A040) one at turn-ins. One regime cell would block it even with more
coverage; see below.

## CR-V A040

Routes 7528b01c2181d63d/00000002, 03, 04, 05, 0a, 0b. 76 min accepted for the load on all of it.

### Column load

Froze at 69 min of log (in route 03) on 18.5 min of accepted frames, friction knee 2 deg/s, motion lag 0 ms.

| | k0 | k1 | c | friction | bias | kroll | kd |
|---|---|---|---|---|---|---|---|
| shipped | −7.29 | −0.143 | −4.60 | −298 | −19.9 | −3.58 | |
| frozen at 69 min | −6.68 | −0.171 | −7.68 | −264 | −16.8 | −7.13 | 0.50 |
| learner, all 153 min (no freeze) | −8.04 | −0.146 | −6.55 | −267 | −10.1 | −5.46 | 0.57 |
| offline recipe refit, all six routes | −8.99 | −0.153 | −7.01 | −320 | −8.2 | −5.42 | |

Regime error: mean (model − firmware) along the output, % of |firmware|, shipped / learned.

| | <8 m/s | 8-15 m/s | 15+ m/s |
|---|---|---|---|
| **at the freeze, each half scored on the other** | | | |
| turn-in | −12 / −6 (46 s) | −11 / −5 (44 s) | |
| hold | −41 / −41 (130 s) | −26 / −21 (263 s) | −16 / −12 (321 s) |
| unwind | −2 / 0 (33 s) | −8 / +3 (44 s) | |
| **the frozen load on the 57 min after the freeze** | | | |
| turn-in | −11 / −5 (102 s) | −12 / −7 (90 s) | +20 / +24 (23 s) |
| hold | −43 / −44 (317 s) | −31 / −27 (596 s) | −5 / +3 (1091 s) |
| unwind | +3 / +7 (82 s) | −2 / +7 (97 s) | +9 / +25 (22 s) |

- Open-loop 0.6-2.5 Hz wheel gain, simulated / measured: 1.06 at 9-20 m/s and 0.86 at 20-40 m/s (shipped 1.12 / 0.89).
  0.86 is one hundredth inside the gate. On all of the data the candidate reads 1.07 / 0.99.
- Pooled R² on the drives after the freeze: 0.864, shipped 0.870. The shipped load was fitted on this car, so parity
  is the expected result. The frozen load is better at town turn-ins and slightly worse at unwinds.
- The frozen k0 and k1 are 17% from what all of the data gives. The split-half and regime checks passed, but 18.5
  minutes is a thin basis for this column.

### Yaw decode

| | scale, deg/s per count | clockwise, deg/s | |
|---|---|---|---|
| shipped (opendbc) | 0.245 | 0.49 | |
| frozen at 109 min | 0.2461 | 0.264 | 1,348 pairs on 4 drives, zero error +0.07 counts |
| learner, all 153 min | 0.2456 | 0.264 | 2,047 pairs on 6 drives, zero error 0.00 |
| `fit_yaw_scale.py`, two terms, routes 03-05 | 0.2488 | 0.192 | 1,123 pairs |
| `fit_yaw_scale.py`, two terms, all six | 0.2481 | 0.183 | 2,124 pairs |

- The shipped clockwise correction is about twice too big, as the offline fit said.
- The two-term offline answer is not robust. Shifting the zero by ±0.2 counts moves it from 0.2421 + 0.44 to
  0.2487 + 0.14. The offline tool takes a route-mean zero and carstate the last standstill's, and per-route zeros on
  this car spread over 509.1-509.8. With the zero fitted as a third term the answer stays at 0.246 + 0.25 for all three
  shifts.
- The clockwise term is still only good to about ±0.08 deg/s. On all 153 min the two halves read 0.177 and 0.342
  and would no longer pass. At 2 deg/s to the right that is a 6% spread; at 10 deg/s, 0.4%.

### Rack map

Not frozen: on the frozen yaw decode the halves differ by 1.7% in one band (limit 1.5%). Candidate from 1,825 s of
turning:

| \|angle\|, deg | 5.3 | 13.9 | 25.9 | 57.2 | 82.9 | 124.6 | 173.3 | 214.9 | 300.8 | slip factor |
|---|---|---|---|---|---|---|---|---|---|---|
| candidate | 17.21 | 16.80 | 16.74 | 16.52 | 16.41 | 16.30 | 16.18 | 16.12 | 16.02 | −0.00085 |
| shipped | 17.38 | 16.90 | 16.67 | 16.45 | 16.27 | 16.17 | 16.04 | 15.90 | 15.53 | −0.00084 |
| on the shipped yaw decode | 16.74 | 16.54 | 16.54 | 16.51 | 16.42 | 16.33 | 16.21 | 16.12 | 16.03 | −0.00077 |

Within 1% of the shipped map up to 175°. The last row shows why the rack waits for the yaw: the shipped decode moves
the centre by 3%.

### Timing (measured only)

- Car against the model's plan at the 0.12 s command delay: entry −0.08 s, exit −0.01 s, all −0.06 s (negative =
  early; 1454 / 1271 / 6903 frames).
- Lag behind the model action: 0.28 / 0.24 / 0.27 s at 3.75 / 7 / 12 m/s on 11 / 66 / 128 s. The shipped schedule
  tells 0.15 / 0.08 / 0.10. Too little data to judge, and the routes mix models.

## CR-V A220

Routes 957267d27a04f758/00000039 and 3d (October), 00000002, 04, 08 (November). 23 min accepted for the load.

### Column load (candidate, not frozen)

| | k0 | k1 | c | friction | bias | kroll | kd | R² |
|---|---|---|---|---|---|---|---|---|
| shipped (the A040's) | −7.29 | −0.143 | −4.60 | −298 | −19.9 | −3.58 | | 0.77 |
| learner, five routes | −10.99 | −0.151 | −4.73 | −379 | −32.1 | +0.39 | 0.47 | 0.835 |
| learner, without route 08 | −13.96 | −0.139 | −6.16 | −371 | −46.8 | +0.85 | 0.54 | 0.851 |
| offline recipe refit, without route 08 | −17.54 | −0.136 | −6.91 | −422 | −45.4 | +0.86 | | 0.801 |

- **The gap to the offline refit is the driver's torque.** On the same frames the recipe gives k0 −16.8 and friction
  −411 without the driver term and −14.0 / −371 with it and the fade-up frames out. The recipe books a resting hand's
  drag as column stiffness and friction.
- **Route 08 still pulls k0** (−14.0 to −11.0). It is 4 min, low speed. The learner has no way to leave a drive out.
- **Coverage is what stops it**: 21 of 30 s past 20 deg/s. The |torque| cap is not the limit on these logs: 72-97% of
  engaged unpressed frames are already under 300. Engaged unpressed time is: 3.1, 2.7 and 2.1 min in the three November
  routes.

Regime error at the end, each half scored on the other, shipped / learned:

| | <8 m/s | 8-15 m/s | 15+ m/s |
|---|---|---|---|
| turn-in | | −21 / −5 (34 s) | |
| hold | −58 / −46 (44 s) | −39 / −31 (303 s) | −25 / −21 (758 s) |
| unwind | | **+1 / +18 (30 s)** | |

- The turn-in under-ask of the A040 load is gone (−21% to −5%).
- **The unwind cell would block the freeze** under the regime rule: +18% against +1%. It is 30 s of data and 18% of a
  small output (median ~230 counts). Held out by route the offline refit shows the same sign (+19%).
- Hold is under-asked by 20-45% on both cars with either load. The load model has no hold friction.

Open-loop wheel gain: 0.99 at 9-20 m/s and 0.94 at 20-40 m/s on the learner's 16 kept windows (shipped 1.07 / 1.04).
**This gate is noisy on this car.** Over all 26 highway windows the offline refit reads 0.72 and the driver-term fit
0.81 (quartiles 0.64-0.97), and a 16-window sample of the same windows reads 0.99. With the knee at 5 deg/s above
15 m/s the 26-window gain is 1.07 for 0.02 of R². A speed-split friction makes it worse (0.76): the fit puts more
friction on the highway, not less.

### Yaw decode (candidate, not frozen)

0.2477 deg/s per count + 0.102 clockwise, zero error +0.02 counts, from 120,232 pairs (10 Hz GPS) on 6 drives. Shipped
0.245 + 0.49: the clockwise correction is about five times too big for this car. It lacks turns in enough separate
minutes (11 + 9 chunks, 12 needed per half).

This car's sensor zero is 512.0. The CR-V seed in opendbc is the A040 car's 509.5, so until the first stop of a
drive its `carState.yawRate` is off by 0.6 deg/s. The learner ignores yaw until that stop.

### Rack map (candidate, thin)

528 s of turning, bands at 45-100° short. On the candidate decode: 18.34 / 17.15 / 16.76 / 16.38 / 16.12 / 15.98 /
15.91 at 5 / 14 / 29 / 56 / 84 / 126 / 174°, slip factor −0.00086. The shipped A040 map is within 1.5% from 14° up.
The 5° value is not trustworthy on this little data.

## Near-centre gain

Car curvature over the shipped rack map's, inside ±3°, within 10 s windows (each window's mean removed). The second
number is the same slope at 4-12°.

| m/s | A040 inside ±3° | A040 at 4-12° | A220 inside ±3° | A220 at 4-12° |
|---|---|---|---|---|
| 5-9 | 0.95 (199 s) | 0.99 | 0.60 (79 s) | (19 s only) |
| 9-15 | 0.96 (519 s) | 0.98 | 0.62 (358 s) | 1.01 |
| 15-30 | 0.84 (1322 s) | 0.96 | 0.65 (456 s) | 0.96 |
| 30-45 | 0.80 (680 s) | | 0.43 (110 s) | |

- The A220 turns about 0.6 of what the map says for small quick corrections around centre, at every speed, and the
  full amount a few degrees out. That is a real centre deficit, not yaw dynamics.
- The A040 has it only from 15 m/s, and milder.
- How it is measured matters. A pooled fit with paramsd's angle offset reads 1.0 on both cars, because that offset is
  fitted to the yaw. A pooled fit against a fixed offset with roll ignored reads lower than these (0.33-0.68 on the
  A220), because road crown moves the wheel without turning the car.

## Torque sensor: what the EPS puts on `steeringTorque`

Revised 2026-11-12. The first version of this section regressed the reading on the firmware output over frames with no
reading above 400 within ±1.5 s. That selection throws out every reading the EPS makes above 400, and the "share of
the firmware output" it found (0.12-0.13) was mostly standing in for column friction.

The sensor is a torsion bar under the wheel, and the EPS motor is below it. The bar carries what it takes to move the
wheel and the column above it, whoever moves them:

`reading = driver + offset + inertia × wheel acceleration + friction × memory + imbalance × sin(wheel angle)`

Memory is the way the wheel last moved (a stop over 0.1° of travel). Fitted over frames with quiet readings 0.5-3 s to
either side and nothing selected between, with the shadow yield's own filter:

| car | min | offset | inertia, per deg/s² | friction | imbalance | quiet reading rms, before → after | R² |
|---|---|---|---|---|---|---|---|
| Clarity TRW-A020 | 245 | −54 | −0.20 | −91 | −127 | 94 → 37 | 0.84 |
| CR-V TLA-A040 | 59 | +121 | −0.26 | −65 | −203 | 74 → 38 | 0.74 |
| CR-V TLA-A220 | 35 | +84 | −0.21 | −56 | −197 | 65 → 37 | 0.68 |
| Civic TGG-A120 | 72 | +20 | −0.20 | −107 | −209 | 115 → 53 | 0.79 |
| Civic TEG-A010 | 84 | −117 | −0.26 | −91 | −157 | 93 → 40 | 0.81 |
| Insight TXM-A040 | 65 | +60 | −0.24 | −50 | −160 | 61 → 33 | 0.71 |
| Ridgeline T6Z-A110 | 14 | −92 | −0.28 | −10 | −22 | 45 → 42 | 0.13 |

- In a steady hold the reading follows the way the wheel last moved, not the size of the command: on the Clarity it is
  +17 counts along the command when the wheel last moved the command's way and +134 when it last moved the other way.
- Plain friction on wheel speed explains 41-57% of the quiet reading on the first six cars, friction with memory
  67-81%. Adding the firmware output on top of that gives 3-12 points more, at 0.06-0.12 per count: a resting hand or
  something real, the logs cannot tell.
- The inertia is known to roughly a factor of two. The wheel-rate signal is coarse, which pulls a fit down; these are
  the values that fit this filter.
- Not fitted: the RDX (its logs are of a shaking wheel) and the Civic C020 (10 min).
- "Quiet" is a stand-in for hands off. The logs have no ground truth; a deliberate hands-off drive would give one.

The shadow driver yield (`selfdrive/controls/lib/honda_eps_driver_yield.py`) takes these terms out of the reading. It
needs no EPS calibration, so it holds for any Honda with this sensor; a car that is not in its table takes the middle
of these.

## Cost

In the Linux build container on an M-series Mac: 131 ms per 60 s chunk, 1.6 s for the open-loop gate over 29 windows,
0.53 MB of saved state, a 2.6 kB result. Expect a few times that on the device; not measured there.

## What still blocks reading the result back into the controller

1. **Nothing has run on a car.** The daemon's message loop is untested on a device. The first shadow drives need
   comparing with a replay of the same drives.
2. **The A220 needs more driving** before anything freezes, and its unwind regime cell fails the rule on the data so
   far.
3. **Hold is under-asked by 20-45% by every load**, shipped or learned. Decide whether a hold term comes first.
4. **The open-loop gate's median is unstable on 16 windows** (0.81 to 0.99 on the A220). It needs more windows or a
   steadier statistic before it decides a freeze.
5. **A frozen load can sit 17% from the long-run fit** in k0 and k1 (A040 at 18.5 min). Raise the minimum, or let a
   frozen load be re-judged.
6. **The yaw decode is per fingerprint in opendbc.** A learned scale, clockwise term and zero seed need a per-car path
   into carstate. The clockwise term is good to ±0.08 deg/s at best.
7. **The rack map has no splice rule.** The learner covers 5-300° at most; the shipped tables continue to lock.
8. **The fitted friction knee has no home.** The calibration's `friction_width_v` is the feedforward's knee on the
   desired rate, a different thing.
9. **Timing stays measured.** The agreed standard is shadow, then review.
10. **A reflash is not detectable.** Every PTM build of a car reports the same version string. Only the load has a
    stale monitor.
11. **One bad drive cannot be left out** (the A220's route 08).
12. **Other cars are not replayed.** The old prototype's caches (Clarity, C020, TEG, Insight) are gone, and their
    telemetry targets are not used by this version.
