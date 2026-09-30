# Peter Bosch Stale-Preference Patch Validation

ARM A IMPLEMENTED CORRECTLY: **YES**

ARM B STRICT-RESET IMPLEMENTED: **YES**

ID3 PRESERVED: **YES**

ID50 PRESERVED: **YES**

ID24 STALE REATTACHMENT ELIMINATED: **YES**

ID53 STALE ASSOCIATION ELIMINATED: **YES**

ID27 LATER REACQUISITION WORKS: **YES**

No commit or push was performed.

## Revision and scope

- Repository worktree: `/Users/REDACTED_USER/nrdr/openpilot-boschradar-inspect`
- Branch: `night-star-bosch-radar`
- Baseline/HEAD: `42c2a191729afac16399e55496669b9dd29ee1df`
- Production change: `selfdrive/controls/radard.py` only.
- Test change: `selfdrive/controls/tests/test_radard_bosch.py` only.
- This report is stored outside the repository in `/Users/REDACTED_USER/Documents/ChatGPT/bosch_radar`.
- RadarInterface, Bosch parser, strict/relaxed thresholds, low-speed takeover rules, MPC, longitudinal planner, UI, and non-Civic-Bosch behavior were not changed.

## Concise diff explanation

The patch adds independent stale-preference evidence state for leadOne and leadTwo, gated entirely by `self.civic_bosch_radar`.

### Arm A — better challenger

- Runs only with a valid model lead and an existing preferred radar track.
- Uses the existing relaxed preferred-track gate unchanged.
- If the preferred track fails that gate, the existing Laplacian association formula is evaluated for all live tracks.
- A counter advances only when a different live track has a strictly greater score.
- Two consecutive qualifying cycles clear the preferred ID.
- Clearing the preferred ID does not select the challenger; normal strict matching remains the only acquisition path.

The association formula was factored into `vision_track_probability()` and reused by both the existing maximum-score selection and Arm A. Its mathematics are unchanged.

### Arm B — gross distance

- Runs only with a valid model lead and an existing preferred radar track.
- Computes the absolute mismatch against `lead.x[0] - RADAR_TO_CAMERA`.
- An existing strict match resets the counter, even when model uncertainty allows an absolute mismatch above 25 m.
- Otherwise, mismatch above 25 m advances the counter.
- Three consecutive qualifying cycles clear the preferred ID.

The strict-pass reset is the validated ID46 protection.

### State isolation and resets

- Challenger and gross-distance counters are independent for leadOne and leadTwo.
- Counter ownership is tied to the numeric preferred ID, so evidence for ID A cannot carry into ID B.
- Counters reset when the model lead is invalid, preference is absent, the preferred track disappears, the relevant association becomes valid again, or normal selection acquires a different radar track.
- The helper is a no-op for non-Civic-Bosch configurations.

## Unit tests

Focused tests cover:

1. Arm A clears after two qualifying challenger wins.
2. Arm A does not directly select a challenger that fails strict matching.
3. Arm A resets when the preferred track regains the relaxed match.
4. Arm B clears after three non-strict cycles above 25 m.
5. Arm B resets on a strict pass despite more than 25 m absolute disagreement.
6. Counter state does not leak between preferred IDs.
7. Non-Civic-Bosch behavior remains unchanged.
8. Duplicate leadOne/leadTwo preference state remains independent.

Result:

```text
16 passed in 0.17s
```

The checkout's committed `msgq/ipc_pyx.so` is an aarch64 Linux ELF and cannot load directly on macOS. The focused suite therefore used the already-built local macOS runtime while importing the exact target worktree source; no generated/native file was altered.

Static checks:

```text
ruff: All checks passed
git diff --check: passed
```

## Association replay method

- Replayed only locally available Peter routes `00000136` and `00000139`.
- Merged 34 route-136 segments and 44 route-139 segments, deduplicated by message timestamp.
- Preserved preferred IDs, evidence counters, model probability filters, and measured-track counts across segment boundaries.
- Reconstructed the target revision's strict matching, preferred fallback, and Civic-Bosch low-speed hardening.
- Baseline identity/type agreement with logged radarState was `99.932%` on route 136 and `99.959%` on route 139.
- Baseline and patched runs used identical recorded `carState`, `liveTracks`, and `modelV2` inputs.

## Required known-case results

| case | result | evidence |
|---|---|---|
| R136/S21 ID3 | PRESERVED | No clear; preferred `31/31` cycles and radar output `31/31`; later strict passes observed. |
| R139/S40 ID50 leadOne | PRESERVED | Preferred `100/100` cycles and radar output `98/100`; later strict passes observed. A separate leadTwo ID50 stale preference clears independently, as designed. |
| R139/S33 ID24 | CLEARED, Arm A | leadOne clears at `4657.599164`; leadTwo clears at `4657.897907`; ID24 is absent from preference/output for all 24 chatter-window cycles. |
| R139/S24 ID53 | CLEARED, Arm B | Both lead slots clear at `4167.488450`; ID53 is absent from preference/output for all 30 requested-window cycles. |
| R139 ID27 | CLEARED THEN STRICTLY REACQUIRED | Arm A clears leadOne at `5180.834015` and leadTwo at `5180.883419`; strict leadOne reacquisition begins at `5183.633792`. |
| R136 ID46 | PRESERVED BY STRICT RESET | No Arm B clear; preferred/output remains ID46 for `20/20` inspected cycles while strict-valid. |

S33 ID44 is never selected in the known chatter window without a normal strict match. There were zero non-strict ID44 outputs in that window.

## Route-level replay results

| route | metric | baseline | patched | change |
|---|---|---:|---:|---:|
| 136 | radar↔vision transitions | 151 | 149 | -2 |
| 136 | large leadOne yRel jumps ≥0.5 m | 201 | 199 | -2 |
| 136 | radar-ID switches | 4 | 4 | 0 |
| 136 | mean continuous radar run | 11.941 s | 12.084 s | +0.143 s |
| 136 | duplicate same-ID lead fraction | 50.316% | 50.314% | -0.002 pp |
| 139 | radar↔vision transitions | 200 | 187 | -13 |
| 139 | large leadOne yRel jumps ≥0.5 m | 425 | 412 | -13 |
| 139 | radar-ID switches | 1 | 1 | 0 |
| 139 | mean continuous radar run | 7.872 s | 8.321 s | +0.449 s |
| 139 | duplicate same-ID lead fraction | 36.056% | 35.783% | -0.273 pp |
| combined | radar↔vision transitions | **351** | **336** | **-15 (-4.27%)** |
| combined | large leadOne yRel jumps | **626** | **611** | **-15 (-2.40%)** |
| combined | radar-ID switches | **5** | **5** | **0** |
| combined | duplicate same-ID lead fraction | **42.218%** | **42.062%** | **-0.156 pp** |

The replay uses the production Civic-Bosch low-speed hardening rather than the older generic low-speed approximation used in an earlier diagnostic. That changes two route-139 baseline event counts, but the patch delta and combined radar↔vision reduction remain the same.

## Clear accounting

| route | Arm A | Arm B | total |
|---|---:|---:|---:|
| 136 | 14 | 11 | 25 |
| 139 | 43 | 13 | 56 |
| combined | 57 | 24 | 81 |

The strict-pass Arm B reset removes the prior benign ID46 clear. Clear totals include independent leadOne/leadTwo state, as required; a clear does not necessarily mean a currently published radar lead disappears.

## Working-tree state

```text
M selfdrive/controls/radard.py
M selfdrive/controls/tests/test_radard_bosch.py
```

Diff size: 236 insertions, 11 deletions across the two files. No repository Markdown or internal investigation document was added.

## Conclusion

The implementation matches the validated two-arm rule and preserves every required good/recoverable case. It removes the known ID24 reattachment chatter and grossly stale ID53 association without increasing radar-ID switching or disturbing duplicate lead state. The ID46 strict-reset protection works, and ID27 demonstrates that clearing stale preference does not prevent later ordinary strict reacquisition.
