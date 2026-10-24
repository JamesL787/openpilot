# Honda EPS controller (`LatControlHondaEps`)

The lateral controller for Hondas whose EPS runs a PTM (Proper Torque Mod) image: Clarity TRW-A020, Civic TBA-C020 /
TBA-C120 / TGG-A120 / TBA-A030 / TEG-A010, Insight TXM-A040, CR-V TLA-A040 / TLA-A220, Acura RDX 3G TJB-A220 (2019-21 and 2022+). Every one of those images runs
the same firmware control law with its own tables, so one controller serves them all; what differs per car lives in
one calibration record per EPS image.

## How it steers

The LKAS path is not a torque command. The firmware turns the 0xE4 value into a target R5, compares it with R6 (a
filtered steering rate, taken before the angle table) and runs P + D + KFF on the difference in its fast control
loop. The controller inverts that chain: a column load model says what motor output the desired motion needs, the
firmware law is solved for the R5 that produces it (rate damping included), and the command map is inverted back to a
lateral output. An angle PID on the residual closes the loop.

Per frame: curvature from controlsd -> command delay -> wheel angle (the car's geometry) -> slew limit -> angle PID +
firmware-inversion feedforward -> output filter -> carcontroller.

## Files

| File | What it holds |
|---|---|
| `openpilot/selfdrive/controls/lib/latcontrol_honda_eps.py` | `LatControlHondaEps`, `eps_firmware_calibration()`, geometry, command delay |
| `openpilot/selfdrive/controls/lib/honda_eps_firmware_ff.py` | the firmware law, `computed_r6`, `EpsFirmwareCalibration`, `HondaEpsFirmwareFeedforward`, `HondaEpsLateralCore` |
| `openpilot/selfdrive/controls/lib/honda_eps_calibrations.py` | every image's calibration, `EPS_FIRMWARE_CALIBRATIONS`, `CALIBRATION_PROVENANCE`, `REQUIRED_PTM_RWD` |
| `openpilot/selfdrive/controls/lib/honda_eps_rack_map.py` | `HondaEpsRackMap` and the yaw-fitted `RackMapTable`s |
| `openpilot/selfdrive/controls/lib/honda_eps_spec_plant.py` | rack map, slip factor and column load predicted from a car's published specs and its A table |
| `openpilot/selfdrive/controls/lib/latcontrol_honda_modified_pid.py` | `LatControlHondaModifiedPID`, the fallback for modified images with no calibration |
| `openpilot/selfdrive/controls/lib/honda_lateral_common.py` | what the modified PID shares: road steer-ratio curves, slew limit, param readers |
| `openpilot/selfdrive/controls/lib/lateral_controller_factory.py` | which controller a car gets |
| `openpilot/selfdrive/modeld/lateral_source.py` | where the steering comes from, written to the `ModelLateralSource` param |
| `opendbc_repo/opendbc/car/honda/steer_ratio.py` | each image's firmware A (position) table |
| `opendbc_repo/opendbc/car/honda/yaw_rate.py` | each car's VSA yaw (0x94) calibration |

## Which cars run it

A car runs `LatControlHondaEps` when it is modified-EPS on PID tuning, its EPS part number has a calibration for that
fingerprint, its torque map (`CarControllerParams.STEER_LOOKUP`) is the linear `[-cap, 0, cap]` the calibration
expects, and its firmware A table is known (the rack map needs it). There is no setting: every calibrated image runs
it.

### Modified-EPS PID fallback

A modified image with no calibration yet (Civic Bosch TGG-A020, Accord TVA-A150) runs
`LatControlHondaModifiedPID`, the angle-space PID the PTM cars ran before this controller. It stays until those images
get a first calibration. Every other PID car keeps 7.0's stock `LatControlPID`.

## The calibration record

`EpsFirmwareCalibration`, one per image, named by part number (`civic_tba_c020`, ...). Two halves:

- **Firmware**, read from the image: command-map row (key axis + R5), P-row key axis, key clamp, speed envelope,
  KFF, scale word, R6. R6 is computed from the image's A table (`computed_r6`: -122 counts per deg/s at centre x
  NORM/1650 x A0/16384, shaped by the table's slope by angle) and clamped at +-32765 as the firmware clamps it, so
  it needs no EPS telemetry. (The RDX's TJB-A220 has no A table: its R6 is read from the firmware, see Geometry.)
- **Vehicle**, measured on the road: column load, residual-PID trims, command delay, model-delay schedule, rack map.

`CALIBRATION_PROVENANCE` records, for every quantity of every image, whether it is `firmware`, `measured` (with the
routes), `inferred` (carried over from a related car), `spec` (predicted from published specs), `default` or `none`.
A test requires the record to be complete, and the controller logs the summary at start.

The C020's calibration follows its corrected rev-b PTM (RWD df67bf6f); the TGG-A120 has its own measured column, rack map
and live command row (row 0).

Each earlier PTM build of an image reports the same EPS version string as the corrected one, so openpilot cannot tell
them apart: `REQUIRED_PTM_RWD` names the build each calibration models, and the car must run that build.

## Rules the controller follows

- **Geometry.** The calibration's rack map is the geometry: firmware A table x a rack ratio by angle + slip factor.
  Where the car has been measured it is fitted against its yaw sensor. Otherwise it is predicted from Honda's
  published specs (`honda_eps_spec_plant`): every measured map is the A table, a tan, and one centre ratio R0, and R0
  comes from the published lock-to-lock turns and lock ratio through the A table (held out one car at a time, 1.6%
  rms, 2.5% worst); the slip factor comes from the axle loads (within 10%). The A030 carries the TEG-A010's measured
  map (same car, same A table). Every calibration has a rack map, and a car whose firmware A table is unknown stays on the
  modified PID; paramsd's steer ratio, the road-measured curves and `HondaEpsFirmwareVgr` apply to the modified PID
  only.
- **The RDX.** Its TJB-A220 image has no A table at all: its linear map is integrated from the EPS's own 0x18F rate word,
  which quickens with the rack, and the rack map is fitted on its yaw through it. The same PTM runs on every 3G RDX
  (2019-2026, the 2022+ MMR included), so both fingerprints take this calibration; its vehicle side was measured on a 2019
  over five routes. R6 is read from the firmware (reference = 32 x its 0x18F rate word x 0.4812, the word measured at 7.8
  per deg/s), and a closed-loop replay (`openpilot/tools/lateral/eps_closed_loop.py`) sets its trims, P x0.7 above 50 mph
  and a softer friction knee at speed (`friction_width_v`), because its loop is delay-limited there.
- **Column load.** Measured per car, or carried over from the same platform. `spec_load_terms` predicts one from
  front-axle mass / R0^2 for an image with no sibling (holds within ~12%, turn rates ~15%, held out).
- **Command delay.** The curvature the car executes is delayed by the calibration's `cmd_delay_s` below 10 m/s and
  `cmd_delay_highway_s` from 15 m/s (the Civics hold theirs flat at 0.15 s and the Clarity takes 0.10 s, since they ran as early
  on the highway as in town; the Insight (0.15 s in town), both CR-Vs and the RDX (the 0.12 s default) have none from 15 m/s), scaled by where the steering comes from (the `ModelLateralSource` param,
  which modeld writes whenever the model actually steering changes, a Chestnut stall included; controlsd reads it once
  a second):
  - **actionHead** (v14-v16, e.g. Cinque v3): the full `cmd_delay_s`. The model moves its aim only ~0.53 of a change
    in the told delay (aim ~0.30 + 0.53 x action_t), and this controller reaches a command faster than the model
    assumes; the measured values come from these drives.
  - **plan** (a catalog model whose runner reads the plan at the told action time exactly): no command delay, since
    the told delay already lands it on time.
  - **curvatureHead** (v9) and **unknown** (no message yet, or a plan read through `get_curvature_from_plan`, which
    floors the action time at `MIN_STABLE_DELAY` 0.3 s: the bundled Chestnut runner, Jetlink): the full `cmd_delay_s`.
  When the model changes (eGPU, a fallback) the delay ramps to the new value over 1 s.
- **Model delay.** Every car tells the model its `lat_delay_schedule` in place of lagd's `lateralDelay`; controlsd
  and modeld both read it. It is the car's measured lag (from the camera frame to its own yaw curvature, less modeld's
  0.075 s), which a plan model follows exactly and an action head in part. The Clarity's measured schedule is the
  default; the TEG has its own (0.20 s flat) and the C020 a provisional one (0.28 s in town, 0.26 s on the highway,
  from an older controller's drive); the A030 takes the TEG's and the C120 and TGG the C020's. lagd told the Civics
  0.37-0.39 s, which ran them early.
- **Driver override.** The shared modified-EPS press detector; after a press, while the carcontroller fades torque
  back in, the integrator bleeds toward 0 (tau 0.5 s) rather than holding its pre-press value.
- **Output ceiling.** The output is limited to what the firmware still answers: past the end of the command row or the
  input clamp, more 0xE4 gives the same R5. A 4096-per-unit car whose row ends at key 1663 (CR-V A040 rows 0-1, A220 rows
  0-3) tops out at 3841/4096 = 0.9377 (key 1663 is 3840.6 E4 counts, rounded up); a car sent its own clamp (the Clarity,
  the Civics, the Insight, the RDX) at 1.0. The residual PID is
  clamped to the same ceiling so its integrator cannot wind into 0xE4 the map ignores.
- **Dropouts (RDX only).** A one-frame STEER_STATUS fault drops latActive for a frame, and controlsd resets the controller
  on every inactive frame. The RDX's NO_TORQUE_ALERT_1 (STEER_STATUS=2) trips when the EPS's torque signal passes 768 of its own
  counts, which are half the Clarity's: 768 x 2 = 1536 in the Clarity's internal units, and the 0x18F packer scales those
  by 1000/512, so it shows as |STEER_TORQUE_SENSOR| of about 3000 on the CAN bus (flipping at about 3000 on the RDX logs;
  the Clarity's own trip is the same 3000, measured onset 3048-3064). Its rise debounce is about 3 ticks where the
  Clarity's is 50, so the status flips within one 10 ms frame of the crossing, and one hard torque spike is enough. A
  dropout shorter than `RIDE_THROUGH_S` (0.1 s) sends nothing but keeps the feedforward and tracks with the integrator
  held; a longer one resets as before. Only the RDX has the window (`RIDE_THROUGH_CARS`, the fingerprints of its
  "39990-TJB-A220" calibration, both 3G fingerprints): the fault is the RDX's and no other car has been road-checked with it,
  so every other car resets on every inactive frame exactly as before (`ride_through_frames` is 0). In the closed-loop replay of the turn that prompted it (route
  412ed2539bfc2c42/000000cc): feedforward off 250 -> 0 ms, worst error 11 -> 8 deg.
- **Disengage** (a dropout past the ride-through) resets the PID and the feedforward.

## Settings

The Night Star page (`openpilot/starpilot/ui/night_star_feature.py`) edits these live, onroad too:

| Param | Meaning |
|---|---|
| `HondaEpsAngleRateLimit` | deg/s ceiling on the desired-angle slew (0 disables); shown on calibrated cars only |
| `HondaDriverOverrideThreshold`, `HondaOverrideTorqueScale`, `HondaDriverAssistDuringOverride` | the override the carcontroller applies |
| `HondaMinSteerSpeed` | no steering torque below this speed |

Fixed by design, with no row: `HondaTorqueOutputLowPassFilter` / `HondaTorqueOutputLpfTau*` (the output filter),
`HondaOverrideFadeUpSecs` / `FadeDownSecs`, and `HondaSteerDeltaLimiter` / `HondaSteerDeltaUp` / `Down` (the stock steer
rate limit: off by default, still read by the carcontroller, off the page since 10-20). These keys survive 7.0's first-start archive
(`openpilot/starpilot/honda_eps_settings.py`), and the manager moves values saved under older names to the current
ones first.

## Logged

`starpilotLateralState`: `epsFfActive`, `epsFfFeedforward`, `epsFfR5`, `epsFfLoad`, `epsFfDesiredRate`, `epsFfWeight`,
`epsCalibration`, `epsCommandDelay`, `epsModelDelay`. The steering source is not a schema field (StarPilot's
fork-compatibility policy has no free Event slot): modeld logs a `modelLateralSource` cloudlog event, with the model
id, each time it changes.

## Measuring a car

Run from the repo root with `PYTHONPATH=<repo>:<repo>/opendbc_repo`. Logs from before 7.0 read as well: the messages
the tools use kept their ordinals across 7.0's renames (`vehicleParameters`, `deviceMotion`).

| Quantity | Tool | Needs |
|---|---|---|
| VSA yaw scale | `openpilot/tools/lateral/fit_yaw_scale.py --bus N <route>` | GPS; straight-to-straight pairs, both turn directions |
| Rack map | `openpilot/tools/lateral/fit_rack_map.py --car FP --vgr PROFILE --bus N --scale S --right R <routes>` | >= 300 s of turning at >= 3 deg, the GPS-checked yaw scale |
| Command delay | `openpilot/tools/lateral/plan_timing.py <route>` | a drive on this controller, turns at 5-12 m/s |
| Per-drive check | `openpilot/tools/lateral/eps_report.py <route>` | any drive: yaw sources, rack map vs the car, tracking, delivery, timing vs its schedule |
| Closed-loop trims | `openpilot/tools/lateral/eps_closed_loop.py --calibration NAME <route dir>` | hands-off engaged windows; replays the core against the car's firmware law and fitted column, open loop and closed loop, with and without the calibration's P scale and friction knee |
| Command row | `openpilot/tools/lateral/live_row_fit.py teg\|c020 <route>` | a telemetry build whose rows differ |
| Column load | `openpilot/tools/lateral/fit_column_load.py --source clarity\|c020\|teg\|e4 --calibration NAME <routes>` (the Clarity recipe) | telemetry, or the E4 -> firmware-law rebuild without it |

## Adding an image

1. Read its tables from the image the owners run: command-map rows and the variant record that selects the live row,
   P row, key clamp, envelope, A table (into `steer_ratio.py` if it is new).
2. Add an `EpsFirmwareCalibration` and an `EPS_FIRMWARE_CALIBRATIONS` entry in `honda_eps_calibrations.py`, with R6
   computed from the A table and, until the car is measured, its rack map from its published specs
   (`honda_eps_spec_plant`). From then on the car steers with this controller instead of the modified PID.
3. Fill `CALIBRATION_PROVENANCE`, marking everything carried over as `inferred`, and `REQUIRED_PTM_RWD`.
4. Measure what its logs allow (table above) and replace `inferred` / `default` entries as measurements land.

## Testing

`tools/night_star_port/docker_pytest.sh -q <tests>` runs the tests in the larch64 builder container against the
committed device artifacts. The controller's tests: `openpilot/selfdrive/controls/tests/test_honda_eps_*.py`,
`test_latcontrol_pid_eps_modified.py`, `opendbc_repo/opendbc/car/honda/tests/test_modified_eps.py`, and the Night Star page's
`openpilot/starpilot/galaxy/tests/test_night_star_settings.py`.
