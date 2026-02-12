#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-report}"
shift || true

case "$cmd" in
  report)
    echo "== git status =="
    git status -sb
    echo "== diff stat =="
    git diff --stat
    echo "== risk hints =="
    changed="$(git diff --name-only)"
    [ -z "$changed" ] && { echo "no local changes"; exit 0; }
    printf "%s\n" "$changed" | while read -r f; do
      case "$f" in
        *.sh) echo "MEDIUM: script changed -> validate shellcheck/manual" ;;
        *.json|*.yml|*.yaml) echo "MEDIUM: config changed -> validate parsing" ;;
        scripts/verify_*) echo "HIGH: verifier changed -> run verify_all" ;;
        *) echo "LOW: $f" ;;
      esac
    done
    ;;
  check)
    git rev-parse --is-inside-work-tree >/dev/null
    echo "DIFF_INTEL_OK"
    ;;
  *)
    echo "usage: $0 {report|check}" >&2
    exit 2
    ;;
esac
