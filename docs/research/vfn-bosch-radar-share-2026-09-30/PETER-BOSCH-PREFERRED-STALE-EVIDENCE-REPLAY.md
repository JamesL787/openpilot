# Peter Bosch Preferred-Stale Evidence Replay

PASSING GROSS-DISTANCE THRESHOLD: **25**

ID3 PRESERVED: **YES**

ID50 PRESERVED: **YES**

ID24 CLEARED: **YES**  
ARM: **A**

ID53 CLEARED: **YES**  
ARM: **B**

ROUTE RADAR/VISION SWITCH CHANGE: **351 -> 336**

LARGE-Y JUMP CHANGE: **628 -> 613**

ARM A CLEARS: **60**

ARM B CLEARS: **25**

POSSIBLE FALSE CLEARS: **9**

STRICT REACQUISITION STILL WORKS: **YES**

EVIDENCE-BASED STALE RULE PROMISING: **YES**

READY FOR PRODUCTION PATCH: **NO**

## Method and replay fidelity

- Association logic only, based on revision `42c2a191729afac16399e55496669b9dd29ee1df`.
- The local route segments for routes 136 and 139 were merged and deduplicated by service timestamp. This preserves continuous preferred-ID, track-count, and lead-probability state across segment boundaries.
- Baseline replay identity/type fidelity against logged `radarState` was `99.930%` for route 136 and `99.932%` for route 139.
- No matching threshold, RadarInterface behavior, MPC logic, longitudinal behavior, or production file was changed.
- Counters are independent for leadOne and leadTwo. Clear totals therefore count preferred-state clears, including separate clears of the same ID in both lead slots.
- The S33 display timestamp used by the earlier scalpel is route-relative; its local segment-33 logMonoTime window is `4658.327..4659.527 s`.

## Four known cases

| gross threshold | ID3 leadOne | ID50 leadOne | ID24 leadOne | ID53 leadOne | required result |
|---:|---|---|---|---|---|
| 15 m | KEEP | KEEP | CLEAR, Arm A | CLEAR, Arm B | PASS |
| 20 m | KEEP | KEEP | CLEAR, Arm A | CLEAR, Arm B | PASS |
| 25 m | KEEP | KEEP | CLEAR, Arm A | CLEAR, Arm B | PASS |

All three thresholds satisfy the required primary-lead behavior. The largest passing value, 25 m, is therefore the conservative route-level choice.

### R136/S21 ID3

- No Arm A or Arm B clear occurs around the recoverable interval.
- ID3 remains preferred for all `31/31` evaluated model cycles and remains leadOne radar output for all `31/31`.
- Its later strict recovery remains intact.
- Reason it survives: no better-scoring challenger exists, and absolute distance mismatch remains far below 25 m.

### R139/S40 ID50

- ID50 remains in preferred state throughout all `100/100` evaluated model cycles.
- It is leadOne radar output on `98/100` cycles; its temporary vision cycles do not erase leadOne preference, and strict recovery remains possible.
- Arm B never fires because the distance mismatch remains below every tested gross threshold.
- Arm A does not clear the recoverable leadOne preference because ID43's score is vastly worse than ID50's.
- One separate **leadTwo** ID50 preference is cleared by Arm A at `5076.282288`. This does not clear the known leadOne association, but it is retained in route-level clear/false-clear accounting rather than hidden.

### R139/S33 ID24

- Arm A clears leadOne ID24 at log time `4657.599164`, before the established `4658.327..4659.527` chatter window.
- ID24 is not preferred or radar output anywhere in the 24-cycle chatter window.
- ID24 cannot reattach through preferred fallback after the clear.
- ID44 is not selected because it still fails the unchanged strict matching gate.
- A separate leadTwo ID24 preference is cleared by Arm A at `4657.897907`.

### R139/S24 ID53

Arm B clears the stale 38–43 m disagreement at every allowed threshold:

| threshold | leadOne clear time | arm |
|---:|---:|---|
| 15 m | 4154.138819 | B |
| 20 m | 4166.388362 | B |
| 25 m | 4167.488450 | B |

At 25 m, ID53 is already cleared before the requested `4170.099` interval and remains absent from preference and radar output throughout its 30 evaluated cycles. Both lead slots independently clear the stale ID53 preference at the same time.

## Route 136/139 regression at 25 m

| route | metric | baseline | candidate | change |
|---|---|---:|---:|---:|
| 136 | radar↔vision transitions | 149 | 147 | -2 |
| 136 | large leadOne yRel jumps ≥0.5 m | 201 | 199 | -2 |
| 136 | radar-ID switches | 4 | 4 | 0 |
| 136 | mean continuous radar run | 12.085 s | 12.232 s | +0.147 s |
| 136 | leadOne/leadTwo same-ID fraction | 50.316% | 50.314% | -0.002 pp |
| 139 | radar↔vision transitions | 202 | 189 | -13 |
| 139 | large leadOne yRel jumps ≥0.5 m | 427 | 414 | -13 |
| 139 | radar-ID switches | 1 | 1 | 0 |
| 139 | mean continuous radar run | 7.820 s | 8.262 s | +0.442 s |
| 139 | leadOne/leadTwo same-ID fraction | 36.058% | 35.785% | -0.273 pp |
| combined | radar↔vision transitions | 351 | 336 | -15 (-4.27%) |
| combined | large yRel jumps | 628 | 613 | -15 (-2.39%) |
| combined | duplicate same-ID fraction | 42.219% | 42.062% | -0.157 pp |

The candidate does not increase radar-ID switching. Continuous radar runs become slightly longer, despite clearing stale preferences, because the S33-style reattachment chatter is reduced.

## Clear accounting

| route | Arm A challenger clears | Arm B gross-distance clears | total |
|---|---:|---:|---:|
| 136 | 14 | 12 | 26 |
| 139 | 46 | 13 | 59 |
| total | **60** | **25** | **85** |

The high count does not mean 85 long-lived radar associations disappear. Most clears either affect a duplicate lead slot, occur while vision is already the output, or are followed by ordinary strict matching. Only one baseline-preferred radar interval longer than one second is removed by the candidate.

## Strict reacquisition and possible false clears

Nine preferred-state clears are followed by strict matching of the same numeric radarTrackId within five seconds and are conservatively flagged `POSSIBLE_FALSE_CLEAR`:

| route | clear time | ID | arm | strict reacquisition delay |
|---|---:|---:|---|---:|
| 136 | 1448.452 | 46 | B | 0.052 s |
| 139 | 2868.761 | 10 | A | 0.099 s |
| 139 | 2868.809 | 10 | A | 0.051 s |
| 139 | 3315.386 | 61 | A | 2.248 s |
| 139 | 3315.386 | 61 | A | 1.799 s |
| 139 | 4251.234 | 41 | A | 1.650 s |
| 139 | 4251.234 | 41 | A | 1.650 s |
| 139 | 5180.834 | 27 | A | 2.800 s |
| 139 | 5180.883 | 27 | A | 2.801 s |

The duplicate rows at identical or near-identical times are separate leadOne/leadTwo preferred states, as required by the diagnostic. These events prove that strict reacquisition remains operational. They do not by themselves prove the clears harmful, but they are the reason this should not yet become production code.

## Removed baseline radar runs longer than one second

Exactly one such interval exists:

| route | start | duration | ID | clear arm | classification | evidence |
|---|---:|---:|---:|---|---|---|
| 139 | 4170.088 | 1.250 s | 53 | B | LIKELY_STALE | Known 38–43 m model/radar distance disagreement; no strict recovery in the interval. |

Counts: `LIKELY_STALE=1`, `POSSIBLE_GOOD=0`, `UNKNOWN=0`.

## Special checks

- **S33 ID24 stale reattachment:** eliminated.
- **S33 ID44 accidental selection:** none; unchanged strict matching continues to reject it.
- **R136 ID3 preference through temporary misses:** preserved.
- **R136 ID3 later strict recovery:** preserved.
- **R139 ID50 leadOne preference through temporary misses:** preserved.
- **R139 ID50 later strict recovery:** preserved.
- **Normal strict radar reacquisition after candidate clears:** observed and functional.

## Conclusion

The two-arm evidence rule succeeds where the unconditional two-miss rule failed: it clears both known stale associations while preserving both recoverable leadOne associations, and 25 m is the most conservative passing gross-distance threshold. Route-level behavior moves in the intended direction and the only removed >1-second preferred-radar run is the known stale ID53 case. However, 9 clears are followed by strict reacquisition within five seconds, including one Arm B clear that reacquires in 0.052 s. Those cases should be inspected before production implementation. The rule is **promising**, but **not yet ready for a production patch**.
