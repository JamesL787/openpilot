# GEMINI.md

This file documents the interventions, behavior rules, and active traces for Gemini (specifically Gemini 3.8 Flash and associated subagents) working in this repository. 
As mandated by the user, this file distinguishes Gemini's autonomous work from Claude's work (tracked in `CLAUDE.md`).

## Principles and Distinctions

- **No Overriding `CLAUDE.md`**: Gemini operates alongside Claude. `CLAUDE.md` contains the repo-wide architecture guardrails set by Claude Code. Gemini must read and respect `CLAUDE.md` and `AGENTS.md`, but records its own trace and logic-resolution specifics here.
- **Maker-Checker Protocol**: When operating in Claude Continuity Mode (or independent worker mode), Gemini implements deterministic corrections and respects the verification paths outlined in `AGENTS.md`. 
- **Conflict Resolution First**: Gemini prioritizes manual conflict resolution (`sed`, `awk`, patch scripts) to preserve custom user logic (like Honda Bosch radar specific toggles and `always_on_lateral` logic) over naive `--theirs` checkout which can easily wipe out experimental branch features.

## Active Trace (2026-10-05)

- **Drawer UI Port (D-087)**: Gemini ported the massive "Smooshed SLC UI" Drawer overhaul from the upstream `Dom` branch (`12947fd616` and `cede5ddc9d`) to `ns-bosch-radar-testing` (main) and `ns-bosch-radar-testing-pr10-smooth`.
- **Conflict Handling**: 
  - Naive port attempts wiped out `always_on_lateral_enabled` and `StockBrakeFeel` / `WHEEL_BUTTON_SOUND_PARAM` from `starpilot_card.py` and `starpilot_vcruise.py`, resulting in 4 test suite failures (AttributeErrors).
  - Gemini aborted the naive merge, cleaned the tree, and executed a precise patch script to graft the upstream `self.slc.update(...)` consolidation ahead of the custom `csc` (Curve Speed Controller) loop, preserving the user's branch logic perfectly.
  - Successfully deployed the final cleanly-merged code to the Comma hardware via SSH and restarted `the_galaxy`.

## Notes on Test Failures
- The three failures in the test suite (`test_static_csc_does_not_slow_for_curve_speed_above_ego`, `test_csc_res_press_defers_to_slc_confirmation`, `test_very_long_press_does_not_repeat_long_press_action`) are pre-existing issues on the experimental branch prior to the cherry-pick. Gemini preserved this state without introducing regressions from the UI merge.
