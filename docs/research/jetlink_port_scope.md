# Jetlink openpilot-side port to ns-bosch-radar-testing

Scoped 2026-10-07. This is an implementation scope, not a completed port or hardware qualification.

**Update 2026-10-07: phase 1 is implemented on `ns-bosch-radar-testing` (uncommitted at the time of writing). See *Implementation findings* at the end and `docs/JETLINK.md`. Nothing has been run on a comma or against a host.**

## Recommendation

Port Zoompilot's API-2 adapter architecture and lifecycle hooks, keeping this branch's model runner, action calculation, publication path, and Bosch radar code. Start with the pinned Jetlink default big model over USB, with the selected local small model as fallback. Add a translated model catalog and iOS support after the runner seam and failover pass device tests.

This is a medium-sized integration, not a clean cherry-pick. The adapter is reusable, but our ModelState, Params API, model catalog, accelerator status, and control engagement state differ. No Honda/opendbc/panda safety changes are expected for this scope; radar timing and lead behavior still require replay validation.

## Reviewed revisions

| Repository | Revision | Purpose |
| --- | --- | --- |
| Target openpilot | `02f16c5b57287d8bf2c6b7529053547b66ad5ba4` | Current local `ns-bosch-radar-testing` HEAD |
| Zoompilot `develop` | `02be6b631d069d8542967916d56bd8b1fc3c744c` | Current openpilot-side integration |
| Jetlink | `4b747aebad3d8d96ab26d76f1668f2b2ecb1b667` | Submodule pinned by that Zoompilot revision; v0.8.5 |
| Tinygrad | `f6fc4e3f2c3db5fae1e19cbfbc3ad9fc579a12ae` | Same declared revision on both sides |

Jetlink remote HEAD was `e0a22763e47d401d5f0600efc148cc46abb24ac0`; use the Zoompilot pin first, not an independently updated server/package. `jetson-trt` still exists, but current `develop` is the reviewed donor. Tinygrad's matching revision reduces compatibility risk; our vendored tree and artifacts still need testing.

Sources: [Zoompilot adapter](https://github.com/zoompilot/zoompilot/blob/02be6b631d069d8542967916d56bd8b1fc3c744c/openpilot/sunnypilot/jetlink_adapter/__init__.py), [Jetlink interface](https://github.com/zoompilot/jetlink/blob/4b747aebad3d8d96ab26d76f1668f2b2ecb1b667/jetlink/openpilot/interface.py), [joining runner](https://github.com/zoompilot/jetlink/blob/4b747aebad3d8d96ab26d76f1668f2b2ecb1b667/jetlink/openpilot/joining.py).

## Architecture to retain

- `jetlinkd` owns the USB gadget across offroad/onroad transitions; provisioning runs separately offroad. Manager restarts the owner with crash backoff.
- Camera capture, calibration, NV12 warp, parsing, action calculation, message publication, planning, radar fusion, and control remain on the comma. Warped frames and packed inputs go to the external inference host; output arrays return.
- `prepare()` runs before realtime scheduling. `attach()` wraps a warm local small runner. The wrapper joins asynchronously and promotes the big runner only when nothing is engaged.
- Missing package, mismatched API, missing warp, failed provisioning, and failed inference leave or return to the local small model. A present Chestnut excludes Jetlink.
- Link shutdown is requested before device poweroff, with a bounded 25-second wait. Status and errors feed UI/offroad alerts.

## Concrete changes

| Workstream | Target files | Required adaptation |
| --- | --- | --- |
| Adapter and dependency | New `starpilot/jetlink_adapter/`; package/vendor pin; `pyproject.toml`; launch/release packaging | Retain lazy imports, API check, absent-package behavior, guarded hooks, license notices. This checkout vendors dependencies and has no `.gitmodules`; choose a pinned vendor/package strategy consistent with deployment rather than copying the donor's complete submodule setup. |
| Params | `common/params_keys.h`; adapter | Declare link INT (off/usb/ios), progress JSON cleared at manager start, persistent spec and pointer JSON, optional phone-charge BOOL, and offroad error JSON. Our `Params.put(key, value)` has no `block=` keyword: implement the adapter's blocking/nonblocking contract using `put`/`put_nonblocking`. `get` already decodes typed values. Verify owner file reads against this branch's Params root/prefix rules. |
| Process lifecycle | `system/manager/process_config.py`; existing process API | Add optional `jetlinkd` across ignition states, excluded when Chestnut is present. Port restart/backoff behavior after checking our process class semantics. A dead optional owner must not cause permanent `processNotRunning` while the local runner remains healthy. |
| Warp/build | `selfdrive/modeld/SConscript`; adapter build helper; release/build entry points | Capture dedicated Jetlink warps for 1928x1208 and 1344x760 cameras into fork-owned paths. Our `make_warp` requires `frame_skip`; choose policy-history mode explicitly and preserve the four-input call convention and packed output. Rebuild against our Tinygrad tree; do not reuse donor pickles. Include build dependencies and artifact packaging. |
| Runner seam | `selfdrive/modeld/modeld.py`; new local/remote facade in adapter | Translate signatures, attributes, camera keys, inputs, generation metadata and reset semantics as detailed below. Keep the existing camera/desire/action/publish loop. |
| Hardware lifecycle | `system/hardware/hardwared.py`; `system/hardware/usb.py` consumers | Report unusable link reason, request host shutdown, preserve Chestnut exclusion. Verify USB gadget/ADB ownership, unplug cleanup and branch switching on the device. |
| Status/events | `cereal/custom.capnp`; `selfdrive/selfdrived/selfdrived.py`; `starpilot/controls/lib/starpilot_events.py` | Add backend/readiness/running/handover information to `starpilotModelV2` at new field ordinals, with defaults supporting old logs. Port available/link-lost/settling behavior to our event system. Keep UsbGpu params specific to local hardware. |
| User controls | Existing driving-model settings in `selfdrive/ui/layouts/settings/` and `selfdrive/ui/mici/layouts/settings/driving_model.py`; Galaxy model UI if exposed there | Off/USB setting, progress, backend, selected/active model, unavailable reason and handback warning. Setting changes parked only. iOS/charge controls follow later. |
| Model catalog, phase 2 | `starpilot/assets/model_manager.py`; adapter; model settings/Galaxy components | Translate NRDR model identities to supported comma source commits and ONNX pointers. Jetlink does not execute our AMD/QCOM pickle artifacts. |

### Runner seam is the critical path

1. Our `ModelState.run(bufs, transforms, inputs, prepare_only, after_output_sync=None, shared_warp=None, *, blinker_on=False)` differs from Jetlink's `run(..., after_enqueue=None)`. Direct attachment would pass a callback into `prepare_only`, lose our extra arguments, and fail on remote attributes. Provide a local facade for Jetlink and a branch-facing wrapper for modeld; explicitly distinguish callback timing.
2. Our `_runner_frame_args()` reads `road_key`, `wide_key`, `off_policy_enabled`, optional input arrays and other metadata. Jetlink uses `img`/`big_img` and always needs `action_t`; its joining wrapper exposes the small model's `numpy_inputs`. Construct canonical remote inputs independently so a local profile lacking `action_t` cannot omit it from a remote frame. Cover desire-key mapping, transforms and traffic convention.
3. Our action path reads `mlsim`, `is_v9`, `is_v14`, `is_v15`, `is_v16` and branch-specific smoothing/toggles. Jetlink's remote state does not define these. Supply validated metadata for the active remote model; never infer it from the fallback profile. Run returned arrays through our parser/fill functions and verify required output heads and shapes.
4. Our `_reset_state()` allocates new queues; it is unsuitable for immediate failover after JIT capture. Jetlink's generic reset zeros device queues and `numpy_inputs`, but must also cover our `npy` views, `full_prev_desired_curv`, fused/split/off-policy state, and blinker/desire history. Pre-capture an in-place reset and confirm buffer identities remain stable.
5. Preserve publications of `modelV2`, `drivingModelData`, `cameraOdometry`, and `starpilotModelV2.turnDirection`. Target schemas do not provide the donor's `modelV2.big`/`modelDataV2SP.acceleratorState` combination; publish explicit custom backend/state instead of importing the donor schemas wholesale.
6. Track handovers, reset applicable frame-drop history, previous action/smoothing and temporal publication state according to replay evidence. Our `_should_publish_model_output()` currently suppresses dropped-frame output; integrate Jetlink handover semantics deliberately so fallback is neither silently dropped nor published with misleading validity.
7. Initial arbitration: detected Chestnut retains the native GPU path; otherwise enabled/usable Jetlink wraps the local small model; otherwise local small only. Model Laboratory remains a Chestnut feature. Do not route remote inference into the dual-AMD/shared-warp path.

### Engagement and timing

Map Zoompilot's `carControlSP.mads.enabled` to this branch's always-on lateral state (`starpilotCarState.alwaysOnLateralEnabled`) plus normal `carControl.enabled`. Treat stale/invalid engagement services as engaged. Check paused AOL semantics: `latActive == false` alone is not sufficient permission to promote a different model.

The donor blocks engagement for about one second after promotion and provides handback/ready alerts. Its settling window also suppresses selected transient localization/communication checks. Adapt narrowly and test the actual invalid-pose sequence; do not copy broad error suppression without verifying that a real localization failure remains visible.

At the reviewed Jetlink pin, frames can reuse the preceding output after a 46 ms hold budget, repeated holds trigger demotion, inference timeout is 200 ms, and a filtered dropped-frame ratio over 0.0075 triggers handback. These are donor policies, not measured guarantees on our branch. Record remote-output age and held-frame counts alongside camera timestamps so replay can distinguish a fresh inference from a held plan. Measure complete frame latency, including warp, transport, parsing and fallback.

### Model selection

Do not set Jetlink's `big_model` key directly to `ActiveBigModel`: ours is a model-key STRING; Jetlink expects JSON `{ref, displayName}` with a 40-hex comma commit. Likewise our NRDR manifest is not its `{bundles}` catalog.

For phase 1, use `Keys.big_model=None`, `Keys.catalog=None`, `catalog_selector=0`, and the pinned package default: Cinque Terre V3, source ref `bf3e3631b3f91d92a1020a5e0dd4298b93ff4244`. Validate this model's parser/action compatibility before enabling it. Keep Jetlink downloads in a dedicated directory under our model root to prevent model-manager pruning.

For phase 2, introduce separate translated JSON params and an explicit supported-model allowlist. Resolve source identity/ONNX availability for each entry; mark unsupported custom NRDR models unavailable rather than substituting a different model. Keep requested and actually running model identities distinct through handback.

## Delivery and estimate

Planning estimate for one engineer familiar with this fork, with a comma and compatible Jetlink host available; not a measured schedule:

1. **Adapter, packaging and warp proof: 1–2 days.** API conformance, absent-package behavior, Params translation, owner lifecycle and camera-specific QCOM warp captures.
2. **Modeld seam and deterministic failover: 2–4 days.** Facades, parser/action metadata, in-place reset, native-GPU arbitration and fault-injection/replay coverage.
3. **Status, events, basic UI and device qualification: 2–4 days.** Optional-process behavior, parked promotion, AOL gating, unplug/reconnect, shutdown and radar/latency checks.
4. **Catalog translation and iOS: another 2–4 days**, dependent on source-model metadata and device access.

Total first usable USB port: approximately **5–10 engineering days**. Hardware-only issues or unsupported output formats can extend this. Keep each stage reviewable in a separate change; phase 1 should ship off by default.

## Validation / acceptance

- Port relevant donor adapter, seam, queue, Tinygrad and warp-build tests; adapt accelerator-event tests to our schema and engagement state. Existing model fallback, camera-offset, lateral smoothing, model-laboratory and model-pipeline tests must remain green.
- Fake-link tests: package absent/API mismatch; unavailable or malformed warp/spec; malformed/missing response; non-finite output; timeout; slow/held frames; device unplug; owner crash/restart; repeated reconnect; native GPU exclusion.
- Each failure must leave the small runner publishing with valid metadata, no uncaught frame-loop exception, and bounded fallback work. Reset must preserve JIT buffer identity and clear all recurrent history; no inference/download/build waits on manager or UI threads.
- Promotion must be blocked during normal engagement, active or paused AOL, and stale engagement inputs. Demotion must be possible while engaged. No-entry/ready/link-lost events must follow actual backend state.
- Replay the branch's Bosch radar routes through small, remote and handover sequences. Check lead selection, `mdMonoTime`, lead probabilities, model-based ego velocity, longitudinal target and action continuity. Radar consumes `modelV2` at 20 Hz; no expected radar implementation change, but held outputs can alter fusion inputs.
- On comma hardware, test both camera geometries where devices are available. Measure p50/p95/p99/max complete loop times, output age, drop/hold rate and fallback latency during a sustained thermally loaded run. Acceptance requires sustained 20 Hz without persistent lag or repeated handbacks; exact latency bounds should be set from the first bench capture and consumer deadlines.
- Test ignition cycling, settings changes parked, ADB coexistence/recovery, Chestnut attachment, updater/release packaging and bounded host shutdown. Real device qualification remains outstanding until the port exists.

## Scope boundary

Includes the fork adapter, comma-side package/runtime, lifecycle/build hooks, status/events/UI and model identity translation. External Jetlink server implementations, host engine compilation changes, new network transports, dual-remote Model Laboratory, and changes to Honda CAN/radar/safety code are outside this initial port.

Inspection used isolated donor checkouts under `/tmp`. Existing target work was preserved; no runtime source was changed and no port tests were run for this scoping document.

## Implementation findings (2026-10-07)

What the implementation found when it checked this document against the code. Items marked **changed** altered the plan.

### Revisions

Verified: target `02f16c5b57`, Zoompilot `02be6b631d`, Jetlink `4b747aebad` (0.8.5, `API == 2`, wire protocol 3), tinygrad
`f6fc4e3f` (`tinygrad_repo/TINYGRAD_COMMIT`). The vendored package is a byte-for-byte copy of that Jetlink revision plus three
reviewable additions (`starpilot/third_party/jetlink_repo/LOCAL_MODIFICATIONS.patch`, checked against the file by a test).

### Assumptions that held

* **Params.** `Params.put` has no `block`; the adapter maps `block=True` to `put` and the default to `put_nonblocking`. `get` already
  decodes by type. Params root/prefix rules agree with Jetlink's file reads (a test writes through `Params` and reads through
  Jetlink's `FileParams`). `Params.get_bool` default-trap does not apply: Jetlink reads the link setting as an INT file.
* **Camera.** `common/transformations/camera.py` gives 1928x1208 (tici/tizi) and 1344x760 (mici), the geometries of the committed
  `warp_<cam>_tinygrad.pkl` files. The fork's `make_warp(..., IMAGE_HISTORY_IN_POLICY)` returns the `(2, 6, 128, 256)` uint8 graph
  Jetlink sends, built through Jetlink's own capture on CPU for both cameras; the call convention (`big_frame, big_tfm, frame,
  tfm`) loads and runs.
* **Model identity.** The pinned model's input/output layout was read from the real ONNX (`404a18cf…`, 766 354 845 bytes; the same
  oid the LFS pointer at `bf3e3631` names) and is checked in a test. The `plan`, `action`, `lead`, `lane_lines`, … heads parse with this
  fork's `Parser` and publish through `fill_model_msg`.
* **Pruning.** `ModelManager` only deletes top-level files named like driving artifacts, so `<models>/jetlink/` is safe.
* **Packaging.** The release scripts keep third-party directories except root `third_party/` and root `scripts/`; the vendored
  package lives under `starpilot/third_party/` for that reason, with its root helper at `scripts/comma/` inside it.

### Assumptions that did not hold, and what was done

* **changed: owner restart.** The donor's `RestartingPythonProcess` watches for a dead `proc` in `start()`. This fork's
  `ensure_running` reaps a crashed process first and restarts it with no pause, so that logic would never fire. Replaced by
  `OptionalPythonProcess` (backoff recorded in `stop()`), found to have a bug in its first draft (`started_at` stale after a
  clean stop/start) by a test.
* **changed: shutdown.** The donor does the bounded host power-off in hardwared. Here the UI's power-off buttons write `DoShutdown`
  themselves and manager's cleanup stops `jetlinkd` right after, so the wait lives in manager's shutdown branch
  (`system/manager/accelerator_shutdown.py`), covering every writer. hardwared only raises the offroad alert.
* **changed: promotion gate.** `carControl.latActive == False` is not permission: always-on lateral pauses (brake, blinker,
  calibration) and resumes by itself. The gate reads `starpilotCarState.alwaysOnLateralEnabled` and `alwaysOnLateralAllowed`
  (armed-but-paused), and the car's AOL capability from `StarPilotCarParams`, so an armed flag on a car that cannot run AOL does not
  block forever. Unknown counts as possible. A blinker or lane change also blocks it.
* **changed: the swap's own stall.** Camera frames dropped during a swap reach modeld's drop filter on the next frames; Jetlink hands
  the large model back past a ratio of 0.0075, so a swap handed itself straight back (proved by mutation: removing the fix makes
  the loop test fail). The donor re-arms the filter's 10-frame warm-up with `run_count = 0`; so does this port.
* **changed: runtime model params.** `set_runtime_model_params` rewrites `Model`/`DrivingModel` (the user's selection). Pointing
  that at the external model would make a restart mid-drive come back to a key the manager does not know. Only `ModelVersion`,
  `DrivingModelVersion` and `DrivingModelName` follow the backend, written non-blocking on the frame loop.
* **changed: second tinygrad artifact.** The warp pickle is unpickled beside the loaded model. The Model Laboratory already
  evicts realized buffer UOps before loading a second artifact so the two do not hash-cons onto the same buffers; the attach does
  the same. (This is precedent, not a demonstrated aliasing on QCOM.)
* **changed: in-place reset.** Jetlink's reset clears `numpy_inputs` and the GPU queues by identity. This fork's ModelState keeps
  history in more places (`npy` views of the packed input including `prev_feat`, `full_prev_desired_curv`), and its own
  `_reset_state` allocates new queues. `LocalRunner` presents all of them to Jetlink's reset and `ModelState.pin_buffers()` makes
  `_reset_state` refuse after attach. Verified on real TinyJit queues: identities unchanged across repeated resets.
* **changed: validated model gate.** Added `validate_spec` to the vendored join so an unvalidated server model is refused before it
  is built, and `demote_invalid` so unusable output hands back through the same path as a lost link.
* **changed: publish state.** `PublishState` (disengage / hard-brake rolling averages) is reset at a backend change.
* **Status schema.** Appended to `StarPilotModelDataV2` (`backend`, `accelerator`, `settling`, `handovers`, `heldFrames`,
  `outputAgeMs`, `remoteModel`, `reason`), not the donor's `modelV2.big` / `modelDataV2SP`. Four StarPilot events added
  (`jetlinkAvailable/Switching/Ready/LinkLost`). Note that `EVENTS` and `STARPILOT_EVENTS` are separate tables whose integers overlap.
* **iOS** is refused with a reason rather than run (the transport is not validated); the setting stores an index Jetlink accepts, so
  a stored `ios` is refused in the adapter.
* **Warp build.** Not an SCons target: this fork builds its prebuilt pickles with standalone scripts on a comma
  (`compile_warp.py`), so `build_warp.py` follows that, and writes a build record the runtime checks (tinygrad commit, Jetlink
  version, geometry). The pickles themselves cannot be produced here (QCOM); none are committed, so a device built from this change
  reports *no warp was built for this camera* until they are.

### Added after the comparison with `peterfork/Jetlink-Port`

* The bounded shutdown now also publishes `JetlinkPoweringOff`, and hardwared refuses to start a drive while it is set (his
  `not_powering_off` idea, adapted to the wait living in manager).
* The model picker and Galaxy cards (ported from his `773a57f634`) with a validated-model gate underneath: unvalidated catalog entries
  are listed but cannot be picked (409), a stale pick is reported.
* The aarch64 params/cereal artifacts are rebuilt for all of it. The Docker build also deleted six tracked binaries and touched
  panda's version stamps (its scrub step); those were restored with `git checkout` and are not part of the change.

### Bench hardware results (2026-10-08)

The first run on a real comma (tizi) and a real host over USB-C is written up in `docs/JETLINK.md` (*Checks on a comma over USB*). In short:
the QCOM warp builds and loads (committed `warp_1928x1208_512x256_tinygrad.pkl` + record), the fast path is byte-identical to the JIT at
p99 2.7 ms, the whole frame over USB is p50 35.8 / p99 42.8 ms at 20 Hz with no held frames, the production attach path promotes and hands
back in the same frame (34.8 ms) on link loss. Findings: ADB and Jetlink are mutually exclusive on this device (the stock `g1` gadget holds the
controller); the picker change broke the offline default until validated models were always added to the effective catalog; a physical
unplug and replug was then tested (same-frame handback at 51.9 ms, rejoin within a second of the host re-enumerating, final state on the large model).

### Validation run

On a Mac: 187 tests in `starpilot/jetlink_adapter/tests` (adapter and interface conformance, Params, modes, absent/mismatched/failing
Jetlink, engagement gate, runner seam against Jetlink's real joining model, the real `modeld.main()` loop end to end with fakes at
the edges, tinygrad CPU warp for both cameras, in-place reset, events, manager backoff and bounded shutdown, route report) with 17
mutations of the safety-relevant behaviors all caught; ruff clean on new files and no new lint in edited ones. Existing suites
that touch edited files (modeld, selfdrived, hardware, manager config, params, UI navigation, model assets) pass except two
failures that this change did not cause: `common/tests/test_params.py::test_wheel_button_sound_is_registered_as_transient_string`
(`ParamKeyType` is never imported in the test) and
`starpilot/controls/tests/test_starpilot_card.py::test_very_long_press_does_not_repeat_long_press_action[distancePressed-…]`.
`starpilot/common/tests/test_starpilot_process.py` does not collect on the host (a vendored `reactivex` raises a
`DeprecationWarning` as an error).

### Not verified (needs a comma and/or a host)

The list in `docs/JETLINK.md` (*Qualification still owed*): warp build on QCOM for both geometries; USB gadget / ADB ownership,
replug, owner restart, branch switch, ignition cycling; frame-loop timing under thermal load; Bosch-radar behavior across
handovers on a real route; that the `v16` action-head reading is right on the car; a real provisioning run and the 25 s shutdown bound.

## Full-modeld replay of a recorded drive on the Mac (2026-10-08)

`modeld.main()` itself, run on route 00000380 segment 4 (30 s, 600 frames, real camera frames from the hevc as stride-padded NV12,
rlog values for carState/liveCalibration/liveDelay): real stock small model (CPU tinygrad artifact), real JetlinkRunner and
`JoiningModelState`, a real `JetlinkModelState` + `Warp` (CPU-built pickle) and a real Jetlink 0.8.5 server (Cinque Terre V3,
Neural Engine) over TCP. Edges faked: VisionIpc, SubMaster, PubMaster. The harness is a scratchpad script, not committed.

* Disengaged: promoted at frame 3, 597 frames on the large model, 0 held, published frame ids contiguous. Against the car's logged
  modelV2: action curvature corr **0.9987** (rms difference 0.00008 vs logged rms 0.00174), orientation rate 0.9994, plan speed 0.970.
* After a mid-drive join the large model starts with no history: the first ~30 frames (1.5 s) differ from the car by up to 1e-3 1/m
  (more than the typical curvature on that stretch); after that the difference is under 3e-5. The swap only happens disengaged.
* Engaged for the whole drive: never promoted (0 handovers, 600 frames local).
* Link dropped at frame 300 while engaged (client closed): handed back that same frame, no frame lost, no rejoin while engaged;
  rejoined at frame 400, the first disengaged frame (3 handovers total).
* Not what this is: the small model here is the repo's upstream CPU build (not the car's rdf43), so the "local" rows say nothing
  about what the car runs; no timing claims (CPU small model at ~7 Hz); no Bosch radar or planner in the loop.
