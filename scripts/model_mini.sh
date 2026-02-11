#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"
openclaw models set openai-codex/gpt-5.1-codex-mini 1>&2
openclaw models status 1>&2
