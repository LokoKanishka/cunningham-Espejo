#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.openclaw/bin:$PATH"

echo "== openclaw security audit ==" >&2
out="$(openclaw security audit 2>&1 || true)"
echo "$out" >&2

if ! echo "$out" | grep -qE 'Summary:\s*0 critical'; then
  echo "FAIL: security audit is not 0 critical" >&2
  exit 1
fi

echo "OK" >&2
