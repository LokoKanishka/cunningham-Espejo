#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

cmd="${1:-status}"
shift || true

case "$cmd" in
  status)
    openclaw memory status --agent main "$@"
    ;;
  index)
    openclaw memory index --agent main "$@"
    ;;
  search)
    q="${1:-}"
    if [ -z "$q" ]; then
      echo "usage: $0 search <query>" >&2
      exit 2
    fi
    shift || true
    openclaw memory search --agent main "$q" "$@"
    ;;
  check)
    openclaw memory --help >/dev/null
    echo "MEMORY_TOOL_OK"
    ;;
  *)
    echo "usage: $0 {status|index|search <query>|check}" >&2
    exit 2
    ;;
esac
