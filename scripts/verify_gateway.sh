#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.openclaw/bin:$PATH"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "== verify gateway ==" >&2

for svc in clawdbot-gateway.service clawdbot-node.service; do
  state="$(systemctl --user is-active "$svc" 2>/dev/null || true)"
  if [ "$state" = "active" ] || [ "$state" = "activating" ]; then
    fail "legacy service '$svc' is $state; disable it to avoid model/config drift"
  fi
done

listener="$(ss -ltnp | rg '127.0.0.1:18789|\[::1\]:18789' || true)"
if printf "%s\n" "$listener" | rg -q 'clawdbot-gatewa'; then
  fail "port 18789 is owned by clawdbot-gateway; expected openclaw-gateway"
fi

if ! openclaw health >/dev/null 2>&1; then
  echo "gateway unreachable; starting foreground gateway in background..." >&2
  nohup openclaw gateway --force > "$HOME/.openclaw/gateway-foreground.log" 2>&1 &

  ok=0
  for _ in $(seq 1 20); do
    if openclaw health >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 1
  done

  if [ "$ok" -ne 1 ]; then
    echo "== gateway log tail ==" >&2
    tail -n 80 "$HOME/.openclaw/gateway-foreground.log" >&2 || true
    fail "gateway did not become healthy"
  fi
fi

proc_line="$(ss -ltnp | rg '127.0.0.1:18789|\[::1\]:18789' || true)"
if ! printf "%s\n" "$proc_line" | rg -q 'openclaw-gatewa'; then
  fail "port 18789 is not owned by openclaw-gateway"
fi

echo "OK" >&2
