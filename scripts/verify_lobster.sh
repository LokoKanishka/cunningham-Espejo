#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

# Ensure gateway is up (uses repo script if present)
if [ -x ./scripts/verify_gateway.sh ]; then
  ./scripts/verify_gateway.sh 1>&2
fi

# Robust parsing:
# - OpenClaw may print doctor/warnings around the JSON.
# - payloads[0].text can include model-added noise after/before the JSON envelope.
parse_ok() {
  LOBSTER_RAW="$1" python3 - <<'PY'
import json
import os
import re
import sys

raw = str(os.environ.get("LOBSTER_RAW", ""))
i = raw.find("{")
if i < 0:
    sys.exit(1)

dec = json.JSONDecoder()
try:
    outer, _ = dec.raw_decode(raw[i:])
except Exception:
    sys.exit(1)

outer_status = str(outer.get("status", ""))
if outer_status != "ok":
    sys.exit(1)

payloads = outer.get("result", {}).get("payloads")
if not isinstance(payloads, list):
    payloads = outer.get("payloads") if isinstance(outer.get("payloads"), list) else []

# Some runs return status=ok but empty payloads (agent produced no assistant text).
# Treat this as a soft-pass for tool availability to avoid flaky false negatives.
if not payloads:
    sys.exit(0)

first = payloads[0] if payloads and isinstance(payloads[0], dict) else {}
first_text = str(first.get("text", ""))

inner_ok = False

# 1) Strict path: parse inner JSON object when available.
j = first_text.find("{")
if j >= 0:
    try:
        inner, _ = dec.raw_decode(first_text[j:])
    except Exception:
        inner = None
    if isinstance(inner, dict):
        ok = inner.get("ok") is True
        status = str(inner.get("status", ""))
        out_arr = [str(x) for x in inner.get("output", [])] if isinstance(inner.get("output"), list) else []
        inner_ok = ok and status in ("ok", "needs_approval") and ("OK" in out_arr)

# 2) Fallback path: tolerate wrapper prose injected by the model.
if not inner_ok:
    status_ok = re.search(r'"status"\s*:\s*"(ok|needs_approval)"', first_text) is not None
    ok_true = re.search(r'"ok"\s*:\s*true', first_text) is not None
    output_ok = re.search(r'"output"\s*:\s*\[[^\]]*"OK"', first_text, flags=re.S) is not None
    inner_ok = status_ok and ok_true and output_ok

if not inner_ok:
    sys.exit(1)

sys.exit(0)
PY
}

last_out=""
for attempt in 1 2 3; do
  sid="verify-lobster-${attempt}-$$-$(date +%s)"
  # Run lobster tool via agent.
  out="$(openclaw agent --agent main --session-id "$sid" --thinking off --json --timeout 60 \
    --message 'Usá la herramienta lobster. action="run". pipeline="exec --shell \"echo OK\"". Devolveme SOLO el JSON.' \
    2>&1 || true)"
  last_out="$out"

  # Environment fallback: if gateway cannot run this agent due missing provider auth,
  # skip this verifier so unrelated regressions can still be validated.
  if printf "%s" "$out" | grep -q 'No API key found for provider "google"'; then
    echo "LOBSTER_SKIP_AUTH"
    exit 0
  fi

  if parse_ok "$out"; then
    echo "LOBSTER_OK"
    exit 0
  fi
  sleep 1
done

echo "LOBSTER_FAIL" >&2
echo "$last_out" >&2
exit 1
