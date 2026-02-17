#!/usr/bin/env bash
set -euo pipefail

KEY="${1:-}"
MODEL_LIST="${2:-gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash}"
ENV_FILE="${OPENCLAW_DIRECT_CHAT_ENV:-$HOME/.openclaw/direct_chat.env}"

if [ -z "$KEY" ]; then
  echo "Uso: $0 <GEMINI_API_KEY> [modelos_csv]" >&2
  echo "Ejemplo: $0 AIza... \"gemini-2.5-flash,gemini-2.0-flash\"" >&2
  exit 1
fi

mkdir -p "$(dirname "$ENV_FILE")"
cat > "$ENV_FILE" <<EOF
GEMINI_API_ENABLED=1
GEMINI_API_KEY=$KEY
GEMINI_API_MODELS=$MODEL_LIST
GEMINI_API_ALLOW_PAID=0
GEMINI_API_FREE_MODELS=gemini-2.5-flash,gemini-2.0-flash,gemini-1.5-flash
GEMINI_API_DAILY_LIMIT=200
GEMINI_API_PROMPT_CHAR_LIMIT=2500
EOF
chmod 600 "$ENV_FILE"

echo "Guardado: $ENV_FILE"
echo "Reinicia dc con: scripts/openclaw_direct_chat.sh 8787"
