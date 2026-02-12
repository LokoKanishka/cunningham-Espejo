#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"
m="openai-codex/gpt-5.1"
openclaw models set "$m" 1>&2
openclaw agent --agent main --message "/new $m" --json --timeout 120 >/dev/null 2>&1 || true
openclaw models status 1>&2
