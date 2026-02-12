#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

cmd="${1:-help}"

case "$cmd" in
  incident)
    echo "== incident runbook =="
    ./scripts/verify_gateway.sh || true
    openclaw status || true
    openclaw security audit || true
    ;;
  recover)
    echo "== recover runbook =="
    ./scripts/gateway_autoheal.sh once || true
    ./scripts/verify_all.sh || true
    ;;
  prepush)
    echo "== prepush runbook =="
    ./scripts/diff_intel.sh report
    ./scripts/autotest_gen.sh run
    ;;
  check)
    echo "RUNBOOK_OK"
    ;;
  *)
    echo "usage: $0 {incident|recover|prepush|check}" >&2
    exit 2
    ;;
esac
