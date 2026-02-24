#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

IN_DIR="$HOME/.openclaw/direct_chat_histories"
OUT_DIR="$HOME/.openclaw/exports"
mkdir -p "$OUT_DIR"

TMP_OUT="$OUT_DIR/.dc_pairs_verify_$$.jsonl"
trap 'rm -f "$TMP_OUT"' EXIT

summary="$(python3 scripts/export_history_jsonl.py \
  --in "$IN_DIR" \
  --out "$TMP_OUT" \
  --mode pairs \
  --min-chars 1 \
  --max-sessions 0 \
  --max-lines 0 \
  --since-days 0)"

python3 - <<'PY' "$summary" "$TMP_OUT"
import json
import sys
from pathlib import Path

summary = json.loads(sys.argv[1])
out_file = Path(sys.argv[2])

if not summary.get("ok"):
    raise SystemExit("FAIL: export returned ok=false")
if not out_file.exists():
    raise SystemExit("FAIL: verify output file missing")

lines = sum(1 for _ in out_file.open("r", encoding="utf-8"))
print("HISTORY_EXPORT_REAL_OK")
print(f"rows={summary.get('rows', 0)}")
print(f"sessions_scanned={summary.get('sessions_scanned', 0)}")
print(f"sessions_with_rows={summary.get('sessions_with_rows', 0)}")
print(f"empty_dropped={summary.get('dropped', {}).get('empty_dropped', 0)}")
print(f"orphan_user_dropped={summary.get('dropped', {}).get('orphan_user_dropped', 0)}")
print(f"lines_written={lines}")
print("top_sessions=")
for item in summary.get("top_sessions", []):
    sid = item.get("session_id", "")
    rows = item.get("rows", 0)
    print(f"- {sid}: {rows}")
PY
