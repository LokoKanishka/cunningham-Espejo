#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[smoke] 1/3 py_compile"
python3 -m py_compile $(git ls-files '*.py')

echo "[smoke] 2/3 unittest"
python3 -m unittest \
  tests.test_voice_stt_manager \
  tests.test_openclaw_youtube_and_tools \
  tests.test_model_router_script \
  tests.test_reader_mode \
  tests.test_reader_library

echo "[smoke] 3/3 pytest focalizado"
pytest -q \
  tests/test_openclaw_youtube_and_tools.py \
  tests/test_model_router_script.py \
  tests/test_reader_mode.py \
  tests/test_reader_library.py

./scripts/verify_reader_mode_v01.sh
./scripts/verify_reader_library.sh
./scripts/verify_reader_ux_dc.sh
./scripts/verify_stt_barge_in_smoke.sh

./scripts/verify_slash_reader_ui.sh
./scripts/verify_history_export.sh

echo "SMOKE_OK"
