#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

FAIL=0

check_code() {
  local name="$1"
  local expected="$2"
  shift 2
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$@")" || code="000"
  echo "[$name] http=$code expected=$expected"
  [[ "$code" == "$expected" ]] || FAIL=1
}

echo "== inventory =="
STRICT_CONFLICTS=true ./scripts/n8n_webhook_inventory.sh | sed -n '1,160p' || FAIL=1

echo
echo "== contract smoke =="
./scripts/webhook_contract_smoke.sh || FAIL=1

echo
echo "== gateway e2e =="
./scripts/n8n_gateway_e2e.sh || FAIL=1

echo
echo "== test_manos =="
docker exec lucy_brain_n8n sh -lc 'mkdir -p /data/lucy_ipc/inbox && echo smoke > /data/lucy_ipc/inbox/test_n8n.txt' >/dev/null 2>&1 || true
WEBHOOK_URL="http://127.0.0.1:5678/webhook/test-manos" \
WORKFLOW_ID="Hrz7BjjUW5dkKfJA" \
METHOD="GET" \
./scripts/n8n_run_and_check.sh || FAIL=1

echo
echo "== endpoint checks =="
check_code "lucy-input" "200" -X POST http://127.0.0.1:5678/webhook/lucy-input -H 'content-type: application/json' --data '{"text":"smoke"}'
check_code "voice-input" "200" -X POST http://127.0.0.1:5678/webhook/voice-input -H 'content-type: application/json' --data '{"text":"smoke"}'

if [[ "$FAIL" -ne 0 ]]; then
  echo "SMOKE=FAIL"
  exit 1
fi

echo "SMOKE=PASS"
