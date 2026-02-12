#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-lucy_brain_n8n}"
BACKUP_BASE="${BACKUP_BASE:-./backups/n8n}"
BACKUP_DIR="${BACKUP_DIR:-}"
TIMEOUT="${TIMEOUT:-30}"
DRY_RUN="${DRY_RUN:-false}"

pick_latest_backup() {
  ls -1dt "${BACKUP_BASE}"/* 2>/dev/null | head -n 1 || true
}

health_wait() {
  local tries="${1:-30}"
  local i code
  for i in $(seq 1 "$tries"); do
    code="$(curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:5678/healthz 2>/dev/null || true)"
    if [[ "$code" == "200" ]]; then
      echo "[health] ok t=${i}s"
      return 0
    fi
    sleep 1
  done
  echo "[health] ERROR no respondió 200 en ${tries}s"
  return 1
}

if [[ -z "$BACKUP_DIR" ]]; then
  BACKUP_DIR="$(pick_latest_backup)"
fi

[[ -n "$BACKUP_DIR" ]] || { echo "[restore] ERROR: no hay backups en ${BACKUP_BASE}"; exit 1; }
[[ -d "$BACKUP_DIR/workflows" ]] || { echo "[restore] ERROR: falta ${BACKUP_DIR}/workflows"; exit 1; }
[[ -d "$BACKUP_DIR/credentials" ]] || { echo "[restore] ERROR: falta ${BACKUP_DIR}/credentials"; exit 1; }

docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q "^${CONTAINER}$" \
  || { echo "[restore] ERROR: container '$CONTAINER' no está corriendo"; exit 1; }

echo "[restore] container=$CONTAINER"
echo "[restore] backup_dir=$BACKUP_DIR"
echo "[restore] dry_run=$DRY_RUN"

health_wait "$TIMEOUT"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[restore] DRY_RUN activo: no se importa nada"
  exit 0
fi

# copy backup into container temp dir
TMP_BASE="/tmp/restore_$(date +%s)"
docker exec -u node "$CONTAINER" mkdir -p "$TMP_BASE/workflows" "$TMP_BASE/credentials"
docker cp "$BACKUP_DIR/workflows/." "$CONTAINER":"$TMP_BASE/workflows/"
docker cp "$BACKUP_DIR/credentials/." "$CONTAINER":"$TMP_BASE/credentials/"

# import credentials first, then workflows
docker exec -u node "$CONTAINER" n8n import:credentials --separate --input="$TMP_BASE/credentials"
docker exec -u node "$CONTAINER" n8n import:workflow --separate --input="$TMP_BASE/workflows"

docker exec -u node "$CONTAINER" rm -rf "$TMP_BASE"

health_wait "$TIMEOUT"

echo "[restore] OK"
