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

  echo "== scenario: $label =="
  if ! URL="$url" METHOD="$method" REQUEST_BODY="$body" N="$n" P="$p" OK_RATE_MIN="$ok_rate_min" ./scripts/n8n_stress.sh | sed -n '1,120p'; then
    FAIL=1
  fi
  echo
}

run_case "healthz n8n" "http://127.0.0.1:5678/healthz" "GET" "" 2000 50 "${OK_RATE_MIN_DEFAULT}"
run_case "webhook test-manos" "http://127.0.0.1:5678/webhook/test-manos" "GET" "" 1000 25 "0.995"
run_case "webhook lucy-input" "http://127.0.0.1:5678/webhook/lucy-input" "POST" '{"text":"stress"}' 300 10 "0.950"

echo "Done. Check ./_stress/"
[[ "$FAIL" -eq 0 ]] || exit 1
