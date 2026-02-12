#!/usr/bin/env bash
set -euo pipefail

CFG="$HOME/.openclaw/openclaw.json"

if [ ! -f "$CFG" ]; then
  echo "FAIL: config not found at $CFG" >&2
  exit 1
fi

node - "$CFG" <<'NODE'
const fs = require("fs");
const cfg = process.argv[2];
const raw = fs.readFileSync(cfg, "utf8");
const j = JSON.parse(raw);

j.agents = j.agents || {};
j.agents.list = Array.isArray(j.agents.list) ? j.agents.list : [];

let main = j.agents.list.find((a) => a && a.id === "main");
if (!main) {
  main = { id: "main" };
  j.agents.list.push(main);
}

main.tools = main.tools || {};
main.tools.allow = [
  "read",
  "edit",
  "write",
  "exec",
  "process",
  "browser",
  "canvas",
  "nodes",
  "cron",
  "message",
  "tts",
  "gateway",
  "agents_list",
  "sessions_list",
  "sessions_history",
  "sessions_send",
  "sessions_spawn",
  "session_status",
  "web_search",
  "web_fetch",
  "lobster",
  "llm-task",
  "memory_search",
  "memory_get",
  "whatsapp_login"
];
main.tools.deny = [];

const bak = cfg + ".bak_" + new Date().toISOString().replace(/[:.]/g, "-");
fs.writeFileSync(bak, raw);
fs.writeFileSync(cfg, JSON.stringify(j, null, 2) + "\n");

console.error("mode=full");
console.error("patched:", cfg);
console.error("backup :", bak);
console.log("main.tools.allow =", JSON.stringify(main.tools.allow));
NODE
