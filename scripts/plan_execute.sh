#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.openclaw/bin:$PATH"

if [ "${1:-}" = "check" ]; then
  openclaw agent --help >/dev/null
  echo "PLAN_EXECUTE_OK"
  exit 0
fi

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <task-text>" >&2
  echo "       $0 check" >&2
  exit 2
fi

task="$*"

planner_prompt="Actua como planner. Para esta tarea: '$task'. Devolve SOLO JSON con keys: objective, steps (array de strings), risks (array), success_criteria (array)."
plan_json="$(openclaw agent --agent main --json --timeout 120 --message "$planner_prompt" 2>&1 || true)"

echo "== planner ==" >&2
printf "%s\n" "$plan_json"

executor_prompt="Usa el siguiente plan (si viene JSON extraelo) y ejecuta SOLO el primer paso de forma segura. Luego responde con JSON: {done:boolean, evidence:string, next_step:string}. Plan raw: $plan_json"
exec_json="$(openclaw agent --agent main --json --timeout 120 --message "$executor_prompt" 2>&1 || true)"

echo "== executor ==" >&2
printf "%s\n" "$exec_json"
