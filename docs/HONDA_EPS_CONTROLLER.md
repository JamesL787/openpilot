# Honda EPS controller (`LatControlHondaEps`)

The lateral controller for Hondas whose EPS runs a PTM (Proper Torque Mod) image: Clarity TRW-A020, Civic TBA-C020 /
TBA-C120 / TGG-A120 / TBA-A030 / TEG-A010, Insight TXM-A040, CR-V TLA-A040 / TLA-A220. Every one of those images runs
the same firmware control law with its own tables, so one controller serves them all; what differs per car lives in
one calibration record per EPS image.

## How it steers

The LKAS path is not a torque command. The firmware turns the 0xE4 value into a target R5, compares it with R6 (a
filtered steering rate, taken before the angle table) and runs P + D + KFF on the difference in its fast control
loop. The controller
inverts that chain: a column load model says what motor output the desired motion needs, the firmware law is solved
for the R5 that produces it (rate damping included), and the command map is inverted back to a lateral output. An
angle PID on the residual closes the loop.

Per frame: curvature from controlsd -> command delay -> wheel angle (the car's geometry) -> slew limit -> angle PID +
firmware-inversion feedforward -> output filter -> carcontroller.

## Files

| File | What it holds |
|---|---|
| `selfdrive/controls/lib/latcontrol_honda_eps.py` | `LatControlHondaEps`, `use_honda_eps_controller()`, calibration selection, geometry, command delay |
| `selfdrive/controls/lib/honda_eps_firmware_ff.py` | the firmware law, `computed_r6`, `EpsFirmwareCalibration`, `HondaEpsFirmwareFeedforward`, `HondaEpsLateralCore` |
| `selfdrive/controls/lib/honda_eps_calibrations.py` | every image's calibration, `EPS_FIRMWARE_CALIBRATIONS`, `CALIBRATION_PROVENANCE`, `REQUIRED_PTM_RWD` |
| `selfdrive/controls/lib/honda_eps_rack_map.py` | `HondaEpsRackMap` and the yaw-fitted `RackMapTable`s |
| `selfdrive/controls/lib/honda_eps_spec_plant.py` | rack map, slip factor and column load predicted from a car's published specs and its A table |
| `selfdrive/controls/lib/honda_lateral_common.py` | what LatControlPID shares: road steer-ratio curves, slew limit, param readers |
| `opendbc/car/honda/steer_ratio.py` | each image's firmware A (position) table |
| `opendbc/car/honda/yaw_rate.py` | each car's VSA yaw (0x94) calibration |

## Which cars run it

A car runs `LatControlHondaEps` when its EPS part number has a calibration for that fingerprint, its torque map is the
linear `[0, E4 cap]` the calibration expects, its firmware A table is known (the rack map needs it), it is
modified-EPS on PID tuning, and either the calibration is
`default_on` (the Clarity) or `HondaEpsController` is on. Otherwise it stays on `LatControlPID`.

### LatControlPID fallback (to be removed)

`LatControlPID`'s modified-EPS path is kept for now as the fallback for PTM cars with `HondaEpsController` off. Once
every image's vehicle calibration is measured (no `inferred` or `default` left in `CALIBRATION_PROVENANCE` for row,
load, command delay and geometry; R6 comes from the image), the `HondaEpsController` toggle is deprecated so every PTM car runs
`LatControlHondaEps`, and then the modified-EPS path in `LatControlPID` is removed.

## The calibration record

`EpsFirmwareCalibration`, one per image, named by part number (`civic_tba_c020`, ...). Two halves:

- **Firmware**, read from the image: command-map row (key axis + R5), P-row key axis, key clamp, speed envelope,
  KFF, scale word, R6. R6 is computed from the image's A table (`computed_r6`: -122 counts per deg/s at centre x
  NORM/1650 x A0/16384, shaped by the table's slope by angle) and clamped at +-32765 as the firmware clamps it, so
  it needs no EPS telemetry.
- **Vehicle**, measured on the road: column load, residual-PID trims, command delay, model-delay schedule, rack map.

`CALIBRATION_PROVENANCE` records, for every quantity of every image, whether it is `firmware`, `measured` (with the
routes), `inferred` (carried over from a related car), `spec` (predicted from published specs), `default` or `none`. A test requires the record to be
complete, and the controller logs the summary at start.

## Rules the controller follows

- **Geometry.** The calibration's rack map is the geometry: firmware A table x a rack ratio by angle + slip factor.
  Where the car has been measured it is fitted against its yaw sensor. Otherwise it is predicted from Honda's
  published specs (`honda_eps_spec_plant`): every measured map is the A table, a tan, and one centre ratio R0, and R0
  comes from the published lock-to-lock turns and lock ratio through the A table (held out one car at a time, 1.6%
  rms, 2.5% worst); the slip factor comes from the axle loads (within 10%). The A030 carries the TEG-A010's measured
  map (same car, same A table). Every calibration has one, and a car whose firmware A table is unknown stays on
  LatControlPID; paramsd's steer ratio, the road-measured curves and `HondaEpsFirmwareVgr` are LatControlPID's only.
- **Column load.** Measured per car, or carried over from the same platform. `spec_load_terms` predicts one from
  front-axle mass / R0^2 for an image with no sibling (holds within ~12%, turn rates ~15%, held out).
- **Command delay.** The curvature the car executes is delayed by the calibration's `cmd_delay_s` below 10 m/s,
  faded to 0 by 15 m/s, scaled by where the steering comes from (`starpilotModelV2.lateralSource`, which modeld sets
  per frame from the model actually steering):
  - **action head** (v14-v16, e.g. Cinque v3): the full `cmd_delay_s`. The model moves its aim only ~0.53 of a change
    in the told delay (aim ~0.30 + 0.53 x action_t), and this controller reaches a command faster than the model
    assumes; the measured values come from these drives. Default 0.12 s, the smaller measured value.
  - **plan** (v11-v12): no command delay. This fork reads the plan at the told action time exactly (there is no
    `MIN_STABLE_DELAY` floor here; upstream and nrdr floor it at 0.3 s), so the told delay already lands it on time.
  - **curvature head** (v9, pre-tinygrad) and **unknown** (older logs, no message yet): the full `cmd_delay_s`.
  When the model changes (eGPU, model lab, a fallback) the delay ramps to the new value over 1 s.
  `starpilotModelV2.delayInput` records how the told delay reaches the model (`actionT`, `lateralControlParams` or
  `none`); a model with none ignores the told delay.
- **Model delay.** Every car tells the model its `lat_delay_schedule` in place of `liveDelay`; the Clarity's measured
  schedule is the default. It is the car's measured lag, which a plan model follows exactly and an action head in part.
- **Driver override.** The shared modified-EPS press detector; after a press, while the carcontroller fades torque
  back in, the integrator bleeds toward 0 (tau 0.5 s) rather than holding its pre-press value.
- **Disengage** resets the PID and the feedforward.

## Params

| Param | Meaning |
|---|---|
| `HondaEpsController` | run it on the cars that are not `default_on` (read when controlsd starts) |
| `HondaEpsAngleRateLimit` | deg/s ceiling on the desired-angle slew (0 disables) |
| `HondaTorqueOutputLowPassFilter`, `HondaTorqueOutputLpfTau*` | the output filter |
| `HondaOverrideFadeUpSecs` / `FadeDownSecs` / `TorqueScale` | the override fade the carcontroller applies |

Old `NrdrLat*` names are migrated once at manager start.

## Logged

`starpilotLateralState`: `epsFfActive`, `epsFfFeedforward`, `epsFfR5`, `epsFfLoad`, `epsFfDesiredRate`, `epsFfWeight`,
`epsCalibration`, `epsCommandDelay`, `epsModelDelay`.

## Measuring a car

| Quantity | Tool | Needs |
|---|---|---|
| VSA yaw scale | `tools/lateral/fit_yaw_scale.py --bus N <route>` | GPS; straight-to-straight pairs, both turn directions |
| Rack map | `tools/lateral/fit_rack_map.py --car FP --vgr PROFILE --bus N --scale S --right R <routes>` | >= 300 s of turning at >= 3 deg, the GPS-checked yaw scale |
| Command delay | `tools/lateral/plan_timing.py <route>` | a drive on this controller, turns at 5-12 m/s |
| Per-drive check | `tools/lateral/eps_report.py <route>` | any drive: yaw sources, rack map vs the car, tracking, delivery, timing vs its schedule |
| Command row | `tools/lateral/live_row_fit.py teg\|c020 <route>` | a telemetry build whose rows differ |
| Column load | `tools/lateral/fit_column_load.py --source clarity\|c020\|teg\|e4 --calibration NAME <routes>` (the Clarity recipe) | telemetry, or the E4 -> firmware-law rebuild without it |

## Adding an image

1. Read its tables from the image the owners run: command-map rows and the variant record that selects the live row,
   P row, key clamp, envelope, A table (into `steer_ratio.py` if it is new).
2. Add an `EpsFirmwareCalibration` and an `EPS_FIRMWARE_CALIBRATIONS` entry in `honda_eps_calibrations.py`, with R6
   computed from the A table and, until the car is measured, its rack map from its published specs (`honda_eps_spec_plant`).
3. Fill `CALIBRATION_PROVENANCE`, marking everything carried over as `inferred`.
4. Measure what its logs allow (table above) and replace `inferred` / `default` entries as measurements land.

## Testing

`tools/lateral/run_eps_tests.sh` runs the controller's tests on a Mac against this checkout. Plain `pytest` goes
through the repo conftest, which can import a stale `.host_runtime` copy of the code and pass against it.
