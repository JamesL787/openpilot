# H020 Honda EPS controller port for LiMing's C3XL `res`

Status: **local, opt-in prototype; H020 firmware calibration with a transferred TGG-A120 vehicle baseline.**
No device installation, firmware flash, GitHub publication or message to LiMing was performed.

## Verified inputs

- Controller source: JamesL787/openpilot `ns-bosch-radar-testing`, commit `92428ab490b3085ea523f79cc6a32d392a057b56`.
- Target base: `https://jihulab.com/mr-one/openpilot`, `res`, commit `01e22f5921d9dfd49235f5867f54d9ec0bdccbaf`.
- LiMing's Drive archive: `res_code_fixed.tar.gz`, file ID `1bFFZFSE1Jn_xaEiUPaMc3BQ5hFknTQdy`, 179,039,337 bytes.
- Archive SHA-256: `9e66df6605d5b0039b6c8763f485839b72d7968ebb30c42f4de9e1bccb0d3974`.
- All **443 common `.py`, `.capnp`, `.h`, and `.sh` source paths** compared between his archive and public `res` have identical blob hashes. This does not establish equality of dependencies omitted from his archive, or of every binary on his device.
- The archive contains `selfdrive`, `cereal`, `common`, and `tools`; it is not a complete installable checkout. In particular, `cereal/car.capnp` points into an omitted `opendbc_repo`.
- `common/version.h` says 0.10.1. Source uses the `CP_SP` constructor, old `LatControl.update` argument order and older global PID API. The archive includes Python 3.12 compiled artifacts. This is not the 2026 `3xl` codebase inspected previously.

## What is ported

The numerical `HondaEpsFirmwareFeedforward` / `HondaEpsLateralCore` is copied from the source branch. Only two imports in that file change: geometry comes from the H020 module, and PID comes from a private copy of the source branch's PID. The old global `common/pid.py` is unchanged.

A res-specific `LatControlHondaEps(CP, CP_SP, CI)` adapter uses the existing PID log schema and update signature. It needs no StarPilot capnp schema, new Honda flags, new Params keys or compiled changes. The adapter preserves res's inactive reset and steering-pressed decisions. It uses the source default 300 deg/s desired-angle slew, initialized at the measured wheel angle on engagement, and rejects nonfinite inputs with zero output/reset. This wrapper is an adaptation: it does not port the source branch's StarPilot telemetry, command-delay head selection, short-dropout state retention, or its separate override detector/fade. Those require additional integration if desired.

H020 PTM stock/modified EPS strings are added only to Civic Bosch fingerprints, consistent with LiMing's reported fingerprint. The interface supplies a **linear `[0, 3840] -> [0, 3840]`** map after res's older nonlinear modified-EPS block, but only when the new controller is explicitly enabled for exact `39990-TEA,H020` firmware. PID uses the donor Civic Bosch/TGG four-point base schedule (P 0.018/0.024/0.048/0.060, I 0.006/0.008/0.016/0.020, at 0/25-mph-minus-0.001/25-mph/50-mph), with the donor's P/I speed-band trims. The core supplies feedforward, so the legacy kf is zero in this mode.

The existing Panda, safety code, AGNOS manifests, launchers, manager, camera code, model assets and global PID are unchanged. Existing non-H020 cars and disabled configurations retain the original res tune. Safety and driver-fault gating remain res's responsibility and are not bypassed.

## Firmware calibration: H020, not C020

Fields were read from the original 2026-10-11 H020 PTM binaries for both Trk4250 and Trk3200:

| Quantity | H020 value / address |
|---|---|
| Live row | 0 in all five searched variant records, `0x4B418 + n*0x59 + 0x0F` |
| R5 key axis | `(0,226,311,495,656,887,1108,1552,1774)` at `0x13794` |
| R5 values | `(0,1926,4938,8455,12036,15926,20138,26955,30000)` at `0x13812` |
| P key axis | `(3,173,441,665,887,1104,1317,1610,1774)` at `0x13AE2` |
| P values | `(117,148,184,220,245,257,263,265,265)` at `0x13B60` |
| Key clamp | 1663 |
| Speed envelope | axes at `0x135E4`, values `0x13662`; 1774 through 100 km/h, 1552 at 120, 1108 from 160 |
| Table A | H020's original `0x1306C` / `0x130A8`, retained by PTM |
| R6 | -153.74 at centre, computed from Table A and NORM1650 using the source controller's estimator model |

The R6 model is firmware-derived, not measured on an H020 drive. Its common motor-rate constant is inherited from the source controller's multi-car estimator model. The source model's assumptions still need an H020 route check.

The two PTM binaries differ only at tracker-1 `0x1378E/F` and their checksum words. Their static control-law fields match. Full image/RWD hashes are in `h020_firmware_evidence.json`. The code does **not** change or create EPS firmware.

The EPS version string cannot distinguish these builds. `ptm_build` is the owner's declaration of the installed image, not a cryptographic ECU readback.

## TGG-A120 vehicle baseline and remaining checks

Per the user's instruction, the vehicle baseline now comes from **Civic TGG-A120**, replacing the initial C020 donor. The source calibration records a column-load fit on routes `83ccc6a9a4e14d0b/0000000b-00000010` (73 minutes engaged/unpressed, R² 0.794, held-out R² 0.558–0.840) and a GPS/yaw-fitted rack map on those routes. Those results belong to the donor car; this change reuses the pinned fitted parameters and does not claim a fresh replay of its raw logs.

The H020 and TGG stock images in the original firmware evidence have byte-identical **A and B X/Y arrays** (four 60-byte comparisons at 0x1306C/0x130A8/0x130E4/0x13120). The earlier H020 work also traced matching controller functions. This supports choosing TGG as the donor; it does not establish that every mechanical or alignment parameter is identical.

Transferred: TGG column-load coefficients (including its bias and roll term), yaw-fitted rack table, and the effective Civic Bosch/TGG residual PID schedule/trims. Retained: H020's command/P axes, R5 values, clamp, speed envelope, firmware geometry, R6 derivation and supported image hashes. The donor's bias and roll terms remain explicit assumptions on H020, as do the rack and load. Details and exact values are in `h020_tgg_donor.json`.

The TGG donor itself inherits timing and P/I trims from C020. Its command/model timing is not an independently measured H020 result. We retain res's model pipeline without adding TGG's 0.15-second command delay or its model schedule. No new H020 measurements are claimed. The absence of H020 logs does not prevent preparing this donor-based starting calibration; it limits what can be concluded about its actual behavior on H020.

No extra command delay or new model-delay schedule is injected. The old res plan timing differs from the source branch, so its schedules cannot simply be transplanted.

Calibration workflow, adapted from the source `tools/lateral` scripts:

1. Obtain complete H020 rlogs from at least two separate drives, plus the exact installed PTM filename/hash and the full CarParams/carFw report. Include GPS, CAN 0x94, sendcan 0xE4, modelV2, carControl, controlsState, carState and liveParameters. Record which settings/build were used. Existing logs are useful before any prototype trial.
2. Check the platform and firmware first. Full ECU fingerprints may need additional entries beyond the EPS; do not force a fingerprint or ignore dashcam mode.
3. Fit yaw scale against GPS on each drive; compare left and right turns. Confirm the 0x94 bus from the logs. The tools require the bus instead of silently selecting a sibling's.
4. Fit the rack map on the GPS-checked yaw scale. Require at least 300 seconds of turning across angle/speed bands, both directions, then check held-out drives. The tool retains an inherited Clarity wheel-to-yaw lag assumption; measure it on H020 before treating the fit as final.
5. Fit column load from reconstructed firmware output (`--source e4`), since the H020 PTM has no dedicated EPS telemetry. The H020 adaptation uses d(Table-A angle)/dt rather than treating the Table-B published rate as that derivative. Compare held-out routes and sensitivity to driver-torque gating. Reconstructed output remains a model-based target, not direct motor-current ground truth.
6. Check plan timing with the measured yaw scale/right correction. H020 VSA latency defaults to zero in the timing tool; report that assumption or supply a measured `--vsa-latency`. Separate model perception/plan errors from controller under-delivery. Do not tune delay from a single steady curve.
7. Validate tracking, command spectrum, saturation, overrides and low-speed noise; compare the donor assumptions and update the provenance with route IDs, fit/holdout results and assumptions. A sibling-model simulation alone cannot validate this car.

Run tools from the checkout root, with its own matching environment and schemas:

```sh
export PYTHONPATH="$PWD:$PWD/opendbc_repo"
python3 tools/lateral/fit_yaw_scale.py --bus 1 '/path/to/route1/rlog*' '/path/to/route2/rlog*'

# Substitute the measured scale and right correction; these variables are deliberately not prefilled.
python3 tools/lateral/fit_rack_map.py --car HONDA_CIVIC_BOSCH --vgr civic_tea_h020 \
  --bus 1 --scale "$H020_YAW_SCALE" --right "$H020_RIGHT_CORRECTION" \
  '/path/to/route1/rlog*' '/path/to/route2/rlog*'
python3 tools/lateral/fit_column_load.py --source e4 --calibration civic_tea_h020 \
  '/path/to/route1/rlog*' '/path/to/route2/rlog*'
python3 tools/lateral/plan_timing.py --bus 1 --scale "$H020_YAW_SCALE" \
  --right "$H020_RIGHT_CORRECTION" '/path/to/route1/rlog*'
```

The tools print fit results; they do not silently deploy calibration changes. The TGG-based starting calibration is prepared without requiring H020 logs; those logs would validate and refine the transfer. The prepared example is disabled until explicitly configured for a reviewed test.

## Activation and rollback mechanism

`tools/lateral/h020_config.example.json` is a template, not a file automatically installed to `/data`. The gate reads `/data/honda_eps_h020.json` at interface/controller startup. It requires JSON boolean `enabled: true`, a recognized `ptm_build` (`20261011-trk4250` or `20261011-trk3200`) and `calibration_stage: "provisional"`. The ordinary disabled/missing/bad configuration selects the original res controller.

Configuration changes are **not live tuning**: interface/CarParams generation and controlsd must restart together while offroad, so the map and controller agree. Then the read-only `tools/lateral/inspect_h020.py` reports firmware, fingerprint, PID/map and whether the new controller would be selected. Do not infer successful activation from a UI slider. A stock H020, wrong car, wrong map, or unknown build must not select the new controller.

Rollback means disable/remove this explicit config and restore the original branch/patch, then restart the existing software while offroad so CarParams is rebuilt. Disabling a config without rebuilding CarParams can leave the previously generated tune in memory. This port does not provide an automatic install/flash script or execute a launcher.

## Verification and handoff limits

**37 tests passed** on the Mac using Python 3.12. All four fitting/timing CLIs also passed import/`--help` smoke checks. The original numerical core was verified byte-for-byte apart from the two import substitutions; the private PID copy is exact and res's global PID is unchanged.

Tests run against the port checkout's **actual res CarParams/PID-log capnp schemas**, not the ns-bosch-radar-testing mirror. They cover configuration gating, unchanged unrelated vehicles, exact H020 map selection, firmware inversion and R6 rail, geometry round trips, numerical bounds, override/inactive behavior, invalid inputs and integration wiring. The copied numerical core retains the source implementation, and its PID API is isolated.

No C3XL boot, complete on-device import/build, vehicle fingerprint, installed firmware hash, CAN-output trace or road behavior has been verified. Public res supplies dependencies omitted from the archive; any unshared device-local dependency edits must still be compared before installation. Heavy assets/models were excluded from the archive, so the patch/overlay is not a complete replacement firmware image.

The branch is prepared locally from the verified res commit. The source `ns-bosch-radar-testing` checkout was not modified. Publishing or sending a GitHub link remains a separate action; no public branch or PR is claimed here.
