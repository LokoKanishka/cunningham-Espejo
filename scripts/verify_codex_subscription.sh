#!/usr/bin/env bash
set -euo pipefail
is_google_auth_fail() {
  grep -q 'No API key found for provider "google"' || grep -q 'FailoverError: No API key found for provider "google"'
}

export PATH="$HOME/.openclaw/bin:$PATH"
MODEL="openai-codex/gpt-5.1-codex-mini"
EXPECT_MODEL_SUB="gpt-5.1-codex-mini"

echo "== openclaw version ==" >&2
openclaw --version >&2

echo "== models status (key lines) ==" >&2
openclaw models status >&2 || true

# Fuerza la sesión actual del agente main a Codex (no importa si no devuelve JSON)
echo "== force session model (/new) ==" >&2
openclaw agent --agent main --message "/new $MODEL" --timeout 120 >/dev/null 2>&1 || true

echo "== smoke agent (--json) ==" >&2
out="$(openclaw agent --agent main --message "Respondé EXACTAMENTE con: OK" --json --timeout 120 2>&1 || true)"

# Auth guard: skip when Google key is missing
if printf "%s" "${out}" | is_google_auth_fail; then
  echo "SKIP_AUTH google_missing_key (verify_codex_subscription)" >&2
  exit 0
fi


# Parse robusto desde stdin: busca el JSON dentro de cualquier ruido (warnings, etc.)
printf "%s" "$out" | EXPECT_MODEL_SUB="$EXPECT_MODEL_SUB" node -e '
const fs=require("fs");
const out=fs.readFileSync(0,"utf8");
const i=out.indexOf("{");
const j=out.lastIndexOf("}");
if(i<0||j<=i){
  console.error("FAIL: no JSON object found in output");
  console.error(out.slice(0,1600));
  process.exit(1);
}
const jsonStr=out.slice(i,j+1);

let data;
try{ data=JSON.parse(jsonStr); }
catch(e){
  console.error("FAIL: JSON parse");
  console.error(String(e));
  console.error(jsonStr.slice(0,1600));
  process.exit(1);
}

const metaContainer = data?.result?.meta ?? data?.meta ?? {};
const meta=metaContainer?.agentMeta ?? {};
const provider=String(meta.provider||"");
const model=String(meta.model||"");
const payloads=Array.isArray(data?.result?.payloads)
  ? data.result.payloads
  : (Array.isArray(data?.payloads) ? data.payloads : []);
const allText=payloads.map(p=>String(p?.text??"")).join("\n").trim();
const expSub=String(process.env.EXPECT_MODEL_SUB||"");

console.error(`provider=${provider}`);
console.error(`model=${model}`);
if(payloads.length) console.error(`text0=${String(payloads[0].text??"").trim()}`);

if(!provider.toLowerCase().includes("codex")){
  console.error("FAIL: expected provider to include codex");
  process.exit(2);
}
if(expSub && !model.includes(expSub)){
  console.error(`FAIL: expected model to include ${expSub}`);
  process.exit(3);
}
if(allText !== "OK"){
  console.error(`FAIL: expected text exactly OK (got ${allText})`);
  process.exit(4);
}
console.error("OK");
'

echo "OK" >&2
