# Vendored Jetlink (comma side)

| | |
| --- | --- |
| Upstream | https://github.com/zoompilot/jetlink |
| Revision | `4b747aebad3d8d96ab26d76f1668f2b2ecb1b667` (jetlink 0.8.5, `jetlink.openpilot.API == 2`) |
| Pinned by | Zoompilot `develop` `02be6b631d069d8542967916d56bd8b1fc3c744c` (its `jetlink_repo` submodule) |
| License | MIT, see `LICENSE` |

Only what the comma runs is vendored, byte-for-byte from that revision:

* `jetlink/` the Python package (numpy is its only third-party dependency)
* `scripts/comma/jetlink-root.sh` the root helper `jetlink.comma.root` runs under `sudo -n`
  (`root.SCRIPT` resolves it as `<repo>/scripts/comma/`, which is why this directory keeps upstream's layout)
* `LICENSE`

The iOS/Android/macOS apps, the Swift server (`JetlinkKit`), tests and docs are not vendored; the server is
installed separately on the inference host and must be the **same release** as this package (the wire protocol is
version-exact: `jetlink.protocol.VERSION == 3`).

`starpilot/jetlink_adapter` puts this directory on `sys.path` and in the environment of the processes it starts.
Nothing here is imported unless the link is enabled, except by the optional `jetlinkd` owner.

## Updating

Do not bump independently of the Jetlink server and the Zoompilot adapter contract. To update:

1. `rsync -a --delete --exclude=__pycache__ <jetlink>/jetlink/ jetlink/` and copy the root script and LICENSE.
2. Check `jetlink.openpilot.API` against `starpilot.jetlink_adapter.API` and re-run `jetlink.openpilot.conformance`
   (`starpilot/jetlink_adapter/tests/test_adapter.py`).
3. Rebuild the warp pickles (`starpilot/jetlink_adapter/models/`) and re-validate the allowlisted big model.
4. Update the revision above.

## Local modifications

Three small additions to `jetlink/openpilot/joining.py`, kept as `LOCAL_MODIFICATIONS.patch` (apply with
`patch -p1 < LOCAL_MODIFICATIONS.patch` after re-vendoring). They are additive and use hooks Jetlink already reads with a
`getattr` fallback, so they can be offered upstream:

1. `join().build()` calls `op.validate_spec(spec)` when the adapter has one. The fork's adapter refuses any server model
   whose SHA-256 and exact layout it has not validated (`starpilot/jetlink_adapter/profiles.py`); the join then fails like
   any other build failure and the small model keeps driving. Without this hook an unvalidated model would be promoted
   and its output parsed with the wrong generation flags.
2. `JoiningModelState.demote_invalid()`: modeld found the large model's output unusable (non-finite or implausible) and
   hands back through the same path as a lost link, without reaching into private methods.
3. `JoiningModelState.last_demotion` / `last_failure`: why the last handback or failed build happened, for the status line.

No other file is changed. The wire protocol, the server contract and `jetlink.openpilot.API` are untouched.
