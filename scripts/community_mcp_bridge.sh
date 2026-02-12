#!/usr/bin/env bash
set -euo pipefail

NAMES=(
  community-office-word
  community-arxiv
  community-browserbase
  community-cloudflare
  community-exa
  community-firecrawl
  community-github
  community-excel
  community-n8n
  community-notion
)

need_bin() {
  local bin="$1"
  command -v "$bin" >/dev/null 2>&1 || {
    echo "FAIL: missing required binary '$bin'" >&2
    exit 1
  }
}

setup_bridge() {
  need_bin mcporter
  need_bin npx
  need_bin uvx

  for name in "${NAMES[@]}"; do
    mcporter config remove "$name" >/dev/null 2>&1 || true
  done

  mcporter config add community-office-word --command uvx --arg office-word-mcp-server --scope home
  mcporter config add community-arxiv --command uvx --arg arxiv-mcp-server --scope home
  mcporter config add community-browserbase --command npx --arg -y --arg @browserbasehq/mcp-server-browserbase --scope home
  mcporter config add community-cloudflare --url https://docs.mcp.cloudflare.com/mcp --scope home
  mcporter config add community-exa --url https://mcp.exa.ai/mcp --scope home
  mcporter config add community-firecrawl --command npx --arg -y --arg firecrawl-mcp --env FIRECRAWL_API_KEY=${FIRECRAWL_API_KEY:-} --scope home
  mcporter config add community-github --url https://api.githubcopilot.com/mcp/ --scope home
  mcporter config add community-excel --command uvx --arg excel-mcp-server --arg stdio --scope home
  mcporter config add community-n8n --command npx --arg -y --arg @leonardsellem/n8n-mcp-server --env N8N_API_URL=${N8N_API_URL:-} --env N8N_API_KEY=${N8N_API_KEY:-} --scope home
  mcporter config add community-notion --command npx --arg -y --arg @notionhq/notion-mcp-server --env NOTION_API_KEY=${NOTION_API_KEY:-} --scope home

  echo "COMMUNITY_MCP_BRIDGE_SETUP_OK count=10"
}

check_bridge() {
  need_bin mcporter
  local count
  count="$(mcporter config list community- --json | jq -r '.servers | length')"
  if [ "$count" != "10" ]; then
    echo "FAIL: expected 10 bridge servers, got $count" >&2
    exit 2
  fi
  echo "COMMUNITY_MCP_BRIDGE_OK count=10"
}

list_bridge() {
  need_bin mcporter
  mcporter config list community- --json | jq -r '.servers[] | [.name,.transport,(.baseUrl // .command)] | @tsv'
}

probe_bridge() {
  need_bin mcporter
  local out="${1:-DOCS/RUNS/community_mcp_bridge_probe_$(date +%Y%m%d_%H%M%S).log}"
  mkdir -p "$(dirname "$out")"
  : > "$out"

  local ok fail
  ok=0
  fail=0
  for name in "${NAMES[@]}"; do
    echo "=== $name ===" | tee -a "$out"
    if timeout 45s mcporter list "$name" --schema --json >>"$out" 2>&1; then
      ok=$((ok + 1))
      echo "OK $name" | tee -a "$out"
    else
      fail=$((fail + 1))
      echo "FAIL $name" | tee -a "$out"
    fi
    echo >> "$out"
  done

  echo "COMMUNITY_MCP_BRIDGE_PROBE_OK ok=$ok fail=$fail log=$out"
}

demo_call() {
  need_bin mcporter
  mcporter call community-cloudflare.search_cloudflare_documentation \
    --args '{"query":"What is Cloudflare Workers?"}' --json
}

usage() {
  cat <<'EOF'
Usage:
  ./scripts/community_mcp_bridge.sh setup
  ./scripts/community_mcp_bridge.sh check
  ./scripts/community_mcp_bridge.sh list
  ./scripts/community_mcp_bridge.sh probe [log_path]
  ./scripts/community_mcp_bridge.sh demo
EOF
}

main() {
  local cmd="${1:-check}"
  case "$cmd" in
    setup) setup_bridge ;;
    check) check_bridge ;;
    list) list_bridge ;;
    probe) probe_bridge "${2:-}" ;;
    demo) demo_call ;;
    -h|--help|help) usage ;;
    *)
      usage >&2
      exit 64
      ;;
  esac
}

main "$@"
