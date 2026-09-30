# Peter Bounded-Action Closed-Loop Validation

Read-only sequential replays. BASELINE uses the production extraction. CANDIDATE computes BOUNDED_CURRENT after each real planner solve and writes that value to `planner.output_a_target`; the next cycle therefore uses it as the prior published target. The raw inputs, MPC costs, and solved trajectory generation are identical.

## Top summary

- STAB EVENTS TESTED: **4**.
- FLOOR REMOVED: **1/4**.
- WORST BASELINE ONE-CYCLE STEP: **3.500000 m/s²**.
- WORST BOUNDED ONE-CYCLE STEP: **3.498787 m/s²**.
- URGENT EVENT PRESERVED: **NO**.
- CANDIDATE CREATES LATER CATCH-UP BRAKE: **YES**.
- BOUNDED_CURRENT STILL PROMISING: **NO**.
- SAFE ENOUGH FOR A SMALL ROAD-TEST PATCH: **NO**. This is a short open-loop-input replay; it does not close the vehicle/control-plant loop or establish emergency-braking safety.
- NEXT STEP: **Validate the bounded extraction in a closed vehicle-response simulation or a guarded bench replay before considering a narrowly scoped patch.**

## Four stab windows

| event | baseline min aTarget | candidate min aTarget | baseline -3.5 cycles | candidate -3.5 cycles | baseline max step | candidate max step | candidate min MPC accel first 1s | min observed dRel | min MPC lead-trajectory separation | candidate later stronger brake? |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| R136/S3 | -3.500000 | -2.984829 | 9 | 0 | 1.083108 | 0.842930 | -3.480795 | 4.197120 | 3.935007 | YES |
| R139/S1 | -3.500000 | -3.498855 | 11 | 1 | 2.701477 | 3.498787 | -3.499571 | 10.937280 | 5.931492 | YES |
| R139/S10 first | -3.500000 | -3.499652 | 71 | 4 | 1.131320 | 2.762009 | -3.499994 | 5.853600 | 5.046575 | YES |
| R139/S10 second | -3.500000 | -3.499652 | 77 | 4 | 3.500000 | 2.300604 | -3.500001 | 5.453760 | 4.769842 | YES |

### R136/S3

- Window: `224.900485` to `229.900485` route-relative seconds; local rlog `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000136--994512551d--3--rlog.zst`.
- At BASELINE minimum: dRel `7.167360 m`, closing `2.276560 m/s`, TTC `3.148330 s`, first-1s MPC minimum `-2.620161 m/s²`.
- At CANDIDATE minimum: dRel `6.710400 m`, closing `2.156081 m/s`, TTC `3.112314 s`, first-1s MPC minimum `-3.479211 m/s²`.

### R139/S1

- Window: `87.145268` to `92.145268` route-relative seconds; local rlog `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--1--rlog.zst`.
- At BASELINE minimum: dRel `12.993600 m`, closing `5.498417 m/s`, TTC `2.363153 s`, first-1s MPC minimum `-2.416930 m/s²`.
- At CANDIDATE minimum: dRel `10.937280 m`, closing `5.709957 m/s`, TTC `1.915475 s`, first-1s MPC minimum `-3.499179 m/s²`.

### R139/S10 first

- Window: `642.671367` to `647.671367` route-relative seconds; local rlog `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--10--rlog.zst`.
- At BASELINE minimum: dRel `21.675341 m`, closing `7.297428 m/s`, TTC `2.970271 s`, first-1s MPC minimum `-3.106753 m/s²`.
- At CANDIDATE minimum: dRel `9.337920 m`, closing `3.450585 m/s`, TTC `2.706185 s`, first-1s MPC minimum `-3.499661 m/s²`.

### R139/S10 second

- Window: `643.118163` to `648.118163` route-relative seconds; local rlog `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000139--3f0032ba2d--10--rlog.zst`.
- At BASELINE minimum: dRel `21.675341 m`, closing `7.297428 m/s`, TTC `2.970271 s`, first-1s MPC minimum `-3.107261 m/s²`.
- At CANDIDATE minimum: dRel `9.337920 m`, closing `3.450585 m/s`, TTC `2.706185 s`, first-1s MPC minimum `-3.499662 m/s²`.

## Urgent control event

- Selected: **R136/S31 geometry-required stop** — one pre-existing constant-deceleration screening event that required the floor and also has `shouldStop=true` near the selected floor.
- Local rlog: `/Users/REDACTED_USER/Downloads/11c8fa231c0499ed_00000136--994512551d--31--rlog.zst`; window `1895.850413` to `1900.850413` route-relative seconds.
- BASELINE: min `-3.500000 m/s²`, floor cycles `7`, max step `3.500000 m/s²`, min observed dRel `0.752145 m`, min predicted selected-lead separation `-10.595967 m`.
- BOUNDED_CURRENT: min `-2.924460 m/s²`, floor cycles `0`, max step `2.638190 m/s²`, min first-1s MPC accel `-3.499998 m/s²`, min observed dRel `0.752145 m`, min predicted selected-lead separation `-10.595967 m`.
- CANDIDATE minimum geometry: dRel `3.366651 m`, closing `0.962959 m/s`, TTC `3.496152 s`, shouldStop `True`.

A predicted selected-lead separation is shown only when the selected MPC lead horizon is physically usable; otherwise observed `dRel` is the usable gap measure.

## Interpretation boundary

The candidate has been fed back into the planner’s own prior-output state, but ego motion and external services remain recorded rather than responding to the different command. The result is useful for detecting an immediate planner-state catch-up effect; it cannot certify road safety or replace an actuator/vehicle closed-loop evaluation. No production files, tuning values, or source code were changed.
