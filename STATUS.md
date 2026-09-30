# Status

**As of: 2026-09-28**

Update the date above whenever this file changes. If it is stale, trust `git log` over this
file.

Repo: StarPilot / openpilot fork `openpilot-radar`. Working branch
`ns-bosch-radar-testing`; `claude/radar-testing-state-88vt2t` is kept identical to it (every commit
is pushed to both). For the current tip, trust `git log`, not this line.

**Latest work (2026-09-24), start here:** item 116 (on-device adaptive P trim prototype, `LatAdaptiveTune` default 0 = off, 1 shadow, 2 apply: one bounded 0.05 step per knot per drive at 20/30/40/50 mph, 0.85–1.15, resets when the manual lateral tuning changes; shadow replay over 19 routes holds 1.00 at every knot on the current tuning, 20 mph never steps up because of override onsets; unit-test/log-replay only, not driven; try shadow first). Then item 115 (continuous lateral gain schedule `LatGainSchedule`, default off, falls back to the bands when absent or invalid, plus offline tuner `tools/lateral/lat_autotune.py`; on 26b+263 it suggests P 120/110/120/105 at 20/30/40/50 mph with I unchanged, about 2 % better on holdout; highway untrusted and frozen; unit-test/replay/sim only, not driven). Then item 114 (route 0000026b: sensor-reaction blips over `NrdrDriverOverrideThreshold` 2000 cut steering torque for ~1 s in low-speed turns and explain the owner's 32:40 exit oversteer and 48:10 stutter; corrected the same day: the 32:40 blips were a sustained driver push below the 2000 threshold, so do NOT raise it; 0.5 s fade-up, then `LatPScaleStandard` 115; replay/sim only). Then item 113 (lateral PID simulator `tools/lateral/lat_pid_sim.py`: open-loop torque replay, fitted steering plant, closed-loop sweeps of the banded lateral scales; validated in the 25–50 mph band on 263 and held-out 268; found that Kp 0.65 was not in effect on 268; suggests I 75 and a trial of `LatPScaleStandard` 115–125; sim evidence only). Then item 112 (radar: route 0000026b, the owner's "best drive yet" on d0b525140 with the hold: all six bookmarks are genuine approaches, the FCW at 39:30.7 was real; the item 111 bound changes nothing here; replay only). Then item 111 (radar: one-sided range bound on Bosch-A coasts behind `RangeDerivedVrel`: on 21 routes only 268 9:55.2 moves (−2.16 → −2.17), 0 protected episodes softened; the 268 9:52 latch brakes about 0.9 s earlier; replay only, not driven, needs a device build). Then item 110 (route 00000268, the owner's first alpha-long drive on build b6619f55, without the hold: the hold changes none of its 9 episodes in replay; the FCW at 11:43.8 was a real approach into slowing traffic, braked hard only after about 1.2 s at −1.0; a D-062 latch at 9:52 coasted a wrong-sign vRel +4.06 for 2.35 s while the live range closed at 6 m/s, and the D-053 assist was blind to it because it disarms on coasts; open design item; replay only). Then item 109 (the item 107 per-track 1 s hold shipped in ffa72fdc after the owner confirmed 237 18:09.4 was a phantom brake; the shipped planner reproduces the prototype on all 214 episodes of 19 routes, 0 protected episodes changed; replay only, not driven; watch curve exits with a lead at 40–70 m). Item 108 is the other agent's C4 marker work. Then item 107 (both item 106 fixes replayed on 19 routes: the 1 s per-track hold fixes 267 15:13.3 (−3.45 → −1.45) and touches only 237 18:09.4, a circular-label alpha brake; the vision-disagreement bound delays a real closing brake on 25f 8:02.6 by 0.35 s and is rejected; nothing shipped, owner decision pending). Then item 106 (stock-ACC routes 266/267 on d20a18d28: 0 protected episodes changed at 0.075; new off-axis false brake 267 15:13.3 lands at bearing 0.070–0.074, under 0.075, so the bearing threshold alone cannot close this class; design question open; replay only). Then item 105 (C4 lead speed labels enlarged to 26 px in-path / 22 px side-lane after the owner's on-road photo; UI only, not rendered). Then item 104 (closed-loop radar + planner replay on 17 routes; `OFF_AXIS_LEAD_MIN_BEARING` 0.10 → 0.075 shipped: 25f 13:58.4 and 260 9:07.8 false brakes −3.45/−3.20 → −1.22/−1.01, 0 of 125 genuine-brake episodes changed; replay only, not driven; 23e 4:54.6 turned out to be a pre-74e live alpha false brake on a curve, which the bound removes; 104a reran with a vision-based label, protected = either label: 0 of 125 protected episodes changed, 0.075 stays). Then item 103 (74c open-loop alpha replay on stock-ACC routes 25d–263: the 25b ~0.7 s hard-lead trail does not reproduce, median +0.05 s vs ACCEL_COMMAND; 25f 13:58.4 is an off-axis false brake at bearing 0.078–0.101, just under the 0.10 bound). Before that: item 91 (D-063 toggle replayed on all 22 alpha-long routes: keep it off; 1 spurious hard brake, 1 delayed brake), item 90 (D-063 variant D'' behind `BoschARailInterval`, default off) and item 89 (stock-ACC route scan, alpha-long watchlist). Earlier: item 74 (route 0000025b) and its sub-items 74a–74g.
74e is a shipped planner change (off-axis Bosch-A lead aLeadK bound); 74f is the stock-ACC data
census and the open follow-ups; 74g lowers the bound's bearing threshold to 0.10 for the 237 false brake.

**Scope note.** This file covers the **radar and longitudinal** work in this repo. The EPS
firmware programme (RWD tunes, the `0x6A0..0x6A8` telemetry stub, the gain bench, UART/UDS
flashing, D-001..D-026) lives in the separate EPS knowledge-base repo and is **not** tracked
here. Where the two touch — the CR-V lateral profile, the steering-ratio curves, the
`extract_drives.py` lineage — that is recorded below as a cross-reference only.

**Open topics to revisit** (parked by decision, not closed):
- **Off-axis lead follow-ups: items 74f/74g.** The 237 942.6 false brake (a real on-road phantom
  brake to aEgo −2.7) is removed in replay by 74g. Two real closings now brake later (25b 665.2 +1.5 s,
  245 40.7 +0.9 s). Needs a road drive on curves with the fix.
- **Stock-ACC behaviour study: item 74f.** Blocked on data: 25b is the only stock-ACC route with rlogs.
- **Brake over-delivery and the low-speed stop-and-go jolt: item 72.** Parked 2026-09-23. Reopen
  when there are about 10 or more low-speed gas-to-brake onsets (below 10 m/s) in rlogs. Today there
  are 3. Also reopen if a drive reports the jolt again.

---

## What the Bosch-A radar work is

Honda's Bosch-A platform exposes a **16-slot object bank** on the camera bus that openpilot
upstream does not parse at all. This branch reverse-engineers it and feeds it to `radard`
as a real radar source, replacing vision-only lead tracking on those cars.

`[CONFIRMED static]` The wire format is one 16-slot bank: each slot has four main frames
(`f0..f3`, one CAN ID each — **not** sub-frames muxed onto a shared ID) plus one
synchronized auxiliary frame. This supersedes the earlier model of `0x280/0x284/0x288/0x28C`
as pieces of a single object, and of `0x2C8/0x2C9` as a separate "coarse" list.

| piece | where |
|---|---|
| Hand-written DBC, 896 signals | `opendbc_repo/opendbc/dbc/honda_bosch_a_radar.dbc` |
| Parser, decode constants, all gates | `opendbc_repo/opendbc/car/honda/radar_interface.py` |
| Lead selection, staleness, shadow telemetry | `selfdrive/controls/radard.py` |
| Enable toggle | Param `BoschARadar` (UI: Longitudinal → "Bosch A Radar") |
| Car set | `HONDA_BOSCH_A` = `HONDA_BOSCH` − radarless − CANFD − alt-radar |

The DBC is **hand-written and not produced by the opendbc generator pipeline.** Its
`VERSION` string records the validation: **361,360/361,360 checksum passes and
214,400/214,400 sequential counter transitions** on route `000001df`. `FRAME_IDX` and
`LIFECYCLE_RAW` are deliberately not named `COUNTER` — the real Honda rolling counter is the
2-bit field at last-byte bits 5:4, alongside the 4-bit checksum at bits 3:0, and both are
declared so opendbc enforces them.

### Decode constants that are firmware-exact, not fitted

`[CONFIRMED static, from firmware]` — do **not** re-fit these against vision:

- **Range scale = 1/16 m per count.** AC004 converts with `(q16 − n)/128` where
  `q16 = sat16(round(8 × raw_range))`, so `range_m = raw_range/16 − n/128`. Corroborated
  three ways: `8 × 4095 = 32760` fits int16 with 7 counts to spare (the `×8` exists to make
  the 12-bit field fill the internal word), full scale is `4095/16 = 255.9 m`, and `/128`
  (Q7) is this firmware's unit for physical quantities throughout. The previous `0.05712`
  was solved from a **single tape point with the offset assumed** and read ~9% short —
  −9 m at 60 m against vision.
- **Range offset is a per-unit calibration value, not a constant.** The firmware term is
  `−n/128`, with `n` assembled from a config word plus a runtime addend; `335` (−2.617 m) is
  only the fallback when the config word reads zero. `−3.0` is retained because it sits
  inside the plausible calibration range. Read it from the radar's own configuration rather
  than re-fitting it.
- **Azimuth = `(raw_angle − 1024)/2048` rad**, closed independently by the `f3` angular-edge
  pair. Supersedes the older empirical 0.032 deg/count fit.
- **Sweep cadence = 14.35 Hz** (median of `0x280` inter-arrival across Peter's routes; p5
  12.5, p95 16.9). This also sets the lead-Kalman `dt` in `radard` — the previous round 15
  ran the filter ~4.5% fast.

### The U11 / u10 velocity channel — the expensive part

`[CONFIRMED, replay + route evidence]` The auxiliary frame carries an 11-bit offset-binary
velocity field (**U11**, `1/64` m/s per count, centre 864) and a 10-bit companion
uncertainty (**u10**). Two hard-won rules govern it, and both were learned by breaking them:

1. **A saturation rail is a bound, not a missing measurement, and it must still be
   published.** Raw 0 and 1728 mean `|vRel| ≥ 13.5 m/s` with the exact value unrecoverable.
   This was briefly routed to the coast path. That was a **safety regression**: a stationary
   car approached above 13.5 m/s (30 mph) rails on *every* sweep, so the coast never ended,
   it outlived `BOSCH_A_STALE_S`, and the point was deleted. Measured on route `000001f9` at
   29:52 — two stopped cars, **88 of 88 active frames on the low rail** with healthy u10
   (78–94), range closing smoothly at −19.4 m/s. The radar lead was dropped, `radard` fell
   back to a vision lead reporting only −11.4 m/s, and the planner commanded **0.00 while
   closing on stopped traffic at 76 m with a 6.6 s TTC. The driver intervened.** See D-041.
2. **u10 is confounded with dynamics; do not re-tune it from offline error statistics.**
   Over 16,834 frames against an event-local reference, median |err| rises 0.26 → 0.88 →
   1.44 → 1.95 m/s across u10 bins 0-64/64-128/128-192/192-256 — but median |a_rel| rises
   0.73 → 2.13 → 3.51 → 4.59 m/s² alongside it (`corr(u10,|err|) = +0.40`,
   `corr(u10,|a_rel|) = +0.43`). The threshold **511** was validated by replaying 20
   bookmarks through the real `RadarInterface` and `radard`'s Kalman filter. Lowering it to
   128 on error statistics alone undid that and caused a measured regression: on route
   `000001f3` at 19:27 u10 sat above 128 for 0.81 s during a real ~8 m/s² lead decel, the
   coast outlived `BOSCH_A_STALE_S`, the lead was deleted, and the vision fallback injected
   a 5 m / 6 m/s step that drove a −3.51 m/s² brake. Restored. See D-042.

`[CONFIRMED]` The **multi-sweep velocity/range consistency check is one-sided by design.**
The per-sweep innovation gate cannot see a velocity error at all — over one ~70 ms sweep even
a 3 m/s error moves the range 0.2 m, far under its 2–5 m thresholds. U11 *lags* true closure
at a deceleration onset (at `000001f3` 19:27 the fitted range rate was −6.7 m/s while U11
still read −2.08), so a symmetric test fires during genuine hard braking — exactly when the
velocity is most needed. Only "U11 claims more closing than the geometry supports" is
evidence of a fault. Checked both ways: `000001eb` 6:59 (U11 −10.58 while the range *opened*
at +0.46, an 11 m/s contradiction across a track-identity change) is rejected; the
`000001f3` onset is not. See D-043.

### Shadow range-derived vRel — telemetry only

`[CONFIRMED static]` `Track.vRelRange` publishes a 5-sample LSQ range rate alongside the
radar's own `vRel`, for **whichever** radar lead is selected — not only Bosch-A. **Nothing
consumes it.** It is plain LSQ with no outlier rejection, so it inherits the range channel's
~1% gross outliers: a diagnostic, not a validated velocity. Timestamps come from the message
clock, not wall clock, so accelerated replay stays faithful.

Motivating measurements: on `000001fe/fb/fd`, U11 detects a closing onset 0.88–1.28 s late
while a 4-sample range LSQ lands within 0.07–0.14 s; on `00000141` R141-8, U11 diverged from
the range by 13.7 m/s while the range moved 1.9 m. It exists to confirm or refute that on a
real drive **before any of it is wired into control.** See D-044.

`[CONFIRMED]` Two defects in this telemetry have already been fixed and are worth
remembering as a pattern, not just as history: `05930e2` — the shadow fields were written to
the **wrong capnp struct**, crashing `radard` on every Bosch-A drive; `d8604bd` — four
further defects where the **test evidence was measuring a stale mirror** of the value under
test. Both passed review first. See AGENTS.md §4.

---

## Build and test environment — solved 2026-09-15, record the recipe

`[CONFIRMED this session]` The repeated note in prior status writeups — "the radard tests
cannot run on this checkout because `msgq/ipc_pyx.so` is not a valid Mach-O binary" / "is a
Linux binary" — was **not** a platform limitation. The checked-in `.so` files are
**aarch64**, built for the comma device:

```
msgq_repo/msgq/ipc_pyx.so: ELF 64-bit LSB shared object, ARM aarch64
```

On any other host they fail to load with `cannot open shared object file`, which reads like
a missing file rather than a wrong architecture. **Rebuild locally and the tests run.**

Two traps to know before you start:

1. **`.venv` at the repo root is a tracked symlink to another machine's home directory**
   (`/Users/jameslichtenstiger/nrdr/openpilot/.venv`, mode `120000`, introduced in
   `82796af`). `uv sync` fails with `failed to create directory .venv: File exists`. Point
   `UV_PROJECT_ENVIRONMENT` elsewhere. Do not delete the tracked link as a side effect of
   unrelated work — retire it deliberately, as its own commit.
2. `uv sync --frozen` does not complete cleanly here (it fails on `pyaudio`, and
   `json-rpc` needs `UV_HTTP_TIMEOUT` raised). The targeted install below is sufficient for
   the radar and longitudinal suites.
3. **The build overwrites 26 tracked device binaries in place.** `git status` after a build
   shows `msgq/ipc_pyx.so`, `common/params_pyx.so`, both acados solvers, `libcereal.a`,
   `pandad` and others as modified. Committing them would ship **x86_64 artifacts to a
   branch that boots on an aarch64 comma.** Stage explicitly; never `git commit -a`. See
   AGENTS.md §10 for the restore command.

### Working recipe (x86_64 Linux, verified end to end this session)

```bash
sudo apt-get update
sudo apt-get install -y clang build-essential xvfb capnproto libcapnp-dev libzmq3-dev opencl-headers \
                        ocl-icd-opencl-dev libeigen3-dev libusb-1.0-0-dev

export UV_PROJECT_ENVIRONMENT=/tmp/opvenv       # NOT the repo's broken .venv
uv venv --managed-python --python 3.12 "$UV_PROJECT_ENVIRONMENT"   # device is 3.12.3; managed CPython ships Python.h
uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" \
  numpy pycapnp pytest pytest-xdist pytest-asyncio pytest-cpp cython scons setuptools \
  smbus2 pyzmq sentry-sdk requests psutil pyserial tqdm zstandard crcmod setproctitle \
  pyjwt libusb1 python-dateutil pycryptodome cffi sympy casadi future-fstrings \
  parameterized hypothesis ruff "raylib<5.5.0.3" qrcode pillow   # last three: UI tests (run under xvfb-run -a)

export PYTHONPATH=$(dirname "$PWD"):$PWD
scons -j8 msgq_repo/ cereal/ opendbc_repo/ common/ selfdrive/
```

`pytest-asyncio`, `pytest-cpp` and `pytest-xdist` are **not optional** — `pyproject.toml`
sets `--strict-config` plus `-n auto --dist=loadgroup`, and without them pytest exits
`Unknown config option` and reports *"no tests ran"*, which looks like a collection problem
rather than a missing plugin.

### Test results, this tree, this session

| suite | result |
|---|---|
| `opendbc_repo/opendbc/car/honda/tests/test_bosch_a_radar.py` | **91 passed** |
| `opendbc_repo/opendbc/car/honda/tests/test_honda.py` | **116 passed** |
| `opendbc_repo/opendbc/car/honda/tests/test_carcontroller_learners.py` | **31 passed** |
| `selfdrive/controls/tests/test_radard_bosch.py` | **26 passed** |
| `selfdrive/controls/tests/test_lead_behavior.py` | **38 passed** |
| `selfdrive/controls/tests/test_lead_follow_policy.py` | **14 passed** |
| `selfdrive/controls/tests/test_following_distance.py` | **18 passed** |
| `selfdrive/controls/tests/test_turn_lead.py` | **34 passed** |

**368 passed, 0 failed.** `test_lead_follow_policy` and `test_following_distance` require
the acados MPC solvers, so `scons selfdrive/` must have completed — collecting them against
an unbuilt tree raises `acados_ocp_solver_pyx.so: cannot open shared object file`, which is
the same architecture trap wearing a different hat.

**`selfdrive/controls/tests/test_leads.py` does not run here** — it drives
`replay_process_with_name` from `selfdrive/test/process_replay`, which spawns real processes
and hangs in this sandbox. Untested, not failing. Running it needs a proper process-replay
environment.

**Lint:** `ruff check` is clean on `selfdrive/controls/radard.py`,
`test_radard_bosch.py`, `lead_behavior.py`, `lead_follow_policy.py`. It reports **2 findings
in `opendbc_repo/opendbc/car/honda/radar_interface.py`** under opendbc's *own* config —
`E303` too many blank lines at line 534, and `B905` `zip()` without explicit `strict=` at
line 601. Both are real and unfixed. Run ruff from the tree that owns the file; opendbc has
its own `pyproject.toml`.

---

## ✅ First real-target Bosch-A route — 2026-09-15

`[CONFIRMED, one 60 s segment replayed through the real parser]` **The sentinel-only era is
over.** Segment `00000231--5782493b00` (device `11c8fa231c0499ed`, car **`HONDA_CIVIC_BOSCH`**,
`radarUnavailable=False`) is the first Bosch-A capture in this project with real tracked
objects. This supersedes the standing caveat that every clean replay had contained only
firmware no-target sentinels.

| | |
|---|---|
| Bosch-A frames | 144,380 — **all 80 addresses**, buses 1 / 2 / 128 |
| Sweep triggers (`0x2FF`) | 1,786 |
| Parser output | **2,878 points across 892 sweeps, 33 distinct track IDs** |
| Range / velocity | dRel 10.9–111.2 m, vRel −13.50 … +4.52 m/s |
| Device-side | `liveTracks` 893, `radarState` 1200 (a lead on **all** 1200) |

Reproduce: `python tools/bosch_a_route_report.py <rlog.zst> --fingerprint HONDA_CIVIC_BOSCH`

### D-041 confirmed on the road, not just in replay

`[CONFIRMED]` The U11 saturation rail is **not** an edge case: **77 samples across 12
distinct tracks hit exactly −13.50 m/s in this single 60-second segment**, and every one of
them was published as a radar point rather than coasted.

The clearest instance is track 58 at t=5.79–6.73 s (y ≈ +10.2…+11.5 m, d 66.9 → 49.3 m):
U11 read the rail on all 14 samples while the **range itself closed 17.6 m in 0.94 s =
−18.69 m/s**, with ego at 16.40 m/s. So the rail understated true closing by ~5.2 m/s —
exactly the documented trade in D-041 — and the point survived. Under the pre-`6126e51`
behaviour those 77 samples would have fed the coast path.

This is the first road evidence that publishing the bound is the correct call, and it
strengthens rather than revisits D-041. It is **not** a licence to re-tune the rail or u10
from one route (D-042).

### Vision and radar disagreed on lead range by ~11 m

`[CONFIRMED]` Around t=37.7 s the model put its lead at `x` 54–57 m (`prob` 1.00,
`y` ≈ −0.1 m) while radar track 6 had it at dRel ≈ 44 m. Allowing for `RADAR_TO_CAMERA`
(1.52 m) that is an ~11 m disagreement. `radard` published the radar range (43.5 m,
`leadOne.radar=1`), which is the right choice — but the match only survives because
`track_matches_vision` uses `dist_scale=0.25`, i.e. a ~13.75 m tolerance at that range. The
margin here is thinner than it looks; worth watching before anyone tightens that scale.

### Bosch-A track IDs are reused within a segment

`[CONFIRMED]` Track ID 58 covers **two unrelated objects 27 s apart**: y ≈ +10.2…+11.5 m
(t 5.8–6.7) and then y ≈ −3.5…−2.5 m (t 33.8–60.0). Bosch-A IDs are 6-bit
(`BOSCH_A_TRACK_ID_MIN=1`, `MAX=0x3F`), so reuse is expected. The second life opens at
vRel +3.03 then reads −2.16 within 0.55 s, which reads like a **fresh** Kalman filter
converging rather than stale state carrying over.

**Settled 2026-09-15 — the filter does reset, but on a one-message margin.** See the section
below; the open item is closed and replaced by a narrower one.

### Track-ID reuse and the lead Kalman filter — settled, with a fragility

`[CONFIRMED static]` Synthetic input driven through the real `RadarInterface` and the real
`RadarD`, against commit `bdf98de`. The question left open above was whether a Bosch-A
track-ID reuse resets `radard`'s lead Kalman filter. **It does — but by object absence, never
by the incarnation boundary the parser actually computes.**

The chain, end to end:

1. **The parser signals the identity change but does not publish it.** A lifecycle
   discontinuity (`life_delta != 2 × frame_delta`) clears the incarnation's range history and
   pops the point. The replacement cannot be republished until a second coherent sample gives
   it a finite derivative (`matured`), so the CAN identity is **absent from `RadarData` for
   exactly one sweep** and then returns *under the same `trackId`*. Pinned by the existing
   `test_in_place_replacement_no_invalid_gap_resets_history_but_keeps_can_id`.
2. **That one-sweep absence is the entire reset signal `radard` receives.** `RadarD.update`
   pops a `Track` — and with it the `KF1D` — only when an ID is missing from the `liveTracks`
   it is looking at. There is no incarnation field on `RadarPoint`: the parser knows the
   identity changed and `radard` cannot.
3. **Observing the gap resets the filter cleanly** (new
   `test_civic_bosch_incarnation_gap_resets_lead_kalman`): the `Track` is reconstructed and the
   new filter is seeded from the new object's own `vLead`, reporting it with **zero** phantom
   acceleration.

So track 58 is reset — though by staleness retirement, not by the lifecycle path, since a 27 s
absence expires `BOSCH_A_STALE_S` many times over. **The lifecycle path is the interesting one,
because it is one message wide.**

**The fragility.** `card.py` publishes `liveTracks` once per sweep (`RadarInterface.update`
returns `None` without a `0x2FF` trigger), i.e. at ~14.35 Hz. `radard` polls `modelV2` at
`DT_MDL` (20 Hz) and reads the **latest** `liveTracks` through `SubMaster`, which keeps no
queue. The gap survives only while the sweep interval stays longer than the model period —
nominally true (median 14.35 Hz, p95 16.9 Hz on `000001df`), but carried by a **single message
with nothing behind it**. Coalesce or drop that one message and the settled filter absorbs the
identity change as a step.

`[CONFIRMED static]` What that costs, measured through the real `RadarD` (new
`test_civic_bosch_coalesced_incarnation_gap_injects_phantom_lead_accel`), with both objects at
constant velocity so the **true lead acceleration is 0 throughout**:

| identity step | peak phantom `aLeadK` | at | back under 0.5 m/s² |
|---|---|---|---|
| −12 → +3 m/s (15 m/s) | **+13.73 m/s²** | 0.49 s | 2.16 s |
| +3 → −12 m/s (15 m/s) | **−13.73 m/s²** | 0.49 s | 2.16 s |
| −0.5 → −6 m/s (5.5 m/s) | **−5.03 m/s²** | 0.49 s | 1.88 s |

≈ **0.92 m/s² of fabricated lead acceleration per m/s of identity step**, in whichever
direction the step runs. For scale, D-042 records a vision fallback injecting a 6 m/s step that
drove a measured **−3.51 m/s²** brake on `000001f3`. The sign matters both ways: a closing→
opening reuse fabricates a *departing* lead and suppresses braking; opening→closing fabricates
an *approaching* one and brakes for nothing.

**This is a characterisation, not a demonstrated on-road defect.** No route evidence shows a
`liveTracks` message being coalesced at an incarnation boundary, and under nominal timing the
reset works. What is established is that the margin is one message and the consequence of
losing it is a multi-m/s² phantom acceleration lasting ~2 s.

**The narrower open item that replaces the old one.** All of the above assumes the radar
*signals* the reuse. Whether Bosch-A can hand an ID to a new object **without** a lifecycle
discontinuity — `life` continuing to advance by exactly `2 × frame_delta` across the change —
is **not established**, and if it can, nothing resets: not the parser's range history, not the
lead filter. That is D-048's “track migrates onto the wrong scatterer” seen from the identity
side, and it needs route evidence to answer. See D-049.

### 🔴 FALSE BRAKE at t≈11 s — radar range drift, and it defeats all three gates

`[CONFIRMED, one segment]` **This is what the driver flagged** (they bookmarked ~26 s after
the event, reporting "a sharp slowdown as if locking on to a much closer target, even though
the lead in front still has plenty of room"). It is a genuine radar fault with a real
actuation consequence, and it is the most important finding in this segment.

**What happened.** Between t=9.1 and 11.35 s, radar track 6 — the selected lead, own lane,
y ≈ 0.0 m — reported its range falling 71.8 → 61.6 m and its `vRel` ramping
−0.59 → **−6.02 m/s**. Over the same window the **vision lead held x ≈ 75–78 m**, `prob`
0.93–1.00, implying `vRel` of only −0.16 to −2.00 m/s. The radar-versus-vision range gap grew
**monotonically: +7.4 → +10.4 → +15.8 → +15.3 → +14.5 m**.

`radard` published the radar lead (`leadOne.radar=1`). The planner commanded **−2.89 m/s²**
and measured **aEgo −4.28 m/s²**. The driver overrode with the accelerator at t≈11.5
(`gasPressedOverride`, `gasPressed`). Track 6's final sample was `measured=0` — coasting,
`vRel` frozen at −4.36 for three samples — and the track then **disappeared for 11.02 s**
(11.35 → 22.36 s), the only dropout over 0.3 s anywhere in the segment. It returned at
53.1 m with a vision gap back down to +7.1 m.

`[INFERRED, high confidence]` The radar **range** on track 6 drifted ~6 m toward the car
while the lead vehicle did not approach. Supporting: vision was stable and confident
throughout; the gap grew monotonically rather than jittering; the track coasted and then died
immediately after; and the driver reports the gap was never closing.

**Why every existing gate passed it — this is the part that matters:**

| gate | why it did not fire |
|---|---|
| Per-sweep range innovation (`..._INNOVATION_MAX_M = 2.0`, hard 5.0) | drift was ~6 m over 1.7 s ≈ **0.25 m per sweep**, far inside 2.0 m |
| One-sided multi-sweep vRel/range check (D-043) | U11 (−6.0) and the fitted range rate (≈ −4.5 to −6.4 m/s) **agreed with each other**. The check only fires when U11 claims *more* closing than the geometry supports, so it **structurally cannot** catch this |
| Gross-distance staleness (`HONDA_BOSCH_A_GROSS_DISTANCE_M = 25.0`) | peak disagreement 15.8 m, **under** the 25 m threshold |

`[CONFIRMED by construction]` The shadow `vRelRange` channel (D-044) is **also blind to
this**: it is an LSQ fit of the same range that drifted, so it would have agreed with U11.
The diagnostic published specifically to cross-check U11 cannot catch a *range* error, and
this event is a range error. That is a real limit on D-044's usefulness and should be
recorded against it.

**The signal that would have caught it is radar-versus-vision range disagreement** — 15.8 m
at a 78 m vision range is ~20%. `HONDA_BOSCH_A_GROSS_DISTANCE_M = 25.0` is too loose to see
it. **This is a candidate, not a change.** Per D-042, one route is not grounds for moving a
threshold, and the two constants previously re-tuned on partial evidence both caused measured
regressions. What is needed first: how often a 10–20 m radar/vision gap occurs on routes
where the radar is *right* (vision range at 70–80 m is itself weak), which cannot be answered
from one segment. **Do not tighten this constant until that distribution is known.**

### Six-segment corpus — two candidate fixes refuted, and a correction

`[CONFIRMED, 6 segments from one drive, ~6 min]` Five further segments
(`f66399a5`, `1be0aa43`, `97566dde`, `9e21cac9`, `bf574f16`) were analysed alongside the
flagged one. **The corpus refutes the threshold candidate this file proposed above**, which is
recorded rather than quietly dropped.

**Radar-versus-vision range gap, pooled** (radar lead selected, vision `prob` ≥ 0.9,
n = 4,868):

| p5 | p25 | p50 | p75 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| −0.2 | +1.4 | **+4.0** | +7.2 | +11.0 | **+14.9** | +21.7 | +27.7 m |

Vision reads **systematically longer** than radar — expected for monocular depth. The
false-brake event's 15.8 m gap is therefore only ~p95, **not an outlier**. Worse, segment
`9e21cac9` runs at a **median gap of 13.8 m with a maximum of 27.7 m and commands no hard
braking at all**. Tightening `HONDA_BOSCH_A_GROSS_DISTANCE_M` toward ~12 m, as suggested
above, would fire continuously on a segment where nothing is wrong. **Candidate dead.**

**Gap *rate* was tested as an alternative and is also refuted.** |d(gap)/dt| pooled: p50 4.7,
p90 22.3, p95 31.1, max 130.2 m/s — vision's frame-to-frame `x` jitter dominates. `9e21cac9`
reaches p95 = 53.7 m/s while braking normally. **Candidate dead.**

`[CORRECTION]` The entry above states the vision evidence showed the radar was wrong. Given
this distribution that was **over-claimed**: a 15.8 m gap at 78 m is within normal vision
spread and proves nothing on its own. The genuine evidence that track 6 was spurious is
(a) it **vanished for 11.02 s** immediately afterwards — the only dropout over 0.3 s in that
segment — and (b) the driver overrode and reports the gap never closed. Treat the gap as
corroborating, not as proof.

**Hard-brake events are too few to tune anything.** Across all six segments there are only
**four** runs with commanded accel < −1.5 m/s² while engaged:

| segment | t | accel | dRel | vRel | vEgo | headway | gap |
|---|---|---|---|---|---|---|---|
| `3a4e0842` **(false)** | 11.21 | −2.89 | 62.4 | −4.36 | 17.6 | **3.56 s** | 14.8 |
| `97566dde` | 43.28 | −2.00 | 40.0 | −2.20 | 19.6 | 2.04 s | 10.5 |
| `f66399a5` | 5.21 | −2.17 | 33.9 | −0.62 | 13.8 | 2.46 s | 6.0 |
| `f66399a5` | 15.15 | −2.40 | 18.5 | −3.53 | 4.5 | 4.09 s | 0.5 |

At highway speed the false event has both the largest headway and the largest gap, but the
low-speed row (4.5 m/s, stop-and-go) has a larger headway still, so headway alone does not
separate them either. **Four events cannot validate a threshold** — this is exactly the
situation D-042 was written about.

### Corpus grown to 16 segments — experimental mode ruled out, and a second failure mode

`[CONFIRMED, 16 segments, ~16 min from one drive]`

**Experimental mode is not implicated in the flagged brake, and does not govern radar-lead
use.** The driver asked, and the data answers cleanly:

- At the flagged brake, `experimentalMode` was **False**. That segment is the only one with a
  sustained False block (False from segment start until t=17.31 s; the brake is at
  t=10.6–11.5 s, and the switch to True comes 5.8 s *after* it ends). So the e2e model was not
  driving longitudinal — the chill/ACC path was, which is what makes the lead attribution
  meaningful.
- Across the corpus, `corr(experimental%, radarLead%) = **−0.084**` — no relationship.
  `corr(visionLead%, radarLead%) = **+0.817**`. Two segments are 100% experimental mode with
  100% and 98.4% radar-lead use.

**The brake began on the radar lead.** `longitudinalPlanSource` runs `lead0` from t=10.2 to
10.8 s as the command ramps −0.52 → −2.70, then hands to `cruise`, which carries the peak to
−2.94. StarPilot's own speed controllers were **flat through the entire window** and are not
involved. The onset is therefore attributable to the radar lead; *why `cruise` binds at the
peak is not explained by these fields* and is left open rather than guessed at.

**A second override event is a CORRECT brake — so override is not a fault label.** On
`3053f5a6` at t=12.57 the command reaches **−3.50 m/s²** (harder than the flagged event) with
`lead0`, a real vehicle at 61 m closing at −12.14 m/s, **vision agreeing at prob 1.00 with a
5.2 m gap**, TTC 5.0 s. The driver overrode anyway. Any future classifier must not treat this
as a false positive.

All six hard-brake events across 16 segments:

| segment | accel | dRel | vRel | headway | TTC | gap | vprob | source | override |
|---|---|---|---|---|---|---|---|---|---|
| `3053f5a6` | −3.50 | 61.3 | −12.14 | 3.20 | **5.0** | 5.2 | 1.00 | lead0 | yes — correct |
| `4b66cbf6` | −3.25 | 72.4 | −13.28 | 6.28 | **5.4** | 21.9 | 0.79 | cruise | no |
| `3a4e0842` **(false)** | −2.89 | 62.4 | −4.36 | 3.56 | **14.3** | 14.8 | 0.98 | lead0→cruise | yes |
| `f66399a5` | −2.40 | 18.5 | −3.53 | 4.09 | 5.3 | 0.5 | 1.00 | lead0 | no |
| `f66399a5` | −2.17 | 33.9 | −0.62 | 2.46 | 54.2 | 6.0 | 1.00 | lead0 | no |
| `97566dde` | −2.00 | 40.0 | −2.20 | 2.04 | 18.1 | 10.5 | 1.00 | lead0 | no |

Note `4b66cbf6`: gap **21.9 m**, larger than the false event's 14.8 — and the brake was
correct (TTC 5.4 s, a near-stationary object at 72 m). **Gap magnitude is decisively not the
discriminator.** The false event is the only one combining hard braking with *both* a long
TTC and a long headway, but with one positive example that is an observation, not a rule.

### The second failure mode: good radar tracks rejected on lateral

`[CONFIRMED]` Radar-lead use tracks vision-lead availability closely (r = +0.82) — four
segments with ~0% radar lead simply have **no lead at all** (`visLead%` of 0.0, 0.0, 0.6,
25.0 on empty road). That is benign, and an earlier framing of it here as a concern was
wrong.

**One segment is a genuine outlier.** `ed6257ef` has a confident vision lead **94.2%** of the
time and **1.84 radar tracks per frame**, yet uses a radar lead **0.8%** of the time. Taking
the nearest-in-range track to the vision lead on every such frame:

| | range residual (radar+1.52 − vision x) | lateral residual |
|---|---|---|
| `ed6257ef` | median **−1.1 m** (p25 −1.6, p75 +0.5) | median **4.30 m** |
| `7b76edd7` | median **−1.2 m** (p25 −1.6, p75 −0.6) | median **4.33 m** |

The tracks agree with vision on **range to about a metre** and are rejected on **lateral**,
where `track_matches_vision` uses `y_std_scale=1.0, y_floor=1.0` — roughly a 1 m tolerance.

**This is the same root cause as the false brake, seen from the other side.** The matcher's
tolerances are inverted relative to the sensors' actual error characteristics: range is gated
loosely (`dist_scale=0.25` → ~15–19 m at 60–78 m) and lateral tightly (~1 m), whereas
Bosch-A is *accurate in range* and *poor in azimuth at distance* (4.3 m lateral at ~70 m is
about 3.5°), and monocular vision is the reverse. So a track whose **range** drifted 15 m kept
matching, while tracks whose range is right to a metre are thrown away on **lateral**.

`[INFERRED]` A lateral tolerance expressed as an **angle** rather than a fixed metric
distance, paired with a tighter range gate, would address both directions. **Not implemented
— see D-048's validation gate.** The tension is real and unresolved: tightening range would
also reject `9e21cac9`, which sustains a median 13.8 m gap while behaving correctly.

### CEM mode chattering — unrelated observation, worth not losing

`[CONFIRMED]` `78270494` shows `experimentalMode` flipping at t=25.17 → 25.25 → 25.36 s —
**80 ms and 110 ms dwell times** — and again at 26.05 → 26.62. Nothing in this corpus ties it
to a control fault, but sub-100 ms longitudinal mode switching is worth a look on its own.

### U11 is a real, independent velocity measurement — not a range derivative

`[CONFIRMED, 9,390 measured track samples across 6 segments]` Worth settling, because the
project has been asked whether Bosch-A has a native vRel at all. It does: U11 in the AUX
frame, and it is **not** simply a differentiated range.

- Correlation with a centred range derivative at zero lag: **0.807** — not ~1.0.
- Cross-correlation peaks at **lag −4 samples (−0.28 s), r = 0.847**: U11 **lags** the range
  channel by roughly 0.28 s on average, consistent with the 0.88–1.28 s onset lag recorded
  earlier for deceleration onsets.
- `|U11 − range_rate|`: median 0.78, p90 2.77, p99 7.12, **max 12.22 m/s**.
- **2.26%** of samples disagree by more than 5 m/s, overwhelmingly with U11 **under-reporting
  opening** (e.g. U11 +0.8 while the range opened at +9.1).

A range-derived field would show r ≈ 1.0 at zero lag with no gross disagreements. So U11 and
the range are two genuinely independent channels — which is what makes D-043's cross-check
meaningful. The honest summary is **not** "there is no native vRel" but "there are two
imperfect vRel sources: U11 (independent, railed at ±13.5, lagged) and the range derivative
(prompt, but only as good as the range)."

**And in the false brake, vRel was not the failure.** U11 (−6.0 m/s) and the fitted range
rate (−4.5 to −6.4 m/s) agreed with each other throughout. Both channels consistently
described an object that was genuinely approaching — the object simply **was not the lead
vehicle**. The defect is in **track-to-object association**, not velocity derivation, and no
amount of vRel cross-checking can catch it because both sources come from the same radar
track. See the proposed direction in `DECISIONS.md` D-048.

### Adjacent-lane closer was never a lead candidate — NOT the flagged event

`[CONFIRMED mechanism, significance not established]` Recorded because it was found while
locating the flag, but the driver's delay means the bookmark points at the t≈11 s false brake
above, not here. At the bookmark instant (t=37.69 s, `userBookmark`) track 58 sat at y ≈ −2.6 m closing at −2.6 to
−3.9 m/s while the lead (id6, y ≈ +0.3 m) closed at only −0.5 m/s. At t=37.8 s track 58 was
**nearer than the lead** (42.6 m vs 44.1 m) and closing roughly 8× faster. It was tracked
continuously and promoted to neither `leadOne` nor `leadTwo`.

The mechanism is not a Bosch-A bug: `match_vision_to_track` only promotes a radar track that
matches a **model** lead, and the model reported one lead at y ≈ −0.1 m. A radar-only target
in an adjacent lane therefore cannot become a lead however fast it closes. Whether that is
the right policy for a cut-in is a longitudinal-planner question, not a parser one, and
nothing here shows the car behaved wrongly — `laneChangeState` stayed `off` and the vehicle
never crossed into own-lane (|y| < 1.8 m).

---

## ✅ Routes now reach an agent session, and the recorded corpus is partly reproduced — 2026-09-15

`[CONFIRMED]` Two routes were fetched from Konik **inside an agent session** and analysed:
`00000231--5782493b00` (32 of 32 rlog segments) and `00000232--fc8dad0d18` (27 rlog segments,
32 qlogs). Both were recorded by device `11c8fa231c0499ed` on **`0083ffa`**
(`ns-bosch-radar-testing`, v0.11.2), car `HONDA_CIVIC_BOSCH`. The standing entry "no Konik route
has been fetched or analysed from an agent session" is retired.

### The laptop can run the whole suite — in an arm64 container, without building

`[CONFIRMED]` The checked-in `.so` files are aarch64 **built against Python 3.12**, and this Mac
runs Colima with an **aarch64** Linux VM. So they load as-is: no `scons`, no rebuild, no
architecture trap. The recipe is `ubuntu:24.04` + `python3-venv` + `libzmq5` (the only missing
shared library) + the pip list from the x86_64 recipe above:

```bash
docker run --rm --platform linux/arm64 -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD":/src/openpilot:ro -v oprad-routes:/routes:ro oprad-test:py312 \
  python -m pytest -p no:cacheprovider -o addopts="" -q selfdrive/controls/tests/test_leads.py
```

Four things bite, all of them recorded because each cost time here:

- **Colima shares only `$HOME` with its VM.** A bind mount of anything under `/tmp` or
  `/private/tmp` silently mounts an **empty** directory inside the container — the report reads
  "Not found", not "permission denied". Route data goes in a **docker volume** (`docker cp`), or
  under `$HOME`.
- **Mount the repo read-only** (`:ro`) and pass `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`
  and `ruff --no-cache`. A read-write mount let a crashed replay drop a 32 MB `core` file into the
  working tree.
- **`/usr/bin/time` does not exist** in `ubuntu:24.04`; wrapping a run in it exits 127.
- **Do not point pytest at `tools/lib/tests/` as a directory.** It collects upstream openpilot
  tests that fork and download into `/tmp/comma_download_cache…`; name this branch's test files.

### Test results on this tree, in that container

| suite | result |
|---|---|
| AGENTS.md §8 suites + this branch's tool tests | **492 passed, 2 skipped, 1 failed** (510 s) — that one failure is fixed by `b9612b2a`, see below |
| `selfdrive/controls/tests/test_leads.py` | **6 passed** (5.2 s) — including `test_radar_fault` |
| tool tests after this session's changes | **147 passed, 2 skipped** (452 s) |

**`test_leads.py` has now run** — the process-replay suite that every prior writeup listed as
unexercised. `test_radar_fault` drives `replay_process_with_name("card", …)` and passes.

**The one failure was real, and it is now fixed by `b9612b2a`.**
`test_far_lead_brake_limit.py::TestDefaultOff` failed with `UnknownKeyName: FarLeadBrakeLimit`,
because the key existed in `common/params_keys.h` (`ebf4c20`) but **not** in the checked-in
aarch64 `common/params_pyx.so`, last rebuilt at `a972d15` — **16 commits earlier**. That file now
reports **17 passed**.

**Say this precisely: the artifacts were not "stale", they were exactly one key behind.** Before
`b9612b2a`, loading the committed `.so` and calling `all_keys()` returned **821 keys** while the
header declared **822**; the only missing one was `FarLeadBrakeLimit`. `BoschARadar`, `BlotV2` and
`HondaBoschARadar` were all present and working throughout.

⚠️ **Do not diagnose these artifacts with `strings`** — that is how this was first (wrongly) argued
here. The `.so` is linked with tail-merged string literals, so a key that is the suffix of a longer
key has no standalone copy: `strings` "proves" `BoschARadar` missing because it only appears inside
`HondaBoschARadar`. Load the `.so` and call `all_keys()`:

```bash
docker run --rm --platform linux/arm64 -v "$PWD":/openpilot -e PYTHONPATH=/:/openpilot \
  oprad-test:py312 python -c \
  "from openpilot.common.params_pyx import Params; print(len(Params(memory=True).all_keys()))"
``` What this cost, before the rebuild:

1. The repo ships a `prebuilt` marker and `launch_chffrplus.sh` only builds when it is absent, so
   **the device ran that one-key-behind artifact** rather than compiling its own.
2. `Params().put_bool("FarLeadBrakeLimit", True)` — the documented way to enable the TEST feature —
   **raised `UnknownKeyName` on the device**, and the Galaxy toggle's write path
   (`the_galaxy.py:461`, a bare `params.put`) has no handler for it, so the row failed to save.
3. Nothing crashed: `longitudinal_planner.far_lead_brake_limit_enabled()` wraps the read in
   `try/except → False` and re-reads every 100 frames, so the exception was caught ~every 5 s and
   the feature was simply inert.

**Resolved in `b9612b2a`** (artifacts only, AGENTS.md §10, pattern `a972d15`). Rebuilt with the
toolchain that produced `a972d15` — Ubuntu 24.04, clang 18.1.3, Python 3.12.3, **Cython pinned to
3.1.4** — and `SP_FORCE_TICI=1` for `arch=larch64`. `params_pyx.cpp` regenerated byte-identical.
Two builds mounted at `/src` and `/work` produced byte-identical binaries. Loading the old and new
`.so` and diffing `all_keys()` shows **821 → 822 keys, the sole difference being
`FarLeadBrakeLimit`, nothing dropped**; `put`/`get`/`remove` round-trip on it.

⚠️ **`scons` will lie to you here.** A rebuild after `git restore` printed
``scons: `common/libcommon.a' is up to date`` and relinked the `.so` against the **old 821-key
archive** — deleting the `.o` files is not enough, because scons trusts `.sconsign.dblite`. Delete
the signature DB and the archive itself (or use `./tools/clean_build_artifacts.sh --sconsign`), then
**check the hash**, or you ship a `.so` that looks freshly built and is not.

This is static verification only — no replay, no road evidence. It makes the toggle writable; it
does not validate the feature, which stays TEST and default OFF.

### Upstream PR state, re-checked

`JamesL787/openpilot` **PR #9 is MERGED** (2026-09-05) and its merge commit `10e4705` is an
ancestor of this branch, so the §8 run above *is* the re-run those records asked for.
`firestar5683/StarPilot` **PR #124 is CLOSED, unmerged** — it was not re-run.

### The recorded corpus: what reproduced, what did not

`[CONFIRMED]` `tools/bosch_a_corpus_report.py` ran on all 32 segments in 38 s. The recorded
hash-labelled segments are identified beyond reasonable doubt, and **the 6-segment corpus is
segments 10–15 and the 16-segment corpus is segments 10–25** of `00000231--5782493b00`:

| recorded label | segment | matched on |
|---|---|---|
| `3a4e0842` (the false brake) | **10** | −2.89 m/s² at dRel 62.4, vRel −4.36, headway 3.57, TTC 14.3; `experimentalMode` False until t=17.3 s (71.1%) |
| `f66399a5` | **11** | both its brakes: −2.40 at 18.5 m and −2.17 at 33.9 m |
| `97566dde` | **13** | −2.00 at 40.0 m, headway 2.04, TTC 18.1 |
| `9e21cac9` | **14** | gap p50 +12.33, max +26.76 (recorded 13.8 / 27.7 before the 1.52 m offset) |
| `4b66cbf6` | **17** | −3.25 at 71.7 m, vRel −13.28, TTC 5.40, `cruise` |
| `3053f5a6` | **19** | −3.50 at 61.3 m, vRel −12.14, TTC 5.05, vprob 1.00, override |
| `7b76edd7` | **24** | lateral residual p50 +4.36, range −1.22 (p25 −1.62, p75 −0.80) |
| `ed6257ef` | **25** | vision lead 94.2% at prob ≥ 0.5, 1.84 tracks/frame, radar lead 0.8%, lateral +4.40 |
| `78270494` | **26** | `experimentalMode` dwells of 78 ms and 112 ms at t=25.25 and 25.37 |

`1be0aa43` and `bf574f16` are segments 12 and 15 in some order; nothing recorded separates them.

**Reproduced** (see D-051 for the two definition differences):

- Pooled radar/vision gap, segments 10–15: **n=4,872** against a recorded 4,868, every percentile
  within 0.9–1.7 m of the recorded value — the `RADAR_TO_CAMERA` offset.
- `corr(visionLead%@0.5, radarLead%)` over segments 10–25: **+0.818** against a recorded +0.817.
- The four "≈0% radar lead" segments: 15, 16, 20, 24 at vision occupancy **0.0 / 0.0 / 0.6 / 25.0**
  — the recorded list exactly.
- The two "100% experimental mode" segments with ~100% radar-lead use: 11 and 12.
- Every hard-brake row's accel, dRel, vRel, headway, TTC and vision probability.
- `tools/bosch_a_route_report.py` on segment 10 reproduces the first-route census **exactly**:
  144,380 Bosch-A frames, 1,786 sweep triggers, 2,878 points over 892 sweeps, 33 track ids,
  dRel 10.9–111.2 m, vRel −13.50…+4.52, liveTracks 893, radarState 1200.

**NOT reproduced, and unresolved in both directions:**

- **U11 versus the range derivative.** Harness (measured points only, runs split at 0.1 s):
  n=10,444, r=0.882 at zero lag, peak at **lag 0**, **9.16%** of samples disagreeing by >5 m/s,
  max 55.05 m/s. Recorded: n=9,390, r=0.807, peak at **lag −4** (r=0.847), **2.26%**, max 12.22.
  The recorded numbers came from code that no longer exists; the harness's own filtering is
  documented but unvalidated. **Do not cite either as settled.**
- **`|d(gap)/dt|`**: harness p50 6.0 / p90 30.5 / p95 43.3 / max 214.6 against recorded
  4.7 / 22.3 / 31.1 / 130.2. Both refute the gap-rate gate; they disagree on how badly.
- **`corr(experimental%, radarLead%)`** over 10–25: **−0.197** against a recorded −0.084. Sign
  agrees, magnitude does not; both are far from explaining anything.

**Two corrections to the recorded hard-brake table**, from the same run:

- The flagged false brake **was** overridden by the driver, and `3053f5a6` too. The earlier harness
  read the override flag at the peak frame only, where the gas press lands ~0.3 s later.
- `3053f5a6` contains **two** runs over −1.5 m/s² (−3.50 at t=12.56, then −3.09 at t=13.41), not
  one. The recorded table lists one.

Whole-drive, three hard brakes fall outside the recorded 16-segment window, including
**segment 7 at −3.50 m/s² with vRel at the −13.50 rail and vision prob 0.58**, driver override.

### `experimentalMode` chattering is real, and not confined to one segment

`[CONFIRMED]` The recorded `78270494` observation reproduces (78 ms, 112 ms) and is not unique.
`00000231` segment 9 switches **10 times**, four of them with dwells of **151, 89, 59 and 54 ms**
within 0.2 s at t≈46.2–46.4. On `00000232`, segment 12 shows 38–196 ms dwells and segment 22 shows
115 ms and 138 ms. Still nothing ties it to a control fault; it is now measured rather than
anecdotal.

### D-044's shadow channel, measured on both drives

`[CONFIRMED, device-side telemetry]` `tools/bosch_a_vrel_shadow_report.py` compares
`radarState.leadOne.vRel` (U11) with `vRelRangeDerived` on the selected radar lead:

| route | frames | r (measured) | `|diff|`>2 m/s | rail samples | rail understatement p50 / max |
|---|---|---|---|---|---|
| `00000231` | 14,446 finite (203 NaN) | **+0.877** | 13.2% | 150 | **+2.19** / +7.37 m/s |
| `00000232` | 15,091 finite (170 NaN) | **+0.854** | 8.9% | 60 | **+2.12** / +9.95 m/s |

So on the rail the range channel says the object is closing **~2 m/s faster** than the published
bound, with a worst case near 10 m/s — the direction D-041 predicted, now quantified on real
drives. **Onset lag is not established**: requiring a crossing to hold 5 samples and pairing it
within 3 s leaves **2 events** (0.19 s and 1.16 s, U11 late) on `00000232` and none on
`00000231`. D-044's recorded 0.88–1.28 s claim is neither confirmed nor refuted by n=2. Note also
that `radarState` repeats at 20 Hz over a 14.35 Hz radar, so these n are inflated by duplicates.

### D-049 gate item 1, answered on one drive and refuted on the other

`[CONFIRMED]` `tools/bosch_a_lifecycle_report.py` replays CAN through the real `RadarInterface`
and counts what the parser itself decided. On **`00000231`: zero lifecycle breaks** in 27,899
sweeps (41,238 continuations, 740 fresh identities, 0 parser errors). An independent check of
segment 10 agrees: 0 range-history clears on a same track object, and the recorded "track 58
reuse" is a **retirement then rebirth** (new objects at t=5.56 s and t=33.34 s), not a lifecycle
break. So the one-message reset D-049 characterises never fired on that drive — a latent hazard,
not a live one.

`00000232` is the opposite, and it exposed a parser defect rather than a reset: see the section
below.

**Seamless reuse (gate item 2) remains open.** Of 18 lateral steps >1.5 m with no break on
`00000231`, 14 are consecutive-sweep runs — a smooth sweep of a real target across the car frame
(track 32 walked y +10.3 → −1.4 m over seven sweeps at a steady ~51 m), not an identity swap.
Four isolated steps on `00000231` and three on `00000232` remain as candidates; none is confirmed.

---

## 🔴 The lifecycle counter saturates after ~137 s and the parser deleted the lead — fixed 2026-09-15

`[CONFIRMED on two drives, offline replay + the device's own recording]` **This is the most
consequential finding in this session, and it explains symptoms the driver reported in chat.**

`LIFECYCLE_RAW` is a 12-bit counter that advances by 2 per frame index, so it reaches its highest
even value **0xFFE = 4094 after 2,047 frames — about 137 s of continuous tracking** at the ~14.9 Hz
sweep rate — and then stops advancing. It is *not* the invalid sentinel (0xFFF): STATUS, range,
azimuth and track id all stay valid and the object is still physically there.

The parser's continuity rule `life_delta == 2 × frame_delta` therefore fails on **every** sweep once
the counter pins. Each failure cleared the range history and popped the point, so no point ever
matured again: **the object was observed every sweep and published on none of them**, for as long as
it stayed visible.

| route | track | age at saturation | suppressed for | published during |
|---|---|---|---|---|
| `00000232--fc8dad0d18` | id 37 | **137.4 s** | **121.8 s** (1,815 sweeps) | **0** |
| `00000232--fc8dad0d18` | id 34 | 137.5 s | 12.3 s (184 sweeps) | 0 |
| `0000020a--1fd2b58eda` | id 38 | — | segments 5→8, ~3.7 min | 0 after t=5:05 |
| `0000020a--1fd2b58eda` | id 51 | — | segments 11→12, ~95 s | 0 |

Track 37's last published geometry before it vanished was **dRel 38.9 m, yRel −0.1 m** — the lead we
were following.

**The device's own recording corroborates it independently of any replay.** On `00000232`, recorded
`liveTracks` carry id 37 in 894/894 frames of segment 8 and 569/893 of segment 9, then **0** in
segments 10, 11 and 12, while the radar lead goes from 1200/1200 frames to **0/1200**. On
`0000020a`, same CAN, device (pre-fix `0083ffa`) versus this tree's parser:

| segment | device published id 38 | with the fix |
|---|---|---|
| 5 | 76/894 (8.5%) | 890/894 (99.6%) |
| 6 | **0/893 (0.0%)** | 831/893 (93.1%) |
| 7 | **0/894 (0.0%)** | 894/894 (100.0%) |
| 8 | **0/893 (0.0%)** | 735/893 (82.3%) |

**The fix** (`BOSCH_A_LIFE_SATURATED`, in `radar_interface.py` with its evidence block): a
saturated→saturated step is treated as a continuation, because a counter pinned at its maximum
cannot testify to identity either way. Per D-041/D-042 the safe direction is to keep publishing
geometry — the range-innovation gate still judges every sweep and staleness still retires a genuine
disappearance. **Cost, recorded against D-049: an ID reuse that happens *while* the counter is
saturated cannot be detected at all.**

Verified after the fix: id 37 publishes **1,788/1,815 sweeps (98.5%)** across the same window, id 34
180/184 (97.8%). The five-route census now reports **0 chronic runs everywhere** (`0000020a` 2 single
one-sweep breaks, `0000020b` 2, `00000213` 1, `00000231` 0, `00000232` 2 — all of them the ordinary
D-049 one-sweep case). Negative control per D-009: a counter
frozen at any *non*-saturated value is still a lifecycle break, pinned by
`test_a_stuck_but_unsaturated_counter_is_still_a_lifecycle_break`.

`[NOT VERIFIED]` Offline replay only. Nothing here shows how the car behaves with the lead restored.

---

## The five flagged drives — what each event actually was, 2026-09-15

`[CONFIRMED, device-side telemetry + offline replay]` Three further routes were fetched and analysed
against timestamps the driver flagged in chat: `0000020a--1fd2b58eda` (17 rlog segments),
`0000020b--60b34177d9` (38) and `00000213--0b61770c26` (23). The driver's own `userBookmark` presses
land 5–25 s *after* each quoted time, confirming the chat timestamps are the events themselves.

| flagged | what the data shows |
|---|---|
| **5:05** semi-hard stop | **Correct brake** — lead genuinely decelerating (vLeadK 18.7 → 5.7, aLeadK −5.7), vision agreeing at prob 1.00, command −3.45. But the radar lead **vanished mid-manoeuvre at t=5:05.17** — the saturation defect above — and the lead handed to vision for the next ~3.7 min. |
| **7:43** stop then creep | Stop at only **−1.2 m/s²** on a **vision** lead (radar still suppressed), ending with the driver on the brake. During the creep the radar briefly offered tracks *further away* than vision (id 26 at 16.8 m vs vision 14.0; id 24 at 7.4 vs 6.6) with negative `vLeadK`. |
| **9:53** "random brake" | **Not a range-drift false brake.** At full rate the radar range moves smoothly (50.8 → 45.9 m over 2.3 s), per-sweep innovation 0.00–0.32 m, `measured` throughout; the apparent radar/vision divergence is **vision x jitter of ±3 m** sweep-to-sweep. The lead really did decelerate mildly (vLeadK 23.5 → 21.4) and the planner commanded **−1.67 m/s² for a lead 48 m away closing at <1 m/s** (TTC ≈ 56 s). That is braking authority, not a sensor fault. **`FarLeadBrakeLimit` would not have caught it**: its regime needs headway ≥ 3.0 s and this was **2.07 s**. |
| **6:06** | Braking −1.1…−1.41 with **no lead at all** (vision prob 0.15–0.50 at ~130 m), then −2.60 against radar id 16 at **94.4 m, y +2.3 m, vLeadK 2.3** — a near-stationary, off-lane object at 94 m, vision prob 0.52. |
| **12:18**, **28:44** | Ordinary lead-deceleration braking on an in-lane radar lead; −1.6 and −1.9 peak. Nothing anomalous. |
| **29:52** | **Not openpilot.** From t=47.1 the car is **disengaged with the brake pedal pressed** (`en0`, `brk1`, commanded accel 0.00) while the driver slows 22.0 → 10.4 m/s. |
| **15:12** curve braking | Lead id 56 at 21–28 m through a curve (steering to +12°, curvature −0.0045). `aLeadK` swings **−1.7 to −3.0 while `vRel` is positive and the range is opening**; commands −1.4…−1.73. The lead filter is manufacturing deceleration out of curve geometry. |
| **16:04** cut-out | The real event is at **t=16:15**. Radar id 44 **keeps its track id** while its motion steps discontinuously in one 0.28 s sweep: dRel 61.6 → 59.3 but `vRel` **+0.45 → −3.62**, `aLeadK` −0.74 → −3.39 → −5.11. Command ramps to −3.45, measured **aEgo −4.81 m/s²**, driver overrides with the gas. The parser recorded **no lifecycle break** on that route at that time. |

**On "FCW".** There are **no FCW or collision `onroadEvents` anywhere** in the sampled segments — the
instrument works (311 event messages, 10 distinct names: `cruiseMismatch`, `gasPressedOverride`,
`pedalPressed`, `laneChange`, …). The `radarState.leadOne.fcw` bit is set on **70.4%** of frames on
`0000020b` and **100%** on `0000020a` segment 9, so that bit is not an alert indicator. The four
"FCW" timestamps are brake events, listed above.

`[OPEN]` **16:04 is the best seamless-reuse candidate yet found** (D-049 gate item 2): an identity
that keeps its id while its motion changes discontinuously, with no lifecycle break for the parser
to see. It is equally consistent with the radar genuinely re-measuring onto the revealed slower car.
Distinguishing the two needs the raw per-slot data at that instant, which has not been done.

---

## 🟠 The far-lead limit was inert on the fault it exists for — fixed and re-replayed 2026-09-16

`[CONFIRMED in replay, 39 segments]` `FarLeadBrakeLimit` as shipped in `ebf4c20` did essentially
nothing on the **t≈11 s false brake** (seg 10 of `00000231--5782493b00`) it was written for.
Replayed at its own toggle: **2 frames fired, 6 altered, peak `aTarget` −2.9075 → −2.9012 m/s²**.
It clipped 0.25 s of tail *after* the peak had already been commanded. The earlier "8 frames
altered, max reduction 0.89 m/s²" figure recorded above was measured the same way and is not in
conflict with this — what was missing was the observation that **none of it lands on the event**.

**Root cause.** The call site stood down entirely whenever `get_close_lead_brake_cap` had returned
a cap. Instrumenting the planner shows frames 203–224 — the fault window — **never reached the
function**, because that cap was non-empty across exactly those frames. `get_close_lead_brake_cap`
has **no distance gate**, fires out to ~68 m, and on this segment it is itself the mechanism
issuing the false brake. The feature deferred to the thing it was meant to bound.

**Why removing the stand-down alone is not enough.** Dropping the deference fixes seg 10 — peak
−2.901 → −1.950 m/s², 21 frames — but produces a **false positive on a correct stop-and-go**:
`0000022e--2c6875ff90` seg 8, t 37.6–41.9 s, 88 altered frames, up to 0.631 m/s² of relief on a
brake where radar (27.1 m) and vision (29.9 m) **agree**, `modelProb` 0.99–1.00, `aLeadK`
−0.45 → −2.47, ego 13.4 → 2.7 m/s, ending in `brakePressed` at 41.94 and a disengage at 42.24.
That is a real deceleration and the limit must not touch it.

The headway gate does not separate the two, because **`dRel / v_ego` rises as the car slows**: an
ordinary brake satisfies a 3.0 s headway on its way down. What separates them is absolute distance
— the fault sits at 61–64 m, the correct brake at 27 m.

**The change: drop the blanket stand-down, add `FAR_LEAD_BRAKE_LIMIT_MIN_DIST = 40.0` m.** Measured
across the variants tried:

| variant | seg 10 peak | seg 10 fires | 15 corpus controls | 23 road segments |
|---|---|---|---|---|
| as shipped (`ebf4c20`) | −2.901 | 2 | 0 | 0 |
| drop the stand-down only | −1.950 | 21 | 0 | **6 fires — false positive** |
| `MIN_TTC` 10.0 → 8.0 | −1.950 | 21 | 0 | bit-identical to the row above |
| fix the ramp anchor (below) | −2.818 | 18 | 0 | — |
| **shipped: stand-down dropped + `dRel ≥ 40 m`** | **−1.950** | **21** | **0** | **0** |

**Acceptance evidence.** Frame-by-frame diff of replayed `longitudinalPlan.aTarget`, toggle OFF vs
ON, against the patched tree through the **stock** `plannerd` process config, over **39 segments** —
`00000231--5782493b00` segs 10–25, all 10 of `0000022e--2c6875ff90`, all 13 of
`0000022f--8acb9d34ac`:

```
segments compared: 39
  CHANGED  231 seg10: 21 altered frames, maxD 1.4807 m/s2, 21 fires
segments with any altered frame: 1
```

Exactly one segment in the set changes, and it is the fault. `test_far_lead_brake_limit.py`:
**21 passed**.

**Margin on the 40 m threshold — it is not wide everywhere.** Counting frames that pass every gate
*except* distance: on `0000022e--2c6875ff90` 3,351 pass and **none** sit in the 30–40 m band; on
`00000231--5782493b00` 8,010 pass and 294 sit in that band; on `0000022f--8acb9d34ac` 1,736 pass
and **376** sit in it. The threshold is doing real work on `0000022f`, and a route carrying a
genuine far-lead range-drift fault at 35 m would land on the wrong side of it.

**This is replay evidence only, on one fault. There is no road evidence for the amended logic.**
The feature stays TEST and default OFF. Its positive evidence base is still **n=1**; what the
39-segment diff buys is a bound on the false-positive side, not a second fault.

**More routes would move this, and these specific shapes are what is missing:** highway cut-ins and
merges settling at 40–70 m (the regime the limit now owns, with no example of a *correct* hard brake
in it); downhill or trailing-throttle following at 45–60 m; and any second instance of long-range
radar range walk, which is the only thing that can take the positive evidence past n=1.

### KNOWN DEFECT, pinned and deliberately not fixed: the ramp anchor

`[CONFIRMED]` `get_far_lead_brake_limit` computes
`floor = accel_min + ramp * (FAR_LEAD_BRAKE_LIMIT_ACCEL - accel_min)`. The unit tests pass
`ACCEL_MIN` (−3.5) as `accel_min`, for which ramp 0 means "no restriction" and ramp 1 means −2.0 —
correct. **The call site passes `output_accel_min`**, which is −0.5 on most of the fault frames, so
intermediate ramp values land between −0.5 and −2.0: the limit **clamps hardest when it is least
confident**. Observed floors on the fault: −1.20 to −1.37.

This is worse than a sign error, because the confidence signal is self-defeating: `ttc = dRel /
-vRel` is derived from the **same corrupted `vRel`** that causes the fault, so TTC collapses
1153 → 10.14 s and the ramp collapses 1.00 → 0.04 exactly when braking is hardest.

Fixing the anchor makes the feature **less** effective on the fault (−2.818 vs −1.950), because the
inversion is accidentally compensating for the collapsing ramp. It is left in place, pinned by
`TestKnownRampAnchorDefect` in `test_far_lead_brake_limit.py` (marked *PINNED, NOT ENDORSED*), so
the behaviour cannot drift silently. **Do not "tidy" this anchor without re-running the 39-segment
diff** — the number it produces today is load-bearing and is not the number the docstring implies.

### `process_replay` could not build `CarParams` at all

`[CONFIRMED]` Separately, and the reason none of the above could be measured at first:
`selfdrive/test/process_replay/process_replay.py:357` called `get_car()` with the pre-StarPilot
signature and died with `TypeError: get_car() missing 1 required positional argument: 'params'` on
any replay that fingerprints. `params` is now passed positionally and
`starpilot_toggles=get_starpilot_toggles()` explicitly — that argument's `None` default is a lie,
`opendbc_repo/opendbc/car/car_helpers.py:321` reads `starpilot_toggles.force_fingerprint`
unconditionally. The import is done inside the function on purpose: `get_starpilot_toggles()` has a
`SubMaster` as a default argument and would open a socket at import time in every process that
merely imports this module. Verified by a stock-config replay that now fingerprints for real:
`HONDA_CIVIC_BOSCH`, source 1, fuzzy True, cached True, fw_count 22.

⚠️ **The same break still exists at `opendbc_repo/opendbc/car/panda_runner.py:17`**, which calls
`get_car(self._can_recv, self.p.can_send_many, self.p.set_obd, True, False)`. It is in a vendored
subtree and is a standalone runner, so it was left alone deliberately rather than fixed in passing.
Anyone using that runner will hit the same `TypeError`.

---

## 🟡 The shadow `vRelRange` channel is now wired into control behind a toggle — 2026-09-16

**TEST feature, default OFF, param `RangeDerivedVrel`, Bosch-A only. Never run on a car.**
Decision and rejected alternatives: **D-053**. Constants and their evidence: the
`RANGE_VREL_ASSIST_*` block in `selfdrive/controls/radard.py`.

D-044 published `vRelRange` — a 5-sample LSQ of d(dRel)/dt — as telemetry and said nothing consumed
it. That is no longer true. With the toggle on, for the lead track only, the range rate may push
the published closing speed **more closing, never less**.

### What it does, precisely

| | |
|---|---|
| Scope | Bosch-A cars only; `RadarD.prev_lead_track_ids` only (leadOne/leadTwo) |
| Direction | one-sided — `disagreement = vRel - vRelRange`, acted on only when **positive** |
| Arming | 2.0 m/s sustained across 5 consecutive **measured** updates (0.35 s) |
| Cap | 8.0 m/s of extra closing |
| Geometry | dRel ≥ 8.0 m and \|yRel\| ≤ 1.5 m → azimuth ≤ 10.8°, cos 0.982 |
| Touches | `radarState.leadOne/leadTwo` `vRel` and `vLead`, and the lead KF (so `aLeadK`) |
| Does **not** touch | `Track.vRel` / `Track.vLead` — so `track_matches_vision`, `vision_track_probability` and the adjacent-lane detectors are unchanged |
| Disarms | on a coast, a range dropout, leaving the geometry gate, the flag going off, or the disagreement reaching zero |
| Holds | on a **duplicate** radard cycle — no new `liveTracks`, so nothing to re-decide. Not the same thing as a coast; see below |

Because it never edits the track's own velocity, this changes what is reported **about** the chosen
lead and never **which** track is chosen. That separation is deliberate — see D-053 rejected
alternative 2.

### Why it exists

* **The rail.** D-041, `000001f9` at 29:52: U11 pinned at −13.5 m/s on 88/88 active frames with
  healthy u10 while the range closed at −19.4 m/s. D-041 published the rail as a bound and left
  recovering the true value "to a separate, validated change". This is that change, unvalidated.
* **The lag.** D-043/D-044, `000001fe/fb/fd`: U11 is **0.88–1.28 s late** to a closing onset where
  a 4-sample range LSQ lands within **0.07–0.14 s**. `000001f3` at 19:27: fitted −6.7 vs U11 −2.08.

### 🔴 The hazard — read this before touching a constant

**This is a velocity check that reads the range channel, so a range error is invisible to it.** The
t≈11 s false brake above is a range error: track 6 walked 71.8 → 61.6 m while vision held 75–78 m
at prob 0.93–1.00 and the real gap grew. U11 (−6.02) and the range fit (−4.5 to −6.4) **agreed**.
This file already records that the shadow channel is blind to that fault; the assist inherits the
blindness exactly.

`[INFERRED from the recorded figures — driven through the real Track object in a unit test,
NOT replayed]` on those numbers the worst disagreement is **+0.38 m/s against the 2.0 m/s
threshold**, so the assist stays inert there. The margin is **1.62 m/s**. That is the only thing between this
feature and amplifying the one false brake this branch has recorded.
`TestTheRangeWalkFault` pins it. **Do not "fix" that test** — if it starts failing, the feature has
become the amplifier, not the test.

### What was verified, and by what method

* `[CONFIRMED — static unit test]` `selfdrive/controls/tests/test_range_vrel_assist.py`, **47
  passed**: default-OFF, one-sidedness across the whole disagreement axis, the arming count,
  single- and double-gross-outlier rejection, the correction cap, both geometry gates, coast and
  dropout disarm, continuous decay as U11 catches up, the KF path, and the `000001f9` rail and
  `000001f3` onset cases recovering toward the range rate.
* `[CONFIRMED — static unit test]` `TestRadardLoopCadence` drives the **real** radard interleave —
  a 20 Hz loop over the 14.35 Hz radar, so ~1 cycle in 4 carries no new `liveTracks` message — and
  pins that the assist arms there, that a duplicate cycle changes nothing, and that a coast still
  clears. See the subsection below; this is where the first implementation was wrong.
* `[CONFIRMED — static]` D-009 negative controls: `TestNegativeControlOfTheTestsThemselves` breaks
  the arm count, the disagreement threshold, the lateral gate and the duplicate-cycle hold in turn
  and asserts each guarded property actually fails.
* `[CONFIRMED — static]` No regression in the §8 suites: honda **240 passed**; radard / lead
  behaviour / lead follow policy / following distance / turn lead / far-lead brake limit
  **152 passed**; `test_leads.py` (process replay, including `test_radar_fault`) **6 passed**.
  `ruff check` clean on `radard.py` and the new test file.
* `[CONFIRMED — static]` The x86_64 `common/params_pyx.so` was rebuilt in this container and
  `Params().get_bool("RangeDerivedVrel")` returns `False` by default.

### A duplicate radard cycle is not a coast — the defect this nearly shipped with

`[CONFIRMED — static]` `RadarD` runs at the 20 Hz model rate over a 14.35 Hz radar and collapses
two conditions into one bit (`measured = pt.measured and radar_fresh`), so `Track.update` sees
`measurement_update = False` both when **no new message arrived** (a duplicate, ~1 cycle in 4,
`t_now` unchanged, point data unchanged, lead KF not stepped) and when a **coast** arrived (new
message, `t_now` advanced, parser's measured bit clear).

The first implementation cleared on both. That resets the arm count roughly every fourth cycle,
so five consecutive qualifying fits are unreachable and **the feature would have been permanently
inert on the car** — while all 41 unit tests passed, because every one of them fed exactly one
update per radar sweep. It was caught by re-reading the call site before committing, not by the
tests. The two are now separated by whether `t_now` advanced, which needs no new constant.

The general lesson is worth more than the fix: **a Bosch-A unit test that feeds one
`Track.update` per sweep is not testing what radard does.** Anything downstream of
`measurement_update` needs `TestRadardLoopCadence`'s interleave, or it is testing a cadence the
car never runs at.

### What is NOT verified

* **No replay and no road evidence for the feature ON.** The `test_leads.py` process replay
  above ran with the param at its default, so it shows the **OFF** path is unchanged and nothing
  more. Unlike `FarLeadBrakeLimit`, there is no OFF-vs-ON segment diff for this. The next agent
  should run one before anything else — the 39-segment harness used for the far-lead limit is the
  right tool, and the expected result is **zero altered frames on all 39**, because no segment in
  the corpus contains a sustained 2 m/s U11-vs-range disagreement on a lead track.
* The `000001f9` rail and `000001f3` onset cases are driven here as **synthetic constant-rate range
  series with the recorded velocities**, not as log replays. They show the arithmetic works; they
  do not show the feature would have helped on those drives.
* The 8.0 m/s cap is sized from **n = 2** recorded events (5.9 and 4.6 m/s). It is a bound on
  damage, not a fitted value.

### 🔴 CONFIRMED ON THE CAR: the toggle renders but cannot be switched on — 2026-09-16

**Observed on a real device** (Galaxy at `/device_settings`): the row renders in the right place,
directly under Far-Lead Brake Limit, and toggling it returns a red banner —

> Parameter 'RangeDerivedVrel' is not editable.

**This is open item 12 firing, not a UI bug.** The row placement and gating are correct; the key
does not exist in the registry the device is running.

The chain, end to end:

1. `common/params_keys.h` declares `RangeDerivedVrel` — but that header is **compiled into**
   `common/params_pyx.so`, and the checked-in `.so` is the aarch64 one built by `b9612b2a`,
   which predates this key.
2. `the_galaxy.py:601` `_build_default_params()` enumerates **`_params_raw.all_keys()`** — the
   `.so` registry. The key is not in it.
3. `_get_param_type_info()` builds `allowed_keys` from that list, so the key is absent.
4. `PUT /api/params` hits `if key not in allowed_keys` and returns **403** with the banner above,
   before any `put` is attempted.

**Verified [CONFIRMED, static]** against the committed blob, not the working tree — the working
copy is this container's x86-64 scons rebuild and is `skip-worktree`, so it proves nothing about
the device:

```bash
git show HEAD:common/params_pyx.so > /tmp/committed.so
file /tmp/committed.so                                  # ELF aarch64
strings -a /tmp/committed.so | grep -x FarLeadBrakeLimit   # PRESENT -> its toggle works
strings -a /tmp/committed.so | grep -x RangeDerivedVrel    # ABSENT  -> 403
```

`strings` is trustworthy **for these two keys specifically**: the tail-merging caveat in open
item 4 only bites keys that are a suffix of a longer key, and no declared key ends with either of
these. It does still lie about `BoschARadar` (a suffix of `HondaBoschARadar`).

**Do not work around this in Galaxy.** Adding the key to an allowlist by hand would let the PUT
through to `params.put`, which raises `UnknownKeyName` on the same missing registry entry; and
even if it stored, `_range_vrel_assist_enabled()` reads through the same `.so` and returns
`False`. The result would be a toggle that looks like it saved and does nothing — strictly worse
than the honest 403. The 403 is the gate working correctly.

**The fix is the larch64 rebuild, and it is the only fix.** It is a **deliberate, separate
commit** (AGENTS.md §10); follow the recipe and the scons-lies warning in open item 4 verbatim,
and expect the key count to go 822 → **823**.

**It cannot be done in this container** — checked 2026-09-16: no docker daemon, no `qemu-user`,
no aarch64 cross-compiler, and the local toolchain is Python 3.11.15 / Cython 3.3.0 against the
pinned Python 3.12.3 / **Cython 3.1.4** that `b9612b2a` reproduced byte-identically. It needs a
machine that can run `--platform linux/arm64`.

**A native on-device build unblocks the toggle but does NOT close open item 12.**
`[CONFIRMED — run on the car, 2026-09-16]` Building on the comma itself produces a working
larch64 `params_pyx.so` with the key present, which is enough to make the Galaxy row editable and
`_range_vrel_assist_enabled()` return the stored value. It is **not** the reproducible
pinned-toolchain artifact, so it must never be staged or pushed, and the committed `.so` stays at
822 keys until item 12's docker recipe is run properly.

Two traps found doing this, both worth knowing before anyone repeats it:

- **`scons common/` fails on the device**, at `common/transformations/coordinates.cc`:
  `fatal error: 'eigen3/Eigen/Dense' file not found`. AGNOS ships no eigen headers. This is a
  sibling SConscript (`common/SConscript:31`) and is unrelated to the params binary, but with
  `-j4` scons aborts **before linking `common/params_pyx.so`**, so the build looks like it ran
  and the key is still missing. Build the single target instead:
  `scons -j4 common/params_pyx.so`. Do not install eigen or touch `common/transformations/` —
  its committed aarch64 `.so` is correct and unchanged by this branch.
- **Do not remove the `prebuilt` marker** to force a rebuild. `launch_chffrplus.sh:153` runs
  `./build.py` when it is absent, and **this branch has no `build.py` at the repo root**, so
  removing it breaks the launch.

Verify the result with `all_keys()`, never `strings` (open item 4's tail-merging caveat).
`PYTHONPATH` must be the **parent** of the openpilot dir, i.e. `/data` on the device:

```bash
PYTHONPATH=/data python3 -c "from openpilot.common.params import Params; \
k=Params(memory=True).all_keys(); print(len(k), b'RangeDerivedVrel' in k)"   # expect: 823 True
```

`RangeDerivedVrel` alone is not sufficient to make the assist act. `is_bosch_a_radar_car(CP)`
(`selfdrive/controls/radard.py:107`) requires `CP.radarUnavailable == False`, which
`opendbc_repo/opendbc/car/honda/interface.py:56-59` sets from the **`BoschARadar`** param when
CarParams is built. So `BoschARadar` must be on too, and it only takes effect after an
offroad→onroad transition; `RangeDerivedVrel` is re-read every 100 radard frames and can be
flipped onroad.

An openpilot update that resets the working tree drops the device back to the committed 822-key
binary, at which point the key silently reads `False` while the UI still shows it on. Re-run the
`all_keys()` check before trusting the toggle after any update.

### The Galaxy row: same location as the far-lead brake limit — 2026-09-16

Both surfaces now carry the row, and **both gate it the same way the far-lead brake limit is
gated**. The two rows are deliberately siblings: same section, same parent, adjacent, same gate.

| Surface | File | State |
|---|---|---|
| On-device (raylib) | `selfdrive/ui/layouts/settings/starpilot/longitudinal.py` | In `_bosch_a_radar_rows`, immediately after `FarLeadBrakeLimit`; inherits that section's advanced + Bosch-A gating |
| Layout metadata | `starpilot/common/assets/device_settings_layout.json` | Immediately after `FarLeadBrakeLimit`; `parent_key: AdvancedLongitudinalTune`, `settings_tier: advanced`, `requires_offroad: true` |
| Galaxy (web) | `starpilot/system/the_galaxy/assets/components/tools/device_settings.js` | `BOSCH_A_REQUIRED_KEYS`, hidden unless `BoschARadarAvailable` |

**The Galaxy gate was the one real gap.** The layout entry and the raylib row were already in
place, but Galaxy's `isSettingVisible` carried a hand-written `param.key === "FarLeadBrakeLimit"`
check and nothing for `RangeDerivedVrel`, so on the web UI the new row would have rendered on
**every** car — including cars with no Bosch-A radar, where the feature cannot do anything. That
single-key check is now a two-key set, `BOSCH_A_REQUIRED_KEYS`, so adding a third Bosch-A TEST row
means adding a string rather than another branch.

**Correction — Galaxy's write path is NOT generic.** An earlier revision of this section said
it was. `PUT /api/params` checks `key in allowed_keys` from `_get_param_type_info()`, and that
set is built by `_build_default_params()` from **`_params_raw.all_keys()`** — the compiled
`params_pyx.so` registry, not `params_keys.h`. A key absent from the `.so` is rejected with
**403 `Parameter '<key>' is not editable.`** before any `put` runs. See the blocker below: this
is the path that actually fires on the car.

**Verified [CONFIRMED, static]:** `node --check` on the frontend, `json.loads` on the layout, and a
new test — `test_bosch_a_test_toggles_share_one_galaxy_location_and_gate` in
`starpilot/system/the_galaxy/tests/test_device_settings_layout.py` — pinning section, parent,
tier, offroad flag, default, adjacency and the Galaxy gate across all three surfaces at once.
Negative-controlled per D-009: dropping the key from `BOSCH_A_REQUIRED_KEYS` fails it, and moving
the row away from its sibling fails it. 21 passed in that file, 116 passed across it plus
`test_range_vrel_assist.py`, `test_radard_bosch.py` and `test_far_lead_brake_limit.py`; ruff clean.

**Not covered:** nothing here renders the page. These are source-level assertions that the two
rows agree; they do not prove Galaxy draws the toggle, and no car has been looked at. Note also
that `starpilot/system/the_galaxy/tests/test_device_settings_frontend.py` has **5 failures at
HEAD**, unrelated to this work (a developer-mode notice missing from the JS and CSS) — confirmed
pre-existing by re-running them against a stashed tree.

### Where the native value went

Nothing was removed and the capnp schema is unchanged. When the assist is active, `radarState`'s
`vRel`/`vLead` carry the correction and `leadOne.vRelRangeDerived` still carries the raw fit; the
**native U11 `vRel` for the same track is recoverable from `liveTracks`** by matching
`rr.points[].trackId` against `radarTrackId`. So a log still contains all three numbers and the
comparison the D-044 channel exists for stays auditable.

---

## 🟡 D-053 reworked after replay — 2026-09-16

`[REPLAY, open loop — not road evidence]` The original D-053 was replayed through the real
`radard.Track` on every Bosch-A sweep of `00000232`, `00000236`, `00000237`, `00000239` and
`0000023a` (script `d053dump.py`; instrument check against logged `vRelRangeDerived`/`aLeadK`
matched: median |diff| 0.000, ≥93% of frames under 0.01 m/s). It **helped** on real rail/onset
closings (236 12:51, 18:55) but **hurt** on two recorded range faults: the `00000232` 3:02.8 range
walk (59.0 → 56.1 → 59.1 m while U11 read +2.1 → +0.1 → +1.1) and the `00000236` 22:13.6
new-track settle (77.2 → 59.5 m in 1.8 s, hit the 8.0 cap). Because it fed the corrected vLead
into the lead KF, `aLeadK` — which the MPC brakes on — dipped to −3.8 / −7.2 / −6.0 / −4.5 / −5.9
m/s² on replay.

**The rework (in `radard.py`, same toggle):** a 15-sample (~1 s) long range fit must agree with
the 5-sample fit for 5 consecutive updates; clear-only guards on long-fit residual (0.6 m), span
(0.6–1.5 s), ego speed (≥5 m/s), a lead that would read as driving backwards (>5 m/s), and a rail
rule (on the U11 −13.5 rail the long fit alone decides); the correction never takes the lead
below 0 m/s; and **the KF stays on native U11**, so `aLeadK` is unchanged by construction. Every
number carries its evidence in the comment block. 74 unit test functions in
`test_range_vrel_assist.py` (was 43), each guard with a negative control.

Open-loop gain = reduction in |published vRel − centered ±0.7 s range fit|, integrated (m/s·s):

| Route | Original: active / gain+ / gain− / min aLeadK shift | Rework: active / gain+ / gain− / aLeadK |
|---|---|---|
| 232 | 21.8 s, hurt at 3:02.8 / min aLeadK shift −3.8 | 1.1 s / +0.4 / −0.2 / native |
| 236 | 27.5 s, hurt at 22:13.6 / −7.2 | 7.4 s / +12.7 / −0.5 / native |
| 237 | 33.5 s / −6.0 | 18.8 s / +35.0 / −0.0 / native |
| 239 | 16.4 s / +15.9 / −1.3 / −4.5 | 5.9 s / +7.1 / −0.0 / native |
| 23a | 9.3 s / +6.6 / −0.1 / −5.9 | 0.7 s / +0.5 / −0.0 / native |

**What bites:**
- **Both recorded phantoms are held off by ONE arm update.** At `ARM_UPDATES = 4` the 232 walk lets
  1.0 m/s·s through and the 236 settle 0.4. Do not lower it.
- **Onset latency is 0.77 s** from a closing kink to the first correction (original: 0.42 s),
  against a measured U11 onset lag of 0.88–1.28 s. The margin is ~0.1 s.
- **It is blind to a range error that U11 agrees with** (the t≈11 s false brake) — unchanged.

**Bookmarks on 239/23a (feature not running on either):** `00000239` 10:33.7, phantom hard brake
then driver gas: lead track's yRel went −0.9 → −3.7 while range fell 74 → 61.5 m and U11 went
+1.5 → −7.5, radar lead dropped at 10:31.5, vision held 69–75 m. Looks like an **association
fault**; the rework's |y| ≤ 1.5 m gate keeps it inert there and it cannot fix it — needs a raw-track
look. `0000023a` 6:23.3, stop-and-go hard brake closing to 17.8 m after a ~1 s radar lead dropout at
6:20.5; disagreement 1.7 < 2.0, rework inert. Neither is a parser lockout.

**Lockout census, D-054 implemented `[REPLAY]`:** on 232 / 236 / 237 / 239 / 23a, old parser → D-054:
- Locked object-time: 6.5 / 7.3 / 14.1 / 6.7 / 9.6 % → 1.9 / 3.2 / 7.4 / 3.6 / 7.8 %.
- Followed-lead-lost ≥1 s episodes: 8 / 8 / 9 / 1 / 2 → 2 / 3 / 4 / 0 / 0.
- Published sweeps went up on every route.
- No new lead-lost episode appeared. Full table and the per-sweep A/B are in D-054.

## Handoff — what is live, what is untested, what bites

**The four contract files are the handoff.** `AGENTS.md` → `STATUS.md` → `DECISIONS.md` →
`CLAUDE.md`, in that order. `.claude/hooks/session-start.sh` prints them at the top of every
session; on a non-remote machine it prints the contract and then skips the dependency install
and build, which is correct — do not "fix" that by making it build on a laptop.

**More than one agent writes this branch.** As of 2026-09-15 there are three: two Claude Code
sessions on separate accounts and a local one. `git pull` before you start and before you
push; a rejected push means someone else moved, so read their commits before merging (a real
example is `7344dc4`, where the other session had landed `D-049` and the corpus harness).

### Awaiting a road test

**`FarLeadBrakeLimit` (`ebf4c20`, amended 2026-09-16) is a TEST feature, default OFF.** It bounds
braking demanded for a lead far away in both time and distance, and it is the only behavioural
change in this work. **As originally shipped it was inert on the fault it was written for** — see
*The far-lead limit was inert on the fault it exists for* above for why, and for the fix. Current
replay evidence: 39 segments, toggle OFF vs ON, **exactly one segment changes** — seg 10 of
`00000231--5782493b00`, the flagged false brake: 21 altered frames, peak `aTarget`
−2.901 → −1.950 m/s². Zero altered frames across the other 38 segments. Its positive evidence base
is still **one example**, which is why it is off by default and labelled TEST. Enabling it is a
deliberate act: `Params().put_bool("FarLeadBrakeLimit", True)`. It carries a **known, pinned defect
in its ramp anchor** — read that subsection before touching the function.

**`RangeDerivedVrel` (2026-09-16, REWORKED the same day) is a TEST feature, default OFF.** It lets
the range-derived closing rate correct the Bosch-A native U11 velocity for the lead, one-sided and
bounded — see *D-053 reworked after replay* below and **D-053**. It has **open-loop replay evidence
on five routes and no road evidence**: the reworked version never ran on a car. It **is now
reachable on the car** once the device is on `b2baba87` or later (open item 12 closed). Routes
`00000239` and `0000023a` were driven on `fa262e0c`, before that fix, and `RangeDerivedVrel` is
absent from their `initData`: **the feature did not run on either**. Enabling it is a deliberate act:
`Params().put_bool("RangeDerivedVrel", True)`, offroad, then cycle offroad→onroad.

Everything else committed in this work is tooling, tests or documentation. No default
behaviour has changed.

### Known traps on a laptop

- **You cannot build this tree on macOS.** The checked-in `.so` files are aarch64 and the
  build needs capnp/zmq/eigen/OpenCL. Anything importing `cereal`, `opendbc.can` or
  `params_pyx` will not run there. The pure-Python tools are written to degrade instead:
  `konik_login.py`, `plain_http.py` and `konik_preflight.py` need only `requests`.
- **The skip-worktree protection is remote-only.** The hook that marks the 53 tracked device
  binaries runs under `CLAUDE_CODE_REMOTE`. On a laptop those flags are not set — which is
  harmless while you cannot build, but never `git commit -a` regardless.
- **macOS CLT Python 3.9 is linked against LibreSSL 2.8.3** and cannot complete a TLS
  handshake with `api.konik.ai`. `plain_http.py` falls back to the system `curl`; the tools
  report which transport they used. If you see the curl note, that is expected, not a fault.
- **`python`/`pip` do not exist on macOS** — `python3`/`pip3` only.
- **The standalone tools must stay Python 3.9-compatible.** That macOS CLT Python is 3.9;
  `pyproject.toml` sets ruff's `target-version = "py311"`, so lint here will happily push a
  3.11-only construct into a file a user runs on 3.9. That already happened once:
  `from datetime import UTC` (3.11+) was written by ruff's `UP017` autofix and the preflight
  died at import on the user's machine. `tools/lib/tests/test_py39_compat.py` now AST-parses
  the three standalone tools at `feature_version=(3, 9)` and greps for a ratchet list of
  too-new runtime names; `UP017` is disabled for those three files in `pyproject.toml`.
  Note the limit: no 3.9 interpreter exists in the agent container, so this is a static check,
  not a real 3.9 run.

### Still open, in priority order

See **Next** at the end of this file. The short version: the Konik transport is verified
from the user's laptop (7 passed / 1 warning, 2026-09-15) but nothing has yet decoded a
Konik-fetched rlog, and no route has reached an agent session by any path other than a manual
file upload; `test_leads.py` has never been run; and D-048's validation gate is unmet, which
is why the far-lead limit ships off.

---

## Tooling added 2026-09-15

**`tools/konik_preflight.py`** — verifies a Konik (or comma) server end to end from a machine
where the network actually works. Agent containers cannot: this environment's policy answers
**403 to CONNECT** for `konik.ai`, `api.konik.ai` and `api.commadotai.com`, so no agent session
can reach a route. Run it on your laptop or the comma and paste the output back.

It walks reachability → token → `/v1/me` → devices → routes → files → an actual ranged rlog
fetch → **Bosch-A content**. That last step is the one specific to this repo: it counts Bosch-A
object frames by CAN ID and bus, `liveTracks`, and `radarState` leads, and warns explicitly when
frames are present but no lead was ever reported — which per this file is what every clean
replay so far has actually contained. A route that uploads cleanly but carries no Bosch-A frames
will not advance the radar work, and finding that out locally costs seconds.

The script mirrors the 80 Bosch-A CAN IDs so it runs on an unbuilt checkout;
`tools/lib/tests/test_konik_preflight.py` asserts that mirror against opendbc exactly, because
a drifted copy would report "0 Bosch-A frames" on a route full of them.

**It does not trust the newest route.** A comma uploads qlogs eagerly and holds rlogs for
WiFi, so the route you just drove is routinely qlog-only — which is what the first live run
hit. Reporting "qlogs only" there and stopping is true and useless, because it reads as *this
path cannot deliver radar data* when the account may hold rlogs a few routes back. So when the
newest route has no rlogs the script walks back up to `--scan-routes` (default 10) older
routes, names the first one that does, and **downloads from that route**, proving the data
path on an rlog rather than on a qlog. `--route` disables the walk-back entirely: an explicit
route is the user's choice and is never second-guessed. When nothing in range has rlogs it
warns and says why (WiFi, or request the segments), rather than failing — the transport is
still proven at that point, and hiding that would be the worse error.

**`tools/bosch_a_corpus_report.py`** — the missing corpus harness. Pools **device-side**
behaviour across the segments of a drive: per-segment and pooled radar/vision range-gap
distributions, `|d(gap)/dt|`, range and lateral residuals against the vision lead, radar- and
vision-lead occupancy, `experimentalMode` occupancy and its correlation with radar-lead use,
U11 versus a centred range derivative with the lag of the cross-correlation peak, and
hard-brake events with headway, TTC, `longitudinalPlanSource` and override.

It is the offline twin of `bosch_a_route_report.py` in the same sense `konik_preflight` is:
the route report replays CAN through the real `RadarInterface` and answers *what the parser
would publish*; this one reads `radarState`, `modelV2`, `carControl` and `longitudinalPlan`
and answers *what the device actually did*. Segment collection is imported from the route
report rather than copied, so the two cannot drift.

```bash
python tools/bosch_a_corpus_report.py <route.zip|dir|rlog> --json corpus.json
```

Two things it gets right that are easy to get wrong, and both are pinned by tests:

- **The lateral residual is a SUM** (`yRel + lead.y[0]`), because radar `yRel` is car-frame
  left-positive and model `y` is device-frame. `track_matches_vision` adds them; differencing
  would report ~2× the residual on any off-centre track and ~0 on a genuinely mismatched one.
  The tests locate the real matcher's accept/reject boundary and assert the report reads the
  tolerance exactly there, so a drift in `radard` breaks them.
- **Hard brakes are grouped into runs**, reported at each run's peak. STATUS.md's counts are
  runs ("only **four** runs with commanded accel < −1.5"); a 1.5 s brake is ~30 frames, so a
  per-frame table would inflate the event count by an order of magnitude — exactly the
  false sample size D-042 warns about.

`[NOT VALIDATED AGAINST A ROUTE]` Its geometry, arithmetic and extraction are tested — the
last against a synthetic segment of real capnp Events with hand-computed answers — but it has
**never been run on a real drive**, so message rates, dropouts and clock skew are unexercised.
Until it re-derives the recorded figures on `00000231--5782493b00`, its output is a fresh
measurement, and a disagreement with the numbers above is **unresolved in both directions**,
not a correction to either.

**`tools/bosch_a_scenarios.py` + `tools/bosch_a_viewer.html`** — drives synthetic Bosch-A CAN
frames through the **real** `RadarInterface` and records what the parser decided on every sweep,
then renders it. Not a simulation: every published number came out of the parser. Frame builders
are imported from the Bosch-A test module rather than copied, so they cannot drift.

Five scenarios, each tied to a decision: `closing_lead` (baseline), `saturation_rail` (D-041),
`high_u10_decel` (D-042), `vrel_contradiction` (D-043), `no_targets` (the honest baseline —
renders empty, because that is what the data we have actually contains).

```bash
python tools/bosch_a_scenarios.py --html viewer.html   # rebuild the page
python tools/bosch_a_scenarios.py --scenario saturation_rail   # JSON for one scenario
```

Published viewer: <https://claude.ai/artifact/PAWLymcsRvobb9waW87KuT>

### What the scenarios show

`[CONFIRMED, synthetic input through the real parser]` **D-041 holds.** A stopped car approached
at 19.4 m/s rails U11 on all 60 sweeps, and the parser publishes a point on 59 of them, pinned at
the −13.5 m/s bound. Longest coast 0.07 s, well inside `BOSCH_A_STALE_S`.

`[INFERRED, needs a real route]` **Two scenarios coast far past the stale limit.**
`high_u10_decel` publishes nothing for 14 consecutive sweeps (0.98 s) and `vrel_contradiction`
for 34 (2.37 s), against `BOSCH_A_STALE_S = 0.20 s`. That is the shape of the failure D-041 and
D-042 describe — a coast that outlives the stale limit, after which the point is deleted and
`radard` falls back to vision. **These inputs are synthetic and may not be representative**: the
`high_u10_decel` gap begins where the scenario's own range clamps, so part of it is likely an
artifact of the construction rather than parser behaviour. This is a question to put to a real
route, **not a demonstrated defect**, and it must not be treated as one.

---

## Alpha Long P061B — exact onset captured; carried over, not re-verified here

> The material in this section was established in the EPS knowledge-base repo against
> routes and forks not present in this checkout. It is carried forward because it governs
> the Honda longitudinal code on this branch. **Nothing in it was re-verified in this
> repo this session** — treat the route claims as prior evidence, and re-derive before
> relying on any of them for a new change.

Route `00000002--aa8501ddcb` (JamesL787/openpilot `ns-bosch-radar-testing`, commit
`7f2bab7b…`) contains the exact P061B onset. At 951.918310 s, PCM-side CAN `0x400` changes
from zero to `06 1b 01 02 …` and keeps broadcasting the code. For **3.681 s immediately
beforehand**, Alpha Long continuously sent positive `GAS_COMMAND` together with negative
`ACCEL_COMMAND`, `BRAKE_REQUEST=1` and `BRAKE_LIGHTS=1` on Honda `0x1DF`. The route contains
**1,584 such contradictory frames**.

`[CONFIRMED static/log analysis]` The installed source gates gas on drag/grade-adjusted
`gas_force > 0` but gates braking independently on **raw** `accel < −0.2`, allowing both
paths at once. `[INFERRED, high confidence]` This is the P061B trigger: the exact onset
during a sustained contradiction matches Honda's time/integrated torque-monitor semantics
and explains the cross-fork/stock-ACC A/B. `[CONFIRMED]` It is **not** memory exhaustion —
control processes are flat after engagement, available RAM never falls below 554.64 MiB, and
there is no OOM, process restart, CAN invalidity, or openpilot `accFaulted` sample.

**Do not use** the faulting Alpha Long build, or test commit `6e583e1c43c5…`, on this
vehicle. Route `00000003--1423cb6de2` proves the test commit's raw-zero gas gate causes
severe closed-loop acceleration/coast oscillation: in its only 87.3 s longitudinal
engagement the gate suppressed a still-positive calculated gas value for ~23.96 s and
repeatedly reapplied hundreds of gas units as requested acceleration crossed zero. It did
prevent gas-plus-brake in that route, but 87 s cannot validate a fault that took ~585 s of
engagement to appear. See D-033.

**Current candidate `694046f33f58…`** derives brake entry (`adjusted force < −0.12 m/s²`)
and release (`> −0.02 m/s²`) from the **same** grade/aero-adjusted quantity used for gas,
with an explicit stopping override and a CAN-boundary gas inhibitor. Open-loop replay cuts
route-4 brake runs 39 → 11; on the complete fault route it preserves gas while removing
braking from all 1,584 conflict frames and cuts brake runs 22 → 11, with **zero replayed
gas-plus-brake frames**. See D-034, D-036.

Its predecessor `57d77a7e1918…` was first vehicle-tested on route `00000004--dcc6a5b59e`:
substantially better than the raw-zero candidate, but it did not restore pre-fix smoothness.
In 291.24 retained active seconds, 2,336 brake frames (46.72 s) occurred while reconstructed
grade/aero-adjusted tractive force was positive; 1,987 of those suppressed a positive
calculated gas output, concentrated in lead-following on positive-pitch inclines, including
561 frames just below the raw −0.2 m/s² threshold.

**This is command replay, not closed-loop validation.** It cannot predict the changed future
speed response or prove PCM acceptance. No P061B appears in the route-4 windows, but their
total active duration is **shorter than the original time-to-fault**, so the fault correction
remains unverified.

### Upstream PRs (state as last recorded — re-check before citing)

- `JamesL787/openpilot` **PR #9** — candidate merged through target tip `3f27c6faaf5b…` as
  merge commit `1ddce1708420…`. Reported `MERGEABLE`/`CLEAN`, diff confined to the three
  intended Honda controller / CAN packer / regression-test files. Post-merge: 232 Honda
  tests and 393 applicable Panda Honda safety tests pass (271 expected skips).
- `firestar5683/StarPilot` **PR #124** — the same final arbitration ported from StarPilot
  `Dom` tip `9d1043ad0114…` as `3a811e9622d9…`, adapted to StarPilot's `CarParams` CAN-packer
  interface and preserving its separate Accord 11G MVL crossover. Reported `MERGEABLE`/
  `CLEAN`, same three-file diff. StarPilot Honda suite 210 tests; Panda Honda safety 369
  tests (267 expected skips); Ruff clean. The owner reports **no fault recurrence so far and
  smoother longitudinal behaviour, especially in full E2E mode** — that is limited road
  evidence, not proof of long-duration P061B prevention or universal thresholds. See D-038.

In both records, the planner/`radard` tests "could not load locally" for the architecture
reason now solved above. Re-run them.

---

## Related lanes (cross-reference only — not this repo's branch)

`[carried over]` An alternate OpenPilot lane at `RiskyBiscuit-arc/openpilot` `arc-dev`
carries the firmware-extracted 30-point CR-V steering-ratio curve, additive lateral-control
telemetry, and the EPS `0x6A0..0x6A8` extractor; PR #3 (`70e0773f…`) corrects VGR ordering so
measured `currentCurvature` uses the direct measured-angle rack ratio before
`VehicleModel.calc_curvature`. Branch `codex/night-star-bosch-radar-telemetry` (`c62d4034c4`)
is the tester-gated CR-V Bosch-A parsing lane built from JamesL787 `f96cfdb8f7…`; both
retained CR-V rlogs contain the complete object family on `CanBus.camera` (bus 2), with 136
and 352 `0x2FF` sweep triggers, offline parser replay completing every trigger with no CAN
decode error — **all objects were firmware no-target sentinels.** See D-027, D-028, D-030.

---

## NOT verified — do not treat as safe

- **Still no closed-loop road validation.** One segment now proves the parser tracks real
  objects (see the section above), but that is offline replay of a recorded drive: it says
  nothing about how the car behaves when this radar drives the planner.
- **The P061B correction is unproven.** Route 4's active duration is shorter than the
  original time-to-fault. Replay cannot predict the changed closed loop or PCM acceptance.
- **Fusion timing is untested here.** `radard` runs at the ~20 Hz model rate while Bosch-A
  measures at ~14.35 Hz; the duplicate-payload path (`measurement_update=False`) is covered
  by unit tests only, never on a live bus.
- *Resolved 2026-09-15 (evening).* **`test_leads.py` has now run** — 6 passed, including
  `test_radar_fault`, which drives `replay_process_with_name("card", …)`. It runs in the arm64
  container described above; it still cannot run on macOS directly (`SocketEventHandle` needs
  eventfd, and that test is skipped on Darwin by its own marker).
- *Resolved 2026-09-15 (evening): routes now reach an agent session end to end. The walk-back
  preflight passed **8/8** live, `tools/konik_fetch.py` pulled **five routes in full**, and all
  five were decoded and analysed in the arm64 container — so step 8's payload check is done, on
  a different machine than the fetch. What remains true is only the last line below: a remote/
  cloud agent container still cannot reach `konik.ai`. Original entry kept for the record.*
- **The Konik transport is verified from the user's laptop; no route has reached an agent
  session over it.** On 2026-09-15 the user ran `tools/konik_preflight.py --dongle-id
  11c8fa231c0499ed` on macOS and it returned **7 passed, 0 failed, 1 warning**: DNS,
  HTTP 401 on `/`, a valid token (expires 2026-12-14), `GET /v1/me`, **551 routes**,
  a file listing, and a ranged download of 0.5 MB at 0.3 MB/s. Every HTTPS call fell back to
  the system `curl` (LibreSSL 2.8.3), as designed. Two limits stand:
  * **Segments are served from `api.konik.ai` itself**, not a separate CDN — so one host
    covers both the metadata and the data path. Good for a network policy, but it means the
    storage host has *not* been exercised as a distinct allow-list entry.
  * **Step 8 was SKIPped** — `cereal` is not importable on that laptop, so nothing has
    decoded a Konik-fetched rlog and confirmed Bosch-A content end to end. The transport is
    proven; the payload is not.
  The agent container's own policy still answers **403 to CONNECT** for `konik.ai`, so the
  fetch must happen on the laptop or the comma either way.
- **Fresh routes are qlog-only, and qlogs are useless here.** The newest route on the account
  (`11c8fa231c0499ed|00000233--e03fb98cc3`, 2026-09-15T21:06Z) listed **0 rlog segments and
  4 qlog segments**. The device sends qlogs eagerly and holds rlogs for WiFi. qlogs are
  decimated and drop the CAN data, so a qlog-only route cannot support any radar claim.
  `konik_preflight.py` now walks back up to `--scan-routes` (default 10) older routes to find
  one that has rlogs, names it, and downloads from *that* route. **Resolved 2026-09-15
  (evening):** the walk-back was run and found `11c8fa231c0499ed|00000232--fc8dad0d18` with
  **27 rlog segments**, one route back from the qlog-only newest. Five routes have since been
  fetched in full — `0000020a` (17 segments), `0000020b` (38), `00000213` (23), `00000231` (32),
  `00000232` (27).
- The checked-in `.so` files remain **aarch64**, and a local build still overwrites 53 of
  them. The SessionStart hook rebuilds and masks them, but a session that skips the hook
  will hit both.
- 🟡 **The recorded corpus numbers are PARTLY reproduced — see the reproduction section above
  and D-051.** Reproduced: the pooled gap distribution (n=4,872 against a recorded 4,868, every
  percentile within the 1.52 m `RADAR_TO_CAMERA` offset), `corr(visionLead%@0.5, radarLead%)`
  (+0.818 against +0.817), the per-segment identities, and every hard-brake row's kinematics.
  **Still NOT reproduced, and unresolved in both directions:** the U11-vs-range-derivative
  statistics (9.16% gross disagreement against a recorded 2.26%; peak at lag 0 against −4),
  `|d(gap)/dt|`, and `corr(experimental%, radarLead%)` (−0.197 against −0.084). The original
  defect that caused this is unchanged and is why it cost a session to sort out: The original defect: the 6- and 16-segment results
  above (pooled radar/vision gap percentiles, the
  `|d(gap)/dt|` distribution, `corr(experimental%, radarLead%)`, the U11-vs-range-derivative
  cross-correlation, the hard-brake tables, the per-segment lateral residuals) were recorded
  in commits `5edbd59`, `69e1683` and `bdf98de`, **all three of which touch only `STATUS.md`
  and `DECISIONS.md`**. `tools/bosch_a_route_report.py` is the only committed route tool and
  it computes none of those quantities — it counts frames, replays the parser, and reports
  points/tracks. So the numbers cannot be re-derived, re-checked, or re-run on a new route,
  and they are unbound to a commit in the sense AGENTS.md §3 requires. They are recorded
  above as prior evidence and not as reproducible until the new harness has actually re-derived
  them. That run is also **D-048's validation-gate item 2** and D-049's item 3, so it still
  blocks both designs — writing the harness did not clear them, running it will.

*Resolved 2026-09-15, previously listed here:* the two `radar_interface.py` ruff findings
(`edef432`) and the dangling `.venv` symlink (`edef432`).

## Next

1. **Done 2026-09-15 (evening)** — five routes fetched and analysed in-session. Fetch any
   further route with:
   ```bash
   python3 tools/konik_fetch.py --route '11c8fa231c0499ed|<route>' --out <dir outside the repo>
   ```
2. **Done 2026-09-15 (evening)** — `test_leads.py` runs: 6 passed, including the
   process-replay `test_radar_fault`.
3. **Done 2026-09-15 (evening)** — `JamesL787/openpilot` PR #9 is **merged** and its merge
   commit `10e4705` is an ancestor of this branch, so the §8 run (492 passed / 1 failed /
   2 skipped) *is* that re-run. `firestar5683/StarPilot` PR #124 is **closed unmerged** and was
   not re-run.
4. **Done 2026-09-15 (`b9612b2a`)** — `common/params_pyx.so` and `common/libcommon.a` rebuilt;
   `FarLeadBrakeLimit` is now writable on the car. The `.so` went from 821 keys to **822**,
   matching the header. Verified by loading the old and the new `.so` and diffing `all_keys()`:
   the sole difference is `FarLeadBrakeLimit` and nothing was dropped; `put`/`get`/`remove`
   round-trip on it; `test_far_lead_brake_limit.py` goes 16 passed / 1 failed → **17 passed**.
   Nothing else had drifted — this was never a general "the artifacts are stale" problem, and it
   must **not** be diagnosed with `strings` (see the test-results section).

   The rebuild used the toolchain that produced the committed artifacts: Ubuntu 24.04,
   clang 18.1.3, Python 3.12.3 and **Cython pinned to 3.1.4** (3.3.0 regenerates
   `params_pyx.cpp` with ~8k lines of churn and a different `.so`), with `SP_FORCE_TICI=1` to
   select `arch=larch64` and `SP_SCONS_CACHE_DIR` set because the larch64 path hardcodes
   `/data/scons_cache`. Locally that is the `oprad-build:cy314` image:
   ```bash
   docker run --rm --platform linux/arm64 -v "$PWD":/work -w /work \
     -e SP_FORCE_TICI=1 -e SP_SCONS_CACHE_DIR=/tmp/sconscache oprad-build:cy314 \
     bash -lc 'export PATH=/opt/venv/bin:$PATH; scons --cache-disable -j$(nproc) \
       common/libcommon.a common/params_pyx.so'
   ```
   Mount at **`/work`**: the generated `params_pyx.cpp` embeds its source path in a metadata
   comment, so mounting elsewhere adds a spurious one-line diff. Builds at `/src` and `/work`
   were otherwise byte-identical, so this is reproducible.

   ⚠️ **Verify the hash afterwards — scons will claim success without rebuilding.** A second
   pass after `git restore` printed ``scons: `common/libcommon.a' is up to date`` and relinked
   the `.so` against the **old 821-key archive**. Removing the `.o` files is not enough; scons
   trusts `.sconsign.dblite`. Delete the signature DB and the archive
   (`./tools/clean_build_artifacts.sh --sconsign`), then confirm the hash changed.

   Shipping rebuilt device binaries stays a deliberate, separate commit (AGENTS.md §10,
   pattern `a972d15`); `b9612b2a` contains those two binaries and nothing else.

   **This is static verification only — no replay, no road evidence.** It makes the toggle
   reachable; it does not validate the feature, which remains TEST and default OFF. Note also
   that the Galaxy row carries `requires_offroad: true`, `settings_tier: "advanced"` and
   `parent_key: AdvancedLongitudinalTune`, so it is editable only while parked, with developer
   mode on, under an enabled parent — and only on cars whose fingerprint is in `HONDA_BOSCH_A`.
5. **Done 2026-09-15** — a real-target route exists; see the section above. The follow-on
   is the shadow `vRelRange` channel (D-044): this segment carries 77 railed samples and an
   ~11 m vision/radar range disagreement, which is exactly the material that channel was
   published to be judged against. Compare `vRelRange` with U11 on this route before anything
   is wired into control.
6. **Done 2026-09-15** — a track-ID reuse does reset the lead Kalman filter, by object
   absence rather than by the incarnation boundary the parser computes, and the reset is
   carried by a single `liveTracks` message. See *Track-ID reuse and the lead Kalman filter*
   above and D-049. Two follow-ons, both needing route data: how often lifecycle breaks
   actually occur, and whether a **seamless** ID reuse (no lifecycle break at all) is possible
   — if it is, nothing resets anywhere.
7. **Partly done 2026-09-16 — the event is now characterised and a mitigation is replayed;
   the constant it argues for is still not justified.** See *The far-lead limit was inert on the
   fault it exists for* above: the amended `FarLeadBrakeLimit` reduces the commanded peak from
   −2.901 to −1.950 m/s² on this event and alters nothing across the other 38 segments replayed.
   That bounds the *output*; it does not fix the *sensor* error, and it does not supply the
   distribution below. Original wording:
   **Still open: characterise the t≈11 s range-drift false brake.** (A second candidate was
   examined this session on `0000020a` at 9:53 and **refuted** — that one is vision jitter plus
   braking authority, not range drift. So the original event stands alone, still n=1.) It produced a
   −2.89 m/s² command and a driver override, and it passed the innovation gate, the
   one-sided rate check and the gross-distance gate. Needed before any fix: the distribution
   of radar-versus-vision range disagreement across routes where the radar is right, so a
   tightened `HONDA_BOSCH_A_GROSS_DISTANCE_M` can be justified rather than guessed (D-042).
   More real-target routes are the blocker.
8. **Done 2026-09-15 (evening)** — the harness ran; see the reproduction section and D-051 for
   what matched and what did not. Original wording:
   **Run `tools/bosch_a_corpus_report.py` against `00000231--5782493b00` and compare it with
   the figures recorded above.** The harness was written 2026-09-15 and covers every quantity
   the 6- and 16-segment sections quote, but it has never seen a route, so the recorded numbers
   are still unreproduced. This is D-048's validation-gate item 2 and D-049's item 3; both
   designs stay blocked until it runs. Three outcomes, and the third is the valuable one:
   it reproduces them (the corpus becomes evidence again), it disagrees (**neither side wins
   automatically** — the recorded numbers came from code that no longer exists, and the harness
   has never been validated, so the disagreement is the finding), or it will not run on real
   data at all, which is itself worth knowing before anyone depends on it.

9. **Open: the far-lead limit's ramp anchor is inverted at the call site.** `[CONFIRMED]` The unit
   tests anchor the ramp at `ACCEL_MIN` (−3.5); the call site passes `output_accel_min` (−0.5 on
   most fault frames), so partial confidence produces a *tighter* floor than full confidence. It is
   pinned by `TestKnownRampAnchorDefect`, not endorsed. Fixing it in isolation makes the feature
   worse on the only fault we have (−2.818 vs −1.950), because it is compensating for a ramp that
   collapses on the same corrupted `vRel` that causes the fault. What is needed before changing it:
   a second fault example, so the ramp's behaviour can be judged on more than n=1. Re-run the
   39-segment OFF-vs-ON diff on any change here.

10. **Open: more routes, in three specific shapes.** The 40 m distance floor separating the fault
    (61–64 m) from a correct stop-and-go brake (27 m) has **376 frames sitting in the 30–40 m band
    on `0000022f--8acb9d34ac`** that pass every other gate, so the margin is not wide. Wanted:
    highway cut-ins/merges settling at 40–70 m; downhill or trailing-throttle following at 45–60 m;
    and a second long-range radar range-walk fault. The third is the one that takes the positive
    evidence past n=1.

11. **Open: `opendbc_repo/opendbc/car/panda_runner.py:17` calls `get_car()` with the old
    signature** and will raise `TypeError: get_car() missing 1 required positional argument:
    'params'`. This is the same break fixed in `process_replay.py` on 2026-09-16, but it is in a
    vendored subtree and a standalone runner, so it was left alone rather than fixed in passing.

12. **CLOSED 2026-09-16 by `b2baba87`:** the larch64 `common/params_pyx.so` and `libcommon.a` were
    rebuilt with item 4's pinned recipe, 822 → 823 keys, `RangeDerivedVrel` the only addition. The
    Galaxy layout test's strict xfail on this is removed, so it now guards the regression. Device
    check: `PYTHONPATH=/data python3 -c "from openpilot.common.params import Params; k=Params(memory=True).all_keys(); print(len(k), b'RangeDerivedVrel' in k)"`
    must print `823 True`. The original entry is kept below for the record.
    **Was: `RangeDerivedVrel` is unreachable on the car until `common/params_pyx.so` is rebuilt
    for larch64. THIS IS NOW CONFIRMED ON A REAL DEVICE, not just inferred — 2026-09-16.**
    `[CONFIRMED — observed on the car]` Toggling the row in Galaxy returns
    **403 `Parameter 'RangeDerivedVrel' is not editable.`** The key is in `common/params_keys.h`,
    but the checked-in `.so` is aarch64 and carries the **old 822-key list**. Two separate paths
    fail on it: Galaxy's `PUT /api/params` rejects the write up front, because `allowed_keys`
    comes from `_build_default_params()` → `_params_raw.all_keys()` → the `.so`; and
    `get_bool("RangeDerivedVrel")` raises `UnknownKeyName` in `_range_vrel_assist_enabled()`,
    which swallows it. The feature stays off no matter what the UI shows. **Do not patch the
    Galaxy allowlist to get past the 403** — see the section above for why that makes it worse.
    **This container cannot do the rebuild** (no docker daemon, no qemu, no aarch64
    cross-compiler, Python 3.11.15 / Cython 3.3.0 vs the pinned 3.12.3 / 3.1.4). This is open item 4 repeating itself with a
    different key. A **native on-device build** makes the toggle usable in the field (see the
    section above for the two traps: `scons common/` dies on missing eigen headers, so build
    `common/params_pyx.so` as a single target; and never remove the `prebuilt` marker), but it
    does **not** close this item — that binary is not the reproducible pinned-toolchain artifact
    and must not be staged. Use item 4's recipe **verbatim** — the `oprad-build:cy314` image, Cython pinned
    to 3.1.4, mounted at `/work`, `SP_FORCE_TICI=1` — and heed its warning that **scons will report
    success without rebuilding**: delete `.sconsign.dblite` and the archive
    (`./tools/clean_build_artifacts.sh --sconsign`) and confirm the hash actually changed. Expected
    key count **822 → 823**, with `RangeDerivedVrel` the sole difference and nothing dropped, proved
    by diffing `all_keys()` between the old and new `.so` — **not** with `strings`. Ship it as a
    deliberate, separate commit containing only the binaries (AGENTS.md §10, pattern `b9612b2a`).
    Until then, `test_param_default_is_off` passes here only because this container's **x86_64**
    `.so` was rebuilt in-session; that proves nothing about the device.

13. **Open: the OFF-vs-ON replay diff for `RangeDerivedVrel` has never been run.** This is the
    single most valuable next step and it needs no new route data — the 39-segment corpus and the
    harness that produced the `FarLeadBrakeLimit` diff (39 segments, one changed) already exist.
    Run it with the param OFF and then ON and diff `aTarget` frame by frame. **The expected result
    is zero altered frames on all 39**, because nothing in the corpus should hold a 2.0 m/s
    U11-versus-range disagreement on a lead track for 5 consecutive measured updates. Both outcomes
    are informative and the second is the important one:
    * Zero altered frames → the arming gate is doing what it was designed to do on ordinary
      driving, and the feature is inert until the conditions it targets actually occur.
    * **Any** altered frames → do **not** treat that as the feature working. Read those frames
      directly: it means the corpus contains a sustained disagreement that nobody has
      characterised, and until it is known whether U11 or the range channel was right there, an
      altered frame is as likely to be the hazard subsection above as a fix.

14. **Open: two of the `RANGE_VREL_ASSIST_*` constants rest on almost nothing.** Both are bounds
    chosen to limit damage, not values fitted to data, and the comment blocks say so — read them
    before changing a number (CLAUDE.md §5).
    * `RANGE_VREL_ASSIST_MAX_CORRECTION_MPS = 8.0` is sized from **n = 2** recorded events
      (the `000001f9` rail, ~5.9 m/s, and the `000001f3` onset, ~4.6 m/s). A third event is what
      would turn it into a justified number.
    * `RANGE_VREL_ASSIST_MIN_DISAGREEMENT_MPS = 2.0` currently clears the one recorded false brake
      by **1.62 m/s** (worst disagreement there is +0.38). That margin is the whole safety
      argument and it is measured against a **single** fault. Lowering it without a second
      range-walk fault to test against is how this feature becomes an amplifier — the same
      blocker as open items 7 and 10.

15. **CLOSED 2026-09-16 by the D-053 rework:** the lead KF now stays on native U11, so `aLeadK` is
    never corrected and cannot be left frozen at a corrected value across a coast. Kept for the record:
    **Was: the correction is inconsistent across a Bosch-A coast, in a bounded way.** `[CONFIRMED
    — static]` On a coast the assist clears (D-052: a coast refreshes `last_seen_nanos`, so it is
    **not** bounded by `BOSCH_A_STALE_S`, and 121.8 s of continuous suppression has been measured —
    holding a correction across one would be unbounded staleness). But the lead KF is not stepped
    on a coast either, so published `vRel`/`vLead` revert to native U11 immediately while `aLeadK`
    stays frozen at its last corrected value until the next measured update. Both sides are
    bounded and both sit on the conservative side, but for the length of the coast the two
    disagree. It is documented in D-053 rather than papered over. Whether it matters at all is a
    replay question, and open item 13 is the run that would show it.

16. **Open: road-test the reworked `RangeDerivedVrel`.** Needs the device on this commit, the
    `823 True` check from item 12, and the toggle stored (confirm it in `initData`, not the UI). The
    replay evidence rests on two one-update margins (the 232 walk and the 236 settle, D-053
    revision): a road event that arms in 4 updates would pass. Onset lead over U11 is only ~0.1 s.
    Item 14's `MIN_DISAGREEMENT` argument now also has the two recorded phantoms behind it.

17. **D-054 lockout fix: implemented 2026-09-17, replay and static only.** The gate now rejects a
    range only if it contradicts both the last accepted sample and the last gated range (the
    `range_anchor` that coasts advance). Evidence is in D-054.
    - **Open, road:** needs the device on this commit. Watch for a lead that pulls away or closes
      while the rate check coasts: it should stay published, with measured=False.
    - **Residuals, investigated 2026-09-17 (replay and static only):** the `ratio_vrel` timing has no
      effect in replay. Lasting steps and stale rate history are real causes. The proposals are in
      D-055 / D-056 / D-057, on branch `proposal/d054-residuals`, which is not for the car.

18. **CHARACTERISED 2026-09-17 (see item 27): `00000239` 10:33.7 phantom hard brake is a same-identity range walk at 10:30.3, not an association fault.** Original note: Looks like a lead association fault (lead
    track yRel −0.9 → −3.7 m while range fell 74 → 61.5 m, U11 +1.5 → −7.5, vision held 69–75 m).
    Neither the rework nor D-054 touches it. Needs a raw-track look at 625–635 s.

19. **ON THE CAR BRANCH 2026-09-17 (replay and static only): D-055 invalid-slot hide guard.**
    See item 26 for the fresh-route evidence that promoted it.
    - Replay vs D-054: 0 lost point-sweeps, 2,252 restored as coasts (504 lead), including
      237 track 9 (21.2 s).
    - Static: 4 tests.
    - Candidate for the car once fresh routes on 0756f810 confirm D-054 on the road.

20. **Rejected in replay: D-056 rate check fit over gated ranges.** Its re-admitted vRel over-closes
    by >3 m/s about 4× as often as reference, and it loses 14 lead point-sweeps on 0000023a. See D-056.

21. **D-057 re-anchor on a lasting clean step — ON THE CAR BRANCH 2026-09-17 (replay and static
    only; see item 28).** Earlier prototype record: on top of D-056 the replay is clean:
    0 lost, and newly measured vRel is at or better than reference. It restores 236 track 38
    (17.1 s) and 237 track 31 (16.2 s). It is stacked on D-056, so it is not shippable as-is.

22. **Next-session tasks (radar residuals).**
    1. **Done 2026-09-17 (item 26).** Lock census run on 0000023b / 0000023e (both on 0756f810).
    2. **Done 2026-09-17 (item 28).** D-057 re-based onto D-055 alone, 4 tests rerun, `ab5.py`
       replay D-055 vs D-055+D-057 on all seven routes with the future-slope metric.
    3. **D-055 part done 2026-09-17 (item 26):** lost = 0 on both fresh routes, no new measured
       vRel; committed to the car branch on its own. D-057 still needs the re-base and replay.
    4. **Done 2026-09-17 (item 28):** 237 track 63 is absent 51.4 s under D-055 and published
       measured under D-057 (23.4→20.5 m, vRel −1.1→0, non-lead).
    5. Decide whether a join should be allowed to publish measured when the joined range contradicts
       U11 (see the D-054 census). That needs its own test, like the D-057 contradiction control
       with an 8.5 m step.
    6. 236 track 21 (20.4 s, fully degraded lead lockout) is not addressed by any proposal.
    7. Item 18 (239 phantom brake) is still open.
    Tooling: `/routes/an2` and `/routes/an2/parsers` in the `oprad-routes` volume.

23. **Hard brakes on 0000023b / 0000023e are not RangeDerivedVrel; an aLeadK limiter was tried and
    NOT proposed (replay only, 2026-09-17).**
    - Toggle read from initData: 23b RangeDerivedVrel=0, 23e =1 (all 42 rlog segments), both on
      0756f810. On 23e the assist was active (correction > 1 m/s) for 21 s of 42 min. At 0 of 11 engaged
      hard-brake onsets (aTarget < -2.5) was it active. The hard-brake rate was 22/h, against 23/h and
      19/h on toggle-off 237 and 239.
    - Mechanism. A short closing transient drives the lead KF's aLeadK to -3..-7 with aLeadTau ~0 in
      about 0.5 s. Past aLeadK < -`MODEL_LEAD_TRAJECTORY_MAX_LEAD_BRAKE`, `build_model_lead_trajectory`
      falls back to `extrapolate_lead`. Above 35 mph that holds aLeadK **constant for the whole
      horizon**, so a -3 dip reads as "lead stops in ~4 s". Over-reactions: 23e 4:55 (future 1 s
      range slope +1.3, driver took over) and 30:20 (U11 -9.1, future -2.8). The real closings at
      9:41, 11:10, 12:51, 16:09, 25:02 and 39:04 look the same at onset.
    - Tried, and why each fails (`alk.py`, `alk3.py`, `alk4.py` in `/routes/an2`):
      1. *Clamp when the short range fit says U11 over-closes*: 0 of 22 onsets touched on 23e, 237 and
         239. At the onset the range fit is MORE closing than U11 (4:55: range -4.4, U11 -2.8). The
         transient is real for about 0.3 s; it just does not last.
      2. *Clamp when vision disagrees* (mlV − vLeadK > 2, mlA > -0.6, TTC > 4): catches 4:55 and
         30:20, and is right on median (the future slope is 2.4–3.9 m/s less closing than U11). But
         it clamps 239 10:30.5 (U11 -3.4, **future -12.7** at 68 m; vision said 25 m/s, mlA 0).
         Rejected: vision is not closing-speed truth.
      3. *Decay young decelerations* (exp decay with tau ≥ 0.6 at all speeds while aLeadK < -0.5
         for < 1 s). Scored against the true lead position 2–3 s later over 1130 engaged
         aLeadK < -2 rows on 7 routes. Current projection error at 3 s for young decels: p50
         -12.6 m (predicts the lead too close). Limited: p50 -10.0 m. Under-predictions > 3 m go
         31 → 44, and the new ones under 50 m are the **real** brakes 23e 11:10 (25 m, up to +5.8 m)
         and 12:51, plus 239 7:41. With tau ≥ 1.5 it is worse (31 → 55). It softens the brakes that
         were right.
    - What the data does say: projection error is biased toward over-braking even for old
      decelerations (all rows p50 -3.0 m at 2 s, -6.4 m at 3 s). aLeadK stays negative after the lead
      stops decelerating, which is KF lag on the release side and not only onset gain.
    - Next candidate, not built: **release-side only**. When aLeadK < -1 but the range slope over the
      last ~0.5 s shows closing has stopped growing, pull aLeadK toward 0 faster. Never soften onset.
      Score it with `alk4.py` (a projection-vs-truth metric, zero new close-range under-predictions
      as the gate) before any code. It needs a radard/long_mpc change, so it gets a DECISIONS entry
      and user OK first.

24. **BLoTv3 supervisor (experimental): two BLoTv3 behavior fixes ported and the supervisor renamed
    from BLoTv2, 2026-09-17, unit evidence (D-058).**
    Upstream `SpysyWeeb/Spysypilot` restructured BLoTv2 into BLoTv3 (`combo-blotv3`, `7aed876`,
    `docs/BLoTv3.md`). Two of those changes are supervisor behavior and are now in
    `selfdrive/controls/lib/blotv3.py`: the `t_follow` pads saturate at their ceilings instead of
    vanishing above `ONSET_MAX_A_REQ` (**reverted 2026-09-28**: it made hard brakes harder,
    route 00000294 6:25 sim -4.23 -> -3.90; closed-loop replay only, see D-058), and the crawl hold latches on "was necessity-braking"
    instead of on the exact `JERK_SCALE_MIN` floor (released by the emergency bypass and by lead
    loss). The module, class, tests and toggle are renamed (`BlotV2` → `BlotV3`, toggle starts off).
    The BLoTv3 module split (`force_stops.py`, `stop_helpers.py`,
    `conditional_experimental_mode.py`, the model-lead anchor) is **not** ported — see D-058.
    - **Replay A/B done 2026-09-17 (rlog replay of the supervisor only, not the MPC; agy-pro
      dispatch, Claude-audited).** BLoTv2 (b38e933e) and BLoTv3 (current) were stepped side by side
      on every `modelV2` frame of 00000232 / 236 / 237 / 239 / 23a / 23b / 23e from the logged
      radar lead, `vEgo`, `aTarget` and `tFollow` (script `blotab.py` in the `oprad-routes` volume,
      `/routes/an2`). Over 115,536 engaged lead frames: `jerk_scale` differed on **0** frames and the
      crawl hold differed in **0** runs, so on these drives the two versions differ only through
      the `t_follow` pad. V3 pad exceeded V2 by > 0.2 s in 68 runs totalling 90.4 s (2.1 % of engaged
      lead frames; longest run 2.9 s, pad saturating at 0.45–0.75 s, closest lead 7.7 m on 23e),
      every one a hard-braking approach where V2 had collapsed its pad to zero.
      **It does not help the radar fault classes and slightly works against them:** during the 239
      10:30 phantom (item 27) V3 raised the pad to 0.45 s for 1.1 s (630.46–631.56 s) while V2 held
      0, i.e. V3 asks for a wider gap from a lead that is not braking; both versions softened
      `jerk_scale` identically (0.70 at 631.6 s). BLoTv3 reads `aLeadK` from the radar lead, the
      signal item 23 shows over-reacting on a range walk, so a phantom reaches it unfiltered.
      Braking *force* is unchanged by V3 on these routes (no jerk-scale difference); braking
      *onset* on a real decelerating lead moves earlier by up to the pad. Verdict: a conservative
      comfort change relative to V2, reasonable to enable for road evaluation, not a radar fix.
      Every route so far was driven with `BlotV2` ON; the renamed `BlotV3` key starts OFF, so it
      must be switched on explicitly for the next drive. Not road-validated.

25. **Release-side aLeadK rule and FarLeadBrakeLimit review. Neither shipped (replay and limited
    road evidence, 2026-09-17).**
    - *Release-side aLeadK* (`alk5.py`). For a deceleration at least 1 s old, fit
      d = d0 + v·t + ½a·t² over the last 1.0–1.5 s of range. If the fit says the lead is decelerating
      less, raise the published aLeadK (optionally capped at half, optionally only when the short range
      fit shows closing is not growing). Scored like item 23 (1130+ rows, 7 routes). Every setting
      improves the bias (changed rows at 2 s: p50 -2.6 → -1.7 m), but none meets the gate "zero new
      close-range under-predictions". The strictest setting still adds 4 cases at 2 s (> 3 m, d < 50 m)
      and 10 at 3 s (> 5 m). They sit on steady -1 to -1.5 m/s² braking where the 1.5 s quadratic fit is
      too noisy (237 6:20 at 34 m, 237 20:02 at 25 m, 23a 5:35). Not implemented.
    - *FarLeadBrakeLimit* was ON on every route 232–23e (initData). `farev.py`: 12 fire clusters. Truth
      is the 1 s future range slope.
      - Not engaged, so no effect on the car: 23a 16:36 and 23e 17:18 / 34:12. In the last two the driver
        was already braking. 23e 34:12 would have cut -5.9 → -0.7 m/s² on a lead truly closing at
        20.5 m/s.
      - Engaged, and helped (lead not really closing, relief > 2 m/s²): 237 15:37 and 15:42.
      - Engaged, negligible relief (< 0.35): 232 19:08, 237 14:24, 14:30 and 19:53, 23e 1:40.
      - Engaged, real closing, relief given: 236 14:18 (closing 5.3 m/s at 60 m, -3.2 → -2.0, no
        intervention), and **237 5:22** (slow car, mlV ~7 at 104 m, truly closing 13.5 m/s, capped
        -3.8 → -1.9; driver braked 4 s later at ~47 m).
      - Verdict: two helpful, two cut real braking, and the capping logic trusts the same vRel it is meant
        to distrust. **Not merged; the toggle stays.** Recommend OFF until the 5:22 / 34:12 shape is
        excluded.

26. **D-055 promoted to the car branch — 2026-09-17 (replay and static only; awaiting road
    evidence).** Item 22.1 and the D-055 half of 22.3, done on the two fresh routes driven on
    D-054 (`gitCommit 0756f810` in `initData`, both routes):
    - **Lock census (`lockcensus.py` / `locksumm.py`, the parser the car ran):** 0000023b (5 seg)
      76 locked sweeps of 5,828 (1.3 %, 5 s), 10 episodes, 0 ≥1 s in path, 0 ≥1 s while the
      device lead was vision-matched to the locked object. 0000023e (42 seg) 2,933 of 77,560
      (3.8 %, 204 s), 231 episodes, 62 ≥1 s, 1 ≥1 s in path, **0 lead-matched**. The longest
      is id5 at 37:22.4 for 6.9 s. Compare 232/236/237 before D-054: 2, 3 and 4 lead-matched
      episodes (5, 26, 42 s). Limited road evidence, not a road test of the fix in isolation.
    - **D-055 vs main (`ab3.py`, pair MG):** 23b lost 0 / lost_lead 0, gained 9 (0 lead), 0 runs
      ≥1 s. 23e lost 0 / lost_lead 0, gained 331 (33 lead), 4 runs ≥1 s, none lead. Every
      restored sweep is a coast (`gained_measured` 0), so no new measured vRel enters control and
      `new_measured_vrel_vs_future_slope` is n = 0. That is the item 22.3 gate, met.
    - **Static:** `test_bosch_a_radar.py` 104 passed, `test_far_lead_brake_limit.py` 22 passed
      (arm64 container). The change is the one-line hide-set exclusion from `4ab261ac` plus its
      4 tests; the comment now records the fresh-route numbers.
    - **What this is not:** D-055 has never run on the car. It only ever re-publishes coasts the
      old parser hid, so its failure mode is a stale coasted point living up to the coast limit,
      not a missing one (D-041/D-042). Watch the next route's `ab3`-style diff for lead runs.
    - Still open from item 22: re-base D-057 onto D-055 (22.2), 237 track 63 (22.4), the
      join-vs-U11 decision (22.5), 236 track 21 (22.6), item 18.

27. **Item 18 characterised — the 239 phantom brake is a same-identity radar range walk, and the
    far-lead limit was live but gated out (replay of recorded data, 2026-09-17).** Raw-slot
    replay (`rawslots.py`, `tracks.py`, `tl2.py`, seg 10, 622–640 s; first pass by an agy-pro
    worker, audited against the raw output, deliverables in the job scratch dir, worktree
    aborted for a `scratch/` path breach):
    - Track 21 is the in-lane lead at 10:22 (59 m, y 0.1, vision 66 m). Through a bend (vision
      y +1.4 → +5.2, radar y −1.9 → −3.8, opposite sign conventions) its range walks
      **72.6 → 61.9 m in 1.0 s (−10.7 m/s)** while wire U11 ramps 0 → **−7.7**, `u10` climbs
      93 → 329, then the range **parks at 61.5 m** for 2 s while U11 decays to 0 and later turns
      +2 as the range grows back to 67 m. Vision holds 73–81 m at vRel ≈ 0 throughout. No other
      valid slot within |y| < 4 m, 50–90 m; the identity never changed and slot migrations
      (s0 ↔ s1) were tracked. The worker's verdict "(b) genuine wire step, same identity" is
      correct as far as it goes; the shape is the 000001f9 range-walk class, which makes this
      the **second recorded range-walk fault** item 10 asked for (n = 2, not yet 3).
    - Command: aTarget −3.5 from 10:30.7 to 10:31.4 (0.8 s), then the lead flip-flopped between
      radar (62 m) and vision-only (76–80 m) sweep to sweep until 10:32.2. The driver's bookmark
      is 3 s after onset.
    - **FarLeadBrakeLimit was ON (`initData` seg 10) and the 2026-09-16 fix `9984de88` is in the
      route's commit `fa262e0c`, yet it fired nowhere on 239.** Both gates excluded it: headway
      68.5 / 24.5 = 2.8 s < `MIN_HEADWAY` 3.0, and TTC 63.5 / 6.6 = 9.6 s < `MIN_TTC` 10. This
      event sits just under both constants of D-042. Not re-tuned: item 25 already shows the
      limit cutting real braking inside its current envelope (236 14:18 at TTC ≈ 11), so
      widening it is a safety-tuning decision that needs the third event, not a replay of one.
    - RangeDerivedVrel would not help here: the range slope (−10.7) closes *faster* than U11
      (−7.7), so the assist direction is the wrong one. What separates this from a real closer is
      vision (13–18 m further, vRel ≈ 0) and the park-and-decay after the walk — the same
      discriminator item 25 lacked for 237 5:22. Proposal work should start from that pair.

28. **D-057 promoted to the car branch (replay and static only, 2026-09-17).** Re-based onto D-055
    without D-056 (`rejected_run` on the track state, `_bosch_a_lasting_clean_step`, constants
    `BOSCH_A_REANCHOR_*`). Static: 108 passed (4 D-057 tests: positive publishes at 1.5–1.65 s, the
    degraded and U11-contradicting controls never re-anchor). Replay D-055 vs D-055+D-057 (`ab5.py`,
    agy-flash dispatch for the mechanical run, Claude-audited): lost 0 on every route; restores 236
    track 38 (17.1 s, lead), 237 track 31 (16.2 s, lead), 237 track 63 (51.4 s, non-lead, item 22.4);
    23b/23e unchanged apart from 13 sweeps. Newly measured vRel over-closes the next-1 s range slope
    by >3 m/s on 2.2 / 2.2 / 0 % (236 / 237 / 23a) vs reference 5.4 / 5.9 / 2.6 %. **Unlike D-055,
    this admits new measured points into control** on a re-anchored identity. Not road-validated:
    the next drive is the first road evidence; check lead lockouts (lock census) and any brake event
    on a re-anchored identity. Still open from item 22: 22.6 (236 track 21); 22.5 closed by item 29.

29. **D-059: a join holds measured vRel until a post-join rate fit agrees (replay and static only,
    2026-09-17).** Closes item 22.5. After the range gate passes again following a rejection run, the
    point publishes unmeasured on its last trusted vRel until a D-043-style fit over post-join ranges
    only agrees with U11; `samples` is untouched. Census: 210 joins (9 lead); post-join measured vRel
    over-closed >3 m/s on 21.0 % vs reference 4.6 %. Static: 110 passed (negative control, 8.5 m step
    with U11 −4, fails on a8370b3b). Replay vs car branch (`ab7.py`): lost 0, new measured 0, 612
    unmeasured flips (30 lead); withdrawn vRel over-closed 29.2 % but also under-closed 18 % (ref
    8.6 %). J1 (clear `samples`) rejected: 16 % over-close on 106 new measured sweeps, 65 lost. Next
    drive: lead lock census, brake events near joins, lead rejoin-hold duration.

30. **Route `0000023f--66ddbb900a` analysed (2026-09-17): first road evidence for
    `FarLeadBrakeLimit`, and the radar/vision gap discriminator is refuted on 8 routes.** 32
    segments, 31:41, 21.3 min engaged, fetched with `konik_fetch.py` and cached in `oprad-routes`.
    The device ran commit `7106fdf4` with `FarLeadBrakeLimit = 1`, `BoschARadar = 1`,
    `RangeDerivedVrel = 1`, `BlotV3 = 0` (from initData — the toggles were actually stored).

    * **`FarLeadBrakeLimit` fired on the road for the first time: 43 caps in 5 clusters**
      (`an2/farev.py`). One cluster is the phantom the feature exists for (12:25, d 46 m, U11
      −2.31 m/s while the next-1 s range slope is **+0.75**, relief 1.11 m/s²). **The other four
      capped leads that were genuinely closing** (future slope −4.0 to −10.0 m/s): 18:10 (relief
      0.05), 20:41 (relief **2.82** at d 83 m, min gap 78.5 m, min TTC 10.7 s), 23:15 (relief 1.28
      at d 57 m, closing −9.97 m/s, min gap 39.1 m, min TTC 4.6 s), 25:51 (relief 0.38). No driver
      brake followed any cluster, min gap over the route stayed 10.4 m and min TTC 2.7 s, and route
      `aEgo` min is −5.90 m/s² with 4 brake presses while enabled, none within 6 s of a cap. So on
      one drive the cap was 1-for-5 on phantoms and never left the car short — but it is bounding
      real closing leads, and 23:15 is the shape to watch. Still default OFF, still a TEST label,
      ramp-anchor defect still pinned, D-048 validation gate still unmet.
    * **D-048 gate item 2 / D-049 item 3, the measurement that was blocking them, is done for the
      absolute-gap candidate** (`an2/visgap.py`, 8 routes, 121 min, 140k radar-lead frames with a
      confident model lead). At d >= 60 m the radar/vision range gap is >= 10 m on 31.5 % and
      >= 15 m on 13.1 % of frames, and those frames are *not* followed by harder braking than
      baseline (lower on 6 of 7 routes). The 15.8 m gap in the 231 fault is therefore ordinary. A
      range-*slope* disagreement variant is refuted too: p90 of normal driving at 60–80 m is
      5.1–9.5 m/s and the fault's worst frame is 7.9 m/s. Written into D-048's rejected list. This
      does **not** clear the gates: it answers the distribution question in the negative, and the
      unreproduced statistics still need the harness re-run.
    * **D-059 out-of-sample on this unseen route** (`an2/ab7.py`): lost 0, lost_lead 0, new measured
      0, 108 unmeasured flips (16 lead); withdrawn measured vRel over-closed the next-1 s slope on
      19/67 (28 %) vs reference 33/702 (4.7 %), and under-closed on 21/67 vs 83/702 — the same
      shape, including the same caveat, as the 7 routes it was built on.
    * **Join census now 8 routes** (`an2/joinsum.py`): 249 joins, 13 on the lead, post-join measured
      vRel over-closes on 20.4 % (1,084 scored) vs reference 4.6 % (5,442). 39 joins and 2 D-057
      re-anchors on 23f alone.
    * Route 231 segments 9–11 are cached now too, so the fault episode can be re-derived against the
      current tree (the other agent's point 4: the 0.25 m/sweep vs 2.0 m gate arithmetic predates
      D-054 and has **not** been re-run yet).

31. **Route `00000241--7948e97423` (2026-09-17): the user reports phantom brakes and one stopped-lead
    miss they had to intervene on. Both are road evidence, and the lateral estimate is implicated in
    both directions.** 12 segments, 11:41, 5.1 min engaged, 4.5 km. Same device build as 23f
    (`FarLeadBrakeLimit = 1`, `BoschARadar = 1`, `RangeDerivedVrel = 1`, `BlotV3 = 0`). 5 brake
    presses and 12 `longActive` drops while enabled; route `aEgo` min −4.85.

    **The stopped-lead misses — three separate shapes, and our parser caused none of them.**
    * **9:36–9:40, the radar itself went blank.** `an2/rawslots.py` on segment 9: at 9:36.1 the
      sweep contains **no valid objects at all** (16 invalid slots) and the near lead (track 20,
      d 25.6 m, existence 68) is simply gone; it does not come back for ~3.7 s. The model lead's
      probability decays 0.93 → 0.62 → 0.38 → 0.06 with `xStd` 8 m, so `radarState` has no lead
      either. The car, just out of a near-stop, was commanding **+1.67 m/s²** into a lead that had
      stopped ~20 m ahead when the driver braked at 9:37.7. Nothing in the Bosch-A gate is involved:
      the radar published nothing to gate.
    * **6:50–6:52, lead selection walked away from a good in-lane point.** The raw sweeps keep
      track 8 at d ≈ 21 m, y ≈ 0.2, existence **126**, published every sweep. `leadOne` nonetheless
      drops it at 6:50.5 (`rad=0 tid=-1 d=27.2`), follows the model lead out to 32 m, then binds to
      track 33 at **43 m, y 4.2**. The genuinely stopping car (track 33) had been visible since 6:49
      at d 48 m with U11 −6.6 m/s, but its `y` read 5–6 m — out of lane — until 1.5 s before the
      intervention. Driver braked at 6:52.1.
    * **3:37–3:47, enough braking, then released.** Lead track 38, probability 1.00, both sensors
      agreeing, a slow roller (`vLead` 1.6–3.4 m/s) approached from 105 m. `FarLeadBrakeLimit` fired
      6 times at 3:37 (planner −2.61 → commanded −1.34), the car then braked to −3.32 at 3:39 and
      **released to −0.80 … −1.24 m/s² for the next 7 s** while still closing 5–8 m/s inside 60 m
      (`aLeadK` had gone positive). Driver braked at 3:47 with 13.9 m left.

    **The phantom brakes are the same coin.** `an2/phantom.py` lists all 8 engaged episodes at
    `aTarget <= -1.5`: **4:55.9** (−2.32, lead **y −8.1 m**), **4:59.4** (−3.24, aEgo −4.15, y −5.3),
    **9:09.5** (−3.20, aEgo −4.25, y +3.7, closing only 2.0 m/s with a −1.27 m/s future slope) and
    **1:51.9** (−2.86, aEgo −3.51, **no radar lead published at all** — cause not yet identified).
    So the car brakes hard for targets 4–8 m off centre while ignoring an in-path stopped car whose
    `y` reads 5 m. The Bosch-A lateral estimate is being trusted symmetrically in both directions,
    and `leadOne` accepted a lead at y −8.1 m.

    **Answered in item 38 (2026-09-21):** the census ran on all 13 routes and found 5 near in-lane
    dropouts on 4 routes — but four of the five lose the target at the lateral edge of the in-lane
    box, so the evidence points at the target leaving the beam rather than at a failing sensor. The
    "16 invalid slots for 3.7 s" premise is also corrected there: the blank condition lasted 0.14 s.
    Original note: whether a stationary-target dropout like 9:36 is visible in the other 9 routes.
    The 1:51.9 no-lead brake and the y −8.1 m lead acceptance are both answered in item 32. `FarLeadBrakeLimit`'s
    road record is now 2 routes: 1 phantom cap and **6 caps on genuinely closing leads**, two of them
    (23f 23:15, 241 3:37) followed by a driver brake. That argues for tightening its gate before it
    ever leaves TEST, not for widening it.

## 32. Route 241 follow-up: the 1:51.9 brake is not a radar event, and there is no absolute lateral bound on a Bosch-A lead — 2026-09-17

Two of the three items left open by item 31 are now answered. Replay and log analysis only; nothing
changed in the tree.

**1:51.9 was the end-to-end longitudinal plan, with no lead of any kind.** Route `00000241--7948e97423`,
seg 1. The raw sweeps carry no object anywhere near the path (`rawslots.py … 1 106 118 1.0`: the only
valid slots are track 23 at d 6–20 m, y −2.5 to −3.2, and from 1:52.0 to 1:55.0 *no valid objects at
all*), the model lead probability is **0.00–0.03** for the whole episode, and `hasLead = 0`,
`shouldStop = 0`, `src = cruise` in `scan_00000241--7948e97423.csv` throughout. `expMode = 1`
(Experimental Mode) the entire time, so longitudinal came from the model's own plan.

What moved was the plan, not a target. Between 1:49.8 and 1:52.6 the last point of `modelV2.position.x`
collapsed from **210 m to 99 m**, then to 69 m at 1:54 and 41 m at 1:57, while `steeringAngleDeg` held
−1.1° and yaw rate 0.007 rad/s — i.e. a straight, clear road. `spVCruise` stepped from 22.36 m/s to
14.06 at 1:50.4 and decayed to 5.09 m/s by 1:59.6, where `longActive` went 1 → 0 as the driver pressed
the gas. So the model planned a stop on an empty straight, the planner followed it down from 22.1 to
5.6 m/s, and the driver overrode.

> **Time-base note.** `scan_<route>.csv`'s `t` is raw `logMonoTime`; route time is
> `(t - min(seg_t0))/1e9` from the JSON, which is what `load.py`, `tl2.py`, `rawslots.py`, `phantom.py`
> and `curv.py` all use. An earlier revision of this item quoted the `spVCruise` times from a hand
> dump that normalised against the CSV's own first row instead, which on this route runs **5.13 s
> late**. The figures above are corrected; the plan-collapse, no-lead and no-object findings came from
> the correctly-based tools and are unaffected.

**This one is outside the Bosch-A path entirely.** No change to `radar_interface.py` could have caused
or prevented it, and it should not be counted against the radar work. It is the clearest phantom the
driver felt on this route, and its cause is the e2e longitudinal plan in Experimental Mode.

**Why `radard` accepted a lead at y −8.1 m: there is no absolute lateral bound on this car.**
`selfdrive/controls/radard.py`:

* The only absolute |`yRel`| gate in the lead path is `g90_radar_lead_lateral_sane` (line 588),
  `abs(yRel) <= min(6.0, 1.5 + 0.08 * dRel)`. At d 45 m that is 5.1 m, which **would** have rejected
  the 4:55.9 track. But it is applied only when `g90_radar_filter` is set, and line 1066 sets that to
  `CP.brand == "hyundai" and CP.carFingerprint == "GENESIS_G90"`. On this Honda it is off.
* The only lateral test that does run is `lat_sane` inside `track_matches_vision` (line 621):
  `abs(track.yRel + lead.y[0]) < max(y_floor, y_std_scale * max(lead.yStd[0], 0.2))`. That is a
  *relative* check — the radar's `y` only has to agree with **vision's** `y`. With `y_std_scale = 1.0,
  y_floor = 1.0` on the strict path and `2.0 / 1.5` on the preferred-track fallback (line 657), and
  vision `yStd` running 1.8–4.8 m at 40–100 m on this route, the tolerance reaches ~10 m. A radar
  track at y −8.1 passes whenever vision's own lead `y` is also off-centre and uncertain, which is
  exactly the case on a bend.

**Do not turn this into a threshold yet.** The same route contains the symmetric failure: at 6:49 the
car that really was stopping read `y` 5–6 m for 3 s (item 31), so an absolute |`yRel`| bound tight
enough to reject the 4:55.9 phantom would also have rejected that real lead and delayed the brake
further. The Bosch-A lateral estimate is too coarse to gate on in *either* direction on one route's
evidence, and D-048's rejected list is already full of thresholds that looked good on one route. The
next step is a measurement, not a constant: a census of published `yRel` against the vision `y` and
against the outcome, over all 10 cached routes, before any bound is proposed.

**Still open from items 31 and 32:** the stationary-target dropout census (does a 9:36-style
all-slots-invalid gap occur on the other 9 routes?), the `yRel` census above, and item 22.6
(236 track 21).

## 33. The 13-route lateral census: adjacent-lane locks are real, rare, and they brake — 2026-09-21

**Tool:** `an2/ycen.py` writes one row per `radarState` frame; `an2/ysum.py` buckets it. The measured
quantity is **`dyPath` = the lead's lateral offset against `modelV2.position` interpolated at the
lead's own range**, not against the car's centreline:

    y1 = -leadOne.yRel            # world frame, left-positive
    dyPath = y1 - pathY(d1)       # blank, never extrapolated, beyond position.x[-1]

`dyPath` is ~0 for an in-lane lead at *any* curvature and ~±3.7 for a genuine next-lane lock. Raw
`|yRel|` cannot separate those on a bend, which is why item 32 declined to bound it.

> **Retraction.** An earlier hand analysis in this session claimed `dyPath` was ~0 for all seven of
> 241's known episodes, and concluded a lateral gate was therefore not the fix. **That was wrong**,
> and wrong for the same reason item 32 was: the hand dump was read at the CSV's own time base, so it
> sampled windows several seconds off the episodes. Re-read at the correct base, 241 at 4:55.9–5:02.7
> shows `dyPath` growing smoothly 0 → **−4.2 m** while vision's own lead stays on path
> (`dyPath_ml` +0.08). The census below replaces that claim.

**Coverage:** 13 routes, 231/232/236/237/239/23a/23b/23e/23f/241/245/246/248. 248 is 8 of 12
segments — **3, 5, 7 and 8 never uploaded**, so its 2170 accepted frames are a partial sample.

**Distribution — lead selection is overwhelmingly in-path, as it should be:** `|dyPath| < 1 m` covers
**88.5–99.0%** of accepted-lead frames on every route. The measure is well behaved.

**Braking rises with off-path offset.** Share of accepted-lead frames whose next 3 s contains an
`aTarget < -1.5 m/s²`, by `|dyPath|` band:

| route | <1 | 1–2.5 | 2.5–5 | >5 |
|---|---|---|---|---|
| 232 | 4.9% | 21.5% | **33.8%** | 25.0% |
| 237 | 7.6% | 26.3% | **29.0%** | 23.5% |
| 245 | 7.9% | 33.7% | **27.7%** | 70.0% |
| 239 | 5.1% | 20.0% | 25.3% | 2.8% |
| 236 | 6.5% | 14.1% | 13.2% | 58.3% |
| 23f | 9.0% | 18.9% | 5.0% | 45.5% |
| 241 | 12.4% | 11.8% | 8.1% | 32.6% |
| 23b | 9.1% | 25.6% | 1.3% | 0.0% |

Nine of thirteen routes show a monotone rise from the `<1` band into `1–2.5`; a 3–5× jump is typical.
241 and 23b do not, so this is an association across the fleet, not a law. **`>5 m` is contaminated**
by junction geometry (ego turning across its own plan, `|curv|` 0.02–0.14, ranges under 20 m) and is
not the interesting band. The band that matters is **2.5–5 m at 30–115 m on a gentle bend.**

**The sharpest case, 245 at 5:52.8–5:58.5** (`ycen_00000245--1356bb0355.csv`), v≈20 m/s, gentle right
bend `curv ≈ -0.0027` (R≈370 m). Radar tracks 26, 32 and 35 are bound as `leadOne` at d = 75–108 m
with `dyPath` **+2.9 to +5.2** — left of the ego's own plan — while vision's lead sits on the plan at
d≈75 m (`dyPath_ml` −0.5…−1.3, `mlProb` 0.35–0.77). `aTarget` reaches the **−3.50 m/s² floor** with
`src = lead0`/`lead1` twice, at 5:53.5 and 5:56.5. 245's `1–2.5` band brakes in 33.7% of frames
against a 7.9% baseline.

Comparable radar-backed, vision-on-path episodes: 237 at 6837–6843 s (d 82–95 m, `dyPath` +2.5…+3.7,
`aTarget` −2.00) and 6888.5 s (d 74 m, −3.50); 236 at 3461–3466 s (d 86–112 m, −1.58); 23e at
23110.5 s and 23376.1 s (both −3.50); 241 at 4:55.9–5:02.7 (d 45–49 m).

**Observation to verify, not yet a finding:** across those 245 frames `leadOne.vRel` reads exactly
**−13.50 m/s** on four different track ids for dozens of consecutive frames. On track 29 the range
slope confirms it (86.3 → 65.5 m in 1.4 s ≈ −14.8 m/s), so it is not simply a clamp — but an
identical constant across distinct tracks needs explaining before anyone reasons from it. Check it
against `rawslots.py` before using `vRel` in any gate.

**What this does and does not license.** It is replay evidence that a lateral disagreement measure
would fire on the frames the driver complains about, and item 32's counter-example is answered:
241's 6:49 real missed stopper reads `dyPath` −0.50…+0.62, so a `dyPath` bound keeps it where a raw
`|yRel|` bound would have dropped it — safe in the D-041 direction. It is **not** a validated gate.
Nothing here has been replayed through `radard` with a candidate threshold, and the 2.5–5 m band
still holds 0.6–3.4% of accepted frames on routes where the association is weak. Before proposing
anything: replay a candidate bound over all 13 routes and count leads *lost*, not leads rejected.

**Still open:** the longitudinal over-reaction from item 32 (−3 m/s² for a 2.0–2.3 m/s closure at
42–45 m) is unexplained and is a separate defect from lead selection; the stationary-target dropout
census; item 22.6 (236 track 21). *(Item 34 resolves the first of those: it is not a defect.)*

## 34. There is no longitudinal over-reaction: the −3.50 floor is correct arithmetic on a railed off-path lead — 2026-09-21

Item 33 left two things open and called them separate: an unexplained `vRel` constant, and an
unexplained longitudinal over-reaction. They are the same thing, and neither is a longitudinal
defect. **The MPC's response is arithmetically correct for the input it was handed. The input is
wrong twice over, and both errors push the same way.**

**The `−13.50 m/s` constant is the Bosch-A saturation rail, already documented in this repo.**
`opendbc_repo/opendbc/car/honda/radar_interface.py:133` states it outright: the U11 domain endpoints
are saturation rails, "at raw 0 or 1728 the true |vRel| is >= 13.5 m/s", and line 145 names the
consequence — "a stopped car reads as vLead = vEgo − 13.5". Four distinct track ids reading exactly
the same value is the rail, not a coincidence and not a clamp bug. Item 33's `vRel` observation is
resolved; nothing new needs measuring. Cross-checking `rawslots.py` is no longer required.

**Why that is expensive: the rail makes any off-path radar return look like a near-stopped car.**
`long_mpc.py` builds the obstacle as `dRel + get_stopped_equivalence_factor(vLead)` =
`dRel + vLead²/(2·2.5)`, and compares it against
`get_safe_obstacle_distance(vEgo, t_follow)` = `vEgo²/5 + 1.45·vEgo + 6`. At the moment the rail
holds, `vLead` reads `vEgo − 13.5` whatever the object is actually doing, so its stopped-equivalence
contribution nearly vanishes. Worked from the 245 CSV rows, with `ACCEL_MIN = −3.5`:

| frame (route time) | tid | vEgo | dRel | vLead published | obstacle | safe distance | deficit |
|---|---|---|---|---|---|---|---|
| 353.6 s | 26 | 20.72 | 89.79 | 7.22 (rail) | 100.2 | 121.9 | **−21.7 m** |
| 356.5 s | 35 | 19.55 | 77.92 | 6.05 (rail) | 85.2 | 110.8 | **−25.5 m** |
| 357.4 s | 29 | 19.35 | 77.92 | 5.85 (rail) | 84.8 | 108.9 | **−24.2 m** |
| 354.4 s | vision lead, same scene | 20.18 | 74.04 | 16.68 | 129.7 | 116.7 | **+13.0 m** |

The last row is the finding. At the same instant, on the same road, the vision lead carries **+13 m
of margin** — the planner wants no brake at all — while the railed radar track 4 m off the predicted
path reads **−25 m** and the solver goes to the floor. −3.50 m/s² is not an over-reaction to that
input; it is the only answer to "a near-stopped car 78 m ahead at 19.5 m/s". A deficit of −20 to −26 m
is not marginal, which is why these events hit `ACCEL_MIN` exactly rather than something in between.

**The reach of the mechanism, from the same two formulas.** A railed radar lead triggers braking
below `safe(vEgo) − (vEgo−13.5)²/5`:

| vEgo (m/s) | 13.5 | 16.0 | 19.5 | 22.0 | 25.0 | 30.0 |
|---|---|---|---|---|---|---|
| brake-triggering range | 62 m | 79 m | 103 m | 120 m | 141 m | 175 m |

So at highway speed *any* accepted radar lead inside ~120–175 m with U11 on its rail commands heavy
braking. This is what makes lateral mis-binding so costly: the rail guarantees the bogus lead looks
nearly stopped, and the range band where that matters is exactly the 30–115 m band item 33 measured.

**The rail correction cannot help here, by design.** `radard.py`'s range-derived `vRel` assist
(D-053, default OFF) is **one-sided** — it may only make the published closing speed *more* closing,
never less — and `RANGE_VREL_ASSIST_MAX_ABS_Y_REL_M = 1.5` excludes adjacent-lane tracks outright.
Both properties are correct for what it was built for (D-041, recovering closing the rail hides) and
both mean it is irrelevant to a false brake. Nothing in the longitudinal stack is mistuned here.

**What the track geometry says about these objects.** Per-track range slope over the contiguous run,
against ego speed (radar frames only, duplicate ranges dropped):

- tid 26, 352.8–353.9 s: 108.3 → 79.3 m, slope **−26.3** vs vEgo 20.8 → ratio **1.26**. Closing
  *faster* than ego travels, so not a stationary object: either an oncoming vehicle (`dyPath` +3.9…
  +5.2, i.e. one to one-and-a-half lanes left) or a track whose range is drifting across objects.
- tid 35, 355.7–356.9 s: 93.0 → 72.9 m, slope **−16.8** vs 19.6 → ratio **0.86**. Apparent object
  speed +2.7 m/s: near-stationary, `dyPath` +2.9…+3.8 — adjacent lane or roadside.
- tid 29, 356.9–358.9 s: 86.3 → 57.8 m, slope **−14.2** vs 19.4 → ratio **0.73**. Apparent speed
  +5.1 m/s, and `dyPath` ≈ **0** — this one is *in* the path. Its brake is defensible, and its true
  closing (−14.2) slightly exceeds the rail, so here the rail under-reads rather than invents.

tid 29 matters as a negative control: not every railed track in the window is a lane lock, and the
one that is on-path is one the car should brake for. Only tids 26/32/35 are the complaint.

**Consequence for the roadmap.** Item 33's "still open: the longitudinal over-reaction" is
**withdrawn** — there is no such defect to chase, on either of its two cases. Item 32's 241 case
(−2.3…−3.2 m/s² for a 2.0–2.3 m/s closure at 42–45 m) computes to a deficit of −8.3 m at vEgo 20 and
is likewise the tune answering honestly: the comfort-brake asymmetry alone demands ~50 m behind a
same-speed lead at 20 m/s, so 43 m is genuinely short by the MPC's own model. Disagreeing with that
is a `COMFORT_BRAKE`/`T_FOLLOW` argument, not a bug report.

All of the remaining leverage on the user's reported symptom is therefore **in lead selection**, which
is where item 33 already pointed. Static/replay evidence only; nothing here was driven.

**Still open:** replay a candidate `dyPath` bound over all 13 routes and score leads *lost*, not
leads rejected (D-041) — 241's 6:49 real stopper at `dyPath` −0.50…+0.62 must survive, and so must
245 tid 29; the stationary-target dropout census; item 22.6 (236 track 21).
*(Item 35 does the bound scoring: 3 of 113 hard brakes touched, and 245 tid 29 sets a 2.5 m floor.)*

## 35. A `dyPath` bound scored by leads *lost*: 3 of 113 hard brakes touched, and 2 of them are the reported symptom — 2026-09-21

Item 34 concluded that all remaining leverage on the reported adjacent-lane lock-on is in lead
selection. This scores the candidate gate the census pointed at, on the metric D-041 demands: not
how many leads it rejects, but **how many frames it would leave with no lead at all.**

**The gate, stated exactly as measured.** Reject the radar-backed lead when `|dyPath| >= 2.5` **and**
vision has its own lead that is *on* the predicted path (`|dyPath_ml| < 1.5` and `mlProb >= 0.5`).
The second clause is the whole safety argument and is not decoration: the gate is only permitted to
fire when a replacement lead demonstrably already exists, so it degrades which object is followed
rather than deleting a point. Where vision disagrees, nothing is rejected.

**Cost, measured over all 13 routes** (`ybound.py`, host Python over the `ycen_*.csv` frames):

| `|dyPath|` bound | frames fired (fallback exists) | frames left alone (no fallback) |
|---|---|---|
| 2.0 | 773 | 617 |
| **2.5** | **449** | **398** |
| 3.0 | 252 | 246 |
| 3.5 | 125 | 180 |

Roughly **half of all off-path radar leads have no on-path vision lead to fall back to**, and at every
bound the gate leaves those untouched. That is the D-041 half of the result, and it is the reason to
require the vision clause rather than gate on `dyPath` alone.

**The number that matters: hard-brake episodes touched.** Classifying every episode with
`aTarget < −2.5` fleet-wide against the 2.5 m bound:

| route | episodes | kept | gated |
|---|---|---|---|
| all 13 routes | **113** | **110** | **3** |

Only **2.7% of hard-brake episodes** are touched at all, and the three are:

- **245 @ 353.5 s** — 8 of 12 frames, `|dyPath|` up to 5.21 at 81 m, floor −3.50.
- **245 @ 356.3 s** — 11 of 33 frames, `|dyPath|` up to 3.44 at 73 m, floor −3.50.
- **23e @ 23109.7 s** — **1 of 48 frames** (`dyPath` +6.09). Not a lane lock. Direct inspection shows
  the ego yawing hard (`curv` → −0.005) during a radar→vision lead handoff: track 25's `dyPath` walks
  +0.2 → +7.75 over 1.5 s while `dyPath_ml` stays under 0.8, then `radar1` goes to 0 and vision holds
  the lead at 15–25 m with a real −3.5 m/s closing rate. **The brake proceeds regardless**; the gate
  would only bring forward a handoff that happened on its own one frame later. This also confirms
  item 33's reading of the `>5 m` band as ego-yaw/junction contamination, now by inspection and not
  just by bucket share.

So the two episodes the gate actually suppresses are **exactly the event the driver reported** — the
adjacent-lane lock on the curve at 352.8–358.5 s on 245, which item 34 showed reaches the `ACCEL_MIN`
floor honestly because the Bosch-A rail makes an off-path return look nearly stopped.

**Both negative controls survive, and one of them sets the bound.**

- **241, every hard brake.** All 8 episodes (128 frames) sit at `|dyPath| < 1.1` except one at
  502.7 s, which is `radar1 == 0` — vision-sourced, so a radar-only gate cannot reach it. Every real
  241 deceleration survives any bound ≥ 2.5. (Correction to item 34's framing: the 6:49 frames carry
  `aTarget` ≈ +0.09, so that window is not itself a hard brake; the route's real stoppers are at
  257.4, 338.1, 356.0, 588.4 and 606.2 s. The conclusion is unchanged and now rests on all of them.)
- **245 tid 29** (near-stationary, in the path, brake correct — item 34's control) peaks at
  `|dyPath| = 2.22` at 358.59 s. **It is gated at a 2.0 m bound and survives at 2.5 m.** This is an
  empirical floor, not a round number: **do not set the bound below 2.5 m.**

**Method limits, stated plainly.** This is a frame-level scoring of `radarState` output, not a
`radard` replay — it measures which frames a gate would reject and what fallback existed at that
instant, not the closed-loop trajectory that would result. Two of the three gated episodes are
*partially* gated (8/12 and 11/33 frames), so the honest claim is that the brake would be reduced or
delayed, not that it would be cleanly prevented. A closed-loop replay is still the thing that would
settle the magnitude. Static/replay evidence only; nothing here was driven.

**Still open:** the closed-loop `radard` replay to get the trajectory effect rather than the frame
counts; the stationary-target dropout census; item 22.6 (236 track 21).

## 36. The closed-loop `radard` replay: the gate never deletes a lead, and the times in items 33–35 were wrong — 2026-09-21

Item 35 scored the 2.5 m `dyPath` gate at **frame level** — which published `radarState.leadOne`
frames a gate *would* reject, and whether vision offered an on-path replacement at that instant. It
could not say what lead would actually be published instead, so two of its three gated hard-brake
episodes came out only *partially* gated (8 of 12 frames, 11 of 33) and "the brake is delayed" was
indistinguishable from "the brake is prevented". This item runs the selection.

**Tool:** `/routes/an2/yrep.py` + `yrepsum.py`. Two `RadarD` instances are driven off the same rlog
stream, cycle for cycle, from the logged `liveTracks` / `carState` / `modelV2` / `starpilotPlan`. A is
untouched. B applies the frozen gate and then **re-runs `get_lead` with the offending radar track
removed from the candidate set**, repeating while the winner keeps tripping the gate;
`prev_lead_track_ids` is then set from B's *own* choice, so the Bosch-A preferred-track hysteresis
follows the replacement on every later cycle instead of re-preferring the track it just rejected.
Track Kalman states do not depend on selection, so they stay shared by construction.

**Validity first.** Restricted to cycles where the log and the baseline replay both published a
radar-backed lead, the baseline picks the **same `trackId` on 99.86–100.00% of cycles on all 13
routes** (100.00% on six of them). Status agreement is 99.35–100.00%. The harness reproduces the
drive; without that nothing below would mean anything.

**Fleet result, 310,403 cycles.** The gate fires on **163** cycles. The published lead differs on
**559** cycles — **0.180%** — across **49 divergence episodes**. The fire count is much smaller than
the divergence count because the gate fires *once* to break a lock and the hysteresis then holds the
replacement; frame-level scoring could not see that, and it is why item 35's partial-gating worry was
the wrong worry.

**The D-041 question is now answered by observation, not by argument.** At the start of the 49
episodes the replacement lead is:

| replacement | episodes |
|---|---|
| the **vision** lead | 48 |
| another radar track | 1 |
| **no lead at all** | **0** |

The gate never once deleted a lead. It is a change of *which* object is followed, in every episode
the fleet contains. That also locates the residual risk exactly: the gate's safety rests entirely on
vision's own lead being right, because vision is what it always falls back to.

**Three episodes contain a hard brake** (`aTarget < −2.5`), independently reproducing item 35's
"3 of 113" by a completely different method:

- **245 @236.6 s** — A follows tid 26 at **101.7 m, `vRel` −13.50** (the U11 saturation rail),
  `dyPath` +4.17. B follows vision at **74.3 m, `vRel` −7.34**, `dyPath` −0.98.
- **245 @239.3 s** — A follows tid 35 at **93.0 m, `vRel` −13.50**, `dyPath` +3.53. B follows vision
  at **84.8 m, `vRel` −3.64**, `dyPath` −0.52.
- **23e @1787.0 s** — A follows tid 25 at 36.0 m, `vRel` −2.30, `dyPath` +2.77. B follows vision at
  **33.4 m, `vRel` −4.51** — *closer, and closing faster.* The gate would make this brake **harder,
  not softer**. Item 35 called this outlier a single frame of 48 and said the brake proceeds
  regardless; closed-loop it is 11 cycles, and the brake does not merely proceed, it strengthens.

On the two 245 episodes B swaps a **railed** lead (`vRel` pinned at the rail, so `long_mpc` loses its
stopped-equivalence term — item 34) for an unrailed one with a real closing rate. That is the
mechanism by which the reported symptom would go away. **The magnitude is still not measured:** that
needs the two lead streams pushed through the MPC, which is the next step and is now unblocked
(`LongitudinalMpc` instantiates in the analysis image).

### A correction that affects every time cited in items 33, 34 and 35

**`ycen.py` writes raw `logMonoTime`, not route-relative ns.** The checkpoint invariant that said
otherwise was wrong, and `ysum.py` / `ybound.py` divide that column by 1e9 with no `T0` subtraction,
so **every time printed by items 33–35 is high by that route's `min(seg_t0)`**:

| route | `T0` (s) | route | `T0` (s) | route | `T0` (s) |
|---|---|---|---|---|---|
| 231 | 77919.70 | 237 | 5901.74 | 23f | 10567.81 |
| 232 | 17367.82 | 239 | 11865.87 | 241 | **38.63** |
| 236 | 3119.15 | 23a | 15469.67 | 245 | **116.46** |
| 23b | 20796.82 | 23e | 21323.47 | 246 | 1641.77 |
| 248 | 31.76 | | | | |

So item 35's "245 @353.5 s / @356.3 s" are route **236.6 s / 239.3 s**, its "23e @23109.7 s" is route
**1787.0 s**, its "245 tid 29 @358.59 s" is route **242.1 s**, and item 33's "245 at 352.8–358.5 s" is
route **236.3–242.0 s**. This replay, which subtracts `T0`, lands on exactly those corrected times —
the two harnesses agree and only the labels were wrong. **No physics, count or conclusion in items
33–35 changes**, because each was computed in one internally consistent base. This is the third time
the time base has cost a correction.

**One control was genuinely measured in the wrong place.** `ybound.py` pinned the driver-reported 241
6:49 window at `t` 409.0–410.5, which on that route is route **370.4–371.9 s — about 6:10, 39 s
early**. Re-examined at the correct route 400–420 s: `vEgo` 1.1–8.5 m/s in slow traffic, min `aTarget`
−0.84, **max `|dyPath|` 0.86, and zero frames the gate could even consider**. The 241 control passes
at the right window, and now passes *where the driver actually reported the event* — a stronger
result than item 35 had. Item 35's claim that the 6:49 window is not itself a hard brake also
survives, but it had been measured at the wrong window.

Two further cautions from the corrected read: from route 411.7 s that window has `aTarget` exactly
`0.0000`, and **56% of route 241's frames carry `longActive == 0`** — openpilot longitudinal is not
engaged, so `aTarget` there is not evidence about what openpilot would have done. Any `aTarget`-based
scoring on 241 must be read with that in mind.

Replay/static evidence only; nothing here was driven.

**Still open:** the MPC pass for the braking magnitude on the two 245 episodes; the stationary-target
dropout census; item 22.6 (236 track 21).

## 37. The planner-level pass: the gate belongs on both lead slots, it is not mergeable, and `FarLeadBrakeLimit` is structurally inert — 2026-09-21

This scores the `dyPath` gate one level higher than item 36: **through the real
`LongitudinalPlanner`**, not at `radarState`. `$T/an2/ympc.py` (in the `oprad-routes` volume at
`/routes/an2/`) builds N planner instances off one rlog stream and swaps only `radarState` between
them, so every variant sees identical frames, identical `carState`, identical `modelV2`. Nothing
longitudinal is reimplemented — it is the shipped planner, including arbitration, `t_follow`,
`jerk_scale` and the BLoTv3 supervisor. Variants: `A` baseline, `B` gate on `leadOne`, `C` gate on
both slots, `Apre`/`Bpre` the pre-`084a9d56` BLoTv3 feedback read, `Aoff` BLoTv3 off, `Aflbl`
`FarLeadBrakeLimit` forced on.

**This corrects item 36's expectation.** Item 36 predicted the two 245 hard brakes would "soften a
lot" once the gate ran closed-loop. Measured, they do not: every variant still reaches min `aTarget`
−3.50, and the `leadOne` gate only cuts time below −2.5 from 2.30 s to 2.00 s.

**Why: `radarState` has two published lead slots and items 35–36 scored only one.**
`LongitudinalMpc.update` takes `min()` over `lead_0_obstacle` and `lead_1_obstacle`, and
`longitudinalPlanSource` at the 245 237.2 s peak reads **`lead1`** — the brake was sourced from
`radarState.leadTwo`, which the frozen gate never touches. The railed off-path track simply
reappears in the second slot. Gating both slots (variant C) on 245 234–243 s:

| variant | min `aTarget` | s below −2.5 | s below −1.5 |
|---|---|---|---|
| A baseline | −3.50 | 2.30 | 2.50 |
| B gate on `leadOne` | −3.50 | 2.00 | 2.45 |
| C gate on both slots | −3.50 | **1.00** | **1.10** |

57% less time in hard braking against 13%. It shortens the brake; it does not prevent it. The
residual is 245 tid 29 at `|dyPath|` 2.22, below the frozen 2.5 floor by design (item 35).

**And the gate is NOT mergeable, because the cost is now quantified.** On 23e 1783–1792 s the gate
makes the brake *worse*, and variant C is identical to B there (11 differing cycles, same numbers):

| variant | min `aTarget` | s below −2.5 |
|---|---|---|
| A baseline | −1.55 in the divergence run | 2.35 |
| B / C | **−3.50** | **2.90** |

Mechanism, from the run's own lead columns: the gate drops radar tid 25 at `dRel` 36.0,
`vRel` −2.30, and selection falls through to the **vision** lead at `dRel` 33.4, `vRel` −4.51 —
nearer and closing twice as fast. The gate fired on **1 cycle** and produced 11 divergent cycles,
because dropping the track also reset `prev_lead_track_ids` and handed the slot to vision for the
rest of the episode. This is D-041 measured rather than argued: deleting a radar point cost 2.32
m/s² of extra braking on an episode where the radar lead was the gentler answer. **Do not ship the
`dyPath` gate in this form.** What it needs is a replacement that is *bounded*, not a deletion — the
gate may only stand a lead down when the object taking its place is not more urgent.

**`FarLeadBrakeLimit` is structurally inert, and this is why it is removed in this commit.** Variant
`Aflbl` (cap forced ON) differs from `A` on **0 cycles in every window measured** — 245 234–243 s,
245 180–270 s (1800 cycles), 23e 1783–1792 s, 241 380–470 s (1798 cycles) — including both of the
worst far-lead hard brakes in the fleet, 90 m leads at −3.50. The cap never engaged once.
`get_far_lead_brake_limit` stands itself down when `ttc = dRel / closing < FAR_LEAD_BRAKE_LIMIT_MIN_TTC
= 10.0`; on the U11 saturation rail (item 34) `closing` is pinned at 13.5 m/s, so a 90 m lead reads
TTC 6.7 s. **The rail that causes the false brake is what makes the cap blind to it.** It can only
fire on leads whose `vRel` is not railed — genuine closers — which is the whole of its 1-good-vs-6-bad
record, and it cannot be tuned out: raising `MIN_TTC` past the rail's own TTC parks the cap directly
on top of real emergency braking. See D-060.

**James's `084a9d56` (BLoTv3 supervisor reads the MPC target, not the arbitrated output) is correct
but not exercised by any window measured.** `Apre` vs `A` = **0 differing cycles** on all four
windows above, 241 included. The fix only bites where the arbitrated output is much more negative
than the MPC's own lead solve (curve limiter, red light, force-decel), and none of these windows
contains that divergence. Report it as unexercised, **not** as ineffective. `Aoff` (BLoTv3 off)
differs on 97 cycles over 245's 90 s span, with BLoTv3 slightly *lengthening* hard braking
(2.70 s on vs 2.55 s off) and on 23e shortening it (2.15 s off vs 2.35 s on) — small, and not
the subject of this item.

**Toggle census from `initData`:** routes 245, 246 and 248 all ran `FarLeadBrakeLimit=0` and
`BlotV3=1`. The driver reports the last two drives did not over-react with the cap off. That is
limited road evidence consistent with the cap being inert, not with the cap having helped.

Replay/static evidence only; nothing in this item was driven.

**Still open:** a bounded (non-deleting) replacement for the `dyPath` gate on both slots — now
designed as **D-061 (proposed, not implemented)**, which bounds the obstacle in the planner instead
of gating selection, and whose first prerequisite is that **`dyPath` does not exist online at all**;
a window that actually exercises `084a9d56`; item 22.6 (236 track 21). **The stationary-target
dropout census is done — see item 38**, which also retracts three intermediate claims made while it
was being built.

## 38. The near in-lane target-dropout census: 5 events on 4 routes, and the evidence points at geometry, not a failing sensor — 2026-09-21

> Extended to 17 routes by **item 39**, which adds 248 (full), 249, 24b and 24d. The conclusion is unchanged.

Closes the "stationary-target dropout census" left open in items 31 and 37. Replay evidence only,
decoded at the CAN/wire level (pre-parser). Nothing here was driven.

### The premise was wrong, and correcting it changed the metric

The starting report was that on 241 at 9:36 *"the radar returned 16 invalid slots — completely
blank — for 3.7 seconds"*. Measured over all 894 sweeps of 241 segment 9, the longest all-16-invalid
run is **0.14 s** (2 sweeps). Only 8 of 894 sweeps have zero valid objects; the `n_valid` histogram
is `{0:8, 1:42, 2:480, 3:308, 4:47, 5:9}`. What lasted ~3.7 s was **track 20, the near in-lane lead,
being absent** while the radar kept reporting other objects — which is what item 31 always said.

**"All 16 slots invalid" is therefore the wrong metric.** On 241 the longest such run is 44.98 s, at
`longActive=False` and `vEgo` ~0 — a parked car. On an empty road the Bosch-A legitimately reports
nothing. The right metric is a **near in-lane target dropout**: an object with `d < 40 m`,
`|y| < 2.0 m`, existence `>= 32`, held `>= 0.5 s`, that then leaves the box, where the track id does
not reappear anywhere in the object list.

Every other number in the original report checks out: commanded `accel` 0.76 -> **1.67** -> 1.80 m/s²
with `longActive=True`, `leadOne` degrading to vision-only then `None`, model lead probability
0.95 -> 0.24, and driver intervention at 9:37.74. The slot was invalid at the wire level, so the
radar genuinely stopped reporting it — **our parser caused none of it.**

### Result: 13 routes, 264 segments, 5 events on 4 routes

```
route  route-time  dur     tid  d      y     exFade   drate  accel@loss  vEgo         mlprobMin
241     9:35.73   71.36s   20   26.0  -1.9   67/126   +1.6    +0.72      3.0 -> 14.2   0.00
241     4:06.92   13.77s   22   28.3  -1.4   68/68    +2.2    +0.78     13.0 -> 17.5   0.66
236    28:16.84   29.49s   37   11.8  -2.0  126/126   -1.4    +0.86     24.1 -> 30.3   0.84
23f     3:57.19    2.67s   24   15.4  -1.4   74/109   -5.3    +0.49      8.1 ->  9.5   0.21
248    10:33.39    3.50s    2   39.2  +0.5   78/126   -0.5    +0.17     12.0 -> 13.4   1.00
```
Zero on 231, 232, 237, 239, 23a, 23b, 23e, 245, 246.

### The finding: four of the five died at the edge of the box

`y` at loss is **−1.9, −1.4, −2.0, −1.4** against a box half-width of 2.0 m. On 241's track 20 the
azimuth is *still drifting outward* as the existence decays 126 -> 94 -> 68 -> 67. That is as
consistent with the target leaving the radar's beam as with the radar failing to hold it, and
nothing measured here separates the two.

The fifth, 248 10:33, is the only one lost near boresight (`y +0.5`) — and there the **camera still
held the lead at probability 1.00**, so no lead was lost at all.

**This census does not establish a radar dropout fault.** It establishes that near in-lane tracks
are lost at the lateral edge of the in-lane box while the sensor keeps reporting. The discriminating
observation — not yet found in any route — would be a **fade-then-die with the target centred**,
`|y|` small throughout while existence halves. Until that exists there is no signal to gate on, and
**D-041 forbids a gate that deletes a point on a suspicion this weak.** No code change is proposed.

### Four detector defects, each of which produced a confidently wrong answer first

Recorded because each one passed quietly and the census looked clean while wrong.

1. **Closing gaps at segment boundaries missed the event that prompted the census.** 241's 9:36
   dropout runs to the end of segment 9. `logMonoTime` is continuous across segments, so a real
   dropout may span one. Exclude recording holes with a sweep-to-sweep `MAX_DT = 2.0 s` check
   instead. *Any census that cannot find the event you already know about is not measuring it.*
2. **Geometry cannot classify an exit.** A `|y| >= 1.6 m` test labelled 241 track 20 a clean lateral
   exit, because its azimuth wandered to the edge as its return weakened. Use **track survival**.
   A "seen at all within 1.5 s" survival test *also* mislabelled it — it was in the object list for
   0.07 s more. Require the re-sighting at **0.75 s or later**. Ground truth from a sweep-by-sweep
   trace: track 20 held 235 consecutive sweeps, rt 560.09..575.80, no gap > 0.5 s, never returned.
3. **Engagement and acceleration were read from different moments.** `longActive` was an OR over the
   whole gap and peak accel a max over its first 5 s, so a row could report "engaged and
   accelerating" when the car was engaged at one instant and accelerating at another. On **23e
   23:46.08** it did: the driver disengaged at 23:43.68, the track died 2.5 s later with the car
   under manual control, and the +1.14 m/s² came from after a re-engagement at 23:48.03. That row
   was reported as a worse instance of 241 before this was caught; **it is not an openpilot event at
   all.** Record engagement and accel **at the moment of loss** and gate on that. Two rows demote
   (23e 23:46.08, 236 32:04.95, both `accel@loss = 0.00`).
4. **Oncoming traffic is not a dropout.** An oncoming car crosses the boresight, sweeps the in-lane
   box for ~1 s and leaves the near field at ~10 m, **dying at full existence with no fade** — the
   exact "no warning" signature. Two such crossings (232 10:05 track 1, 23e 13:38 track 9) were
   reported as a distinct fault population that a degradation-based gate would miss. Both are
   oncoming: range collapsing at ~29 m/s while `vEgo` was 14–16 m/s, `y` sweeping −4.6 -> +2.8.
   Nothing ahead can close faster than ego speed. Classify `d_rate < -(vEgo + 3)` as **oncoming**
   (15 such gaps fleet-wide), and compute `d_rate` over **one track id**, never over "nearest
   in-lane object", which switches tracks and yields rates no object had (−29.7, −30.9 m/s).

### Caveats on these numbers

- **The 248 row is from a partial route.** Only 8 of 23 segments were cached, and not contiguous
  (0,1,2,4,6,9,10,11). The full route arrived 2026-09-21 and has not been re-censused.
- Routes `00000249--d481c5de77`, `0000024b--02cabe206c` and `0000024d--f80e13b850` arrived the same
  day and are **not** in this census.
- `seg_t0` in `/routes/an2/scan_<route>.json` **cannot be used to locate a segment**: every entry
  reads the same value because each segment's first `logMonoTime` is `initData` (all 42 entries of
  23e read offset 0.0). The global `T0 = min(seg_t0)` is correct; segment index comes from
  `route_time // 60`.

## 39. Four more routes censused (248 full, 249, 24b, 24d): the geometry finding holds, and a separate range-rate latency shows up on 24d — 2026-09-21

Extends item 38 from 13 routes to **17 routes / 343 segments**.
> **Corrected by 39.5:** that is 17 route-*entries* over **16 routes / 335 segments** — 248 is
> counted twice, partial then full. The events and the conclusion are unaffected. Routes added, all fetched complete
into the `oprad-routes` volume and rescanned with `/routes/an2/scan.py`:

| route | segs | in-lane gaps | >=1.0s | dangerous |
|---|---|---|---|---|
| `00000248--4f275f0bb6` | 23 (was 8, non-contiguous) | 10 | 5 | **1** |
| `00000249--d481c5de77` | 6 | 19 | 9 | 0 (1 demoted, not engaged at loss) |
| `0000024b--02cabe206c` | 18 | 83 | 19 | **0** — all 19 classified `exited` |
| `0000024d--f80e13b850` | 32 | 57 | 33 | **1** |

**248's row is confirmed, not corrected.** Item 38 scored 248 on 8 of 23 segments. The full route
returns the *same single event* at 10:33.39 (tid 2, d=39.2, y=+0.5, exFade 78/126, camera held the
lead at mlprob 1.00). The partial-route row was right by luck, but it was right.

**The one new event, 24d 18:47.38**, fits the item 38 pattern and does not challenge it:
`tid=21 d=37.4 y=-2.0 ex=126 held=2.5s drate=+6.1 exFade=126/126 blank=0.0% mlprobMin=0.00`.
`y = -2.0` is exactly the edge of the +/-2.0 m box, and `drate = +6.1` means the target was
**receding at 6 m/s** while ego accelerated 14.5 -> 21.9 m/s. A receding target drifting off the
lane edge is a vehicle being left behind, not a sensor failure. Existence never faded (126/126).

**Fleet total: 6 events on 5 routes out of 17 routes. Five of the six died at |y| >= 1.4 m against
a 2.0 m box.** The discriminating observation named in item 38 -- a fade-then-die with the target
**centred** -- still does not occur anywhere in the fleet. Item 38's conclusion stands: no deletion
gate is justified on this evidence, and D-041 forbids one on evidence this weak.

### 39.1 A separate finding on 24d: the lead range rate lags the true range slope by ~1 s

This is NOT a dropout and is NOT part of the census. It came from investigating the reported
"strange early braking / it insists on keeping a certain distance with lead" on 24d.

24d has **23 braking episodes** with `longActive` and `aTarget < -1.0`; **ten of them pin at
aTarget ~ -3.5**, which is a rail, not a computed demand. Tracing the 5:18 episode against the
route CSV:

| route-time | d1 (m) | measured range slope | `leadOne.vRel` | `liveTracks` vRel (U11) |
|---|---|---|---|---|
| 5:17.14 | 54.2 | **-4.0** | +0.09 | +0.09 |
| 5:17.35 | 53.5 | **-6.1** | +0.02 | +0.02 |
| 5:17.55 | 52.5 | -6.4 | -3.42 | -0.20 |
| 5:18.15 | 49.0 | -6.6 | -5.44 | -1.36 |
| 5:18.35 | 47.8 | -5.7 | **-5.77** | -2.09 |
| 5:19.14 | 43.7 | -5.3 | -3.48 | -3.48 |

Two things, in order of confidence:

1. **Both estimators read ~0.0 m/s while the range was already closing at 4-6 m/s**, for roughly
   one second (5:17.1 -> 5:17.5). The radar did not report the lead's deceleration until the gap
   had already closed ~8 m. When `vRel` finally catches up, the planner has to make up the deficit
   at once -- which is why the demand goes straight to the -3.5 rail and holds it 1.5 s. The brake
   is **late in detection and therefore hard**, not early. From the seat it reads as "early"
   because there is still 47 m of gap.
2. **`leadOne.vRel` converges much faster than the raw U11 track vRel** (error ~1.1-1.5 m/s vs
   ~4.7-6.2 m/s through the transient). An earlier reading of this table had it backwards -- that
   our estimate was overshooting and driving the brake. It is not: checked against the measured
   range slope, ours is the closer of the two and the native U11 lags ~1.5 s. Recorded because the
   wrong version is the intuitive one.

**Instrument corrected (centred difference).** 39.1's table above used a 0.5 s *forward*
difference, which leads the truth by ~0.25 s and inflated the slope. Re-run with a centred
+/-0.5 s difference, the finding holds but is smaller:

| route-time | d1 (m) | centred slope | fwd slope (old) | `leadOne.vRel` | U11 vRel |
|---|---|---|---|---|---|
| 5:17.10 | 54.5 | -3.45 | -4.30 | +0.16 | +0.09 |
| 5:17.26 | 53.7 | -4.21 | -4.85 | +0.05 | +0.05 |
| 5:17.40 | 53.2 | -4.61 | -5.49 | **-2.96** | -0.08 |
| 5:18.15 | 49.0 | -6.27 | -6.62 | -5.44 | -1.36 |
| 5:19.05 | 44.5 | -5.14 | -6.62 | -3.20 | -3.20 |

Corrected magnitudes: the blind window is **~0.8 s** (5:16.6 -> 5:17.40), not ~1 s, and the peak
under-read is **~4.3 m/s**, not 6. `leadOne.vRel` breaks away at 5:17.40 and tracks within
0.6-2.0 m/s; the raw U11 track vRel does not converge until ~5:19.0, so it lags by **~1.6 s**.
Both conclusions in 39.1 survive the correction; only the numbers move.

### 39.2 RETRACTED: the tFollow/desiredFollowDistance zeros are a disengagement, not a defect

39.1 closed by calling the simultaneous zeroing of `tFollow`, `desiredFollowDistance` and
`minAcceleration` at 5:25.24 "not yet explained" and pointing at longitudinalPlanSP. **That was
wrong.** At that same sample `longActive`, `enabled` and `active` all go 1 -> 0 together: the
driver disengaged. `StarPilotFollowing.update()` sets `t_follow = 0` in its `else`
(`not long_control_active`) branch and `desired_follow_distance = 0` alongside it, so the zeros
are the documented behaviour of a disengaged system.

Confirmed fleet-style on the route itself: **0 of 22,038 `longActive` samples on 24d have
`tFollow == 0`.** The zeros never occur while engaged.

Consequence for the complaint: the slow crawl from 5:25 to 5:36 (6.3 -> 0 m/s, gap 39 -> 10 m)
was **the driver**, not openpilot. Only the ~5 engaged seconds before the disengagement belong to
the car.

One real oddity noted but NOT established: `carState.cruiseState.speed` reads 0.0 through this
window while the planner's own `vCruise` reads 22.22 m/s. I did not determine whether that is
normal for this Honda or a reporting gap, and nothing here rests on it.

### 39.3 The padding behaviour is real, rare, and still without a mechanism

The engaged window 5:21 -> 5:25 is genuine and matches the reported complaint: `vEgo` 6.3 m/s flat,
gap 38-40 m, `desiredFollowDistance` 13-14 m, set speed 22.2 m/s, `maxAcceleration` 1.77,
`disableThrottle` 0, `shouldStop` 0 -- and `aTarget` sitting at **+0.05**. The car wants a 13 m gap,
has 39 m, has 16 m/s of speed deficit and full throttle headroom, and commands nothing.

Scored across the route with a deliberate signature (tracking a lead, gap > 2.5x desired,
|aTarget| < 0.25, `maxAcceleration` > 0.8, set speed at least 5 m/s above `vEgo`, throttle not
disabled, not stopping):

- **93 samples = 4.7 s out of 1102 s engaged (0.4%).**
- `longitudinalPlanSource` is `cruise` on **all 93**.
- median `vEgo` 6.3 m/s (range 4.2-16.5) -- it is a low-speed, post-deceleration behaviour.

**Two hypotheses tested and both rejected.** (a) A `t_follow` defect: rejected by 39.2. (b)
Experimental mode / e2e longitudinal: rejected -- the 93 samples split 49/44 between `expMode` 1
and 0, while the route runs 5081/16922 in favour of `expMode` 0, so the behaviour is not tied to
it. The common thread is only `src == cruise` at low speed after a deceleration.

**Open:** why the cruise cost yields ~0 m/s^2 with a 16 m/s speed deficit and 1.77 m/s^2 of
headroom. That is a `longitudinal_mpc_lib` / cruise-cost question. 4.7 s on one route is too
little to tune against -- the next step is to run this same signature across all 17 routes before
anyone touches a cost weight.

### 39.4 The padding signature run fleet-wide: 24d is unremarkable, and there is nothing to tune

39.3's closing step is done. The same signature (tracking a lead, gap > 2.5x desired,
`|aTarget| < 0.25`, `maxAcceleration > 0.8`, set speed at least 5 m/s above `vEgo`, throttle not
disabled, not stopping) was scored over all **16 cached routes, 11,221 s of engaged time**, from
the `scan_<route>.csv` whole-route dumps. Script: `$CLAUDE_JOB_DIR/tmp/padfleet.py` (job-local).

**Fleet: 673 samples = 58.7 s of 11,221 s engaged (0.52%).** Per route, as a share of that route's
engaged time: 23f 1.14%, 236 1.01%, **24d 0.63%**, 232 0.55%, 237 0.51%, 245 0.35%, 248 0.22%,
23e 0.14%, 241 0.13%, 24b 0.05%, 23a 0.00%; and **zero samples on 231, 239, 23b, 246**.

- **24d is not an outlier.** At 0.63% it sits mid-pack, below 23f and 236. Whatever the drive felt
  like, the route is not measurably more padded than the rest of the fleet.
- **`longitudinalPlanSource` is `cruise` on 669 of 673 samples** (the other 4 are `lead0`/`lead1`
  on 236). This is the one property that holds fleet-wide and it confirms 39.3's read.
- **`expMode` does not track it,** again: 232 splits 0/70, 237 splits 78/11, 23f 135/44. The
  behaviour appears on both sides of the toggle on different routes, so it is not e2e longitudinal.

**The signature does not describe a sustained behaviour, which is the finding that matters.**
The longest contiguous episode anywhere in 11,221 s is **3.51 s** (23f 23:00.60); 24d's 5:21.60
window is **2.39 s**, the second longest. Sweeping the `aTarget` cap to see whether a slow-approach
mode was being excluded by the tight threshold:

```
 cap   samples   secs  % eng  eps>=1s  longest
0.25       550   51.5  0.41%        6    3.51s
0.40       887   75.0  0.60%       10    6.15s
0.60      1263  105.2  0.85%       17    6.15s
0.80      1761  142.7  1.15%       29    6.15s
1.00      2408  185.9  1.50%       46    6.15s
```

The sample count and the engaged share grow roughly linearly with the cap while the longest episode
**stops moving at 6.15 s**. That is the shape of ordinary distribution mass being swept up by a
widening threshold, not of a distinct behaviour mode with its own duration scale. A real
"insists on keeping a certain distance" fault would show sustained episodes that appear once the cap
clears their operating point; none do.

**Conclusion: no cruise-cost change is justified on this evidence, and 39.3's open question is
closed as not actionable.** The brief near-zero-`aTarget` samples are real and they are concentrated
in `src == cruise` at low-to-mid speed after a deceleration, but they are transient (median episode
well under a second, maximum 6.15 s across the whole corpus) and no worse on the route that
prompted the complaint. Touching a `longitudinal_mpc_lib` cost weight to chase 0.5% of engaged time
would be tuning against noise. **What would reopen this is a drive where the driver marks the
timestamp of the padding as it happens** -- the complaint may be about a window this signature does
not capture at all, and 4.7 s buried in 1102 s cannot be matched to a memory of a drive.

Replay/offline evidence only. Nothing here is road-validated.

### 39.5 The census re-run as one uniform pass over all 16 routes: every event reproduces, and the route/segment count was double-counted

Items 38 and 39 spliced **two different runs** — 13 routes, then 4 more — and 248 was scored twice
(8 non-contiguous segments in item 38, the full 23 in item 39). That splice is the reason to re-run,
not a doubt about the events. This is one consistent pass: the durable
`tools/bosch_a_dropout_census.py` with `DUMPALL=1` and `min_gap 1.0` over every route that has a
`scan_*.json`, run route-by-route from a single detached driver.

**The six events reproduce exactly — same routes, same route-times, same track ids, same `y`,
`exFade`, `drate`, `accel@loss` and `mlprobMin`.** So do all three demotions
(23e 23:46.08, 236 32:04.95, 249 2:13.91 — each `accelAt0 = 0.00`, the defect-3 gate from item 38).
Nothing in items 38, 39 or their conclusion changes.

#### The one correction: 16 routes / 335 segments, not 17 / 343

Item 39's header says "17 routes / 343 segments". There are **16 distinct routes and 335 segments**.
The extra route-entry and the extra 8 segments are 248 counted twice — item 38's partial 8-segment
copy plus item 39's full 23. The arithmetic closes: 264 − 8 = 256 over 12 routes, plus item 39's
79 (23 + 6 + 18 + 32) = **335**. Read item 38's "17 routes" as *17 route-entries over 16 routes*.

#### The full pre-filter picture, which items 38 and 39 only ever reported as zeros

| route | segs | in-lane gaps | ≥1.0s | `exited` | `oncoming` | `DROPOUT` | strict |
|---|---|---|---|---|---|---|---|
| `00000231--5782493b00` | 3 | 22 | 3 | 3 | 0 | 0 | 0 |
| `00000232--3a01619ce5` | 29 | 43 | 30 | 26 | 1 | 3 | 0 |
| `00000236--60bfb34cb1` | 42 | 78 | 53 | 39 | 3 | 11 | **1** |
| `00000237--77313c5a66` | 30 | 69 | 26 | 21 | 4 | 1 | 0 |
| `00000239--d1cf55daa7` | 16 | 35 | 14 | 12 | 0 | 2 | 0 |
| `0000023a--5c3a439dfc` | 18 | 34 | 10 | 5 | 0 | 5 | 0 |
| `0000023b--7f6d4c1ba9` | 5 | 11 | 6 | 4 | 0 | 2 | 0 |
| `0000023e--9a40b07f55` | 42 | 111 | 37 | 28 | 3 | 6 | 0 (1 demoted) |
| `0000023f--66ddbb900a` | 32 | 70 | 27 | 22 | 1 | 4 | **1** |
| `00000241--7948e97423` | 12 | 37 | 11 | 5 | 1 | 5 | **2** |
| `00000245--1356bb0355` | 19 | 63 | 17 | 12 | 1 | 4 | 0 |
| `00000246--52b04ed170` | 8 | 17 | 9 | 5 | 2 | 2 | 0 |
| `00000248--4f275f0bb6` | 23 | 10 | 5 | 3 | 0 | 2 | **1** |
| `00000249--d481c5de77` | 6 | 19 | 9 | 4 | 0 | 5 | 0 (1 demoted) |
| `0000024b--02cabe206c` | 18 | 83 | 19 | 19 | 0 | 0 | 0 |
| `0000024d--f80e13b850` | 32 | 57 | 33 | 29 | 0 | 4 | **1** |
| **TOTAL** | **335** | **759** | **309** | 237 | **16** | 56 | **6** |

Two things this table says that the earlier write-ups did not:

1. **56 gaps carry `kind=DROPOUT` at the pre-filter stage; 6 survive the strict gate, 3 more are
   demoted at the engagement check.** The other 47 fail on engagement, acceleration, hold time or
   the box — i.e. the strict gate is doing almost all of the work, and **`kind=DROPOUT` on its own
   is not a fault count.** Anyone reading a raw census log should not quote the 56.
2. **16 oncoming crossings, not 15** as item 38's defect-4 note says. The extra one is bookkeeping
   from the same splice; the classifier (`d_rate < -(vEgo + 3)`) is unchanged and correct.

`0000024b--02cabe206c` remains the clean control: **19 gaps ≥ 1 s, all 19 `exited`, no `DROPOUT`
kind at all.** A route with that many long in-lane gaps and zero dropout-shaped ones is the strongest
single argument that the shape is geometric.

#### Still absent, and it is the thing that would change the answer

**No fade-then-die with the target centred, anywhere in 335 segments.** Of the six strict events the
`y` at loss is −1.9, −1.4, −2.0, −1.4, −2.0 and +0.5, and the one near boresight (248 10:33) kept the
camera lead at probability 1.00. Item 38's conclusion is unchanged and now rests on a single
uniform pass: **no deletion gate is justified, and D-041 forbids one on evidence this weak.**

Replay evidence only. Nothing here was driven. Benign stderr on every route: the `CANParser ...
not valid (timeout or missing)` lines are the parser's cold start before the first radar frame.

## 40. James's `3a257065d` reconciled against our `longitudinal_planner.py` — DO NOT MERGE IT

The long-carried open item. James's commit `3a257065d` ("long: feed the BLoT supervisor the MPC
target, not the arbitrated output") was never merged here because we already carry the same fix
twice: `552798ab0` and `084a9d56e`, de-duplicated by `95ce224f2`. This is the deliberate diff that
was owed, done as a diff and not a merge.

### The fix is carried in full, exactly once

Every line James's commit adds, normalised for the BLoTv2 -> BLoTv3 rename, appears **exactly once**
in our tree; both lines it removes appear **zero** times:

| element | ours |
|---|---|
| `JERK_SCALE_MIN` added to the supervisor import | `longitudinal_planner.py:23` |
| `self.last_mpc_a_target = 0.0` in `__init__` | `:635` |
| `self.last_mpc_a_target = float(self.a_desired)` on reset, after the aEgo clip | `:2150` |
| supervisor fed `float(self.last_mpc_a_target)` instead of `output_a_target` | `:2246` |
| `blotv3_jerk_scale` clipped to `[JERK_SCALE_MIN, 1.0]` at `set_weights` | `:2433` |
| `output_a_target_mpc = None` before the model-path branch | `:2555` |
| write-back after arbitration, before the caps | `:2603` |

`output_a_target_mpc` is assigned on the tinygrad path at `:2561` and stays `None` on the classic and
default paths, so the write-back's `is not None` fallback is what carries those two. The write-back
sits after the experimental speed handoff (`:2591`) and before `comfort_output_accel_min` (`:2605`),
which is the point the fix requires: the MPC solution is captured before the vision caps, the curve
limiter, the force-decel floor and the stop-go target can touch it. `blotv3.py` exports
`JERK_SCALE_MIN = 0.3`, and `a_mpc` is the same third positional parameter of
`BLoTv3Supervisor.update()`.

### The entire remaining divergence in this file is the rename plus one blank line

`git diff 3a257065d HEAD -- selfdrive/controls/lib/longitudinal_planner.py` is **27 insertions,
26 deletions**, and every one of them is either a `blotv2`/`BLoTv2`/`BlotV2` -> v3 identifier,
comment or param-key rename, or a single added blank line at `:158`. **There is nothing in James's
version of this file that we lack**, and nothing of ours that his fix would improve. A merge or
cherry-pick would apply the fix a third time; `git apply -3` reports conflicts on it. **Do not merge
`3a257065d`. The item is closed.**

### What the reconciliation did turn up: the rename silently dropped the toggle for one drive

The rename changed the Params key from `BlotV2` to `BlotV3`. `common/params_keys.h:373` registers
`{"BlotV3", {PERSISTENT, BOOL, "0", ...}}` — default **off** — and nothing migrates the old key. No
`BlotV2`/`blotv2`/`BLoTv2` reference survives anywhere in the tree, so the rename itself is clean,
but the stored value did not carry. Read from `initData` on all 16 cached routes:

```
231 232 236 237 239 23a 23b 23e    BlotV2=1   BlotV3 absent   (pre-rename builds)
23f                                BlotV2 absent   BlotV3=0    <-- BLoT ran DISABLED
241 245 246 248 249 24b 24d        BlotV2 absent   BlotV3=1
```

**23f is a drive with the supervisor off**, between the rename and the toggle being re-set. This is
the same failure mode as D-053 (believed on, never stored) and it argues for checking `initData`
before crediting any toggle, which the project memory already says.

**Tempting but not supported:** 23f is also the highest row in the 39.4 padding table (1.14% of
engaged time) and the one route where BLoT was off. But 236 sits at 1.01% with `BlotV2=1`, so the
supervisor being off does not separate the populations. n=1 either way. **Do not read 23f's 39.4 row
as a BLoT effect.**

### Verification

`selfdrive/controls/tests/test_longitudinal_planner.py` + `selfdrive/controls/lib/tests/test_blotv3.py`:
**519 passed** (`-W ignore::DeprecationWarning`, required or the planner file fails collection under
NumPy 2.5). Static and unit-test evidence only. No replay and no road validation of the BLoT path.

## 41. Two changes carried in from the upstream review: the pursuit tail, and a renamed-toggle migration

Both land on `ns-bosch-radar-testing`. Both are **unit-test evidence only — no replay, no road
validation.** Neither is a fix for anything observed on our own routes.

### Half A — the pursuit tail (`f7a85a35a`)

Ported from upstream `SpysyWeeb/Spysypilot` `cdf8e54c9` (2026-09-02), `necessity_supervisor.py`.
Our port baseline was `7aed8763c`, so this was the **one real behavioural gap** in the upstream
supervisor. The other two supervisor commits since that baseline are not gaps: `7dfe70610` removes
dead `stand_down` code we never carried, and `7f0a9ad37` is naming only
(`STOPPED_LEAD_FULL_DECEL = 1.2`, already the literal `1.2` in `blotv3.py`).

**The problem.** The recovery trigger disarms at the plan's zero crossing — which is exactly the
frame where the MPC has to swing from braking to acceleration. So the pickup behind a lead that has
driven off is made with the **stock stiff jerk cost**, the one the supervisor had just spent the
whole braking episode softening.

**The mechanism.** `PURSUIT_TAIL_S = 3.0` in `selfdrive/controls/lib/blotv3.py`:

- arms `self._pursuit_s = PURSUIT_TAIL_S` while `recovery_active and lead.acceleration > LAUNCH_ALEAD_ON`;
- clears outright on `lead.acceleration <= 0.0` (the lead stopped pulling — not a pursuit any more);
- otherwise decays by `self.dt`;
- feeds one disjunct:
  `if recovery_active or model_active or launch_active or self._pursuit_s > 0.0: scale_target = JERK_SCALE_MIN`.

Cleared in `reset()`, on the emergency bypass, and on the not-present/crawl branch. A pull-away that
ends in a crawl is not a pursuit, so the tail is deliberately **not** held through the low-speed latch.

**It touches `jerk_scale` ONLY — never `t_follow`.** Following distance is unchanged by this commit,
and there is a test that asserts exactly that.

**One deliberate divergence from upstream.** `_pursuit_s` is initialised in `__init__` as well as in
`reset()`. Upstream carries it only in `reset()` because upstream's `__init__` calls `reset()`; ours
does not. Without the extra initialiser the first frame that reaches the decay branch raises
`AttributeError`. Pinned by `test_pursuit_tail_state_exists_before_the_first_update` so a future
re-sync cannot quietly drop it.

**Evidence discipline.** The figure in the code comment — `+0.26 m/s²` early in the pickup, `0.15 s`
over the ramp, upstream route `0x3b` t=390–405, a truck that drove off — is **upstream's replay
measurement on upstream's tree.** It is not ours. We have no route in the cache that reproduces it.
On this tree the tail is supported by unit tests and by the mechanism argument above, nothing more.

**Do NOT read this as a fix for the 24d padding complaint.** Item 39.4 found those padding samples
are `src == cruise`, not a lead-departure recovery. The two are adjacent in subject matter and
unconnected in evidence. Recorded as a lead only.

### Half B — migrating a renamed PERSISTENT BOOL (`38d5635a9`)

Item 40 found that renaming the Params key `BlotV2` → `BlotV3` silently dropped the stored value,
and route `0000023f` therefore drove with the supervisor **off**. This commit adds the migration that
should have shipped with the rename.

`migrate_starpilot_bool_param_renames(params, params_cache)` in `system/manager/manager.py`, table
`LEGACY_STARPILOT_BOOL_RENAMES = {"BlotV2": "BlotV3"}`, guarded by its own one-shot flag
`/data/starpilot_bool_rename_v1`, called from `manager_init` **ahead of the `clear_all()` calls**.

Three design points worth keeping:

1. **It needs its own flag.** The existing `migrate_starpilot_param_renames` looks like the right
   home, but its flag (`starpilot_param_rename_v1`) is already written on every device that went
   through the FrogPilot→StarPilot rename. An entry added to that table would **never run**. Any
   future rename migration needs a fresh flag for the same reason.
2. **It reads the old key as raw bytes off disk** (`_read_raw_param_bytes` → `get_param_path`), not
   through the schema. So **no `common/params_keys.h` change, and therefore no aarch64 artifact
   rebuild.** The orphaned key is unreadable through the normal API precisely because the schema no
   longer knows it.
3. **An explicit value on the new key wins**, in either store. For a toggle that gates longitudinal
   control, turning something **on** unasked is the worse error.

**The key finding, and why this is a guard rather than a repair.** `clear_all()` **deletes params
keys the schema does not know** (see the comment near `manager.py:1132`). `BlotV2` was therefore
already gone from disk after the *first* boot of the renamed build. **This migration cannot repair
route `0000023f`.** A rename has exactly **one** boot in which the old value is still recoverable,
which means the migration entry has to ship in the **same release** as the rename — added afterwards
it is always too late. That constraint is written into the comment above the table so the next
person renaming a toggle hits it before repeating the mistake.

### Verification

| | |
|---|---|
| `test_blotv3.py` (8 new tests) | 26 passed |
| negative control, pursuit tail | **2 failed / 24 passed** on revert |
| `test_manager.py` (7 new tests) | 42 passed, 1 skipped |
| negative control, migration | **2 failed / 40 passed** on revert |
| planner + blotv3 | 527 passed |
| manager + planner + blotv3 | **569 passed, 1 skipped** |

The negative controls are partial by design: of the 8 pursuit-tail tests only two assert the tail
*holds*; the rest assert it **ends** (on its own, when the lead stops pulling, on lead loss, on
reset) and so pass under revert. A test that passes with the feature removed is not evidence for the
feature — recorded here so the count is not mistaken for a weak control.

`-W ignore::DeprecationWarning` is required or `test_longitudinal_planner.py` fails **collection**
under NumPy 2.5 and the run silently shrinks. `manager.py` carries 5 pre-existing ruff findings
(ISC002, E501, PIE810); none are on these lines and none were touched.

Static and unit-test evidence only. **No replay and no road validation of either change.**

## 42. Two bookmarked drives (24f, 251): the semi-hard brake is the −3.5 rail, and the driver's marks land on it — 2026-09-21

Routes `0000024f--8c147bae2e` (19 segments, 1082 s) and `00000251--0f743e380e` (15 segments, 888 s),
both fetched on 2026-09-21. **First drives in this project with usable driver bookmarks.**

### Configuration (read from `initData`, per the D-053 lesson)

Both routes: `gitBranch = ns-bosch-radar-testing`, commit `350570847`, `dirty = False`,
**`BlotV3 = 1`** (supervisor ON, unlike 23f), `LongitudinalPersonality = 1` (Standard),
`StandardFollow = 1.6`, `StandardFollowHigh = 1.2`, `CustomPersonalities = 0`.
**Neither route contains the pursuit tail** (`f7a85a35a`, committed after these drives).

### The bookmarks are good instruments

`userBookmark` presses: 24f at 2:53.24, 4:37.36, 6:09.52, 7:34.11, 9:57.02, 10:25.57; 251 at
3:57.13, 6:07.46, 8:27.71. **Every mark follows its braking episode by 1–8 s**, against ~26 s on 24d.
Search a window *backwards* from the mark, not at it, but the lag is now small enough that
attribution is unambiguous.

### The marks land on rail-pinned episodes

Hard-brake episodes = `longActive`, `aTarget < −1.0`, held ≥ 0.2 s. "Rail" = `aTarget <= −3.40`.

| route | episodes | rail-pinned | rail rate |
|---|---|---|---|
| `0000024f` | 14 | 3 | 21% |
| `00000251` | 4 | 1 | 25% |
| `0000024d` (item 39.1) | 23 | 10 | 43% |

Mapping marks to episodes:

| mark | episode | duration | `aTarget` min | time at rail |
|---|---|---|---|---|
| 24f 2:53.24 | 2:49.37 | 2.3 s | **−3.47** | 0.30 s |
| 24f 4:37.36 | 4:31.57 | 3.1 s | **−3.45** | 0.90 s |
| 24f 6:09.52 | 6:01.88 | 6.5 s | **−3.47** | 0.45 s |
| 24f 7:34.11 | 7:28.33 | 1.6 s | −2.09 | — |
| 24f 9:57.02 | 9:54.54 | 1.9 s | −2.46 | — |
| 24f 10:25.57 | 10:25.35 | 0.4 s | −1.08 | — |
| 251 3:57.13 | 3:55.50 | 3.3 s | **−3.47** | 0.85 s |
| 251 6:07.46 | 6:05.01 | 1.0 s | −3.20 | — |
| 251 8:27.71 | 8:22.51 | 0.4 s | −1.29 | — |

**All four rail-pinned episodes across both routes are bookmarked**, and 24f's three rail events are
its only three. The unbookmarked 24f 12:11.29 touched the rail for one frame (0.05 s). So the
sensation the driver reports **is the rail**, and the driver's discrimination is sharper than the
statistics: the four worst episodes by this metric are exactly the four they marked.

### The mechanism is NOT 24d's estimator divergence

Traced 24f 2:49.37 frame by frame (centred ±0.5 s difference on `d1`):

| t−onset | `vEgo` | `d1` | `y1` | centred slope | `leadOne.vRel` | U11 `vRel` | `aTarget` |
|---|---|---|---|---|---|---|---|
| −2.78 | 17.57 | 47.3 | −0.68 | −0.49 | −0.06 | −0.06 | +0.46 |
| −2.33 | 17.85 | 46.8 | −0.62 | **−2.32** | −0.64 | −0.64 | +0.26 |
| −2.03 | 18.03 | 46.0 | −0.57 | −2.51 | −1.23 | −1.23 | −0.41 |
| −1.43 | 17.92 | 44.0 | −0.43 | −2.29 | −2.12 | −2.12 | −0.50 |
| −0.68 | 17.14 | 42.8 | −0.23 | **−3.04** | −1.69 | −1.69 | −0.64 |
| −0.23 | 16.63 | 40.8 | −0.14 | **−4.68** | −2.95 | −2.95 | −0.81 |
| −0.08 | 16.46 | 39.4 | −0.14 | −5.22 | −4.00 | −4.00 | −0.94 |
| +0.52 | 15.21 | 37.3 | −0.11 | −2.90 | −3.59 | −3.59 | **−3.47** |

Three things, in order of confidence:

1. **`leadOne.vRel` and the raw U11 `vRel` are identical to two decimals through the whole episode.**
   There is **no estimator divergence on this route.** 39.1's finding — ours converging ~1.6 s ahead
   of raw U11 — does **not** reproduce here, so it is not a general property of the Bosch-A path. Do
   not cite 39.1's convergence advantage as a fleet-wide claim; on 24f the two are the same signal.
2. **The radar under-read still happens, but it is half the size of 24d's.** Blind window ≈ **1.3 s**
   (−2.8 to −1.5) with a peak under-read of ≈ **1.7 m/s**, and a second divergence at −0.7 to −0.2
   reaching ≈ 2.4 m/s. 24d's corrected figures were ~0.8 s and ~4.3 m/s. So latency is present and
   smaller, yet the outcome (rail) is the same — **latency alone does not explain the rail.**
3. **The planner under-reacts to data it already has, then catches up all at once.** At t = −2.03 the
   measured slope is −2.51 and `vRel` is already −1.23, and `aTarget` is only −0.41. It then moves
   −0.94 → **−3.47 in 0.6 s**. The lead is a clean, continuously-tracked, dead-centre target the
   whole time (`tid1 = 48` unbroken, `mProb1 = 0.999`, `y1` −0.8 → 0.0, `d1` 47 → 36 m). This is not
   a dropout, not a cut-in, and not a track change.

**Consequence: the tuning target moves.** 24d pointed at sensor latency. 24f points at the planner's
*response shape* — it sits on a developing closure, then demands everything in one ramp and clips the
limit. That is a jerk-cost / ramp-rate question, and it is the first evidence on this branch that
argues for touching one.

### Not established, and deliberately not acted on

- **No cut-in has been isolated yet.** The driver reports the brake sometimes fires when being cut
  off, inconsistently. All four rail episodes examined here are continuous-track cases, so the
  cut-in population is still unsampled. It is a different code path (track initialisation, not
  `vRel` convergence) and needs its own pass.
- **Why `aTarget` lags its own `vRel` input is not explained.** Item 39.1 assumed late detection was
  sufficient; on 24f it is not. Candidates not yet separated: the jerk cost, `danger`/`accJerk`
  weighting, or a `t_follow` interaction. **Do not tune until the term is identified.**
- **Driving personality and safety-gap bias were deliberately left unchanged** for these drives, so
  24f/251 remain comparable with the other 16 routes. Both act on base `t_follow` and would confound
  the BLoTv3 pads. Changing either would mask this finding rather than fix it.
- **No claim that BLoTv3 caused or worsened this.** `BlotV3 = 1` on both routes, but there is no
  matched-configuration comparison, and the supervisor only touches `jerk_scale` and `t_follow`.

Route data cited by ID only. Offline log analysis; no replay and no road validation of any change.

## 43. The −0.50 clamp ahead of the rail: `DecelerationProfile` is ECO on both bookmarked routes

Item 42 ended with "why `aTarget` lags its own `vRel` input is not explained" and told the next
pass to find which term moves. It is not a jerk weight. The jerk columns are **constant** across
every rail episode on both routes: `accJerk = 250.00`, `spdJerk = 5.50`, `dngJerk = 100.00`,
`danger = 0.75`, `tFollow = 1.45`. Nothing in the jerk/danger family moves as `aTarget` ramps.

What moves is nothing — because `aTarget` is **clamped**, and the clamp is a setting.

### The measurement

`minAcc` in the scan CSV is `starpilotPlan.minAcceleration`. On both routes, on every sampled
frame, it reads exactly **−0.50**. `starpilotPlan.minAcceleration` is
`starpilot_acceleration.min_accel`, which for a plain deceleration profile is
`get_profile_min_accel_floor(deceleration_profile)`
(`starpilot/controls/lib/starpilot_acceleration.py:122`). That returns:

- `A_CRUISE_MIN_ECO` = `A_CRUISE_MIN / 2` = **−0.5**   (`starpilot_acceleration.py:61`)
- `A_CRUISE_MIN` = **−1.0**                            (`longitudinal_planner.py:429`)
- `A_CRUISE_MIN_SPORT` = `A_CRUISE_MIN * 2` = −2.0

`DECELERATION_PROFILES` is `{"STANDARD": 0, "ECO": 1, "SPORT": 2}`
(`starpilot/common/accel_profile.py:15`). The stored param on **both** routes is
**`DecelerationProfile = 1`, i.e. ECO** — read from `init_by_seg[<first seg>]['params']`, not
guessed. So the observed −0.50 is `A_CRUISE_MIN_ECO` and matches the code exactly.

That value is fed straight in as the lower accel limit:

```
longitudinal_planner.py:2137-2141
    if self.mpc.mode == 'acc':
      accel_limits = [sm['starpilotPlan'].minAcceleration, sm['starpilotPlan'].maxAcceleration]
      ...
      accel_limits_turns[0] = max(get_vehicle_min_accel(self.CP, v_ego), accel_limits_turns[0])
    else:
      accel_limits = [ACCEL_MIN, ACCEL_MAX]
```

### `aTarget` sits on that number, including with a closing lead tracked

24f 6:01.88, sampled at 5 Hz, `dt` relative to onset. `d1` is lead range, `vRel1` closing rate:

| dt | vEgo | aTarget | src | d1 | vRel1 | minAcc |
|---|---|---|---|---|---|---|
| −1.35 | 24.17 | **−0.50** | lead1 | 78.6 | −4.50 | −0.50 |
| −1.15 | 24.19 | **−0.50** | lead1 | 75.9 | −3.97 | −0.50 |
| −0.95 | 24.19 | **−0.50** | lead1 | 61.7 | −5.41 | −0.50 |
| −0.75 | 24.20 | **−0.50** | lead1 | 60.5 | −5.58 | −0.50 |
| −0.55 | 24.15 | **−0.50** | lead1 | 58.2 | −6.20 | −0.50 |
| −0.35 | 24.09 | −0.55 | lead1 | 56.8 | −6.30 | −0.50 |
| +0.05 | 23.91 | −1.24 | lead1 | 54.3 | −6.33 | −0.50 |
| +0.65 | 23.14 | −2.09 | lead1 | 52.2 | −5.11 | −0.50 |

**`aTarget` holds at exactly −0.50 for 1.2 s while a tracked lead closes at 6.3 m/s.** That is not
a solver choosing to be gentle; −0.50 to two decimals, held flat, equal to the configured floor,
is a clamp. 24f 4:31.57 shows the same pin for 1.6 s (`src = cruise`, `aTarget` −0.50 for eight
consecutive sampled frames) before ramping to −3.45.

The other side is unchanged from item 42: once released, `planAmin` and `planA1s` go to **−3.50**
exactly and `aTarget` reaches −3.47 in 0.6 s.

### What this does and does not establish

**Established.** ECO is set on both routes. The floor it selects is −0.5 rather than STANDARD's
−1.0. `aTarget` measurably rests on that value for over a second at a time, in at least one case
with a continuously tracked lead closing at 6.3 m/s at 55–78 m. No jerk or danger term varies
across any rail episode on either route.

**NOT established — and one code comment argues against it.**
`starpilot_acceleration.py:63` says of the traffic floor: *"cruise-decel floor only; MPC lead
braking keeps full ACCEL_MIN authority."* If lead braking really keeps full authority, the ECO
floor should not bind while `src = lead1` — yet the table above is `src = lead1` at −0.50. Either
the comment does not hold for the ECO/STANDARD floors, or something else produces exactly −0.50.
**That is not resolved here, and it is the next thing to settle.** `aTarget` does later exceed
−0.50, so the clamp is not unconditional; the release path has not been traced.

**No causal claim that ECO produces the −3.5 slam.** The sequence (pinned at −0.50, then −3.47 in
0.6 s) is consistent with a suppressed early response forcing a late large one, but consistency is
not evidence. There is no matched-configuration comparison: every route in the set was driven on
ECO, so the profile is a constant across all 16 and cannot be attributed against itself.

### Why this matters for the settings question

Item 42 answered "should I change driving personality or safety gap bias?" with no, because both
scale `t_follow` and the complaint is brake *shape*. That answer stands — and `tFollow = 1.45`
constant through every episode confirms the gap was never the moving part.

`DecelerationProfile` is a different lever and was not considered: it does not touch `t_follow`,
it sets the braking authority floor directly. ECO → STANDARD doubles it (−0.5 → −1.0). **This is
the first setting on this branch with a measured mechanism behind it.** It is still not a
recommendation: the release path is untraced, the causal link is unproven, and changing it breaks
the one-configuration assumption that makes 24f/251 comparable with the other 14 routes. If it is
changed, it must be changed as a deliberate A/B with the profile recorded, not quietly.

Offline log analysis of two routes. No replay, no road validation, no change made.

## 44. The 251 6:06 semi-hard brake: a real but small lead brake-tap, answered 1 s late at full authority

User-identified event (not the cut-in earlier assumed): route `11c8fa231c0499ed/00000251--0f743e380e`,
route time 364.4-366.2 s (~6:04-6:06). Peak measured `aEgo` **-3.58 m/s2 at t=365.86**. Traced frame by
frame from the device's own log (`radarState` 20 Hz, `liveTracks` ~15 Hz, segment 6 rlog).

### The stimulus is real. It is not a phantom and not a tracker fabrication.

`liveTracks` carries exactly one point in the ego lane through the whole event (y = -0.3 to -0.4 m), and
that point's own range and Doppler agree with each other:

```
  t        dRel   yRel   vRel      (raw liveTracks, ego-lane point only)
  363.90   45.6   -0.4   +2.5   <- lead receding
  364.44   43.7   -0.4   -0.9   <- closing begins
  364.77   41.0   -0.4   -4.2   <- peak apparent closing
  365.11   40.0   -0.4   -3.4   <- minimum range 39.5 m (radarState)
  365.18   40.6   -0.4   -1.1   <- +0.6 m / +2.3 m/s step in one 66 ms frame (the one discontinuity)
  365.58   40.6   -0.3   -0.2   <- closing over
  366.59   43.4   +0.1   +3.5   <- receding again
```

Range fell 45.6 -> 40.0 m in 1.0 s with `vEgo` flat at 26.45 m/s, so the lead really lost about 5 m/s
and regained most of it: a brake tap. `tid1 = 57` throughout, `mProb1 = 1.00`, `radar1 = 1`, no track
change. **Minimum range was 39.5 m at 26.3 m/s = 1.50 s headway, against `tFollow = 1.45`.** The gap
closed to roughly the configured following distance and no further. There was no collision threat at
any point in this event.

Two caveats recorded, not resolved: the +0.6 m / +2.3 m/s step at 365.18 is not physical for a rigid
object, and the recovery limb implies about +4.8 m/s2 of lead acceleration, which is also not physical
for a car. Some of the recovery limb is filter, not vehicle. The descending limb is smooth and
coherent in both range and Doppler and is taken as real.

### Vision saw nothing.

`mlV` stayed 26.3-27.2 m/s and `mlA` stayed about +0.03 m/s2 for the entire event; `mlX` stayed 47-51 m
and never dipped. The model contributed nothing to this brake and, read literally, argued against it.
Consistent with the standing finding that vision is not closing-speed truth - but note the direction:
here vision's silence was the *correct* magnitude call and the radar's was the alarming one.

### The control response is late and then unlimited. That is the defect shape.

```
  t        aTarget  minAcc  planAmin  src      vRel1   d1
  364.41    -0.04   -0.50    -0.51    lead1    -0.28   43.67
  364.65    -0.50   -0.50    -1.72    lead1    -3.38   41.48   <- aTarget == minAcc exactly
  364.75    -0.50   -0.50    -2.25    lead1    -3.80   40.98   <- still exactly -0.50
  364.85    -0.50   -0.50    -3.35    lead1    -4.14   40.23   <- still exactly -0.50
  364.91    -0.65   -0.50    -3.50    lead1    -4.14   40.23   <- clamp released; minAcc unchanged
  365.15    -1.55   -0.50    -3.50    lead1    -3.41   39.54   <- minimum range
  365.50    -3.20   -0.50    -3.43    lead1    -0.38   40.23   <- aTarget minimum; closing already over
  365.60    -3.14   -0.50    -3.32    lead1    -0.17   40.17
  365.86    -2.58   -0.50    -2.95    cruise   +0.98   40.67   <- aEgo minimum -3.58; lead pulling away
```

Three facts, each read directly off the log:

1. **The ECO floor binds again, with `src = lead1`.** Five CSV rows (about 0.2 s, 2-3 distinct plan
   frames) sit at exactly -0.50 = `minAcc` = `A_CRUISE_MIN_ECO` while `planAmin` is already diving
   through -3.35. This is the second independent instance of the STATUS 43 signature, and the second
   one that contradicts the `starpilot_acceleration.py:63` comment ("MPC lead braking keeps full
   ACCEL_MIN authority"). The 24f 6:01 instance held 1.2 s; this one holds 0.2 s. Weaker, same shape.
2. **The clamp delays the onset without capping the peak.** `minAcc` never changes value, yet `aTarget`
   passes through it at 364.91 and continues to -3.20. So the floor is not an authority limit on this
   path - it is a 0.2 s dead band at the *start* of the response, i.e. exactly the interval in which a
   small early correction would have been sufficient. Late and then full-authority is the worst of the
   two behaviours.
3. **The hardest braking is applied after the stimulus has gone.** Closing is over by 365.58 and the
   lead is pulling away at +1.0 m/s by 365.86, which is where measured `aEgo` bottoms out at -3.58.
   The peak of the response trails the peak of the stimulus by about 1.0 s and trails the end of the
   stimulus by about 0.3-0.7 s. The range was already growing when the car braked hardest.

### What this changes and what it does not

Established: a real 5 m/s lead brake-tap that never took the gap below the configured following
distance produced a -3.58 m/s2 brake whose peak landed after the gap had reopened, with the ECO floor
holding the first 0.2 s of the response at exactly -0.50 while `planAmin` was already on the -3.50 rail.

NOT established, and specifically not to be tuned on: that removing or raising the ECO floor would
reduce the peak. It is plausible - an earlier, gentler response to a stimulus this small should not
need -3.5 - but the counterfactual has not been run. **That is a replay experiment, not an edit.**
`ACCEL_MIN = -3.5` as the rail source is still unverified, and the release path at 364.91 is still
untraced (`longitudinal_planner.py:2137-2141` versus `get_mpc_mode()` at :2448-2450).

Also noted for later, not part of this event: at 365.65-365.98 a third `liveTracks` point appears at
y = +9.2 to +10.4 m with a constant reported `vRel = -13.5 m/s` while its own `dRel` walks 40.6 -> 29.2 m
in 0.33 s, a range rate of about -34 m/s. Its Doppler contradicts its own range rate by roughly 20 m/s.
It is well outside the ego lane and did not drive this brake, but it is a parser-side inconsistency
worth a census pass.

Offline log analysis of one route, one event. No replay, no road validation, no change made.

## 45. The ECO decel floor is a one-sided leaky clamp on the planner OUTPUT, not on the MPC

Static code read of `selfdrive/controls/lib/longitudinal_planner.py` and
`selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py` on this tree. No replay, no road
validation, no change made. This resolves the release path left untraced in items 43 and 44.

**`ACCEL_MIN == -3.5` is confirmed** at `opendbc_repo/opendbc/car/interfaces.py:40`
(`ACCEL_MAX = 2.0` at :39). It is the rail `planAmin` sits on in both the 24f 6:01 and the
251 6:06 episodes.

**The ECO floor never reaches the solver.** `long_mpc.py:956` sets

    self.params[:,0] = ACCEL_MIN

unconditionally, before and outside the `if self.mode == 'acc'` branch. `set_accel_limits()`
(:919-923) stores its `min_a` in `self.cruise_min_a`, and `cruise_min_a` is read in exactly one
place, `:965`:

    v_lower = v_ego + (T_IDXS * self.cruise_min_a * 1.05)

which clips `v_cruise` to build the *cruise* obstacle. Upstream's own comment on `set_accel_limits`
says so: "TODO this sets a max accel limit, but the minimum limit is only for cruise decel /
needs refactor." So the MPC really does keep full `ACCEL_MIN` authority for lead braking, and
the claim in `starpilot/controls/lib/starpilot_acceleration.py:63` is **correct about the MPC**.
Items 43 and 44 called that comment contradicted. That was wrong, and this supersedes it.

**The clamp is on the published output instead.** The path is:

  1. `longitudinal_planner.py:2137-2139` - in `acc` mode, `accel_limits[0] = starpilotPlan.minAcceleration`
     (the ECO floor, -0.50), carried into `accel_limits_turns[0]` by `limit_accel_in_turns()`.
  2. `:2141` - `accel_limits_turns[0] = max(get_vehicle_min_accel(self.CP, v_ego), accel_limits_turns[0])`.
     For this car `get_vehicle_min_accel` falls through to `float(ACCEL_MIN)` at `:425`, so
     `max(-3.5, -0.50) = -0.50`. The floor survives.
  3. `:2605-2607` - `comfort_output_accel_min = accel_limits_turns[0]`, then `output_accel_min = comfort_output_accel_min`.
  4. `:3115` - `output_a_target = float(np.clip(output_a_target, output_accel_min, output_accel_max))`.

That `np.clip` is what emits exactly -0.50. It explains the exact equality `aTarget == minAcc` with
`src = lead1` while `planAmin` was already through -3.35: the MPC had solved for the harder number
and the planner truncated it on the way out.

**What releases it is `:2202`:**

    # clip limits, cannot init MPC outside of bounds
    accel_limits_turns[0] = min(accel_limits_turns[0], self.a_desired + 0.05)

`self.a_desired` is the planner's own trajectory state, interpolated from the MPC solution at
`:2526`, and it is **not** subject to the `:3115` clip. So `a_desired` follows the MPC down
freely while the published `aTarget` is pinned at -0.50; as soon as `a_desired + 0.05` falls
below -0.50 the bound follows `a_desired` down, and from then on the clip is inactive.

**So the ECO deceleration profile is a pure phase lag on lead braking, with no attenuation
afterwards.** The hold lasts however long `a_desired` needs to fall through the floor - about
0.2 s on 251 (2-3 plan frames), about 1.2 s on 24f - and once released the output tracks the
unclamped MPC solution all the way to the rail. It is late-then-unlimited by construction, not
by accident. This is the mechanism behind the shape measured in item 44: the -3.58 m/s2 peak
landed about 1.0 s after peak closing.

**What this does NOT establish.** That the clamp is the dominant cause of the late peak - the
MPC's own solution was already through -3.35 before the clamp released, so the solver was
asking for a hard number on its own and part of the phase error is upstream of `:3115`.
Whether removing the clamp reduces or merely re-times the peak is still a replay counterfactual,
not an edit, and it has not been run. `:2202`'s comment says its purpose is MPC initialisation,
so it is not obviously the right place to govern output authority either; that is a design
question for DECISIONS.md, not a tuning change.

## 46. The phase hypothesis is dead. The radar-vs-no-radar difference is brake ENTRY RATE, not lag and not peak magnitude

Item 44 proposed that the 251 6:06 brake felt wrong because it arrived ~1.0 s after peak
closing with the gap already reopening, and that radar brakes are systematically later than
vision-lead brakes. **Measured across the corpus, that is false.** The lag distributions are
indistinguishable.

Method: `$CLAUDE_JOB_DIR/tmp/phase.py`. Episode = `aEgo < -1.5` held > 0.15 s on engaged
frames with `vEgo > 5`. For each episode `t_a = argmin(aEgo)`; the closing signal is searched
over `[episode_start - 4.0, t_a]` using two independent measures, the published `vRel1` and the
geometric range rate `d(d1)/dt` differenced over 0.5 s. `lag = t_a - t_closing_peak`.

| | 242 NO RADAR | 251 RADAR | 24f RADAR |
|---|---|---|---|
| episodes / span | 25 / 1385 s | 3 / 448 s | 11 / 831 s |
| lag `vRel1` p50 | +0.70 s | +0.95 s | +0.70 s |
| lag range-rate p50 | +2.60 s | +1.05 s | +1.10 s |
| gap already opening at peak brake | 20% (5/25) | 33% (1/3) | 36% (4/11) |

The `vRel1` medians are the same to within one plan frame. On the range-rate measure the
**no-radar** route is the later one (+2.60 s vs +1.05/+1.10), the opposite of the hypothesis.
The opening-at-peak fractions do differ in the predicted direction (20% vs 33/36%), but with
n=5 and n=14 that is not a result. **Item 44's phase reading is withdrawn as a general claim.**
It still stands as a description of the single 251 6:06 episode, which item 46 does not revisit.

### What does separate: how fast the brake is applied

`$CLAUDE_JOB_DIR/tmp/onset.py`. Onset = walking back from the episode to the last frame with
`aEgo >= -0.5` (max 4 s). `entry_rate = (a_min - a_onset) / (t_a - t_onset)`.

| | n | entry rate p50 | mean | p25 | entry duration p50 |
|---|---|---|---|---|---|
| 242 NO RADAR | 25 | **-0.74** | -1.01 | -1.48 | **2.40 s** |
| 251 RADAR | 3 | -1.95 | -2.86 | -5.10 | 0.61 s |
| 24f RADAR | 11 | -1.45 | -1.44 | -2.33 | 1.30 s |
| pooled RADAR | 14 | **-1.54** | -1.74 | | |

Mann-Whitney U (normal approximation, tie-corrected) on pooled radar vs no-radar entry rate:
**U=99.0, z=-2.23, p=0.026.** The radar routes reach their peak deceleration about twice as
fast. The no-radar route spends a median 2.40 s getting from -0.5 to its peak; 24f takes
1.30 s and 251 takes 0.61 s.

This **reconciles** the contradiction in the checkpoint. Item 45's comparison established that
no-radar 242 is harsher on every magnitude and jerk metric (worst -4.57 vs -3.92, 1.08
episodes/min vs 0.40, 4.42% of frames below -1.5 vs 2.68%, |j| p99 7.72 vs 6.29). Both are
true at once: the no-radar brakes are **deeper but entered gradually**, the radar brakes are
**shallower but entered abruptly**. "Too reactive" is a statement about the entry, not the
peak, and the entry is where the two configurations actually differ.

The narrower 0.3 s onset-jerk window does NOT reach significance (no-radar p50 -0.63, radar
p50 -1.86, U=132.0, z=-1.26, **p=0.208**) — the difference lives in the whole ramp from -0.5 to
the peak, not in the first three frames. Do not quote the 0.3 s figure as the result.

### What this does NOT establish

- **No mechanism.** This is an output-side statistic on published `aEgo`. It does not say
  whether the fast entry comes from the radar lead's `vRel` driving a larger `x_obstacle` step,
  from `d1` discontinuities at track handover, from the ECO clamp release traced in item 45, or
  from BLoTv3's jerk-cost softening firing more often with a radar lead. Each is a separate
  measurement.
- **n=14 radar episodes, two routes, one of them contributing three.** 251's 0.61 s median is
  three episodes. The pooled p=0.026 rests mostly on 24f.
- **Confounds carried from item 45 are unchanged:** mean `vEgo` 18.0 (242) vs 21.1 (251) vs
  18.2 (24f), different traffic, 1385 s vs 448 s vs 831 s, and 242's `src` histogram is
  lead1-heavy where the radar routes are lead0-heavy. A no-radar drive on the same road at the
  same speed does not exist in the corpus.
- **No road evidence of any kind for a change.** Nothing here has been replayed and no code has
  been touched. The next step is a replay that reproduces the entry-rate difference on 251 with
  the radar path instrumented, not an edit.

## 47. The abrupt radar brake entry is generated in the PLANNER, not downstream, and it is not track handover

Item 46 established that radar brake episodes reach their peak roughly twice as fast as no-radar
ones, but measured only the published `aEgo` — an output-side statistic that cannot tell a planner
cause from an actuator/brake-response one. This item measures the plan itself.

**Method.** `entry_dump.py` (job-local, not committed). Same episode definition as item 46
(`aEgo < -1.5` held > 0.15 s, engaged, `vEgo > 5`). For each episode, the entry rate is computed
independently for `aEgo` and for `aTarget` (the planner's published target), each with its own
onset: peak = the signal's own minimum in the episode, onset = walking back from that peak while
the signal stays below -0.5, at most 4.0 s. **Note the definitional refinement:** item 46 walked
back from the episode start, this walks back from the peak. That shifts the no-radar `aEgo` p50
from -0.74 to -0.65 and the pooled radar p50 from -1.54 to -1.55; the separation is unchanged.

| | n | `aEgo` entry p50 | `aTarget` entry p50 | ratio |
|---|---|---|---|---|
| 242 NO RADAR | 25 | -0.65 | -0.41 | 0.63 |
| 251 RADAR | 3 | -1.66 | -1.79 | 1.08 |
| 24f RADAR | 11 | -1.40 | -1.04 | 0.75 |
| pooled RADAR | 14 | **-1.55** | **-1.25** | 0.81 |

Mann-Whitney U (tie-corrected normal approximation), pooled radar vs no-radar:
- `aEgo`: U=106.0, z=-2.02, **p=0.043**
- `aTarget`: U=85.0, z=-2.64, **p=0.008**

**The plan separates more strongly than the output.** `aTarget` already carries the full entry
asymmetry — about 0.8 of the `aEgo` rate on radar routes and 0.63 on the no-radar route, so the
ratio is if anything *lower* where the entry is slow. There is no configuration-dependent
downstream amplification: whatever makes a radar brake abrupt is present in the planner's own
commanded target before the actuator sees it. The planner investigation is pointed the right way.

**Track handover is ruled out as the driver.** Over each entry ramp the dump counted distinct
`tid1` values and the largest frame-to-frame step in `d1`, `vRel1`, `nat_d1`, `nat_vRel1`. Of the
14 radar episodes, 11 ran on a single track id with steps under 2 m and 2 m/s. The three that did
show handover are the three with the *slowest* entries: 24f t=99.01 and t=100.01 (4 ids, 28.50 m
`d1` step, entry -0.80 and -0.62) and 24f t=367.38 (5 ids, 8.62 m and 7.44 m/s steps, entry
-0.37). Every fast entry (-1.40 or steeper) occurred with `nTid=1`. A discontinuity at handover
does exist in the data and is worth its own item, but it is anti-correlated with abrupt entry.

**What this does NOT establish.** No mechanism inside the planner is identified — this narrows the
search to the planner and eliminates one of item 46's four candidates, nothing more. Two candidates
remain untested: radar `vRel` driving a larger `x_obstacle` step (`long_mpc.py:1087`) and the
BLoTv3 jerk-cost softening firing more often. The item-45 ECO clamp remains a phase-lag-only
effect and cannot attenuate, so it cannot be the cause of a *faster* entry. n is still 14 radar
episodes over two routes with 251 contributing three, the speed/traffic/duration/`src` confounds
of item 45 are unchanged, and there is no road evidence and no replay of any kind.

## 48. BLoTv3 is exonerated: neither supervisor dial is active on a fast brake entry. Only the x_obstacle path remains.

Item 47 narrowed the abrupt radar brake entry to the planner. Item 46 named two surviving
candidate causes inside it: the BLoTv3 supervisor softening its jerk cost more often, or radar
`vRel` driving a larger `x_obstacle` step. This item tests the supervisor and clears it.

**First, a correction to the method I had planned.** The checkpointed plan was to read the
supervisor's `t_follow_pad` as `desFollow - tFollow`. **That is wrong: `desFollow` is a distance in
metres, not a following time.** Across all three routes `desFollow - vEgo*tFollow` has p50 +3.1 to
+7.4 m and p10/p90 of roughly -9/+19 m, and `desFollow` is exactly 0.00 on every `src=cruise`
frame — it is the desired follow *gap*. Any figure of the form `desFollow - tFollow` is
meaningless; the first run of `pad_entry.py` produced such figures (pad "p50 41.55", U tests at
p=0.965 and p=0.176) and they are **withdrawn, not evidence of anything.**

**The pad is directly observable as `tFollow` itself**, whose base is 1.45 s on these routes.

| | engaged frames | `tFollow` = 1.45 | other values | entry ramps with `tFollow` > 1.45 |
|---|---|---|---|---|
| 242 NO RADAR | 17834 | 98.55% | 26 distinct values, 0.79–1.42, 1–5 frames each | **0 / 25** |
| 251 RADAR | 2721 | 100.00% | none | **0 / 3** |
| 24f RADAR | 9660 | 84.93% | 1.75 (14.93%), 1.25 (9 fr), 1.65 (1 fr), 0.00 (4 fr) | **1 / 11** |

The one hit is 24f t=449.08 (entry -2.69, pad +0.30). It is almost certainly **not** a supervisor
pad: 24f's 1.75 s frames form a single 1442-frame block with one intermediate frame at 1.65 in the
whole route, which is a step change in the gap setting, not a pad slewed at `ONSET_RATE_UP` = 0.8/s
(that would leave roughly six intermediate frames per transition). The scatter of sub-1.45 values
on 242 is below the base and so cannot be a pad at all. **On no route does the t_follow pad
participate in a brake entry.**

**The jerk cost is observable too, and it clears the supervisor on the other dial.** `accJerk` is
250 and `spdJerk` 5.50 for 98–99% of engaged frames; the softened values are `accJerk` 50 (0.2x) on
235 frames of 242 and 148 of 24f, 125 (0.5x) on 9 frames of 24f, and `spdJerk` 2.75 on those same 9.
**251 — the route with the fastest entries in the corpus — never softens at all.** Counting
softened frames inside each entry ramp:

- 242: 4 ramps, at t=137.72 / 138.22 / 138.82 / 139.71, entry rates **-0.33 / -0.28 / -0.24 / -0.20**
- 24f: 2 ramps, at t=99.01 / 100.01, entry rates **-0.80 / -0.62**
- 251: **none**

Those six are the six slowest entries in the whole 39-episode corpus. As with track handover in
item 47, softening is not merely absent from the fast entries — it is **anti-correlated** with
abruptness, and it fires slightly more often on the no-radar route (1.34% of frames vs 1.56% on 24f
and 0% on 251). BLoTv3 does not cause the fast entry on either of its dials.

**What this leaves.** One candidate from item 46 survives: radar `vRel1` driving a larger or
steppier `x_obstacle` (`long_mpc.py:1087`) than vision `vRel1` does. That is now the whole
remaining hypothesis and it has not been tested.

**What this does NOT establish.** The softened-frame counts are an association over 39 episodes,
not a causal test, and `jerk_scale` itself is not logged — this reads it through `accJerk`, which
also carries whatever else scales the MPC cost. `0.2x` does not correspond to any bound in
`blotv3.py` (`JERK_SCALE_MIN` is 0.3, which would give 75), so the mapping from `jerk_scale` to
`accJerk` is assumed, not verified. n is still 14 radar episodes over two routes with 251
contributing three; the speed/traffic/duration/`src` confounds of item 45 are unchanged; and there
is no road evidence and no replay of any kind.

## 49. The x_obstacle path is exonerated too: the radar obstacle is SMOOTHER, not steppier. All four candidates from item 46 are dead.

Item 48 left one candidate standing: radar `vRel1` driving a larger or steppier `x_obstacle`
(`long_mpc.py:1087`) than vision `vRel1` does. It does not. The radar obstacle is measurably
*less* jagged than the vision obstacle, in the opposite direction to the hypothesis.

**What the solver actually sees.** Traced from the source, not assumed. At horizon index 0 the
lead cost residual (`long_mpc.py:374`) reduces to

    e = (x_obstacle - x_ego) - desired_dist_comfort
      = dRel + v_lead^2/(2*CB) - ( v_ego^2/(2*CB) + t_follow*v_ego + STOP_DISTANCE )
      = dRel - desired_follow_distance(v_ego, v_lead, t_follow)
      = d1 - desFollow          <- both already logged, both in metres

with `COMFORT_BRAKE = 2.5` and `STOP_DISTANCE = 6.0` (`:155-156`), the obstacle built at `:951`
as `lead_xv_0[:,0] + get_stopped_equivalence_factor(lead_xv_0[:,1])`, and `process_lead` feeding
it `lead.dRel` and `lead.vLead`. So `d(x_obstacle)/d(v_lead) = v_lead/2.5` metres per m/s -- **10 m
of obstacle motion per 1 m/s of lead-speed error at 25 m/s.** That gain is real and is why the
hypothesis was worth testing: radar `vRel` is a Doppler measurement, vision `vRel` a regression.

The reconstruction was validated before use, the check item 48's premise did not get:
`desFollow - recon` p50 -0.74 m (242) / -0.50 (251) / -0.45 (24f), p10/p90 within about +-2 m of
gaps of 40-100 m. The small systematic offset is the `lead_v_filter` that `process_lead` applies
to `v_lead` and the logged `desFollow` does not see.

**Measurement** (`obst_entry.py`), over the same `aEgo` entry ramp `[k0,ka]` as items 47-48, per
episode: the slope of `e`, of its geometric part `d1`, and of its lead-speed part `v_lead^2/5`;
the slope of `vRel1` itself; and `jag`, the mean absolute second difference per frame, which
measures steppiness independently of slope.

|  | n | entry p50 | de/dt | d(d1)/dt | dV/dt | d(vRel)/dt | jag V | jag e |
|---|---|---|---|---|---|---|---|---|
| 242 NO RADAR | 25 | -0.65 | -1.51 | -2.44 | -7.75 | -0.38 | 1.743 | 2.400 |
| 251 RADAR | 3 | -1.66 | +0.79 | -3.07 | -12.84 | -0.31 | 1.387 | 1.548 |
| 24f RADAR | 11 | -1.40 | +0.33 | -2.91 | -1.24 | +0.57 | 0.582 | 1.195 |
| pooled RADAR | 14 | -1.55 | **+0.33** | -3.07 | -5.33 | +0.35 | **0.867** | 1.244 |

Mann-Whitney, pooled radar vs no-radar:

- `de/dt`  U=230.0 z=+1.61 **p=0.107** -- not significant, and the sign is backwards: the residual
  *grows* on radar entries while it shrinks on no-radar ones.
- `d(d1)/dt` U=203.0 z=+0.82 p=0.412. `dV/dt` U=212.0 z=+1.08 p=0.279. `d(vRel)/dt` U=230.0
  z=+1.61 p=0.107. None significant.
- `jag V` U=100.0 z=-2.20 **p=0.028** -- significant, **radar SMOOTHER** (0.867 vs 1.743).
- `jag e` U=124.0 z=-1.49 p=0.135, same direction.

**The horizon, not just frame 0.** The residual above is only the first horizon point; the solver
sees the whole trajectory that `extrapolate_lead` builds from `aLeadK` and `aLeadTau`. So the
extrapolation input was checked the same way: `jag aLeadK1` p50 0.0871 radar vs 0.1116 no-radar,
U=172.0 z=-0.09 **p=0.930**; `jag mProb1` p=0.128; `d(aLeadK)/dt` p=0.380. Nothing steppier on the
radar side there either.

**This is the third consecutive anti-correlation.** Track handover (item 47), jerk-cost softening
(item 48) and now obstacle steppiness all appear *less* on the fast radar entries than on the slow
no-radar ones. Three independent mechanisms have now been eliminated by the same shape of evidence.
All four candidates enumerated in item 46 are dead: the ECO clamp (45: phase-lag only, cannot
attenuate, so cannot produce a faster entry), track handover, the BLoTv3 dials, and the obstacle path.

**What this does NOT establish.**
- It does not explain the abruptness. Item 47's result stands -- the entry asymmetry is in
  `aTarget`, so it is generated inside the planner -- but no mechanism inside the planner has been
  found, and CSV-level inference has now exhausted its candidate list.
- `de/dt` at n=14 vs 25 is underpowered; p=0.107 on a backwards sign is "no evidence", not
  "evidence of no effect". The `jag` result is the one that carries a direction.
- The reconstruction is horizon index 0 only. A mechanism that reshapes the *interior* of the
  extrapolated trajectory without changing `aLeadK`, `aLeadTau`, `dRel` or `vLead` would be
  invisible to this measurement. Reading the MPC's own solved trajectory requires replay.
- Confounds unchanged from 43-48: different drives, traffic, and 251 contributing only 3 episodes.
- No road evidence and no replay. Nothing here was validated against a driven car with real radar
  targets, and no code has been changed.

**Next move is therefore replay instrumentation, not further CSV work.** The quantities that would
settle it -- `self.params[:,2]` per horizon point, the solved `a` trajectory, `lead_xv_0` -- are not
in the log and must be captured by re-running the planner over the route.

## 50. The lead-trajectory path switches mid-entry, but not differently on radar. Fourth consecutive null; CSV inference is closed.

Item 49 closed with a stated limitation: the obstacle residual was reconstructed at horizon index 0
only, so a mechanism reshaping the *interior* of the extrapolated trajectory would be invisible.
Reconstructing all 13 points is pure numpy -- everything from `radarState` to `params[:,2]`
(`process_lead` -> `extrapolate_lead` -> stopped equivalence -> cruise obstacle -> `np.min`) runs
without acados; only `run()` needs the solver. So the interior looked answerable from the existing
CSVs. It is not, and the reason is worth recording.

**`extrapolate_lead` is not always what builds the trajectory.** `build_model_lead_trajectory`
(`long_mpc.py:169`) replaces it with the model's `leadsV3` horizon, anchored to the raw h=0
measurement (`x_lead_traj = raw_d_rel + (model_x - model_x[0])`). It declines, returning `None`, when

```python
raw_lead_brake = max(0.0, -aLeadK)
closing_speed  = max(0.0, v_ego - raw_v_lead)
ttc            = raw_d_rel / max(closing_speed, 1e-3) if closing_speed > 0.1 else inf
if (raw_lead_brake > MODEL_LEAD_TRAJECTORY_MAX_LEAD_BRAKE or        # 0.5
    (closing_speed > 0.75 and ttc < MODEL_LEAD_TRAJECTORY_MAX_CLOSING_TTC)):   # 7.0
  return None
```

with the comment "keep the legacy raw-lead path so an optimistic model horizon cannot delay the first
braking response." That guard reads like it must fire on every brake entry. It does not.

**Measured: 14 of 39 entry ramps contain at least one model-path frame** -- 242 8/25, 251 1/3,
24f 5/11 -- and the per-ramp live fraction ranges 0.067 to 1.000, so on those ramps the obstacle
*switches definition mid-entry*. Whole-route model-path occupancy is 77-82% of engaged frames on all
three routes; the guard is a brake-entry exception, not the normal case.

**This figure is an upper bound, not a measurement.** The checks the CSV cannot model -- `model_x` /
`model_v` shape against `LEAD_T_IDXS_MODEL`, and the `isfinite` guards -- can only make the function
return `None` *more* often. A frame counted as legacy is therefore definitely legacy; a frame counted
as model-path is only *possibly* live. Tightening 14/39 requires `modelV2.leadsV3` from the rlog and
cannot be done from the dumped CSV. (Field note: `model_lead.prob` is the CSV's `mlProb`, not
`mProb1` -- the latter is the radar track's own modelProb.)

**But the switching does not separate radar from no-radar.** Per entry ramp, over the `aEgo` ramp
`[onset, peak]` as item 46's `rate()` defines it, pooled radar (251 + 24f, n=14) vs no-radar
(242, n=25), Mann-Whitney with radar first:

| metric | radar p50 | no-radar p50 | U | z | p |
|---|---|---|---|---|---|
| model-path live fraction | 0.0000 | 0.0000 | 190.0 | +0.51 | 0.609 |
| path flips per frame | 0.0000 | 0.0000 | 189.5 | +0.51 | 0.613 |

Flips-per-frame p50 is 0.0000 on all three routes (max 0.2143 on 242, 0.0909 on 251, 0.0769 on 24f).

**The tail is more decisive than the average.** Of the five fastest entries in the corpus, four are
100% legacy with zero flips:

| route | t | entry rate | live fraction | flips | onset -> peak |
|---|---|---|---|---|---|
| 251 | 365.86 | **-5.39** | 0.583 | 1/11 | legacy -> MODEL |
| 242 | 1405.25 | -2.71 | 0.000 | 0/26 | legacy -> legacy |
| 24f | 449.08 | -2.69 | 0.000 | 0/15 | legacy -> legacy |
| 24f | 595.74 | -2.51 | 0.000 | 0/21 | legacy -> legacy |
| 242 | 816.42 | -2.45 | 0.000 | 0/30 | legacy -> legacy |

The one fast entry that touches the model path, 251 t=365.86, **starts on the legacy path and flips to
MODEL at the peak**. The flip is downstream of the brake onset, not upstream of it, so it cannot have
caused an entry that was already underway.

**This is the fourth consecutive null, and the interior measurement was abandoned rather than run.**
Item 47 ruled out track handover (the three handover episodes are the three slowest). Item 48 ruled
out the BLoTv3 dials (jerk softening appears only in the six slowest ramps). Item 49 ruled out the
obstacle inputs, with `jag V` significant in the *opposite* direction (p=0.028, radar smoother). This
item rules out the path switch. The 13-point interior comparison was *not* run: 25 of the 39 ramps are
fully legacy and reconstructible, but that subset excludes 251 t=365.86 -- the exemplar the whole
investigation rests on -- and drops n to 8 vs 17, below the already-underpowered 14 vs 25. Measuring a
weaker question on a sample chosen to exclude the phenomenon is not evidence; it is the confirmation
trap in a new shape. The plan that specified this work
(`docs/superpowers/plans/2026-09-22-obstacle-trajectory-interior.md`, commit `1206eacbe`)
pre-registered that fork and it was taken as written.

**What this does NOT establish.**
- It does not explain the abruptness. Item 47's finding stands -- the asymmetry is in `aTarget`, so it
  is generated inside the planner -- and no mechanism has been found.
- 14/39 is an upper bound on model-path involvement, so "the path switches mid-entry" is established
  but its true frequency is not. Two of the four unmodelled guards could in principle void every
  model-path frame counted here.
- p=0.609 and p=0.613 at n=14 vs 25 are "no evidence of a difference", not "evidence of no
  difference". The tail argument above carries more weight than either p-value.
- The interior of the extrapolated trajectory is still unmeasured. This item declines to measure it
  on a biased subset; it does not show it would be null.
- Confounds unchanged from 43-49: different drives, traffic, and 251 contributing only 3 episodes.
- No road evidence, no replay, no code changed.

**The remaining suspect is the cost function, not the inputs.** Every input to the MPC lead cost has
now been checked at frame 0 and found equal or smoother on radar, while the *output* (`aTarget`)
separates more strongly than `aEgo` does (item 47). If clean inputs produce a steeper plan, the
mapping is what differs -- the lead cost at `long_mpc.py:374` and the danger term at `:389`, whose
`1/(v_ego + 10.)` normalisation and `danger_factor` weighting are the only remaining unexamined
transforms between the obstacle and the solved acceleration. That requires acados and a replay
harness; it cannot be read from a log. A fifth CSV probe would be the confirmation trap.

**Addendum to 50: the danger factor is a constant and is ruled out.** Before escalating to a replay
harness, the last logged input to the cost function was checked, because the danger slack constraint at
`long_mpc.py:389` scales the whole of `desired_dist_comfort` by `lead_danger_factor` and that product
is tens of metres at highway speed. The CSV's `danger` column is **identically 0.75 on all 30,156
engaged frames of all three routes** -- one distinct value, zero range on every entry ramp, radar and
no-radar Mann-Whitney U=175.0 z=+0.00 p=1.000 at onset, at peak and on range. It never moves, so it
cannot differentiate anything. `LEAD_DANGER_FACTOR` is doing no work here.

That leaves the lead cost at `:374`, `((x_obstacle - x_ego) - desired_dist_comfort) / (v_ego + 10.)`,
whose numerator is item 49's residual `e` (measured, radar not steeper) and whose denominator depends
only on `v_ego`. Both terms are therefore accounted for, which sharpens the open question rather than
widening it: if the inputs, the residual, the danger factor and the trajectory path are all equal or
smoother on radar while `aTarget` separates, the difference is in how the **solver** responds -- the
runtime cost weights set in `set_weights()`, the slack penalties, or conditioning -- not in any
quantity the log contains. Nothing short of running acados over both routes will separate those.

## 51. The follow policy's matched-regime exit is real in one replay window but absent from the corpus. Fifth null.

**Method (replay + offline, no code changed).** A whole-planner replay of 251 segments 5+6 (mode
`x0+src+pa+oat`) traced every line after which `update()`'s local `output_a_target` changed inside
t 365.5–366.3. While `lead_follow_policy._matched` is True, `_matched_brake_floor` lifts the MPC's
≈ −2.8 request to ≈ −0.10. `_transition_target` is then allowed, because −0.10 > −0.25 =
`FOLLOW_TRANSITION_MAX_BRAKE`, and it emits `prev + up_step` (0.07–0.13 per frame), replacing the MPC's
braking. At t 365.89 `_matched` flips False, and the replayed output steps −2.582 → −1.820. The
replay reproduces the matched-phase follow-policy output to 0.000. `action_t` was also checked:
it is a constant 0.550 on the tinygrad `acc` branch with no e2e blend, so it is exonerated.

The replay's negative control still fails: p99 0.159 against a gate of 0.05, and the residual is
100% trajectory (dtraj). So the +0.76 step at the flip is **replay-only**. In the log, the largest
`aTarget` step at that flip is 0.13.

**Corpus test** (`flip_entry.py`, calling the real `lfp._matched` on the logged lead1 fields and
`tFollow`). It counts True→False flips in [onset − 0.5 s, peak] of every aEgo entry ramp:

| route | engaged frames matched | entries | entries with a flip | any matched on ramp |
|---|---|---|---|---|
| 242 no radar | 7.1% | 25 | 0 | 1 |
| 251 radar | 34.4% | 3 | 1 (t 365.86) | 1 |
| 24f radar | 14.3% | 11 | 0 | 0 |

The premise holds: matched is 2–5× more frequent on radar. The mechanism does not follow from it.
Only 1 of 14 radar entries has a flip; incidence is 0/25 vs 1/14, MWU p=0.71. With that episode
removed, radar entry rate is p50 −1.44 against 242's −0.65, so the steepness difference survives
without any flip. The matched regime belongs to steady follow, not to brake entries. It explains at
most the single 251 t 365.86 event and not the "too reactive with radar" feel.

**Still open:** the dtraj control failure (the replay brakes harder than the car in 365.70–365.80,
choosing `cruise` where the car chose `lead1`). It points at solver-side terms — `set_weights()`,
slack penalties, constraints — as item 50 concluded. Replay evidence only; nothing here is
road-validated.

## 52. The replay control failure is mostly a harness gap: BLoTv3 was on in the car, off in the replay

**Finding (replay, 251 segs 5+6, mode `x0+src+pa+oat`).** `LongitudinalPlanner._blotv3_active()`
(`longitudinal_planner.py:583`) reads `Params().get_bool("BlotV3")`. The docker replay has an empty
param store, so it returned False and `_blotv3_policy` was None, meaning jerk_scale 1.0 and no BLoTv3
t_follow. `initData` shows `BlotV3 = 1` on **all three** comparison routes (242, 24f, 251), so the
car ran BLoTv3 every time. Forcing it on in the harness (`BLOT=1`, which sets
`planner._blotv3_active = lambda: True`) gives:

| mode | p50 | p90 | p99 | max |
|---|---|---|---|---|
| before (BLoTv3 off) | 0.00094 | 0.0308 | 0.1587 | 0.1725 |
| BLOT=1 | 0.00024 | 0.0136 | 0.1063 | 0.1557 |

During 365.0–365.9 the replay's jerk_scale runs 0.900 down to 0.825, which lowers acceleration_jerk.
The gate (p99 < 0.05) **still FAILS**. The new worst frame is 364.50 (replay −0.077, logged −0.233),
in a different place from before. The 0.10629 p99 is also the floor that several weight sweeps below
hit, so it is probably a separate residual.

**Sensitivity tests that led here** (all replay-only, harness env overrides on `set_weights`):
- `uncertainty` is unlogged, from `uncert_slow`, and runs 0.484–0.514 in the window. It is **not the cause**. In-band
  values 0.50/0.52 give p99 0.159/0.157, and forcing it out of the rescale band (0.44 or 0.60) makes
  p99 **worse**, at 0.177.
- `lead_dist` = 20 gives p99 0.160, and `panic_bypass` forced False gives 0.1587. Neither is the cause.
- `speed_jerk` ×2/×3/×5 gives p99 0.135/0.106/0.106. `acceleration_jerk` ×0.5/×0.33 gives 0.106, and ×3 gives 0.180,
  but every one of these raises p50 by 2–6×. The car behaved as if acceleration_jerk were lower
  than logged, and BLoTv3's jerk_scale is exactly that term.
- An earlier batch of these runs was a silent no-op. zsh does not word-split an unquoted `$1`, so
  `-e UNC_FORCE=0.44` reached docker as one argument and set an env var named ` UNC_FORCE`. Only
  the `${=1}` reruns are counted above.

**Consequence.** Every replay-based measurement in items 46–51 ran with BLoTv3 off. The
live-log and CSV corpus statistics are unaffected, including the matched-flip corpus count in 51.
Replay-derived claims should be re-checked under `BLOT=1`, especially STATUS 51's +0.76 m/s² replay-only step at 365.89.
This does **not** confound the 242 vs radar comparison, because BLoTv3 was on for all three.

Replay evidence only; nothing here is road-validated. No planner code was changed.

## 53. The replay now nearly reproduces the car: the 364.50 miss was stale radar input, not BLoTv3

**Method (replay only, no code changed).** Same harness and window as item 52 (251 segments 5+6,
mode `x0+src+pa+oat`, `BLOT=1`).

1. **`desFollow` cannot check the BLoTv3 pad.** It is `int(desired_follow_distance(v_ego, vLead,
   self.t_follow))` from `starpilot_following.py:123`, in metres, built from StarPilot's own
   `t_follow` before BLoTv3 adds its pad. Neither `tFollow` nor `desFollow` records the pad.
2. **BLoTv3 timing is not the 364.50 cause.** Harness overrides changed each BLoTv3 output on its own:
   jerk_scale lag of 1 and 3 frames, offsets of ±0.1, pad ×0 and ×2, and jerk_scale forced to 1.
   None moved 364.50: the replay stayed at −0.076 to −0.082 against −0.233 logged.
3. **The cause is input alignment.** At 364.50 the car's `leadTrajectoryX0[0]` is 42.67 m. That is
   the replay's value one frame later, at 364.55. The replay itself had 43.23 m. The frames either
   side match to 0.00, so the car's planner had already drained the next `radarState`.
   - The harness now accepts `LPCUT=1`, which gives each modelV2 frame every message logged before
     the car's own `longitudinalPlan` for that frame. This emulates the SubMaster drain at the
     observed cut-off.

| run | p50 | p90 | p99 | max | worst frame |
|---|---|---|---|---|---|
| BLoTv3 off (item 51) | 0.00094 | – | 0.159 | – | – |
| `BLOT=1` (item 52) | 0.00024 | 0.0136 | 0.106 | 0.156 | 364.50 |
| `BLOT=1 LPCUT=1` | 0.00028 | 0.0038 | **0.059** | **0.060** | 366.45 |
| `LPCUT=1`, BLoTv3 off | 0.00097 | 0.0302 | 0.159 | 0.173 | 366.00 |

- The MPC source mismatch is now 0 of 141 frames. The item 51 open point ("the replay chose
  `cruise` where the car chose `lead1`, 365.70–365.80") is closed: it was the same stale input.
- **Still failing:** the gate is p99 < 0.05, and the remaining error is 366.20–366.60. The replay
  recovers too fast, by up to +0.060, during cruise, while BLoTv3's pursuit tail holds jerk_scale at 0.30.
  - The error depends on the unlogged BLoTv3 state. JS_OFF=+0.1 gives p99 0.0502, max 0.061, and moves
    the worst frame to 366.05. JS_OFF=+0.3 makes it worse (0.113).
  - Without BLoTv3 state in cereal, this is as close as the replay gets.
4. **The 365.89 step from item 51 re-checked.** With inputs aligned it reproduces to −0.003. It is
   the follow policy's output diverging from the planner's internal `a_desired`, which drops
   −2.86 → −1.82. The logged `aTarget` moved only 0.13, so item 51's corpus conclusion stands.

**Consequence.** Items 46–51 used a replay with BLoTv3 off and stale inputs. Their log-only and corpus
conclusions are unaffected. Replay-derived numbers from those items should be re-derived with
`BLOT=1 LPCUT=1` before anyone relies on them.

**No mechanism that separates radar from no-radar has been found.** No code change is proposed.
The next test the harness can now support: replay a 251/24f brake entry with the radar lead replaced
by the vision lead, keeping the planner fixed, and check whether the entry rate falls to 242's
level. If it does, the cause is in the input; if not, it is in the planner.
Replay evidence only; nothing here is road-validated.

## 54. Swapping the radar lead for the vision lead moves the 251 brake entry by about one frame, not its shape

**Method (replay only, no code changed).** Harness env `VISLEAD` rewrites every `radarState` fed to
the planner:
- `VISLEAD=1` replaces leadOne and leadTwo with radard's own vision-only lead, as
  `get_RadarState_from_vision` builds it (radard.py:663): prob > 0.35, dRel = x − 1.52, the
  model-relative vRel, the 0.8/0.2 aLeadK blend, and radar=False.
- `VISLEAD=2` keeps the radar flags, to separate the planner's radar-only branches from the value
  change.

The planner is unchanged. The run uses 251 segments 5+6 with `BLOT=1 LPCUT=1` and the one-step x0
anchor, so every frame starts from the car's real state. This is the per-frame command the
planner would have issued, not a free-running trajectory.

| t | logged | radar (base) | vision (1) |
|---|---|---|---|
| 364.50 | −0.233 | −0.236 | −0.062 |
| 365.00 | −1.006 | −1.006 | −0.746 |
| 365.20 | −2.314 | −2.314 | −1.852 |
| 365.50 | −3.198 | −3.198 | −3.078 |
| 366.00 | −1.393 | −1.393 | −1.710 |
| 366.30 | −0.458 | −0.409 | −0.714 |

- **Onset:** the radar lead starts braking about 0.1 s earlier. It crosses −1.0 and −2.0 about
  0.06 s (one frame) before the vision lead does.
- **Peak and slope:** the peak is the same (−3.20 against −3.14), and so is the slope. On the release
  the vision lead brakes harder, not softer.
- **Radar-only planner branches:** `VISLEAD=2` matches `VISLEAD=1` to within 0.003 except at one frame
  (366.30), so the radar-only branches play almost no part here.

**Reading.** In this entry the radar input advances the braking by about one frame; it does not make
it harsher. That does not explain a "too reactive" feel. The limits are that this is one entry, a
per-frame test rather than a free run, and replay only. The 11 entries on route 24f are the next
place to test.

## 55. On route 24f, the vision lead brakes as deep as the radar lead and often more steeply

This repeats the item 54 test on all 11 of 24f's brake entries. The harness and settings are
unchanged: `BLOT=1 LPCUT=1`, mode `x0+src+pa+oat`, and a vision run with `VISLEAD=1`. The route
was split into seven groups of 2–3 segments, and each group was warmed about 10 s before its
first entry.

**The harness reproduces the car on 24f.** Six of the seven groups pass the negative-control gate
(p99 below 0.05):

| group | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| p99 | 0.016 | 0.002 | 0.006 | 0.005 | 0.001 | 0.032 | 0.001 |

Group A has a single frame at 0.59, during warm-up. On every entry, the radar (base) metrics match
the logged ones to 0.03.

The table covers the window [peak − 4 s, peak + 1 s]:

- **min:** the lowest aTarget in the window.
- **t−1, t−2:** the first times aTarget reaches −1 and −2.
- **slope:** the steepest aTarget change over 0.25 s, in m/s³.

| peak | radar min | vision min | radar t−1 / t−2 | vision t−1 / t−2 | radar slope | vision slope |
|---|---|---|---|---|---|---|
| 99.0 | −1.57 | −1.57 | 97.96 / – | 97.96 / – | −0.65 | −0.65 |
| 100.0 | −1.59 | −1.59 | 97.96 / – | 97.96 / – | −0.65 | −0.65 |
| 151.2 | −0.91 | −0.91 | – | – | −4.70 | −4.59 |
| 170.2 | −3.47 | −3.45 | 169.31 / 169.56 | 168.16 / 169.36 | −4.54 | −5.13 |
| 174.6 | −2.47 | −2.50 | 170.62 / 170.62 | 170.62 / 170.62 | −1.66 | −3.53 |
| 272.7 | −3.45 | −3.50 | 271.52 / 272.07 | 270.72 / 272.02 | −6.53 | −7.47 |
| 367.4 | −3.47 | −3.45 | 363.42 / 363.42 | 363.42 / 363.42 | −3.89 | −4.12 |
| 449.1 | −2.09 | −2.58 | 448.33 / 448.78 | 448.13 / 448.33 | −2.86 | −5.12 |
| 595.7 | −2.47 | −2.42 | 594.48 / 595.03 | 594.43 / 594.83 | −2.09 | −5.72 |
| 699.4 | −1.25 | −1.20 | 698.74 / – | 698.64 / – | −0.67 | −3.62 |
| 731.9 | −3.46 | −3.50 | 731.24 / 731.64 | 730.44 / 731.39 | −6.89 | −5.94 |

- **Depth:** the depth is the same (median difference 0.00). Four entries bottom out near −3.5
  either way, which is the brake limit, so the lead source does not set how deep they go.
- **Timing:** the vision lead reaches −1 and −2 at the same time or earlier. For −2 its median
  lead is 0.20 s, and at 170.2 it reaches −1 1.15 s earlier. On 251 the radar lead was about
  one frame earlier.
- **Steepness:** the vision lead is steeper in 7 of the 11 entries, gentler in 1 (731.9), and
  equal in 3. The median radar − vision slope is +0.60 m/s³.

**Reading (replay only).** Across 12 entries on two radar routes, 251 and 24f, the radar lead
never makes the planner brake harder, earlier or more steeply than the vision lead would have on
the same drive. That rules out one explanation: the lead measurement that radar supplies is not what
makes these entries abrupt. On 24f the vision lead is the more reactive of the two.

This matters for the "too reactive" symptom when compared with 242 (no radar; aTarget entry-rate
p50 −0.41, against −1.04 on 24f). That gap is not caused by the planner reacting to a radar
lead in place of a vision one. The likely difference is the situations each route contains:
closing speed, cut-ins and headway at onset. It could also come from something that differs
between the drives but not the lead source, such as personality, the BLoTv3 pad or matched-follow
exits.

Limits:
- The test is per-frame, anchored to x0, so the car's actual response is not simulated.
- The vision lead uses radard's vision-only estimate, not a real no-radar drive.
- The evidence is replay only.

**Next.** Match entries between 242 and the radar routes by their situation at onset (vEgo,
closing speed, headway, whether a lead was newly acquired), then compare the entry rates within
matched pairs. Do not propose a planner fix until a matched comparison shows a gap that remains.

## 56. 242 and the radar routes were driven with the same settings; the current code reproduces 242 exactly, and the gap comes from the situations

Three tests followed item 55. All are replay or offline.

**1. Matching entries by their situation at onset.** Script: `match_entries.py` in the harness
directory.

Each aTarget brake entry is described at onset by:
- vEgo;
- closing speed from the 1 s range slope;
- headway (d1 / vEgo);
- whether the lead is new (hasLead false, or a d1 jump of more than 4 m, within the previous 2 s).

Nearest-neighbour matching found only 4 pairs within distance 1 going from 242 to radar, and 6 of
14 going from radar to 242. In both directions the radar entry is steeper: a median difference of
−0.29 (4 of 4 pairs) and −0.80.

Before matching, the two sets differ a lot:
- 242 has 8 new-lead entries out of 25; its far vision acquisitions at headway above 4 s are
  gentle, with rates from −0.14 to −0.27. The radar routes have 1 out of 14.
- Among existing-lead entries, the closing speed at onset has a median of 1.29 m/s on 242 and
  2.89 m/s on the radar routes.

The existing-lead entry-rate p50 is −0.49 on 242 and −1.25 on the radar routes. The overall
−0.41 that STATUS used to quote mixes in the gentle new-lead entries.

**2. Software and settings.** The routes differ only in software:

| | 242 | 251 and 24f |
|---|---|---|
| commit | 4d5ba0b | 3505708 |
| BoschARadar | 0 | 1 |

`BlotV3`, `LongitudinalPersonality`, `ExperimentalMode` and the personality profiles are the same.
Two planner changes landed between those commits:
- the far-lead brake limit was removed (1434176b3). It only acted on leads with `radar=True`, so
  it was inert on 242;
- BLoTv3 now reads the MPC target instead of the arbitrated output (552798ab / 084a9d56).

The route 242 entries were replayed on the current code (which includes 3505708) with
`BLOT=1 LPCUT=1`, in seven groups H–N. Six of the seven pass p99 < 0.05. Group M has an excursion
of about 1.0 and group K a p99 of 0.064. Across 11 existing-lead entries, the median difference
between logged and replayed min, slope, rate, t−1 and t−2 is 0.00. Only 1200.5 differs, by −0.24
on min, and it lies inside the group M excursion. **The code change between the drives does not
explain why 242 is gentler.**

**3. Jitter during steady following.** Frames with hasLead, vEgo > 8, |vRel| < 1 and
|aTarget| < 0.8:

| | 242 | 251 | 24f |
|---|---|---|---|
| minutes | 6.8 | 1.3 | 4.0 |
| aTarget jerk p50 / p90 / p99 | 0.07 / 0.24 / 1.01 | 0.03 / 0.19 / 0.61 | 0.04 / 0.31 / 1.81 |
| slope reversals per minute | 43.8 | 26.7 | 41.8 |
| \|ΔvRel\| per frame, p50 | 0.126 | 0.016 | 0.016 |

The radar vRel is about eight times cleaner, and steady following is no jumpier with radar. The
exception is the p99 tail on 24f.

**Reading (replay only).** Put together:
- identical settings;
- the current code reproducing 242 (this item);
- the vision-lead counterfactual not softening the radar entries (items 54 and 55);
- steady following no noisier.

These rule out a planner or radar-input mechanism as the cause of the gap in entry rates. The
radar drives contain harder situations at onset: higher closing speeds and fewer gentle far
acquisitions. When the situations are matched, the pairs that remain still lean steeper on
radar. But n is 4 to 6, and 242's closing speeds come from vision range, which understates
closing at distance (see memory "vision isn't closing-speed truth"). So that residual cannot yet
be separated from measurement bias.

**No fix is proposed.** No change here has evidence that it would reduce a real over-reaction
without also blunting correct braking.

**Next.** What would settle it is road data with situations the analysis can compare: a radar
drive and a no-radar drive over the same road and in similar traffic. Alternatively, the driver
could timestamp the moments that felt too reactive (bookmarks), so the analysis starts from the
felt events rather than from every brake entry.

**Correction to "Next" (2026-09-22).** That paragraph is wrong. 24f and 251 already carry driver
bookmarks, analysed in item 42: every rail-pinned (-3.5) brake on both routes is bookmarked and
nothing else is. The felt events are known; item 57 starts from them.

## 57. Removing the ECO output floor does not soften the bookmarked 24f brakes; it makes them earlier and sometimes harder

Replay only (harness `replay.py`, `BLOT=1 LPCUT=1`, new env `MINACC_FORCE` overriding the fed
`starpilotPlan.minAcceleration`), route 24f, the five bookmarked brakes that fall inside the
replayed groups (170.2, 272.7, 367.4, 449.1, 595.7; the ~625 mark is past the end of group F).
Baseline replays pass the gate (p99 0.0008-0.032). No repo code changed.

Times are seconds relative to the bookmarked peak; rate is the steepest 0.5 s drop of aTarget.

| event | floor | first < -0.3 | first < -1.5 | peak | rate |
|---|---|---|---|---|---|
| 170.2 | ECO -0.5 (as driven) | -2.89 | -0.74 | -3.47 | -4.17 |
| | -1.0 (STANDARD) | -2.89 | -0.74 | -3.47 | -4.17 |
| | -3.5 (none) | -2.89 | -0.99 | -3.50 | -4.92 |
| 272.7 | ECO | -4.38 | -0.78 | -3.45 | -4.25 |
| | STANDARD | -4.38 | -0.78 | -3.45 | -4.25 |
| | none | -4.38 | -0.93 | -3.50 | -4.59 |
| 367.4 | ECO | -4.98 | -4.98 | -3.47 | -2.46 |
| | none | -4.98 | -4.98 | -3.50 | -2.70 |
| 449.1 | ECO | -3.92 | -0.62 | -2.09 | -2.55 |
| | STANDARD | -3.92 | -0.62 | -2.09 | -1.93 |
| | none | -3.92 | -1.17 | **-3.50** | **-6.10** |
| 595.7 | ECO | -1.72 | -0.97 | -2.47 | -1.94 |
| | none | -1.72 | -1.17 | -2.52 | -2.50 |

**Reading.** Braking onset (< -0.3) is identical in every case: the ECO floor does not delay the
start of braking. Removing it moves the hard part 0.15-0.55 s earlier but leaves peak and slope
the same or steeper, and on 449.1 it turns a -2.09 brake into a -3.50 rail brake at -6.1 m/s3.
The STANDARD floor (-1.0) is indistinguishable from ECO except for 449.1, where it is gentler.
So the hold-then-rail shape of items 43/45 is the MPC's own solution arriving late and hard; the
output floor only trims its first ~0.2 s. **Relaxing or removing the ECO floor is not a fix** and
would make at least one bookmarked brake harsher (replay evidence).

**Next.** The lateness is upstream of the output clip. The candidate already on record is the
follow policy (`lead_follow_policy.apply()`, via `longitudinal_planner.py:3094`): while `_matched`
is true it replaces the MPC's braking with `prev + up_step` and a brake floor, then releases in one
frame (251 t=365.89: -2.58 -> -1.82). Next replay counterfactual: disable the matched floor and
transition target on the same five events, and see whether braking starts earlier and gentler.

## 58. The follow policy and BLoTv3 are not active in the bookmarked 24f brakes

Replay only, same five bookmarked 24f events and metrics as item 57. Two harness counterfactuals,
no repo code changed:

- `FP_OFF=1` disables `lead_follow_policy._matched_brake_floor`, `_transition_target` and
  `_steady_follow_deadband`. It does change the replay elsewhere: 12/24/4/0/82 frames in groups
  B-F, max 1.16 m/s2, all at t = 120-138, 226-245 and 509-591. So the switch works. **Inside every
  bookmarked window the output is bit-identical to baseline.** The policy is not engaged in these
  brakes. The 251 t=365.89 release step (item 3/LEAD f) is real but is not what the driver marked
  on 24f.
- BLoTv3 off (no `BLOT=1`): identical to baseline to within one 50 ms frame on all five events.

**Conclusion (replay).** The ECO floor (item 57), the matched-follow policy and BLoTv3 are all
ruled out for the bookmarked 24f brakes. The late-then-rail shape is the MPC's own solution to the
lead input it is given. What remains: the MPC's lead cost / `t_follow` / jerk weights against a
fast-closing lead, and whether the lead state fed to it (dRel, vLead, aLeadK) at the onset
understates the closing rate that the range slope shows.

## 59. The harness pins planner state to the log, so items 55, 57 and 58 measured one-frame effects only

Replay only; no repo code changed.

**Harness caveat (supersedes the conclusions of 55, 57 and 58).** Mode `x0+src+pa+oat`
(`replay.py`) re-anchors the MPC initial state (`x0`), the previous accel (`pa`) and the previous
published output (`oat`) to the LOGGED values every frame. That is right for reproducing the log
(the p99 gate), but in a counterfactual nothing the change does can accumulate. The planner's state
is reset to what the car actually did on every frame. Items 55 (vision lead), 57 (ECO floor) and
58 (follow policy, BLoTv3) therefore measured only the instantaneous one-frame response. Their
"no effect" results are not evidence that those layers don't shape the brake. They have to be
re-run with the anchors removed (mode `src` or `free`). Ego speed and accel still come from the
log, so even that is planner-open-loop, not vehicle closed-loop.

**What is still valid from this item (the instantaneous response under the logged state).**
- Line trace at 24f 272.7 (`w271.4:272.4`): the target before the final clip (`L2568`, MPC at
  action_t) goes -1.0 -> -4.17 in 0.7 s. The published output (`L3115`) is held above it by
  `output_accel_min = min(ECO -0.5, a_desired + 0.05)` (`:2202`, item 45). So in ECO the output
  tracks the one-step `a_desired`, not the MPC's lookahead demand: 272.07 raw -4.04 vs out -2.03.
- With the lead's vRel/vLead/aLeadK taken from 1.0 s later (`LEAD_ADV=1.0`, non-causal), the
  pre-clip target reaches -5.1 at 271.12, 1 s earlier than baseline. Earlier lead information does
  make the MPC ask earlier. Under the anchors the output can't show it.
- Q1, lead lag: over the five events the fed `vRel1` lags the range derivative by about 0.3, 1.35,
  1.45 (rms 3.4, unreliable), 0.65 and 0.30 s. Route-wide 5 s windows give a median of 0.25 s
  (p75 0.70). The fits are noisy. It suggests, but does not show, extra lag at brake onsets.
- In all five events the lead itself braked hard (aLeadK -3.7 to -4.4, range slope -3.5 to -5.2)
  on a single track (no handover). The rail brakes answer real hard lead braking.
- Q2 (`TF_ADD=0.3`): no instantaneous effect. It has to be re-run un-anchored.

New harness envs: `LEAD_ADV=<s>`, `TF_ADD=<s>` (backup `replay.py.bak-pre-leadadv`); scripts
`vq2.sh`, `q1lead.py`, `q1lag.py`; traces `trC.txt`, `trCadv.txt`.

## 60. Un-anchored re-run: the vision lead is much softer, the ECO floor and pre-brake are not a fix, and no car-specific cap fires

*Replay evidence only, route 24f, groups B-F, harness mode `src`.* In this mode the planner runs
on its own state, and only the source label is pinned. Ego speed still comes from the log, so the
gap does not respond to a change in braking. That understates how much braking a delayed
response would need later.

**Control:** the un-anchored base reproduces the logged aTarget (group C p99 0.004 m/s2, PASS).
The metrics in the table match the log to 0.01. Counterfactual runs "FAIL" the gate by design,
because they diverge from the log.

| variant | effect on the 5 bookmarked brakes (peak / steepest 0.5 s rate, base -1.9 to -4.25) |
|---|---|
| ECO floor at -1.0 (`MINACC_FORCE=-1.0`) | removes the -0.5 hold (0.6-1.05 s -> 0-0.1 s); same peak; rate about the same |
| ECO floor off (-3.5) | hard part 0.15-0.6 s earlier; 449.1 -2.09 -> **-3.50**, rate -2.55 -> -6.10. Harsher |
| follow policy off (`FP_OFF`) | no change (max rate diff 0.11) |
| tFollow +0.3 s (`TF_ADD`) | small, mixed (170.2 rate -4.17 -> -3.40, others within 0.2) |
| lead 0.5 s earlier (`LEAD_ADV`) | t<-1.5 0.45-0.65 s earlier; same peak and rate |
| vision lead (`VISLEAD=1`) | **peak -0.9 to -2.9, rate -0.9 to -1.9**. About half the radar response in every event |
| anticipatory pre-brake off (`PB_OFF`, L2529-2540) | peak 0.25-0.6 s later; rate softer at 170.2/595.7, **steeper** at 272.7/367.4 |

**Item 55 is reversed.** Its "vision is as deep" result was an anchoring artefact. Free-running, the
vision lead gives about half the braking. This matches 242 feeling smoother. It does not show
that radar is wrong, though: the lead braked at -3.7 to -4.4 in all five events (item 59), and
vision is known to understate fast closing.

**Cap census:** a line trace of `self.a_desired` and `output_a_target` over pk-4.5 .. pk+0.5 for
all five events. Only these lines change the value:
- L2526, the MPC interpolation;
- L2540, the anticipatory pre-brake, 22-58 frames per event, up to -0.06 per frame, fed back as the
  next x0;
- L2544, the deadzone;
- L3091/3093, the follow policy, almost always lifting (softening);
- L2758, `close_lead_brake_cap`, 2 frames at 449.1 and 595.7;
- L3115, the output clip (the ECO floor, lifting).

**None of the RAV4, Sienna, Accord, CR-V, vision-only or pretracking caps fire.** Trimming them
would not change these brakes.

**Conclusion (replay):** the planner's extra layers are not what makes these brakes harsh. The
harshness follows the radar-measured lead braking. The -0.5 hold is ECO, and a -1.0 floor removes
the hold without deepening the peak. The pre-brake is a two-sided trade-off, not a clean trim.
The harness also cannot show the closed-loop cost of braking later.

## 61. ECO soft floor drops to -1.0 while a lead is closing (branch `claude/eco-lead-floor`); closed loop keeps more gap

*Replay evidence only (open and closed loop), route 24f, groups B-F. Not road-driven.*

**Change** (`longitudinal_planner.py`, acc mode): when `radarState.leadOne` has status and
(vRel < -0.3 or aLeadK < -0.25), `accel_limits[0] = min(minAcceleration, A_CRUISE_MIN)`. The ECO (-0.5)
and traffic (-0.35) profiles are unchanged with no lead, or with a steady lead.

**Open loop** (mode `src`, ego speed from the log): the -0.5 hold goes from 0.60 to 0.05 s at 170.2,
0.20 to 0.00 at 449.1, and 0.20 to 0.00 at 595.7. 367.4 had no hold. 272.7 goes 1.05 -> 0.85 s: the
remaining 268.9-269.7 is steady-follow ECO (vRel ~0, aLeadK -0.1..-0.2), 3 s before the brake, and is
left alone on purpose. Peaks are unchanged.

**Closed loop** (new harness env `CL_T`). From CL_T = pk-6 the ego acceleration follows
`output_a_target` through a first-order lag (tau 0.35 s), and vEgo/aEgo are overridden. The lead
position and speed come from the log, so the lead does not react to us, and radarState dRel/vRel are
recomputed against the simulated ego. modelV2 and aLeadK stay as logged. Metrics cover pk-6 .. pk+8.
The first 3 s of every run match between variants, which is the sanity check.

| brake | variant | min gap m | min TTC s | peak cmd | steepest 0.5 s rate of a | t(a<-1.5) s |
|---|---|---|---|---|---|---|
| 170.2 | base / **(a)** / PB_OFF | 18.0 / **19.2** / 17.8 | 5.16 / **5.73** / 5.05 | -3.45 / -3.44 / -3.30 | -3.14 / **-2.84** / -2.88 | 3.30 / 3.10 / 3.35 |
| 272.7 | base / **(a)** / PB_OFF | 18.9 / **20.6** / 18.4 | 5.99 / **6.31** / 5.78 | -3.48 / -3.48 / -3.45 | -3.28 / -3.26 / -3.56 | 2.40 / 2.36 / 2.39 |
| 367.4 | base / **(a)** / PB_OFF | 28.8 / **29.5** / 27.4 | 4.84 / 4.87 / 4.54 | -3.48 / -3.47 / -3.45 | -1.62 / -1.64 / -1.78 | 6.10 / 5.80 / 6.10 |
| 449.1 | base / **(a)** / PB_OFF | 6.5 / **9.2** / 6.5 | 3.07 / **4.36** / 3.07 | -1.74 / -1.72 / -1.74 | -1.36 / **-1.18** / -1.36 | 0.39 / 0.45 / 0.39 |
| 595.7 | base / **(a)** / PB_OFF | 42.1 / 42.5 / 41.0 | 8.86 / 9.32 / 8.62 | -2.29 / -2.10 / -2.11 | -1.58 / -1.62 / -1.26 | 1.25 / 1.26 / 1.00 |

(a) + PB_OFF sits between the two in every event (vcl.sh `uapb`).

**Reading (replay).** (a) keeps more gap and TTC in all five brakes, with the same peak, and the jerk
is equal or softer (170.2 and 449.1 soften by about 0.2-0.3). It starts braking 0.2-0.6 s earlier at
about -0.6..-1.0 instead of waiting at -0.5. PB_OFF gives less gap in every event and a softer rate
in only 2 of 5. It is **not** a trim candidate: the pre-brake is buying distance. Harness limits:
- the lag model is not the car's actuator;
- the lead is replayed, not reactive;
- the model and aLeadK inputs are not re-simulated.

**Tests:** `selfdrive/controls/tests` gives "3 failed, 1263 passed" both with and without the change,
the same three pre-existing failures:
- `test_latcontrol`: bolt low-speed center output;
- `test_latcontrol`: palisade center taper;
- `test_starpilot_planner::test_force_stop_jerk_scale_is_platform_specific`.

No unit test is added yet. Nothing is pushed to `ns-bosch-radar-testing`.

## 62. FrogPilot "human following" = model lead path with no guard; softer brakes, less gap (closed-loop replay)

*Replay evidence only (closed loop as in item 61), route 24f, groups B-F. FrogPilot-Testing 728f65472
(2026-09-14), fetched as `refs/remotes/frog/testing`.*

**What FrogPilot has now.**
- `HumanFollowing` (`long_mpc.py process_lead`): when the model lead prob exceeds the threshold and the
  radar lead is valid, the MPC lead path is radar dRel/vLead plus the model's future x/v deltas, instead
  of the constant-aLeadK exponential extrapolation. There is **no** braking or TTC bail-out.
- `HumanAcceleration` only shapes max accel (low-speed and ramp-off) and launch. It does not touch
  braking. StarPilot already removed it (`test_human_acceleration_param_is_removed`).
- The FrogPilot ECO floor goes to ACCEL_MIN whenever `tracking_lead` (a stronger form of item 61).

**StarPilot** already has the same path (`build_model_lead_trajectory`, long_mpc.py:159). It
falls back to the raw extrapolation when aLeadK < -0.5 or (closing > 0.75 m/s and TTC < 7 s): see
`MODEL_LEAD_TRAJECTORY_MAX_LEAD_BRAKE/MAX_CLOSING_TTC`, commits 24f482966 and 7f2bab7be. There is no
evidence entry, only the comment "optimistic model horizon cannot delay the first braking response".
Every bookmarked brake trips that guard, so the harsh path is the raw aLeadK extrapolation. The item-60
"vision lead is half as hard" result is the same effect.

Harness env `MLT_FROG=1` sets both guard constants to never trip.

| brake | min gap m: base / (a) / MLT / (a)+MLT | min TTC s: same order | peak cmd: same order | steepest 0.5 s rate: same order |
|---|---|---|---|---|
| 170.2 | 18.0 / 19.2 / 13.4 / 13.7 | 5.16 / 5.73 / 4.19 / 4.36 | -3.45 / -3.44 / -2.05 / -1.93 | -3.14 / -2.84 / -1.26 / -1.04 |
| 272.7 | 18.9 / 20.6 / 16.5 / 17.2 | 5.99 / 6.31 / 5.65 / 6.03 | -3.48 / -3.48 / -2.36 / -2.26 | -3.28 / -3.26 / -1.26 / -1.18 |
| 367.4 | 28.8 / 29.5 / 23.6 / 27.7 | 4.84 / 4.87 / 3.70 / 4.31 | -3.48 / -3.47 / -2.34 / -2.28 | -1.62 / -1.64 / -1.72 / -1.40 |
| 449.1 | 6.5 / 9.2 / 6.3 / 8.7 | 3.07 / 4.36 / 3.21 / 4.25 | -1.74 / -1.72 / -1.10 / -1.15 | -1.36 / -1.18 / -0.50 / -0.84 |
| 595.7 | 42.1 / 42.5 / 34.9 / 37.8 | 8.86 / 9.32 / 8.24 / 8.93 | -2.29 / -2.10 / -0.92 / -1.00 | -1.58 / -1.62 / -0.96 / -1.68 |

Full FrogPilot braking (MLT + ECO floor to ACCEL_MIN, tag `frog`) keeps the most gap but restores
the peak (-2.9 to -3.5) and hits a rate of -4.0 at 449.1.

**Reading (replay).** The guard is what makes these brakes feel "reactive". With it off, the peak
falls by about a third and the jerk by about half. The cost is 1-7 m of gap and up to 1.1 s of TTC
(367.4: 4.84 -> 3.70), and (a) wins back part of that. Limits:
- the model lead deltas are replayed from the log, so they do not react to the simulated ego;
- the lead is not reactive.

This is a safety-margin trade and it is not decided here. No code change is made.

## 63. Model lead path keeps only a 3 s closing-TTC guard (closer to FrogPilot HumanFollowing); replay only

Following 62, and at the user's request (goal: FrogPilot-like following, fewer guards that cause abrupt
braking), `build_model_lead_trajectory` (`long_mpc.py`) no longer falls back to the raw aLeadK
extrapolation because the lead is braking (`MODEL_LEAD_TRAJECTORY_MAX_LEAD_BRAKE` 0.5 is removed). The
closing-TTC fallback is reduced from 7 s to 3 s (`MODEL_LEAD_TRAJECTORY_MAX_CLOSING_TTC`); it still needs
closing > 0.75 m/s.

Closed-loop sweep on the five bookmarked 24f brakes, with the 61 ECO floor in place (CL_TAU 0.35):

| guard (lead-brake / TTC)  | peak cmd (m/s^2)                      | min TTC (s)                  |
|---------------------------|----------------------------------------|------------------------------|
| 0.5 / 7 (old)             | -3.44 / -3.48 / -3.47 / -1.72 / -2.10  | 5.73 / 6.31 / 4.87 / 4.36 / 9.32 |
| 1.5 or 2.5 / 7            | about the same as old                  | -                            |
| 4 / 3                     | partial improvement                    | -                            |
| none / 3 (this change)    | -1.93 / -2.26 / -2.28 / -1.15 / -1.00  | 4.36 / 6.03 / 4.31 / 4.25 / 8.93 |

Limits:
- **The 3 s TTC guard never trips in these five events, so its effect is not tested by replay.**
- The model lead deltas and the lead are replayed from the log and do not react to the simulated ego.
- Min TTC is lower than with the old guards on three of the five brakes. This trades margin for comfort.
- Replay evidence only. Nothing is road-validated. On the next drive, watch hard lead brakes, cut-ins
  and late stopped-car approaches. The concern is braking that starts later than before.

Tests: `test_model_lead_trajectory_used_for_braking_lead_with_long_ttc` is added. The urgent-fallback
case now uses a closing lead at a 2 s TTC. The `selfdrive/controls/tests` run gives 1264 passed and 3
failed, and all 3 failures were already failing before this change (latcontrol bolt, latcontrol
palisade, `test_force_stop_jerk_scale_is_platform_specific`).

## 64. Guard trim batch 1: three inert highway caps deleted; batch 2 not exercised; 254 vs 257 drive A/B; replay + limited road evidence

Goal: trim longitudinal guards that do not measurably buy gap or TTC, so the MPC and model decide more
(closer to FrogPilot). Scope is the longitudinal planner only. Method: each guard was given a temporary
env kill switch, and the five bookmarked brake events of route `0000024f--8c147bae2e` (B 140 s, C 262 s,
D 357 s, E 440 s, F 585 s) were replayed closed-loop (CL_TAU 0.35, lead non-reactive) with each guard
off, one at a time, against the same tree. A guard is kept only if removing it loses gap or TTC.

### Batch 1 (highway braking caps) — closed-loop replay, minGap m / minTTC s

| Event | base | no close_lead_brake_cap | no inside_gap cap | no raw_close_lead_needs_control | no matched floor | no transition limiter |
|---|---|---|---|---|---|---|
| B | 13.70 / 4.36 | 13.71 / 4.35 | 13.75 / 4.37 | = | = | = |
| C | 17.20 / 6.03 | 17.09 / 6.03 | 17.19 / 6.03 | = | = | 17.19 / 6.03 |
| D | 27.68 / 4.31 | **24.37 / 3.98** | = | 27.83 / 4.32 | = | = |
| E | 8.69 / 4.25 | **7.47 / 3.72** | = | **5.08 / 1.28** | = | = |
| F | 37.81 / 8.93 | 35.20 / 8.21 | 37.72 / 8.89 | = | 38.82 / 8.93 | 37.35 / 8.92 |

KEPT: `get_close_lead_brake_cap` (D loses 3.3 m, E loses 1.2 m, and the brake starts later and ends
harder: D peak −2.28 → −2.39, 0.5 s rate −1.40 → −1.70) and `raw_close_lead_needs_control` (E TTC
4.25 → 1.28). DELETED, all inert (peak command moved ≤ 0.03 m/s² on every event):
`get_inside_gap_closing_lead_accel_cap` and its `INSIDE_GAP_CLOSING_*` constants,
`lead_follow_policy._matched_brake_floor`, `lead_follow_policy._transition_target` and the
`FOLLOW_TRANSITION_*` / `FOLLOW_SIGN_CROSS_STEP` / `FOLLOW_MAX_CLOSING` constants, and
`MATCHED_FOLLOW_TRANSITION_MIN_SPEED`. `FollowResult` is now `(lead, accel_cap, target)`; nothing
outside the policy consumed `brake_floor`. `get_lead_geometry_required_accel` is telemetry only and
was left alone. Batch 1 does not explain the abrupt-braking complaint; the replay harness at
`$T/vcl.sh` / `vclcmp.py` now mounts the branch planner, policy and `long_mpc.py` together.

### Batch 2 (vision-lead caps) — not exercised by the corpus

`get_vision_lead_approach_cap`, `get_vision_untracked_slow_lead_cap`,
`get_vision_untracked_approach_lift_cap`, `get_vision_slow_stopped_lead_cap`,
`get_tracked_vision_model_brake_floor` / `_cap` and `tracked_vision_lead_approach_needs_immediate_brake`
were swept the same way. Every tag produced byte-identical numbers on all five events in every column.
All five events are radar-tracked leads and every batch-2 guard is a vision-lead path, so replay cannot
distinguish harmless from untested here. Decision: keep batch 2 and defer until a vision-only brake
event is replayed (route `00000257--50424c1a3a` at 348.7 s, `radar=0`, peak −2.55, is a candidate).
Batch 3 (standstill and depart holds) is not started and rests on road testing; replay covers stop-go poorly.

### Drive A/B on the STATUS 63 change: `00000254--8afa97025c` (5d7e1512f) vs `00000257--50424c1a3a` (8c9f5dc66)

Both builds are confirmed from initData; the only planner difference is STATUS 63 (model lead path keeps
only the 3 s TTC guard). Per-frame scan (`/routes/an2/scan_<r>.csv`, summary `$T/smooth.py`),
longActive frames only:

| | 254 before | 257 after |
|---|---|---|
| longActive frames | 4843 | 7795 |
| aTarget p1 / p5 | −3.45 / −1.97 | −2.13 / −1.00 |
| measured aEgo p1 | −3.87 | −2.42 |
| worst 0.5 s drop of aTarget | −3.86 | −1.72 |
| 0.5 s drops steeper than −1.5 m/s² | 37 | 8 |
| braking episodes (aTarget < −1.0), peak | 5, all at −3.45 (the clamp) | 6, −1.28 … −2.82 |
| driver brake while enabled / disengagements | 0 / 9 | 1 / 9 |

Every "before" episode pinned at the −3.45 floor and four of the five had command drops of −1.9 to
−3.9 m/s² inside half a second. After the change the hardest event (415.8 s, lead 75 m closing at
16.7 m/s) peaked at −2.82 with a −0.80 drop. This is one drive each on different roads: limited road
evidence, not a controlled comparison. The one driver brake press in 257 (127 s, lead 72 m closing
7 m/s, planner asked −1.57) is a candidate "too soft" case to look at.

Tests: `selfdrive/controls/tests` gives 1256 passed, 4 skipped, 3 failed; the 3 failures are the same
pre-existing ones (latcontrol bolt, latcontrol palisade, `test_force_stop_jerk_scale_is_platform_specific`).
Five tests for the deleted guards were removed. The 9 `ruff` findings on the planner and its test file
all lie outside the diff hunks and are pre-existing. Not road-validated.

## 65. Guard trim batch 2 (vision-lead caps) replayed on three vision-only brake events; only the untracked slow-lead cap buys gap; replay only

Batch 2 was deferred in STATUS 64 because route 24f has radar leads everywhere. Three vision-only
events were replayed closed-loop (CL_TAU 0.35, lead non-reactive, branch planner at 820c58ca3
mounted over the built tree), with each guard turned off one at a time through a replay-harness
monkeypatch (the branch has no kill switches):

| Event | Route | Build | What happens |
|---|---|---|---|
| V 348.7 s | `00000257--50424c1a3a` | 8c9f5dc66 | vision lead 44 m closing 7.2 m/s at 12.5 m/s, radar 0; logged peak aTarget −2.55 |
| W 787.7 s | `0000020c--4712c9cce5` | d8604bd20 | untracked vision lead 70–90 m closing 6–9 m/s at 13.5 m/s, `src=cruise` throughout |
| X 221.0 s | `0000020c--4712c9cce5` | d8604bd20 | vision lead 78 → 45 m at 21.6 m/s, tracked as `lead1`/`lead0` |

Route 20c has no radar lead in any of its 5792 longActive lead frames. Closed loop, minGap m / minTTC s / peak cmd:

| Guard off | V | W | X |
|---|---|---|---|
| base | 12.24 / 4.13 / −2.41 | 41.28 / 6.56 / −0.85 | 22.07 / 3.71 / −3.50 |
| `get_vision_lead_approach_cap` | 12.06 / 4.09 / −2.42 | = | = |
| `get_vision_untracked_slow_lead_cap` | = | **17.22 / 5.55 / −1.06** | 21.99 / 3.68 / −3.50 |
| `get_vision_untracked_approach_lift_cap` | = | = | = |
| `get_vision_slow_stopped_lead_cap` | = | = | = |
| `get_tracked_vision_model_brake_floor` + `_cap` | = | = | = |
| `tracked_vision_lead_approach_needs_immediate_brake` | 12.06 / 4.09 / −2.42 | = | = |
| all six off | 12.06 / 4.09 / −2.42 | 17.21 / 5.55 / −0.71 | 21.99 / 3.68 / −3.50 |

"=" means the closed-loop trace is byte-identical to base.

KEEP `get_vision_untracked_slow_lead_cap`: on W it is the only thing that brakes. With it off the
planner holds 11.5–12.3 m/s while the untracked lead closes from 70 m to 34 m, minimum gap 41 → 17 m
and TTC 6.6 → 5.6 s. MPC never took that lead (`src=cruise` for the whole event), so nothing else
would have.

Near-inert: `get_vision_lead_approach_cap` and `tracked_vision_lead_approach_needs_immediate_brake`
(same mechanism) advance the brake onset by one frame on V (cmd −1.30 instead of −1.00 for 0.1 s at
348.7 s); 0.18 m of gap, 0.04 s of TTC, then identical. Not exercised on W or X.

Not exercised on any of the three events: `get_vision_untracked_approach_lift_cap`,
`get_vision_slow_stopped_lead_cap`, `get_tracked_vision_model_brake_floor` / `_cap`. None of the
events had a stopped vision lead, so the slow-stopped cap in particular has still not been tested.

No code changed in this section. Deletion of the near-inert or unexercised guards waits for the
user's decision. Harness: `~/.claude/jobs/3c03581d/tmp/{vcl257.sh,vcl20c.sh,replay.py}` with
`GT_VLA/VUS/VUL/VSS/TVM/TVI=0` env hooks; `EVG="V:347.5:353.5" python3 vclcmp.py ...`.

## 66. Guard trim batch 2: vision lead approach cap and immediate-brake confirm bypass deleted (near-inert per STATUS 65); replay only

Per the user's decision on STATUS 65, the near-inert pair is gone from
`selfdrive/controls/lib/longitudinal_planner.py`: `get_vision_lead_approach_cap`,
`tracked_vision_lead_approach_needs_immediate_brake`, their call site in `update()`, the
`vision_lead_approach_confirm_t` state and the `VISION_LEAD_APPROACH_*` constants they alone used
(−112 lines). `VISION_LEAD_APPROACH_MIN_MODEL_PROB` / `_FULL_MODEL_PROB` stay because the untracked
approach-lift cap and `get_dynamic_t_follow` still read them.

Seven tests removed from `test_longitudinal_planner.py` (−133 lines): the four unit tests of the
cap, the two acc-mode/persistence tests that drove it, and
`test_acc_mode_tracked_vision_close_or_braking_lead_bypasses_persistence`, which asserted the
one-frame-earlier onset (first-frame command below −1.3) that STATUS 65 measured as the pair's
whole effect. Controls suite in docker: 1237 passed, 4 skipped, 3 failed, all three pre-existing
and unrelated (two latcontrol, `test_force_stop_jerk_scale_is_platform_specific`).

Closed-loop replay of event V (`00000257--50424c1a3a` 348.7 s, CL_TAU 0.35) with the deleted-pair
planner is byte-identical to the STATUS 65 "cap off" row: minGap 12.06 m, minTTC 4.09 s, peak
command −2.42 m/s², versus 12.24 / 4.13 / −2.41 with the pair. Events W and X were already
unaffected by these two guards.

Kept from batch 2: `get_vision_untracked_slow_lead_cap` (buys 24 m on 20c W),
`get_vision_untracked_approach_lift_cap`, `get_vision_slow_stopped_lead_cap`,
`get_tracked_vision_model_brake_floor` / `_cap` (unexercised on any replayed event, no stopped
vision-lead event exists yet). Replay evidence only; no road data on this build. Pushed to
`ns-bosch-radar-testing` for road testing; new routes to be analysed against this build.

## 67. First road route on `41abc1f36`: route 258. The hard brakes are real leads; the one worst brake followed a lead dropout; the car over-brakes its own command. Limited road evidence, no replay.

Route `11c8fa231c0499ed/00000258--626242f48b`, segments 39-67 (0-38 idle). `initData`: `gitCommit
41abc1f36`, `ns-bosch-radar-testing`, not dirty -- the STATUS 66 build. ECO decel
(`DecelerationProfile 1`), conditional experimental (experimental on 22.6% of engaged frames),
aggressive personality (tFollow 1.25-1.45). 22.9 engaged minutes, 5 user bookmarks. Analysis is
CSV-only (`scan_00000258--626242f48b.csv` in the `oprad-routes` volume, 20 Hz); the rlogs were
already cleaned from the fetch dir, so there is no `liveTracks` and no replay here.

**1. The planner is passed through unchanged; the extra braking past about −3 happens in the car.** `outAccel == aTarget` within 0.05
on 99% of engaged frames. Car response 0.35 s later, by commanded bin, median `aEgo - outAccel`:
−0.08 (−1..−0.5), −0.11, −0.16, −0.13, −0.04, **−0.34 (−3.6..−3.0)**, p10 down to −1.12. The
wheel-speed derivative (`dv/dt` over 0.2 s) agrees (−0.30 in the last bin), so this is not `aEgo`
noise. Worst cases: `aEgo` −4.76 against a −3.50 command (66:36), and −2.79 against −1.60 at 7 m/s
in stop-and-go (63:53.8). Every one of the 9 episodes reaching `aEgo` ≤ −3 had the command
saturated at or near `ACCEL_MIN` −3.5 and the ECO floor `minAcc` −0.50 overridden (the
`a2ed92d29` lead-closing floor). Road grade is not logged in the CSV and is not excluded.

**2. The hard brakes are real lead decelerations, not phantoms.** 42:59 (lead 24.4→6.4 m/s,
`aLeadK` −7.6, model agrees 17→2 m/s), 44:41 (radar 14.9→6.1, model 15→4.3), 51:33 (radar and range
slope agree at −7 to −8 m/s; the model lags by ~3 m/s), 43:49, 53:31, 55:27. Onset is driven by
`leadGeometryRequiredAccel` (2.7-5.9) with `closeLeadBrakeCap` equal to `aTarget`. On 51:33 and
55:27 the radar `aLeadK` spikes (−6, and +8.2 / +13.8 elsewhere) are implausible as accelerations but
the ranges confirm the closing.

**3. 66:36, the hardest brake on the route, followed a 2.5 s lead dropout.** Radar track `tid 20`
was the lead at 63 m, 11 m/s, `y` −3.2→−5.4 (curve), with `modelProb` 0.90→0.65. From 66:32.8 to
66:35.3 **no lead at all** was published (`nat_d1` NaN too) while the model's own lead probability
fell to 0.01-0.05 and its `mlX` walked 69→35 m. The lead came back at 66:35.3 as vision (27 m),
then **the same `tid 20`** at 29.4 m with `vLead` −1.4 (range slope confirms ~1 m/s), TTC ~2.4 s:
`aTarget` −3.50 within 0.5 s, `aEgo` −4.76. The same track id on both sides suggests the radar
kept the object and the *lead selection* dropped it when model probability collapsed -- the D-041/D-042
failure shape (a withheld point, not a degraded one). **Not proven:** without `liveTracks` it
cannot be shown that `tid 20` was continuously present during the gap. Re-fetch segment 66 to
settle it.

**4. Bookmarks.**
- 55:43 -- radar `tid 46` `vRel` frozen at −5.7 (and `aLeadK` 2.07) for ~4 s while its own range
  closed at only ~1.2 m/s; the planner braked to −1.0 twice and the driver overrode with gas twice.
  A stuck or over-closing radar velocity, the same class as the census "U11 over-closes future
  slope" (3 onsets on this route, 8/h).
- 63:10 -- a steady stop behind a decelerating lead, command −1.35, `aEgo` −1.5..−1.8. Looks
  proportionate; the only oddity is the car over-braking its command by 0.2-0.4.
- 63:57 / 64:07 -- stop-and-go. Command −1.0→−1.6 inside the desired gap (13.6 m at 7.8 m/s);
  `aEgo` −2.79. The jolt is the car over-braking its command by 1.2 at low speed. Driver gas at 64:04.
- 66:24 -- cut-in: new radar track `tid 18` at `y` +3.8, 23 m, `aLeadK` −6.4 → command −2.22 at
  engagement. Plausibly correct.

**What this does NOT establish.** One route, 22.9 min, CSV only, no replay, no `liveTracks`. The
over-brake could be Honda Bosch brake tracking or unlogged grade; it is outside the planner either
way, but its cause is not identified. Item 3's mechanism is inferred from the lead fields.

## 68. HumanAcceleration ported from FrogPilot (default off); HumanFollowing becomes a toggle (default on). Static and unit evidence only.

**HumanAcceleration** (`HumanAcceleration`, default **off**; FrogPilot defaults it on). Ported from
FrogPilot-Testing `728f65472` (`frogpilot_acceleration.py`, same math as the Nov 2025 snapshot
`202543c86`). Only `max_accel` changes, in `StarPilotAcceleration.update`: after the profile is chosen
and before the weather reduction. Braking and `min_accel` are not touched.
- The set speed scales max accel: 1/4 of it at a 0 set speed, 1/2 at 12.5 m/s, full from 25 m/s.
- Ramp-off near the set speed: 0 at the set speed, 0.5 m/s² at 1 m/s below it, full at 5 m/s below.
- FrogPilot's other half (in the starting state, longcontrol outputs `a_target` instead of
  `startAccel`) is **not ported**. StarPilot's starting state already clips `a_target` to
  `[0, startAccel]`.

**HumanFollowing** (`HumanFollowing`, default **on**). The model lead path with the 3 s closing-TTC
guard from STATUS 62/63 used to be unconditional. It is now gated in `human_following_model()`
(`longitudinal_planner.py`): with the toggle off, the MPC gets no `modelV2` and every lead
falls back to the `aLeadK` extrapolation. On by default, so driving is unchanged unless the
driver switches it off. The Nov 2025 FrogPilot follow-gap HumanFollowing is **not** ported.

**Where the settings live.** Both toggles follow FrogPilot's gating: they sit under
Longitudinal Tuning (`parent_key LongitudinalTune`, on-device panel rows between Deceleration
Profile and Human-Like Lane Changes) and read as off when `LongitudinalTune` is off
(`get_value(..., condition=longitudinal_tuning)`). Both keys came out of
`STARPILOT_REMOVED_PARAM_KEYS`; they were in that list, which deleted them on every boot.
Both are also in the safe-mode key list. Galaxy's `HIDDEN_SETTING_KEYS` is now empty.

**Artifacts.** `common/libcommon.a` and `common/params_pyx.so` were rebuilt using the larch64 Docker
recipe (Cython 3.1.4, `SP_FORCE_TICI=1`, sconsign cleared first). The key count went from 822 to
824, and `Params(memory=True)` returns defaults HumanAcceleration=False, HumanFollowing=True.

**Tests.** New unit tests (`test_starpilot_acceleration.py`, `test_longitudinal_planner.py`,
galaxy layout) pass. 5 tests fail: 4 fail identically on a clean HEAD export (`test_latcontrol`
×2, `test_force_stop_jerk_scale_is_platform_specific`, one `test_starpilot_card` case). The 5th,
`test_every_galaxy_toggle_key_exists_in_the_committed_device_params_binary`, reads the committed
`.so` and needs the commit. Not replayed, not driven.

## 69. Route 258 re-examined with rlogs: the 43:49 FCW was a real lead hidden for 12.7 s by a self-latching Bosch-A vRel rate check; the trim batches are not implicated. Replay (parser) plus limited road evidence.

Route `11c8fa231c0499ed/00000258--626242f48b` is still the newest on Konik (68 segments). Segments
42-44 and 66 were re-fetched; `initData` on 43: `gitCommit 41abc1f36`, `RangeDerivedVrel 1`,
`HondaBoschARadar 1`.

**1. The FCW (first frame route t 2628.88 = 43:48.9; Peter noted it as 43:41) is the planner FCW, not stock.**
`longitudinalPlan.fcw` (MPC crash count > 2), `carState.stockFcw` never set, driver never braked.
The lead is real: radar `tid 13`, model prob 1.00, braking 24 → 3 m/s; min gap ~7 m at 3 m/s,
`aEgo` −3.9. STATUS 67 item 2 already listed 43:49 as a real lead; what it missed is below.

**2. For 12.7 s before the FCW the published closing speed was wrong by up to 8 m/s.** From 43:29.2
to 43:46.0 `tid 13` was published `measured=False` with `vRel` held at −0.45 (the last trusted
value) while its range fell 124 → 31 m. The radar was right: raw U11 went −3.3 → −8.7 m/s and
matches the range slope. With `vLead` ≈ `vEgo` the planner stayed in `cruise` until d = 42 m and
reached −1 m/s² only at d = 31 m, when U11 was re-admitted (−2.9 s). `aLeadK` sat frozen at +13.75
and `vLeadK` at 17.1 throughout, because the lead KF is not stepped on coasts.

**3. Mechanism: replay of the real `RadarInterface` with an instrumented copy (not committed).**
Every sweep in that window hit `vrel_inconsistent` (the one-sided multi-sweep rate check, D-054):
U11 < fitted range rate − 3.0. The fit uses `track.samples`, and **`samples` is only appended on
accepted or rejoin-held sweeps, never on a `vrel_inconsistent` coast** — even though the range
itself had passed the innovation gate (the comment above the check says the accepted range "is the
gate's baseline from here on, whatever happens to vRel"). The 8 samples froze at 43:12.2-43:18.7,
while the lead was pulling away (+2.8 m/s), so the fit kept a stale opening rate and rejected
every correct closing U11 that followed. The gate latches itself until the single fresh point drags
the frozen fit far enough — here 12.7 s and 90 m of closing. This is a lockout of the kind
`lockcensus.py` looks for, triggered by a real opening → closing reversal of the lead.

**4. Neither safety net saw it.** RadarD's D-053 range assist clears on a coast and appends to
`range_hist` only on measured updates, so `vRelRangeDerived` was NaN for the whole window. The
model lead read 19-21 m/s (closer to truth), but the HumanFollowing path anchors on the radar
`vLead` and takes only the model's future deltas.

**5. Segment 66 (STATUS 67 item 3) is settled: a withheld point, not a missing one.** `tid 20` was
in `liveTracks`, `measured=True`, on every sweep of the 66:32.75-66:35.25 gap (range 60 → 35 m,
`y` −6.7 → −8.6 on a curve, `vRel` −2.5 → −13.5, range slope ~12 m/s confirms). Lead selection
dropped it when the model lead probability collapsed to 0.02-0.24. D-041/D-042 failure shape.

**6. Trim batches (STATUS 64, 66): neutral, not measurable.** Neither route-258 event involves a
deleted guard: the vision-lead approach cap returned early for any `lead.radar` lead (43:49 was
radar throughout) and there was no lead at all during the 66:33 gap. Census (`hb.py`, aTarget < −1.5
onsets per engaged hour): 254 (pre-trim) 74/h over 4 min, 257 (pre-trim) 18/h over 6 min, 258
(post-trim) 21/h over 23 min. The baselines are 4 and 6 engaged minutes; no rate difference is
resolvable. No evidence the trim hurt; none that it helped.

**Next, in priority order (none implemented):**
1. Rate-check lockout: append the innovation-gated range to `track.samples` on a
   `vrel_inconsistent` coast too, so the fit tracks the object. Must be A/B'd with the `ab3.py`
   harness (lost / gained / newly-measured vRel over-close vs the next-1 s range slope against ref)
   on 258 and the cached routes before promotion — D-056 shows a gate relaxation can re-admit
   over-closing U11. Add a `lockcensus.py` count of inconsistent runs > 2 s per route.
2. Let D-053 range assist use coasted-but-gated ranges, so a long coast gets a range-derived vRel.
3. Lead selection must not drop a measured, continuously tracked lead on a model-probability
   collapse alone (segment 66).

## 70. D-062 implemented: a lasting clean run of rate-check coasts re-roots the Bosch-A vRel fit. Static and replay evidence; not driven.

Fixes the STATUS 69 lockout (route 258 43:29-43:46). Mechanism and rule in D-062;
`radar_interface.py` `inconsistent_run`, tests `TestRateCheckCoastReRoots` in
`test_bosch_a_radar.py`.

**Replay harness.** `ab9.py` (not committed, in the `oprad-routes` volume) runs the current parser
(M) and D-062 (R) side by side over each route's rlogs. The routes are the 24 cached rlog routes
(`0000020c`, `231`-`258`).

**1. Coverage.** R loses 0 radar points and 0 lead points against M. It turns 711 coasted sweeps into
measured ones (113 on the lead) and 16 measured sweeps into coasts (3 on the lead).

**2. The one-sided score overstates the cost.** Counting only R's newly measured vRel, 15.4%
over-close the next-1 s range slope by more than 3 m/s, against 4.7% for M's own measured vRel. The
score never looks at the coasted value M published on the same sweep, and that value is often far
worse. On 251 `tid 60`, M held −13.50 for 3 s while the range closed at about −4 to −6. R re-rooted
0.9 s earlier at −8.0 and converged to −6.3; it scores as over-closing but is about 5 m/s nearer.

**3. Paired score.** For every sweep that R measures and M coasts, compare each value with the
next-1 s range slope (at least 10 range points over at least 0.7 s). A side wins when it is nearer
by more than 0.5 m/s.

| | sweeps | R nearer | M coast nearer | summed abs error R / M (m/s) |
|---|---|---|---|---|
| all | 421 | 235 | 79 | 815 / 1,627 |
| lead | 113 | 73 | 35 | — |

By route: 258 is 94 to 4 (lead 71 to 0; M error 709, R 269). 251 is 51 to 17, 24b 20 to 7 and 232
30 to 1. **Against R:** 241 is 0 to 20 (lead 0 to 16) and 24f is 7 to 19 (lead 2 to 19); 237 is
0 to 9, a near tie (median error 1.55 vs 1.48). R over-closes (by more than 3 m/s) where M does not
on 43 sweeps, 31 of them on 258.

**4. The lead losses, by hand.**
- 241 `tid 33`: M coasts −6.67 until 414.7 s; R re-roots at 413.1 with −9.27 and eases to −7.59;
  they agree from 414.73. R is nearer at first and farther later. It errs by 1-2.6 m/s toward
  closing, and neither value is unsafe.
- 24f `tid 18`: both parsers are stale for about 2.5 s, and R is about 1.4 m/s more closing.
- The one hand-checked real R over-close is 239 `tid 13`, not a lead.

**5. Not tightened.** At 3 m/s, the trailing range slope does not separate the good re-roots from
the bad. Three lead routes are too few to re-tune the D-057 thresholds (rule 5). On the lead, the
expected road symptom is earlier or harder braking behind a car that is closing slowly, not a late
brake.

**MetaDrive logic test of 087646dc (static, real `_update_steering_torque`, scripted CS/CC).** Cases 1–7 passed. It found three faults, all fixed in this commit.
- **Release.** While the release hold kept a let-go press, tq·cmd = 0 read as a fight, so every help release stepped 0.8 → 0 and faded back. Fix: |tq| under the 0.75× release level is neutral and holds the state.
- **Ceiling hover.** 3500 ± 100 gave 38 edges in 4 s. Fix: a ceiling cut resets the entry hold, and re-entry needs 0.2 s under 1.5× (`SAME_DIR_REENTRY_FRAC`).
- **Speed edge.** 25 ± 0.5 mph gave 6 transitions. Fix: a speed exit locks until release, like the time cap.

By design, each help press still starts with the ordinary cut: an instant cut, 0.2 s at 0, then a 0.5 s fade-in. That is about a 0.7 s notch, the price of the sign hold.

**Tests (static).** All 260 Honda radar tests pass in docker. Controls suite in docker: 1246 passed, 4 skipped, 3 failed. These are the same three failures as STATUS 66 (two in latcontrol, `test_force_stop_jerk_scale_is_platform_specific`); none is new.

**Next.**
1. Drive it. Watch for brakes that are early or harder than the gap needs behind slow-closing leads.
2. Done: the qlog sweep follow-up is below. Still open: replay route 252 (`00000252--69505eb434`),
   segments 15 and 16, once its rlogs reach Konik.
3. STATUS 69 next items 2 (D-053 range assist on gated coasts) and 3 (a lead dropped on a
   model-probability collapse) are still open.

**Follow-up (2026-09-23): qlog sweep and 24d.**

*Correction.* The table in point 3 covers 23 routes, not 24. `ab9.py` crashed on `0000024d` on a
point that only R publishes (M has no value to pair against). With that guard added, 24d gives:
R loses 0 points and 0 lead points, 69 coasted sweeps become measured (none on the lead), and R
publishes 31 point-sweeps that M did not (none on the lead). The paired score goes 2 to 21 against R
(median error 1.69 vs 0.79 m/s, none on the lead, neither side over-closes). With 24d the all-sweeps
row becomes 461 sweeps, 237 R nearer, 100 M nearer, summed error 878 / 1,659. The lead row is
unchanged.

*qlog sweep.* 254 radar-era routes, 198 with engagement, 43.7 engaged hours, 0 segment errors.
Flags: FCW 64, hard brake 765, sign reversal 446, and `frozen_lead` 13 on 7 routes (lead vRel and
aLeadK bit-identical for at least 2 s while its range moves at least 1 m). qlogs only found the
candidates. Every check below is an rlog replay.

| route, t (s) | frozen | M rate-check run in rlog? | lead / engaged | D-062 re-roots it? |
|---|---|---|---|---|
| 252 262.7, 992.3 | 12.2 s, 9.5 s (992: closing 68→36 m) | **rlogs not on Konik yet** | — | not replayed |
| 24d 660.2 | 11.8 s | yes, tid 23, 12.5 s, agrees with U11 | 0.94 / 0.94 | no |
| 24d 828.5 | 4.7 s | yes, tid 47, 7.6 s, 104→56 m, U11 over-closes | 1.0 / 0.26 | no |
| 24d 1506.3 | 4.0 s | yes, tid 47, 5.2 s, agrees | 1.0 / 1.0 | no |
| 23f 1240.6 | 6.0 s | **no run of 2 s or more** | — | — |
| 23f 1640.4 | — | yes, tid 37, 3.9 s, agrees | 0.61 / 1.0 | no |
| 24f 367.4 | 5.5 s, closing 53→37 m | yes, tid 18, 5.8 s, U11 over-closes | 1.0 / 0.45 | **yes**, 1.2 s from 372.8 (point 4) |
| 24f 799.2 | — | yes, tid 23/33, about 2.6 s | 0 and 1.0 / 0 | no |
| 23e 875.7 | 2.5 s | yes, tid 28, 9.4 s, agrees | 0.31 / 1.0 | no |
| 251 490.9 | — | yes, tid 39, 3.8 s, opening | 0.76 / 1.0 | no |
| 251 499.7 | — | yes, tid 30, 2.3 s, U11 over-closes | 0.97 / 0.57 | no |
| 257 169.2 | — | yes, tid 61, 2.2 s, opening | 1.0 / 1.0 | no |

Replay findings:
- The qlog `frozen_lead` signature finds the M rate-check coast in 10 of 11 events that could be
  replayed.
- 23f 1240.6 has no rate-check run behind it. That freeze is unexplained, and the qlog decimation
  may be the cause.
- D-062 re-roots only one flagged lead, 24f `tid 18`. That is the loss already listed in point 4.
- On the others, R has no lead run of 1 s or more that differs from M.
- Those runs are also `degraded` for their whole length (24f `tid 18` only half of it). This is an
  observation, not a tested cause.
- The 258-style lockout (a clean, lasting run of rate-check coasts on the lead while closing) does
  not show up in any other replayable route.
- 252 at 992 s is the one open candidate, and it is closing. Its rlogs upload only on WiFi. When
  they do, fetch segments 15 and 16 and replay them with `ab9.py`.

## 71. The car over-brakes its own command, and the cause is not in our code: the Honda Bosch brake ECU overshoots fast brake onsets. It happens on all 7 routes checked. Replay (log decode) evidence only.

Follows STATUS 67 item 1. Scripts `ob1.py` (per-route bins and episodes) and `ob2.py` (timelines) are in
the `oprad-routes` volume at `/routes/an2` and are not committed. They were run on the rlogs of 258,
257, 254, 251, 24f, 241 and 237.

**1. We send exactly what the planner asks for.** On every route, `ACC_CONTROL.ACCEL_COMMAND` (0x1DF,
decoded from `sendcan`) equals `carControl.actuators.accel`: median difference 0.000, p1/p99 within
±0.03 m/s². On Bosch, `carcontroller.py` only clips to [−3.5, 2.0], and the hill term reaches only
the gas path. Honda Bosch has no longitudinal PID (`kiV` is set only for non-Bosch), so the car's
own ECU closes the loop on `ACCEL_COMMAND`.

**2. Grade is not the cause.** Median pitch is 0.1-1.4° per bin. Correcting `aEgo` by g·sin(pitch)
moves the bin medians by at most about 0.25 and does not remove the saturated-bin offset.

**3. Steady tracking is good; only the saturated bin over-brakes.** Median `aEgo(t+0.35) − cmd` is
within ±0.35 on routes with enough samples for every bin from −0.5 to −3.0 m/s². The −3.0 to −3.6 bin is
−0.25 to −0.65 on every route that reaches it (258 −0.34, 237 −0.33, 241 −0.65, 24f −0.25, 251 −0.29,
254 −0.26).

**4. The large overshoots are short transients at fast brake onsets.** There are 28 episodes across
7 routes where `aEgo` stays more than 0.8 below the command for at least 0.3 s. All have
`BRAKE_REQUEST` set, most last 0.3-0.7 s, and in every one the minimum `aEgo` is more than 0.8
below the minimum command, so reaction lag does not explain them.
- About half peak at a saturated command: 237 cmd −3.42 → `aEgo` −5.98; 254 −3.46 → −5.21;
  258 51:30 −3.39 → −4.04 (`dv/dt` agrees), then the brake releases about 0.3 s behind the command.
- Low speed after a gas-to-brake flip, the STATUS 67 stop-and-go jolt: 258 63:50 at 7.7 m/s went
  from +0.8 to −1.5 in 1 s and `aEgo` reached −2.8. 3 of the 28 episodes are below 10 m/s.
- The routes predate and postdate the guard trims (237/241 against 258), so this is car behaviour,
  not a regression.

**Superseded by item 72:** over-brake scales with brake depth, not onset rate, so the "fast brake
onsets" wording in this heading and in point 4 is wrong.

**What this does not establish.** Whether ECU overshoot depends on the command's rate (jerk) rather
than its level. The data suggests rate, but no replay has varied it. On the road, a brake onset
overshoot is conservative for collision but is felt as a jolt.

**Options (none implemented; any change that lowers a brake command needs a decision first):**
1. Leave it. It errs toward more braking, and a mid-range command is tracked within about 0.2.
2. Limit command jerk at brake onset, below 10 m/s and on gas-to-brake flips only. This targets the
   stop-and-go jolt and does not change the peak deceleration available.
3. Do not scale down saturated commands to cancel the overshoot. It would cut peak braking in exactly
   the emergencies where it is needed.

## 72. Brake over-delivery scales with how hard openpilot asks, not how fast the brake builds; the close-lead cap is not the jolt's cause. Parked, open to revisit. Replay (log decode and closed-loop planner) evidence only.

Follows item 71. Peter asked (1) whether a StarPilot planner guard causes the fast brake onset and
could simply be deleted, as with the item 64-66 trims, and (2) for option 2 of item 71, an onset
jerk limit. Result: no guard to delete, and option 2 is not supported. **Nothing changed in code.**

**1. The 258 63:50 stop-and-go jolt runs through `get_close_lead_brake_cap`, but the cap is not
the problem.** From 49.72 to 51.8 s `longitudinalPlan.aTarget` equals `closeLeadBrakeCap` on every
frame. The first frame replaces the MPC's +0.45 with −0.81, because the cap arrives at full strength
when projected TTC crosses `CLOSE_LEAD_BRAKE_CAP_MAX_TTC` (10 s). Its value is mostly
`0.7 * aLeadK`, and here the lead really was braking (aLeadK to −2.7). A closed-loop replay from
49.0 s (CL_TAU 0.35, lead not reactive) compares three runs:

| Run | reaches −1.0 | peak cmd | min gap |
|---|---|---|---|
| cap on (as driven) | 49.81 s | −1.57 | 9.83 m |
| cap off | 49.96 s | −1.75 | 9.89 m |
| cap off below 10 m/s | same as off | −1.75 | 9.89 m |

Without the cap, the MPC reaches −1.0 only 0.15 s later and then brakes harder. The cap was also kept
by item 64 on highway gap evidence. It stays. The MPC's own swing is +0.45 to −1.0 in about 0.65 s.
The car's `aEgo` of −3.0 against a −1.5 command came about 0.8 s later, while the command was steady.

**2. All 79 brake onsets on the 7 item-71 routes.** An onset is the command crossing −1.0 from above
−0.2, with none in the previous 4 s, followed by 3 s with long control engaged and no pedal.
Over-brake is min `aEgo(t+0.35)` minus min command over those 3 s, pitch-corrected; negative means
the car braked harder than asked.

| onset rate (m/s³) | n | median over-brake | share worse than −0.8 |
|---|---|---|---|
| < 1 | 49 | −0.42 | 14% |
| 1-2 | 8 | −0.37 | 0% |
| 2-4 | 3 | −1.31 | 67% |
| ≥ 4 | 19 | −0.11 | 5% |

- Faster onsets over-brake **less**: the correlation of rate with over-brake is +0.46, where positive
  means less over-brake.
- The least-squares fit is `over = −0.13 + 0.019·rate + 0.268·cmd_min + 0.004·v`. Over-brake is about
  27% of the requested depth, and rate and speed add nothing.
- The worst case is 237 at 762 s: −3.5 requested, −5.98 delivered, at an onset of only 0.7 m/s³.
- Gas-to-brake onsets (previous command ≥ +0.3), n = 16, have the same median as the rest (−0.40
  against −0.38).

**3. The one group that looks different is too small to act on.** The 2-4 m/s³ band has 3 onsets,
2 of them 258's low-speed stop-and-go jolts:
- 63:50 at 7.7 m/s: −1.6 requested, −3.04 delivered;
- 2882 s at 2.4 m/s: −1.0 requested, −2.58 delivered.

There are 6 onsets below 10 m/s in total. Rule 5 applies: do not tune on a handful of points.

**Decision (Peter, 2026-09-23): leave it for now; it is a topic to revisit.** Onset-jerk limiting
(item 71 option 2) is not supported by this data. Compensating for the ECU's depth-proportional
over-delivery would lower brake commands and needs Peter's decision. If it is ever tried, it should
be behind a toggle that defaults off, after replay, and never applied to saturated or emergency
commands (item 71 option 3).

**To revisit:** collect low-speed stop-and-go rlogs until there are about 10 or more onsets below
10 m/s, then rerun `ob5.py` and `ob5sum.py` (in the `oprad-routes` volume at `/routes/an2`, not
committed). The question is whether low-speed gas-to-brake flips over-brake beyond the 27% depth
trend. If they do, retry option 2 there only.

Scripts (not committed, in the `/routes/an2` volume):
- `ob4.py`: plan, guard, lead and command trace.
- `ob5.py`, `ob5sum.py`: the onset census.
- The closed-loop replay is the item-64 `replay.py` plus a `CLC` env switch (`0` = cap off,
  `v<thr>` = off below thr m/s).

## 73. ICBM (formerly Redneck Cruise) on Honda Bosch stock long: Curve Speed Control now lowers the set speed, and the feature is renamed. Static and unit evidence only; not driven.

**What changed (d9b0aa313).** Ported the intent of sunnypilot's ICBM: under stock long with the
`RedneckCruise` param on, openpilot sends SCM_BUTTONS RES_ACCEL / DECEL_SET (0x296, ≤20 Hz) so
the car's own ACC set speed follows openpilot's target. Stock ACC still does all following and braking.

- `starpilot/common/starpilot_variables.py`: `honda_icbm_active()` (available ∧ not pcmCruiseSpeed ∧
  not openpilot long) and `curve_speed_controller_available()` (openpilot long **or** ICBM). CSC was
  previously hidden under stock long.
- `starpilot/controls/lib/starpilot_vcruise.py`: `csc_long_control_active()`. controlsd only sets
  `longActive` under openpilot long, so CSC used `controls_enabled ∧ ICBM` instead. This feeds only `csc_available`.
- UI label "Redneck Cruise" became "ICBM" and the description names Honda Bosch as well as Hyundai.
  **The param key `RedneckCruise` is unchanged**, which avoids a migration.

**Lead-aware target (existing behaviour, documented here).** `select_redneck_target_speed` in
`selfdrive/car/redneck_cruise.py` runs on Honda with no separate toggle. With a lead it holds the set speed while following,
coasts early when closing within 4 s headway (1 mph plus up to 3 mph, scaled by headway), and
steps up 1.25–3 mph when the lead departs. It is capped at the set speed, with a floor of 25 mph on Honda. It needs
`longitudinalPlan.hasLead` plus `radarState.leadOne`. Without radar dRel/vRel it only holds.

**Tests.** The new unit tests pass (`-n0`). 4 pre-existing failures (test_starpilot_card
`test_very_long_press…` and three in test_wheel_controlsd) fail identically on the pre-change tree.
The UI tests need pyray and were not run. ruff count unchanged at 63.

**Open, needs a stock-long drive.** (1) Confirm lead dRel/vRel reach radarState under stock long.
(2) Measure SCM_BUTTONS during a real driver long-press on +/− (5 mph steps) before any
hold-mode emulation is written. Injected frames interleave with the car's own frames, so they may register as taps.

**73a. The speed-limit confirm prompt now works under ICBM (static and unit evidence; not driven).**
`SpeedLimitController.handle_limit_change` accepted a + press only when `carControl.longActive`
was set, and longActive is never set under stock long. Under ICBM the "new speed limit" prompt could not be
accepted with +, and it never timed out either, because the 30 s auto-deny also needed longActive. The helper
`csc_long_control_active` moved to `starpilot_variables.icbm_long_control_active` and now gates
both CSC and SLC confirmation. Plain stock long without ICBM is unchanged. Test:
`test_icbm_accel_press_confirms_pending_limit`. To check on the drive: ICBM's own injected + presses must not register as
the driver's `accelPressed`. If they did, they would auto-accept prompts.

## 74. Route 0000025b (stock long, ICBM on, build e20a86641): long-press measured, an SLC set-speed grid bug fixed, 22:19 FCW was a real hard-braking lead. Replay (log decode) evidence; the fix is static and unit tested only.

Params (initData): RedneckCruise=1, BoschARadar=1, SpeedLimitController=1, CurveSpeedController=0.
CP: openpilotLongitudinalControl=False, pcmCruise=True. Route time is the qlog seg-0 t0. The driver's
bookmark clock reads ~10 s early (driver "3:18" is 3:28 here). Logs live under ~/r25b_work, not committed.

- **Stock long-press, measured (seg 3, 3:22–3:27).** The driver's SCM_BUTTONS (0x296) arrive on bus 1 at 25 Hz.
  A held −/+ is a continuous run of btn=3/4 frames. The car steps the set speed 5 mph about 0.63 s into the hold,
  e.g. 80→72 kph cluster (49.7→44.7 mph). ICBM's own frames (TX bus 1, ~17 Hz) interleave with the car's btn=0
  frames. A 0.85 s ICBM + burst at 3:20.0 moved the cluster 1 mph at a time (47.8→48.5→49.7), never 5. **Emulating
  a long press by injection is therefore not supported by this evidence.** ICBM presses did not appear as driver
  buttonEvents, so the driver's ceiling is not polluted by ICBM (the open check in 73a is answered).
- **Bug fixed: ICBM undid the driver's long-press −.** SLC had set vCruise to exactly 50 mph = 80.5 kph, which is off
  the 1.6 kph imperial grid. The long-press "partial interval" snap therefore moved vCruise only to 80.0 kph (49.7 mph),
  while the car went to 44.7. ICBM then pressed + at 3:23.19 and pulled the car back up (cluster 44.7→46.0), and again
  at 3:25.69. Fix in `VCruiseHelper._update_v_cruise_non_pcm`: an exact-mph value is mapped onto the grid before stepping,
  and `previous_v_cruise_kph` is taken before that mapping. Otherwise the SLC-crossing clamp would pin + presses at the limit.
  Tests: `test_long_decel_press_from_exact_slc_speed_steps_five_units` (fails before the fix) and
  `test_accel_press_from_exact_slc_speed_moves_above_it`.
- **The 22:19 FCW was real (seg 22).** The lead was first seen by vision at 92 m, and radar took it at 50 m, closing 7–8 m/s.
  The lead then braked hard: vLead 14.9→7.0 m/s over ~2 s, aLeadK down to −5.3. Stock ACC was already braking
  (−2.3 at 22:19.25, peak −4.1) before openpilot's FCW fired at 22:19.81 (d 30 m, vRel −10). The car raised no FCW
  because its own ACC had the event in hand. Minimum gap was ~21 m at 14 m/s. Radar and model range agreed within 1–3 m throughout.
- **Radar coverage under stock long.** qlog: 1,989 of 2,789 leadOne frames are radar-sourced. In rlog segs
  13/21/22, radar supplied 94/93/96% of frames where the model had a lead ≥0.7 within 80 m. Seg 13 radar reads a median 8.6 m
  shorter than the model, which is the known vision-long bias.
- **To look at: seg 15, 15:33–15:36.** Stock ACC braked at −3 m/s² for a closing lead (vision ~100 m, vRel −11) that
  never became a radar lead in radarState and was dropped at 15:35. The car's own radar acted on it and Bosch-A did not
  publish it. Not investigated further (parser replay needed).

**74a. Speed-limit prompts on 0000025b, and − now really denies (static and unit evidence; not driven).** The car ran
e20a86641, which predates 73a. Prompt 1 at 11:15 (50→35): + at 11:17.96 and 11:19.80 was ignored (the 73a bug).
− at 11:22.32 cleared the prompt, **but SLC adopted 35 anyway**. `handle_limit_change` stores `denied_target` and
nothing ever read it, so on the next frame the no-change branch took the denied limit as the target. Deny therefore behaved like accept. Fixed:
that branch now skips a limit matching `denied_target`. Test: `test_denied_lower_limit_is_not_adopted_on_following_frames`
(fails before the fix). Prompt 2 at 22:41 (45→40): + at 22:44.67 was ignored, and the prompt stayed up 49 s until a brake disengage
auto-accepted it, because the 30 s timeout also needed longActive (both fixed in 73a).

**74b. 0000025b seg 15, 15:33–15:35: the vision-only lead had no radar return to match (replay of the on-device liveTracks; not a gate rejection).**
Ego was about 24.3 m/s. (An earlier version of this note said 13.5; that was the vRel saturation rail, not ego speed.) Vision reported a lead at 107→89→101→99 m, vRel −8 to −11, modelProb 0.2–0.8. The distance was jumpy, and the lead was dropped at 15:35. liveTracks held 0–3 points, all at 83 m or closer, and all railed at vRel −13.5, which means closing at 13.5 m/s or more. Track 22 (y −1.5…−1.8, 83→42 m over 2 s) was probably a stationary in-path object. No track came within 30 m of the vision range, so radard had nothing to associate, and rad=0 is correct. No code change. Stock ACC braked to −3.4 m/s² from 15:34.0 (item 74c). Its target cannot be identified from these logs.

**74c. Open-loop replay: alpha long's planner on 25b's stock-long segments (3, 11, 13, 15, 21–23). Replay evidence only.**
Script: `/routes/an2/r25b/alpharp.py` (oprad-routes volume). It feeds the logged carState, radarState, modelV2, starpilotPlan and related messages into `LongitudinalPlanner` and compares `output_a_target` to the stock ACC's `aEgo`. **This is open loop:** ego follows stock ACC, so once the two diverge, the later alpha values are what alpha would command *from stock's state*. Episodes where either side went below −1.5 m/s²:

| Time | Stock ACC | Alpha plan | What happened |
|---|---|---|---|
| 11:01–11:05 | min −2.1, gentle | −3.43 at 11:02, −3.45 at 11:05 | The lead was cutting out (y 1.8→7.2 m). aLeadK swung −2.7 → +8.3 → −4.7, and alpha hard-braked on each swing. |
| 11:29–11:30 | ~0, never braked | **−3.45** | Real in-lane lead on a curve (see 74d; an earlier version of this row wrongly said two lanes over). MPC source was `cruise`; `get_close_lead_brake_cap` drove −3.45 from aLeadK −7.8 while vRel was only −1.5. |
| 13:18–13:21 | −1.7, onset 13:19.3 | −2.7, onset 13:18.4 | A real closing lead. Alpha started earlier and braked harder. |
| 15:34–15:36 | −3.4 | −0.3 | Vision-only lead (74b). Alpha did not brake. |
| 22:19–22:21 (FCW) | **−4.4, onset 22:19.0–22:19.2** | −0.4 from 22:18.0, then −3.49 (the cap) from 22:19.8 | A real hard-braking lead. Stock ramped about 0.6–0.8 s earlier and went past alpha's −3.5 floor. Alpha's step followed aLeadK, which reached −2.65 only at 22:19.8. |
| 22:33–22:37 | −2.7, onset 22:33.3 | −3.45, onset 22:34.1 | Slow closing at 28 m. Alpha started later, then braked harder. |

Takeaways (candidates, none implemented; (1) is withdrawn by 74d): (1) ~~lateral bound~~. (2) aLeadK on a cutting-out lead is noisy enough to trigger −3.4 bursts (11:02, 11:05). (3) On a real hard-braking lead, alpha's onset trails stock by ~0.7 s because it waits for aLeadK. Don't raise the −3.5 floor until (1) and (2) are fixed.

**74d. The 11:02, 11:05 and 11:29 alpha hard brakes on 0000025b are aLeadK-driven, not lateral mis-binding. Replay evidence; a lateral gate was tried and reverted.**
Instrumenting every `get_*` cap in the replay (`/routes/an2/r25b/who.py`) shows `get_close_lead_brake_cap` sets output −3.45 in all three cases; the later layers pass it through. `yRel` was large (−11…−14 m at 11:29, +7.2 at 11:05) because the road curved. Measured against `modelV2.position` at the lead's range (`off.py`), `dyPath` was 0.4–2.9 m at 11:29 and ≤1.3 m at 11:02–11:05. The vision lead sat at the same spot with p 0.65–0.99, so these were real in-lane cars. A draft that skipped this cap for radar leads with `|dyPath| ≥ 2.5` (STATUS 35's floor) changed **0 of 5,608** engaged frames on the replay. It was reverted without committing. The driver of the demand is aLeadK: −7.8 at 11:29 while vRel only moved −0.8 → −1.7 and was back to +3.2 within 1.5 s, and −2.7 → +8.3 → −4.7 at 11:02–11:05. In `required_decel = c²/2d + 0.7·aLeadK`, the aLeadK term is ~95% of the demand in these frames. Stock ACC (−0.5) did not react to any of them. Hypothesis, not tested: Bosch-A vRel is radial, and on a curve the bearing change feeds lateral motion into range-rate, which aLeadK differentiates. Next candidate is takeaway (2), bounding aLeadK's influence on this cap when vRel/range slope don't corroborate it. It needs the fleet hard-brake negative controls (items 23/35) before any change, because this cap also carries the genuine 000001e8 9:00 stop.

**74e. Off-axis radar leads: aLeadK is bounded once, at planner input, on Bosch-A Hondas. Replay evidence (open-loop planner) plus static unit tests; not road-validated.**
74d showed that bounding one cap changes nothing: ~20 planner sites and the MPC read `aLeadK`. `bound_off_axis_leads` (`longitudinal_planner.py`) now runs once at the top of `LongitudinalPlanner.update()`, only when `CP.carFingerprint in HONDA_BOSCH_A`. For a radar lead with bearing `|yRel|/dRel >= 0.12` and aLeadK below −1.5, the planner and the MPC see `aLeadK' = max(aLeadK, −max(1.5, −leadsV3[0].a[0] if vision p >= 0.5))`. Every other lead field is the original, and radarState and radard are untouched (D-041/D-042). The limit to Bosch-A is deliberate: the radial range-rate is measured Bosch-A behaviour, and other radars are unmeasured.

Replay, before vs after, hard-brake episodes (output aTarget < −2.5):

| Route | Episodes | Changed | Detail |
|---|---|---|---|
| 0000025b | 7 | 3 | 689.3 (11:29) −3.45 → −0.72; 692.2 −3.45 → −1.79 (both bearing 0.22–0.27, vision a ≥ −0.08, stock did not brake). 665.2: still −3.45, onset 1.5 s later (bearing 0.19, d 37.8, vRel −5.4, vision a −0.03; stock aEgo −0.26). 799.7, 1340.0, 1354.2 unchanged. |
| 00000245 | 3 | 1 | 40.7: −3.50 → −2.92, onset 0.9 s later (bearing 0.20, d 32.7, vRel −2.7, vision a −0.56; live alpha aEgo −1.78). 353–358 s unchanged. |
| 00000237 | 7 | 1 | 942.6: min −3.50 unchanged, onset 0.05 s earlier (bearing 0.116–0.119, printed rounded; the bound never applied, see 74g; aLeadK −6.6, vision a +0.03), so a false brake that another layer still carries. |
| 00000241, 23e, 236, 239, 232, 23b, 23a | 14 | 0 | 241's 257.4/338.1/356.0/588.4/606.2 unchanged. |

Total: 24 episodes, 5 changed, every one off-axis with vision a ≥ −0.56. Open items: 665.2 (25b) and 40.7 (245) are real closings that now start later, and stock ACC did not brake hard at 665.2 either. 237 942.6 is still a −3.5 false brake. The Bosch-A limit was re-checked on 25b: every frame is identical to the run without it (8,391/8,391). Tests: `test_longitudinal_planner.py` has 485 passing (477 before, plus 8 new covering the 25b 11:29 geometry, a straight lead, vision-corroborated −4/−6, low vision confidence, a centred 000001e8-like stop, vision-only and mild leads, and the Bosch-A limit).

**74f. Handoff: what 74e leaves open, and the stock-ACC data census (2026-09-23).**

*Where the 74e change lives.* `selfdrive/controls/lib/longitudinal_planner.py`: constants
`OFF_AXIS_LEAD_MIN_BEARING` (0.12 in 74e, 0.10 since 74g), `OFF_AXIS_LEAD_MAX_BRAKE` (1.5), `OFF_AXIS_LEAD_VISION_MIN_PROB` (0.5);
functions `off_axis_lead_a_lead`, `bound_off_axis_leads`, `uses_off_axis_lead_bound`; view classes
`_BoundedLead`, `_BoundedRadarState`, `_BoundedSubMaster`. `LongitudinalPlanner.__init__` sets
`self.bound_off_axis_radar_leads`, and `update()` swaps `sm` for the bounded view on its first line when it
is set. Because the MPC gets `sm['radarState']` from inside `update()`, the MPC sees the bound too.
`publish()` still reads the raw radarState (the stop-release guard); this is deliberate and not bounded.
Tests: the `test_off_axis_lead_*` tests at the end of `selfdrive/controls/tests/test_longitudinal_planner.py`.
The 74d attempt that bounded only `get_close_lead_brake_cap` changed no output frame, because later
stages (`get_honda_accord_stop_go_accel_target`, `get_vehicle_far_follow_slew_target`) pass −3.45 through
and ~20 other sites read aLeadK. Don't repeat it.

*Open items from 74e (replay evidence):*
1. 00000237 942.6: **resolved in 74g.** The note here was wrong: the bearing was 0.116–0.119, so the
   bound never applied; no other layer was involved.
2. 0000025b 665.2 and 00000245 40.7 are real closings that now start braking 1.5 s and 0.9 s later. Stock
   ACC did not brake hard at 665.2 (aEgo −0.26), so it isn't clearly a regression, but a curve drive with
   the fix should confirm it.
3. The bound's evidence is one car (HONDA_CIVIC_BOSCH, dongle 11c8fa231c0499ed). Treat it as limited
   until a road drive on curves with a lead confirms no late brakes.

*Stock-ACC census (Konik).* The user asked for how stock ACC picks its lead and sizes braking. Findings:
- Konik lists 400 routes for the account; 101 have rlogs. Konik's `platform` field is unreliable: 44 of
  the 101 are labelled `mock`, 25b among them. Don't filter on it; read `carParams` from the qlog instead.
- Reading the last `carParams` in segments 0–1 of all 101: 99 have `openpilotLongitudinalControl` true.
  Only **0000025b** (radar on) and **0000016e** (radarUnavailable, not engaged in segs 0–1) are stock long.
- So there is no stock-ACC rlog corpus beyond 25b. What 25b shows is in 74b–74d. Stock ignored the curve
  false alarms (≈0 to −0.5), braked −4.4 on the real 22:19 lead about 0.7 s earlier than alpha would, and
  braked −3.4 at 15:34 for a vision-only lead.
- Stock's internals (which object it follows, how it sizes braking) are inside the Bosch radar unit and
  are not in any log. Only its behaviour can be fitted: its commands and aEgo against radar tracks,
  vision leads and TTC. The car's ACC commands (CAN) are only in rlogs; qlogs carry aEgo, radarState
  and modelV2 at reduced rate, enough for a rough timing/strength fit only.
- The 179 qlog-only routes (≥ 3 segments) were checked the same way: 178 are openpilot long. The one
  stock route, **0000025a** (4 qlog segments, minutes before 25b), was never engaged in segs 0–1. So the
  account has no other stock-ACC driving on Konik at all, with or without rlogs.
- Next step for the study: a handful of stock-ACC drives, which upload with rlogs, covering: a lead
  in-lane on a curve, cut-ins/cut-outs, a hard-braking lead, a stopped car ahead, stop-and-go, and
  adjacent-lane passes on curves. Then fit stock onset and strength against closing speed, gap and TTC,
  and whether it ignores off-axis leads.

*How to reproduce the census.*
- List routes via `tools/konik_preflight.py`'s `plain_http` plus `_token`: `GET /v1/me/devices/`, then
  `GET /v1/devices/<dongle>/routes_segments?limit=400`. The Mac's system Python TLS (LibreSSL) fails the
  handshake with `requests`; `plain_http` falls back to curl.
- Fetch qlogs with `tools/konik_fetch.py --route 'DONGLE|ROUTE' --segments 0,1 --qlogs --out DIR`.
- Read `carParams.openpilotLongitudinalControl` in the `oprad-test:py312` container with
  `_LogFileReader`. The script is `/routes/stk/cpmode.py` in the `oprad-routes` volume.

*Replay tooling used for 74c–74e* (volume `oprad-routes`, `/routes/an2/r25b/`; not in the repo):
- `caprp.py <route>`: open-loop planner replay; env `TAG=before` sets `LP.OFF_AXIS_LEAD_MIN_BEARING=1e9`.
- `fleetcmp.py <routes>`: hard-brake episodes (aTarget < −2.5), before vs after.
- `who.py`: which `get_*` stage sets the output.
- Run with the repo mounted:
  `docker run --rm -e PYTHONPATH=/src/openpilot:/src -v $PWD:/src/openpilot:ro -v oprad-routes:/routes oprad-test:py312 python /routes/an2/r25b/<script>`.
- The fleet routes (25b, 245, 241, 23b, 23e, 237, 236, 239, 23a, 232) are archived to Drive
  (`~/.local/bin/oprad-routes retrieve <route>` before replaying).

**74g. 237 942.6 root cause and fix: the bearing threshold drops to 0.10. Replay evidence plus limited road evidence of the failure; the fix is not road-validated.**

*Root cause (replay; `who2.py` on seg 15).* The MPC originates the brake: `a_solution[3]` reaches −3.2 with
source `cruise`; the close-lead cap is 0, and `get_honda_accord_stop_go_accel_target` and
`get_vehicle_far_follow_slew_target` only pass it through. The radar lead's aLeadK falls −0.9 → −7.1 in
0.8 s while vRel swings +8 → −3 and vision a stays +0.03..+0.12. Its bearing |yRel|/dRel is 0.116–0.119,
just under 74e's 0.12, so the bound never applied. 74e/74f printed it rounded as "0.12".

*The lead is real and in-lane (replay; `off237.py`).* The lead sits 0–3 m from the model path
(`modelV2.position` at dRel) on a curve (steer 8.3–10°, v 18 m/s). The model sees the same car at x ≈ 85 m,
y ≈ −10 m, prob 0.6–0.8. This is the 74e failure (radial range-rate on a curve), not a ghost target. leadTwo
duplicates leadOne on and off.

*Correction: live alpha did brake (limited road evidence).* 74f/`fleetcmp.py` quoted aEgo −0.02 at 942.6.
That sample is before the actuator lag. The log (build fa262e0c7) shows accel −1.21 at 942.5, −2.00 at
942.75–943.0, aEgo −2.74 at 943.75, and 18.1 → 15.4 m/s, with no brake or gas pedal. This is an on-road
phantom brake, not only a replay artefact.

*Candidates, 10-route replay* (25b, 245, 241, 23b, 23e, 237, 236, 239, 23a, 232; 31 hard-brake episodes):
| variant | 237 942.6 | other hard-brake episodes changed | notable frame changes (> 0.3 m/s²) |
|---|---|---|---|
| (a) bearing 0.10 | −3.50 → +0.15 | none | 236 843.6: −1.57 → −1.16 (bearing 0.119, aLeadK −2.1, vision a −0.02 at p 1.0: same false pattern) |
| (b) far lead (d ≥ 70 m, vision p ≥ 0.5 and within 15 m) bounded regardless of bearing | −3.50 → +0.15 | none | 237 322.6: −1.00 → −0.53 on a straight-ahead far lead that vision confirms is braking (a −1.14, p 0.93) |

(b) softens a genuine brake, so (a) shipped. Protected episodes are identical under both (25b 799.7 / 1340 /
1354.2 at bearing ≤ 0.004; 245 352–358; 241 257.4 / 338.1 / 356.0 / 588.4 / 606.2). Other diffs are at
no-lead frames (236 1117, 2097) and follow from planner state diverging after an earlier change, not from
the bound firing there. The margin is thin: 237 at 943.5 reaches bearing 0.099 with aLeadK −2.8, which
0.10 misses, but the replay minimum there stays +0.08.

*Change.* `OFF_AXIS_LEAD_MIN_BEARING` 0.12 → 0.10, with the evidence in its comment. New test
`test_off_axis_lead_bound_covers_route_237_942_geometry`. 486 pass.

*Tooling added* (volume `/routes/an2/r25b/`; host copies in `/tmp/rp/`): `off237.py` (lead vs model path),
`act237.py` (logged carControl/aEgo), `protchk.py` (protected episodes per variant), `diffv.py` (frame
diffs per variant vs `after`). `caprp.py` takes `TAG=b10` and `TAG=far` (env `FAR`, default 70);
`fleetcmp.py` compares `before` against env `CMP` (default `after`). `/tmp/rp/fleet2.sh` runs tags in
parallel and skips existing outputs; run it with `TAGS="..."` from bash, because zsh doesn't word-split
an unquoted `$R`. Colima was resized to 4 CPU / 4 GiB (2026-09-23). At 2 GiB, 6 parallel replays were
OOM-killed; at 4 GiB, 3 run cleanly.

## 75. Curve Speed Control: the upstream learner is the default again, and James's slider is behind a "Manual Curve Scaling" toggle. Static and unit evidence only; not driven.

**What changed.** `starpilot/controls/lib/curve_speed_controller.py` is upstream StarPilot's learning
controller again, verbatim from merge base 249b03a3f5 (unchanged on `Dom`). It does curvature-bucketed learning,
override nudges, a RES-press cancel and far-field correction. James's single-slider static controller
(ba1530965) moved to `curve_speed_controller_static.py` as `StaticCurveSpeedController`. The new param
`CurveSpeedManualScaling` (BOOL, default **off**) picks between them. `StarPilotVCruise._select_csc_mode` swaps
controllers live, and on any switch it releases the cap and flushes the learner.
UI: the slider shows only when the toggle is on. The calibrated lat-accel readout, the progress readout and Reset show only when it is off
(both the device settings and the Galaxy).

**Behaviour change for current cars.** Default is now the learner, not the slider. To keep the old
behaviour, turn Manual Curve Scaling on.

**Upstream bug, not fixed (static evidence).** `_correct_far_field` clamps curvature at `MAX_CURVATURE=0.02`.
On a hairpin the `CSC_MAX_LATERAL_ACCEL` cap (14.1 m/s) therefore never undercuts the 25 mph
`CSC_MIN_SPEED` floor. Two upstream tests fail on `Dom` too. They are marked strict-xfail and no retune was done.

**Artifacts.** `params_pyx.so` and `libcommon.a` were rebuilt per the larch64 recipe. There are 825 keys, the new key reads False, and the modes are unchanged.
Tests: vcruise, both CSC suites and longitudinal_planner pass (xfails as above). Galaxy layout: 22 passed.
navigation_params: 40 passed (needs Pillow in the container).

## 76. ICBM never slowed for curves: two separate bugs, both fixed. Static and unit evidence only; not driven.

The user reported, from road driving, that ICBM still does not slow for curves after item 73. Reading the code found two independent
blocks. Either one alone would stop it.

1. **CSC never became available under stock long.** `csc_available` required
   `not is_manual_speed_control(sm)`, and that function is True whenever `carControl.longActive` is False.
   longActive is always False under stock long. d9b0aa313 fixed the `long_control_active` term but
   missed this one. The fix: `manual_speed_control = not long_control_active or is_user_overriding_longitudinal(sm)`,
   using the ICBM-aware `long_control_active`. This is identical to before whenever ICBM is off. The learner's
   `log_data` now takes this state too. Without it, the learner would treat every ICBM-held frame as
   driver-controlled and train on stock ACC's curve speeds, so it would learn to slow less.
2. **ICBM ignored the CSC target anyway.** `select_redneck_target_speed` uses `starpilotPlan.vCruise`
   only when the car has no set speed. Once the car had a set speed, ICBM followed that set speed or the SLC target. The plan-decrease path only applied with a lead, a stop, or a
   non-cruise source. New: card passes `cscSpeed` while `cscControllingSpeed` is true, and it is applied as a
   cap only (it can never raise the set speed).

Tests: `test_csc_slows_for_curve_under_icbm_stock_long` (both modes), `test_csc_stays_off_under_plain_stock_long`,
`test_learner_does_not_train_while_icbm_holds_speed`, and three in `test_redneck_cruise.py`.
`test_target_speed_coasts_before_closing_lead_plan_crosses_set_speed` fails identically at HEAD (pre-existing).

**To check on the next ICBM drive.** On a curve, `starpilotPlan.cscControllingSpeed` should go true, and
the car's set speed should step down toward `cscSpeed` through DECEL_SET presses. The CSC target is computed from
vEgo, while ICBM compares against cluster speed, so expect it to land ~1–2 mph under. The step rate is ICBM's
button rate, so a sharp late curve may still be entered fast. The learner starts empty, so
the first curves use its default lateral acceleration.

## 77. ICBM counter sync: the car only counts button frames with the right message counter, so ICBM steps slowly. Fix is behind `ICBMCounterSync` (default off). Replay (log decode) evidence for the cause; the fix is static and unit tested only, not driven.

**Finding (route 0000025b seg 3, 3:20–3:27).** The car's SCM_BUTTONS (0x296, bus 1) run at 25 Hz with a 2-bit COUNTER.
ICBM's frames (~17 Hz) used the packer's own free-running counter. Only 9 of 34 ICBM frames had counter = car's last + 1.
All 3 ICBM set-speed steps came right after **two consecutive in-sequence frames**. A lone in-sequence frame (205.685)
did nothing. The pair at 206.1 fell inside a driver long press and is not counted. So the ~2–2.5 mph/s ICBM rate is
counter luck, not the car's limit. n = 3 steps, so "two frames per press" is likely but not proven.

**Change.** `ICBMCounterSync` (Honda + ICBM only; Galaxy, advanced). `carstate` exposes `scm_buttons_counter`. The
carcontroller sends each press right after a new car frame carrying its counter + 1. A press lasts 2 car frames, then a release
of 2 (−) or 3 (+) frames, via `icbm_counter_sync_step`. Expected rate is ~6 steps/s (−) and ~5 steps/s (+). The cluster lags ~0.1–0.2 s,
so expect an overshoot of 1–2 steps. Off = the old path, unchanged. Params artifacts rebuilt (826 keys).
Tests: `opendbc_repo/opendbc/car/honda/tests/test_icbm_counter_sync.py`.

**Drive test.** On a straight road, let ICBM lower the set speed with the toggle off, then on. Compare mph/s and
overshoot, and check the car raised no fault and ignored no frames.

## 78. The CSC learner keeps recording while Manual Curve Scaling is on. Static and unit evidence only; not driven.

Before this, turning Manual Curve Scaling on (item 75) stopped the learner entirely. Only the slider controller ran, and
`csc_learned.log_data` was never called, so driving with LKAS only (cruise off) taught it nothing. Now, in manual mode,
`StarPilotVCruise.update` also calls `csc_learned.log_data` with the ICBM-aware manual-speed state. The slider still
sets the speed. The learner records only its usual training frames: cruise not engaged (or the driver overriding),
above CRUISING_SPEED, no tracked lead, in a curve, no blinker. Switching to manual no longer flushes the learner on the switch.
It never cleared learned data anyway; `reset()` only resets the speed target. The calibrated lat-accel readout, the progress
readout and Reset now show in both modes on device (the Galaxy already did). Tests:
`test_learner_keeps_recording_while_manual_scaling_is_on`.

## 79. Route 260 (ICBMCounterSync + CSC learner drive): sync works; ICBM now holds while the driver is on the gas. Limited road evidence for sync and CSC; the gas hold is static and unit evidence only.

Route `11c8fa231c0499ed/00000260--a95a0c44ab`, commit f3952d84c4. `ICBMCounterSync` was off at boot. The live toggle JSON
in `starpilotPlan` (≈1 Hz; the qlogs had dropped it) shows it **off in seg 5 and on from t≈360 s (seg 6)**. initData params are captured once at boot, so they
cannot show a toggle that changed mid-drive. Read the rlog toggle JSON instead.
- **Counter sync (rlog replay, segs 5/6/9/10):** synced TX frames carry car counter + 1 and land 40 ms apart, one pair per car
  frame slot, every 160 ms (decel) / 200 ms (accel). 173/188, 330/563 (the rest are 100 Hz CANCEL spam, btn=2), and 153/161
  in-sequence, against 144/520 by chance unsynced in seg 5. The set speed moves one step per pair. Clean bursts ran at
  4–6 steps/s (seg 9 42→25 in 2.9 s; seg 10 25→51 in 5.2 s), against ~2–3.7 mph/s unsynced in seg 5.
- **Overshoot:** it is 1 step. Under a CSC target that wobbles ±1 mph (seg 6 407–419 s, cscSpeed 38.1–40.9), ICBM walked the
  set speed 38↔40 every ~0.5 s while vEgo stayed 39.0–39.6. That is cosmetic, but it can be fixed with a ±1 deadband if it bothers the driver.
- **Bug found and fixed:** ICBM kept pressing while the driver held the gas. That was 105 of 636 synced presses in segs 6/9/10.
  `CC.cruiseControl.override` is only set under openpilot long (`controlsd.py`), so it is always False on stock ACC. On a Honda,
  DECEL/SET under gas snaps the set speed to vEgo: 39→25 mph at 14 mph (seg 6 371.3 s), and 29→32 while ICBM was decreasing
  (seg 9 541.9 s). `RedneckCruise._update_readiness` now also requires `not CS.gasPressed`. Presses resume after the
  pre-active delay once the gas is released. Tests: `selfdrive/car/tests/test_redneck_gas_override.py`.
- **CSC (limited road):** it controlled the speed in seg 6 (407–419 s, target 38–41 mph at curvature 0.005, learned lat accel
  1.62–1.67 m/s²). The driver cancelled it with RES+ at 419 s (`cscOverridden`). The learner trained in seg 11 during manual driving in
  curves (`cscTraining`, cruise off, curvature up to 0.021, lat accel 1.7–1.96). Manual Curve Scaling was off for the whole drive,
  so this route does not exercise item 78's manual-mode learning.

## 80. Auxiliary features ported from StarPilot `Dom` 79c61f479a (merge base 249b03a3f5). Static and unit evidence only; nothing here touches radar, radard, the planner or control code.

Ported the Galaxy web UI (tools, sentry push, dashboard, longitudinal-mode API), wheel controls and Bluetooth personality
actions, screen settings, favorites/radial menu, the SLC sources bubble and speed-limit pulse UI, the fleet-safety runner, the model
release scripts, `cereal/custom.capnp` (adds only `SteeringLimitInfo`, with the matching `libcereal.a`), and 849 params keys
(`libcommon.a` and `params_pyx.so` rebuilt; `AlwaysOnLateral` and `LeadInfo` keep our default "1").
- **Not ported (planner/SLC review later):** `selfdrived.py` (Dom's unified long mode relies on its planner setting
  `experimentalMode`), `selfdrive/car/card.py`/`cruise.py` changes, `pandad.py`, the Tesla preAP/coop tests, and the
  `fleet_safety` workflow. The Dom tests for those files were left out or reverted to ours: `test_coherent_mode_handoff.py` and
  `test_mode_review_regressions.py` (they read Dom's `selfdrived.update_events` through the AST), the Bluetooth test that
  runs `selfdrived.params_thread`, `test_cruise_speed.py` (resume keeps the previous software cruise speed; it needs Dom's `cruise.py`)
  and `test_redneck_cruise.py` (`openpilot_longitudinal_adjustment_active`; it needs Dom's `card.py`).
- **Galaxy personality profiles are gated off** (`PERSONALITY_PROFILES_ENABLED=false`). Our planner still reads the legacy
  CustomPersonalities sliders, not `LongitudinalPersonalityProfiles`.
- **Toggle derivation:** CE and Conditional Chill now come from `longitudinal_mode.read_mode_values` (a locked read of the
  same three params) and are forced off in safe mode. `toggle.experimental_mode` is new but has no consumer in our tree.
- **Tests (per file, each in its own process):** several Galaxy/UI tests stub `accel_profile`/`favorite_slots` in
  `sys.modules`, so a single-process run shows ~160 false import errors. Run the files one at a time, with `-p no:unraisableexception`
  (teardown ResourceWarnings from TemporaryDirectory). The remaining failures are one of three kinds:
  - **Test-image env:** pyray, node, flask, pywebpush, evdev and no GPU.
  - **Not in our opendbc:** Tesla HW1.
  - **Fails on Dom too:** `test_model_release` refresh-manifest ×2, whose mock returns a str from `find_hf`.
  - **Pre-existing at HEAD:** dashboard_stats ×2, wheel_controlsd ×3 (evdev), model_release sha ×1, and
    redneck `test_target_speed_coasts_before_closing_lead_plan_crosses_set_speed`.

  `test_longitudinal_planner.py` passes (486).

## 81. Speed Limit Controller ported from StarPilot Dom 79c61f479a, plus the gentler nav-turn braking. Static and unit evidence only; not driven.

Source: Dom commits 50a8d1abdb (rejected limit not auto-applied), 7222b29a88 (accepting a higher limit raises the set speed),
65c8581db3 (ghost confirmation fix, override simplification). Navigation code already matched Dom.

- **`speed_limit_controller.py` is Dom's**, plus one local line: `long_active` still goes through `icbm_long_control_active`
  so +/− accept or deny a limit, and the 30 s timeout runs, under ICBM stock long (73a).
- **Overrides (behaviour change, user-approved 2026-09-23).** Gas above the limit overrides only while the pedal is held.
  Raising the set speed above the limit overrides until the next posted limit that is lower, or at or above the set speed.
  Under ICBM (`redneck_cruise`), any driver +/− is a bidirectional override: − below the limit holds until the next sign.
  The `SLCOverride` manual / set-speed choice no longer changes behaviour. `allow_lower_override` is now just `redneck_cruise`
  in `card.py`, `starpilot_vcruise.py` and `starpilot_acceleration.py` (×2).
- **Confirmations.** +/− only accept or deny when a confirmation is required. Accepting a higher limit writes
  `SLCForceCruiseSpeed` (the `card.py` consumer was already in our tree), and the accepting press does not also start an override.
- **Denied limits.** Dom's `denied_same_limit` replaces our 74a fix. Our test
  `test_denied_lower_limit_is_not_adopted_on_following_frames` is kept and passes.
- **Vision source** no longer switches while the car is at a standstill.
- **SLC targets under 25 mph now apply** (the `CSC_MIN_SPEED` floor on the SLC target is gone, so 15/20 mph school zones take effect). CSC keeps its floor.
- **`NAV_TURN_COMFORT_DECEL` 1.25 → 0.45**: the nav-turn target starts lowering farther from the turn. Ported at the user's request.
- **Not ported:** Dom's `card.py` Tesla preAP and steering-limit publishing, and `cruise.py` `_uses_software_cruise`.

Tests (docker, one file per process): SLC 52 passed (Dom's file plus our 73a ICBM-accept and 74a denied tests), vcruise 94
(Dom's under-25 mph SLC and two nav-turn tests added), acceleration 27, cruise_speed 38, redneck_gas_override 2,
longitudinal_planner 486. Redneck: only the pre-existing coast test fails. `test_speed_limit_pulse` needs pyray (environment).

## 82. D-063 variant D (U11 rail bound up to 20 m/s, plus a D-059-style hold) is parked as a patch, not applied. Replay evidence only; not driven.

Patch: was `tools/bosch_a_variants/d063_variant_d.patch` (applied to `radar_interface.py` at this commit; the parser in the tree was unchanged). Superseded by item 90: the D'' refinement of this variant is now in the tree behind `BoschARailInterval` (default off) and the patch files are removed.
Variant D treats a U11 vRel at the -13.5 m/s rail as an interval reaching down to -20 m/s. The interval is used in the D-054 range
gate and the D-057 re-anchor. A sweep admitted only through that interval starts the D-059 hold, so vRel stays unmeasured until a fresh fit agrees.
- **Replay A/B against HEAD** (routes 25d, 25e, 25f, 260). Over-closing means a newly measured vRel that shows more than 3 m/s more closing than the next 1 s range slope. The reference rate is ~5%.

  | Route | Over-closing / new measured | Lost | Lead points lost | Notes |
  |---|---|---|---|---|
  | 25e | 12/55 | 7 | 0 | Track 59 lead restored from 79.5 m (34/38 measured) |
  | 25f | 19/47 | 1 | 0 | No lead points gained |
  | 25d | 0/0 | 0 | 0 | |
  | 260 | 0/0 | 5 | 0 | Losses are non-lead points at the rail, 25-31 m off-axis |
  | 261 (added 2026-09-23) | 0/0 | 0 | 0 | 50 points gained, 9 of them lead points, none newly measured |
  | 262 (added 2026-09-23) | 13/87 | 8 | 0 | Reference 12/242. Every over-closer is non-lead: track 9 at 52-62 m (U11 on the rail, range closing at 7-10 m/s) and track 52 at 88-92 m. The 8 lost are non-lead rail points at 84-86 m, 24-32 m off-axis. 2 in-path gains, not lead (track 2 at 144.3 s, 79 m) |

- **Over-closing sweeps.** Almost all come from three non-lead tracks at 60-81 m. In two of them U11 sat on the rail while the range
  closed at only about 10 m/s, so the rail is not always a lower bound on closing speed. The third (25f track 33) was a genuine unrailed U11 of -12.5
  against -9. There was also one lead sweep: 25e track 48 at 404.9 s, 36.5 m, vRel -1.7 while the range was opening at +2.8.
- **Variant E** added a two-sided fresh-fit hold for rail-admitted tracks. It changed none of the over-closers and cut track 59 to 29/38 measured,
  so it was dropped.
- **Decision (Peter, 2026-09-23):** not applied. The plan is to collect more stock-ACC routes with far, fast-closing leads (above 60 m and 13.5 m/s) and
  pull-aways, and replay D on each. D can go behind a default-off toggle for alpha-long testing only once replay shows 0 lost lead points
  and no lead sweep that over-closes.

## 83. Planner review of StarPilot Dom 79c61f479a: three small pieces ported. Static and unit evidence only; not driven.

- **Conditional mode reset.** When Conditional Experimental or Conditional Chill is not the active mode, the planner now calls `deactivate()`. That clears
  its hold timers and cached status. Before, it only flipped `experimental_mode`, so an old hold could briefly force the wrong mode when the mode was re-enabled.
  The published-mode hunk from Dom's `starpilot_planner.py` was not taken; it belongs to Dom's unified long mode, which was skipped in item 80.
- **Personality profiles now reach the planner.** When `CustomPersonalities` is on and the active personality's profile is enabled, `starpilot_following.py` takes
  its follow time from the profile and `starpilot_acceleration.py` takes max accel and the braking floor from it. The UI editor and toggles were already in the tree
  but had no effect. With `CustomPersonalities` off, both files behave as before. `CustomPersonalities` requires openpilot longitudinal.
  The SLC-shaped floor was moved into `_shape_min_accel_for_slc` (Dom's refactor, no behaviour change); our explanatory comments were kept.
- **AOL alerts** go through `update_aol_alerts` (Dom refactor, adds a Tesla pre-AP case).
- **Not ported:** the far-lead coast cap in `longitudinal_planner.py`. It caps braking at -0.2 m/s² for leads beyond 45 m with more than 8 s TTC.
  It acts directly on the radar lead's dRel and vLead, so it would confound radar testing. It trusts a closing-speed estimate that can be understated at range,
  and it depends on `inside_gap_closing_cap`, which our planner removed. The set-aside Dom tests in `.claude/dom_backup/` were dropped: they cover
  unported features (unified long mode, resume keeping software cruise speed, Tesla pre-AP).
- **Tests (docker, per file):** Dom's new `test_conditional_reentry` 13, `test_personality_following_profiles` 29, `test_personality_longitudinal_profiles` 15,
  `test_personality_transient_contract` 21, `test_preap_aol_alerts` 2 and `test_longitudinal_personality_profiles` 71 all pass. Existing suites also pass:
  acceleration 27 (fixture now supplies `selfdriveState`; Dom's copy has the same gap), conditional chill 19 and experimental 51, longitudinal_planner 486,
  vcruise 94, SLC 52. These failures are identical at HEAD: test_starpilot_planner 1, test_starpilot_card 1, Galaxy test_longitudinal_mode 59,
  and test_mode_consumer_interleavings 37 (unified long mode not ported).

## 84. ICBM launch mode and gas-release set speed (Peter asked for both, 2026-09-23). Static and unit evidence only; not driven.

**Why (limited road evidence).** Route `00000260--a95a0c44ab`. The car sat stopped from 8:28 to 8:38, set to 25 mph, with a target of 49.7 mph.
openpilot's auto-resume sent RES at 8:38.2 and the car moved at 8:39.3, but ICBM made no press until 8:51.0, the moment vEgo passed the
25.05 mph set speed. Meanwhile the lead pulled away from 8 m to 34 m. The cause is the lead-recovery branch of `select_redneck_target_speed`:
it raises the set speed only when `plan_speeds[0] > speedCluster`, and with a lead ahead the plan tracks vEgo, so it held at 25 mph.
Peter's reasoning: on stock ACC openpilot does not control longitudinal, and the car's own radar does the following. So a set speed of
40+ mph behind a stopped or slow lead does not close on the lead.

- **Launch mode** (`redneck_cruise.update_launch_state`, `card._get_redneck_target_speed`, stock-ACC path only).
  - After a full stop, once vEgo reaches 2 mph (gas released), the ICBM target becomes the cruise target, with no plan hold and no lead hold.
    SLC and CSC caps still apply.
  - It never starts while the car is stopped, so ICBM does not press RES+ at standstill; on a Honda that would resume the car by itself.
  - It ends when vEgo is within 2 mph of the target, when the car stops again, on any driver cruise button, or on disengage.
- **Gas-release set speed** (`VCruiseHelper._update_v_cruise_gas_release`, toggle `SetSpeedOnGasRelease`, **default ON**, ICBM cars only).
  - When the gas pedal is released with vEgo more than 1 mph above the set speed, openpilot's set speed becomes vEgo, rounded to a whole
    mph (exact conversion, as SLC stores it) or km/h. ICBM then walks the car's set speed up to it.
  - With an SLC limit active, the new set speed becomes SLC's persistent override (the existing ICBM bidirectional path), so SLC does not
    pull it back down to the limit. This is intended.
  - The toggle sits in the Galaxy under Developer, next to ICBM Counter Sync.
- **Artifacts.** `libcommon.a` and `params_pyx.so` were rebuilt with the larch64 recipe (`oprad-build:cy314`, sconsign cleared, hash changed).
  The key count went from 849 to 850, `SetSpeedOnGasRelease` is the only difference (checked with `all_keys()`), and the key reads True by default.
- **Tests (docker, per file):**
  - `test_redneck_cruise`: 7 new launch tests pass, including a card-level case (stock ACC, lead, cluster 25 mph, launch from 0 to 3 mph, target = 50 mph).
    `test_target_speed_coasts_before_closing_lead_plan_crosses_set_speed` fails identically at HEAD (pre-existing).
  - `test_cruise_speed` 42 (4 new), device settings layout 29, navigation params 45 and starpilot_variables 35 all pass.
- **Watch on the next drive:**
  - The set speed jumps to the target a second or two after launch, and ICBM presses RES+ steadily.
  - Stock ACC still follows the lead without surging.
  - After a gas overtake, the set speed lands on the release speed.

## 85. Dom's far-lead coast cap is parked behind `FarLeadCoastCap`, default off (Peter asked, 2026-09-23). Static and unit evidence only; not driven or replayed.

- **What it does when on.** `get_far_lead_coast_cap` in `longitudinal_planner.py` limits braking to -0.2 m/s² while the lead is at least 45 m away and beyond the desired gap
  by 6 m, reaching it would take 8 s or more, closing speed is above 0.5 m/s, ego speed is above 10 m/s and the lead is braking less than 0.35 m/s². It then releases to
  the normal planner. The function and constants are Dom's (79c61f479a), unchanged.
- **Gate.** On top of Dom's conditions (not experimental mode, no stop or red light or stop sign, no close-lead caps, panic bypass or departure veto), two differences:
  Dom also requires `inside_gap_closing_cap is None`, which our planner does not have. It is replaced by: no nearer second lead with status, and no active tracked-vision
  model brake floor. `desired_gap` is the planner's pre-brake headway gap, the same variable Dom used.
- **Toggle.** `FarLeadCoastCap` (BOOL, default "0", under Advanced Longitudinal Tuning, advanced tier), read as `toggle.far_lead_coast_cap` only when advanced
  longitudinal tuning is on (which requires openpilot longitudinal). With it off, the planner is unchanged. Artifacts rebuilt (oprad-build:cy314, /work mount):
  `all_keys()` 850 -> 851, adding only `FarLeadCoastCap`; `params_pyx.cpp` unchanged.
- **Before turning it on.** It trusts dRel/vLead at 45 m and beyond, where closing speed can read low (see D-063 / item 82). Replay it on routes with far, fast-closing leads
  first. Check that no case coasts into a TTC below 4 s or needs braking harder than the normal planner would have used.
- **Tests:** Dom's 4 cap tests plus a default-off check are added to test_longitudinal_planner (491 pass). Layout, Galaxy settings and variables suites pass. The known
  failures (test_dashboard_stats ×2, test_starpilot_planner ×1) also fail at HEAD.

## 86. ICBM gas release now sets a floor on the ICBM target, and launch hands back to lead following sooner (Peter approved both, 2026-09-23). Static, unit and open-loop replay evidence only; not driven.

**Why (limited road evidence, route `00000262--864cc3c6db`, build 314b85768).**
- **Gas release did nothing.** The STATUS 84 path compares vEgo with openpilot's v_cruise, which on ICBM is the 55 mph maximum rather than the set speed on the dash.
  At 1:29.3 Peter released the gas at 37 mph over a 24.9 mph set speed. Nothing changed, and stock ACC braked back to 32 mph.
- **Launch held too long.** At 3:43.8 the launch raised the set speed to 49.7 mph by 3:50, as intended. It then made no press for 36 s (until about 4:26)
  while the lead drove at 30-45 mph, because the launch only ended when vEgo came within 2 mph of the cruise target.

**Changes** (`redneck_cruise.py`, `card._get_redneck_target_speed`):
- **Gas-release floor** (`update_gas_release_floor`, same `SetSpeedOnGasRelease` toggle).
  - When the gas is released with vEgo more than 1 mph above the car's set speed (`cruiseState.speedCluster`), the ICBM target is held at
    or above the release speed, rounded to a whole mph or km/h.
  - The floor is capped by the cruise target (vCruise, SLC, CSC).
  - It clears on any driver cruise button, on the brake, on a stop and on disengage.
  - The old `VCruiseHelper` path stays. It only matters when the release is above the 55 mph maximum, where it raises that maximum.
- **Launch end.** The launch now also ends once the set speed has reached the launch target and vEgo has come within 2 mph of the normal
  (lead or plan) target. The existing exits are unchanged.

**Open-loop replay on 262.** The logged inputs were fed through the new `_get_redneck_target_speed`. The set speed in the log is the old
one, so the target is valid only up to the first divergence.
- **1:30:** the floor is 37 mph, so the target is 37, where the old target was about 33. A second release at 1:33 moves it to 38.
- **2:25.7:** the release at 35.8 mph was under the 41.6 mph set speed, so there is no floor, correctly. The drop to 33.6 there was normal lead following.
- **Launch:** it ends at 3:50.0. From then the target tracks the lead: 22.6, then 31 at 3:55, 37 at 4:05 and 44 at 4:19.

**Tests (docker, per file).**
- `test_redneck_cruise`: 8 new tests pass. The pre-existing failure `test_target_speed_coasts_before_closing_lead_plan_crosses_set_speed` also fails at HEAD.
- `test_cruise_speed`: all 42 pass.

**Watch on the next drive:**
- After an overtake on the gas, the set speed on the dash walks up to the release speed and stays there until a button or the brake.
- After a launch, once the set speed has jumped up, it comes back down to follow the lead within a few seconds.

## 87. ICBM gas snap: while the gas is held above the set speed, ICBM presses -/SET so the dash set speed jumps to vEgo (Peter approved, 2026-09-23). Static, unit and open-loop replay evidence only; not driven.

**Why (limited road evidence, route `00000263--b8afdda0eb`, build 5969cac4f, which has the STATUS 86 floor).** The floor works, but it
walks the set speed up at 1 mph per press only after the release, while stock ACC is already braking toward the old set speed.
- 13:44.0: release at 42.0 mph over a 26.1 mph set speed. The set speed reached 41 mph at 13:47.1 (3.1 s), and the car slowed from
  42.4 to 40.4 mph meanwhile (`ACCEL_COMMAND` down to -1.1).
- 7:28.1 (38.3 over 28.0) and 9:12.7 (43.7 over 33.6) took about 3 s the same way. Peter's report: "it will speed up very quickly
  from 25 to 40, I expected to be instantaneous".

**Change** (`redneck_cruise.want_gas_snap`, `RedneckCruise._gas_snap_button`, `card._get_redneck_target_speed`; `SetSpeedOnGasRelease`).
- While the gas is held, with vEgo more than 1 mph above the set speed and no higher than the cruise target (vCruise, SLC, CSC), ICBM sends
  DECEL_SET for 0.2 s every 0.6 s. On a Honda, -/SET under gas sets the set speed to vEgo (route 260 seg 9: 29 -> 32 mph).
- **It only raises the set speed.** Honda's set speed is never below 25 mph, so the snap needs vEgo > 26 mph. It never fires where
  -/SET would set 25 mph (route 260: 39 -> 25 at 14 mph).
- The pulses stop on the frame the gas is released, so a -/SET cannot land without gas, where it would lower the set speed by 1 mph.
  A cancel, a resume, a driver button, the brake or a disengage also stops it.
- A release after a snap starts the STATUS 86 floor even though the set speed is already close to vEgo, so the lead-hold target does not
  walk it back down.
- Above the cruise target there is no snap; the capped floor ramps as before.

**Open-loop replay on 263** (logged inputs; the logged set speed does not move, so this shows where it fires, not the closed loop):
it would fire in exactly the five gas-over-set episodes (0:13.6, 7:23.4, 7:25.0, 9:08.9, 13:39.2). Each ends on the release frame. No other snaps.

**Tests (docker, per file).** `test_redneck_cruise`: 6 new tests pass. The pre-existing failure
`test_target_speed_coasts_before_closing_lead_plan_crosses_set_speed` is unchanged.

**Watch on the next drive:**
- Pedal from 25 to 40 mph: the dash set speed follows within about half a second while the gas is still held, and there is no ramp after the release.
- Listen for a beep on each snap press. If -/SET under gas beeps, tell me and I'll lengthen the interval.

## 88. ICBM reads Honda's truncated km/h set speed as the right whole mph (Peter approved, 2026-09-23). Static and unit evidence only; not driven.

**Why (limited road evidence, route `00000263--b8afdda0eb` 10:05-10:27).** Honda's `ACC_HUD CRUISE_SPEED` is whole km/h, truncated, so a 54 mph set
speed arrives as 86 km/h = 53.4 mph and ICBM rounded it to 53. With a 54 mph target, ICBM pressed + (to 88 km/h = 55 mph), then - (back to 86),
about 40 presses in 5 s, with many presses the car ignored. This is the likeliest source of the dash beeps Peter reported.

**Change** (`RedneckCruise._update_calculations`): on a Honda in mph, add half a km/h (0.31 mph) before rounding the set speed. This recovers
the held mph for every set speed from 25 to 90 mph (unit test). Metric cars and other brands are unchanged.

**Tests (docker, per file).** `test_redneck_cruise`: 3 new tests pass. The pre-existing failure is unchanged.

**Watch on the next drive:** no +/- flicker of the dash set speed near a steady target, and fewer beeps.

## 89. All stock-ACC routes scanned for alpha-long readiness (25b, 25d, 25e, 25f, 260, 261, 262, 263). Replay evidence only; nothing driven.

Scanner: `scan.py` in the session tmp dir (not committed). Per radarState frame it joins carState, `leadOne` (with `radarTrackId`, `radar`, `measuredRadar`) and the car's own `ACC_CONTROL.ACCEL_COMMAND`, so the stock ACC acts as a second radar opinion. Braking driven by ICBM lowering the set speed is excluded (set >= vEgo - 0.5 m/s, vEgo > 2 m/s).

**Correction (added with item 103):** this entry first said ACC_CONTROL was read on bus 0. On this car it is on bus 1. The stock values in the table are real ACC_CONTROL data (25b 15:34.7 at -2.69 matches item 74), so the counts stand. `scan.py` was never committed, so which bus it actually read cannot be re-checked.

| Route (build) | cruise on | stock brake, no lead | hard-brake onsets / lead age < 1 s | closing lead, stock silent | dropouts < 2 s (cruise on) | radar->vision handoffs, step > 20 m | stops: lead held from |
|---|---|---|---|---|---|---|---|
| 25b (e20a866, 7 segs) | 282 s | 1.7 s (15:34.7, -2.69, 48 mph; item 74 case) | 2 / 1 (15:33.4, 92 m, -8.2, age 0.6 s) | 0 | 15 | 9, 2 | no stops |
| 25d (92a8c7a) | 408 s | 0 | 4 / 1 (1:45.7, 86 m, U11 rail, 50 mph, age 0.6 s) | 0 | 7 | 41, 1 | 30-111 m |
| 25e (92a8c7a) | 888 s | 0.6 s (16:45.4, mid-dropout) | 8 / 1 (16:41.4, 48 m, age 0.4 s) | 0 | 14 | 33, 7 | 29-90 m |
| 25f (817c6fb) | 893 s | 0 | 5 / 0 | 1 (2:44.6, 30 m, -7.2; driver disengaged 2 s later) | 29 | 23, 3 | 16-43 m |
| 260 (f3952d8) | 376 s | 1.3 s (10:59.1, -1.16, 39 mph) | 6 / 1 (9:30.6 cut-in at 26 m, age 0.0 s) | 0 | 5 | 25, 6 | 22 m |
| 261 (5047b96) | 546 s | 0 | 3 / 0 | 1 (6:53.3, 40 m, -11.3 unmeasured; driver disengaged 1 s later) | 10 | 9, 3 | 9 m |
| 262 (314b857) | 409 s | 0 | 2 / 0 | 0 | 10 | 16, 0 | 34-49 m |
| 263 (5969cac) | 955 s | 0 | 9 / 1 (6:17.4, 31 m, age 0.8 s) | 2 (6:18.2 24 m -9.3; 8:06.8 16 m -3.4) | 17 | 96, 43 | 28-105 m |

What it says:
- **The radar rarely misses what the car's own ACC brakes for.** Over 4,757 s of cruise, stock ACC braked harder than -0.5 with no lead in radarState for 3.6 s in total. The worst is the known item-74 case, 25b 15:33-15:36: the lead at 92 m (vRel -8.2) reached radarState 0.6 s before stock ACC started braking, then dropped for 1.7 s while stock braked to -2.69 at 48 mph (build e20a866, before D-054..D-063). The other is 260 10:59.1: the lead at 46 m vanished (radar -> vision at 88 m for 0.2 s -> nothing) while stock ACC braked -1.16 for 1.3 s, then stock accelerated again by 11:02, so the lead most likely left the lane. Of 37 hard-brake onsets, 36 had a lead in radarState; 4 had held it for under 1 s. 260 9:30.6 is a cut-in at 26 m acquired the same 50 ms stock ACC started braking.
- **Radar -> vision handoffs are the largest alpha-long risk.** When the radar lead drops for 0.1-9 s, the vision lead reads 25-30 m farther at 50-85 m (263 9:14-14:13: radar 53-56 m, vision 78-86 m, repeatedly; 25e 15:40.9: 91 -> 59 m for 2 s at 49 mph goes the other way). Under stock ACC this is invisible; under alpha long the planner sees the lead jump away and back. 263 had 96 handoffs in 955 s (one per 10 s), 43 with a step over 20 m; the other routes 9-41. Whether vision ranges the same car long or picks the next car is not known from the logs. The 42 s vision-only stretch at 263 14:32 is a standstill behind a stopped car at 3.6 m (radar minimum range) and is benign.
- **Dropouts** are short (median 0.2-0.35 s, max 1.95 s) and 90% return the same `radarTrackId`. Four happened during stock braking (263 6:16.6 at -2.25 is the one already noted in item 88's route review).
- **Closing lead with no stock braking** (possible phantom or overstated vRel): 4 episodes, all under 2 s, and in 25f 2:44.6 and 261 6:53.3 the driver disengaged within 2 s, so the situation was real. Not investigated further.
- **Stops:** every stop with cruise on had a lead; it was held continuously from 22-58 m (median per route) and seen stopped from about 10 m (25d: 19 m).
- **vRel vs range slope (lead only, measured, same track, 1 s ahead):** bias -0.1 to -0.4 m/s under 70 m with |error| > 3 m/s in 0-9% of frames; at 70-110 m the spread is 2.2-3.3 m/s and 11-20% exceed 3 m/s. 260 70-110 m reads +2.0 (vRel understates closing: 10:28-10:31, 89 m, vRel -7.8) and 261 above 110 m +2.0.

**Variant D' (D-063 rail interval only for tracks within 4 m of the path)** — never shipped as a patch; the replay module was the session's `ri_new6.py`. Same A/B as item 82 (over-closing = new measured vRel more than 3 m/s more closing than the next 1 s range slope):

| Route | D over-closing / lost | D' over-closing / lost | Lead points lost | Lead gains |
|---|---|---|---|---|
| 25e | 12/55, 7 | 12/52, 0 | 0 | unchanged (track 59 from 79.5 m, 34/38 measured) |
| 25f | 19/47, 1 | 19/47, 0 | 0 | none either way |
| 260 | 0/0, 5 | 0/0, 0 | 0 | none |
| 261 | 0/0, 0 | 0/0, 0 | 0 | unchanged |
| 262 | 13/87, 8 | 10/27, 0 | 0 | none |
| 263 | 0/23, 5 | 0/0, 0 | 0 | none (D's 23 new measured sweeps were all non-lead) |
| 25d | 0/0, 0 | 0/0, 0 | 0 | none |

D' removes every lost point (all were off-axis, 24-32 m) while keeping D's lead gains. The remaining over-closers are three non-lead tracks with U11 on the -13.5 rail while the range closed at 9-10 m/s (25e track 6 at 78-82 m, 25f track 33 at 60 m, 262 track 9 at 62 m), inside 4 m of the path, so an adjacent lane; and the single lead sweep 25e track 48 at 404.9 s (36.5 m, vRel -1.7 against +2.8) which D publishes where HEAD publishes nothing. **D'' (same, 2 m gate; was `tools/bosch_a_variants/d063_variant_d2_inpath.patch` on top of the variant D patch, now in the tree per item 90):** over-closing 1/35 (25e), 0/0 (25f), 0/2 (262); lost 0; lead gains identical (25e track 59 still 34/38 measured). The one remaining over-closer is the 25e track 48 lead sweep. So the adjacent-lane rail cases are gone and only the in-lane one is left.
Decision at the time of this item: not applied. D'' met item 82's bar except for that single lead sweep (a point HEAD does not publish at all); Peter then asked for it as a default-off toggle, which is item 90.

**Alpha-long watchlist for the first drive (limited road evidence for everything below):**
1. Lead jumping 25-30 m away and back at 50-85 m on a straight road at 40-55 mph: radar -> vision handoff. Expect a brief throttle then brake. Bookmark it; the fix is in radard's lead arbitration, not the radar.
2. Far fast closer above 70 m (25d 1:45.7 pattern): radar lead arrives 0.6 s before the car's own ACC brakes, with vRel on the rail. Alpha long will brake later or softer than stock did.
3. Cut-ins under 30 m: radar acquires them as fast as stock ACC (260 9:30.6). Stopped cars: seen stopped from about 10 m; held from 20-60 m.
4. Standstill: the radar has no return under ~4 m; the stopped lead is vision-only until the gap opens.
5. Stock ACC never braked for something the radar had not seen for more than 1.3 s; the reverse (a radar lead stock ignored) happened 4 times, each under 2 s.

## 90. D-063 variant D'' (U11 rail read as an interval, in-path tracks only) is in the tree behind `BoschARailInterval`, default off (Peter asked, 2026-09-23). Replay and unit evidence only; not driven.

**What shipped.** In `_update_bosch_a`, when the toggle is on and the track is within `BOSCH_A_RAIL_INTERVAL_MAX_Y_M = 2.0` of straight ahead, a U11 on the -13.5 m/s rail is read by the D-054 range gate and the D-057 re-anchor as the interval [-20, -13.5] m/s (`BOSCH_A_DIRECT_VREL_RAIL_BOUND_MPS`) instead of the exact rail value. A sweep admitted only because of the interval (`rail_admitted`) starts the D-059 hold, so vRel stays unmeasured until a fresh fit agrees. Published vRel is unchanged; only whether the lead is kept changes. Off-axis tracks and unrailed U11 use the exact gate exactly as before. With the toggle off, `exact_gate` is True for every sweep and the parser's gate arithmetic is the pre-D-063 code.

**Toggle.** `BoschARailInterval` (PERSISTENT BOOL, default 0) in `common/params_keys.h`; raylib row "Keep Fast-Closing Leads" in `selfdrive/ui/layouts/settings/starpilot/longitudinal.py` (Bosch A Radar rows, after Range-Derived Closing Speed); Galaxy entry in `starpilot/common/assets/device_settings_layout.json` under `AdvancedLongitudinalTune`, advanced tier, `requires_offroad`; `tools/StarPilot/feasibleparams.txt`. Read once in `RadarInterface.__init__` (`_bosch_a_rail_interval_enabled`), so a restart is needed after flipping it. New key, not a reuse of `RangeDerivedVrel`, so the car's existing toggle state does not turn it on.

**Artifacts.** `common/libcommon.a` and `common/params_pyx.so` rebuilt in `oprad-build:cy314` (recipe in item 85): 851 -> 852 keys, `BoschARailInterval` and `RangeDerivedVrel` both present under `Params(memory=True).all_keys()` in `oprad-test:py312`. Build-dirtied `panda/board/obj/*` restored, not committed.

**Evidence (replay only).** Item 89's D'' A/B: 7 routes, 0 lead points lost, lead gains identical to variant D (25e track 59 34/38 measured where HEAD went dark from 100 m to 41 m), over-closing 1/35 on 25e (the track 48 lead sweep, a point HEAD does not publish), 0 elsewhere. Unit: `test_rail_interval_gate_reads_rail_as_bound_only_when_asked` (interval helper rails/exact; the gate rejects 100 -> 80 m in 1 s at the rail under the exact reading and accepts it under the interval; 100 -> 74 m is rejected either way; an unrailed U11 is identical either way) and `test_rail_interval_toggle_default_off_and_read_at_startup`. `test_bosch_a_radar.py` + `test_device_settings_layout.py`: 144 passed. ruff: no new findings against HEAD on the edited files.

**`RangeDerivedVrel` (D-053) stays.** Peter asked whether it is still useful now that D'' exists. Scan of the 7 stock-ACC routes (all had the toggle on): the assist was active about 50 s of 3,857 s of lead time (25d 0.1 s, 25e 15.7 s, 25f 16.0 s, 260 1.5 s, 261 6.4 s, 262 1.1 s, 263 8.6 s), mostly at 60-125 m. On the real closers it did the job it was written for: 25f 7:59 (lead 100 -> 42 m in 6 s, stock ACC -1.6) the assist pulled vLead down about 1 s before U11 moved; 25e 7:06 (98 -> 82 m while U11 said receding) it read the closing at 35-44 mph against a true ~41. It is a different layer from D'' (D'' keeps the lead alive; D-053 publishes more closing on a lead that is alive), so both stay exposed. Watch item for alpha long: at range it overshoots (25f 7:59 vLead read ~14 mph where ~26 was true; the correction hit its 8 m/s cap).

**Removed.** `tools/bosch_a_variants/d063_variant_d.patch` and `d063_variant_d2_inpath.patch` (items 82 and 89): the code is in the tree.

**Not done.** No road drive. If Peter wants it for the alpha-long drive he must turn on Keep Fast-Closing Leads under Advanced Longitudinal Tuning and restart; it stays off otherwise.

## 91. D-063 (`BoschARailInterval`) replayed on all 22 alpha-long routes, toggle on vs off. Replay evidence only; nothing driven.

Peter asked (2026-09-23) whether the shipped toggle (item 90) had been tried on every earlier alpha-long route at the depth of the stock-ACC scans (items 82 and 89). Answer: it has now, and **the toggle should stay off** (its default). Two of the planner-level differences are in the wrong direction and one root cause is still unidentified.

**Method.** Two in-tree `RadarInterface` instances run off each route's logged CAN, one with `rail_interval=False` (A, the default) and one with `rail_interval=True` (B). Nothing else differs. The point-level census compares every sweep. Brake onsets come from openpilot's own ACC_CONTROL command as the panda echoed it on bus 1 (`can` src 129; these routes carry no camera copy of 0x1DF, so the parser had to be given the frames with the bus bit masked off). An onset is ACCEL_COMMAND crossing -0.8 with cruise engaged, no brake pedal and vEgo above 2 m/s; a hard episode is a crossing of -1.5. For every window where A and B disagreed near a brake, two real `LongitudinalPlanner` instances were run on the two radar states (same replay harness as item 89 a3, planner columns from 20 s of preroll), with hard crossings at -1.5 and -3.0 recorded because the -0.8 onset is often reached by vision alone.

**Point-level census, 22 alpha-long routes (231 through 258, plus 25d/25e for reference).** 407 567 sweeps, 461 brake onsets, 237 hard episodes. B loses **0** points and **0** lead points on every route. B publishes a new measured vRel on 6 routes (237, 23e, 246, 24d, 251, 258); the over-closing rate of those (vRel more than 3 m/s more closing than the next 1 s range slope) is 10/23 on 237, 12/21 on 24d, 14/37 on 251, 0 elsewhere. Every one of the 22 over-closers is a point sitting at the -13.5 rail while the range closed at 6-10 m/s, as item 82 found on route 262. Only two of them were the lead: 237 track 31 (765.1-766.2 s, 42 to 32 m) and 251 track 53 (539.0-540.4 s, 51 to 39 m). Lead-changing differences near a brake occurred on 2 routes (237, 25e); two more routes (245, 258) gained a non-lead rail point at -13.5 next to an onset and were checked anyway (identical planner output, both).

**Planner A/B on every candidate window** (t is seconds from the route's first message; "log" is what the car actually commanded):

| Route, window | Off (A) | On (B) | What changed |
|---|---|---|---|
| 237, 759-775 s | onset 765.06, -1.5 at 765.71, -3.0 at 766.31 | onset 764.51, -1.5 at 764.91, -3.0 at 765.46 | B takes track 31 as lead 1.2 s earlier, at 54 m with vRel at the -13.5 rail (vision said -6). B brakes 0.55-0.85 s earlier and harder; both saturate at -3.5 by 766.3; the log reached -3.5 at 766.16. Conservative direction. |
| 25e, 719-737 s | onset 724.31, -1.5 at 725.91, -3.0 at 726.11 | onset 725.11, -1.5 at 725.26, -3.0 at 725.41 | B gains track 59 at 79.5 m published **unmeasured with a stale +11.1 m/s** for 0.3 s (planner eased -0.80 to -0.55), then measured at the -13.5 rail; B then hard-brakes 0.65-0.7 s earlier than A. |
| 25e, 398-411 s | never below -0.58 (log -0.58) | -0.8 at 403.36, -1.5 at 403.56, **-3.45 held 403.9-404.9** | B publishes track 48 as lead at 35 m with vRel -13.5 for 1.5 s (1 measured sweep of 26; the range was *opening* at +0.8 m/s). A, the log and vision all held a lead at 38-44 m closing 1-3 m/s. **A spurious hard brake at 68 km/h with no threat.** Wrong direction. |
| 251, 532-547 s | -1.5 and -3.0 at 537.70 (log -3.5 at 537.85) | -1.5 and -3.0 at **540.55** | A and the log brake on a vision-only lead at 75 m closing 14.7 m/s. B holds track 53 as radar lead (77 m, -13.5, vision-confirmed) but the planner stays at the -1.0 cruise floor until the lead is 37.7 m away, 2.85 s later, at 21 m/s closing 12 m/s. **Under-braking.** Wrong direction; the planner rule that holds -1.0 for the radar lead but not for the vision lead has NOT been identified (FarLeadCoastCap is off and caps at -0.2; the CR-V catch-up cap is CR-V only). |
| 245, 38-46 s | identical | identical | non-lead rail point, no effect |
| 258, 3728-3736 s | identical | identical | non-lead rail point, no effect |

Validity: A matched the logged radarState lead on 95-99% of cycles in every window except 237 (42%), where the in-tree parser takes track 31 as lead from 765.7 s and the code driven that day kept the vision lead; A is the current default and is the right baseline.

**What this shows.** Point-level, D'' does what item 90 said: nothing lost, in-path rail points published at the rail. Planner-level, on 22 routes it changed braking in 4 windows: 2 earlier/harder brakes on real closing leads (fine), 1 spurious -3.45 hard brake on a coasting point carrying a stale -13.5 (25e 403 s), and 1 hard brake delayed by 2.85 s (251). The stale-vRel coast is the mechanism behind both 25e windows: with the interval on, the D-054 range gate passes a rail point whose direct vRel gate failed, and the coast branch publishes `last_trusted_vrel` (+11.1 or -13.5) as `measured=False`. That coast path is item 89 a2's open question and is brake-affecting; it needs Peter's OK before any change. The 251 hold needs a planner trace first.

**What this does not show.** Nothing was driven. The planner replay uses the logged model and car state, so B's earlier brakes never fed back into the scene. The 251 planner hold may also exist with the toggle off whenever the radar lead is the one at range; only the toggle-on case was hit in these windows.

**Recommendation.** Leave `BoschARailInterval` off. Before turning it on: fix the coast branch so a rail-interval admission cannot publish a stale vRel (publish the rail as a measured bound or drop to vision), trace the 251 -1.0 hold, then re-run this A/B (scripts: `ab11.py`, `census11.py`, `ympc63.py`, recipe in the route-analysis memory).

**Housekeeping.** Routes 231-258 were archived to Drive and their working copies deleted after the run; 25e-262 are still local for the next replay.

## 92. D-063 addendum: the rail-interval coast is bounded by a fresh range fit (behind `BoschARailInterval`, still default off). Replay evidence only; nothing driven.

Item 91 named the mechanism behind both 25e windows: with the interval on, the D-054 range gate passes a rail point whose direct vRel gate failed, and the two coast branches publish `last_trusted_vrel` verbatim as `measured=False`. Peter OK'd a brake-affecting fix on 2026-09-24 on the condition that it stays behind the toggle. This item is that fix and its replay.

**Change (`radar_interface.py`, `_bosch_a_coast_vrel`, `_bosch_a_fresh_range_rate`).** With the toggle off nothing changes: the coast publishes the last trusted vRel verbatim, the pre-D-063 behaviour. With the toggle on, the coasted vRel is clamped to within 3 m/s (`BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS`, the D-059 hold's own tolerance) of a least-squares range rate over the samples the coast itself has gathered: `rejoin_samples` first (the D-059 hold appends every sweep), else `inconsistent_run` (D-062 appends every inconsistent sweep). The fit needs the D-043 minimum window, 4 samples over 0.25 s; below that the coast is unchanged. `samples` is not used because D-062 freezes it during a coast, so a fit over it would be stale by construction. The point is always published (D-041/D-042). Four unit tests in `TestRailIntervalBoundsTheCoast` (rejoin hold bounded; off path verbatim; under 4 fresh samples unchanged; stale opening vRel on an inconsistent coast pulled toward the closing fit). 119 Bosch-A tests pass in Docker.

**Planner A/B, same six windows and harness as item 91 (`ympc63.py`), toggle on (B), before and after the fix.** A (toggle off) is unchanged in every window, as expected.

| Route, window | B before (item 91) | B after | Note |
|---|---|---|---|
| 25e, 398-411 s | -0.8 at 403.36, -1.5 at 403.56, **-3.45 held 403.9-404.9** | -0.8 at 403.36, -1.5 at 403.56, min **-2.39** at 404.06, -3.0 never crossed | The 1 s hard brake is gone. The -1.5 tap remains (log and A never below -0.58). |
| 25e, 719-737 s | onset 725.11, -1.5 at 725.26, -3.0 at 725.41 | byte-identical | The +11.1 coast is a birth coast (track 59, 724.26-724.46, 0.2 s): no fresh samples exist yet, so the bound cannot act. |
| 237, 759-775 s | onset 764.51, -1.5 at 764.91, -3.0 at 765.46 | identical | baseline still 42% (item 91) |
| 251, 532-547 s | -1.5 and -3.0 at 540.55 | identical | the -1.0 hold is a planner question, not a coast one |
| 245, 258 | identical to A | identical to A | non-lead rail points |

**Why the 25e 403 tap remains (parser trace, track 48).** After the D-057 re-root at 403.313 the hold starts a fresh `rejoin_samples`; the fit exists from the 5th sweep (0.26 s later). Those 5 sweeps still coast the rail at -13.5 from 35 m, 5 planner cycles carry it, and the planner reaches -1.5 at 403.56 and bottoms at -2.39 at 404.06 while the clamp holds -2.0..-3.0 (fit about +0.9 m/s, 3 m/s tolerance). A takes the same track as lead at 404.96 and outputs -0.54.

**Why B admitted the walk at all.** The sweep at 402.912 was degraded (range sigma over threshold), so the D-054 gate was the 2 m one. A's residual was 2.32 m (reject); B's interval residual was 1.93 m (accept). The interval's 6.5 m/s of extra width times the 60 ms sweep is 0.39 m, and that tipped a degraded-gate decision. On a degraded sweep the interval is doing exactly what it was not meant to do: widen a gate that was tightened because the sweep was suspect.

**Recommendation.** `BoschARailInterval` stays off. The coast bound is kept behind it because it removes the one -3.0 crossing and changes nothing else in 22 routes' worth of windows. The next change to look at is the interval gate on degraded sweeps (use the exact rate, not the interval, when `degraded` is true). A shorter fresh window is not the answer: a one- or two-sample derivative is what D-043 forbids. Nothing in this item has been driven; the 25e -1.5 tap is a replay number.

**Housekeeping.** 237, 251, 245, 258 were retrieved for the run and deleted after it (archived on Drive). 25e deleted after this item.

## 93. Item B traced: the 251 "-1.0 hold" is the planner's ACC comfort floor, which only a vision-only lead can open. Replay evidence only; nothing changed in code.

Item 91 left one cause unidentified: with `BoschARailInterval` on, 251 (532-547 s) held aTarget at exactly -1.0 for 2.85 s while a radar lead closed at 12-15 m/s, and the toggle-off run braked -3.5 at 537.70. A `sys.settrace` dump of every numeric local of `LongitudinalPlanner.update` at its return, per cycle, both variants, 535-541 s (`trace251.py`, outputs `trace251_A.txt`/`trace251_B.txt` in `/routes/an2`) answers it.

**What the two variants computed at 538.40 s (lead 62.5 m, closing 16 m/s, vEgo 23 m/s, ACC mode).**

| Local | A (toggle off, lead = vision, `radar=False`) | B (toggle on, lead = radar track 53, `radar=True`) |
|---|---|---|
| `output_a_target_mpc` (the MPC's own request) | -5.684 | -5.684 |
| `accel_limits_turns[0]` (starpilotPlan floor, forced to <= -1.0 by `A_CRUISE_MIN` with a closing lead) | -1.000 | -1.000 |
| `slow_stop_cap` (`get_vision_slow_stopped_lead_cap`) | -1.200 | None |
| `vision_brake_cap_active` | True | False |
| `output_accel_min` (the clip floor at `:3096`) | **-3.500** | **-1.000** |
| `output_a_target` | -3.500 | -1.000 |

The MPC wanted the same -5.7 in both. The planner clips its output to `output_accel_min`, which starts at the comfort floor (-1.0 here) and is opened to the vehicle minimum (-3.5) in exactly one place, `:3041`, when `vision_brake_cap_active` is set. That flag is set only by `get_vision_slow_stopped_lead_cap` and `get_vision_low_speed_stop_buffer_cap`, and the first line of the slow-stopped cap is `if ... bool(getattr(lead, "radar", False)): return None`. So with a radar-tracked lead in ACC mode the MPC's request is clipped at the comfort floor; with the same scene seen as a vision-only lead, the -1.2 vision cap's side effect opens the floor and the -5.7 request passes through, clipped to -3.5. The cap that was designed as a gentle -1.2 limit is what releases the hard brake.

**What released B at 540.55 s.** Not the lead distance. The logged `selfdriveState.experimentalMode` flipped on at 540.6 (the car's own mode switch that day); `experimental_mlsim` then selects `get_vehicle_min_accel` (-3.5) as the comfort floor and the -5.7 request passes. Item 91's wording "until the lead is 37.7 m away" was the coincident distance, not the cause.

**What this means.** The hold is a planner property, independent of D-063: any radar-tracked lead in ACC (chill) mode is limited to the comfort floor until a vision cap fires or the mode flips. D-063 exposed it on 251 only because B made the closing lead a radar track that the toggle-off parser had left to vision. The car that day braked -3.5 at 537.85 on its vision lead (log lead `radar=False`), through the same vision path A took. Whether the toggle-off code hits this hold on real drives is a corpus question: cycles in ACC mode with `leadOne.radar` true, MPC request below -1.5, output pinned at the floor, and no vision cap. That scan has not been run. STATUS 42 and 61 (24f, 251 bookmarked brakes) reached -3.5 on the road, consistent with those brakes going through the vision path.

**Not done, and why.** No planner change. The floor and its release are longitudinal control invariants (retained for Claude per CLAUDE.md, brake-affecting, Peter's OK required), and the right fix is a design choice: let a radar lead open the floor the way a vision lead does (same TTC/closing-speed conditions, `radar` flag ignored), or drop the `radar` exclusion in the slow-stopped cap. Either would change braking on every alpha-long drive and needs the corpus scan first.

**Housekeeping.** 251 retrieved for the trace and deleted after (archived, unsynced=0).

## 94. ICBM far-lead target (`ICBMFarLead`, ships ON at the owner's request) replayed on 25e on vs off, plus the 662 press/step dump. Replay and unit evidence only; nothing driven.

Peter reported (route `11c8fa231c0499ed/0000025e--919b58ab81`): "if OP already detects a stopped lead from faraway, I would expect OP will command stock ACC to slow down." ICBM (`RedneckCruise`) does not brake; it walks the stock ACC set speed down with spoofed `SCM_BUTTONS` (address 662) decel presses, and stock ACC does the braking. Alpha long was off on 25e and experimental mode never came on.

**The three 25e episodes (replay, `icbmscan.py` / `icbmtl.py`).**

| Window | What happened | Why ICBM was late |
|---|---|---|
| 723-733 s | Vision-only lead at 102 m, vLead 14.7 m/s, closing 7.5 m/s. Planner `planMin` stayed at the set speed until 724.5 s (83 m); first decel press 724.5; set stepped 1 mph per ~0.5 s, stalled at 74 km/h from 726.1 to 727.9 with presses still going out; radar fused only at 28.6 m (728.0); stock ACC braked -3.5 from 726; Peter braked at 732.5 with a 4.8 m gap. | The chill MPC plan is ICBM's only lead input and does not slow for a far lead; then the ~2 steps/s walk. |
| 317-323 s | Same pattern, radar lead; the car's own ACC did the decel, the ICBM set never went below vEgo. | Same, plus the 25 mph floor. |
| 310.5-311.5 s | Radar lead at 96-101 m with vRel pinned at -13.50 for 3 cycles, then +0.45: 28 decel presses, 2 mph lost. | U11 rail (D-063); the planner itself also dipped 0.3 s later. |

**What changed (commits 5fdc433dc, afe003d7b).** `select_redneck_target_speed` takes `lead_speed_ms=None`. When the lead is closing (`vRel < -LEAD_CLOSING_REL_SPEED_MIN_MS`) and a speed was given, the target is capped at `get_far_lead_target_ms(d, vLead) = sqrt(vLead^2 + 2 * 1.5 * (d - max(6 m, 1.5 s * vLead)))`: the speed from which a 1.5 m/s^2 decel reaches the lead's speed at the desired gap. Every return of the plan block is wrapped in `min(..., far_lead_target)`, so the rule can only lower the target, never raise it, and `None` leaves the HEAD arithmetic byte-identical (replay: max difference 0.0 in all three windows). `card.py` passes `radarState.leadOne.vLead` only when the toggle is on. Toggle `ICBMFarLead` (Galaxy Developer Mode, "ICBM Far-Lead Slowdown (Honda, experimental)") ships **on** because Peter asked to try it on the next update; stock value off. Params artifacts rebuilt 852 → 853 keys (aarch64, hash checked, modes unchanged).

**Replay on 25e, toggle on vs off (`icbmfar.py`, set walk simulated at 1 mph per 0.5 s).**

| Window | Off | On |
|---|---|---|
| 723-733: first cycle with target below the set speed | 724.07 s (86.9 m) | 723.02 s (102.7 m, target 21.39 vs set 22.22 m/s) |
| simulated set at 726.0 / 728.0 / 730.0 s (m/s) | 20.43 / 18.65 / 16.86 | 19.54 / 17.75 / 15.96 |
| 317-323 | first below set at 316.93 s (79.1 m) | identical to off |
| 310.5-311.5 rail | set steps at 311.08 | one step earlier, 310.53 (target 16.8 vs planMin 18.6 while U11 is railed; from 310.83 the planner drops and on == off) |

The far lead brings the first press forward by 1.05 s and keeps the set about 2 mph lower through the whole slowdown. Both walks are limited by the ~2 steps/s press rate, not by the target (the on-target falls to 11 m/s by 726 while the simulated set is still 19.5 m/s). The rail case is the D-063 interaction: a pinned -13.50 makes the far lead pull one extra step; `BoschARailInterval` (off) is the mitigation, and the planner reacted to the same rail 0.3 s later on its own.

**662 press/step dump (`icbmcan.py`, `icbmclass.py`; windows 724-729, 306-309, 313-315).**

- (a) openpilot sends 662 continuously at 16.0 frames/s (gap median 60 ms, min 56, max 66, no gap over 120 ms): there are no press-release edges today. The car's own bus-1 662 runs at 25 frames/s with COUNTER cycling 0-3.
- (b) openpilot's COUNTER advances once per frame on its own clock. Classed against the car's last counter it repeats a fixed 8-frame pattern (other x4, next x2, dup x2) every 0.48 s, the beat between the two counter cycles (25/4 = 6.25 Hz vs 16.7/4 = 4.17 Hz).
- (c) The cluster set speed steps at most once per beat: 724-729 has 7 steps, each 0.07-0.19 s after a "next" pair, and every "next" pair produced a step except the three inside the 726.1-727.9 stall. 306-309 (accel presses): 6 steps in 6 of 7 beats. So the ~2 steps/s rate is locked to the counter beat, not to the frame rate, which says the car accepts a press only in one counter phase. `ICBMCounterSync` puts every frame in the "next" phase and should raise the rate; the bench test below measures it. The stall itself is not explained by counter class (three good pairs, no step); stock ACC was braking -3.5 during it, and whether the ECU freezes the set speed while it brakes is left to the bench test and road evidence.
- (d) A single ICBM press today is 6 frames (~0.36 s, 313-315) and yields exactly 1 step, the same as the 7 steps of the continuous 724-729 run per beat.

**Bench test for Peter (parked, ACC set, engine running, count cluster set-speed steps in 5 s).** Pattern A: today's continuous frames (toggle `ICBMCounterSync` off). Pattern B: `ICBMCounterSync` on. Pattern C: press-release taps (needs a test build, 3 frames on, 3 off). If the counter-phase reading is right, B >> A. If the ECU auto-repeats a held press, A ~10 and C ~25+. Record it as a route so the 662 frames are logged.

**Tests.** `test_redneck_cruise.py` (5 new: stopping-distance value, lowers target for a closing lead, `None` byte-identical, never raises the target, card toggle gate) + `test_device_settings_layout.py`: 91 passed, 1 failed (pre-existing, item 38 of the session notes: `test_target_speed_coasts_before_closing_lead_plan_crosses_set_speed` broke when the hold buffer went 0.5 → 1.5 mph in 50e1c1d37; retune the test or revert the band is Peter's call). ruff: no new findings vs HEAD.

**Not done.** No planner change, no hold-band change, no send-pattern change (Peter: change nothing else before the bench test). The stall cause is open. Nothing here has been driven.

**Housekeeping.** 25e verified (unsynced=0) and deleted from the volume after this item. A second copy `0000025e--919b58ab81o` exists in the volume from an unknown earlier run; left in place.

**Addendum (same day): the 726-728 stall coincides with an undocumented `ACC_CONTROL` (479) flag.** Replayed `carState` plus the car's own 479 frames at 0.1 s through the stall (`icbmstall.py`). The set speed (`cruiseState.speed` and `speedCluster` alike) froze at 20.56 m/s from 726.11 to 727.915 while decel presses kept going out at 16/s, vEgo fell from 20.3 to 14.3 m/s, aEgo ran -2.7 to -3.6, no pedal. The car's `ACCEL_COMMAND` went from -2.15 at 726.10 to a held -3.00 m/s^2 (726.6-727.5). Byte 6 of 479, which the Honda DBC does not name (bits 48-55 sit between `AEB_BRAKING` and `CHECKSUM`), read 0x00 before 726.10, 0x29 from 726.10 to 727.61, and 0x00 again at 727.70; the next accepted step came at 727.915, and both later steps landed with byte 6 at 0x00. One episode, so the reading is: **while the ACC ECU raises this flag during its own hard braking, it ignores set-speed presses.** Not the counter phase, not the hold band, not a floor. Worth checking on the next stock-ACC route with a hard self-brake: if byte 6 is 0x29 whenever the walk stalls, ICBM can stop wasting presses during it (and the cluster set speed will catch up as soon as the flag clears, as it did here).

## 95. Bench routes 264 and 265 (owner-driven A/B of `ICBMCounterSync`, held physical buttons, one slower-lead approach each). Limited road evidence, read back by replay; no code change.

**Routes.** `11c8fa231c0499ed/00000264--da75030df6` (drive A, 7 segments) and `11c8fa231c0499ed/00000265--28d99bed88` (drive B, 9 segments, seg 9 qlog only). The owner's `userBookmark` presses: 264 at 111.9 s, 136.1 s (the two hold tests) and 334.2 s (just after the lead approach); 265 at 64.6 s (just after the lead approach), 159.5 s and 197.7 s (the two hold tests). Both routes were verified against the archive and removed from the volume after this item.

**Which drive had counter sync on.** The boot-time `initData` params say 264 `ICBMCounterSync=1` and 265 `ICBMCounterSync=0`, the opposite of the owner's labels. The 662 traffic says the opposite of the params and agrees with the owner: 264 sends continuously at 16.7 frames/s with the free-running counter and the OOOONNDD class pattern of item 94 (window 318-334: 162 frames, classes other 81 / next 41 / dup 40); 265 sends in 2-frame bursts on a new car frame only, every frame in the `next` class (window 44-60: 90 frames, 90 `next`), which is exactly `icbm_counter_sync_step`. The toggle was flipped after boot on both drives, so `initData` shows the stale value (same trap as item 74's D-053). Credited by behaviour: **264 = sync off, 265 = sync on.**

**(a) Held physical SET- (the "5 s hold" tests).** Identical on both drives: the car's own SCM_BUTTONS held `decel_set` at 25 Hz and the ECU stepped the set speed **5 mph per repeat, one repeat every ~0.5 s**, 22.22 -> 20.00 -> 17.78 -> 15.56 -> 13.33 -> 11.11 m/s (50 -> 25 mph) in 2.5 s and then stopped at the 25 mph floor (264 at 126.5-128.5 s, 265 at 189.5-192.0 s). The "5 steps" count is floor-limited, not hold-limited: the hold ran longer than the walk. So the ECU's own auto-repeat is ~2 steps/s of 5 mph = ~10 mph/s, which is 5x the mph/s that ICBM gets from 1 mph presses at the item-94 rate.

**Held physical RES+ went badly on both drives, worse with sync.** The driver held `resume` from 11.11 m/s while ICBM was pressing `decel_set` against it (its own cruise target was still at the floor). 264 (sync off): the ECU stepped up 5 mph per ~1 s for 2.5 s (11.11 -> 17.78) while ICBM sent 16 decel presses/s, then ICBM flipped to `resume` at 104 s and walked the set on its own to 28.89 m/s (65 mph) by 113.5 s. 265 (sync on): ICBM's decel presses won against the driver's held button; the set reached 13.33 once, was knocked back to 12.78, 11.67, 11.11 within 3 s and never got above 30 mph while the driver held RES+ for ~4 s (155.5-160 s, ICBM 6 presses/step, cluster alternating 13.33 <-> 12.78 every 0.1 s). **With sync on, ICBM's presses beat the driver's own held button.** Open issue, not fixed here: ICBM keeps pressing against a physical hold instead of yielding to it. Needs a design decision (yield to any physical press for N s, or fold the ECU's 5 mph hold steps into ICBM's target) before it is touched; brake-affecting.

**(b) ICBM press-to-step rate, sync on vs off.**

| drive | send pattern | example run | steps/s |
|---|---|---|---|
| 264 sync off | continuous 16.7/s, counter free-running, OOOONNDD beat | 327.0 s btn=3, 4.0 s, 68 frames, 8 steps | ~2.0 (beat-locked, item 94) |
| 265 sync on | 2-frame bursts on a new car frame, all `next` class, 10-13 frames/s | 48.95 s btn=3, 3.0 s, 40 frames, 18 steps; 49.5-52.0 s set 24.44 -> 16.39 (18 steps in 2.5 s) | ~6-7 |

Every 2-frame `next` pair in 265 produced a step (`icbmclass2.py`, prior-frame listing per SET change). **Counter sync roughly triples the walk rate on the road**, from ~2 to ~6-7 steps/s of 1 mph. That is still slower than the ECU's own held-button repeat (~10 mph/s). Making `ICBMCounterSync` default on is the obvious next step and needs the owner's OK (brake-affecting, changes how fast the set drops on every lead).

**(c) Did `ICBMFarLead` fire on the slower-lead approaches? It fired but never mattered.** Replayed `select_redneck_target_speed` on the logged inputs with `lead_speed_ms` on and off (`icbmfar.py`, item 94's harness):

- 264 (325-332 s): the lead first appeared vision-only at 113.7 m with vLead 22.2 m/s (near ego), and the existing headway coast target went below the 24.44 set at that same sample (325.35 s) with or without the far-lead term. The far-lead target was lower than the old target only from 326.25 to 327.1 s (radar lead at 72 m closing 12 m/s, vLead 10.4: far-lead 16.6 vs old 21.8 m/s); the planner path (`planMin` 16.4) took over at 327.55 s. Decel presses were continuous throughout either way, and the set only reached 20.0 m/s by 331 s (8 steps in 5.5 s, beat-locked). Stock ACC did the braking (`aTarget` to -2.8, vEgo 22.4 -> 13.0). No behaviour change from the far-lead term on this approach; the walk rate was the limiter.
- 265 (46-58 s): the lead appeared vision-only at 108 m with vLead 18.0 and the headway coast fired at 46.97 s. The far-lead target was never below the old target anywhere in the window (max on-off difference 0.00 m/s). With sync the set went 24.44 -> 16.39 in 2.5 s, held 4 s at 16.39 while the lead ran 14.5-15 m/s at 75-87 m, then walked to 11.11 as the lead slowed to 7 m/s; stock ACC braked -3.4 at 50-51.5 s and -3.45 at 58.5-60 s (dRel 38 -> 27 m).

So on both approaches the lead entered the picture at ~110 m already at or below the 2 s headway coast threshold, and the kinematic far-lead target only undercuts the headway coast when a much slower lead is picked up much further out. The toggle stays on; this is not evidence for or against it, only evidence that it is harmless on these two approaches (limited road evidence, replay of the target function on logged inputs; the device itself ran with the toggle on).

**Side observation (radard).** In 264, `leadOne` alternated at 20 Hz between the vision-only track at ~100 m / 21 m/s and the radar track at ~70 m / 10.4 m/s from 326.2 to 326.6 s before settling on the radar track. Not analysed further here.

**Tools.** `$CLAUDE_JOB_DIR` scratch `icbmbench.py` (route census), `icbmclass2.py`; volume scripts `icbmcan.py`, `icbmtl.py`, `icbmfar.py` (`/routes/an2`, need `segt0_<route>.json` from `ympc63.seg_t0_map`).

**(d) Addendum, 265 at 1:38.8-1:53.6 (the owner's "radar locks onto a nonexistent lead at 1:48"). It was the vision model, not the radar, and it did not drive the car.** Read back after the route was retrieved again (`scan.py`, `rawslots.py`, a 662/`starpilotPlan` dump); replay evidence.

- **1:38.8-1:42.3: a third held physical SET-, not bookmarked.** The car's own SCM_BUTTONS held `decel_set` for 3.5 s; the ECU walked the set 22.2 -> 11.1 m/s in 5 mph steps (0.6 s apart) and stopped at the 25 mph floor at 1:41.8. Openpilot's own cruise target (`carState.vCruise`, `starpilotPlan.vCruise`) followed the same hold through `selfdrive/car/cruise.py`'s long-press logic all the way to **8 km/h (2.2 m/s)**, so ICBM's target sat at the floor and ICBM kept spoofing `decel_set` (src 129) until the disengage. Harmless here because the ECU would not go below 25 mph, but it is the target-side half of the held-button problem: after any hold >0.5 s openpilot's target and the ECU's set disagree by whatever the long-press logic subtracted.
- **1:40-1:53.6: the slowdown (22 -> 16 m/s, aEgo -0.4 to -0.5) was stock ACC settling toward the 25 mph set.** Openpilot longitudinal was off (`longControlState off`, `outAccel` 0). The owner braked at 1:53.6 (`pedalPressed`, `cruiseDisabled`).
- **The lead icon 1:41-1:52.5 was vision-only for all but 1.4 s.** `modelV2.leadsV3[0]` put a lead at 80-118 m (xStd 11-23 m) with prob 0.40 at 1:41.0, 0.94 at 1:42.0, 0.5-0.7 through 1:46, then 0.3-0.45 and flickering below 0.3 from 1:47.5 to 1:52.5. Its range never closed in 11 s while ego drove 16-22 m/s, which no real object at 100 m and 10-17 m/s could do: after 1:45 it is a ghost.
- **The radar had exactly one in-lane object in the window, and none at all from 1:45 to 1:53.** Slot 34 (y 0.1-1.5 m) at 130 m closing 3 m/s at 1:41, 112 m closing 5.7 m/s at 1:44.5, then gone; the parser published it as the radar lead for 1.4 s (1:43.3-1:44.7, tid 34, 118 -> 111 m, vLead 15). From 1:45.1 to 1:53.0 every sweep was `invalid_slots=16` (no valid objects). The only other point, slot 32, was 14-16 m to the side. **At 1:48.0 the radar reported nothing; the published lead was vision-only, prob 0.32, 105 m, xStd 16 m.**
- Reading: a real vehicle was ~120-130 m ahead at 1:41-1:44 (radar and vision agree, both closing), it then left the picture (turned off or out of range), and the model kept a fading lead at ~100 m for another 8 s. Nothing in radard or the parser locked onto it; the radar lead is exactly the 1.4 s it was measured. No action; it is the known far-vision behaviour, and it changed nothing the car did.


## 96. `ICBMCounterSync` ships on (d6f854f2e) and ICBM now yields to a held physical cruise button for the whole hold (D-065). Unit evidence only for the yield; the sync default rests on the item 95 bench drives. Brake-affecting; both at the owner's request; neither driven since.

**What changed.**
- `ICBMCounterSync` default flipped to on in `params_keys.h` (item 95: ~6-7 vs ~2 set-speed steps/s on the road). Params artifacts rebuilt; the built `.so` reports the default on. Stock openpilot has no such toggle, so "stock off" is nominal.
- `selfdrive/car/redneck_cruise.py`: `update_manual_button_timers` now keeps two counters per button, frames since the press edge (`cruise_button_held`) and frames since the release edge (`cruise_button_timers`). `manual_button_active` blocks ICBM while any button is held, capped at `MANUAL_BUTTON_HELD_MAX_S` (10 s, a missed-release guard), and for `MANUAL_BUTTON_INACTIVE_TIMER` (0.5 s) after the release. Before, the block ran only 0.5 s from the press edge, so a hold longer than that unblocked ICBM while the driver's finger was still down (264 at 101.5 s and 265 at 156.5 s: ICBM pressed decel against a held RES+, and with counter sync on it won), and a release unblocked it in the same frame.

**Evidence.** `selfdrive/car/tests/test_redneck_cruise.py`, 66 passed (was 63): held 3 s with no release edge gives `SEND_BUTTON_NONE` on every frame; release then gives `NONE` for 0.5 s and `INCREASE` after; a press with no release ever resumes after the 10 s cap. The pre-existing missed-release test was retuned to the cap. Nothing replayed (no route reproduces a held button through `RedneckCruise` offline without the car's response) and nothing driven.

**Open residual, seen on 265 at 1:38.8 (item 95(d)).** The target side is untouched: under a physical hold longer than 0.5 s, openpilot's own cruise target (`selfdrive/car/cruise.py` long-press logic, 5-unit steps every 50 frames) walks independently of the ECU's 5 mph auto-repeat, so after a long SET- hold the ECU set can sit at the 25 mph floor while `vCruise` reads 8 km/h and ICBM keeps pressing decel until the driver disengages. The yield fix stops ICBM fighting the hold itself; it does not reconcile the two targets afterwards. Folding the ECU's hold steps into the target is D-065's rejected alternative for now; a resync of `vCruise` to the cluster on release is the obvious next step if the owner sees the set stuck low after a hold.

**Ask of the owner.** On the next drive with counter sync on: hold RES+ and SET- for 3-5 s each while ICBM is active, bookmark each, and send the route. Expected: the cluster walks 5 mph per ~0.5 s with no ICBM press in the 662 log until 0.5 s after the release.

## 97. C4 (mici) UI: every lead marker carries its speed beneath it, adjacent-lane leads are drawn, and under ICBM the MAX box stays up showing the driver's own ceiling. UI only, not brake-affecting. Unit evidence (14 new tests); render check on a logged drive pending in the follow-up entry.

**Owner's ask.** The comma 3/3X UI shows several lead markers; the C4 showed one (occasionally two). He wants each marker's speed right under it, adjacent leads especially, behind the Developer UI. He also wants a persistent display of his own ICBM ceiling next to the road speed-limit sign.

**Why the C4 showed fewer markers.** `selfdrive/ui/mici/onroad/model_renderer.py` drew only `radarState.leadOne/leadTwo` and printed leadOne's speed once at top-centre (`LeadInfo`). The big UI (`selfdrive/ui/onroad/model_renderer.py`) also draws `starpilotRadarState.leadLeft/leadRight`, with metrics under each. radard only publishes leadLeft/leadRight when `adjacent_lead_tracking` is on (has radar AND `AdjacentLeadsUI`, which sits under `DeveloperWidgets` under `developer_ui = DeveloperUI or big_ui`) or with human lane changes (`starpilot_variables.py:1032,1059`, `radard.py:1021`). On the C3X `big_ui` switches it on. On the C4, `DeveloperUI` defaults off.

**Change.**
- mici `ModelRenderer`, when `multi_lead_ui_enabled()` holds (`DeveloperUI && DeveloperWidgets && AdjacentLeadsUI`, `selfdrive/ui/lib/starpilot_visuals.py`):
  - draws leadLeft (blue) and leadRight (purple) chevrons, placed like the big UI;
  - puts a speed label beneath every drawn marker (leadOne, leadTwo, left, right) in the configured units;
  - skips a label whose box would overlap one already drawn.
  - The top-centre `LeadInfo` text is unchanged.
- mici `HudRenderer`: when ICBM is active (`RedneckCruise` on, CarParams loaded, no openpilot longitudinal; `icbm_ceiling_active()`) and engaged, the MAX box stays visible (no 2.5 s fade) and shows `carState.vCruise`, which is the driver's ceiling that ICBM holds the stock setpoint under. Otherwise the behaviour is stock. No new params, so no params artifact rebuild.

**How to turn it on (C4).** Galaxy → Developer UI on. `DeveloperWidgets` and `AdjacentLeadsUI` already default on. The ICBM ceiling needs no toggle.

**Caveat: Developer UI on the C4 also changes a control input.** `conditional_chill_mode.py:330-347` `_adjacent_lead_ambiguous` reads leadLeft/leadRight. Switching Developer UI on therefore also turns on CCM's adjacent-lead veto on the C4. The C3X already runs with it through `big_ui`. Not changed here; the owner decides.

**Evidence.** Static/unit only.
- `selfdrive/ui/tests/test_mici_multi_lead.py`, 14 tests:
  - the three-toggle truth table;
  - the ICBM-ceiling predicate;
  - the overlay labels each drawn lead with its own speed, draws adjacent chevrons in their colours with a visible minimum alpha, and draws nothing adjacent without starpilotRadarState.
- UI suites (`selfdrive/ui/tests`, `selfdrive/ui/mici/tests`, under Xvfb in a raylib image): 500 passed.
- The 8 failures are identical to the pre-change baseline run on the same image: camera ROI, raylib_ui, soundd, theme, and mici camera cleanup. `test_aethergrid` was excluded because it segfaults drawing without a GL window, before and after the change.
- ruff clean.

## 98. STATUS 97 follow-up: the C4 UI rendered offline from logged route 265, and the lead speed label shrunk from 32 px to 20 px. Replay render evidence, UI only.
- **How it was rendered.** The real mici `AugmentedRoadView` was driven offscreen (raylib under Xvfb, `RECORD=1`) by a stub SubMaster fed from 265's rlogs. Toggles came from the logged initData params: Developer UI, DeveloperWidgets, AdjacentLeadsUI and RedneckCruise were all on during that drive.
  - The camera video was not in the route copy, so the background is flat.
  - `CameraView._render` was replaced with the same projection maths and no video.
  - The harness is scratch and is not committed.
- **Segment 3, about 180–200 s of its log time.**
  - A left-lane radar lead is drawn at the side of the path, labelled "47 mph" and then "44 mph".
  - While ICBM is engaged, the MAX box stays up at the driver's 50 mph ceiling beside the 50 speed-limit sign.
- **Segment 1, about 62–71 s.** The left "lead" was 17–20 m to the side and partly off-screen. That is plausibly not an adjacent-lane car; the display shows whatever radard publishes.
- **Label size.** At 32 px (13% of the 240 px screen) the label nearly matched the MAX text and ran into the wheel icon, as the owner noted ("a little big"). It is now 20 px with a 3 px gap.
- **Tests.** 14/14 multi-lead tests pass.

## 99. C4 MAX box drawn at 55% of stock size while ICBM holds it up. Replay render evidence, UI only.

- **What changed.** The owner asked for a smaller box ("maybe make it smaller"). While ICBM holds the box on screen it now draws at 55% of stock size (`ICBM_SET_SPEED_SCALE`, `set_speed_scale()` in `selfdrive/ui/mici/onroad/hud_renderer.py`). The number, the "MAX" text and the drop shadow all scale.
- **Unchanged.** For 2.5 s after the set speed changes, the box pops up at stock size, as it does without ICBM.
- **Render check.** Route 265, segment 3, 180–200 s, rendered offline. The compact 50 MAX shows between ceiling changes, and the full-size box shows right after each change.
- **Harness fix.** The offline harness now drives the UI clock (`rl.get_time`) from log time. Before, it read render wall time, so the length of the 2.5 s pop-up in the replay frames didn't match log time.
- **Tests.** The UI suite ran 505 passed and 7 failed. All 7 failures come from tests that were already failing before this change (camera ROI, soundd, theme, camera cleanup). 4 new `set_speed_scale` cases are included.

## 100. C4: the top-centre lead readout is hidden while the marker labels show lead speed. Unit evidence, UI only; not yet re-rendered.

- **What changed.** Owner: "remove the lead speed on top of the screen too no? isnt that too redundant?" The number at the top centre comes from the Lead Info toggle (`LeadInfo`, mode speed), and it repeats the speed label under the lead marker (STATUS 97). `show_top_lead_info()` in `selfdrive/ui/mici/onroad/model_renderer.py` now hides it when the multi-lead UI is on and Lead Info is set to speed.
- **Unchanged.** Distance mode still shows at the top, because the marker labels carry speed only. With the multi-lead UI off, the top readout behaves as before.
- **Tests.** 5 new cases. UI suite: 510 passed; the 7 failures come from tests that were already failing before this change.

## 101. C4: MAX folded into the speed-limit card. Replay render evidence, UI only.

- Peter asked (2026-09-24): "fit both the max and the speed limit in the current speed limit box, with the max speed being on top". He also said the compact MAX box spacing was "a little off".
- **Sign visible and ICBM holding the MAX:** the top-left box is not drawn. The speed-limit card grows by `MAX_BAND_HEIGHT` (72 px) and shows "MAX / 50", a divider, then the sign. This applies to US and Vienna signs. Gate: `combine_max_with_sign()` in `hud_renderer.py`.
- **No sign:** the compact 55% box (STATUS 99) stays top-left, with "MAX" now centred under the number and the gap closed.
- **Set-speed change:** for 2.5 s the stock full-size pop-up shows top-left, next to a plain sign. The card then takes the MAX back.
- **Evidence:** offline replay render of route 263, seg 3, 221–231 s, all three cases (card / no sign forced / pop-up forced). The same render confirms STATUS 100: the top-centre lead readout is gone. 4 new unit cases.
- **Fix from STATUS 100:** the attribute is read with `getattr` so that `test_lead_indicator`, which builds a bare `ModelRenderer`, passes again.
- **UI suite:** 513 passed. The same 7 pre-existing failures remain, plus `test_raylib_ui`. That test fails only inside the full suite; it passes alone 3/3. It runs offroad and never draws the HUD.
- Not seen on the device.

## 102. C4: MAX now fits inside the original speed-limit sign; side-lane markers are smaller and always labelled. Replay render evidence, UI only.

- **MAX in the sign** (+5 moved up 4 px on 2026-09-24 so its gap to 40 matches the other rows; measured from the render): Peter said the tall card from STATUS 101 "takes up a lot of real estate". He wants MAX and the speed limit to "all fit in that original square". The sign keeps its original size, 116×142, and draws a single "MAX 50" line on top with a divider below it. SPEED LIMIT / 40 / +5 are shrunk to fit underneath. A Vienna sign gets the same MAX line inside the circle. `MAX_BAND_HEIGHT` is gone. The gating and pop-up behaviour from STATUS 101 are unchanged.
- **Even spacing, no SPEED LIMIT words** (2026-09-24). Peter asked to "make sure everything is evenly spaced out" and was OK with dropping the words. The US combined sign no longer draws "SPEED LIMIT"; the sign shape carries that meaning. "MAX 50" stays, because it is the only thing that tells the two numbers apart. The limit number grows to 44 px, or 48 px with no offset. The rows are MAX line, divider, limit and +5. On a route 263 replay render, the gaps between them and to the inner border measure 24/24/24/23/25 px at 2×. The no-offset layout has not been rendered. Its numbers were derived from the same measurements.
- **Adjacent markers only for a car in the neighbouring lane** (2026-09-24). Peter asked that the side markers "only show up when there is an actual lead on that lane". radard's `leadLeft`/`leadRight` is the nearest moving track past our own lane line, and it has no outer bound. The UI now also requires the lead to sit between our lane line and the next one out (`lead_in_adjacent_lane` in `mici/onroad/model_renderer.py`), with a 0.5 m margin past the far line. When the far line has probability below 0.3, our own lane width, clipped to 3.0–4.5 m, stands in for it. On route 263 segments 2–5 this drops 14% of the adjacent-lead frames (L 459/3350, R 428/2943). The sampled drops sit 1.5 or more lanes out, and the render still marks the real neighbouring cars. radard is unchanged, because lane-change and chill-mode logic also read these fields. Replay evidence, UI only.
- **Side-lane markers:** Peter asked for "slightly smaller, with the speed label right below it".
  - The side markers now draw at `ADJACENT_LEAD_SCALE` (0.7) and their labels at 16 px. In-path markers stay at 20 px.
  - A side label that would overlap another label now slides outward, away from the centre, instead of being hidden.
  - In-path labels are still dropped on overlap.
- **Evidence:** offline replay of route 263, seg 3, 221–241 s. All three labels show in the sampled frames, where before the side labels were mostly hidden. 1 new unit test.
- **UI suite:** 514 passed. The same failures as STATUS 101 remain: 7 pre-existing, plus `test_raylib_ui`, which fails only in the full run and passes alone.
- Not seen on the device.

**Watch on the 2026-09-24 drive** (nothing below has been driven since it changed; bookmark each and send the route):
- **Brake-affecting, first road check (items 94, 96).** `ICBMFarLead` and `ICBMCounterSync` both ship on.
  - A stopped or much slower car seen far ahead should start the set speed walking down early, at about 6-7 steps/s, instead of waiting until radar fuses at around 30 m.
  - Hold RES+ and then SET- for 3-5 s each while ICBM is active. Expected: the cluster walks 5 mph per ~0.5 s, and ICBM does nothing until 0.5 s after the release.
  - After a long SET- hold, watch for the set speed getting stuck low with ICBM still pressing decel. That is the open residual in item 96.
- **Sign (item 102).** With ICBM holding MAX and a speed-limit sign up:
  - Check MAX, the divider, the limit and +5 are evenly spaced and readable at a glance.
  - Catch a sign with **no** offset. That layout has never been rendered.
  - Change the set speed: the stock pop-up should show top-left for about 2.5 s, then MAX folds back into the sign.
  - With no sign, the compact MAX box should sit top-left.
- **Side markers (item 102).**
  - A car genuinely in the next lane should get a marker. Watch for one going missing on curves, at merges or exits, or where the outer lane line is faint.
  - Nothing should be marked two lanes over or on the shoulder.
  - Side labels should sit under their marker and slide outward, not overlap.
- **Unchanged:** D-063 `BoschARailInterval` stays off unless you switch it on.

## 103. STATUS 74c open-loop alpha planner replay on the seven stock-ACC routes 25d–263. Replay evidence only; nothing driven, no code change to the planner.

The owner asked (2026-09-24) to rerun 74c on the newer stock-ACC routes. The question was whether alpha long would brake harder than stock ACC, or later than it.

**Tool.** `alpharp.py` only exists on the Mac, so this item rebuilds it as `tools/longitudinal/alpha_open_loop_replay.py` (7411fe9, 8a70d51).
- **Usage:** `python tools/longitudinal/alpha_open_loop_replay.py ROUTE_DIR [--threshold -1.5] [--json OUT]`. `ROUTE_DIR` is in the `tools/konik_fetch.py` layout, `<dir>/<seg>/rlog.zst`.
- **What it does:** each route's logged messages are fed into `LongitudinalPlanner` at 20 Hz. The planner's `output_a_target` is compared with stock ACC's `carState.aEgo` and with `ACC_CONTROL.ACCEL_COMMAND`.
- **Output:** every episode where any side goes below the threshold. For each episode the tool reports:
  - the minimum on each side;
  - the time each side first crosses −1.0, −1.5 and −2.5;
  - a lead trace;
  - how many frames the off-axis bound fired on.
- **Two planners** run side by side. `alpha` is the tree as shipped. `nobound` has `bound_off_axis_radar_leads=False`, the same as 74f's `TAG=before`.
- **Existing tools didn't cover this.** `score_route_longitudinal.py` does not compare against stock, and it crashes on `sm.all_checks` because it is handed a plain dict.

**Method and caveats.**
- **Open loop:** ego follows what stock ACC actually did, so alpha's output never feeds back into the gap. When alpha brakes earlier or harder than stock, the replay cannot show the gap it would have opened.
- **radarState** is the on-device log from each route's own build. The replay does not re-run radard. Planner code is at 6805d4a.
- **CarParams are flipped** to alpha long (`openpilotLongitudinalControl=True`, `pcmCruise=False`). These routes log `longControlState=off` throughout. The replay therefore synthesizes `pid` when `cruiseState.enabled and not brakePressed`, and `off` otherwise.
- **ACC_CONTROL (0x1DF) is on bus 1 on this car, not bus 0** as item 89 first wrote (item 89 now carries a correction). It is decoded with DBC `honda_civic_hatchback_ex_2017_can_generated`.
- **Standstill excluded:** `ACCEL_COMMAND` is held at −4.0 at standstill, so frames with vEgo ≤ 1.0 m/s are dropped.
- **Toggles:** `starpilotToggles` is empty on these builds, so defaults apply. BLoTv3 is read from `initData` and was True on every route. The off-axis bound was active on every route.
- **Episodes** merge within 3 s. Times are route time from `initData.logMonoTime`.
- **Lag** means alpha's crossing time minus stock's crossing time, at the same threshold. Positive means alpha trails. Ramp-start lag was also tried, but it moved by seconds on gentle pre-brake stretches, so it is not used.

**Routes** (dongle `11c8fa231c0499ed`). All are HONDA_CIVIC_BOSCH on stock ACC. Route data stays in the session scratchpad and is not committed.

| Route | Build | Engaged | Episodes < −1.5 |
|---|---|---|---|
| `0000025d--0a4208fba9` | 92a8c7a01 | 407 s | 4 |
| `0000025e--919b58ab81` | 92a8c7a01 | 887 s | 10 |
| `0000025f--ff78805bdc` | 817c6fb25 | 891 s | 11 |
| `00000260--a95a0c44ab` | f3952d84c | 372 s | 9 |
| `00000261--70d5276477` | 5047b9631 | 544 s | 5 |
| `00000262--864cc3c6db` | 314b85768 | 408 s | 5 |
| `00000263--b8afdda0eb` | 5969cac4f | 950 s | 12 (20 rlog segments; the API lists 21) |
| `0000025b--1f614c85d6` (segs 3, 11, 13, 15, 21–23 only; the 74c check) | e20a86641 | 272 s | 7 |

The 63 episodes split as follows:
- 41 where both sides went below −1.5;
- 18 alpha only;
- 4 stock only (one of these is alpha below −1.5 only with the bound off).

`konik_preflight.py` passed 6 of 6 checks before the fetch.

**The tool reproduces 74c on 25b.**
- **22:18.9 hard lead:**
  - Alpha crosses −1.5 at 22:19.7, and the command crossed it at 22:18.9, so alpha is **+0.8 s** late.
  - At −2.5 alpha is +0.6 s late against the command and +0.5 s against aEgo. This is 74c's ~0.7 s.
  - Stock went deeper: aEgo −4.40 and cmd −3.0, against alpha's floor of −3.48.
- **22:33.2:** alpha is +0.5 s late against the command.
- **15:33.7 vision-only lead (74b):** stock only. Cmd was −2.73 and aEgo −3.38, while alpha reached only −0.58.
- **11:29 off-axis lead:** −3.45 without the bound and −2.16 with it; stock was −0.6. This is the 74e case.
- **11:01:** the bound fired on 55 frames but alpha still reached −3.46, against stock aEgo −2.09.
- **13:17.8:** alpha reaches −3.45 against cmd −1.13. 74c had −2.7 here; the planner has changed since 74c.

### Hard-braking leads: the ~0.7 s trail does not reproduce on the newer builds

A hard-lead episode here means a vision lead with a ≤ −1.0 and a stock command below −2.0. Lag is alpha's −1.5 crossing minus the command's −1.5 crossing.

| Route | Time | Lag vs cmd | Alpha min | Cmd min | aEgo min |
|---|---|---|---|---|---|
| 25d | 1:46.2 | +0.2 s | −3.45 | −2.47 | −3.06 |
| 25e | 2:48.0 | +0.3 s | −3.62 | −2.22 | −2.86 |
| 25e | 6:09.2 | −0.5 s | −3.46 | −2.81 | −3.21 |
| 25e | 8:49.9 | −3.4 s | −3.42 | −2.15 | −2.41 |
| 25e | 12:05.5 | +0.2 s | −3.50 | **−4.00** | **−4.34** |
| 25e | 14:15.2 | +0.4 s | −3.48 | −2.62 | −3.40 |
| 25e | 15:47.0 | −0.4 s | −3.46 | −2.02 | −2.36 |
| 25f | 6:54.2 | +0.4 s | −3.73 | −2.92 | **−4.05** |
| 25f | 12:49.2 | −0.8 s | −3.45 | −2.64 | −3.07 |
| 260 | 9:30.6 | −0.5 s | −3.45 | −2.24 | −2.81 |
| 261 | 2:12.2 | −3.8 s | −3.48 | −2.99 | −3.35 |
| 262 | 2:42.3 | +0.1 s | −3.45 | −2.64 | −2.89 |
| 262 | 5:10.3 | −2.5 s | −3.00 | −2.29 | −2.65 |
| 263 | 6:14.3 | +0.3 s | −3.45 | −2.46 | −3.07 |
| 263 | 14:25.2 | −3.0 s | −3.47 | −2.04 | −2.41 |

- **Across all 17 hard-lead episodes** (including the two on 25b):
  - Against the command: median lag **+0.05 s**. The worst on the new routes is +0.4 s.
  - Against aEgo: median lag +0.30 s. The worst is +1.3 s, at 25e 2:48.0.
  - At −2.5 (n = 8): median −0.45 s. The worst is +0.6 s, and only on 25b.
- **Stock is deeper at the peak.** In three hard stops stock went below alpha's floor of about −3.45 to −3.73:
  - 25e 12:05.5: cmd −4.00, aEgo −4.34. This was a vision-only lead closing from about 100 m at vRel −7 to −15, with vision a ≈ −1.2 to −1.4.
  - 25f 6:54.2: aEgo −4.05.
  - 25b 22:19: aEgo −4.40.

  This is replay only, and open loop. It does not say whether alpha's floor would have been enough.
- **25e 8:49.9 is not an off-axis case.** The lead was straight ahead (bearing ≤ 0.036). The 0.39 maximum bearing comes after the lead turned off. Alpha started 3.4 s ahead of stock.

### Off-axis leads on curves (the 74e/74g bound)

- 🔴 **25f 13:58.4: off-axis false brake just below the 0.10 threshold. The bound never fired.**
  - Alpha −3.45 (source `cruise`); stock cmd −0.49 and aEgo −0.73.
  - The radar lead sat at 49–61 m, y −4 to −6 m, bearing **0.078–0.101**, with steer about 12°.
  - aLeadK read −4.2 and −3.9 while vision a stayed at about 0.0 with p 0.99. The bound fired on **0** frames.
  - This is the same signature as 74g's 237 942.6. 74g's margin note (0.099 at 943.5) has now happened on a route.
  - `OFF_AXIS_LEAD_MIN_BEARING=0.10` would need to come down to about 0.075 to catch it. That is **not changed here**: lowering it also widens the bound onto real in-lane leads on curves. See 263 6:14.3 below. It needs its own negative-control pass before any change.
- 🟠 **260 9:07.8: the bound is only partly effective.**
  - Bearing 0.093–0.119, with y swinging −1.7 → +6.5 m and the lead flipping between radar and vision.
  - The bound fired on 9 frames: alpha −3.21 with it, −3.45 without. Stock cmd was −0.38.
  - The frames below 0.10 carry the brake.
- ✅ **25f 16:52.0: the bound worked.**
  - Bearing 0.11–0.128, aLeadK −5.1, vision a about +0.05.
  - The bound fired on 41 frames and took alpha from −1.81 to −0.89; stock was −0.4.
- ✅ **260 9:53.9: the bound fired on 7 frames,** −2.09 → −1.96. Stock cmd −1.09. Small effect.
- ✅ **263 6:14.3: a real hard lead cutting out on a curve.**
  - y +1.3 → −4.6 m, bearing up to 0.149, vision a about −1.5.
  - The bound fired on 9 frames and did **not** delay alpha: +0.3 s against the command, the same as the unbounded planner.
  - This is the negative control that any threshold change has to keep.
- **260 9:01.2 is not off-axis.** Bearing was 0.02. Track 35, which otherwise reads vRel about +1, had a single-sample spike of vRel −3.6 and aLeadK −3.7. Alpha went to −2.67; stock stayed at −0.30. The aLeadK filter passes a one-sample spike through to the planner.
- **260 6:03.4:** bearing 0.268 only after the event, as the lead leaves. Alpha is +0.1 s against the command.

### Alpha-only and stock-only episodes

- **Alpha is often much harsher than stock on ordinary slowdowns.** In 16 episodes alpha reached −3.1 to −3.48 while the stock command stayed above −2.0:
  - 25b 11:01.6, 13:17.8
  - 25d 9:35.2 (cmd −0.80)
  - 25e 1:28.6, 5:18.0, 9:15.8, 16:42.0
  - 25f 2:37.1, 8:02.6, 13:58.4
  - 260 5:53.9, 6:03.4, 9:07.8
  - 263 2:43.0, 13:21.1, 15:57.9

  Most are real leads that stock handled at −1.3 to −1.8. Alpha goes to the rail. In open loop that difference may partly close, because alpha would have opened the gap earlier. It is still the biggest feel difference between alpha and stock in this data.
- **Alpha only, no brake from stock** (worst first):
  - 25f 13:58.4 (off-axis, above)
  - 260 9:07.8 (off-axis, above)
  - 260 9:01.2 (aLeadK spike, above)
  - 25f 0:43.7: newly acquired lead at 61 m, vRel −11, vision a +0.1. Alpha −2.33; stock −0.5.
  - 262 1:30.3: alpha −2.28; cmd −1.19.
  - 263 0:13.4: vRel −11.1 with aLeadK +1.8/+7.6 and vision a +0.4. Alpha −2.06; stock cmd −0.95, aEgo +0.5.
  - 261 2:42.3: alpha −2.02.
  - 25b 23:05.4: alpha −1.95; stock −0.42.
  - 263 5:58.2 −1.93, 17:01.8 −1.92
  - 261 6:43.4 −1.77, 8:42.1 −1.64
  - 263 2:35.6 −1.57, 6:05.0 −1.53
  - 262 1:34.1 −1.56
  - 25f 6:09.1 −1.52
- **Stock only:**
  - 25b 15:33.7: vision-only lead (74b).
  - 260 10:59.6: lead lost. Stock cmd −1.16 and aEgo −1.57, while alpha stayed at −0.08. This is the item 89 case.
  - 25d 1:57.4: aEgo −1.60 on its own.
  - 25f 16:52.0: bounded, above.

**What this does not settle.**
- Everything here is open loop and uses on-device radarState from mixed builds. Nothing was driven.
- The 0.10 bearing threshold stays as it is. 25f 13:58.4 argues for lowering it; 263 6:14.3 is the case that would have to survive the change. Both need a closed-loop radard + planner pass before a number moves.

## 104. Closed-loop radar + planner replay of `OFF_AXIS_LEAD_MIN_BEARING` 0.10 vs 0.075 on 17 routes; 0.075 ships. Replay evidence only; brake-affecting; not driven.

The owner asked (2026-09-24) for the closed-loop pass that item 103 said had to come before the threshold moved, and to ship 0.075 if it passed.

**Pass criteria, fixed before the results were read.**
1. Replayed vs logged `leadOne.status` agrees on ≥ 99% of frames on every route.
2. No genuine-brake episode is softened by more than 0.3 m/s² or delayed by more than 0.2 s at the −1.5 crossing. An episode is genuine if the stock or live command goes below −2.0, or vision a ≤ −1.0. This includes 263 6:14.3 and the 74g protected episodes.
3. The targeted false brakes improve.

**Tool.** `tools/longitudinal/alpha_closed_loop_replay.py` (f1bc872).
- **Usage:** `python tools/longitudinal/alpha_closed_loop_replay.py ROUTE_DIR [--bearings 0.10,0.075] [--threshold -1.5] [--json OUT]`
- **"Closed loop" in item 36's sense:** the radar chain is re-run from logged CAN. The current Bosch-A `RadarInterface` feeds the current `RadarD`, which feeds radarState, which feeds `LongitudinalPlanner`.
- D-063 rail interval and D-053 range/vRel assist are off, as shipped.
- **Four planners** run side by side: `b0.1`, `b0.075`, `nobound`, and `logged` (the on-device radarState at 0.10).
- **Ego motion is still the logged motion.** The planner output never feeds back into the gap.
- Alpha-long routes use their logged controlsState. Stock routes use item 103's synthesized pid state and ACC_CONTROL on bus 1.
- Episodes and crossings are the same as in item 103.

**Validity.** `leadOne.status` agrees on 99.10–99.81% of frames on every route. Same-track agreement is lower, 60.8% (260) to 90.4% (23e), because the drives ran older parser builds than the tree. Status, radar flag and dRel (±1 m) agree well enough for episode-level comparison. Frame-level track identity does not.

| Route | Build | Episodes | status | radar | dRel ±1 m | track |
|---|---|---|---|---|---|---|
| `00000232--3a01619ce5` | 9984de885 | 19 | 99.81% | 96.3% | 94.1% | 65.4% |
| `00000236--60bfb34cb1` | fa262e0c7 | 31 | 99.48% | 95.1% | 89.1% | 82.7% |
| `00000237--77313c5a66` | fa262e0c7 | 20 | 99.35% | 92.3% | 84.3% | 74.1% |
| `00000239--d1cf55daa7` | fa262e0c7 | 7 | 99.66% | 99.1% | 93.9% | 83.3% |
| `0000023a--5c3a439dfc` | fa262e0c7 | 1 | 99.69% | 98.9% | 93.6% | 81.1% |
| `0000023b--7f6d4c1ba9` | 0756f8103 | 3 | 99.69% | 99.5% | 97.2% | 67.0% |
| `0000023e--9a40b07f55` | 0756f8103 | 31 | 99.50% | 99.4% | 96.2% | 90.4% |
| `00000241--7948e97423` | 9845e8775 | 8 | 99.46% | 99.2% | 92.3% | 83.3% |
| `00000245--1356bb0355` | 0dae515c5 | 13 | 99.70% | 99.5% | 96.2% | 89.3% |
| `0000025b--1f614c85d6` (item 103 segs) | e20a86641 | 11 | 99.19% | 99.1% | 86.9% | 71.6% |
| `0000025d--0a4208fba9` | 92a8c7a01 | 4 | 99.58% | 99.5% | 96.1% | 63.4% |
| `0000025e--919b58ab81` | 92a8c7a01 | 10 | 99.64% | 99.7% | 90.0% | 68.4% |
| `0000025f--ff78805bdc` | 817c6fb25 | 11 | 99.38% | 99.5% | 90.3% | 80.6% |
| `00000260--a95a0c44ab` | f3952d84c | 9 | 99.21% | 98.9% | 80.8% | 60.8% |
| `00000261--70d5276477` | 5047b9631 | 5 | 99.20% | 99.6% | 92.0% | 78.3% |
| `00000262--864cc3c6db` | 314b85768 | 5 | 99.10% | 99.5% | 94.9% | 85.6% |
| `00000263--b8afdda0eb` | 5969cac4f | 12 | 99.76% | 98.7% | 93.1% | 83.8% |

The first nine routes (232–245) are alpha-long drives; the last eight are stock ACC. All are on dongle `11c8fa231c0499ed`. Route data stays in the session scratchpad and is not committed.

**Result: 200 episodes; 2 changed, both false brakes; 0 of 125 genuine-brake episodes changed.**
- ✅ **25f 13:58.4**, the item 103 target:
  - b0.1 −3.45 → b0.075 **−1.22**. Stock cmd was −0.49 and aEgo −0.73; nobound and logged were both −3.45.
  - Bearing 0.078–0.101, aLeadK −3.4 to −4.2, vision a about 0.0 at p 0.99.
  - The bound fired on 0 frames at 0.10 and on 46 at 0.075.
- ✅ **260 9:07.8**, which item 103 found only partly bounded:
  - −3.20 → **−1.01**. Stock cmd was −0.38 and nobound −3.45.
  - The bound fired on 9 frames at 0.10 and on 17 at 0.075.
- **Negative controls, all unchanged** (Δmin 0.00, Δt 0.00 at −1.5):
  - **263 6:14.3:** −3.45 at both thresholds; cmd −2.46, aEgo −3.07. Bearing reaches 0.149 and the bound fires on 10 and 15 frames. Vision a −1.55 caps the bound at −1.55 (`max(1.5, vision_brake)`), so the brake survives.
  - **237 15:42.5** (74g target) is still bounded at both thresholds.
  - **245 0:40.4:** −2.93 at both.
  - **25b** 13:17.8, 22:18.9 and 22:33.2.
  - **241:** the 5:17.2 hard brake, where the bound fires on 1 frame at 0.10 and on 33 at 0.075. Output −2.84 vs −2.83; crossing unchanged.
  - **236 14:18.0:** 9 frames bounded at 0.075; output −3.50 at both.
  - **25e 12:05.5:** 3 frames bounded at 0.075; −3.50 at both.
- **Why the extra bounded frames on real brakes change nothing:** in each case either vision corroborates the lead's braking, which raises the cap, or aLeadK was not what set the output on those frames.

**Frame-level differences outside the two episodes** (|Δ| > 0.3 m/s² between b0.1 and b0.075). Each cluster was inspected frame by frame:
- **23e 23:47–23:52 (232 frames):**
  - No lead on any frame, and none below −0.3.
  - It is the post-disengage acceleration ramp: b0.075 +1.27 against b0.1 +0.84. b0.075 matches nobound and b0.1 matches logged.
  - This is MPC internal state carried from earlier on the route. A segments 22–23 subset replay gives identical variants.
- **260 10:08.6:** no lead, ego accelerating. b0.075 is 0.2–0.6 higher.
- **25e 16:28.4:** centred lead at bearing 0.01. b0.075 matches logged; b0.1 is −0.5 for two frames.
- **245 14:19.7:** bearing 0.001, one frame after a QP solver error. **b0.075 is lower** (−0.54 vs 0.00), the same as nobound.
- **241 4:23.0:** a lead 6 m to the side at 49–67 m, bearing 0.085–0.095, aLeadK −2.7 to −3.0, vision p 0.44 (so vision is ignored). The bound fires; b0.1 −0.31 → b0.075 0.00. Live alpha logged −0.25 and stock did not brake. Not a genuine brake.
- **25b 20:50.5 (17 frames):** inside an episode whose outcome did not move, −3.45 → −3.42.

**Shipped.**
- `OFF_AXIS_LEAD_MIN_BEARING` goes from 0.10 to **0.075** in `selfdrive/controls/lib/longitudinal_planner.py`. The comment block records the evidence.
- **New tests:** `test_off_axis_lead_bound_covers_route_25f_1358_geometry` and `test_off_axis_lead_bound_threshold_edge`. The second checks that bearing 0.070 is left alone and that a vision-corroborated −3.0 is kept at 0.078.
- `test_longitudinal_planner.py`: 493 passed. Ruff reports no new findings; the 9 on these two files predate this change.
- **Brake-affecting and not road-validated.** The evidence is replay only, with ego following the log. What to watch on the next drives:
  - curves with a lead 3–6 m off-centre at 40–70 m;
  - the item 102 checklist.

**Pre-existing, not caused by this change (found in the same pass).**
- ✅ **23e 4:54.6 (corrected on follow-up, same day): this is a live alpha false brake that the bound now removes, not a genuine brake it softens.** The first version of this entry had it the wrong way round.
  - **Why it was labelled genuine:** on the alpha-long routes, "cmd" is alpha's own logged command, not an independent stock reference. 23e ran build 0756f8103, which predates the 74e bound (f561b6f, 2026-09-23). On the drive the logged plan went to −2.83 and the command to −3.03, and the car reached −3.5.
  - **The lead was in our lane on a tight left curve.** Steer was +29°, radar y +9 m at 37 m, bearing 0.25. At the estimated turn radius of about 80 m, the arc puts the in-lane car roughly 8.3 m to the side, which matches. Vision agrees on the object (x 36–37 m, y −8.4, p 0.97–0.99).
  - **Radar and vision disagree about its speed:**
    - Radar lead speed (vEgo + vRel) goes 17.5 → 12.5 → 15.8 m/s over 294.0–297.0, and aLeadK reads −3.2.
    - Vision holds v 15.0–15.6 with a −0.03 to +0.14 throughout.
    - A real car does not shed 5 m/s and regain 3.3 m/s in 3 s. This is the 74e radial range-rate signature.
  - **What happened next:** after the brake the gap opened from 37 m to 44 m while vision's lead speed held. The driver pressed the brake at 295.8 (disengaging) and then the gas at 298.3 (`gasPressedOverride`). That is consistent with overriding an unwanted brake, but it does not prove it.
  - **Replay result:** the replayed current planner gives −1.21 against −2.45 without the bound, the same at both thresholds. The bound was doing its job.
  - **The labelling caveat is wider than this episode.** 23 of the 125 "genuine" episodes are genuine only because alpha's own command went below −2.0, with vision a above −1.0. Four had bounded frames: 236 14:18.0, 23e 4:54.6, 241 9:09.5 and 245 0:40.4. None changed between 0.10 and 0.075, so the ship decision stands. Future passes should label alpha-long episodes by vision or by an independent reference, not by alpha's own command.
- **241 4:56.0 and 237 18:38.6:** alpha is far shallower than cmd (−1.72 vs −3.24, −1.38 vs −2.60) at all four variants, including nobound. It is not the bound. It is on the item 103 "stock is deeper" list.

**What this does not settle.**
- Ego follows the log, so a softer planner's effect on the gap is not simulated.
- Mixed on-device builds explain the lower track agreement. Frame-level lead identity is not trustworthy for these routes.
- Nothing here was driven.

### 104a. Rerun with a vision-based genuine-brake label (same day). 0.075 stays. Replay evidence only; not driven.

The 23e 4:54.6 correction showed that the pass labelled alpha-long episodes as genuine brakes using alpha's own command. The owner asked for the episodes to be relabelled by vision and the pass rerun, with 0.075 reverted to 0.10 if any genuine episode changed.

**Tool change** (`alpha_closed_loop_replay.py`, bff8fa7).
- Each episode carries an independent reference built from `modelV2.leadsV3[0]`. It uses no radar and no planner output.
- The episode is genuine when, on ≥ 3 frames with p ≥ 0.5, either vision a ≤ −1.0 or the required deceleration reaches ≥ 2.0 m/s²:
  `req = max(0, −a_vis) + max(0, v_ego − v_vis)² / (2·max(x_vis − 4 m, 0.5))`
- On stock-ACC routes, a stock command below −2.0 also counts.
- Driver brake presses are reported but not used.
- The default `--bearings` is now `0.1,0.075` explicitly.

**Pass rule used.** An episode is **protected** if either label calls it genuine: the new vision/stock label, or the item 104 rule (any command < −2.0, or vision a ≤ −1.0 on any one frame). The new label under-counts on its own. On the stock routes it catches 19 of the 21 stock hard brakes. It misses:
- 25b 15:33.7, the 74b vision-only lead (stock −2.73, vision a −0.89);
- 25f 11:39.7 (stock −2.29, vision a −0.71).

It also drops alpha episodes that look real, e.g. 237 12:45.4 at aEgo −5.71 with vision a −0.94. So neither label is used alone.

**Result: 17 of 17 routes, 200 episodes; 125 protected; 0 protected episodes changed.**
- **Labels:** the new label calls 95 episodes genuine (52 alpha, 43 stock). The old rule called 125. 30 episodes are genuine under the old rule only, including 23e 4:54.6; none is genuine under the new rule only. The union is therefore the same 125.
- **The only two changed episodes are the targeted false brakes, as in item 104:**
  - 25f 13:58.4: −3.45 → −1.22. Stock −0.49, maximum required deceleration 0.1.
  - 260 9:07.8: −3.20 → −1.01. Stock −0.36, maximum required deceleration 0.3.
- **Genuine episodes where the bound fires, all unchanged** (Δmin ≤ 0.01, Δt 0.00):
  - 237 18:38.6
  - 23e 12:51.3
  - 241 4:56.0
  - 241 5:17.2 (1 → 33 bounded frames)
  - 25e 12:05.5 (0 → 3)
  - 260 9:53.9
  - 263 6:14.3 (10 → 15; required deceleration 2.6; vision a −1.55 keeps the cap at −1.55)
- **Determinism:** b0.1, b0.075 and nobound are bit-identical to the first run on all 200 episodes. Only `logged` moved, because it runs the shipped constant (0.10 then, 0.075 now). So the unpatched shipped planner on the on-device radarState now also gives 25f 13:58.4 −1.21 and 260 9:07.8 −1.01.
- **Tests on the shipped tree** (0.075), all passing:
  - `test_longitudinal_planner.py`: 493 passed.
  - `opendbc_repo/opendbc/car/honda/tests/`: 271 passed.
  - `test_radard_bosch`, `test_lead_behavior`, `test_lead_follow_policy`, `test_following_distance`, `test_turn_lead`: 129 passed.

  `OFF_AXIS_LEAD_MIN_BEARING` has one consumer (`off_axis_lead_a_lead`).

**Still open.**
- Neither label is a ground truth. Vision under-counts, and the old rule counts alpha's own brakes.
- Ego still follows the log.
- Nothing was driven.

### 104b. Item 104 in plain terms, and why no StarPilot setting changes it. Docs only; the settings finding is static code reading.

**The problem.** The radar sometimes reports that the car ahead is braking hard when it is not. This happens mostly when that car is off to one side, for example in the next lane or across a curve. At that angle the radar cannot reliably tell "that car is slowing down" from "my reading of that car jumped". Without a guard, the planner believes the bad reading and brakes hard for nothing.

**The guard.** `off_axis_lead_a_lead` measures how off-centre the lead is as `|yRel| / dRel`, called the bearing. When the bearing is at or above `OFF_AXIS_LEAD_MIN_BEARING`:
- the planner will not brake harder than −1.5 m/s² for that lead;
- the cap is lifted when the camera also sees the lead braking hard (vision `a`, probability ≥ 0.5).

So the guard only overrides the radar when the camera disagrees with it.

**The change.** The threshold went from 0.10 to 0.075. At 50 m ahead, a lead is now treated as off-centre once it is more than 3.75 m to the side, down from 5 m.

**Why.** At 25f 13:58.4 a lead sat at bearing 0.078–0.101, just under the old threshold.
- The radar said the lead was braking at −4.2 m/s². The camera, at probability 0.99, said about 0.
- In replay, alpha braked at −3.45. Stock ACC braked at −0.49.

**Evidence (replay only).**
- Of 200 brake episodes on 17 routes, 2 changed. Both were false brakes and both got gentler: 25f 13:58.4 −3.45 → −1.22, and 260 9:07.8 −3.20 → −1.01.
- None of the 125 genuine-brake episodes changed.
- 263 6:14.3 is a real hard stop with the lead well off-centre. It is unchanged because the camera saw that lead braking.

**Remaining risk.** A lead slightly off-centre brakes hard for real, and the camera misses it. The planner then brakes at only −1.5 until the camera or the driver catches up. No replayed episode showed this, and nothing has been driven. On the next drive, watch curves and multi-lane roads with a lead 3–6 m to the side at 40–70 m.

**No StarPilot setting changes this.** The owner asked whether StarPilot's lane-centering setting could compensate for off-centre leads. It cannot. Static reading of this tree:
- The bound reads the radar's `yRel` for the lead. That value is the lead's position relative to our car. `RadarD` takes it from the radar tracks.
- `LaneCentering` and `LaneCenterOffset` (clamped to ±0.3 m) only feed the lateral curvature in `controlsd.py` through `self.lane_centering.update`.
- `CameraOffset` shears the model input in `modeld`. It moves the camera's picture, not the radar's `yRel`.
- `NAPRadarOffset` is a Tesla pre-AP parameter and is not read on Honda.

Shifting our own car by 0.3 m in the lane would also move the bearing by only about 0.006 at 50 m. The off-centre cases the guard targets are 3–6 m to the side. The fix ships in the code on `ns-bosch-radar-testing`, and running that build is what applies it.

## 105. C4 lead speed labels enlarged: in-path 20 → 26 px, side-lane 16 → 22 px. Unit evidence, UI only; not rendered, not seen on the device.

- **Owner's ask** (2026-09-24, on-road photo of the C4 on a 45 mph arterial showing "13 mph", "13 mph", "38 mph" markers): "the speed labels are a little too small, can you make it a little bit bigger". A first step to 24/20 px (`16c4a731`) was followed by "go to 26 / 22" (`418a35c9`).
- **What changed.** `LEAD_LABEL_FONT_SIZE` 20 → 26 and `ADJACENT_LEAD_LABEL_FONT_SIZE` 16 → 22 in `selfdrive/ui/mici/onroad/model_renderer.py`. Side labels stay smaller than the in-path one (the test asserts it). Marker sizes, placement and the overlap rules from item 102 are unchanged. Item 98 had cut the label from 32 px to 20 px because 32 px "ran into the wheel icon"; 26 px sits between the two.
- **Evidence.** `selfdrive/ui/tests/test_mici_multi_lead.py`: 38 passed (Xvfb, Python 3.12, on `418a35c9`). ruff clean. The full UI suite was not run. No route render: this session had no route logs and no comma connect login.
- **Synthetic render instead (same day).** The real `_update_lead_vehicle` chevrons and `_draw_lead_label` were drawn at 536×240 under Xvfb, with the three markers placed as in the owner's photo. The 20/16 panel matches the photo's label sizes and positions. At 26/22 on that scene:
  - all three labels draw;
  - the right "38 mph" label slides outward and spans about x 344–418;
  - the speed-limit sign starts at about x 396, so that label now runs roughly 20 px into the sign. At 20/16 the photo already shows "mph" touching the sign edge.
  - Nothing reaches the wheel icon.

  The render script was scratch and is not committed.
- **Route render (same day).** Route `00000267--e83a1fa671` seg 16 was fetched from Konik: rlog plus qcamera.
  - Method: the real mici `ModelRenderer` was driven offscreen under Xvfb by a stub SubMaster, with toggles from the route's initData. The transform copies `AugmentedRoadView._calc_frame_matrix`, using mici os04c10 fcam 1344×760 with the qcamera stretched to it.
  - The HUD and speed-limit sign are **not** drawn. The harness is scratch and is not committed.
  - Checked at t = 7.9, 24.2, 30.2 and 43.1 s, at 20/16 vs 26/22:
    - 7.9 s: two close in-path leads (22 and 23 mph). At 26 px one in-path label is dropped by the overlap rule; at 20 px both showed.
    - 24.2 s: at 26/22 all three labels show (4 / 17 / 4 mph). At 20/16 the left one did not appear.
    - 30.2 and 43.1 s: fine at both sizes.
  - Replay render evidence, UI only.
  - qlogs carry no `modelV2`, so the render needs rlogs.
- **26/22 kept; side labels now avoid the speed-limit sign** (owner, 2026-09-24: "keep 26/22 and make side labels avoid the sign").
  - `HudRenderer.speed_limit_rect()` is the one source of the sign geometry: `_draw_speed_limit` draws from it, and `AugmentedRoadView` passes it to `ModelRenderer.set_side_label_obstacles()` after `prepare()` and before the model overlay.
  - A side-lane label that hits the sign or another label first slides outward. If that still collides or leaves the view, it slides inward. If neither fits, it is dropped.
  - In-path labels ignore the sign (unchanged: dropped only on overlap with another label).
  - Unit evidence: 4 new tests in `test_mici_multi_lead.py`, 42 passed. ruff clean on the changed files; the 2 E501 findings in `sidebar_widgets.py` pre-date this change.
  - **Rendered with the sign** (same day). The route harness now also runs the real mici `HudRenderer`: `prepare()`, then `speed_limit_rect()` passed to the labels, then `render_background()`. Route `00000267--e83a1fa671` seg 16:
    - 24.2 s: before, at 20/16, the right-lane "4 mph" label ran into the sign's "+5". Now it is dropped, because outward hits the sign and inward hits the in-path "17 mph". The left-lane and in-path labels still show.
    - 34.2 and 43.1 s: no conflict; all labels draw at 26/22.
  - **Below-sign fallback** (owner: "drop just below the sign"). When neither slide fits and one of the tried positions ran into the sign, the side label goes centred just below the sign (`_below_obstacle`). It is hidden only if that spot is taken or off-screen. A label boxed in only by other labels, never touching the sign, is still hidden.
    - Re-rendered 24.2 s: the right-lane "4 mph" now shows under the "35 +5" sign.
    - 3 tests replace the drop test; 44 passed.
    - With MAX in the sign (ICBM holding, engaged, no recent set-speed change): same 24.2 s frame, sign "MAX 45 / 35 / +5". The right-lane label sits centred just below it. The sign box is the same 116×142 with or without MAX (item 102), so the spot does not move. The harness clock had to be pushed past the 2.5 s set-speed pop-up, or the plain sign drew.
  - Replay render evidence; the harness is scratch and is not committed. Not seen on the device. UI only, not brake-affecting.
- **What to watch.** The larger labels need more room, so the item 102 overlap rules fire more often:
  - an in-path label that would overlap another label is hidden (e.g. leadOne and leadTwo close together);
  - a side label slides outward, and could now reach the screen edge or the wheel icon.
  - Photograph it if a label goes missing or clips.

**Test environment on an aarch64 Linux host (this session).** The checked-in `.so` files load natively. They were built for **Python 3.12** (`msgq/ipc_pyx.so` needs `PyType_FromMetaclass`), but the SessionStart hook created a 3.11 `.venv`. **Fixed 2026-09-24:** the hook now creates `.venv` on 3.12, and rebuilds an existing venv on another version unless `.venv` is tracked by git. Checked on this aarch64 host: `.venv` 3.11 → 3.12.3, and `msgq.ipc_pyx`, `cereal.messaging` and `Params` import. Its scons step also fails without `clang++`, and it leaves `panda/board/obj/{gitversion.h,version}` dirty (restore them). What worked for the mici UI tests:
- a 3.12 venv outside the repo with the hook's package list plus `raylib<5.5.0.3`, `qrcode` and `pillow`;
- `PARAMS_ROOT` pointed at a scratch directory, because Params otherwise tries `/data/params`;
- running under `xvfb-run -a`, because raylib segfaults at import without a display.

**Hook fixed further, same day.**
- It apt-installs `clang build-essential xvfb`. SConstruct hardcodes clang; the hook used to exit on `clang++: not found` before masking the artifacts.
- The venv now uses **uv-managed** CPython 3.12. The system `python3.12` on this image has no `Python.h`, and scons failed compiling `ipc_pyx.cpp` against it. An existing venv without headers is rebuilt.
- It installs `raylib<5.5.0.3 qrcode pillow`.
- The session env file exports `PARAMS_ROOT` (default `~/.comma/params`).

Checked on this aarch64 host (uv-managed 3.12.14): the hook exits 0, the full scons build completes, and 53 artifacts are skip-worktree. A second run is a no-op (1.4 s). Tests: `opendbc_repo/opendbc/car/honda/tests/` 271 passed; the five radard/longitudinal suites 129 passed; `test_mici_multi_lead.py` under `xvfb-run` 38 passed. **Not run on an x86_64 container.**

## 106. Stock-ACC routes 266 and 267 (build d20a18d28, the 0.075 bound on the device): the item 103/104 replays, both FCW events, and every brake takeover. Replay (log decode, open- and closed-loop planner) evidence only; no code change, nothing driven under alpha.

The owner asked (2026-09-24) for analysis of two new stock-ACC drives. The routes were fetched on an aarch64 Oracle host (`konik_preflight.py` 8/8, `konik_fetch.py` 30/30 and 21/21 rlog segments). Route data is outside the repo, not committed.

| Route | Build | Car | Duration / cruise on | Episodes < −1.5 | Brake takeovers | FCW |
|---|---|---|---|---|---|---|
| `00000266--f766f599f0` | d20a18d28 | HONDA_CIVIC_BOSCH, stock ACC | 1777 s / 972 s | 13 | 4 (+1 gas, 3 other) | 4:27.5, 4:28.7, 4:29.4, 14:32.5 |
| `00000267--e83a1fa671` | d20a18d28 | HONDA_CIVIC_BOSCH, stock ACC | 1218 s / 639 s | 5 | 5 (+1 other) | none |

Tools, run at 2026-09-24 HEAD `d3786234`, with planner code identical to item 104a: `tools/longitudinal/alpha_open_loop_replay.py` and `alpha_closed_loop_replay.py` (default bearings 0.1,0.075). Closed-loop validity is `leadOne.status` agreement **99.14% (266) and 99.36% (267)**, radar flag 99.20/99.53%, dRel ±1 m 91.9/95.5%, same track 81.9/67.4%. Open and closed loop agree on every episode to within 0.03 m/s².

**Protected episodes: none changed between 0.10 and 0.075** (266: 6 genuine by vision/stock label; 267: 3). The only b0.1/b0.075 frame differences are 266 14:29.1 (13 frames, genuine, −3.77 → −3.69, crossing unchanged) and 267 15:13.0 (16 frames, below).

### The two FCWs on 266 (openpilot planner FCW; `stockFcw` stayed 0)

- **4:27.5–4:29.4: a real hard stop, and the FCW was justified.** A slow lead, vision v 5.6 → 0.5 m/s, was approached from 94 m at vRel −9.4 at 52 mph (radar track 13, y ±0.2 throughout). Stock braked to cmd −3.23, aEgo −3.80, and stopped about 12 m behind with no driver input. The owner bookmarked it at 4:31.4. Alpha replay: −3.45, crossing −1.5 0.7 s **before** the stock command and −2.5 1.7 s before it. Radar quirks during the stop were a one-sample vRel −15.0 at 4:27.4 (from −9.5; not a rail value) and aLeadK down to −6.9 at 4:29.1 while vision a was −0.4. The lead really was coming to rest, and the FCW was already firing on range/TTC.
- **14:32.5: a real braking lead, but the FCW was marginal and radar-driven.** Track 36 came in from y −3.3 to 0 on a left curve (steer −10° → 0) at 29–37 m. Vision a was −1.5 to −2.1, stock cmd −1.78, so the brake was real. At the FCW frame radar vRel was −8.4 and aLeadK −7.6. The 1 s range slope was −6.6 and vision vRel −4.7. With vRel −8.4, TTC is 3.4 s, under the 4.0 s FCW limit. With the range slope it is about 4.5 s. The driver braked at 14:35.9 and then took over on the gas and steering for a turn. The replay episode (14:29.1) is genuine: alpha −3.69 vs cmd −2.11, and the bound fired 11 frames at 0.075.

### Alpha-only brakes (alpha ≤ −3 while stock stayed above −1.5)

- 🔴 **267 15:13.3: off-axis false brake that 0.075 does not catch. Same signature as 25f 13:58.4 and 237 942.6.**
  - This was on a right-curve exit, steer +13° → 0. Radar track 39 swings from y +8.8 to +0.2 at 56–69 m.
  - Radar vRel went +6.1 → −8.2 → −0.9 in about 3 s, and aLeadK reached −9.4.
  - Over the same time vision held v 14.8–15.9 and a +0.0–0.25 at p 0.92–0.97. Ego was at 13.4–14.4, so vision vRel ≈ +1. The radar range dipped 69 → 56 m and recovered to 59 m.
  - Alpha went to −3.45 at both thresholds and with no bound. Stock cmd was +0.28 at the peak and −0.60 later. Required decel is 0.0, so it is not protected.
  - **Why the bound misses:** bearing was 0.084 at 15:13.25 (bounded), then 0.074 and 0.070 at 15:13.40–15:13.55, where aLeadK was −9.1 to −9.4. The lead swings toward the centre as the curve unwinds, so the worst radial-rate artifact arrives **after** bearing falls under the threshold. 0.075 bounded 11 frames (Δ up to 0.3 on single frames) and did not change the minimum.
  - **Not changed here.** Lowering the threshold a second time (0.10 → 0.075 → about 0.065) chases the threshold on one case at a time, and 263 6:14.3 would have to survive each step. The structural alternative is a design question for the owner. Candidates: hold the bound on a track for about 1 s after its bearing was above the threshold, or while steering or yaw rate is high; or bound when vision is confident (p ≥ 0.9) and disagrees with the radar lead speed by more than about 5 m/s. Any of these needs its own closed-loop pass against the 125 protected episodes.
- 🟠 **266 2:27.9: vRel settling on a newly acquired track, centred.** Track 61 took over from a vision-only lead at 61 m. vRel went +3.1 → −3.5 in 1 s and aLeadK hit −4.8, while vision v held 18.1–18.9 against ego 18.8 (vision vRel ≈ 0). Alpha −3.45, stock cmd −0.99, required decel 0.2. At 2:29.7 the driver pressed the gas against even stock's −1.0. Bearing 0.00–0.01, so no bearing bound applies. This is the 260 9:01.2 class: the aLeadK filter passes a short vRel transient to the planner.
- 🟡 **266 11:42.3: real mild slowdown; alpha goes to the rail.** Track 12, centred at 26–35 m, lead slowing from 19.4 to 16.9 (vision). The range closed at about 3.8 m/s and radar vRel reached −5.0, aLeadK −4.1. Alpha −3.48, stock cmd −1.14. Item 103's "alpha is harsher on ordinary slowdowns" pattern.
- ✅ **266 16:11.6: the bound worked.** Bearing 0.12–0.13, 46/46 frames bounded, −3.45 → −1.79 (stock −0.30).

### Stock deeper than alpha (genuine)

- **267 14:47.0: close cut-in.** Track 28 appeared at 9.7 m (y +1.6), replacing the 23 m lead. Stock started braking the same frame and went to cmd −3.46, aEgo −4.05, bottoming at a 7.1 m gap at 6.9 m/s. Alpha reached only −2.53 and trailed by +0.2 s. Radar vRel went −3.3 → −3.9 → −1.6, consistent with vision. This adds to item 103's "stock is deeper at the peak" list; replay only, it does not say −2.5 would have been too little.
- **266 4:24.8 and 13:19.4** were genuine hard brakes where alpha led stock (−0.7 s and −0.2 s at −1.5).

### Driver brake takeovers (the 5 s before each)

- **Not a lead problem:** 266 6:44.0 (no lead, ICBM/CSC set speed falling 25 → 14), 18:47.3 (no lead, accelerating), 26:19.4 (no lead), 267 3:25.2 (no lead), 267 10:01.5 (no lead in radarState; vision lead at 128 m, p ≤ 0.1). These are ordinary exits and slowdowns.
- **266 16:15.7:** off-axis track 59 on a curve (y +9.4 → +3.4, bearing 0.13 → 0.07) read vRel −8.6 and aLeadK −6.7 while vision said about −1.6. Stock stayed at −0.3; the driver braked as the vision lead began braking (a −1.4). Same radial-rate signature as 267 15:13.3, but the bound (bearing ≥ 0.075 for most of it) covers the worst frames.
- **267 6:48.6:** lead track 2 swinging y −3.6 → +3.7 on a curve with the set speed falling; the lead dropped, and the driver braked.
- **267 11:31.4:** far lead 110–127 m decelerating (vision a −1.1 to −1.6), stock only −0.5; the driver braked early. Radar had it at vRel −4 to −7.
- 🟠 **267 16:28.1: a radar lead that may be the wrong object at 90 m.** Track 39 at 87–92 m read vRel **+4.1 → +2.0 (opening)**, and its range really did open (86.9 → 92.3 m). Vision showed a lead braking: v 13.5 → 7.7, a −1.1, ego 14.6–15.9. Stock ACC was **accelerating** (cmd +0.37), so stock missed it as well. radarState then flipped to a vision-only lead reading −7.6 to −9.4, and the driver braked at 16:27.8. Under alpha the planner would have seen the same opening radar lead for about 2.5 s. It is no worse than stock here, but it is a far-range lead-identity case for the watchlist.

**What this does not settle.** Ego follows the log, so no replay shows the gap alpha would have opened. Frame-level track identity agrees only 67–82% with the on-device parser. Nothing here was driven under alpha long.

## 107. The two item 106 follow-ups replayed closed-loop on 19 routes: the per-track 1 s hold beats the vision-disagreement bound. Replay evidence only; nothing shipped, nothing driven.

The owner asked (2026-09-24) to test both fixes and pick the better one. Both are in `tools/longitudinal/alpha_closed_loop_replay.py --fixes` as replay-only planner variants on top of the shipped 0.075 rule. The planner is unchanged. Both reach the same bound, aLeadK ≥ −max(1.5, vision brake); they differ only in the extra way past the bearing test:
- **hold:** the bearing test also passes for 1.0 s after the same radar track last sat at bearing ≥ 0.075.
- **visdis:** the bearing test also passes when vision is confident (p ≥ 0.9), is the same object (x within max(5 m, 15% of dRel)), and its lead speed disagrees with the radar's vEgo + vRel by ≥ 5 m/s.

Run: all 17 item 104 routes plus 266 and 267, `--bearings 0.075 --fixes`, at HEAD 17ba13db plus the tool change. 214 episodes, 132 protected (vision/stock label or the item 104 rule, as in 104a). leadOne.status agreement ≥ 99.10% on every route. Pass criteria are item 104's: 0 protected episodes softened > 0.3 or delayed > 0.2 s at −1.5.

| | hold | visdis |
|---|---|---|
| 267 15:13.3 off-axis false brake (stock −0.60) | −3.45 → **−1.45** | −3.45 → −2.97 |
| Protected episodes changed | 1: 237 18:09.4 (see below) | 1: **25f 8:02.6, a real closing brake delayed 0.35 s** |
| Other frame-level differences > 0.3 | none | 25f 8:03.3 (10 frames), 266 4:27.3 (1 frame) |
| 266 2:27.9 (centred new-track transient) | unchanged | unchanged (disagreement 3.6 m/s, under 5) |

- **visdis fails in the dangerous direction.** At 25f 8:02.6 a centred lead (bearing 0.008) closed from 94 m to 42 m. Radar vRel grew −0.8 → −13.4, and the range confirms it: 55.2 → 41.6 m in 1 s. Vision under-read the closure (a −0.3 to −0.6), so the disagreement rule fired on 49 frames and bounded aLeadK to vision. Alpha crossed −1.5 at 8:03.70 instead of 8:03.34, 0.4 s behind stock's own command (8:03.29). Vision lagging a real closure is exactly the case where the radar has to win (D-041/D-042 spirit). Rejected.
- **hold's one protected change is protected only by the circular label.** At 237 18:09.4 (alpha-long, build fa262e0c7, before the bound) track 62 at 64–69 m swung in from y +5.4 to 0, with vRel −3.6 and aLeadK −3.5, while vision a was ~0.0 (p 0.26–0.58). The range closed 68.6 → 61.7 m and then held. Live alpha commanded −2.57 and the car reached −3.29 with no driver brake. The episode is protected only because alpha's own command went below −2.0 (the item 104 caveat that also covered 23e 4:54.6). Vision a stayed above −1.0 until later, and the peak vision-required decel was 1.0. Hold gives −0.73 against a closing speed of 3.6 m/s at 64 m (TTC about 18 s). Read as a false alpha brake that hold softens, **but that is judgment, not the pre-set criterion**. The owner drove this route and can say whether that brake was wanted.
- **Recommendation: hold, not shipped yet.** It needs the owner's call on 237 18:09.4. If approved, it goes into `off_axis_lead_a_lead` as a planner change with unit tests, followed by a road drive on curve exits. Ego still follows the log in all of this.

## 108. C4 close-lead marker flips onto the lead's roof, tip down, with its speed above it (owner request). Unit and replay render evidence; UI only, not brake-affecting; not seen on the device.

- **Problem** (owner: "when I'm getting really close to lead, sometimes I can't see the marker at all"). The mici chevron sits at the lead's bottom edge. `_update_lead_vehicle` clamps it to `rect.height - 0.6·sz`, so a close lead's marker is pinned to the bottom of the view and its speed label is drawn below the screen.
- **Change** (`selfdrive/ui/mici/onroad/model_renderer.py`):
  - Each lead (in-path and side-lane) also projects its roof, 1.5 m above the road (`LEAD_ROOF_HEIGHT`).
  - When the normal marker would be clamped, or its bottom point is off the projection, and the roof point is known, the marker flips. It draws tip down on the roof, and `_draw_lead_label` puts the speed above it.
  - Hysteresis stops it flickering: it un-flips only once the normal tip is 1.6·sz above the bottom (`FLIPPED_LEAD_UNFLIP_SZ`). The tip is kept 30 px below the top, leaving room for the label.
  - The flipped points are listed in reverse, so the triangle fan keeps the upright marker's winding and raylib still draws it.
  - Every label is now clamped horizontally into the view. The in-path label of a marker near the right edge was running off-screen.
- **Tests:** 7 new tests in `test_mici_multi_lead.py` cover the flip, winding, hysteresis, label on top and edge clamp. 67 passed together with `mici/tests/test_lead_indicator.py`.
- **Route render** (00000267--e83a1fa671, real mici `ModelRenderer` and `HudRenderer` offscreen over the qcamera; scratch harness, not committed):
  - seg 13 59.0 s, lead 7.3 m at 5 mph: before, a marker sliver at the bottom edge and no label. Now there is a red down-chevron on the car's roof with "5 mph" above it.
  - seg 13 56.0 s, lead 10.9 m: not flipped, unchanged.
  - seg 16 38.2 s, leadOne 7.9 m at yRel −3.2 (a cut-in at the right edge): the flipped marker lands top-right, next to the speed-limit sign. Its label now stays on screen but touches the top edge of the sign. In-path labels ignore the sign by the item 105 rule.
- **Follow-up, same day** (owner: "the 14 mph is still occluded a little bit by the frame"):
  - The flip now also fires when only the label would be cut off. The upright marker needs `sz + LEAD_LABEL_ROOM` (32 px: a 2 px gap plus the 30.2 px box of a 26 px label) above the bottom of the view. The unflip band is 1.0·sz.
  - Re-render seg 13 56.0 s (lead 10.9 m): before, "14 mph" was cut off at the bottom edge; now it flips onto the roof with "14 mph" above. At 52.9 s (18.2 m) the label fits and the marker stays upright. The 10.9 m left-lane pickup there flips too.
  - 1 new test; 68 passed.
- **In-path labels now avoid the sign too** (owner: "make the cut-in label avoid the sign too"). This replaces the item 105 rule that in-path labels ignore it.
  - An in-path label that hits the sign slides off it toward the side its centre is on, then the other way, then goes just below the sign.
  - If none of those fits, it is drawn in place. The sign alone never hides the in-path speed; overlapping another label still hides it, as before.
  - 4 tests replace `test_in_path_label_ignores_the_sign`; 71 passed.
  - Re-render seg 16 38.2 s: the in-path "12 mph" moves left of the sign and the right-lane "12 mph" (the same car) drops below it; both are clear. The 7.0 and 35.2 s label positions are unchanged.
- **Tall leads rendered** (owner request; route 00000267, rlogs and qcameras for segs 4, 10 and 17 fetched from Konik; build d0b52514):
  - seg 4 11.5 s, a Sprinter-height van at 5.4 m, stopped: the roof is above the screen. The marker is held at the label-room limit (tip y 56) on the rear windows, with "0 mph" above it.
  - seg 10 16.2 s, a Ram pickup at 8.1 m, 9 mph: the marker sits on the rear window, just under the cab roof.
  - seg 17 45.0 s, an SUV at 3.5 m, stopped: the marker is held at the top, on the rear glass.
  - In all three the marker and label are fully visible; before, each showed only a marker corner at the bottom edge.
  - Owner reviewed these renders and kept `LEAD_ROOF_HEIGHT` at 1.5 m ("it looks fine"). Raising it to about 1.9 m was offered, to put the marker above pickup cabs.
- **Stop-and-go flicker and doubled labels** (owner, 2026-09-27: "make it flip back without flicker in stop-and-go"; "sometimes the speed label doubles").
  - Method: a frame-by-frame replay through the real `ModelRenderer` on 00000267 segs 3, 4, 10, 13, 14, 16 and 17 (about 8,400 frames), with the renderer clock pinned to log time. Scratch harness, not committed.
  - **Flicker cause found.** At seg 10 625.0 s a flipped lead (vision-only, 16 m) blinked out for one frame and came back upright, inside the hysteresis band, because the flip state lived on the per-frame `LeadVehicle` and was lost with it.
  - **Fix:** `_place_lead` keeps a flip state per lead slot. It survives a dropout of up to 1 s (`LEAD_FLIP_MEMORY_S`), and any flip, either way, is held at least 1 s (`LEAD_FLIP_MIN_HOLD_S`) unless the held form cannot be drawn.
  - Replayed: that frame now stays flipped. Every remaining form change is a single one, at least 8.9 s apart, including after a gap longer than 1 s.
  - **Doubled label, cause 1:** a side-lane lead that is the same car as an in-path lead. At seg 16 38.2 s, leadOne and leadRight were both radar track 41; this happened on 29 frames across segs 14 and 16.
  - **Fix:** `same_lead()` matches the same radar track (≥ 0), or for vision-only leads the same spot (within 1.5 m dRel and 1.0 m yRel). A matching side lead is not drawn. Replayed: 0 such frames.
  - **Doubled label, cause 2, left alone:** two different cars doing the same speed, for example seg 13 782.7 s (leadOne 55 m, track 28; leadLeft 103 m, track 44), about 170 frames. They are two cars.
  - Not changed: a lead that blinks out for a few frames (seg 10 625 s, a vision lead at yRel 7–8 m) still makes its marker disappear for those frames. That is the published lead status, not the UI.
  - 3 flip-memory tests and 6 `same_lead` cases added; 80 passed.
  - **Checked on two longer drives** (owner request): 00000280--d02d9c2f8e (build 63827356b) and 00000283--fe4e75f88b (build a37852f8a). Both builds have the flip but not this fix; their renderer is identical to d0b52514.
    - Frame-by-frame replay of 14 segments (about 16,000 frames), picked from a qlog scan for close leads and same-car side leads: 280 segs 4, 13, 23, 29, 31, 32, 33 and 283 segs 12, 14, 15, 25, 29, 35, 36. Each ran with the drive's own renderer and with the fix.
    - Flips that switch back within 1 s: 2 → 0 (280 seg 31 1920.5 s, 0.25 s at 10.0 m; 283 seg 36 2212.2 s, 0.75 s at 12.4 m). leadOne form changes: 26 → 24.
    - Same-car doubled labels: 132 → 4 frames.
    - The frames that still repeat a speed are different cars doing the same speed: in-path + side 304, side + side 117, and 3 where the repeat was the other side lead.
    - Radar vs vision, left in the display (4 frames): 280 seg 13 791.8 s, leadOne vision-only (track −1) at 19.0 m while leadTwo, radar track 7, was at 12.4 m with yRel −1.0 at the same speed; and 280 seg 32 1928.4 s, leadOne track 34 at yRel 5.4 against leadTwo vision at yRel 2.2. Both are probably one car. This is upstream of the UI (radard lead selection) and not investigated here.
    - Route logs deleted after the analysis (owner request).
- **On-device logs, 2026-09-27** (pulled from the comma over ssh, read-only). Routes 0000028a--0f4ebf7920 (build 2ab675ffe) and 0000028b--ed67104f14 (99a4e49f4): both include the fix, and their renderer is identical to HEAD. DeveloperUI, DeveloperWidgets, AdjacentLeadsUI and RadarTracksUI are all on.
  - Replayed 10 segments (11,815 frames): 28a segs 13, 15, 20, 21, 28 and 28b segs 0, 9, 10, 11, 19.
    - 0 flips back within 1 s, 0 same-car in-path + side doubles, 17 leadOne form changes.
    - Repeated speeds are otherwise different cars (in-path + side 315 frames, side + side 95).
  - **Found and fixed:** leadTwo is often leadOne again. With separate per-slot flip memories the two could split, one marker on the roof and one under the car (28a seg 28 1694.8 s, a 2.4 m lead, 4 frames). leadTwo is now skipped when `same_lead(leadOne, leadTwo)`; 1 test added.
- **Radar points on the C4** (owner: "is it possible to also show radar points as well"). `_draw_radar_points` ports the big UI's liveTracks overlay: the same "Radar Point Display" toggle (`RadarTracksUI`) and the same `project_radar_points`.
  - Red dots, 4 px with a 5.5 px outline.
  - Drawn over the lead markers, so each lead's radar return shows against its vision marker.
  - Points off the view are dropped. The big UI pins them to the screen edge, which read as stray specks at the C4's size.
  - 4 tests added; 85 passed.
  - Rendered on 28a segs 13 and 20 and 28b seg 19: 2–4 tracks per frame. Each in-path and side lead has its dot at the marker tip. Close leads' returns fall below the view, so they have none.
  - Replay render evidence; not seen on the device.
- **Deployed to the car, 2026-09-28** (owner: "you can do update and restart on it. But don't change any toggle"). While offroad, with no other agent logged in: `/data/openpilot` fast-forwarded 99e807fd → e0d4aa2c, pure Python, and the `prebuilt` marker was kept. The device's local `starpilot/assets/active_theme/` edits were left as they were. It was rebooted, came back on e0d4aa2c, and `selfdrive.ui.ui` is running with no UI exception in swaglog. No param or toggle was changed. Not yet driven on this build.
- **First drives with the radar dots, 2026-09-28** (openpilot-51 (Steve); logs pulled from the comma, analysed, then deleted). 0000028f--b6284c4bc9 ran e0d4aa2c; 00000290--af15379c8c, 00000291--edadbd74e6 and 00000292--72e364dd62 ran ea8e066d, whose mici renderer is identical to e0d4aa2c and HEAD. `RadarTracksUI` and `AdjacentLeadsUI` were on for all four.
  - Method: every segment (62, 70,230 frames) replayed frame by frame through the real `ModelRenderer`, recording markers, labels and radar dots. Selected frames rendered over the qcamera. Replay render evidence; the owner has not yet reported what he saw.
  - Flip: 56 leadOne form changes, 0 that switch back within 1 s.
  - Doubled labels: 0 frames with the same car labelled twice. Every repeated speed is two different cars, for example 28f seg 13 785.2 s: leadOne track 46 (its right-lane copy correctly hidden) and left lead track 43, both 19 mph.
  - Radar dots: a dot sits within 25 px of the in-path marker tip on 11,028 of 12,519 radar-lead frames on 28f, 1,742 of 1,747 on 290 and 4,926 of 6,608 on 292. Nearly all the misses are flipped close leads, whose returns fall below the view. Only 36 upright frames miss, mostly cut-ins whose marker is clamped at the screen edge.
  - **Marker blinks:** leadOne's status drops for 0.5 s or less and comes back 176 times (28f 20, 290 28, 291 1, 292 127). 152 of these are vision-only leads (track −1). Worst case: 292 seg 1 118.3–120.2 s (render 56.9–57.2 s), stopped at night, disengaged, with a vision lead at 26 m switching on and off every 0.1–0.3 s. Not changed; holding the marker through these dropouts is an owner decision (see the open item in the handoff).
  - Seen once in a render: 28f seg 8 11.8 s, a flipped right-lane marker (15 m, yRel −2.8) draws over the corner of the speed-limit sign. Label avoidance covers labels, not markers.
  - **Side labels no longer jump across the in-path label (owner, from the contact sheet).** At 28f seg 6 51.2 s the right-lane lead's "56 mph" and at 28f seg 8 11.8 s its "46 mph" had slid about 180 px left to get off the speed-limit sign, past the in-path label, so they read as a second in-path speed ("super confusing"). `_draw_lead_label` now drops a side-lane label that sits on the sign, never slides a side label inward past the label it hit, and never parks one under the sign. Label-only collisions still slide outward, and in-path labels are unchanged. The marker still draws. Unit tests plus a replay render of both frames; not seen on device.
  - **Not a UI fault, for Radar Work (Bob):** at 28f seg 6 32.6 s the blue left-lane "16 mph" marker sits next to the black sedan, not under it. It is on track 49 (dRel 29.5, yRel 3.0), whose range closes at about 21 m/s (the car's own speed; 74.6 → 7.9 m over 30.5–34.0 s) while U11 sits on the −13.5 m/s rail. That makes it a stationary return, published as the rail bound (vLead = vEgo − 13.5 ≈ 16 mph), not the sedan, which moves with traffic. Track 43 (9 m left) shows the same pattern.
  - **Side leads wait 0.5 s before their marker and label (owner: "Just radar points on those. No need for label and marker.").** A new leadLeft/leadRight track gets no marker and no speed label until the same radar track has held that slot `SIDE_LEAD_MIN_AGE_S` = 0.5 s; a new track id or a status drop starts the wait over. Its radar dot draws the whole time. Unit tests only, not rendered or seen on device. **Second correction (replay, Radar Work (Bob) + this session):** the first correction above tested the UI delay alone against radard-OFF output (28f segs 8-12 → 65.5 s to 34.9 s of oncoming marker time, a flat ~0.5 s trim). That understated the car's actual behavior, which runs the radard fix and this UI delay together. Bob's own gate simulation (`/tmp/rv/adj_0000028f_8-9-10-11-12.json`, 28f 517-750 s) with both fixes combined: oncoming marker time 68.4 s (no fixes) → 21.3 s (radard fix only) → 0.0 s (radard + UI delay, fully cleared); other railed takeovers (track-43-style handoffs) 7.1 s → 0.0 s; stationary 4.9 s → 0.1 s; real same-direction side cars 14.9 s → 12.4 s (still mostly shown, as intended). So on the car, the combination does clear the oncoming markers in this stretch — the "only trims 0.5 s" read holds for the UI delay in isolation, not for the shipped combination. Replay numbers only, not rendered or seen on device. The big UI (`selfdrive/ui/onroad/model_renderer.py`) is unchanged.
- **Watch:** a tall lead (truck, SUV) has its roof above 1.5 m, so the marker sits on the rear of the body rather than above it (rendered above). Photograph it if the marker flickers between the two forms in stop-and-go.

## 109. The item 107 per-track hold is shipped in the planner (ffa72fdc, owner approved); the shipped code reproduces the replay prototype on 19 routes. Replay evidence only; brake-affecting; not driven.

The owner confirmed that 237 18:09.4 was a phantom brake ("braked way too early … nowhere close in the zone where it should constitute a hard brake"), which settles item 107's open judgment call. Hold then passes the pre-set criterion, and the owner approved shipping it.

- **Code (ffa72fdc):** `longitudinal_planner.py` adds `OFF_AXIS_LEAD_HOLD_FRAMES = 20` (1 s at 20 Hz; its comment block carries the evidence) and `OffAxisLeadHold`, which records the last frame each `radarTrackId` sat at |yRel|/dRel ≥ `OFF_AXIS_LEAD_MIN_BEARING` (0.075). `off_axis_lead_a_lead(lead, model_msg, held=False)` skips the bearing test while the track is held. The bound itself is unchanged: aLeadK ≥ −max(1.5, vision brake). 3 new tests (the 267 15:13.3 curve exit, expiry after exactly 20 frames, and a never-off-axis track left untouched); 625 planner/radard/lead tests pass.
- **Verification:** all 19 routes re-run with `alpha_closed_loop_replay.py --bearings 0.075` on the shipped planner (no `--fixes`). All 214 episodes match item 107's `hold` variant: min within 0.02 and the −1.5 crossing within 0.05 s, 0 mismatches. Against the old 0.075 run only three episodes move: 267 15:13.3 (−3.45 → −1.45), 237 18:09.4 (−2.57 → −0.73) and 25f 13:58.4 (−1.22 → −1.18, above −1.5 either way). 0 protected episodes change.
- **Not addressed:** 266 2:27.9 (centred new-track vRel transient; item 106) is unchanged. Hold only acts on a track that was off-axis in the last second.
- **Watch on the road:** curve exits with a lead at 40–70 m. If alpha now reacts late to a lead that really brakes just as the curve straightens, the hold is the first suspect, because it keeps the bound on for 1 s after the lead centres. The owner's next drive has "Keep Fast-Closing Leads" (`BoschARailInterval`) off, so that brakes on that drive can be attributed to the hold.

## 110. Route 00000268 (the owner's first alpha-long drive on the vision-radar fusion build b6619f55): the hold changes nothing here; the FCW was a real approach into slowing traffic; one D-062 latch held a wrong-sign vRel for 2.35 s. Replay and log-decode evidence only; no code change.

Build b6619f55 predates the hold (ffa72fdc), so this drive ran without it. Toggles as logged: `RangeDerivedVrel` 1, `BoschARailInterval` 0, `FarLeadCoastCap` 1. 858 s, 498 s engaged, 9 episodes below −1.5. Replay agrees with the device: leadOne status 99.63%, and every episode minimum is within 0.07 of the logged value.

- **Hold vs no hold:** the shipped planner and a copy with `OFF_AXIS_LEAD_HOLD_FRAMES = -1` give identical minima and crossings on all 9 episodes. The hold neither helped nor hurt this route.
- **`FarLeadCoastCap`:** forced on or forced off in replay, all 9 episodes are identical (`starpilotToggles` in the log does not carry this key, so the replay default is off). The cap never binds: every far approach here had a braking lead or a TTC under 8 s.
- **Startup faults:** `commIssue`, `selfdrivedLagging`, `posenetInvalid` and `radarTempUnavailable` all fall in the first 13 s. None of them occur while driving.
- **The three disengagements are all brake takeovers, and none follows an alpha misstep:**
  - 5:37.7: a lead pulling away at 23 m, alpha accelerating gently.
  - 7:46.7: a vision-only lead at 49 m.
  - 12:30.3: a lead closing 2–3 m/s at 46 m, with alpha already at −0.5.

**The owner's five bookmarks**

| Bookmark | Episode (alpha min, aEgo) | What the log shows |
|---|---|---|
| 5:28.6 | 5:25.9 (−3.50, −4.03) | In a turn (steer +14°), track 18 at 43 m swung from y +5.5 to +3.9 (bearing 0.12). The range closed at about 6.6 m/s and vision had the lead slowing from 12.6 to 7.1 m/s. The 74e off-axis bound was active (20 frames) and cut aLeadK −7.7 to the vision value, yet the closure alone drove −3.5. Vision label: genuine (required 1.8). |
| 5:57.2 | 5:56.6 (−1.37) | A new radar track 43 at 40 m, 5 m/s slower than ego. Mild; genuine. |
| 9:08.4 | 9:05.5 (−3.48, −4.44) | A lead in a curve (y +8 → +0.5), vision-only until 9:06.0, slowing to 4.5 m/s. Radar range read 12 m shorter than vision (48.9 vs 62.7). Genuine (required 2.7). |
| 9:59.7 | 9:55.2 (−2.16, −2.73) | **The D-062 latch, below**, then a cut-in by track 35 at 26 m closing 4 m/s. Vision label: not genuine (required 1.0). |
| 11:43.0 | 11:41.2 (−3.45, −4.44), FCW 11:43.8 | See the FCW bullet below. |

- **FCW 11:43.8 (openpilot planner FCW; no driver brake):**
  - From 11:39 a vision-only lead at 95–105 m closed at 7–8 m/s while slowing (vision v 14.6 → 4.5 m/s, a −1.1).
  - At 11:40.3 radar track 34 was picked up at 98 m with vRel on the −13.5 m/s rail (D-041).
  - Alpha braked −0.8 to −1.0 until 11:41.0 and passed −1.5 at 11:41.2 (TTC about 6 s), then −4.0 from 11:42.3. The FCW fired at 41 m with 11.5 m/s closing, while the car was already at −4.
  - The car stopped closing at 34 m, at 7.4 m/s.
  - The brake was real and needed. The ~1.2 s at −1.0 before the hard brake is the same shape as the unexplained 251 532–547 s under-brake (item 85 table), and it is not explained here either. `FarLeadCoastCap` is ruled out: see above.
- **D-062 latch at 9:51.6–9:54.7, track 25 (y −2.2 → −0.9 as it moved in):**
  - At 9:51.6–9:52.4 the range stepped from 45.3 to 51.7 m, as a reflection or association change. The two U11 samples measured during the step (+3.3, +4.1) became the trusted vRel.
  - The range then closed at about 6 m/s (52.2 → 38.3 m in 2.4 s). Vision's lead speed agreed: 18.4 against ego 22.0.
  - The one-sided rate check rejected the true closing U11 against the stale opening fit (+7.2), so vRel was coasted at **+4.06, and aLeadK +3.26**, flagged `measured=False`.
  - The D-062 lasting-clean-step re-root released it only at 9:54.74, after 2.35 s. vRel then read −5.98, and aLeadK swung to −4.0 within 0.5 s.
  - `vRelRangeDerived` was NaN for the whole coast, because the D-053 assist disarms on unmeasured samples. So the assist, which was on, could not act, even though the coasted dRel was the radar's live, innovation-checked range.
  - Outcome: about 2.3 s with no brake while closing from 50 to 38 m at 22 m/s, then a −2.1 catch-up brake. Not dangerous here: the gap stayed at 1.7 s or more.
  - The mechanism goes further than the D-041 note in the coast path, which says "an understated closing rate still brakes". Here the coasted value had the **wrong sign**, and it would have been the same on a hard-braking lead.
- **Open (design, not changed):** during a coast whose dRel is live, the lead could be bounded by the range slope, for example by letting the D-053 assist consume coasted live ranges, one-sided toward more closing. D-062 rejected appending coasted ranges to the U11 check's samples, because that re-admits over-closing U11. The planner-side bound is a separate question and would need its own replay on the 24-route set before any change.

## 111. One-sided range bound on Bosch-A coasts, behind `RangeDerivedVrel` (the item 110 open design item). Replay evidence only; not driven.

**What changed (`opendbc_repo/opendbc/car/honda/radar_interface.py`):** `_bosch_a_coast_vrel` already clamped a coasted vRel to within 3 m/s (`BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS`) of a fresh range-rate fit over `rejoin_samples` or `inconsistent_run` (item 92). That clamp ran only with `BoschARailInterval` on, which the owner keeps off (item 91). It now also runs when `RangeDerivedVrel` is on (read once at startup, `self.coast_range_bound`), but **one-sided**: `vrel = min(vrel, rate + 3)`. It can only make a coast more closing, never less. With `BoschARailInterval` on it stays two-sided, unchanged. The fit still needs at least 4 samples over 0.25 s, so a coast without fresh ranges keeps the held vRel (D-041 unchanged: nothing is deleted, only the held value is bounded).

**Why one-sided:** the first, two-sided attempt softened five protected brakes on the 20-route set: 237 9:58.5 −3.10 → −2.38, 266 8:04.0 −1.98 → −1.48, 266 9:20.9 −1.66 → −1.11, 23e 1:07.0 −2.00 → −1.66, 232 20:32.6 −2.51 → −2.25. It also made 263 0:13.4 harder (−1.82 → −2.78) and removed 262 1:34.0. It was rejected.

**Replay (`alpha_closed_loop_replay.py --bearings 0.075 --coast-bound`, against the shipped planner with the bound off), 21 routes (the 20-route set plus 0000026b), 235 episodes, 147 protected:**
- One episode moves: 268 9:55.2, −2.16 → −2.17, reaching −1.5 0.05 s earlier (protected).
- No new episodes, and none gone. 0 protected episodes softened or delayed.
- **268 9:52 (the item 110 latch), segment 9 trace:** the coasted vRel goes +4.06 → +0.64 at 9:52.79 and −1.10 at 9:52.94, then follows the range down to −3.9 by 9:54.1. Without the bound it stays at +4.06 until 9:54.74. The planner reaches −0.5 at 9:53.84 with the bound, against 9:54.74 without it (about 0.9 s earlier), and eases in from −0.2 instead of sitting at −0.05. The peak is unchanged (−1.67), because the later cut-in sets it.
- Tests: 129 pass in `test_bosch_a_radar.py` + `test_leads.py`; the radard, assist and replay-tool tests pass. The new tests cover:
  - the toggle read at startup;
  - off: an inconsistent coast holds the stale opening vRel;
  - on, via either toggle: the bound pulls it toward the range fit;
  - `RangeDerivedVrel` alone never softens an over-closing coast.
  `test_longitudinal_planner.py` fails to collect (DeprecationWarning) with or without this change.
- **Needs a device build to take effect.** `RangeDerivedVrel` is already on in the owner's logs, so no toggle change is needed. Watch for early or harder brakes right after a radar track re-appears or steps in range.

## 112. Route 0000026b (alpha long, vision-radar fusion build d0b525140, which includes the hold ffa72fdc): the owner's "best drive yet"; all six bookmarks are genuine approaches; the item 111 bound changes nothing here. Replay and log-decode evidence only.

2949 s, 1327 s engaged, 12 replay episodes below −1.5. Replay agrees with the device on status in 58665 of 58828 frames.

**The owner's six bookmarks** (each one follows the episode by about 1–5 s):

| Bookmark | Episode (replay min) | What the log shows |
|---|---|---|
| 25:56.3 | 25:55.4 (−3.45) | Lane change into a slower lane. Stopped-to-slow traffic (vision 7 m/s) seen from 110 m, radar track 47 from 69 m on the −13.5 m/s rail. Braked to aEgo −3.9, finished at 30 m. Genuine. |
| 30:01.9 | 29:59.4 (−3.12) | Track 48 at 39 m braked hard (aLeadK −4.8, vision agrees). aEgo −3.2, finished at 22 m. Genuine. |
| 36:51.6 | 36:46.8 (−1.44) | In a curve, track 1 at 80–98 m, y +7.5 (bearing 0.08). Radar vRel −7.5 against vision about −3. The shipped off-axis hold/bound acted here: without it, replay gives −2.10. aEgo only −1.2. |
| 37:16.8 | none below −1.5 | Closing 13.5 m/s on slow traffic from 72 m. A gentle −1.0 to −1.4, finished at 37 m. |
| 38:36.3 | 38:34.1 (−3.46) | Track 6 at 33 m braked (aLeadK −5, vision −2.2). aEgo −4.2, finished at 22 m. Genuine. |
| 39:30.6 | 39:28.4 (−3.48), FCW 39:30.7 | Curve (steer −13°), track 32 moving in from y −4.9 to −1.4 as the lead slowed (vision 18.8 → 6.7 m/s). The brake built from −0.4 at 39:27.5 to −4.1 at 39:30.3; the FCW fired at 22.6 m with 7.5 m/s closing, with the car already at −4. Real and needed. It is the same slow ramp as the item 110 11:43.8 FCW, and the curve kept bearing at up to 0.12 while the lead moved in. |

- **The eight brake takeovers, none after an alpha misstep:**
  - 11:53.7, 14:00.2 and 41:56.2: no tracked lead.
  - 15:15.0: in a turn, steer −24°, no lead.
  - 26:57.9: creeping at 3 m/s behind a lead pulling away.
  - 33:21.1 and 41:19.2: a lead opening at 40 m.
  - 42:51.4: no lead.
  - The three gas overrides are at 9:20.6, 9:42.4 and 42:31.5.
- **Item 111 bound on this route:** no episode minimum or −1.5 crossing changes.
- **Open:** the ~1–2 s mild ramp before hard braking on a lead that slows while moving in through a curve (39:27.5 here, item 110 11:41) keeps recurring. Not changed.

## 113. Lateral PID simulator (`tools/lateral/lat_pid_sim.py`) for dialing in the Civic Bosch lateral scales. Replay and simulation evidence only; no controller or setting change; nothing driven.

**What it is.** The tool runs the real `LatControlPID` (modified-EPS Civic Bosch path, banded `Lat{P,I,F}Scale*`, `HondaLateralPidKp/KiScale`, output shaping) on logged inputs. Around it sits a mirror of the Honda carcontroller steering stage: min steer speed, the override ramp and fade-up, and the optional delta limiter. It has three stages:
- `replay` is open loop. It feeds the logged angle, rate and desired curvature through the controller and compares the torque it computes with the torque the car logged.
- `fit` / `validate` fit a steering plant to engaged, hands-off frames by Levenberg–Marquardt on 1 s free-run windows. The plant is a 2-state angle/rate model with speed-dependent stiffness, damping and torque gain, plus a bias term and a tanh friction term. `validate` then checks that the closed loop at the logged settings reproduces the logged metrics.
- `sim` / `sweep` run the controller and plant closed loop while the desired curvature stays held to the log. Whenever the driver's hands are on, the plant re-syncs to the log. `sweep` reports per-band error rms, bias, curve actual/desired ratio, straight rms and sign-change rate for each value of one parameter.

Desired curvature is exogenous: the model and planner are not simulated, so this tunes tracking of the path the car asked for, not the path itself. Route data is cached in the route directory, never in the repo.

**Replay (open loop) finding: the Kp scale on route 00000268 was not in effect.** initData recorded `HondaLateralPidKpScale = 0.65`. Yet the logged `pidState.p` is exactly 1/0.65 = 1.538× the P the controller recomputes at 0.65, on every active frame of the drive. With a 1.0 override, P matches exactly. The car ran Kp 1.0 on 268. The item this corrects is chat-only: the earlier attribution of 268's looser straights to the Kp cut was wrong. Why the setting did not apply live has not been checked.

**Replay (open loop) torque match on 268 with the 1.0 override:**
- With the integrator freeze taken from the log (the logged I is unchanged from the previous frame), the median torque error is 6.9e-4 and p99 is 9.1e-3, against a logged median |out| of 0.041.
- With the freeze recomputed from carControl/carOutput, the median error is 2.3e-2. The one-frame `steer_limited_by_safety` timing cannot be recovered from message interleaving: none of 8 alignments tried was exact. The sim uses the recomputed freeze, so its integrator is somewhat more active than the car's.

**Plant fit** (fit on 260–263, coefficients kept in scratch; not committed). Error at the end of a 3 s free run:

| Route | Plant | Hold-last-angle baseline |
|---|---|---|
| 263 (in fit set) | 1.33° | 4.04° |
| 268 (held out) | 1.93° | 11.33° |

**Closed-loop validation at the logged settings, 25–50 mph band:**

| Route | Curve ratio, log → sim | Straight rms, log → sim |
|---|---|---|
| 263 | 0.926 → 0.911 | 0.55° → 0.53° |
| 268 (held out, Kp 1.0) | 0.963 → 0.955 | 0.86° → 0.89° |

**Limits:**
- The sim under-predicts sign changes: about 0.5–0.6/s against 0.8/s logged. It has no sensor noise and no actuator delay. That makes it optimistic about weave, and more so at higher gain.
- Below 25 mph it does not validate. On 268 the sim's curve ratio is 0.913 against 0.849 logged.
- There is too little highway data to say anything.

**Sweep 1: `LatIScaleStandard`** (Kp 1.0). Each cell is curve ratio / straight rms in the 25–50 mph band:

| I scale | 261 | 263 | 268 |
|---|---|---|---|
| 25 | 0.943 / 0.52 | 0.911 / 0.53 | 0.903 / 0.81 |
| 50 | 0.964 / 0.57 | 0.944 / 0.55 | 0.934 / 0.86 |
| 75 | 0.978 / 0.62 | 0.966 / 0.56 | 0.955 / 0.89 |
| 100 | 0.986 / 0.66 | 0.978 / 0.57 | 0.972 / 0.92 |
| 150 | 0.992 / 0.74 | 0.991 / 0.60 | 0.990 / 0.97 |

More I closes curve undershoot and costs a little on straights. Even at I 25, 268's straights were 0.81°, so most of their looseness comes from the road. The 25 → 75 change adds about 0.08°. 75 (the current setting) is a reasonable middle.

**Sweep 2: `HondaLateralPidKpScale`** (I 75). Each cell is straight rms / sign changes per second in the 25–50 mph band:

| Kp | 261 | 263 | 268 |
|---|---|---|---|
| 0.65 | 0.89 / 0.5 | 0.74 / 0.5 | 1.19 / 0.5 |
| 1.0 | 0.62 / 0.6 | 0.56 / 0.6 | 0.89 / 0.5 |
| 1.25 | 0.50 / 0.7 | 0.47 / 0.7 | 0.77 / 0.5 |
| 1.5 | 0.43 / 0.8 | 0.42 / 0.7 | 0.69 / 0.6 |
| 2.0 | 0.33 / 0.9 | 0.34 / 0.9 | 0.58 / 0.6 |

The curve ratio barely moves with Kp (±0.01). In the sim, more P tightens straights steadily and raises the sign-change rate. Because the sim under-predicts oscillation, anything above about 1.25 is outside what it can vouch for.

**Suggested next on-road step** (sim evidence only):
- Keep I 75.
- Try `LatPScaleStandard` 100 → 115–125, in one step. This band-limited P is nearly the same lever as Kp for 25–50 mph. On 268 in the sim, P 125 gives straight rms 0.80° and curve ratio 0.960; Kp 1.25 gives 0.77°.
- Watch for weave on straights. The sign-change rate in `sweep` output of the new drive is the check.
- Leave low-speed and highway alone until the sim validates there.

## 114. Route 0000026b (48 min, lateral settings as in 268: I 75, Kp 1.0): false driver-override trips cut steering torque in low-speed turns. Replay and log-decode evidence only; no code or setting change.

**Owner report:** slight oversteer at 32:40 and wheel stutter in a right turn at 48:10; otherwise good.

**Mechanism** (log decode, 100 Hz):
- `STEER_TORQUE_SENSOR` reads the column torque. That is the driver's hands plus the reaction to the EPS's own torque, and in hard low-speed turns it reaches 1500–2100.
- With `NrdrDriverOverrideThreshold = 2000` (the code default is 2400), the sensor crossed the threshold in 62 episodes while engaged:
  - 41 were blips of ≤ 0.2 s, peaking at 2001–2394, typically mid-turn with |cmd| around 0.2–1.0.
  - 21 were sustained genuine overrides, peaking at 2125–3480 (median 2824).
- Each blip sets the override ramp to `HondaOverrideTorqueScale = 0` and fades it back up over `HondaOverrideFadeUpSecs = 1.0`. The delivered torque is therefore cut for about a second, and the integrator freezes while `steer_limited_by_safety` holds.
- Below 25 mph, delivered torque was under 50% of the command on 22% of engaged frames.

**The two reported events:**
- **32:40 (15 mph left turn, 137° of wheel).** Turn-in lagged by about 20°. At 32:45.6, 15 pressed frames in 0.9 s cut the torque, and the wheel unwound from 128° to 67° against a desired of about 100–130°. The integrator froze at +0.36, wound up. On the exit the wheel trailed the unwind by up to 18° (32:48.4), then held 1–5° left of desired for about 2 s until the integrator released at 32:51.5. That is the reported oversteer. Whether the driver's hand contributed cannot be separated from sensor reaction in this signal.
- **48:10 (18 mph right turn).** A 3-frame blip to 2042 at 48:12.9 cut the torque from −0.52 to −0.07, with a 1 s fade back: the turn-in stutter. On the exit, the wheel trailed the unwind by 25–45° (48:17) with the torque delivered in full, which is gain- and plant-limited, not a cut. The driver took over at 48:19 (2800–3000).

**Counterfactual on the logged sensor trace** (open loop, so it cannot see the reaction torque change once more torque is delivered):

| Threshold | Fade-up | Episodes (blips) | Torque·s withheld outside genuine overrides | Frames < 25 mph with < 50% delivered | Genuine overrides still over threshold |
|---|---|---|---|---|---|
| 2000 | 1.0 s | 62 (41) | 11.2 | 8.1% | 21/21 |
| 2000 | 0.5 s | 62 (41) | 6.8 | 4.5% | 21/21 |
| 2200 | 0.5 s | 37 (15) | 1.6 | 1.2% | 20/21 (median +30 ms) |
| 2400 | 1.0 s | 25 (8) | 1.3 | 1.5% | 18/21 (median +40 ms) |
| 2400 | 0.5 s | 25 (8) | 0.6 | 0.6% | 18/21 (median +40 ms) |

The 3 genuine overrides that 2400 would miss peaked at 2125–2312. In practice the driver pushes harder, so the cost is a firmer override, not a missed one.

**Other results:**
- **25–50 mph band is good** (logged): curve actual/desired 0.975, straight rms 0.76°. On 268 these were 0.963 and 0.86°.
- **Vehicle model is accurate.** Yaw-rate curvature over angle-derived curvature is 0.99–1.01 from 9 to 50 mph (learned SR 15.14, stiffness 1.35). So the lane-position p99 of 0.52 m, driven by curves at 40–46 mph (37:40 −0.68 m, 40:48 +0.74 m; angle tracked within 0.5°), sits in the planned path, not in PID tracking. The 24:09–24:31 spikes (up to 1.2 m in under 1 s, on straights) look like lane-line detection jumps.
- **Sim sweeps on this route** (plant `plant_260_263`, held out). `LatPScaleStandard` 100 → 115 → 125: straight rms 0.87 → 0.81 → 0.78°, curve ratio unchanged. `LatPScaleLowSpeed` 100 → 125: curve ratio 0.902 → 0.916 (the low band is weakly validated). `LatFScaleLowSpeed` 50 → 100: no effect.

**Correction, same day (owner report plus log decode). Do NOT raise the override threshold.** The owner reports that at 32:40 the car nearly went into the adjacent left lane while another car was also turning left.
- `steeringTorque` (negative = right push) reads −1200 to −1890 almost continuously from 32:42.4 to about 32:51. That is the driver resisting the left turn, and it stayed below the 2000 threshold except at 32:45.6 and 32:48.7. For roughly 6 s, openpilot kept full left torque against the driver.
- The "blips" at 32:45.6 were the crests of a sustained driver push, not sensor reaction. Raising the threshold to 2400 would have left openpilot fighting the driver for the whole turn.
- The desired curvature came straight from the model action. No blinker was on, so the turn hold and turn lead did not engage, and lane centering left it unchanged.
- Actual heading change was 88°. The integrated desired curvature reaches 110°, but that over-counts, because the model re-asks for curvature while the car lags. The car's placement in the lane cannot be recovered: no lane lines are seen during the turn.
- The open design issue is that the raw threshold cannot separate driver push from EPS reaction. A reaction-compensated override (driver torque minus k × delivered torque) would need its own replay before any change.

**Suggested settings** (replay and sim evidence only, not driven):
1. Keep `NrdrDriverOverrideThreshold` at 2000. Do not raise it. `HondaOverrideFadeUpSecs` 1.0 → 0.5 is still reasonable. It only shortens the torque gap after a release, and it does not change when an override is detected.
2. `LatPScaleStandard` 100 → 115.
3. Only after (1) is driven: `LatPScaleLowSpeed` 100 → 125. More low-speed P means more torque, which means more sensor reaction.

## 115. Continuous lateral gain schedule (`LatGainSchedule`) and an offline auto-tuner (`tools/lateral/lat_autotune.py`). Unit-test, replay and sim evidence only; nothing driven; no setting changed.

**Controller (`selfdrive/controls/lib/latcontrol_pid.py`, modified-EPS path):** optional param `LatGainSchedule`, JSON in percent like the band params, e.g. `{"v_mph":[20,30,40,50],"p":[120,110,120,105],"i":[50,75,75,0]}`. The P/I/F trims are interpolated linearly between knots and held flat past the end knots. Any of p/i/f may be omitted; an omitted term keeps its `Lat*Scale` band.
- Validation: 2–8 knots, strictly increasing speeds within 0–100 mph. Limits are P 25–300 %, I 0–300 %, F 0–200 %, all finite.
- Any malformed field rejects the whole schedule, and every term falls back to the bands. An out-of-range knot is never clamped into a value the owner did not write.
- The param is read in the existing 300-frame refresh and registered in `common/params_keys.h` (STRING, default empty). Empty or absent means the behaviour is unchanged.
- Tests: `selfdrive/controls/tests/test_lat_gain_schedule.py` (26 tests).
- Replay on 00000263 through `lat_pid_sim`:
  - a flat schedule gives torque bit-identical to the same flat values set as bands;
  - an invalid schedule gives torque bit-identical to no schedule.
- The two `test_latcontrol.py` failures (Bolt 2022–23 low-speed limit, Palisade taper) and the two `test_accel_profile.py` failures also fail on the base tree without this change.

**Tuner (`tools/lateral/lat_autotune.py`)** builds on `lat_pid_sim`, with tests in `tools/lateral/tests/test_lat_autotune.py`. It prints a schedule for the owner to review and never writes a param.
- **Seed:** it starts from the current bands (or an existing schedule) plus `--set`. The default knots are 20/30/40/50 mph, so above 50 mph the seed is exactly the highway band.
- **Trust gate:** per band, the sim at the driven tuning is compared with the log. The band is untrusted if err rms or straight rms differ by more than 25 %, or the curve ratio by more than 0.05.
  - Knots in an untrusted band are frozen.
  - An untrusted band may not get worse on all data: err or straight rms by more than 1 %, or straight sign-change rate by more than 10 %.
- **Search:** best-improvement coordinate search with steps 10/5/2.5 points, within ±25 points of the seed.
  - The per-band cost is relative to the seed, so the large turn errors below 25 mph do not drown the other bands.
  - Scoring uses alternate 2-minute blocks of the drive. The other blocks are holdout and decide the verdict: the holdout total must improve, and no trusted band may get worse by more than 2 %.
- **Two faults found in the first runs:**
  - The first run blended I 75 → 0 across 45–55 mph. That added I on the highway and raised highway sign changes from 0.27 to 0.42 /s. The untrusted-band guard missed it, because each half had under 3 minutes of highway. Fixed with the all-data guard and the 20/30/40/50 default knots.
  - The second run was vetoed by a strict 1.00× rule over a highway err rms change of 0.758 → 0.759°, which is carry-in from the blend. The tolerance is now 1 %.

**Run on 0000026b + 00000263, current owner tuning:** P 100/100/105, I 50/75/0, F 50/100/100; plant `plant_260_263`; 96 closed-loop evaluations.
- Gate: low band trusted (9.8 min), standard trusted (29.6 min).
- Highway untrusted: err rms sim 0.76 vs log 0.58°, curve ratio sim 0.738 vs log 0.851. Knots at 50 mph were frozen.
- Holdout total, relative to the seed: current bands 0.952, proposed 0.932, about 2 % better.

| Band (all data) | err rms | straight rms | curve ratio | straight sign changes |
|---|---|---|---|---|
| < 25 mph, current → proposed | 12.74 → 12.25° | 3.12 → 2.89° | 0.882 → 0.897 | 0.66 → 0.67 /s |
| 25–50 mph | 1.109 → 1.058° | 0.743 → 0.712° | 0.967 → 0.955 | 0.62 → 0.66 /s |
| > 50 mph (untrusted, frozen) | 0.758 → 0.759° | 0.583 → 0.584° | 0.738 → 0.738 | 0.27 → 0.26 /s |

Candidate (sim evidence only, not driven): `LatGainSchedule = {"v_mph":[20,30,40,50],"p":[120,110,120,105],"i":[50,75,75,0]}`

**Read before trying it:**
- The gain is small, about 2 % on holdout. It is mostly more P below 25 mph and at 35–45 mph.
- The 25–50 mph sign-change rate rises 6 % and the curve ratio drops 0.967 → 0.955. The drop comes from the 40–50 mph I blend (75 → 0) replacing the 50 mph step.
- The plant under-predicts oscillation.
- The sim does not model driver-override trips. Item 114 found that EPS reaction torque from low-speed torque trips the 2000 threshold in turns, and P 120 below 20 mph adds torque exactly there.
- Desired curvature is exogenous, so model-path problems like 26b 32:40 are invisible to the tuner.
- If driven, compare the next route's low-speed turn override crossings and 25–50 mph straight rms against 26b before keeping it. Clearing `LatGainSchedule` returns to the bands.

**Stage 3 (on-device adaptive tuning)** is deliberately not built. It waits until an offline schedule from this tool has been driven and shown to match the sim's prediction.

## 116. On-device adaptive P trim, prototype (`LatAdaptiveTune`, default 0 = off). Unit-test and log-replay evidence only; nothing driven; no setting changed.

The owner asked for a prototype of item 115's stage 3 before an offline schedule had been driven, so it is built but off by default. It is meant to run in **shadow** first.

**What it is:** `selfdrive/controls/lib/lat_adaptive_tune.py`, hooked into `LatControlPID` on the modified-EPS path only. Tests are in `selfdrive/controls/tests/test_lat_adaptive_tune.py` (29 tests).
- **One knob:** a multiplicative factor on the P trim at knots 20/30/40/50 mph, interpolated like `LatGainSchedule` and applied after the bands and the schedule. I and F are not touched.
- **Bounded:** 0.85–1.15. It moves at most one 0.05 step per knot per drive, and neighbouring knots may differ by at most 0.10.
- **Never mid-drive:** during a drive it only measures. Statistics are saved to `LatAdaptiveStats` once a minute with `put_nonblocking`. The step happens at the next controlsd start and is written to `LatAdaptiveState`.
- **What it measures:** engaged, hands-off frames above 4 m/s, with no blinker and not steer-limited, split between the two neighbouring knots. It uses the same definitions as `lat_pid_sim` metrics(): straight is |desired| < 3°, curve is |desired| > 5°. It records:
  - straight rms error;
  - straight error sign changes per second, counted on consecutive straight frames only;
  - curve ratio (achieved / desired);
  - driver-override onsets per engaged minute.
- **Rules per knot,** in order. A knot needs ≥ 3 min of data, and a shorter knot's data carries over into the next drive.
  1. Revert. Only in apply mode, and only after an up-step, if sign changes rose > 15 % or onsets rose > 25 % + 0.2/min.
  2. Down if sign changes > 1.0/s.
  3. Down if the curve ratio > 1.03.
  4. Up if the curve ratio < 0.95 **and** sign changes < 0.8/s **and** onsets < 1.5/min.
  5. Otherwise hold.
- **Modes:** `LatAdaptiveTune` 0 = off, with no Params reads beyond the mode and no writes; 1 = shadow, which learns and stores but always applies 1.0; 2 = apply. Any Params error turns it off for the drive.
- **Tuning fingerprint:** the state stores a hash of the manual lateral gains (`TUNING_KEYS`: P/I/F bands, `LatGainSchedule`, Kp/Ki scale, centre scale/boost, LPF taus, override fade/scale, and `NrdrLatUseFirmwareVgr`).
  - If any of them differs at start, the factors reset to 1.0 and the previous drive's statistics are dropped.
  - `last` then reads `reset: manual lateral tuning changed`.
- **Params:** `LatAdaptiveTune` (INT, 0), `LatAdaptiveState` and `LatAdaptiveStats` (STRING), all in `common/params_keys.h`.
- **Mode 0 changes nothing:** the `lat_pid_sim` replay of 00000263 is unchanged, torque |sim−log| median 8.9e-4. `test_latcontrol.py` has only the two failures that item 115 already showed fail on base.

**Log replay, all 19 extracted routes in drive order (00000232 → 0000026b), shadow mode, with carry-over:**

| Knot | Minutes (all routes) | Straight rms | Sign changes | Curve ratio | Override onsets |
|---|---|---|---|---|---|
| 20 mph | 39.9 | 1.76° | 0.53 /s | 0.911 | 15.3 /min |
| 30 mph | 45.4 | 0.83° | 0.67 /s | 0.942 | 3.4 /min |
| 40 mph | 71.7 | 0.56° | 0.75 /s | 0.955 | 1.4 /min |
| 50 mph | 99.6 | 0.46° | 0.82 /s | 0.947 | 0.8 /min |

- **20 mph never steps up.** Onsets are 6–32/min on every route, far over 1.5. This is intended, because item 114 found EPS reaction torque trips the 2000 threshold in low-speed turns, and more P there makes it worse. The learner cannot tell those from real driver input, so it simply refuses to add P there.
- **30 mph** stepped up once, on 237 (curve ratio 0.948). It was then held by onsets of 1.6–3.3/min on later routes.
- **Sign changes** per drive with ≥ 10 s straight range from 0.36 to 1.17/s. Only 23a at 40 mph (1.02, 1 min) and 262 at 50 mph (1.17, 1.5 min) exceed 1.0, and both are too short to act on alone. With carry-over, no knot ever stepped down.
- **A fault the replay found and fixed:** without the fingerprint, 40 mph walked 1.0 → 1.15 on 25f, 261 and 263, while the standard-band I was 25. P was covering an I shortfall. After I went back to 75 (268, 26b), the curve ratio returned to 0.977, inside the dead band, and 1.15 would have been held on the new tuning indefinitely. With the fingerprint, each tuning change (245 → 25b, 263 → 268, 268 → 26b) resets it.
- **Final state on the current tuning** (P 100/100/105, I 50/75/0, 26b): all four knots hold at 1.00. At 30 mph the curve ratio is 0.916, but onsets of 2.7/min block the step-up.

**What this means:** on the owner's logged driving this learner would almost always hold. The metrics sit inside the dead band, or the up-step is blocked by override onsets. It adds no P the owner has not already tried. In apply mode it could not have caused the 26b 32:40 or 48:10 events. It also would not have fixed them.

**Why it trims only P, not I or F** (a design choice; for the owner write-up):
1. **The three metrics cannot tell the terms apart.** A curve shortfall can be closed by more P, more I or more F. With three knobs on the same signals, the learner could trade one against another and never settle. The replay already showed this with one knob: 40 mph walked P to 1.15 to cover I 25, which is the fault the tuning fingerprint now resets. Letting it move I would make that kind of trade-off the normal case.
2. **I is the risky term, and a 3-minute-per-knot drive cannot judge it.**
   - I acts slowly. Its failure modes are slow weaving and windup carried past an override or out of a curve.
   - In the sim, adding I on the highway raised straight sign changes from 0.27 to 0.42 /s (item 115); that is why highway I is 0.
   - The integrator also freezes during override trips. Below 25 mph those come from EPS reaction torque at 6–32 per minute (item 114), so I measured there is distorted.
3. **F already has a learner, and there is no evidence F is the wrong setting.**
   - Feedforward is desired curvature times the car's steering response. openpilot already learns that response live (steer ratio, stiffness, angle offset: `NrdrLearn*`), and a second learner on F would fight it.
   - In the sim, `LatFScaleLowSpeed` 50 → 100 had no effect (item 114).
4. **One bounded knob keeps it auditable.** One number per knot, capped at ±15 %, one step per drive, with a reason for each step in `LatAdaptiveState`. I and F stay under the owner's manual control.

Adding I or F later would need a signal specific to that term, then sim validation first:
- **For F:** the curve-entry shortfall, before I has time to build.
- **For I:** the residual error mid-way through a long, steady curve.

That should wait until the P-only version has run in shadow for a while and its steps match what the owner feels.

**How it sits with the firmware VGR table:**
- All 19 replayed routes ran with `NrdrLatUseFirmwareVgr` = 1. The car is Civic Bosch with the `VGR_CIVIC_TBA_C020` flag set, so the firmware A table was in effect. It warps the angle that `VehicleModel` computes from the paramsd-learned `sR` into the target wheel angle.
- The tuner measures tracking of that target in steering-wheel degrees, after the map. A map error (the firmware table corrects only the VGR pinion, not the whole chain) changes the path, not the tracking. The model corrects it by asking for a different curvature, so the tuner holds rather than covering it with P.
- Switching the map (firmware table ↔ road-measured curve) moves the centre gain by about 10 % and changes the taper. It is therefore in `TUNING_KEYS` and resets the state.
- The paramsd-learned `sR` is not in `TUNING_KEYS`, because it drifts continuously.
- The replay above is unchanged by this, since the map setting never changed across the 19 routes.

**Limits (read before enabling apply):**
- Desired curvature is exogenous here too. A model-path error looks like a tracking error to the learner.
- An override onset is either the driver or EPS reaction torque (item 114). Both count, so the learner errs toward not adding P.
- The revert rule (1) has only been exercised in unit tests; no real drive has run in apply mode.
- The thresholds (0.95/1.03 curve ratio, 0.8/1.0 sign changes, 1.5 onsets/min) are checked against these 19 routes only. They are not tuned on closed-loop outcomes.

**To try it:**
1. Set `LatAdaptiveTune=1` (shadow). Drive a few times. Read `LatAdaptiveState`: `factor` is what apply mode would use, and `last` gives the reason for each knot.
2. Consider `LatAdaptiveTune=2` only if the shadow factors stay near 1.0, move for reasons that match what the owner feels, and do not ping-pong.
3. To reset, clear `LatAdaptiveState`. To remove it from the loop, set `LatAdaptiveTune=0`.

**Handoff: Galaxy toggle and owner write-up (not done here; for the next agent).**
- **Toggle:** add a `LatAdaptiveTune` row to `starpilot/common/assets/device_settings_layout.json`.
  - Place it under `LateralTune` (`"parent_key": "LateralTune"`, `"settings_tier": "advanced"`), after the `Lat*Scale*` rows.
  - Use a 3-way `"ui_type": "dropdown"` with `"data_type": "int"`, patterned on `AccelerationProfile`: 0 Off, 1 Shadow (learn only), 2 Apply. A bool toggle cannot express shadow mode.
  - It only matters on the modified-EPS PID path; the tuner is never constructed elsewhere.
- **Optional:** a reset action that clears `LatAdaptiveState`, and a read-only view of its `factor` and `last`. Read-only is enough; the owner should never hand-edit the state.
- **Item 12 applies:** Galaxy's `allowed_keys` comes from the compiled `common/params_pyx.so` registry, not the header. Until the device runs a build with the three new keys, the row will show "not editable". A device without the keys is harmless: `LatAdaptiveTuner` catches the unknown-key error and runs as off.
- **Write-up:** the owner-facing description should be drawn from this item (what it measures, the rules, the 0.85–1.15 bound, one step per drive, the reset on manual tuning change, why it trims only P, shadow first). Keep the evidence level: unit-test and log replay only, not driven.

### 116a. `LatAdaptiveTune` Galaxy dropdown (live) and params artifacts. Unit-test and static evidence only; not driven, not seen on device.

The item 116 handoff is done.
- **Galaxy row:** `LatAdaptiveTune` under `LateralTune`, after the `Lat*Scale*` rows. It is an advanced-tier `int` dropdown with 0 Off, 1 Shadow (learn only), 2 Apply. It has no `requires_offroad`, so it can be changed while driving.
- **Live mode:** `LatControlPID` calls `LatAdaptiveTuner.refresh_mode()` in its 300-frame (3 s) param refresh, the same refresh the `Lat*Scale` rows use.
  - Off → Shadow/Apply mid-drive loads the state and takes this drive's one step, with non-blocking writes.
  - Shadow ↔ Apply only changes what `p_factor()` returns. Going to Apply applies the stored factor at once, a P step of at most ±15 %.
  - → Off returns P to 1.0 at once, saves the stats collected so far and pauses learning.
  - Only the mode is live. The factors still step at most once per drive.
- **Tests:** 4 new tests in `TestLiveMode`; 58 pass across `test_lat_adaptive_tune.py` and `test_lat_gain_schedule.py`.
- **Params artifacts:** `common/params_pyx.so` and `common/libcommon.a` were rebuilt with the Docker larch64 recipe (Cython 3.1.4) and now have 853 → 857 keys. The 4 new keys are `LatAdaptiveTune` (default 0), `LatAdaptiveState`, `LatAdaptiveStats`, and `LatGainSchedule` (item 115), which was in the header but missing from the binary. Before this rebuild, Galaxy would have returned 403 "not editable" for all four (item 12).

### 116b. Items 116 and 116a reverted (owner request, 2026-09-24).

The owner wants the adaptive lateral tuner rebuilt in the Galaxy FLM format instead. That means up to 8 selected routes, learning on the device while the car is off, results kept as separate trials, and a revert per trial.
- **Removed:** `lat_adaptive_tune.py` and its tests, the `LatControlPID` hook, the Galaxy `LatAdaptiveTune` row, and the three `LatAdaptive*` keys.
- **Params artifacts:** rebuilt, 857 → 854 keys. `LatGainSchedule` (item 115) stays in the binary.
- **Kept:** the item 116 text above, as the design record for the rebuild. Its rules, thresholds and 19-route replay findings still apply.

## 117. Lateral Tune workspace: item-116 P trim rebuilt FLM-style (routes → offroad trial → apply/revert). Unit-test and static evidence only; nothing driven; no setting changed by default.

Replaces the reverted on-road tuner (116/116b) with the FLM workflow the owner asked for.

- **Analyzer** `selfdrive/controls/lib/lat_tune_analyzer.py`: the item-116 rules verbatim, **per StarPilot PID speed band** since `e0ba9af8a` (LowSpeed < 25 mph, Standard 25–50, Highway ≥ 50, hard steps exactly as `_lat_pid_scale_banded`; before that, triangular-weighted knots at 20/30/40/50 mph) ( factor 0.85–1.15, one 0.05 step per trial, neighbour gap ≤ 0.10, ready at ≥ 3 min per band, straight < 3°, curve > 5°; down on sign-rate > 1.0/s or curve ratio > 1.03, up on curve ratio < 0.95 with sign-rate < 0.8/s and onsets < 1.5/min). Frames come from rlogs (`controlsState.lateralControlState.pidState` + `carState`); the current `LatPScale*`/`LatIScale*`/`LatFScale*` per band are read from the newest route's `initData`; proposed band P = current × factor on the Galaxy 5 % grid (a step never rounds away to nothing); I and F are shown and never proposed (item 116). One trial = one step: the logs were driven with one gain, so compounding steps across routes would have no evidence behind it.
- **Galaxy** `Tools → Lateral Tune` (`/lat_tune`, classic UI): pick up to 8 local routes, Analyze runs `lat_tune_workspace.py worker` detached (`nice -n 19`, status in `/tmp/galaxy_lat_tune_status.json`, cancelled the moment `IsOnroad` goes true), trials stored at `/data/galaxy/lat_tune/trials/<id>.json` with per-band minutes / readiness / metrics / factor / reason / current P/I/F / proposed P. **Apply** writes `LatPScaleLowSpeed/Standard/Highway` (INT) and drops a `p` term from `LatGainSchedule` if one is set (it would override the bands), after snapshotting all four prior values into the trial; pre-band (schema 1) trials are refused; applied trials form a stack in `active.json` and only the top can be **reverted** (restores all four prior values exactly, or removes keys that were unset). Apply is refused (409) when the device's manual tuning fingerprint (the 116 `TUNING_KEYS`) differs from the one the routes were driven with, unless forced. Analyze, apply and revert are all parked-only (FLM gates only analyze; a live lateral gain deserves the stricter default).
- **API** `/api/lat_tune/{workspace,status,analyze,analyze/stop,trial/<id>[,/apply,/revert]}` mirrors `/api/flm/*` (404/400/409 mapping).
- **CLI for when the comma is unreachable** `tools/lateral/lat_tune_cli.py --routes-root <dir> --latest 8 [--json trial.json]` runs the same analyzer over the newest ≤ 8 route dirs (Konik `<dongle>/<time>--<seg>` layout accepted) and prints the per-band table (P/I/F now → P new) plus `LatPScaleLowSpeed = N` / `Standard` / `Highway` lines to set in Galaxy.
- **No new Params keys**, so the aarch64 params artifacts stay at 854 keys; workspace state is files only.
- **Evidence:** 29 analyzer tests, 10 workspace tests, 3 route tests, 4 CLI tests pass in `oprad-test:py312` (Galaxy files run one per process with flask + pillow pip-installed into the throwaway container, since the image lacks them); dashboard_stats 70 + its 2 pre-existing failures, longitudinal_mode_api 20, frontend_module_graph 11, device_settings_layout 29, lat_gain_schedule 26, latcontrol 171 + the 2 known base failures. Classic page render-checked static on the Mac: the real assets and CSS served with mocked `/api/lat_tune/*` and `/api/routes`, screenshotted in headless Chromium (not the full Galaxy server). That check caught body text inheriting black on the dark cards; fixed by setting `var(--text-color)` as FLM's cards do. Not driven; no replay against real routes yet — run the CLI on the Konik archive next and record the proposed factors here before anyone applies a trial.
- **Mobile panel (2026-09-24):** `Tuning → NRDR PID lateral tune` (`/tuning/nrdr-pid`, `NrdrLatTunePanel.js`) is the mobile Vue face of the same `/api/lat_tune/*` endpoints: route picker (max 8), status, trials with per-knot details, apply (force retry only after a fingerprint refusal), revert of the stack top only, delete. `test_ui_vue_frontend` 31 pass; static render check at 390 px against mocked endpoints only, not driven, not seen on device.
- **First real run, CLI, offline replay (2026-09-24) — superseded by the 3-band re-run below; the `LatGainSchedule` line in it must not be applied:** the owner's 8 newest Konik routes `11c8fa231c0499ed|00000262--864cc3c6db`, `…263--b8afdda0eb`, `…264--da75030df6`, `…265--28d99bed88`, `…266--f766f599f0`, `…267--e83a1fa671`, `…268--4bc9811934`, `…26b--92b1979afa` (164 rlog segments; `…269`/`…26a` skipped as empty). 22 segments had no engaged pidState frames (disengaged stretches, mostly `…26b` 0–7 and 18–22).

  | knot | minutes | sign/s | curve ratio | overrides/min | factor | P% |
  |---|---|---|---|---|---|---|
  | 20 mph | 15.0 | 0.53 | 0.922 | 17.10 | 1.00 hold | 100 |
  | 30 mph | 17.2 | 0.62 | 0.924 | 4.25 | 1.00 hold | 100 |
  | 40 mph | 33.9 | 0.73 | 0.940 | 1.44 | **1.05 up** | 100 → **105** |
  | 50 mph | 30.1 | 0.82 | 0.936 | 1.37 | 1.00 hold | 105 |

  Proposed setting: `LatGainSchedule = {"v_mph":[20.0,30.0,40.0,50.0],"p":[100.0,100.0,105.0,105.0]}`. The analyzer reads `curve ratio < 0.95` everywhere as under-steer on curves, but at 20/30/50 mph the sign-change or override rate vetoes the step (the 20 mph override rate of 17/min is town turning with the wheel held, not an oscillation). So the only change is +5 % P at 40 mph. **Caveat:** the routes were not driven on one tuning: `LatIScaleStandard` is 25 on `…262` and 75 on `…26b`, and the fingerprint mismatch warning fired, so the baseline is `…26b`'s tuning (`LatPScaleStandard 100`, `LatPScaleHighway 105`). Offline replay only; the proposal has not been applied or driven. The trial JSON is `/routes/an2/lat_tune_trial_262-26b.json` in the `oprad-routes` volume. The CLI's Konik-layout discovery fix is `1965657c0`.
- **Re-run on StarPilot's 3 PID speed bands (2026-09-24, owner request: match the Galaxy PID settings, 3 bands × P/I/F; see PR #6).** Same 8 routes, 164 segments (22 with no engaged pidState frames), offline replay only:

  | band | minutes | sign/s | curve ratio | overrides/min | factor | P / I / F now | P new |
  |---|---|---|---|---|---|---|---|
  | LowSpeed 0–25 mph | 15.1 | 0.50 | 0.916 | 16.83 | 1.00 hold | 100 / 50 / 50 | 100 |
  | Standard 25–50 mph | 73.4 | 0.74 | 0.944 | 2.10 | 1.00 hold | 100 / 75 / 100 | 100 |
  | Highway 50+ mph | 7.7 | 0.83 | – (< 30 s of curve) | 1.83 | 1.00 hold | 105 / 0 / 100 | 105 |

  **Result (superseded by the override-episode re-run below): no change proposed** (`LatPScaleLowSpeed = 100`, `LatPScaleStandard = 100`, `LatPScaleHighway = 105`). The old +5 % at the 40 mph knot does not survive banding: its minutes now pool with 25–40 mph town driving, and the Standard band's override-onset rate (2.10/min) is above the 1.5/min step-up veto. Highway has only 7.7 min at ≥ 50 mph (the old 50 mph knot borrowed 40–50 mph minutes through the triangular weights) and no curve data, so there is no up/down evidence there. The values shown are the newest route's (`…26b`) logged tuning, including `LatIScaleHighway = 0`; the routes were driven on mixed tuning (fingerprint warning). Trial JSON: `/routes/an2/lat_tune_trial_bands_262-26b.json`; route logs deleted from the volume after the run. Tests after the rework: analyzer 39, workspace 12, API 3, CLI 5, test_ui_vue_frontend 31, frontend_module_graph 11; both Galaxy panels render-checked statically with band mock data. Not applied, not driven.
- **Re-run with 15 % steps and override episodes (2026-09-24), offline replay, same 8 routes:** two analyzer changes. (1) Curve steps are sized to the shortfall, 5–15 % per trial (owner: "up to 15 % per trial"); sign-rate step-downs stay 5 %. (2) The override veto counts **override episodes**: a press starting within 1.5 s of the previous pressed frame joins the same override (`PRESS_MERGE_FRAMES`). The reason: at `NrdrDriverOverrideThreshold` 2000 a driver fighting the wheel makes `steeringPressed` flicker, because each press cuts the torque, the reading drops under the threshold, the 1.0 s fade-up brings the torque back, and it trips again. Across the 8 routes, 723 of 724 engaged press onsets had ≥ 0.2 s of |steeringTorque| > 1000 within ±1 s, and only 1 of the 724 looked like an isolated sensor spike. So the short presses are real driver effort, not noise, and they should be merged, not dropped. Episodes vs onsets: LowSpeed 185 vs 530, Standard 63 vs 179, Highway 4 vs 15. The fade-up frames were already left out of the metrics by the `steer_limited` check (carControl vs carOutput torque).

  | band | min | sign/s | curve ratio | override episodes/min | P now → proposed |
  |---|---|---|---|---|---|
  | LowSpeed 0–25 | 15.1 | 0.50 | 0.916 | 4.14 (veto > 1.5) | 100 → 100 |
  | Standard 25–50 | 73.4 | 0.74 | 0.944 | 0.75 | **100 → 105** (shortfall 6 % → one 5 % step) |
  | Highway 50+ | 7.7 | 0.83 | – | 0.49 | 105 → 105 (no curve data) |

  What-if `--baseline LatPScaleStandard=115`: the same metrics give 115 → 120. Those metrics were measured at P 100, so this only says the evidence doesn't argue against 115; it doesn't show that 115 is better. The analyzer's own evidence supports **105**. Trial JSONs: `/routes/an2/lat_tune_trial_bands_262-26b_ep.json` and `…_ep115.json`. Tests: analyzer 48, CLI 6, workspace 12. Not applied, not driven.
- **Route `…26b` 32:40 left swerve (log decode, offline):** at 15 mph (6.8 m/s), from about 32:38.5 the model lost both lane lines (probabilities 0.7 → 0.01) and its path swung up to 9 m left, with no blinker. The PID followed it: desired curvature −0.064, actual −0.054, steering +128°. The driver resisted from about 32:40.4 at 1500–1990 torque, but at threshold 2000 (the centre-boost threshold was also 2000) the first press registered only at 32:43.7, **about 3 s late**. Seven 0.02–0.04 s presses followed through 32:45.2, then a 0.25 s press peaking at 2578 at 32:46.6. The cause was the model's path, not the gains; a higher P would have turned harder. **At 2400 only the 32:46.6 press would have registered**, so raising the threshold to cut "blips" would have lengthened this event. Offline log reading only.
- **Settings shipped (2026-09-24, owner request):** `migrate_nrdr_lat_tune_2026_09_24` in `system/manager/manager.py` writes the lateral settings once at the next boot, then sets the flag `/data/nrdr_lat_tune_2026_09_24_v1`. The values are what `…26b` was driven with, from its initData, except `LatPScaleStandard` 100 → 105:
  - `LatPScale` Low/Std/Hwy 100/105/105, `LatIScale` 50/75/0, `LatFScale` 50/100/100;
  - `NrdrDriverOverrideThreshold` 2000, `NrdrOverrideThresholdCenterBoost` 2000;
  - `HondaOverrideFadeUpSecs` 1.0, `HondaOverrideFadeDownSecs` 0.0.

  It overwrites the keys unconditionally, and on any device running this branch. Later slider changes persist. Evidence: unit test only; the 105 is not driven yet.

## 118. HumanAcceleration and HumanFollowing built in (FrogPilot logic, no toggles), keeping StarPilot's 3 s closing-TTC fallback. Unit-test and replay evidence only; not driven.

*What changed.*
- **HumanAcceleration** (owner approved; `starpilot_acceleration.py`, `longcontrol.py`): FrogPilot-Testing 728f65472's
  `get_max_accel_low_speeds` and `get_max_accel_ramp_off` are always applied (throttle side only; braking untouched).
  The longcontrol starting state now outputs `a_target` instead of the `startAccel` shove, as FrogPilot does. Honda has
  no `CP.startingState`, so the Civic goes stopping → pid and the launch half has no effect on it.
- **HumanFollowing** (`long_mpc.py build_model_lead_trajectory`, `longitudinal_planner.py`): the model lead path is always
  on and follows FrogPilot: radar dRel/vLead anchor plus the model's future x/v deltas, gated on model lead prob >
  `LeadDetectionThreshold` (default 0.35, was a fixed 0.5), clipped by `min_x_lead`, and bounded by `x_lead_max` (the
  distance the lead's speed can cover). `human_following_model()` is gone.
- **Kept, StarPilot only:** the 3 s closing-TTC fallback (closing > 0.75 m/s and dRel/closing < 3 s → raw aLeadK
  extrapolation). FrogPilot has none.
- `starpilot_variables.py` sets `human_acceleration`/`human_following` True; the params are no longer read.
- **Left for the owner:** the HumanAcceleration/HumanFollowing rows in `selfdrive/ui/layouts/settings/starpilot/longitudinal.py`,
  `starpilot/common/assets/device_settings_layout.json` and `starpilot/common/safe_mode.py`. The agent's edit to remove them
  was blocked by the permission classifier. The toggles are visible but inert.

*Why the fallback stays (replay; `tools/longitudinal/alpha_closed_loop_replay.py --human-ab [--vision-only]`, variants
`human_off`, `frog` = FrogPilot without fallback, `frog_guard` = with it; 22 routes 20c-26b, fused and radar dropped).*
- HumanFollowing itself: with fusion it takes the big brakes off (26b 1605.4 −3.45 → −1.72, 1709.7 −3.45 → −1.73; 268
  595.0 −3.47 → −2.16). With radar dropped it matters little (26b 1798.6 −3.42 vs −2.85). FrogPilot's path is the same
  as or firmer than StarPilot's old one and never softer or later on a protected brake.
- Fallback trip frames: 1023 fused, 725 radar-dropped. Brake episodes: 234 and 241. Changed by the fallback (min > 0.3 or
  −1.5 crossing > 0.2 s): 4, all fused, all real in-lane leads, each firmer, none later: 236 557.1 −2.65 → −3.03,
  23e 670.1 −2.89 → −3.29, 23e 2639.4 −3.11 → −3.49, 25f 483.1 −3.03 → −3.45 (a near-stopped car at 60 m, radar
  and vision agree, closing 10-13 m/s; the checker's `genuine` flag missed it). Radar-dropped: 0 changed.
- Against stock ACC (the owner's Honda Sensing check). 25b is the only stock-long rlog, 281 s engaged.
  - At 25b 2658-2661 (replay time 1339), stock ACC_CONTROL.ACCEL_COMMAND began braking at TTC ≈ 6.5 s. It reached −1.1
    at 5.5 s and −3.0 (its maximum) at 4.1 s; the lowest TTC was 2.5 s, and there was no stock FCW. The fallback trips
    once on this drive, at TTC 2.76, while stock is already at −3.0.
  - Owner-supplied Honda CMBS stages, unverified (Honda publishes no numbers): FCW about 2.0-2.4 s, light brake
    1.4-1.6 s, full AEB 0.8-1.0 s. 3 s sits between stock ACC's onset and CMBS stage 1.
  - Alpha long silences the Bosch radar ECU (`honda/interface.py:475`), so CMBS cannot back it up.
  - At that 25b event every variant plans −3.47 but crosses −1.5 about 0.9 s after stock's command. This is the known
    item 74 onset gap, not the fallback's doing. It is open-loop (the log is stock braking), so not conclusive.

*Tests.* `test_longitudinal_planner.py`, `test_leads.py`, `test_longcontrol.py`, `test_starpilot_acceleration.py`: 617 pass.
- Toggle and startAccel tests were rewritten: the launch follows `a_target`, and the limits apply with the toggle on or off.
- New: `test_model_lead_trajectory_follows_lead_detection_threshold`.
- The two urgent-raw-lead fallback tests pass unchanged.
- The full-directory xdist run hung on a worker (`test_leads::test_radar_fault`); that file passes alone in 3 s.

*Open.* A staged alpha-side warning or brake mirroring CMBS stage 1 (about 2.4 s) was raised, not built. It needs its own
replay study and the owner's go-ahead.

### 118a. Correction: the stock-ACC check covers all 8 stock-long routes, not one. Replay evidence only; not driven.

Item 118 cited 25b as "the only stock-long rlog", from the item-74 census. Item 89 already lists 8 stock-ACC routes, all
driven with ICBM: 25b, 25d, 25e, 25f, 260, 261, 262, 263. About 4,760 s of cruise, ACC_CONTROL on bus 1. Braking
from an ICBM-lowered set speed (set < vEgo − 0.5) is excluded. Scripts `/tmp/stock_ttc.py`, `/tmp/stock_an2.py`, not
committed.

- **Fallback trips (closing > 0.75 m/s, TTC < 3 s, model prob > 0.35):** 18 episodes.
  - 16: stock was already braking (command < −1) 0.3-7.9 s before the trip, at TTC 3.8-16 s. At the trip it commanded
    −1.1 to −3.1; the lowest per episode ranged −1.2 to −4.0.
  - 2: stock stayed silent. Both are item 89's "closing lead, stock silent" cases, and the driver took over within
    1-2 s each time: 25f 2:45, 22 m at −7.5 m/s; 261 6:54, 34 m at −11.3 m/s. These are where the fallback is meant to
    act.
- **Stock hard-brake onsets (command < −1.5) on a closing radar lead:** 14. TTC at onset had median 6.5 s, p25 5.3 s,
  range 1.9-21 s. Only 2 were under 3 s, both on 25f at under 8 m/s and about −1.5.
- **Planner vs stock on 28 stock-route brakes** (open loop; `g_*_0.json`, frog_guard vs the logged command):
  - Reaching −1.5: the planner is a median 0.25 s earlier than stock (range 5.3 s earlier to 1.05 s later).
  - Deepest brake: median −2.66 vs stock −2.23.
  - The fallback changes one brake by more than 0.3: 25f 483.1, −3.03 → −3.45, where stock settled at −1.8. There the
    planner reaches −1.5 0.35 s after stock, so the firmer brake comes from the late start, not from the 3 s threshold.
    Lowering the threshold would soften that brake and leave the late start.
- **Conclusion:** keep 3 s. Across the 8 stock routes it never trips where stock ACC was calm and the driver did not
  take over. The open item is still the planner's late start against stock on some closings (25b 22:19 +0.85 s,
  25f 8:03 +0.35 s, 262 6:19 +1.05 s), item 74.

## 119. Late brake start vs stock ACC: two fixes shipped (comfort-floor pass for persistent MPC lead braking, merge-floor release). Replay evidence only; not driven.

**Question (owner, 2026-09-25).** On some closing leads the alpha planner reaches −1.5 later than stock ACC (item 74; item 118a listed 8 such brakes on the 8 stock-long routes).

**Method.** Per-frame line trace of `LongitudinalPlanner.update` (which line last set `output_a_target`, plus the accel limits and merge floor) on 25b 1338.9, 262 379.4, 25e 318.1 and 25f 483.1. Then `alpha_closed_loop_replay.py --late-ab` on all 22 routes. The replay is open loop (ego follows the logged drive), so onset times are indicative.

**Causes found.**
1. **Comfort-floor clip lag (systematic).** The final `np.clip(output_a_target, output_accel_min, …)` uses `accel_limits_turns[0] = min(cruise floor −1.0 / ECO −0.5, a_desired + 0.05)`. `a_desired` is the MPC one step ahead, not at `action_t`, so any MPC lead brake below the cruise floor was held back and trailed the MPC. This is the mechanism of items 45/46, whose counterfactual had never been run. 25e 318.1: MPC −1.5 at 319.0, stock ACC 319.92, output 320.92.
2. **Lane-change merge floor (25b 1338.9).** During a real lane change (starting 1336.0, finishing 1340.6) `get_lane_change_merge_accel_floor` held −0.4 for 1.3 s while the MPC asked −1.5…−4.2 and the lead braked 3–5 m/s² down to TTC 2.6. Its 4 s TTC gate uses the current closing speed only. Holding `a_desired` at −0.4 also kept cause 1's floor at −1.0.
3. **MPC gentler than stock on a slow-closing follow (262 379.4).** At ~20 m the MPC asked −0.93 where stock went −1.5. Not addressed.

**Fixes (`longitudinal_planner.py`).**
- **A.** `MPC_LEAD_BRAKE_PASSES_COMFORT_FLOOR`, `get_mpc_lead_brake_accel_min`. The final clip's floor is lowered to the MPC demand when that demand has been lead-sourced (`lead0`/`lead1`) for `MPC_LEAD_BRAKE_PERSIST_TICKS = 3` ticks from a lead that is closing or braking (the existing `LEAD_CLOSING_FLOOR_VREL`/`_ALEAD` test). It uses the mildest of those 3 ticks.
  - A first version without the persistence and closing gate let **phantom source-switch spikes** through: 25f 634.9, a vision lead at 89 m closing 0.2 m/s, went to −2.78; 0237 796.0 went to −1.68. The comfort floor had been acting as a spike filter. The gated version leaves both unchanged.
- **B.** `LC_MERGE_RELEASE_MPC_DEMAND = −1.5`. The merge floor lets go when the MPC lead demand is below −1.5 inside `LC_MERGE_TTC_ACCEL` (6 s).

**Replay, 22 routes, pre-119 (`late_off`) vs shipped.**
- 225 episodes. 122 changed, 0 softer by more than 0.3 and 0 later by more than 0.2 s at −1.5. Median crossing 0.20 s earlier. Every changed episode has a closing radar lead.
- Frames below −1.5: 8,056 → 8,852. Below −2.5: 2,182 → 2,510.
- Against stock ACC (37 stock −1.5 brakes on the stock-long routes): median planner-minus-stock −0.47 → −0.78 s; brakes more than 0.3 s late 8 → 4.

| Brake | Pre-119 vs stock | Shipped vs stock |
|---|---|---|
| 25b 1338.8 (lane change) | +0.85 s | −0.15 s (needs A+B) |
| 25e 318.1 | +1.00 s | −0.85 s |
| 25f 483.1 | +0.35 s | −0.15 s |
| 0263 374.3 | +0.55 s | +0.15 s |
| Still late: 0262 379.4 / 25f 55.8 / 25b 1353.2 / 25e 1002.0 | +1.05 / +0.85 / +0.55 / +0.50 s | +1.05 / +0.70 / +0.55 / +0.35 s |

**Tests.** Eight new unit tests: the pass after persistence (on and off), spike, not-closing and cruise-source cases held, and the merge-floor release. Results: test_longitudinal_planner 504, test_longcontrol 89, test_leads 6, test_starpilot_acceleration 26, tools/longitudinal/tests 9, all passing.

**Not verified.** Not driven. Needs a drive with a braking lead ahead and one with a lane change behind a braking car; watch for any brake on a far vision lead at a source switch. Replay variants `late_off` / `late_A` / `late_B` (`--late-ab`) reproduce this.

## 120. The 4 brakes still late after 119: cause traced; two planner fixes tried and rejected. Replay evidence only; no code change.

**Cause (open-loop replay, HEAD d2cd56e2, preceding segment included for warm-up).** It is not T_FOLLOW. When stock ACC crosses -1.5, the gap is already 2-17 m inside the desired distance in all four episodes, so the MPC knows it is too close.
- **0262 379.4 (+1.05 s) and 25e 1002.0 (+0.35 s): HumanFollowing.** The model's lead path has the lead speeding up by 2-3.5 m/s over its horizon, while radar aLeadK reads -1 to -2.
  - The 3 s TTC hand-back never trips at TTC 9-45 s.
  - With the raw aLeadK path, 262 is +0.15 s and 25e is level with stock.
  - On 25e the close-lead brake cap is also held at the -1.0 comfort floor (`get_close_lead_brake_cap(..., output_accel_min)`).
- **25f 55.8 (+0.70 s) and 25b 1353.2 (+0.55 s): radard aLeadK lag.** aLeadK reads -0.6 to -1.0 while the lead is actually braking at about -1.4 to -1.5. HumanFollowing adds only 0.1-0.15 s here. This is an input problem, not a planner term.
- All four lose about 0.1 s to 119's mildest-of-3-ticks filter, as designed.

**Fixes tried** (both behind switches, replayed on the same 22 routes, then reverted; patch kept off-repo):
- **F1a:** while aLeadK < -0.5, the model lead path may not speed up past radar vLead.
- **F1b:** under the same condition, hand back to the aLeadK extrapolation (the pre-63 guard).
- **F2:** the close-lead cap is built against the vehicle minimum and passes the comfort floor through 119's persistence filter.
- **F2L:** F2 with the pass limited to -2.0.

| | frames < -1.5 | frames < -2.5 | 0.5 s drops < -1.5 | new -1.5 crossings | deeper > 0.3 | later > 0.2 s | vs stock (23 brakes): median / late > 0.3 s |
|---|---|---|---|---|---|---|---|
| HEAD | 8853 | 2510 | 76 | - | - | - | -0.70 / 2 |
| F1a | 8978 | 2542 | 76 | 1 | 2 | 0 | -0.70 / 2 |
| F1b | 10050 | 3914 | 131 | 51 | 133 | 19 | -0.65 / 3 |
| F2 | 10443 | 3692 | 140 | 39 | 104 | 1 | -1.20 / 2 |
| F2L | 10443 | 3658 | 137 | 39 | 101 | 1 | -1.20 / 2 |

**Reading (replay).**
- **F1a** is nearly inert: 262 is only 0.05 s earlier.
- **F1b** brings back the STATUS 62/63 harshness.
  - On 262 it brakes 2 s before stock on a brief aLeadK dip, peaking at -2.51 where stock reached -1.61.
  - Across the routes it adds brakes stock never made, e.g. 0239 707.0 at -3.88 where stock reached -1.38.
- **F2/F2L** start every brake earlier, not just the late ones.
  - They still leave 25b 1353.2 and 25f 55.8 late (+0.50 / +0.45 s).
  - They add hard brakes where stock barely braked: 0266 147.8 at -3.42 vs stock -0.99; 0260 541.0 at -2.73 vs -0.3.
  - Unlimited, the cap's physical-gap geometry asked -3.5 on 262 312-315, where stock held -1.3 to -2.3.
  - The -2.0 limit does not hold because the cap also lowers `self.a_desired`, which seeds the next MPC solve, so the deeper plan returns through 119's MPC-demand pass.

**Decision: ship neither.** The remaining late starts come from radard's aLeadK lag (25f, 25b) and the model path's optimism (262, 25e). Every planner-side correction tested costs more hard braking than it saves.
- The stock-referenced set in this run is 23 brakes, of which HEAD is late on 2.
- 262 379.4 and 25e 1002.0 are not stock-labelled here, so they do not appear in that column.

**Next, if pursued:** aLeadK responsiveness in radard, weighed against the noise that 62/63 removed. Not started.

## 121. Faster radard aLeadK: five causal estimators studied offline; none clears the bar. Offline replay only; no code change.

**Question.** Can aLeadK recognise a braking lead sooner without adding false dips? This is the follow-up named in 120.

**Setup.**
- Bosch-A `RadarInterface` + `RadarD` replayed on the 22 routes, D-053 off.
- The re-run current KF (E0) matches `Track.aLeadK` to within 1.7e-7.
- Ground truth: aEgo + d²dRel/dt² from a centred 1.5 s range fit. **It is weak.**
  - The 1.0 s and 1.5 s fits differ by 1.2 m/s² (std).
  - The fit correlates only 0.4-0.55 with the native-vLead derivative.
  - 573 of 1024 lead segments are under 3 s because of identity breaks.
- The U11-derived reference lags range onset by 0.3-0.6 s, consistent with D-044.
- 275 confirmed braking events.

**Candidates.**
- **E0:** the current KF. K = (0.2272, 0.2815) is the DARE result for Q = diag(10, 100), R = 1e3.
- **E1:** Q ×2 and Q ×4.
- **E2:** matched vision visA assist (min, or blend), after N ticks of disagreement.
- **E3:** asymmetric: the Q×4 KF only toward braking, with a closing gate.
- **E4:** a KF fed the range-LSQ vRel, with and without a U11 corroboration gate.

| cand | onset lag to -1.0, median / p90 s | paired vs E0, median s | phantom episodes (worst) | false-dip ticks < -1 |
|---|---|---|---|---|
| E0 | 1.20 / 3.00 | 0 | 12 (-6.22) | 36 |
| E1 Q×2 | 1.05 / 1.67 | -0.10 | 13 (-7.18) | 15 |
| E1 Q×4 | 0.95 / 1.45 | -0.15 | 12 (-8.15), every recorded phantom 0.4-1.9 deeper, a new one at 0236 1392.6 (-4.69) | 2 |
| E2 N=2/3/5 | 1.15 / 3.00 | 0 | 15-17 | 37 |
| E3 | 1.15 / 1.85 | 0 | 12 (-7.30) | 36 |
| E4 with U11 corroboration | 1.05 / 1.73 | 0 | 23 | 42 |
| E4 without | 0.80 / 1.40 | -0.25 | 32 | 60 |

**The four late cases.**
- **25f 55.8:** truth crosses at 54.75, E0 at 56.01, the best candidate at 55.96. U11 lags range by about 0.6 s, and the lead really brakes at about -7.
- **25b 1353.2:** E1 and E4 are 0.15 s earlier.
- **262 379.4:** Q×4 is 0.2 s earlier.
- **25e 1002.0:** unchanged; the cause is the model path (120).

**Reading (offline).**
- The limit is U11's onset lag, not the KF gain.
- Every candidate that starts earlier deepens or multiplies the phantom dips. long_mpc and chill read aLeadK directly (D-048), so those dips become braking authority.
- E4 is the only candidate past 0.2 s. It re-opens the D-053 phantom class (12 → 32 episodes), and adding the U11 gate removes its gain.

**Decision.** No radard change. Scripts and data are kept off-repo.

## 122. FrogPilot e7debabe5 HumanFollowing gate (radar lead must be vision-matched) replayed on 22 routes: it never fires. Replay evidence only; no planner change.

**Question (owner, 2026-09-25).** FrogPilot e7debabe5 (2026-09-20) adds `radar_lead.modelProb > lead_detection_probability` to the HumanFollowing condition in `process_lead`. Our `build_model_lead_trajectory` checks only `model_lead.prob` and `radar_lead.status`. Does the extra gate change anything here?
- Their radard change (lane-change adjacent track returned with modelProb 0 unless it is the vision match) has no counterpart here: our `match_vision_to_track` only narrows candidates by side and still runs the full match. Their CEM `slow_lead` change is already covered: StarPilot's CEM reads `lead.modelProb`.
- The only path here that publishes a radar lead with modelProb 0 is the low-speed override (`closest_track.get_RadarState()`, `radard.py` ~758).

**Method.** `alpha_closed_loop_replay.py --hf-gate` adds variant `hf_gate`: the shipped builder, refused when the radar lead's modelProb is at or below the threshold. Harness `/tmp/lt/lab4.py` + `sum4.py` (STATUS 120's lab3/sum3 with this variant), HEAD 981df7d2, all 22 routes 20c-26b, fused radar.

**Result.**
- Gate refusals on engaged frames: **0 on every route.** 226 episodes, 0 changed; frames < -1.5 8783 and < -2.5 2510 in both; 0.5 s drops 76 in both; vs stock (23 brakes) median -0.70, late > 0.3 s: 2 in both (25b 1353.2, 25f 55.8).
- Not a wiring fault: on 23b the builder produced a model path on 5,634 ticks (5,361 radar, 273 vision) and the radar lead's modelProb there never fell below 0.362.
- Why: HumanFollowing needs `model_lead.prob` above the threshold, and on Bosch-A `candidate_is_established` only lets a low-speed-override track replace the lead when there is no valid lead or it matches vision. The matched-vision case would publish modelProb 0 and be gated (switching HumanFollowing off for a correct lead); it did not occur on these routes.

**Decision.** Nothing to adopt for Bosch-A: inert on this data. It could matter on non-Bosch-A cars, where `candidate_is_established` always passes; if ported, the low-speed override should carry `filtered_lead_prob` when the candidate matches vision. It does not touch the 262/25e late brakes (STATUS 120), which are on vision-confirmed leads.

## 123. Galaxy NRDR PID Tuning page redesigned and audited (item 117 follow-up). Static render check and unit tests only; not seen on device, not driven.

- **Rename.** The classic-UI tab `Lateral Tune` (`/lat_tune`) is now **NRDR PID Tuning**, so it is not confused with FLM (`Lateral Tuning`, `/tuning`). The URL is unchanged. User-facing text says "NRDR PID" instead of "StarPilot PID" on both the classic page and the mobile panel.
- **Redesign.** `lat_tune.js` / `lat_tune.css` now use FLM's `longManeuver*` / `flm*` classes, so both lateral tools share one look. The page has:
  - an intro and an evidence notice;
  - the actions and a status grid, plus a progress bar while analyzing;
  - the current P/I/F gains as three band tiles, with a warning when `LatGainSchedule` is set;
  - FLM's two columns: local routes (newest first, readable dates, length, Connect link, Latest 8 / Clear) and trials (P now → proposed pills, Applied / No change badges, Apply or Revert, Delete);
  - a full-width trial detail with one card per band (P now → new, factor, metrics, reason), an applied before/written table and the warnings.

  Apply is disabled on a trial that proposes no change. Checked in headless Chromium at 412 px and 1280 px against mocked `/api/lat_tune/*` and `/api/routes`, with no console errors. This was not the real Galaxy server.
- **Audit fixes.** Unit tests only: analyzer 49, workspace 17, CLI 6, test_ui_vue_frontend 31, frontend_module_graph 11. `test_lat_tune_api.py` was not run because `.venv` has no flask. Five of the six new tests fail on the pre-fix code; the Stop test also passes on it.
  1. **The fingerprint never matched once a BOOL tuning key was set.** initData holds raw bytes (`"0"`), while `Params.get()` returns `False`, so every apply returned 409 and force became the routine path. `tuning_fingerprint` now normalises bools and numbers to `repr(float)`. Trials made before this change carry the old hash: re-analyze them rather than forcing.
  2. **Removing a key was undone at the next boot.** When apply or revert removed a key (a stripped `LatGainSchedule`, or a band P that was unset before), `manager_init` restored it from the params cache. Removals are now mirrored into `Paths.params_cache_root()`.
  3. **Apply, revert and delete now run under a lock.** A double-click could snapshot the first apply's writes as the "prior" values, or drop a stack entry.
  4. **Stop only signals a live worker that is still running and leads its own process group.** Before, it could `killpg` a stale pid from an old status file.
  5. **Start refuses while a worker left over from before a Galaxy restart is still alive.**
  6. **The UI status shows a worker that died without reporting as `failed`.** Before, it stayed `running` for up to an hour.
  7. **Trial ids now carry the worker pid.**
  8. **Applied trials stay listed past the newest 20.**
- **The three open items are closed in 123a below.**

### 123a. The three open items from 123, closed (owner approved). Unit tests only; not driven.

1. **Apply is relative to the device.** `build_band_params(trial, device_gains)` writes `propose_p(device P, factor)` and only for bands whose factor moved. Held bands are not written. Apply snapshots only the keys it writes, and refuses a trial with nothing to change. For an unforced apply the fingerprint matches, so the device P equals the logged P and the result is unchanged. A forced apply now keeps a manual change made since the drive: logged 100 → 105, device 120 → 125.
2. **`strip_schedule_p` only strips a schedule the controller accepts** (`"p" in schedule_terms`). `LatControlPID` rejects a malformed schedule whole, so its i/f are not live and the bands already drive P. Stripping a bad `p` could make the rest valid and turn those i/f terms on, so a rejected schedule is left untouched.
3. **Unset band keys show their real defaults.** `BAND_DEFAULTS`: P 100/100/100, I 20/100/0, F 100/100/100. A test pins these against `common/params_keys.h` and the `latcontrol_pid.py` fallbacks.
- **Tests:** analyzer 50, workspace 20, API 3, CLI 6, test_ui_vue_frontend 31, frontend_module_graph 11.
  - `test_lat_tune_api.py` now runs. flask was installed into `.venv` with `uv pip install flask`; this is a local env only, and no dependency file changed.
  - Its stub needed `public_status`, and `written` as a dict.

### 123b. NRDR PID Tuning, offline run on the 4 newest routes (owner request; the comma was unreachable). Offline replay only; nothing applied, nothing driven.

- **Command:** `tools/lateral/lat_tune_cli.py --routes-root <routes dir> --latest 4` at `5e091b67`, over `00000267--e83a1fa671`, `00000268--4bc9811934`, `0000026b--92b1979afa` and `0000026c--10bec2e200`.
  - 113 rlog segments. 21 of them had no engaged pidState frames, mostly `…26b` 0–7 and 18–22.
  - The run needs `PYTHONPATH` to contain a directory that holds an `openpilot` → repo symlink, because `.venv` does not install the repo as `openpilot`.

  | band | min | sign/s | curve ratio | override episodes/min | factor | P/I/F now (from `…26c`) | P new |
  |---|---|---|---|---|---|---|---|
  | LowSpeed 0–25 | 12.3 | 0.37 | 0.913 | 3.88 (veto > 1.5) | 1.00 hold | 100 / 50 / 50 | 100 |
  | Standard 25–50 | 47.8 | 0.75 | 0.96 | 0.65 | 1.00 hold | 105 / 75 / 100 | 105 |
  | Highway 50+ | 4.8 | 0.86 | – (no curve data) | 0.00 | 1.00 hold | 105 / 0 / 100 | 105 |

- **No change proposed.** Standard's curve ratio went from 0.944 in the item 117 run to 0.96. That is inside the 0.95–1.03 dead band, so the +5 % that item 117 proposed is not asked for again.
- **Caveat: the 4 routes ran on 4 different tunings.** The initData fingerprints differ on every route. The differing keys:

  | key | `…267` | `…268` | `…26b` | `…26c` |
  |---|---|---|---|---|
  | `LatPScaleStandard` | 100 | 100 | 100 | 105 |
  | `LatIScaleStandard` | 25 | 75 | 75 | 75 |
  | `HondaLateralPidKpScale` | 0.65 | 0.65 | 1.0 | 1.0 |
  | `HondaLateralPidKiScale` | 1.0 | 1.0 | 1.0 | 3.07 |

  So the pooled metrics mix gains. The only route on the current tuning is `0000026c--10bec2e200`. Run alone (`--latest 1`), it gives:
  - Standard: 14.6 min, sign 0.81/s, curve 0.98, override episodes 0.64/min → hold at 105.
  - LowSpeed (2.6 min) and Highway (0.8 min): not ready.

  Both runs agree: keep P at 100 / 105 / 105.
- **Next:** collect ≥ 3 min per band on the current tuning (mostly highway and low speed), then re-run on routes from `…26c` onward only.

## 124. ICBM yields to the distance (gap) and LKAS buttons (owner request). Unit tests and log decode only; not driven.

- **Problem (owner):** changing the stock-ACC gap while ICBM is active is hard, because presses don't take.
- **Log decode of stock-ACC routes `…0000026f--896ba35291` and `…00000270--56a94f62cd` (segs 0-11), limited road evidence:**
  - 9 driver gap presses (`gapAdjustCruise`), 3 registered (ACC_HUD `HUD_DISTANCE` stepped).
  - With no ICBM frame within 0.5 s: 2/2 registered. With ICBM frames overlapping the press: 1/7, and that one was the longest press (0.36 s).
  - 270 2:36-2:45: six presses in 8 s for one gap step, while ICBM hunted the set speed behind a lead pulling away.
- **Mechanism (static):**
  - With `ICBMCounterSync` (D-065) each ICBM `SCM_BUTTONS` frame takes the car's next counter and always writes `CRUISE_SETTING=0` (`hondacan.py` `spam_buttons_command`), so the ECU drops the car's own frame carrying the press.
  - D-065's yield covered only the speed/cancel/main buttons: `CRUISE_BUTTON_TIMERS` had no `gapAdjustCruise` or `lkas`.
  - The panda is not involved (0x296 TX on bus 1, nothing forwarded or blocked).
- **Change** (`selfdrive/car/redneck_cruise.py`, `selfdrive/car/card.py`):
  - `gapAdjustCruise` and `lkas` join `CRUISE_BUTTON_TIMERS`, so ICBM sends nothing while one is held (10 s missed-release cap as before) and for `SETTING_BUTTON_INACTIVE_TIMER = 1.0 s` after release. Speed buttons keep 0.5 s.
  - 1.0 s rather than 0.5 s because repeat gap presses came 0.69-0.71 s after the previous release; a 0.5 s window lets a burst land in between.
  - `driver_button` in `card.py` now uses `is_speed_button_press`, so a gap or LKAS press no longer cancels ICBM launch or clears the gas-release floor.
  - Detection uses the car's own frames (src 1); the ICBM echo is src 129. All 9 presses appeared as buttonEvents while spoofing.
  - A frame already sent just before the press edge cannot be recalled (270 163.03), so the first frame of a press can still be lost.
- **Tests:** `test_redneck_cruise.py` 69 pass (3 new: distance/LKAS held, 1.0 s release window, `is_speed_button_press`); `test_redneck_gas_override.py` 2 pass. ruff: only the file's pre-existing unittest/E731 errors.
- **Road check to do:** with ICBM hunting, press distance 3-4 times. Each press should step `HUD_DISTANCE` once, and no src-129 `SCM_BUTTONS` frame should appear from the press until 1.0 s after release.
- **Open ICBM items found alongside, not changed:**
  - set-speed hunting: `HYST_GAP = 0`, and presses outrun the 0.2-0.3 s cluster lag; 69/91 direction reversals within 1.5 s on 26f/270; scratch `/tmp/icbm/`;
  - about 8 % of the car's SCM frames modelled as dropped by counter sync;
  - no pause on the ACC_CONTROL byte-6 stall flag (item 94);
  - the item 96 `vCruise` resync.

## 125. Stopped/slow radar lead hold below 5 m/s (26c 4:26 surge). Unit tests and replay only; not driven.

- **Problem:** route `…0000026c--10bec2e200` 4:26 (replay 270.2-271.5): at 2.4 m/s behind a stopped radar+vision lead 22 m ahead, the command went -1.00 -> +1.24.
- **Mechanism (replay):**
  - `lead_control_active` = `tracking_lead` OR `raw_close_lead_needs_control`.
  - Approaching a stopped car, the model plans to stop short of it, so `tracking_lead` drops (dRel > plan length + 6 m).
  - The braking the lead caused pushes TTC past 7 s and lets aLeadK settle, so the raw gate drops too.
  - The MPC then loses the lead (source `cruise`) and plans acceleration toward it.
- **Change** (`selfdrive/controls/lib/longitudinal_planner.py`, `STOPPED_RADAR_LEAD_HOLD_*`, `update_stopped_radar_lead_hold`):
  - Arming: a lead that is already controlling arms the hold on its radar track id.
  - The hold then keeps lead control while all of these stay true: same track, `modelProb >= 0.5` (D-048), `|yRel| <= 1.75`, `vLead <= 3.5`, not pulling away (`vEgo - vLead >= -0.5`), and `vEgo < 5 m/s`.
  - It never admits a lead that was not controlling, and it does not re-arm without the normal gates.
- **Replay, 26 routes (`tools/longitudinal/alpha_closed_loop_replay.py`, harness `/tmp/g1`):**
  - Episodes: 0 softer by > 0.3 or later by > 0.2 s, and 0 new <= -1.5 crossings or clusters.
  - Surges toward a slow radar lead: 17 -> 12. 4:26 peak output: +1.24 -> about -0.1.
  - Pumps: 266 -> 262.
  - 5 mild deeper-than-base clusters (-0.51 to -0.86), all at 1.9-4.5 m/s. The logged command was as deep or deeper in every one.
- **Rejected variant, no speed limit:** fixed the 12:28 pumping (8 m/s), but added 6 new <= -1.5 clusters at 8.6-11.5 m/s approaching stopped queues 47-72 m ahead (00000232 1232.9, 00000236 416.2, 00000239 206.5, 0000026c 758.8). 12:28 is therefore not fixed.
- **Tests:** planner 512 (8 new), longcontrol 89, leads 6, tools/longitudinal/tests 9.
- **Road check to do:** creep up to a stopped car at < 5 m/s with alpha long. There should be no surge after the initial brake.

## 126. ICBM: gas-release floor limits, corroborated far-lead decel 0.8, set-speed hunting (hold rounding, last-step pacing, increase lockout). Unit tests and replay only; not driven.

- **Problem (route `…00000271--4e9b9502db`, segs 7+, 5 far-lead bookmarks; /tmp/i271/report.md), limited road evidence:**
  - The gas-release floor had no expiry and no lead exit. It held BM4 29:52 at 33.6 mph from a release 94.6 s earlier while the plan wanted 18-25 mph, and it held BM2 22:01 at 50 mph so no press went out.
  - `FAR_LEAD_DECEL_MS2 = 1.5` assumed a decel the set-speed channel does not deliver. With set-speed-only decel on 271, stock ACCEL_COMMAND median/p10 was -0.39/-0.59 at 3-5 mph over the set, -0.59/-0.73 at 5-8, and -0.83/-0.89 at 8-12. aEgo median was -0.18..-0.27.
  - Hunting: 214 direction reversals within 1.5 s; the longest ran 45 s at seg28+36.7.
- **Hunting causes (logged reversals, classified against replayed targets; 271 / 26f / 270):**

  | Cause | 271 | 26f | 270 |
  |---|---|---|---|
  | Press-to-cluster lag overshoot | 82 | 25 | 33 |
  | Lead target moved | 49 | 33 | 27 |
  | CSC controlling toggles | 44 | 4 | 13 |
  | Hold-rounding mismatch | 21 | 11 | 3 |
  | hasLead flips | 13 | 2 | 23 |

  - Measured lag from first press frame to first cluster change: median 0.235 s, p90 0.39-0.42 s.
  - Hold rounding: 49 mph shows as 78 km/h = 48.47 mph. The hold branch returned that value, it rounded to 48 against the corrected 49, and ICBM pressed DECEL (the 45 s seg28 episode is this plus CSC).
- **Change** (`selfdrive/car/redneck_cruise.py`, `selfdrive/car/card.py`):
  - **Floor.** `GAS_RELEASE_FLOOR_MAX_S = 15.0` after each release. The floor is also dropped (until the next release) when a lead that is closing and more than `GAS_RELEASE_FLOOR_LEAD_HEADWAY_S = 4.0` s ahead wants the set below the floor (`gas_release_floor_expired`).
    - A nearer lead does not clear it. Stock ACC follows that lead itself (item 84), and a closing-only rule cleared the floor's own case, 262 1:29 (radar lead 43.6 m, 2.6 s, closing 2.2 m/s), one frame after the release.
  - **Far lead.** `FAR_LEAD_DECEL_MS2 = 0.8` only for a corroborated lead (radar, or modelProb >= 0.7, `is_far_lead_corroborated`). Uncorroborated leads keep 1.5 (`FAR_LEAD_UNCORROBORATED_DECEL_MS2`), because vision vRel at 85-105 m was wrong in BM3/BM4.
  - **Hold.** When the target equals `cruiseState.speedCluster`, `v_target` is the corrected cluster, so a hold sends nothing.
  - **Pacing (counter sync only).** Within 1 mph of the target, one `PRESS_PULSE_S = 0.1` s pulse then a `PRESS_SETTLE_S = 0.45` s wait for the cluster. Larger gaps press as before.
    - `INCREASE_AFTER_DECREASE_LOCKOUT_S = 1.0`: no INCREASE within 1 s of a DECREASE. It never delays a decrease.
- **Replay** (`/tmp/icbm2/sim.py`: logged inputs, simulated counter-synced presses with a 0.15 s ECU delay calibrated to the measured lag, 10 Hz truncated-km/h cluster; open loop in vEgo; it overstates hunting vs the log, e.g. 271 base 352 vs logged 214, so compare base vs fix only):

  | Route | Reversals < 1.5 s, base -> fix | Longest episode | Phantom lead drops mph | Open-road s > 2 mph below cruise target |
  |---|---|---|---|---|
  | 271 (seg 7+) | 352 -> 110 | 46 -> 21 | 252 -> 247 | 485.2 -> 479.6 |
  | 26f | 174 -> 34 | 52 -> 5 | 63 -> 51 | 164.3 -> 160.9 |
  | 270 | 100 -> 31 | 18 -> 6 | 71 -> 58 | 124.3 -> 125.3 |
  | 266 | 309 -> 83 | 37 -> 7 | 201 -> 198 | 227.0 -> 240.9 |
  | 267 | 267 -> 49 | 37 -> 7 | 83 -> 70 | 134.0 -> 133.8 |
  | 262 | 72 -> 20 | | 63 -> 47 | 148.0 -> 148.7 |
  | 263 | 299 -> 83 | | 191 -> 165 | 337.4 -> 335.4 |

  - Most of the reversal cut comes from pacing; the lockout adds the rest (271 150 -> 120 in the pre-headway run).
  - 271 bookmarks, set at -2 s (base -> fix): BM0 34.8 -> 31.7; BM2 49.7 (floor 50, no press) -> 41.6 (press from -4.66 s); BM4 33.6 (floor 34) -> 24.9. BM1, BM3 and 32:01 are unchanged at -2 s.
  - 262 1:29 replays identically to base (floor held, set walks 24.9 -> 37.9).
- **Beep (271 segs 7+), log decode only:**
  - ACC_HUD CHIME is always 0. The 0x1FA byte-5 "CHIME" value 64 pulses 13 times, and all 13 coincide within 0.1 s with a stock ACC HUD_LEAD 1<->2 transition. 5 of those have no ICBM frame within 3 s.
  - Reading [INFERRED]: the audible beep follows stock ACC target acquire/loss, not ICBM presses. No cheap ICBM-only beep class was found.
- **Tests:**
  - `test_redneck_cruise.py`: 81 pass (12 new).
  - gas_override 2, cruise_speed 42, honda `test_icbm_counter_sync` 5, starpilot_vcruise 94, speed_limit_controller 52 and `test_longitudinal_planner.py` 512 pass.
  - Each new test group fails with its fix reverted.
- **Road check to do:**
  - Re-drive 271-style far-lead approaches: the set should drop from a radar-corroborated lead at 80-100 m.
  - After a gas release on an open road, the set should hold the release speed for up to 15 s, and it must not fall behind a nearby lead.
  - Cruise at a steady target: expect no 1-mph DECEL/ACCEL alternation on the cluster.
- **Open:**
  - CSC controlling-flag toggles still move the target (44 reversals on 271).
  - 1-mph approaches are up to ~0.55 s slower, and an increase waits 1 s after a decrease.
  - No pause on the ACC_CONTROL byte-6 stall flag (item 94).

## 127. ICBM counter sync is baked in on Honda (owner request); the `ICBMCounterSync` toggle is gone. Static only.

- **Why:** D-065 has shipped counter sync on by default since STATUS 96. Every ICBM drive since then ran with it on, 00000271 included. With sync the set speed steps about 6-7 times/s; without it, about 2 times/s (limited road evidence, bench routes 264/265). The owner asked for no more toggles where a feature is good enough.
- **Change:**
  - `starpilot/common/starpilot_variables.py`: `icbm_counter_sync` is now `car_make == "honda" and redneck_cruise`. The param is no longer read.
  - `starpilot/common/assets/device_settings_layout.json`: the Galaxy toggle entry is removed.
  - The `ICBMCounterSync` key stays in `params_keys.h` and `feasibleparams.txt`, so the aarch64 `libcommon.a`/`params_pyx.so` need no rebuild. It is unused.
- **Effect:** a car that had the toggle turned off now syncs too. The STATUS 126 last-step pacing (counter-sync only) now always applies on Honda ICBM.
- **Open items carried from 124:** about 8 % of the car's own SCM frames are modelled as dropped by sync. The gap/LKAS yield from 124 covers the presses that matter.
- **Tests:** `test_redneck_cruise.py` 81 pass, honda `test_icbm_counter_sync.py` 5 pass, the_galaxy `test_device_settings_layout.py` 29 pass and `test_device_settings_frontend.py` 9 pass. `test_personality_profiles_js.py` has 14 failures that are also there at HEAD without this change.

## 128. Radar lead-loss census, pre-fix vs post-fix drives (`tools/bosch_a_lead_loss.py`). Log decode on 10 routes; limited road evidence for D-052..D-062; no parser change.

**The tool:** it reads what the device published. A loss is `leadOne` stopping being a radar lead for ≥ 1 s, while the car is engaged (`carControl.enabled`), after a radar lead held ≥ 0.5 s, and while vision still sees a lead (prob > 0.5, < 80 m). It ends when radar returns, vision goes away, or the car disengages. A loss counts as **parser** when the lost track id is missing from `liveTracks` on at least half its frames. Otherwise `radard` chose not to use a published track. This is not the D-054 replay metric (two parsers on the same CAN), so do not put the two in one table. Tests: `tools/lib/tests/test_bosch_a_lead_loss.py`, 8 pass, with negative controls: a held lead, no vision lead, and disengaged.

**Builds, from `initData`:** 232 `9984de885`, and 236/237/239/23a `fa262e0c7`. Both are before D-054 (`0756f810`). 26b `d0b525140`, 26c `cbab2214e`, 26f/270 `4b80584da` and 271 `95eb27abe` all contain D-054/055/057/059/062. 26f, 270 and 271 are stock-long (lateral only; the parser runs the same).

| | engaged | losses ≥ 1 s | loss time | parser losses | longest parser loss |
|---|---|---|---|---|---|
| pre-fix: 232, 236, 237, 239, 23a | 88 min | 38 (26/h) | 65 s (44 s/h) | 15 (10/h), 35 s | 5.8 s (236 seg 29) |
| post-fix: 26b, 26c, 26f, 270, 271 | 75 min | 19 (15/h) | 32 s (26 s/h) | 5 (4/h), 9 s | 3.3 s (26b seg 39) |

- Most of the per-hour gain is 236 (20 losses, 10 of them parser losses). 26c has 0 parser losses. Its loss time (31 s/h) is still about the same as pre-fix 232 and 237 (about 28 s/h).
- **271 seg 25, id 26, 2.0 s** (the longest parser loss today) was traced through the real parser. Just before it stopped being published, the track moved from y −3.4 to −7.5 m and opened at +3.6 m/s. That looks like a car leaving the path, not a lockout. Why the parser stopped publishing it was not checked against the raw slots.
- `bosch_a_lifecycle_report.py` on 26c/26f/270/271 (current parser): 5 single-sweep breaks in total, 0 on the device lead, 0 within 2 s of a hard brake, and 0 chronic.
- **Limits:** different traffic on each side, and about 1.25 engaged hours per side. No loss fell inside a hard brake, so this says nothing about braking authority.

## 128. ICBM far-lead slowdown is baked in on Honda (owner request); the `ICBMFarLead` toggle is gone. Static only.

- **Why:** `ICBMFarLead` already defaulted on (`params_keys.h` "1"), and the owner's ICBM drives ran with it on, 00000271 included. The owner asked for no more toggles where a feature is good enough.
- **Change:**
  - `starpilot/common/starpilot_variables.py`: `icbm_far_lead` is now `car_make == "honda" and redneck_cruise`. The param is no longer read.
  - `starpilot/common/assets/device_settings_layout.json`: the Galaxy toggle entry is removed.
  - Comments are updated in `selfdrive/car/card.py` and `selfdrive/car/redneck_cruise.py`.
  - The key stays in `params_keys.h`, so there is no binary rebuild. It is unused.
- **Effect:** a car that had the toggle turned off now gets the far-lead set-speed target too, including the STATUS 126 corroborated 0.8 m/s^2 decel. That STATUS 126 behaviour is replay only and not yet driven.
- **Tests:** `test_redneck_cruise.py` 81 pass, the_galaxy `test_device_settings_layout.py` 29 pass and `test_device_settings_frontend.py` 9 pass.
- **Numbering:** the radar agent's pending drafts shift to 129/130.

## 131. `HondaLateralPidKpScale` / `HondaLateralPidKiScale` never reached the controller; NRDR PID tuner now pools only routes on the newest route's tuning. Unit tests, open-loop replay and sim only; not driven.

**The bug (item 113's open question, answered).** `StarPilotVariables.update()` rewrites every non-torque car's
`CP.lateralTuning` to torque (`configure_torque_tune`) before the toggles are read. `honda_pid_lateral` then checked
`CP.lateralTuning.which() == "pid"`, which was therefore always False, so `get_value` returned the 1.0 default for
both scales on every drive. The Galaxy sliders did nothing.
- **Replay proof on `0000026c--10bec2e200`** (`lat_pid_sim.py replay`, logged freeze): with the logged Ki 3.07 the torque
  error median is 4.6e-2 (logged |out| median 0.036); with `--set HondaLateralPidKiScale=1.0` it is 1.6e-3. The car ran
  Ki 1.0, just as 268 ran Kp 1.0 with 0.65 set.
- **Fix:** `is_pid_car` is read before the rewrite and used for `honda_pid_lateral`. Regression test
  `test_honda_pid_gain_scales_reach_the_toggles` fails on the old code (1.0 != 0.65) and passes on the new;
  `test_starpilot_variables.py` 36 pass. `lat_pid_sim` already applied the logged scales directly, so it was right and
  the car was not.
- **Effect on the next build — read before driving it.** Routes 26c, 26f, 270 and 271 all logged
  `HondaLateralPidKiScale = 3.07` (Kp 1.0). With the fix that value takes effect: I becomes 3.07x in the LowSpeed and
  Standard bands (Highway I is 0, so no change there). **Ki 3.07 has never been driven.** Sim sweep (plant refit on
  260–263, `/tmp` only, same recipe as item 113), 25–50 mph band:

  | Ki scale | 271 curve ratio / straight rms / sign | 26c curve ratio / straight rms / sign |
  |---|---|---|
  | 1.0 (what was driven) | 0.963 / 0.71° / 0.6 /s | 0.950 / 0.80° / 0.6 /s |
  | 2.0 | 0.989 / 0.67° / 0.7 /s | 0.971 / 0.77° / 0.6 /s |
  | 3.07 | 0.998 / 0.62° / 0.7 /s | 0.985 / 0.72° / 0.7 /s |

  Below 25 mph the curve ratio goes 0.864 → 0.928 (271) and 0.927 → 0.973 (26c). The sim under-predicts oscillation, does
  not model driver-override trips, and holds the integrator exactly as the car does only approximately (item 113). More I
  also means more wound-up I frozen through an override, the 26b 32:40 exit mechanism (item 114). Recommendation: set Ki
  back to 1.0 (or 2.0) before the first drive on this build and step up from there, rather than jumping to 3.07.
- Older trials' fingerprints include Kp/Ki values that were not in effect; they over-split routes that actually ran
  identically, which is conservative.

**Tuner: routes on other tuning are left out (STATUS 123b follow-up).** `analyze_sources` now keeps one `DriveStats` per
route, takes the newest route's logged tuning as the baseline, and pools only routes with the same
`tuning_fingerprint`. Every other route is listed in the warnings with the keys that differ (or "no logged tuning") and in
`perRoute` with `used: false`; its minutes are still reported. `mixed_tuning=True` / CLI `--mixed-tuning` restores the
old pooling with the old warning. Galaxy calls the default (filtered). The CLI prints a used/left-out line per route.
- Tests: analyzer 53 (3 new, 1 moved to `mixed_tuning=True`), CLI 7 (1 new), workspace 20, API 3 pass.
- **Offline run, 4 newest routes** (`0000026c--10bec2e200`, `0000026f--896ba35291`, `00000270--56a94f62cd`,
  `00000271--4e9b9502db`, 89 segments): all four on fingerprint `e5615f03`, all pooled.

  | band | min | sign/s | curve ratio | override episodes/min | P/I/F now | P new |
  |---|---|---|---|---|---|---|
  | LowSpeed | 8.2 | 0.38 | 0.91 | 3.40 (veto) | 100 / 50 / 50 | 100 |
  | Standard | 38.8 | 0.81 | 0.97 | 0.80 | 105 / 75 / 100 | 105 |
  | Highway | 3.8 | 0.85 | – (no curve data) | 0.99 | 105 / 0 / 100 | 105 |

  No change proposed. These metrics describe Ki 1.0 (what ran), so once the fix ships, the first routes on the new
  build carry a new effective I and should be analysed on their own.

## 132. Lateral accuracy pass: tuner sign-change deadband, curve entry/steady/exit split, sim plant delay + angle quantisation; override-reaction and stutter studies (owner request, items 2/3/4/6 + stutter). Unit tests, replay and sim only; not driven.

Routes: `00000262`, `263`, `268`, `26b`, `26c`, `26f`, `270`, `271` (per-frame arrays in `/tmp` only).

**Item 4: tuner sign changes now need a 0.15° swing (`SIGN_HYST_DEG`).** A straight-frame error sign change counts only once the error has gone from ≥ +0.15° to ≤ −0.15° (or back); inside the band the last sign is kept.
- Replay, 25–50 mph: 0.76–0.92 /s with no deadband → 0.24–0.30 /s at 0.15° on all 8 routes; highway 0.64–1.58 → 0.10–0.29. The old count was mostly the angle sensor's 0.1° steps, not weave.
- Limits restated in deadband units: `SIGN_RATE_MAX` 1.0 → **0.6** (2× the worst 25–50 mph route), `SIGN_RATE_UP_MAX` 0.8 → **0.45** (1.5×). A revert after an up-step now also needs +0.05 /s absolute (`SIGN_SLACK`), because 3 min at 0.3 /s is only ~50 changes. Set on these 8 routes only, not on closed-loop outcomes.
- 4-route trial (26c/26f/270/271, same pool as 131): same decisions (hold 100/105/105). Sign changes Low 0.30, Standard 0.28, Highway 0.19 /s.

**Item 3: curve ratio split into entry / steady / exit** (`curveRatioEntry/Steady/Exit` in the trial, CLI columns, both Galaxy tuner views). Curve frames are split by how fast |desired| moves over 0.1 s (±5 °/s). Reported only; the rules still use the whole-curve ratio.
- Replay, every route: **the angle trails the desired by 0.15–0.25 s** (best-shift curve error 25–50 mph 1.27 → 0.81° on 26b). Entry reads 0.72–0.86, exit 1.00–1.21.
- 25–50 mph steady ≈ whole curve (26c–271 pool: entry 0.84 / steady 0.973 / exit 1.10). Below 25 mph the steady ratio is the *low* one (0.68–0.90; pool 0.83): real under-steer mid-corner, still vetoed by the override rate (3.4 /min).
- So the largest remaining tracking error at 25–50 mph is lag, not gain. More P only partly fixes lag. Not tried yet: a desired-rate feedforward, or less target smoothing (`HondaLpfTau*` delays the request before it reaches the logged desired, so its cost is not in these numbers).

**Item 6: `lat_pid_sim` plant has a command delay and 0.1° angle quantisation.**
- `Plant(coef, delay, quant)`; old plant JSONs load undelayed/unquantised. `fit` grids `FIT_DELAYS` or takes `--delay`. `validate`/`sweep` print the deadband sign-change rate and the tracking lag. `lat_autotune` loads plants the same way.
- Fit on 260–263: the free-run residual picks delay 0 (1.43° vs 1.54° at 6 frames; weakly identified).
- Closed loop at logged settings (Kp/Ki 1.0), 25–50 mph, logged vs sim:

  | route | logged raw / deadband | sim raw / deadband, delay 0 no quant (old) | delay 0 + quant | delay 5 + quant |
  |---|---|---|---|---|
  | 263 | 0.8 / 0.29 | 0.6 / 0.28 | 1.1 / 0.28 | 0.8 / 0.28 |
  | 268 | 0.8 / 0.25 | 0.5 / 0.23 | 0.9 / 0.23 | 0.6 / 0.25 |
  | 271 | 0.8 / 0.30 | 0.6 / 0.30 | 1.1 / 0.31 | 0.8 / 0.31 |

  **The old "sim under-predicts oscillation" gap (item 113) was the sensor quantisation, not missing dynamics.** On the deadband metric the undelayed plant already matched within 0.02 /s. So item 113/131 Kp/Ki sweeps stand on that metric. Delay 5 matches both counts best; err rms and lag change little (sim lag 0.26–0.33 s vs logged 0.14–0.31 s).

**Item 2: reaction-compensated override detection. Replay does not support it; no param added, threshold stays 2000.**
- Hands-off frames: driver torque ≈ −1000…−1500 × delivered command, R² 0.11–0.21 (26b/26c/268/26f/270/271). Subtracting it changes override onsets by −7 % to +5 %; only 2–17 onsets per route were reaction-only.

**Stutter: the override cut-and-fade, triggered by threshold grazes.**
- 62–71 % of `steeringPressed` episodes last ≤ 0.1 s, and 23–42 % last ≤ 0.03 s. Isolated short presses peak at median |torque| 2058–2140, just over the threshold. 33–48 % are within ±3° (the 1200 centre threshold).
- Each one cuts the torque to 0 in one frame (`HondaOverrideTorqueScale` 0, fade-down 0), then fades it back over 1 s with the integrator frozen (steer_limited). That is 2.9–7.2 % of engaged time in fade, plus 1.3–3.4 % pressed.
- Open-loop replay of the ramp only (no plant response):
  - `HondaOverrideFadeDownSecs` 0.2 s cuts the torque withheld after short presses by 20–40 %, and keeps ≤ 0.01 u·s on real (> 0.3 s) presses.
  - A fast fade-up (0.25 s) after presses ≤ 0.1 s cuts it 35–46 % and halves the time in fade.
- **Proposed, not implemented:** a fast recovery after an isolated graze (no other press within 1.5 s, so a real fight keeps the 1 s fade), as a default-off carcontroller param. `HondaOverrideFadeDownSecs` 0.2 is an existing setting the owner can try. Both change override feel and need a drive to judge.

Tests: analyzer 62 (was 53; 9 new cases, 3 adjusted to deadband units), `test_lat_pid_sim.py` 5 new, CLI 7, workspace, UI frontend and py39-compat pass. Galaxy test files collected together with `-k` hit pre-existing module-stub import errors (`accel_profile`, `testing_grounds`); each file passes alone.

## 133. Tracking lag: `NrdrLatRateFF` desired-rate feedforward (new, default off), target smoothing scored against the unshaped target. Unit tests and sim only; not driven.

Owner request: cut the 0.15–0.25 s lag found in 132. Sim: `lat_pid_sim` closed loop on `263`/`268`/`271`, plant fitted on 260–263 at delay 5 + 0.1° quantisation (the best closed-loop match in 132), Kp/Ki 1.0 as logged. Cross-checked on the undelayed plant. **The sim runs more lag than the logs (0.23–0.38 s vs 0.15–0.25 s), so read the numbers as relative.**

**Sim change: score against the target before shaping.** The logged desired angle is after the 300 °/s slew clip and the `HondaLpfTau*` smoothing, so every earlier lag number hid the smoothing's own delay. `LatControlPID.raw_angle_steers_des` now keeps the unshaped target (offline use only), `simulate(..., with_raw=True)` returns it, and `sweep`/`sim` print error rms, lag and curve-entry ratio (|target| growing > 5 °/s, as in the tuner) against it. Against the unshaped target the lag is 0.31–0.48 s at 25–50 mph.

**New param `NrdrLatRateFF` (float, 0–2, default 0 = off).**
- Adds `k × (shaped target slew) / 100 °/s` to the NRDR PID output, before the center-taper/phase scales. The rack damps rate, so P only moves the wheel once an error has built up; this pays for the slew as it is asked for.
- Plumbing: `params_keys.h`, device settings (NRDR tuning), Galaxy layout, and both tuner `TUNING_KEYS`. The tuner fingerprint leaves it out while unset or 0, so earlier routes still pool and the learned state does not reset on update (`FINGERPRINT_ADDED_OFF`).
- Sim, 25–50 mph (263 / 268 / 271):

  | k | err rms ° | lag s (vs logged-style target) | entry ratio vs unshaped | straight rms ° | sign changes /s at 0.15° |
  |---|---|---|---|---|---|
  | 0 | 0.96 / 1.17 / 1.13 | 0.30 / 0.30 / 0.29 | 0.62 / – / 0.72 | 0.56 / 0.90 / 0.72 | 0.28 / 0.25 / 0.31 |
  | 0.25 | 0.91 / 1.11 / 1.07 | 0.25 / 0.28 / 0.25 | 0.64 / – / 0.74 | 0.51 / 0.85 / 0.68 | 0.28 / 0.25 / 0.31 |
  | **0.5** | 0.87 / 1.06 / 1.01 | 0.21 / 0.26 / 0.22 | 0.67 / – / 0.76 | 0.47 / 0.80 / 0.65 | 0.28 / 0.24 / 0.29 |
  | 0.75 | 0.85 / 1.03 / 0.97 | 0.18 / 0.24 / 0.18 | 0.69 / – / 0.78 | 0.43 / 0.76 / 0.63 | 0.29 / 0.24 / 0.29 |
  | 1.0 | 0.84 / 1.02 / 0.94 | 0.14 / 0.22 / 0.14 | 0.73 / – / 0.80 | 0.40 / 0.74 / 0.62 | 0.29 / 0.24 / 0.29 |
  | 1.5 | 0.86 / 1.04 / 0.92 | 0.09 / 0.23 / 0.07 | 0.78 / – / 0.84 | 0.38 / 0.71 / 0.60 | 0.26 / 0.24 / 0.28 |

- Below 25 mph: err rms 9.96 / 18.6 / 11.4 → 9.06 / 17.7 / 9.48 at 0.5, curve ratio 0.86–0.91 → 0.89–0.93. Weave rises from about 0.75: sign changes 0.38 / 0.32 / 0.35 → 0.36 / 0.44 / 0.35 at 0.5, 0.43 / 0.42 / 0.44 at 0.75, and 0.30 / 0.64 / 0.51 at 1.5, where 271 err rms gets worse than off (11.8).
- Undelayed plant, same routes: the same picture (25–50 mph err rms 0.93 / 1.15 / 1.11 → 0.85 / 1.05 / 1.00 at 0.5; low-speed sign changes 0.33 / 0.28 / 0.31 at 0.5).
- **Default stays 0.** Sim-only and plant-dependent, and it adds torque on every target slew. **Recommendation to try on the road: 0.5.** In the sim it takes 0.04–0.09 s off the lag and 9–11 % off the 25–50 mph error, with no rise in weave there. Watch the tuner's low-speed sign-change rate and the override rate.

**Target smoothing (`HondaLpfTau*`): no change.**
- 25–50 mph, `HondaLpfTauStandard` 0.1 → 0.05 → 0 against the unshaped target: err rms 1.24 / 1.30 / 1.36 → 1.13 / 1.19 / 1.12 at 0. Lag against the unshaped target 0.43 / 0.48 / 0.38 → 0.34 / 0.31 / 0.28.
- But sign changes 0.28 / 0.25 / 0.31 → 0.32 / 0.29 / 0.39, and error against the shaped target is flat or worse.
- With `NrdrLatRateFF` 0.5, tau 0 still adds weave (271: 0.29 → 0.37).
- `HondaLpfTauLowSpeed` 0 is worse outright below 25 mph (err rms up 1–6 %, sign changes up to 0.47).
- The smoothing is paying for itself in weave; the rate feedforward is the cheaper lag fix.

Tests: `test_latcontrol_pid_rate_ff.py` (3 new: default off and param read, torque follows target slew, raw target is pre-shaping); analyzer 63 (1 new: fingerprint unchanged by an unset or zero added key); `tools/lateral/tests` and py39 compat pass. `test_latcontrol.py` has 4 failures that predate this change: bolt/palisade taper, planner jerk scale, torqued roll bias (same with the HEAD controller).

## 129. `BoschARailInterval` finished: degraded sweeps need range corroboration, and the coast's less-closing side only acts inside a rail-admission hold. Still default off. Unit tests and replay only; not driven.

- **Problem (item 92 open item):** the rail interval admitted range walks on degraded sweeps. Route `…0000025e--919b58ab81` 6:43 (403 s), track 48: a 47.9 -> 35.3 m walk was admitted against a 0.53 s old baseline, and -13.5 was coasted at 35 m (planner -3.23; vision and toggle-off -0.5).
- **Rejected variants (replay):**
  - Exact gate on every degraded sweep (item 92's suggestion): kills the D-063 case itself. 25e 12:03 track 59 is degraded on every sweep, admitted at 724.233 against a 2.16 s old baseline, and went dark again until 32 m.
  - Baseline-age floor 0.31 s: kept 12:03 and still admitted the 6:43 walk.
  - Corroboration fit over the last 8 sweeps: averaged the finished walk in (about -20 m/s) and still admitted 6:43.
- **Change** (`opendbc_repo/opendbc/car/honda/radar_interface.py`):
  - `BOSCH_A_RAIL_INTERVAL_EXACT_WHEN_DEGRADED`, `_bosch_a_trailing_fit_window`: on a degraded sweep the interval applies only if the shortest D-043 tail of the rejected run plus this sweep (4 samples over >= 0.25 s) fits within 3 m/s of the rail interval. At 6:43 the fit is about -2 m/s, so the sweep is not admitted. At 12:03 it is -16..-18 m/s, so the sweep is admitted. No new number.
  - `BOSCH_A_RAIL_INTERVAL_DOWN_SIDE_ONLY_ON_RAIL_HOLD`, `_BoschATrackState.rail_hold`: item 92's two-sided coast clamp now makes a coast less closing only inside a hold that a rail admission started. Every other coast keeps the one-sided item 111 bound. Applied to every coast, it had softened three protected brakes: 232 1147.2 (-2.25 -> -1.88), 266 560.0 (-1.79 -> -1.38) and 266 795.4 (-1.5 crossing 3.75 s later).
  - With the toggle off both gates run `exact`. Byte-identical: 0 differing sweeps and 0 differing lead frames on all 26 routes.
- **Replay, 26 routes, toggle on vs off** (harness `/tmp/ri3/ab.py`, `RangeDerivedVrel` and the D-053 assist on in both chains):
  - Routes: alpha-long 20c 232 236 237 239 23a 23b 23e 241 245 268 26b 26c; stock ACC 25b 25d 25e 25f 260 261 262 263 266 267; ICBM/stock 26f 270 271 (271 from seg 7). 266 and 267 are stock ACC, not alpha. 246, 24d, 251 and 258 from item 91 are no longer on disk.
  - Points lost 0 and lead points lost 0 on every route. New measured points on 237, 23e, 25e, 26b, 26f and 271.
  - Protected episodes softer by > 0.3 or later by > 0.2 s: 0.
  - New <= -1.5 or <= -3.0 crossings: none. 237 764.7 (not protected) crosses -3.0 1.25 s earlier, on track 31 taken as lead at 53 m on the rail. The range closed 53.3 -> 44.1 m in 0.5 s (about -18 m/s) and the logged alpha car reached -3.50 at 766.2. This is the same as item 91's "earlier on a real closing lead". Its 10 over-closers (765.1-766.2, rail -13.5 vs range -5..-10 while ego braked) are the raw rail, which toggle off also publishes from 765.9.
  - 26f 516.9 (not protected): -2.14 -> +0.12. The toggle-off parser coasts -13.5 on track 30 at 58-60 m while the range opens 58.4 -> 60.3 m; the next measured U11 is -1.5 and the stock command is -0.20. The hold's clamp removes a stale-rail brake.
  - 25e 12:03 (item 90 dark lead, protected): track 59 published from 78 m at 724.36. -1.5 at 725.26 vs 725.66, -3.0 at 725.66 vs 726.06.
  - 25e 6:43: identical to toggle off (min -0.51).
  - 271 BM0 9:26, 27:33 and 29:52 (and all of 270, 271): lead publication identical to toggle off (0 differing lead frames). The pass-1 one-frame coast difference at 29:52 is gone.
- **Tests:** test_bosch_a_radar 144 (11 new for 129), honda 116, leads 6, range_vrel_assist 87, longitudinal_planner 512.
- **Recommendation:** the toggle can be offered for a watched drive, still default off. Road check: a lead closing past 13.5 m/s at 80-120 m should appear on radar about 0.4 s earlier than with the toggle off. No brake on an in-lane rail point whose range is flat.

- **Fix 1 retested, not shipped:** the parked coast-rise patch (/tmp/f1/fix1.patch) was rebased onto this and replayed on the 26 routes. It only ever makes a coasted vRel less closing, so it cannot brake earlier at 271 BM0 (0 differing frames there). 26c 12:28.8: planner -1.21 -> -0.94. It had one unprotected effect: 237 1188.2 -1.51 -> -1.37. It fixes nothing the owner reported, so it was reverted from the tree; the patch and notes stay in /tmp/f1 and /tmp/ri3.
- **Existing behaviour, unchanged:** with the toggle off, 26f 516.9 still dips to -1.95 from a stale -13.5 coast.

## 134. ICBM: no set-speed increase right after a lead change or toward a closing in-path target; model-only far-lead backstop; lead-change hysteresis. Unit tests and replay only; not driven.

- **Problem (route `…00000276--4be5263f89`, build 51964cb6, same ICBM code as HEAD; /tmp/r276/report.md), limited road evidence:**
  - 14:36.7: radar lead tid 5 left the path at 51.6 m. A slower car on a curve at 87-102 m showed only as a flickering vision lead (p 0.23-0.40, yRel +4..+8.5). ICBM raised the set 37.9 -> 43.5 mph toward it. Radar published it 0.2 s before the driver braked (-2.52).
  - 17:22.5: 13 reversals in 24 s. leadOne flipped between radar at 70 m and vision at 95 m.
  - 8:27.9: vision-only lead from 114 m slowing 25 -> 3 mph; the driver cancelled 3.3 s after engaging at 28.6 mph.
- **Change** (`selfdrive/car/redneck_cruise.py`, `selfdrive/car/card.py`; Honda ICBM only, same gate as the STATUS 128 far lead):
  - **Increase block** (`IncreaseBlock`). The target is capped at the cluster set speed, so a hold sends nothing and a decrease is never delayed. The cap applies:
    - for `INCREASE_BLOCK_AFTER_LEAD_CHANGE_S = 2.0` after leadOne is lost, after plan.hasLead drops, or after leadOne changes source (radar/vision), radar track id, or range by more than `LEAD_CHANGE_RANGE_JUMP_M = 15`;
    - while radarState leadOne/leadTwo, or modelV2.leadsV3[0] with prob >= `INCREASE_BLOCK_MODEL_PROB = 0.25`, is within `INCREASE_BLOCK_RANGE_M = 110` and closing faster than `INCREASE_BLOCK_CLOSING_MS = 5`.
    - Both sources are path-relative by construction: the model's lead is the lead on its path, and radard publishes only tracks matched to it. There is no raw-yRel gate (the 14:36.7 lead sat at y +8).
    - Raw liveTracks are not used, because there is no path-gated clutter filter for them.
  - card subscribes to `modelV2` on Honda ICBM only.
  - **Model-only far lead** (`get_model_only_far_lead_target_ms`). A vision-only leadOne with modelProb >= 0.5 that is closing faster than 8 m/s feeds the far-lead target even when plan.hasLead is False.
    - It always uses the uncorroborated 1.5 m/s^2. 271 BM3/BM4 vision errors (range +35-45 m, vRel about half) put the target too high, so on such a lead it only helps partly.
    - The planner (MPC) is unchanged.
  - **Hysteresis:** the lead-change hold is the lead-source hysteresis. A nearer lead lowers the set at once; the farther one can raise it only after 2 s of a stable lead.
- **Replay** (`/tmp/icbm3/sim.py`, the STATUS 126 sim plus modelV2 and leadTwo; open loop in vEgo, overstates hunting; compare base vs fix only):

  | Route | Reversals < 1.5 s | Longest episode | Lead drops kept mph | Phantom mph | Open-road s > 2 mph below target |
  |---|---|---|---|---|---|
  | 276 | 50 -> 27 | 5 -> 5 | 134 -> 121 | 121 -> 109 | 269.5 -> 278.4 |
  | 271 (seg 7+) | 110 -> 88 | 21 -> 14 | 363 -> 368 | 247 -> 250 | 479.6 -> 508.9 |
  | 26f | 34 -> 22 | 5 -> 5 | 177 -> 173 | 51 -> 50 | 160.9 -> 165.2 |
  | 270 | 31 -> 19 | 6 -> 4 | 117 -> 116 | 58 -> 53 | 125.3 -> 139.6 |

  - 276 14:36.7, set from -8 s to -1 s (base / fix):
    - base: 42.9, 42.9, 40.4, 38.5, 37.9, 37.9, 37.9, 41.6 (INCREASE from -2.2 s);
    - fix: the same down to 37.9, then held at 37.9 with no INCREASE (blocked from -3 s).
  - 276 6:58.1: first decel press -5.95 s and set 43.5 at -2 s in both. The fix drops base's 46.6 -> 48.5 bounce in the middle of the drop.
  - 276 8:27.9: unchanged (first decel press -0.75, set 28.6 at -2 s). hasLead was already True, and the existing far-lead path gave 27.9 at -0.5 (0.8 decel at p 0.74). The model-only path never binds on any of the four routes, so it is a backstop only.
  - 271 BM0-BM4 and 32:01: first press, first drop and set at -2 s are identical.
  - 276 17:15-17:50: reversals 10 -> 5.
  - Attribution, lead-change hold removed: reversals and open-road time equal base, and 14:36.7 still rises to 39.8 at -1 s.
  - Attribution, closing test removed: the route metrics equal the full fix, and 14:36.7 is still fully held. The closing test is kept as the guard for a slow car with no preceding lead change. Dropping the radar<->vision source trigger: 26f 22 -> 31 reversals, and it saves only about 6 s open-road on 271.
- **Cost:** open-road time below target rises by +9, +29, +4 and +14 s. Most of it is the 2 s loss hold re-armed by a flickering vision lead (271 22:19 7.6 s at 46 vs 47.8 mph).
- **20:25.8 (no lead, set 33.6 -> 49.7 after a CSC curve dip):** no recovery rate limit. There was no lead or closing target, and the driver braked 21 s before a stop. Nothing shows that the rise caused the brake.
- **Tests:**
  - `test_redneck_cruise.py`: 90 pass (9 new). The 3 new card tests fail with the card change reverted.
  - gas_override 2, cruise_speed 42, honda `test_icbm_counter_sync` 5 and `test_longitudinal_planner.py` 512 pass.
- **Road check to do:**
  - Behind a lead that turns off or leaves on a curve, the set should not rise for about 2 s, and not at all while a slower car is visible ahead.
  - Large lead-driven drops should keep their pace.
  - Watch for sluggish set recovery under a flickering vision lead.
- **Open:**
  - 8:27.9-type approaches at about 28 mph cannot be helped by the set speed (25 mph floor).
  - A far lead that radar publishes late (cause A) is not addressed here.
- **Params artifacts (follow-up):** Galaxy returned "not editable" for `NrdrLatRateFF` because the checked-in `common/params_pyx.so` lacked the key (item 12). `libcommon.a` and `params_pyx.so` rebuilt with item 4's pinned toolchain natively on an aarch64 Ubuntu 24.04 host (clang 18.1.3, system Python 3.12.3 + `python3.12-dev`, Cython 3.1.4, `SP_FORCE_TICI=1`, bind-mounted at `/work`, sconsign cleared). `params_pyx.cpp` came out byte-identical to the committed one; keys 854 → 855, the only addition `NrdrLatRateFF` (put/get round-trips). Static only.

## 135. D-053 rail fast path: a railed in-path lead that both range fits show closing faster than the rail arms after 3 corroborated updates from an 8-sample long fit, and is sized by the mean of the two fits. Rides `RangeDerivedVrel`, with the module constant `RANGE_VREL_RAIL_FAST = True`. Unit tests and open-loop replay only; not driven.

- **Problem (route `…00000271--4e9b9502db` BM0 9:26, seg9+28.4; limited road evidence plus replay):**
  - A near-stopped car was published at 118.8 m (-3.82 s relative to the bookmark). U11 was on its -13.5 rail while the range closed at about -21 to -23 m/s. The driver braked at -1.69 s.
  - Three things delayed D-053 (replay trace /tmp/rs/r271_t24.txt):
    - The track was dark for 1.07 s before publication, because u10 865 -> 546 was above 511. This is D-042 and is not changed here.
    - Arming came 1.22 s after publication: 1 not_lead cycle, then the short fit not fresh for 3 sweeps, then 10 sweeps waiting for the 15-sample long history, then 5 arm updates. The short and long fits already read -28 from the 5th sample on.
    - Once armed, min(short, long) sizing followed the short fit's dips. It published -15.4 to -16.3 at -1.8 to -1.6 while the trailing 1 s range fit read -18.1 to -19.9.
  - **26c 4:08** is not a rail case. U11 lagged rather than railed, and the assist was blocked by `|yRel| > 1.5` on a curve (y 1.5 -> 9.3 m), by D-043 coasts and by the long residual. Left open; see below.
  - **26c 12:27:** the rail was close to true (range fit -11.5 to -14.6), so there was nothing to correct.
- **Change** (`selfdrive/controls/radard.py`, `Track._update_range_assist` and `_fit_long_range`; constants in a commented block above `BOSCH_A_U11_LOW_RAIL_MPS`). It applies only while U11 is on the rail:
  - The long fit may be taken over `RANGE_VREL_RAIL_LONG_MIN_SAMPLES = 8` samples, clamped to `RANGE_VREL_LONG_SAMPLES`. Its span floor is `RANGE_VREL_RAIL_LONG_MIN_SPAN_S = 0.45` s. The residual, backward-lead and span-ceiling guards are unchanged.
  - `RANGE_VREL_RAIL_ARM_UPDATES = 3` consecutive measured updates, each with the smaller of the short and long disagreements >= 2.0 m/s, arm it. Both fits must corroborate, which is stricter than the existing long-only rail decision. The 5-update rule is unchanged off the rail and for the old path.
  - While railed, the correction is sized by the mean of the two disagreements (`RANGE_VREL_RAIL_SIZE_MEAN`). That is never beyond the more-closing range fit. It stays under the 8 m/s cap and the vLead >= 0 bound. It publishes a bound and deletes nothing.
  - With `RANGE_VREL_RAIL_FAST = False` the behaviour is the pre-change behaviour.
- **Replay, 27 routes, fix vs current** (both with `RangeDerivedVrel` on and `BoschARailInterval` off; 271 from seg 7, open-loop radar; harness /tmp/rs/ab130/):
  - 271 BM0: the first corrected vRel moves from -2.59 to -3.19 s (0.60 s after publication, not 1.22). It publishes -20.0, bound by vLead >= 0, against range fits of -19.6/-23.4. At -1.8 to -1.6 it publishes -17.9 to -16.8, where it was -16.3 to -15.4.
  - 271 BM0 planner: the -1.5 crossing moves -2.34 -> -2.49 s, the -2.0 crossing -2.04 -> -2.19 s, and the minimum before the driver brake -2.43 -> -2.50. There is still no -3.0 before the driver.
    - The corrected lead sits on the -1.0 ACC comfort floor (item 93) from -3.14 to -2.84 s. That floor, not the radar vRel, is now the bottleneck.
  - 26c 4:08, 26c 12:27, 25e 12:03 and 26f 516.9: 0 differing lead frames and no fast arms.
  - 25e 6:43 (403 s, track 48, the range-walk trap): identical (min -0.51).
  - 276 13:46.6 (flat-range rail, negative control): tid 5 was published at -13.5 at 56.4 -> 55.1 m, and was coasted there. Fix and current are identical: no correction, no fast arm, and the same planner output (+0.50..+0.78). All of 276 has 0 differing frames.
  - Points lost 0, lead points lost 0. Protected brakes softer by > 0.3 or later by > 0.2 s: 0. Spurious new <= -1.5 / <= -3.0 crossings: 0.
  - 19 fast arms fleet-wide (17 on the lead), all on the rail at 57-105 m. Corrected lead time 212.5 -> 219.7 s.
  - Moved episodes, both with vision-confirmed leads:
    - 236 771.9: -1.5 crossing 0.25 s earlier.
    - 268 700.9: -1.5 crossing 0.15 s earlier; -3.0 crossing 0.70 s earlier.
  - Variants replayed:
    - min sizing (V1): tracks the fits worse.
    - arm 4 (V2): one MPC solver-error artifact at 260 446.9.
    - 10 samples / 0.6 s (V3): later.
    - None gave a benefit over the shipped constants.
- **Tests:** test_bosch_a_radar 134, honda 116, leads 6, range_vrel_assist 92 (a `pre130` fixture pins the old-mechanism tests to `RANGE_VREL_RAIL_FAST=False`; new TestRailFastPath: fast arm with the correction between the fits, the 276 flat-range rail gives no correction, a 1.5 m step does not arm, and the cap/vLead bound), longitudinal_planner 512.
- **Open:**
  - 26c 4:08 needs the `|yRel| <= 1.5` geometry gate revisited. At 80 m, 9 m of y is only about 6 deg of azimuth, and the gate is a lane proxy, not the 10.8 deg bound its comment describes. The long span and residual also block that case. Not changed here.
  - The 1.07 s dark time at 271 BM0 is D-042 (u10 511); not changed.
- **Recommendation:** replay supports it (0 lost points, 0 spurious brakes, 0 protected regressions) for a watched drive. The gain is small (about 0.15 s and 0.07 m/s^2 at 271 BM0) until the -1.0 comfort floor is revisited. Road check: a railed lead closing well past 13.5 m/s at 60-120 m should show a corrected vRel about 0.6 s after publication.

## 136. Gas-override census for commaai/openpilot PR 39015 ("gas override boost"): not worth porting. Offline log analysis only; nothing changed in the controls.

**Question.** PR 39015 raises the e2e target (`modelV2.action.desiredAcceleration`) by up to 0.2 m/s² after the driver presses gas while the e2e target is below the MPC target in Experimental Mode (≥10 mph, 0.05 per press, held for the drive, also softens e2e braking between −1.0 and −0.5). Would it have anything to fix here, in particular a lead pulling away?

**Tool.** `tools/longitudinal/gas_override_census.py ROUTE_DIR...`: every rising edge of `gasPressed` while engaged at ≥4.5 m/s (presses within 3 s merged), the median of the 1 s before it. The MPC target is estimated with `get_accel_from_plan` on `longitudinalPlan.speeds/accels` at 0.5 s (it tracks `aTarget` on the MPC-limited rows). Classes: `e2e_slow_accel` (exp mode, e2e < MPC − 0.15 and e2e ≥ 0, the PR's case), `e2e_brake` (same but e2e < 0), `mpc_brake` / `mpc_slow`. "Lead pulling away" = lead status and (aLeadK > 0.3 or vRel > 0.5).

**Result, 28 local Civic Bosch routes (0000020c … 00000277), 177 presses; the 13 alpha-long routes (`openpilotLongitudinalControl` = 1: 20c 232 236 237 239 23a 23b 23e 241 245 268 26b 26c) carry 109.** On the stock-ACC routes `aTarget` is not actuated, so only the alpha-long numbers matter:

| class | exp mode | ACC mode | of which lead pulling away |
|---|---|---|---|
| e2e_slow_accel (PR target) | 4 | — | 1 (236 22:22.3, vision lead 79 m, e2e 0.37 vs MPC 0.93) |
| e2e_brake | 12 | — | 2 |
| mpc_brake | 26 | 44 | 17 |
| mpc_slow | 8 | 15 | 12 |

- The PR's trigger does not check the sign of the e2e target, so on these routes it would have grown from 16 presses, 12 of them the model braking harder than the MPC. Its main input here is model over-braking, and it would then soften the model's light braking for the rest of the drive.
- A lead pulling away with the driver pressing gas is almost always MPC-limited (29 of 32), and 17 of those have the MPC still braking (e.g. 236 17:19.4, MPC −0.59 with vRel +3.88 at 34 m; 236 35:00.4, −1.62 with vRel +6.23 at 16.7 m). The e2e target is not what is slow to respond to a departing lead; the lead/follow path is.
- In this fork the model's stop plans reach the MPC through the cruise speed (`spVCruise`, item 31, route 00000241 1:59.6), not through `desiredAcceleration`, so the PR's `model_limited` test misses them.

**Decision.** Do not port PR 39015. Its `accelBoost @40` would also collide with `leadTrajectoryX0 @40` in our `LongitudinalPlan`. **Open:** MPC response to a lead pulling away (the 17 `mpc_brake` rows above) is the lead to follow for "more responsive to lead accelerating".

## 137. Lateral jerk at the 50 mph band edge (route 277): the Lat*Scale trims now slew, and a band with an I trim of 0 no longer hides a live integrator. Unit tests, open-loop replay and sim only; not driven.

**What the owner saw.** Route `11c8fa231c0499ed/00000277--2f5fd64a58`, around 5:00–5:15. At 50 mph on a straight, with a flat target and no press, the wheel went left at +160 °/s, from −0.4° to +5.3° in 120 ms. The driver took over and braked. Route tuning: LatIScale 50/75/0 (low/standard/highway), commit 28d4eda8.

**Cause (log).**
- `_lat_pid_scale_banded` switches the P/I/F trims hard at 25 and 50 mph.
- `PIDController` integrates at the unscaled gain, and it froze only on a safety limit, a press, or v < 2 m/s. So while the highway I trim was 0, `pid.i` kept winding where nothing could see it (0.514).
- As vEgo went 50.00 → 49.98 mph, the trim stepped 0 → 0.75. The output jumped −0.00 → +0.39 in one frame.
- The same happened twice more in that minute, as speed flapped across 50 mph: a +0.37 step, and a −0.21 step to the right.
- The default trims (highway I = 0) have the same exposure.

**Fix (`latcontrol_pid.py`, modified-EPS path).**
- The applied P/I/F trims move toward the banded (or `LatGainSchedule`) value at `NRDR_TRIM_SLEW_PER_S = 0.5` per second, instead of stepping.
- While the applied I trim is 0, the integrator is frozen and bled out with `NRDR_HIDDEN_I_BLEED_TAU = 2.0` s. Coming back into an I band therefore ramps in from about zero.
- The state resets when lateral control is inactive.
- No new params.

**Evidence.**
- Unit (`test_latcontrol_pid_trim_slew.py`): a steady 0.3° error held above 50 mph, then 49.98 mph.
  - HEAD: hidden i reaches 0.65, and the output steps 0.485 in one frame.
  - Fix: hidden i is 0.00, and the largest step is 0.0012.
  - Both tests fail on HEAD.
- Open-loop replay, 277 segs 3–6 (logged tuning):

  | | HEAD | fix |
  |---|---|---|
  | step at 311.26 s (the jerk) | 0.266 | 0.000 |
  | step at 282.78 s | 0.214 | 0.018 |
  | frames with a step > 0.1 | 8 | 2 |
  | frames with a step > 0.05 | 23 | 9 |

  The two steps > 0.1 left with the fix are target changes, apart from the 25 mph one below.
- Sim (plant_d5, routes 263/268/271/276, Kp/Ki scale 1.0, with and without `NrdrLatRateFF=0.5`): no regression.
  - Standard-band error rms is equal or 0.01–0.04° lower.
  - Straight-line bias moves toward 0: for example, 263 goes −0.03 → +0.00 and low speed −0.25 → −0.15.
  - 268 highway lag falls from 0.60 s to 0.42 s.

**Not fixed, noted.** The base gains in `interface.py` step as well: kpBP/kiBP are `[0, 11.18, 11.18, 22.35]`, so kp goes 0.024 → 0.048 at 25 mph. In the replay this gives a −0.11 step at 318.39 s, with a 3.7° error at the crossing. It is P only (no hidden state), so its size scales with the error at that moment. Making it continuous is a base-tune change and needs its own sim pass. Not done.

## 138. ICBM: close-lead cap on the launch target; a radar<->vision flip of the same departing car no longer re-arms the increase hold. Unit tests and replay only; not driven.

- **Problem (route `…00000277--2f5fd64a58`, segs 17-34 parking lot excluded; /tmp/r277), limited road evidence plus replay:**
  - 16:34.1: launching from a stop behind a radar lead 7-38 m ahead (vLead 12 -> 30 mph), ICBM raised the set 24.9 -> 48.5 mph, then cut it to 28.6 once the launch ended. The driver braked.
  - 3:51.5 (sim with STATUS 134): a departing lead at 77-94 m flickered radar<->vision at 52-57 mph. Every flip re-armed the 2 s increase hold, and the set sat up to 5 mph low for 12.6 s.
- **Change** (`selfdrive/car/redneck_cruise.py`, `selfdrive/car/card.py`; Honda ICBM only, same gate as STATUS 128/134):
  - **Launch cap** (`close_lead_cap_ms`). While a corroborated leadOne (radar, or modelProb >= 0.7) is within `LAUNCH_LEAD_CAP_RANGE_M = 30` m or `LAUNCH_LEAD_CAP_HEADWAY_S = 3.0` s, the launch target is capped at max(normal target, vLead + `LAUNCH_LEAD_SPEED_MARGIN_MS = 5 mph`).
    - The vLead term keeps the set off the 25 mph floor while the lead pulls away (route 260 8:39).
    - The launch also ends once the set has reached the cap and vEgo is within 2 mph of a lead doing >= 25 mph. Ending it behind a slower lead put the set back on the floor behind a faster lead for up to 2.3 s per launch.
    - 3.0 s rather than 2.5 s: at 16:34.1 the lead sat at 2.7-2.9 s from -3 s to the brake.
    - The gas-release floor is not capped. Capping it cut 277 38:26.4 from 46.0 to 41.6 mph while the driver was passing a lead at 47-61 m.
    - A launch with no lead, or with the lead beyond both gates, is unchanged.
  - **Source flip** (`lead_changed`). A radar<->vision flip is no longer a lead change when all three hold:
    - the range stays within `LEAD_CHANGE_RANGE_JUMP_M = 15` m;
    - neither side is closing faster than `LEAD_SOURCE_FLIP_CLOSING_MS = 1.0` m/s;
    - the lead is at least `LEAD_SOURCE_FLIP_MIN_HEADWAY_S = 2.5` s ahead.
    - Track-id changes, losses and range jumps still re-arm the hold.
    - Without the headway gate, 277 11:07 (lead at 37-45 m, 2.3 s) gained 5 reversals. Sweep: 2.0 s no change, 2.5 s best, 3.0 s lost 271's open-road gain.
- **Replay** (`/tmp/icbm4/sim.py`, base = HEAD with 134; open loop in vEgo, so compare base vs fix only):

  | Route | Reversals < 1.5 s | Longest episode | Lead drops kept mph | Phantom mph | Open-road s > 2 mph below target |
  |---|---|---|---|---|---|
  | 277 (excl. 17-34) | 32 -> 36 | 5 -> 5 | 200 -> 191 | 181 -> 172 | 249.5 -> 249.1 |
  | 276 | 27 -> 29 | 5 -> 5 | 121 -> 121 | 109 -> 109 | 278.4 -> 278.4 |
  | 271 (seg 7+) | 88 -> 91 | 14 -> 14 | 368 -> 311 | 250 -> 211 | 508.9 -> 502.7 |
  | 26f | 22 -> 25 | 5 -> 5 | 173 -> 121 | 50 -> 33 | 165.2 -> 165.7 |
  | 270 | 19 -> 23 | 4 -> 6 | 116 -> 103 | 53 -> 40 | 139.6 -> 139.1 |

  - Attribution of the reversals:
    - flip only: 277 +2, 276 +2, 271 +3, 26f +1, 270 +3;
    - launch only: 277 +2, 26f +3, 270 -2.
    - STATUS 134 measured 26f 22 -> 31 for dropping all flips; this change gives +1 on 26f.
    - The fewer drops and phantom mph are the launch cap: fewer launch overshoots to undo.
  - 277 16:34.1, set from -8 to +1 s: base 46.0, 47.8, 41.6, 35.4, 29.8, 28.6, 30.4, 31.7, 32.9, 32.9; fix 28.6, 26.7, 29.8, 34.8, 31.7, 29.8, 30.4, 31.7, 32.9, 32.9. The peak is 35.4 instead of 48.5.
  - 277 3:51.5, -8..+16 s: the hold drops 16.6 -> 8.1 s, and the time with the set > 2 mph below vEgo drops 12.7 -> 6.2 s. From +0 s the set is 53.4-55.9, where base had 51.0-52.8. The open-road metric does not move, because the lead is within the planner's lead target.
  - Unchanged (set -8..+1 s, first decel press):
    - 276 14:36.7 (held at 37.9, no INCREASE);
    - 276 6:58.1;
    - 277 4:23.1 and 6:46.1 (increases still blocked);
    - 277 38:26.4.
  - 271 BM0-BM4 and 32:01: first press, first drop and set at -2 s are identical.
  - Launches: 11 of 15 changed across the 5 routes. Max set in 20 s fell at 277 16:21 (49.7 -> 35.4), 271 14:34/20:39/28:04, and 26f 1:50/3:11/8:07.
    - Set on the floor behind a faster lead: 26f 1:50 0 -> 1.1 s and 271 14:34 0 -> 0.5 s.
    - 26f 8:07 and 270 2:12 improved (1.5 -> 0, 1.4 -> 0 s).
- **Tests:**
  - `test_redneck_cruise.py`: 96 pass (6 new; the flip assertion in `test_lead_changed` now passes vEgo). `test_card_launch_capped_behind_close_lead` fails with the card change reverted.
  - gas_override 2, cruise_speed 42, honda `test_icbm_counter_sync` 5 and `test_longitudinal_planner.py` 512 pass.
- **Road check to do:**
  - Launching behind a close lead, the set should track the lead's speed plus about 5 mph instead of jumping to the cruise target.
  - Behind a departing lead at 80+ m that flickers radar/vision, the set should keep rising.
  - Watch for 1-2 mph hunting behind a lead at 2.5-3 s that flips source.
- **Open:** the reversal cost is small but consistent (+2..+4 per route). The sim is open loop in vEgo, so it cannot say whether stock ACC would close on the lead less at 16:34.1.

**136a. Vision-only e2e (radar off) changes the answer: the PR's case is real there, the PR's mechanism is still the wrong fix.** Konik route list for `11c8fa231c0499ed`: 192 Civic routes over 1 mile; segment-0 `carParams` shows **100** with `openpilotLongitudinalControl` = 1 and `radarUnavailable` = 1 (65 on `night-star-testing`, 17 `night-star-bosch-radar`, 11 `ns-bosch-radar-testing`, 6 `night-star-sp-08.08.2026`, 1 `peter`), ~23 h engaged, ~15 h of it in Experimental Mode. Full qlogs for all 100; rlogs exist for only 63 of the 363 press segments (13 routes; the rest were never uploaded), so most presses are classified from qlogs, which have no `modelV2`. Proxy: exp mode and `aTarget` < MPC estimate − 0.15 = "something other than the MPC is lower". Against the 90 rlog presses where e2e is known it agrees 87/90 (3 over-counts, no misses).

| exp-mode presses | rlog, e2e known (90) | qlog proxy, all (518) |
|---|---|---|
| model lower, asking for accel ≥ 0 (PR case) | 23, **15 with a lead pulling away** | 110, 57 with a lead pulling away |
| model lower, braking | 12 | 105 |
| MPC lower, braking | 42 | 224 |
| MPC lower, accel ≥ 0 | 13 | 79 |

- The typical PR-case press is a vision lead 50–100 m ahead pulling away at +1–3 m/s, e2e +0.0…+0.5 while the MPC allows +0.7…+0.9 (e.g. 0000006d--4715a1d4cc 4:22.5 e2e 0.23 vs MPC 0.75; 000000cb--2506619877 11:36.3 0.15 vs 0.88). The gap is ~0.5 m/s², more than the PR's 0.2 cap, which also needs 4 presses to reach.
- The PR's trigger would still take about as many inputs from model over-braking (105) as from slow acceleration (110), and it softens light braking for the rest of the drive.
- **Open, owner decision:** a stateless lead-departure rule in the exp-mode arbitration (lead present and pulling away, MPC higher than e2e → move toward the MPC, braking untouched) would address the 57/110 directly. Not implemented.

## 139. The base kp step at 25 mph no longer jumps the output: the applied kp slews. Also answers "can the target low-pass filter go?" (not while `NrdrLatRateFF` is on). Unit tests, open-loop replay and sim only; not driven.

**Base gain slew.**
- In `interface.py`, every modified-EPS Honda has kpBP/kiBP of `[0, 25 mph − 1e-3, 25 mph, 50 mph]`, so kp doubles at 25 mph (0.024 → 0.048).
- P is the gain times the current error, so the output stepped by error × 0.024 at the crossing. Route 277 open-loop replay: −0.11 in one frame at 318.39 s, with a 3.7° error (STATUS 137).
- On the modified-EPS path `latcontrol_pid.py` now slews the applied kp toward `pid.k_p` at `NRDR_KP_SLEW_REL_PER_S = 1.0`, which is 100 %/s of the larger gain, so the doubling takes about 0.5 s. The state resets when lateral control is inactive.
- The tune in `interface.py` is unchanged, so every steady-speed gain is the one that was road-tuned.
- The ki step needs nothing: the integrator stores ki × error already accumulated, so a ki step only changes its future rate.

**Evidence.**
- Unit test `test_crossing_the_25mph_base_gain_step_does_not_step_p`: a 3° error held across 25 mph. The largest step is under 0.01, and kp settles on the tuned value. The test fails on HEAD.
- Route 277 open-loop replay:

  | | STATUS 137 code | kp slew |
  |---|---|---|
  | step at 318.39 s | −0.108 | −0.007 |
  | largest step within ±1 s | 0.108 | 0.020 |
  | frames with a step > 0.1 | 2 | 1 |
  | frames with a step > 0.05 | 9 | 8 |

- Sim (plant_d5, 263/268/271/276): unchanged to ±0.01° error rms. Low-speed sign changes 0.34/0.32 → 0.31/0.30 on 263/268.

**Target low-pass filter (`HondaTorqueLowPassFilter`, tau 0.1 s): keep it while `NrdrLatRateFF` is used.**
- Sim, same routes. Error rms is against the unshaped target; sign changes are per second at the 0.15° deadband.

  | band | metric | LPF on | LPF off |
  |---|---|---|---|
  | 25–50 mph | error rms ° | 1.23 / 1.27 / 1.36 / 1.10 | 1.12 / 1.16 / 1.12 / 0.91 |
  | 25–50 mph | lag s | 0.43 / 0.47 / 0.38 / 0.33 | 0.34 / 0.33 / 0.28 / 0.25 |
  | 25–50 mph | sign changes | 0.28 / 0.24 / 0.32 / 0.33 | 0.33 / 0.28 / 0.40 / 0.35 |
  | < 25 mph | sign changes | 0.31 / 0.30 / 0.33 / 0.33 | 0.45 / 0.36 / 0.45 / 0.55 |

  Low-speed error still falls with the filter off (11.1 / 20.4 / 12.8 / 18.6 → 10.5 / 19.8 / 11.5 / 18.3).
- Frame-to-frame torque change (rms, % of max, near-straight):
  - LPF alone off: up 5–45 %. For example 25–50 mph goes 0.16–0.17 → 0.17–0.19; the wheel angle high-pass is flat to 3 %.
  - `NrdrLatRateFF 0.5` with the LPF on: low speed 0.10–0.34 → 0.33–0.49.
  - Rate FF 0.5 with the LPF off: 2.5–3.9 % below 25 mph, 0.67–0.94 % at 25–50 mph, and 0.39–0.54 % above 50 mph. That is 3–8× the filtered case.
- Reason: the rate feedforward is a derivative of the target. The LPF is what keeps the model's frame-to-frame target noise out of it.
- The sim plant is a linear fit, so the wheel barely shows this torque buzz. On the car it would be felt as rack buzz or chatter. That is inferred, not measured.
- `NrdrLatAngleRateLimit` 0 (300 °/s limit off): identical to the LPF-off case on every metric. The limit never binds on these routes.
- **If the LPF is to go:**
  1. Give the rate feedforward its own filtered derivative first.
  2. Then drop the LPF.
  3. Expect about 5–15 % more low-speed weave (sign changes).
  Not done.

## 140. Lateral-acceleration-space study (owner request, step 1 toward replacing the angle-space PID with a torque controller + live learning + firmware VGR). Offline log analysis only; nothing in the controls changed.

**Tool.** `tools/lateral/lat_accel_space_study.py` (tests in `tools/lateral/tests/test_lat_accel_space_study.py`; they need `PARAMS_ROOT` set). It runs on 28 HONDA_CIVIC_BOSCH routes (`000002*`), all EPS `39990-TBA,C020`, all on the PID tune, at 20 Hz.
- It fits the plain upstream model form only, with no StarPilot controller code, so the answer holds for upstream as well.
- Log facts:
  - `carState.yawRate` and `steeringTorqueEps` are 0 on every frame on this port.
  - Measured curvature is therefore −(calibrated livePose yaw)/v.
  - Torque is `-carOutput.actuatorsOutput.torque`, as torqued uses it.
  - liveDelay is about 0.48 s.

**A. Angle → curvature, three models.** M0 is a constant SR, M1 is James's firmware VGR (`vgr_physical_to_linear`) then a constant SR, and M2 is `NRDR_SR_CURVE_BY_FP`.
- Pooled fits:

  | Model | SR | K | per-route SR std |
  |---|---|---|---|
  | M0 | 14.81 | 6.6e-4 | 0.52 |
  | M1 | 15.27 | 5.9e-4 | 0.29 |
  | M2 | 15.13 | 6.1e-4 | 0.31 |

  With driver-pressed frames kept, the per-route SR std is 0.34 / 0.12 / 0.09.
- Lat-accel residual rms (m/s², M0 / M1 / M2), pressed frames kept:

  | \|angle\| | residual rms |
  |---|---|
  | 0–5° | .062 / .052 / .052 |
  | 15–45° | .092 / .063 / .065 |
  | 45–90° | .109 / .053 / .048 |
  | 90°+ | .073 / .045 / .043 |

  M0 also pulls K up to 9.5e-4 and carries a +0.03–0.05 bias near centre. At small angles and at speed all three are equal: the ~0.05 floor is noise, not the rack model.
- **Result:** VGR correction (M1, or M2 about equally) is needed for a constant-SR torque path at large angles and low speed. It halves the per-route SR scatter. Neither `latcontrol_torque`'s `measured_curvature` nor `paramsd` uses VGR today.

**B. Torque → lateral accel**, fitting torque = la/LAF + friction·clip(jerk/0.3) + offset.
- Study fit (±1 s press margin, torqued-style delay):

  | band | LAF | friction | R² |
  |---|---|---|---|
  | pooled | 11.1 | .033 | .49 |
  | < 25 mph | 9.7 | .095 | .38 |
  | 25–50 mph | 11.5 | .025 | .65 |
  | > 50 mph | 11.1 | .019 | .61 |

  Using the pooled fit instead of the band fit costs ≤ 0.005 rms above 25 mph.
- Audit refit (cruder: 0.5 s shift, no press margin, gradient jerk): LAF 11.8 / 12.1 / 11.9 across the three bands and friction 0.069 / 0.008 / 0.003.
- **Robust across both fits:**
  - LAF is about 11–12 and near speed-independent above 25 mph.
  - Friction is several times higher below 25 mph.
- **Not robust:** the low-speed LAF drop. It moves with the frame filtering.
- VGR does not change the torque map: M0/M1 angle-derived lat accel gives the same LAF and R².
- The map is near-linear to ±2 m/s² at 25+ mph, with no centre deadzone at 0.2 m/s² resolution. Below 25 mph it steepens above 1 m/s².
- **Scale:** upstream `params.toml` has HONDA_CIVIC_BOSCH LAF 1.69. The modified EPS is about 6–7× that, so stock values, fleet values and the `HONDA_CIVIC_BOSCH` NNFF model (stock EPS, presumably) do not apply.
- liveTorqueParameters is logged but invalid (LAF 0) on every route, because torqued does not use its params under a PID tune.

**Caveats.**
- The torque here is the PID's closed-loop command, not a measured EPS torque. Hence R² 0.35–0.65; the low-speed numbers partly reflect PID behaviour.
- Roll is constant at about 0.046 rad on every route. That looks like mount roll, not road roll, and the fit's offset absorbs it (zero-torque point ≈ −0.2 m/s²).
- The large-angle bins are thin without pressed frames (256–595 samples).

**What this means for the plan.**
- One lateral-accel model does cover 25 mph and up: one LAF, low friction.
- Below 25 mph it needs speed-dependent friction. Upstream's torque controller does not have that; it would be a small, principled addition, not a band.
- The firmware VGR belongs in opendbc as one angle → centre-equivalent-angle conversion used before `VehicleModel.calc_curvature`, by both the torque controller's measurement and paramsd. It should not go in StarPilot's `latcontrol_torque`.
- StarPilot's Civic-modified torque branch already layers its own patches: LAF ×1.2, `get_civic_bosch_modified_b_ff_scale` side/phase/low-speed shaping, a fixed friction threshold of 0.30, a friction scale, and the centre deadzone. A clean trial should bypass them.

## 136b. `ExpLeadDepartureAssist` (new, default off): Experimental Mode lifts the e2e target toward the MPC behind a lead pulling away. Unit tests and open-loop replay only; not driven.

**Rule** (`longitudinal_planner.py`, `get_exp_lead_departure_weight` / `apply_exp_lead_departure` / `update_exp_lead_departure`, called right after the speed handoff in the e2e/MPC arbitration):
- Arms on a lead (radar, or vision with modelProb ≥ 0.5) at or beyond `tFollow · vEgo`, pulling away (weight ramps over vRel 0.3–1.0 m/s), aLeadK ≥ −0.2, vEgo ≥ 4.5 m/s, no e2e stop / forcingStop / redLight.
- Lift = weight · min(0.5, 0.6 · (MPC − e2e)), faded to 0 as e2e falls from 0 to −0.15 (below −0.15 untouched). Never above the MPC target, never lowers the target, applies before the planner's later caps.
- Weight rises with τ 0.5 s, falls with τ 0.15 s, and drops to 0 at once when the lead closes (vRel < 0) or brakes, or a stop is planned. The lift rises at most 1 m/s³; drops are not limited (toward braking is the safe side).
- Works with radar or vision leads; the owner asked about vision-only and kept it for both.

**Evidence.**
- Unit tests: `test_exp_lead_departure.py` 18 new; with `test_longitudinal_planner.py` and `test_starpilot_variables.py`, 566 pass.
- Open-loop replay: `tools/longitudinal/exp_lead_departure_replay.py ROUTE_DIR... [--presses FILE]` runs the planner's own method on every engaged Experimental Mode `longitudinalPlan` frame from rlogs (baseline = min(e2e, MPC estimate), later caps not replayed; the car does not respond). 24 routes, 96.9 exp-mode engaged minutes: 12 vision-only Konik routes with rlogs (0000000f, 00000012, 0000003f, 00000044, 00000063, 00000066, 0000006d, 00000073, 00000091, 000000c7, 000000cb, 00000150) + 0000020c (vision-only) + 11 radar alpha routes (232 236 237 239 23a 23e 241 245 268 26b 26c).
  - Acts 7.4 % of exp-mode time, 292 episodes: vision-only 13.4 %, radar 2.3 %. Lift p50 0.09–0.24, p95 ≤ 0.48, max 0.50 m/s². Largest one-frame rise 0.050 m/s² (1 m/s³).
  - 0 frames lifting while e2e < −0.15; 0 frames lifting > 0.05 while the lead closes faster than 0.5 m/s or brakes harder than −1.0.
  - Covers 15/15 rlog gas presses of class `e2e_slow_accel` with a lead pulling away (item 136a): lifting in the 1.5 s before each.
- Tuning from the replay: the vRel ramp started at 0.5–2.0 m/s and covered 1/15 (e.g. 0000006d 4:22.5 had the lead at +1.0–1.4 m/s and lifted only 0.05–0.11); 0.3–1.0 covers 15/15. The immediate drop and the rise limit were added after the first replay showed decay tails over closing leads and 0.24 m/s² one-frame rises from MPC jumps.

**Params.** Key `ExpLeadDepartureAssist` (BOOL, default 0). `common/params_pyx.so` and `libcommon.a` rebuilt natively on an aarch64 Ubuntu 24.04 host with the pinned toolchain (clang 18.1.3, system Python 3.12.3, Cython 3.1.4, `SP_FORCE_TICI=1`, repo bind-mounted at `/work`, sconsign cleared): keys 855 → 856 against the committed blob, the only addition `ExpLeadDepartureAssist`; `params_pyx.cpp` byte-identical; put/get round-trips. Commit e995fdbd. Galaxy: Advanced Longitudinal Tune → "Follow Departing Leads (Experimental)".

**Road check to do.** Behind a car pulling away from a light or merging ahead, Experimental Mode should pick up without a gas press; it should let go at once when that car brakes or a slower car cuts in. Watch vision-only drives at 50–100 m leads.

### 136c. First drive with the toggle, route 11c8fa231c0499ed|00000278--8f101d683e (owner: "more eager to speed but also brakes faster in exp mode"). Log decode and replay only; nothing changed.

- Build a0940b9f: it contains the first assist version 38676190 (vRel ramp 0.5–2.0 m/s, no immediate drop, no rise limit, no brake fade), not the tuned 65d42a95. Radar alpha long (`radarUnavailable` 0, 88 % of exp-mode lead time radar); 13.6 engaged min, 9.4 in Experimental Mode.
- `initData` params carry `ExpLeadDepartureAssist` = 0 (loggerd records them once at route start). The logged aTarget matches a replay of 38676190 to ±0.01 from 5:39 to 6:49 and shows no lift at 4:59–5:08 or 13:20–14:41, where the replay would lift up to 0.36. So the toggle was switched on after 5:08 and was off again by 13:20.
- While it was on, it lifted > 0.03 m/s² for about 6 s in total: 5:58 (up to 0.08, lead +1.2 m/s) and 6:47 (up to 0.24 for ~1.5 s, lead accelerating at +2–3.7 m/s²; followed by aTarget ≥ −0.44).
- The hard brakes in that window were not preceded by the assist: lift ≤ 0.01 in the 8 s before each. They were:
  - 5:53, −1.20, lead closing at 4.2 m/s and braking at −1.2;
  - 6:20.8, −3.50, lead braking at −3.6;
  - 6:29.6, −3.50;
  - 6:33.8.
- The drive's other hard targets were also outside the window and made with the toggle off (7:28 −3.22, 12:15 −2.59, 14:14 −2.72). The launch at 13:03 (aTarget 0.35 above min(e2e, MPC) from standstill) is another planner path; the assist is disarmed below 4.5 m/s.
- Verdict: this drive does not show the assist causing either feel. Its effect was too small and too short, and the braking came from real closing/braking leads. The device should update to 65d42a95 before a second trial.

### 136d. Routes 11c8fa231c0499ed|00000280--d02d9c2f8e and |00000283--fe4e75f88b: the tuned assist runs on the road as built. Log decode and replay only; nothing changed.

- Builds 63827356 (280) and a37852f8 (283) both contain 65d42a95; the assist code is unchanged since. Radar alpha long, 89 / 94 % of exp-mode lead time radar.
- `initData` shows the toggle 0 on 280 (switched on mid-drive, first lift at 7:01) and 1 on 283.
- On every frame where the replay lifts > 0.05, the logged aTarget − min(e2e, MPC) equals the replayed lift within 0.02 on 96 % (280) and 95 % of frames (283), and is never ~0.
- 280: 20 episodes, 41 s, 4.2 % of 16.1 exp min, max 0.42. 283: 70 episodes, 116 s, 7.1 % of 27.3 exp min, max 0.50. For example, 283 7:59–8:05 held +0.45 for 5 s behind a radar lead pulling away at +2 m/s, 57–62 mph.
- The harder brakes within 5 s after an episode were new events, not the assist:
  - 283 8:10: a slower lead at 45 m closing at 9.7 m/s, MPC −3.2;
  - 283 18:52.8: the radar lead's vRel swung +4.5 → −5.0 → +4.5 and aLeadK −6.6 in 1.5 s, for a −3.5 target lasting ~0.5 s; the assist had already dropped at 18:52.0 on aLeadK < −0.2;
  - 283 5:30: a vision cut-in at 49 m, the assist dropped at once;
  - 283 13:28: e2e's own −0.59 after the vision lead was lost.
- Two things to watch:
  - The release is a one-frame step by design: 29 steps > 0.15 and 11 > 0.3 on 283 (largest 0.50), 4 on 280. Every step is felt as a small lift-off.
  - 283 13:25 lifted to 0.46 behind a vision lead whose dRel jumped 28 → 55 → 44 → 66 m before it was lost; the model-probability gate passed it.
- Softening candidate (not applied): limit the release to ~3 m/s³ (0.5 m/s² over ~0.17 s) and keep the instant drop only for a lead closing faster than 0.5 m/s or braking harder than −1.0.

### 136e. `ExpLeadDepartureAssist` release smoothed (owner request after 136d). Unit tests and open-loop replay only; not driven.

- The lift now falls at most 3 m/s³ (`EXP_LEAD_DEPARTURE_MAX_LIFT_FALL`), i.e. a full 0.5 m/s² lift releases over ~0.17 s instead of in one 50 ms frame. The weight still disarms at once on vRel < 0 or aLeadK < −0.2; only the output is ramped.
- Still instant for:
  - a lead closing faster than 0.5 m/s or braking harder than −1.0 m/s² (`EXP_LEAD_DEPARTURE_URGENT_*`);
  - a planned stop / red light;
  - e2e below −0.15;
  - the toggle turning off.
- The held lift is capped so the output never exceeds the MPC estimate.
- Replay (same code path) on 280 / 283:
  - largest one-frame release drops from 0.41 / 0.50 to 0.15 / 0.32;
  - every drop > 0.16 left on 283 is an urgent case (6 frames, vRel −0.9 to −5.3 or aLeadK −1.05);
  - acting share unchanged (4.2 / 7.1 %); 0 frames lifting > 0.05 while the lead closes faster than 0.5 m/s or brakes harder than −1.0.
- Tests: `test_exp_lead_departure.py` now checks the gentle release rate (closing, braking, lost lead), the 3-frame release, the urgent instant drops, stop / toggle / e2e-brake instant drops and the MPC cap. 560 passed with `test_longitudinal_planner.py`.

### 136f. Route 11c8fa231c0499ed|00000293--9d152a3cdc (owner: drove in Experimental Mode throughout): the smoothed release (136e) runs on the road. Log decode and replay only; nothing changed.

- Build 6b0242f4 (contains a5c342ba, assist code unchanged since); `ExpLeadDepartureAssist` = 1. Radar alpha long; 26.2 engaged min, 24.8 in Experimental Mode (95 %); lead present 66 % of it, 84 % radar.
- Assist acted 62 s (4.1 % of exp), 40 episodes, lift p50 0.11, max 0.41. The logged aTarget − min(e2e, MPC) matches the replay within 0.02 on 97 % of acting frames.
- Release: the largest logged one-frame drop during a release is 0.31. Only 2 drops exceed 0.16, and both are urgent cases (lead closing > 0.5 m/s or braking < −1.0). 0 frames lifting while the lead closes/brakes past those limits; 0 frames lifting while e2e < −0.15.
- 27 brake onsets below −1.5 in exp. 26 have assist ≤ 0.02 in the 5 s before; each has a closing radar/vision lead or, at 19:36, MPC braking with no lead. The one exception is 34:02.5 (−1.6 within 2 s): the assist lifted ≤ 0.22 behind a lead at 46 m / 32 mph, released by 34:01.6, then the lead braked at −1.9.
- What the assist does not cover — the owner's gas presses on this drive:
  - 29:23 and 34:12: a radar lead pulling away at +4.8 / +5.9 m/s with MPC +0.6 / −0.15 → +0.3, while e2e itself braked at −0.45 / −0.83. By design the assist never lifts e2e braking below −0.15.
  - 12:06, 12:16, 14:05: no lead; e2e −0.16 to +0.18 against MPC +0.35 to +0.60. The assist needs a lead.
  - These are the item 136a `e2e_brake` / no-lead classes, not the class the assist targets.

### 136g. `ExpLeadDepartureAssist` baked in unconditionally; the TEST toggle is removed (owner request). Unit tests and static build checks only; not itself driven — no behavior changes for a car that already had the toggle on.

**Why.** Four separate logged/replayed drives (136c–136f, 96.9 replay-minutes plus routes 278/280/283/293 on the road) showed the assist behaving exactly as designed with the toggle on: logged `aTarget` matched the open-loop replay within 0.02 on 95–97 % of acting frames, 0 frames lifted while a lead closed faster than 0.5 m/s or braked harder than −1.0 m/s², 0 frames lifted while e2e itself was braking below −0.15, and no hard brake in the 5–8 s window after an episode was attributable to the assist — each was an independent lead event or a model braking decision the assist does not touch. 136d's one-frame release steps (up to 0.50 m/s²) were the only defect found, and 136e/136f closed it (max release step fell to 0.31–0.32, and every remaining step > 0.16 is one of the intentional urgent instant-drop cases). With no fault found across four drives and a defined defect already fixed and re-verified, the TEST/default-off gate was no longer buying anything but an extra param a driver had to know to flip. Removing it collapses the assist to the same "on in Experimental Mode" behavior every driver who had already opted in was getting.

**What did not change.** Every gate from 136b is still in force: `get_exp_lead_departure_weight` still requires a lead (radar, or vision with modelProb ≥ 0.5) at or beyond the follow distance and pulling away, ≥ 4.5 m/s, no planned stop; `update_exp_lead_departure` still runs only on the tinygrad-model branch of the e2e/MPC arbitration, in Experimental Mode; the lift still never exceeds the MPC target, never lowers the e2e target, and never touches e2e braking below −0.15; the smoothed release (136e) is unchanged. The only thing removed is the boolean gate that let a driver turn the whole rule off.

**What is explicitly not in scope.** 136f identified two classes of gas presses the assist still does not cover: e2e braking behind a departing lead (the assist never touches e2e braking by design), and no-lead cases where the model itself is slow. Extending the assist to either would mean overriding the model's own braking decision, which risks masking something the radar cannot see — that is a separate, harder change and was not requested here.

**Code (`selfdrive/controls/lib/longitudinal_planner.py`).** `update_exp_lead_departure` no longer takes a `starpilot_toggles` argument or gates on it; it always computes the lift (subject to the gates above) unless `hold_experimental`. The call site drops the now-unused argument. The constant-block comment above `EXP_LEAD_DEPARTURE_MIN_SPEED` documents the full 136b–136g history so the next person touching these constants can see what each one is for and what evidence set it.

**Removed.** The `ExpLeadDepartureAssist` key: from `common/params_keys.h`; the `toggle.exp_lead_departure_assist` load in `starpilot/common/starpilot_variables.py`; the "Follow Departing Leads (Experimental)" row in `selfdrive/ui/layouts/settings/starpilot/longitudinal.py`; the matching entry in `starpilot/common/assets/device_settings_layout.json`. `tools/longitudinal/exp_lead_departure_replay.py` and `selfdrive/controls/tests/test_exp_lead_departure.py` updated for the new function signature; the toggle-specific tests (`test_toggle_off_changes_nothing`, the `toggle=False` case in the stop/brake instant-drop test) removed since there is no longer a toggle to test.

**Params artifacts.** `common/params_pyx.so` and `common/libcommon.a` rebuilt natively on this aarch64 host with the pinned toolchain (clang 18.1.3, system Python 3.12.3, Cython 3.1.4, `SP_FORCE_TICI=1`, sconsign cleared first): keys 855 → 854 against the pre-change blob, the only removal `ExpLeadDepartureAssist`; `params_pyx.cpp` byte-identical apart from the build-path comment; a remaining key (`BoschARadar`) still put/get/removes cleanly, and reading the removed key now raises `UnknownKeyName` as expected.

**Tests.** `test_exp_lead_departure.py` (24, was 18 pre-136e) and `test_longitudinal_planner.py` together: 566 passed, same count as 136e/136f since no test logic changed beyond the signature and the toggle-specific cases removed.

## 141. Galaxy Plots rebuilt: recorded drives with a lateral/longitudinal analysis. Unit tests and a headless render against a synthetic drive only; not used on a car.

**What changed.** The Plots page (classic `/plots` and mobile `#/plots`) no longer grades a 30 s window with client-side "Great/Good/Fair/Poor" scores. A backend module `starpilot/system/the_galaxy/drive_plots.py` (commit 57cca03c) samples `controlsState`, `carControl`, `carState`, `longitudinalPlan` at ~20 Hz. Requested lateral is `desiredCurvature·v²`, measured is `curvature·v²`; requested longitudinal is `longitudinalPlan.aTarget`, measured is `aEgo`. Only engaged, non-override samples count (`latActive`/`longActive`, no steer/gas press).
- **Start/Stop recording** writes the whole drive to `<galaxy_dir>/drive_plots/<id>/` and runs until Stop, or 30 s after the car goes offroad. An unfinished session found later is finalized as interrupted.
- **Analysis on stop**: tracking error (RMS, 95th percentile) after lag alignment, response lag, curve/overall gain, straight-road pull (L/R), oscillation ratio, brake/accel bias, jerk p95, hard brakes, overrides, disengagements. It gives numbers plus short heuristic notes; there are no letter grades.
- **Drive detail**: whole-drive overview charts (not-engaged shaded), click to open a full-resolution 60 s window, CSV download, delete. The live view shows the last 30 s with the same analysis from the server.
- Frontends share `assets/components/tools/drive_plots_shared.mjs` (chart geometry, live buffer, formatting). Classic uses fixed SVG elements, because arrow-core puts nested templates inside `<svg>` in the XHTML namespace. Each changing block renders under a revision root, because arrow reuses same-string templates.

**Evidence.** `test_drive_plots.py` passes 18 tests: a planted lag, gain, bias and oscillation are recovered, disengaged time is excluded, and recorder/auto-stop/endpoints round-trip. It includes a fix for numpy scalars being written to CSV as `np.float64(...)`. `test_ui_vue_frontend.py` and `test_frontend_module_graph.py` pass. I rendered both pages in headless Chromium against the real Flask app with a synthetic 14-minute drive: live charts, recording, stop, drive detail, zoom and delete-confirm all rendered. The analysis recovered the planted 0.9 lateral gain, 0.3 s lag, wobble and left pull.

**Not verified.** No car, no real route. The heuristic thresholds in the notes (e.g. "oscillation" above ratio 1.5) are guesses and are unvalidated against real drives. The sampler's CPU cost on the device is unmeasured.

## 141a. Galaxy Plots audited on desktop and phone: swallowed taps, misaligned axes and an out-of-view detail fixed; plain-language findings, speed bands, steering-limit time and the tune snapshot added. Headless render and unit tests only; not used on a car.

**Bugs fixed.** (1) The classic page re-rendered every block on each 500 ms poll, so a tap that spanned a re-render landed on a detached button. Buttons now live in blocks that read only slow-changing state; the poll-fed text and charts render in nested slots (`inline()` in `plots.js`). Verified headless: all five buttons stay attached across polls, charts keep updating, Pause works. (2) Classic x-axis labels were laid out edge-to-edge instead of under their grid lines; both pages now overlay HTML labels at the tick positions, with y labels on the chart. (3) Mobile y labels were positioned against the SVG plus the tick row, drifting ~16 px at the bottom. (4) Tapping a saved drive at the bottom opened the detail at the top, out of view: the list now sits above the detail (5 most recent, "Show all"), and the page scrolls to the detail and to the zoom. (5) Stopping a recording that captured nothing saved an empty drive; it is now discarded and the page says so. (6) Speed was in m/s; it now follows `IsMetric` (mph / km/h). The live route returns `isMetric`.

**Analysis.** Findings are written for a driver: each note says what happened, whether you would feel it, and what to try; a "What stands out" list (max 4) tops the drive; a collapsible reading guide explains each number; the technical values stay in the key grid. New per-drive facts: curve response and error per speed band (under 30 / 30-50 / 50-70 / 70+ mph), fraction of curve time the steering was saturated (new `lat_sat` column from `lateralControlState.*.saturated`), and the tune snapshot that was already recorded (`meta.tune`, controller type, openpilot longitudinal) is now shown. `read_rows` maps by header, so older recordings without `lat_sat` still analyze.

**Evidence.** `test_drive_plots.py` 22 tests (bands recover a planted 0.75 gain above 50 mph, saturation fraction, header-tolerant read, empty discard); frontend suites pass (69 total). Both pages rendered in headless Chromium against the real Flask app with a synthetic drive: takeaways, band tables, tune list, zoom and axis alignment checked visually on 1400 px and 412 px viewports.

**Not verified.** Still no car. The swallowed-tap fix is verified by node identity across polls, not by a human tap. Band edges and the 5 % saturation threshold are guesses. `ruff` reports the same implicit-string-concatenation and `time.time` classes as the committed version; not changed.

## 141b. Galaxy Plots follow the new lateral controllers and radar work: wheel-angle scoring, tight low-speed turns, a "Moments to check" list with the car ahead, and a tune snapshot that knows which controller drove (owner, 2026-09-28). Unit tests and a headless render against a synthetic drive only; not used on a car.

**Why.** Since 141a the Civic defaults to LatControlClarityEps (STATUS 188), the NRDR PID gains are set per LowSpeed / Standard / Highway band, and the radar work is judged on hard brakes and phantom braking. The page still scored curves on the vehicle-model lateral acceleration, used 30/50/70 mph bands, and advised LatP/LatI changes to a controller that does not read them.

**What changed.**
- New recorded columns: requested and measured wheel angle (`ang_des`, `ang_act`, `ang_ok`) and the car ahead (`lead_d`, `lead_v`, `lead_src` = none / radar / camera only). Older recordings still analyze; the new metrics are left out.
- Curve response is measured on wheel angle, so a wrong steer ratio no longer biases it. Tight turns (wheel past 45 degrees under 25 mph) get their own table in degrees: off-by, past the request (overshoot or late unwind), behind, and time at limit. A wheel-wobble table covers near-straight road.
- Speed bands are now Low speed (under 25 mph), Standard (25-50) and Highway (50+), matching the tuning sliders.
- "Moments to check" lists hard brakes, gas presses while openpilot braked, steering takeovers and tight turns that went 10 degrees or more past the request. Each moment gives the clock time, speed, and the car ahead with its distance, speed and source. Tapping one opens the charts there.
- The zoom and live views add a steering-wheel-angle chart and a car-ahead distance chart. The distance line breaks where no car was tracked.
- The drive meta records which steering controller drove (James's controller, NRDR PID, or the CarParams tuning type) and snapshots the lateral, NRDR, longitudinal and radar params (BlotV3, BoschARadar, NrdrHondaEcuMatchedLong). Under James's controller the Lat*Scale and Honda PID scale values are marked "not used", advice does not suggest slider changes, and the P-term chart notes that the logged P is before its speed-band scale and output filter.

**Evidence.** `test_drive_plots.py` 33 tests (angle-based curve response, planted tight turns and wobble, each moment kind, controller-specific advice, old-column tolerance); with the frontend suites 79 pass. Both pages rendered in headless Chromium against the Flask app with a synthetic drive at 1400 px and 412 px: moments, turn tables, grouped tune, wheel-angle and car-ahead charts checked visually; no page errors from Plots.

**Not verified.** No real drive has been recorded with the new columns. The 45 degree / 25 mph tight-turn cut, the 10 degree "went past" cut, and the 2.5 m/s² hard-brake threshold are guesses to be checked against the first real recordings. The controller label mirrors the controlsd selection rule by reading CarParamsPersistent and NrdrLatEpsFirmwareFF; it is not read from the running controller.

## 141c. Galaxy Plots records every drive by itself and copies its moments into the drive's rlog, with the signals the long and lat agents asked for, plus an offline tool that rebuilds the same analysis from any rlog (owner, 2026-09-28). Unit tests, a headless render against a synthetic drive, and a replay of one real route; not yet recorded on a car.

**Why.** Recording only ran when someone pressed Start, and what it found stayed in the Galaxy session folder, where the agents working on long and lat could not see it. The owner asked for recording to start with the drive, for the results to land in the rlogs, and for the plots to carry what those agents need. James, Bob, Kevin and John were asked what they wanted, and all four replied.

**What changed.**
- **Auto-record.** A watcher starts when the Galaxy starts. It begins recording when the car goes onroad and stops 30 s after offroad.
  - The setting lives in `drive_plots/settings.json`, not a param, because the device runs a prebuilt tree and a new params key would need a rebuild. It defaults to `{"auto_record": true, "publish_to_log": true}`.
  - Both Plots pages have a "Record every drive" checkbox (`/api/plots/settings`).
  - Pressing Stop skips the rest of that drive; the next drive records again.
  - Only automatic sessions are pruned: the newest 20 are kept, up to 1 GB. Manual recordings are never pruned.
- **Copy in the rlog.** The recording publishes JSON on `customReservedRawData0`. It is already in the log list and nothing else sends on it; the testing-ground worker uses customReserved9.
  - The schema is `drivePlots/1`, with `type` start / moment / takeover / summary / end and `mono_ns`.
  - `start` carries the drive meta: controller, tune snapshot, git and lateral delay.
  - Moments are published as they finish. Every 20 s the last 60 s are scanned, and a moment is sent once it is 8 s old. Takeovers wait 7 s after release so the recovery is measured.
  - `summary` goes out every 300 s, and `end` goes out at stop.
  - loggerd only runs onroad, so nothing published after offroad reaches the rlog. The final analysis stays in the Galaxy session.
- **New columns** (NaN when that service never arrived, so older recordings and missing services are not read as zeros):
  - Lateral: `steer_tq`, `steer_tq_eps`, `steer_rate`, `blinker`, `tq_req`, `tq_out`, `lat_out`, `ang_err`, `pid_active`, `ff_active`, `ff_w`, `ff`, `lane_off` (+ = car left of centre), `lane_w`, `lane_prob`.
  - Timing: `cs_age_ms` (carState age at the plan).
  - Longitudinal: `a_cmd`, `should_stop`, `fcw`, `has_lead`, `exp_mode`, `t_follow`, `tracking_lead`, `standstill`.
  - Lead: `lead_id`, `lead_y`, `lead_vrel`, `lead_a`, `lead_prob`, `lead_meas`, `lead_vrr`, `lead2_on/d/v/id`.
  - Model lead: `mlead_p/x/y/v/a`.
  - The Galaxy now subscribes to carOutput, modelV2, selfdriveState, starpilotPlan and starpilotLateralState at 20 Hz on every drive. That is extra CPU in the Galaxy process, and it has not been measured on the device.
- **New moments** (`drive_plots_agents.py`): firm brake, brake with no car ahead, camera-only brake, driver brake override, car appeared close, car vanished close, and track-ID swap.
  - Steering takeovers are measured as episodes: hold time, push direction, blinker, wheel swing after release, and time back on plan and back within 2 degrees.
  - Recovery numbers are left empty when lateral was not active after the release.
  - The drive analysis adds a takeover breakdown and the median lane position on straights per speed band. Under 8 cm reads "centred".
- **`tools/drive_plots/rlog_report.py ROUTE_DIR_OR_RLOG... --out DIR [--rate plan|carstate] [--no-detect]`** rebuilds the same rows and analysis from raw rlogs. It writes `report.json` and `samples.csv`.
  - Times are labelled `route_s`, `seg` and `seg_mmss`. Each segment starts at its first carState, because initData repeats in every segment.
  - The report includes:
    - the tune snapshot (every Nrdr*/HondaOverride* key in `params_keys.h`; "missing" when not logged)
    - the controller, detected by `lat_score`
    - controls gaps from `cs_age_ms`
    - lateral delay and liveTorqueParameters
    - the car's own drivePlots messages, when present

**Evidence.**
- 86 tests pass across `test_drive_plots.py`, the frontend suites and `tools/drive_plots/tests`. They cover:
  - the agent columns and NaN handling
  - the takeover episode
  - auto start and the manual-stop skip
  - the rlog messages through a fake publisher
  - pruning
  - a synthetic rlog through the offline tool
- Both pages were rendered in headless Chromium at 1400 px and 412 px. The checkbox, takeover moments, takeover rows and lane-position row were checked as text; there were no Plots page errors.
- Replay: `rlog_report.py` on 3 segments of one real ClarityEps route gave 3529 rows, detected clarity_eps, and found 32 moments and 20 takeovers in about 5 s. That replay found and fixed three bugs:
  - "car appeared close" fired at standstill
  - takeovers while disengaged got a recovery overshoot
  - segment labels were wrong

**Not verified.**
- No drive has been recorded on the device with this code, and no rlog yet contains a drivePlots message.
- A takeover held longer than about 50 s is not published live; the offline tool still finds it.
- The Galaxy CPU cost of the extra subscriptions is unmeasured.
- All moment thresholds are first guesses, to be checked against real recordings.

## 141d. Plots moments after the agents' first read of 141c (2026-09-28): takeovers say which controller drove and where the car sat in the lane, and the lead moments stop firing on next-lane blinks and radar/camera handoffs. Unit tests and a replay of one real route only.

- **Takeovers** (Driver override, VFN Shadow controller):
  - Every episode carries `lateral_controller` and `git_commit`, because takeovers under ClarityEps and the PID are not comparable. The rlog copy and rlog_report carry them too.
  - Each episode adds `lane_press_m`, `lane_release_m` and `lane_press_3s_m`: position from the centre of the lane at the press (+ = left), carried across a lane change. This is the real-grab counterpart of the design-C sim's "+3 s from press" residual. It is limited road evidence and never scored pass/fail, since a real grab has no no-push twin.
- **Lead moments** (Radar Work, from route 28f):
  - `track_id_swap` is now radar to radar only: both IDs >= 0, lead kept, distance within 3 m. Handoffs are `radar_acquired` / `radar_lost`. They stay in the analysis and the rlog but are not listed on the page.
  - `lead_appeared_close` / `lead_vanished_close` now need the lead within 2 m laterally and under 30 / 40 m, and the new state must hold 0.5 s.
  - An appear and a vanish within 1 s are one `lead_flicker`.
  - A distance drop over 8 m while the lead is 30 m or farther is `lead_jump`.
- **Experimental mode:** the moment field is now `experimental_active`. `selfdriveState.experimentalMode` is switched by Conditional Experimental, so it is not the driver's setting. ConditionalExperimental and ConditionalChill join ExperimentalMode in the tune snapshot.
- **Replay** of the same 3 segments of one ClarityEps route:
  - Before: 5 swaps, 7 appeared, 4 vanished.
  - After: 0 swaps (5 radar_lost, 4 radar_acquired), 2 appeared, 1 lead_jump, 0 vanished.
  - All 20 takeovers carry clarity_eps, the commit and the three lane positions.
  - Its snapshot shows ConditionalExperimental = 1.
- 87 tests pass, including a scenario that exercises every lead gate.
- **Not verified:** the new 2 m / 0.5 s / 1 s gates are Bob's numbers from one route and have not been checked against a second.

## 141e. Plots checked against the rlogs and the agents' lat_score (owner, 2026-09-28): the tight-turn table now also gives lat_score's figure, wobble leaves out lane changes, and `tools/drive_plots/mirror_check.py` checks all four layers. Unit tests and a replay of one real route only.

- **Mirror check** (`tools/drive_plots/mirror_check.py <route>`), four checks on the same logs:
  - **columns:** every `build_row` column against the rlog field it names, read on its own at each longitudinalPlan.
  - **frames:** Plots' angle, desired angle, grab, pidState.active and lane-change state against `lat_pid_sim.extract_logs` (the frames lat_score scores). Rows are lined up by message order, not logMonoTime, because an rlog's logMonoTime is not strictly ordered (a controlsState can be stamped after the plan that follows it in the file). Matching by time put 3% of rows one frame off.
  - **lat_score:** `score_arrays` turn error / past / behind and wobble beside Plots.
  - **car:** the drivePlots messages in the rlog beside the same moments and takeovers found offline.
- **Two gaps it found, both fixed:**
  - **Tight turns read about 10x lower than lat_score** (under 12 mph: 2.7 vs 26.6 deg). The cause is that Plots leaves out the second after the driver lets go (James asked for that), and those frames average about 30 deg off.
    - Each turn bin now also carries `scorecard`, which uses lat_score's mask: pidState.active (latActive before that column), hands off, over 4 m/s.
    - The page shows it under the table as "Counting the second after you let go, as the agents' scorecard does: ...", and the notes carry it too. Plots' own figure is unchanged.
  - **Wobble 8-12 m/s counted lane changes** (0.36 vs lat_score 0.19). A new column, `lane_change` (modelV2.meta.laneChangeState), lets the straight mask drop them as lat_score does. Older recordings without the column are scored as before.
- **Replay** of 3 segments of one ClarityEps route:
  - **columns:** all 69 columns match the rlog fields on 3529 rows.
  - **frames:** desired angle and pidState.active agree on 100% of rows; angle, grab and lane change on 99.8%+. The rest are rows holding a carState or modelV2 one frame newer than lat_pid_sim's frame.
  - **lat_score vs Plots:**

    | Metric | lat_score | Plots |
    |---|---|---|
    | turn error, under 12 mph | 26.6 | 26.4 |
    | turn error, 12-25 mph | 18.3 | 18.7 |
    | wobble 5-8 m/s | 0.524 | 0.54 |
    | wobble 8-12 m/s | 0.194 | 0.21 |
    | wobble 12-20 m/s | 0.189 | 0.16 |

    All are within the printed tolerances: 1.5 deg / 10% for turns, 0.03 deg / 15% for wobble.
  - **car:** this route predates the car's drivePlots messages, so the car check is untested on a real drive.
- 89 tests pass. Two are new synthetic-drive tests: one with out-of-order stamps, a lane change, a tight turn with a grab and a car message, and one negative control where a column reads the wrong field.
- **Not verified:**
  - The car check on a drive recorded by the car.
  - Any route other than this one.

## 141f. Plots fixes from James's read of route 293 with rlog_report (2026-09-28): lane drift needs both lines through the window, turns under a light hold are left out and tagged, and overshoots carry route times. Unit tests and a replay of one real route only.

- **Takeover lane numbers:**
  - drift_1s / 3s / 6s are None unless both lane lines stay above 0.5 from the press to the end of that window. `lanes_ok` is the same test from press to release.
  - `lane_release_m` and `lane_press_3s_m` are gated the same way. New `lane_prob_min` is the lowest from press to release + 6 s.
  - At 1202.7 the old release-only check passed (0.72 at release) while the right line sat at 0.02-0.18 in the hold, and the reported 1.06 m was the line jumping.
- **Holds:**
  - The "driver's hands plus 1 s after" mask (`agents.after_release`, new `agents.held`) now counts the takeover episodes as well as raw steeringPressed. steeringPressed flickers off in a light hold the torque still shows.
  - This affects Plots' own turn and wobble figures, the tight-turns list and the lane-straight numbers. The `scorecard` figures stay on lat_score's steeringPressed-only mask.
  - Each tight turn carries `held_frac`: the share of -10 s .. +5 s around turn-in that the driver was holding.
- **Overshoots** carry mono_s, so rlog_report adds route_s / seg / seg_mmss and drops the old `t`. That `t` counted from the first sample, not the route start, and was easy to misread against samples.csv's monotonic `t`.
- **Replay of route 293** (41 segments):
  - 1202.7 has drift None and lane_prob_min 0.02.
  - The 234.0 turn is gone. 1166 is tagged held_frac 0.52, and the tight-turn list is down to 8.
  - One overshoot remains, at route_s 1742.8.
  - Only 1 of 80 takeovers keeps its drift, against 10 that passed at release before. The median lowest lane probability in a takeover on this route is 0.00, so on this road drift is mostly not measurable.
- 91 tests pass.
- **Lane rule loosened at James's request** (same day): a window counts when both lines are above 0.5 for 90% of its frames and neither stays under 0.3 longer than 0.5 s in a row. One-frame dropouts at merges and gores no longer void it. New `lane_ok_frac`.
  - Route 293 still keeps only 3 drift_3s of 80 (lanes_ok 4). The median lane_ok_frac is 0.04, and 1202.7 is still rejected at 0.45.
  - The lines are faint, not flickering: both lines are above 0.5 on 3% of the frames where the wheel is held (median 0.01), against 64% engaged above 15 m/s. Takeovers here happen at low speed and in turns, where the model does not see both lines.
  - Any both-lines rule keeps few takeovers on such roads. A looser signal (the stronger line alone) would need a new column, and is James's call.
  - James chose to keep this rule: None is the honest answer on such takeovers. A one-line gate would bring back the lane-width guesses.
- **Added** (James):
  - `lane_prob_l` / `lane_prob_r` columns beside the min, to see which side drops out. The mirror check confirms all 71 columns against the rlog.
  - Each takeover drift median now has `drift_Ns_measurable` ("n / total", blinker takeovers left out) beside it. On route 293: 3 / 49 at 1 s and 3 s, 2 / 49 at 6 s.
  - The median now uses every measurable takeover without a blinker; drift is gated per window itself.
- **Not verified:** the rule on a highway route, where takeovers should see the lines.

## 141g. Plots memory on the comma (2026-09-28): reading a finished drive no longer takes the_galaxy to 667 MB. Device reading (read-only) and local measurements; not yet re-measured on the device.

- **Seen on the device** (route 294 procLog, read-only ssh): while recording, the_galaxy went 78 → 121 MB and levelled off
  (the live buffer is 60 s, < 1 MB). At the stop it reached 229 MB (finalize), then 667 MB when Plots was opened,
  device memory 89 %, and it stayed near 510 MB: seven ~33 MB glibc arenas held freed memory.
- **Cause:** every zoom (`get_window`) and the finalize parsed the whole CSV as text plus Python float lists
  (~110 MB for 20 min). Taps at once stacked (8 at once: 730 MB peak, 315 MB held, local).
- **Fix:** `read_rows` streams into one array, and with a window keeps only that window's rows; one whole-session read
  at a time (`DrivePlots._heavy`); `malloc_trim` after each; the_galaxy caps glibc at 2 arenas in `main()`
  (`limit_malloc_arenas`, pure Python, no launch change). Local, same 20-min session: 8 zooms at once +8 MB peak,
  finalize +36 MB peak (was +112). Results are identical to the old reader (whole drive and windows; test).
- **Not verified:** the device numbers after an update. Check `/proc/<the_galaxy>/status` VmRSS/VmHWM after a drive
  and a few zooms.
- **2026-09-29 follow-up:**
  - Device on the fix (ffe96749), route 297, ~58 min, auto-record off: the_galaxy held at 96-109 MB (qlog procLog), device
    memory 78-82 %. There is still no device reading with a recording.
  - Local worst case, a 2-hour drive (the 20-min session tiled): finalize peaked at +250 MB, because `read_rows` grew its array by
    doubling. It now fills fixed 2048-row blocks and joins them one at a time: a clean 2 h read + analyze is +90 MB,
    72 MB of which is the rows themselves. 10 zooms at once on 2 h: +8 MB.
  - A stop in the background (by hand, or MAX_RECORDING_S mid-drive) now waits until IsOnroad is false before the
    whole-drive analysis, so it never runs while driving.
- **2026-09-29 zoom:** drag sideways across any whole-drive chart to zoom to that stretch (a tap still gives a minute).
  Buttons pan and zoom in/out, and ctrl + scroll or a trackpad pinch zooms around the pointer. The zoomed stretch is
  shaded on the whole-drive charts, and a drag inside a zoomed chart zooms further in. Spans are 4 s to 900 s, kept
  inside the drive, and the newest request wins. Charts use `touch-action: pan-y`, so an up/down swipe still scrolls the
  phone page. Each zoom is still one `/window` read under the `_heavy` lock (+8 MB for 10 at once, above).
  Evidence is static only: `tests/test_plots_zoom_browser.mjs` runs headless Chromium on both pages against a synthetic
  20-min drive, covering mouse drag, finger drag, vertical swipe, tap, buttons and the band. Not yet tried on a phone
  against the device.
- **2026-09-29 agent metrics** (Kevin, James, Bob and John asked; static and one-route replay evidence only):
  - 31 more columns (09d059dac): steering faults, desired/actual curvature, firmware-FF internals, liveParameters,
    liveDelay, planner source and caps, pitch, set speed, red light, gas learner, adjacent leads. RAM, local x86, a 2 h
    drive with every column filled: finalize peak 255 MB vs 188 MB before (+67 MB after parking); nothing added
    while driving (rows stream to disk). About 50 µs of CPU per row.
  - Per-takeover numbers for Kevin (fcfe0e868): release gap, takeback rate, t90, re-press, fault flicker, near-cut.
  - Moments (d7c014256, bcd56fd0d): Bob's exp_flipflop, false_red_light, atarget_step, close_lead_cap,
    radar_coast_near, vrel_disagree, radar_vs_model, overspeed_no_lead and gf_clip; James's fault_flicker,
    release_snap, hwy_inside_cut and hwy_wiggle. Bob then set vrel_disagree to > 3.0 m/s held > 1.0 s, moving only
    (f9511da9e): 8 on route 297 (0.96 h), was 263; `radar_vrel_gap` p50 0.74, p90 2.39 m/s. exp_flipflop carries
    standstill and long_active; bursts with long control off stay in the analysis but leave the drive's list
    (3afd48749): 10 of 25 listed on 297.
  - Kevin's live flags on each takeover (`flags`, published as it finishes): FLICKER, SNAPBACK, GAP (> 20° under
    10 mph), NEAR-CUT (1500-1800 held > 1 s). Route 297 replay: 20 of 91 takeovers flagged (6 / 10 / 5 / 0).
    `rlog_report` also writes `moment_windows.csv`, ±2 s of rows around each moment (offline only).
  - Bob's brake_overshoot (long active, aEgo more than 0.8 below a negative a_cmd held > 0.3 s) and
    unmeasured_lead_cap (radar lead with measuredRadar false while closeLeadBrakeCap < 0, held > 0.3 s); runs under
    1 s apart are one moment. Replay: 298 has 1 overshoot (its bookmark 1, -3.5 asked, -4.72 reached) and 6 caps (its
    bookmark 3 is the 121 m one); 297 has 2 and 4. 7 of the 10 caps start with vRel at -13.3 to -13.5 m/s.
  - Kevin's FIGHT flag: latActive, no steeringPressed, |steeringTorque| >= 600 against the sign of carControl's torque
    request, held > 1 s, then steeringPressed within 1 s. Adds fought_first_s / _tq_med / _err_deg to that takeover.
    A takeover whose run had no press after is marked held_against_request with the same fields and no flag (context:
    a hand on the wheel reads this way whenever openpilot applies torque); one row per takeover, no separate moment.
    Replay: FIGHT 11 on 297 and 5 on 298; held_against_request 9 and 4 takeovers, covering 13 and 5 runs (two
    takeovers hold two runs, three held runs sit in FIGHT takeovers). Peter's seg-12 left turn on 298 is a FIGHT and
    1 of 2 with the wheel past the plan toward the request.
  - `tools/drive_plots/sim_export.py` writes John's `lat_pid_sim.npz` per steered segment at the controls rate
    (~97 Hz on 297), t from each segment's first carState. Not yet read by his scorer.
  - sim_export's export.json also lists John's scoring windows and presses (`0d089047f`), plus every Nrdr* toggle in
    initData. **NrdrLatEpsFfAngleGate = 1 was written on the comma at 14:42 on 2026-09-29, after 298.** It is absent
    from 298's initData, so no result from 298 or 297 is credited to the gate. Check export.json `params` on the next drive.
    298 had 0 s engaged at 25+ m/s.

## 142. Step 2 toward a torque controller: comma's torque controller (2a) and StarPilot's (2b, NNFF off) against the NRDR PID in the closed-loop sim, with and without the firmware VGR map. Sim only; nothing on the car changed.

**What was added.**
- `selfdrive/controls/lib/latcontrol_torque_upstream.py`: comma's `LatControlTorque`, vendored verbatim from commaai/openpilot master `49bbba371c29c5612e69b8ea9f906e151410e8bc`. Three changes, each marked `# nrdr`: the `log` import, an optional `angle_to_linear` argument, and that hook applied to the measured angle before `VM.calc_curvature`. Nothing imports it outside the sim. In a real port the hook belongs in opendbc (the VehicleModel angle-to-curvature path, and paramsd later), not in a controller.
- `tools/lateral/lat_pid_sim.py`:
  - `Controller(kind=...)` accepts `pid | torque_upstream | torque_starpilot`.
  - The torque kinds use the logged CarParams with the tuning switched to torque. Defaults come from the STATUS 140 study: LAF 11.5, friction 0.025, lat_delay 0.2 s.
  - `vgr=1` feeds the firmware map (C020) into the measured curvature and sets sR 15.27 (the M1 pooled fit).
  - `friction_low` sets the friction used below 20 mph, blended into `friction` by 25 mph.
  - StarPilot's kind uses its Civic-modified B branch (ff scale, fixed 0.30 friction threshold, friction scale). Its internal ×1.2 LAF is divided out, so both torque kinds get the same car model. NNFF is a separate class that controlsd swaps in, so it is never built here.
  - A new `compare` subcommand and a delivered-command rate metric.
  - Every variant runs through the same `CarControllerSteer` stage (min steer speed, override torque scale, fade up/down).
- `tools/lateral/tests/test_lat_pid_sim_torque.py`: 8 tests. Both torque kinds, with and without VGR, close the loop on a synthetic step. The VGR target is the map applied to the linear angle. VGR without the firmware flag is refused. The testing-ground hooks are restored. The variant parser is covered.

**Sim result.**
- Routes: 263, 268, 271, 276, 277.
- Plant: plant_d5, with `HondaLateralPidKpScale=1.0` and `HondaLateralPidKiScale=1.0`.
- Figures are minute-weighted. Error and lag are measured against each controller's own unshaped target.

| band | variant | err rms (deg) | lag (s) | curve entry | straight rms | sign chg/s @0.15 | cmd rate rms /s |
|---|---|---|---|---|---|---|---|
| 25-50 | PID | 1.25 | 0.39 | 0.69 | 0.69 | 0.30 | 0.20 |
| 25-50 | PID + NrdrLatRateFF 0.5 | **1.13** | **0.31** | **0.73** | **0.61** | 0.30 | 0.21 |
| 25-50 | 2a | 1.63 | 0.54 | 0.59 | 1.01 | 0.31 | 0.11 |
| 25-50 | 2a + VGR | 1.59 | 0.54 | 0.60 | 1.00 | 0.32 | 0.11 |
| 25-50 | 2b | 1.31 | 0.39 | 0.68 | 0.86 | 0.33 | 0.12 |
| 25-50 | 2b + VGR | 1.27 | 0.39 | 0.69 | 0.85 | 0.33 | 0.13 |
| >50 | PID | 0.79 | 0.36 | - | 0.58 | 0.12 | 0.14 |
| >50 | PID + RFF | 0.76 | 0.35 | - | 0.55 | 0.12 | 0.16 |
| >50 | 2a + VGR | 0.80 | 0.51 | - | 0.65 | 0.25 | 0.09 |
| >50 | 2b + VGR | **0.73** | 0.38 | - | 0.60 | 0.24 | 0.09 |
| <25 | PID | 15.0 | 0.39 | 0.58 | 2.48 | 0.32 | 0.37 |
| <25 | PID + RFF | **13.4** | **0.30** | **0.71** | **1.97** | 0.35 | 1.05 |
| <25 | 2a + VGR | 16.9 | 0.47 | 0.48 | 3.97 | 0.34 | 0.42 |
| <25 | 2a + VGR + friction_low 0.08 | 16.3 | 0.45 | 0.55 | 3.55 | 0.40 | 0.45 |
| <25 | 2b + VGR | 14.4 | 0.37 | 0.66 | 2.81 | 0.46 | 0.53 |

- **2b (StarPilot, NNFF off) + VGR is level with the plain PID** on curves and error at every speed, with a smoother command. It is worse on straights: straight rms 0.85 vs 0.69, and twice the sign changes above 50 mph.
- **PID + rate FF is still the best tracker** in the sim.
- **2a (comma stock) lags** by about 0.15 s more.
- **VGR helps both torque kinds** at every speed, most below 25 mph.
- lat_delay 0.1 / 0.3 s (routes 271 and 276 only): 2b does not care. 2a is best at 0.1 s: 25-50 err 1.48, lag 0.45.

**Limits.**
- The plant was fitted on PID-driven data.
- The torque tunes are the study's fixed values: no torqued live learning, no liveDelay.
- Desired curvature is exogenous, so lane position is not scored.
- The "own target" differs between the kinematic models only above about 15 deg of wheel angle, which in practice means below 25 mph.

**Not verified.** No road drive of any torque variant. Road use would need a param (for example `ForceTorqueController`) plumbed to the new controller, which is an artifact rebuild and needs owner approval.

## 143. Routes 00000278 / 0000027a (owner report: low-speed stutter with `NrdrLatRateFF`, slow unwind at 27a 12:34). Log decode, open-loop replay and sim only; no controller or setting change.

Routes `11c8fa231c0499ed/00000278--8f101d683e` (24 segs) and `0000027a--4eae257c95` (15 segs), both device build `a0940b9f`. Tool: `tools/lateral/lat_route_check.py` (new; `chatter`, `unwind`, `rateff`).

**Settings.** 278 starts with `NrdrLatRateFF` 0.5, `HondaOverrideFadeDownSecs` 0.2; 27a has rate FF 0 and fade-down 0. Both: P/I/F low 100/50/50, standard 105/75/100, highway 105/75/100, LPF tau 0.09/0.1/0.1, firmware VGR on, fade-up 1.0 s, override torque scale 0. Against 277 (`28d4eda8`) the only lateral code in the build is the trim slew (137) and kp slew (139).

**When rate FF was live in 278** (`rateff`, open-loop replay against the logged output, 30 s windows): 0.5 matches from 0:00 to 17:30 (|sim−log| median 1e-4–4e-3 against 2e-3–0.17 at 0); 0 matches from 18:00 on. So it was switched off at about 17:45.

**Stutter: caused by the rate feedforward below 25 mph. `[CONFIRMED, log decode + replay]`**
- Chatter, engaged hands-off (`chatter`):

  | window | 2–10 mph d(torque) rms / reversals / wheel jitter | 10–25 mph |
  |---|---|---|
  | 278 0:00–2:00, rate FF 0.5 | 3.71 %/frame / 19.6 /s / 1.07° | 2.24 / 18.0 / 0.61 |
  | 278 18:00–end, rate FF off | 1.09 / 5.4 / 0.81 | 0.96 / 6.1 / 0.62 |
  | 27a, off | 0.86 / 4.6 / 0.63 | 0.39 / 3.1 / 0.33 |
  | 270, 271, 276, 277 (never on) | 0.56–0.95 / 2.7–5.2 | 0.46–0.62 / 2.7–6.9 |

- The FF term itself (replay on − off), 278 first 2 min: below 10 mph median |FF| 0.134 of full torque, p95 0.57, frame-to-frame rms 3.4 % against 1.05 % for the whole rest of the PID. 10–25 mph: median 0.045, p95 0.39. Above 25 mph it is small (frame-to-frame 0.05–0.22 %), which is why the sim (133) and the highway drive did not show it.
- Mechanism: the term is `k × target slew / 100 °/s`, not speed-scaled. At low speed the model's curvature, as a wheel angle, moves hundreds of deg/s and jitters frame to frame; the 0.09 s LPF does not remove enough. Item 139 predicted the low-speed torque noise (0.10–0.34 → 0.33–0.49 %) on the linear plant but could not show the feel; on the car it is 3–4× the off level.
- **Recommendation: keep `NrdrLatRateFF` 0.** If it is revisited, it needs a speed gate (off below ~25 mph) and its own filtered derivative (139). Not done.

**Unwind: no route-level regression; the 27a 12:34 event is a chain. `[INFERRED from log decode]`**
- `unwind` over engaged low-speed turns (peak ≥ 45°, < 5 % pressed; small n): unwind lag 27a 0.19 s (n = 4) against 0.14–0.28 s on 262–278. Unwind error scales with unwind rate (27a 87 °/s → 16.6°; 262 106 °/s → 14.5°; 271 97 °/s → 15.3°). Turn-in lags more than unwind on every route (0.33–0.60 s).
- 27a 12:34 (t ≈ 753–760 s, 13–15 mph, left turn to −176°):
  1. The desired held its peak until about 757.3 s. The driver was already pushing the unwind from 757.1 (driver torque 1000–2100); the controller was pulling back into the turn (P −0.47 at 757.4).
  2. The push tripped the override twice (757.2, 757.7): delivered torque went to ≈0 and faded back over 1 s, and the integrator froze (steer-limited) from 757.2 to 758.9 **at −0.19, the into-turn value**.
  3. During the real unwind (758.4–760.0, desired −111° → −8°, ~70 °/s) the wheel trailed by 13–20°. P gave +0.3 to +0.43; the frozen, then slowly bleeding I (−0.19 → −0.08) cancelled 35–45 % of it.
- Nothing here changed between 277 and 27a: the low-band gains, fade and freeze are the same, and 27a had no rate FF.
- Sim (plant_d5, no driver, 27a and 26b), unwind error / lag: `LatIScaleLowSpeed` 50 → 25 → 0 gives 4.2 → 3.4 → 2.1° on 27a and 0.26 → 0.20 → 0.14 s on 26b, turn-in unchanged. Rate FF 0.5 cuts unwind lag to 0.04 s in the same sim, but the sim cannot show the chatter above. Sim only; a lower low-speed I is the thing to try if unwind stays a complaint. No setting changed.

**Not covered.** The model's late unwind request (step 1) is not a controller issue and is not scored. Episode counts are small because turns with driver presses are excluded. The sim plant is linear, with no driver and no curb.

### 143a. Owner follow-up: which band trims to change, and the override threshold. Sim only; nothing changed on the car.

Sim with plant_d5 on 27a / 26b / 271, low band (< 25 mph), the logged settings as the base:
- `LatPScaleLowSpeed` 100 → 115 → 130: error rms 15.90/13.84/11.11 → 15.48/13.43/10.69 → 15.17/13.14/10.37°. Lag 0.36/0.35/0.23 → 0.34/0.32/0.21 → 0.32/0.30/0.20 s. Unwind error (`lat_route_check` episodes) 4.2/0.5/0.9 → 3.4/0.2/0.5 → 2.5/0.0/0.2°. Mid-corner ratio up slightly. Sign changes at 0.15° 0.37/0.23/0.36 → 0.40/0.23/0.37 → 0.42/0.25/0.39.
- `LatIScaleLowSpeed` 50 → 25 → 0: unwind is faster, but the mid-corner ratio falls (26b 0.906 → 0.880 → 0.858; 271 0.931 → 0.892 → 0.844), and low speed already under-steers mid-corner (132). Error rms is flat. Rejected in favour of P.
- **Given to the owner: `LatPScaleLowSpeed` 115. Everything else unchanged** (low I 50 / F 50; standard and highway 105 / 75 / 100; `NrdrLatRateFF` 0). 130 is the next step if unwind is still slow and low-speed weave has not risen.
- **`NrdrDriverOverrideThreshold`: keep 2000.** Lowering it adds threshold grazes, which are already 62–71 % of presses and cut the torque (132). At 27a 12:34 the cut had already fired at 1998–2105.

### 143b. Owner follow-up: override fade-up/down and the target LPF taus. Sim only; nothing changed on the car.

Sim plant_d5 on 27a / 26b / 271, base = the logged settings + `LatPScaleLowSpeed` 115. The sim has no driver: logged press frames are re-synced to the log, so fade settings are scored only on how fast tracking recovers after a press, not on how the returning torque feels under a hand that is still on the wheel.

| setting | low < 25 mph error rms ° (27a / 26b / 271) | lag s | 25–50 mph error rms |
|---|---|---|---|
| fade-up 1.0 (as driven) | 15.48 / 13.43 / 10.69 | 0.34 / 0.32 / 0.21 | 0.85 / 1.21 / 0.91 |
| fade-up 0.5 | 13.79 / 12.32 / 9.76 | 0.30 / 0.29 / 0.20 | 0.84 / 1.15 / 0.85 |
| fade-up 0.25 | 12.71 / 11.66 / 9.32 | 0.28 / 0.27 / 0.20 | 0.84 / 1.11 / 0.82 |
| fade-down 0 → 0.2 | 15.48 → 14.57 / 13.43 → 12.01 / 10.69 → 9.66 | 0.34 → 0.32 / 0.32 → 0.29 / 0.21 → 0.20 | ≈ / 1.16 / 0.82 |

Sign changes are unchanged by either setting.
- **Given to the owner: `HondaOverrideFadeUpSecs` 0.5 and `HondaOverrideFadeDownSecs` 0.2.**
  - Fade-up 0.25 scores best, but it returns torque 4× faster under a hand that may still be on the wheel. The sim cannot see that, and 132 kept 1 s for real fights.
  - Fade-down 0.2 was already in use on 278 before the rate FF was switched off. With the rate FF off afterwards, no stutter was attributed to it.
- **LPF tau: keep 0.09 / 0.1 / 0.1.** With the rate FF off, the taus barely matter in the sim.
  - Low 0.06 vs 0.09 vs 0.12: 15.96 vs 15.48 vs 15.01 on 27a, and within 2 % on the other two routes.
  - Standard and highway 0.07 to 0.13: within 0.02°.
  - A longer tau also delays the request itself, which these numbers, scored against the shaped target, do not charge. 133 showed tau 0 at low speed was worse.

### 143c. Is the frozen-integrator problem fixed? Partly. JamesL787/openpilot PR #8 checked against this tree. Log decode and static read only.

PR #8 (`armin/lateral-fixes`, open, unmerged) has three lateral pieces: (1) a relative freeze rule, (2) the Clarity left/right split knobs, (3) a PID reset on disengage.
- **(1) Freeze rule: the main cause is fixed, but by a different route.** James's `02163421` and `6fe70e09` (both in HEAD) moved the torque LPF off the output and onto the target. So on the straight and at speed the flag no longer trips: frozen 0.8–2.4 % of engaged frames above 25 mph on 271/278/27a, against PR #8's 81–87 %.
  - **The override fade was left in the carcontroller, and it still freezes the integrator.** Below 25 mph (v > 2 m/s) the integrator is frozen 36 % of frames on 27a, 46 % on 278 and 27 % on 271.
  - Pressed frames are 9–16 %. Commanded ≠ delivered while not pressed is 17–28 %, and 60–70 % of those frames fall within fade-up + 0.1 s after a press.
  - That is the 27a 12:34 mechanism (143): I held at the into-turn −0.19 through the fade. PR #8's relative rule would still freeze early fade (its own note: "early override fade still ~100 %"), so porting it would not fix this case either.
- **(3) Stale I across a disengage: not in this tree.** `LatControlPID` has no `reset()` override, and its inactive branch does not touch `pid.i`. The first active frame after re-engaging carries the old integrator:
  - 27a: 13 re-engagements, median |i| 0.056, max 0.078.
  - 278: 28, median 0.042, max 0.175.
  - 277: 76, median 0.030, max 0.323.
- (2) is not relevant to this report; not evaluated.
- Not done: any code change. Candidates are a port of (3), and a bleed toward zero (instead of a hold) while the override fade is ramping. Both need tests and a drive.

### 143d. Owner-approved: PR #8's disengage reset ported, and the integrator bleeds through the override fade instead of holding. Unit tests, open-loop replay and closed-loop sim only; not driven.

Both changes are in `selfdrive/controls/lib/latcontrol_pid.py`.
- **Reset (PR #8 piece 3).** `LatControlPID.reset()` now clears `pid` state as well as `sat_time`, and the inactive branch calls `pid.reset()`. Open-loop replay, integrator on the first engaged frame:
  - HEAD: 277 max 0.304 (64/76 re-engagements above 0.05); 278 max 0.197 (16/28); 27a max 0.095 (7/13).
  - Now: 0 on every re-engagement.
- **Fade bleed.** Applies on modified-EPS cars only. It runs on frames where `steer_limited_by_safety` holds, the press detector is off, and the last press was within `HondaOverrideFadeUpSecs` (refreshed with the other params, default 1.5 like the carcontroller).
  - On those frames `pid.i *= exp(-dt / NRDR_OVERRIDE_FADE_I_BLEED_TAU)`, with tau 0.5 s.
  - Unchanged: the integrator stays frozen while pressed, and a limit with no recent press still freezes.
- **27a 12:34, closed-loop sim** (`plant_d5`, recorded pressed frames and carcontroller fade), wheel behind desired during the unwind:
  - 759.0 s: 21.4 → 16.3 deg.
  - 759.5 s: 17.7 → 12.8 deg.
  - 760.5 s: 4.4 → 0.6 deg.
  - No overshoot through 763 s.
  - Open loop, I at 758.5 s is −0.021 against HEAD's −0.204 (into the turn).
- **Whole-route closed-loop sim, 277/278/27a.**
  - RMS error is equal or lower in every band (<25, 25–50 and >50 mph), within 3 s of an engage and within 3 s of a release. The largest gain is 27a <25 mph: 15.90 → 15.72 deg.
  - p99 |err| is unchanged except 27a 25–50 mph: 3.1 → 3.2 deg.
  - Output chatter (rms d(out)) is unchanged.
- **Tests.** `selfdrive/controls/tests/test_latcontrol_pid_override_fade.py`: 3 of its 4 fail on HEAD; the fourth is the no-press freeze control. The other lateral tests still pass. The two failures in `test_latcontrol.py` (Bolt center limit, Palisade taper) fail on HEAD too and are not related.
- **Not validated.** Road feel after a press and release in a turn, especially short touches, which now lose some I. Owner: check turn exits after a nudge, and the first second after re-engaging.
- **Upstream.** Ported onto JamesL787/openpilot `ns-bosch-radar-testing` (`3a257065`) as PR JamesL787/openpilot#14 (branch `lateral/integrator-reset-and-fade-bleed`, one commit, the same two files). His tree lacks the rate-FF, trim-slew and kp-slew work, so the patch was rebuilt on his file. The tests were run against his patched file in this tree, since every module it imports is identical: 4 pass, and 3 fail on his unpatched file.

## 144. Torque controller on the modified-EPS Civic Bosch: why it fought the driver, and the fix (owner: "the controller is often too strong that override becomes somewhat of a safety issue"). Static reading, unit tests and sim only; not driven.
- **Override handling already applies.** The Honda carcontroller's `_update_steering_torque` scales the lateral command during a driver press for any controller: `HondaOverrideTorqueScale`, `HondaOverrideFadeUpSecs`, `HondaOverrideFadeDownSecs` and `NrdrIncreaseOverrideTolerance`. The torque controller gets the same override torque and fade up/down as the PID. No new setting is needed.
- **Cause: the torque tune, not the override logic.**
  - `ForceTorqueController` (and NNFF / NNFF-lite) call `configure_torque_tune`, which loads the params.toml row for `HONDA_CIVIC_BOSCH`: LAF 1.69 and friction 0.25. Those are fitted on the **stock** EPS.
  - The modified rack needs about 7x less command per m/s² (STATUS 140: LAF 11.5, friction 0.025 above 25 mph).
  - torqued keeps its learned LAF within ±30 % of the offline value, so starting from 1.69 it can never learn its way out.
- **New tool: `lat_pid_sim.py stiffness`.** It holds the wheel 5 deg off-centre on a straight and reads the command 0.1 s later (1.0 = full). This is the push-back the driver feels before any override ramp.

  | Controller and tune | 11 mph | 22 mph | 34 mph | 45 mph | 56 mph | 67 mph |
  |---|---|---|---|---|---|---|
  | PID | 0.105 | 0.119 | 0.281 | 0.310 | 0.315 | 0.315 |
  | Torque, stock table | 0.355 | 0.459 | 0.576 | 0.719 | 0.755 | 0.663 |
  | 2b, measured tune (the new road path, effective LAF 13.8) | 0.069 | 0.089 | 0.098 | 0.110 | 0.106 | 0.084 |
  | 2b at the backstop floor (LAF 9.6, friction 0.05) | 0.103 | 0.140 | 0.156 | 0.173 | 0.167 | 0.135 |

  - The PID row uses route 276's CarParams. The new test uses the fingerprinted C020 CarParams, whose PID row is 0.45 above 50 mph.
  - On the stock table, 10 deg of error is a full 1.0 command from 34 mph up.
- **Fix.**
  1. **Measured values.** A new hook, `CarInterfaceBase._converted_torque_tune` (no-op by default), runs after the torque conversion. The Honda override sets LAF 11.5 and friction 0.025 for `HONDA_CIVIC_BOSCH` with `EPS_MODIFIED`. Other modified-EPS Hondas are unmeasured and keep the table.
  2. **Backstop.** `LatControlTorque` bounds the modified Civic's offline, learned and custom-toggle values before its multipliers, both at init and in `update_live_torque_params`. LAF is floored at 8.0 and friction capped at 0.05 (`CIVIC_BOSCH_MODIFIED_MIN_LAT_ACCEL_FACTOR` and `_MAX_FRICTION`). A custom LAF or friction toggle can no longer make it stiff again.
- **Kept StarPilot's ×1.2 multiplier.** The effective LAF is 13.8, which is softer. In the 25–50 mph band on 263/268/271/276/277 it costs tracking: err rms rises from the 11.5 case by 0.09–0.23 deg per route (263 1.28 → 1.37, 268 1.36 → 1.49, 271 1.37 → 1.60, 276 1.07 → 1.22, 277 1.17 → 1.29), and the PID is 0.88–1.11 deg. So the torque path still tracks worse than the PID in sim (STATUS 142). Dropping the ×1.2 for the measured tune is a follow-up if the owner wants tracking over softness.
- **Tests.**
  - `test_honda.py`: the conversion gives 11.5/0.025 through all three toggles. Stock EPS and the modified Accord keep the table.
  - `test_lat_pid_sim_torque.py`:
    - Torque push-back is at or under the PID at every speed.
    - The floor case is within 1.25x of the PID.
    - The stock table is at least 1.5x the PID.
    - The bounds hold on the init and live paths.
  - `test_latcontrol.py`: the Civic multiplier test moved from LAF 3.0 to 10.0, since 3.0 is now floored.
  - The Bolt/Palisade and `test_straight_road_roll_bias` failures predate this (see 143d) and are not on the Civic path.
- **What changes on the car.** Nothing on the default PID path. Only with `ForceTorqueController`, NNFF or NNFF-lite on. NNFF uses its own stock-EPS model for the feedforward, which this does not fix; keep NNFF off on the modified rack.
- **Not validated.** Road feel and override effort on the torque path. Owner: if you try it, start with `ForceTorqueController` on and NNFF off, and push against it on a straight at 30–45 mph first.

## 145. The owner's C020 EPS firmware, and how often the PID asks for more than 0.35. Static decode against the owner's stock C020 image, and logged-route statistics; nothing on the car changed.

**Firmware.** Three images are in `eps_tools/rwd/`, all passing `check_rwd.py`: stock C020, the 2026-08-05 Trk4500 tune, and `-Trk4000-PTM`. The decode is in `eps_tools/rwd/README.md`. Changes from stock:
- tracker 1996 → 4500 (or 4000; this is the only difference between the two tunes);
- Norm 3429 → 1650;
- P row 0–179 → 117–265, the same in every row;
- D row 159/264 → 737;
- speed clamp 10 → 0;
- torque rows max 4147–4608 → one table to 30000;
- 310 bytes of new code, plus a few changed code words, not decoded.

The P clamp 7373 and the 1774 / 9000 words are stock.

**Does LAF 11.5 fit the firmware?** Roughly.
- The table gives 1.0–2.8× stock at the first breakpoint, depending on the row, and 6.5–7.2× at the top.
- Times Norm's ~2.08× that is roughly 2–6× the stock small-signal gain.
- Stock LAF is 1.69, so the prediction is about 3.5–10 against the 11.5 fitted on the road (STATUS 140). The P row raise may account for the rest.

This is a consistency check, not a derivation.

**PID |actuators.torque| distribution.** Routes 263, 268, 271, 276 and 277, engaged, not pressed, no lane change, from the `/tmp/latstudy` cache:

| speed | engaged time | >0.25 | >0.35 | >0.5 | p99 | p99.9 | max |
|---|---|---|---|---|---|---|---|
| <25 mph | 45 min | 24.6% | 22.4% | 19.0% | 1.00 | 1.00 | 1.00 |
| 25–50 mph | 59 min | 0.69% | 0.33% | 0.11% | 0.22 | 0.51 | 1.00 |
| >50 mph | 7 min | 0 | 0 | 0 | 0.10 | 0.14 | 0.23 |

Above 25 mph there are 15 episodes over 0.35, of two kinds:
- **Real curves at 26–31 mph.** 0.80 at 1.84 m/s² (271), 0.88 at 2.04 m/s² with 41° of wheel (276), 0.58–0.64 at 1.4 m/s² (277).
- **Near-straight transients.** 0.4–0.5 at ≤0.5 m/s². This includes a 2.65 s run of 0.51 at 46 mph on 277 (t≈302 s) that is not explained.

A flat 0.35 ceiling from 25 mph would clip the real curves. A speed-scheduled ceiling (no limit to ~35 mph, ~0.5 by 45 mph, ~0.3 from 55 mph) would touch nothing in these logs. However, the evidence above 50 mph is only 7 minutes. Not implemented.

## 146. The lateral sim now runs the command through the EPS firmware's torque table (owner: "improve the current lateral sim to account for my current eps fw value"). Sim and fit evidence only; nothing on the car changed.

**What it does.** `tools/lateral/eps_fw.py` reads one row of the C020 torque table from an `.rwd`:
- the input axis 0–1774 at `0x137f4`, and the torque at `0x13872`, 7 rows;
- it refuses images that are not C020.

`lat_pid_sim.py fit --eps-rwd IMAGE` fits the plant on table torque instead of the raw command. The table travels in the plant json. `validate`, `sim`, `sweep` and `compare --eps-rwd OTHER` (repeatable) swap in another image's table.

**What it does not model.** The EPS's own controller words (tracker, Norm, P row, D row, speed clamp) stay as they were on the fitted drives. When the swapped image differs in them, the sim prints a warning listing them. The sim therefore **cannot tell Trk4000 from Trk4500**: the two images share a table and differ only in the tracker. That needs a plant fitted on drives made with Trk4000.

**How the choices were made.** Plant fits at delay 5, window rms in degrees:

| routes | linear | owner row 0 | owner best row | stock row 0 | stock row 3 |
|---|---|---|---|---|---|
| 260–263 | 1.521 | 1.529 | 1.477 (row 3) | 1.800 | 1.996 |
| 268 / 271 | 1.274 | 1.275 | 1.275 (row 0) | 1.526 | 1.725 |
| 276 / 277 | 1.088 | 1.085 | 1.085 (row 0) | 1.231 | 1.348 |
| 278 / 27a | 1.426 | 1.404 | 1.388 (row 2) | 1.703 | 1.878 |

- **The stock table fits 15–25% worse on every group.** The logs agree those drives ran a modified table. The owner has not confirmed which image was flashed for each drive; every modified image reports `39990-TBA,C020`.
- **Row 0 is the default.** It is within 1% of linear on all four groups. What selects a row is not decoded. No speed schedule consistently beat row 0 (rows 0/3 either way at 11 m/s, rows 0/6 at 20 m/s).
- **A full command maps to axis 1774.** The stock table saturates at axis 1111/1774 = 0.626, which matches comma's stock-Civic 2560/4096 cap. The owner's table is near-linear, so the logs cannot pin the scale: rms moves under 1% for scales 0.6–1.2.

**Checks.**
- Plant fitted through the owner table on 260–263 at delay 5, validated on held-out 276 / 277 at the logged settings: the same metrics as the raw-command plant, within 0.03 deg err rms per band.
- Swap on 277, PID at logged settings (err rms deg, low / standard / highway):
  - owner table: 12.9 / 0.93 / 0.90;
  - Trk4000: identical, with a tracker warning;
  - stock table with the owner's controller kept: 30.5 / 2.10 / 1.56, with warnings for norm, P, D, speed clamp and tracker.
- Tests: `tools/lateral/tests/test_eps_fw.py`:
  - decode against the documented words;
  - non-C020 images are refused;
  - the table is odd and monotone;
  - the plant json round-trips;
  - the owner table reproduces the raw plant within 5%, and a 0.3× table tracks at least 1.4× worse.

## 147. This repo's NRDR PID vs nrdr-nightly's lateral controller on the owner's Civic, a centre-boost sweep, and the 2 August tracker drives (owner: "which one is better suited for me"; "on august 2 … I tried 2 files with 2 different trackers: 3200 and 4000"). Sim and log statistics only; nothing on the car changed.

**What nrdr-nightly runs on this car** (fetched as `refs/remotes/nrdr/nrdr-nightly`, v2026.003.000 prebuilt; static reading):
- `LatControlClarityHybrid` (PID below ~27 mph handing to NNLC/torque above ~33 mph) is selected only for `HONDA_CLARITY` (`sunnypilot/selfdrive/controls/controlsd_ext.py`). **A Civic Bosch cannot get it.**
- A modified-EPS Civic Bosch runs `NrdrLatControlPID`, the same family as this repo's PID. `configure_modified_eps` overrides the Civic tune to flat kp 0.03 / ki 0.01 / kf 1.2e-5, torqueBP/V [0,4096]. It also has:
  - rate damping 0.3 × 0.010 × steeringRateDeg, faded out by 30 mph;
  - centre boost `HondaCenterScale` 0.5 above 50 mph;
  - TuneLearner on by default.
- Its "hybrid steer ratio" is geometry only, blending two angle maps. The default mode 0 is manual 15.38→10.93. It is not a controller.
- nrdr's `STEER_RATIO_MODES.md` says the hybrid ratio is opt-in with no road validation. No Civic C020 validation is documented.

**Sim comparison.** Plant fitted through the owner's C020 table (STATUS 146), delay 5, on 260–263. Err rms in deg, with straight rms in brackets:
- `james` is the logged tuning (firmware VGR on, the owner's Lat* trims, `HondaCenterScale` 0).
- `nrdr` is `lat_pid_sim.py compare --variant nrdr=pid,kp=0.03,ki=0.01,kf=1.2e-5,rate_damp=0.3,NrdrLatUseFirmwareVgr=1,HondaCenterScale=0.5,Lat*Scale*=100`.

| route | band | james | nrdr |
|---|---|---|---|
| 276 | 25–50 | 0.88 (0.62) | 1.24 (0.87) |
| 277 | 25–50 | 0.93 (0.55) | 1.21 (0.78) |
| 271 | 25–50 | 0.91 (0.57) | 1.21 (0.79) |
| 27a | 25–50 | 0.81 (0.62) | 1.09 (0.85) |
| 268 | 25–50 | 1.29 (0.95) | 1.61 (1.22) |
| 278 | 25–50 | 0.55 (0.43) | 0.78 (0.62) |

- **25–50 mph, the band the sim is trusted in:** nrdr's gains track 25–45% worse on every route.
- **Below 25 mph:** within ±5%, either way.
- **Above 50 mph:** mixed; nrdr is better only on 268 (0.60 vs 1.10), from its I trim of 100 against the owner's 0.
- The repo's road-measured ratio curve (`NrdrLatUseFirmwareVgr=0`) scored 1–7% lower than the firmware map in most bands. Each variant is scored against its own target, so this is not a like-for-like comparison.
- **Not modelled:**
  - nrdr's TuneLearner (a learned bias);
  - its default manual steer-ratio mode;
  - the unwind-phase weighting of its rate damping.
- **Recommendation (sim evidence only):** stay on this repo's PID. nrdr's Clarity hybrid does not apply to this car, and its Civic gains track worse here.

**Centre boost** (`sweep --param HondaCenterScale`, 6 routes). Above 50 mph, going from 0 to 0.5 lowers err rms by 1–13% on every route, and 0 to 1.0 by 2–25%. Straight sign changes rise by 0–0.2/s on 3 of 6 routes. Below 50 mph it has no effect, since the boost only acts above 50 mph. There are only 0.6–2.2 highway minutes per route, and the autotuner's trust gate marks the highway band untrusted (sim 0.73 vs log 0.57 deg). So this is a candidate for a drive, not a setting.

**2 August drives** (device `11c8fa231c0499ed`, night-star-testing @ 96604b6c):
- **Available:** rlogs for 62, 63, 64, 66 and 6d. 68, 69 and 6b are not uploaded (qlogs only).
- **Command-to-wheel-rate coherence is ~0 above 10 Hz** on every route, including the later ones. The 20–35 Hz rate content is not driven by the command, so it cannot show a tracker difference. The only earlier sign of a tracker problem was the CR-V's ~29 Hz limit cycle (eps_tools/rwd/README.md), which would show as a rate peak. None of these routes has one: 20–35 Hz rate rms at 25–50 mph is 0.31–0.47 deg/s, below the later 271–27a (0.45–0.61).
- **Loop gain at 2–5 Hz** (|rate / command|, 25–50 mph, hands off; coherence 0.16–0.5), with values for each third of a route in brackets:
  - 6d: 44 (38 / 33 / 47)
  - 66: 57
  - 62: 72
  - 63: 76
  - 64: 98 (121 / 101 / 93)
  - later 271 / 277: 175 / 188
- **What that leaves:**
  - The spread is too wide and too continuous to split the routes into two images from the logs alone. Speed mix, temperature and the controller's command content all move this number.
  - Route 64 started one minute after 63 ended, which makes a flash between them unlikely.
  - The routes run 17:53–01:19 UTC. 6d, after the three missing routes, is the only candidate for a second image.
  - The owner's flash order, or the missing rlogs, would settle it.
- **Per-route plant fits are not identifiable:** gain 190–2800 with delay pinned at the grid minimum, so they were not used.

**Tool change.** `lat_pid_sim.py` variant keys `kp`, `ki`, `kf` and `rate_damp` apply to the pid kind only. They run another fork's flat gains and rate damping through this repo's PID; `kf` bypasses the banded modified-EPS kf. Tests are in `tools/lateral/tests/test_lat_pid_sim_torque.py`.

## 148. Close-lead brake cap: in experimental mode the 0.7*aLeadK term is bounded by the lead's stop geometry (routes 00000278 / 0000027a). Evidence is open- and closed-loop replay plus unit tests only; nothing has been driven.

- **Finding.** In experimental mode `get_close_lead_brake_cap` is built against the vehicle minimum (-3.5). Its `0.7*lead_brake` term set the peak brake in 8 of the 9 exp-mode bookmarks on 00000278 / 0000027a. It counted a stopped or crawling lead's aLeadK as "braking" and pulsed with it.
- **Change (`longitudinal_planner.py`, function body only).** When the cap's `accel_min` is below A_CRUISE_MIN (experimental mode; in chill only once `accel_limits_turns[0]` has followed a_desired below -1.0), the demand becomes `max(match, min(match + 0.7*b, stop))`, where `stop = vEgo^2 / (2*(gap + vLead^2/(2b)))`: ego stops inside the usable gap plus the lead's own stopping distance.
  - This is the same stop term `get_lead_geometry_required_accel` uses.
  - The change only softens, and never below the match term.
  - A moving lead that brakes normally keeps the full demand.
  - At the comfort floor (chill) the cap is unchanged from HEAD.
  - The change adds no new state.
- **Variants tried for the bound:**
  - V2g applies it in both modes.
  - V2b measures the stop to max(STOP_DISTANCE, target_gap) instead of target_gap.
  - V2a applies it only below the comfort floor. **V2a was chosen.**
- **Replay.** 30 routes in ~/routes, open loop, both modes as logged (271 from seg 7; 277 without segs 17-34), HEAD 3b5134d9 planner and radard. Variants tried:
  - V0 HEAD
  - V1 drop the term
  - V2g stop-geometry bound (chosen)
  - V2s drop the term below vLead 1.5
  - V3g / V3a V2g / V1 plus mildest-of-3 persistence
  - V4 no cap (reference only)

  | var | <-1.5 | <-2.5 | <-3.0 | exp <-1.5 | 0.5 s drops | pulses | new -1.5 | softer >0.3 | later >0.2 s | stock-ACC late >0.3 s (of 54) |
  |---|---|---|---|---|---|---|---|---|---|---|
  | V0 | 11171 | 2914 | 1432 | 1439 | 80 | 33 | - | - | - | 16 |
  | V1 | 11003 | 2795 | 1368 | 1198 | 53 | 24 | 7 | 14 | 12 | 14 |
  | V2g | 11018 | 2809 | 1376 | 1280 | 75 | 25 | 1 | 9 | 5 | 16 |
  | V2s | 11072 | 2844 | 1402 | 1335 | 78 | 33 | 0 | 5 | 2 | 16 |
  | V3g | 11029 | 2815 | 1387 | 1250 | 70 | 21 | 2 | 10 | 6 | 15 |
  | V3a | 11089 | 2815 | 1384 | 1187 | 53 | 21 | 8 | 15 | 13 | 14 |
  | V4 | 11143 | 2854 | 1424 | 1122 | 50 | 19 | 10 | 14 | 14 | 14 |

- **Bookmarks (min output, V0 -> V2g; V2a is identical on all 11).**
  - 278 BM2 -3.50 -> -1.69 (2 pulses -> 0).
  - 278 BM3 -3.25 -> -1.74.
  - 278 BM4 -2.73 -> -1.89.
  - 278 BM5 -2.71 -> -1.77.
  - 27a BM0 -1.97 -> -1.37.
  - 27a BM1 -3.02 -> -1.37; the +1 s pulse -2.97 -> -0.53.
  - 27a BM4 -2.39 -> -1.20.
  - 278 BM1 stays at -3.50. It is a radar range jump (64 -> 55 m, vRel -6.1, aLeadK -5.5 on a 15.7 m/s lead, vision 20.2 m/s): an input glitch that geometry cannot tell from a hard brake.
  - 278 BM0 and 27a BM2/BM3 are chill mode, the cap is not involved, and they are unchanged.
- **Protected cases: V2g, V2b and V2a are identical to V0.**
  - 25b 1338.8, 25e 318.1, 25f 483.1 and 0263 374.3: same minimum and same -1.5 crossing.
  - 271 BM0: min -6.29, -1.5 crossing at -2.50 s.
- **Softer or later brakes under V2g (9 softer, 5 later), all exp mode.** V2a has the same list; its fleet rerun (32 routes with 24f and 258, 182 episodes) is below. Each was checked against the stop need from radar (physR) and vision (physV):
  - 0232 1233.8: stopped lead at 51 m; -2.51 -> -2.04, crossing unchanged; need 1.25 / 1.55.
  - 0236 858.0: radar aLeadK -4.46 while vision a -0.07; -3.50 -> -2.04; need 0.23 / 0.92.
  - 026c 756.6: stopped lead at 96 m, railed vRel -13.5; -3.32 -> -1.91, +0.25 s; V2g -1.40..-1.75 against a need of ≤1.24 / ≤1.10.
  - 278 390.5 (BM2): -3.50 -> -1.69, +0.5 s; need 0.87 / 1.47.
  - 278 447.0 (BM3): stopped lead at 85 m; -3.25 -> -1.74, +3.65 s; need about 0.9-1.1.
  - 278 737.7 (BM4): stopped lead at 73 m; -2.73 -> -1.89; need 1.25 / 1.64.
  - 278 854.9 (BM5): lead at 40 m doing 11 m/s; -2.71 -> -1.77; need 1.55 / 0.97.
  - 27a 324.1: slow lead at 60 m; -3.02 -> -1.26, never crosses -1.5; need ≤0.93.
  - 27a 607.8: lead at 17.7 m doing 0.3 m/s, vEgo 4.3; -2.39 -> -1.20; need 0.66 / 1.02.
  - The one new crossing, 0245 46.7 (-1.50 -> -1.51), is threshold noise.
  - Every softer brake is a phantom, a stopped or slow lead far enough away, or still at least the stop need.
- **Why not the others.**
  - V1 is later on real closings (0268 326.1 +0.25 s with a need of 1.8; 026c 257.1 +0.2 s with a need of 2.1) and adds 7 new crossings.
  - V3 adds state and onset delay (0232 +0.2 s, 026c +0.35 s) with no pulse gain at the bookmarks.
  - V2s leaves 278 BM2/BM3 and 27a BM1 mostly unfixed.
  - Fix (5), the exp->chill release, was not taken: it would add a guard.
- **Fleet rerun (32 routes, 182 episodes).**

  | var | <-1.5 | <-2.5 | <-3.0 | exp <-1.5 | drops | pulses | new -1.5 | softer | later | stock late (of 54) |
  |---|---|---|---|---|---|---|---|---|---|---|
  | V0 | 11473 | 2914 | 1432 | 1506 | 82 | 33 | - | - | - | 16 |
  | V2g | 11317 | 2809 | 1376 | 1347 | 77 | 25 | 1 | 10 | 5 | 16 |
  | V2b | 11322 | 2810 | 1377 | 1352 | 77 | 25 | 0 | 9 | 5 | 16 |
  | V2a | 11253 | 2809 | 1376 | 1347 | 77 | 25 | 0 | 10 | 5 | 16 |

  - The softer lists of V2g and V2a add one chill entry, 0236 2096.9: min -2.14 -> -1.79 (V2a -1.79 as well). The lead is 10.4 m ahead at vRel -1.0 with aLeadK +0.8, and the need is 0.10 / 0.48.
  - At 2096.9 the close-lead cap is inactive (0.0) in every variant, and the frame is the first one after engagement. The difference is therefore per-variant planner state carried across the disengaged stretch, not the cap law. The same effect produces V2a's lower chill <-1.5 count (66 frames on 0236). The state was not traced further.
- **Tests.**
  - New cases in `test_longitudinal_planner.py`, run against the vehicle minimum:
    - a stopped lead's aLeadK is ignored;
    - a slow lead is bounded by the stop geometry, milder than HEAD;
    - a fast braking lead keeps the full demand.
  - A further new case covers the comfort floor: at A_CRUISE_MIN the cap equals HEAD's full demand, and at -3.5 it is milder.
  - `test_off_axis_lead_keeps_vision_corroborated_brake` now asserts < -2.75, the stop need of 2.77 for aLeadK -7.8 at 17.1 m/s over its 43.8 m gap (was < -3.0; output -2.94).
  - 607 pass with longcontrol. Ruff reports no new findings.
- **Held patch.** /tmp/cf/fastclose_floor.patch still applies cleanly (`git apply --check`). It builds the cap against the vehicle minimum for fast-closing leads in chill, so V2a's bound would also apply to those leads once it lands. Its own test lead has aLeadK 0, so that test is unaffected. The combination has not been replayed.
- **Closed loop, STATUS 61/64 method** (from pk-6, ego accel follows `output_a_target` through a lag with tau 0.35, lead replayed and not reactive, dRel/vRel recomputed against the simulated ego, model and aLeadK as logged, HEAD radard re-run from CAN, metrics pk-6..pk+8). The V0 column reproduces STATUS 64's base within 0.8 m.

  | Event | V0 minGap m / minTTC s / peak | V2g | V2b | V2a | V4 (no cap) |
  |---|---|---|---|---|---|
  | 24f B 170.2 | 13.99 / 4.22 / -1.99 | = | = | = | 14.23 / 4.31 / -1.95 |
  | 24f C 272.7 | 17.42 / 5.93 / -2.10 | 17.36 / 5.93 | 17.38 / 5.93 | = | 17.42 / 5.94 |
  | 24f D 367.4 | 28.45 / 4.27 / -2.28 | = | = | = | 27.29 / 3.87 / -2.12 |
  | 24f E 449.1 | 9.04 / 4.28 / -1.00 | **7.77 / 3.58** | **8.19 / 3.84** | = | 7.60 / 3.61 |
  | 24f E to 468 (stop) | 5.16 / 4.25 | **4.75 / 2.89** | 5.31 / **3.44** | = | 4.75 / 2.95 |
  | 24f F 595.7 | 38.61 / 9.02 / -1.00 | = | = | = | 36.56 / 7.94 |
  | 258 63:50, 3831.9-3860 (seg 64 added, through the 2nd stop) | 7.97 / 4.25 / -1.47 | **4.80** / 4.24 | **5.50** / 4.25 | = | 5.13 / 4.13 / -1.66 |

  - E and 258's second stop are chill-mode, low-speed stops (comfort floor -1.0) behind a lead slowing to a stop with aLeadK around -1.
  - There the `0.7*aLeadK` term holds the cap near -1.0. The stop-geometry bound relaxes it to the cap's own 2-3 m standoff, and ego closes in.
  - At the E stop, V0 stops 6.16 m back and V2g 5.13 m back.
  - V2b fails both E (0.9 m / 0.4 s, and 0.8 s TTC through the stop) and 258 (2.5 m).
  - V2a leaves chill untouched and equals V0 on every closed-loop event.
- **Not verified.** There has been no road drive. The 278 BM1 glitch is not addressed. In chill the cap still counts a crawling lead's aLeadK (by design, per E and 258). Interaction with the held fast-closing patch has not been replayed.

**Rejected the same day (replay only; nothing committed):**
- **Less-closing correction for a railed lead with slowly shrinking range (277 38:17.4, track 55).** The motivating lead was in a D-043 coast, with a range burst at the rail value; vision was at prob 0.15-0.46 at 104-118 m. The strict gate never fired there. On the fleet it softened real closings: 266 484.2 (a vision-confirmed brake) -2.28 -> -2.18, and 263 358.6 released -2.00 -> -1.30. This is the same failure as fix 1 and STATUS 111/129. Patch: /tmp/rl/rail_slow.patch.
- **Path-relative replacement for radard's `|yRel| <= 1.5` D-053 gate (26c 4:08).** At 4:08 it corrected on one cycle only (-2.0 crossing 0.05 s earlier); the long fit's span/residual across D-043 coasts is the real limiter. It added spurious -1.5 crossings on curve range wobble at 70-95 m (26c 649.9, 237 942.8), and 236 2211.4 went -3.16 -> -3.50. The lateral gate was filtering the curve range walk. Patch: /tmp/yg/pathgate.patch.
- **Held, not rejected: the close-lead cap built against the vehicle minimum for a vision-corroborated radar lead closing >= 10 m/s at TTC <= 6 s (271 BM0).** -1.5 crossing -2.49 -> -3.19 s. Costs: frames < -3.0 1387 -> 1894, 0.5 s drops 73 -> 88, a one-tick step, and 025f 483.0 min -3.88 -> -3.50 (a single-tick artifact). Held because the owner reported rough braking; it would combine with this item's bound, and that combination is unreplayed. Patch: /tmp/cf/fastclose_floor.patch.

## 149. Two planner fixes for the remaining exp-mode bookmarks on 00000278 (BM1 reassociation, BM0 slow-lead gate), and a radard young-track bound for 27a BM2 (committed separately after the owner's OK). Open- and closed-loop replay plus unit tests only; nothing has been driven.

Harness times: analyst + 4.115 s on 278 and + 1.672 s on 27a. The fleet is the 32 routes of /tmp/cap/out2 (179 brake episodes), replayed open loop through the Bosch-A RadarInterface, RadarD and the planner. In closed loop, ego accel follows the output with tau 0.35 and the lead is shifted by the ego position difference (vision is not shifted).

1. **`REASSOC_LEAD_BOUND`** (planner input, `bound_reassociated_leads`, next to the off-axis bound). Covers 278 BM1.
   - What happened: radar track 21 slid from a car at 66 m onto a nearer car that vision had at 48-50 m (p >= 0.96, not closing).
     - U11 -0.4 -> -6.6; D-053 -13.2; aLeadK -5.5.
     - Alpha commanded -3.50 (aEgo -4.4) for a car doing ego's speed.
   - Arming conditions: the radar lead started at least 10 m beyond a confident vision lead (p >= 0.9) and has since dropped at least 6 m. Vision is at or nearer the radar range (+3 m), closing <= 2 m/s, and a >= -1.5.
   - Bound while armed: vRel/vLead/vLeadK are bounded to vision's closing minus 1.5 m/s, and aLeadK to -max(1.0, vision brake), for up to 3 s.
   - What is not touched: dRel, the track, radarState and radard. No point is removed (D-041/D-042).
   - Replay results: open loop -3.50 -> -1.22; closed loop -3.50 -> -1.49, min gap 45.9 -> 44.2 m.
2. **`SLOW_RADAR_LEAD_STOP_GATE`** (`raw_close_lead_needs_control`). Covers 278 BM0.
   - What happened: after an exp -> chill switch 93 m behind a 1.8-2.5 m/s radar lead at 16 m/s, chill's raw gate admitted the slow (not stopped) lead only inside max(40, 3v). The close cap first bit at 73 m.
   - Change: a radar lead at or below 3 m/s with modelProb >= 0.9 is now admitted inside closing^2/2 + 10 m, capped at the stopped-lead limit.
   - Replay results: open loop -2.65 -> -2.53; closed loop -2.87 -> -2.41, min gap 7.10 -> 6.72 m.
   - The remaining -2.4 is chill's ACC MPC approach profile. BM0 is softened, not made comfortable.
   - Three episodes brake 0.25-1.0 s earlier: 232 1232.8, 278 278.2 and 278 737.0. In all three, vision has the lead at 2.4-3.7 m/s at the radar range, so they are real approaches.

**Fleet, both fixes together (replay, open loop):**
- Protected list: every case unchanged. This covers 232 1147.2, 236 771.9, 237 764.7, 25b 1338.8, 25e 318.1/723.0, 25f 483.1, 263 358.6/374.3, 266 484.2/560.0/795.4, 268 700.9 and 26f 516.9.
- New -1.5 crossings: 0.
- Softer brakes: only 278 BM1.
- Earlier brakes: only the three above.
- Frames below -3.0: 1376 -> 1363.

**Closed loop:** 24f B-F and 258 63:50 are identical to HEAD.

**Rejected:**
- Exp -> chill handoff ceiling hold: costs 1.0 m of closed-loop gap on BM0.
- Vision non-contradiction before the STATUS 119 pass: softens protected 26f 516.9 from -2.14 to -1.62.

**Committed after the owner's OK (radard, follow-up commit the same day):**
- What it is: `YOUNG_TRACK_FLAT_RANGE_BOUND` + `YOUNG_TRACK_VISION_GATE`, covering 27a BM2. A track at most 1 s old has its published vRel raised to (fitted fresh-sweep range rate - 3).
- When it applies: >= 6 sweeps over >= 0.35 s, residual <= 0.6 m, |rate| <= 6, and a confident vision lead at or beyond range - 5 m that is neither closing nor braking.
- Why 27a BM2 needs it: track 15 was born at 64 m with U11 -11.1 and coasted at -10.7 while its range stayed flat. Vision had the lead at 73-85 m doing ego's speed.
- Replay results: -2.02 -> -1.38 open loop, -1.88 -> -1.28 closed loop.
- Lead publication: 0 leads lost or gained. vRel was raised on 164 lead frames and never lowered.
- Fleet (32 routes, with F1+G): no other episode changes.

**Tests:** test_longitudinal_planner, test_longcontrol and test_range_vrel_assist pass (620). ruff has no new findings versus HEAD.
  radard tests: test_range_vrel_assist, test_radard_bosch and test_leads pass; test_leads::test_radar_fault errors at teardown on `/data/params` (errno 13, sandbox only).

**147 addendum: autotune, and the 2 August flash order** (owner: "3200 I believe then 4000").
- **Autotune result.** Command: `lat_autotune.py --plant plant_d5_fw` on 271/276/277/278/27a. Only the 25–50 mph band is trusted, so the low and highway knots stayed frozen. It proposes `LatGainSchedule {"v_mph":[20,30,40,50],"p":[100,130,125,105],"i":[50,95,75,75],"f":[50,100,100,100]}` against the driven p 105/105 and i 75/75 at 30/40 mph.
  - 25–50 mph err rms 0.848 → 0.771 (−9%); straight rms 0.570 → 0.524.
  - Sign changes 0.75 → 0.79/s.
  - Holdout cost on alternate 2-minute blocks: 0.924 against the seed.
  - This is sim evidence only; nothing was written to params. Drive it and compare it with the driven schedule before keeping it.
- **When the flash happened, from the route list.** Konik lists short parked sessions between the drives:
  - 61, 17:48 UTC, before 62;
  - 65, 18:46, after 66;
  - 67, 20:20, before 68;
  - 6a, 21:02;
  - 6c, 00:52, 0.5 mi.
  - The longest break, with a parked session at each end, is 66 → 68 (18:49 → 20:19 UTC). If 3200 went on first, the most likely split is **3200: 62/63/64/66; 4000: 68/69/6b/6c/6d**.
  - The EPS reports `39990-TBA,C020` on every route, so the flash itself leaves no trace in the logs.
- **The tracker leaves no mark on the closed-loop response.** 68, 69 and 6b have qlogs only, so every route was redone from qlogs at 10 Hz. Values are |steering rate / command| at 0.7–1.5 Hz, hands off, lateral active, 35–45 mph:
  - 3200 group: 38 / 34 / 44 / 48.
  - 4000 group: 33 / 62 / 42 / 34 (6d 34).
  - Later Trk4500 drives 271 / 277: 36 / 37.
  - Across a whole route, what moves this number is speed and command amplitude. 64 and 69 are high, with the lowest speed and the largest commands; 62, 68 and 6d are low.
  - **Correction to 147:** the 2–5 Hz grouping above, which singled out 6d, was that confound, not the image.
  - The logs cannot tell trackers 3200, 4000 and 4500 apart, in either the response or high-frequency content.
- **The same result in the owner's band parameters** (owner: "I don't do the 20/30/40/50 speed band. It's below 25 / 25-50 / 50 and above"). Standard-band grid run with `compare --variant ...LatPScaleStandard=P,LatIScaleStandard=I` on the same 5 routes. LowSpeed and Highway are untouched. Values are 25–50 mph, minutes-weighted over 60.8 min:

  | Standard P / I | err rms | straight rms | sign changes/s |
  |---|---|---|---|
  | 105 / 75 (driven) | 0.839 | 0.559 | 0.74 |
  | 115 / 85 | 0.788 (−6%) | 0.527 | 0.83 |
  | 125 / 95 | 0.745 (−11%) | 0.498 | 0.87 |
  | 135 / 95 | 0.720 (−14%) | 0.475 | 0.93 |

  - Error falls monotonically with both gains on every route, and there is no optimum inside the grid.
  - The fitted plant does not reproduce the high-frequency EPS dynamics that eventually limit gain on the car. So the sim cannot say where to stop, and the rising sign-change rate is the only warning it gives.
  - Suggested next drive: `LatPScaleStandard 125`, `LatIScaleStandard 95`. That is within the autotuner's 25-point trust region and matches its 30/40 mph knots.
  - Revert if the car hunts on straights at 25–50 mph.
  - Sim evidence only; nothing written to params.
- **Highway band, from route 1b8** (owner: "I do have a long highway route with rlogs: 11c8fa231c0499ed/000001b8--6098496d3c").
  - **The route:** driven 29 Aug, 68 mi. 52.1 min engaged hands-off above 50 mph, against 0.6–2.2 min on each of 271–27a. Driven with LatP/I/FScaleHighway 100/100/100 and HondaCenterScale 0.5. It is assumed to be on the owner's Trk4500 image, which is dated 5 Aug.
  - **Current plant (260–263 only)** at the driven tuning on 1b8: highway err rms 0.39 vs log 0.33, straight 0.37 vs 0.32, lag 0.52 vs 0.27 s, zero crossings 0.8 vs 1.1/s. That is inside the gate but slow and calm, a bias toward over-gaining.
  - **Refit plant:** 260–263 plus the first half of 1b8, delay 5, same table: coef [-12.18, -0.023, -2.229, -7.273, 854.8, -9.005, -17.38, -20.20, -150.5]. The command gain at 30 m/s rises from about 275 to about 428 (per table-torque unit). It lives in /tmp/plant_d5_hwy.json and is not committed; refit with `fit_plant(... delays=(5,), eps=owner table)`.
  - **On the held-out second half of 1b8** (22.6 min highway, log / old / new):
    - err rms 0.35 / 0.43 / 0.37;
    - straight 0.34 / 0.41 / 0.36;
    - sign changes at 0.15 deg 0.38 / 0.35 / 0.36 per second.
  - The 25–50 mph band is unchanged on all 6 routes (within 0.01 deg).
  - **Still failing: highway curves.** On 271 and 277 the sim follows 0.71–0.74 of the desired curvature against 0.83–0.86 logged. That rests on about 10 s of highway-curve data in total, and 1b8 has 3 s, so the gate still marks the highway band untrusted on curve ratio. The gate was not relaxed. A highway drive with sustained curves (interchanges, curvy freeway) would settle it.
  - **Highway grid on the held-out half** (straight-line figures only; new plant). Driven P100/I100/C0.5 scored err 0.370 and straight 0.355:
    - P 85 / 115 / 130: 0.405 / 0.341 / 0.317; zero crossings 0.84 / 1.05 / 1.14 per second against 0.95.
    - HondaCenterScale 0 / 1.0: 0.443 / 0.322.
    - **I 0: 0.457 with bias +0.21 deg. I 0 plus C 0, as driven on 271–277: 0.563 with bias +0.28.** The +0.3–0.5 deg highway bias noted above is, in the sim, the missing integrator.
  - **Road evidence** (confounded by road and traffic): 1b8's logged highway err rms is 0.33–0.35 at I100/C0.5, against 0.46–0.67 logged on 271–278 at I 0–75/C0.
  - **Suggested highway settings** (sim, straight-line only): LatIScaleHighway 100, HondaCenterScale 0.5, LatPScaleHighway 100–115. Watch highway curves, which the sim cannot score yet.

## 150. Fast-closing lead pass (the held 271 BM0 fix from STATUS 148), now capped at -2.0. Open- and closed-loop replay plus unit tests only; nothing has been driven.

- **What it is.** For a radar lead that the MPC is braking for, closing >= 10 m/s at TTC <= 6 s, and seen closing by vision too, the close-lead cap may pass the -1.0 comfort floor. It is held on the same track while closing stays >= 5 m/s. This is the held patch /tmp/cf/fastclose_floor.patch, whose reasoning is in the code comment.
- **What is new.** The pass is built against max(vehicle min, -`FAST_CLOSING_LEAD_MAX_BRAKE`) = -2.0 (`fast_closing_accel_min`), not the vehicle minimum.
- **Why capped.** The uncapped version was held for the owner's rough-braking report. Re-replayed on the current tree (32 routes, 178 episodes), it deepened 22 approaches, many to -3.5, took frames < -3.0 from 1363 to 1626, and made 025e 318.1 go -2.48 -> -3.38.
- **Capped at -2.0 (fleet, open loop):**
  - Frames below -3.0: 1363 -> 1328. Below -2.5: 2772 -> 2704. 0.5 s drops: 77 -> 84.
  - 11 approaches start braking 0.1-0.8 s earlier. Their peaks are mostly softer (271 567.2 -2.50 -> -2.33, 270 516.6 -2.85 -> -2.63, 026f 81.9 -2.96 -> -2.81).
  - One new -1.5 crossing: 241 218.7 at -1.83. That is a real slowdown to a lead doing 5 m/s at 70 m, where the driver braked to -4.4.
  - 266 29.2 goes -1.88 -> -2.34. That is an approach to a 1-2.5 m/s lead.
  - Protected list: nothing softer or later.
  - A cap of 1.5 was a no-op.
- **Closed loop (tau 0.35, non-reactive lead):**
  - 271 BM0 (559-575): peak -5.68 -> -3.05, min gap 8.99 -> 13.51 m, TTC 1.95 -> 2.74, -1.5 crossing 0.9 s earlier.
  - 270 516: -4.87 -> -3.26, gap 13.6 -> 18.3 m, TTC 2.18 -> 3.37.
  - 271 1793: -3.84 -> -3.74, gap 9.27 -> 9.21.
  - 24f B-F and 258 63:50: identical.
- **Tests:** test_longitudinal_planner + test_longcontrol pass (623); 11 new tests are the held patch's plus a cap test. ruff: no new findings.
- **Road check:** on a fast approach to a stopped or slow car, braking should begin earlier and hold around -2 rather than arriving late and hard. Watch for early braking on a car that is turning off.

## 151. Low-speed plant trained on the post-3-August routes, and the Galaxy NRDR lateral tuner now runs the sim (owner: "train the sim on the low speed routes, on anything past august 3"; "redo the nrdr lateral tuner on galaxy to reflect these new changes given the better sim"). Sim, replay and log statistics only; nothing on the car changed and no params were written.

**Plant.** `tools/lateral/plants/civic_bosch_c020.json` is a two-band plant (`BandedPlant` in `lat_pid_sim.py`): a low band below 22 mph, the STATUS 147 highway band (route 000001b8) above 28 mph, and a linear blend between them. Both bands send the command through the C020 torque table (STATUS 146). The low band adds a centring term `c9·tanh(θ/2)`. It was fitted on 36 routes after 2026-08-03 (163 hands-off minutes below 25 mph, delay 5 frames) and scored on held-out routes 271/276/277/278/27a (12.2 low-speed minutes):

| | err rms | straight rms | curve ratio | sign/s |
|---|---|---|---|---|
| log | 14.31 | 2.80 | 0.869 | 0.37 |
| sim, first fit (12 routes) | 14.04 | 2.36 | 0.914 | 0.42 |
| sim, shipped fit (36 routes) | 14.03 | 2.36 | 0.915 | 0.41 |

The sim reads the straight-line error about 16% low. Doubling the training data changed nothing held out, so the gap is in the model form, not the amount of data.

**LowSpeed grid** (first low fit, same held-out routes; the shipped fit matches it held out). At the current 100/50, the sim straight-line rms is 2.36:

| P/I | straight rms | curve ratio |
|---|---|---|
| 115/75 | 2.27 | 0.941 |
| 130/75 | 2.19 | 0.948 |

F has no effect below 25 mph. The provisional LowSpeed suggestion is P 115, I 75: the smallest step, because the sim's error is larger than the gain.

**Galaxy tuner.** `lat_tune_workspace.run_worker` now runs `tools/lateral/lat_tune_sim.refine_trial` after the rule analysis:
- It uses the same trust gate as lat_autotune: err and straight rms within 25% of the log, curve ratio within 0.05, at least 3 minutes per band, and a fit/holdout split in alternating 120 s blocks.
- For each trusted band it replaces the rule P step with the best sim cell of a 3×3 grid of P ±0.10 and I ±25, vetoed on sign rate and driver-press rate. An untrusted band keeps the rule result.
- The plant is only used when carParams shows `HONDA_CIVIC_BOSCH` with EPS `39990-TBA,C020`.
- Extracts are cached in `workspace/sim_cache`; the job is cancellable; if the sim fails, the rule result stands.
- Apply now writes `LatIScale<band>` as well as `LatPScale<band>` when the sim moves I. Both frontends show P and I, the source (rules or sim), and the trust line.
- The CLI `tools/lateral/lat_tune_cli.py` does the same; `--no-sim` gives rules only.
- On the newest 8 routes the CLI kept only 00000278 (tuning changed across the others). That left 7.5 trusted Standard minutes, and the sim proposed Standard P 105→115, I 75→100. LowSpeed and Highway had 0 minutes, so the rules held them. 7.5 minutes is thin.

**Not known:** the worker's runtime on the device. On this x86 box it takes about 0.7 s per route-minute with 2 workers, and the device will be slower. Whether any sim step helps on the road is also unknown.

**Incident:** this session's fetch script deleted each route's raw segment dirs after extraction without checking whether they predated the session. That removed the raw rlogs of radar-fleet routes 0000023e and 00000258 (the radar session is re-fetching them). The script was stopped at 17:04 UTC. Any script that frees disk must delete only the files it downloaded itself.

## 152. Vision-corroborated range assist for 26c 4:08 (late brake on a curve), default OFF. Open- and closed-loop replay plus unit tests only; nothing has been driven.

**What it is.** A module constant `VISION_ASSIST_GEOMETRY` (radard.py, default `False`, rides the
`RangeDerivedVrel` toggle) extends D-053. On 0000026c--10bec2e200 at 4:08, D-053 never engaged for
three reasons:
- the |yRel| <= 1.5 lane gate (the track sat at yRel 9.3 -> 6.3 m),
- the long-fit span/residual guards,
- the 5-update arm count.

The path-relative replacement for the lane gate was rejected (STATUS 148, /tmp/yg/pathgate.patch).
This change relaxes those three blocks only on updates where `modelV2.leadsV3[0]` corroborates the
closing itself. That means all of the following:
- prob >= 0.7,
- x - 1.52 within 15 % of dRel,
- |yRel + y| <= 3 m,
- vision closing speed vEgo - v >= 5 m/s.

When relaxed:
- the lane gate is lifted up to the existing 10.8 deg azimuth bound;
- a long fit failing span/residual falls back to the short fit;
- arming takes 3 updates instead of 5, provided vision corroborated every one of them.

The correction may exist only because of one of these relaxations, i.e. the plain D-053 rule would
publish zero on that update. In that case:
- the published vRel is bounded at -(vision closing + 3 m/s);
- it drops to zero on any update where vision stops corroborating.

Once the plain rule would have armed on its own, the correction is exactly the plain D-053 one. The
replay shows 0 frames where the published vRel is less closing than H, over 32 routes. No point is
deleted or hidden: lead lost/gained 0 and lead id/d changed 0 over the fleet.

**26c 4:08, open loop, H -> E5 (shipped constants):**

| Metric | H | E5 | Change |
|---|---|---|---|
| -1.0 crossing | 256.90 | 256.75 | 0.15 s earlier |
| -1.5 crossing | 257.05 | 256.80 | 0.25 s earlier |
| -2.0 crossing | 257.15 | 257.15 | same |
| -3.0 crossing | 257.35 | 257.35 | same |
| Minimum | -3.35 | -3.29 | 0.06 softer |

Vision closing during the onset was 5.3-6.5 m/s at p 0.74-0.82. The published vRel was about -9 from
256.70, where H had -4.3. Past about 257.0 the MPC, not the radar, limits the response. That is why
the gain is small and should not be read as "fixed".

**26c 4:08, closed loop (clrb.py, 250-264):**
- min gap 32.85 -> 33.15 m
- min TTC 4.36 -> 4.43 s
- peak -3.41 -> -3.33
- -1.5 crossing 0.25 s earlier

**Wobble cases (STATUS 148):** 26c 649.9, 237 942.8 and 236 2211.4 are identical to H, including
the vRel minimum.

**Fleet, 32 routes, open loop, H vs E5:**
- new -1.5 crossings: 0
- softer > 0.3 or later > 0.2: 0
- deeper: 0

Protected cases:
- 025e 318.1: -2.48/318.82 -> -2.46/318.87, i.e. 0.02 softer and 0.05 s later at -1.5. It arms
  0.2 s earlier, and the open-loop planner then asks slightly less afterwards. Vision closing there is
  9.6 m/s.
- 0266 484.2: 0.05 s earlier.
- 0268 700.9: 0.03 deeper.
- All other protected cases: identical.

Five earlier episodes. All are vision-confirmed (vision closing 6-14 m/s, p >= 0.70) and all are
real brakes that stock also braked for where stock was driving:
- 025d 105.7: 0.26 s earlier
- 025e 369.0: 0.21 s earlier
- 025e 529.6: 0.55 s earlier
- 0261 132.2: 0.75 s earlier, min -3.11 -> -2.97
- 26c 256.8

24f B-F closed loop: identical. 258: open loop changes at most 0.01. In closed loop, 3831.9 is
identical and at 3320 min gap goes 22.36 -> 22.82 m and peak -3.64 -> -3.62.

**Iterations that failed, kept for the record:**
- Bypass-only (margin 3, p 0.5-0.9): no change at 26c. Vision closing (5-6 m/s) bounded U11
  (-9 .. -13.5) to zero.
- V70s3, i.e. vision closing >= 3 m/s with the bound applied only to bypass/short-fit corrections.
  It produced -1.0 dips that vision did not confirm, because early arming was unbounded:
  - 0245 773.9: -0.58 -> -1.00
  - 025e 313.6: -0.65 -> -1.00, published -9.65 against a vision closing of 3.4
  - 0271 1434.3 (margin 5): -0.21 -> -1.00
- Applying the vision bound to every corroborated correction (CAP_ALL) softened existing D-053
  brakes. 588 frames were less closing than H, e.g. 0261 -3.11 -> -2.84 and 26c 1127 -2.14 -> -1.93.
  Replaced by the "bound only what the plain rule would not publish" rule.

**Verdict.** Passes the stated gates on replay:
- 0 new crossings
- 0 softer/later outside tolerance
- no vision-unconfirmed episode
- 3 wobble cases unchanged

The 26c improvement is modest: 0.25 s at -1.5, and nothing at -2.0 or deeper. Default stays OFF;
turning it on is an owner call.

Tests (static): `test_range_vrel_assist.py::TestVisionAssistGeometry` (8 cases) covers:
- off by default,
- inert without vision,
- the azimuth bound,
- the vision-closing bound,
- the helper gates,
- in lane, never less closing than plain D-053.

Commands and results:
- `test_range_vrel_assist.py` + `test_radard_bosch.py`: 133 passed.
- `test_py39_compat.py`: passes.
- `test_leads.py`: 6 passed, 1 teardown error (/data/params). HEAD has the same error.

Routes 0000023e and 00000258 lost their rlogs mid-run to a lateral cache job and were re-fetched
from konik before the final fleet. The final numbers above cover all 32 routes.

## 153. The STATUS 152 vision-corroborated range assist is now a toggle, `RangeVisionAssist` (default ON at the owner's request, stock value off; editable in Galaxy and on the device). Static tests and a params round-trip only; nothing has been driven.

Owner: "make it a toggle for me in starpilot. Make sure it's editable".

- **Key.** `RangeVisionAssist` (PERSISTENT, BOOL, default 0) in `common/params_keys.h`.
- **Galaxy and device.** The row is labelled "Camera-Confirmed Curve Closing Speed". It sits under Advanced Longitudinal Tune, right after Range-Derived Closing Speed, and like that row it can only be changed while the car is parked (`requires_offroad`). It is in both `device_settings_layout.json` and `longitudinal.py`.
- **radard.** radard reads the key on the same 100-frame cadence as `RangeDerivedVrel`.
  - It only counts when `RangeDerivedVrel` is also on, since the assist is an extension of D-053.
  - It is read in its own `try`, so a `.so` without this key reads it as off and leaves D-053 running.
  - `Track.update` gets `vision_assist=`. The code constant `VISION_ASSIST_GEOMETRY` stays `False` and still forces the assist on for replay harnesses, so the STATUS 152 numbers apply unchanged when the toggle is on.
- **Params artifacts.** `common/params_pyx.so` and `libcommon.a` were rebuilt natively on this aarch64 Ubuntu 24.04 host with the pinned toolchain: clang 18.1.3, system Python 3.12.3, Cython 3.1.4, `SP_FORCE_TICI=1`, the repo bind-mounted at `/work`, sconsign and both targets cleared first.
  - Keys went from 856 to 857. The only addition is `RangeVisionAssist`, and nothing was dropped.
  - `params_pyx.cpp` came out byte-identical.
  - On the new `.so`, `RangeVisionAssist` reads False by default, put_bool/get_bool round-trips, and it reads False again after remove.
- **Tests.** `test_range_vrel_assist.py` has 5 new cases: the param switch gives the same result as the code flag, plus a parametrised param read (both on, child off, parent off, key missing).
  - `test_range_vrel_assist.py`, `test_radard_bosch.py`, `test_py39_compat.py` and `test_longitudinal_planner.py`: 686 passed on the rebuilt `.so`.
  - ruff is clean on radard and the test file.
  - The settings row adds 7 ISC002 findings in `longitudinal.py`. They come from the same multi-line subtitle pattern the neighbouring rows use; that file had 104 findings at HEAD.
- **Not verified.** The toggle has not been exercised in the Galaxy UI on the device. Once it has, `initData.params` on the next route should carry `RangeVisionAssist`.
- **Default on (follow-up, owner: "Make it on by default for me").**
  - The key is now `{PERSISTENT, BOOL, "1", "0", 3}`: default on, stock value off. The manager writes defaults for missing keys at startup, so the first boot on this build turns it on. It then does something only because `RangeDerivedVrel` is also on; route 0000027e's `initData` has `RangeDerivedVrel` = 1 and `BoschARailInterval` = 1.
  - The params artifacts were rebuilt again with the same recipe.
    - `get_default_value("RangeVisionAssist")` is True and `get_stock_value` is False.
    - Still 857 keys, and `params_pyx.cpp` is byte-identical.
  - The rows now read "default on ... not yet driven".
  - The fallback in radard is unchanged: a missing key or a read error means off.
  - **This puts replay-only behaviour on the road by default.** Everything behind it is open-/closed-loop replay (STATUS 152). The first drives are its first road evidence. Check them with `vision_assist` in mind: an earlier onset on a curve lead, and no vision-unconfirmed dips.

## 154. Honda Bosch gas: the learned `gasfactor` no longer multiplies the hill feed-forward. Static tests and log statistics from one route only; not yet driven.

Owner, route 00000280 (the first drive on 63827356, with `RangeDerivedVrel` = 1 and `RangeVisionAssist` = 1): "When going up hill, specifically from segment 29 to 32, it makes the accel too aggressive which ends up overshooting, esp when it is coming up to a slower lead that got obscured by the hill."

- **Mechanism.** `carcontroller.py` computed the gas lookup input as `(accel + wind*windfactor + hill_brake - min_gas) * gasfactor + min_gas`, so the pitch feed-forward was scaled by `gasfactor` too.
  - `LongGasLearner` freezes above |pitch| 0.02 rad, so `gasfactor` is fitted on flat road only. The value on this route was 1.248, sitting at the 1.25 soft cap.
  - Extrapolating that factor to the hill term had never been checked.
- **Log evidence (route 280, segments 29–31, engaged, gas > 0 and unsaturated, no pedals, > 20 mph, |cmd| < 0.6, 0.25 s samples).** Mean aEgo − cmd, binned by the hill term:

  | Hill term (m/s²) | n | Mean aEgo − cmd (m/s²) |
  |---|---|---|
  | below 0.1 | 92 | −0.01 |
  | 0.1–0.3 | 131 | +0.04 |
  | 0.3–0.5 | 17 | +0.27 |
  | 0.5–0.7 | 32 | +0.10 |
  | 0.7–1.0 | 20 | +0.13 |

  The model `(gasfactor − 1) × hill` predicts +0.10 to +0.22 of that overshoot.
  - At 30:53–30:55 the car accelerated at +0.5 to +1.0 m/s² against an aTarget of about 0 and went to 51.4 mph on a 50 set. A slower lead then appeared at 80 m over the crest.
  - At 30:46 the error was about 0.58 at a 5.3° pitch. This change explains only about 0.23 of it; the rest is probably lag in the pitch estimate at the climb onset. That part is **not** addressed.
- **Change.** A new pure helper, `bosch_gas_lookup_accel(gas_pedal_force, hill_brake, gasfactor, min_gas)`, returns `(gas_pedal_force − hill_brake − min_gas) * gasfactor + min_gas + hill_brake`.
  - The flat-road request stays scaled and anchored at `min_gas` exactly as before. The hill term is added unscaled.
  - It is symmetric: a gasfactor below 1 no longer shrinks a downhill term either.
  - The learner is unchanged. It still sees the full `gas_pedal_force`, and it is frozen on real hills anyway.
- **Effect.** With `gasfactor` at 1.0 the output is identical to before. On flat road it is identical at any `gasfactor`. At 1.248 on a 4° climb (hill 0.69) the lookup input drops by 0.17 m/s², which is about 137 gas units on the Civic's linear 0–1600 table.
- **Tests.** `TestHillTermOutsideGasfactor` in `test_carcontroller_learners.py` covers flat road unchanged, hill added unscaled, nominal factor identical, downhill symmetric, and the `min_gas` anchor.
  - `opendbc/car/honda/tests`: 294 passed. `test_py39_compat.py` plus `test_longitudinal_planner.py`: 548 passed.
  - ruff shows 8 pre-existing findings in the two files and none on the changed lines.
- **Check on the next drive over the same hills (segments 29–32 of route 280).**
  - Uphill aEgo − cmd should sit near 0 rather than +0.1 to +0.3.
  - Watch for a small **under**shoot on steep climbs (the estimate is −0.05 to −0.08), which the planner should absorb.
  - Watch for no change on flat road.

Other route-280 bookmarks, reported to the owner with no change made:
- **4:29.** Stop-and-go creep of about 1 m.
- **7:29.** The lead slowed to turn; −3.8 m/s² briefly.
- **15:31 and 21:07.** A stopped car was revealed after the lead moved out.
  - The camera had it at about 100 m but estimated it at 15–30 mph.
  - No in-lane radar point existed until 67 and 75 m. At 21:06 track #49 appeared already railed at −13.5.
  - The result was a gentle-then-firm brake to −2.3 and −3.3 m/s².
  - No radar point was deleted. Collect more cases before designing anything.
- **24:35.** Cut-in at 30 m; the first-frame vRel of −6.6 gave a one-second tap.
- **26:11.** The lead braked hard (9 m of gap lost in 1 s); −3.2 m/s², with the radar lag about 1 s.

## 155. First drive on the STATUS 147/151 lateral values: route 00000280--d02d9c2f8e (owner: "I drove it with your latest fix and recommendation"). Limited road evidence: one drive, compared against five earlier routes on different roads.

The drive ran LowSpeed 115/50/50, Standard 125/95/100 and Highway 115/100/100 (P/I/F). Before, it was 100/50/50, 105/75/100 and 105/75/100 on 278 and 27a (Highway I 0 on 271–277). `HondaOverrideFadeUpSecs` also went from 1.0 to 0.5 on the same drive, so driver-press numbers are not a clean comparison.

Logged hands-off tracking, leaving out the first 5 s and ±3 s around lane changes and blinkers. Without that, a log-start artifact (a −66° target at t=0 while moving at 38 mph) and lane changes make up 75% of 280's Standard squared error:

| band | 280 | 271 / 276 / 277 / 278 / 27a |
|---|---|---|
| Standard: min / err / straight / curve \|e\|/\|des\| median | 18.5 / 0.45 / 0.39 / 0.045 | err 0.52–1.01, straight 0.45–0.63, curve 0.058–0.078 |
| LowSpeed: min / err / straight | 2.4 / 1.74 / 1.15 | err 3.0–16.7, straight 1.49–2.16 |
| Highway: min / err / straight | 1.7 / 0.28 / 0.28 | err 0.44–0.62, straight 0.39–0.53 |

- **Standard:** best on every measure. Sign changes per second are unchanged (0.33 against 0.30–0.33). Standard driver presses were 1.85/min against 0.09–2.98.
- **LowSpeed and Highway:** too few minutes to judge. Highway sign rate 0.34 is at the top of the earlier range (0.15–0.30), on 1.7 minutes.
- **Sim step on 280 alone:** proposes Standard 140/120 (fit 0.943, holdout 0.867) and holds LowSpeed. Not recommended yet: one route, and Standard is already the best measured. Collect two or three more drives on the current values first.

## 156. `UploadRlogs` toggle: rlogs upload alongside qlogs, including while driving (default off). Static tests and a params round-trip only; nothing has run on the device.

Owner: "make a toggle to enable uploading rlogs alongside with qlogs during a drive so that I dont have to manually go in and do it on konik stable. You can put the toggle in the data area that has the onroad upload option".

- **Behaviour** (`system/loggerd/uploader.py`, `next_file_to_upload`).
  - With the toggle on, `rlog`/`rlog.zst` becomes an automatic upload candidate. The key gets the `.zst` suffix that `step()` already appended for `rlog`.
  - Ordering: crash/boot first, then every pending qlog/qcamera, then rlogs oldest segment first. An rlog therefore never delays a qlog.
  - ~~rlogs never go on a metered connection.~~ Changed in the follow-up below: rlogs upload on any connection.
  - The segment being recorded carries a `.lock` and is skipped, as for qlogs. Each finished segment's rlog uploads during the drive, and the last one uploads once it closes.
  - `DisableOnroadUploads` still stops the uploader process onroad (`process_config.py`), rlogs included.
- **Key:** `{"UploadRlogs", {PERSISTENT, BOOL, "0", "0", 2, SETTINGS_SIMPLE}}`, placed next to `DisableOnroadUploads`.
  - Galaxy: Device Management, entry before `HigherBitrate`.
  - Device: system settings toggles, between "Disable Onroad Uploads" and "Disable Logging".
  - The key is also listed in `tools/StarPilot/feasibleparams.txt`.
- **Artifacts:** `params_pyx.so` and `libcommon.a` were rebuilt with the STATUS build recipe (larch64, pinned Cython 3.1.4).
  - Key count went 857 -> 858, and the only new key is `UploadRlogs`.
  - `params_pyx.cpp` is byte-identical, and in `libcommon.a` only `params.o` changed.
  - Default and stock values are both False. put/get round-trips.
  - `libcommon.a` shrank by 8.6 KB even though a key was added. The whole difference is in `params.o`'s static keys-map initializer (`__cxx_global_var_init`, -8,892 bytes, same clang 18.1.3); every other symbol is the same size. Loading both `.so` files, all 857 existing keys have identical default, stock, type and flag.
- **Tests (static):**
  - `test_uploader.py`: 11 passed, including 3 new tests: off by default, rlogs after qlogs, and locked-segment skip plus metered handling (inverted in the follow-up). The new tests fail against HEAD's uploader (negative control: 2 of the 3 fail; the off-by-default test passes on both, as it should).
  - Other suites: `test_device_settings_layout.py` 29 passed, `test_device_settings_frontend.py` 9, `test_process_config.py` 27, `test_py39_compat.py` 14.
  - ruff finds nothing new; the 13 findings in `system_settings.py` are all present at HEAD.
- **Not verified:**
  - Konik's `v1.4/upload_url` has not been seen accepting an `rlog.zst` key from the automatic path. It is the same key the manual request path uses.
  - rlogs are much larger than qlogs, and they now go over the owner's hotspot, so this costs phone data.
- **Follow-up: hotspot, and editability** (owner: "make sure the toggle editable. I will upload through my phone hotspot so internet speed isn't the issue").
  - **Metered limit removed for rlogs.** `get_network_metered` (`system/hardware/tici/hardware.py`) reports Wi-Fi as metered when NetworkManager says `METERED_YES` or `GUESS_YES`. NetworkManager guesses yes for phone hotspots. So with the first version, rlogs would never have gone up over the owner's hotspot unless `AlwaysAllowUploads` was on. `UploadRlogs` is already an explicit opt-in, so rlogs now upload whatever the metered flag says. Ordering is unchanged: qlogs and qcameras first. qcamera's own metered rule is untouched.
  - The test now asserts that the rlog is returned on both metered and unmetered connections. 49 passed across `test_uploader.py` and the two device-settings suites.
  - **Galaxy editability, checked statically.** `PUT /api/params` accepts any key in the params library that is not in `EXCLUDED_KEYS`. Against the rebuilt `.so`, `UploadRlogs` is present and not excluded. Its default is a bool and the layout says `data_type: bool`. Tuning level is 2, the same as `DisableOnroadUploads`, and put/get round-trips. The entry shows under the **Device Settings** (`DeviceManagement`) parent toggle once that parent is on and expanded, or through search.
  - **On the device,** the toggle has no `is_enabled` gate, so it is always tappable. "Disable Uploads", and "Disable Onroad Uploads" while driving, still stop the uploader process and so override it.
- **Follow-up: default ON** (owner: "Ship with it on for me for now").
  - The key is now `{PERSISTENT, BOOL, "1", "0", 2, SETTINGS_SIMPLE}`: default on, stock value off.
  - On a device, an unset key reads True. `openpilot.common.params.Params.get_bool` asks the library with `return_default=True`, and that is the wrapper the uploader and the settings UI use. This was checked on an empty params dir: `UploadRlogs` True, `RangeVisionAssist` True, `DisableOnroadUploads` False. The raw `params_pyx` `get_bool` still returns False for an unset key. The manager's startup loop does not write defaults (`manager.py:1270`); it only restores keys from the params cache. So a device that has explicitly stored `0` keeps it off.
  - Artifacts were rebuilt with the same recipe. There are still 858 keys, and the only metadata change is `UploadRlogs` default False -> True (stock False). `params_pyx.cpp` is byte-identical. In `libcommon.a` only `params.o` changed.
  - Tests: the upstream uploader tests go through the wrapper, so the new default made them upload rlogs (4 failed). `TestUploader.setup_method` now pins `UploadRlogs` off for them. The off-state test is renamed `test_rlogs_not_uploaded_when_off` and sets False explicitly. 90 passed across the uploader, device-settings, process-config and py39 suites. Static only.
- **Follow-up, route `00000284--1109db7c4c` (owner: "i dont think it uploaded, i had to upload manually"). Log statistics only.**
  - The device ran `90487307` with `UploadRlogs=1`, `AlwaysAllowUploads=1` and the hotspot link, so the uploader saw `metered: false`. The toggle worked: rlogs went up the whole drive at 0.4–0.9 MB/s.
  - They were the wrong rlogs. `list_upload_files` walks routes oldest first, and the first toggle-on drive had a backlog of never-uploaded rlogs from older routes. The rlogs of segments 20 and 29 (fetched from Konik after the manual upload) show `upload_success` for `00000266--f766f599f0--16..19` and then `00000267--e83a1fa671--5`. That is about ten backlog rlogs in 9 min, and none were from 284. Each 284 qlog and qcamera still went up as its segment closed.
  - First fix (`3de45706`): newest route first. Superseded the same day on owner request: "limit to only rlogs of the current drive", "if the car turns off … keep going until it's finished", "if i start a new drive immediately after … continue the previous drive, then move on to the current drive".
  - Now (`system/loggerd/rlog_upload.py`): the route in progress when the uploader first sees the toggle on becomes the anchor, stored as xattr `user.rlog_upload_from` on the log root. rlogs from the anchor route onward go up oldest first, so an unfinished previous drive completes before the next one. Older routes (the pre-toggle backlog) are never sent. Toggle off clears the anchor, and turning it back on re-anchors at the newest drive. Without xattr support, it falls back to the newest drive only. qlogs and qcameras still go first.
  - Shutdown hold (`power_monitoring.py`): when `offroad_timeout` fires, `UploadRlogs` is on, and rlogs in the window are still unmarked, the timer is held. The check is uncached and runs every 30 s, and the hold is capped at `RLOG_UPLOAD_HOLD_MAX_S` = 2 h past the timer. Low voltage and battery-exhausted are never held. The owner's timer is 30 h (`DeviceShutdown`=30 on 284), so this is a guard for shorter settings. The uploader only makes progress while the device has a link: a phone hotspot that leaves with the driver stops it until the next drive, and the drive then resumes at the unfinished route.
  - Tests: `test_upload_rlogs_previous_drive_then_current_never_backlog`, `test_upload_rlogs_off_clears_anchor`, and 5 hold cases in `test_power_monitoring.py`. Uploader, power-monitoring and deleter suites: 40 passed. `hardwared`, `deleter`, `process_config` and `starpilot_variables` import cleanly; a first draft had imported the uploader into `power_monitoring` and made a cycle through `starpilot_variables`. Static only, not run on the device.
  - Separate and not fixed: after each qlog upload, Konik calls athena `uploadFilesToUrls` for `<segment>/rlog`. A "whole route" request asks for `rlog.bz2`. The device file is `rlog.zst`, and athena only tries the name as given and with `.zst` stripped, so every one of these requests fails (`athena.uploadFilesToUrls.failed`, about once a minute on 284). This is a server-side naming mismatch. It does not block the uploader path above.

## 157. Turn stutter at the last bookmark on 00000283--fe4e75f88b (segment 33, about 2003–2008 s from the start of the route): a limit cycle between the driver-override flag and the torque fade. Log statistics only; no change has been made.

Owner: "I marked some bad stuttering while turning." The car was at about 25 → 14 mph at the start of a hard right turn (target angle 0 → −168°).

**Mechanism.** For about 2 s the wheel stayed near 0° while the command grew from −0.2 to −0.45. `STEER_TORQUE_SENSOR` read +1400 to +2480, opposing the command: hands holding the wheel against the push. Both the `NrdrDriverOverrideThreshold` and `NrdrOverrideThresholdCenterBoost` thresholds were 2000, and `NrdrIncreaseOverrideTolerance` was off, so the raw flag drove the ramp in `carcontroller._update_steering_torque`. The cycle:
1. The torque sensor crosses 2000, and `steeringPressed` is set for about 3 frames.
2. `HondaOverrideFadeDownSecs` 0.2 lowers the ramp by 0.05 per frame, so output falls about 25%.
3. The sensor unloads to about 1400 within 30 ms, and the flag clears.
4. `HondaOverrideFadeUpSecs` 0.5 raises the ramp by 0.02 per frame, torque rebuilds past 2000, and the flag sets again.

The period is about 0.11 s (about 9 Hz), and the ramp swings between 0.6 and 1.0 on each cycle.

**How common.** An episode is at least 4 press onsets within 1 s while engaged. Most are in low-speed turns.

| route | thresholds (driver/centre) | fade down / up (s) | episodes / engaged min |
|---|---|---|---|
| 277 | 2000/2000 | 0 / 1.0 | 8 / 19 |
| 278 | 2000/2000 | 0.2 / 1.0 | 4 / 15 |
| 27a | 2000/2000 | 0 / 1.0 | 3 / 10 |
| 280 | 2000/2000 | 0.2 / 0.5 | 10 / 25 |
| 283 | 2000/2000 | 0.2 / 0.5 | 23 / 27 |

Route 283 has about twice the rate, but it also has more turns, so the 1.0 → 0.5 fade-up change is not shown to be the cause.

**Not a lateral-gain problem.** The flag is reading the car's own torque reacting against the hands. The sim has no hands model and cannot reproduce this.

**Candidate fix (not implemented; the owner decides):** add release hysteresis on the override flag in the command path. Hold "pressed" until the torque sensor falls below about 0.75× the threshold, or for at least about 0.3 s. The override would then fade once and stay faded while the hands hold, instead of chopping at 9 Hz. That only makes the override stickier, never weaker. Raising the threshold, or turning on `NrdrIncreaseOverrideTolerance` (which doubles it), is excluded by the owner's standing rule.

## 158. Release hysteresis on the driver-override flag (the STATUS 157 fix). Implemented; static tests and an open-loop replay only. Not driven.

The owner asked for it ("Yeah lets test it").

**Change** (`opendbc_repo/opendbc/car/honda/carcontroller.py`, `hold_steering_pressed`, used in `_update_steering_torque`):
- It only applies on the raw-flag path, with `NrdrIncreaseOverrideTolerance` off. The filtered path is unchanged.
- A raw `steeringPressed` sets the latch. The latch clears only when both of these are true:
  - no raw press for `OVERRIDE_RELEASE_HOLD_S` = 0.3 s;
  - |`steeringTorque`| is below `OVERRIDE_RELEASE_FRAC` = 0.75 × the active threshold. `carstate` now stores that threshold as `CS.steer_threshold`, including the centre boost and doubling rules.
- The latch resets whenever lateral control is inactive.
- The constants are hardcoded with an evidence comment. There are no new params, and no threshold changes.
- The change can only extend an override, never start one.
- `CS.out.steeringPressed` itself, and everything else that reads it, is unchanged.

**Static.** Four new tests in `test_honda.py` (`TestHondaSteeringCommandFidelity`):
- A 3-frames-on / 8-frames-off flicker at 2300/1600 no longer rebuilds the ramp.
- The latch releases after the hold once the sensor unloads.
- The latch stays held at 0.8× the threshold and releases at 0.7×.
- Without a threshold, the release is time-only.

The Honda test directory passes (312) and `test_py39_compat` passes.

**Replay (open loop).** The logged raw flag and sensor drive the real `_update_steering_torque`, using each route's fade params and threshold 2000. "Old" is the raw flag.

| route | engaged min | flicker episodes old → new | press onsets old → new | ramp travel/min old → new | time ramp<1 old → new | longest hold past last raw press |
|---|---|---|---|---|---|---|
| 277 | 19.1 | 8 → 0 | 97 → 46 | 4.6 → 3.3 | 7.0% → 7.8% | 0.80 s |
| 278 | 15.2 | 4 → 0 | 78 → 31 | 2.6 → 2.2 | 3.6% → 4.9% | 0.94 s |
| 27a | 9.9 | 3 → 0 | 52 → 25 | 4.3 → 3.5 | 6.2% → 7.1% | 1.20 s |
| 280 | 24.9 | 10 → 0 | 113 → 27 | 2.0 → 1.8 | 1.3% → 2.3% | 0.89 s |
| 283 | 27.3 | 23 → 0 | 216 → 36 | 3.3 → 2.3 | 2.2% → 3.5% | 0.96 s |

**What the owner will feel at the 283 bookmark.** This is the turn-in, 2000.0–2001.7 s in extract time. The sensor reads +1800 to +2300 while the command goes −0.3 to −1.0.
- Old: the ramp chops between 0.6 and 1.0 at about 9 Hz.
- New: the ramp fades to 0 once, in 0.2 s, because `HondaOverrideTorqueScale` is 0. The hands own the wheel for about 2 s. The latch releases at 2002.0 s, and the ramp fades back to full by 2002.5 s with the turn about −90° in.

So the stutter becomes one clean handback followed by a 0.5 s re-take mid-turn.

**Caveats.**
- Open loop: in the car, the sensor partly reads the car's own push. With the push faded out, the sensor would unload sooner, so the real hold is likely shorter than the replay shows.
- A slower cycle is possible if the hands keep resisting after the re-take: 0.2 s fade, then at least 0.3 s hold, then 0.5 s rebuild, or about 1 Hz. Replay cannot rule that out.
- If a full handback feels too abrupt, `HondaOverrideTorqueScale` > 0 keeps partial assist while held. That is an owner param; it was not changed.

## 159. First drive with the STATUS 158 override hysteresis: route 00000284--1109db7c4c. Limited road evidence: one drive, 11.6 engaged minutes. The 9 Hz chop is gone, but a slower, deeper pump appeared in one right turn.

The device ran `90487307` (clean): hysteresis on, fade down/up 0.2/0.5 s, `HondaOverrideTorqueScale` 0, threshold 2000.

**The four bookmarks** (1360, 1495, 1531, 1598 s) are not steering events: straight road (|angle| ≤ 4°), no presses, two hard stops. These are radar/longitudinal bookmarks.

**Override behaviour**, from the logs. Out/cmd is the delivered ratio; a "dip" is a fall below 0.8.

| route | engaged min | min in turns >30° | raw flicker episodes | fast chop (≥3 dips/1 s) | slow pump (≥3 dips/4 s) |
|---|---|---|---|---|---|
| 277 | 19.1 | 0.81 | 8 | 8 | 17 |
| 280 | 24.9 | 0.30 | 10 | 7 | 8 |
| 283 | 27.3 | 0.44 | 23 | 17 | 16 |
| 284 | 11.6 | 0.77 | 1 | 2 | 10 |

**The slow pump, 1629–1636 s.** A right turn at about 13 mph with the blinker on, wheel 0 → −149°.
- The command sits saturated at −1.0. The torque sensor reads +1300 to +2000 against it, while the wheel moves *with* the command: hands damping, not steering against the car.
- Each brief raw press lets the latch take the output to 0. The latch releases after 0.3 s and the output rebuilds (fade-up 0.5 s). At about 0.5 of the command the sensor crosses 2000 again.
- Result: 8 cuts to zero in about 6.5 s, roughly 1.2 Hz, output swinging 0 ↔ 0.55. This is the cycle STATUS 158 flagged as possible. The old cycle was 9 Hz at 0.6 ↔ 1.0; this one is slower but deeper.
- 1117–1120 s (right turn, 13 mph) shows two such cycles.
- Genuine overrides are clean: at 1637–1642 s the hands turn the wheel against the command to +164° and the output stays at 0 throughout; 1681 s is similar.

**Levers, none applied:**
- `HondaOverrideFadeUpSecs` 1.0 halves the rebuild rate. That probably slows the cycle to under 1 Hz, but the crossing still happens at the same torque.
- `HondaOverrideTorqueScale` > 0 (e.g. 0.3–0.5) floors the cut. The pump in this turn would shrink to roughly scale ↔ 0.55. The cost: during genuine overrides like 1637 s, the car keeps pushing at that fraction.
- Code: stop counting "opposing torque while the wheel moves with the command" as an override (a damping signature). This changes when the override fires, so it needs the owner's decision.

**Addendum, owner feedback.** "The stuttering is at 27:56. Turns at 21:49 was pretty smooth overall."
- **27:56** (1676 s): a right turn at about 20 mph. The model's desired angle leads to −45° while the hands hold the wheel near +2°, and the torque sensor rises to +1800–2000 against the command.
  - Two raw presses of 3 and 2 frames (30 and 20 ms), peaking at 2039 and 2029, each cut the output to 0: −0.23 → 0 → −0.50 → 0 → −0.94 within 1.4 s, while the command ramped to −1.0.
  - The genuine override that follows (1680.93 s: 98 frames, peak 2853) is clean.
- **21:49** (1309 s): the hands were light (sensor −350 at most), there were no presses, and delivered = command throughout.
- **Press lengths.** Every cut in the 27:09–27:16 and 27:56 turns was triggered by a 1–5 frame blip peaking at 2005–2300. On 283 and 280, the median press is also 3 frames.
- **Candidate** (not implemented; it relaxes the override, so it's the owner's decision): debounce the press onset. Require the raw flag for about 8 consecutive frames, or fire instantly above about 1.25× the threshold.

## 160. Onset debounce on the driver-override flag (the STATUS 159 candidate, owner-approved). Implemented; static tests and an open-loop replay only. Not driven.

**Change** (`carcontroller.py`, raw `steeringPressed` path only, `debounce_steering_pressed`):
- A press counts only after `OVERRIDE_ONSET_FRAMES` = 6 frames (60 ms) on a leaky counter (+1 per raw frame, −1 per frame without one, so a one-frame dropout does not restart it).
- It counts on the first frame when |steeringTorque| ≥ `OVERRIDE_INSTANT_FRAC` = 1.25 × the threshold (2500 at 2000).
- Once the override is held, any raw frame refreshes the STATUS 158 release hold.
- No params were added or changed. The `NrdrIncreaseOverrideTolerance` path is untouched.

**Choosing N and the instant level.** Replay over routes 277, 278, 27a, 280, 283 and 284: 447 blips of ≤ 5 frames and 84 genuine presses of ≥ 0.2 s. The owner asked that the car not fight a takeover, so detection delay was weighted over filtering.

| frames | instant | blips still triggering | takeover delay median / p90 / max | takeovers instant |
|---|---|---|---|---|
| 8 | 1.25× | 6% | 60 / 70 / 70 ms | 14% |
| **6** | **1.25×** | **7%** | **50 / 50 / 50 ms** | **14%** |
| 6 | 1.15× | 13% | 25 / 50 / 50 ms | 23% |
| 5 | 1.10× | 35% | 10 / 40 ms | 32% |

**Open-loop replay of 284** (logged torque and press drive the real `_update_steering_torque`; the hands do not react, so this cannot show the closed loop). "Fight" is the time from the raw press onset to delivered < 10% of the command.

| config | cuts < 0.8 (whole route) | 27:09–27:16 turn | 27:56 turn | fight at 18:37 / 28:01 takeovers |
|---|---|---|---|---|
| as driven (fade-down 0.2) | 25 | 5 | 1 | 178 / 182 ms |
| debounce, fade-down 0.2 | 14 | 0 | 0 | 228 / 234 ms |
| debounce, fade-down 0 | 14 | 0 | 0 | 70 / 58 ms |

- Most of the time the car spends pushing against a takeover comes from `HondaOverrideFadeDownSecs` 0.2, not from the debounce. With the blips filtered, an instant cut (fade-down 0) no longer produces the chop it did on 283. That setting is the owner's to make; this commit does not write it.
- Keep `HondaOverrideTorqueScale` at 0: any floor means the car keeps pushing through a takeover.
- **Risk:** a takeover at 2000–2500 now waits 60 ms before the fade begins. A blip that lasts 6 frames or more, or peaks above 2500, still cuts (7% of blips on these routes).

**Correction (same day), from the logged `STEERING_CONTROL` frames on 284.** The owner runs `HondaDriverAssistDuringOverride` = 0. With it off, `lkas_active` drops as soon as the override is held, and `create_steering_control` sends `STEER_TORQUE` 0 with `STEER_TORQUE_REQUEST` 0 from that frame on.
- On 284 the car sent 0 torque on the very frame of each raw press (1676.19 s, 1676.86 s), and ramped back in over the fade-up (0.5 s) once the hold released. `HondaOverrideFadeDownSecs` never reaches the EPS on this configuration.
- The "fight" column above therefore overstates what was sent. Only the 6-frame onset window (0 ms for presses at 2500 or more) is added pushing time. Driven 284 had none.
- Retract the fade-down 0 recommendation: it is moot while the toggle is off.
- Turning the toggle on would keep the request bit set through a takeover, shaping torque only by the fade-down (0.2 s) and `HondaOverrideTorqueScale`. That adds pushing against the driver.

## 161. EPS telemetry is on the owner's CAN (for porting James's firmware-inversion feedforward). Log statistics only; nothing changed.

James's branch `JamesL787/openpilot` `vfn-controller-shadow` (fd815ef3) adds `LatControlClarityEps`: a feedforward that inverts the EPS firmware law (P + D + KFF45 on target R5 minus filtered rate R6), plus vfn's angle PID on the residual. It is Clarity-only, and its constants come from a Clarity Tracker3200 build. The owner's C020 image has the same P row, KFF45 and Norm1650, but a different torque table, tracker and E4 scale. James says he wrote the C020 telemetry and that the calibration is "close to clarity but not 100% identical". The owner believes the flashed tracker is 4500.

Route 00000284, segments 27–28, bus 1:
- 0x6A0–0x6A3 arrive at 50 Hz with live data. These IDs are not in the Honda DBCs; they match "Telem6A3" in the Clarity image names.
- **0x6A2 bytes 0–1** (signed, big-endian) = −169.9 counts per deg/s of `steeringRateDeg`, corr −0.994 at 0 lag. This is the R6 rate term; the Clarity constant is −138.6. If R6 scales with the tracker from 3200, −170 points nearer 4000 (−173) than 4500 (−195). That is unconfirmed; James knows the scaling.
- 0x6A3 bytes 5–6 track driver torque (corr −0.88).
- The R5 target word is **not** found. No 16- or 32-bit field correlates above 0.61 with the sent E4, either raw or mapped through the owner's torque table. The layout may differ from the Clarity's.
- The Civic sends E4 up to ±4096; the Clarity code assumes 3840.

**Needed before a port:** James's C020 telemetry layout (which word is R5), the E4→key scaling on C020, and the R6 scale at the flashed tracker. Then refit the column load model on the owner's routes. Run it in shadow (logged, not applied) and score it against the telemetry R5 before it steers.

**Addendum: telemetry decoded from the firmware** (owner: "use the xray rwd"). Static disassembly of the Trk4500 image (SH-2A, big-endian, capstone 5; the Trk4000 image differs only in the tracker word and checksums), checked against route 284 segments 27–28.
- **The hook.** 0x1d8f8 jumps to new code at 0x4c2d4. That code copies 16 RAM words, 4 per frame, into 0x6A0–0x6A3 (mailboxes 51–54), then returns to 0x1d900.
- **The control law.** The patched call at 0x29006 runs the stock law at 0x292a0 and then new code at 0x4c3c4, which adds `45 * R5 >> 10` (KFF45).
  - R5 is read from `*(gbr+300)+6`. R6 is at gbr+100 = 0xfff88a28 (gbr 0xfff889c4).
  - The law stores X (clamped to ±65536) at 0xfff8a970, and `err = R5 - R6 - X` at 0xfff8a974 (and clamped at 0xfff8a978).

| frame | bytes | RAM | meaning |
|---|---|---|---|
| 0x6A0 | 0–1 | 0xfff801b2 | not identified |
| 0x6A0 | 2–3 | 0xfff8a97e | not identified |
| 0x6A0 | 4–7 | 0xfff8a978 | err, clamped (s32) |
| 0x6A1 | 0–3 | 0xfff8a970 | X (s32) |
| 0x6A1 | 4–7 | 0xfff8a974 | err (s32) |
| 0x6A2 | 0–1 | 0xfff88a28 | **R6** (s16): −169.9 counts per deg/s, corr −0.994 |
| 0x6A2 | 2–7 | 0xfff887c0, 0xfff8701a, 0xfff8aac4 | not identified |
| 0x6A3 | 0–7 | 0xfff801d8, 0xfff898ae, 0xfff898b0, 0xfff898c6 | 898b0 (bytes 4–5) tracks driver torque; the rest not identified |

- **R5 = err + X + R6** (all from 0x6A1 and 0x6A2 in the same frame). Against the E4 we sent: corr **0.997**, R5 ≈ **7.4 × E4** at a 0–20 ms lag. The Clarity value is 7.7. The fit is linear over the logged range (E4 up to ±4096).
- The tracker value cannot be read from this data.

**Addendum: what the tracker word does** (owner: James says tracker differences don't matter; why?). Static disassembly of the C020 Trk4500 image.
- **0x3a080 is a first-order low-pass**, state in Q15: `s += alpha * (x - (s >> 15))`, where alpha is the constant passed in, per 32768. Its DC gain is 1.
- **R6 is built at 0x28e82:**
  - x = `1650 * raw_rate >> 8`, where raw_rate is at 0xfff89850 and 1650 is the Norm word inside 0x29ef8.
  - x is filtered by 0x3a080 with alpha = the tracker word 0x137ee, clamped to ±32765 (0x137f0), and stored at 0xfff88a28. That is R6, the word telemetry sends in 0x6A2 bytes 0–1.
- The tracker is therefore **the bandwidth of the rate filter, not a gain.** R6 per deg/s in steady state is the same at any tracker.
- At the 1 kHz loop James reports (not verified here), the filter time constant is about 15.4 ms at stock 1996, 7.2 ms at 4000 and 6.3 ms at 4500. So 4000 vs 4500 is about 1 ms of extra lag in the firmware's own damping path. That is invisible at openpilot's 100 Hz and under the feedforward's 100–150 ms smoothing. **James is right for the feedforward.**
- **Retracted** from this entry: "−170 points nearer 4000 than 4500". The tracker does not scale R6. The Clarity −138.6 vs Civic −169.9 difference must come from raw_rate scaling on the column, so the Civic port uses the measured −169.9 rather than a scaled Clarity constant.
- **The tracker still matters for the EPS's own stability.** A faster rate filter adds phase margin to the firmware's damping loop, and the eps_tools README records a ~29 Hz hands-off limit cycle when tracker alpha was raised on a high-D CR-V tune. That concerns hands-off buzz, not the feedforward calibration.

## 162. Longitudinal on 00000284--1109db7c4c (chill, RangeDerivedVrel and RangeVisionAssist on): the 22:38 false brake, and a wider young-track range bound. Implemented; static tests and replay only. Not driven.

**Bookmarks (log statistics).**
- **22:38 (false brake).** At 22:35.4 the lead became a new track 17 at ~79 m. It was born with U11 -10.5, and the D-043 coast held that value for ~1.5 s, while its own range went 79 -> 83 -> 80 m. Vision (p 1.00) was at own speed. Chill aTarget reached -1.47 and aEgo -1.77. D-053 played no part: the replay with RangeDerivedVrel off is identical. The STATUS 149 young-track bound missed it twice:
  - the fit residual was 0.56-1.28 m against a cap of 0.6 (range noise at 80 m);
  - the hold outlasted the 1.0 s age window.
- **25:29 (real).** The lead braked hard: the camera showed it going from 32 to 12 mph in about 2 s. Radar vRel lagged the camera by ~1 s. aTarget reached -3.5 and aEgo -3.86, and the car stopped 23.7 m behind.
- **26:36 (over-delivery).** A real lead at 40 m, closing about 3 m/s. aTarget was -0.51 but aEgo reached -1.10. This is the known brake over-delivery (option C, open).
- **24:52 (not a brake).** A cut-in at 22 m, opening at +3.9 m/s. aTarget stayed at +0.6.

**Change.** In `Track.young_flat_range_vrel_floor`:
- A fit with residual <= `YOUNG_TRACK_MAX_RESIDUAL_M` (0.6) keeps the original floor exactly: slope - 3.
- A fit with residual up to `YOUNG_TRACK_NOISY_MAX_RESIDUAL_M` (2.0) now also bounds. Its floor is lowered by `YOUNG_TRACK_NOISY_SE_K` (2) standard errors of the slope, so noise allows more closing rather than removing it.
- `YOUNG_TRACK_MAX_AGE_S` goes from 1.0 to 2.0.
- The vision gate, the rate cap (|slope| <= 6) and reporting-only publication are unchanged. No point is deleted and the KF is untouched.

**Replay** (35 routes: the 32-route fleet plus 280, 283 and 284, rb283 harness, old rule vs new):
- 113 frames publish less closing, and 0 publish more.
- The only output change over 0.3 m/s² is 284 1357.4, where the minimum aTarget goes -1.46 -> -0.88.
- The other 11 changed runs move out by <= 0.02. This includes 27a 514 (the STATUS 149 case), which stays at -1.38.
- No -1.5 crossing is later.

**Vision bound on the D-053 correction (tried and dropped, not committed).** The idea was to cap the D-053 correction at vision closing + 3 m/s when a p >= 0.9 model lead matches the track. It fixes 283 9:12 (-3.15 -> -2.30), but it also softened real approaches, so it was dropped:

| rule | softened real approaches |
|---|---|
| model range 0.85-1.35 x dRel | 258 3383 (-2.10 -> -1.62; range really fell 12 m in 2 s), 026b 1709 (-2.34 -> -1.88, 0.25 s later), 280 1503 (-2.02 -> -1.62) |
| model range >= 1.13 x dRel | 280 1503 (-1.95 -> -1.54) |

At 280 1503 the radar range fell 107 -> 64 m in 5 s and the camera's own range fell too, but the model's speed said closing was only 2-4 m/s. The model's lead speed understates real closing often enough that it cannot bound radar closing on its own.

## 163. The other 00000284--1109db7c4c longitudinal bookmarks (26:36, 25:29, 24:52): nothing changed in code. Log decode and replay evidence only.

Follows item 162. Peter asked for the remaining 284 items to be addressed.

**1. 26:36, a gentle brake that felt too firm: the car, not the command, and not systematic.**
- The lead was a new radar track, #3 at 44.8 m, against the camera's 54 m. The radar closing speed was −3, against the camera's ~2.1.
- `aTarget` and `carControl.actuators.accel` were both −0.51, and the command went out unchanged (item 71 point 1).
- Pitch was ~0, yet `aEgo` went from −0.76 to −1.16 over 1594.1-1595.1 s. The onset was gas-to-brake: the previous command was +0.55, at 21.6 m/s.
- Census of all 575 brake onsets on the 35-route set (fleet_routes.txt plus 280, 283 and 284):
  - An onset is the command crossing −0.2 from above −0.05 within 1 s, followed by 3 s of long control with no pedal.
  - Plateau is the mean of `aEgo(t+0.35)` minus the command while the command is within 80% of its minimum.
  - Peak is min `aEgo(t+0.35)` minus min command.
  - Negative means the car braked harder than asked.

| command min | n | plateau median | peak median |
|---|---|---|---|
| −0.2 to −0.4 | 163 | +0.05 | −0.21 |
| −0.4 to −0.7 | 204 | +0.02 | −0.28 |
| −0.7 to −1.0 | 76 | −0.17 | −0.44 |
| −1.0 to −1.5 | 75 | −0.14 | −0.41 |
| −1.5 and deeper | 57 | −0.34 | −0.73 |

- Mild commands are tracked on average. A −0.4 to −0.7 command settles within +0.02 of the request, and gas-to-brake onsets are no worse (+0.06, n = 43).
- 26:36 (onset 26:32.9) is a transient dip: plateau −0.34, peak −0.64. That is about the worst quarter of mild gas-to-brake onsets (26% have a peak at or below −0.64), and 8% of all mild onsets.
- Scaling mild commands down would make the typical mild brake too weak in order to trim an occasional ~0.5 s dip, so no compensation was added.
- The deep bins agree with item 72: over-brake grows with depth. Item 71 option 3 and the 2026-09-23 decision stand.

**2. 25:29, a hard brake for a real lead.**
- The camera lead dropped from 32 to 12 mph in about 2 s. `aTarget` reached −3.5 and `aEgo` −3.86, and the car stopped 23.7 m behind.
- The radar vRel trailed the camera by about 1 s. That is filter lag on a real deceleration. Shortening it means changing lead arbitration (D-048), and the stop here still left a 23.7 m margin. No change.

**3. 24:52, a cut-in at 22 m that the car did not brake for.**
- The cut-in car was opening at +3.9 m/s, so the planner kept +0.6. This is expected: a faster car merging ahead needs no braking.
- Left as is unless Peter says it felt wrong.

Scripts (in /tmp, not committed): `/tmp/ob/mild.py` builds the time series, and `/tmp/ob/ana.py` runs the census.

## 164. James's firmware-inversion feedforward ported in SHADOW for the Civic Bosch C020 (owner's image, tracker 4500). Logs only, never steers. Static tests, telemetry statistics and an open-loop replay on 00000284--1109db7c4c only. Not driven.

**What it is.** Upstream is JamesL787/openpilot `vfn-controller-shadow`. The shadow commit is 52618f42; the feedforward is as of fd815ef3.
- `selfdrive/controls/lib/nrdr_eps_firmware_ff.py` is upstream's feedforward line for line. The firmware tables moved into an `EpsFirmwareCalibration`; `CLARITY_A020` reproduces upstream exactly.
- Upstream's applied controller (`ClarityEpsLateralCore`, `LatControlClarityEps`) is not ported.
- `LatControlPID` runs the feedforward every frame on a modified-EPS Clarity or Civic Bosch, as 52618f42 did. It is logged on `starpilotLateralState` (100 Hz, rlog) and never added to the output.
- Fields use upstream's final names and ordinals: `epsFfActive` @8, `epsFfFeedforward` @9, `epsFfR5` @10, `epsFfLoad` @11, `epsFfDesiredRate` @12, `epsFfWeight` @13. `epsFfWeight` is always 0 here.
- Any exception in the shadow is caught and logged once. A test checks the command is bit-identical with the shadow on, off, or raising.

**C020 calibration.** Read from the flashed `.rwd` and checked against the bus-1 telemetry (R5 = err + X + R6, STATUS 161) on segments 0-29 of 284.

| Item | Value | Evidence |
|---|---|---|
| E4 per unit output | 4096 | `torqueBP/V` = [0, 4096] identity |
| Command map | row 1: axis 0x13806, R5 0x13872 | The seven rows share the R5 row [0 ... 30000] and differ only in the key axis. Row 1 matches R5 at E4 + 10 ms to 385 / 94 / 31 counts RMS at 5-11, 11-20 and >20 m/s. Row 0: 417 / 200 / 179. Rows 2-6: 119-1987. What selects a row is not decoded. |
| Key clamp | 1663 (0x137F2) | The largest R5 on 284 is 28497, which is row 1 at key 1663. |
| P row, KFF, Norm | Clarity's (117..265 at 0x13BC0, KFF45, 1650) | Image name and dump |
| R6 | -173 counts per deg/s | Fit over all engaged frames of 284 (-169.9 on segments 27-28 alone). The tracker does not enter (STATUS 161). |
| Speed envelope | 1774 to 100 km/h, 1552 at 120, 1219 at 150, 1108 from 160 (axis 0x13644, values 0x136C2) | **Not checked.** 284 never passed 89 km/h, and what `SpeedClamp0` disables is not decoded. |

- New fact: on the Civic, E4 4096 is key 1773, past the 1663 clamp. Commands above |0.938| all land on the same R5. On the Clarity, 3840 is key 1662, so the clamp is never reached.
- Kp is still indexed by the command key. Row 1 is not linear (19.5 R5 per key at the bottom, 17.4 at the top), so for the C020 Kp is built piecewise over |R5| through the map rather than upstream's constant 18.04 per key. The quadratic solve is unchanged; the tests cover the round trip and inversion.

**The load model is still the Clarity's (route 352 fit).**
- A refit on 284 lost to it in leave-one-segment-out: R² 0.49-0.52 against 0.51-0.56. It won only above 11 m/s (0.49 vs 0.37).
- 284 is one drive, mostly straight. Two parking-lot segments (0 and 9, |angle| up to 338°) fit badly under either model.
- The shadow logs are what a Civic refit needs.

**Open-loop replay on 284.** Feed the logged desired angle (minus `angleOffsetDeg`), vEgo and roll through the shadow, then compare its R5 with the R5 the car ran. Engaged frames only, no driver press, v > 2 m/s.

| | All | Turning (\|angle\| > 2°) | Turning < 25 mph | Turning > 25 mph |
|---|---|---|---|---|
| C020 calibration | 0.52 | 0.53 | 0.52 | 0.74 |
| Clarity calibration | 0.54 | 0.56 | 0.54 | 0.75 |

- James's Clarity figure is 0.79 on turning frames of held-out route 353.
- The Clarity calibration scores slightly higher here only because the Clarity load model was fitted together with the Clarity damping scale. The firmware constants are the C020's by telemetry.
- The gap is the load model, which is the reason to log before any apply.

**Not done.** Applying it (upstream's core, fade-in and join gate), a Civic load refit, and the >100 km/h envelope. No param keys and no params artifact were added.

Pre-existing failures, not touched: `test_latcontrol` Bolt/Palisade taper (2), `test_torqued_lat_accel_offset` (1), `test_starpilot_planner` (1). The collection errors in `test_controlsd`, `test_turn_lead`, `test_longitudinal_planner` and `test_nissan_leaf_fallback` are DeprecationWarnings.

Scripts (in /tmp, not committed): `/tmp/c020_rows.py`, `/tmp/c020_loadfit*.py`, `/tmp/c020_shadow_replay.py`, `/tmp/c020_score.py`.

## 165. The STATUS 164 firmware-inversion feedforward can now steer, behind a toggle (owner-requested, default off). Static tests and an open-loop replay on 00000284--1109db7c4c only. Not driven.

**Toggle.** `NrdrLatEpsFirmwareFF` is "EPS Firmware Feedforward (Test)" under Lateral Tune (advanced) in the Galaxy and the device's NRDR tuning page. It is a bool, default off, and applies to the modified-EPS Clarity and Civic Bosch.
- The params artifacts were rebuilt: larch64, pinned Cython 3.1.4, 858 → 859 keys.
- The key is in `lat_tune_analyzer.TUNING_KEYS`. At off it stays out of the fingerprint (`FINGERPRINT_ADDED_OFF`), so earlier routes do not re-hash.

**What it does (`LatControlPID`, modified EPS only).**
- **Join gate.** The gate is upstream's `ClarityEpsLateralCore`: `FF_JOIN_ERROR_DEG` 10, `FF_FADE_IN_S` 0.5, `FF_SPEED_BP` [2, 4] m/s.
  - It joins once |angle error| < 10°, then ramps to full over 0.5 s.
  - A driver press drops the weight to 0 at once, and so does v < 2 m/s. The press is the modified-EPS override detector, with its onset debounce.
  - After that, it rejoins through the same gate.
- **Output.** `output = P·p + I·i + D + (1−w)·F·f_scale + w·eps_ff + (1−w)·rate_ff·slew`.
  - The firmware feedforward replaces the kf feedforward and the desired-rate feedforward. As upstream, it is not trimmed by `LatFScale*`.
  - P, I, the center taper, the testing-ground scale and alpha, and the clip are unchanged.
- **Shadow.** It is now updated before the active check, so the log is identical either way. `epsFfWeight` records the weight actually applied.
- **Failure.** Any exception in the feedforward, or a non-finite output, gives weight 0. The command is then bit-identical to toggle-off (tested).

**Replay: the size of the term it adds (284, engaged, no press, v > 2 m/s).** `F` is the logged kf feedforward before `f_scale`; `eff` is the C020 firmware feedforward at full weight.

| | rms F | rms eff | rms command | corr(eff, command) |
|---|---|---|---|---|
| Turning, < 25 mph | 0.004 | 0.236 | 0.439 | 0.50 |
| Turning, > 25 mph | 0.010 | 0.078 | 0.067 | 0.86 |
| Straight (\|des\| ≤ 2°) | 0.002 | 0.049 | 0.044 | 0.65 |

- **On the Civic the kf feedforward is almost nothing.** The owner's command is carried by P and I. The toggle therefore **adds** a term about the size of today's whole command in turns. It does not swap like for like.
- **Expect the P/I loop to rebalance.** I will unwind and P will see a smaller or reversed error. Until it does, expect more turn-in torque and a chance of overshoot on the first turns.
- **Below 25 mph the load model tracks the command least** (corr 0.50; R² 0.52 in STATUS 164). That is where it is most likely to feel wrong.
- **Frame-to-frame roughness is not the problem.** The rms step of eff is 0.0020, against 0.0036 for the logged command.
- **Not scaled by LatF.** `LatFScale*` does not trim this term. If it is too strong, the knobs are LatP/I, or turn it off.

**Tests.** `test_nrdr_eps_firmware_ff.py`: 102 pass, 7 of them new.
- The gate: join, fade, press, speed.
- Applied on both cars: the command changes and the weight reaches 1.
- A press takes the weight to 0, and it rejoins afterwards.
- An applied failure gives the toggle-off command exactly.

`test_lat_tune_analyzer`, `test_py39_compat` and the Galaxy layout/frontend tests pass. `test_latcontrol` has the 2 pre-existing Bolt/Palisade failures and nothing new.

**Not done.** A Civic load refit, the >100 km/h envelope, and any closed-loop simulation of the PI rebalancing.

Scripts (in /tmp, not committed): `/tmp/epsff/ffmag.py`, `/tmp/epsff/ffcmp.py`.

## 166. `NrdrLatEpsFirmwareFF` now runs James's controller itself, `LatControlClarityEps`, generalized to the Civic Bosch C020. This supersedes the 165 crossfade (owner: "match exactly how James had it, but for the Civic"). Static tests and an open-loop replay on 00000284--1109db7c4c only. Not driven.

**What changed.**
- **Controller selection.** With the toggle on, `controlsd` builds `LatControlClarityEps` (upstream JamesL787 8c3a3fd8 / fd815ef3) instead of `LatControlPID`.
  - This applies on the modified-EPS Clarity and Civic Bosch when the lateral tune is `pid`.
  - The toggle is read once, when controlsd starts, so a change applies on the next drive.
  - Upstream selects it unconditionally on the Clarity. Here the toggle gates both cars.
- **`common/pid.py`** is upstream's. `update()` gains `integrator_gain_scale` and `reset_integrator`, and both defaults leave every other caller unchanged.
- **`LatControlPID` is back to STATUS 164.** It logs the firmware feedforward in shadow and never applies it. The 165 crossfade and `eps_ff_weight` are gone.
- **`ClarityEpsLateralCore` and `speed_band`** are in `nrdr_eps_firmware_ff.py`, verbatim, except:
  - the calibration and the P/I trims are constructor arguments;
  - the Civic gets `CIVIC_BOSCH_C020` (STATUS 164) and its own trims.

**The controller, as upstream.**
- **Error:** `error = des + offset − angle`.
- **Gains:** a PID on CP's kp/ki, with limits ±1.
- **Feedforward:** the firmware-inversion feedforward, through the join gate (10°, 0.5 s fade, 2–4 m/s; a press or v < 2 sets it to 0).
- **Integrator:** frozen on steer-limited, a press, or v < 2. Its rate is scaled per band by I_SCALE, and it is reset below 2 m/s.
- **Output:** `clip(p·P_SCALE[band] + i + d + ff)`, then a per-band output low-pass (τ 0.07 / 0.05 / 0.01 s), then clip. Bands split at 25 and 50 mph.
- **Desired angle:** the shell computes it from the firmware VGR or the sr curve (`NrdrLatUseFirmwareVgr`), rate-limits it by `NrdrLatAngleRateLimit`, and uses the modified-EPS press detector.

**Civic specifics.**
- **Trims.** The trims are fixed at what the owner drove on 284 (initData):
  - P (1.15, 1.25, 1.15)
  - I (0.75, 0.95, 1.00)
  - Clarity's upstream trims (P 1.25/1.00/1.25, I 0.70/0.95/0.35) stay for the Clarity.
- **Gains.** The Civic Bosch modified gains are the same numbers as James's (kpV 0.018/0.024/0.048/0.060, kiV 0.006/0.008/0.016/0.020).
- **Output low-pass.** It uses upstream's constant τ. The `HondaTorqueOutput*` keys do not exist on this branch, and `HondaLpfTau*` (a target filter here) is not used by this controller.

**What does not apply while it is on.** This is upstream's behaviour, not a port gap:
- `LatP/I/FScale*` and `HondaLateralPidKp/KiScale`
- the kf and rate feedforward
- the center taper
- target smoothing
- the override fade
- the testing-ground scale
- every other `LatControlPID` shaping

The carcontroller does not filter modified-EPS torque, on this branch as upstream.

**Open-loop replay (284, engaged, no press, v > 2 m/s; logged inputs, so the error is the one the old controller left).**

| | rms James | rms logged | corr | James ff / p / i | logged p / i |
|---|---|---|---|---|---|
| Turning, < 25 mph | 0.539 | 0.439 | 0.91 | 0.121 / 0.638 / 0.230 | 0.556 / 0.056 |
| Turning, > 25 mph | 0.136 | 0.067 | 0.83 | 0.078 / 0.046 / 0.070 | 0.036 / 0.043 |
| Straight | 0.126 | 0.044 | 0.52 | 0.05 / 0.03–0.08 / 0.09–0.16 | 0.03–0.07 / 0.02–0.04 |

- **The excess is mostly the integrator,** integrating error that closed-loop feedforward would have removed.
- **Open loop cannot size the closed-loop command.** The replay shows the terms have the expected shape and scale, nothing more.
- **Feedforward weight.** The mean is 0.91, and it is at full weight 88 % of the time.
- **Roughness.** The rms step is 0.0030 against 0.0036 logged, and the 5–8 Hz energy ratio is 0.92.

**Tests.** `test_nrdr_eps_firmware_ff.py`: 121 pass.
- James's core tests are included verbatim.
- A Civic core test checks the banded PID on the Civic trims.
- Toggle selection on both cars; off, stock, and other Hondas keep `LatControlPID`.
- The Civic uses its own calibration and trims.
- Settings are read.
- It steers, logs and rests.
- The rate limit holds.

With `test_lat_tune_analyzer` and `test_py39_compat`, 199 pass. `test_latcontrol` has only the 2 pre-existing Bolt/Palisade failures. Ruff is clean on the new files.

**Not done.** A Civic load refit, the >100 km/h envelope, and a closed-loop simulation. The first drive should expect more turn-in torque below 25 mph than today.

Script (in /tmp, not committed): `/tmp/epsff/core_replay.py`.

## 167. Closed-loop simulation of `LatControlClarityEps` on the Civic C020 plant, six routes. It tracks better at 25 mph and above, the same below 25 mph, and dithers about twice as much everywhere. Sim evidence only. Not driven.

**What was added.** `tools/lateral/lat_pid_sim.py` has a new controller kind, `clarity_eps`.
- It builds the car's `LatControlClarityEps` through `use_clarity_eps_controller` with `NrdrLatEpsFirmwareFF` = 1, so the Civic gets `CIVIC_BOSCH_C020` and its trims exactly as on the car.
- It runs through the same `CarControllerSteer` stage and fitted plant (`tools/lateral/plants/civic_bosch_c020.json`) as the `pid` kind.
- It refuses a stock EPS or a non-pid tune.
- As on the car, `LatP/I/FScale*` and `HondaLateralPidKp/KiScale` do not reach it. A test checks this: the output is bit-identical when they change, and the `pid` output moves.
- Tests: 3 new tests in `test_lat_pid_sim_torque.py`.
  - The wiring test checks the controller, the calibration, the FF joining to weight 1.0, the log and the target.
  - The slider-isolation test.
  - The refusal test, which also checks that params are restored.
- The synthetic-step convergence check was dropped. On the synthetic step, **both** `pid` and `clarity_eps` limit-cycle at ±1, with the test plant and with the C020 plant, at 6, 15 and 25 m/s. The synthetic harness is not representative; it was not investigated further. Convergence is scored on routes instead.

**How the sim is read.**
- The plant integrates the delivered command only while the car is engaged and hands-off, and resyncs to the log elsewhere.
- Metrics use the owner-facing report's definitions, per band.
- `pid` in the sim is the regular path on each route's logged tuning. It is the check that the plant is credible.
  - At 25–50 mph it reproduces the logged err rms within ~0.1° on 5 of 6 routes (280: 0.73 sim vs 0.97 logged).
  - Below 25 mph it reproduces within ~1.5° on 5 of 6 routes. On 284 it does not (9.0° sim vs 16.3° logged), so 284's low band is weak evidence.

**Err rms, degrees (sign changes per second on straights, 0.15° hysteresis).**

| route | < 25 mph logged / pid / clarity | 25–50 logged / pid / clarity | > 50 logged / pid / clarity |
|---|---|---|---|
| 284 | 16.31 / 9.04 / 9.65 (0.38 / 0.49 / 1.16) | 0.70 / 0.64 / 0.44 (0.30 / 0.38 / 0.54) | 0.39 / 0.50 / 0.30 (0.28 / 0.26 / 0.32) |
| 280 | 6.09 / 6.14 / 6.10 (0.41 / 0.46 / 1.01) | 0.97 / 0.73 / 0.61 (0.33 / 0.38 / 0.62) | 0.28 / 0.29 / 0.22 (0.34 / 0.34 / 0.45) |
| 277 | 11.98 / 12.85 / 13.24 (0.43 / 0.31 / 1.10) | 0.94 / 0.95 / 0.72 (0.32 / 0.33 / 0.57) | 0.67 / 0.83 / 0.47 (0.23 / 0.21 / 0.43) |
| 276 | 16.71 / 16.79 / 18.17 (0.29 / 0.46 / 0.81) | 0.88 / 0.89 / 0.50 (0.33 / 0.32 / 0.57) | 0.52 / 0.62 / 0.30 (0.15 / 0.14 / 0.30) |
| 278 | 18.22 / 16.91 / 18.36 (0.45 / 0.53 / 1.17) | 0.54 / 0.56 / 0.35 (0.30 / 0.31 / 0.51) | 0.46 / 0.56 / 0.36 (0.30 / 0.25 / 0.32) |
| 27a | 16.30 / 16.55 / 17.14 (0.25 / 0.38 / 1.02) | 0.77 / 0.82 / 0.50 (0.30 / 0.28 / 0.45) | too little data |

**Findings.**
- **25–50 mph: better.**
  - Err rms is 17–44 % lower than sim `pid` on all six routes.
  - The curve actual/desired ratio is 1.01–1.06, against 0.94–0.98.
  - Lag is 0.00–0.24 s, against 0.15–0.33 s.
  - The ratio is slightly above 1 on 284 (1.064, 8 s of curve), which is mild overshoot.
- **> 50 mph: better.** Err rms is 25–45 % lower on five routes, and the curve ratio is 1.00 on 284 and 0.94 on 277, against 0.93 and 0.71.
- **Below 25 mph: not better on err rms** (−0.04 to +1.45° against `pid`). It is better on turn entry: entry actual/target is 0.69–0.87 against 0.45–0.71, and the curve ratio is 0.93–1.01 against 0.83–0.97. Low-speed err rms is dominated by large transients the plant only roughly reproduces.
- **Dither is the thing to watch.** On straights, sign changes are about 2× `pid` at 25–50 mph and 2–3× below 25 mph.
  - The 1 s high-passed error on near-straights (|des| < 5°) is 40–90 % higher below 25 mph (for example 284: 1.24° against 0.88°) and ~40–100 % higher at 25–50 mph.
  - The rms step of the delivered command is ~1.7× below 25 mph (0.22–0.30 against 0.13–0.17 /s), and the same or lower above.
  - p95 |err| on straights is still lower at 25–50 mph (0.62–0.81° against 0.93–1.49°). So above 25 mph this is small, fast wandering around a tighter mean. Below 25 mph it is a real increase in wheel activity.
  - Whether the car shows it depends on what the fitted plant leaves out: friction and the tracker. Read it as a prediction to check, not a result.

**Limits.**
- The plant was fitted on PID-driven data (the regular path).
- It is a black box. It cannot represent the EPS tracker (Trk4000 vs Trk4500), and it has no driver.
- Desired curvature is exogenous: the model does not react to the controller's path.
- The FF load constants are still James's Clarity fit. Nothing here refits them.

**First drive with the toggle on: what to check.**
- **Below 25 mph:** wheel dither on straights and after turn exit, and the turn-in amount (the sim expects more entry and less lag).
- **25–50 mph:** overshoot on curves (ratio > 1).
- **Logs:** `epsFfWeight` and the P/I/FF split, against 284.

**Tests.** 192 pass (`tools/lateral/tests/`, `test_nrdr_eps_firmware_ff.py`, `test_py39_compat`). Ruff is clean on the new lines. The one UP031 at `lat_pid_sim.py:511` pre-exists at HEAD.

**Scripts** (in /tmp, not committed):
- `/tmp/epsff/cl_sim.py` runs the six-route comparison.
- `/tmp/epsff/dither.py` computes the high-pass and command-step figures.
- 284 was extracted to `/tmp/epsff/00000284--1109db7c4c.npz`. No routes were fetched.

## 171. First drive with the STATUS 160 onset debounce: route 00000285--1cd7a85309. Limited road evidence: one short drive, 7.0 engaged minutes, mostly intersection turns. No code change.

**Setup.** The device ran `f71648c5` (clean) with `NrdrLatEpsFirmwareFF` off, so this is the NRDR PID.
- Threshold 2000 with centre boost 2000.
- `HondaOverrideFadeDownSecs` 0.0 (moot, see 160's correction), fade-up 0.5.
- Torque scale 0, `HondaDriverAssistDuringOverride` 0.
- LatP 115/125/115, LatI 75/95/100, LatF 50/115/115.
- The drive has no bookmarks.

**The debounce runs as built.** Replaying `_update_steering_torque` on the logged inputs with the debounce matches the delivered/command ratio on 94.6 % of frames, against 92.5 % without it.
- Only 2 blips of ≤ 5 frames started from full output (403.5 s, 643.5 s), and both still cut, probably via the leaky counter.
- On 284 the same test finds 3.

**What still cuts: 60–190 ms presses just over threshold.** Raw presses by length, 285 vs 284:

| raw press length | 285 | 284 |
|---|---|---|
| 1–5 frames | 27 | 34 |
| 6–19 frames | 37 | 8 |
| ≥ 20 frames | 18 | 13 |

- The 6–19 frame presses peak at 2020–2200.
- In 27 of the 37, the torque opposes the command. In 14, the wheel is still moving with the command.
- Most sit at |angle| < 10° while the target leads by 10–30°. That is hands holding against turn-in or unwind, not blips.
- There are 85 dips below 0.8 in 7.0 min (12.1/min). On 284 it was 53 in 11.6 min (4.6/min). This drive has more turning: 1.25 min above 30° against 0.77.

Clusters of three or more cuts:

| route time | cuts | notes |
|---|---|---|
| 0:39 | 5 | 9 mph |
| 1:21 | 4 | |
| 3:41–3:54 | 11 | 17 mph, turn to 123° |
| 6:19 | 9 | |
| 6:30–6:44 | 12 | |
| 7:52 | 3 | |
| 9:06–9:20 | 11 | 20 mph, turn to 58° |
| 9:58 | 3 | |
| 10:44–10:51 | 7 | |

Most of the clusters are with the blinker on.

**Levers, none applied (the owner's call; the threshold is not to be raised):**
- **Longer onset window for torque between 2000 and 2500, instant above 2500.** At about 20 frames it would filter most of these. The cost: a light takeover waits up to 200 ms before the cut.
- **A damping signature.** Opposing torque while the wheel still moves with the command does not count as a press. This changes when an override fires.
- **Slower fade-up.** This softens the rebuild, but does not change how often the car cuts.

Scripts (in /tmp, not committed): `/tmp/r285.py`, `/tmp/r285b.py`, `/tmp/r285c.py`.

## 168. First drive with `LatControlClarityEps` on: 00000286--ba543e3a3e (build f71648c5, `NrdrLatEpsFirmwareFF` 1). It tracks tighter than any PID drive, with 2–3× the straight-line dither the STATUS 167 sim predicted, and a feedforward roll offset the integrator cancels. Limited road evidence (one drive) and log decode; nothing changed in code.

**The drive.** 12.9 min engaged, 10.9 min hands-off.
- initData confirms build f71648c5 with `NrdrLatEpsFirmwareFF` = 1 and `NrdrLatUseFirmwareVgr` = 1, and the controller logged `epsFf*` all drive.
- Feedforward weight: mean 0.92 below 25 mph (0.89 of frames at full weight), 1.00 above.
- 7 bookmarks: 5:58.2, 6:27.1, 6:38.1, 6:43.6, 10:05.7, 12:14.3 and 12:52.4. Across ±10 s of each, the error is under 1°, with no press and no saturation.
  - 5:58 is a lane change.
  - 10:05, 12:14 and 12:52 are decelerations from ~50 mph.
  - What the owner marked them for is not known yet.

**Tracking (logged, hands-off; STATUS 167 definitions).**

| band | 286 err rms | 284 (PID) err rms | 286 straight rms | 284 straight rms | 286 curve ratio | 284 curve ratio | 286 sign changes /s (0.15°) | 284 sign changes /s (0.15°) |
|---|---|---|---|---|---|---|---|---|
| < 25 mph | 11.33 | 16.31 | 2.46 | 2.07 | 0.951 | 0.785 | 2.3 (0.95) | 0.7 (0.38) |
| 25–50 | 0.73 | 0.70 | 0.27 | 0.61 | 0.985 (4 s) | 1.007 | 2.0 (0.54) | 0.9 (0.30) |
| > 50 | 0.19 | 0.39 | 0.19 | 0.39 | – | 0.943 | 2.9 (0.46) | 1.0 (0.28) |

- On straights at 25 mph and above, 286 has the lowest error of any logged route on this car. The 25–50 band has only 4 s of curve.
- Below 25 mph it follows turns much better (curve ratio 0.95 against 0.79 on 284, lag 0.14 s against 0.24 s).

**The sim prediction held.** The STATUS 167 `clarity_eps` sim, run on 286's own inputs, matches the logged drive:
- Sign changes: 2.2 / 1.9 / 1.8 per s simulated, against 2.3 / 2.0 / 2.9 logged.
- 1 s high-passed error below 25 mph: 1.39° simulated, 1.37° logged.
- Command step rms below 25 mph: 0.35 simulated, 0.38 logged.
- So the dither is real, and it is the controller, not the plant model. On the highway it is fast and small (straight rms 0.19°). Below 25 mph the command moves about twice as fast as on PID drives (0.38 against 0.14–0.41 /s).

**Driver presses while engaged.**

| band | 286 | PID routes (276, 277, 278, 27a, 280, 284) |
|---|---|---|
| < 25 mph | 10.0 /min | 7.9–27 /min |
| 25–50 | 0.6 /min | 0.1–3.0 /min |
| > 50 | 0 | 0 on five routes, 6.9 /min on 277 |

286 is inside the PID range in every band.

**Feedforward roll offset.**
- On highway near-straights (|des| < 1.5°), the feedforward averages +0.057 while the integrator holds −0.027 and P is ~0. The net +0.029 is what PID drives settle at (+0.02–0.03 on 30 routes).
- A least-squares fit puts the offset on roll, at 1.01 command per rad.
- liveParameters roll on this car is +0.03–0.05 rad on every route since 1ba, far more than road crown. The mount or roll estimate is biased, and James's Clarity `LOAD_KROLL` turns that bias into ~2× the torque the Civic needs.
- The integrator absorbs it. It will lag wherever roll changes (ramps, crowned turns). This belongs to the Civic load refit: a Civic `LOAD_KROLL` / `LOAD_BIAS`, not a change to the Clarity's.

**Not changed.** No code, no params.
- Candidates, owner's call:
  - the Civic roll/bias refit above;
  - a longer low-speed output τ or lower low-speed P trim for the dither;
  - making those tunable.
- Each needs another drive to judge.

Scripts (in /tmp, not committed): `/tmp/epsff/r286_*.py`, `roll_all.py`, `press.py`.

## 169. Longitudinal on 00000286--ba543e3a3e (build f71648c5, chill 89%), the first drive with the item 162 young-track bound: it never fired, and none of the 7 bookmarks is a false brake. Nothing changed in code. Log decode and replay only.

- **Item 162 bound.** A radard replay of the whole route, with the bound off against on, differs on 0 frames. This drive neither tests nor exercises the fix.
- **10:03 and 12:09: −3.0 brakes for real slow traffic.**
  - Radar first held each lead at 95-116 m, closing on the −13.5 U11 rail (tracks 50 and 15). Radar and camera ranges both fell 13-18 m/s, so the rail under-read the closing.
  - The camera under-read the lead's closing too (it read 29-41 mph at 12:06).
  - Braking began within 0.5 s of the radar pick-up.
  - At 10:08 the car was 25 m behind a ~9 mph lead. By 12:13 it was 43 m back, level with a 24 mph lead.
  - At 9:57.7 the lead was a 126 m radar-only leadTwo (−15.5) with modelProb 0.1, not taken as leadOne, which is by design.
  - Bookmarks 10:05.7 and 12:14.3 fall at the ends of these brakes.
- **12:47-12:53: −2.2 on a vision-only lead.**
  - liveTracks had no point in path from 35 to 100 m, with only 1-4 points per sweep. The model's range jumped 54-78 m.
  - There were real slow cars: the adjacent-lane radar points closed at −8.
  - Radar misses of this kind also occur on 284 (segment 20 has a point near the vision lead on only 11% of frames). They are not new.
  - Bookmark 12:52.4.
- **6:15-6:43, the speed wobble following track 36 at ~55 mph and 47-75 m.** Bookmarks 6:27.1, 6:38.1 and 6:43.6.
  - Radar and camera are on the same car. The yRel magnitude matches, 4.5 m on a curve converging to 0.
  - Radar range and vRel agree with each other: +4.5 m/s opening at 6:33, then −4.5 m/s closing at 6:35 (54.4 to 47.0 m). The camera range dipped 53.4 to 49.6 m at the same moment.
  - aLeadK went from +3.4 to −5.8 in 1.5 s, while the model's lead accel stayed −0.1. The MPC hit the chill floor of −1.0 twice, at 6:22.5 and 6:35.0.
  - At 6:35 the command flipped from +0.70 to −1.00 in 1 s. The car delivered −1.78 for about 1 s, 0.8 beyond the command (the item 163 gas-to-brake transient), and speed fell from 56.9 to 50.7 mph.
  - Bounding aLeadK by the model's accel (a camera cross-check, proposed in conversation and not implemented) would have removed this. It would also remove real lead brakes, because the model's lead accel sits near 0 even when the lead slows (12:08: model −0.0 while range fell 16 m/s). One event is not enough to tune on (rule 5).
- **5:58.2**: a lane change, with the lead dropped and +0.8 acceleration. Nothing longitudinal.

## 170. The wheel wobble the owner felt resuming from a stop on 00000286--ba543e3a3e comes from `LatControlClarityEps`'s feedforward below ~12 m/s. Nothing changed in code. Log decode, replay and closed-loop sim only.

**What the log shows.** Measured as the 0.4–3 Hz band rms of the wheel angle, engaged, no press, no lane change, |angle| and |desired| under 12°, held for 1.5 s.

| speed (m/s) | 286 (ClarityEps) | PID drives 284, 280, 278, 277, 276, 27a |
|---|---|---|
| 2–5 | 1.44° | 0.22–0.44° |
| 5–8 | 1.38° | 0.21–0.38° |
| 8–12 | 0.90° | 0.14–0.30° |
| 12–20 | 0.16° | 0.11–0.16° |

- On 286 the wheel moves more than its target in this band (ang > des). On every PID drive it moves less.
- The model's desired angle in the same band is also 1.5–2× the PID drives' (1.44 vs 0.56–0.80° at 2–5 m/s). The model reacts to the car's wobble, which closes a loop the sim does not have.
- **Resume 9:01.4, no press.** The wheel runs a ~1 Hz ±3.5° oscillation from 3 to 10 m/s, in phase with the desired angle, and settles by 6 s.
  - The feedforward joins at 2–4 m/s and is the largest term, up to +0.13 against P +0.09.
  - I is ~0.
- **Resumes 0:25.5 and 1:34.8, with the driver holding the wheel at 140–330°.**
  - The command swings ±1 within 2.5 s after lateral re-engages at ~1 m/s, driven by P on a 100–250° error.
  - PID drives have the same kind of event: 284 at 2:21, 276 at 1:54 and 21:17, 278 at 1:51. Their fast wheel motion measures 1.3–2.0°, against 2.9° and 1.5° here. So this is not specific to ClarityEps.
- The carcontroller's override fade-up applies to both controllers.

**Sim (tools/lateral/lat_pid_sim, C020 plant, routes 284, 280, 278, 277 and 286; mean over routes).** In each row one setting was changed, in the sim only. Wobble is the metric above, in degrees. Tracking metrics are the <25 mph hands-off ones from STATUS 167.

| variant | wob 2–5 | wob 5–8 | wob 8–12 | wob 12–20 | low err rms | low entry ratio | low lag s | std err rms |
|---|---|---|---|---|---|---|---|---|
| PID (logged tune) | 0.55 | 0.27 | 0.16 | 0.10 | 11.12 | 0.61 | 0.23 | 0.70 |
| ClarityEps as built | 0.87 | 0.83 | 0.50 | 0.20 | 11.51 | 0.82 | 0.21 | 0.54 |
| feedforward off | 0.57 | 0.31 | 0.22 | 0.12 | 12.22 | 0.66 | 0.27 | 0.71 |
| feedforward ×0.7 below 25 mph | 0.75 | 0.63 | 0.41 | 0.19 | 11.53 | 0.77 | 0.23 | 0.54 |
| feedforward ×0.5 below 25 mph | 0.68 | 0.52 | 0.37 | 0.19 | 11.64 | 0.74 | 0.24 | 0.55 |
| FF_SPEED_BP 4–8 m/s (from 2–4) | 0.59 | 0.58 | 0.50 | 0.20 | 11.82 | 0.75 | 0.24 | 0.54 |
| FF_SPEED_BP 6–10 m/s | 0.57 | 0.37 | 0.43 | 0.20 | 12.12 | 0.70 | 0.27 | 0.55 |
| LEAD_S 0 | 0.87 | 0.82 | 0.49 | 0.19 | 11.51 | 0.82 | 0.21 | 0.54 |
| DESIRED_RATE_TAU 0.30 | 0.82 | 0.73 | 0.44 | 0.18 | 11.72 | 0.82 | 0.22 | 0.56 |
| low-band P ×0.8 | 0.83 | 0.75 | 0.46 | 0.20 | 11.92 | 0.79 | 0.22 | 0.54 |
| output LPF τ 0.15 below 25 mph | 0.84 | 0.83 | 0.50 | 0.20 | 11.85 | 0.81 | 0.22 | 0.54 |
| 0.3 s low-pass on the FF's desired angle, <25 mph | 0.78 | 0.67 | 0.42 | 0.19 | 11.89 | 0.80 | 0.23 | 0.55 |
| 0.15 s low-pass on the whole target | 0.76 | 0.68 | 0.40 | 0.16 | 12.80 | 0.70 | 0.29 | 0.67 |

- Turning the feedforward off returns the wobble to PID level. Wobble scales with the feedforward's gain.
- The rate path (LEAD_S, DESIRED_RATE_TAU), P, and the output LPF barely move it.
- Mechanism: the firmware-inversion feedforward makes the EPS follow the desired angle almost 1:1, including the model's low-speed wiggle, which PID attenuates. On the road the model then reacts to the resulting yaw.
- No setting gets PID-level wobble and keeps the turn-entry gain (0.82 vs PID 0.61). It is a trade.

**Candidates, not applied (design change on James's controller; needs the owner's go-ahead and a drive):**
1. FF_SPEED_BP 2–4 → 4–8 m/s (Civic only). This targets the resume itself: at 2–5 m/s the wobble falls to PID level (0.59 vs 0.55), and low-speed turn entry keeps 0.75.
2. Feedforward ×0.5–0.7 in the <25 mph band, for the 5–12 m/s wobble. Entry drops to 0.74–0.77.
3. Both together.

The sim wobble for ClarityEps is 2–3×. On 286 the road shows 4–6×, because of the model loop. The sim ranks the levers but understates the problem, so any fix needs a drive to judge.

Scratch scripts: /tmp/epsff/lowspd_wobble.py, sim_wobble.py, variants.py and r286_resume2.py. Not committed.

## 172. Owner's 285 turn notes, and a LowSpeed P sweep (owner: "try 2 first, then 1"). Renumbered from a duplicate 168; commit d6eafad6's "STATUS 167" is 171 and e686f02a's "STATUS 168" is this entry. Log decode and closed-loop sim only; no code or param change.

**The owner's turns.** No stutter was reported. The notes were: 7:06 R "did not commit", 7:58 R "too wild", 9:15 L "undershoots", 10:01 R "wide".
- **7:12 R** (5.8 mph, wheel to −250°): the command is saturated at −1.0 and the wheel trails the target by 35–43°. This is an authority limit.
- **7:58 R** (5 mph): the wheel trails by 13–20° with the command at only −0.3 to −0.47 (P only; I and F are about 0). At 8:01.8 the driver cranks it (−3472) past the target by about 30°, and the override cuts for about 2.5 s.
- **10:01 R:** a +2099 press at turn-in (9:57.6) cuts the torque for about 0.4 s while the error is 46–49°. The turn-in is late.
- **9:15 L:** the override is held from 9:15.8 to 9:19 while the driver's torque (+2600 to +3300) is in the **same** direction as the command. The car sends 0 and the driver steers alone.
- **Across drives (turns with |des| > 45°):** 285 is not worse than 284 or 280. Under 12 mph the mean |err| is 30° (284: 42°, 280: 61°); from 12 to 25 mph it is 16° (284: 21°, 280: 13°).
- **Cause of the lag:** the Civic's kf feedforward is about 0 below 25 mph, and `NrdrLatRateFF` is 0.

**LowSpeed P sweep** (plant `civic_bosch_c020.json`, closed loop, hands-off frames, low band < 25 mph, err rms / curve ratio / sign changes per s):

| route | log | P 115 (driven) | P 130 | P 140 | P 150 |
|---|---|---|---|---|---|
| 285 | 12.48 / 0.864 / 0.8 | 10.02 / 0.931 / 0.9 | 9.54 / 0.937 / 1.0 | 9.29 / 0.941 / 1.1 | 9.08 / 0.945 / 1.1 |
| 284 | 16.31 / 0.785 / 0.7 | 9.04 / 0.962 / 1.4 | 8.80 / 0.963 / 1.4 | 8.68 / 0.964 / 1.5 | 8.57 / 0.965 / 1.5 |
| 280 | 6.09 / 0.826 / 0.9 | 6.14 / 0.834 / 1.3 | 5.91 / 0.846 / 1.2 | 5.78 / 0.855 / 1.2 | 5.67 / 0.866 / 1.3 |

- **Trust.** The sim is trusted on 280 (it matches the log). On 285 it reads the error 20 % low and the curve ratio 0.07 high. On 284 it is untrusted (9.0 against 16.3), because the real car trails more than the plant does in sharp slow turns.
- **Gain from 115 → 130.** Error drops 3–4 %, the curve ratio rises 0.001–0.012, and sign changes rise by up to 0.1/s. From 130 to 150 the gain is smaller for each step and the wiggle rises.
- **Suggestion:** `LatPScaleLowSpeed` 130, consistent with the STATUS 151 grid. Expect a small improvement in partial-command turns like 7:58. It cannot help 7:12 (already saturated), 9:15 or 10:01 (override cuts). Those need the override change or a feedforward.

## 173. Branch `clarity-eps-testing` (commit 0f27431d; not merged here): James's controller's feedforward is gated by the desired wheel angle, faded in from 10° to 30° of |desired| (`FF_ANGLE_GATE_DEG`). `FF_SPEED_BP` is back to upstream's [2, 4] m/s. This is the fix for the STATUS 170 wobble and applies to both the Clarity and the Civic. Static tests and closed-loop sim only; not driven.

- **History.** This replaces the branch's first fix, `FF_SPEED_BP` [2, 4] → [4, 8] (commit 2c7518a2, which numbered its entry 171 before the PID session's renumber took 171). The owner asked for that fix to be undone and redone with the PID session's gate. The PID session found the gate in sim inside `LatControlPID`, using the STATUS 165 feedforward.
- **Why the gate works.** Near straight, the feedforward makes the EPS follow the model's small desired-angle wiggle almost 1:1. In a turn it is what gets the wheel round. The [4, 8] fix removed it by speed, turns included. The gate removes it by angle, so turns keep it.
- **The change** is in `selfdrive/controls/lib/nrdr_eps_firmware_ff.py`, `ClarityEpsLateralCore.update`: `ff_weight = ramp × interp(v, [2, 4]) × interp(|desired_angle_no_offset|, [10, 30])`. The gate does not reset the join ramp. Leaving a turn fades the feedforward out, and the next turn brings it straight back.
- **Tests.** `test_feedforward_is_gated_by_the_desired_angle` is new. The `_hold` helper's default is now 40° so the existing weight tests run with the gate open. The sim wiring test steps to curvature 0.02 (past the gate) and checks weight 0 while straight. 179 pass (`test_nrdr_eps_firmware_ff.py` and `tools/lateral/tests/`).
- **Closed-loop sim** (C020 plant; script /tmp/epsff/gate_eps.py). Wobble is the 0.4–3 Hz wheel rms (STATUS 170 mask) by speed band: 2–5 / 5–8 / 8–12 / 12–20 m/s. Turn error is the mean |error| on |desired| > 45°, hands off, under 12 mph / 12–25 mph.

| route | variant | wobble (°) | turn error (°) |
|---|---|---|---|
| 286 | PID | 1.27 / 0.27 / 0.24 / 0.07 | 23.2 / 14.2 |
| 286 | James, [2, 4], no gate (as driven) | 1.44 / 1.40 / 0.96 / 0.17 | 16.7 / 12.4 |
| 286 | James, [4, 8] (first fix) | 1.30 / 1.01 / 0.95 / 0.17 | 21.7 / 13.2 |
| 286 | **James, gate** | 1.28 / 0.34 / 0.30 / 0.09 | 16.9 / 12.5 |
| 285 | PID / no gate / gate | 0.58 / 0.37 / 0.20 / 0.12 · 1.02 / 0.82 / 0.42 / 0.26 · **0.60 / 0.43 / 0.21 / 0.14** | 17.3 / 13.6 · 17.0 / 13.0 · **17.0 / 13.0** |
| 284 | PID / no gate / gate | 0.48 / 0.33 / 0.13 / 0.11 · 1.00 / 0.90 / 0.31 / 0.21 · **0.49 / 0.36 / 0.16 / 0.11** | 24.2 / 8.5 · 25.8 / 8.5 · **25.9 / 8.6** |
| 280 | PID / no gate / gate | 0.25 / 0.19 / 0.15 / 0.10 · 0.54 / 0.65 / 0.37 / 0.21 · **0.27 / 0.23 / 0.17 / 0.14** | 15.6 / 14.0 · 17.2 / 12.1 · **17.3 / 12.2** |

- **Result.** With the gate, wobble is at PID's level in every band on all four routes, and turn error is the same as the ungated controller's. Adding [4, 8] on top of the gate changes nothing except losing turn error on 285 and 286 (18.0 and 21.6 under 12 mph), so it is not used.
- **Not tested.**
  - The sim resyncs to the log below ~4 m/s. The 2–5 m/s column therefore barely moves: 286 reads 1.28 for the gate against 1.27 for PID. Pulling away from a stop, the owner's actual symptom, needs a drive.
  - The sim has no model-in-the-loop, so it under-reads the road wobble (STATUS 170).
  - James's Clarity (A020 calibration) has not been simulated or driven with the gate.
- `ns-bosch-radar-testing` keeps upstream's ungated [2, 4] for `LatControlClarityEps`. The PID session's own gate inside `LatControlPID` is separate work.
- **Against the PID session's fix** (STATUS 175, `NrdrLatPidFirmwareFF` on, ebdd44d7; same sim and routes, /tmp/epsff/pid175_vs_eps.py). The format is wobble by band, then turn error.
  - PID + gated feedforward: 286 1.27 / 0.27 / 0.23 / 0.07, 15.3 / 10.7. 285 0.58 / 0.37 / 0.20 / 0.11, 15.4 / 11.4. 284 0.45 / 0.34 / 0.13 / 0.11, 23.8 / 7.2. 280 0.25 / 0.19 / 0.15 / 0.10, 15.3 / 11.6.
  - The first fix here, James + [4, 8], trails it everywhere. It wobbles 2–4× as much at 5–12 m/s, and its turn error is higher (286: 21.7 / 13.2).
  - James's controller with the gate is level on wobble (within 0.07°). Its turn error is equal below 12 mph on 285, 286 and 280, 2 ° worse on 284, and 0.6–1.8° worse at 12–25 mph on all four routes.
- **MetaDrive, model in the loop (sim only, not driven; one episode per cell; reported by the MetaDrive Sim session, STATUS 177 on `sim-lat-training`).** The setup is TSFDO, the comma 4 camera and torque mode through the fitted C020 EPS. Do not compare these with the earlier stock-model sims.
  - **Stop and resume on a gentle loop** (40 km/h, cancel and brake to 0, resume at 60 s). This is the pull-away case the replay above cannot see.
    - pullaway_wobble: ungated 1.99, gated 1.11. Reference: PID 0.48, PID + firmware FF 0.65.
    - Standard-band err_rms: 4.68 → 3.28. curve_ratio: 1.04 → 0.98.
    - Both re-engaged, and neither left the road.
  - **R 60 m loop at 25 km/h**, turn_err / trail / past:
    - Ungated 7.94 / 6.06 / 1.89; gated 9.41 / 6.75 / 2.66.
    - Reference: PID 10.65 / 9.72 / 0.92 (one departure); PID + firmware FF 7.31 / 5.12 / 2.19.
  - **R 40 m** is past the torque limit for every controller, so it is a stress case, not a ranking.
  - **Read.** The gate roughly halves pull-away wobble and lowers the standard-band error, at about +0.7° trail and +0.8° past in the R 60 turns. Pull-away wobble with the gate is still about 2× PID's. Repeat runs (run-to-run spread) are pending.
- **MetaDrive repeats, n=3 per cell (sim only, not driven; reported by the MetaDrive Sim session). They settle the gate against run-to-run spread.** All 12 episodes ran at 87-99 Hz.
  - **Stop and resume.** pullaway_wobble: ungated 1.99 / 1.71 / 2.32 (mean 2.01); gated 1.11 / 1.24 / 1.32 (mean 1.22). The 0.79 gain exceeds both ranges (0.61, 0.21), and the ranges do not overlap.
    - Centre (|des| < 10) and turning pull-aways both improve.
    - err_rms_standard: mean 5.50 → 3.67. curve_ratio_standard: 1.11 → 0.99. Gated n=2 on both, because one episode had too little ≥ 25 mph time.
    - No departures.
  - **R 60 at 25 km/h**, turn err / trail / past means: ungated 6.87 / 4.99 / 1.89; gated 7.26 / 4.50 / 2.77.
    - err (+0.39) and trail (−0.49) are inside the spread.
    - past +0.88 is outside it: ungated 1.62-2.15, gated 2.58-3.06. The gate gives a consistent ~0.9° more overshoot past the desired angle in R 60 turns.
    - Departures: ungated 2 (one episode), gated 0.
  - **Read.** The gate's pull-away gain is real in sim. Its turn cost is a small, consistent overshoot, not a turn-error increase. On the road, watch for the wheel going slightly past the line through moderate turns.

- **James's turn smoothing, ported and put on the car's test branch (owner's request, 2026-09-27; static tests only, not driven).**
  - The fix is JamesL787 `vfn-controller-shadow` aa943ad4. The problem it targets: with the blinker on at low speed, the turn hold and turn lead entered the steering target as steps, and at a stop the target could flip between the hold and the model every frame (James's routes 354/355).
  - It applies only when `LatControlClarityEps` is the built controller: `turn_shaping = isinstance(self.LaC, LatControlClarityEps)`, so the PID path is unchanged. The hold/lead floor goes through a 0.25 s low-pass, a release glides onto the model, and a driver-confirmed capture still snaps.
  - `clarity-turn-shaping` 3682a600: the candidate on this branch's tip, for sim.
  - `clarity-eps-testing` 24c9212f + f7655b64: the same port, on top of 0f27431d's angle gate. A one-time migration (`migrate_nrdr_clarity_eps_default`, flag `/data/nrdr_clarity_eps_default_v1`) turns `NrdrLatEpsFirmwareFF` on, which makes James's controller that branch's default. The toggle still turns it off, and the value persists if another branch is flashed. The compiled default stays `"0"`.
  - Tests: 44 pass (James's 7 plus test_controlsd, test_turn_lead and test_nissan_leaf_fallback). A MetaDrive pilot with a latched blinker and a stop before each corner is queued; the full set waits on whether the pilot reproduces the standstill flip-flop.

- **Route 00000287--5cda3437c4, the first drive of `clarity-eps-testing` f7655b64 (limited road evidence; initData confirms the branch, the commit and `NrdrLatEpsFirmwareFF`=1).** The owner reported two events. Neither came from the steering controller: in both, the wheel followed the commanded angle, and the command came from the model.
  - **2:17-2:26, left curve at 25-32 mph, "hugged left, over the line".**
    - The controller tracked the plan: yaw-rate curvature matched desiredCurvature within about 3%, and the angle ran 0.4-1 deg past a 27 deg desired.
    - The plan itself sat left of the lane centre. At 20 m it was about 0.7 m left of the midpoint between the lane lines.
    - The left line fell to 0.8-1.2 m from the car at x=0, so the left wheels were on the line.
    - The right line was near invisible (prob 0.02-0.10).
    - Whether PID on the same plan would sit anywhere different was not tested. A replay comparison is the next check.
  - **2:38.2, right curve, 23 mph.** The driver pulled left at up to +2100 torque and the angle went from -25 to -11 deg. The feedforward dropped out on the press and came back by 2:39.6.
  - **2:43.4, left blinker at 19.8 mph, "almost turned into the oncoming traffic waiting at the stoplight".**
    - The cause is StarPilot's Force Turn Desires (`TurnDesires`=1): below `MinimumLaneChangeSpeed` (20 mph on this car), a single blinker feeds a turnLeft desire to the model. modelV2 desireState went to turnLeft on the next frame.
    - The model asked for a hard left at once: path 10 m left at 20 m ahead, 80-87 deg of wheel at 19 mph. The controller followed it: desiredCurvature equalled the model action, so the turn lead added nothing.
    - The driver pushed right at 1500-2200 torque from 2:44.8. The model kept the left turn until about 2:50.
    - This happens with either lateral controller while that toggle is on.
  - **`lat_score.py score`, 286 (ungated) vs 287 (gated).** These are different roads, so the comparison is confounded. Limited road evidence:
    - Low-speed overshoot (turn_past<12mph) fell 10.55 -> 0.55 deg, but trailing rose 10.1 -> 24.5, so turn error went 20.7 -> 25.1.
    - At 12-25 mph, past was 4.9 -> 5.1.
    - Pull-away wobble went 2.17 -> 2.72 (n 6 / 5).
    - Most road pull-aways are turns out of a stop. Only 1-2 per drive are straight: 286 scored 1.88 and 0.17, 287 scored 1.24. That is too few to confirm or refute the sim's 2.01 -> 1.22.
    - Caveat: the hands-off mask uses steeringPressed, which stayed 0 at 1500-2200 driver torque during the 2:44 fight. The 287 turn figures include that fight.
- **Route 00000289--ba86b1c7c3, the owner's drive of `clarity-turn-shaping` 3682a600 (James's turn smoothing, feedforward ungated; initData `NrdrLatEpsFirmwareFF`=1, `NrdrLatPidFirmwareFF`=0). Limited road evidence, log decode.** The owner reported wobble when resuming at low speed, and oversteer at 9:40 and 10:30. Times below are log time; the owner's bookmarks run about 2-3 s earlier. The bookmarks went to the Radar Work session for the longitudinal side.
  - **Pull-away wobble is the feedforward riding the model's own swing.** The pull-aways at 0:39.8 and 2:03.6 both do it. From about 9 mph, where the speed fade reaches w = 1, up to about 20 mph, the wheel swings ±5-7° at about 1 Hz (2:06.9-2:08.9: +5.4 / -6.0 / +7.0 / -3.4). Through all of it |desired| stays under 8°.
    - The desired angle swings in phase, about 0.25 s ahead: +2.9 / -3.8 / +5.5 / -1.2.
    - f is in phase with the desired and is most of the command (f +0.14-0.15 of out +0.22-0.24), while p opposes the overshoot.
    - Band-passed rms, 2.5-9 m/s, 15 s after each straight start: 3.49 and 3.80. The 15:20 start scored 1.18.
    - The same window on gated 287 (4:48 start) scored 2.29, with |f| 0.002 against 289's 0.06.
    - This is the |desired| < 10° region where 0f27431d's gate holds the feedforward at 0. That is consistent with the gate targeting this wobble, but it is one straight start on each side, on different roads.
    - Route pull-away wobble (lat_score) is 2.17 over 6 starts, the same as 286 (also ungated).
  - **9:40 (log 9:42.5-9:49): an unsignalled left turn at about 16 mph through an intersection (lane-line prob 0.00-0.09).**
    - At the turn peak the wheel went past the plan: 9:45.3-9:45.5, angle +129.8 against desired about +121, while f stayed +0.40 to +0.31 and p opposed it at -0.18 to -0.20. Yaw-rate curvature ran above the desired.
    - The driver then pulled right at -1800 to -2100 torque, and the wheel trailed afterwards.
  - **10:30 (log 10:31-10:39): an unsignalled right turn at 12.5-14.4 mph.**
    - The plan asked for a tight turn: desired -118° (curvature 0.054, about a 19 m radius), path +13 m to the right at 20 m.
    - The driver held the wheel left at +1800 to +2100 torque from 10:32.1 to 10:35.6 while the wheel was still short of the plan. For example, at 10:34.1 the angle was -62 against -114.
    - Only one steeringPressed frame registered (10:34.6), which reset the feedforward ramp.
    - On release the wheel ran to -109 at 10:35.9-10:36.4. It then stayed past the unwinding plan: 10:36.6, -106.9 against -98.3; 10:37.1, -86.8 against -81.4. Through that, f was -0.13 and p was +0.19 opposing.
    - So there are two parts: the plan itself cut the corner, and then the ungated feedforward overshot on the unwind. The unwind is the same shape as 9:40 and STATUS 170's overshoot.
  - **Not concluded:** whether the gated build would have avoided either turn overshoot. The gate is fully open above 30° desired, so it does not touch the turn peak. What changes there is the fade-in on the way up, and the Metadrive Civic-plant R60 runs cover that. No controller change is proposed from this route.

## 174. Gas learner (`LongGasLearner`) on 00000286--ba543e3a3e, and its values now go into the drive log (`starpilotCarState.gasLearner*`). The 286 findings are from a CAN decode. The logging has static tests only and has not been driven.

**What 286 shows.** Nothing in the log recorded the learner, so its applied gasfactor was rebuilt from `ACC_CONTROL` in sendcan: `GAS_COMMAND / 375 = gf·(ACCEL_COMMAND + wind·wf) + hill`. The Civic Bosch table is [0, 750] (interface.py `BOSCH_GAS_LOOKUP_V`), not the 1600 in values.py.

- **It runs as built.** It loads the saved value at boot: `HondaGasFactorParams` 1.5616 in initData, and the first gas frame (0:47.6) implies 1.556. A least-squares fit over the drive gives:
  - gf 1.42
  - wf 0.92 (saved 0.899)
  - hill term ×1.05, where the STATUS 154 design is ×1.0, unscaled
  - rms 0.043 m/s²
- **Flat-road tracking is close.** The mean gap between command and aEgo is within 0.06 m/s² for commands below 1 m/s², and about 0.12 for commands of 1–2 m/s².
- **The value swings and sits high.** Median applied gf by minute:

  | Minute | Median gf |
  |---|---|
  | 0 | 1.56 |
  | 2 | 1.49 |
  | 3 | 1.39 |
  | 4 | 1.35 |
  | 5 | 1.20 |
  | 6 | 1.31 → 1.55 |
  | 9 | 1.55 |
  | 10 | 1.48 |
  | 11 | 1.46 |
  | 12 | 1.45 |

  - It is above the 1.25 soft band for almost the whole drive. The 0.01/min decay is small next to the learn rate: about 0.04–0.1 per second at 0.3 m/s² error with learn_speed 150.
  - The saved 1.5616 equals the 1.6 hard ceiling minus about 230 s of decay. The raw value was probably pinned at the ceiling on the previous drive (inference).
- **The 6:09–6:18 jump (1.35 → 1.49) happened on a climb.** Pitch was +0.03 to +0.05, where learning is frozen (deadband 0.02). The raw value must have moved as the grade started, around 6:09–6:10 or earlier; the applied value trails it by 7.5 s. The CAN decode cannot show the raw value or which tick learned, and that is why the logging below was added.
- **Open question.** Does gf about 1.4–1.6 describe the car, with the 750 table too small, or is the learner soaking up grade onset and lag? The new fields answer this on the next drive. No gain or gate was changed.

**Logging (new).** These fields are added to `custom.StarPilotCarState`, logged at 100 Hz in the rlog (every 10th frame in the qlog):

| Field | Meaning |
|---|---|
| `gasLearnerAvailable` @31 | Honda Bosch only; false elsewhere |
| `gasLearnerGasFactor` @32 | applied value |
| `gasLearnerGasFactorRaw` @33 | persisted integrator |
| `gasLearnerWindFactor` @34 | applied value |
| `gasLearnerWindFactorRaw` @35 | persisted value |
| `gasLearnerError` @36 | last lag-aligned command minus aEgo |
| `gasLearnerLearning` @37 | this tick passed every gate |

How it is wired:

- `LongGasLearner.learning` is the new flag. It is cleared on every tick and when `HondaLiveLearningGas` is off.
- `CarController.gas_learner_state()` returns the values.
- `card.set_gas_learner_fields()` copies them in when it publishes. The values are one frame old, and a failure logs once and leaves the fields at their defaults instead of stopping card.
- It is schema-only on the C++ side, like the epsFf* fields in bca3f9d0. No rebuilt binaries and no params key.
- The stale comment saying last_gas_error was mirrored into actuators.speed is corrected.

**Tests.** All static:

- `test_carcontroller_learners.py` TestLearningFlag: 3 tests.
- `selfdrive/car/tests/test_gas_learner_log.py`: 3 tests.
- The honda tests together with the new file: 307 passed.
- py39 compat: 14 passed.
- A smoke test with a real `CarInterface`: HONDA_CIVIC_BOSCH fills the fields; HONDA_CIVIC (Nidec) leaves `gasLearnerAvailable` false.
- The ruff findings in carcontroller.py and the learner test file were already there; none are on changed lines.

**Reading it back.** `LogReader(...)` → `m.starpilotCarState.gasLearnerGasFactorRaw` etc.

## 175. `NrdrLatPidFirmwareFF` (new, default off): the NRDR PID gets James's EPS firmware feedforward in turns only, gated by |desired angle|. This is option 3 from STATUS 172. It is separate from James's controller. Static tests and closed-loop sim only; not driven.

- **Owner asks:** "add the fix for nrdr pid lateral tuner to the main branch", and keep James's controller separate. Also: "make sure it's gated behind the actual controller, so whatever fix that works for pid doesnt impact the new controller and vice versa."
- **What it does.** This is the STATUS 165 crossfade, back in `LatControlPID` behind its own key, with one addition: the weight also scales with |desired angle|. It is 0 below 10° and full from 30°.
  - In a turn it replaces the kf and rate feedforward (both at 1 − w) with w × the firmware-inversion feedforward.
  - P and I are unchanged, and the `LatFScale*` trims do not scale the firmware term (as upstream).
  - Join gate as upstream fd815ef3: the weight ramps in over 0.5 s once the error is under 10°, and a press or v < 2 m/s drops it. It reaches full weight at 4 m/s.
  - If the feedforward throws or goes non-finite, the weight drops to 0 and the toggle-off command carries on.
  - `epsFfWeight` on starpilotLateralState now logs the applied weight.
- **Why the gate.** STATUS 170: ungated, the feedforward makes the wheel follow the model's near-centre wiggle, 4–6× PID's wobble below 12 m/s on 286. The gate keeps it out of exactly that region.
- **Kept apart from James's controller.**
  - The gate, the join and the speed constants (`NRDR_PID_EPS_FF_*`, `nrdr_pid_eps_ff_weight`) live in `latcontrol_pid.py`, so a change to `nrdr_eps_firmware_ff.FF_SPEED_BP` or its join constants on clarity-eps-testing does not move the PID.
  - `LatControlClarityEps` never reads `NrdrLatPidFirmwareFF`. With `NrdrLatEpsFirmwareFF` on, controlsd runs James's controller and this path does not run at all.
  - What the two share is the feedforward model itself, `ClarityEpsFirmwareFeedforward` and its calibrations. A change there moves both.
  - Tests pin all of this, including that the PID's weights are unchanged when `nrdr_eps_firmware_ff`'s gate constants are patched.
- **Sim (tools/lateral/lat_pid_sim.py, C020 banded plant, logged params, this code).** Mean |des − angle| over hands-off frames with |des| > 45°, off → on:

  | route | < 12 mph | 12–25 mph | wobble 2–5 / 5–8 / 8–12 / 12–20 m/s, off → on |
  |---|---|---|---|
  | 286 | 23.2 → 15.3° | 14.2 → 10.7° | 1.27/0.27/0.24/0.07 → 1.27/0.27/0.23/0.07 |
  | 285 | 17.3 → 15.4° | 13.6 → 11.4° | 0.58/0.37/0.20/0.12 → 0.58/0.37/0.20/0.11 |
  | 280 | 15.6 → 15.3° | 14.0 → 11.6° | unchanged, 0.25/0.19/0.15/0.10 |
  | 284 | 24.2 → 23.8° | 8.5 → 7.2° | 0.48/0.33/0.13/0.11 → 0.45/0.34/0.13/0.11 |

  - Wobble is the STATUS 170 metric (0.4–3 Hz rms, |angle| and |des| < 12° held 1.5 s).
  - Ungated, the same feedforward gives the same turn error but 2–3× the wobble. For example, 286 at 5–8 / 8–12 m/s: 1.03 / 0.67.
  - The 2–5 m/s bin is not closed-loop (the sim re-syncs to the log below 4 m/s), so resume-from-stop is untested.
  - Sim trust per STATUS 172: good on 280, reads low on 285, untrusted on 284.
- **What it can and can't fix on 285 (STATUS 172).**
  - It adds torque in partial-command turns like 7:58 and 10:01.
  - It cannot help 7:12, where the command was already saturated.
  - It cannot help 9:15, where a same-direction press made the car send 0; that is option 1.
- **Params artifacts.** `common/params_pyx.so` and `libcommon.a` were rebuilt natively on aarch64 with the pinned toolchain: clang 18.1.3, Python 3.12.3, Cython 3.1.4, `SP_FORCE_TICI=1`, the repo bind-mounted at `/work`, sconsign and targets cleared.
  - `params_pyx.cpp` is byte-identical. Keys go 858 → 859, the only addition `NrdrLatPidFirmwareFF`.
  - Galaxy: Lateral Tune → "PID Turn Feedforward (Test)".
- **Tests.**
  - selfdrive/controls/tests/test_latcontrol_pid_eps_ff.py: 6 pass. They cover the gate, the join and drop, default-off identical, on adds turn torque only in turns, and both isolation checks.
  - The lateral, sim, galaxy-layout and py39 suites pass.
  - test_latcontrol.py's Bolt and Palisade taper tests fail with and without this change (pre-existing).
  - selfdrive/ui/tests/test_device_screen_settings.py segfaults on this host in collection (not investigated).
- **Suggested first drive:** turn it on together with or after `LatPScaleLowSpeed` 130, and note the same intersections as 285.
- Scratch: /tmp/epsff_pid/gate_sim.py (harness), real_sim.py (this code).

## 176. `tools/lateral/lat_score.py`: one scorecard and gate for both lateral controllers, fed by replay and by MetaDrive. Replay (closed-loop sim) only; nothing driven, no controller or param change.

- **Owner asks:** "I don't have all the time to test every single scenario between both controllers … I was hoping that metaldrive could help … speed up the tuning process for both controllers." Also: set up the same pipeline with the NRDR PID session and the MetaDrive session.
- **The division of labour.** MetaDrive (`sim-lat-training`, `lat_cem_tune.py`) searches for candidate tunes on scenarios the owner has not driven. This tool accepts or rejects a candidate against the owner's own drives. Its metrics are the ones STATUS 170/173/175 used, so a search cannot win on a figure the owner does not feel.
- **Commands.**
  - `score FILE_OR_DIR …`: scores a lat_pid_sim-format log as recorded, with no simulation. This covers a real route cache or a MetaDrive `lat_episode.sh` OUTDIR, where `offroad` and `engaged_s` come from `episode.json`. It adds pull-away wobble: the 10 s after each start from a stop.
  - `replay` / `gate ROUTES --kind pid|clarity_eps --set K=V [--base-kind --base-set] [--clarity-const FF_SPEED_BP=a,b]`: runs a baseline and a candidate on the C020 plant over the 7 default routes (280, 284, 285, 286, 27a, 277, 278). `gate` exits 0 only on "pass".
  - `--clarity-const` sets a list constant of `nrdr_eps_firmware_ff.py` in the worker only. It is sim only; the car cannot set it.
  - Toggles are forced per kind:
    - pid: `NrdrLatEpsFirmwareFF` 0.
    - clarity_eps: `NrdrLatEpsFirmwareFF` 1 and `NrdrLatPidFirmwareFF` 0.
    - The toggles are printed, so 286's logged EpsFF=1 cannot leak into a PID run.
- **Metrics.**
  - wobble: 0.4–3 Hz rms on near-straight driving, for 2–5 / 5–8 / 8–12 / 12–20 m/s. The mask is taken from the log, so both runs score the same frames.
  - turn error: |des| > 45°, for < 12 and 12–25 mph. Alongside it: the fraction of those frames with |out| > 0.99, and the mean feedforward weight.
  - dither: command reversals per second on |des| < 5°. A reversal needs |out| > 0.01 on both sides. Without that, 280's resting command (|out| ≈ 7e-4) counted 0.2/s of noise as a regression.
  - unwind lag, from `lat_route_check`.
  - `lat_pid_sim.metrics` err_rms and curve_ratio per band.
- **Gate.** Per route, agreed with the NRDR PID session. A figure regresses if it gets worse by more than:
  - wobble (5–8 / 8–12 / 12–20 only): max(0.05°, 15 %). The 2–5 bin is re-synced to the log and is reported, not gated.
  - turn error: 0.5°.
  - dither: 0.1/s.
  - err_rms: 3 %.
  - An improvement is the same margin in the other direction. The route-trust notes from STATUS 172 are printed; 284's < 12 mph turn error is not gated. "Better on 280, worse elsewhere" is reported as "mixed", not "pass".
- **Check against STATUS 175.** 286, pid → PidFF: turn error 23.20 / 14.21 → 15.33 / 10.70, identical to STATUS 175.
- **First runs (7 routes, sim only).**
  - **PID → PID + `NrdrLatPidFirmwareFF`: mixed.**
    - Turn error improves on 6 routes. For example, 27a < 12 mph goes 43.8 → 35.4, and 285 goes 17.3 / 13.6 → 15.4 / 11.4.
    - Wobble and dither are unchanged everywhere.
    - **278, < 12 mph turn error, regresses 17.45 → 18.95.** This has been passed to the NRDR PID session.
  - **PID + PidFF → James's controller (this branch, ungated [2, 4]): fail on all 7.**
    - Wobble 5–8 m/s is 2–5× higher (286: 0.27 → 1.40).
    - Dither is about 2× higher.
    - < 12 mph turn error is 1.4–5.4° worse.
    - Only err_rms at 25–50 and > 50 mph improves (for example, 277 highway 0.83 → 0.47).
    - This agrees with STATUS 173.
  - **James's controller, `FF_SPEED_BP` [2, 4] → [4, 8]: mixed.**
    - Wobble 5–8 m/s improves on all 7 (286: 1.40 → 1.01).
    - < 12 mph turn error regresses on 6 (286: 16.8 → 21.7).
    - This is the trade STATUS 173's |desired| gate (clarity-eps-testing 0f27431d) was built to avoid.
- **Limits.** These are lat_pid_sim's limits: exogenous desired curvature, no model in the loop, one linear plant fitted at 5–21 m/s, and a re-sync to the log below 4 m/s. Pull-away wobble only means something on a MetaDrive or road log. MetaDrive's own caveat (its road departures ended the world at about 40 s, since fixed on its side with `out_of_road_done=False`) is that session's to record.
- **Follow-up: turn error split into trailing and past-desired** (`turn_trail` + `turn_past` = `turn_err`, signed by des). The split is reported, not gated; the NRDR PID session asked for it.
  - It explains the 278 < 12 mph result. The feedforward cuts trailing error (13.9 → 12.1) but the wheel goes past the line more (3.6 → 6.9), mostly in two steady tight turns near 4.5 m/s.
  - On 286 it only cuts trailing (12.0 → 3.9); past-desired is unchanged (11.2 → 11.4).
  - The PID session keeps the code as is and will tell the owner to watch long tight turns near 10 mph. The dither deadband stays at 0.01.
- **Follow-up: `lat_score.py detect ROUTE_DIR [...]` says which lateral controller drove a route, so the route goes to its owner.** This is step 2 of the tuning group's routing rule; the owner's drives are routed per segment. It reads rlogs only (log decode, static).
  - **Evidence, in order:**
    - `initData` `NrdrLatEpsFirmwareFF` and gitCommit. The key is read once at start: 1 is James's controller, 0 is PID. A build whose commit has no `latcontrol_clarity_eps.py` is PID by construction (280 at 63827356, 284 at 90487307).
    - An identity test. `LatControlClarityEps` logs the feedforward it applied as `pidState.f`, which equals `epsFfWeight × epsFfFeedforward` of the same frame, gated build or not. `LatControlPID` logs its unscaled kf term there; PidFF crossfades later, in the output (checked by the NRDR PID session at latcontrol_pid.py:874).
      - Frames are counted only where either side exceeds 1e-3, the NRDR PID session's floor: both sides near 0 would match trivially. Under 200 such frames the segment is "undetermined".
      - Pairing is by timestamp: `starpilotLateralState` follows `controlsState` by about 0.2 ms. Index pairing broke 286 segment 11, which starts between the two.
    - `centre_w` (the fraction of |des| < 10° frames with weight > 0) separates the ungated build (about 1) from the 0f27431d gated build (about 0).
  - **Output.** It prints the owner, or "ASK PETER" when a key is missing on a newer build, or when the key and the identity test (or two segments) disagree.
  - **Measured.**
    - 286: identity 1.00 on all 14 segments, `centre_w` 0.96–1.00. James's controller, ungated.
    - 285: identity 0.00 → PID.
    - 280 and 284 → PID (build predates the controller).
  - **Not yet measured on a drive:** a gated-James drive and a PidFF-on drive. Those two cases rest on the code (static) and the synthetic tests.

## 177. Longitudinal on 00000287--5cda3437c4 (build clarity-eps-testing f7655b64; BoschARailInterval 1, RangeDerivedVrel 1; 7.3 min, 25 % experimental). There are two brakes below -1.5, and one is a stale coasted vRel. No bookmarks, and nothing changed in code. Log decode only.

**2:39.0–2:39.2: aTarget -2.74 → -2.87 for 3 radar frames on track 49, a coast.**

- **The coast.** Track 49 was born at 155.50 s, 54.9 m out at yRel -14.3, during the left turn. Its measured vRel was -11.4 while ego was at 11.5 m/s, which reads as a stationary object.
  - From 156.31 s it is published `measured=False`, and the last trusted vRel of -11.4 is held for 2.9 s.
  - Over those 2.9 s its range falls only 45.6 → 35.1 m, a slope of about -3.7 m/s. Ego slows from 11.5 to 9.6 m/s.
- **The bad frames.** At 159.07 s the point swings in-path (yRel -4.3) and radard makes it leadOne. It carries vRel -11.4 with vLead -1.6 to -1.8, meaning a lead reversing. Vision had the same car at vRel about -6, lead about 4 m/s. At 159.18 s the radar re-measures the track at -6.8, matching vision, and aTarget returns to -1.2.
- **The driver.** The owner pressed the gas at 2:39.6 and switched to chill at 2:40.6.
- **Why D-063 did not act.** The coast bound, `_bosch_a_coast_vrel`, pulls a coast toward the range fit only on the closing side unless the coast is inside a rail-interval hold (STATUS 129). This coast was not in one. Its down side would have allowed vRel ≥ fit − 3 ≈ -6.7.
- **Candidate fix, not applied** (radar gate, needs the owner's OK): a physical floor on coasted vRel only, vRel ≥ -(vEgo + margin). A coast would never publish a lead reversing faster than the margin. The point is kept (D-041/042) and only its implied reversing speed is bounded. Here it would give about -9.6 instead of -11.4. It is untested against STATUS 129's three protected brakes (00000232 1147.2, 00000266 560.0, 00000266 795.4); replay on those comes first.
- **Same turn as STATUS 173's 2:43 near-turn.** That entry traces the 2:43 near-turn into oncoming traffic to Force Turn Desires.

**4:02.0–4:06: aTarget -1.9 → -2.99, real slow traffic.**

- Radar picks up tracks 10 and 18 at 62–88 m on the U11 rail (-13.5) at 36 mph. Vision puts the lead at 4–7 mph, and the rail is not binding (true closing is about 12–13 m/s).
- It peaks at -2.99 for about 1 s, then eases to -0.9, then about -1.8 to the stop.
- This is the same pattern as STATUS 169's 10:03 and 12:09 events: the plan front-loads the stop at about 1.8× the constant decel it needs (about 1.7 m/s² from 62 m).
- No false brake.

**Gas learner.** A CAN decode as in STATUS 174. The drive was on a build without the new logging.

- The saved value at boot was 1.307, and the first minute implies 1.56.
- Minute medians were 1.56 (min 2), 1.35 (min 3) and 1.38 (min 5).
- It swings between 1.3 and 1.6 again, above the 1.25 soft band.

## 178. Longitudinal on 00000289--ba86b1c7c3 (build clarity-turn-shaping 3682a600; 19.4 min, 9 % experimental). The owner's three device bookmarks are real hard brakes for braking leads. Longitudinal did not cause the 9:40/10:30 oversteer or the pull-away wobble. No code change. Log decode only.

The lateral side of the same drive is in the STATUS 173 thread (commit 1a098438). Times are log time.

**Brakes below -1.5.** There are eight. All are real leads that radar and vision agree on.

- **1:19.8, -3.69, chill.** Lead #47 at 21 m, vRel -5, aLeadK -3.7. Device bookmark 1:22.4.
- **6:21.6, -3.52, chill.** Cut-in: vision lead at 83 m, then radar #5 at 43 m closing at -8 m/s, ego 20 m/s. Device bookmark 6:24.3.
- **12:47.3, -3.48, chill.** Lead #47 braking at aLeadK -4.9, ego 19 m/s down to 3 m/s. Device bookmark 12:49.5.
- **Milder ones:**
  - 1:37.1, -2.4
  - 9:41, -1.7
  - 10:21.9, -2.1
  - 3:40.7, -1.57
  - 3:55.2, -1.51

  These are ordinary slowing for a lead. aEgo tracks aTarget within about 0.4.

**Coasted leads with vLead < 0 (the STATUS 177 pattern).** There are 99 frames across 7 episodes, and none of them was engaged-and-braking.

- **7:19-7:24, not engaged, driver braking.** Track #48 held vRel -13.5 flat for 2.4 s (7:21.0-7:23.4) at 75 to 52 m. Over the same 2.4 s the range fell at about -9.6 m/s, so the held vRel was about 4 m/s too negative.
  - This is a second instance of 287's 2:39 stale coast.
  - The candidate floor vRel >= -(vEgo + margin) would **not** catch it, because -13.5 is roughly -vEgo.
  - A range-rate bound would catch it. That is the rail-hold-only down side of STATUS 129.
  - It is recorded for the on-hold coast review. Nothing was applied.
- **17:04, not engaged, driver on gas in a tight turn.** Radar #55, a stationary object at 6 m closing at 2.5 m/s, drove aTarget to -5.6. Nothing was actuated. It looks like a real object near the turn path, not a coast artefact.
- **The other five** (4:01, 15:10, 16:02, 16:46, 17:42) are at or near standstill or were never leadOne-for-control.

**Pull-aways (the "wobble when resuming").**

- At 0:39.8, 5:08.9 and 15:20 the driver was on the gas and openpilot sent no accel command (acc 0, gasPressed). The wobble still happened.
- **2:03.6 is the only pull-away under openpilot longitudinal**, and it is the worst wobble per the lateral agent.
  - The accel command was steady at +1.5 to +1.7.
  - aEgo was +1.2 to +1.6, with no 1 Hz fore-aft swing in phase with the ±5-12 deg steering swing.
- Conclusion: the wobble is not driven by a longitudinal surge. This agrees with STATUS 170/173.

**Oversteer bookmarks.**

- **9:40 (log 9:42.5-9:49), experimental.** aTarget peaked at -1.7 at 9:41 for real lead #48. The driver pressed the gas from 9:42.5 and stayed on it through the turn, so there was no openpilot braking during the turn.
- **10:30 (log 10:31-10:39).** No longitudinal event. aTarget was -0.1 to +0.7, with lead #35 at 22 m until 10:31.5. The driver was on the gas from 10:30.5.

**Gas learner.** A CAN decode as in STATUS 174; the build predates the a2248077 logging.

- Implied gas factor per minute went from 1.25 at the start, peaked at 1.42 (min 2), eased to about 1.23 (min 7-9), and ended at 1.52 (min 13).
- That is the same 1.2-1.6 swing as 286 and 287, above the 1.25 soft band. It is still open whether this is a table error or grade and lag. The a2248077 logging answers that on the next build that carries it.

## 179. A coasted vRel that says the car ahead is reversing is now bounded by the range rate (or floored at a stopped lead). Fix for route 00000287 2:39 (STATUS 177). Replay and static evidence only; not yet driven.

**Problem.** On 287 at 2:39, track #49 coasted a stale vRel of -11.4 for 2.9 s while ego was at about 10 m/s. That coast means the lead was reversing at about -1.8 m/s. The range was really falling at -3.7 m/s, so the true vRel was about -6.8. aTarget reached -2.87 and the owner pressed the gas. STATUS 129 limits the down side of the coast bound (making a coast *less* closing) to rail-interval holds, so this coast kept its stale value.

**Change** (`opendbc/car/honda/radar_interface.py`, `_bosch_a_coast_vrel`; `selfdrive/car/card.py`):

- card feeds `RI.v_ego = CS.vEgo` before `RI.update`.
- When a coast implies a reversing lead (`v_ego + vRel < -BOSCH_A_COAST_REVERSING_MARGIN_MPS`, 1.0 m/s), it also gets the down side `max(vRel, rate - 3)` against the fresh range fit, outside a rail hold too.
- With no fit yet (fewer than 4 fresh samples over 0.25 s), it is floored at vLead = -margin.
- Coasts that imply a stopped or slower car are untouched. These are STATUS 129's protected over-closing brakes.
- The change rides the existing toggles: it acts only when BoschARailInterval or RangeDerivedVrel is on. With both off, the coast is verbatim.
- The point is always kept (D-041/D-042).

**Replay** (a copy of the real RadarInterface plus radard and the planner, over the full routes; variants A = current, F = radard floor, K5 = rate-5 down side on every coast, R/RF = this change without/with the no-fit floor):

| Route | F | K5 | R/RF |
|---|---|---|---|
| 287 2:39 (track 49 vRel, truth about -6.8) | -10.8 | -9.2 | **-7.2** (A -11.4) |
| 287 brake episode 160.0 | unchanged | later | **-2.00 -> -1.50** |
| 232 1147.2 protected | unchanged | **softened -2.25 -> -1.92** | unchanged |
| 266 560.0 / 795.4 protected | unchanged | **softened / later** | unchanged |
| 232 90.0 | **new harder brake -2.35 -> -3.50** | unchanged | unchanged |
| 236, 26b, 289 | no episode moved | 289 381.6 later | no episode moved |

- No variant lost a point on any of the six routes.
- RF is the only variant that moves just the target event. It is what was applied.

**Not caught.** On 289 at 7:21 (STATUS 178), vRel -13.5 at vEgo 12.9 implies vLead -0.6. That is inside the margin, so it is not bounded. openpilot was not engaged there.

**Tests.** `test_bosch_a_radar.py::TestRailIntervalBoundsTheCoast` has three new tests: a reversing coast is floored and then fit-bounded, a non-reversing coast (unknown, stopped or slower lead) keeps the one-sided bound, and both toggles off is verbatim. The honda tests, py39 compat and the gas learner log tests give 326 passed. Static.

**To watch on the next drive.** Brakes for a lead that coasts after its speed reading went stale: they should be no harder than the range closing supports.

## 180. Longitudinal on 0000028a--0f4ebf7920 (ns-bosch-radar-testing 2ab675ff, NRDR PID lateral, before the STATUS 179 fix; 30 segments). There are four device bookmarks: one mild radar false brake in a curve, one hard brake made harder by the lead switching to a car beside the lane, and two real brakes. The STATUS 179 fix moves nothing here. Log decode and replay only.

Times are log time. Bookmarks sit 2-3 s after the event.

- **5:29.8, mild false brake, aEgo -1.6 (command -1.0 to -1.4).**
  - Entering a left curve (steer -8 deg), lead #47 was about 3 m off-centre. Its measured range fell from 50.2 m to 40.8 m in 1.3 s, with vRel -5.8 to -7.2 and no coast.
  - Over the same window the camera lead held at 43-46 m and v about 15 (ego 16.3).
  - This is consistent with the reflection point moving to the side of the turning car.
  - Not a coast artefact. It is the same family as the one-sweep blip at 5:21.5 (command -1.39).
- **13:35.7, hard brake -3.5 (aEgo -4.4) at 13:32.**
  - Traffic was slowing to about 5 m/s on a right curve (steer +4 to +7 deg).
  - At 13:31.3, leadOne switched from #42 (70-80 m, y 3.0) to #32 (47-51 m, y 5.5, modelProb 0.86-0.91).
  - The camera lead was at 65-71 m, y about 5.3 in the radar frame. Scaled to 47 m along the curve, the lane centre sits near y 2.8, so #32 was likely about 2.5 m right of the ego path.
  - Braking for #32 instead of #42 roughly doubles the required decel.
  - This is a candidate for D-048 lead arbitration: a model match on lateral position that accepts an 18 m range mismatch. No change on one instance.
- **18:09.8, -1.2 to -2.0 at 70-105 m for #5, a car slowing to nearly a stop.**
  - The camera put it at v 1-3; the range rate from 91.8 to 54.9 m over 3.5 s says about -10.5 against measured vRel -7.5.
  - There was one 0.55 s coast (-10.5, 18:06.75-18:07.30) while the range said about -5.
  - The coast implies vLead about 9, so it is not reversing and STATUS 179 does not act.
  - The braking matches v²/2d, about 1.8.
- **20:05.4, real hard brake -3.5 (aEgo -4.3) at 20:04.** In-lane lead #39 braked hard (radar vRel -9.1, camera v 14 -> 5, prob 1.0). Radar and camera agree.

**Replay of the STATUS 179 fix** (in-tree code, A = v_ego not fed, RF = fed; `/tmp/rv/ab2.py`, which reproduces 287 160.0 -2.00 -> -1.50):

- 0 points lost.
- None of the 5 braking episodes moved (3 of them protected).
- Lead values differed in 18 frames, with no planner consequence.

## 181. Galaxy NRDR PID Tuning tab removed (owner request, 2026-09-27). PID tuning is done in the MetaDrive and replay sims now. Static only.

- **Removed from both UIs:**
  - the classic `/lat_tune` page (sidebar entry, route, `lat_tune.js`/`.css`);
  - the mobile `Tuning → NRDR PID lateral tune` tab (`NrdrLatTunePanel.js`);
  - the `/api/lat_tune/*` endpoints, `lat_tune_workspace.py` and their tests.
- **Deletions landed in the wrong commit:** they were swept into `eb2cd3bb` (STATUS 180) from the shared index, and this commit finishes the removal. Between the two commits `the_galaxy.py` imported a deleted module, so don't deploy `eb2cd3bb` alone.
- **Kept:**
  - the offline tools `tools/lateral/lat_tune_cli.py`, `lat_tune_sim.py`, `lat_pid_sim.py` and `selfdrive/controls/lib/lat_tune_analyzer.py`;
  - the band params `LatPScale*`, which are unchanged.
- **Stale links:** an old `/tuning/nrdr-pid` link falls back to the first tab.
- **On-device data:** trial files in `/data/galaxy/lat_tune/` are left in place.
- **Tests:** galaxy tests show the same failures as before the removal in this container (e.g. `test_dashboard_stats` 2 date failures reproduce with the old test file).

## 182. Longitudinal on 0000028b--ed67104f14: the first drive with the STATUS 179 fix (ns-bosch-radar-testing 99a4e49f, NRDR PID lateral; 32 segments). The fix acted live and never touched a lead. There are five device bookmarks: left-curve light brakes, the third and fourth instances of the pattern; a justified stop after engaging mid-turn; a normal stop; and a short over-held brake on a new lead. Log decode and replay only.

**The fix, live.**

- 3427 coasted points in total. 74 sat exactly at the floor, vRel = -(vEgo + 1).
- 34 coasted points still implied a reversing lead (18 episodes). Their likely paths are the range-rejected coast, which STATUS 179 leaves untouched, or a fit whose rate-3 bound is still below the floor.
- None of the 34 was ever leadOne.

**Replay** (`/tmp/rv/ab2.py`, A = v_ego not fed, RF = fed): 0 points lost, 0 of 9 episodes moved (6 protected), 0 lead-difference frames.

**Bookmarks.** Times are log time.

- **6:28.3 / 6:36.5: left curve (steer -5 to -10 deg).**
  - 6:26.5 (-1.0 command, aEgo -1.88) and 6:30.0 (-1.0, aEgo -1.14): lead #14's measured radar range fell from 43.5 to 30.3 m over 5 s (vLead 10-12). The camera held the lead at 40-45 m with v 14.5-15.
  - 6:35.5 (-0.68): #8 at y -4.8, with the camera agreeing on the lateral position. Radar vRel was -4.4 against a camera lead speed matching ego.
  - With 0000028a 5:27 (STATUS 180), that makes four brakes on three stretches, all in left curves, all measured (not coasts), each with radar range and speed below the camera's.
  - This is the next candidate. Before touching anything, compare radar and camera lead range and speed against steering angle over the corpus.
- **9:32.0: justified brake.**
  - The driver braked from 9:20 and engaged at 9:30.0 mid sharp-left turn (steer -30 deg) at 7.6 m/s.
  - #5 was measured throughout, with vRel -8 to -9.9. Its range fell from 39.0 to 16.4 m in 1.9 s (-12 m/s, more than vEgo), so the object was still moving toward the path.
  - The camera confirmed it: prob 0.78 -> 0.97, v about 0. It was a stopped car at 12 m.
  - aTarget -2.6 to -2.7, aEgo -3.4 peak.
- **11:20.6: normal stop.** Lead #36 braked to a stop (aLeadK down to -3.5). Ego went smoothly from 16 m/s to 0 at -1.5 to -2.3 and stopped 5.2 m behind it after a slow final creep under 2 m/s.
- **14:54.8: short over-held light brake.**
  - At 14:51, lead #45 moved right and #10 at 61 m became the lead. It was measured at -5.5 to -6.5 for 1 s, and the range agreed (-5 m/s). The camera lead speed fell 21 -> 17.
  - From 14:52.2 the range went flat, while #10 coasted -4.5* for 0.35 s and then measured -3.2 to -2.4.
  - The command stayed at -0.7 to -0.8 for about 0.5 s after the range stopped closing. Mild.

## 184. Desired Rate Feedforward slider removed from the device settings (owner request, 2026-09-27). Static only.

- Removed: the `NrdrLatRateFF` row in `selfdrive/ui/layouts/settings/starpilot/nrdr_tuning.py` and its entry in `starpilot/common/assets/device_settings_layout.json`.
- Kept: the param (default 0.0) and its term in `latcontrol_pid.py`, which is skipped at 0. The offline sims (`lat_pid_sim.py`, `lat_route_check.py`) still take it as a variant override.
- Evidence it was off: route 0000028b initData has `NrdrLatRateFF` 0.0. It has been recommended at 0 since STATUS 143, where 0.5 caused the low-speed stutter on 278.

## 185. Same-direction assist for NRDR PID (`NrdrSameDirectionAssist`, default off). A driver press that helps the turn no longer cuts the steering. Evidence is unit tests and open-loop replay of 28a/28b. No road evidence yet.

**Problem (routes 0000028a, 0000028b).** Any press above the override threshold cut the PID torque to 0 (HondaOverrideTorqueScale 0), whichever way the driver pushed.
- On slow tight turns Peter helps the wheel the way openpilot is already steering. The help cut openpilot out, and the car then under-turned.
- 28b 2:04–2:09: a right turn from a stop. The command was +1 and the wheel was 48° short, but 0 torque was delivered for 5.4 s.
- 28a 27:40: 3.1 s of same-sign help, all of it cut.
- Magnitude cannot tell help from a fight: help |tq| p50 is 2530–2650 and a fight's is 2280–2390. Only the sign can.

**Change.** `SameDirectionAssist` in `opendbc_repo/opendbc/car/honda/carcontroller.py`, applied after the debounce/hold chain.
- A press is exempt from the override when all of these hold:
  - sign(driver torque) == sign(command) continuously for 0.2 s (`SAME_DIR_ENTRY_S`);
  - speed ≤ 25 mph;
  - |torque| < 1.75× the threshold;
  - the press has been exempt for less than 8 s.
- On entry, torque returns through the normal fade-up (0.5 s).
- The carcontroller has no desired angle, so "short of the plan" is read from the command's sign: once the wheel passes the plan, the PID pushes back, the signs disagree, and the press is a fight.
- A command below 0.05 is neutral: it holds the current state, so a plan crossing zero does not flicker.
- Exits:
  - Opposite sign or above the ceiling: instant cut, the same as today.
  - The 8 s cap or leaving the speed band: a 0.3 s fade-out, then locked until the hand releases.
- Toggle off, or James's controller: the chain is unchanged. The toggle is under LateralTune (advanced) and in the NRDR tuning layout.

**Tests (static).** There are eleven new cases in `test_honda.py`:
- help with ±150 jitter, no chatter;
- toggle off;
- opposite-then-same, with the entry hold;
- a fight that starts with a same-sign blip;
- the ceiling;
- the 8 s cap fade;
- the speed band;
- a command crossing zero;
- letting go keeps the torque;
- a grip hovering at the ceiling;
- speed hovering at the band edge.

All 320 honda tests pass.

**Replay (open loop, logged tq/cmd/pressed through the real `_update_steering_torque`, threshold 2000, fades up 0.5 / down 0).** Open loop means the logged command is not re-run through the PID, so the closed-loop response to the returned torque is not modelled.

| Episode | Result |
|---|---|
| 28a 27:40 help | exempt 3.1 of 3.1 s, 0 transitions |
| 28b 2:04 help | exempt 4.4 of 5.4 s (the first 0.5 s was opposite sign), 1 transition |
| 28a 27:49 and 28:09 fights; 28b 8:34 fight | 0 s exempt |
| 28b 20:01–20:09 (Peter leading the plan) | chatter while the command sits within ±0.06 of zero; delivered torque ≤ 0.045 |

Every step above 0.1 is also present with the toggle off: it is the existing debounce cut.

**Watch items for the first drive:**
- An EPS steer fault during a help press. Combined same-sign torque above 2000 has only 0.1 s of history in the logs, max 2371.
- The closed-loop PID response when torque returns mid-press.
- `lat_pid_sim.py`'s CarControllerSteer does not mirror the assist.

## 186. NRDR PID output scale simplified: no turn-in / unwind / centre-boost terms (owner, 2026-09-27). Sim and static evidence only; not driven.

**What changed.** `_clarity_eps_pid_output_scale` (latcontrol_pid.py) is now James's version from
`clarity-eps-testing` (e3de63be / 66293384 / a08a1bf0). It adds up to +0.0675 through 10–20 deg and
+0.0847 more through 16–28 deg, faded in over 4–14 m/s, and it is the same for left and right. The owner
removed these terms, which came from starpilot's first Honda PID:
- the left/right-asymmetric coefficients;
- the turn-in and unwind (phase) terms;
- the centre boost (`HondaCenterScale`, `HondaCenterBoostMinSpeed`) and its lane-change fade.

The Center Scale and Center Boost Min Speed sliders are gone from both settings UIs. Their param keys
stay in params_keys.h, because the sim tools and the tune analyzer still list them. `HondaCenterBoostThreshold`
stays: carstate uses it for the centre override threshold (`NrdrOverrideThresholdCenterBoost`), not the scale.
`phase` is still computed, because the Civic testing-ground scale uses it.

**On the owner's car today.** 28a/28b ran with `HondaCenterScale` 0.0, so the centre boost was already off.
Nothing near centre changes. The change acts only in turns deeper than 10 deg above 9 mph.

**Evidence (sim, `lat_score gate`, C020 plant; routes 280, 284, 285, 286, 27a, 277, 278, 289, 28a, 28b).**
- Verdict **pass**: 4 routes improve and none regress.
  - 280: turn_err 12–25 mph 13.96 → 13.16.
  - 28b: turn_err 12–25 mph 11.93 → 10.58.
  - 27a: err_rms 25–50 mph 0.82 → 0.75.
  - 278: err_rms 25–50 mph 0.56 → 0.51.
- Every other figure is inside the gate margins. The real code reproduces the monkeypatched gate run
  exactly: max difference 0 over all metrics.
- Keeping our asymmetry and centre boost and dropping only the phase terms scored the same, and
  also improved 284 slightly (0.64 → 0.62).
- 28a/28b open-loop A/B on a plant fitted to those two drives: 25–50 mph rms fell by up to 0.1 deg
  (28b left 0.77 → 0.66). That plant reads 28b left error 0.77 against 0.48 logged, so the size of the
  gain is uncertain.

**Not ported from James.** He moved the low-pass filter from the target to the final torque (target
filter off, output tau 0.1). It fails the gate on all 10 routes: turn_err up 1–10 deg, wobble up at
5–20 m/s. His integrator reset at low speed and his stop flip-flop hold were not needed; our code already
handles both cases.

**Tests (static).** `selfdrive/controls/tests/test_latcontrol_pid_output_scale.py` checks that the scale is
the same both ways, is 1.0 near centre and below 4 m/s, and has the right values in a full turn. The
latcontrol_pid, analyzer, settings-layout, lateral-tools and py39 suites pass (243).

**Still open.** MetaDrive closed-loop A/B against the parent commit is pending (group rule). First drive:
watch mid-speed turns, both directions, for over- or under-steer at the apex.

## 187. The STATUS 186 output scale is now on the branch, and the lateral sim can model the C020 easing off under hand load. Sim and static evidence only; not driven.

**STATUS 186 lands.** Its text was committed early: it was swept into `e0d4aa2c` from the shared index while the code
stayed on `pid-simple-output-scale` (87fb0904). This commit brings in that code unchanged: `latcontrol_pid.py`, the
two removed sliders (`HondaCenterScale`, `HondaCenterBoostMinSpeed`) and `test_latcontrol_pid_output_scale.py`.
Both sims agreed before it landed:
- lat_score gate (11 routes, the ab57c707 file as base, `NrdrLatPidFirmwareFF` 1): pass, 3 routes better, wobble flat.
- MetaDrive chains 43/44 (post camera fix, n=6 per arm, windows where the ISO lateral-accel clip bound excluded;
  MetaDrive's STATUS 181): at >= 8 m/s, zero-crossings/s 2.05 -> 1.41 (lower in 5/6 pairs), rms error 2.11 -> 2.02 deg
  (4/6), wheel-rate rms 19.3 -> 20.3 deg/s (+5 %, higher in 5/6). The pre-fix chain 40 zero-crossing concern
  reversed.
- **Below 8 m/s neither sim decides.** MetaDrive had 1-15 s per run there, and in the only 2 usable pairs Base had
  fewer zero-crossings. Pull-away and slow turns rest on the first drive.

**Sim: hands yield (99e807fd, tools only).** `Plant.hands_yield` (off by default) and `fit_plant(with_hands_yield)`
in `tools/lateral/lat_pid_sim.py` model the C020 firmware giving less torque while the driver's hands load the
column (`HANDS_YIELD`). With it on, the plant is closer to the logs in the 800-2000 torque bins, though it still
under-predicts there. No controller compensates for it: James's new EPS firmware will change the table.

## 188. clarity-eps-testing merged into ns-bosch-radar-testing: LatControlClarityEps becomes the default controller (owner, 2026-09-28). Static and limited road evidence (one drive, 290); not driven from this branch.

**Owner decision.** After route 290 on clarity-eps-testing (ea8e066d: no oversteer, accurate tracking in the owner's words;
0.4-0.5 deg rms hands-off tracking, one drive), the owner made James's controller the default and asked for the merge.
Merge `3b4644e0` into `d07dee21`. The two sides touch no file in common since `bfbc0361`, so the merge is textual only.

What arrives:
- `LatControlClarityEps` feedforward gated on |desired angle| (`FF_ANGLE_GATE_DEG` [10, 30]; STATUS 173). The gate is
  in `ClarityEpsLateralCore`, which only `latcontrol_clarity_eps.py` uses; LatControlPID is unchanged.
- James's turn smoothing (`Controls.update_turn_hold`, `TURN_SHAPING_TAU` 0.25 s). Active only when the built
  controller is `LatControlClarityEps`.
- `manager.py migrate_nrdr_clarity_eps_default`: on the first boot of this build, puts `NrdrLatEpsFirmwareFF=1` once
  (flag `/data/nrdr_clarity_eps_default_v1`). Turning the toggle off afterwards returns to NRDR PID and is kept. The
  owner's device already has it at 1. The compiled default in `params_keys.h` stays 0.
- lagd is upstream: the fresh-every-drive reset (3b79604f) was reverted in `3b4644e0` before the merge. The owner is
  pinning the delay instead (Use Auto-Learned Delay off, Actuator Delay 0.32 s; `lagd.py:236` publishes it as is).
  Why: the Clarity (route 352) re-learned 0.479 s from a fresh start. A rough desired-to-yaw cross-correlation gives
  0.25-0.36 s on both cars. Which estimate is right is open.

**PID work continues.** NRDR PID stays one toggle away, and its sliders and code are untouched.

**Not verified.** No test run on the merged tree; each side's tests passed on its own branch. Next drive: check
liveDelay reads 0.32 from the start, lateralControlState is the ClarityEps one, and turn-in/unwind timing against 290.

## 189. STATUS 187's MetaDrive evidence is withdrawn pending re-run, and a stronger standard-band angle feedforward does not cut PID corner overshoot. Replay/sim only; docs only.

**MetaDrive PID arms may have run the wrong controller.** Per MetaDrive Sim (John) (2026-09-28), the car-config
`params.json` from the car's initData carries `NrdrLatEpsFirmwareFF=1`. `launch_openpilot.sh` applies it at launch,
over the run's `false`, and the run's overrides are only re-applied at +30 s. controlsd can start before that (+25 s in
one logged episode), so the "PID" arms may have driven LatControlClarityEps. max|f| per run is bimodal within
arms. **Treat as withdrawn until re-run:** chains 43/44 (Base vs Simple, the ">= 8 m/s" bullet in 187) and chain 49
(steer delay 0.30 vs 0.47: "no corner benefit, more hunting").
- The output scale in 187 stays on the branch. Its remaining evidence is the lat_score gate (pass, 3 routes better,
  wobble flat) plus the owner's call. Its MetaDrive support is pending.
- The steer-delay question is open again. See 188 for the owner's pinned 0.32 s on James's controller.

**Std-band angle feedforward (replay, lat_score gate, d07dee21 PID, `NrdrLatPidFirmwareFF` 1, 11 routes).**
Route 28f logs show the angle FF supplies ~0.015 of ~0.09 output in steady 6-25 deg turns at 25-50 mph. The
integrator carries ~0.068. The test raised `LatFScaleStandard` from 115 to 200 / 300 / 450:
- The gate verdict goes neutral / pass / pass. err_rms_standard drops 3-6 % (28f 0.77 -> 0.73 at 300) and
  curve_ratio_standard moves to ~1.0. 12-20 mph dither is up 0.01-0.03 at 450.
- Per-turn overshoot at 25-50 mph is not reduced. On 28f sharp turns (n=8) it is +3.08 / +3.08 / +3.06 / +3.02 deg
  (log +2.26). Mild turns are flat to worse (28a n=21: +1.66 -> +1.78 at 450).
- The replay plant overshoots more than the car does on sharp turns, so it may not resolve this.
- No change is made. The owner can try `LatFScaleStandard` 300 on a PID drive (param only).

**Civic load constants (`CIVIC_PID_LOAD`, >= 25 mph) are uncommitted in the PID session's working tree.** Replay gate:
neutral. 28f sharp overshoot: +3.32 -> +2.99. Not shipped.

## 190. NRDR PID on the Civic: from 25 mph the firmware feedforward uses the car's own column-load fit instead of the Clarity's (owner, 2026-09-28). Replay and static evidence only; not driven.

**Why.** On route 28f, sharp corners at 25-50 mph overshoot by ~2-4 deg (the owner's "oversteer"). In those corners the
PID's firmware feedforward (`NrdrLatPidFirmwareFF`) carries the turn. It used the Clarity column-load fit (`LOAD_*`),
which on 28f's sharp corners asks ~1.5x the load the Civic used.

**What.** `CIVIC_PID_LOAD` in `nrdr_eps_firmware_ff.py` is fitted on 284, 285, 286, 287, 289, 28a, 28b. Held out one
route at a time, it beats the Clarity fit on 7 of 8. It is used only by LatControlPID's feedforward on the Civic
Bosch (C020 cal). LatControlClarityEps and the Clarity keep `LOAD_*`.
- It applies from 25 mph (`CIVIC_PID_LOAD_MIN_V`) and blends in over ~4 mph (`LOAD_BLEND_V`); a hard switch stepped the
  output by up to 0.026.
- At all speeds it slowed low-speed turns in replay (27a turn_err <12 mph 35.4 -> 36.1), hence the 25 mph floor.

**Evidence.** lat_score gate (11 routes, d07dee21 PID, `NrdrLatPidFirmwareFF` 1): neutral, no route better or worse.
Per-turn replay overshoot on 28f sharp corners (n=8): +3.3 -> +3.0 deg (logged drive +2.3). Tests: 166 pass in
`test_nrdr_eps_firmware_ff.py` + `test_latcontrol_pid_output_scale.py`.
- Not yet run in MetaDrive (its PID arms are being re-run; STATUS 189).
- Refit after any EPS reflash.

**This is the last planned NRDR PID change.** Per the owner, the lateral focus moves to LatControlClarityEps.

## 191. NRDR PID turn feedforward now comes back 0.5 s after a release while the wheel is short of the turn (`NrdrLatPidFirmwareFF`, still default off; owner, 2026-09-29). Replay and static evidence only; not driven, and the driver re-grab is unscored.

**Why.** The owner saw no benefit from `NrdrLatPidFirmwareFF`. A press drops its feedforward, and it only rejoined once
the wheel was within 10 deg of the path. After a release mid-turn the wheel is usually further behind than that, so
the plain PID carried the turn and trailed. On 28a/28b/28f, 23-33 % of turn time was latched out this way, mostly in
the first second after a release (never 3 s or more).

**What.** `nrdr_pid_eps_ff_weight` in `latcontrol_pid.py` also joins when `error * desired > 0` (the wheel is short of
the turn) and there has been no press for `NRDR_PID_EPS_FF_REJOIN_HOLD_S` = 0.5 s. The fade-in, the |desired| gate,
the 2-4 m/s speed gate and "a press drops it" are unchanged. `inf` turns the rejoin off. James's controller is not
touched. The toggle keeps its key, so a device with it off is unchanged.

**Evidence (replay, `lat_score` gate, 10 PID routes 277-28f, no driver in the loop).**

| hold-off | turn_err 12-25 mph | turn_err < 12 mph | turn_past 12-25 mph |
|---|---|---|---|
| none (old law) | 14.81 | 23.60 | 5.73 |
| 0 s | 12.84 | 22.74 | 5.95 |
| **0.5 s (shipped)** | **13.51** | **22.91** | **6.01** |
| 1.0 s | 14.16 | 23.10 | 6.00 |
| 1.5 s | 14.57 | 23.33 | 5.90 |

- Joining when *past* the path instead (negative control) changes nothing, so the "short of the turn" sign carries it.
- Wobble and dither are unchanged in every arm. Verdict: pass.
- At 12-25 mph, 93 % of the gain is on turns left hands-off for 2 s or more after the join (mean -2.62 deg, overshoot
  +0.41).
- Nearly all of the gain is on right turns (sides from the desired angle, + = left). Left-turn error barely moves.
  The overshoot rises to watch: 27a right 1.46 -> 2.79, 28b left 1.75 -> 2.43.

**Open: the re-grab.** Replay re-syncs to the log on every press, so it cannot score a driver who grabs the wheel back.
- From the road logs, 43 % of 0.5 s joins meet a press within 0.5 s (64 % at 0 s).
- 50 of those 60 re-presses push against the turn: 23 at the exit, 17 while the plan still turns in, 10 mid-turn.
- John's MetaDrive re-grab row (base / 0 s / 0.5 s, re-grab drawn from those road events) is to be preregistered and
  is not yet run.
- The owner's left turns on the PID are gentle and need little correction. Report any change by turn side.

**Correction (2026-09-29, found by James, static).** As pushed in `1a0dc489e`, the rejoin also fired at a mid-turn
engagement with no press at all. `since_press_s` is `inf` from engagement until the first press, and `inf >= 0.5` let
it through, so the feedforward faded in 20-70 deg short of the turn right at engagement. The commit text ("0.5 s after
you let go") did not describe that. Now the new branch needs `0.5 <= since_press_s < inf`: only a real release counts.
`since_press_s` itself still starts at `inf`, because the override fade reads it. A test pins the engagement case.

My replay harness had the same flaw (its clock started at 1e9 per route), so the table above included engagement joins.
Replay of the fixed code (base = the old law, same 10 routes):

| | turn_err 12-25 mph | turn_err < 12 mph | turn_past 12-25 mph |
|---|---|---|---|
| old law | 14.81 | 23.59 | 5.73 |
| 0.5 s, as pushed in 1a0dc489e (superseded) | 13.51 | 22.91 | 6.01 |
| **0.5 s, fixed** | **13.52** | **22.88** | **6.02** |

- The 12-25 mph gain is unchanged. 94.7 % of it is on turns left hands-off for 2 s or more (93.3 % before).
- Below 12 mph, the engagement join was a small *loss*: before any release, error was 0.66 deg worse and overshoot
  0.89 deg higher on those frames. The fix removes it, and those frames now match the old law exactly.
- Wobble and dither are unchanged. Verdict: pass (replay).
- The hold-off rows restated on the fixed code (turn_err 12-25 / turn_err < 12 / turn_past 12-25):
  - 0 s: 12.85 / 22.71 / 5.96.
  - 1.0 s: 14.17 / 23.07 / 6.01.
  - 1.5 s: 14.58 / 23.31 / 5.91.
  - All are within 0.03 of the flawed-harness rows, and the ranking is unchanged. Wobble and dither are unchanged, and every arm passes.
  - 0.5 s is still a pick between 0 s (the most gain) and the road re-grab rate (64 % vs 43 % of joins meet a press within 0.5 s). RG1's t0 arm is the test of it.
- A car without the modified-EPS press detector never sets `since_press_s`, so it never takes this rejoin.
- The sim re-grab row (RG1) uses base = the pre-build `latcontrol_pid.py` blob `ef28076db`, not hold = `inf`.

## 192. ICBM gas-release set speed is baked in (owner request, 2026-09-29); the `SetSpeedOnGasRelease` toggle is gone, and the ICBM description is rewritten. Static and unit evidence only.

- **Why:** `SetSpeedOnGasRelease` has defaulted on since STATUS 84, and the owner's ICBM drives since then ran with it on. STATUS 86/87/126 reworked it into the release set speed, the time-limited gas-release floor and the gas snap. The owner asked for it to be part of ICBM rather than a toggle.
- **Change:**
  - `starpilot/common/starpilot_variables.py`: `set_speed_on_gas_release` is now `redneck_cruise` on every ICBM car (Hyundai and Honda), as before by default. The param is no longer read.
  - `starpilot/common/assets/device_settings_layout.json`: the Galaxy toggle entry is removed. The ICBM description now lists what ICBM adds to stock ACC: curve and speed-limit slowdowns, the Honda far-lead slowdown, launch after a stop, gas-release set speed, Honda counter sync, and driver buttons always win. Stock ACC still does the following and braking.
  - The comments in `selfdrive/car/cruise.py` and `selfdrive/car/redneck_cruise.py` are updated.
  - The key stays in `params_keys.h` and `feasibleparams.txt`, so there is no binary rebuild. It is unused.
- **Effect:** a car that had the toggle turned off now gets the gas-release set speed, floor and snap too. No other behaviour changes.
- **Tests:** `test_redneck_cruise.py`, `test_cruise_speed.py`, the_galaxy `test_device_settings_layout.py` and `test_device_settings_frontend.py`, and `test_starpilot_variables.py`: 212 pass.

## 193. `tools/longitudinal/stock_acc_reference.py`: what stock Honda ACC would have commanded in the same situation, learned from the stock routes and scored against our planner (owner request, 2026-09-29). Replay only; a reference, not a controller.

- **What it does:**
  - Reads stock ACC's own ACCEL_COMMAND (0x1DF, bus 1 on this car) from every stock route.
  - For each 20 Hz moment of an alpha-long route, finds the 15 nearest stock moments and reports their median command now and 0.5–3 s ahead.
  - It matches on vEgo, log gap, vRel, the lead's 1 s accel slope and set speed − vEgo. aEgo is left out because it leaks braking already under way.
  - Modes:
    - `build`: npz cache per route.
    - `validate`: leave one route out.
    - `gain`: delivered aEgo against the command.
    - `compare`: per-brake-episode verdicts, `--json`.
    - `augment`: adds a `stock_nn` variant to a long_replay_viewer frames file.
  - Episodes where the nearest stock moments are far away are tagged `no stock precedent` rather than scored.
- **Corpus:** 16 stock routes (25b–292), 120k rows, about 100 min with a lead within 120 m. Only about 60 s of stock braking is below −2.5.
  - ICBM steps the stock set speed down during stock braking. On 270 that is 60 % of moving-with-lead rows, so set speed is a matching feature and its share is reported.
  - Peter's next drive is ICBM-off, for a clean base.
- **Validation (leave one route out):**
  - Command MAE 0.19 m/s² overall; 0.65 while stock is below −1.5.
  - 20 stock brake episodes: peak error median +0.05; onset error median −0.52 s, |dt| p75 1.9 s.
  - Peak level is usable; onset timing is loose.
  - Adding inverse TTC tightened onset to |dt| p75 1.46 s on the same 20 episodes. Not adopted on that little evidence.
- **Command → aEgo at a firm brake (cmd < −1.5 held 0.5 s):**
  - Stock: gain 1.09, lag 0.1 s, rms 0.22 (161 s).
  - Ours: gain 1.10, lag 0.2 s, rms 0.35 (125 s).
  - The ~1.1× over-delivery is the car under both, so a fix belongs in the command, not a gain correction.
- **Compare, 118 brake episodes on 23e, 280, 283, 286, 297 and 298:**
  - 44 have no stock precedent, mostly highway closing at 6–13 m/s from 40–95 m.
  - Of the 74 with precedent: ours harder 23, ours earlier 23, ours twitchier 18, similar 14, ours later 10, ours softer 8, stock would not brake 6.
  - Command reversals per minute with a lead: ours 10.2–13.6 on 23e/280/283/286/297 and 7.9 on 298, against stock's logged 6.4.
- **Peter's labelled moments:**
  - 283 881.5 (14:43): ours −3.50 with 2.6 s below −2.5; stock reference −2.21 with 0 s. Ours harder and 0.8 s earlier (precedent 1.3).
  - 298 bm1 = P6 (9:39.8, bookmark at route t 582.2): ours −3.50; stock reference −1.38. No stock precedent (1.8).
  - 298 789.7 (13:11.7, labelled over-braked): ours −3.50 vs −1.96, harder and 2.6 s earlier (precedent 1.2). Agrees with the label.
- **Limits:**
  - The reference is a neighbour median. It says what stock did in similar logged moments, not what it would have done here.
  - No cut-ins, stop-and-go to zero, or adjacent-lane curves are separated out yet.
  - Tests: `tools/longitudinal/tests/test_stock_acc_reference.py`, 11 pass (synthetic routes).
- **Addendum (2026-09-29, Bob's gate3 questions; replay only):**
  - **Radar-vs-model tag.** An episode is tagged `radar closing > model` when radar closing exceeds the model lead's closing on the same car by 3 m/s or more in the second before our peak.
    - Ours harder: 10 of 23 tagged.
    - Ours earlier: 7 of 23 tagged.
    - Twitchier: 4 of 24. Similar: 0 of 72. No precedent: 25 of 58.
    - Reading: the tag is concentrated where we out-brake stock and absent where we match it. But it covers under half of the harder and earlier cases, so gate3 is aimed at a real subset, not at the whole gap.
  - **Q3, does stock react to the lead braking before the gap closes?** `leadbrake` mode.
    - Event: the lead's accel slope first drops below −1.0 after a calm second, with vRel > −1 and lead within 100 m. Stock has 183 events, ours 206.
    - Stock barely moves: 1 s command drop median 0.04, ≥ 0.3 in 9 %, against a 4 % calm-lead control. With a hard lead brake (< −3) and the gap closing within 2 s, the 1 s drop is 0.04 (0 % at ≥ 0.3) and the 2 s drop is 0.19.
    - Ours moves first: in the same hard/closing case, 1 s drop median 0.68 (65 % at ≥ 0.3); control 3 %.
    - Reading: stock's decisiveness does not come from reacting to lead braking. It waits for the gap and closing speed, then commits. Ours reacts to the lead's decel within the first second, which lines up with "ours earlier".
  - **`compare --candidate trace.json`** (one route): scores a {"t", "cmd"} command trace against the stock reference in place of our logged command, for Bob's open-loop gate3+TTC variant.
  - **End-of-stop profile, `stops` mode (replay).** A stop behind a lead: speed falls from ≥ 4 m/s to < 0.2, engaged throughout, lead within 30 m. Creeps after an earlier stop are excluded. Stock n 33, ours n 32.

    | median | stock | ours |
    |---|---|---|
    | command at 4 m/s | −1.35 | −1.02 |
    | command at 2 m/s | −1.12 | −0.67 |
    | command at 1 m/s | −0.82 | −0.42 |
    | 4 m/s → stop | 4.5 s | 9.1 s |
    | time below 1 m/s | 1.3 s | 2.4 s |
    | gap at stop | 4.8 m | 5.1 m |
    | aEgo step at standstill | +1.90 | +2.09 |
    | command reversals | 0 | 1 |

    - Stock brakes about twice as firmly through the last 4 m/s and holds roughly −0.8 into the stop. Ours tapers to about −0.4 and creeps for twice as long.
    - Both stop at about the same gap, and the standstill aEgo step is similar.
    - Reading: stock's stop is short and firm; ours is a long, soft crawl with one change of mind.
  - **Route 299 added (2026-09-29), stock ACC with ICBM off:** `11c8fa231c0499ed|00000299--cfcac519b7`, 38.6 min usable with a lead. Stock stops n 45 now; the stock stop profile barely moved (command at 2 m/s −1.16, 4 m/s → stop 4.6 s).
    - The dash BRAKE warning Peter saw at bookmarks 1 and 3 is ACC_CONTROL 0x1DF `AEB_PREPARE` on bus 1, set at 11:49.9 and 19:56.7 and nowhere else. `AEB_STATUS`, `AEB_BRAKING`, `stockFcw` and `stockAeb` never set. Bob found other rare bits (0x1FA, 0x374, 0x1DF 11/13/19) toggling at the same two moments; not yet decoded.
    - Bookmark 1: stock hit its −3.0 limit within 0.5 s of the warning and was back to −0.43 by +2.5 s. Bob's shadow planner on the same moment reached −2.4 at +0.75 s and was still −1.06 at +3 s.
  - **Release time and the `ours lingers` tag (Bob's suggestion, replay):** seconds from an episode's peak until the command is back above half of it. `ours lingers` when ours takes more than 1.0 s longer than the stock reference.
    - Over the 6 alpha routes, among 70 real brakes with stock precedent (stock peak < −1.5): ours lingers in 29. Median release ours 2.1 s vs stock 0.6 s.
    - Reading: stock is sharp in and sharp out. Along with the soft stop, the long tail after the peak is the main shape difference on real brakes.
  - **Dash BRAKE warning column (2026-09-30, Bob's decode; replay):** 0x374 STALK_STATUS byte 4 (`DASHBOARD_ALERT`) == 185 on the ACC bus, about 1.1 s per warning. Cached as `alert`; caches from before it read as unknown, not "never warned" (rebuilt cache: `/tmp/sar2`).
    - Across the 17 stock routes it fires 6 times: 25e 726.3, 266 1690.3, 270 267.6 and 275.4, 299 710.1 and 1196.9.
    - `compare` reports `stock_alert_share`, the share of stock neighbours within 1 s of a warning, and tags `stock would warn` at ≥ 0.2. It also reports `dash_alert` for the route's own dash. That is n/a under openpilot long, not "never warned": our init silences the radar (disable_ecu), so the car's own FCW/AEB is off on every alpha route (Bob, route 298 seg 14 log). A missing warning there says nothing about ours being calmer.
    - 18 of 200 alpha episodes are `stock would warn`. Six are also `ours lingers`, and 4 are `ours later` (2 of them also `ours softer`): in the moments where stock would have warned, ours sometimes comes in later and trails off.
    - Limit: the precedent is only 6 warnings, so a share of 0.8 means neighbours drawn from one or two events, not a rate.
  - **`law` mode: stock's brake law by regime (2026-09-30, Peter via Bob's Bosch-A relay, ideas 2 and 3; replay, /tmp/sar2).** Each brake onset (command < −1 with a lead) is sorted into one of three regimes:
    - `threat`: a dash BRAKE warning within 1 s. Stock only; the dash is silenced under openpilot long.
    - `set speed`: set speed at or below ego speed at the onset, meaning ICBM or a set-speed cut rather than the lead.
    - `following`: everything else.
    - It reports the situation at the onset: time gap, closing speed, and TTC three ways (plain, lead-accel-extrapolated with the 1 s slope, and with aLeadK; ego at constant speed, and the lead stops at 0). It also reports peak, time to peak, half-release time, and the release measured from the moment the gap stops closing. A grid gives the share of following-regime rows that are braking, by time gap × TTC(alead), for stock and ours.
    - **Stock following** (n 69): brakes at median closing −1.3 m/s, 1.8 s gap and TTC(alead) 5.7 s, with the lead at −1.0. Peak −1.5, reached in 1.0 s.
    - **Ours** (n 121): brakes at closing −3.7 m/s, 2.5 s gap and TTC(alead) 4.4 s, with the lead at −2.2. Peak −2.0, reached in 0.7 s.
    - The grid holds the situation fixed. At TTC 4–6 s with a 1.2–3 s gap, stock is braking in 42–45 % of rows and ours in 26–33 %. At TTC 2–3 s, it is 87–98 % vs 80–82 %. (At gaps above 3 s ours brakes more: 32 % vs 22 %.)
    - **Reading:** ours starts later in the 2–6 s TTC band, then brakes harder. Stock starts earlier at a lower closing speed and brakes gently.
    - **Release, on each side's own real brakes (peak < −1.5):** about the same, 1.7 s stock (n 34) vs 1.7 s ours (n 77). Stock lets go 0.25 s after the gap stops closing (p25..p75 −0.1..0.6); ours 0.0 s (−0.8..0.3).
    - So the `ours lingers` gap above (2.1 vs 0.6 s) comes from matched situations and the kNN precedent. It does not reproduce as a difference in release law between the two sides' own brakes. Treat `ours lingers` as situation-specific (bm1-like), not a general tail.
    - **Threat** (n 3 of 6 warnings; the other 3 were stock disengaged or never went below −1):
      - 25e 12:05: a cut-in at 22 m/s, closing −11. TTC plain 7.1, alead 4.3.
      - 270 4:27: gap 0.51 s, not closing, TTC 12.
      - 299 11:49.8 (bm1): plain TTC never, TTC(alead) 3.4.
      - These fit Bob's reading of the Bosch-A doc: lead accel and time gap are inputs, and plain TTC alone explains none of them. Three events cannot fit the 4.75/4.375/4.0 thresholds; that is Bob's corpus scan.
    - **Limits:** one car. The `threat` regime is 3 events. `set speed` (n 74) is mostly ICBM stock routes. Ours is 6 alpha routes. The lead-accel TTC treats a lead that is speeding up as steady.
  - **Warning thresholds and AEB ramp (Bob's corpus scan, 2026-09-30; log evidence; `/tmp/rv/boscha/alerts_corpus.txt`, not committed):**
    - The scan finds the same 6 stock BRAKE warnings and no others. 266 1690.1 is with ACC off.
    - Chime (0x1FA byte 5 = 41/42) and AEB_PREPARE fire 0.17–0.21 s before dash 185. The tool's ±1 s window already covers that lead time.
    - Dash 187 (24 transitions, including alpha routes and standstill) is not a forward-collision warning. The tool keys on 185 only.
    - AEB_STATUS and AEB_BRAKING never assert on any route. The stock AEB brake ramp (idea 4) cannot be measured from these drives.
    - The doc's TTC ladder (4.75 / 4.375 / 4.0) does not fit:
      - 3 warnings fire at a 0.5–0.73 s gap with little or no closing (270 267.4, 299 709.9, 299 1196.7); 270 275.1 is at 1.04 s.
      - 35 stretches at TTC < 4 s have no warning; stock was already braking in them.
    - `stock would warn` needs no change. It already comes from stock neighbours matched on speed, gap, closing speed and lead accel, not from a TTC threshold. Same 6-event limit as above.

## 194. 297 48:12 harder-than-needed brake: a newborn track's birth rail, plus a short RAIL_FAST add-on (2026-09-30). Replay (car-matched 07b66420, params 2026-09-30T16:44:42Z) + log; no gate change.
- A newborn track 4 (born at 95 m) sat on the U11 birth rail (−13.5) from 48:11.97 to 48:13.33, while the true closing was about −10 by settled range and NC. This is the known class in D-068 (294 7:06); a railed birth U11 is only a bound (D-063).
- `RANGE_VREL_RAIL_FAST` armed on the 0.5 s-old track, with rail_count 3 and corr 2.74. It fitted the track's range-convergence tail (rsig 11→9; bank range −16.3 m/s, then −8.5 over the next 0.5 s), which added about 2.7 m/s of fake closing for 0.25 s (lead1 −16.2). The rsig 59/18 birth rows never reached radard.
- The ego peak of −4.4 came at 48:13.1, after the assist ended, so the rail value drove most of the brake.
- The counter-case is 298 4:10 (newborn tracks 33→35): the rail was a correct bound there, with true closing about −21.6 by range and NC.
- Open, owner's call: should RAIL_FAST require a minimum track age or a settled rsig?
- Tooling note: old `/tmp/rv/298/scan_*.pkl` clocks zeroed on the first carState, which is a per-route offset (297 +7.0 s, 298 +4.1 s vs initData route time). Do not trust times from those scans.

## 195. Short Plan Read-Ahead (`PlannerShortActionTime`) ON vs OFF on 2a6/2a4 jab windows: no effect; and the longitudinal replay plant under-reads transient brakes (owner request, 2026-09-30). Replay only.
- **Setup:** Bob's closed-loop crawler (`r6.py`), with the planner from 87505f426 (the build 2a6 ran). Each drive's own initData params. Bob's fitted table plant (`PLANT_NOGRADE=1`). Only `_short_action_t_active` is toggled.
- **Windows (11):** 5 owner bookmarks on 000002a6--f5f92c6f78 (158, 245, 326, 537, 904 s) and 6 jab spots on 000002a4--4736f8e372 (961, 1019, 1105, 1144, 1386, 1510 s). 2a4 ran 44918d843, before the toggle existed.
- **Validation:** open loop on logged state reproduces the logged `actuators.accel` with a median |err| of 0.007–0.04 (one-tick shift). At 2a6 904 s (15:10) it gives −2.65 vs −2.68 logged.
- **Result:** ON vs OFF is the same within about 0.1 in every window.
  - Means over the 11 windows, ON vs OFF: min cmd −1.89 vs −1.87; cmd jerk RMS 1.69 vs 1.68; min gap 23.6 vs 23.7 m.
  - Open loop, ON == OFF exactly at the jab onsets.
  - The only visible difference is 2a4 1510 s: −1.99 vs −1.84.
  - Raising the plant lag to 0.4 s gives the same picture.
  - **The toggle did not cause or sharpen the 2a6 jabs.** They follow real lead slowdowns. At 904 s, the radar check and the model-path check agree it was a real brake tap.
- **🟠 Plant limit — applies to every closed-loop longitudinal replay:** on transient brakes the real aEgo lags the command by about 0.5 s, then overshoots it by about 0.8–0.9 m/s². The fitted plant (LAG 0.1, TAU_BRAKE 0.2) settles on the command instead.

  | 2a6 window | cmd | real aEgo | plant aEgo |
  |---|---|---|---|
  | 904 s | −2.68 | −3.60 | −2.18 |
  | 537 s | −3.15 | −3.88 | −3.00 |
  | 326 s | −2.06 | −2.63 | −1.96 |

  - LAG 0.4 still does not reproduce the overshoot (904 s plant −2.67).
  - **So closed-loop replays under-read how harsh a jab feels.** Compare candidates on the command, not on the simulated aEgo peak.
  - A plant with a brake overshoot term is open.
