# Repo notes on this bundle (added 2026-09-30)

A research share from JamesL787 (vfn), kept as he sent it. It was written against an older fork
branch, and its analysis rests on route logs that are not in this repo.

**Stale, confirmed by Peter. The repo wins:**
- The R141 audit's range scale of 0.05712 m/count is outdated. The parser's `raw/16 - 3.0`
  (`opendbc_repo/opendbc/car/honda/radar_interface.py`) is the ground truth.
- Neither patch applies to `ns-bosch-radar-testing` as written.
  - Patch 1 (5 s TTC exit in `build_model_lead_trajectory`) depends on a prior fork patch that
    is not in the bundle.
  - Patch 2 (strict FCW authority): **do not apply.** `require_lead_fcw` would silence planner FCW
    for vision-only leads and for modelProb <= 0.9 on Bosch-A (static reading).

**Worth following up (replay per the bundle, not re-checked here):**
- At low-speed floors, `get_accel_from_plan` asks for 1.1-2.4 m/s^2 more braking than the MPC's
  direct command (R136/R139). The bundle's own verdict is "SAFE FOR ROAD PATCH: NO".
- The relative-observer experiment makes the vRel and aLeadK tails worse near the U11 rail.
- In some intervals, the stale-preference lead rule removes a lead rather than bounding it
  (about 9-10, unverified). This is in tension with D-041/D-042/D-048.

The bundle has nothing on the NC channel or the rail, so D-071 is unaffected.
