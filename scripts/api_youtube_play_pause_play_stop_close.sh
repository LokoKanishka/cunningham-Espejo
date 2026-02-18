#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

need_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing dependency '$1'" >&2
    exit 1
  }
}

need_bin curl
need_bin jq
need_bin wmctrl

PORT="${DC_PORT:-8788}"
USE_EXISTING_DC="${USE_EXISTING_DC:-0}"
SESSION="api_yt_seq_$(date +%s)"
OUT_DIR="${HOME}/.openclaw/logs"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/api_youtube_seq_${SESSION}.log"

WS="$(wmctrl -d | awk '$2=="*"{print $1; exit}')"
if [[ -z "${WS:-}" ]]; then
  echo "ERROR: no active workspace detected" >&2
  exit 1
fi
yt_ws_ids() {
  wmctrl -lp | awk -v d="$WS" '$2==d{l=tolower($0); if(l ~ /youtube/) print $1}'
}

yt_other_ids() {
  wmctrl -lp | awk -v d="$WS" '$2!=d{l=tolower($0); if(l ~ /youtube/) print $1 ":" $2}'
}

STARTED_LOCAL=0
DC_PID=""
if [[ "$USE_EXISTING_DC" == "1" ]] && curl -sS -m 1 "http://127.0.0.1:${PORT}/api/history?session=ping" >/dev/null 2>&1; then
  :
else
  if curl -sS -m 1 "http://127.0.0.1:${PORT}/api/history?session=ping" >/dev/null 2>&1; then
    echo "ERROR: ya hay un direct-chat en puerto ${PORT}. Usá otro DC_PORT o USE_EXISTING_DC=1." >&2
    exit 1
  fi
  DC_PY_BIN="${DIRECT_CHAT_PYTHON:-$HOME/.openclaw/venvs/xtts/bin/python}"
  if [[ ! -x "$DC_PY_BIN" ]]; then
    DC_PY_BIN="python3"
  fi
  "$DC_PY_BIN" scripts/openclaw_direct_chat.py --host 127.0.0.1 --port "${PORT}" >/tmp/openclaw_dc_api_seq.log 2>&1 &
  DC_PID="$!"
  STARTED_LOCAL=1
fi

cleanup() {
  if [[ "$STARTED_LOCAL" == "1" && -n "$DC_PID" ]]; then
    kill "$DC_PID" >/dev/null 2>&1 || true
    wait "$DC_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

for _ in $(seq 1 70); do
  if curl -sS -m 1 "http://127.0.0.1:${PORT}/api/history?session=ping" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

api_fail=0
open_ok=0
pause_ok=0
play_ok=0
stop_close_ok=0
safety_ok=0

before_ws="$(yt_ws_ids | tr '\n' ' ')"
before_other="$(yt_other_ids | tr '\n' ' ')"

send_msg() {
  local msg="$1"
  local payload resp
  payload="$(jq -cn --arg m "$msg" --arg s "$SESSION" '{message:$m,session_id:$s,mode:"operativo",allowed_tools:["firefox","web_search","web_ask","desktop","model"]}')"
  resp="$(curl -sS -m 70 -H 'content-type: application/json' -d "$payload" "http://127.0.0.1:${PORT}/api/chat" || true)"
  if ! jq -e . >/dev/null 2>&1 <<<"$resp"; then
    api_fail=$((api_fail + 1))
  fi
  echo "msg=$msg" >>"$LOG"
  echo "reply=$(jq -r '.reply // .error // "(no-reply)"' <<<"$resp" 2>/dev/null | tr '\n' ' ' | cut -c1-360)" >>"$LOG"
  echo "---" >>"$LOG"
  printf '%s' "$resp"
}

open_resp="$(send_msg 'en youtube buscá lo-fi chill y reproducí el primer video')"
new_opened=0
for _ in $(seq 1 80); do
  now_ws="$(yt_ws_ids | tr '\n' ' ')"
  if [[ "$now_ws" != "$before_ws" ]]; then
    new_opened=1
    break
  fi
  sleep 0.25
done
if [[ "$new_opened" == "1" ]]; then
  open_ok=1
fi

sleep 20

pause_resp="$(send_msg 'en youtube pausá el video actual')"
if jq -r '.reply // ""' <<<"$pause_resp" | tr '[:upper:]' '[:lower:]' | rg -q "pause|paus|detuve youtube"; then
  pause_ok=1
fi

sleep 20

play_resp="$(send_msg 'en youtube reanudá la reproducción del video actual')"
if jq -r '.reply // ""' <<<"$play_resp" | tr '[:upper:]' '[:lower:]' | rg -q "rean|reanud|play"; then
  play_ok=1
fi

sleep 5

stop_close_resp="$(send_msg 'en youtube detené el video actual y cerrá la ventana')"
closed_back=0
for _ in $(seq 1 70); do
  now_ws="$(yt_ws_ids | tr '\n' ' ')"
  if [[ "$now_ws" == "$before_ws" ]]; then
    closed_back=1
    break
  fi
  sleep 0.25
done
if [[ "$closed_back" == "1" ]]; then
  stop_close_ok=1
fi

after_other="$(yt_other_ids | tr '\n' ' ')"
if [[ "$before_other" == "$after_other" ]]; then
  safety_ok=1
fi

echo "SUMMARY session=$SESSION ws=$WS open_ok=$open_ok pause_ok=$pause_ok play_ok=$play_ok stop_close_ok=$stop_close_ok safety_ok=$safety_ok api_fail=$api_fail log=$LOG"
