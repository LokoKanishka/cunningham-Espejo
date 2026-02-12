#!/usr/bin/env bash
set -euo pipefail

echo "== verify_gateway ==" >&2
./scripts/verify_gateway.sh
echo "== verify_plugins ==" >&2
./scripts/verify_plugins.sh 1>&2
echo "== verify_lobster ==" >&2
./scripts/verify_lobster.sh 1>&2

echo "== verify_capabilities ==" >&2
./scripts/verify_capabilities.sh 1>&2

echo "== verify_codex_subscription ==" >&2
./scripts/verify_codex_subscription.sh

echo "== verify_security_audit ==" >&2
./scripts/verify_security_audit.sh

echo "== verify_community_mcp ==" >&2
./scripts/community_mcp.sh check 1>&2

echo "ALL_OK" >&2
