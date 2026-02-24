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
  --since-days 0 \
  --max-completion-chars 0)"

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
if "files_invalid_json" not in summary:
    raise SystemExit("FAIL: missing files_invalid_json")
if "pairs_per_backend_model" not in summary:
    raise SystemExit("FAIL: missing pairs_per_backend_model")
if not isinstance(summary.get("pairs_per_backend_model"), dict):
    raise SystemExit("FAIL: pairs_per_backend_model is not an object")

dropped = summary.get("dropped", {})
if "completion_truncated" not in dropped:
    raise SystemExit("FAIL: missing dropped.completion_truncated")
if "user_overwritten" not in dropped:
    raise SystemExit("FAIL: missing dropped.user_overwritten")

lines = sum(1 for _ in out_file.open("r", encoding="utf-8"))
print("HISTORY_EXPORT_REAL_OK")
print(f"rows={summary.get('rows', 0)}")
print(f"sessions_scanned={summary.get('sessions_scanned', 0)}")
print(f"sessions_with_rows={summary.get('sessions_with_rows', 0)}")
print(f"files_invalid_json={summary.get('files_invalid_json', 0)}")
print(f"empty_dropped={summary.get('dropped', {}).get('empty_dropped', 0)}")
print(f"orphan_user_dropped={summary.get('dropped', {}).get('orphan_user_dropped', 0)}")
print(f"user_overwritten={summary.get('dropped', {}).get('user_overwritten', 0)}")
print(f"completion_truncated={summary.get('dropped', {}).get('completion_truncated', 0)}")
print(f"lines_written={lines}")
print("top_sessions=")
for item in summary.get("top_sessions", []):
    sid = item.get("session_id", "")
    rows = item.get("rows", 0)
    print(f"- {sid}: {rows}")
PY
