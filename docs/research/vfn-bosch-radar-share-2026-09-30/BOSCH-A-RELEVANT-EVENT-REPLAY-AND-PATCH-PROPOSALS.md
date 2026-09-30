# Bosch-A relevant-event replay and patch proposals

Base: `origin/ns-bosch-radar-testing` at `24f482966d812a961f0d9e8db1fe89a6dcd67467`.

No active checkout, commit, or remote branch was changed. The candidate code was evaluated in a detached temporary worktree.

## Conclusion

Two different problems remain:

1. **Repeated hard/early braking crossover:** the current Civic Bosch-A guard abandons the model-backed future trajectory when a second, binary `required_decel >= 0.5` calculation crosses its threshold. That recreates the pessimistic legacy `aLeadK` trajectory even when raw distance and TTC are not urgent.
2. **False red FCW event:** a radar track retained only by the relaxed preferred-track continuity gate can still authorize planner FCW. Continuity is useful for ordinary following, but a relaxed-only association should not independently authorize an emergency alert.

These should be fixed separately. The first proposal changes braking behavior. The second changes FCW authority only.

## Stateful replay results

All windows were replayed sequentially through the actual target-revision `LongitudinalPlanner`; planner state was carried cycle to cycle.

| Event | Current-tip min aTarget | Proposal 1 min aTarget | Floor cycles current → candidate | Finding |
|---|---:|---:|---:|---|
| R1c7 1:23:46 | 0.000 | 0.000 | 0 → 0 | Already corrected by current tip |
| R1c7 1:42:50 | -0.654 | -0.654 | 0 → 0 | Unchanged mild braking |
| R1c7 1:52:19 | -0.561 | -0.561 | 0 → 0 | Unchanged mild braking |
| R1c7 2:03:00 | +0.026 | +0.026 | 0 → 0 | Old lingering-aLeadK event already corrected |
| R1c9 2:19:46 | -3.443 | -3.133 | 3 → 0 | Model itself still asks for strong braking, but false floor is removed |
| R1c9 2:49:30 | -2.497 | -1.473 | 0 → 0 | Required-decel crossover removed |
| R1c9 2:50:18 | -0.500 | -0.500 | 0 → 0 | Unchanged |
| R1c9 2:52:53 | -0.500 | -0.500 | 0 → 0 | Unchanged |
| R1c9 2:56:45 | -2.108 | -1.880 | 0 → 0 | Moderately softened |
| R1cb 9:28 | -3.446 | -2.752 | 4 → 0 | Required-decel crossover removed |
| R1d1 3:49 red event | -3.500 | -3.500 | 2 → 2 | Separate relaxed-association/vision-transition event |
| R1d1 10:19 | -3.450 | -2.613 | 11 → 0 | Required-decel crossover removed |

Across these windows, Proposal 1 reduces exact/near-floor cycles from **20 to 2**. The two remaining floor cycles are the separate R1d1 3:49 association/vision event.

Proposal 2 changes the R1d1 3:49 planner FCW result from **one red-alert cycle to zero**. It deliberately does **not** hide or soften the two hard-braking cycles: the output switches to vision and the model geometry itself remains urgent. Solving that braking transition requires a separate association/trajectory replay, not another Bosch velocity threshold.

## Proposal 1 — raw TTC decides conservative legacy fallback

Patch: `proposal-1-bosch-raw-geometry-ttc.patch`

For real Civic Bosch-A radar leads:

- raw `dRel` and `vLead` remain the horizon-zero safety anchor;
- retain the legacy conservative radar trajectory at `dRel <= 12 m` or raw TTC `<= 5 s`;
- otherwise keep the model-backed future trajectory instead of switching on a second `required_decel` threshold.

The 5-second boundary is the existing 4-second planner FCW horizon plus one second of margin. It is a policy guard, not a claimed Bosch calibration value.

Non-Bosch and vision-lead behavior remains instruction-for-instruction unchanged.

## Proposal 2 — strict association required for Civic Bosch-A planner FCW

Patch: `proposal-2-bosch-strict-fcw-authority.patch`

For Civic Bosch-A only:

- a relaxed preferred radar association may continue to supply ordinary lead control;
- it loses `fcw` authority until it passes the existing strict D/V/Y match again;
- both MPC crash counting and final planner FCW publication honor that authority bit.

No matching threshold, preference-clear rule, parser behavior, or ordinary lead selection changes.

## Safety/invariant checks

- Urgent fallbacks preserved for `27/35/20`, `27/52/13`, `27/80/0`, and a 10 m close lead.
- Generic/non-Bosch model-trajectory rejection remains unchanged.
- Strict Civic Bosch-A radar matches retain FCW authority.
- Relaxed-only Civic Bosch-A preferred matches retain control continuity but cannot independently trigger planner FCW.
- 14 focused longitudinal tests and 2 focused radard tests passed.
- `git diff --check` passed.
- Ruff reports 10 existing findings in the touched large files; none point to the added lines. The repository-wide touched-file Ruff invocation therefore does not exit cleanly at this base revision.

## Recommendation

Apply **Proposal 1** as the braking fix and **Proposal 2** as the red-alert authority fix, keeping them as separate commits. Do not claim the R1d1 3:49 hard braking is solved: the alert is fixed, but its radar-to-vision/relaxed-association trajectory transition remains the next focused investigation.
