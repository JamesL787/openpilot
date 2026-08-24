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
