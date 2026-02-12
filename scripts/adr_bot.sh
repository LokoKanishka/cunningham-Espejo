#!/usr/bin/env bash
set -euo pipefail

store="DOCS/DECISIONS.md"
mkdir -p DOCS

cmd="${1:-list}"
shift || true

init_store() {
  if [ ! -f "$store" ]; then
    cat > "$store" <<'MD'
# Decisions

MD
  fi
}

case "$cmd" in
  add)
    title="${1:-}"
    decision="${2:-}"
    rationale="${3:-}"
    [ -n "$title" ] && [ -n "$decision" ] && [ -n "$rationale" ] || {
      echo "usage: $0 add <title> <decision> <rationale>" >&2
      exit 2
    }
    init_store
    {
      echo "## $(date '+%F %T') - $title"
      echo "- Decision: $decision"
      echo "- Rationale: $rationale"
      echo
    } >> "$store"
    echo "ADR_ADDED"
    ;;
  list)
    init_store
    sed -n '1,240p' "$store"
    ;;
  search)
    q="${1:-}"
    [ -n "$q" ] || { echo "usage: $0 search <term>" >&2; exit 2; }
    init_store
    grep -ni "$q" "$store" || true
    ;;
  check)
    init_store
    echo "ADR_BOT_OK"
    ;;
  *)
    echo "usage: $0 {add|list|search|check}" >&2
    exit 2
    ;;
esac
