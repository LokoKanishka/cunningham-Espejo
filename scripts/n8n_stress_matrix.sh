#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

OK_RATE_MIN_DEFAULT="${OK_RATE_MIN_DEFAULT:-0.995}"
FAIL=0

run_case() {
  local label="$1"
  local url="$2"
  local method="$3"
  local body="$4"
  local n="$5"
  local p="$6"
  local ok_rate_min="$7"
  local p95_max="${8:-}"
  local endpoint_label="$9"

  echo "== scenario: $label =="
  if ! URL="$url" METHOD="$method" REQUEST_BODY="$body" N="$n" P="$p" OK_RATE_MIN="$ok_rate_min" P95_MAX_S="$p95_max" ENDPOINT_LABEL="$endpoint_label" ./scripts/n8n_stress.sh | sed -n '1,120p'; then
    FAIL=1
  fi
  echo
}

NOW_TS="$(date --iso-8601=seconds)"
LUCY_BODY="{\"kind\":\"text\",\"source\":\"stress\",\"ts\":\"${NOW_TS}\",\"text\":\"stress\"}"

run_case "healthz n8n" "http://127.0.0.1:5678/healthz" "GET" "" 2000 50 "${OK_RATE_MIN_DEFAULT}" "0.050" "healthz"
run_case "webhook test-manos" "http://127.0.0.1:5678/webhook/test-manos" "GET" "" 1000 25 "0.995" "0.200" "test-manos"
run_case "webhook lucy-input" "http://127.0.0.1:5678/webhook/lucy-input" "POST" "$LUCY_BODY" 500 20 "0.980" "0.300" "lucy-input"

echo "Done. Check ./_stress/"
[[ "$FAIL" -eq 0 ]] || exit 1
