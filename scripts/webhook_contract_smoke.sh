#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p _tmp/contract_smoke
OUT="_tmp/contract_smoke"
REQ="$OUT/request.json"
RES="$OUT/response.json"

cat > "$REQ" <<'JSON'
{
  "kind": "text",
  "source": "smoke",
  "ts": "2026-02-13T00:00:00Z",
  "text": "smoke",
  "meta": {
    "suite": "contract"
  }
}
JSON

python3 scripts/contract_validate.py contracts/lucy_input_v1.schema.json "$REQ"
HTTP_CODE="000"
for i in 1 2 3 4 5; do
  HTTP_CODE="$(curl -sS -o "$RES" -w '%{http_code}' -X POST http://127.0.0.1:5678/webhook/lucy-input -H 'content-type: application/json' --data-binary "@$REQ" || true)"
  echo "contract_attempt=$i http=$HTTP_CODE"
  [[ "$HTTP_CODE" == "200" ]] && break
  sleep 1
done

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "CONTRACT_SMOKE=FAIL"
  exit 1
fi

python3 scripts/contract_validate.py contracts/lucy_output_v1.schema.json "$RES"
echo "CONTRACT_SMOKE=PASS"
