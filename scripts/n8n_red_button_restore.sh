#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-lucy_brain_n8n}"
BACKUP_BASE="${BACKUP_BASE:-./backups/n8n}"
BACKUP_DIR="${BACKUP_DIR:-}"
TIMEOUT="${TIMEOUT:-30}"
DRY_RUN="${DRY_RUN:-false}"
RUN_SMOKE="${RUN_SMOKE:-true}"
SMOKE_SCRIPT="${SMOKE_SCRIPT:-./scripts/webhook_smoke.sh}"
ROLLBACK_ON_FAIL="${ROLLBACK_ON_FAIL:-true}"

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

restore_from_dir() {
  local restore_dir="$1"
  [[ -d "$restore_dir/workflows" ]] || { echo "[restore] ERROR: falta ${restore_dir}/workflows"; return 1; }
  [[ -d "$restore_dir/credentials" ]] || { echo "[restore] ERROR: falta ${restore_dir}/credentials"; return 1; }

  local tmp_base="/tmp/restore_$(date +%s)_$RANDOM"
  docker exec -u node "$CONTAINER" mkdir -p "$tmp_base/workflows" "$tmp_base/credentials"
  docker cp "$restore_dir/workflows/." "$CONTAINER":"$tmp_base/workflows/"
  docker cp "$restore_dir/credentials/." "$CONTAINER":"$tmp_base/credentials/"

  docker exec -u node "$CONTAINER" n8n import:credentials --separate --input="$tmp_base/credentials"
  docker exec -u node "$CONTAINER" n8n import:workflow --separate --input="$tmp_base/workflows"
  docker exec -u node "$CONTAINER" rm -rf "$tmp_base"

  # Reactivate workflows that were active in the backup set.
  mapfile -t active_ids < <(python3 - <<'PY' "$restore_dir/workflows"
import json
import sys
from pathlib import Path
base = Path(sys.argv[1])
for f in sorted(base.glob('*.json')):
    try:
        obj = json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        continue
    if isinstance(obj, list) and obj:
        obj = obj[0]
    if isinstance(obj, dict) and obj.get('active') and obj.get('id'):
        print(obj['id'])
PY
  )
  for wid in "${active_ids[@]:-}"; do
    [[ -n "$wid" ]] || continue
    docker exec -u node "$CONTAINER" n8n update:workflow --id="$wid" --active=true >/dev/null || true
  done

  URL_MODE=hardcoded ANTIGRAVITY_TARGET_URL="http://127.0.0.1:5000/execute" ./scripts/n8n_set_antigravity_url.sh >/dev/null || true
  docker restart "$CONTAINER" >/dev/null
}

if [[ -z "$BACKUP_DIR" ]]; then
  BACKUP_DIR="$(pick_latest_backup)"
fi

[[ -n "$BACKUP_DIR" ]] || { echo "[restore] ERROR: no hay backups en ${BACKUP_BASE}"; exit 1; }

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[restore] DRY_RUN activo"
  echo "[restore] target_backup=$BACKUP_DIR"
  [[ -d "$BACKUP_DIR/workflows" ]] || { echo "[restore] ERROR: falta workflows"; exit 1; }
  [[ -d "$BACKUP_DIR/credentials" ]] || { echo "[restore] ERROR: falta credentials"; exit 1; }
  exit 0
fi

docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q "^${CONTAINER}$" \
  || { echo "[restore] ERROR: container '$CONTAINER' no está corriendo"; exit 1; }

echo "[restore] container=$CONTAINER"
echo "[restore] backup_dir=$BACKUP_DIR"
echo "[restore] run_smoke=$RUN_SMOKE rollback_on_fail=$ROLLBACK_ON_FAIL"

health_wait "$TIMEOUT"

PRE_BACKUP=""
if [[ "$ROLLBACK_ON_FAIL" == "true" ]]; then
  SNAP_BASE="${BACKUP_BASE}/pre_restore_snapshots"
  echo "[restore] creando snapshot previo en $SNAP_BASE"
  BASE_DIR="$SNAP_BASE" ./scripts/n8n_backup.sh >/dev/null
  PRE_BACKUP="$(ls -1dt "$SNAP_BASE"/* | head -n 1)"
  echo "[restore] pre_snapshot=$PRE_BACKUP"
fi

restore_from_dir "$BACKUP_DIR"
health_wait "$TIMEOUT"

if [[ "$RUN_SMOKE" == "true" ]]; then
  echo "[restore] running smoke: $SMOKE_SCRIPT"
  if ! "$SMOKE_SCRIPT"; then
    echo "[restore] smoke FAIL"
    if [[ "$ROLLBACK_ON_FAIL" == "true" && -n "$PRE_BACKUP" ]]; then
      echo "[restore] rollback from $PRE_BACKUP"
      restore_from_dir "$PRE_BACKUP"
      health_wait "$TIMEOUT"
      echo "[restore] rollback complete"
    fi
    exit 1
  fi
fi

echo "[restore] OK"
