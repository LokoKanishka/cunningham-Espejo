#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-./ipc}"
mkdir -p "$BASE/inbox" "$BASE/outbox" "$BASE/deadletter"
touch "$BASE/inbox/.keep" "$BASE/outbox/.keep" "$BASE/deadletter/.keep"
echo "IPC_LAYOUT=OK base=$BASE"
