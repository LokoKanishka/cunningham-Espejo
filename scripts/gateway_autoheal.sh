#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

interval="${AUTOHEAL_INTERVAL:-5}"
loops="${AUTOHEAL_LOOPS:-12}"
logf="${AUTOHEAL_LOG:-DOCS/RUNS/gateway_autoheal.log}"

mkdir -p "$(dirname "$logf")"

check_once() {
  if openclaw health >/dev/null 2>&1; then
    echo "$(date -Is) HEALTHY" >> "$logf"
    return 0
  fi

  echo "$(date -Is) UNHEALTHY -> restart" >> "$logf"
  if [ -x ./scripts/verify_gateway.sh ]; then
    ./scripts/verify_gateway.sh >/dev/null 2>&1 || true
  else
    nohup openclaw gateway --force >/tmp/openclaw-gateway-autoheal.log 2>&1 &
    sleep 2
  fi

  if openclaw health >/dev/null 2>&1; then
    echo "$(date -Is) RECOVERED" >> "$logf"
    return 0
  fi
  echo "$(date -Is) STILL_DOWN" >> "$logf"
  return 1
}

cmd="${1:-check}"
case "$cmd" in
  check)
    openclaw health >/dev/null 2>&1 || true
    echo "GATEWAY_AUTOHEAL_OK"
    ;;
  once)
    check_once
    ;;
  run)
    i=0
    while [ "$i" -lt "$loops" ]; do
      check_once || true
      i=$((i+1))
      sleep "$interval"
    done
    echo "AUTOHEAL_DONE loops=$loops log=$logf"
    ;;
  *)
    echo "usage: $0 {check|once|run}" >&2
    exit 2
    ;;
esac
