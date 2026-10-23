# H020 Honda EPS controller port for LiMing's C3XL `res`

Status: **local, disabled-by-default prototype; A–E fixes plus an offline H02B rev-b candidate and matching controller profile. Calibration remains unvalidated on H020.**

The owner subsequently requested a firmware rebuild and selected **TGG response + Clarity limits**, superseding the earlier calibration freeze. The new profile is distinct from legacy H020. Full evidence, hashes, table comparison and reproduction are in `tools/eps/h020_revb/README.md`. It is not represented as ready for vehicle testing.
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

A res-specific `LatControlHondaEps(CP, CP_SP, CI)` adapter uses the existing PID log schema and update signature. It needs no StarPilot capnp schema, new Honda flags, new Params keys or compiled changes. It now includes the source modified-EPS press detector: opposing torque/low command/already recognized presses act immediately, while command-aligned raw presses have the source 0.28-second filter. This signal only controls feedforward/integration; res's driver-fault and actuation gating are unchanged. It also retains model state/integral through up to 0.1 second inactive, while returning **zero output on every inactive frame**, and hard-resets after longer dropouts.

The wrapper sets output-filter time constants to the source wrapper default of 0.1 second in all three speed bands (the numerical core alone defaults to 0.07/0.05/0.01). It uses the source default 300 deg/s desired-angle slew but deliberately initializes it at the measured wheel angle on engagement, an adaptation rather than source-identical behavior. Nonfinite inputs produce zero output/reset. StarPilot telemetry, source command-delay head selection, live settings and the separate override fade are not ported. res has a different model pipeline; no new delay is assumed.

Only the **modified** `39990-TEA,H020` and locally generated `39990-TEA,H02B` EPS strings are added to Civic Bosch fingerprints. The earlier added stock-H020 entry was removed after audit. This is a provisional platform association; a real exact full-car firmware fingerprint is required. Bosch versus Nidec is unverified without actual CarParams/carFw from this car: the TEA prefix appears under both Nidec Civic and Civic Bosch. The port does not force a platform. The interface supplies a **linear `[0, 3840] -> [0, 3840]`** map after res's older nonlinear modified-EPS block, but only when the new controller is explicitly enabled with a build declaration matching the queried H020/H02B firmware family. PID uses the donor Civic Bosch/TGG four-point base schedule (P 0.018/0.024/0.048/0.060, I 0.006/0.008/0.016/0.020, at 0/25-mph-minus-0.001/25-mph/50-mph), with the donor's P/I speed-band trims. The core supplies feedforward, so the legacy kf is zero in this mode.

The existing Panda, safety code, AGNOS manifests, launchers, manager, camera code, model assets and global PID are unchanged. The new tune is scoped to the explicit H020 configuration. Removing the added stock entry restores the baseline fingerprint database for stock-H020 cars; the added modified entry still intentionally changes matching for that modified version. Safety and driver-fault gating remain res's responsibility and are not bypassed.

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

The two PTM binaries differ only at tracker-1 `0x1378E/F` and their checksum words. Their static control-law fields match. Full image/RWD hashes are in `h020_firmware_evidence.json`. These describe the legacy October 11 images. The new offline builder creates separate H02B candidates; it never modifies these input files. See the rev-b report for all new output hashes and changes.

The EPS version string cannot distinguish the two tracker variants within a family. H02B is a separate family from legacy H020; its live query result has not been observed. `ptm_build` is the owner's declaration of the installed image, not a cryptographic ECU readback.

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

`tools/lateral/h020_config.example.json` is a disabled template, not a file automatically installed to `/data`. card reads `/data/honda_eps_h020.json` once per startup. It requires JSON boolean `enabled: true`, recognized `ptm_build` (the two October 11 legacy declarations or `20261022b-tgg-claritylimits-trk4250` / `20261022b-tgg-claritylimits-trk3200`) and `calibration_stage: "provisional"`. Missing/invalid/disabled configuration retains the ordinary res path for legacy/stock/unrelated EPS; only the newly introduced H02B family is marked dashcam-only because it requires the new matching profile. Configuration edits are **not live tuning**: restart card/controlsd together offroad through the normal manager lifecycle, which clears CarParams at manager start/onroad transition.

When enabled, card bypasses CarParamsCache and the platform bundle to obtain fresh identification, shares the one config snapshot with interface initialization, then validates final CarParams **after** real `setup_interfaces` and later startup settings. If no H020 PTM EPS response is present (stock reflash, a different EPS, or a different car), it logs a loud error, treats the H020 config as disabled, and publishes the **original res tune/controller**. The H020-specific interface block never changes those vehicles' tunes. It does not create a new activation record for that fallback. Disabled/missing config retains the ordinary res path and creates no runtime guard.

If an H020 PTM response **is** present, wrong platform, dashcam/fuzzy/non-firmware identification, incompatible torque/NNLC settings, or a changed final PID/map still refuse activation. Conflicting EPS responses including H020 PTM also refuse rather than pretending to be a stock rollback. An environment-forced fingerprint is rejected because its source is `fixed`. The port never forces a Bosch fingerprint or adds speculative firmware entries.

Fingerprint blockers list Civic Bosch ECUs as matched, mismatched or missing, with required/optional-when-missing labels. The comparison uses the existing merged Honda FW database and res's brand, logging, address/subaddress and non-essential ECU rules. A missing optional ECU is allowed by res; a present optional ECU must match. This diagnostic explains the gate; it does not loosen it, establish that the gate is satisfiable on this car, or prove Bosch hardware. `tools/lateral/inspect_h020.py` displays the same ECU report and blocker, even if card refused before publishing an activation record. A stock/unrelated fallback is reported as an ignored config rather than a blocked car.

After H020 validation, card atomically writes `/data/honda_eps_h020_activation.json` containing the config snapshot and SHA-256 of the exact serialized CarParams **before publishing CarParams**. controlsd loads the matching record once and passes that snapshot through selection/construction. All activation reads require the original raw CarParams bytes: neither reader nor previously written builder is reserialized. A capnp copy can have a different serialized layout/hash, so copying and rehashing is not a substitute for the published bytes. Missing/corrupt/mismatched/disabled records on a tuned H020 map still block startup.

**Runtime consistency guard:** only an active H020 port checks Params CarParams and its activation record at most once per monotonic second. A changed/missing CarParams, changed build/config snapshot, missing/corrupt activation record or other activation mismatch latches lateral control inactive and returns zero torque. It emits an error immediately on detection and every five seconds thereafter, requesting an offroad controlsd restart. It never switches to an ordinary PID/torque controller mid-run and never unlatches because files were restored. A card-only restart with an identical CP/config is compatible. The polling detection latency is up to one second, plus scheduling delay; it is not an instantaneous interprocess handshake. This guard is offline-tested and does not make independent process restarts a supported vehicle procedure.

Run the read-only `python3 tools/lateral/inspect_h020.py` from the checkout root for requested/latched config, fingerprint source, ECU match details, PID/map, errors and restart requirement. It exits 2 on an activation blocker. `ptm_build` remains an **owner declaration, not an ECU readback**; the sidecar is a consistency record, not firmware or physical-platform attestation.

Rollback: disable/remove the config and restart card/controlsd together offroad through the normal manager lifecycle, rebuilding CarParams. Reflashing stock with a stale enabled config now falls back to stock res behavior, while an already running H020 controlsd latches zero after detecting the new CP. Deleting the operator config alone is not a live tune change. This port executes no installer/launcher/flash script.

## Firmware model limitations retained after audit

The supplied H020 PTM command row retains TargetMap-D values on H020's non-uniform native key axis. Direct differences give R5/key slopes **8.522, 35.435, 19.114, 22.242, 16.840, 19.059, 15.354, 13.716**. The 226–311-key segment is about 1.96 times the 18.04 linear reference. The static feedforward inversion follows this row; it does not make the residual angle PID's plant gain uniform. The TGG-donor PID trims and load were fitted on a different image, so their loop gain does not transfer to this H020 command map. Legacy values remain preserved. The subsequent owner-authorized H02B candidate corrects the selected command/P data response to TGG rev-b and uses Clarity limits, with a separately extracted `H020_REVB` profile. That offline data correction does not validate TGG donor load/trim transfer or physical loop gain on H020. The independent calibration audit identifies the 10-16 `PTM_FIX_FAMILY` rev-b rebuild as correcting eight other images, **not H020**. No firmware table or residual-gain redesign was made in the A–E implementation commit `86aa8c485`; the separate H02B candidate follows the later request. Residual donor trims remain unchanged.

The forward model also assumes unity pre-table shaping. The supplied H020 trace leaves blend inputs/gate flags unresolved. Identical estimator code and A/B geometry tables do not establish the live gate values or H020's motor-to-angle constant. Row 0 is verified in the supplied binaries, not in running-vehicle telemetry. These remain explicit model assumptions. The actual car's full CarParams/carFw and installed image identity are still absent. H020 route/telemetry evidence is needed to resolve these questions; existing TGG fit values alone do not resolve them. The package is ready for another offline audit, **not represented as ready for vehicle testing or as an H020-validated calibration**.

## Verification and handoff limits

**120 tests passed** in the current rev-b follow-up. The preceding A–E revision had **86 tests passed** with the requested Python 3.12 interpreter and `tools/lateral/run_h020_tests.sh`. New regressions fail against the unchanged 128e205e0 implementation (15 failed, 71 passed); both Honda sign-chain cases already pass there and justify no detector inversion. The four fitting/timing CLIs had help/import smoke checks in the previous revision; they were not changed or re-audited in this implementation-only follow-up. The original numerical core is byte-for-byte source-identical apart from the two import substitutions; the private PID copy is exact and res's global PID is unchanged.

Tests use the port checkout's **actual res CarParams/PID-log capnp schemas**. They run the real Honda `get_params`/`get_params_sp`, real Sunnypilot `setup_interfaces`, real Honda CarController/CAN packer, override/dropout behavior, firmware inversion, numerical bounds and activation-record errors. They execute the actual card and controlsd initializer function bodies compiled from their AST, with transport/native Params/unrelated services replaced for Mac execution. Tests reproduce torque/NNLC overwrites and verify publication is blocked, enforce cache/bundle bypass, remove config/record files between startup stages, check active/inactive E4 sign/request behavior, execute real CarState sensor decoding, and execute real controlsd `state_control` across card-only restarts and stock rollback. This is meaningful offline startup coverage, not a full daemon or device boot. The former source-text wiring test is removed.

No C3XL boot, complete on-device import/build, vehicle fingerprint, installed firmware hash, on-device CAN-output trace or road behavior has been verified. Public res supplies dependencies omitted from the archive; any unshared device-local dependency edits must still be compared before installation. Heavy assets/models were excluded from the archive, so the patch/overlay is not a complete replacement firmware image.

The branch is prepared locally from the verified res commit. No command edited the source `ns-bosch-radar-testing` checkout; source comparisons were read-only and its requested Python interpreter was used. The rev-b follow-up adds a build registry, firmware builder/verifier and matching calibration profile. Legacy calibration values, fitting tools, the numerical core/private/global PID and geometry/rack modules are unchanged from `86aa8c485`. New images are offline candidates; input firmware files are unchanged. Publishing or sending a GitHub link remains a separate action; no public branch or PR is claimed here.
