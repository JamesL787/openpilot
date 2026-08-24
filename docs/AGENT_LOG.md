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
- Exposed the added NRDR longitudinal controls through Galaxy's shared device
  settings layout.
- Kept the existing lateral panel because it already covers the upstream
  vehicle learning, controller tuning, override, filter, and tune-report
  areas. The upstream handcrafted-lateral switch was not added because its
  controller runtime is not present on this branch.

## 2026-08-24 — Dynamic longitudinal settings visibility

- Hid the generic StarPilot stop controls whenever an active Honda openpilot
  long controller uses the Honda-specific override parameters instead.
- Scoped NRDR Long controls and sections to the detected Honda controller path,
  while retaining the Nidec-only controls for Nidec cars.
- Added conditional hub-tile support and hid NRDR's Honda-only lateral and
  longitudinal entry points for non-Honda fingerprints.
- Added one shared CarParams/controller capability catalogue for Galaxy,
  Favorites, and the native vehicle settings panel. It gates Honda Bosch/Nidec
  paths, modified EPS tuning, Tesla Model 3 vs. Pre-AP controls, GM pedal and
  Volt settings, Subaru/Toyota/Jeep settings, Rivian hardware, and Hyundai
  CAN-FD controls without deleting stored preferences.
- Changed the native advanced lateral view to omit controls that do not apply
  to the detected angle/torque controller rather than showing disabled rows.

## 2026-08-24 — EPS tooling recovery from arc-dev

- Recovered the deleted `arc-dev` tip from its reflog and compared its
  `eps_tools/` tree with `ns-bosch-radar`.
- Ported the guided flasher, diagnostic and UDS hardening, firmware guidance,
  and the CR-V 5G rate-authority tuning image to `ns-bosch-radar`.
- Corrected the tuning README to name the recovered image file exactly.

## 2026-08-24 — StarPilot distance-button hold feedback

- Deferred long-press actions until release, allowing very-long button actions
  without temporarily toggling and undoing the long-press action.
- Added existing openpilot audio cues at the long and very-long thresholds;
  driving and safety alerts retain priority over these feedback sounds.
