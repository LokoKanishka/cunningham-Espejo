#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_VOLUMES="${WITH_VOLUMES:-false}"
if [[ "$WITH_VOLUMES" == "true" ]]; then
  ./scripts/compose_infra.sh down -v
else
  ./scripts/compose_infra.sh down
fi

echo "TEARDOWN=PASS"
