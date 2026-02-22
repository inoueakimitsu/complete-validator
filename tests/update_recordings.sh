#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/6] record static baseline"
python3 tests/test_harness.py --scenario static --config tests/configs/baseline.json --record

echo "[2/6] record static optimized"
python3 tests/test_harness.py --scenario static --config tests/configs/optimized.json --record

echo "[3/6] verify static baseline recorded"
python3 tests/test_harness.py --scenario static --config tests/configs/baseline.json --recorded

echo "[4/6] verify static optimized recorded"
python3 tests/test_harness.py --scenario static --config tests/configs/optimized.json --recorded

echo "[5/6] regression static"
python3 tests/test_harness.py --scenario regression --regression-scenario static --regression-max-drop 0.05

echo "[6/6] done"
