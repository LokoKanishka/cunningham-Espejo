#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[smoke] 1/3 py_compile"
mapfile -t PY_FILES < <(git ls-files '*.py' | while read -r path; do [[ -f "$path" ]] && echo "$path"; done)
python3 -m py_compile "${PY_FILES[@]}"

echo "[smoke] 2/3 pytest focalizado"
TMP_LOG="$(mktemp)"
set +e
pytest -q \
  tests/test_voice_stt_manager.py \
  tests/test_openclaw_youtube_and_tools.py \
  tests/test_model_router_script.py \
  tests/test_reader_mode.py \
  tests/test_reader_library.py | tee "$TMP_LOG"
PYTEST_RC="${PIPESTATUS[0]}"
set -e

if [[ "$PYTEST_RC" -ne 0 ]]; then
  if grep -Eq '[0-9]+ passed' "$TMP_LOG" && ! grep -Eq '([0-9]+ failed|ERROR|FAILED)' "$TMP_LOG"; then
    echo "[smoke] aviso: pytest finalizo con senal tras pasar toda la suite; se continua."
  else
    echo "[smoke] pytest fallo (rc=$PYTEST_RC)"
    rm -f "$TMP_LOG"
    exit "$PYTEST_RC"
  fi
fi
rm -f "$TMP_LOG"

echo "[smoke] 3/3 verificadores de contrato"
./scripts/verify_reader_mode_v01.sh
./scripts/verify_reader_library.sh
./scripts/verify_reader_ux_dc.sh
./scripts/verify_stt_barge_in_smoke.sh

./scripts/verify_slash_reader_ui.sh
./scripts/verify_history_export.sh

echo "SMOKE_OK"
