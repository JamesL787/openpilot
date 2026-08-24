# Repository Agent Rules

## Working tree and branches

- Keep feature work on `ns-bosch-radar`. Use `ns-bosch-radar-tel` only for EPS
  telemetry and tuning work that is intentionally layered on top of it.
- Push owned branches to `origin` (`RiskyBiscuit-arc/openpilot`) over HTTPS when
  SSH is unavailable. Do not alter branches on `starpilot`, `upstream`, or
  `sunnypilot` unless explicitly asked.
- Before switching branches, inspect tracked changes and preserve unrelated
  workspace files. This checkout contains untracked duplicate-suffixed files;
  do not add, rename, or delete them unless the task specifically targets them.

## Repository layout

- `selfdrive/` contains vehicle, controls, and UI code. Settings UI lives in
  `selfdrive/ui/layouts/settings/`; StarPilot-specific settings are under
  `selfdrive/ui/layouts/settings/starpilot/`.
- `starpilot/` contains StarPilot runtime, feature, and asset code.
- `eps_tools/` contains EPS capture, decoding, flashing, and telemetry tools.
- `system/`, `common/`, `cereal/`, `panda/`, and `tools/` are first-party
  platform, shared-code, messaging, hardware, and developer-tool roots.
- `opendbc_repo/`, `msgq_repo/`, `rednose_repo/`, and `tinygrad_repo/` are
  vendored components. Follow any rules inside those directories, especially
  `tinygrad_repo/AGENTS.md`.

## Verification and documentation

- Prefer focused checks for changed code. For Python UI edits, run
  `python3 -m py_compile` on the modified modules and `git diff --check`.
- Record structural or workflow changes in `docs/AGENT_LOG.md`.
- Keep pull requests focused. State validation that was run and any environment
  limitation that prevented a test from running.
