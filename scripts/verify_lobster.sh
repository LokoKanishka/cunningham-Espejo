#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.openclaw/bin:$PATH"

echo "== verify lobster ==" >&2

lobster_bin="$(command -v lobster || true)"
if [ -z "$lobster_bin" ]; then
  echo "FAIL: lobster binary not found in PATH" >&2
  exit 1
fi

echo "lobster_bin=$lobster_bin" >&2

plugins_out="$(openclaw plugins list 2>&1 || true)"
printf "%s\n" "$plugins_out" | grep -Eiq 'lobster.*\bloaded\b' || {
  echo "FAIL: lobster plugin is not loaded" >&2
  exit 2
}

# Expect a resumable approval envelope with token.
run_out="$(lobster run --mode tool 'exec --json --shell "echo [1]" | approve --prompt "verify"' 2>&1 || true)"

printf "%s" "$run_out" | node -e '
const fs = require("fs");
const out = fs.readFileSync(0, "utf8");
const i = out.indexOf("{");
const j = out.lastIndexOf("}");
if (i < 0 || j <= i) {
  console.error("FAIL: no JSON object found in lobster output");
  console.error(out.slice(0, 1200));
  process.exit(3);
}
let env;
try {
  env = JSON.parse(out.slice(i, j + 1));
} catch (e) {
  console.error("FAIL: cannot parse lobster envelope");
  console.error(String(e));
  process.exit(4);
}

const ok = env?.ok === true;
const status = String(env?.status || "");
const token = String(env?.requiresApproval?.resumeToken || "");
console.error(`envelope_ok=${ok}`);
console.error(`status=${status}`);
console.error(`resumeToken_present=${token.length > 0}`);

if (!ok) {
  console.error("FAIL: lobster envelope not ok");
  process.exit(5);
}
if (status !== "needs_approval" && status !== "ok") {
  console.error("FAIL: unexpected lobster status");
  process.exit(6);
}
if (status === "needs_approval" && !token) {
  console.error("FAIL: needs_approval without resumeToken");
  process.exit(7);
}
'

echo "OK" >&2
