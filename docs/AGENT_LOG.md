# Agent Maintenance Log

## 2026-08-23 — Repository structure baseline

- Added root `AGENTS.md` to describe the active branch policy, first-party
  source roots, vendored components, and focused validation expectations.
- Established `ns-bosch-radar` as the primary feature branch and
  `ns-bosch-radar-tel` as its EPS telemetry/tuning companion branch.
- Documented the StarPilot settings location and the NRDR/StarPilot UI split so
  future changes land in the correct settings layout.
- Noted that duplicate-suffixed untracked files must be treated as user
  workspace data unless explicitly in scope.

## 2026-08-23 — NRDR settings comparison

- Compared the NRDR longitudinal and lateral settings in `ns-bosch-radar`
  against `nrdr-development-new`.
- Added the newer NRDR longitudinal option surface to the StarPilot NRDR
  panel, retaining the existing StarPilot controls and parameter compatibility.
- Omitted NRDR's set-speed overshoot allowance because StarPilot's existing
  Set Speed Offset already provides the overlapping cruise-target behavior.
- Kept the existing lateral panel because it already covers the upstream
  vehicle learning, controller tuning, override, filter, and tune-report
  areas. The upstream handcrafted-lateral switch was not added because its
  controller runtime is not present on this branch.
