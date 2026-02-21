#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

choose_model() {
  txt="$1"
  prof="$(./scripts/task_profile.sh classify "$txt")"
  printf "%s\n" "$prof" | awk -F= '/^model=/{print $2}'
}

run_agent() {
  msg="$1"
  out="$(openclaw agent --agent main --json --timeout 120 --message "$msg" 2>&1 || true)"
  printf "%s" "$out"
}

has_ollama_model() {
  local mid="$1"
  command -v ollama >/dev/null 2>&1 || return 1
  ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fxq "$mid"
}

pick_local_fallback_model() {
  local candidate
  for candidate in \
    "gpt-oss:20b" \
    "huihui_ai/qwq-abliterated:32b-Q6_K" \
    "mistral-uncensored:latest" \
    "dolphin-mixtral:latest"
  do
    if has_ollama_model "$candidate"; then
      printf "ollama/%s\n" "$candidate"
      return 0
    fi
  done
  return 1
}

cmd="${1:-check}"
shift || true

case "$cmd" in
  check)
    ./scripts/task_profile.sh check >/dev/null
    echo "MODEL_ROUTER_OK"
    ;;
  ask)
    msg="${*:-}"
    [ -n "$msg" ] || { echo "usage: $0 ask <message>" >&2; exit 2; }
    m="$(choose_model "$msg")"
    openclaw models set "$m" >/dev/null 2>&1 || true
    openclaw agent --agent main --message "/new $m" --timeout 90 >/dev/null 2>&1 || true
    run_agent "$msg"
    ;;
  ask-with-fallback)
    msg="${*:-}"
    [ -n "$msg" ] || { echo "usage: $0 ask-with-fallback <message>" >&2; exit 2; }
    m="$(choose_model "$msg")"
    openclaw models set "$m" >/dev/null 2>&1 || true
    openclaw agent --agent main --message "/new $m" --timeout 90 >/dev/null 2>&1 || true
    out="$(run_agent "$msg")"
    if printf "%s" "$out" | grep -Eiq 'quota|rate limit|temporarily unavailable|429'; then
      local_fallback="$(pick_local_fallback_model || true)"
      if [ -n "$local_fallback" ]; then
        openclaw models set "$local_fallback" >/dev/null 2>&1 || true
        openclaw agent --agent main --message "/new $local_fallback" --timeout 90 >/dev/null 2>&1 || true
        out="$(run_agent "$msg")"
      fi
    fi
    printf "%s" "$out"
    ;;
  *)
    echo "usage: $0 {check|ask <message>|ask-with-fallback <message>}" >&2
    exit 2
    ;;
esac
