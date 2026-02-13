#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DB_PATH:-data/n8n/database.sqlite}"
WORKFLOW_NAME="${WORKFLOW_NAME:-Test_Manos}"
URL_MODE="${URL_MODE:-hardcoded}" # hardcoded | env
ANTIGRAVITY_TARGET_URL="${ANTIGRAVITY_TARGET_URL:-http://127.0.0.1:5000/execute}"
export DB_PATH WORKFLOW_NAME URL_MODE ANTIGRAVITY_TARGET_URL

python3 - <<'PY'
import json
import os
import sqlite3
from pathlib import Path

p=Path(os.environ['DB_PATH'])
name=os.environ['WORKFLOW_NAME']
con=sqlite3.connect(str(p))
con.row_factory=sqlite3.Row
row=con.execute('SELECT id,nodes FROM workflow_entity WHERE name=? ORDER BY updatedAt DESC LIMIT 1',(name,)).fetchone()
if not row:
    raise SystemExit(f'workflow not found: {name}')

nodes=json.loads(row['nodes'])
changed=0
if os.environ['URL_MODE'] == 'env':
    target_url='={{$env.ANTIGRAVITY_URL}}/execute'
else:
    target_url=os.environ['ANTIGRAVITY_TARGET_URL']
for n in nodes:
    if n.get('type')!='n8n-nodes-base.httpRequest':
        continue
    params=n.get('parameters') or {}
    url=params.get('url')
    if isinstance(url,str) and ('127.0.0.1:5000/execute' in url or 'antigravity' in url.lower() or '{{$env.ANTIGRAVITY_URL}}' in url):
        params['url']=target_url
        n['parameters']=params
        changed+=1

if not changed:
    print('NO_CHANGE')
    raise SystemExit(0)

con.execute('UPDATE workflow_entity SET nodes=?, updatedAt=CURRENT_TIMESTAMP WHERE id=?',(json.dumps(nodes,ensure_ascii=False,separators=(",",":")),row['id']))
con.commit()
print(f'UPDATED workflow_id={row["id"]} changed_nodes={changed}')
PY
