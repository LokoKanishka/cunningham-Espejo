#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

mkdir -p DOCS/RUNS
ts="$(date +%Y%m%d_%H%M%S)"
out="DOCS/RUNS/ops_${ts}.log"

{
  echo "== ts =="
  date -Is
  echo "== health =="
  openclaw health || true
  echo "== status =="
  openclaw status || true
  echo "== sessions (json) =="
  openclaw sessions --json || true
  echo "== logs tail =="
  openclaw logs --plain --limit 80 || true
} >"$out" 2>&1

echo "OPS_LOG=$out"
