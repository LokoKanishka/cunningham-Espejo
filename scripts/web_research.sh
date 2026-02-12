#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

mkdir -p DOCS/RUNS
cmd="${1:-check}"
shift || true

case "$cmd" in
  check)
    [ -x ./scripts/browser_vision.sh ]
    openclaw agent --help >/dev/null
    echo "WEB_RESEARCH_OK"
    ;;
  run)
    q="${*:-openclaw plugins security best practices}"
    ts="$(date +%Y%m%d_%H%M%S)"
    out="DOCS/RUNS/web_research_${ts}.md"
    raw="$(openclaw agent --agent main --json --timeout 120 \
      --message "Usa web_search para buscar: $q. Luego usa web_fetch en 2 resultados y devolve un resumen breve con fuentes en markdown." \
      2>&1 || true)"

    text="$(printf "%s" "$raw" | node -e '
const fs=require("fs");
const raw=fs.readFileSync(0,"utf8");
const i=raw.indexOf("{"); const j=raw.lastIndexOf("}");
if(i<0||j<=i){ console.log("PARSE_FAIL"); process.exit(0); }
try{
  const o=JSON.parse(raw.slice(i,j+1));
  const p=Array.isArray(o?.result?.payloads)?o.result.payloads:(Array.isArray(o?.payloads)?o.payloads:[]);
  console.log(p.map(x=>String(x?.text||"")).join("\n").trim() || "EMPTY");
}catch{ console.log("PARSE_FAIL"); }
')"

    {
      echo "# Web Research"
      echo
      echo "Query: $q"
      echo "Generated: $(date -Is)"
      echo
      echo "$text"
    } > "$out"

    echo "WEB_RESEARCH_OUT:$out"
    ;;
  *)
    echo "usage: $0 {check|run <query...>}" >&2
    exit 2
    ;;
esac
