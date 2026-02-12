#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-lucy_brain_n8n}"
BASE_DIR="${BASE_DIR:-./backups/n8n}"
DECRYPTED="${DECRYPTED:-false}"

TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${BASE_DIR}/${TS}"
WF_DIR="${OUT_DIR}/workflows"
CR_DIR="${OUT_DIR}/credentials"

mkdir -p "$WF_DIR" "$CR_DIR"

echo "[backup] container=$CONTAINER"
echo "[backup] out_dir=$OUT_DIR"

docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q "^${CONTAINER}$" \
  || { echo "[backup] ERROR: container '$CONTAINER' no está corriendo"; exit 1; }

# Workflows (separate files, version-friendly)
docker exec -u node "$CONTAINER" n8n export:workflow --backup --output=/tmp/workflows

docker cp "$CONTAINER":/tmp/workflows/. "$WF_DIR" >/dev/null

docker exec -u node "$CONTAINER" rm -rf /tmp/workflows

# Credentials (encrypted by default)
if [[ "$DECRYPTED" == "true" ]]; then
  docker exec -u node "$CONTAINER" n8n export:credentials --backup --decrypted --output=/tmp/credentials
else
  docker exec -u node "$CONTAINER" n8n export:credentials --backup --output=/tmp/credentials
fi

docker cp "$CONTAINER":/tmp/credentials/. "$CR_DIR" >/dev/null

docker exec -u node "$CONTAINER" rm -rf /tmp/credentials

WF_COUNT="$(find "$WF_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
CR_COUNT="$(find "$CR_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"

cat > "${OUT_DIR}/manifest.txt" <<EOF
timestamp=${TS}
container=${CONTAINER}
decrypted_credentials=${DECRYPTED}
workflows_count=${WF_COUNT}
credentials_count=${CR_COUNT}
out_dir=${OUT_DIR}
EOF

echo "[backup] OK workflows=${WF_COUNT} credentials=${CR_COUNT}"
echo "[backup] manifest=${OUT_DIR}/manifest.txt"
