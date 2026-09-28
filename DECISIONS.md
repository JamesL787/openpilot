# Decisions

Settled decisions and the reasoning behind them. **Do not relitigate these without new
evidence** — if you have new evidence, add a superseding entry rather than editing the old
one.

Format: what was decided, what was rejected, why.

---

### On the numbering

Numbers are **inherited from the EPS knowledge-base repo** so cross-references between the
two projects stay valid. **D-001 … D-026 are EPS firmware decisions** (hook placement, the
code cave, RWD build/verify, UART/UDS flashing, telemetry v1–v5, the gain bench) and live in
that repo, not here. They are intentionally absent rather than renumbered.

Carried into this repo: **D-009, D-010, D-027 … D-038**. New decisions made in this repo
start at **D-039** and continue upward.

---

## D-009 — Every assertion suite needs a negative control
**Decided 2026-07-28. Applies here unchanged.** A suite of passing assertions is
unfalsifiable until one of them is shown to fail when the mechanism is broken on purpose.

Concretely in this repo: if a test asserts that a gate suppresses a bad radar point, it must
be paired with a case proving the point *is* published when the gate is removed. Without it,
the passing assertions look identical to a harness that simply observes nothing. This repo
has already paid for the general version of this — see `d8604bd`, where the test evidence for
four defects was measuring a stale mirror of the value under test and passed either way.

## D-010 — Git is the timestamp; artifacts are content-addressed
**Decided 2026-07-28. Applies here unchanged.** No dates in filenames. Commit per session as
`YYYY-MM-DD <what changed>`; tag milestones; `STATUS.md` carries one `As of:` date.

In this repo, the content address of a claim is the pair **(route ID, commit SHA)**. A replay
number without both is not reproducible, because a replay result inherits the code it ran on.

## D-027 — The James night-star experiment keeps James's SR and adds observability only
**Decided 2026-08-21.** The alternate OpenPilot experiment starts from JamesL787
`night-star-bosch-radar` and retains its CR-V road-measured direct six-point steering-ratio
curve unchanged. Runtime telemetry identifies this as profile 5. Profile 4 remains reserved
for arc-dev's firmware-extracted 30-point curve, so replay cannot silently substitute one
implementation for the other.

Ported scope is additive OpenPilot PID/mechanism telemetry and the coherent nine-frame EPS
extractor. Rejected: transplanting arc-dev's firmware VGR, current-curvature hook, or
learned/fixed hybrid behaviour into this comparison branch. Those changes would prevent an
A/B evaluation of James's implementation and would violate the requested scope.

## D-028 — Bosch-A radar support remains an explicit RX-only experiment
**Decided 2026-08-22.** `HONDA_CRV_5G` may use the hand-written Bosch-A object decoder
because two content-retained vehicle logs prove the complete 16-slot object family and the
`0x2FF` sweep trigger are present on the same camera-side bus the Civic implementation
parses. The platform allowlist is **one named set shared by `CarInterface` and `radard`**, so
parser availability and the radar-rate fusion behaviour cannot silently diverge.

The tester toggle remains **required and default-off**. Rejected: enabling the decoder for
every Honda Bosch fingerprint; making it default-on; or treating stationary no-target
sentinels as proof that real target geometry, relative velocity, association, planner
consumption, or vehicle behaviour is correct. Those require a comma build followed by
controlled live-target and road validation. This change is RX-only and does not alter the
steering-ratio implementation.

> **Naming, as of this repo:** the toggle is `BoschARadar` (param `BoschARadar`; UI
> Longitudinal → "Bosch A Radar"), and the car set / prefixes are `HONDA_BOSCH_A` /
> `HONDA_BOSCH_A_*`. The earlier `NrdrBoschARadar` and `civic_bosch_radar` / `CIVIC_BOSCH_*`
> names were renamed in `af4ea03`/`cdfde65` and `fa0552c`, and the non-functional
> `BoschLong` toggle was removed at the same time. The decision above is unchanged; only the
> identifiers moved. `common/params_keys.h` also still carries a separate legacy
> `HondaBoschARadar` key — do not add a third.

## D-029 — StarPilot keeps Konik selection but adopts bounded durable registration
**Decided 2026-08-22.** The alternate branch retains StarPilot's `UseKonikServer` setting and
defaults it to Konik, while adopting arc-dev's durable identity separation under
`/data/community/identity`. A saved Konik identity is authoritative across params resets and
is never written over the factory comma identity. Explicit server switching remains
supported.

Remote registration failure must not block manager indefinitely or manufacture a plausible
random dongle ID. After a bounded attempt (60 s) it records the explicit unregistered state
so setup can continue and report the failure. Rejected: switching this branch to comma
servers, removing the independent background API, or importing arc-dev steering/controller
behaviour as part of the registration repair.

## D-030 — Night-star CR-V starts from the effective arc/nrdr lateral profile
**Decided 2026-08-22.** The modified-EPS `HONDA_CRV_5G` profile follows James
`84f1b7ec789b`: retain StarPilot's DBC-aligned `[0,3840]` identity request mapping while
importing the effective arc/nrdr four-point P/I and feedforward schedules. StarPilot's schema
lacks `kfBP/kfV`, so the feedforward curve remains an explicit runtime selector with `3.6e-6`
as the `CarParams` fallback.

The P/I fine-trim Params default to neutral 100% so the declared `CarParams` tune is the
effective baseline. A migration rewrites **only** the exact untouched legacy `100/135/200`
tuple; custom or partial profiles are preserved. Rejected: keeping the stale flat CR-V tune;
stacking hidden speed multipliers on the explicit schedule; treating the EPS-internal 30,000
command-map endpoint as an OpenPilot CAN command; or copying nrdr's 4096 request endpoint —
the source commit keeps 3840, which matches the Honda DBC's documented range. The new gain
schedules still require a new build and controlled road validation.

## D-031 — CR-V Alpha Long stays disabled until gas and brake use one command domain
**Decided 2026-09-03.** Route `00000002--aa8501ddcb` captures P061B beginning at
951.918310 s during a continuous positive-gas / negative-acceleration / brake-bit
contradiction. The installed source selects gas from adjusted `gas_force` and braking from
raw `accel`, permitting both.

Rejected: treating the fault as a device memory leak — post-engagement RAM and control-process
RSS remain stable, with no OOM or restart. Also rejected: continuing road reproduction on the
defective command path, or attributing the event to MAF/air-filter hardware without new
evidence, given the clean stock-ACC / manual-pedal A/B and the exact software-command/DTC
timing captured here.

## D-032 — Publish the P061B fix as an isolated test branch, not a merge
**Decided 2026-09-03.** `fix-honda-alpha-long-p061b` at `6e583e1c43c5…` is based exactly on
the faulting `7f2bab7b…` commit. The captured failure and the general mutual-exclusion
invariant are both regression-tested.

Rejected: merging directly into the owner's normal driving branch, or calling the change
verified from static tests. The branch stays isolated until a controlled vehicle A/B shows
that P061B does not recur and longitudinal behaviour remains acceptable.

## D-033 — Withdraw the raw-zero P061B gate after its first vehicle test
**Decided 2026-09-04.** Do not continue testing `6e583e1c43c5…` in traffic. Route
`00000003--1423cb6de2` proves it suppresses a positive calculated gas value for 23.96 of
87.3 engaged seconds and immediately reapplies hundreds of gas units across raw-acceleration
zero, creating a severe speed sawtooth. The static gas/brake mutual-exclusion tests were
necessary but insufficient.

Rejected: reading the absence of P061B in this route as validation — the engagement lasted
87.3 s against ~585 s before the original fault. Also rejected: reverting to the unmodified
`gas_force` gate, which restores the proven gas-plus-brake conflict. A future candidate must
preserve road-load compensation **and** explicit gas/brake mutual exclusion together.

## D-034 — Replace the raw-zero gate with compensated gas plus brake inhibition
**Decided 2026-09-04.** Candidate `57d77a7e1918…` restores the positive-`gas_force` decision
so freeway drag/grade compensation survives raw-acceleration zero, and adds `not braking` as
a hard gas condition. Open-loop replay restores all 1,198 gas frames removed by the defective
candidate and suppresses all 1,584 original gas-plus-brake frames.

Rejected: merely reverting `6e583e1c…`, which recreates the contradiction; or treating
open-loop command replay as proof of closed-loop behaviour. The candidate still sends
positive gas with negative non-braking `ACCEL_COMMAND`; whether Honda accepts that over a
long engagement remains a vehicle-validation question.

## D-035 — Do not tune the lead planner around the compensated-gate regression
**Decided 2026-09-04.** Route `00000004--dcc6a5b59e` shows `57d77a7e1918…` resolves the
simultaneous transmitted gas/brake command but still selects those modes from **different
physical quantities** — braking from raw `accel < −0.2`, propulsion from acceleration plus
grade and aero compensation. Of 3,916 logged brake frames, 2,336 have positive reconstructed
adjusted force. The next candidate arbitrates gas, coast and brake from that same
adjusted-force quantity with stateful hysteresis near zero, retaining explicit stop/hold and
urgent-deceleration tests.

Rejected: retuning lead-follow acceleration to conceal the downstream mode discontinuity.
The described natural behaviour is observational evidence, not a policy, and the pre-fix
controller already felt smooth before its simultaneous gas/brake defect was exposed. Also
rejected: treating the illustrative `−0.12/−0.02 m/s²` thresholds as final — they reduce
logged brake runs 39 → 11 in open-loop replay only, and this route retains just 3.70 s of
decline activity, which cannot establish a two-sided tune.

## D-036 — Test same-force-domain Bosch arbitration with a stateful coast band
**Decided 2026-09-04.** Publish experimental candidate `694046f33f58…` on the existing
isolated branch. It enters braking when adjusted tractive force falls below `−0.12 m/s²`,
releases above `−0.02 m/s²`, forces braking in the stopping state, and retains the
independent CAN-boundary rule that gas requires **both** positive adjusted force and no
brake. Propulsion, coast and ordinary braking now use one physical domain without weakening
the P061B mutual-exclusion invariant.

The thresholds are an experimental selection, not a final tune. Rejected: keeping D-034's raw
`−0.2 m/s²` brake bit, which route 4 proves taps the brake during positive tractive effort;
using adjusted force with no hysteresis, which leaves a 50 Hz sign boundary; removing the
stopping override; or claiming the candidate verified from replay — a changed command
invalidates the recorded future closed loop.

## D-037 — Base the Alpha Long PR on the current James target tip
**Decided 2026-09-05.** Merge the current JamesL787 `ns-bosch-radar-testing` tip into the
isolated candidate and open the result as PR #9. The branch contains the complete target
history through `3f27c6faaf5b…` via merge `1ddce1708420…`; the comparison is clean and
confined to the three intended Honda Alpha Long files.

Rejected: opening review from the stale `7f2bab7b…` base, which would show eight intervening
radar/planner commits as divergence; rebasing away the experimental history after an explicit
request to merge into the existing test branch; or treating `MERGEABLE` as road validation.

> **Superseded in part by D-047.** This entry recorded the planner/`radard` tests as
> "locally uncollected because the checked-in `msgq/ipc_pyx.so` is not valid Mach-O." That
> was an architecture mismatch, not a corrupt artifact, and it is solvable. Re-run those
> suites before citing this decision's coverage claims.

## D-038 — Port the final force-domain fix to StarPilot without retuning MVL
**Decided 2026-09-06.** Base the StarPilot port exactly on Firestar `Dom` `9d1043ad0114…`
and adapt the ordinary Honda Bosch path to StarPilot's `CarParams` CAN-packer API. Ordinary
Bosch passes the same adjusted force used to calculate gas magnitude, applies stateful
`−0.12/−0.02 m/s²` brake hysteresis plus stopping override, and repeats mutual exclusion at
the CAN boundary. Preserve the separate Accord 11G MVL force crossover through the optional
legacy selector; there is **no route evidence authorizing an MVL retune**.

Rejected: cherry-picking the James commit without adaptation, which would discard StarPilot's
`CarParams` interface and MVL behaviour; keeping raw acceleration as ordinary Bosch mode
selection; or describing the user-reported absence of new DTCs as proof.

---

## D-039 — Bosch-A is one 16-slot bank, and its DBC is hand-written and enforcing
**Decided in this repo; recorded 2026-09-15 from the implementation.** The wire format is a
single 16-slot object bank: four main frames per slot (`f0..f3`, one CAN ID each — **not**
sub-frames muxed onto a shared ID) plus one synchronized auxiliary frame.

This supersedes two earlier models that were wrong: `0x280/0x284/0x288/0x28C` as pieces of
one object, and `0x2C8/0x2C9` as a separate "coarse" object list. Both are retired.

`opendbc/dbc/honda_bosch_a_radar.dbc` is written by hand and is deliberately **not** produced
by the opendbc generator pipeline. It declares the real Honda rolling `COUNTER` (2-bit, last
byte bits 5:4) and `CHECKSUM` (4-bit, bits 3:0) so opendbc enforces them — verified
361,360/361,360 checksum passes and 214,400/214,400 sequential counter transitions on route
`000001df`. `FRAME_IDX` and `LIFECYCLE_RAW` are intentionally *not* named `COUNTER`.

Rejected: generating this DBC, which cannot express the bank geometry; and naming the
per-slot frame index `COUNTER`, which would make opendbc enforce the wrong field.

## D-040 — Decode constants come from the firmware, not from fitting against vision
**Decided in this repo; recorded 2026-09-15.** Range scale is `1/16` m/count and azimuth is
`(raw − 1024)/2048` rad, both derived from the firmware's own arithmetic and independently
corroborated (see `STATUS.md`). The range **offset** is a per-unit calibration value
(`−n/128`, `n` from a config word plus a runtime addend); `−3.0` is a retained plausible
value, and the right way to improve it is to **read the radar's configuration**.

Rejected: the previous `0.05712` scale, which was `16 × 0.00357` where the `0.00357` had been
solved from a **single tape point with the offset assumed** — it read ~9% short, −9 m at 60 m
against vision. Also rejected: re-fitting either constant against the vision lead. Vision is
not a range reference, and a two-parameter fit against it will silently trade scale for
offset and look good in the middle of the range.

## D-041 — A saturation rail is a bound, and it must still be published
**Decided in this repo; recorded 2026-09-15.** U11 raw `0` and `1728` mean `|vRel| ≥ 13.5 m/s`
with the exact value unrecoverable. Publish the rail. Do **not** treat it as a missing
measurement.

This was briefly routed to the coast path, and it was a safety regression. A stationary car
approached above 13.5 m/s (30 mph) rails on *every* sweep, so the coast never ended, it
outlived `BOSCH_A_STALE_S`, and the radar point was **deleted**. Route `000001f9` at 29:52:
two stopped cars, 88 of 88 active frames on the low rail with healthy u10 (78–94), range
closing smoothly at −19.4 m/s. `radard` fell back to a vision lead reporting only −11.4 m/s;
the planner commanded **0.00 while closing on stopped traffic at 76 m with a 6.6 s TTC**, and
the driver intervened. Restored in `6126e51`.

Publishing the rail understates closing (a stopped car reads as `vLead = vEgo − 13.5`) and
that understatement is why it looked worth "fixing". **Understating closing still brakes;
deleting the object does not.** Recovering the true value past the rail needs the range
channel and is deliberately left to a separate, validated change.

Generalise this: **when a radar gate is uncertain, the safe direction is to publish a
degraded bound, not to coast.** Every coast has a deadline, and the deadline deletes the car.

## D-042 — The u10 threshold is 511, validated by replay; do not re-tune it from statistics
**Decided in this repo; recorded 2026-09-15.** `BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW =
511`, validated in `d5000fe344` by replaying 20 bookmarks through the real `RadarInterface`
and `radard`'s Kalman filter, where it collapsed recorded `aLeadK` spikes up to −26.5 m/s².

It was lowered to 128 on error statistics alone. That undid the validated result and caused a
measured regression: route `000001f3` at 19:27, u10 sat above 128 for 0.81 s during a real
~8 m/s² lead decel, the coast outlived `BOSCH_A_STALE_S`, the lead was deleted, and the
vision fallback injected a 5 m / 6 m/s step driving a −3.51 m/s² brake. Restored in `39c0f09`.

The reason the statistics mislead: **u10 is confounded with dynamics.** Across 16,834 frames,
median |err| rises 0.26 → 0.88 → 1.44 → 1.95 m/s over u10 bins 0-64/64-128/128-192/192-256,
but median |a_rel| rises 0.73 → 2.13 → 3.51 → 4.59 m/s² alongside it
(`corr(u10,|err|) = +0.40`, `corr(u10,|a_rel|) = +0.43`). Holding dynamics out, the quality
signal is real (calm-frame corr +0.52) — but u10 climbs during genuine hard braking just as
reliably, so a lower threshold **preferentially rejects real manoeuvring**.

Rejected: tuning this number from offline error statistics at all. What must stay safe is the
coast path (D-041), not this threshold.

## D-043 — The multi-sweep velocity/range consistency check is one-sided
**Decided in this repo; recorded 2026-09-15.** Compare U11 against a range rate fitted over
several sweeps, and reject **only** "U11 claims more closing than the geometry supports."

Two reasons it cannot be symmetric. U11 *lags* true closure at a deceleration onset — at
`000001f3` 19:27 the fitted range rate was −6.7 m/s while U11 still read −2.08 — so a
symmetric `|U11 − rate|` test fires during genuine hard braking, exactly when the velocity
matters most. And lag can only make U11 *under*-report closing while a lead brakes, so only
the other direction is evidence of a fault. In the mirror case (a lead accelerating away) the
one-sided test coasts a more-conservative velocity, so it fails safe.

Scope, measured on nine flagged events: this catches **gross** disagreement — `000001eb` 6:59
reported `vRel −10.58 m/s` while the range was *opening* at +0.46 m/s, an 11 m/s
contradiction across a track-identity change. It deliberately does **not** chase the milder
0.6–2.5 m/s overshoots at deceleration onset; a trailing window legitimately lags during real
braking, and those are the u10 gate's job.

Rejected: relying on the per-sweep innovation gate to catch velocity error. Over one ~70 ms
sweep, even a 3 m/s error moves the range 0.2 m — far under its 2–5 m thresholds. That gate
has no power here at all.

## D-044 — The range-derived vRel is shadow telemetry; nothing consumes it
**Decided in this repo; recorded 2026-09-15.** `Track.vRelRange` publishes a 5-sample LSQ
range rate alongside the radar's own `vRel`, for **whichever** radar lead is selected — not
only Bosch-A — so the two can be compared on real drives. It is wired to **no** control path.

It is plain LSQ with **no outlier rejection**, so it inherits the range channel's ~1% gross
outliers: read it as a diagnostic, never as a validated velocity. Timestamps come from the
message clock rather than wall clock, because wall-clock time made every accelerated replay
of this field meaningless. Duplicate payloads are excluded (`measurement_update=False`) so a
repeated frame cannot forge a zero-`dt` sample, and a stale or gappy history is rejected
outside `[0.12, 0.60] s`.

Why it exists: on `000001fe/fb/fd`, U11 detects a closing onset 0.88–1.28 s late while a
4-sample range LSQ lands within 0.07–0.14 s; on `00000141` R141-8, U11 diverged from the
range by 13.7 m/s while the range moved 1.9 m.

Rejected: wiring it into control before a drive confirms or refutes it. Also rejected:
diverging `RANGE_VREL_SAMPLES` from the minimum fit length — the deque length and the minimum
are deliberately the same constant.

## D-045 — Publish RadarPoints on the last main frame, never on the auxiliary frame
**Decided in this repo; recorded 2026-09-15.** `BOSCH_A_TRIGGER_MSG` is slot 15's fourth main
frame (`0x2FF`). Passive captures prove slot 15's companion frame `0x297` follows it and is
the final observed object-family frame in a full sweep.

Rejected: making `0x297` the trigger. One dropped auxiliary frame would then suppress an
otherwise-valid point update, contradicting the parser's contract that **aux never gates
validity**. The companion data stays optional/debug-only, and that is the whole point.

## D-046 — The lead Kalman dt comes from the measured cadence, not a round number
**Decided in this repo; recorded 2026-09-15.** `BOSCH_A_FREQ_HZ = 14.35`, the median of
`0x280` inter-arrival across the retained routes (p5 12.5, p95 16.9). `radard` derives
`HONDA_BOSCH_A_RADAR_TS` from it, so the lead Kalman filter runs at the rate the radar
actually measures at.

Rejected: the previous round `15`, which ran the filter ~4.5% fast. Note this is **not** the
rate `radard` itself is driven at — that is the ~20 Hz model rate — which is why the duplicate
payload path exists at all: a Bosch-A measurement must not be absorbed twice.

## D-047 — The checked-in device binaries are aarch64; rebuild rather than reporting "cannot run"
**Decided 2026-09-15.** The `.so` files tracked in this repo (`msgq/ipc_pyx.so`,
`common/params_pyx.so`, `common/transformations/transformations.so`, the acados solvers) are
built for the comma device and are **ARM aarch64**. On any other host they fail to load with
`cannot open shared object file`, which reads like a missing file rather than a wrong
architecture.

This has been recorded at least three times across prior status writeups as "the
radard/planner tests cannot run on this checkout" — on macOS as "not a valid Mach-O binary",
on Linux as "is a Linux binary". In every case the tests were runnable after a local
`scons` build. **366 radar and longitudinal tests pass** once the tree is rebuilt; the exact
recipe is in `STATUS.md` → *Build and test environment*.

Standing rule: **do not report a test as unrunnable until you have tried that recipe**, and
do not cite a coverage claim that was skipped for this reason without re-running it.

Corollary, and it cuts the other way: **a local build overwrites 26 tracked device binaries
in place**, so after building, `git status` shows them modified. Committing them would ship
x86_64 artifacts to a branch that boots on an aarch64 comma. Stage explicitly; never
`git commit -a`. Rebuilding a device artifact on purpose is its own commit that says so
(`a972d15` is the pattern), never a side effect of running tests.

Also settled here: the repo-root **`.venv` is a tracked symlink to another machine's home
directory** (`/Users/jameslichtenstiger/nrdr/openpilot/.venv`, mode `120000`, from `82796af`)
and breaks `uv sync`. Work around it with `UV_PROJECT_ENVIRONMENT`. Rejected: deleting the
tracked link as a side effect of unrelated work — it is a one-line commit of its own, and it
belongs in a change that is about the build environment and nothing else.

## D-048 — Corroboration bounds a radar lead's braking authority; it never deletes the point
**Proposed 2026-09-15 from a six-segment corpus. NOT IMPLEMENTED — see the validation gate
at the end before writing any code.**

### The failure this addresses

On `00000231--5782493b00` t=9.1–11.35 s, radar track 6 (the selected lead, own lane) walked
its range from 71.8 to 61.6 m with U11 ramping to −6.02 m/s while the vision lead held
75–78 m at `prob` ≥ 0.93. The planner commanded −2.89 m/s², the driver felt −4.28 and
overrode with the accelerator. Track 6 then coasted, froze, and disappeared for 11.02 s.

**Every existing gate passed it, and two of them structurally cannot ever catch it:**

- The per-sweep range innovation gate saw ~0.25 m per sweep against a 2.0 m limit.
- D-043's one-sided U11-vs-range check compares two channels that **both come from the same
  radar track**. Here they agreed with each other (−6.0 vs −4.5…−6.4). When a track migrates
  onto the wrong scatterer, its range and its velocity stay mutually consistent while both
  describe the wrong object. No radar-internal cross-check can see this.
- D-044's shadow `vRelRange` is an LSQ fit of that same range, so it agrees too. **Record
  this against D-044: it can cross-check U11, but it can never cross-check the range.**
- `HONDA_BOSCH_A_GROSS_DISTANCE_M = 25.0` saw a 15.8 m peak disagreement.

### What was rejected first, on evidence

**Tightening `HONDA_BOSCH_A_GROSS_DISTANCE_M`.** Refuted by the corpus: pooled radar/vision
gap is median +4.0, p95 +14.9, max +27.7 m, and segment `9e21cac9` sustains a **median 13.8 m
gap with no hard braking at all**. A ~12 m threshold fires continuously where nothing is
wrong.

**Re-confirmed on 8 whole routes, 2026-09-17** (`an2/visgap.py`, 121 min, 140k radar-lead frames
with a confident model lead). The radar/vision range gap is banded by range: |gap| p50 is 1.4–2.5 m
below 40 m but 4.8–14.9 m at 60–80 m, and at d >= 60 m it reaches >= 10 m on **31.5 %** and >= 15 m
on **13.1 %** of radar-lead frames (5,921 / 2,463 of 18,782). Those frames are **not** where the
braking is: `aTarget <= -2 m/s^2` within the next 3 s is equal to or *lower* than the same-route
baseline on 6 of 7 routes with far-lead frames (e.g. 239 3.5 % vs 6.4 %, 23f 2.0 % vs 4.3 %; only
237 is higher, 11.3 % vs 7.9 %), and driver braking within 6 s is not elevated. So the 15.8 m gap in
the 231 fault sits inside the ordinary distribution, and no absolute-gap threshold separates it.
Caveats: the model lead is assumed to be the same object (not verified laterally), and "the radar is
right" is proxied by "nothing bad followed", not by ground truth.

**Gating on the radar/vision range-*slope* disagreement** (each sensor rating its own range over a
2 s window, so it is not range-relative in the D-044 sense). Refuted by the same run: at 60–80 m
|radar slope − vision slope| is p50 1.7–3.0 m/s and p90 5.1–9.5 m/s, because the vision range is too
jittery at that distance. The 231 fault's worst frame is 7.9 m/s, around p90 of normal driving, and
its earlier, still-faulty frames are ~2.5 m/s, at the median. No threshold both catches the fault and
stays quiet.

**Gating on d(gap)/dt.** Refuted: |d(gap)/dt| is p95 31 m/s, max 130 m/s, dominated by the
vision model's frame-to-frame `x` jitter; `9e21cac9` reaches p95 53.7 m/s while braking
normally.

**Switching to the vision lead when radar looks wrong.** Rejected on existing evidence, not
new work: D-042 records that exactly this hard switch injected a 5 m / 6 m/s step and drove a
−3.51 m/s² brake. A fix that hard-switches recreates a regression already paid for.

**Deleting or coasting the suspect point.** Rejected outright — that is D-041, and doing it
cost a driver intervention on stopped traffic.

### The decision

Give each radar track a **corroboration score**: a slow EMA of how well its range has agreed
with the vision lead while the two were matched, plus how much of its recent history was
`measured` rather than coasted. The score bounds **how much deceleration authority that track
may command** — it never gates publication.

Three properties are load-bearing:

1. **The point is always published.** Corroboration changes authority, not existence
   (D-041). A poorly-corroborated lead still brakes; it brakes *less hard*.
2. **Authority is blended, never switched.** Low corroboration moves the commanded
   deceleration toward what the vision-implied kinematics support, continuously. No
   discontinuity, so the D-042 step-injection cannot recur.
3. **Corroboration is slow; urgency overrides it.** The score must not react to
   frame-to-frame vision jitter (see the refuted gap-rate candidate), so it is an EMA over
   seconds. Any genuinely urgent geometry — small range, short TTC — **bypasses the bound
   entirely**. A fix that softens real emergency braking is worse than the fault it fixes.

### Where it lives

**`selfdrive/controls/radard.py`, not the parser.** `opendbc`'s `radar_interface.py` has no
access to `modelV2` and never should; the corroborating signal is vision, so this must sit
above the parser, after `match_vision_to_track` and before the lead is published. It is a new
layer on top of the existing chain (sentinels → innovation → u10 → D-043 rate check → rail
publish → staleness → Kalman → vision match → preferred-track staleness), and it changes none
of them.

### Validation gate — do not implement before this is satisfied

The corpus has **four** hard-brake events, one of them the fault. That cannot validate a
threshold, and D-042 is explicit about what happens when a constant is tuned on partial
evidence. Before any code:

1. Enough routes to see the radar/vision residual distribution **separately for tracks that
   later prove good versus tracks that later die** — track 6's 11 s disappearance suggests
   mortality is the label to train against.
2. A replay harness that re-runs the corpus and asserts **zero reduction in authority on the
   five benign segments** — the negative control D-009 requires.
3. The parameters chosen from that distribution, not from the single fault.

Until then this is a design, and the repo carries it as one.

## D-049 — The incarnation boundary is not published; the lead KF reset rides on one message
**Recorded 2026-09-15 from static analysis and tests against `bdf98de`. NOT IMPLEMENTED — the
fix is not the obvious one; see below.**

### What is settled

`radard`'s lead Kalman filter **is** reset across a Bosch-A track-ID reuse, but only because
the object goes absent, never because the identity changed:

- `radar_interface.py` detects the identity change (`life_delta != 2 × frame_delta`), clears
  the incarnation's range history and pops the point. The replacement needs a second coherent
  sample to mature, so the CAN identity is missing from `RadarData` for **exactly one sweep**
  and returns under the **same `trackId`**.
- `RadarD.update` pops a `Track` — and with it the `KF1D` — only when an ID is absent from the
  `liveTracks` it is looking at. **`RadarPoint` carries no incarnation field**, so the parser
  knows the identity changed and `radard` cannot.
- `card.py` publishes `liveTracks` once per sweep (~14.35 Hz); `radard` polls `modelV2` at
  `DT_MDL` (20 Hz) and reads the latest message through `SubMaster`, which keeps no queue.

So the reset is carried by **one message with nothing behind it**. Measured through the real
`RadarD` with both objects at constant velocity (true lead acceleration 0 throughout), losing
that message fabricates ≈ **0.92 m/s² of lead acceleration per m/s of identity step**, peaking
at 0.49 s and taking ~2.2 s to fall under 0.5 m/s²: a 15 m/s step yields ±13.73 m/s². D-042's
comparable 6 m/s step drove a measured −3.51 m/s² brake on `000001f3`.

Both signs are harmful: closing→opening fabricates a departing lead and **suppresses** braking;
opening→closing fabricates an approaching one and **brakes for nothing**.

Tests: `test_civic_bosch_incarnation_gap_resets_lead_kalman` and
`test_civic_bosch_coalesced_incarnation_gap_injects_phantom_lead_accel`. The first fails when
the `Track` pop is removed (D-009 negative control, checked).

### What is NOT settled, and it is the part that matters

All of the above assumes the radar **signals** the reuse. Whether Bosch-A can hand a track ID
to a new object with `life` still advancing by exactly `2 × frame_delta` — a seamless reuse —
is **not established**. If it can, nothing resets: not the parser's range history, not the lead
filter, and there is no absence for anything downstream to notice. That is D-048's "track
migrates onto the wrong scatterer" seen from the identity side, and it needs route evidence.

### Rejected: widening the gap for redundancy

The reflex fix — withhold the replacement for two sweeps instead of one so the absence cannot
be coalesced away — is **rejected outright**. It buys redundancy by deleting a radar point for
longer, which is precisely D-041 and D-042: on `000001f9` a deleted point left the planner
commanding 0.00 while closing on stopped traffic. **Never buy a reset by deleting geometry.**

The direction that does not fight D-041 is to publish the boundary as *information* — an
incarnation counter on `RadarPoint`, so `radard` can reseed the filter on an identity change
while the point keeps being published continuously. That changes a published struct and the
parser/`radard` contract, so it is a design, not a patch.

### Validation gate — do not implement before this is satisfied

1. **How often lifecycle breaks actually occur on real routes**, and whether any of them
   coincide with a hard brake. Zero observed breaks would make this a latent hazard, not a
   live one, and would change the priority.
2. **Whether seamless ID reuse exists at all** (the open question above). It decides whether an
   incarnation counter is sufficient or merely necessary.
3. A negative control per D-009: the corpus replays with **no** change in published leads on
   segments containing no incarnation break.

Until then this is a characterisation, and the repo carries it as one.

---

## D-050 — The standalone laptop tools target Python 3.9, and lint must not be allowed to break that

**Status:** settled, 2026-09-15. **Evidence:** a user's own run of `tools/konik_preflight.py`.

`tools/konik_login.py`, `tools/plain_http.py` and `tools/konik_preflight.py` exist so that a
route can be checked from a machine where the network works and the tree cannot be built. The
Python they will actually meet there is the macOS Command Line Tools build, which is **3.9** —
older than the 3.11 the rest of this repo targets.

This is not hypothetical. `pyproject.toml` sets ruff `target-version = "py311"`, so `UP017`
rewrote `datetime.now(timezone.utc)` to `datetime.now(datetime.UTC)` in the preflight. It
passed lint and every test in the container, and then died on the user's laptop before the
first check ran:

    from datetime import UTC, datetime
    ImportError: cannot import name 'UTC' from 'datetime'

The rule this settles: **the repo's Python target does not apply to these three files.**

1. `UP017` is disabled for them in `pyproject.toml`, with the reason written at the ignore.
2. `tools/lib/tests/test_py39_compat.py` enforces the constraint from two sides — it AST-parses
   each file at `feature_version=(3, 9)` (catching syntax) and greps for a list of runtime names
   that parse fine but do not exist until 3.10/3.11/3.12 (catching imports and attributes).
3. That name list is a **ratchet, not a specification**. It cannot be exhaustive. When a
   too-new name gets through and bites someone, the fix includes adding it to the list.
4. Anything new added to `STANDALONE` in that test takes on the same constraint.

**Known limit, stated per AGENTS.md §4:** there is no 3.9 interpreter in the agent container,
so this is a *static* check. It would not catch a 3.10+ behaviour change in a function that
exists in both versions. The only real verification is a user running the tool on 3.9.

## D-051 — Where the corpus harness and the recorded analysis disagree on a definition, the harness's definition is canonical and both are stated

**Settled 2026-09-15**, when `tools/bosch_a_corpus_report.py` first ran on
`00000231--5782493b00` and was compared against the 6- and 16-segment figures recorded in
`STATUS.md`. Those figures came from code that was never committed, so a disagreement had no
tie-breaker; three of them turned out to be **definitions**, not measurements.

1. **The radar/vision range gap carries `RADAR_TO_CAMERA`.** The harness computes
   `dRel - (lead.x - 1.52)`; the recorded figures computed `lead.x - dRel`. Every recorded gap
   percentile is reproduced to within 0.9–1.7 m by that 1.52 m offset (6 segments, n=4,872 here
   against 4,868 recorded). **The harness's definition wins** because it is the one
   `radard.track_matches_vision` actually applies when deciding whether a track matches a lead —
   a gap statistic that does not match the matcher cannot inform a matcher threshold.
2. **Vision-lead occupancy and residuals are cut at `prob >= 0.5`; the gap distribution at
   `>= 0.9`.** At 0.9, `ed6257ef` (segment 25) reads 1.4% vision-lead occupancy against the
   recorded 94.2%; at 0.5 it reads 94.2% exactly, its lateral residual reproduces at +4.40 m
   (recorded 4.30) and `7b76edd7` (segment 24) at +4.36 (recorded 4.33). Both cuts are now
   reported side by side rather than one being silently chosen.
3. **U11-versus-range-rate pairs use MEASURED points only, inside contiguous runs.** Coasted
   points carry a held velocity, not U11, and differentiating across a dropout or an ID reuse
   manufactures range rates — 55.8 m/s at the extreme. This one does **not** reconcile: the
   harness reports 9.16% of samples disagreeing by more than 5 m/s against a recorded 2.26%, and
   no lag at the cross-correlation peak against a recorded −4 samples. **Neither side wins**; see
   `STATUS.md`.

Rejected: quietly adopting the recorded definition to make the numbers match. The offset and the
probability cut are each a *decision about what the statistic means*, and the recorded analysis
cannot be re-run to defend its choice.

**Consequence for anyone reading older figures:** a gap quoted before this date is ~1.5 m larger
than the same gap quoted after it, and an occupancy quoted before this date is the 0.5 cut.

---

## D-052 — A saturated lifecycle counter is not an identity change; keep publishing the object

**Settled 2026-09-15 from two real drives.** `LIFECYCLE_RAW` is 12 bits and advances by 2 per frame
index, so it pins at **0xFFE (4094) after 2,047 frames — ~137 s of continuous tracking** at the
~14.9 Hz sweep rate, and never advances again. It is **not** the invalid sentinel (0xFFF): STATUS,
range, azimuth and track id all stay valid and the object is still there.

`life_delta == 2 * frame_delta` therefore failed on every subsequent sweep, clearing the range
history and popping the point each time, so no point could ever mature again.

### What that cost, measured

* `00000232--fc8dad0d18`: track 37 saturated at an age of **137.4 s** and was then observed on every
  sweep for **121.8 s (1,815 sweeps) and published on none of them**. Its last published geometry
  was dRel 38.9 m, yRel −0.1 m — the followed lead. Track 34 did the same at 137.5 s.
* `0000020a--1fd2b58eda`: track 38 was suppressed across segments 5→8 (~3.7 min, starting at route
  time 5:05.17) and track 51 across segments 11→12.
* **Corroborated by the device, not only by replay.** On the same CAN, the car (running `0083ffa`,
  without this fix) published id 38 on **0/893, 0/894, 0/893** sweeps of segments 6, 7 and 8, while
  this tree's parser publishes 93.1%, 100.0% and 82.3%. On `00000232` the recorded `liveTracks` drop
  id 37 entirely across segments 10–12 and the radar lead goes 1200/1200 → 0/1200 frames.
* The driver felt it: the 5:05 brake on `0000020a` handed from radar to vision mid-manoeuvre, and
  the 7:43 stop-and-creep ran with no radar lead at all.

### The decision

A counter pinned at its maximum **cannot testify to identity either way**, so it must not be read as
evidence of a new incarnation. `BOSCH_A_LIFE_SATURATED` makes a saturated→saturated step a
continuation. This follows D-041 and D-042: publishing a bounded/uncertain point is safer than
deleting a real object, and the range-innovation gate still judges every sweep while
`_bosch_a_retire_stale_tracks` still retires a genuine disappearance.

Verified after the change: id 37 publishes **1,788/1,815 (98.5%)** over the same window, id 34
180/184, and the five-route lifecycle census reports **zero chronic runs**.

**Rejected:** treating saturation as a death and letting the track re-birth. That is the same
"delete the geometry to buy a reset" move D-049 already rejected, and here it deletes a lead that is
still in front of the car.

### The cost, stated plainly

An ID reuse that happens **while the counter is saturated** is now undetectable at the parser: there
is no counter movement left to break. That narrows D-049's gate item 2 rather than closing it, and
it is the price of not deleting a live lead. A tracked object old enough to saturate has been held
for over two minutes, which makes a reuse at that moment less likely but not impossible.

**Negative control (D-009):** a counter frozen at any non-saturated value is still a lifecycle break
— `test_a_stuck_but_unsaturated_counter_is_still_a_lifecycle_break`.

---

## D-053 — The range-derived vRel may correct U11, in ONE direction, behind a toggle

**Decided 2026-09-16. TEST feature, default OFF, param `RangeDerivedVrel`, Bosch-A only.
Nothing here is road evidence — this has never run on a car.**

D-044 published `vRelRange` — a 5-sample LSQ of d(dRel)/dt — as shadow telemetry and said nothing
consumes it. This amends that, narrowly: on Bosch-A, with the toggle on, for the lead track only,
the range rate may make the published closing speed **more closing, never less**.

### Why the one direction

Both recorded U11 failure modes understate closing, so correcting in only that direction is the
whole safety argument:

* **The rail.** D-041, route `000001f9` at 29:52: U11 pinned at −13.5 m/s on 88 of 88 active frames
  with healthy u10 while the range closed at −19.4 m/s. D-041 publishes the rail as a **bound** and
  states that recovering the true value past it "needs the range channel and is deliberately left
  to a separate, validated change." This is that change. It is still unvalidated.
* **The lag.** D-043/D-044, routes `000001fe/fb/fd`: U11 detects a closing onset **0.88–1.28 s
  late** while a 4-sample range LSQ lands within **0.07–0.14 s**. On `000001f3` at 19:27 the fitted
  range rate was −6.7 m/s while U11 still read −2.08.

The mirror direction — letting the range say a lead is closing **less** than U11 claims — is
refused outright. That would release braking on a range channel that the branch has already
recorded being wrong, and it is the same asymmetry D-043 settled for the parser's consistency
check. An understated closing rate still brakes; an overstated one does not.

### What bounds it

Constants and their evidence live in the `RANGE_VREL_ASSIST_*` block in
`selfdrive/controls/radard.py`. In short: 2.0 m/s of sustained disagreement, held for 5 consecutive
**measured** updates (0.35 s, against a 0.88–1.28 s lag), correction capped at 8.0 m/s, and geometry
gated to dRel ≥ 8 m with |yRel| ≤ 1.5 m — an azimuth bound of 10.8°, where reading a radial rate as
a longitudinal one costs at most 1.8%.

Every rejection path clears the correction outright, so the fallback is always the shipped U11
behaviour and never a half-applied correction.

### A duplicate radard cycle is not a coast, and must hold rather than clear

`RadarD` runs at the 20 Hz model rate over a 14.35 Hz radar and collapses two different conditions
into one bit — `measured = pt.measured and radar_fresh` — so `Track.update` sees
`measurement_update = False` for both of these:

* **A duplicate cycle.** No new `liveTracks` message arrived, so `t_now` has not advanced,
  `dRel`/`yRel`/`vRel` are last cycle's values, the range history is not appended to and the lead
  KF is not stepped. Roughly one cycle in four. Nothing was re-measured, so there is nothing to
  re-decide: **hold**.
* **A coast.** A new message *did* arrive, with the parser's measured bit clear. `t_now` advances.
  **Clear** — see rejected alternative 6.

Clearing on both — which is what the first implementation did — resets the arm count roughly every
fourth cycle, so `RANGE_VREL_ASSIST_ARM_UPDATES` consecutive qualifying fits are unreachable and
the feature is **permanently inert on a car**, while every unit test that feeds one update per
radar sweep still passes. It was caught by reading the call site, not by the tests. The two are
now separated by whether `t_now` advanced, which needs no tuned constant;
`TestRadardLoopCadence` drives the real 20-Hz-over-14.35-Hz interleave and
`test_clearing_on_a_duplicate_cycle_makes_the_assist_permanently_inert` is the D-009 control that
reproduces the defect. If the call site is ever given separate bits for the two conditions, split
on those bits — the clock comparison is standing in for information `RadarD` discarded.

### The hazard, stated plainly

**This is a velocity check that reads the range channel, so a RANGE error is invisible to it.**
STATUS.md's t≈11 s false brake on `00000231--5782493b00` is exactly a range error: track 6 walked
71.8 → 61.6 m while vision held 75–78 m at prob 0.93–1.00 and the real gap grew. U11 (−6.02) and
the range fit (−4.5 to −6.4) **agreed with each other** throughout. STATUS.md already records that
the shadow channel is blind to this, and so is this assist.

`[INFERRED from the recorded figures, not replayed]` on those numbers the worst disagreement is
**+0.38 m/s against a 2.0 m/s threshold**, so the assist stays inert there — a 1.62 m/s margin.
That margin is the only thing standing between this feature and amplifying the one false brake
this branch has recorded. `TestTheRangeWalkFault` in
`selfdrive/controls/tests/test_range_vrel_assist.py` pins it. Do not "fix" that test.

### Rejected alternatives

1. **A symmetric correction.** See above: it releases braking on an unverified channel.
2. **Feeding it into track selection.** `track_matches_vision` and `vision_track_probability` keep
   scoring the **native** `self.vRel`/`self.vLead`; only `get_RadarState` and the lead KF see the
   correction. This changes what is reported *about* the chosen lead, never *which* track is
   chosen. Association is a separate problem with its own recorded failures (D-048, D-049) and
   folding an unvalidated velocity into it would make both harder to diagnose.
3. **Applying it to every track.** Restricted to `RadarD.prev_lead_track_ids`. Adjacent-lane tracks
   sit at 17–23° azimuth where a range derivative is not a longitudinal velocity at all, and the
   adjacent-lane stopped-vehicle detector reads `self.vRel` directly.
4. **Changing the capnp schema** to publish the native U11 alongside the corrected value. Not
   needed: the native `vRel` for the same track is already recoverable from `liveTracks` by
   matching `rr.points[].trackId` against `radarTrackId`, so the comparison stays fully auditable
   in a log. A schema change would mean regenerating `libcereal.a` and `cereal/gen/cpp` for a
   field that is derivable.
5. **Non-Bosch-A radars.** The evidence base is entirely Bosch-A U11. Nidec and Bosch-B have
   neither the rail nor the measured lag, and `RadarD` does not read the param at all on them.
6. **Holding the correction across a coast.** A Bosch-A coast holds `last_trusted_vrel` and is
   **not** bounded by `BOSCH_A_STALE_S` — every coast path refreshes `last_seen_nanos`, and D-052
   measured 121.8 s of continuous suppression of a followed lead. Holding a correction across that
   is unbounded staleness, so a coast clears it.
7. **Enabling by default.** It has never run on a car.

### The toggle rides the far-lead brake limit's gate, on all three surfaces

`RangeDerivedVrel` is exposed exactly where `FarLeadBrakeLimit` is: adjacent to it in
`device_settings_layout.json` under `parent_key: AdvancedLongitudinalTune` with
`settings_tier: advanced` and `requires_offroad: true`, adjacent to it in the raylib
`_bosch_a_radar_rows`, and behind the same `BoschARadarAvailable` check in Galaxy.

Galaxy's check was a hand-written `param.key === "FarLeadBrakeLimit"` branch. It is now a set,
`BOSCH_A_REQUIRED_KEYS`. **Rejected: leaving the new row ungated in Galaxy.** A row that renders on
a car whose radar cannot feed the feature is an invitation to switch on something inert and then
report that it "did nothing" — the same class of confusion open item 4 cost a day to unpick. Both
rows are Bosch-A-only TEST features acting on the same radar lead; they get one gate, not two.

**Rejected: a per-key `requires_capability` field in the layout JSON instead.** That mechanism
already exists and would be more general, but `FarLeadBrakeLimit` does not use it, and the point
of this change is that the two rows behave identically. Converting both is a separate change with
its own blast radius across every other consumer of the layout.

Pinned by `test_bosch_a_test_toggles_share_one_galaxy_location_and_gate`, which asserts the two
keys agree on all three surfaces at once, and is negative-controlled both ways (D-009).

### Known asymmetry during a coast

The lead KF is only stepped on a measurement update, so across a coast `aLeadK` stays frozen at its
corrected value while the published `vLead` reverts to native. Both are bounded, and both sit on
the conservative side (`aLeadK` more negative, `vLead` back to shipped behaviour), but they are
briefly inconsistent with each other. Recorded here rather than papered over.

**Negative control (D-009):** `TestNegativeControlOfTheTestsThemselves` breaks the arm count, the
disagreement threshold, the lateral gate and the duplicate-cycle hold in turn and asserts each
guarded property actually fails — including that lowering `MIN_DISAGREEMENT` makes the t≈11 s
fault fire, and that clearing on a duplicate cycle makes the assist unable to arm at all.

### Revision 2026-09-16 — reworked after replay; the KF no longer sees the correction

`[REPLAY, open loop — not road evidence]` The version above was replayed through the real
`radard.Track` on 232/236/237/239/23a. It helped on real rail and onset closings but fired on two
recorded range faults (the `00000232` 3:02.8 range walk and the `00000236` 22:13.6 new-track
settle, which hit the 8.0 cap), and because the corrected vLead fed the lead KF, `aLeadK` dipped by
as much as −7.2 m/s² on replay. Same toggle, same one-sided contract, now also:

- **Two fits must agree.** A 15-sample (~1 s) long range fit and the 5-sample fit must both show
  ≥2.0 m/s more closing for `ARM_UPDATES = 5` consecutive updates. At 4, the 232 walk leaks
  1.0 m/s·s and the 236 settle 0.4 — **both recorded phantoms are refused by ONE update**.
- **Clear-only guards** (they can drop a correction, never create one): long-fit residual ≤0.6 m,
  long-fit span 0.6–1.5 s, ego ≥5 m/s, and no correction that would read the lead as driving
  backwards by >5 m/s. The correction never takes the lead below 0 m/s.
- **Rail rule:** on the U11 −13.5 m/s low rail the short fit is not needed; the long fit decides.
- **The lead KF stays on native U11.** Only the published `vLead`/`vRel` is corrected, so `aLeadK`
  is unchanged by construction (100% equal on 239/23a replay). This removes the known asymmetry
  recorded above.

Cost: onset latency 0.77 s from a closing kink to first correction (0.42 s before), against a U11
onset lag of 0.88–1.28 s. Replay gain and activity per route are in STATUS.md. The t≈11 s blind
spot (range error that U11 agrees with) is unchanged.

## D-054 — A range is range-rejected only if it contradicts BOTH the last accepted sample and the last gated range

**Decided 2026-09-17. Implemented in `radar_interface.py` (`_BoschATrackState.range_anchor`,
`_bosch_a_range_innovation_rejected`). Replay and static evidence only; never run on a car.**

**The lockout.** Before this, the range-innovation gate measured every sweep against the last
ACCEPTED sample. A velocity coast (D-043 rate check, high u10, U11 and ratio unavailable) publishes
the range but appends no sample, so that baseline froze while the range kept moving. Every later
sweep was predicted across the growing gap with the U11 the coast had just distrusted. The error grew
until the gate rejected, and after `BOSCH_A_STALE_S` the point was deleted. 00000232 track 43 is the
followed lead pulling away 78.5 → 84.5 m. Four coasts grew the error 0.86 / 1.12 / 1.53 / 1.87 / 2.11 m,
and the degraded 2.0 m limit rejected it. Radar then lost the lead for 14.7 s while it closed from
84 m to 27 m. Drift from a coast, not a range step, started 57–78 % of unpublished held sweeps on four
of the five routes, and 656 of 671 held sweeps on the lead. No ≥ 5 m step ever involved the lead.
The earlier wording "never re-admitted" was overstated: about 30 % of lock episodes ended published.

**The rule.** `range_anchor` is the (time, range) of the last observation that passed the gate,
accepted or coasted. A sweep is rejected only if it fails the unchanged residual test (U11
extrapolation or the 00CA ratio, `HARD_MAX` 5.0 m, 2.0 m when degraded) against **both** the anchor
and the last accepted sample. `samples`, the velocity history, stay accepted-only. A rejected range
moves neither baseline. A coast advances the anchor only when an anchor already exists, and the first
accepted sample roots it. A lifecycle break clears it. The rejection hold's freshness is timed from
the anchor.

**Why both baselines.** Replay found two drafts wrong before this one:
1. *The anchor advanced on every coast.* A high-u10 BIRTH coast rooted the gate on a range that was
   never checked or published. On 00000239 this withheld 2,236 sweeps the old parser published.
2. *The anchor alone was the baseline.* 00000237 track 12 is a new object whose range walked out
   25.4 → 28.06 m while U11 said −2 m/s. The rate check rightly coasted the walk and the walk became
   the anchor. The real ranges (25.3 m closing to 17 m) were then rejected for 52.8 s, while the old
   parser, measuring against the accepted sample, tracked them. This is the mirror of 232 track 43:
   there U11 lagged and the range was right; here the range walked and U11 was right. Each baseline
   alone locks one of them out.

**Replay `[REPLAY]`** through one continuous real `RadarInterface` per route, old parser → this one,
on 232 / 236 / 237 / 239 / 23a:

| | 232 | 236 | 237 | 239 | 23a |
|---|---|---|---|---|---|
| published % of valid object sweeps | 85.3 → 89.8 | 83.0 → 87.2 | 73.6 → 80.2 | 83.3 → 86.5 | 75.2 → 77.1 |
| locked object-time % | 6.5 → 1.9 | 7.3 → 3.2 | 14.1 → 7.4 | 6.7 → 3.6 | 9.6 → 7.8 |
| followed lead lost ≥ 1 s (episodes / s) | 8 / 41 → 2 / 5 | 8 / 77 → 3 / 26 | 9 / 105 → 4 / 42 | 1 / 4 → 0 | 2 / 2 → 0 |
| sweeps published only by old / only by new | 0 / 1,931 | 16 / 4,024 | 88 / 3,227 | 54 / 1,173 | 10 / 422 |

Every remaining lead-lost episode also exists in the old parser, at the same length or shorter
(232 track 43: 14.7 → 4.0 s; 237 track 9: 39.9 → 21.2 s). No run of sweeps that only the old parser
published is a lead-lost episode in the census. The longest run is 237 track 36: 5.2 s at 110 m, |y| 3.1 m.
Its range walked 109.6 → 117.1 m over ~3 s against a closing U11, one walked range was accepted, and
the snap back to 111.7 m then contradicted both baselines.

**Negative controls (static, `test_bosch_a_radar.py::TestCoastAdvancesTheRangeGate`).** The recorded
reset shape after a coast never publishes and never enters either baseline. A persistent +8 m step
is still rejected.
- Against the old parser: the 232 lockout, hold and anchor tests fail, and the 237 walk test passes.
- Against the anchor-only draft: only the 237 walk test fails.
- Against the first draft: the walk and the birth-coast tests fail.

**Residuals, investigated 2026-09-17. Replay and static only; nothing below is on this branch.**
Prototypes are on `proposal/d054-residuals` (not for the car). Replay covered 00000232, 00000236,
00000237, 00000239 and 0000023a on the D-054 parser.
- *Ratio vRel timed from the last accepted sample:* no effect in replay. 0 published vRel values
  were ratio-sourced. No change proposed.
- *Lead-lost time with D-054:* 9 episodes. The D-043 rate check dominated 32.3 s of them and range
  rejection dominated 50.3 s. That led to three causes: D-055, D-056 and D-057.
- *Rejection-run census* (558 runs, D-054+D-055+D-056 parser):
  - **Returned** runs (the range came back to the old track), 13 of ≥3 sweeps: all ≤1.2 s and all
    degraded (existence 0 on 62–83% of sweeps, U11 railed at −13.5 m/s). Rejecting these is correct.
  - **Joined** runs (the anchor's U11 extrapolation eventually meets the real range), 79: 7 lead
    runs totalling 74.4 s (236 track 38, 27.4 s; 236 track 21, 20.4 s, fully degraded; 237 track 31,
    20.4 s; 237 track 36, 12.9 s).
  - **Unresolved** (the track ends still rejected), 341: 3 lead runs totalling 21.3 s.
  - A join publishes whether or not the range agrees with U11. That is existing behaviour, and it
    is how a stale anchor ends a lockout today.

## D-055 — an invalid slot must not hide an identity that is valid in another slot this sweep

**Status: on the car branch 2026-09-17 (replay and static only; no road evidence yet).** Promoted
after the two fresh routes driven on D-054 (`0756f810`) were replayed: 0000023b / 0000023e show
**0 lost point-sweeps (0 lead)**, 9 + 331 restored (33 lead on 23e), every one a coast
(measured=False), so no new measured vRel reaches control and the future-slope metric is unchanged.
The lock census on those routes (same parser the car ran): 23b 76 locked sweeps (1.3 %), 23e 2,933
(3.8 %), and **0 episodes ≥1 s with the device lead vision-matched to the locked object** on either.
The collapse loop hid the previous occupant id of any slot that turned invalid, even when that id
had just migrated to another valid slot. A coasted point then vanished while its object was still
reported.
- **Change:** the ids valid in this sweep are excluded from the hide set.
- **Static:** 4 tests. The 2 coasted-migration tests fail on D-054; the negative control (an id
  seen nowhere else is still hidden) passes on both.
- **Replay vs D-054:** 0 lost point-sweeps on all 5 routes. 2,252 point-sweeps restored, 504 of
  them lead, and every one is measured=False (a coast, carrying stale vRel). It fully restores 232
  track 43 (4.0 s), 237 track 47 (4.6 s) and 237 track 9 (21.2 s).
- **Recommendation:** the strongest candidate for the car after the fresh routes on 0756f810.

## D-056 — REJECTED IN REPLAY: fit the D-043 rate check over gated ranges

**Status: prototype only. Do not ship.**
The idea: the rate check fits `samples` (accepted only), which go stale during coasts; fit gated
ranges instead.
- **Static:** 2 tests pass.
- **Replay vs D-055:**
  - The re-admitted measured vRel disagrees with the next-1 s range slope far more than reference
    points do. >3 m/s over-close is 18–21% of new points, against 3–6% for reference.
  - p90 error is 4.9–6.4 m/s, against a reference of 3.0–5.7 m/s.
  - 0000023a loses 73 point-sweeps, 14 of them lead.
- **Why it fails:** D-043 was catching real U11 over-closing that the stale-history fit happened
  to flag. The fresh fit follows the range and lets the U11 claim through.
- **Next step:** any retry must be judged by that future-slope metric, not by lost/gained counts.

## D-057 — a lasting, clean, U11-consistent rejected step re-anchors the gate

**Status: on the car branch 2026-09-17, re-based onto D-055 alone (no `gated_ranges`; `samples` and the anchor re-root on the run's last 3 sweeps). Replay and static only; no road evidence yet.**
- **Replay vs D-055 (`ab5.py`, 2026-09-17), all seven routes 232/236/237/239/23a/23b/23e:** lost 0 and
  0 measured/unmeasured flips everywhere. Gained point-sweeps: 232 9, 236 607 (198 lead), 237 1,027
  (181 lead), 239 0, 23a 266, 23b 0, 23e 13. 236 track 38 restored 17.1 s, 237 track 31 16.2 s,
  237 track 63 51.4 s (item 22.4, non-lead, 23→20 m at ≈0 m/s). Re-admitted measured vRel vs the
  next-1 s slope: p90 2.2 / 1.1 / 2.4 m/s and >3 m/s over-close 2.2 / 2.2 / 0 % (236 / 237 / 23a)
  against reference 5.4 / 5.9 / 2.6 %. Unlike D-055 this DOES put new measured vRel into control.
- Earlier prototype record (stacked on D-056) follows.
- **Change:** a rejection run re-roots samples and anchor on its last 3 sweeps when all of these
  hold:
  - it has ≥8 sweeps and spans ≥1.5 s;
  - its last 8 sweeps are non-degraded with U11;
  - a line fit has rms ≤1 m;
  - its slope is within 3 m/s of median U11.
  Constants: `BOSCH_A_REANCHOR_MIN_SPAN_S`, `_WINDOW`, `_MAX_RMS_M`.
- **Why 1.5 s:** every returned run in the census was ≤1.2 s and degraded.
- **Static:** 4 tests.
  - The positive test publishes within 1.5–1.65 s, and fails without D-057.
  - The degraded (sigma 7; existence 0) and U11-contradicting controls never re-anchor.
  - The contradiction control needs a 25 m step: with 8.5 m the existing join publishes first.
- **Replay vs D-056:**
  - 0 lost and 0 measured/unmeasured flips on all 5 routes.
  - New measured point-sweeps: 236 602 (198 lead), 237 1,015 (181 lead), 23a 266.
  - 232 gained 9 point-sweeps; 239 is unchanged.
  - 236 track 38 is restored for 17.1 s and 237 track 31 for 16.2 s.
  - Newly measured vRel vs the next-1 s slope is as good as or better than reference: p90 2.2 / 1.0
    / 2.4 m/s, and >3 m/s over-close is 2.2% / 2.2% / 0%.
- **Limits:**
  - 236 track 21 (20.4 s) is fully degraded, and D-057 does not touch it by design.
  - Onset-to-re-anchor was about 10 s on 236_38, so its tail was degraded for a while.
- **Next step (done 2026-09-17):** re-based onto D-055 without D-056 and replayed; see status above.


---

## D-058 — BLoTv3: the t_follow pads saturate rather than vanish, and the crawl hold latches on necessity, not on the exact floor

**Decided 2026-09-17. Experimental. Implemented in `selfdrive/controls/lib/blotv3.py`. Ported from
upstream BLoTv3 (`SpysyWeeb/Spysypilot`, branch `combo-blotv3`, `necessity_supervisor.py` at
`7aed876`, design note `docs/BLoTv3.md` §3). With these fixes in, the supervisor, its module, its
class and its toggle were renamed from BLoTv2 to BLoTv3 (`BlotV2` → `BlotV3`; the stored toggle
does not carry over and starts off). Unit evidence.** (Numbered D-058 because D-055 was taken by the
radar residual proposal that landed in parallel.)

Our supervisor was a port of upstream BLoTv2 (b38e933 closed five gaps against it). Upstream has
since restructured BLoTv2 into BLoTv3, which is mostly a module split we do not want: BLoTv3 moves
stop handling into `force_stops.py`, mode selection into `conditional_experimental_mode.py`, and
model-lead anchoring into `longitudinal_lead.py`, none of which we have or consume. Two items in
that restructure are **behavioral fixes to the supervisor itself**, and those are what this entry
adopts. The rest is deliberately not ported; see the closing list.

**1. The pads no longer vanish above `ONSET_MAX_A_REQ`.** Both following-time pads were gated on
`required_decel < ONSET_MAX_A_REQ` (1.5 m/s²). That constant's real job is the emergency bypass,
which additionally needs `TTC < MIN_TTC` **and** a real braking shortfall. So whenever need rose
past 1.5 m/s² without those two also holding — a hard-braking lead still 4 s away, or a stopped
lead the MPC is already braking adequately for — the pad collapsed from its ceiling to zero in one
frame, i.e. the obstacle cost tightened exactly where need was highest. The ratio terms
(`-onset_lead_accel / ONSET_FULL_DECEL`, `required_decel / 1.2`) are already `min(..., 1.0)`, so
dropping the upper gate makes the pads saturate at 0.45 s and 0.75 s instead. Nothing here
publishes acceleration; the widest outcome is following further back.

**2. The crawl hold latches on "was necessity-braking", not on `jerk_scale == JERK_SCALE_MIN`.**
The hold that carries softening through the `v_ego <= MIN_SPEED` transition only fired when
`jerk_scale` sat *exactly* at its floor. A partially softened approach — a pad with no trigger
armed, or a slew still in flight when `v_ego` crossed `MIN_SPEED` — was not held, so the jerk cost
stiffened back toward 1.0 in the last metres of the stop, which is the ratchet the hold exists to
prevent. The hold now keys off a `_responsive` latch (set by any in-motion frame that softened the
scale or raised a pad) and clamps with `min(scale_target, self.jerk_scale)`.

**Both release paths are explicit, because a latch that cannot clear is the dangerous shape here.**
The emergency bypass clears `_responsive` in the same frame it fires, so the one case that wants the
stock jerk cost gets it. Lead loss clears it, so a re-acquired lead inherits no softening from a
vehicle that is gone. Each clearing path has a test that fails when that line is removed (D-009).

**Rejected alternative: port BLoTv3 wholesale.** BLoTv3's value is its module boundaries, and those
boundaries assume BLoTv3's own stop machinery, CEM, and model-lead anchor. Adopting them here would
replace StarPilot's lead selection and stop handling with an unvalidated upstream design in one
commit. The two fixes above are separable and stand on their own.

**Not ported, and why:**
- `force_stops.py`, `stop_helpers.py`, `conditional_experimental_mode.py` (D13–D21 upstream) — a
  stop/commitment architecture we have no equivalent of. Separate decision if ever wanted.
- `LeadDeparturePreRelease` and `model_predicted_speed()` — upstream Smooth Stops, still nothing to
  wire them into (unchanged from b38e933).
- `MODEL_LEAD_STATIONARY_NOISE` (0.2 m/s) — fixes upstream's `anchor_model_lead`, whose strict
  `vLead >= 0` gate dropped the anchor through lead launches. Our `model_predicted_acceleration`
  has no such gate, so there is no equivalent defect to fix here.
- The `emergency` → `stand_down` rename and BLoTv3's `LongitudinalPolicy` shape (pad instead of
  absolute `t_follow`). Naming, not behavior; renaming would churn the planner's call site without
  changing a frame. Our `emergency` field already reaches no alert, which is upstream's D7.
- BLoTv3's MPC/planner ownership rules (single `set_weights`, `a_prev` refill on obstacle handoff,
  removal of the third model lead, no turn budget). These are `long_mpc.py`/`longitudinal_planner.py`
  decisions in a file StarPilot has diverged from heavily; they are not supervisor behavior.

**What this is not.** Unit tests plus a supervisor-only rlog replay (2026-09-17, STATUS item 24:
jerk scale identical on every engaged lead frame of seven routes; the pad differs for 90 s in 68
hard-braking runs, and also for 1.1 s during the 239 phantom brake), on an experimental supervisor
gated behind the `BlotV3` toggle. Both changes widen following distance or keep the jerk
cost softer for longer; neither deletes a radar point or commands acceleration.

**Part 1 reverted 2026-09-28 (owner request).** The pads again apply only below
`ONSET_MAX_A_REQ` and slew back out above it. The premise above was wrong: a pad asks the MPC for
*more* following distance, so a pad held while the car already needs a hard brake makes that brake
harder, not softer. Evidence (closed-loop replay sim, not driven): route 00000294 6:25, an
owner-bookmarked bad brake (a real lead braked about -5 m/s² and then turned off at 35 m), peaked
at -4.23 with BLoTv3 on, -3.54 off and -3.90 after the revert. Across 8 hard brakes on 00000293 and
00000294, BLoTv3 on braked harder than off in every one (by 0.03-0.8 m/s²) and kept the same closest
gap within about 1 m. After the revert the gap to BLoTv3-off is 0.0-0.57 m/s², and the closest gap
moves by at most 0.9 m (293 6:54: 7.8 -> 7.4 m, off 8.8). What is left of the gap to off comes from
the model-trigger jerk softening, which is BLoTv2's original design and not reverted here. Part 2
(the crawl hold) is unchanged.

## D-059 — a join publishes measured vRel only after a fresh post-join rate fit agrees

**Status:** on the car branch 2026-09-17, replay and static only. Closes STATUS item 22.5.

**Problem.** A *join* is when the D-054 range gate passes again after a rejection run, because the
stale anchor's U11 extrapolation happens to meet the range. The D-043 rate check then fits `samples`
that straddle the gap (pre-gap ranges plus the joined range), so the gap sets the rate and a U11
that contradicts the joined range is not caught. Join census over 232/236/237/239/23a/23b/23e
(`an2/joinscan.py`): 210 joins, 9 on the lead. Measured vRel within 1 s after a join over-closes the
next-1 s range slope by >3 m/s on 21.0 % of sweeps (33.1 % when the run slope contradicts U11,
n=59) vs 4.6 % for all measured points (n=4,740). Static probe on a8370b3b: an 8.5 m step held still
with U11 −4 joins at 0.84 s and publishes measured −4.0 m/s, then coasts holding −4.0 as trusted.

**Decision.** At a join the track starts `rejoin_samples`. Until a one-sided D-043-style fit over
the last `BOSCH_A_REANCHOR_WINDOW` post-join ranges (same min-samples, min-span and 3 m/s
constants) agrees with vRel, the point is published unmeasured on its last trusted vRel, and a point
the rejection had popped is re-created (D-041/D-042: publish degraded, do not delete). `samples` is
left untouched, so the change can only withdraw measured vRel, never admit it.

**Rejected: J1, clearing `samples` at a join.** Replay (`an2/ab6.py`): 106 newly measured sweeps
over-closing on 16.0 % (236: 12/14) and 65 non-lead point-sweeps lost — the D-056 failure mode.

**Replay, J2 (shipped) vs the car branch** (`an2/ab7.py`): lost 0 and new measured 0 on every route;
gained 1 (236); 612 point-sweeps flip to unmeasured, 30 on the lead (236 12, 237 8, 23e 10). The
withdrawn measured vRel over-closed on 29.2 % (105/359 scored) vs reference 4.6 %. **Caveat:** it
also under-closed by >3 m/s on 18 % (65/359) vs reference 8.6 % — some withdrawn values were
lagging rather than over-closing, and now coast on the last trusted vRel instead.

**Road check.** Not road-validated. On the next drive: the lead lock census, any brake event within
1 s of a join, and how long lead points sit in the unmeasured rejoin hold.


## D-060 — REMOVED: the far-lead brake limit is inert on the fault it was written for

**Decision.** `FarLeadBrakeLimit` and every `FAR_LEAD_BRAKE_LIMIT_*` constant are removed from the
tree: the planner method pair, the call site, the param key, the raylib row, the Galaxy layout entry
and its Bosch-A key set, and the feature's own test file. The driver's decision that it ships default
OFF (D-053-era) is superseded — there is nothing left to switch on. This is not a re-tune and it must
not be reintroduced as one.

**Why.** Measured through the real `LongitudinalPlanner` on rlog-fed replay (STATUS item 37), the cap
forced ON differs from the cap OFF on **0 cycles in every window measured** — four windows, ~3900
planner cycles, including both of the worst far-lead hard brakes in the fleet (90 m leads reaching
`ACCEL_MIN` −3.50). It never engaged once.

The mechanism is structural, not a threshold that was set badly. `get_far_lead_brake_limit` computed
`ttc = dRel / closing` and returned `None` when `ttc < FAR_LEAD_BRAKE_LIMIT_MIN_TTC = 10.0`. The
false brakes this feature exists for are caused by the Bosch-A U11 saturation rail (item 34,
`b73dc693`), where `vRel` publishes exactly −13.50 m/s; at 90 m that reads TTC 6.7 s, so the cap
stood itself down on precisely the frames it was meant to bound. **The rail that causes the fault is
what makes the cap blind to it.** The only leads it could ever fire on are leads whose `vRel` is not
railed, i.e. genuine closers — which is why its record was one good cap against six bad ones.

**Why not raise `MIN_TTC`.** To see a railed lead the threshold would have to sit below the rail's
own TTC, which at realistic ranges is 3–7 s. A floor of −2.0 m/s² applied to every lead inside 7 s of
collision is a cap on real emergency braking. That is a worse failure than the one being fixed, and
it is the reason this is a removal and not a constant change. The known ramp-anchor defect documented
in the old evidence block is moot and is not carried forward.

**Limited road evidence, consistent but not confirming.** Routes 245, 246 and 248 ran with the cap
off (`initData`), and the driver reports the last two drives did not over-react. That is consistent
with the cap being inert; it is not evidence the cap ever helped.

**What this does not settle.** Removing the cap does not address the false brake itself. The fault is
lead *selection* — a railed off-path radar track published as a lead — and the replacement must act
there. See STATUS item 37 for why the `dyPath` deletion gate is not that replacement: on 23e it
turned a −1.55 brake into −3.50 by dropping a valid 36 m radar lead and falling through to a nearer,
faster-closing vision lead. Per D-041, the replacement must publish a **bound**, not delete a point,
and it must cover **both** published lead slots, because `LongitudinalMpc` takes `min()` over both.
That replacement is designed as **D-061**, which is proposed and not implemented.

## D-061 — PROPOSED: the dyPath replacement bounds the obstacle in the planner, and never touches selection
**Proposed 2026-09-21 from replay through the real `LongitudinalPlanner` (STATUS item 37). NOT
IMPLEMENTED — the prerequisite in "What does not exist yet" and the acceptance gates at the end both
come before any tune is written.**

### The failure this addresses

D-060 removed `FarLeadBrakeLimit` and recorded that the false brake is a lead *selection* fault: a
railed off-path radar track published as a lead. The obvious fix — reject the radar lead when
`|dyPath| >= 2.5` while vision holds an on-path lead — was scored through the real planner and
**made things worse where it mattered**. On 23e 1783–1792 s it turned a −1.55 m/s² brake into −3.50,
2.32 m/s² worse, with time below −2.5 rising 2.35 → 2.90 s.

The mechanism is recorded in item 37 and is the whole reason for this decision: the gate dropped
radar tid 25 at `dRel` 36.0 / `vRel` −2.30, which cleared `prev_lead_track_ids[i]`, which handed the
slot to a **vision** lead at `dRel` 33.4 / `vRel` −4.51 — nearer and closing twice as fast. It fired
on **1 cycle** and produced **11** divergent cycles, because the handoff outlived the condition that
caused it. This is D-041 measured rather than argued: deleting a radar point bought a harder brake.

### The decision

Keep the `dyPath` signal and throw away the gate. The replacement **bounds the obstacle in the
planner** and leaves `radarState` untouched:

> The lead is published exactly as measured, keeps its slot, and stays in `prev_lead_track_ids`.
> Attenuation happens downstream, on the per-slot obstacle. **No selection change means no handoff,
> and no handoff means the 23e mechanism cannot occur.**

Four clauses, all load-bearing:

1. **Ramp, not a step.** `offpath` is a scalar in [0,1]: zero below `|dyPath| = 2.5`, one at 3.5,
   linear between. The 2.5 floor is unchanged and is **empirical, not round** — 245 tid 29 peaks at
   2.22 and is a correct brake (item 35). Do not set it lower. The ramp also removes the cliff where
   one cycle's classification dictates the next second of behaviour, which is what turned 1 gated
   cycle into 11 on 23e. This is D-048's "blended, never switched" applied to path geometry.

2. **Vision corroboration, unchanged from item 35.** Attenuate only where vision holds its own
   on-path lead: `|dyPath_ml| < 1.5` and `mlProb >= 0.5`. Where vision disagrees, nothing happens.
   This clause is why roughly half of all off-path radar leads — the ones with no fallback at all —
   are left completely alone, and it is why the census scored *leads lost* rather than leads
   rejected. It is not decoration.

3. **Non-escalation clamp. This is the new clause and the one 23e demands.** Build `x_obstacles`
   twice, unattenuated and attenuated, and require

       min(x_obstacles_bounded[0]) >= min(x_obstacles_raw[0])

   Attenuation may only move the binding obstacle *farther*. If softening a slot would let a nearer
   column win — the other lead, cruise, or a vision lead already holding the other slot — the clamp
   yields exactly zero effect for that cycle. On 23e the fall-through is nearer, so the clamp zeroes
   it **by construction**: that episode becomes structurally untouched rather than luckily untouched,
   and the property is assertable in a unit test instead of re-measured on every tune change.

4. **A floor on the attenuation — the bound is itself bounded.** Without this, clause 3 still permits
   softening all the way out to cruise, which is deletion wearing a different hat. The off-path lead
   keeps authority down to `OFFPATH_ACCEL_FLOOR` (start at **−1.5 m/s²**) and loses only the span
   between that and `ACCEL_MIN`. Express the floor as a distance through the MPC's own algebra
   (`get_safe_obstacle_distance`, `get_stopped_equivalence_factor`) and apply it as a `max` against
   the obstacle, so the solver stays in charge and the result is a bound rather than an offset.

**What this buys, stated honestly.** Variant C (gate on both slots) cut time below −2.5 on 245
234–243 s from 2.30 s to 1.00 s while still reaching −3.50. A bound should land in that
neighbourhood. **It shortens the false brake; it does not prevent it**, and it must not be described
as prevention. The residual — 245 tid 29 at `|dyPath|` 2.22 — sits below the floor by design.

### Amendment to D-048, on new evidence

D-048 clause 3 requires that "any genuinely urgent geometry — small range, short TTC — **bypasses the
bound entirely**." **The TTC half of that is withdrawn for Bosch-A, and must not be written into this
or any Bosch-A bound.** It is the D-060 trap exactly: on the U11 saturation rail `closing` is pinned
at 13.5 m/s, so a railed off-path return at 80 m reads TTC ~6 s — "urgent" — and a TTC bypass would
therefore disable the bound on precisely the railed off-path leads it exists for, the same way
`FAR_LEAD_BRAKE_LIMIT_MIN_TTC = 10.0` disabled the cap on the far-lead brakes it was written for.
**On this platform, a TTC threshold reads the rail and not the road.**

Two replacements, and this decision takes both:

- **Gate on range and lateral geometry, not TTC.** Neither channel is corrupted by the rail.
- **Where `vRelRangeDerived` is finite, use it for closing** rather than the railed `vRel`.
  `RangeDerivedVrel` is the surviving Bosch-A toggle after `1434176b` and the only channel that sees
  past the rail (D-044, D-053). Where it is NaN, fall back to clause 3, which needs no closing
  estimate at all.

**Standing rule from this:** any TTC or closing-speed term added anywhere on this platform must state
in its comment block which channel it reads and what it does when that channel is railed. Two
features have now been lost to the unstated version of that question.

The rest of D-048 stands and is not relitigated. The two decisions bound different axes at different
layers: D-048 bounds a track's authority on **corroboration** inside `radard`, D-061 bounds a slot's
obstacle on **path geometry** inside the planner. They compose; neither subsumes the other.

### Where it lives, and why not in radard

| Piece | Location |
|---|---|
| `dyPath` / `dyPath_ml` per slot | `longitudinal_planner.py`, near the existing `scene_v_ego` block |
| `offpath` ramp, corroboration, floor → per-slot bias | new `get_offpath_lead_obstacle_bound()` in `longitudinal_vehicle_tunes.py`, shaped like `get_honda_crv_5g_stopped_lead_obstacle_bias` |
| Combining with the existing tune biases | `longitudinal_planner.py`, the `stopped_lead_obstacle_bias` block |
| Non-escalation clamp | `long_mpc.py`, immediately after the `lead_*_obstacle` construction |

D-048 argued its layer belongs in `radard` because the corroborating signal is vision and the parser
cannot see `modelV2`. That argument is satisfied by the planner too, and two things force this one
higher: the clamp of clause 3 needs `cruise_obstacle` and **both** slots' obstacle columns, which
exist only in `LongitudinalMpc.update`; and 23e is a direct demonstration that anything acting on
selection inside `radard` can trigger a handoff whose cost exceeds the fault.

Existing plumbing carries it: `LongitudinalMpc.update` already takes `lead_obstacle_bias=(0.0, 0.0)`
per slot. **Note the sign** — the MPC computes `lead_i_obstacle -= bias`, so pushing an obstacle out
requires a **negative** bias, and every existing caller passes positive values only. The clause 3
clamp is what keeps a negative one honest.

New telemetry is not optional: per-slot `dyPathBound` (metres applied) and `dyPathBoundActive`, so
the `ympc` harness can score it and on-road logs show engagement without another replay.

### What does not exist yet

**`dyPath` is not computed anywhere online.** It exists only in the host-Python analysis scripts in
the `oprad-routes` volume at `/routes/an2/`; every number in items 35–37 is an offline quantity read
out of `ycen_*.csv`. Before any tune is written:

- compute `dyPath` per slot in the planner from `sm['modelV2'].position` interpolated at the lead's
  own `dRel`, and `dyPath_ml` from the matching `leadsV3` entry;
- define the degenerate cases — `dRel` past the model horizon, short or invalid `position` — as
  returning **`nan`, where `nan` means no attenuation**, so every failure falls toward braking;
- **prove the online value reproduces the offline `ycen` value on stored frames.** Without this the
  entire census is measuring a different quantity than the one that would ship.

### Acceptance gates — do not merge before all of these

Scored as variant `D` in the existing `$T/an2/ympc.py` matrix (`A` baseline, `B`/`C` the rejected
gate on one/both slots).

| Window | Required |
|---|---|
| 23e 1783–1792 s | **0 differing cycles.** Hard gate — anything else means the clause 3 clamp is wrong. |
| 241, all 8 hard-brake episodes | 0 differing cycles |
| `000001f9` 29:52 — D-041's own regression, two stopped cars, 88/88 frames railed | untouched; proves the bound cannot engage on a railed on-path stopped car |
| 245 234–243 s | time below −2.5 m/s² at or below variant C's 1.00 s |
| Fleet, all 113 hard-brake episodes | no episode whose baseline min `aTarget` < −2.5 with an on-path lead finishes softer than −1.5 |

Plus a unit test asserting clause 3 directly against synthetic obstacle columns, so the
non-escalation property belongs to the code and not to the routes that happen to be on hand.

### Honest cost

Three interacting scalar clauses, a new online geometric quantity, and a sign-sensitive edit to the
MPC's obstacle columns, on the longitudinal path of a car that gets driven. That is materially more
machinery than the gate it replaces. The reason to accept it is that the simpler thing was measured
and it was worse.

**Replay and static evidence only. Nothing in this decision has been driven, and clause 3's
structural claim is an argument until a test asserts it.** Until then the repo carries this as a
design, exactly as it carries D-048.

## D-062 — IMPLEMENTED: a lasting, clean run of rate-check coasts re-roots the Bosch-A vRel rate fit
**Decided 2026-09-23 on parser replay (STATUS 70). Static and replay evidence only; not road-validated.**

### The failure

The one-sided multi-sweep rate check (D-054) fits `track.samples`, and `samples` grow only on
accepted sweeps. A `vrel_inconsistent` sweep coasts vRel without appending, even though its range has
passed the innovation gate. When a lead turns from opening to closing, the frozen fit keeps the old
opening rate and rejects every correct closing U11 that follows, so the check latches itself. Route
`00000258--626242f48b` 43:29-43:46: `tid 13` held vRel −0.45 for 12.7 s while its range fell
124 → 31 m and U11 read −3.3 → −8.7 m/s, then planner FCW (STATUS 69).

### The decision

Collect consecutive range-passed, rate-inconsistent sweeps in `track.inconsistent_run` (cleared by
any rate-consistent sweep, any range rejection and any lifecycle discontinuity). When that run passes
the D-057 `_bosch_a_lasting_clean_step` test — at least 8 sweeps over at least 1.5 s, none degraded,
ranges on a line within 1.0 m RMS, and that line's slope within 3.0 m/s of the median U11 — re-root
`samples` on the run's most recent points and publish the sweep's vRel as measured. No constants are
new; all are reused from D-054 and D-057.

### Rejected alternative: F1, append every coasted range to `samples`

It unfreezes the fit immediately, but it re-admits over-closing U11 (the D-056 failure). On
`00000231--5782493b00`, newly measured vRel over-closed the next-1 s range slope by more than
3 m/s on 17.0% of sweeps against 6.8% for the reference parser.

### Evidence and known cost

Paired replay over 24 cached rlog routes (STATUS 70): on each sweep where D-062 publishes a measured
vRel that the current parser coasts, the re-rooted value was nearer the next-1 s range slope on 235
sweeps and the coast on 79; lead 73 vs 35; summed absolute error 815 vs 1,627 m/s. No radar point
and no lead point is lost. **The lead result is not uniform:** route 258 is 71 to 0 for D-062, but
`00000241` is 0 to 16 and `0000024f` 2 to 19 against it, and both lose by over-closing (earlier or
harder braking, not missed braking). Three lead routes are too few to tune on (AGENTS.md rule on
constants); revisit with road evidence rather than by tightening the D-057 thresholds offline.

## D-063 — IMPLEMENTED behind `BoschARailInterval` (default off): a railed U11 is a bound, not a value, for in-path tracks
**Decided 2026-09-23 on parser replay (STATUS 82, 89, 90). Static and replay evidence only; not road-validated. Peter asked for it as a default-off toggle.**

### The failure

The Bosch-A direct closing-speed channel (U11) pins at -13.5 m/s. The D-054 range gate and the D-057
re-anchor predict the next range from U11, and with U11 pinned they predicted exactly 13.5 m/s of
closing. A lead closing faster contradicted that prediction on every sweep: route 25e track 59 went
dark from 100 m until 41 m while closing at 15-17 m/s (STATUS 82).

### The decision

When the toggle is on and the track is within 2.0 m of straight ahead
(`BOSCH_A_RAIL_INTERVAL_MAX_Y_M`), a railed U11 predicts the range interval for closing speeds from
13.5 up to 20 m/s (`BOSCH_A_DIRECT_VREL_RAIL_BOUND_MPS`) in both the gate and the re-anchor. A sweep
admitted only through that interval (`rail_admitted`) enters the D-059 hold, so the published vRel
stays unmeasured until a fresh fit agrees. Nothing about the published closing speed changes; only
whether the lead is kept does. Off by default because the evidence is replay only.

### Rejected alternatives

- **Variant D (interval for every track, STATUS 82):** loses 24-32 m off-axis points on 3 routes and
  admits adjacent-lane over-closers with U11 on the rail.
- **Variant D' (4 m gate, STATUS 89):** removes the lost points but keeps three adjacent-lane
  over-closers (25e track 6, 25f track 33, 262 track 9) inside 4 m of the path.
- **Reusing `RangeDerivedVrel` as the switch:** that toggle is already on in the car, so D'' would
  have gone live without a decision. A new key keeps it off until flipped.
- **Removing D-053 in favour of this:** the two act on different layers (D-053 publishes more closing
  on a live lead; D-063 keeps a lead alive), and D-053 fired usefully on the real closers in the
  stock-ACC routes (STATUS 90). Both stay.

### Addendum 2026-09-24 (coast bound, STATUS 92)

The two coast branches (`high_u10_live_vrel or vrel_inconsistent or rejoin_hold`, and
`u11_and_ratio_unavailable`) published `last_trusted_vrel` verbatim as `measured=False`. With the
interval on, that value can be the -13.5 rail on a point whose range is opening (25e 403 s, a
replayed -3.45 m/s^2 with no threat). With the toggle on, `_bosch_a_coast_vrel` now clamps the coast
to within 3 m/s of a least-squares range rate over the samples the coast itself gathered
(`rejoin_samples`, else `inconsistent_run`), with the D-043 minimum window (4 samples, 0.25 s) and
no one-sweep derivatives. The off path is untouched. Replay: the 25e -3.0 crossing is gone
(min -2.39), five other windows identical. The toggle stays off: the first 0.26 s after a re-root
still coast the rail, and the walk was admitted on a DEGRADED sweep where the interval widened a
2 m gate by 0.39 m. Next: use the exact rate, not the interval, on degraded sweeps.

## D-064 — IMPLEMENTED behind `ICBMFarLead` (default ON at the owner's request, stock off): ICBM lowers the set speed toward a stopping-distance speed for a closing lead the chill plan ignores
**Decided 2026-09-24 on 25e replay (STATUS 94). Replay and unit evidence only; not driven. Peter asked for it to ship on so he can try it on the next update.**

### The failure

ICBM (`RedneckCruise`) has one lead input: the chill MPC plan's minimum speed. On 25e a stopped-ish
lead was visible at 102 m closing 7.5 m/s, but the plan did not dip below the set speed until 83 m,
so the first decel press came 1.5 s after the lead was known, and the 2 steps/s set-speed walk then
ran out of road (STATUS 94). Peter's expectation, "if OP already detects a stopped lead from far
away, command stock ACC to slow down," is the right one for a system whose only brake is the ACC
set speed.

### The decision

`select_redneck_target_speed` takes `lead_speed_ms` (default `None`). With the toggle on, `card.py`
passes `leadOne.vLead`; when the lead is closing, the target is capped at
`sqrt(vLead^2 + 2 * FAR_LEAD_DECEL_MS2 * (d - max(FAR_LEAD_MIN_GAP_M, FAR_LEAD_HEADWAY_S * vLead)))`
with 1.5 m/s^2, 6 m and 1.5 s: the speed from which a comfortable decel reaches the lead's speed at
the desired gap. The cap wraps every return of the plan block, so it only ever lowers the target.
`None` (toggle off) leaves the HEAD arithmetic byte-identical (replay max difference 0.0). On 25e the
first press moves from 724.07 to 723.02 s and the simulated set runs ~2 mph lower throughout; the
317 s episode is unchanged; the 310.5 s U11-rail episode gets one extra step (D-063 interaction,
mitigated by `BoschARailInterval`).

### Rejected alternatives

- **Raising `LEAD_PROACTIVE_COAST_HEADWAY_MAX_S`.** Widens the coast for every closing lead, not just
  the far ones the plan ignores, and the coast is a fixed buffer, not a distance-aware target.
- **Lowering the hold band (`LEAD_RECOVERY_HOLD_BUFFER_MS`, 1.5 mph).** Behaviour change on every
  ICBM drive for ~0.5 s of gain; Peter said change nothing else before the bench test.
- **Changing the planner (chill MPC) floor.** Brake-affecting on alpha long too, retained for Claude
  and needs Peter's OK; the far-lead rule keeps the change inside ICBM.
- **Changing the 662 send pattern (counter sync on by default, press-release taps).** The press/step
  dump says the step rate is locked to the counter beat, so `ICBMCounterSync` is the likely fix, but
  it is measured by the STATUS 94 bench test, not assumed.

### Limits

The walk is still limited to ~2 steps/s and the 25 mph floor; a far target cannot make stock ACC
brake harder than the set-speed walk allows. The 726-728 s stall (presses out, no steps) is not
explained. If the set speed comes down too early on the road, the toggle is in Galaxy Developer
Mode as "ICBM Far-Lead Slowdown".

## D-065 — IMPLEMENTED: `ICBMCounterSync` defaults on, and ICBM yields to a held physical cruise button for the whole hold plus 0.5 s
**Decided 2026-09-24 on the bench routes 264/265 (STATUS 95) at the owner's request (STATUS 96). Sync: limited road evidence. Yield: unit evidence only; not driven.**

### The failure

Two things from the bench drives. (1) With the free-running 662 counter the set-speed walk is
~2 steps/s; with the counter synced to the car's own SCM_BUTTONS frames it is ~6-7 steps/s, and
every lead approach on ICBM depends on that rate. (2) `RedneckCruise` blocked its own presses for
only 0.5 s from a physical button's press edge and unblocked on release in the same frame. The Honda
ECU auto-repeats 5 mph per ~0.5 s under a hold, so any hold longer than 0.5 s had ICBM pressing
decel against the driver's held RES+ (264 at 101.5 s, 265 at 156.5 s); with sync on, ICBM won.

### The decision

- `ICBMCounterSync` ships on (`params_keys.h` default "1").
- ICBM yields while any cruise button is physically held (`cruise_button_held`, capped at
  `MANUAL_BUTTON_HELD_MAX_S` = 10 s so a missed release edge cannot silence ICBM for the drive) and
  for `MANUAL_BUTTON_INACTIVE_TIMER` = 0.5 s after the release edge. The driver's finger always
  wins; ICBM resumes half a second after it lifts.

### Rejected alternatives

- **Folding the ECU's 5 mph hold steps into openpilot's cruise target.** The target side
  (`selfdrive/car/cruise.py` long-press logic) already diverges from the ECU under a hold (265 at
  1:38.8: ECU at the 25 mph floor, `vCruise` at 8 km/h). Reconciling them is a target-side change on
  every car, not an ICBM change, and needs its own evidence. Left as the open residual in STATUS 96.
- **Keeping the 0.5 s window but restarting it on each ECU step.** The ECU's steps are visible only
  through the cluster speed, which lags; the press edge and release edge are the direct signal.
- **No cap on the hold.** A missed release edge (CAN drop, state reset) would then disable ICBM
  until the next press; 10 s is longer than any deliberate hold to the floor (2.5 s) or ceiling.

### Limits

The yield is measured by unit tests only. Whether a held button on the road produces a clean press
and release edge pair in `buttonEvents` on every hold is the bench question in STATUS 96.

## D-066 — `eps_tools/rwd_format/` is canonical; `eps_tools/rwd_xray/format/` is reference only
`eps_tools/rwd_xray/` is cfranyota/rwd-xray at 8d8e1ff3 (MIT), folded in on the owner's request for EPS firmware analysis. Content-hash compare against the tracked tree: `header.py` and `header_value.py` are identical to `rwd_format/`; `base.py`, `x31.py` and `x5a.py` differ only by the Python-3 port (relative imports, bytes indexing instead of `ord`). Run `rwd_format/`; keep `rwd_xray/` unedited as the source of the per-EPS patch offsets and stock/modified table values in `tools/eps_tool.py`.

## D-067 — IMPLEMENTED: no lane-change side filter in `match_vision_to_track`
StarPilot's `HumanLaneChanges` dropped every radar track on the far side of 0 m (left change: yRel <= 0,
right change: yRel >= 0) during `laneChangeStarting`. The function only pairs a radar track with the
vision lead, which must already agree in distance, speed and lateral position, so the filter never
changed which car was followed. It could only take radar away from it (D-041/D-042: a gate that can only
delete radar points is removed rather than tuned).

Evidence (replay/closed-loop sim, `--bearings 0.075`, filter re-applied vs removed, route 00000293):
- 10:49 left change: the new lane's car (track 61) crossed to y -0.2..-0.4 as we arrived. With the filter
  it went vision-only for ~2.5 s and the sim brake came late, -1.7 then -3.3; without it radar stays on,
  the brake starts earlier and plateaus at -2.6..-2.9, min gap 11.9 -> 13.1 m.
- 29:13-29:16 right change on a curve: track 12 at y +0.2..+1.2. With the filter vision put the car at
  64-79 m (radar 53-67) and the merge push held +0.5 until radar returned at 52.6 m; without it the push
  releases ~1 s earlier, the later brake is -1.79 vs -1.92, min gap 41.8 -> 43.6 m.
- 294 13:10: no difference (the lead was lost for another reason).
- Route 00000296 (device without this change): radar was on the lead for 0-53% of each of 5 lane changes.

Limits: replay only; no road drive with this change yet. `test_leads.py`
`test_match_vision_to_track_keeps_new_lane_car_during_human_lane_change` pins both 293 geometries.

## D-068 — REJECTED: publishing a high-U10 birth as a bound
Route 00000296 5:16 (route 322.05-322.38 s): track 17, the real in-lane lead slowing to a stop at
66 -> 63 m, had U10 above `BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW` on all six sweeps. With no accepted
sample and no trusted vRel, the coast path had nothing to coast, so the object was never published.

Tried (not committed): publish such a birth, in lane (|y| <= 2 m) and from 25 m out, once its own ranges fit
(4 samples over 0.25 s, rms <= 1 m), with vRel = max(live U11, fit - 3 m/s), measured=False. It did not stay
in the tree. Open-loop A/B replay, `--bearings 0.075`:
- 00000296: no gain. Track 17 was published for its last two sweeps only and never became the lead. The
  5:16 command was unchanged; 0 harder and 0 softer frames on the route.
- 00000294 7:06 (route 426.4 s): track 16, a new in-lane car at 69 m. Its birth U11 was railed at -13.5
  and its settling birth ranges fit about -13.6, so the bound was -13.5. The radar then read -5.6 a few
  sweeps later. Vision also said -13 then, so the bound was not a new wrong distance or speed on its own.
  But radard's lead filter, seeded at -13.5 and then corrected to -5.6, reported the lead ACCELERATING at
  +3..+5.7 m/s^2 for ~1.1 s (426.9-428.0). Without the change it reported -0.2 falling to -3; the lead was
  starting to brake. The command was softer by up to 0.5 m/s^2 in that window (peak -2.39 vs -2.76) and
  crossed -1.5 slightly harder at 428.0 (-1.63 vs -1.47).

Reason: a birth's own ranges are still settling (00000239), and a railed birth U11 is only a bound (D-063).
Neither gives a vRel good enough to seed radard's filter. A wrong-direction lead acceleration can make a
real brake late, which is worse than 296's extra 2 s of vision-only lead. Any retry needs a birth vRel
that does not seed the lead filter's acceleration, and a replay showing a gain. The patch is not kept;
this entry is the record. Replay evidence only.
