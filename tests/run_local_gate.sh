#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/4] static recorded baseline"
python3 tests/test_harness.py --scenario static --config tests/configs/baseline.json --recorded

echo "[2/4] static recorded optimized"
python3 tests/test_harness.py --scenario static --config tests/configs/optimized.json --recorded

echo "[3/4] static regression gate"
python3 tests/test_harness.py --scenario regression --regression-scenario static --regression-max-drop 0.05

echo "[4/4] done"
