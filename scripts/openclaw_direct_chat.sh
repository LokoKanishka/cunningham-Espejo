#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8787}"
LOG="DOCS/RUNS/openclaw_direct_chat.log"
PID_FILE="/tmp/openclaw_direct_chat.pid"
ENV_FILE="${OPENCLAW_DIRECT_CHAT_ENV:-$HOME/.openclaw/direct_chat.env}"

mkdir -p DOCS/RUNS

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

# Workspace policy default: fixed isolated workspace (don't follow active desktop).
: "${DIRECT_CHAT_FOLLOW_ACTIVE_WORKSPACE:=0}"
export DIRECT_CHAT_FOLLOW_ACTIVE_WORKSPACE
# Avoid temporary desktop jumps by default.
: "${DIRECT_CHAT_TEMP_SWITCH_WORKSPACE:=0}"
export DIRECT_CHAT_TEMP_SWITCH_WORKSPACE

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    sleep 0.2
  fi
fi

nohup python3 scripts/openclaw_direct_chat.py --port "$PORT" >"$LOG" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"

sleep 0.7
echo "OPENCLAW_DIRECT_CHAT_URL=http://127.0.0.1:$PORT"
echo "OPENCLAW_DIRECT_CHAT_PID=$pid"
echo "OPENCLAW_DIRECT_CHAT_LOG=$LOG"
