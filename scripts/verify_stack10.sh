#!/usr/bin/env bash
set -euo pipefail

scripts=(
  scripts/memory_semantic.sh
  scripts/browser_vision.sh
  scripts/watch_workspace.sh
  scripts/plan_execute.sh
  scripts/lobster_approval.sh
  scripts/rpa_web_task.sh
  scripts/ops_observe.sh
  scripts/goals_queue.sh
  scripts/git_autopilot.sh
  scripts/knowledge_ingest.sh
)

for s in "${scripts[@]}"; do
  [ -x "$s" ] || { echo "FAIL: not executable $s" >&2; exit 1; }
  echo "OK: $s" >&2
done

action_tmp="DOCS/GOALS.verify.tmp.jsonl"
cleanup() {
  rm -f "$action_tmp"
}
trap cleanup EXIT
GOALS_FILE="$action_tmp" ./scripts/goals_queue.sh add "stack10 smoke" >/dev/null
GOALS_FILE="$action_tmp" ./scripts/goals_queue.sh next >/dev/null

./scripts/memory_semantic.sh check >/dev/null
./scripts/browser_vision.sh probe >/dev/null
./scripts/watch_workspace.sh . check >/dev/null
./scripts/plan_execute.sh check >/dev/null
./scripts/lobster_approval.sh check >/dev/null
./scripts/rpa_web_task.sh check >/dev/null
./scripts/git_autopilot.sh check >/dev/null
./scripts/knowledge_ingest.sh --dry-run >/dev/null
ops_out="$(./scripts/ops_observe.sh)"
printf "%s\n" "$ops_out" | grep -q '^OPS_LOG=' || { echo "FAIL: ops_observe" >&2; exit 1; }

echo "STACK10_OK"
