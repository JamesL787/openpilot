# Peter Action-Extraction Four-Method Check

Read-only, stateful replay. The four methods below are calculated from the exact same solved MPC trajectory at each logged cycle; none is fed back into a subsequent planner cycle. “Published” means the extraction-only result after the actual lower acceleration limit, so it isolates output extraction rather than proposing a production change.

## Top summary

- CURRENT AMPLIFICATION REPEATS: **YES**.
- DIRECT REMOVES FALSE FLOOR: **4/4**.
- LOCAL_VEL REMOVES FALSE FLOOR: **4/4**.
- BOUNDED_CURRENT REMOVES FALSE FLOOR: **4/4**.
- ANY METHOD CLEARLY UNDERBRAKES URGENT CASE: **NO**. This is a conservative flag: the candidate methods soften a floor while the solved horizon still contains substantial braking inside one second; this experiment cannot establish a safe replacement.
- MOST PROMISING OFFLINE CANDIDATE: **NONE**. Bounded-current removes all four floors while preserving a local trajectory bound, but this small diagnostic cannot prove that it retains necessary anticipation.
- NEXT STEP: **Run a separate safety-focused replay that applies one candidate output method through sequential closed-loop planner state before making any code change.**

## Definitions

- CURRENT: `get_accel_from_plan()`.
- DIRECT: acceleration trajectory interpolated directly at `action_t`.
- LOCAL_VEL: finite difference between the two control-horizon velocity points bracketing `action_t`.
- BOUNDED_CURRENT: CURRENT clamped to the minimum/maximum acceleration samples in `action_t ± 0.20 s`.
- Continuity deltas are selected-cycle method output minus the immediately preceding planner-cycle method output.

## Event 1 — R136/S3 original floor

- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000136--994512551d--3--rlog.zst`
- Normal cycle and first floor remain in `source=cruise` with `shouldStop=False`.
- Floor lead: `dRel=7.167360 m`, `vRel=-2.296875 m/s`, `aLeadK=0.037058 m/s²`, closing speed `2.276560 m/s`, TTC `3.148330 s`.

| selected cycle | t_rel (s) | logged aTarget | replay/published aTarget | CURRENT | DIRECT | LOCAL_VEL | BOUNDED_CURRENT | extraction-only published (current/direct/local/bounded) | continuity delta (current/direct/local/bounded) |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| normal braking | 226.838976 | -3.055781 | -3.049340 | -3.049340 | -2.319327 | -2.118247 | -2.472262 | -3.049340 / -2.319327 / -2.118247 / -2.472262 | 0.031087 / 0.044282 / 0.009489 / 0.070744 |
| first -3.5 floor | 226.900485 | -3.500000 | -3.500000 | -4.388995 | -1.989031 | -2.217956 | -2.449703 | -3.500000 / -1.989031 / -2.217956 / -2.449703 | -1.339655 / 0.330296 / -0.099709 / 0.022559 |

- `action_t=0.550 s`; accel samples defining the floor BOUNDED_CURRENT window are `[0.3515625, 0.478515625, 0.625]` s → `[-2.449703, -2.154982, -1.814919]` m/s².
- MPC minimum acceleration: 0→`action_t` = `-2.581643 m/s²`; first 1.0 s = `-2.620994 m/s²`.
- Current-direct floor amplification: `-2.399964 m/s²`.

## Event 2 — R139/S1

- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--1--rlog.zst`
- Normal cycle and first floor remain in `source=cruise` with `shouldStop=False`.
- Floor lead: `dRel=12.993600 m`, `vRel=-5.546875 m/s`, `aLeadK=0.128616 m/s²`, closing speed `5.498417 m/s`, TTC `2.363153 s`.

| selected cycle | t_rel (s) | logged aTarget | replay/published aTarget | CURRENT | DIRECT | LOCAL_VEL | BOUNDED_CURRENT | extraction-only published (current/direct/local/bounded) | continuity delta (current/direct/local/bounded) |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| normal braking | 89.098563 | -2.933406 | -2.933406 | -2.933406 | -2.495144 | -2.241081 | -2.688376 | -2.933406 / -2.495144 / -2.241081 / -2.688376 | -0.002601 / -0.052500 / -0.001428 / -0.091343 |
| first -3.5 floor | 89.145268 | -3.500000 | -3.500000 | -3.755107 | -2.385506 | -2.344090 | -2.417005 | -3.500000 / -2.385506 / -2.344090 / -2.417005 | -0.821701 / 0.109638 / -0.103009 / 0.271370 |

- `action_t=0.550 s`; accel samples defining the floor BOUNDED_CURRENT window are `[0.3515625, 0.478515625, 0.625]` s → `[-2.302164, -2.355483, -2.417005]` m/s².
- MPC minimum acceleration: 0→`action_t` = `-2.355483 m/s²`; first 1.0 s = `-2.417005 m/s²`.
- Current-direct floor amplification: `-1.369600 m/s²`.

## Event 3 — R139/S10 first

- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--10--rlog.zst`
- Normal cycle and first floor remain in `source=cruise` with `shouldStop=False`.
- Floor lead: `dRel=15.049920 m`, `vRel=-6.046875 m/s`, `aLeadK=0.104600 m/s²`, closing speed `5.909241 m/s`, TTC `2.546845 s`.

| selected cycle | t_rel (s) | logged aTarget | replay/published aTarget | CURRENT | DIRECT | LOCAL_VEL | BOUNDED_CURRENT | extraction-only published (current/direct/local/bounded) | continuity delta (current/direct/local/bounded) |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| normal braking | 644.620905 | -3.265124 | -3.265124 | -3.265124 | -2.260986 | -2.332652 | -2.405202 | -3.265124 / -2.260986 / -2.332652 / -2.405202 | -0.504780 / 0.109202 / -0.200533 / 0.146051 |
| first -3.5 floor | 644.671367 | -3.500000 | -3.500000 | -4.134969 | -2.260723 | -2.376033 | -2.492764 | -3.500000 / -2.260723 / -2.376033 / -2.492764 | -0.869845 / 0.000262 / -0.043381 / -0.087562 |

- `action_t=0.550 s`; accel samples defining the floor BOUNDED_CURRENT window are `[0.3515625, 0.478515625, 0.625]` s → `[-2.492764, -2.344313, -2.173023]` m/s².
- MPC minimum acceleration: 0→`action_t` = `-2.492764 m/s²`; first 1.0 s = `-2.579043 m/s²`.
- Current-direct floor amplification: `-1.874246 m/s²`.

## Event 4 — R139/S10 second

- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--10--rlog.zst`
- Normal cycle and first floor remain in `source=cruise` with `shouldStop=False`.
- Floor lead: `dRel=13.164960 m`, `vRel=-5.421875 m/s`, `aLeadK=0.088060 m/s²`, closing speed `5.245414 m/s`, TTC `2.509804 s`.

| selected cycle | t_rel (s) | logged aTarget | replay/published aTarget | CURRENT | DIRECT | LOCAL_VEL | BOUNDED_CURRENT | extraction-only published (current/direct/local/bounded) | continuity delta (current/direct/local/bounded) |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| normal braking | 645.071224 | -3.053940 | -3.053940 | -3.053940 | -2.485058 | -2.294067 | -2.630319 | -3.053940 / -2.485058 / -2.294067 / -2.630319 | -0.012333 / 0.059241 / -0.043896 / 0.137684 |
| first -3.5 floor | 645.118163 | -3.500000 | -3.500000 | -3.505847 | -2.435689 | -2.342744 | -2.506379 | -3.500000 / -2.435689 / -2.342744 / -2.506379 | -0.451906 / 0.049369 / -0.048678 / 0.123940 |

- `action_t=0.550 s`; accel samples defining the floor BOUNDED_CURRENT window are `[0.3515625, 0.478515625, 0.625]` s → `[-2.248654, -2.368312, -2.506379]` m/s².
- MPC minimum acceleration: 0→`action_t` = `-2.368312 m/s²`; first 1.0 s = `-2.506379 m/s²`.
- Current-direct floor amplification: `-1.070158 m/s²`.

## Safety interpretation

Every selected floor has nontrivial braking still present in the solved MPC horizon. Removing the output floor in this one-cycle extraction test is therefore **not** evidence that DIRECT, LOCAL_VEL, or BOUNDED_CURRENT is safe. It only establishes that the current velocity-based reconstruction is more negative than the local acceleration trajectory in these samples. No planner state, MPC cost, radar input, or production code was altered.
