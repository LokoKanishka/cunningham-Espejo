#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

if command -v tmux >/dev/null 2>&1; then
  session="openclaw-pro"
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux attach -t "$session"
    exit 0
  fi

  tmux new-session -d -s "$session" -n monitor 'cd /home/lucy-ubuntu/Escritorio/cunningham && while true; do clear; echo "== verify_gateway =="; ./scripts/verify_gateway.sh || true; echo; echo "== date =="; date -Is; sleep 3; done'
  tmux split-window -h -t "$session":monitor 'export PATH="$HOME/.openclaw/bin:$PATH"; while true; do clear; echo "== openclaw status =="; openclaw status || true; sleep 5; done'
  tmux split-window -v -t "$session":monitor.1 'export PATH="$HOME/.openclaw/bin:$PATH"; openclaw logs --follow --plain --limit 120'
  tmux select-pane -t "$session":monitor.0
  tmux set-option -t "$session" -g mouse on >/dev/null 2>&1 || true
  tmux attach -t "$session"
else
  echo "tmux no está instalado. Fallback:" >&2
  echo "1) ./scripts/verify_gateway.sh" >&2
  echo "2) openclaw status" >&2
  echo "3) openclaw logs --follow --plain --limit 120" >&2
fi
