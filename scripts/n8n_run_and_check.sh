#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DB_PATH:-data/n8n/database.sqlite}"
WEBHOOK_URL="${WEBHOOK_URL:-http://127.0.0.1:5678/webhook/test-manos}"
WORKFLOW_ID="${WORKFLOW_ID:-Hrz7BjjUW5dkKfJA}"
METHOD="${METHOD:-GET}"
PAYLOAD="${PAYLOAD:-}"
CONTENT_TYPE="${CONTENT_TYPE:-application/json}"
TIMEOUT_S="${TIMEOUT_S:-30}"
export DB_PATH WORKFLOW_ID TIMEOUT_S

[[ -f "$DB_PATH" ]] || { echo "ERROR db not found: $DB_PATH"; exit 1; }

LAST_BEFORE="$(python3 - <<'PY'
import os, sqlite3
con=sqlite3.connect(os.environ['DB_PATH']); con.row_factory=sqlite3.Row
row=con.execute("SELECT COALESCE(MAX(id),0) AS id FROM execution_entity WHERE workflowId=?", (os.environ['WORKFLOW_ID'],)).fetchone()
print(row['id'])
PY
)"
export LAST_BEFORE

curl_args=(-sS -o /dev/null -w '%{http_code}' -X "$METHOD" "$WEBHOOK_URL")
if [[ "$METHOD" != "GET" ]]; then
  curl_args+=( -H "content-type: ${CONTENT_TYPE}" )
  if [[ -n "$PAYLOAD" ]]; then
    curl_args+=( --data "$PAYLOAD" )
  fi
fi
http_code="$(curl "${curl_args[@]}")"
echo "trigger_http=$http_code url=$WEBHOOK_URL method=$METHOD"

python3 - <<'PY'
import json, os, sqlite3, sys, time

DB_PATH=os.environ['DB_PATH']
WORKFLOW_ID=os.environ['WORKFLOW_ID']
LAST_BEFORE=int(os.environ['LAST_BEFORE'])
TIMEOUT_S=int(os.environ['TIMEOUT_S'])

con=sqlite3.connect(DB_PATH)
con.row_factory=sqlite3.Row

def resolve_graph(v, pool, depth=0):
    if depth > 1000:
        return v
    if isinstance(v, str) and v.isdigit():
        idx=int(v)
        if 0 <= idx < len(pool):
            return resolve_graph(pool[idx], pool, depth + 1)
        return v
    if isinstance(v, list):
        return [resolve_graph(x, pool, depth + 1) for x in v]
    if isinstance(v, dict):
        return {k: resolve_graph(val, pool, depth + 1) for k, val in v.items()}
    return v

def extract_errors(raw):
    if not raw:
        return None, []
    try:
        parsed=json.loads(raw)
    except Exception as ex:
        return f'JSON_PARSE_ERROR: {ex}', []

    root=parsed
    if isinstance(parsed, list) and parsed:
        root=resolve_graph(parsed[0], parsed)

    if not isinstance(root, dict):
        return None, []

    rd=root.get('resultData')
    if isinstance(rd, list):
        rd=resolve_graph(rd, rd)
    if not isinstance(rd, dict):
        return None, []

    result_error=rd.get('error')
    run_data=rd.get('runData')
    node_errors=[]
    if isinstance(run_data, dict):
        for node, runs in run_data.items():
            if not isinstance(runs, list):
                continue
            for r in runs:
                if not isinstance(r, dict):
                    continue
                err=r.get('error')
                if isinstance(err, dict):
                    msg=err.get('message') or str(err)
                elif isinstance(err, str):
                    msg=err
                else:
                    msg=None
                if msg:
                    node_errors.append((node, msg))
    return result_error, node_errors

start=time.time()
row=None
while time.time()-start < TIMEOUT_S:
    row=con.execute(
        """
        SELECT id, workflowId, status, mode, startedAt, stoppedAt
        FROM execution_entity
        WHERE workflowId=? AND id>?
        ORDER BY id ASC
        LIMIT 1
        """,
        (WORKFLOW_ID, LAST_BEFORE),
    ).fetchone()
    if row and row['status'] != 'running':
        break
    time.sleep(0.5)

if not row:
    print('ERROR timeout waiting execution row')
    sys.exit(2)

if row['status'] == 'running':
    waited=time.time()-start
    while waited < TIMEOUT_S:
        latest=con.execute('SELECT id,status,mode,startedAt,stoppedAt FROM execution_entity WHERE id=?', (row['id'],)).fetchone()
        row=latest
        if row['status'] != 'running':
            break
        time.sleep(0.5)
        waited=time.time()-start

edata=con.execute('SELECT data FROM execution_data WHERE executionId=?', (row['id'],)).fetchone()
result_error, node_errors = extract_errors(edata['data'] if edata else None)

print(f"exec_id={row['id']} workflowId={WORKFLOW_ID} status={row['status']} mode={row['mode']}")
print(f"result_error={result_error}")
print(f"node_errors={node_errors[:10]}")

if row['status'] != 'success':
    sys.exit(3)
PY
