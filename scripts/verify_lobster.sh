#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

# Ensure gateway is up (uses repo script if present)
if [ -x ./scripts/verify_gateway.sh ]; then
  ./scripts/verify_gateway.sh 1>&2
fi

# Run lobster tool via agent
out="$(openclaw agent --agent main --json --timeout 60 \
  --message 'Usá la herramienta lobster. action="run". pipeline="exec --shell \"echo OK\"". Devolveme SOLO el JSON.' \
  2>&1 || true)"

# Parse both layers:
# 1) outer OpenClaw JSON
# 2) inner lobster envelope inside payloads[].text
if printf "%s" "$out" | node -e '
const fs = require("fs");
const raw = fs.readFileSync(0, "utf8");
const i = raw.indexOf("{");
const j = raw.lastIndexOf("}");
if (i < 0 || j <= i) process.exit(1);
let outer;
try {
  outer = JSON.parse(raw.slice(i, j + 1));
} catch {
  process.exit(1);
}

const payloads = Array.isArray(outer?.result?.payloads)
  ? outer.result.payloads
  : (Array.isArray(outer?.payloads) ? outer.payloads : []);
const firstText = String(payloads?.[0]?.text || "");

let inner;
try {
  inner = JSON.parse(firstText);
} catch {
  process.exit(1);
}

const ok = inner?.ok === true;
const status = String(inner?.status || "");
const outArr = Array.isArray(inner?.output) ? inner.output.map(String) : [];
if (!ok) process.exit(1);
if (status !== "ok" && status !== "needs_approval") process.exit(1);
if (!outArr.includes("OK")) process.exit(1);
'; then
  echo "LOBSTER_OK"
  exit 0
fi

echo "LOBSTER_FAIL" >&2
echo "$out" >&2
exit 1
