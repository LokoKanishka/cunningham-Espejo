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
      if command -v ollama >/dev/null 2>&1; then
        openclaw models set ollama/gpt-oss:20b >/dev/null 2>&1 || true
        openclaw agent --agent main --message '/new ollama/gpt-oss:20b' --timeout 90 >/dev/null 2>&1 || true
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
