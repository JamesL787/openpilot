#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${H020_TEST_PYTHON:-python3}"
PYTHONPATH="$ROOT:$ROOT/opendbc_repo${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON_BIN" -m pytest -q --noconftest -p no:cacheprovider tools/lateral/test_h020_port.py
