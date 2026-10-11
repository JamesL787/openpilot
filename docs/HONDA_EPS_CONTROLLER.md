# Honda EPS controller (`LatControlHondaEps`)

The lateral controller for Hondas whose EPS runs a PTM (Proper Torque Mod) image: Clarity TRW-A020, Civic TBA-C020 /
TBA-C120 / TGG-A120 / TBA-A030 / TEG-A010, Insight TXM-A040, CR-V TLA-A040 / TLA-A220. Every one of those images runs
the same firmware control law with its own tables, so one controller serves them all; what differs per car lives in
one calibration record per EPS image.

## How it steers

The LKAS path is not a torque command. The firmware turns the 0xE4 value into a target R5, compares it with R6 (a
filtered steering rate, taken before the angle table) and runs P + D + KFF on the difference at 1 kHz. The controller
inverts that chain: a column load model says what motor output the desired motion needs, the firmware law is solved
for the R5 that produces it (rate damping included), and the command map is inverted back to a lateral output. An
angle PID on the residual closes the loop.

Per frame: curvature from controlsd -> command delay -> wheel angle (the car's geometry) -> slew limit -> angle PID +
firmware-inversion feedforward -> output filter -> carcontroller.

## Files

| File | What it holds |
|---|---|
| `selfdrive/controls/lib/latcontrol_honda_eps.py` | `LatControlHondaEps`, `use_honda_eps_controller()`, calibration selection, geometry, command delay |
| `selfdrive/controls/lib/honda_eps_firmware_ff.py` | the firmware law, `EpsFirmwareCalibration` and every image's calibration, `CALIBRATION_PROVENANCE`, `HondaEpsFirmwareFeedforward`, `HondaEpsLateralCore` |
| `selfdrive/controls/lib/honda_eps_rack_map.py` | `HondaEpsRackMap` and the yaw-fitted `RackMapTable`s |
| `selfdrive/controls/lib/honda_lateral_common.py` | what LatControlPID shares: road steer-ratio curves, slew limit, param readers |
| `opendbc/car/honda/steer_ratio.py` | each image's firmware A (position) table |
| `opendbc/car/honda/yaw_rate.py` | each car's VSA yaw (0x94) calibration |

## Which cars run it

A car runs `LatControlHondaEps` when its EPS part number has a calibration for that fingerprint, its torque map is the
linear `[0, E4 cap]` the calibration expects, it is modified-EPS on PID tuning, and either the calibration is
`default_on` (the Clarity) or `HondaEpsController` is on. Otherwise it stays on `LatControlPID`.

## The calibration record

`EpsFirmwareCalibration`, one per image, named by part number (`civic_tba_c020`, ...). Two halves:

- **Firmware**, read from the image: command-map row (key axis + R5), P-row key axis, key clamp, speed envelope,
  KFF, scale word, R6 (computed from the image's A table, or a telemetry fit).
- **Vehicle**, measured on the road: column load, residual-PID trims, command delay, model-delay schedule, rack map.

`CALIBRATION_PROVENANCE` records, for every quantity of every image, whether it is `firmware`, `measured` (with the
routes), `inferred` (carried over from a related car), `default` or `none`. A test requires the record to be
complete, and the controller logs the summary at start.

## Rules the controller follows

- **Geometry.** A calibration's yaw-fitted rack map, where it has one, is the geometry (firmware A table x a rack ratio
  by angle + slip factor, fitted against the car's yaw sensor). Without one: the road-measured steer-ratio curve, or
  the firmware table with `HondaEpsFirmwareVgr` on, or the table alone when the car has no road curve.
- **Command delay.** Every car delays the curvature it executes by its `cmd_delay_s` below 10 m/s, faded to 0 by
  15 m/s: the models aim at a fixed time ahead whatever delay they are told, and this controller reaches a command
  faster than the PID. Default 0.12 s, the smaller measured value, so an unmeasured car cannot be pushed late.
- **Model delay.** Every car tells the model its `lat_delay_schedule` in place of `liveDelay`; the Clarity's measured
  schedule is the default.
- **Driver override.** The shared modified-EPS press detector; after a press, while the carcontroller fades torque
  back in, the integrator bleeds toward 0 (tau 0.5 s) rather than holding its pre-press value.
- **Disengage** resets the PID and the feedforward.

## Params

| Param | Meaning |
|---|---|
| `HondaEpsController` | run it on the cars that are not `default_on` (read when controlsd starts) |
| `HondaEpsFirmwareVgr` | cars without a rack map: the firmware table instead of the road curve |
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
2. Add an `EpsFirmwareCalibration` and an `EPS_FIRMWARE_CALIBRATIONS` entry, with R6 computed from the A table.
3. Fill `CALIBRATION_PROVENANCE`, marking everything carried over as `inferred`.
4. Measure what its logs allow (table above) and replace `inferred` / `default` entries as measurements land.
