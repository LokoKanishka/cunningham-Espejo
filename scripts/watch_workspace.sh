#!/usr/bin/env bash
set -euo pipefail

root="${1:-$PWD}"
mode="${2:-watch}"

if [ "$mode" = "check" ]; then
  if command -v inotifywait >/dev/null 2>&1; then
    echo "WATCHER_OK:inotify"
  else
    echo "WATCHER_OK:polling"
  fi
  exit 0
fi

if command -v inotifywait >/dev/null 2>&1; then
  echo "watching (inotify): $root" >&2
  inotifywait -mr -e create,modify,delete,move --format '%T %w%f %e' --timefmt '%F %T' "$root"
else
  echo "watching (polling): $root" >&2
  prev="$(find "$root" -type f -printf '%P %T@\n' | sort | sha1sum | awk '{print $1}')"
  while true; do
    sleep 2
    now="$(find "$root" -type f -printf '%P %T@\n' | sort | sha1sum | awk '{print $1}')"
    if [ "$now" != "$prev" ]; then
      echo "$(date '+%F %T') change-detected $root"
      prev="$now"
    fi
  done
fi
