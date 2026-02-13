#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/apps/dockge/.env"
COMPOSE_FILE="$ROOT_DIR/apps/dockge/compose.yaml"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down

echo "DOCKGE_TEARDOWN=PASS"
