#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

out="${1:-DOCS/ops_dashboard.html}"
mkdir -p "$(dirname "$out")"

health="DOWN"
if openclaw health >/dev/null 2>&1; then health="UP"; fi

plugins="$(openclaw plugins list 2>/dev/null | sed -n '1,40p' | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"
status="$(openclaw status 2>/dev/null | sed -n '1,120p' | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"
community="$(./scripts/community_mcp.sh check 2>/dev/null | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"
bridge="COMMUNITY_MCP_BRIDGE_UNAVAILABLE"
if [ -x "./scripts/community_mcp_bridge.sh" ]; then
  bridge="$(./scripts/community_mcp_bridge.sh check 2>/dev/null || echo COMMUNITY_MCP_BRIDGE_NOT_CONFIGURED)"
  bridge="$(printf "%s" "$bridge" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')"
fi

health_badge="bg-red-lt text-red"
if [ "$health" = "UP" ]; then
  health_badge="bg-green-lt text-green"
fi

cat > "$out" <<HTML
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenClaw Ops Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/@tabler/core@1.4.0/dist/css/tabler.min.css" rel="stylesheet">
  <style>
    :root {
      --brand-1: #0f172a;
      --brand-2: #0b3b5e;
      --brand-3: #14532d;
      --panel-bg: rgba(8, 16, 30, 0.85);
    }
    body {
      font-family: "Space Grotesk", sans-serif;
      background:
        radial-gradient(1200px 600px at -10% -20%, rgba(20, 83, 45, 0.35), transparent 60%),
        radial-gradient(1200px 600px at 110% -10%, rgba(11, 59, 94, 0.45), transparent 60%),
        linear-gradient(140deg, var(--brand-1), #05080f);
      min-height: 100vh;
    }
    .page {
      max-width: 1200px;
      margin: 2rem auto;
      padding: 0 1rem;
    }
    .hero {
      border: 1px solid rgba(255, 255, 255, 0.12);
      background: linear-gradient(135deg, rgba(20, 83, 45, 0.22), rgba(11, 59, 94, 0.25));
      backdrop-filter: blur(8px);
    }
    .panel {
      background: var(--panel-bg);
      border: 1px solid rgba(255, 255, 255, 0.1);
      box-shadow: 0 10px 35px rgba(0, 0, 0, 0.35);
    }
    .kpi-value {
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: 0.01em;
    }
    pre {
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      margin: 0;
      max-height: 460px;
      overflow: auto;
    }
    .fade-in {
      animation: fadeInUp 460ms ease both;
    }
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="card hero p-4 p-md-5 mb-4 fade-in">
      <div class="d-flex flex-wrap align-items-center justify-content-between gap-3">
        <div>
          <div class="text-uppercase text-secondary fw-bold mb-1">OpenClaw Runtime</div>
          <h1 class="m-0">Ops Dashboard</h1>
        </div>
        <div class="badge $health_badge fs-4 px-3 py-2">Gateway $health</div>
      </div>
      <div class="text-secondary mt-3">Generado: $(date -Is)</div>
    </div>

    <div class="row g-3 mb-3 fade-in">
      <div class="col-12 col-md-4">
        <div class="card panel p-3 h-100">
          <div class="text-secondary text-uppercase fw-bold mb-2">Estado Gateway</div>
          <div class="kpi-value">$health</div>
        </div>
      </div>
      <div class="col-12 col-md-4">
        <div class="card panel p-3 h-100">
          <div class="text-secondary text-uppercase fw-bold mb-2">Community MCP (20)</div>
          <div class="kpi-value">${community:-COMMUNITY_MCP_UNAVAILABLE}</div>
        </div>
      </div>
      <div class="col-12 col-md-4">
        <div class="card panel p-3 h-100">
          <div class="text-secondary text-uppercase fw-bold mb-2">Bridge MCP (Top10)</div>
          <div class="kpi-value">${bridge}</div>
        </div>
      </div>
    </div>

    <div class="card panel mb-3 fade-in">
      <div class="card-header">
        <h3 class="card-title m-0">Status</h3>
      </div>
      <div class="card-body"><pre>$status</pre></div>
    </div>

    <div class="card panel mb-3 fade-in">
      <div class="card-header">
        <h3 class="card-title m-0">Plugins</h3>
      </div>
      <div class="card-body"><pre>$plugins</pre></div>
    </div>
  </div>
</body>
</html>
HTML

echo "DASHBOARD_OK:$out"
