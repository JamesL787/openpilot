# Jetlink

Jetlink runs a large driving model on an attached Jetson or Mac over USB-C, keeping everything that touches the car on the
comma (cameras, calibration, warp, parsing, action, planning, radar fusion, control). This branch ships the comma side.
The local small model keeps driving until the host is ready and takes over again on any failure.

**Status: phase 1, off by default, USB only, one validated model. Bench-tested on a comma and a Mac host (parked); not road-tested.**
Most checks ran on a Mac against fakes, real tinygrad on CPU and the real ONNX metadata; the hardware checks that ran on a real comma
(tizi) and a real host are in *Checks on a comma over USB*. Nothing has run in a car or with an engaged drive. The qualification still
owed is listed at the end.

## What you need

| | |
| --- | --- |
| comma | 3X (tici/tizi) or 4 (mici), no Chestnut fitted (Jetlink stays off beside one) |
| Host | A Jetson or Mac running the **same Jetlink release as the vendored package: 0.8.5** (`jetlink.protocol.VERSION == 3`). The wire protocol is version-exact; never pair a newer or older server |
| Cable | USB-C data cable from the comma's USB-C port to the host |
| Model | Cinque Terre V3 (comma commit `bf3e3631b3f9`, ONNX sha256 `404a18cf…`, 766 354 845 bytes), fetched and built by the host on first use |
| Build | Warp pickles for the device's camera, built on a comma: `python3 starpilot/jetlink_adapter/build_warp.py` (see *Building*) |

## Using it

1. Settings → Driving Controls → **Jetlink** (comma 3X/tizi), or the **jetlink (usb)** toggle in the comma 4's settings list.
   The toggle changes only while parked.
2. Plug the host in. While parked, `jetlinkd` presents the USB gadget and a provisioning run uploads the model and builds its
   engine on the host (minutes the first time; the record survives reboots). The panel's *Status* line shows progress.
3. Drive. The local model drives. When the host is ready and **nothing is in control** the large model swaps in; the status
   line, the **Large Model Active (Jetlink)** chime and `starpilotModelV2` say so.
4. Engaged when the link is ready: *"Jetlink Ready: disengage to switch to the large model"* once. Disengage (and let AOL
   rest) and it swaps in by itself.

If you turn the link on and it cannot run, the device shows **Jetlink unavailable: <reason>** (offroad alert), for example
*no warp was built for this camera; update or reinstall, or turn Jetlink off*, *service stopped*, or the gadget error.

### When the large model drives

* **Promotion** happens only when openpilot is not engaged (`carControl.enabled/latActive/longActive`), always-on lateral is
  neither enabled nor armed-but-paused (a paused AOL resumes by itself, so `latActive == False` alone is not permission), no
  blinker or lane change is active, and the engagement inputs (`carState`, `carControl`, `starpilotCarState`) are alive and
  valid. Anything stale counts as engaged.
* For one second after any switch (**settling**) selfdrived refuses new engagement (*Switching Models*) and ignores only
  `posenetInvalid` / `locationdTemporaryError`, logging the suppression; a real fault outside that second still shows.
* **Handback** to the local model happens on a lost link, a reply later than 200 ms, repeated held frames (see below), a
  filtered dropped-frame ratio above 0.0075, or an unusable reply (non-finite, implausible, or missing the plan/action head).
  It is allowed while engaged: the frame is re-run on the local model in the same modeld iteration, the local model starts from a
  zeroed history (its queues are cleared in place), and the driver sees **Jetlink Lost: Small model is driving** for 5 s. Nothing
  disengages.
* After **three handbacks in a drive** the large model is locked out until the car restarts.
* A frame whose reply is late is **held**: the previous output is published again, up to 46 ms into the frame, and
  `starpilotModelV2.heldFrames` / `outputAgeMs` say how stale it is. Five held frames in a row, or more than 20 in 10 s, hand back.
  Radar fusion does not read the age; a held frame can be up to 250 ms old before it hands back.
* Chestnut and Model Laboratory are untouched: if a Chestnut is fitted, or a Chestnut / Model Laboratory path is active,
  Jetlink does not start, attach or alert.

### Shutdown

A power-off (`DoShutdown`, from the power monitor or the UI) first asks the host to power off too and keeps manager (and
`jetlinkd`) running for at most 25 s while it takes the request (`system/manager/accelerator_shutdown.py`). Reboots and
uninstalls do not wait.

## Model identity

* The persisted selection (`Model`, `DrivingModel`, `ActiveBigModel`) is **never** pointed at the external model. Those are
  model-manager keys; Jetlink's model is not one, and a restart mid-drive must come back to the user's local choice.
  While the large model drives only `ModelVersion`, `DrivingModelVersion` (`v16`) and `DrivingModelName` follow it; the
  handback restores them from the local model.
* The external model's generation flags come from `starpilot/jetlink_adapter/profiles.py`, keyed by the model's SHA-256 and
  checked against its exact input/output layout and head slices. Nothing is inferred from the local model that is loaded
  beside it. A server running anything else is refused in the vendored joining code (`validate_spec`), the small model keeps
  driving, and the refusal is shown (*Connecting (UnsupportedModel: …)*).
* **The picker** (Galaxy model manager, desktop and mobile; `JetlinkBigModel` = `{ref, displayName}`, `JetlinkCatalog` = Jetlink's
  merge of sunnypilot's big-model catalogs, refreshed by the model manager only for someone who turned the link on) lists the
  catalog and marks each model **validated or not**. A pick is accepted only if `profiles.py` has validated the model (otherwise
  the Galaxy API answers 409 with the reason), a stored pick that is no longer validated is reported as an offroad reason, and
  a PUT while driving is refused. With one validated model the picker is mostly a view of the catalog; adding a model is adding a
  profile after the checks in *Adding a model* below. `ActiveBigModel` stays a Chestnut model-key string and is not used.
* Jetlink's ONNX downloads live in `<models>/jetlink/`; `ModelManager` only deletes top-level files named like driving artifacts.

## How it is built

```
modeld ──> JetlinkRunner ──> JoiningModelState ──> LocalRunner ──> ModelState        (local small model)
 (loop)    (runner.py)        (vendored Jetlink)  └─> JetlinkModelState ──USB──> host (Cinque Terre V3)
```

| Path | |
| --- | --- |
| `starpilot/third_party/jetlink_repo/` | Vendored Jetlink 0.8.5 (`@4b747aeb`), see its `VENDORED.md`; three small additions in `LOCAL_MODIFICATIONS.patch` |
| `starpilot/jetlink_adapter/__init__.py` | The adapter (Jetlink's `Openpilot` interface), the hooks every process calls, the engagement gate `in_control`, the warp record check |
| `starpilot/jetlink_adapter/runner.py` | `LocalRunner` (Jetlink's view of `ModelState`) and `JetlinkRunner` (modeld's view of Jetlink) |
| `starpilot/jetlink_adapter/profiles.py` | The validated external models |
| `starpilot/jetlink_adapter/build_warp.py` | Builds the warp pickles on a comma |
| `starpilot/jetlink_adapter/route_report.py` | Qualification report from a route's logs |
| `starpilot/controls/lib/jetlink_events.py` | Driver alerts and the settling window |
| `system/manager/process.py` `OptionalPythonProcess`, `accelerator_shutdown.py` | Restart backoff for `jetlinkd`; bounded host shutdown |
| `selfdrive/modeld/modeld.py` | `prepare()` before realtime, `attach` after the local model loads, per-frame `set_control` / `snapshot`, handover resets |

Params: `JetlinkLink` (INT: 0 off, 1 usb; 2 iOS is stored by Jetlink but refused here), `JetlinkSpec`, `JetlinkModelPointers`,
`JetlinkChargePhone`, `JetlinkBigModel`, `JetlinkCatalog`, `JetlinkProgress`, `JetlinkPoweringOff` (manager is waiting for the host to
power off: hardwared starts no drive meanwhile), `Offroad_JetlinkUnavailable`. The native-GPU `UsbGpu*` params are not reused. The
aarch64 `common/params_pyx.so`, `common/libcommon.a` and `cereal/libcereal.a` are rebuilt for these keys and the schema (laptop Docker
build, `scripts/laptop_device_build.sh scons …`) and were checked in an arm64 container: all keys read their types and defaults and
round-trip. Rebuild them whenever `params_keys.h` or the capnp schema changes.
`starpilotModelV2` gained `backend`, `accelerator`, `settling`, `handovers`, `heldFrames`, `outputAgeMs`, `remoteModel`, `reason`
at ordinals 1–8; old logs decode as *local, no accelerator*.

### Building

The warp is a TinyJit capture of this fork's own `compile_modeld.make_warp` (policy-history graph, four named inputs, a
`(2, 6, 128, 256)` uint8 output) against **this tree's tinygrad (`f6fc4e3f`)**. It is a QCOM capture, so it must be built on a
comma:

```bash
cd /data/openpilot && source ./launch_env.sh
python3 starpilot/jetlink_adapter/build_warp.py                 # this device's camera
python3 starpilot/jetlink_adapter/build_warp.py --all-cameras   # both, for a prebuilt release
```

Each pickle is written beside a `.json` record of the tinygrad commit, Jetlink version, camera and model geometry it was built
against, and loaded back the way modeld loads it. modeld and the offroad alert refuse a pickle whose record does not match the
running tree. QCOM kernels are GPU-specific: build each geometry on the device model that will run it. The pickles are
committed with the other prebuilt artifacts; any tinygrad bump needs them rebuilt. Releases need nothing else (the packaging
scripts keep `starpilot/third_party/jetlink_repo/` and `starpilot/jetlink_adapter/models/`).

### Updating the vendored package

See `starpilot/third_party/jetlink_repo/VENDORED.md`. Never bump it independently of the host's Jetlink release.

### Adding a model

1. Read the ONNX's inputs, outputs and `output_slices` (`jetlink.spec.spec_from_onnx`) and add a `RemoteProfile` in `profiles.py` with
   the sha256, size, frame skip, exact shapes and head slices, and the behavior generation.
2. Run `route_feed.py` on a recorded drive and compare the action, plan speed and orientation rate with a car that ran the same model
   (as for Cinque Terre V3: curvature corr 0.9993). A generation is a claim until that holds.
3. Only then does the picker offer it.

### Relationship to `peterfork/Jetlink-Port`

Trung's branch ports the same Zoompilot work. The persisted keys are named alike (`JetlinkLink`, `JetlinkSpec`, `JetlinkModelPointers`,
`JetlinkChargePhone`, `JetlinkBigModel`, `JetlinkCatalog`), so a setting or a built engine carries across. The two transient keys differ:
his `AcceleratorProgress` / `Offroad_AcceleratorUnavailable` are `JetlinkProgress` / `Offroad_JetlinkUnavailable` here ("accelerator" is
ambiguous beside the Chestnut's `UsbGpu*`); both are cleared at manager start. His branch vendors Jetlink `69d308f` (0.8.3), this one
`4b747aeb` (0.8.5), and both use `starpilot/jetlink_adapter/`, so merging means choosing one adapter. See the comparison in the session
notes for what each has.

## Tests

```bash
./dev pytest starpilot/jetlink_adapter -q
```

* `test_loop.py` runs the real `modeld.main()` loop with the real vendored joining model, faking only the camera, messaging, model
  files and the host.
* `test_runner.py` / `test_pipeline.py` cover the seam and a large-model reply through the fork's parser, action and `modelV2` path.
* `test_tinygrad.py` builds the warp from the fork's graph on tinygrad's CPU device for both camera geometries, and checks the
  in-place reset on real TinyJit queues.
* `test_profiles.py` checks the pinned profile against the real ONNX when it is in the Jetlink cache.
* Report on a route: `./dev python -m openpilot.starpilot.jetlink_adapter.route_report <route-or-rlog>`.

## Checks against a real server (2026-10-07, Mac, loopback)

Jetlink.app 0.7.4 serving Cinque Terre V3 on the M1 Pro Neural Engine, with its TCP bench listener on port 5599, driven by the
vendored 0.8.5 client:

* `host_bench.py` (noise frames): the server's spec passes `require_profile`; 200 frames through Parser, v16 action and `fill_model_msg`
  with 0 non-finite; round trip p50 28.8 / p99 36.1 / max 38.3 ms, 0 of 190 over 50 ms.
* `route_feed.py` (real camera frames of route 00000380 segment 4, warped with the verified cinque-head-rl warp, the server's reply
  through this fork's output path, compared with the modelV2 the car logged for the same frames, 30 s, 600 frames): action curvature
  through the fork's v16 path corr **0.9993** (rms difference 0.00008 against a logged rms of 0.00173); plan speed 0.963; orientation
  rate 0.9995; round trip p50 29.2 / p99 32.9 ms paced at 20 Hz. A stopped segment (20) matches by holding its last curvature
  (speed below 0.3 m/s). A mixed stop-and-go segment (12) gives 0.86 on curvature and 0.985 on plan speed and orientation rate; the
  low-speed part is where `raw / v^2` and the hold-last-curvature rule diverge, so read it as a limit of an open-loop comparison.
* Repeated with Jetlink.app **0.8.5** (the intended pair, DMG sha256 `f99e448e…`, launched with `-developerTransport tcp -tcpPort 5599`):
  identical agreement (curvature corr 0.9993, plan speed 0.963, orientation rate 0.9995); round trip p50 29.5 / p99 33.2 ms paced.
  The 0.7.4 app measured the same, so the older server was not hiding anything.
* Not covered: USB, the comma's own warp, the whole modeld loop with this server, the sim, any handover on a car.

## Checks on a comma over USB (2026-10-08, parked, tizi + Mac host)

A tizi (1928x1208) on this branch's tree copied to `/data/tmp/jl-tree` (the car's own `/data/openpilot` untouched), Jetlink.app 0.8.5 on the
M1 Pro over USB-C, an isolated params store, `jetlinkd` started by hand. `host_bench.py` / `usb_bench` style scripts were run on the device.

* **Warp build on QCOM:** `build_warp.py` built and loaded `warp_1928x1208_512x256_tinygrad.pkl` against tinygrad `f6fc4e3f` (committed, with
  its build record). Jetlink's fast path initialised with no errors (IO-coherent output buffer and the graph-only replay), its output is
  byte-identical to the pickled JIT, and a frame takes **p50 1.22 / p99 2.73 / max 4.47 ms** (warp start + wait). The 1344x760 (mici) warp
  has not been built.
* **Whole frame over USB, real warp, real server, 20 Hz, 600 frames:** warp + send + server + receive + parse p50 **35.8** / p95 40.7 / p99
  **42.8** / max 45.4 ms; 0 held, 0 non-finite, 0 of 590 over 50 ms (server-side total 28.3 ms mean). That leaves roughly 7 ms of the 50 ms for
  the rest of modeld's iteration (action, publish) at p99.
* **Production attach path** (`prepare()` -> `runner.attach` -> `JoiningModelState` -> `JetlinkRunner`, a stand-in local model with real GPU
  queues, fake camera buffers): the large model prepared 3.7 s ahead of the swap, promoted when disengaged, then 540 frames at loop **p50 38.0 /
  p99 46.1 ms** with 0 held; the swap frame itself took 78 ms (one frame over budget, forgiven by the drop-filter warm-up). The server's own
  log agrees: 540 frames in 84 s, total p50 27 / p99 31 / max 47 ms, 0 slow.
* **Link loss:** with the gadget unbound mid-run the runner handed back in the same frame, **34.8 ms** for the whole frame (link 5, demote 25
  including the in-place reset, small model 4 with the stand-in), so no camera frame was lost. This used an *unbind*, which is not a physical
  unplug (see the next item for a real one).
* **Physical unplug and replug (a 4-minute run, 4800 frames at 20 Hz):** the large model promoted at frame 60 and ran 3 minutes. Unplugged at
  17:40:06 (the controller reported "Nothing attached"), the runner handed back **in the same frame, 51.9 ms** (link 12, demote 36, small
  model 3 with the stand-in; about 2 ms over budget, so one camera frame can be lost on a real pull). Replugged at 17:40:21: the host
  re-enumerated, "a host configured us at super-speed", and the large model was back at frame 3866 (swap frame 65.5 ms) within the same second.
  Over the run: 4444 large-model frames at p50 38.0 / p99 46.4 ms, 0 held, 3 handovers, no lockout, ended on the large model. After a real
  unplug the stock ADB gadget is not involved (it was unbound for the test), so whether it returns after a branch switch is still untested.
* **ADB conflict (a finding):** this comma has `AdbEnabled=1`, so the stock `g1` gadget (adb + ncm) holds the only device controller, and
  Jetlink's root helper refuses to share it ("tear it down first"). Jetlink and USB adb are **mutually exclusive on this device**; ssh over
  the network is unaffected. For the test `g1` was unbound and afterwards rebound; the stock gadget, `adb devices` and the Jetlink gadget
  teardown were verified to be restored. With the link on and ADB on, the offroad alert says the gadget is held.
* **Idle behaviour:** `jetlinkd` releases the gadget after 60 s with nothing to do so the host can sleep, and re-presents it when modeld asks.
* **Two bugs the device found** that the Mac tests could not: the picker change left a fresh or offline comma with no catalog, so Jetlink
  had no default model and never joined (fixed: validated models are always in the effective catalog); and a fake camera buffer smaller than
  the real padded NV12 frame segfaults the process, because the GPU reads past it (my harness, but a reminder that the buffer size is the
  VisionIPC buffer size).

Not covered by these runs: a real camera and the real small model, the full `modeld` process, an engaged or moving car, thermal load over a drive,
and Bosch-radar behaviour across a handover.

## Known limitations

* **Blinker cancel cannot flush the host's desire history.** The local model flushes it on a blinker release; the wire protocol
  has only a full reset. Mitigation: a swap is refused while a blinker or lane change is active, and starts from empty history.
* **Control races.** Promotion reads engagement at the start of a frame; an engage arriving in the same frame as the swap is
  possible. The settling no-entry second and the 20-frame proving period (a single held frame hands back) bound it.
* **Held-frame age is not consumed by radar fusion**; it is published and logged only.
* iOS and dual-remote Model Laboratory are not built. The Galaxy picker was checked through Flask's test client and a syntax check of the
  JS, not in a browser.

## Qualification still owed

Done on bench hardware (see above): the QCOM warp build for the tizi camera, the Warp fast path and its timing, the whole-frame loop over USB
at 20 Hz, the production attach, promotion and a same-frame handback. Still owed, in a car or on the real stack:

1. `build_warp.py` for the mici (1344x760) camera on a comma 4.
2. Whether the stock ADB gadget comes back after a branch switch away from this branch, and a decision on ADB: Jetlink cannot share the
   controller with it. (Physical unplug/replug recovery is verified, see above.)
3. The real `modeld` process on the comma (real camera, real small model, the car's `/data/openpilot` on this branch): frame-loop timing
   sustained and thermally loaded, held-frame rate, dropped camera frames, repeated handbacks (use `route_report`). For comparison one April
   segment of this car's local model ran modeld at p50 28.9 / p99 30.3 ms.
4. Replay or a drive with handovers on a Bosch-radar car: lead selection, lead probabilities, `mdMonoTime`, model-based ego velocity,
   longitudinal target and action continuity across a handover (`route_report` flags steps above the drive's own p99).
5. The `v16` action-head reading in closed loop. Open loop on recorded frames it is confirmed (corr 0.9993).
6. Ignition cycling with the host on the ignition rail, provisioning from nothing (model download, engine build) and the 25 s shutdown bound.


## Models the link will accept

Cinque Terre V3 is the only model read from its ONNX and replayed against a car's log. Five more of Jetlink's catalog (Sad, BMRLNAP v4,
BMRLNAP v6, Cinque Terre, Cinque Terre V2) are pinned in `profiles.py` by the hash and size in their LFS pointers and assume V3's layout
and v16 action head, because their ONNX is within 0.4 MB of V3's and this fork's manifest tags the same models v16. That assumption is
not verified: nobody has run them. `require_profile` still compares the server's reported inputs, outputs and every head slice with V3's
exactly, so a model that differs in layout is refused at the join and the small model keeps driving; what it cannot catch is a different
action-head behavior. The larger catalog models (about 1.76 GB, an older architecture) and the previews have no profile and stay unpickable.
