# Bosch Experimental fixed-input MPC replay

```yaml
REMOTE HEAD: 42c2a191729afac16399e55496669b9dd29ee1df
MPC FIXED-INPUT REPLAY: PARTIAL (actual Darwin host-generated acados solver passed; local corpus has 53 reproducible clusters, not the requested 24-event inventory)
EVENTS REPLAYED: 53 / 24 requested; raw local threshold clusters=53
SAME INPUT ACC VS BLENDED DIFFERENCE: n=53, median=0.032, mean=0.166, p05=-1.021, p95=2.391, min=-1.250, max=2.511, more-negative(<-0.05)=18, more-positive(>0.05)=22 m/s^2
FLOOR EVENTS WITH TAME aLeadK: 15 / 34 using |aLeadK| < 0.5; floor-required-by-constant-decel=7
PRIMARY BLENDED AGGRESSION SOURCE: cost-vector branch effect median=-0.131; ACC-geometry blended-cost isolation is the largest consistent signed effect; update/reference branch offset median=0.183
CURRENT_X_EGO_COST EFFECT: median=-0.001 m/s² vs blended
A_CHANGE_COST EFFECT: median=-0.054 m/s² vs blended
JERK COST EFFECT: median=0.035 m/s² vs blended
A_EGO_COST EFFECT: median=-0.004 m/s² vs blended
ACCEL LIMIT EFFECT: median=0.000 m/s² vs blended
RADAR CONTRIBUTION: aligned A4 coverage 37/53; blended current-minus-A4 n=37, median=0.000, mean=0.001, p05=-0.001, p95=0.001, min=-0.002, max=0.055, more-negative(<-0.05)=0, more-positive(>0.05)=1; ACC current-minus-A4 n=37, median=0.000, mean=-0.001, p05=-0.003, p95=0.005, min=-0.047, max=0.010, more-negative(<-0.05)=0, more-positive(>0.05)=0
PLANNER CONTRIBUTION: same-input ACC-vs-blended n=53, median=0.032, mean=0.166, p05=-1.021, p95=2.391, min=-1.250, max=2.511, more-negative(<-0.05)=18, more-positive(>0.05)=22
EXP DANGER ZONE: REAL PLANNER RESPONSE EFFECT in controlled synthetic surface; event sweep 583 samples is input-dependent (blended-minus-ACC n=583, median=0.029, mean=0.182, p05=-1.070, p95=2.395, min=-1.250, max=2.549, more-negative(<-0.05)=204, more-positive(>0.05)=242); synthetic surface n=495, median=-0.160, mean=-0.144, p05=-0.220, p95=-0.023, min=-0.258, max=0.087, more-negative(<-0.05)=446, more-positive(>0.05)=3
RADAR PARSER CHANGE NEEDED FIRST: no parser change is justified by this mode-isolation replay; A4 substitution is near-zero in the aligned event set
SAFE TO BEGIN EXP TUNING: YES for a narrowly scoped, replay-gated experiment; do not tune from logged output alone
NEXT SMALLEST CODE EXPERIMENT: replay the cost-vector ablation that replaces blended [0.1, 0.2] ego V/A penalties and 40.0 acceleration-change cost with ACC terms, without changing planner limits
```

## Method

The replay imports the target-revision Python MPC source through the Mac Darwin host runtime. The target ARM ELF solver cannot load on macOS; the host-generated Mach-O solver is used, and the target `long_mpc.py` source was verified byte-identical to that host runtime before running. Each event copies the nearest `carState`, `radarState`, `modelV2`, `starpilotPlan`, `selfdriveState`, and previous `longitudinalPlan` state. The same copied lead/model inputs are run once with `mode='acc'` and once with `mode='blended'`.

The event representative is the most negative logged `longitudinalPlan.aTarget` in a contiguous one-second-separated cluster with `aTarget < -2`. The two latest local routes used here are route `00000136` (rlog commit prefix `994512551d`, 34 segments) and route `00000139` (rlog commit prefix `3f0032ba2d`, 44 segments). The request states that an existing inventory contains 24 events, but no such inventory was present in the workspace or Downloads. These routes produce 53 clusters with this transparent rule; 42 remain when any cluster containing `shouldStop` is excluded. The CSV therefore retains all reproducible local clusters rather than silently discarding 29 events.

## Target-source facts

- ACC costs are `[current_x_ego_cost, 0, 0, 0, acceleration_jerk, speed_jerk]` when the previous-acceleration constraint is active.
- Blended costs are `[0, 0.1, 0.2, 5.0, 40.0, 1.0]` when that constraint is active.
- ACC uses the StarPilot/CP-derived acceleration limits followed by the turn envelope; blended starts from global `[-3.5, +2.0]`.
- Both modes use the same lead obstacle construction and the same copied radar/model state in the primary pair. In this offline harness `trackingLead` is augmented only by the target 42c2 raw-close gate; dynamic `tFollow`, uncertainty filters, and optional model-lead trajectory parameter state are recorded as limitations when not present directly in the rlog.

## Fixed-input event results

See `bosch_exp_acc_vs_blended_events.csv`. The fields include logged lead state, both counterfactual trajectories, obstacle positions, sources, acceleration limits, and first-solution divergence metadata.

## Component ablations

See `bosch_exp_mpc_ablation.csv`. Median delta versus the baseline blended solve (negative means the ablation solved more negatively): acc_costs_global_limits=-0.008, acc_geometry_blended_costs=-0.183, blend_acc_change=-0.054, blend_acc_jerk=0.035, blend_acc_obstacle=-0.001, blend_current_x=-0.001, blend_no_aego=-0.004, blend_no_vego=-0.002, blended_accel_limits=0.000. `acc_geometry_blended_costs` isolates the blended cost vector while retaining the ACC update/reference branch; its median delta versus the ACC baseline is -0.131 m/s². The complementary blended update/reference branch effect is 0.183 m/s².

## Response surface and danger-zone evidence

See `bosch_exp_response_surface.csv`. `response_surface` rows use the target solver with synthetic controlled lead inputs over the requested ego speed, relative velocity, lead acceleration, and distance grid. `event_sweep` rows move each selected event lead by -5 to +5 m while holding the logged kinematics fixed. This is structural diagnosis, not a tuning recommendation.

## Numeric findings

- Local route corpus: 53 threshold clusters from routes 00000136 and 00000139; the requested 24-event inventory was not found locally. Of these, 34 reached the logged acceleration floor and 15 had |aLeadK| < 0.5.
- Same-input mode effect: n=53, median=0.032, mean=0.166, p05=-1.021, p95=2.391, min=-1.250, max=2.511, more-negative(<-0.05)=18, more-positive(>0.05)=22 m/s². The result is mixed in event snapshots, but the controlled synthetic surface is consistently more negative in blended mode: n=495, median=-0.160, mean=-0.144, p05=-0.220, p95=-0.023, min=-0.258, max=0.087, more-negative(<-0.05)=446, more-positive(>0.05)=3.
- Cost-only isolation: n=53, median=-0.131, mean=-0.076, p05=-1.299, p95=1.931, min=-1.466, max=2.402, more-negative(<-0.05)=30, more-positive(>0.05)=13 m/s² (ACC update geometry with blended costs versus ACC baseline). Update/reference branch addition: n=53, median=0.183, mean=0.243, p05=0.016, p95=0.636, min=-0.020, max=0.966, more-negative(<-0.05)=0, more-positive(>0.05)=45 m/s² (blended branch versus that cost-only isolation).
- First material solution divergence (absolute horizon acceleration delta > 0.05 m/s²): horizon[-1]=1, horizon[1]=44, horizon[2]=5, horizon[4]=1, horizon[7]=1, horizon[8]=1. This identifies the first divergent solved horizon, not a unique cost term; source/obstacle selection also changes in some events.
- A4 radar substitution: 37/53 events matched to freshly regenerated raw-CAN A4; blended effect n=37, median=0.000, mean=0.001, p05=-0.001, p95=0.001, min=-0.002, max=0.055, more-negative(<-0.05)=0, more-positive(>0.05)=1 m/s² and ACC effect n=37, median=0.000, mean=-0.001, p05=-0.003, p95=0.005, min=-0.047, max=0.010, more-negative(<-0.05)=0, more-positive(>0.05)=0 m/s². This is not evidence that A4 is a better measurement; it only bounds its planner sensitivity here.
- Logged-floor source split: ACC counterfactual source {'cruise': 16, 'lead0': 16, 'lead1': 2}; blended counterfactual source {'lead0': 12, 'e2e': 3, 'lead1': 19}. This is why a floor event cannot be labeled radar-driven from lead presence alone.
- Event-distance sweep threshold counts:
- -1.0 m/s²: ACC 378/583, blended 429/583
- -2.0 m/s²: ACC 333/583, blended 253/583
- -3.0 m/s²: ACC 180/583, blended 119/583
- -3.5 m/s²: ACC 0/583, blended 0/583

## Final decision questions

1. IDENTICAL INPUT ACC VS BLENDED: The real event snapshots are mixed: blended is more negative by >0.05 m/s² in 18/53 and less negative by >0.05 in 22/53, with median delta +0.032 m/s². The controlled response surface does show a repeatable blended-more-negative region: 446/495 rows, median -0.160 m/s².
2. FREQUENCY: 18/53 local event representatives show a materially stronger blended result at the chosen snapshot; 446/495 synthetic surface points are materially more negative. These are different populations and are not interchangeable.
3. MAGNITUDE: Event snapshot p05/min are -1.021/-1.250 m/s² for blended-minus-ACC; the synthetic surface median/min are -0.160/-0.258 m/s².
4. DOMINANT TERM: No single scalar term is proven by the one-at-a-time ablations. The largest consistent category is the blended cost-vector interaction (cost-only isolation median -0.131 m/s² versus ACC baseline); acceleration limits are effectively neutral (median 0.000), current-x/obstacle weighting is neutral (median -0.001), a-change is -0.054, and jerk is +0.035 relative to baseline blended. The blended update/reference branch offsets that cost-only effect toward less-negative output by +0.183 median.
5. FLOOR GEOMETRY: The simple constant-deceleration-to-a-6m-stop-gap check marks 7/34 logged floor events as requiring the global -3.5 m/s² floor; 10/34 are tame-|aLeadK| events that this simple geometry does not require. This is a screening calculation, not a full collision-risk proof, because it does not model lead acceleration, actuator delay, or the planner's complete stopping state.
6. S22 RADAR MOTION: The radar-motion inconsistency remains a valid secondary measurement-quality finding, but the aligned A4 counterfactual changes blended output by median 0.000 m/s² across 37/53 matched events and is near-zero for the S22-like case. The planner/mode contribution is therefore separable and currently larger than the A4 substitution effect in this replay.
7. PARSER STATUS: Keep the current 42c2 parser as the baseline for this planner investigation. It is not declared perfect; native-vRel/quality work remains a secondary issue, but this replay does not justify another parser change before the Experimental planner experiment.
8. NEXT SMALLEST PLANNER EXPERIMENT: Offline-only, replace the blended cost vector with the ACC cost vector while retaining the blended update branch and global limits, then replay the same event/surface corpus. Do not implement or road-test it from this report alone.

## Replay limitations

This is an actual target MPC solve, but not a byte-for-byte full planner replay. The rlogs do not expose every internal planner state (notably the complete desired-speed/acceleration filters, all prior MPC internal states, and optional model-lead trajectory parameter state), so the script uses the nearest logged prior plan acceleration vector and the target raw-close lead gate. The report therefore establishes controlled structural effects, not a final safety or tuning answer.

## Interpretation guardrails

The replay does not alter radar parsing, DBC definitions, RadarD matching, U11, A4, planner constants, or production files. A negative blended-minus-ACC value proves only that the target MPC solved more negatively for the copied input; it does not by itself establish that the behavior was unsafe or that a specific cost should be changed. Floor events with large negative `aLeadK`, explicit stop state, or missing tracking inputs require geometry review before labeling them brake stabs.

## Artifact provenance

- Script: `/Users/REDACTED_USER/Documents/ChatGPT/bosch_radar/tools/bosch_exp_fixed_input_mpc_replay.py`
- Source revision requested: `42c2a191729afac16399e55496669b9dd29ee1df`
- Production checkout was not modified, committed, or pushed.
