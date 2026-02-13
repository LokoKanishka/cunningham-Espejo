#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="${OUT_DIR:-./_stress/metrics_snapshots}"
URL="${URL:-http://127.0.0.1:5678/metrics}"
mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="$OUT_DIR/metrics_${TS}.txt"

curl -sS "$URL" > "$OUT_FILE"

echo "metrics_file=$OUT_FILE"
echo "== key lines =="
rg -n "(process_resident_memory_bytes|process_cpu_user_seconds_total|n8n|workflow|execution|error)" "$OUT_FILE" | head -n 10 || true
