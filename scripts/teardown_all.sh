#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_VOLUMES="${WITH_VOLUMES:-false}"
if [[ "$WITH_VOLUMES" == "true" ]]; then
  docker compose down -v
else
  docker compose down
fi

echo "TEARDOWN=PASS"
