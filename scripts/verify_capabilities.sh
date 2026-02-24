#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

is_google_auth_fail() {
  grep -q 'No API key found for provider "google"' || grep -q 'FailoverError: No API key found for provider "google"'
}

extract_payload_text() {
  # Read stdout, parse the JSON payload even if warnings/ANSI noise appear before it.
  python3 -c '
import sys, json, re
raw = sys.stdin.read()
clean = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw)
dec = json.JSONDecoder()
best = None
for i, ch in enumerate(clean):
    if ch != "{":
        continue
    try:
        outer, _ = dec.raw_decode(clean[i:])
    except Exception:
        continue
    if not isinstance(outer, dict):
        continue
    payloads = outer.get("result", {}).get("payloads")
    if not isinstance(payloads, list):
        payloads = outer.get("payloads") if isinstance(outer.get("payloads"), list) else []
    texts = []
    for p in payloads:
        if isinstance(p, dict):
            texts.append(str(p.get("text", "")))
    if texts:
        best = "\n".join(texts).strip()
if best is None:
    print("__NO_JSON_PAYLOAD__", file=sys.stderr)
    sys.exit(2)
print(best)
'
}

echo "== capability: desktop via exec ==" >&2
out_desktop="$(openclaw agent --agent main --json --timeout 120 \
  --message 'Usá la herramienta exec para listar el escritorio con: ls -1 ~/Escritorio | head -n 20. Respondé EXACTAMENTE con DESKTOP_OK si ves la carpeta cunningham; si no, DESKTOP_FAIL.' \
  2>&1 || true)"

if printf "%s" "$out_desktop" | is_google_auth_fail; then
  echo "DESKTOP_SKIP_AUTH google_missing_key" >&2
else
  txt="$(printf "%s" "$out_desktop" | extract_payload_text 2>/tmp/_cap_desktop_parse.err || true)"
  if ! printf "%s" "$txt" | grep -Eq '\bDESKTOP_OK\b'; then
    echo "FAIL: desktop expected DESKTOP_OK" >&2
    echo "$txt" >&2
    echo "RAW:" >&2
    echo "$out_desktop" >&2
    exit 1
  fi
  echo "DESKTOP_OK" >&2
fi

echo "== capability: web via web_fetch ==" >&2
out_web="$(openclaw agent --agent main --json --timeout 120 \
  --message 'Usá la herramienta web_fetch para leer https://example.com y devolvé en una sola línea: RESULT=<ok|fail> REASON=<motivo corto>. Si no tenés la tool, devolvé RESULT=fail REASON=no_tool.' \
  2>&1 || true)"

if printf "%s" "$out_web" | is_google_auth_fail; then
  echo "WEB_SKIP_AUTH google_missing_key" >&2
else
  txt="$(printf "%s" "$out_web" | extract_payload_text 2>/tmp/_cap_web_parse.err || true)"
  low="$(printf "%s" "$txt" | tr '[:upper:]' '[:lower:]')"
  if printf "%s" "$low" | grep -q "result=ok"; then
    echo "WEB_OK" >&2
  elif printf "%s" "$low" | grep -Eq "no_tool|no disponible|not available"; then
    echo "FAIL: web tool unavailable" >&2
    echo "$txt" >&2
    exit 1
  elif printf "%s" "$low" | grep -Eq "enotfound|eai_again|timed out|network|dns"; then
    echo "WEB_TOOL_OK_NETWORK_UNAVAILABLE" >&2
  else
    echo "FAIL: unexpected web result" >&2
    echo "$txt" >&2
    echo "RAW:" >&2
    echo "$out_web" >&2
    exit 1
  fi
fi

echo "CAPABILITIES_OK" >&2
