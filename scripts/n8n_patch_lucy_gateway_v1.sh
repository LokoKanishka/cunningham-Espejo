#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
CONTAINER="${CONTAINER:-lucy_brain_n8n}"
WORKFLOW_ID="${WORKFLOW_ID:-SnRyEoRbJuDC-5PBLt8os}"
TMP_DIR="${TMP_DIR:-./_tmp/lucy_gateway_patch}"

mkdir -p "$TMP_DIR"
SRC="$TMP_DIR/workflow_src.json"
PATCHED="$TMP_DIR/workflow_patched.json"

docker exec -u node "$CONTAINER" n8n export:workflow --id "$WORKFLOW_ID" --output /tmp/lucy_gateway_src.json >/dev/null
docker cp "$CONTAINER":/tmp/lucy_gateway_src.json "$SRC" >/dev/null

python3 tools/patch_lucy_gateway_v1.py "$SRC" "$PATCHED"

docker cp "$PATCHED" "$CONTAINER":/tmp/lucy_gateway_patched.json >/dev/null
docker exec -u node "$CONTAINER" n8n import:workflow --input=/tmp/lucy_gateway_patched.json >/dev/null
docker exec -u node "$CONTAINER" n8n update:workflow --id="$WORKFLOW_ID" --active=true >/dev/null
docker exec -u node "$CONTAINER" n8n publish:workflow --id="$WORKFLOW_ID" >/dev/null
./scripts/compose_infra.sh restart n8n >/dev/null

echo "PATCH_APPLIED workflow_id=$WORKFLOW_ID"
