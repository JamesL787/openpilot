# Honda Civic Bosch longitudinal braking — three causal proofs

## Scope and provenance

This report documents the Segment 13 braking event from:

```text
Route:        11c8fa231c0499ed/00000179--c5944a0122
Local input:  /tmp/peter_route179/rlog_new/13.rlog.zst
Event:        B2 hard-braking transition
Window:       approximately logMonoTime 872.40–872.75 s
```

The route was recorded by:

```text
gitCommit: 9f65e53c99fb6281cc0d77f7cb5308d3a742e4c2
gitBranch: ns-bosch-radar-testing
dirty:     false
```

The current local checkout used for source inspection is a different revision:

```text
gitBranch: night-star-testing
gitCommit: 8955c907a0cd21dba4a3fec6e6b9f4deaeee8bc6
```

That difference matters: a complete byte-for-byte stateful replay of the route
against the current checkout is not authoritative. The strongest evidence below
comes from the recorded messages themselves, plus the current planner's explicit
source ordering and equations.

No production code was changed, committed, or pushed.

## Executive conclusion

```text
PROOF 1 — native U11/fallback caused the floor:       NO
PROOF 2 — a post-MPC close-lead cap caused the floor: YES
PROOF 3 — EXP enabled a much lower cap than Chill:    YES
```

The causal chain is:

```text
Bosch track 26 remains selected
    -> native U11 remains available/qualified
    -> radar lead aLeadK is pessimistic (about -4 to -6.7 m/s²)
    -> EXP/tinygrad branch permits output_accel_min near -3.5 m/s²
    -> close-lead brake cap is applied after the MPC solve
    -> aTarget jumps from -0.5 to about -3.4 m/s²
    -> the next planner cycle inherits that severe output
```

The parser's adjacent-range fallback is not the trigger in this event. The
remaining radar-related concern is the second-stage lead filter's pessimistic
`aLeadK`, not a bogus one-sweep OLS/U11 fallback velocity.

## Proof 1 — this was not an adjacent-derivative/U11 fallback event

### Recorded lead identity and geometry

The selected Bosch lead remained native radar track ID 26. Both published lead
slots contained the same ID; this was duplication of the lead object, not an ID
switch or stale-preference reattachment.

At the first floor cycle:

```text
time:       872.562148
track ID:   26 (leadOne and leadTwo)
dRel:       42.524639 m
yRel:       8.391267 m
vRel:       -4.218750 m/s
vLead:      14.900833 m/s
vLeadK:     13.680532 m/s
aLeadK:     -4.004934 m/s²
modelProb:  approximately 0.955
vEgo:       approximately 19.041454 m/s
```

The range evolution was smooth across the transition. The object remained
present and selected; there was no birth, death, slot migration, or preferred
track replacement at the floor entry.

### Native velocity authority

The AUX U11 candidate was present and qualified for this event. The observed
U10 values in the surrounding rows were approximately 215–269. Some values are
above the informal 255 diagnostic band, but 255 is not the deployed parser's
invalid threshold: the active qualification policy accepts U10 through 511.

Therefore the parser did not take the adjacent range derivative because U11 was
rejected. This is also consistent with the stable published `vRel` and the
absence of a range-reset signature.

The correct conclusion is not that every radar field was ideal. The radar
second-stage lead estimate was clearly pessimistic in acceleration:

```text
model lead0 acceleration: approximately -1.72 m/s²
radar aLeadK:             approximately -3.52 to -4.34 m/s² in the transition
```

That pessimistic `aLeadK` is relevant to Proof 2. It is different from the
specific failure mode of exposing a raw -30/-40 m/s adjacent derivative.

### Rejected alternatives

There was no evidence at the transition of:

- a parser U11-to-OLS fallback;
- a one-sweep range discontinuity;
- a Bosch TRACK_ID switch;
- stale-preference reacquisition;
- a leadOne/leadTwo physical-object change.

Thus the parser fallback was not the first causal edge in this event.

## Proof 2 — the floor was inserted by a post-MPC close-lead cap

### Direct recorded comparison

The decisive row is the first floor cycle:

| log time | logged aTarget | first MPC acceleration | MPC acceleration samples | source |
|---:|---:|---:|---|---|
| 872.511184 | -0.500000 | -0.500 | `[-0.5, -0.493, -0.473, -0.443, -0.409, -0.365]` | lead0 |
| 872.562148 | -3.400111 | -0.500 | `[-0.5, -0.493, -0.473, -0.443, -0.409, -0.365]` | lead0 |
| 872.610152 | -3.405896 | -3.400 | `[-3.4, -3.206, -2.625, -1.905, -1.474, -0.920]` | lead0 |
| 872.656682 | -3.124605 | -3.406 | `[-3.406, -3.274, -2.880, -2.343, -1.867, -1.255]` | lead0 |

At `872.562148`, the first MPC acceleration is still approximately `-0.5`,
while the published target is `-3.400111`. That cannot be caused by the first
MPC sample itself. The severe value is inserted after the solver result and is
then carried into the following cycle, where the MPC starts near `-3.4`.

The current target planner implements this ordering in
`selfdrive/controls/lib/longitudinal_planner.py`:

1. The MPC and E2E targets are computed.
2. The selected target is placed in `output_a_target`.
3. `get_close_lead_brake_cap()` is evaluated for the active lead(s).
4. The planner applies:

```python
self.a_desired = min(self.a_desired, close_lead_brake_cap)
output_a_target = min(output_a_target, close_lead_brake_cap)
```

5. Only afterward is the result clipped to `output_accel_min`/`output_accel_max`.

Relevant source locations in the inspected checkout:

```text
selfdrive/controls/lib/longitudinal_planner.py:720–741   cap calculation
selfdrive/controls/lib/longitudinal_planner.py:2393–2399 lead-cap collection
selfdrive/controls/lib/longitudinal_planner.py:2431–2434 post-MPC cap application
selfdrive/controls/lib/longitudinal_planner.py:2779–2780 final clipping
```

### Numerical reconstruction of the cap

The cap function uses:

```text
lead_brake              = max(0, -aLeadK)
reaction_t              = max(longitudinalActuatorDelay, dt)
closing_speed           = max(0, vEgo - vLead)
projected_closing_speed = closing_speed + lead_brake * reaction_t
target_gap              = clip(2 + 0.2*vEgo, 2, 6)
delay_buffer            = projected_closing_speed * reaction_t
available_gap           = max(dRel - target_gap - delay_buffer, 0.5)
required_decel          = projected_closing_speed²/(2*available_gap)
                          + 0.7*lead_brake
cap                     = max(accel_min, -required_decel)
```

Using the route's `longitudinalActuatorDelay = 0.5 s`:

| time | required decel | cap with `accel_min=-0.5` | cap with `accel_min=-3.5` |
|---:|---:|---:|---:|
| 872.511184 | approximately -3.629 | -0.500 | approximately -3.500 |
| 872.562148 | approximately -3.364 | -0.500 | approximately -3.364 |
| 872.610152 | approximately -3.365 | -0.500 | approximately -3.365 |

The cap therefore explains why the output changes from `-0.5` to the
`-3.4`/`-3.5` region even though the first MPC sample remains mild. It also
explains the following-cycle behavior: once `a_desired` and the published
target have been forced strongly negative, the next MPC solve begins with a
strongly negative state.

### Action extraction is secondary here

At the first floor cycle, an offline fixed-input diagnostic estimated:

```text
direct MPC action-time acceleration: approximately -1.31 m/s²
local MPC trajectory minimum:         approximately -3.50 m/s²
get_accel_from_plan result:            not the first causal floor insertion
```

The recorded planner row is stronger evidence than the non-stateful diagnostic:
the logged first MPC sample is `-0.5`, while `aTarget` is already `-3.400111`.
Accordingly, action extraction can amplify or reshape the resulting request in
some windows, but it is not the first cause of this B2 floor transition.

## Proof 3 — EXP exposes the hard cap; Chill clamps it away

The planner has a mode-dependent lower acceleration bound. In the inspected
source, the relevant branch is:

```python
experimental_mlsim = bool(tinygrad_model and self.mlsim and self.mode != 'acc')

comfort_output_accel_min = (
  get_vehicle_min_accel(self.CP, v_ego)
  if experimental_mlsim else accel_limits_turns[0]
)
output_accel_min = comfort_output_accel_min
```

The cap itself is explicitly bounded by that value:

```python
return max(accel_min, -required_decel)
```

This produces the key mode difference:

```text
Chill/ACC-style lower bound: approximately -0.5 m/s²
EXP/tinygrad lower bound:    approximately -3.5 m/s²
```

For the same lead geometry at `872.562148`, the close-lead calculation asks for
approximately `-3.364 m/s²`:

```text
with Chill bound -0.5:  cap = max(-0.5, -3.364) = -0.5
with EXP bound -3.5:   cap = max(-3.5, -3.364) = -3.364
```

The route's `selfdriveState.experimentalMode` changes immediately before the
planner transition:

```text
experimentalMode=False through approximately 872.497780
experimentalMode=True  first observed at approximately 872.507539
```

That places the EXP transition directly ahead of the first severe planner
output at `872.562148`.

The planner also uses a different non-ACC source arbitration path:

```python
if self.mode == 'acc' or self.generation == 'v9':
  output_a_target = output_a_target_mpc
else:
  output_a_target = min(output_a_target_mpc, output_a_target_e2e)
```

That arbitration may matter in other events, but it is not needed to explain
this B2 floor. The mode-dependent lower bound plus the post-MPC close-lead cap
is sufficient.

### Tinygrad/MLSIM limitation

The raw route contains `starpilotPlan` fields such as `minAcceleration=-0.5`,
`trackingLead=True`, and a valid cruise target. Its serialized
`starpilotToggles` field is empty, so the exact internal tinygrad/MLSIM flag is
not independently recoverable from that field alone. The EXP conclusion is
therefore source-backed and strongly time-correlated with the route, but the
exact hidden MLSIM toggle is a build/runtime assumption rather than a directly
serialized fact.

## Full causal timeline

```text
Before EXP transition:
  Chill/ACC-style lower bound keeps close-lead cap at about -0.5.

EXP becomes active:
  lower bound changes to approximately -3.5.

Next planner cycle:
  same selected ID26 lead and native U11 path;
  radar aLeadK remains pessimistic;
  close-lead formula requests roughly -3.36;
  post-MPC cap changes output_a_target from the mild MPC result to about -3.4.

Following cycles:
  planner state inherits the severe target;
  MPC begins near -3.4 and the floor persists/relaxes gradually.
```

This is why Peter experiences the behavior primarily in EXP while Chill is
substantially softer, even though the lead identity is stable and the radar
parser is not taking the bogus adjacent-derivative fallback in this event.

## What is proven versus not proven

### Proven from the recorded route

- The same Bosch track ID remained selected through the transition.
- The lead was present in both lead slots; there was no identity switch.
- Native U11 was available/qualified under the deployed parser policy.
- The first floor-cycle MPC trajectory begins at approximately `-0.5`.
- The published target reaches approximately `-3.4` on that same cycle.
- Experimental mode becomes active immediately before the transition.
- Radar `aLeadK` is materially more negative than the model lead acceleration.

### Proven from planner source ordering

- Close-lead braking is calculated after the MPC/E2E target is formed.
- The cap directly lowers both `a_desired` and `output_a_target`.
- The cap is bounded by the mode-dependent `output_accel_min`.
- Final clipping happens after the cap.

### Not proven by this report

- That the radar `aLeadK` estimator is wrong in every route or every event.
- That changing U11 qualification would fix this B2 event.
- That replacing the close-lead cap is the correct production fix without
  replaying urgent-braking cases.
- That the exact hidden tinygrad/MLSIM state can be reconstructed from the
  serialized route alone.

## Bottom line

The three requested proofs line up:

1. **This event is not caused by the Bosch parser falling back to a raw,
   one-sweep adjacent derivative.** The native U11 path and stable track ID are
   present. The radar contribution that remains suspicious is pessimistic
   `aLeadK`.
2. **The first severe target is created after the MPC solve by the close-lead
   brake cap.** The first MPC acceleration is still approximately `-0.5` when
   the published `aTarget` jumps to approximately `-3.4`.
3. **EXP makes that cap actionable by allowing a lower output floor.** With the
   Chill-style `-0.5` bound the same cap is clamped away; with the EXP/tinygrad
   `-3.5` bound it reaches the planner output and is then inherited by later
   cycles.

The smallest next investigation is therefore the EXP close-lead cap versus the
radar-filter `aLeadK` input—not another U11 fallback search.

