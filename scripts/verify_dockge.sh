#!/usr/bin/env bash
set -euo pipefail

FAIL=0

if curl -fsS http://127.0.0.1:5001/ >/dev/null; then
  echo "DOCKGE_HTTP=PASS"
else
  echo "DOCKGE_HTTP=FAIL"
  FAIL=1
fi

if ss -lntp | grep ':5001' | grep -q '127.0.0.1'; then
  echo "DOCKGE_BIND=PASS"
else
  echo "DOCKGE_BIND=FAIL"
  FAIL=1
fi

if docker ps --format '{{.Names}}' | grep -q '^lucy_ui_dockge$'; then
  echo "DOCKGE_CONTAINER=PASS"
else
  echo "DOCKGE_CONTAINER=FAIL"
  FAIL=1
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "DOCKGE_VERIFY=PASS"
else
  echo "DOCKGE_VERIFY=FAIL"
  exit 1
fi
