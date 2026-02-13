#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_STRESS="${RUN_STRESS:-false}"
SERVICES="${SERVICES:-n8n antigravity searxng}"
APPLY_GATEWAY_PATCH="${APPLY_GATEWAY_PATCH:-true}"

echo "[bringup] init IPC layout"
./scripts/ipc_layout_init.sh ./ipc

echo "[bringup] compose_infra up -d --build ${SERVICES}"
./scripts/compose_infra.sh up -d --build ${SERVICES}

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

if [[ "$APPLY_GATEWAY_PATCH" == "true" ]]; then
  echo "[bringup] applying Lucy Gateway v1 patch"
  ./scripts/n8n_patch_lucy_gateway_v1.sh
  URL_MODE=hardcoded ANTIGRAVITY_TARGET_URL="http://127.0.0.1:5000/execute" ./scripts/n8n_set_antigravity_url.sh >/dev/null || true
  ./scripts/compose_infra.sh restart n8n >/dev/null
  wait_http "n8n-post-patch" "http://127.0.0.1:5678/healthz"
fi

echo "[bringup] running webhook smoke"
if ! ./scripts/webhook_smoke.sh; then
  echo "[bringup] smoke failed, diagnostics:"
  ./scripts/compose_infra.sh ps
  docker logs --tail 120 lucy_brain_n8n || true
  docker logs --tail 120 lucy_hands_antigravity || true
  exit 1
fi

if [[ "$RUN_STRESS" == "true" ]]; then
  echo "[bringup] running stress matrix"
  ./scripts/n8n_stress_matrix.sh
fi

echo "BRINGUP=PASS"
