#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/apps/dockge/.env"
COMPOSE_FILE="$ROOT_DIR/apps/dockge/compose.yaml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "DOCKGE_BRINGUP=FAIL missing_env=$ENV_FILE" >&2
  exit 1
fi

WORKSPACE_DIR="$(sed -n 's/^WORKSPACE_DIR=//p' "$ENV_FILE" | head -n 1)"
if [[ -z "$WORKSPACE_DIR" || "$WORKSPACE_DIR" != /* ]]; then
  echo "DOCKGE_BRINGUP=FAIL invalid_WORKSPACE_DIR=$WORKSPACE_DIR" >&2
  exit 1
fi
if [[ ! -d "$WORKSPACE_DIR" ]]; then
  echo "DOCKGE_BRINGUP=FAIL missing_workspace_dir=$WORKSPACE_DIR" >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

echo "DOCKGE_BRINGUP=PASS"
