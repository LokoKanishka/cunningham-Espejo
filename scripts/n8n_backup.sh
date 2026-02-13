#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-lucy_brain_n8n}"
BASE_DIR="${BASE_DIR:-./backups/n8n}"
DECRYPTED="${DECRYPTED:-false}"
RETAIN="${RETAIN:-14}"

TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${BASE_DIR}/${TS}"
WF_DIR="${OUT_DIR}/workflows"
CR_DIR="${OUT_DIR}/credentials"

mkdir -p "$WF_DIR" "$CR_DIR"

echo "[backup] container=$CONTAINER"
echo "[backup] out_dir=$OUT_DIR"
echo "[backup] retain=$RETAIN"

docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q "^${CONTAINER}$" \
  || { echo "[backup] ERROR: container '$CONTAINER' no está corriendo"; exit 1; }

docker exec -u node "$CONTAINER" sh -lc 'rm -rf /tmp/workflows && mkdir -p /tmp/workflows'
docker exec -u node "$CONTAINER" n8n export:workflow --backup --output=/tmp/workflows >/dev/null || true
docker cp "$CONTAINER":/tmp/workflows/. "$WF_DIR" >/dev/null || true
docker exec -u node "$CONTAINER" rm -rf /tmp/workflows

docker exec -u node "$CONTAINER" sh -lc 'rm -rf /tmp/credentials && mkdir -p /tmp/credentials'
if [[ "$DECRYPTED" == "true" ]]; then
  docker exec -u node "$CONTAINER" n8n export:credentials --backup --decrypted --output=/tmp/credentials >/dev/null || true
else
  docker exec -u node "$CONTAINER" n8n export:credentials --backup --output=/tmp/credentials >/dev/null || true
fi
docker cp "$CONTAINER":/tmp/credentials/. "$CR_DIR" >/dev/null || true
docker exec -u node "$CONTAINER" rm -rf /tmp/credentials

WF_COUNT="$(find "$WF_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
CR_COUNT="$(find "$CR_DIR" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"

CHECKSUM_FILE="${OUT_DIR}/checksums.sha256"
find "$OUT_DIR" -type f -name '*.json' -print0 | sort -z | xargs -0 sha256sum > "$CHECKSUM_FILE"
CHECKSUM_COUNT="$(wc -l < "$CHECKSUM_FILE" | tr -d ' ')"

cat > "${OUT_DIR}/manifest.txt" <<EOF
timestamp=${TS}
container=${CONTAINER}
decrypted_credentials=${DECRYPTED}
retain=${RETAIN}
workflows_count=${WF_COUNT}
credentials_count=${CR_COUNT}
checksums_file=${CHECKSUM_FILE}
checksums_count=${CHECKSUM_COUNT}
out_dir=${OUT_DIR}
EOF

if [[ "$RETAIN" =~ ^[0-9]+$ ]] && (( RETAIN > 0 )); then
  mapfile -t existing < <(find "$BASE_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | rg '^[0-9]{8}_[0-9]{6}$' | sort)
  total="${#existing[@]}"
  if (( total > RETAIN )); then
    remove_n=$((total - RETAIN))
    for d in "${existing[@]:0:remove_n}"; do
      rm -rf "$BASE_DIR/$d"
      echo "[backup] rotated_out=$BASE_DIR/$d"
    done
  fi
fi

echo "[backup] OK workflows=${WF_COUNT} credentials=${CR_COUNT} checksums=${CHECKSUM_COUNT}"
echo "[backup] manifest=${OUT_DIR}/manifest.txt"
