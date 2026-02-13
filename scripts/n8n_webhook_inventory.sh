#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-./_tmp}"
CONTAINER="${CONTAINER:-lucy_brain_n8n}"
STRICT_CONFLICTS="${STRICT_CONFLICTS:-false}"
mkdir -p "$OUT_DIR"

EXPORT_FILE="$OUT_DIR/workflows_export.json"
docker exec -u node "$CONTAINER" n8n export:workflow --all --output /tmp/workflows_export.json >/dev/null
docker cp "$CONTAINER":/tmp/workflows_export.json "$EXPORT_FILE" >/dev/null
export EXPORT_FILE STRICT_CONFLICTS

python3 - <<'PY'
import json
import os
from collections import defaultdict
from pathlib import Path

p=Path(os.environ['EXPORT_FILE'])
text=p.read_text(encoding='utf-8', errors='replace')
obj=json.loads(text)
workflows=obj['workflows'] if isinstance(obj,dict) and 'workflows' in obj else obj

rows=[]
for w in workflows:
    wid=w.get('id')
    name=w.get('name')
    active=bool(w.get('active'))
    for n in w.get('nodes') or []:
        t=(n.get('type') or '').lower()
        if 'webhook' not in t and 'trigger' not in t:
            continue
        params=n.get('parameters') or {}
        path=params.get('path') or params.get('webhookPath') or ''
        method=(params.get('httpMethod') or params.get('method') or '').upper()
        if path:
            rows.append((path, method, active, wid, name, n.get('name')))

print(f'workflows={len(workflows)} triggers={len(rows)}')
for path, method, active, wid, name, node in sorted(rows):
    print(f'- path={path} method={method or "N/A"} active={active} workflow={name} ({wid}) node={node}')

by_path=defaultdict(list)
for r in rows:
    by_path[(r[0], r[1])].append(r)

active_conflicts=[]
for key, vals in by_path.items():
    active_vals=[v for v in vals if v[2]]
    if len(active_vals) > 1:
        active_conflicts.append((key, active_vals))

strict = os.environ.get('STRICT_CONFLICTS', 'false').lower() == 'true'
if active_conflicts:
    print('ACTIVE_CONFLICTS=YES')
    for (path, method), vals in active_conflicts:
        names=', '.join(f'{v[4]}({v[3]})' for v in vals)
        print(f'  conflict path={path} method={method} active={names}')
    if strict:
        raise SystemExit(1)
else:
    print('ACTIVE_CONFLICTS=NO')
PY
