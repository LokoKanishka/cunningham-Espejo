#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
OUT_DIR="${OUT_DIR:-./_tmp/contract_probe}"
mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
REQ="$OUT_DIR/request_${TS}.json"
RES_BODY="$OUT_DIR/response_${TS}.json"
RES_HEADERS="$OUT_DIR/response_${TS}.headers"

cat > "$REQ" <<'JSON'
{
  "kind": "text",
  "source": "cli",
  "ts": "__TS__",
  "text": "contract probe",
  "meta": {
    "probe": true
  }
}
JSON

python3 - <<'PY' "$REQ"
from pathlib import Path
from datetime import datetime, timezone
import sys
p=Path(sys.argv[1])
p.write_text(p.read_text().replace('__TS__', datetime.now(timezone.utc).isoformat()), encoding='utf-8')
PY

HTTP_CODE="$(curl -sS -o "$RES_BODY" -D "$RES_HEADERS" -w '%{http_code}' \
  -X POST http://127.0.0.1:5678/webhook/lucy-input \
  -H 'content-type: application/json' \
  --data-binary "@$REQ")"

echo "probe_http=$HTTP_CODE"
echo "request=$REQ"
echo "response_body=$RES_BODY"
echo "response_headers=$RES_HEADERS"
cat "$RES_BODY"
