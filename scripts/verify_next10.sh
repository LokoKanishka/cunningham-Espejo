#!/usr/bin/env bash
set -euo pipefail

scripts=(
  scripts/gateway_autoheal.sh
  scripts/task_profile.sh
  scripts/model_router.sh
  scripts/local_vision.sh
  scripts/diff_intel.sh
  scripts/autotest_gen.sh
  scripts/runbook.sh
  scripts/policy_engine.sh
  scripts/adr_bot.sh
  scripts/ops_dashboard.sh
  scripts/goals_worker.sh
  scripts/ops_alerts.sh
  scripts/web_research.sh
)

for s in "${scripts[@]}"; do
  [ -x "$s" ] || { echo "FAIL: missing exec $s" >&2; exit 1; }
  echo "OK: $s" >&2
done

./scripts/gateway_autoheal.sh check >/dev/null
./scripts/task_profile.sh check >/dev/null
./scripts/model_router.sh check >/dev/null
./scripts/local_vision.sh check >/dev/null
./scripts/diff_intel.sh check >/dev/null
./scripts/autotest_gen.sh check >/dev/null
./scripts/runbook.sh check >/dev/null
./scripts/policy_engine.sh check >/dev/null
./scripts/adr_bot.sh check >/dev/null
./scripts/goals_worker.sh check >/dev/null
./scripts/ops_alerts.sh check >/dev/null
./scripts/web_research.sh check >/dev/null

out="$(./scripts/ops_dashboard.sh)"
printf "%s\n" "$out" | grep -q '^DASHBOARD_OK:' || { echo "FAIL: dashboard" >&2; exit 1; }

echo "NEXT10_OK"
