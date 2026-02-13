# Infra Handoff (Headless n8n)

## Local URLs
- n8n: `http://127.0.0.1:5678`
- n8n health: `http://127.0.0.1:5678/healthz`
- Antigravity: `http://127.0.0.1:5000`
- Antigravity health: `http://127.0.0.1:5000/healthz`
- SearXNG: `http://127.0.0.1:8080`

## One-command lifecycle
- Bring up all services + smoke: `./scripts/bringup_all.sh`
- Bring up + stress matrix: `RUN_STRESS=true ./scripts/bringup_all.sh`
- Teardown (keep data): `./scripts/teardown_all.sh`
- Teardown + delete volumes: `WITH_VOLUMES=true ./scripts/teardown_all.sh`

## Webhook operations (no UI)
- Inventory + collision check: `./scripts/n8n_webhook_inventory.sh`
- Trigger `Test_Manos` and verify execution result in SQLite:
  - `./scripts/n8n_run_and_check.sh`
- Full smoke suite:
  - `./scripts/webhook_smoke.sh`

## Test_Manos / Antigravity wiring
- n8n env var in compose: `ANTIGRAVITY_URL=http://127.0.0.1:5000`
- `Test_Manos` HTTP node URL parameterized as:
  - `={{$env.ANTIGRAVITY_URL}}/execute`
- Re-apply parametrization if needed:
  - `./scripts/n8n_set_antigravity_url.sh && docker compose restart n8n`

## Backup / Restore
- Manual backup: `./scripts/n8n_backup.sh`
- Red button restore (latest backup): `./scripts/n8n_red_button_restore.sh`
- Restore explicit backup:
  - `BACKUP_DIR=./backups/n8n/<timestamp> ./scripts/n8n_red_button_restore.sh`
- Restore DRY RUN:
  - `DRY_RUN=true ./scripts/n8n_red_button_restore.sh`
- Restore with rollback if smoke fails (default):
  - `RUN_SMOKE=true ROLLBACK_ON_FAIL=true ./scripts/n8n_red_button_restore.sh`

## Stress tests
- Matrix (health + real webhooks): `./scripts/n8n_stress_matrix.sh`
- Custom stress:
  - `URL=http://127.0.0.1:5678/webhook/lucy-input METHOD=POST REQUEST_BODY='{"text":"stress"}' N=1000 P=25 ./scripts/n8n_stress.sh`

## Automated daily backup (systemd user timer)
- Install timer:
  - `./scripts/install_backup_timer.sh`
- Verify timer:
  - `systemctl --user list-timers n8n-backup.timer --no-pager`

## Final verification checklist
- `./scripts/bringup_all.sh` -> `BRINGUP=PASS`
- `./scripts/n8n_stress_matrix.sh` -> all scenarios PASS
- `DRY_RUN=true ./scripts/n8n_red_button_restore.sh` -> dry run OK
- `./scripts/webhook_smoke.sh` -> `SMOKE=PASS`
