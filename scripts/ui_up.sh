#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
./scripts/bringup_dockge.sh

echo "UI_URL=http://127.0.0.1:5001"
