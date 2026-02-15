#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

LOG_DIR="$HOME/.openclaw/logs"
LOG_FILE="$LOG_DIR/launch_l_cunningham.log"
mkdir -p "$LOG_DIR"

echo "[launch] $(date -Is) starting" >>"$LOG_FILE"

# Ensure SearXNG is up (needed for web_search). Keep it lightweight by default.
if command -v docker >/dev/null 2>&1; then
  if ! docker ps --format '{{.Names}}' | grep -qx 'lucy_eyes_searxng'; then
    echo "[launch] searxng container not running; bringup searxng" >>"$LOG_FILE"
    SERVICES="${SERVICES:-searxng}" APPLY_GATEWAY_PATCH="${APPLY_GATEWAY_PATCH:-false}" ./scripts/bringup_all.sh >>"$LOG_FILE" 2>&1 || true
  fi
fi

# Start/restart the Direct Chat UI service.
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user restart openclaw-direct-chat.service >>"$LOG_FILE" 2>&1 || true
fi

wait_http() {
  local url="$1"
  local tries="${2:-40}"
  for _ in $(seq 1 "$tries"); do
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
    if [[ "$code" == "200" ]]; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

UI_URL="${DIRECT_CHAT_URL:-http://127.0.0.1:8787/}"
if ! wait_http "$UI_URL" 60; then
  echo "[launch] UI not ready at $UI_URL" >>"$LOG_FILE"
fi

# Open in Chrome, forcing the "diego" profile if present.
CHROME_BIN="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium-browser || command -v chromium || true)"
if [[ -n "$CHROME_BIN" ]]; then
  PROFILE_DIR="$(python3 - <<'PY'
import json, os
root = os.path.expanduser("~/.config/google-chrome")
local_state = os.path.join(root, "Local State")
hint = "diego"
if os.path.exists(local_state):
    try:
        data = json.load(open(local_state, "r", encoding="utf-8"))
        info = data.get("profile", {}).get("info_cache", {})
        for key, value in info.items():
            if str(value.get("name", "")).strip().lower() == hint:
                print(key)
                raise SystemExit(0)
    except Exception:
        pass
print("Default")
PY
)"
  echo "[launch] opening chrome profile=$PROFILE_DIR url=$UI_URL" >>"$LOG_FILE"
  "$CHROME_BIN" \
    --user-data-dir="$HOME/.config/google-chrome" \
    --profile-directory="$PROFILE_DIR" \
    --new-window \
    "$UI_URL" >/dev/null 2>&1 &
  exit 0
fi

echo "[launch] chrome not found; fallback xdg-open url=$UI_URL" >>"$LOG_FILE"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$UI_URL" >/dev/null 2>&1 &
fi

