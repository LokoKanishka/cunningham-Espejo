#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_STRESS="${RUN_STRESS:-false}"
SERVICES="${SERVICES:-n8n antigravity searxng}"

echo "[bringup] docker compose up -d --build ${SERVICES}"
docker compose up -d --build ${SERVICES}

wait_http() {
  local name="$1"
  local url="$2"
  local tries="${3:-60}"
  for i in $(seq 1 "$tries"); do
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
    if [[ "$code" == "200" ]]; then
      echo "[bringup] $name ok t=${i}s"
      return 0
    fi
    sleep 1
  done
  echo "[bringup] $name failed url=$url"
  return 1
}

wait_http "n8n" "http://127.0.0.1:5678/healthz"
wait_http "antigravity" "http://127.0.0.1:5000/healthz"
wait_http "searxng" "http://127.0.0.1:8080/"

echo "[bringup] running webhook smoke"
if ! ./scripts/webhook_smoke.sh; then
  echo "[bringup] smoke failed, diagnostics:"
  docker compose ps
  docker logs --tail 120 lucy_brain_n8n || true
  docker logs --tail 120 lucy_hands_antigravity || true
  exit 1
fi

if [[ "$RUN_STRESS" == "true" ]]; then
  echo "[bringup] running stress matrix"
  ./scripts/n8n_stress_matrix.sh
fi

echo "BRINGUP=PASS"
