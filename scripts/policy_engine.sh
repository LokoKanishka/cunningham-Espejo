#!/usr/bin/env bash
set -euo pipefail

risk="${1:-show}"

case "$risk" in
  show)
    echo "policies: low, medium, high"
    ;;
  low)
    ./scripts/mode_full.sh >/dev/null
    echo "POLICY_APPLIED:low"
    ;;
  medium)
    ./scripts/mode_safe.sh >/dev/null
    echo "POLICY_APPLIED:medium"
    ;;
  high)
    ./scripts/mode_safe.sh >/dev/null
    echo "POLICY_APPLIED:high + manual approvals required"
    ;;
  check)
    [ -x ./scripts/mode_full.sh ] && [ -x ./scripts/mode_safe.sh ]
    echo "POLICY_ENGINE_OK"
    ;;
  *)
    echo "usage: $0 {show|low|medium|high|check}" >&2
    exit 2
    ;;
esac
