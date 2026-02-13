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
./scripts/n8n_webhook_inventory.sh | sed -n '1,120p'

echo
echo "== webhook smoke =="
WEBHOOK_URL="http://127.0.0.1:5678/webhook/test-manos" \
WORKFLOW_ID="Hrz7BjjUW5dkKfJA" \
METHOD="GET" \
./scripts/n8n_run_and_check.sh || FAIL=1

check_code "lucy-input" "200" -X POST http://127.0.0.1:5678/webhook/lucy-input -H 'content-type: application/json' --data '{"text":"smoke"}'
check_code "voice-input" "200" -X POST http://127.0.0.1:5678/webhook/voice-input -H 'content-type: application/json' --data '{"text":"smoke"}'

if [[ "$FAIL" -ne 0 ]]; then
  echo "SMOKE=FAIL"
  exit 1
fi

echo "SMOKE=PASS"
