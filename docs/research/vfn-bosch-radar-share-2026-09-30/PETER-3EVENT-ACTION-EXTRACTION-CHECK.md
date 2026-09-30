# Peter Three-Event Action-Extraction Check

Read-only, stateful replays of exactly three additional Peter hard-floor transitions. Each replay was seeded five seconds before its selected floor and updated cycle-by-cycle with recorded service snapshots. The direct-acceleration counterfactual is diagnostic only: it substitutes the direct interpolation at the floor cycle and is not fed into later planner state.

## Event selection

All three selected transitions have a real radar lead, `shouldStop=false` before and at entry, and no source change at entry. They were selected from a bounded inspection of only route 139 segments 1, 3, and 10.

## Event 1 — route 00000139, segment 1

- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--1--rlog.zst`
- LeadOne/LeadTwo same physical radar track at floor: **YES**.
- Single-cycle direct-acceleration diagnostic: **the -3.5 floor would not remain** (`direct=-2.385506 m/s²`).

| cycle | t_rel (s) | source | shouldStop | leadOne | leadTwo | direct MPC accel at action_t | get_accel_from_plan | extraction_delta | logged aTarget | replay/published aTarget |
|---|---:|---|:---:|---|---|---:|---:|---:|---:|---:|
| before | 89.098563 | cruise | False | id=27, radar=True, status=True, dRel=13.50768, vRel=-5.54688, aLeadK=0.13069 | id=27, radar=True, status=True, dRel=13.50768, vRel=-5.54688, aLeadK=0.13069 | -2.495144 | -2.933406 | -0.438261 | -2.933406 | -2.933406 |
| first floor | 89.145268 | cruise | False | id=27, radar=True, status=True, dRel=12.99360, vRel=-5.54688, aLeadK=0.12862 | id=27, radar=True, status=True, dRel=12.99360, vRel=-5.54688, aLeadK=0.12862 | -2.385506 | -3.755107 | -1.369600 | -3.500000 | -3.500000 |

At the floor cycle, `action_t=0.550 s`; `extraction_delta = get_accel_from_plan - direct = -1.369600 m/s².`

## Event 2 — route 00000139, segment 10

- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--10--rlog.zst`
- LeadOne/LeadTwo same physical radar track at floor: **YES**.
- Single-cycle direct-acceleration diagnostic: **the -3.5 floor would not remain** (`direct=-2.260723 m/s²`).

| cycle | t_rel (s) | source | shouldStop | leadOne | leadTwo | direct MPC accel at action_t | get_accel_from_plan | extraction_delta | logged aTarget | replay/published aTarget |
|---|---:|---|:---:|---|---|---:|---:|---:|---:|---:|
| before | 644.620905 | cruise | False | id=61, radar=True, status=True, dRel=15.67824, vRel=-6.23438, aLeadK=0.10927 | id=61, radar=True, status=True, dRel=15.67824, vRel=-6.23438, aLeadK=0.10927 | -2.260986 | -3.265124 | -1.004138 | -3.265124 | -3.265124 |
| first floor | 644.671367 | cruise | False | id=61, radar=True, status=True, dRel=15.04992, vRel=-6.04688, aLeadK=0.10460 | id=61, radar=True, status=True, dRel=15.04992, vRel=-6.04688, aLeadK=0.10460 | -2.260723 | -4.134969 | -1.874246 | -3.500000 | -3.500000 |

At the floor cycle, `action_t=0.550 s`; `extraction_delta = get_accel_from_plan - direct = -1.874246 m/s².`

## Event 3 — route 00000139, segment 10

- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--10--rlog.zst`
- LeadOne/LeadTwo same physical radar track at floor: **YES**.
- Single-cycle direct-acceleration diagnostic: **the -3.5 floor would not remain** (`direct=-2.435689 m/s²`).

| cycle | t_rel (s) | source | shouldStop | leadOne | leadTwo | direct MPC accel at action_t | get_accel_from_plan | extraction_delta | logged aTarget | replay/published aTarget |
|---|---:|---|:---:|---|---|---:|---:|---:|---:|---:|
| before | 645.071224 | cruise | False | id=61, radar=True, status=True, dRel=13.45056, vRel=-5.50000, aLeadK=0.08747 | id=61, radar=True, status=True, dRel=13.45056, vRel=-5.50000, aLeadK=0.08747 | -2.485058 | -3.053940 | -0.568882 | -3.053940 | -3.053940 |
| first floor | 645.118163 | cruise | False | id=61, radar=True, status=True, dRel=13.16496, vRel=-5.42188, aLeadK=0.08806 | id=61, radar=True, status=True, dRel=13.16496, vRel=-5.42188, aLeadK=0.08806 | -2.435689 | -3.505847 | -1.070158 | -3.500000 | -3.500000 |

At the floor cycle, `action_t=0.550 s`; `extraction_delta = get_accel_from_plan - direct = -1.070158 m/s².`

## Required answers

- EVENT 1 extraction amplification: **-1.369600 m/s²**.
- EVENT 2 extraction amplification: **-1.874246 m/s²**.
- EVENT 3 extraction amplification: **-1.070158 m/s²**.
- FLOOR WOULD REMAIN WITH DIRECT ACCEL: **Event 1: NO; Event 2: NO; Event 3: NO.**
- SAME MECHANISM REPEATS: **YES**. In each selected case, the direct MPC acceleration is above the hard floor while the output reconstruction is substantially more negative and is then clipped to the published floor.

No code, tuning, or planner state was changed by this validation.
