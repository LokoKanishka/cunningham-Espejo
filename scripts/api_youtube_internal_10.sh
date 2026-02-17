#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOCK_FILE="/tmp/cunningham_api_youtube_internal_10.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "ERROR: ya hay una corrida activa (lock: $LOCK_FILE)" >&2
  exit 1
fi

need_bin() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing dependency '$1'" >&2
    exit 1
  }
}

need_bin curl
need_bin jq
need_bin wmctrl

WS="$(wmctrl -d | awk '$2=="*"{print $1; exit}')"
SESSION="api_yt_$(date +%s)"
OUT_DIR="${HOME}/.openclaw/logs"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/api_youtube_internal_${SESSION}.log"

python3 scripts/openclaw_direct_chat.py --host 127.0.0.1 --port 8787 >/tmp/openclaw_dc_api_test.log 2>&1 &
DC_PID=$!
cleanup() {
  kill "$DC_PID" >/dev/null 2>&1 || true
  wait "$DC_PID" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 70); do
  if curl -sS -m 1 "http://127.0.0.1:8787/api/history?session=ping" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

msgs=(
  "busca lo-fi chill en youtube y reproduci el primer video"
  "buscá tutorial python para principiantes en youtube y poné a reproducir el primer resultado"
  "investiga en youtube musica ambiental lluvia y abrí un video para que se reproduzca"
  "busca en youtube documental agujeros negros, abrí primer video y reproducilo"
  "en youtube buscá recetas de pizza napolitana y poné el primer video"
  "quiero un video de youtube sobre historia de roma, abrí el primero y reproducilo"
  "busca meditacion guiada en youtube y dale play al primer video"
  "buscá noticias tecnologia hoy en youtube, abrí primer video y reproducilo"
  "en youtube busca musica focus y abrí un video para reproducir"
  "youtube busca teoria de la relatividad explicada y reproducí el primer video"
)

open_ok=0
close_ok=0
safety_ok=0
api_fail=0

yt_ws_ids() {
  wmctrl -lp | awk -v d="$WS" '$2==d{l=tolower($0); if(l ~ /youtube/) print $1}'
}

yt_other_ids() {
  wmctrl -lp | awk -v d="$WS" '$2!=d{l=tolower($0); if(l ~ /youtube/) print $1 ":" $2}'
}

echo "session=$SESSION ws=$WS" >>"$LOG"

for i in $(seq 0 9); do
  idx=$((i + 1))
  msg="${msgs[$i]}"
  before_other="$(yt_other_ids | tr '\n' ' ')"

  payload="$(jq -cn --arg m "$msg" --arg s "$SESSION" '{message:$m,session_id:$s,mode:"operativo",allowed_tools:["firefox","web_search","web_ask","desktop","model"]}')"
  resp="$(curl -sS -m 70 -H 'content-type: application/json' -d "$payload" http://127.0.0.1:8787/api/chat || true)"
  if ! jq -e . >/dev/null 2>&1 <<<"$resp"; then
    api_fail=$((api_fail + 1))
  fi

  found=0
  for _ in $(seq 1 70); do
    n="$(yt_ws_ids | wc -l | tr -d ' ')"
    if [[ "$n" != "0" ]]; then
      found=1
      break
    fi
    sleep 0.25
  done
  if [[ "$found" == "1" ]]; then
    open_ok=$((open_ok + 1))
  fi

  close_payload="$(jq -cn --arg m 'cerrá las ventanas web que abriste' --arg s "$SESSION" '{message:$m,session_id:$s,mode:"operativo",allowed_tools:["firefox","web_search","web_ask","desktop","model"]}')"
  close_resp="$(curl -sS -m 35 -H 'content-type: application/json' -d "$close_payload" http://127.0.0.1:8787/api/chat || true)"
  if ! jq -e . >/dev/null 2>&1 <<<"$close_resp"; then
    api_fail=$((api_fail + 1))
  fi

  closed=0
  for _ in $(seq 1 60); do
    n="$(yt_ws_ids | wc -l | tr -d ' ')"
    if [[ "$n" == "0" ]]; then
      closed=1
      break
    fi
    sleep 0.25
  done
  if [[ "$closed" == "1" ]]; then
    close_ok=$((close_ok + 1))
  fi

  after_other="$(yt_other_ids | tr '\n' ' ')"
  if [[ "$before_other" == "$after_other" ]]; then
    safety_ok=$((safety_ok + 1))
  fi

  echo "[$idx] msg=$msg" >>"$LOG"
  echo "open=$found close=$closed" >>"$LOG"
  echo "reply=$(jq -r '.reply // .error // "(no-reply)"' <<<"$resp" 2>/dev/null | tr '\n' ' ' | cut -c1-260)" >>"$LOG"
  echo "close_reply=$(jq -r '.reply // .error // "(no-reply)"' <<<"$close_resp" 2>/dev/null | tr '\n' ' ' | cut -c1-200)" >>"$LOG"
  echo "---" >>"$LOG"
done

echo "SUMMARY session=$SESSION ws=$WS open_ok=$open_ok/10 close_ok=$close_ok/10 safety_ok=$safety_ok/10 api_fail=$api_fail log=$LOG"
