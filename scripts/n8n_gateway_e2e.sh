#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p _tmp/gateway_e2e

for attempt in 1 2 3 4 5; do
  REQ="_tmp/gateway_e2e/request_${attempt}.json"
  RES="_tmp/gateway_e2e/response_${attempt}.json"

  CORR="cid_e2e_$(date +%s)_$attempt"
  TS="$(date --iso-8601=seconds)"

  cat > "$REQ" <<JSON
{
  "kind": "text",
  "source": "e2e",
  "ts": "$TS",
  "text": "e2e gateway",
  "meta": {"suite": "gateway_e2e", "attempt": $attempt},
  "correlation_id": "$CORR"
}
JSON

  HTTP_CODE="$(curl -sS -o "$RES" -w '%{http_code}' -X POST http://127.0.0.1:5678/webhook/lucy-input -H 'content-type: application/json' --data-binary "@$REQ")"
  echo "e2e_attempt=$attempt http=$HTTP_CODE"
  if [[ "$HTTP_CODE" != "200" ]]; then
    sleep 1
    continue
  fi

  if ! python3 scripts/contract_validate.py contracts/lucy_output_v1.schema.json "$RES" >/dev/null; then
    sleep 1
    continue
  fi

  if python3 - <<'PY' "$RES"
import json
import time
import subprocess
import sys
from pathlib import Path

res=json.loads(Path(sys.argv[1]).read_text())
cid=res['correlation_id']
candidates = [
    ('ipc/inbox', '/data/lucy_ipc/inbox'),
    ('ipc/payloads', '/data/lucy_ipc/payloads'),
]

env=None
for _ in range(30):
    for host_base, container_base in candidates:
        host_path = Path(host_base) / f'{cid}.json'
        cpath = f'{container_base}/{cid}.json'
        if host_path.exists():
            env=json.loads(host_path.read_text())
            break
        out=subprocess.run(
            ['docker','exec','lucy_brain_n8n','sh','-lc',f'test -f {cpath} && cat {cpath}'],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            env=json.loads(out.stdout)
            break
    if env is not None:
        break
    time.sleep(0.2)

if env is None:
    raise SystemExit(1)
if env.get('correlation_id') != cid:
    raise SystemExit(1)
print(f'GATEWAY_E2E=PASS correlation_id={cid}')
PY
  then
    exit 0
  fi

  sleep 1
done

echo "GATEWAY_E2E=FAIL"
exit 1
