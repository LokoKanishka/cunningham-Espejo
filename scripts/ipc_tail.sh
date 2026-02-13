#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-./ipc/inbox}"
[[ -d "$BASE" ]] || { echo "missing dir: $BASE"; exit 1; }

echo "Watching: $BASE"
while true; do
  ls -1t "$BASE"/*.json 2>/dev/null | head -n 5
  sleep 1
  clear
done
