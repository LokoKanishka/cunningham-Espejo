#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "check" ]; then
  git rev-parse --is-inside-work-tree >/dev/null
  echo "GIT_AUTOPILOT_OK"
  exit 0
fi

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <branch-slug> <commit-message> [paths...]" >&2
  echo "       $0 check" >&2
  exit 2
fi

branch="$1"
shift
msg="$1"
shift

git rev-parse --is-inside-work-tree >/dev/null

if ! git rev-parse --verify "$branch" >/dev/null 2>&1; then
  git checkout -b "$branch"
else
  git checkout "$branch"
fi

if [ "$#" -gt 0 ]; then
  git add "$@"
else
  git add -A
fi

git commit -m "$msg"
echo "COMMIT_DONE"
