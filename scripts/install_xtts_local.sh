#!/usr/bin/env bash
set -euo pipefail

VENV_PATH="${XTTS_VENV_PATH:-$HOME/.openclaw/venvs/xtts}"
PY_BIN="$VENV_PATH/bin/python"

mkdir -p "$(dirname "$VENV_PATH")"
python3 -m venv --system-site-packages "$VENV_PATH"

"$PY_BIN" -m pip install --upgrade pip
"$PY_BIN" -m pip install coqui-tts torchaudio "transformers==4.57.1" "tokenizers<=0.22.0,>=0.21.0" "coqui-tts[codec]"

# Required by XTTS first download flow (CPML / commercial license prompt).
export COQUI_TOS_AGREED=1

"$PY_BIN" - <<'PY'
from TTS.api import TTS
import torch

model = "tts_models/multilingual/multi-dataset/xtts_v2"
print("Warming model:", model)
tts = TTS(model)
if torch.cuda.is_available():
    tts = tts.to("cuda")
print("XTTS ready.")
PY

cat <<EOF
OK: XTTS local instalado.
- venv: $VENV_PATH
- python: $PY_BIN
Sugerencia:
  export DIRECT_CHAT_PYTHON="$PY_BIN"
  export COQUI_TOS_AGREED=1
EOF
