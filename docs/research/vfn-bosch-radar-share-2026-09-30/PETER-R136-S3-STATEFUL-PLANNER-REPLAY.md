# Peter R136 S3 Stateful LongitudinalPlanner Replay

LOGGED FLOOR REPRODUCED: YES

LOGGED MIN aTarget: -3.500000 m/s^2

REPLAY MIN aTarget: -3.500000 m/s^2

FIRST MATERIAL DIVERGENCE: t=221.934559s, logged=-0.908404, replay=-0.255438, delta=0.652965; logged source=cruise, replay source=cruise.

FLOOR SOURCE: logged=cruise; replay=cruise

RADAR aLeadK AT FLOOR: 0.037058 m/s^2

FIRST PLANNER SOURCE MISMATCH: None in the replay window.

MISSING STATE IF NOT REPRODUCED: none; the planner output was reproduced from the logged service snapshots.

NEXT STEP: Use this matched replay as the baseline and isolate the EXP/MPC state transition around 226.79–226.90 s; do not change radar parsing from this event.

## Scope and provenance

- Route: `00000136`, segment 3, local rlog `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000136--994512551d--3--rlog.zst`.
- Route commit prefix: `994512551d`.
- Target branch/revision requested: `night-star-bosch-radar` at `42c2a191729afac16399e55496669b9dd29ee1df`.
- Segment monotonic span: `99.866545168` to `341.383610979` seconds.
- Floor window: `321.767029805` to `329.767029805` monotonic seconds; route-relative `221.900484637` to `229.900484637`.
- Logged floor start is the first segment-3 `longitudinalPlan.aTarget <= -3.4`: route-relative `226.900484637 s`.
- Replay uses the target-revision planner source from the local Darwin host runtime, whose planner source hash matches the requested revision.
- All planner updates are sequential. `modelV2` is selected at each plan’s recorded `modelMonoTime`; radar/car/control services are selected at or before the plan cycle timestamp.
- The replay clock is driven by logged monotonic timestamps so planner timers advance with recorded cadence rather than wall-clock speed.
- The rlog `initData.params` records `ModelVersion=v15` (therefore `tinygrad_model=True`), `NrdrModelLeadTrajectory=0`, and `NrdrBlotV2=1`; the replay applies those recorded feature states.
- No optional Experimental=False counterfactual was run; the requested Experimental baseline was prioritized.

## Window summary

- Planner cycles: `160`.
- Logged floor cycles: `9`; replay floor cycles: `9`.
- Maximum negative radar `lead0.aLeadK` in window: `-0.089383 m/s^2`.
- Maximum absolute aTarget delta: `0.652965 m/s^2`.
- The CSV is the complete per-cycle comparison and includes planner state needed to identify the transition.

## Primary answer

- Sequential stateful replay **does reproduce** the logged transition to the `-3.5 m/s²` floor.
- The first floor cycle is at route-relative `226.900485 s`; both logged and replayed outputs are `-3.500000`, with `shouldStop=false`.
- The planner source is still `cruise` at floor entry. The source changes to `lead0` only after floor entry; that change does not cause the floor.
- The immediately preceding non-floor output was `-3.055781 m/s²` at `t=226.838976 s`; the next cycle reached the floor.
- At floor entry, radar `lead0.aLeadK=0.037058 m/s²`, `dRel=7.167 m`, and `vLead=-0.207 m/s`; the radar lead state is not an abrupt hard-braking source in this event.
- The first material mismatch is earlier, at the replay-window start; it decays before the floor approach and does not prevent the later stateful floor transition from matching.
- No ACC counterfactual was run.

## First and floor cycles

| t_rel (s) | logged aTarget | replay aTarget | delta | logged source | replay source | logged stop | replay stop | lead dRel | lead vLead | lead aLeadK | vEgo | planner a_desired | filter v | MPC a0 |
|---:|---:|---:|---:|---|---|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|
| 221.934559 | -0.908404 | -0.255438 | 0.652965 | cruise | cruise | True | True | 12.422 | -0.173 | 0.033 | 1.030 | -0.255 | 1.023 | -1.087 |
| 221.989296 | -0.889591 | -0.315868 | 0.573724 | cruise | cruise | True | True | 12.308 | -0.149 | 0.054 | 0.976 | -0.304 | 1.017 | -0.255 |
| 222.043818 | -0.870419 | -0.256542 | 0.613877 | cruise | cruise | True | True | 12.251 | -0.127 | 0.076 | 0.917 | -0.257 | 1.009 | -0.304 |
| 222.088883 | -0.850941 | -0.273191 | 0.577750 | cruise | cruise | True | True | 12.251 | -0.185 | 0.076 | 0.861 | -0.264 | 1.005 | -0.257 |
| 222.141624 | -0.831285 | -0.271240 | 0.560045 | cruise | cruise | True | True | 12.194 | -0.158 | 0.084 | 0.775 | -0.267 | 0.999 | -0.264 |
| 226.900485 | -3.500000 | -3.500000 | 0.000000 | cruise | cruise | False | False | 7.167 | -0.207 | 0.037 | 2.070 | -1.575 | 2.030 | 0.000 |
| 226.942151 | -3.500000 | -3.500000 | 0.000000 | cruise | cruise | False | False | 7.167 | -0.217 | 0.037 | 2.062 | -1.023 | 2.036 | 0.000 |
| 226.990951 | -3.500000 | -3.500000 | 0.000000 | lead0 | lead0 | False | False | 7.053 | -0.224 | 0.023 | 2.052 | -2.004 | 2.002 | 0.000 |
| 227.042616 | -3.500000 | -3.500000 | 0.000000 | lead0 | lead0 | False | False | 6.939 | -0.217 | 0.014 | 2.049 | -2.187 | 1.994 | 0.000 |
| 227.092559 | -3.500000 | -3.500000 | 0.000000 | lead0 | lead0 | False | False | 6.939 | -0.228 | 0.014 | 2.041 | -2.235 | 1.985 | 0.000 |
| 227.145654 | -3.500000 | -3.500000 | 0.000000 | lead0 | lead0 | False | False | 6.939 | -0.228 | 0.014 | 2.030 | -2.252 | 1.973 | 0.000 |
| 227.196924 | -3.500000 | -3.500000 | 0.000000 | lead0 | lead0 | False | False | 6.768 | -0.232 | 0.001 | 2.016 | -2.280 | 1.959 | 0.000 |
| 227.241660 | -3.500000 | -3.500000 | 0.000000 | lead0 | lead0 | False | False | 6.710 | -0.158 | 0.004 | 1.998 | -2.298 | 1.941 | 0.000 |
| 227.291696 | -3.500000 | -3.500000 | 0.000000 | lead0 | lead0 | False | False | 6.710 | -0.158 | 0.004 | 1.984 | -2.299 | 1.927 | 0.000 |
