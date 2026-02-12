#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

dry=0
if [ "${1:-}" = "--dry-run" ]; then
  dry=1
fi

ws="$HOME/.openclaw/workspace"
out="$ws/KNOWLEDGE_LOCAL.md"
mkdir -p "$ws"

{
  echo "# Local Knowledge Snapshot"
  echo
  echo "Generated: $(date -Is)"
  echo
  for f in README.md DOCS/PLAN.md DOCS/PLUGINS.md DOCS/CAPABILITIES.md DOCS/LOBSTER.md docs/INTEGRATIONS.md; do
    if [ -f "$f" ]; then
      echo "## Source: $f"
      sed -n '1,220p' "$f"
      echo
    fi
  done
} > "$out"

echo "KNOWLEDGE_FILE=$out"

if [ "$dry" -eq 1 ]; then
  echo "DRY_RUN"
  exit 0
fi

openclaw memory index --agent main || true
openclaw memory status --agent main || true
