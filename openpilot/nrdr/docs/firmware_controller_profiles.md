# Firmware Controller profiles

This is steering-angle feedback plus an EPS-firmware-inversion feedforward, not
real-time yaw feedback. `NrdrLateralController = 1` is latched at drive startup;
changing it requires offroad confirmation. PIF's Device Yaw Correction is separate.

| Detected vehicle / EPS family | Calibration | Basis | Prediction delay |
| --- | --- | --- | --- |
| HONDA_CLARITY / 39990-TRW-A020, modified EPS | Clarity TRW-A020 (P-minus-5 build) | Measured, road-validated | Measured speed schedule |
| HONDA_CIVIC_BOSCH / 39990-TBA-C020, modified EPS | Civic C020 TargetMapD / Tracker4500 / Norm1650 / P117to265 / D737 / KFF45 | Measured, road-validated | Normal live/manual path |
| HONDA_CIVIC / 39990-TEG-A010, modified EPS | Civic C020 calibration (placeholder) | **Provisional C020 placeholder, not road-validated for TEG** | Normal live/manual path |
| HONDA_CRV_5G / 39990-TLA-A040, modified EPS | CR-V TLA-A040 | Tables, R6 and load measured on the owner's telemetry rlogs | Normal live/manual path |
| HONDA_CIVIC_BOSCH / 39990-TBA-C120, modified EPS | Civic Bosch C120 | Tables from the image; R6 and load carried over from the C020. **Provisional** | Normal live/manual path |
| HONDA_CIVIC_BOSCH / 39990-TGG-A120, modified EPS | Civic hatch TGG-A120 | Tables from the image; R6 and load carried over from the C020. **Provisional** | Normal live/manual path |
| HONDA_INSIGHT / 39990-TXM-A040, modified EPS | Insight TXM-A040 | Tables from the image (row 0 on every Insight build); load measured from the owner's rlogs; R6 the C020's (no telemetry build) | Normal live/manual path |

PID CarParams and a matching firmware steer-ratio profile are also required. A
vehicle or firmware version not listed gets no firmware controller: there is no
generic Honda fallback, and the CR-V TLA-A220 has no entry until it has a drive.
"Provisional" means R6 and the column load are carried over from a cousin car
instead of measured from this car's rlogs; it is not a claim that the car behaves
like its cousin. No image except the Clarity and the C020 has steered with this
controller on the road. An EPS version string identifies a family, not the
flashed build: confirm the image separately. No ECU flashing or safety-limit
changes are part of this port.

## Timing

The temporary fixed 0.30-second prediction override is removed. Clarity uses
0.15 / 0.08 / 0.10 / 0.20 / 0.30 seconds at 3.5 / 7 / 12 / 20 / 30 m/s,
interpolated every frame, with endpoints held. Both model runtimes and controlsd
use the same profile. Saved live/manual settings are preserved but unavailable
while that schedule is selected. Civic has no measured prediction schedule in the
source and therefore keeps live/manual delay normally, subject to Suggested locks.
Model-specific smoothing remains separate, as in the source implementation.

Command delay is a separate interpolated curvature history buffer, not a blocking
sleep. It fades between 10 and 15 m/s. Clarity retains its saved endpoints, default
0.145 / 0.025 seconds. Every other image uses its own fixed source delay plus the
existing port's 0.025-second model-action compensation
(`SOURCE_COMMAND_DELAY_LOW`): C020, C120, TGG-A120 and Insight 0.175 / 0.025 seconds
(source 0.150, measured on the C020, inferred for the Insight); CR-V and any image
without its own value 0.145 / 0.025 (the Clarity's 0.120, the smaller measured value,
so an unmeasured car cannot be pushed late). Saved Clarity command-delay settings do
not retune them. These are model-dependent calibrations, not a guarantee for every
driving model.

## Calibration and unchanged behavior

C020 has its own nonlinear command map, speed envelope, measured angle-dependent R6, column
load fit, fixed P trims (115 / 125 / 115%) and I trims (75 / 95 / 100%). Its firmware
law inversion includes both the command-map and P-map knots. Clarity keeps its
angle-dependent R6 conversion and all existing core numerical behavior.

Each image carries its own command map, P-row axis, key clamp, speed envelope,
R6, column load and fixed P/I trims (`FIRMWARE_CAR_TUNES`), so no image is
evaluated with another's tables. The Civic family runs the C020's trims
(115 / 125 / 115% P, 75 / 95 / 100% I); the CR-V runs untrimmed (100%), as its owner drives it. Transport
differs by fingerprint and follows this tree's opendbc (`_EXTENDED_TORQUE_LIMITS`),
which a test checks: the Clarity sends through the 3840-count transport; Civic
Bosch (C020, C120, TGG-A120), Insight and CR-V through 4096. The command clamp word read from each image is 1663, which is E4 3840, on
every image but the CR-V's (1774, E4 4096): the firmware ignores E4 above that. So
on the Civic Bosch images (C020, C120, TGG-A120) and the Insight, which this tree's
opendbc sends 4096, a command above 0.9375 of full scale saturates in the firmware
and the controller models that with the clamp. Capping those cars' transport at
3840, as the source branch's opendbc does for the C120 and Insight, is an opendbc
change and not part of this port.

The TEG exception deliberately uses the complete C020 controller calibration,
not a hybrid of Clarity load/P-I trims. Its real vehicle geometry and CAN range
are still retained: TEG sends through its existing 3840-count transport, whereas
the fitted C020 model assumes 4096. Its plant/normalization is consequently only a
placeholder; there is no claim that commands or resulting motion are equivalent.
Unknown physical firmware behavior cannot be inferred from this substitution.

The C020 now uses its own P-row axis (0, 223, 441, ...) read from its image, where
this port had borrowed the Clarity's (0, 222, 443, ...); the C020 R5 target moves by
0.025% at the median and 0.56% at the 99th percentile.

The Clarity calibration describes the P-minus-5 build (P117 to 265, D737, KFF45,
Tracker3200, Norm1650). The A280-flat variant of that build edits only the A280
torque-rate governor's cells, so these tables are unchanged; it should hold the
0x6A2 scale word at a constant 256, which is the value the model assumes. No route
on the A280-flat build has been analysed yet. The A280 pump is the sustainer of the
rare 6.5 Hz stutter on the earlier build.

Shared steer-ratio selection, driver override, torque clipping, safety checks,
inactive reset/history behavior and single output LPF are preserved. Optimized
lane changes suppress feedforward (including modeled EPS damping) for either
controller and fade it back in afterward. No extra rate damping or device-yaw
blend is added to Firmware Controller.

## Source audit and verification boundary

Sources: JamesL787 `honda-eps-controller-update` ab868ea15561 (Clarity prediction
refit); `civic-command-delay` 59eb99e3183e (C020 calibration, load/P-I trims and
command delay); `c020-crawl-gate-civic-load` 74938539173c. The later
`crv-eps-calibration-fix` 898a319842cd was checked: its relevant C020 calibration
and load remain the same. Its CR-V/radar/model updates are outside this change.

The Civic crawl gate/friction-width schedule is included. The older Clarity
constant-R6 model from the Civic branch is not imported. No unmeasured TEG yaw
calibration is added, and neither controller is converted to live car-yaw feedback.
The C020 high-speed envelope is firmware-derived; the original source drive did
not validate its high-speed rail.

Host checks validate numerical parity, profile admission, shared schedule wiring,
lane-change bypass and generated Sunnylink definitions. They do not replace native
C4 tests, recorded-drive replay or progressive road validation. Do not promote
this patch to release branches or call the TEG placeholder validated on this basis.

## Rate feedback (R6)

R6 per published deg/s is angle-dependent on every image. The firmware's R6 is the pre-table column rate (flat
against the 0x18F rate on both cars with telemetry), scaled by NORM (1650 on every PTM build) and the motor-to-angle
constant (3121 in every image), while the feedforward differentiates the published angle, which comes out of each
image's A table. Per published deg/s, R6(angle) = -122 x (A-table centre divisor / 16384) x (A-table slope ratio).
Against telemetry (0.1 s angle derivative): Clarity within 0.6% at centre and 2.7% at every angle; C020 within 0.4% at
centre but 5-10% high past 60 deg, so the C020 and the TGG-A120 (same A table) use the C020's measured curve. The
C120, Insight and CR-V use the A-table model. The single constants used before (-173 C020, -138.4 CR-V) were angle
averages against the 0x14A rate, about 12% too strong at centre and 8-18% too weak in big turns. The column loads
were all measured with the Clarity's recipe (firmware output on every engaged, unpressed frame with the scale word at
or above 240, so resting-hand turns count; 2 deg/s friction knee; inertia term fitted, not deployed); the Insight,
whose build has no telemetry, from the firmware law rebuilt from its sent E4 with a driver-torque cut for the gate.
