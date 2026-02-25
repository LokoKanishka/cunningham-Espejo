# Bitácora Operativa (2026-02-12)

## Objetivo del día
Blindar n8n para uso local/offline, evitar costos variables, dejar pruebas de estrés y runbooks de backup/restore.

## Qué se hizo (confirmado)
- n8n quedó `local-only`:
  - listeners: `127.0.0.1:5678` y `127.0.0.1:5679`
  - no más `*:5678`
- Compose de `infra` endurecido:
  - imagen pinneada: `n8nio/n8n:2.4.4`
  - `N8N_LISTEN_ADDRESS=127.0.0.1`
  - `N8N_DIAGNOSTICS_ENABLED=false`
  - `N8N_VERSION_NOTIFICATIONS_ENABLED=false`
  - `N8N_TEMPLATES_ENABLED=false`
  - `QUEUE_HEALTH_CHECK_ACTIVE=true`
  - `N8N_METRICS=true`
- Endpoints validados en `200`:
  - `/`, `/healthz`, `/healthz/readiness`, `/metrics`
- Stress testing listo y ejecutado:
  - scripts: `scripts/n8n_stress.sh`, `scripts/n8n_stress_matrix.sh`
  - matrix completa `PASS` (3 escenarios)
  - log consolidado: `~/Lucy_Workspace/infra/_stress/matrix_20260212_191452.log`
- Repo `~/Lucy_Workspace/infra` inicializado en Git:
  - root commit: `c9ecf3d`
  - commit backup/restore: `cb80b01`
- Runbooks operativos agregados:
  - `scripts/n8n_backup.sh`
  - `scripts/n8n_red_button_restore.sh`
  - `backups/` ignorado por Git

## Errores que aparecieron y cómo se corrigieron
- `curl` devolvía `000` tras `compose up -d`:
  - causa: race de arranque
  - corrección: retry con espera antes de validar endpoints
- harness rompía por quoting en heredoc Python (`"$RAW"` literal):
  - corrección: pasar rutas por variables de entorno (`RAW`, `SUMMARY`)
- warning de `xargs` por usar `-n` junto con `-I`:
  - corrección: quitar `-n1` y dejar `-I` + `-P`
- automatización UI (Playwright) no encontraba/ejecutaba por overlays:
  - corrección: selectores robustos y click forzado en botón execute

## No repetir (reglas)
- No usar `n8nio/n8n:latest` en entornos estables.
- No validar disponibilidad de n8n sin retry (esperar socket/HTTP).
- No commitear secretos ni backups de credenciales (`.env.n8n.local`, `backups/`).
- No asumir que UI refleja todo: confirmar también por consola/log/DB.
- En scripts con Python embebido, no interpolar paths con heredoc quoted; usar env vars.

## Comandos de referencia rápida
- Verificar estado n8n:
  - `ss -ltn | egrep ':(5678|5679)\\b'`
  - `docker logs --tail 100 lucy_brain_n8n`
- Stress matrix:
  - `cd ~/Lucy_Workspace/infra && URL=http://127.0.0.1:5678/healthz ./scripts/n8n_stress_matrix.sh`
- Backup:
  - `cd ~/Lucy_Workspace/infra && ./scripts/n8n_backup.sh`
- Restore (ensayo seguro):
  - `cd ~/Lucy_Workspace/infra && DRY_RUN=true ./scripts/n8n_red_button_restore.sh`

## Estado pendiente abierto
- Workflow `Test_Manos` ejecuta pero falla en nodo `Antigravity (Cálculo)` con:
  - `The service refused the connection - perhaps it is offline`
  - probable causa: servicio destino en `http://127.0.0.1:5000/execute` no disponible.
