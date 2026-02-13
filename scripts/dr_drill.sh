#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_BASE="${BACKUP_BASE:-./backups/n8n}"
WIPE_BASE="${WIPE_BASE:-./_tmp}"
RESTORE_TIMEOUT="${RESTORE_TIMEOUT:-60}"
SNAP_RETAIN="${SNAP_RETAIN:-14}"

TS="$(date +%Y%m%d_%H%M%S)"
WIPE_DIR="$WIPE_BASE/wipe_${TS}"
ORIG_DIR="$WIPE_DIR/n8n_original"
mkdir -p "$WIPE_DIR"

rollback_original_data() {
  echo "[dr] rollback original data"
  ./scripts/compose_infra.sh stop n8n >/dev/null || true
  rm -rf data/n8n
  if [[ -d "$ORIG_DIR" ]]; then
    mv "$ORIG_DIR" data/n8n
  fi
  ./scripts/compose_infra.sh up -d n8n >/dev/null
  ./scripts/webhook_smoke.sh || true
}

echo "[dr] step=backup"
RETAIN="$SNAP_RETAIN" BASE_DIR="$BACKUP_BASE" ./scripts/n8n_backup.sh
BACKUP_DIR="$(ls -1dt "$BACKUP_BASE"/* | head -n 1)"
echo "[dr] backup_dir=$BACKUP_DIR"

if [[ ! -d data/n8n ]]; then
  echo "[dr] ERROR missing data/n8n"
  exit 1
fi

echo "[dr] step=wipe_simulation"
./scripts/compose_infra.sh stop n8n >/dev/null
mv data/n8n "$ORIG_DIR"
mkdir -p data/n8n

echo "[dr] step=start_blank_n8n"
./scripts/compose_infra.sh up -d n8n >/dev/null

echo "[dr] step=restore"
if ! BACKUP_DIR="$BACKUP_DIR" TIMEOUT="$RESTORE_TIMEOUT" RUN_SMOKE=true ROLLBACK_ON_FAIL=true ./scripts/n8n_red_button_restore.sh; then
  echo "[dr] restore failed -> rollback"
  rollback_original_data
  echo "DR_DRILL=FAIL"
  exit 1
fi

echo "[dr] step=post_restore_smoke"
if ! ./scripts/webhook_smoke.sh; then
  echo "[dr] smoke failed -> rollback"
  rollback_original_data
  echo "DR_DRILL=FAIL"
  exit 1
fi

echo "[dr] step=cleanup_original_snapshot"
rm -rf "$ORIG_DIR"

echo "DR_DRILL=PASS backup_dir=$BACKUP_DIR"
