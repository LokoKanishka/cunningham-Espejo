#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

ALLOW="DOCS/allowlist_plugins.txt"
[ -f "$ALLOW" ] || { echo "FAIL: missing $ALLOW" >&2; exit 1; }

want="$(sed '/^\s*$/d' "$ALLOW" | sort -u)"

# Compare against enabled plugin entries in config (stable IDs).
enabled="$(jq -r '
  .plugins.entries
  | to_entries[]
  | select(.value.enabled == true)
  | .key
' "$HOME/.openclaw/openclaw.json" | sort -u)"

if [ "$enabled" != "$want" ]; then
  echo "FAIL: enabled plugin IDs differ from allowlist" >&2
  echo "== want ==" >&2
  printf "%s\n" "$want" >&2
  echo "== enabled ==" >&2
  printf "%s\n" "$enabled" >&2
  exit 2
fi

# Runtime check: required integrated mods must be loaded by the gateway.
list_out="$(openclaw plugins list 2>&1 || true)"
for mod in lobster llm-task open-prose; do
  case "$mod" in
    lobster) pattern='extensions/lobster/' ;;
    llm-task) pattern='extensions/llm-task/' ;;
    open-prose) pattern='extensions/open-prose/' ;;
    *) pattern="$mod" ;;
  esac
  printf "%s\n" "$list_out" | grep -qi "$pattern" || {
    echo "FAIL: required plugin '$mod' not present in plugin list output" >&2
    exit 3
  }
  # Best-effort loaded check by row snippet.
  printf "%s\n" "$list_out" | grep -Eiq "$pattern.*loaded|loaded.*$pattern" || {
    echo "FAIL: required plugin '$mod' is not loaded" >&2
    exit 3
  }
done

status="$(openclaw status 2>&1 || true)"
printf "%s\n" "$status" | grep -Eiq 'WhatsApp.*│[[:space:]]*OFF' || {
  echo "FAIL: WhatsApp channel is not OFF" >&2
  printf "%s\n" "$status" | grep -Ei 'WhatsApp' >&2 || true
  exit 4
}

echo "OK" >&2
