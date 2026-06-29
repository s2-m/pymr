#!/usr/bin/env bash
# Unit tests (dev env) + end-to-end round-trip (viewer env).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "=================  unit tests  ================="
pixi run -e dev test

echo "=============  integration round-trip  ========="
pixi run -e viewer integration

echo
echo "ALL TESTS PASSED"
