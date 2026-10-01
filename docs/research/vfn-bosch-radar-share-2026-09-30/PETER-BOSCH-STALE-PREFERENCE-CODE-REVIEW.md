# Peter Bosch Stale-Preference Code Review

ASSOCIATION SCORE SEMANTICS IDENTICAL: **YES**

CIVIC-BOSCH SCOPE CORRECT: **YES**

COUNTER STATE CORRECT: **YES**

ARM A EXACTLY TWO CYCLES: **YES**

ARM B EXACTLY THREE CYCLES: **YES**

CLEAR/REACQUIRE ORDERING CORRECT: **YES**

PRODUCTION DIFF SIZE: **+79 / -9**

TEST DIFF SIZE: **+157 / -2**

SIMPLIFICATION RECOMMENDED: **NO**

MISSING IMPORTANT TEST: **Add one full `RadarD.update()` regression that clears a stale preferred ID, exercises the Civic-Bosch low-speed path, and then proves a later strict acquisition resets ownership normally.**

SAFE TO COMMIT AS-IS: **YES**

No code was changed, committed, or pushed during this review.

## 1. Association-score refactor

The old local `prob(c)` and new `vision_track_probability(track, lead, v_ego)` are mathematically identical:

| term | baseline | worktree | result |
|---|---|---|---|
| longitudinal center | `lead.x[0] - RADAR_TO_CAMERA` | identical | unchanged |
| distance probability | `laplacian_pdf(dRel, offset, xStd[0])` | identical | unchanged |
| lateral probability | `laplacian_pdf(yRel, -lead.y[0], yStd[0])` | identical | unchanged |
| velocity probability | `laplacian_pdf(vRel + v_ego, lead.v[0], vStd[0])` | identical | unchanged |
| standard-deviation floor | existing `laplacian_pdf()` floor `max(b, 1e-4)` | same helper | unchanged |
| combined score | `prob_d * prob_y * prob_v` | identical order | unchanged |
| winning candidate | `max(tracks.values(), key=prob)` | same iterable/order with equivalent key | unchanged, including ties |

No sign, offset, scale, floor, multiplication order, or candidate filtering changed.

## 2. Civic-Bosch scope

The stale evaluator is called for both model leads after probability filtering, but immediately returns unless `self.civic_bosch_radar` is true. Arm A/B counters are never read by normal matching or generic radar code.

The post-selection reset helper can update otherwise-unused bookkeeping arrays for non-Civic configurations, but it cannot alter `prev_lead_track_ids`, matching, or output. Functional behavior is therefore fully Civic-Bosch scoped.

## 3. Counter ownership and reset audit

- Lead slots use separate index-0/index-1 owner IDs and counters.
- An owner-ID mismatch resets both counters before evaluating the new ID, preventing A-to-B evidence carryover.
- Missing preference, missing preferred track, invalid/not-ready model lead, or filtered probability at/below the existing threshold resets both counters.
- A relaxed preferred pass resets Arm A.
- A strict preferred pass resets Arm B, including the validated >25 m ID46 case.
- Clearing either arm sets the preferred ID to `-1` and resets owner plus both counters.
- A normally acquired different radar ID resets ownership and both counters before becoming preferred.
- Output invalidation or preferred-track disappearance clears preference and both counters.

Arm A increments from 0 to 1 on the first qualifying cycle and clears at `>=2` on the second. Arm B similarly clears on the third qualifying cycle at `>=3`. There is no off-by-one error.

## 4. Ordering audit

The order is correct:

1. Update the existing model-lead probability filter.
2. Evaluate/possibly clear stale preference.
3. Run unchanged normal strict matching.
4. Run unchanged preferred fallback using the possibly-cleared ID.
5. Run unchanged Civic-Bosch low-speed handling.
6. Update `prev_lead_track_ids` from the final published result and reset evidence on a normal new acquisition.

A stale ID that fails strict matching cannot be restored from preferred state in the same cycle because `get_lead()` receives `-1`. Arm A never passes its challenger into selection. A challenger that fails strict matching also cannot displace the valid vision lead through the Civic-Bosch low-speed path because the existing establishment rule requires model agreement. The old ID may return only through a legitimate unchanged acquisition path, which is intended.

## 5. Diff-size sanity

Production: `+79/-9`; tests: `+157/-2`.

The nine production deletions are the old local score closure plus its selection line; the replacement helper preserves that code for reuse by Arm A. The remaining production code consists of three constants, three two-element state arrays, one reset helper, one evidence evaluator, one call site, and final-output ownership resets.

The owner-ID array could be removed only by relying on every present and future assignment to `prev_lead_track_ids` to reset both counters correctly. That would save a few lines but weaken the explicit no-state-leak invariant. No substantial safe reduction exists without making the state machine less auditable, so the current size is justified.

## 6. Test coverage map

| required invariant | test |
|---|---|
| Arm A clears on exactly two challenger wins | `test_bosch_arm_a_clears_after_two_better_challenger_cycles` |
| Arm A does not directly select non-strict challenger | `test_bosch_arm_a_clear_does_not_select_non_strict_challenger` |
| relaxed recovery resets Arm A | `test_bosch_arm_a_resets_when_preferred_relaxed_match_recovers` |
| Arm B clears on exactly three non-strict gross mismatches | `test_bosch_arm_b_clears_after_three_non_strict_gross_distance_cycles` |
| strict pass protects >25 m ID46-type case | `test_bosch_arm_b_strict_match_resets_gross_distance_streak` |
| evidence cannot leak from ID A to ID B | `test_bosch_stale_evidence_does_not_leak_to_new_preferred_id` |
| non-Civic behavior unchanged | `test_non_bosch_radar_does_not_apply_preferred_stale_logic` |
| leadOne/leadTwo state independent | `test_bosch_duplicate_lead_preferences_keep_independent_stale_state` |

There are no dedicated unit tests for model invalidation, preferred-track disappearance, or the complete clear-to-strict-reacquisition sequence through `RadarD.update()`. The first two reset branches are direct and low-risk; the update-level ordering/reacquisition test is the only meaningful missing regression. Route replay already validated that behavior, so this gap does not reveal a correctness defect in the current patch.

## Conclusion

No correctness issue was found. Existing association scoring and matching thresholds remain unchanged, Arm A/B are functionally Civic-Bosch-only, state ownership is isolated per lead and per preferred ID, and same-cycle ordering cannot restore a stale non-strict preference or implicitly promote the challenger. The patch is safe to commit as-is, with the noted integrated regression test recommended as follow-up coverage rather than a blocker.
