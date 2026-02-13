#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p "$HOME/.config/systemd/user"
cp systemd/n8n-backup.service "$HOME/.config/systemd/user/n8n-backup.service"
cp systemd/n8n-backup.timer "$HOME/.config/systemd/user/n8n-backup.timer"

systemctl --user daemon-reload
systemctl --user restart n8n-backup.service || true
systemctl --user enable --now n8n-backup.timer
systemctl --user list-timers n8n-backup.timer --no-pager
echo "logs: journalctl --user -u n8n-backup.service -n 50 --no-pager"
