#!/usr/bin/env bash
set -euo pipefail

store="${GOALS_FILE:-DOCS/GOALS.jsonl}"
interval="${GOALS_WORKER_INTERVAL:-3}"
loops="${GOALS_WORKER_LOOPS:-5}"
mkdir -p DOCS/RUNS "$(dirname "$store")"

cmd="${1:-check}"

next_goal() {
  GOALS_FILE="$store" ./scripts/goals_queue.sh next
}

mark_done() {
  id="$1"
  GOALS_FILE="$store" ./scripts/goals_queue.sh done "$id" >/dev/null || true
}

run_once() {
  row="$(next_goal)"
  [ "$row" = "NO_TODO" ] && { echo "NO_TODO"; return 0; }

  id="$(printf "%s" "$row" | python3 -c 'import json,sys; o=json.loads(sys.stdin.read()); print(o.get("id",""))')"
  goal="$(printf "%s" "$row" | python3 -c 'import json,sys; o=json.loads(sys.stdin.read()); print(o.get("goal",""))')"

  ts="$(date +%Y%m%d_%H%M%S)"
  log="DOCS/RUNS/goal_${id}_${ts}.log"

  {
    echo "== goal =="
    echo "id=$id"
    echo "goal=$goal"
    echo "== profile =="
    ./scripts/task_profile.sh classify "$goal"
    echo "== execution =="
    ./scripts/model_router.sh ask "$goal"
  } >"$log" 2>&1 || true

  mark_done "$id"
  echo "DONE:$id:$log"
}

case "$cmd" in
  check)
    [ -x ./scripts/goals_queue.sh ]
    [ -x ./scripts/model_router.sh ]
    [ -x ./scripts/task_profile.sh ]
    echo "GOALS_WORKER_OK"
    ;;
  once)
    run_once
    ;;
  run)
    i=0
    while [ "$i" -lt "$loops" ]; do
      run_once || true
      i=$((i+1))
      sleep "$interval"
    done
    echo "GOALS_WORKER_DONE loops=$loops"
    ;;
  *)
    echo "usage: $0 {check|once|run}" >&2
    exit 2
    ;;
esac
