#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
./scripts/teardown_dockge.sh
