#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

if [ "${1:-}" = "check" ]; then
  openclaw plugins list | grep -qi 'extensions/lobster/' || { echo "LOBSTER_PLUGIN_MISSING" >&2; exit 1; }
  echo "LOBSTER_APPROVAL_OK"
  exit 0
fi

token="${1:-}"
decision="${2:-yes}"
if [ -z "$token" ]; then
  echo "usage: $0 <resume-token> [yes|no]" >&2
  echo "       $0 check" >&2
  exit 2
fi
if [ "$decision" != "yes" ] && [ "$decision" != "no" ]; then
  echo "decision must be yes|no" >&2
  exit 2
fi

openclaw agent --agent main --json --timeout 120 \
  --message "Usa lobster con action='resume', token='$token', approve='$decision'. Devuelve SOLO JSON." \
  2>&1
