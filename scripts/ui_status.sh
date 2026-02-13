#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== dockge =="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | awk '
NR==1 { print; next }
/^lucy_ui_dockge([[:space:]]|$)/ { print }
'

echo
echo "== infra (key services) =="
./scripts/compose_infra.sh ps | awk '
NR==1 { print; next }
/lucy_brain_n8n|lucy_brain_runners|lucy_hands_antigravity|lucy_eyes_searxng|lucy_manos_runner/ { print }
'
