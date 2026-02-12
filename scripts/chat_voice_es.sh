#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

msg="${*:-Decime un resumen breve del estado del sistema.}"

raw="$(openclaw agent --agent main --json --timeout 120 --message "Respondé en castellano: $msg" 2>&1 || true)"
text="$(printf "%s" "$raw" | node -e '
const fs=require("fs");
const raw=fs.readFileSync(0,"utf8");
const i=raw.indexOf("{");
const j=raw.lastIndexOf("}");
if(i<0||j<=i){ console.log("No pude parsear respuesta."); process.exit(0); }
try{
  const o=JSON.parse(raw.slice(i,j+1));
  const p=Array.isArray(o?.result?.payloads)?o.result.payloads:(Array.isArray(o?.payloads)?o.payloads:[]);
  const t=p.map(x=>String(x?.text||"")).join("\n").trim();
  console.log(t||"(sin texto)");
}catch{ console.log("No pude parsear respuesta."); }
')"

echo "$text"

if command -v spd-say >/dev/null 2>&1; then
  spd-say -l es "$text" || true
elif command -v espeak >/dev/null 2>&1; then
  espeak -v es "$text" || true
else
  echo "TTS no disponible (instalá speech-dispatcher o espeak)." >&2
fi
