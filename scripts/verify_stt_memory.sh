#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[stt-memory] 1/2 defaults baseline"
python3 scripts/stt_memory_snapshot.py check

if [[ "${STT_MEMORY_STRICT:-0}" == "1" ]]; then
  echo "[stt-memory] 2/2 strict stt tests"
  pytest -q tests/test_stt_local_filters.py tests/test_voice_stt_manager.py
else
  echo "[stt-memory] 2/2 strict stt tests (skip, set STT_MEMORY_STRICT=1)"
fi

echo "STT_MEMORY_OK"
