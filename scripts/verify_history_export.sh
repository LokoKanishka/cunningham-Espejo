#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

in_dir="$tmp_dir/in"
out_file="$tmp_dir/out/dc_pairs.jsonl"
mkdir -p "$in_dir" "$tmp_dir/out"

cat > "$in_dir/sessionA__cloud__demo-model.json" <<'JSON'
[
  {"role":"user","content":"Hola dataset"},
  {"role":"assistant","content":"   "},
  {"role":"assistant","content":"Respuesta válida"},
  {"role":"user","content":"Segundo prompt"},
  {"role":"assistant","content":""},
  {"role":"assistant","content":"Segunda respuesta"}
]
JSON

python3 scripts/export_history_jsonl.py \
  --in "$in_dir" \
  --out "$out_file" \
  --mode pairs \
  --min-chars 1 \
  --max-sessions 0 >/dev/null

python3 - <<'PY' "$out_file"
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
if not p.exists():
    raise SystemExit("FAIL: output file not created")

lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
if len(lines) < 1:
    raise SystemExit("FAIL: output has no lines")

for idx, line in enumerate(lines, 1):
    obj = json.loads(line)
    completion = str(obj.get("completion", ""))
    if not completion.strip():
        raise SystemExit(f"FAIL: empty completion at line {idx}")

print(f"HISTORY_EXPORT_OK lines={len(lines)}")
PY
