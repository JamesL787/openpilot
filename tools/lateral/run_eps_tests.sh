#!/usr/bin/env bash
# Run the Honda EPS controller tests against this checkout (see eps_pytest_stubs.py for why plain pytest is not enough).
#   tools/lateral/run_eps_tests.sh                 # the controller's own tests
#   tools/lateral/run_eps_tests.sh <test paths>    # anything else under the same stubs
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [ "$#" -eq 0 ]; then
  set -- selfdrive/controls/tests/test_honda_eps_firmware_ff.py
fi
PYTHONPATH="$ROOT/tools/lateral" exec "$ROOT/.venv/bin/python" -m pytest -q -p no:cacheprovider -p eps_pytest_stubs --noconftest "$@"
