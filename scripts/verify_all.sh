#!/usr/bin/env bash
set -euo pipefail

echo "== verify_gateway ==" >&2
./scripts/verify_gateway.sh

echo "== verify_codex_subscription ==" >&2
./scripts/verify_codex_subscription.sh

echo "== verify_security_audit ==" >&2
./scripts/verify_security_audit.sh

echo "ALL_OK" >&2
