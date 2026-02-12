#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

strict=0
if [ "${1:-}" = "--strict" ]; then
  strict=1
  shift
fi

cmd="${1:-probe}"
shift || true

probe_web_fetch() {
  out="$(openclaw agent --agent main --json --timeout 90 \
    --message 'Usa web_fetch para leer https://example.com y responde en una linea: RESULT=<ok|fail> REASON=<corto>.' \
    2>&1 || true)"

  result="$(printf "%s" "$out" | node -e '
const fs=require("fs");
const raw=fs.readFileSync(0,"utf8");
const i=raw.indexOf("{");
const j=raw.lastIndexOf("}");
if(i<0||j<=i){ console.log("PARSE_FAIL"); process.exit(0); }
try{
  const obj=JSON.parse(raw.slice(i,j+1));
  const p=Array.isArray(obj?.result?.payloads)?obj.result.payloads:(Array.isArray(obj?.payloads)?obj.payloads:[]);
  const t=p.map(x=>String(x?.text||"")).join("\n").trim().toLowerCase();
  if(t.includes("result=ok")) {
    console.log("WEB_OK");
  } else if(t.includes("enotfound")||t.includes("eai_again")||t.includes("dns")||t.includes("timed out")||t.includes("network")) {
    console.log("WEB_TOOL_OK_NET_DOWN");
  } else if(t.includes("no_tool")||t.includes("no disponible")||t.includes("not available")) {
    console.log("WEB_TOOL_MISSING");
  } else {
    console.log("WEB_UNKNOWN");
  }
}catch{ console.log("PARSE_FAIL"); }
')"

  case "$result" in
    WEB_OK|WEB_TOOL_OK_NET_DOWN)
      echo "$result"
      return 0
      ;;
    WEB_TOOL_MISSING)
      echo "$result" >&2
      return 2
      ;;
    *)
      echo "$result" >&2
      [ "$strict" -eq 1 ] && return 3 || return 0
      ;;
  esac
}

case "$cmd" in
  probe)
    probe_web_fetch
    ;;
  search)
    q="${1:-openclaw}"
    openclaw agent --agent main --json --timeout 90 \
      --message "Usa web_search con query: $q. Resume en 3 bullets." \
      2>&1
    ;;
  check)
    openclaw agent --help >/dev/null
    echo "BROWSER_VISION_TOOL_OK"
    ;;
  *)
    echo "usage: $0 [--strict] {probe|search <query>|check}" >&2
    exit 2
    ;;
esac
