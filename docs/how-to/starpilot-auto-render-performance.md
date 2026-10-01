# Starpilot Auto render optimizations

These changes reduce per-frame work without reducing the configured FPS or
changing driver-monitoring validity/frequency checks.

## Profile findings

The September 25 capture contained 30 profile windows and 163 render-stat
intervals, mostly onroad. Median interval values were 25.8 FPS, 38.35 ms frame
time and 27.19 ms renderer CPU time. The corner decoration and repeated Params
reads were visible hot paths. Native calls that release the GIL can absorb
sampling attribution: the raylib share is not a measurement of wrapper overhead.

## Changes

- Bypass the entire radial favorites component in the dedicated Starpilot Auto
  car view. `OnroadControls.route()` sends no touches to the normal driving
  layout, so its radial menu cannot be opened there. Avoid constructing the
  component, processing gestures, loading favorite slots/layouts each frame,
  drawing its hint or creating its cached textures. The separate Starpilot Auto quick menu
  and navigation destination favorites remain available.
- Keep the favorite-menu corner cache for the comma's own large UI (C3X), based on the useful part of
  `origin/AAOptimizev1` (`ef767cff9`). Size and pressed state invalidate it;
  translation reuses it. Deferred rendering captures its inputs, and compositing
  preserves premultiplied alpha. Only this small cached decoration is supersampled.
  C4's native `mici` UI uses a separate favorites overlay and is unchanged.
  Mirror mode still shows whatever is on the device's own display.
- Use the existing shared UI settings cache for default border/lead helpers,
  instead of opening Params and reading the filesystem on each draw. Explicit
  Params arguments retain their behavior; control-state parameters are unchanged.
- Skip unchanged polygon shader uniform uploads. Value snapshots detect in-place
  color, stop and rectangle changes, and shader teardown clears the cache.
- Avoid invalidating model-renderer transforms when an equivalent transform is
  submitted. Use scalar two-point interpolation for normal increasing endpoints,
  retaining NumPy's behavior for duplicate/reversed endpoints. The parent already
  caches transforms, so this is not a claim of eliminating an every-frame update.
- Avoid polling map data twice when drawing an already-prepared Starpilot Auto map.
- Attribute sampled Params waits to key names in the existing profiler. Unlike
  the branch's global Params wrappers, this adds no hook to every parameter read.
  The report contains sampled shares, not exact read counts, and never values.

Earlier changes removed full-frame car-layout MSAA, fused padding/vertical flip
and alpha composition into NV12 conversion, and made diagnostic `glFinish`
opt-in. The map's separate render target and camera upload path remain unchanged.

## Device measurements

Offroad microbenchmarks on the comma's Adreno 630 used a temporary source overlay;
the installed checkout and original logs were not modified. Median wall times:

| Operation | Before | After | Iterations per variant |
| --- | ---: | ---: | ---: |
| Corner decoration, including GPU completion | 3.099 ms | 0.639 ms | 200 |
| Border-setting lookup | 0.115 ms | 0.038 ms | 1,000 |
| Unchanged gradient configuration | 0.187 ms | 0.058 ms | 300 |

Corner CPU time fell from 2.937 ms to 0.509 ms. Both corner variants include
render-target setup, clearing, and a GPU completion wait. Their 2.460 ms wall-time
difference demonstrates the cache benefit, but the remaining 0.639 ms is not
the hint's standalone cost. The subsequent Starpilot Auto component bypass has not been
benchmarked; it also skips menu layout and parameter reads absent from this
microbenchmark. These measurements are not additive whole-frame savings or a
full-drive FPS result.

The initial optimizations passed 232 relevant tests on the device, including actual GPU NV12 composition
and byte-for-byte cached-versus-uncached gradient rendering checks. Tests cover
cache invalidation, map polling, interpolation, navigation, render layers,
settings changes and profiling privacy.

The subsequent Starpilot Auto favorites bypass passed 91 device tests covering the optional
component's lifecycle, C3X radial favorites, C4 favorites and Starpilot Auto navigation/touch
routing. These ran through the temporary source overlay, without deploying to
the installed UI or restarting projection.

## Remaining validation

### Starpilot Auto map route culling

The dedicated Starpilot Auto renderer now caches bounding boxes for groups of 128 route
segments. For long active routes (at least 8,192 points), it projects and scans
only the range that could intersect the map. Bounds are rebuilt when the route
array changes; camera movement searches the same bounds. Both endpoints of each
segment are included, and the range spans all candidate groups, preserving
cross-screen segments and routes that leave and re-enter the view. Existing
clipping, simplification, traveled-route styling and end caps remain in use.

Short routes bypass this search because a desktop benchmark showed its overhead
outweighing the savings. Native C3X/C4 maps and route previews use the original
path. No tile-cache format, downloading, eviction or worker behavior changed:
downloaded tiles already load and decode on background workers. This change
addresses route CPU work that remains even with warm tiles, not download speed.

In a synthetic route-drawing Mac GPU benchmark at a 537x720 split-map target with
4x MSAA, median route-draw submission times over 300 measured redraws were:

| Route points | Full-route processing | Trimmed processing |
| --- | ---: | ---: |
| 20,000 | 0.178 ms | 0.123 ms |
| 100,000 | 0.470 ms | 0.129 ms |

These are host microbenchmarks, not comma FPS measurements or savings established
for the recorded drive. The first redraw also pays the one-time bounds build.
100 targeted map/tile tests passed on the host, including 60 actual GPU comparisons
with identical output bytes across headings, progress positions and route ends.
The host run used an isolated UI-state stub because the checkout's messaging
extensions target Linux; broader Starpilot Auto navigation tests still need a device run.

The route-culling change alone leaves Starpilot Auto output FPS, the map's 15 Hz redraw
budget, anti-aliasing and safety checks unchanged. It targets long-route
frame-time spikes, not animation cadence.

### Smooth Starpilot Auto map motion

The Starpilot Auto map now moves its cached world image on every car frame, while retaining
the existing average 15 Hz schedule for drawing tiles, routes and destinations.
Camera position, heading and zoom advance at the car-frame cadence. A 32-physical-
pixel border provides room for the intermediate transform; all four viewport
corners must remain inside that cache. Otherwise the previous view is held until
the next scheduled redraw, rather than exposing gaps or increasing GPU redraws.
The map is clipped to its pane, including in scaled left/right split layouts.

Guidance/status graphics use a separate premultiplied texture, refreshed on
message/state changes and once a second for time-dependent text. It shares the
world's MSAA target, rather than allocating a second multisampled target. The
car marker stays anchored and uses two small supersampled sprites (fresh/stale),
rotated each frame. Resizing invalidates both layers. Native displays still use
the original direct rendering path; tile storage and safety checks are unchanged.

Starpilot Auto dead reckoning also uses the position's published monotonic timestamp instead
of the later UI-read time. The 4 Hz publisher and 5 Hz polling previously caused
periodic position resets even at constant speed. Missing/future timestamps fall
back to read time. This display-only change adds no GPU work and leaves native
maps' time reference unchanged.

There is a real cost: the border adds approximately 22% to a 537x720 map target's
area, and the overlay needs one extra render texture. RGBA color storage alone
increases by about 2.1 MiB for that size, before depth/MSAA allocations. Extra
composition and camera math are not free. In a synthetic Mac warm-tile benchmark
with a 2,000-point route, 4x MSAA, one guidance update per second, and 30 car
frames/second, two runs per variant measured these mean per-frame times:

| Map preparation + composition | Previous cache | Moving cache |
| --- | ---: | ---: |
| Renderer-thread CPU | 0.243–0.248 ms | 0.324–0.330 ms |
| Wall time including GPU completion | 0.841–0.862 ms | 1.101–1.104 ms |

Each run discarded 60 warm-up frames and measured 600 frames. Both variants
redrew the world 330 times over 660 simulated car frames. The completion wait
was benchmark-only; no production synchronization was added. These numbers are
not comma measurements, isolated GPU timings, or whole-UI FPS results.

157 targeted host tests passed, including real GPU checks for intermediate motion,
rotation/zoom, edge coverage, scaled split clipping, alpha, marker orientation,
resizing, cache teardown, stationary idling and the unchanged redraw budget.
A simulated 4 Hz publisher/5 Hz reader verifies continuous constant-speed motion.
The run used an isolated UI-state stub for Linux-only messaging dependencies.
The device reported onroad, so no device rendering benchmark or deployment was
performed. Actual Starpilot Auto frame delivery, thermal/memory pressure and driver-monitoring
headroom still need a matched device comparison. GPS jumps, stale fixes and cache
coverage limits can still cause a hold; this is not a promise of eliminating every
possible stutter.

### Optional C4 native-screen sleep

The Galaxy's Starpilot Auto Layout panel offers `sleep_device_screen`, on by default.
It reuses the native screen timeout and tap-to-wake path, suspending drawing
without stopping UI state updates, watchdog servicing, driver monitoring or
Starpilot Auto's separate car renderer. Critical alerts always hold the native display awake;
`sleep_wake_events` adds any of the other Standby wake events (warnings by default).
Native Live UI viewers still keep drawing active; C3X and mirror mode are unchanged.

The supervisor records the source timestamp only after sending a real car-view
frame. The native UI checks that heartbeat and focused demand from shared-memory
header bytes, without copying frame pixels or polling a control socket. Startup,
lost focus, or a sent frame at least one second old cannot put the screen to sleep; once
asleep, a gap has to outlast a 3 s grace to wake it, so a single slow frame does not
relight the panel for a full timeout.
Session initialization clears the heartbeat. This uses existing settings storage
and unused frame-header space, with no Params/schema build or new background worker.

Read-only copies of route `000000bc--59fdef8bba` qlogs give this native-UI baseline:

| Segment | Native UI CPU (% of one core) | Median uiDebug draw wall time |
| --- | ---: | ---: |
| 8 | 40.65% | 44.00 ms |
| 20 | 42.13% | 44.73 ms |
| 27 | 40.76% | 40.63 ms |

CPU values are differences between two `procLog` samples approximately 30 seconds
apart, for `selfdrive.ui.ui`, not the Starpilot Auto renderer. They include work retained while
asleep, so 40–42% of one core is a ceiling, not a savings claim. `uiDebug` measures
wall time, not isolated GPU time. Native-render tests verify zero drawing/texture
passes over 60 sleeping loop iterations while the loop continues yielding.

An isolated C4 policy benchmark, with display-power calls mocked and temporary
settings/frame files, measured 36.661 µs CPU/tick disabled and 62.001 µs enabled
(median of five 2,000-tick batches). The added 25.340 µs is about 0.15% of one core
at 60 ticks/sec. This measures policy overhead, not GPU savings. Device-side tests
used temporary source overlays; the installed UI, settings and source logs were
not changed. An actual connected awake/asleep comparison is still required to
quantify net CPU/GPU savings and driver-monitoring/Starpilot Auto FPS improvements.

Validation: 92 Python tests passed on the device using the temporary overlay,
including sleep/wake policy, frame freshness/focus, mirror exclusion and settings
API coverage. Six UI-panel tests and Ruff checks also passed.

After the owner confirmed the comma was safely parked/on a bench, an isolated
536x240 EGL test rendered its native onroad HUD/sidebar/driver graphics using
segment 20 messages. Across three 60-frame batches, median CPU time was
10.23–11.06 ms/frame and GPU-completed wall time was 14.77–15.64 ms/frame.
The qlog omits modelV2, so path rendering was excluded; camera capture/upload,
side-camera preview, scanout and Starpilot Auto transmission were also excluded. These are
component costs avoided while sleeping, not a matched whole-system savings or
isolated GPU-time measurement. No physical display-power calls were made.

`starpilot-auto-dhu` can provide the connected bench comparison after deployment. The normal
launcher runs installed code and rotates Starpilot Auto logs; preserve existing logs or use
a separate temporary log directory before testing. DHU does not reproduce the
car's wireless link or driving workload.

### Connected comparison

After deployment, compare matched onroad runs at the same configured FPS and
resolution. Check produced and sent FPS, frame age, driverStateV2 and
driverMonitoringState frequency/validity, and communication alerts. The target is
20 Hz driver monitoring with no loss of delivered UI FPS; isolated benchmarks
cannot prove that outcome. Do not weaken safety checks to suppress the warning.

### Map hitches between smooth stretches

Four sources of a periodic stall in the cached map, addressed together:

- **Turning at 1 Hz.** Fixes arrive once a second, and dead reckoning ran each one
  along a straight tangent. In a curve the next fix landed inside it, and easing
  that correction out read as a slow-down once a second; the bearing, and so the
  marker and a heading-up map, also snapped once a second. The map now estimates
  a turn rate from the last two fixes (above 3 m/s, clamped to 40°/s), dead reckons
  along that arc, and turns the heading continuously, easing a new fix's bearing in
  like its position.
- **Overlay redraws.** The cached guidance overlay was redrawn once a second and for
  every copy of navigationd's instruction. It now redraws only when its text changes.
- **Tile uploads.** At most one 512×512 texture upload per car frame instead of two.
- **Garbage collection.** Full collections walked every object the car UI built at
  startup. The renderer now `gc.freeze()`s them once the UI is constructed.

These are host-tested (arc prediction leaves under 0.1 m for the next fix at
20 m/s and 12–20°/s); an on-device render_stats comparison has not been done yet.
