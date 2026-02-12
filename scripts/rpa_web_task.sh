#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

cmd="${1:-check}"
url="${2:-https://example.com}"

case "$cmd" in
  check)
    openclaw browser status --json >/dev/null 2>&1 || true
    echo "RPA_BROWSER_CHECK_OK"
    ;;
  run)
    openclaw browser start --json >/dev/null
    openclaw browser open "$url" --json >/dev/null
    openclaw browser snapshot --format ai --limit 120 --json
    ;;
  *)
    echo "usage: $0 {check|run [url]}" >&2
    exit 2
    ;;
esac
