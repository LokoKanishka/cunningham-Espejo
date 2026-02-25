# Infra Handoff (Headless n8n) - v0.2

## Local URLs
- n8n: `http://127.0.0.1:5678`
- n8n health: `http://127.0.0.1:5678/healthz`
- n8n metrics: `http://127.0.0.1:5678/metrics`
- Antigravity: `http://127.0.0.1:5000`
- Antigravity health: `http://127.0.0.1:5000/healthz`
- SearXNG: `http://127.0.0.1:8080`
- Prometheus (optional profile): `http://127.0.0.1:9090`

## One-command lifecycle
- Bring up all services + full smoke:
  - `./scripts/bringup_all.sh`
- Bring up + stress matrix:
  - `RUN_STRESS=true ./scripts/bringup_all.sh`
- Teardown (keep data):
  - `./scripts/teardown_all.sh`
- Teardown + delete volumes:
  - `WITH_VOLUMES=true ./scripts/teardown_all.sh`

## Gateway Contract v1
- Schemas:
  - `contracts/lucy_input_v1.schema.json`
  - `contracts/lucy_ack_v1.schema.json` (ACK webhook)
  - `contracts/lucy_output_v1.schema.json` (outbox envelope)
- Rules/examples:
  - `contracts/README.md`
- Validate any JSON against schema:
  - `python3 scripts/contract_validate.py contracts/lucy_input_v1.schema.json <json_file>`

## Lucy Input Gateway (headless patch)
- Patch/import workflow via CLI (no UI):
  - `./scripts/n8n_patch_lucy_gateway_v1.sh`
- Probe contract and persist request/response artifacts:
  - `./scripts/lucy_input_contract_probe.sh`
- Contract smoke:
  - `./scripts/webhook_contract_smoke.sh`
- End-to-end gateway check (ACK + IPC file):
  - `./scripts/n8n_gateway_e2e.sh`
  - Verifica `inbox` y compatibilidad `payloads` en runtime.
- Outbox patch headless:
  - `./scripts/n8n_patch_lucy_outbox_v1.sh`

## IPC envelope and layout
- Envelope spec:
  - `ipc/envelopes/v1.md`
- Initialize layout:
  - `./scripts/ipc_layout_init.sh`
- Paths used by gateway:
  - `/data/lucy_ipc/inbox`
  - `/data/lucy_ipc/outbox`
  - `/data/lucy_ipc/deadletter`
  - outbox canonical naming: `/data/lucy_ipc/outbox/<correlation_id>.json`
  - legacy compatibility: `/data/lucy_ipc/outbox/res_<correlation_id>.json`
  - compat runtime observed: `/data/lucy_ipc/payloads`
- Quick watcher:
  - `./scripts/ipc_tail.sh ./ipc/inbox`

## Webhook operations (no UI)
- Inventory + active conflict detection:
  - `STRICT_CONFLICTS=true ./scripts/n8n_webhook_inventory.sh`
- Trigger `Test_Manos` and assert success in SQLite:
  - `./scripts/n8n_run_and_check.sh`
- Full smoke suite:
  - `./scripts/webhook_smoke.sh`

## Stress matrix
- Run all scenarios (health + real webhooks):
  - `./scripts/n8n_stress_matrix.sh`
- Raw artifacts in `_stress/` are endpoint-labeled, e.g.:
  - `raw_lucy-input_*`
  - `summary_test-manos_*`

## Observability
- Health checks:
  - `curl -sS -i http://127.0.0.1:5678/healthz`
  - `curl -sS -i http://127.0.0.1:5000/healthz`
- Metrics snapshot:
  - `./scripts/metrics_snapshot.sh`
- Metrics snapshot artifacts:
  - `_stress/metrics_snapshots/`
- Optional Prometheus profile:
  - `docker compose --profile observability up -d prometheus`

## UI panels (local-only)
- Dockge stack operations: `http://127.0.0.1:5001`
- Lucy Panel (functional gateway UI): `http://127.0.0.1:5100`
- Lucy Panel docs: `docs/LUCY_UI_PANEL.md`

## Backup / Restore / DR
- Backup (rotating, with checksums):
  - `./scripts/n8n_backup.sh`
- Red button restore (with smoke + rollback):
  - `./scripts/n8n_red_button_restore.sh`
- Restore dry run:
  - `DRY_RUN=true ./scripts/n8n_red_button_restore.sh`
- Full DR drill (backup -> simulated wipe -> restore -> smoke):
  - `./scripts/dr_drill.sh`

## Antigravity URL in Test_Manos
- Normalization script:
  - `./scripts/n8n_set_antigravity_url.sh`
- Default mode uses hardcoded URL (`http://127.0.0.1:5000/execute`) to avoid blocked env access in node expressions.
- Optional env mode:
  - `URL_MODE=env ./scripts/n8n_set_antigravity_url.sh`

## Automated daily backup (systemd user timer)
- Install/update timer:
  - `./scripts/install_backup_timer.sh`
- Verify timer:
  - `systemctl --user list-timers n8n-backup.timer --no-pager`
- Logs:
  - `journalctl --user -u n8n-backup.service -n 50 --no-pager`

## Resume checklist
1. `./scripts/bringup_all.sh`
2. `./scripts/webhook_smoke.sh`
3. `./scripts/n8n_stress_matrix.sh`
4. `./scripts/dr_drill.sh`
