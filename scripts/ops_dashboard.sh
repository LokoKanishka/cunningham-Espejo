#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

out="${1:-DOCS/ops_dashboard.html}"
mkdir -p "$(dirname "$out")"

health="DOWN"
if openclaw health >/dev/null 2>&1; then health="UP"; fi

plugins="$(openclaw plugins list 2>/dev/null | sed -n '1,40p' | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"
status="$(openclaw status 2>/dev/null | sed -n '1,120p' | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"

cat > "$out" <<HTML
<!doctype html>
<html><head><meta charset="utf-8"><title>Ops Dashboard</title>
<style>body{font-family:ui-monospace,monospace;background:#0b1020;color:#d6e2ff;padding:20px} .card{border:1px solid #2a3457;border-radius:8px;padding:12px;margin:10px 0;background:#111933} .ok{color:#74f3a6} pre{white-space:pre-wrap}</style>
</head><body>
<h1>OpenClaw Ops Dashboard</h1>
<div class="card">Gateway: <span class="ok">$health</span></div>
<div class="card"><h3>Status</h3><pre>$status</pre></div>
<div class="card"><h3>Plugins</h3><pre>$plugins</pre></div>
<div class="card">Generated: $(date -Is)</div>
</body></html>
HTML

echo "DASHBOARD_OK:$out"
