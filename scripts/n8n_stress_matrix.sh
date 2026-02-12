#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Matriz “real” (la que le vamos a dar a Codex)
SCENARIOS=(
  "N=2000 P=50"
  "N=10000 P=100"
  "N=30000 P=200"
)

URL="${URL:-http://127.0.0.1:5678/healthz}"
OK_RATE_MIN="${OK_RATE_MIN:-0.995}"

echo "URL=$URL OK_RATE_MIN=$OK_RATE_MIN"
echo

for s in "${SCENARIOS[@]}"; do
  echo "== scenario: $s =="
  (export URL OK_RATE_MIN; export $s; ./scripts/n8n_stress.sh) | sed -n '1,120p'
  echo
done

echo "Done. Check ./_stress/"
