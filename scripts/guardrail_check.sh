#!/usr/bin/env bash
set -euo pipefail

SESSION_ID="${1:-}"
TOOL_NAME="${2:-}"
PARAMS_JSON="${3:-"{}"}"

MAX_TOOLS_PER_WINDOW="${MAX_TOOLS_PER_WINDOW:-10}"
WINDOW_SECONDS="${WINDOW_SECONDS:-3600}"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
ALLOWED_DOMAINS_FILE="${ALLOWED_DOMAINS_FILE:-config/allowed_domains.txt}"

if [[ -z "$SESSION_ID" || -z "$TOOL_NAME" ]]; then
  echo "usage: $0 <session_id> <tool_name> [params_json]" >&2
  exit 2
fi

redis_cmd() {
  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli -u "$REDIS_URL" "$@"
    return
  fi
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx 'lucy_memory_redis'; then
    docker exec lucy_memory_redis redis-cli -n 0 "$@"
    return
  fi
  echo "GUARDRAIL_ERROR: redis-cli no disponible" >&2
  return 127
}

KEY="session:${SESSION_ID}:tool_count"
COUNT="$(redis_cmd INCR "$KEY" | tr -d '\r')"
if [[ "$COUNT" == "1" ]]; then
  redis_cmd EXPIRE "$KEY" "$WINDOW_SECONDS" >/dev/null
fi

if (( COUNT > MAX_TOOLS_PER_WINDOW )); then
  echo "RATE_LIMIT_EXCEEDED: session=${SESSION_ID} count=${COUNT} limit=${MAX_TOOLS_PER_WINDOW}" >&2
  exit 10
fi

readarray -t EXTRACTED < <(python3 - "$TOOL_NAME" "$PARAMS_JSON" <<'PY'
import json
import sys
from urllib.parse import urlparse

_tool = sys.argv[1]
raw = sys.argv[2]
try:
    params = json.loads(raw) if raw else {}
except Exception:
    params = {}

def pick(*keys):
    for k in keys:
        v = params.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

url = pick("url", "href", "link", "target")
payload = pick("cmd", "command", "code", "script", "bash", "python", "prompt")
host = (urlparse(url).hostname or "").lower().strip(".") if url else ""

print(url)
print(host)
print(payload)
PY
)

TARGET_URL="${EXTRACTED[0]:-}"
TARGET_HOST="${EXTRACTED[1]:-}"
PAYLOAD_TEXT="${EXTRACTED[2]:-}"

if [[ "$TOOL_NAME" == "browser_vision" ]]; then
  if [[ -z "$TARGET_URL" || -z "$TARGET_HOST" ]]; then
    echo "POLICY_DENY: browser_vision sin URL/host valido" >&2
    exit 20
  fi
  if [[ ! -f "$ALLOWED_DOMAINS_FILE" ]]; then
    echo "POLICY_DENY: falta allowlist $ALLOWED_DOMAINS_FILE" >&2
    exit 21
  fi

  ALLOWED=0
  while IFS= read -r line; do
    domain="$(echo "$line" | sed 's/#.*//' | xargs)"
    [[ -z "$domain" ]] && continue
    domain="${domain#.}"
    if [[ "$TARGET_HOST" == "$domain" || "$TARGET_HOST" == *".${domain}" ]]; then
      ALLOWED=1
      break
    fi
  done < "$ALLOWED_DOMAINS_FILE"

  if [[ "$ALLOWED" -ne 1 ]]; then
    echo "POLICY_DENY: dominio no permitido ($TARGET_HOST)" >&2
    exit 23
  fi
fi

if [[ "$TOOL_NAME" == "bash" || "$TOOL_NAME" == "python" || "$TOOL_NAME" == "code_exec" ]]; then
  BLOCKED_REGEX='rm[[:space:]]+-rf[[:space:]]+/|mkfs(\.|[[:space:]])|dd[[:space:]]+if=|:\(\)\{:\|:\&\};:|shutdown[[:space:]]+-h|reboot'
  if grep -Eiq "$BLOCKED_REGEX" <<<"$PAYLOAD_TEXT"; then
    echo "POLICY_DENY: comando peligroso detectado" >&2
    exit 30
  fi
fi

echo "GUARDRAIL_OK: session=${SESSION_ID} tool=${TOOL_NAME} count=${COUNT}"
exit 0
