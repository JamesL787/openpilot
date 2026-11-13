# HondaEps car learner: design (shadow)

Status 2026-11-12: ported onto this branch's modules, wired as a shadow daemon behind `HondaEpsLearner` (default on on this branch).
It measures and publishes. **Nothing reads its result back into the controller.** Replay results on two CR-Vs:
`CAR_LEARNER_REPLAY.md`.

| what | where |
|---|---|
| learner (numpy + the controller's own modules) | `selfdrive/controls/lib/honda_eps_car_learner.py` |
| column simulator shared with `eps_closed_loop.py` | `selfdrive/controls/lib/honda_eps_column_plant.py` |
| daemon and chunk builder | `selfdrive/controls/honda_eps_learnerd.py` |
| replay over rlogs (through the daemon's chunk builder) | `tools/lateral/replay_car_learner.py` |
| read the result out of a qlog | `tools/lateral/learner_result.py` |
| tests | `selfdrive/controls/tests/test_honda_eps_car_learner.py` |

## Goal

The firmware half of an `EpsFirmwareCalibration` is read from the PTM image. The car half has needed owner rlogs and
an offline fit:

- the column load (`ColumnLoadModel`)
- the yaw decode (scale and clockwise correction of VSA 0x94)
- the rack map and its slip factor
- the command delay and the model-delay schedule

The learner does those fits on the device from 60 s chunks. Each part converges, then freezes and stops adapting.

## One copy of each recipe

The offline tools and the learner share code, so they cannot drift apart:

| recipe | shared piece | used by |
|---|---|---|
| load target | `firmware_target()`: `eps_ff.firmware_output(r5_from_output(...))`, the scalar law the controller runs | learner, `fit_column_load.py` |
| load regressors | `load_regressors()` | learner, `fit_column_load.py` |
| open-loop check | `honda_eps_column_plant.Plant`, `open_loop_window()` | learner, `eps_closed_loop.py` |
| rack fit | `RackMapFit`, `rack_samples()` | learner, `fit_rack_map.py` |
| yaw pairs | `straight_pairs()` | learner, `fit_yaw_scale.py` |
| rack geometry | `HondaEpsRackMap` | near-centre gain |

R6 is not learned: `computed_r6` takes it from the image, and the target and the feedforward's inversion both go
through it.

Two offline tools change slightly with this: `fit_rack_map.py` now pools rising ratios with the learner's weighted
isotonic fit, and `fit_yaw_scale.py` also prints the fit with a zero term.

## Parts and freeze criteria

Checks run every 5 chunks. Alternate chunks build two halves. A part freezes on its **second passing check in a row**.

### Column load

Fit: `k0 th + k1 th v² + c thd + fr tanh(thd/w) + j thdd + bias + kroll roll v² + kd tq`, motion lag searched over
0-40 ms, ridged toward the shipped load by 5 s of data.

- **Hands-on drivers.** The driver's torque is a regressor (`kd`), with a 1200-count cap and no frames inside the
  override fade-up (`HondaOverrideFadeUpSecs` + 0.3 s after a press). `kd` came out 0.54 / 0.58 counts per count on the
  A220 / A040. The deployable bias is taken at the mean torque, because the sensor has an offset (+90 / +124 counts).
- **Coverage:** 15 min accepted, 45 s past 20°, 30 s past 20 deg/s, 3 speed bands with 60 s each, and 6 hands-off 20 s
  windows in each of 9-20 and 20-40 m/s.
- **Bounds and identifiability:** as before, with k0 widened to −25 for the A220.
- **Split halves:** load surfaces within 10% of the full fit's RMS, cross R² within 0.05.
- **Regime gate.** In every turn-in / hold / unwind × (<8, 8-15, 15+ m/s) cell with 20 s of frames, each half's fit is
  scored on the other half as mean (model − firmware) along the output, in % of |firmware|. It may not be further from
  zero than the shipped load by more than 5 points in any cell.
- **Open-loop gate.** The column plant with the candidate load, driven by the logged 0xE4 over the kept windows, must
  give a 0.6-2.5 Hz wheel gain of 0.85-1.15 in both bands (median).
- **Friction knee.** If the gain is too low, the fit is retried with the knee above 15 m/s widened from 2 to 3.5, then
  5 deg/s (`friction_width_v`, at the feedforward's own speed breakpoints). The first knee that passes is frozen. A
  speed-split friction was tried and rejected: the fit puts *more* friction on the highway (to cover holds), which
  lowers the gain further.
- **After the freeze** nothing adapts. The gain of the measured target on the frozen prediction is watched, and a 15%
  move marks the load stale (a reflash, a changed column).

### Yaw decode

GPS straight-to-straight pairs, the `fit_yaw_scale.py` recipe, streaming. Three terms are fitted: scale, clockwise
correction, and a **zero error**. The two-term fit moves with the zero: 0.2 counts took the A040 from 0.2421 + 0.44 to
0.2487 + 0.14, while the three-term fit stayed at 0.246 + 0.25.

- Yaw is ignored until carstate has learned this drive's zero at a standstill.
- Coverage: 300 pairs, 20% each side, 12 chunks with pairs per half, 3 drives.
- Split halves: scale within 1%, clockwise term within 0.08 deg/s.

### Rack map

The `fit_rack_map.py` recipe on per-cell reservoirs (bounded). Samples store yaw **counts**, so the fit runs on
whichever decode is current. It only freezes once the yaw decode is frozen.

### Near-centre gain (reported, never applied)

Slope of the car's curvature on the shipped map's inside ±3°, within 10 s windows with each window's mean removed, per
speed band. The same slope at 4-12° is reported as the reference. Pooled fits with paramsd's angle offset read ~1.0
whatever the car does, because that offset is itself fitted to the yaw.

### Timing (measured only)

- **Command delay:** `plan_timing.py`'s shift of the car against the model's plan, for the town delay that ran. Chunks
  at another delay restart the measurement. There is no request and no handshake.
- **Model-delay schedule:** `eps_report`'s lag per town band.

### Torque sensor (reported only)

`steeringTorque` with quiet hands, regressed on what moving the wheel puts on the torsion bar: wheel inertia, the
column's friction (which remembers the way the wheel last moved) and the wheel's imbalance, plus an offset. The terms
come through the shadow driver yield's own filter (`honda_eps_driver_yield.DriverYield.terms`), so a fitted car's
numbers can go straight into its `TorqueSensor`. Nothing in the fit is the EPS command. Frames are kept when the reading
is quiet 0.5-3 s to either side and the default sensor leaves under 300 counts of them. See the replay report.

## Wiring

- **Process:** `honda_eps_learnerd`, started by manager only when `HondaEpsLearner` is on and the car is steered by
  LatControlHondaEps.
- **Inputs:** carState, carControl, sendcan (0xE4), modelV2, gpsLocation / gpsLocationExternal (queued, merged by
  time), vehicleParameters and starpilotLateralState (latest). controlsState is not needed, and `can` is not read: the
  yaw counts come back out of `carState.yawRate` through opendbc's calibration.
- **State:** `/data/honda_eps_learner/state.npz`, saved every 5 chunks, on a state change and on exit.
- **Reset:** `HondaEpsLearnerReset`, or automatically when the EPS version, the calibration name, the calibration's
  `REQUIRED_PTM_RWD` or the learner version changes.
- **Result:** `HondaEpsLearnerResult` (JSON, a few kB): per part its state, reason and frozen value or current
  candidate. Params are copied into every route's initData, so a qlog carries it.

Adding the three params changes `params_keys.h`, so the device needs a rebuild (`scripts/laptop_device_build.sh`).

## Traps

- **The law must match the image the drives ran.** Every PTM build of a car reports the same version string. Reset
  after a reflash; the stale monitor catches a forgotten one.
- **The yaw zero is per unit.** The CR-V seed (509.5) is the A040 car's; the A220 car sits at 512.0, so its yaw is off
  by 0.6 deg/s until the first stop of a drive.
- **A car without a decoded 0x94** (the Ridgeline) learns its load and timing only.
- **Telemetry targets are not used.** The old prototype could fit against 0x6A0-0x6A3 on the Clarity, C020 and TEG.
  That needs `can` on the device and was left out.
