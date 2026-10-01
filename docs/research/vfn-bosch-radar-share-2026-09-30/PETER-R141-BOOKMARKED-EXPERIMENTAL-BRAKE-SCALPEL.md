# Peter R141 bookmarked Experimental-brake scalpel

## Top summary

BOOKMARKED EVENTS: **10**

SAME ROOT CAUSE ACROSS EVENTS: **PARTIAL**

PRIMARY REMAINING CAUSE: **MIXED** — several abrupt low-speed changes have a
stable visible radar association but an unlogged planner/MPC-state transition;
two events have a clear native/parser-vRel or radar-association precursor.

STALE-PREFERENCE FIX INVOLVED: **NO observable evidence**

RADAR INPUT CORRUPTION INVOLVED: **NO proven corruption**; events R141-5 and
R141-8 contain suspicious vRel changes that should remain parser/radar review
items.

ACTION EXTRACTION AMPLIFICATION REPEATS: **NO**

EARLY BRAKING EXISTS BEFORE HONDA ACTUATION: **YES**. In the strongest cases,
the published planner target is already strongly negative and the nearest
Honda command follows the already-negative `carControl` acceleration.

HONDA ACTUATOR MAPPING ADDS EXTRA HARSHNESS: **NO evidence in this route**.

NEXT SMALLEST FIX TARGET: instrument the live planner/MPC output path for the
R141 low-speed `cruise` events, while separately validating the large Bosch
vRel changes in R141-5, R141-8, and R141-9.

## Provenance and method

Route: `11c8fa231c0499ed/00000141--d3a05962de`

Analyzed segments: 1 through 6, because those are the segments containing
bookmarks. Segment 0 contained no bookmark.

Running revision recorded in every segment:

```text
branch: night-star-bosch-radar
commit: 7315fb15f58fd6a6f7e9ebe748b87f4fc6f21789
dirty:  false
version: 0.11.2
vehicle: HONDA_CIVIC_BOSCH
```

The canonical event time is the `bookmarkButton` timestamp. The paired
`userBookmark` message is a logger echo and was merged with its button event.
The route-relative origin used here is the first meaningful message in
segment 0, `85.746922362 s` in the route clock.

The ten merged bookmark times are:

| event | segment | route-relative bookmark time |
|---:|---:|---:|
| R141-1 | 1 | 65.102910 |
| R141-2 | 1 | 69.152405 |
| R141-3 | 2 | 134.489897 |
| R141-4 | 3 | 227.019782 |
| R141-5 | 3 | 232.425078 |
| R141-6 | 4 | 263.695238 |
| R141-7 | 4 | 276.874842 |
| R141-8 | 5 | 324.946771 |
| R141-9 | 5 | 354.486747 |
| R141-10 | 6 | 361.766594 |

Each event was restricted to the requested bookmark window, approximately
`bookmark - 1.5 s` through `bookmark + 2.5 s`. No route-wide scan was used.

Recorded Honda parameters include `longitudinalActuatorDelay=0.5 s`,
`radarTimeStep=0.05 s`, and `radarDelay=0.1 s`; therefore the diagnostic
action time used for the published plan was `action_t = 0.55 s`.

`get_accel_from_plan()` was reproduced exactly from the checked-out planner:

```text
v_now    = speeds[0]
a_now    = accels[0]
v_target = interp(action_t, CONTROL_N_T_IDX, speeds)
current  = 2*(v_target-v_now)/action_t - a_now
```

The direct comparator is interpolation of the logged acceleration trajectory at
the same `action_t`. The logged `longitudinalPlan` contains the published
speed/acceleration trajectories, but not the internal solver obstacle arrays,
full cost vector, pre-clip target, or final internal `mpc.mode`/`mlsim` state.
There were no `liveLongitudinalMpc` messages in these windows. Those fields are
reported as unavailable rather than reconstructed.

## Mode and telemetry limits

`selfdriveState.experimentalMode` and `starpilotPlan.experimentalMode` agreed:
Experimental was true for R141-1 through R141-7, R141-9, and R141-10; R141-8
was non-Experimental. The planner source code maps that flag to
`self.mode='blended'` or `'acc'`, initializes `mpc.mode` accordingly when not
running `mlsim`, and later passes through `get_mpc_mode()`.

The exact final `mpc.mode` and whether `mlsim` was active are not serialized in
these rlogs. `starpilotToggles` was empty, so the model-generation/tinygrad
variant is also not independently recoverable. `longitudinalPlanSource` is
the published source label, not a substitute for the internal solver mode.

Likewise, the report can show the logged lead trajectories (`leadTrajectoryX0`
and `leadTrajectoryX1`) and the published `velocity`/`acceleration` arrays.
The internal `lead0 obstacle`, `lead1 obstacle`, `cruise obstacle`, selected
minimum obstacle, `x_solution`, and solver cost vector were not logged.

## Bookmark event tables

Values in `first 6 v/a` are the first six logged published-plan samples. The
`leadX0/leadX1` values are the first six logged lead-trajectory samples. `x`
for the planner state and internal obstacles is not present in the rlog.
`min a first 1 s` is the minimum of the first eleven logged acceleration
samples, a one-second diagnostic window.

### R141-1 — segment 1, bookmark 65.102910 s

First material target step: `66.488637 -> 66.542382 s`,
`-0.015323 -> -0.756910 m/s²`, delta `-0.741587 m/s²`, `dt=0.053745 s`.

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| ego `vEgo`, `aEgo` | 3.254, 0.218 m/s² |
| leadOne | radar ID20, dRel 31.672, yRel -0.155, vRel -3.312, vLead -0.105, aLeadK -0.655 |
| leadTwo | same ID20 and same geometry/velocity; duplicate radar lead |
| model lead0 | x 41.078, y -0.060, v 0.525, a -0.233, prob 0.982 |
| first 6 v/a | v=`[4.20,4.20,4.22,4.26,4.31,4.37]`; a=`[0.65,0.65,0.66,0.68,0.72,0.78]` |
| leadX0 / leadX1 | both `[31.67,31.67,31.67,31.67,31.67,31.67]` |
| extraction | current 0.969, direct 0.969, amplification ~0.000 |
| min a first 1 s | +0.649 |
| nearest 0x1DF / carControl | ACCEL_COMMAND -0.03; brake request 0; carControl accel -0.015 |

The first upstream visible change is not represented by a radar identity or
lead geometry change. The MPC trajectory at `action_t` remains positive while
the published target jumps negative. Classification: **UNKNOWN**; the
unlogged planner/post-solver state is the remaining candidate.

Closing speed is 3.312 m/s, TTC 9.56 s, and the constant-deceleration sanity
requirement to a 6 m gap is only about -0.214 m/s²: **substantial braking was
not geometrically required**.

Association checks: no radar/vision transition within ±0.5 s; no radar-ID
transition; no observable stale-preference clear; same S33 failure pattern not
proven.

### R141-2 — segment 1, bookmark 69.152405 s

Largest target step in the window: `69.685558 -> 69.744222 s`,
`+0.069319 -> -0.425112 m/s²`, delta `-0.494431 m/s²`.

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| ego at step | vEgo 2.791 m/s |
| leadOne / leadTwo | both radar ID20; dRel 25.389, yRel +0.025, vRel -2.750, vLead -0.037, aLeadK -0.050 |
| model lead0 | x 29.350, y +0.093, v 0.575, a -0.186, prob 0.995 |
| extraction at step | current -0.425, direct -0.320, amplification -0.105 |
| min a first 1 s | -0.724 |
| nearest 0x1DF / carControl | ACCEL_COMMAND +0.05; brake request 0; carControl accel approximately 0 |

No radar ID or radar/vision transition occurred around the bookmark. The
radar velocity is essentially stable across the abrupt target step, so the
first causal internal change is not identifiable from the recorded services.
Classification: **UNKNOWN**.

Closing speed is 2.750 m/s, TTC 9.23 s, and the 6 m-gap sanity requirement is
about -0.157 m/s² at the exact step: **not substantial**. Around the selected
low-speed portion of the window the requirement reaches roughly -0.511
m/s², which is **borderline**, not an emergency demand.

Association checks: no transition within ±0.5 s; no ID switch; no observable
stale-preference clear; same S33 failure pattern not proven.

### R141-3 — segment 2, bookmark 134.489897 s

No abrupt braking onset. The largest negative target change is only
`+0.478676 -> +0.459952 m/s²`, delta `-0.018724 m/s²` at `136.964065 s`.

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| representative radar | leadOne/Two radar ID26; dRel 27.445, yRel +0.308, vRel +1.234, vLead +10.544, aLeadK +0.354 |
| model lead0 | x 39.417, y +0.468, v 11.834, a +0.469, prob ~1.000 |
| representative extraction | current -0.017, direct -0.000, amplification -0.017 |
| first 6 v/a | v=`[9.60,9.60,9.60,9.59,9.59,9.59]`; a=`[-0.05,-0.05,-0.05,-0.05,-0.05,-0.05]` |
| min a first 1 s | -0.053 |
| nearest 0x1DF / carControl | ACCEL_COMMAND -0.03; brake request 0; carControl -0.049 |

No association transition occurred. Classification: **UNKNOWN / no abrupt
braking event reproduced**. Closing speed is zero because the object is
opening; no meaningful TTC or braking requirement exists.

### R141-4 — segment 3, bookmark 227.019782 s

No abrupt negative transition. The target is gradual through the window; the
minimum selected target was about -1.805 m/s² near `225.609 s`, while the
later published trajectory settles near -0.398 m/s². The local target change
at the end of the window is effectively zero (`-0.398483 -> -0.398252`).

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| representative radar | leadOne/Two radar ID53; dRel 54.520, yRel -0.133, vRel +0.250, vLead 10.570, aLeadK -1.973 |
| model lead0 | x 70.289, y +0.167, v 6.735, a -0.840, prob 0.988 |
| representative extraction | current -1.805, direct -1.685, amplification -0.119 |
| first 6 v/a | v=`[10.38,10.36,10.30,10.21,10.08,9.91]`; a=`[-1.89,-1.90,-1.92,-1.94,-1.93,-1.92]` |
| leadX0 / leadX1 | both `[54.52,55.25,57.46,61.13,66.26,72.87]` |
| min a first 1 s | -1.941 |
| nearest 0x1DF / carControl | ACCEL_COMMAND about -1.87; brake request 1; carControl -1.894 |

No ID or radar/vision transition occurred. Classification: **MPC_TRAJECTORY_RESHAPE
 / gradual**, not an abrupt association event. Closing speed is zero at the
 representative row; braking was not required by closing geometry at that
 instant.

### R141-5 — segment 3, bookmark 232.425078 s

First abrupt target step: `231.856933 -> 231.907306 s`,
`-2.454289 -> -3.347610 m/s²`, delta `-0.893320 m/s²`.

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| ego | vEgo 4.321, aEgo -2.413 m/s² |
| leadOne / leadTwo | both radar ID53; dRel 38.926, yRel +0.152, vRel -4.484, vLead +0.189, aLeadK -3.561 |
| immediately prior lead | ID53; dRel 39.554, vRel -2.609, aLeadK -2.955 |
| model lead0 | x 42.568, y +0.180, v 1.048, a -0.211, prob 0.993 |
| first 6 v/a | v=`[5.10,5.08,5.02,4.92,4.80,4.65]`; a=`[-2.45,-2.40,-2.24,-2.00,-1.76,-1.45]` |
| leadX0 / leadX1 | both `[38.93,38.93,38.93,38.93,38.93,38.93]` |
| extraction | current -0.437, direct -0.873, amplification +0.436 (current is less negative) |
| min a first 1 s | -2.454 |
| nearest 0x1DF / carControl | ACCEL_COMMAND -2.43; brake request 1; carControl -2.454 |

The first visible precursor is a native radar vRel/aLeadK change, not action
extraction. The published target is much more negative than both extraction
diagnostics, so extraction did not create this step. The exact post-MPC
operation producing the published target is unavailable from the rlog.
Classification: **RADAR_VREL_CHANGE** (with a downstream planner-state/output
stage still unresolved).

Closing speed is 4.484 m/s, TTC 8.68 s, and the 6 m-gap requirement is about
-0.305 m/s²: **substantial braking was not geometrically required** by this
simple sanity check. No association transition or ID switch occurred within
±0.5 s; no stale-preference clear is observable; same S33 failure pattern not
proven.

### R141-6 — segment 4, bookmark 263.695238 s

No abrupt transition. Largest local negative change is about
`-0.623205 -> -0.673344 m/s²`, delta `-0.050139 m/s²` at `265.908818 s`.

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| leadOne / leadTwo | both radar ID62; dRel 35.727, yRel +0.297, vRel -1.594, vLead +3.977, aLeadK -0.797 |
| model lead0 | x 37.752, y +0.132, v 2.816, a -0.639, prob 0.994 |
| extraction | current -0.466, direct -0.506, amplification +0.040 |
| first 6 v/a | v=`[7.74,7.74,7.72,7.68,7.64,7.58]`; a=`[-0.74,-0.73,-0.71,-0.67,-0.64,-0.60]` |
| leadX0 / leadX1 | both `[35.73,36.10,37.13,38.74,40.78,43.06]` |
| min a first 1 s | -0.623 at the selected transition row |
| nearest 0x1DF / carControl | ACCEL_COMMAND about -0.75; brake request 1; carControl -0.736 |

Classification: **MPC_TRAJECTORY_RESHAPE / gradual**. Closing speed 1.594
m/s, TTC 20.74 s, and 6 m-gap requirement about -0.054 m/s²: **no substantial
braking requirement**. No association switch within ±0.5 s.

### R141-7 — segment 4, bookmark 276.874842 s

First abrupt target step: `277.853851 -> 277.905316 s`,
`-0.309075 -> -0.639413 m/s²`, delta `-0.330339 m/s²`.

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| ego | vEgo 2.450 m/s |
| leadOne / leadTwo | both radar ID21; dRel 13.736, yRel +0.315, vRel -2.547, vLead -0.111, aLeadK -0.368 |
| model lead0 | x 16.903, y +0.138, v 0.275, a -0.101, prob 0.999 |
| extraction | current +0.024, direct -0.089, amplification +0.113 |
| first 6 v/a | v=`[2.19,2.18,2.15,2.10,2.04,1.97]`; a=`[-1.22,-1.20,-1.11,-0.98,-0.85,-0.69]` |
| leadX0 / leadX1 | both `[13.74,13.74,13.74,13.74,13.74,13.74]` |
| min a first 1 s | -0.309 at the transition row |
| nearest 0x1DF / carControl | ACCEL_COMMAND -0.27; brake request 1; carControl -0.309 |

The radar vRel changes from approximately -1.94 to -2.55 m/s around the
transition and is the strongest visible precursor, but the track remains the
same ID. Classification: **RADAR_VREL_CHANGE**. Closing speed 2.547 m/s,
TTC 5.39 s, and the 6 m-gap requirement is about -0.294 m/s²: **borderline,
not substantial**. No radar/vision or ID transition within ±0.5 s.

### R141-8 — segment 5, bookmark 324.946771 s

The first target step is `323.649716 -> 323.707115 s`,
`+0.251613 -> -0.422039 m/s²`, delta `-0.673652 m/s²`. A second, larger
step follows at `323.807832 s`, `+0.599765 -> -0.500000`, delta
`-1.099765 m/s²`.

| field | value |
|---|---|
| mode / source / stop | non-Experimental / `cruise` / false |
| ego at first step | vEgo 19.278 m/s |
| leadOne / leadTwo at first step | both radar ID42; dRel 116.495, yRel -1.024, vRel -9.440, vLead 9.823, aLeadK +1.099 |
| immediately prior lead | ID42; dRel 117.238, yRel -1.030, vRel +3.724, vLead 22.952, aLeadK +3.636 |
| model lead0 | x 118.763, y -0.243, v 17.575, a -0.017, prob 0.631 |
| extraction at first step | current +0.253, direct +0.253, amplification ~0 |
| min a first 1 s | +0.251 at first step; later second step reaches about -1.167 |
| nearest 0x1DF / carControl | ACCEL_COMMAND +0.29; brake request 0; carControl +0.252 |

This is the clearest radar-input anomaly: U11/parser vRel changes by about
13.2 m/s while range and geometry move smoothly. Around the bookmark itself,
ID42 repeatedly toggles radar↔vision (nine visible transitions in the ±0.5 s
window), although the first target step precedes that flicker. Classification:
**RADAR_VREL_CHANGE**; the later association oscillation is a separate
secondary symptom. Closing speed at the first step is 9.440 m/s, TTC 12.34 s,
and the 6 m-gap requirement is only about -0.403 m/s²: **not substantial**.

Association checks: radar↔vision **YES within ±0.5 s**; radar ID changes
between ID42 and vision `-1`; no direct Arm A/B counter or clear is logged;
same S33 stale-preference failure not proven.

### R141-9 — segment 5, bookmark 354.486747 s

First material step is `353.106788 -> 353.159136 s`,
`-1.240763 -> -1.764292 m/s²`, delta `-0.523528 m/s²`. Around
`353.452686 s` a second step occurs, `-1.611326 -> -2.262997`, delta
`-0.651670 m/s²`.

| field | value |
|---|---|
| mode / source at first step | Experimental; `lead0 -> cruise`; stop false |
| lead immediately before | radar ID5; dRel 41.668, yRel -0.285, vRel -5.786, vLead 9.206, aLeadK -0.834 |
| lead at first step | vision (`radar=false`, ID -1); dRel 46.773, yRel -0.061, vRel -2.790, vLead 12.108, aLeadK -1.427 |
| lead at second step | radar ID40; dRel 38.355, yRel -0.337, vRel -11.081, vLead 3.536, aLeadK +1.136 |
| model lead0 at first step | x 47.500, y +0.036, v 12.547, a -1.389, prob ~1.000 |
| extraction at first step | current -1.764, direct -1.534, amplification -0.230 |
| first 6 v/a | v=`[14.77,14.75,14.71,14.64,14.54,14.41]`; a=`[-1.24,-1.27,-1.38,-1.49,-1.50,-1.53]` |
| leadX0 / leadX1 | lead0 `[46.77,47.61,50.08,54.05,59.32,65.62]`; lead1 `[46.95,47.79,50.26,54.24,59.53,65.85]` |
| min a first 1 s | -1.739 |
| nearest 0x1DF / carControl | ACCEL_COMMAND -1.23; brake request 1; carControl -1.241 |

The onset coincides with a radar-to-vision change and source change; the
subsequent radar return is a different ID with another large negative vRel.
Classification: **RADAR_ASSOCIATION_CHANGE**. The association transition is
outside the bookmark's ±0.5 s center window but inside the requested event
inspection window. Closing speed at first step is 2.790 m/s, TTC 16.77 s, and
the 6 m-gap requirement is only -0.095 m/s²: **no substantial braking
requirement**.

Association checks at ±0.5 s around the bookmark: no transition is present
there because the ID40 radar track is already established. The earlier
radar/vision transition is the important event; no direct stale Arm A/B clear
is observable.

### R141-10 — segment 6, bookmark 361.766594 s

No strong jerk onset. The largest local target change is
`-0.715820 -> -0.975170 m/s²` at `362.453468 s`, delta `-0.259351 m/s²`.

| field | value |
|---|---|
| mode / source / stop | Experimental / `cruise` / false |
| ego | vEgo 1.523 m/s |
| leadOne / leadTwo | both radar ID40; dRel 12.936, yRel -0.051, vRel -1.594, vLead -0.046, aLeadK -0.983 |
| model lead0 | x 15.095, y +0.008, v 0.179, a -0.103, prob 0.999 |
| extraction | current -0.469, direct -0.518, amplification +0.049 |
| first 6 v/a | v=`[4.59,4.56,4.50,4.40,4.26,4.07]`; a=`[-2.03,-2.04,-2.08,-2.12,-2.11,-2.11]` |
| leadX0 / leadX1 | both `[12.94,13.11,13.55,14.12,14.58,14.59]` |
| min a first 1 s | -0.716 at the transition row |
| nearest 0x1DF / carControl | ACCEL_COMMAND about -0.67; brake request 1; carControl -0.716 |

Classification: **MPC_TRAJECTORY_RESHAPE / gradual**. Closing speed 1.594
m/s, TTC 8.12 s, and 6 m-gap requirement about -0.111 m/s²: **no substantial
braking requirement**. No radar/vision or ID transition within ±0.5 s.

## Complete-chain findings

### Radar leads and duplicate leadOne/leadTwo

At the selected radar-active cycles, leadOne and leadTwo carried the same
Bosch ID and identical geometry in R141-1 through R141-8 and R141-10. R141-9's
first abrupt event was vision in both slots, then ID40 appeared on the later
radar return. This route therefore does not show a second distinct radar lead
being substituted for the selected one at the main low-speed events.

The only dense radar↔vision oscillation in the bookmark windows is R141-8:
ID42 ↔ vision `-1`. It occurs after the first target change, so it cannot by
itself explain the initial R141-8 target step.

### Planner/MPC and output extraction

The strongest low-speed event is R141-5. Its first six published MPC
accelerations are already approximately `[-2.45,-2.40,-2.24,-2.00,-1.76,-1.45]`,
but the production extraction at `action_t` returns only -0.437 while direct
interpolation returns -0.873. The published `aTarget` is -3.348 and then
reaches the -3.5 floor later. Thus the dangerous negative target is not being
created by `get_accel_from_plan()`; the extraction is actually less negative
than direct interpolation in this event.

R141-9 shows a smaller negative extraction difference (-0.230), but the
trajectory itself is negative (`a[0]≈-1.24`) and the nearest command follows
`carControl.accel≈-1.24`. R141-7 has the opposite sign: current extraction is
about +0.024 while direct interpolation is -0.089. Across the bookmarks, the
sign and size are not consistent with a single extraction-amplification bug.

For R141-1, R141-2, and R141-5, the logged `longitudinalPlanSource` remains
`cruise` at the first negative step even though the radar lead is present.
This is not proof that radar is ignored: the lead trajectory is visible in the
plan and the internal source-selection/MPC obstacle state is not logged.
`source=cruise` should therefore be read as the published source label, not as
proof that the radar lead did not influence the solver.

### Early-braking sanity

The simple `dRel / closing_speed` and constant-deceleration-to-6m checks give:

| event | closing m/s | TTC s | 6m-gap decel m/s² | verdict |
|---|---:|---:|---:|---|
| R141-1 | 3.312 | 9.56 | -0.214 | NO |
| R141-2 | 2.750 | 9.23 | about -0.16 at onset; -0.51 at low-speed minimum | BORDERLINE |
| R141-3 | opening | — | 0.000 | NO |
| R141-4 | opening | — | 0.000 | NO |
| R141-5 | 4.484 | 8.68 | -0.305 | NO |
| R141-6 | 1.594 | 20.74 | -0.054 | NO |
| R141-7 | 2.547 | 5.39 | -0.294 | BORDERLINE |
| R141-8 | 9.440 | 12.34 | -0.403 | NO |
| R141-9 | 2.790 | 16.77 | -0.095 | NO |
| R141-10 | 1.594 | 8.12 | -0.111 | NO |

These are sanity checks only; they do not replace the planner's safety model.
They do show that the major negative-command transitions were generally not
forced by an imminent 6m-gap collision under constant-deceleration geometry.

### Honda command path

Where a negative command was available near the event, the nearest raw
`sendcan` `0x1DF` `ACCEL_COMMAND` tracked the already-negative
`carControl.actuators.accel`: approximately -2.43 for R141-5 and -1.23 for
R141-9. There is no route evidence that Honda CAN packing added a second hidden
negative request. Timestamp alignment means a nearest command is diagnostic,
not an exact same-cycle causal pairing, but it is sufficient to exclude a
large extra actuator-side amplification here.

## Final classification

| event | first-step classification | radar/vision or ID change near event | same old S33 failure proven? |
|---|---|---|---|
| R141-1 | UNKNOWN / planner-state candidate | no | no |
| R141-2 | UNKNOWN / planner-state candidate | no | no |
| R141-3 | no abrupt event | no | no |
| R141-4 | gradual MPC trajectory | no | no |
| R141-5 | RADAR_VREL_CHANGE | no | no |
| R141-6 | gradual MPC trajectory | no | no |
| R141-7 | RADAR_VREL_CHANGE | no | no |
| R141-8 | RADAR_VREL_CHANGE; later association flicker | yes, ID42↔vision | no |
| R141-9 | RADAR_ASSOCIATION_CHANGE | yes in inspection window, before bookmark center | no |
| R141-10 | gradual MPC trajectory | no | no |

The Civic-Bosch stale-preference fix is present in the running commit, but the
rlog does not expose Arm A/B counters or the preferred-track ownership state.
There is no defensible way to mark a stale clear as having fired from these
services alone. The route does not reproduce the old S33 ID24 pattern as a
proven cause.

## Remaining uncertainty and next step

The route separates the problem into two workstreams:

1. R141-1/R141-2 and the gradual events need live planner/MPC instrumentation,
   because the published target changes while radar ID, lead geometry, and
   direct action extraction do not identify the internal state transition.
2. R141-5/R141-7/R141-8/R141-9 contain suspicious radar vRel or association
   changes. Those should be replayed against raw Bosch CAN and parser fields,
   but they should not be conflated with the stable-ID planner-state events.

The smallest next experiment is to add temporary, non-production telemetry to
one R141 low-speed window and capture `get_mpc_mode`, obstacle minima,
`a_desired`, solver `a_solution[0]`, pre-clip target, and final target on the
first target step.
