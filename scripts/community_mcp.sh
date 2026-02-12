#!/usr/bin/env bash
set -euo pipefail

CATALOG="${CATALOG:-DOCS/community_mcp_catalog.json}"
ROOT="${COMMUNITY_ROOT:-community/mcp/repos}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/community_mcp.sh list
  ./scripts/community_mcp.sh check
  ./scripts/community_mcp.sh sync

Env:
  CATALOG        Path to catalog JSON (default: DOCS/community_mcp_catalog.json)
  COMMUNITY_ROOT Download dir for repositories (default: community/mcp/repos)
EOF
}

need_tools() {
  command -v jq >/dev/null 2>&1 || { echo "FAIL: jq not found" >&2; exit 1; }
  command -v curl >/dev/null 2>&1 || { echo "FAIL: curl not found" >&2; exit 1; }
  command -v tar >/dev/null 2>&1 || { echo "FAIL: tar not found" >&2; exit 1; }
}

check_catalog() {
  [ -f "$CATALOG" ] || { echo "FAIL: missing catalog $CATALOG" >&2; exit 2; }

  local count unique names_ok commits_ok
  count="$(jq -r '.repos | length' "$CATALOG")"
  unique="$(jq -r '[.repos[].full_name] | unique | length' "$CATALOG")"
  names_ok="$(jq -r '[.repos[].full_name | test("^[^/]+/[^/]+$")] | all' "$CATALOG")"
  commits_ok="$(jq -r '[.repos[].pinned_ref.commit | test("^[0-9a-f]{40}$")] | all' "$CATALOG")"

  [ "$count" = "20" ] || { echo "FAIL: expected 20 repos, got $count" >&2; exit 3; }
  [ "$unique" = "$count" ] || { echo "FAIL: duplicate repos in catalog" >&2; exit 3; }
  [ "$names_ok" = "true" ] || { echo "FAIL: invalid repo name format in catalog" >&2; exit 3; }
  [ "$commits_ok" = "true" ] || { echo "FAIL: invalid commit hash in catalog" >&2; exit 3; }
}

cmd_list() {
  check_catalog
  jq -r '.repos[] | "\(.full_name)\t\(.stars)\t\(.license)\t\(.pinned_ref.commit)"' "$CATALOG"
}

cmd_sync() {
  check_catalog
  mkdir -p "$ROOT"

  local total updated skipped
  total=0
  updated=0
  skipped=0

  while IFS= read -r item; do
    total=$((total + 1))

    local full_name commit safe_name dst marker tmpdir archive_url
    full_name="$(printf "%s" "$item" | jq -r '.full_name')"
    commit="$(printf "%s" "$item" | jq -r '.pinned_ref.commit')"
    safe_name="${full_name//\//__}"
    dst="$ROOT/$safe_name"
    marker="$dst/.community_source.json"
    archive_url="https://codeload.github.com/$full_name/tar.gz/$commit"

    if [ -f "$marker" ] && [ "$(jq -r '.pinned_commit' "$marker" 2>/dev/null || true)" = "$commit" ]; then
      skipped=$((skipped + 1))
      continue
    fi

    tmpdir="$(mktemp -d)"
    curl -fsSL "$archive_url" -o "$tmpdir/repo.tgz"
    tar -xzf "$tmpdir/repo.tgz" -C "$tmpdir"

    rm -rf "$dst"
    mkdir -p "$dst"
    cp -a "$tmpdir"/*/./ "$dst/"

    jq -n \
      --arg full_name "$full_name" \
      --arg commit "$commit" \
      --arg archive_url "$archive_url" \
      --arg synced_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{
        source: "community",
        full_name: $full_name,
        pinned_commit: $commit,
        archive_url: $archive_url,
        synced_at: $synced_at
      }' > "$marker"

    rm -rf "$tmpdir"
    updated=$((updated + 1))
  done < <(jq -c '.repos[]' "$CATALOG")

  echo "COMMUNITY_MCP_SYNC_OK total=$total updated=$updated skipped=$skipped root=$ROOT"
}

cmd_check() {
  check_catalog

  local downloaded
  downloaded=0
  if [ -d "$ROOT" ]; then
    downloaded="$(find "$ROOT" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
  fi
  echo "COMMUNITY_MCP_OK catalog=20 downloaded=$downloaded root=$ROOT"
}

main() {
  need_tools
  local cmd="${1:-check}"
  case "$cmd" in
    list) cmd_list ;;
    sync) cmd_sync ;;
    check) cmd_check ;;
    -h|--help|help) usage ;;
    *)
      usage >&2
      exit 64
      ;;
  esac
}

main "$@"
